"""Past issues rebuilt as they would have been (VT-10): the training examples for fitted forecast parameters.

For every committee release of a past season, each baseline is rebuilt at each issue cutoff by the same code
that builds a live issue, reading the store in replay mode as of that cutoff. Nothing is written. Past seasons
have no published draw; the same rule (a hash of a fixed phrase and the team id) supplies one.
"""

from __future__ import annotations

import dataclasses
from collections.abc import Mapping, Sequence
from datetime import datetime
from pathlib import Path
from typing import Any

import polars as pl

from cfp.common.draw import PHRASE, draw_positions
from cfp.forecast.cutoffs import ISSUES
from cfp.forecast.noise_params import Example, release_kind
from cfp.ingest.cfp_releases import load_schedule
from cfp.open_ranking.frozen import Frozen
from cfp.release.issue import IssueRefused, build_issue
from cfp.store.lake import Lake


def past_examples(
    lake: Lake,
    data: Path,
    seasons: Sequence[int],
    now: datetime,
    *,
    frozen: Frozen | None = None,
    lists: Mapping[str, Any] | None = None,
) -> tuple[list[Example], list[str]]:
    """(examples, problems) for every release of `seasons` and both issue times."""
    schedule = load_schedule(data / "cfp_reveals.csv")
    releases = lake.as_of("committee_releases", now, "replay").frame
    team_ids = lake.as_of("teams", now, "replay").frame["team_id"].to_list()
    out: list[Example] = []
    problems: list[str] = []
    for season in seasons:
        shows = sorted(reveal.show_start for day, reveal in schedule.items() if day.year == season)
        draw = draw_positions(team_ids, PHRASE.format(season=season))
        params = dataclasses.replace(frozen, season=season) if frozen is not None else None
        for number, reveal in enumerate(shows, start=1):
            actual = releases.filter(pl.col("reveal_utc") == reveal).sort("rank")["team_id"].to_list()
            if len(actual) != 25:
                problems.append(f"{season} release {number}: {len(actual)} ranked teams in the store")
                continue
            for issue in ISSUES:
                try:
                    built = build_issue(
                        lake,
                        season=season,
                        issue=issue,
                        reveal=reveal,
                        reveals=shows,
                        mode="replay",
                        now=now,
                        code_hash="history",
                        draw=draw,
                        frozen=params,
                        lists=lists,
                    )
                except (IssueRefused, ValueError) as error:
                    problems.append(f"{season} release {number} {issue}: {error}")
                    continue
                forecasts = built.doc["forecasts"]
                if built.doc["open_points_error"]:
                    problems.append(f"{season} release {number} {issue}: {built.doc['open_points_error']}")
                out.append(
                    Example(
                        season,
                        number,
                        issue,
                        release_kind(number, len(shows)),
                        forecasts["baseline1"]["order"],
                        [row["team_id"] for row in forecasts["baseline2"]["rows"]],
                        actual,
                    )
                )
    return out, problems
