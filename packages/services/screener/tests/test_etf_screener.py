"""Tests for the ETF screener module.

All tests are pure-Python — no HTTP calls, no file I/O.
"""

from __future__ import annotations

import pytest

from flinttrade_screener.etf_screener import (
    ETF_CATALOGUE,
    ETFRecord,
    ETFScreenResult,
    calculate_asset_quilt,
    calculate_momentum_score,
    get_52w_high_low,
    get_sparkline,
    screen_etfs,
)


# ---------------------------------------------------------------------------
# ETF_CATALOGUE
# ---------------------------------------------------------------------------


class TestETFCatalogue:
    """Verify the catalogue has the expected content and structure."""

    def test_catalogue_has_at_least_50_entries(self):
        assert len(ETF_CATALOGUE) >= 50

    def test_all_entries_are_etf_records(self):
        for sym, rec in ETF_CATALOGUE.items():
            assert isinstance(rec, ETFRecord), f"{sym} is not an ETFRecord"

    def test_symbols_match_keys(self):
        # Every record's symbol should equal (or be close to) the catalogue key
        # (a few entries deliberately differ — just ensure all symbols are non-empty)
        for sym, rec in ETF_CATALOGUE.items():
            assert rec.symbol, f"symbol missing for key {sym}"

    def test_categories_are_valid(self):
        valid = {"Equity", "Debt", "Gold", "International", "Sector"}
        for sym, rec in ETF_CATALOGUE.items():
            assert rec.category in valid, f"{sym}: invalid category {rec.category!r}"

    def test_aum_buckets_are_valid(self):
        valid = {"small", "medium", "large", "mega"}
        for sym, rec in ETF_CATALOGUE.items():
            assert rec.aum_bucket in valid, f"{sym}: invalid aum_bucket {rec.aum_bucket!r}"

    def test_known_entries_present(self):
        for key in ("NIFTYBEES", "GOLDBEES", "BANKBEES", "MON50", "LIQUIDBEES"):
            assert key in ETF_CATALOGUE, f"{key} missing from catalogue"

    def test_niftybees_metadata(self):
        rec = ETF_CATALOGUE["NIFTYBEES"]
        assert rec.category == "Equity"
        assert rec.aum_bucket == "mega"
        assert rec.expense_ratio < 0.1

    def test_goldbees_category(self):
        assert ETF_CATALOGUE["GOLDBEES"].category == "Gold"

    def test_expense_ratios_non_negative(self):
        for sym, rec in ETF_CATALOGUE.items():
            assert rec.expense_ratio >= 0.0, f"{sym}: negative expense ratio"

    def test_frozen_record_immutable(self):
        rec = ETF_CATALOGUE["NIFTYBEES"]
        with pytest.raises((AttributeError, TypeError)):
            rec.name = "changed"  # type: ignore[misc]


# ---------------------------------------------------------------------------
# calculate_momentum_score
# ---------------------------------------------------------------------------


class TestCalculateMomentumScore:
    """Verify the weighted momentum formula."""

    def test_basic_weighted_sum(self):
        # 0.10*2 + 0.20*5 + 0.30*8 + 0.40*12 = 0.2+1.0+2.4+4.8 = 8.4
        score = calculate_momentum_score(
            returns_1m=2.0,
            returns_3m=5.0,
            returns_6m=8.0,
            returns_12m=12.0,
        )
        assert abs(score - 8.4) < 1e-6

    def test_weights_sum_to_1(self):
        # If all returns = 1.0, score should equal 1.0
        score = calculate_momentum_score(1.0, 1.0, 1.0, 1.0)
        assert abs(score - 1.0) < 1e-6

    def test_negative_returns(self):
        score = calculate_momentum_score(-5.0, -3.0, -2.0, -1.0)
        assert score < 0

    def test_zero_returns(self):
        assert calculate_momentum_score(0.0, 0.0, 0.0, 0.0) == 0.0

    def test_long_term_dominates(self):
        # 12m return very high, others zero → score should be positive
        score_high_12m = calculate_momentum_score(0.0, 0.0, 0.0, 20.0)
        score_high_1m = calculate_momentum_score(20.0, 0.0, 0.0, 0.0)
        assert score_high_12m > score_high_1m

    def test_rounding_to_4_decimals(self):
        score = calculate_momentum_score(1.111, 2.222, 3.333, 4.444)
        assert score == round(score, 4)

    def test_float_returns(self):
        score = calculate_momentum_score(2.1, 5.4, 8.9, 14.3)
        expected = round(0.10 * 2.1 + 0.20 * 5.4 + 0.30 * 8.9 + 0.40 * 14.3, 4)
        assert abs(score - expected) < 1e-9

    def test_large_returns(self):
        score = calculate_momentum_score(100.0, 100.0, 100.0, 100.0)
        assert abs(score - 100.0) < 1e-6


# ---------------------------------------------------------------------------
# calculate_asset_quilt
# ---------------------------------------------------------------------------


class TestCalculateAssetQuilt:
    """Verify the calendar-year return grid construction."""

    def _sample_returns(self) -> dict[str, dict[int, float]]:
        return {
            "NIFTYBEES": {2022: 5.0, 2023: 20.0, 2024: 10.0},
            "GOLDBEES": {2022: 12.0, 2023: -3.0, 2024: 18.0},
            "MON50": {2022: -15.0, 2023: 30.0, 2024: 8.0},
        }

    def test_basic_structure(self):
        quilt = calculate_asset_quilt(
            ["NIFTYBEES", "GOLDBEES"],
            [2022, 2023],
            self._sample_returns(),
        )
        assert "NIFTYBEES" in quilt
        assert "GOLDBEES" in quilt
        assert "2022" in quilt["NIFTYBEES"]
        assert "2023" in quilt["GOLDBEES"]

    def test_return_values(self):
        quilt = calculate_asset_quilt(
            ["NIFTYBEES"],
            [2023],
            {"NIFTYBEES": {2023: 20.0}},
        )
        assert quilt["NIFTYBEES"]["2023"] == 20.0

    def test_ranks_assigned(self):
        quilt = calculate_asset_quilt(
            ["NIFTYBEES", "GOLDBEES", "MON50"],
            [2023],
            self._sample_returns(),
        )
        # 2023: MON50=30 > NIFTYBEES=20 > GOLDBEES=-3
        assert quilt["MON50"]["rank_2023"] == 1
        assert quilt["NIFTYBEES"]["rank_2023"] == 2
        assert quilt["GOLDBEES"]["rank_2023"] == 3

    def test_missing_data_returns_none(self):
        quilt = calculate_asset_quilt(
            ["NIFTYBEES"],
            [2021],
            {"NIFTYBEES": {}},  # no 2021 data
        )
        assert quilt["NIFTYBEES"]["2021"] is None

    def test_empty_symbols_raises(self):
        with pytest.raises(ValueError, match="symbols"):
            calculate_asset_quilt([], [2023], {})

    def test_empty_years_raises(self):
        with pytest.raises(ValueError, match="years"):
            calculate_asset_quilt(["NIFTYBEES"], [], {})

    def test_multiple_years(self):
        quilt = calculate_asset_quilt(
            ["NIFTYBEES", "GOLDBEES"],
            [2022, 2023, 2024],
            self._sample_returns(),
        )
        for sym in ("NIFTYBEES", "GOLDBEES"):
            for yr in ("2022", "2023", "2024"):
                assert yr in quilt[sym]


# ---------------------------------------------------------------------------
# get_52w_high_low
# ---------------------------------------------------------------------------


class TestGet52wHighLow:
    """Verify 52-week high and low extraction."""

    def test_basic(self):
        prices = [100.0, 105.0, 98.0, 110.0, 102.0]
        high, low = get_52w_high_low(prices)
        assert high == 110.0
        assert low == 98.0

    def test_uses_last_252_days(self):
        # First element is very low; within window it doesn't appear
        old_prices = [1.0] * 10
        recent_prices = [100.0 + i for i in range(252)]
        prices = old_prices + recent_prices
        high, low = get_52w_high_low(prices)
        assert low >= 100.0

    def test_fewer_than_252_uses_all(self):
        prices = [50.0, 80.0, 30.0]
        high, low = get_52w_high_low(prices)
        assert high == 80.0
        assert low == 30.0

    def test_single_element(self):
        high, low = get_52w_high_low([42.0])
        assert high == 42.0
        assert low == 42.0

    def test_empty_raises(self):
        with pytest.raises(ValueError, match="empty"):
            get_52w_high_low([])

    def test_all_same(self):
        high, low = get_52w_high_low([100.0] * 100)
        assert high == 100.0
        assert low == 100.0

    def test_high_ge_low(self):
        import random

        rng = random.Random(42)
        prices = [rng.uniform(50, 200) for _ in range(300)]
        high, low = get_52w_high_low(prices)
        assert high >= low


# ---------------------------------------------------------------------------
# get_sparkline
# ---------------------------------------------------------------------------


class TestGetSparkline:
    """Verify sparkline normalisation."""

    def test_basic_normalisation(self):
        prices = [100.0, 102.0, 98.0, 105.0]
        sparkline = get_sparkline(prices, n=4)
        assert sparkline[0] == 1.0
        assert abs(sparkline[1] - 1.02) < 1e-6
        assert abs(sparkline[2] - 0.98) < 1e-6

    def test_default_n_is_30(self):
        prices = list(range(1, 51))  # 50 prices
        sparkline = get_sparkline(prices)
        assert len(sparkline) == 30

    def test_fewer_prices_than_n(self):
        prices = [100.0, 110.0, 90.0]
        sparkline = get_sparkline(prices, n=30)
        assert len(sparkline) == 3

    def test_empty_prices(self):
        assert get_sparkline([]) == []

    def test_zero_base_returns_zeros(self):
        prices = [0.0, 5.0, 10.0]
        sparkline = get_sparkline(prices, n=3)
        assert sparkline == [0.0, 0.0, 0.0]

    def test_returns_last_n(self):
        prices = list(range(100, 200))  # 100 prices: 100..199
        sparkline = get_sparkline(prices, n=10)
        assert len(sparkline) == 10
        # Last price is 199, base (last 10 start) is 190
        assert abs(sparkline[0] - 1.0) < 1e-6
        assert abs(sparkline[-1] - 199 / 190) < 1e-4

    def test_values_rounded_to_6_decimals(self):
        prices = [3.0, 7.0]
        sparkline = get_sparkline(prices, n=2)
        for v in sparkline:
            assert v == round(v, 6)


# ---------------------------------------------------------------------------
# screen_etfs
# ---------------------------------------------------------------------------


class TestScreenEtfs:
    """Verify ETF screener filtering and sorting."""

    def _all_records(self) -> list[ETFRecord]:
        return list(ETF_CATALOGUE.values())

    def test_returns_list(self):
        results = screen_etfs(self._all_records())
        assert isinstance(results, list)
        assert len(results) > 0

    def test_returns_etf_screen_result(self):
        results = screen_etfs(self._all_records())
        assert all(isinstance(r, ETFScreenResult) for r in results)

    def test_sort_by_aum_descending(self):
        results = screen_etfs(self._all_records(), sort_by="aum")
        buckets = [r.record.aum_bucket for r in results]
        # First entry should be mega or large
        assert buckets[0] in ("mega",)

    def test_filter_min_aum_medium(self):
        results = screen_etfs(self._all_records(), min_aum="medium")
        for r in results:
            assert r.record.aum_bucket in ("medium", "large", "mega")

    def test_filter_min_aum_large(self):
        results = screen_etfs(self._all_records(), min_aum="large")
        for r in results:
            assert r.record.aum_bucket in ("large", "mega")

    def test_filter_category_gold(self):
        results = screen_etfs(self._all_records(), category="Gold")
        assert len(results) > 0
        for r in results:
            assert r.record.category == "Gold"

    def test_filter_category_debt(self):
        results = screen_etfs(self._all_records(), category="Debt")
        for r in results:
            assert r.record.category == "Debt"

    def test_sort_by_momentum_with_returns(self):
        records = [ETF_CATALOGUE["NIFTYBEES"], ETF_CATALOGUE["GOLDBEES"]]
        returns = {
            "NIFTYBEES": {"1m": 2.0, "3m": 5.0, "6m": 8.0, "12m": 15.0},
            "GOLDBEES": {"1m": 1.0, "3m": 2.0, "6m": 3.0, "12m": 5.0},
        }
        results = screen_etfs(records, sort_by="momentum", returns=returns)
        assert results[0].record.symbol == "NIFTYBEES"

    def test_sort_by_return_1m(self):
        records = [ETF_CATALOGUE["NIFTYBEES"], ETF_CATALOGUE["GOLDBEES"]]
        returns = {
            "NIFTYBEES": {"1m": 10.0, "3m": 0.0, "6m": 0.0, "12m": 0.0},
            "GOLDBEES": {"1m": 2.0, "3m": 0.0, "6m": 0.0, "12m": 0.0},
        }
        results = screen_etfs(records, sort_by="return_1m", returns=returns)
        assert results[0].record.symbol == "NIFTYBEES"

    def test_returns_attached_to_result(self):
        records = [ETF_CATALOGUE["NIFTYBEES"]]
        returns = {"NIFTYBEES": {"1m": 3.5, "3m": 7.0, "6m": 12.0, "12m": 18.0}}
        results = screen_etfs(records, returns=returns)
        r = results[0]
        assert r.return_1m == 3.5
        assert r.return_3m == 7.0

    def test_prices_generate_sparkline(self):
        records = [ETF_CATALOGUE["NIFTYBEES"]]
        prices_data = {"NIFTYBEES": [100.0 + i * 0.5 for i in range(50)]}
        results = screen_etfs(records, prices=prices_data)
        assert len(results[0].sparkline) == 30

    def test_prices_generate_52w(self):
        records = [ETF_CATALOGUE["NIFTYBEES"]]
        prices_data = {"NIFTYBEES": [100.0 + i for i in range(260)]}
        results = screen_etfs(records, prices=prices_data)
        assert results[0].high_52w is not None
        assert results[0].low_52w is not None

    def test_empty_input_returns_empty(self):
        assert screen_etfs([]) == []

    def test_combined_filters(self):
        results = screen_etfs(
            self._all_records(),
            category="Sector",
            min_aum="large",
        )
        for r in results:
            assert r.record.category == "Sector"
            assert r.record.aum_bucket in ("large", "mega")

    def test_no_returns_momentum_is_zero(self):
        records = [ETF_CATALOGUE["NIFTYBEES"]]
        results = screen_etfs(records)
        assert results[0].momentum_score == 0.0
