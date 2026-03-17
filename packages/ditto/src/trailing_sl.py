"""Trailing stop loss manager.

Absorbs AlgoMirror's supertrend.py patterns. Supports four trailing modes:
1. Points-based: trail by N points from peak
2. Percentage-based: trail by N% from peak
3. Supertrend-based: Supertrend indicator as dynamic trailing SL
4. ATR-based: trail by N x ATR from peak

Each open position has its own SL tracker. When the trail moves, the SL order
is auto-modified via OpenAlgo /api/v1/modifyorder.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from enum import Enum

logger = logging.getLogger("flinttrade.ditto.trailing_sl")


class TrailingMode(str, Enum):
    POINTS = "POINTS"
    PERCENTAGE = "PERCENTAGE"
    SUPERTREND = "SUPERTREND"
    ATR = "ATR"


@dataclass
class SLTracker:
    """Stop-loss tracker for a single position."""

    position_id: str
    symbol: str
    side: str  # "BUY" (long) or "SELL" (short)
    entry_price: float = 0.0
    current_sl: float = 0.0
    peak_price: float = 0.0
    trough_price: float = float("inf")
    trail_mode: str = "POINTS"
    trail_value: float = 50.0  # Points, percentage, or multiplier
    sl_order_id: str = ""
    adjustments: int = 0

    @property
    def is_long(self) -> bool:
        return self.side.upper() == "BUY"


@dataclass
class SLAdjustment:
    """Record of a single SL adjustment."""

    position_id: str
    old_sl: float
    new_sl: float
    trigger_price: float  # The price that caused the adjustment
    mode: str
    timestamp: str = ""


# ---------------------------------------------------------------------------
# Supertrend calculation (pure Python, Numba-optional)
# ---------------------------------------------------------------------------


def compute_atr(
    highs: list[float],
    lows: list[float],
    closes: list[float],
    period: int = 10,
) -> list[float]:
    """Average True Range."""
    n = len(closes)
    if n < 2:
        return [0.0] * n

    tr = [highs[0] - lows[0]]
    for i in range(1, n):
        tr.append(max(
            highs[i] - lows[i],
            abs(highs[i] - closes[i - 1]),
            abs(lows[i] - closes[i - 1]),
        ))

    # SMA of true range
    atr: list[float] = [0.0] * n
    if n >= period:
        atr[period - 1] = sum(tr[:period]) / period
        for i in range(period, n):
            atr[i] = (atr[i - 1] * (period - 1) + tr[i]) / period

    return atr


def compute_supertrend(
    highs: list[float],
    lows: list[float],
    closes: list[float],
    period: int = 10,
    multiplier: float = 3.0,
) -> tuple[list[float], list[bool]]:
    """Supertrend indicator.

    Returns (supertrend_values, is_uptrend).
    When is_uptrend[i] is True, supertrend[i] is the support (trailing SL for longs).
    When False, supertrend[i] is the resistance (trailing SL for shorts).
    """
    n = len(closes)
    if n < period + 1:
        return [0.0] * n, [True] * n

    atr = compute_atr(highs, lows, closes, period)

    st: list[float] = [0.0] * n
    uptrend: list[bool] = [True] * n

    for i in range(period, n):
        mid = (highs[i] + lows[i]) / 2
        basic_upper = mid + multiplier * atr[i]
        basic_lower = mid - multiplier * atr[i]

        if i == period:
            st[i] = basic_lower if closes[i] > basic_lower else basic_upper
            uptrend[i] = closes[i] > basic_lower
            continue

        if uptrend[i - 1]:
            st[i] = max(basic_lower, st[i - 1]) if closes[i] > st[i - 1] else basic_upper
        else:
            st[i] = min(basic_upper, st[i - 1]) if closes[i] < st[i - 1] else basic_lower

        uptrend[i] = closes[i] > st[i]

    return st, uptrend


try:
    from numba import njit

    @njit
    def _numba_supertrend(highs, lows, closes, period, multiplier):
        """Numba-optimized Supertrend (used when numba is available)."""
        n = len(closes)
        st = [0.0] * n
        uptrend = [True] * n
        atr_arr = [0.0] * n

        # True range
        tr = [highs[0] - lows[0]]
        for i in range(1, n):
            tr.append(max(
                highs[i] - lows[i],
                abs(highs[i] - closes[i - 1]),
                abs(lows[i] - closes[i - 1]),
            ))

        # ATR
        if n >= period:
            s = 0.0
            for j in range(period):
                s += tr[j]
            atr_arr[period - 1] = s / period
            for i in range(period, n):
                atr_arr[i] = (atr_arr[i - 1] * (period - 1) + tr[i]) / period

        # Supertrend
        for i in range(period, n):
            mid = (highs[i] + lows[i]) / 2
            basic_upper = mid + multiplier * atr_arr[i]
            basic_lower = mid - multiplier * atr_arr[i]

            if i == period:
                st[i] = basic_lower if closes[i] > basic_lower else basic_upper
                uptrend[i] = closes[i] > basic_lower
                continue

            if uptrend[i - 1]:
                st[i] = max(basic_lower, st[i - 1]) if closes[i] > st[i - 1] else basic_upper
            else:
                st[i] = min(basic_upper, st[i - 1]) if closes[i] < st[i - 1] else basic_lower

            uptrend[i] = closes[i] > st[i]

        return st, uptrend

    _HAS_NUMBA = True
except ImportError:
    _HAS_NUMBA = False


# ---------------------------------------------------------------------------
# Trailing SL calculation
# ---------------------------------------------------------------------------


def calculate_trailing_sl(
    tracker: SLTracker,
    current_price: float,
    *,
    highs: list[float] | None = None,
    lows: list[float] | None = None,
    closes: list[float] | None = None,
    atr_period: int = 14,
    supertrend_period: int = 10,
    supertrend_multiplier: float = 3.0,
) -> float | None:
    """Calculate the new trailing SL given current price and mode.

    Returns new SL price, or None if SL should not be adjusted.
    """
    mode = tracker.trail_mode
    val = tracker.trail_value
    old_sl = tracker.current_sl

    if tracker.is_long:
        # Long position: SL trails upward
        if current_price > tracker.peak_price:
            tracker.peak_price = current_price

        if mode == TrailingMode.POINTS.value:
            new_sl = tracker.peak_price - val
        elif mode == TrailingMode.PERCENTAGE.value:
            new_sl = tracker.peak_price * (1 - val / 100)
        elif mode == TrailingMode.ATR.value:
            atr_val = _latest_atr(highs or [], lows or [], closes or [], atr_period)
            new_sl = tracker.peak_price - val * atr_val
        elif mode == TrailingMode.SUPERTREND.value:
            new_sl = _latest_supertrend_sl(
                highs or [], lows or [], closes or [],
                supertrend_period, supertrend_multiplier, is_long=True,
            )
        else:
            return None

        # SL can only move UP for longs
        if new_sl > old_sl:
            return round(new_sl, 2)
    else:
        # Short position: SL trails downward
        if current_price < tracker.trough_price:
            tracker.trough_price = current_price

        if mode == TrailingMode.POINTS.value:
            new_sl = tracker.trough_price + val
        elif mode == TrailingMode.PERCENTAGE.value:
            new_sl = tracker.trough_price * (1 + val / 100)
        elif mode == TrailingMode.ATR.value:
            atr_val = _latest_atr(highs or [], lows or [], closes or [], atr_period)
            new_sl = tracker.trough_price + val * atr_val
        elif mode == TrailingMode.SUPERTREND.value:
            new_sl = _latest_supertrend_sl(
                highs or [], lows or [], closes or [],
                supertrend_period, supertrend_multiplier, is_long=False,
            )
        else:
            return None

        # SL can only move DOWN for shorts
        if old_sl == 0 or new_sl < old_sl:
            return round(new_sl, 2)

    return None


def _latest_atr(
    highs: list[float], lows: list[float], closes: list[float], period: int,
) -> float:
    """Get the latest ATR value."""
    if not closes:
        return 0.0
    atr = compute_atr(highs, lows, closes, period)
    return atr[-1] if atr else 0.0


def _latest_supertrend_sl(
    highs: list[float], lows: list[float], closes: list[float],
    period: int, multiplier: float, is_long: bool,
) -> float:
    """Get the latest Supertrend value as SL."""
    if len(closes) < period + 1:
        return 0.0

    if _HAS_NUMBA:
        st, uptrend = _numba_supertrend(highs, lows, closes, period, multiplier)
    else:
        st, uptrend = compute_supertrend(highs, lows, closes, period, multiplier)

    return st[-1]


# ---------------------------------------------------------------------------
# Trailing SL Manager
# ---------------------------------------------------------------------------


class TrailingSLManager:
    """Manage trailing stop losses across positions.

    Usage::

        mgr = TrailingSLManager()
        mgr.add_tracker(SLTracker(
            position_id="pos1", symbol="NIFTY", side="BUY",
            entry_price=24000, current_sl=23900,
            trail_mode="POINTS", trail_value=100,
        ))
        adj = mgr.update("pos1", current_price=24200)
        if adj:
            print(f"SL moved from {adj.old_sl} to {adj.new_sl}")
    """

    def __init__(self) -> None:
        self._trackers: dict[str, SLTracker] = {}
        self._adjustments: list[SLAdjustment] = []

    @property
    def trackers(self) -> dict[str, SLTracker]:
        return dict(self._trackers)

    @property
    def adjustments(self) -> list[SLAdjustment]:
        return list(self._adjustments)

    def add_tracker(self, tracker: SLTracker) -> None:
        if tracker.peak_price == 0:
            tracker.peak_price = tracker.entry_price
        if tracker.trough_price == float("inf"):
            tracker.trough_price = tracker.entry_price
        self._trackers[tracker.position_id] = tracker

    def remove_tracker(self, position_id: str) -> None:
        self._trackers.pop(position_id, None)

    def update(
        self,
        position_id: str,
        current_price: float,
        *,
        highs: list[float] | None = None,
        lows: list[float] | None = None,
        closes: list[float] | None = None,
    ) -> SLAdjustment | None:
        """Update trailing SL for a position. Returns adjustment if SL moved."""
        tracker = self._trackers.get(position_id)
        if not tracker:
            return None

        new_sl = calculate_trailing_sl(
            tracker, current_price,
            highs=highs, lows=lows, closes=closes,
        )

        if new_sl is None or new_sl == tracker.current_sl:
            return None

        adj = SLAdjustment(
            position_id=position_id,
            old_sl=tracker.current_sl,
            new_sl=new_sl,
            trigger_price=current_price,
            mode=tracker.trail_mode,
        )

        tracker.current_sl = new_sl
        tracker.adjustments += 1
        self._adjustments.append(adj)

        logger.info(
            "Trailing SL adjusted: %s %s %s → %.2f (was %.2f, peak=%.2f)",
            tracker.symbol, tracker.side, tracker.trail_mode,
            new_sl, adj.old_sl, tracker.peak_price,
        )
        return adj

    def update_all(
        self,
        prices: dict[str, float],
    ) -> list[SLAdjustment]:
        """Update all trackers with current prices. Returns list of adjustments."""
        adjustments: list[SLAdjustment] = []
        for pos_id, tracker in self._trackers.items():
            price = prices.get(tracker.symbol, 0.0)
            if price > 0:
                adj = self.update(pos_id, price)
                if adj:
                    adjustments.append(adj)
        return adjustments

    def get_sl(self, position_id: str) -> float:
        """Get current SL for a position."""
        tracker = self._trackers.get(position_id)
        return tracker.current_sl if tracker else 0.0
