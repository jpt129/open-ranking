"""Hand-verified lists the snapshot needs: conference title games, forfeits and games never played."""

from __future__ import annotations

import csv
from dataclasses import dataclass
from datetime import UTC, date, datetime
from pathlib import Path


class SnapshotDataError(ValueError):
    """A hand-kept list is malformed."""


@dataclass(frozen=True)
class TitleGame:
    season: int
    conference: str
    day: date
    team_a: str  # school names as the teams table prints them; empty until the pairing is known
    team_b: str
    source_url: str


@dataclass(frozen=True)
class Forfeit:
    season: int
    game_id: str
    winner_id: str
    public_utc: datetime  # when the ruling became public; a replay cut before it does not see the forfeit
    source_url: str


@dataclass(frozen=True)
class Unplayed:
    """A scheduled game that was cancelled, declared no contest, or postponed and never played."""

    season: int
    day: date
    home: str
    away: str
    status: str
    source_url: str


def _rows(path: Path | str) -> list[dict[str, str]]:
    with Path(path).open(newline="") as handle:
        return list(csv.DictReader(handle))


def _sourced(row: dict[str, str], where: str) -> str:
    if not row["source_url"].startswith("https://"):
        raise SnapshotDataError(f"{where}: no source")
    return row["source_url"]


def load_title_games(path: Path | str) -> list[TitleGame]:
    """Played or scheduled conference title games. Rows marked not_played are skipped."""
    out = []
    for row in _rows(path):
        if row["site_type"] == "not_played":
            continue
        where = f"title games: {row['season']} {row['conference']}"
        if bool(row["team_a"]) != bool(row["team_b"]):
            raise SnapshotDataError(f"{where}: one team is named and the other is not")
        out.append(
            TitleGame(
                int(row["season"]),
                row["conference"],
                date.fromisoformat(row["game_date"]),
                row["team_a"],
                row["team_b"],
                _sourced(row, where),
            )
        )
    return out


def load_forfeits(path: Path | str) -> list[Forfeit]:
    out = []
    for row in _rows(path):
        public = datetime.fromisoformat(row["public_utc"])
        if public.tzinfo is None:
            raise SnapshotDataError(f"forfeits: {row['game_id']}: public_utc needs a UTC offset")
        url = _sourced(row, f"forfeits: {row['game_id']}")
        out.append(Forfeit(int(row["season"]), row["game_id"], row["winner_id"], public.astimezone(UTC), url))
    return out


def load_unplayed(path: Path | str) -> list[Unplayed]:
    out = []
    for row in _rows(path):
        where = f"unplayed games: {row['home']} v {row['away']} {row['scheduled_date']}"
        if row["status"] not in ("cancelled", "no_contest", "postponed_never_played"):
            raise SnapshotDataError(f"{where}: unknown status {row['status']!r}")
        day = date.fromisoformat(row["scheduled_date"])
        season = day.year if day.month >= 7 else day.year - 1
        out.append(Unplayed(season, day, row["home"], row["away"], row["status"], _sourced(row, where)))
    return out
