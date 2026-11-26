"""Final-field score (VT-12): Brier and log loss for field and bye probabilities, by stratum.

The bubble cohort is set from Baseline 2's order at the issue and is the same for every model scored.
"""

from __future__ import annotations

import math
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from typing import Any, Final

from cfp.forecast.pl import BUBBLE_WIDTH, bubble_places

ROUTES: Final = ("automatic", "at_large")


@dataclass(frozen=True)
class FieldRow:
    """One team in one issue: what was published, and what happened on Selection Day."""

    season: int
    lead: str  # the issue the forecast came from: its lead time
    era: str  # rules era, such as "12-team"
    team: str
    p_field: float
    p_bye: float
    in_field: bool
    bye: bool
    p_automatic: float
    p_at_large: float
    route: str | None  # how the team qualified: "automatic", "at_large", or None if it did not
    bubble: bool  # in Baseline 2's bubble cohort at the issue


def bubble_cohort(order: Sequence[str], last_at_large: str, width: int = BUBBLE_WIDTH) -> frozenset[str]:
    """Teams within `width` Baseline 2 places of the projected last at-large team."""
    if last_at_large not in order:
        raise ValueError(f"{last_at_large} is not in the baseline order")
    return frozenset(order[k] for k in bubble_places(list(order).index(last_at_large), len(order), width))


def _score(p: Sequence[float], y: Sequence[bool]) -> dict[str, Any]:
    if not p:
        return {"n": 0, "brier": None, "log_loss": None}
    if any(not 0.0 < v < 1.0 for v in p):
        raise ValueError("a published probability is never 0 or 1: these rows were not built from an edition")
    brier = sum((v - (1.0 if o else 0.0)) ** 2 for v, o in zip(p, y, strict=True)) / len(p)
    loss = -sum(math.log(v if o else 1.0 - v) for v, o in zip(p, y, strict=True)) / len(p)
    return {"n": len(p), "brier": brier, "log_loss": loss}


def _pair(rows: Sequence[FieldRow]) -> dict[str, Any]:
    return {
        "field": _score([r.p_field for r in rows], [r.in_field for r in rows]),
        "bye": _score([r.p_bye for r in rows], [r.bye for r in rows]),
    }


def _split(rows: Sequence[FieldRow], key: Callable[[FieldRow], str]) -> dict[str, Any]:
    groups: dict[str, list[FieldRow]] = {}
    for row in rows:
        groups.setdefault(key(row), []).append(row)
    return {name: _pair(found) for name, found in sorted(groups.items())}


def field_scores(rows: Sequence[FieldRow]) -> dict[str, Any]:
    """Overall, and by lead time, season, rules era, route and bubble.

    A route is scored as its own event: the chance published for qualifying that way, against whether the
    team did.
    """
    if not rows:
        raise ValueError("no field forecasts to score")
    return {
        "overall": _pair(rows),
        "by": {
            "lead": _split(rows, lambda r: r.lead),
            "season": _split(rows, lambda r: str(r.season)),
            "era": _split(rows, lambda r: r.era),
            "route": {
                "automatic": _score([r.p_automatic for r in rows], [r.route == "automatic" for r in rows]),
                "at_large": _score([r.p_at_large for r in rows], [r.route == "at_large" for r in rows]),
            },
            "bubble": _split(rows, lambda r: "bubble" if r.bubble else "other"),
        },
    }
