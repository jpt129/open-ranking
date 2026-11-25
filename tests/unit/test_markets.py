"""Kalshi and Polymarket readers (P02d). Read-only: listings, order books and venue price history."""

from __future__ import annotations

import json
import re
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import polars as pl
import pytest

from cfp.ingest.errors import SourceError
from cfp.ingest.http import Budget, Fetcher, Response, TokenBucket
from cfp.markets import readers
from cfp.markets.snapshot import Venues, history, load_events, snapshot
from cfp.store.lake import Lake

from .store_helpers import Clock

NOW = datetime(2026, 11, 25, 18, 0, tzinfo=UTC)
ROOT = Path(__file__).resolve().parents[2]
FIX = ROOT / "tests" / "fixtures"
ND_TOKEN = "62114091072138831244471139109132311412024028335938216863576747342572512750405"


def fixture(name: str) -> Any:
    return json.loads((FIX / name).read_text())


def test_kalshi_listing_reads_best_quotes_and_treats_an_empty_side_as_no_quote() -> None:
    listed = {c.ticker: c for c in readers.kalshi_listing(fixture("kalshi_events_playoff.json"))}
    assert len(listed) == 5
    nd = listed["KXNCAAFPLAYOFF-26-ND"]
    assert (nd.event_ref, nd.series, nd.outcome_name, nd.status) == (
        "KXNCAAFPLAYOFF-26",
        "KXNCAAFPLAYOFF",
        "Notre Dame",
        "active",
    )
    assert (nd.quote.bid, nd.quote.ask, nd.quote.bid_size, nd.quote.ask_size) == (0.98, 0.99, 4.08, 21228.41)
    assert nd.close_utc == datetime(2026, 12, 29, 15, 0, tzinfo=UTC)
    osu = listed["KXNCAAFPLAYOFF-26-OSU"].quote
    assert (osu.bid, osu.bid_size, osu.ask) == (None, None, 0.02)  # a 0.00 bid with no size is no bid


def test_kalshi_book_turns_the_best_no_bid_into_the_yes_ask() -> None:
    quote = readers.kalshi_book(fixture("kalshi_orderbook_nd.json"))
    assert (quote.bid, quote.bid_size, quote.ask, quote.ask_size) == (0.98, 4.08, 0.99, 21228.41)
    empty = readers.kalshi_book({"orderbook_fp": {"yes_dollars": [], "no_dollars": []}})
    assert (empty.bid, empty.ask, empty.bid_size, empty.ask_size) == (None, None, None, None)


def test_kalshi_candles() -> None:
    candles = readers.kalshi_candles(fixture("kalshi_candles_nd.json"))
    assert len(candles) == 3
    first = candles[0]
    assert first.ts == datetime.fromtimestamp(1795608000, UTC)
    assert (first.quote.bid, first.quote.ask, first.quote.last) == (0.98, 0.99, None)  # no trade in the hour


def test_polymarket_listing_uses_the_yes_token() -> None:
    listed = readers.polymarket_listing(fixture("polymarket_event_playoffs.json"))
    assert [c.outcome_name for c in listed] == ["Notre Dame", "Ohio St.", "Miami (FL)"]
    nd = listed[0]
    assert (nd.ticker, nd.event_ref, nd.status) == (ND_TOKEN, "948140", "active")
    assert (nd.quote.bid, nd.quote.ask, nd.quote.last, nd.quote.bid_size) == (0.963, 0.997, 0.982, None)


def test_polymarket_book_and_history() -> None:
    quote = readers.polymarket_book(fixture("polymarket_book_nd.json"))
    assert (quote.bid, quote.bid_size, quote.ask, quote.ask_size, quote.last) == (
        0.963,
        1200.0,
        0.997,
        100.3,
        0.982,
    )
    points = readers.polymarket_history(fixture("polymarket_history_nd.json"))
    assert len(points) == 7
    assert (points[0].ts, points[0].quote.last, points[0].quote.bid) == (
        datetime.fromtimestamp(1795604429, UTC),
        0.98,
        None,
    )


def test_bad_payloads_raise() -> None:
    event = fixture("polymarket_event_playoffs.json")
    event[0]["markets"][0]["outcomes"] = '["Over", "Under"]'
    with pytest.raises(SourceError, match="Yes/No"):
        readers.polymarket_listing(event)
    listing = fixture("kalshi_events_playoff.json")
    listing["events"][0]["markets"][0]["yes_ask_dollars"] = "1.2000"
    with pytest.raises(SourceError, match=r"outside 0\.\.1"):
        readers.kalshi_listing(listing)
    listing = fixture("kalshi_events_playoff.json")
    listing["cursor"] = "more"
    with pytest.raises(SourceError, match="more pages"):
        readers.kalshi_listing(listing)
    listing["cursor"] = ""
    listing["events"][0]["markets"][0]["market_type"] = "scalar"
    with pytest.raises(SourceError, match="binary"):
        readers.kalshi_listing(listing)


# --- snapshot ------------------------------------------------------------------------------------------


REVISED: dict[str, Path] = {}
EVENTS = (
    "venue,ref,season,question,depth,note\n"
    "kalshi,KXNCAAFPLAYOFF,2026,make_playoff,yes,\n"
    "polymarket,948140,2026,make_playoff,yes,\n"
)
ALIASES = "alias,team_id\nNotre Dame,cfbd-87\nOhio St.,cfbd-194\nTexas,cfbd-251\nMiami (FL),cfbd-2390\n"


def world(tmp_path: Path, clock: Clock) -> tuple[Lake, Venues, Path, list[str]]:
    lake = Lake(tmp_path / "lake", clock=clock)
    data = tmp_path / "data"
    data.mkdir()
    (data / "market_events.csv").write_text(EVENTS)
    (data / "aliases_kalshi.csv").write_text(ALIASES)
    (data / "aliases_polymarket.csv").write_text(ALIASES)
    urls: list[str] = []
    bodies = {
        "gamma.example.test/events": "polymarket_event_playoffs.json",
        "/events?": "kalshi_events_playoff.json",
        "/orderbook": "kalshi_orderbook_nd.json",
        "/candlesticks": "kalshi_candles_nd.json",
        "/book?": "polymarket_book_nd.json",
        "/prices-history": "polymarket_history_nd.json",
    }

    def transport(url: str, headers: Any, timeout: float) -> Response:
        urls.append(url)
        if "KXEMPTY" in url:
            return Response(200, b'{"events": [], "cursor": ""}', {})
        if "/candlesticks" in url and REVISED:
            return Response(200, REVISED["path"].read_bytes(), {})
        name = next(v for k, v in bodies.items() if k in url)
        return Response(200, (FIX / name).read_bytes(), {})

    def fetcher(source: str, base: str) -> Fetcher:
        return Fetcher(
            lake,
            source,
            base,
            budget=Budget(tmp_path / "budget.json", clock=clock),
            allowance=100_000,
            bucket=TokenBucket(1000.0, 1000.0),
            transport=transport,
            clock=clock,
        )

    venues = Venues(
        kalshi=fetcher("kalshi", "https://kalshi.example.test/v2"),
        gamma=fetcher("polymarket_gamma", "https://gamma.example.test"),
        clob=fetcher("polymarket_clob", "https://clob.example.test"),
    )
    return lake, venues, data, urls


def test_snapshot_writes_catalogue_top_quotes_and_books_at_capture_time(tmp_path: Path) -> None:
    clock = Clock(NOW)
    lake, venues, data, urls = world(tmp_path, clock)
    report = snapshot(lake, venues, load_events(data / "market_events.csv"), data)
    assert all(not re.search(r"order(s)?\b(?!book)|portfolio", u) for u in urls)

    catalogue = lake.scan("market_catalogue").collect()
    assert catalogue.height == 5 + 3
    by_name = {(r["venue"], r["outcome_name"]): r for r in catalogue.iter_rows(named=True)}
    assert by_name[("kalshi", "Notre Dame")]["team_id"] == "cfbd-87"
    assert by_name[("polymarket", "Miami (FL)")]["team_id"] == "cfbd-2390"
    assert (
        by_name[("kalshi", "Miami (OH)")]["team_id"] is None
    )  # not on the alias list: left empty, never guessed
    assert report.unmapped == {("kalshi", "Miami (OH)")}
    assert set(catalogue["question"].to_list()) == {"make_playoff"}

    quotes = lake.scan("market_quotes").collect()
    assert quotes.group_by("venue", "kind").len().sort("venue", "kind").rows() == [
        ("kalshi", "book", 5),
        ("kalshi", "top", 5),
        ("polymarket", "book", 3),
        ("polymarket", "top", 3),
    ]
    assert set(quotes["vintage"].to_list()) == {"live"}
    assert set(quotes["first_public_time"].to_list()) == {NOW}  # a quote is public when we captured it
    assert set(quotes["ts_utc"].to_list()) == {NOW}
    for raw_hash in quotes["raw_hash"].unique().to_list():
        assert lake.has_raw(raw_hash)
    book = quotes.filter((pl.col("kind") == "book") & (pl.col("ticker") == ND_TOKEN)).row(0, named=True)
    assert (book["bid"], book["bid_size"], book["ask"], book["ask_size"]) == (0.963, 1200.0, 0.997, 100.3)

    # invisible before the capture, visible after, in live mode
    assert lake.as_of("market_quotes", NOW - timedelta(seconds=1), "live").frame.height == 0
    assert lake.as_of("market_quotes", NOW, "live").frame.height == 16

    clock.now = NOW + timedelta(minutes=30)
    again = snapshot(lake, venues, load_events(data / "market_events.csv"), data, depth=False)
    assert (again.catalogue_new, again.catalogue_changed, again.clean) == (0, 0, False)
    assert lake.scan("market_quotes").collect().height == 16 + 8


def test_history_rows_are_public_at_their_own_time_and_reruns_add_nothing(tmp_path: Path) -> None:
    clock = Clock(NOW)
    lake, venues, data, _ = world(tmp_path, clock)
    events = load_events(data / "market_events.csv")
    snapshot(lake, venues, events, data, depth=False)
    before = lake.scan("market_quotes").collect().height
    history(lake, venues, events, hours=6)
    candles = lake.scan("market_quotes").filter(pl.col("kind") == "candle").collect()
    assert candles.height == 5 * 3 + 3 * 7
    assert (candles["first_public_time"] == candles["ts_utc"]).all()
    assert set(candles["vintage"].to_list()) == {"reconstructed"}  # reported by the venue after the fact
    history(lake, venues, events, hours=6)
    assert lake.scan("market_quotes").collect().height == before + candles.height


def test_events_file_is_validated(tmp_path: Path) -> None:
    path = tmp_path / "events.csv"
    path.write_text("venue,ref,season,question,depth,note\nbetfair,X,2026,make_playoff,yes,\n")
    with pytest.raises(SourceError, match="venue"):
        load_events(path)
    path.write_text("venue,ref,season,question,depth,note\nkalshi,X,2026,who_knows,yes,\n")
    with pytest.raises(SourceError, match="question"):
        load_events(path)


def test_repo_events_and_alias_files_load() -> None:
    events = load_events(ROOT / "data" / "market_events.csv")
    assert {e.venue for e in events} == {"kalshi", "polymarket"}
    assert any(e.question == "make_playoff" and e.depth for e in events)


TRADING = re.compile(
    r"portfolio|/orders|create_order|private_key|wallet|signature|api[-_]?key|authori[sz]ation", re.I
)


def test_no_trading_or_account_code_anywhere_in_the_markets_package() -> None:
    for path in (ROOT / "src" / "cfp" / "markets").rglob("*.py"):
        assert not TRADING.search(path.read_text()), path


@pytest.mark.parametrize("package", ["forecast", "open_ranking", "snapshot", "rules"])
def test_predictors_never_name_the_market_tables(package: str) -> None:
    for path in (ROOT / "src" / "cfp" / package).rglob("*.py"):
        text = path.read_text()
        assert "market_quotes" not in text, path
        assert "market_catalogue" not in text, path


def test_long_polymarket_history_is_fetched_in_windows_of_a_week(tmp_path: Path) -> None:
    lake, venues, data, urls = world(tmp_path, Clock(NOW))
    history(lake, venues, load_events(data / "market_events.csv"), hours=24 * 20)
    assert sum("/prices-history" in u for u in urls) == 3 * 3  # three contracts, three windows each
    assert sum("/candlesticks" in u for u in urls) == 5
    candles = lake.scan("market_quotes").filter(pl.col("kind") == "candle").collect()
    assert candles.height == 5 * 3 + 3 * 7  # a point returned by two windows is stored once


def test_a_price_of_one_is_no_offer_and_a_price_of_zero_is_no_bid() -> None:
    event = fixture("polymarket_event_playoffs.json")
    event[0]["markets"][0] |= {"bestBid": 0, "bestAsk": 1}
    quote = readers.polymarket_listing(event)[0].quote
    assert (quote.bid, quote.ask) == (None, None)
    candles = fixture("kalshi_candles_nd.json")
    candles["candlesticks"][0]["yes_ask"]["close_dollars"] = "1.0000"
    candles["candlesticks"][0]["yes_bid"]["close_dollars"] = "0.0000"
    first = readers.kalshi_candles(candles)[0].quote
    assert (first.bid, first.ask) == (None, None)
    listing = fixture("kalshi_events_playoff.json")
    texas = next(c for c in readers.kalshi_listing(listing) if c.outcome_name == "Texas")
    assert (texas.quote.bid, texas.quote.ask, texas.quote.ask_size) == (0.98, None, None)
    del listing["events"][0]["markets"][0]["yes_ask_size_fp"]
    with pytest.raises(KeyError):  # without sizes an empty side cannot be told from a quote
        readers.kalshi_listing(listing)


def test_an_event_with_no_contracts_is_reported_and_closed_contracts_get_no_quote(tmp_path: Path) -> None:
    lake, venues, data, _ = world(tmp_path, Clock(NOW))
    (data / "market_events.csv").write_text(EVENTS + "kalshi,KXEMPTY,2026,champion,no,\n")
    events = load_events(data / "market_events.csv")
    report = snapshot(lake, venues, events, data, depth=False)
    assert report.empty == ["kalshi:KXEMPTY"]
    assert not report.clean


def test_a_revised_candle_is_public_when_we_saw_the_revision(tmp_path: Path) -> None:
    clock = Clock(NOW)
    lake, venues, data, _ = world(tmp_path, clock)
    events = [e for e in load_events(data / "market_events.csv") if e.venue == "kalshi"]
    history(lake, venues, events, hours=6)
    revised = fixture("kalshi_candles_nd.json")
    revised["candlesticks"][0]["yes_bid"]["close_dollars"] = "0.9000"
    (tmp_path / "revised.json").write_text(json.dumps(revised))
    REVISED["path"] = tmp_path / "revised.json"
    try:
        clock.now = NOW + timedelta(hours=2)
        history(lake, venues, events, hours=6)
    finally:
        REVISED.clear()
    first_ts = datetime.fromtimestamp(1795608000, UTC)
    rows = lake.scan("market_quotes").filter(pl.col("ts_utc") == first_ts).collect()
    changed = rows.filter(pl.col("correction_version") == 1)
    assert changed.height == 5
    assert set(changed["first_public_time"].to_list()) == {NOW + timedelta(hours=2)}
    before = lake.as_of("market_quotes", NOW + timedelta(hours=1), "replay").frame.filter(
        pl.col("ts_utc") == first_ts
    )
    assert set(before["bid"].to_list()) == {0.98}
