"""Append only what changed, as the next correction version of each key (DS-01)."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime
from typing import Literal

import polars as pl

from cfp.common.timeutil import require_utc
from cfp.store.lake import Lake
from cfp.store.schemas import TS

CorrectionPublic = Literal["observed", "asserted"]


@dataclass(frozen=True)
class UpsertResult:
    table: str
    new: int
    corrected: int
    unchanged: int


def upsert(
    lake: Lake,
    table: str,
    rows: pl.DataFrame,
    now: datetime,
    corrections: CorrectionPublic,
    ignore: Sequence[str] = (),
    redate: bool = False,
) -> UpsertResult:
    """Write new keys as version 0 and changed keys as the next version; skip unchanged rows.

    `rows` carries every column except correction_version and ingest_time. first_public_time is clamped to
    `now`. With corrections="observed" (live capture) a changed row becomes public at `now`, the moment we
    saw it; with "asserted" (backfill) the caller's rule-based time stands. Columns in `ignore` are stored
    but do not make a row count as changed. With `redate`, a row whose rule-based first_public_time differs
    from the stored one is written as a correction too: that is how a wrongly dated record is put right.
    """
    spec = lake.spec(table)
    now = require_utc(now, "now")
    key, payload = list(spec.key), list(spec.columns)
    rows = rows.drop([c for c in ("correction_version", "ingest_time") if c in rows.columns])
    if rows.select(key).is_duplicated().any():
        clash = rows.filter(rows.select(key).is_duplicated()).select(key).row(0)
        raise ValueError(f"{table}: the same key appears twice in one capture: {clash}")
    stored = lake.scan(table)
    latest = (
        stored.filter(pl.col("correction_version") == pl.col("correction_version").max().over(key))
        .select([*payload, "correction_version", "first_public_time"])
        .collect()
    )
    joined = rows.join(
        latest.rename({c: f"{c}__old" for c in latest.columns if c not in key}),
        on=key,
        how="left",
        nulls_equal=True,
    )
    is_new = pl.col("correction_version__old").is_null()
    same = pl.all_horizontal(
        [pl.col(c).eq_missing(pl.col(f"{c}__old")) for c in payload if c not in key and c not in ignore]
    )
    if redate:
        if corrections != "asserted":
            raise ValueError("redate needs asserted public times")
        same = same & pl.min_horizontal(pl.col("first_public_time"), pl.lit(now).cast(TS)).eq_missing(
            pl.col("first_public_time__old")
        )
    changed = joined.filter(is_new | ~same)
    n_new = changed.filter(is_new).height
    out = changed.with_columns(
        correction_version=(pl.col("correction_version__old").fill_null(-1) + 1).cast(pl.Int32()),
        first_public_time=pl.when(~is_new & (corrections == "observed"))
        .then(pl.lit(now).cast(TS))
        .otherwise(pl.min_horizontal(pl.col("first_public_time"), pl.lit(now).cast(TS))),
        ingest_time=pl.lit(None, dtype=TS),
    ).select(list(spec.schema))
    lake.append(table, out)
    return UpsertResult(table, n_new, out.height - n_new, rows.height - out.height)
