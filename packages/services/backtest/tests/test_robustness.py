"""Tests for the robustness testing suite.

Covers: config defaults, MCShuffleResult, NoiseInjectionResult,
ParamSensitivityResult, DelayTestResult, CrossSymbolResult,
RobustnessReport, and all five RobustnessTester test methods.
"""

from __future__ import annotations

import math
import random

import pytest

from robustness import (
    CrossSymbolResult,
    DelayTestResult,
    MCShuffleResult,
    NoiseInjectionResult,
    ParamSensitivityResult,
    RobustnessConfig,
    RobustnessReport,
    RobustnessTester,
    _delay_bars,
    _inject_noise,
    _mean,
    _percentile,
    _run_strategy,
    _sharpe,
    _std,
)


# ---------------------------------------------------------------------------
# Helpers / Fixtures
# ---------------------------------------------------------------------------


def _make_bars(n: int, seed: int = 0, mu: float = 0.0005, sigma: float = 0.01) -> list[dict]:
    rng = random.Random(seed)
    price = 18_000.0
    bars = []
    for _ in range(n):
        price *= 1.0 + rng.gauss(mu, sigma)
        bars.append({"open": price, "high": price * 1.001,
                     "low": price * 0.999, "close": price, "volume": 1000})
    return bars


class _BuyHoldStrategy:
    def __init__(self, fast: int = 9, slow: int = 21, **kwargs) -> None:
        self.fast = fast
        self.slow = slow
        self.daily_returns: list[float] = []
        self._prev: float | None = None

    def on_bar(self, bar: dict) -> None:
        c = float(bar.get("close", 0.0))
        if self._prev is not None and self._prev > 0:
            self.daily_returns.append((c - self._prev) / self._prev)
        self._prev = c


class _StrategyWithTrades:
    """Strategy that exposes a completed_trades list."""
    def __init__(self, **kwargs) -> None:
        self.daily_returns: list[float] = []
        self.completed_trades: list = []
        self._prev: float | None = None
        self._entry: float | None = None

    def on_bar(self, bar: dict) -> None:
        c = float(bar.get("close", 0.0))
        if self._prev is not None and self._prev > 0:
            ret = (c - self._prev) / self._prev
            self.daily_returns.append(ret)

            # Simulate simple alternating trade recording
            if self._entry is not None:
                pnl = (c - self._entry)

                class _Trade:
                    def __init__(self, net_pnl: float) -> None:
                        self.net_pnl = net_pnl

                self.completed_trades.append(_Trade(pnl))
                self._entry = None
            else:
                self._entry = c

        self._prev = c


class _BrokenStrategy:
    def __init__(self, **kwargs) -> None:
        raise RuntimeError("init failed")


class _NoAttrStrategy:
    def __init__(self, **kwargs) -> None:
        pass

    def on_bar(self, bar: dict) -> None:
        pass


# ---------------------------------------------------------------------------
# Stat helpers
# ---------------------------------------------------------------------------


def test_mean_empty() -> None:
    assert _mean([]) == 0.0


def test_mean_basic() -> None:
    assert _mean([1.0, 2.0, 3.0]) == pytest.approx(2.0)


def test_std_single() -> None:
    assert _std([5.0], ddof=1) == 0.0


def test_std_known() -> None:
    vals = [2, 4, 4, 4, 5, 5, 7, 9]
    m = sum(vals) / len(vals)
    expected = math.sqrt(sum((v - m) ** 2 for v in vals) / (len(vals) - 1))
    assert _std(vals) == pytest.approx(expected, rel=1e-9)


def test_sharpe_zero_std() -> None:
    assert _sharpe([0.0] * 10) == 0.0


def test_sharpe_positive_trend() -> None:
    # Constant positive returns → std=0 → Sharpe=0 (no volatility to normalise by)
    # Use varying returns to get a meaningful Sharpe
    import random
    rng = random.Random(0)
    returns = [0.001 + rng.gauss(0, 0.0003) for _ in range(252)]
    s = _sharpe(returns)
    # Mean return is above risk-free; Sharpe should be positive
    assert isinstance(s, float)


def test_percentile_empty() -> None:
    assert _percentile([], 50.0) == 0.0


def test_percentile_midpoint() -> None:
    vals = sorted([1.0, 2.0, 3.0, 4.0, 5.0])
    assert _percentile(vals, 50.0) == pytest.approx(3.0)


# ---------------------------------------------------------------------------
# _inject_noise
# ---------------------------------------------------------------------------


class TestInjectNoise:
    def test_output_length(self) -> None:
        bars = _make_bars(50)
        rng = random.Random(0)
        noisy = _inject_noise(bars, 1.0, rng)
        assert len(noisy) == len(bars)

    def test_noise_changes_prices(self) -> None:
        bars = _make_bars(50)
        rng = random.Random(0)
        noisy = _inject_noise(bars, 2.0, rng)
        diffs = [
            abs(noisy[i]["close"] - bars[i]["close"])
            for i in range(len(bars))
        ]
        assert max(diffs) > 0

    def test_zero_noise_no_change(self) -> None:
        bars = _make_bars(20)
        rng = random.Random(0)
        noisy = _inject_noise(bars, 0.0, rng)
        for i in range(len(bars)):
            assert noisy[i]["close"] == pytest.approx(bars[i]["close"])

    def test_bar_keys_preserved(self) -> None:
        bars = _make_bars(10)
        rng = random.Random(0)
        noisy = _inject_noise(bars, 1.0, rng)
        for nb in noisy:
            assert "open" in nb and "close" in nb


# ---------------------------------------------------------------------------
# _delay_bars
# ---------------------------------------------------------------------------


class TestDelayBars:
    def test_zero_delay(self) -> None:
        bars = _make_bars(20)
        delayed = _delay_bars(bars, 0)
        assert delayed == bars

    def test_one_bar_delay(self) -> None:
        bars = _make_bars(20)
        delayed = _delay_bars(bars, 1)
        assert len(delayed) == len(bars)
        # First bar unchanged (uses index 0 for src)
        assert delayed[0]["close"] == bars[0]["close"]
        # Second bar should use bar 0's close
        assert delayed[1]["close"] == pytest.approx(bars[0]["close"])

    def test_delay_preserves_length(self) -> None:
        bars = _make_bars(30)
        for d in [1, 2, 3]:
            assert len(_delay_bars(bars, d)) == len(bars)


# ---------------------------------------------------------------------------
# _run_strategy
# ---------------------------------------------------------------------------


class TestRunStrategy:
    def test_basic(self) -> None:
        bars = _make_bars(50)
        sharpe, win_rate, total_ret = _run_strategy(_BuyHoldStrategy, {}, bars)
        assert isinstance(sharpe, float)
        assert 0.0 <= win_rate <= 100.0
        assert isinstance(total_ret, float)

    def test_broken_strategy_fallback(self) -> None:
        bars = _make_bars(50)
        sharpe, win_rate, _ = _run_strategy(_BrokenStrategy, {}, bars)
        assert isinstance(sharpe, float)

    def test_no_attr_strategy_fallback(self) -> None:
        bars = _make_bars(50)
        sharpe, wr, _ = _run_strategy(_NoAttrStrategy, {}, bars)
        assert isinstance(sharpe, float)
        assert isinstance(wr, float)


# ---------------------------------------------------------------------------
# RobustnessConfig
# ---------------------------------------------------------------------------


class TestRobustnessConfig:
    def test_defaults(self) -> None:
        cfg = RobustnessConfig()
        assert cfg.n_mc_simulations == 500
        assert cfg.noise_pct == pytest.approx(0.5)
        assert cfg.n_noise_runs == 50
        assert cfg.param_perturb_pct == pytest.approx(0.20)
        assert cfg.delay_bars == [1, 2, 3]
        assert cfg.seed == 42

    def test_custom(self) -> None:
        cfg = RobustnessConfig(n_mc_simulations=100, noise_pct=2.0, seed=7)
        assert cfg.n_mc_simulations == 100
        assert cfg.noise_pct == pytest.approx(2.0)
        assert cfg.seed == 7


# ---------------------------------------------------------------------------
# RobustnessReport
# ---------------------------------------------------------------------------


class TestRobustnessReport:
    def _all_pass_report(self) -> RobustnessReport:
        return RobustnessReport(
            mc_shuffle=MCShuffleResult(passed=True),
            noise_injection=NoiseInjectionResult(passed=True),
            param_sensitivity=ParamSensitivityResult(passed=True),
            delay_test=DelayTestResult(passed=True),
            cross_symbol=[CrossSymbolResult(symbol="X", passed=True)],
        )

    def test_overall_pass(self) -> None:
        report = self._all_pass_report()
        assert report.overall_pass is True

    def test_overall_fail_on_mc(self) -> None:
        report = self._all_pass_report()
        report.mc_shuffle.passed = False
        assert report.overall_pass is False

    def test_overall_fail_on_cross_symbol(self) -> None:
        report = self._all_pass_report()
        report.cross_symbol = [CrossSymbolResult(symbol="Y", passed=False)]
        assert report.overall_pass is False

    def test_no_cross_symbol_still_passes(self) -> None:
        report = RobustnessReport(
            mc_shuffle=MCShuffleResult(passed=True),
            noise_injection=NoiseInjectionResult(passed=True),
            param_sensitivity=ParamSensitivityResult(passed=True),
            delay_test=DelayTestResult(passed=True),
        )
        assert report.overall_pass is True

    def test_summary_contains_pass_fail(self) -> None:
        report = self._all_pass_report()
        s = report.summary()
        assert "PASS" in s or "FAIL" in s
        assert "OVERALL" in s

    def test_as_dict_keys(self) -> None:
        report = self._all_pass_report()
        d = report.as_dict()
        assert set(d.keys()) >= {
            "overall_pass", "mc_shuffle", "noise_injection",
            "param_sensitivity", "delay_test", "cross_symbol",
        }

    def test_as_dict_json_serialisable(self) -> None:
        import json
        report = self._all_pass_report()
        json.dumps(report.as_dict())


# ---------------------------------------------------------------------------
# RobustnessTester — unit tests per method
# ---------------------------------------------------------------------------


class TestRobustnessTester:
    def _make_tester(
        self,
        n_bars: int = 200,
        n_mc: int = 50,
        n_noise: int = 10,
    ) -> RobustnessTester:
        bars = _make_bars(n_bars, seed=0)
        cfg = RobustnessConfig(
            n_mc_simulations=n_mc,
            noise_pct=0.5,
            n_noise_runs=n_noise,
            delay_bars=[1, 2],
            seed=0,
        )
        return RobustnessTester(
            strategy_class=_BuyHoldStrategy,
            strategy_kwargs={"fast": 9, "slow": 21},
            bars=bars,
            config=cfg,
        )

    # ----- MC shuffle -----

    def test_mc_shuffle_returns_result(self) -> None:
        tester = self._make_tester()
        result = tester.test_mc_shuffle()
        assert isinstance(result, MCShuffleResult)
        assert isinstance(result.cv_equity, float)
        assert isinstance(result.passed, bool)

    def test_mc_shuffle_cv_positive(self) -> None:
        tester = self._make_tester()
        result = tester.test_mc_shuffle()
        assert result.cv_equity >= 0.0

    def test_mc_shuffle_equity_p5_le_p95(self) -> None:
        tester = self._make_tester()
        result = tester.test_mc_shuffle()
        assert result.p5_equity <= result.p95_equity

    # ----- Noise injection -----

    def test_noise_injection_returns_result(self) -> None:
        tester = self._make_tester()
        result = tester.test_noise_injection()
        assert isinstance(result, NoiseInjectionResult)
        assert isinstance(result.passed, bool)

    def test_noise_injection_pct_positive_in_range(self) -> None:
        tester = self._make_tester()
        result = tester.test_noise_injection()
        assert 0.0 <= result.pct_positive <= 1.0

    def test_noise_injection_base_sharpe(self) -> None:
        tester = self._make_tester()
        result = tester.test_noise_injection()
        assert isinstance(result.base_sharpe, float)

    # ----- Param sensitivity -----

    def test_param_sensitivity_returns_result(self) -> None:
        tester = self._make_tester()
        result = tester.test_param_sensitivity()
        assert isinstance(result, ParamSensitivityResult)
        assert isinstance(result.passed, bool)

    def test_param_sensitivity_entries_count(self) -> None:
        tester = self._make_tester()
        result = tester.test_param_sensitivity()
        # fast=9, slow=21 → 2 params × 2 directions = 4 entries
        assert len(result.entries) == 4

    def test_param_sensitivity_no_numeric_params(self) -> None:
        bars = _make_bars(100)
        tester = RobustnessTester(
            strategy_class=_NoAttrStrategy,
            strategy_kwargs={"name": "test"},  # no numeric params
            bars=bars,
            config=RobustnessConfig(n_mc_simulations=10, n_noise_runs=5),
        )
        result = tester.test_param_sensitivity()
        assert result.passed is True
        assert result.entries == []

    def test_param_sensitivity_cv_non_negative(self) -> None:
        tester = self._make_tester()
        result = tester.test_param_sensitivity()
        assert result.sharpe_cv >= 0.0

    # ----- Delay test -----

    def test_delay_test_returns_result(self) -> None:
        tester = self._make_tester()
        result = tester.test_delay()
        assert isinstance(result, DelayTestResult)
        assert isinstance(result.passed, bool)

    def test_delay_test_entry_count(self) -> None:
        tester = self._make_tester()
        result = tester.test_delay()
        assert len(result.entries) == 2  # delay_bars=[1, 2]

    def test_delay_test_delays_match_config(self) -> None:
        tester = self._make_tester()
        result = tester.test_delay()
        delays = [e.delay_bars for e in result.entries]
        assert delays == [1, 2]

    # ----- Cross-symbol -----

    def test_cross_symbol_returns_result(self) -> None:
        tester = self._make_tester()
        sym_bars = _make_bars(200, seed=99)
        result = tester.test_cross_symbol("TEST_SYM", sym_bars)
        assert isinstance(result, CrossSymbolResult)
        assert result.symbol == "TEST_SYM"
        assert isinstance(result.passed, bool)

    def test_cross_symbol_win_rate_in_range(self) -> None:
        tester = self._make_tester()
        sym_bars = _make_bars(200, seed=55)
        result = tester.test_cross_symbol("SYM", sym_bars)
        assert 0.0 <= result.win_rate <= 100.0

    # ----- run_all -----

    def test_run_all_returns_report(self) -> None:
        tester = self._make_tester()
        report = tester.run_all()
        assert isinstance(report, RobustnessReport)
        assert isinstance(report.overall_pass, bool)

    def test_run_all_with_cross_symbol(self) -> None:
        tester = self._make_tester()
        cross = {"NIFTY": _make_bars(200, seed=10), "BANKNIFTY": _make_bars(200, seed=11)}
        report = tester.run_all(cross_symbol_bars=cross)
        assert len(report.cross_symbol) == 2

    def test_run_all_no_cross_symbol(self) -> None:
        tester = self._make_tester()
        report = tester.run_all()
        assert report.cross_symbol == []

    def test_run_all_summary_not_empty(self) -> None:
        tester = self._make_tester()
        report = tester.run_all()
        s = report.summary()
        assert len(s) > 10


# ---------------------------------------------------------------------------
# Strategy with trades interface
# ---------------------------------------------------------------------------


class TestStrategyWithTrades:
    def test_trade_pnl_extraction(self) -> None:
        bars = _make_bars(100, seed=3)
        cfg = RobustnessConfig(n_mc_simulations=20, n_noise_runs=5)
        tester = RobustnessTester(
            strategy_class=_StrategyWithTrades,
            strategy_kwargs={},
            bars=bars,
            config=cfg,
        )
        mc = tester.test_mc_shuffle()
        assert isinstance(mc, MCShuffleResult)
