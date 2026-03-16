"""
TOTP auto-login is intentionally NOT implemented in FlintTrade.

OpenAlgo handles broker authentication. FlintTrade connects via API key.
If the OpenAlgo session expires, the dashboard shows a notification to
re-authenticate at the OpenAlgo web interface.

Reasons:
- Every broker has a different login flow (OAuth, TOTP, PIN, SMS OTP)
- Broker UI changes break scrapers without warning
- Some brokers actively block automated logins
- OpenAlgo already handles this — no need to duplicate
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

    Broker authentication is handled by OpenAlgo. This class exists
    for backward compatibility with cron_manager references.
    """

    def __init__(self, **kwargs) -> None:
        pass

    def execute(self, **kwargs) -> LoginResult:
        return LoginResult(
            success=False,
            error="TOTP auto-login removed — authenticate via OpenAlgo web UI",
            timestamp=datetime.now(IST).isoformat(),
        )
