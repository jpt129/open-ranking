"""Season-versioned bracket rules (BR-2014..BR-2027, BR-SCHED, BR-CONTRACT).

Inputs: a rank order, official eligibility, conference champions, the season's rules and any extra committee
ordering. Outputs, for every team it was told about: qualifier, bid route, seed, bye, host round and reason.

The rules for each era are data in `seasons/*.yaml`. Rank, eligibility and seed are three different things:
a team's rank is its place in the order it was given; whether it is in the field and where it is seeded
follow from the season's rules.

The engine never guesses. A named conference with no champion, or unranked automatic qualifiers with no
committee ordering between them, is an error.
"""

from __future__ import annotations

from collections.abc import Collection, Mapping, Sequence
from dataclasses import dataclass
from functools import cache
from pathlib import Path
from typing import Any, Final

import yaml

SEASONS_DIR: Final = Path(__file__).parent / "seasons"


class RulesError(ValueError):
    """The field cannot be decided from these inputs."""


@dataclass(frozen=True)
class Guarantee:
    team_id: str
    name: str
    top: int  # in if ranked at or above this place


@dataclass(frozen=True)
class SeasonRules:
    first_season: int
    last_season: int | None
    field_size: int
    champion_count: int  # highest-ranked champions that qualify from any conference (2024, 2025)
    named: tuple[str, ...]  # conferences whose champion always qualifies
    group: tuple[str, ...]  # conferences that share one place
    group_of: str  # the place goes to the group's highest-ranked "champion" or "team"
    guarantee: Guarantee | None
    seeding: str  # "rank", or "champions_first" (2024: the four best champions are seeds 1-4)
    byes: tuple[int, ...]
    hosts: tuple[tuple[int, tuple[int, ...]], ...]  # (round, seeds that host it)
    at_large_route: str
    schedule_standard: int | None
    source: str
    qualifying_games: tuple[tuple[str, str], ...] = ()  # which games count toward the standard, by group
    fcs_wins_given_weight: int | None = None
    unpublished: tuple[str, ...] = ()  # rules the CFP has not published; a season freeze waits on these
    sources: tuple[str, ...] = ()


@dataclass(frozen=True)
class Entry:
    team_id: str
    rank: int | None  # place in the order given; None if outside it
    qualifier: bool
    route: str | None  # auto:<conference>, auto:group, guarantee, at_large, top_four
    seed: int | None
    bye: bool
    host_round: int | None
    reason: str
    waiver: bool = False
    below_schedule_standard: bool = False


_KEYS: Final = frozenset(
    {
        "seasons",
        "field_size",
        "auto",
        "at_large_route",
        "seeding",
        "byes",
        "hosts",
        "guarantee",
        "schedule_standard",
        "qualifying_games",
        "fcs_wins_given_weight",
        "source",
        "source_also",
        "unpublished",
    }
)


def _parse(doc: Mapping[str, Any]) -> SeasonRules:
    unknown = sorted(set(doc) - _KEYS)
    if unknown:
        raise RulesError(f"unknown key in a season file: {unknown[0]}")
    count, named, group, group_of = 0, (), (), "champion"
    for item in doc["auto"]:
        kind = item["kind"]
        if kind == "highest_ranked_champions":
            count = int(item["count"])
        elif kind == "named_champions":
            named = tuple(item["conferences"])
        elif kind == "group_place":
            group, group_of = tuple(item["conferences"]), str(item["of"])
        else:
            raise RulesError(f"unknown automatic bid kind {kind!r}")
    if group_of not in ("champion", "team"):
        raise RulesError(f"unknown group place rule {group_of!r}")
    if doc["seeding"] not in ("rank", "champions_first"):
        raise RulesError(f"unknown seeding {doc['seeding']!r}")
    promise = doc.get("guarantee")
    return SeasonRules(
        int(doc["seasons"]["first"]),
        None if doc["seasons"]["last"] is None else int(doc["seasons"]["last"]),
        int(doc["field_size"]),
        count,
        named,
        group,
        group_of,
        Guarantee(promise["team_id"], promise["name"], int(promise["top"])) if promise else None,
        doc["seeding"],
        tuple(doc["byes"]),
        tuple(sorted((int(rnd), tuple(seeds)) for rnd, seeds in doc["hosts"].items())),
        doc.get("at_large_route", "at_large"),
        doc.get("schedule_standard"),
        doc["source"],
        tuple(sorted((str(k), str(v)) for k, v in (doc.get("qualifying_games") or {}).items())),
        doc.get("fcs_wins_given_weight"),
        tuple(doc.get("unpublished") or ()),
        (doc["source"], *([doc["source_also"]] if doc.get("source_also") else [])),
    )


@cache
def _all_rules() -> tuple[SeasonRules, ...]:
    return tuple(_parse(yaml.safe_load(path.read_text())) for path in sorted(SEASONS_DIR.glob("*.yaml")))


def load_rules(season: int) -> SeasonRules:
    """The rules in force for `season`."""
    for rules in _all_rules():
        if rules.first_season <= season and (rules.last_season is None or season <= rules.last_season):
            return rules
    raise RulesError(f"no rules are on file for {season}")


def select_field(
    rules: SeasonRules,
    order: Sequence[str],
    champions: Mapping[str, str],
    *,
    eligible: Mapping[str, bool] | None = None,
    conference_of: Mapping[str, str] | None = None,
    extra_order: Sequence[str] = (),
    waivers: Collection[str] = (),
    qualifying_games: Mapping[str, int] | None = None,
) -> list[Entry]:
    """Apply the season's rules.

    `order` is the rank order, best first. `champions` maps a conference to its champion. `eligible` marks
    teams the CFP has ruled out (missing means eligible); a team in `waivers` is eligible by waiver.
    `conference_of` gives each team's conference; it is needed when a place goes to a group's highest-ranked
    team rather than its champion. `extra_order` is the committee's ordering of teams outside `order`, used
    only for automatic qualifiers. `qualifying_games` is each team's count toward the scheduling standard:
    it is reported, never applied.
    """
    if len(set(order)) != len(order):
        raise RulesError("a team appears twice in the order")
    if len(set(extra_order)) != len(extra_order):
        raise RulesError("a team appears twice in the extra ordering")
    rank = {team: place for place, team in enumerate(order, start=1)}
    both = sorted(set(extra_order) & set(rank))
    if both:
        raise RulesError(f"{both[0]} is both ranked and in the extra ordering")
    extra = {team: place for place, team in enumerate(extra_order, start=1)}
    waived = set(waivers)
    excused = {team for team in waived if eligible is not None and not eligible.get(team, True)}

    def allowed(team: str) -> bool:
        return team in waived or eligible is None or eligible.get(team, True)

    def standing(team: str) -> tuple[int, int]:
        """Sort key: ranked teams by rank, then extra-ordered teams; raises for a team with neither."""
        if team in rank:
            return (0, rank[team])
        if team in extra:
            return (1, extra[team])
        raise RulesError(f"{team} is outside the order and needs extra committee ordering")

    def best(candidates: Sequence[str], count: int, what: str) -> list[str]:
        """The `count` highest-standing candidates.

        Ranked teams come first, then teams in the extra ordering. A candidate with neither is below both;
        if such teams would have to be told apart to fill the places, that is an error.
        """
        placed = sorted((t for t in candidates if t in rank or t in extra), key=standing)
        if len(placed) >= count:
            return placed[:count]
        unplaced = sorted(t for t in candidates if t not in rank and t not in extra)
        if len(unplaced) > count - len(placed):
            raise RulesError(f"{what}: {', '.join(unplaced)} need extra committee ordering")
        return [*placed, *unplaced]

    holders: dict[str, str] = {}
    for conference, team in sorted(champions.items()):
        if team in holders:
            raise RulesError(f"{team} is given as champion of two conferences: {holders[team]}, {conference}")
        holders[team] = conference
    routes: dict[str, str] = {}
    for conference in rules.named:
        if conference not in champions:
            raise RulesError(f"no champion is given for {conference}")
        team = champions[conference]
        if not allowed(team):  # no source says where that place would go
            raise RulesError(f"the {conference} champion {team} is not eligible; the rules do not cover this")
        routes[team] = f"auto:{conference}"
    if rules.group:
        if rules.group_of == "team":
            if conference_of is None:
                raise RulesError("the group place goes to its highest-ranked team: conference_of is needed")
            known = [*order, *extra_order]
            lost = sorted(team for team in known if team not in conference_of)
            if lost:
                raise RulesError(f"no conference is given for {lost[0]}")
            candidates = [t for t in known if conference_of[t] in rules.group and allowed(t)]
            # a champion outside both orders can still be the group's best when no member is placed
            candidates += [
                champions[c] for c in sorted(rules.group) if c in champions and champions[c] not in candidates
            ]
            candidates = [t for t in candidates if allowed(t) and t not in routes]
        else:
            candidates = [
                champions[c] for c in sorted(rules.group) if c in champions and allowed(champions[c])
            ]
        if not candidates:
            raise RulesError("no team is given for the group place")
        if not any(team in rank or team in extra for team in candidates):
            # the committee identifies this team itself; one known champion is not enough to name it
            raise RulesError("the group place: no candidate is ranked; it needs extra committee ordering")
        for team in best(candidates, 1, "the group place"):
            routes[team] = "auto:group"
    if rules.champion_count:
        candidates = sorted(team for team in holders if allowed(team))
        if len(candidates) < rules.champion_count:
            raise RulesError(
                f"{rules.champion_count} champions qualify; only {len(candidates)} eligible ones are given"
            )
        for team in best(candidates, rules.champion_count, "the champions' places"):
            routes[team] = f"auto:{holders[team]}"

    places = rules.field_size - len(routes)
    if places < 0:
        raise RulesError("more automatic qualifiers than places")
    pool = [team for team in order if team not in routes and allowed(team)]
    at_large = pool[:places]
    if len(at_large) < places:
        raise RulesError(f"the order is too short: {places} at-large places, {len(at_large)} eligible teams")
    displaced: str | None = None
    promise = rules.guarantee
    if promise and promise.team_id in rank and rank[promise.team_id] <= promise.top:
        team = promise.team_id
        if team not in routes and team not in at_large and allowed(team):
            if not at_large:
                raise RulesError("no at-large place is left for the guaranteed team")
            displaced = at_large.pop()
            routes[team] = "guarantee"
    for team in at_large:
        routes[team] = rules.at_large_route

    unplaced = sorted(team for team in routes if team not in rank and team not in extra)
    if len(unplaced) > 1 or (unplaced and any(team in extra for team in routes)):
        raise RulesError(f"seeding: {', '.join(unplaced)} need extra committee ordering")

    def seed_key(team: str) -> tuple[int, int]:
        return standing(team) if team in rank or team in extra else (2, 0)

    seeded = sorted(routes, key=seed_key)
    if rules.seeding == "champions_first":
        first = [team for team in seeded if routes[team].startswith("auto:")][: len(rules.byes)]
        seeded = [*first, *(team for team in seeded if team not in first)]
    seed = {team: place for place, team in enumerate(seeded, start=1)}
    host = {s: rnd for rnd, seeds in rules.hosts for s in seeds if rnd == 1}
    host |= {s: rnd for rnd, seeds in rules.hosts for s in seeds if rnd != 1 and s not in host}

    last_in = max((rank[t] for t in at_large), default=None)
    out: list[Entry] = []
    for team in sorted(set(order) | set(champions.values()) | set(extra_order)):
        notes: list[str] = []
        if team in routes:
            route = routes[team]
            if route.startswith("auto:"):
                notes.append(f"automatic place ({route[5:]})")
            elif route == "guarantee":
                notes.append(f"guaranteed a place when ranked in the top {promise.top if promise else ''}")
            elif route == "top_four":
                notes.append("ranked in the top four")
            else:
                notes.append("at-large place by rank")
            if team in excused:
                notes.append("eligible by waiver")
        elif not allowed(team):
            notes.append("not eligible")
        elif team == displaced:
            notes.append(
                f"last at-large place went to {promise.name} ({promise.team_id}) under its guarantee"
                if promise
                else "displaced"
            )
        elif team in rank and rules.at_large_route == "top_four":
            notes.append(f"ranked {rank[team]}, outside the top four")
        elif team in rank:
            notes.append(
                f"ranked {rank[team]}, below the last at-large place"
                + (f" (rank {last_in})" if last_in is not None else "")
            )
        else:
            notes.append("outside the order and no automatic place")
        games = (qualifying_games or {}).get(team)
        short = rules.schedule_standard is not None and games is not None and games < rules.schedule_standard
        if games is not None and rules.schedule_standard is not None:
            notes.append(
                f"{games} qualifying games against a standard of {rules.schedule_standard} (not applied)"
            )
        place = seed.get(team)
        out.append(
            Entry(
                team,
                rank.get(team),
                team in routes,
                routes.get(team),
                place,
                place in rules.byes if place is not None else False,
                host.get(place) if place is not None else None,
                "; ".join(notes),
                team in excused and team in routes,
                short,
            )
        )
    big = len(out) + rules.field_size + 1
    return sorted(out, key=lambda e: (e.seed or big, e.rank or big, e.team_id))
