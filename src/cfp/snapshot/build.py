"""The dated season snapshot the Open Ranking scores (OR-07).

`build_snapshot` reads games, teams and membership through the Open Ranking's view at a cutoff and returns
the completed regular-season and conference-title games involving an FBS team, each with both sides'
division and conference on the game date, plus a log of everything left out and why. It never guesses:
a game that looks like a forfeit and is not on the hand-verified list, a classification that disagrees with
the membership table, or a title game that cannot be found, stops the build.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any

import polars as pl

from cfp.snapshot.data import Forfeit, TitleGame, Unplayed
from cfp.store.views import OpenRankingView

FORFEIT_SCORES = frozenset({(0, 0), (1, 0), (0, 1), (2, 0), (0, 2)})
TITLE_DAY_SLACK = timedelta(days=1)  # a late kickoff falls on the next UTC day
TITLE_OVERDUE = timedelta(days=3)
COLUMNS = (
    "game_id",
    "season",
    "week",
    "start_utc",
    "home_id",
    "away_id",
    "home_pts",
    "away_pts",
    "winner_id",
    "neutral",
    "site",
    "title_game",
    "home_div",
    "away_div",
    "home_conf",
    "away_conf",
    "ordinary_fbs",
    "forfeit",
    "margin_excluded",
    "correction_version",
    "raw_hash",
)
OMISSION_SCHEMA = {
    "game_id": pl.String(),
    "season": pl.Int32(),
    "day": pl.Date(),
    "home": pl.String(),
    "away": pl.String(),
    "reason": pl.String(),
    "detail": pl.String(),
}


class SnapshotBlocked(RuntimeError):
    """The inputs need a person's decision before a snapshot can be built."""


@dataclass(frozen=True)
class Snapshot:
    season: int
    cutoff: datetime
    mode: str
    games: pl.DataFrame
    omissions: pl.DataFrame
    snapshot_hash: str


def _hash(games: pl.DataFrame) -> str:
    """SHA-256 of the rows in game_id order, one canonical JSON object per line."""
    digest = hashlib.sha256()
    for row in games.sort("game_id").iter_rows(named=True):
        plain = {k: (v.isoformat() if isinstance(v, datetime) else v) for k, v in row.items()}
        digest.update(json.dumps(plain, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode())
        digest.update(b"\n")
    return digest.hexdigest()


def _with_membership(games: pl.DataFrame, membership: pl.DataFrame) -> pl.DataFrame:
    """Attach each side's division and conference in force on the game date; stop on any gap or clash."""
    day = games["start_utc"].dt.date()
    out = games.with_columns(day.alias("_day"))
    for side in ("home", "away"):
        joined = out.join(
            membership.select(
                pl.col("team_id").alias(f"{side}_id"),
                "valid_from",
                "valid_to",
                pl.col("division").alias(f"_{side}_div"),
                pl.col("conference_id").alias(f"{side}_conf"),
            ),
            on=f"{side}_id",
            how="left",
        ).filter(
            pl.col("valid_from").is_null()
            | (
                (pl.col("valid_from") <= pl.col("_day"))
                & (pl.col("valid_to").is_null() | (pl.col("valid_to") >= pl.col("_day")))
            )
        )
        counts = joined.group_by("game_id").len()
        covered = joined.filter(pl.col(f"_{side}_div").is_not_null())
        if covered.height != out.height or counts.filter(pl.col("len") != 1).height:
            missing = sorted(set(out["game_id"]) - set(covered["game_id"]))[:5]
            raise SnapshotBlocked(f"membership does not cover the {side} team on the game date for {missing}")
        clash = joined.filter(pl.col(f"_{side}_div") != pl.col(f"{side}_div"))
        if clash.height:
            row = clash.row(0, named=True)
            raise SnapshotBlocked(
                f"{row['game_id']}: the game row classes {row[f'{side}_id']} as {row[f'{side}_div']}, "
                f"the membership table as {row[f'_{side}_div']}; ask before building"
            )
        out = joined.drop("valid_from", "valid_to", f"_{side}_div")
    return out.drop("_day")


def _title_ids(
    games: pl.DataFrame, teams: pl.DataFrame, title_games: Sequence[TitleGame], season: int, cutoff: datetime
) -> set[str]:
    """Game ids of the listed title games. A named, overdue title game absent from the data blocks."""
    ids_by_name: dict[str, str] = dict(teams.select("name", "team_id").iter_rows())
    found: set[str] = set()
    for title in (t for t in title_games if t.season == season and t.team_a):
        unknown = [name for name in (title.team_a, title.team_b) if name not in ids_by_name]
        if unknown:
            raise SnapshotBlocked(f"title games: no team is named {unknown} ({title.conference} {season})")
        pair = {ids_by_name[title.team_a], ids_by_name[title.team_b]}
        day = pl.col("start_utc").dt.date()
        match = games.filter(
            pl.col("home_id").is_in(pair)
            & pl.col("away_id").is_in(pair)
            & (day >= title.day - TITLE_DAY_SLACK)
            & (day <= title.day + TITLE_DAY_SLACK)
        )
        if match.height > 1:
            raise SnapshotBlocked(f"title games: {title.conference} {season} matches {match.height} games")
        if match.height == 1:
            found.add(match["game_id"][0])
        elif cutoff.date() > title.day + TITLE_OVERDUE:
            raise SnapshotBlocked(
                f"title games: the {season} {title.conference} game is listed, not in the data"
            )
    return found


def _omission(row: dict[str, Any], reason: str, detail: str = "") -> dict[str, Any]:
    start = row["start_utc"]
    return {
        "game_id": row["game_id"],
        "season": row["season"],
        "day": start.date() if start is not None else None,
        "home": row["home_id"],
        "away": row["away_id"],
        "reason": reason,
        "detail": detail,
    }


def build_snapshot(
    view: OpenRankingView,
    season: int,
    *,
    title_games: Sequence[TitleGame],
    forfeits: Sequence[Forfeit] = (),
    unplayed: Sequence[Unplayed] = (),
) -> Snapshot:
    """The season's scoreable games as public at the view's cutoff, with the log of omissions."""
    games = view.table("games", season).filter(pl.col("season") == season)
    teams = view.table("teams")
    membership = view.table("membership")
    title_ids = _title_ids(games, teams, title_games, season, view.t)
    forfeit_by_id = {f.game_id: f for f in forfeits}

    flagged = set(games.filter(pl.col("title_game"))["game_id"]) - title_ids
    listed_season = any(t.season == season and t.team_a for t in title_games)
    if flagged and listed_season:
        raise SnapshotBlocked(f"the source flags {sorted(flagged)} as title games; they are not on the list")

    kept: list[dict[str, Any]] = []
    omitted: list[dict[str, Any]] = []
    fbs = {"fbs"}
    for row in games.iter_rows(named=True):
        is_title = row["game_id"] in title_ids
        if row["home_div"] not in fbs and row["away_div"] not in fbs:
            omitted.append(_omission(row, "no_fbs_team"))
        elif row["status"] != "final":
            omitted.append(_omission(row, "not_final_at_cutoff", row["status"]))
        elif row["season_type"] != "regular" and not is_title:
            omitted.append(_omission(row, "postseason", row["season_type"]))
        else:
            kept.append(row | {"title_game": is_title})

    rows: list[dict[str, Any]] = []
    for row in kept:
        home, away = row["home_pts"], row["away_pts"]
        if home is None or away is None:
            raise SnapshotBlocked(f"{row['game_id']}: final with no score")
        forfeit = forfeit_by_id.get(row["game_id"])
        if forfeit is None and (home, away) in FORFEIT_SCORES:
            raise SnapshotBlocked(
                f"{row['game_id']}: a {home}-{away} final looks like a forfeit and is not on the list; "
                "verify it by hand and record it in docs/DATA_GAPS.md"
            )
        if forfeit is not None:
            if forfeit.winner_id not in (row["home_id"], row["away_id"]):
                raise SnapshotBlocked(f"{row['game_id']}: the forfeit list names a winner who did not play")
            winner = forfeit.winner_id
        elif home == away:
            raise SnapshotBlocked(f"{row['game_id']}: a {home}-{away} tie is not a result")
        else:
            winner = row["home_id"] if home > away else row["away_id"]
        both_fbs = row["home_div"] == "fbs" and row["away_div"] == "fbs"
        rows.append(
            row
            | {
                "winner_id": winner,
                "forfeit": forfeit is not None,
                "margin_excluded": forfeit is not None,
                "ordinary_fbs": both_fbs and forfeit is None,
            }
        )
    extra = {
        "winner_id": pl.String(),
        "forfeit": pl.Boolean(),
        "margin_excluded": pl.Boolean(),
        "ordinary_fbs": pl.Boolean(),
    }
    frame = pl.DataFrame(rows, schema={**dict(games.schema), **extra})
    if frame.height:
        frame = _with_membership(frame, membership)
    else:
        empty = pl.lit(None, dtype=pl.String)
        frame = frame.with_columns(empty.alias("home_conf"), empty.alias("away_conf"))
    frame = frame.select(COLUMNS).sort("game_id")

    for game in unplayed:
        if game.season == season and game.day <= view.t.date():
            omitted.append(
                {
                    "game_id": None,
                    "season": season,
                    "day": game.day,
                    "home": game.home,
                    "away": game.away,
                    "reason": game.status,
                    "detail": game.source_url,
                }
            )
    omissions = pl.DataFrame(omitted, schema=OMISSION_SCHEMA).sort("reason", "day", "home", "away")
    return Snapshot(season, view.t, view.mode, frame, omissions, _hash(frame))
