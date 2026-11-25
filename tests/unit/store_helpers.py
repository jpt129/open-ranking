"""Builders for store tests."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

import polars as pl

from cfp.store.lake import Lake
from cfp.store.schemas import TABLES

T0 = datetime(2026, 11, 22, 7, 0, tzinfo=UTC)  # a Sunday 02:00 ET issue time
SEC = timedelta(seconds=1)


def frame(table: str, rows: list[dict[str, Any]]) -> pl.DataFrame:
    return pl.DataFrame(rows, schema=TABLES[table].schema)


def game(lake: Lake, game_id: str = "g1", **over: Any) -> dict[str, Any]:
    """One games row whose raw payload is registered in the lake."""
    raw_hash = lake.put_raw(f"payload:{game_id}:{over.get('correction_version', 0)}".encode())
    row: dict[str, Any] = {
        "game_id": game_id,
        "season": 2026,
        "week": 12,
        "start_utc": T0 - timedelta(hours=10),
        "home_id": "A",
        "away_id": "B",
        "home_pts": 28,
        "away_pts": 24,
        "neutral": False,
        "site": None,
        "season_type": "regular",
        "status": "final",
        "title_game": False,
        "home_div": "fbs",
        "away_div": "fbs",
        "source_id": "test",
        "event_time": T0 - timedelta(hours=7),
        "first_public_time": T0 - timedelta(hours=7),
        "ingest_time": T0 - timedelta(hours=6),
        "correction_version": 0,
        "raw_hash": raw_hash,
        "vintage": "live",
    }
    row.update(over)
    return row
