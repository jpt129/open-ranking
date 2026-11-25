"""CFBD payloads -> store rows (P02a). Pure functions; field names follow CFBD's OpenAPI schema v5.

Rows carry rule-based first-public times (cfp.ingest.public_time). A row is vintage "live" only when the
live system captured it within seven days of that time; everything else, including the first catch-up of
the live season, is "reconstructed" (John, 2026-11-25). IDs are `cfbd-<id>`.
"""

from __future__ import annotations

import re
from collections.abc import Sequence
from datetime import datetime
from typing import Any

import polars as pl

from cfp.common.timeutil import require_utc
from cfp.ingest.errors import SourceError
from cfp.ingest.http import Fetched
from cfp.ingest.public_time import game_final_public, poll_public, vintage_at
from cfp.store.schemas import TABLES

SEASON_TYPES = ("regular", "postseason")
POLLS = {"AP Top 25": "ap", "Coaches Poll": "coaches"}
# "SEC Championship", "Big 12 Championship Game"; not "FCS Championship - Second Round".
TITLE_NOTE = re.compile(r"^[\w .&'()-]+ championship( game)?$", re.IGNORECASE)
PROVIDED = ("correction_version", "ingest_time")


def _frame(table: str, rows: list[dict[str, Any]]) -> pl.DataFrame:
    schema = {k: v for k, v in TABLES[table].schema.items() if k not in PROVIDED}
    return pl.DataFrame(rows, schema=schema)


def _time(value: Any) -> datetime | None:
    if value in (None, ""):
        return None
    return require_utc(datetime.fromisoformat(str(value).replace("Z", "+00:00")), "startDate")


def team_id(value: Any) -> str:
    return f"cfbd-{int(value)}"


def is_title_game(game: dict[str, Any]) -> bool:
    """Provisional: a regular-season game between FBS teams whose note is "<conference> Championship".

    P04 replaces this with a hand-verified list.
    """
    both_fbs = game.get("homeClassification") == "fbs" and game.get("awayClassification") == "fbs"
    note = (game.get("notes") or "").strip()
    return game["seasonType"] == "regular" and both_fbs and bool(TITLE_NOTE.match(note))


def _provenance(got: Fetched, path: str, event: datetime, public: datetime, vintage: str) -> dict[str, Any]:
    return {
        "source_id": f"cfbd:{path}",
        "event_time": event,
        "first_public_time": public,
        "raw_hash": got.raw_hash,
        "vintage": vintage,
    }


def game_rows(got: Fetched, live: bool) -> tuple[pl.DataFrame, list[str]]:
    """One row per game in a /games payload, in its current state, plus the IDs of games left out.

    A completed game is a "final" row, public at kickoff + 4.5 h. An unplayed game in the live season is a
    "scheduled" row, public when we captured it. Left out: unplayed games of a past season (when their
    schedule became known is not something this payload can tell us) and non-FBS games marked completed
    with no score.
    """
    rows: list[dict[str, Any]] = []
    left_out: list[str] = []
    for game in got.json():
        if game["seasonType"] not in SEASON_TYPES:
            continue
        game_id = f"cfbd-{int(game['id'])}"
        start = _time(game.get("startDate"))
        if start is None:
            raise SourceError(f"cfbd: game {game['id']} has no start time")
        if game.get("neutralSite") is None:
            raise SourceError(f"cfbd: game {game['id']} has no neutral-site flag")
        done = bool(game.get("completed"))
        scores = (game.get("homePoints"), game.get("awayPoints"))
        if done and None in scores:
            # No score is never filled in. With an FBS team involved the ingest stops; otherwise the game
            # is left out and reported.
            if "fbs" in (game.get("homeClassification"), game.get("awayClassification")):
                raise SourceError(f"cfbd: FBS game {game['id']} is marked completed without a score")
            left_out.append(game_id)
            continue
        if not done and not live:
            left_out.append(game_id)
            continue
        if done:
            public = game_final_public(start, bool(game.get("startTimeTBD")))
            vintage = vintage_at(live, public, got.fetched_at)
        else:
            public, vintage = got.fetched_at, "live"
        rows.append(
            {
                "game_id": game_id,
                "season": int(game["season"]),
                "week": int(game["week"]),
                "start_utc": start,
                "home_id": team_id(game["homeId"]),
                "away_id": team_id(game["awayId"]),
                "home_pts": int(scores[0]) if done else None,
                "away_pts": int(scores[1]) if done else None,
                "neutral": bool(game["neutralSite"]),
                "site": game.get("venue"),
                "season_type": game["seasonType"],
                "status": "final" if done else "scheduled",
                "title_game": is_title_game(game),
                # "unknown" is CFBD giving no classification; a snapshot must resolve it, never assume it
                "home_div": game.get("homeClassification") or "unknown",
                "away_div": game.get("awayClassification") or "unknown",
            }
            | _provenance(got, "/games", start, public, vintage)
        )
    return _frame("games", rows), left_out


def poll_rows(got: Fetched, kickoffs: Sequence[tuple[int, datetime]], live: bool) -> pl.DataFrame:
    """AP and Coaches rows from one regular-season /rankings payload.

    `kickoffs` is (week, kickoff) for the season's regular-season games; it dates each poll by rule.
    Postseason polls and CFBD's copy of the committee rankings are not written (docs/DECISIONS.md).
    """
    if not kickoffs:
        raise SourceError("cfbd: polls cannot be dated without the season's game kickoffs")
    last: dict[int, datetime] = {}
    for week, kickoff in kickoffs:
        last[week] = max(last.get(week, kickoff), kickoff)
    first = min(kickoff for _, kickoff in kickoffs)
    rows: list[dict[str, Any]] = []
    dated: dict[int, datetime] = {}
    for item in got.json():
        if item["seasonType"] != "regular":
            continue
        week = int(item["week"])
        try:
            public = poll_public(week, last, first)
        except ValueError as error:
            raise SourceError(f"cfbd: {error}") from error
        if public in dated.values() and week not in dated:
            raise SourceError(
                f"cfbd: the week-{week} poll gets the same public time as another week's ({public}); "
                "a game is filed under the wrong week"
            )
        dated[week] = public
        vintage = vintage_at(live, public, got.fetched_at)
        for poll in item["polls"]:
            name = POLLS.get(poll["poll"])
            if name is None:
                continue
            for rank in poll["ranks"]:
                rows.append(
                    {
                        "poll": name,
                        "season": int(item["season"]),
                        "week": week,
                        "team_id": team_id(rank["teamId"]),
                        "rank": int(rank["rank"]) if rank.get("rank") is not None else None,
                        "points": int(rank["points"]) if rank.get("points") is not None else None,
                        "fpv": int(rank["firstPlaceVotes"])
                        if rank.get("firstPlaceVotes") is not None
                        else None,
                        "others_votes": False,
                    }
                    | _provenance(got, "/rankings", public, public, vintage)
                )
    return _frame("polls", rows)


def line_rows(got: Fetched, live: bool) -> pl.DataFrame:
    """Closing lines from one /lines payload, one row per provider and game."""
    rows: list[dict[str, Any]] = []
    for game in got.json():
        start = _time(game.get("startDate"))
        if start is None:
            continue
        public = game_final_public(start)
        for line in game.get("lines") or []:
            values = {
                "ml_home": line.get("homeMoneyline"),
                "ml_away": line.get("awayMoneyline"),
                "spread": line.get("spread"),
                "total": line.get("overUnder"),
            }
            if all(value is None for value in values.values()):
                continue
            rows.append(
                {
                    "provider": str(line["provider"]),
                    "game_id": f"cfbd-{int(game['id'])}",
                    "as_of_utc": start,
                    "season": int(game["season"]),
                    **{k: float(v) if v is not None else None for k, v in values.items()},
                }
                | _provenance(got, "/lines", start, public, vintage_at(live, public, got.fetched_at))
            )
    return _frame("lines", rows)
