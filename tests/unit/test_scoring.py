"""Scoring (VT-10 to VT-14): weekly rank score, field scores, bracket integrity, promotion, replay."""

from __future__ import annotations

import dataclasses
from pathlib import Path

import pytest

from cfp.forecast.noise_params import Example
from cfp.forecast.promotion import Scores, decide
from cfp.rules.engine import Entry
from cfp.scoring.field import FieldRow, bubble_cohort, field_scores
from cfp.scoring.integrity import IntegrityError, check_path, check_section
from cfp.scoring.replay import LossDrop, expanding_folds, replay_final, replay_weekly
from cfp.scoring.weekly import (
    cumulative_from_counts,
    movement,
    rank_error,
    score_weekly,
    secondary_cohort,
    top25_scores,
    weekly_score,
)

TEAMS = [f"T{k:02d}" for k in range(1, 51)]
ACTUAL = TEAMS[:25]


def certain(order: list[str]) -> dict[str, list[float]]:
    """A forecast that puts each team at one rank with certainty."""
    return {team: [1.0 if k >= place else 0.0 for k in range(1, 26)] for place, team in enumerate(order, 1)}


# --- VT-11 -------------------------------------------------------------------------


def test_weekly_score_perfect_is_zero() -> None:
    assert weekly_score(certain(TEAMS), ACTUAL, TEAMS) == 0.0
    swapped = [TEAMS[1], TEAMS[0], *TEAMS[2:]]
    # two teams one slot out: each is wrong at one cutoff (k = 1) by 1.0
    assert weekly_score(certain(swapped), ACTUAL, TEAMS) == pytest.approx(2 / (25 * 50))


def test_weekly_score_uniform_hand_computed() -> None:
    """Fifty teams, each equally likely at every rank: P(r <= k) = k/50.

    At cutoff k, k teams are inside (error 1 - k/50) and 50 - k outside (error k/50), which sums to
    50 a (1 - a) with a = k/50. S = (1/25) * sum over k = 1..25 of a (1 - a) = (6.5 - 2.21) / 25 = 0.1716.
    """
    uniform = {team: [k / 50 for k in range(1, 26)] for team in TEAMS}
    assert weekly_score(uniform, ACTUAL, TEAMS) == pytest.approx(0.1716)
    # a team with no forecast row is scored as given no chance, not skipped
    missing = {team: row for team, row in uniform.items() if team != "T50"}
    assert weekly_score(missing, ACTUAL, TEAMS) > weekly_score(uniform, ACTUAL, TEAMS) - 0.01
    assert weekly_score(missing, ACTUAL, TEAMS) != weekly_score(uniform, ACTUAL, TEAMS)
    with pytest.raises(ValueError, match="25"):
        weekly_score({"T01": [1.0] * 24}, ACTUAL, TEAMS)
    with pytest.raises(ValueError, match="not among"):
        weekly_score(uniform, ["ZZ", *ACTUAL[1:]], TEAMS)


def test_cumulative_from_counts() -> None:
    counts = [0] * 26
    counts[0], counts[2], counts[25] = 500, 300, 200
    got = cumulative_from_counts(counts, 1000)
    assert got[:3] == [0.5, 0.5, 0.8]
    assert got[24] == 0.8
    assert len(got) == 25
    with pytest.raises(ValueError, match="paths"):
        cumulative_from_counts(counts, 999)


def test_secondary_cohort() -> None:
    """VT-11a: the forecast's top 35 together with the actual top 25, each team once."""
    order = TEAMS[5:] + TEAMS[:5]  # the forecast leaves the actual top five at the bottom
    cohort = secondary_cohort(order, ACTUAL)
    assert len(cohort) == 40
    assert set(cohort) == set(order[:35]) | set(ACTUAL)
    card = score_weekly("m", order, certain(order), ACTUAL, TEAMS, prior=TEAMS[:25])
    assert card["teams"] == 50
    assert card["secondary"]["teams"] == 40
    assert card["secondary"]["score"] > card["score"]  # the same errors over fewer teams


def test_entrants_exits_slots_and_rank_error() -> None:
    prior = TEAMS[:25]
    actual = [*TEAMS[:23], "T30", "T31"]  # T24 and T25 dropped out; T30 and T31 came in
    order = [*TEAMS[:22], "T24", "T23", "T30", *TEAMS[25:29], *TEAMS[31:], "T25", "T31"]
    moved = movement(prior, order[:25], actual)
    assert moved["entrants"] == ["T30", "T31"]
    assert moved["exits"] == ["T24", "T25"]
    assert moved["entrants_called"] == ["T30"]
    assert moved["exits_called"] == ["T25"]
    card = score_weekly("m", order, certain(order), actual, TEAMS, prior=prior)
    assert card["exact_slots"] == 22
    error = rank_error(order, actual)
    # jointly ranked: the 22 exact, T23 (forecast 24, actual 23) and T30 (forecast 25, actual 24)
    assert error["jointly_ranked"] == 24
    assert error["coverage"] == pytest.approx(24 / 25)
    assert error["mean_abs_error"] == pytest.approx(2 / 24)


def test_top25_scores_put_raw_and_calibrated_on_the_same_teams() -> None:
    raw = {"A": 0.9, "B": 0.6, "C": 0.1}
    cal = {"A": 0.8, "B": 0.5}
    got = top25_scores(raw, cal, actual=["A"])
    assert got["raw"]["n"] == got["calibrated"]["n"] == 2  # C has no calibrated value and is left out of both
    assert got["raw"]["brier"] == pytest.approx((0.01 + 0.36) / 2)
    assert got["calibrated"]["brier"] == pytest.approx((0.04 + 0.25) / 2)
    assert got["raw_all_teams"]["n"] == 3


# --- VT-12 -------------------------------------------------------------------------


def rows() -> list[FieldRow]:
    return [
        FieldRow(2025, "sun0200", "12-team", "A", 0.9, 0.5, True, True, 0.6, 0.3, "automatic", True),
        FieldRow(2025, "sun0200", "12-team", "B", 0.6, 0.1, True, False, 0.1, 0.6, "at_large", True),
        FieldRow(2025, "sun0200", "12-team", "C", 0.2, 0.1, False, False, 0.1, 0.2, None, False),
        FieldRow(2024, "tminus60", "12-team", "A", 0.5, 0.2, False, False, 0.1, 0.4, None, True),
    ]


def test_field_scores_by_stratum() -> None:
    got = field_scores(rows())
    assert got["overall"]["field"]["n"] == 4
    assert got["overall"]["field"]["brier"] == pytest.approx((0.01 + 0.16 + 0.04 + 0.25) / 4)
    assert got["overall"]["bye"]["brier"] == pytest.approx((0.25 + 0.01 + 0.01 + 0.04) / 4)
    assert set(got["by"]) == {"lead", "season", "era", "route", "bubble"}
    assert got["by"]["season"]["2025"]["field"]["n"] == 3
    assert got["by"]["lead"]["tminus60"]["field"]["brier"] == pytest.approx(0.25)
    assert got["by"]["era"]["12-team"]["field"]["n"] == 4
    assert got["by"]["bubble"]["bubble"]["field"]["n"] == 3
    assert got["by"]["bubble"]["other"]["field"]["n"] == 1
    # a route is its own event: did the team qualify that way
    assert got["by"]["route"]["automatic"]["brier"] == pytest.approx((0.16 + 0.01 + 0.01 + 0.01) / 4)
    assert got["by"]["route"]["at_large"]["brier"] == pytest.approx((0.09 + 0.16 + 0.04 + 0.16) / 4)
    assert got["overall"]["field"]["log_loss"] > 0
    with pytest.raises(ValueError, match="never 0 or 1"):
        field_scores([FieldRow(2025, "sun0200", "12-team", "A", 1.0, 0.5, True, True, 0.6, 0.3, None, True)])


def test_bubble_cohort_frozen_at_issue() -> None:
    """VT-12: within five Baseline 2 places of the projected last at-large team; one cohort for all."""
    order = TEAMS[:40]
    cohort = bubble_cohort(order, "T11")
    assert cohort == frozenset(TEAMS[5:16])
    assert bubble_cohort(order, "T02") == frozenset(TEAMS[:7])
    with pytest.raises(ValueError, match="not in"):
        bubble_cohort(order, "ZZ")
    # another model's order, or what happened later, never changes who is in it
    one = [
        FieldRow(2025, "sun0200", "12-team", t, 0.5, 0.1, False, False, 0.1, 0.4, None, t in cohort)
        for t in order
    ]
    two = [
        FieldRow(2025, "sun0200", "12-team", t, 0.3, 0.1, t == "T30", False, 0.1, 0.2, None, t in cohort)
        for t in order
    ]
    assert field_scores(one)["by"]["bubble"]["bubble"]["field"]["n"] == 11
    assert field_scores(two)["by"]["bubble"]["bubble"]["field"]["n"] == 11


# --- VT-13 -------------------------------------------------------------------------


def entries(n: int = 12, byes: int = 4) -> list[Entry]:
    out = []
    for seed in range(1, n + 1):
        host = 1 if byes < seed <= byes + (n - byes) // 2 else None
        out.append(Entry(f"S{seed}", seed, True, "at_large", seed, seed <= byes, host, ""))
    return out


def test_integrity_sums_and_uniqueness() -> None:
    check_path(entries(), field=12, byes=4, hosts=4)
    twice = entries()
    twice[5] = Entry("S6", 6, True, "at_large", 5, False, 1, "")  # two teams hold seed 5
    with pytest.raises(IntegrityError, match="seed"):
        check_path(twice, field=12, byes=4, hosts=4)
    same = entries()
    same[3] = Entry("S1", 4, True, "at_large", 4, True, None, "")  # one team twice
    with pytest.raises(IntegrityError, match="twice"):
        check_path(same, field=12, byes=4, hosts=4)
    with pytest.raises(IntegrityError, match="bye"):
        check_path(entries(byes=3), field=12, byes=4, hosts=4)
    teams = [
        {
            "team_id": f"S{s}",
            "field_paths": 100,
            "bye_paths": 100 if s <= 4 else 0,
            "seed_paths": {str(s): 100},
            "host_paths": {"1": 100 if 4 < s <= 8 else 0},
        }
        for s in range(1, 13)
    ]
    section = {"paths": 100, "forecast": {"teams": teams}, "scenarios": None}
    check_section(section, field=12, byes=4, hosts=4)
    teams[0]["field_paths"] = 99
    with pytest.raises(IntegrityError, match="field"):
        check_section(section, field=12, byes=4, hosts=4)
    teams[0]["field_paths"] = 100
    teams[1]["seed_paths"] = {"1": 100}
    with pytest.raises(IntegrityError, match="seed 1"):
        check_section(section, field=12, byes=4, hosts=4)


# --- VT-14 -------------------------------------------------------------------------


def test_promotion_rule() -> None:
    base = Scores(primary=0.100, bubble_brier=0.200)
    assert decide(base, Scores(0.090, 0.205), seasons=9).promote  # better, and bubble Brier within 0.01
    assert decide(base, Scores(0.090, 0.210), seasons=9).promote  # exactly 0.01 worse is allowed
    worse_bubble = decide(base, Scores(0.090, 0.2101), seasons=9)
    assert not worse_bubble.promote
    assert "bubble" in worse_bubble.reason
    no_gain = decide(base, Scores(0.100, 0.150), seasons=9)
    assert not no_gain.promote  # the primary score must improve, not tie
    assert "primary" in no_gain.reason
    pilot = decide(base, Scores(0.050, 0.100), seasons=1)
    assert not pilot.promote  # one season is a pilot
    assert "pilot" in pilot.reason
    missing = decide(base, Scores(0.050, None), seasons=9)
    assert not missing.promote  # no bubble Brier, no decision
    assert "bubble" in missing.reason


# --- VT-10 -------------------------------------------------------------------------


def history() -> list[Example]:
    out = []
    for season in range(2014, 2021):
        for number in range(2, 6):
            for issue in ("sun0200", "tminus60"):
                shift = (season + number) % 3
                losses = {TEAMS[k]: 1 for k in range(shift)}
                order = sorted(TEAMS, key=lambda t, losses=losses: TEAMS.index(t) + 5 * losses.get(t, 0))
                actual = order[:25]
                j = (season * 7 + number) % 20
                actual[j], actual[j + 1] = actual[j + 1], actual[j]
                out.append(Example(season, number, issue, "weekly", TEAMS, order, actual, TEAMS, losses, 6))
    return out


def test_expanding_replay_no_future_seasons() -> None:
    assert expanding_folds(range(2014, 2021)) == [
        ((2014, 2015, 2016), 2017),
        ((2014, 2015, 2016, 2017), 2018),
        ((2014, 2015, 2016, 2017, 2018), 2019),
        ((2014, 2015, 2016, 2017, 2018, 2019), 2020),
    ]
    with pytest.raises(ValueError, match="2014"):
        expanding_folds(range(2015, 2021))
    seen: list[tuple[int, list[int]]] = []

    class Spy(LossDrop):
        def fit(self, train: list[Example]) -> dict[str, float]:  # type: ignore[override]
            found = super().fit(train)
            seen.append((max(e.season for e in train), sorted({e.season for e in train})))
            return found

    report = replay_weekly(history(), Spy("five", 5.0), paths=500)
    assert [s for s in report["seasons"]] == ["2017", "2018", "2019", "2020"]
    assert [latest for latest, _ in seen] == [2016, 2017, 2018, 2019]  # only earlier seasons, every time
    assert seen[0][1] == [2014, 2015, 2016]  # the initial training window
    assert 0 <= report["score"] < 0.1
    assert report["releases"] == 4 * 4 * 2
    assert report == replay_weekly(history(), LossDrop("five", 5.0), paths=500)  # recorded seeds
    # a model that drops losers further than they fell scores worse on this history
    assert replay_weekly(history(), LossDrop("twenty", 20.0), paths=500)["score"] > report["score"]


def finals() -> list[Example]:
    """Six Selection Days. The No. 1 team loses its title game and finishes third, not sixth."""
    out = []
    for season in range(2014, 2020):
        fall = 2 if season < 2019 else 9  # 2019 breaks the pattern, and no earlier fold may know it
        actual = [*TEAMS[1 : 1 + fall], TEAMS[0], *TEAMS[1 + fall : 25]]
        j = 6 + season % 10
        actual[j], actual[j + 1] = actual[j + 1], actual[j]
        out.append(Example(season, 6, "sun0200", "final", TEAMS, TEAMS, actual, TEAMS, {TEAMS[0]: 1}, 6))
    return out


def test_replay_final_applies_the_promotion_rule() -> None:
    weekly = [e for e in history() if e.issue == "sun0200"]
    leagues = {season: dict.fromkeys(TEAMS, "sec") for season in range(2014, 2020)}
    report = replay_final(finals(), weekly, champions={}, conference_of=leagues, paths=2000)
    assert report["held_out"] == [2017, 2018, 2019]
    folds = report["seasons"]
    # the title-week drop is fitted on earlier Selection Days only: 2019's nine-place fall is never seen
    # (finishing third from first is a drop of 3.0 in the model: 2.5 and 3.0 fit equally and the grid's
    # larger value is kept)
    assert [folds[s]["models"]["pilot_unshrunk"]["drop_title"] for s in ("2017", "2018", "2019")] == [3.0] * 3
    assert folds["2017"]["trained_on"] == [2014, 2015, 2016]
    assert folds["2017"]["models"]["baseline"]["drop_title"] == 5.0
    assert len(folds["2017"]["bubble"]) <= 11
    base, pilot = report["models"]["baseline"], report["models"]["pilot_unshrunk"]
    assert base["n"] == pilot["n"] == 3 * 50  # the same teams for every model
    assert base["bubble_n"] == pilot["bubble_n"]  # and the same bubble cohort
    for season in ("2017", "2018"):  # a short fall keeps the loser in a field of four, as the candidate says
        assert pilot["by_season"][season] < base["by_season"][season]
    assert pilot["by_season"]["2019"] > base["by_season"]["2019"]  # and the year the pattern broke costs it
    assert pilot["log_loss_sum"] == pytest.approx(sum(pilot["by_season"].values()))
    ruling = report["decisions"]["pilot_unshrunk"]
    assert pilot["log_loss_sum"] > base["log_loss_sum"]
    assert ruling["promote"] is False
    assert "primary" in ruling["reason"]
    assert report["decisions"]["pilot_unshrunk"]["seasons"] == 3
    assert report == replay_final(finals(), weekly, champions={}, conference_of=leagues, paths=2000)
    with pytest.raises(ValueError, match="2018"):
        replay_final(finals(), weekly, champions={}, conference_of={2017: leagues[2017]}, paths=2000)


def test_score_replay_command_reports_and_writes_nothing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    from cfp import cli

    weekly = history()
    both = [dataclasses.replace(e, issue=issue) for e in finals() for issue in ("sun0200", "tminus60")]
    leagues = {season: dict.fromkeys(TEAMS, "sec") for season in range(2014, 2021)}
    monkeypatch.setattr("cfp.release.history.past_examples", lambda *a, **k: ([*weekly, *both], ["a note"]))
    monkeypatch.setattr("cfp.release.history.past_champions", lambda *a, **k: ({}, leagues, []))
    monkeypatch.setattr("cfp.open_ranking.frozen.load_frozen", lambda *a, **k: None)
    argv = ["--lake", str(tmp_path / "lake"), "--data", "data", "score-replay", "--season", "2026"]
    assert cli.main([*argv, "--paths", "500", "--drop", "9"]) == 0
    out = capsys.readouterr().out
    assert "a note" in out
    assert "weekly rank score" in out
    assert "drop 9" in out
    assert "rule: promote False (primary score did not improve" in out  # losers fall five places here
    assert "Selection Day, sun0200" in out
    assert "pilot_unshrunk" in out
    assert "report only" in out
    assert not (tmp_path / "lake").exists()
