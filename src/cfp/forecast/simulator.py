"""Game simulator (FF-02, VT-13, DS-07): probabilities, correlated outcomes and valid scores.

A game's home-win probability comes from two-sided moneylines with the margin removed, or from a spread
through a curve fitted on past seasons, or from a strength model when nothing is quoted. Outcomes are tied
together by team: each path draws one standard normal shock per team and one per game. For a game,

    x = a * (z_home - z_away) / sqrt(2) + sqrt(1 - a^2) * e,    u = Phi(x),

and the home team wins when u > 1 - p. The squared weights sum to one, so x is standard normal and every
game keeps its own probability whatever `a` is; `a = 0` makes games independent. Scores are drawn from past
games with the same winning side and a similar pregame probability, so they are whole numbers and never tied.

Every draw comes from one generator built from the recorded seed. Nothing here reads a price for a team's
playoff chances: only game lines.
"""

from __future__ import annotations

import math
from collections.abc import Sequence
from dataclasses import dataclass, field
from typing import Any, Final

import numpy as np
import numpy.typing as npt
import polars as pl
from scipy.optimize import brentq, minimize_scalar
from scipy.special import ndtr, ndtri

Floats = npt.NDArray[np.float64]
Ints = npt.NDArray[np.int64]
Bools = npt.NDArray[np.bool_]

SCORE_BINS: Final = 10
SERIES_TERMS: Final = 12
_EPS: Final = 1e-9


def _implied(moneyline: float) -> float:
    if not math.isfinite(moneyline) or abs(moneyline) < 100:
        raise ValueError(f"{moneyline!r} is not a valid American moneyline")
    return -moneyline / (-moneyline + 100) if moneyline < 0 else 100 / (moneyline + 100)


def devig(ml_home: float, ml_away: float) -> float:
    """Home-win probability from the two American moneylines, the bookmaker's margin removed in proportion."""
    home, away = _implied(ml_home), _implied(ml_away)
    return home / (home + away)


@dataclass(frozen=True)
class SpreadCurve:
    """P(home wins) = Phi(-spread / scale). A negative spread means the home side is favoured."""

    scale: float

    def probability(self, spread: float) -> float:
        return float(ndtr(-spread / self.scale))


def fit_spread_curve(spreads: Floats, home_won: Bools) -> SpreadCurve:
    """The scale that maximises the likelihood of past results given their spreads."""
    spreads = np.asarray(spreads, dtype=np.float64)
    won = np.asarray(home_won, dtype=bool)
    if spreads.size == 0 or spreads.size != won.size:
        raise ValueError("no games to fit the spread curve on")

    def loss(scale: float) -> float:
        p = np.clip(ndtr(-spreads / scale), _EPS, 1 - _EPS)
        return float(-(np.log(p[won]).sum() + np.log(1 - p[~won]).sum()))

    found = minimize_scalar(loss, bounds=(3.0, 40.0), method="bounded", options={"xatol": 1e-6})
    return SpreadCurve(float(found.x))


def game_probability(
    curve: SpreadCurve,
    *,
    moneylines: Sequence[tuple[float, float]],
    spreads: Sequence[float],
    strength: float | None,
) -> tuple[float, str]:
    """(home-win probability, its source): the median book's moneylines, else the spread, else strength."""
    if moneylines:
        return float(np.median([devig(home, away) for home, away in moneylines])), "moneyline"
    if spreads:
        return curve.probability(float(np.median(list(spreads)))), "spread"
    if strength is not None:
        if not 0.0 < strength < 1.0:
            raise ValueError(f"a strength estimate of {strength!r} is not a probability")
        return strength, "strength"
    raise ValueError("no probability: the game has no moneyline, no spread and no strength estimate")


@dataclass(frozen=True)
class Game:
    game_id: str
    home_id: str
    away_id: str
    p_home: float


@dataclass(frozen=True)
class ScoreTable:
    """Past final scores, grouped by winning side and pregame home-win probability."""

    home: tuple[Ints, ...]  # per probability bin: (n, 2) home and away points where the home team won
    away: tuple[Ints, ...]

    @classmethod
    def from_history(cls, history: pl.DataFrame, bins: int = SCORE_BINS) -> ScoreTable:
        p = history["p_home"].to_numpy().astype(np.float64)
        if not (np.isfinite(p) & (p >= 0.0) & (p <= 1.0)).all():
            raise ValueError("a past game has a probability outside 0 to 1")
        pts = np.column_stack([history["home_pts"].to_numpy(), history["away_pts"].to_numpy()]).astype(
            np.int64
        )
        if (pts[:, 0] == pts[:, 1]).any():
            raise ValueError("a tied score cannot be used")
        if (pts < 0).any():
            raise ValueError("a negative score cannot be used")
        which = np.minimum((p * bins).astype(int), bins - 1)
        sides: list[tuple[Ints, ...]] = []
        for home_won in (True, False):
            side = (pts[:, 0] > pts[:, 1]) == home_won
            groups = [pts[side & (which == b)] for b in range(bins)]
            filled = [b for b in range(bins) if len(groups[b])]
            if not filled:
                raise ValueError("no past scores for one winning side")
            # an empty bin borrows the nearest bin that has games
            sides.append(tuple(groups[min(filled, key=lambda f, b=b: (abs(f - b), f))] for b in range(bins)))  # type: ignore[misc]
        return cls(sides[0], sides[1])

    def sample(self, p_home: float, home_won: Bools, rng: np.random.Generator) -> tuple[Ints, Ints]:
        bins = len(self.home)
        b = min(int(p_home * bins), bins - 1)
        out = np.empty((home_won.size, 2), dtype=np.int64)
        for mask, table in ((home_won, self.home[b]), (~home_won, self.away[b])):
            count = int(mask.sum())
            if count:
                out[mask] = table[rng.integers(0, len(table), size=count)]
        return out[:, 0], out[:, 1]


@dataclass(frozen=True)
class Paths:
    game_ids: tuple[str, ...]  # sorted; the columns of the arrays below
    home_won: Bools  # (paths, games)
    home_pts: Ints | None
    away_pts: Ints | None
    seed: int
    a: float
    sides: dict[str, tuple[str, str]] = field(default_factory=dict)  # game id -> (home, away)


def simulate(
    games: Sequence[Game], n: int, *, a: float, seed: int, scores: ScoreTable | None = None
) -> Paths:
    """`n` joint outcomes of `games`. The same games, `a`, seed and score table give the same arrays."""
    if not 0.0 <= a <= 1.0:
        raise ValueError("the dependence weight a must be between 0 and 1")
    if isinstance(seed, bool) or not isinstance(seed, int) or seed < 0:
        raise ValueError("a recorded seed is needed: a whole number, zero or more")
    if n < 1:
        raise ValueError("at least one path is needed")
    ordered = sorted(games, key=lambda g: g.game_id)
    ids = tuple(g.game_id for g in ordered)
    if len(set(ids)) != len(ids):
        raise ValueError("a game appears twice")
    for g in ordered:
        if g.home_id == g.away_id:
            raise ValueError(f"game {g.game_id} has one team on both sides")
        if not 0.0 <= g.p_home <= 1.0:
            raise ValueError(f"game {g.game_id} has a probability outside 0 to 1")
    teams = sorted({t for g in ordered for t in (g.home_id, g.away_id)})
    at = {team: k for k, team in enumerate(teams)}
    rng = np.random.default_rng(seed)
    team_shock = rng.standard_normal((n, len(teams)))
    game_shock = rng.standard_normal((n, len(ordered)))
    home = np.array([at[g.home_id] for g in ordered], dtype=np.intp)
    away = np.array([at[g.away_id] for g in ordered], dtype=np.intp)
    p = np.array([g.p_home for g in ordered], dtype=np.float64)
    x = a * (team_shock[:, home] - team_shock[:, away]) / np.sqrt(2.0) + np.sqrt(1.0 - a * a) * game_shock
    won: Bools = ndtr(x) > 1.0 - p
    home_pts: Ints | None = None
    away_pts: Ints | None = None
    if scores is not None:
        home_pts = np.empty(won.shape, dtype=np.int64)
        away_pts = np.empty(won.shape, dtype=np.int64)
        for k, g in enumerate(ordered):
            home_pts[:, k], away_pts[:, k] = scores.sample(g.p_home, won[:, k], rng)
    return Paths(ids, won, home_pts, away_pts, seed, a, {g.game_id: (g.home_id, g.away_id) for g in ordered})


@dataclass(frozen=True)
class Dependence:
    a: float
    pairs: int  # pairs of games sharing exactly one team in a season
    observed: float  # mean signed product of residuals over those pairs
    seasons: tuple[int, ...]


def _pair_covariance(rho: Floats, h: Floats, k: Floats) -> Floats:
    """Cov(1[x>-h], 1[y>-k]) for standard normals with correlation rho (the tetrachoric series)."""
    density = np.exp(-(h * h + k * k) / 2.0) / (2.0 * np.pi)
    total = np.zeros_like(h)
    prev_h, prev_k = np.zeros_like(h), np.zeros_like(k)  # He_{-1}, unused at j = 1
    cur_h, cur_k = np.ones_like(h), np.ones_like(k)  # He_0
    power, factorial = np.ones_like(h), 1.0
    for j in range(1, SERIES_TERMS + 1):
        power = power * rho
        factorial *= j
        total += power / factorial * cur_h * cur_k
        prev_h, cur_h = cur_h, h * cur_h - (j - 1) * prev_h
        prev_k, cur_k = cur_k, k * cur_k - (j - 1) * prev_k
    out: Floats = density * total
    return out


def fit_dependence(results: pl.DataFrame) -> Dependence:
    """The weight `a` that reproduces how past results moved together, given their pregame probabilities.

    Two games in one season that share a team have latent correlation +a^2/2 when the team is on the same
    side in both and -a^2/2 otherwise. `a` is chosen so that the model's signed covariance of those pairs
    equals the observed signed product of residuals (result minus probability). `results` needs game_id,
    season, home_id, away_id, p_home and home_won.
    """
    rows: dict[tuple[Any, str], list[tuple[int, int]]] = {}
    frame = results.sort("season", "game_id")
    p = np.clip(frame["p_home"].to_numpy().astype(np.float64), 1e-4, 1 - 1e-4)
    won = frame["home_won"].to_numpy().astype(np.float64)
    home_ids, away_ids = frame["home_id"].to_list(), frame["away_id"].to_list()
    for i, (season, home, away) in enumerate(zip(frame["season"].to_list(), home_ids, away_ids, strict=True)):
        rows.setdefault((season, home), []).append((i, 1))
        rows.setdefault((season, away), []).append((i, -1))
    first: list[int] = []
    second: list[int] = []
    signs: list[int] = []
    for key in sorted(rows, key=lambda item: (item[0], item[1])):
        mine = rows[key]
        for x in range(len(mine)):
            for y in range(x + 1, len(mine)):
                (i, si), (j, sj) = mine[x], mine[y]
                if {home_ids[i], away_ids[i]} == {home_ids[j], away_ids[j]}:
                    continue  # a rematch shares both teams; it is not a one-team pair
                first.append(i)
                second.append(j)
                signs.append(si * sj)
    if not first:
        raise ValueError("no pairs of games share a team")
    i_, j_ = np.array(first), np.array(second)
    sign = np.array(signs, dtype=np.float64)
    resid = won - p
    observed = float((sign * resid[i_] * resid[j_]).mean())
    h, k = ndtri(p[i_]), ndtri(p[j_])

    def gap(a: float) -> float:
        return float((sign * _pair_covariance(sign * a * a / 2.0, h, k)).mean()) - observed

    if gap(0.0) >= 0.0:
        a = 0.0
    elif gap(1.0) <= 0.0:
        a = 1.0
    else:
        a = float(brentq(gap, 0.0, 1.0, xtol=1e-6))
    return Dependence(a, len(first), observed, tuple(sorted(set(frame["season"].to_list()))))
