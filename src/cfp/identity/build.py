"""Team identity and dated conference membership (P03), built from archived CFBD game payloads.

Every game row names each side's school, classification and conference as of that season, so the registry
needs no further calls. A team's classification and conference must be the same in every game of a season;
anything else stops the build.
"""

from __future__ import annotations

import csv
import re
import unicodedata
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any

import polars as pl

from cfp.ingest.errors import CrossCheckFailed, MissingSource, SourceError
from cfp.ingest.http import Fetched
from cfp.store.schemas import TABLES

DIVISIONS = ("fbs", "fcs", "ii", "iii")
UNKNOWN = "unknown"
INDEPENDENTS = "FBS Independents"
GROUPS = ("power", "non_power", "independent")
PROVIDED = ("correction_version", "ingest_time")


class IdentityError(SourceError):
    """The sources disagree about who a team is or where it belongs."""


@dataclass(frozen=True)
class SeasonTeam:
    team_id: str
    name: str
    division: str  # fbs, fcs, ii, iii or unknown
    conference: str | None  # as CFBD prints it


def conference_id(name: str | None) -> str | None:
    """A stable slug: "Mid-American" -> "mid-american", "FBS Independents" -> "fbs-independents"."""
    if not name:
        return None
    plain = unicodedata.normalize("NFKD", name).encode("ascii", "ignore").decode()
    return re.sub(r"[^a-z0-9]+", "-", plain.lower()).strip("-")


def season_start(season: int) -> date:
    return date(season, 8, 1)


def season_public(season: int) -> datetime:
    """Membership for a season is treated as public on 20 Aug: after conference moves are settled (and after
    the August 2020 opt-outs), before the first game of any season."""
    return datetime(season, 8, 20, 4, 0, tzinfo=UTC)


def season_teams(payloads: Sequence[Any]) -> dict[str, SeasonTeam]:
    """Every team in one season's /games payloads, with the one classification and conference it has."""
    seen: dict[str, set[tuple[str, str, str | None]]] = {}
    for payload in payloads:
        for game in payload:
            for side in ("home", "away"):
                team_id = f"cfbd-{int(game[f'{side}Id'])}"
                division = game.get(f"{side}Classification") or UNKNOWN
                if division not in (*DIVISIONS, UNKNOWN):
                    raise IdentityError(f"{team_id}: unexpected classification {division!r}")
                name = " ".join(str(game[f"{side}Team"]).split())
                seen.setdefault(team_id, set()).add((name, division, game.get(f"{side}Conference") or None))
    out: dict[str, SeasonTeam] = {}
    for team_id, facts in seen.items():
        if len(facts) != 1:
            raise IdentityError(
                f"{team_id} changes name, classification or conference within a season: {facts}"
            )
        name, division, conference = next(iter(facts))
        out[team_id] = SeasonTeam(team_id, name, division, conference)
    return out


def load_overrides(path: Path | str) -> dict[str, str]:
    """Hand-kept team_id -> name, for the rare case where CFBD prints one name for two teams."""
    with Path(path).open(newline="") as handle:
        rows = list(csv.DictReader(handle))
    if any(not row["reason"].strip() for row in rows):
        raise SourceError("team name overrides: every row needs a reason")
    return {row["team_id"]: row["name"] for row in rows}


def renamed(teams: Mapping[str, SeasonTeam], overrides: Mapping[str, str]) -> dict[str, SeasonTeam]:
    return {
        team_id: SeasonTeam(team_id, overrides.get(team_id, team.name), team.division, team.conference)
        for team_id, team in teams.items()
    }


def load_groups(path: Path | str) -> dict[tuple[int, str], str]:
    """Hand-kept (season, conference) -> power | non_power | independent, each row with a source."""
    out: dict[tuple[int, str], str] = {}
    with Path(path).open(newline="") as handle:
        for row in csv.DictReader(handle):
            key = (int(row["season"]), row["conference"])
            if row["group"] not in GROUPS:
                raise SourceError(f"conference groups: {key} has group {row['group']!r}")
            if not row["source_url"].startswith("https://"):
                raise SourceError(f"conference groups: {key} has no source")
            if key in out:
                raise SourceError(f"conference groups: {key} listed twice")
            out[key] = row["group"]
    return out


def load_group_sources(path: Path | str) -> dict[tuple[int, str], str]:
    """(season, conference) -> the source for that conference's standing as an FBS conference that season."""
    with Path(path).open(newline="") as handle:
        return {(int(row["season"]), row["conference"]): row["source_url"] for row in csv.DictReader(handle)}


@dataclass(frozen=True)
class Transition:
    """One sourced team-season of a program moving between FCS and FBS."""

    season: int
    school: str
    ncaa_status: str
    cfp_eligible: bool
    waiver: bool
    source_url: str


def load_transitions(path: Path | str) -> list[Transition]:
    out: list[Transition] = []
    with Path(path).open(newline="") as handle:
        for row in csv.DictReader(handle):
            where = f"transitioning: {row['school']} {row['season']}"
            if row["cfp_eligible"] not in ("yes", "no", "waiver"):
                raise SourceError(f"{where}: cfp_eligible must be yes, no or waiver")
            if not row["source_url"].startswith("https://"):
                raise SourceError(f"{where}: no source")
            if not row["ncaa_status"].startswith(("transition year", "full FBS member")):
                raise SourceError(f"{where}: unknown NCAA status {row['ncaa_status']!r}")
            out.append(
                Transition(
                    int(row["season"]),
                    row["school"],
                    row["ncaa_status"],
                    row["cfp_eligible"] != "no",
                    row["cfp_eligible"] == "waiver",
                    row["source_url"],
                )
            )
    return out


def check_classification(
    by_season: Mapping[int, Mapping[str, SeasonTeam]],
    groups: Mapping[tuple[int, str], str],
    transitions: Sequence[Transition],
) -> dict[tuple[int, str], Transition]:
    """Apply the classification rule and stop if CFBD disagrees with it (John's ruling, 2026-11-25).

    A team is FBS in a season if it is an NCAA FBS member that season, including a reclassifying member in
    any transition year, and is a football member of an FBS conference or an FBS independent. The sourced
    conference list says which conferences are FBS; the sourced transition table says who is reclassifying.
    Returns the transition rows keyed by (season, team_id).
    """
    keyed: dict[tuple[int, str], Transition] = {}
    for row in transitions:
        teams = by_season.get(row.season)
        if teams is None:
            continue
        match = [team for team in teams.values() if team.name == row.school]
        if len(match) != 1:
            raise IdentityError(f"transitioning: {row.school!r} matches {len(match)} teams in {row.season}")
        keyed[(row.season, match[0].team_id)] = row
    for season, teams in sorted(by_season.items()):
        for team in teams.values():
            in_fbs_conference = team.conference is not None and (season, team.conference) in groups
            if (team.division == "fbs") != in_fbs_conference:
                where = f"{season}: CFBD classes {team.name} as {team.division} in {team.conference!r}"
                rule = "a team is FBS exactly when it plays in an FBS conference or as an FBS independent"
                raise IdentityError(f"{where}; {rule}")
    return keyed


def load_counts(path: Path | str) -> dict[int, int]:
    """Hand-kept count of FBS teams that played each season (in 2020 three members sat out)."""
    with Path(path).open(newline="") as handle:
        return {int(row["season"]): int(row["played"]) for row in csv.DictReader(handle) if row["played"]}


def check_counts(by_season: Mapping[int, Mapping[str, SeasonTeam]], counts: Mapping[int, int]) -> None:
    """The FBS count CFBD implies must equal the sourced count for every season that has one."""
    for season, teams in sorted(by_season.items()):
        ours = sum(team.division == "fbs" for team in teams.values())
        if season not in counts:
            raise MissingSource(f"{season}: no sourced FBS team count")
        if ours != counts[season]:
            raise CrossCheckFailed(
                f"{season}: CFBD implies {ours} FBS teams, the sourced count is {counts[season]}"
            )


def _frame(table: str, rows: list[dict[str, Any]]) -> pl.DataFrame:
    schema = {k: v for k, v in TABLES[table].schema.items() if k not in PROVIDED}
    return pl.DataFrame(rows, schema=schema)


@dataclass(frozen=True)
class Origin:
    """Where a derived row came from: a source label and the hash of the archived payload or data file."""

    source_id: str
    raw_hash: str


def _provenance(origin: Origin | Fetched, season: int) -> dict[str, Any]:
    public = season_public(season)
    return {
        "source_id": origin.source_id if isinstance(origin, Origin) else "cfbd:/games",
        "event_time": public,
        "first_public_time": public,
        "raw_hash": origin.raw_hash,
        "vintage": "reconstructed",
    }


def espn_matches(
    by_season: Mapping[int, Mapping[str, SeasonTeam]],
    espn: Mapping[int, Sequence[str]],
    hand: Mapping[str, str],
) -> tuple[dict[str, Sequence[str]], list[str]]:
    """Teams whose CFBD number is also ESPN's id for the same school, and the pairs left unconfirmed.

    A shared number is accepted when ESPN prints the CFBD name (as its location or short name, or at the
    start of its display name), or when the pair is on the hand-checked list. An FBS team must be confirmed.
    """
    latest: dict[str, SeasonTeam] = {}
    ever_fbs: set[str] = set()
    for season in sorted(by_season):
        for team in by_season[season].values():
            latest[team.team_id] = team
            if team.division == "fbs":
                ever_fbs.add(team.team_id)
    matched: dict[str, Sequence[str]] = {}
    unconfirmed: list[str] = []
    for team_id, team in sorted(latest.items()):
        names = espn.get(int(team_id.removeprefix("cfbd-")))
        location, display, short = names if names else ("", "", "")
        same = names is not None and (
            team.name in (location, short) or display.startswith(team.name) or hand.get(team_id) == location
        )
        if same:
            matched[team_id] = (location, display)
        elif names is not None:
            unconfirmed.append(f"{team_id}: CFBD {team.name!r}, ESPN {location!r}")
        if not same and team_id in ever_fbs:
            raise IdentityError(
                f"{team_id} ({team.name}) is FBS but ESPN does not confirm the same id: {names}"
            )
    return matched, unconfirmed


def load_espn_matches(path: Path | str) -> dict[str, str]:
    """Hand-checked team_id -> ESPN location, for schools the two sources spell differently."""
    with Path(path).open(newline="") as handle:
        return {row["team_id"]: row["espn_location"] for row in csv.DictReader(handle)}


def membership_rows(
    season: int,
    teams: Mapping[str, SeasonTeam],
    groups: Mapping[tuple[int, str], str],
    got: Fetched,
    group_sources: Mapping[tuple[int, str], str] | None = None,
    transitions: Mapping[tuple[int, str], Transition] | None = None,
    transition_origin: Origin | None = None,
) -> pl.DataFrame:
    """One row per team for the season. An FBS row names the source that makes the team-season FBS."""
    rows: list[dict[str, Any]] = []
    for team in sorted(teams.values(), key=lambda t: t.team_id):
        group = url = None
        origin: Origin | Fetched = got
        if team.division == "fbs":
            if team.conference is None:
                raise IdentityError(f"{season}: FBS team {team.name} ({team.team_id}) has no conference")
            group = groups.get((season, team.conference))
            if group is None:
                raise MissingSource(f"{season}: no sourced CFP group for conference {team.conference!r}")
            url = (group_sources or {}).get((season, team.conference))
            moving = (transitions or {}).get((season, team.team_id))
            if moving is not None and transition_origin is not None:
                url, origin = moving.source_url, transition_origin
        rows.append(
            {
                "team_id": team.team_id,
                "valid_from": season_start(season),
                "valid_to": date(season + 1, 7, 31),
                "conference_id": conference_id(team.conference),
                "division": team.division,
                "cfp_group": group,
                "source_url": url,
            }
            | _provenance(origin, season)
        )
    return _frame("membership", rows)


def eligibility_rows(
    by_season: Mapping[int, Mapping[str, SeasonTeam]],
    transitions: Mapping[tuple[int, str], Transition],
    origin: Origin,
) -> pl.DataFrame:
    """Bid eligibility for the sourced transition team-seasons that are FBS. A team-season with no row is an
    established FBS member with no restriction."""
    rows = [
        {
            "season": season,
            "team_id": team_id,
            "standard_met": None,
            "waiver": row.waiver,
            "cfp_eligible": row.cfp_eligible,
            "ncaa_status": row.ncaa_status,
            "source_url": row.source_url,
        }
        | _provenance(origin, season)
        for (season, team_id), row in sorted(transitions.items())
        if by_season[season][team_id].division == "fbs"
    ]
    return _frame("eligibility", rows)


def team_rows(
    by_season: Mapping[int, Mapping[str, SeasonTeam]],
    sources: Mapping[int, Fetched],
    espn_confirmed: Mapping[str, Sequence[str]],
) -> pl.DataFrame:
    """One row per team: its most recent name, and its ESPN id where ESPN confirms the same school."""
    first: dict[str, int] = {}
    last: dict[str, int] = {}
    for season in sorted(by_season):
        for team_id in by_season[season]:
            first.setdefault(team_id, season)
            last[team_id] = season
    rows = []
    for team_id in sorted(first):
        number = int(team_id.removeprefix("cfbd-"))
        rows.append(
            {
                "team_id": team_id,
                "name": by_season[last[team_id]][team_id].name,
                "cfbd_id": number,
                "espn_id": number if team_id in espn_confirmed else None,
                "kalshi_code": None,
            }
            | _provenance(sources[last[team_id]], first[team_id])
        )
    return _frame("teams", rows)


def alias_rows(
    by_season: Mapping[int, Mapping[str, SeasonTeam]],
    sources: Mapping[int, Fetched],
    site_aliases: Mapping[str, str],
    espn_names: Mapping[str, Sequence[str]],
    origins: Mapping[str, Origin],
) -> pl.DataFrame:
    """Names by source. A name that points at two teams within one source stops the build."""
    found: dict[tuple[str, str], tuple[str, int]] = {}

    def add(source: str, alias: str, team_id: str, season: int) -> None:
        held = found.setdefault((source, alias), (team_id, season))
        if held[0] != team_id:
            raise IdentityError(f"{source}: the name {alias!r} points at both {held[0]} and {team_id}")

    known: dict[str, int] = {}
    for season in sorted(by_season):
        for team in by_season[season].values():
            add("cfbd", team.name, team.team_id, season)
            known.setdefault(team.team_id, season)
    for alias, team_id in site_aliases.items():
        if team_id not in known:
            raise IdentityError(f"cfp_site: alias {alias!r} points at {team_id}, which is in no game payload")
        add("cfp_site", alias, team_id, known[team_id])
    # ESPN prints some names for more than one school; such a name is left out, so resolving it fails.
    owners: dict[str, set[str]] = {}
    for team_id, names in espn_names.items():
        for name in names:
            owners.setdefault(name, set()).add(team_id)
    for name, ids in owners.items():
        if len(ids) == 1:
            team_id = next(iter(ids))
            add("espn", name, team_id, known[team_id])
    rows = [
        {"source": source, "alias": alias, "team_id": team_id}
        | _provenance(origins[source] if source in origins else sources[season], season)
        for (source, alias), (team_id, season) in sorted(found.items())
    ]
    return _frame("team_aliases", rows)
