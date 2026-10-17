"""No-network child parser. Unsupported formats fail before model use."""

import json
from pathlib import Path
import subprocess
import sys
import tempfile

from .policy import Rejected, require


PARSER_VERSION = "strict-text-v2"


def parse_source(data, suffix, mapping=None):
    require(suffix in {".md", ".pdf", ".json", ".xlsx"}, "unsupported_source", 422)
    require(len(data) <= 10 * 1024**2, "source_too_large", 413)
    with tempfile.TemporaryDirectory(prefix="assuredesk-parse-") as temp:
        root = Path(temp).resolve()
        temp = str(root)
        out_dir = root / "out"
        out_dir.mkdir()
        source, output = root / ("input" + suffix), out_dir / "output.json"
        source.write_bytes(data)
        source.chmod(0o400)
        if mapping is not None:
            (root / "mapping.json").write_text(json.dumps(mapping))
        script = Path(__file__).with_name("parser_child.py").resolve()
        python = Path(sys.executable).absolute()
        roots = {
            str(Path(sys.base_prefix).resolve()),
            str(python.parent.parent.resolve()),
            str(script.parent),
        }
        command = [str(python), "-I", str(script), str(source), str(output)]
        if sys.platform == "darwin":
            # Homebrew-built Python links to these runtime libraries, outside sys.base_prefix.
            for name in ["gettext", "openssl@3", "xz", "zstd", "libffi", "sqlite", "mpdecimal"]:
                runtime = Path("/opt/homebrew/opt") / name
                if runtime.exists():
                    roots.add(str(runtime.resolve()))
            # Only runtime/code/input are readable. The project's .env is outside these roots.
            read = " ".join(
                f"(subpath {json.dumps(p)})"
                for p in roots
                | {
                    temp,
                    "/usr",
                    "/System",
                    "/private/var/db/dyld",
                    "/private/preboot",
                    "/Library/Apple/System",
                }
            )
            profile = (
                "(version 1)(deny default)(allow process*)(allow sysctl-read)(allow mach-lookup)(allow file-read-metadata)(allow file-map-executable)"
                f'(allow file-read* {read} (literal "/") (literal "/dev/urandom") (literal "/dev/null"))'
                f"(allow file-write* (subpath {json.dumps(str(out_dir))}))"
            )
            command = ["/usr/bin/sandbox-exec", "-p", profile, *command]
        elif sys.platform == "linux":
            # The trusted child installs Landlock and seccomp before third-party parsing.
            pass
        else:
            raise Rejected("parser_sandbox_unavailable", 503)
        try:
            result = subprocess.run(
                command,
                env={
                    "PATH": "/usr/bin:/bin",
                    "PYTHONDONTWRITEBYTECODE": "1",
                    "OPENBLAS_NUM_THREADS": "1",
                    "OMP_NUM_THREADS": "1",
                },
                stdin=subprocess.DEVNULL,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                timeout=15,
            )
            require(result.returncode == 0 and output.exists(), "unsupported_source", 422)
            require(output.stat().st_size <= 8 * 1024**2, "extraction_too_large", 413)
            blocks = json.loads(output.read_text())
            require(
                blocks and sum(len(x["text"]) for x in blocks) <= 2_000_000,
                "empty_or_oversized_extraction",
                422,
            )
            return blocks
        except (subprocess.TimeoutExpired, ValueError) as exc:
            raise Rejected("parser_failed") from exc
