"""Properties of the ledger (VT-01, VT-02, VT-03)."""

from __future__ import annotations

import random
from typing import Any

from cfp.open_ranking.ordering import rank_teams
from tests.unit.test_ledger import TEAMS, flipped, frame, game, league, totals


def test_flip_exact_10000() -> None:
    """VT-01: flipping any ordinary FBS result moves each team's own total by exactly 10000."""
    rows = league()
    base = totals(rows)
    for index in (0, 17, 40, 95):
        changed = [*rows[:index], flipped(rows[index]), *rows[index + 1 :]]
        after = totals(changed)
        home, away = rows[index]["home_id"], rows[index]["away_id"]
        home_won = rows[index]["winner_id"] == home
        assert after[home] - base[home] == (-10000 if home_won else 10000)
        assert after[away] - base[away] == (10000 if home_won else -10000)


def test_margin_invariance() -> None:
    """VT-02: a team's own margins never change its total."""
    rows = league()
    base = totals(rows)
    for team in ("T00", "T15", "T31"):
        changed = []
        for r in rows:
            if team in (r["home_id"], r["away_id"]):
                home_won = r["winner_id"] == r["home_id"]
                r = r | {"home_pts": 59 if home_won else 3, "away_pts": 3 if home_won else 59}
            changed.append(r)
        after = totals(changed)
        assert after[team] == base[team]
        assert after != base  # other teams' ledgers do see those margins


def test_relabel_permutation_neutral_reversal() -> None:
    """VT-03: renaming teams, permuting rows and reversing a neutral game leave totals in agreement."""
    rows = league()
    rows.append(game("n1", "T04", "T05", 31, 17, week=7, neutral=True))
    base = totals(rows)
    shuffled = rows[:]
    random.Random(9).shuffle(shuffled)
    assert totals(shuffled) == base
    reversed_neutral = [*rows[:-1], game("n1", "T05", "T04", 17, 31, week=7, neutral=True)]
    assert totals(reversed_neutral) == base

    names = TEAMS[:]
    random.Random(4).shuffle(names)  # a scrambled relabel, so the sorted order of teams changes
    new = {team: f"X{names.index(team):02d}" for team in TEAMS} | {"c0": "zz", "c1": "mm", "c2": "aa"}

    def rename(value: Any) -> Any:
        return new.get(value, value) if isinstance(value, str) else value

    renamed = [{k: rename(v) for k, v in r.items()} for r in rows]
    moved = totals(renamed)
    for team in TEAMS:
        assert abs(moved[rename(team)] - base[team]) <= 1  # same up to floating point at a rounding boundary
    draw = {team: place for place, team in enumerate(TEAMS, start=1)}
    before = rank_teams(base, frame(rows), draw)
    after = rank_teams(moved, frame(renamed), {rename(team): place for team, place in draw.items()})
    if all(moved[rename(team)] == base[team] for team in TEAMS):
        assert [r.team_id for r in after] == [rename(r.team_id) for r in before]  # mapped ranks
        assert [r.open_rank for r in after] == [r.open_rank for r in before]
