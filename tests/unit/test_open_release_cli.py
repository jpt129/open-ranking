"""`cfp open-ranking build` (OR-08, RL-02): write-once folder, table row, previous edition, corrections."""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest

from cfp import cli
from cfp.common.hashing import sha256_hex
from cfp.open_ranking import RULE_VERSION_ID
from cfp.open_ranking.frozen import write_frozen
from cfp.store.lake import Lake

from .store_helpers import Clock, frame, game
from .test_snapshot import ROOT, world

TEAMS = {f"T{i:02d}": (f"Team {i:02d}", "fbs", f"c{i % 2}") for i in range(20)}
OCT3 = datetime(2026, 10, 3, 17, 0, tzinfo=UTC)
C0 = datetime(2026, 10, 25, 7, 0, tzinfo=UTC)  # after four rounds
C1 = datetime(2026, 11, 1, 7, 0, tzinfo=UTC)  # after five
NOW = datetime(2026, 11, 3, 12, 0, tzinfo=UTC)
E0 = "or-2026-20261025t0700z-replay-e1"
E1 = "or-2026-20261101t0700z-replay-e1"


def row(lake: Lake, rnd: int, i: int, **over: Any) -> dict[str, Any]:
    home, away = f"T{i:02d}", f"T{10 + (i + rnd) % 10:02d}"
    start = OCT3 + timedelta(days=7 * (rnd - 1))
    public = start + timedelta(hours=4, minutes=30)
    base = {"home_id": home, "away_id": away, "start_utc": start, "week": 5 + rnd, "vintage": "reconstructed"}
    base |= {
        "home_pts": 20 + (3 * i + rnd) % 17,
        "away_pts": 19,
        "event_time": public,
        "first_public_time": public,
    }
    return game(lake, f"r{rnd}-{i}", **(base | over))


def setup(tmp_path: Path, rounds: int = 5) -> Lake:
    lake = world(tmp_path, [], TEAMS)
    lake.append("games", frame("games", [row(lake, r, i) for r in range(1, rounds + 1) for i in range(10)]))
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


def build(tmp_path: Path, cutoff: datetime | str, *extra: str, now: datetime = NOW) -> int:
    when = cutoff if isinstance(cutoff, str) else cutoff.isoformat()
    argv = ["--lake", str(tmp_path / "lake"), "--data", str(tmp_path / "data"), "open-ranking", "build"]
    argv += ["--season", "2026", "--mode", "replay", "--frozen", str(tmp_path / "params"), "--cutoff", when]
    return cli._open_ranking_build(cli.build_parser().parse_args([*argv, *extra]), Clock(now))


def edition(tmp_path: Path, edition_id: str) -> dict[str, Any]:
    return json.loads((tmp_path / "lake" / "editions" / edition_id / "edition.json").read_text())  # type: ignore[no-any-return]


@pytest.fixture(autouse=True)
def pinned_code(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(cli, "_code_hash", lambda: "abc1234")


def test_build_writes_once_and_records(tmp_path: Path) -> None:
    lake = setup(tmp_path)
    assert build(tmp_path, C0) == 0
    folder = tmp_path / "lake" / "editions" / E0
    assert sorted(p.name for p in folder.iterdir()) == ["edition.json", "games.jsonl", "receipt.json"]
    doc = edition(tmp_path, E0)
    assert doc["manifest"]["games"] == 40
    assert doc["manifest"]["games_sha256"] == sha256_hex((folder / "games.jsonl").read_bytes())
    assert len((folder / "games.jsonl").read_text().splitlines()) == 40
    assert doc["data_as_of_utc"] == doc["cutoff_utc"] == C0.isoformat()
    held = lake.scan("editions").collect()
    assert held.height == 1
    stored = held.row(0, named=True)
    assert (stored["edition_id"], stored["product"], stored["vintage"]) == (
        E0,
        "open_ranking",
        "reconstructed",
    )
    assert stored["sha256"] == sha256_hex((folder / "edition.json").read_bytes())
    assert stored["input_ids"] == doc["inputs"]
    assert build(tmp_path, C0) == cli.EXIT_EXISTS
    assert lake.scan("editions").collect().height == 1


def test_previous_edition_is_the_latest_earlier_one_and_is_an_input(tmp_path: Path) -> None:
    setup(tmp_path)
    assert build(tmp_path, C0) == 0
    assert build(tmp_path, C1) == 0
    first, second = edition(tmp_path, E0), edition(tmp_path, E1)
    assert first["previous_edition"] is None
    body = (tmp_path / "lake" / "editions" / E0 / "edition.json").read_bytes()
    assert second["previous_edition"] == {"edition_id": E0, "sha256": sha256_hex(body)}
    assert f"previous:{E0}:{sha256_hex(body)}" in second["inputs"]
    assert any(r["revision_cp"] is not None for t in second["teams"] for r in t["rows"])


def test_a_run_that_died_before_recording_is_repaired(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    lake = setup(tmp_path)
    import cfp.ingest.upsert as module

    real = module.upsert

    def broken(*args: Any, **kwargs: Any) -> Any:
        raise OSError("disk full")

    monkeypatch.setattr(module, "upsert", broken)
    with pytest.raises(OSError, match="disk full"):
        build(tmp_path, C0)
    assert lake.scan("editions").collect().height == 0
    monkeypatch.setattr(module, "upsert", real)
    assert build(tmp_path, C0) == cli.EXIT_EXISTS
    held = lake.scan("editions").collect()
    assert held["edition_id"].to_list() == [E0]
    assert held["sha256"][0] == sha256_hex(
        (tmp_path / "lake" / "editions" / E0 / "edition.json").read_bytes()
    )


def test_correction_creates_new_edition(tmp_path: Path) -> None:
    lake = setup(tmp_path)
    assert build(tmp_path, C1) == 0
    later = C1 + timedelta(days=1)
    fixed = row(
        lake, 2, 3, home_pts=10, away_pts=19, correction_version=1, first_public_time=later, event_time=later
    )
    extra = row(lake, 6, 0, start_utc=C1 + timedelta(hours=6), first_public_time=C1 + timedelta(hours=11))
    lake.append("games", frame("games", [fixed, extra]))
    asof = (C1 + timedelta(days=2)).isoformat()
    assert build(tmp_path, C1, "--corrected-as-of", asof) == 1  # a correction is a new revision
    assert build(tmp_path, C1, "--revision", "2", "--corrected-as-of", asof) == 0
    old, new = edition(tmp_path, E1), edition(tmp_path, E1[:-1] + "2")
    assert new["supersedes"] == E1
    assert (new["cutoff_utc"], new["data_as_of_utc"]) == (C1.isoformat(), asof)
    assert new["manifest"]["games"] == 50  # the game played after the cutoff stays out

    def total(doc: dict[str, Any], team: str) -> int:
        return next(t["total_cp"] for t in doc["teams"] if t["team_id"] == team)

    home, away = fixed["home_id"], fixed["away_id"]
    assert total(new, home) - total(old, home) == -10000
    assert total(new, away) - total(old, away) == 10000
    assert json.loads((tmp_path / "lake" / "editions" / E1 / "edition.json").read_text()) == old  # untouched
    assert build(tmp_path, C1, "--revision", "4") == 1  # e3 does not exist


def test_refusals(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    setup(tmp_path)
    assert build(tmp_path, NOW + timedelta(hours=1)) == 1
    assert build(tmp_path, "garbage") == 2
    assert build(tmp_path, C0 + timedelta(seconds=30)) == 1
    assert "whole minute" in capsys.readouterr().err
    assert not (tmp_path / "lake" / "editions").exists()
