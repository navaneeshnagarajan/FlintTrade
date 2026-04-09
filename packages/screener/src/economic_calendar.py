"""Economic calendar for India and global macro events.

Provides upcoming high/medium/low-impact economic releases with optional
country and impact filters.  Sample data covers a configurable rolling window
and includes all major Indian and global macro events that affect Indian
equity and F&O markets.

Endpoint (registered via economic_routes.py):
    GET /ft-api/v1/economic/calendar?days=14&country=IN,US&impact=high

Usage::

    from packages.screener.src.economic_calendar import EconomicCalendarProvider

    provider = EconomicCalendarProvider()
    provider.generate_sample_data(months=2)
    upcoming = provider.get_upcoming(days=14, countries=["IN", "US"], min_impact="high")
"""

from __future__ import annotations

import logging
from datetime import date, timedelta
from typing import Any

from pydantic import BaseModel, Field

logger = logging.getLogger("flinttrade.screener.economic_calendar")

# ---------------------------------------------------------------------------
# Impact ordering (used for "min_impact" filter)
# ---------------------------------------------------------------------------

_IMPACT_ORDER: dict[str, int] = {"low": 0, "medium": 1, "high": 2}

# ---------------------------------------------------------------------------
# Supported countries
# ---------------------------------------------------------------------------

_VALID_COUNTRIES: frozenset[str] = frozenset({"IN", "US", "EU", "JP", "CN", "GB"})

# ---------------------------------------------------------------------------
# Pydantic model
# ---------------------------------------------------------------------------


class EconomicEvent(BaseModel):
    """A single macro-economic event.

    Attributes:
        date: Scheduled release date.
        time: Release time in IST (e.g. ``"14:00"``).
        event: Human-readable event name.
        country: Two-letter country/region code (``"IN"``, ``"US"``, etc.).
        impact: Expected market impact — ``"high"``, ``"medium"``, or ``"low"``.
        previous: Prior reading as a formatted string (e.g. ``"6.50%"``).
        forecast: Analyst consensus forecast as a string.
        actual: Actual reported value; ``None`` for upcoming events.
        category: Event category — one of ``"interest_rate"``, ``"gdp"``,
            ``"cpi"``, ``"employment"``, ``"trade"``, ``"pmi"``,
            ``"industrial"``, or ``"other"``.
    """

    date: date
    time: str = Field(pattern=r"^\d{2}:\d{2}$")
    event: str
    country: str
    impact: str = Field(pattern=r"^(high|medium|low)$")
    previous: str | None = None
    forecast: str | None = None
    actual: str | None = None
    category: str = Field(
        pattern=r"^(interest_rate|gdp|cpi|employment|trade|pmi|industrial|other)$"
    )

    def to_dict(self) -> dict[str, Any]:
        """Serialise to a JSON-compatible dictionary.

        Returns:
            Dict with ``date`` as an ISO-format string.
        """
        d = self.model_dump()
        d["date"] = self.date.isoformat()
        return d


# ---------------------------------------------------------------------------
# Template definitions
# ---------------------------------------------------------------------------
# Each template is a dict with keys:
#   event, country, impact, time, category, cadence_days, base_day_of_month
#   (base_day_of_month is the approximate day of month the event occurs)

_EVENT_TEMPLATES: list[dict[str, Any]] = [
    # ---- India ----
    {
        "event": "RBI Monetary Policy Decision",
        "country": "IN",
        "impact": "high",
        "time": "10:00",
        "category": "interest_rate",
        "cadence_days": 60,       # bi-monthly (approx 8 times/year → ~60 day gap)
        "base_day_of_month": 8,   # typically released on the 8th of the month
    },
    {
        "event": "India CPI Inflation",
        "country": "IN",
        "impact": "high",
        "time": "17:30",
        "category": "cpi",
        "cadence_days": 30,
        "base_day_of_month": 12,
    },
    {
        "event": "India WPI Inflation",
        "country": "IN",
        "impact": "medium",
        "time": "12:00",
        "category": "cpi",
        "cadence_days": 30,
        "base_day_of_month": 14,
    },
    {
        "event": "India GDP Growth Rate",
        "country": "IN",
        "impact": "high",
        "time": "17:30",
        "category": "gdp",
        "cadence_days": 90,       # quarterly
        "base_day_of_month": 28,
    },
    {
        "event": "India Industrial Production (IIP)",
        "country": "IN",
        "impact": "medium",
        "time": "17:30",
        "category": "industrial",
        "cadence_days": 30,
        "base_day_of_month": 12,
    },
    {
        "event": "India Trade Balance",
        "country": "IN",
        "impact": "medium",
        "time": "15:30",
        "category": "trade",
        "cadence_days": 30,
        "base_day_of_month": 19,
    },
    {
        "event": "India Manufacturing PMI",
        "country": "IN",
        "impact": "medium",
        "time": "10:30",
        "category": "pmi",
        "cadence_days": 30,
        "base_day_of_month": 1,
    },
    {
        "event": "India Services PMI",
        "country": "IN",
        "impact": "medium",
        "time": "10:30",
        "category": "pmi",
        "cadence_days": 30,
        "base_day_of_month": 3,
    },
    # ---- United States ----
    {
        "event": "US Fed Rate Decision (FOMC)",
        "country": "US",
        "impact": "high",
        "time": "23:30",
        "category": "interest_rate",
        "cadence_days": 42,       # roughly 6-weekly (8 meetings/year)
        "base_day_of_month": 15,
    },
    {
        "event": "US Non-Farm Payrolls",
        "country": "US",
        "impact": "high",
        "time": "18:30",
        "category": "employment",
        "cadence_days": 30,
        "base_day_of_month": 5,
    },
    {
        "event": "US CPI",
        "country": "US",
        "impact": "high",
        "time": "18:30",
        "category": "cpi",
        "cadence_days": 30,
        "base_day_of_month": 12,
    },
    {
        "event": "US GDP Growth Rate",
        "country": "US",
        "impact": "high",
        "time": "18:30",
        "category": "gdp",
        "cadence_days": 90,
        "base_day_of_month": 26,
    },
    {
        "event": "US Initial Jobless Claims",
        "country": "US",
        "impact": "medium",
        "time": "18:30",
        "category": "employment",
        "cadence_days": 7,        # weekly
        "base_day_of_month": 0,   # no fixed day — every Thursday
    },
    {
        "event": "US ISM Manufacturing PMI",
        "country": "US",
        "impact": "medium",
        "time": "20:00",
        "category": "pmi",
        "cadence_days": 30,
        "base_day_of_month": 1,
    },
    {
        "event": "US Retail Sales",
        "country": "US",
        "impact": "medium",
        "time": "18:30",
        "category": "other",
        "cadence_days": 30,
        "base_day_of_month": 16,
    },
    # ---- China ----
    {
        "event": "China Manufacturing PMI (Caixin)",
        "country": "CN",
        "impact": "medium",
        "time": "07:15",
        "category": "pmi",
        "cadence_days": 30,
        "base_day_of_month": 1,
    },
    {
        "event": "China GDP Growth Rate",
        "country": "CN",
        "impact": "high",
        "time": "07:00",
        "category": "gdp",
        "cadence_days": 90,
        "base_day_of_month": 18,
    },
    {
        "event": "China CPI",
        "country": "CN",
        "impact": "medium",
        "time": "07:30",
        "category": "cpi",
        "cadence_days": 30,
        "base_day_of_month": 10,
    },
    # ---- European Union ----
    {
        "event": "ECB Interest Rate Decision",
        "country": "EU",
        "impact": "high",
        "time": "17:15",
        "category": "interest_rate",
        "cadence_days": 42,
        "base_day_of_month": 14,
    },
    {
        "event": "Eurozone CPI",
        "country": "EU",
        "impact": "medium",
        "time": "15:00",
        "category": "cpi",
        "cadence_days": 30,
        "base_day_of_month": 30,
    },
    {
        "event": "Eurozone GDP Growth Rate",
        "country": "EU",
        "impact": "high",
        "time": "14:30",
        "category": "gdp",
        "cadence_days": 90,
        "base_day_of_month": 30,
    },
    # ---- Japan ----
    {
        "event": "Bank of Japan Rate Decision",
        "country": "JP",
        "impact": "high",
        "time": "08:00",
        "category": "interest_rate",
        "cadence_days": 42,
        "base_day_of_month": 18,
    },
    {
        "event": "Japan CPI",
        "country": "JP",
        "impact": "medium",
        "time": "09:30",
        "category": "cpi",
        "cadence_days": 30,
        "base_day_of_month": 24,
    },
    # ---- United Kingdom ----
    {
        "event": "Bank of England Rate Decision",
        "country": "GB",
        "impact": "high",
        "time": "17:30",
        "category": "interest_rate",
        "cadence_days": 42,
        "base_day_of_month": 7,
    },
    {
        "event": "UK CPI",
        "country": "GB",
        "impact": "medium",
        "time": "14:00",
        "category": "cpi",
        "cadence_days": 30,
        "base_day_of_month": 19,
    },
    {
        "event": "UK GDP Growth Rate",
        "country": "GB",
        "impact": "high",
        "time": "14:30",
        "category": "gdp",
        "cadence_days": 90,
        "base_day_of_month": 12,
    },
]

# Representative prior/forecast pairs keyed by category
_SAMPLE_READINGS: dict[str, list[tuple[str, str]]] = {
    "interest_rate": [("6.50%", "6.50%"), ("6.25%", "6.00%"), ("5.25%", "5.50%")],
    "gdp": [("7.6%", "7.0%"), ("6.2%", "6.5%"), ("2.8%", "2.6%"), ("3.1%", "3.0%")],
    "cpi": [("5.69%", "5.10%"), ("4.85%", "4.80%"), ("3.2%", "3.1%"), ("2.6%", "2.5%")],
    "employment": [("206K", "190K"), ("8.90L", "9.00L"), ("1.9M", "1.85M")],
    "trade": [("-₹21,780Cr", "-₹20,000Cr"), ("-$78.8B", "-$80B")],
    "pmi": [("55.9", "55.5"), ("58.5", "57.0"), ("50.1", "49.9"), ("47.5", "48.0")],
    "industrial": [("5.0%", "5.5%"), ("3.8%", "4.2%")],
    "other": [("0.6%", "0.4%"), ("0.3%", "0.2%")],
}


def _sample_reading(category: str, seed: int) -> tuple[str | None, str | None]:
    """Return a (previous, forecast) pair from pre-defined sample readings.

    Args:
        category: Event category string.
        seed: Deterministic seed for selection.

    Returns:
        Tuple of (previous, forecast) strings; falls back to ``("N/A", "N/A")``.
    """
    readings = _SAMPLE_READINGS.get(category, [("N/A", "N/A")])
    entry = readings[seed % len(readings)]
    return entry[0], entry[1]


# ---------------------------------------------------------------------------
# Provider
# ---------------------------------------------------------------------------


class EconomicCalendarProvider:
    """Economic calendar backed by an in-memory list of events.

    Events are stored in a flat list and queried with list comprehensions.
    The provider is designed to be upgraded to a live data source (e.g.
    scraped from Investing.com or a paid API) without changing the public
    interface.

    Attributes:
        _events: All cached :class:`EconomicEvent` objects.
    """

    def __init__(self) -> None:
        self._events: list[EconomicEvent] = []

    # ------------------------------------------------------------------
    # Public query API
    # ------------------------------------------------------------------

    def get_upcoming(
        self,
        days: int = 14,
        countries: list[str] | None = None,
        min_impact: str = "low",
    ) -> list[EconomicEvent]:
        """Return upcoming events within the next N days with optional filters.

        Args:
            days: Look-ahead window in calendar days (clamped to 1–365).
            countries: Optional list of two-letter country codes to include.
                If ``None`` or empty all countries are returned.
            min_impact: Minimum impact level to include (``"low"``,
                ``"medium"``, or ``"high"``).  Defaults to ``"low"``
                (i.e. all events).

        Returns:
            Events sorted ascending by date then by country then by event name.
        """
        days = max(1, min(365, days))
        today = date.today()
        cutoff = today + timedelta(days=days)
        min_rank = _IMPACT_ORDER.get(min_impact.lower(), 0)

        country_filter: frozenset[str] | None = (
            frozenset(c.upper() for c in countries) if countries else None
        )

        results: list[EconomicEvent] = [
            ev
            for ev in self._events
            if (
                today <= ev.date <= cutoff
                and _IMPACT_ORDER.get(ev.impact, 0) >= min_rank
                and (country_filter is None or ev.country in country_filter)
            )
        ]
        return sorted(results, key=lambda e: (e.date, e.country, e.event))

    def get_by_country(self, country: str) -> list[EconomicEvent]:
        """Return all cached events for a single country.

        Args:
            country: Two-letter country code (case-insensitive).

        Returns:
            All matching events sorted by date ascending.
        """
        upper = country.upper()
        return sorted(
            (ev for ev in self._events if ev.country == upper),
            key=lambda e: e.date,
        )

    def event_count(self) -> int:
        """Return total number of cached events.

        Returns:
            Integer count.
        """
        return len(self._events)

    # ------------------------------------------------------------------
    # Sample data generation
    # ------------------------------------------------------------------

    def generate_sample_data(self, months: int = 2) -> list[EconomicEvent]:
        """Generate realistic sample economic events and populate the cache.

        Events are generated by stepping each template forward from the
        window start using its cadence (in days) so the spacing mirrors
        real-world release schedules.  Past events receive a simulated
        ``actual`` reading; future events have only ``previous`` and
        ``forecast``.

        Args:
            months: Total months of events to generate centred around today
                (half before, half after).  Clamped to 1–24.

        Returns:
            Flat list of all generated :class:`EconomicEvent` objects.
        """
        months = max(1, min(24, months))
        self._events.clear()

        today = date.today()
        half = max(1, months // 2)
        window_start = today - timedelta(days=half * 30)
        window_end = today + timedelta(days=(months - half) * 30)

        all_events: list[EconomicEvent] = []

        for tmpl in _EVENT_TEMPLATES:
            cadence: int = tmpl["cadence_days"]
            base_dom: int = tmpl["base_day_of_month"]
            category: str = tmpl["category"]

            # Build an anchor date for the first occurrence inside / just before
            # the window start.
            if base_dom > 0:
                # Fixed day-of-month cadence: start from first month of window
                anchor = date(window_start.year, window_start.month, min(base_dom, 28))
                if anchor > window_end:
                    continue
                if anchor < window_start - timedelta(days=cadence):
                    anchor = window_start
            else:
                # Weekly cadence (e.g. Jobless Claims — every Thursday)
                anchor = window_start
                # Move to the nearest Thursday
                days_to_thursday = (3 - anchor.weekday()) % 7
                anchor += timedelta(days=days_to_thursday)

            # Step forward through the window
            current = anchor
            seed_base = abs(hash(tmpl["event"]))
            step = 0

            while current <= window_end:
                if current >= window_start:
                    prev, forecast = _sample_reading(category, seed_base + step)
                    actual: str | None = None
                    if current < today:
                        # Simulate a slight deviation for past events
                        actual = _simulate_actual(category, forecast, seed_base + step)

                    try:
                        event = EconomicEvent(
                            date=current,
                            time=tmpl["time"],
                            event=tmpl["event"],
                            country=tmpl["country"],
                            impact=tmpl["impact"],
                            category=category,
                            previous=prev,
                            forecast=forecast,
                            actual=actual,
                        )
                        all_events.append(event)
                    except Exception:  # noqa: BLE001
                        logger.debug(
                            "Skipped invalid event template: %s", tmpl["event"]
                        )

                current += timedelta(days=cadence)
                step += 1

        self._events = sorted(all_events, key=lambda e: (e.date, e.country, e.event))
        logger.info(
            "EconomicCalendarProvider: generated %d events across %d months",
            len(self._events),
            months,
        )
        return list(self._events)

    # ------------------------------------------------------------------
    # Persistence helpers
    # ------------------------------------------------------------------

    def load_from_list(self, events: list[EconomicEvent]) -> None:
        """Populate the cache from an externally supplied list.

        Replaces any existing cached data.

        Args:
            events: Iterable of :class:`EconomicEvent` instances.
        """
        self._events = list(events)
        logger.debug(
            "EconomicCalendarProvider: loaded %d events from list", len(self._events)
        )


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _simulate_actual(category: str, forecast: str | None, seed: int) -> str:
    """Produce a simulated actual value close to the forecast.

    Applies a small ±10 % deviation so the data looks plausible without
    using random — the result is purely deterministic from the seed.

    Args:
        category: Event category (used for formatting context).
        forecast: Analyst forecast string (e.g. ``"6.50%"``).
        seed: Deterministic integer seed.

    Returns:
        Simulated actual as a string matching the forecast's format.
    """
    if not forecast or forecast == "N/A":
        return forecast or "N/A"

    # Strip non-numeric suffix characters to get the bare number
    clean = forecast.strip()
    suffix = ""
    prefix = ""

    # Detect currency prefixes
    for pfx in ("₹", "$", "€", "¥", "£"):
        if clean.startswith(pfx):
            prefix = pfx
            clean = clean[len(pfx):]
            break

    # Detect common suffixes
    for sfx in ("%", "K", "M", "B", "L", "Cr"):
        if clean.endswith(sfx):
            suffix = sfx
            clean = clean[: -len(sfx)]
            break

    try:
        val = float(clean.replace(",", "").replace(" ", ""))
    except ValueError:
        return forecast  # Cannot parse — return unchanged

    # Small deterministic nudge: ±5 % based on seed parity
    nudge = 0.03 if seed % 3 == 0 else (-0.03 if seed % 3 == 1 else 0.0)
    actual_val = round(val * (1 + nudge), 2)

    # Format back to a compact string
    formatted = f"{actual_val:g}"
    return f"{prefix}{formatted}{suffix}"
