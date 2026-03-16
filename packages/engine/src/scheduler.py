"""Time scheduler — market hours, auto square-off, deploy freeze, holidays.

All times are in IST (Asia/Kolkata, UTC+5:30).
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta, timezone
from typing import Any

from packages.core.src.openalgo_client import OpenAlgoClient

logger = logging.getLogger("flinttrade.engine.scheduler")

# IST is UTC+5:30
IST = timezone(timedelta(hours=5, minutes=30))


# ---------------------------------------------------------------------------
# Exchange schedule definitions
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class ExchangeSchedule:
    """Trading hours and auto square-off for an exchange segment."""

    exchange: str
    market_open: time   # IST
    market_close: time  # IST
    square_off: time    # IST — auto square-off for MIS positions
    is_24x7: bool = False


# From CLAUDE.md + engine CLAUDE.md
EXCHANGE_SCHEDULES: dict[str, ExchangeSchedule] = {
    "NSE": ExchangeSchedule("NSE", time(9, 15), time(15, 30), time(15, 15)),
    "BSE": ExchangeSchedule("BSE", time(9, 15), time(15, 30), time(15, 15)),
    "NFO": ExchangeSchedule("NFO", time(9, 15), time(15, 30), time(15, 15)),
    "BFO": ExchangeSchedule("BFO", time(9, 15), time(15, 30), time(15, 15)),
    "CDS": ExchangeSchedule("CDS", time(9, 0), time(17, 0), time(16, 45)),
    "BCD": ExchangeSchedule("BCD", time(9, 0), time(17, 0), time(16, 45)),
    "MCX": ExchangeSchedule("MCX", time(9, 0), time(23, 55), time(23, 30)),
    "NCDEX": ExchangeSchedule("NCDEX", time(10, 0), time(17, 0), time(16, 45)),
    "DELTA": ExchangeSchedule("DELTA", time(0, 0), time(23, 59), time(23, 59), is_24x7=True),
    "NSE_INDEX": ExchangeSchedule("NSE_INDEX", time(9, 15), time(15, 30), time(15, 30)),
    "BSE_INDEX": ExchangeSchedule("BSE_INDEX", time(9, 15), time(15, 30), time(15, 30)),
}


# Deploy freeze windows per market segment (from CLAUDE.md)
_DEPLOY_FREEZE_WINDOWS: dict[str, tuple[time, time]] = {
    "equity":   (time(9, 15), time(15, 30)),
    "currency": (time(9, 0),  time(17, 0)),
    "mcx":      (time(9, 0),  time(23, 55)),
    "crypto":   (time(0, 0),  time(23, 59)),  # 24/7 — always frozen, needs position check
}

# Map exchanges to deploy freeze segments
_EXCHANGE_TO_SEGMENT: dict[str, str] = {
    "NSE": "equity", "BSE": "equity", "NFO": "equity", "BFO": "equity",
    "NSE_INDEX": "equity", "BSE_INDEX": "equity",
    "CDS": "currency", "BCD": "currency",
    "MCX": "mcx", "NCDEX": "mcx",
    "DELTA": "crypto",
}


class TimeScheduler:
    """Knows market hours, deploy freezes, holidays, and square-off times.

    Usage::

        sched = TimeScheduler()
        if sched.is_market_open("NSE"):
            ...
        if sched.is_deploy_frozen(["NSE", "NFO"]):
            ...
    """

    def __init__(self, client: OpenAlgoClient | None = None) -> None:
        self._client = client
        self._holidays: dict[str, list[str]] = {}  # year -> list of "YYYY-MM-DD"

    def now_ist(self) -> datetime:
        """Current datetime in IST."""
        return datetime.now(IST)

    # ------------------------------------------------------------------
    # Market hours
    # ------------------------------------------------------------------

    def get_schedule(self, exchange: str) -> ExchangeSchedule | None:
        return EXCHANGE_SCHEDULES.get(exchange)

    def is_market_open(self, exchange: str, at: datetime | None = None) -> bool:
        """Check if the given exchange is currently in trading hours.

        Does NOT account for holidays — use is_trading_day() separately.
        """
        sched = EXCHANGE_SCHEDULES.get(exchange)
        if sched is None:
            return False

        if sched.is_24x7:
            return True

        now = (at or self.now_ist()).timetz()
        return sched.market_open <= now <= sched.market_close

    def is_trading_day(self, exchange: str, on: date | None = None) -> bool:
        """Check if the given date is a trading day (not weekend, not holiday)."""
        d = on or self.now_ist().date()

        # Weekends — crypto trades 24/7
        sched = EXCHANGE_SCHEDULES.get(exchange)
        if sched and sched.is_24x7:
            return True

        if d.weekday() >= 5:  # Saturday=5, Sunday=6
            return False

        # Check cached holidays
        year_key = str(d.year)
        if year_key in self._holidays:
            return d.isoformat() not in self._holidays[year_key]

        return True  # Assume trading day if holidays not loaded

    def time_to_square_off(self, exchange: str, at: datetime | None = None) -> timedelta | None:
        """Time remaining until auto square-off. None if market closed or 24/7."""
        sched = EXCHANGE_SCHEDULES.get(exchange)
        if sched is None or sched.is_24x7:
            return None

        now = at or self.now_ist()
        now_t = now.timetz()
        if not (sched.market_open <= now_t <= sched.market_close):
            return None

        sq_dt = now.replace(
            hour=sched.square_off.hour,
            minute=sched.square_off.minute,
            second=0, microsecond=0,
        )
        remaining = sq_dt - now.replace(tzinfo=None if sq_dt.tzinfo is None else IST)
        if hasattr(remaining, "total_seconds") and remaining.total_seconds() < 0:
            return timedelta(0)
        return remaining

    def should_square_off(self, exchange: str, at: datetime | None = None) -> bool:
        """True if current time is at or past the square-off time."""
        sched = EXCHANGE_SCHEDULES.get(exchange)
        if sched is None or sched.is_24x7:
            return False

        now_t = (at or self.now_ist()).timetz()
        return now_t >= sched.square_off

    # ------------------------------------------------------------------
    # Deploy freeze
    # ------------------------------------------------------------------

    def is_deploy_frozen(self, exchanges: list[str] | None = None, at: datetime | None = None) -> bool:
        """Check if ANY of the given exchanges is in a deploy freeze window.

        If no exchanges given, checks equity window (default from CLAUDE.md).
        """
        now_t = (at or self.now_ist()).timetz()
        target_exchanges = exchanges or ["NSE"]

        for exch in target_exchanges:
            segment = _EXCHANGE_TO_SEGMENT.get(exch, "equity")
            window = _DEPLOY_FREEZE_WINDOWS.get(segment)
            if window is None:
                continue

            if segment == "crypto":
                # Crypto is always frozen — deploy needs position check
                return True

            start, end = window
            if start <= now_t <= end:
                return True

        return False

    # ------------------------------------------------------------------
    # Holidays
    # ------------------------------------------------------------------

    def load_holidays(self, year: str | None = None) -> list[str]:
        """Fetch holidays from OpenAlgo and cache them.

        Returns list of date strings like ["2026-01-26", "2026-03-14", ...].
        """
        y = year or str(self.now_ist().year)

        if self._client is None:
            logger.warning("No OpenAlgo client — cannot fetch holidays")
            return []

        try:
            data = self._client.holidays(year=y)
            holidays = data.get("holidays", []) if isinstance(data, dict) else []
            if isinstance(holidays, list):
                self._holidays[y] = holidays
                logger.info("Loaded %d holidays for %s", len(holidays), y)
                return holidays
        except Exception as exc:
            logger.error("Failed to load holidays for %s: %s", y, exc)

        return []

    def get_holidays(self, year: str | None = None) -> list[str]:
        """Return cached holidays, loading if necessary."""
        y = year or str(self.now_ist().year)
        if y not in self._holidays:
            self.load_holidays(y)
        return self._holidays.get(y, [])
