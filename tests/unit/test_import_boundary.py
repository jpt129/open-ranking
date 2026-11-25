"""test_import_boundary: cfp.open_ranking must not import forecast, markets or ingest modules.

Runs the import-linter contracts in pyproject.toml so a boundary break fails the test suite as well as
the dedicated CI step.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def test_import_contracts_hold() -> None:
    result = subprocess.run(
        [str(Path(sys.executable).parent / "lint-imports"), "--config", str(ROOT / "pyproject.toml")],
        cwd=ROOT, capture_output=True, text=True, check=False,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert "0 broken" in result.stdout, result.stdout
