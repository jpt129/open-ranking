"""Calibration (P11-lite; OR-04, OR-12, VT-07): rolling pregame predictions, grid search, frozen file."""

from __future__ import annotations

import json
import random
from pathlib import Path
from typing import Any

import polars as pl
import pytest

from cfp.common.hashing import sha256_hex
from cfp.open_ranking.calibration import Grid, brier, log_loss, pregame, report, search, venue_only
from cfp.open_ranking.frozen import FrozenError, load_frozen, write_frozen
from cfp.open_ranking.strength import Params, fit

GRID = Grid(lambda_c=(0.5, 2.0, 8.0), lambda_u=(0.5, 2.0, 8.0), t=tuple(4.0 + 0.5 * i for i in range(33)))
PARAMS = Params(lambda_c=2.0, lambda_u=2.0)


def make_season(seed: int, weeks: int = 13, noise: float = 12.0) -> pl.DataFrame:
    """24 teams in three leagues; 12 games a week; margins from true strengths plus noise."""
    rng = random.Random(seed)
    teams = [f"T{i:02d}" for i in range(24)]
    conf = {team: f"c{i % 3}" for i, team in enumerate(teams)}
    league = {"c0": 6.0, "c1": 0.0, "c2": -6.0}
    true = {team: league[conf[team]] + rng.gauss(0, 6) for team in teams}
    rows: list[dict[str, Any]] = []
    for week in range(1, weeks + 1):
        order = teams[:]
        rng.shuffle(order)
        for k in range(12):
            home, away = order[2 * k], order[2 * k + 1]
            neutral = week == weeks and k == 0
            margin = round(true[home] - true[away] + (0 if neutral else 2.5) + rng.gauss(0, noise)) or 1
            rows.append(
                {
                    "game_id": f"s{seed}-w{week:02d}-{k:02d}",
                    "week": week,
                    "home_id": home,
                    "away_id": away,
                    "home_pts": 30 + margin,
                    "away_pts": 30,
                    "winner_id": home if margin > 0 else away,
                    "neutral": neutral,
                    "home_div": "fbs",
                    "away_div": "fbs",
                    "home_conf": conf[home],
                    "away_conf": conf[away],
                    "ordinary_fbs": True,
                    "margin_excluded": False,
                }
            )
    return pl.DataFrame(rows, schema_overrides={"week": pl.Int32, "home_pts": pl.Int32, "away_pts": pl.Int32})


def test_calibration_rolling_pregame_only() -> None:
    games = make_season(1)
    base = {p.game_id: p for p in pregame(games, PARAMS, 2021, first_week=8)}
    assert len(base) == 6 * 12  # weeks 8 to 13
    assert {p.week for p in base.values()} == set(range(8, 14))
    # rewrite every result from week 10 on: predictions for weeks 8 to 10 must not move at all
    later = pl.col("week") >= 10
    changed = games.with_columns(
        home_pts=pl.when(later).then(pl.col("away_pts") - 17).otherwise(pl.col("home_pts")).cast(pl.Int32),
        winner_id=pl.when(later).then(pl.col("away_id")).otherwise(pl.col("winner_id")),
    )
    again = {p.game_id: p for p in pregame(changed, PARAMS, 2021, first_week=8)}
    for game_id, p in base.items():
        if p.week <= 10:
            assert again[game_id].d == p.d
    assert any(again[g].d != p.d for g, p in base.items() if p.week >= 11)
    assert all(not p.home_won for p in again.values() if p.week >= 10)
    assert pregame(games.reverse(), PARAMS, 2021, first_week=8) == pregame(games, PARAMS, 2021, first_week=8)


def test_a_team_with_no_earlier_games_gets_its_league_effect() -> None:
    games = make_season(2)
    without = (pl.col("home_id") != "T00") & (pl.col("away_id") != "T00")
    late = games.filter((pl.col("week") >= 9) | without)  # T00 first plays in week 9
    first = next(p for p in pregame(late, PARAMS, 2020, first_week=9) if p.week == 9 and "T00" in p.teams)
    earlier = fit(late.filter(pl.col("week") < 9), PARAMS)
    assert "T00" not in earlier.theta
    home, away = first.teams
    side = {team: earlier.theta.get(team, earlier.conference["c0"]) for team in first.teams}  # T00 is in c0
    expected = side[home] - side[away] + (0.0 if first.neutral else earlier.home_adv)
    assert first.d == pytest.approx(expected, abs=1e-12)
    assert earlier.conference["c0"] != 0.0


def test_scores() -> None:
    preds = pregame(make_season(3), PARAMS, 2021, first_week=8)
    assert log_loss(preds, 7.0) > 0
    assert 0 < brier(preds, 7.0) < 0.5
    assert log_loss(preds, 1e6) == pytest.approx(0.6931, abs=1e-3)  # a huge scale predicts 50-50
    flat_ll, flat_brier = venue_only(preds)
    assert 0.5 < flat_ll < 0.75
    assert 0.15 < flat_brier < 0.27


def test_calibration_report() -> None:
    seasons = {2015 + i: make_season(100 + i) for i in range(6)}
    found = search(seasons, GRID, first_week=8)
    years = sorted(seasons)
    choice = found.choose(years)
    assert choice.n == 6 * 6 * 12
    assert choice.params.lambda_c in GRID.lambda_c
    assert choice.params.lambda_u in GRID.lambda_u
    assert 5.0 <= choice.t <= 16.0  # noise sd 12 is a logistic scale near 7; estimation error widens it
    assert choice.log_loss < venue_only(found.predictions(choice.params, years))[0]
    assert choice.log_loss == min(row["log_loss"] for row in found.table(years))
    out = report(found, targets=[2018, 2019, 2020])
    assert [row["season"] for row in out["rolling"]] == [2018, 2019, 2020]
    first = out["rolling"][0]
    assert first["trained_on"] == [2015, 2016, 2017]  # parameters for a season come from earlier seasons only
    assert set(first) >= {"log_loss", "brier", "venue_only_log_loss", "venue_only_brier", "n", "t"}
    assert len(out["reliability"]) == 10
    assert sum(row["n"] for row in out["reliability"]) == sum(row["n"] for row in out["rolling"])
    assert found.choose([2015, 2016]).n == 2 * 6 * 12
    with pytest.raises(ValueError, match="no seasons"):
        found.choose([])


def test_frozen_hash(tmp_path: Path) -> None:
    doc: dict[str, Any] = {"season": 2026, "lambda_c": 2.0, "lambda_u": 0.5, "t": 7.25, "cap": 24}
    doc |= {"independent_penalty": "combined", "status": "provisional", "rule_version_id": "or-test"}
    root = tmp_path / "frozen_params"
    path, digest = write_frozen(root, 2026, doc)
    assert path.name == "params_2026.json"
    assert digest == sha256_hex(path.read_bytes())
    assert (root / "params_2026.sha256").read_text().split()[0] == digest
    frozen = load_frozen(root, 2026)
    assert (frozen.params, frozen.t, frozen.sha256) == (Params(2.0, 0.5), 7.25, digest)
    assert frozen.rule_version_id == "or-test"
    with pytest.raises(FrozenError, match="already frozen"):
        write_frozen(root, 2026, doc)
    path.chmod(0o644)
    path.write_text(json.dumps(doc | {"t": 9.0}))
    with pytest.raises(FrozenError, match="does not match"):
        load_frozen(root, 2026)
    with pytest.raises(FrozenError, match="not frozen"):
        load_frozen(root, 2027)
