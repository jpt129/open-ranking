"""First-public rules err late (DS-03, John's ruling 2026-11-25)."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest

from cfp.ingest.public_time import clamp, game_final_public, poll_public, tuesday_after, vintage_at
from cfp.ingest.upsert import upsert
from cfp.store.lake import Lake

from .store_helpers import Clock, frame, game

ET = ZoneInfo("America/New_York")


def et(*args: int) -> datetime:
    return datetime(*args, tzinfo=ET).astimezone(UTC)  # type: ignore[misc]


def test_final_is_public_four_and_a_half_hours_after_kickoff() -> None:
    assert game_final_public(et(2025, 11, 22, 22, 30)) == et(2025, 11, 23, 3, 0)


def test_late_saturday_kickoff_invisible_at_sunday_cutoff(tmp_path: Path) -> None:
    """A 22:30 ET Saturday kickoff is not in a replay at the 02:00 ET Sunday cutoff; a 21:30 one is."""
    cutoff = et(2025, 11, 23, 2, 0)
    lake = Lake(tmp_path, clock=Clock(et(2026, 11, 25, 12, 0)))
    rows = []
    for game_id, kickoff in (("late", et(2025, 11, 22, 22, 30)), ("early", et(2025, 11, 22, 21, 30))):
        row = game(lake, game_id, season=2025, start_utc=kickoff, vintage="reconstructed")
        row["event_time"] = kickoff
        row["first_public_time"] = game_final_public(kickoff)
        rows.append(row)
    lake.append("games", frame("games", rows))
    assert lake.as_of("games", cutoff, "replay").frame["game_id"].to_list() == ["early"]
    assert lake.as_of("games", cutoff, "scored").frame["game_id"].to_list() == ["early"]
    later = lake.as_of("games", cutoff + timedelta(hours=1), "replay").frame["game_id"].to_list()
    assert later == ["early", "late"]


def test_placeholder_kickoff_time_errs_late() -> None:
    """A kickoff flagged as a placeholder (midnight UTC) is not trusted: the clock starts at day's end ET."""
    placeholder = datetime(2025, 11, 22, 0, 0, tzinfo=UTC)  # 19:00 ET on the 21st
    assert game_final_public(placeholder, time_tbd=True) == et(2025, 11, 23, 4, 29)
    assert game_final_public(placeholder, time_tbd=True) > et(2025, 11, 23, 2, 0)  # past the Sunday cutoff
    assert game_final_public(placeholder) == placeholder + timedelta(hours=4, minutes=30)


def test_vintage_is_live_only_within_seven_days_of_public() -> None:
    public = et(2026, 11, 21, 20, 0)
    assert vintage_at(True, public, public + timedelta(days=7)) == "live"
    assert vintage_at(True, public, public + timedelta(days=7, seconds=1)) == "reconstructed"
    assert vintage_at(False, public, public + timedelta(hours=1)) == "reconstructed"
    assert vintage_at(True, public, public - timedelta(hours=2)) == "live"  # seen before the rule time


def test_tuesday_after() -> None:
    assert tuesday_after(et(2025, 11, 23, 3, 0)) == et(2025, 11, 25, 17, 0)  # Sunday morning -> Tuesday
    assert tuesday_after(et(2025, 9, 2, 0, 30)) == et(2025, 9, 2, 17, 0)  # early Tuesday -> same day
    assert tuesday_after(et(2025, 9, 2, 17, 1)) == et(2025, 9, 9, 17, 0)  # after 17:00 -> next week


def test_poll_rule() -> None:
    kicks = {1: et(2025, 9, 1, 20, 0), 2: et(2025, 9, 6, 22, 30)}  # week 1 ends on Labor Day night
    first = et(2025, 8, 23, 12, 0)
    assert poll_public(1, kicks, first) == first
    assert poll_public(2, kicks, first) == et(2025, 9, 2, 17, 0)
    assert poll_public(3, kicks, first) == et(2025, 9, 9, 17, 0)
    # the week-12 poll is not visible at the Sunday 02:00 ET issue that follows week 11's games ...
    week11 = {11: et(2025, 11, 8, 22, 30)}
    assert poll_public(12, week11, first) > et(2025, 11, 9, 2, 0)
    # ... and is visible at the Tuesday 18:00 ET issue
    assert poll_public(12, week11, first) <= et(2025, 11, 11, 18, 0)


def test_poll_rule_refuses_a_gap_in_the_games() -> None:
    """With week 12 missing, the week-13 poll would be dated from week 5: weeks too early."""
    partial = {1: et(2025, 8, 30, 12, 0), 5: et(2025, 9, 27, 20, 0)}
    with pytest.raises(ValueError, match="week 12"):
        poll_public(13, partial, et(2025, 8, 30, 12, 0))


def test_clamp() -> None:
    now = et(2026, 11, 25, 12, 0)
    assert clamp(now + timedelta(hours=1), now) == now
    assert clamp(now - timedelta(hours=1), now) == now - timedelta(hours=1)


def _capture(lake: Lake, **over: object) -> dict[str, object]:
    row = game(lake, "g1", **over)
    del row["correction_version"]
    return row


def _games(rows: list[dict[str, object]]):  # type: ignore[no-untyped-def]
    return frame("games", [{**r, "correction_version": 0} for r in rows]).drop("correction_version")


def test_upsert_versions_and_public_times(tmp_path: Path) -> None:
    kickoff = et(2026, 11, 28, 22, 30)
    clock = Clock(et(2026, 11, 28, 12, 0))
    lake = Lake(tmp_path, clock=clock)
    scheduled = _capture(lake, status="scheduled", home_pts=None, away_pts=None, start_utc=kickoff)
    scheduled["first_public_time"] = kickoff  # a rule that lands after the capture is clamped to it
    first = upsert(lake, "games", _games([scheduled]), clock.now, "observed")
    assert (first.new, first.corrected, first.unchanged) == (1, 0, 0)
    again = upsert(lake, "games", _games([scheduled]), clock.now, "observed")
    assert (again.new, again.corrected, again.unchanged) == (0, 0, 1)

    clock.now = et(2026, 11, 29, 1, 55)  # the ingest just before the 02:00 ET cutoff sees the final
    final = _capture(lake, status="final", start_utc=kickoff)
    final["first_public_time"] = game_final_public(kickoff)  # 03:00 ET by rule
    second = upsert(lake, "games", _games([final]), clock.now, "observed")
    assert (second.new, second.corrected, second.unchanged) == (0, 1, 0)

    stored = lake.scan("games").sort("correction_version").collect()
    assert stored["correction_version"].to_list() == [0, 1]
    assert stored["first_public_time"].to_list() == [et(2026, 11, 28, 12, 0), et(2026, 11, 29, 1, 55)]
    cutoff = et(2026, 11, 29, 2, 0)
    assert lake.as_of("games", cutoff, "live").frame["status"].to_list() == ["final"]
    assert lake.as_of("games", et(2026, 11, 29, 1, 0), "live").frame["status"].to_list() == ["scheduled"]


def test_upsert_backfill_keeps_asserted_times(tmp_path: Path) -> None:
    kickoff = et(2025, 11, 22, 22, 30)
    clock = Clock(et(2026, 11, 25, 12, 0))
    lake = Lake(tmp_path, clock=clock)
    final = _capture(lake, season=2025, status="final", start_utc=kickoff, vintage="reconstructed")
    final["first_public_time"] = game_final_public(kickoff)
    upsert(lake, "games", _games([final]), clock.now, "asserted")
    fixed = dict(final, home_pts=35)  # a later source correction in a backfill keeps its asserted time
    upsert(lake, "games", _games([fixed]), clock.now, "asserted")
    assert lake.as_of("games", et(2025, 11, 23, 2, 0), "replay").frame.height == 0
    assert lake.as_of("games", et(2025, 11, 23, 3, 0), "replay").frame["home_pts"].to_list() == [35]


def test_upsert_ignored_columns_do_not_make_a_correction(tmp_path: Path) -> None:
    clock = Clock(et(2026, 11, 25, 12, 0))
    lake = Lake(tmp_path, clock=clock)
    row = _capture(lake, site="Stadium A")
    upsert(lake, "games", _games([row]), clock.now, "observed", ignore=("site",))
    again = upsert(
        lake, "games", _games([dict(row, site="Stadium B")]), clock.now, "observed", ignore=("site",)
    )
    assert (again.corrected, again.unchanged) == (0, 1)
    changed = upsert(lake, "games", _games([dict(row, home_pts=3)]), clock.now, "observed", ignore=("site",))
    assert changed.corrected == 1


def test_upsert_refuses_a_key_listed_twice(tmp_path: Path) -> None:
    clock = Clock(et(2026, 11, 25, 12, 0))
    lake = Lake(tmp_path, clock=clock)
    row = _capture(lake)
    with pytest.raises(ValueError, match="twice"):
        upsert(lake, "games", _games([row, dict(row, home_pts=3)]), clock.now, "observed")
