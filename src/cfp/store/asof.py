"""as_of(table, t, mode): the point-in-time query (DS-03).

A row is visible at `t` when its first_public_time is at or before `t`. Among the visible rows of a key the
latest correction_version wins. `live` mode also requires ingest_time at or before `t`, which is what the
running system could actually have seen. `scored` mode then drops unknown-vintage rows and reports coverage
(DS-02); a key whose latest visible correction is unknown-vintage is dropped, never rolled back to a
superseded row.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Final, Literal

import polars as pl

from cfp.common.timeutil import require_utc
from cfp.store.schemas import TableSpec

Mode = Literal["live", "replay", "scored"]
MODES: Final = ("live", "replay", "scored")


@dataclass(frozen=True)
class Coverage:
    table: str
    mode: str
    rows_visible: int  # one per key, before any vintage filter
    rows_kept: int
    dropped_unknown: int
    by_vintage: dict[str, int]

    @property
    def share_kept(self) -> float:
        return 1.0 if self.rows_visible == 0 else self.rows_kept / self.rows_visible


@dataclass(frozen=True)
class AsOf:
    frame: pl.DataFrame
    coverage: Coverage


def as_of(rows: pl.LazyFrame, spec: TableSpec, t: datetime, mode: Mode) -> AsOf:
    if mode not in MODES:
        raise ValueError(f"mode must be one of {MODES}; got {mode!r}")
    cutoff = require_utc(t, "t")
    visible = rows.filter(pl.col("first_public_time") <= cutoff)
    if mode == "live":
        visible = visible.filter(pl.col("ingest_time") <= cutoff)
    key = list(spec.key)
    latest = (
        visible.filter(pl.col("correction_version") == pl.col("correction_version").max().over(key))
        .sort(key)
        .collect()
    )
    counts = latest.group_by("vintage").len().sort("vintage")
    by_vintage = dict(zip(counts["vintage"].to_list(), counts["len"].to_list(), strict=True))
    kept = latest.filter(pl.col("vintage") != "unknown") if mode == "scored" else latest
    coverage = Coverage(spec.name, mode, latest.height, kept.height, latest.height - kept.height, by_vintage)
    return AsOf(kept, coverage)
