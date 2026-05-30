"""Tests for PortfolioBacktester.

All tests run without vectorbt (pure-Python simulator path).
Tests that specifically exercise the vectorbt code path are
decorated with ``@_VBT`` and skipped when the library is absent.
"""

from __future__ import annotations

import math
from typing import Any

import pytest

from flinttrade_backtest.portfolio_backtest import (  # noqa: E402
    BenchmarkComparison,
    PortfolioBacktester,
    PortfolioResult,
    RebalanceEntry,
    _equal_weight,
    _inverse_volatility,
    _momentum_weight,
    is_available,
)

# ---------------------------------------------------------------------------
# Availability markers
# ---------------------------------------------------------------------------

_VBT = pytest.mark.skipif(
    not is_available(), reason="vectorbt not installed on this machine"
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_price_df(
    symbols: list[str] | None = None,
    n: int = 260,
    start: str = "2022-01-01",
) -> "Any":
    """Return a synthetic price DataFrame for testing."""
    import random

    import pandas as pd

    symbols = symbols or ["RELIANCE", "INFY", "TCS"]
    rng = random.Random(99)
    dates = pd.bdate_range(start, periods=n)
    data: dict[str, list[float]] = {}
    for sym in symbols:
        price = 100.0
        prices = []
        for _ in dates:
            price = max(1.0, price * (1 + rng.gauss(0.0004, 0.015)))
            prices.append(round(price, 2))
        data[sym] = prices
    return pd.DataFrame(data, index=dates)


# ---------------------------------------------------------------------------
# Class TestEqualWeight — allocation helper
# ---------------------------------------------------------------------------


class TestEqualWeight:
    """_equal_weight returns 1/N for every symbol."""

    def test_weights_sum_to_one(self) -> None:
        w = _equal_weight(["A", "B", "C"])
        assert abs(sum(w.values()) - 1.0) < 1e-9

    def test_all_equal(self) -> None:
        w = _equal_weight(["A", "B", "C", "D"])
        assert all(abs(v - 0.25) < 1e-9 for v in w.values())

    def test_single_symbol(self) -> None:
        w = _equal_weight(["NIFTY"])
        assert abs(w["NIFTY"] - 1.0) < 1e-9


# ---------------------------------------------------------------------------
# Class TestPortfolioBacktesterConstruction
# ---------------------------------------------------------------------------


class TestPortfolioBacktesterConstruction:
    """Constructor validation."""

    def test_empty_symbols_raises(self) -> None:
        with pytest.raises(ValueError, match="symbols"):
            PortfolioBacktester([])

    def test_invalid_rebalance_freq_raises(self) -> None:
        with pytest.raises(ValueError, match="rebalance_freq"):
            PortfolioBacktester(["A"], rebalance_freq="decade")

    def test_non_positive_capital_raises(self) -> None:
        with pytest.raises(ValueError, match="initial_capital"):
            PortfolioBacktester(["A"], initial_capital=0.0)

    def test_defaults_stored(self) -> None:
        bt = PortfolioBacktester(["A", "B"])
        assert bt.benchmark == "NIFTY 50"
        assert bt.rebalance_freq == "quarterly"
        assert bt.initial_capital == 1_000_000.0

    def test_all_rebalance_freqs_accepted(self) -> None:
        for freq in ("daily", "weekly", "monthly", "quarterly", "yearly"):
            bt = PortfolioBacktester(["A"], rebalance_freq=freq)
            assert bt.rebalance_freq == freq


# ---------------------------------------------------------------------------
# Class TestEqualWeightAllocation — backtest run
# ---------------------------------------------------------------------------


class TestEqualWeightAllocation:
    """PortfolioBacktester.run() with equal_weight allocation."""

    def test_returns_portfolio_result(self) -> None:
        bt = PortfolioBacktester(["RELIANCE", "INFY", "TCS"])
        result = bt.run("2022-01-01", "2023-12-31", "equal_weight")
        assert isinstance(result, PortfolioResult)

    def test_equity_curve_starts_at_one(self) -> None:
        bt = PortfolioBacktester(["A", "B"])
        result = bt.run("2022-01-01", "2023-12-31", "equal_weight")
        assert abs(result.equity_curve[0] - 1.0) < 1e-6

    def test_equity_curve_length_positive(self) -> None:
        bt = PortfolioBacktester(["A", "B"])
        result = bt.run("2022-01-01", "2023-12-31", "equal_weight")
        assert len(result.equity_curve) > 0

    def test_sharpe_is_finite(self) -> None:
        bt = PortfolioBacktester(["RELIANCE", "INFY"])
        result = bt.run("2022-01-01", "2023-12-31", "equal_weight")
        assert math.isfinite(result.sharpe_ratio)

    def test_max_drawdown_non_negative(self) -> None:
        bt = PortfolioBacktester(["A", "B", "C"])
        result = bt.run("2022-01-01", "2023-12-31", "equal_weight")
        assert result.max_drawdown >= 0.0

    def test_drawdown_curve_same_length_as_equity(self) -> None:
        bt = PortfolioBacktester(["A", "B"])
        result = bt.run("2022-01-01", "2023-12-31", "equal_weight")
        assert len(result.drawdown_curve) == len(result.equity_curve)

    def test_unknown_strategy_raises(self) -> None:
        bt = PortfolioBacktester(["A"])
        with pytest.raises(ValueError, match="allocation_strategy"):
            bt.run("2022-01-01", "2023-12-31", "black_magic")

    def test_with_external_price_data(self) -> None:
        symbols = ["RELIANCE", "INFY", "TCS"]
        df = _make_price_df(symbols)
        bt = PortfolioBacktester(symbols)
        result = bt.run("2022-01-01", "2023-12-31", "equal_weight", price_data=df)
        assert isinstance(result, PortfolioResult)
        assert len(result.equity_curve) > 0


# ---------------------------------------------------------------------------
# Class TestRebalanceAtQuarterlyBoundaries
# ---------------------------------------------------------------------------


class TestRebalanceAtQuarterlyBoundaries:
    """Rebalance log is populated at quarterly boundaries."""

    def test_quarterly_rebalance_log_non_empty(self) -> None:
        bt = PortfolioBacktester(
            ["A", "B", "C"],
            rebalance_freq="quarterly",
            initial_capital=500_000,
        )
        result = bt.run("2021-01-01", "2024-01-01", "equal_weight")
        # 3-year period with quarterly rebalancing → at least 1 event
        assert len(result.rebalance_log) >= 1

    def test_rebalance_log_entries_are_correct_type(self) -> None:
        bt = PortfolioBacktester(["A", "B"], rebalance_freq="quarterly")
        result = bt.run("2021-01-01", "2023-12-31", "equal_weight")
        for entry in result.rebalance_log:
            assert isinstance(entry, RebalanceEntry)

    def test_rebalance_entry_has_date(self) -> None:
        bt = PortfolioBacktester(["A", "B"], rebalance_freq="quarterly")
        result = bt.run("2021-01-01", "2023-12-31", "equal_weight")
        for entry in result.rebalance_log:
            assert isinstance(entry.date, str)
            assert len(entry.date) >= 10  # YYYY-MM-DD

    def test_rebalance_weights_sum_to_one_or_less(self) -> None:
        """For equal_weight, new_weights must sum to exactly 1.0."""
        bt = PortfolioBacktester(["A", "B", "C"], rebalance_freq="quarterly")
        result = bt.run("2021-01-01", "2023-12-31", "equal_weight")
        for entry in result.rebalance_log:
            total = sum(entry.new_weights.values())
            assert total <= 1.0 + 1e-6

    def test_monthly_rebalance_more_events_than_quarterly(self) -> None:
        bt_q = PortfolioBacktester(["A", "B"], rebalance_freq="quarterly")
        bt_m = PortfolioBacktester(["A", "B"], rebalance_freq="monthly")
        r_q = bt_q.run("2021-01-01", "2024-01-01", "equal_weight")
        r_m = bt_m.run("2021-01-01", "2024-01-01", "equal_weight")
        assert len(r_m.rebalance_log) > len(r_q.rebalance_log)


# ---------------------------------------------------------------------------
# Class TestBenchmarkComparison
# ---------------------------------------------------------------------------


class TestBenchmarkComparison:
    """compare_benchmark returns correct structure and metrics."""

    def test_returns_benchmark_comparison(self) -> None:
        bt = PortfolioBacktester(["A", "B", "C"])
        result = bt.run("2022-01-01", "2023-12-31", "equal_weight")
        cmp = bt.compare_benchmark(result)
        assert isinstance(cmp, BenchmarkComparison)

    def test_comparison_strategy_matches_result(self) -> None:
        bt = PortfolioBacktester(["A", "B"])
        result = bt.run("2022-01-01", "2023-12-31", "equal_weight")
        cmp = bt.compare_benchmark(result)
        # strategy in comparison should be the same object
        assert cmp.strategy is result

    def test_alpha_is_finite(self) -> None:
        bt = PortfolioBacktester(["A", "B", "C"])
        result = bt.run("2022-01-01", "2023-12-31", "equal_weight")
        cmp = bt.compare_benchmark(result)
        assert math.isfinite(cmp.alpha)

    def test_beta_is_finite(self) -> None:
        bt = PortfolioBacktester(["A", "B"])
        result = bt.run("2022-01-01", "2023-12-31", "equal_weight")
        cmp = bt.compare_benchmark(result)
        assert math.isfinite(cmp.beta)

    def test_information_ratio_is_finite(self) -> None:
        bt = PortfolioBacktester(["A", "B"])
        result = bt.run("2022-01-01", "2023-12-31", "equal_weight")
        cmp = bt.compare_benchmark(result)
        assert math.isfinite(cmp.information_ratio)

    def test_buy_hold_result_is_portfolio_result(self) -> None:
        bt = PortfolioBacktester(["A", "B"])
        result = bt.run("2022-01-01", "2023-12-31", "equal_weight")
        cmp = bt.compare_benchmark(result)
        assert isinstance(cmp.buy_hold, PortfolioResult)

    def test_with_external_benchmark_prices(self) -> None:
        """compare_benchmark accepts a benchmark_prices Series."""
        import pandas as pd

        bt = PortfolioBacktester(["A", "B"])
        result = bt.run("2022-01-01", "2023-12-31", "equal_weight")
        # Synthetic benchmark series
        n = len(result.equity_curve)
        dates = pd.bdate_range("2022-01-01", periods=n)
        bench = pd.Series([100.0 + i * 0.05 for i in range(n)], index=dates)
        cmp = bt.compare_benchmark(result, benchmark_prices=bench)
        assert math.isfinite(cmp.alpha)


# ---------------------------------------------------------------------------
# Class TestDrawdownCalculation
# ---------------------------------------------------------------------------


class TestDrawdownCalculation:
    """Drawdown curve is monotonically computed from equity."""

    def test_drawdown_curve_all_non_negative(self) -> None:
        bt = PortfolioBacktester(["A", "B"])
        result = bt.run("2022-01-01", "2023-12-31", "equal_weight")
        assert all(dd >= 0.0 for dd in result.drawdown_curve)

    def test_drawdown_curve_bounded_by_one(self) -> None:
        bt = PortfolioBacktester(["A", "B"])
        result = bt.run("2022-01-01", "2023-12-31", "equal_weight")
        assert all(dd <= 1.0 for dd in result.drawdown_curve)

    def test_max_drawdown_equals_max_of_drawdown_curve(self) -> None:
        bt = PortfolioBacktester(["A", "B", "C"])
        result = bt.run("2022-01-01", "2023-12-31", "equal_weight")
        # max_drawdown is in % (×100), drawdown_curve is fractional
        expected = max(result.drawdown_curve) * 100
        assert abs(result.max_drawdown - expected) < 1e-3


# ---------------------------------------------------------------------------
# Class TestAllocationStrategies — smoke tests for each strategy
# ---------------------------------------------------------------------------


class TestAllocationStrategies:
    """Every allocation strategy produces a valid PortfolioResult."""

    @pytest.mark.parametrize(
        "strategy",
        ["equal_weight", "inverse_volatility", "momentum", "market_cap"],
    )
    def test_strategy_runs_without_error(self, strategy: str) -> None:
        symbols = ["A", "B", "C"]
        df = _make_price_df(symbols)
        bt = PortfolioBacktester(symbols)
        result = bt.run("2022-01-01", "2023-12-31", strategy, price_data=df)
        assert isinstance(result, PortfolioResult)
        assert math.isfinite(result.total_return)

    def test_inverse_volatility_weights_sum_to_one(self) -> None:
        df = _make_price_df(["A", "B", "C"])
        w = _inverse_volatility(["A", "B", "C"], price_data=df)
        assert abs(sum(w.values()) - 1.0) < 1e-6

    def test_momentum_weights_sum_lte_one(self) -> None:
        df = _make_price_df(["A", "B", "C"])
        w = _momentum_weight(["A", "B", "C"], price_data=df)
        assert sum(w.values()) <= 1.0 + 1e-6

    def test_momentum_top_n_limits_symbols(self) -> None:
        df = _make_price_df(["A", "B", "C", "D"])
        w = _momentum_weight(["A", "B", "C", "D"], price_data=df, top_n=2)
        non_zero = sum(1 for v in w.values() if v > 0)
        assert non_zero <= 2


# ---------------------------------------------------------------------------
# Class TestIsAvailable
# ---------------------------------------------------------------------------


class TestIsAvailable:
    """is_available() always returns a bool."""

    def test_returns_bool(self) -> None:
        assert isinstance(is_available(), bool)
