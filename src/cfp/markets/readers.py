"""Parsers for Kalshi and Polymarket public market data (P02d). Reading only.

Prices are probabilities of the "Yes" side, 0..1. A side with nothing resting is None, never 0 or 1.
"""

from __future__ import annotations

import json
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from cfp.ingest.errors import SourceError


@dataclass(frozen=True)
class Quote:
    bid: float | None = None
    ask: float | None = None
    bid_size: float | None = None
    ask_size: float | None = None
    last: float | None = None


@dataclass(frozen=True)
class Contract:
    """One Yes/No contract as a venue lists it, with the best quotes the listing carries."""

    venue: str
    ticker: str  # Kalshi market ticker; Polymarket Yes-token id
    event_ref: str
    event_title: str
    outcome_name: str
    status: str
    close_utc: datetime | None
    quote: Quote
    series: str | None = None  # Kalshi only; needed for the candlestick path


@dataclass(frozen=True)
class Point:
    ts: datetime
    quote: Quote


def _price(value: Any, where: str) -> float | None:
    if value is None or value == "":
        return None
    price = float(value)
    if not 0.0 <= price <= 1.0:
        raise SourceError(f"{where}: price {value!r} is outside 0..1")
    return price


def _size(value: Any) -> float | None:
    if value is None or value == "":
        return None
    size = float(value)
    if size < 0:
        raise SourceError(f"negative size {value!r}")
    return size or None


def _bid(value: Any, where: str) -> float | None:
    """A bid of 0 is the venue's way of printing "no bid"."""
    price = _price(value, where)
    return price if price else None


def _ask(value: Any, where: str) -> float | None:
    """An ask of 1 is the venue's way of printing "no offer"."""
    price = _price(value, where)
    return price if price is not None and price < 1.0 else None


def _sided(price: float | None, size: float | None) -> tuple[float | None, float | None]:
    """A price with no size behind it is not a quote."""
    return (None, None) if price is None or size is None else (price, size)


def _time(value: Any) -> datetime | None:
    if not value:
        return None
    return datetime.fromisoformat(str(value).replace("Z", "+00:00")).astimezone(UTC)


# --- Kalshi --------------------------------------------------------------------------------------------


def kalshi_listing(payload: Any) -> list[Contract]:
    """GET /events?series_ticker=…&with_nested_markets=true."""
    if payload.get("cursor"):
        raise SourceError("kalshi: the listing has more pages than were fetched")
    out: list[Contract] = []
    for event in payload["events"]:
        for market in event["markets"]:
            ticker = market["ticker"]
            if market.get("market_type") != "binary":
                raise SourceError(f"kalshi {ticker}: not a binary market")
            # the size fields are read with [] on purpose: without them a quote cannot be told from an empty side
            bid, bid_size = _sided(_bid(market["yes_bid_dollars"], ticker), _size(market["yes_bid_size_fp"]))
            ask, ask_size = _sided(_ask(market["yes_ask_dollars"], ticker), _size(market["yes_ask_size_fp"]))
            last = _price(market.get("last_price_dollars"), ticker)
            out.append(
                Contract(
                    venue="kalshi",
                    ticker=ticker,
                    event_ref=event["event_ticker"],
                    event_title=" ".join(str(event["title"]).split()),
                    outcome_name=" ".join(str(market["yes_sub_title"]).split()),
                    status=str(market["status"]),
                    close_utc=_time(market.get("close_time")),
                    quote=Quote(bid, ask, bid_size, ask_size, last or None),
                    series=event["series_ticker"],
                )
            )
    return out


def _best(levels: Iterable[Any], where: str) -> tuple[float | None, float | None]:
    priced = [(p, s) for p, s in ((_price(lv[0], where), _size(lv[1])) for lv in levels) if p and s]
    return max(priced) if priced else (None, None)


def kalshi_book(payload: Any) -> Quote:
    """GET /markets/{ticker}/orderbook. Both sides are resting bids; a No bid at p is a Yes offer at 1 - p."""
    book = payload["orderbook_fp"]
    bid, bid_size = _best(book.get("yes_dollars") or [], "kalshi book")
    no_bid, no_size = _best(book.get("no_dollars") or [], "kalshi book")
    ask = None if no_bid is None else round(1.0 - no_bid, 6)
    return Quote(bid, ask, bid_size, no_size if ask is not None else None)


def kalshi_candles(payload: Any) -> list[Point]:
    """GET /series/{series}/markets/{ticker}/candlesticks: closing bid, ask and trade price per period."""
    out = []
    for candle in payload.get("candlesticks") or []:
        quote = Quote(
            bid=_bid((candle.get("yes_bid") or {}).get("close_dollars"), "kalshi candle"),
            ask=_ask((candle.get("yes_ask") or {}).get("close_dollars"), "kalshi candle"),
            last=_price((candle.get("price") or {}).get("close_dollars"), "kalshi candle"),
        )
        out.append(Point(datetime.fromtimestamp(int(candle["end_period_ts"]), UTC), quote))
    return out


# --- Polymarket ----------------------------------------------------------------------------------------


def polymarket_listing(payload: Any) -> list[Contract]:
    """Gamma GET /events?id=…. The contract is each market's Yes token."""
    out: list[Contract] = []
    for event in payload:
        for market in event["markets"]:
            where = f"polymarket market {market['id']}"
            outcomes, tokens = json.loads(market["outcomes"]), json.loads(market["clobTokenIds"])
            if sorted(outcomes) != ["No", "Yes"] or len(tokens) != 2:
                raise SourceError(f"{where}: not a Yes/No market: {outcomes}")
            name = market.get("groupItemTitle") or market["question"]
            closed = bool(market.get("closed")) or not market.get("active", True)
            out.append(
                Contract(
                    venue="polymarket",
                    ticker=str(tokens[outcomes.index("Yes")]),
                    event_ref=str(event["id"]),
                    event_title=" ".join(str(event["title"]).split()),
                    outcome_name=" ".join(str(name).split()),
                    status="closed" if closed else ("active" if market.get("enableOrderBook") else "no_book"),
                    close_utc=_time(market.get("endDate")),
                    quote=Quote(
                        bid=_bid(market.get("bestBid"), where),
                        ask=_ask(market.get("bestAsk"), where),
                        last=_price(market.get("lastTradePrice"), where) or None,
                    ),
                )
            )
    return out


def polymarket_book(payload: Any) -> Quote:
    """CLOB GET /book?token_id=…."""
    bids = [(_price(lv["price"], "polymarket book"), _size(lv["size"])) for lv in payload.get("bids") or []]
    asks = [(_price(lv["price"], "polymarket book"), _size(lv["size"])) for lv in payload.get("asks") or []]
    bid, bid_size = max(((p, s) for p, s in bids if p and s), default=(None, None))
    ask, ask_size = min(((p, s) for p, s in asks if p and s), default=(None, None))
    return Quote(
        bid, ask, bid_size, ask_size, _price(payload.get("last_trade_price"), "polymarket book") or None
    )


def polymarket_history(payload: Any) -> list[Point]:
    """CLOB GET /prices-history?market=<token>: the venue's displayed price series, stored in `last`.

    The venue does not say whether a point is a trade or a midpoint, so these rows are a price path only and
    cannot stand in for a two-sided quote.
    """
    return [
        Point(datetime.fromtimestamp(int(p["t"]), UTC), Quote(last=_price(p["p"], "polymarket history")))
        for p in payload.get("history") or []
    ]
