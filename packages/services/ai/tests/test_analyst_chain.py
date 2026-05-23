"""Tests for AnalystChain — multi-agent analysis pipeline.

All tests mock LLMClient to avoid real LLM calls.
Arrange-Act-Assert structure throughout.
"""

from __future__ import annotations

from datetime import date
from unittest.mock import MagicMock


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_llm_client(response_text: str = "LLM response") -> MagicMock:
    """Return a mock LLMClient whose chat() returns a successful LLMResponse."""
    from flinttrade_ai.llm_client import LLMResponse

    client = MagicMock()
    client.chat.return_value = LLMResponse(content=response_text)
    return client


def _make_chain(
    response_text: str = "LLM response",
    analysts: list[str] | None = None,
    deep_response_text: str | None = None,
    memory=None,
):
    """Build an AnalystChain with mocked LLM clients."""
    from flinttrade_ai.analyst_chain import AnalystChain

    quick = _make_llm_client(response_text)
    deep = _make_llm_client(deep_response_text or response_text) if deep_response_text else None
    return AnalystChain(
        llm_client=quick,
        deep_llm_client=deep,
        memory=memory,
        analysts=analysts,
    ), quick, deep


# ---------------------------------------------------------------------------
# State dataclass
# ---------------------------------------------------------------------------


class TestAnalysisState:
    """Test AnalysisState default values and field types."""

    def test_defaults(self) -> None:
        # Arrange / Act
        from flinttrade_ai.analyst_chain import AnalysisState

        state = AnalysisState(
            symbol="NIFTY",
            exchange="NSE_INDEX",
            trade_date=date(2026, 3, 25),
        )
        # Assert
        assert state.market_report == ""
        assert state.sentiment_report == ""
        assert state.bull_thesis == ""
        assert state.bear_thesis == ""
        assert state.risk_assessment == ""
        assert state.final_decision == "HOLD"
        assert state.final_reasoning == ""
        assert state.confidence == 0.0
        assert state.errors == []

    def test_errors_field_is_independent_per_instance(self) -> None:
        # Arrange — two independent instances must not share the errors list
        from flinttrade_ai.analyst_chain import AnalysisState

        s1 = AnalysisState(symbol="A", exchange="NSE", trade_date=date.today())
        s2 = AnalysisState(symbol="B", exchange="NSE", trade_date=date.today())
        # Act
        s1.errors.append("some error")
        # Assert
        assert s2.errors == []


# ---------------------------------------------------------------------------
# AnalystChain.analyze — full pipeline runs
# ---------------------------------------------------------------------------


class TestAnalyzeReturnState:
    """Test that analyze() always returns a valid AnalysisState."""

    def test_analyze_returns_state_with_decision(self) -> None:
        # Arrange
        judge_text = "DECISION: BUY\nCONFIDENCE: 0.8\nREASONING: Strong momentum."
        chain, quick, _ = _make_chain(
            response_text="Market looks good.",
            deep_response_text=judge_text,
            analysts=["market"],
        )
        # Act
        state = chain.analyse("NIFTY", "NSE_INDEX")
        # Assert
        from flinttrade_ai.analyst_chain import AnalysisState

        assert isinstance(state, AnalysisState)
        assert state.symbol == "NIFTY"
        assert state.exchange == "NSE_INDEX"
        assert state.final_decision in ("BUY", "SELL", "HOLD")

    def test_analyze_uses_today_when_date_omitted(self) -> None:
        # Arrange
        chain, _, _ = _make_chain(analysts=["market"])
        # Act
        state = chain.analyse("NIFTY", "NSE_INDEX")
        # Assert
        assert state.trade_date == date.today()

    def test_analyze_respects_supplied_date(self) -> None:
        # Arrange
        target_date = date(2026, 1, 15)
        chain, _, _ = _make_chain(analysts=["market"])
        # Act
        state = chain.analyse("NIFTY", "NSE_INDEX", trade_date=target_date)
        # Assert
        assert state.trade_date == target_date

    def test_custom_analyst_list(self) -> None:
        # Arrange — only run fundamentals, skip market and sentiment
        from flinttrade_ai.llm_client import LLMResponse
        from flinttrade_ai.analyst_chain import AnalystChain

        fundamentals_response = "BULL: Strong earnings.\nBEAR: High valuation."
        quick = MagicMock()
        quick.chat.return_value = LLMResponse(content=fundamentals_response)
        chain = AnalystChain(llm_client=quick, analysts=["fundamentals"])
        # Act
        state = chain.analyse("TCS", "NSE")
        # Assert
        assert state.bull_thesis != "" or state.bear_thesis != ""
        assert state.market_report == ""
        assert state.sentiment_report == ""


# ---------------------------------------------------------------------------
# Market analyst node
# ---------------------------------------------------------------------------


class TestMarketAnalyst:
    """Test the market analyst node behaviour."""

    def test_analyze_with_market_analyst_populates_report(self) -> None:
        # Arrange
        expected_report = "Nifty is in a strong uptrend with support at 22000."
        chain, quick, _ = _make_chain(
            response_text=expected_report,
            analysts=["market"],
        )
        # Act
        state = chain.analyse("NIFTY", "NSE_INDEX")
        # Assert
        assert state.market_report == expected_report

    def test_market_analyst_calls_llm_once(self) -> None:
        # Arrange
        chain, quick, deep = _make_chain(
            response_text="Market text.",
            deep_response_text="DECISION: HOLD\nCONFIDENCE: 0.5\nREASONING: OK.",
            analysts=["market"],
        )
        # Act
        chain.analyse("NIFTY", "NSE_INDEX")
        # Assert — quick called once for market node, deep called once for judge
        assert quick.chat.call_count == 1
        assert deep.chat.call_count == 1


# ---------------------------------------------------------------------------
# Sentiment analyst node
# ---------------------------------------------------------------------------


class TestSentimentAnalyst:
    """Test the sentiment analyst node behaviour."""

    def test_analyze_with_sentiment_analyst_populates_report(self) -> None:
        # Arrange
        expected = "Overall sentiment is bullish driven by FII buying."
        chain, quick, _ = _make_chain(
            response_text=expected,
            analysts=["sentiment"],
        )
        # Act
        state = chain.analyse("NIFTY", "NSE_INDEX")
        # Assert
        assert state.sentiment_report == expected

    def test_memory_context_included_when_available(self) -> None:
        # Arrange — inject a mock TradedMemory that returns one past memory
        from flinttrade_ai.memory import MemoryItem, MemoryLayer, MemoryQueryResult
        from flinttrade_ai.llm_client import LLMResponse
        from flinttrade_ai.analyst_chain import AnalystChain
        from datetime import datetime, timezone

        past_item = MemoryItem(
            id="abc-123",
            symbol="NIFTY",
            text="NIFTY was bearish last week on FII sell-off.",
            layer=MemoryLayer.SHORT,
            importance=65.0,
            recency_delta=3,
            access_count=1,
            timestamp=datetime.now(timezone.utc),
        )
        mock_memory = MagicMock()
        mock_memory.get_memories.return_value = MemoryQueryResult(
            items=[past_item],
            query="sentiment for NIFTY",
            layer=MemoryLayer.SHORT,
        )

        quick = MagicMock()
        quick.chat.return_value = LLMResponse(content="Sentiment report.")
        chain = AnalystChain(
            llm_client=quick,
            memory=mock_memory,
            analysts=["sentiment"],
        )
        # Act
        chain.analyse("NIFTY", "NSE_INDEX")
        # Assert — prompt sent to LLM for the sentiment node (first call) includes
        # the past memory text.  The second call is the judge node.
        all_calls = quick.chat.call_args_list
        sentiment_call_messages = all_calls[0][0][0]  # first call, first positional arg
        user_message = next(m for m in sentiment_call_messages if m.role == "user")
        assert "NIFTY was bearish last week" in user_message.content

    def test_memory_unavailable_does_not_fail(self) -> None:
        # Arrange — memory raises on get_memories
        from flinttrade_ai.analyst_chain import AnalystChain
        from flinttrade_ai.llm_client import LLMResponse

        mock_memory = MagicMock()
        mock_memory.get_memories.side_effect = RuntimeError("ChromaDB unavailable")
        quick = MagicMock()
        quick.chat.return_value = LLMResponse(content="Sentiment fallback.")
        chain = AnalystChain(llm_client=quick, memory=mock_memory, analysts=["sentiment"])
        # Act
        state = chain.analyse("NIFTY", "NSE_INDEX")
        # Assert — error is swallowed inside the node; no top-level error for this
        assert state.sentiment_report == "Sentiment fallback."


# ---------------------------------------------------------------------------
# Judge node — parsing
# ---------------------------------------------------------------------------


class TestJudgeParsing:
    """Test _parse_judge_response for all decision variants."""

    def test_judge_parses_buy_decision(self) -> None:
        # Arrange
        from flinttrade_ai.analyst_chain import AnalystChain

        response = "DECISION: BUY\nCONFIDENCE: 0.85\nREASONING: Strong upside momentum."
        # Act
        decision, confidence, reasoning = AnalystChain._parse_judge_response(response)
        # Assert
        assert decision == "BUY"
        assert confidence == 0.85
        assert "Strong upside momentum" in reasoning

    def test_judge_parses_sell_decision(self) -> None:
        # Arrange
        from flinttrade_ai.analyst_chain import AnalystChain

        response = "DECISION: SELL\nCONFIDENCE: 0.72\nREASONING: Bearish breakdown confirmed."
        # Act
        decision, confidence, reasoning = AnalystChain._parse_judge_response(response)
        # Assert
        assert decision == "SELL"
        assert confidence == 0.72

    def test_judge_parses_hold_on_explicit_hold(self) -> None:
        # Arrange
        from flinttrade_ai.analyst_chain import AnalystChain

        response = "DECISION: HOLD\nCONFIDENCE: 0.5\nREASONING: Mixed signals."
        # Act
        decision, confidence, reasoning = AnalystChain._parse_judge_response(response)
        # Assert
        assert decision == "HOLD"
        assert confidence == 0.5

    def test_judge_parses_hold_on_malformed(self) -> None:
        # Arrange — response doesn't follow the format at all
        from flinttrade_ai.analyst_chain import AnalystChain

        response = "I cannot determine a clear direction at this time."
        # Act
        decision, confidence, reasoning = AnalystChain._parse_judge_response(response)
        # Assert — defaults
        assert decision == "HOLD"
        assert confidence == 0.0
        assert reasoning == response  # falls back to full response text

    def test_judge_parses_hold_on_invalid_decision_value(self) -> None:
        # Arrange — DECISION contains a non-standard value
        from flinttrade_ai.analyst_chain import AnalystChain

        response = "DECISION: MAYBE\nCONFIDENCE: 0.6\nREASONING: Uncertain."
        # Act
        decision, confidence, reasoning = AnalystChain._parse_judge_response(response)
        # Assert — falls back to HOLD because "MAYBE" is not valid
        assert decision == "HOLD"

    def test_confidence_clamped_0_to_1_above(self) -> None:
        # Arrange — model returns a value above 1.0
        from flinttrade_ai.analyst_chain import AnalystChain

        response = "DECISION: BUY\nCONFIDENCE: 1.5\nREASONING: Very confident."
        # Act
        _, confidence, _ = AnalystChain._parse_judge_response(response)
        # Assert
        assert confidence == 1.0

    def test_confidence_clamped_0_to_1_below(self) -> None:
        # Arrange — model returns a negative value
        from flinttrade_ai.analyst_chain import AnalystChain

        response = "DECISION: SELL\nCONFIDENCE: -0.3\nREASONING: Uncertain."
        # Act
        _, confidence, _ = AnalystChain._parse_judge_response(response)
        # Assert
        assert confidence == 0.0

    def test_confidence_invalid_string_defaults_to_zero(self) -> None:
        # Arrange — confidence is not a number
        from flinttrade_ai.analyst_chain import AnalystChain

        response = "DECISION: BUY\nCONFIDENCE: high\nREASONING: Trend is up."
        # Act
        _, confidence, _ = AnalystChain._parse_judge_response(response)
        # Assert
        assert confidence == 0.0


# ---------------------------------------------------------------------------
# Judge via full pipeline
# ---------------------------------------------------------------------------


class TestJudgeViaAnalyze:
    """Test judge integration through the analyze() entrypoint."""

    def test_judge_decision_stored_on_state(self) -> None:
        # Arrange
        judge_text = "DECISION: SELL\nCONFIDENCE: 0.65\nREASONING: Bearish reversal."
        chain, _, _ = _make_chain(
            response_text="Market bearish.",
            deep_response_text=judge_text,
            analysts=["market"],
        )
        # Act
        state = chain.analyse("BANKNIFTY", "NSE_INDEX")
        # Assert
        assert state.final_decision == "SELL"
        assert state.confidence == 0.65
        assert "Bearish reversal" in state.final_reasoning

    def test_judge_uses_deep_llm_not_quick(self) -> None:
        # Arrange — quick and deep return different content
        from flinttrade_ai.llm_client import LLMResponse
        from flinttrade_ai.analyst_chain import AnalystChain

        quick = MagicMock()
        quick.chat.return_value = LLMResponse(content="Quick market analysis.")

        deep = MagicMock()
        deep.chat.return_value = LLMResponse(
            content="DECISION: BUY\nCONFIDENCE: 0.9\nREASONING: Deep analysis says buy."
        )

        chain = AnalystChain(llm_client=quick, deep_llm_client=deep, analysts=["market"])
        # Act
        state = chain.analyse("NIFTY", "NSE_INDEX")
        # Assert — judge used the deep client
        assert deep.chat.called
        assert state.final_decision == "BUY"

    def test_judge_uses_quick_when_no_deep_provided(self) -> None:
        # Arrange — only quick client provided; it serves both analyst and judge
        from flinttrade_ai.llm_client import LLMResponse
        from flinttrade_ai.analyst_chain import AnalystChain

        quick = MagicMock()
        quick.chat.side_effect = [
            LLMResponse(content="Market report text."),
            LLMResponse(content="DECISION: HOLD\nCONFIDENCE: 0.4\nREASONING: No clear signal."),
        ]
        chain = AnalystChain(llm_client=quick, deep_llm_client=None, analysts=["market"])
        # Act
        state = chain.analyse("NIFTY", "NSE_INDEX")
        # Assert — quick was called twice (once per node + once for judge)
        assert quick.chat.call_count == 2
        assert state.final_decision == "HOLD"


# ---------------------------------------------------------------------------
# Error handling
# ---------------------------------------------------------------------------


class TestErrorHandling:
    """Test that analyst errors are captured without aborting the pipeline."""

    def test_analyst_error_captured_in_state(self) -> None:
        # Arrange — quick.chat raises on first call (market node)
        from flinttrade_ai.llm_client import LLMResponse
        from flinttrade_ai.analyst_chain import AnalystChain

        quick = MagicMock()
        quick.chat.side_effect = [
            RuntimeError("LLM timeout"),  # market node fails
            LLMResponse(content="DECISION: HOLD\nCONFIDENCE: 0.3\nREASONING: No data."),
        ]
        chain = AnalystChain(llm_client=quick, analysts=["market"])
        # Act
        state = chain.analyse("NIFTY", "NSE_INDEX")
        # Assert — error recorded, pipeline did not crash
        assert len(state.errors) == 1
        assert "market" in state.errors[0]
        assert "LLM timeout" in state.errors[0]

    def test_unknown_analyst_error_captured(self) -> None:
        # Arrange — analyst list includes a name that doesn't exist
        chain, quick, _ = _make_chain(analysts=["market", "nonexistent"])
        # Act
        state = chain.analyse("NIFTY", "NSE_INDEX")
        # Assert — nonexistent node error is captured
        error_names = [e.split(":")[0] for e in state.errors]
        assert "nonexistent" in error_names

    def test_multiple_analyst_errors_all_captured(self) -> None:
        # Arrange — both market and sentiment nodes fail
        from flinttrade_ai.llm_client import LLMResponse
        from flinttrade_ai.analyst_chain import AnalystChain

        quick = MagicMock()
        quick.chat.side_effect = [
            RuntimeError("Market node down"),
            RuntimeError("Sentiment node down"),
            LLMResponse(content="DECISION: HOLD\nCONFIDENCE: 0.0\nREASONING: No reports."),
        ]
        chain = AnalystChain(llm_client=quick, analysts=["market", "sentiment"])
        # Act
        state = chain.analyse("NIFTY", "NSE_INDEX")
        # Assert — two errors recorded
        assert len(state.errors) == 2

    def test_all_analysts_fail_judge_still_runs(self) -> None:
        # Arrange — market analyst fails; judge must still produce a decision
        from flinttrade_ai.llm_client import LLMResponse
        from flinttrade_ai.analyst_chain import AnalystChain

        quick = MagicMock()
        quick.chat.side_effect = [
            RuntimeError("Market unavailable"),
            LLMResponse(content="DECISION: HOLD\nCONFIDENCE: 0.0\nREASONING: No data available."),
        ]
        chain = AnalystChain(llm_client=quick, analysts=["market"])
        # Act
        state = chain.analyse("NIFTY", "NSE_INDEX")
        # Assert
        assert state.final_decision == "HOLD"
        assert len(state.errors) == 1  # only the market error, judge succeeded


# ---------------------------------------------------------------------------
# AnalystChain construction
# ---------------------------------------------------------------------------


class TestAnalystChainInit:
    """Test AnalystChain constructor behaviour."""

    def test_default_analysts_list(self) -> None:
        # Arrange / Act
        from flinttrade_ai.analyst_chain import AnalystChain

        quick = _make_llm_client()
        chain = AnalystChain(llm_client=quick)
        # Assert
        assert chain._analysts == ["market", "sentiment"]

    def test_deep_llm_falls_back_to_quick_when_none(self) -> None:
        # Arrange / Act
        from flinttrade_ai.analyst_chain import AnalystChain

        quick = _make_llm_client()
        chain = AnalystChain(llm_client=quick, deep_llm_client=None)
        # Assert — _deep is the same object as _quick
        assert chain._deep is quick

    def test_deep_llm_stored_when_provided(self) -> None:
        # Arrange
        from flinttrade_ai.analyst_chain import AnalystChain

        quick = _make_llm_client()
        deep = _make_llm_client()
        # Act
        chain = AnalystChain(llm_client=quick, deep_llm_client=deep)
        # Assert
        assert chain._deep is deep
        assert chain._quick is quick
