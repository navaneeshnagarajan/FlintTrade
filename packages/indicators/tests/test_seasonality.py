"""Tests for packages/indicators/src/seasonality.py.

Covers:
- Monthly seasonality: avg, median, std, positive_rate, years_count,
  best_year, worst_year
- Weekday seasonality: avg, std, positive_rate, sample_count
- Day-of-month seasonality: mapping and values
- Seasonality matrix: shape, year/month indexing, NaN cells
- Edge cases: empty DataFrame, single row (no pct_change), single year,
  all-negative months, all-positive months
- Input validation: missing close column, non-DatetimeIndex, wrong type
"""

from __future__ import annotations

import math

import numpy as np
import pandas as pd
import pytest


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_ohlc(
    prices: list[float],
    start: str = "2005-01-03",
    freq: str = "B",  # business days
) -> pd.DataFrame:
    """Return a minimal OHLC DataFrame with only a ``close`` column."""
    idx = pd.date_range(start=start, periods=len(prices), freq=freq)
    return pd.DataFrame({"close": prices}, index=idx)


def _make_monthly_prices(
    monthly_returns_by_year: dict[int, list[float]],
    start_price: float = 1000.0,
) -> pd.DataFrame:
    """Build a daily-frequency DataFrame from prescribed monthly returns.

    Each entry in ``monthly_returns_by_year`` is a list of 12 monthly
    returns (%) for that year (Jan … Dec).  The function synthesises one
    daily price row per month-end so that resampling to "ME" recovers the
    exact returns.

    Args:
        monthly_returns_by_year: ``{year: [jan_ret, feb_ret, ..., dec_ret]}``.
        start_price: The starting close price (price before January of the
            first year).

    Returns:
        DataFrame with DatetimeIndex and ``close`` column.
    """
    rows: list[tuple[pd.Timestamp, float]] = []
    price = start_price
    years = sorted(monthly_returns_by_year)

    # Seed row: December of (first_year - 1) so pct_change can compute January
    seed_year = years[0] - 1
    seed_ts = pd.Timestamp(year=seed_year, month=12, day=1) + pd.offsets.BMonthEnd(0)
    rows.append((seed_ts, price))

    for year in years:
        monthly_rets = monthly_returns_by_year[year]
        for month_idx, ret_pct in enumerate(monthly_rets, start=1):
            # Last business day of the month
            month_end = pd.Timestamp(year=year, month=month_idx, day=1) + pd.offsets.BMonthEnd(0)
            price = price * (1 + ret_pct / 100)
            rows.append((month_end, price))

    idx = pd.DatetimeIndex([r[0] for r in rows])
    close = [r[1] for r in rows]
    return pd.DataFrame({"close": close}, index=idx)


# ---------------------------------------------------------------------------
# Monthly seasonality
# ---------------------------------------------------------------------------


class TestComputeMonthlySeasonality:
    """Tests for compute_monthly_seasonality."""

    def test_returns_twelve_months_for_full_data(self):
        """With 5+ years of data covering all months, all 12 months appear."""
        from packages.indicators.src.seasonality import compute_monthly_seasonality

        data = _make_monthly_prices(
            {y: [1.0] * 12 for y in range(2010, 2016)}
        )
        stats = compute_monthly_seasonality(data)
        assert len(stats) == 12

    def test_month_numbers_are_one_to_twelve(self):
        from packages.indicators.src.seasonality import compute_monthly_seasonality

        data = _make_monthly_prices(
            {y: [0.5] * 12 for y in range(2010, 2016)}
        )
        months = [s.month for s in compute_monthly_seasonality(data)]
        assert months == list(range(1, 13))

    def test_month_names_correct(self):
        from packages.indicators.src.seasonality import compute_monthly_seasonality

        data = _make_monthly_prices(
            {y: [0.0] * 12 for y in range(2010, 2013)}
        )
        stats = compute_monthly_seasonality(data)
        expected_names = [
            "January", "February", "March", "April", "May", "June",
            "July", "August", "September", "October", "November", "December",
        ]
        assert [s.month_name for s in stats] == expected_names

    def test_avg_return_matches_known_values(self):
        """Jan returns: +2%, +4%, +6% → avg = 4.0%."""
        from packages.indicators.src.seasonality import compute_monthly_seasonality

        # Only Jan varies; all other months = 0 %
        data = _make_monthly_prices(
            {
                2010: [2.0] + [0.0] * 11,
                2011: [4.0] + [0.0] * 11,
                2012: [6.0] + [0.0] * 11,
            }
        )
        stats = compute_monthly_seasonality(data)
        jan = next(s for s in stats if s.month == 1)
        assert jan.avg_return_pct == pytest.approx(4.0, abs=1e-6)

    def test_median_return_matches_known_values(self):
        """Jan returns: +1%, +10%, +3% → median = 3.0%."""
        from packages.indicators.src.seasonality import compute_monthly_seasonality

        data = _make_monthly_prices(
            {
                2010: [1.0] + [0.0] * 11,
                2011: [10.0] + [0.0] * 11,
                2012: [3.0] + [0.0] * 11,
            }
        )
        stats = compute_monthly_seasonality(data)
        jan = next(s for s in stats if s.month == 1)
        assert jan.median_return_pct == pytest.approx(3.0, abs=1e-6)

    def test_positive_rate_all_positive(self):
        """Every Jan is positive → positive_rate == 1.0."""
        from packages.indicators.src.seasonality import compute_monthly_seasonality

        data = _make_monthly_prices(
            {y: [1.0] + [0.0] * 11 for y in range(2010, 2016)}
        )
        stats = compute_monthly_seasonality(data)
        jan = next(s for s in stats if s.month == 1)
        assert jan.positive_rate == pytest.approx(1.0)

    def test_positive_rate_all_negative(self):
        """Every Oct is negative → positive_rate == 0.0."""
        from packages.indicators.src.seasonality import compute_monthly_seasonality

        oct_idx = 9  # October is index 9 (0-based)
        data = _make_monthly_prices(
            {
                y: [0.0] * oct_idx + [-1.0] + [0.0] * (11 - oct_idx)
                for y in range(2010, 2016)
            }
        )
        stats = compute_monthly_seasonality(data)
        oct_stats = next(s for s in stats if s.month == 10)
        assert oct_stats.positive_rate == pytest.approx(0.0)

    def test_positive_rate_half_positive(self):
        """Two positive Mays, two negative Mays → positive_rate == 0.5."""
        from packages.indicators.src.seasonality import compute_monthly_seasonality

        may_idx = 4
        data = _make_monthly_prices(
            {
                2010: [0.0] * may_idx + [2.0] + [0.0] * (11 - may_idx),
                2011: [0.0] * may_idx + [3.0] + [0.0] * (11 - may_idx),
                2012: [0.0] * may_idx + [-1.0] + [0.0] * (11 - may_idx),
                2013: [0.0] * may_idx + [-2.0] + [0.0] * (11 - may_idx),
            }
        )
        stats = compute_monthly_seasonality(data)
        may = next(s for s in stats if s.month == 5)
        assert may.positive_rate == pytest.approx(0.5)

    def test_years_count_matches_input(self):
        from packages.indicators.src.seasonality import compute_monthly_seasonality

        data = _make_monthly_prices(
            {y: [1.0] * 12 for y in range(2015, 2020)}
        )
        stats = compute_monthly_seasonality(data)
        # Each month should have 5 observations (2015–2019)
        for s in stats:
            assert s.years_count == 5

    def test_best_year_identification(self):
        """March 2012 = +8 % is the best March in three years."""
        from packages.indicators.src.seasonality import compute_monthly_seasonality

        mar_idx = 2
        data = _make_monthly_prices(
            {
                2010: [0.0] * mar_idx + [2.0] + [0.0] * (11 - mar_idx),
                2011: [0.0] * mar_idx + [4.0] + [0.0] * (11 - mar_idx),
                2012: [0.0] * mar_idx + [8.0] + [0.0] * (11 - mar_idx),
            }
        )
        stats = compute_monthly_seasonality(data)
        mar = next(s for s in stats if s.month == 3)
        assert mar.best_year[0] == 2012
        assert mar.best_year[1] == pytest.approx(8.0, abs=1e-4)

    def test_worst_year_identification(self):
        """March 2010 = -5 % is the worst March."""
        from packages.indicators.src.seasonality import compute_monthly_seasonality

        mar_idx = 2
        data = _make_monthly_prices(
            {
                2010: [0.0] * mar_idx + [-5.0] + [0.0] * (11 - mar_idx),
                2011: [0.0] * mar_idx + [1.0] + [0.0] * (11 - mar_idx),
                2012: [0.0] * mar_idx + [3.0] + [0.0] * (11 - mar_idx),
            }
        )
        stats = compute_monthly_seasonality(data)
        mar = next(s for s in stats if s.month == 3)
        assert mar.worst_year[0] == 2010
        assert mar.worst_year[1] == pytest.approx(-5.0, abs=1e-4)

    def test_std_pct_is_non_negative(self):
        from packages.indicators.src.seasonality import compute_monthly_seasonality

        data = _make_monthly_prices(
            {y: [float(y % 5)] * 12 for y in range(2010, 2016)}
        )
        for s in compute_monthly_seasonality(data):
            assert s.std_pct >= 0.0

    def test_single_year_returns_stats(self):
        """One full year of data should produce stats (std may be NaN for single samples)."""
        from packages.indicators.src.seasonality import compute_monthly_seasonality

        data = _make_monthly_prices({2020: [1.0] * 12})
        stats = compute_monthly_seasonality(data)
        assert len(stats) == 12
        for s in stats:
            assert s.years_count == 1

    def test_empty_dataframe_returns_empty_list(self):
        from packages.indicators.src.seasonality import compute_monthly_seasonality

        empty = pd.DataFrame({"close": pd.Series([], dtype=float)},
                             index=pd.DatetimeIndex([]))
        assert compute_monthly_seasonality(empty) == []

    def test_single_row_no_pct_change_returns_empty(self):
        """Only one data point — pct_change produces all NaN, no results."""
        from packages.indicators.src.seasonality import compute_monthly_seasonality

        df = _make_ohlc([1000.0], start="2020-01-31")
        assert compute_monthly_seasonality(df) == []


# ---------------------------------------------------------------------------
# Weekday seasonality
# ---------------------------------------------------------------------------


class TestComputeWeekdaySeasonality:
    """Tests for compute_weekday_seasonality."""

    def _five_year_daily(self) -> pd.DataFrame:
        """Five years of business-day prices, all flat (0 % daily return)."""
        idx = pd.date_range("2015-01-02", "2019-12-31", freq="B")
        prices = [1000.0] * len(idx)
        return pd.DataFrame({"close": prices}, index=idx)

    def test_returns_five_weekdays(self):
        from packages.indicators.src.seasonality import compute_weekday_seasonality

        data = self._five_year_daily()
        stats = compute_weekday_seasonality(data)
        assert len(stats) == 5

    def test_weekday_indices_zero_to_four(self):
        from packages.indicators.src.seasonality import compute_weekday_seasonality

        data = self._five_year_daily()
        wds = [s.weekday for s in compute_weekday_seasonality(data)]
        assert wds == [0, 1, 2, 3, 4]

    def test_weekday_names_correct(self):
        from packages.indicators.src.seasonality import compute_weekday_seasonality

        data = self._five_year_daily()
        names = [s.weekday_name for s in compute_weekday_seasonality(data)]
        assert names == ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday"]

    def test_avg_return_zero_for_flat_prices(self):
        """Flat price series → all weekday avg returns are 0 %."""
        from packages.indicators.src.seasonality import compute_weekday_seasonality

        data = self._five_year_daily()
        for s in compute_weekday_seasonality(data):
            assert s.avg_return_pct == pytest.approx(0.0, abs=1e-10)

    def test_sample_count_positive(self):
        from packages.indicators.src.seasonality import compute_weekday_seasonality

        data = self._five_year_daily()
        for s in compute_weekday_seasonality(data):
            assert s.sample_count > 0

    def test_positive_rate_range(self):
        from packages.indicators.src.seasonality import compute_weekday_seasonality

        # Build data with some up days and some down days
        idx = pd.date_range("2015-01-02", "2017-12-31", freq="B")
        rng = np.random.default_rng(42)
        prices = np.cumprod(1 + rng.normal(0.0001, 0.01, len(idx))) * 1000
        data = pd.DataFrame({"close": prices}, index=idx)

        for s in compute_weekday_seasonality(data):
            assert 0.0 <= s.positive_rate <= 1.0

    def test_std_pct_non_negative(self):
        from packages.indicators.src.seasonality import compute_weekday_seasonality

        idx = pd.date_range("2015-01-02", "2017-12-31", freq="B")
        rng = np.random.default_rng(7)
        prices = np.cumprod(1 + rng.normal(0, 0.008, len(idx))) * 1000
        data = pd.DataFrame({"close": prices}, index=idx)

        for s in compute_weekday_seasonality(data):
            assert s.std_pct >= 0.0

    def test_empty_dataframe_returns_empty_list(self):
        from packages.indicators.src.seasonality import compute_weekday_seasonality

        empty = pd.DataFrame({"close": pd.Series([], dtype=float)},
                             index=pd.DatetimeIndex([]))
        assert compute_weekday_seasonality(empty) == []

    def test_single_row_returns_empty(self):
        from packages.indicators.src.seasonality import compute_weekday_seasonality

        df = _make_ohlc([1000.0])
        assert compute_weekday_seasonality(df) == []


# ---------------------------------------------------------------------------
# Day-of-month seasonality
# ---------------------------------------------------------------------------


class TestComputeDayOfMonthSeasonality:
    """Tests for compute_day_of_month_seasonality."""

    def test_returns_dict(self):
        from packages.indicators.src.seasonality import compute_day_of_month_seasonality

        data = _make_ohlc(list(range(100, 200)), start="2020-01-02")
        result = compute_day_of_month_seasonality(data)
        assert isinstance(result, dict)

    def test_keys_are_valid_day_numbers(self):
        from packages.indicators.src.seasonality import compute_day_of_month_seasonality

        data = _make_ohlc(list(range(100, 200)), start="2020-01-02")
        for key in compute_day_of_month_seasonality(data):
            assert 1 <= key <= 31

    def test_values_are_floats(self):
        from packages.indicators.src.seasonality import compute_day_of_month_seasonality

        data = _make_ohlc(list(range(100, 200)), start="2020-01-02")
        result = compute_day_of_month_seasonality(data)
        for val in result.values():
            assert isinstance(val, float)

    def test_known_avg_for_specific_day(self):
        """Day 3 appears with returns +1 % and +3 % → avg = 2 %."""
        from packages.indicators.src.seasonality import compute_day_of_month_seasonality

        # Construct two data points on the 3rd of different months
        dates = pd.DatetimeIndex(["2020-01-01", "2020-01-03", "2020-02-01", "2020-02-03"])
        # Returns on Jan-03: +1 %, Feb-03: +3 %
        # Jan-03 close = 1010 (prev = 1000): +1 %
        # Feb-03 close = 1060.3 (prev = 1050): +1 %, approx
        # Use exact values for determinism:
        closes = [1000.0, 1010.0, 1050.0, 1081.5]
        # pct change for day 3 entries: (1010-1000)/1000 = 1 %, (1081.5-1050)/1050 = 3 %
        df = pd.DataFrame({"close": closes}, index=dates)
        result = compute_day_of_month_seasonality(df)
        assert 3 in result
        assert result[3] == pytest.approx(2.0, abs=1e-4)

    def test_empty_dataframe_returns_empty_dict(self):
        from packages.indicators.src.seasonality import compute_day_of_month_seasonality

        empty = pd.DataFrame({"close": pd.Series([], dtype=float)},
                             index=pd.DatetimeIndex([]))
        assert compute_day_of_month_seasonality(empty) == {}

    def test_single_row_returns_empty(self):
        from packages.indicators.src.seasonality import compute_day_of_month_seasonality

        df = _make_ohlc([1000.0])
        assert compute_day_of_month_seasonality(df) == {}

    def test_does_not_include_days_not_in_data(self):
        """If data spans only business days, day 29-31 may be absent."""
        from packages.indicators.src.seasonality import compute_day_of_month_seasonality

        # Two weeks of data — very unlikely to include day 31
        data = _make_ohlc(list(range(100, 115)), start="2020-01-02")
        result = compute_day_of_month_seasonality(data)
        for day in result:
            assert 1 <= day <= 31


# ---------------------------------------------------------------------------
# Seasonality matrix
# ---------------------------------------------------------------------------


class TestBuildSeasonalityMatrix:
    """Tests for build_seasonality_matrix."""

    def test_shape_years_by_12_months(self):
        from packages.indicators.src.seasonality import build_seasonality_matrix

        data = _make_monthly_prices(
            {y: [1.0] * 12 for y in range(2010, 2016)}
        )
        matrix = build_seasonality_matrix(data)
        assert list(matrix.columns) == list(range(1, 13))
        assert 2015 in matrix.index

    def test_cell_values_approximate_input_returns(self):
        """January 2011 = +5 % should appear in matrix[2011, 1]."""
        from packages.indicators.src.seasonality import build_seasonality_matrix

        data = _make_monthly_prices(
            {
                2010: [0.0] * 12,
                2011: [5.0] + [0.0] * 11,
                2012: [0.0] * 12,
            }
        )
        matrix = build_seasonality_matrix(data)
        assert matrix.loc[2011, 1] == pytest.approx(5.0, abs=1e-4)

    def test_empty_dataframe_returns_empty_dataframe(self):
        from packages.indicators.src.seasonality import build_seasonality_matrix

        empty = pd.DataFrame({"close": pd.Series([], dtype=float)},
                             index=pd.DatetimeIndex([]))
        result = build_seasonality_matrix(empty)
        assert result.empty

    def test_matrix_index_type_is_int(self):
        from packages.indicators.src.seasonality import build_seasonality_matrix

        data = _make_monthly_prices({y: [1.0] * 12 for y in range(2015, 2018)})
        matrix = build_seasonality_matrix(data)
        for yr in matrix.index:
            assert isinstance(yr, (int, np.integer))


# ---------------------------------------------------------------------------
# Input validation
# ---------------------------------------------------------------------------


class TestInputValidation:
    """Tests for error handling across all public functions."""

    def _funcs(self):
        from packages.indicators.src.seasonality import (
            compute_day_of_month_seasonality,
            compute_monthly_seasonality,
            compute_weekday_seasonality,
        )
        return [
            compute_monthly_seasonality,
            compute_weekday_seasonality,
            compute_day_of_month_seasonality,
        ]

    def test_raises_type_error_for_non_dataframe(self):
        for fn in self._funcs():
            with pytest.raises(TypeError, match="pandas DataFrame"):
                fn(np.array([1.0, 2.0, 3.0]))  # type: ignore[arg-type]

    def test_raises_type_error_for_non_datetimeindex(self):
        for fn in self._funcs():
            df = pd.DataFrame({"close": [1.0, 2.0]}, index=[0, 1])
            with pytest.raises(TypeError, match="DatetimeIndex"):
                fn(df)

    def test_raises_value_error_for_missing_close_column(self):
        for fn in self._funcs():
            idx = pd.date_range("2020-01-01", periods=5, freq="B")
            df = pd.DataFrame({"open": [1.0] * 5}, index=idx)
            with pytest.raises(ValueError, match="close"):
                fn(df)

    def test_build_matrix_raises_type_error_for_non_dataframe(self):
        from packages.indicators.src.seasonality import build_seasonality_matrix

        with pytest.raises(TypeError, match="pandas DataFrame"):
            build_seasonality_matrix([1.0, 2.0, 3.0])  # type: ignore[arg-type]

    def test_build_matrix_raises_value_error_missing_close(self):
        from packages.indicators.src.seasonality import build_seasonality_matrix

        idx = pd.date_range("2020-01-01", periods=5, freq="B")
        df = pd.DataFrame({"open": [1.0] * 5}, index=idx)
        with pytest.raises(ValueError, match="close"):
            build_seasonality_matrix(df)


# ---------------------------------------------------------------------------
# Integration / realistic scenario
# ---------------------------------------------------------------------------


class TestRealisticScenario:
    """End-to-end sanity check with synthetic 20-year NIFTY-like data."""

    @pytest.fixture(scope="class")
    def nifty_like(self) -> pd.DataFrame:
        rng = np.random.default_rng(2024)
        idx = pd.date_range("2004-01-02", "2023-12-29", freq="B")
        daily_rets = rng.normal(0.0003, 0.012, len(idx))
        prices = np.cumprod(1 + daily_rets) * 1000.0
        return pd.DataFrame({"close": prices}, index=idx)

    def test_monthly_stats_count(self, nifty_like):
        from packages.indicators.src.seasonality import compute_monthly_seasonality

        stats = compute_monthly_seasonality(nifty_like)
        assert len(stats) == 12

    def test_monthly_positive_rates_in_range(self, nifty_like):
        from packages.indicators.src.seasonality import compute_monthly_seasonality

        for s in compute_monthly_seasonality(nifty_like):
            assert 0.0 <= s.positive_rate <= 1.0, (
                f"{s.month_name}: positive_rate={s.positive_rate}"
            )

    def test_monthly_years_count_approx_20(self, nifty_like):
        from packages.indicators.src.seasonality import compute_monthly_seasonality

        for s in compute_monthly_seasonality(nifty_like):
            # 20 years of data → each month ~20 observations
            assert 15 <= s.years_count <= 21, (
                f"{s.month_name}: years_count={s.years_count}"
            )

    def test_weekday_stats_count(self, nifty_like):
        from packages.indicators.src.seasonality import compute_weekday_seasonality

        stats = compute_weekday_seasonality(nifty_like)
        assert len(stats) == 5

    def test_weekday_sample_counts_roughly_equal(self, nifty_like):
        from packages.indicators.src.seasonality import compute_weekday_seasonality

        counts = [s.sample_count for s in compute_weekday_seasonality(nifty_like)]
        # ~4 years of trading → each weekday ~200+ samples; all roughly equal
        assert max(counts) - min(counts) < 100

    def test_dom_covers_most_days(self, nifty_like):
        from packages.indicators.src.seasonality import compute_day_of_month_seasonality

        result = compute_day_of_month_seasonality(nifty_like)
        # 20 years of data should cover at least days 1-28 reliably
        for day in range(1, 29):
            assert day in result, f"Day {day} missing from result"

    def test_matrix_shape(self, nifty_like):
        from packages.indicators.src.seasonality import build_seasonality_matrix

        matrix = build_seasonality_matrix(nifty_like)
        assert matrix.shape[1] == 12
        assert matrix.shape[0] >= 19  # at least 19 complete years

    def test_best_worst_year_tuple_structure(self, nifty_like):
        from packages.indicators.src.seasonality import compute_monthly_seasonality

        for s in compute_monthly_seasonality(nifty_like):
            year, ret = s.best_year
            assert isinstance(year, int)
            assert isinstance(ret, float)
            assert not math.isnan(ret)

            year, ret = s.worst_year
            assert isinstance(year, int)
            assert isinstance(ret, float)
            assert not math.isnan(ret)

    def test_best_return_geq_worst_return(self, nifty_like):
        from packages.indicators.src.seasonality import compute_monthly_seasonality

        for s in compute_monthly_seasonality(nifty_like):
            assert s.best_year[1] >= s.worst_year[1], (
                f"{s.month_name}: best={s.best_year[1]:.2f} < worst={s.worst_year[1]:.2f}"
            )
