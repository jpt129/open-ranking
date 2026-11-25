"""Calibration of the link scale and ridge penalties (OR-04, VT-07).

For each game from `first_week` on, strengths are fitted on that season's earlier weeks only, and the game is
predicted from d = strength(home) - strength(away) + home advantage (none on a neutral field). The penalties
and the scale t are the grid point with the lowest log loss of p = 1/(1+exp(-d/t)) against who actually won,
pooled over the training seasons. Only game results are used: no committee ranking, poll or betting line
(OR-12).
"""

from __future__ import annotations

import math
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any, Final

import polars as pl

from cfp.open_ranking.strength import INDEPENDENT, Engine, Params

FIRST_WEEK: Final = 8  # the first ledger follows week 7, so the link is only ever used from week 8 on
BINS: Final = 10
_EPS: Final = 1e-12

Weeks = list[tuple[int, Engine | None, pl.DataFrame]]


@dataclass(frozen=True)
class Grid:
    lambda_c: tuple[float, ...]
    lambda_u: tuple[float, ...]
    t: tuple[float, ...]


DEFAULT_GRID: Final = Grid(
    lambda_c=(0.25, 0.5, 1.0, 2.0, 4.0, 8.0, 16.0, 32.0),
    lambda_u=(0.25, 0.5, 1.0, 2.0, 4.0, 8.0, 16.0, 32.0),
    t=tuple(round(3.0 + 0.25 * i, 2) for i in range(69)),  # 3.00 to 20.00
)


@dataclass(frozen=True)
class Prediction:
    season: int
    game_id: str
    week: int
    teams: tuple[str, str]  # home, away
    d: float  # pregame strength difference in points, from the home side
    neutral: bool
    home_won: bool


@dataclass(frozen=True)
class Choice:
    params: Params
    t: float
    log_loss: float
    brier: float
    n: int
    at_grid_edge: tuple[str, ...]  # which of lambda_c, lambda_u, t sit on the edge of the grid


def _usable(games: pl.DataFrame) -> pl.DataFrame:
    return games.filter(pl.col("ordinary_fbs") & ~pl.col("margin_excluded")).sort("game_id")


def _engines(games: pl.DataFrame, cap: int, first_week: int) -> Weeks:
    """(week, engine on earlier weeks, that week's games) for every week from first_week that has games."""
    usable = _usable(games)
    if usable["week"].null_count():
        raise ValueError("a game has no week")
    out: Weeks = []
    for week in sorted(w for w in usable["week"].unique().to_list() if w >= first_week):
        earlier = usable.filter(pl.col("week") < week)
        engine = Engine(earlier, Params(1.0, 1.0, cap)) if earlier.height else None
        out.append((int(week), engine, usable.filter(pl.col("week") == week)))
    return out


def _predict(season: int, weeks: Weeks, params: Params) -> list[Prediction]:
    out: list[Prediction] = []
    for week, engine, slate in weeks:
        fit = engine.with_penalties(params).fit() if engine is not None else None
        for g in slate.iter_rows(named=True):
            sides = []
            for team, league in ((g["home_id"], g["home_conf"]), (g["away_id"], g["away_conf"])):
                if fit is None:
                    sides.append(0.0)
                elif team in fit.theta:
                    sides.append(fit.theta[team])
                else:  # not yet played this season: its league's effect, or zero for an independent
                    sides.append(0.0 if league == INDEPENDENT else fit.conference.get(league, 0.0))
            site = 0.0 if g["neutral"] or fit is None else fit.home_adv
            out.append(
                Prediction(
                    season,
                    g["game_id"],
                    week,
                    (g["home_id"], g["away_id"]),
                    sides[0] - sides[1] + site,
                    bool(g["neutral"]),
                    g["winner_id"] == g["home_id"],
                )
            )
    return out


def pregame(
    games: pl.DataFrame, params: Params, season: int, first_week: int = FIRST_WEEK
) -> list[Prediction]:
    """Pregame predictions for one season's games from `first_week` on, each from earlier weeks only."""
    return _predict(season, _engines(games, params.cap, first_week), params)


def _p(d: float, t: float) -> float:
    z = d / t
    if z >= 0:
        return 1.0 / (1.0 + math.exp(-z))
    grown = math.exp(z)
    return grown / (1.0 + grown)


def log_loss(predictions: Sequence[Prediction], t: float) -> float:
    total = 0.0
    for item in predictions:
        p = min(max(_p(item.d, t), _EPS), 1.0 - _EPS)
        total -= math.log(p if item.home_won else 1.0 - p)
    return total / len(predictions)


def brier(predictions: Sequence[Prediction], t: float) -> float:
    return sum((_p(item.d, t) - item.home_won) ** 2 for item in predictions) / len(predictions)


def venue_only(predictions: Sequence[Prediction]) -> tuple[float, float]:
    """(log loss, Brier) of the venue-only model: the home side's win rate at home, one half when neutral.

    The rate is taken from the same games it is scored on, which flatters this benchmark slightly.
    """
    at_home = [item for item in predictions if not item.neutral]
    rate = sum(item.home_won for item in at_home) / len(at_home) if at_home else 0.5
    rate = min(max(rate, _EPS), 1.0 - _EPS)
    ll = sq = 0.0
    for item in predictions:
        p = 0.5 if item.neutral else rate
        ll -= math.log(p if item.home_won else 1.0 - p)
        sq += (p - item.home_won) ** 2
    return ll / len(predictions), sq / len(predictions)


class Search:
    """Pregame predictions for every penalty pair on the grid, for every season."""

    def __init__(
        self, grid: Grid, cap: int, by_point: dict[tuple[float, float], dict[int, list[Prediction]]]
    ) -> None:
        self.grid = grid
        self.cap = cap
        self._by_point = by_point

    @property
    def seasons(self) -> list[int]:
        return sorted(next(iter(self._by_point.values())))

    def predictions(self, params: Params, seasons: Sequence[int]) -> list[Prediction]:
        table = self._by_point[(params.lambda_c, params.lambda_u)]
        return [item for season in sorted(seasons) for item in table[season]]

    def table(self, seasons: Sequence[int]) -> list[dict[str, Any]]:
        """The best t and its log loss for each penalty pair, over `seasons`."""
        if not seasons:
            raise ValueError("no seasons to score")
        rows = []
        for lam_c in self.grid.lambda_c:
            for lam_u in self.grid.lambda_u:
                preds = self.predictions(Params(lam_c, lam_u, self.cap), seasons)
                loss, t = min((log_loss(preds, t), t) for t in self.grid.t)
                rows.append({"lambda_c": lam_c, "lambda_u": lam_u, "t": t, "log_loss": loss, "n": len(preds)})
        return rows

    def choose(self, seasons: Sequence[int]) -> Choice:
        """The grid point with the lowest pooled log loss; ties go to the first in grid order."""
        best = min(self.table(seasons), key=lambda row: row["log_loss"])
        params = Params(best["lambda_c"], best["lambda_u"], self.cap)
        preds = self.predictions(params, seasons)
        edge = tuple(
            name
            for name, value, axis in (
                ("lambda_c", params.lambda_c, self.grid.lambda_c),
                ("lambda_u", params.lambda_u, self.grid.lambda_u),
                ("t", best["t"], self.grid.t),
            )
            if value in (axis[0], axis[-1])
        )
        return Choice(params, best["t"], best["log_loss"], brier(preds, best["t"]), len(preds), edge)


def search(
    seasons: Mapping[int, pl.DataFrame],
    grid: Grid = DEFAULT_GRID,
    first_week: int = FIRST_WEEK,
    cap: int = 24,
) -> Search:
    """Fit every penalty pair on every season's rolling weeks. `seasons` maps a season to snapshot games."""
    designs = {season: _engines(games, cap, first_week) for season, games in sorted(seasons.items())}
    by_point: dict[tuple[float, float], dict[int, list[Prediction]]] = {}
    for lam_c in grid.lambda_c:
        for lam_u in grid.lambda_u:
            params = Params(lam_c, lam_u, cap)
            by_point[(lam_c, lam_u)] = {s: _predict(s, weeks, params) for s, weeks in designs.items()}
    return Search(grid, cap, by_point)


def report(found: Search, targets: Sequence[int]) -> dict[str, Any]:
    """Out-of-sample check: each target season is scored with parameters chosen on earlier seasons only."""
    rolling: list[dict[str, Any]] = []
    scored: list[tuple[float, bool]] = []
    for season in sorted(targets):
        earlier = [s for s in found.seasons if s < season]
        choice = found.choose(earlier)
        preds = found.predictions(choice.params, [season])
        flat_ll, flat_brier = venue_only(preds)
        rolling.append(
            {
                "season": season,
                "trained_on": earlier,
                "lambda_c": choice.params.lambda_c,
                "lambda_u": choice.params.lambda_u,
                "t": choice.t,
                "n": len(preds),
                "log_loss": log_loss(preds, choice.t),
                "brier": brier(preds, choice.t),
                "venue_only_log_loss": flat_ll,
                "venue_only_brier": flat_brier,
            }
        )
        scored += [(_p(item.d, choice.t), item.home_won) for item in preds]
    reliability: list[dict[str, Any]] = []
    for b in range(BINS):
        lo, hi = b / BINS, (b + 1) / BINS
        inside = [(p, won) for p, won in scored if lo <= p < hi or (b == BINS - 1 and p == 1.0)]
        reliability.append(
            {
                "bin": f"{lo:.1f}-{hi:.1f}",
                "n": len(inside),
                "mean_predicted": sum(p for p, _ in inside) / len(inside) if inside else None,
                "home_win_rate": sum(won for _, won in inside) / len(inside) if inside else None,
            }
        )
    return {"rolling": rolling, "reliability": reliability}
