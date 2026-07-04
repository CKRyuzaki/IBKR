"""Small timezone helpers. Each G10 currency's instruments trade on their own local exchange
calendar/hours; the storage layer always keeps timestamps in UTC and lets the dashboard layer
localize for display."""

from __future__ import annotations

from datetime import date, datetime, timezone


def as_utc_datetime(value: datetime | date) -> datetime:
    """Normalize a datetime or bare date (as returned by ib_async historical bars) to UTC."""
    if isinstance(value, datetime):
        return value if value.tzinfo else value.replace(tzinfo=timezone.utc)
    return datetime(value.year, value.month, value.day, tzinfo=timezone.utc)
