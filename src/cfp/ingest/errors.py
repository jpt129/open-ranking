"""Ingest failures are loud. A missing source is recorded in docs/DATA_GAPS.md, never filled in."""

from __future__ import annotations

from datetime import date
from pathlib import Path


class SourceError(RuntimeError):
    """A source answered, but not with something usable."""


class MissingSource(SourceError):
    """A source or input is absent. Nothing is substituted for it."""


class BudgetExceeded(RuntimeError):
    """The call would take a source past its monthly allowance less the reserve."""


class StageOverrun(BudgetExceeded):
    """A stage has used more than twice its estimated calls."""


class CrossCheckFailed(SourceError):
    """Two sources disagree about the same record."""


def log_gap(path: Path | str, day: date, source: str, gap: str, effect: str, status: str = "open") -> None:
    """Append one row to the data-gaps table. Idempotent on (source, gap)."""

    def cell(text: str) -> str:
        return " ".join(text.replace("|", "/").split())

    file = Path(path)
    row = f"| {day.isoformat()} | {cell(source)} | {cell(gap)} | {cell(effect)} | {cell(status)} |"
    text = file.read_text() if file.is_file() else ""
    if f"| {cell(source)} | {cell(gap)} |" in text:
        return
    file.write_text(text.rstrip("\n") + "\n" + row + "\n")
