"""Tests for POST /api/v1/advisor/stream (SSE streaming endpoint).

The generator is bounded by patching ``LLMClient.chat_stream`` to yield a
finite sequence of tokens then return naturally, which causes the Flask
response generator to reach its ``done`` sentinel and terminate.

All LLM interactions are mocked, so no local inference server is required.
"""

from __future__ import annotations

import json
from typing import Generator
from unittest.mock import MagicMock, patch

import pytest
from flask import Flask


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _finite_stream(tokens: list[str]) -> Generator[str, None, None]:
    """Yield a fixed sequence of tokens then stop.

    Args:
        tokens: Token strings to emit one by one.

    Yields:
        Each token string in order.
    """
    yield from tokens


def _parse_sse(raw: bytes) -> list[dict]:
    """Parse raw SSE bytes into a list of decoded JSON payloads.

    Args:
        raw: Raw response bytes from the test client.

    Returns:
        List of dicts decoded from each ``data: ...`` line.
    """
    events: list[dict] = []
    for line in raw.decode("utf-8").splitlines():
        if line.startswith("data: "):
            events.append(json.loads(line[6:]))
    return events


# ---------------------------------------------------------------------------
# Fixture
# ---------------------------------------------------------------------------


@pytest.fixture()
def app() -> Flask:
    """Flask test app with advisor_bp registered.

    Returns:
        Flask application instance.
    """
    from flinttrade_ai.advisor_routes import advisor_bp

    flask_app = Flask(__name__)
    flask_app.config["TESTING"] = True
    flask_app.register_blueprint(advisor_bp)
    return flask_app


@pytest.fixture()
def client(app: Flask):
    """Flask test client.

    Args:
        app: Flask application fixture.

    Returns:
        Test client.
    """
    return app.test_client()


# ---------------------------------------------------------------------------
# POST /api/v1/advisor/stream
# ---------------------------------------------------------------------------


class TestAdvisorStream:
    def test_happy_path_tokens_in_sse_format(self, client) -> None:
        """Tokens arrive as ``data: {"token": "..."}`` SSE lines in order.

        The generator is bounded by returning three tokens from chat_stream
        then naturally exhausting the iterator.

        Args:
            client: Flask test client.
        """
        tokens = ["Hello", " ", "world"]
        mock_llm = MagicMock()
        mock_llm.chat_stream.return_value = _finite_stream(tokens)

        with (
            patch("flinttrade_ai.advisor_routes._is_llm_configured", return_value=True),
            patch("flinttrade_ai.advisor_routes.LLMClient", return_value=mock_llm),
        ):
            resp = client.post(
                "/api/v1/advisor/stream",
                json={"message": "What is the trend for NIFTY?"},
            )

        assert resp.status_code == 200
        assert "text/event-stream" in resp.content_type

        events = _parse_sse(resp.data)
        # First three events carry tokens
        token_events = [e for e in events if "token" in e]
        assert [e["token"] for e in token_events] == tokens

    def test_done_marker_appears_last(self, client) -> None:
        """Final SSE event must carry ``done: true`` after all token events.

        Args:
            client: Flask test client.
        """
        mock_llm = MagicMock()
        mock_llm.chat_stream.return_value = _finite_stream(["Hi"])

        with (
            patch("flinttrade_ai.advisor_routes._is_llm_configured", return_value=True),
            patch("flinttrade_ai.advisor_routes.LLMClient", return_value=mock_llm),
        ):
            resp = client.post(
                "/api/v1/advisor/stream",
                json={"message": "Hello"},
            )

        events = _parse_sse(resp.data)
        assert events, "Expected at least one SSE event"
        assert events[-1].get("done") is True, "Last event must be {done: true}"

    def test_missing_message_returns_400(self, client) -> None:
        """Empty payload (no message or messages) must return HTTP 400 before streaming.

        Args:
            client: Flask test client.
        """
        with patch("flinttrade_ai.advisor_routes._is_llm_configured", return_value=True):
            resp = client.post("/api/v1/advisor/stream", json={})

        assert resp.status_code == 400
        body = resp.get_json()
        assert body["status"] == "error"
        assert "required" in body["message"].lower()

    def test_llm_not_configured_returns_503(self, client) -> None:
        """Missing LLM configuration must return HTTP 503 before streaming.

        Args:
            client: Flask test client.
        """
        with patch("flinttrade_ai.advisor_routes._is_llm_configured", return_value=False):
            resp = client.post("/api/v1/advisor/stream", json={"message": "Hello"})

        assert resp.status_code == 503
        body = resp.get_json()
        assert body["status"] == "error"

    def test_exception_mid_stream_yields_error_event(self, client) -> None:
        """An exception raised during streaming must emit an error SSE event.

        The generator is bounded by raising mid-way through the first token.

        Args:
            client: Flask test client.
        """
        def _failing_stream():
            raise RuntimeError("LLM connection dropped")
            yield  # make it a generator

        mock_llm = MagicMock()
        mock_llm.chat_stream.side_effect = RuntimeError("LLM connection dropped")

        with (
            patch("flinttrade_ai.advisor_routes._is_llm_configured", return_value=True),
            patch("flinttrade_ai.advisor_routes.LLMClient", return_value=mock_llm),
        ):
            resp = client.post(
                "/api/v1/advisor/stream",
                json={"message": "Crash me"},
            )

        # The response itself is 200 (streaming started) but contains an error event
        assert resp.status_code == 200
        events = _parse_sse(resp.data)
        assert any("error" in e for e in events), (
            "Expected at least one SSE event with an 'error' key"
        )

    def test_messages_array_accepted_in_stream(self, client) -> None:
        """Conversation-history ``messages[]`` payload works for the stream endpoint.

        Args:
            client: Flask test client.
        """
        mock_llm = MagicMock()
        mock_llm.chat_stream.return_value = _finite_stream(["OK"])

        with (
            patch("flinttrade_ai.advisor_routes._is_llm_configured", return_value=True),
            patch("flinttrade_ai.advisor_routes.LLMClient", return_value=mock_llm),
        ):
            resp = client.post(
                "/api/v1/advisor/stream",
                json={
                    "messages": [
                        {"role": "user", "content": "Analyse BANKNIFTY options"},
                    ]
                },
            )

        assert resp.status_code == 200
        events = _parse_sse(resp.data)
        assert any(e.get("token") == "OK" for e in events)

    def test_empty_token_stream_still_emits_done(self, client) -> None:
        """Zero-token stream (LLM returns nothing) must still emit the done event.

        Args:
            client: Flask test client.
        """
        mock_llm = MagicMock()
        mock_llm.chat_stream.return_value = _finite_stream([])

        with (
            patch("flinttrade_ai.advisor_routes._is_llm_configured", return_value=True),
            patch("flinttrade_ai.advisor_routes.LLMClient", return_value=mock_llm),
        ):
            resp = client.post(
                "/api/v1/advisor/stream",
                json={"message": "Silent response"},
            )

        events = _parse_sse(resp.data)
        assert events[-1].get("done") is True
