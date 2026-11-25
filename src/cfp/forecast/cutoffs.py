"""Issue times (SC-02, SC-02a): Sunday 02:00 Eastern, and 60 minutes before the reveal. Stored in UTC."""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
from typing import Final
from zoneinfo import ZoneInfo

from cfp.common.timeutil import require_utc

ET: Final = ZoneInfo("America/New_York")
ISSUES: Final = ("sun0200", "tminus60")
SUNDAY: Final = 6


def sunday_0200(day: date) -> datetime:
    """02:00 Eastern on a Sunday. When the clocks go back that morning, the later reading is used."""
    if day.weekday() != SUNDAY:
        raise ValueError(f"{day} is not a Sunday")
    return datetime(day.year, day.month, day.day, 2, 0, tzinfo=ET, fold=1).astimezone(UTC)


def issue_time(issue: str, reveal: datetime) -> datetime:
    """The cutoff of an issue for the reveal at `reveal`.

    sun0200 is the last Sunday 02:00 Eastern before the reveal (the same morning when the reveal is on a
    Sunday); tminus60 is one hour before the reveal.
    """
    reveal = require_utc(reveal, "reveal")
    if issue == "tminus60":
        return reveal - timedelta(minutes=60)
    if issue != "sun0200":
        raise ValueError(f"issue must be one of {ISSUES}; got {issue!r}")
    day = reveal.astimezone(ET).date()
    for _ in range(8):
        if day.weekday() == SUNDAY and sunday_0200(day) < reveal:
            return sunday_0200(day)
        day -= timedelta(days=1)
    raise AssertionError("no Sunday in eight days")
