"""Rank noise (SC-03, SC-05): a fitted temperature turns a baseline's order into a distribution of orders."""

from __future__ import annotations

import math

import numpy as np
import pytest

from cfp.forecast.rank_noise import (
    fit_temperature,
    log_likelihood,
    published_probability,
    rank_frequencies,
    sample_orders,
)

TEAMS = [f"T{k:03d}" for k in range(130)]


def test_log_likelihood_by_hand() -> None:
    # order A, B, C at temperature 1: weights 1, e^-1, e^-2
    w = [1.0, math.exp(-1), math.exp(-2)]
    assert log_likelihood(["A", "B", "C"], ["B"], 1.0) == pytest.approx(math.log(w[1] / sum(w)))
    both = math.log(w[1] / sum(w)) + math.log(w[0] / (w[0] + w[2]))
    assert log_likelihood(["A", "B", "C"], ["B", "A"], 1.0) == pytest.approx(both)
    assert log_likelihood(["A", "B", "C"], ["A", "B"], 0.2) > log_likelihood(["A", "B", "C"], ["B", "A"], 0.2)
    with pytest.raises(ValueError, match="not in the order"):
        log_likelihood(["A", "B"], ["Z"], 1.0)
    with pytest.raises(ValueError, match="twice"):
        log_likelihood(["A", "B"], ["A", "A"], 1.0)
    with pytest.raises(ValueError, match="positive"):
        log_likelihood(["A", "B"], ["A"], 0.0)


def test_sampling_is_seeded_and_follows_the_order() -> None:
    one = sample_orders(len(TEAMS), 2.0, 2000, seed=7)
    assert one.shape == (2000, 130)
    assert np.array_equal(one, sample_orders(len(TEAMS), 2.0, 2000, seed=7))
    assert not np.array_equal(one, sample_orders(len(TEAMS), 2.0, 2000, seed=8))
    assert (np.sort(one, axis=1) == np.arange(130)).all()  # every row is a full order
    cold = sample_orders(len(TEAMS), 1e-6, 50, seed=1)
    assert (cold == np.arange(130)).all()  # no noise: the baseline's own order
    # the chance the first team is picked first is 1 / sum_k exp(-k / tau)
    tau = 3.0
    expect = 1.0 / sum(math.exp(-k / tau) for k in range(130))
    got = float((sample_orders(130, tau, 40_000, seed=3)[:, 0] == 0).mean())
    assert got == pytest.approx(expect, abs=4 * math.sqrt(expect * (1 - expect) / 40_000))
    for bad in (None, True, -3):
        with pytest.raises(ValueError, match="recorded seed"):
            sample_orders(10, 1.0, 5, seed=bad)  # type: ignore[arg-type]


def test_fit_recovers_the_temperature() -> None:
    truth = 2.5
    drawn = sample_orders(len(TEAMS), truth, 60, seed=11)
    examples = [(TEAMS, [TEAMS[i] for i in row[:25]]) for row in drawn]
    fit = fit_temperature(examples)
    assert fit.tau == pytest.approx(truth, rel=0.15)
    assert fit.releases == 60
    assert fit.log_likelihood == pytest.approx(sum(log_likelihood(o, a, fit.tau) for o, a in examples))
    assert fit.log_likelihood >= sum(log_likelihood(o, a, truth * 2) for o, a in examples)
    with pytest.raises(ValueError, match="no releases"):
        fit_temperature([])


def test_rank_frequencies_and_published_probabilities() -> None:
    drawn = sample_orders(40, 2.0, 10_000, seed=5)
    counts = rank_frequencies(drawn, top=25)
    assert counts.shape == (40, 26)  # team by rank 1..25, then "outside 25"
    assert (counts.sum(axis=1) == 10_000).all()
    assert (counts[:, :25].sum(axis=0) == 10_000).all()  # each rank holds one team on every path
    assert counts[0, 0] > counts[1, 0] > counts[5, 0]
    # never 0 or 1: a count of none or all is published as half a path short of the edge
    assert published_probability(0, 10_000) == pytest.approx(0.00005)
    assert published_probability(10_000, 10_000) == pytest.approx(0.99995)
    assert published_probability(2_500, 10_000) == 0.25
    with pytest.raises(ValueError, match="count"):
        published_probability(11, 10)
