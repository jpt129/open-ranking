"""Conference title pairings for a forecast (FF-04): what was official at the cutoff, and from where.

A pairing comes, in order, from: a hand-kept row in `data/title_games.csv` with a source and a first-public
time at or before the cutoff; else the schedule in the store as of the cutoff, when exactly one game on the
title date has both teams from that conference (labelled `cfbd_schedule`, a secondary source; never for a
conference the season's rules name); else, if
`data/title_scenarios.csv` lists the possible pairings, those scenarios, each run separately and never
weighted; else the pairing is open. Nothing is guessed.

A hand row is final only on the conference's own word (John's ruling, 26 Nov 2026): its basis is
`conference_release` (the conference announced the pairing) or `conference_scenario+result` (the conference's
published clinching scenario in `source_url` and the final score that triggers it in `result_url`, with the
later of the two first-public times). A row on any other basis, such as a media tracker, settles nothing.
A scenario plus a result settles a pairing only when the conference's scenario turns on game results alone; a
branch decided by a ranking or any figure the conference computes needs the conference's announcement. That
is for the person entering the row to judge: the code cannot.

For the conferences the season's rules name, the schedule settles nothing: it is a cross-check that warns
when it disagrees with the file. A scenario list is a hypothesis, so its test is completeness: its basis is
`conference_scenarios` (the conference published them) or `two_outlets` (two independent named outlets give
the same complete set; both URLs recorded). When it is unclear whether a pairing is still possible, list it.
The code checks only that the two URLs are on different sites: it cannot tell one wire story printed twice
from two outlets, or whether the list is complete. Those are for the person entering the rows.
"""

from __future__ import annotations

import csv
import math
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Final
from urllib.parse import urlsplit

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
    listed_by: str | None = None  # for a scenario: on whose word the list of possible pairings rests


@dataclass(frozen=True)
class Pairings:
    decided: dict[str, Pairing]
    scenarios: dict[str, list[Pairing]]
    open: list[str]  # conferences with a title game and no pairing of any kind
    sha256: str  # of the files' bytes
    ignored: tuple[str, ...] = ()  # rows whose teams were not used, and why
    warnings: tuple[str, ...] = ()  # the schedule disagrees with the file for a named conference


@dataclass(frozen=True)
class Review:
    """What the files would give an issue at a cutoff, for the person entering them."""

    problems: list[str]  # why the field section would be not delivered; information only
    warnings: list[str]
    lines: list[str]
    combinations: int
    faults: list[str] = field(default_factory=list)  # what makes a file not valid; these stop a push


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
    named: Sequence[str] = (),
) -> Pairings:
    """Each conference's title pairing as known at `cutoff`. `games` is the season's schedule as of then.

    `named` are the conferences whose champion always qualifies: for them the schedule settles nothing.
    """
    body = Path(title_path).read_bytes()
    extra = Path(scenario_path).read_bytes() if scenario_path and Path(scenario_path).exists() else b""
    decided: dict[str, Pairing] = {}
    days: dict[str, date] = {}
    ignored: list[str] = []
    warnings: list[str] = []
    checks: dict[str, set[str]] = {}  # named conference -> the one game the schedule shows for its title
    label = {team_id: name for name, team_id in name_id.items()}

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
        if conference in decided and conference not in named:
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
        if conference in named:
            if len(found) == 1:
                checks[conference] = {found[0]["home_id"], found[0]["away_id"]}
            continue
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
        source, second = row["source_url"], (row.get("source_url_2") or "").strip()
        basis = (row.get("basis") or "").strip()
        names = [name.strip() for name in (row.get("outlets") or "").split(";") if name.strip()]
        if basis == "conference_scenarios":
            # true whether the conference lists pairings or only each team's conditions
            listed_by = f"possible pairings worked out from the conference's published scenarios ({source})"
            if second:  # an optional cross-check, named
                host = (urlsplit(second).hostname or "").lower().rstrip(".").removeprefix("www.")
                if not second.startswith("https://") or not host or len(names) > 1:
                    raise PairingError(f"{where}: a cross-check needs its URL and at most one outlet name")
                listed_by += f"; cross-checked against {f'{names[0]} ({host})' if names else host}"
                source = f"{source} {second}"
        elif basis == "two_outlets":
            hosts = [
                (urlsplit(url).hostname or "").lower().rstrip(".").removeprefix("www.")
                for url in (source, second)
            ]
            if not second.startswith("https://") or not all(hosts) or hosts[0] == hosts[1]:
                raise PairingError(f"{where}: a list from the press needs two outlets, each with its URL")
            who = hosts
            if (row.get("outlets") or "").strip():  # the outlets' names, when a URL is a carrier's site
                if len(names) != 2 or names[0].lower() == names[1].lower():
                    raise PairingError(f"{where}: outlets must name the two outlets, separated by ';'")
                who = [f"{name} ({host})" for name, host in zip(names, hosts, strict=True)]
            listed_by = (
                f"possible pairings per {who[0]} and {who[1]}; not published by the "
                f"{row['conference'].strip()}"
            )
            source = f"{source} {second}"
        else:
            raise PairingError(f"{where}: basis must be conference_scenarios or two_outlets, not {basis!r}")
        if any((p.listed_by, p.source_url) != (listed_by, source) for p in scenarios.get(conference, [])):
            raise PairingError(f"{where}: a conference's scenarios must share one basis and one source")
        scenarios.setdefault(conference, []).append(
            Pairing(
                conference,
                days[conference],
                team(row["team_a"], where),
                team(row["team_b"], where),
                "scenario",
                source,
                public,
                row["scenario"].strip(),
                listed_by,
            )
        )
    still = sorted(c for c in days if c not in decided and c not in scenarios)
    # For a named conference the schedule settles nothing; it is only compared with what the file gives.
    for conference, shown in sorted(checks.items()):
        a, b = sorted(label.get(team_id, team_id) for team_id in shown)
        if conference in decided:
            mine = decided[conference]
            if shown != {mine.team_a, mine.team_b}:
                warnings.append(
                    f"{conference}: the schedule in the store shows {a} v {b}, not the file's pairing; "
                    "the file stands"
                )
        elif conference in scenarios:
            if all(shown != {p.team_a, p.team_b} for p in scenarios[conference]):
                warnings.append(
                    f"{conference}: the schedule in the store shows {a} v {b}, which is not among the "
                    "listed scenarios; the scenarios stand"
                )
        else:
            warnings.append(
                f"{conference}: the schedule in the store shows {a} v {b}; the file has no pairing, and "
                "the schedule settles nothing for this conference"
            )
    digest = sha256_hex(body + b"\n--\n" + extra)
    return Pairings(decided, scenarios, still, digest, tuple(ignored), tuple(warnings))


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
    files = [("title games", title_path)]
    if scenario_path and Path(scenario_path).exists():
        files.append(("title scenarios", scenario_path))
    faults: list[str] = []
    for label, path in files:  # the shape of each file, before anything reads it
        raw = Path(path).read_bytes()
        if raw.startswith(b"\xef\xbb\xbf"):
            faults.append(f"{label}: {Path(path).name} starts with a byte-order mark")
        table = list(csv.reader(raw.decode("utf-8-sig").splitlines()))
        for number, cells in enumerate(table[1:], start=2):
            if len(cells) != len(table[0]):
                faults.append(
                    f"{label}: {Path(path).name} line {number} has {len(cells)} fields; "
                    f"the header has {len(table[0])}"
                )
    try:
        found = resolve_pairings(
            title_path, scenario_path, season, cutoff, name_id, games, conference_of, named
        )
    except Exception as error:  # whatever stops the issue's own read is the finding
        text = f"{type(error).__name__}: {error}"
        return Review([f"the files cannot be read as written; {lost}"], [], [], 0, [*faults, text])
    problems: list[str] = []
    warnings: list[str] = []
    lines: list[str] = []
    name = {team: label for label, team in name_id.items()}

    def placed(pair: Pairing, what: str) -> None:
        for team in (pair.team_a, pair.team_b):
            if conference_of.get(team) != pair.conference:
                faults.append(f"{what}: {name.get(team, team)} is not a {pair.conference} team")

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
    warnings.extend(found.warnings)
    for conference, pair in sorted(found.decided.items()):
        if " " in pair.source_url and pair.basis == "official":
            warnings.append(
                f"{conference}: settled by a scenario plus a result. That holds only if the conference's "
                "scenario turns on game results alone; a branch decided by a ranking needs its announcement"
            )
    for conference, options in sorted(found.scenarios.items()):
        lines.append(f"{conference}: {options[0].listed_by}")
    for note in found.ignored:
        (problems if note.split(":")[0] in named else warnings).append(note)
    combinations = math.prod(len(options) for options in found.scenarios.values())
    if combinations > MAX_SCENARIOS:
        problems.append(f"{combinations} scenario combinations; the limit is {MAX_SCENARIOS}; {lost}")
    for label, path in files:
        for row in csv.DictReader(Path(path).read_text().splitlines()):
            if int(row["season"]) != season or not (row["team_a"] and row["team_b"]):
                continue
            where = f"{label}: {row['conference']} {row.get('scenario') or ''}".strip()
            public = _time(row.get("first_public_utc") or "", where)
            if public is None:
                faults.append(f"{where}: teams are named with no first-public time; the row is ignored")
            elif public > cutoff:
                problems.append(f"{where}: first public {public.isoformat()} is after the cutoff; ignored")
    if faults:
        problems.append(f"a file is not valid; {lost}")
    return Review(problems, warnings, lines, combinations, faults)
