"""Capture market listings, order books and venue price history into the lake (P02d). Evaluation only.

A quote is public when we captured it, so its first-public time is the capture time and it can never be
visible to an issue cut before the capture. History rows carry the venue's own period time and are always
vintage "reconstructed": the venue reported them after the fact, and only captured quotes count as live.
"""

from __future__ import annotations

import csv
from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

import polars as pl

from cfp.ingest.cfp_releases import load_aliases
from cfp.ingest.errors import SourceError
from cfp.ingest.http import Fetched, Fetcher
from cfp.ingest.upsert import upsert
from cfp.markets import readers
from cfp.markets.readers import Contract, Quote
from cfp.store.lake import Lake
from cfp.store.schemas import TABLES

KALSHI = "https://api.elections.kalshi.com/trade-api/v2"
POLYMARKET_GAMMA = "https://gamma-api.polymarket.com"
POLYMARKET_CLOB = "https://clob.polymarket.com"
VENUES = ("kalshi", "polymarket")
QUESTIONS = (
    "make_playoff",
    "top4_seed",
    "seed",
    "quarterfinal",
    "semifinal",
    "finalist",
    "champion",
    "poll_rank",
    "poll_top",
)
PROVIDED = ("correction_version", "ingest_time")
CANDLE_MINUTES = 60
MAX_WINDOW = timedelta(days=7)


@dataclass(frozen=True)
class Venues:
    kalshi: Fetcher
    gamma: Fetcher  # Polymarket listings
    clob: Fetcher  # Polymarket books and history


@dataclass(frozen=True)
class EventRef:
    venue: str
    ref: str  # Kalshi series ticker, or Polymarket event id
    season: int
    question: str
    depth: bool  # fetch each contract's order book in a snapshot, and its history


@dataclass
class Report:
    catalogue_new: int = 0
    catalogue_changed: int = 0
    quotes: int = 0
    unmapped: set[tuple[str, str]] = field(default_factory=set)
    empty: list[str] = field(default_factory=list)  # listed events that returned no contract

    @property
    def clean(self) -> bool:
        return not self.unmapped and not self.empty


def load_events(path: Path | str) -> list[EventRef]:
    """The hand-kept list of events to capture."""
    out: list[EventRef] = []
    with Path(path).open(newline="") as handle:
        for row in csv.DictReader(handle):
            if row["venue"] not in VENUES:
                raise SourceError(f"market events: unknown venue {row['venue']!r}")
            if row["question"] not in QUESTIONS:
                raise SourceError(f"market events: unknown question {row['question']!r} for {row['ref']}")
            if row["depth"] not in ("yes", "no"):
                raise SourceError(f"market events: depth must be yes or no for {row['ref']}")
            out.append(
                EventRef(row["venue"], row["ref"], int(row["season"]), row["question"], row["depth"] == "yes")
            )
    if len({(e.venue, e.ref) for e in out}) != len(out):
        raise SourceError("market events: an event is listed twice")
    return out


def listing(venues: Venues, event: EventRef) -> tuple[Fetched, list[Contract]]:
    if event.venue == "kalshi":
        params = {"series_ticker": event.ref, "status": "open", "with_nested_markets": "true", "limit": 200}
        got = venues.kalshi.get("/events", params)
        return got, readers.kalshi_listing(got.json())
    got = venues.gamma.get("/events", {"id": event.ref})
    return got, readers.polymarket_listing(got.json())


def _frame(table: str, rows: list[dict[str, Any]]) -> pl.DataFrame:
    schema = {k: v for k, v in TABLES[table].schema.items() if k not in PROVIDED}
    return pl.DataFrame(rows, schema=schema)


def _quote_row(
    contract: Contract,
    season: int,
    kind: str,
    ts: datetime,
    quote: Quote,
    got: Fetched,
    vintage: str = "live",
) -> dict[str, Any]:
    return {
        "venue": contract.venue,
        "ticker": contract.ticker,
        "ts_utc": ts,
        "kind": kind,
        "season": season,
        "bid": quote.bid,
        "ask": quote.ask,
        "bid_size": quote.bid_size,
        "ask_size": quote.ask_size,
        "last": quote.last,
        "source_id": f"{got.source}:{kind}",
        "event_time": ts,
        "first_public_time": ts,
        "raw_hash": got.raw_hash,
        "vintage": vintage,
    }


def _book(venues: Venues, contract: Contract) -> tuple[Fetched, Quote]:
    if contract.venue == "kalshi":
        got = venues.kalshi.get(f"/markets/{contract.ticker}/orderbook")
        return got, readers.kalshi_book(got.json())
    got = venues.clob.get("/book", {"token_id": contract.ticker})
    return got, readers.polymarket_book(got.json())


def snapshot(
    lake: Lake, venues: Venues, events: Sequence[EventRef], data_dir: Path, depth: bool = True
) -> Report:
    """One capture of every listed event: catalogue, best quotes, and order books where asked for."""
    aliases = {venue: load_aliases(data_dir / f"aliases_{venue}.csv") for venue in VENUES}
    report = Report()
    for event in events:
        got, contracts = listing(venues, event)
        catalogue, quotes = [], []
        for contract in contracts:
            team_id = aliases[contract.venue].get(contract.outcome_name)
            if team_id is None and contract.status != "closed":  # closed placeholders are not reported
                report.unmapped.add((contract.venue, contract.outcome_name))
            catalogue.append(
                {
                    "venue": contract.venue,
                    "ticker": contract.ticker,
                    "season": event.season,
                    "event_ref": contract.event_ref,
                    "event_title": contract.event_title,
                    "question": event.question,
                    "outcome_name": contract.outcome_name,
                    "team_id": team_id,
                    "status": contract.status,
                    "close_utc": contract.close_utc,
                    "source_id": f"{got.source}:listing",
                    "event_time": got.fetched_at,
                    "first_public_time": got.fetched_at,
                    "raw_hash": got.raw_hash,
                    "vintage": "live",
                }
            )
            if contract.status == "active":  # a closed contract's last listing is not a quote
                quotes.append(_quote_row(contract, event.season, "top", got.fetched_at, contract.quote, got))
        if not contracts:
            report.empty.append(f"{event.venue}:{event.ref}")
            continue
        result = upsert(
            lake, "market_catalogue", _frame("market_catalogue", catalogue), got.fetched_at, "observed"
        )
        report.catalogue_new += result.new
        report.catalogue_changed += result.corrected
        latest = got.fetched_at
        if depth and event.depth:
            for contract in contracts:
                if contract.status != "active":
                    continue
                book_got, book = _book(venues, contract)
                quotes.append(_quote_row(contract, event.season, "book", book_got.fetched_at, book, book_got))
                latest = max(latest, book_got.fetched_at)
        if quotes:
            frame = _frame("market_quotes", quotes)
            report.quotes += upsert(lake, "market_quotes", frame, latest, "observed").new
    return report


def _windows(end: datetime, hours: int) -> list[tuple[int, int]]:
    """Unix-second windows of at most MAX_WINDOW covering the last `hours`, oldest first."""
    start, out = end - timedelta(hours=hours), []
    while start < end:
        stop = min(start + MAX_WINDOW, end)
        out.append((int(start.timestamp()), int(stop.timestamp())))
        start = stop
    return out


def _history(venues: Venues, contract: Contract, hours: int) -> list[tuple[Fetched, list[readers.Point]]]:
    if contract.venue == "kalshi":
        end = venues.kalshi.now()
        path = f"/series/{contract.series}/markets/{contract.ticker}/candlesticks"
        params = {
            "start_ts": int((end - timedelta(hours=hours)).timestamp()),
            "end_ts": int(end.timestamp()),
            "period_interval": CANDLE_MINUTES,
        }
        got = venues.kalshi.get(path, params)
        return [(got, readers.kalshi_candles(got.json()))]
    out = []
    for start, stop in _windows(venues.clob.now(), hours):  # the venue refuses long windows
        query = {"market": contract.ticker, "startTs": start, "endTs": stop, "fidelity": CANDLE_MINUTES}
        got = venues.clob.get("/prices-history", query)
        out.append((got, readers.polymarket_history(got.json())))
    return out


def history(lake: Lake, venues: Venues, events: Sequence[EventRef], hours: int) -> Report:
    """Hourly venue history for the depth-flagged events, `hours` back. Reruns add only new periods."""
    report = Report()
    for event in (e for e in events if e.depth):
        _, contracts = listing(venues, event)
        if not contracts:
            report.empty.append(f"{event.venue}:{event.ref}")
        rows: dict[tuple[str, datetime], dict[str, Any]] = {}
        latest: datetime | None = None
        for contract in contracts:
            for got, points in _history(venues, contract, hours):
                latest = got.fetched_at if latest is None else max(latest, got.fetched_at)
                for point in points:
                    if point.ts > got.fetched_at:  # a period still open is not final
                        continue
                    row = _quote_row(
                        contract, event.season, "candle", point.ts, point.quote, got, "reconstructed"
                    )
                    held = rows.setdefault((contract.ticker, point.ts), row)
                    if any(held[c] != row[c] for c in ("bid", "ask", "last")):
                        raise SourceError(f"{contract.venue} {contract.ticker}: two prices for {point.ts}")
        if rows and latest is not None:
            # "observed": if the venue later revises a period, the revision is public when we saw it
            frame = _frame("market_quotes", list(rows.values()))
            report.quotes += upsert(lake, "market_quotes", frame, latest, "observed").new
    return report
