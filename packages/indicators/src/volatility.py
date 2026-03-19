"""Volatility indicators — ATR, Bollinger Bands, Keltner Channels.

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
