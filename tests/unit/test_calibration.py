"""The calibrated disclosure column (SC-05): monotone maps from published probability to frequency."""

from __future__ import annotations

import itertools
from datetime import timedelta
from pathlib import Path

import numpy as np
import pytest

from cfp.forecast.calibration import (
    QUANTITIES,
    CalibrationError,
    apply_map,
    fit_calibration,
    fit_map,
    forecast_rows,
    leave_one_season_out,
    load_calibration,
    reliability,
    scores,
    write_calibration,
)
from cfp.forecast.noise_params import Example, fit_noise, load_noise, release_kind, write_noise
from cfp.forecast.rank_noise import sample_orders

from .test_issue import PRIOR, REVEAL, issue, world
from .test_noise import examples as noise_examples

FLOOR = 0.5 / 10_000
TEAMS = [f"T{k:03d}" for k in range(60)]
SEASONS = (2019, 2020, 2021, 2022, 2023, 2024, 2025)
TAUS = {"sun0200": 2.0, "tminus60": 2.0}


def test_isotonic_fit_pools_violators_and_is_monotone() -> None:
    found = fit_map([0.1, 0.2, 0.3, 0.4], [0, 1, 0, 1])
    got = [round(apply_map(found, p, FLOOR), 6) for p in (0.1, 0.2, 0.3, 0.4)]
    assert got == [0.25, 0.5, 0.5, 0.75]  # a lone miss or hit is half an event short of 0 or 1
    rng = np.random.default_rng(3)
    p = rng.uniform(0, 1, 5000)
    y = (rng.uniform(0, 1, 5000) < p**2).astype(int)  # published probabilities that run too high
    learned = fit_map(p.tolist(), y.tolist())
    out = [apply_map(learned, float(g), FLOOR) for g in np.linspace(0, 1, 501)]
    assert all(b >= a for a, b in itertools.pairwise(out))  # never decreasing
    assert all(FLOOR <= v <= 1 - FLOOR for v in out)  # never 0 or 1
    assert abs(apply_map(learned, 0.5, FLOOR) - 0.25) < 0.08
    assert abs(apply_map(learned, 0.9, FLOOR) - 0.81) < 0.08
    with pytest.raises(CalibrationError):
        fit_map([], [])
    with pytest.raises(CalibrationError):
        fit_map([0.2, 1.2], [0, 1])


def test_equal_probabilities_share_one_value_and_gaps_are_interpolated() -> None:
    found = fit_map([0.2, 0.2, 0.2, 0.2, 0.8, 0.8], [0, 0, 0, 1, 1, 1])
    top = 1 - 0.5 / 3  # two hits out of two: half an event short of certain
    assert apply_map(found, 0.2, FLOOR) == pytest.approx(0.25)
    assert apply_map(found, 0.8, FLOOR) == pytest.approx(top)
    assert apply_map(found, 0.5, FLOOR) == pytest.approx((0.25 + top) / 2)  # halfway across the gap
    assert apply_map(found, 0.0, FLOOR) == pytest.approx(0.25)  # outside the fitted range: the end value
    assert apply_map(found, 1.0, FLOOR) == pytest.approx(top)


def test_reliability_table_and_scores() -> None:
    table = reliability([0.1, 0.1, 0.9, 0.9], [0, 1, 1, 1], edges=(0.0, 0.5, 1.0))
    assert [(r["n"], r["mean_forecast"], r["observed"]) for r in table] == [(2, 0.1, 0.5), (2, 0.9, 1.0)]
    found = scores([0.5, 0.5], [1, 0])
    assert found["brier"] == pytest.approx(0.25)
    assert found["log_loss"] == pytest.approx(0.6931, abs=1e-4)
    assert found["n"] == 2


def past(shaken: bool = True) -> list[Example]:
    """Past releases against a baseline that is plain order TEAMS.

    With `shaken`, six of the baseline's top 25 fall ten places before a little noise is added, as ranked
    teams that lose do: no single temperature describes that, so the raw probabilities are off. Without it
    the committee is the baseline plus noise, and the raw probabilities are already right.
    """
    out = []
    for season in SEASONS:
        for number in range(1, 7):
            for which in ("sun0200", "tminus60"):
                seed = season * 100 + number + (which == "sun0200")
                base = list(range(60))
                if shaken:
                    rng = np.random.default_rng(seed)
                    fallen = set(rng.choice(25, size=6, replace=False).tolist())
                    base = sorted(base, key=lambda k, fallen=fallen: k + 10.5 if k in fallen else k)
                drawn = sample_orders(60, 1.5 if shaken else 2.0, 1, seed=seed)[0]
                actual = [TEAMS[base[i]] for i in drawn[:25]]
                out.append(Example(season, number, which, release_kind(number, 6), TEAMS, TEAMS, actual))
    return out


def test_forecast_rows_cover_weekly_releases_only_with_recorded_seeds() -> None:
    rows = forecast_rows(past(), TAUS, paths=2000)
    weekly = len(SEASONS) * 4  # six releases a season: one opening, four weekly, one final
    assert len(rows) == weekly * 2 * 60 * len(QUANTITIES)
    assert {r.quantity for r in rows} == set(QUANTITIES)
    assert rows == forecast_rows(past(), TAUS, paths=2000)  # seeded
    top = [r for r in rows if r.quantity == "top25" and r.issue == "sun0200"]
    assert sum(r.y for r in top) == weekly * 25
    assert all(0 < r.p < 1 for r in rows)


def test_leave_one_season_out_never_fits_a_season_on_itself() -> None:
    data = past()
    report = leave_one_season_out(data, paths=2000)
    cell = report["cells"]["sun0200"]["top25"]
    assert cell["after"]["log_loss"] < cell["before"]["log_loss"]  # the map repairs a misshapen forecast
    assert cell["after"]["brier"] <= cell["before"]["brier"]
    assert cell["verified"] is True
    assert report["seasons"] == list(SEASONS)
    assert sum(r["n"] for r in cell["reliability_before"]) == cell["before"]["n"]
    assert sum(r["n"] for r in cell["reliability_after"]) == cell["after"]["n"]
    # change one season's outcomes: its own calibrated values must not move; another season's do
    spoiled = [
        Example(e.season, e.release_no, e.issue, e.kind, e.baseline1, e.baseline2, TEAMS[::-1][:25])
        if e.season == 2022
        else e
        for e in data
    ]
    again = leave_one_season_out(spoiled, paths=2000)
    assert again["held_out"][2022] == report["held_out"][2022]
    assert again["held_out"][2023] != report["held_out"][2023]


def test_a_map_that_does_not_help_is_not_verified() -> None:
    # forecasts that are already right: a map has nothing to repair, and fitting one only adds noise
    cells = leave_one_season_out(past(shaken=False), paths=2000)["cells"]
    flags = [cells[i][q]["verified"] for i in cells for q in cells[i]]
    assert all(isinstance(flag, bool) for flag in flags)
    assert not all(flags)


def test_calibration_file_is_written_once_and_checked(tmp_path: Path) -> None:
    doc = fit_calibration(past(), 2026, taus=TAUS, paths=2000)
    assert doc["trained_on"] == list(SEASONS)
    assert "held_out" not in doc["verification"]
    with pytest.raises(CalibrationError, match="earlier season"):
        fit_calibration(past(), 2025, taus=TAUS, paths=2000)
    path, digest = write_calibration(tmp_path, 2026, doc)
    loaded = load_calibration(tmp_path, 2026)
    assert loaded.sha256 == digest
    assert loaded.verified("sun0200", "top25")
    assert not loaded.verified("sun0200", "nothing")
    assert 0 < loaded.value("sun0200", "top25", 0.5) < 1
    with pytest.raises(CalibrationError, match="no map"):
        loaded.value("sun0200", "nothing", 0.5)
    with pytest.raises(CalibrationError, match="never rewritten"):
        write_calibration(tmp_path, 2026, doc)
    path.chmod(0o644)
    path.write_text(path.read_text() + " ")
    with pytest.raises(CalibrationError, match="recorded hash"):
        load_calibration(tmp_path, 2026)
    with pytest.raises(CalibrationError, match="no calibration"):
        load_calibration(tmp_path / "none", 2026)


def test_issue_carries_a_labelled_calibrated_column_for_weekly_forecasts_only(tmp_path: Path) -> None:
    write_noise(tmp_path / "p", 2026, fit_noise(noise_examples(), 2026))
    noise = load_noise(tmp_path / "p", 2026)
    write_calibration(tmp_path / "p", 2026, fit_calibration(past(), 2026, taus=TAUS, paths=2000))
    maps = load_calibration(tmp_path / "p", 2026)
    plain = issue(world(tmp_path / "a"), noise=noise).doc
    assert plain["rank_noise"]["calibration"] is None
    assert "calibrated" not in plain["forecasts"]["baseline2"]["rows"][0]
    # the test world's issue forecasts the season's last release: the maps are for weekly releases only
    final = issue(world(tmp_path / "b"), noise=noise, calibration=maps).doc
    assert final["rank_noise"]["kind"] == "final"
    assert "calibrated" not in final["forecasts"]["baseline2"]["rows"][0]
    assert "weekly" in final["rank_noise"]["calibration"]["left_out"]
    assert final["rank_noise"]["calibration"]["published"] == []
    # with a later reveal on the schedule the same issue is a weekly one
    reveals = [PRIOR, REVEAL, REVEAL + timedelta(days=5)]
    doc = issue(world(tmp_path / "c"), noise=noise, calibration=maps, reveals=reveals).doc
    assert doc["rank_noise"]["kind"] == "weekly"
    block = doc["rank_noise"]["calibration"]
    assert block["sha256"] == maps.sha256
    assert "not a promoted model" in block["label"]
    assert "top25" in block["published"]
    row = doc["forecasts"]["baseline2"]["rows"][0]
    assert row["calibrated"]["p_top25"] == maps.value("sun0200", "top25", row["p_top25"])
    assert set(row["calibrated"]["p_rank_at_most"]) <= {"4", "12"}
    assert f"calibration:{maps.sha256}" in doc["inputs"]
    raw = issue(world(tmp_path / "d"), noise=noise, reveals=reveals).doc["forecasts"]["baseline2"]["rows"][0]
    assert {k: v for k, v in row.items() if k != "calibrated"} == raw  # the raw column is untouched
    other = fit_calibration(past(), 2027, taus=TAUS, paths=2000)
    write_calibration(tmp_path / "q", 2027, other)
    with pytest.raises(ValueError, match="2027, not 2026"):
        issue(world(tmp_path / "e"), noise=noise, calibration=load_calibration(tmp_path / "q", 2027))
