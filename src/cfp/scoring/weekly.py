"""Weekly rank score (VT-11) and its secondary cohort (VT-11a).

S = (1 / (25 N)) * sum over teams i and cutoffs k = 1..25 of (P_i(rank <= k) - 1[rank_i <= k])^2.

N is every team the forecast could have ranked, read from the data for that season. A team the forecast
gives no row is scored as given no chance, never skipped.
"""

from __future__ import annotations

import math
from collections.abc import Mapping, Sequence
from itertools import pairwise
from typing import Any, Final

RANKED: Final = 25
SECONDARY_TOP: Final = 35


def cumulative_from_counts(counts: Sequence[int], paths: int) -> list[float]:
    """P(rank <= k) for k = 1..25 from a team's path counts by rank (25 ranks, then "outside")."""
    if len(counts) != RANKED + 1 or sum(counts) != paths or paths < 1:
        raise ValueError(f"the rank counts do not cover {paths} paths over {RANKED} ranks and outside")
    out, running = [], 0
    for count in counts[:RANKED]:
        running += count
        out.append(running / paths)
    return out


def _check(forecast: Mapping[str, Sequence[float]], actual: Sequence[str], teams: Sequence[str]) -> None:
    known = set(teams)
    if len(known) != len(teams):
        raise ValueError("a team is listed twice")
    if len(set(actual)) != len(actual) or len(actual) > RANKED:
        raise ValueError(f"the actual ranking must be at most {RANKED} different teams")
    for team in actual:
        if team not in known:
            raise ValueError(f"{team} was ranked but is not among the teams scored")
    for team, row in forecast.items():
        if team not in known:
            raise ValueError(f"{team} has a forecast but is not among the teams scored")
        if len(row) != RANKED:
            raise ValueError(f"{team}: a forecast needs {RANKED} cumulative probabilities, not {len(row)}")
        if any(not 0.0 <= p <= 1.0 for p in row) or any(b < a for a, b in pairwise(row)):
            raise ValueError(f"{team}: cumulative probabilities must lie in 0..1 and never fall")


def weekly_score(
    forecast: Mapping[str, Sequence[float]], actual: Sequence[str], teams: Sequence[str]
) -> float:
    """S over `teams`. `forecast[team][k - 1]` is P(rank <= k)."""
    _check(forecast, actual, teams)
    if not teams:
        raise ValueError("no teams to score")
    place = {team: k for k, team in enumerate(actual, start=1)}
    nothing = [0.0] * RANKED
    total = 0.0
    for team in teams:
        row = forecast.get(team, nothing)
        rank = place.get(team)
        for k in range(1, RANKED + 1):
            total += (row[k - 1] - (1.0 if rank is not None and rank <= k else 0.0)) ** 2
    return total / (RANKED * len(teams))


def secondary_cohort(order: Sequence[str], actual: Sequence[str]) -> list[str]:
    """VT-11a: the forecast's top 35 together with the actual top 25, each team once."""
    cohort = list(order[:SECONDARY_TOP])
    held = set(cohort)
    cohort.extend(team for team in actual if team not in held)
    return cohort


def movement(
    prior: Sequence[str], forecast_top: Sequence[str], actual: Sequence[str]
) -> dict[str, list[str]]:
    """Who entered and left the top 25 since the prior release, and which of those the forecast had."""
    before, after, called = set(prior), set(actual), set(forecast_top)
    entrants = [t for t in actual if t not in before]
    exits = [t for t in prior if t not in after]
    return {
        "entrants": entrants,
        "exits": exits,
        "entrants_called": [t for t in entrants if t in called],
        "exits_called": [t for t in exits if t not in called],
    }


def rank_error(order: Sequence[str], actual: Sequence[str]) -> dict[str, Any]:
    """Mean absolute rank error on teams in both top 25s, with the share of the actual list that covers."""
    mine = {team: k for k, team in enumerate(order[:RANKED], start=1)}
    errors = [abs(mine[team] - k) for k, team in enumerate(actual, start=1) if team in mine]
    return {
        "jointly_ranked": len(errors),
        "coverage": len(errors) / len(actual) if actual else None,
        "mean_abs_error": sum(errors) / len(errors) if errors else None,
    }


def score_weekly(
    model: str,
    order: Sequence[str],
    forecast: Mapping[str, Sequence[float]],
    actual: Sequence[str],
    teams: Sequence[str],
    *,
    prior: Sequence[str] | None,
) -> dict[str, Any]:
    """One model's scorecard for one release. `order` is its point order, best first."""
    cohort = secondary_cohort(order, actual)
    card: dict[str, Any] = {
        "model": model,
        "teams": len(teams),
        "score": weekly_score(forecast, actual, teams),
        "secondary": {
            "teams": len(cohort),
            "score": weekly_score({t: forecast[t] for t in cohort if t in forecast}, actual, cohort),
        },
        "exact_slots": sum(1 for a, b in zip(order[:RANKED], actual, strict=False) if a == b),
        "rank_error": rank_error(order, actual),
        "movement": movement(prior, order[:RANKED], actual) if prior is not None else None,
    }
    return card


def _binary(p: Sequence[float], y: Sequence[bool]) -> dict[str, Any]:
    if not p:
        return {"n": 0, "brier": None, "log_loss": None}
    if any(not 0.0 < v < 1.0 for v in p):
        raise ValueError("a published probability is never 0 or 1")
    brier = sum((v - (1.0 if o else 0.0)) ** 2 for v, o in zip(p, y, strict=True)) / len(p)
    loss = -sum(math.log(v if o else 1.0 - v) for v, o in zip(p, y, strict=True)) / len(p)
    return {"n": len(p), "brier": brier, "log_loss": loss}


def top25_scores(
    raw: Mapping[str, float], calibrated: Mapping[str, float], *, actual: Sequence[str]
) -> dict[str, Any]:
    """P(top 25) alone: the raw and the calibrated column on the same teams, and raw on every team."""
    inside = set(actual)
    both = [t for t in raw if t in calibrated]
    return {
        "raw": _binary([raw[t] for t in both], [t in inside for t in both]),
        "calibrated": _binary([calibrated[t] for t in both], [t in inside for t in both]),
        "raw_all_teams": _binary(list(raw.values()), [t in inside for t in raw]),
    }
