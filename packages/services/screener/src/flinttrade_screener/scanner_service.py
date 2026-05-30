"""Real-time scanner service — tick-driven candle building and multi-scanner dispatch.

Ticks arrive from the WebSocket stream (or any source), are aggregated into
1m / 5m / 15m OHLCV bars per symbol, and each completed bar is evaluated by
registered :class:`AbstractScanner` instances.  Matches are published to
asyncio queues or a user-supplied callback.

Design goals
------------
- 500+ symbols concurrently without hitting rate limits (all processing is
  in-process; no external I/O per tick)
- No hard Redis dependency — ``asyncio.Queue`` is the default transport;
  an optional Redis publisher can be plugged in later
- asyncio-compatible throughout; ``ScannerService`` is itself an async
  context manager

Usage::

    service = ScannerService()
    service.add_scanner(RSIScanner())
    service.add_scanner(EMACrossoverScanner())
    service.add_scanner(VolumeSpikeScanner())

    async with service:
        # Feed ticks from WebSocket
        await service.on_tick({"symbol": "NIFTY", "ltp": 22450.0, "volume": 123456})

    # Consume matches
    while not service.matches.empty():
        match = service.matches.get_nowait()
"""

from __future__ import annotations

import asyncio
import logging
from abc import ABC, abstractmethod
from collections import deque
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

import numpy as np

from flinttrade_indicators.streaming import StreamingEMA, StreamingRSI

logger = logging.getLogger("flinttrade.screener.scanner_service")

# ---------------------------------------------------------------------------
# Types
# ---------------------------------------------------------------------------

#: Supported candle timeframes (in whole minutes).
TIMEFRAMES: tuple[int, ...] = (1, 5, 15)

#: Maximum number of completed bars kept in memory per symbol per timeframe.
MAX_BARS_IN_MEMORY: int = 200


# ---------------------------------------------------------------------------
# Tick and Candle data structures
# ---------------------------------------------------------------------------


@dataclass
class Tick:
    """Normalised market tick received from WebSocket or any feed.

    Attributes:
        symbol:    NSE/BSE symbol string (e.g. ``"NIFTY"``).
        ltp:       Last traded price.
        volume:    Cumulative traded volume for the day.
        timestamp: UTC timestamp of the tick.
        exchange:  Exchange code (default ``"NSE"``).
    """

    symbol: str
    ltp: float
    volume: float
    timestamp: datetime
    exchange: str = "NSE"

    @classmethod
    def from_ws_payload(cls, payload: dict[str, Any]) -> "Tick":
        """Build a :class:`Tick` from a raw WebSocket payload dict.

        The WebSocket can deliver the top-level tick directly or nest it
        under a ``"data"`` key (OpenAlgo market_data format).

        Args:
            payload: Raw dict from the WebSocket tick stream.

        Returns:
            Normalised :class:`Tick` instance.

        Raises:
            KeyError: If required fields are absent.
            ValueError: If ltp or volume cannot be coerced to float.
        """
        data: dict[str, Any] = payload.get("data", payload)
        symbol: str = str(data["symbol"])
        ltp: float = float(data["ltp"])
        volume: float = float(data.get("volume", 0.0))
        ts_raw = data.get("timestamp")
        if ts_raw is None:
            ts = datetime.now(timezone.utc)
        elif isinstance(ts_raw, datetime):
            ts = ts_raw if ts_raw.tzinfo else ts_raw.replace(tzinfo=timezone.utc)
        else:
            ts = datetime.now(timezone.utc)
        exchange: str = str(data.get("exchange", "NSE"))
        return cls(symbol=symbol, ltp=ltp, volume=volume, timestamp=ts, exchange=exchange)


@dataclass
class Candle:
    """Completed OHLCV candle bar.

    Attributes:
        symbol:     Symbol this candle belongs to.
        timeframe:  Timeframe in minutes (1, 5, or 15).
        open:       Opening price of the bar.
        high:       Highest price during the bar.
        low:        Lowest price during the bar.
        close:      Closing (last) price of the bar.
        volume:     Cumulative volume delta for the bar.
        bar_open_ts: UTC timestamp when the bar opened.
        bar_close_ts: UTC timestamp when the bar closed.
    """

    symbol: str
    timeframe: int
    open: float
    high: float
    low: float
    close: float
    volume: float
    bar_open_ts: datetime
    bar_close_ts: datetime


@dataclass
class _PartialBar:
    """Mutable in-progress bar accumulator (internal use only).

    Attributes:
        open:       Opening price (set on first tick).
        high:       Running high.
        low:        Running low.
        close:      Latest close price.
        volume_start: Volume at bar open (for delta calculation).
        bar_open_ts: UTC timestamp of bar start.
    """

    open: float
    high: float
    low: float
    close: float
    volume_start: float
    bar_open_ts: datetime


# ---------------------------------------------------------------------------
# CandleBuilder
# ---------------------------------------------------------------------------


class CandleBuilder:
    """Aggregates raw ticks into OHLCV candles for one symbol.

    Maintains independent bar accumulators for 1m, 5m, and 15m timeframes.
    Whenever a bar boundary is crossed (i.e. the current tick falls into a
    new minute slot), the completed bar is appended to ``bars[timeframe]``
    and the new bar starts.

    A 1-minute boundary is used as the master clock: 5m bars close when
    ``minute % 5 == 0`` and 15m bars when ``minute % 15 == 0``.

    Args:
        symbol:           Symbol this builder tracks.
        max_bars:         Maximum completed bars kept in memory per timeframe.
        timeframes:       Tuple of timeframe periods in minutes to track.
    """

    def __init__(
        self,
        symbol: str,
        max_bars: int = MAX_BARS_IN_MEMORY,
        timeframes: tuple[int, ...] = TIMEFRAMES,
    ) -> None:
        self.symbol = symbol
        self._max_bars = max_bars
        self._timeframes = timeframes
        # Completed bars per timeframe
        self.bars: dict[int, deque[Candle]] = {
            tf: deque(maxlen=max_bars) for tf in timeframes
        }
        # In-progress partial bars per timeframe
        self._partials: dict[int, _PartialBar | None] = {tf: None for tf in timeframes}
        # Track the current 1m slot (floor of minute) per timeframe
        self._current_slots: dict[int, int | None] = {tf: None for tf in timeframes}

    # ------------------------------------------------------------------
    # Public
    # ------------------------------------------------------------------

    def update(self, tick: Tick) -> list[Candle]:
        """Feed one tick and return any candles completed by this tick.

        Args:
            tick: Incoming tick for this builder's symbol.

        Returns:
            List of :class:`Candle` objects completed by this tick.
            May contain 0, 1, 2, or 3 items depending on which timeframes
            closed.
        """
        completed: list[Candle] = []
        for tf in self._timeframes:
            candle = self._update_timeframe(tick, tf)
            if candle is not None:
                completed.append(candle)
        return completed

    def get_bars(self, timeframe: int) -> list[Candle]:
        """Return a snapshot of completed bars for a timeframe, oldest first.

        Args:
            timeframe: Timeframe in minutes (must be in TIMEFRAMES).

        Returns:
            List of completed :class:`Candle` objects.

        Raises:
            KeyError: If timeframe not tracked by this builder.
        """
        if timeframe not in self.bars:
            raise KeyError(f"Timeframe {timeframe} not tracked (allowed: {self._timeframes})")
        return list(self.bars[timeframe])

    def bar_count(self, timeframe: int) -> int:
        """Number of completed bars stored for this timeframe.

        Args:
            timeframe: Timeframe in minutes.

        Returns:
            Integer count.
        """
        return len(self.bars.get(timeframe, []))

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    def _bar_slot(self, ts: datetime, timeframe: int) -> int:
        """Compute the bar slot index (floor division of total minutes by tf).

        Uses total minutes since epoch so that slot numbers are globally
        monotonically increasing and boundary detection is unambiguous.

        Args:
            ts:        Tick timestamp.
            timeframe: Bar duration in minutes.

        Returns:
            Integer slot index.
        """
        total_minutes = int(ts.timestamp() // 60)
        return total_minutes // timeframe

    def _update_timeframe(self, tick: Tick, tf: int) -> Candle | None:
        """Update the partial bar for ``tf`` and return a completed candle if closed.

        Args:
            tick: Tick to process.
            tf:   Timeframe in minutes.

        Returns:
            Completed :class:`Candle` or ``None`` if the bar is still open.
        """
        slot = self._bar_slot(tick.timestamp, tf)
        current_slot = self._current_slots[tf]
        partial = self._partials[tf]

        if current_slot is None:
            # First tick — open new bar
            self._current_slots[tf] = slot
            self._partials[tf] = _PartialBar(
                open=tick.ltp,
                high=tick.ltp,
                low=tick.ltp,
                close=tick.ltp,
                volume_start=tick.volume,
                bar_open_ts=tick.timestamp,
            )
            return None

        if slot == current_slot:
            # Still inside the same bar — update in-place
            assert partial is not None
            if tick.ltp > partial.high:
                partial.high = tick.ltp
            if tick.ltp < partial.low:
                partial.low = tick.ltp
            partial.close = tick.ltp
            return None

        # New slot — close the old bar and open a fresh one
        assert partial is not None
        volume_delta = max(0.0, tick.volume - partial.volume_start)
        bar_close_ts = tick.timestamp

        completed = Candle(
            symbol=self.symbol,
            timeframe=tf,
            open=partial.open,
            high=partial.high,
            low=partial.low,
            close=partial.close,
            volume=volume_delta,
            bar_open_ts=partial.bar_open_ts,
            bar_close_ts=bar_close_ts,
        )
        self.bars[tf].append(completed)

        # Start new partial bar with the triggering tick
        self._current_slots[tf] = slot
        self._partials[tf] = _PartialBar(
            open=tick.ltp,
            high=tick.ltp,
            low=tick.ltp,
            close=tick.ltp,
            volume_start=tick.volume,
            bar_open_ts=tick.timestamp,
        )
        return completed


# ---------------------------------------------------------------------------
# Scanner match event
# ---------------------------------------------------------------------------


@dataclass
class ScannerMatch:
    """A scanner match event published to the matches queue.

    Attributes:
        scanner_name: Name of the scanner that fired.
        symbol:       Matched symbol.
        exchange:     Exchange of the symbol.
        timeframe:    Bar timeframe (minutes) that triggered the match.
        signal:       Signal type string (e.g. ``"oversold"``, ``"golden_cross"``).
        value:        Indicator value at the time of match.
        ltp:          Last traded price (close of triggering bar).
        matched_at:   UTC timestamp of match detection.
        extra:        Optional extra metadata from the scanner.
    """

    scanner_name: str
    symbol: str
    exchange: str
    timeframe: int
    signal: str
    value: float
    ltp: float
    matched_at: datetime
    extra: dict[str, Any] = field(default_factory=dict)


# ---------------------------------------------------------------------------
# AbstractScanner
# ---------------------------------------------------------------------------


class AbstractScanner(ABC):
    """Base class for all real-time candle scanners.

    Subclass this to implement a new scanner type.  Each scanner maintains
    its own per-symbol state via ``_symbol_states`` which is populated on
    first call.

    Args:
        name:       Human-readable scanner name.
        timeframe:  Bar timeframe this scanner reacts to (minutes).
    """

    def __init__(self, name: str, timeframe: int = 1) -> None:
        self.name = name
        self.timeframe = timeframe
        self._symbol_states: dict[str, Any] = {}

    @abstractmethod
    def on_candle(self, candle: Candle, history: list[Candle]) -> ScannerMatch | None:
        """Evaluate the latest completed candle and return a match if found.

        Args:
            candle:  The newly completed candle bar.
            history: All previously completed bars for this symbol and timeframe,
                     oldest first (does NOT include ``candle`` itself — append it
                     yourself if needed for indicator computation).

        Returns:
            :class:`ScannerMatch` if a signal fired, otherwise ``None``.
        """
        ...

    def reset(self, symbol: str) -> None:
        """Clear the per-symbol indicator state for ``symbol``.

        Args:
            symbol: Symbol to reset.
        """
        self._symbol_states.pop(symbol, None)

    def reset_all(self) -> None:
        """Clear all per-symbol indicator states."""
        self._symbol_states.clear()


# ---------------------------------------------------------------------------
# RSI Scanner
# ---------------------------------------------------------------------------


@dataclass
class _RSIState:
    rsi: StreamingRSI


class RSIScanner(AbstractScanner):
    """Detects RSI oversold and overbought conditions on completed candles.

    Uses the ``StreamingRSI`` indicator from ``packages/core/indicators`` which
    implements Wilder's RMA smoothing, matching TradingView behaviour.

    Args:
        period:      RSI period (default 14).
        oversold:    Threshold below which a symbol is considered oversold
                     (default 30).
        overbought:  Threshold above which a symbol is considered overbought
                     (default 70).
        timeframe:   Bar timeframe in minutes (default 1).
    """

    def __init__(
        self,
        period: int = 14,
        oversold: float = 30.0,
        overbought: float = 70.0,
        timeframe: int = 1,
    ) -> None:
        super().__init__(name="RSIScanner", timeframe=timeframe)
        self._period = period
        self._oversold = oversold
        self._overbought = overbought

    def on_candle(self, candle: Candle, history: list[Candle]) -> ScannerMatch | None:
        """Feed a completed candle and return a match if RSI crosses a threshold.

        Args:
            candle:  Latest completed candle.
            history: Prior completed candles (oldest first).

        Returns:
            :class:`ScannerMatch` with signal ``"oversold"`` or ``"overbought"``,
            or ``None`` if no threshold is crossed.
        """
        symbol = candle.symbol
        if symbol not in self._symbol_states:
            self._symbol_states[symbol] = _RSIState(rsi=StreamingRSI(period=self._period))

        state: _RSIState = self._symbol_states[symbol]
        rsi_val = state.rsi.update(candle.close)

        if rsi_val is None:
            return None

        signal: str | None = None
        if rsi_val <= self._oversold:
            signal = "oversold"
        elif rsi_val >= self._overbought:
            signal = "overbought"

        if signal is None:
            return None

        return ScannerMatch(
            scanner_name=self.name,
            symbol=candle.symbol,
            exchange=candle.symbol,  # caller may override via extra
            timeframe=candle.timeframe,
            signal=signal,
            value=round(rsi_val, 2),
            ltp=candle.close,
            matched_at=candle.bar_close_ts,
            extra={"period": self._period, "oversold": self._oversold, "overbought": self._overbought},
        )


# ---------------------------------------------------------------------------
# EMA Crossover Scanner
# ---------------------------------------------------------------------------


@dataclass
class _EMACrossState:
    fast: StreamingEMA
    slow: StreamingEMA
    prev_fast: float | None = None
    prev_slow: float | None = None


class EMACrossoverScanner(AbstractScanner):
    """Detects EMA golden cross and death cross events.

    A **golden cross** occurs when the fast EMA crosses above the slow EMA
    (bullish signal).  A **death cross** occurs when it crosses below
    (bearish signal).

    Uses ``StreamingEMA`` from ``packages/core/indicators`` for O(1) per-bar cost.

    Args:
        fast:      Fast EMA period (default 9).
        slow:      Slow EMA period (default 21).
        timeframe: Bar timeframe in minutes (default 1).
    """

    def __init__(
        self,
        fast: int = 9,
        slow: int = 21,
        timeframe: int = 1,
    ) -> None:
        if fast >= slow:
            raise ValueError(
                f"EMACrossoverScanner: fast period ({fast}) must be < slow period ({slow})"
            )
        super().__init__(name="EMACrossoverScanner", timeframe=timeframe)
        self._fast_period = fast
        self._slow_period = slow

    def on_candle(self, candle: Candle, history: list[Candle]) -> ScannerMatch | None:
        """Feed a completed candle and return a match if an EMA cross is detected.

        Args:
            candle:  Latest completed candle.
            history: Prior completed candles (oldest first).

        Returns:
            :class:`ScannerMatch` with signal ``"golden_cross"`` or
            ``"death_cross"``, or ``None`` if no cross occurred.
        """
        symbol = candle.symbol
        if symbol not in self._symbol_states:
            self._symbol_states[symbol] = _EMACrossState(
                fast=StreamingEMA(self._fast_period),
                slow=StreamingEMA(self._slow_period),
            )

        state: _EMACrossState = self._symbol_states[symbol]

        fast_val = state.fast.update(candle.close)
        slow_val = state.slow.update(candle.close)

        if fast_val is None or slow_val is None:
            state.prev_fast = fast_val
            state.prev_slow = slow_val
            return None

        prev_fast = state.prev_fast
        prev_slow = state.prev_slow
        # Save current values for next bar before potentially returning early
        state.prev_fast = fast_val
        state.prev_slow = slow_val

        if prev_fast is None or prev_slow is None:
            return None

        signal: str | None = None
        if prev_fast <= prev_slow and fast_val > slow_val:
            signal = "golden_cross"
        elif prev_fast >= prev_slow and fast_val < slow_val:
            signal = "death_cross"

        if signal is None:
            return None

        return ScannerMatch(
            scanner_name=self.name,
            symbol=candle.symbol,
            exchange=candle.symbol,
            timeframe=candle.timeframe,
            signal=signal,
            value=round(fast_val - slow_val, 4),
            ltp=candle.close,
            matched_at=candle.bar_close_ts,
            extra={"fast_ema": round(fast_val, 4), "slow_ema": round(slow_val, 4),
                   "fast_period": self._fast_period, "slow_period": self._slow_period},
        )


# ---------------------------------------------------------------------------
# Volume Spike Scanner
# ---------------------------------------------------------------------------


@dataclass
class _VolSpikeState:
    recent_volumes: deque[float]


class VolumeSpikeScanner(AbstractScanner):
    """Detects volume spikes where current bar volume exceeds N × average.

    The rolling average is computed over the last ``lookback`` completed bars
    (excluding the current bar).  A spike fires when:

        current_volume > threshold_multiplier × rolling_avg_volume

    Args:
        lookback:             Number of prior bars used to compute average volume
                              (default 20).
        threshold_multiplier: Spike detection multiplier (default 2.0 — fires
                              when volume is more than 2× average).
        timeframe:            Bar timeframe in minutes (default 1).
    """

    def __init__(
        self,
        lookback: int = 20,
        threshold_multiplier: float = 2.0,
        timeframe: int = 1,
    ) -> None:
        if lookback < 2:
            raise ValueError(f"VolumeSpikeScanner: lookback must be >= 2, got {lookback}")
        if threshold_multiplier <= 0:
            raise ValueError(
                f"VolumeSpikeScanner: threshold_multiplier must be > 0, got {threshold_multiplier}"
            )
        super().__init__(name="VolumeSpikeScanner", timeframe=timeframe)
        self._lookback = lookback
        self._threshold = threshold_multiplier

    def on_candle(self, candle: Candle, history: list[Candle]) -> ScannerMatch | None:
        """Feed a completed candle and return a match if volume is a spike.

        Args:
            candle:  Latest completed candle.
            history: Prior completed candles (oldest first).

        Returns:
            :class:`ScannerMatch` with signal ``"volume_spike"`` or ``None``.
        """
        symbol = candle.symbol
        if symbol not in self._symbol_states:
            self._symbol_states[symbol] = _VolSpikeState(
                recent_volumes=deque(maxlen=self._lookback)
            )

        state: _VolSpikeState = self._symbol_states[symbol]

        # Need at least `lookback` prior volumes to compute a meaningful average
        if len(state.recent_volumes) < self._lookback:
            state.recent_volumes.append(candle.volume)
            return None

        avg_volume = float(np.mean(state.recent_volumes))
        state.recent_volumes.append(candle.volume)

        if avg_volume <= 0.0:
            return None

        ratio = candle.volume / avg_volume

        if ratio <= self._threshold:
            return None

        return ScannerMatch(
            scanner_name=self.name,
            symbol=candle.symbol,
            exchange=candle.symbol,
            timeframe=candle.timeframe,
            signal="volume_spike",
            value=round(ratio, 3),
            ltp=candle.close,
            matched_at=candle.bar_close_ts,
            extra={
                "current_volume": candle.volume,
                "avg_volume": round(avg_volume, 0),
                "multiplier": round(ratio, 3),
                "threshold": self._threshold,
                "lookback": self._lookback,
            },
        )


# ---------------------------------------------------------------------------
# ScannerService
# ---------------------------------------------------------------------------


class ScannerService:
    """Orchestrates tick ingestion, candle building, and scanner dispatch.

    Architecture
    ------------
    - One :class:`CandleBuilder` per symbol (created on first tick).
    - Each registered :class:`AbstractScanner` is called whenever a candle
      matching its ``timeframe`` is completed.
    - Matches are pushed to ``self.matches`` (an ``asyncio.Queue``).
    - An optional ``match_callback`` is invoked synchronously for each match
      (useful for Flask-SSE or WebSocket broadcast integration).
    - No Redis required; swap ``self.matches`` for a Redis stream adapter
      externally if needed.

    Args:
        match_callback: Optional coroutine or sync callable invoked on each
                        :class:`ScannerMatch`.  Signature:
                        ``(match: ScannerMatch) -> None | Awaitable[None]``.
        queue_maxsize:  Maximum number of matches buffered in the asyncio Queue
                        before blocking (default 1000).
    """

    def __init__(
        self,
        match_callback: Any = None,
        queue_maxsize: int = 1000,
    ) -> None:
        self._scanners: list[AbstractScanner] = []
        self._builders: dict[str, CandleBuilder] = {}
        self.matches: asyncio.Queue[ScannerMatch] = asyncio.Queue(maxsize=queue_maxsize)
        self._match_callback = match_callback
        self._started: bool = False

    # ------------------------------------------------------------------
    # Scanner registration
    # ------------------------------------------------------------------

    def add_scanner(self, scanner: AbstractScanner) -> None:
        """Register a scanner with the service.

        The same scanner instance can only be added once; duplicate adds are
        silently ignored.

        Args:
            scanner: :class:`AbstractScanner` instance to add.
        """
        if scanner not in self._scanners:
            self._scanners.append(scanner)
            logger.info("Scanner registered: %s (tf=%dm)", scanner.name, scanner.timeframe)

    def remove_scanner(self, scanner: AbstractScanner) -> bool:
        """Unregister a scanner.

        Args:
            scanner: Scanner instance to remove.

        Returns:
            ``True`` if removed, ``False`` if not found.
        """
        try:
            self._scanners.remove(scanner)
            return True
        except ValueError:
            return False

    def list_scanners(self) -> list[AbstractScanner]:
        """Return a snapshot of all registered scanners.

        Returns:
            List of :class:`AbstractScanner` instances (shallow copy).
        """
        return list(self._scanners)

    # ------------------------------------------------------------------
    # Tick ingestion
    # ------------------------------------------------------------------

    async def on_tick(self, payload: dict[str, Any] | Tick) -> list[ScannerMatch]:
        """Ingest one tick and dispatch to scanners for any completed candles.

        This is the primary entry point.  Call it from your WebSocket
        consumer for every incoming tick.

        Args:
            payload: Either a raw WebSocket payload dict (will be normalised
                     via :meth:`Tick.from_ws_payload`) or an already-normalised
                     :class:`Tick`.

        Returns:
            List of :class:`ScannerMatch` objects fired by this tick.
        """
        tick: Tick = (
            payload
            if isinstance(payload, Tick)
            else Tick.from_ws_payload(payload)
        )

        if tick.symbol not in self._builders:
            self._builders[tick.symbol] = CandleBuilder(symbol=tick.symbol)

        builder = self._builders[tick.symbol]
        completed_candles = builder.update(tick)

        all_matches: list[ScannerMatch] = []
        for candle in completed_candles:
            for scanner in self._scanners:
                if scanner.timeframe != candle.timeframe:
                    continue
                history = builder.get_bars(candle.timeframe)
                # history includes the just-appended candle; pass it without
                # the last element so on_candle receives prior history
                match = scanner.on_candle(candle, history[:-1])
                if match is not None:
                    all_matches.append(match)
                    await self._publish(match)

        return all_matches

    async def _publish(self, match: ScannerMatch) -> None:
        """Push a match to the queue and invoke the optional callback.

        Args:
            match: The :class:`ScannerMatch` to publish.
        """
        try:
            self.matches.put_nowait(match)
        except asyncio.QueueFull:
            logger.warning(
                "Scanner match queue full — dropping match for %s (%s)",
                match.symbol,
                match.signal,
            )

        if self._match_callback is not None:
            try:
                result = self._match_callback(match)
                if asyncio.iscoroutine(result):
                    await result
            except Exception as exc:
                logger.warning("match_callback raised: %s", exc)

    # ------------------------------------------------------------------
    # Context manager support
    # ------------------------------------------------------------------

    async def __aenter__(self) -> "ScannerService":
        self._started = True
        logger.info(
            "ScannerService started with %d scanner(s)", len(self._scanners)
        )
        return self

    async def __aexit__(self, *_: object) -> None:
        self._started = False
        logger.info("ScannerService stopped")

    # ------------------------------------------------------------------
    # Utility
    # ------------------------------------------------------------------

    @property
    def tracked_symbols(self) -> list[str]:
        """Return a sorted list of all symbols currently tracked.

        Returns:
            Sorted list of symbol strings.
        """
        return sorted(self._builders.keys())

    def get_builder(self, symbol: str) -> CandleBuilder | None:
        """Return the :class:`CandleBuilder` for ``symbol``, or ``None``.

        Args:
            symbol: Symbol string.

        Returns:
            Builder instance or ``None`` if symbol not yet seen.
        """
        return self._builders.get(symbol)

    def stats(self) -> dict[str, Any]:
        """Return a diagnostic snapshot of service state.

        Returns:
            Dict with counts of tracked symbols, registered scanners, and
            pending matches in the queue.
        """
        return {
            "tracked_symbols": len(self._builders),
            "registered_scanners": len(self._scanners),
            "pending_matches": self.matches.qsize(),
            "started": self._started,
        }
