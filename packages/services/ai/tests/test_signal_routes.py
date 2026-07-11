"""Tests for packages/services/ai/src/signal_routes.py (Flask Blueprint).

Covers:
  GET  /api/v1/signals/recent    — happy path + invalid limit
  GET  /api/v1/signals/config    — returns pipeline config
  POST /api/v1/signals/configure — valid / invalid payloads

SSE /stream is not tested here due to its infinite-generator nature.
The pipeline is mocked to avoid streaming indicator dependencies.
"""

from __future__ import annotations

import math
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
    p.stream_id = "test-stream-id"

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


class _TrackingLock:
    """Minimal context lock that exposes whether the critical section is active."""

    def __init__(self) -> None:
        self.held = False
        self.entries = 0

    def __enter__(self) -> _TrackingLock:
        assert not self.held
        self.held = True
        self.entries += 1
        return self

    def __exit__(self, *_args: object) -> None:
        self.held = False


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
    from flinttrade_ai.signal_routes import signal_bp

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
        with patch("flinttrade_ai.signal_routes._get_pipeline", return_value=pipeline):
            resp = client.get("/api/v1/signals/recent")
        assert resp.status_code == 200
        data = resp.get_json()
        assert data["status"] == "success"
        assert len(data["data"]["signals"]) == 1
        assert data["data"]["signals"][0]["symbol"] == "NIFTY"

    def test_returns_pipeline_stream_id_for_sse_cursor_namespacing(
        self,
        client: MagicMock,
        pipeline: MagicMock,
    ) -> None:
        with patch("flinttrade_ai.signal_routes._get_pipeline", return_value=pipeline):
            response = client.get("/api/v1/signals/recent")

        assert response.status_code == 200
        assert response.get_json()["data"]["stream_id"] == "test-stream-id"

    def test_default_limit_is_20(self, client: MagicMock, pipeline: MagicMock) -> None:
        """Calling without limit parameter passes limit=20 to the pipeline.

        Args:
            client:   Flask test client.
            pipeline: Mock pipeline fixture.
        """
        with patch("flinttrade_ai.signal_routes._get_pipeline", return_value=pipeline):
            client.get("/api/v1/signals/recent")
        pipeline.get_recent_signals.assert_called_with(limit=20)

    def test_custom_limit_accepted(self, client: MagicMock, pipeline: MagicMock) -> None:
        """Custom limit parameter is forwarded to get_recent_signals.

        Args:
            client:   Flask test client.
            pipeline: Mock pipeline fixture.
        """
        with patch("flinttrade_ai.signal_routes._get_pipeline", return_value=pipeline):
            client.get("/api/v1/signals/recent?limit=5")
        pipeline.get_recent_signals.assert_called_with(limit=5)

    def test_invalid_limit_returns_400(self, client: MagicMock, pipeline: MagicMock) -> None:
        """Non-integer limit returns HTTP 400.

        Args:
            client:   Flask test client.
            pipeline: Mock pipeline fixture.
        """
        with patch("flinttrade_ai.signal_routes._get_pipeline", return_value=pipeline):
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
        with patch("flinttrade_ai.signal_routes._get_pipeline", return_value=pipeline):
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
        with patch("flinttrade_ai.signal_routes._get_pipeline", return_value=pipeline):
            resp = client.post(
                "/api/v1/signals/configure",
                json={"instruments": ["NSE_INDEX:NIFTY", "NSE_INDEX:BANKNIFTY"]},
            )
        assert resp.status_code == 200
        data = resp.get_json()
        assert data["status"] == "success"
        pipeline.update_config.assert_called_once()

    def test_unqualified_instrument_returns_400(self, client: MagicMock, pipeline: MagicMock) -> None:
        with patch("flinttrade_ai.signal_routes._get_pipeline", return_value=pipeline):
            resp = client.post("/api/v1/signals/configure", json={"instruments": ["RELIANCE"]})

        assert resp.status_code == 400
        assert "EXCHANGE:SYMBOL" in resp.get_json()["message"]
        pipeline.update_config.assert_not_called()

    @pytest.mark.parametrize(
        "identity",
        ["NSE:REL:IANCE", "N SE:RELIANCE", "NSE:REL IANCE", " NSE:RELIANCE", 123, None],
    )
    def test_invalid_instrument_identity_returns_400(
        self,
        client: MagicMock,
        pipeline: MagicMock,
        identity: object,
    ) -> None:
        with patch("flinttrade_ai.signal_routes._get_pipeline", return_value=pipeline):
            resp = client.post("/api/v1/signals/configure", json={"instruments": [identity]})

        assert resp.status_code == 400
        assert "EXCHANGE:SYMBOL" in resp.get_json()["message"]
        pipeline.update_config.assert_not_called()

    def test_empty_instrument_list_disables_all_rule_ticks(self, client: MagicMock, pipeline: MagicMock) -> None:
        with patch("flinttrade_ai.signal_routes._get_pipeline", return_value=pipeline):
            resp = client.post("/api/v1/signals/configure", json={"instruments": []})

        assert resp.status_code == 200
        pipeline.update_config.assert_called_once_with(instruments=[], indicators=None, thresholds=None)

    def test_recorder_watchlist_mismatch_returns_409(self, client: MagicMock, pipeline: MagicMock) -> None:
        recorder = MagicMock()
        recorder.subscription_lock = _TrackingLock()
        recorder.get_watchlist.return_value = {
            "ltp": [],
            "quote": [{"exchange": "NSE", "symbol": "RELIANCE"}],
            "depth": [],
        }
        client.application.config["TICK_RECORDER"] = recorder

        with patch("flinttrade_ai.signal_routes._get_pipeline", return_value=pipeline):
            response = client.post(
                "/api/v1/signals/configure",
                json={"instruments": ["NSE:TCS"]},
            )

        assert response.status_code == 409
        assert "/api/v1/data/ticks/watchlist" in response.get_json()["message"]
        pipeline.update_config.assert_not_called()

    def test_matching_recorder_watchlist_updates_under_shared_lock(
        self,
        client: MagicMock,
        pipeline: MagicMock,
    ) -> None:
        lifecycle_lock = _TrackingLock()
        lock = _TrackingLock()
        recorder = MagicMock()
        recorder.subscription_lock = lock
        recorder.get_watchlist.return_value = {
            "ltp": [{"exchange": "NSE", "symbol": "RELIANCE"}],
            "quote": [{"exchange": "BSE", "symbol": "RELIANCE"}],
            "depth": [{"exchange": "NSE", "symbol": "RELIANCE"}],
        }
        client.application.config["TICK_RECORDER"] = recorder
        client.application.config["TICK_CAPTURE_LIFECYCLE_LOCK"] = lifecycle_lock

        def update_config(**_kwargs: object) -> MagicMock:
            assert lifecycle_lock.held
            assert lock.held
            return pipeline.get_config.return_value

        pipeline.update_config.side_effect = update_config
        with patch("flinttrade_ai.signal_routes._get_pipeline", return_value=pipeline):
            response = client.post(
                "/api/v1/signals/configure",
                json={"instruments": ["nse:reliance", "BSE:RELIANCE"]},
            )

        assert response.status_code == 200
        assert lifecycle_lock.entries == 1
        assert lock.entries == 1
        pipeline.update_config.assert_called_once_with(
            instruments=["NSE:RELIANCE", "BSE:RELIANCE"],
            indicators=None,
            thresholds=None,
        )

    def test_threshold_update_uses_recorder_lock_without_comparing_watchlist(
        self,
        client: MagicMock,
        pipeline: MagicMock,
    ) -> None:
        lock = _TrackingLock()
        recorder = MagicMock()
        recorder.subscription_lock = lock
        client.application.config["TICK_RECORDER"] = recorder

        def update_config(**_kwargs: object) -> MagicMock:
            assert lock.held
            return pipeline.get_config.return_value

        pipeline.update_config.side_effect = update_config
        with patch("flinttrade_ai.signal_routes._get_pipeline", return_value=pipeline):
            response = client.post(
                "/api/v1/signals/configure",
                json={"thresholds": {"ema_cross_min_pct": 1.0}},
            )

        assert response.status_code == 200
        assert lock.entries == 1
        recorder.get_watchlist.assert_not_called()
        pipeline.update_config.assert_called_once_with(
            instruments=None,
            indicators=None,
            thresholds={"ema_cross_min_pct": 1.0},
        )

    def test_instruments_not_list_returns_400(self, client: MagicMock, pipeline: MagicMock) -> None:
        """Passing instruments as a string (not a list) returns HTTP 400.

        Args:
            client:   Flask test client.
            pipeline: Mock pipeline fixture.
        """
        with patch("flinttrade_ai.signal_routes._get_pipeline", return_value=pipeline):
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
        with patch("flinttrade_ai.signal_routes._get_pipeline", return_value=pipeline):
            resp = client.post(
                "/api/v1/signals/configure",
                json={"thresholds": ["wrong", "type"]},
            )
        assert resp.status_code == 400

    def test_empty_object_is_a_non_destructive_snapshot(self, client: MagicMock, pipeline: MagicMock) -> None:
        with patch("flinttrade_ai.signal_routes._get_pipeline", return_value=pipeline):
            resp = client.post("/api/v1/signals/configure", json={})

        assert resp.status_code == 200
        assert resp.get_json()["data"] == pipeline.get_config.return_value.to_dict.return_value
        pipeline.get_config.assert_called_once_with()
        pipeline.update_config.assert_not_called()

    def test_no_body_is_a_non_destructive_snapshot(self, client: MagicMock, pipeline: MagicMock) -> None:
        with patch("flinttrade_ai.signal_routes._get_pipeline", return_value=pipeline):
            resp = client.post("/api/v1/signals/configure")

        assert resp.status_code == 200
        assert resp.get_json()["data"] == pipeline.get_config.return_value.to_dict.return_value
        pipeline.get_config.assert_called_once_with()
        pipeline.update_config.assert_not_called()

    def test_malformed_json_returns_400(self, client: MagicMock, pipeline: MagicMock) -> None:
        with patch("flinttrade_ai.signal_routes._get_pipeline", return_value=pipeline):
            resp = client.post(
                "/api/v1/signals/configure",
                data='{"thresholds":',
                content_type="application/json",
            )

        assert resp.status_code == 400
        pipeline.update_config.assert_not_called()

    @pytest.mark.parametrize(
        ("body", "content_type"),
        [
            ("null", "application/json"),
            ('{"unexpected": true}', "application/json"),
            ('{"thresholds": null}', "application/json"),
        ],
    )
    def test_invalid_configuration_objects_return_400(
        self,
        client: MagicMock,
        pipeline: MagicMock,
        body: str,
        content_type: str,
    ) -> None:
        with patch("flinttrade_ai.signal_routes._get_pipeline", return_value=pipeline):
            resp = client.post("/api/v1/signals/configure", data=body, content_type=content_type)

        assert resp.status_code == 400
        pipeline.update_config.assert_not_called()

    @pytest.mark.parametrize(
        "payload",
        [
            {"indicators": ["RSI"]},
            {"indicators": [{"name": "RSI", "params": "14"}]},
            {"thresholds": {"rsi_oversold": "30"}},
            {"thresholds": {"rsi_oversold": math.nan}},
            {"thresholds": {"rsi_oversold": 80, "rsi_overbought": 70}},
        ],
    )
    def test_nested_validation_errors_return_400(self, payload: dict[str, object]) -> None:
        from flinttrade_ai.signal_pipeline import LiveSignalPipeline
        from flinttrade_ai.signal_routes import signal_bp

        app = Flask(__name__)
        app.config["TESTING"] = True
        app.register_blueprint(signal_bp)
        app._live_signal_pipeline = LiveSignalPipeline()  # type: ignore[attr-defined]

        with app.test_client() as client:
            response = client.post("/api/v1/signals/configure", json=payload)

        assert response.status_code == 400
        assert response.get_json()["status"] == "error"

    def test_non_object_configuration_payload_returns_400(self) -> None:
        from flinttrade_ai.signal_routes import signal_bp

        app = Flask(__name__)
        app.config["TESTING"] = True
        app.register_blueprint(signal_bp)

        with app.test_client() as client:
            response = client.post("/api/v1/signals/configure", json=["invalid"])

        assert response.status_code == 400

    @pytest.mark.parametrize(
        "payload",
        [
            {"indicators": [{"name": "RSI", "params": {"period": 10**400}}]},
            {"thresholds": {"macd_crossover_min": 10**400}},
        ],
    )
    def test_huge_legal_json_numbers_return_controlled_400(self, payload: dict[str, object]) -> None:
        from flinttrade_ai.signal_pipeline import LiveSignalPipeline
        from flinttrade_ai.signal_routes import signal_bp

        app = Flask(__name__)
        app.config.update(TESTING=True, PROPAGATE_EXCEPTIONS=False)
        app.register_blueprint(signal_bp)
        app._live_signal_pipeline = LiveSignalPipeline()  # type: ignore[attr-defined]

        with app.test_client() as client:
            response = client.post("/api/v1/signals/configure", json=payload)

        assert response.status_code == 400
        assert response.get_json()["status"] == "error"
