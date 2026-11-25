"""The committee's designated team from the six-conference group (BR-2026).

In 2026 and 2027 one place in the field goes to the highest-ranked team from a named group of conferences.
When none of them is in the committee's 25, the committee names that team itself. The name is not in the
rankings feed, so it is kept by hand in `data/committee_designations.csv`: one row per release, each with its
source, the sentence relied on, and the time it became public. A row not yet public at an issue's cutoff does
not exist for that issue.
"""

from __future__ import annotations

import csv
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import date, datetime
from pathlib import Path

from cfp.common.hashing import sha256_hex


class DesignationError(ValueError):
    """The designations file cannot be used."""


@dataclass(frozen=True)
class Designation:
    season: int
    release_date: date
    team_id: str
    basis: str
    source_url: str
    first_public: datetime
    quote: str


@dataclass(frozen=True)
class Designations:
    rows: tuple[Designation, ...]
    sha256: str  # of the file's bytes


def load_designations(path: Path | str) -> Designations:
    body = Path(path).read_bytes()
    rows: list[Designation] = []
    seen: set[tuple[int, date]] = set()
    for number, row in enumerate(csv.DictReader(body.decode().splitlines()), start=2):
        where = f"{path} line {number}"
        if not row["source_url"].startswith("https://") or not row["basis"].strip():
            raise DesignationError(f"{where}: a row needs a basis and an https source")
        try:
            public = datetime.fromisoformat(row["first_public_utc"])
        except ValueError as error:
            raise DesignationError(f"{where}: first_public_utc is not a time") from error
        offset = public.utcoffset()
        if offset is None or offset.total_seconds() != 0:
            raise DesignationError(f"{where}: first_public_utc must be in UTC")
        key = (int(row["season"]), date.fromisoformat(row["release_date"]))
        if key in seen:
            raise DesignationError(f"{where}: release {key[1]} is listed twice")
        seen.add(key)
        if not row["team_id"].strip():
            raise DesignationError(f"{where}: no team_id")
        rows.append(
            Designation(
                key[0], key[1], row["team_id"].strip(), row["basis"], row["source_url"], public, row["quote"]
            )
        )
    return Designations(tuple(rows), sha256_hex(body))


def designated_for(
    found: Designations, season: int, release_date: date, cutoff: datetime
) -> Designation | None:
    """The designation made with one release, if it was public by `cutoff`."""
    for row in found.rows:
        if (row.season, row.release_date) == (season, release_date) and row.first_public <= cutoff:
            return row
    return None


def needs_designation(prior: Sequence[str], conference_of: Mapping[str, str], group: Sequence[str]) -> bool:
    """True when a group place exists and no team from the group is in the committee's list."""
    return bool(group) and not any(conference_of.get(team) in group for team in prior)
