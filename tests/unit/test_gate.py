"""The release gate and the public page (RL-01, RL-01a, OR-08, OR-09): check an edition, then publish."""

from __future__ import annotations

import json
from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest

from cfp import cli
from cfp.common.draw import load_draw
from cfp.common.hashing import sha256_hex
from cfp.release.edition import canonical
from cfp.release.gate import CHECKS, run_gate

from .test_open_release_cli import C0, C1, E0, E1, build, setup


@pytest.fixture(autouse=True)
def pinned_code(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(cli, "_code_hash", lambda: "abc1234")


def folder(tmp_path: Path, edition_id: str = E0) -> Path:
    return tmp_path / "lake" / "editions" / edition_id


def rewrite(path: Path, body: bytes) -> None:
    path.parent.chmod(0o755)
    path.chmod(0o644)
    path.write_bytes(body)


def store(tmp_path: Path) -> dict[str, str]:
    """What the store would hold if every edition's recorded hash were its file's hash now."""
    root = tmp_path / "lake" / "editions"
    return {p.name: sha256_hex((p / "edition.json").read_bytes()) for p in root.iterdir() if p.is_dir()}


def gate(
    tmp_path: Path, edition_id: str = E0, *, params: Path | None = None, recorded: str | None = None
) -> Any:
    """The gate with the store's hashes kept in step with the files, unless `recorded` says otherwise."""
    here = folder(tmp_path, edition_id)
    return run_gate(
        here,
        frozen_root=params or tmp_path / "params",
        draw=load_draw(tmp_path / "data" / "preseason_draw_2026.csv", 2026),
        recorded=store(tmp_path) | ({edition_id: recorded} if recorded else {}),
    )


def plant(tmp_path: Path, change: Callable[[dict[str, Any]], None]) -> None:
    """Change the edition's document and keep the receipt in step, so only the content is wrong."""
    here = folder(tmp_path)
    doc = json.loads((here / "edition.json").read_bytes())
    change(doc)
    body = canonical(doc)
    rewrite(here / "edition.json", body)
    receipt = json.loads((here / "receipt.json").read_bytes()) | {"sha256": sha256_hex(body)}
    rewrite(here / "receipt.json", canonical(receipt))


def failed(report: Any) -> set[str]:
    return {check.name for check in report.checks if not check.passed}


def test_gate_passes_a_written_edition(tmp_path: Path) -> None:
    setup(tmp_path)
    assert build(tmp_path, C0) == 0
    assert build(tmp_path, C1) == 0  # the second edition names the first as its previous one
    for edition_id in (E0, E1):
        report = gate(tmp_path, edition_id)
        assert failed(report) == set()
        assert report.passed
        assert [check.name for check in report.checks] == list(CHECKS)
        assert report.sha256 == sha256_hex((folder(tmp_path, edition_id) / "edition.json").read_bytes())


def bump_points(doc: dict[str, Any]) -> None:
    doc["teams"][0]["rows"][0]["points_cp"] += 1


def bump_points_and_total(doc: dict[str, Any]) -> None:
    doc["teams"][0]["rows"][0]["points_cp"] += 1
    doc["teams"][0]["total_cp"] += 1


def flip_result(doc: dict[str, Any]) -> None:
    team = doc["teams"][0]
    row = next(r for r in team["rows"] if r["result"] == "W" and r["q"] is not None)
    team["total_cp"] -= 10000
    row["result"], row["points_cp"] = "L", -row["q"]
    team["wins"] -= 1
    team["losses"] += 1


def swap_order(doc: dict[str, Any]) -> None:
    doc["teams"][0]["order"], doc["teams"][1]["order"] = doc["teams"][1]["order"], doc["teams"][0]["order"]


def mismatch(doc: dict[str, Any]) -> None:
    doc["manifest"]["second_implementation"] = "mismatch"


@pytest.mark.parametrize(
    ("change", "check"),
    [
        (bump_points, "ledger sums"),
        (bump_points_and_total, "row arithmetic"),
        (flip_result, "results"),
        (swap_order, "ranks"),
        (mismatch, "second implementation"),
    ],
)
def test_gate_fails_on_planted_break(
    tmp_path: Path, change: Callable[[dict[str, Any]], None], check: str
) -> None:
    setup(tmp_path)
    assert build(tmp_path, C0) == 0
    plant(tmp_path, change)
    report = gate(tmp_path)
    assert check in failed(report)
    assert not report.passed
    assert (
        "rebuild" in failed(report) or check == "second implementation"
    )  # the same inputs no longer give these bytes


def test_gate_fails_on_files_and_parameters(tmp_path: Path) -> None:
    setup(tmp_path)
    assert build(tmp_path, C0) == 0
    here = folder(tmp_path)
    assert "hash" in failed(gate(tmp_path, recorded="0" * 64))  # not the hash recorded at issue
    other = tmp_path / "other"
    from cfp.open_ranking import RULE_VERSION_ID
    from cfp.open_ranking.frozen import write_frozen

    doc: dict[str, Any] = {"season": 2026, "lambda_c": 4.0, "lambda_u": 4.0, "t": 6.0, "cap": 24}
    doc |= {"independent_penalty": "combined", "status": "provisional", "rule_version_id": RULE_VERSION_ID}
    write_frozen(other, 2026, doc)
    assert "frozen parameters" in failed(gate(tmp_path, params=other))
    games = (here / "games.jsonl").read_bytes()
    lines = games.splitlines(keepends=True)
    late = json.loads(lines[0]) | {"start_utc": "2026-12-25T17:00:00+00:00"}
    rewrite(here / "games.jsonl", canonical(late) + b"".join(lines[1:]))
    report = gate(tmp_path)
    assert {"games file", "inputs"} <= failed(report)  # changed bytes, and a game after the cutoff
    rewrite(here / "games.jsonl", games)
    assert gate(tmp_path).passed
    issued = sha256_hex((here / "edition.json").read_bytes())
    assert gate(tmp_path, recorded=issued).passed
    rewrite(here / "edition.json", (here / "edition.json").read_bytes() + b" ")
    assert "hash" in failed(gate(tmp_path, recorded=issued))


def test_gate_second_impl_not_run_state(tmp_path: Path) -> None:
    """RL-01a: until a second implementation exists the gate records "not run" and does not fail on it."""
    setup(tmp_path)
    assert build(tmp_path, C0) == 0
    report = gate(tmp_path)
    (check,) = [c for c in report.checks if c.name == "second implementation"]
    assert check.passed
    assert "not run" in check.detail
    assert report.second_implementation == "not run"
    assert report.document()["second_implementation"] == "not run"


def run(tmp_path: Path, *argv: str) -> int:
    head = ["--lake", str(tmp_path / "lake"), "--data", str(tmp_path / "data")]
    return cli.main([*head, *argv, "--frozen", str(tmp_path / "params")])


def test_gate_and_publish_commands(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    setup(tmp_path)
    assert build(tmp_path, C0) == 0
    site = tmp_path / "site"
    assert run(tmp_path, "gate", E0) == 0
    out = capsys.readouterr().out
    assert all(f"PASS  {name}" in out for name in CHECKS)
    assert run(tmp_path, "gate", "or-2026-20990101t0000z-replay-e1") == 1  # no such edition
    assert run(tmp_path, "publish", "--edition", E0, "--site", str(site)) == 0
    public = site / "open-ranking" / E0
    assert sorted(p.name for p in public.iterdir()) == [
        "edition.json",
        "games.jsonl",
        "gate.json",
        "index.html",
    ]
    assert (public / "edition.json").read_bytes() == (folder(tmp_path) / "edition.json").read_bytes()
    assert json.loads((public / "gate.json").read_text())["passed"] is True
    page = (public / "index.html").read_text()
    doc = json.loads((public / "edition.json").read_bytes())
    top = doc["teams"][0]
    assert "Open Ranking" in page
    assert sha256_hex((public / "edition.json").read_bytes()) in page
    assert f"Team {top['team_id'][1:]}" in page  # names, not ids
    assert f"{top['total_cp'] / 100:+.2f}" in page
    assert "second implementation: not run" in page.lower()
    assert "provisional" in page
    for missing in ("Sensitivity intervals", "Rank-reversal report", "What-if tool"):
        assert missing in page
    assert "not delivered in the pilot" in page
    assert (site / "open-ranking" / "latest" / "index.html").read_text() == page
    assert (
        run(tmp_path, "publish", "--edition", E0, "--site", str(site)) == 0
    )  # the same bytes again: no change
    # an earlier edition never replaces a later one as the latest
    assert build(tmp_path, C1) == 0
    assert run(tmp_path, "publish", "--edition", E1, "--site", str(site)) == 0
    assert run(tmp_path, "publish", "--edition", E0, "--site", str(site)) == 0
    assert E1 in (site / "open-ranking" / "latest" / "index.html").read_text()


def test_publish_refuses_an_edition_that_fails_the_gate(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    setup(tmp_path)
    assert build(tmp_path, C0) == 0
    plant(tmp_path, bump_points)  # the receipt is in step, but the store's recorded hash is not
    site = tmp_path / "site"
    assert run(tmp_path, "gate", E0) == 1
    assert "FAIL  hash" in capsys.readouterr().out
    assert run(tmp_path, "publish", "--edition", E0, "--site", str(site)) == 1
    assert "gate" in capsys.readouterr().err
    assert not site.exists()


def shift_q(doc: dict[str, Any]) -> None:
    """A different opponent strength, carried through the row and the total: self-consistent, and wrong."""
    team = doc["teams"][0]
    row = next(r for r in team["rows"] if r["q"] is not None and 10 < r["q"] < 9990)
    row["q"] += 7
    row["points_cp"] -= 7
    team["total_cp"] -= 7


def test_only_the_rebuild_catches_a_self_consistent_change(tmp_path: Path) -> None:
    setup(tmp_path)
    assert build(tmp_path, C0) == 0
    plant(tmp_path, shift_q)
    assert failed(gate(tmp_path)) <= {"rebuild", "ranks"}
    assert "rebuild" in failed(gate(tmp_path))


def test_gate_checks_games_against_the_cutoff_and_the_previous_edition_against_the_store(
    tmp_path: Path,
) -> None:
    setup(tmp_path)
    assert build(tmp_path, C0) == 0
    assert build(tmp_path, C1) == 0
    # the second edition names the first; if the store recorded something else for it, the chain is broken
    wrong = store(tmp_path) | {E0: "0" * 64}
    report = run_gate(
        folder(tmp_path, E1),
        frozen_root=tmp_path / "params",
        draw=load_draw(tmp_path / "data" / "preseason_draw_2026.csv", 2026),
        recorded=wrong,
    )
    assert failed(report) == {"rebuild"}

    def earlier_cutoff(doc: dict[str, Any]) -> None:  # claims an earlier cutoff than its games allow
        doc["cutoff_utc"] = "2026-10-11T07:00:00+00:00"

    plant(tmp_path, earlier_cutoff)
    assert "inputs" in failed(gate(tmp_path))


def test_a_replay_edition_never_replaces_a_live_latest(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    setup(tmp_path)
    assert build(tmp_path, C0) == 0
    site = tmp_path / "site"
    latest = site / "open-ranking" / "latest"
    latest.mkdir(parents=True)
    shown = {
        "mode": "live",
        "cutoff_utc": "2026-10-01T07:00:00+00:00",
        "revision": 1,
        "edition_id": "live-one",
    }
    (latest / "edition.json").write_bytes(canonical(shown))
    assert run(tmp_path, "publish", "--edition", E0, "--site", str(site)) == 0
    assert "never replaces a live one" in capsys.readouterr().out
    assert json.loads((latest / "edition.json").read_bytes()) == shown
    assert {p.name for p in (site / "open-ranking").iterdir()} == {E0, "latest"}  # no staging left behind
    page = (site / "open-ranking" / E0 / "index.html").read_text()
    for shown_once in ("Calibration report", "Bracket", "Change since last edition", "raw rank", "Snapshot:"):
        assert shown_once in page
    before = (site / "open-ranking" / E0 / "index.html").stat().st_mtime_ns
    assert run(tmp_path, "publish", "--edition", E0, "--site", str(site)) == 0  # already published: untouched
    assert (site / "open-ranking" / E0 / "index.html").stat().st_mtime_ns == before
