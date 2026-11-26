"""The field forecast inside a whole issue (FF-01 to FF-05): built from the store at the cutoff."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import numpy as np

from cfp.forecast.noise_params import fit_noise, load_noise, write_noise
from cfp.store.lake import Lake

from .store_helpers import frame, game
from .test_issue import AUG, CUTOFF, TEAMS, issue, prov, world
from .test_noise import examples

LEAGUES = {"T02": "big-ten", "T07": "big-ten", "T04": "big-12", "T08": "big-12", "T05": "acc", "T10": "acc"}
OUTSIDE = {"T26": "mountain-west", "T27": "sun-belt"}
TITLES = {"sec": ("T01", "T06"), "big-ten": ("T02", "T07"), "big-12": ("T04", "T08"), "acc": ("T05", "T10")}
KICK = datetime(2026, 11, 29, 21, 0, tzinfo=UTC)  # after the cutoff, before the final reveal
HEAD = "season,conference,game_date,team_a,team_b,site,site_type,basis,source_url,notes,first_public_utc\n"
LABEL = {"sec": "SEC", "big-ten": "Big Ten", "big-12": "Big 12", "acc": "ACC"}


def line(lake: Lake, gid: str, season: int, seen: datetime, public: datetime, **price: Any) -> dict[str, Any]:
    row = {"provider": "book", "game_id": gid, "as_of_utc": seen, "season": season}
    row |= {"ml_home": None, "ml_away": None, "spread": None, "total": None} | price
    return row | prov(lake, f"line-{gid}", public)


def field_world(root: Path) -> Lake:
    """The issue world plus four leagues, two finished seasons with lines, and four title games to play."""
    lake = world(root, leagues=LEAGUES | OUTSIDE)
    games, lines = [], []
    for season in (2024, 2025):
        rng = np.random.default_rng(season)
        for k in range(300):
            gid = f"p{season}-{k}"
            spread = float(np.round(rng.normal(0, 12) * 2) / 2)
            margin = int(np.round(rng.normal(-spread, 14))) or 1
            low = int(rng.integers(0, 30))
            start = datetime(season, 10, 1, tzinfo=UTC) + timedelta(hours=k)
            done = start + timedelta(hours=4, minutes=30)
            pts = (low + margin, low) if margin > 0 else (low, low - margin)
            games.append(
                game(
                    lake,
                    gid,
                    season=season,
                    start_utc=start,
                    home_id=f"P{k % 40}",
                    away_id=f"P{(k * 7 + k // 40) % 40 + 40}",
                    home_pts=pts[0],
                    away_pts=pts[1],
                    event_time=done,
                    first_public_time=done,
                )
            )
            lines.append(line(lake, gid, season, start, done, spread=spread))
    for conference, (home, away) in TITLES.items():
        gid = f"t-{conference}"
        games.append(
            game(
                lake,
                gid,
                week=15,
                start_utc=KICK,
                home_id=home,
                away_id=away,
                home_pts=None,
                away_pts=None,
                neutral=True,
                status="scheduled",
                title_game=True,
                event_time=AUG,
                first_public_time=AUG,
            )
        )
        seen = CUTOFF - timedelta(hours=3)
        lines.append(line(lake, gid, 2026, seen, seen, ml_home=-150.0, ml_away=130.0))
    lake.append("games", frame("games", games))
    lake.append("lines", frame("lines", lines))
    return lake


def title_files(root: Path, known: tuple[str, ...] = tuple(TITLES)) -> tuple[Path, Path]:
    rows = [
        f"2026,{LABEL[c]},2026-11-29,School {TITLES[c][0]},School {TITLES[c][1]},,neutral,conference_release,"
        f"https://example.test/{c},,2026-11-28T12:00:00+00:00\n"
        for c in known
    ]
    titles = root / "title_games.csv"
    titles.write_text(HEAD + "".join(rows))
    return titles, root / "title_scenarios.csv"


def noise(root: Path) -> Any:
    write_noise(root / "p", 2026, fit_noise(examples(), 2026))
    return load_noise(root / "p", 2026)


def test_issue_carries_the_field_forecast_and_records_its_inputs(tmp_path: Path) -> None:
    built = issue(field_world(tmp_path), noise=noise(tmp_path), pairing_files=title_files(tmp_path))
    doc = built.doc
    assert doc["final_field_error"] is None
    section = doc["final_field"]
    assert section["kind"] == "final"
    assert [p["basis"] for p in section["pairings"]] == ["official"] * 4
    run = section["forecast"]
    assert sorted(g["title_for"] for g in run["games"]) == ["acc", "big-12", "big-ten", "sec"]
    assert {g["source"] for g in run["games"]} == {"moneyline"}
    paths = section["paths"]
    assert sum(t["field_paths"] for t in run["teams"]) == 12 * paths
    assert sum(t["bye_paths"] for t in run["teams"]) == 4 * paths
    group = [t for t in run["teams"] if t["team_id"] in OUTSIDE]
    assert sum(t["field_paths"] for t in group) == paths  # the six-conference place, on every path
    assert all(0 < t["p_field"] < 1 for t in run["teams"])
    names = [i.split(":")[0] for i in doc["inputs"]]
    assert "pairings" in names
    assert any(i.startswith("all-seasons-") for i in doc["inputs"])
    assert (
        built.sha256
        == issue(
            field_world(tmp_path / "again"),
            noise=noise(tmp_path / "again"),
            pairing_files=title_files(tmp_path),
        ).sha256
    )  # the same store and files give the same bytes


def test_a_refused_field_records_no_field_inputs(tmp_path: Path) -> None:
    files = title_files(tmp_path, known=("sec", "acc"))
    doc = issue(field_world(tmp_path), noise=noise(tmp_path), pairing_files=files).doc
    assert doc["final_field"] is None
    assert "big-" in doc["final_field_error"]
    assert not [i for i in doc["inputs"] if i.startswith(("pairings:", "all-seasons-"))]
    assert doc["forecasts"]["baseline2"]["rows"][0]["p_top25"] > 0.9  # the weekly forecast is whole


def test_pairwise_bubble_probabilities_are_in_the_issue(tmp_path: Path) -> None:
    doc = issue(field_world(tmp_path), noise=noise(tmp_path)).doc
    pairs = doc["rank_noise"]["pairwise"]
    assert doc["rank_noise"]["pairwise_error"] is None
    order = [row["team_id"] for row in doc["forecasts"]["baseline2"]["rows"]]
    last = order.index(pairs["last_at_large"])
    assert pairs["teams"] == order[max(0, last - 5) : last + 6]
    size = len(pairs["teams"])
    for i in range(size):
        assert pairs["p_ahead"][i][i] is None
        for j in range(i + 1, size):
            assert pairs["ahead_paths"][i][j] + pairs["ahead_paths"][j][i] == doc["rank_noise"]["paths"]
            assert pairs["ahead_paths"][i][j] > pairs["ahead_paths"][j][i]  # the better-placed team leads
    plain = issue(world(tmp_path / "one-league"), noise=noise(tmp_path / "one-league")).doc["rank_noise"]
    assert (plain["pairwise"] is None) != (plain["pairwise_error"] is None)  # the pairs, or the reason
    assert TEAMS[0] in order


def test_a_bracket_that_fails_the_per_path_check_refuses_the_field(tmp_path: Path, monkeypatch: Any) -> None:
    from cfp.release import field as field_module
    from cfp.scoring.integrity import IntegrityError

    calls: list[int] = []
    real = field_module.check_path

    def counting(entries: Any, **sizes: int) -> None:
        calls.append(1)
        real(entries, **sizes)

    monkeypatch.setattr(field_module, "check_path", counting)
    doc = issue(field_world(tmp_path), noise=noise(tmp_path), pairing_files=title_files(tmp_path)).doc
    assert doc["final_field_error"] is None
    assert len(calls) == doc["final_field"]["paths"]  # every published path went through the check
    assert "bracket checked on every path" in " ".join(doc["final_field"]["notes"])

    def broken(entries: Any, **sizes: int) -> None:
        raise IntegrityError("two teams hold seed 5")

    monkeypatch.setattr(field_module, "check_path", broken)
    world2 = field_world(tmp_path / "b")
    doc = issue(world2, noise=noise(tmp_path / "b"), pairing_files=title_files(tmp_path)).doc
    assert doc["final_field"] is None
    assert "two teams hold seed 5" in doc["final_field_error"]
