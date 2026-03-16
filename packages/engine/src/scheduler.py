"""Time scheduler + async strategy execution engine.

Query utilities: market hours, auto square-off, deploy freeze, holidays.
Execution: StrategyRunner (single strategy tick loop), StrategyScheduler (multi).

All times are in IST (Asia/Kolkata, UTC+5:30).
"""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta, timezone
from typing import Any

from packages.core.src.models import Quote
from packages.core.src.openalgo_client import OpenAlgoClient

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

        now = (at or self.now_ist()).time().replace(tzinfo=None)
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
        now_t = now.time().replace(tzinfo=None)
        if not (sched.market_open <= now_t <= sched.market_close):
            return None

        sq_dt = now.replace(
            hour=sched.square_off.hour,
            minute=sched.square_off.minute,
            second=0, microsecond=0,
        )
        remaining = sq_dt - now
        if hasattr(remaining, "total_seconds") and remaining.total_seconds() < 0:
            return timedelta(0)
        return remaining

    def should_square_off(self, exchange: str, at: datetime | None = None) -> bool:
        """True if current time is at or past the square-off time."""
        sched = EXCHANGE_SCHEDULES.get(exchange)
        if sched is None or sched.is_24x7:
            return False

        now_t = (at or self.now_ist()).time().replace(tzinfo=None)
        return now_t >= sched.square_off

    # ------------------------------------------------------------------
    # Deploy freeze
    # ------------------------------------------------------------------

    def is_deploy_frozen(self, exchanges: list[str] | None = None, at: datetime | None = None) -> bool:
        """Check if ANY of the given exchanges is in a deploy freeze window.

        If no exchanges given, checks equity window (default from CLAUDE.md).
        """
        now_t = (at or self.now_ist()).time().replace(tzinfo=None)
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
        if not self.scheduler.is_market_open(exchange):
            return

        # Skip if deploy is frozen (strategies should not fire during deploys)
        if self.scheduler.is_deploy_frozen([exchange]):
            return

        # Check auto square-off
        if self.scheduler.should_square_off(exchange):
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
