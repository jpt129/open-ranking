"""Strength engine (OR-02).

capped margin = strength(home) - strength(away) + home advantage (zero on a neutral field) + noise
strength(team) = conference effect + team deviation, both shrunk toward zero by ridge penalties.

Only FBS-versus-FBS games with a usable margin enter the fit. An independent has one individual effect and no
league effect; its penalty is 1/(1/lambda_c + 1/lambda_u), which gives it the same prior variance as a league
team (OR-02a). The home advantage is estimated in the same fit and is not penalised. `exclude` removes every
game involving one team, so nothing that team did can move the strengths used to grade it. Nothing carries
over from an earlier season.

Rows are put in game-id order before any arithmetic, so the order of the input never matters.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Final, Literal

import numpy as np
import polars as pl

INDEPENDENT: Final = "fbs-independents"
IndependentPenalty = Literal["combined", "team"]


class StrengthError(ValueError):
    """The games cannot be fitted."""


@dataclass(frozen=True)
class Params:
    lambda_c: float  # ridge penalty on conference effects
    lambda_u: float  # ridge penalty on team deviations
    cap: int = 24  # margins are capped at +/- cap points
    independent_penalty: IndependentPenalty = "combined"


@dataclass(frozen=True)
class Fit:
    theta: dict[str, float]  # strength of every FBS team except the excluded one
    conference: dict[str, float]  # league effects (independents have none)
    deviation: dict[str, float]  # team deviations; for an independent, its whole individual effect
    home_adv: float
    n_games: int
    excluded: str | None


class Engine:
    """The season's design, built once; `fit` solves it with one team's games removed."""

    def __init__(self, games: pl.DataFrame, params: Params) -> None:
        if params.lambda_c <= 0 or params.lambda_u <= 0 or params.cap <= 0:
            raise StrengthError("penalties and the cap must be positive")
        if params.independent_penalty not in ("combined", "team"):
            raise StrengthError(
                f"independent_penalty must be combined or team; got {params.independent_penalty!r}"
            )
        usable = games.filter(
            pl.col("ordinary_fbs")
            & ~pl.col("margin_excluded")
            & (pl.col("home_div") == "fbs")
            & (pl.col("away_div") == "fbs")
        ).sort("game_id")
        if usable.height == 0:
            raise StrengthError("no FBS games to fit")
        if usable["game_id"].is_duplicated().any():
            raise StrengthError("a game appears twice")
        conf: dict[str, str] = {}
        for side in ("home", "away"):
            for team, league in usable.select(f"{side}_id", f"{side}_conf").iter_rows():
                if league is None:
                    raise StrengthError(f"{team} has no conference on a game row")
                if conf.setdefault(team, league) != league:
                    raise StrengthError(f"{team} appears in two conferences: {conf[team]} and {league}")
        self.params = params
        self.teams = sorted(conf)
        self.conf = conf
        self.leagues = sorted({league for league in conf.values() if league != INDEPENDENT})
        n_leagues, n_teams = len(self.leagues), len(self.teams)
        league_col = {league: 1 + i for i, league in enumerate(self.leagues)}
        self._team_col = {team: 1 + n_leagues + i for i, team in enumerate(self.teams)}
        width = 1 + n_leagues + n_teams
        x = np.zeros((usable.height, width))
        home_ids, away_ids = usable["home_id"].to_list(), usable["away_id"].to_list()
        x[:, 0] = [0.0 if neutral else 1.0 for neutral in usable["neutral"].to_list()]
        for i, (home, away) in enumerate(zip(home_ids, away_ids, strict=True)):
            for team, sign in ((home, 1.0), (away, -1.0)):
                x[i, self._team_col[team]] += sign
                if conf[team] != INDEPENDENT:
                    x[i, league_col[conf[team]]] += sign
        margin = (usable["home_pts"] - usable["away_pts"]).clip(-params.cap, params.cap)
        self._x = x
        self._y = margin.cast(pl.Float64).to_numpy()
        self._home, self._away = home_ids, away_ids
        combined = 1.0 / (1.0 / params.lambda_c + 1.0 / params.lambda_u)
        lone = combined if params.independent_penalty == "combined" else params.lambda_u
        penalty = np.zeros(width)
        penalty[1 : 1 + n_leagues] = params.lambda_c
        for team, col in self._team_col.items():
            penalty[col] = lone if conf[team] == INDEPENDENT else params.lambda_u
        self._penalty = penalty
        self._league_col = league_col

    def fit(self, exclude: str | None = None) -> Fit:
        keep = np.array([exclude not in pair for pair in zip(self._home, self._away, strict=True)])
        x, y = self._x[keep], self._y[keep]
        gram = x.T @ x + np.diag(self._penalty)
        rhs = x.T @ y
        if not x[:, 0].any():  # no game at a home site: the home advantage cannot be estimated, so it is zero
            gram[0, :] = 0.0
            gram[:, 0] = 0.0
            gram[0, 0] = 1.0
            rhs[0] = 0.0
        beta = np.linalg.solve(gram, rhs)
        conference = {league: float(beta[col]) for league, col in self._league_col.items()}
        deviation = {team: float(beta[col]) for team, col in self._team_col.items() if team != exclude}
        theta = {
            team: value + (conference[self.conf[team]] if self.conf[team] != INDEPENDENT else 0.0)
            for team, value in deviation.items()
        }
        return Fit(theta, conference, deviation, float(beta[0]), int(keep.sum()), exclude)


def fit(games: pl.DataFrame, params: Params, exclude: str | None = None) -> Fit:
    """Fit the season's strengths, optionally with every game involving `exclude` removed."""
    return Engine(games, params).fit(exclude)


def fit_all(games: pl.DataFrame, params: Params) -> dict[str, Fit]:
    """One fold per FBS team: the fit with that team's games removed."""
    engine = Engine(games, params)
    return {team: engine.fit(team) for team in engine.teams}
