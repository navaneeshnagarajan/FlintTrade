"""Automatic broker login is unavailable.

Connect and renew native accounts through FlintTrade's broker connect flow.
Each adapter owns its supported OAuth, TOTP, PIN or OTP authentication methods.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone

logger = logging.getLogger("flinttrade.automation.totp_login")

IST = timezone(timedelta(hours=5, minutes=30))


@dataclass
class LoginResult:
    """Result of a login check (retained for API compatibility)."""

    success: bool = False
    error: str = ""
    timestamp: str = ""


def is_holiday(d: date) -> bool:
    """Check if a date is an NSE holiday using jugaad-data."""
    try:
        from jugaad_data.holidays import holidays as jd_holidays
        holiday_dates = jd_holidays(d.year)
        return d in holiday_dates
    except ImportError:
        logger.warning("jugaad-data not installed — cannot check holidays")
        return False
    except Exception as exc:
        logger.warning("Holiday check failed: %s", exc)
        return False


def is_trading_day(d: date | None = None) -> bool:
    """Check if today is a trading day (weekday + not NSE holiday)."""
    d = d or datetime.now(IST).date()
    if d.weekday() >= 5:
        return False
    return not is_holiday(d)


class TOTPLogin:
    """Stub — TOTP auto-login is not implemented.

    Native adapters own broker authentication. This class exists
    for backward compatibility with cron_manager references.
    """

    def __init__(self, **kwargs) -> None:
        pass

    def execute(self, **kwargs) -> LoginResult:
        return LoginResult(
            success=False,
            error="TOTP auto-login removed — renew the native account through FlintTrade broker connect",
            timestamp=datetime.now(IST).isoformat(),
        )
