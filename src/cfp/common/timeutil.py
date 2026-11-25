"""UTC time handling. Every stored instant is timezone-aware UTC."""

from __future__ import annotations

from datetime import UTC, datetime


def require_utc(value: datetime, name: str = "time") -> datetime:
    """Return `value` converted to UTC; refuse naive datetimes and non-datetimes."""
    if not isinstance(value, datetime):
        raise ValueError(f"{name} must be a datetime with a timezone; got {type(value).__name__}")
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{name} must carry a timezone; got naive datetime {value!r}")
    return value.astimezone(UTC)


def utc_now() -> datetime:
    return datetime.now(UTC)
