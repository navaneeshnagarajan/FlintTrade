"""Tests for packages/services/ai/src/advisor_routes.py (Flask Blueprint).

Covers POST /api/v1/advisor (chat — both messages[] and legacy message),
POST /api/v1/advisor/stream (SSE), and GET /api/v1/advisor/status and
GET /api/v1/signals (stub).

All LLM interactions are mocked so no running LM Studio is required.
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest
from flask import Flask


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_llm_response(success: bool = True, content: str = "NIFTY looks bullish") -> MagicMock:
    """Build a mock LLMResponse.

    Args:
        success: Whether the response is successful.
        content: Text content to return.

    Returns:
        MagicMock representing an LLMResponse.
    """
    r = MagicMock()
    r.success = success
    r.content = content
    r.error = None if success else "provider_error"
    return r


# ---------------------------------------------------------------------------
# Fixture
# ---------------------------------------------------------------------------


@pytest.fixture()
def app():
    """Flask test app with advisor_bp registered and LLM configured.

    Yields:
        Flask application instance.
    """
    from flinttrade_ai.advisor_routes import advisor_bp

    flask_app = Flask(__name__)
    flask_app.config["TESTING"] = True
    flask_app.register_blueprint(advisor_bp)
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
# POST /api/v1/advisor
# ---------------------------------------------------------------------------


class TestAdvisorChat:
    def test_messages_array_happy_path(self, client) -> None:
        """messages[] payload returns 200 with data.response from LLM.

        Args:
            client: Flask test client.
        """
        mock_llm = MagicMock()
        mock_llm.chat.return_value = _make_llm_response(content="Use Iron Condor today")
        with (
            patch("flinttrade_ai.advisor_routes._is_llm_configured", return_value=True),
            patch("flinttrade_ai.advisor_routes.LLMClient", return_value=mock_llm),
        ):
            resp = client.post(
                "/api/v1/advisor",
                json={"messages": [{"role": "user", "content": "What strategy today?"}]},
            )
        assert resp.status_code == 200
        data = resp.get_json()
        assert data["status"] == "success"
        assert data["data"]["response"] == "Use Iron Condor today"

    def test_legacy_message_string_happy_path(self, client) -> None:
        """Legacy message string payload returns 200 with data.response.

        Args:
            client: Flask test client.
        """
        mock_llm = MagicMock()
        mock_llm.chat.return_value = _make_llm_response(content="Go with RSI strategy")
        with (
            patch("flinttrade_ai.advisor_routes._is_llm_configured", return_value=True),
            patch("flinttrade_ai.advisor_routes.LLMClient", return_value=mock_llm),
        ):
            resp = client.post(
                "/api/v1/advisor",
                json={"message": "Give me a strategy"},
            )
        assert resp.status_code == 200
        assert resp.get_json()["data"]["response"] == "Go with RSI strategy"

    def test_llm_not_configured_returns_503(self, client) -> None:
        """Missing LLM configuration returns HTTP 503.

        Args:
            client: Flask test client.
        """
        with patch("flinttrade_ai.advisor_routes._is_llm_configured", return_value=False):
            resp = client.post("/api/v1/advisor", json={"message": "Hello"})
        assert resp.status_code == 503
        assert resp.get_json()["status"] == "error"

    def test_missing_message_and_messages_returns_400(self, client) -> None:
        """Empty payload (no message/messages) returns HTTP 400.

        Args:
            client: Flask test client.
        """
        with patch("flinttrade_ai.advisor_routes._is_llm_configured", return_value=True):
            resp = client.post("/api/v1/advisor", json={})
        assert resp.status_code == 400
        assert resp.get_json()["status"] == "error"

    def test_llm_error_returns_502(self, client) -> None:
        """LLM provider error surfaces as HTTP 502.

        Args:
            client: Flask test client.
        """
        mock_llm = MagicMock()
        mock_llm.chat.return_value = _make_llm_response(success=False)
        with (
            patch("flinttrade_ai.advisor_routes._is_llm_configured", return_value=True),
            patch("flinttrade_ai.advisor_routes.LLMClient", return_value=mock_llm),
        ):
            resp = client.post("/api/v1/advisor", json={"message": "Hello"})
        assert resp.status_code == 502

    def test_context_is_accepted(self, client) -> None:
        """Optional context field is accepted alongside messages.

        Args:
            client: Flask test client.
        """
        mock_llm = MagicMock()
        mock_llm.chat.return_value = _make_llm_response()
        with (
            patch("flinttrade_ai.advisor_routes._is_llm_configured", return_value=True),
            patch("flinttrade_ai.advisor_routes.LLMClient", return_value=mock_llm),
        ):
            resp = client.post(
                "/api/v1/advisor",
                json={
                    "message": "Analyse my portfolio",
                    "context": "Long NIFTY 22000 CE x100",
                },
            )
        assert resp.status_code == 200

    def test_object_context_does_not_500(self, client) -> None:
        """An object context (the help pill sends {route, activeWidget}) must be
        accepted, not 500 on .strip(). Regression for the AITutorPill advisor."""
        mock_llm = MagicMock()
        mock_llm.chat.return_value = _make_llm_response()
        with (
            patch("flinttrade_ai.advisor_routes._is_llm_configured", return_value=True),
            patch("flinttrade_ai.advisor_routes.LLMClient", return_value=mock_llm),
        ):
            resp = client.post(
                "/api/v1/advisor",
                json={
                    "messages": [{"role": "user", "content": "What's my exposure?"}],
                    "context": {"route": "/lab", "activeWidget": "OptionChain"},
                },
            )
        assert resp.status_code == 200
        # the object context is flattened into the system prompt the LLM sees
        conversation = mock_llm.chat.call_args[0][0]
        ctx_msgs = [m for m in conversation if "route: /lab" in getattr(m, "content", "")]
        assert ctx_msgs, "object context should be injected as a system message"


# ---------------------------------------------------------------------------
# GET /api/v1/advisor/status
# ---------------------------------------------------------------------------


class TestAdvisorStatus:
    def test_status_configured(self, client) -> None:
        """Status returns configured=True when LLM config is present.

        Args:
            client: Flask test client.
        """
        mock_cfg = MagicMock()
        mock_cfg.provider = "lmstudio"
        mock_cfg.model = "qwen"
        with (
            patch("flinttrade_ai.advisor_routes._is_llm_configured", return_value=True),
            patch("flinttrade_ai.advisor_routes.LLMConfig") as mock_cls,
        ):
            mock_cls.from_env.return_value = mock_cfg
            resp = client.get("/api/v1/advisor/status")
        assert resp.status_code == 200
        data = resp.get_json()
        assert data["status"] == "success"
        assert data["data"]["configured"] is True

    def test_status_not_configured(self, client) -> None:
        """Status returns configured=False when LLM is not set up.

        Args:
            client: Flask test client.
        """
        with patch("flinttrade_ai.advisor_routes._is_llm_configured", return_value=False):
            resp = client.get("/api/v1/advisor/status")
        assert resp.status_code == 200
        data = resp.get_json()
        assert data["data"]["configured"] is False
        assert data["data"]["provider"] == ""


# ---------------------------------------------------------------------------
# GET /api/v1/signals (stub)
# ---------------------------------------------------------------------------


class TestGetSignalsStub:
    def test_signals_returns_empty_list(self, client) -> None:
        """Signals stub endpoint returns an empty list with status=success.

        Args:
            client: Flask test client.
        """
        resp = client.get("/api/v1/signals")
        assert resp.status_code == 200
        data = resp.get_json()
        assert data["status"] == "success"
        assert data["data"]["signals"] == []
