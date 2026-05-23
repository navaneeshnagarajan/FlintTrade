"""Tests for voice order Flask routes.

All tests use a test Flask app client. No live LLM or broker calls.
"""

from __future__ import annotations

import json
import pytest
from unittest.mock import AsyncMock, MagicMock


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def app():
    """Create a minimal Flask app with the voice blueprint registered."""
    from flask import Flask
    from flinttrade_automation.voice_routes import voice_bp

    application = Flask("test_voice")
    application.config["TESTING"] = True
    application.register_blueprint(voice_bp)
    return application


@pytest.fixture
def mock_bridge():
    """Create a fully mocked VoiceOrderBridge."""
    from flinttrade_automation.voice_order_bridge import (
        VoiceOrderBridge,
        VoiceOrderIntent,
    )

    bridge = MagicMock(spec=VoiceOrderBridge)

    # Default parse response
    default_intent = VoiceOrderIntent(
        action="BUY",
        symbol="RELIANCE",
        exchange="NSE",
        quantity=100,
        order_type="MARKET",
        price=None,
        confidence=0.95,
        raw_text="buy 100 reliance at market",
        warnings=[],
    )
    bridge.parse.return_value = default_intent
    bridge.execute = AsyncMock(return_value={"status": "success", "action": "BUY", "data": {"orderid": "ORD001"}})
    bridge.transcribe_audio.return_value = "buy 100 reliance at market"
    return bridge, default_intent


@pytest.fixture
def client(app, mock_bridge):
    """Test client with bridge injected."""
    from flinttrade_automation.voice_routes import init_voice_routes

    bridge, _ = mock_bridge
    init_voice_routes(bridge)
    with app.test_client() as c:
        yield c


# ---------------------------------------------------------------------------
# POST /api/v1/voice/parse
# ---------------------------------------------------------------------------


class TestVoiceParse:
    """Tests for the /parse endpoint."""

    def test_parse_success(self, client, mock_bridge):
        bridge, intent = mock_bridge
        resp = client.post(
            "/api/v1/voice/parse",
            data=json.dumps({"text": "buy 100 reliance at market"}),
            content_type="application/json",
        )
        assert resp.status_code == 200
        data = resp.get_json()
        assert data["status"] == "success"
        assert data["data"]["action"] == "BUY"
        assert data["data"]["symbol"] == "RELIANCE"
        bridge.parse.assert_called_once_with("buy 100 reliance at market")

    def test_parse_missing_text_returns_400(self, client):
        resp = client.post(
            "/api/v1/voice/parse",
            data=json.dumps({}),
            content_type="application/json",
        )
        assert resp.status_code == 400
        assert "text" in resp.get_json()["message"].lower()

    def test_parse_empty_text_returns_400(self, client):
        resp = client.post(
            "/api/v1/voice/parse",
            data=json.dumps({"text": "  "}),
            content_type="application/json",
        )
        assert resp.status_code == 400

    def test_parse_error_returns_422(self, client, mock_bridge):
        from flinttrade_automation.voice_order_bridge import ParseError

        bridge, _ = mock_bridge
        bridge.parse.side_effect = ParseError("cannot parse this")

        resp = client.post(
            "/api/v1/voice/parse",
            data=json.dumps({"text": "gibberish xyz 999 abc"}),
            content_type="application/json",
        )
        assert resp.status_code == 422
        assert "cannot parse" in resp.get_json()["message"]

    def test_parse_not_initialised_returns_503(self, app):
        """Bridge not injected → 503."""
        import flinttrade_automation.voice_routes as vr
        original = vr._bridge
        try:
            vr._bridge = None
            with app.test_client() as c:
                resp = c.post(
                    "/api/v1/voice/parse",
                    data=json.dumps({"text": "buy 10 tcs"}),
                    content_type="application/json",
                )
            assert resp.status_code == 503
        finally:
            vr._bridge = original


# ---------------------------------------------------------------------------
# POST /api/v1/voice/execute
# ---------------------------------------------------------------------------


class TestVoiceExecute:
    """Tests for the /execute endpoint."""

    def _intent_dict(self, **overrides) -> dict:
        base = {
            "action": "BUY",
            "symbol": "RELIANCE",
            "exchange": "NSE",
            "quantity": 100,
            "order_type": "MARKET",
            "price": None,
            "confidence": 0.95,
            "raw_text": "buy 100 reliance",
            "warnings": [],
        }
        base.update(overrides)
        return base

    def test_execute_success(self, client, mock_bridge):
        bridge, _ = mock_bridge
        resp = client.post(
            "/api/v1/voice/execute",
            data=json.dumps({"intent": self._intent_dict(), "confirm": False}),
            content_type="application/json",
        )
        assert resp.status_code == 200
        data = resp.get_json()
        assert data["status"] == "success"

    def test_execute_pending_approval_returns_202(self, client, mock_bridge):
        from flinttrade_automation.voice_order_bridge import (
            PendingApprovalError,
        )

        bridge, intent = mock_bridge
        bridge.execute = AsyncMock(side_effect=PendingApprovalError(intent))

        resp = client.post(
            "/api/v1/voice/execute",
            data=json.dumps({"intent": self._intent_dict(action="CANCEL"), "confirm": True}),
            content_type="application/json",
        )
        assert resp.status_code == 202
        data = resp.get_json()
        assert data["status"] == "pending"

    def test_execute_missing_intent_returns_400(self, client):
        resp = client.post(
            "/api/v1/voice/execute",
            data=json.dumps({"confirm": False}),
            content_type="application/json",
        )
        assert resp.status_code == 400

    def test_execute_invalid_intent_action_returns_400(self, client):
        resp = client.post(
            "/api/v1/voice/execute",
            data=json.dumps({
                "intent": self._intent_dict(action="TELEPORT"),
                "confirm": False,
            }),
            content_type="application/json",
        )
        assert resp.status_code == 400


# ---------------------------------------------------------------------------
# POST /api/v1/voice/transcribe
# ---------------------------------------------------------------------------


class TestVoiceTranscribe:
    """Tests for the /transcribe endpoint."""

    def test_transcribe_no_file_returns_400(self, client):
        resp = client.post("/api/v1/voice/transcribe")
        assert resp.status_code == 400

    def test_transcribe_unavailable_returns_501(self, client, mock_bridge):
        from io import BytesIO
        from flinttrade_automation.voice_order_bridge import TranscribeUnavailableError

        bridge, _ = mock_bridge
        bridge.transcribe_audio.side_effect = TranscribeUnavailableError(
            "openai-whisper is not installed"
        )

        resp = client.post(
            "/api/v1/voice/transcribe",
            data={"file": (BytesIO(b"fake audio bytes"), "audio.wav", "audio/wav")},
            content_type="multipart/form-data",
        )
        assert resp.status_code == 501
        data = resp.get_json()
        assert "install" in data
