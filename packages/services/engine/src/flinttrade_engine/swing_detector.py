"""Swing high / swing low detector for OHLCV data.

Implements the watch-based confirmation system adapted from
nifty-trading-railway. A swing is only confirmed after two independent
"watch" events validate that the candidate bar was a true turning point.

Watch logic:
    * **low_watch** — a future bar has a HIGHER high AND a HIGHER close than
      the candidate bar.  Two such bars confirm a swing LOW at the candidate.
    * **high_watch** — a future bar has a LOWER low AND a LOWER close.
      Two such bars confirm a swing HIGH.

After the first swing is established, the pattern strictly alternates:
LOW → HIGH → LOW → HIGH …  Same-direction updates (e.g. a lower low before
the next HIGH forms) also require two-watch confirmation before the existing
swing extreme is updated.

Usage::

    from flinttrade_engine.swing_detector import SwingDetector, SwingPoint

    detector = SwingDetector(lookback=3)

    for bar in ohlcv_bars:
        result = detector.add_bar(bar)
        if result is not None:
            print(result)  # SwingPoint(type='LOW', price=..., ...)

    breaks = detector.check_break(current_bar)
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

logger = logging.getLogger("flinttrade.engine.swing_detector")


# ---------------------------------------------------------------------------
# IST helper
# ---------------------------------------------------------------------------


def _now_ist() -> datetime:
    try:
        from zoneinfo import ZoneInfo

        return datetime.now(ZoneInfo("Asia/Kolkata"))
    except Exception:
        return datetime.now(UTC)


# ---------------------------------------------------------------------------
# Data models
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class OHLCVBar:
    """A single OHLCV bar.

    Attributes:
        timestamp:  Bar close time.
        open:       Opening price.
        high:       High price.
        low:        Low price.
        close:      Closing price.
        volume:     Volume (0 if unavailable).
        vwap:       VWAP (falls back to ``close`` if unavailable).
    """

    timestamp: datetime
    open: float
    high: float
    low: float
    close: float
    volume: int = 0
    vwap: float = 0.0

    def __post_init__(self) -> None:
        # Freeze vwap to close if not supplied
        if self.vwap == 0.0:
            object.__setattr__(self, "vwap", self.close)


@dataclass
class SwingPoint:
    """A confirmed swing high or low.

    Attributes:
        swing_type:   ``"LOW"`` or ``"HIGH"``.
        price:        Swing extreme price (low for LOW, high for HIGH).
        timestamp:    Bar timestamp at which the swing extreme occurred.
        bar_index:    Index of the swing bar in the detector's internal buffer.
        vwap:         VWAP frozen at the time of first swing detection
                      (intentionally NOT updated on subsequent extremes).
        bar_high:     High of the swing bar.
        bar_low:      Low of the swing bar.
        broken:       ``True`` once price has crossed below (LOW) or above (HIGH).
        strength:     Watch-count at confirmation (always 2 in the standard system;
                      exposed for downstream filtering / ranking).
        metadata:     Free-form dict for strategy-specific annotations.
    """

    swing_type: str          # "LOW" or "HIGH"
    price: float
    timestamp: datetime
    bar_index: int
    vwap: float
    bar_high: float
    bar_low: float
    broken: bool = False
    strength: int = 2
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class BreakEvent:
    """Emitted when price crosses the last unbroken swing extreme.

    Attributes:
        swing_type:    Type of the swing that was broken (``"LOW"`` or ``"HIGH"``).
        swing_price:   Price of the broken swing extreme.
        break_price:   Price at which the break was confirmed (bar low/high).
        break_time:    Timestamp of the breaking bar.
        swing_time:    Timestamp of the original swing bar.
        highest_high:  Highest high between the swing bar and the break bar
                       (relevant for SL calculation).
        lowest_low:    Lowest low in the same window.
        vwap_at_swing: VWAP frozen at swing formation time.
    """

    swing_type: str
    swing_price: float
    break_price: float
    break_time: datetime
    swing_time: datetime
    highest_high: float
    lowest_low: float
    vwap_at_swing: float


# ---------------------------------------------------------------------------
# SwingDetector
# ---------------------------------------------------------------------------


class SwingDetector:
    """Stateful swing high/low detector using the watch-based confirmation system.

    Each ``SwingDetector`` tracks a single symbol (or any homogeneous price
    stream) independently.

    Args:
        lookback:       Maximum number of past bars to retain in memory.
                        Older bars are pruned to bound memory use.
                        Default ``500`` (sufficient for an entire IST session
                        at 1-minute granularity).
        watch_threshold: Number of watch events required before confirming a
                         swing.  Default ``2`` (matches the original system).

    Example::

        detector = SwingDetector()
        for bar in bars:
            swing = detector.add_bar(bar)
            if swing:
                print(f"New {swing.swing_type} @ {swing.price}")
    """

    def __init__(
        self,
        lookback: int = 500,
        watch_threshold: int = 2,
    ) -> None:
        self._lookback = lookback
        self._watch_threshold = watch_threshold

        self._bars: list[OHLCVBar] = []
        self._swings: list[SwingPoint] = []
        self._last_swing: SwingPoint | None = None
        self._last_swing_idx: int | None = None

        # Watch counters: {bar_index: count}
        self._low_watch: dict[int, int] = {}
        self._high_watch: dict[int, int] = {}

        # Deduplication: set of (timestamp_iso, swing_type, rounded_price)
        self._logged_swings: set[tuple[str, str, float]] = set()

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def add_bar(self, bar: OHLCVBar) -> SwingPoint | None:
        """Process a new OHLCV bar and return a new SwingPoint if confirmed.

        Bars must be supplied in chronological order.  Out-of-order or
        duplicate timestamps are silently skipped.

        Args:
            bar: An ``OHLCVBar`` instance.

        Returns:
            A ``SwingPoint`` if a new swing LOW or swing HIGH was confirmed,
            otherwise ``None``.
        """
        # --- Duplicate / out-of-order guard ---
        if self._bars:
            last_ts = self._bars[-1].timestamp
            if bar.timestamp < last_ts:
                logger.debug(
                    "[SWING] Out-of-order bar skipped: %s < %s",
                    bar.timestamp, last_ts,
                )
                return None
            if bar.timestamp == last_ts:
                logger.debug("[SWING] Duplicate timestamp skipped: %s", bar.timestamp)
                return None

        current_index = len(self._bars)
        self._bars.append(bar)

        # Prune old bars to bound memory usage
        if len(self._bars) > self._lookback:
            self._prune()
            current_index = len(self._bars) - 1

        if len(self._bars) < 2:
            return None

        if self._last_swing is None:
            return self._find_initial_swing(current_index, bar)
        return self._find_alternate_swing(current_index, bar)

    def check_break(self, bar: OHLCVBar) -> BreakEvent | None:
        """Check whether the bar breaks the last unbroken swing extreme.

        Currently checks only for LOW breaks (bar low < swing low price).
        Extend the ``break_direction`` parameter if HIGH breaks are needed.

        Args:
            bar: The latest bar (may or may not have been passed to ``add_bar``).

        Returns:
            A ``BreakEvent`` if the last swing low is broken, otherwise ``None``.
        """
        if self._last_swing is None:
            return None
        if self._last_swing.broken:
            return None
        if self._last_swing.swing_type != "LOW":
            return None

        swing_price = self._last_swing.price
        if bar.low < swing_price:
            self._last_swing.broken = True

            swing_idx = self._last_swing.bar_index
            # Find the adjusted index in the possibly-pruned buffer
            window = self._bars[max(0, swing_idx):]
            if not window:
                window = self._bars

            highest_high = max(b.high for b in window)
            lowest_low = min(b.low for b in window)

            event = BreakEvent(
                swing_type="LOW",
                swing_price=swing_price,
                break_price=bar.low,
                break_time=bar.timestamp,
                swing_time=self._last_swing.timestamp,
                highest_high=highest_high,
                lowest_low=lowest_low,
                vwap_at_swing=self._last_swing.vwap,
            )
            logger.info(
                "[SWING] LOW BREAK @ %.2f (bar low=%.2f) hh=%.2f",
                swing_price, bar.low, highest_high,
            )
            return event

        return None

    def reset(self) -> None:
        """Clear all state (call at the start of each trading day)."""
        self._bars.clear()
        self._swings.clear()
        self._last_swing = None
        self._last_swing_idx = None
        self._low_watch.clear()
        self._high_watch.clear()
        self._logged_swings.clear()
        logger.debug("[SWING] Detector reset.")

    @property
    def last_swing(self) -> SwingPoint | None:
        """Most recently confirmed swing point (or None)."""
        return self._last_swing

    @property
    def last_swing_low(self) -> SwingPoint | None:
        """Last unbroken swing LOW, or None."""
        if (
            self._last_swing is not None
            and self._last_swing.swing_type == "LOW"
            and not self._last_swing.broken
        ):
            return self._last_swing
        return None

    @property
    def all_swings(self) -> list[SwingPoint]:
        """All confirmed swing points (oldest first).

        Returns deep copies so callers cannot mutate the detector's internal
        state through the returned objects (``_update_extreme`` mutates
        ``SwingPoint`` fields in-place).
        """
        from copy import deepcopy

        return [deepcopy(s) for s in self._swings]

    def get_bars(self, count: int | None = None) -> list[OHLCVBar]:
        """Return recent bars from the internal buffer.

        Args:
            count: Number of most-recent bars to return. ``None`` returns all.
        """
        if count is None:
            return list(self._bars)
        return list(self._bars[-count:])

    # ------------------------------------------------------------------
    # Internal: initial swing detection
    # ------------------------------------------------------------------

    def _find_initial_swing(self, i: int, current: OHLCVBar) -> SwingPoint | None:
        """Find the very first swing (LOW or HIGH) — whichever triggers first.

        Scans all previous bars [0, i-1] to accumulate watch counts.
        Triggers as soon as any bar's watch counter reaches the threshold.
        """
        for j in range(i):
            prev = self._bars[j]

            # low_watch: current has HIGHER high AND HIGHER close
            if current.high > prev.high and current.close > prev.close:
                self._low_watch[j] = self._low_watch.get(j, 0) + 1
                if self._low_watch[j] >= self._watch_threshold:
                    window = self._bars[: i + 1]
                    lowest_idx = min(range(len(window)), key=lambda x: window[x].low)
                    return self._create_swing("LOW", window[lowest_idx], lowest_idx)

            # high_watch: current has LOWER low AND LOWER close
            if current.low < prev.low and current.close < prev.close:
                self._high_watch[j] = self._high_watch.get(j, 0) + 1
                if self._high_watch[j] >= self._watch_threshold:
                    window = self._bars[: i + 1]
                    highest_idx = max(range(len(window)), key=lambda x: window[x].high)
                    return self._create_swing("HIGH", window[highest_idx], highest_idx)

        return None

    # ------------------------------------------------------------------
    # Internal: alternating swing detection
    # ------------------------------------------------------------------

    def _find_alternate_swing(self, i: int, current: OHLCVBar) -> SwingPoint | None:
        """Find the next swing alternating from the last confirmed swing.

        Also handles same-direction updates (e.g. lower LOW before the
        next HIGH forms), but only after two-watch confirmation.
        """
        last_idx = self._last_swing_idx
        if last_idx is None:
            return None

        last_type = self._last_swing.swing_type  # "LOW" or "HIGH"

        for j in range(last_idx + 1, i):
            prev = self._bars[j]

            if last_type == "LOW":
                # Looking for alternating HIGH
                if current.low < prev.low and current.close < prev.close:
                    self._high_watch[j] = self._high_watch.get(j, 0) + 1
                    if self._high_watch[j] >= self._watch_threshold:
                        window = self._bars[last_idx + 1 : i + 1]
                        highest_local = max(range(len(window)), key=lambda x: window[x].high)
                        highest_idx = last_idx + 1 + highest_local
                        return self._create_swing("HIGH", self._bars[highest_idx], highest_idx)

                # Same-direction update (lower LOW)
                if current.high > prev.high and current.close > prev.close:
                    self._low_watch[j] = self._low_watch.get(j, 0) + 1
                    if self._low_watch[j] >= self._watch_threshold:
                        window = self._bars[last_idx + 1 : i + 1]
                        lowest_local = min(range(len(window)), key=lambda x: window[x].low)
                        lowest_idx = last_idx + 1 + lowest_local
                        candidate = self._bars[lowest_idx]
                        if candidate.low < self._last_swing.price:
                            return self._update_extreme("LOW", candidate, lowest_idx)

            else:  # last_type == "HIGH"
                # Looking for alternating LOW
                if current.high > prev.high and current.close > prev.close:
                    self._low_watch[j] = self._low_watch.get(j, 0) + 1
                    if self._low_watch[j] >= self._watch_threshold:
                        window = self._bars[last_idx + 1 : i + 1]
                        lowest_local = min(range(len(window)), key=lambda x: window[x].low)
                        lowest_idx = last_idx + 1 + lowest_local
                        return self._create_swing("LOW", self._bars[lowest_idx], lowest_idx)

                # Same-direction update (higher HIGH)
                if current.low < prev.low and current.close < prev.close:
                    self._high_watch[j] = self._high_watch.get(j, 0) + 1
                    if self._high_watch[j] >= self._watch_threshold:
                        window = self._bars[last_idx + 1 : i + 1]
                        highest_local = max(range(len(window)), key=lambda x: window[x].high)
                        highest_idx = last_idx + 1 + highest_local
                        candidate = self._bars[highest_idx]
                        if candidate.high > self._last_swing.price:
                            return self._update_extreme("HIGH", candidate, highest_idx)

        return None

    # ------------------------------------------------------------------
    # Internal: swing creation & update helpers
    # ------------------------------------------------------------------

    def _create_swing(self, swing_type: str, bar: OHLCVBar, idx: int) -> SwingPoint | None:
        """Register a new confirmed swing point."""
        price = bar.low if swing_type == "LOW" else bar.high

        # Deduplication
        key = (bar.timestamp.isoformat(), swing_type, round(price, 2))
        if key in self._logged_swings:
            return None
        self._logged_swings.add(key)

        swing = SwingPoint(
            swing_type=swing_type,
            price=price,
            timestamp=bar.timestamp,
            bar_index=idx,
            vwap=bar.vwap,
            bar_high=bar.high,
            bar_low=bar.low,
        )
        self._swings.append(swing)
        self._last_swing = swing
        self._last_swing_idx = idx

        # Reset watch counters for the next swing window
        self._low_watch.clear()
        self._high_watch.clear()

        logger.info(
            "[SWING] New %s @ %.2f  time=%s  idx=%d",
            swing_type, price,
            bar.timestamp.strftime("%H:%M") if hasattr(bar.timestamp, "strftime") else str(bar.timestamp),
            idx,
        )
        return swing

    def _update_extreme(self, swing_type: str, bar: OHLCVBar, idx: int) -> SwingPoint | None:
        """Update an existing swing to a new confirmed extreme.

        Returns the updated swing if it is a LOW (useful for trading logic),
        otherwise returns ``None`` (HIGH updates are informational).
        """
        if self._last_swing is None:
            return None

        new_price = bar.low if swing_type == "LOW" else bar.high
        old_price = self._last_swing.price

        logger.info(
            "[SWING] UPDATE %s  %.2f → %.2f  time=%s",
            swing_type, old_price, new_price,
            bar.timestamp.strftime("%H:%M") if hasattr(bar.timestamp, "strftime") else str(bar.timestamp),
        )

        # Mutate the existing SwingPoint in place
        # (VWAP intentionally NOT updated — frozen at original detection time)
        self._last_swing.price = new_price
        self._last_swing.timestamp = bar.timestamp
        self._last_swing.bar_index = idx
        self._last_swing.bar_high = bar.high
        self._last_swing.bar_low = bar.low
        self._last_swing_idx = idx

        if swing_type == "LOW":
            return self._last_swing
        return None

    # ------------------------------------------------------------------
    # Internal: memory pruning
    # ------------------------------------------------------------------

    def _prune(self) -> None:
        """Remove the oldest half of the bar buffer to free memory.

        Also adjusts all bar indices stored in SwingPoints so they remain
        consistent with the new buffer offsets.
        """
        cut = len(self._bars) // 2
        self._bars = self._bars[cut:]

        # Shift watch counter keys
        self._low_watch = {k - cut: v for k, v in self._low_watch.items() if k >= cut}
        self._high_watch = {k - cut: v for k, v in self._high_watch.items() if k >= cut}

        # Adjust last_swing_idx
        if self._last_swing_idx is not None:
            self._last_swing_idx = max(0, self._last_swing_idx - cut)

        # Adjust bar_index in all swing objects
        for swing in self._swings:
            swing.bar_index = max(0, swing.bar_index - cut)

        logger.debug("[SWING] Pruned bar buffer by %d bars (now %d bars).", cut, len(self._bars))


# ---------------------------------------------------------------------------
# MultiSwingDetector — manages per-symbol detectors
# ---------------------------------------------------------------------------


class MultiSwingDetector:
    """Manage independent ``SwingDetector`` instances for multiple symbols.

    Args:
        lookback:         Forwarded to each ``SwingDetector``.
        watch_threshold:  Forwarded to each ``SwingDetector``.
        on_swing:         Optional callback called with ``(symbol, SwingPoint)``
                          when a new swing is confirmed.
        on_break:         Optional callback called with ``(symbol, BreakEvent)``
                          when a swing break is confirmed.

    Example::

        def handle_swing(symbol: str, swing: SwingPoint) -> None:
            print(f"{symbol}: new {swing.swing_type} @ {swing.price}")

        detector = MultiSwingDetector(on_swing=handle_swing)
        detector.add_symbols(["NIFTY30DEC2523500CE", "NIFTY30DEC2523500PE"])

        for symbol, bar in ticks:
            detector.update(symbol, bar)
    """

    def __init__(
        self,
        lookback: int = 500,
        watch_threshold: int = 2,
        on_swing: Any = None,
        on_break: Any = None,
    ) -> None:
        self._lookback = lookback
        self._watch_threshold = watch_threshold
        self._on_swing = on_swing
        self._on_break = on_break
        self._detectors: dict[str, SwingDetector] = {}

    def add_symbols(self, symbols: list[str]) -> None:
        """Register detectors for new symbols (idempotent).

        Args:
            symbols: List of instrument symbols.
        """
        for sym in symbols:
            if sym not in self._detectors:
                self._detectors[sym] = SwingDetector(
                    lookback=self._lookback,
                    watch_threshold=self._watch_threshold,
                )

    def update(self, symbol: str, bar: OHLCVBar) -> BreakEvent | None:
        """Process a new bar for one symbol, fire callbacks if applicable.

        Args:
            symbol: Instrument symbol.
            bar:    ``OHLCVBar`` instance.

        Returns:
            ``BreakEvent`` if the last swing low was broken, else ``None``.
        """
        if symbol not in self._detectors:
            self.add_symbols([symbol])

        detector = self._detectors[symbol]
        swing = detector.add_bar(bar)

        if swing is not None and self._on_swing is not None:
            self._on_swing(symbol, swing)

        break_event = detector.check_break(bar)
        if break_event is not None and self._on_break is not None:
            self._on_break(symbol, break_event)

        return break_event

    def get_detector(self, symbol: str) -> SwingDetector | None:
        """Return the detector for a specific symbol, or ``None``."""
        return self._detectors.get(symbol)

    def reset_all(self) -> None:
        """Reset all detectors (call at the start of each trading day)."""
        for detector in self._detectors.values():
            detector.reset()
        logger.info("[SWING] All %d detectors reset.", len(self._detectors))

    @property
    def symbols(self) -> list[str]:
        """All symbols currently tracked."""
        return list(self._detectors.keys())
