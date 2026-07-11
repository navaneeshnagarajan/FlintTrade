"""Time scheduler + async strategy execution engine.

Query utilities: market hours, auto square-off, deploy freeze, holidays.
Execution: StrategyRunner (single strategy tick loop), StrategyScheduler (multi).
Cron scheduling: CronStrategyScheduler (APScheduler-based, IST-aware, market-gated).

All times are in IST (Asia/Kolkata, UTC+5:30).
"""

from __future__ import annotations

import asyncio
import logging
import math
from dataclasses import dataclass, field
from datetime import date, datetime, time, timedelta, timezone
from typing import Any, Callable

from flinttrade_core.models import Quote
from flinttrade_core.openalgo_client import OpenAlgoClient

from .strategy import BaseStrategy, StrategyState

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
        "GLOBAL_INDEX", time(0, 0), time(23, 59), time(23, 59), is_24x7=True,
    ),
}


# Deploy freeze windows per market segment — see docs/USER_GUIDE.md (Operations).
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
    "MCX": "mcx", "NCDEX": "mcx", "MCX_INDEX": "mcx", "NCO": "mcx",
    "DELTA": "crypto", "GLOBAL_INDEX": "crypto",
}

_CDS_CROSS_CURRENCY_UNDERLYINGS = ("EURUSD", "GBPUSD", "USDJPY")

_CALENDAR_EXCHANGE_ALIASES = {
    "NSE_INDEX": "NSE",
    "BSE_INDEX": "BSE",
    "MCX_INDEX": "MCX",
}


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
            parsed = datetime.fromisoformat(
                text[:-1] + "+00:00" if text.endswith(("Z", "z")) else text
            )
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
        return self._active_market_window(
            exchange,
            at=current,
            symbol=symbol,
        ) is not None

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
            exchange_sessions = [
                session
                for session in calendar_day.open_sessions
                if session.exchange == calendar_key
            ]
            matching_sessions = [
                session for session in exchange_sessions if session.matches(symbol)
            ]
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
        market_close = (
            time(19, 30)
            if exchange_key == "CDS" and _is_cds_cross_currency(symbol)
            else sched.market_close
        )
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
            )
            closes_at = session_midnight.replace(
                hour=market_close.hour,
                minute=market_close.minute,
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
            {int(year)}
            if year is not None
            else {date.fromisoformat(row["date"]).year for row in calendar_rows}
        )
        for holiday_date in tuple(self._calendar_days):
            if holiday_date.year in replacement_years:
                self._calendar_days.pop(holiday_date, None)
        for row in calendar_rows:
            holiday_date = date.fromisoformat(row["date"])
            calendar_day = self._calendar_days.setdefault(holiday_date, _CalendarDay())
            calendar_day.closed_exchanges.update(
                _calendar_exchange(exchange_name)
                for exchange_name in row["closed_exchanges"]
            )
            for raw_session in row["open_exchanges"]:
                session_exchange = _calendar_exchange(
                    str(raw_session.get("exchange") or "")
                )
                start = _calendar_time(raw_session.get("start_time"))
                end = _calendar_time(raw_session.get("end_time"))
                if start is None or end is None or end == start:
                    if session_exchange:
                        calendar_day.closed_exchanges.add(session_exchange)
                    continue
                symbols = {
                    str(raw_session.get("symbol") or "").strip().upper()
                }
                raw_symbols = raw_session.get("symbols", [])
                if isinstance(raw_symbols, list | tuple | set):
                    symbols.update(
                        str(symbol).strip().upper() for symbol in raw_symbols
                    )
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
            else:
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
    ) -> None:
        self.strategy = strategy
        self.client = client
        self.scheduler = scheduler or TimeScheduler()
        self.tick_interval = tick_interval_seconds
        self.symbol = symbol or strategy.name
        self._task: asyncio.Task[None] | None = None
        self._running = False
        self._tick_count = 0

    @property
    def is_running(self) -> bool:
        return self._running

    @property
    def tick_count(self) -> int:
        return self._tick_count

    async def start(self) -> None:
        """Start the strategy and begin the tick loop."""
        if self._running:
            return
        self.strategy.start()
        self._running = True
        self._task = asyncio.ensure_future(self._run_loop())
        logger.info("StrategyRunner started: %s on %s", self.strategy.name, self.strategy.exchange)

    async def stop(self) -> None:
        """Stop the strategy and cancel the tick loop."""
        self._running = False
        self.strategy.stop()
        if self._task and not self._task.done():
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
        self._task = None
        logger.info("StrategyRunner stopped: %s (ticks=%d)", self.strategy.name, self._tick_count)

    def pause(self) -> None:
        """Pause the strategy (loop continues but skips on_tick)."""
        self.strategy.pause()

    def resume(self) -> None:
        """Resume a paused strategy."""
        self.strategy.resume()

    async def _run_loop(self) -> None:
        """Main tick loop — runs until stopped or market closes."""
        while self._running and self.strategy.state == StrategyState.ACTIVE:
            try:
                await self._tick()
            except asyncio.CancelledError:
                break
            except Exception as exc:
                logger.error("StrategyRunner tick error for %s: %s", self.strategy.name, exc)
                self.strategy.set_error(str(exc))
                break

            await asyncio.sleep(self.tick_interval)

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
        self.strategy.on_tick(quote)
        self._tick_count += 1

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
                self.strategy.on_square_off()
            except Exception as exc:
                logger.error("on_square_off failed for %s: %s", self.strategy.name, exc)

        self._running = False
        self.strategy.stop()


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
        )
        self._runners[strategy.name] = runner
        logger.info("Registered strategy runner: %s", strategy.name)
        return runner

    async def start_all(self) -> None:
        """Start all registered runners."""
        for runner in self._runners.values():
            await runner.start()

    async def stop_all(self) -> None:
        """Stop all registered runners."""
        for runner in self._runners.values():
            await runner.stop()

    async def stop_one(self, strategy_name: str) -> None:
        """Stop a single runner by strategy name."""
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
            }
        return result


# ---------------------------------------------------------------------------
# CronScheduleConfig — per-job metadata
# ---------------------------------------------------------------------------


@dataclass
class CronScheduleConfig:
    """Metadata for a cron-scheduled strategy callback.

    Attributes:
        strategy_id: Unique identifier for the strategy.
        cron_expr: Standard 5-field cron expression (minute hour dom month dow).
            E.g. ``"30 9 * * 1-5"`` = 09:30 IST on weekdays.
        exchange: Exchange code used for market-hours and holiday gating.
        job_id: APScheduler job ID (set after scheduling).
        last_skipped_reason: Human-readable reason the last fire was skipped,
            or empty string if the last fire executed successfully.
    """

    strategy_id: str
    cron_expr: str
    exchange: str = "NSE"
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
        self._scheduler: Any = None  # APScheduler BackgroundScheduler
        self._running = False

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    def start(self) -> None:
        """Start the underlying APScheduler background thread."""
        if self._running:
            return
        try:
            from apscheduler.schedulers.background import BackgroundScheduler
            import pytz as _pytz  # pytz required by APScheduler for named TZ
            self._scheduler = BackgroundScheduler(
                timezone=_pytz.timezone(_IST_PYTZ_NAME),
                daemon=True,
            )
        except ImportError as exc:
            raise ImportError(
                "apscheduler and pytz are required — pip install apscheduler pytz"
            ) from exc

        self._scheduler.start()
        self._running = True
        logger.info("CronStrategyScheduler started (IST)")

    def stop(self) -> None:
        """Shut down the background scheduler gracefully."""
        if self._scheduler and self._running:
            self._scheduler.shutdown(wait=False)
            self._running = False
            logger.info("CronStrategyScheduler stopped")

    @property
    def running(self) -> bool:
        """True if the background scheduler thread is active."""
        return self._running

    # ------------------------------------------------------------------
    # Schedule / unschedule
    # ------------------------------------------------------------------

    def schedule(
        self,
        strategy_id: str,
        cron_expr: str,
        callback: Callable[[], None],
        exchange: str = "NSE",
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

        Returns:
            The APScheduler job ID string.

        Raises:
            ValueError: If the cron expression cannot be parsed or the
                scheduler has not been started.
            RuntimeError: If the scheduler is not running — call :meth:`start`
                first, or use :meth:`schedule_lazy` to defer the APScheduler
                registration until :meth:`start` is called.
        """
        if not strategy_id:
            raise ValueError("strategy_id must be a non-empty string")

        _parts = self._parse_cron_expr(cron_expr)  # raises ValueError on bad expr

        config = CronScheduleConfig(
            strategy_id=strategy_id,
            cron_expr=cron_expr,
            exchange=exchange.upper(),
        )
        self._schedules[strategy_id] = config

        wrapped = self._make_gated_callback(strategy_id, callback, config)

        if self._running and self._scheduler is not None:
            job_id = self._add_apscheduler_job(strategy_id, _parts, wrapped)
            config.job_id = job_id
        else:
            # Scheduler not started yet — store for deferred registration.
            # job_id will be assigned once start() is called.
            config.job_id = f"pending:{strategy_id}"

        logger.info(
            "Scheduled strategy '%s' with cron '%s' on %s (job_id=%s)",
            strategy_id,
            cron_expr,
            exchange,
            config.job_id,
        )
        return config.job_id

    def unschedule(self, strategy_id: str) -> bool:
        """Remove the cron schedule for a strategy.

        Args:
            strategy_id: The strategy to unschedule.

        Returns:
            ``True`` if the schedule existed and was removed, ``False``
            if no schedule was found for this strategy.
        """
        config = self._schedules.pop(strategy_id, None)
        if config is None:
            return False

        if self._running and self._scheduler is not None and config.job_id:
            try:
                self._scheduler.remove_job(config.job_id)
            except Exception:
                logger.debug("APScheduler job '%s' not found during removal", config.job_id)

        logger.info("Unscheduled strategy '%s'", strategy_id)
        return True

    # ------------------------------------------------------------------
    # Introspection
    # ------------------------------------------------------------------

    def list_jobs(self) -> list[dict[str, Any]]:
        """Return a list of all scheduled jobs with metadata.

        Returns:
            List of dicts with keys: ``strategy_id``, ``cron_expr``,
            ``exchange``, ``job_id``, ``last_skipped_reason``,
            ``next_fire_time`` (ISO string or empty).
        """
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
                    "job_id": cfg.job_id,
                    "last_skipped_reason": cfg.last_skipped_reason,
                    "next_fire_time": next_fire,
                }
            )
        return result

    def get_schedule(self, strategy_id: str) -> CronScheduleConfig | None:
        """Return the schedule config for a strategy, or None."""
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
            "day_of_week": dow,
        }

    def _make_gated_callback(
        self,
        strategy_id: str,
        callback: Callable[[], None],
        config: CronScheduleConfig,
    ) -> Callable[[], None]:
        """Wrap ``callback`` with market-hours / holiday gate logic.

        The gate logic (in order):

        1. If :attr:`_check_market` is ``False`` — always execute (test bypass).
        2. Ask the canonical :class:`TimeScheduler` whether the exchange is open.
        3. If closed, derive a useful skip reason from that scheduler's session.
        """
        time_scheduler = self._time_scheduler

        def gated() -> None:
            if not self._check_market:
                callback()
                return

            now_ist = time_scheduler.now_ist()
            today = now_ist.date()
            exchange = config.exchange
            sched = EXCHANGE_SCHEDULES.get(exchange)
            if not time_scheduler.is_market_open(exchange, at=now_ist):
                session = time_scheduler.get_market_session(exchange, on=today)
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
                        f"({open_t.strftime('%H:%M')}-{close_t.strftime('%H:%M')} IST), "
                        f"current={now_t.strftime('%H:%M')}"
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
        from apscheduler.triggers.cron import CronTrigger
        import pytz as _pytz

        trigger = CronTrigger(
            timezone=_pytz.timezone(_IST_PYTZ_NAME),
            **cron_parts,
        )
        job = self._scheduler.add_job(
            func=wrapped_callback,
            trigger=trigger,
            id=strategy_id,
            replace_existing=True,
        )
        return job.id
