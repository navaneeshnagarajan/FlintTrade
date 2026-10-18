"""Public evaluator identity and failure controls; synthetic observations only."""
import pytest
from flask import Flask

from flinttrade_backtest.permutation_routes import permutation_bp
from flinttrade_backtest.walk_forward import WalkForwardAnalyser, WalkForwardConfig
from flinttrade_backtest.strategies import STRATEGY_REGISTRY
from flinttrade_backtest.base_strategy import BaseBacktestStrategy

pytestmark = pytest.mark.unit


class FlatCandidate(BaseBacktestStrategy):
    def on_bar(self, bar):
        pass


class BrokenCandidate(FlatCandidate):
    def on_bar(self, bar):
        raise RuntimeError("candidate failed")


def bars():
    return [{"timestamp": f"2025-01-{i + 1:02}", "open": 100 + i,
             "close": 100 + i, "high": 101 + i, "low": 99 + i, "volume": 1000}
            for i in range(28)]


def test_mounted_walkforward_runs_selected_candidate(monkeypatch):
    monkeypatch.setitem(STRATEGY_REGISTRY, "FlatCandidate", FlatCandidate)
    app = Flask(__name__)
    app.register_blueprint(permutation_bp)
    response = app.test_client().post("/v1/backtest/walkforward", json={
        "strategy": "FlatCandidate", "symbol": "TEST", "bars": bars(),
        "metric": "total_return", "config": {"n_splits": 2},
    })
    assert response.status_code == 200
    data = response.json["data"]
    assert data["avg_test_metric"] == 0
    assert data["candidate"] == "FlatCandidate"
    assert data["status"] == "completed"
    assert data["n_splits_run"] == 2
    assert data["qualification"] == "unqualified"


def test_failed_candidate_retains_failed_splits_without_baseline_substitution():
    result = WalkForwardAnalyser(WalkForwardConfig(n_splits=2)).analyse(
        bars(), BrokenCandidate, {"symbol": "TEST"}, metric="total_return")
    assert result.n_splits_run == 0
    assert result.status == "failed"
    assert result.avg_test_metric is None
    assert result.failures and all("candidate failed" in f["reason"] for f in result.failures)
    assert not result.is_robust


def test_missing_candidate_is_refused_at_http_seam():
    app = Flask(__name__)
    app.register_blueprint(permutation_bp)
    response = app.test_client().post("/v1/backtest/walkforward", json={"bars": bars()})
    assert response.status_code == 400


def test_exported_result_types_keep_both_capabilities():
    import flinttrade_backtest as package
    from flinttrade_backtest.optimizer import WalkForwardResult as OptimizerResult
    from flinttrade_backtest.walk_forward import WalkForwardResult as AnalysisResult
    assert package.OptimizerWalkForwardResult is OptimizerResult
    assert package.WalkForwardResult is AnalysisResult
    assert package.WFResult is AnalysisResult
