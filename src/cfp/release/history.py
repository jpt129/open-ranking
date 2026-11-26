"""Past issues rebuilt as they would have been (VT-10): the training examples for fitted forecast parameters.

For every committee release of a past season, each baseline is rebuilt at each issue cutoff by the same code
that builds a live issue, reading the store in replay mode as of that cutoff. Nothing is written. Past seasons
have no published draw; the same rule (a hash of a fixed phrase and the team id) supplies one.
"""

from __future__ import annotations

import dataclasses
from collections.abc import Mapping, Sequence
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any

import polars as pl

from cfp.common.draw import PHRASE, draw_positions
from cfp.forecast.cutoffs import ISSUES
from cfp.forecast.noise_params import Example, release_kind
from cfp.forecast.pairings import conference_id as conference_key
from cfp.ingest.cfp_releases import load_schedule
from cfp.open_ranking.frozen import Frozen
from cfp.release.issue import IssueRefused, build_issue
from cfp.snapshot.data import load_title_games
from cfp.store.lake import Lake


def _initial(row: Mapping[str, Any]) -> int:
    return int(row["initial"])


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
                        [row["team_id"] for row in sorted(forecasts["baseline2"]["rows"], key=_initial)],
                        {
                            row["team_id"]: row["losses"]
                            for row in forecasts["baseline2"]["rows"]
                            if row["losses"]
                        },
                        len(shows),
                    )
                )
    return out, problems


def past_champions(
    lake: Lake, data: Path, seasons: Sequence[int], now: datetime
) -> tuple[dict[int, dict[str, str]], dict[int, dict[str, str]], list[str]]:
    """(champion by season and conference, conference by season and team, problems) from played title games.

    A champion is the winner of the final game between the two named teams within a day of the listed date.
    A title game that cannot be matched to one final game is a problem, never a guess.
    """
    wanted = set(seasons)
    ids = dict(lake.as_of("teams", now, "replay").frame.select("name", "team_id").iter_rows())
    games = lake.as_of("games", now, "replay").frame.filter(pl.col("status") == "final")
    membership = lake.as_of("membership", now, "replay").frame
    champions: dict[int, dict[str, str]] = {season: {} for season in wanted}
    problems: list[str] = []
    for title in load_title_games(data / "title_games.csv"):
        if title.season not in wanted:
            continue
        where = f"{title.season} {title.conference}"
        if not title.team_a:
            problems.append(f"{where}: the title game's teams are not on file")
            continue
        a, b = ids.get(title.team_a), ids.get(title.team_b)
        if a is None or b is None:
            problems.append(f"{where}: {title.team_a} or {title.team_b} is not a team in the store")
            continue
        day = pl.col("start_utc").dt.date()
        met = ((pl.col("home_id") == a) & (pl.col("away_id") == b)) | (
            (pl.col("home_id") == b) & (pl.col("away_id") == a)
        )
        near = (day >= title.day - timedelta(days=1)) & (day <= title.day + timedelta(days=1))
        found = games.filter((pl.col("season") == title.season) & met & near)
        if found.height != 1:
            problems.append(f"{where}: {found.height} final games match the title game")
            continue
        game = found.row(0, named=True)
        winner = game["home_id"] if game["home_pts"] > game["away_pts"] else game["away_id"]
        champions[title.season][conference_key(title.conference)] = winner
    leagues: dict[int, dict[str, str]] = {}
    for season in wanted:
        dec1 = date(season, 12, 1)
        rows = membership.filter(
            (pl.col("valid_from") <= dec1) & (pl.col("valid_to").is_null() | (pl.col("valid_to") >= dec1))
        )
        leagues[season] = dict(rows.select("team_id", "conference_id").iter_rows())
    return champions, leagues, problems
