"""Simulator (P17; FF-02, VT-13, DS-07): game probabilities, correlated draws, valid scores, seeds."""

from __future__ import annotations

import numpy as np
import polars as pl
import pytest

from cfp.forecast.simulator import (
    Game,
    ScoreTable,
    SpreadCurve,
    devig,
    fit_dependence,
    fit_spread_curve,
    game_probability,
    simulate,
)

N = 40_000


def se(p: float, n: int = N) -> float:
    return float(np.sqrt(p * (1 - p) / n))


def test_devig_moneylines() -> None:
    assert devig(-110, -110) == pytest.approx(0.5)
    # -150 implies 0.6 and +130 implies 0.43478; together 1.03478, so the home share is 0.57983
    assert devig(-150, 130) == pytest.approx(0.6 / (0.6 + 100 / 230))
    assert devig(130, -150) == pytest.approx(1 - devig(-150, 130))
    assert devig(-250, 200) == pytest.approx((250 / 350) / (250 / 350 + 100 / 300))
    assert devig(-10000, 2000) == pytest.approx((10000 / 10100) / (10000 / 10100 + 100 / 2100))
    for bad in ((0, -110), (-110, 50), (-99, 120)):
        with pytest.raises(ValueError, match="moneyline"):
            devig(*bad)


def test_spread_curve() -> None:
    rng = np.random.default_rng(11)
    spreads = np.round(rng.normal(0, 12, 20_000) * 2) / 2
    truth = SpreadCurve(scale=13.0)
    won = rng.random(20_000) < np.array([truth.probability(s) for s in spreads])
    curve = fit_spread_curve(spreads, won)
    assert curve.scale == pytest.approx(13.0, abs=0.8)
    assert curve.probability(0.0) == pytest.approx(0.5)
    assert curve.probability(-7.0) > 0.5 > curve.probability(7.0)  # a negative spread favours the home side
    assert curve.probability(-7.0) == pytest.approx(1 - curve.probability(7.0))
    assert curve.probability(-40.0) > curve.probability(-10.0)
    with pytest.raises(ValueError, match="no games"):
        fit_spread_curve(np.array([]), np.array([], dtype=bool))


def test_game_probability_prefers_moneylines_then_spread_then_strength() -> None:
    curve = SpreadCurve(scale=13.0)
    assert game_probability(curve, moneylines=[(-150, 130)], spreads=[-3.0], strength=0.9) == (
        pytest.approx(devig(-150, 130)),
        "moneyline",
    )
    both = game_probability(
        curve, moneylines=[(-150, 130), (-170, 150), (-140, 120)], spreads=[], strength=None
    )
    assert both == (pytest.approx(devig(-150, 130)), "moneyline")  # the median book
    assert game_probability(curve, moneylines=[], spreads=[-3.0, -3.5, -4.0], strength=0.9) == (
        pytest.approx(curve.probability(-3.5)),
        "spread",
    )
    assert game_probability(curve, moneylines=[], spreads=[], strength=0.61) == (0.61, "strength")
    with pytest.raises(ValueError, match="no probability"):
        game_probability(curve, moneylines=[], spreads=[], strength=None)


def slate() -> list[Game]:
    return [
        Game("g1", "A", "B", 0.70),
        Game("g2", "A", "C", 0.55),  # A at home again
        Game("g3", "D", "A", 0.40),  # A away
        Game("g4", "E", "F", 0.05),
        Game("g5", "G", "H", 0.95),
        Game("g6", "I", "J", 0.50),
    ]


def test_win_rates_match_inputs() -> None:
    for a in (0.0, 0.6, 1.0):
        paths = simulate(slate(), N, a=a, seed=5)
        assert paths.home_won.shape == (N, 6)
        for k, game in enumerate(slate()):
            assert abs(paths.home_won[:, k].mean() - game.p_home) < 3 * se(game.p_home), (a, game.game_id)


def test_a_zero_independent() -> None:
    def corr(a: float, i: int, j: int) -> float:
        won = simulate(slate(), N, a=a, seed=9).home_won.astype(float)
        return float(np.corrcoef(won[:, i], won[:, j])[0, 1])

    noise = 3 / np.sqrt(N)
    assert abs(corr(0.0, 0, 1)) < noise  # a = 0: games sharing a team are independent
    assert abs(corr(0.0, 0, 2)) < noise
    assert corr(0.8, 0, 1) > 5 * noise  # A at home in both: its good days help in both
    assert corr(0.8, 0, 2) < -5 * noise  # A at home in one and away in the other
    assert abs(corr(0.8, 3, 4)) < noise  # games with no team in common stay independent
    with pytest.raises(ValueError, match="between 0 and 1"):
        simulate(slate(), 10, a=1.2, seed=1)


def test_seed_reproducible() -> None:
    table = ScoreTable.from_history(history())
    one = simulate(slate(), 500, a=0.5, seed=42, scores=table)
    two = simulate(slate(), 500, a=0.5, seed=42, scores=table)
    other = simulate(slate(), 500, a=0.5, seed=43, scores=table)
    assert one.seed == 42
    assert np.array_equal(one.home_won, two.home_won)
    assert np.array_equal(one.home_pts, two.home_pts)
    assert not np.array_equal(one.home_won, other.home_won)
    assert (
        simulate(list(reversed(slate())), 500, a=0.5, seed=42).game_ids == one.game_ids
    )  # sorted by game id


def history(n: int = 6000) -> pl.DataFrame:
    rng = np.random.default_rng(3)
    p = rng.uniform(0.03, 0.97, n)
    margin = np.round(rng.normal((p - 0.5) * 50, 14)).astype(int)
    margin[margin == 0] = 1
    low = rng.integers(0, 35, n)
    home = np.where(margin > 0, low + margin, low)
    away = np.where(margin > 0, low, low - margin)
    return pl.DataFrame({"p_home": p, "home_pts": home, "away_pts": away})


def test_no_tied_scores() -> None:
    table = ScoreTable.from_history(history())
    paths = simulate(slate(), 5000, a=0.6, seed=7, scores=table)
    assert paths.home_pts is not None
    assert paths.away_pts is not None
    assert paths.home_pts.dtype.kind == "i"
    assert (paths.home_pts != paths.away_pts).all()
    assert ((paths.home_pts > paths.away_pts) == paths.home_won).all()  # the score agrees with the winner
    assert (paths.home_pts >= 0).all()
    assert (paths.away_pts >= 0).all()
    # a heavy favourite that wins does so by more, on average, than a coin-flip winner
    fav = (paths.home_pts[:, 4] - paths.away_pts[:, 4])[paths.home_won[:, 4]].mean()
    even = (paths.home_pts[:, 5] - paths.away_pts[:, 5])[paths.home_won[:, 5]].mean()
    assert fav > even
    with pytest.raises(ValueError, match="tied"):
        ScoreTable.from_history(pl.DataFrame({"p_home": [0.5], "home_pts": [21], "away_pts": [21]}))
    assert simulate(slate(), 10, a=0.6, seed=7).home_pts is None  # no table, no scores


def season_of(a: float, seed: int, teams: int = 60, rounds: int = 12) -> pl.DataFrame:
    """One season simulated with a known dependence weight: every team plays each round."""
    rng = np.random.default_rng(seed)
    rows = []
    for rnd in range(rounds):
        order = rng.permutation(teams)
        for k in range(teams // 2):
            rows.append(
                (
                    f"s{seed}-r{rnd}-{k}",
                    f"T{order[2 * k]}",
                    f"T{order[2 * k + 1]}",
                    float(rng.uniform(0.15, 0.85)),
                )
            )
    games = [Game(*row) for row in rows]
    paths = simulate(games, 1, a=a, seed=seed)
    won = dict(zip(paths.game_ids, paths.home_won[0], strict=True))
    data = [(g.game_id, seed, g.home_id, g.away_id, g.p_home, bool(won[g.game_id])) for g in games]
    return pl.DataFrame(
        data, schema=["game_id", "season", "home_id", "away_id", "p_home", "home_won"], orient="row"
    )


def test_fit_dependence_recovers_a() -> None:
    strong = pl.concat([season_of(0.7, seed) for seed in range(1, 13)])
    fit = fit_dependence(strong)
    assert fit.a == pytest.approx(0.7, abs=0.15)
    assert fit.pairs > 20_000
    none = pl.concat([season_of(0.0, seed) for seed in range(21, 33)])
    assert fit_dependence(none).a < 0.35
    with pytest.raises(ValueError, match="no pairs"):
        fit_dependence(strong.head(1))


def test_pair_covariance_matches_the_bivariate_normal() -> None:
    from scipy.stats import multivariate_normal, norm

    from cfp.forecast.simulator import _pair_covariance

    for rho, h, k in (
        (0.3, 0.2, -0.7),
        (-0.5, 1.3, 0.4),
        (0.5, -1.8, 1.8),
        (0.02, 0.0, 0.0),
        (-0.25, 1.5, 1.5),
    ):
        joint = multivariate_normal(mean=[0, 0], cov=[[1, rho], [rho, 1]]).cdf([h, k])
        exact = float(joint - norm.cdf(h) * norm.cdf(k))
        got = float(_pair_covariance(np.array([rho]), np.array([h]), np.array([k]))[0])
        assert got == pytest.approx(exact, abs=2e-5)
