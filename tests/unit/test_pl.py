"""SC-05: sampled orders with a recorded seed, rank distributions and pairwise bubble probabilities."""

from __future__ import annotations

import numpy as np
import pytest

from cfp.forecast.pl import (
    bubble_places,
    pairwise_counts,
    published_probability,
    rank_frequencies,
    rank_summary,
    sample_orders,
)

N = 4000


def test_pl_sample_seed_reproducible() -> None:
    one = sample_orders(40, 2.9, N, seed=11)
    assert np.array_equal(one, sample_orders(40, 2.9, N, seed=11))  # the recorded seed gives the same lists
    assert not np.array_equal(one, sample_orders(40, 2.9, N, seed=12))
    assert one.shape == (N, 40)
    assert all(sorted(row) == list(range(40)) for row in one[:50].tolist())  # each list ranks every team once
    for bad in (None, -1, True, 1.5):
        with pytest.raises(ValueError, match="recorded seed"):
            sample_orders(40, 2.9, 10, seed=bad)  # type: ignore[arg-type]


def test_rank_dist_outputs() -> None:
    orders = sample_orders(40, 2.9, N, seed=5)
    counts = rank_frequencies(orders, 25)
    assert counts.shape == (40, 26)
    assert (counts.sum(axis=1) == N).all()  # every team has a rank or "outside 25" on every path
    assert (counts[:, :25].sum(axis=0) == N).all()  # every rank is held by one team on every path
    top = rank_summary([int(c) for c in counts[0]], N, (4, 12, 25))
    assert top["median_rank"] in (1, 2)
    assert top["top25_paths"] == N - int(counts[0, 25])
    assert top["p_top25"] == published_probability(top["top25_paths"], N)
    assert set(top["p_rank_at_most"]) == {"4", "12", "25"}
    assert top["p_rank_at_most"]["4"] <= top["p_rank_at_most"]["12"] <= top["p_rank_at_most"]["25"]
    far = rank_summary([int(c) for c in counts[39]], N, (4, 12, 25))
    assert far["median_rank"] == "outside 25"  # a median outside the list prints the category, not a number
    assert 0 < far["p_top25"] < 0.5
    with pytest.raises(ValueError, match="paths"):
        rank_summary([1, 2, 3], N, (4,), top=2)


def test_pairwise_counts_match_a_direct_count() -> None:
    orders = sample_orders(30, 2.9, N, seed=9)
    places = [9, 10, 11, 12, 13]
    ahead = pairwise_counts(orders, places)
    assert ahead.shape == (5, 5)
    assert (np.diag(ahead) == 0).all()
    assert ((ahead + ahead.T)[~np.eye(5, dtype=bool)] == N).all()  # one of the two is ahead on every path
    position = {int(team): rank for rank, team in enumerate(orders[0].tolist())}
    direct = sum(1 for row in orders.tolist() if row.index(9) < row.index(13))
    assert ahead[0, 4] == direct
    assert position  # the first list was readable
    assert ahead[0, 4] > ahead[4, 0]  # the better-placed team is ahead more often
    assert ahead[0, 1] > N / 2
    with pytest.raises(ValueError, match="twice"):
        pairwise_counts(orders, [3, 3])
    with pytest.raises(ValueError, match="outside"):
        pairwise_counts(orders, [3, 30])


def test_bubble_places_are_within_five_of_the_last_at_large() -> None:
    assert bubble_places(11, 40) == list(range(6, 17))  # places are counted from 0
    assert bubble_places(2, 40) == list(range(0, 8))
    assert bubble_places(38, 40) == list(range(33, 40))
    with pytest.raises(ValueError, match="outside"):
        bubble_places(40, 40)
