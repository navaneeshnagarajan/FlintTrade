"""Trend indicators — EMA, SMA, DEMA, TEMA, WMA, HMA, Ichimoku, Parabolic SAR,
Supertrend, VWAP, KAMA, ADX, DMI, LinReg.

All functions:
- Accept numpy float64 arrays
- Return numpy float64 arrays (or tuples thereof)
- Fill NaN for bars where insufficient history exists
- Do NOT forward-fill
"""

from __future__ import annotations

import numpy as np
from numpy.typing import NDArray

from packages.indicators.src.numba_kernels import HAS_NUMBA, _ema_core
from packages.indicators.src.utils import validate_ohlcv, validate_series

# Threshold: use Numba JIT only when array length exceeds this value.
# Below this, JIT compilation overhead exceeds the loop speedup.
_NUMBA_THRESHOLD = 1000


def ema(close: NDArray[np.float64], period: int) -> NDArray[np.float64]:
    """Exponential Moving Average.

    Seeded with the simple mean of the first ``period`` bars. Each subsequent
    bar uses the standard EMA multiplier k = 2 / (period + 1).

    When numba is installed and the array is large enough (> 1000 elements),
    the inner loop is JIT-compiled for a ~5-10x speedup.

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
    seed = float(np.nanmean(close[:period]))

    if HAS_NUMBA and n > _NUMBA_THRESHOLD:
        # JIT path: run inner loop through Numba kernel
        sliced = np.ascontiguousarray(close[period - 1 :], dtype=np.float64)
        jit_values = _ema_core(sliced, k, seed)
        result[period - 1 :] = jit_values
    else:
        # Pure-Python path
        result[period - 1] = seed
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
    with np.errstate(divide="ignore", invalid="ignore"):
        result = np.where(cum_vol > 0, cum_tp_vol / cum_vol, np.nan)
    return result


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


def kama(
    close: NDArray[np.float64],
    period: int = 10,
    fast_period: int = 2,
    slow_period: int = 30,
) -> NDArray[np.float64]:
    """Kaufman Adaptive Moving Average.

    KAMA adjusts its smoothing constant based on the Efficiency Ratio (ER),
    which measures directional movement relative to total path length. When
    price moves efficiently, KAMA tracks closely; in noisy markets it barely
    moves.

    ER       = abs(close[i] - close[i - period]) / sum(abs(diff(close)), period)
    fast_sc  = 2 / (fast_period + 1)
    slow_sc  = 2 / (slow_period + 1)
    sc       = (ER * (fast_sc - slow_sc) + slow_sc) ** 2
    KAMA[i]  = KAMA[i-1] + sc * (close[i] - KAMA[i-1])

    Args:
        close: Close prices, shape (n,).
        period: Efficiency ratio period (default 10).
        fast_period: Fast EMA period for SC calculation (default 2).
        slow_period: Slow EMA period for SC calculation (default 30).

    Returns:
        KAMA values, shape (n,). First ``period`` values are NaN.

    Raises:
        ValueError: If period < 1 or fast_period >= slow_period.
    """
    validate_series(close, min_length=period + 1)
    if period < 1:
        raise ValueError(f"KAMA period must be >= 1, got {period}")
    if fast_period >= slow_period:
        raise ValueError(
            f"fast_period ({fast_period}) must be < slow_period ({slow_period})"
        )

    n = len(close)
    result = np.full(n, np.nan, dtype=np.float64)

    fast_sc = 2.0 / (fast_period + 1.0)
    slow_sc = 2.0 / (slow_period + 1.0)
    sc_range = fast_sc - slow_sc

    # Seed KAMA at index `period` with the close value at that bar
    result[period] = close[period]

    abs_diff = np.abs(np.diff(close))  # shape (n-1,)

    for i in range(period + 1, n):
        direction = abs(close[i] - close[i - period])
        # sum of absolute 1-bar changes over last `period` bars
        noise = float(np.sum(abs_diff[i - period : i]))
        er = direction / noise if noise != 0.0 else 0.0
        sc = (er * sc_range + slow_sc) ** 2
        result[i] = result[i - 1] + sc * (close[i] - result[i - 1])

    return result


def adx(
    high: NDArray[np.float64],
    low: NDArray[np.float64],
    close: NDArray[np.float64],
    period: int = 14,
) -> NDArray[np.float64]:
    """Average Directional Index.

    ADX measures trend strength without regard to direction.  Values above 25
    typically indicate a strong trend; below 20 indicates a trendless market.

    Computed via Wilder smoothing of the Directional Movement indices:
        +DM = max(high - prev_high, 0) if > max(prev_low - low, 0) else 0
        -DM = max(prev_low - low, 0)   if > max(high - prev_high, 0) else 0
        TR  = max(high-low, |high-prev_close|, |low-prev_close|)
        +DI = 100 * Wilder(+DM, period) / Wilder(TR, period)
        -DI = 100 * Wilder(-DM, period) / Wilder(TR, period)
        DX  = 100 * |+DI - -DI| / (+DI + -DI)
        ADX = Wilder(DX, period)

    Args:
        high: High prices, shape (n,).
        low: Low prices, shape (n,).
        close: Close prices, shape (n,).
        period: Smoothing period (default 14).

    Returns:
        ADX values, shape (n,). First ``2 * period - 1`` values are NaN.
    """
    validate_ohlcv(high, low, close, min_length=2)
    n = len(close)
    result = np.full(n, np.nan, dtype=np.float64)

    if n < 2 * period:
        return result

    # Raw per-bar DM and TR
    plus_dm = np.zeros(n, dtype=np.float64)
    minus_dm = np.zeros(n, dtype=np.float64)
    tr = np.zeros(n, dtype=np.float64)
    tr[0] = high[0] - low[0]

    for i in range(1, n):
        up_move = high[i] - high[i - 1]
        down_move = low[i - 1] - low[i]
        if up_move > down_move and up_move > 0.0:
            plus_dm[i] = up_move
        if down_move > up_move and down_move > 0.0:
            minus_dm[i] = down_move
        tr[i] = max(
            high[i] - low[i],
            abs(high[i] - close[i - 1]),
            abs(low[i] - close[i - 1]),
        )

    # Seed Wilder smoothed values at index `period`
    s_tr = float(np.sum(tr[1 : period + 1]))
    s_plus = float(np.sum(plus_dm[1 : period + 1]))
    s_minus = float(np.sum(minus_dm[1 : period + 1]))

    # Store smoothed arrays
    sm_tr = np.full(n, np.nan, dtype=np.float64)
    sm_plus = np.full(n, np.nan, dtype=np.float64)
    sm_minus = np.full(n, np.nan, dtype=np.float64)
    dx_arr = np.full(n, np.nan, dtype=np.float64)

    sm_tr[period] = s_tr
    sm_plus[period] = s_plus
    sm_minus[period] = s_minus

    def _dx(sp: float, sm: float, t: float) -> float:
        if t == 0.0:
            return 0.0
        pdi = 100.0 * sp / t
        mdi = 100.0 * sm / t
        denom = pdi + mdi
        return 100.0 * abs(pdi - mdi) / denom if denom != 0.0 else 0.0

    dx_arr[period] = _dx(s_plus, s_minus, s_tr)

    for i in range(period + 1, n):
        s_tr = s_tr - s_tr / period + tr[i]
        s_plus = s_plus - s_plus / period + plus_dm[i]
        s_minus = s_minus - s_minus / period + minus_dm[i]
        sm_tr[i] = s_tr
        sm_plus[i] = s_plus
        sm_minus[i] = s_minus
        dx_arr[i] = _dx(s_plus, s_minus, s_tr)

    # Seed ADX with mean of first `period` DX values (index period..2*period-1)
    adx_seed_end = 2 * period - 1
    if adx_seed_end >= n:
        return result

    result[adx_seed_end] = float(np.mean(dx_arr[period : adx_seed_end + 1]))
    for i in range(adx_seed_end + 1, n):
        result[i] = (result[i - 1] * (period - 1) + dx_arr[i]) / period

    return result


def dmi(
    high: NDArray[np.float64],
    low: NDArray[np.float64],
    close: NDArray[np.float64],
    period: int = 14,
) -> tuple[NDArray[np.float64], NDArray[np.float64]]:
    """Directional Movement Index — returns (+DI, -DI).

    +DI and -DI are the smoothed directional indicators that form the basis of
    ADX. Crossovers between +DI and -DI signal potential trend changes.

    Args:
        high: High prices, shape (n,).
        low: Low prices, shape (n,).
        close: Close prices, shape (n,).
        period: Wilder smoothing period (default 14).

    Returns:
        Tuple of (plus_di, minus_di) arrays, each shape (n,).
        First ``period`` values are NaN in both arrays.
    """
    validate_ohlcv(high, low, close, min_length=2)
    n = len(close)
    plus_di = np.full(n, np.nan, dtype=np.float64)
    minus_di = np.full(n, np.nan, dtype=np.float64)

    if n < period + 1:
        return plus_di, minus_di

    raw_plus_dm = np.zeros(n, dtype=np.float64)
    raw_minus_dm = np.zeros(n, dtype=np.float64)
    tr = np.zeros(n, dtype=np.float64)
    tr[0] = high[0] - low[0]

    for i in range(1, n):
        up_move = high[i] - high[i - 1]
        down_move = low[i - 1] - low[i]
        if up_move > down_move and up_move > 0.0:
            raw_plus_dm[i] = up_move
        if down_move > up_move and down_move > 0.0:
            raw_minus_dm[i] = down_move
        tr[i] = max(
            high[i] - low[i],
            abs(high[i] - close[i - 1]),
            abs(low[i] - close[i - 1]),
        )

    s_tr = float(np.sum(tr[1 : period + 1]))
    s_plus = float(np.sum(raw_plus_dm[1 : period + 1]))
    s_minus = float(np.sum(raw_minus_dm[1 : period + 1]))

    def _di(s_dm: float, s_t: float) -> float:
        return 100.0 * s_dm / s_t if s_t != 0.0 else 0.0

    plus_di[period] = _di(s_plus, s_tr)
    minus_di[period] = _di(s_minus, s_tr)

    for i in range(period + 1, n):
        s_tr = s_tr - s_tr / period + tr[i]
        s_plus = s_plus - s_plus / period + raw_plus_dm[i]
        s_minus = s_minus - s_minus / period + raw_minus_dm[i]
        plus_di[i] = _di(s_plus, s_tr)
        minus_di[i] = _di(s_minus, s_tr)

    return plus_di, minus_di


def linreg(close: NDArray[np.float64], period: int = 14) -> NDArray[np.float64]:
    """Linear Regression Value.

    For each bar, fits a least-squares line to the preceding ``period`` bars
    and returns the endpoint (fitted value at the current bar) of that line.
    This is equivalent to the TradingView LINREG function.

    Args:
        close: Close prices, shape (n,).
        period: Regression window length (default 14).

    Returns:
        Linear regression values, shape (n,). First ``period - 1`` values are
        NaN.

    Raises:
        ValueError: If period < 2.
    """
    validate_series(close, min_length=1)
    if period < 2:
        raise ValueError(f"linreg period must be >= 2, got {period}")

    n = len(close)
    result = np.full(n, np.nan, dtype=np.float64)

    # Pre-compute x values and their statistics for the window
    x = np.arange(period, dtype=np.float64)
    x_mean = float(np.mean(x))
    x_var = float(np.sum((x - x_mean) ** 2))  # sum of squared deviations

    if x_var == 0.0:
        return result

    for i in range(period - 1, n):
        y = close[i - period + 1 : i + 1]
        y_mean = float(np.mean(y))
        cov = float(np.sum((x - x_mean) * (y - y_mean)))
        slope = cov / x_var
        result[i] = y_mean + slope * (x[-1] - x_mean)

    return result
