"""Unit tests for daily broker re-authentication status."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from flinttrade_ditto.reauth import (
    IST,
    compute_reauth_status,
    last_reset_at_or_before,
    next_reset_after,
)

pytestmark = pytest.mark.unit


def _ist(y, mo, d, h, mi=0) -> datetime:
    return datetime(y, mo, d, h, mi, tzinfo=IST)


def test_no_prior_auth_needs_reauth():
    now = _ist(2026, 6, 5, 10, 0)
    status = compute_reauth_status(now, None)
    assert status.needs_reauth is True
    assert status.valid_today is False
    assert status.last_auth is None


def test_auth_after_todays_reset_is_valid():
    now = _ist(2026, 6, 5, 10, 0)  # 10:00 IST, after the 08:00 reset
    last_auth = _ist(2026, 6, 5, 8, 30)  # authed at 08:30 IST today
    status = compute_reauth_status(now, last_auth)
    assert status.valid_today is True
    assert status.needs_reauth is False


def test_auth_before_todays_reset_needs_reauth():
    now = _ist(2026, 6, 5, 10, 0)
    last_auth = _ist(2026, 6, 4, 21, 0)  # authed yesterday evening
    status = compute_reauth_status(now, last_auth)
    assert status.needs_reauth is True
    assert status.valid_today is False


def test_before_mornings_reset_yesterdays_auth_still_valid():
    # 07:30 IST — before today's 08:00 reset, so yesterday's session still counts.
    now = _ist(2026, 6, 5, 7, 30)
    last_auth = _ist(2026, 6, 4, 9, 0)
    status = compute_reauth_status(now, last_auth)
    assert status.valid_today is True


def test_reset_boundaries():
    now = _ist(2026, 6, 5, 10, 0)
    boundary = last_reset_at_or_before(now).astimezone(IST)
    assert boundary.hour == 8 and boundary.day == 5
    nxt = next_reset_after(now).astimezone(IST)
    assert nxt.hour == 8 and nxt.day == 6


def test_accepts_utc_input():
    # 04:30 UTC == 10:00 IST.
    now = datetime(2026, 6, 5, 4, 30, tzinfo=timezone.utc)
    last_auth = now - timedelta(hours=1)  # 09:00 IST today, after reset
    assert compute_reauth_status(now, last_auth).valid_today is True
