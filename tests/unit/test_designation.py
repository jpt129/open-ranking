"""The committee's designated team from the six-conference group (BR-2026): sourced, dated, placed 26th."""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
from pathlib import Path

import polars as pl
import pytest

from cfp.forecast.baselines import initial_order
from cfp.forecast.designations import DesignationError, designated_for, load_designations, needs_designation

from .test_issue import CUTOFF, DRAW, PRIOR, TEAMS, issue, world

HEAD = "season,release_date,team_id,team,basis,source_url,first_public_utc,quote,notes\n"
ROW = '2026,2026-11-24,T28,School T28,primary,https://example.test/release,2026-11-25T01:10:00+00:00,"quoted",\n'


def write(tmp_path: Path, body: str) -> Path:
    path = tmp_path / "committee_designations.csv"
    path.write_text(HEAD + body)
    return path


def test_load_and_pick_by_release_and_cutoff(tmp_path: Path) -> None:
    rows = load_designations(write(tmp_path, ROW))
    assert rows.sha256 == load_designations(write(tmp_path, ROW)).sha256
    found = designated_for(rows, 2026, date(2026, 11, 24), CUTOFF)
    assert found is not None
    assert (found.team_id, found.source_url) == ("T28", "https://example.test/release")
    # not yet public at an earlier cutoff: it does not exist for that issue
    assert designated_for(rows, 2026, date(2026, 11, 24), datetime(2026, 11, 25, 1, 0, tzinfo=UTC)) is None
    assert designated_for(rows, 2026, date(2026, 11, 17), CUTOFF) is None
    for bad, why in (
        (ROW.replace("https://example.test/release", ""), "source"),
        (ROW.replace("2026-11-25T01:10:00+00:00", ""), "first_public_utc"),
        (ROW.replace("2026-11-25T01:10:00+00:00", "2026-11-25T01:10:00"), "first_public_utc"),
        (ROW + ROW, "twice"),
    ):
        with pytest.raises(DesignationError, match=why):
            load_designations(write(tmp_path, bad))


def test_designated_team_starts_26th() -> None:
    ap = pl.DataFrame(
        {
            "week": [13] * 3,
            "team_id": ["T26", "T27", "T29"],
            "rank": [None, None, None],
            "points": [90, 40, 5],
        },
        schema_overrides={"rank": pl.Int64},
    )
    prior = TEAMS[:25]
    plain = initial_order(TEAMS, prior, ap, None, DRAW)
    assert plain[25:28] == ["T26", "T27", "T29"]
    placed = initial_order(TEAMS, prior, ap, None, DRAW, designated="T28")
    assert placed[:25] == prior
    assert placed[25:29] == ["T28", "T26", "T27", "T29"]
    assert sorted(placed) == sorted(TEAMS)
    with pytest.raises(ValueError, match="already in the committee's 25"):
        initial_order(TEAMS, prior, ap, None, DRAW, designated="T03")
    with pytest.raises(ValueError, match="not in the field"):
        initial_order(TEAMS, prior, ap, None, DRAW, designated="ZZ")
    with pytest.raises(ValueError, match="needs a committee release"):
        initial_order(TEAMS, None, ap, None, DRAW, designated="T28")


def test_needs_designation() -> None:
    group = ("sun-belt", "mac")
    conference = {"A": "sec", "B": "sun-belt", "C": "mac"}
    assert needs_designation(["A"], conference, group)
    assert not needs_designation(["A", "B"], conference, group)
    assert not needs_designation(["A"], conference, ())  # a season with no group place


def test_issue_places_and_records_the_designated_team(tmp_path: Path) -> None:
    lake = world(tmp_path)
    rows = load_designations(write(tmp_path, ROW))
    built = issue(lake, designations=rows)
    second = built.doc["forecasts"]["baseline2"]
    by_team = {row["team_id"]: row for row in second["rows"]}
    assert by_team["T28"]["initial"] == 26
    assert second["anchor"]["designated_team"] == "T28"
    assert second["anchor"]["designated_source"] == "https://example.test/release"
    assert f"designations:{rows.sha256}" in built.doc["inputs"]
    bare = issue(lake)
    assert bare.doc["forecasts"]["baseline2"]["anchor"]["designated_team"] is None
    # published after this issue's cutoff: unseen
    late = ROW.replace("2026-11-25T01:10:00+00:00", (CUTOFF + timedelta(minutes=1)).isoformat())
    unseen = issue(lake, designations=load_designations(write(tmp_path, late)))
    assert unseen.doc["forecasts"]["baseline2"]["anchor"]["designated_team"] is None
    assert PRIOR < CUTOFF
