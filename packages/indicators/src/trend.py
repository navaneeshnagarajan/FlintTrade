"""Trend indicators — EMA, SMA, DEMA, TEMA, WMA, HMA, Ichimoku, Parabolic SAR,
Supertrend, VWAP.

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


def tema(close: NDArray[np.float64], period: int) -> NDArray[np.float64]:
    """Triple Exponential Moving Average.

    TEMA = 3 * EMA(close, period)
         - 3 * EMA(EMA(close, period), period)
         + EMA(EMA(EMA(close, period), period), period)

    Further reduces lag compared to DEMA by applying three EMA passes.

    Args:
        close: Close prices, shape (n,).
        period: EMA period.

    Returns:
        TEMA values, shape (n,). First ``3 * (period - 1)`` values are NaN.
    """
    validate_series(close, min_length=1)

    n = len(close)
    result = np.full(n, np.nan, dtype=np.float64)

    e1 = ema(close, period)

    valid1 = ~np.isnan(e1)
    e1_valid = e1[valid1]
    if len(e1_valid) < period:
        return result

    e2_valid = ema(e1_valid, period)
    valid1_indices = np.where(valid1)[0]
    e2 = np.full(n, np.nan, dtype=np.float64)
    e2[valid1_indices] = e2_valid

    valid2 = ~np.isnan(e2)
    e2_clean = e2[valid2]
    if len(e2_clean) < period:
        return result

    e3_valid = ema(e2_clean, period)
    valid2_indices = np.where(valid2)[0]
    e3 = np.full(n, np.nan, dtype=np.float64)
    e3[valid2_indices] = e3_valid

    all_valid = ~np.isnan(e1) & ~np.isnan(e2) & ~np.isnan(e3)
    result[all_valid] = (
        3.0 * e1[all_valid] - 3.0 * e2[all_valid] + e3[all_valid]
    )
    return result


def wma(close: NDArray[np.float64], period: int) -> NDArray[np.float64]:
    """Weighted Moving Average.

    Weights are linearly increasing: bar at position i within the window
    has weight (i + 1).  The denominator is period * (period + 1) / 2.

    Args:
        close: Close prices, shape (n,).
        period: WMA window (must be >= 1).

    Returns:
        WMA values, shape (n,). First ``period - 1`` values are NaN.
    """
    validate_series(close, min_length=1)
    if period < 1:
        raise ValueError(f"WMA period must be >= 1, got {period}")

    n = len(close)
    result = np.full(n, np.nan, dtype=np.float64)
    denom = float(period * (period + 1)) / 2.0
    weights = np.arange(1, period + 1, dtype=np.float64)

    for i in range(period - 1, n):
        result[i] = np.dot(close[i - period + 1 : i + 1], weights) / denom

    return result


def hull(close: NDArray[np.float64], period: int) -> NDArray[np.float64]:
    """Hull Moving Average.

    HMA = WMA(2 * WMA(close, period // 2) - WMA(close, period), int(sqrt(period)))

    Combines speed and smoothness — minimal lag while remaining smooth.

    Args:
        close: Close prices, shape (n,).
        period: Hull period (must be >= 4 for meaningful sqrt sub-period).

    Returns:
        HMA values, shape (n,).
    """
    validate_series(close, min_length=1)
    if period < 1:
        raise ValueError(f"Hull period must be >= 1, got {period}")

    half_period = max(1, period // 2)
    sqrt_period = max(1, int(np.sqrt(period)))

    wma_half = wma(close, half_period)
    wma_full = wma(close, period)

    diff = 2.0 * wma_half - wma_full
    return wma(diff, sqrt_period)


def ichimoku(
    high: NDArray[np.float64],
    low: NDArray[np.float64],
    close: NDArray[np.float64],
    conversion_period: int = 9,
    base_period: int = 26,
    span_b_period: int = 52,
    displacement: int = 26,
) -> tuple[
    NDArray[np.float64],
    NDArray[np.float64],
    NDArray[np.float64],
    NDArray[np.float64],
    NDArray[np.float64],
]:
    """Ichimoku Cloud.

    Returns the five Ichimoku components aligned to the same index space as
    the input arrays.  Leading spans A and B are NOT shifted forward here —
    callers that need the visual cloud shift should offset by ``displacement``.

    Components:
        - Tenkan-sen (Conversion Line):  avg(highest_high, lowest_low) over conversion_period
        - Kijun-sen  (Base Line):        avg(highest_high, lowest_low) over base_period
        - Senkou Span A (Leading Span A): avg(tenkan, kijun), aligned at current bar
        - Senkou Span B (Leading Span B): avg(highest, lowest) over span_b_period
        - Chikou Span  (Lagging Span):   close shifted back by displacement bars

    Args:
        high: High prices, shape (n,).
        low:  Low prices,  shape (n,).
        close: Close prices, shape (n,).
        conversion_period: Tenkan period (default 9).
        base_period: Kijun period (default 26).
        span_b_period: Senkou Span B period (default 52).
        displacement: Cloud displacement / chikou shift (default 26).

    Returns:
        Tuple of (tenkan, kijun, senkou_a, senkou_b, chikou), each shape (n,).
    """
    validate_ohlcv(high, low, close, min_length=1)
    n = len(close)

    def _donchian_mid(period: int) -> NDArray[np.float64]:
        result = np.full(n, np.nan, dtype=np.float64)
        for i in range(period - 1, n):
            result[i] = (
                np.max(high[i - period + 1 : i + 1])
                + np.min(low[i - period + 1 : i + 1])
            ) / 2.0
        return result

    tenkan = _donchian_mid(conversion_period)
    kijun = _donchian_mid(base_period)
    senkou_a = np.where(~np.isnan(tenkan) & ~np.isnan(kijun), (tenkan + kijun) / 2.0, np.nan)
    senkou_b = _donchian_mid(span_b_period)

    # Chikou: close shifted backwards by displacement bars
    chikou = np.full(n, np.nan, dtype=np.float64)
    if displacement < n:
        chikou[: n - displacement] = close[displacement:]

    return tenkan, kijun, senkou_a, senkou_b, chikou


def parabolic_sar(
    high: NDArray[np.float64],
    low: NDArray[np.float64],
    af_step: float = 0.02,
    af_max: float = 0.2,
) -> tuple[NDArray[np.float64], NDArray[np.bool_]]:
    """Parabolic SAR.

    Classic Wilder Parabolic SAR.  Starts in uptrend using the first bar's low
    as the initial SAR and highest high seen so far as the extreme point.

    Args:
        high: High prices, shape (n,).
        low:  Low prices,  shape (n,).
        af_step: Acceleration factor increment per new extreme (default 0.02).
        af_max:  Maximum acceleration factor (default 0.2).

    Returns:
        Tuple of:
        - sar: SAR values, shape (n,). Index 0 is NaN (no prior bar).
        - uptrend: bool array, shape (n,). True = price is in uptrend.
    """
    from packages.indicators.src.utils import validate_ohlcv as _val

    _val(high, low, high, min_length=2)  # reuse ohlcv validator with high as close proxy
    n = len(high)

    sar = np.full(n, np.nan, dtype=np.float64)
    uptrend = np.ones(n, dtype=np.bool_)

    # Initialise at bar 1 (first bar we can compute SAR for)
    _up = True
    _af = af_step
    _ep = high[0]  # extreme point
    _sar = low[0]  # SAR starts below first bar in uptrend

    for i in range(1, n):
        # Tentative SAR for this bar
        _sar_new = _sar + _af * (_ep - _sar)

        # Ensure SAR doesn't go above the two prior lows (uptrend)
        # or below the two prior highs (downtrend)
        if _up:
            _sar_new = min(_sar_new, low[i - 1])
            if i >= 2:
                _sar_new = min(_sar_new, low[i - 2])
        else:
            _sar_new = max(_sar_new, high[i - 1])
            if i >= 2:
                _sar_new = max(_sar_new, high[i - 2])

        # Flip check
        if _up and low[i] < _sar_new:
            _up = False
            _sar_new = _ep  # flip: SAR becomes the prior extreme
            _ep = low[i]
            _af = af_step
        elif not _up and high[i] > _sar_new:
            _up = True
            _sar_new = _ep
            _ep = high[i]
            _af = af_step
        else:
            # Update extreme point and AF
            if _up and high[i] > _ep:
                _ep = high[i]
                _af = min(_af + af_step, af_max)
            elif not _up and low[i] < _ep:
                _ep = low[i]
                _af = min(_af + af_step, af_max)

        sar[i] = _sar_new
        uptrend[i] = _up
        _sar = _sar_new

    return sar, uptrend
