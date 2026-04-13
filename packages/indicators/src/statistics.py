"""Statistical indicators — LRSLOPE, CORREL, BETA, VAR, TSF, MEDIAN, MODE,
MedianBands.

All functions:
- Accept numpy float64 arrays
- Return numpy float64 arrays (or scalars for summary functions)
- Fill NaN for bars where insufficient history exists
- Do NOT forward-fill
"""

from __future__ import annotations

import numpy as np
from numpy.typing import NDArray

from packages.indicators.src.utils import validate_series


def lrslope(
    close: NDArray[np.float64],
    period: int = 14,
) -> NDArray[np.float64]:
    """Linear Regression Slope.

    Returns the slope (rate of change) of the least-squares regression line
    fit to the most recent ``period`` bars.  Positive values indicate an
    upward-trending price series; negative values indicate a downward trend.

    Formula:
        For each window of length ``period``:
          x   = [0, 1, ..., period-1]
          m   = (period * sum(x*y) - sum(x)*sum(y)) / (period * sum(x^2) - sum(x)^2)
        LRSLOPE[i] = m

    Args:
        close: Close prices, shape (n,).
        period: Regression window length (default 14, must be >= 2).

    Returns:
        Slope values, shape (n,). First ``period - 1`` values are NaN.

    Raises:
        ValueError: If period < 2.
    """
    validate_series(close, min_length=period)
    if period < 2:
        raise ValueError(f"lrslope period must be >= 2, got {period}")

    n = len(close)
    result = np.full(n, np.nan, dtype=np.float64)
    x = np.arange(period, dtype=np.float64)
    x_sum = float(np.sum(x))
    x2_sum = float(np.sum(x * x))
    denom = period * x2_sum - x_sum * x_sum

    if denom == 0.0:
        return result

    for i in range(period - 1, n):
        y = close[i - period + 1 : i + 1]
        y_sum = float(np.sum(y))
        xy_sum = float(np.sum(x * y))
        result[i] = (period * xy_sum - x_sum * y_sum) / denom

    return result


def correl(
    series_a: NDArray[np.float64],
    series_b: NDArray[np.float64],
    period: int = 20,
) -> NDArray[np.float64]:
    """Rolling Pearson Correlation Coefficient.

    Measures the linear relationship between two series over a rolling window.
    Values range from -1 (perfect negative correlation) to +1 (perfect positive
    correlation).  Zero indicates no linear relationship.

    Formula:
        r = cov(A, B) / (std(A) * std(B))

    Args:
        series_a: First series, shape (n,).
        series_b: Second series, shape (n,). Must match length of series_a.
        period: Rolling window length (default 20, must be >= 2).

    Returns:
        Correlation values, shape (n,). First ``period - 1`` values are NaN.
        NaN is returned when either series has zero variance in the window.

    Raises:
        ValueError: If period < 2 or arrays have different lengths.
    """
    validate_series(series_a, min_length=period)
    validate_series(series_b, min_length=period)
    if len(series_a) != len(series_b):
        raise ValueError(
            f"Array length mismatch: series_a={len(series_a)}, series_b={len(series_b)}"
        )
    if period < 2:
        raise ValueError(f"correl period must be >= 2, got {period}")

    n = len(series_a)
    result = np.full(n, np.nan, dtype=np.float64)

    for i in range(period - 1, n):
        a = series_a[i - period + 1 : i + 1]
        b = series_b[i - period + 1 : i + 1]
        std_a = float(np.std(a, ddof=0))
        std_b = float(np.std(b, ddof=0))
        if std_a == 0.0 or std_b == 0.0:
            result[i] = np.nan
        else:
            result[i] = float(np.mean((a - np.mean(a)) * (b - np.mean(b)))) / (std_a * std_b)

    return result


def beta(
    asset: NDArray[np.float64],
    benchmark: NDArray[np.float64],
    period: int = 20,
) -> NDArray[np.float64]:
    """Rolling Beta — asset sensitivity to the benchmark.

    Beta is the slope of the regression of asset returns on benchmark returns.
    Beta > 1 means the asset amplifies benchmark moves; Beta < 1 means it is
    less volatile than the benchmark; Beta < 0 means it moves inversely.

    Formula:
        beta[i] = cov(R_asset, R_bench) / var(R_bench)

    where R = log return (close[i] / close[i-1]).

    Args:
        asset: Asset close prices, shape (n,). All values > 0.
        benchmark: Benchmark close prices, shape (n,). All values > 0.
        period: Rolling window for return-series regression (default 20).

    Returns:
        Beta values, shape (n,). First ``period`` values are NaN.

    Raises:
        ValueError: If arrays have different lengths or any price <= 0.
    """
    validate_series(asset, min_length=period + 1)
    validate_series(benchmark, min_length=period + 1)
    if len(asset) != len(benchmark):
        raise ValueError(
            f"Array length mismatch: asset={len(asset)}, benchmark={len(benchmark)}"
        )
    if np.any(asset <= 0.0) or np.any(benchmark <= 0.0):
        raise ValueError("beta requires all prices to be strictly positive.")

    n = len(asset)
    r_asset = np.full(n, np.nan, dtype=np.float64)
    r_bench = np.full(n, np.nan, dtype=np.float64)
    r_asset[1:] = np.log(asset[1:] / asset[:-1])
    r_bench[1:] = np.log(benchmark[1:] / benchmark[:-1])

    result = np.full(n, np.nan, dtype=np.float64)

    for i in range(period, n):
        ra = r_asset[i - period + 1 : i + 1]
        rb = r_bench[i - period + 1 : i + 1]
        if np.any(np.isnan(ra)) or np.any(np.isnan(rb)):
            continue
        var_b = float(np.var(rb, ddof=0))
        if var_b == 0.0:
            result[i] = np.nan
        else:
            cov = float(np.mean((ra - np.mean(ra)) * (rb - np.mean(rb))))
            result[i] = cov / var_b

    return result


def var(
    close: NDArray[np.float64],
    period: int = 14,
    ddof: int = 0,
) -> NDArray[np.float64]:
    """Rolling Variance.

    Computes the rolling variance of the close price series.  Useful as a
    raw volatility measure or as a building block for other statistics.

    Formula:
        VAR[i] = sum((close[j] - mean)^2, j in window) / (period - ddof)

    Args:
        close: Close prices, shape (n,).
        period: Rolling window length (default 14).
        ddof: Delta degrees of freedom — 0 for population variance (default),
            1 for sample variance.

    Returns:
        Variance values, shape (n,). First ``period - 1`` values are NaN.

    Raises:
        ValueError: If ddof not in (0, 1) or period < 2.
    """
    validate_series(close, min_length=period)
    if period < 2:
        raise ValueError(f"var period must be >= 2, got {period}")
    if ddof not in (0, 1):
        raise ValueError(f"var ddof must be 0 or 1, got {ddof}")

    n = len(close)
    result = np.full(n, np.nan, dtype=np.float64)

    for i in range(period - 1, n):
        window = close[i - period + 1 : i + 1]
        result[i] = float(np.var(window, ddof=ddof))

    return result


def tsf(
    close: NDArray[np.float64],
    period: int = 14,
) -> NDArray[np.float64]:
    """Time Series Forecast (TSF).

    TSF is the linear regression value projected one bar ahead.  It is
    equivalent to the Linear Regression value at period + 1, which makes it
    a one-bar-ahead forecast of the trend.

    Formula:
        Fit a least-squares line to window [i-period+1 .. i].
        Project the fitted value one bar forward (at x = period).

    Args:
        close: Close prices, shape (n,).
        period: Regression window length (default 14, must be >= 2).

    Returns:
        TSF values, shape (n,). First ``period - 1`` values are NaN.

    Raises:
        ValueError: If period < 2.
    """
    validate_series(close, min_length=period)
    if period < 2:
        raise ValueError(f"tsf period must be >= 2, got {period}")

    n = len(close)
    result = np.full(n, np.nan, dtype=np.float64)
    x = np.arange(period, dtype=np.float64)
    x_mean = float(np.mean(x))
    x_var = float(np.sum((x - x_mean) ** 2))

    if x_var == 0.0:
        return result

    for i in range(period - 1, n):
        y = close[i - period + 1 : i + 1]
        y_mean = float(np.mean(y))
        cov = float(np.sum((x - x_mean) * (y - y_mean)))
        slope = cov / x_var
        intercept = y_mean - slope * x_mean
        # Project one bar ahead: x = period (one step beyond the last x = period-1)
        result[i] = slope * period + intercept

    return result


def median(
    close: NDArray[np.float64],
    period: int = 14,
) -> NDArray[np.float64]:
    """Rolling Median.

    Computes the rolling median of the close price series over a window.
    More robust to outliers than the SMA.

    Args:
        close: Close prices, shape (n,).
        period: Rolling window length (default 14).

    Returns:
        Median values, shape (n,). First ``period - 1`` values are NaN.
    """
    validate_series(close, min_length=period)
    if period < 1:
        raise ValueError(f"median period must be >= 1, got {period}")

    n = len(close)
    result = np.full(n, np.nan, dtype=np.float64)

    for i in range(period - 1, n):
        result[i] = float(np.median(close[i - period + 1 : i + 1]))

    return result


def mode(
    close: NDArray[np.float64],
    period: int = 14,
    bins: int = 10,
) -> NDArray[np.float64]:
    """Rolling Approximate Mode (most frequent price bin).

    Since continuous prices rarely repeat exactly, the mode is approximated by
    binning the window into ``bins`` equal-width bins and returning the centre
    of the most populated bin.

    Args:
        close: Close prices, shape (n,).
        period: Rolling window length (default 14).
        bins: Number of price bins (default 10).

    Returns:
        Approximate mode values, shape (n,). First ``period - 1`` values are NaN.

    Raises:
        ValueError: If bins < 2 or period < 2.
    """
    validate_series(close, min_length=period)
    if period < 2:
        raise ValueError(f"mode period must be >= 2, got {period}")
    if bins < 2:
        raise ValueError(f"mode bins must be >= 2, got {bins}")

    n = len(close)
    result = np.full(n, np.nan, dtype=np.float64)

    for i in range(period - 1, n):
        window = close[i - period + 1 : i + 1]
        lo = float(np.min(window))
        hi = float(np.max(window))
        if lo == hi:
            result[i] = lo
            continue
        counts, edges = np.histogram(window, bins=bins)
        modal_idx = int(np.argmax(counts))
        result[i] = (edges[modal_idx] + edges[modal_idx + 1]) / 2.0

    return result


def median_bands(
    close: NDArray[np.float64],
    period: int = 20,
    multiplier: float = 2.0,
) -> tuple[NDArray[np.float64], NDArray[np.float64], NDArray[np.float64]]:
    """Median Bands.

    An alternative to Bollinger Bands that uses the rolling median as the
    centre line instead of the SMA, making the indicator more robust to
    price spikes.  The bands use the median absolute deviation (MAD) scaled by
    the multiplier.

    Formula:
        middle  = rolling_median(close, period)
        MAD     = median(|close[j] - middle[i]| for j in window)
        upper   = middle + multiplier * MAD
        lower   = middle - multiplier * MAD

    Args:
        close: Close prices, shape (n,).
        period: Rolling window length (default 20).
        multiplier: MAD multiplier for band width (default 2.0).

    Returns:
        Tuple of (upper, middle, lower) arrays, each shape (n,).
        First ``period - 1`` values are NaN.

    Raises:
        ValueError: If multiplier <= 0.
    """
    validate_series(close, min_length=period)
    if multiplier <= 0.0:
        raise ValueError(f"median_bands multiplier must be > 0, got {multiplier}")

    n = len(close)
    mid = np.full(n, np.nan, dtype=np.float64)
    upper = np.full(n, np.nan, dtype=np.float64)
    lower = np.full(n, np.nan, dtype=np.float64)

    for i in range(period - 1, n):
        window = close[i - period + 1 : i + 1]
        med = float(np.median(window))
        mad = float(np.median(np.abs(window - med)))
        mid[i] = med
        upper[i] = med + multiplier * mad
        lower[i] = med - multiplier * mad

    return upper, mid, lower
