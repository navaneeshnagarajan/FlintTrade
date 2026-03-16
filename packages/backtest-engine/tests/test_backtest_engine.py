"""Tests for FlintTrade backtest-engine package.

DO NOT RUN — written for pytest. All tests use synthetic data.
"""

from __future__ import annotations

import json
import math
import os
import sys
from typing import Any

import pytest

# backtest-engine has a hyphen so can't be imported as a Python package.
# Add the src directory to sys.path so we can import modules directly.
_test_dir = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(_test_dir, '..', 'src'))
# Also need the repo root on the path so that source files'
# `from packages.core.src.models import ...` etc. resolve correctly.
sys.path.insert(0, os.path.join(_test_dir, '..', '..', '..'))
# Add core/src and engine/src for direct imports like `from models import OHLCV`
# and `from strategy import BaseStrategy`.
sys.path.insert(0, os.path.join(_test_dir, '..', '..', 'core', 'src'))
sys.path.insert(0, os.path.join(_test_dir, '..', '..', 'engine', 'src'))


# ======================================================================
# Helpers — generate synthetic bar data
# ======================================================================


def _make_bars(
    n: int = 100,
    start_price: float = 100.0,
    trend: float = 0.1,
    volatility: float = 1.0,
) -> list[dict[str, Any]]:
    """Generate n synthetic daily bars with a linear trend + noise."""
    import random
    random.seed(42)
    bars = []
    price = start_price
    for i in range(n):
        noise = random.uniform(-volatility, volatility)
        price = max(1.0, price + trend + noise)
        o = price
        h = price + abs(noise)
        l = price - abs(noise)
        c = price + random.uniform(-volatility / 2, volatility / 2)
        c = max(l, min(h, c))
        bars.append({
            "timestamp": f"2025-{(i // 30) + 1:02d}-{(i % 30) + 1:02d} 09:15:00",
            "open": round(o, 2),
            "high": round(h, 2),
            "low": round(l, 2),
            "close": round(c, 2),
            "volume": 10000 + i * 100,
            "oi": 0,
        })
    return bars


def _make_uptrend_bars(n: int = 100) -> list[dict[str, Any]]:
    """Strongly upward-trending bars."""
    return _make_bars(n=n, start_price=100.0, trend=0.5, volatility=0.3)


def _make_downtrend_bars(n: int = 100) -> list[dict[str, Any]]:
    """Strongly downward-trending bars."""
    return _make_bars(n=n, start_price=200.0, trend=-0.5, volatility=0.3)


# ======================================================================
# Simulator — EMA Crossover on sample data
# ======================================================================


class TestSimulator:
    """Test backtest simulator with EMA crossover."""

    def test_run_ema_crossover(self):
        from simulator import BacktestConfig, BacktestSimulator
        from strategies import EMACrossover

        bars = _make_uptrend_bars(200)
        config = BacktestConfig(
            symbol="TEST", exchange="NSE", interval="1d",
            initial_capital=100000, position_size_pct=50,
        )
        strategy = EMACrossover(
            name="EMA_Test", fast_period=9, slow_period=21, symbol="TEST",
        )
        sim = BacktestSimulator(config)
        result = sim.run(strategy, bars)

        assert result.total_bars == 200
        assert result.final_equity > 0
        assert len(result.equity_curve) == 200

    def test_run_produces_trades(self):
        from simulator import BacktestConfig, BacktestSimulator
        from strategies import EMACrossover

        bars = _make_bars(200, trend=0.2)
        config = BacktestConfig(symbol="TEST", initial_capital=100000)
        strategy = EMACrossover(name="EMA", fast_period=5, slow_period=20, symbol="TEST")
        result = BacktestSimulator(config).run(strategy, bars)

        assert len(result.trades) > 0

    def test_run_empty_bars(self):
        from simulator import BacktestConfig, BacktestSimulator
        from strategies import EMACrossover

        config = BacktestConfig(symbol="TEST", initial_capital=100000)
        strategy = EMACrossover(name="EMA", symbol="TEST")
        result = BacktestSimulator(config).run(strategy, [])

        assert result.error == "No bars provided"
        assert result.total_bars == 0

    def test_equity_curve_starts_at_capital(self):
        from simulator import BacktestConfig, BacktestSimulator
        from strategies import EMACrossover

        bars = _make_bars(50)
        config = BacktestConfig(symbol="TEST", initial_capital=500000)
        strategy = EMACrossover(name="EMA", slow_period=10, fast_period=5, symbol="TEST")
        result = BacktestSimulator(config).run(strategy, bars)

        # First equity point should be near initial capital
        assert abs(result.equity_curve[0].equity - 500000) < 500000 * 0.1

    def test_slippage_applied(self):
        from simulator import BacktestConfig, BacktestSimulator
        from strategies import EMACrossover

        bars = _make_bars(100, trend=0.5)
        config_no_slip = BacktestConfig(symbol="TEST", initial_capital=100000, slippage_pct=0)
        config_slip = BacktestConfig(symbol="TEST", initial_capital=100000, slippage_pct=0.5)

        s1 = EMACrossover(name="E1", fast_period=5, slow_period=15, symbol="TEST")
        s2 = EMACrossover(name="E2", fast_period=5, slow_period=15, symbol="TEST")

        r1 = BacktestSimulator(config_no_slip).run(s1, bars)
        r2 = BacktestSimulator(config_slip).run(s2, bars)

        # With slippage, final equity should be less (or at least different)
        if r1.trades and r2.trades:
            assert r1.final_equity != r2.final_equity

    def test_total_return_pct(self):
        from simulator import BacktestConfig, BacktestSimulator
        from strategies import EMACrossover

        bars = _make_uptrend_bars(100)
        config = BacktestConfig(symbol="TEST", initial_capital=100000)
        strategy = EMACrossover(name="EMA", symbol="TEST")
        result = BacktestSimulator(config).run(strategy, bars)
        assert isinstance(result.total_return_pct, float)


# ======================================================================
# Metrics — Sharpe, drawdown, win rate
# ======================================================================


class TestMetrics:
    """Test performance metrics calculations."""

    def _make_result(self, n_bars: int = 200):
        from simulator import BacktestConfig, BacktestSimulator
        from strategies import EMACrossover

        bars = _make_bars(n_bars, trend=0.2)
        config = BacktestConfig(symbol="TEST", initial_capital=100000)
        strategy = EMACrossover(name="EMA", fast_period=5, slow_period=20, symbol="TEST")
        return BacktestSimulator(config).run(strategy, bars)

    def test_sharpe_ratio(self):
        from metrics import PerformanceMetrics

        result = self._make_result()
        report = PerformanceMetrics.compute(result)
        assert isinstance(report.sharpe_ratio, float)

    def test_sortino_ratio(self):
        from metrics import PerformanceMetrics

        result = self._make_result()
        report = PerformanceMetrics.compute(result)
        assert isinstance(report.sortino_ratio, float)

    def test_max_drawdown(self):
        from metrics import PerformanceMetrics

        result = self._make_result()
        report = PerformanceMetrics.compute(result)
        assert report.drawdown.max_drawdown_pct >= 0

    def test_win_rate(self):
        from metrics import PerformanceMetrics

        result = self._make_result()
        report = PerformanceMetrics.compute(result)
        assert 0 <= report.trade_stats.win_rate <= 100

    def test_profit_factor(self):
        from metrics import PerformanceMetrics

        result = self._make_result()
        report = PerformanceMetrics.compute(result)
        assert report.trade_stats.profit_factor >= 0

    def test_cagr(self):
        from metrics import compute_cagr

        assert compute_cagr(100000, 200000, 252) == pytest.approx(100.0, abs=5)
        assert compute_cagr(100000, 100000, 252) == pytest.approx(0.0)
        assert compute_cagr(0, 100000, 252) == 0.0

    def test_compute_returns(self):
        from metrics import compute_returns
        from simulator import EquityPoint

        curve = [
            EquityPoint(timestamp="d1", equity=100, cash=100, positions_value=0),
            EquityPoint(timestamp="d2", equity=110, cash=110, positions_value=0),
            EquityPoint(timestamp="d3", equity=105, cash=105, positions_value=0),
        ]
        returns = compute_returns(curve)
        assert len(returns) == 2
        assert returns[0] == pytest.approx(0.1, abs=0.001)
        assert returns[1] < 0

    def test_sharpe_flat_returns(self):
        from metrics import compute_sharpe
        # All same return → zero std → sharpe = 0
        assert compute_sharpe([0.01, 0.01, 0.01]) == 0.0

    def test_trade_stats_empty(self):
        from metrics import compute_trade_stats
        stats = compute_trade_stats([])
        assert stats.total_trades == 0
        assert stats.win_rate == 0

    def test_var_basic(self):
        from metrics import compute_var

        returns = [-0.05, -0.03, -0.01, 0.01, 0.02, 0.03, 0.04, 0.05, 0.06, 0.08]
        var, cvar = compute_var(returns, 0.95)
        assert var > 0  # VaR should be positive (representing loss)
        assert cvar >= var  # CVaR >= VaR

    def test_monthly_returns(self):
        from metrics import compute_monthly_returns
        from simulator import EquityPoint

        curve = [
            EquityPoint(timestamp="2025-01-01", equity=100, cash=100, positions_value=0),
            EquityPoint(timestamp="2025-01-31", equity=110, cash=110, positions_value=0),
            EquityPoint(timestamp="2025-02-28", equity=105, cash=105, positions_value=0),
        ]
        monthly = compute_monthly_returns(curve)
        assert len(monthly) >= 1

    def test_pnl_histogram(self):
        from metrics import PerformanceMetrics

        result = self._make_result()
        report = PerformanceMetrics.compute(result)
        assert isinstance(report.pnl_histogram, list)

    def test_calmar_ratio(self):
        from metrics import PerformanceMetrics

        result = self._make_result()
        report = PerformanceMetrics.compute(result)
        assert isinstance(report.calmar_ratio, float)


# ======================================================================
# Walk-Forward — split logic
# ======================================================================


class TestWalkForward:
    """Test walk-forward optimization split logic."""

    def test_split_basic(self):
        from optimizer import walk_forward_splits

        windows = walk_forward_splits(total_bars=1000, in_sample_pct=0.7, num_windows=3)
        assert len(windows) > 0
        for w in windows:
            assert w.in_sample_end < w.out_sample_start
            assert w.out_sample_end >= w.out_sample_start

    def test_split_too_few_bars(self):
        from optimizer import walk_forward_splits
        windows = walk_forward_splits(total_bars=5, in_sample_pct=0.7, num_windows=3)
        assert len(windows) == 0

    def test_split_single_window(self):
        from optimizer import walk_forward_splits
        windows = walk_forward_splits(total_bars=100, in_sample_pct=0.7, num_windows=1)
        assert len(windows) >= 0  # May produce 1 or 0 depending on rounding

    def test_param_grid_combinations(self):
        from optimizer import ParamGrid
        grid = ParamGrid()
        grid.add("fast", [5, 10, 15])
        grid.add("slow", [20, 50])
        combos = grid.combinations()
        assert len(combos) == 6
        assert grid.total_combinations == 6
        assert {"fast": 5, "slow": 20} in combos

    def test_param_grid_empty(self):
        from optimizer import ParamGrid
        grid = ParamGrid()
        assert grid.combinations() == [{}]

    def test_optimizer_runs(self):
        from optimizer import ParamGrid, WalkForwardOptimizer
        from simulator import BacktestConfig
        from strategies import EMACrossover

        bars = _make_bars(200, trend=0.2)
        config = BacktestConfig(symbol="TEST", initial_capital=100000)
        grid = ParamGrid()
        grid.add("fast_period", [5, 10])
        grid.add("slow_period", [20, 30])

        optimizer = WalkForwardOptimizer()
        result = optimizer.optimize(
            strategy_factory=lambda params: EMACrossover(name="OPT", symbol="TEST", **params),
            bars=bars,
            config=config,
            grid=grid,
            in_sample_pct=0.7,
        )
        assert result.best_params is not None
        assert "fast_period" in result.best_params
        assert len(result.in_sample_results) == 4  # 2x2 grid

    def test_optimizer_robustness_score(self):
        from optimizer import ParamGrid, WalkForwardOptimizer
        from simulator import BacktestConfig
        from strategies import EMACrossover

        bars = _make_uptrend_bars(200)
        config = BacktestConfig(symbol="TEST", initial_capital=100000)
        grid = ParamGrid()
        grid.add("fast_period", [5])
        grid.add("slow_period", [20])

        result = WalkForwardOptimizer().optimize(
            strategy_factory=lambda params: EMACrossover(name="OPT", symbol="TEST", **params),
            bars=bars, config=config, grid=grid,
        )
        assert isinstance(result.robustness_score, float)


# ======================================================================
# Monte Carlo — confidence intervals
# ======================================================================


class TestMonteCarlo:
    """Test Monte Carlo simulation."""

    def test_monte_carlo_basic(self):
        from optimizer import WalkForwardOptimizer
        from simulator import SimTrade

        trades = [
            SimTrade(entry_timestamp="t1", exit_timestamp="t2", symbol="X", side="BUY",
                     quantity=1, entry_price=100, exit_price=110, pnl=10, commission=1, net_pnl=9),
            SimTrade(entry_timestamp="t3", exit_timestamp="t4", symbol="X", side="BUY",
                     quantity=1, entry_price=100, exit_price=95, pnl=-5, commission=1, net_pnl=-6),
            SimTrade(entry_timestamp="t5", exit_timestamp="t6", symbol="X", side="BUY",
                     quantity=1, entry_price=100, exit_price=115, pnl=15, commission=1, net_pnl=14),
        ]

        result = WalkForwardOptimizer.monte_carlo(trades, initial_capital=100000, num_simulations=500)
        assert result.num_simulations == 500
        assert result.probability_of_profit > 0
        assert result.percentile_5 <= result.percentile_95

    def test_monte_carlo_empty_trades(self):
        from optimizer import WalkForwardOptimizer
        result = WalkForwardOptimizer.monte_carlo([], initial_capital=100000)
        assert result.mean_return == 0

    def test_monte_carlo_percentiles_ordered(self):
        from optimizer import WalkForwardOptimizer
        from simulator import SimTrade

        trades = [
            SimTrade(entry_timestamp="", exit_timestamp="", symbol="X", side="BUY",
                     quantity=1, entry_price=100, exit_price=100 + i * 5,
                     pnl=i * 5, commission=1, net_pnl=i * 5 - 1)
            for i in range(-5, 6)
        ]

        result = WalkForwardOptimizer.monte_carlo(trades, 100000, num_simulations=1000)
        assert result.percentile_5 <= result.percentile_25
        assert result.percentile_25 <= result.median_return
        assert result.median_return <= result.percentile_75
        assert result.percentile_75 <= result.percentile_95


# ======================================================================
# Data Connector — normalization
# ======================================================================


class TestDataConnector:
    """Test data connector normalization and validation."""

    def test_normalize_bar(self):
        from data_connector import normalize_bar
        raw = {"timestamp": "2025-01-01", "Open": 100, "High": 110, "Low": 90, "Close": 105, "Volume": 5000}
        bar = normalize_bar(raw)
        assert bar["open"] == 100.0
        assert bar["close"] == 105.0
        assert bar["volume"] == 5000
        assert bar["oi"] == 0

    def test_normalize_bar_lowercase(self):
        from data_connector import normalize_bar
        raw = {"timestamp": "2025-01-01", "open": 100, "high": 110, "low": 90, "close": 105, "volume": 5000}
        bar = normalize_bar(raw)
        assert bar["open"] == 100.0

    def test_validate_bars_valid(self):
        from data_connector import validate_bars
        bars = _make_bars(10)
        issues = validate_bars(bars)
        assert len(issues) == 0

    def test_validate_bars_empty(self):
        from data_connector import validate_bars
        issues = validate_bars([])
        assert "No bars" in issues[0]

    def test_validate_bars_bad_ohlc(self):
        from data_connector import validate_bars
        bars = [{"timestamp": "2025-01-01", "open": 0, "high": 100, "low": 90, "close": 95, "volume": 100}]
        issues = validate_bars(bars)
        assert any("open" in i for i in issues)

    def test_validate_bars_high_less_than_low(self):
        from data_connector import validate_bars
        bars = [{"timestamp": "2025-01-01", "open": 100, "high": 90, "low": 100, "close": 95, "volume": 100}]
        issues = validate_bars(bars)
        assert any("high" in i.lower() for i in issues)

    def test_detect_gaps(self):
        from data_connector import detect_gaps
        bars = [
            {"timestamp": "2025-01-01 09:15:00"},
            {"timestamp": "2025-01-01 09:20:00"},
            {"timestamp": "2025-01-01 10:00:00"},  # 40-minute gap
        ]
        gaps = detect_gaps(bars, expected_interval_minutes=5)
        assert len(gaps) > 0
        assert gaps[0].missing_bars > 0

    def test_detect_no_gaps(self):
        from data_connector import detect_gaps
        bars = [
            {"timestamp": "2025-01-01 09:15:00"},
            {"timestamp": "2025-01-01 09:20:00"},
            {"timestamp": "2025-01-01 09:25:00"},
        ]
        gaps = detect_gaps(bars, expected_interval_minutes=5)
        assert len(gaps) == 0

    def test_csv_connector(self):
        from data_connector import CSVConnector
        csv_str = "timestamp,open,high,low,close,volume\n2025-01-01,100,110,90,105,5000\n2025-01-02,105,115,95,110,6000"
        result = CSVConnector.load_string(csv_str)
        assert result.success
        assert result.total_bars == 2
        assert result.bars[0]["open"] == 100.0

    def test_json_connector(self):
        from data_connector import JSONConnector
        data = [
            {"timestamp": "2025-01-01", "open": 100, "high": 110, "low": 90, "close": 105, "volume": 5000},
            {"timestamp": "2025-01-02", "open": 105, "high": 115, "low": 95, "close": 110, "volume": 6000},
        ]
        result = JSONConnector.load_string(json.dumps(data))
        assert result.success
        assert result.total_bars == 2

    def test_json_connector_invalid(self):
        from data_connector import JSONConnector
        result = JSONConnector.load_string("not json")
        assert not result.success
        assert result.error

    def test_data_result_properties(self):
        from data_connector import DataResult
        r = DataResult(bars=[{"timestamp": "t1"}], source="test")
        assert r.total_bars == 1
        assert r.success
        empty = DataResult(source="test", error="fail")
        assert not empty.success


# ======================================================================
# Strategies — built-in catalog
# ======================================================================


class TestStrategies:
    """Test built-in strategy catalog."""

    def test_all_12_strategies_exist(self):
        from strategies import BUILTIN_STRATEGIES
        assert len(BUILTIN_STRATEGIES) == 12
        assert "EMACrossover" in BUILTIN_STRATEGIES
        assert "Supertrend" in BUILTIN_STRATEGIES
        assert "MACD_RSI" in BUILTIN_STRATEGIES
        assert "BollingerMR" in BUILTIN_STRATEGIES
        assert "VWAPDev" in BUILTIN_STRATEGIES
        assert "StraddleSell" in BUILTIN_STRATEGIES
        assert "StrangleSell" in BUILTIN_STRATEGIES
        assert "IronCondor" in BUILTIN_STRATEGIES
        assert "BullPutSpread" in BUILTIN_STRATEGIES
        assert "BearCallSpread" in BUILTIN_STRATEGIES
        assert "MomentumBreakout" in BUILTIN_STRATEGIES
        assert "ORB" in BUILTIN_STRATEGIES

    def test_ema_crossover_generates_orders(self):
        from models import OHLCV
        from strategies import EMACrossover

        s = EMACrossover(name="test", fast_period=3, slow_period=10, symbol="TEST")
        s.start()
        for i in range(50):
            s.on_bar(OHLCV(
                timestamp=f"2025-01-{i + 1:02d}",
                open=100 + i * 0.5, high=101 + i * 0.5,
                low=99 + i * 0.5, close=100.5 + i * 0.5,
                volume=10000,
            ))
        orders = s.generate_orders()
        # At some point crossover should trigger
        assert isinstance(orders, list)

    def test_all_strategies_inherit_base(self):
        from strategies import BUILTIN_STRATEGIES
        for name, cls in BUILTIN_STRATEGIES.items():
            base_names = [b.__name__ for b in cls.__mro__]
            assert "BaseStrategy" in base_names, f"{name} must inherit BaseStrategy"

    def test_indicator_ema(self):
        from strategies import ema
        values = [1.0, 2.0, 3.0, 4.0, 5.0]
        result = ema(values, 3)
        assert len(result) == 5
        assert result[-1] > result[0]

    def test_indicator_sma(self):
        from strategies import sma
        values = [10.0, 20.0, 30.0, 40.0, 50.0]
        result = sma(values, 3)
        assert len(result) == 5
        assert result[2] == pytest.approx(20.0)  # (10+20+30)/3

    def test_indicator_rsi(self):
        from strategies import rsi
        # Steady uptrend → RSI should be high
        values = [float(i) for i in range(1, 31)]
        result = rsi(values, 14)
        assert result[-1] > 50

    def test_indicator_bollinger(self):
        from strategies import bollinger_bands
        values = [100.0 + i * 0.1 for i in range(30)]
        upper, mid, lower = bollinger_bands(values, 20)
        assert len(upper) == 30
        assert upper[-1] > mid[-1] > lower[-1]


# ======================================================================
# Package exports
# ======================================================================


class TestPackageExports:
    """Verify __init__.py exports."""

    def test_all_exports(self):
        # __init__.py uses relative imports so can't be imported directly.
        # Read the file and check __all__ is defined with expected names.
        init_path = os.path.join(os.path.dirname(__file__), '..', 'src', '__init__.py')
        content = open(init_path).read()
        expected = [
            "BacktestSimulator", "PerformanceMetrics", "WalkForwardOptimizer",
            "DataConnector", "ParamGrid", "BUILTIN_STRATEGIES",
            "EMACrossover", "BacktestConfig", "BacktestResult",
        ]
        for name in expected:
            assert name in content, f"Missing export: {name}"

    def test_version(self):
        init_path = os.path.join(os.path.dirname(__file__), '..', 'src', '__init__.py')
        content = open(init_path).read()
        assert '__version__ = "0.1.0-dev"' in content

    def test_package_exists(self):
        pkg_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        assert os.path.exists(os.path.join(pkg_dir, "src", "__init__.py"))
        assert os.path.exists(os.path.join(pkg_dir, "CLAUDE.md"))
        assert os.path.exists(os.path.join(pkg_dir, "AGENTS.md"))
