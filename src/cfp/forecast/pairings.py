"""Conference title pairings for a forecast (FF-04): what was official at the cutoff, and from where.

A pairing comes, in order, from: a hand-kept row in `data/title_games.csv` with a source and a first-public
time at or before the cutoff; else the schedule in the store as of the cutoff, when exactly one game on the
title date has both teams from that conference (labelled `cfbd_schedule`, a secondary source); else, if
`data/title_scenarios.csv` lists the possible pairings, those scenarios, each run separately and never
weighted; else the pairing is open. Nothing is guessed.

A hand row is final only on the conference's own word (John's ruling, 26 Nov 2026): its basis is
`conference_release` (the conference announced the pairing) or `conference_scenario+result` (the conference's
published clinching scenario in `source_url` and the final score that triggers it in `result_url`, with the
later of the two first-public times). A row on any other basis, such as a media tracker, settles nothing.
"""

from __future__ import annotations

import csv
import math
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Final

import polars as pl

from cfp.common.hashing import sha256_hex

ANNOUNCED: Final = "conference_release"
TRIGGERED: Final = "conference_scenario+result"
# The issuing run checks the files out up to two hours before the cutoff; pairings are entered by then.
PAIRINGS_LEAD: Final = timedelta(hours=2, minutes=15)
MAX_SCENARIOS: Final = 8
OPEN_GROUP_LIMIT: Final = 0.05


class PairingError(ValueError):
    """A pairings file cannot be used."""


@dataclass(frozen=True)
class Pairing:
    conference: str  # conference id, e.g. "big-ten"
    day: date
    team_a: str  # team ids
    team_b: str
    basis: str  # "official" (hand row), "cfbd_schedule" or "scenario"
    source_url: str
    first_public: datetime | None
    scenario: str | None = None


@dataclass(frozen=True)
class Pairings:
    decided: dict[str, Pairing]
    scenarios: dict[str, list[Pairing]]
    open: list[str]  # conferences with a title game and no pairing of any kind
    sha256: str  # of the files' bytes
    ignored: tuple[str, ...] = ()  # rows whose teams were not used, and why


@dataclass(frozen=True)
class Review:
    """What the files would give an issue at a cutoff, for the person entering them."""

    problems: list[str]  # each would cost the issue its field section, or a row its effect
    warnings: list[str]
    lines: list[str]
    combinations: int


def conference_id(label: str) -> str:
    return label.strip().lower().replace(" ", "-")


def _time(text: str, where: str) -> datetime | None:
    if not text.strip():
        return None
    try:
        when = datetime.fromisoformat(text)
    except ValueError as error:
        raise PairingError(f"{where}: first_public_utc is not a time") from error
    offset = when.utcoffset()
    if offset is None or offset.total_seconds() != 0:
        raise PairingError(f"{where}: first_public_utc must be in UTC")
    return when


def resolve_pairings(
    title_path: Path | str,
    scenario_path: Path | str | None,
    season: int,
    cutoff: datetime,
    name_id: Mapping[str, str],
    games: pl.DataFrame,
    conference_of: Mapping[str, str],
) -> Pairings:
    """Each conference's title pairing as known at `cutoff`. `games` is the season's schedule as of then."""
    body = Path(title_path).read_bytes()
    extra = Path(scenario_path).read_bytes() if scenario_path and Path(scenario_path).exists() else b""
    decided: dict[str, Pairing] = {}
    days: dict[str, date] = {}
    ignored: list[str] = []

    def team(name: str, where: str) -> str:
        if name not in name_id:
            raise PairingError(f"{where}: no team is named {name!r}")
        return name_id[name]

    for row in csv.DictReader(body.decode().splitlines()):
        if int(row["season"]) != season or row["site_type"] == "not_played":
            continue
        conference = conference_id(row["conference"])
        where = f"title games: {season} {row['conference']}"
        if conference in days:
            raise PairingError(f"{where}: the conference is listed twice")
        days[conference] = date.fromisoformat(row["game_date"])
        public = _time(row.get("first_public_utc") or "", where)
        if row["team_a"] and row["team_b"] and public is not None and public <= cutoff:
            if not row["source_url"].startswith("https://"):
                raise PairingError(f"{where}: no source")
            source = row["source_url"]
            if row["basis"] == TRIGGERED:
                result = (row.get("result_url") or "").strip()
                if not result.startswith("https://"):
                    raise PairingError(f"{where}: a pairing settled by a result needs its result_url")
                source = f"{source} {result}"
            elif row["basis"] != ANNOUNCED:
                ignored.append(
                    f"{conference}: basis {row['basis']!r} is not the conference's own word; its teams are "
                    "not used"
                )
                continue
            decided[conference] = Pairing(
                conference,
                days[conference],
                team(row["team_a"], where),
                team(row["team_b"], where),
                "official",
                source,
                public,
            )
    for conference, day in sorted(days.items()):
        if conference in decided:
            continue
        near = games.filter(
            (pl.col("start_utc").dt.date() >= day - timedelta(days=1))
            & (pl.col("start_utc").dt.date() <= day + timedelta(days=1))
        )
        found = [
            row
            for row in near.sort("game_id").iter_rows(named=True)
            if conference_of.get(row["home_id"]) == conference
            and conference_of.get(row["away_id"]) == conference
        ]
        if len(found) == 1:
            decided[conference] = Pairing(
                conference,
                day,
                found[0]["home_id"],
                found[0]["away_id"],
                "cfbd_schedule",
                "cfbd:/games",
                None,
            )
    scenarios: dict[str, list[Pairing]] = {}
    for row in csv.DictReader(extra.decode().splitlines()) if extra else []:
        if int(row["season"]) != season:
            continue
        conference = conference_id(row["conference"])
        where = f"title scenarios: {season} {row['conference']} {row['scenario']}"
        public = _time(row["first_public_utc"], where)
        if conference in decided or conference not in days or public is None or public > cutoff:
            continue
        if not row["source_url"].startswith("https://") or not row["scenario"].strip():
            raise PairingError(f"{where}: a scenario needs a label and a source")
        pair = {team(row["team_a"], where), team(row["team_b"], where)}
        if any({p.team_a, p.team_b} == pair for p in scenarios.get(conference, [])):
            raise PairingError(f"{where}: the same pairing is listed twice")
        scenarios.setdefault(conference, []).append(
            Pairing(
                conference,
                days[conference],
                team(row["team_a"], where),
                team(row["team_b"], where),
                "scenario",
                row["source_url"],
                public,
                row["scenario"].strip(),
            )
        )
    still = sorted(c for c in days if c not in decided and c not in scenarios)
    return Pairings(decided, scenarios, still, sha256_hex(body + b"\n--\n" + extra), tuple(ignored))


def review_pairings(
    title_path: Path | str,
    scenario_path: Path | str | None,
    season: int,
    cutoff: datetime,
    name_id: Mapping[str, str],
    conference_of: Mapping[str, str],
    *,
    games: pl.DataFrame,
    named: Sequence[str],
    group_leagues: Sequence[str],
) -> Review:
    """Read the two files as an issue at `cutoff` would and say what it would do with them. Writes nothing."""
    lost = "the field section would be not delivered"
    try:
        found = resolve_pairings(title_path, scenario_path, season, cutoff, name_id, games, conference_of)
    except Exception as error:  # whatever stops the issue's own read is the finding
        return Review([f"{type(error).__name__}: {error}; {lost}"], [], [], 0)
    problems: list[str] = []
    warnings: list[str] = []
    lines: list[str] = []
    name = {team: label for label, team in name_id.items()}

    def placed(pair: Pairing, what: str) -> None:
        for team in (pair.team_a, pair.team_b):
            if conference_of.get(team) != pair.conference:
                problems.append(f"{what}: {name.get(team, team)} is not a {pair.conference} team; {lost}")

    for conference, pair in sorted(found.decided.items()):
        placed(pair, f"{conference} pairing")
        lines.append(f"{conference}: {pair.team_a} v {pair.team_b} ({pair.basis}; {pair.source_url})")
    for conference, options in sorted(found.scenarios.items()):
        for pair in options:
            placed(pair, f"{conference} scenario {pair.scenario!r}")
            lines.append(f"{conference}: scenario {pair.scenario!r}: {pair.team_a} v {pair.team_b}")
    for conference in found.open:
        lines.append(f"{conference}: open")
    for conference in named:
        if conference in found.open:
            problems.append(f"{conference}: no pairing and no scenarios on file; {lost}")
    for conference in found.open:
        if conference in group_leagues:
            warnings.append(
                f"{conference}: open. THIS CHECK CANNOT TELL: if its teams take the other conferences' place "
                f"in more than {OPEN_GROUP_LIMIT:.0%} of paths, {lost}; enter its pairing or scenarios"
            )
    for note in found.ignored:
        (problems if note.split(":")[0] in named else warnings).append(note)
    combinations = math.prod(len(options) for options in found.scenarios.values())
    if combinations > MAX_SCENARIOS:
        problems.append(f"{combinations} scenario combinations; the limit is {MAX_SCENARIOS}; {lost}")
    files = [("title games", title_path)]
    if scenario_path and Path(scenario_path).exists():
        files.append(("title scenarios", scenario_path))
    for label, path in files:
        for row in csv.DictReader(Path(path).read_text().splitlines()):
            if int(row["season"]) != season or not (row["team_a"] and row["team_b"]):
                continue
            where = f"{label}: {row['conference']} {row.get('scenario') or ''}".strip()
            public = _time(row.get("first_public_utc") or "", where)
            if public is None:
                problems.append(f"{where}: teams are named with no first-public time; the row is ignored")
            elif public > cutoff:
                problems.append(f"{where}: first public {public.isoformat()} is after the cutoff; ignored")
    return Review(problems, warnings, lines, combinations)
