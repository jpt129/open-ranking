"""CFP selection committee releases (P02b; DS-01, DS-02, DS-06).

Primary source: the CFP site's own rankings data, one payload per season. Each release must have exactly
25 rows, a scheduled show start from the hand-verified schedule, every team name resolved through the alias
list, and agreement with a second source. Anything else fails the ingest.

Vintage (John, 2026-11-25): "live" when we captured the release ourselves within seven days of the reveal;
"archived_authentic" when a Wayback capture taken within seven days after the reveal shows the same 25 rows;
otherwise "reconstructed".
"""

from __future__ import annotations

import csv
import gzip
import html
import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

import polars as pl

from cfp.common.timeutil import require_utc
from cfp.ingest.errors import CrossCheckFailed, MissingSource, SourceError
from cfp.ingest.http import Fetched, Fetcher
from cfp.ingest.upsert import UpsertResult, upsert
from cfp.store.lake import Lake
from cfp.store.schemas import TABLES

ET = ZoneInfo("America/New_York")
SOURCE_ID = "cfp_site:/api/v2/rankings"
SITE = "https://collegefootballplayoff.com"
ROWS = 25
WINDOW = timedelta(days=7)
WAYBACK_PAGES = ("collegefootballplayoff.com/rankings.aspx", "collegefootballplayoff.com/rankings")
MAX_CAPTURES_TRIED = 6
ESPN_COMMITTEE = "cfp"
CFBD_COMMITTEE = "Playoff Committee Rankings"


@dataclass(frozen=True)
class Release:
    season: int
    release_no: int
    day: date
    names: tuple[str, ...]  # as printed by the source, in rank order

    @property
    def release_id(self) -> str:
        return f"cfp-{self.season}-{self.release_no:02d}"


@dataclass(frozen=True)
class Reveal:
    show_start: datetime  # UTC
    basis: str
    source_url: str


@dataclass(frozen=True)
class Capture:
    taken: datetime  # UTC
    url: str
    raw_hash: str


def parse_site(payload: Any, season: int) -> list[Release]:
    """Releases of one season from the CFP site's payload, numbered by date."""
    if not isinstance(payload, list) or not payload:
        raise MissingSource(f"cfp_site: no releases in the {season} payload")
    seen: dict[date, tuple[str, ...]] = {}
    for item in payload:
        if int(item["year"]) != season:
            raise SourceError(f"cfp_site: asked for {season}, got a {item['year']} release")
        day = date.fromisoformat(str(item["releaseDate"])[:10])
        teams = sorted(item["teams"], key=lambda t: int(t["rank"]))
        ranks = [int(t["rank"]) for t in teams]
        names = tuple(" ".join(str(t["team"]).split()) for t in teams)
        if ranks != list(range(1, ROWS + 1)):
            raise SourceError(f"cfp_site: release {day} does not have ranks 1..{ROWS}: {ranks}")
        if len(set(names)) != ROWS or not all(names):
            raise SourceError(f"cfp_site: release {day} has a blank or repeated team")
        if day in seen:
            raise SourceError(f"cfp_site: two releases dated {day}")
        seen[day] = names
    return [Release(season, n, day, seen[day]) for n, day in enumerate(sorted(seen), start=1)]


def load_schedule(path: Path | str) -> dict[date, Reveal]:
    """Hand-verified show starts, keyed by the release date as the CFP site prints it.

    Columns: release_date, show_date (the day the show aired, where the site's date is wrong),
    show_start_et (HH:MM Eastern), basis, source_url.
    """
    out: dict[date, Reveal] = {}
    with Path(path).open(newline="") as handle:
        for row in csv.DictReader(handle):
            if not row["show_start_et"].strip():
                continue
            key = date.fromisoformat(row["release_date"])
            day = date.fromisoformat(row["show_date"] or row["release_date"])
            hour, minute = (int(part) for part in row["show_start_et"].split(":"))
            start = datetime(day.year, day.month, day.day, hour, minute, tzinfo=ET).astimezone(UTC)
            if key in out:
                raise SourceError(f"reveal schedule lists {key} twice")
            out[key] = Reveal(start, row["basis"], row["source_url"])
    return out


def load_aliases(path: Path | str) -> dict[str, str]:
    """Hand-verified names as printed by the CFP site -> team_id."""
    out: dict[str, str] = {}
    with Path(path).open(newline="") as handle:
        for row in csv.DictReader(handle):
            if row["alias"] in out:
                raise SourceError(f"alias list names {row['alias']!r} twice")
            out[row["alias"]] = row["team_id"]
    return out


def resolve(release: Release, aliases: Mapping[str, str]) -> list[str]:
    unknown = [name for name in release.names if name not in aliases]
    if unknown:
        raise MissingSource(
            f"{release.release_id}: no alias for {unknown}; add them to the alias list by hand"
        )
    ids = [aliases[name] for name in release.names]
    if len(set(ids)) != ROWS:
        raise SourceError(f"{release.release_id}: two names resolve to the same team")
    return ids


def parse_espn(payload: Any) -> tuple[date, list[str]] | None:
    """The committee ranking in one ESPN rankings payload: (date, team_ids in rank order), if present."""
    for ranking in payload.get("rankings", []):
        if ranking.get("type") != ESPN_COMMITTEE:
            continue
        rows = sorted(ranking["ranks"], key=lambda r: int(r["current"]))
        if [int(r["current"]) for r in rows] != list(range(1, ROWS + 1)):
            raise SourceError("espn: committee ranking does not have ranks 1..25")
        day = datetime.fromisoformat(str(ranking["date"]).replace("Z", "+00:00")).date()
        return day, [f"cfbd-{int(r['team']['id'])}" for r in rows]
    return None


def parse_cfbd(weeks: Sequence[Any]) -> list[list[str]]:
    """CFBD's committee rankings for one season, in release order (regular weeks, then postseason)."""
    order = {"regular": 0, "postseason": 1}
    out: list[list[str]] = []
    for week in sorted(weeks, key=lambda w: (order[w["seasonType"]], int(w["week"]))):
        for poll in week["polls"]:
            if poll["poll"] != CFBD_COMMITTEE:
                continue
            rows = sorted(poll["ranks"], key=lambda r: int(r["rank"]))
            if [int(r["rank"]) for r in rows] != list(range(1, ROWS + 1)):
                raise SourceError(
                    f"cfbd: committee ranking {week['season']} week {week['week']} is not 1..25"
                )
            out.append([f"cfbd-{int(r['teamId'])}" for r in rows])
    return out


def cross_check(release: Release, ids: Sequence[str], other: Sequence[str] | None, other_name: str) -> None:
    """Fail unless the second source has the same 25 teams in the same order (DS-06)."""
    if other is None:
        raise CrossCheckFailed(f"{release.release_id} ({release.day}): {other_name} has no matching release")
    diffs = [
        f"#{rank}: {name} ({mine}) vs {theirs}"
        for rank, (name, mine, theirs) in enumerate(zip(release.names, ids, other, strict=False), start=1)
        if mine != theirs
    ]
    if diffs or len(other) != len(ids):
        raise CrossCheckFailed(f"{release.release_id} ({release.day}) differs from {other_name}: {diffs[:5]}")


def decode(body: bytes) -> str:
    """Page text from archived bytes; Wayback's raw captures are often still gzip-compressed."""
    if body[:2] == b"\x1f\x8b":
        body = gzip.decompress(body)
    return body.decode("utf-8", "replace")


def page_text(page: str) -> str:
    body = re.sub(r"(?is)<(script|style)\b.*?</\1>", " ", page)
    return " ".join(html.unescape(re.sub(r"<[^>]+>", " ", body)).split())


def page_matches(page: str, names: Sequence[str]) -> bool:
    """True if the page lists the names as ranks 1..25, in order."""
    text, position = page_text(page), 0
    for rank, name in enumerate(names, start=1):
        found = re.compile(rf"(?<![\d#.-]){rank}\W{{0,3}}{re.escape(name)}(?![A-Za-z])").search(
            text, position
        )
        if found is None:
            return False
        position = found.end()
    return True


def capture_queries(release: Release) -> list[dict[str, str]]:
    """Where an authentic copy may have been archived: the dated press release, then the rankings page."""
    day = release.day
    news = f"collegefootballplayoff.com/news/{day.year}/{day.month}/{day.day}/"
    return [{"url": news, "matchType": "prefix"}, *({"url": page} for page in WAYBACK_PAGES)]


def find_capture(wayback: Fetcher, release: Release, reveal: datetime) -> Capture | None:
    """A Wayback capture within seven days after the reveal whose 25 rows match, if one exists."""
    tried = 0
    for query in capture_queries(release):
        index = wayback.get(
            "https://web.archive.org/cdx/search/cdx",
            {
                **query,
                "output": "json",
                "from": reveal.strftime("%Y%m%d"),
                "to": (reveal + WINDOW).strftime("%Y%m%d"),
                "filter": "statuscode:200",
                "collapse": "digest",
                "limit": 50,
            },
            reuse=True,
        ).json()
        for row in index[1:]:
            stamp, original = str(row[1]), str(row[2])
            taken = datetime.strptime(stamp, "%Y%m%d%H%M%S").replace(tzinfo=UTC)
            if not reveal <= taken <= reveal + WINDOW:
                continue
            if tried >= MAX_CAPTURES_TRIED:
                return None
            tried += 1
            url = f"https://web.archive.org/web/{stamp}id_/{original}"
            try:
                got = wayback.get(url, reuse=True)
            except SourceError:
                continue
            if page_matches(decode(got.body), release.names):
                return Capture(taken, url, got.raw_hash)
    return None


def vintage_for(reveal: datetime, captured_at: datetime, capture: Capture | None) -> str:
    if reveal <= captured_at <= reveal + WINDOW:
        return "live"
    if capture is not None and reveal <= capture.taken <= reveal + WINDOW:
        return "archived_authentic"
    return "reconstructed"


def release_rows(
    release: Release, ids: Sequence[str], reveal: Reveal, site: Fetched, capture: Capture | None
) -> list[dict[str, Any]]:
    start = require_utc(reveal.show_start, "show_start")
    if site.fetched_at < start:
        raise SourceError(
            f"{release.release_id}: captured before its scheduled reveal at {start.isoformat()}"
        )
    vintage = vintage_for(start, site.fetched_at, capture)
    keep = capture if vintage == "archived_authentic" else None
    return [
        {
            "release_id": release.release_id,
            "rank": rank,
            "season": release.season,
            "release_no": release.release_no,
            "reveal_utc": start,
            "team_id": team_id,
            "source_name": name,
            "archive_capture_utc": keep.taken if keep else None,
            "archive_raw_hash": keep.raw_hash if keep else None,
            "source_id": SOURCE_ID,
            "event_time": start,
            "first_public_time": start,  # the scheduled show start
            "raw_hash": site.raw_hash,
            "vintage": vintage,
        }
        for rank, (name, team_id) in enumerate(zip(release.names, ids, strict=True), start=1)
    ]


def ingest_season(
    lake: Lake,
    season: int,
    site: Fetched,
    schedule: Mapping[date, Reveal],
    aliases: Mapping[str, str],
    second: Mapping[date, Sequence[str]],
    second_name: str,
    captures: Mapping[date, Capture],
) -> UpsertResult:
    """Validate every release of a season, cross-check each one, then write. Nothing is written on failure."""
    rows: list[dict[str, Any]] = []
    for release in parse_site(site.json(), season):
        ids = resolve(release, aliases)
        if release.day not in schedule:
            raise MissingSource(
                f"{release.release_id} ({release.day}): no verified show start in the schedule"
            )
        cross_check(release, ids, second.get(release.day), second_name)
        rows += release_rows(release, ids, schedule[release.day], site, captures.get(release.day))
    spec = TABLES["committee_releases"]
    schema = {k: v for k, v in spec.schema.items() if k not in ("correction_version", "ingest_time")}
    return upsert(lake, "committee_releases", pl.DataFrame(rows, schema=schema), site.fetched_at, "observed")
