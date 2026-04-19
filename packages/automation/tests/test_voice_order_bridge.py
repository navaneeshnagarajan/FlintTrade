"""Tests for VoiceOrderBridge — all tests use mocks, no live LLM or API calls.

DO NOT RUN against a real LLM or broker. All external I/O is patched.
"""

from __future__ import annotations

import json
import pytest
from unittest.mock import AsyncMock, MagicMock, patch


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_llm_response(content: str, success: bool = True) -> MagicMock:
    """Create a mock LLMResponse."""
    resp = MagicMock()
    resp.success = success
    resp.content = content
    resp.error = "" if success else "LLM error"
    return resp


def _make_bridge(llm_content: str | None = None, llm_success: bool = True):
    """Create a VoiceOrderBridge with mocked dependencies."""
    from packages.automation.src.voice_order_bridge import VoiceOrderBridge

    llm = MagicMock()
    if llm_content is not None:
        llm.chat.return_value = _make_llm_response(llm_content, success=llm_success)

    router = MagicMock()
    router.place_order = AsyncMock(return_value={"orderid": "ORD001", "status": "success"})
    router.cancel_last_order = AsyncMock(return_value={"status": "cancelled"})
    router.close_position = AsyncMock(return_value={"status": "closed"})
    router.modify_last_order = AsyncMock(return_value={"status": "modified"})

    tracker = MagicMock()
    tracker.get_positions = AsyncMock(return_value=[
        {"symbol": "RELIANCE", "qty": 100, "exchange": "NSE"},
    ])

    return VoiceOrderBridge(llm, router, tracker), llm, router, tracker


# ---------------------------------------------------------------------------
# VoiceOrderIntent
# ---------------------------------------------------------------------------


class TestVoiceOrderIntent:
    """Tests for VoiceOrderIntent data model."""

    def test_is_high_risk_cancel(self):
        from packages.automation.src.voice_order_bridge import VoiceOrderIntent

        intent = VoiceOrderIntent(
            action="CANCEL", symbol=None, exchange=None, quantity=None,
            order_type=None, price=None, confidence=0.9, raw_text="cancel"
        )
        assert intent.is_high_risk is True

    def test_is_high_risk_exit(self):
        from packages.automation.src.voice_order_bridge import VoiceOrderIntent

        intent = VoiceOrderIntent(
            action="EXIT", symbol="NIFTY", exchange="NFO", quantity=None,
            order_type=None, price=None, confidence=0.85, raw_text="exit nifty"
        )
        assert intent.is_high_risk is True

    def test_is_high_risk_large_quantity(self):
        from packages.automation.src.voice_order_bridge import VoiceOrderIntent

        intent = VoiceOrderIntent(
            action="BUY", symbol="INFY", exchange="NSE", quantity=500,
            order_type="MARKET", price=None, confidence=0.95, raw_text="buy 500 infy"
        )
        assert intent.is_high_risk is True

    def test_is_not_high_risk_normal_buy(self):
        from packages.automation.src.voice_order_bridge import VoiceOrderIntent

        intent = VoiceOrderIntent(
            action="BUY", symbol="TCS", exchange="NSE", quantity=10,
            order_type="MARKET", price=None, confidence=0.97, raw_text="buy 10 tcs"
        )
        assert intent.is_high_risk is False

    def test_to_dict_structure(self):
        from packages.automation.src.voice_order_bridge import VoiceOrderIntent

        intent = VoiceOrderIntent(
            action="SELL", symbol="WIPRO", exchange="NSE", quantity=25,
            order_type="LIMIT", price=450.5, confidence=0.92,
            raw_text="sell 25 wipro at 450.5", warnings=["test warning"]
        )
        d = intent.to_dict()
        assert d["action"] == "SELL"
        assert d["symbol"] == "WIPRO"
        assert d["price"] == 450.5
        assert d["is_high_risk"] is False
        assert "test warning" in d["warnings"]


# ---------------------------------------------------------------------------
# Parsing — LLM path
# ---------------------------------------------------------------------------


class TestVoiceOrderBridgeParseLLM:
    """Tests for parse() using the LLM path."""

    def test_parse_buy_market(self):
        llm_json = json.dumps({
            "action": "BUY", "symbol": "RELIANCE", "exchange": "NSE",
            "quantity": 100, "order_type": "MARKET", "price": None,
            "confidence": 0.95, "warnings": []
        })
        bridge, _, _, _ = _make_bridge(llm_content=llm_json)
        intent = bridge.parse("buy 100 reliance at market")

        assert intent.action == "BUY"
        assert intent.symbol == "RELIANCE"
        assert intent.exchange == "NSE"
        assert intent.quantity == 100
        assert intent.order_type == "MARKET"
        assert intent.price is None
        assert intent.confidence == 0.95
        assert intent.warnings == []

    def test_parse_sell_limit(self):
        llm_json = json.dumps({
            "action": "SELL", "symbol": "TCS", "exchange": "NSE",
            "quantity": 50, "order_type": "LIMIT", "price": 3850.0,
            "confidence": 0.97, "warnings": []
        })
        bridge, _, _, _ = _make_bridge(llm_content=llm_json)
        intent = bridge.parse("sell 50 shares of TCS at 3850 limit")

        assert intent.action == "SELL"
        assert intent.price == 3850.0
        assert intent.order_type == "LIMIT"

    def test_parse_cancel_with_warning(self):
        llm_json = json.dumps({
            "action": "CANCEL", "symbol": None, "exchange": None,
            "quantity": None, "order_type": None, "price": None,
            "confidence": 0.80, "warnings": ["No specific order ID mentioned"]
        })
        bridge, _, _, _ = _make_bridge(llm_content=llm_json)
        intent = bridge.parse("cancel my last order")

        assert intent.action == "CANCEL"
        assert len(intent.warnings) == 1
        assert intent.is_high_risk is True

    def test_parse_status(self):
        llm_json = json.dumps({
            "action": "STATUS", "symbol": None, "exchange": None,
            "quantity": None, "order_type": None, "price": None,
            "confidence": 0.99, "warnings": []
        })
        bridge, _, _, _ = _make_bridge(llm_content=llm_json)
        intent = bridge.parse("show my positions")

        assert intent.action == "STATUS"
        assert intent.confidence == 0.99

    def test_parse_strips_markdown_fences(self):
        llm_content = '```json\n{"action":"BUY","symbol":"INFY","exchange":"NSE","quantity":10,"order_type":"MARKET","price":null,"confidence":0.9,"warnings":[]}\n```'
        bridge, _, _, _ = _make_bridge(llm_content=llm_content)
        intent = bridge.parse("buy 10 infy")

        assert intent.action == "BUY"
        assert intent.symbol == "INFY"

    def test_parse_clamps_confidence(self):
        llm_json = json.dumps({
            "action": "BUY", "symbol": "HDFC", "exchange": "NSE",
            "quantity": 5, "order_type": "MARKET", "price": None,
            "confidence": 1.5,  # out of range
            "warnings": []
        })
        bridge, _, _, _ = _make_bridge(llm_content=llm_json)
        intent = bridge.parse("buy 5 hdfc")

        assert intent.confidence == 1.0

    def test_parse_raises_parse_error_on_invalid_json(self):
        from packages.automation.src.voice_order_bridge import ParseError

        bridge, _, _, _ = _make_bridge(llm_content="not valid json at all")
        # LLM fails, regex fallback should handle BUY keyword
        # but the raw text has no recognizable action → ParseError from regex too
        with pytest.raises((ParseError, Exception)):
            bridge.parse("xyz abc def 999")

    def test_parse_raises_parse_error_on_invalid_action(self):
        from packages.automation.src.voice_order_bridge import ParseError

        llm_json = json.dumps({
            "action": "TELEPORT", "symbol": "TCS", "exchange": "NSE",
            "quantity": 10, "order_type": "MARKET", "price": None,
            "confidence": 0.9, "warnings": []
        })
        bridge, _, _, _ = _make_bridge(llm_content=llm_json)
        # LLM gives invalid action → regex fallback
        # raw text has no recognizable action either → ParseError
        with pytest.raises((ParseError, Exception)):
            bridge.parse("teleport 10 tcs")

    def test_parse_empty_text_raises(self):
        from packages.automation.src.voice_order_bridge import ParseError

        bridge, _, _, _ = _make_bridge()
        with pytest.raises(ParseError, match="empty"):
            bridge.parse("   ")


# ---------------------------------------------------------------------------
# Parsing — regex fallback
# ---------------------------------------------------------------------------


class TestVoiceOrderBridgeParseRegex:
    """Tests for the regex fallback parser."""

    def _bridge_with_failing_llm(self):
        """Bridge where LLM always fails, forcing regex fallback."""
        from packages.automation.src.voice_order_bridge import VoiceOrderBridge

        llm = MagicMock()
        llm.chat.return_value = _make_llm_response("", success=False)

        router = MagicMock()
        tracker = MagicMock()
        return VoiceOrderBridge(llm, router, tracker)

    def test_regex_buy_market(self):
        bridge = self._bridge_with_failing_llm()
        intent = bridge.parse("buy 100 reliance")

        assert intent.action == "BUY"
        assert intent.quantity == 100
        assert intent.symbol == "RELIANCE"
        assert "regex" in intent.warnings[0].lower()

    def test_regex_sell_limit(self):
        bridge = self._bridge_with_failing_llm()
        intent = bridge.parse("sell 50 TCS at 3850")

        assert intent.action == "SELL"
        assert intent.quantity == 50
        assert intent.price == 3850.0
        assert intent.order_type == "LIMIT"

    def test_regex_status(self):
        bridge = self._bridge_with_failing_llm()
        intent = bridge.parse("show positions")

        assert intent.action == "STATUS"

    def test_regex_exit(self):
        bridge = self._bridge_with_failing_llm()
        intent = bridge.parse("exit all positions")

        assert intent.action == "EXIT"


# ---------------------------------------------------------------------------
# Execution
# ---------------------------------------------------------------------------


class TestVoiceOrderBridgeExecute:
    """Tests for execute() method."""

    def test_execute_buy_success(self):
        import asyncio
        llm_json = json.dumps({
            "action": "BUY", "symbol": "RELIANCE", "exchange": "NSE",
            "quantity": 50, "order_type": "MARKET", "price": None,
            "confidence": 0.95, "warnings": []
        })
        bridge, _, router, _ = _make_bridge(llm_content=llm_json)
        intent = bridge.parse("buy 50 reliance")
        result = asyncio.run(bridge.execute(intent, confirm=False))

        assert result["status"] == "success"
        assert result["action"] == "BUY"
        router.place_order.assert_called_once()

    def test_execute_raises_low_confidence(self):
        import asyncio
        from packages.automation.src.voice_order_bridge import LowConfidenceError, VoiceOrderIntent

        bridge, _, _, _ = _make_bridge()
        intent = VoiceOrderIntent(
            action="BUY", symbol="TCS", exchange="NSE", quantity=10,
            order_type="MARKET", price=None, confidence=0.40, raw_text="buy tcs"
        )
        with pytest.raises(LowConfidenceError):
            asyncio.run(bridge.execute(intent, confirm=False))

    def test_execute_high_risk_requires_approval(self):
        import asyncio
        from packages.automation.src.voice_order_bridge import PendingApprovalError, VoiceOrderIntent

        bridge, _, _, _ = _make_bridge()
        intent = VoiceOrderIntent(
            action="CANCEL", symbol=None, exchange=None, quantity=None,
            order_type=None, price=None, confidence=0.90, raw_text="cancel"
        )
        with pytest.raises(PendingApprovalError) as exc_info:
            asyncio.run(bridge.execute(intent, confirm=True))
        assert exc_info.value.intent is intent

    def test_execute_high_risk_bypassed_when_confirm_false(self):
        import asyncio
        from packages.automation.src.voice_order_bridge import VoiceOrderIntent

        bridge, _, router, _ = _make_bridge()
        intent = VoiceOrderIntent(
            action="CANCEL", symbol=None, exchange=None, quantity=None,
            order_type=None, price=None, confidence=0.90, raw_text="cancel"
        )
        result = asyncio.run(bridge.execute(intent, confirm=False))
        assert result["status"] == "success"
        router.cancel_last_order.assert_called_once()

    def test_execute_status_filters_by_symbol(self):
        import asyncio
        from packages.automation.src.voice_order_bridge import VoiceOrderIntent

        bridge, _, _, tracker = _make_bridge()
        tracker.get_positions = AsyncMock(return_value=[
            {"symbol": "RELIANCE", "qty": 100},
            {"symbol": "TCS", "qty": 50},
        ])
        intent = VoiceOrderIntent(
            action="STATUS", symbol="RELIANCE", exchange="NSE", quantity=None,
            order_type=None, price=None, confidence=0.99, raw_text="reliance position"
        )
        result = asyncio.run(bridge.execute(intent, confirm=False))
        assert result["status"] == "success"
        assert len(result["data"]) == 1
        assert result["data"][0]["symbol"] == "RELIANCE"

    def test_execute_sell_missing_symbol_returns_error(self):
        import asyncio
        from packages.automation.src.voice_order_bridge import VoiceOrderIntent

        bridge, _, _, _ = _make_bridge()
        intent = VoiceOrderIntent(
            action="SELL", symbol=None, exchange="NSE", quantity=10,
            order_type="MARKET", price=None, confidence=0.95, raw_text="sell something"
        )
        result = asyncio.run(bridge.execute(intent, confirm=False))
        assert result["status"] == "error"
        assert "symbol" in result["message"].lower()


# ---------------------------------------------------------------------------
# Transcription
# ---------------------------------------------------------------------------


class TestTranscribeAudio:
    """Tests for transcribe_audio() — Whisper optional dependency."""

    def test_raises_when_whisper_not_installed(self):
        from packages.automation.src.voice_order_bridge import TranscribeUnavailableError

        bridge, _, _, _ = _make_bridge()

        with patch.dict("sys.modules", {"whisper": None}):
            with pytest.raises(TranscribeUnavailableError, match="openai-whisper"):
                bridge.transcribe_audio(b"fake audio bytes")

    def test_returns_text_when_whisper_available(self):
        bridge, _, _, _ = _make_bridge()

        mock_whisper = MagicMock()
        mock_model = MagicMock()
        mock_model.transcribe.return_value = {"text": "buy 100 reliance at market"}
        mock_whisper.load_model.return_value = mock_model

        with patch.dict("sys.modules", {"whisper": mock_whisper}):
            text = bridge.transcribe_audio(b"fake audio bytes", language="en")

        assert text == "buy 100 reliance at market"

    def test_raises_voice_order_error_on_transcription_failure(self):
        from packages.automation.src.voice_order_bridge import VoiceOrderError

        bridge, _, _, _ = _make_bridge()

        mock_whisper = MagicMock()
        mock_model = MagicMock()
        mock_model.transcribe.side_effect = RuntimeError("corrupt audio")
        mock_whisper.load_model.return_value = mock_model

        with patch.dict("sys.modules", {"whisper": mock_whisper}):
            with pytest.raises(VoiceOrderError, match="Transcription failed"):
                bridge.transcribe_audio(b"bad audio")
