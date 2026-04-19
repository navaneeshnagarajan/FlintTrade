"""Tests for packages/ai/src/signal_routes.py (Flask Blueprint).

Covers:
  GET  /api/v1/signals/recent    — happy path + invalid limit
  GET  /api/v1/signals/config    — returns pipeline config
  POST /api/v1/signals/configure — valid / invalid payloads

SSE /stream is not tested here due to its infinite-generator nature.
The pipeline is mocked to avoid streaming indicator dependencies.
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest
from flask import Flask


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_pipeline() -> MagicMock:
    """Build a mock LiveSignalPipeline with the required interface.

    Returns:
        MagicMock with signals deque, get_recent_signals, get_config,
        update_config methods.
    """
    p = MagicMock()
    p.signals = []  # deque-like empty list

    mock_signal = MagicMock()
    mock_signal.to_dict.return_value = {
        "symbol": "NIFTY",
        "signal_type": "BUY",
        "confidence": 0.7,
        "timestamp": "2026-04-19T10:00:00",
    }
    p.get_recent_signals.return_value = [mock_signal]

    mock_config = MagicMock()
    mock_config.to_dict.return_value = {
        "instruments": [],
        "indicators": [],
        "thresholds": {},
    }
    p.get_config.return_value = mock_config
    p.update_config.return_value = mock_config
    return p


# ---------------------------------------------------------------------------
# Fixture
# ---------------------------------------------------------------------------


@pytest.fixture()
def pipeline() -> MagicMock:
    """Return a mock LiveSignalPipeline.

    Returns:
        Configured MagicMock pipeline.
    """
    return _make_pipeline()


@pytest.fixture()
def client(pipeline: MagicMock):
    """Flask test client with signal_bp registered and pipeline injected.

    Args:
        pipeline: Mock pipeline fixture.

    Yields:
        Flask test client with _live_signal_pipeline attached to app.
    """
    from packages.ai.src.signal_routes import signal_bp

    flask_app = Flask(__name__)
    flask_app.config["TESTING"] = True
    flask_app.register_blueprint(signal_bp)

    with flask_app.test_client() as c:
        # Inject mock pipeline; _get_pipeline() will find it on current_app
        with flask_app.app_context():
            flask_app._live_signal_pipeline = pipeline  # type: ignore[attr-defined]
        yield c


# ---------------------------------------------------------------------------
# GET /api/v1/signals/recent
# ---------------------------------------------------------------------------


class TestSignalsRecent:
    def test_returns_signals_list(self, client: MagicMock, pipeline: MagicMock) -> None:
        """Recent signals endpoint returns mocked signals correctly.

        Args:
            client:   Flask test client.
            pipeline: Mock pipeline fixture.
        """
        with patch("packages.ai.src.signal_routes._get_pipeline", return_value=pipeline):
            resp = client.get("/api/v1/signals/recent")
        assert resp.status_code == 200
        data = resp.get_json()
        assert data["status"] == "success"
        assert len(data["data"]["signals"]) == 1
        assert data["data"]["signals"][0]["symbol"] == "NIFTY"

    def test_default_limit_is_20(self, client: MagicMock, pipeline: MagicMock) -> None:
        """Calling without limit parameter passes limit=20 to the pipeline.

        Args:
            client:   Flask test client.
            pipeline: Mock pipeline fixture.
        """
        with patch("packages.ai.src.signal_routes._get_pipeline", return_value=pipeline):
            client.get("/api/v1/signals/recent")
        pipeline.get_recent_signals.assert_called_with(limit=20)

    def test_custom_limit_accepted(self, client: MagicMock, pipeline: MagicMock) -> None:
        """Custom limit parameter is forwarded to get_recent_signals.

        Args:
            client:   Flask test client.
            pipeline: Mock pipeline fixture.
        """
        with patch("packages.ai.src.signal_routes._get_pipeline", return_value=pipeline):
            client.get("/api/v1/signals/recent?limit=5")
        pipeline.get_recent_signals.assert_called_with(limit=5)

    def test_invalid_limit_returns_400(self, client: MagicMock, pipeline: MagicMock) -> None:
        """Non-integer limit returns HTTP 400.

        Args:
            client:   Flask test client.
            pipeline: Mock pipeline fixture.
        """
        with patch("packages.ai.src.signal_routes._get_pipeline", return_value=pipeline):
            resp = client.get("/api/v1/signals/recent?limit=abc")
        assert resp.status_code == 400
        assert resp.get_json()["status"] == "error"


# ---------------------------------------------------------------------------
# GET /api/v1/signals/config
# ---------------------------------------------------------------------------


class TestSignalsConfig:
    def test_returns_current_config(self, client: MagicMock, pipeline: MagicMock) -> None:
        """Config endpoint returns the pipeline's current configuration.

        Args:
            client:   Flask test client.
            pipeline: Mock pipeline fixture.
        """
        with patch("packages.ai.src.signal_routes._get_pipeline", return_value=pipeline):
            resp = client.get("/api/v1/signals/config")
        assert resp.status_code == 200
        data = resp.get_json()
        assert data["status"] == "success"
        assert "instruments" in data["data"]


# ---------------------------------------------------------------------------
# POST /api/v1/signals/configure
# ---------------------------------------------------------------------------


class TestSignalsConfigure:
    def test_update_instruments(self, client: MagicMock, pipeline: MagicMock) -> None:
        """Updating instruments list returns success with updated config.

        Args:
            client:   Flask test client.
            pipeline: Mock pipeline fixture.
        """
        with patch("packages.ai.src.signal_routes._get_pipeline", return_value=pipeline):
            resp = client.post(
                "/api/v1/signals/configure",
                json={"instruments": ["NIFTY", "BANKNIFTY"]},
            )
        assert resp.status_code == 200
        data = resp.get_json()
        assert data["status"] == "success"
        pipeline.update_config.assert_called_once()

    def test_instruments_not_list_returns_400(self, client: MagicMock, pipeline: MagicMock) -> None:
        """Passing instruments as a string (not a list) returns HTTP 400.

        Args:
            client:   Flask test client.
            pipeline: Mock pipeline fixture.
        """
        with patch("packages.ai.src.signal_routes._get_pipeline", return_value=pipeline):
            resp = client.post(
                "/api/v1/signals/configure",
                json={"instruments": "NIFTY"},
            )
        assert resp.status_code == 400
        assert "list" in resp.get_json()["message"]

    def test_thresholds_not_dict_returns_400(self, client: MagicMock, pipeline: MagicMock) -> None:
        """Passing thresholds as a list (not a dict) returns HTTP 400.

        Args:
            client:   Flask test client.
            pipeline: Mock pipeline fixture.
        """
        with patch("packages.ai.src.signal_routes._get_pipeline", return_value=pipeline):
            resp = client.post(
                "/api/v1/signals/configure",
                json={"thresholds": ["wrong", "type"]},
            )
        assert resp.status_code == 400

    def test_empty_body_is_accepted(self, client: MagicMock, pipeline: MagicMock) -> None:
        """Empty body (all fields optional) is accepted and returns success.

        Args:
            client:   Flask test client.
            pipeline: Mock pipeline fixture.
        """
        with patch("packages.ai.src.signal_routes._get_pipeline", return_value=pipeline):
            resp = client.post("/api/v1/signals/configure", json={})
        assert resp.status_code == 200
