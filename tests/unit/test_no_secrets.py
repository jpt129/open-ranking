"""No API key may appear under tests/ or in any tracked file (John, 2026-11-25)."""

from __future__ import annotations

import os
import re
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
KEY_NAMES = ("CFBD_API_KEY", "ODDS_API_KEY")
SHA256 = re.compile(r"\b[0-9a-f]{64}\b")
KEY_SHAPED = [
    re.compile(r"Bearer\s+[A-Za-z0-9+/=_\-.]{16,}"),
    re.compile(r"(?i)authorization\W{1,4}\w"),
    re.compile(r"(?i)api_?key\W{1,4}[A-Za-z0-9+/_\-]{16,}"),
    re.compile(r"(?<![A-Za-z0-9+/])[A-Za-z0-9+/]{40,}={0,2}(?![A-Za-z0-9+/])"),  # long base64 token
    re.compile(r"(?<![0-9a-f])[0-9a-f]{32}(?![0-9a-f])"),  # 32-hex key
]
# Files whose job is to describe or test key handling.
EXEMPT = {"tests/unit/test_no_secrets.py", "tests/unit/test_ingest_http.py"}


def key_shaped(text: str) -> list[str]:
    text = SHA256.sub("", text)  # content digests are not secrets
    return [match.group(0)[:12] + "..." for pattern in KEY_SHAPED for match in pattern.finditer(text)]


def test_detector_recognises_key_shapes() -> None:
    assert key_shaped("Authorization: Bearer abcdefghijklmnop1234")
    assert key_shaped('{"apiKey": "0123456789abcdef0123456789abcdef"}')
    assert key_shaped("x" + "/" + "Ab3" * 21 + "==")
    assert not key_shaped("raw_hash " + "a" * 64 + " and a team named Georgia")


def test_no_key_shaped_string_under_tests() -> None:
    hits: dict[str, list[str]] = {}
    for path in sorted((ROOT / "tests").rglob("*")):
        relative = path.relative_to(ROOT).as_posix()
        if not path.is_file() or "__pycache__" in relative or relative in EXEMPT:
            continue
        found = key_shaped(path.read_text(errors="replace"))
        if found:
            hits[relative] = found[:3]
    assert not hits, hits


def test_configured_keys_appear_in_no_tracked_file() -> None:
    """When keys are present in the environment or .env, their exact values must not be in the repository."""
    from cfp.common.env import load_env

    load_env(ROOT / ".env")
    values = [os.environ[name].removeprefix("Bearer ").strip() for name in KEY_NAMES if os.environ.get(name)]
    values = [value for value in values if len(value) >= 12]
    listed = subprocess.run(
        ["git", "ls-files", "-co", "--exclude-standard"], cwd=ROOT, capture_output=True, text=True
    )
    leaked = []
    for relative in listed.stdout.splitlines():
        path = ROOT / relative
        if path.is_file() and any(value.encode() in path.read_bytes() for value in values):
            leaked.append(relative)
    assert not leaked, leaked
