"""CFBD parsers. Payloads here are hand-written in the shape of CFBD's OpenAPI schema (v5.34), with made-up
teams; recorded fixtures replace them once live calls are possible (docs/DATA_GAPS.md)."""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import polars as pl
import pytest

from cfp.ingest.cfbd import RESERVE, allowance
from cfp.ingest.cfbd_normalize import game_rows, is_title_game, line_rows, poll_rows
from cfp.ingest.errors import SourceError
from cfp.ingest.http import Fetched
from cfp.ingest.upsert import upsert
from cfp.store.lake import Lake

from .store_helpers import Clock

NOW = datetime(2026, 11, 25, 15, 0, tzinfo=UTC)


def cfbd_game(game_id: int, **over: Any) -> dict[str, Any]:
    game: dict[str, Any] = {
        "id": game_id,
        "season": 2025,
        "week": 13,
        "seasonType": "regular",
        "startDate": "2025-11-23T03:30:00.000Z",  # Saturday 22:30 ET
        "completed": True,
        "neutralSite": False,
        "venue": "Made-up Stadium",
        "homeId": 1,
        "homeClassification": "fbs",
        "homePoints": 31,
        "awayId": 2,
        "awayClassification": "fbs",
        "awayPoints": 17,
        "notes": None,
    }
    return game | over


def fetched(lake: Lake, payload: Any, at: datetime = NOW) -> Fetched:
    body = json.dumps(payload).encode()
    return Fetched("cfbd", "https://example.test/games", lake.put_raw(body), body, at)


def test_backfill_final_is_public_four_and_a_half_hours_after_kickoff(tmp_path: Path) -> None:
    lake = Lake(tmp_path, clock=Clock(NOW))
    got = fetched(lake, [cfbd_game(401)])
    rows, left_out = game_rows(got, live=False)
    assert left_out == []
    upsert(lake, "games", rows, got.fetched_at, "asserted")
    row = lake.scan("games").collect().row(0, named=True)
    assert (row["status"], row["correction_version"], row["vintage"]) == ("final", 0, "reconstructed")
    assert row["first_public_time"] == datetime(2025, 11, 23, 8, 0, tzinfo=UTC)  # 03:00 ET Sunday
    assert row["raw_hash"] == got.raw_hash
    assert (row["game_id"], row["home_id"], row["away_id"]) == ("cfbd-401", "cfbd-1", "cfbd-2")
    assert (row["home_pts"], row["away_pts"], row["home_div"], row["site"]) == (
        31,
        17,
        "fbs",
        "Made-up Stadium",
    )
    sunday_cutoff = datetime(2025, 11, 23, 7, 0, tzinfo=UTC)  # 02:00 ET
    assert lake.as_of("games", sunday_cutoff, "replay").frame.height == 0
    assert lake.as_of("games", datetime(2025, 11, 23, 8, 0, tzinfo=UTC), "replay").frame.height == 1


def test_no_row_claims_a_past_schedule(tmp_path: Path) -> None:
    """An unplayed game of a past season is left out; nothing is public before a result could be."""
    lake = Lake(tmp_path, clock=Clock(NOW))
    title = cfbd_game(403, week=15, neutralSite=True, notes=None)  # a title game CFBD did not label
    cancelled = cfbd_game(404, completed=False, homePoints=None, awayPoints=None)
    rows, left_out = game_rows(fetched(lake, [title, cancelled]), live=False)
    assert left_out == ["cfbd-404"]
    assert rows["game_id"].to_list() == ["cfbd-403"]
    assert (rows["first_public_time"] >= rows["start_utc"]).all()


def test_live_unplayed_game_is_public_when_captured(tmp_path: Path) -> None:
    lake = Lake(tmp_path, clock=Clock(NOW))
    upcoming = cfbd_game(402, completed=False, homePoints=None, awayPoints=None, season=2026)
    upcoming["startDate"] = "2026-11-28T17:00:00.000Z"
    rows, left_out = game_rows(fetched(lake, [upcoming]), live=True)
    assert left_out == []
    assert rows.select("status", "home_pts", "vintage", "first_public_time").row(0) == (
        "scheduled",
        None,
        "live",
        NOW,
    )


def test_live_catch_up_is_reconstructed_unless_recent(tmp_path: Path) -> None:
    lake = Lake(tmp_path, clock=Clock(NOW))
    september = cfbd_game(1, season=2026, startDate="2026-09-05T19:30:00.000Z")
    last_week = cfbd_game(2, season=2026, startDate="2026-11-21T17:00:00.000Z")
    rows, _ = game_rows(fetched(lake, [september, last_week]), live=True)
    assert rows["vintage"].to_list() == ["reconstructed", "live"]
    assert rows["first_public_time"].to_list()[0] == datetime(2026, 9, 6, 0, 0, tzinfo=UTC)


def test_title_note_classification_and_placeholder_time(tmp_path: Path) -> None:
    lake = Lake(tmp_path, clock=Clock(NOW))
    title = cfbd_game(403, week=15, neutralSite=True, notes="Made-up Conference Championship")
    bowl = cfbd_game(404, seasonType="postseason", week=1, notes="National Championship")
    odd = cfbd_game(405, awayClassification=None)
    spring = cfbd_game(406, seasonType="spring_regular")
    tbd = cfbd_game(407, startDate="2025-11-22T05:00:00.000Z", startTimeTBD=True)
    assert is_title_game(title)
    assert not is_title_game(bowl)
    rows, _ = game_rows(fetched(lake, [title, bowl, odd, spring, tbd]), live=False)
    assert rows["game_id"].to_list() == ["cfbd-403", "cfbd-404", "cfbd-405", "cfbd-407"]
    assert rows["title_game"].to_list() == [True, False, False, False]
    assert rows["away_div"].to_list() == ["fbs", "fbs", "unknown", "fbs"]
    assert rows["first_public_time"].to_list()[3] == datetime(
        2025, 11, 23, 9, 29, tzinfo=UTC
    )  # end of day + 4.5 h


def test_broken_games_fail_loudly(tmp_path: Path) -> None:
    lake = Lake(tmp_path, clock=Clock(NOW))
    with pytest.raises(SourceError, match="without a score"):
        game_rows(fetched(lake, [cfbd_game(1, homePoints=None)]), live=False)
    lower = cfbd_game(2, homePoints=None, homeClassification="iii", awayClassification=None)
    rows, left_out = game_rows(fetched(lake, [lower]), live=True)  # no FBS team: left out, never scored
    assert (rows.height, left_out) == (0, ["cfbd-2"])
    with pytest.raises(SourceError, match="no start time"):
        game_rows(fetched(lake, [cfbd_game(1, startDate=None)]), live=False)
    with pytest.raises(SourceError, match="neutral-site"):
        game_rows(fetched(lake, [cfbd_game(1, neutralSite=None)]), live=False)


def test_polls_keep_ap_and_coaches_and_are_dated_by_rule(tmp_path: Path) -> None:
    lake = Lake(tmp_path, clock=Clock(NOW))
    ranks = [{"rank": 1, "teamId": 1, "school": "A", "firstPlaceVotes": 60, "points": 1550}]
    ranks.append({"rank": 2, "teamId": 2, "school": "B", "firstPlaceVotes": 2, "points": 1480})
    polls = [
        {"poll": name, "ranks": ranks} for name in ("AP Top 25", "Coaches Poll", "Playoff Committee Rankings")
    ]
    payload = [
        {"season": 2025, "seasonType": "regular", "week": 1, "polls": polls[:2]},
        {"season": 2025, "seasonType": "regular", "week": 13, "polls": polls},
        {"season": 2025, "seasonType": "postseason", "week": 1, "polls": polls[:1]},
    ]
    kickoffs = [
        (1, datetime(2025, 8, 30, 16, 0, tzinfo=UTC)),
        (12, datetime(2025, 11, 16, 3, 30, tzinfo=UTC)),
    ]
    rows = poll_rows(fetched(lake, payload), kickoffs, live=False)
    assert sorted(set(rows["poll"].to_list())) == ["ap", "coaches"]
    assert sorted(set(rows["week"].to_list())) == [1, 13]
    week13 = rows.filter((rows["week"] == 13) & (rows["poll"] == "ap")).sort("rank")
    assert week13["team_id"].to_list() == ["cfbd-1", "cfbd-2"]
    assert week13["points"].to_list() == [1550, 1480]
    # week 12 ended Saturday 15 Nov (ET); the week-13 poll is public Tuesday 18 Nov 17:00 ET
    assert set(week13["first_public_time"].to_list()) == {datetime(2025, 11, 18, 22, 0, tzinfo=UTC)}
    preseason = rows.filter(rows["week"] == 1)
    assert set(preseason["first_public_time"].to_list()) == {datetime(2025, 8, 30, 16, 0, tzinfo=UTC)}
    assert set(rows["vintage"].to_list()) == {"reconstructed"}
    upsert(lake, "polls", rows, NOW, "asserted")
    # a poll stored with a wrong public time is put right by a new version, and only when asked
    wrong = datetime(2025, 12, 16, 22, 0, tzinfo=UTC)
    late = Lake(tmp_path / "late", clock=Clock(NOW))
    rows = poll_rows(fetched(late, payload), kickoffs, live=False)
    upsert(
        late,
        "polls",
        rows.with_columns(first_public_time=pl.lit(wrong).cast(rows.schema["first_public_time"])),
        NOW,
        "asserted",
    )
    between = datetime(2025, 11, 30, 7, 0, tzinfo=UTC)
    assert late.as_of("polls", between, "replay").frame.height == 0
    assert upsert(late, "polls", rows, NOW, "asserted").corrected == 0
    fixed = upsert(late, "polls", rows, NOW, "asserted", redate=True)
    assert fixed.corrected == rows.height
    seen = late.as_of("polls", between, "replay").frame
    assert seen.filter(seen["week"] == 13).height == 4
    assert set(seen["correction_version"].to_list()) == {1}
    assert upsert(late, "polls", rows, NOW, "asserted", redate=True).corrected == 0
    with pytest.raises(SourceError):
        poll_rows(fetched(lake, payload), [], live=False)
    with pytest.raises(SourceError, match="week 12"):  # week 12's games are missing
        poll_rows(fetched(lake, payload), kickoffs[:1], live=False)
    # a December game filed under week 1 would date every later poll after the season: refused
    stray = [*kickoffs, (1, datetime(2025, 12, 13, 18, 0, tzinfo=UTC))]
    later = [*payload, {"season": 2025, "seasonType": "regular", "week": 2, "polls": polls[:2]}]
    with pytest.raises(SourceError, match="same public time"):
        poll_rows(fetched(lake, later), stray, live=False)


def test_lines_one_row_per_provider(tmp_path: Path) -> None:
    lake = Lake(tmp_path, clock=Clock(NOW))
    lines = [
        {"provider": "BookA", "spread": -6.5, "overUnder": 51.5, "homeMoneyline": -240, "awayMoneyline": 195},
        {"provider": "BookB", "spread": -7, "overUnder": None, "homeMoneyline": None, "awayMoneyline": None},
        {
            "provider": "Empty",
            "spread": None,
            "overUnder": None,
            "homeMoneyline": None,
            "awayMoneyline": None,
        },
    ]
    payload = [{"id": 401, "season": 2025, "startDate": "2025-11-23T03:30:00.000Z", "lines": lines}]
    rows = line_rows(fetched(lake, payload), live=False).sort("provider")
    assert rows["provider"].to_list() == ["BookA", "BookB"]
    assert rows["ml_home"].to_list() == [-240.0, None]
    assert rows["spread"].to_list() == [-6.5, -7.0]
    assert set(rows["first_public_time"].to_list()) == {datetime(2025, 11, 23, 8, 0, tzinfo=UTC)}
    upsert(lake, "lines", rows, NOW, "asserted")


def test_reserve_holds_through_30_november() -> None:
    assert allowance(datetime(2026, 11, 25, 12, 0, tzinfo=UTC)) == 1000 - RESERVE == 700
    assert allowance(datetime(2026, 12, 1, 4, 59, tzinfo=UTC)) == 700  # 23:59 ET, 30 Nov
    assert allowance(datetime(2026, 12, 1, 5, 0, tzinfo=UTC)) == 1000


def _season(tmp_path: Path, season: int, clock: Clock, state: dict[str, Any]) -> tuple[Lake, Any]:
    from cfp.ingest.cfbd import Cfbd
    from cfp.ingest.http import Budget, Fetcher, Response, TokenBucket

    lake = Lake(tmp_path, clock=clock)

    def transport(url: str, headers: Any, timeout: float) -> Response:
        state["urls"].append(url)
        clock.now += timedelta(seconds=state.get("latency", 0))  # the reply arrives later than the request
        kind = "regular" if "seasonType=regular" in url else "postseason"
        return Response(200, json.dumps(state.get(kind, [])).encode(), {})

    fetcher = Fetcher(
        lake,
        "cfbd",
        "https://api.example.test",
        budget=Budget(tmp_path / "budget.json", clock=clock),
        allowance=100,
        bucket=TokenBucket(1000.0, 1000.0),
        transport=transport,
        clock=clock,
    )
    return lake, Cfbd(fetcher)


def test_live_season_ingest_end_to_end(tmp_path: Path) -> None:
    from cfp.ingest import run

    clock = Clock(datetime(2026, 11, 28, 17, 0, tzinfo=UTC))
    played = cfbd_game(1, season=2026, startDate="2026-11-21T17:00:00.000Z", week=13)
    tonight = cfbd_game(2, season=2026, startDate="2026-11-29T00:30:00.000Z", week=14, completed=False)
    tonight |= {"homePoints": None, "awayPoints": None}
    state: dict[str, Any] = {"regular": [played, tonight], "urls": []}
    lake, cfbd = _season(tmp_path, 2026, clock, state)

    run.ingest_cfbd_season(lake, cfbd, 2026, ["games"])
    # The request leaves at 01:58 ET and the reply showing the final arrives at 02:01 ET, after the cutoff.
    clock.now = datetime(2026, 11, 29, 6, 58, tzinfo=UTC)
    state["latency"] = 90
    state["regular"] = [played, tonight | {"completed": True, "homePoints": 24, "awayPoints": 21}]
    run.ingest_cfbd_season(lake, cfbd, 2026, ["games"])
    state["latency"] = 0
    unchanged = run.ingest_cfbd_season(lake, cfbd, 2026, ["games"])
    assert sum(r.new + r.corrected for r in unchanged.results) == 0

    stored = lake.scan("games").collect().sort("game_id", "correction_version")
    assert stored.select("game_id", "correction_version", "status").rows() == [
        ("cfbd-1", 0, "final"),
        ("cfbd-2", 0, "scheduled"),
        ("cfbd-2", 1, "final"),
    ]
    public = stored["first_public_time"].to_list()
    assert public[0] == datetime(2026, 11, 21, 21, 30, tzinfo=UTC)  # rule time, already past at first capture
    assert public[2] == datetime(
        2026, 11, 29, 7, 1, tzinfo=UTC
    )  # when the payload arrived, not when we asked
    cutoff = datetime(2026, 11, 29, 7, 0, tzinfo=UTC)
    for mode in ("live", "replay"):  # a final that arrived after the cutoff waits, in both modes
        assert lake.as_of("games", cutoff, mode).frame.sort("game_id")["status"].to_list() == [
            "final",
            "scheduled",
        ]
    assert len(state["urls"]) == 6  # the live season is refetched, never reused


def test_source_revert_does_not_unfinalise_a_game(tmp_path: Path) -> None:
    from cfp.ingest import run

    clock = Clock(datetime(2026, 11, 28, 17, 0, tzinfo=UTC))
    played = cfbd_game(1, season=2026, startDate="2026-11-21T17:00:00.000Z")
    state: dict[str, Any] = {"regular": [played], "urls": []}
    lake, cfbd = _season(tmp_path, 2026, clock, state)
    run.ingest_cfbd_season(lake, cfbd, 2026, ["games"])
    state["regular"] = [played | {"completed": False, "homePoints": None, "awayPoints": None}]
    report = run.ingest_cfbd_season(lake, cfbd, 2026, ["games"])
    assert any("no longer marks as final" in note and "cfbd-1" in note for note in report.notes)
    assert lake.scan("games").collect()["status"].to_list() == ["final"]


def test_game_in_both_payloads_fails_loudly(tmp_path: Path) -> None:
    from cfp.ingest import run

    clock = Clock(datetime(2026, 11, 28, 17, 0, tzinfo=UTC))
    game = cfbd_game(1, season=2026, startDate="2026-11-21T17:00:00.000Z")
    state: dict[str, Any] = {
        "regular": [game],
        "postseason": [game | {"seasonType": "postseason"}],
        "urls": [],
    }
    lake, cfbd = _season(tmp_path, 2026, clock, state)
    with pytest.raises(ValueError, match="twice"):
        run.ingest_cfbd_season(lake, cfbd, 2026, ["games"])
    assert lake.scan("games").collect().height == 0


def test_past_season_is_reconstructed_and_fetched_once(tmp_path: Path) -> None:
    from cfp.ingest import run

    clock = Clock(NOW)
    state: dict[str, Any] = {"regular": [cfbd_game(401), cfbd_game(402, completed=False)], "urls": []}
    lake, cfbd = _season(tmp_path, 2025, clock, state)
    report = run.ingest_cfbd_season(lake, cfbd, 2025, ["games"])
    assert report.notes == ["2025 regular: 1 games left out (unplayed or no score)"]
    run.ingest_cfbd_season(lake, cfbd, 2025, ["games"])
    assert len(state["urls"]) == 2
    stored = lake.scan("games").collect()
    assert stored.select("game_id", "vintage").rows() == [("cfbd-401", "reconstructed")]


# --- recorded CFBD responses (trimmed by scripts/build_release_fixtures.py) -------------------------------

FIX = Path(__file__).resolve().parents[1] / "fixtures"


def recorded(lake: Lake, name: str) -> Fetched:
    return fetched(lake, json.loads((FIX / name).read_text()))


def test_recorded_title_week_has_nine_title_games_four_on_campus(tmp_path: Path) -> None:
    lake = Lake(tmp_path, clock=Clock(NOW))
    rows, left_out = game_rows(recorded(lake, "cfbd_games_2025_w15.json"), live=False)
    assert left_out == []
    assert rows.height == 12
    titles = rows.filter(rows["title_game"])
    assert titles.height == 9
    assert titles.filter(~titles["neutral"]).height == 4  # the official site flag, not forced neutral
    assert set(titles["home_div"].to_list()) | set(titles["away_div"].to_list()) == {"fbs"}
    assert rows.filter(~rows["title_game"])["home_div"].to_list() == ["iii", "iii", "fcs"]  # playoff rounds
    upsert(lake, "games", rows, NOW, "asserted")


def test_recorded_week_one_named_games_are_not_title_games(tmp_path: Path) -> None:
    lake = Lake(tmp_path, clock=Clock(NOW))
    rows, _ = game_rows(recorded(lake, "cfbd_games_2025_w1_sample.json"), live=False)
    assert rows.height == 5
    assert not rows["title_game"].any()
    assert rows["away_div"].to_list()[-1] == "unknown"


def test_recorded_preseason_poll(tmp_path: Path) -> None:
    lake = Lake(tmp_path, clock=Clock(NOW))
    first_kickoff = datetime(2025, 8, 23, 16, 0, tzinfo=UTC)
    rows = poll_rows(recorded(lake, "cfbd_rankings_2025_w1.json"), [(1, first_kickoff)], live=False)
    ap = rows.filter(rows["poll"] == "ap").sort("rank")
    assert ap.height == 25
    assert ap.select("team_id", "points", "fpv").row(0) == ("cfbd-251", 1552, 25)  # Texas, preseason No. 1
    assert sorted(set(rows["poll"].to_list())) == ["ap", "coaches"]
    assert set(rows["first_public_time"].to_list()) == {first_kickoff}
    upsert(lake, "polls", rows, NOW, "asserted")


def test_recorded_cfbd_committee_ranking_matches_the_cfp_site(tmp_path: Path) -> None:
    """CFBD's week-11 committee ranking is the CFP site's first 2025 release, team for team."""
    from cfp.ingest.cfp_releases import cross_check, load_aliases, parse_cfbd, parse_site, resolve

    root = Path(__file__).resolve().parents[2]
    aliases = load_aliases(root / "data" / "aliases_cfp_site.csv")
    release = parse_site(json.loads((FIX / "cfp_site_rankings_2025_first.json").read_text()), 2025)[0]
    lists = parse_cfbd(json.loads((FIX / "cfbd_rankings_2025_w11.json").read_text()))
    assert len(lists) == 1
    cross_check(release, resolve(release, aliases), lists[0], "cfbd")


def test_recorded_lines(tmp_path: Path) -> None:
    lake = Lake(tmp_path, clock=Clock(NOW))
    rows = line_rows(recorded(lake, "cfbd_lines_2025_w1_sample.json"), live=False)
    assert rows.height >= 2
    assert rows["spread"].null_count() < rows.height
    assert (rows["first_public_time"] > rows["as_of_utc"]).all()
    upsert(lake, "lines", rows, NOW, "asserted")


# --- AP votes outside the top 25, from ESPN (SC-03) ---------------------------------


def _espn_ap(points_shift: int = 0, others: list[tuple[int, int]] | None = None) -> bytes:
    import json

    ranks = [
        {
            "current": r,
            "points": 1600 - 50 * r + points_shift,
            "team": {"id": str(100 + r), "location": f"S{r}"},
        }
        for r in range(1, 26)
    ]
    rows = [{"current": 0, "points": p, "team": {"id": str(i), "location": "x"}} for i, p in others or []]
    payload = {"rankings": [{"type": "cfp", "ranks": []}, {"type": "ap", "ranks": ranks, "others": rows}]}
    return json.dumps(payload).encode()


def test_ap_others_take_the_week_and_public_time_of_the_matching_stored_poll(tmp_path: Path) -> None:
    import polars as pl

    from cfp.ingest.errors import SourceError
    from cfp.ingest.espn_polls import others_rows
    from cfp.ingest.http import Fetched

    lake = Lake(tmp_path / "lake")
    public = datetime(2026, 11, 24, 22, 0, tzinfo=UTC)
    stored = pl.DataFrame(
        {
            "season": [2026] * 50,
            "week": [12] * 25 + [13] * 25,
            "team_id": [f"cfbd-{100 + r}" for r in range(1, 26)] * 2,
            "rank": list(range(1, 26)) * 2,
            "points": [1500 - 50 * r for r in range(1, 26)] + [1600 - 50 * r for r in range(1, 26)],
            "first_public_time": [public - timedelta(days=7)] * 25 + [public] * 25,
        }
    )
    ids = {100 + r: f"cfbd-{100 + r}" for r in range(1, 26)} | {300: "cfbd-300", 301: "cfbd-301"}

    def got(body: bytes) -> Fetched:
        return Fetched(
            "espn", "https://example.test/rankings", lake.put_raw(body), body, public + timedelta(hours=1)
        )

    rows = others_rows(got(_espn_ap(others=[(300, 40), (999, 31), (301, 2)])), stored, ids, live=True)
    assert rows.select("team_id", "points", "week").rows() == [("cfbd-300", 40, 13), ("cfbd-301", 2, 13)]
    assert rows["rank"].null_count() == 2
    assert rows["others_votes"].all()
    assert set(rows["first_public_time"]) == {public}
    assert set(rows["vintage"]) == {"live"}
    with pytest.raises(SourceError, match="matches 0 stored polls"):
        others_rows(got(_espn_ap(points_shift=1, others=[(300, 40)])), stored, ids, live=True)
    with pytest.raises(SourceError, match="not matched"):
        others_rows(got(_espn_ap(others=[(300, 40)])), stored, {300: "cfbd-300"}, live=True)
    with pytest.raises(SourceError, match="no votes outside"):
        others_rows(got(_espn_ap()), stored, ids, live=True)
