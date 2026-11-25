"""Ingest jobs behind `cfp ingest ...`: fetch, verify, write."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path

import polars as pl

from cfp.ingest import cfbd_normalize as norm
from cfp.ingest import cfp_releases as rel
from cfp.ingest.cfbd import Cfbd
from cfp.ingest.errors import CrossCheckFailed
from cfp.ingest.http import Budget, Fetcher, TokenBucket
from cfp.ingest.upsert import CorrectionPublic, UpsertResult, upsert
from cfp.store.lake import Lake

# A plain client name; no contact details are sent to third parties.
AGENT = {"User-Agent": "Mozilla/5.0 (compatible; research-client)", "Accept": "*/*"}
ESPN = "https://site.api.espn.com/apis/site/v2/sports/football/college-football"
ESPN_REGULAR_WEEKS = range(8, 17)
UNMETERED = 100_000
LIVE_SEASON = 2026
# Calls per season: games (regular, postseason), rankings; reference payloads; lines (regular, postseason).
CALLS = {"games": 2, "rankings": 1, "reference": 3, "lines": 2}


@dataclass
class SeasonReport:
    results: list[UpsertResult] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)


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


def ingest_releases(lake: Lake, season: int, data_dir: Path, cfbd: Cfbd | None = None) -> UpsertResult:
    """Fetch one season's releases, cross-check each one, look for archived copies, write.

    John, 2026-11-25: 2014-25 are checked against CFBD, the live season against a second source (ESPN).
    There is no way to choose a weaker check.
    """
    schedule = rel.load_schedule(data_dir / "cfp_reveals.csv")
    aliases = rel.load_aliases(data_dir / "aliases_cfp_site.csv")
    site = public_fetcher(lake, "cfp_site", rel.SITE).get("/api/v2/rankings", {"year": season})
    releases = rel.parse_site(site.json(), season)
    if season >= LIVE_SEASON:
        second, other = "espn", espn_committee(public_fetcher(lake, "espn", ESPN), season)
    elif cfbd is not None:
        second, other = "cfbd", cfbd_committee(cfbd, season, releases)
    else:
        raise ValueError(f"{season}: releases before {LIVE_SEASON} need the CFBD cross-check")
    wayback = public_fetcher(lake, "wayback", "https://web.archive.org", rate=0.5)
    captures: dict[date, rel.Capture] = {}
    for release in releases:
        reveal = schedule.get(release.day)
        if reveal is None or rel.vintage_for(reveal.show_start, site.fetched_at, None) == "live":
            continue  # a missing time fails in ingest_season; our own timely capture needs no archive
        found = rel.find_capture(wayback, release, reveal.show_start)
        if found is not None:
            captures[release.day] = found
    return rel.ingest_season(lake, season, site, schedule, aliases, other, second, captures)


def ingest_cfbd_season(lake: Lake, cfbd: Cfbd, season: int, what: Sequence[str]) -> SeasonReport:
    """One season from CFBD. `what` is any of games, rankings, reference, lines.

    In the live season a change to a row we already hold becomes public at the moment the payload showing
    it was fetched. Past seasons are fetched once and carry rule-based times.
    """
    live = season == LIVE_SEASON
    reuse = not live  # finished seasons are fetched once; the raw payload is the record
    how: CorrectionPublic = "observed" if live else "asserted"
    report = SeasonReport()
    if "reference" in what:  # archived raw for P03 (identity, membership); not normalized here
        cfbd.teams(season, reuse=reuse)
        cfbd.conferences(reuse=reuse)
        cfbd.calendar(season, reuse=reuse)
    if "games" in what:
        frames, seen_at = [], []
        for season_type in norm.SEASON_TYPES:
            got = cfbd.games(season, season_type, reuse=reuse)
            rows, left_out = norm.game_rows(got, live)
            frames.append(rows)
            seen_at.append(got.fetched_at)
            if left_out:
                report.notes.append(
                    f"{season} {season_type}: {len(left_out)} games left out (unplayed or no score)"
                )
        games = pl.concat(frames)  # one upsert: a game listed in both payloads fails loudly
        held = lake.scan("games").filter(pl.col("season") == season)
        latest = pl.col("correction_version") == pl.col("correction_version").max().over("game_id")
        finals = held.filter(latest & (pl.col("status") == "final")).collect()["game_id"].to_list()
        reverted = games.filter((pl.col("status") == "scheduled") & pl.col("game_id").is_in(finals))
        if reverted.height:  # never un-finalise a game on the source's say-so; a person records a correction
            report.notes.append(f"{season}: source no longer marks as final: {reverted['game_id'].to_list()}")
            games = games.filter(~pl.col("game_id").is_in(reverted["game_id"].to_list()))
        report.results.append(upsert(lake, "games", games, max(seen_at), how))
    if "rankings" in what:
        regular = lake.scan("games").filter(
            (pl.col("season") == season) & (pl.col("season_type") == "regular")
        )
        kickoffs = regular.select("week", "start_utc").unique().collect().rows()
        got = cfbd.rankings(season, "regular", reuse=reuse)
        report.results.append(upsert(lake, "polls", norm.poll_rows(got, kickoffs, live), got.fetched_at, how))
    if "lines" in what:
        for season_type in norm.SEASON_TYPES:
            got = cfbd.lines(season, season_type, reuse=reuse)
            report.results.append(upsert(lake, "lines", norm.line_rows(got, live), got.fetched_at, how))
    return report
