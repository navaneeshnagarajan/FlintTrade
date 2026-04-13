"""Trend indicators — EMA, SMA, DEMA, TEMA, WMA, HMA, Ichimoku, Parabolic SAR,
Supertrend, VWAP, KAMA, ADX, DMI, LinReg, ALMA, T3, FRAMA, McGinley Dynamic,
VIDYA, Alligator, MovingAverageEnvelopes, TRIMA.

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


def _rma(close: NDArray[np.float64], period: int) -> NDArray[np.float64]:
    """Wilder / Running Moving Average (internal helper).

    RMA uses alpha = 1 / period, seeded with the SMA of the first ``period``
    bars.  This is the same smoothing used by ATR and ADX.

    Args:
        close: Input series, shape (n,).
        period: Smoothing period (>= 1).

    Returns:
        RMA values, shape (n,). First ``period - 1`` values are NaN.
    """
    n = len(close)
    result = np.full(n, np.nan, dtype=np.float64)
    if n < period:
        return result
    alpha = 1.0 / period
    result[period - 1] = float(np.mean(close[:period]))
    for i in range(period, n):
        result[i] = alpha * close[i] + (1.0 - alpha) * result[i - 1]
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


def alma(
    close: NDArray[np.float64],
    period: int = 9,
    offset: float = 0.85,
    sigma: float = 6.0,
) -> NDArray[np.float64]:
    """Arnaud Legoux Moving Average.

    ALMA uses a Gaussian distribution of weights along the window to combine
    low lag (high offset) with low noise (high sigma). It is computed as the
    normalised weighted sum of prices within the rolling window.

    Formula:
        m = floor(offset * (period - 1))
        s = period / sigma
        w[j] = exp(-((j - m)^2) / (2 * s^2))   for j in 0..period-1
        ALMA[i] = sum(w[j] * close[i - period + 1 + j]) / sum(w)

    Args:
        close: Close prices, shape (n,).
        period: Window length (default 9).
        offset: Gaussian centre offset in [0, 1]. Higher values favour recent
            prices (lower lag); lower values favour older prices (more smooth).
            Default 0.85.
        sigma: Gaussian width divisor. Higher values produce smoother output.
            Default 6.0.

    Returns:
        ALMA values, shape (n,). First ``period - 1`` values are NaN.

    Raises:
        ValueError: If period < 1 or sigma <= 0.
    """
    validate_series(close, min_length=period)
    if period < 1:
        raise ValueError(f"alma period must be >= 1, got {period}")
    if sigma <= 0.0:
        raise ValueError(f"alma sigma must be > 0, got {sigma}")

    n = len(close)
    result = np.full(n, np.nan, dtype=np.float64)

    m = float(np.floor(offset * (period - 1)))
    s = period / sigma
    j_arr = np.arange(period, dtype=np.float64)
    weights = np.exp(-((j_arr - m) ** 2) / (2.0 * s * s))
    w_sum = float(np.sum(weights))

    if w_sum == 0.0:
        return result

    for i in range(period - 1, n):
        window = close[i - period + 1 : i + 1]
        result[i] = float(np.dot(window, weights)) / w_sum

    return result


def t3(
    close: NDArray[np.float64],
    period: int = 5,
    vfactor: float = 0.7,
) -> NDArray[np.float64]:
    """T3 Moving Average (Tillson).

    T3 is a six-stage EMA combination that achieves extremely low lag while
    remaining smooth. The volume factor ``vfactor`` (default 0.7) controls the
    trade-off between smoothness and responsiveness.

    Formula (each stage applied on the previous stage's output):
        c1 = -(vfactor^3)
        c2 =  3*vfactor^2 + 3*vfactor^3
        c3 = -6*vfactor^2 - 3*vfactor - 3*vfactor^3
        c4 =  1 + 3*vfactor + vfactor^3 + 3*vfactor^2
        e1..e6 = successive EMA passes
        T3 = c1*e6 + c2*e5 + c3*e4 + c4*e3

    Args:
        close: Close prices, shape (n,).
        period: EMA period for each of the six passes (default 5).
        vfactor: Volume factor controlling smoothness vs lag (default 0.7).

    Returns:
        T3 values, shape (n,). Leading NaN region grows with each EMA pass.

    Raises:
        ValueError: If vfactor not in (0, 1] or period < 1.
    """
    validate_series(close, min_length=period)
    if period < 1:
        raise ValueError(f"t3 period must be >= 1, got {period}")
    if not (0.0 < vfactor <= 1.0):
        raise ValueError(f"t3 vfactor must be in (0, 1], got {vfactor}")

    v2 = vfactor * vfactor
    v3 = v2 * vfactor
    c1 = -v3
    c2 = 3.0 * v2 + 3.0 * v3
    c3 = -6.0 * v2 - 3.0 * vfactor - 3.0 * v3
    c4 = 1.0 + 3.0 * vfactor + v3 + 3.0 * v2

    def _ema_valid(arr: NDArray[np.float64], p: int) -> NDArray[np.float64]:
        """EMA computed only over the valid (non-NaN) portion of arr."""
        mask = ~np.isnan(arr)
        valid = arr[mask]
        if len(valid) < p:
            return arr.copy()
        e_valid = ema(valid, p)
        out = arr.copy()
        out[mask] = e_valid
        return out

    e1 = ema(close, period)
    e2 = _ema_valid(e1, period)
    e3 = _ema_valid(e2, period)
    e4 = _ema_valid(e3, period)
    e5 = _ema_valid(e4, period)
    e6 = _ema_valid(e5, period)

    n = len(close)
    result = np.full(n, np.nan, dtype=np.float64)
    valid = ~np.isnan(e3) & ~np.isnan(e4) & ~np.isnan(e5) & ~np.isnan(e6)
    result[valid] = (
        c1 * e6[valid] + c2 * e5[valid] + c3 * e4[valid] + c4 * e3[valid]
    )
    return result


def frama(
    close: NDArray[np.float64],
    period: int = 16,
) -> NDArray[np.float64]:
    """Fractal Adaptive Moving Average.

    FRAMA dynamically adjusts its smoothing constant using the fractal dimension
    of the price series over the window.  In trending markets the fractal
    dimension is near 1 (fast tracking); in choppy markets it approaches 2
    (slow, highly smoothed).

    Formula:
        For each window of size ``period`` (must be even):
          n1 = (highest(close, half) - lowest(close, half)) / half
          n2 = (highest(close[half:], half) - lowest(close[half:], half)) / half
          n3 = (highest(close, period) - lowest(close, period)) / period
          D  = (log(n1 + n2) - log(n3)) / log(2)
          alpha = exp(-4.6 * (D - 1))
          alpha = clamp(alpha, 0.01, 1.0)
          FRAMA[i] = alpha * close[i] + (1 - alpha) * FRAMA[i-1]

    Args:
        close: Close prices, shape (n,).
        period: Window length (default 16, must be even and >= 4).

    Returns:
        FRAMA values, shape (n,). First ``period - 1`` values are NaN.

    Raises:
        ValueError: If period is odd or < 4.
    """
    validate_series(close, min_length=period)
    if period < 4:
        raise ValueError(f"frama period must be >= 4, got {period}")
    if period % 2 != 0:
        raise ValueError(f"frama period must be even, got {period}")

    n = len(close)
    result = np.full(n, np.nan, dtype=np.float64)
    half = period // 2

    # Seed FRAMA at first valid bar
    result[period - 1] = close[period - 1]

    for i in range(period - 1, n):
        window = close[i - period + 1 : i + 1]
        w1 = window[:half]
        w2 = window[half:]

        hi1, lo1 = float(np.max(w1)), float(np.min(w1))
        hi2, lo2 = float(np.max(w2)), float(np.min(w2))
        hi3, lo3 = float(np.max(window)), float(np.min(window))

        n1 = (hi1 - lo1) / half
        n2 = (hi2 - lo2) / half
        n3 = (hi3 - lo3) / period if period > 0 else 0.0

        if n1 + n2 <= 0.0 or n3 <= 0.0:
            alpha = 0.01
        else:
            denom = np.log(2.0)
            d = (np.log(n1 + n2) - np.log(n3)) / denom if denom != 0.0 else 1.0
            alpha = float(np.exp(-4.6 * (d - 1.0)))
            alpha = max(0.01, min(1.0, alpha))

        if i == period - 1:
            result[i] = close[i]
        else:
            prev = result[i - 1]
            if np.isnan(prev):
                result[i] = close[i]
            else:
                result[i] = alpha * close[i] + (1.0 - alpha) * prev

    return result


def mcginley_dynamic(
    close: NDArray[np.float64],
    period: int = 14,
) -> NDArray[np.float64]:
    """McGinley Dynamic Indicator.

    Developed by John R. McGinley, this indicator automatically adjusts its
    speed based on the ratio between the current price and the previous
    indicator value.  This self-adjusting nature eliminates whipsaws and keeps
    the line closely aligned with prices.

    Formula:
        MD[i] = MD[i-1] + (close[i] - MD[i-1]) / (period * (close[i] / MD[i-1])^4)

    Seeded with the SMA of the first ``period`` bars.

    Args:
        close: Close prices, shape (n,). All values must be > 0.
        period: Period constant (default 14).

    Returns:
        McGinley Dynamic values, shape (n,). First ``period - 1`` values are
        NaN.

    Raises:
        ValueError: If period < 1 or any close <= 0.
    """
    validate_series(close, min_length=period)
    if period < 1:
        raise ValueError(f"mcginley_dynamic period must be >= 1, got {period}")
    if np.any(close <= 0.0):
        raise ValueError("mcginley_dynamic requires all close prices to be strictly positive.")

    n = len(close)
    result = np.full(n, np.nan, dtype=np.float64)

    # Seed with SMA of first period bars
    seed = float(np.mean(close[:period]))
    result[period - 1] = seed

    for i in range(period, n):
        prev = result[i - 1]
        ratio = close[i] / prev
        denom = period * (ratio ** 4)
        result[i] = prev + (close[i] - prev) / denom if denom != 0.0 else prev

    return result


def vidya(
    close: NDArray[np.float64],
    cmo_period: int = 9,
    ema_period: int = 12,
) -> NDArray[np.float64]:
    """Variable Index Dynamic Average.

    VIDYA was introduced by Tushar Chande. It adapts its smoothing constant
    using the absolute value of the Chande Momentum Oscillator (CMO) as a
    volatility index — the faster the momentum, the faster the average tracks.

    Formula:
        vi    = abs(CMO(close, cmo_period)) / 100  (volatility index in [0, 1])
        alpha = 2 / (ema_period + 1)
        VIDYA[i] = alpha * vi * close[i] + (1 - alpha * vi) * VIDYA[i-1]

    Args:
        close: Close prices, shape (n,).
        cmo_period: Period for the CMO volatility index (default 9).
        ema_period: Base EMA period controlling the alpha constant (default 12).

    Returns:
        VIDYA values, shape (n,). NaN until both CMO and VIDYA are seeded.

    Raises:
        ValueError: If either period < 1.
    """
    from packages.indicators.src.momentum import cmo as _cmo

    validate_series(close, min_length=cmo_period + 1)
    if cmo_period < 1:
        raise ValueError(f"vidya cmo_period must be >= 1, got {cmo_period}")
    if ema_period < 1:
        raise ValueError(f"vidya ema_period must be >= 1, got {ema_period}")

    n = len(close)
    result = np.full(n, np.nan, dtype=np.float64)
    cmo_vals = _cmo(close, cmo_period)
    alpha = 2.0 / (ema_period + 1.0)

    # First valid bar: seed with close value
    first_valid = cmo_period  # cmo produces first valid at index cmo_period
    if first_valid >= n:
        return result

    result[first_valid] = close[first_valid]

    for i in range(first_valid + 1, n):
        if np.isnan(cmo_vals[i]):
            continue
        vi = abs(cmo_vals[i]) / 100.0
        prev = result[i - 1]
        if np.isnan(prev):
            result[i] = close[i]
        else:
            sc = alpha * vi
            result[i] = sc * close[i] + (1.0 - sc) * prev

    return result


def alligator(
    high: NDArray[np.float64],
    low: NDArray[np.float64],
    jaw_period: int = 13,
    jaw_offset: int = 8,
    teeth_period: int = 8,
    teeth_offset: int = 5,
    lips_period: int = 5,
    lips_offset: int = 3,
) -> tuple[NDArray[np.float64], NDArray[np.float64], NDArray[np.float64]]:
    """Williams Alligator Indicator.

    Developed by Bill Williams.  Three smoothed moving averages of the bar
    midpoint are computed and then shifted forward (displaced into the future)
    by different amounts to visualise trend and its absence.

    Components:
        Jaw   (Blue):   SMMA(midpoint, jaw_period)   shifted forward jaw_offset bars
        Teeth (Red):    SMMA(midpoint, teeth_period) shifted forward teeth_offset bars
        Lips  (Green):  SMMA(midpoint, lips_period)  shifted forward lips_offset bars

    where midpoint = (high + low) / 2 and SMMA = Smoothed Moving Average (Wilder RMA).

    Args:
        high: High prices, shape (n,).
        low: Low prices, shape (n,).
        jaw_period: Jaw SMMA period (default 13).
        jaw_offset: Jaw displacement bars (default 8).
        teeth_period: Teeth SMMA period (default 8).
        teeth_offset: Teeth displacement bars (default 5).
        lips_period: Lips SMMA period (default 5).
        lips_offset: Lips displacement bars (default 3).

    Returns:
        Tuple of (jaw, teeth, lips) arrays, each shape (n,).  Values are NaN
        where the SMMA has not yet warmed up AND for the final
        ``offset`` bars of each line (shifted out of range).
    """
    validate_ohlcv(high, low, high, min_length=1)
    n = len(high)
    midpoint = (high + low) / 2.0

    def _smma_shifted(period: int, offset: int) -> NDArray[np.float64]:
        raw = _rma(midpoint, period)
        out = np.full(n, np.nan, dtype=np.float64)
        # Shift the series forward by ``offset`` bars
        end = n - offset
        if end > 0:
            out[offset : offset + end] = raw[:end]
        return out

    jaw = _smma_shifted(jaw_period, jaw_offset)
    teeth = _smma_shifted(teeth_period, teeth_offset)
    lips = _smma_shifted(lips_period, lips_offset)

    return jaw, teeth, lips


def moving_average_envelopes(
    close: NDArray[np.float64],
    period: int = 20,
    pct: float = 2.5,
    ma_type: str = "sma",
) -> tuple[NDArray[np.float64], NDArray[np.float64], NDArray[np.float64]]:
    """Moving Average Envelopes.

    Bands are placed a fixed percentage above and below a central moving
    average.  The envelope defines a "normal" price range; moves outside the
    bands are potential signals.

    Formula:
        upper = MA * (1 + pct / 100)
        lower = MA * (1 - pct / 100)

    Args:
        close: Close prices, shape (n,).
        period: MA period (default 20).
        pct: Envelope width as a percentage of the MA (default 2.5).
        ma_type: Moving average type — ``"sma"`` or ``"ema"`` (default ``"sma"``).

    Returns:
        Tuple of (upper, middle, lower) arrays, each shape (n,).

    Raises:
        ValueError: If pct <= 0 or ma_type is unrecognised.
    """
    validate_series(close, min_length=period)
    if pct <= 0.0:
        raise ValueError(f"moving_average_envelopes pct must be > 0, got {pct}")
    ma_type = ma_type.lower()
    if ma_type not in ("sma", "ema"):
        raise ValueError(f"moving_average_envelopes ma_type must be 'sma' or 'ema', got {ma_type!r}")

    middle = sma(close, period) if ma_type == "sma" else ema(close, period)
    factor = pct / 100.0
    upper = middle * (1.0 + factor)
    lower = middle * (1.0 - factor)
    return upper, middle, lower


def trima(close: NDArray[np.float64], period: int = 20) -> NDArray[np.float64]:
    """Triangular Moving Average.

    TRIMA is a double-smoothed SMA that places more weight on the middle
    portion of the data.  It is equivalent to the SMA of an SMA and is notably
    smoother than a plain SMA of the same period.

    Formula:
        half = ceil(period / 2)
        first_sma  = SMA(close, half)
        TRIMA      = SMA(first_sma, half)

    Args:
        close: Close prices, shape (n,).
        period: Total TRIMA period (default 20).

    Returns:
        TRIMA values, shape (n,). First ``period - 1`` values are NaN.

    Raises:
        ValueError: If period < 2.
    """
    validate_series(close, min_length=period)
    if period < 2:
        raise ValueError(f"trima period must be >= 2, got {period}")

    half = int(np.ceil(period / 2.0))

    first_sma = sma(close, half)

    # Compute the second SMA only over the valid portion of first_sma
    valid_mask = ~np.isnan(first_sma)
    valid_first = first_sma[valid_mask]

    n = len(close)
    result = np.full(n, np.nan, dtype=np.float64)

    if len(valid_first) < half:
        return result

    second_sma_valid = sma(valid_first, half)
    valid_indices = np.where(valid_mask)[0]
    result[valid_indices] = second_sma_valid

    return result
