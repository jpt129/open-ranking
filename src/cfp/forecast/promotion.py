"""The promotion rule (VT-14), as code.

A component is promoted only if the primary held-out score improves and bubble Brier worsens by no more
than 0.01. One season is a pilot. This reports; a person rules.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Final

BUBBLE_ALLOWANCE: Final = 0.01
MIN_SEASONS: Final = 2


@dataclass(frozen=True)
class Scores:
    primary: float  # held-out weekly rank score, or final-field log loss: lower is better
    bubble_brier: float | None  # Brier on the bubble cohort; None if it could not be measured


@dataclass(frozen=True)
class Decision:
    promote: bool
    reason: str


def decide(baseline: Scores, candidate: Scores, *, seasons: int) -> Decision:
    """Whether the candidate passes the rule over `seasons` held-out seasons."""
    if seasons < MIN_SEASONS:
        return Decision(False, f"{seasons} held-out season is a pilot, not a test")
    if not candidate.primary < baseline.primary:
        return Decision(
            False, f"primary score did not improve ({baseline.primary:.6g} to {candidate.primary:.6g})"
        )
    if any(math.isnan(v) for v in (baseline.primary, candidate.primary)):
        return Decision(False, "a primary score is not a number, so the rule cannot be applied")
    measured = [
        v for v in (baseline.bubble_brier, candidate.bubble_brier) if v is not None and not math.isnan(v)
    ]
    if len(measured) != 2 or baseline.bubble_brier is None or candidate.bubble_brier is None:
        return Decision(False, "bubble Brier was not measured for both, so the rule cannot be applied")
    worse = round(candidate.bubble_brier - baseline.bubble_brier, 12)
    if worse > BUBBLE_ALLOWANCE:
        return Decision(False, f"bubble Brier worsened by {worse:.4f}, more than {BUBBLE_ALLOWANCE}")
    return Decision(
        True,
        f"primary score improved ({baseline.primary:.6g} to {candidate.primary:.6g}) and bubble Brier "
        f"changed by {worse:+.4f}",
    )
