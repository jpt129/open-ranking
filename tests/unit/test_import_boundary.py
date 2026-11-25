"""test_import_boundary: the Open Ranking cannot import forecasts, markets, ingest or the lake.

Runs the import-linter contracts in pyproject.toml, proves they fail on planted violations in a scratch copy
of the package, and scans the Open Ranking's source for routes no import contract can see.
"""

from __future__ import annotations

import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
LINT = Path(sys.executable).parent / "lint-imports"
GUARDED = ("open_ranking", "snapshot", "rules")

# Ways to reach data without an import the contracts can follow.
BACKDOORS = re.compile(
    r"\bLake\b|PointInTimeView|_OpenRankingView|\bpit\b|read_parquet|scan_parquet|read_csv|read_ipc|\bduckdb\b|pyarrow"
    r"|importlib|__import__|\b_read\b|__closure__|__globals__|\bgetattr\b|normalized/|\beval\(|\bexec\("
)


def lint(cwd: Path) -> subprocess.CompletedProcess[str]:
    env = {**os.environ, "PYTHONPATH": str(cwd / "src")}
    return subprocess.run(
        [str(LINT), "--config", str(cwd / "pyproject.toml")],
        cwd=cwd, capture_output=True, text=True, check=False, env=env,
    )  # fmt: skip


def test_import_contracts_hold() -> None:
    result = lint(ROOT)
    assert result.returncode == 0, result.stdout + result.stderr
    assert "4 kept, 0 broken" in result.stdout, result.stdout


@pytest.mark.parametrize(
    ("module", "statement"),
    [
        ("open_ranking", "from cfp import forecast"),
        ("open_ranking", "from cfp.ingest import anything"),
        ("open_ranking", "from cfp.store.lake import Lake"),
        ("open_ranking", "from cfp.store.pit import PointInTimeView"),
        ("open_ranking", "import cfp.store.asof"),
        ("open_ranking", "from cfp.store import schemas"),
        ("open_ranking", "from cfp import markets"),
        ("snapshot", "from cfp.store.lake import Lake"),
        ("rules", "from cfp import forecast"),
        ("store/views.py", "from cfp.store.lake import Lake"),
    ],
)
def test_planted_violation_breaks_a_contract(tmp_path: Path, module: str, statement: str) -> None:
    shutil.copytree(ROOT / "src", tmp_path / "src", ignore=shutil.ignore_patterns("__pycache__"))
    shutil.copy(ROOT / "pyproject.toml", tmp_path / "pyproject.toml")
    target = tmp_path / "src" / "cfp" / module
    if target.is_dir():
        (target / "_probe.py").write_text(statement + "\n")
    else:
        target.write_text(target.read_text() + "\n" + statement + "\n")
    result = lint(tmp_path)
    assert result.returncode != 0, f"contract did not catch: {statement}\n{result.stdout}"
    assert "broken" in result.stdout.lower()


def test_guarded_packages_have_no_backdoors() -> None:
    offenders = []
    for package in GUARDED:
        for path in sorted((ROOT / "src" / "cfp" / package).rglob("*.py")):
            for number, line in enumerate(path.read_text().splitlines(), start=1):
                if BACKDOORS.search(line):
                    offenders.append(f"{path.relative_to(ROOT)}:{number}: {line.strip()}")
    assert not offenders, "\n".join(offenders)


@pytest.mark.parametrize(
    "line",
    [
        "lake = view._OpenRankingView__lake",
        "from cfp.store.views import Lake",
        'pl.read_parquet("lake/normalized/polls/x.parquet")',
        'duckdb.sql("select * from polls")',
        'importlib.import_module("cfp.forecast")',
        "view._read('polls', None)",
        "view.table.__closure__",
        "import cfp.store; cfp.store.pit.PointInTimeView",
    ],
)
def test_backdoor_scan_catches(line: str) -> None:
    assert BACKDOORS.search(line)
