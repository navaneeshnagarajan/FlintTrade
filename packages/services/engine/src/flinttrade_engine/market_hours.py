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
from datetime import date, datetime, time, timedelta, timezone

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
        pre_open_time: Published pre-open, when the exchange circular gives one.
            A weekend session without it stays closed until a calendar row is loaded.
    """

    session_date: date
    name: str
    open_time: time
    close_time: time
    exchanges: tuple[str, ...] = field(default_factory=lambda: ())
    pre_open_time: time | None = None


# ---------------------------------------------------------------------------
# Standard exchange hours (IST)
# ---------------------------------------------------------------------------

#: Standard market hours per exchange segment. Tuple of (open_time, close_time).
STANDARD_HOURS: dict[str, tuple[time, time]] = {
    "NSE": (time(9, 15), time(15, 30)),
    "BSE": (time(9, 15), time(15, 30)),
    "NFO": (time(9, 15), time(15, 40)),
    "BFO": (time(9, 15), time(15, 40)),
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
# Muhurat Trading is a Diwali special session. 2025 keeps the published
# evening window. 2026 F&O is the published afternoon window: pre-open
# 14:05–14:20 and normal market 14:20–15:40 IST. 2027 stays a projection
# and does not open a weekend on its own.

SPECIAL_SESSIONS: list[SpecialTradingSession] = [
    # 2025 -- Diwali: 20 Oct 2025
    SpecialTradingSession(
        session_date=date(2025, 10, 20),
        name="Muhurat Trading 2025",
        open_time=time(18, 15),
        close_time=time(19, 15),
        exchanges=_EQUITY_EXCHANGES,
    ),
    # 2026 -- Sunday 8 Nov. F&O normal market 14:20–15:40 IST.
    SpecialTradingSession(
        session_date=date(2026, 11, 8),
        name="Muhurat Trading 2026",
        open_time=time(14, 20),
        close_time=time(15, 40),
        exchanges=("NSE", "BSE", "NFO", "BFO", "NSE_INDEX", "BSE_INDEX"),
        pre_open_time=time(14, 5),
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
    exchange: str | None = None,
) -> SpecialTradingSession | None:
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


def nse_cash_phase(minutes_from_midnight: int) -> str:
    """Return the NSE cash session phase.

    Continuous 09:15–15:15, CAS 15:15–15:35, Matching 15:35–15:50,
    Post-close 15:50–16:00. Cash is never Continuous after 15:15; CAS is
    not Closed. The September 2026 consultation is not product UI.
    """
    if 9 * 60 + 15 <= minutes_from_midnight < 15 * 60 + 15:
        return "continuous"
    if 15 * 60 + 15 <= minutes_from_midnight < 15 * 60 + 35:
        return "cas"
    if 15 * 60 + 35 <= minutes_from_midnight < 15 * 60 + 50:
        return "matching"
    if 15 * 60 + 50 <= minutes_from_midnight < 16 * 60:
        return "post-close"
    return "closed"


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
    from_date: date | None = None,
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


# ---------------------------------------------------------------------------
# Muhurat operator notes
# ---------------------------------------------------------------------------

_IST = timezone(timedelta(hours=5, minutes=30))
_PRE_OPEN_LEAD_MINUTES = 15
_EQUITY_AMO_BEFORE_PRE_OPEN_MINUTES = 2
_FO_AMO_BEFORE_PRE_OPEN_MINUTES = 3
_FO_AMO_BEFORE_NORMAL_OPEN_MINUTES = 4
_MUHURAT_2026 = date(2026, 11, 8)

_FUNDS_NOTE = (
    "F&O credits and intraday equity profits from 6 November 2026 are not "
    "included in available funds during this Muhurat session. The settlement "
    "holiday keeps those credits on the ledger."
)


def _as_ist(at: datetime) -> datetime:
    if at.tzinfo is None or at.utcoffset() is None:
        return at.replace(tzinfo=_IST)
    return at.astimezone(_IST)


def _minutes(value: time) -> int:
    return value.hour * 60 + value.minute


def _hhmm(minutes: int) -> str:
    return f"{minutes // 60:02d}:{minutes % 60:02d}"


def _session_on(
    at: datetime,
    sessions: list[SpecialTradingSession] | None,
    exchange: str = "NFO",
) -> SpecialTradingSession | None:
    """Return the supplied session for this instant, or nothing when data is absent."""
    if not sessions:
        return None
    current = _as_ist(at)
    venue = exchange.strip().upper()
    for session in sessions:
        if session.session_date != current.date():
            continue
        if session.exchanges and venue not in session.exchanges:
            continue
        return session
    return None


def fo_session_state(
    at: datetime,
    sessions: list[SpecialTradingSession] | None,
    exchange: str = "NFO",
) -> str:
    """Return ``open``, ``closed``, or ``absent``.

    ``absent`` means the caller did not supply a special session for this
    date. Callers stay closed in that case.
    """
    session = _session_on(at, sessions, exchange)
    if session is None:
        return "absent"
    minutes = _minutes(_as_ist(at).time())
    if _minutes(session.open_time) <= minutes <= _minutes(session.close_time):
        return "open"
    return "closed"


def muhurat_amo_note(
    at: datetime,
    sessions: list[SpecialTradingSession] | None,
    exchange: str = "NFO",
) -> str | None:
    """After-market-order note for a supplied Muhurat session, before it opens."""
    session = _session_on(at, sessions, exchange)
    if session is None:
        return None
    current = _as_ist(at)
    minutes = _minutes(current.time())
    open_min = _minutes(session.open_time)
    close_min = _minutes(session.close_time)
    if minutes > close_min or open_min <= minutes <= close_min:
        return None
    if session.pre_open_time is not None:
        pre_open = _minutes(session.pre_open_time)
    else:
        pre_open = open_min - _PRE_OPEN_LEAD_MINUTES
    equity_cutoff = pre_open - _EQUITY_AMO_BEFORE_PRE_OPEN_MINUTES
    fo_pre_cutoff = pre_open - _FO_AMO_BEFORE_PRE_OPEN_MINUTES
    fo_normal_cutoff = open_min - _FO_AMO_BEFORE_NORMAL_OPEN_MINUTES
    open_label = _hhmm(open_min)
    pre_label = _hhmm(pre_open)
    equity_label = _hhmm(equity_cutoff)
    fo_pre_label = _hhmm(fo_pre_cutoff)
    fo_normal_label = _hhmm(fo_normal_cutoff)
    if minutes <= fo_pre_cutoff:
        return (
            "F&O after-market orders for the Muhurat session are collected until "
            f"{fo_pre_label} IST, 3 minutes before pre-open, and until {fo_normal_label} IST, "
            f"4 minutes before the {open_label} normal open. Equity after-market orders are "
            f"collected until {equity_label} IST, 2 minutes before the {pre_label} equity pre-open."
        )
    if minutes <= equity_cutoff:
        return (
            "F&O after-market orders for Muhurat pre-open have closed. Orders for the "
            f"{open_label} normal open are collected until {fo_normal_label} IST. Equity "
            f"after-market orders are collected until {equity_label} IST."
        )
    if minutes <= fo_normal_cutoff:
        return (
            "Equity after-market orders for the Muhurat session have closed. F&O after-market "
            f"orders for the {open_label} normal open are collected until {fo_normal_label} IST."
        )
    return (
        "After-market orders for the Muhurat session have closed. "
        f"F&O opens at {open_label} IST."
    )


def muhurat_funds_note(
    at: datetime,
    sessions: list[SpecialTradingSession] | None,
    exchange: str = "NFO",
) -> str | None:
    """Funds note while the 8 Nov 2026 Muhurat session is open."""
    session = _session_on(at, sessions, exchange)
    if session is None or session.session_date != _MUHURAT_2026:
        return None
    if fo_session_state(at, sessions, exchange) != "open":
        return None
    return _FUNDS_NOTE
