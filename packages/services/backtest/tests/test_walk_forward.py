"""Tests for the walk-forward analysis module.

Covers: config validation, split generation (rolling + anchored), metric
computation helpers, strategy runner adapter, degradation calculation,
WalkForwardResult model, edge cases, and performance.
"""

from __future__ import annotations

import pytest

from flinttrade_backtest.walk_forward import (
    WalkForwardConfig,
    WalkForwardResult,
    WalkForwardAnalyser,
    _bars_to_returns,
    _compute_metric,
    _degradation,
    _equity_to_returns,
    _generate_splits,
    _run_strategy_on_bars,
    _safe_mean,
    _safe_std,
    _sharpe_from_returns,
    _sortino_from_returns,
    _total_return_from_returns,
    _calmar_from_returns,
    _win_rate_from_returns,
    _profit_factor_from_returns,
)


# ---------------------------------------------------------------------------
# Fixtures / helpers
# ---------------------------------------------------------------------------


def _make_bars(n: int, seed: int = 0) -> list[dict]:
    """Generate deterministic close-only bar dicts."""
    import random
    rng = random.Random(seed)
    price = 18000.0
    bars = []
    for _ in range(n):
        price *= 1.0 + rng.gauss(0.0005, 0.01)
        bars.append({"close": round(price, 2)})
    return bars


class _DailyReturnStrategy:
    """Simple strategy that records bar-to-bar returns for testing."""

    def __init__(self, **kwargs) -> None:
        self.daily_returns: list[float] = []
        self._prev: float | None = None

    def on_bar(self, bar: dict) -> None:
        c = float(bar["close"])
        if self._prev is not None and self._prev > 0:
            self.daily_returns.append((c - self._prev) / self._prev)
        self._prev = c


class _BrokenStrategy:
    """Strategy that raises on first call (tests error handling)."""

    def __init__(self, **kwargs) -> None:
        pass

    def on_bar(self, bar: dict) -> None:
        raise RuntimeError("strategy failure")


# ---------------------------------------------------------------------------
# WalkForwardConfig validation
# ---------------------------------------------------------------------------


def test_config_defaults() -> None:
    cfg = WalkForwardConfig()
    assert cfg.n_splits == 5
    assert cfg.train_ratio == 0.7
    assert cfg.anchored is False


def test_config_n_splits_lower_bound() -> None:
    with pytest.raises(Exception):
        WalkForwardConfig(n_splits=1)  # < 2 is invalid


def test_config_train_ratio_lower_bound() -> None:
    with pytest.raises(Exception):
        WalkForwardConfig(train_ratio=0.4)


def test_config_train_ratio_upper_bound() -> None:
    with pytest.raises(Exception):
        WalkForwardConfig(train_ratio=0.95)


def test_config_anchored_true() -> None:
    cfg = WalkForwardConfig(anchored=True)
    assert cfg.anchored is True


# ---------------------------------------------------------------------------
# _safe_mean / _safe_std
# ---------------------------------------------------------------------------


def test_safe_mean_empty() -> None:
    assert _safe_mean([]) == 0.0


def test_safe_mean_values() -> None:
    assert _safe_mean([1.0, 2.0, 3.0]) == pytest.approx(2.0)


def test_safe_std_short() -> None:
    assert _safe_std([]) == 0.0
    assert _safe_std([1.0]) == 0.0


def test_safe_std_known_values() -> None:
    # _safe_std uses sample std (n-1 denominator).
    # For vals = [2,4,4,4,5,5,7,9], population std ≈ 2.0; sample std ≈ 2.138.
    vals = [2.0, 4.0, 4.0, 4.0, 5.0, 5.0, 7.0, 9.0]
    std = _safe_std(vals)
    assert std > 1.9  # sample std is always >= population std


# ---------------------------------------------------------------------------
# Metric helpers
# ---------------------------------------------------------------------------


def test_sharpe_positive() -> None:
    # Needs varied returns — identical values give std=0, so Sharpe=0
    import random
    rng = random.Random(0)
    returns = [rng.uniform(0.001, 0.015) for _ in range(30)]
    assert _sharpe_from_returns(returns) > 0


def test_sharpe_short() -> None:
    assert _sharpe_from_returns([0.01]) == 0.0
    assert _sharpe_from_returns([]) == 0.0


def test_sortino_all_positive() -> None:
    returns = [0.005] * 30
    assert _sortino_from_returns(returns) >= 0.0


def test_total_return_flat() -> None:
    assert _total_return_from_returns([0.0] * 10) == pytest.approx(0.0)


def test_total_return_positive() -> None:
    tr = _total_return_from_returns([0.01] * 10)
    assert tr > 0


def test_calmar_zero_drawdown() -> None:
    # Zero drawdown → Calmar = 0 (no drawdown to divide by)
    returns = [0.001] * 50  # monotonically increasing equity
    assert _calmar_from_returns(returns) == 0.0


def test_calmar_with_drawdown() -> None:
    returns = [0.01, -0.02, 0.01, -0.01, 0.02] * 10
    c = _calmar_from_returns(returns)
    assert isinstance(c, float)


def test_win_rate_all_wins() -> None:
    assert _win_rate_from_returns([0.01] * 10) == pytest.approx(100.0)


def test_win_rate_all_losses() -> None:
    assert _win_rate_from_returns([-0.01] * 10) == pytest.approx(0.0)


def test_win_rate_empty() -> None:
    assert _win_rate_from_returns([]) == pytest.approx(0.0)


def test_profit_factor_mixed() -> None:
    returns = [0.1, -0.05, 0.2, -0.1]
    pf = _profit_factor_from_returns(returns)
    assert pf > 0


def test_compute_metric_unsupported_raises() -> None:
    with pytest.raises(ValueError, match="Unsupported"):
        _compute_metric([0.01] * 10, "magic_metric")


def test_compute_metric_supported_names() -> None:
    returns = [0.01, -0.005, 0.008, 0.003, -0.002] * 10
    for metric in ("sharpe_ratio", "sortino_ratio", "total_return",
                   "calmar_ratio", "win_rate", "profit_factor"):
        val = _compute_metric(returns, metric)
        assert isinstance(val, float), f"metric={metric} returned non-float"


# ---------------------------------------------------------------------------
# _equity_to_returns / _bars_to_returns
# ---------------------------------------------------------------------------


def test_equity_to_returns_length() -> None:
    equity = [100.0, 101.0, 100.5, 103.0]
    returns = _equity_to_returns(equity)
    assert len(returns) == 3


def test_equity_to_returns_known() -> None:
    equity = [100.0, 110.0, 99.0]
    returns = _equity_to_returns(equity)
    assert returns[0] == pytest.approx(0.1)
    assert returns[1] == pytest.approx((99.0 - 110.0) / 110.0)


def test_bars_to_returns_close_key() -> None:
    bars = [{"close": 100.0}, {"close": 102.0}, {"close": 101.0}]
    returns = _bars_to_returns(bars)
    assert len(returns) == 2
    assert returns[0] == pytest.approx(0.02)


def test_bars_to_returns_missing_close() -> None:
    bars = [{"open": 100.0}, {"open": 105.0}]
    returns = _bars_to_returns(bars)
    assert returns == []


def test_bars_to_returns_empty() -> None:
    assert _bars_to_returns([]) == []


# ---------------------------------------------------------------------------
# _degradation
# ---------------------------------------------------------------------------


def test_degradation_positive() -> None:
    """In-sample > out-of-sample → positive degradation."""
    assert _degradation(1.0, 0.7) == pytest.approx(30.0)


def test_degradation_improvement() -> None:
    """Out-of-sample better → negative degradation."""
    assert _degradation(1.0, 1.3) == pytest.approx(-30.0)


def test_degradation_zero_train() -> None:
    assert _degradation(0.0, 0.5) == pytest.approx(0.0)


def test_degradation_identical() -> None:
    assert _degradation(1.0, 1.0) == pytest.approx(0.0)


# ---------------------------------------------------------------------------
# _generate_splits — rolling window
# ---------------------------------------------------------------------------


def test_generate_splits_rolling_count() -> None:
    cfg = WalkForwardConfig(n_splits=5, train_ratio=0.7, anchored=False)
    splits = _generate_splits(500, cfg)
    assert len(splits) == 5


def test_generate_splits_rolling_no_overlap() -> None:
    """Test windows should not overlap each other."""
    cfg = WalkForwardConfig(n_splits=4, train_ratio=0.7, anchored=False)
    splits = _generate_splits(400, cfg)
    for i in range(len(splits) - 1):
        _, _, _, test_end_i = splits[i]
        _, _, test_start_j, _ = splits[i + 1]
        assert test_start_j > test_end_i


def test_generate_splits_train_before_test() -> None:
    cfg = WalkForwardConfig(n_splits=3, train_ratio=0.7, anchored=False)
    splits = _generate_splits(300, cfg)
    for train_start, train_end, test_start, test_end in splits:
        assert train_end >= train_start
        assert test_end >= test_start
        assert test_start > train_end


def test_generate_splits_too_few_bars_raises() -> None:
    cfg = WalkForwardConfig(n_splits=5)
    with pytest.raises(ValueError, match="at least"):
        _generate_splits(5, cfg)


# ---------------------------------------------------------------------------
# _generate_splits — anchored (expanding) window
# ---------------------------------------------------------------------------


def test_generate_splits_anchored_train_starts_at_zero() -> None:
    cfg = WalkForwardConfig(n_splits=4, train_ratio=0.7, anchored=True)
    splits = _generate_splits(400, cfg)
    for train_start, _, _, _ in splits:
        assert train_start == 0


def test_generate_splits_anchored_train_grows() -> None:
    cfg = WalkForwardConfig(n_splits=4, train_ratio=0.7, anchored=True)
    splits = _generate_splits(400, cfg)
    train_ends = [s[1] for s in splits]
    for i in range(len(train_ends) - 1):
        assert train_ends[i + 1] > train_ends[i]


# ---------------------------------------------------------------------------
# _run_strategy_on_bars
# ---------------------------------------------------------------------------


def test_run_strategy_returns_daily_returns_list() -> None:
    bars = _make_bars(30)
    returns = _run_strategy_on_bars(_DailyReturnStrategy, {}, bars)
    assert isinstance(returns, list)
    assert len(returns) == len(bars) - 1


def test_run_strategy_broken_falls_back_to_close_returns() -> None:
    bars = _make_bars(20)
    # _BrokenStrategy raises → falls back to bar-to-bar close returns
    returns = _run_strategy_on_bars(_BrokenStrategy, {}, bars)
    assert isinstance(returns, list)
    assert len(returns) == len(bars) - 1


def test_run_strategy_empty_bars() -> None:
    returns = _run_strategy_on_bars(_DailyReturnStrategy, {}, [])
    assert returns == []


# ---------------------------------------------------------------------------
# WalkForwardAnalyser.analyse — integration
# ---------------------------------------------------------------------------


def test_analyse_returns_walk_forward_result() -> None:
    bars = _make_bars(300, seed=42)
    cfg = WalkForwardConfig(n_splits=3, train_ratio=0.7)
    analyser = WalkForwardAnalyser(cfg)
    result = analyser.analyse(bars, _DailyReturnStrategy, {})
    assert isinstance(result, WalkForwardResult)


def test_analyse_correct_split_count() -> None:
    bars = _make_bars(400, seed=1)
    cfg = WalkForwardConfig(n_splits=4, train_ratio=0.7)
    result = WalkForwardAnalyser(cfg).analyse(bars, _DailyReturnStrategy, {})
    assert result.n_splits_run == 4


def test_analyse_split_details_length() -> None:
    bars = _make_bars(350, seed=2)
    cfg = WalkForwardConfig(n_splits=3)
    result = WalkForwardAnalyser(cfg).analyse(bars, _DailyReturnStrategy, {})
    assert len(result.splits) == result.n_splits_run


def test_analyse_degradation_is_float() -> None:
    bars = _make_bars(300, seed=3)
    cfg = WalkForwardConfig(n_splits=3)
    result = WalkForwardAnalyser(cfg).analyse(bars, _DailyReturnStrategy, {})
    assert isinstance(result.degradation_pct, float)


def test_analyse_is_robust_is_bool() -> None:
    bars = _make_bars(300, seed=4)
    cfg = WalkForwardConfig(n_splits=3)
    result = WalkForwardAnalyser(cfg).analyse(bars, _DailyReturnStrategy, {})
    assert isinstance(result.is_robust, bool)


def test_analyse_is_robust_threshold() -> None:
    """Robust ↔ |degradation_pct| < 30."""
    bars = _make_bars(300, seed=5)
    cfg = WalkForwardConfig(n_splits=3)
    result = WalkForwardAnalyser(cfg).analyse(bars, _DailyReturnStrategy, {})
    if abs(result.degradation_pct) < 30.0:
        assert result.is_robust is True
    else:
        assert result.is_robust is False


def test_analyse_split_indices_sequential() -> None:
    bars = _make_bars(400, seed=6)
    cfg = WalkForwardConfig(n_splits=4)
    result = WalkForwardAnalyser(cfg).analyse(bars, _DailyReturnStrategy, {})
    for i, split in enumerate(result.splits):
        assert split.split_index == i


def test_analyse_split_bar_counts_positive() -> None:
    bars = _make_bars(350, seed=7)
    cfg = WalkForwardConfig(n_splits=3)
    result = WalkForwardAnalyser(cfg).analyse(bars, _DailyReturnStrategy, {})
    for split in result.splits:
        assert split.n_train_bars > 0
        assert split.n_test_bars > 0


def test_analyse_train_before_test_in_splits() -> None:
    bars = _make_bars(300, seed=8)
    cfg = WalkForwardConfig(n_splits=3)
    result = WalkForwardAnalyser(cfg).analyse(bars, _DailyReturnStrategy, {})
    for split in result.splits:
        assert split.train_end < split.test_start


def test_analyse_anchored_window() -> None:
    bars = _make_bars(400, seed=9)
    cfg = WalkForwardConfig(n_splits=4, anchored=True)
    result = WalkForwardAnalyser(cfg).analyse(bars, _DailyReturnStrategy, {})
    for split in result.splits:
        assert split.train_start == 0


def test_analyse_unsupported_metric_raises() -> None:
    bars = _make_bars(200, seed=10)
    cfg = WalkForwardConfig(n_splits=2)
    analyser = WalkForwardAnalyser(cfg)
    with pytest.raises(ValueError, match="Unsupported"):
        analyser.analyse(bars, _DailyReturnStrategy, {}, metric="bad_metric")


def test_analyse_too_few_bars_raises() -> None:
    bars = _make_bars(5, seed=11)
    cfg = WalkForwardConfig(n_splits=5)
    analyser = WalkForwardAnalyser(cfg)
    with pytest.raises(ValueError, match="at least"):
        analyser.analyse(bars, _DailyReturnStrategy, {})


def test_analyse_multiple_metrics() -> None:
    bars = _make_bars(300, seed=12)
    cfg = WalkForwardConfig(n_splits=3)
    for metric in ("sharpe_ratio", "sortino_ratio", "total_return",
                   "win_rate", "profit_factor"):
        result = WalkForwardAnalyser(cfg).analyse(
            bars, _DailyReturnStrategy, {}, metric=metric
        )
        assert result.n_splits_run > 0, f"No splits for metric={metric}"


# ---------------------------------------------------------------------------
# WalkForwardResult.as_dict
# ---------------------------------------------------------------------------


def test_as_dict_keys() -> None:
    bars = _make_bars(300, seed=13)
    cfg = WalkForwardConfig(n_splits=3)
    result = WalkForwardAnalyser(cfg).analyse(bars, _DailyReturnStrategy, {})
    d = result.as_dict()
    expected_keys = {
        "splits", "avg_train_metric", "avg_test_metric",
        "degradation_pct", "is_robust", "n_splits_run", "wfe_ratio",
    }
    assert expected_keys == set(d.keys())


def test_as_dict_splits_is_list() -> None:
    bars = _make_bars(300, seed=14)
    result = WalkForwardAnalyser().analyse(bars, _DailyReturnStrategy, {})
    assert isinstance(result.as_dict()["splits"], list)


def test_as_dict_split_keys() -> None:
    bars = _make_bars(300, seed=15)
    result = WalkForwardAnalyser().analyse(bars, _DailyReturnStrategy, {})
    split_d = result.as_dict()["splits"][0]
    expected = {
        "split_index", "train_start", "train_end",
        "test_start", "test_end", "n_train_bars", "n_test_bars",
        "train_metric", "test_metric", "degradation_pct", "wfe",
    }
    assert expected == set(split_d.keys())


# ---------------------------------------------------------------------------
# Performance guard
# ---------------------------------------------------------------------------


def test_analyse_performance() -> None:
    """5-split walk-forward on 500 bars should complete in reasonable time."""
    import time
    bars = _make_bars(500, seed=99)
    cfg = WalkForwardConfig(n_splits=5)
    start = time.monotonic()
    WalkForwardAnalyser(cfg).analyse(bars, _DailyReturnStrategy, {})
    elapsed = time.monotonic() - start
    assert elapsed < 10.0, f"Took {elapsed:.1f}s — too slow"


class TestWalkForwardEfficiency:
    """WFE folded in from walk_forward_analysis (U13)."""

    def test_wfe_helper_maths(self) -> None:
        from flinttrade_backtest.walk_forward import _wfe

        assert _wfe(2.0, 1.0) == 0.5
        assert _wfe(1.0, 1.0) == 1.0
        assert _wfe(0.0, 1.0) == 0.0  # zero in-sample → 0, never a div/0
        assert _wfe(-2.0, -1.0) == 0.5

    def test_result_carries_wfe_ratio_and_per_split_wfe(self) -> None:
        from flinttrade_backtest.walk_forward import SplitDetail, WalkForwardResult

        split = SplitDetail(
            split_index=0, train_start=0, train_end=99, test_start=100,
            test_end=129, n_train_bars=100, n_test_bars=30,
            train_metric=2.0, test_metric=1.0, degradation_pct=50.0, wfe=0.5,
        )
        result = WalkForwardResult(
            splits=[split], avg_train_metric=2.0, avg_test_metric=1.0,
            degradation_pct=50.0, is_robust=False, n_splits_run=1, wfe_ratio=0.5,
        )
        payload = result.as_dict()
        assert payload["wfe_ratio"] == 0.5
        assert payload["splits"][0]["wfe"] == 0.5
