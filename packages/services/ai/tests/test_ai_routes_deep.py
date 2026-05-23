"""Deep happy-path tests for ``/sentiment/analyse`` and ``/ai/refine-strategy``.

Both endpoints resolve their real dependency (``score_article_with_llm``
and ``StrategyRefiner``) via a lazy ``from . import ...`` inside the
view function. The surface tests in ``test_ai_routes.py`` patch at the
top-level module path and therefore accept either 200 or 500 because
the in-function import shadows the patched name.

These tests patch at the **exact lazy-import target** so the handler's
happy path runs end-to-end under deterministic mocks.
"""

from __future__ import annotations

import os
from unittest.mock import MagicMock, patch

import pytest

os.environ.setdefault("MASTER_PASSWORD", "test-master")
os.environ.setdefault("OPENALGO_API_KEY", "test")
os.environ.setdefault("FLINTTRADE_TOTP_KEY", "test-key")


@pytest.fixture
def flask_app():
    """Minimal Flask app with just ai_bp — avoids the auth middleware
    in create_flask_app that would otherwise return 401 without a JWT."""
    from flask import Flask

    from flinttrade_ai.ai_routes import ai_bp

    app = Flask(__name__)
    app.config["TESTING"] = True
    app.register_blueprint(ai_bp)
    yield app


@pytest.fixture
def client(flask_app):
    return flask_app.test_client()


# ---------------------------------------------------------------------------
# /sentiment/analyse — happy path
# ---------------------------------------------------------------------------


class TestSentimentAnalyseDeep:
    """Drive the lazy imports so the endpoint returns 200 with real mapping."""

    def _score_obj(self, sentiment: str, confidence: float, reasoning: str = "mocked"):
        obj = MagicMock()
        obj.sentiment = sentiment
        obj.confidence = confidence
        obj.reasoning = reasoning
        return obj

    @patch("flinttrade_ai.ai_routes._is_llm_configured", return_value=True)
    @patch("flinttrade_ai.sentiment.score_article_with_llm")
    @patch("flinttrade_ai.llm_client.LLMClient")
    def test_bullish_path_maps_to_positive_score(
        self,
        llm_cls,
        score_fn,
        _cfg,
        client,
    ):
        """BULLISH sentiment with 0.82 confidence yields score +0.82, label bullish."""
        llm_cls.return_value = MagicMock()
        score_fn.return_value = self._score_obj("BULLISH", 0.82)

        resp = client.post("/api/v1/sentiment/analyse", json={"text": "Nifty roared"})
        assert resp.status_code == 200
        payload = resp.get_json()["data"]
        assert payload["label"] == "bullish"
        assert payload["score"] == pytest.approx(0.82, rel=1e-3)
        assert payload["confidence"] == pytest.approx(0.82, rel=1e-3)

    @patch("flinttrade_ai.ai_routes._is_llm_configured", return_value=True)
    @patch("flinttrade_ai.sentiment.score_article_with_llm")
    @patch("flinttrade_ai.llm_client.LLMClient")
    def test_bearish_path_maps_to_negative_score(
        self,
        llm_cls,
        score_fn,
        _cfg,
        client,
    ):
        """BEARISH sentiment with 0.6 confidence yields -0.6, label bearish."""
        llm_cls.return_value = MagicMock()
        score_fn.return_value = self._score_obj("BEARISH", 0.6)
        resp = client.post("/api/v1/sentiment/analyse", json={"symbol": "NIFTY"})
        assert resp.status_code == 200
        payload = resp.get_json()["data"]
        assert payload["label"] == "bearish"
        assert payload["score"] == pytest.approx(-0.6, rel=1e-3)

    @patch("flinttrade_ai.ai_routes._is_llm_configured", return_value=True)
    @patch("flinttrade_ai.sentiment.score_article_with_llm")
    @patch("flinttrade_ai.sentiment.score_article_rule_based")
    @patch("flinttrade_ai.llm_client.LLMClient")
    def test_llm_failure_falls_back_to_rule_based(
        self,
        llm_cls,
        rule_fn,
        llm_fn,
        _cfg,
        client,
    ):
        """When the LLM scorer throws, the endpoint falls back to rule-based."""
        llm_cls.return_value = MagicMock()
        llm_fn.side_effect = RuntimeError("LLM down")
        rule_fn.return_value = self._score_obj("NEUTRAL", 0.0)
        resp = client.post("/api/v1/sentiment/analyse", json={"text": "market flat"})
        assert resp.status_code == 200
        payload = resp.get_json()["data"]
        assert payload["label"] == "neutral"
        assert payload["score"] == 0.0


# ---------------------------------------------------------------------------
# /ai/refine-strategy — happy path
# ---------------------------------------------------------------------------


class TestRefineStrategyDeep:
    """Drive the lazy imports so the refiner endpoint returns 200."""

    def _suggestion(self) -> MagicMock:
        sug = MagicMock()
        sug.to_dict.return_value = {
            "analysis": "Drawdown too high",
            "suggested_params": {"stop_loss": 0.02},
            "reasoning": "mock",
            "confidence": 0.77,
            "timestamp": "2026-04-19T10:00:00Z",
        }
        return sug

    @patch("flinttrade_ai.ai_routes._is_llm_configured", return_value=False)
    @patch("flinttrade_ai.strategy_refiner.StrategyRefiner")
    def test_refine_without_llm_uses_rule_based(
        self,
        refiner_cls,
        _cfg,
        client,
    ):
        """refine() is invoked without an LLM client when none is configured."""
        instance = MagicMock()
        instance.refine.return_value = self._suggestion()
        refiner_cls.return_value = instance
        resp = client.post(
            "/api/v1/ai/refine-strategy",
            json={
                "strategy_name": "supertrend",
                "backtest_results": {"sharpe_ratio": 0.4, "max_drawdown": -0.3},
                "current_params": {"atr_period": 14},
            },
        )
        assert resp.status_code == 200
        assert resp.get_json()["data"]["confidence"] == 0.77
        assert refiner_cls.call_args.kwargs["llm_client"] is None

    @patch("flinttrade_ai.ai_routes._is_llm_configured", return_value=True)
    @patch("flinttrade_ai.llm_client.LLMClient")
    @patch("flinttrade_ai.strategy_refiner.StrategyRefiner")
    def test_refine_with_llm_passes_client(
        self,
        refiner_cls,
        llm_cls,
        _cfg,
        client,
    ):
        """When an LLM is configured, the refiner receives a live client."""
        llm_instance = MagicMock()
        llm_cls.return_value = llm_instance
        instance = MagicMock()
        instance.refine.return_value = self._suggestion()
        refiner_cls.return_value = instance
        resp = client.post(
            "/api/v1/ai/refine-strategy",
            json={
                "strategy_name": "ema_cross",
                "backtest_results": {"sharpe_ratio": 1.2, "max_drawdown": -0.08},
                "current_params": {"fast": 9, "slow": 21},
            },
        )
        assert resp.status_code == 200
        assert refiner_cls.call_args.kwargs["llm_client"] is llm_instance
        llm_instance.close.assert_called_once()
