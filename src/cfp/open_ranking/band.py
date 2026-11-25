"""Reference band (OR-03): the bubble strength a team is measured against.

In team A's fold (A's games removed, A not a candidate), rank the remaining FBS strengths. The band is ranks
1-8 for a four-team field, 9-16 for twelve, 21-28 for twenty-four; its strength is the average of those eight.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Final

from cfp.open_ranking.strength import Fit

BAND_BY_FIELD: Final[dict[int, tuple[int, int]]] = {4: (1, 8), 12: (9, 16), 24: (21, 28)}


class BandError(ValueError):
    """The band cannot be formed."""


@dataclass(frozen=True)
class Band:
    members: tuple[str, ...]  # strongest first
    strength: float  # average strength of the members
    ranks: tuple[int, int]


def field_size(season: int) -> int:
    """Teams in the playoff field: 4 through 2023, 12 for 2024-2026, 24 from 2027 (BR-2014..BR-2027)."""
    if season < 2014:
        raise BandError(f"no playoff field is defined for {season}")
    return 4 if season <= 2023 else 12 if season <= 2026 else 24


def band_ranks(season: int) -> tuple[int, int]:
    return BAND_BY_FIELD[field_size(season)]


def reference_band(fold: Fit, size: int) -> Band:
    """The band among the strengths in `fold`, which already leaves out the fold's excluded team."""
    if size not in BAND_BY_FIELD:
        raise BandError(f"no band is defined for a field size of {size}")
    first, last = BAND_BY_FIELD[size]
    if len(fold.theta) < last:
        raise BandError(f"the band needs {last} teams; the fold has {len(fold.theta)}")
    ranked = sorted(fold.theta.items(), key=lambda item: (-item[1], item[0]))[first - 1 : last]
    total = 0.0
    for _, strength in ranked:  # summed strongest first, so the result does not depend on input order
        total += strength
    return Band(tuple(team for team, _ in ranked), total / len(ranked), (first, last))
