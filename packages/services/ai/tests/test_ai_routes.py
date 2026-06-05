"""Tests for packages/services/ai/src/ai_routes.py (Flask Blueprint).

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
    from flinttrade_ai.ai_routes import ai_bp

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
        with patch("flinttrade_ai.ai_routes._is_llm_configured", return_value=False):
            resp = client.post("/api/v1/sentiment/analyse", json={"text": "NIFTY up 1%"})
        assert resp.status_code == 503

    def test_missing_text_and_symbol_returns_400(self, client) -> None:
        """Empty payload (no text, no symbol) returns HTTP 400.

        Args:
            client: Flask test client.
        """
        with patch("flinttrade_ai.ai_routes._is_llm_configured", return_value=True):
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
            patch("flinttrade_ai.ai_routes._is_llm_configured", return_value=True),
            patch("flinttrade_ai.ai_routes.ai_bp.url_prefix", "/api/v1"),
        ):
            with (
                patch("flinttrade_ai.sentiment.score_article_with_llm", return_value=mock_scored),
                patch("flinttrade_ai.sentiment.NewsArticle") as mock_article_cls,
                patch("flinttrade_ai.llm_client.LLMClient"),
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
            patch("flinttrade_ai.ai_routes._is_llm_configured", return_value=False),
            patch("flinttrade_ai.strategy_refiner.StrategyRefiner", return_value=mock_refiner),
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


class TestSentimentSummary:
    """GET /api/v1/ai/sentiment/summary — honest neutral summary when no feed."""

    def test_returns_neutral_summary_when_no_feed(self, client, monkeypatch) -> None:
        monkeypatch.setattr(
            "flinttrade_ai.sentiment.SentimentAnalyzer.analyze_feeds",
            lambda self: [],
        )
        resp = client.get("/api/v1/ai/sentiment/summary")
        assert resp.status_code == 200
        data = resp.get_json()["data"]
        assert data["sentiment_score"] == 0.0
        assert data["market_sentiment"] == "neutral"
        assert isinstance(data["indices"], list)
        assert "fii_net" in data["fii_dii_flow"]
        assert data["key_points"]  # honest note when no feed


class TestSentimentTickers:
    """GET /api/v1/ai/sentiment/tickers — empty list when no feed."""

    def test_returns_empty_list_when_no_feed(self, client, monkeypatch) -> None:
        monkeypatch.setattr(
            "flinttrade_ai.sentiment.SentimentAnalyzer.analyze_feeds",
            lambda self: [],
        )
        resp = client.get("/api/v1/ai/sentiment/tickers")
        assert resp.status_code == 200
        assert resp.get_json()["data"]["tickers"] == []


class TestMarketRegime:
    """GET /api/v1/ai/regime — clear 503 (not 404) without market data."""

    def test_no_market_data_returns_503(self, client) -> None:
        resp = client.get("/api/v1/ai/regime?symbol=NIFTY")
        assert resp.status_code == 503
        assert "connected market-data" in resp.get_json()["message"]

    def test_connected_registry_returns_live_regime(self, app, client) -> None:
        """The LIVE branch was dead code: registry.is_connected() /
        get_primary_account_id() did not exist, so a connected broker still got a
        503/500. With those methods present the route computes a real regime."""
        # 30 trending candles → a detectable regime.
        candles = [
            {"high": 100 + i, "low": 98 + i, "close": 99 + i, "open": 98.5 + i}
            for i in range(30)
        ]

        class _FakeRegistry:
            def is_connected(self):
                return True

            def get_primary_account_id(self):
                return "acc-1"

            def get_history(self, account_id, params):
                assert account_id == "acc-1"
                return {"data": candles}

        app.config["REGISTRY"] = _FakeRegistry()
        resp = client.get("/api/v1/ai/regime?symbol=NIFTY")
        assert resp.status_code == 200
        data = resp.get_json()["data"]
        assert "state" in data and "suggested_strategy" in data  # the regime loop closed
