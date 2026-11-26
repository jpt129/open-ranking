"""Guard hook: editions and frozen parameters are immutable; clean-room sessions cannot see src/."""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
HOOK = ROOT / ".claude" / "hooks" / "guard.py"
BLOCK, ALLOW = 2, 0


def run_hook(tool: str, tool_input: dict[str, str], cleanroom: bool = False) -> int:
    env = {k: v for k, v in os.environ.items() if k != "CFP_CLEANROOM"}
    env["CLAUDE_PROJECT_DIR"] = str(ROOT)
    if cleanroom:
        env["CFP_CLEANROOM"] = "1"
    payload = json.dumps({"tool_name": tool, "tool_input": tool_input})
    return subprocess.run(
        [sys.executable, str(HOOK)], input=payload, text=True, capture_output=True, env=env, check=False
    ).returncode


@pytest.mark.parametrize(
    ("tool", "tool_input", "expected"),
    [
        ("Edit", {"file_path": "frozen/params_2026.json"}, BLOCK),
        ("Write", {"file_path": str(ROOT / "lake/editions/x.json")}, BLOCK),
        ("Write", {"file_path": str(ROOT / "lake/scorecards/score-2026-r05-e1/scorecard.json")}, BLOCK),
        ("Bash", {"command": "rm lake/scorecards/score-2026-r05-e1/scorecard.json"}, BLOCK),
        ("Bash", {"command": "uv run cfp score --release cfp-2026-05"}, ALLOW),
        ("Write", {"file_path": str(ROOT / "lake/gaps/gap-2026-r05-e1/gap.json")}, BLOCK),
        ("Bash", {"command": "rm lake/gaps/gap-2026-r05-e1/gap.json"}, BLOCK),
        ("Bash", {"command": "echo x > lake/gaps/gap-2026-r05-e1/gap.json"}, BLOCK),
        ("Bash", {"command": "uv run cfp gap --release cfp-2026-05"}, ALLOW),
        ("Read", {"file_path": "frozen/MANIFEST"}, ALLOW),
        ("Bash", {"command": "cat frozen/MANIFEST"}, ALLOW),
        ("Bash", {"command": "echo x > frozen/params.json"}, BLOCK),
        ("Bash", {"command": "rm lake/editions/a.json"}, BLOCK),
        ("Bash", {"command": 'python3 -c \'open("frozen/p.json", "w")\''}, BLOCK),
        ("Bash", {"command": "uv run cfp publish --edition e1"}, ALLOW),
        # words that merely contain the folder name are not paths
        (
            "Bash",
            {"command": "python3 -c 'from dataclasses import dataclass; dataclass(frozen=True)'"},
            ALLOW,
        ),
        ("Bash", {"command": "git commit -m 'frozen parameters are immutable; see docs'"}, ALLOW),
        ("Bash", {"command": "rm -r frozen"}, BLOCK),
        ("Bash", {"command": "rm -r frozen && ls"}, BLOCK),
        ("Bash", {"command": "rm -r frozen docs"}, BLOCK),
        ("Bash", {"command": "rm -rf frozen *"}, BLOCK),
        ("Bash", {"command": 'rm -r "frozen"'}, BLOCK),
        ("Bash", {"command": "mv frozen old"}, BLOCK),
        ("Bash", {"command": "find frozen -delete"}, BLOCK),
        ("Bash", {"command": "cd lake && rm -r editions"}, BLOCK),
        ("Bash", {"command": "rm -rf lake"}, BLOCK),
        ("Bash", {"command": "git clean -fdx frozen"}, BLOCK),
        ("Bash", {"command": "ls frozen"}, ALLOW),
        ("Bash", {"command": "rm -r docs/old && echo frozen parameters stay"}, ALLOW),
        ("Bash", {"command": "rm tests/unit/tmp.py"}, ALLOW),
        ("Edit", {"file_path": "src/cfp/store/frozen/x.py"}, ALLOW),
        ("Edit", {"file_path": "src/cfp/a.py"}, ALLOW),
        ("Grep", {"pattern": "x"}, ALLOW),
    ],
)
def test_immutable_paths(tool: str, tool_input: dict[str, str], expected: int) -> None:
    assert run_hook(tool, tool_input) == expected


@pytest.mark.parametrize(
    ("tool", "tool_input", "expected"),
    [
        ("Read", {"file_path": "src/cfp/a.py"}, BLOCK),
        ("Bash", {"command": "cat src/cfp/a.py"}, BLOCK),
        ("Grep", {"pattern": "x", "path": "src"}, BLOCK),
        ("Grep", {"pattern": "x"}, BLOCK),
        ("Glob", {"pattern": "**/*.py", "path": "."}, BLOCK),
        ("Edit", {"file_path": "ts/src/ledger.ts"}, ALLOW),
        ("Bash", {"command": "cd ts && npx tsc && ls ts/src"}, ALLOW),
        ("Grep", {"pattern": "x", "path": "docs"}, ALLOW),
        ("Read", {"file_path": "docs/SPEC.md"}, ALLOW),
    ],
)
def test_cleanroom(tool: str, tool_input: dict[str, str], expected: int) -> None:
    assert run_hook(tool, tool_input, cleanroom=True) == expected
