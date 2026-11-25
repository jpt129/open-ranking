"""Ledger (OR-01, OR-05, OR-06, OR-08, OR-11): one row per game, in integer centipoints.

For team A, strengths are fitted with every game involving A removed, and the reference band is formed without
A. Each of A's games against an FBS opponent has a reference probability p that a bubble-strength team wins it
at A's site; q = round_half_even(p * 10^4). A win scores 10000 - q and a loss scores -q, title games and
forfeits included. An FCS win scores 0 and an FCS loss -9900. The total is the integer sum of the rows.

Nothing here reads a float back out of a published total: q is the only place a float becomes an integer.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, replace
from typing import Any, Final

import polars as pl

from cfp.open_ranking import RULE_VERSION_ID
from cfp.open_ranking.band import field_size, reference_band
from cfp.open_ranking.link import SCALE, Site, probability, quantize
from cfp.open_ranking.strength import Engine, Params

FCS_WIN_CP: Final = 0
FCS_LOSS_CP: Final = -9900


class LedgerError(ValueError):
    """A ledger cannot be built from these games."""


@dataclass(frozen=True)
class Row:
    game_id: str
    week: int | None
    opponent_id: str
    site: Site
    result: str  # "W" or "L"
    title_game: bool
    q: int | None  # reference probability in 1/10000ths; None where a policy sets the points
    boundary: bool  # p * 10^4 lay within 1e-6 of a rounding boundary
    points_cp: int
    policy_exception: str | None  # fcs_win, fcs_loss, forfeit
    revision_cp: int | None = None  # change in points_cp since the last edition; None if the row is new


@dataclass(frozen=True)
class Ledger:
    team_id: str
    rows: tuple[Row, ...]
    total_cp: int
    band: tuple[str, ...]  # the reference band's members, strongest first
    band_strength: float
    home_adv: float
    rule_version_id: str = RULE_VERSION_ID


def row_dict(row: Row) -> dict[str, Any]:
    """A ledger row as it is published."""
    return {
        "game_id": row.game_id,
        "week": row.week,
        "opponent_id": row.opponent_id,
        "site": row.site,
        "result": row.result,
        "title_game": row.title_game,
        "q": row.q,
        "boundary": row.boundary,
        "points_cp": row.points_cp,
        "policy_exception": row.policy_exception,
        "revision_cp": row.revision_cp,
    }


def points_cp(won: bool, q: int) -> int:
    """Game points in centipoints: 10000 - q for a win, -q for a loss."""
    if isinstance(q, bool) or not isinstance(q, int) or not 0 <= q <= SCALE:
        raise LedgerError(f"q must be an integer from 0 to {SCALE}; got {q!r}")
    return SCALE - q if won else -q


def build_ledgers(games: pl.DataFrame, params: Params, t: float, season: int) -> dict[str, Ledger]:
    """A ledger for every FBS team in the snapshot's games."""
    if games["game_id"].is_duplicated().any():
        raise LedgerError("a game appears twice")
    size = field_size(season)
    engine = Engine(games, params)
    keys = [name for name in ("start_utc", "week") if name in games.columns]
    ordered = games.sort([*keys, "game_id"])
    mine: dict[str, list[dict[str, object]]] = {}
    for g in ordered.iter_rows(named=True):
        if g["winner_id"] not in (g["home_id"], g["away_id"]):
            raise LedgerError(f"game {g['game_id']} has no winner among its teams")
        for side in ("home", "away"):
            if g[f"{side}_div"] is None:
                raise LedgerError(f"game {g['game_id']} has a team with no division")
            if g[f"{side}_div"] == "fbs":
                mine.setdefault(g[f"{side}_id"], []).append(g)
    out: dict[str, Ledger] = {}
    for team in sorted(mine):
        fold = engine.fit(exclude=team)
        band = reference_band(fold, size)
        rows: list[Row] = []
        for g in mine[team]:
            at_home = g["home_id"] == team
            other = "away" if at_home else "home"
            opponent = str(g[f"{other}_id"])
            won = g["winner_id"] == team
            site: Site = "neutral" if g["neutral"] else "home" if at_home else "away"
            q: int | None = None
            boundary = False
            if g[f"{other}_div"] == "fbs":
                if opponent not in fold.theta or not engine.games_in_fold(opponent, exclude=team):
                    raise LedgerError(
                        f"{opponent} has no game with a usable margin outside its games with {team}"
                    )
                p = probability(band.strength, fold.theta[opponent], fold.home_adv, site, t)
                q, boundary = quantize(p)
                points = points_cp(won, q)
                policy = "forfeit" if g["forfeit"] else None
            else:
                points, policy = (FCS_WIN_CP, "fcs_win") if won else (FCS_LOSS_CP, "fcs_loss")
            week = g.get("week")
            rows.append(
                Row(
                    str(g["game_id"]),
                    int(week) if isinstance(week, int) else None,
                    opponent,
                    site,
                    "W" if won else "L",
                    bool(g["title_game"]),
                    q,
                    boundary,
                    points,
                    policy,
                )
            )
        total = sum(row.points_cp for row in rows)
        out[team] = Ledger(team, tuple(rows), total, band.members, band.strength, fold.home_adv)
    return out


def with_revisions(current: Mapping[str, Ledger], previous: Mapping[str, Ledger]) -> dict[str, Ledger]:
    """The current ledgers with each row's change in points since the previous edition."""
    out: dict[str, Ledger] = {}
    for team, ledger in current.items():
        old = {row.game_id: row.points_cp for row in previous[team].rows} if team in previous else {}
        rows = tuple(
            replace(row, revision_cp=row.points_cp - old[row.game_id] if row.game_id in old else None)
            for row in ledger.rows
        )
        out[team] = replace(ledger, rows=rows)
    return out
