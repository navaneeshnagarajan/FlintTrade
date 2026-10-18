"""Failure admission through the public optimiser with real synthetic simulations."""

from __future__ import annotations

import pytest

from flinttrade_backtest.metrics import PerformanceMetrics
from flinttrade_backtest.optimizer import ParamGrid, WalkForwardOptimizer
from flinttrade_backtest.simulator import BacktestConfig, BacktestResult
from flinttrade_core.models import OHLCV, Order, Quote
from flinttrade_engine.strategy import BaseStrategy

pytestmark = pytest.mark.unit


def bars() -> list[dict]:
    """Two four-bar periods, each with a loss for a one-unit long position."""
    return [
        {"timestamp": f"2025-01-{day:02d}", "open": price, "high": price, "low": price,
         "close": price, "volume": 1000}
        for day, price in enumerate((100, 90, 80, 70, 100, 90, 80, 70), start=1)
    ]


def config() -> BacktestConfig:
    return BacktestConfig(symbol="TEST", initial_capital=1000, slippage_pct=0, commission_per_order=0)


def grid(*modes: str) -> ParamGrid:
    result = ParamGrid()
    result.add("mode", list(modes))
    return result


class TrialStrategy(BaseStrategy):
    """Public strategy hooks supply deterministic orders or a real lifecycle fault."""

    def __init__(self, mode: str) -> None:
        super().__init__(name=mode)
        self.mode = mode
        self.seen: list[str] = []

    def start(self) -> None:
        super().start()
        if self.mode == "start_failure":
            raise RuntimeError("startup failed")

    def on_tick(self, quote: Quote) -> None:
        pass

    def on_signal(self, signal: dict) -> None:
        pass

    def on_bar(self, bar: OHLCV) -> None:
        self.seen.append(bar.timestamp)
        if self.mode == "bar_failure" and len(self.seen) == 2:
            raise RuntimeError("bar failed")

    def generate_orders(self) -> list[Order]:
        if self.mode == "loss" and len(self.seen) == 1:
            return [Order(symbol="TEST", action="BUY", quantity="1")]
        return []

    def stop(self) -> None:
        super().stop()
        if self.mode == "stop_failure":
            raise RuntimeError("cleanup failed")


@pytest.mark.parametrize("rank_by", ["return", "sharpe"])
@pytest.mark.parametrize(("mode", "reason"), [
    ("start_failure", "startup failed"),
    ("bar_failure", "bar failed"),
    ("stop_failure", "cleanup failed"),
])
def test_failed_simulation_cannot_outrank_completed_loss(monkeypatch, rank_by, mode, reason):
    scored: list[BacktestResult] = []
    compute = PerformanceMetrics.compute

    def observe_metrics(result):
        scored.append(result)
        return compute(result)

    monkeypatch.setattr(PerformanceMetrics, "compute", staticmethod(observe_metrics))
    result = WalkForwardOptimizer().optimize(
        lambda params: TrialStrategy(**params), bars(), config(), grid(mode, "loss"),
        in_sample_pct=0.5, rank_by=rank_by,
    )

    assert result.best_params == {"mode": "loss"}
    assert [entry.params for entry in result.in_sample_results] == [{"mode": "loss"}]
    assert result.in_sample_results[0].total_return_pct == -3.0
    assert result.in_sample_results[0].sharpe < 0
    assert result.in_sample_results[0].total_trades == 1
    assert result.error == ""
    assert result.out_sample_report is not None
    assert result.out_sample_report.total_return_pct == -3.0
    assert len(result.failed_trials) == 1
    failure = result.failed_trials[0]
    assert failure.params == {"mode": mode}
    assert failure.stage == "in_sample"
    assert reason in failure.error
    assert len(scored) == 2  # Completed training and held-out simulations only.
    assert all(run.error == "" and run.total_bars == 4 for run in scored)


@pytest.mark.parametrize("rank_by", ["return", "sharpe"])
@pytest.mark.parametrize("fault", ["factory", "metrics"])
def test_raised_candidate_failure_is_evidence_not_a_zero_score(monkeypatch, rank_by, fault):
    compute = PerformanceMetrics.compute

    def factory(params):
        if fault == "factory" and params["mode"] == "no_orders":
            raise RuntimeError("factory failed")
        return TrialStrategy(**params)

    def fail_metrics(result):
        if not result.trades:
            raise RuntimeError("metrics failed")
        return compute(result)

    if fault == "metrics":
        monkeypatch.setattr(PerformanceMetrics, "compute", staticmethod(fail_metrics))
    result = WalkForwardOptimizer().optimize(
        factory, bars(), config(), grid("no_orders", "loss"), in_sample_pct=0.5, rank_by=rank_by,
    )

    assert result.best_params == {"mode": "loss"}
    assert [entry.params for entry in result.in_sample_results] == [{"mode": "loss"}]
    assert result.in_sample_results[0].total_return_pct == -3.0
    assert result.in_sample_results[0].sharpe < 0
    assert result.error == ""
    assert result.out_sample_report is not None
    assert result.out_sample_report.total_return_pct == -3.0
    assert len(result.failed_trials) == 1
    failure = result.failed_trials[0]
    assert failure.params == {"mode": "no_orders"}
    assert failure.stage == "in_sample"
    assert f"{fault} failed" in failure.error


@pytest.mark.parametrize("modes", [("start_failure", "bar_failure"), ()])
def test_no_eligible_candidates_returns_explicit_failure_without_validation(modes):
    created: list[str] = []

    def factory(params):
        created.append(params["mode"])
        return TrialStrategy(**params)

    result = WalkForwardOptimizer().optimize(factory, bars(), config(), grid(*modes), in_sample_pct=0.5)

    assert result.error == "No eligible in-sample candidates"
    assert result.best_params == {}
    assert result.in_sample_results == []
    assert result.out_sample_report is None
    assert result.robustness_score is None
    assert created == list(modes)  # No held-out strategy was constructed.
    assert [failure.params for failure in result.failed_trials] == [{"mode": mode} for mode in modes]
    assert all(failure.stage == "in_sample" and failure.error for failure in result.failed_trials)


@pytest.mark.parametrize("fault", ["bar", "stop"])
def test_failed_held_out_simulation_has_no_qualified_report_or_best_params(monkeypatch, fault):
    class HeldOutFailure(TrialStrategy):
        def on_bar(self, bar):
            super().on_bar(bar)
            if fault == "bar" and bar.timestamp == "2025-01-06":
                raise RuntimeError("held-out bar failed")

        def stop(self):
            super().stop()
            if fault == "stop" and self.seen and self.seen[0] == "2025-01-05":
                raise RuntimeError("held-out stop failed")

    scored: list[BacktestResult] = []
    compute = PerformanceMetrics.compute

    def observe_metrics(result):
        scored.append(result)
        return compute(result)

    monkeypatch.setattr(PerformanceMetrics, "compute", staticmethod(observe_metrics))
    result = WalkForwardOptimizer().optimize(
        lambda params: HeldOutFailure(**params), bars(), config(), grid("start_failure", "loss"), in_sample_pct=0.5,
    )

    assert result.out_sample_report is None
    assert result.best_params == {}
    assert result.robustness_score is None
    assert f"held-out {fault} failed" in result.error
    assert [entry.params for entry in result.in_sample_results] == [{"mode": "loss"}]
    assert result.in_sample_results[0].total_return_pct == -3.0
    assert len(result.failed_trials) == 2
    assert result.failed_trials[0].params == {"mode": "start_failure"}
    assert result.failed_trials[0].stage == "in_sample"
    assert "startup failed" in result.failed_trials[0].error
    failure = result.failed_trials[1]
    assert failure.params == {"mode": "loss"}
    assert failure.stage == "out_sample"
    assert f"held-out {fault} failed" in failure.error
    assert len(scored) == 1
    assert scored[0].error == ""
    assert scored[0].total_bars == 4


@pytest.mark.parametrize("fault", ["factory", "metrics"])
def test_raised_held_out_failure_does_not_promote_training_winner(monkeypatch, fault):
    created: list[dict] = []
    compute = PerformanceMetrics.compute

    def factory(params):
        created.append(dict(params))
        if fault == "factory" and len(created) == 2:
            raise RuntimeError("held-out factory failed")
        return TrialStrategy(**params)

    def fail_metrics(result):
        if result.equity_curve[0].timestamp == "2025-01-05":
            raise RuntimeError("held-out metrics failed")
        return compute(result)

    if fault == "metrics":
        monkeypatch.setattr(PerformanceMetrics, "compute", staticmethod(fail_metrics))
    result = WalkForwardOptimizer().optimize(factory, bars(), config(), grid("loss"), in_sample_pct=0.5)

    assert f"held-out {fault} failed" in result.error
    assert result.best_params == {}
    assert result.out_sample_report is None
    assert result.robustness_score is None
    assert [entry.params for entry in result.in_sample_results] == [{"mode": "loss"}]
    assert result.in_sample_results[0].total_return_pct == -3.0
    assert created == [{"mode": "loss"}, {"mode": "loss"}]
    assert len(result.failed_trials) == 1
    failure = result.failed_trials[0]
    assert failure.params == {"mode": "loss"}
    assert failure.stage == "out_sample"
    assert f"held-out {fault} failed" in failure.error


@pytest.mark.parametrize("parameterised", [False, True])
def test_completed_no_order_zero_result_is_validated_even_without_parameters(parameterised):
    created: list[TrialStrategy] = []

    def factory(params):
        strategy = TrialStrategy(params.get("mode", "no_orders"))
        created.append(strategy)
        return strategy

    parameters = grid("no_orders") if parameterised else ParamGrid()
    result = WalkForwardOptimizer().optimize(factory, bars(), config(), parameters, in_sample_pct=0.5)

    assert result.out_sample_report is not None
    assert result.error == ""
    assert result.best_params == ({"mode": "no_orders"} if parameterised else {})
    assert result.failed_trials == []
    assert len(result.in_sample_results) == 1
    assert result.in_sample_results[0].total_return_pct == 0.0
    assert result.in_sample_results[0].sharpe == 0.0
    assert result.in_sample_results[0].total_trades == 0
    assert result.out_sample_report.total_return_pct == 0.0
    assert result.out_sample_report.sharpe_ratio == 0.0
    assert result.out_sample_report.trade_stats.total_trades == 0
    assert result.robustness_score == 0.0
    assert [strategy.seen for strategy in created] == [
        ["2025-01-01", "2025-01-02", "2025-01-03", "2025-01-04"],
        ["2025-01-05", "2025-01-06", "2025-01-07", "2025-01-08"],
    ]


def test_missing_held_out_bars_cannot_promote_training_only_result():
    result = WalkForwardOptimizer().optimize(
        lambda params: TrialStrategy(**params), bars(), config(), grid("loss"), in_sample_pct=1.0,
    )

    assert "No bars provided" in result.error
    assert result.best_params == {}
    assert result.out_sample_report is None
    assert result.robustness_score is None
    assert len(result.in_sample_results) == 1
    assert len(result.failed_trials) == 1
    assert result.failed_trials[0].params == {"mode": "loss"}
    assert result.failed_trials[0].stage == "out_sample"
    assert result.failed_trials[0].error == "No bars provided"


def test_missing_walk_forward_window_returns_explicit_non_success():
    created: list[dict] = []

    def factory(params):
        created.append(params)
        return TrialStrategy(**params)

    result = WalkForwardOptimizer().optimize(factory, bars(), config(), grid("loss"), num_windows=3)

    assert result.error == "No walk-forward windows available"
    assert result.best_params == {}
    assert result.in_sample_results == []
    assert result.out_sample_report is None
    assert result.robustness_score is None
    assert result.failed_trials == []  # No trials attempted, not a fabricated trial failure.
    assert created == []


@pytest.mark.parametrize("rank_by", ["return", "sharpe"])
def test_best_completed_candidate_is_selected_and_validated(rank_by):
    class LongOrShort(TrialStrategy):
        def generate_orders(self):
            if self.mode != "no_orders" and len(self.seen) == 1:
                side = "SELL" if self.mode == "profit" else "BUY"
                return [Order(symbol="TEST", action=side, quantity="1")]
            return []

    result = WalkForwardOptimizer().optimize(
        lambda params: LongOrShort(**params), bars(), config(), grid("loss", "no_orders", "profit"),
        in_sample_pct=0.5, rank_by=rank_by,
    )

    assert result.error == ""
    assert result.failed_trials == []
    assert result.best_params == {"mode": "profit"}
    assert [entry.params for entry in result.in_sample_results] == [
        {"mode": "profit"}, {"mode": "no_orders"}, {"mode": "loss"},
    ]
    assert [entry.total_return_pct for entry in result.in_sample_results] == [3.0, 0.0, -3.0]
    assert [entry.total_trades for entry in result.in_sample_results] == [1, 0, 1]
    assert result.out_sample_report is not None
    assert result.out_sample_report.total_return_pct == 3.0
    assert result.out_sample_report.trade_stats.total_trades == 1
    assert result.out_sample_report.sharpe_ratio > 0
    assert result.robustness_score == 100.0


def test_held_out_startup_failure_cannot_publish_a_best_result():
    created: list[TrialStrategy] = []

    def factory(params):
        strategy = TrialStrategy("start_failure" if created else params["mode"])
        created.append(strategy)
        return strategy

    result = WalkForwardOptimizer().optimize(factory, bars(), config(), grid("loss"), in_sample_pct=0.5)

    assert "startup failed" in result.error
    assert result.best_params == {}
    assert result.out_sample_report is None
    assert result.robustness_score is None
    assert len(result.in_sample_results) == 1
    assert len(result.failed_trials) == 1
    assert result.failed_trials[0].params == {"mode": "loss"}
    assert result.failed_trials[0].stage == "out_sample"
    assert "startup failed" in result.failed_trials[0].error
    assert created[1].seen == []


@pytest.mark.parametrize("stage", ["in_sample", "out_sample"])
def test_exception_without_message_retains_its_type_as_failure_reason(monkeypatch, stage):
    compute = PerformanceMetrics.compute

    def fail_metrics(result):
        first_bar = "2025-01-01" if stage == "in_sample" else "2025-01-05"
        if result.equity_curve[0].timestamp == first_bar:
            raise RuntimeError
        return compute(result)

    monkeypatch.setattr(PerformanceMetrics, "compute", staticmethod(fail_metrics))
    result = WalkForwardOptimizer().optimize(
        lambda params: TrialStrategy(**params), bars(), config(), grid("loss"), in_sample_pct=0.5,
    )

    assert result.error
    assert result.best_params == {}
    assert result.out_sample_report is None
    assert result.robustness_score is None
    assert len(result.failed_trials) == 1
    assert result.failed_trials[0].params == {"mode": "loss"}
    assert result.failed_trials[0].stage == stage
    assert "RuntimeError" in result.failed_trials[0].error
    assert len(result.in_sample_results) == (0 if stage == "in_sample" else 1)
