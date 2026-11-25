"""AP votes for teams outside the top 25, from ESPN's rankings feed (SC-03; docs/DECISIONS.md 2026-11-25).

CFBD's poll rows stop at 25. Baseline 2 orders the other teams by AP votes, so the "others receiving votes"
list is read from ESPN. An ESPN poll is accepted only when its ranked 25 (team and points) equal an AP poll
already stored from CFBD; the new rows take that poll's week and public time.
"""

from __future__ import annotations

from collections.abc import Mapping
from datetime import datetime
from typing import Any

import polars as pl

from cfp.ingest.cfbd_normalize import PROVIDED
from cfp.ingest.errors import SourceError
from cfp.ingest.http import Fetched
from cfp.ingest.public_time import vintage_at
from cfp.store.schemas import TABLES

SOURCE_ID = "espn:/rankings"
ESPN_AP = "ap"


def others_rows(
    got: Fetched, stored_ap: pl.DataFrame, team_by_espn: Mapping[int, str], live: bool
) -> pl.DataFrame:
    """Polls rows (rank null, others_votes true) for the AP poll in one ESPN rankings payload.

    `stored_ap` is the season's AP rows already in the store; `team_by_espn` maps confirmed ESPN ids to team
    ids. An unknown ESPN id among the ranked 25 stops the build. Among the others it is an FCS or otherwise
    untracked school and is skipped, since only FBS teams are forecast.
    """
    polls = [r for r in got.json().get("rankings", []) if r.get("type") == ESPN_AP]
    if len(polls) != 1:
        raise SourceError(f"espn: expected one AP poll in the payload, found {len(polls)}")
    poll = polls[0]
    ranked: dict[str, int] = {}
    for row in poll["ranks"]:
        espn_id = int(row["team"]["id"])
        if espn_id not in team_by_espn:
            raise SourceError(
                f"espn: AP-ranked team {row['team'].get('location')} ({espn_id}) is not matched"
            )
        ranked[team_by_espn[espn_id]] = int(row["points"])
    weeks = []
    top = stored_ap.filter(pl.col("rank").is_not_null())
    for (week,), rows in top.partition_by("week", as_dict=True).items():
        if dict(rows.select("team_id", "points").iter_rows()) == ranked:
            weeks.append((week, rows))
    if len(weeks) != 1:
        raise SourceError(f"espn: the AP poll matches {len(weeks)} stored polls; ingest CFBD rankings first")
    week, match = weeks[0]
    public = match["first_public_time"].max()
    if not isinstance(public, datetime):
        raise SourceError("espn: the stored poll has no public time")
    season = int(match["season"][0])
    out: list[dict[str, Any]] = []
    for row in poll.get("others") or []:
        team = team_by_espn.get(int(row["team"]["id"]))
        if team is None:
            continue
        if team in ranked:
            raise SourceError(f"espn: {team} is both ranked and among the others")
        out.append(
            {
                "poll": "ap",
                "season": season,
                "week": int(week),
                "team_id": team,
                "rank": None,
                "points": int(row["points"]),
                "fpv": int(row.get("firstPlaceVotes") or 0),
                "others_votes": True,
                "source_id": SOURCE_ID,
                "event_time": public,
                "first_public_time": public,
                "raw_hash": got.raw_hash,
                "vintage": vintage_at(live, public, got.fetched_at),
            }
        )
    if not out:
        raise SourceError(f"espn: the week-{week} AP poll lists no votes outside the top 25")
    schema = {k: v for k, v in TABLES["polls"].schema.items() if k not in PROVIDED}
    return pl.DataFrame(out, schema=schema)
