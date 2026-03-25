"""Optional Numba JIT kernels for indicator hot loops.

Import pattern: if numba is available, use @njit versions.
If not, fall back to pure Python (already in trend.py/momentum.py).

These kernels accelerate the inner loops of EMA, RSI, and ATR calculations.
The threshold (len > 1000) in callers ensures JIT compilation overhead is
amortised over enough iterations to produce a net speedup.

All kernels accept and return numpy float64 arrays (not Python lists) to
avoid Numba's deprecated "reflected list" type.

Usage from other modules::

    from packages.indicators.src.numba_kernels import HAS_NUMBA, _ema_core

    if HAS_NUMBA and len(close) > 1000:
        values = _ema_core(close[period-1:], k, seed)
        ...
"""

from __future__ import annotations

import numpy as np

try:
    from numba import njit

    HAS_NUMBA = True
except ImportError:
    HAS_NUMBA = False

    def njit(f=None, **kwargs):  # type: ignore[misc]
        """No-op decorator when numba is not installed."""
        if f is not None:
            return f
        return lambda fn: fn


@njit(cache=True)
def _ema_core(
    close: np.ndarray, k: float, seed: float
) -> np.ndarray:
    """EMA inner loop — O(n), cacheable.

    Args:
        close: Price values (numpy float64 array, starting from period-1 onward).
        k: EMA multiplier, 2 / (period + 1).
        seed: SMA of first ``period`` bars.

    Returns:
        Numpy float64 array of EMA values, same length as ``close``.
    """
    n = len(close)
    result = np.empty(n, dtype=np.float64)
    result[0] = seed
    for i in range(1, n):
        result[i] = close[i] * k + result[i - 1] * (1.0 - k)
    return result


@njit(cache=True)
def _rsi_core(
    changes: np.ndarray, period: int
) -> np.ndarray:
    """RSI Wilder smoothing inner loop.

    Args:
        changes: Price changes (numpy float64 diff array), length ``m``.
        period: RSI period.

    Returns:
        Numpy float64 array of RSI values, length ``m + 1`` (aligned to
        original close indices). Index ``period`` holds the first valid RSI.
        Values before ``period`` are NaN.
    """
    m = len(changes)
    result_len = m + 1
    result = np.full(result_len, np.nan, dtype=np.float64)

    # Seed with SMA of first `period` changes
    avg_gain = 0.0
    avg_loss = 0.0
    for i in range(period):
        if changes[i] > 0:
            avg_gain += changes[i]
        else:
            avg_loss -= changes[i]
    avg_gain /= period
    avg_loss /= period

    if avg_loss == 0:
        result[period] = 100.0
    else:
        rs = avg_gain / avg_loss
        result[period] = 100.0 - (100.0 / (1.0 + rs))

    # Wilder smoothing
    for i in range(period, m):
        gain = changes[i] if changes[i] > 0 else 0.0
        loss = -changes[i] if changes[i] < 0 else 0.0
        avg_gain = (avg_gain * (period - 1) + gain) / period
        avg_loss = (avg_loss * (period - 1) + loss) / period
        if avg_loss == 0:
            result[i + 1] = 100.0
        else:
            rs = avg_gain / avg_loss
            result[i + 1] = 100.0 - (100.0 / (1.0 + rs))

    return result


@njit(cache=True)
def _atr_core(
    highs: np.ndarray,
    lows: np.ndarray,
    closes: np.ndarray,
    period: int,
) -> np.ndarray:
    """ATR Wilder smoothing inner loop.

    Args:
        highs: High prices (numpy float64 array), length ``n``.
        lows: Low prices (numpy float64 array), length ``n``.
        closes: Close prices (numpy float64 array), length ``n``.
        period: ATR period.

    Returns:
        Numpy float64 array of ATR values, length ``n``.
        First ``period - 1`` values are NaN.
    """
    n = len(highs)
    result = np.full(n, np.nan, dtype=np.float64)

    # Compute true range
    tr = np.empty(n, dtype=np.float64)
    tr[0] = highs[0] - lows[0]
    for i in range(1, n):
        hl = highs[i] - lows[i]
        hc = abs(highs[i] - closes[i - 1])
        lc = abs(lows[i] - closes[i - 1])
        tr[i] = max(hl, max(hc, lc))

    # Seed: simple mean of first `period` TR values
    tr_sum = 0.0
    for i in range(period):
        tr_sum += tr[i]
    result[period - 1] = tr_sum / period

    # Wilder smoothing
    for i in range(period, n):
        result[i] = (result[i - 1] * (period - 1) + tr[i]) / period

    return result
