"""The Odds API reader (P02c): current college-football game lines from many books, into `lines`.

The key is shared with other projects, so this client keeps its own monthly credit cap far below the plan's.
Credits are counted before each request: one per market per region, ten times that for historical snapshots.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Any

import polars as pl

from cfp.common.env import secret
from cfp.ingest.errors import SourceError
from cfp.ingest.http import Budget, Fetched, Fetcher, TokenBucket, Transport, urllib_transport
from cfp.store.lake import Lake
from cfp.store.schemas import TABLES

SOURCE = "odds_api"
BASE_URL = "https://api.the-odds-api.com/v4"
SPORT = "americanfootball_ncaaf"
MARKETS = ("h2h", "spreads", "totals")
REGIONS = ("us",)
# John, 2026-11-25: the 15M-credit plan is shared with other projects; be realistic. This project's own cap:
MONTHLY_CREDITS = 50_000
HISTORICAL_MULTIPLIER = 10
KICKOFF_SLACK = timedelta(hours=36)
PROVIDED = ("correction_version", "ingest_time")


def credit_cost(markets: Sequence[str], regions: Sequence[str], historical: bool = False) -> int:
    return len(markets) * len(regions) * (HISTORICAL_MULTIPLIER if historical else 1)


class OddsApi:
    def __init__(self, fetcher: Fetcher) -> None:
        self.fetcher = fetcher

    @classmethod
    def from_env(
        cls, lake: Lake, transport: Transport = urllib_transport, monthly: int = MONTHLY_CREDITS
    ) -> OddsApi:
        fetcher = Fetcher(
            lake,
            SOURCE,
            BASE_URL,
            budget=Budget(lake.root / "budget.json"),
            allowance=monthly,
            bucket=TokenBucket(rate=1.0, capacity=2.0),
            headers={"Accept": "application/json"},
            secret_params={"apiKey": secret("ODDS_API_KEY").strip()},
            transport=transport,
        )
        return cls(fetcher)

    def _charge(self, credits: int) -> None:
        """Count the credits a request will cost beyond the one the fetcher counts itself, before sending."""
        for _ in range(credits - 1):
            self.fetcher.budget.spend(SOURCE, self.fetcher.allowance, "credits")

    def used(self) -> int:
        return self.fetcher.budget.used(SOURCE)

    def odds(self, markets: Sequence[str] = MARKETS, regions: Sequence[str] = REGIONS) -> Fetched:
        """Current lines for every listed game."""
        self._charge(credit_cost(markets, regions))
        params = {"markets": ",".join(markets), "regions": ",".join(regions), "oddsFormat": "american"}
        return self.fetcher.get(f"/sports/{SPORT}/odds", params)


@dataclass
class OddsReport:
    rows: int = 0
    games: int = 0
    in_play: int = 0  # events already kicked off at capture; their prices are not pregame lines
    unmatched: list[str] = field(default_factory=list)  # events we could not tie to a game in the store


def _point(market: Mapping[str, Any], name: str) -> float | None:
    for outcome in market["outcomes"]:
        if outcome["name"] == name and outcome.get("point") is not None:
            return float(outcome["point"])
    return None


def _price(market: Mapping[str, Any], name: str) -> float | None:
    for outcome in market["outcomes"]:
        if outcome["name"] == name:
            return float(outcome["price"])
    return None


def line_rows(
    got: Fetched, team_ids: Mapping[str, str], games: pl.DataFrame, vintage: str = "live"
) -> tuple[pl.DataFrame, OddsReport]:
    """One row per book and game from an /odds payload of pregame lines.

    `team_ids` maps the names the API prints to team ids; `games` is the store's games table (any number of
    versions per game). An event is tied to the one game between the same two teams that kicks off within
    36 hours of the API's commence time, whichever side each source calls home. The spread and the home
    moneyline are the stored home team's, as in the CFBD rows. Events already under way are skipped. Rows
    are public at the capture time.
    """
    payload = got.json()
    events = payload["data"] if isinstance(payload, dict) else payload
    stamp = got.fetched_at
    latest = games.sort("correction_version").unique("game_id", keep="last")
    report = OddsReport()
    rows: list[dict[str, Any]] = []
    for event in events:
        names = (event["home_team"], event["away_team"])
        label = f"{names[1]} at {names[0]} ({event['commence_time']})"
        kickoff = datetime.fromisoformat(event["commence_time"].replace("Z", "+00:00"))
        if kickoff <= stamp:
            report.in_play += 1
            continue
        name_by_id = {team_ids[name]: name for name in names if name in team_ids}
        if len(name_by_id) != 2:
            report.unmatched.append(f"{label}: unknown team name")
            continue
        pair = list(name_by_id)
        match = latest.filter(
            pl.col("home_id").is_in(pair)
            & pl.col("away_id").is_in(pair)
            & (pl.col("start_utc") >= kickoff - KICKOFF_SLACK)
            & (pl.col("start_utc") <= kickoff + KICKOFF_SLACK)
        )
        if match.height != 1:
            report.unmatched.append(f"{label}: {match.height} games in the store")
            continue
        report.games += 1
        game = match.row(0, named=True)
        home_name, away_name = name_by_id[game["home_id"]], name_by_id[game["away_id"]]
        for book in event.get("bookmakers") or []:
            markets = {m["key"]: m for m in book["markets"]}
            values = {
                "ml_home": _price(markets["h2h"], home_name) if "h2h" in markets else None,
                "ml_away": _price(markets["h2h"], away_name) if "h2h" in markets else None,
                "spread": _point(markets["spreads"], home_name) if "spreads" in markets else None,
                "total": _point(markets["totals"], "Over") if "totals" in markets else None,
            }
            if all(value is None for value in values.values()):
                continue
            rows.append(
                {
                    "provider": f"oddsapi:{book['key']}",
                    "game_id": game["game_id"],
                    "as_of_utc": stamp,
                    "season": game["season"],
                    **values,
                    "source_id": "odds_api:/odds",
                    "event_time": stamp,
                    "first_public_time": stamp,
                    "raw_hash": got.raw_hash,
                    "vintage": vintage,
                }
            )
    if len({(r["provider"], r["game_id"]) for r in rows}) != len(rows):
        raise SourceError("odds_api: a book quotes the same game twice in one payload")
    schema = {k: v for k, v in TABLES["lines"].schema.items() if k not in PROVIDED}
    report.rows = len(rows)
    return pl.DataFrame(rows, schema=schema), report
