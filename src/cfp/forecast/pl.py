"""The rank distribution published with each weekly forecast (SC-05).

Sampling and the temperature fit live in `cfp.forecast.rank_noise`; this module is the published side: the
sampled lists, each team's rank counts and summary, and pairwise probabilities for bubble comparisons.

The bubble is defined before any result is seen (VT-12): the teams within five baseline places of the
projected last at-large team.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any, Final

import numpy as np
from numpy.typing import NDArray

from cfp.forecast.rank_noise import published_probability, rank_frequencies, sample_orders

__all__ = [
    "BUBBLE_WIDTH",
    "Ints",
    "bubble_places",
    "pairwise_counts",
    "published_probability",
    "rank_frequencies",
    "rank_summary",
    "sample_orders",
]

BUBBLE_WIDTH: Final = 5
Ints = NDArray[np.int64]


def rank_summary(counts: Sequence[int], paths: int, cuts: Sequence[int], top: int = 25) -> dict[str, Any]:
    """One team's published rank outputs from its counts by rank (`top` ranks, then "outside")."""
    if len(counts) != top + 1 or sum(counts) != paths:
        raise ValueError(f"the rank counts do not cover {paths} paths over {top} ranks and outside")
    inside = paths - counts[top]
    running, median = 0, None
    for rank, count in enumerate(counts[:top], start=1):
        running += count
        if median is None and 2 * running >= paths:
            median = rank
    return {
        "rank_counts": list(counts),
        "top25_paths": inside,
        "p_top25": published_probability(inside, paths),
        "median_rank": median if median is not None else f"outside {top}",
        "p_rank_at_most": {str(k): published_probability(sum(counts[:k]), paths) for k in cuts if k <= top},
    }


def pairwise_counts(orders: Ints, places: Sequence[int]) -> Ints:
    """Paths on which the team at baseline place `places[i]` is ranked ahead of the one at `places[j]`."""
    n, size = orders.shape
    if len(set(places)) != len(places):
        raise ValueError("a baseline place is listed twice")
    if any(not 0 <= place < size for place in places):
        raise ValueError("a baseline place is outside the sampled lists")
    position = np.empty_like(orders)
    position[np.arange(n)[:, None], orders] = np.arange(size, dtype=np.int64)[None, :]
    chosen = position[:, list(places)]
    out: Ints = (chosen[:, :, None] < chosen[:, None, :]).sum(axis=0).astype(np.int64)
    return out


def bubble_places(last_at_large: int, size: int, width: int = BUBBLE_WIDTH) -> list[int]:
    """Baseline places (0 first) within `width` of the projected last at-large team's place."""
    if not 0 <= last_at_large < size:
        raise ValueError("the last at-large place is outside the baseline")
    return list(range(max(0, last_at_large - width), min(size, last_at_large + width + 1)))
