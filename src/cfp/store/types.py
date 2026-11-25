"""Plain result types shared by the store's query and view modules. No I/O and no store imports."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Final, Literal

import polars as pl

Mode = Literal["live", "replay", "scored"]
MODES: Final = ("live", "replay", "scored")


def check_mode(mode: str) -> None:
    if mode not in MODES:
        raise ValueError(f"mode must be one of {MODES}; got {mode!r}")


@dataclass(frozen=True)
class Coverage:
    """What a point-in-time read saw and what scored mode dropped (DS-02)."""

    table: str
    mode: str
    rows_visible: int  # one per key, before any vintage filter
    rows_kept: int
    dropped_unknown: int
    by_vintage: dict[str, int]
    dropped_keys: tuple[tuple[object, ...], ...] = ()  # first few, for the disclosure

    @property
    def share_kept(self) -> float:
        return 1.0 if self.rows_visible == 0 else self.rows_kept / self.rows_visible


@dataclass(frozen=True)
class AsOf:
    frame: pl.DataFrame
    coverage: Coverage
