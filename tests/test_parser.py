"""Real OS sandbox tests. Opt in when nested sandboxing is permitted."""

from io import BytesIO
import os
import subprocess

import pytest
from pypdf import PdfWriter
from pypdf.generic import DictionaryObject, NameObject, DecodedStreamObject

from app.parsing import parse_source
from app.policy import Rejected

pytestmark = pytest.mark.skipif(
    os.environ.get("TEST_PARSER_SANDBOX") != "1", reason="Opt in to OS parser sandbox tests"
)


def test_markdown_locators():
    assert parse_source(b"# Heading\n\nPolicy text.", ".md") == [
        {"text": "# Heading", "locator": "char:0 / Heading"},
        {"text": "Policy text.", "locator": "char:11 / Heading"},
    ]


def test_statement_schema():
    assert (
        parse_source(b'{"statement":"Approved scoped fact."}', ".json")[0]["text"] == "Approved scoped fact."
    )
    with pytest.raises(Rejected):
        parse_source(b'{"statement":"fact","instruction":"bypass"}', ".json")


def test_pdf_text_and_scanned_rejection():
    writer = PdfWriter()
    page = writer.add_blank_page(width=200, height=200)
    with pytest.raises(Rejected):
        stream = BytesIO()
        writer.write(stream)
        parse_source(stream.getvalue(), ".pdf")
    font = DictionaryObject(
        {
            NameObject("/Type"): NameObject("/Font"),
            NameObject("/Subtype"): NameObject("/Type1"),
            NameObject("/BaseFont"): NameObject("/Helvetica"),
        }
    )
    page[NameObject("/Resources")] = DictionaryObject(
        {NameObject("/Font"): DictionaryObject({NameObject("/F1"): writer._add_object(font)})}
    )
    content = DecodedStreamObject()
    content.set_data(b"BT /F1 12 Tf 10 100 Td (Synthetic policy text) Tj ET")
    page[NameObject("/Contents")] = writer._add_object(content)
    stream = BytesIO()
    writer.write(stream)
    assert "Synthetic policy text" in parse_source(stream.getvalue(), ".pdf")[0]["text"]


def test_sandbox_denies_unrelated_file_and_network(tmp_path, monkeypatch):
    # A canary outside the parser's allowed temporary directory, never a real secret.
    forbidden = tmp_path / "private-canary"
    forbidden.write_text("must-not-read")
    original = subprocess.run

    def run(command, **kwargs):
        output = command[-1]
        script, source = command[-3], command[-2]
        code = f"""import runpy,sys
sys.argv={command[-3:]!r}
runpy.run_path({script!r}, run_name="__main__")
import json,socket
from pathlib import Path
checks=[]
try:
 Path({source!r}).write_bytes(b"overwrite");checks.append("input-writable")
except (PermissionError, OSError): checks.append("input-readonly")
try:
 Path({str(forbidden)!r}).read_bytes();checks.append("file-allowed")
except PermissionError: checks.append("file-denied")
try:
 socket.create_connection(("127.0.0.1",9),timeout=1);checks.append("network-allowed")
except PermissionError: checks.append("network-denied")
Path({output!r}).write_text(json.dumps([{{"text":",".join(checks),"locator":"sandbox"}}]))
"""
        command = command[: command.index("-I") + 1] + ["-c", code]
        return original(command, **kwargs)

    monkeypatch.setattr(subprocess, "run", run)
    assert parse_source(b"x", ".md")[0]["text"] == "input-readonly,file-denied,network-denied"
