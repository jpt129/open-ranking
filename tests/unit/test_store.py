"""P01 acceptance tests: store and point-in-time API (DS-01, DS-02, DS-03, DS-04)."""

from __future__ import annotations

import time
from datetime import datetime, timedelta
from pathlib import Path

import polars as pl
import pytest

from cfp.store.asof import as_of
from cfp.store.lake import DuplicateRow, Lake, MissingRaw
from cfp.store.schemas import PROVENANCE, TABLES, VINTAGES, SchemaError
from cfp.store.views import ForbiddenTable, OpenRankingView, PointInTimeView

from .store_helpers import SEC, T0, frame, game


@pytest.fixture
def lake(tmp_path: Path) -> Lake:
    return Lake(tmp_path / "lake")


# --- DS-01 / DS-02: schemas ---------------------------------------------------


def test_schema_has_provenance() -> None:
    expected = [
        "source_id",
        "event_time",
        "first_public_time",
        "ingest_time",
        "correction_version",
        "raw_hash",
    ]
    assert list(PROVENANCE) == [*expected, "vintage"]
    assert VINTAGES == ("live", "archived_authentic", "reconstructed", "unknown")
    for name, spec in TABLES.items():
        for column in PROVENANCE:
            assert column in spec.schema, f"{name} lacks {column}"
        assert set(spec.key) <= set(spec.schema), name


def test_expected_tables_exist() -> None:
    assert set(TABLES) >= {
        "games",
        "teams",
        "team_aliases",
        "membership",
        "committee_releases",
        "polls",
        "lines",
        "market_quotes",
        "eligibility",
        "champions",
        "editions",
        "chair_remarks",
    }


# --- DS-03: point-in-time visibility -----------------------------------------


def test_row_public_after_t_invisible(lake: Lake) -> None:
    lake.append("games", frame("games", [game(lake, first_public_time=T0 + SEC, ingest_time=T0 + SEC)]))
    for mode in ("live", "replay", "scored"):
        assert lake.as_of("games", T0, mode).frame.height == 0
    assert lake.as_of("games", T0 + SEC, "replay").frame.height == 1


def test_row_public_exactly_at_t_visible(lake: Lake) -> None:
    lake.append("games", frame("games", [game(lake, first_public_time=T0, ingest_time=T0)]))
    assert lake.as_of("games", T0, "live").frame.height == 1


def test_late_correction_invisible_live(lake: Lake) -> None:
    original = game(lake, home_pts=28)
    correction = game(lake, home_pts=31, correction_version=1, ingest_time=T0 + timedelta(hours=1))
    lake.append("games", frame("games", [original]))
    lake.append("games", frame("games", [correction]))
    assert lake.as_of("games", T0, "live").frame["home_pts"].to_list() == [28]
    assert lake.as_of("games", T0, "replay").frame["home_pts"].to_list() == [31]
    assert lake.as_of("games", T0 + timedelta(hours=1), "live").frame["home_pts"].to_list() == [31]


def test_latest_correction_wins_per_key(lake: Lake) -> None:
    rows = [
        game(lake, "g1"),
        game(lake, "g1", home_pts=35, correction_version=2),
        game(lake, "g1", home_pts=30, correction_version=1),
        game(lake, "g2", home_id="C", away_id="D"),
    ]
    lake.append("games", frame("games", rows))
    result = lake.as_of("games", T0, "replay").frame
    assert result["game_id"].to_list() == ["g1", "g2"]
    assert result["home_pts"].to_list() == [35, 28]
    assert result["correction_version"].to_list() == [2, 0]


def test_correction_not_yet_public_falls_back(lake: Lake) -> None:
    rows = [
        game(lake),
        game(lake, home_pts=31, correction_version=1, first_public_time=T0 + SEC, ingest_time=T0 + SEC),
    ]
    lake.append("games", frame("games", rows))
    assert lake.as_of("games", T0, "replay").frame["home_pts"].to_list() == [28]


def test_scored_mode_drops_unknown_vintage(lake: Lake) -> None:
    rows = [
        game(lake, "g1", vintage="live"),
        game(lake, "g2", vintage="archived_authentic"),
        game(lake, "g3", vintage="reconstructed"),
        game(lake, "g4", vintage="unknown"),
    ]
    lake.append("games", frame("games", rows))
    replay = lake.as_of("games", T0, "replay")
    scored = lake.as_of("games", T0, "scored")
    assert replay.frame.height == 4
    assert replay.coverage.dropped_unknown == 0
    assert scored.frame["game_id"].to_list() == ["g1", "g2", "g3"]
    assert scored.coverage.rows_visible == 4
    assert scored.coverage.rows_kept == 3
    assert scored.coverage.dropped_unknown == 1
    assert scored.coverage.by_vintage == {
        "archived_authentic": 1,
        "live": 1,
        "reconstructed": 1,
        "unknown": 1,
    }
    assert scored.coverage.share_kept == pytest.approx(0.75)


def test_scored_mode_does_not_resurrect_superseded_row(lake: Lake) -> None:
    """If the latest visible correction is unknown-vintage, the key is dropped, not rolled back."""
    rows = [game(lake, vintage="live"), game(lake, home_pts=31, correction_version=1, vintage="unknown")]
    lake.append("games", frame("games", rows))
    scored = lake.as_of("games", T0, "scored")
    assert scored.frame.height == 0
    assert scored.coverage.dropped_unknown == 1


def test_as_of_rejects_naive_time_and_bad_mode(lake: Lake) -> None:
    with pytest.raises(ValueError, match="timezone"):
        lake.as_of("games", datetime(2026, 11, 22, 7, 0), "replay")  # noqa: DTZ001
    with pytest.raises(ValueError, match="mode"):
        lake.as_of("games", T0, "final")  # type: ignore[arg-type]


def test_as_of_empty_table_has_schema(lake: Lake) -> None:
    result = lake.as_of("polls", T0, "scored")
    assert result.frame.height == 0
    assert result.frame.schema == TABLES["polls"].schema
    assert result.coverage.share_kept == 1.0


# --- DS-04: views --------------------------------------------------------------


@pytest.mark.parametrize(
    "table",
    [
        "polls",
        "committee_releases",
        "lines",
        "market_quotes",
        "chair_remarks",
        "editions",
        "team_aliases",
        "eligibility",
        "champions",
        "no_such_table",
    ],
)
def test_open_ranking_view_refuses_forbidden_tables(lake: Lake, table: str) -> None:
    view = OpenRankingView(lake, T0)
    with pytest.raises(ForbiddenTable):
        view.table(table)


def test_open_ranking_view_allows_only_three(lake: Lake) -> None:
    lake.append("games", frame("games", [game(lake)]))
    view = OpenRankingView(lake, T0)
    assert frozenset({"games", "teams", "membership"}) == OpenRankingView.ALLOWED
    assert view.table("games").height == 1
    assert view.table("teams").height == 0
    assert view.table("membership").height == 0
    assert not hasattr(view, "lake")


def test_point_in_time_view_reads_any_table_and_collects_coverage(lake: Lake) -> None:
    lake.append("games", frame("games", [game(lake, "g1"), game(lake, "g2", vintage="unknown")]))
    view = PointInTimeView(lake, T0, "scored")
    assert view.table("games").height == 1
    assert view.table("polls").height == 0
    assert view.coverage["games"].dropped_unknown == 1
    assert set(view.coverage) == {"games", "polls"}


# --- lake: raw store and append rules -----------------------------------------


def test_raw_is_content_addressed(lake: Lake) -> None:
    first = lake.put_raw(b'{"a": 1}')
    second = lake.put_raw(b'{"a": 1}')
    assert first == second == "f9d86028c6e0d64e225186f96acb69338b2c59764df79162107f5c4bb34d1310"
    assert lake.get_raw(first) == b'{"a": 1}'
    assert len([p for p in (lake.root / "raw").rglob("*") if p.is_file()]) == 1


def test_append_requires_raw_payload(lake: Lake) -> None:
    row = game(lake)
    row["raw_hash"] = "0" * 64
    with pytest.raises(MissingRaw):
        lake.append("games", frame("games", [row]))


def test_append_rejects_duplicate_key_and_version(lake: Lake) -> None:
    lake.append("games", frame("games", [game(lake)]))
    with pytest.raises(DuplicateRow):
        lake.append("games", frame("games", [game(lake, home_pts=99)]))
    with pytest.raises(DuplicateRow):
        lake.append("games", frame("games", [game(lake, "g9"), game(lake, "g9")]))


def test_append_validates_schema(lake: Lake) -> None:
    good = frame("games", [game(lake)])
    with pytest.raises(SchemaError, match="vintage"):
        lake.append("games", good.with_columns(pl.lit("guess").alias("vintage")))
    with pytest.raises(SchemaError, match="columns"):
        lake.append("games", good.drop("raw_hash"))
    with pytest.raises(SchemaError, match="columns"):
        lake.append("games", good.with_columns(pl.lit(1).alias("extra")))
    with pytest.raises(SchemaError, match="first_public_time"):
        lake.append("games", good.with_columns(pl.col("first_public_time").dt.replace_time_zone(None)))
    with pytest.raises(SchemaError, match="null"):
        lake.append("games", good.with_columns(pl.lit(None, dtype=pl.String).alias("source_id")))
    with pytest.raises(SchemaError, match="null"):
        lake.append("games", good.with_columns(pl.lit(None, dtype=pl.String).alias("game_id")))
    with pytest.raises(SchemaError, match="ingest_time"):
        lake.append(
            "games", good.with_columns((pl.col("first_public_time") - timedelta(days=1)).alias("ingest_time"))
        )
    with pytest.raises(KeyError):
        lake.append("nope", good)


def test_append_is_partitioned_by_season_and_append_only(lake: Lake) -> None:
    lake.append("games", frame("games", [game(lake, "g1"), game(lake, "g2", season=2025)]))
    files_before = sorted(
        p.relative_to(lake.root).as_posix() for p in (lake.root / "normalized").rglob("*.parquet")
    )
    assert [f.rsplit("/", 1)[0] for f in files_before] == [
        "normalized/games/season=2025",
        "normalized/games/season=2026",
    ]
    lake.append("games", frame("games", [game(lake, "g3")]))
    files_after = sorted(
        p.relative_to(lake.root).as_posix() for p in (lake.root / "normalized").rglob("*.parquet")
    )
    assert set(files_before) < set(files_after)
    assert lake.scan("games").collect().height == 3


def test_append_same_batch_twice_is_rejected_not_duplicated(lake: Lake) -> None:
    batch = frame("games", [game(lake)])
    lake.append("games", batch)
    with pytest.raises(DuplicateRow):
        lake.append("games", batch)
    assert lake.scan("games").collect().height == 1


# --- budget ---------------------------------------------------------------------


def test_as_of_one_million_rows_under_one_second() -> None:
    n = 1_000_000
    base = pl.DataFrame({"i": pl.int_range(n, eager=True)})
    quotes = (
        base.select(
            pl.lit("kalshi").alias("venue"),
            (pl.lit("KX-") + (pl.col("i") % 250).cast(pl.String)).alias("ticker"),
            (pl.lit(T0) - pl.duration(seconds=pl.col("i") * 2)).alias("ts_utc"),
            pl.lit(2026, dtype=pl.Int32).alias("season"),
            pl.lit(0.5).alias("bid"),
            pl.lit(0.52).alias("ask"),
            pl.lit(10.0).alias("bid_size"),
            pl.lit(10.0).alias("ask_size"),
            pl.lit(0.51).alias("last"),
            pl.lit("kalshi").alias("source_id"),
            (pl.lit(T0) - pl.duration(seconds=pl.col("i") * 2)).alias("event_time"),
            (pl.lit(T0 + timedelta(hours=1)) - pl.duration(seconds=pl.col("i") * 2)).alias(
                "first_public_time"
            ),
            (pl.lit(T0 + timedelta(hours=2)) - pl.duration(seconds=pl.col("i") * 2)).alias("ingest_time"),
            (pl.col("i") % 3).cast(pl.Int32).alias("correction_version"),
            pl.lit("0" * 64).alias("raw_hash"),
            pl.when(pl.col("i") % 10 == 0).then(pl.lit("unknown")).otherwise(pl.lit("live")).alias("vintage"),
        )
        .select(list(TABLES["market_quotes"].schema))
        .cast(dict(TABLES["market_quotes"].schema))
    )
    spec = TABLES["market_quotes"]
    as_of(quotes.lazy(), spec, T0, "scored")  # warm-up
    best = float("inf")
    for _ in range(3):
        start = time.perf_counter()
        result = as_of(quotes.lazy(), spec, T0, "scored")
        best = min(best, time.perf_counter() - start)
    assert 0 < result.frame.height < n
    assert result.coverage.dropped_unknown > 0
    print(f"as_of over {n:,} rows: {best * 1000:.0f} ms")
    assert best < 1.0
