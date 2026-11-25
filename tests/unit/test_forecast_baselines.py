"""Observations, cutoffs and baselines (P15; SC-01, SC-02, SC-02a, SC-03)."""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from typing import Any

import polars as pl
import pytest

from cfp.forecast.baselines import ap_order, baseline1, baseline2, initial_order, losses_since
from cfp.forecast.cutoffs import issue_time, sunday_0200
from cfp.forecast.draw import draw_positions, load_draw
from cfp.forecast.observations import ObservationError, fbs_field, label_leaked, observations

ROOT = Path(__file__).resolve().parents[2]
REVEAL = datetime(2026, 12, 2, 0, 0, tzinfo=UTC)  # Tue 1 Dec 19:00 ET
TEAMS = [f"T{i:02d}" for i in range(1, 41)]
DRAW = {team: position for position, team in enumerate(reversed(TEAMS), start=1)}


def ap(ranked: list[str], others: dict[str, int] | None = None, week: int = 13) -> pl.DataFrame:
    rows: list[dict[str, Any]] = [
        {"week": week, "team_id": team, "rank": rank, "points": 1600 - 50 * rank}
        for rank, team in enumerate(ranked, start=1)
    ]
    rows += [{"week": week, "team_id": t, "rank": None, "points": p} for t, p in (others or {}).items()]
    return pl.DataFrame(
        rows, schema={"week": pl.Int32, "team_id": pl.String, "rank": pl.Int32, "points": pl.Int32}
    )


def games(*results: tuple[str, str, int, int, datetime]) -> pl.DataFrame:
    rows = [
        {"game_id": f"g{i}", "home_id": h, "away_id": a, "home_pts": hp, "away_pts": ap_, "start_utc": at}
        for i, (h, a, hp, ap_, at) in enumerate(results)
    ]
    schema = {
        "game_id": pl.String,
        "home_id": pl.String,
        "away_id": pl.String,
        "home_pts": pl.Int32,
        "away_pts": pl.Int32,
        "start_utc": pl.Datetime("us", "UTC"),
    }
    return pl.DataFrame(rows, schema=schema).with_columns(status=pl.lit("final"), week=pl.lit(14, pl.Int32))


# --- cutoffs (SC-02, SC-02a) ---------------------------------------------------


def test_cutoffs_sun0200_tminus60() -> None:
    assert sunday_0200(date(2026, 11, 29)) == datetime(2026, 11, 29, 7, 0, tzinfo=UTC)
    assert issue_time("sun0200", REVEAL) == datetime(2026, 11, 29, 7, 0, tzinfo=UTC)
    assert issue_time("tminus60", REVEAL) == datetime(2026, 12, 1, 23, 0, tzinfo=UTC)
    selection = datetime(2026, 12, 6, 17, 0, tzinfo=UTC)  # Sunday noon ET: the 02:00 issue is that morning
    assert issue_time("sun0200", selection) == datetime(2026, 12, 6, 7, 0, tzinfo=UTC)
    assert issue_time("tminus60", selection) == datetime(2026, 12, 6, 16, 0, tzinfo=UTC)
    with pytest.raises(ValueError, match="issue"):
        issue_time("noon", REVEAL)
    with pytest.raises(ValueError, match="Sunday"):
        sunday_0200(date(2026, 11, 28))


def test_dst_sunday() -> None:
    # Clocks go back on 1 Nov 2026. 02:00 that morning is taken in standard time: the later of the candidates.
    assert sunday_0200(date(2026, 11, 1)) == datetime(2026, 11, 1, 7, 0, tzinfo=UTC)
    assert sunday_0200(date(2026, 10, 25)) == datetime(2026, 10, 25, 6, 0, tzinfo=UTC)


# --- observations (SC-01) ------------------------------------------------------


def field(n_fbs: int = 30) -> pl.DataFrame:
    membership = pl.DataFrame(
        {
            "team_id": TEAMS,
            "valid_from": [date(2026, 8, 1)] * 40,
            "valid_to": [date(2027, 7, 31)] * 40,
            "division": ["fbs"] * n_fbs + ["fcs"] * (40 - n_fbs),
        }
    )
    eligibility = pl.DataFrame(
        {"season": [2026, 2025], "team_id": ["T30", "T29"], "cfp_eligible": [False, False]}
    )
    return fbs_field(membership, eligibility, 2026, date(2026, 11, 29))


def release(release_id: str, ranked: list[str], reveal: datetime = REVEAL) -> pl.DataFrame:
    return pl.DataFrame(
        {
            "release_id": [release_id] * len(ranked),
            "rank": list(range(1, len(ranked) + 1)),
            "team_id": ranked,
            "reveal_utc": [reveal] * len(ranked),
        },
        schema_overrides={"rank": pl.Int32},
    )


def test_observation_denominator() -> None:
    obs = observations(release("cfp-2026-05", TEAMS[:25]), field())
    assert obs.height == 30  # every FBS team, ranked or not
    assert obs.filter(pl.col("rank").is_not_null()).height == 25
    below = obs.filter(pl.col("below_25"))
    assert below["team_id"].to_list() == TEAMS[25:30]
    assert below["rank"].null_count() == 5
    with pytest.raises(ObservationError, match="not an FBS team"):
        observations(release("cfp-2026-05", [*TEAMS[:24], "T35"]), field())
    with pytest.raises(ObservationError, match="25"):
        observations(release("cfp-2026-05", TEAMS[:24]), field())


def test_eligibility_flag() -> None:
    teams = field()
    flags = dict(teams.select("team_id", "cfp_eligible").iter_rows())
    assert flags["T30"] is False  # sourced as ineligible this season
    assert flags["T29"] is True  # last season's flag does not carry over
    obs = observations(release("cfp-2026-05", TEAMS[:25]), teams)
    assert obs.filter(pl.col("team_id") == "T30")["cfp_eligible"].to_list() == [False]
    assert obs.height == 30  # an ineligible team stays in the denominator


def test_leaked_label_ineligible() -> None:
    earlier = release("cfp-2026-04", TEAMS[:25], REVEAL - timedelta(days=7))
    assert label_leaked(earlier, REVEAL) is False
    leaked = pl.concat([earlier, release("cfp-2026-05", TEAMS[:25], REVEAL)])
    assert label_leaked(leaked, REVEAL) is True


# --- baselines (SC-03) ---------------------------------------------------------


def test_baseline1_latest_ap() -> None:
    older = ap(list(reversed(TEAMS[:25])), week=12)
    latest = ap(TEAMS[:25], {"T30": 40, "T28": 90}, week=13)
    order = baseline1(TEAMS[:32], pl.concat([older, latest]), DRAW)
    assert order[:25] == TEAMS[:25]
    assert order[25:27] == ["T28", "T30"]  # then others by votes
    assert order[27:] == ["T32", "T31", "T29", "T27", "T26"]  # then the draw
    assert ap_order(pl.concat([older, latest]))[0] == (13, "T01", 1550)
    with pytest.raises(ValueError, match="no AP poll"):
        baseline1(TEAMS[:32], ap([]), DRAW)


def test_initial_order_cfp_then_ap_votes_then_open_points_then_draw() -> None:
    cfp = TEAMS[:25]
    poll = ap([*TEAMS[:20], "T27", "T26", "T21", "T22", "T23"], {"T30": 55, "T29": 55, "T31": 9})
    order = initial_order(TEAMS[:36], cfp, poll, None, DRAW)
    assert order[:25] == cfp
    assert order[25:27] == ["T27", "T26"]  # AP-ranked teams outside the committee's 25, by votes
    assert order[27:30] == ["T30", "T29", "T31"]  # equal votes: no open points, so the draw (T30 before T29)
    assert order[30:] == ["T36", "T35", "T34", "T33", "T32", "T28"]  # no votes at all: the draw
    points = {"T29": 120_000, "T30": -5_000, "T28": 40_000, "T36": 40_000}
    order = initial_order(TEAMS[:36], cfp, poll, points, DRAW)
    assert order[27:30] == ["T29", "T30", "T31"]  # equal votes now split by open points
    assert order[30:33] == [
        "T36",
        "T28",
        "T35",
    ]  # equal open points fall to the draw; missing points sort last
    assert initial_order(TEAMS[:36], None, poll, None, DRAW)[:22] == [
        *TEAMS[:20],
        "T27",
        "T26",
    ]  # opening week
    with pytest.raises(ValueError, match="not in the field"):
        initial_order(TEAMS[:20], cfp, poll, None, DRAW)


def test_losses_since_counts_only_games_not_final_at_the_release() -> None:
    since = REVEAL - timedelta(days=7)
    played = games(
        ("T03", "T09", 10, 20, since + timedelta(days=3)),
        ("T50", "T03", 31, 30, since + timedelta(days=4)),  # a loss to a team outside the field still counts
        (
            "T03",
            "T04",
            7,
            14,
            since - timedelta(days=2),
        ),  # before the release: already in the committee's order
        ("T05", "T06", 21, 20, since - timedelta(minutes=30)),  # kicked off before the show, final after it
        ("T07", "T08", 21, 20, since - timedelta(hours=5)),  # final before the show
        ("T60", "T61", 14, 14, since + timedelta(days=1)),  # a tie between teams outside the field is ignored
        ("T62", "T63", 3, 0, since + timedelta(days=1)),
    )
    assert losses_since(played, TEAMS, since=since) == {"T03": 2, "T06": 1}
    assert losses_since(played, TEAMS, since_week=14) == {"T03": 3, "T06": 1, "T08": 1}
    assert losses_since(played, TEAMS, since_week=15) == {}
    tie = games(("T01", "T02", 14, 14, since + timedelta(days=1)))
    with pytest.raises(ValueError, match="tie"):
        losses_since(tie, TEAMS, since=since)
    with pytest.raises(ValueError, match="no week"):
        losses_since(played.with_columns(week=pl.lit(None, pl.Int32)), TEAMS, since_week=14)


def test_ap_rank_ties_fall_to_open_points_then_the_draw() -> None:
    poll = ap(TEAMS[:25]).with_columns(
        rank=pl.when(pl.col("team_id") == "T21").then(20).otherwise(pl.col("rank")).cast(pl.Int32),
        points=pl.when(pl.col("team_id") == "T21").then(600).otherwise(pl.col("points")).cast(pl.Int32),
    )  # T20 and T21 share rank 20 on 600 points
    for frame in (poll, poll.reverse(), poll.sort("team_id", descending=True)):
        assert baseline1(TEAMS[:30], frame, DRAW)[19:21] == ["T21", "T20"]  # the draw puts T21 first
        assert initial_order(TEAMS[:30], None, frame, {"T20": 5, "T21": 4}, DRAW)[19:21] == ["T20", "T21"]


def test_baseline2_two_losses_move_ten() -> None:
    rows = baseline2(TEAMS[:30], {"T03": 2, "T20": 1})
    by_team = {row.team_id: row for row in rows}
    assert (by_team["T03"].initial, by_team["T03"].losses, by_team["T03"].adjusted) == (3, 2, 13)
    # sorted by adjusted position, then original order: T03 ties T13 at 13 and keeps its earlier place
    assert [row.team_id for row in rows][9:13] == ["T11", "T12", "T03", "T13"]
    assert by_team["T03"].position == 12
    assert (by_team["T20"].adjusted, by_team["T20"].position) == (25, 24)
    assert [row.position for row in rows] == list(range(1, 31))
    assert [row.team_id for row in baseline2(TEAMS[:30], {})] == TEAMS[:30]


def test_baseline_tiebreak_draw() -> None:
    positions = draw_positions(TEAMS, "open-ranking draw test")
    assert sorted(positions.values()) == list(range(1, 41))
    assert positions == draw_positions(
        list(reversed(TEAMS)), "open-ranking draw test"
    )  # input order is irrelevant
    assert positions != draw_positions(TEAMS, "another phrase")
    # the published file is exactly what the recorded phrase produces for the season's FBS teams
    published = load_draw(ROOT / "data" / "preseason_draw_2026.csv", 2026)
    assert len(published) == 138
    assert published == draw_positions(list(published), "open-ranking tiebreak draw 2026")
