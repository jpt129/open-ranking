"""Build one weekly forecast issue at its cutoff (SC-02, SC-03; P23).

Every table is read through as_of at the cutoff. A live issue must be run between its cutoff and the reveal;
a replay is never a prospective forecast. The document carries no wall-clock time.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime
from typing import Any

import polars as pl

from cfp.common.hashing import sha256_hex
from cfp.common.timeutil import require_utc
from cfp.forecast.baselines import ap_order, baseline1, baseline2, initial_order, losses_since
from cfp.forecast.cutoffs import ET, issue_time
from cfp.forecast.observations import RANKED, fbs_field, label_leaked
from cfp.release.edition import canonical, input_id
from cfp.store.lake import Lake
from cfp.store.types import Mode

PRODUCT = "shadow_committee_weekly"
RULE_VERSION = "sc-baselines-1"
TABLES = ("teams", "membership", "eligibility", "committee_releases", "polls", "games")


class IssueRefused(RuntimeError):
    """The issue cannot be built: wrong time, or a required input is missing."""


@dataclass(frozen=True)
class Issue:
    edition_id: str
    doc: dict[str, Any]
    body: bytes
    sha256: str
    cutoff: datetime
    reveal: datetime


def build_issue(
    lake: Lake,
    *,
    season: int,
    issue: str,
    reveal: datetime,
    reveals: Sequence[datetime],
    mode: Mode,
    now: datetime,
    code_hash: str,
    draw: Mapping[str, int],
    revision: int = 1,
) -> Issue:
    """The forecast for the committee release revealed at `reveal`, from inputs public at the issue cutoff.

    `reveals` is the season's sourced reveal schedule; it says which release is being forecast and which
    earlier release must already be in the store.
    """
    reveal, now = require_utc(reveal, "reveal"), require_utc(now, "now")
    schedule = sorted(require_utc(r, "reveals") for r in reveals)
    if reveal not in schedule:
        raise IssueRefused(f"{reveal.isoformat()} is not a scheduled reveal for {season}")
    cutoff = issue_time(issue, reveal)
    if mode == "live":
        if now >= reveal:
            raise IssueRefused(f"refused: it is {now.isoformat()}, after the reveal at {reveal.isoformat()}")
        if now < cutoff:
            raise IssueRefused(f"refused: it is {now.isoformat()}, before the cutoff at {cutoff.isoformat()}")
    elif mode != "replay":
        raise IssueRefused(f"an issue is built in live or replay mode; got {mode!r}")

    read = {name: lake.as_of(name, cutoff, mode, season=season).frame for name in TABLES}
    names: dict[str, str] = dict(read["teams"].select("team_id", "name").iter_rows())
    field = fbs_field(read["membership"], read["eligibility"], season, cutoff.astimezone(ET).date())
    teams: list[str] = field["team_id"].to_list()
    eligible: dict[str, bool] = dict(field.iter_rows())
    if not teams:
        raise IssueRefused(f"no FBS teams are on record for {season} at the cutoff")
    missing = ["open_points", "rank_noise_temperature"]

    releases = read["committee_releases"]
    leaked = label_leaked(releases, reveal)
    earlier = [r for r in schedule if r < reveal]
    prior: list[str] | None = None
    anchor: dict[str, Any]
    ap = read["polls"].filter(pl.col("poll") == "ap")
    if ap.height == 0:
        raise IssueRefused("no AP poll is public at the cutoff")
    ap_week = ap_order(ap)[0][0]
    if not ap.filter((pl.col("week") == ap_week) & pl.col("others_votes")).height:
        if mode == "live":
            raise IssueRefused(
                f"the week-{ap_week} AP poll has no votes for teams outside the top 25; "
                "run `cfp ingest ap-others`"
            )
        missing.append("ap_votes_outside_25")
    games = read["games"]
    if earlier:
        release_id = f"cfp-{season}-{len(earlier):02d}"
        last = releases.filter(pl.col("reveal_utc") == earlier[-1]).sort("rank")
        if last.height != RANKED or last["release_id"].unique().to_list() != [release_id]:
            raise IssueRefused(f"{release_id} (revealed {earlier[-1].isoformat()}) is not in the store")
        prior = last["team_id"].to_list()
        anchor = {"kind": "cfp_release", "release_id": release_id, "since_utc": earlier[-1].isoformat()}
        losses = losses_since(games, since=earlier[-1])
    else:
        anchor = {"kind": "ap_poll", "ap_week": ap_week}
        losses = losses_since(games, since_week=ap_week)

    try:
        first = baseline1(teams, ap, draw)
        placed = baseline2(initial_order(teams, prior, ap, None, draw), losses)
    except ValueError as error:
        raise IssueRefused(str(error)) from error
    second = [
        {
            "team_id": p.team_id,
            "name": names[p.team_id],
            "position": p.position,
            "initial": p.initial,
            "losses": p.losses,
            "adjusted": p.adjusted,
            "cfp_eligible": eligible[p.team_id],
        }
        for p in placed
    ]
    target = len(earlier) + 1
    edition_id = f"scw-{season}-r{target:02d}-{issue}-e{revision}"
    inputs = [input_id(name, read[name], lake.spec(name).key) for name in TABLES]
    inputs.append(f"draw:{len(draw)}:{sha256_hex(canonical(dict(sorted(draw.items()))))}")
    doc: dict[str, Any] = {
        "schema": 1,
        "edition_id": edition_id,
        "product": PRODUCT,
        "public_name": "Open Ranking Models",
        "season": season,
        "issue": issue,
        "cutoff_utc": cutoff.isoformat(),
        "reveal_utc": reveal.isoformat(),
        "target_release_no": target,
        "mode": mode,
        "label_leaked": leaked,
        "prospective_eligible": mode == "live" and not leaked,
        "headline_forecast": "baseline2",
        "missing_inputs": missing,
        "ap_week": ap_week,
        "fbs_teams": len(teams),
        "forecasts": {
            "baseline1": {"top25": first[:RANKED], "order": first},
            "baseline2": {
                "anchor": anchor,
                "top25": [row["team_id"] for row in second[:RANKED]],
                "rows": second,
            },
        },
        "inputs": inputs,
        "code_hash": code_hash,
        "rule_version_id": RULE_VERSION,
    }
    body = canonical(doc)
    return Issue(edition_id, doc, body, sha256_hex(body), cutoff, reveal)
