"""CollegeFootballData client (P02a). Parsing lives in cfp.ingest.cfbd_normalize."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from cfp.common.env import secret
from cfp.ingest.http import Budget, Fetched, Fetcher, TokenBucket, Transport, urllib_transport
from cfp.store.lake import Lake

SOURCE = "cfbd"
BASE_URL = "https://api.collegefootballdata.com"
MONTHLY_CALLS = 1000
# John, 2026-11-25: keep 300 calls in reserve through 30 Nov 2026 unless the key is upgraded.
RESERVE_UNTIL = datetime(2026, 12, 1, 5, 0, tzinfo=UTC)  # midnight ET, 1 Dec
RESERVE = 300


def allowance(now: datetime, monthly: int = MONTHLY_CALLS) -> int:
    return monthly - RESERVE if now < RESERVE_UNTIL else monthly


class Cfbd:
    def __init__(self, fetcher: Fetcher) -> None:
        self.fetcher = fetcher

    @classmethod
    def from_env(
        cls, lake: Lake, now: datetime, transport: Transport = urllib_transport, monthly: int = MONTHLY_CALLS
    ) -> Cfbd:
        key = secret("CFBD_API_KEY").removeprefix("Bearer ").strip()  # tolerate a pasted "Bearer " prefix
        fetcher = Fetcher(
            lake,
            SOURCE,
            BASE_URL,
            budget=Budget(lake.root / "budget.json"),
            allowance=allowance(now, monthly),
            bucket=TokenBucket(rate=2.0, capacity=2.0),
            headers={"Authorization": f"Bearer {key}", "Accept": "application/json"},
            transport=transport,
        )
        return cls(fetcher)

    def _get(self, path: str, reuse: bool, **params: Any) -> Fetched:
        return self.fetcher.get(path, {k: v for k, v in params.items() if v is not None}, reuse=reuse)

    def info(self) -> Fetched:
        return self._get("/info", False)

    def games(self, year: int, season_type: str, week: int | None = None, reuse: bool = False) -> Fetched:
        return self._get("/games", reuse, year=year, seasonType=season_type, week=week)

    def teams(self, year: int, reuse: bool = False) -> Fetched:
        return self._get("/teams", reuse, year=year)

    def fbs_teams(self, year: int, reuse: bool = False) -> Fetched:
        return self._get("/teams/fbs", reuse, year=year)

    def conferences(self, reuse: bool = False) -> Fetched:
        return self._get("/conferences", reuse)

    def calendar(self, year: int, reuse: bool = False) -> Fetched:
        return self._get("/calendar", reuse, year=year)

    def rankings(self, year: int, season_type: str, week: int | None = None, reuse: bool = False) -> Fetched:
        return self._get("/rankings", reuse, year=year, seasonType=season_type, week=week)

    def lines(self, year: int, season_type: str, week: int | None = None, reuse: bool = False) -> Fetched:
        return self._get("/lines", reuse, year=year, seasonType=season_type, week=week)
