"""Ordering (TB-01..04).

Teams are sorted by total centipoints. Adjacent totals at most 2500 apart join into one group. In a group of
exactly two, a team that won the season series (every meeting, title games included; forfeits are not
meetings) goes first. A split series and any larger group keep points order. Teams still exactly tied share a
rank; the preseason draw gives the total order a bracket needs.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Final

import polars as pl

WINDOW_CP: Final = 2500


@dataclass(frozen=True)
class Ranked:
    team_id: str
    total_cp: int
    raw_rank: int  # rank by points alone; equal totals share it
    group: int  # 1 for the top group
    head_to_head: str | None  # the decision, where a series was looked at
    open_rank: int  # final rank; unresolved exact ties share it
    order: int  # total order, 1..n: head-to-head, then the draw, settle what points leave open


def _series(games: pl.DataFrame, a: str, b: str) -> tuple[int, int]:
    """(wins by a, wins by b) over every played meeting."""
    pair = games.filter(
        ~pl.col("forfeit")
        & (
            ((pl.col("home_id") == a) & (pl.col("away_id") == b))
            | ((pl.col("home_id") == b) & (pl.col("away_id") == a))
        )
    )
    winners = pair["winner_id"].to_list()
    return winners.count(a), winners.count(b)


def rank_teams(totals_cp: Mapping[str, int], games: pl.DataFrame, draw: Mapping[str, int]) -> list[Ranked]:
    """The final order. `games` needs game_id, home_id, away_id, winner_id and forfeit."""
    missing = sorted(set(totals_cp) - set(draw))
    if missing:
        raise ValueError(f"the draw has no position for: {', '.join(missing)}")
    places = [draw[team] for team in totals_cp]
    if len(set(places)) != len(places):
        raise ValueError("the draw gives two teams the same position")
    if games["game_id"].is_duplicated().any():
        raise ValueError("a game appears twice")
    if games["forfeit"].null_count() or games["winner_id"].null_count():
        raise ValueError("a game has no forfeit flag or no winner")
    teams = sorted(totals_cp, key=lambda team: (-totals_cp[team], draw[team]))
    raw: dict[str, int] = {}
    group: dict[str, int] = {}
    for i, team in enumerate(teams):
        same = i > 0 and totals_cp[teams[i - 1]] == totals_cp[team]
        raw[team] = raw[teams[i - 1]] if same else i + 1
        near = i > 0 and totals_cp[teams[i - 1]] - totals_cp[team] <= WINDOW_CP
        group[team] = group[teams[i - 1]] + (0 if near else 1) if i > 0 else 1
    sizes: dict[int, int] = {}
    for g in group.values():
        sizes[g] = sizes.get(g, 0) + 1
    note: dict[str, str] = {}
    settled: set[str] = set()  # the lower team of a pair that head-to-head put in order
    for i in range(len(teams) - 1):
        first, second = teams[i], teams[i + 1]
        if group[first] != group[second] or sizes[group[first]] != 2:
            continue
        a_wins, b_wins = _series(games, first, second)
        if a_wins == b_wins:
            if a_wins:
                note[first] = f"split the series {a_wins}-{b_wins} with {second}; points order kept"
                note[second] = f"split the series {b_wins}-{a_wins} with {first}; points order kept"
            continue
        if b_wins > a_wins:
            teams[i], teams[i + 1] = second, first
            first, second, a_wins, b_wins = second, first, b_wins, a_wins
        note[first] = f"won the series {a_wins}-{b_wins} over {second}"
        note[second] = f"lost the series {b_wins}-{a_wins} to {first}"
        settled.add(second)
    out: list[Ranked] = []
    for i, team in enumerate(teams):
        tied = i > 0 and totals_cp[teams[i - 1]] == totals_cp[team] and team not in settled
        rank = out[-1].open_rank if tied else i + 1
        out.append(Ranked(team, totals_cp[team], raw[team], group[team], note.get(team), rank, i + 1))
    return out
