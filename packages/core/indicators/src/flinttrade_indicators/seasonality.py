"""Seasonality indicator — monthly, weekday, and day-of-month return patterns.

Inspired by OpenAlgo's seasonality.py example.  Answers questions like:
  - "Which months are historically strong for NIFTY?"
  - "Do Mondays underperform Fridays?"
  - "Is the last trading day of the month a reliable up-day?"

All functions:
- Accept a pandas DataFrame with a DatetimeIndex and a ``close`` column.
- Return plain dataclasses or dicts — no external rendering dependency.
- Are fully type-annotated and work with Python 3.12+.
"""

from __future__ import annotations

from dataclasses import dataclass

import pandas as pd

# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------


@dataclass
class MonthlyStats:
    """Statistics for a single calendar month aggregated across multiple years.

    Attributes:
        month: Calendar month number (1 = January … 12 = December).
        month_name: Full English name of the month.
        avg_return_pct: Mean monthly return across all sampled years (%).
        median_return_pct: Median monthly return (%).
        std_pct: Sample standard deviation of monthly returns (%).
        positive_rate: Fraction of sampled years where the month closed
            positive (0.0 – 1.0).
        years_count: Number of complete months used in the calculation.
        best_year: ``(year, return_pct)`` for the single strongest occurrence.
        worst_year: ``(year, return_pct)`` for the single weakest occurrence.
    """

    month: int
    month_name: str
    avg_return_pct: float
    median_return_pct: float
    std_pct: float
    positive_rate: float
    years_count: int
    best_year: tuple[int, float]
    worst_year: tuple[int, float]


@dataclass
class WeekdayStats:
    """Statistics for a single day of the week across all sampled trading days.

    Attributes:
        weekday: ISO weekday index (0 = Monday … 4 = Friday).
        weekday_name: Full English name of the weekday.
        avg_return_pct: Mean daily return on this weekday (%).
        std_pct: Sample standard deviation of daily returns (%).
        positive_rate: Fraction of occurrences that closed positive (0.0 – 1.0).
        sample_count: Number of trading days used in the calculation.
    """

    weekday: int
    weekday_name: str
    avg_return_pct: float
    std_pct: float
    positive_rate: float
    sample_count: int


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

_MONTH_NAMES: list[str] = [
    "January",
    "February",
    "March",
    "April",
    "May",
    "June",
    "July",
    "August",
    "September",
    "October",
    "November",
    "December",
]

_WEEKDAY_NAMES: list[str] = [
    "Monday",
    "Tuesday",
    "Wednesday",
    "Thursday",
    "Friday",
    "Saturday",
    "Sunday",
]


def _require_close(ohlc: pd.DataFrame) -> pd.Series:
    """Extract and validate the ``close`` column.

    Args:
        ohlc: Input DataFrame.  Must have a DatetimeIndex and a ``close``
            column containing numeric data.

    Returns:
        The ``close`` Series.

    Raises:
        TypeError: If ``ohlc`` is not a DataFrame or its index is not a
            DatetimeIndex.
        ValueError: If the ``close`` column is absent.
    """
    if not isinstance(ohlc, pd.DataFrame):
        raise TypeError(
            f"ohlc must be a pandas DataFrame, got {type(ohlc).__name__}"
        )
    if not isinstance(ohlc.index, pd.DatetimeIndex):
        raise TypeError(
            "ohlc must have a DatetimeIndex; "
            f"got {type(ohlc.index).__name__}"
        )
    if "close" not in ohlc.columns:
        raise ValueError(
            "ohlc DataFrame must contain a 'close' column; "
            f"found columns: {list(ohlc.columns)}"
        )
    return ohlc["close"]


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def compute_monthly_seasonality(ohlc: pd.DataFrame) -> list[MonthlyStats]:
    """Compute per-calendar-month return statistics from daily OHLC data.

    Monthly returns are calculated as the percentage change between the last
    closing price of consecutive calendar months (matching OpenAlgo's
    ``resample("ME")`` approach).  Only complete months are included; if the
    input ends mid-month the partial month is implicitly excluded because
    ``pct_change`` requires a previous month-end.

    Args:
        ohlc: DataFrame with a ``DatetimeIndex`` (any timezone) and at least
            a ``close`` column of numeric type.  Typically daily frequency but
            any intraday or higher frequency also works because the function
            resamples to month-end internally.

    Returns:
        A list of up to 12 :class:`MonthlyStats` objects, one for each
        calendar month that has at least one complete observation in the
        input.  Months with no data are omitted.

    Example:
        >>> stats = compute_monthly_seasonality(nifty_daily_df)
        >>> for s in stats:
        ...     print(f"{s.month_name}: avg={s.avg_return_pct:.2f}%  pos={s.positive_rate:.0%}")
    """
    close = _require_close(ohlc)

    if close.empty:
        return []

    # Resample to last close of each calendar month then compute % change
    monthly: pd.Series = close.resample("ME").last()
    returns: pd.Series = monthly.pct_change() * 100
    returns = returns.dropna()

    if returns.empty:
        return []

    results: list[MonthlyStats] = []
    for month in range(1, 13):
        month_returns: pd.Series = returns[returns.index.month == month]
        if month_returns.empty:
            continue

        best_idx = month_returns.idxmax()
        worst_idx = month_returns.idxmin()

        results.append(
            MonthlyStats(
                month=month,
                month_name=_MONTH_NAMES[month - 1],
                avg_return_pct=float(month_returns.mean()),
                median_return_pct=float(month_returns.median()),
                std_pct=float(month_returns.std()),
                positive_rate=float((month_returns > 0).mean()),
                years_count=int(len(month_returns)),
                best_year=(int(best_idx.year), float(month_returns.loc[best_idx])),
                worst_year=(int(worst_idx.year), float(month_returns.loc[worst_idx])),
            )
        )

    return results


def compute_weekday_seasonality(ohlc: pd.DataFrame) -> list[WeekdayStats]:
    """Compute average daily return broken down by day of the trading week.

    Daily return for bar *i* is ``(close[i] - close[i-1]) / close[i-1] * 100``.
    Only weekdays 0–4 (Monday–Friday) are included; weekends are skipped
    automatically because Indian exchanges do not trade on those days.

    Args:
        ohlc: DataFrame with a ``DatetimeIndex`` and a ``close`` column.
            Daily frequency is expected, but any frequency is accepted — the
            weekday is taken from the row's timestamp.

    Returns:
        A list of up to 5 :class:`WeekdayStats` objects (Monday to Friday),
        only for weekdays that actually appear in the input.

    Example:
        >>> stats = compute_weekday_seasonality(nifty_daily_df)
        >>> for s in stats:
        ...     print(f"{s.weekday_name}: avg={s.avg_return_pct:.3f}%")
    """
    close = _require_close(ohlc)

    if close.empty:
        return []

    daily_returns: pd.Series = close.pct_change() * 100
    daily_returns = daily_returns.dropna()

    if daily_returns.empty:
        return []

    results: list[WeekdayStats] = []
    for wd in range(5):  # 0=Monday … 4=Friday only
        wd_returns: pd.Series = daily_returns[daily_returns.index.weekday == wd]
        if wd_returns.empty:
            continue

        results.append(
            WeekdayStats(
                weekday=wd,
                weekday_name=_WEEKDAY_NAMES[wd],
                avg_return_pct=float(wd_returns.mean()),
                std_pct=float(wd_returns.std()),
                positive_rate=float((wd_returns > 0).mean()),
                sample_count=int(len(wd_returns)),
            )
        )

    return results


def compute_day_of_month_seasonality(ohlc: pd.DataFrame) -> dict[int, float]:
    """Compute average daily return for each calendar day of the month (1–31).

    Useful for identifying expiry-day patterns (e.g. monthly F&O expiry on
    the last Thursday), month-end rebalancing effects, or salary-day demand
    spikes.

    Args:
        ohlc: DataFrame with a ``DatetimeIndex`` and a ``close`` column.

    Returns:
        A ``dict`` mapping day-of-month (1–31) to mean daily return (%).
        Only days that appear at least once in the input are included.

    Example:
        >>> dom = compute_day_of_month_seasonality(nifty_daily_df)
        >>> print(f"Last Thursday avg: {dom.get(28, float('nan')):.3f}%")
    """
    close = _require_close(ohlc)

    if close.empty:
        return {}

    daily_returns: pd.Series = close.pct_change() * 100
    daily_returns = daily_returns.dropna()

    if daily_returns.empty:
        return {}

    result: dict[int, float] = {}
    for dom in range(1, 32):
        dom_returns: pd.Series = daily_returns[daily_returns.index.day == dom]
        if not dom_returns.empty:
            result[dom] = float(dom_returns.mean())

    return result


def build_seasonality_matrix(ohlc: pd.DataFrame) -> pd.DataFrame:
    """Build a year × month matrix of monthly percentage returns.

    This mirrors the ``build_seasonality_matrix`` helper in OpenAlgo's
    ``seasonality.py`` example, exposed here as a reusable utility.

    Rows are years; columns are months 1–12.  A ``NaN`` cell means no data
    was available for that year/month combination.

    Args:
        ohlc: DataFrame with a ``DatetimeIndex`` and a ``close`` column.

    Returns:
        A :class:`pandas.DataFrame` indexed by year (int) with integer
        column labels 1–12 representing calendar months.

    Example:
        >>> matrix = build_seasonality_matrix(nifty_daily_df)
        >>> print(matrix.round(2).to_string())
    """
    close = _require_close(ohlc)

    if close.empty:
        return pd.DataFrame(dtype=float)

    monthly: pd.Series = close.resample("ME").last()
    returns: pd.Series = monthly.pct_change() * 100

    years = sorted({dt.year for dt in returns.dropna().index})
    if not years:
        return pd.DataFrame(dtype=float)

    matrix = pd.DataFrame(index=years, columns=range(1, 13), dtype=float)

    for dt, ret in returns.items():
        if not pd.isna(ret) and dt.year in matrix.index:
            matrix.loc[dt.year, dt.month] = ret

    return matrix
