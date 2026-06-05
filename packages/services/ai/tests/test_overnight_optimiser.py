"""Tests for the overnight strategy-optimisation pass."""

from __future__ import annotations

from datetime import datetime, timezone

import pytest

from flinttrade_ai.overnight_optimiser import OvernightOptimiser

pytestmark = pytest.mark.unit


class _Suggestion:
    def __init__(self, name: str, params: dict):
        self._name = name
        self._params = params

    def to_dict(self) -> dict:
        return {"strategy_name": self._name, "suggested_params": self._params, "confidence": 0.7}


class _MockRefiner:
    """Stand-in for StrategyRefiner.refine()."""

    def __init__(self, fail_on: str | None = None):
        self.calls: list[tuple] = []
        self._fail_on = fail_on

    def refine(self, name, backtest_results, params):
        self.calls.append((name, backtest_results, params))
        if name == self._fail_on:
            raise ValueError("boom")
        return _Suggestion(name, {**params, "lookback": 21})


_FIXED_CLOCK = lambda: datetime(2026, 6, 6, 2, 0, tzinfo=timezone.utc)  # noqa: E731


def test_run_refines_every_strategy():
    refiner = _MockRefiner()
    strategies = [
        {"name": "ema_cross", "params": {"lookback": 14}, "backtest_results": {"sharpe": 1.2}},
        {"name": "rsi_mr", "params": {"period": 7}},
    ]
    opt = OvernightOptimiser(lambda: strategies, refiner, clock=_FIXED_CLOCK)
    report = opt.run()
    assert report["strategies_seen"] == 2 and report["strategies_optimised"] == 2
    assert report["timestamp"] == "2026-06-06T02:00:00+00:00"
    assert {s["strategy_name"] for s in report["suggestions"]} == {"ema_cross", "rsi_mr"}
    # the refiner received the per-strategy params + backtest results
    assert refiner.calls[0] == ("ema_cross", {"sharpe": 1.2}, {"lookback": 14})


def test_run_isolates_a_failing_strategy():
    # One bad strategy must not sink the whole nightly pass.
    refiner = _MockRefiner(fail_on="rsi_mr")
    strategies = [{"name": "ema_cross", "params": {}}, {"name": "rsi_mr", "params": {}}]
    report = OvernightOptimiser(lambda: strategies, refiner).run()
    assert report["strategies_optimised"] == 1
    assert report["errors"] == [{"strategy": "rsi_mr", "error": "boom"}]


def test_run_persists_via_sink():
    saved: list[dict] = []
    opt = OvernightOptimiser(
        lambda: [{"name": "ema_cross", "params": {}}],
        _MockRefiner(),
        report_sink=saved.append,
        clock=_FIXED_CLOCK,
    )
    report = opt.run()
    assert saved == [report]


def test_run_tolerates_empty_and_broken_provider():
    assert OvernightOptimiser(lambda: [], _MockRefiner()).run()["strategies_optimised"] == 0

    def _broken():
        raise RuntimeError("no runner")

    report = OvernightOptimiser(_broken, _MockRefiner()).run()
    assert report["strategies_seen"] == 0 and report["suggestions"] == []


def test_sink_failure_never_fails_the_pass():
    def _bad_sink(_report):
        raise OSError("disk full")

    report = OvernightOptimiser(
        lambda: [{"name": "ema_cross", "params": {}}], _MockRefiner(), report_sink=_bad_sink
    ).run()
    assert report["strategies_optimised"] == 1  # pass still completed


def test_run_with_the_real_refiner_yields_populated_suggestions():
    """The report must carry real content, not just counts.

    Uses the actual rule-based StrategyRefiner (no LLM) so the assertions cover
    the genuine "optimise overnight -> reports + improvement suggestions" output:
    each suggestion has a narrative analysis, concrete suggested params, a
    reasoning string and a valid confidence.
    """
    from flinttrade_ai.strategy_refiner import StrategyRefiner

    strategies = [
        {
            "name": "ema_crossover",
            "params": {"fast_period": 9, "slow_period": 21},
            "backtest_results": {
                "sharpe_ratio": 0.4, "max_drawdown": -0.25, "win_rate": 0.38,
                "total_trades": 40, "total_return": 0.05, "profit_factor": 1.1,
            },
        },
        {
            "name": "rsi_mean_reversion",
            "params": {"period": 14},
            "backtest_results": {
                "sharpe_ratio": 1.6, "max_drawdown": -0.08, "win_rate": 0.55,
                "total_trades": 80, "total_return": 0.22, "profit_factor": 1.9,
            },
        },
    ]
    optimiser = OvernightOptimiser(lambda: strategies, StrategyRefiner(), clock=_FIXED_CLOCK)

    report = optimiser.run()

    assert report["strategies_seen"] == 2
    assert report["strategies_optimised"] == 2
    assert report["errors"] == []
    assert report["timestamp"] == "2026-06-06T02:00:00+00:00"
    assert {s["strategy_name"] for s in report["suggestions"]} == {"ema_crossover", "rsi_mean_reversion"}
    for sugg in report["suggestions"]:
        assert isinstance(sugg["analysis"], str) and sugg["analysis"].strip()
        assert isinstance(sugg["suggested_params"], dict) and sugg["suggested_params"]
        assert isinstance(sugg["reasoning"], str) and sugg["reasoning"].strip()
        assert 0.0 <= sugg["confidence"] <= 1.0
        assert sugg["timestamp"]
