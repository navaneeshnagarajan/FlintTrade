"""Tests for packages/ai/src/strategy_refiner.py and the /api/v1/ai/refine-strategy endpoint.

All LLM calls are mocked — no live API required.
"""

from __future__ import annotations

import json
from unittest.mock import MagicMock

import pytest
from flask import Flask


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

GOOD_METRICS: dict = {
    "sharpe_ratio": 0.7,
    "max_drawdown": -0.25,
    "win_rate": 0.38,
    "total_trades": 120,
    "total_return": 0.15,
    "profit_factor": 1.3,
    "sortino_ratio": 0.9,
}

POOR_METRICS: dict = {
    "sharpe_ratio": 0.4,
    "max_drawdown": -0.35,
    "win_rate": 0.32,
    "total_trades": 50,
    "total_return": 0.04,
    "profit_factor": 1.1,
}

PARAMS: dict = {
    "fast_period": 9,
    "slow_period": 21,
    "stop_loss_pct": 0.02,
    "position_size_pct": 0.10,
    "risk_pct": 0.01,
}


@pytest.fixture()
def refiner():
    from packages.ai.src.strategy_refiner import StrategyRefiner
    return StrategyRefiner()


@pytest.fixture()
def refiner_with_llm():
    from packages.ai.src.strategy_refiner import StrategyRefiner
    llm = MagicMock()
    return StrategyRefiner(llm_client=llm), llm


@pytest.fixture()
def app():
    from packages.ai.src.ai_routes import ai_bp
    flask_app = Flask(__name__)
    flask_app.config["TESTING"] = True
    flask_app.register_blueprint(ai_bp)
    return flask_app


@pytest.fixture()
def client(app):
    return app.test_client()


# ---------------------------------------------------------------------------
# Test 1 — rule-based fallback: low Sharpe triggers stop-loss widening
# ---------------------------------------------------------------------------


class TestRuleBasedRefinement:
    """Rule-based path — no LLM configured."""

    def test_low_sharpe_widens_stop_loss(self, refiner):
        params = {"stop_loss_pct": 0.02, "position_size_pct": 0.10}
        result = refiner.refine("ema", {"sharpe_ratio": 0.5, "max_drawdown": -0.10, "win_rate": 0.50}, params)
        assert result.suggested_params["stop_loss_pct"] > params["stop_loss_pct"]

    def test_low_sharpe_reduces_position_size(self, refiner):
        params = {"stop_loss_pct": 0.02, "position_size_pct": 0.10}
        result = refiner.refine("ema", {"sharpe_ratio": 0.5, "max_drawdown": -0.10, "win_rate": 0.50}, params)
        assert result.suggested_params["position_size_pct"] < params["position_size_pct"]

    def test_high_drawdown_tightens_risk(self, refiner):
        params = {"risk_pct": 0.02, "max_loss_per_day": 5000.0}
        result = refiner.refine("scalper", {"sharpe_ratio": 1.5, "max_drawdown": -0.30, "win_rate": 0.55}, params)
        assert result.suggested_params["risk_pct"] < params["risk_pct"]
        assert result.suggested_params["max_loss_per_day"] < params["max_loss_per_day"]

    def test_low_win_rate_adjusts_periods(self, refiner):
        params = {"fast_period": 9, "slow_period": 21}
        result = refiner.refine("crossover", {"sharpe_ratio": 1.5, "max_drawdown": -0.10, "win_rate": 0.35}, params)
        # fast period should decrease OR slow period should increase
        assert (
            result.suggested_params["fast_period"] < params["fast_period"]
            or result.suggested_params["slow_period"] > params["slow_period"]
        )

    def test_healthy_metrics_no_changes(self, refiner):
        params = {"stop_loss_pct": 0.02}
        result = refiner.refine("good_strat", {"sharpe_ratio": 1.8, "max_drawdown": -0.08, "win_rate": 0.55}, params)
        assert result.confidence < 0.5  # low confidence in no-change suggestion
        assert result.suggested_params == params  # no changes applied

    def test_suggestion_logged_in_history(self, refiner):
        refiner.refine("test", GOOD_METRICS, PARAMS)
        history = refiner.get_refinement_history()
        assert len(history) == 1
        assert history[0]["strategy_name"] == "test"

    def test_multiple_refinements_all_logged(self, refiner):
        refiner.refine("s1", GOOD_METRICS, PARAMS)
        refiner.refine("s2", POOR_METRICS, PARAMS)
        assert len(refiner.get_refinement_history()) == 2


# ---------------------------------------------------------------------------
# Test 2 — LLM path: parse JSON response
# ---------------------------------------------------------------------------


class TestLLMRefinement:
    """LLM-backed path — LLM client is mocked."""

    def _make_llm_response(self, data: dict) -> MagicMock:
        resp = MagicMock()
        resp.success = True
        resp.content = json.dumps(data)
        return resp

    def test_llm_response_parsed_correctly(self, refiner_with_llm):
        refiner, llm = refiner_with_llm
        llm.chat.return_value = self._make_llm_response({
            "analysis": "Sharpe is low — widen SL.",
            "suggested_params": {"stop_loss_pct": 0.025},
            "reasoning": "Wider SL reduces noise-based exits.",
            "confidence": 0.75,
        })
        result = refiner.refine("ema", GOOD_METRICS, {"stop_loss_pct": 0.02})
        assert result.analysis == "Sharpe is low — widen SL."
        assert result.suggested_params["stop_loss_pct"] == 0.025
        assert result.confidence == 0.75

    def test_llm_markdown_fence_stripped(self, refiner_with_llm):
        refiner, llm = refiner_with_llm
        payload = {
            "analysis": "OK",
            "suggested_params": {},
            "reasoning": "none",
            "confidence": 0.5,
        }
        resp = MagicMock()
        resp.success = True
        resp.content = "```json\n" + json.dumps(payload) + "\n```"
        llm.chat.return_value = resp
        result = refiner.refine("s", GOOD_METRICS, {})
        assert result.analysis == "OK"

    def test_llm_failure_falls_back_to_rule_based(self, refiner_with_llm):
        refiner, llm = refiner_with_llm
        resp = MagicMock()
        resp.success = False
        resp.error = "timeout"
        llm.chat.return_value = resp
        # Should not raise — rule-based fallback returns a valid suggestion
        result = refiner.refine("s", GOOD_METRICS, PARAMS)
        assert result is not None
        assert isinstance(result.confidence, float)

    def test_llm_exception_falls_back_to_rule_based(self, refiner_with_llm):
        refiner, llm = refiner_with_llm
        llm.chat.side_effect = RuntimeError("connection refused")
        result = refiner.refine("s", GOOD_METRICS, PARAMS)
        assert result is not None

    def test_bad_json_returns_low_confidence(self, refiner_with_llm):
        refiner, llm = refiner_with_llm
        resp = MagicMock()
        resp.success = True
        resp.content = "This is NOT json at all"
        llm.chat.return_value = resp
        result = refiner.refine("s", GOOD_METRICS, PARAMS)
        assert result.confidence <= 0.1


# ---------------------------------------------------------------------------
# Test 3 — Flask endpoint
# ---------------------------------------------------------------------------


class TestRefineStrategyEndpoint:
    """HTTP endpoint tests."""

    def test_missing_strategy_name_returns_400(self, client):
        rv = client.post(
            "/api/v1/ai/refine-strategy",
            json={"backtest_results": GOOD_METRICS, "current_params": PARAMS},
        )
        assert rv.status_code == 400

    def test_missing_backtest_results_returns_400(self, client):
        rv = client.post(
            "/api/v1/ai/refine-strategy",
            json={"strategy_name": "ema", "current_params": PARAMS},
        )
        assert rv.status_code == 400

    def test_valid_request_returns_200(self, client, monkeypatch):
        # Patch LLMConfig.from_env to report LLM not configured so
        # the route uses rule-based fallback (no live LLM needed in tests)
        import packages.ai.src.ai_routes as ai_routes_mod
        monkeypatch.setattr(ai_routes_mod, "_is_llm_configured", lambda: False)

        rv = client.post(
            "/api/v1/ai/refine-strategy",
            json={
                "strategy_name": "ema_crossover",
                "backtest_results": GOOD_METRICS,
                "current_params": PARAMS,
            },
        )
        assert rv.status_code == 200
        data = rv.get_json()
        assert data["status"] == "success"
        assert "suggested_params" in data["data"]
        assert "confidence" in data["data"]
        assert data["data"]["strategy_name"] == "ema_crossover"
