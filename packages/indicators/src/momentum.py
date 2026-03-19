"""Momentum indicators — RSI, MACD, Stochastic, Williams %R.

All functions:
- Accept numpy float64 arrays
- Return numpy float64 arrays (or tuples thereof)
- Fill NaN for bars where insufficient history exists
- Do NOT forward-fill
"""

from __future__ import annotations

import numpy as np
from numpy.typing import NDArray

from packages.indicators.src.utils import validate_series


def rsi(close: NDArray[np.float64], period: int = 14) -> NDArray[np.float64]:
    """Relative Strength Index — Wilder smoothing.

    RSI oscillates between 0 and 100. Values above 70 are traditionally
    overbought; values below 30 are oversold. Uses Wilder's smoothing (RMA),
    matching TradingView behaviour.

    Args:
        close: Close prices, shape (n,).
        period: Lookback period (default 14).

    Returns:
        RSI values, shape (n,). First ``period`` values are NaN.
    """
    validate_series(close, min_length=period + 1)
    n = len(close)
    result = np.full(n, np.nan, dtype=np.float64)

    delta = np.diff(close)
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
    from packages.indicators.src.trend import ema

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
    from packages.indicators.src.utils import validate_ohlcv
    from packages.indicators.src.trend import sma

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
    from packages.indicators.src.utils import validate_ohlcv

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
