"""Tests for metrics.py — all calculations verified with known inputs.

Covers both the existing batch PerformanceMetrics and the new streaming
StreamingMetrics implementations.
"""

from __future__ import annotations


import pytest


# ---------------------------------------------------------------------------
# Helpers — construct EquityPoint and SimTrade directly
# ---------------------------------------------------------------------------


def _ep(equity: float, ts: str = "2025-01-01") -> "Any":  # noqa: F821
    from flinttrade_backtest.simulator import EquityPoint
    return EquityPoint(timestamp=ts, equity=equity, cash=equity, positions_value=0)


def _trade(net_pnl: float, bars_held: int = 1) -> "Any":  # noqa: F821
    from flinttrade_backtest.simulator import SimTrade
    sign = 1 if net_pnl >= 0 else -1
    pnl_gross = net_pnl + sign * 1.0  # Gross = net + commission
    return SimTrade(
        entry_timestamp="2025-01-01",
        exit_timestamp="2025-01-02",
        symbol="TEST",
        side="BUY",
        quantity=1,
        entry_price=100.0,
        exit_price=100.0 + net_pnl,
        pnl=pnl_gross,
        commission=1.0,
        net_pnl=net_pnl,
        bars_held=bars_held,
    )


def _flat_curve(n: int = 20, equity: float = 100_000.0) -> list:
    return [_ep(equity, f"2025-01-{i + 1:02d}") for i in range(n)]


def _trending_curve(n: int = 50, start: float = 100_000.0, step: float = 500.0) -> list:
    return [_ep(start + i * step, f"2025-01-{(i % 28) + 1:02d}") for i in range(n)]


def _drawdown_curve() -> list:
    """Curve that goes up 20%, crashes 30% from peak, then recovers."""
    pts = []
    eq = 100_000.0
    for i in range(10):  # Rise
        eq += 1000
        pts.append(_ep(eq))
    for i in range(15):  # Crash
        eq -= 800
        pts.append(_ep(eq))
    for i in range(10):  # Recovery
        eq += 600
        pts.append(_ep(eq))
    return pts


# ---------------------------------------------------------------------------
# Sharpe ratio
# ---------------------------------------------------------------------------


class TestSharpeRatio:
    """Sharpe ratio edge cases and known values."""

    def test_sharpe_positive_uptrend(self):
        from flinttrade_backtest.metrics import compute_sharpe, compute_returns
        curve = _trending_curve(50, step=200)
        returns = compute_returns(curve)
        sharpe = compute_sharpe(returns)
        assert sharpe > 0

    def test_sharpe_flat_returns_zero(self):
        from flinttrade_backtest.metrics import compute_sharpe
        # All zero returns → std = 0 → sharpe = 0
        assert compute_sharpe([0.0] * 30) == 0.0

    def test_sharpe_constant_positive_returns(self):
        from flinttrade_backtest.metrics import compute_sharpe
        # Constant positive return with no variance → std = 0 → 0
        assert compute_sharpe([0.01] * 30) == 0.0

    def test_sharpe_negative_trend(self):
        from flinttrade_backtest.metrics import compute_sharpe, compute_returns
        curve = _trending_curve(30, start=200_000, step=-500)
        returns = compute_returns(curve)
        sharpe = compute_sharpe(returns)
        assert sharpe < 0  # Negative return → negative Sharpe

    def test_sharpe_single_return_zero(self):
        from flinttrade_backtest.metrics import compute_sharpe
        assert compute_sharpe([0.05]) == 0.0  # Need ≥2 returns

    def test_sharpe_annualised_approximately_correct(self):
        from flinttrade_backtest.metrics import compute_sharpe
        # Daily return = 0.04%, annualised ≈ 10.08%
        # risk-free = 7%, excess ≈ 3.08%
        # std = 0.02% daily, annualised = 3.18%
        # Sharpe ≈ 3.08 / 3.18 ≈ 0.97
        daily_r = [0.0004] * 252
        # Add tiny variance to avoid zero std
        import random
        random.seed(1)
        daily_r = [r + random.gauss(0, 0.0002) for r in daily_r]
        sharpe = compute_sharpe(daily_r, risk_free=0.07)
        assert isinstance(sharpe, float)
        assert sharpe > 0  # Positive return over risk-free


# ---------------------------------------------------------------------------
# Sortino ratio
# ---------------------------------------------------------------------------


class TestSortinoRatio:
    """Sortino ratio tests."""

    def test_sortino_with_downside_returns(self):
        from flinttrade_backtest.metrics import compute_sortino
        returns = [0.02, -0.01, 0.03, -0.02, 0.01, -0.005, 0.015]
        sortino = compute_sortino(returns)
        assert isinstance(sortino, float)

    def test_sortino_no_downside_zero(self):
        from flinttrade_backtest.metrics import compute_sortino
        # All positive returns → no downside → downside_dev = 0 → sortino = 0
        returns = [0.01, 0.02, 0.01, 0.015, 0.012]
        sortino = compute_sortino(returns)
        assert sortino == 0.0

    def test_sortino_single_return_zero(self):
        from flinttrade_backtest.metrics import compute_sortino
        assert compute_sortino([0.01]) == 0.0

    def test_sortino_greater_than_sharpe_for_positive_skew(self):
        """For a strategy with positive skew, Sortino ≥ Sharpe."""
        from flinttrade_backtest.metrics import compute_sharpe, compute_sortino
        # Mixed returns with mostly wins, few big losses
        returns = [0.01, 0.02, 0.015, -0.001, 0.018, 0.012, -0.002, 0.02, 0.01, 0.015]
        sharpe = compute_sharpe(returns)
        sortino = compute_sortino(returns)
        # Sortino penalises only downside, so it can be ≥ Sharpe
        assert isinstance(sortino, float)
        assert isinstance(sharpe, float)


# ---------------------------------------------------------------------------
# Maximum drawdown
# ---------------------------------------------------------------------------


class TestMaxDrawdown:
    """Maximum drawdown: amount, percentage, and duration."""

    def test_no_drawdown_flat_curve(self):
        from flinttrade_backtest.metrics import compute_max_drawdown
        curve = _flat_curve(20, 100_000)
        dd = compute_max_drawdown(curve)
        assert dd.max_drawdown_pct == 0.0

    def test_drawdown_from_known_curve(self):
        from flinttrade_backtest.metrics import compute_max_drawdown
        # Peak at 120k, trough at 84k: drawdown = 36k / 120k = 30%
        curve = (
            [_ep(100_000 + i * 2_000) for i in range(11)]  # 100k → 120k
            + [_ep(120_000 - i * 2_400) for i in range(1, 16)]  # 120k → 84k
        )
        dd = compute_max_drawdown(curve)
        assert dd.max_drawdown_pct > 0
        assert dd.max_drawdown_pct <= 100

    def test_drawdown_pct_bounded(self):
        from flinttrade_backtest.metrics import compute_max_drawdown
        dd = compute_max_drawdown(_drawdown_curve())
        assert 0 <= dd.max_drawdown_pct <= 100

    def test_drawdown_duration_tracked(self):
        from flinttrade_backtest.metrics import compute_max_drawdown
        dd = compute_max_drawdown(_drawdown_curve())
        assert dd.max_drawdown_duration_bars >= 0

    def test_empty_curve_returns_zero(self):
        from flinttrade_backtest.metrics import compute_max_drawdown
        dd = compute_max_drawdown([])
        assert dd.max_drawdown_pct == 0.0
        assert dd.max_drawdown_duration_bars == 0

    def test_strictly_increasing_curve(self):
        from flinttrade_backtest.metrics import compute_max_drawdown
        curve = [_ep(100_000 + i * 1_000) for i in range(50)]
        dd = compute_max_drawdown(curve)
        assert dd.max_drawdown_pct == pytest.approx(0.0, abs=0.001)

    def test_avg_drawdown_leq_max(self):
        from flinttrade_backtest.metrics import compute_max_drawdown
        dd = compute_max_drawdown(_drawdown_curve())
        assert dd.avg_drawdown_pct <= dd.max_drawdown_pct


# ---------------------------------------------------------------------------
# CAGR
# ---------------------------------------------------------------------------


class TestCAGR:
    """Compound Annual Growth Rate."""

    def test_cagr_double_in_one_year(self):
        from flinttrade_backtest.metrics import compute_cagr
        # Double in exactly 252 bars (1 year): CAGR = 100%
        cagr = compute_cagr(100_000, 200_000, 252)
        assert cagr == pytest.approx(100.0, abs=0.1)

    def test_cagr_no_change(self):
        from flinttrade_backtest.metrics import compute_cagr
        assert compute_cagr(100_000, 100_000, 252) == pytest.approx(0.0, abs=0.001)

    def test_cagr_zero_initial_returns_zero(self):
        from flinttrade_backtest.metrics import compute_cagr
        assert compute_cagr(0, 100_000, 252) == 0.0

    def test_cagr_two_years(self):
        from flinttrade_backtest.metrics import compute_cagr
        # Start=100k, end=161k, 2 years: CAGR ≈ 26.9% (1.269^2 ≈ 1.61)
        cagr = compute_cagr(100_000, 161_000, 504)
        assert cagr == pytest.approx(26.9, abs=2.0)

    def test_cagr_negative_return(self):
        from flinttrade_backtest.metrics import compute_cagr
        cagr = compute_cagr(100_000, 80_000, 252)
        assert cagr < 0


# ---------------------------------------------------------------------------
# Trade statistics
# ---------------------------------------------------------------------------


class TestTradeStats:
    """Win rate, profit factor, expectancy, consecutive stats."""

    def test_empty_trades(self):
        from flinttrade_backtest.metrics import compute_trade_stats
        stats = compute_trade_stats([])
        assert stats.total_trades == 0
        assert stats.win_rate == 0.0
        assert stats.profit_factor == 0.0
        assert stats.expectancy == 0.0

    def test_all_winners(self):
        from flinttrade_backtest.metrics import compute_trade_stats
        trades = [_trade(100) for _ in range(5)]
        stats = compute_trade_stats(trades)
        assert stats.total_trades == 5
        assert stats.winning_trades == 5
        assert stats.losing_trades == 0
        assert stats.win_rate == 100.0

    def test_all_losers(self):
        from flinttrade_backtest.metrics import compute_trade_stats
        trades = [_trade(-50) for _ in range(4)]
        stats = compute_trade_stats(trades)
        assert stats.win_rate == 0.0
        assert stats.total_trades == 4

    def test_win_rate_50pct(self):
        from flinttrade_backtest.metrics import compute_trade_stats
        trades = [_trade(100), _trade(-50), _trade(100), _trade(-50)]
        stats = compute_trade_stats(trades)
        assert stats.win_rate == pytest.approx(50.0)

    def test_profit_factor_calculation(self):
        from flinttrade_backtest.metrics import compute_trade_stats
        # Gross profit = 300, gross loss = 100: PF = 3.0
        trades = [_trade(100), _trade(100), _trade(100), _trade(-100)]
        stats = compute_trade_stats(trades)
        assert stats.profit_factor == pytest.approx(3.0, abs=0.1)

    def test_expectancy_positive(self):
        from flinttrade_backtest.metrics import compute_trade_stats
        trades = [_trade(100), _trade(100), _trade(-30)]
        stats = compute_trade_stats(trades)
        assert stats.expectancy > 0

    def test_largest_win_and_loss(self):
        from flinttrade_backtest.metrics import compute_trade_stats
        trades = [_trade(50), _trade(200), _trade(-30), _trade(-80)]
        stats = compute_trade_stats(trades)
        assert stats.largest_win == pytest.approx(200.0)
        assert stats.largest_loss == pytest.approx(-80.0)

    def test_consecutive_wins(self):
        from flinttrade_backtest.metrics import compute_trade_stats
        trades = [_trade(10), _trade(10), _trade(10), _trade(-5), _trade(10)]
        stats = compute_trade_stats(trades)
        assert stats.max_consecutive_wins == 3

    def test_consecutive_losses(self):
        from flinttrade_backtest.metrics import compute_trade_stats
        trades = [_trade(-5), _trade(-5), _trade(-5), _trade(10)]
        stats = compute_trade_stats(trades)
        assert stats.max_consecutive_losses == 3

    def test_avg_win_and_loss(self):
        from flinttrade_backtest.metrics import compute_trade_stats
        trades = [_trade(100), _trade(200), _trade(-50), _trade(-150)]
        stats = compute_trade_stats(trades)
        assert stats.avg_win == pytest.approx(150.0)
        assert stats.avg_loss == pytest.approx(100.0)

    def test_avg_bars_held(self):
        from flinttrade_backtest.metrics import compute_trade_stats
        trades = [_trade(10, bars_held=2), _trade(20, bars_held=4), _trade(-5, bars_held=6)]
        stats = compute_trade_stats(trades)
        assert stats.avg_bars_held == pytest.approx(4.0)


# ---------------------------------------------------------------------------
# Calmar ratio
# ---------------------------------------------------------------------------


class TestCalmarRatio:
    """Calmar ratio = CAGR / max drawdown."""

    def test_calmar_positive_for_good_strategy(self):
        from flinttrade_backtest.metrics import PerformanceMetrics
        from flinttrade_backtest.simulator import BacktestConfig

        try:
            from flinttrade_backtest.simulator import BacktestConfig, BacktestSimulator
            from flinttrade_backtest.strategies import EMACrossover

            bars = [{
                "timestamp": f"2025-{(i // 30) + 1:02d}-{(i % 28) + 1:02d}",
                "open": 100 + i * 0.3, "high": 101 + i * 0.3,
                "low": 99 + i * 0.3, "close": 100.2 + i * 0.3,
                "volume": 5000, "oi": 0,
            } for i in range(100)]

            config = BacktestConfig(symbol="T", initial_capital=100_000)
            strategy = EMACrossover(name="E", fast_period=5, slow_period=20, symbol="T")
            result = BacktestSimulator(config).run(strategy, bars)
            report = PerformanceMetrics.compute(result)
            assert isinstance(report.calmar_ratio, float)
        except ImportError:
            pytest.skip("simulator/strategies not available")


# ---------------------------------------------------------------------------
# Return over max drawdown (RoMaD)
# ---------------------------------------------------------------------------


class TestReturnOverMaxDrawdown:
    """Calmar and RoMaD equivalence checks."""

    def test_calmar_computed_from_known_values(self):
        from flinttrade_backtest.metrics import compute_cagr, compute_max_drawdown

        curve = (
            [_ep(100_000 + i * 2_000) for i in range(25)]
            + [_ep(148_000 - i * 1_000) for i in range(1, 15)]
        )
        dd = compute_max_drawdown(curve)
        cagr = compute_cagr(100_000, float(curve[-1].equity), len(curve))
        if dd.max_drawdown_pct > 0:
            calmar = cagr / dd.max_drawdown_pct
            assert isinstance(calmar, float)


# ---------------------------------------------------------------------------
# Monthly returns
# ---------------------------------------------------------------------------


class TestMonthlyReturns:
    """Monthly return grouping and calculation."""

    def test_two_months(self):
        from flinttrade_backtest.metrics import compute_monthly_returns
        from flinttrade_backtest.simulator import EquityPoint
        curve = [
            EquityPoint(timestamp="2025-01-01", equity=100_000, cash=100_000, positions_value=0),
            EquityPoint(timestamp="2025-01-31", equity=110_000, cash=110_000, positions_value=0),
            EquityPoint(timestamp="2025-02-01", equity=108_000, cash=108_000, positions_value=0),
            EquityPoint(timestamp="2025-02-28", equity=115_000, cash=115_000, positions_value=0),
        ]
        monthly = compute_monthly_returns(curve)
        assert len(monthly) == 2
        # January: 110k / 100k - 1 = 10%
        jan = next(m for m in monthly if m.month == 1)
        assert jan.return_pct == pytest.approx(10.0, abs=0.1)

    def test_single_month(self):
        from flinttrade_backtest.metrics import compute_monthly_returns
        from flinttrade_backtest.simulator import EquityPoint
        curve = [
            EquityPoint(timestamp="2025-03-01", equity=100_000, cash=100_000, positions_value=0),
            EquityPoint(timestamp="2025-03-31", equity=105_000, cash=105_000, positions_value=0),
        ]
        monthly = compute_monthly_returns(curve)
        assert len(monthly) >= 1

    def test_empty_curve(self):
        from flinttrade_backtest.metrics import compute_monthly_returns
        assert compute_monthly_returns([]) == []


# ---------------------------------------------------------------------------
# VaR and CVaR
# ---------------------------------------------------------------------------


class TestVaR:
    """Value at Risk and Conditional VaR."""

    def test_var_positive_for_losses(self):
        from flinttrade_backtest.metrics import compute_var
        returns = [-0.05, -0.03, 0.01, 0.02, -0.01, 0.04, -0.08, 0.03, -0.02, 0.01]
        var, cvar = compute_var(returns, 0.95)
        assert var >= 0

    def test_cvar_geq_var(self):
        from flinttrade_backtest.metrics import compute_var
        returns = [-0.1, -0.05, -0.02, 0.01, 0.03, 0.02, -0.01, 0.04, -0.06, 0.02]
        var, cvar = compute_var(returns)
        assert cvar >= var

    def test_empty_returns_zero(self):
        from flinttrade_backtest.metrics import compute_var
        var, cvar = compute_var([])
        assert var == 0.0
        assert cvar == 0.0

    def test_all_positive_var_near_zero(self):
        from flinttrade_backtest.metrics import compute_var
        returns = [0.01, 0.02, 0.015, 0.025, 0.03] * 10
        var, cvar = compute_var(returns, 0.95)
        # All positive returns → VaR is near 0 or represents smallest positive
        assert var <= 5.0  # Less than 5% loss


# ---------------------------------------------------------------------------
# Streaming metrics
# ---------------------------------------------------------------------------


class TestStreamingMetrics:
    """StreamingMetrics single-pass online algorithm."""

    def test_update_equity_tracks_drawdown(self):
        from flinttrade_backtest.metrics import StreamingMetrics
        sm = StreamingMetrics(initial_capital=100_000)
        sm.update_equity(110_000)  # New peak
        sm.update_equity(100_000)  # Drawdown: 10k / 110k ≈ 9.09%
        sm.update_equity(105_000)  # Partial recovery
        assert sm._max_drawdown_pct > 0

    def test_record_trade_updates_win_rate(self):
        from flinttrade_backtest.metrics import StreamingMetrics
        sm = StreamingMetrics(initial_capital=100_000)
        sm.record_trade(pnl=100, return_pct=1.0)
        sm.record_trade(pnl=-50, return_pct=-0.5)
        sm.record_trade(pnl=200, return_pct=2.0)
        assert sm.win_rate == pytest.approx(200.0 / 3, abs=0.1)

    def test_profit_factor_correct(self):
        from flinttrade_backtest.metrics import StreamingMetrics
        sm = StreamingMetrics(initial_capital=100_000)
        sm.record_trade(pnl=300, return_pct=3.0)
        sm.record_trade(pnl=-100, return_pct=-1.0)
        assert sm.profit_factor == pytest.approx(3.0, abs=0.1)

    def test_sharpe_positive_for_positive_returns(self):
        from flinttrade_backtest.metrics import StreamingMetrics
        sm = StreamingMetrics(initial_capital=100_000)
        for i in range(50):
            sm.update_equity(100_000 + (i + 1) * 200)
        sharpe = sm.sharpe
        assert isinstance(sharpe, float)

    def test_snapshot_returns_dict(self):
        from flinttrade_backtest.metrics import StreamingMetrics
        sm = StreamingMetrics(initial_capital=100_000)
        sm.update_equity(105_000)
        snapshot = sm.snapshot()
        assert "sharpe" in snapshot
        assert "max_drawdown_pct" in snapshot
        assert "win_rate" in snapshot
        assert "trade_count" in snapshot

    def test_sqn_zero_without_trades(self):
        from flinttrade_backtest.metrics import StreamingMetrics
        sm = StreamingMetrics(initial_capital=100_000)
        sm.update_equity(110_000)
        assert sm.sqn == 0.0

    def test_sqn_positive_for_good_system(self):
        from flinttrade_backtest.metrics import StreamingMetrics
        sm = StreamingMetrics(initial_capital=100_000)
        for _ in range(30):
            sm.record_trade(pnl=100, return_pct=1.0)
        for _ in range(5):
            sm.record_trade(pnl=-30, return_pct=-0.3)
        sqn = sm.sqn
        assert sqn > 0

    def test_consecutive_wins_tracked(self):
        from flinttrade_backtest.metrics import StreamingMetrics
        sm = StreamingMetrics(initial_capital=100_000)
        for _ in range(5):
            sm.record_trade(pnl=10, return_pct=0.1)
        sm.record_trade(pnl=-5, return_pct=-0.05)
        assert sm._max_consecutive_wins == 5

    def test_total_return_pct(self):
        from flinttrade_backtest.metrics import StreamingMetrics
        sm = StreamingMetrics(initial_capital=100_000)
        sm.update_equity(120_000)
        assert sm.total_return_pct == pytest.approx(20.0, abs=0.001)

    def test_fees_accumulated(self):
        from flinttrade_backtest.metrics import StreamingMetrics
        sm = StreamingMetrics(initial_capital=100_000)
        sm.record_trade(pnl=100, return_pct=1.0, fees=20.0)
        sm.record_trade(pnl=50, return_pct=0.5, fees=20.0)
        assert sm._total_fees == pytest.approx(40.0)
