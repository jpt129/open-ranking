"""The Odds API reader (P02c): credit accounting and line rows."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import polars as pl
import pytest

from cfp.ingest.errors import BudgetExceeded
from cfp.ingest.http import Budget, Fetched, Fetcher, Response, TokenBucket
from cfp.ingest.odds_api import MONTHLY_CREDITS, OddsApi, credit_cost, line_rows
from cfp.store.lake import Lake

from .store_helpers import Clock, frame, game

NOW = datetime(2026, 11, 25, 18, 0, tzinfo=UTC)
KICK = datetime(2026, 11, 28, 17, 0, tzinfo=UTC)
FAKE_KEY = "not-a-real-key"
IDS = {"Texas Longhorns": "T-TEX", "Texas A&M Aggies": "T-TAMU", "Rice Owls": "T-RICE"}


def book(
    key: str, home: str, away: str, spread: float | None = -6.5, total: float | None = 51.5
) -> dict[str, Any]:
    markets: list[dict[str, Any]] = [
        {"key": "h2h", "outcomes": [{"name": home, "price": -240}, {"name": away, "price": 195}]}
    ]
    if spread is not None:
        markets.append(
            {
                "key": "spreads",
                "outcomes": [
                    {"name": away, "price": -110, "point": -spread},
                    {"name": home, "price": -110, "point": spread},
                ],
            }
        )
    if total is not None:
        markets.append(
            {
                "key": "totals",
                "outcomes": [
                    {"name": "Over", "price": -108, "point": total},
                    {"name": "Under", "price": -112, "point": total},
                ],
            }
        )
    return {"key": key, "title": key, "last_update": "2026-11-25T17:58:00Z", "markets": markets}


def event(home: str, away: str, books: list[dict[str, Any]], kick: datetime = KICK) -> dict[str, Any]:
    return {
        "id": "e1",
        "sport_key": "americanfootball_ncaaf",
        "commence_time": kick.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "home_team": home,
        "away_team": away,
        "bookmakers": books,
    }


def fetched(lake: Lake, payload: Any) -> Fetched:
    body = json.dumps(payload).encode()
    return Fetched("odds_api", "https://api.example.test/odds", lake.put_raw(body), body, NOW)


def store(tmp_path: Path) -> tuple[Lake, pl.DataFrame]:
    lake = Lake(tmp_path / "lake", clock=Clock(NOW))
    rows = [game(lake, "g-tex", home_id="T-TEX", away_id="T-TAMU", start_utc=KICK, status="scheduled")]
    lake.append("games", frame("games", rows))
    return lake, lake.scan("games").collect()


def test_credit_cost_matches_the_published_rule() -> None:
    assert credit_cost(["h2h"], ["us"]) == 1
    assert credit_cost(["h2h", "spreads", "totals"], ["us"]) == 3
    assert credit_cost(["h2h"], ["us", "uk", "au"]) == 3
    assert credit_cost(["h2h", "spreads", "totals"], ["us"], historical=True) == 30
    assert MONTHLY_CREDITS <= 150_000  # at most 1% of the shared plan


def client(tmp_path: Path, monthly: int, seen: list[str]) -> OddsApi:
    clock = Clock(NOW)
    lake = Lake(tmp_path / "lake", clock=clock)

    def transport(url: str, headers: Any, timeout: float) -> Response:
        seen.append(url)
        return Response(200, b"[]", {})

    fetcher = Fetcher(
        lake,
        "odds_api",
        "https://api.example.test/v4",
        budget=Budget(tmp_path / "budget.json", clock=clock),
        allowance=monthly,
        bucket=TokenBucket(1000.0, 1000.0),
        secret_params={"apiKey": FAKE_KEY},
        transport=transport,
        clock=clock,
    )
    return OddsApi(fetcher)


def test_credits_are_counted_before_the_request_and_the_cap_holds(tmp_path: Path) -> None:
    seen: list[str] = []
    api = client(tmp_path, monthly=7, seen=seen)
    api.odds()
    api.odds()
    assert api.used() == 6
    with pytest.raises(BudgetExceeded):
        api.odds()  # would be credits 7, 8, 9
    assert len(seen) == 2  # the refused request was never sent
    assert "markets=h2h%2Cspreads%2Ctotals" in seen[0]
    assert "regions=us" in seen[0]
    log = (tmp_path / "lake" / "fetch_log.jsonl").read_text()
    assert FAKE_KEY not in log  # the key never reaches the fetch log


def test_line_rows_one_per_book_with_home_spread_and_capture_time(tmp_path: Path) -> None:
    lake, games = store(tmp_path)
    payload = [
        event(
            "Texas Longhorns",
            "Texas A&M Aggies",
            [
                book("draftkings", "Texas Longhorns", "Texas A&M Aggies"),
                book("fanduel", "Texas Longhorns", "Texas A&M Aggies", spread=-7.0, total=None),
            ],
        )
    ]
    rows, report = line_rows(fetched(lake, payload), IDS, games)
    assert (report.rows, report.games, report.unmatched) == (2, 1, [])
    by_book = {r["provider"]: r for r in rows.iter_rows(named=True)}
    dk = by_book["oddsapi:draftkings"]
    assert (dk["game_id"], dk["ml_home"], dk["ml_away"], dk["spread"], dk["total"]) == (
        "g-tex",
        -240.0,
        195.0,
        -6.5,
        51.5,
    )
    assert (by_book["oddsapi:fanduel"]["spread"], by_book["oddsapi:fanduel"]["total"]) == (-7.0, None)
    assert set(rows["first_public_time"].to_list()) == {NOW}
    assert set(rows["as_of_utc"].to_list()) == {NOW}
    assert set(rows["vintage"].to_list()) == {"live"}
    lake.append(
        "lines",
        rows.with_columns(
            pl.lit(0, dtype=pl.Int32).alias("correction_version"), pl.lit(None).alias("ingest_time")
        ).select(list(lake.spec("lines").schema)),
    )


def test_events_that_cannot_be_tied_to_a_game_are_reported_not_guessed(tmp_path: Path) -> None:
    lake, games = store(tmp_path)
    payload = [
        event("Texas Longhorns", "Nowhere Tech Owls", [book("dk", "Texas Longhorns", "Nowhere Tech Owls")]),
        event("Texas Longhorns", "Rice Owls", [book("dk", "Texas Longhorns", "Rice Owls")]),
        event("Texas A&M Aggies", "Texas Longhorns", [book("dk", "Texas A&M Aggies", "Texas Longhorns")]),
        event("Texas Longhorns", "Texas A&M Aggies", [], kick=datetime(2026, 12, 5, 17, 0, tzinfo=UTC)),
    ]
    rows, report = line_rows(fetched(lake, payload), IDS, games)
    assert rows.height == 0
    assert len(report.unmatched) == 4
    assert "unknown team name" in report.unmatched[0]
    assert "0 games in the store" in report.unmatched[1]


def test_recorded_payload(tmp_path: Path) -> None:
    lake = Lake(tmp_path / "lake", clock=Clock(NOW))
    kick = datetime(2026, 11, 27, 20, 30, tzinfo=UTC)
    rows = [game(lake, "g-sjsu", home_id="T-SJSU", away_id="T-NDSU", start_utc=kick, status="scheduled")]
    lake.append("games", frame("games", rows))
    payload = json.loads(
        (Path(__file__).resolve().parents[1] / "fixtures" / "odds_api_ncaaf_sample.json").read_text()
    )
    ids = {"San Jose State Spartans": "T-SJSU", "North Dakota State Bison": "T-NDSU"}
    lines, report = line_rows(fetched(lake, payload), ids, lake.scan("games").collect())
    assert (report.games, lines.height, len(report.unmatched)) == (1, 2, 1)
    fanduel = lines.filter(pl.col("provider") == "oddsapi:fanduel").row(0, named=True)
    # North Dakota State is the road favourite: the home side gets the points
    assert (fanduel["ml_home"], fanduel["ml_away"], fanduel["spread"], fanduel["total"]) == (
        280.0,
        -350.0,
        8.5,
        39.5,
    )
