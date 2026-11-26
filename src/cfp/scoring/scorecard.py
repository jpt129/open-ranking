"""The scorecard for one committee release: every edition issued for that reveal, scored (VT-11, VT-13).

Nothing here changes an edition. A scorecard is written once; a correction is a new numbered scorecard.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Final

import polars as pl

from cfp.release.edition import canonical
from cfp.release.issue import PRODUCT
from cfp.rules.engine import RulesError, load_rules
from cfp.scoring.integrity import IntegrityError, check_section
from cfp.scoring.weekly import RANKED, cumulative_from_counts, score_weekly, top25_scores
from cfp.store.lake import Lake
from cfp.store.types import Mode

SCHEMA: Final = 1
LABELS: Final = {"baseline1": "AP as issued", "baseline2": "prior CFP update"}
NOTES: Final = (
    "Lower is better. A perfect forecast scores 0.",
    "The fitted model was not issued this season, so the comparison is between the two baselines.",
    "The calibrated column is scored on P(top 25) alone, beside the raw column on the same teams. It is "
    "not part of the weekly rank score, which needs every cutoff from 1 to 25.",
    "A replay edition is scored for reference and is never counted as a prospective forecast.",
    "One release is one observation. No model is promoted or dropped on one scorecard.",
)


class ScoreRefused(ValueError):
    """The release cannot be scored from what is in the store."""


@dataclass(frozen=True)
class Scorecard:
    scorecard_id: str
    doc: dict[str, Any]
    body: bytes
    sha256: str


def _certain(order: Sequence[str]) -> dict[str, list[float]]:
    return {
        team: [1.0 if k >= place else 0.0 for k in range(1, RANKED + 1)]
        for place, team in enumerate(order[:RANKED], start=1)
    }


def _field(doc: Mapping[str, Any]) -> dict[str, Any] | None:
    section = doc.get("final_field")
    if not section:
        return None
    out: dict[str, Any] = {"kind": section.get("kind"), "outcome": None}
    out["outcome_note"] = "Field and bye probabilities are scored after Selection Day."
    try:
        rules = load_rules(doc["season"])
        hosts = sum(len(seeds) for _, seeds in rules.hosts)
        runs = check_section(section, field=rules.field_size, byes=len(rules.byes), hosts=hosts)
        out["integrity"] = {"passed": True, "runs": runs}
    except (IntegrityError, RulesError, KeyError) as error:
        out["integrity"] = {"passed": False, "error": str(error)}
    return out


def score_edition(
    doc: Mapping[str, Any], actual: Sequence[str], *, prior: Sequence[str] | None
) -> dict[str, Any]:
    """Both baselines in one edition against the committee's list."""
    noise = doc.get("rank_noise")
    first = doc["forecasts"]["baseline1"]
    rows = doc["forecasts"]["baseline2"]["rows"]
    orders = {"baseline1": list(first["order"]), "baseline2": [r["team_id"] for r in rows]}
    if set(orders["baseline1"]) != set(orders["baseline2"]):
        raise ScoreRefused("the two baselines in the edition do not cover the same teams")
    if noise:
        paths = noise["paths"]
        forecasts = {
            "baseline1": {t: cumulative_from_counts(c, paths) for t, c in first["rank_counts"].items()},
            "baseline2": {r["team_id"]: cumulative_from_counts(r["rank_counts"], paths) for r in rows},
        }
        how = "sampled ranks"
    else:
        forecasts = {name: _certain(order) for name, order in orders.items()}
        how = "point order, scored as certain"
    models: dict[str, Any] = {}
    for name, order in orders.items():
        try:
            card = score_weekly(name, order, forecasts[name], actual, order, prior=prior)
        except ValueError as error:
            raise ScoreRefused(str(error)) from error
        models[name] = card | {"label": LABELS[name], "forecast": how}
    column = None
    calibrated = {
        r["team_id"]: r["calibrated"]["p_top25"] for r in rows if "p_top25" in (r.get("calibrated") or {})
    }
    if calibrated:
        try:
            column = top25_scores({r["team_id"]: r["p_top25"] for r in rows}, calibrated, actual=actual)
        except ValueError as error:
            raise ScoreRefused(f"P(top 25) column: {error}") from error
    return {"models": models, "top25_column": column, "field": _field(doc)}


def not_prospective(
    doc: Mapping[str, Any], row: Mapping[str, Any], reveal: datetime, superseded: bool = False
) -> list[str]:
    """Why an edition does not count as a prospective forecast for this reveal; empty if it does.

    `row` is the store's record of the edition. Its ingest time is stamped by the store when the row is
    written, so an edition recorded after the reveal never counts, whatever its receipt says.
    """
    why = []
    if not doc.get("prospective_eligible"):
        why.append("the edition was not marked eligible when it was issued")
    if row["vintage"] != "live":
        why.append(f"its vintage is {row['vintage']}, not live")
    if not datetime.fromisoformat(doc["cutoff_utc"]) < reveal:
        why.append("its cutoff is not before the reveal")
    if not row["first_public_time"] < reveal:
        why.append("it was issued after the reveal")
    if not row["ingest_time"] < reveal:
        why.append("it was recorded in the store after the reveal")
    if superseded:
        why.append("a later revision supersedes it")
    return why


def release_rows(frame: pl.DataFrame, release_id: str) -> tuple[int, int, datetime, list[str]]:
    rows = frame.filter(pl.col("release_id") == release_id).sort("rank")
    if not rows.height:
        raise ScoreRefused(f"{release_id} is not in the store: ingest the release first")
    if rows["rank"].to_list() != list(range(1, RANKED + 1)):
        raise ScoreRefused(f"{release_id} does not hold ranks 1 to {RANKED} once each")
    head = rows.row(0, named=True)
    return head["season"], head["release_no"], head["reveal_utc"], rows["team_id"].to_list()


def build_scorecard(
    lake: Lake,
    release_id: str,
    *,
    now: datetime,
    mode: Mode = "live",
    revision: int = 1,
    code_hash: str,
    editions_root: Path | None = None,
) -> Scorecard:
    """Score every recorded edition issued for `release_id`. Reads only; writes nothing."""
    if revision < 1:
        raise ScoreRefused("a revision is 1 or more")
    releases = lake.as_of("committee_releases", now, mode).frame
    season, number, reveal, actual = release_rows(releases, release_id)
    if now < reveal:
        raise ScoreRefused(f"{release_id} is revealed at {reveal.isoformat()}: nothing is scored before then")
    prior: list[str] | None = None
    prior_id: str | None = None
    if number > 1:
        earlier = releases.filter((pl.col("season") == season) & (pl.col("release_no") == number - 1))
        if not earlier.height:
            raise ScoreRefused(f"release {number - 1} of {season} is not in the store: ingest it first")
        prior_id = earlier["release_id"][0]
        _, _, _, prior = release_rows(releases, prior_id)
    names = dict(lake.as_of("teams", now, mode).frame.select("team_id", "name").iter_rows())
    stem = f"scw-{season}-r{number:02d}-"
    held = lake.as_of("editions", now, mode, season=season).frame
    held = held.filter((pl.col("product") == PRODUCT) & pl.col("edition_id").str.starts_with(stem))
    if not held.height:
        raise ScoreRefused(f"no edition was recorded for {release_id}: there is nothing to score")
    root = editions_root or lake.root / "editions"
    docs: dict[str, dict[str, Any]] = {}
    for row in held.sort("edition_id").iter_rows(named=True):
        path = root / row["edition_id"] / "edition.json"
        if not path.is_file():
            raise ScoreRefused(f"{row['edition_id']} is recorded but its file is missing")
        body = path.read_bytes()
        if hashlib.sha256(body).hexdigest() != row["sha256"]:
            raise ScoreRefused(f"{row['edition_id']}: the file's hash is not the hash recorded at issue")
        docs[row["edition_id"]] = json.loads(body) | {"_row": row}
    replaced = {d["supersedes"]: name for name, d in docs.items() if d.get("supersedes")}
    editions = []
    for name, doc in docs.items():
        row = doc["_row"]
        if doc.get("target_release_no") != number or datetime.fromisoformat(doc["reveal_utc"]) != reveal:
            raise ScoreRefused(
                f"{name} was not issued for {release_id}: its own reveal or release number differs"
            )
        why = not_prospective(doc, row, reveal, superseded=name in replaced)
        editions.append(
            {
                "edition_id": name,
                "sha256": row["sha256"],
                "hash_matches_issue": True,
                "issue": doc["issue"],
                "cutoff_utc": doc["cutoff_utc"],
                "issued_utc": row["first_public_time"].isoformat(),
                "vintage": row["vintage"],
                "code_hash": doc.get("code_hash"),
                "prospective": not why,
                "not_prospective_because": why,
                "superseded_by": replaced.get(name),
                "headline_forecast": doc.get("headline_forecast"),
            }
            | score_edition(doc, actual, prior=prior)
        )
    scorecard_id = f"score-{season}-r{number:02d}-e{revision}"
    document = {
        "schema": SCHEMA,
        "scorecard_id": scorecard_id,
        "product": "scorecard_weekly",
        "supersedes": f"score-{season}-r{number:02d}-e{revision - 1}" if revision > 1 else None,
        "season": season,
        "release_id": release_id,
        "release_no": number,
        "reveal_utc": reveal.isoformat(),
        "prior_release_id": prior_id,
        "mode": mode,
        "actual": actual,
        "actual_sha256": hashlib.sha256(canonical(actual)).hexdigest(),
        "names": {team: names.get(team, team) for team in actual},
        "fitted_model": "not issued",
        "prospective_editions": sum(1 for e in editions if e["prospective"]),
        "editions": editions,
        "code_hash": code_hash,
        "notes": list(NOTES),
    }
    body = canonical(document)
    return Scorecard(scorecard_id, document, body, hashlib.sha256(body).hexdigest())
