"""P00 smoke test: the package imports and the CLI runs."""

from __future__ import annotations

import importlib

import pytest

import cfp
from cfp.cli import main

PACKAGES = [
    "common", "store", "store.schemas", "store.asof", "store.views", "ingest", "identity", "snapshot",
    "open_ranking", "rules", "forecast", "scoring", "markets", "gap", "release",
]


@pytest.mark.parametrize("name", PACKAGES)
def test_package_imports(name: str) -> None:
    assert importlib.import_module(f"cfp.{name}") is not None


def test_cli_runs(capsys: pytest.CaptureFixture[str]) -> None:
    assert main([]) == 0
    assert "usage: cfp" in capsys.readouterr().out


def test_cli_version(capsys: pytest.CaptureFixture[str]) -> None:
    with pytest.raises(SystemExit) as exit_info:
        main(["--version"])
    assert exit_info.value.code == 0
    assert cfp.__version__ in capsys.readouterr().out
