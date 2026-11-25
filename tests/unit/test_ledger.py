"""Ledger (P07; OR-01, OR-05, OR-06, OR-08, OR-11) and ordering (P08; TB-01..04)."""

from __future__ import annotations

import random
from typing import Any

import polars as pl
import pytest

from cfp.open_ranking.ledger import FCS_LOSS_CP, LedgerError, build_ledgers, points_cp, with_revisions
from cfp.open_ranking.ordering import WINDOW_CP, rank_teams
from cfp.open_ranking.strength import INDEPENDENT, Params

PARAMS = Params(lambda_c=4.0, lambda_u=4.0)
T = 5.75


# --- arithmetic (OR-01, OR-05, OR-06, OR-11) ------------------------------------


def test_ledger_points_unit() -> None:
    assert points_cp(True, 2000) == 8000
    assert points_cp(False, 9000) == -9000
    assert points_cp(True, 0) == 10000
    assert points_cp(False, 0) == 0
    assert points_cp(True, 2000) - points_cp(False, 2000) == 10000
    with pytest.raises(LedgerError):
        points_cp(True, 10001)


def test_two_paths_same_total() -> None:
    assert points_cp(True, 2000) + points_cp(False, 9000) == -1000  # win at p=0.20, then loss at p=0.90
    assert points_cp(False, 2000) + points_cp(True, 9000) == -1000  # the expected loss, then the expected win


def test_ten_wins_25500() -> None:
    qs = [7450] * 10
    assert sum(qs) == 74500
    assert sum(points_cp(True, q) for q in qs) == 25500
    uneven = [9900, 9500, 9000, 8500, 8000, 7500, 7000, 6000, 5100, 4000]
    assert sum(uneven) == 74500
    assert sum(points_cp(True, q) for q in uneven) == 25500


def test_title_game_full_weight() -> None:
    assert (points_cp(True, 5000), points_cp(False, 5000)) == (5000, -5000)


def test_fcs_win_zero_loss_9900() -> None:
    assert FCS_LOSS_CP == -9900
    ledgers = build_ledgers(
        frame([*league(), fcs("f1", "T00", won=True), fcs("f2", "T01", won=False)]), PARAMS, T, 2026
    )
    win = next(r for r in ledgers["T00"].rows if r.game_id == "f1")
    loss = next(r for r in ledgers["T01"].rows if r.game_id == "f2")
    assert (win.points_cp, win.q, win.policy_exception) == (0, None, "fcs_win")
    assert (loss.points_cp, loss.q, loss.policy_exception) == (-9900, None, "fcs_loss")
    assert "FCS" not in ledgers  # only FBS teams have a ledger


# --- a synthetic season -----------------------------------------------------------

TEAMS = [f"T{i:02d}" for i in range(32)]
CONF = {team: (INDEPENDENT if i >= 30 else f"c{i % 3}") for i, team in enumerate(TEAMS)}


def game(game_id: str, home: str, away: str, home_pts: int, away_pts: int, **over: Any) -> dict[str, Any]:
    base = {
        "game_id": game_id,
        "week": 5,
        "home_id": home,
        "away_id": away,
        "home_pts": home_pts,
        "away_pts": away_pts,
        "winner_id": home if home_pts > away_pts else away,
        "neutral": False,
        "title_game": False,
        "home_div": "fbs",
        "away_div": "fbs",
        "home_conf": CONF.get(home),
        "away_conf": CONF.get(away),
        "ordinary_fbs": True,
        "forfeit": False,
        "margin_excluded": False,
    }
    return base | over


def fcs(game_id: str, team: str, won: bool) -> dict[str, Any]:
    pts = (45, 3) if won else (17, 20)
    return game(game_id, team, "FCS", *pts, away_div="fcs", away_conf="big-sky", ordinary_fbs=False)


def league(seed: int = 5) -> list[dict[str, Any]]:
    """Six rounds of random pairings among 32 teams, with strength falling by team number."""
    rng = random.Random(seed)
    rows = []
    for week in range(1, 7):
        order = TEAMS[:]
        rng.shuffle(order)
        for k in range(16):
            home, away = order[2 * k], order[2 * k + 1]
            margin = round((TEAMS.index(away) - TEAMS.index(home)) * 0.8 + 2.5 + rng.gauss(0, 10)) or 1
            rows.append(game(f"w{week}-{k:02d}", home, away, 30 + margin, 30, week=week))
    return rows


def frame(rows: list[dict[str, Any]]) -> pl.DataFrame:
    overrides = {"week": pl.Int32, "home_pts": pl.Int32, "away_pts": pl.Int32, "home_conf": pl.String}
    return pl.DataFrame(rows, schema_overrides=overrides | {"away_conf": pl.String})


def flipped(row: dict[str, Any]) -> dict[str, Any]:
    """The same game with the other team winning by the same score."""
    return row | {
        "home_pts": row["away_pts"],
        "away_pts": row["home_pts"],
        "winner_id": row["away_id"] if row["winner_id"] == row["home_id"] else row["home_id"],
    }


def totals(rows: list[dict[str, Any]], season: int = 2026) -> dict[str, int]:
    return {team: ledger.total_cp for team, ledger in build_ledgers(frame(rows), PARAMS, T, season).items()}


def test_ledger_row_fields() -> None:
    rows = league()
    rows.append(game("title", "T02", "T03", 27, 24, week=7, title_game=True, neutral=True))
    ledgers = build_ledgers(frame(rows), PARAMS, T, 2026)
    assert set(ledgers) == set(TEAMS)
    ledger = ledgers["T02"]
    assert ledger.total_cp == sum(r.points_cp for r in ledger.rows)
    assert len(ledger.rows) == 7
    assert len(ledger.band) == 8
    assert "T02" not in ledger.band
    title = ledger.rows[-1]  # rows are in week order
    assert (title.game_id, title.opponent_id, title.site, title.result, title.title_game) == (
        "title",
        "T03",
        "neutral",
        "W",
        True,
    )
    assert title.policy_exception is None
    assert title.q is not None
    assert title.points_cp == 10000 - title.q  # full weight, like any other game
    other = next(r for r in ledgers["T03"].rows if r.game_id == "title")
    assert (other.result, other.site, other.points_cp) == ("L", "neutral", -(other.q or 0))
    home = next(r for r in ledger.rows if r.site == "home")
    assert 0 < (home.q or 0) < 10000
    assert isinstance(home.boundary, bool)
    assert home.revision_cp is None


def test_site_moves_the_reference_probability() -> None:
    base = league()
    sample = next(r for r in base if r["home_id"] == "T10")
    as_neutral = [r | {"neutral": True} if r is sample else r for r in base]
    q_home = next(
        r.q for r in build_ledgers(frame(base), PARAMS, T, 2026)["T10"].rows if r.game_id == sample["game_id"]
    )
    ledgers = build_ledgers(frame(as_neutral), PARAMS, T, 2026)
    q_neutral = next(r.q for r in ledgers["T10"].rows if r.game_id == sample["game_id"])
    assert q_home is not None
    assert q_neutral is not None
    assert q_home > q_neutral  # a bubble team is likelier to win at home than on a neutral field


def test_loss_to_first_year_fbs_member_scores_minus_q() -> None:
    """John's ruling, 2026-11-25: a reclassifying member in an FBS conference is an ordinary FBS opponent."""
    rows = league()
    rows.append(game("ndsu", "T31", "T07", 28, 31, week=7))  # stands in for a 2026 loss to North Dakota State
    ledger = build_ledgers(frame(rows), PARAMS, T, 2026)["T31"]
    loss = next(r for r in ledger.rows if r.game_id == "ndsu")
    assert loss.policy_exception is None
    assert loss.q is not None
    assert loss.points_cp == -loss.q
    assert loss.points_cp != FCS_LOSS_CP


def test_forfeit_is_scored_normally_and_labelled() -> None:
    rows = league()
    rows.append(
        game("ff", "T08", "T09", 0, 2, week=7, ordinary_fbs=False, forfeit=True, margin_excluded=True)
    )
    ledgers = build_ledgers(frame(rows), PARAMS, T, 2026)
    win = next(r for r in ledgers["T09"].rows if r.game_id == "ff")
    assert (win.policy_exception, win.result, win.site) == ("forfeit", "W", "away")
    assert win.q is not None
    assert win.points_cp == 10000 - win.q


def test_band_follows_the_season_field_size() -> None:
    rows = league()
    four, twelve, twenty_four = (build_ledgers(frame(rows), PARAMS, T, s)["T20"] for s in (2019, 2026, 2027))
    assert four.band != twelve.band != twenty_four.band
    assert (
        four.total_cp < twelve.total_cp < twenty_four.total_cp
    )  # a stronger reference lowers every game's points


def test_ledger_revision_since_last_edition() -> None:
    rows = league()
    before = build_ledgers(frame(rows[:80]), PARAMS, T, 2026)
    after = with_revisions(build_ledgers(frame(rows), PARAMS, T, 2026), before)
    ledger = after["T00"]
    old = {r.game_id: r.points_cp for r in before["T00"].rows}
    for r in ledger.rows:
        if r.game_id in old:
            assert r.revision_cp == r.points_cp - old[r.game_id]  # old wins are re-valued as evidence changes
        else:
            assert r.revision_cp is None  # new since the last edition
    assert any(r.revision_cp not in (None, 0) for team in after.values() for r in team.rows)
    assert ledger.total_cp == build_ledgers(frame(rows), PARAMS, T, 2026)["T00"].total_cp


# --- ordering (TB-01..04) --------------------------------------------------------------

DRAW = {name: place for place, name in enumerate(["D", "C", "B", "A", "E", "F"], start=1)}


def met(*results: tuple[str, str]) -> pl.DataFrame:
    rows = [
        {"game_id": f"m{i}", "home_id": won, "away_id": lost, "winner_id": won, "forfeit": False}
        for i, (won, lost) in enumerate(results)
    ]
    schema = {"game_id": pl.String, "home_id": pl.String, "away_id": pl.String, "winner_id": pl.String}
    return pl.DataFrame(rows, schema=schema | {"forfeit": pl.Boolean})


def order(totals_cp: dict[str, int], games: pl.DataFrame) -> list[tuple[str, int, str | None]]:
    return [(r.team_id, r.open_rank, r.head_to_head) for r in rank_teams(totals_cp, games, DRAW)]


def test_groups_join_within_2500() -> None:
    assert WINDOW_CP == 2500
    ranked = rank_teams({"A": 30000, "B": 27500, "C": 24999, "D": 10000}, met(), DRAW)
    assert [r.group for r in ranked] == [1, 1, 2, 3]  # 2500 joins, 2501 does not
    assert [r.raw_rank for r in ranked] == [1, 2, 3, 4]
    assert [r.team_id for r in ranked] == ["A", "B", "C", "D"]


def test_isolated_pair_h2h() -> None:
    assert order({"A": 30000, "B": 28000, "C": 10000}, met(("B", "A"))) == [
        ("B", 1, "won the series 1-0 over A"),
        ("A", 2, "lost the series 0-1 to B"),
        ("C", 3, None),
    ]
    assert order({"A": 30000, "B": 28000}, met()) == [("A", 1, None), ("B", 2, None)]  # never met
    assert order({"A": 30000, "B": 28000}, met(("A", "B")))[0][0] == "A"  # the leader won anyway
    assert order({"A": 30000, "B": 27499}, met(("B", "A")))[0][0] == "A"  # outside the window: no group


def test_split_series_keeps_points_order() -> None:
    assert [t for t, _, _ in order({"A": 30000, "B": 28000}, met(("B", "A"), ("A", "B")))] == ["A", "B"]
    twice = order({"A": 30000, "B": 28000}, met(("B", "A"), ("B", "A")))
    assert twice[0] == ("B", 1, "won the series 2-0 over A")
    two_one = order({"A": 30000, "B": 28000}, met(("B", "A"), ("A", "B"), ("B", "A")))
    assert two_one[0][0] == "B"  # every meeting counts, title games included


def test_three_team_cycle() -> None:
    games = met(("A", "B"), ("B", "C"), ("C", "A"))
    assert order({"A": 30000, "B": 29000, "C": 28000}, games) == [
        ("A", 1, None),
        ("B", 2, None),
        ("C", 3, None),
    ]


def test_chained_gaps() -> None:
    ranked = rank_teams({"A": 30000, "B": 27600, "C": 25200}, met(("C", "B"), ("B", "A")), DRAW)
    assert [r.group for r in ranked] == [1, 1, 1]  # 2400 + 2400 chains into one group of three
    assert [r.team_id for r in ranked] == ["A", "B", "C"]  # larger groups stay in points order
    assert all(r.head_to_head is None for r in ranked)


def test_exact_tie_at_cutoff_shared_rank_and_draw() -> None:
    ranked = rank_teams({"A": 30000, "B": 20000, "C": 20000, "D": 20000, "E": 5000}, met(), DRAW)
    assert [(r.team_id, r.open_rank) for r in ranked] == [("A", 1), ("D", 2), ("C", 2), ("B", 2), ("E", 5)]
    assert [r.order for r in ranked] == [
        1,
        2,
        3,
        4,
        5,
    ]  # the draw gives a total order where a bracket needs one
    pair = rank_teams({"A": 20000, "B": 20000}, met(), DRAW)
    assert [(r.team_id, r.open_rank, r.raw_rank) for r in pair] == [("B", 1, 1), ("A", 1, 1)]
    settled = rank_teams({"A": 20000, "B": 20000}, met(("A", "B")), DRAW)
    assert [(r.team_id, r.open_rank, r.raw_rank) for r in settled] == [("A", 1, 1), ("B", 2, 1)]
    with pytest.raises(ValueError, match="draw"):
        rank_teams({"A": 1, "Z": 1}, met(), DRAW)


def test_forfeits_are_not_meetings() -> None:
    games = met(("B", "A")).with_columns(forfeit=pl.lit(True))
    assert [t for t, _, _ in order({"A": 30000, "B": 28000}, games)] == ["A", "B"]


def test_ordering_refuses_bad_inputs() -> None:
    with pytest.raises(ValueError, match="same position"):
        rank_teams({"A": 1, "B": 1}, met(), {"A": 1, "B": 1})
    with pytest.raises(ValueError, match="forfeit flag"):
        rank_teams({"A": 1, "B": 1}, met(("A", "B")).with_columns(forfeit=pl.lit(None, pl.Boolean)), DRAW)


def test_opponent_with_no_other_game_stops_the_build() -> None:
    rows = league()
    rows.append(game("solo", "T00", "T99", 30, 10, week=7, away_conf="c0"))  # T99 plays only T00
    with pytest.raises(LedgerError, match="T99 has no game"):
        build_ledgers(frame(rows), PARAMS, T, 2026)
    odd = game("x", "T00", "Q", 30, 10, away_div=None, ordinary_fbs=False)
    with pytest.raises(LedgerError, match="no division"):
        build_ledgers(frame([*league(), odd]), PARAMS, T, 2026)


def test_open_ranking_runs_without_forbidden_tables() -> None:
    """OR-12: built from game rows and the draw alone; no lake, release, poll or line is read."""
    from cfp.open_ranking import RULE_VERSION_ID

    games = frame(league())
    ledgers = build_ledgers(games, PARAMS, T, 2026)
    draw = {team: place for place, team in enumerate(TEAMS, start=1)}
    ranked = rank_teams({team: ledger.total_cp for team, ledger in ledgers.items()}, games, draw)
    assert len(ranked) == 32
    assert all(ledger.rule_version_id == RULE_VERSION_ID for ledger in ledgers.values())
