"""What the Committee Gap reads from the store (CG-01): only editions frozen before the reveal."""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest

from cfp.common.hashing import sha256_hex
from cfp.gap.report import GapRefused, load_inputs
from cfp.store.lake import Lake

from .store_helpers import Clock, frame
from .test_issue import CUTOFF, REVEAL, TEAMS, prov, release_rows, run_live, world

AFTER = REVEAL + timedelta(hours=1)
ACTUAL = [*TEAMS[:2], *TEAMS[3:24], "T03", "T26"]
LATER = "2026,2026-12-06,2026-12-06,12:00,primary,https://example.test/s,,\n"


def plant(
    root: Path,
    edition_id: str,
    *,
    recorded: datetime,
    cutoff: datetime = CUTOFF,
    data_as_of: datetime | None = None,
    vintage: str = "live",
) -> Path:
    """An Open Ranking edition folder and its store row, recorded at `recorded`."""
    lake = Lake(root / "lake", clock=Clock(recorded))
    doc = {
        "edition_id": edition_id,
        "product": "open_ranking",
        "season": 2026,
        "cutoff_utc": cutoff.isoformat(),
        "data_as_of_utc": (data_as_of or cutoff).isoformat(),
        "teams": [
            {"team_id": t, "order": k, "open_rank": k, "total_cp": -k, "rows": [], "head_to_head": None}
            for k, t in enumerate(TEAMS, start=1)
        ],
    }
    body = json.dumps(doc, sort_keys=True).encode()
    folder = root / "lake" / "editions" / edition_id
    folder.mkdir(parents=True)
    (folder / "edition.json").write_bytes(body)
    row: dict[str, Any] = {
        "edition_id": edition_id,
        "season": 2026,
        "product": "open_ranking",
        "issue_utc": cutoff,
        "input_ids": [],
        "seed": None,
        "code_hash": "abc1234",
        "rule_version_id": "or-test",
        "sha256": sha256_hex(body),
    }
    lake.append(
        "editions", frame("editions", [row | prov(lake, edition_id, recorded) | {"vintage": vintage}])
    )
    return folder / "edition.json"


def revealed(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, *, last: bool = False) -> Lake:
    """The issue test's world, one live forecast for release 2, and the release itself."""
    world(tmp_path)
    assert run_live(tmp_path, CUTOFF + timedelta(minutes=5), monkeypatch) == 0
    if not last:  # a later reveal on the calendar, so release 2 is not Selection Day
        with (tmp_path / "data" / "cfp_reveals.csv").open("a") as out:
            out.write(LATER)
    lake = Lake(tmp_path / "lake", clock=Clock(REVEAL + timedelta(minutes=10)))
    lake.append("committee_releases", frame("committee_releases", release_rows(lake, 2, REVEAL, ACTUAL)))
    return lake


def load(tmp_path: Path, mode: str = "live", now: datetime = AFTER) -> Any:
    lake = Lake(tmp_path / "lake", clock=Clock(now))
    return load_inputs(lake, tmp_path / "data", "cfp-2026-02", now=now, mode=mode)  # type: ignore[arg-type]


def test_live_report_reads_only_editions_frozen_before_the_reveal(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    revealed(tmp_path, monkeypatch)
    with pytest.raises(GapRefused, match="no Open Ranking edition"):
        load(tmp_path)
    early = datetime(2026, 11, 22, 7, 0, tzinfo=UTC)
    plant(tmp_path, "or-2026-20261122t0700z-e1", recorded=early + timedelta(minutes=9), cutoff=early)
    plant(tmp_path, "or-2026-20261129t0700z-e1", recorded=CUTOFF + timedelta(minutes=9))
    # none of these may be chosen: a rebuilt edition, one recorded after the reveal, a post-reveal correction
    plant(
        tmp_path,
        "or-2026-20261130t0700z-replay-e1",
        recorded=CUTOFF,
        cutoff=CUTOFF + timedelta(days=1),
        vintage="reconstructed",
    )
    plant(tmp_path, "or-2026-20261201t0700z-e1", recorded=AFTER, cutoff=CUTOFF + timedelta(days=2))
    plant(tmp_path, "or-2026-20261129t0700z-e2", recorded=AFTER, data_as_of=AFTER)
    with pytest.raises(GapRefused, match="not in the store"):  # live mode cannot see the release yet
        load(tmp_path, now=REVEAL - timedelta(minutes=1))
    got = load(tmp_path, now=AFTER + timedelta(hours=1))
    assert got.open_edition[0]["edition_id"] == "or-2026-20261129t0700z-e1"
    assert got.forecast_edition[0]["edition_id"] == "scw-2026-r02-sun0200-e1"
    assert (got.release_no, got.releases, list(got.actual)) == (2, 3, ACTUAL)
    assert got.champions == {}
    assert got.eligible == {team: True for team in TEAMS}  # the store's table: eligible unless sourced
    assert got.members["T01"] == "sec"
    assert got.names["T01"] == "School T01"


def test_replay_never_takes_an_edition_whose_data_was_read_after_the_reveal(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    revealed(tmp_path, monkeypatch)
    plant(tmp_path, "or-2026-20261129t0700z-e1", recorded=CUTOFF + timedelta(minutes=9))
    plant(
        tmp_path,
        "or-2026-20261129t0700z-e2",
        recorded=CUTOFF + timedelta(hours=2),
        data_as_of=CUTOFF + timedelta(hours=1),
    )
    plant(
        tmp_path,
        "or-2026-20261129t0700z-e10",
        recorded=CUTOFF + timedelta(hours=4),
        data_as_of=CUTOFF + timedelta(hours=3),
    )
    plant(tmp_path, "or-2026-20261129t0700z-e11", recorded=AFTER, data_as_of=AFTER)
    got = load(tmp_path, "replay", AFTER + timedelta(hours=1))
    assert got.open_edition[0]["edition_id"] == "or-2026-20261129t0700z-e10"  # by number: e10 is after e2
    assert any("e11" in line and "after the reveal" in line for line in got.passed_over)
    assert got.mode == "replay"


def test_a_changed_file_or_a_missing_champion_refuses(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    revealed(tmp_path, monkeypatch, last=True)  # release 2 is the last on the calendar: Selection Day
    path = plant(tmp_path, "or-2026-20261129t0700z-e1", recorded=CUTOFF + timedelta(minutes=9))
    with pytest.raises(GapRefused, match="champion"):
        load(tmp_path)
    with (tmp_path / "data" / "cfp_reveals.csv").open("a") as out:
        out.write(LATER)
    assert load(tmp_path).open_edition[1] == sha256_hex(path.read_bytes())
    path.write_bytes(path.read_bytes() + b" ")
    with pytest.raises(GapRefused, match="hash"):
        load(tmp_path)
