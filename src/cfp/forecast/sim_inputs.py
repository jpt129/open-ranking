"""Simulator inputs (FF-01, FF-02): from stored game lines to probabilities, and fits on past seasons.

The caller reads `games` and `lines` from the store as of the issue cutoff, so nothing here can see a later
quote; `slate` still refuses any line stamped after the cutoff. A book's latest quote counts, and the median
across books is used. Past seasons give the spread curve, the dependence weight and the score table; the
season being forecast is never part of that history. Only game lines are read: never a team's playoff price.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import datetime
from typing import Final

import polars as pl

from cfp.forecast.simulator import (
    Dependence,
    Game,
    ScoreTable,
    SpreadCurve,
    _implied,
    fit_dependence,
    fit_spread_curve,
    game_probability,
)

MIN_BOOK_SUM: Final = 1.0  # the two implied probabilities of a real two-sided price sum to at least one
MAX_BOOK_SUM: Final = 1.25


def book_key(provider: str) -> str:
    """One name per bookmaker across sources: "oddsapi:draftkings" and "DraftKings" are the same book."""
    name = provider.split(":", 1)[-1].lower()
    return "".join(ch for ch in name if ch.isalnum())


def _usable(home: float | None, away: float | None) -> bool:
    if home is None or away is None:
        return False
    try:
        total = _implied(home) + _implied(away)
    except ValueError:
        return False
    return MIN_BOOK_SUM <= total <= MAX_BOOK_SUM


@dataclass
class Quotes:
    moneylines: list[tuple[float, float]] = field(default_factory=list)
    spreads: list[float] = field(default_factory=list)
    invalid: int = 0  # moneyline pairs that could not be used
    books: int = 0


def consensus(lines: pl.DataFrame) -> dict[str, Quotes]:
    """Each game's usable quotes: one per book, that book's most recently published."""
    keyed = lines.with_columns(book=pl.col("provider").map_elements(book_key, return_dtype=pl.String))
    order = [
        "first_public_time",
        "provider",
        "ml_home",
        "ml_away",
        "spread",
    ]  # full order: ties cannot matter
    latest = keyed.sort(order, nulls_last=True).group_by("game_id", "book", maintain_order=True).last()
    out: dict[str, Quotes] = {}
    for row in latest.sort("game_id", "book").iter_rows(named=True):
        quotes = out.setdefault(row["game_id"], Quotes())
        quotes.books += 1
        home, away = row["ml_home"], row["ml_away"]
        if home is not None or away is not None:
            if _usable(home, away):
                quotes.moneylines.append((float(home), float(away)))
            else:
                quotes.invalid += 1
        if row["spread"] is not None:
            quotes.spreads.append(float(row["spread"]))
    return out


def history(games: pl.DataFrame, lines: pl.DataFrame, *, season: int) -> pl.DataFrame:
    """Finished FBS-against-FBS games of earlier seasons that had a spread, with the median spread.

    The stored past lines are closing lines: quoted at kickoff (`as_of_utc`) and marked public only after the
    game, so a replay cannot see them early. Here the season is over, and the quote's own time is what counts.
    """
    done = games.filter(
        (pl.col("season") < season)
        & (pl.col("status") == "final")
        & (pl.col("home_div") == "fbs")
        & (pl.col("away_div") == "fbs")
        & pl.col("home_pts").is_not_null()
        & pl.col("away_pts").is_not_null()
        & (pl.col("home_pts") != pl.col("away_pts"))
    )
    quoted = lines.join(done.select("game_id", "start_utc"), on="game_id").filter(
        pl.col("spread").is_not_null() & (pl.col("as_of_utc") <= pl.col("start_utc"))
    )
    latest = quoted.sort("as_of_utc", "provider").group_by("game_id", "provider", maintain_order=True).last()
    spread = latest.group_by("game_id").agg(pl.col("spread").median())
    return (
        done.join(spread, on="game_id")
        .with_columns(home_won=pl.col("home_pts") > pl.col("away_pts"))
        .select("game_id", "season", "home_id", "away_id", "spread", "home_won", "home_pts", "away_pts")
        .sort("season", "game_id")
    )


@dataclass(frozen=True)
class Fitted:
    curve: SpreadCurve
    dependence: Dependence
    scores: ScoreTable
    seasons: tuple[int, ...]
    games: int


def fit_history(games: pl.DataFrame, lines: pl.DataFrame, *, season: int) -> Fitted:
    """The spread curve, dependence weight and score table from seasons before `season`."""
    frame = history(games, lines, season=season)
    if frame.is_empty():
        raise ValueError(f"no past games with a spread before {season}")
    curve = fit_spread_curve(frame["spread"].to_numpy(), frame["home_won"].to_numpy())
    frame = frame.with_columns(
        p_home=pl.col("spread").map_elements(curve.probability, return_dtype=pl.Float64)
    )
    return Fitted(
        curve,
        fit_dependence(frame),
        ScoreTable.from_history(frame),
        tuple(sorted(set(frame["season"].to_list()))),
        frame.height,
    )


@dataclass(frozen=True)
class Slate:
    games: tuple[Game, ...]
    sources: dict[str, str]  # game id -> moneyline, spread or strength
    in_progress: tuple[str, ...]  # kicked off before the cutoff with no final score: not simulated
    invalid_quotes: int
    books: dict[str, int]  # game id -> books quoting it; one book is a thin price and is shown as such


def slate(
    games: pl.DataFrame,
    lines: pl.DataFrame,
    cutoff: datetime,
    season: int,
    curve: SpreadCurve,
    strength: Mapping[str, float] | None = None,
) -> Slate:
    """The season's games not yet started at the cutoff that involve an FBS team, each with a probability."""
    if not lines.is_empty() and lines["first_public_time"].max() > cutoff:  # type: ignore[operator]
        raise ValueError("a line was published after the cutoff")
    open_ = games.filter(
        (pl.col("season") == season)
        & (pl.col("status") != "final")
        & ((pl.col("home_div") == "fbs") | (pl.col("away_div") == "fbs"))
    ).sort("game_id")
    quotes = consensus(lines.filter(pl.col("game_id").is_in(open_["game_id"].to_list())))
    made: list[Game] = []
    sources: dict[str, str] = {}
    started: list[str] = []
    invalid = 0
    books: dict[str, int] = {}
    for row in open_.iter_rows(named=True):
        gid = row["game_id"]
        if row["start_utc"] <= cutoff:
            started.append(gid)
            continue
        found = quotes.get(gid, Quotes())
        invalid += found.invalid
        books[gid] = found.books
        try:
            p, source = game_probability(
                curve, moneylines=found.moneylines, spreads=found.spreads, strength=(strength or {}).get(gid)
            )
        except ValueError as error:
            raise ValueError(
                f"no probability for {gid}: no moneyline, spread or strength estimate"
            ) from error
        made.append(Game(gid, row["home_id"], row["away_id"], p))
        sources[gid] = source
    return Slate(tuple(made), sources, tuple(started), invalid, books)
