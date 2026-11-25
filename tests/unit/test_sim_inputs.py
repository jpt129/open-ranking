"""Simulator inputs (FF-01, FF-02): quotes to probabilities, history fits, the slate of remaining games."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import numpy as np
import polars as pl
import pytest

from cfp.forecast.sim_inputs import consensus, fit_history, history, slate
from cfp.forecast.simulator import SpreadCurve, devig

CUT = datetime(2026, 11, 29, 7, tzinfo=UTC)


def game(gid: str, season: int = 2026, **over: object) -> dict[str, object]:
    row: dict[str, object] = {
        "game_id": gid,
        "season": season,
        "start_utc": CUT + timedelta(days=6),
        "home_id": f"{gid}-h",
        "away_id": f"{gid}-a",
        "home_pts": None,
        "away_pts": None,
        "neutral": False,
        "status": "scheduled",
        "title_game": False,
        "home_div": "fbs",
        "away_div": "fbs",
    }
    return row | over


GAME_SCHEMA = {"home_pts": pl.Int64, "away_pts": pl.Int64}


def quote(
    gid: str, book: str, hours_before: float, ml: tuple[float, float] | None, spread: float | None
) -> dict[str, object]:
    seen = CUT - timedelta(hours=hours_before)
    home, away = ml if ml else (None, None)
    return {
        "provider": book,
        "game_id": gid,
        "as_of_utc": seen,
        "first_public_time": seen,
        "ml_home": home,
        "ml_away": away,
        "spread": spread,
    }


LINE_SCHEMA = {"ml_home": pl.Float64, "ml_away": pl.Float64, "spread": pl.Float64}


def test_consensus_takes_each_books_latest_quote() -> None:
    lines = pl.DataFrame(
        [
            quote("g1", "a", 30, (-200, 170), -5.0),  # stale: replaced by the next row
            quote("g1", "a", 2, (-150, 130), -3.0),
            quote("g1", "b", 5, (-170, 150), -3.5),
            quote("g1", "c", 4, (-140, 120), -4.0),
            quote("g1", "d", 3, (-50, 120), None),  # not a valid moneyline: dropped and counted
            quote("g2", "a", 3, None, 7.0),
        ],
        schema_overrides=LINE_SCHEMA,
    )
    found = consensus(lines)
    assert sorted(found["g1"].moneylines) == [(-170.0, 150.0), (-150.0, 130.0), (-140.0, 120.0)]
    assert sorted(found["g1"].spreads) == [-4.0, -3.5, -3.0]
    assert found["g1"].invalid == 1
    assert (found["g2"].moneylines, found["g2"].spreads) == ([], [7.0])


def test_one_book_from_two_sources_counts_once_and_bad_prices_are_dropped() -> None:
    lines = pl.DataFrame(
        [
            quote("g1", "DraftKings", 9, (-200, 170), -5.0),
            quote("g1", "oddsapi:draftkings", 2, (-150, 130), -3.0),  # the same book, later: this one counts
            quote("g1", "oddsapi:fanduel", 2, (-160, 140), -3.5),
            quote("g1", "x", 2, (150, 150), None),  # the two sides sum below one: not a real price
            quote("g1", "y", 2, (-900, -900), None),  # sums far above one
            quote("g1", "z", 2, (float("nan"), -110), None),
        ],
        schema_overrides=LINE_SCHEMA,
    )
    found = consensus(lines)["g1"]
    assert sorted(found.moneylines) == [(-160.0, 140.0), (-150.0, 130.0)]
    assert (found.invalid, found.books) == (3, 5)
    assert consensus(lines.reverse())["g1"].moneylines == found.moneylines
    tied = pl.DataFrame(
        [quote("g", "a", 2, (-300, 250), None), quote("g", "a", 2, (-150, 130), None)],
        schema_overrides=LINE_SCHEMA,
    )
    assert consensus(tied)["g"].moneylines == consensus(tied.reverse())["g"].moneylines


def past(season: int, n: int = 400) -> tuple[pl.DataFrame, pl.DataFrame]:
    rng = np.random.default_rng(season)
    games, lines = [], []
    for k in range(n):
        gid = f"p{season}-{k}"
        spread = float(np.round(rng.normal(0, 12) * 2) / 2)
        margin = int(np.round(rng.normal(-spread, 14))) or 1
        low = int(rng.integers(0, 30))
        start = datetime(season, 10, 1, tzinfo=UTC) + timedelta(hours=k)
        pts = (low + margin, low) if margin > 0 else (low, low - margin)
        games.append(
            game(
                gid,
                season,
                start_utc=start,
                status="final",
                home_pts=pts[0],
                away_pts=pts[1],
                home_id=f"T{k % 40}",
                away_id=f"T{(k * 7 + k // 40) % 40 + 40}",
            )
        )
        lines.append(
            {
                "provider": "x",
                "game_id": gid,
                "as_of_utc": start,
                "first_public_time": start + timedelta(hours=4),  # as stored: public only after the game
                "ml_home": None,
                "ml_away": None,
                "spread": spread,
            }
        )
    return pl.DataFrame(games, schema_overrides=GAME_SCHEMA), pl.DataFrame(
        lines, schema_overrides=LINE_SCHEMA
    )


def test_history_uses_only_earlier_seasons_and_usable_games() -> None:
    frames = [past(s) for s in (2024, 2025, 2026)]
    games = pl.concat([f[0] for f in frames])
    lines = pl.concat([f[1] for f in frames])
    odd = pl.DataFrame(
        [
            game("tie", 2025, status="final", home_pts=20, away_pts=20),
            game("fcs", 2025, status="final", home_pts=40, away_pts=3, away_div="fcs"),
            game("noline", 2025, status="final", home_pts=40, away_pts=3),
        ],
        schema_overrides=GAME_SCHEMA,
    )
    extra = pl.DataFrame(
        [quote("tie", "x", 1, None, -1.0), quote("fcs", "x", 1, None, -30.0)], schema_overrides=LINE_SCHEMA
    )
    frame = history(pl.concat([games, odd]), pl.concat([lines, extra]), season=2026)
    assert set(frame["season"].to_list()) == {2024, 2025}  # the target season is never training data
    assert not {"tie", "fcs", "noline"} & set(frame["game_id"].to_list())
    assert frame.height == 800
    fitted = fit_history(pl.concat([games, odd]), pl.concat([lines, extra]), season=2026)
    assert fitted.seasons == (2024, 2025)
    assert fitted.games == 800
    assert fitted.curve.scale == pytest.approx(14.0, abs=2.5)
    assert 0.0 <= fitted.dependence.a <= 1.0
    with pytest.raises(ValueError, match="no past games"):
        fit_history(games, lines, season=2024)


def test_slate_is_the_games_still_to_play() -> None:
    games = pl.DataFrame(
        [
            game("ml"),
            game("sp"),
            game("st", neutral=True, title_game=True),
            game("done", status="final", home_pts=30, away_pts=10, start_utc=CUT - timedelta(days=1)),
            game(
                "started", start_utc=CUT - timedelta(minutes=30)
            ),  # kicked off before the cutoff, no final yet
            game("lower", home_div="fcs", away_div="fcs"),
            game("other-season", season=2025),
        ],
        schema_overrides=GAME_SCHEMA,
    )
    lines = pl.DataFrame(
        [
            quote("ml", "a", 2, (-150, 130), -3.0),
            quote("sp", "a", 2, None, -7.0),
            quote("done", "a", 40, (-300, 250), -7.0),
            quote("started", "a", 1, (-120, 100), None),  # before its kickoff half an hour before the cutoff
            quote("started", "a", 0.2, (-900, 600), None),  # in-game: ignored,
        ],
        schema_overrides=LINE_SCHEMA,
    )
    curve = SpreadCurve(14.0)
    made = slate(games, lines, CUT, 2026, curve, strength={"st": 0.4})
    assert [g.game_id for g in made.games] == ["ml", "sp", "st", "started"]
    assert made.sources == {"ml": "moneyline", "sp": "spread", "st": "strength", "started": "moneyline"}
    by = {g.game_id: g for g in made.games}
    assert by["ml"].p_home == pytest.approx(devig(-150, 130))
    assert by["sp"].p_home == pytest.approx(curve.probability(-7.0))
    assert (by["st"].p_home, by["st"].home_id, by["st"].away_id) == (0.4, "st-h", "st-a")
    assert made.books == {"ml": 1, "sp": 1, "st": 0, "started": 1}
    assert made.in_progress == ("started",)  # unplayed: priced from the last quote before kickoff
    assert by["started"].p_home == pytest.approx(devig(-120, 100))
    est = slate(games, lines, CUT, 2026, curve, estimate=lambda home, away, neutral: 0.3 if neutral else None)
    assert {g.game_id: g.p_home for g in est.games}["st"] == 0.3
    with pytest.raises(ValueError, match="no probability for st"):
        slate(games, lines, CUT, 2026, curve)
    late = lines.with_columns(first_public_time=pl.lit(CUT + timedelta(minutes=1)))
    with pytest.raises(ValueError, match="after the cutoff"):
        slate(games, late, CUT, 2026, curve, strength={"st": 0.4})
