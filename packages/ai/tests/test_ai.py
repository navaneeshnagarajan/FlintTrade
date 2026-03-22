"""Tests for FlintTrade AI package.

DO NOT RUN — written for pytest. All tests use synthetic data, no API calls.
LLM/ChromaDB/LightGBM/CatBoost calls are mocked.
"""

from __future__ import annotations

import os
from unittest.mock import MagicMock



# ======================================================================
# LLM Client — initialization with different providers
# ======================================================================


class TestLLMClient:
    """Test LLM client initialization and provider handling."""

    def test_config_from_env(self, monkeypatch):
        monkeypatch.setenv("LLM_PROVIDER", "ollama")
        monkeypatch.setenv("LLM_HOST", "http://localhost:11434")
        monkeypatch.setenv("LLM_MODEL", "llama3")
        monkeypatch.setenv("LLM_CONTEXT_LENGTH", "8192")

        from packages.ai.src.llm_client import LLMConfig
        cfg = LLMConfig.from_env()
        assert cfg.provider == "ollama"
        assert cfg.host == "http://localhost:11434"
        assert cfg.model == "llama3"
        assert cfg.context_length == 8192

    def test_config_defaults(self, monkeypatch):
        monkeypatch.delenv("LLM_PROVIDER", raising=False)
        monkeypatch.delenv("LLM_HOST", raising=False)
        monkeypatch.delenv("LLM_MODEL", raising=False)

        from packages.ai.src.llm_client import LLMConfig
        cfg = LLMConfig.from_env()
        assert cfg.provider == ""
        assert "1234" in cfg.host

    def test_client_creates_with_config(self):
        from packages.ai.src.llm_client import LLMClient, LLMConfig
        cfg = LLMConfig(provider="lmstudio", host="http://127.0.0.1:1234", model="test")
        client = LLMClient(config=cfg)
        assert client.config.provider == "lmstudio"
        client.close()

    def test_client_with_fallback(self):
        from packages.ai.src.llm_client import LLMClient, LLMConfig
        primary = LLMConfig(provider="lmstudio", host="http://localhost:1234", model="primary")
        fallback = LLMConfig(provider="ollama", host="http://localhost:11434", model="fallback")
        client = LLMClient(config=primary, fallback_config=fallback)
        assert client.fallback_config is not None
        client.close()

    def test_estimate_tokens(self):
        from packages.ai.src.llm_client import estimate_tokens
        assert estimate_tokens("hello world") >= 2
        assert estimate_tokens("") == 1

    def test_fits_context(self):
        from packages.ai.src.llm_client import LLMClient, LLMConfig, LLMMessage
        cfg = LLMConfig(context_length=2000)
        client = LLMClient(config=cfg)
        messages = [LLMMessage(role="user", content="short message")]
        assert client.fits_context(messages)
        client.close()

    def test_does_not_fit_context(self):
        from packages.ai.src.llm_client import LLMClient, LLMConfig, LLMMessage
        cfg = LLMConfig(context_length=10)
        client = LLMClient(config=cfg)
        messages = [LLMMessage(role="user", content="a" * 1000)]
        assert not client.fits_context(messages)
        client.close()

    def test_trim_to_fit(self):
        from packages.ai.src.llm_client import LLMClient, LLMConfig, LLMMessage
        cfg = LLMConfig(context_length=50)
        client = LLMClient(config=cfg)
        messages = [
            LLMMessage(role="system", content="sys"),
            LLMMessage(role="user", content="old msg " * 50),
            LLMMessage(role="user", content="new msg"),
        ]
        trimmed = client.trim_to_fit(messages)
        # System message should be preserved
        assert any(m.role == "system" for m in trimmed)
        # Should be shorter than original
        assert len(trimmed) <= len(messages)
        client.close()

    def test_provider_enum(self):
        from packages.ai.src.llm_client import LLMProvider
        assert LLMProvider.LMSTUDIO == "lmstudio"
        assert LLMProvider.OLLAMA == "ollama"
        assert LLMProvider.ANTHROPIC == "anthropic"
        assert LLMProvider.OPENAI == "openai"

    def test_response_success_property(self):
        from packages.ai.src.llm_client import LLMResponse
        assert LLMResponse(content="hello").success
        assert not LLMResponse(content="", error="fail").success
        assert not LLMResponse(content="").success


# ======================================================================
# RAG — chunking and retrieval
# ======================================================================


class TestRAG:
    """Test RAG chunking and document handling."""

    def test_chunk_short_text(self):
        from packages.ai.src.rag import chunk_text
        result = chunk_text("Hello world", chunk_size=100)
        assert len(result) == 1
        assert result[0] == "Hello world"

    def test_chunk_long_text(self):
        from packages.ai.src.rag import chunk_text
        text = "word " * 1000
        chunks = chunk_text(text, chunk_size=50, overlap=10)
        assert len(chunks) > 1
        # Chunks should overlap
        for c in chunks:
            assert len(c) > 0

    def test_chunk_preserves_content(self):
        from packages.ai.src.rag import chunk_text
        text = "The quick brown fox. Jumps over the lazy dog. " * 20
        chunks = chunk_text(text, chunk_size=20, overlap=5)
        # Reassembled chunks should cover most of the original
        combined = " ".join(chunks)
        assert "quick brown fox" in combined

    def test_content_hash_stable(self):
        from packages.ai.src.rag import content_hash
        h1 = content_hash("test content")
        h2 = content_hash("test content")
        assert h1 == h2
        h3 = content_hash("different content")
        assert h1 != h3

    def test_document_creation(self):
        from packages.ai.src.rag import Document
        doc = Document(
            content="NIFTY options strategy guide",
            source="docs/strategy.md",
            doc_type="strategy",
        )
        assert doc.doc_type == "strategy"
        assert doc.source == "docs/strategy.md"

    def test_rag_engine_infer_doc_type(self):
        from packages.ai.src.rag import RAGEngine
        assert RAGEngine._infer_doc_type("my_strategy.md") == "strategy"
        assert RAGEngine._infer_doc_type("OPENALGO_API.md") == "api_docs"
        assert RAGEngine._infer_doc_type("trade_journal.txt") == "trade_journal"
        assert RAGEngine._infer_doc_type("market_report.md") == "market_report"
        assert RAGEngine._infer_doc_type("random.txt") == "general"

    def test_retrieved_chunk_dataclass(self):
        from packages.ai.src.rag import RetrievedChunk
        chunk = RetrievedChunk(
            content="NIFTY max pain is 24000",
            source="docs/oi.md",
            doc_type="strategy",
            score=0.85,
        )
        assert chunk.score == 0.85

    def test_rag_response_success(self):
        from packages.ai.src.rag import RAGResponse
        r = RAGResponse(answer="Max pain is the strike...", query="What is max pain?")
        assert r.success
        empty = RAGResponse(query="test", error="no docs")
        assert not empty.success


# ======================================================================
# Signals — feature engineering pipeline
# ======================================================================


class TestSignals:
    """Test signal feature engineering and prediction."""

    def _make_bars(self, n=100):
        import random
        random.seed(42)
        bars = []
        price = 100.0
        for i in range(n):
            price += random.uniform(-1, 1.5)
            price = max(10, price)
            bars.append({
                "timestamp": f"2025-01-{(i % 28) + 1:02d}",
                "open": price, "high": price + 1, "low": price - 1,
                "close": price + 0.5, "volume": 10000 + i * 100, "oi": 0,
            })
        return bars

    def test_engineer_features_basic(self):
        from packages.ai.src.signals import engineer_features
        bars = self._make_bars(100)
        features = engineer_features(bars)
        assert len(features.names) > 0
        assert len(features.values) > 0
        # Feature names should include known indicators
        assert "rsi_14" in features.names
        assert "macd_hist" in features.names
        assert "bb_pct" in features.names

    def test_engineer_features_too_few_bars(self):
        from packages.ai.src.signals import engineer_features
        bars = self._make_bars(10)
        features = engineer_features(bars)
        assert len(features.values) == 0

    def test_engineer_features_with_oi_data(self):
        from packages.ai.src.signals import engineer_features
        bars = self._make_bars(100)
        pcr = [0.8 + i * 0.001 for i in range(100)]
        features = engineer_features(bars, pcr_values=pcr)
        assert "pcr" in features.names
        # PCR feature should be populated
        pcr_idx = features.names.index("pcr")
        assert features.values[-1][pcr_idx] > 0

    def test_generate_labels(self):
        from packages.ai.src.signals import generate_labels
        closes = [100 + i * 0.5 for i in range(100)]
        labels = generate_labels(closes, lookahead=5, threshold_pct=0.5, offset=20)
        assert len(labels) == 80  # 100 - offset=20
        # In a steady uptrend, most labels should be BUY (2)
        buy_count = sum(1 for l in labels if l == 2)
        assert buy_count > 0

    def test_compute_rsi(self):
        from packages.ai.src.signals import compute_rsi
        # Steady uptrend → RSI should be high
        closes = [100 + i for i in range(30)]
        rsi_vals = compute_rsi(closes, 14)
        assert len(rsi_vals) == 30
        assert rsi_vals[-1] > 50

    def test_compute_rsi_downtrend(self):
        from packages.ai.src.signals import compute_rsi
        closes = [200 - i for i in range(30)]
        rsi_vals = compute_rsi(closes, 14)
        assert rsi_vals[-1] < 50

    def test_compute_ema(self):
        from packages.ai.src.signals import compute_ema
        values = [float(i) for i in range(20)]
        result = compute_ema(values, 5)
        assert len(result) == 20
        assert result[-1] > result[0]

    def test_compute_bollinger_pct(self):
        from packages.ai.src.signals import compute_bollinger_pct
        closes = [100.0] * 30
        bb = compute_bollinger_pct(closes, 20)
        assert len(bb) == 30
        # Flat price = at middle of bands
        assert 0.3 <= bb[-1] <= 0.7

    def test_signal_dataclass(self):
        from packages.ai.src.signals import Signal
        s = Signal(action="BUY", confidence=0.8, symbol="NIFTY")
        assert s.is_actionable
        hold = Signal(action="HOLD", confidence=0.9)
        assert not hold.is_actionable
        low_conf = Signal(action="BUY", confidence=0.3)
        assert not low_conf.is_actionable

    def test_signal_generator_init(self):
        from packages.ai.src.signals import SignalGenerator
        sg = SignalGenerator()
        assert not sg.is_trained


# ======================================================================
# Sentiment — scoring output format
# ======================================================================


class TestSentiment:
    """Test sentiment analysis output formatting."""

    def test_extract_symbols(self):
        from packages.ai.src.sentiment import extract_symbols
        symbols = extract_symbols("NIFTY hits all-time high, RELIANCE and TCS gain 2%")
        assert "NIFTY" in symbols
        assert "RELIANCE" in symbols
        assert "TCS" in symbols

    def test_extract_symbols_empty(self):
        from packages.ai.src.sentiment import extract_symbols
        symbols = extract_symbols("No stock names here")
        assert len(symbols) == 0

    def test_rule_based_sentiment_bullish(self):
        from packages.ai.src.sentiment import NewsArticle, score_article_rule_based
        article = NewsArticle(
            title="Markets surge to all-time high on strong earnings growth",
            summary="The rally continued as investors bought into the rally.",
        )
        score = score_article_rule_based(article)
        assert score.sentiment == "BULLISH"
        assert score.confidence > 0.5

    def test_rule_based_sentiment_bearish(self):
        from packages.ai.src.sentiment import NewsArticle, score_article_rule_based
        article = NewsArticle(
            title="Markets crash 3% on weak global cues, sell-off intensifies",
            summary="Massive correction as investors panic sell amid decline.",
        )
        score = score_article_rule_based(article)
        assert score.sentiment == "BEARISH"

    def test_rule_based_sentiment_neutral(self):
        from packages.ai.src.sentiment import NewsArticle, score_article_rule_based
        article = NewsArticle(
            title="Markets await RBI policy decision tomorrow",
            summary="Investors remain cautious ahead of monetary policy.",
        )
        score = score_article_rule_based(article)
        assert score.sentiment == "NEUTRAL"

    def test_sentiment_score_format(self):
        from packages.ai.src.sentiment import SentimentScore
        s = SentimentScore(
            article_title="Test",
            sentiment="BULLISH",
            confidence=0.85,
            symbols=["NIFTY", "RELIANCE"],
        )
        assert s.sentiment in ("BULLISH", "BEARISH", "NEUTRAL")
        assert 0 <= s.confidence <= 1
        assert isinstance(s.symbols, list)

    def test_aggregate_sentiment(self):
        from packages.ai.src.sentiment import SentimentScore, aggregate_sentiment
        scores = [
            SentimentScore(sentiment="BULLISH", confidence=0.8, symbols=["NIFTY"]),
            SentimentScore(sentiment="BULLISH", confidence=0.9, symbols=["NIFTY"]),
            SentimentScore(sentiment="BEARISH", confidence=0.6, symbols=["NIFTY"]),
        ]
        agg = aggregate_sentiment(scores, "NIFTY")
        assert agg.bullish_count == 2
        assert agg.bearish_count == 1
        assert agg.article_count == 3
        assert agg.net_score > 0  # Net bullish
        assert agg.dominant_sentiment == "BULLISH"

    def test_aggregate_empty(self):
        from packages.ai.src.sentiment import aggregate_sentiment
        agg = aggregate_sentiment([], "NIFTY")
        assert agg.article_count == 0
        assert agg.net_score == 0

    def test_detect_shifts(self):
        from packages.ai.src.sentiment import SentimentAnalyzer, SentimentScore
        prev = [
            SentimentScore(sentiment="NEUTRAL", confidence=0.5, symbols=["NIFTY"]),
        ]
        curr = [
            SentimentScore(sentiment="BULLISH", confidence=0.9, symbols=["NIFTY"]),
            SentimentScore(sentiment="BULLISH", confidence=0.8, symbols=["NIFTY"]),
        ]
        alerts = SentimentAnalyzer.detect_shifts(curr, prev, threshold=0.3)
        assert len(alerts) > 0
        assert alerts[0]["symbol"] == "NIFTY"
        assert alerts[0]["direction"] == "BULLISH"

    def test_analyzer_init(self):
        from packages.ai.src.sentiment import SentimentAnalyzer
        analyzer = SentimentAnalyzer()
        assert len(analyzer._feeds) > 0


# ======================================================================
# MCP Bridge — command parsing
# ======================================================================


class TestMCPBridge:
    """Test MCP bridge natural language command parsing."""

    def test_parse_buy_order(self):
        from packages.ai.src.mcp_bridge import parse_order_command
        result = parse_order_command("Buy RELIANCE 100 shares")
        assert result is not None
        assert result.tool_name == "place_order"
        assert result.arguments["symbol"] == "RELIANCE"
        assert result.arguments["action"] == "BUY"
        assert result.arguments["quantity"] == "100"

    def test_parse_sell_order(self):
        from packages.ai.src.mcp_bridge import parse_order_command
        result = parse_order_command("Sell TCS 50 qty")
        assert result is not None
        assert result.arguments["action"] == "SELL"
        assert result.arguments["symbol"] == "TCS"
        assert result.arguments["quantity"] == "50"

    def test_parse_options_order(self):
        from packages.ai.src.mcp_bridge import parse_order_command
        result = parse_order_command("Sell NIFTY25000CE 2 lots")
        assert result is not None
        assert result.arguments["action"] == "SELL"
        assert result.arguments["exchange"] == "NFO"
        # 2 lots * 75 = 150
        assert result.arguments["quantity"] == "150"

    def test_parse_with_price(self):
        from packages.ai.src.mcp_bridge import parse_order_command
        result = parse_order_command("Buy RELIANCE 10 shares at 2500 limit")
        assert result is not None
        assert result.arguments["price"] == "2500"
        assert result.arguments["pricetype"] == "LIMIT"

    def test_parse_simple_order(self):
        from packages.ai.src.mcp_bridge import parse_order_command
        result = parse_order_command("Buy INFY")
        assert result is not None
        assert result.arguments["symbol"] == "INFY"

    def test_parse_non_order(self):
        from packages.ai.src.mcp_bridge import parse_order_command
        result = parse_order_command("What is the current NIFTY price?")
        assert result is None

    def test_bridge_execute_with_handler(self):
        from packages.ai.src.mcp_bridge import MCPBridge
        bridge = MCPBridge()
        mock_handler = MagicMock(return_value={"orderid": "12345"})
        bridge.register_handler("place_order", mock_handler)

        result = bridge.execute("Buy RELIANCE 100 shares")
        assert result.success
        assert result.tool_name == "place_order"
        mock_handler.assert_called_once()

    def test_bridge_execute_no_handler(self):
        from packages.ai.src.mcp_bridge import MCPBridge
        bridge = MCPBridge()
        result = bridge.execute("Buy RELIANCE 100 shares")
        assert not result.success
        assert "No handler" in result.error

    def test_bridge_available_tools(self):
        from packages.ai.src.mcp_bridge import MCPBridge
        bridge = MCPBridge()
        tools = bridge.available_tools
        assert "place_order" in tools
        assert "get_positions" in tools
        assert "get_quotes" in tools
        assert "get_option_chain" in tools
        assert "get_greeks" in tools
        assert "run_backtest" in tools
        assert "get_screener_data" in tools

    def test_tool_definitions_valid(self):
        from packages.ai.src.mcp_bridge import TOOL_DEFINITIONS
        for tool in TOOL_DEFINITIONS:
            assert "name" in tool
            assert "description" in tool
            assert "parameters" in tool

    def test_bridge_parse_fallback(self):
        from packages.ai.src.mcp_bridge import MCPBridge
        # Without LLM, non-order commands should return tool_name="none"
        bridge = MCPBridge()
        call = bridge.parse("What are my positions?")
        assert call.tool_name == "none"


# ======================================================================
# Advisor — ranking output
# ======================================================================


class TestAdvisor:
    """Test stock advisor ranking output."""

    def _make_stocks(self):
        from packages.ai.src.advisor import StockFeatures
        return [
            StockFeatures(
                symbol="RELIANCE", pe_ratio=25, pb_ratio=2.5, roe=15,
                rsi_14=55, return_1m=3.0, return_3m=8.0, sentiment_score=0.3,
            ),
            StockFeatures(
                symbol="TCS", pe_ratio=30, pb_ratio=10, roe=40,
                rsi_14=65, return_1m=5.0, return_3m=12.0, sentiment_score=0.5,
            ),
            StockFeatures(
                symbol="INFY", pe_ratio=22, pb_ratio=7, roe=30,
                rsi_14=45, return_1m=-2.0, return_3m=-5.0, sentiment_score=-0.3,
            ),
        ]

    def test_simple_rank_without_model(self):
        from packages.ai.src.advisor import StockAdvisor
        advisor = StockAdvisor()
        stocks = self._make_stocks()
        suggestion = advisor.rank(stocks, top_n=3)
        assert suggestion.total_stocks == 3
        assert len(suggestion.rankings) > 0
        # Rankings should be sorted by score descending
        scores = [r.score for r in suggestion.rankings]
        assert scores == sorted(scores, reverse=True)

    def test_ranking_has_actions(self):
        from packages.ai.src.advisor import StockAdvisor
        advisor = StockAdvisor()
        stocks = self._make_stocks()
        suggestion = advisor.rank(stocks)
        for r in suggestion.rankings:
            assert r.action in ("BUY", "SELL", "HOLD")
            assert 0 <= r.score <= 1

    def test_ranking_allocations(self):
        from packages.ai.src.advisor import StockAdvisor
        advisor = StockAdvisor()
        stocks = self._make_stocks()
        suggestion = advisor.rank(stocks, top_n=3)
        buy_picks = suggestion.buy_picks
        if buy_picks:
            total_alloc = sum(p.allocation_pct for p in buy_picks)
            assert abs(total_alloc - 100) < 1  # Should sum to ~100%

    def test_features_to_array(self):
        from packages.ai.src.advisor import StockFeatures, features_to_array
        sf = StockFeatures(symbol="TEST", pe_ratio=20, roe=15, rsi_14=60)
        arr = features_to_array(sf)
        assert len(arr) == 16  # Number of features
        assert arr[0] == 20  # pe_ratio
        assert arr[2] == 15  # roe

    def test_rebalance_check(self):
        from packages.ai.src.advisor import StockAdvisor
        advisor = StockAdvisor()
        current = {"RELIANCE": 20.0, "TCS": 15.0, "INFY": 10.0}
        target = {"RELIANCE": 10.0, "TCS": 10.0, "INFY": 10.0}
        alerts = advisor.check_rebalance(current, target, threshold_pct=5.0)
        assert len(alerts) > 0
        # RELIANCE drifted 10% from target
        rel_alert = [a for a in alerts if a.symbol == "RELIANCE"]
        assert len(rel_alert) == 1
        assert rel_alert[0].action == "DECREASE"
        assert rel_alert[0].drift_pct == 10.0

    def test_rebalance_exit(self):
        from packages.ai.src.advisor import StockAdvisor
        advisor = StockAdvisor()
        current = {"OLD_STOCK": 15.0}
        target = {}
        alerts = advisor.check_rebalance(current, target, threshold_pct=5.0)
        assert len(alerts) == 1
        assert alerts[0].action == "EXIT"

    def test_rebalance_no_drift(self):
        from packages.ai.src.advisor import StockAdvisor
        advisor = StockAdvisor()
        current = {"RELIANCE": 10.0}
        target = {"RELIANCE": 10.0}
        alerts = advisor.check_rebalance(current, target, threshold_pct=5.0)
        assert len(alerts) == 0

    def test_advisor_not_trained_initially(self):
        from packages.ai.src.advisor import StockAdvisor
        advisor = StockAdvisor()
        assert not advisor.is_trained

    def test_portfolio_suggestion_properties(self):
        from packages.ai.src.advisor import PortfolioSuggestion, StockRanking
        suggestion = PortfolioSuggestion(
            rankings=[
                StockRanking(symbol="A", action="BUY", score=0.8),
                StockRanking(symbol="B", action="SELL", score=0.3),
                StockRanking(symbol="C", action="HOLD", score=0.5),
            ],
            total_stocks=3,
        )
        assert len(suggestion.buy_picks) == 1
        assert len(suggestion.sell_picks) == 1


# ======================================================================
# Package exports
# ======================================================================


class TestPackageExports:
    """Verify __init__.py exports."""

    def test_all_exports(self):
        from packages.ai.src import __all__
        expected = [
            "LLMClient", "RAGEngine", "SignalGenerator",
            "SentimentAnalyzer", "MCPBridge", "StockAdvisor",
            "LLMConfig", "LLMMessage", "LLMResponse",
            "Document", "Signal", "SentimentScore",
        ]
        for name in expected:
            assert name in __all__, f"Missing export: {name}"

    def test_version(self):
        from packages.ai.src import __version__
        assert __version__ == "0.1.0-alpha"

    def test_package_exists(self):
        pkg_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        assert os.path.exists(os.path.join(pkg_dir, "src", "__init__.py"))
        assert os.path.exists(os.path.join(pkg_dir, "README.md"))
