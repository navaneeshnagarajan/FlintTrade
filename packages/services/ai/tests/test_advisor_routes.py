"""Tests for packages/services/ai/src/advisor_routes.py (Flask Blueprint).

Covers POST /api/v1/advisor (chat — both messages[] and legacy message),
POST /api/v1/advisor/stream (SSE), and GET /api/v1/advisor/status.

All LLM interactions are mocked, so no local inference server is required.
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

    def test_llm_provider_body_is_never_returned_by_the_advisor(self, client) -> None:
        """Provider response bodies remain outside the public API error."""
        from flinttrade_ai.llm_client import LLMClient, LLMConfig

        secret = "provider-response-credential"
        upstream_request_id = "key-substring-key"
        correlation_id = "srv_advisor_01234567"
        llm_client = LLMClient(LLMConfig(provider="openai", model="m", api_key="key"))
        llm_client._http.post = MagicMock(
            return_value=MagicMock(
                status_code=401,
                text=f"upstream echoed Bearer {secret}",
                headers={"x-request-id": upstream_request_id},
            )
        )
        with (
            patch("flinttrade_ai.advisor_routes._is_llm_configured", return_value=True),
            patch("flinttrade_ai.advisor_routes.LLMClient", return_value=llm_client),
            patch("flinttrade_ai.llm_client._new_correlation_id", return_value=correlation_id),
        ):
            resp = client.post("/api/v1/advisor", json={"message": "Hello"})

        body = resp.get_json()
        assert resp.status_code == 502
        assert body["message"] == f"LLM error: HTTP 401 (correlation_id={correlation_id})"
        assert secret not in str(body)
        assert upstream_request_id not in str(body)
        assert "upstream echoed" not in str(body)

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
        mock_cfg.provider = "ollama"
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

    def test_empty_ollama_default_is_not_configured(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Blank stored provider plus no LLM_PROVIDER is not configured."""
        from flinttrade_ai.advisor_routes import _is_llm_configured, _llm_readiness_source

        monkeypatch.delenv("LLM_PROVIDER", raising=False)
        monkeypatch.setattr(
            "flinttrade_ai.advisor_routes.read_llm_config",
            lambda: {"provider": ""},
            raising=False,
        )
        with patch(
            "flinttrade_core.llm_config.read_llm_config",
            return_value={"provider": ""},
        ):
            assert _llm_readiness_source() == "default"
            assert _is_llm_configured() is False

    def test_env_only_llm_provider_is_configured(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """LLM_PROVIDER env-only setup is an explicit configured source."""
        from flinttrade_ai.advisor_routes import _is_llm_configured, _llm_readiness_source

        monkeypatch.setenv("LLM_PROVIDER", "openai")
        assert _llm_readiness_source() == "env"
        assert _is_llm_configured() is True


# ---------------------------------------------------------------------------
# FT-MONDAY-001 — Practice SandboxEngine book for AI
# ---------------------------------------------------------------------------


class TestAdvisorPracticeSandboxBook:
    """AI chat can read Practice fills; Live/Explore do not get that book."""

    @pytest.fixture()
    def practice_app(self, tmp_path):
        """Advisor app with a real SandboxEngine that already has one fill."""
        from flinttrade_ai.advisor_routes import advisor_bp
        from flinttrade_data.sandbox_engine import SandboxEngine

        flask_app = Flask(__name__)
        flask_app.config["TESTING"] = True
        engine = SandboxEngine(db_path=str(tmp_path / "advisor-sandbox.sqlite3"))
        result = engine.place_order(
            symbol="NIFTY",
            exchange="NSE",
            action="BUY",
            quantity=1,
            price=100.0,
            product="MIS",
            order_type="MARKET",
        )
        assert result["status"] == "COMPLETE"
        flask_app.config["DATA_SANDBOX_ENGINE"] = engine
        flask_app.register_blueprint(advisor_bp)
        return flask_app

    @staticmethod
    def _headers(mode: str) -> dict[str, str]:
        from flinttrade_core.auth_routes import _create_token

        token = _create_token("ft-monday-001-ai", mode=mode, live_mode_unlocked=False)
        return {
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
        }

    def test_practice_jwt_injects_sandbox_fills_into_llm_context(self, practice_app) -> None:
        """A Practice JWT lets the advisor read the SandboxEngine book."""
        mock_llm = MagicMock()
        mock_llm.chat.return_value = _make_llm_response(content="Practice book received")
        client = practice_app.test_client()
        with (
            patch("flinttrade_ai.advisor_routes._is_llm_configured", return_value=True),
            patch("flinttrade_ai.advisor_routes.LLMClient", return_value=mock_llm),
        ):
            resp = client.post(
                "/api/v1/advisor",
                json={"messages": [{"role": "user", "content": "What did I fill?"}]},
                headers=self._headers("practice"),
            )
        assert resp.status_code == 200
        conversation = mock_llm.chat.call_args[0][0]
        book_msgs = [
            message
            for message in conversation
            if "Practice SandboxEngine book" in getattr(message, "content", "")
        ]
        assert book_msgs, "Practice fills must be visible to the advisor"
        assert "NIFTY" in book_msgs[0].content

    def test_live_jwt_does_not_inject_practice_sandbox_book(self, practice_app) -> None:
        """Live AI-on-broker reads are FT-MONDAY-003 — not injected here."""
        mock_llm = MagicMock()
        mock_llm.chat.return_value = _make_llm_response()
        client = practice_app.test_client()
        with (
            patch("flinttrade_ai.advisor_routes._is_llm_configured", return_value=True),
            patch("flinttrade_ai.advisor_routes.LLMClient", return_value=mock_llm),
        ):
            resp = client.post(
                "/api/v1/advisor",
                json={"messages": [{"role": "user", "content": "What did I fill?"}]},
                headers=self._headers("live"),
            )
        assert resp.status_code == 200
        conversation = mock_llm.chat.call_args[0][0]
        assert all(
            "Practice SandboxEngine book" not in getattr(message, "content", "")
            for message in conversation
        )
