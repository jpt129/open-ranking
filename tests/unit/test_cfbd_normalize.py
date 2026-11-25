"""CFBD parsers. Payloads here are hand-written in the shape of CFBD's OpenAPI schema (v5.34), with made-up
teams; recorded fixtures replace them once live calls are possible (docs/DATA_GAPS.md)."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

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


def fetched(lake: Lake, payload: Any) -> Fetched:
    body = json.dumps(payload).encode()
    return Fetched("cfbd", "https://example.test/games", lake.put_raw(body), body, NOW)


def test_backfill_game_becomes_scheduled_then_final(tmp_path: Path) -> None:
    lake = Lake(tmp_path, clock=Clock(NOW))
    got = fetched(lake, [cfbd_game(401)])
    scheduled, final = game_rows(got, "reconstructed")
    upsert(lake, "games", scheduled, NOW, "asserted")
    upsert(lake, "games", final, NOW, "asserted")
    stored = lake.scan("games").collect().sort("correction_version")
    assert stored["status"].to_list() == ["scheduled", "final"]
    assert stored["first_public_time"].to_list() == [
        datetime(2025, 8, 1, 4, 0, tzinfo=UTC),
        datetime(2025, 11, 23, 8, 0, tzinfo=UTC),  # kickoff + 4.5 h = 03:00 ET
    ]
    assert set(stored["vintage"].to_list()) == {"reconstructed"}
    assert set(stored["raw_hash"].to_list()) == {got.raw_hash}
    row = stored.row(1, named=True)
    assert (row["game_id"], row["home_id"], row["away_id"]) == ("cfbd-401", "cfbd-1", "cfbd-2")
    assert (row["home_pts"], row["away_pts"], row["home_div"], row["site"]) == (
        31,
        17,
        "fbs",
        "Made-up Stadium",
    )
    sunday_cutoff = datetime(2025, 11, 23, 7, 0, tzinfo=UTC)  # 02:00 ET
    assert lake.as_of("games", sunday_cutoff, "replay").frame["status"].to_list() == ["scheduled"]


def test_unplayed_game_has_only_a_scheduled_row(tmp_path: Path) -> None:
    lake = Lake(tmp_path, clock=Clock(NOW))
    upcoming = cfbd_game(402, completed=False, homePoints=None, awayPoints=None, season=2026)
    upcoming["startDate"] = "2026-11-28T17:00:00.000Z"
    scheduled, final = game_rows(fetched(lake, [upcoming]), "live")
    assert (scheduled.height, final.height) == (1, 0)
    assert scheduled["home_pts"].to_list() == [None]


def test_title_game_and_other_classifications(tmp_path: Path) -> None:
    lake = Lake(tmp_path, clock=Clock(NOW))
    title = cfbd_game(403, week=15, neutralSite=True, notes="Made-up Conference Championship")
    bowl = cfbd_game(404, seasonType="postseason", week=1, notes="National Championship")
    odd = cfbd_game(405, awayClassification=None)
    spring = cfbd_game(406, seasonType="spring_regular")
    assert is_title_game(title)
    assert not is_title_game(bowl)
    scheduled, final = game_rows(fetched(lake, [title, bowl, odd, spring]), "reconstructed")
    assert scheduled["game_id"].to_list() == ["cfbd-403", "cfbd-404", "cfbd-405"]
    assert final["title_game"].to_list() == [True, False, False]
    assert final["away_div"].to_list() == ["fbs", "fbs", "other"]
    # title and postseason pairings are known only at kickoff
    assert scheduled["first_public_time"].to_list()[:2] == scheduled["start_utc"].to_list()[:2]


def test_broken_games_fail_loudly(tmp_path: Path) -> None:
    lake = Lake(tmp_path, clock=Clock(NOW))
    with pytest.raises(SourceError, match="without a score"):
        game_rows(fetched(lake, [cfbd_game(1, homePoints=None)]), "reconstructed")
    with pytest.raises(SourceError, match="no start time"):
        game_rows(fetched(lake, [cfbd_game(1, startDate=None)]), "reconstructed")


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
    rows = poll_rows(fetched(lake, payload), kickoffs, "reconstructed")
    assert sorted(set(rows["poll"].to_list())) == ["ap", "coaches"]
    assert sorted(set(rows["week"].to_list())) == [1, 13]
    week13 = rows.filter((rows["week"] == 13) & (rows["poll"] == "ap")).sort("rank")
    assert week13["team_id"].to_list() == ["cfbd-1", "cfbd-2"]
    assert week13["points"].to_list() == [1550, 1480]
    # week 12 ended Saturday 15 Nov (ET); the week-13 poll is public Tuesday 18 Nov 17:00 ET
    assert set(week13["first_public_time"].to_list()) == {datetime(2025, 11, 18, 22, 0, tzinfo=UTC)}
    preseason = rows.filter(rows["week"] == 1)
    assert set(preseason["first_public_time"].to_list()) == {datetime(2025, 8, 30, 16, 0, tzinfo=UTC)}
    upsert(lake, "polls", rows, NOW, "asserted")
    with pytest.raises(SourceError):
        poll_rows(fetched(lake, payload), [], "reconstructed")


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
    rows = line_rows(fetched(lake, payload), "reconstructed").sort("provider")
    assert rows["provider"].to_list() == ["BookA", "BookB"]
    assert rows["ml_home"].to_list() == [-240.0, None]
    assert rows["spread"].to_list() == [-6.5, -7.0]
    assert set(rows["first_public_time"].to_list()) == {datetime(2025, 11, 23, 8, 0, tzinfo=UTC)}
    upsert(lake, "lines", rows, NOW, "asserted")


def test_reserve_holds_through_30_november() -> None:
    assert allowance(datetime(2026, 11, 25, 12, 0, tzinfo=UTC)) == 1000 - RESERVE == 700
    assert allowance(datetime(2026, 12, 1, 4, 59, tzinfo=UTC)) == 700  # 23:59 ET, 30 Nov
    assert allowance(datetime(2026, 12, 1, 5, 0, tzinfo=UTC)) == 1000


def test_live_season_ingest_end_to_end(tmp_path: Path) -> None:
    """First capture: played games carry rule times. Later capture: a new final is public when we saw it."""
    from cfp.ingest import run
    from cfp.ingest.cfbd import Cfbd
    from cfp.ingest.http import Budget, Fetcher, Response, TokenBucket

    clock = Clock(datetime(2026, 11, 28, 17, 0, tzinfo=UTC))
    lake = Lake(tmp_path, clock=clock)
    played = cfbd_game(1, season=2026, startDate="2026-11-21T17:00:00.000Z", week=13)
    tonight = cfbd_game(2, season=2026, startDate="2026-11-29T00:30:00.000Z", week=14, completed=False)
    tonight |= {"homePoints": None, "awayPoints": None}
    state: dict[str, Any] = {"games": [played, tonight], "urls": []}

    def transport(url: str, headers: Any, timeout: float) -> Response:
        state["urls"].append(url)
        regular = "seasonType=regular" in url
        return Response(200, json.dumps(state["games"] if regular else []).encode(), {})

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
    cfbd = Cfbd(fetcher)
    real_now = run.utc_now
    run.utc_now = clock  # type: ignore[assignment]
    try:
        run.ingest_cfbd_season(lake, cfbd, 2026, ["games"])
        clock.now = datetime(2026, 11, 29, 6, 55, tzinfo=UTC)  # 01:55 ET Sunday, just before the cutoff
        state["games"] = [played, tonight | {"completed": True, "homePoints": 24, "awayPoints": 21}]
        run.ingest_cfbd_season(lake, cfbd, 2026, ["games"])
        clock.now = datetime(2026, 11, 29, 6, 58, tzinfo=UTC)
        unchanged = run.ingest_cfbd_season(lake, cfbd, 2026, ["games"])
        assert sum(r.new + r.corrected for r in unchanged) == 0
    finally:
        run.utc_now = real_now
    stored = lake.scan("games").collect().sort("game_id", "correction_version")
    assert stored.select("game_id", "correction_version", "status").rows() == [
        ("cfbd-1", 0, "scheduled"),
        ("cfbd-1", 1, "final"),
        ("cfbd-2", 0, "scheduled"),
        ("cfbd-2", 1, "final"),
    ]
    assert set(stored["vintage"].to_list()) == {"live"}
    public = stored["first_public_time"].to_list()
    assert public[1] == datetime(2026, 11, 21, 21, 30, tzinfo=UTC)  # rule time, already past at first capture
    assert public[3] == datetime(2026, 11, 29, 6, 55, tzinfo=UTC)  # seen live, 4.5 h rule not needed
    cutoff = datetime(2026, 11, 29, 7, 0, tzinfo=UTC)
    assert lake.as_of("games", cutoff, "live").frame["status"].to_list() == ["final", "final"]
    assert len(state["urls"]) == 6  # the live season is refetched, never reused
