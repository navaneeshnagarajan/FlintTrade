"""Tests for GET /api/v1/signals/stream (SSE live-signals endpoint).

The ``_sse_generator`` is an infinite ``while True`` loop.  It is bounded in
tests by replacing it entirely with a finite generator that yields a fixed
set of pre-built SSE lines then returns.  This avoids the PEP 479 trap
(``StopIteration`` inside a generator becomes ``RuntimeError`` in Python 3.7+)
and keeps tests fast — no real sleeping.

All pipeline interactions are mocked — no live signal feed is required.
"""

from __future__ import annotations

import json
from collections import deque
from typing import Callable, Generator
from unittest.mock import MagicMock, patch

import pytest
from flask import Flask


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_mock_signal(symbol: str = "NIFTY") -> MagicMock:
    """Build a mock Signal with a ``to_dict`` method.

    Args:
        symbol: Instrument symbol to embed in the signal dict.

    Returns:
        MagicMock representing a Signal instance.
    """
    sig = MagicMock()
    sig.to_dict.return_value = {
        "symbol": symbol,
        "signal_type": "BUY",
        "confidence": 0.85,
        "timestamp": "2026-04-19T09:15:00",
    }
    return sig


def _make_pipeline(signals: list | None = None) -> MagicMock:
    """Build a mock LiveSignalPipeline.

    Args:
        signals: Pre-populated list of Signal mocks to expose via ``.signals``.

    Returns:
        MagicMock mimicking a LiveSignalPipeline.
    """
    pipeline = MagicMock()
    pipeline.signals = deque(signals or [], maxlen=100)
    return pipeline


def _parse_sse(raw: bytes) -> list[dict]:
    """Decode raw SSE bytes into a list of JSON payload dicts.

    Comment lines (starting with ``:``) are skipped.

    Args:
        raw: Raw response bytes from the Flask test client.

    Returns:
        List of decoded event payload dicts.
    """
    events: list[dict] = []
    for line in raw.decode("utf-8").splitlines():
        if line.startswith("data: "):
            try:
                events.append(json.loads(line[6:]))
            except json.JSONDecodeError:
                pass
    return events


def _finite_sse_generator(events: list[str]):
    """Return a generator factory that yields pre-built SSE lines then stops.

    This replaces ``_sse_generator`` in tests, bounding the otherwise-infinite
    loop to exactly ``len(events)`` yields.

    Args:
        events: Pre-formatted SSE strings to yield (e.g. ``"data: {...}\\n\\n"``).

    Returns:
        A callable matching the signature of ``_sse_generator(pipeline)``.
    """

    def _gen(_pipeline) -> Generator[str, None, None]:  # noqa: ANN001
        yield from events

    return _gen


def _signal_sse_line(symbol: str, exchange: str = "NSE_INDEX") -> str:
    """Build a single SSE data line for a signal.

    Args:
        symbol: Instrument symbol to embed.

    Returns:
        SSE-formatted string ready to be yielded by a generator.
    """
    payload = json.dumps(
        {
            "symbol": symbol,
            "exchange": exchange,
            "signal_type": "BUY",
            "confidence": 0.85,
            "timestamp": "2026-04-19T09:15:00",
        }
    )
    return f"data: {payload}\n\n"


# ---------------------------------------------------------------------------
# Fixture
# ---------------------------------------------------------------------------


@pytest.fixture()
def app() -> Flask:
    """Flask test app with signal_bp registered.

    Returns:
        Flask application instance.
    """
    from flinttrade_ai.signal_routes import signal_bp

    flask_app = Flask(__name__)
    flask_app.config["TESTING"] = True
    flask_app.register_blueprint(signal_bp)
    return flask_app


# ---------------------------------------------------------------------------
# GET /api/v1/signals/stream
# ---------------------------------------------------------------------------


class TestSignalsStream:
    def test_happy_path_emits_signal_events(self, app: Flask) -> None:
        """Signals are emitted as SSE data events in correct JSON shape.

        Two pre-built SSE lines are yielded by the bounded generator.
        Both symbols must appear in the parsed events.

        Args:
            app: Flask application fixture.
        """
        sse_lines = [
            _signal_sse_line("NIFTY"),
            _signal_sse_line("BANKNIFTY"),
        ]
        pipeline = _make_pipeline()

        with app.test_client() as client:
            with patch("flinttrade_ai.signal_routes._get_pipeline", return_value=pipeline):
                with patch(
                    "flinttrade_ai.signal_routes._sse_generator",
                    side_effect=_finite_sse_generator(sse_lines),
                ):
                    resp = client.get("/api/v1/signals/stream")

        assert resp.status_code == 200
        assert "text/event-stream" in resp.content_type

        events = _parse_sse(resp.data)
        symbols = {e["symbol"] for e in events if "symbol" in e}
        assert "NIFTY" in symbols
        assert "BANKNIFTY" in symbols

    def test_empty_pipeline_produces_no_data_events(self, app: Flask) -> None:
        """An empty signal deque results in a stream with no data events.

        The bounded generator yields nothing, so the response body should
        contain no parseable SSE payloads.

        Args:
            app: Flask application fixture.
        """
        pipeline = _make_pipeline([])

        with app.test_client() as client:
            with patch("flinttrade_ai.signal_routes._get_pipeline", return_value=pipeline):
                with patch(
                    "flinttrade_ai.signal_routes._sse_generator",
                    side_effect=_finite_sse_generator([]),
                ):
                    resp = client.get("/api/v1/signals/stream")

        assert resp.status_code == 200
        events = _parse_sse(resp.data)
        assert events == [], f"Expected no data events for empty pipeline, got {events}"

    def test_response_headers_set_correctly(self, app: Flask) -> None:
        """Cache-Control and X-Accel-Buffering headers must be present on the stream response.

        Args:
            app: Flask application fixture.
        """
        pipeline = _make_pipeline([])

        with app.test_client() as client:
            with patch("flinttrade_ai.signal_routes._get_pipeline", return_value=pipeline):
                with patch(
                    "flinttrade_ai.signal_routes._sse_generator",
                    side_effect=_finite_sse_generator([]),
                ):
                    resp = client.get("/api/v1/signals/stream")

        assert resp.headers.get("Cache-Control") == "no-cache"
        assert resp.headers.get("X-Accel-Buffering") == "no"

    def test_route_passes_context_free_auth_revalidator_to_stream(self, app: Flask) -> None:
        auth_revalidator = MagicMock(return_value=True)
        captured: dict[str, object] = {}

        def finite_stream(
            _pipeline: object,
            *,
            auth_revalidator: object,
        ) -> Generator[str, None, None]:
            captured["auth_revalidator"] = auth_revalidator
            yield ": heartbeat\n\n"

        with app.test_client() as client:
            with patch("flinttrade_ai.signal_routes._get_pipeline", return_value=_make_pipeline([])):
                with patch(
                    "flinttrade_ai.signal_routes._request_stream_auth_revalidator",
                    return_value=auth_revalidator,
                ):
                    with patch("flinttrade_ai.signal_routes._sse_generator", side_effect=finite_stream):
                        response = client.get("/api/v1/signals/stream")

        assert response.status_code == 200
        assert captured["auth_revalidator"] is auth_revalidator

    def test_active_stream_stops_when_auth_revalidation_fails(self) -> None:
        from flinttrade_ai.signal_pipeline import LiveSignalPipeline
        from flinttrade_ai.signal_routes import _sse_generator

        authorised = True
        stream = _sse_generator(
            LiveSignalPipeline(instruments=[]),
            heartbeat_interval=0.0,
            auth_revalidator=lambda: authorised,
        )

        assert next(stream) == ": heartbeat\n\n"
        authorised = False

        with pytest.raises(StopIteration):
            next(stream)

    def test_stream_session_revalidator_checks_expiry_revocation_and_password_change(self) -> None:
        from flinttrade_ai.signal_routes import StreamSessionClaims, _build_stream_auth_revalidator

        now = [150.0]
        revoked = [False]
        password_changed_at = [0.0]
        claims = StreamSessionClaims(
            jti="session-jti",
            issued_at=100.0,
            expires_at=200.0,
        )

        def build() -> Callable[[], bool]:
            return _build_stream_auth_revalidator(
                claims,
                is_jti_revoked=lambda _jti: revoked[0],
                password_changed_at=lambda: password_changed_at[0],
                clock=lambda: now[0],
            )

        validate = build()
        assert validate() is True

        revoked[0] = True
        assert build()() is False
        revoked[0] = False
        password_changed_at[0] = 103.0
        assert build()() is False
        password_changed_at[0] = 0.0
        now[0] = 200.0
        assert build()() is False
        now[0] = float("nan")
        assert build()() is False
        now[0] = 150.0
        password_changed_at[0] = float("nan")
        assert build()() is False

    def test_request_revalidator_survives_context_teardown_without_retaining_bearer(self, app: Flask) -> None:
        from flinttrade_ai.signal_routes import _request_stream_auth_revalidator

        bearer = "header.payload.signature-secret"
        revoked = [False]
        auth_service = MagicMock()
        auth_service.get_password_changed_at.return_value = 0.0
        app.config["AUTH_SERVICE"] = auth_service

        with app.test_request_context(
            "/api/v1/signals/stream",
            headers={"Authorization": f"Bearer {bearer}"},
        ):
            with patch(
                "flinttrade_core.auth_routes.decode_token",
                return_value={
                    "type": "session",
                    "jti": "session-jti",
                    "iat": 100.0,
                    "exp": 1_000_000_000_000.0,
                },
            ):
                with patch(
                    "flinttrade_core.auth_routes._is_jti_revoked",
                    side_effect=lambda _jti: revoked[0],
                ):
                    revalidator = _request_stream_auth_revalidator()

        assert revalidator is not None
        closure_values = [cell.cell_contents for cell in (revalidator.__closure__ or ())]
        assert all(bearer not in repr(value) for value in closure_values)
        assert revalidator() is True
        revoked[0] = True
        assert revalidator() is False

    def test_decode_failure_only_preserves_the_configured_api_key_bearer(
        self,
        app: Flask,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        from flinttrade_ai.signal_routes import _request_stream_auth_revalidator

        monkeypatch.setenv("FLINTTRADE_API_KEY", "configured-api-key")
        with patch(
            "flinttrade_core.auth_routes.decode_token",
            side_effect=ValueError("revoked between admission and stream setup"),
        ):
            with app.test_request_context(
                "/api/v1/signals/stream",
                headers={"Authorization": "Bearer revoked-session-token"},
            ):
                revoked_session = _request_stream_auth_revalidator()
            with app.test_request_context(
                "/api/v1/signals/stream",
                headers={"Authorization": "Bearer configured-api-key"},
            ):
                api_key = _request_stream_auth_revalidator()

        assert revoked_session is not None
        assert revoked_session() is False
        assert api_key is None

    def test_multiple_signals_order_preserved(self, app: Flask) -> None:
        """Events arrive in the order they are emitted by the generator.

        Three signals for different instruments are pre-built.  The events
        list must preserve insertion order so the frontend can rely on it.

        Args:
            app: Flask application fixture.
        """
        instruments = ["NIFTY", "BANKNIFTY", "FINNIFTY"]
        sse_lines = [_signal_sse_line(sym) for sym in instruments]
        pipeline = _make_pipeline()

        with app.test_client() as client:
            with patch("flinttrade_ai.signal_routes._get_pipeline", return_value=pipeline):
                with patch(
                    "flinttrade_ai.signal_routes._sse_generator",
                    side_effect=_finite_sse_generator(sse_lines),
                ):
                    resp = client.get("/api/v1/signals/stream")

        events = _parse_sse(resp.data)
        received_symbols = [e["symbol"] for e in events if "symbol" in e]
        assert received_symbols == instruments

    def test_sse_event_shape_matches_signal_schema(self, app: Flask) -> None:
        """Each SSE data payload must include symbol, signal_type, confidence, timestamp.

        Args:
            app: Flask application fixture.
        """
        sse_lines = [_signal_sse_line("MIDCPNIFTY")]
        pipeline = _make_pipeline()

        with app.test_client() as client:
            with patch("flinttrade_ai.signal_routes._get_pipeline", return_value=pipeline):
                with patch(
                    "flinttrade_ai.signal_routes._sse_generator",
                    side_effect=_finite_sse_generator(sse_lines),
                ):
                    resp = client.get("/api/v1/signals/stream")

        events = _parse_sse(resp.data)
        assert len(events) == 1
        event = events[0]
        for field in ("symbol", "signal_type", "confidence", "timestamp"):
            assert field in event, f"Missing field '{field}' in SSE payload: {event}"
        assert event["symbol"] == "MIDCPNIFTY"
        assert isinstance(event["confidence"], float)

    def test_sse_payloads_preserve_exchange_qualified_identities(self, app: Flask) -> None:
        sse_lines = [
            _signal_sse_line("RELIANCE", "NSE"),
            _signal_sse_line("RELIANCE", "BSE"),
        ]
        pipeline = _make_pipeline()

        with app.test_client() as client:
            with patch("flinttrade_ai.signal_routes._get_pipeline", return_value=pipeline):
                with patch(
                    "flinttrade_ai.signal_routes._sse_generator",
                    side_effect=_finite_sse_generator(sse_lines),
                ):
                    response = client.get("/api/v1/signals/stream")

        assert [(event["exchange"], event["symbol"]) for event in _parse_sse(response.data)] == [
            ("NSE", "RELIANCE"),
            ("BSE", "RELIANCE"),
        ]
