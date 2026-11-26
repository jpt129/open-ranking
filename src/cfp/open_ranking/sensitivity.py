"""Evidence sensitivity (VT-08): refit the strengths with re-weighted games; results are held fixed.

Each refit draws one exponential weight of mean one for every fitted game and multiplies that game's squared
error by it. The same weight is used in every team's fold. The ridge penalties and the frozen settings are not
touched. The bubble band, every ledger total and the order are then worked again from the refit.

Nothing in the formula's own files is changed for this: the weighted fit is the ordinary fit on a design whose
rows and margins are scaled by the square root of each game's weight, which is weighted least squares. With
every weight equal to one it gives the published totals exactly.

Every refit has its own seed, derived from the edition's seed and the refit's index, so any refit can be run
alone and batching or parallel runs cannot change a number.
"""

from __future__ import annotations

import copy
import hashlib
import json
import multiprocessing
import time
from collections.abc import Iterable, Mapping, Sequence
from concurrent.futures import ProcessPoolExecutor, as_completed
from concurrent.futures.process import BrokenProcessPool
from dataclasses import dataclass
from typing import Final

import numpy as np
import polars as pl

from cfp.open_ranking.band import field_size, reference_band
from cfp.open_ranking.ledger import FCS_LOSS_CP, FCS_WIN_CP, points_cp
from cfp.open_ranking.link import Site, probability, quantize
from cfp.open_ranking.ordering import rank_teams
from cfp.open_ranking.strength import Engine, Params

REFITS: Final = 1000
BATCH: Final = 8  # refits handed to a worker process at a time
LABEL: Final = (
    "Sensitivity to the observed games: how far the result moves when the games behind the strength fit "
    "are re-weighted. It is not a full uncertainty interval."
)


class SensitivityError(ValueError):
    """The refits cannot be run."""


def _seed(text: str) -> int:
    return int.from_bytes(hashlib.sha256(text.encode()).digest()[:8], "big") >> 1  # fits a signed 64-bit


def edition_seed(edition_id: str, sha256: str) -> int:
    """The recorded seed for one edition's refits."""
    return _seed(f"vt08|{edition_id}|{sha256}")


def refit_seed(seed: int, index: int) -> int:
    """The seed of refit number `index` (from 0)."""
    if index < 0:
        raise SensitivityError("a refit index is 0 or more")
    return _seed(f"vt08-refit|{seed}|{index}")


def game_weights(game_ids: Iterable[str], seed: int) -> dict[str, float]:
    """One exponential weight of mean one per game, drawn in game-id order."""
    ids = sorted(set(game_ids))
    uniform = np.random.Generator(np.random.PCG64(seed)).random(len(ids))
    drawn = -np.log1p(-uniform)  # the inverse of the exponential distribution function
    drawn = np.maximum(drawn, np.finfo(np.float64).tiny)  # a draw of exactly zero cannot be a weight
    return {game: float(weight) for game, weight in zip(ids, drawn, strict=True)}


def fitted_games(games: pl.DataFrame, engine: Engine) -> list[str]:
    """The ids of the games in the engine's fit, in its row order."""
    usable = games.filter(
        pl.col("ordinary_fbs")
        & ~pl.col("margin_excluded")
        & (pl.col("home_div") == "fbs")
        & (pl.col("away_div") == "fbs")
    ).sort("game_id")
    same = usable["home_id"].to_list() == engine._home and usable["away_id"].to_list() == engine._away
    if not same:
        raise SensitivityError("the fitted games cannot be matched to the fit's rows")
    return [str(game) for game in usable["game_id"].to_list()]


def weighted(engine: Engine, game_ids: Sequence[str], weights: Mapping[str, float]) -> Engine:
    """The engine with each game's squared error multiplied by its weight. Penalties are unchanged."""
    missing = [game for game in game_ids if game not in weights]
    if missing:
        raise SensitivityError(f"no weight for {len(missing)} fitted games, such as {missing[0]}")
    drawn = np.array([float(weights[game]) for game in game_ids])
    if len(drawn) != engine._x.shape[0]:
        raise SensitivityError("the weights do not line up with the fit's rows")
    if not (np.isfinite(drawn).all() and (drawn > 0).all()):
        raise SensitivityError("every weight must be positive and finite")
    root = np.sqrt(drawn)
    other = copy.copy(engine)
    other._x = engine._x * root[:, None]
    other._y = engine._y * root
    return other


def weighted_totals(
    games: pl.DataFrame, params: Params, t: float, season: int, weights: Mapping[str, float]
) -> dict[str, int]:
    """Every FBS team's ledger total with the strength fit re-weighted. Results and rules are as published."""
    size = field_size(season)
    plain = Engine(games, params)
    engine = weighted(plain, fitted_games(games, plain), weights)
    mine: dict[str, list[dict[str, object]]] = {}
    for g in games.iter_rows(named=True):
        for side in ("home", "away"):
            if g[f"{side}_div"] == "fbs":
                mine.setdefault(g[f"{side}_id"], []).append(g)
    totals: dict[str, int] = {}
    for team in sorted(mine):
        fold = engine.fit(exclude=team)
        band = reference_band(fold, size)
        total = 0
        for g in mine[team]:
            at_home = g["home_id"] == team
            other = "away" if at_home else "home"
            opponent = str(g[f"{other}_id"])
            won = g["winner_id"] == team
            if g[f"{other}_div"] != "fbs":
                total += FCS_WIN_CP if won else FCS_LOSS_CP
                continue
            if opponent not in fold.theta or not engine.games_in_fold(opponent, exclude=team):
                raise SensitivityError(f"{opponent} has no fitted game outside its games with {team}")
            site: Site = "neutral" if g["neutral"] else "home" if at_home else "away"
            q, _ = quantize(probability(band.strength, fold.theta[opponent], fold.home_adv, site, t))
            total += points_cp(won, q)
        totals[team] = total
    return totals


@dataclass(frozen=True)
class Refit:
    index: int
    seed: int
    order: tuple[str, ...]  # best first, settled by head-to-head and the draw as in an edition
    ranks: dict[str, int]
    totals: dict[str, int]

    def digest(self) -> str:
        """A hash of everything the refit produced, for checking a rerun against the published file."""
        record = {"index": self.index, "seed": self.seed, "order": list(self.order), "totals": self.totals}
        text = json.dumps(record, sort_keys=True, separators=(",", ":"))
        return hashlib.sha256(text.encode()).hexdigest()


def refit(
    games: pl.DataFrame,
    params: Params,
    t: float,
    season: int,
    draw: Mapping[str, int],
    *,
    seed: int,
    index: int,
) -> Refit:
    """Refit number `index` of the edition whose seed is `seed`."""
    mine = refit_seed(seed, index)
    ids = fitted_games(games, Engine(games, params))
    totals = weighted_totals(games, params, t, season, game_weights(ids, mine))
    ranked = rank_teams(totals, games, draw)
    return Refit(
        index,
        mine,
        tuple(place.team_id for place in ranked),
        {place.team_id: place.open_rank for place in ranked},
        totals,
    )


def _batch(
    args: tuple[pl.DataFrame, Params, float, int, dict[str, int], int, list[int]],
) -> list[Refit]:
    games, params, t, season, draw, seed, indices = args
    return [refit(games, params, t, season, draw, seed=seed, index=k) for k in indices]


def run(
    games: pl.DataFrame,
    params: Params,
    t: float,
    season: int,
    draw: Mapping[str, int],
    *,
    seed: int,
    indices: Iterable[int],
    workers: int = 1,
    deadline: float | None = None,
) -> list[Refit]:
    """The named refits, in the order asked for. `workers` changes the time taken and nothing else.

    `deadline` is a time.monotonic() value. Past it the run stops with an error and returns nothing: a
    partial set of refits is never a result.
    """
    wanted = list(indices)
    if workers < 1:
        raise SensitivityError("at least one worker")

    def late() -> bool:
        return deadline is not None and time.monotonic() >= deadline

    over = SensitivityError("the refits passed their time limit; nothing was produced")
    if late():
        raise over
    by_index: dict[int, Refit] = {}
    if workers == 1 or len(wanted) < 2:
        for k in wanted:
            if late():
                raise over
            by_index[k] = refit(games, params, t, season, draw, seed=seed, index=k)
        return [by_index[k] for k in wanted]
    # small batches, so a run past its limit stops within a few refits
    share = [wanted[k : k + BATCH] for k in range(0, len(wanted), BATCH)]
    # spawn, never fork: a forked child of a process that has used polars can deadlock (seen on Linux)
    fresh = multiprocessing.get_context("spawn")
    pool = ProcessPoolExecutor(max_workers=min(workers, len(share)), mp_context=fresh)
    try:
        tasks = [pool.submit(_batch, (games, params, t, season, dict(draw), seed, part)) for part in share]
        left = None if deadline is None else max(0.0, deadline - time.monotonic())
        for done in as_completed(tasks, timeout=left):
            by_index |= {one.index: one for one in done.result()}
    except (TimeoutError, BrokenProcessPool) as error:
        # do not wait for the workers: one that hangs must not hold the edition's release up
        running = list((pool._processes or {}).values())
        pool.shutdown(wait=False, cancel_futures=True)
        for process in running:
            process.terminate()
        if isinstance(error, TimeoutError):
            raise over from None
        raise SensitivityError(f"a worker process died: {error}") from error
    pool.shutdown()
    return [by_index[k] for k in wanted]


def middle80(values: Sequence[int]) -> list[int]:
    """The middle 80%: the narrowest ends with at most a tenth of the values beyond each."""
    if not values:
        raise ValueError("no values")
    ordered = sorted(values)
    beyond = len(ordered) // 10
    return [ordered[beyond], ordered[len(ordered) - 1 - beyond]]
