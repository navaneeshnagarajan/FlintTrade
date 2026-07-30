"""Shared broker-session expiry helpers."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

_IST = ZoneInfo("Asia/Kolkata")


def next_6am_ist_timestamp(now: datetime | None = None) -> float:
    """Return the next 06:00 IST dashboard reset as a UTC epoch timestamp."""
    current = (now or datetime.now(tz=_IST)).astimezone(_IST)
    expiry = current.replace(hour=6, minute=0, second=0, microsecond=0)
    if expiry <= current:
        expiry += timedelta(days=1)
    return expiry.astimezone(timezone.utc).timestamp()
