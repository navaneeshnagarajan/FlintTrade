"""Market hours management with special trading session support.

Provides standard market hours for Indian exchanges (NSE, BSE, MCX, etc.)
and special session handling for events like Muhurat Trading on Diwali.

Pattern adapted from AlgoMirror SpecialTradingSession model and adapted
to a pure-Python dataclass-based approach (no DB dependency).

Usage::

    from flinttrade_engine.market_hours import (
        get_market_hours,
        is_special_session,
        get_standard_hours,
    )

    # Check if today is a special session
    session = is_special_session(date.today())
    if session:
        print(f"Special: {session.name} ({session.open_time}-{session.close_time})")

    # Get effective hours for an exchange
    open_t, close_t = get_market_hours("NSE", date.today())
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import date, time
from typing import Optional

logger = logging.getLogger("flinttrade.engine.market_hours")


# ---------------------------------------------------------------------------
# Data model
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class SpecialTradingSession:
    """A special trading session that overrides standard market hours.

    Attributes:
        session_date: Calendar date of the session.
        name: Human-readable name (e.g. "Muhurat Trading 2025").
        open_time: Session opening time (IST).
        close_time: Session closing time (IST).
        exchanges: Exchanges this session applies to. An empty list
            means it applies to all equity exchanges (NSE, BSE, NFO, BFO, CDS, BCD).
    """

    session_date: date
    name: str
    open_time: time
    close_time: time
    exchanges: tuple[str, ...] = field(default_factory=lambda: ())


# ---------------------------------------------------------------------------
# Standard exchange hours (IST)
# ---------------------------------------------------------------------------

#: Standard market hours per exchange segment. Tuple of (open_time, close_time).
STANDARD_HOURS: dict[str, tuple[time, time]] = {
    "NSE": (time(9, 15), time(15, 30)),
    "BSE": (time(9, 15), time(15, 30)),
    "NFO": (time(9, 15), time(15, 30)),
    "BFO": (time(9, 15), time(15, 30)),
    "CDS": (time(9, 0), time(17, 0)),
    "BCD": (time(9, 0), time(17, 0)),
    "MCX": (time(9, 0), time(23, 30)),
    "NCDEX": (time(10, 0), time(23, 30)),
    "NCO": (time(9, 0), time(17, 0)),
    "NSE_INDEX": (time(9, 15), time(15, 30)),
    "BSE_INDEX": (time(9, 15), time(15, 30)),
    "MCX_INDEX": (time(9, 0), time(23, 30)),
    # GLOBAL_INDEX mirrors US/UK reference feeds. We expose the widest
    # plausible LTP window (Sydney open through US close) so the UI
    # reports "open" whenever the upstream feed could plausibly tick.
    "GLOBAL_INDEX": (time(0, 0), time(23, 59)),
}

#: Equity exchanges that participate in Muhurat Trading
_EQUITY_EXCHANGES = ("NSE", "BSE", "NFO", "BFO", "CDS", "BCD", "NSE_INDEX", "BSE_INDEX")


# ---------------------------------------------------------------------------
# Known special sessions -- Muhurat Trading dates for 2025-2027
# ---------------------------------------------------------------------------
#
# Muhurat Trading is held on Diwali evening, typically 6:15 PM - 7:15 PM IST.
# Dates are based on the Hindu calendar (Kartik Amavasya) and confirmed
# annually by NSE/BSE. These are best-effort predictions; the engine should
# be updated when exchanges publish official circulars.
#
# Sources:
# - NSE circulars (confirmed for 2025)
# - Hindu calendar Diwali dates for 2026-2027 (projected)

SPECIAL_SESSIONS: list[SpecialTradingSession] = [
    # 2025 -- Diwali: 20 Oct 2025
    SpecialTradingSession(
        session_date=date(2025, 10, 20),
        name="Muhurat Trading 2025",
        open_time=time(18, 15),
        close_time=time(19, 15),
        exchanges=_EQUITY_EXCHANGES,
    ),
    # 2026 -- Diwali: 8 Nov 2026 (projected)
    SpecialTradingSession(
        session_date=date(2026, 11, 8),
        name="Muhurat Trading 2026",
        open_time=time(18, 15),
        close_time=time(19, 15),
        exchanges=_EQUITY_EXCHANGES,
    ),
    # 2027 -- Diwali: 29 Oct 2027 (projected)
    SpecialTradingSession(
        session_date=date(2027, 10, 29),
        name="Muhurat Trading 2027",
        open_time=time(18, 15),
        close_time=time(19, 15),
        exchanges=_EQUITY_EXCHANGES,
    ),
]

# Pre-index by date for O(1) lookup
_SESSIONS_BY_DATE: dict[date, list[SpecialTradingSession]] = {}
for _session in SPECIAL_SESSIONS:
    _SESSIONS_BY_DATE.setdefault(_session.session_date, []).append(_session)


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def is_special_session(
    target_date: date,
    exchange: Optional[str] = None,
) -> Optional[SpecialTradingSession]:
    """Check whether a date has a special trading session.

    Args:
        target_date: The date to check.
        exchange: If provided, only return sessions applicable to this
            exchange. If None, return the first matching session regardless
            of exchange.

    Returns:
        The matching SpecialTradingSession, or None if no special session
        is scheduled for the given date (and exchange).
    """
    sessions = _SESSIONS_BY_DATE.get(target_date)
    if not sessions:
        return None

    for session in sessions:
        if exchange is None:
            return session
        # Empty exchanges tuple means all equity exchanges
        if not session.exchanges or exchange in session.exchanges:
            return session

    return None


def get_standard_hours(exchange: str) -> tuple[time, time]:
    """Return the standard (open, close) times for an exchange.

    Args:
        exchange: Exchange code (e.g. "NSE", "MCX").

    Returns:
        Tuple of (open_time, close_time) in IST.

    Raises:
        ValueError: If the exchange code is not recognised.
    """
    hours = STANDARD_HOURS.get(exchange)
    if hours is None:
        raise ValueError(
            f"Unknown exchange: {exchange!r}. "
            f"Supported: {', '.join(sorted(STANDARD_HOURS.keys()))}"
        )
    return hours


def get_market_hours(
    exchange: str,
    target_date: date,
) -> tuple[time, time]:
    """Return the effective (open, close) times for an exchange on a date.

    If a special session (e.g. Muhurat Trading) is scheduled for the given
    date and applies to the exchange, those hours are returned instead of
    the standard hours.

    Args:
        exchange: Exchange code (e.g. "NSE", "MCX").
        target_date: The calendar date to query.

    Returns:
        Tuple of (open_time, close_time) in IST.

    Raises:
        ValueError: If the exchange code is not recognised.
    """
    special = is_special_session(target_date, exchange=exchange)
    if special is not None:
        logger.info(
            "Special session '%s' on %s for %s: %s-%s",
            special.name,
            target_date,
            exchange,
            special.open_time,
            special.close_time,
        )
        return (special.open_time, special.close_time)

    return get_standard_hours(exchange)


def add_special_session(session: SpecialTradingSession) -> None:
    """Register an additional special trading session at runtime.

    This is useful for dynamically adding sessions from exchange circulars
    without modifying the SPECIAL_SESSIONS constant.

    Args:
        session: The special session to register.
    """
    SPECIAL_SESSIONS.append(session)
    _SESSIONS_BY_DATE.setdefault(session.session_date, []).append(session)
    logger.info(
        "Registered special session '%s' on %s (%s-%s)",
        session.name,
        session.session_date,
        session.open_time,
        session.close_time,
    )


def list_upcoming_sessions(
    from_date: Optional[date] = None,
    limit: int = 10,
) -> list[SpecialTradingSession]:
    """Return upcoming special sessions sorted by date.

    Args:
        from_date: Start date (inclusive). Defaults to today.
        limit: Maximum number of sessions to return.

    Returns:
        List of SpecialTradingSession objects ordered by date.
    """
    if from_date is None:
        from_date = date.today()

    upcoming = [s for s in SPECIAL_SESSIONS if s.session_date >= from_date]
    upcoming.sort(key=lambda s: s.session_date)
    return upcoming[:limit]
