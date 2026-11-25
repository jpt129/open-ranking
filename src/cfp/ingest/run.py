"""Ingest jobs behind `cfp ingest ...`: fetch, verify, write."""

from __future__ import annotations

from collections.abc import Sequence
from datetime import date
from pathlib import Path

import polars as pl

from cfp.common.timeutil import utc_now
from cfp.ingest import cfbd_normalize as norm
from cfp.ingest import cfp_releases as rel
from cfp.ingest.cfbd import Cfbd
from cfp.ingest.errors import CrossCheckFailed
from cfp.ingest.http import Budget, Fetcher, TokenBucket
from cfp.ingest.upsert import UpsertResult, upsert
from cfp.store.lake import Lake

# A plain client name; no contact details are sent to third parties.
AGENT = {"User-Agent": "Mozilla/5.0 (compatible; research-client)", "Accept": "*/*"}
ESPN = "https://site.api.espn.com/apis/site/v2/sports/football/college-football"
ESPN_REGULAR_WEEKS = range(8, 17)
UNMETERED = 100_000


def public_fetcher(lake: Lake, source: str, base_url: str, rate: float = 1.0) -> Fetcher:
    return Fetcher(
        lake,
        source,
        base_url,
        budget=Budget(lake.root / "budget.json"),
        allowance=UNMETERED,
        bucket=TokenBucket(rate, 1.0),
        headers=AGENT,
        attempts=3,
    )


def espn_committee(espn: Fetcher, season: int) -> dict[date, list[str]]:
    """ESPN's copy of each committee release in a season, by date."""
    out: dict[date, list[str]] = {}
    queries = [{"seasons": season, "types": 2, "weeks": week} for week in ESPN_REGULAR_WEEKS]
    queries.append({"seasons": season, "types": 3, "weeks": 1})
    for query in queries:
        parsed = rel.parse_espn(espn.get("/rankings", query).json())
        if parsed is not None:
            out[parsed[0]] = parsed[1]
    return out


def cfbd_committee(cfbd: Cfbd, season: int, releases: Sequence[rel.Release]) -> dict[date, list[str]]:
    """CFBD's committee rankings matched to releases by order. The counts must agree."""
    weeks = [*cfbd.rankings(season, "regular", reuse=True).json()]
    weeks += cfbd.rankings(season, "postseason", reuse=True).json()
    lists = rel.parse_cfbd(weeks)
    if len(lists) != len(releases):
        raise CrossCheckFailed(f"{season}: CFP site has {len(releases)} releases, CFBD has {len(lists)}")
    return {release.day: ids for release, ids in zip(releases, lists, strict=True)}


def ingest_releases(
    lake: Lake, season: int, data_dir: Path, second: str, cfbd: Cfbd | None = None
) -> UpsertResult:
    """Fetch one season's releases, cross-check each against `second`, look for archived copies, write."""
    schedule = rel.load_schedule(data_dir / "cfp_reveals.csv")
    aliases = rel.load_aliases(data_dir / "aliases_cfp_site.csv")
    site = public_fetcher(lake, "cfp_site", rel.SITE).get("/api/v2/rankings", {"year": season})
    releases = rel.parse_site(site.json(), season)
    if second == "espn":
        other = espn_committee(public_fetcher(lake, "espn", ESPN), season)
    elif second == "cfbd" and cfbd is not None:
        other = cfbd_committee(cfbd, season, releases)
    else:
        raise ValueError(f"unknown second source {second!r}")
    wayback = public_fetcher(lake, "wayback", "https://web.archive.org", rate=0.5)
    captures: dict[date, rel.Capture] = {}
    now = utc_now()
    for release in releases:
        reveal = schedule.get(release.day)
        if reveal is None or rel.vintage_for(reveal.show_start, now, None) == "live":
            continue  # a missing time fails in ingest_season; our own timely capture needs no archive
        found = rel.find_capture(wayback, release, reveal.show_start)
        if found is not None:
            captures[release.day] = found
    return rel.ingest_season(lake, season, site, schedule, aliases, other, second, captures)


LIVE_SEASON = 2026
# Calls per season: games (regular, postseason), rankings; reference payloads; lines (regular, postseason).
CALLS = {"games": 2, "rankings": 1, "reference": 3, "lines": 2}


def ingest_cfbd_season(lake: Lake, cfbd: Cfbd, season: int, what: Sequence[str]) -> list[UpsertResult]:
    """One season from CFBD. `what` is any of games, rankings, reference, lines.

    The live season is vintage "live": a result first seen for a game we already held becomes public at the
    moment we saw it. Everything else, including the first catch-up of games already played, carries the
    rule-based time; earlier seasons are "reconstructed".
    """
    live = season >= LIVE_SEASON
    vintage = "live" if live else "reconstructed"
    reuse = not live  # finished seasons are fetched once; the raw payload is the record
    results: list[UpsertResult] = []
    now = utc_now()
    if "reference" in what:  # archived raw for P03 (identity, membership); not normalized here
        cfbd.teams(season, reuse=reuse)
        cfbd.conferences(reuse=reuse)
        cfbd.calendar(season, reuse=reuse)
    if "games" in what:
        held = set(lake.scan("games").filter(pl.col("season") == season).collect()["game_id"].to_list())
        for season_type in norm.SEASON_TYPES:
            scheduled, final = norm.game_rows(cfbd.games(season, season_type, reuse=reuse), vintage)
            seen_before = pl.col("game_id").is_in(sorted(held))
            # a game we already hold that is now final gets only its final row, or it would flip back
            finished = pl.col("game_id").is_in(final["game_id"].to_list())
            pending = scheduled.filter(~(seen_before & finished))
            results.append(upsert(lake, "games", pending, now, "observed" if live else "asserted"))
            results.append(upsert(lake, "games", final.filter(~seen_before), now, "asserted"))
            results.append(
                upsert(lake, "games", final.filter(seen_before), now, "observed" if live else "asserted")
            )
    if "rankings" in what:
        games = lake.scan("games").filter((pl.col("season") == season) & (pl.col("season_type") == "regular"))
        kickoffs = games.select("week", "start_utc").unique().collect().rows()
        polls = norm.poll_rows(cfbd.rankings(season, "regular", reuse=reuse), kickoffs, vintage)
        results.append(upsert(lake, "polls", polls, now, "observed" if live else "asserted"))
    if "lines" in what:
        for season_type in norm.SEASON_TYPES:
            lines = norm.line_rows(cfbd.lines(season, season_type, reuse=reuse), vintage)
            results.append(upsert(lake, "lines", lines, now, "observed" if live else "asserted"))
    return results
