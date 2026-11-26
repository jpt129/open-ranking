"""The scorecard and `cfp score` (VT-11, VT-13): score every edition issued for a reveal, write once."""

from __future__ import annotations

import json
from datetime import timedelta
from pathlib import Path

import pytest

from cfp import cli
from cfp.common.hashing import sha256_hex
from cfp.scoring.scorecard import ScoreRefused, not_prospective, score_edition
from cfp.store.lake import Lake

from .store_helpers import Clock, frame
from .test_issue import CUTOFF, REVEAL, TEAMS, release_rows, run_live, world

ACTUAL = [*TEAMS[:2], *TEAMS[3:24], "T03", "T26"]  # T03 lost and fell; T25 dropped out; T26 came in
AFTER = REVEAL + timedelta(hours=1)


def reveal(tmp_path: Path, ranked: list[str] = ACTUAL) -> None:
    lake = Lake(tmp_path / "lake", clock=Clock(REVEAL + timedelta(minutes=10)))
    lake.append("committee_releases", frame("committee_releases", release_rows(lake, 2, REVEAL, ranked)))


def score(tmp_path: Path, *extra: str, at: object = AFTER) -> int:
    argv = ["--lake", str(tmp_path / "lake"), "score", "--release", "cfp-2026-02", *extra]
    return cli._score(cli.build_parser().parse_args(argv), Clock(at))  # type: ignore[arg-type]


def test_score_command_writes_one_scorecard(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    world(tmp_path)
    assert run_live(tmp_path, CUTOFF + timedelta(minutes=5), monkeypatch) == 0
    assert score(tmp_path) == 1  # the release is not in the store yet
    assert "ingest" in capsys.readouterr().err
    reveal(tmp_path)
    assert score(tmp_path, at=REVEAL - timedelta(minutes=1)) == 1  # nothing is scored before the reveal
    assert score(tmp_path) == 0
    out = capsys.readouterr().out
    folder = tmp_path / "lake" / "scorecards" / "score-2026-r02-e1"
    body = (folder / "scorecard.json").read_bytes()
    assert sha256_hex(body) in out
    assert not folder.stat().st_mode & 0o222
    card = json.loads(body)
    assert (card["release_id"], card["actual"], card["prior_release_id"]) == (
        "cfp-2026-02",
        ACTUAL,
        "cfp-2026-01",
    )
    assert card["fitted_model"] == "not issued"
    (edition,) = card["editions"]
    assert edition["edition_id"] == "scw-2026-r02-sun0200-e1"
    assert edition["hash_matches_issue"] is True
    assert edition["prospective"] is True
    one, two = edition["models"]["baseline1"], edition["models"]["baseline2"]
    assert one["teams"] == two["teams"] == 30  # every team in the data, not an assumed count
    assert 0 < two["score"] < one["score"]  # Baseline 2 moved the loser down; AP as issued did not
    assert two["movement"]["entrants"] == ["T26"]
    assert two["movement"]["exits"] == ["T25"]
    assert score(tmp_path) == cli.EXIT_EXISTS  # write-once
    assert score(tmp_path, "--revision", "2") == 0
    again = json.loads((folder.parent / "score-2026-r02-e2" / "scorecard.json").read_bytes())
    assert again["supersedes"] == "score-2026-r02-e1"
    assert again["editions"] == card["editions"]  # the same inputs score the same


def test_score_refuses_an_edition_whose_bytes_changed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    world(tmp_path)
    assert run_live(tmp_path, CUTOFF + timedelta(minutes=5), monkeypatch) == 0
    reveal(tmp_path)
    folder = tmp_path / "lake" / "editions" / "scw-2026-r02-sun0200-e1"
    folder.chmod(0o755)
    (folder / "edition.json").chmod(0o644)
    (folder / "edition.json").write_bytes((folder / "edition.json").read_bytes() + b" ")
    assert score(tmp_path) == 1
    assert "hash" in capsys.readouterr().err
    assert not (tmp_path / "lake" / "scorecards").exists()


def test_score_refuses_with_no_edition_or_a_short_release(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    world(tmp_path)
    reveal(tmp_path)
    assert score(tmp_path) == 1
    assert "no edition" in capsys.readouterr().err


def test_a_replay_edition_is_scored_but_never_counted_as_prospective(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    world(tmp_path)
    reveal(tmp_path)
    assert run_live(tmp_path, AFTER, monkeypatch, "--mode", "replay") == 0  # built after the reveal
    assert score(tmp_path, at=AFTER + timedelta(hours=1)) == 0
    card = json.loads(
        (tmp_path / "lake" / "scorecards" / "score-2026-r02-e1" / "scorecard.json").read_bytes()
    )
    (edition,) = card["editions"]
    assert edition["prospective"] is False
    assert edition["not_prospective_because"]
    assert card["prospective_editions"] == 0


def doc(order: list[str], counts: dict[str, list[int]] | None, paths: int = 100) -> dict[str, object]:
    rows = [{"team_id": t, "p_top25": 0.5} | ({"rank_counts": counts[t]} if counts else {}) for t in order]
    return {
        "season": 2026,
        "rank_noise": {"paths": paths} if counts else None,
        "final_field": None,
        "forecasts": {
            "baseline1": {"order": order} | ({"rank_counts": counts} if counts else {}),
            "baseline2": {"rows": rows},
        },
    }


def test_score_edition_reads_counts_or_scores_a_point_order_as_certain() -> None:
    order = TEAMS
    exact = {t: [100 if k == place else 0 for k in range(26)] for place, t in enumerate(order[:25])}
    exact |= {t: [0] * 25 + [100] for t in order[25:]}
    got = score_edition(doc(order, exact), TEAMS[:25], prior=None)
    assert got["models"]["baseline2"]["score"] == 0.0
    assert got["models"]["baseline2"]["forecast"] == "sampled ranks"
    assert got["models"]["baseline2"]["movement"] is None
    point = score_edition(doc(order, None), TEAMS[:25], prior=TEAMS[:25])
    assert point["models"]["baseline1"]["score"] == 0.0
    assert point["models"]["baseline1"]["forecast"] == "point order, scored as certain"
    with pytest.raises(ScoreRefused, match="T30"):
        score_edition(doc(order[:29], None), [*TEAMS[:24], "T30"], prior=None)


def test_only_an_edition_issued_and_recorded_before_the_reveal_is_prospective() -> None:
    early = REVEAL - timedelta(hours=2)
    doc = {"prospective_eligible": True, "cutoff_utc": (REVEAL - timedelta(hours=3)).isoformat()}
    row = {"vintage": "live", "first_public_time": early, "ingest_time": early}
    assert not_prospective(doc, row, REVEAL) == []
    late = REVEAL + timedelta(minutes=1)
    assert "issued after" in not_prospective(doc, row | {"first_public_time": late}, REVEAL)[0]
    # a row written later with an early receipt time: the store's own stamp decides
    assert "recorded in the store after" in not_prospective(doc, row | {"ingest_time": late}, REVEAL)[0]
    assert "cutoff" in not_prospective(doc | {"cutoff_utc": REVEAL.isoformat()}, row, REVEAL)[0]
    assert "vintage" in not_prospective(doc, row | {"vintage": "reconstructed"}, REVEAL)[0]
    assert "eligible" in not_prospective(doc | {"prospective_eligible": False}, row, REVEAL)[0]
    assert "supersedes" in not_prospective(doc, row, REVEAL, superseded=True)[0]
