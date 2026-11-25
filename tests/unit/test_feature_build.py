"""Open points as a forecast feature (SC-04a): same formula as an edition, built at the issue cutoff."""

from __future__ import annotations

import shutil
from datetime import date, timedelta
from pathlib import Path
from typing import Any

import pytest

from cfp.forecast.observations import open_points_feature
from cfp.open_ranking import RULE_VERSION_ID
from cfp.open_ranking.feature import feature_build
from cfp.open_ranking.release import build_edition
from cfp.release.edition import canonical
from cfp.snapshot.build import Snapshot
from cfp.snapshot.data import TitleGame
from cfp.store.lake import Lake

from .store_helpers import Clock, frame, game
from .test_issue import CUTOFF, SAT, TEAMS, issue, world
from .test_ledger import frame as ledger_frame
from .test_ledger import league
from .test_open_release import DRAW as SYNTHETIC_DRAW
from .test_open_release import EMPTY, frozen, rows_with_extras, snapshot

LISTS: dict[str, Any] = {"title_games": [], "forfeits": [], "unplayed": []}


def add_games(lake: Lake, rounds: int = 5) -> None:
    """Earlier Saturdays: each round pairs team i with team i+15 (rotated), so all thirty teams play."""
    rows = []
    for rnd in range(1, rounds + 1):
        start = SAT - timedelta(days=7 * rnd)
        public = start + timedelta(hours=4, minutes=30)
        for i in range(15):
            home, away = TEAMS[i], TEAMS[15 + (i + rnd) % 15]
            over = {"home_id": home, "away_id": away, "start_utc": start, "week": 14 - rnd}
            over |= {"home_pts": 21 + (2 * i + 3 * rnd) % 19, "away_pts": 20, "event_time": public}
            rows.append(game(lake, f"r{rnd}-{i}", **over, first_public_time=public))
    lake.append("games", frame("games", rows))


def earlier_edition(params: Any) -> Any:
    early = Snapshot(
        2026, CUTOFF - timedelta(days=14), "replay", ledger_frame(league()[:80]), EMPTY, "e" * 64, "b" * 64
    )
    return build_edition(early, params, SYNTHETIC_DRAW, code_hash="abc")


def test_feature_build_matches_edition_on_same_snapshot(tmp_path: Path) -> None:
    params = frozen(tmp_path)
    snap = snapshot(rows_with_extras())
    feature = feature_build(snap, params)
    edition = build_edition(snap, params, SYNTHETIC_DRAW, code_hash="abc").doc
    assert feature.snapshot_hash == edition["manifest"]["snapshot_hash"]
    assert feature.params_sha256 == edition["manifest"]["params_sha256"]
    assert feature.formula_hash == edition["manifest"]["formula_hash"]
    assert feature.rule_version_id == RULE_VERSION_ID
    published = {team["team_id"]: team["rows"] for team in edition["teams"]}
    assert canonical(feature.rows) == canonical(published)  # byte-identical ledgers
    assert feature.points == {team["team_id"]: team["total_cp"] for team in edition["teams"]}
    assert feature.feature_build_id.startswith("orf:")
    # a later edition adds each row's change since its predecessor; the ledger itself is still identical
    later = build_edition(snap, params, SYNTHETIC_DRAW, code_hash="abc", previous=earlier_edition(params)).doc
    stripped = {t["team_id"]: [r | {"revision_cp": None} for r in t["rows"]] for t in later["teams"]}
    assert canonical(stripped) == canonical(feature.rows)
    assert (
        feature_build(snapshot(rows_with_extras(), tag="c"), params).feature_build_id
        != feature.feature_build_id
    )


def test_feature_build_without_forbidden_tables(tmp_path: Path) -> None:
    params = frozen(tmp_path)
    full = world(tmp_path / "full")
    add_games(full)
    shutil.copytree(tmp_path / "full" / "lake", tmp_path / "bare" / "lake")
    for table in ("committee_releases", "polls"):  # the only forbidden tables this world holds
        shutil.rmtree(tmp_path / "bare" / "lake" / "normalized" / table)
    bare = Lake(tmp_path / "bare" / "lake", clock=Clock(CUTOFF - timedelta(hours=1)))
    assert sorted(p.name for p in (tmp_path / "bare" / "lake" / "normalized").iterdir()) == [
        "games",
        "membership",
        "teams",
    ]
    a = open_points_feature(full.open_ranking_view(CUTOFF, "live"), 2026, params, LISTS)
    b = open_points_feature(bare.open_ranking_view(CUTOFF, "live"), 2026, params, LISTS)
    assert a.feature_build_id == b.feature_build_id
    assert a.points == b.points
    assert canonical(a.rows) == canonical(b.rows)
    assert len(a.points) == 30


def test_forecast_manifest_records_feature_build(tmp_path: Path) -> None:
    params = frozen(tmp_path)
    lake = world(tmp_path)
    add_games(lake)
    without = issue(lake).doc
    assert "open_points" in without["missing_inputs"]
    assert without["open_ranking_feature"] is None
    doc = issue(lake, frozen=params, lists=LISTS).doc
    assert "open_points" not in doc["missing_inputs"]
    feature = doc["open_ranking_feature"]
    expected = open_points_feature(lake.open_ranking_view(CUTOFF, "live"), 2026, params, LISTS)
    assert feature == {
        "feature_build_id": expected.feature_build_id,
        "snapshot_hash": expected.snapshot_hash,
        "lists_hash": expected.lists_hash,
        "params_sha256": params.sha256,
        "formula_hash": expected.formula_hash,
        "rule_version_id": RULE_VERSION_ID,
    }
    assert f"feature:{expected.feature_build_id}" in doc["inputs"]
    rows = {row["team_id"]: row for row in doc["forecasts"]["baseline2"]["rows"]}
    assert {team: row["open_points_cp"] for team, row in rows.items()} == expected.points
    # T28, T29 and T30 have no AP votes: open points order them, not the draw
    tail = sorted(("T28", "T29", "T30"), key=lambda team: -expected.points[team])
    assert [t for t in doc["forecasts"]["baseline2"]["top25"] + list(rows) if t in tail][-3:] == tail
    assert sorted(tail, key=lambda team: rows[team]["initial"]) == tail
    assert doc["open_points_error"] is None


def test_a_blocked_snapshot_is_disclosed_not_fatal(tmp_path: Path) -> None:
    params = frozen(tmp_path)
    lake = world(tmp_path)
    add_games(lake)
    title = TitleGame(2026, "SEC", date(2026, 12, 5), "Nowhere State", "School T01", "https://example.test/t")
    doc = issue(lake, frozen=params, lists=LISTS | {"title_games": [title]}).doc
    assert "open_points" in doc["missing_inputs"]
    assert doc["open_ranking_feature"] is None
    assert doc["open_points_error"]
    assert all(row["open_points_cp"] is None for row in doc["forecasts"]["baseline2"]["rows"])
    assert doc["open_points_error"].startswith("SnapshotBlocked")
    noted = issue(lake, open_points_note="FrozenError: 2026 is not frozen").doc
    assert noted["open_points_error"] == "FrozenError: 2026 is not frozen"


def test_an_unexpected_fault_is_disclosed_as_unexpected(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import cfp.release.issue as module

    def broken(*args: Any, **kwargs: Any) -> Any:
        raise KeyError("bug")

    monkeypatch.setattr(module, "open_points_feature", broken)
    lake = world(tmp_path)
    doc = issue(lake, frozen=frozen(tmp_path), lists=LISTS).doc
    assert doc["open_points_error"].startswith("unexpected KeyError")
    assert "open_points" in doc["missing_inputs"]


def test_manifest_inputs_pin_the_feature(tmp_path: Path) -> None:
    params = frozen(tmp_path)
    lake = world(tmp_path)
    add_games(lake)
    doc = issue(lake, frozen=params, lists=LISTS).doc
    feature = doc["open_ranking_feature"]
    assert doc["inputs"][-4:] == [
        f"feature:{feature['feature_build_id']}",
        f"feature-snapshot:{feature['snapshot_hash']}",
        f"feature-params:{params.sha256}",
        f"feature-rule:{RULE_VERSION_ID}",
    ]
    assert doc["product"] == "shadow_committee_weekly"  # a feature build is never labelled an edition
    assert not doc["edition_id"].startswith("or-")
