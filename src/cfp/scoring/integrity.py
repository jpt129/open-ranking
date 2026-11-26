"""Bracket integrity (VT-13): one bracket is well formed, and a published field section adds up."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any

from cfp.rules.engine import Entry


class IntegrityError(ValueError):
    """A bracket or a field section does not add up."""


def check_path(entries: Sequence[Entry], *, field: int, byes: int, hosts: int) -> None:
    """One path's bracket: every team once, seeds 1..field once each, the era's byes and hosts."""
    seen: set[str] = set()
    for entry in entries:
        if entry.team_id in seen:
            raise IntegrityError(f"{entry.team_id} is listed twice in one bracket")
        seen.add(entry.team_id)
    inside = [e for e in entries if e.qualifier]
    if len(inside) != field:
        raise IntegrityError(f"{len(inside)} teams in the field, not {field}")
    held: dict[int, str] = {}
    for entry in inside:
        if entry.seed is None or not 1 <= entry.seed <= field:
            raise IntegrityError(f"{entry.team_id} is in the field with seed {entry.seed}")
        if entry.seed in held:
            raise IntegrityError(f"seed {entry.seed} is held by {held[entry.seed]} and {entry.team_id}")
        held[entry.seed] = entry.team_id
    outside = [
        e.team_id for e in entries if not e.qualifier and (e.seed is not None or e.bye or e.host_round)
    ]
    if outside:
        raise IntegrityError(f"{outside[0]} is outside the field but has a seed, a bye or a home game")
    got = sum(1 for e in inside if e.bye)
    if got != byes:
        raise IntegrityError(f"{got} byes, not {byes}")
    homes = sum(1 for e in inside if e.host_round is not None)
    if homes != hosts:
        raise IntegrityError(f"{homes} hosts, not {hosts}")
    if any(e.bye and e.host_round is not None for e in inside):
        raise IntegrityError("a team has both a bye and a first-round home game")


def _check_run(run: Mapping[str, Any], paths: int, *, field: int, byes: int, hosts: int, label: str) -> None:
    teams = run["teams"]
    total = sum(t["field_paths"] for t in teams)
    if total != paths * field:
        raise IntegrityError(f"{label}: field places sum to {total}, not {paths} paths x {field}")
    total = sum(t["bye_paths"] for t in teams)
    if total != paths * byes:
        raise IntegrityError(f"{label}: byes sum to {total}, not {paths} paths x {byes}")
    by_seed: dict[int, int] = {}
    for team in teams:
        mine = 0
        for seed, count in team["seed_paths"].items():
            by_seed[int(seed)] = by_seed.get(int(seed), 0) + count
            mine += count
        if mine != team["field_paths"]:
            raise IntegrityError(
                f"{label}: {team['team_id']} has {mine} seeded paths but {team['field_paths']} in the field"
            )
        if team["bye_paths"] > team["field_paths"]:
            raise IntegrityError(f"{label}: {team['team_id']} has more byes than places in the field")
    for seed in range(1, field + 1):
        if by_seed.get(seed, 0) != paths:
            raise IntegrityError(
                f"{label}: seed {seed} was filled on {by_seed.get(seed, 0)} of {paths} paths"
            )
    if set(by_seed) - set(range(1, field + 1)):
        raise IntegrityError(f"{label}: a seed outside 1..{field} was given")
    total = sum(count for t in teams for count in t["host_paths"].values())
    if total != paths * hosts:
        raise IntegrityError(f"{label}: home games sum to {total}, not {paths} paths x {hosts}")


def check_section(section: Mapping[str, Any], *, field: int, byes: int, hosts: int) -> int:
    """A published field section adds up to the era's field, byes, seeds and hosts. Returns runs checked."""
    paths = section["paths"]
    runs = [section["forecast"]] if section.get("forecast") else list(section.get("scenarios") or [])
    if not runs:
        raise IntegrityError("the field section holds no forecast and no scenarios")
    for number, run in enumerate(runs, start=1):
        _check_run(
            run, paths, field=field, byes=byes, hosts=hosts, label=str(run.get("scenario") or f"run {number}")
        )
    return len(runs)
