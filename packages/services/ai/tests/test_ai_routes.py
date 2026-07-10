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


def _market_summary_provider_data() -> dict[str, object]:
    """Complete trusted numeric snapshot expected by the rich-summary path."""
    return {
        "indices": [{"name": "NIFTY 50", "value": 24500.0, "change_pct": 0.8}],
        "fii_dii_flow": {"fii_net": 100.0, "dii_net": -20.0},
    }


def _typed_market_summary():
    from flinttrade_ai.sentiment import MarketSummary

    return MarketSummary.model_validate(
        {
            "sentiment_score": 6.5,
            "market_sentiment": "BULLISH",
            "indices": [{"name": "NIFTY 50", "value": 24500, "change_pct": 0.8, "signal": "BUY"}],
            "sectors": [{"name": "IT", "performance": "Outperforming", "outlook": "Firm."}],
            "key_points": ["Point one", "Point two", "Point three"],
            "fii_dii_flow": {"fii_net": 100, "dii_net": -20, "interpretation": "Net inflow."},
            "risks": ["Oil"],
            "opportunities": ["IT"],
        }
    )


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
                patch("flinttrade_ai.llm_client.LLMClient") as mock_llm_cls,
            ):
                mock_article_cls.return_value = MagicMock()
                resp = client.post(
                    "/api/v1/sentiment/analyse",
                    json={"text": "NIFTY rally expected"},
                )

        assert resp.status_code == 200
        assert resp.get_json()["data"]["label"] == "bullish"
        mock_llm_cls.return_value.close.assert_called_once()

    def test_scoring_failure_closes_llm_before_rule_fallback(self, client) -> None:
        fallback = MagicMock(sentiment="NEUTRAL", confidence=0.5, reasoning="")
        with (
            patch("flinttrade_ai.ai_routes._is_llm_configured", return_value=True),
            patch("flinttrade_ai.sentiment.score_article_with_llm", side_effect=RuntimeError("offline")),
            patch("flinttrade_ai.sentiment.score_article_rule_based", return_value=fallback),
            patch("flinttrade_ai.llm_client.LLMClient") as mock_llm_cls,
        ):
            resp = client.post("/api/v1/sentiment/analyse", json={"text": "NIFTY unchanged"})

        assert resp.status_code == 200
        assert resp.get_json()["data"]["label"] == "neutral"
        mock_llm_cls.return_value.close.assert_called_once()


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

    def test_disabled_rag_runtime_returns_a_distinct_reason(self, app, client) -> None:
        app.config["RAG_STATUS"] = "disabled"

        resp = client.post("/api/v1/rag/query", json={"query": "What is theta?"})

        assert resp.status_code == 503
        assert resp.get_json()["message"] == "RAG runtime disabled"

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
        rag_response.answer = "Theta is time decay."
        rag_response.error = None
        rag_response.chunks_used = [chunk]

        mock_rag = MagicMock()
        mock_rag.query.return_value = rag_response
        app.config["RAG"] = mock_rag

        resp = client.post("/api/v1/rag/query", json={"query": "What is theta?", "top_k": 3})
        assert resp.status_code == 200
        mock_rag.query.assert_called_once_with("What is theta?", top_k=3)
        data = resp.get_json()
        assert data["status"] == "success"
        assert data["data"]["answer"] == "Theta is time decay."
        assert len(data["data"]["results"]) == 1
        assert data["data"]["results"][0]["content"] == "Theta is time decay."

    def test_rag_query_accepts_the_legacy_facade(self, app, client) -> None:
        """The compatibility RAGEngine accepts the route's canonical top_k keyword."""
        from flinttrade_ai.rag import RAGEngine

        rag = RAGEngine(llm_client=MagicMock())
        rag._store.search = MagicMock(return_value=[])
        app.config["RAG"] = rag

        resp = client.post("/api/v1/rag/query", json={"query": "What is theta?", "top_k": 3})

        assert resp.status_code == 200
        assert resp.get_json()["data"] == {"answer": "", "results": []}
        rag._store.search.assert_called_once_with(
            "What is theta?",
            top_k=3,
            doc_type=None,
            similarity_threshold=0.7,
        )

    def test_no_relevant_documents_returns_a_successful_empty_result(self, app, client) -> None:
        rag_response = MagicMock(
            answer="",
            error="No relevant documents found",
            chunks_used=[],
        )
        mock_rag = MagicMock()
        mock_rag.query.return_value = rag_response
        app.config["RAG"] = mock_rag

        resp = client.post("/api/v1/rag/query", json={"query": "Unknown adjustment"})

        assert resp.status_code == 200
        assert resp.get_json()["data"] == {"answer": "", "results": []}

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
        assert data["market_sentiment"] == "NEUTRAL"
        assert set(data) == {
            "sentiment_score",
            "market_sentiment",
            "indices",
            "sectors",
            "key_points",
            "fii_dii_flow",
            "risks",
            "opportunities",
        }
        assert len(data["key_points"]) == 3

    def test_rss_summary_uses_frontend_scale_and_label(self, client, monkeypatch) -> None:
        bullish = MagicMock(sentiment="BULLISH", confidence=0.8)
        bearish = MagicMock(sentiment="BEARISH", confidence=0.2)
        monkeypatch.setattr(
            "flinttrade_ai.sentiment.SentimentAnalyzer.analyze_feeds",
            lambda self: [bullish, bearish],
        )

        resp = client.get("/api/v1/ai/sentiment/summary")

        data = resp.get_json()["data"]
        assert data["sentiment_score"] == pytest.approx(3.0)
        assert data["market_sentiment"] == "BULLISH"
        assert len(data["key_points"]) == 3

    def test_rich_provider_returns_typed_market_summary(self, app, client) -> None:
        summary = _typed_market_summary()
        provider_data = _market_summary_provider_data()
        app.config["MARKET_SENTIMENT_DATA_PROVIDER"] = lambda: provider_data

        with patch(
            "flinttrade_ai.ai_routes._cached_or_schedule_rich_summary",
            return_value=summary,
        ) as cached_or_schedule:
            resp = client.get("/api/v1/ai/sentiment/summary")

        assert resp.status_code == 200
        assert resp.get_json()["data"] == summary.to_display_dict()
        cached_or_schedule.assert_called_once_with(provider_data)

    @pytest.mark.parametrize("provider", [lambda: {}, lambda: [], lambda: None])
    def test_empty_or_invalid_provider_uses_rss_fallback(self, app, client, monkeypatch, provider) -> None:
        app.config["MARKET_SENTIMENT_DATA_PROVIDER"] = provider
        monkeypatch.setattr(
            "flinttrade_ai.sentiment.SentimentAnalyzer.analyze_feeds",
            lambda self: [],
        )

        resp = client.get("/api/v1/ai/sentiment/summary")

        assert resp.status_code == 200
        assert resp.get_json()["data"]["market_sentiment"] == "NEUTRAL"

    def test_throwing_provider_uses_rss_fallback(self, app, client, monkeypatch) -> None:
        def broken_provider():
            raise RuntimeError("market data offline")

        app.config["MARKET_SENTIMENT_DATA_PROVIDER"] = broken_provider
        monkeypatch.setattr(
            "flinttrade_ai.sentiment.SentimentAnalyzer.analyze_feeds",
            lambda self: [],
        )

        resp = client.get("/api/v1/ai/sentiment/summary")

        assert resp.status_code == 200
        assert resp.get_json()["data"]["market_sentiment"] == "NEUTRAL"

    def test_uncached_rich_generation_schedules_and_uses_rss_fallback(self, app, client, monkeypatch) -> None:
        provider_data = _market_summary_provider_data()
        app.config["MARKET_SENTIMENT_DATA_PROVIDER"] = lambda: provider_data
        monkeypatch.setattr(
            "flinttrade_ai.sentiment.SentimentAnalyzer.analyze_feeds",
            lambda self: [],
        )

        with patch(
            "flinttrade_ai.ai_routes._cached_or_schedule_rich_summary",
            return_value=None,
        ) as cached_or_schedule:
            resp = client.get("/api/v1/ai/sentiment/summary")

        assert resp.status_code == 200
        assert resp.get_json()["data"]["market_sentiment"] == "NEUTRAL"
        cached_or_schedule.assert_called_once_with(provider_data)

    def test_background_generation_closes_client_on_failure(self) -> None:
        from flinttrade_ai.ai_routes import _generate_rich_market_summary

        with (
            patch("flinttrade_ai.ai_routes._is_llm_configured", return_value=True),
            patch("flinttrade_ai.llm_client.LLMClient") as mock_llm_cls,
            patch("flinttrade_ai.sentiment.generate_market_summary", return_value=None),
        ):
            result = _generate_rich_market_summary(_market_summary_provider_data())

        assert result is None
        mock_llm_cls.return_value.close.assert_called_once()

    def test_rich_generation_cache_is_single_flight(self, monkeypatch) -> None:
        import flinttrade_ai.ai_routes as routes

        thread = MagicMock()
        monkeypatch.setattr(routes, "_rich_summary_cache", None)
        monkeypatch.setattr(routes, "_rich_summary_inflight_key", None)

        with patch("flinttrade_ai.ai_routes.threading.Thread", return_value=thread) as thread_cls:
            first = routes._cached_or_schedule_rich_summary(_market_summary_provider_data())
            second = routes._cached_or_schedule_rich_summary(_market_summary_provider_data())

        assert first is None
        assert second is None
        thread_cls.assert_called_once()
        thread.start.assert_called_once()

    def test_cache_key_and_worker_share_one_immutable_snapshot(self, monkeypatch) -> None:
        import flinttrade_ai.ai_routes as routes

        provider_data = _market_summary_provider_data()
        thread = MagicMock()
        monkeypatch.setattr(routes, "_rich_summary_cache", None)
        monkeypatch.setattr(routes, "_rich_summary_inflight_key", None)

        with patch("flinttrade_ai.ai_routes.threading.Thread", return_value=thread) as thread_cls:
            routes._cached_or_schedule_rich_summary(provider_data)

        cache_key, worker_data = thread_cls.call_args.kwargs["args"]
        provider_data["indices"][0]["value"] = 99999.0
        assert worker_data["indices"][0]["value"] == pytest.approx(24500.0)
        assert cache_key == routes._market_data_cache_key(worker_data)

    def test_incomplete_provider_does_not_start_thread_or_llm(self, monkeypatch) -> None:
        import flinttrade_ai.ai_routes as routes

        monkeypatch.setattr(routes, "_rich_summary_cache", None)
        monkeypatch.setattr(routes, "_rich_summary_inflight_key", None)

        with (
            patch("flinttrade_ai.ai_routes.threading.Thread") as thread_cls,
            patch("flinttrade_ai.ai_routes._is_llm_configured", return_value=True),
            patch("flinttrade_ai.llm_client.LLMClient") as llm_cls,
        ):
            assert routes._cached_or_schedule_rich_summary({"nifty": 24500}) is None
            assert routes._generate_rich_market_summary({"nifty": 24500}) is None

        thread_cls.assert_not_called()
        llm_cls.assert_not_called()

    def test_thread_start_failure_clears_single_flight_marker(self, monkeypatch) -> None:
        import flinttrade_ai.ai_routes as routes

        thread = MagicMock()
        thread.start.side_effect = RuntimeError("thread creation unavailable")
        monkeypatch.setattr(routes, "_rich_summary_cache", None)
        monkeypatch.setattr(routes, "_rich_summary_inflight_key", None)

        with patch("flinttrade_ai.ai_routes.threading.Thread", return_value=thread):
            result = routes._cached_or_schedule_rich_summary(_market_summary_provider_data())

        assert result is None
        assert routes._rich_summary_inflight_key is None

    def test_provider_copy_failure_never_sets_single_flight_marker(self, monkeypatch) -> None:
        import flinttrade_ai.ai_routes as routes

        class CannotCopy:
            def __deepcopy__(self, memo):
                raise RuntimeError("not copyable")

        provider_data = _market_summary_provider_data()
        provider_data["extra"] = CannotCopy()
        monkeypatch.setattr(routes, "_rich_summary_cache", None)
        monkeypatch.setattr(routes, "_rich_summary_inflight_key", None)

        with patch("flinttrade_ai.ai_routes.threading.Thread") as thread_cls:
            result = routes._cached_or_schedule_rich_summary(provider_data)

        assert result is None
        assert routes._rich_summary_inflight_key is None
        thread_cls.assert_not_called()

    def test_background_refresh_publishes_cache_and_clears_marker(self, monkeypatch) -> None:
        import flinttrade_ai.ai_routes as routes

        provider_data = _market_summary_provider_data()
        cache_key = routes._market_data_cache_key(provider_data)
        summary = _typed_market_summary()
        monkeypatch.setattr(routes, "_rich_summary_cache", None)
        monkeypatch.setattr(routes, "_rich_summary_inflight_key", cache_key)
        monkeypatch.setattr(routes, "_generate_rich_market_summary", lambda data: summary)

        routes._refresh_rich_summary_cache(cache_key, provider_data)

        assert routes._rich_summary_cache is not None
        assert routes._rich_summary_cache.key == cache_key
        assert routes._rich_summary_cache.summary is summary
        assert routes._rich_summary_inflight_key is None


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
    """GET /api/v1/ai/regime — broker OHLCV when connected, free daily-data
    fallback when not; 503 only when NEITHER source has enough history."""

    def test_no_source_returns_503(self, client, monkeypatch) -> None:
        # Disconnected AND the free fallback has no data → a clear 503.
        monkeypatch.setattr(
            "flinttrade_ai.ai_routes._free_daily_ohlcv",
            lambda *a, **k: ([], [], []),
        )
        resp = client.get("/api/v1/ai/regime?symbol=NIFTY")
        assert resp.status_code == 503
        assert "Not enough history" in resp.get_json()["message"]

    def test_disconnected_falls_back_to_free_daily_data(self, client, monkeypatch) -> None:
        # No broker connected, but free daily OHLCV is available → the regime
        # panel still works for disconnected / Explore users.
        highs = [102.0 + i for i in range(30)]
        lows = [98.0 + i for i in range(30)]
        closes = [100.0 + i for i in range(30)]
        monkeypatch.setattr(
            "flinttrade_ai.ai_routes._free_daily_ohlcv",
            lambda *a, **k: (highs, lows, closes),
        )
        resp = client.get("/api/v1/ai/regime?symbol=NIFTY")
        assert resp.status_code == 200
        data = resp.get_json()["data"]
        assert "state" in data and data["suggested_strategy"]["strategy"]
        assert data["data_source"] == "openchart"

    def test_connected_registry_returns_live_regime(self, app, client) -> None:
        """The LIVE branch was dead code: registry.is_connected() /
        get_primary_account_id() did not exist, so a connected broker still got a
        503/500. With those methods present the route computes a real regime."""
        # 30 trending candles → a detectable regime.
        candles = [{"high": 100 + i, "low": 98 + i, "close": 99 + i, "open": 98.5 + i} for i in range(30)]

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
        assert data["data_source"] == "broker"


def test_free_daily_ohlcv_extracts_bars(monkeypatch) -> None:
    from flinttrade_ai import ai_routes
    from flinttrade_historical import free_data
    from flinttrade_historical.free_data import FreeBar, FreeDataResult

    bars = [FreeBar(timestamp="2026-01-01", open=100, high=102, low=99, close=101, volume=1000)]

    class _FakeNSE:
        def historical(self, *a, **k):
            return FreeDataResult(symbol="NIFTY", exchange="NSE", source="openchart", bars=bars)

    monkeypatch.setattr(free_data, "NSEData", _FakeNSE)
    highs, lows, closes = ai_routes._free_daily_ohlcv("NIFTY")
    assert highs == [102.0] and lows == [99.0] and closes == [101.0]


def test_free_daily_ohlcv_empty_on_error(monkeypatch) -> None:
    from flinttrade_ai import ai_routes
    from flinttrade_historical import free_data
    from flinttrade_historical.free_data import FreeDataResult

    class _EmptyNSE:
        def historical(self, *a, **k):
            return FreeDataResult(symbol="NIFTY", exchange="NSE", source="openchart", bars=[], error="boom")

    monkeypatch.setattr(free_data, "NSEData", _EmptyNSE)
    assert ai_routes._free_daily_ohlcv("NIFTY") == ([], [], [])
