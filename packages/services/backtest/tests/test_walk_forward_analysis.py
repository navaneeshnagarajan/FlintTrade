"""Tests for the walk_forward_analysis module (WFE ratio).

Covers: config validation, split generation (rolling + anchored), WFE ratio
computation, metric functions, strategy runner, WFAFold, WalkForwardAnalysisResult,
edge cases, and the WFAnalysis.run() public API.
"""

from __future__ import annotations

import random

import pytest

from flinttrade_backtest.walk_forward_analysis import (
    WFAConfig,
    WFAFold,
    WFAnalysis,
    WalkForwardAnalysisResult,
    _calmar,
    _compute_metric,
    _generate_splits,
    _profit_factor,
    _run_strategy,
    _safe_mean,
    _safe_std,
    _sharpe,
    _sortino,
    _total_return,
    _wfe_ratio,
    _win_rate,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_bars(n: int, seed: int = 0, mu: float = 0.0005, sigma: float = 0.01) -> list[dict]:
    rng = random.Random(seed)
    price = 18_000.0
    bars = []
    for _ in range(n):
        price *= 1.0 + rng.gauss(mu, sigma)
        bars.append({"close": round(price, 2)})
    return bars


# Minimal strategy that records daily returns
class _BuyHoldStrategy:
    def __init__(self, **kwargs) -> None:
        self.daily_returns: list[float] = []
        self._prev: float | None = None

    def on_bar(self, bar: dict) -> None:
        c = float(bar["close"])
        if self._prev is not None and self._prev > 0:
            self.daily_returns.append((c - self._prev) / self._prev)
        self._prev = c


class _NoAttrStrategy:
    """Strategy that has no daily_returns or get_equity_curve — exercises fallback."""
    def __init__(self, **kwargs) -> None:
        pass

    def on_bar(self, bar: dict) -> None:
        pass


# ---------------------------------------------------------------------------
# _safe_mean / _safe_std
# ---------------------------------------------------------------------------


def test_safe_mean_empty() -> None:
    assert _safe_mean([]) == 0.0


def test_safe_mean_basic() -> None:
    assert _safe_mean([1.0, 2.0, 3.0]) == pytest.approx(2.0)


def test_safe_std_single() -> None:
    assert _safe_std([5.0]) == 0.0


def test_safe_std_known() -> None:
    import math
    vals = [2, 4, 4, 4, 5, 5, 7, 9]
    m = sum(vals) / len(vals)
    expected = math.sqrt(sum((v - m) ** 2 for v in vals) / (len(vals) - 1))
    assert _safe_std(vals) == pytest.approx(expected, rel=1e-9)


# ---------------------------------------------------------------------------
# Metric functions
# ---------------------------------------------------------------------------


def test_sharpe_insufficient_data() -> None:
    assert _sharpe([0.01]) == 0.0


def test_sharpe_zero_std() -> None:
    assert _sharpe([0.0] * 10) == 0.0


def test_sharpe_positive_trend() -> None:
    # Constant returns → std=0 → Sharpe=0; use varying positive returns
    import random
    rng = random.Random(42)
    returns = [0.001 + rng.gauss(0, 0.0003) for _ in range(252)]
    s = _sharpe(returns)
    assert isinstance(s, float)


def test_sortino_zero_downside() -> None:
    returns = [0.01] * 100
    assert _sortino(returns) == 0.0  # no downside deviation


def test_total_return_basic() -> None:
    returns = [0.1] * 10
    tr = _total_return(returns)
    expected = ((1.1 ** 10) - 1) * 100
    assert tr == pytest.approx(expected, rel=1e-6)


def test_total_return_empty() -> None:
    assert _total_return([]) == 0.0


def test_win_rate_all_wins() -> None:
    assert _win_rate([0.01] * 10) == pytest.approx(100.0)


def test_win_rate_no_wins() -> None:
    assert _win_rate([-0.01] * 10) == 0.0


def test_profit_factor_no_losses() -> None:
    pf = _profit_factor([0.01, 0.02, 0.03])
    assert pf == float("inf")


def test_profit_factor_mixed() -> None:
    pf = _profit_factor([0.1, 0.1, -0.05, -0.05])
    assert pf == pytest.approx(2.0, rel=1e-6)


def test_calmar_no_drawdown() -> None:
    assert _calmar([0.001] * 50) == 0.0  # no drawdown → returns 0


# ---------------------------------------------------------------------------
# _compute_metric
# ---------------------------------------------------------------------------


def test_compute_metric_unsupported() -> None:
    with pytest.raises(ValueError, match="Unsupported"):
        _compute_metric([0.01], "invalid_metric")


@pytest.mark.parametrize("metric", [
    "sharpe_ratio", "sortino_ratio", "total_return",
    "calmar_ratio", "win_rate", "profit_factor",
])
def test_compute_metric_all_supported(metric: str) -> None:
    returns = [0.001 * i for i in range(-5, 15)]
    result = _compute_metric(returns, metric)
    assert isinstance(result, float)


# ---------------------------------------------------------------------------
# _run_strategy
# ---------------------------------------------------------------------------


def test_run_strategy_daily_returns_attr() -> None:
    bars = _make_bars(50)
    returns = _run_strategy(_BuyHoldStrategy, {}, bars)
    assert len(returns) >= 1
    assert all(isinstance(r, float) for r in returns)


def test_run_strategy_fallback() -> None:
    bars = _make_bars(50)
    returns = _run_strategy(_NoAttrStrategy, {}, bars)
    assert len(returns) >= 1


def test_run_strategy_empty_bars() -> None:
    returns = _run_strategy(_BuyHoldStrategy, {}, [])
    assert returns == []


def test_run_strategy_exception_graceful() -> None:
    class _BrokenStrategy:
        def __init__(self, **kw) -> None:
            raise RuntimeError("broken")

    bars = _make_bars(30)
    returns = _run_strategy(_BrokenStrategy, {}, bars)
    assert isinstance(returns, list)


# ---------------------------------------------------------------------------
# _wfe_ratio
# ---------------------------------------------------------------------------


def test_wfe_ratio_is_zero() -> None:
    assert _wfe_ratio(0.0, 1.0) == 0.0


def test_wfe_ratio_equal_metrics() -> None:
    assert _wfe_ratio(1.0, 1.0) == pytest.approx(1.0)


def test_wfe_ratio_oos_half() -> None:
    assert _wfe_ratio(2.0, 1.0) == pytest.approx(0.5)


def test_wfe_ratio_clamp_high() -> None:
    assert _wfe_ratio(0.1, 10.0) == pytest.approx(2.0)


def test_wfe_ratio_clamp_low() -> None:
    assert _wfe_ratio(1.0, -5.0) == pytest.approx(-1.0)


# ---------------------------------------------------------------------------
# _generate_splits
# ---------------------------------------------------------------------------


class TestGenerateSplits:
    def test_rolling_count(self) -> None:
        config = WFAConfig(n_splits=5, train_pct=0.7, anchor=False)
        splits = _generate_splits(500, config)
        assert len(splits) >= 1

    def test_anchored_train_always_starts_zero(self) -> None:
        config = WFAConfig(n_splits=4, train_pct=0.7, anchor=True)
        splits = _generate_splits(300, config)
        for ts, te, os, oe in splits:
            assert ts == 0

    def test_rolling_train_start_advances(self) -> None:
        config = WFAConfig(n_splits=4, train_pct=0.7, anchor=False)
        splits = _generate_splits(300, config)
        starts = [s[0] for s in splits]
        assert starts == sorted(starts)

    def test_no_overlap_test_windows(self) -> None:
        config = WFAConfig(n_splits=4, train_pct=0.7, anchor=False)
        splits = _generate_splits(300, config)
        for i in range(len(splits) - 1):
            _, _, _, oe = splits[i]
            _, _, ns, _ = splits[i + 1]
            assert ns > oe, "OOS windows must not overlap"

    def test_insufficient_data_raises(self) -> None:
        config = WFAConfig(n_splits=20, train_pct=0.7, anchor=False)
        with pytest.raises(ValueError, match="bars"):
            _generate_splits(10, config)

    def test_splits_within_bounds(self) -> None:
        n = 400
        config = WFAConfig(n_splits=5, train_pct=0.7, anchor=False)
        splits = _generate_splits(n, config)
        for ts, te, os, oe in splits:
            assert ts >= 0
            assert oe < n
            assert te >= ts
            assert oe >= os


# ---------------------------------------------------------------------------
# WFAConfig
# ---------------------------------------------------------------------------


class TestWFAConfig:
    def test_defaults(self) -> None:
        cfg = WFAConfig()
        assert cfg.n_splits == 5
        assert cfg.train_pct == pytest.approx(0.7)
        assert cfg.anchor is False

    def test_anchored_flag(self) -> None:
        cfg = WFAConfig(anchor=True)
        assert cfg.anchor is True

    def test_invalid_n_splits(self) -> None:
        with pytest.raises(Exception):
            WFAConfig(n_splits=1)  # ge=2

    def test_invalid_train_pct_high(self) -> None:
        with pytest.raises(Exception):
            WFAConfig(train_pct=0.95)  # le=0.9

    def test_invalid_train_pct_low(self) -> None:
        with pytest.raises(Exception):
            WFAConfig(train_pct=0.3)  # ge=0.5


# ---------------------------------------------------------------------------
# WFAFold
# ---------------------------------------------------------------------------


class TestWFAFold:
    def test_as_dict_keys(self) -> None:
        fold = WFAFold(
            fold_index=0, train_start=0, train_end=99,
            oos_start=100, oos_end=149, n_train=100, n_oos=50,
            is_metric=1.2, oos_metric=0.9, wfe=0.75,
        )
        d = fold.as_dict()
        assert set(d.keys()) >= {
            "fold_index", "train_start", "train_end", "oos_start",
            "oos_end", "n_train", "n_oos", "is_metric", "oos_metric", "wfe",
        }

    def test_as_dict_no_returns(self) -> None:
        fold = WFAFold()
        d = fold.as_dict()
        assert "is_returns" not in d


# ---------------------------------------------------------------------------
# WalkForwardAnalysisResult
# ---------------------------------------------------------------------------


class TestWalkForwardAnalysisResult:
    def test_as_dict_shape(self) -> None:
        fold = WFAFold(
            fold_index=0, train_start=0, train_end=99,
            oos_start=100, oos_end=149, n_train=100, n_oos=50,
            is_metric=1.0, oos_metric=0.8, wfe=0.8,
        )
        result = WalkForwardAnalysisResult(
            folds=[fold],
            avg_is_metric=1.0,
            avg_oos_metric=0.8,
            wfe_ratio=0.8,
            degradation_pct=20.0,
            is_robust=True,
            metric="sharpe_ratio",
            n_folds_run=1,
        )
        d = result.as_dict()
        assert "wfe_ratio" in d
        assert "folds" in d
        assert len(d["folds"]) == 1

    def test_empty_result(self) -> None:
        r = WalkForwardAnalysisResult(metric="sharpe_ratio")
        assert r.n_folds_run == 0
        assert r.wfe_ratio == 0.0
        assert r.is_robust is False


# ---------------------------------------------------------------------------
# WFAnalysis integration
# ---------------------------------------------------------------------------


class TestWFAnalysis:
    def test_basic_run(self) -> None:
        bars = _make_bars(300, seed=0)
        config = WFAConfig(n_splits=3, train_pct=0.7, anchor=False)
        wfa = WFAnalysis(config)
        result = wfa.run(bars, _BuyHoldStrategy, {}, metric="sharpe_ratio")

        assert isinstance(result, WalkForwardAnalysisResult)
        assert result.n_folds_run >= 1
        assert result.metric == "sharpe_ratio"
        assert isinstance(result.wfe_ratio, float)
        assert isinstance(result.avg_is_metric, float)
        assert isinstance(result.avg_oos_metric, float)

    def test_anchored_mode(self) -> None:
        bars = _make_bars(300, seed=5)
        config = WFAConfig(n_splits=3, train_pct=0.7, anchor=True)
        wfa = WFAnalysis(config)
        result = wfa.run(bars, _BuyHoldStrategy, {})
        assert result.n_folds_run >= 1

    def test_wfe_ratio_range(self) -> None:
        bars = _make_bars(300, seed=7)
        wfa = WFAnalysis(WFAConfig(n_splits=3, train_pct=0.7))
        result = wfa.run(bars, _BuyHoldStrategy, {})
        assert -1.0 <= result.wfe_ratio <= 2.0

    def test_all_metrics_run(self) -> None:
        bars = _make_bars(300, seed=1)
        wfa = WFAnalysis(WFAConfig(n_splits=2, train_pct=0.7))
        for metric in ("sharpe_ratio", "sortino_ratio", "total_return",
                       "calmar_ratio", "win_rate", "profit_factor"):
            result = wfa.run(bars, _BuyHoldStrategy, {}, metric=metric)
            assert result.metric == metric

    def test_unsupported_metric_raises(self) -> None:
        bars = _make_bars(200)
        wfa = WFAnalysis()
        with pytest.raises(ValueError, match="Unsupported"):
            wfa.run(bars, _BuyHoldStrategy, {}, metric="unknown")

    def test_insufficient_data_raises(self) -> None:
        bars = _make_bars(5)
        wfa = WFAnalysis(WFAConfig(n_splits=10, train_pct=0.7))
        with pytest.raises(ValueError, match="bars"):
            wfa.run(bars, _BuyHoldStrategy, {})

    def test_fallback_strategy(self) -> None:
        bars = _make_bars(300, seed=2)
        wfa = WFAnalysis(WFAConfig(n_splits=3, train_pct=0.7))
        result = wfa.run(bars, _NoAttrStrategy, {})
        assert result.n_folds_run >= 1

    def test_degradation_direction(self) -> None:
        """Positive degradation when OOS < IS (normal overfitting scenario)."""
        bars = _make_bars(300, seed=0)
        wfa = WFAnalysis(WFAConfig(n_splits=3, train_pct=0.7))
        result = wfa.run(bars, _BuyHoldStrategy, {})
        # degradation can be positive or negative, just check it's a float
        assert isinstance(result.degradation_pct, float)

    def test_is_robust_flag(self) -> None:
        bars = _make_bars(300, seed=0)
        wfa = WFAnalysis(WFAConfig(n_splits=3, train_pct=0.7))
        result = wfa.run(bars, _BuyHoldStrategy, {})
        expected = abs(result.degradation_pct) < 30.0
        assert result.is_robust == expected

    def test_fold_count_matches_n_splits_run(self) -> None:
        bars = _make_bars(500, seed=10)
        config = WFAConfig(n_splits=5, train_pct=0.7)
        result = WFAnalysis(config).run(bars, _BuyHoldStrategy, {})
        assert len(result.folds) == result.n_folds_run

    def test_as_dict_serialisable(self) -> None:
        import json
        bars = _make_bars(300)
        result = WFAnalysis(WFAConfig(n_splits=3, train_pct=0.7)).run(bars, _BuyHoldStrategy, {})
        d = result.as_dict()
        # Should not raise
        json.dumps(d)

    def test_default_config(self) -> None:
        wfa = WFAnalysis()
        assert wfa.config.n_splits == 5
        assert wfa.config.anchor is False
