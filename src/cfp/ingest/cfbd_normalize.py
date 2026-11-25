"""CFBD payloads -> store rows (P02a). Pure functions; field names follow CFBD's OpenAPI schema v5.

Backfill rows are vintage "reconstructed" with rule-based first-public times (cfp.ingest.public_time);
rows captured during the live season are "live" (John, 2026-11-25). IDs are `cfbd-<id>`.
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
from cfp.ingest.public_time import game_final_public, poll_public, schedule_public
from cfp.store.schemas import TABLES

SEASON_TYPES = ("regular", "postseason")
POLLS = {"AP Top 25": "ap", "Coaches Poll": "coaches"}
TITLE_NOTE = re.compile(r"\bchampionship\b", re.IGNORECASE)
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
    """Provisional: a regular-season game whose note names a championship. P04 replaces this with a list."""
    return game["seasonType"] == "regular" and bool(TITLE_NOTE.search(game.get("notes") or ""))


def _provenance(got: Fetched, path: str, event: datetime, public: datetime, vintage: str) -> dict[str, Any]:
    return {
        "source_id": f"cfbd:{path}",
        "event_time": event,
        "first_public_time": public,
        "raw_hash": got.raw_hash,
        "vintage": vintage,
    }


def game_rows(got: Fetched, vintage: str) -> tuple[pl.DataFrame, pl.DataFrame]:
    """(scheduled rows, final rows) for one /games payload.

    Every game with a kickoff time yields a scheduled row; a completed game with both scores also yields a
    final row. Writing the scheduled rows first makes the final the next correction version.
    """
    scheduled: list[dict[str, Any]] = []
    final: list[dict[str, Any]] = []
    for game in got.json():
        if game["seasonType"] not in SEASON_TYPES:
            continue
        start = _time(game.get("startDate"))
        if start is None:
            raise SourceError(f"cfbd: game {game['id']} has no start time")
        season, title = int(game["season"]), is_title_game(game)
        base = {
            "game_id": f"cfbd-{int(game['id'])}",
            "season": season,
            "week": int(game["week"]),
            "start_utc": start,
            "home_id": team_id(game["homeId"]),
            "away_id": team_id(game["awayId"]),
            "neutral": bool(game["neutralSite"]),
            "site": game.get("venue"),
            "season_type": game["seasonType"],
            "title_game": title,
            "home_div": game.get("homeClassification") or "other",
            "away_div": game.get("awayClassification") or "other",
        }
        known = schedule_public(season, start, game["seasonType"], title)
        scheduled.append(
            base
            | {"home_pts": None, "away_pts": None, "status": "scheduled"}
            | _provenance(got, "/games", start, known, vintage)
        )
        done = bool(game.get("completed"))
        scores = (game.get("homePoints"), game.get("awayPoints"))
        if done and None in scores:
            raise SourceError(f"cfbd: game {game['id']} is marked completed without a score")
        if done:
            final.append(
                base
                | {"home_pts": int(scores[0]), "away_pts": int(scores[1]), "status": "final"}
                | _provenance(got, "/games", start, game_final_public(start), vintage)
            )
    return _frame("games", scheduled), _frame("games", final)


def poll_rows(got: Fetched, kickoffs: Sequence[tuple[int, datetime]], vintage: str) -> pl.DataFrame:
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
    for item in got.json():
        if item["seasonType"] != "regular":
            continue
        week = int(item["week"])
        public = poll_public(week, last, first)
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


def line_rows(got: Fetched, vintage: str) -> pl.DataFrame:
    """Closing lines from one /lines payload, one row per provider and game."""
    rows: list[dict[str, Any]] = []
    for game in got.json():
        start = _time(game.get("startDate"))
        if start is None:
            continue
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
                | _provenance(got, "/lines", start, game_final_public(start), vintage)
            )
    return _frame("lines", rows)
