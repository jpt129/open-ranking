"""Final-field forecast (FF-03, FF-04, FF-05): simulated results, a sampled order, the season's rules."""

from __future__ import annotations

import numpy as np
import pytest

from cfp.forecast.final_field import BASELINE, FieldError, Model, Setup, field_today, run
from cfp.forecast.simulator import Game, simulate
from cfp.rules.engine import load_rules

N = 2000
TEAMS = [f"R{k:02d}" for k in range(1, 41)]
POWER = {"sec": ("R01", "R06"), "big-ten": ("R02", "R09"), "big-12": ("R03", "R14"), "acc": ("R05", "R16")}
GROUP = {"sun-belt": ("R22", "R30"), "mid-american": ("R27", "R33")}


def league() -> dict[str, str]:
    out = {team: "sec" for team in TEAMS}
    out["R04"] = "fbs-independents"
    for conference, pair in (POWER | GROUP).items():
        for team in pair:
            out[team] = conference
    return out


def games() -> list[Game]:
    out = []
    for conference, (home, away) in (POWER | GROUP).items():
        out.append(Game(f"title-{conference}", home, away, 0.6))
    return out


def setup(**over: object) -> Setup:
    base: dict[str, object] = {
        "season": 2026,
        "initial": TEAMS,
        "conference_of": league(),
        "eligible": {},
        "regular_losses": {},
        "title_losses": {},
        "champions": {},
        "title_games": {f"title-{conference}": conference for conference in (POWER | GROUP)},
        "title_week": frozenset(f"title-{conference}" for conference in (POWER | GROUP)),
    }
    return Setup(**(base | over))  # type: ignore[arg-type]


PILOT = Model("pilot", drop_regular=9.0, drop_title=4.0, tau=1.3)


def test_field_and_bye_sums_match_era() -> None:
    paths = simulate(games(), N, a=0.0, seed=4)
    out = run(setup(), paths, load_rules(2026), BASELINE.with_tau(1.3), seed=11)
    assert out.paths == N
    assert sum(out.field.values()) == 12 * N
    assert sum(out.bye.values()) == 4 * N
    assert sum(out.host[1].values()) == 4 * N  # seeds 5 to 8 host round one
    assert all(sum(counts.values()) == out.field[team] for team, counts in out.seeds.items())
    for seed in range(1, 13):
        assert sum(counts.get(seed, 0) for counts in out.seeds.values()) == N  # one team per seed per path
    assert out.field["R01"] > out.field["R12"] > out.field["R20"]
    assert out.routes["R04"].get("guarantee", 0) + out.routes["R04"].get("at_large", 0) == out.field["R04"]
    # the four-team era: no byes, no hosts, four in
    old = run(
        setup(season=2019, title_games={}, title_week=frozenset()), paths, load_rules(2019), PILOT, seed=11
    )
    assert (sum(old.field.values()), sum(old.bye.values())) == (4 * N, 0)
    # 2027: 24 in, eight byes
    big = run(setup(season=2027), paths, load_rules(2027), PILOT, seed=11)
    assert (sum(big.field.values()), sum(big.bye.values())) == (24 * N, 8 * N)


def test_conditionals_with_path_counts() -> None:
    paths = simulate(games(), N, a=0.0, seed=4)
    out = run(setup(), paths, load_rules(2026), PILOT, seed=11)
    cond = out.conditionals["R14"]  # the Big 12 title game's away side, ranked 14th
    assert cond.game_id == "title-big-12"
    assert cond.win_paths + cond.lose_paths == N
    assert cond.win_paths == int((~paths.home_won[:, paths.game_ids.index("title-big-12")]).sum())
    assert cond.field_if_win == cond.win_paths  # a named champion is always in
    assert cond.field_if_lose < cond.lose_paths
    assert cond.field_if_win + cond.field_if_lose == out.field["R14"]
    assert "R20" not in out.conditionals  # no game left


def test_baseline_same_paths() -> None:
    paths = simulate(games(), N, a=0.0, seed=4)
    one = run(setup(), paths, load_rules(2026), BASELINE.with_tau(1.3), seed=11)
    two = run(setup(), paths, load_rules(2026), PILOT, seed=11)
    assert one.paths_seed == two.paths_seed == 4
    assert one.order_seed == two.order_seed == 11
    assert one.champion_paths == two.champion_paths  # the same simulated champions on every path
    assert one.field != two.field  # only the drop differs
    again = run(setup(), paths, load_rules(2026), PILOT, seed=11)
    assert again.field == two.field
    assert again.seeds == two.seeds
    # losses already on the books move the starting order: five places each in the baseline
    hurt = run(setup(regular_losses={"R10": 2}), paths, load_rules(2026), BASELINE.with_tau(1.3), seed=11)
    assert hurt.field["R10"] < one.field["R10"]
    assert BASELINE.drop_regular == BASELINE.drop_title == 5.0


def test_scenarios_when_tiebreak_input_missing() -> None:
    paths = simulate([g for g in games() if g.game_id != "title-sec"], N, a=0.0, seed=4)
    lacking = setup(
        title_games={k: v for k, v in setup().title_games.items() if v != "sec"},
        title_week=frozenset(k for k in setup().title_week if k != "title-sec"),
    )
    with pytest.raises(FieldError, match="no champion or title game for sec"):
        run(lacking, paths, load_rules(2026), PILOT, seed=11)
    # a known champion needs no game
    done = run(
        setup(**(vars(lacking) | {"champions": {"sec": "R01"}})), paths, load_rules(2026), PILOT, seed=11
    )
    assert done.field["R01"] == N
    with pytest.raises(FieldError, match="both decided and still to play"):
        run(
            setup(champions={"sec": "R01"}),
            simulate(games(), N, a=0.0, seed=4),
            load_rules(2026),
            PILOT,
            seed=11,
        )


def test_field_today_uses_stand_in_champions() -> None:
    today = field_today(setup(), load_rules(2026))
    seeds = {entry.seed: entry.team_id for entry in today.entries if entry.seed}
    assert len(seeds) == 12
    assert today.stand_ins == {"sec": "R01", "big-ten": "R02", "big-12": "R03", "acc": "R05"}
    assert seeds[1] == "R01"
    assert "R22" in seeds.values()  # the best team of the group


def test_paths_and_order_noise_are_seeded() -> None:
    paths = simulate(games(), 200, a=0.0, seed=4)
    for bad in (None, True, -1):
        with pytest.raises(ValueError, match="recorded seed"):
            run(setup(), paths, load_rules(2026), PILOT, seed=bad)  # type: ignore[arg-type]
    cold = run(setup(), paths, load_rules(2026), Model("cold", 5.0, 5.0, 1e-6), seed=1)
    assert set(np.unique(list(cold.field.values()))) <= set(range(201))
    assert cold.field["R01"] == 200


def test_path_recomputes_open_points() -> None:
    """FF-03: a path's simulated games change open points exactly as real games would."""
    from cfp.forecast.final_field import open_points_on_path

    from .test_ledger import PARAMS, T, frame, game, league, totals

    played = league()
    extra = [game("sim-1", "T01", "T02", 31, 17), game("sim-2", "T03", "T04", 10, 24)]
    before = totals(played)
    after = open_points_on_path(frame(played), frame(extra), PARAMS, T, 2026)
    assert after == totals(played + extra)  # the same numbers as a snapshot that held those games
    assert after["T01"] > before["T01"]  # a simulated win adds points
    assert after["T03"] < before["T03"]
    flipped = [game("sim-1", "T01", "T02", 17, 31), extra[1]]
    other = open_points_on_path(frame(played), frame(flipped), PARAMS, T, 2026)
    assert after["T01"] - other["T01"] == 10000  # an ordinary flip moves a total by exactly 10000
