"""A small store with real conference names, for the sensitivity command's tests."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from cfp import cli
from cfp.open_ranking import RULE_VERSION_ID
from cfp.open_ranking.frozen import write_frozen
from cfp.open_ranking.strength import INDEPENDENT
from cfp.store.lake import Lake

from .store_helpers import Clock, frame, game
from .test_snapshot import ROOT, world

LEAGUES = ("acc", "big-ten", "big-12", "sec", "mountain-west", "sun-belt")
TEAMS = {
    f"S{i:02d}": (f"School {i:02d}", "fbs", INDEPENDENT if i >= 36 else LEAGUES[i % 6]) for i in range(40)
}
OCT3 = datetime(2026, 10, 3, 17, 0, tzinfo=UTC)
CUTOFF = datetime(2026, 11, 15, 7, 0, tzinfo=UTC)  # after six rounds
NOW = datetime(2026, 11, 17, 12, 0, tzinfo=UTC)
EDITION = "or-2026-20261115t0700z-replay-e1"


def row(lake: Lake, rnd: int, i: int) -> dict[str, Any]:
    home, away = f"S{i:02d}", f"S{20 + (i + 3 * rnd) % 20:02d}"
    start = OCT3 + timedelta(days=7 * (rnd - 1))
    public = start + timedelta(hours=4, minutes=30)
    base = {"home_id": home, "away_id": away, "start_utc": start, "week": 5 + rnd, "vintage": "reconstructed"}
    base |= {
        "home_pts": 2 * ((3 * i + 5 * rnd) % 17 + (20 - i) // 4) + 4,  # even, so never 21
        "away_pts": 21,
        "event_time": public,
        "first_public_time": public,
    }
    return game(lake, f"r{rnd}-{i:02d}", **base)


def setup(tmp_path: Path, rounds: int = 6) -> Lake:
    lake = world(tmp_path, [], TEAMS)
    lake.append("games", frame("games", [row(lake, r, i) for r in range(1, rounds + 1) for i in range(20)]))
    data = tmp_path / "data"
    data.mkdir()
    for name in ("title_games.csv", "forfeits.csv", "unplayed_games.csv"):
        (data / name).write_text((ROOT / "data" / name).read_text().splitlines()[0] + "\n")
    lines = [f"2026,{place},{team},{TEAMS[team][0]}\n" for place, team in enumerate(TEAMS, start=1)]
    (data / "preseason_draw_2026.csv").write_text("season,position,team_id,name\n" + "".join(lines))
    doc: dict[str, Any] = {"season": 2026, "lambda_c": 4.0, "lambda_u": 4.0, "t": 5.75, "cap": 24}
    doc |= {"independent_penalty": "combined", "status": "provisional", "rule_version_id": RULE_VERSION_ID}
    write_frozen(tmp_path / "params", 2026, doc)
    return lake


def _head(tmp_path: Path) -> list[str]:
    return ["--lake", str(tmp_path / "lake"), "--data", str(tmp_path / "data")]


def build(tmp_path: Path) -> int:
    argv = [*_head(tmp_path), "open-ranking", "build", "--season", "2026", "--mode", "replay"]
    argv += ["--frozen", str(tmp_path / "params"), "--cutoff", CUTOFF.isoformat()]
    return cli._open_ranking_build(cli.build_parser().parse_args(argv), Clock(NOW))


def sensitivity(tmp_path: Path, edition: str, *extra: str) -> int:
    argv = [*_head(tmp_path), "open-ranking", "sensitivity", "--edition", edition]
    argv += ["--frozen", str(tmp_path / "params"), "--workers", "1", *extra]
    return cli._open_ranking_sensitivity(cli.build_parser().parse_args(argv), Clock(NOW))


def run(tmp_path: Path, *argv: str) -> int:
    return cli.main([*_head(tmp_path), *argv, "--frozen", str(tmp_path / "params")])
