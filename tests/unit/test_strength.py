"""Strength engine (P05, OR-02): ridge fit of capped margins with the evaluated team removed."""

from __future__ import annotations

import random
import time
from typing import Any

import numpy as np
import polars as pl
import pytest

from cfp.open_ranking.strength import INDEPENDENT, Params, StrengthError, fit, fit_all

PARAMS = Params(lambda_c=2.0, lambda_u=0.5)
LEAGUES = {"east": ["E1", "E2", "E3", "E4"], "west": ["W1", "W2", "W3", "W4"], INDEPENDENT: ["ND", "UC"]}
CONF = {team: conf for conf, teams in LEAGUES.items() for team in teams}
TRUE = {"E1": 12.0, "E2": 6.0, "E3": 3.0, "E4": -2.0, "W1": 2.0, "W2": -3.0, "W3": -8.0, "W4": -10.0}
TRUE |= {"ND": 9.0, "UC": -9.0}


def row(game_id: str, home: str, away: str, home_pts: int, away_pts: int, **over: Any) -> dict[str, Any]:
    base = {
        "game_id": game_id,
        "home_id": home,
        "away_id": away,
        "home_pts": home_pts,
        "away_pts": away_pts,
        "neutral": False,
        "home_div": "fbs",
        "away_div": "fbs",
        "home_conf": CONF.get(home),
        "away_conf": CONF.get(away),
        "ordinary_fbs": True,
        "margin_excluded": False,
    }
    return base | over


def frame(rows: list[dict[str, Any]]) -> pl.DataFrame:
    schema = {
        "game_id": pl.String,
        "home_id": pl.String,
        "away_id": pl.String,
        "home_pts": pl.Int32,
        "away_pts": pl.Int32,
        "neutral": pl.Boolean,
        "home_div": pl.String,
        "away_div": pl.String,
        "home_conf": pl.String,
        "away_conf": pl.String,
        "ordinary_fbs": pl.Boolean,
        "margin_excluded": pl.Boolean,
    }
    return pl.DataFrame(rows, schema=schema)


def season(seed: int = 7, home_adv: float = 3.0, noise: float = 0.0) -> list[dict[str, Any]]:
    """Every pair meets twice, home and away; margins follow the true strengths (kept inside the cap)."""
    rng = random.Random(seed)
    teams = sorted(TRUE)
    rows = []
    for home in teams:
        for away in teams:
            if home == away:
                continue
            margin = round(TRUE[home] - TRUE[away] + home_adv + rng.gauss(0, noise))
            margin = margin or 1
            rows.append(row(f"{home}-{away}", home, away, 30 + margin, 30))
    return rows


def same(a: Any, b: Any) -> bool:
    return a.theta == b.theta and a.home_adv == b.home_adv and a.conference == b.conference


def test_fit_recovers_strength_differences_and_home_advantage() -> None:
    got = fit(frame(season()), Params(lambda_c=1e-6, lambda_u=1e-6))
    assert got.home_adv == pytest.approx(3.0, abs=0.2)
    for a, b in (("E1", "W4"), ("ND", "UC"), ("E2", "W1")):
        assert got.theta[a] - got.theta[b] == pytest.approx(TRUE[a] - TRUE[b], abs=0.6)
    assert got.n_games == 90
    assert set(got.theta) == set(TRUE)


def test_strength_is_conference_effect_plus_team_deviation_shrunk_toward_zero() -> None:
    got = fit(frame(season(noise=4.0)), PARAMS)
    assert set(got.conference) == {"east", "west"}  # independents share no league effect
    for team, conf in CONF.items():
        expected = got.deviation[team] + (got.conference[conf] if conf != INDEPENDENT else 0.0)
        assert got.theta[team] == pytest.approx(expected, abs=1e-12)
    heavy = fit(frame(season(noise=4.0)), Params(lambda_c=1e9, lambda_u=1e9))
    assert max(abs(value) for value in heavy.theta.values()) < 1e-4
    spread = max(got.theta.values()) - min(got.theta.values())
    loose = fit(frame(season(noise=4.0)), Params(lambda_c=1e-6, lambda_u=1e-6))
    assert spread < max(loose.theta.values()) - min(loose.theta.values())


def test_fit_solves_the_ridge_normal_equations() -> None:
    """Independent check: the same answer from least squares on the penalty-augmented system."""
    games = frame(season(noise=5.0))
    got = fit(games, PARAMS)
    teams, confs = sorted(TRUE), ["east", "west"]
    columns = ["h", *confs, *teams]
    index = {name: i for i, name in enumerate(columns)}
    lam_ind = 1.0 / (1.0 / PARAMS.lambda_c + 1.0 / PARAMS.lambda_u)
    rows, y = [], []
    for g in games.iter_rows(named=True):
        x = [0.0] * len(columns)
        x[index["h"]] = 1.0
        for team, sign in ((g["home_id"], 1.0), (g["away_id"], -1.0)):
            x[index[team]] += sign
            if CONF[team] != INDEPENDENT:
                x[index[CONF[team]]] += sign
        rows.append(x)
        y.append(float(max(-24, min(24, g["home_pts"] - g["away_pts"]))))
    penalty = [0.0, PARAMS.lambda_c, PARAMS.lambda_c]
    penalty += [lam_ind if CONF[t] == INDEPENDENT else PARAMS.lambda_u for t in teams]
    design = np.vstack([np.array(rows), np.diag(np.sqrt(penalty))])
    beta = np.linalg.lstsq(design, np.array(y + [0.0] * len(columns)), rcond=None)[0]
    assert got.home_adv == pytest.approx(beta[0], abs=1e-9)
    for team in teams:
        league = beta[index[CONF[team]]] if CONF[team] != INDEPENDENT else 0.0
        assert got.theta[team] == pytest.approx(beta[index[team]] + league, abs=1e-9)


def test_independents_penalty_is_combined_by_default_and_team_only_on_request() -> None:
    games = frame(season(noise=4.0))
    combined = fit(games, PARAMS)
    team_only = fit(games, Params(lambda_c=2.0, lambda_u=0.5, independent_penalty="team"))
    assert combined.theta["ND"] != team_only.theta["ND"]
    assert abs(combined.theta["ND"]) > abs(
        team_only.theta["ND"]
    )  # 1/(1/2 + 1/0.5) = 0.4 < 0.5: less shrinkage
    with pytest.raises(StrengthError, match="independent_penalty"):
        fit(games, Params(lambda_c=2.0, lambda_u=0.5, independent_penalty="none"))  # type: ignore[arg-type]


def test_a_teams_own_games_do_not_change_the_fit_used_to_grade_it() -> None:
    rows = season(noise=4.0)
    base = fit(frame(rows), PARAMS, exclude="E2")
    assert "E2" not in base.theta
    assert base.n_games == 72
    changed = []
    for g in rows:
        if "E2" in (g["home_id"], g["away_id"]):
            g = g | {"home_pts": g["away_pts"] + 40, "away_pts": g["home_pts"]}  # new margins and results
        changed.append(g)
    assert same(fit(frame(changed), PARAMS, exclude="E2"), base)
    dropped = [g for g in rows if "E2" not in (g["home_id"], g["away_id"])]
    assert fit(frame(dropped), PARAMS).theta == pytest.approx(base.theta, abs=1e-9)
    assert not same(fit(frame(changed), PARAMS), fit(frame(rows), PARAMS))  # the full fit does see them


def test_permutation_invariance() -> None:
    rows = season(noise=4.0)
    base = fit(frame(rows), PARAMS, exclude="W1")
    shuffled = rows[:]
    random.Random(3).shuffle(shuffled)
    assert same(fit(frame(shuffled), PARAMS, exclude="W1"), base)
    assert same(fit(frame(list(reversed(rows))), PARAMS, exclude="W1"), base)


def test_neutral_reversal_symmetry() -> None:
    rows = season(noise=4.0)
    rows.append(row("bowl-like", "E1", "W1", 31, 17, neutral=True))
    flipped = [*rows[:-1], row("bowl-like", "W1", "E1", 17, 31, neutral=True)]
    assert same(fit(frame(flipped), PARAMS), fit(frame(rows), PARAMS))
    at_home = [*rows[:-1], row("bowl-like", "E1", "W1", 31, 17)]
    assert not same(
        fit(frame(at_home), PARAMS), fit(frame(rows), PARAMS)
    )  # a true home game adds the site term


def test_margins_are_capped_at_24() -> None:
    rows = season(noise=4.0)
    blowout = [row("x", "E1", "W4", 70, 0), row("y", "W4", "E1", 0, 63)]
    capped = [row("x", "E1", "W4", 24, 0), row("y", "W4", "E1", 0, 24)]
    assert same(fit(frame(rows + blowout), PARAMS), fit(frame(rows + capped), PARAMS))
    uncapped = Params(lambda_c=2.0, lambda_u=0.5, cap=100)
    assert not same(fit(frame(rows + blowout), uncapped), fit(frame(rows + capped), uncapped))


def test_only_fbs_v_fbs_games_with_usable_margins_enter_the_fit() -> None:
    rows = season(noise=4.0)
    base = fit(frame(rows), PARAMS)
    extra = [
        row("fcs", "E1", "FCS1", 3, 45, away_div="fcs", away_conf="big-sky", ordinary_fbs=False),
        row("forfeit", "E1", "W4", 0, 2, ordinary_fbs=False, margin_excluded=True),
    ]
    assert same(fit(frame(rows + extra), PARAMS), base)
    assert "FCS1" not in base.theta


def test_a_team_in_two_conferences_or_an_all_neutral_slate_is_handled() -> None:
    rows = season()
    with pytest.raises(StrengthError, match="two conferences"):
        fit(frame([*rows, row("odd", "E1", "W1", 20, 10, home_conf="west")]), PARAMS)
    with pytest.raises(StrengthError, match="no FBS games"):
        fit(frame([]), PARAMS)
    neutral = fit(frame([g | {"neutral": True} for g in rows]), PARAMS)
    assert neutral.home_adv == 0.0  # nothing to estimate it from


def test_fit_all_gives_one_fold_per_team_within_budget() -> None:
    rng = random.Random(11)
    teams = [f"T{i:03d}" for i in range(136)]
    conf = {team: f"c{i % 10}" for i, team in enumerate(teams)}
    rows = []
    for n in range(800):
        home, away = rng.sample(teams, 2)
        margin = rng.randint(-30, 30) or 3
        rows.append(row(f"g{n:04d}", home, away, 30 + margin, 30, home_conf=conf[home], away_conf=conf[away]))
    games = frame(rows)
    fit_all(games, PARAMS)  # warm-up
    start = time.perf_counter()
    folds = fit_all(games, PARAMS)
    elapsed = time.perf_counter() - start
    assert set(folds) == set(teams)
    assert elapsed < 1.0, f"136 fits took {elapsed:.2f}s"
    assert same(folds["T007"], fit(games, PARAMS, exclude="T007"))
    assert "T007" not in folds["T007"].theta
