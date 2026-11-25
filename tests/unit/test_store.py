"""P01 acceptance tests: store and point-in-time API (DS-01, DS-02, DS-03, DS-04)."""

from __future__ import annotations

import time
from datetime import date, datetime, timedelta
from pathlib import Path

import polars as pl
import pytest

from cfp.store.asof import IntegrityError, as_of
from cfp.store.lake import CorrectionOrder, DuplicateRow, Lake, MissingRaw
from cfp.store.pit import PointInTimeView
from cfp.store.schemas import PROVENANCE, TABLES, TS, VINTAGES, SchemaError, TableSpec
from cfp.store.views import ForbiddenTable, OpenRankingView

from .store_helpers import HOUR, SEC, T0, Clock, frame, game


@pytest.fixture
def clock() -> Clock:
    return Clock(T0 - 6 * HOUR)


@pytest.fixture
def lake(tmp_path: Path, clock: Clock) -> Lake:
    return Lake(tmp_path / "lake", clock=clock)


def parquet_files(lake: Lake) -> dict[str, bytes]:
    return {p.relative_to(lake.root).as_posix(): p.read_bytes() for p in lake.root.rglob("*.parquet")}


# --- DS-01 / DS-02: schemas ---------------------------------------------------


def test_schema_has_provenance() -> None:
    assert dict(PROVENANCE) == {
        "source_id": pl.String(),
        "event_time": TS,
        "first_public_time": TS,
        "ingest_time": TS,
        "correction_version": pl.Int32(),
        "raw_hash": pl.String(),
        "vintage": pl.String(),
    }
    assert pl.Datetime("us", "UTC") == TS
    assert VINTAGES == ("live", "archived_authentic", "reconstructed", "unknown")
    for name, spec in TABLES.items():
        assert list(spec.schema)[-len(PROVENANCE) :] == list(PROVENANCE), name
        assert not set(spec.key) & spec.nullable, name
        assert not set(PROVENANCE) & spec.nullable, name


def test_expected_tables_exist() -> None:
    assert set(TABLES) == {
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


def test_spec_refuses_nullable_key() -> None:
    with pytest.raises(ValueError, match="key columns cannot be nullable"):
        TableSpec("bad", ("a",), {"a": pl.String()}, frozenset({"a"}), partition_by_season=False)


@pytest.mark.parametrize("column", [c for c in PROVENANCE if c != "ingest_time"])
def test_provenance_fields_cannot_be_null(lake: Lake, column: str) -> None:
    good = frame("games", [game(lake)])
    broken = good.with_columns(pl.lit(None, dtype=good.schema[column]).alias(column))
    with pytest.raises(SchemaError):
        lake.append("games", broken)


# --- DS-03: point-in-time visibility -----------------------------------------


def test_row_public_after_t_invisible(lake: Lake, clock: Clock) -> None:
    clock.now = T0 + SEC
    lake.append("games", frame("games", [game(lake, first_public_time=T0 + SEC)]))
    for mode in ("live", "replay", "scored"):
        assert lake.as_of("games", T0, mode).frame.height == 0  # type: ignore[arg-type]
    assert lake.as_of("games", T0 + SEC, "replay").frame.height == 1
    assert lake.as_of("games", T0 + SEC, "live").frame.height == 1


def test_row_public_exactly_at_t_visible(lake: Lake, clock: Clock) -> None:
    clock.now = T0
    lake.append("games", frame("games", [game(lake, first_public_time=T0)]))
    assert lake.as_of("games", T0, "live").frame.height == 1


def test_late_correction_invisible_live(lake: Lake, clock: Clock) -> None:
    lake.append("games", frame("games", [game(lake, home_pts=28)]))
    clock.now = T0 + HOUR
    lake.append("games", frame("games", [game(lake, home_pts=31, correction_version=1)]))
    assert lake.as_of("games", T0, "live").frame["home_pts"].to_list() == [28]
    assert lake.as_of("games", T0, "replay").frame["home_pts"].to_list() == [31]
    assert lake.as_of("games", T0 + HOUR, "live").frame["home_pts"].to_list() == [31]


def test_append_cannot_backdate_into_a_past_live_view(lake: Lake, clock: Clock) -> None:
    """ingest_time comes from the lake's clock, whatever the caller supplies."""
    lake.append("games", frame("games", [game(lake, home_pts=28)]))
    before = lake.as_of("games", T0, "live").frame
    clock.now = T0 + 2 * HOUR
    forged = game(lake, home_pts=99, correction_version=1, ingest_time=T0 - 6 * HOUR)
    lake.append("games", frame("games", [forged]))
    assert lake.as_of("games", T0, "live").frame.equals(before)
    stored = lake.scan("games").filter(pl.col("correction_version") == 1).collect()
    assert stored["ingest_time"].to_list() == [T0 + 2 * HOUR]


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


def test_correction_not_yet_public_falls_back(lake: Lake, clock: Clock) -> None:
    clock.now = T0 + SEC
    rows = [game(lake), game(lake, home_pts=31, correction_version=1, first_public_time=T0 + SEC)]
    lake.append("games", frame("games", rows))
    assert lake.as_of("games", T0, "replay").frame["home_pts"].to_list() == [28]
    assert lake.as_of("games", T0 + SEC, "replay").frame["home_pts"].to_list() == [31]


def test_correction_visible_while_original_is_not(lake: Lake, clock: Clock) -> None:
    clock.now = T0 + HOUR
    rows = [game(lake, first_public_time=T0 + SEC), game(lake, home_pts=31, correction_version=1)]
    lake.append("games", frame("games", rows))
    result = lake.as_of("games", T0, "replay").frame
    assert (result["home_pts"].to_list(), result["correction_version"].to_list()) == ([31], [1])


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
    assert (replay.coverage.dropped_unknown, replay.coverage.dropped_keys) == (0, ())
    assert scored.frame["game_id"].to_list() == ["g1", "g2", "g3"]
    assert scored.coverage.rows_visible == 4
    assert scored.coverage.rows_kept == 3
    assert scored.coverage.dropped_unknown == 1
    assert scored.coverage.dropped_keys == (("g4",),)
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


def test_coverage_can_be_scoped_to_a_season(lake: Lake) -> None:
    rows = [
        game(lake, "g1"),
        game(lake, "g2", vintage="unknown"),
        game(lake, "old", season=2019, vintage="unknown"),
    ]
    lake.append("games", frame("games", rows))
    scoped = lake.as_of("games", T0, "scored", season=2026)
    assert scoped.frame["game_id"].to_list() == ["g1"]
    assert (scoped.coverage.rows_visible, scoped.coverage.dropped_unknown) == (2, 1)
    assert lake.as_of("games", T0, "scored").coverage.rows_visible == 3


def test_as_of_rejects_bad_time_and_mode(lake: Lake) -> None:
    with pytest.raises(ValueError, match="timezone"):
        lake.as_of("games", datetime(2026, 11, 22, 7, 0), "replay")  # noqa: DTZ001
    with pytest.raises(ValueError, match="datetime"):
        lake.as_of("games", date(2026, 11, 22), "replay")  # type: ignore[arg-type]
    with pytest.raises(ValueError, match="mode"):
        lake.as_of("games", T0, "final")  # type: ignore[arg-type]
    with pytest.raises(ValueError, match="mode"):
        lake.open_ranking_view(T0, "final")  # type: ignore[arg-type]
    with pytest.raises(ValueError, match="mode"):
        PointInTimeView(lake, T0, "final")  # type: ignore[arg-type]


def test_as_of_accepts_non_utc_aware_time(lake: Lake) -> None:
    from zoneinfo import ZoneInfo

    lake.append("games", frame("games", [game(lake)]))
    eastern = datetime(2026, 11, 22, 2, 0, tzinfo=ZoneInfo("America/New_York"))
    assert eastern == T0
    assert lake.as_of("games", eastern, "live").frame.height == 1


def test_as_of_empty_table_has_schema(lake: Lake) -> None:
    result = lake.as_of("polls", T0, "scored")
    assert result.frame.height == 0
    assert result.frame.schema == TABLES["polls"].schema
    assert result.coverage.share_kept == 1.0


def test_as_of_refuses_tied_rows(lake: Lake) -> None:
    """Two stored rows with one (key, correction_version) are an integrity failure, not a silent double."""
    lake.append("games", frame("games", [game(lake)]))
    (original,) = list(lake.root.rglob("*.parquet"))
    original.with_name("part-smuggled.parquet").write_bytes(original.read_bytes())
    with pytest.raises(IntegrityError):
        lake.as_of("games", T0, "replay")


# --- DS-04: views --------------------------------------------------------------

FORBIDDEN = [
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
]


@pytest.mark.parametrize("table", FORBIDDEN)
def test_open_ranking_view_refuses_forbidden_tables(lake: Lake, table: str) -> None:
    with pytest.raises(ForbiddenTable):
        lake.open_ranking_view(T0).table(table)


def test_open_ranking_view_allows_only_three(lake: Lake) -> None:
    lake.append("games", frame("games", [game(lake)]))
    view = lake.open_ranking_view(T0)
    assert frozenset({"games", "teams", "membership"}) == OpenRankingView.ALLOWED
    assert view.table("games").height == 1
    assert view.table("teams").height == 0
    assert view.table("membership").height == 0


@pytest.mark.parametrize("table", ["polls", "lines", "committee_releases"])
def test_open_ranking_view_bypasses_are_closed(lake: Lake, table: str) -> None:
    view = lake.open_ranking_view(T0)
    # the view holds no lake
    assert not any(isinstance(getattr(view, slot, None), Lake) for slot in OpenRankingView.__slots__)
    assert not hasattr(view, "_OpenRankingView__lake")
    # its reader enforces the allow-list too
    with pytest.raises(ForbiddenTable):
        view._read(table, None)
    # widening the class attribute changes nothing
    original = OpenRankingView.ALLOWED
    try:
        OpenRankingView.ALLOWED = frozenset({table})  # type: ignore[misc]
        with pytest.raises(ForbiddenTable):
            view.table(table)
    finally:
        OpenRankingView.ALLOWED = original  # type: ignore[misc]
    # subclassing is refused
    with pytest.raises(TypeError):
        type("Wide", (OpenRankingView,), {"ALLOWED": frozenset({table})})


def test_views_module_exposes_no_lake_access() -> None:
    import cfp.store.views as views

    assert not hasattr(views, "Lake")
    assert not hasattr(views, "PointInTimeView")
    assert not hasattr(views, "as_of")


def test_open_ranking_view_reports_coverage_in_scored_mode(lake: Lake) -> None:
    lake.append("games", frame("games", [game(lake, "g1"), game(lake, "g2", vintage="unknown")]))
    view = lake.open_ranking_view(T0, "scored")
    assert view.table("games")["game_id"].to_list() == ["g1"]
    assert view.coverage["games"].dropped_unknown == 1
    assert view.coverage["games"].dropped_keys == (("g2",),)


def test_point_in_time_view_reads_any_table_and_collects_coverage(lake: Lake) -> None:
    lake.append("games", frame("games", [game(lake, "g1"), game(lake, "g2", vintage="unknown")]))
    view = PointInTimeView(lake, T0, "scored")
    assert view.table("games").height == 1
    assert view.table("polls").height == 0
    assert view.coverage["games"].dropped_unknown == 1
    assert set(view.coverage) == {"games", "polls"}


# --- lake: raw store -----------------------------------------------------------


def test_raw_is_content_addressed(lake: Lake) -> None:
    first = lake.put_raw(b'{"a": 1}')
    second = lake.put_raw(b'{"a": 1}')
    assert first == second == "f9d86028c6e0d64e225186f96acb69338b2c59764df79162107f5c4bb34d1310"
    assert lake.get_raw(first) == b'{"a": 1}'
    assert len([p for p in (lake.root / "raw").rglob("*") if p.is_file()]) == 1


def test_corrupt_raw_is_detected_and_repaired(lake: Lake) -> None:
    digest = lake.put_raw(b"payload")
    (path,) = [p for p in (lake.root / "raw").rglob("*") if p.is_file()]
    path.write_bytes(b"tampered")
    assert not lake.has_raw(digest)
    with pytest.raises(MissingRaw):
        lake.get_raw(digest)
    row = game(lake)
    row["raw_hash"] = digest
    with pytest.raises(MissingRaw):
        lake.append("games", frame("games", [row]))
    assert lake.put_raw(b"payload") == digest
    assert lake.get_raw(digest) == b"payload"


@pytest.mark.parametrize("bad", ["/etc/hosts", "../../x", "0" * 63, "G" * 64, ""])
def test_raw_hash_must_be_a_digest(lake: Lake, bad: str) -> None:
    assert not lake.has_raw(bad)
    row = game(lake)
    row["raw_hash"] = bad
    with pytest.raises(SchemaError, match="raw_hash"):
        lake.append("games", frame("games", [row]))


def test_append_requires_raw_payload(lake: Lake) -> None:
    row = game(lake)
    row["raw_hash"] = "0" * 64
    with pytest.raises(MissingRaw):
        lake.append("games", frame("games", [row]))


# --- lake: append rules ----------------------------------------------------------


def test_append_rejects_duplicate_key_and_version(lake: Lake) -> None:
    lake.append("games", frame("games", [game(lake)]))
    with pytest.raises(DuplicateRow):
        lake.append("games", frame("games", [game(lake, home_pts=99)]))
    with pytest.raises(DuplicateRow):
        lake.append("games", frame("games", [game(lake, "g9"), game(lake, "g9")]))
    with pytest.raises(DuplicateRow):  # same key and version filed under another season
        lake.append("games", frame("games", [game(lake, season=2025)]))
    assert lake.scan("games").collect().height == 1


def test_append_requires_versions_in_order(lake: Lake) -> None:
    with pytest.raises(CorrectionOrder):  # a new key must start at 0
        lake.append("games", frame("games", [game(lake, correction_version=1)]))
    lake.append("games", frame("games", [game(lake)]))
    with pytest.raises(CorrectionOrder):  # no gaps
        lake.append("games", frame("games", [game(lake, correction_version=2)]))
    with pytest.raises(CorrectionOrder):
        lake.append("games", frame("games", [game(lake, "g2"), game(lake, "g2", correction_version=2)]))
    lake.append("games", frame("games", [game(lake, correction_version=1), game(lake, correction_version=2)]))
    assert sorted(lake.scan("games").collect()["correction_version"].to_list()) == [0, 1, 2]


def test_append_validates_schema(lake: Lake, clock: Clock) -> None:
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
        lake.append("games", good.with_columns(pl.lit(None, dtype=pl.String).alias("game_id")))
    with pytest.raises(SchemaError, match="correction_version"):
        lake.append("games", good.with_columns(pl.lit(-1, dtype=pl.Int32).alias("correction_version")))
    with pytest.raises(SchemaError, match="ingested before it is public"):
        lake.append("games", good.with_columns(pl.lit(clock.now + SEC).cast(TS).alias("first_public_time")))
    with pytest.raises(KeyError):
        lake.append("nope", good)
    assert parquet_files(lake) == {}


def test_append_is_partitioned_by_season_and_never_rewrites(lake: Lake) -> None:
    lake.append("games", frame("games", [game(lake, "g1"), game(lake, "g2", season=2025)]))
    before = parquet_files(lake)
    assert sorted(f.rsplit("/", 1)[0] for f in before) == [
        "normalized/games/season=2025",
        "normalized/games/season=2026",
    ]
    for name, payload in before.items():
        seasons = pl.read_parquet(payload)["season"].unique().to_list()
        assert seasons == [int(name.split("season=")[1].split("/")[0])]
    lake.append("games", frame("games", [game(lake, "g3")]))
    after = parquet_files(lake)
    assert len(after) == 3
    assert {name: after[name] for name in before} == before  # old files are byte-identical
    assert lake.scan("games").collect().height == 3


def test_append_table_without_season(lake: Lake) -> None:
    raw = lake.put_raw(b"teams")
    row = {
        "team_id": "t1",
        "name": "Team One",
        "cfbd_id": 1,
        "espn_id": None,
        "kalshi_code": None,
        "source_id": "test",
        "event_time": T0 - 7 * HOUR,
        "first_public_time": T0 - 7 * HOUR,
        "ingest_time": None,
        "correction_version": 0,
        "raw_hash": raw,
        "vintage": "live",
    }
    lake.append("teams", frame("teams", [row]))
    assert [p.parent.name for p in (lake.root / "normalized" / "teams").rglob("*.parquet")] == ["all"]
    with pytest.raises(DuplicateRow):
        lake.append("teams", frame("teams", [row]))
    assert lake.open_ranking_view(T0).table("teams")["team_id"].to_list() == ["t1"]


def test_append_same_batch_twice_is_rejected_not_duplicated(lake: Lake) -> None:
    batch = frame("games", [game(lake)])
    lake.append("games", batch)
    with pytest.raises(DuplicateRow):
        lake.append("games", batch)
    assert lake.scan("games").collect().height == 1


def test_failed_multi_season_batch_leaves_nothing_and_can_be_retried(
    lake: Lake, monkeypatch: pytest.MonkeyPatch
) -> None:
    batch = frame("games", [game(lake, "g1", season=2025), game(lake, "g2", season=2026)])
    real_write = Lake._write_staged
    calls = {"n": 0}

    def flaky(tmp: Path, payload: bytes) -> None:
        calls["n"] += 1
        if calls["n"] == 2:
            raise OSError("disk full")
        real_write(tmp, payload)

    monkeypatch.setattr(Lake, "_write_staged", staticmethod(flaky))
    with pytest.raises(OSError, match="disk full"):
        lake.append("games", batch)
    assert parquet_files(lake) == {}
    assert not list(lake.root.rglob("*.tmp"))
    monkeypatch.setattr(Lake, "_write_staged", staticmethod(real_write))
    lake.append("games", batch)
    assert sorted(lake.scan("games").collect()["game_id"].to_list()) == ["g1", "g2"]


# --- budget ---------------------------------------------------------------------


def test_as_of_one_million_rows_under_one_second(tmp_path: Path) -> None:
    """Lake-backed Parquet, three correction versions per key, one row in ten of unknown vintage."""
    n, versions = 1_000_000, 3
    clock = Clock(T0 + 2 * HOUR)
    lake = Lake(tmp_path / "big", clock=clock)
    raw = lake.put_raw(b"quotes")
    spec = TABLES["market_quotes"]
    key_no = pl.col("i") // versions
    stamp = pl.lit(T0) - pl.duration(seconds=key_no * 2)
    quotes = (
        pl.DataFrame({"i": pl.int_range(n - n % versions, eager=True)})
        .select(
            pl.lit("kalshi").alias("venue"),
            (pl.lit("KX-") + (key_no % 250).cast(pl.String)).alias("ticker"),
            stamp.alias("ts_utc"),
            pl.lit(2026, dtype=pl.Int32).alias("season"),
            (pl.col("i") % versions).cast(pl.Float64).alias("bid"),
            pl.lit(0.52).alias("ask"),
            pl.lit(10.0).alias("bid_size"),
            pl.lit(10.0).alias("ask_size"),
            pl.lit(0.51).alias("last"),
            pl.lit("kalshi").alias("source_id"),
            stamp.alias("event_time"),
            (stamp + pl.duration(hours=1)).alias("first_public_time"),
            pl.lit(None).alias("ingest_time"),
            (pl.col("i") % versions).cast(pl.Int32).alias("correction_version"),
            pl.lit(raw).alias("raw_hash"),
            pl.when(key_no % 10 == 0).then(pl.lit("unknown")).otherwise(pl.lit("live")).alias("vintage"),
        )
        .cast(dict(spec.schema))
    )
    lake.append("market_quotes", quotes)
    lake.as_of("market_quotes", T0, "scored")  # warm-up
    best = float("inf")
    for _ in range(3):
        start = time.perf_counter()
        result = lake.as_of("market_quotes", T0, "scored")
        best = min(best, time.perf_counter() - start)
    keys = n // versions
    visible = keys - 1800  # keys whose first_public_time (ts + 1 h) is after T0: 3600 s / 2 s per key
    assert result.coverage.rows_visible == visible
    unknown = len(range(1800, keys, 10))  # visible keys are numbers 1800 and up; every tenth is unknown
    assert result.coverage.dropped_unknown == unknown
    assert result.frame.height == visible - unknown
    assert result.frame["correction_version"].unique().to_list() == [versions - 1]
    assert result.frame["bid"].unique().to_list() == [float(versions - 1)]
    print(f"as_of over {quotes.height:,} lake rows: {best * 1000:.0f} ms")
    assert best < 1.0


def test_as_of_function_matches_lake_method(lake: Lake) -> None:
    lake.append("games", frame("games", [game(lake)]))
    direct = as_of(lake.scan("games"), TABLES["games"], T0 + timedelta(0), "replay")
    assert direct.frame.equals(lake.as_of("games", T0, "replay").frame)
