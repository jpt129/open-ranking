"""Link and fixed point (OR-04, OR-01a).

p = 1 / (1 + exp(-d / t)), where d is the bubble strength minus the opponent's, plus the home advantage when
the evaluated team is at home and minus it on the road. q = round_half_even(p * 10^4), in integer centipoints.
"""

from __future__ import annotations

import math
from typing import Final, Literal

Site = Literal["home", "away", "neutral"]
SCALE: Final = 10_000
BOUNDARY: Final = 1e-6
_SIGN: Final[dict[str, float]] = {"home": 1.0, "away": -1.0, "neutral": 0.0}


def probability(bubble: float, opponent: float, home_adv: float, site: Site, t: float) -> float:
    """The chance a bubble-strength team wins this game at the evaluated team's site."""
    if site not in _SIGN:
        raise ValueError(f"site must be home, away or neutral; got {site!r}")
    if not t > 0:
        raise ValueError(f"the scale t must be positive; got {t}")
    d = (bubble - opponent + _SIGN[site] * home_adv) / t
    if d >= 0:
        return 1.0 / (1.0 + math.exp(-d))
    grown = math.exp(d)  # the same value, written so exp never overflows
    return grown / (1.0 + grown)


def quantize(p: float) -> tuple[int, bool]:
    """(q, boundary flag). The flag is set when p * 10^4 lies within 1e-6 of a rounding boundary."""
    if not 0.0 <= p <= 1.0:  # also refuses NaN
        raise ValueError(f"not a probability: {p}")
    scaled = p * SCALE
    boundary = abs(scaled - (math.floor(scaled) + 0.5)) < BOUNDARY
    return round(scaled), boundary  # Python rounds halves to the even neighbour
