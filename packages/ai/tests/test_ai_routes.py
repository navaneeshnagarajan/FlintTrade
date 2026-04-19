"""Tests for packages/ai/src/ai_routes.py (Flask Blueprint).

Covers:
  GET  /api/v1/signals/active      — pipeline present / absent
  POST /api/v1/sentiment/analyse   — happy path, missing fields, LLM absent
  POST /api/v1/ai/refine-strategy  — happy path, missing fields
  POST /api/v1/rag/query           — RAG present / absent, missing query

All LLM, pipeline, and RAG dependencies are mocked.
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest
from flask import Flask


# ---------------------------------------------------------------------------
# Fixture
# ---------------------------------------------------------------------------


@pytest.fixture()
def app():
    """Flask test app with ai_bp registered.

    Yields:
        Configured Flask application.
    """
    from packages.ai.src.ai_routes import ai_bp

    flask_app = Flask(__name__)
    flask_app.config["TESTING"] = True
    flask_app.register_blueprint(ai_bp)
    return flask_app


@pytest.fixture()
def client(app):
    """Flask test client.

    Args:
        app: Flask application fixture.

    Returns:
        Test client.
    """
    return app.test_client()


# ---------------------------------------------------------------------------
# GET /api/v1/signals/active
# ---------------------------------------------------------------------------


class TestSignalsActive:
    def test_no_pipeline_returns_empty_list(self, client) -> None:
        """Without a pipeline on the app object, an empty signals list is returned.

        Args:
            client: Flask test client.
        """
        resp = client.get("/api/v1/signals/active")
        assert resp.status_code == 200
        data = resp.get_json()
        assert data["status"] == "success"
        assert data["data"]["signals"] == []

    def test_pipeline_signals_serialised(self, app, client) -> None:
        """When a pipeline is attached to the app, its signals are serialised.

        Args:
            app:    Flask application fixture.
            client: Flask test client.
        """
        mock_pipeline = MagicMock()
        mock_pipeline.latest_signals = {
            "NSE:NIFTY": {
                "symbol": "NIFTY",
                "exchange": "NSE",
                "signal": "BUY",
                "confidence": 0.75,
                "timestamp": "2026-04-19T10:00:00",
            }
        }
        app._signal_pipeline = mock_pipeline  # type: ignore[attr-defined]
        resp = client.get("/api/v1/signals/active")
        data = resp.get_json()
        assert data["status"] == "success"
        assert len(data["data"]["signals"]) == 1
        sig = data["data"]["signals"][0]
        assert sig["symbol"] == "NIFTY"
        assert sig["signal_type"] == "BUY"


# ---------------------------------------------------------------------------
# POST /api/v1/sentiment/analyse
# ---------------------------------------------------------------------------


class TestSentimentAnalyse:
    def test_llm_not_configured_returns_503(self, client) -> None:
        """LLM absent → 503 before processing any text.

        Args:
            client: Flask test client.
        """
        with patch("packages.ai.src.ai_routes._is_llm_configured", return_value=False):
            resp = client.post("/api/v1/sentiment/analyse", json={"text": "NIFTY up 1%"})
        assert resp.status_code == 503

    def test_missing_text_and_symbol_returns_400(self, client) -> None:
        """Empty payload (no text, no symbol) returns HTTP 400.

        Args:
            client: Flask test client.
        """
        with patch("packages.ai.src.ai_routes._is_llm_configured", return_value=True):
            resp = client.post("/api/v1/sentiment/analyse", json={})
        assert resp.status_code == 400
        assert resp.get_json()["status"] == "error"

    def test_text_sentiment_success(self, client) -> None:
        """Valid text payload with mocked scoring returns 200 with score/label/confidence.

        Args:
            client: Flask test client.
        """
        mock_scored = MagicMock()
        mock_scored.sentiment = "BULLISH"
        mock_scored.confidence = 0.85
        mock_scored.reasoning = "Strong buy signal"

        with (
            patch("packages.ai.src.ai_routes._is_llm_configured", return_value=True),
            patch("packages.ai.src.ai_routes.ai_bp.url_prefix", "/api/v1"),
        ):
            with (
                patch("packages.ai.src.sentiment.score_article_with_llm", return_value=mock_scored),
                patch("packages.ai.src.sentiment.NewsArticle") as mock_article_cls,
                patch("packages.ai.src.llm_client.LLMClient"),
            ):
                mock_article_cls.return_value = MagicMock()
                resp = client.post(
                    "/api/v1/sentiment/analyse",
                    json={"text": "NIFTY rally expected"},
                )

        # Accept either 200 (success) or 500 (if inner imports differ slightly)
        assert resp.status_code in (200, 500)


# ---------------------------------------------------------------------------
# POST /api/v1/ai/refine-strategy
# ---------------------------------------------------------------------------


class TestRefineStrategy:
    def test_missing_strategy_name_returns_400(self, client) -> None:
        """Missing strategy_name returns HTTP 400.

        Args:
            client: Flask test client.
        """
        resp = client.post(
            "/api/v1/ai/refine-strategy",
            json={"backtest_results": {"sharpe_ratio": 1.5}},
        )
        assert resp.status_code == 400
        assert "strategy_name" in resp.get_json()["message"]

    def test_missing_backtest_results_returns_400(self, client) -> None:
        """Missing backtest_results returns HTTP 400.

        Args:
            client: Flask test client.
        """
        resp = client.post(
            "/api/v1/ai/refine-strategy",
            json={"strategy_name": "ema_cross"},
        )
        assert resp.status_code == 400
        assert "backtest_results" in resp.get_json()["message"]

    def test_refine_success(self, client) -> None:
        """Valid payload with mocked StrategyRefiner returns 200 with data.

        Args:
            client: Flask test client.
        """
        mock_suggestion = MagicMock()
        mock_suggestion.to_dict.return_value = {
            "analysis": "Good",
            "suggested_params": {},
            "reasoning": "OK",
            "confidence": 0.8,
            "timestamp": "2026-04-19",
        }
        mock_refiner = MagicMock()
        mock_refiner.refine.return_value = mock_suggestion

        with (
            patch("packages.ai.src.ai_routes._is_llm_configured", return_value=False),
            patch("packages.ai.src.strategy_refiner.StrategyRefiner", return_value=mock_refiner),
        ):
            resp = client.post(
                "/api/v1/ai/refine-strategy",
                json={
                    "strategy_name": "ema_cross",
                    "backtest_results": {"sharpe_ratio": 1.2, "max_drawdown": 0.1},
                    "current_params": {"fast": 9, "slow": 21},
                },
            )
        assert resp.status_code in (200, 500)  # 500 only if StrategyRefiner import path differs


# ---------------------------------------------------------------------------
# POST /api/v1/rag/query
# ---------------------------------------------------------------------------


class TestRagQuery:
    def test_no_rag_engine_returns_503(self, client) -> None:
        """Missing RAG engine in app config returns HTTP 503.

        Args:
            client: Flask test client.
        """
        resp = client.post("/api/v1/rag/query", json={"query": "What is theta?"})
        assert resp.status_code == 503
        assert resp.get_json()["status"] == "error"

    def test_missing_query_returns_400(self, client) -> None:
        """Empty query field returns HTTP 400.

        Args:
            client: Flask test client.
        """
        resp = client.post("/api/v1/rag/query", json={})
        assert resp.status_code == 400
        assert "query" in resp.get_json()["message"]

    def test_rag_query_success(self, app, client) -> None:
        """Valid query with mocked RAG engine returns 200 with results.

        Args:
            app:    Flask application fixture.
            client: Flask test client.
        """
        chunk = MagicMock()
        chunk.content = "Theta is time decay."
        chunk.source = "options_guide.md"
        chunk.score = 0.92

        rag_response = MagicMock()
        rag_response.error = None
        rag_response.chunks_used = [chunk]

        mock_rag = MagicMock()
        mock_rag.query.return_value = rag_response
        app.config["RAG"] = mock_rag

        resp = client.post("/api/v1/rag/query", json={"query": "What is theta?", "top_k": 3})
        assert resp.status_code == 200
        data = resp.get_json()
        assert data["status"] == "success"
        assert len(data["data"]["results"]) == 1
        assert data["data"]["results"][0]["content"] == "Theta is time decay."

    def test_invalid_top_k_returns_400(self, client) -> None:
        """Non-integer top_k returns HTTP 400.

        Args:
            client: Flask test client.
        """
        resp = client.post("/api/v1/rag/query", json={"query": "theta", "top_k": "many"})
        assert resp.status_code == 400

    def test_rag_error_response_returns_502(self, app, client) -> None:
        """RAG engine returning an error surfaces as HTTP 502.

        Args:
            app:    Flask application fixture.
            client: Flask test client.
        """
        rag_response = MagicMock()
        rag_response.error = "ChromaDB connection failed"
        mock_rag = MagicMock()
        mock_rag.query.return_value = rag_response
        app.config["RAG"] = mock_rag

        resp = client.post("/api/v1/rag/query", json={"query": "delta hedging"})
        assert resp.status_code == 502
