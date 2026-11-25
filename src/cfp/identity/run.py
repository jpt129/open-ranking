"""`cfp identity build`: rebuild teams, aliases and membership from archived payloads. No metered calls."""

from __future__ import annotations

import json
from collections.abc import Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from cfp.identity import build
from cfp.ingest.cfbd import Cfbd
from cfp.ingest.cfbd_normalize import SEASON_TYPES
from cfp.ingest.cfp_releases import load_aliases
from cfp.ingest.errors import MissingSource
from cfp.ingest.http import Fetched
from cfp.ingest.upsert import UpsertResult, upsert
from cfp.store.lake import Lake


def archived_games(cfbd: Cfbd, season: int) -> list[Fetched]:
    """The season's archived /games payloads. A season that was never fetched is a missing source."""
    out = []
    for season_type in SEASON_TYPES:
        public_url = cfbd.fetcher.public_url("/games", {"year": season, "seasonType": season_type})
        got = cfbd.fetcher.lookup(public_url)
        if got is None:
            raise MissingSource(
                f"cfbd: no archived {season_type} games for {season}; run the season ingest first"
            )
        out.append(got)
    return out


def espn_teams(payload: Any) -> dict[int, tuple[str, str, str]]:
    """ESPN's team ids, each with the location, display name and short name ESPN prints."""
    items = payload["sports"][0]["leagues"][0]["teams"]
    return {
        int(i["team"]["id"]): (
            i["team"]["location"],
            i["team"]["displayName"],
            i["team"].get("shortDisplayName") or "",
        )
        for i in items
    }


@dataclass
class IdentityReport:
    results: list[UpsertResult] = field(default_factory=list)
    unconfirmed_espn: list[str] = field(default_factory=list)


def build_identity(
    lake: Lake, cfbd: Cfbd, data_dir: Path, seasons: Sequence[int], espn: Fetched
) -> IdentityReport:
    """Check everything first, then write teams, aliases and membership."""
    groups = build.load_groups(data_dir / "conference_groups.csv")
    counts = build.load_counts(data_dir / "fbs_counts.csv")
    site_file = data_dir / "aliases_cfp_site.csv"
    site_aliases = load_aliases(site_file)
    overrides = build.load_overrides(data_dir / "team_name_overrides.csv")
    hand = build.load_espn_matches(data_dir / "espn_id_matches.csv")
    by_season: dict[int, dict[str, build.SeasonTeam]] = {}
    sources: dict[int, Fetched] = {}
    for season in seasons:
        payloads = archived_games(cfbd, season)
        found = build.season_teams([json.loads(got.body) for got in payloads])
        by_season[season] = build.renamed(found, overrides)
        sources[season] = payloads[0]
    build.check_counts(by_season, counts)
    moving_file = data_dir / "transitioning.csv"
    moving = build.check_classification(by_season, groups, build.load_transitions(moving_file))
    moving_origin = build.Origin("data:transitioning.csv", lake.put_raw(moving_file.read_bytes()))
    group_sources = build.load_group_sources(data_dir / "conference_groups.csv")
    confirmed, unconfirmed = build.espn_matches(by_season, espn_teams(espn.json()), hand)
    membership = [
        build.membership_rows(s, by_season[s], groups, sources[s], group_sources, moving, moving_origin)
        for s in sorted(by_season)
    ]
    origins = {
        "cfp_site": build.Origin("data:aliases_cfp_site.csv", lake.put_raw(site_file.read_bytes())),
        "espn": build.Origin("espn:/teams", espn.raw_hash),
    }
    frames = {
        "teams": build.team_rows(by_season, sources, confirmed),
        "team_aliases": build.alias_rows(by_season, sources, site_aliases, confirmed, origins),
        "eligibility": build.eligibility_rows(by_season, moving, moving_origin),
    }
    now = max([espn.fetched_at, *(got.fetched_at for got in sources.values())])
    report = IdentityReport(unconfirmed_espn=unconfirmed)
    report.results = [upsert(lake, table, frame, now, "asserted") for table, frame in frames.items()]
    report.results += [upsert(lake, "membership", frame, now, "asserted") for frame in membership]
    return report
