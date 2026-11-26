"""Evidence sensitivity (VT-08): re-weighted refits of the strength fit, with results held fixed."""

from __future__ import annotations

import json
import random
from pathlib import Path
from typing import Any

import numpy as np
import polars as pl
import pytest

from cfp.forecast.final_field import Setup, field_today
from cfp.open_ranking import sensitivity as core
from cfp.open_ranking.ledger import build_ledgers
from cfp.open_ranking.ordering import rank_teams
from cfp.open_ranking.strength import INDEPENDENT, Engine, Params
from cfp.release import sensitivity as report
from cfp.rules.engine import load_rules

from .test_ledger import fcs, frame, game

PARAMS = Params(lambda_c=4.0, lambda_u=4.0)
T = 5.75
LEAGUES = ("acc", "big-ten", "big-12", "sec", "mountain-west", "sun-belt")
TEAMS = [f"S{i:02d}" for i in range(40)]
CONF = {team: (INDEPENDENT if i >= 36 else LEAGUES[i % 6]) for i, team in enumerate(TEAMS)}
DRAW = {team: place for place, team in enumerate(reversed(TEAMS), start=1)}
ELIGIBLE = {team: True for team in TEAMS}


def season(seed: int = 11, weeks: int = 8) -> list[dict[str, Any]]:
    """Random pairings among 40 teams in real conferences, with strength falling by team number."""
    rng = random.Random(seed)
    rows = []
    for week in range(1, weeks + 1):
        order = TEAMS[:]
        rng.shuffle(order)
        for k in range(20):
            home, away = order[2 * k], order[2 * k + 1]
            margin = round((TEAMS.index(away) - TEAMS.index(home)) * 0.8 + 2.5 + rng.gauss(0, 10)) or 1
            over = {"week": week, "home_conf": CONF[home], "away_conf": CONF[away]}
            rows.append(game(f"w{week}-{k:02d}", home, away, 30 + margin, 30, **over))
    return rows


def published(games: pl.DataFrame) -> dict[str, Any]:
    """The part of an edition document the sensitivity report reads."""
    ledgers = build_ledgers(games, PARAMS, T, 2026)
    ranked = rank_teams({team: ledger.total_cp for team, ledger in ledgers.items()}, games, DRAW)
    teams = [
        {"team_id": r.team_id, "total_cp": r.total_cp, "open_rank": r.open_rank, "order": r.order}
        for r in ranked
    ]
    return {"edition_id": "or-2026-20261122t0700z-replay-e1", "season": 2026, "teams": teams}


def built(games: pl.DataFrame, refits: int = 20, **over: Any) -> Any:
    args: dict[str, Any] = {"members": CONF, "eligible": ELIGIBLE, "code_hash": "abc1234", "refits": refits}
    return report.build_sensitivity(published(games), "e" * 64, games, PARAMS, T, DRAW, **(args | over))


# --- weights -------------------------------------------------------------------


def test_refit_weights_reused_across_folds() -> None:
    """A weight of 2 on one game is that game played twice, in every team's fold; penalties are unchanged."""
    rows = season()
    games = frame(rows)
    twice = rows[7]
    doubled = frame([*rows, twice | {"game_id": "w1-07-again"}])
    base = Engine(games, PARAMS)
    ids = core.fitted_games(games, base)
    assert ids == sorted(str(row["game_id"]) for row in rows)
    weighted = core.weighted(base, ids, dict.fromkeys(ids, 1.0) | {twice["game_id"]: 2.0})
    plain = Engine(doubled, PARAMS)
    for team in TEAMS:
        ours, theirs = weighted.fit(team), plain.fit(team)
        assert ours.theta.keys() == theirs.theta.keys()
        assert max(abs(ours.theta[t] - theirs.theta[t]) for t in ours.theta) < 1e-9
        assert abs(ours.home_adv - theirs.home_adv) < 1e-9
    assert (weighted._penalty == base._penalty).all()
    # every game re-weighted: each fold is the full weighted solve with that one set of weights
    drawn = core.game_weights(ids, seed=5)
    assert list(drawn) == ids
    folds = core.weighted(base, ids, drawn)
    x, y, w = base._x, base._y, np.array([drawn[g] for g in ids])
    by_id = {str(row["game_id"]): row for row in rows}
    for team in ("S00", "S17", "S39"):
        keep = np.array([team not in (by_id[g]["home_id"], by_id[g]["away_id"]) for g in ids])
        gram = (x[keep] * w[keep, None]).T @ x[keep] + np.diag(base._penalty)
        beta = np.linalg.solve(gram, (x[keep] * w[keep, None]).T @ y[keep])
        fold = folds.fit(team)
        assert abs(fold.home_adv - beta[0]) < 1e-9
        for other, col in base._team_col.items():
            if other != team and base.conf[other] == INDEPENDENT:
                assert abs(fold.theta[other] - beta[col]) < 1e-9
    assert base.fit("S00").theta == Engine(games, PARAMS).fit("S00").theta  # the engine given is not changed


def test_weights_must_cover_every_fitted_game_and_be_positive() -> None:
    games = frame(season())
    engine = Engine(games, PARAMS)
    ids = core.fitted_games(games, engine)
    ones = dict.fromkeys(ids, 1.0)
    short = dict(ones)
    del short["w3-03"]
    for bad in ({}, short, ones | {"w1-00": 0.0}, ones | {"w1-00": float("nan")}, ones | {"w1-00": -1.0}):
        with pytest.raises(core.SensitivityError):
            core.weighted(engine, ids, bad)
    with pytest.raises(core.SensitivityError):
        core.weighted(engine, ids[:-1], ones)  # the ids must be the fit's rows


def test_unit_weights_reproduce_the_published_ledgers() -> None:
    rows = season()
    rows.append(fcs("f1", "S00", won=True) | {"home_conf": CONF["S00"]})
    rows.append(fcs("f2", "S05", won=False) | {"home_conf": CONF["S05"]})
    rows.append(game("title", "S00", "S06", 27, 24, week=9, title_game=True, neutral=True) | conf("S00"))
    games = frame(rows)
    plain = build_ledgers(games, PARAMS, T, 2026)
    ones = dict.fromkeys(core.fitted_games(games, Engine(games, PARAMS)), 1.0)
    again = core.weighted_totals(games, PARAMS, T, 2026, ones)
    assert again == {team: ledger.total_cp for team, ledger in plain.items()}
    drawn = core.game_weights(ones, seed=9)
    assert core.weighted_totals(games, PARAMS, T, 2026, drawn) != again  # and other weights do move it


def test_unit_weights_reproduce_the_rehearsal_edition_on_real_games() -> None:
    """All 138 totals of the golden rehearsal edition, from its 819 real games, through the refit's code."""
    from cfp.open_ranking.frozen import load_frozen
    from cfp.release.gate import games_from_lines

    from .test_golden_edition import ROOT, golden, rebuild

    meta, body = golden()
    games = games_from_lines(body)
    frozen = load_frozen(ROOT / "frozen", 2026)
    ones = dict.fromkeys(core.fitted_games(games, Engine(games, frozen.params)), 1.0)
    totals = core.weighted_totals(games, frozen.params, frozen.t, 2026, ones)
    edition = json.loads(rebuild(meta, body))
    assert totals == {team["team_id"]: team["total_cp"] for team in edition["teams"]}
    assert len(totals) == 138


def test_weights_are_exponential_with_mean_one() -> None:
    ids = [f"g{i:05d}" for i in range(20_000)]
    drawn = np.array(list(core.game_weights(ids, seed=1).values()))
    assert (drawn > 0).all()
    assert abs(drawn.mean() - 1.0) < 0.03
    assert abs(drawn.var() - 1.0) < 0.08
    assert abs(np.median(drawn) - np.log(2)) < 0.03
    assert core.game_weights(ids, seed=1) == core.game_weights(list(reversed(ids)), seed=1)  # by game id
    assert core.game_weights(ids, seed=1) != core.game_weights(ids, seed=2)


# --- seeds ---------------------------------------------------------------------


def test_one_seed_per_refit_so_any_refit_stands_alone() -> None:
    games = frame(season())
    seed = core.edition_seed("or-2026-20261122t0700z-replay-e1", "e" * 64)
    assert seed != core.edition_seed("or-2026-20261122t0700z-replay-e1", "f" * 64)
    assert len({core.refit_seed(seed, k) for k in range(1000)}) == 1000
    assert core.refit_seed(seed, 3) != core.refit_seed(seed + 1, 3)

    def run(indices: list[int], workers: int = 1) -> dict[int, str]:
        found = core.run(games, PARAMS, T, 2026, DRAW, seed=seed, indices=indices, workers=workers)
        assert [r.index for r in found] == indices
        return {r.index: r.digest() for r in found}

    whole = run(list(range(6)))
    assert len(set(whole.values())) == 6  # six different draws
    assert run([4]) == {4: whole[4]}  # alone
    assert run([5, 2, 0]) == {k: whole[k] for k in (5, 2, 0)}  # any order, any batch
    assert run(list(range(6)), workers=2) == whole  # in parallel
    one = core.run(games, PARAMS, T, 2026, DRAW, seed=seed, indices=[4])[0]
    assert one.seed == core.refit_seed(seed, 4)
    assert sorted(one.order) == sorted(TEAMS)
    assert set(one.totals) == set(one.ranks) == set(TEAMS)


def test_middle_80_leaves_at_most_a_tenth_beyond_each_end() -> None:
    assert core.middle80(list(range(1, 11))) == [2, 9]
    assert core.middle80([5, 1, 3]) == [1, 5]  # fewer than ten values: nothing can be left out
    values = list(range(1000))
    random.Random(3).shuffle(values)
    assert core.middle80(values) == [100, 899]
    assert core.middle80([7] * 50) == [7, 7]
    with pytest.raises(ValueError, match="no values"):
        core.middle80([])


# --- the bracket in each refit ---------------------------------------------------


def test_champion_stand_ins_are_held_fixed_and_the_group_place_follows_the_order() -> None:
    rules = load_rules(2026)
    order = TEAMS[:]  # S00 (acc) ... : the best acc team is S00, the best mountain-west team is S04
    setup = Setup(2026, order, CONF, ELIGIBLE, {}, {}, {}, {}, frozenset())
    stand_ins = field_today(setup, rules).stand_ins
    assert stand_ins == {"acc": "S00", "big-ten": "S01", "big-12": "S02", "sec": "S03"}
    moved = ["S06", "S10", "S16", *[t for t in TEAMS if t not in ("S06", "S10", "S16")]]
    entries = report.field_of(rules, moved, members=CONF, eligible=ELIGIBLE, champions=stand_ins)
    routes = {e.team_id: e.route for e in entries}
    assert routes["S00"] == "auto:acc"  # still the champion, though S06 (acc) is now placed above it
    assert routes["S06"] == "at_large"
    assert routes["S10"] == "auto:group"  # the six-conference place went to the best-placed team now
    assert len(entries) == 12
    with pytest.raises(report.SensitivityRefused):  # no champion and no stand-in for the sec
        report.field_of(
            rules, moved, members=CONF, eligible=ELIGIBLE, champions={"acc": "S00", "big-ten": "S01"}
        )


def test_cut_line_is_the_last_at_large_team() -> None:
    rules = load_rules(2026)
    champions = {"acc": "S00", "big-ten": "S01", "big-12": "S02", "sec": "S33"}  # S33 is far down the order
    entries = report.field_of(rules, TEAMS, members=CONF, eligible=ELIGIBLE, champions=champions)
    at_large = [e.team_id for e in entries if e.route == "at_large"]
    assert report.cut_line(entries, TEAMS) == max(at_large, key=TEAMS.index)
    assert report.cut_line(entries, TEAMS) != "S33"  # a champion below the cut is not the cut line


def test_champions_decided_in_the_edition_games_are_used() -> None:
    rows = season()
    rows.append(game("t-acc", "S00", "S06", 27, 24, week=9, title_game=True, neutral=True) | conf("S00"))
    assert report.decided_champions(frame(rows)) == {"acc": "S00"}
    rows.append(game("t-odd", "S01", "S02", 27, 24, week=9, title_game=True, neutral=True))
    with pytest.raises(report.SensitivityRefused):
        report.decided_champions(frame(rows))


def conf(team: str) -> dict[str, Any]:
    return {"home_conf": CONF[team], "away_conf": CONF[team]}


# --- the report ----------------------------------------------------------------


def test_sensitivity_outputs() -> None:
    games = frame(season())
    edition = published(games)
    out = built(games, refits=20)
    doc = out.doc
    assert json.loads(out.body) == doc
    assert not [k for k, v in walk(doc) if isinstance(v, float)]  # whole numbers only
    seed = core.edition_seed(edition["edition_id"], "e" * 64)
    assert (doc["edition_id"], doc["edition_sha256"]) == (edition["edition_id"], "e" * 64)
    assert (doc["seed"], doc["refits"], doc["code_hash"]) == (seed, 20, "abc1234")
    assert "sensitivity to the observed games" in doc["label"].lower()
    assert "not a full uncertainty interval" in doc["label"].lower()
    refits = core.run(games, PARAMS, T, 2026, DRAW, seed=seed, indices=range(20))
    assert doc["refit_digests"] == [r.digest() for r in refits]

    # the scenario: the published order's stand-ins, the same in every refit
    rules = load_rules(2026)
    order = [t["team_id"] for t in edition["teams"]]
    stand_ins = field_today(Setup(2026, order, CONF, ELIGIBLE, {}, {}, {}, {}, frozenset()), rules).stand_ins
    assert doc["scenario"]["provisional"] is True
    assert doc["scenario"]["stand_ins"] == stand_ins
    assert doc["scenario"]["champions"] == {}
    assert "stands in" in doc["scenario"]["note"]

    # every number for every team, worked again here from the refits
    rank = {t["team_id"]: t["open_rank"] for t in edition["teams"]}
    total = {t["team_id"]: t["total_cp"] for t in edition["teams"]}
    fields = [
        report.field_of(rules, r.order, members=CONF, eligible=ELIGIBLE, champions=stand_ins) for r in refits
    ]
    cuts = [report.cut_line(entries, r.order) for entries, r in zip(fields, refits, strict=True)]
    assert [row["team_id"] for row in doc["teams"]] == order
    for row in doc["teams"]:
        team = row["team_id"]
        moves = sorted(r.ranks[team] - rank[team] for r in refits)
        margins = sorted(r.totals[team] - r.totals[cut] for r, cut in zip(refits, cuts, strict=True))
        points = sorted(r.totals[team] - total[team] for r in refits)
        assert row["rank_diff_80"] == [moves[2], moves[17]]  # 20 refits: two may lie beyond each end
        assert row["rank_80"] == [rank[team] + moves[2], rank[team] + moves[17]]
        assert row["cut_margin_cp_80"] == [margins[2], margins[17]]
        assert row["points_diff_cp_80"] == [points[2], points[17]]
        assert row["qualifies"] == sum(1 for entries in fields if team in {e.team_id for e in entries})
    assert sum(row["qualifies"] for row in doc["teams"]) == 20 * 12
    now = report.field_of(rules, order, members=CONF, eligible=ELIGIBLE, champions=stand_ins)
    cut_now = report.cut_line(now, order)
    assert doc["cut_line"]["published"] == cut_now
    assert {row["team_id"]: row["cut_margin_cp"] for row in doc["teams"]} == {
        team: total[team] - total[cut_now] for team in order
    }
    assert built(games, refits=20).body == out.body  # the same bytes again
    assert built(games, refits=20, workers=2).body == out.body


def walk(value: Any, path: str = "") -> list[tuple[str, Any]]:
    if isinstance(value, dict):
        return [hit for k, v in value.items() for hit in walk(v, f"{path}/{k}")]
    if isinstance(value, list):
        return [hit for i, v in enumerate(value) for hit in walk(v, f"{path}/{i}")]
    return [(path, value)]


def test_selection_day_uses_the_actual_champions() -> None:
    rows = season()
    for k, league in enumerate(("acc", "big-ten", "big-12", "sec")):
        a, b = TEAMS[k + 6], TEAMS[k]  # the lower-numbered team loses its title game
        rows.append(game(f"t-{league}", a, b, 27, 24, week=9, title_game=True, neutral=True) | conf(a))
    games = frame(rows)
    doc = built(games, refits=10).doc
    assert doc["scenario"]["provisional"] is False
    assert doc["scenario"]["stand_ins"] == {}
    assert doc["scenario"]["champions"] == {"acc": "S06", "big-ten": "S07", "big-12": "S08", "sec": "S09"}
    assert "stands in" not in doc["scenario"]["note"]


def test_report_refuses_games_that_do_not_reproduce_the_edition() -> None:
    games = frame(season())
    edition = published(games)
    edition["teams"][0]["total_cp"] += 1
    with pytest.raises(report.SensitivityRefused, match="reproduce"):
        report.build_sensitivity(
            edition, "e" * 64, games, PARAMS, T, DRAW, members=CONF, eligible=ELIGIBLE, code_hash="x"
        )


# --- the gate's sample ---------------------------------------------------------


def test_gate_sample_is_chosen_by_the_edition_hash() -> None:
    first, second = report.gate_indices("e" * 64, 1000), report.gate_indices("f" * 64, 1000)
    assert len(first) == len(set(first)) == 10
    assert all(0 <= k < 1000 for k in first)
    assert first != second
    assert first != list(range(10))
    assert report.gate_indices("e" * 64, 1000) == first
    assert report.gate_indices("e" * 64, 4) == [0, 1, 2, 3]  # fewer refits than the sample: all of them


def test_verify_reruns_the_sampled_refits() -> None:
    games = frame(season())
    edition = published(games)
    out = built(games, refits=30)
    said = report.verify(out.doc, edition, "e" * 64, games, PARAMS, T, DRAW)
    assert "10 of 30" in said
    sample = report.gate_indices("e" * 64, 30)
    wrong = json.loads(out.body)
    wrong["refit_digests"][sample[3]] = "0" * 64
    with pytest.raises(report.SensitivityRefused, match=f"refit {sample[3]}"):
        report.verify(wrong, edition, "e" * 64, games, PARAMS, T, DRAW)
    other = json.loads(out.body)
    unsampled = next(k for k in range(30) if k not in sample)
    other["refit_digests"][unsampled] = "0" * 64
    report.verify(other, edition, "e" * 64, games, PARAMS, T, DRAW)  # a sample, and it says so
    with pytest.raises(report.SensitivityRefused, match="different edition"):
        report.verify(out.doc, edition, "f" * 64, games, PARAMS, T, DRAW)
    stale = json.loads(out.body) | {"seed": out.doc["seed"] + 1}
    with pytest.raises(report.SensitivityRefused, match="seed"):
        report.verify(stale, edition, "e" * 64, games, PARAMS, T, DRAW)


# --- the command, the gate and the page ----------------------------------------


def test_command_writes_once_and_the_page_shows_it(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    from cfp import cli
    from cfp.release.gate import CHECKS

    from . import sensitivity_world as world

    monkeypatch.setattr(cli, "_code_hash", lambda: "abc1234")
    world.setup(tmp_path)
    assert world.build(tmp_path) == 0
    edition = world.EDITION
    assert world.run(tmp_path, "publish", "--edition", edition, "--site", str(tmp_path / "before")) == 0
    before = (tmp_path / "before" / "open-ranking" / edition / "index.html").read_text()
    assert "Sensitivity intervals" in before  # listed as not delivered until the file exists
    assert world.sensitivity(tmp_path, "or-2026-20990101t0000z-replay-e1") == 1  # no such edition
    assert world.sensitivity(tmp_path, edition, "--refits", "12") == 0
    out = capsys.readouterr().out
    assert "12 refits" in out
    file = tmp_path / "lake" / "sensitivity" / edition / "sensitivity.json"
    doc = json.loads(file.read_bytes())
    body = (tmp_path / "lake" / "editions" / edition / "edition.json").read_bytes()
    from cfp.common.hashing import sha256_hex

    assert (doc["edition_id"], doc["edition_sha256"]) == (edition, sha256_hex(body))
    assert (doc["refits"], doc["code_hash"]) == (12, "abc1234")
    assert doc["seed"] == core.edition_seed(edition, sha256_hex(body))
    assert world.sensitivity(tmp_path, edition, "--refits", "12") == cli.EXIT_EXISTS  # written once
    assert json.loads(file.read_bytes()) == doc

    # the gate reruns a sample; the result is reported and never blocks the edition
    assert world.run(tmp_path, "gate", edition) == 0
    out = capsys.readouterr().out
    assert all(f"PASS  {name}" in out for name in CHECKS)
    assert "PASS  sensitivity" in out
    site = tmp_path / "site"
    assert world.run(tmp_path, "publish", "--edition", edition, "--site", str(site)) == 0
    public = site / "open-ranking" / edition
    assert (public / "sensitivity.json").read_bytes() == file.read_bytes()
    page = (public / "index.html").read_text()
    assert "Sensitivity to the observed games" in page
    assert "not a full uncertainty interval" in page
    assert "stands in" in page  # the scenario is stated
    assert "Sensitivity intervals" not in page  # no longer listed as not delivered
    assert "Rank-reversal report" in page
    gate = json.loads((public / "gate.json").read_text())
    assert gate["passed"] is True
    assert {c["name"]: c["blocking"] for c in gate["checks"]}["sensitivity"] is False


def test_a_bad_sensitivity_file_never_blocks_the_edition(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    from cfp import cli

    from . import sensitivity_world as world

    monkeypatch.setattr(cli, "_code_hash", lambda: "abc1234")
    world.setup(tmp_path)
    assert world.build(tmp_path) == 0
    edition = world.EDITION
    assert world.sensitivity(tmp_path, edition, "--refits", "12") == 0
    file = tmp_path / "lake" / "sensitivity" / edition / "sensitivity.json"
    doc = json.loads(file.read_bytes())
    doc["refit_digests"] = ["0" * 64] * 12
    file.parent.chmod(0o755)
    file.chmod(0o644)
    file.write_text(json.dumps(doc))
    capsys.readouterr()
    assert world.run(tmp_path, "gate", edition) == 0  # the edition's own checks still pass
    out = capsys.readouterr().out
    assert "FAIL  sensitivity" in out
    assert "gate passed" in out
    site = tmp_path / "site"
    assert world.run(tmp_path, "publish", "--edition", edition, "--site", str(site)) == 0
    public = site / "open-ranking" / edition
    assert not (public / "sensitivity.json").exists()
    page = (public / "index.html").read_text()
    assert "Sensitivity intervals" in page  # back to not delivered
    assert "Sensitivity to the observed games" not in page
