"""Trend indicators — EMA, SMA, DEMA, Supertrend, VWAP.

All functions:
- Accept numpy float64 arrays
- Return numpy float64 arrays (or tuples thereof)
- Fill NaN for bars where insufficient history exists
- Do NOT forward-fill
"""

from __future__ import annotations

import numpy as np
from numpy.typing import NDArray

from packages.indicators.src.utils import validate_ohlcv, validate_series


def ema(close: NDArray[np.float64], period: int) -> NDArray[np.float64]:
    """Exponential Moving Average.

    Seeded with the simple mean of the first ``period`` bars. Each subsequent
    bar uses the standard EMA multiplier k = 2 / (period + 1).

    Args:
        close: Close prices, shape (n,).
        period: EMA period (must be >= 1).

    Returns:
        EMA values, shape (n,). First ``period - 1`` values are NaN.

    Raises:
        ValueError: If period < 1 or series is empty.
    """
    validate_series(close, min_length=1)
    if period < 1:
        raise ValueError(f"EMA period must be >= 1, got {period}")

    n = len(close)
    result = np.full(n, np.nan, dtype=np.float64)

    if n < period:
        return result

    k = 2.0 / (period + 1)
    result[period - 1] = np.mean(close[:period])
    for i in range(period, n):
        result[i] = close[i] * k + result[i - 1] * (1.0 - k)

    return result


def sma(close: NDArray[np.float64], period: int) -> NDArray[np.float64]:
    """Simple Moving Average.

    Args:
        close: Close prices, shape (n,).
        period: SMA window (must be >= 1).

    Returns:
        SMA values, shape (n,). First ``period - 1`` values are NaN.
    """
    validate_series(close, min_length=1)
    if period < 1:
        raise ValueError(f"SMA period must be >= 1, got {period}")

    n = len(close)
    result = np.full(n, np.nan, dtype=np.float64)

    for i in range(period - 1, n):
        result[i] = np.mean(close[i - period + 1 : i + 1])

    return result


def dema(close: NDArray[np.float64], period: int) -> NDArray[np.float64]:
    """Double Exponential Moving Average.

    DEMA = 2 * EMA(close, period) - EMA(EMA(close, period), period)

    DEMA responds faster to price changes than a plain EMA of the same period
    because it subtracts the lag introduced by the second EMA pass.

    Args:
        close: Close prices, shape (n,).
        period: EMA period.

    Returns:
        DEMA values, shape (n,). First ``2 * (period - 1)`` values are NaN.
    """
    validate_series(close, min_length=1)

    e1 = ema(close, period)

    # Only compute EMA of EMA over the valid (non-NaN) portion of e1
    valid_mask = ~np.isnan(e1)
    valid_e1 = e1[valid_mask]

    n = len(close)
    result = np.full(n, np.nan, dtype=np.float64)

    if len(valid_e1) < period:
        return result

    e2_valid = ema(valid_e1, period)

    # Map e2 back to the original index space
    valid_indices = np.where(valid_mask)[0]
    e2 = np.full(n, np.nan, dtype=np.float64)
    e2[valid_indices] = e2_valid

    # DEMA = 2 * e1 - e2 wherever both are non-NaN
    both_valid = ~np.isnan(e1) & ~np.isnan(e2)
    result[both_valid] = 2.0 * e1[both_valid] - e2[both_valid]

    return result


def supertrend(
    high: NDArray[np.float64],
    low: NDArray[np.float64],
    close: NDArray[np.float64],
    period: int = 10,
    multiplier: float = 3.0,
) -> tuple[NDArray[np.float64], NDArray[np.bool_]]:
    """Supertrend indicator.

    Supertrend rides an ATR-derived band above or below price. When price
    closes below the upper band (downtrend) or above the lower band (uptrend),
    the direction flips.

    Args:
        high: High prices, shape (n,).
        low: Low prices, shape (n,).
        close: Close prices, shape (n,).
        period: ATR period (default 10).
        multiplier: ATR multiplier for band width (default 3.0).

    Returns:
        Tuple of:
        - supertrend_values: shape (n,), NaN for bars before ATR warms up.
        - direction: bool array, shape (n,). True = uptrend, False = downtrend.
    """
    from packages.indicators.src.volatility import atr as _atr

    validate_ohlcv(high, low, close, min_length=2)
    n = len(close)

    atr_vals = _atr(high, low, close, period)
    hl2 = (high + low) / 2.0

    # Basic bands (raw, before carryover logic)
    basic_upper = hl2 + multiplier * atr_vals
    basic_lower = hl2 - multiplier * atr_vals

    # Final bands (with carryover) and output arrays
    final_upper = np.full(n, np.nan, dtype=np.float64)
    final_lower = np.full(n, np.nan, dtype=np.float64)
    st = np.full(n, np.nan, dtype=np.float64)
    direction = np.ones(n, dtype=np.bool_)  # default: uptrend

    # Start from index where ATR is first valid
    start = period - 1

    if start >= n:
        return st, direction

    for i in range(start, n):
        if i == start:
            final_upper[i] = basic_upper[i]
            final_lower[i] = basic_lower[i]
            # Initial direction: uptrend if close > lower band
            direction[i] = close[i] > final_lower[i]
            st[i] = final_lower[i] if direction[i] else final_upper[i]
            continue

        # Carry-over lower band: only tighten (raise floor) when in uptrend
        if basic_lower[i] > final_lower[i - 1] or close[i - 1] < final_lower[i - 1]:
            final_lower[i] = basic_lower[i]
        else:
            final_lower[i] = final_lower[i - 1]

        # Carry-over upper band: only tighten (lower ceiling) when in downtrend
        if basic_upper[i] < final_upper[i - 1] or close[i - 1] > final_upper[i - 1]:
            final_upper[i] = basic_upper[i]
        else:
            final_upper[i] = final_upper[i - 1]

        # Determine direction flip
        if direction[i - 1]:  # was uptrend
            if close[i] < final_lower[i]:
                direction[i] = False  # flip to downtrend
                st[i] = final_upper[i]
            else:
                direction[i] = True
                st[i] = final_lower[i]
        else:  # was downtrend
            if close[i] > final_upper[i]:
                direction[i] = True  # flip to uptrend
                st[i] = final_lower[i]
            else:
                direction[i] = False
                st[i] = final_upper[i]

    return st, direction


def vwap(
    high: NDArray[np.float64],
    low: NDArray[np.float64],
    close: NDArray[np.float64],
    volume: NDArray[np.float64],
) -> NDArray[np.float64]:
    """Volume Weighted Average Price (intraday, cumulative from bar 0).

    VWAP = cumsum(typical_price * volume) / cumsum(volume)
    where typical_price = (high + low + close) / 3.

    Designed for intraday data — reset at session open by slicing the input
    arrays to the current session before calling.

    Args:
        high: High prices, shape (n,).
        low: Low prices, shape (n,).
        close: Close prices, shape (n,).
        volume: Volume, shape (n,). Values must be >= 0.

    Returns:
        VWAP values, shape (n,). NaN where cumulative volume is 0.
    """
    validate_ohlcv(high, low, close)
    validate_series(volume, min_length=1)

    typical_price = (high + low + close) / 3.0
    cum_tp_vol = np.cumsum(typical_price * volume)
    cum_vol = np.cumsum(volume)
    return np.where(cum_vol > 0, cum_tp_vol / cum_vol, np.nan)
