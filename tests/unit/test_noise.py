"""Fitted rank noise in the weekly issue (SC-03, SC-05): saved parameters and published probabilities."""

from __future__ import annotations

import json
from datetime import timedelta
from pathlib import Path

import pytest

from cfp.forecast.noise_params import Example, NoiseError, fit_noise, load_noise, release_kind, write_noise
from cfp.forecast.rank_noise import sample_orders

from .test_issue import CUTOFF, PRIOR, REVEAL, issue, world

TEAMS = [f"T{k:03d}" for k in range(60)]
PATHS = 10_000


def examples(tau: float = 2.0, seasons: tuple[int, ...] = (2023, 2024, 2025)) -> list[Example]:
    out = []
    for season in seasons:
        for number in range(1, 7):
            for which in ("sun0200", "tminus60"):
                drawn = sample_orders(60, tau, 1, seed=season * 100 + number)[0]
                actual = [TEAMS[i] for i in drawn[:25]]
                kind = release_kind(number, 6)
                out.append(Example(season, number, which, kind, TEAMS, TEAMS, actual))
    return out


def test_release_kind() -> None:
    assert [release_kind(n, 6) for n in (1, 2, 5, 6)] == ["opening", "weekly", "weekly", "final"]
    with pytest.raises(ValueError, match="release 7 of 6"):
        release_kind(7, 6)


def test_fit_uses_only_earlier_seasons_and_reports_each_kind() -> None:
    doc = fit_noise(examples(), 2026)
    assert doc["season"] == 2026
    assert doc["trained_on"] == [2023, 2024, 2025]
    weekly = doc["temperatures"]["baseline2"]["sun0200"]["weekly"]
    assert weekly["releases"] == 12  # four weekly releases a season
    assert doc["temperatures"]["baseline2"]["sun0200"]["final"]["releases"] == 3
    assert 0.8 < weekly["tau"] < 4.0
    assert set(doc["temperatures"]) == {"baseline1", "baseline2"}
    with pytest.raises(NoiseError, match="2026 is not an earlier season"):
        fit_noise(examples(seasons=(2025, 2026)), 2026)
    with pytest.raises(NoiseError, match="no earlier releases"):
        fit_noise([], 2026)


def test_noise_file_is_written_once_and_checked(tmp_path: Path) -> None:
    doc = fit_noise(examples(), 2026)
    path, digest = write_noise(tmp_path, 2026, doc)
    noise = load_noise(tmp_path, 2026)
    assert noise.sha256 == digest
    assert (
        noise.tau("baseline2", "sun0200", "weekly")
        == doc["temperatures"]["baseline2"]["sun0200"]["weekly"]["tau"]
    )
    with pytest.raises(NoiseError, match="never rewritten"):
        write_noise(tmp_path, 2026, doc)
    with pytest.raises(NoiseError, match="no temperature"):
        noise.tau("baseline2", "sun0200", "nightly")
    path.chmod(0o644)
    path.write_text(path.read_text().replace('"season": 2026', '"season": 2026 '))
    with pytest.raises(NoiseError, match="hash"):
        load_noise(tmp_path, 2026)
    with pytest.raises(NoiseError, match="no rank-noise parameters"):
        load_noise(tmp_path, 2027)


def test_issue_publishes_sampled_probabilities(tmp_path: Path) -> None:
    write_noise(tmp_path / "p", 2026, fit_noise(examples(), 2026))
    noise = load_noise(tmp_path / "p", 2026)
    lake = world(tmp_path)
    built = issue(lake, noise=noise)
    doc = built.doc
    assert doc["schema"] == 3
    assert "rank_noise_temperature" not in doc["missing_inputs"]
    info = doc["rank_noise"]
    assert info["paths"] == PATHS
    assert info["kind"] == "final"  # the forecast release is the last on the schedule
    assert info["params_sha256"] == noise.sha256
    assert info["tau"]["baseline2"] == noise.tau("baseline2", "sun0200", "final")
    assert isinstance(info["seed"], int)
    rows = doc["forecasts"]["baseline2"]["rows"]
    assert all(sum(row["rank_counts"]) == PATHS for row in rows)
    assert sum(row["top25_paths"] for row in rows) == 25 * PATHS  # each path fills 25 places
    assert all(row["top25_paths"] == PATHS - row["rank_counts"][25] for row in rows)
    assert all(0.0 < row["p_top25"] < 1.0 for row in rows)  # never printed as 0 or 1
    assert rows[0]["p_top25"] > rows[24]["p_top25"] > rows[29]["p_top25"]
    assert rows[0]["median_rank"] in (1, 2)
    assert rows[-1]["median_rank"] == "outside 25"
    assert set(rows[0]["p_rank_at_most"]) == {"4", "8", "12", "25"}
    first = doc["forecasts"]["baseline1"]
    assert sum(sum(counts[:25]) for counts in first["rank_counts"].values()) == 25 * PATHS
    assert issue(lake, noise=noise).body == built.body  # the same seed, the same bytes
    # a week that is not the last uses the weekly temperature
    later = REVEAL + timedelta(days=5)
    mid = issue(lake, noise=noise, reveals=[PRIOR, REVEAL, later])
    assert mid.doc["rank_noise"]["kind"] == "weekly"
    # without parameters the issue still goes out and says what is missing
    bare = issue(lake)
    assert "rank_noise_temperature" in bare.doc["missing_inputs"]
    assert bare.doc["rank_noise"] is None
    assert "p_top25" not in bare.doc["forecasts"]["baseline2"]["rows"][0]
    assert CUTOFF < REVEAL
    assert json.loads(built.body)["rank_noise"]["seed"] == info["seed"]


def test_final_seen_from_two_releases_back() -> None:
    """A field forecast issued before the last weekly release needs the noise over both remaining steps."""
    made = []
    for season in (2023, 2024, 2025):
        start = list(TEAMS)
        losses_week = {"T004": 1}
        losses_title = {"T002": 1}
        drawn = sample_orders(60, 3.0, 1, seed=season)[0]
        base = [
            t
            for _, _, t in sorted(
                (k + 1 + 5 * ((t == "T004") + (t == "T002")), k, t) for k, t in enumerate(start)
            )
        ]
        final = [base[i] for i in drawn[:25]]
        for which in ("sun0200", "tminus60"):
            made.append(Example(season, 5, which, "weekly", TEAMS, TEAMS, TEAMS[:25], start, losses_week, 6))
            made.append(Example(season, 6, which, "final", TEAMS, TEAMS, final, start, losses_title, 6))
    doc = fit_noise(made, 2026)
    two = doc["temperatures"]["baseline2"]["sun0200"]["final_two_back"]
    assert two["releases"] == 3
    assert 1.0 < two["tau"] < 9.0
    assert "final_two_back" in doc["temperatures"]["baseline2"]["tminus60"]
