"""The Committee Gap report for one release: Open Ranking against forecast against the committee's list.

Both the Open Ranking edition and the forecast edition were frozen before the reveal; the release is read
from the store separately. The report is written once by `cfp gap`; a correction is a new numbered report.
"""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Final

import polars as pl

from cfp.forecast.observations import fbs_field
from cfp.gap.core import aggregate, consequences, reasons, team_rows
from cfp.ingest.cfp_releases import load_schedule
from cfp.open_ranking.release import PRODUCT as OPEN_PRODUCT
from cfp.release.edition import canonical
from cfp.release.history import past_champions
from cfp.release.issue import PRODUCT as FORECAST_PRODUCT
from cfp.rules.engine import load_rules
from cfp.scoring.scorecard import ScoreRefused, not_prospective, release_rows
from cfp.store.lake import Lake
from cfp.store.types import Mode

SCHEMA: Final = 1
NOTES: Final = (
    "Lift is Open Ranking rank minus committee rank. Positive means the committee ranked the team higher.",
    "Anticipated is the part of the lift the forecast's median already expected. Beyond forecast is how many "
    "places above that median the committee put the team.",
    "A team the committee left out is 26th or lower, so its lift is shown as a bound.",
    "Reasons are given only where a bid, a bye or a home game differs. They quote the Open Ranking ledger; "
    "no inference about the committee's thinking is added.",
    "Decisive games are each team's three largest ledger rows by size. That is a display rule.",
    "Bid eligibility is the store's eligibility table: eligible unless a sourced row says not.",
)
REVISION: Final = re.compile(r"-e(\d+)$")


class GapRefused(ValueError):
    """The report cannot be built from what is in the store."""


@dataclass(frozen=True)
class Inputs:
    season: int
    release_id: str
    release_no: int
    releases: int  # releases scheduled this season: the last one is Selection Day
    reveal: datetime
    actual: Sequence[str]
    open_edition: tuple[Mapping[str, Any], str]  # document, sha256
    forecast_edition: tuple[Mapping[str, Any], str] | None
    members: Mapping[str, str]
    names: Mapping[str, str]
    champions: Mapping[str, str]
    remarks: Sequence[Mapping[str, Any]]
    mode: str = "live"
    eligible: Mapping[str, bool] | None = None  # the store's eligibility table; None in a hand-built test
    passed_over: Sequence[str] = ()  # later editions not used, with the reason


@dataclass(frozen=True)
class Gap:
    gap_id: str
    doc: dict[str, Any]
    body: bytes
    sha256: str


def _read(root: Path, row: Mapping[str, Any]) -> dict[str, Any]:
    path = root / row["edition_id"] / "edition.json"
    if not path.is_file():
        raise GapRefused(f"{row['edition_id']} is recorded but its file is missing")
    body = path.read_bytes()
    if hashlib.sha256(body).hexdigest() != row["sha256"]:
        raise GapRefused(f"{row['edition_id']}: the file's hash is not the hash recorded at issue")
    return json.loads(body)  # type: ignore[no-any-return]


def _newest_first(frame: pl.DataFrame) -> list[dict[str, Any]]:
    """Rows by cutoff and then revision number, newest first (e10 is after e2)."""

    def key(row: Mapping[str, Any]) -> tuple[Any, int, str]:
        found = REVISION.search(row["edition_id"])
        return (row["issue_utc"], int(found.group(1)) if found else 0, row["edition_id"])

    return sorted(frame.iter_rows(named=True), key=key, reverse=True)


def load_inputs(lake: Lake, data: Path, release_id: str, *, now: datetime, mode: Mode) -> Inputs:
    """Everything the report reads. Refuses without the release or an earlier Open Ranking edition."""
    releases = lake.as_of("committee_releases", now, mode).frame
    try:
        season, number, reveal, actual = release_rows(releases, release_id)
    except ScoreRefused as error:
        raise GapRefused(str(error)) from error
    if now < reveal:
        raise GapRefused(f"{release_id} is revealed at {reveal.isoformat()}: no gap before then")
    scheduled = sum(1 for day in load_schedule(data / "cfp_reveals.csv") if day.year == season)
    held = lake.as_of("editions", now, mode, season=season).frame
    # live: frozen before the announcement. replay: rebuilt later from data as of a cutoff before it.
    before = held.filter(pl.col("issue_utc") < reveal)
    if mode == "live":
        before = before.filter(pl.col("first_public_time") < reveal)
    root = lake.root / "editions"
    ranking = before.filter(pl.col("product") == OPEN_PRODUCT)
    if mode == "live":
        ranking = ranking.filter((pl.col("vintage") == "live") & (pl.col("ingest_time") < reveal))
    passed: list[str] = []
    open_edition = None
    for row in _newest_first(ranking):
        doc = _read(root, row)
        # a correction keeps its cutoff but may have read data later: that is not frozen before the reveal
        if not datetime.fromisoformat(doc["data_as_of_utc"]) < reveal:
            passed.append(f"{row['edition_id']}: its data was read after the reveal")
            continue
        open_edition = (doc, row["sha256"])
        break
    if open_edition is None:
        raise GapRefused(f"no Open Ranking edition was issued before {release_id} was revealed")
    forecast = None
    stem = f"scw-{season}-r{number:02d}-"
    every = held.filter((pl.col("product") == FORECAST_PRODUCT) & pl.col("edition_id").str.starts_with(stem))
    for row in _newest_first(every):
        doc = _read(root, row)
        why = not_prospective(doc, row, reveal) if mode == "live" else []
        if not row["issue_utc"] < reveal:
            why.append("its cutoff is not before the reveal")
        if doc.get("target_release_no") != number or doc.get("reveal_utc") != reveal.isoformat():
            why.append("it was issued for a different reveal")
        if why:
            passed.append(f"{row['edition_id']}: {'; '.join(dict.fromkeys(why))}")
            continue
        forecast = (doc, row["sha256"])
        break
    day = reveal.date()
    everyone = lake.as_of("membership", now, mode).frame
    flags = fbs_field(everyone, lake.as_of("eligibility", now, mode).frame, season, day)
    eligible = {str(team): bool(flag) for team, flag in flags.iter_rows()}
    membership = everyone.filter(
        (pl.col("valid_from") <= day) & (pl.col("valid_to").is_null() | (pl.col("valid_to") >= day))
    )
    members = dict(membership.select("team_id", "conference_id").drop_nulls().iter_rows())
    names = dict(lake.as_of("teams", now, mode).frame.select("team_id", "name").iter_rows())
    champions: dict[str, str] = {}
    if number == scheduled:
        try:
            found, _, problems = past_champions(lake, data, [season], now)
        except OSError as error:
            raise GapRefused(
                f"Selection Day flags need every champion; the title games cannot be read: {error}"
            ) from error
        if problems:
            raise GapRefused("Selection Day flags need every champion: " + "; ".join(problems))
        champions = found[season]
    remarks = lake.as_of("chair_remarks", now, mode, season=season).frame
    said = [
        {"url": r["url"], "published_utc": r["published_utc"].isoformat()}
        for r in remarks.filter(pl.col("release_id") == release_id)
        .sort("published_utc")
        .iter_rows(named=True)
    ]
    return Inputs(
        season,
        release_id,
        number,
        scheduled,
        reveal,
        actual,
        open_edition,
        forecast,
        members,
        names,
        champions,
        said,
        mode,
        eligible,
        passed,
    )


def build_gap(inputs: Inputs, *, revision: int = 1, code_hash: str) -> Gap:
    """The report document. Reads nothing and writes nothing."""
    if revision < 1:
        raise GapRefused("a revision is 1 or more")
    ranking, ranking_sha = inputs.open_edition
    teams = {team["team_id"]: team for team in ranking["teams"]}
    order = [team["team_id"] for team in sorted(ranking["teams"], key=lambda team: team["order"])]
    open_ranks = {team: int(teams[team]["open_rank"]) for team in order}
    forecast: dict[str, dict[str, Any]] = {}
    eligible: dict[str, bool] = dict(inputs.eligible or {})
    said = None
    if inputs.forecast_edition is not None:
        doc, sha = inputs.forecast_edition
        paths = (doc.get("rank_noise") or {}).get("paths")
        for row in doc["forecasts"]["baseline2"]["rows"]:
            if inputs.eligible is None:
                eligible[row["team_id"]] = bool(row.get("cfp_eligible", True))
            forecast[row["team_id"]] = {
                "median": row.get("median_rank"),
                "rank_counts": row.get("rank_counts") if paths else None,
                "paths": paths,
            }
        said = {"edition_id": doc["edition_id"], "sha256": sha}
    try:
        rows = team_rows(open_ranks, forecast, list(inputs.actual))
        effects = consequences(
            load_rules(inputs.season),
            order,
            list(inputs.actual),
            members=inputs.members,
            eligible=eligible,
            champions=inputs.champions,
            final=inputs.release_no == inputs.releases,
        )
    except ValueError as error:
        raise GapRefused(str(error)) from error
    for row in rows:
        row["name"] = inputs.names.get(row["team_id"], row["team_id"])
    explained = []
    seen: set[tuple[str, str]] = set()
    for flag in effects["flags"]:
        flag["name"] = inputs.names.get(flag["team_id"], flag["team_id"])
        other = next(
            (
                f["team_id"]
                for f in effects["flags"]
                if f["change"] == flag["change"]
                and f["open"] != flag["open"]
                and f["team_id"] != flag["team_id"]
            ),
            None,
        )
        if other is None or (flag["team_id"], other) in seen or (other, flag["team_id"]) in seen:
            continue
        seen.add((flag["team_id"], other))
        explained.append(reasons(flag["team_id"], other, teams, inputs.names, remarks=inputs.remarks))
    stem = f"gap-{inputs.season}-r{inputs.release_no:02d}-" + ("" if inputs.mode == "live" else "replay-")
    gap_id = f"{stem}e{revision}"
    document = {
        "schema": SCHEMA,
        "gap_id": gap_id,
        "product": "committee_gap",
        "supersedes": f"{stem}e{revision - 1}" if revision > 1 else None,
        "season": inputs.season,
        "release_id": inputs.release_id,
        "release_no": inputs.release_no,
        "mode": inputs.mode,
        "reference_only": inputs.mode != "live",
        "reveal_utc": inputs.reveal.isoformat(),
        "open_edition": {
            "edition_id": ranking["edition_id"],
            "sha256": ranking_sha,
            "cutoff_utc": ranking.get("cutoff_utc"),
        },
        "editions_passed_over": list(inputs.passed_over),
        "forecast_edition": said,
        "forecast_note": None if said else "no forecast edition was issued before this reveal",
        "teams": rows,
        "consequences": effects,
        "reasons": explained,
        "aggregation": aggregate(rows, inputs.members),
        "code_hash": code_hash,
        "notes": list(NOTES),
    }
    body = canonical(document)
    return Gap(gap_id, document, body, hashlib.sha256(body).hexdigest())
