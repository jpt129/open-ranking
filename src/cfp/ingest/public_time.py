"""Rule-based first-public times for records whose source gives none (DS-03; docs/DECISIONS.md 2026-11-25).

Every estimate errs late: a replay may learn something a little after the public did, never before.
"""

from __future__ import annotations

from collections.abc import Mapping
from datetime import UTC, date, datetime, time, timedelta
from zoneinfo import ZoneInfo

from cfp.common.timeutil import require_utc

ET = ZoneInfo("America/New_York")
FINAL_LAG = timedelta(hours=4, minutes=30)  # kickoff to a final score, with no recorded end time
POLL_HOUR_ET = time(17, 0)
TUESDAY = 1
UNSETTLED_SCHEDULE_SEASONS = frozenset({2020})


def game_final_public(start: datetime) -> datetime:
    """When a result with no recorded end time is treated as public: kickoff + 4.5 hours."""
    return require_utc(start, "start") + FINAL_LAG


def schedule_public(season: int, start: datetime, season_type: str, title_game: bool) -> datetime:
    """When a reconstructed scheduled game is treated as known.

    Regular-season schedules are public months ahead, so 1 Aug 04:00 UTC errs late. Title-game and postseason
    pairings, and every 2020 date, were not known in advance: those are public at kickoff.
    """
    kickoff = require_utc(start, "start")
    if season_type != "regular" or title_game or season in UNSETTLED_SCHEDULE_SEASONS:
        return kickoff
    return min(kickoff, datetime(season, 8, 1, 4, 0, tzinfo=UTC))


def tuesday_after(moment: datetime) -> datetime:
    """The first Tuesday 17:00 ET at or after `moment`."""
    local = require_utc(moment, "moment").astimezone(ET)
    day: date = local.date()
    while True:
        candidate = datetime.combine(day, POLL_HOUR_ET, tzinfo=ET)
        if day.weekday() == TUESDAY and candidate >= local:
            return candidate.astimezone(UTC)
        day += timedelta(days=1)


def poll_public(
    week: int, last_kickoff_by_week: Mapping[int, datetime], season_first_kickoff: datetime
) -> datetime:
    """When a weekly poll is treated as public.

    The poll labelled week N ranks teams after week N-1's games. It normally appears Sunday afternoon and
    slips to Tuesday after Labor Day, so: the first Tuesday 17:00 ET after week N-1's last result. The
    preseason poll (no earlier games) is public at the season's first kickoff.
    """
    earlier = [kick for wk, kick in last_kickoff_by_week.items() if wk < week]
    if not earlier:
        return require_utc(season_first_kickoff, "season_first_kickoff")
    return tuesday_after(game_final_public(max(earlier)))


def clamp(estimate: datetime, captured_at: datetime) -> datetime:
    """A record cannot become public after we captured it."""
    return min(require_utc(estimate, "estimate"), require_utc(captured_at, "captured_at"))
