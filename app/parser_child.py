"""Standalone entry point: only invoked by the restricted parser subprocess."""

import json
import re
from pathlib import Path
import resource
import sys

resource.setrlimit(resource.RLIMIT_CPU, (10, 10))
resource.setrlimit(resource.RLIMIT_FSIZE, (8 * 1024**2, 8 * 1024**2))
source, output = map(Path, sys.argv[1:])
if sys.platform == "linux":
    resource.setrlimit(resource.RLIMIT_AS, (1024 * 1024**2, 1024 * 1024**2))
    # Landlock ABI >=3 denies filesystem access except runtime/code/input and output.
    # https://www.kernel.org/doc/html/v6.9/userspace-api/landlock.html
    # Fail closed rather than silently reducing protection on unsupported hosts.
    import ctypes
    import errno
    import os
    import platform

    if platform.machine() not in {"aarch64", "x86_64"}:
        raise RuntimeError("Unsupported sandbox architecture")
    libc = ctypes.CDLL(None, use_errno=True)
    if libc.syscall(444, 0, 0, 1) < 3:
        raise RuntimeError("Landlock ABI 3 required")
    handled = (1 << 15) - 1  # ABI3 filesystem rights, including REFER and TRUNCATE.
    ruleset = ctypes.c_uint64(handled)
    fd = libc.syscall(444, ctypes.byref(ruleset), ctypes.sizeof(ruleset), 0)
    if fd < 0:
        raise RuntimeError("Filesystem sandbox unavailable")

    class PathRule(ctypes.Structure):
        _pack_ = 1
        _fields_ = [("access", ctypes.c_uint64), ("parent", ctypes.c_int32)]

    roots = {
        Path(sys.base_prefix).resolve(),
        Path(sys.executable).absolute().parent.parent.resolve(),
        Path(__file__).resolve().parent,
        source.parent,
        Path("/usr"),
        Path("/lib"),
        Path("/lib64"),
    }
    read = (1 << 2) | (1 << 3)
    for path, access in [(p, read) for p in roots if p.exists()] + [(output.parent, handled & ~1)]:
        parent = os.open(path, os.O_PATH | os.O_CLOEXEC)
        rule = PathRule(access, parent)
        result = libc.syscall(445, fd, 1, ctypes.byref(rule), 0)
        os.close(parent)
        if result:
            raise RuntimeError("Filesystem sandbox unavailable")
    if libc.prctl(38, 1, 0, 0, 0) or libc.syscall(446, fd, 0):
        raise RuntimeError("Filesystem sandbox unavailable")
    os.close(fd)

    seccomp = ctypes.CDLL("libseccomp.so.2", use_errno=True)
    seccomp.seccomp_init.argtypes = [ctypes.c_uint32]
    seccomp.seccomp_init.restype = ctypes.c_void_p
    seccomp.seccomp_syscall_resolve_name.argtypes = [ctypes.c_char_p]
    seccomp.seccomp_rule_add.argtypes = [ctypes.c_void_p, ctypes.c_uint32, ctypes.c_int, ctypes.c_uint]
    seccomp.seccomp_load.argtypes = [ctypes.c_void_p]
    seccomp.seccomp_release.argtypes = [ctypes.c_void_p]
    ctx = seccomp.seccomp_init(0x7FFF0000)
    if not ctx:
        raise RuntimeError("Network sandbox unavailable")
    for name in (
        b"socket",
        b"socketpair",
        b"connect",
        b"io_uring_setup",
        b"execve",
        b"execveat",
        b"ptrace",
        b"process_vm_readv",
        b"process_vm_writev",
        b"kill",
        b"tkill",
        b"tgkill",
        b"clone",
        b"clone3",
    ):
        syscall = seccomp.seccomp_syscall_resolve_name(name)
        if syscall < 0 or seccomp.seccomp_rule_add(ctx, 0x00050000 | errno.EPERM, syscall, 0):
            raise RuntimeError("Network sandbox unavailable")
    if seccomp.seccomp_load(ctx):
        raise RuntimeError("Network sandbox unavailable")
    seccomp.seccomp_release(ctx)
if sys.platform == "darwin":
    # macOS rejects RLIMIT_AS/DATA changes. Enforce an RSS watchdog in addition to CPU/time limits.
    import os
    import threading
    import time

    def memory_guard():
        while True:
            if resource.getrusage(resource.RUSAGE_SELF).ru_maxrss > 512 * 1024**2:
                os._exit(72)
            time.sleep(0.02)

    threading.Thread(target=memory_guard, daemon=True).start()
blocks = []
if source.suffix == ".xlsx":
    import mimetypes

    mimetypes.knownfiles = []
    mimetypes.init(files=[])
    import types

    package = types.ModuleType("app")
    package.__path__ = [str(Path(__file__).parent)]
    sys.modules["app"] = package
    from app.workbooks import extract

    blocks = extract(source.read_bytes(), json.loads((source.parent / "mapping.json").read_text()))
elif source.suffix == ".pdf":
    from pypdf import PdfReader

    if not source.read_bytes().startswith(b"%PDF-"):
        raise ValueError("Invalid PDF signature")
    reader = PdfReader(source)
    if reader.is_encrypted or len(reader.pages) > 200:
        raise ValueError("Unsupported PDF")
    for i, page in enumerate(reader.pages, 1):
        text = page.extract_text(extraction_mode="layout") or ""
        # Fail closed on likely columns/tables or replacement glyphs: no guessed cell ordering.
        if "\ufffd" in text or any(re.search(r"\S {3,}\S", line) for line in text.splitlines()):
            raise ValueError("Table or column layout requires curated text")
        if len(text) > 100_000:
            raise ValueError("Page too large")
        if text.strip():
            blocks.append({"text": text, "locator": f"page:{i}"})
elif source.suffix == ".md":
    text = source.read_text()
    offset = 0
    headings = []
    for section in text.split("\n\n"):
        if section.strip():
            for line in section.splitlines():
                match = re.match(r"^(#{1,6})\s+(.+)$", line)
                if match:
                    level = len(match[1])
                    headings = headings[: level - 1] + [match[2]]
            locator = f"char:{offset}" + (" / " + " > ".join(headings) if headings else "")
            blocks.append({"text": section, "locator": locator[:120]})
        offset += len(section) + 2
else:
    value = json.loads(source.read_text())
    if not isinstance(value, dict) or set(value) != {"statement"} or not isinstance(value["statement"], str):
        raise ValueError("Expected a single explicitly approved statement")
    blocks.append({"text": value["statement"], "locator": "statement"})
if not blocks or sum(len(x["text"]) for x in blocks) > 2_000_000:
    raise ValueError("Unsupported extraction")
output.write_text(json.dumps(blocks))
