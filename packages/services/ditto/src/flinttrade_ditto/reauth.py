"""Daily broker re-authentication status for the Account Manager.

Indian broker logins (and the OpenAlgo sessions in front of them) expire once a
day — the operator must re-authenticate each trading morning. Most brokers and
OpenAlgo invalidate the session around 08:00 IST. This module computes, from the
last successful authentication, whether a given account needs re-auth *today*, so
the Account Manager can show a per-broker "reauth required" indicator that drives
the operator to act.

Pure and clock-injectable — no network, fully unit-testable.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime, timedelta, timezone
from typing import Any

IST = timezone(timedelta(hours=5, minutes=30))

# Sessions are treated as stale once the day's 08:00 IST reset has passed.
DAILY_RESET_HOUR_IST = 8


@dataclass
class ReauthStatus:
    """Per-account daily re-authentication status."""

    needs_reauth: bool
    valid_today: bool
    last_auth: str | None
    next_reset: str  # ISO timestamp (UTC) of the next 08:00 IST reset

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _to_utc(dt: datetime) -> datetime:
    return dt.astimezone(timezone.utc) if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


def last_reset_at_or_before(now: datetime) -> datetime:
    """Return the most recent 08:00 IST reset boundary at or before ``now`` (UTC)."""
    now_ist = _to_utc(now).astimezone(IST)
    reset_ist = now_ist.replace(hour=DAILY_RESET_HOUR_IST, minute=0, second=0, microsecond=0)
    if now_ist < reset_ist:
        reset_ist -= timedelta(days=1)
    return reset_ist.astimezone(timezone.utc)


def next_reset_after(now: datetime) -> datetime:
    """Return the next 08:00 IST reset boundary strictly after ``now`` (UTC)."""
    return last_reset_at_or_before(now) + timedelta(days=1)


def compute_reauth_status(now: datetime, last_auth: datetime | None = None) -> ReauthStatus:
    """Compute whether an account needs re-authentication today.

    Args:
        now: Current time (UTC; naive is treated as UTC).
        last_auth: Time of the last successful authentication, or None if never.

    Returns:
        A :class:`ReauthStatus`. ``needs_reauth`` is True when there is no prior
        auth, or the last auth predates the most recent 08:00 IST reset.
    """
    boundary = last_reset_at_or_before(now)
    nxt = next_reset_after(now)
    if last_auth is None:
        return ReauthStatus(True, False, None, nxt.isoformat())
    last_utc = _to_utc(last_auth)
    valid = last_utc >= boundary
    return ReauthStatus(
        needs_reauth=not valid,
        valid_today=valid,
        last_auth=last_utc.isoformat(),
        next_reset=nxt.isoformat(),
    )
