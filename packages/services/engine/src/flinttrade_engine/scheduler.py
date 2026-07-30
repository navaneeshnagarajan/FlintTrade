"""Time scheduler + async strategy execution engine.

Query utilities: market hours, auto square-off, deploy freeze, holidays.
Execution: StrategyRunner (single strategy tick loop), StrategyScheduler (multi).
Cron scheduling: CronStrategyScheduler (APScheduler-based, IST-aware, market-gated).

All times are in IST (Asia/Kolkata, UTC+5:30).
"""

from __future__ import annotations

import asyncio
import inspect
import logging
import math
import threading
import time as _time
from collections.abc import Awaitable as AwaitableABC, Coroutine as CoroutineABC
from contextvars import ContextVar
from dataclasses import dataclass, field
from datetime import date, datetime, time, timedelta, timezone
from types import UnionType
from typing import Annotated, Any, Callable, TypeAliasType, Union, get_args, get_origin, get_type_hints

from flinttrade_core.models import Quote
from flinttrade_core.openalgo_client import OpenAlgoClient

from .strategy import BaseStrategy, StrategyState

logger = logging.getLogger("flinttrade.engine.scheduler")


class StrategyStartTimeoutError(TimeoutError):
    """Raised after a timed-out start is revoked and bounded cleanup is attempted."""


class StrategyStopTimeoutError(TimeoutError):
    """Raised while a bounded route wait leaves scheduler-owned cleanup running."""


_MIN_TERMINAL_DRAIN_SECONDS = 0.05
_MAX_TERMINAL_DRAIN_SECONDS = 5.0


@dataclass
class _RevocableStartRequest:
    """Cross-thread revocation signal for one route-submitted start."""

    _revoked: threading.Event = field(default_factory=threading.Event)

    @property
    def revoked(self) -> bool:
        return self._revoked.is_set()

    def revoke(self) -> None:
        self._revoked.set()


@dataclass
class _StrategyExecutionLease:
    """Generation-scoped ownership inherited by tasks spawned in a callback."""

    runner: Any
    task: asyncio.Task[None] | None
    active: bool = True


_CURRENT_STRATEGY_LEASE: ContextVar[_StrategyExecutionLease | None] = ContextVar(
    "current_strategy_execution_lease",
    default=None,
)


def _future_stored_exception_is(future: Any, error: BaseException) -> bool:
    """Distinguish a completed operation failure from ``Future.result`` wait expiry."""
    if not future.done():
        return False
    try:
        return future.exception() is error
    except BaseException:  # cancelled/racing futures are not completed with this error
        return False

# IST is UTC+5:30
IST = timezone(timedelta(hours=5, minutes=30))


async def _await_if_needed(result: Any) -> Any:
    """Await a strategy hook result when the implementation is asynchronous."""
    if inspect.isawaitable(result):
        return await result
    return result


# ---------------------------------------------------------------------------
# Exchange schedule definitions
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class ExchangeSchedule:
    """Trading hours and auto square-off for an exchange segment."""

    exchange: str
    market_open: time  # IST
    market_close: time  # IST
    square_off: time  # IST — auto square-off for MIS positions
    is_24x7: bool = False


# Exchange schedules — see docs/ARCHITECTURE.md and docs/USER_GUIDE.md (Operations).
EXCHANGE_SCHEDULES: dict[str, ExchangeSchedule] = {
    "NSE": ExchangeSchedule("NSE", time(9, 15), time(15, 30), time(15, 15)),
    "BSE": ExchangeSchedule("BSE", time(9, 15), time(15, 30), time(15, 15)),
    "NFO": ExchangeSchedule("NFO", time(9, 15), time(15, 30), time(15, 15)),
    "BFO": ExchangeSchedule("BFO", time(9, 15), time(15, 30), time(15, 15)),
    "CDS": ExchangeSchedule("CDS", time(9, 0), time(17, 0), time(16, 45)),
    "BCD": ExchangeSchedule("BCD", time(9, 0), time(17, 0), time(16, 45)),
    "MCX": ExchangeSchedule("MCX", time(9, 0), time(23, 55), time(23, 30)),
    "NCDEX": ExchangeSchedule("NCDEX", time(10, 0), time(17, 0), time(16, 45)),
    # NCO (NSE Commodities) — Zerodha-only on upstream as of v2.0.0.7.
    "NCO": ExchangeSchedule("NCO", time(9, 0), time(17, 0), time(16, 45)),
    "DELTA": ExchangeSchedule("DELTA", time(0, 0), time(23, 59), time(23, 59), is_24x7=True),
    "NSE_INDEX": ExchangeSchedule("NSE_INDEX", time(9, 15), time(15, 30), time(15, 30)),
    "BSE_INDEX": ExchangeSchedule("BSE_INDEX", time(9, 15), time(15, 30), time(15, 30)),
    "MCX_INDEX": ExchangeSchedule("MCX_INDEX", time(9, 0), time(23, 30), time(23, 30)),
    # GLOBAL_INDEX is reference-only; we treat it as 24/7 for scheduling so
    # cron strategies that read GLOBAL_INDEX quotes never get blocked by a
    # closed-market guard.
    "GLOBAL_INDEX": ExchangeSchedule(
        "GLOBAL_INDEX",
        time(0, 0),
        time(23, 59),
        time(23, 59),
        is_24x7=True,
    ),
}


# Deploy freeze windows per market segment — see docs/USER_GUIDE.md (Operations).
_DEPLOY_FREEZE_WINDOWS: dict[str, tuple[time, time]] = {
    "equity": (time(9, 15), time(15, 30)),
    "currency": (time(9, 0), time(17, 0)),
    "mcx": (time(9, 0), time(23, 55)),
    "crypto": (time(0, 0), time(23, 59)),  # 24/7 — always frozen, needs position check
}

# Map exchanges to deploy freeze segments
_EXCHANGE_TO_SEGMENT: dict[str, str] = {
    "NSE": "equity",
    "BSE": "equity",
    "NFO": "equity",
    "BFO": "equity",
    "NSE_INDEX": "equity",
    "BSE_INDEX": "equity",
    "CDS": "currency",
    "BCD": "currency",
    "MCX": "mcx",
    "NCDEX": "mcx",
    "MCX_INDEX": "mcx",
    "NCO": "mcx",
    "DELTA": "crypto",
    "GLOBAL_INDEX": "crypto",
}

_CDS_CROSS_CURRENCY_UNDERLYINGS = ("EURUSD", "GBPUSD", "USDJPY")

_CALENDAR_EXCHANGE_ALIASES = {
    "NSE_INDEX": "NSE",
    "BSE_INDEX": "BSE",
    "MCX_INDEX": "MCX",
}

_MAX_CROSS_MIDNIGHT_SESSION_DURATION = timedelta(hours=12)


def _is_cds_cross_currency(symbol: str | None) -> bool:
    value = str(symbol or "").strip().upper()
    return any(value.startswith(underlying) for underlying in _CDS_CROSS_CURRENCY_UNDERLYINGS)


def _as_ist(value: datetime) -> datetime:
    """Interpret naive scheduler values as IST and convert aware values to IST."""
    if value.tzinfo is None or value.utcoffset() is None:
        return value.replace(tzinfo=IST)
    return value.astimezone(IST)


def _calendar_exchange(exchange: str) -> str:
    value = exchange.strip().upper()
    return _CALENDAR_EXCHANGE_ALIASES.get(value, value)


def _calendar_time(value: Any) -> time | None:
    if isinstance(value, time):
        return value.replace(tzinfo=None)
    if isinstance(value, bool):
        return None
    if isinstance(value, int | float):
        epoch = float(value)
        if not math.isfinite(epoch):
            return None
        if abs(epoch) >= 100_000_000_000:
            epoch /= 1000.0
        try:
            return datetime.fromtimestamp(epoch, tz=IST).time().replace(tzinfo=None)
        except (OSError, OverflowError, ValueError):
            return None
    if not isinstance(value, str) or not value.strip():
        return None
    text = value.strip()
    try:
        numeric = float(text)
    except ValueError:
        numeric = None
    if numeric is not None:
        return _calendar_time(numeric)
    try:
        return time.fromisoformat(text).replace(tzinfo=None)
    except ValueError:
        try:
            parsed = datetime.fromisoformat(text[:-1] + "+00:00" if text.endswith(("Z", "z")) else text)
        except ValueError:
            return None
        return _as_ist(parsed).time().replace(tzinfo=None)


@dataclass(frozen=True)
class _SpecialMarketSession:
    exchange: str
    start: time
    end: time
    symbols: tuple[str, ...] = ()

    def matches(self, symbol: str | None) -> bool:
        if not self.symbols:
            return True
        candidate = str(symbol or "").strip().upper()
        return bool(candidate) and any(candidate.startswith(prefix) for prefix in self.symbols)


@dataclass
class _CalendarDay:
    closed_exchanges: set[str] = field(default_factory=set)
    open_sessions: list[_SpecialMarketSession] = field(default_factory=list)


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
        self._calendar_days: dict[date, _CalendarDay] = {}

    def now_ist(self) -> datetime:
        """Current datetime in IST."""
        return datetime.now(IST)

    # ------------------------------------------------------------------
    # Market hours
    # ------------------------------------------------------------------

    def get_schedule(self, exchange: str) -> ExchangeSchedule | None:
        return EXCHANGE_SCHEDULES.get(exchange.strip().upper())

    def is_market_open(
        self,
        exchange: str,
        at: datetime | None = None,
        symbol: str | None = None,
    ) -> bool:
        """Check whether the exchange is open on the trading calendar and clock."""
        exchange = exchange.strip().upper()
        sched = EXCHANGE_SCHEDULES.get(exchange)
        if sched is None:
            return False

        if sched.is_24x7:
            return True

        current = _as_ist(at) if at is not None else self.now_ist()
        return (
            self._active_market_window(
                exchange,
                at=current,
                symbol=symbol,
            )
            is not None
        )

    def get_market_session(
        self,
        exchange: str,
        *,
        on: date | None = None,
        symbol: str | None = None,
    ) -> tuple[time, time] | None:
        """Return effective IST hours after exchange and special-session rules."""
        exchange_key = exchange.strip().upper()
        sched = EXCHANGE_SCHEDULES.get(exchange_key)
        if sched is None:
            return None
        if sched.is_24x7:
            return sched.market_open, sched.market_close

        session_date = on or self.now_ist().date()
        calendar_key = _calendar_exchange(exchange_key)
        calendar_day = self._calendar_days.get(session_date)
        if calendar_day is not None:
            exchange_sessions = [session for session in calendar_day.open_sessions if session.exchange == calendar_key]
            matching_sessions = [session for session in exchange_sessions if session.matches(symbol)]
            if matching_sessions:
                selected = min(matching_sessions, key=lambda session: session.start)
                return selected.start, selected.end
            if (
                "*" in calendar_day.closed_exchanges
                or calendar_key in calendar_day.closed_exchanges
                or exchange_sessions
            ):
                return None
        elif session_date.isoformat() in self._holidays.get(str(session_date.year), []):
            return None

        if session_date.weekday() >= 5:
            return None
        market_close = time(19, 30) if exchange_key == "CDS" and _is_cds_cross_currency(symbol) else sched.market_close
        return sched.market_open, market_close

    def is_trading_day(
        self,
        exchange: str,
        on: date | None = None,
        symbol: str | None = None,
    ) -> bool:
        """Check if the given date is a trading day (not weekend, not holiday)."""
        return self.get_market_session(exchange, on=on, symbol=symbol) is not None

    def _active_market_window(
        self,
        exchange: str,
        *,
        at: datetime,
        symbol: str | None = None,
    ) -> tuple[datetime, datetime] | None:
        """Return the effective session datetimes when ``at`` is inside them."""
        for day_offset in (0, -1):
            session_date = at.date() + timedelta(days=day_offset)
            session = self.get_market_session(exchange, on=session_date, symbol=symbol)
            if session is None:
                continue
            market_open, market_close = session
            session_midnight = at.replace(hour=0, minute=0, second=0, microsecond=0)
            session_midnight += timedelta(days=day_offset)
            opens_at = session_midnight.replace(
                hour=market_open.hour,
                minute=market_open.minute,
                second=market_open.second,
                microsecond=market_open.microsecond,
            )
            closes_at = session_midnight.replace(
                hour=market_close.hour,
                minute=market_close.minute,
                second=market_close.second,
                microsecond=market_close.microsecond,
            )
            if market_close < market_open:
                closes_at += timedelta(days=1)
            if opens_at <= at <= closes_at:
                return opens_at, closes_at
        return None

    @staticmethod
    def _square_off_offset(schedule: ExchangeSchedule) -> timedelta:
        """Return the configured pre-close square-off offset."""
        close_minutes = schedule.market_close.hour * 60 + schedule.market_close.minute
        square_off_minutes = schedule.square_off.hour * 60 + schedule.square_off.minute
        if square_off_minutes > close_minutes:
            close_minutes += 24 * 60
        return timedelta(minutes=close_minutes - square_off_minutes)

    def time_to_square_off(
        self,
        exchange: str,
        at: datetime | None = None,
        symbol: str | None = None,
    ) -> timedelta | None:
        """Time remaining until auto square-off. None if market closed or 24/7."""
        sched = EXCHANGE_SCHEDULES.get(exchange.strip().upper())
        if sched is None or sched.is_24x7:
            return None

        now = _as_ist(at) if at is not None else self.now_ist()
        active_window = self._active_market_window(exchange, at=now, symbol=symbol)
        if active_window is None:
            return None
        _, closes_at = active_window
        sq_dt = closes_at - self._square_off_offset(sched)
        remaining = sq_dt - now
        if remaining.total_seconds() < 0:
            return timedelta(0)
        return remaining

    def should_square_off(
        self,
        exchange: str,
        at: datetime | None = None,
        symbol: str | None = None,
    ) -> bool:
        """True if current time is at or past the square-off time."""
        sched = EXCHANGE_SCHEDULES.get(exchange.strip().upper())
        if sched is None or sched.is_24x7:
            return False

        now = _as_ist(at) if at is not None else self.now_ist()
        active_window = self._active_market_window(exchange, at=now, symbol=symbol)
        if active_window is None:
            return False
        _, closes_at = active_window
        return now >= closes_at - self._square_off_offset(sched)

    # ------------------------------------------------------------------
    # Deploy freeze
    # ------------------------------------------------------------------

    def is_deploy_frozen(self, exchanges: list[str] | None = None, at: datetime | None = None) -> bool:
        """Check if ANY of the given exchanges is in a deploy freeze window.

        If no exchanges given, checks the equity window (NSE) as the default.
        """
        now = _as_ist(at) if at is not None else self.now_ist()
        now_t = now.time().replace(tzinfo=None)
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

    def set_holidays(
        self,
        holidays: Any,
        *,
        year: str | None = None,
        exchange: str = "NSE",
    ) -> list[str]:
        """Cache a normalised holiday payload already fetched by another owner."""
        from flinttrade_core.openalgo_client import (  # noqa: PLC0415
            normalise_holiday_dates,
            normalise_market_calendar,
        )

        calendar_rows = normalise_market_calendar(holidays)
        replacement_years = (
            {int(year)} if year is not None else {date.fromisoformat(row["date"]).year for row in calendar_rows}
        )
        for holiday_date in tuple(self._calendar_days):
            if holiday_date.year in replacement_years:
                self._calendar_days.pop(holiday_date, None)
        for row in calendar_rows:
            holiday_date = date.fromisoformat(row["date"])
            calendar_day = self._calendar_days.setdefault(holiday_date, _CalendarDay())
            calendar_day.closed_exchanges.update(
                _calendar_exchange(exchange_name) for exchange_name in row["closed_exchanges"]
            )
            for raw_session in row["open_exchanges"]:
                session_exchange = _calendar_exchange(str(raw_session.get("exchange") or ""))
                start = _calendar_time(raw_session.get("start_time"))
                end = _calendar_time(raw_session.get("end_time"))
                cross_midnight_duration = (
                    datetime.combine(date.min + timedelta(days=1), end) - datetime.combine(date.min, start)
                    if start is not None and end is not None and end < start
                    else None
                )
                if (
                    start is None
                    or end is None
                    or end == start
                    or (
                        cross_midnight_duration is not None
                        and cross_midnight_duration > _MAX_CROSS_MIDNIGHT_SESSION_DURATION
                    )
                ):
                    if session_exchange:
                        calendar_day.closed_exchanges.add(session_exchange)
                    continue
                symbols = {str(raw_session.get("symbol") or "").strip().upper()}
                raw_symbols = raw_session.get("symbols", [])
                if isinstance(raw_symbols, list | tuple | set):
                    symbols.update(str(symbol).strip().upper() for symbol in raw_symbols)
                symbols.discard("")
                session = _SpecialMarketSession(
                    exchange=session_exchange,
                    start=start,
                    end=end,
                    symbols=tuple(sorted(symbols)),
                )
                if session.exchange and session not in calendar_day.open_sessions:
                    calendar_day.open_sessions.append(session)

        values = normalise_holiday_dates(holidays, exchange=exchange)
        grouped: dict[str, list[str]] = {}
        for value in values:
            grouped.setdefault(value[:4], []).append(value)
        for holiday_year, dates in grouped.items():
            self._holidays[holiday_year] = dates
        if not values:
            resolved_year = year or str(self.now_ist().year)
            self._holidays[resolved_year] = []
        elif year is not None and year not in grouped:
            self._holidays[year] = []
        return values

    def load_holidays(self, year: str | None = None) -> list[str]:
        """Fetch holidays from OpenAlgo and cache them.

        ``OpenAlgoClient.holidays()`` is an async method. This synchronous
        helper runs it to completion using asyncio, so it can be called from
        non-async startup code (e.g. app initialisation, tests).

        Returns list of date strings like ["2026-01-26", "2026-03-14", ...].
        """
        y = year or str(self.now_ist().year)

        if self._client is None:
            logger.warning("No OpenAlgo client — cannot fetch holidays")
            return []

        try:
            try:
                loop = asyncio.get_running_loop()
            except RuntimeError:
                loop = None

            if loop is not None and loop.is_running():
                logger.error(
                    "Cannot synchronously load holidays from a running event-loop thread; "
                    "fetch asynchronously and call set_holidays()"
                )
                return []
            # One-owner-loop rule for the shared client's pooled connections.
            from flinttrade_core.openalgo_client import client_call_sync  # noqa: PLC0415

            data = client_call_sync(
                self._client,
                self._client.holidays(  # type: ignore[union-attr]
                    year=y,
                    allow_legacy_fallback=True,
                ),
            )

            holidays = self.set_holidays(data, year=y)
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


# ---------------------------------------------------------------------------
# Live quote helper
# ---------------------------------------------------------------------------


async def get_latest_quote(
    client: OpenAlgoClient,
    symbol: str,
    exchange: str,
) -> Quote | None:
    """Fetch the latest quote from OpenAlgo. Returns None on failure."""
    try:
        return await client.quotes(symbol, exchange)
    except Exception as exc:
        logger.warning("Failed to get quote for %s/%s: %s", symbol, exchange, exc)
        return None


# ---------------------------------------------------------------------------
# StrategyRunner — single-strategy async tick loop
# ---------------------------------------------------------------------------


class StrategyRunner:
    """Runs a single strategy in an async tick loop.

    Flow per tick:
    1. Check market open + not deploy-frozen
    2. Fetch live quote via OpenAlgoClient
    3. Call strategy.on_tick(quote)
    4. Check should_square_off — trigger auto square-off if needed
    """

    def __init__(
        self,
        strategy: BaseStrategy,
        client: OpenAlgoClient,
        scheduler: TimeScheduler | None = None,
        tick_interval_seconds: float = 1.0,
        symbol: str = "",
        lifecycle_timeout_seconds: float = 30.0,
        start_generation_provider: Callable[[], int] | None = None,
    ) -> None:
        self.strategy = strategy
        self.execution_contract = strategy.require_execution_contract()
        self.client = client
        self.scheduler = scheduler or TimeScheduler()
        self.tick_interval = tick_interval_seconds
        self.symbol = symbol or str(getattr(strategy, "symbol", "")).strip() or strategy.name
        self.lifecycle_timeout = max(0.001, float(lifecycle_timeout_seconds))
        self._start_generation_provider = start_generation_provider
        self._task: asyncio.Task[None] | None = None
        self._running = False
        self._tick_count = 0
        self._transition_lock = asyncio.Lock()
        self._start_hook_task: asyncio.Task[Any] | None = None
        self._stop_hook_task: asyncio.Task[Any] | None = None
        self._start_hook_worker_active: threading.Event | None = None
        self._stop_hook_worker_active: threading.Event | None = None
        self._stop_request_count = 0
        self._stop_failed = False
        self._cleanup_required = False
        self._quarantined = False
        self._retired = False
        self._ownership_lock = threading.RLock()

    @property
    def is_running(self) -> bool:
        with self._ownership_lock:
            return self._running

    @property
    def cleanup_required(self) -> bool:
        """True until a started lifecycle generation is stopped cleanly."""
        with self._ownership_lock:
            return self._cleanup_required

    @property
    def is_quarantined(self) -> bool:
        """True when lifecycle ownership outlived bounded scheduler cleanup."""
        with self._ownership_lock:
            return self._quarantined

    @property
    def has_live_owner(self) -> bool:
        """True while execution or an incomplete lifecycle transition is owned."""
        with self._ownership_lock:
            return self._has_live_owner_unlocked()

    def _has_live_owner_unlocked(self) -> bool:
        return bool(
            self._running
            or self._cleanup_required
            or self._quarantined
            or (self._task is not None and not self._task.done())
            or self._start_hook_task is not None
            or self._stop_hook_task is not None
            or self._stop_request_count
            or self._stop_failed
            or self.strategy.state != StrategyState.STOPPED
        )

    def _retire(self) -> None:
        """Permanently prevent this generation from starting again."""
        with self._ownership_lock:
            if self._retired:
                return
            if self._has_live_owner_unlocked():
                raise RuntimeError("Strategy runner still owns lifecycle work")
            self._retired = True

    def _requires_stop(self) -> bool:
        """Return whether a writer or incomplete transition still needs cleanup."""
        with self._ownership_lock:
            return bool(
                self._running
                or self._cleanup_required
                or self._quarantined
                or (self._task is not None and not self._task.done())
                or self._start_hook_task is not None
                or self._stop_hook_task is not None
                or self._stop_failed
                or self.strategy.state != StrategyState.STOPPED
            )

    @property
    def tick_count(self) -> int:
        return self._tick_count

    async def start(self) -> None:
        """Start the strategy and begin the tick loop."""
        self.execution_contract = self.strategy.require_execution_contract()
        expected_generation = self._admit_start()
        async with self._transition_lock:
            self._assert_start_generation(expected_generation)
            with self._ownership_lock:
                if self._retired:
                    raise RuntimeError("Strategy runner generation is permanently retired")
                if self._running:
                    return
                if self._stop_request_count or self._stop_failed:
                    raise RuntimeError("Strategy cannot restart because the previous stop did not complete")
                if self._cleanup_required:
                    raise RuntimeError("Strategy cannot restart because previous lifecycle cleanup did not complete")
                self._cleanup_required = True

            start_hook, worker_active = self._create_lifecycle_hook_task(self.strategy.start)
            with self._ownership_lock:
                self._start_hook_task = start_hook
                self._start_hook_worker_active = worker_active
            try:
                await self._wait_for_task(
                    start_hook,
                    label="start hook",
                    cancel_on_timeout=True,
                    worker_active=worker_active,
                )
            except asyncio.CancelledError as exc:
                if not worker_active.is_set() and not start_hook.done():
                    start_hook.cancel()
                    await asyncio.sleep(0)
                with self._ownership_lock:
                    stop_requested = bool(self._stop_request_count)
                if stop_requested:
                    raise RuntimeError("Strategy start was interrupted by stop") from exc
                raise
            finally:
                if start_hook.done():
                    with self._ownership_lock:
                        if self._start_hook_task is start_hook:
                            self._start_hook_task = None
                            self._start_hook_worker_active = None

            self._assert_start_generation(expected_generation)
            with self._ownership_lock:
                if self._stop_request_count:
                    raise RuntimeError("Strategy start was interrupted by stop")
                self._running = True
                self._task = asyncio.create_task(self._run_loop())
                self._task.add_done_callback(self._on_run_loop_done)
            logger.info(
                "StrategyRunner started: %s on %s",
                self.strategy.name,
                self.strategy.exchange,
            )

    async def stop(self) -> None:
        """Stop the strategy and cancel the tick loop."""
        if not self._requires_stop():
            with self._ownership_lock:
                if self._task is not None and self._task.done():
                    self._task = None
            return
        with self._ownership_lock:
            self._stop_request_count += 1
            start_hook = self._start_hook_task
            start_hook_worker_active = self._start_hook_worker_active
        try:
            if start_hook is not None and not start_hook.done():
                if start_hook_worker_active is None or not start_hook_worker_active.is_set():
                    start_hook.cancel()

            try:
                await asyncio.wait_for(
                    self._transition_lock.acquire(),
                    timeout=self.lifecycle_timeout,
                )
            except TimeoutError as exc:
                with self._ownership_lock:
                    self._stop_failed = True
                raise TimeoutError("Strategy lifecycle transition did not stop before the deadline") from exc

            try:
                if not self._requires_stop():
                    return
                with self._ownership_lock:
                    self._running = False
                    task = self._task
                current_task = asyncio.current_task()
                execution_lease = _CURRENT_STRATEGY_LEASE.get()
                caller_owns_tick = task is current_task or bool(
                    execution_lease is not None
                    and execution_lease.active
                    and execution_lease.runner is self
                    and execution_lease.task is task
                )
                if task is not None and not task.done() and not caller_owns_tick:
                    task.cancel()
                    await self._wait_for_task(
                        task,
                        label="tick loop",
                        cancel_on_timeout=True,
                    )
                if task is None or task.done():
                    with self._ownership_lock:
                        if self._task is task:
                            self._task = None

                await self._drain_start_hook_for_stop()

                stop_hook, stop_hook_worker_active = self._get_or_create_stop_hook()
                if not stop_hook.done():
                    await self._wait_for_task(
                        stop_hook,
                        label="stop hook",
                        cancel_on_timeout=True,
                        worker_active=stop_hook_worker_active,
                    )
            except BaseException:
                with self._ownership_lock:
                    self._stop_failed = True
                raise
            else:
                with self._ownership_lock:
                    self_stop_handoff = bool(caller_owns_tick and task is not None and not task.done())
                    if not self_stop_handoff:
                        self._stop_hook_task = None
                        self._stop_hook_worker_active = None
                    self._cleanup_required = self_stop_handoff
                    self._quarantined = False
                    self._stop_failed = False
                logger.info(
                    "StrategyRunner stopped: %s (ticks=%d)",
                    self.strategy.name,
                    self._tick_count,
                )
            finally:
                self._transition_lock.release()
        finally:
            with self._ownership_lock:
                self._stop_request_count -= 1
                if self._stop_request_count < 0:
                    raise RuntimeError("Strategy stop request ownership underflow")

    def _create_lifecycle_hook_task(
        self,
        hook: Callable[[], Any],
    ) -> tuple[asyncio.Task[Any], threading.Event]:
        """Create an owned hook task and offload synchronous invocation."""
        declares_awaitable = self._declares_awaitable_return(hook)
        uses_worker = not inspect.iscoroutinefunction(hook) and not declares_awaitable
        worker_active = threading.Event()

        async def invoke() -> Any:
            if uses_worker:
                worker_active.set()
                try:
                    result = await asyncio.to_thread(hook)
                finally:
                    worker_active.clear()
            else:
                result = hook()
            return await _await_if_needed(result)

        return asyncio.create_task(invoke()), worker_active

    def _admit_start(self) -> int | None:
        """Return the scheduler lifecycle generation that admits this start."""
        if self._start_generation_provider is None:
            return None
        return self._start_generation_provider()

    def _assert_start_generation(self, expected_generation: int | None) -> None:
        """Reject starts superseded by an aggregate scheduler stop."""
        if self._start_generation_provider is None:
            return
        current_generation = self._start_generation_provider()
        if current_generation != expected_generation:
            raise RuntimeError("Strategy start was superseded by an aggregate stop")

    @staticmethod
    def _declares_awaitable_return(hook: Callable[[], Any]) -> bool:
        """Resolve whether a synchronous hook promises an awaitable result."""
        try:
            return_annotation = get_type_hints(hook).get("return", inspect.Signature.empty)
        except Exception:  # noqa: BLE001 - unresolved optional annotations stay on the bounded worker
            return False
        return StrategyRunner._annotation_contains_awaitable(return_annotation)

    @staticmethod
    def _annotation_contains_awaitable(
        annotation: Any,
        seen_aliases: set[int] | None = None,
        type_bindings: dict[Any, Any] | None = None,
    ) -> bool:
        """Unwrap only transparent annotation wrappers around awaitable types."""
        if type_bindings is not None:
            try:
                bound_annotation = type_bindings.get(annotation, annotation)
            except TypeError:
                bound_annotation = annotation
            if bound_annotation is not annotation:
                return StrategyRunner._annotation_contains_awaitable(
                    bound_annotation,
                    seen_aliases,
                    type_bindings,
                )
        origin = get_origin(annotation)
        alias = (
            annotation
            if isinstance(annotation, TypeAliasType)
            else origin
            if isinstance(origin, TypeAliasType)
            else None
        )
        if alias is not None:
            visited = set() if seen_aliases is None else set(seen_aliases)
            alias_identity = id(alias)
            if alias_identity in visited:
                return False
            visited.add(alias_identity)
            try:
                alias_value = alias.__value__
            except Exception:  # noqa: BLE001 - lazy optional type providers are non-authoritative
                return False
            bindings = dict(type_bindings or {})
            if origin is alias:
                bindings.update(zip(alias.__type_params__, get_args(annotation), strict=False))
            return StrategyRunner._annotation_contains_awaitable(alias_value, visited, bindings)
        awaitable_types = (AwaitableABC, CoroutineABC, asyncio.Future)
        if annotation in awaitable_types or origin in awaitable_types:
            return True
        if origin is Annotated:
            return StrategyRunner._annotation_contains_awaitable(
                get_args(annotation)[0],
                seen_aliases,
                type_bindings,
            )
        if origin in (Union, UnionType):
            return any(
                StrategyRunner._annotation_contains_awaitable(member, seen_aliases, type_bindings)
                for member in get_args(annotation)
            )
        return isinstance(annotation, type) and issubclass(annotation, awaitable_types)

    def _get_or_create_stop_hook(self) -> tuple[asyncio.Task[Any], threading.Event]:
        """Reuse a retained stop hook, or create one after a failed attempt."""
        with self._ownership_lock:
            stop_hook = self._stop_hook_task
            worker_active = self._stop_hook_worker_active
        if stop_hook is not None and stop_hook.done():
            try:
                stop_hook.result()
            except (asyncio.CancelledError, Exception):
                stop_hook = None
                with self._ownership_lock:
                    self._stop_hook_task = None
                    self._stop_hook_worker_active = None
        if stop_hook is None:
            stop_hook, worker_active = self._create_lifecycle_hook_task(self.strategy.stop)
            with self._ownership_lock:
                self._stop_hook_task = stop_hook
                self._stop_hook_worker_active = worker_active
        if worker_active is None:
            raise RuntimeError("Strategy stop hook lost worker ownership")
        return stop_hook, worker_active

    async def _drain_start_hook_for_stop(self) -> None:
        """Drain an interrupted start before invoking the stop hook."""
        with self._ownership_lock:
            start_hook = self._start_hook_task
            worker_active = self._start_hook_worker_active
        if start_hook is None:
            return
        if not start_hook.done():
            done, _ = await asyncio.wait(
                {start_hook},
                timeout=self.lifecycle_timeout,
            )
            if not done:
                if worker_active is None or not worker_active.is_set():
                    start_hook.cancel()
                    await asyncio.sleep(0)
                raise TimeoutError("Strategy start hook did not stop before the deadline")
        try:
            start_hook.result()
        except (asyncio.CancelledError, Exception):
            pass
        finally:
            with self._ownership_lock:
                if self._start_hook_task is start_hook:
                    self._start_hook_task = None
                    self._start_hook_worker_active = None

    async def _wait_for_task(
        self,
        task: asyncio.Task[Any],
        *,
        label: str,
        cancel_on_timeout: bool,
        worker_active: threading.Event | None = None,
    ) -> None:
        """Wait for an owned lifecycle task without exceeding the deadline."""
        done, _ = await asyncio.wait({task}, timeout=self.lifecycle_timeout)
        if not done:
            if cancel_on_timeout and (worker_active is None or not worker_active.is_set()):
                task.cancel()
                await asyncio.sleep(0)
            raise TimeoutError(f"Strategy {label} did not stop before the deadline")
        try:
            task.result()
        except asyncio.CancelledError:
            if label != "tick loop":
                raise

    def pause(self) -> None:
        """Pause the strategy (loop continues but skips on_tick)."""
        self.strategy.pause()

    def resume(self) -> None:
        """Resume a paused strategy."""
        self.strategy.resume()

    def _on_run_loop_done(self, task: asyncio.Task[None]) -> None:
        """Release running state even when cancellation precedes coroutine entry."""
        with self._ownership_lock:
            if self._task is task:
                self._running = False
                self._release_completed_self_stop_unlocked()

    def _release_completed_self_stop_unlocked(self) -> None:
        """Release retained hook ownership once the self-stopped loop exits."""
        if (
            not self._cleanup_required
            or self._stop_failed
            or self._stop_request_count
            or self._start_hook_task is not None
            or self.strategy.state != StrategyState.STOPPED
        ):
            return
        stop_hook = self._stop_hook_task
        if stop_hook is not None:
            if not stop_hook.done() or stop_hook.cancelled() or stop_hook.exception() is not None:
                return
            self._stop_hook_task = None
            self._stop_hook_worker_active = None
        self._cleanup_required = False

    async def _run_loop(self) -> None:
        """Main tick loop — runs until stopped or market closes."""
        try:
            while self._running:
                if self.strategy.state == StrategyState.PAUSED:
                    await asyncio.sleep(self.tick_interval)
                    continue
                if self.strategy.state != StrategyState.ACTIVE:
                    break
                try:
                    await self._tick()
                except asyncio.CancelledError:
                    break
                except Exception as exc:
                    logger.error("StrategyRunner tick error for %s: %s", self.strategy.name, exc)
                    self.strategy.set_error(str(exc))
                    break

                if not self._running or self.strategy.state != StrategyState.ACTIVE:
                    break
                await asyncio.sleep(self.tick_interval)
        finally:
            with self._ownership_lock:
                if asyncio.current_task() is self._task:
                    self._running = False
                    self._release_completed_self_stop_unlocked()

    async def _tick(self) -> None:
        """Single tick iteration."""
        exchange = self.strategy.exchange

        # Skip if market is closed
        if not self.scheduler.is_market_open(exchange, symbol=self.symbol):
            return

        # NOTE: is_deploy_frozen() guards code *deployment*, not tick delivery.
        # Strategies must receive ticks during market hours regardless of
        # whether a deployment freeze is active. Do not gate ticks here.

        # Check auto square-off
        if self.scheduler.should_square_off(exchange, symbol=self.symbol):
            await self._handle_square_off()
            return

        # Fetch live quote
        quote = await get_latest_quote(self.client, self.symbol, exchange)
        if quote is None:
            return

        # Deliver tick to strategy
        await self._invoke_strategy_callback(lambda: self.strategy.on_tick(quote))
        self._tick_count += 1

    async def _invoke_strategy_callback(self, callback: Callable[[], Any]) -> Any:
        """Invoke user strategy code under an invalidatable tick-generation lease."""
        lease = _StrategyExecutionLease(runner=self, task=self._task)
        ownership_token = _CURRENT_STRATEGY_LEASE.set(lease)
        try:
            return await _await_if_needed(callback())
        finally:
            lease.active = False
            _CURRENT_STRATEGY_LEASE.reset(ownership_token)

    async def _handle_square_off(self) -> None:
        """Trigger auto square-off and stop the runner."""
        logger.warning(
            "AUTO_SQUARE_OFF triggered for %s at %s",
            self.strategy.name,
            datetime.now(IST).strftime("%H:%M:%S IST"),
        )

        # Call on_square_off if the strategy implements it
        if hasattr(self.strategy, "on_square_off") and callable(self.strategy.on_square_off):
            try:
                await self._invoke_strategy_callback(self.strategy.on_square_off)
            except Exception as exc:
                logger.error("on_square_off failed for %s: %s", self.strategy.name, exc)

        with self._ownership_lock:
            self._running = False
            self._cleanup_required = True
        stop_hook, worker_active = self._get_or_create_stop_hook()
        try:
            if not stop_hook.done():
                await self._wait_for_task(
                    stop_hook,
                    label="stop hook",
                    cancel_on_timeout=True,
                    worker_active=worker_active,
                )
        except Exception:
            with self._ownership_lock:
                self._stop_failed = True
            raise
        else:
            with self._ownership_lock:
                task = self._task
                self_stop_handoff = bool(task is asyncio.current_task() and task is not None and not task.done())
                if self._stop_hook_task is stop_hook and not self_stop_handoff:
                    self._stop_hook_task = None
                    self._stop_hook_worker_active = None
                self._cleanup_required = self_stop_handoff
                self._quarantined = False
                self._stop_failed = False


# ---------------------------------------------------------------------------
# StrategyScheduler — multi-strategy lifecycle management
# ---------------------------------------------------------------------------


class StrategyScheduler:
    """Manages multiple StrategyRunners.

    Usage::

        sched = StrategyScheduler(client=client)
        runner = sched.register(my_strategy, tick_interval=1.0)
        await sched.start_all()
        ...
        await sched.stop_all()
    """

    def __init__(
        self,
        client: OpenAlgoClient | None = None,
        time_scheduler: TimeScheduler | None = None,
    ) -> None:
        self.client = client
        self.time_scheduler = time_scheduler or TimeScheduler(client=client)
        self._runners: dict[str, StrategyRunner] = {}
        self._owned_runners: list[StrategyRunner] = []
        self._runner_lock = threading.RLock()
        self._scheduler_transition_lock = asyncio.Lock()
        self._aggregate_stop_active = False
        self._aggregate_stop_generation = 0
        self._runtime_loop: asyncio.AbstractEventLoop | None = None
        self._runtime_call_timeout = 35.0
        self._pending_stop_submissions: set[Any] = set()

    def register(
        self,
        strategy: BaseStrategy,
        client: OpenAlgoClient | None = None,
        tick_interval: float = 1.0,
        symbol: str = "",
    ) -> StrategyRunner:
        """Register a strategy and create its runner."""
        runner = StrategyRunner(
            strategy=strategy,
            client=client or self.client,
            scheduler=self.time_scheduler,
            tick_interval_seconds=tick_interval,
            symbol=symbol,
            start_generation_provider=self._admit_runner_start,
        )
        with self._runner_lock:
            existing = self._runners.get(strategy.name)
            if existing is not None:
                try:
                    existing._retire()
                except RuntimeError as exc:
                    raise RuntimeError(f"Strategy runner '{strategy.name}' is already active") from exc
                self._owned_runners = [
                    owned_runner for owned_runner in self._owned_runners if owned_runner is not existing
                ]
            self._runners[strategy.name] = runner
            self._owned_runners.append(runner)
        logger.info("Registered strategy runner: %s", strategy.name)
        return runner

    def _admit_runner_start(self) -> int:
        """Admit a registered runner start outside aggregate-stop generations."""
        with self._runner_lock:
            if self._aggregate_stop_active:
                raise RuntimeError("Strategy cannot start during an aggregate stop")
            return self._aggregate_stop_generation

    def bind_runtime_loop(self, loop: asyncio.AbstractEventLoop) -> None:
        """Bind synchronous route submissions to one long-lived event loop."""
        if loop.is_closed() or not loop.is_running():
            raise RuntimeError("Strategy runtime loop is not running")
        current = self._runtime_loop
        if current is not None and current is not loop and current.is_running():
            raise RuntimeError("Strategy scheduler is already bound to another runtime loop")
        self._runtime_loop = loop

    async def start_one(self, strategy_name: str) -> None:
        """Start one registered runner."""
        with self._runner_lock:
            runner = self._runners.get(strategy_name)
        if runner is None:
            raise KeyError(f"No runner registered for '{strategy_name}'")
        await self._start_registered_runner(
            strategy_name,
            runner,
            _RevocableStartRequest(),
        )

    async def _start_registered_runner(
        self,
        strategy_name: str,
        runner: StrategyRunner,
        request: _RevocableStartRequest,
    ) -> None:
        """Start one exact runner generation and roll back every failed attempt."""
        with self._runner_lock:
            if self._aggregate_stop_active:
                raise RuntimeError("Strategy cannot start during an aggregate stop")
            expected_generation = self._aggregate_stop_generation
        async with self._scheduler_transition_lock:
            await self._start_registered_runner_under_transition(
                strategy_name,
                runner,
                request,
                expected_generation=expected_generation,
            )

    async def _start_registered_runner_under_transition(
        self,
        strategy_name: str,
        runner: StrategyRunner,
        request: _RevocableStartRequest,
        *,
        expected_generation: int,
    ) -> None:
        """Start one exact runner while the scheduler transition lock is held."""
        with self._runner_lock:
            if self._aggregate_stop_active or self._aggregate_stop_generation != expected_generation:
                raise RuntimeError("Strategy start was superseded by an aggregate stop")
            current_runner = self._runners.get(strategy_name)
        if current_runner is not runner:
            raise RuntimeError("Strategy runner generation changed before start")
        if request.revoked:
            raise StrategyStartTimeoutError("Strategy start was revoked before admission")
        try:
            await runner.start()
            if request.revoked:
                raise StrategyStartTimeoutError("Strategy start was revoked before activation")
        except BaseException as exc:
            unresolved = await self._drain_runners_to_terminal((runner,))
            if unresolved:
                exc.add_note(
                    "Lifecycle ownership remains quarantined for: "
                    + ", ".join(owned.strategy.name for owned in unresolved)
                )
            raise

    @staticmethod
    def _terminal_drain_timeout(runner: StrategyRunner) -> float:
        """Return a bounded cleanup window scaled to the runner hook timeout."""
        return min(
            _MAX_TERMINAL_DRAIN_SECONDS,
            max(_MIN_TERMINAL_DRAIN_SECONDS, runner.lifecycle_timeout * 2),
        )

    @classmethod
    async def _drain_failed_start(
        cls,
        runner: StrategyRunner,
        *,
        timeout: float | None = None,
    ) -> bool:
        """Retry cleanup within a deadline while retaining unresolved ownership."""
        cleanup_timeout = cls._terminal_drain_timeout(runner) if timeout is None else max(0.0, timeout)
        deadline = asyncio.get_running_loop().time() + cleanup_timeout
        attempts = 0
        while runner.has_live_owner:
            remaining = deadline - asyncio.get_running_loop().time()
            if remaining <= 0:
                with runner._ownership_lock:
                    runner._quarantined = True
                logger.error(
                    "Strategy lifecycle remains quarantined after bounded rollback: %s",
                    runner.strategy.name,
                )
                return False
            attempts += 1
            try:
                async with asyncio.timeout(remaining):
                    await runner.stop()
            except BaseException as exc:  # noqa: BLE001 - failure cannot be reported before ownership is gone
                if attempts == 1 or attempts % 10 == 0:
                    logger.warning(
                        "Strategy start rollback still pending for %s after %d attempt(s): %s",
                        runner.strategy.name,
                        attempts,
                        type(exc).__name__,
                    )
            remaining = deadline - asyncio.get_running_loop().time()
            if runner.has_live_owner and remaining > 0:
                await asyncio.sleep(min(0.01, remaining))
        return True

    @classmethod
    async def _drain_runners_to_terminal(
        cls,
        runners: tuple[StrategyRunner, ...],
    ) -> tuple[StrategyRunner, ...]:
        """Shield concurrent bounded cleanup and return retained owners."""
        if not runners:
            return ()

        async def drain() -> tuple[StrategyRunner, ...]:
            outcomes = await asyncio.gather(
                *(
                    cls._drain_failed_start(
                        runner,
                        timeout=cls._terminal_drain_timeout(runner),
                    )
                    for runner in runners
                )
            )
            return tuple(runner for runner, terminal in zip(runners, outcomes, strict=True) if not terminal)

        cleanup_task = asyncio.create_task(drain())
        while True:
            try:
                return await asyncio.shield(cleanup_task)
            except asyncio.CancelledError:
                # The caller's original outcome is re-raised by its enclosing
                # failure path after this task reaches a terminal ownership state.
                continue

    def start_one_threadsafe(self, strategy_name: str) -> None:
        """Start one runner, revoking and draining it before timeout failure."""
        loop = self._require_runtime_loop()
        with self._runner_lock:
            runner = self._runners.get(strategy_name)
        if runner is None:
            raise KeyError(f"No runner registered for '{strategy_name}'")

        request = _RevocableStartRequest()
        future = asyncio.run_coroutine_threadsafe(
            self._start_registered_runner(strategy_name, runner, request),
            loop,
        )
        try:
            future.result(timeout=self._runtime_call_timeout)
        except TimeoutError as exc:
            if _future_stored_exception_is(future, exc):
                raise
            request.revoke()
            try:
                future.result(timeout=self._terminal_drain_timeout(runner))
            except TimeoutError:
                future.cancel()
            except BaseException:
                pass

            rollback = asyncio.run_coroutine_threadsafe(
                self._drain_failed_start(runner),
                loop,
            )
            terminal = False
            try:
                terminal = bool(
                    rollback.result(timeout=self._terminal_drain_timeout(runner) + 0.25)
                )
            except TimeoutError:
                with runner._ownership_lock:
                    runner._quarantined = True
            outcome = "was rolled back" if terminal else "remains quarantined"
            raise StrategyStartTimeoutError(f"Strategy '{strategy_name}' start timed out and {outcome}") from exc

    def stop_one_threadsafe(self, strategy_name: str) -> None:
        """Stop one runner on the scheduler's bound runtime loop."""
        self._run_threadsafe(
            lambda: self.stop_one(strategy_name),
            timeout_message=f"Strategy '{strategy_name}' stop is still in progress",
        )

    def stop_all_threadsafe(self) -> None:
        """Stop all runners on the scheduler's bound runtime loop."""
        self._run_threadsafe(
            self.stop_all,
            timeout_message="Strategy shutdown is still in progress",
        )

    def _run_threadsafe(self, operation: Callable[[], Any], *, timeout_message: str) -> None:
        """Submit owned stop work and bound only the synchronous caller's wait."""
        loop = self._require_runtime_loop()

        future = asyncio.run_coroutine_threadsafe(operation(), loop)
        with self._runner_lock:
            self._pending_stop_submissions.add(future)

        def release_submission(completed: Any) -> None:
            with self._runner_lock:
                self._pending_stop_submissions.discard(completed)

        future.add_done_callback(release_submission)
        try:
            future.result(timeout=self._runtime_call_timeout)
        except TimeoutError as exc:
            if _future_stored_exception_is(future, exc):
                raise
            # ``Future.result(timeout=...)`` does not cancel the owner-loop task.
            # Keep the submission retained until its done callback confirms that
            # cleanup has reached a final state.
            raise StrategyStopTimeoutError(timeout_message) from exc

    def _require_runtime_loop(self) -> asyncio.AbstractEventLoop:
        """Return the bound owner loop when synchronous submission is safe."""
        loop = self._runtime_loop
        if loop is None or loop.is_closed() or not loop.is_running():
            raise RuntimeError("Strategy runtime loop is not available")
        try:
            caller_loop = asyncio.get_running_loop()
        except RuntimeError:
            caller_loop = None
        if caller_loop is loop:
            raise RuntimeError("Synchronous strategy submission cannot run on its owner loop")
        return loop

    async def start_all(self) -> None:
        """Start every exact runner generation or roll the aggregate back."""
        with self._runner_lock:
            if self._aggregate_stop_active:
                raise RuntimeError("Strategies cannot start during an aggregate stop")
            expected_generation = self._aggregate_stop_generation
            runners = tuple(self._runners.items())
        started: list[StrategyRunner] = []
        async with self._scheduler_transition_lock:
            try:
                for name, runner in runners:
                    already_owned = runner.has_live_owner
                    await self._start_registered_runner_under_transition(
                        name,
                        runner,
                        _RevocableStartRequest(),
                        expected_generation=expected_generation,
                    )
                    if not already_owned and runner.has_live_owner:
                        started.append(runner)
            except BaseException as exc:
                unresolved = await self._drain_runners_to_terminal(tuple(reversed(started)))
                if unresolved:
                    exc.add_note(
                        "Lifecycle ownership remains quarantined for: "
                        + ", ".join(owned.strategy.name for owned in unresolved)
                    )
                raise

    async def stop_all(self) -> None:
        """Stop every registered runner and report any failures together."""
        errors: list[Exception] = []
        async with self._scheduler_transition_lock:
            with self._runner_lock:
                self._aggregate_stop_active = True
                self._aggregate_stop_generation += 1
                runners: list[tuple[str, StrategyRunner]] = []
                seen: set[int] = set()
                for runner in self._owned_runners:
                    runners.append((runner.strategy.name, runner))
                    seen.add(id(runner))
                for name, runner in self._runners.items():
                    if id(runner) not in seen:
                        runners.append((name, runner))
            stop_tasks = [asyncio.create_task(runner.stop()) for _name, runner in runners]
            stop_group = asyncio.gather(*stop_tasks, return_exceptions=True)
            cancellation: asyncio.CancelledError | None = None
            try:
                while True:
                    try:
                        results = await asyncio.shield(stop_group)
                        break
                    except asyncio.CancelledError as exc:
                        cancellation = exc
            finally:
                with self._runner_lock:
                    self._aggregate_stop_active = False
            for (name, _runner), result in zip(runners, results, strict=True):
                if isinstance(result, BaseException):
                    logger.error(
                        "Failed to stop strategy runner %s: %s",
                        name,
                        type(result).__name__,
                    )
                    if isinstance(result, Exception):
                        errors.append(result)
                    else:
                        errors.append(RuntimeError(f"Strategy runner {name} stop was cancelled"))
        if cancellation is not None:
            if errors:
                raise cancellation from ExceptionGroup("Strategy cleanup failed during cancellation", errors)
            raise cancellation
        if errors:
            raise ExceptionGroup("One or more strategy runners failed to stop", errors)

    async def stop_one(self, strategy_name: str) -> None:
        """Stop a single runner by strategy name."""
        async with self._scheduler_transition_lock:
            runner = self._runners.get(strategy_name)
            if runner:
                await runner.stop()
            else:
                raise KeyError(f"No runner registered for '{strategy_name}'")

    def get_runner(self, strategy_name: str) -> StrategyRunner | None:
        """Get a runner by strategy name."""
        return self._runners.get(strategy_name)

    def status(self) -> dict[str, dict[str, Any]]:
        """Return status of all registered runners."""
        result: dict[str, dict[str, Any]] = {}
        for name, runner in self._runners.items():
            result[name] = {
                "state": runner.strategy.state.value,
                "is_running": runner.is_running,
                "exchange": runner.strategy.exchange,
                "tick_count": runner.tick_count,
                "quarantined": runner.is_quarantined,
            }
        return result


# ---------------------------------------------------------------------------
# CronScheduleConfig — per-job metadata
# ---------------------------------------------------------------------------


def _translate_standard_cron_weekdays(expression: str) -> str:
    """Translate Sunday-zero cron weekdays to APScheduler's Monday-zero form.

    Named weekdays already have the same meaning in both formats. Numeric
    terms are expanded before translation so Sunday-containing ranges and
    stepped expressions retain their standard cron semantics.
    """
    if expression == "*":
        return expression

    translated_terms: list[str] = []
    for term in expression.split(","):
        if any(character.isalpha() for character in term):
            translated_terms.append(term)
            continue

        base, separator, raw_step = term.partition("/")
        try:
            step = int(raw_step) if separator else 1
        except ValueError as exc:
            raise ValueError(f"Invalid cron weekday step {raw_step!r}") from exc
        if step <= 0:
            raise ValueError("Cron weekday step must be positive")

        if base == "*":
            standard_days = list(range(0, 7, step))
        elif "-" in base:
            raw_start, raw_end = base.split("-", 1)
            try:
                start, end = int(raw_start), int(raw_end)
            except ValueError as exc:
                raise ValueError(f"Invalid numeric cron weekday term {term!r}") from exc
            if start > end:
                raise ValueError(f"Invalid descending cron weekday range {base!r}")
            standard_days = list(range(start, end + 1, step))
        else:
            try:
                start = int(base)
            except ValueError as exc:
                raise ValueError(f"Invalid numeric cron weekday term {term!r}") from exc
            end = 7 if separator else start
            standard_days = list(range(start, end + 1, step))

        if not standard_days or any(day < 0 or day > 7 for day in standard_days):
            raise ValueError(f"Cron weekday values must be between 0 and 7: {term!r}")

        apscheduler_days: list[int] = []
        for day in standard_days:
            translated = 6 if day in {0, 7} else day - 1
            if translated not in apscheduler_days:
                apscheduler_days.append(translated)

        if (
            len(apscheduler_days) > 1
            and not separator
            and apscheduler_days == list(range(apscheduler_days[0], apscheduler_days[-1] + 1))
        ):
            translated_terms.append(f"{apscheduler_days[0]}-{apscheduler_days[-1]}")
        else:
            translated_terms.append(",".join(str(day) for day in apscheduler_days))

    return ",".join(translated_terms)


@dataclass
class CronScheduleConfig:
    """Metadata for a cron-scheduled strategy callback.

    Attributes:
        strategy_id: Unique identifier for the strategy.
        cron_expr: Standard 5-field cron expression (minute hour dom month dow).
            E.g. ``"30 9 * * 1-5"`` = 09:30 IST on weekdays.
        exchange: Exchange code used for market-hours and holiday gating.
        symbol: Optional instrument symbol used by symbol-scoped sessions.
        generation: Monotonic callback generation used to reject stale jobs.
        job_id: APScheduler job ID (set after scheduling).
        last_skipped_reason: Human-readable reason the last fire was skipped,
            or empty string if the last fire executed successfully.
    """

    strategy_id: str
    cron_expr: str
    exchange: str = "NSE"
    symbol: str = ""
    generation: int = field(default=0, repr=False)
    job_id: str = ""
    last_skipped_reason: str = field(default="")


# ---------------------------------------------------------------------------
# CronStrategyScheduler
# ---------------------------------------------------------------------------

# Pytz IST constant used by APScheduler (it requires a pytz timezone object
# when passed to BackgroundScheduler, unlike stdlib timezone).
_IST_PYTZ_NAME = "Asia/Kolkata"


class CronStrategyScheduler:
    """Schedule strategy callbacks using cron expressions with market-hours awareness.

    Each callback delegates market eligibility to its :class:`TimeScheduler`,
    including holidays, weekend special sessions, and dynamic trading hours.

    The underlying APScheduler ``BackgroundScheduler`` is initialised with the
    ``Asia/Kolkata`` timezone so that all ``CronTrigger`` expressions are
    evaluated in IST automatically.

    Usage::

        cron_sched = CronStrategyScheduler()
        cron_sched.start()

        job_id = cron_sched.schedule(
            strategy_id="my-strat",
            cron_expr="30 9 * * 1-5",
            callback=my_callback,
            exchange="NSE",
        )
        ...
        cron_sched.unschedule("my-strat")
        cron_sched.stop()
    """

    def __init__(
        self,
        time_scheduler: TimeScheduler | None = None,
        market_hours_check: bool = True,
    ) -> None:
        """Initialise the scheduler.

        Args:
            time_scheduler: An existing :class:`TimeScheduler` instance used for
                holiday and market-hours queries.  A new one is created if not
                provided.
            market_hours_check: When ``True`` (default), each cron fire is
                gated behind the market-hours / holiday check.  Set to ``False``
                only in unit tests that do not need the gate.
        """
        self._time_scheduler: TimeScheduler = time_scheduler or TimeScheduler()
        self._check_market = market_hours_check
        # strategy_id -> CronScheduleConfig
        self._schedules: dict[str, CronScheduleConfig] = {}
        self._callbacks: dict[str, Callable[[], None]] = {}
        self._next_generation = 0
        self._scheduler: Any = None  # APScheduler BackgroundScheduler
        self._running = False
        self._lifecycle_lock = threading.RLock()
        self._callback_condition = threading.Condition(self._lifecycle_lock)
        self._callbacks_in_flight = 0
        self._callbacks_in_flight_by_strategy: dict[str, int] = {}
        self._callbacks_in_flight_by_generation: dict[tuple[str, int], int] = {}
        self._retiring_generations: dict[tuple[str, int], CronScheduleConfig] = {}
        self._auto_release_retiring_generations: set[tuple[str, int]] = set()
        self._callback_context = threading.local()
        self._backend_shutdown_requested = False
        self._backend_auto_release = False

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    def start(self) -> None:
        """Start the underlying APScheduler background thread."""
        with self._lifecycle_lock:
            if self._running:
                return
            if self._scheduler is not None:
                raise RuntimeError("CronStrategyScheduler cannot restart until the previous backend stops")
            try:
                import pytz as _pytz  # pytz required by APScheduler for named TZ
                from apscheduler.schedulers.background import BackgroundScheduler

                self._scheduler = BackgroundScheduler(
                    timezone=_pytz.timezone(_IST_PYTZ_NAME),
                    daemon=True,
                )
                self._backend_shutdown_requested = False
            except ImportError as exc:
                raise ImportError("apscheduler and pytz are required — pip install apscheduler pytz") from exc

            start_attempted = False
            try:
                for strategy_id, config in self._schedules.items():
                    callback = self._callbacks.get(strategy_id)
                    if callback is None:
                        continue
                    config.job_id = self._add_apscheduler_job(
                        strategy_id,
                        self._parse_cron_expr(config.cron_expr),
                        callback,
                    )

                # Revoke queued callbacks before shutdown by flipping this flag
                # in stop(). Set it before start() so an immediately due job is
                # valid once the lifecycle lock is released.
                self._running = True
                start_attempted = True
                self._scheduler.start()
            except Exception:
                self._running = False
                backend = self._scheduler
                if backend is not None and start_attempted:
                    try:
                        backend.shutdown(wait=False)
                    except Exception:
                        logger.exception("CronStrategyScheduler startup rollback failed")
                    else:
                        self._scheduler = None
                        self._backend_shutdown_requested = False
                elif not start_attempted:
                    self._scheduler = None
                    self._backend_shutdown_requested = False
                raise
        logger.info("CronStrategyScheduler started (IST)")

    def stop(self, *, timeout: float = 30.0) -> None:
        """Revoke queued jobs and wait for every admitted callback to finish."""
        deadline = _time.monotonic() + max(0.0, float(timeout))
        with self._callback_condition:
            backend = self._scheduler
            if backend is None:
                self._running = False
                self._backend_auto_release = False
                return
            # APScheduler may already have submitted a callback to its worker
            # pool. Revoke it before asking the backend to stop. The backend
            # remains owned if shutdown raises, allowing a later stop retry and
            # preventing start() from orphaning a live scheduler thread.
            self._running = False
            if not self._backend_shutdown_requested:
                try:
                    backend.shutdown(wait=False)
                except Exception:
                    self._backend_shutdown_requested = False
                    raise
                self._backend_shutdown_requested = True
            own_callbacks = len(getattr(self._callback_context, "generation_stack", ()))
            if own_callbacks:
                self._backend_auto_release = True
                logger.info("CronStrategyScheduler stop deferred until admitted callbacks return")
                return
            while self._callbacks_in_flight > own_callbacks:
                remaining = deadline - _time.monotonic()
                if remaining <= 0:
                    raise RuntimeError("CronStrategyScheduler callbacks did not stop before the deadline")
                self._callback_condition.wait(timeout=remaining)
            self._scheduler = None
            self._backend_shutdown_requested = False
            self._backend_auto_release = False
            logger.info("CronStrategyScheduler stopped")

    @property
    def running(self) -> bool:
        """True if the background scheduler thread is active."""
        with self._lifecycle_lock:
            return self._running

    @property
    def time_scheduler(self) -> TimeScheduler:
        """Return the shared market-calendar owner used by cron gates."""
        return self._time_scheduler

    # ------------------------------------------------------------------
    # Schedule / unschedule
    # ------------------------------------------------------------------

    def schedule(
        self,
        strategy_id: str,
        cron_expr: str,
        callback: Callable[[], None],
        exchange: str = "NSE",
        symbol: str = "",
    ) -> str:
        """Register a strategy callback on a cron expression.

        The callback is wrapped with a market-hours gate that silently skips
        execution whenever the effective exchange session is closed.

        Args:
            strategy_id: Unique identifier for the strategy.  Used as the
                APScheduler job ID prefix, so it must be a valid non-empty string.
            cron_expr: Standard 5-field cron expression evaluated in IST.
                Example: ``"30 9 * * 1-5"`` → 09:30 every weekday.
            callback: Zero-argument callable to invoke when the cron fires.
            exchange: Exchange code (``"NSE"``, ``"MCX"``, etc.) used to look
                up trading hours and holidays for gating.
            symbol: Optional instrument symbol for symbol-scoped sessions.

        Returns:
            The APScheduler job ID string.

        Raises:
            ValueError: If the strategy ID or cron expression is invalid.
            ImportError: If APScheduler or pytz is unavailable.
        """
        if not strategy_id:
            raise ValueError("strategy_id must be a non-empty string")

        cron_parts = self._parse_cron_expr(cron_expr)
        # Parse every field with APScheduler before touching the active maps.
        # A five-field expression can still be invalid (for example minute 99).
        self._build_cron_trigger(cron_parts)

        with self._lifecycle_lock:
            if any(retiring_strategy_id == strategy_id for retiring_strategy_id, _ in self._retiring_generations):
                raise RuntimeError(f"Strategy '{strategy_id}' still has a retiring generation")
            generation = self._next_generation + 1
            self._next_generation = generation

            config = CronScheduleConfig(
                strategy_id=strategy_id,
                cron_expr=cron_expr,
                exchange=exchange.upper(),
                symbol=symbol.strip().upper(),
                generation=generation,
            )
            wrapped = self._make_gated_callback(
                strategy_id,
                callback,
                config,
                generation=generation,
            )
            previous_config = self._schedules.get(strategy_id)

            if self._running and self._scheduler is not None:
                # APScheduler's replace_existing operation and the in-memory
                # commit are one serialised lifecycle transaction. If the
                # backend rejects the replacement, the old maps remain intact.
                job_id = self._add_apscheduler_job(strategy_id, cron_parts, wrapped)
                config.job_id = job_id
            else:
                # Scheduler not started yet — store for deferred registration.
                # job_id will be assigned once start() is called.
                config.job_id = f"pending:{strategy_id}"

            self._schedules[strategy_id] = config
            self._callbacks[strategy_id] = wrapped
            if previous_config is not None:
                previous_key = (strategy_id, previous_config.generation)
                if self._callbacks_in_flight_by_generation.get(previous_key, 0):
                    self._retiring_generations[previous_key] = previous_config
                    self._auto_release_retiring_generations.add(previous_key)

        logger.info(
            "Scheduled strategy '%s' with cron '%s' on %s (job_id=%s)",
            strategy_id,
            cron_expr,
            exchange,
            config.job_id,
        )
        return config.job_id

    def unschedule(self, strategy_id: str, *, timeout: float = 30.0) -> bool:
        """Remove the cron schedule for a strategy.

        Args:
            strategy_id: The strategy to unschedule.

        Returns:
            ``True`` if the schedule existed and was removed, ``False``
            if no schedule was found for this strategy.
        """
        deadline = _time.monotonic() + max(0.0, float(timeout))
        with self._callback_condition:
            config = self._schedules.pop(strategy_id, None)
            retirement_keys = {key for key in self._retiring_generations if key[0] == strategy_id}
            if config is None and not retirement_keys:
                return False
            if config is not None:
                self._callbacks.pop(strategy_id, None)
                retirement_key = (strategy_id, config.generation)
                self._retiring_generations[retirement_key] = config
                retirement_keys.add(retirement_key)

                if self._running and self._scheduler is not None and config.job_id:
                    try:
                        self._scheduler.remove_job(config.job_id)
                    except Exception:
                        logger.debug(
                            "APScheduler job '%s' not found during removal",
                            config.job_id,
                        )

            current_stack = tuple(getattr(self._callback_context, "generation_stack", ()))
            own_counts = {key: current_stack.count(key) for key in retirement_keys}
            for key, own_count in own_counts.items():
                if own_count:
                    self._auto_release_retiring_generations.add(key)

            while any(
                self._callbacks_in_flight_by_generation.get(key, 0) > own_counts.get(key, 0) for key in retirement_keys
            ):
                remaining = deadline - _time.monotonic()
                if remaining <= 0:
                    raise RuntimeError(f"Cron callback for strategy '{strategy_id}' did not stop before the deadline")
                self._callback_condition.wait(timeout=remaining)

            for key in retirement_keys:
                if not self._callbacks_in_flight_by_generation.get(key, 0):
                    self._retiring_generations.pop(key, None)
                    self._auto_release_retiring_generations.discard(key)

        logger.info("Unscheduled strategy '%s'", strategy_id)
        return True

    # ------------------------------------------------------------------
    # Introspection
    # ------------------------------------------------------------------

    def list_jobs(self) -> list[dict[str, Any]]:
        """Return a list of all scheduled jobs with metadata.

        Returns:
            List of dicts with keys: ``strategy_id``, ``cron_expr``,
            ``exchange``, ``symbol``, ``job_id``, ``last_skipped_reason``,
            ``next_fire_time`` (ISO string or empty).
        """
        with self._lifecycle_lock:
            result: list[dict[str, Any]] = []
            for sid, cfg in self._schedules.items():
                next_fire = ""
                if self._running and self._scheduler is not None and cfg.job_id:
                    try:
                        job = self._scheduler.get_job(cfg.job_id)
                        if job and job.next_run_time:
                            next_fire = job.next_run_time.isoformat()
                    except Exception:
                        pass
                result.append(
                    {
                        "strategy_id": sid,
                        "cron_expr": cfg.cron_expr,
                        "exchange": cfg.exchange,
                        "symbol": cfg.symbol,
                        "job_id": cfg.job_id,
                        "last_skipped_reason": cfg.last_skipped_reason,
                        "next_fire_time": next_fire,
                    }
                )
            return result

    def get_schedule(self, strategy_id: str) -> CronScheduleConfig | None:
        """Return the schedule config for a strategy, or None."""
        with self._lifecycle_lock:
            return self._schedules.get(strategy_id)

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _parse_cron_expr(cron_expr: str) -> dict[str, str]:
        """Parse a 5-field cron expression into APScheduler CronTrigger kwargs.

        Args:
            cron_expr: Space-separated string with fields:
                ``minute hour day_of_month month day_of_week``.

        Returns:
            Dict with keys ``minute``, ``hour``, ``day``, ``month``,
            ``day_of_week`` suitable for ``CronTrigger(**parts)``.

        Raises:
            ValueError: If the expression does not have exactly 5 fields.
        """
        parts = cron_expr.strip().split()
        if len(parts) != 5:
            raise ValueError(
                f"Invalid cron expression {cron_expr!r}: expected 5 fields "
                f"(minute hour dom month dow), got {len(parts)}"
            )
        minute, hour, dom, month, dow = parts
        return {
            "minute": minute,
            "hour": hour,
            "day": dom,
            "month": month,
            "day_of_week": _translate_standard_cron_weekdays(dow),
        }

    def _make_gated_callback(
        self,
        strategy_id: str,
        callback: Callable[[], None],
        config: CronScheduleConfig,
        *,
        generation: int | None = None,
    ) -> Callable[[], None]:
        """Wrap ``callback`` with market-hours / holiday gate logic.

        The gate logic (in order):

        1. If :attr:`_check_market` is ``False`` — always execute (test bypass).
        2. Ask the canonical :class:`TimeScheduler` whether the exchange is open.
        3. If closed, derive a useful skip reason from that scheduler's session.
        """
        time_scheduler = self._time_scheduler

        def is_current_generation() -> bool:
            if generation is not None:
                active = self._schedules.get(strategy_id)
                if not self._running or active is not config or active.generation != generation:
                    logger.debug(
                        "Cron skip [%s]: stale or stopped generation %d",
                        strategy_id,
                        generation,
                    )
                    return False
            return True

        def run_gated() -> None:
            if not self._check_market:
                callback()
                return

            now_ist = time_scheduler.now_ist()
            today = now_ist.date()
            exchange = config.exchange
            symbol = config.symbol or None
            sched = EXCHANGE_SCHEDULES.get(exchange)
            if not time_scheduler.is_market_open(
                exchange,
                at=now_ist,
                symbol=symbol,
            ):
                session = time_scheduler.get_market_session(
                    exchange,
                    on=today,
                    symbol=symbol,
                )
                if sched is None:
                    reason = f"unknown exchange {exchange!r}"
                elif session is None and today.weekday() >= 5:
                    reason = f"weekend ({today.strftime('%A')})"
                elif session is None:
                    reason = f"market holiday on {today.isoformat()}"
                else:
                    open_t, close_t = session
                    now_t = now_ist.time().replace(tzinfo=None)
                    reason = (
                        f"outside market hours for {exchange} "
                        f"({open_t.strftime('%H:%M:%S')}-{close_t.strftime('%H:%M:%S')} IST), "
                        f"current={now_t.strftime('%H:%M:%S')}"
                    )
                config.last_skipped_reason = reason
                logger.debug("Cron skip [%s]: %s", strategy_id, reason)
                return

            # All checks passed — execute
            config.last_skipped_reason = ""
            logger.info("Cron fire [%s] at %s IST", strategy_id, now_ist.strftime("%H:%M:%S"))
            try:
                callback()
            except Exception as exc:
                logger.error("Cron callback error [%s]: %s", strategy_id, exc)

        def gated() -> None:
            # Admission is serialised with stop/unschedule/replacement, but the
            # user callback runs outside the lifecycle lock. stop() revokes
            # callbacks that have not reached this point and waits for every
            # callback admitted here before releasing backend ownership.
            with self._callback_condition:
                while True:
                    if not is_current_generation():
                        return
                    predecessor_in_flight = any(
                        retired_strategy_id == strategy_id
                        and retired_generation != generation
                        and self._callbacks_in_flight_by_generation.get(
                            (retired_strategy_id, retired_generation),
                            0,
                        )
                        for retired_strategy_id, retired_generation in self._retiring_generations
                    )
                    if not predecessor_in_flight:
                        break
                    self._callback_condition.wait()
                callback_generation = config.generation if generation is None else generation
                generation_key = (strategy_id, callback_generation)
                self._callbacks_in_flight += 1
                self._callbacks_in_flight_by_strategy[strategy_id] = (
                    self._callbacks_in_flight_by_strategy.get(strategy_id, 0) + 1
                )
                self._callbacks_in_flight_by_generation[generation_key] = (
                    self._callbacks_in_flight_by_generation.get(generation_key, 0) + 1
                )
                generation_stack = getattr(self._callback_context, "generation_stack", None)
                if generation_stack is None:
                    generation_stack = []
                    self._callback_context.generation_stack = generation_stack
                generation_stack.append(generation_key)
            try:
                run_gated()
            finally:
                with self._callback_condition:
                    generation_stack.pop()
                    self._callbacks_in_flight -= 1
                    strategy_callbacks = self._callbacks_in_flight_by_strategy[strategy_id] - 1
                    if strategy_callbacks:
                        self._callbacks_in_flight_by_strategy[strategy_id] = strategy_callbacks
                    else:
                        self._callbacks_in_flight_by_strategy.pop(strategy_id, None)
                    generation_callbacks = self._callbacks_in_flight_by_generation[generation_key] - 1
                    if generation_callbacks:
                        self._callbacks_in_flight_by_generation[generation_key] = generation_callbacks
                    else:
                        self._callbacks_in_flight_by_generation.pop(generation_key, None)
                        if generation_key in self._auto_release_retiring_generations:
                            self._retiring_generations.pop(generation_key, None)
                            self._auto_release_retiring_generations.discard(generation_key)
                    self._callback_condition.notify_all()
                    if self._callbacks_in_flight == 0:
                        if self._backend_auto_release and not self._running and self._backend_shutdown_requested:
                            self._scheduler = None
                            self._backend_shutdown_requested = False
                            self._backend_auto_release = False
                        self._callback_condition.notify_all()

        return gated

    def _add_apscheduler_job(
        self,
        strategy_id: str,
        cron_parts: dict[str, str],
        wrapped_callback: Callable[[], None],
    ) -> str:
        """Register the wrapped callback with APScheduler.

        Args:
            strategy_id: Used as the job ID.
            cron_parts: Parsed fields from :meth:`_parse_cron_expr`.
            wrapped_callback: The market-gated callable.

        Returns:
            The job ID string used by APScheduler.
        """
        trigger = self._build_cron_trigger(cron_parts)
        job = self._scheduler.add_job(
            func=wrapped_callback,
            trigger=trigger,
            id=strategy_id,
            replace_existing=True,
        )
        return job.id

    @staticmethod
    def _build_cron_trigger(cron_parts: dict[str, str]) -> Any:
        """Build and validate an APScheduler cron trigger in IST."""
        import pytz as _pytz
        from apscheduler.triggers.cron import CronTrigger

        return CronTrigger(
            timezone=_pytz.timezone(_IST_PYTZ_NAME),
            **cron_parts,
        )
