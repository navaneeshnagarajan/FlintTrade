"""Volatility indicators — ATR, Bollinger Bands, Keltner Channels, Donchian
Channel, NATR, Historical Volatility, Williams VIX Fix, Chaikin Volatility,
BBPercent (%B), BBWidth, ChandelierExit, UlcerIndex, STARC Bands.

All functions:
- Accept numpy float64 arrays
- Return numpy float64 arrays (or tuples thereof)
- Fill NaN for bars where insufficient history exists
- Do NOT forward-fill
"""

from __future__ import annotations

import numpy as np
from numpy.typing import NDArray

from .numba_kernels import HAS_NUMBA, _atr_core
from .utils import validate_ohlcv, validate_series

# Threshold: use Numba JIT only when array length exceeds this value.
_NUMBA_THRESHOLD = 1000


def atr(
    high: NDArray[np.float64],
    low: NDArray[np.float64],
    close: NDArray[np.float64],
    period: int = 14,
) -> NDArray[np.float64]:
    """Average True Range — Wilder smoothing.

    ATR measures market volatility. It uses Wilder's smoothing (RMA),
    identical to the method used in TradingView and most platforms.

    When numba is installed and the array is large enough (> 1000 elements),
    the inner loop is JIT-compiled for a ~5-10x speedup.

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

    if n < period:
        return np.full(n, np.nan, dtype=np.float64)

    if HAS_NUMBA and n > _NUMBA_THRESHOLD:
        # JIT path: delegate entire computation to Numba kernel
        return _atr_core(
            np.ascontiguousarray(high, dtype=np.float64),
            np.ascontiguousarray(low, dtype=np.float64),
            np.ascontiguousarray(close, dtype=np.float64),
            period,
        )

    # Pure-Python path
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
    from .trend import sma  # avoid circular at module level

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
    from .trend import ema as _ema

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


def williams_vix_fix(
    close: NDArray[np.float64],
    low: NDArray[np.float64],
    period: int = 22,
) -> NDArray[np.float64]:
    """Williams VIX Fix — volatility proxy using highest close vs current low.

    Developed by Larry Williams as a synthetic VIX. Measures fear/volatility
    using freely available OHLC data rather than options prices.

    Formula:
        WVF[i] = (highest(close, period)[i] - low[i]) / highest(close, period)[i] * 100

    Higher values indicate more fear/volatility (similar to VIX spikes).
    Values near 0 suggest low fear; values near 100 are extreme panic readings.

    Args:
        close: Close prices, shape (n,).
        low: Low prices, shape (n,). Must be same length as close.
        period: Lookback for highest close (default 22, approx one month of daily bars).

    Returns:
        WVF values as percentages, shape (n,). First ``period - 1`` values are NaN.

    Raises:
        ValueError: If close and low lengths differ.
    """
    validate_series(close, min_length=period)
    validate_series(low, min_length=period)
    if len(close) != len(low):
        raise ValueError(
            f"Array length mismatch: close={len(close)}, low={len(low)}"
        )

    n = len(close)
    result = np.full(n, np.nan, dtype=np.float64)

    for i in range(period - 1, n):
        highest_close = float(np.max(close[i - period + 1 : i + 1]))
        if highest_close == 0.0:
            result[i] = 0.0
        else:
            result[i] = (highest_close - low[i]) / highest_close * 100.0

    return result


def chaikin_volatility(
    high: NDArray[np.float64],
    low: NDArray[np.float64],
    period: int = 10,
    roc_period: int = 10,
) -> NDArray[np.float64]:
    """Chaikin Volatility — EMA of the high-low range, then Rate of Change.

    Developed by Marc Chaikin. Measures the rate of change in a smoothed
    high-low range. Rising values indicate increasing volatility (range
    expansion); falling values indicate narrowing volatility.

    Formula:
        hl_ema[i] = EMA(high - low, period)
        CV[i] = (hl_ema[i] - hl_ema[i - roc_period]) / hl_ema[i - roc_period] * 100

    Args:
        high: High prices, shape (n,).
        low: Low prices, shape (n,). Must be same length as high.
        period: EMA period for smoothing the high-low range (default 10).
        roc_period: Lookback period for the rate of change (default 10).

    Returns:
        Chaikin Volatility values as percentages, shape (n,).
        First ``period - 1 + roc_period`` values are NaN.

    Raises:
        ValueError: If high and low lengths differ.
    """
    from .trend import ema as _ema

    validate_series(high, min_length=period)
    validate_series(low, min_length=period)
    if len(high) != len(low):
        raise ValueError(
            f"Array length mismatch: high={len(high)}, low={len(low)}"
        )
    if period < 1:
        raise ValueError(f"chaikin_volatility period must be >= 1, got {period}")
    if roc_period < 1:
        raise ValueError(f"chaikin_volatility roc_period must be >= 1, got {roc_period}")

    hl_range = (high - low).astype(np.float64)
    hl_ema = _ema(hl_range, period)

    n = len(high)
    result = np.full(n, np.nan, dtype=np.float64)

    for i in range(roc_period, n):
        prev = hl_ema[i - roc_period]
        if np.isnan(hl_ema[i]) or np.isnan(prev) or prev == 0.0:
            continue
        result[i] = (hl_ema[i] - prev) / prev * 100.0

    return result


def bb_percent(
    close: NDArray[np.float64],
    period: int = 20,
    std_dev: float = 2.0,
) -> NDArray[np.float64]:
    """Bollinger %B — position of price within the Bollinger Bands.

    %B indicates where the price is relative to the Bollinger Bands. A value
    of 1.0 means the price equals the upper band; 0.0 means it equals the
    lower band; 0.5 means it is at the midline.

    Formula:
        %B = (close - lower) / (upper - lower)

    Args:
        close: Close prices, shape (n,).
        period: Bollinger Bands period (default 20).
        std_dev: Standard deviation multiplier (default 2.0).

    Returns:
        %B values, shape (n,). First ``period - 1`` values are NaN.
        Returns 0.5 when the band width is zero (flat price series).
    """
    upper, _mid, lower = bollinger_bands(close, period, std_dev)
    n = len(close)
    result = np.full(n, np.nan, dtype=np.float64)

    for i in range(period - 1, n):
        bw = upper[i] - lower[i]
        if np.isnan(bw):
            continue
        result[i] = (close[i] - lower[i]) / bw if bw != 0.0 else 0.5

    return result


def bb_width(
    close: NDArray[np.float64],
    period: int = 20,
    std_dev: float = 2.0,
) -> NDArray[np.float64]:
    """Bollinger Band Width — (upper - lower) / middle.

    Bandwidth measures the relative width of the Bollinger Bands.  The Squeeze
    occurs near historical bandwidth lows; breakouts typically follow.

    Formula:
        BBW = (upper - lower) / middle * 100

    Args:
        close: Close prices, shape (n,).
        period: Bollinger Bands period (default 20).
        std_dev: Standard deviation multiplier (default 2.0).

    Returns:
        BBWidth values as percentages, shape (n,). First ``period - 1`` values
        are NaN.  NaN is returned when the middle (SMA) is zero.
    """
    upper, middle, lower = bollinger_bands(close, period, std_dev)
    with np.errstate(divide="ignore", invalid="ignore"):
        result = np.where(
            (~np.isnan(upper)) & (middle != 0.0),
            (upper - lower) / middle * 100.0,
            np.nan,
        )
    return result.astype(np.float64)


def chandelier_exit(
    high: NDArray[np.float64],
    low: NDArray[np.float64],
    close: NDArray[np.float64],
    period: int = 22,
    multiplier: float = 3.0,
) -> tuple[NDArray[np.float64], NDArray[np.float64]]:
    """Chandelier Exit.

    Developed by Charles Le Beau.  The Chandelier Exit sets a trailing stop
    loss based on the ATR to keep traders in trending moves without stopping
    out on normal retracements.

    Formula:
        CE Long  = highest(high, period) - multiplier * ATR(period)
        CE Short = lowest(low, period)   + multiplier * ATR(period)

    Args:
        high: High prices, shape (n,).
        low: Low prices, shape (n,).
        close: Close prices, shape (n,).
        period: ATR and lookback period (default 22).
        multiplier: ATR multiplier (default 3.0).

    Returns:
        Tuple of (long_stop, short_stop) arrays, each shape (n,).
        First ``period - 1`` values are NaN.
    """
    validate_ohlcv(high, low, close, min_length=period)
    n = len(close)
    atr_vals = atr(high, low, close, period)

    long_stop = np.full(n, np.nan, dtype=np.float64)
    short_stop = np.full(n, np.nan, dtype=np.float64)

    for i in range(period - 1, n):
        if np.isnan(atr_vals[i]):
            continue
        highest_high = float(np.max(high[i - period + 1 : i + 1]))
        lowest_low = float(np.min(low[i - period + 1 : i + 1]))
        long_stop[i] = highest_high - multiplier * atr_vals[i]
        short_stop[i] = lowest_low + multiplier * atr_vals[i]

    return long_stop, short_stop


def ulcer_index(
    close: NDArray[np.float64],
    period: int = 14,
) -> NDArray[np.float64]:
    """Ulcer Index.

    Developed by Peter Martin and Byron McCann.  The Ulcer Index measures
    downside risk based on drawdowns from a rolling highest close.  The larger
    or longer the drawdown, the higher the index.

    Formula:
        pct_drawdown[i] = ((close[i] - max(close, period)[i]) / max(close, period)[i]) * 100
        UI[i] = sqrt(mean(pct_drawdown^2, period))

    Args:
        close: Close prices, shape (n,). All values must be > 0.
        period: Rolling lookback window (default 14).

    Returns:
        Ulcer Index values, shape (n,). First ``2 * period - 2`` values are NaN
        (warmup for both the highest-close window and the variance window).

    Raises:
        ValueError: If any close price <= 0.
    """
    validate_series(close, min_length=period)
    if np.any(close <= 0.0):
        raise ValueError("ulcer_index requires all close prices to be strictly positive.")

    n = len(close)
    result = np.full(n, np.nan, dtype=np.float64)

    # Step 1: rolling highest close over the window
    highest_close = np.full(n, np.nan, dtype=np.float64)
    for i in range(period - 1, n):
        highest_close[i] = float(np.max(close[i - period + 1 : i + 1]))

    # Step 2: percentage drawdown from highest close
    pct_dd = np.full(n, np.nan, dtype=np.float64)
    for i in range(period - 1, n):
        if highest_close[i] != 0.0:
            pct_dd[i] = ((close[i] - highest_close[i]) / highest_close[i]) * 100.0

    # Step 3: rolling RMS of pct_drawdown
    for i in range(2 * period - 2, n):
        window = pct_dd[i - period + 1 : i + 1]
        if np.any(np.isnan(window)):
            continue
        result[i] = float(np.sqrt(float(np.mean(window ** 2))))

    return result


def starc_bands(
    high: NDArray[np.float64],
    low: NDArray[np.float64],
    close: NDArray[np.float64],
    sma_period: int = 5,
    atr_period: int = 15,
    multiplier: float = 1.33,
) -> tuple[NDArray[np.float64], NDArray[np.float64], NDArray[np.float64]]:
    """STARC Bands (Stoller Average Range Channel).

    Developed by Manning Stoller.  STARC Bands use an ATR-derived channel
    around a short-period SMA.  Buying near the lower band and selling near
    the upper band is a low-risk strategy; a close outside the bands is a
    high-risk extreme.

    Formula:
        middle      = SMA(close, sma_period)
        atr_val     = ATR(period=atr_period)
        upper_band  = middle + multiplier * atr_val
        lower_band  = middle - multiplier * atr_val

    Args:
        high: High prices, shape (n,).
        low: Low prices, shape (n,).
        close: Close prices, shape (n,).
        sma_period: SMA period for the middle band (default 5).
        atr_period: ATR period for the channel width (default 15).
        multiplier: ATR multiplier (default 1.33).

    Returns:
        Tuple of (upper, middle, lower) arrays, each shape (n,).
    """
    from .trend import sma as _sma

    validate_ohlcv(high, low, close, min_length=max(sma_period, atr_period))

    middle = _sma(close, sma_period)
    atr_vals = atr(high, low, close, atr_period)

    upper = middle + multiplier * atr_vals
    lower = middle - multiplier * atr_vals
    return upper, middle, lower
