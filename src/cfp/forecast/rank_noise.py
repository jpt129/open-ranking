"""Rank noise (SC-03, SC-05): a baseline's order made into a distribution of orders.

A baseline gives every team a place, 1 first. Orders are drawn one team at a time with chance proportional to
exp(-place / tau) among the teams not yet drawn (a Plackett-Luce draw). One number, the temperature tau, says
how far the committee's list strays from the baseline: near zero reproduces the baseline; larger values mix
neighbours. It is fitted by maximum likelihood on the committee's actual first 25 picks in earlier seasons,
with every team in the field in the denominator.

Draws use the Gumbel-max form of the same model, from one generator built on the recorded seed.
"""

from __future__ import annotations

import math
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Final

import numpy as np
import numpy.typing as npt
from scipy.optimize import minimize_scalar

Ints = npt.NDArray[np.int64]

TAU_BOUNDS: Final = (0.05, 200.0)


def _picks(order: Sequence[str], observed: Sequence[str]) -> list[int]:
    place = {team: k for k, team in enumerate(order)}
    if len(place) != len(order):
        raise ValueError("a team appears twice in the order")
    out: list[int] = []
    seen: set[str] = set()
    for team in observed:
        if team not in place:
            raise ValueError(f"{team} was ranked but is not in the order")
        if team in seen:
            raise ValueError(f"{team} appears twice in the ranking")
        seen.add(team)
        out.append(place[team])
    return out


def _log_likelihood(size: int, picks: Sequence[int], tau: float) -> float:
    score = -np.arange(size, dtype=np.float64) / tau
    alive = np.ones(size, dtype=bool)
    total = 0.0
    for k in picks:
        rest = score[alive]
        top = float(rest[0])  # scores fall with place, so the first team left has the largest
        total += float(score[k]) - (top + math.log(float(np.exp(rest - top).sum())))
        alive[k] = False
    return total


def log_likelihood(order: Sequence[str], observed: Sequence[str], tau: float) -> float:
    """Log chance of the committee's picks, in their order, given the baseline's order and a temperature."""
    if not tau > 0:
        raise ValueError("the temperature must be positive")
    return _log_likelihood(len(order), _picks(order, observed), tau)


@dataclass(frozen=True)
class Temperature:
    tau: float
    releases: int
    log_likelihood: float
    picks: int


def fit_temperature(examples: Sequence[tuple[Sequence[str], Sequence[str]]]) -> Temperature:
    """The temperature that makes the observed rankings most likely, from (baseline order, actual) pairs."""
    if not examples:
        raise ValueError("no releases to fit the temperature on")
    cases = [(len(order), _picks(order, observed)) for order, observed in examples]

    def loss(log_tau: float) -> float:
        return -sum(_log_likelihood(size, picks, math.exp(log_tau)) for size, picks in cases)

    low, high = (math.log(b) for b in TAU_BOUNDS)
    found = minimize_scalar(loss, bounds=(low, high), method="bounded", options={"xatol": 1e-7})
    tau = math.exp(float(found.x))
    return Temperature(tau, len(cases), -float(found.fun), sum(len(picks) for _, picks in cases))


def sample_orders(size: int, tau: float, n: int, *, seed: int) -> Ints:
    """`n` sampled orders of a baseline with `size` teams: row r lists baseline places (0 first) by rank."""
    if isinstance(seed, bool) or not isinstance(seed, int) or seed < 0:
        raise ValueError("a recorded seed is needed: a whole number, zero or more")
    if not tau > 0:
        raise ValueError("the temperature must be positive")
    rng = np.random.default_rng(seed)
    keys = -np.arange(size, dtype=np.float64) / tau + rng.gumbel(size=(n, size))
    out: Ints = np.argsort(-keys, axis=1, kind="stable").astype(np.int64)
    return out


def rank_frequencies(orders: Ints, top: int = 25) -> Ints:
    """Counts by (baseline place, rank): columns are ranks 1..top, then one column for "outside"."""
    n, size = orders.shape
    counts = np.zeros((size, top + 1), dtype=np.int64)
    for rank in range(min(top, size)):
        counts[:, rank] = np.bincount(orders[:, rank], minlength=size)
    counts[:, top] = n - counts[:, :top].sum(axis=1)
    return counts


def published_probability(count: int, n: int) -> float:
    """A path count as a probability that is never printed as 0 or 1.

    No finite sample shows that something cannot happen, so none and all are published half a path short of
    the edge. The count itself is published beside it.
    """
    if not 0 <= count <= n or n < 1:
        raise ValueError(f"a count of {count} out of {n} paths is not possible")
    return min(max(count, 0.5), n - 0.5) / n
