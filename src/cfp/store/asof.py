"""as_of(rows, spec, t, mode): the point-in-time query (DS-03).

A row is visible at `t` when its first_public_time is at or before `t`. Among the visible rows of a key the
latest correction_version wins. `live` mode also requires ingest_time at or before `t`, which is what the
running system could actually have seen. `replay` and `scored` rebuild history from first_public_time alone,
because backfilled rows are ingested long after the fact. `scored` mode then drops unknown-vintage rows and
reports coverage (DS-02); a key whose latest visible correction is unknown-vintage is dropped, never rolled
back to a superseded row.
"""

from __future__ import annotations

from datetime import datetime

import polars as pl

from cfp.common.timeutil import require_utc
from cfp.store.schemas import TableSpec
from cfp.store.types import MODES, AsOf, Coverage, Mode, check_mode

__all__ = ["MODES", "AsOf", "Coverage", "IntegrityError", "Mode", "as_of"]

DROPPED_KEYS_SHOWN = 20


class IntegrityError(RuntimeError):
    """The stored rows break a store invariant."""


def as_of(rows: pl.LazyFrame, spec: TableSpec, t: datetime, mode: Mode, where: pl.Expr | None = None) -> AsOf:
    """Point-in-time read. `where` narrows the rows first (for example to one season)."""
    check_mode(mode)
    cutoff = require_utc(t, "t")
    if where is not None:
        rows = rows.filter(where)
    visible = rows.filter(pl.col("first_public_time") <= cutoff)
    if mode == "live":
        visible = visible.filter(pl.col("ingest_time") <= cutoff)
    key = list(spec.key)
    latest = (
        visible.filter(pl.col("correction_version") == pl.col("correction_version").max().over(key))
        .sort(key)
        .collect()
    )
    if latest.select(key).is_duplicated().any():
        clash = latest.filter(latest.select(key).is_duplicated()).select(key).row(0)
        raise IntegrityError(f"{spec.name}: two rows share key {clash} and correction_version")
    counts = latest.group_by("vintage").len().sort("vintage")
    by_vintage = dict(zip(counts["vintage"].to_list(), counts["len"].to_list(), strict=True))
    if mode == "scored":
        kept = latest.filter(pl.col("vintage") != "unknown")
        dropped = latest.filter(pl.col("vintage") == "unknown").select(key).head(DROPPED_KEYS_SHOWN).rows()
    else:
        kept, dropped = latest, []
    coverage = Coverage(
        spec.name, mode, latest.height, kept.height, latest.height - kept.height, by_vintage, tuple(dropped)
    )
    return AsOf(kept, coverage)
