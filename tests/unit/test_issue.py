"""Issue pipeline and proof (P23; SC-02, RL-03): build at the cutoff, write once, hash, prove."""

from __future__ import annotations

import json
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest

from cfp import cli
from cfp.cli import main
from cfp.common.hashing import sha256_hex
from cfp.release.edition import EditionExists, canonical, write_edition
from cfp.release.issue import IssueRefused, TooEarly, Unresolved, build_issue, due_issue
from cfp.release.proof import ProofError, granted, post_text, request_token, tag_commands, timestamp_query
from cfp.store.lake import Lake

from .store_helpers import Clock, frame, game

AUG = datetime(2026, 8, 20, 4, 0, tzinfo=UTC)
PRIOR = datetime(2026, 11, 25, 0, 30, tzinfo=UTC)  # Tue 24 Nov 19:30 ET
REVEAL = datetime(2026, 12, 2, 0, 0, tzinfo=UTC)  # Tue 1 Dec 19:00 ET
CUTOFF = datetime(2026, 11, 29, 7, 0, tzinfo=UTC)  # Sun 29 Nov 02:00 ET
REVEALS = [PRIOR, REVEAL]
TEAMS = [f"T{i:02d}" for i in range(1, 31)]
DRAW = {team: position for position, team in enumerate(TEAMS, start=1)}
SAT = datetime(2026, 11, 28, 17, 0, tzinfo=UTC)


def prov(lake: Lake, label: str, public: datetime) -> dict[str, Any]:
    return {
        "source_id": "test",
        "event_time": public,
        "first_public_time": public,
        "ingest_time": None,
        "correction_version": 0,
        "raw_hash": lake.put_raw(label.encode()),
        "vintage": "live",
    }


def release_rows(lake: Lake, number: int, reveal: datetime, ranked: list[str]) -> list[dict[str, Any]]:
    return [
        {
            "release_id": f"cfp-2026-{number:02d}",
            "rank": rank,
            "season": 2026,
            "release_no": number,
            "reveal_utc": reveal,
            "team_id": team,
            "source_name": team,
            "archive_capture_utc": None,
            "archive_raw_hash": None,
        }
        | prov(lake, f"release{number}", reveal)
        for rank, team in enumerate(ranked, start=1)
    ]


def world(
    root: Path,
    *,
    others: bool = True,
    prior: bool = True,
    ingested: datetime | None = None,
    leagues: dict[str, str] | None = None,
) -> Lake:
    """Thirty FBS teams, the 24 Nov release, the week-13 AP poll and one Saturday loss by T03."""
    lake = Lake(root / "lake", clock=Clock(ingested or CUTOFF - timedelta(hours=1)))
    lake.append(
        "teams",
        frame(
            "teams",
            [
                {"team_id": t, "name": f"School {t}", "cfbd_id": i, "espn_id": None, "kalshi_code": None}
                | prov(lake, t, AUG)
                for i, t in enumerate(TEAMS)
            ],
        ),
    )
    lake.append(
        "membership",
        frame(
            "membership",
            [
                {
                    "team_id": t,
                    "valid_from": date(2026, 8, 1),
                    "valid_to": date(2027, 7, 31),
                    "conference_id": (leagues or {}).get(t, "sec"),
                    "division": "fbs",
                    "cfp_group": None,
                    "source_url": "https://example.test/m",
                }
                | prov(lake, "m" + t, AUG)
                for t in TEAMS
            ],
        ),
    )
    if prior:
        lake.append(
            "committee_releases", frame("committee_releases", release_rows(lake, 1, PRIOR, TEAMS[:25]))
        )
    poll_public = datetime(2026, 11, 24, 22, 0, tzinfo=UTC)
    votes: list[tuple[str, int | None, int]] = [
        (t, r, 1600 - 50 * r) for r, t in enumerate(TEAMS[:25], start=1)
    ]
    if others:
        votes += [("T27", None, 30), ("T26", None, 12)]
    lake.append(
        "polls",
        frame(
            "polls",
            [
                {
                    "poll": "ap",
                    "season": 2026,
                    "week": 13,
                    "team_id": t,
                    "rank": r,
                    "points": p,
                    "fpv": 0,
                    "others_votes": r is None,
                }
                | prov(lake, "ap13", poll_public)
                for t, r, p in votes
            ],
        ),
    )
    final = SAT + timedelta(hours=4, minutes=30)
    lost = game(
        lake,
        "g-loss",
        home_id="T03",
        away_id="T09",
        home_pts=10,
        away_pts=20,
        start_utc=SAT,
        week=14,
        event_time=final,
        first_public_time=final,
    )
    lake.append("games", frame("games", [lost]))
    return lake


def issue(lake: Lake, **over: Any) -> Any:
    args: dict[str, Any] = {
        "season": 2026,
        "issue": "sun0200",
        "reveal": REVEAL,
        "reveals": REVEALS,
        "mode": "live",
        "now": CUTOFF + timedelta(minutes=5),
        "code_hash": "abc1234",
        "draw": DRAW,
    }
    return build_issue(lake, **(args | over))


def test_issue_builds_baselines_at_the_cutoff(tmp_path: Path) -> None:
    built = issue(world(tmp_path))
    doc = built.doc
    assert built.edition_id == "scw-2026-r02-sun0200-e1"
    assert (doc["cutoff_utc"], doc["reveal_utc"]) == (
        "2026-11-29T07:00:00+00:00",
        "2026-12-02T00:00:00+00:00",
    )
    assert (doc["target_release_no"], doc["prospective_eligible"], doc["label_leaked"]) == (2, True, False)
    assert doc["headline_forecast"] == "baseline2"
    assert doc["missing_inputs"] == ["open_points", "rank_noise_temperature", "designated_group_team"]
    assert doc["forecasts"]["baseline1"]["top25"] == TEAMS[:25]
    b2 = doc["forecasts"]["baseline2"]
    assert b2["anchor"] == {
        "kind": "cfp_release",
        "release_id": "cfp-2026-01",
        "since_utc": PRIOR.isoformat(),
        "designated_team": None,
        "designated_source": None,
    }
    t03 = next(row for row in b2["rows"] if row["team_id"] == "T03")
    assert (t03["initial"], t03["losses"], t03["adjusted"], t03["position"]) == (3, 1, 8, 7)
    assert [row["team_id"] for row in b2["rows"]][24:27] == ["T25", "T27", "T26"]
    assert len(b2["rows"]) == 30
    assert built.sha256 == sha256_hex(built.body)
    assert built.body == canonical(doc)
    assert any(item.startswith("games:") for item in doc["inputs"])


def test_hash_replays_bytewise(tmp_path: Path) -> None:
    lake = world(tmp_path)
    first = issue(lake)
    again = issue(lake, now=CUTOFF + timedelta(hours=30))  # the wall clock is not part of the edition
    assert (first.body, first.sha256) == (again.body, again.sha256)
    other = world(tmp_path / "other")
    assert issue(other).body == first.body  # a second store holding the same rows gives the same bytes
    # a result that became public after the cutoff changes nothing; one before it does
    late = SAT + timedelta(hours=18)
    later = Lake(tmp_path / "lake", clock=Clock(late + timedelta(hours=1)))
    row = game(later, "g-late", home_id="T01", away_id="T02", home_pts=3, away_pts=9, start_utc=SAT)
    later.append("games", frame("games", [row | {"event_time": late, "first_public_time": late}]))
    assert issue(lake).sha256 == first.sha256
    assert issue(lake, code_hash="def5678").sha256 != first.sha256


def test_live_issue_sees_only_what_was_ingested_by_the_cutoff(tmp_path: Path) -> None:
    lake = world(tmp_path)
    Lake(tmp_path / "lake", clock=Clock(CUTOFF + timedelta(minutes=1))).append(
        "games",
        frame(
            "games",
            [game(lake, "g2", home_id="T01", away_id="T02", home_pts=3, away_pts=9, start_utc=SAT, week=14)],
        ),
    )
    rows = issue(lake).doc["forecasts"]["baseline2"]["rows"]
    assert next(r for r in rows if r["team_id"] == "T01")["losses"] == 0  # public in time, but ingested late
    replay = issue(lake, mode="replay").doc
    assert next(r for r in replay["forecasts"]["baseline2"]["rows"] if r["team_id"] == "T01")["losses"] == 1
    assert replay["prospective_eligible"] is False  # a replay is never a prospective forecast


def test_issue_refuses_outside_its_window_or_without_inputs(tmp_path: Path) -> None:
    lake = world(tmp_path)
    with pytest.raises(IssueRefused, match="after the reveal"):
        issue(lake, now=REVEAL)
    with pytest.raises(TooEarly, match="before the cutoff"):
        issue(lake, now=CUTOFF - timedelta(seconds=1))
    with pytest.raises(IssueRefused, match="not a scheduled reveal"):
        issue(lake, reveal=REVEAL + timedelta(days=1))
    degraded = issue(world(tmp_path / "a", others=False)).doc  # disclosed, not fatal
    assert "ap_votes_outside_25" in degraded["missing_inputs"]
    with pytest.raises(IssueRefused, match="cfp-2026-01"):
        issue(world(tmp_path / "b", prior=False))  # the schedule says a release exists; the store lacks it


def test_leaked_label_marks_the_edition_ineligible(tmp_path: Path) -> None:
    lake = world(tmp_path)
    leak = [
        row | {"first_public_time": CUTOFF - timedelta(hours=2)}
        for row in release_rows(lake, 2, REVEAL, TEAMS[:25])
    ]
    lake.append("committee_releases", frame("committee_releases", leak))
    doc = issue(lake).doc
    assert (doc["label_leaked"], doc["prospective_eligible"]) == (True, False)
    assert (
        doc["forecasts"]["baseline2"]["anchor"]["release_id"] == "cfp-2026-01"
    )  # the leak is never used as input


def test_opening_week_anchors_on_ap(tmp_path: Path) -> None:
    lake = world(tmp_path, prior=False)
    doc = issue(lake, reveals=[REVEAL]).doc
    anchor = doc["forecasts"]["baseline2"]["anchor"]
    assert (anchor["kind"], anchor["ap_week"]) == ("ap_poll", 13)
    t03 = next(row for row in doc["forecasts"]["baseline2"]["rows"] if row["team_id"] == "T03")
    assert t03["losses"] == 1  # the week-13 poll follows week 12, so week-14 results count


# --- write-once editions ---------------------------------------------------------


def test_editions_write_once(tmp_path: Path) -> None:
    body = canonical({"b": 1, "a": [2, 1]})
    assert body == b'{"a":[2,1],"b":1}\n'
    folder = write_edition(tmp_path / "editions", "scw-test-e1", body, {"sha256": sha256_hex(body)})
    assert (folder / "edition.json").read_bytes() == body
    assert json.loads((folder / "receipt.json").read_text())["sha256"] == sha256_hex(body)
    assert not (folder / "edition.json").stat().st_mode & 0o222  # read-only
    with pytest.raises(EditionExists):
        write_edition(tmp_path / "editions", "scw-test-e1", body, {})
    with pytest.raises(ValueError, match="edition id"):
        write_edition(tmp_path / "editions", "../escape", body, {})


# --- proof (RL-03) ---------------------------------------------------------------

DIGEST = "ab" * 32


def test_timestamp_query_is_the_rfc3161_request_for_the_hash() -> None:
    query = timestamp_query(DIGEST)
    head = bytes(
        [
            0x30,
            0x39,
            2,
            1,
            1,
            0x30,
            0x31,
            0x30,
            0x0D,
            6,
            9,
            0x60,
            0x86,
            0x48,
            1,
            0x65,
            3,
            4,
            2,
            1,
            5,
            0,
            4,
            0x20,
        ]
    )
    assert query == head + bytes.fromhex(DIGEST) + bytes.fromhex("0101ff")
    with pytest.raises(ValueError, match="SHA-256"):
        timestamp_query("xyz")


def reply(status: int = 0, digest: str = DIGEST) -> bytes:
    inner = bytes([0x30, 0x03, 0x02, 0x01, status]) + b"\x30\x82\x01\x00token" + bytes.fromhex(digest)
    return bytes([0x30, 0x82, len(inner) >> 8, len(inner) & 0xFF]) + inner


def test_token_is_kept_only_if_granted_for_this_hash() -> None:
    assert granted(reply(), DIGEST)
    assert not granted(reply(status=2), DIGEST)
    assert not granted(reply(digest="cd" * 32), DIGEST)
    assert not granted(b"<html>busy</html>", DIGEST)
    calls: list[str] = []

    def post(url: str, body: bytes) -> bytes:
        calls.append(url)
        assert body == timestamp_query(DIGEST)
        return reply(status=2) if len(calls) == 1 else reply()

    token, authority = request_token(DIGEST, post, ("https://one.test/tsr", "https://two.test/tsr"))
    assert (token, authority, len(calls)) == (reply(), "https://two.test/tsr", 2)
    with pytest.raises(ProofError, match="no timestamp authority"):
        request_token(DIGEST, lambda url, body: b"", ("https://one.test/tsr",))


def test_tag_and_post_text() -> None:
    commands = tag_commands("scw-2026-r02-sun0200-e1", DIGEST, push=True)
    assert commands[0][:4] == ["git", "tag", "-s", "issue/scw-2026-r02-sun0200-e1"]
    assert DIGEST in commands[0][-1]
    assert commands[1] == ["git", "push", "origin", "refs/tags/issue/scw-2026-r02-sun0200-e1"]
    assert len(tag_commands("x", DIGEST, push=False)) == 1
    text = post_text("scw-2026-r02-sun0200-e1", DIGEST, CUTOFF, REVEAL)
    for part in (DIGEST, "scw-2026-r02-sun0200-e1", "Open Ranking Models"):
        assert part in text


# --- command line ------------------------------------------------------------------


def cli_args(tmp_path: Path, *extra: str) -> list[str]:
    data = tmp_path / "data"
    data.mkdir(exist_ok=True)
    head = "season,release_date,show_date,show_start_et,basis,source_url,quote,notes\n"
    rows = "2026,2026-11-24,2026-11-24,19:30,primary,https://example.test/s,,\n"
    rows += "2026,2026-12-01,2026-12-01,19:00,primary,https://example.test/s,,\n"
    (data / "cfp_reveals.csv").write_text(head + rows)
    lines = [f"2026,{position},{team},School\n" for team, position in DRAW.items()]
    (data / "preseason_draw_2026.csv").write_text("season,position,team_id,name\n" + "".join(lines))
    argv = ["--lake", str(tmp_path / "lake"), "--data", str(data), "forecast", "issue", "--season", "2026"]
    return [*argv, "--issue", "sun0200", "--reveal", "2026-12-01", "--no-proof", *extra]


def run_cli(tmp_path: Path, now: datetime, *extra: str) -> int:
    """A dry run at a frozen time."""
    return main([*cli_args(tmp_path, *extra), "--now", now.isoformat()])


def run_live(tmp_path: Path, now: datetime, monkeypatch: pytest.MonkeyPatch, *extra: str) -> int:
    """The live command with the clock and the code hash pinned."""
    monkeypatch.setattr(cli, "_code_hash", lambda: "abc1234")
    return cli._forecast_issue(cli.build_parser().parse_args(cli_args(tmp_path, *extra)), Clock(now))


def test_frozen_clock_after_reveal_exits_nonzero(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    world(tmp_path)
    assert run_cli(tmp_path, REVEAL + timedelta(minutes=1)) != 0
    assert "after the reveal" in capsys.readouterr().err
    assert not (tmp_path / "lake" / "editions").exists()


def test_issue_refuses_after_reveal(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    world(tmp_path)
    assert run_live(tmp_path, REVEAL, monkeypatch) == 1
    assert run_live(tmp_path, CUTOFF - timedelta(minutes=1), monkeypatch) == 75  # too early: try again
    assert not (tmp_path / "lake" / "editions").exists()


def test_dry_run_never_takes_the_live_edition_id(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    lake = world(tmp_path)
    now = CUTOFF + timedelta(minutes=5)
    assert run_cli(tmp_path, now) == 0
    folder = tmp_path / "lake" / "editions"
    dry = json.loads((folder / "scw-2026-r02-sun0200-dry-e1" / "edition.json").read_text())
    assert (dry["dry_run"], dry["prospective_eligible"]) == (True, False)
    assert lake.scan("editions").collect().height == 0  # a dry run is not recorded as an edition
    assert main([*cli_args(tmp_path), "--mode", "replay", "--revision", "0"]) == 1
    assert main([*cli_args(tmp_path), "--mode", "replay"]) == 0
    assert (folder / "scw-2026-r02-sun0200-replay-e1").is_dir()
    assert run_live(tmp_path, now, monkeypatch) == 0  # the live ID was still free
    live = json.loads((folder / "scw-2026-r02-sun0200-e1" / "edition.json").read_text())
    assert (live["dry_run"], live["prospective_eligible"], live["mode"]) == (False, True, "live")


def test_cli_writes_the_edition_once_and_records_it(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    lake = world(tmp_path)
    now = CUTOFF + timedelta(minutes=5)
    assert run_live(tmp_path, now, monkeypatch) == 0
    out = capsys.readouterr().out
    folder = tmp_path / "lake" / "editions" / "scw-2026-r02-sun0200-e1"
    body = (folder / "edition.json").read_bytes()
    assert sha256_hex(body) in out
    receipt = json.loads((folder / "receipt.json").read_text())
    assert (receipt["sha256"], receipt["issued_utc"], receipt["dry_run"]) == (
        sha256_hex(body),
        now.isoformat(),
        False,
    )
    assert not folder.stat().st_mode & 0o222  # the folder is read-only too
    assert not list(folder.parent.glob(".staging-*"))
    stored = lake.scan("editions").collect().row(0, named=True)
    assert (stored["edition_id"], stored["sha256"]) == ("scw-2026-r02-sun0200-e1", sha256_hex(body))
    assert (stored["product"], stored["vintage"]) == ("shadow_committee_weekly", "live")
    assert (stored["first_public_time"], stored["ingest_time"]) == (now, now)
    assert run_live(tmp_path, now, monkeypatch) == 17  # the same edition cannot be written twice
    assert lake.scan("editions").collect().height == 1


def test_a_run_that_died_before_recording_is_repaired(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    lake = world(tmp_path)
    now = CUTOFF + timedelta(minutes=5)
    built = issue(lake)
    receipt = {"sha256": built.sha256, "issued_utc": now.isoformat()}
    write_edition(tmp_path / "lake" / "editions", built.edition_id, built.body, receipt)
    assert lake.scan("editions").collect().height == 0
    assert run_live(tmp_path, now + timedelta(minutes=3), monkeypatch) == 17
    stored = lake.scan("editions").collect().row(0, named=True)
    assert (stored["sha256"], stored["first_public_time"]) == (built.sha256, now)


def test_correction_creates_new_edition(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    world(tmp_path)
    now = CUTOFF + timedelta(minutes=5)
    assert run_live(tmp_path, now, monkeypatch, "--revision", "2") == 1  # nothing to supersede yet
    assert run_live(tmp_path, now, monkeypatch) == 0
    assert run_live(tmp_path, now, monkeypatch, "--revision", "2") == 0
    folder = tmp_path / "lake" / "editions"
    first = (folder / "scw-2026-r02-sun0200-e1" / "edition.json").read_bytes()
    second = json.loads((folder / "scw-2026-r02-sun0200-e2" / "edition.json").read_text())
    assert second["supersedes"] == "scw-2026-r02-sun0200-e1"
    assert json.loads(first)["supersedes"] is None
    assert (
        folder / "scw-2026-r02-sun0200-e1" / "edition.json"
    ).read_bytes() == first  # the original is untouched


def test_stale_results_refuse_a_live_issue_unless_disclosed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    lake = world(tmp_path)
    pending = game(
        lake, "g-pending", home_id="T05", away_id="T06", home_pts=None, away_pts=None, start_utc=SAT
    )
    old = game(lake, "g-old", home_id="T07", away_id="T08", start_utc=SAT - timedelta(days=30))
    late = game(lake, "g-late-kick", home_id="T10", away_id="T11", start_utc=CUTOFF - timedelta(hours=3))
    lower = game(lake, "g-lower", home_id="X1", away_id="X2", start_utc=SAT)
    rows = [
        row | {"status": "scheduled", "home_pts": None, "away_pts": None}
        for row in (pending, old, late, lower)
    ]
    public = datetime(2026, 9, 1, tzinfo=UTC)
    lake.append(
        "games", frame("games", [row | {"event_time": public, "first_public_time": public} for row in rows])
    )
    with pytest.raises(Unresolved, match="g-pending"):
        issue(lake)
    doc = issue(lake, allow_unresolved=True).doc
    assert doc["unresolved_games"] == [
        "g-pending"
    ]  # not the month-old game, the late kickoff or the outsiders
    assert issue(lake, mode="replay").doc["unresolved_games"] == ["g-pending"]  # a replay only records them
    now = CUTOFF + timedelta(minutes=5)
    assert run_live(tmp_path, now, monkeypatch) == 18
    assert run_live(tmp_path, now, monkeypatch, "--allow-unresolved") == 0


def test_live_issue_needs_committed_code_and_notes_a_missing_ap_poll(tmp_path: Path) -> None:
    lake = world(tmp_path)
    for bad in ("abc1234-dirty", "unknown"):
        with pytest.raises(IssueRefused, match="committed code"):
            issue(lake, code_hash=bad)
    assert issue(lake, code_hash="abc1234-dirty", dry_run=True).edition_id.endswith("-dry-e1")
    assert "latest_ap_poll" not in issue(lake).doc["missing_inputs"]  # week 14 finished on Saturday
    tuesday = issue(lake, issue="tminus60", now=REVEAL - timedelta(minutes=30)).doc
    assert "latest_ap_poll" in tuesday["missing_inputs"]  # by Tuesday evening the week-15 poll should be in


def test_due_issue_picks_the_cutoff_that_is_near() -> None:
    selection = datetime(2026, 12, 6, 17, 0, tzinfo=UTC)
    reveals = [PRIOR, REVEAL, selection]
    assert due_issue(reveals, CUTOFF - timedelta(hours=4)) is None
    assert due_issue(reveals, CUTOFF - timedelta(hours=2)) == ("sun0200", REVEAL)
    assert due_issue(reveals, CUTOFF + timedelta(minutes=40)) == (
        "sun0200",
        REVEAL,
    )  # a late start still issues
    assert due_issue(reveals, CUTOFF + timedelta(hours=2)) is None
    assert due_issue(reveals, REVEAL - timedelta(minutes=90)) == ("tminus60", REVEAL)
    assert due_issue(reveals, REVEAL - timedelta(minutes=10)) == ("tminus60", REVEAL)
    assert due_issue(reveals, REVEAL) is None  # never after the reveal
    assert due_issue(reveals, selection - timedelta(hours=11)) == ("sun0200", selection)
    assert due_issue(reveals, selection - timedelta(hours=3)) == ("tminus60", selection)


def test_due_command_prints_issue_date_and_cutoff(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    world(tmp_path)
    run_cli(tmp_path, REVEAL + timedelta(minutes=1))  # writes the data files; refused after the reveal
    capsys.readouterr()
    base = [
        "--lake",
        str(tmp_path / "lake"),
        "--data",
        str(tmp_path / "data"),
        "forecast",
        "due",
        "--season",
        "2026",
    ]
    assert main([*base, "--now", (CUTOFF - timedelta(hours=1)).isoformat()]) == 0
    assert capsys.readouterr().out.split() == ["sun0200", "2026-12-01", str(int(CUTOFF.timestamp()))]
    assert main([*base, "--now", (CUTOFF - timedelta(days=2)).isoformat()]) == 0
    assert capsys.readouterr().out == ""
