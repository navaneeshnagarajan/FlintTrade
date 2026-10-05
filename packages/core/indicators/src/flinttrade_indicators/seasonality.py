"""Calendar return summaries implemented from closing-price observations.

Monthly values compare the last observed close in successive months. Daily
values compare consecutive observations. Neither calculation infers whether a
month is complete or predicts future performance.
"""

from __future__ import annotations

import calendar
from collections import defaultdict
from dataclasses import dataclass
from math import isfinite, nan
from statistics import mean, median, stdev

import pandas as pd


@dataclass
class MonthlyStats:
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
    weekday: int
    weekday_name: str
    avg_return_pct: float
    std_pct: float
    positive_rate: float
    sample_count: int


def _observations(frame: pd.DataFrame) -> list[tuple[pd.Timestamp, float]]:
    if not isinstance(frame, pd.DataFrame):
        raise TypeError("Expected a pandas DataFrame")
    if not isinstance(frame.index, pd.DatetimeIndex):
        raise TypeError("Closing prices require a DatetimeIndex")
    if "close" not in frame.columns:
        raise ValueError("Closing prices require a close column")
    return [
        (stamp, float(value))
        for stamp, value in frame["close"].sort_index().items()
        if pd.notna(value) and isfinite(float(value))
    ]


def _changes(observations: list[tuple[pd.Timestamp, float]]) -> list[tuple[pd.Timestamp, float]]:
    result = []
    for (previous_stamp, previous), (stamp, current) in zip(observations, observations[1:]):
        if previous == 0:
            continue
        change = 100 * (current / previous - 1)
        if isfinite(change):
            result.append((stamp, change))
    return result


def _monthly_changes(frame: pd.DataFrame) -> list[tuple[pd.Timestamp, float]]:
    closing: dict[tuple[int, int], tuple[pd.Timestamp, float]] = {}
    for stamp, value in _observations(frame):
        closing[(stamp.year, stamp.month)] = (stamp, value)
    return _changes(list(closing.values()))


def _sample_std(values: list[float]) -> float:
    return stdev(values) if len(values) > 1 else nan


def compute_monthly_seasonality(ohlc: pd.DataFrame) -> list[MonthlyStats]:
    """Group observed month-to-month percentage changes by calendar month."""
    groups: dict[int, list[tuple[int, float]]] = defaultdict(list)
    for stamp, change in _monthly_changes(ohlc):
        groups[stamp.month].append((stamp.year, change))
    summaries = []
    for month, samples in sorted(groups.items()):
        values = [value for year, value in samples]
        summaries.append(
            MonthlyStats(
                month=month,
                month_name=calendar.month_name[month],
                avg_return_pct=mean(values),
                median_return_pct=median(values),
                std_pct=_sample_std(values),
                positive_rate=sum(value > 0 for value in values) / len(values),
                years_count=len(values),
                best_year=max(samples, key=lambda sample: sample[1]),
                worst_year=min(samples, key=lambda sample: sample[1]),
            )
        )
    return summaries


def compute_weekday_seasonality(ohlc: pd.DataFrame) -> list[WeekdayStats]:
    """Summarise consecutive-observation returns for Monday through Friday."""
    groups: dict[int, list[float]] = defaultdict(list)
    for stamp, change in _changes(_observations(ohlc)):
        if stamp.weekday() < 5:
            groups[stamp.weekday()].append(change)
    return [
        WeekdayStats(
            weekday=day,
            weekday_name=calendar.day_name[day],
            avg_return_pct=mean(values),
            std_pct=_sample_std(values),
            positive_rate=sum(value > 0 for value in values) / len(values),
            sample_count=len(values),
        )
        for day, values in sorted(groups.items())
    ]


def compute_day_of_month_seasonality(ohlc: pd.DataFrame) -> dict[int, float]:
    """Map observed calendar days to their mean consecutive-observation return."""
    groups: dict[int, list[float]] = defaultdict(list)
    for stamp, change in _changes(_observations(ohlc)):
        groups[stamp.day].append(change)
    return {day: mean(values) for day, values in sorted(groups.items())}


def build_seasonality_matrix(ohlc: pd.DataFrame) -> pd.DataFrame:
    """Arrange observed monthly returns in a year by month matrix."""
    cells = {(stamp.year, stamp.month): value for stamp, value in _monthly_changes(ohlc)}
    if not cells:
        return pd.DataFrame(dtype=float)
    years = sorted({year for year, month in cells})
    return pd.DataFrame(
        [[cells.get((year, month), nan) for month in range(1, 13)] for year in years],
        index=years,
        columns=range(1, 13),
        dtype=float,
    )
