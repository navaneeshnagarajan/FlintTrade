"""Earnings calendar for NIFTY 50 companies.

Provides upcoming, date-specific, and per-symbol earnings event data.
Sample data generation covers a configurable window of months using the
standard Indian quarterly reporting schedule (Jan / Apr / Jul / Oct).

Endpoints (registered via earnings_routes.py):
    GET /ft-api/v1/earnings/calendar?days=30
    GET /ft-api/v1/earnings/by-date?date=2026-04-15
    GET /ft-api/v1/earnings/by-symbol?symbol=RELIANCE

Usage::

    from .earnings_calendar import EarningsCalendar

    cal = EarningsCalendar()
    upcoming = cal.get_upcoming(days=30)
    on_date  = cal.get_by_date(date(2026, 4, 15))
    history  = cal.get_by_symbol("RELIANCE")
"""

from __future__ import annotations

import logging
import random
from datetime import date, timedelta
from typing import Any

from pydantic import BaseModel, Field

logger = logging.getLogger("flinttrade.screener.earnings_calendar")

# ---------------------------------------------------------------------------
# NIFTY 50 universe (symbol → company name)
# ---------------------------------------------------------------------------

_NIFTY50: dict[str, str] = {
    "RELIANCE": "Reliance Industries Ltd",
    "TCS": "Tata Consultancy Services Ltd",
    "HDFCBANK": "HDFC Bank Ltd",
    "INFY": "Infosys Ltd",
    "ICICIBANK": "ICICI Bank Ltd",
    "HINDUNILVR": "Hindustan Unilever Ltd",
    "ITC": "ITC Ltd",
    "SBIN": "State Bank of India",
    "BHARTIARTL": "Bharti Airtel Ltd",
    "KOTAKBANK": "Kotak Mahindra Bank Ltd",
    "LT": "Larsen & Toubro Ltd",
    "HCLTECH": "HCL Technologies Ltd",
    "ASIANPAINT": "Asian Paints Ltd",
    "AXISBANK": "Axis Bank Ltd",
    "BAJFINANCE": "Bajaj Finance Ltd",
    "MARUTI": "Maruti Suzuki India Ltd",
    "WIPRO": "Wipro Ltd",
    "ULTRACEMCO": "UltraTech Cement Ltd",
    "TITAN": "Titan Company Ltd",
    "SUNPHARMA": "Sun Pharmaceutical Industries Ltd",
    "ONGC": "Oil and Natural Gas Corporation Ltd",
    "NTPC": "NTPC Ltd",
    "POWERGRID": "Power Grid Corporation of India Ltd",
    "NESTLEIND": "Nestle India Ltd",
    "TECHM": "Tech Mahindra Ltd",
    "BAJAJFINSV": "Bajaj Finserv Ltd",
    "CIPLA": "Cipla Ltd",
    "DRREDDY": "Dr. Reddy's Laboratories Ltd",
    "EICHERMOT": "Eicher Motors Ltd",
    "GRASIM": "Grasim Industries Ltd",
    "HEROMOTOCO": "Hero MotoCorp Ltd",
    "HINDALCO": "Hindalco Industries Ltd",
    "INDUSINDBK": "IndusInd Bank Ltd",
    "JSWSTEEL": "JSW Steel Ltd",
    "MM": "Mahindra & Mahindra Ltd",
    "BRITANNIA": "Britannia Industries Ltd",
    "COALINDIA": "Coal India Ltd",
    "DIVISLAB": "Divi's Laboratories Ltd",
    "HDFCLIFE": "HDFC Life Insurance Company Ltd",
    "SBILIFE": "SBI Life Insurance Company Ltd",
    "SHREECEM": "Shree Cement Ltd",
    "TATACONSUM": "Tata Consumer Products Ltd",
    "TATAMOTORS": "Tata Motors Ltd",
    "TATASTEEL": "Tata Steel Ltd",
    "APOLLOHOSP": "Apollo Hospitals Enterprise Ltd",
    "BPCL": "Bharat Petroleum Corporation Ltd",
    "BAJAJ-AUTO": "Bajaj Auto Ltd",
    "ADANIPORTS": "Adani Ports and Special Economic Zone Ltd",
    "ADANIENT": "Adani Enterprises Ltd",
    "UPL": "UPL Ltd",
}

# Quarter start months: Indian FY (Apr–Mar) uses Apr/Jul/Oct/Jan.
# Q1 FY: Apr–Jun → results in Jul
# Q2 FY: Jul–Sep → results in Oct
# Q3 FY: Oct–Dec → results in Jan
# Q4 FY: Jan–Mar → results in Apr/May
_RESULT_MONTHS: list[int] = [1, 4, 7, 10]  # Jan, Apr, Jul, Oct

_QUARTER_LABELS: dict[int, str] = {
    1: "Q3",   # Jan window → Q3 (Oct–Dec quarter)
    4: "Q4",   # Apr window → Q4 (Jan–Mar quarter)
    7: "Q1",   # Jul window → Q1 (Apr–Jun quarter)
    10: "Q2",  # Oct window → Q2 (Jul–Sep quarter)
}


def _shift_to_month_start(anchor: date, offset_months: int) -> date:
    """Return the first day of the month offset from ``anchor``."""
    month_index = (anchor.year * 12) + (anchor.month - 1) + offset_months
    year, zero_based_month = divmod(month_index, 12)
    return date(year, zero_based_month + 1, 1)


def _month_end(anchor: date) -> date:
    """Return the final day of ``anchor``'s calendar month."""
    return _shift_to_month_start(anchor, 1) - timedelta(days=1)


def _result_label(month: int, quarter: str, year: int) -> str:
    """Return the Financial Year string for a given calendar year and quarter.

    Args:
        month: Calendar month of the result announcement.
        quarter: Quarter label (Q1–Q4).
        year: Calendar year of the result announcement.

    Returns:
        FY string such as ``"FY2026"``.
    """
    # Q1/Q2 results are announced in Jul/Oct of the same FY year.
    # Q3/Q4 results are announced in Jan/Apr; Jan belongs to the same FY,
    # Apr to the next.
    if month in (7, 10):
        # Apr–Mar FY: Jul/Oct announcements belong to the FY ending Mar of year+1
        fy_end = year + 1
    elif month == 1:
        # Jan announcement: belongs to FY ending Mar of the same year
        fy_end = year
    else:  # month == 4
        # Apr announcement: Q4 of the FY that ended the previous month (Mar)
        fy_end = year
    return f"FY{fy_end}"


# ---------------------------------------------------------------------------
# Pydantic model
# ---------------------------------------------------------------------------


class EarningsEvent(BaseModel):
    """A single earnings result announcement event.

    Attributes:
        symbol: NSE ticker symbol (e.g. ``"RELIANCE"``).
        company_name: Full company name.
        date: Scheduled announcement date.
        quarter: Quarter label (``"Q1"``–``"Q4"``).
        financial_year: FY string (e.g. ``"FY2026"``).
        estimated_eps: Analyst consensus EPS estimate; ``None`` if unavailable.
        actual_eps: Reported EPS; ``None`` for upcoming events.
        surprise_pct: Percentage deviation of actual vs estimated;
            positive = beat, negative = miss. ``None`` when actual is unknown.
        result: Qualitative outcome — ``"beat"``, ``"miss"``, or ``"meet"``.
            ``None`` for upcoming events.
    """

    symbol: str
    company_name: str
    date: date
    quarter: str
    financial_year: str
    estimated_eps: float | None = None
    actual_eps: float | None = None
    surprise_pct: float | None = None
    result: str | None = Field(default=None, pattern=r"^(beat|miss|meet)$")

    def to_dict(self) -> dict[str, Any]:
        """Serialise to a JSON-compatible dictionary.

        Returns:
            Dict with ``date`` converted to ISO-format string.
        """
        d = self.model_dump()
        d["date"] = self.date.isoformat()
        return d


# ---------------------------------------------------------------------------
# Calendar engine
# ---------------------------------------------------------------------------


class EarningsCalendar:
    """In-memory earnings calendar with DuckDB-ready design.

    Events are stored in a dict keyed by ISO date string for O(1) date lookups.
    The internal cache is populated either from a live data source (future) or
    from :meth:`generate_sample_data` for explore / dev mode.

    Attributes:
        _cache: Mapping of ``ISO date string`` → list of :class:`EarningsEvent`.
    """

    def __init__(self) -> None:
        self._cache: dict[str, list[EarningsEvent]] = {}

    # ------------------------------------------------------------------
    # Public query methods
    # ------------------------------------------------------------------

    def get_upcoming(self, days: int = 30) -> list[EarningsEvent]:
        """Return earnings events scheduled within the next N calendar days.

        Args:
            days: Look-ahead window in calendar days (clamped to 1–365).

        Returns:
            Events sorted ascending by date, then alphabetically by symbol.
        """
        days = max(1, min(365, days))
        today = date.today()
        cutoff = today + timedelta(days=days)
        events: list[EarningsEvent] = []
        for iso_date, day_events in self._cache.items():
            event_date = date.fromisoformat(iso_date)
            if today <= event_date <= cutoff:
                events.extend(day_events)
        return sorted(events, key=lambda e: (e.date, e.symbol))

    def get_by_date(self, target_date: date) -> list[EarningsEvent]:
        """Return all earnings events scheduled on a specific date.

        Args:
            target_date: The exact calendar date to query.

        Returns:
            List of events on that date, sorted alphabetically by symbol.
            Returns an empty list if no events are scheduled.
        """
        events = self._cache.get(target_date.isoformat(), [])
        return sorted(events, key=lambda e: e.symbol)

    def get_by_symbol(self, symbol: str) -> list[EarningsEvent]:
        """Return the complete earnings history for a single symbol.

        Args:
            symbol: NSE ticker symbol (case-insensitive).

        Returns:
            All cached events for the symbol, sorted by date ascending.
        """
        upper = symbol.upper()
        matching: list[EarningsEvent] = [
            event
            for day_events in self._cache.values()
            for event in day_events
            if event.symbol == upper
        ]
        return sorted(matching, key=lambda e: e.date)

    # ------------------------------------------------------------------
    # Sample data generation
    # ------------------------------------------------------------------

    def generate_sample_data(self, months: int = 3) -> list[EarningsEvent]:
        """Generate realistic sample earnings data and populate the internal cache.

        Creates plausible events for all NIFTY 50 companies across the given
        number of months, centred around today.  Each company receives one
        announcement per result window that falls within the range.

        The date within each result window is staggered deterministically based
        on the symbol name so companies do not all report on the same day.

        Past events include simulated actual EPS and surprise figures; future
        events have only estimated EPS.

        Args:
            months: Total months to cover (half before today, half after).
                Clamped to 1–24.

        Returns:
            Flat list of all generated :class:`EarningsEvent` objects.
        """
        months = max(1, min(24, months))
        self._cache.clear()

        today = date.today()
        half = months // 2 or 1
        window_start = _shift_to_month_start(today, -half)
        window_end = _month_end(_shift_to_month_start(today, months - half))

        # Ensure the window always reaches back to the most recent result month
        # that is fully in the past, so there is recent completed earnings data
        # (with actuals) regardless of where in the quarter "today" falls — a
        # 3-month window centred mid-quarter could otherwise contain only future
        # results. Quarters (Jan/Apr/Jul/Oct) are 3 months apart, so one lies
        # within the last 4 months.
        for offset in range(1, 5):
            candidate = _shift_to_month_start(today, -offset)
            if candidate.month in _RESULT_MONTHS and _month_end(candidate) < today:
                window_start = min(window_start, candidate)
                break

        all_events: list[EarningsEvent] = []
        symbols = list(_NIFTY50.keys())

        # Walk through every possible result month in the window
        # Scan a generous year range so we don't miss window edges
        for year in range(window_start.year, window_end.year + 1):
            for result_month in _RESULT_MONTHS:
                # Build a base date (1st of result month)
                try:
                    base = date(year, result_month, 1)
                except ValueError:
                    continue

                # Skip entire month if it falls outside our window
                month_end = date(year, result_month, 28)
                if month_end < window_start or base > window_end:
                    continue

                quarter = _QUARTER_LABELS[result_month]
                fy = _result_label(result_month, quarter, year)

                for symbol in symbols:
                    # Stagger announcement days: 1–28 deterministically from symbol
                    rng = random.Random(hash(symbol + str(year) + str(result_month)))
                    day_offset = rng.randint(0, 27)
                    event_date = base + timedelta(days=day_offset)

                    if event_date < window_start or event_date > window_end:
                        continue

                    company = _NIFTY50[symbol]
                    est_eps = round(rng.uniform(5.0, 120.0), 2)

                    if event_date < today:
                        # Past event: generate actual EPS + surprise
                        surprise_pct = round(rng.uniform(-15.0, 20.0), 2)
                        actual_eps = round(est_eps * (1 + surprise_pct / 100), 2)
                        if surprise_pct > 2.0:
                            outcome = "beat"
                        elif surprise_pct < -2.0:
                            outcome = "miss"
                        else:
                            outcome = "meet"
                        event = EarningsEvent(
                            symbol=symbol,
                            company_name=company,
                            date=event_date,
                            quarter=quarter,
                            financial_year=fy,
                            estimated_eps=est_eps,
                            actual_eps=actual_eps,
                            surprise_pct=surprise_pct,
                            result=outcome,
                        )
                    else:
                        # Future / upcoming event: estimate only
                        event = EarningsEvent(
                            symbol=symbol,
                            company_name=company,
                            date=event_date,
                            quarter=quarter,
                            financial_year=fy,
                            estimated_eps=est_eps,
                        )

                    iso = event_date.isoformat()
                    self._cache.setdefault(iso, []).append(event)
                    all_events.append(event)

        logger.info(
            "EarningsCalendar: generated %d events across %d months",
            len(all_events),
            months,
        )
        return all_events

    # ------------------------------------------------------------------
    # Persistence helpers (for future DuckDB integration)
    # ------------------------------------------------------------------

    def load_from_list(self, events: list[EarningsEvent]) -> None:
        """Populate the cache from an externally supplied list of events.

        Replaces any existing cached data.

        Args:
            events: Iterable of :class:`EarningsEvent` instances.
        """
        self._cache.clear()
        for event in events:
            iso = event.date.isoformat()
            self._cache.setdefault(iso, []).append(event)
        logger.debug("EarningsCalendar: loaded %d events from list", len(events))

    def event_count(self) -> int:
        """Return total number of cached events across all dates.

        Returns:
            Integer count of all events in the cache.
        """
        return sum(len(v) for v in self._cache.values())
