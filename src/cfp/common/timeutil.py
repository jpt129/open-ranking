"""UTC time handling. Every stored instant is timezone-aware UTC."""

from __future__ import annotations

from datetime import UTC, datetime


def require_utc(value: datetime, name: str = "time") -> datetime:
    """Return `value` converted to UTC; refuse naive datetimes."""
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{name} must carry a timezone; got naive datetime {value!r}")
    return value.astimezone(UTC)
