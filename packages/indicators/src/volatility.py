"""Volatility indicators — ATR, Bollinger Bands, Keltner Channels, Donchian
Channel, NATR, Historical Volatility.

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


def atr(
    high: NDArray[np.float64],
    low: NDArray[np.float64],
    close: NDArray[np.float64],
    period: int = 14,
) -> NDArray[np.float64]:
    """Average True Range — Wilder smoothing.

    ATR measures market volatility. It uses Wilder's smoothing (RMA),
    identical to the method used in TradingView and most platforms.

    Args:
        high: High prices, shape (n,).
        low: Low prices, shape (n,).
        close: Close prices, shape (n,).
        period: Smoothing period (default 14).

    Returns:
        ATR values, shape (n,). First ``period - 1`` values are NaN.
    """
    validate_ohlcv(high, low, close, min_length=2)
    n = len(close)
    result = np.full(n, np.nan, dtype=np.float64)

    # True Range: max of three ranges
    tr = np.empty(n, dtype=np.float64)
    tr[0] = high[0] - low[0]
    tr[1:] = np.maximum(
        high[1:] - low[1:],
        np.maximum(
            np.abs(high[1:] - close[:-1]),
            np.abs(low[1:] - close[:-1]),
        ),
    )

    if n < period:
        return result

    # Seed: simple mean of first 'period' TR values
    result[period - 1] = np.mean(tr[:period])

    # Wilder smoothing (RMA)
    for i in range(period, n):
        result[i] = (result[i - 1] * (period - 1) + tr[i]) / period

    return result


def bollinger_bands(
    close: NDArray[np.float64],
    period: int = 20,
    std_dev: float = 2.0,
) -> tuple[NDArray[np.float64], NDArray[np.float64], NDArray[np.float64]]:
    """Bollinger Bands — returns (upper, middle, lower).

    Standard deviation is computed over the same rolling window as the SMA.

    Args:
        close: Close prices, shape (n,).
        period: Rolling window length (default 20).
        std_dev: Number of standard deviations for bands (default 2.0).

    Returns:
        Tuple of (upper, middle, lower) arrays, each shape (n,).
        First ``period - 1`` values are NaN in all three arrays.
    """
    from packages.indicators.src.trend import sma  # avoid circular at module level

    validate_series(close, min_length=period)
    n = len(close)
    middle = sma(close, period)
    std = np.full(n, np.nan, dtype=np.float64)

    for i in range(period - 1, n):
        std[i] = np.std(close[i - period + 1 : i + 1], ddof=0)

    upper = middle + std_dev * std
    lower = middle - std_dev * std
    return upper, middle, lower


def keltner_channels(
    high: NDArray[np.float64],
    low: NDArray[np.float64],
    close: NDArray[np.float64],
    ema_period: int = 20,
    atr_period: int = 10,
    multiplier: float = 2.0,
) -> tuple[NDArray[np.float64], NDArray[np.float64], NDArray[np.float64]]:
    """Keltner Channels — EMA +/- (multiplier * ATR).

    Args:
        high: High prices, shape (n,).
        low: Low prices, shape (n,).
        close: Close prices, shape (n,).
        ema_period: Period for the middle EMA (default 20).
        atr_period: Period for ATR (default 10).
        multiplier: Width multiplier (default 2.0).

    Returns:
        Tuple of (upper, middle, lower) arrays, each shape (n,).
    """
    from packages.indicators.src.trend import ema as _ema

    validate_ohlcv(high, low, close)
    middle = _ema(close, ema_period)
    atr_vals = atr(high, low, close, atr_period)
    upper = middle + multiplier * atr_vals
    lower = middle - multiplier * atr_vals
    return upper, middle, lower


def donchian_channels(
    high: NDArray[np.float64],
    low: NDArray[np.float64],
    period: int = 20,
) -> tuple[NDArray[np.float64], NDArray[np.float64], NDArray[np.float64]]:
    """Donchian Channels — highest high / lowest low over a rolling window.

    Upper = highest high over period bars
    Lower = lowest low over period bars
    Middle = (upper + lower) / 2

    Args:
        high:   High prices, shape (n,).
        low:    Low prices,  shape (n,).
        period: Rolling window (default 20).

    Returns:
        Tuple of (upper, middle, lower), each shape (n,).
        First ``period - 1`` values are NaN.
    """
    validate_series(high, min_length=period)
    validate_series(low, min_length=1)
    if len(high) != len(low):
        raise ValueError(
            f"Array length mismatch: high={len(high)}, low={len(low)}"
        )
    n = len(high)
    upper = np.full(n, np.nan, dtype=np.float64)
    lower = np.full(n, np.nan, dtype=np.float64)

    for i in range(period - 1, n):
        upper[i] = np.max(high[i - period + 1 : i + 1])
        lower[i] = np.min(low[i - period + 1 : i + 1])

    middle = np.where(~np.isnan(upper) & ~np.isnan(lower), (upper + lower) / 2.0, np.nan)
    return upper, middle.astype(np.float64), lower


def natr(
    high: NDArray[np.float64],
    low: NDArray[np.float64],
    close: NDArray[np.float64],
    period: int = 14,
) -> NDArray[np.float64]:
    """Normalized Average True Range — ATR as a percentage of closing price.

    NATR = (ATR / close) * 100

    Args:
        high:   High prices,  shape (n,).
        low:    Low prices,   shape (n,).
        close:  Close prices, shape (n,).
        period: ATR period (default 14).

    Returns:
        NATR values, shape (n,). First ``period - 1`` values are NaN.
    """
    validate_ohlcv(high, low, close, min_length=period)
    atr_vals = atr(high, low, close, period)
    return np.where(close != 0.0, (atr_vals / close) * 100.0, np.nan)


def historical_volatility(
    close: NDArray[np.float64],
    period: int = 10,
    annualization: int = 252,
) -> NDArray[np.float64]:
    """Historical Volatility — annualised standard deviation of log returns.

    HV = 100 * rolling_stdev(log(close[i] / close[i-1]), period)
             * sqrt(annualization)

    Args:
        close:          Close prices, shape (n,). All values must be > 0.
        period:         Rolling window for standard deviation (default 10).
        annualization:  Number of trading periods per year (default 252 for
                        daily data; use 365 for crypto).

    Returns:
        HV values as annualised percentages, shape (n,).
        First ``period`` values are NaN.

    Raises:
        ValueError: If any close price is <= 0.
    """
    validate_series(close, min_length=period + 1)
    if np.any(close <= 0):
        raise ValueError("historical_volatility requires all close prices to be strictly positive.")

    n = len(close)
    result = np.full(n, np.nan, dtype=np.float64)

    log_ret = np.full(n, np.nan, dtype=np.float64)
    log_ret[1:] = np.log(close[1:] / close[:-1])

    ann_factor = float(np.sqrt(annualization))

    for i in range(period, n):
        window = log_ret[i - period + 1 : i + 1]
        if np.any(np.isnan(window)):
            continue
        result[i] = float(np.std(window, ddof=0)) * ann_factor * 100.0

    return result
