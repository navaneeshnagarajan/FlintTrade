"""Momentum indicators — RSI, MACD, Stochastic, Williams %R, CCI, ROC, CMO,
TRIX, StochRSI, BOP, MOM, Awesome Oscillator, Squeeze Momentum, DPO,
Fisher Transform, CRSI, ElderRay.

All functions:
- Accept numpy float64 arrays
- Return numpy float64 arrays (or tuples thereof)
- Fill NaN for bars where insufficient history exists
- Do NOT forward-fill
"""

from __future__ import annotations

import numpy as np
from numpy.typing import NDArray

from .numba_kernels import HAS_NUMBA, _rsi_core
from .utils import validate_ohlcv, validate_series

# Threshold: use Numba JIT only when array length exceeds this value.
_NUMBA_THRESHOLD = 1000


def rsi(close: NDArray[np.float64], period: int = 14) -> NDArray[np.float64]:
    """Relative Strength Index — Wilder smoothing.

    RSI oscillates between 0 and 100. Values above 70 are traditionally
    overbought; values below 30 are oversold. Uses Wilder's smoothing (RMA),
    matching TradingView behaviour.

    When numba is installed and the array is large enough (> 1000 elements),
    the inner loop is JIT-compiled for a ~5-10x speedup.

    Args:
        close: Close prices, shape (n,).
        period: Lookback period (default 14).

    Returns:
        RSI values, shape (n,). First ``period`` values are NaN.
    """
    validate_series(close, min_length=period + 1)
    n = len(close)

    delta = np.diff(close)

    if HAS_NUMBA and n > _NUMBA_THRESHOLD:
        # JIT path: delegate entire loop to Numba kernel
        delta_c = np.ascontiguousarray(delta, dtype=np.float64)
        return _rsi_core(delta_c, period)

    # Pure-Python path
    result = np.full(n, np.nan, dtype=np.float64)
    gain = np.where(delta > 0, delta, 0.0)
    loss = np.where(delta < 0, -delta, 0.0)

    # Seed averages from first `period` changes
    avg_gain = float(np.mean(gain[:period]))
    avg_loss = float(np.mean(loss[:period]))

    # First RSI value at index `period`
    if avg_loss == 0.0:
        result[period] = 100.0
    else:
        rs = avg_gain / avg_loss
        result[period] = 100.0 - (100.0 / (1.0 + rs))

    # Subsequent values via Wilder smoothing
    for i in range(period, len(delta)):
        avg_gain = (avg_gain * (period - 1) + gain[i]) / period
        avg_loss = (avg_loss * (period - 1) + loss[i]) / period
        if avg_loss == 0.0:
            result[i + 1] = 100.0
        else:
            rs = avg_gain / avg_loss
            result[i + 1] = 100.0 - (100.0 / (1.0 + rs))

    return result


def macd(
    close: NDArray[np.float64],
    fast: int = 12,
    slow: int = 26,
    signal: int = 9,
) -> tuple[NDArray[np.float64], NDArray[np.float64], NDArray[np.float64]]:
    """Moving Average Convergence/Divergence.

    MACD Line    = EMA(fast) - EMA(slow)
    Signal Line  = EMA(MACD Line, signal)
    Histogram    = MACD Line - Signal Line

    Args:
        close: Close prices, shape (n,).
        fast: Fast EMA period (default 12).
        slow: Slow EMA period (default 26).
        signal: Signal EMA period (default 9).

    Returns:
        Tuple of (macd_line, signal_line, histogram), each shape (n,).
    """
    from .trend import ema

    validate_series(close, min_length=slow)

    n = len(close)
    fast_ema = ema(close, fast)
    slow_ema = ema(close, slow)
    macd_line = fast_ema - slow_ema  # NaN where either EMA is NaN

    # Compute signal EMA only over the valid (non-NaN) portion of macd_line
    valid_mask = ~np.isnan(macd_line)
    valid_macd = macd_line[valid_mask]

    signal_line = np.full(n, np.nan, dtype=np.float64)
    if len(valid_macd) >= signal:
        sig_valid = ema(valid_macd, signal)
        signal_line[valid_mask] = sig_valid

    histogram = macd_line - signal_line
    return macd_line, signal_line, histogram


def stochastic(
    high: NDArray[np.float64],
    low: NDArray[np.float64],
    close: NDArray[np.float64],
    k_period: int = 14,
    d_period: int = 3,
) -> tuple[NDArray[np.float64], NDArray[np.float64]]:
    """Stochastic Oscillator — %K and %D.

    %K = 100 * (close - lowest_low) / (highest_high - lowest_low)
    %D = SMA(%K, d_period)

    Args:
        high: High prices, shape (n,).
        low: Low prices, shape (n,).
        close: Close prices, shape (n,).
        k_period: %K lookback period (default 14).
        d_period: %D smoothing period (default 3).

    Returns:
        Tuple of (%K, %D) arrays, each shape (n,). NaN where insufficient data.
    """
    from .trend import sma
    from .utils import validate_ohlcv

    validate_ohlcv(high, low, close, min_length=k_period)
    n = len(close)

    k = np.full(n, np.nan, dtype=np.float64)
    for i in range(k_period - 1, n):
        highest = np.max(high[i - k_period + 1 : i + 1])
        lowest = np.min(low[i - k_period + 1 : i + 1])
        denom = highest - lowest
        if denom == 0.0:
            k[i] = 50.0  # undefined range — neutral
        else:
            k[i] = 100.0 * (close[i] - lowest) / denom

    d = sma(k, d_period)
    return k, d


def williams_r(
    high: NDArray[np.float64],
    low: NDArray[np.float64],
    close: NDArray[np.float64],
    period: int = 14,
) -> NDArray[np.float64]:
    """Williams %R — inverse of Stochastic %K.

    %R = -100 * (highest_high - close) / (highest_high - lowest_low)

    Ranges from -100 (most oversold) to 0 (most overbought).
    Traditional levels: overbought above -20, oversold below -80.

    Args:
        high: High prices, shape (n,).
        low: Low prices, shape (n,).
        close: Close prices, shape (n,).
        period: Lookback period (default 14).

    Returns:
        Williams %R values, shape (n,). NaN for first ``period - 1`` bars.
    """
    from .utils import validate_ohlcv

    validate_ohlcv(high, low, close, min_length=period)
    n = len(close)
    result = np.full(n, np.nan, dtype=np.float64)

    for i in range(period - 1, n):
        highest = np.max(high[i - period + 1 : i + 1])
        lowest = np.min(low[i - period + 1 : i + 1])
        denom = highest - lowest
        if denom == 0.0:
            result[i] = -50.0  # neutral when no range
        else:
            result[i] = -100.0 * (highest - close[i]) / denom

    return result


def cci(
    high: NDArray[np.float64],
    low: NDArray[np.float64],
    close: NDArray[np.float64],
    period: int = 20,
) -> NDArray[np.float64]:
    """Commodity Channel Index.

    CCI = (Typical Price - SMA(TP, period)) / (0.015 * MeanDeviation)

    where Typical Price = (high + low + close) / 3 and MeanDeviation is the
    mean absolute deviation of TP over the window.

    Args:
        high:   High prices, shape (n,).
        low:    Low prices,  shape (n,).
        close:  Close prices, shape (n,).
        period: Lookback window (default 20).

    Returns:
        CCI values, shape (n,). First ``period - 1`` values are NaN.
    """
    validate_ohlcv(high, low, close, min_length=period)
    n = len(close)
    result = np.full(n, np.nan, dtype=np.float64)
    tp = (high + low + close) / 3.0

    for i in range(period - 1, n):
        window = tp[i - period + 1 : i + 1]
        sma_tp = float(np.mean(window))
        mean_dev = float(np.mean(np.abs(window - sma_tp)))
        if mean_dev != 0.0:
            result[i] = (tp[i] - sma_tp) / (0.015 * mean_dev)
        else:
            result[i] = 0.0

    return result


def roc(close: NDArray[np.float64], period: int = 12) -> NDArray[np.float64]:
    """Rate of Change.

    ROC = ((close[i] - close[i - period]) / close[i - period]) * 100

    Args:
        close:  Close prices, shape (n,).
        period: Lookback period (default 12).

    Returns:
        ROC values, shape (n,). First ``period`` values are NaN.
    """
    validate_series(close, min_length=period + 1)
    n = len(close)
    result = np.full(n, np.nan, dtype=np.float64)

    for i in range(period, n):
        prev = close[i - period]
        if prev != 0.0:
            result[i] = ((close[i] - prev) / prev) * 100.0
        else:
            result[i] = 0.0

    return result


def cmo(close: NDArray[np.float64], period: int = 14) -> NDArray[np.float64]:
    """Chande Momentum Oscillator.

    CMO = 100 * (sum_up - sum_down) / (sum_up + sum_down)

    where sum_up is the sum of positive price changes and sum_down is the sum
    of absolute negative price changes over the lookback window.

    Args:
        close:  Close prices, shape (n,).
        period: Lookback period (default 14).

    Returns:
        CMO values, shape (n,). First ``period`` values are NaN.
    """
    validate_series(close, min_length=period + 1)
    n = len(close)
    result = np.full(n, np.nan, dtype=np.float64)
    delta = np.diff(close)

    for i in range(period, n):
        window = delta[i - period : i]
        sum_up = float(np.sum(window[window > 0]))
        sum_down = float(np.sum(np.abs(window[window < 0])))
        total = sum_up + sum_down
        result[i] = 100.0 * (sum_up - sum_down) / total if total != 0.0 else 0.0

    return result


def trix(close: NDArray[np.float64], period: int = 18) -> NDArray[np.float64]:
    """TRIX — 1-period rate of change of a triple-smoothed EMA.

    Computed as 10000 * change(EMA(EMA(EMA(log(close), period), period), period)).

    Args:
        close:  Close prices, shape (n,). All values must be > 0.
        period: EMA period (default 18).

    Returns:
        TRIX values, shape (n,).

    Raises:
        ValueError: If any close price is <= 0.
    """
    from .trend import ema as _ema

    validate_series(close, min_length=period)
    if np.any(close <= 0):
        raise ValueError("TRIX requires all close prices to be strictly positive.")

    n = len(close)
    log_close = np.log(close)

    # Chain three EMA passes stripping leading NaNs between passes (same
    # pattern as DEMA/TEMA) so that np.mean seeding never sees NaN values.
    e1 = _ema(log_close, period)

    valid1 = ~np.isnan(e1)
    e1_clean = e1[valid1]
    if len(e1_clean) < period:
        return np.full(n, np.nan, dtype=np.float64)
    e2_clean = _ema(e1_clean, period)

    valid1_idx = np.where(valid1)[0]
    e2 = np.full(n, np.nan, dtype=np.float64)
    e2[valid1_idx] = e2_clean

    valid2 = ~np.isnan(e2)
    e2_valid = e2[valid2]
    if len(e2_valid) < period:
        return np.full(n, np.nan, dtype=np.float64)
    e3_valid = _ema(e2_valid, period)

    valid2_idx = np.where(valid2)[0]
    e3 = np.full(n, np.nan, dtype=np.float64)
    e3[valid2_idx] = e3_valid

    result = np.full(n, np.nan, dtype=np.float64)
    for i in range(1, n):
        if not np.isnan(e3[i]) and not np.isnan(e3[i - 1]):
            result[i] = (e3[i] - e3[i - 1]) * 10000.0

    return result


def stoch_rsi(
    close: NDArray[np.float64],
    rsi_period: int = 14,
    stoch_period: int = 14,
    k_period: int = 3,
    d_period: int = 3,
) -> tuple[NDArray[np.float64], NDArray[np.float64]]:
    """Stochastic RSI — applies Stochastic to RSI values.

    StochRSI_K raw = (RSI - min(RSI, stoch_period)) / (max(RSI, stoch_period) - min(RSI, stoch_period))
    %K = SMA(StochRSI_K raw, k_period) * 100
    %D = SMA(%K, d_period)

    Args:
        close:        Close prices, shape (n,).
        rsi_period:   Period for RSI (default 14).
        stoch_period: Rolling window for stochastic on RSI (default 14).
        k_period:     Smoothing for %K (default 3).
        d_period:     Smoothing for %D (default 3).

    Returns:
        Tuple of (%K, %D) arrays, each shape (n,). NaN where insufficient data.
    """
    from .trend import sma as _sma

    validate_series(close, min_length=rsi_period + 1)

    rsi_vals = rsi(close, rsi_period)
    n = len(close)
    raw_k = np.full(n, np.nan, dtype=np.float64)

    for i in range(stoch_period - 1, n):
        window = rsi_vals[i - stoch_period + 1 : i + 1]
        if np.any(np.isnan(window)):
            continue
        lo = float(np.min(window))
        hi = float(np.max(window))
        denom = hi - lo
        if denom == 0.0:
            raw_k[i] = 50.0
        else:
            raw_k[i] = (rsi_vals[i] - lo) / denom

    k = _sma(raw_k, k_period) * 100.0
    d = _sma(k, d_period)
    return k, d


def bop(
    open_: NDArray[np.float64],
    high: NDArray[np.float64],
    low: NDArray[np.float64],
    close: NDArray[np.float64],
) -> NDArray[np.float64]:
    """Balance of Power.

    BOP = (close - open) / (high - low)

    Measures the ability of buyers vs. sellers to push price to an extreme.
    Returns 0.0 when high == low (no range).

    Args:
        open_:  Open prices,  shape (n,).
        high:   High prices,  shape (n,).
        low:    Low prices,   shape (n,).
        close:  Close prices, shape (n,).

    Returns:
        BOP values, shape (n,). No NaN warmup period — calculated for every bar.
    """
    validate_ohlcv(high, low, close, min_length=1)
    validate_series(open_, min_length=1)
    if len(open_) != len(close):
        raise ValueError(
            f"Array length mismatch: open={len(open_)}, close={len(close)}"
        )
    n = len(close)
    result = np.full(n, np.nan, dtype=np.float64)
    for i in range(n):
        hl = high[i] - low[i]
        result[i] = (close[i] - open_[i]) / hl if hl != 0.0 else 0.0
    return result


def mom(close: NDArray[np.float64], period: int = 10) -> NDArray[np.float64]:
    """Simple Momentum — close minus close ``period`` bars ago.

    MOM[i] = close[i] - close[i - period]

    Unlike ROC, this is an absolute (not percentage) change.

    Args:
        close:  Close prices, shape (n,).
        period: Lookback period (default 10).

    Returns:
        Momentum values, shape (n,). First ``period`` values are NaN.

    Raises:
        ValueError: If period < 1.
    """
    validate_series(close, min_length=period + 1)
    if period < 1:
        raise ValueError(f"mom period must be >= 1, got {period}")

    n = len(close)
    result = np.full(n, np.nan, dtype=np.float64)
    result[period:] = close[period:] - close[: n - period]
    return result


def awesome_oscillator(
    high: NDArray[np.float64],
    low: NDArray[np.float64],
    fast: int = 5,
    slow: int = 34,
) -> NDArray[np.float64]:
    """Awesome Oscillator (AO) — Bill Williams.

    AO = SMA(midpoint, fast) - SMA(midpoint, slow)
    where midpoint = (high + low) / 2.

    Positive AO indicates bullish momentum; negative indicates bearish
    momentum. A zero-line crossover is a primary signal.

    Args:
        high: High prices, shape (n,).
        low:  Low prices,  shape (n,).
        fast: Fast SMA period (default 5).
        slow: Slow SMA period (default 34).

    Returns:
        AO values, shape (n,). First ``slow - 1`` values are NaN.

    Raises:
        ValueError: If fast >= slow or either period < 1.
    """
    from .trend import sma as _sma
    from .utils import validate_ohlcv as _val

    _val(high, low, high, min_length=slow)  # high as close proxy for length check
    if fast < 1:
        raise ValueError(f"awesome_oscillator fast period must be >= 1, got {fast}")
    if slow < 1:
        raise ValueError(f"awesome_oscillator slow period must be >= 1, got {slow}")
    if fast >= slow:
        raise ValueError(
            f"awesome_oscillator fast ({fast}) must be < slow ({slow})"
        )

    midpoint = (high + low) / 2.0
    return _sma(midpoint, fast) - _sma(midpoint, slow)


def squeeze_momentum(
    high: NDArray[np.float64],
    low: NDArray[np.float64],
    close: NDArray[np.float64],
    bb_period: int = 20,
    bb_mult: float = 2.0,
    kc_period: int = 20,
    kc_mult: float = 1.5,
    mom_period: int = 12,
) -> tuple[NDArray[np.float64], NDArray[np.bool_]]:
    """Squeeze Momentum Indicator (LazyBear).

    Detects market "squeezes" — periods where Bollinger Bands contract inside
    Keltner Channels. When bands expand back out, explosive momentum often
    follows in the direction of the momentum histogram.

    Squeeze: when BB upper < KC upper AND BB lower > KC lower.
    Momentum: linear regression of delta, where:
        delta = close - (highest(high, mom_period) + lowest(low, mom_period)
                         + sma(close, mom_period)) / 3

    Args:
        high: High prices, shape (n,).
        low: Low prices, shape (n,).
        close: Close prices, shape (n,).
        bb_period: Bollinger Bands period (default 20).
        bb_mult: Bollinger Bands standard deviation multiplier (default 2.0).
        kc_period: Keltner Channels EMA period (default 20).
        kc_mult: Keltner Channels ATR multiplier (default 1.5).
        mom_period: Period for the momentum midline and linear regression (default 12).

    Returns:
        Tuple of:
        - momentum: Linear-regression momentum histogram values, shape (n,).
          NaN where insufficient history.
        - squeeze_on: Boolean array, shape (n,). True = squeeze is active
          (BB inside KC). False = squeeze is released.
    """
    from .trend import linreg as _linreg, sma as _sma
    from .volatility import bollinger_bands, keltner_channels

    validate_ohlcv(high, low, close, min_length=max(bb_period, kc_period, mom_period))

    n = len(close)

    # Bollinger Bands
    bb_upper, _bb_mid, bb_lower = bollinger_bands(close, bb_period, bb_mult)

    # Keltner Channels (use kc_period for both EMA and ATR periods)
    kc_upper, _kc_mid, kc_lower = keltner_channels(
        high, low, close, ema_period=kc_period, atr_period=kc_period, multiplier=kc_mult
    )

    # Squeeze: BB inside KC
    squeeze_on = np.zeros(n, dtype=np.bool_)
    for i in range(n):
        if (
            not np.isnan(bb_upper[i])
            and not np.isnan(kc_upper[i])
            and bb_upper[i] < kc_upper[i]
            and bb_lower[i] > kc_lower[i]
        ):
            squeeze_on[i] = True

    # Momentum delta: close minus the midline
    # midline = (highest(high, mom_period) + lowest(low, mom_period) + sma(close, mom_period)) / 3
    sma_close = _sma(close, mom_period)
    delta = np.full(n, np.nan, dtype=np.float64)

    for i in range(mom_period - 1, n):
        highest_high = float(np.max(high[i - mom_period + 1 : i + 1]))
        lowest_low = float(np.min(low[i - mom_period + 1 : i + 1]))
        if np.isnan(sma_close[i]):
            continue
        midline = (highest_high + lowest_low + sma_close[i]) / 3.0
        delta[i] = close[i] - midline

    # Momentum = linear regression of delta
    # Only compute over valid (non-NaN) portion of delta
    valid_mask = ~np.isnan(delta)
    valid_delta = delta[valid_mask]
    momentum = np.full(n, np.nan, dtype=np.float64)

    if len(valid_delta) >= mom_period:
        linreg_vals = _linreg(valid_delta, mom_period)
        valid_indices = np.where(valid_mask)[0]
        momentum[valid_indices] = linreg_vals

    return momentum, squeeze_on


def dpo(close: NDArray[np.float64], period: int = 20) -> NDArray[np.float64]:
    """Detrended Price Oscillator — removes trend to show cycles.

    DPO eliminates the long-term trend from price so that underlying cycles
    can be identified more easily. It compares past price to a past SMA.

    Formula:
        shift = period // 2 + 1
        DPO[i] = close[i - shift] - SMA(close, period)[i - shift]

    The result is aligned to the CURRENT bar index, meaning:
        result[i] = close[i - shift] - SMA(close, period)[i - shift]

    This is equivalent to the standard DPO definition used in TradingView
    and most charting platforms.

    Args:
        close: Close prices, shape (n,).
        period: Lookback period (default 20).

    Returns:
        DPO values, shape (n,). First ``period - 1 + shift`` values are NaN,
        where shift = period // 2 + 1.

    Raises:
        ValueError: If period < 2.
    """
    from .trend import sma as _sma

    validate_series(close, min_length=period)
    if period < 2:
        raise ValueError(f"dpo period must be >= 2, got {period}")

    n = len(close)
    shift = period // 2 + 1
    result = np.full(n, np.nan, dtype=np.float64)

    sma_vals = _sma(close, period)

    # DPO[i] = close[i - shift] - SMA[i - shift], reported at bar i
    for i in range(shift, n):
        past_idx = i - shift
        sma_past = sma_vals[past_idx]
        if not np.isnan(sma_past):
            result[i] = close[past_idx] - sma_past

    return result


def fisher_transform(
    high: NDArray[np.float64],
    low: NDArray[np.float64],
    period: int = 9,
) -> tuple[NDArray[np.float64], NDArray[np.float64]]:
    """Fisher Transform.

    Converts prices into a Gaussian normal distribution. Extreme readings
    (above +2.5 or below -2.5) indicate potential reversals.

    Formula:
        HL2  = (high + low) / 2
        val  = 2 * ((HL2 - lowest(HL2, period)) /
                    (highest(HL2, period) - lowest(HL2, period))) - 1
        val  = clamp(val, -0.999, 0.999)
        fisher = 0.5 * ln((1 + val) / (1 - val))
        signal = fisher[i-1]

    Args:
        high: High prices, shape (n,).
        low: Low prices, shape (n,).
        period: Lookback period for highest/lowest midpoint (default 9).

    Returns:
        Tuple of (fisher, signal) arrays, each shape (n,).
        First ``period`` values are NaN.
    """
    validate_ohlcv(high, low, high, min_length=period)
    n = len(high)
    hl2 = (high + low) / 2.0

    fisher = np.full(n, np.nan, dtype=np.float64)
    signal = np.full(n, np.nan, dtype=np.float64)

    for i in range(period - 1, n):
        window = hl2[i - period + 1 : i + 1]
        hi = float(np.max(window))
        lo = float(np.min(window))
        denom = hi - lo
        if denom == 0.0:
            val = 0.0
        else:
            val = 2.0 * ((hl2[i] - lo) / denom) - 1.0
        # Clamp to avoid log of zero / negative
        val = max(-0.999, min(0.999, val))
        fisher[i] = 0.5 * float(np.log((1.0 + val) / (1.0 - val)))
        if i > period - 1:
            signal[i] = fisher[i - 1]

    return fisher, signal


def crsi(
    close: NDArray[np.float64],
    rsi_period: int = 3,
    streak_period: int = 2,
    rank_period: int = 100,
) -> NDArray[np.float64]:
    """Connors RSI.

    Connors RSI is a composite momentum oscillator that combines three
    components into a single 0-100 oscillator:
    1. Short RSI of close prices
    2. RSI of the up/down streak length
    3. Percentile rank of the current period's return vs the past ``rank_period`` returns

    Formula:
        CRSI = (RSI(close, rsi_period)
               + RSI(streak, streak_period)
               + PercentRank(roc_1, rank_period)) / 3

    Args:
        close: Close prices, shape (n,).
        rsi_period: Period for the RSI of close (default 3).
        streak_period: Period for the RSI of the streak (default 2).
        rank_period: Lookback for the percentile rank of 1-bar returns (default 100).

    Returns:
        CRSI values, shape (n,). NaN during warm-up.
    """
    validate_series(close, min_length=max(rsi_period, streak_period, rank_period) + 2)

    n = len(close)

    # Component 1: Short RSI
    rsi_vals = rsi(close, rsi_period)

    # Component 2: Consecutive up/down streak
    streak = np.zeros(n, dtype=np.float64)
    for i in range(1, n):
        if close[i] > close[i - 1]:
            streak[i] = max(streak[i - 1] + 1.0, 1.0)
        elif close[i] < close[i - 1]:
            streak[i] = min(streak[i - 1] - 1.0, -1.0)
        else:
            streak[i] = 0.0

    streak_rsi = rsi(streak, streak_period)

    # Component 3: Percentile rank of 1-bar ROC
    roc1 = np.full(n, np.nan, dtype=np.float64)
    for i in range(1, n):
        prev = close[i - 1]
        roc1[i] = ((close[i] - prev) / prev * 100.0) if prev != 0.0 else 0.0

    pct_rank = np.full(n, np.nan, dtype=np.float64)
    for i in range(rank_period, n):
        window = roc1[i - rank_period : i]
        if np.any(np.isnan(window)):
            continue
        count_below = float(np.sum(window < roc1[i]))
        pct_rank[i] = (count_below / rank_period) * 100.0

    result = np.full(n, np.nan, dtype=np.float64)
    for i in range(n):
        if not (np.isnan(rsi_vals[i]) or np.isnan(streak_rsi[i]) or np.isnan(pct_rank[i])):
            result[i] = (rsi_vals[i] + streak_rsi[i] + pct_rank[i]) / 3.0

    return result


def elder_ray(
    high: NDArray[np.float64],
    low: NDArray[np.float64],
    close: NDArray[np.float64],
    period: int = 13,
) -> tuple[NDArray[np.float64], NDArray[np.float64]]:
    """Elder Ray Index — Bull Power and Bear Power.

    Developed by Alexander Elder.  The indicator measures buying and selling
    power in the market by comparing highs and lows to an EMA of closes.

    Formula:
        EMA     = EMA(close, period)
        Bull Power = high - EMA
        Bear Power = low  - EMA

    Positive Bull Power indicates buyers pushing prices above the average.
    Negative Bear Power indicates sellers pushing prices below the average.

    Args:
        high: High prices, shape (n,).
        low: Low prices, shape (n,).
        close: Close prices, shape (n,).
        period: EMA period (default 13).

    Returns:
        Tuple of (bull_power, bear_power) arrays, each shape (n,).
        First ``period - 1`` values are NaN.
    """
    from .trend import ema as _ema

    validate_ohlcv(high, low, close, min_length=period)

    ema_vals = _ema(close, period)
    bull_power = high - ema_vals
    bear_power = low - ema_vals

    # Mask bars where EMA is NaN
    nan_mask = np.isnan(ema_vals)
    bull_power[nan_mask] = np.nan
    bear_power[nan_mask] = np.nan

    return bull_power, bear_power
