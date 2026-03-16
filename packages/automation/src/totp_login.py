"""Daily automated broker login using pyotp TOTP codes.

Reads BROKER_TOTP_SECRET from .env, generates a time-based one-time password,
calls the OpenAlgo login endpoint, and verifies the session via /api/v1/ping.

Designed to run via cron at 8:30 AM IST. Skips weekends and NSE holidays
using jugaad-data. Logs success/failure to audit.
"""

from __future__ import annotations

import logging
import os
import time
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta, timezone
from typing import Any

import httpx

logger = logging.getLogger("flinttrade.automation.totp_login")

IST = timezone(timedelta(hours=5, minutes=30))


@dataclass
class LoginResult:
    """Result of a TOTP login attempt."""

    success: bool = False
    totp_generated: bool = False
    session_verified: bool = False
    attempt_count: int = 0
    error: str = ""
    timestamp: str = ""


def generate_totp(secret: str) -> str:
    """Generate a TOTP code from a base32 secret."""
    try:
        import pyotp
    except ImportError:
        raise ImportError("pyotp required — pip install pyotp")

    if not secret:
        raise ValueError("BROKER_TOTP_SECRET is empty")

    totp = pyotp.TOTP(secret)
    return totp.now()


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
    """Automated daily broker login via TOTP.

    Usage::

        login = TOTPLogin()
        result = login.execute()
        if result.success:
            print("Logged in successfully")
    """

    def __init__(
        self,
        openalgo_host: str | None = None,
        totp_secret: str | None = None,
        max_retries: int = 3,
        retry_delay: float = 30.0,
    ) -> None:
        self._host = (openalgo_host or os.getenv("OPENALGO_HOST", "http://127.0.0.1:5000")).rstrip("/")
        self._totp_secret = totp_secret or os.getenv("BROKER_TOTP_SECRET", "")
        self._api_key = os.getenv("OPENALGO_API_KEY", "")
        self._max_retries = max_retries
        self._retry_delay = retry_delay
        self._http = httpx.Client(timeout=30.0)

    def close(self) -> None:
        self._http.close()

    def __enter__(self) -> TOTPLogin:
        return self

    def __exit__(self, *args: Any) -> None:
        self.close()

    def execute(self, skip_holiday_check: bool = False) -> LoginResult:
        """Run the full TOTP login flow.

        1. Check if today is a trading day (skip weekends/holidays)
        2. Generate TOTP code
        3. Submit login to OpenAlgo
        4. Verify session via /api/v1/ping
        """
        now = datetime.now(IST)
        result = LoginResult(timestamp=now.isoformat())

        # Skip weekends and holidays
        if not skip_holiday_check and not is_trading_day(now.date()):
            logger.info("Not a trading day — skipping TOTP login")
            result.error = "Not a trading day"
            return result

        if not self._totp_secret:
            result.error = "BROKER_TOTP_SECRET not configured"
            logger.error(result.error)
            return result

        # Generate TOTP
        try:
            code = generate_totp(self._totp_secret)
            result.totp_generated = True
            logger.info("TOTP code generated")
        except Exception as exc:
            result.error = f"TOTP generation failed: {exc}"
            logger.error(result.error)
            return result

        # Attempt login with retries
        for attempt in range(1, self._max_retries + 1):
            result.attempt_count = attempt
            logger.info("Login attempt %d/%d", attempt, self._max_retries)

            try:
                login_ok = self._submit_login(code)
                if login_ok:
                    # Verify session
                    if self._verify_session():
                        result.success = True
                        result.session_verified = True
                        logger.info("TOTP login successful on attempt %d", attempt)
                        return result
                    else:
                        result.error = "Session verification failed after login"
                        logger.warning(result.error)
                else:
                    result.error = "Login submission failed"
                    logger.warning("Login attempt %d failed", attempt)
            except Exception as exc:
                result.error = str(exc)
                logger.error("Login attempt %d error: %s", attempt, exc)

            if attempt < self._max_retries:
                logger.info("Retrying in %.0f seconds", self._retry_delay)
                time.sleep(self._retry_delay)

        logger.error("TOTP login failed after %d attempts", self._max_retries)
        return result

    def _submit_login(self, totp_code: str) -> bool:
        """Submit TOTP code to OpenAlgo login endpoint."""
        url = f"{self._host}/api/v1/login"
        payload = {
            "apikey": self._api_key,
            "totp": totp_code,
        }
        try:
            resp = self._http.post(url, json=payload)
            if resp.status_code == 200:
                data = resp.json()
                return data.get("status") != "error"
            logger.warning("Login HTTP %d: %s", resp.status_code, resp.text[:200])
            return False
        except Exception as exc:
            logger.error("Login request failed: %s", exc)
            return False

    def _verify_session(self) -> bool:
        """Verify session is active via /api/v1/ping."""
        url = f"{self._host}/api/v1/ping"
        payload = {"apikey": self._api_key}
        try:
            resp = self._http.post(url, json=payload)
            if resp.status_code == 200:
                data = resp.json()
                return data.get("status") != "error"
            return False
        except Exception:
            return False
