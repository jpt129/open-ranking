"""Open Ranking edition document (OR-08, RL-01a, RL-02): manifest hashes, integer content, revisions."""

from __future__ import annotations

import json
import random
import re
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import polars as pl
import pytest

from cfp.common.hashing import sha256_hex
from cfp.open_ranking import RULE_VERSION_ID
from cfp.open_ranking.frozen import Frozen, load_frozen, write_frozen
from cfp.open_ranking.release import PRODUCT, ReleaseError, build_edition, formula_hash
from cfp.snapshot.build import Snapshot
from tests.unit.test_ledger import TEAMS, fcs, frame, game, league

CUTOFF = datetime(2026, 11, 22, 7, 0, tzinfo=UTC)
DRAW = {team: place for place, team in enumerate(reversed(TEAMS), start=1)}
HEX = re.compile(r"^[0-9a-f]{64}$")


def frozen(tmp_path: Path, t: float = 5.75, rule: str = RULE_VERSION_ID) -> Frozen:
    doc: dict[str, Any] = {"season": 2026, "lambda_c": 4.0, "lambda_u": 4.0, "t": t, "cap": 24}
    doc |= {"independent_penalty": "combined", "status": "provisional", "rule_version_id": rule}
    root = tmp_path / f"params-{t}-{rule}"
    write_frozen(root, 2026, doc)
    return load_frozen(root, 2026)


def snapshot(rows: list[dict[str, Any]], mode: str = "replay", tag: str = "a") -> Snapshot:
    omissions = pl.DataFrame({"game_id": ["x1", "x2"], "reason": ["unplayed", "unplayed"]})
    return Snapshot(2026, CUTOFF, mode, frame(rows), omissions, tag * 64, "b" * 64)


def rows_with_extras() -> list[dict[str, Any]]:
    rows = league()
    rows.append(fcs("f1", "T00", won=True))
    rows.append(game("title", "T02", "T03", 27, 24, week=7, title_game=True, neutral=True))
    return rows


def floats_in(value: Any, path: str = "") -> list[str]:
    if isinstance(value, float):
        return [path]
    if isinstance(value, dict):
        return [hit for k, v in value.items() for hit in floats_in(v, f"{path}/{k}")]
    if isinstance(value, list):
        return [hit for i, v in enumerate(value) for hit in floats_in(v, f"{path}/{i}")]
    return []


def test_edition_manifest_hashes(tmp_path: Path) -> None:
    params = frozen(tmp_path)
    built = build_edition(snapshot(rows_with_extras()), params, DRAW, code_hash="abc123")
    doc = built.doc
    assert built.edition_id == doc["edition_id"] == "or-2026-20261122t0700z-replay-e1"
    assert (doc["product"], doc["season"], doc["mode"]) == (PRODUCT, 2026, "replay")
    assert doc["cutoff_utc"] == "2026-11-22T07:00:00+00:00"
    manifest = doc["manifest"]
    assert manifest["snapshot_hash"] == "a" * 64
    assert manifest["lists_hash"] == "b" * 64
    assert manifest["params_sha256"] == params.sha256
    assert manifest["params"] == {"lambda_c": 4.0, "lambda_u": 4.0, "t": 5.75, "cap": 24} | {
        "independent_penalty": "combined",
        "status": "provisional",
    }
    assert manifest["formula_hash"] == formula_hash(params, 2026)
    assert HEX.match(manifest["formula_hash"])
    assert HEX.match(manifest["draw_hash"])
    assert manifest["code_hash"] == "abc123"
    assert manifest["rule_version_id"] == RULE_VERSION_ID
    assert manifest["second_implementation"] == "not run"  # RL-01a
    assert manifest["band_ranks"] == [9, 16]
    assert manifest["omissions"] == {"unplayed": 2}
    assert manifest["games"] == len(rows_with_extras())
    assert built.inputs == [
        f"snapshot:{'a' * 64}",
        f"lists:{'b' * 64}",
        f"params:{params.sha256}",
        f"draw:{manifest['draw_hash']}",
    ]
    # the only floats are the frozen parameter values, which are read from the file, not computed
    assert sorted(floats_in(doc)) == [
        "/manifest/params/lambda_c",
        "/manifest/params/lambda_u",
        "/manifest/params/t",
    ]
    assert json.loads(built.body) == doc
    assert built.sha256 == sha256_hex(built.body)
    # same inputs in another row order give the same bytes
    shuffled = rows_with_extras()
    random.Random(3).shuffle(shuffled)
    again = build_edition(snapshot(shuffled), params, DRAW, code_hash="abc123")
    assert again.body == built.body
    # the formula hash moves with the parameters and the season's band, the snapshot hash with the inputs
    assert formula_hash(frozen(tmp_path, t=6.0), 2026) != manifest["formula_hash"]
    assert formula_hash(params, 2027) != manifest["formula_hash"]
    other = build_edition(snapshot(rows_with_extras(), tag="c"), params, DRAW, code_hash="abc123")
    assert other.sha256 != built.sha256


def test_edition_teams_and_rows(tmp_path: Path) -> None:
    doc = build_edition(snapshot(rows_with_extras()), frozen(tmp_path), DRAW, code_hash="abc").doc
    teams = doc["teams"]
    assert len(teams) == 32
    assert [t["order"] for t in teams] == list(range(1, 33))
    assert teams == sorted(teams, key=lambda t: t["order"])
    for team in teams:
        assert team["total_cp"] == sum(row["points_cp"] for row in team["rows"])
        assert team["rule_version_id"] == RULE_VERSION_ID
        assert set(team) == {
            "team_id",
            "total_cp",
            "raw_rank",
            "group",
            "head_to_head",
            "open_rank",
            "order",
        } | {
            "wins",
            "losses",
            "band",
            "rows",
            "rule_version_id",
        }
        assert team["wins"] + team["losses"] == len(team["rows"])
        assert len(team["band"]) == 8
    row = next(r for r in next(t for t in teams if t["team_id"] == "T02")["rows"] if r["game_id"] == "title")
    assert row == {
        "game_id": "title",
        "week": 7,
        "opponent_id": "T03",
        "site": "neutral",
        "result": "W",
        "title_game": True,
        "q": row["q"],
        "boundary": False,
        "points_cp": 10000 - row["q"],
        "policy_exception": None,
        "revision_cp": None,
    }
    won = next(r for r in next(t for t in teams if t["team_id"] == "T00")["rows"] if r["game_id"] == "f1")
    assert (won["q"], won["points_cp"], won["policy_exception"]) == (None, 0, "fcs_win")
    assert doc["manifest"]["boundary_rows"] == 0


def test_revisions_since_the_previous_edition(tmp_path: Path) -> None:
    params = frozen(tmp_path)
    rows = league()
    first = build_edition(
        Snapshot(
            2026,
            datetime(2026, 11, 15, 7, 0, tzinfo=UTC),
            "replay",
            frame(rows[:80]),
            EMPTY,
            "d" * 64,
            "b" * 64,
        ),
        params,
        DRAW,
        code_hash="abc",
    )
    assert first.doc["previous_edition"] is None
    second = build_edition(snapshot(rows), params, DRAW, code_hash="abc", previous=first)
    assert second.doc["previous_edition"] == {"edition_id": first.edition_id, "sha256": first.sha256}
    old = {(t["team_id"], r["game_id"]): r["points_cp"] for t in first.doc["teams"] for r in t["rows"]}
    seen = 0
    for team in second.doc["teams"]:
        for row in team["rows"]:
            key = (team["team_id"], row["game_id"])
            assert row["revision_cp"] == (row["points_cp"] - old[key] if key in old else None)
            seen += key in old and row["revision_cp"] != 0
    assert seen > 0
    with pytest.raises(ReleaseError, match="not earlier"):
        build_edition(snapshot(rows), params, DRAW, code_hash="abc", previous=second)


def test_corrections_and_refusals(tmp_path: Path) -> None:
    params = frozen(tmp_path)
    rows = league()
    live = build_edition(snapshot(rows, mode="live"), params, DRAW, code_hash="abc", revision=2)
    assert live.edition_id == "or-2026-20261122t0700z-e2"
    assert live.doc["supersedes"] == "or-2026-20261122t0700z-e1"
    assert build_edition(snapshot(rows), params, DRAW, code_hash="abc").doc["supersedes"] is None
    for bad in ("abc-dirty", "unknown"):
        with pytest.raises(ReleaseError, match="committed code"):
            build_edition(snapshot(rows, mode="live"), params, DRAW, code_hash=bad)
        assert build_edition(snapshot(rows), params, DRAW, code_hash=bad).doc["manifest"]["code_hash"] == bad
    with pytest.raises(ReleaseError, match="rule version"):
        build_edition(snapshot(rows), frozen(tmp_path, rule="or-0.9"), DRAW, code_hash="abc")
    with pytest.raises(ReleaseError, match="season"):
        build_edition(
            Snapshot(2025, CUTOFF, "replay", frame(rows), EMPTY, "a" * 64, "b" * 64),
            params,
            DRAW,
            code_hash="abc",
        )
    with pytest.raises(ReleaseError, match="revision"):
        build_edition(snapshot(rows), params, DRAW, code_hash="abc", revision=0)


EMPTY = pl.DataFrame({"game_id": [], "reason": []}, schema={"game_id": pl.String, "reason": pl.String})
