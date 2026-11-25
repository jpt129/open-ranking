"""Conference title pairings for a forecast (FF-04): what was official at the cutoff, and from where.

A pairing comes, in order, from: a hand-kept row in `data/title_games.csv` with a source and a first-public
time at or before the cutoff; else the schedule in the store as of the cutoff, when exactly one game on the
title date has both teams from that conference (labelled `cfbd_schedule`, a secondary source); else, if
`data/title_scenarios.csv` lists the possible pairings, those scenarios, each run separately and never
weighted; else the pairing is open. Nothing is guessed.
"""

from __future__ import annotations

import csv
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from pathlib import Path

import polars as pl

from cfp.common.hashing import sha256_hex


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

    def team(name: str, where: str) -> str:
        if name not in name_id:
            raise PairingError(f"{where}: no team is named {name!r}")
        return name_id[name]

    for row in csv.DictReader(body.decode().splitlines()):
        if int(row["season"]) != season or row["site_type"] == "not_played":
            continue
        conference = conference_id(row["conference"])
        where = f"title games: {season} {row['conference']}"
        days[conference] = date.fromisoformat(row["game_date"])
        public = _time(row.get("first_public_utc") or "", where)
        if row["team_a"] and row["team_b"] and public is not None and public <= cutoff:
            if not row["source_url"].startswith("https://"):
                raise PairingError(f"{where}: no source")
            decided[conference] = Pairing(
                conference,
                days[conference],
                team(row["team_a"], where),
                team(row["team_b"], where),
                "official",
                row["source_url"],
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
    return Pairings(decided, scenarios, still, sha256_hex(body + b"\n--\n" + extra))
