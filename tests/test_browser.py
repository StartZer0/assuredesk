"""Opt-in real-browser acceptance; synthetic data only, no model calls."""

import os
from pathlib import Path
import socket
import threading
import time

import pytest
from argon2 import PasswordHasher
import uvicorn

from app.config import Settings
from app.db import User
from app.web import create_app

pytestmark = pytest.mark.skipif(
    os.environ.get("TEST_BROWSER") != "1", reason="Opt into installed browser runtime"
)


def test_reviewer_export_preview_history_and_revocation(env):
    from playwright.sync_api import sync_playwright, expect

    with env.db.transaction() as s:
        for role in ("reviewer", "sales"):
            s.get(User, getattr(env, role)).password = PasswordHasher().hash("browser-test-password")
    app = create_app(Settings("sqlite://", secure_cookie=False), env.db, env.objects)
    sock = socket.socket()
    sock.bind(("127.0.0.1", 0))
    port = sock.getsockname()[1]
    server = uvicorn.Server(uvicorn.Config(app, log_level="error"))
    thread = threading.Thread(target=lambda: server.run(sockets=[sock]), daemon=True)
    thread.start()
    for _ in range(100):
        if server.started:
            break
        time.sleep(0.02)
    artifacts = Path("output/playwright")
    artifacts.mkdir(parents=True, exist_ok=True)
    try:
        with sync_playwright() as p:
            browser = p.chromium.launch()
            context = browser.new_context(
                viewport={"width": 1440, "height": 1000}, record_video_dir=str(artifacts)
            )
            page = context.new_page()
            errors = []
            page.on("pageerror", lambda e: errors.append(str(e)))
            page.goto(f"http://127.0.0.1:{port}")
            expect(page.get_by_role("heading", name="Questionnaires, with evidence.")).to_be_visible()
            page.get_by_label("Username", exact=True).fill("reviewer")
            page.get_by_label("Password", exact=True).fill("browser-test-password")
            page.get_by_role("button", name="Sign in", exact=True).click()
            page.locator("#books button").first.click()
            expect(page.locator(".question")).to_have_count(5)
            for i, card in enumerate(page.locator(".question").all()):
                card.get_by_text("Write a reviewed answer", exact=True).click()
                card.locator("select").select_option("Yes" if i == 1 else "Unknown")
                card.get_by_label("Explanation", exact=True).fill(
                    "Atlas encrypts customer data using TLS 1.3."
                    if i == 1
                    else "The eligible source does not establish a complete answer to this question."
                )
                if i == 1:
                    card.get_by_role("button", name="Choose supporting evidence").click()
                    card.get_by_label("public · section:1:", exact=False).check()
                    assert card.get_by_text("INTERNAL-CANARY", exact=False).count() == 0
                    assert card.get_by_text("NOVA-CANARY", exact=False).count() == 0
                card.get_by_role("button", name="Save new revision", exact=True).click()
                expect(card.get_by_role("button", name="Approve this revision", exact=True)).to_be_visible()
                card.locator('input[type="checkbox"]').first.check()
                card.get_by_label("Review rationale", exact=True).fill(
                    "Checked the current public TLS excerpt against the full answer."
                )
                card.locator('input[type="checkbox"]').last.check()
                card.get_by_role("button", name="Approve this revision", exact=True).click()
                expect(card.locator(".badge")).to_have_text("Approved")
            page.locator(".question").nth(1).get_by_role("button", name="Supporting excerpt").click()
            expect(page.locator("#evidence-text")).to_contain_text("TLS 1.3")
            page.screenshot(path=str(artifacts / "inspectable-answer.png"), full_page=False)
            page.get_by_role("button", name="Close", exact=True).click()
            page.get_by_role("button", name="Preview approved export", exact=True).click()
            expect(page.get_by_role("heading", name="5 approved rows", exact=True)).to_be_visible()
            expect(page.locator("#review")).to_contain_text("C3: Yes")
            page.get_by_role("button", name="Create export", exact=True).click()
            download = page.get_by_role("link", name="Download approved workbook", exact=True)
            expect(download).to_be_visible()
            url = download.get_attribute("href")
            assert page.request.get(f"http://127.0.0.1:{port}{url}").status == 200
            page.locator(".question").first.get_by_role(
                "button", name="Revision and decision history"
            ).click()
            expect(page.locator("#evidence-text")).to_contain_text("answer_approved")
            page.get_by_role("button", name="Close", exact=True).click()
            page.get_by_text("Evidence sources", exact=True).click()
            page.get_by_role("button", name="Refresh permitted sources", exact=True).click()
            # Exercise the real UI handoff from reindex to activation; generation hashes are not IDs.
            from sqlalchemy import select
            from app.db import Source
            from app.worker import index_pending

            class Indexer:
                model_id = "fake"

                def documents(self, texts):
                    return [[1.0] + [0.0] * 383 for _ in texts]

            page.locator("#sources > div").filter(has_text="acme · customer_approved · active").get_by_role(
                "button", name="Rebuild pending version", exact=True
            ).click()
            expect(page.locator("#message")).to_contain_text("Pending version created")
            index_pending(env.db, Indexer())
            page.get_by_role("button", name="Refresh permitted sources", exact=True).click()
            page.locator("#sources > div").filter(has_text="acme · customer_approved · pending").get_by_role(
                "button", name="Activate", exact=True
            ).click()
            expect(page.locator("#message")).to_contain_text("Source activated")
            with env.db.transaction() as s:
                assert s.get(Source, env.sources["acme"]).superseded
                assert (
                    len(
                        list(
                            s.scalars(
                                select(Source).where(
                                    Source.family == "acme",
                                    Source.active.is_(True),
                                    Source.superseded.is_(False),
                                )
                            )
                        )
                    )
                    == 1
                )
            assert page.request.get(f"http://127.0.0.1:{port}{url}").status == 409
            # Source revocation through the same authenticated UI invalidates subsequent download.
            page.locator("#sources > div").filter(has_text="public · public").get_by_role(
                "button", name="Deactivate", exact=True
            ).click()
            expect(page.locator("#message")).to_contain_text("Source deactivated")
            assert page.request.get(f"http://127.0.0.1:{port}{url}").status == 409
            assert not errors
            context.close()
            browser.close()
    finally:
        server.should_exit = True
        thread.join(timeout=5)
        sock.close()


@pytest.mark.skipif(os.environ.get("RECORD_DEMO") != "1", reason="Optional three-minute walkthrough")
def test_three_minute_walkthrough(env, tmp_path):
    """Designed recovery scenario with real retrieval and scripted model responses."""
    from io import BytesIO
    from sqlalchemy import select
    from openpyxl import Workbook as Excel, load_workbook
    from langgraph.checkpoint.memory import InMemorySaver
    from playwright.sync_api import sync_playwright, expect
    from app.db import Chunk, Draft, Run, Source
    from app.workflow import Engine
    from test_acceptance import correction_scenario

    generator, embeddings = correction_scenario(env)
    w = Excel()
    w.active.append(["ID", "Question", "Response", "Explanation"])
    w.active.append(["Q1", "Customer hosting region EU policy and archive window"])
    w.active.append(["Q2", "What is the independently verified Atlas certification number?"])
    incoming = tmp_path / "demo-questionnaire.xlsx"
    w.save(incoming)
    with env.db.transaction() as s:
        s.get(User, env.reviewer).password = PasswordHasher().hash("browser-test-password")
    server = uvicorn.Server(
        uvicorn.Config(
            create_app(Settings("sqlite://", secure_cookie=False), env.db, env.objects), log_level="error"
        )
    )
    sock = socket.socket()
    sock.bind(("127.0.0.1", 0))
    port = sock.getsockname()[1]
    thread = threading.Thread(target=lambda: server.run(sockets=[sock]), daemon=True)
    thread.start()
    for _ in range(100):
        if server.started:
            break
        time.sleep(0.02)
    artifacts = Path("output/playwright")
    artifacts.mkdir(parents=True, exist_ok=True)
    try:
        with sync_playwright() as p:
            browser = p.chromium.launch()
            context = browser.new_context(
                viewport={"width": 1440, "height": 1000}, record_video_dir=str(artifacts)
            )
            page = context.new_page()
            video = page.video
            started = time.monotonic()
            page.goto(f"http://127.0.0.1:{port}")
            page.evaluate(
                """() => { const el=document.createElement('div');el.id='demo-caption';el.style='position:fixed;bottom:0;left:0;right:0;padding:14px;background:#10283b;color:white;z-index:10000;font-size:18px';document.body.append(el); }"""
            )

            def chapter(text, seconds=10):
                page.locator("#demo-caption").evaluate(
                    "(el,text)=>el.textContent='SCRIPTED SYNTHETIC DEMO · '+text", text
                )
                page.wait_for_timeout(seconds * 1000)

            page.get_by_label("Username", exact=True).fill("reviewer")
            page.get_by_label("Password", exact=True).fill("browser-test-password")
            chapter("A security reviewer signs in. No live model performance is claimed.")
            page.get_by_role("button", name="Sign in", exact=True).click()
            page.get_by_text("Import questionnaire", exact=True).click()
            form = page.locator("#upload-form")
            form.locator('[name="file"]').set_input_files(incoming)
            form.locator('[name="last_row"]').fill("3")
            form.get_by_role("button", name="Import and preview").click()
            expect(page.get_by_role("button", name="Confirm this mapping")).to_be_visible()
            chapter("Import: check the extracted questions and destination columns before confirmation.", 15)
            page.get_by_role("button", name="Confirm this mapping").click()
            first = page.locator(".question").nth(0)
            first.get_by_role("button", name="Retrieve and draft").click()
            expect(page.locator("#message")).to_contain_text("Retrieval queued")
            with env.db.transaction() as s:
                run = s.scalar(select(Run).where(Run.principal_id == env.reviewer))
                ident = run.id
            engine = Engine(env.db, generator, embeddings)
            state = {"run_id": ident, "step": 0}
            state.update(engine.bounded(engine.search)(state))
            state.update(engine.bounded(engine.assess)(state))
            # Observe the first incomplete result through the actual API/UI, then continue the same stages.
            page.locator("#books button").last.click()
            page.locator(".question").nth(0).locator("summary").filter(has_text="Retrieval:").click()
            chapter(
                "Round 1: hosting evidence is available; archive retention is missing. A targeted query is proposed.",
                20,
            )
            state.update(engine.bounded(engine.search)(state))
            state.update(engine.bounded(engine.assess)(state))
            state.update(engine.bounded(engine.check)(state))
            engine.graph(InMemorySaver()).invoke(
                {"run_id": ident, "route": "search"}, {"configurable": {"thread_id": ident}}
            )
            # The completed stage cache prevents repeated scripted calls when the graph reconstructs its cursor.
            page.locator("#books button").last.click()
            first = page.locator(".question").nth(0)
            first.locator("summary").filter(has_text="Retrieval:").click()
            expect(first).to_contain_text("Archive retention is thirty days")
            with env.db.transaction() as s:
                run = s.get(Run, ident)
                assert run.rounds == 2 and run.record["trace"][1]["new_ids"]
                draft = s.get(Draft, run.record["draft_id"])
                revoke_title = s.get(Source, s.get(Chunk, draft.evidence[0]).source_id).title
            chapter(
                "Round 2: real hybrid retrieval supplies a new excerpt. Both requirements now have evidence.",
                20,
            )
            first.get_by_role("button", name="Supporting excerpt").first.click()
            chapter("Read the exact source excerpt. Model support does not replace reviewer approval.", 15)
            page.get_by_role("button", name="Close", exact=True).click()
            second = page.locator(".question").nth(1)
            second.get_by_text("Write a reviewed answer", exact=True).click()
            second.get_by_label("Explanation", exact=True).fill(
                "No eligible evidence establishes a certification number. The answer remains Unknown."
            )
            second.get_by_role("button", name="Save new revision").click()
            chapter("Missing fact: Unknown is explicit. Missing evidence is never converted to No.", 15)
            for card in page.locator(".question").all():
                for check in card.locator('input[type="checkbox"]').all():
                    check.check()
                card.get_by_label("Review rationale", exact=True).fill(
                    "Reviewed full answer, current source excerpts and customer scope."
                )
                card.get_by_role("button", name="Approve this revision").click()
                expect(card.locator(".badge")).to_have_text("Approved")
            chapter(
                "Each claim and disclosure scope are reviewed; approval is tied to this exact revision.", 15
            )
            page.get_by_role("button", name="Preview approved export").click()
            chapter("Preview: the approved answers will populate C2/C3 and their explanations D2/D3.", 15)
            page.get_by_role("button", name="Create export", exact=True).click()
            link = page.get_by_role("link", name="Download approved workbook")
            expect(link).to_be_visible()
            url = link.get_attribute("href")
            response = page.request.get(f"http://127.0.0.1:{port}{url}")
            assert response.status == 200
            assert load_workbook(BytesIO(response.body())).active["C3"].value == "Unknown"
            chapter("The clean workbook downloads only after every row has a current approval.", 10)
            page.get_by_text("Evidence sources", exact=True).click()
            page.get_by_role("button", name="Refresh permitted sources").click()
            row = page.locator("#sources > div").filter(has_text=revoke_title + " ·")
            row.get_by_role("button", name="Deactivate", exact=True).click()
            assert page.request.get(f"http://127.0.0.1:{port}{url}").status == 409
            page.locator("#books button").last.click()
            expect(page.get_by_role("button", name="Preview approved export")).to_be_disabled()
            chapter(
                "Source revoked: approvals are stale, export is disabled, and the old download URL now returns 409.",
                15,
            )
            remaining = max(0, 180 - (time.monotonic() - started))
            while remaining > 0:
                page.wait_for_timeout(min(remaining, 20) * 1000)
                remaining = max(0, 180 - (time.monotonic() - started))
            context.close()
            video.save_as(str(artifacts / "assuredesk-three-minute-demo.webm"))
            browser.close()
    finally:
        server.should_exit = True
        thread.join(timeout=5)
