"""Build one weekly forecast issue at its cutoff (SC-02, SC-03; P23).

Every table is read through as_of at the cutoff. A live issue must be run between its cutoff and the reveal;
a replay is never a prospective forecast. The document carries no wall-clock time.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any

import polars as pl

from cfp.common.hashing import sha256_hex
from cfp.common.timeutil import require_utc
from cfp.forecast.baselines import FINAL_LAG, ap_order, baseline1, baseline2, initial_order, losses_since
from cfp.forecast.cutoffs import ET, ISSUES, issue_time
from cfp.forecast.observations import (
    RANKED,
    ObservationError,
    fbs_field,
    label_leaked,
    open_points_feature,
)
from cfp.ingest.public_time import tuesday_after
from cfp.open_ranking.band import BandError
from cfp.open_ranking.frozen import Frozen
from cfp.open_ranking.ledger import LedgerError
from cfp.open_ranking.strength import StrengthError
from cfp.release.edition import canonical, input_id
from cfp.snapshot.build import SnapshotBlocked
from cfp.store.lake import Lake
from cfp.store.types import Mode

PRODUCT = "shadow_committee_weekly"
RULE_VERSION = "sc-baselines-1"
STALE_WINDOW = timedelta(days=7)
TABLES = ("teams", "membership", "eligibility", "committee_releases", "polls", "games")


class IssueRefused(RuntimeError):
    """The issue cannot be built: wrong time, or a required input is missing."""


class TooEarly(IssueRefused):
    """The cutoff has not passed yet; the same command will work once it has."""


class Unresolved(IssueRefused):
    """Games that should be final by the cutoff are still listed as scheduled: results look stale."""


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
    dry_run: bool = False,
    allow_unresolved: bool = False,
    frozen: Frozen | None = None,
    lists: Mapping[str, Any] | None = None,
    open_points_note: str | None = None,
) -> Issue:
    """The forecast for the committee release revealed at `reveal`, from inputs public at the issue cutoff.

    `reveals` is the season's sourced reveal schedule; it says which release is being forecast and which
    earlier release must already be in the store.

    A live issue is refused when a game involving an FBS team should be final by the cutoff (kickoff plus
    4.5 hours, within the last week) and is still listed as scheduled, because that means results were not
    ingested. `allow_unresolved` issues anyway and lists those games in the document. A dry run (frozen
    clock) and a replay carry their own edition IDs and are never eligible for prospective scoring.

    With `frozen` parameters and the hand-kept `lists`, open points are built at the cutoff (SC-04a) and
    break ties among teams level on AP standing. If that build cannot be made, the issue still goes out:
    open points are listed as a missing input and the reason is in `open_points_error`.
    """
    if revision < 1:
        raise IssueRefused(f"revision must be 1 or more; got {revision}")
    if mode == "live" and not dry_run and (code_hash == "unknown" or code_hash.endswith("-dirty")):
        raise IssueRefused(f"refused: a live issue needs committed code; the code hash is {code_hash!r}")
    reveal, now = require_utc(reveal, "reveal"), require_utc(now, "now")
    schedule = sorted(require_utc(r, "reveals") for r in reveals)
    if reveal not in schedule:
        raise IssueRefused(f"{reveal.isoformat()} is not a scheduled reveal for {season}")
    cutoff = issue_time(issue, reveal)
    if mode == "live":
        if now >= reveal:
            raise IssueRefused(f"refused: it is {now.isoformat()}, after the reveal at {reveal.isoformat()}")
        if now < cutoff:
            raise TooEarly(f"refused: it is {now.isoformat()}, before the cutoff at {cutoff.isoformat()}")
    elif mode != "replay":
        raise IssueRefused(f"an issue is built in live or replay mode; got {mode!r}")

    read = {name: lake.as_of(name, cutoff, mode, season=season).frame for name in TABLES}
    names: dict[str, str] = dict(read["teams"].select("team_id", "name").iter_rows())
    try:
        field = fbs_field(read["membership"], read["eligibility"], season, cutoff.astimezone(ET).date())
    except ObservationError as error:
        raise IssueRefused(str(error)) from error
    teams: list[str] = field["team_id"].to_list()
    eligible: dict[str, bool] = dict(field.iter_rows())
    if not teams:
        raise IssueRefused(f"no FBS teams are on record for {season} at the cutoff")
    missing = ["rank_noise_temperature"]
    feature = None
    feature_error: str | None = open_points_note  # why the caller could not supply parameters or lists
    if frozen is not None and lists is not None:
        try:
            feature = open_points_feature(lake.open_ranking_view(cutoff, mode), season, frozen, lists)
        except (SnapshotBlocked, LedgerError, BandError, StrengthError) as error:
            feature_error = f"{type(error).__name__}: {error}"  # the data cannot support a ledger yet
        except Exception as error:  # a fault in the feature build must not cost the forecast its deadline
            feature_error = f"unexpected {type(error).__name__}: {error}"
    if feature is None:
        missing.insert(0, "open_points")
    open_points = feature.points if feature is not None else None

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
        # Disclosed, not fatal: teams outside the AP top 25 then fall to the draw (`cfp ingest ap-others`).
        missing.append("ap_votes_outside_25")
    games = read["games"]
    involved = pl.col("home_id").is_in(teams) | pl.col("away_id").is_in(teams)
    overdue = games.filter(
        involved
        & (pl.col("status") == "scheduled")
        & (pl.col("start_utc") + FINAL_LAG <= cutoff)
        & (pl.col("start_utc") >= cutoff - STALE_WINDOW)
    )
    unresolved: list[str] = sorted(overdue["game_id"].to_list())
    if unresolved and mode == "live" and not allow_unresolved:
        raise Unresolved(
            f"refused: {len(unresolved)} games should be final by the cutoff and are still scheduled "
            f"(first: {unresolved[0]}); ingest results, or pass --allow-unresolved to issue and disclose"
        )
    finals = games.filter((pl.col("status") == "final") & (pl.col("season_type") == "regular"))
    expected_ap = [
        int(week) + 1
        for week, start in finals.select("week", "start_utc").drop_nulls().iter_rows()
        if tuesday_after(start + FINAL_LAG) <= cutoff
    ]
    if expected_ap and ap_week < max(expected_ap):
        missing.append("latest_ap_poll")
    try:
        if earlier:
            release_id = f"cfp-{season}-{len(earlier):02d}"
            last = releases.filter(pl.col("reveal_utc") == earlier[-1]).sort("rank")
            if last.height != RANKED or last["release_id"].unique().to_list() != [release_id]:
                raise IssueRefused(f"{release_id} (revealed {earlier[-1].isoformat()}) is not in the store")
            prior = last["team_id"].to_list()
            anchor = {"kind": "cfp_release", "release_id": release_id, "since_utc": earlier[-1].isoformat()}
            losses = losses_since(games, teams, since=earlier[-1])
        else:
            anchor = {"kind": "ap_poll", "ap_week": ap_week}
            losses = losses_since(games, teams, since_week=ap_week)
    except ValueError as error:
        raise IssueRefused(str(error)) from error

    try:
        first = baseline1(teams, ap, draw)
        placed = baseline2(initial_order(teams, prior, ap, open_points, draw), losses)
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
            "open_points_cp": open_points.get(p.team_id) if open_points is not None else None,
            "cfp_eligible": eligible[p.team_id],
        }
        for p in placed
    ]
    target = len(earlier) + 1
    kind = "-dry" if dry_run else ("-replay" if mode == "replay" else "")
    stem = f"scw-{season}-r{target:02d}-{issue}{kind}"
    edition_id = f"{stem}-e{revision}"
    inputs = [input_id(name, read[name], lake.spec(name).key) for name in TABLES]
    inputs.append(f"draw:{len(draw)}:{sha256_hex(canonical(dict(sorted(draw.items()))))}")
    if feature is not None:
        inputs.append(f"feature:{feature.feature_build_id}")
        inputs.append(f"feature-snapshot:{feature.snapshot_hash}")
        inputs.append(f"feature-params:{feature.params_sha256}")
        inputs.append(f"feature-rule:{feature.rule_version_id}")
    doc: dict[str, Any] = {
        "schema": 2,
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
        "dry_run": dry_run,
        "prospective_eligible": mode == "live" and not leaked and not dry_run,
        "supersedes": f"{stem}-e{revision - 1}" if revision > 1 else None,
        "unresolved_games": unresolved,
        "headline_forecast": "baseline2",
        "missing_inputs": missing,
        "open_ranking_feature": (
            {
                "feature_build_id": feature.feature_build_id,
                "snapshot_hash": feature.snapshot_hash,
                "lists_hash": feature.lists_hash,
                "params_sha256": feature.params_sha256,
                "formula_hash": feature.formula_hash,
                "rule_version_id": feature.rule_version_id,
            }
            if feature is not None
            else None
        ),
        "open_points_error": feature_error,
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


def due_issue(
    reveals: Sequence[datetime], now: datetime, lead: timedelta = timedelta(hours=3)
) -> tuple[str, datetime] | None:
    """The issue whose cutoff is within `lead` of now, or passed under an hour ago, and before its reveal."""
    now = require_utc(now, "now")
    due = []
    for reveal in reveals:
        for issue in ISSUES:
            cutoff = issue_time(issue, reveal)
            if cutoff - lead <= now < min(reveal, cutoff + timedelta(hours=1)):
                due.append((cutoff, issue, require_utc(reveal, "reveal")))
    if not due:
        return None
    _, issue, reveal = min(due)
    return issue, reveal
