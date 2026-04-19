"""Tests for packages/ai/src/retrain_routes.py — ML auto-retraining endpoints."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest
from flask import Flask


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


def _make_mock_retrainer(history: list | None = None):
    """Build a MagicMock AutoRetrainer."""
    retrainer = MagicMock()
    retrainer._running = True
    retrainer._config.symbols = ["NIFTY", "BANKNIFTY"]
    retrainer._config.retrain_interval_hours = 24
    retrainer._config.min_accuracy = 0.6

    if history is None:
        result = MagicMock()
        result.to_dict.return_value = {"symbol": "NIFTY", "accuracy": 0.82}
        result.symbol = "NIFTY"
        history = [result]

    retrainer.get_history.return_value = history
    return retrainer


@pytest.fixture()
def app_with_retrainer():
    """Flask app with AutoRetrainer attached."""
    import packages.ai.src.retrain_routes as mod

    flask_app = Flask(__name__)
    flask_app.config["TESTING"] = True
    flask_app.register_blueprint(mod.retrain_bp)

    retrainer = _make_mock_retrainer()
    flask_app._auto_retrainer = retrainer  # type: ignore[attr-defined]
    flask_app._retrain_loop = None
    return flask_app


@pytest.fixture()
def app_no_retrainer():
    """Flask app without AutoRetrainer (uninitialised)."""
    import packages.ai.src.retrain_routes as mod

    flask_app = Flask(__name__)
    flask_app.config["TESTING"] = True
    flask_app.register_blueprint(mod.retrain_bp)
    return flask_app


# ---------------------------------------------------------------------------
# GET /ft-api/v1/retrain/status
# ---------------------------------------------------------------------------


def test_status_ok(app_with_retrainer):
    """Happy path: returns retrainer state."""
    with app_with_retrainer.test_client() as c:
        resp = c.get("/ft-api/v1/retrain/status")
    assert resp.status_code == 200
    body = resp.get_json()
    assert body["status"] == "success"
    assert "running" in body["data"]
    assert body["data"]["symbols"] == ["NIFTY", "BANKNIFTY"]


def test_status_no_retrainer(app_no_retrainer):
    """503 when AutoRetrainer not initialised."""
    with app_no_retrainer.test_client() as c:
        resp = c.get("/ft-api/v1/retrain/status")
    assert resp.status_code == 503
    assert resp.get_json()["status"] == "error"


# ---------------------------------------------------------------------------
# POST /ft-api/v1/retrain/trigger
# ---------------------------------------------------------------------------


def test_trigger_no_symbol(app_with_retrainer):
    """400 when symbol is missing."""
    with app_with_retrainer.test_client() as c:
        resp = c.post("/ft-api/v1/retrain/trigger", json={})
    assert resp.status_code == 400


def test_trigger_ok(app_with_retrainer):
    """Happy path: runs synchronously (no bg loop) and returns result."""
    result_mock = MagicMock()
    result_mock.to_dict.return_value = {"symbol": "NIFTY", "accuracy": 0.85}

    with patch("asyncio.run", return_value=result_mock):
        with app_with_retrainer.test_client() as c:
            resp = c.post(
                "/ft-api/v1/retrain/trigger", json={"symbol": "NIFTY"}
            )

    assert resp.status_code == 200
    body = resp.get_json()
    assert body["status"] == "success"
    assert "accuracy" in body["data"]


def test_trigger_no_retrainer(app_no_retrainer):
    """503 when AutoRetrainer not initialised."""
    with app_no_retrainer.test_client() as c:
        resp = c.post("/ft-api/v1/retrain/trigger", json={"symbol": "NIFTY"})
    assert resp.status_code == 503


# ---------------------------------------------------------------------------
# GET /ft-api/v1/retrain/history
# ---------------------------------------------------------------------------


def test_history_ok(app_with_retrainer):
    """Returns paginated history list."""
    with app_with_retrainer.test_client() as c:
        resp = c.get("/ft-api/v1/retrain/history")
    assert resp.status_code == 200
    body = resp.get_json()
    assert body["status"] == "success"
    assert "results" in body["data"]
    assert "total" in body["data"]


def test_history_no_retrainer(app_no_retrainer):
    """503 when not initialised."""
    with app_no_retrainer.test_client() as c:
        resp = c.get("/ft-api/v1/retrain/history")
    assert resp.status_code == 503


def test_history_invalid_limit(app_with_retrainer):
    """400 for non-integer limit param."""
    with app_with_retrainer.test_client() as c:
        resp = c.get("/ft-api/v1/retrain/history?limit=abc")
    assert resp.status_code == 400


def test_history_symbol_filter(app_with_retrainer):
    """Symbol filter reduces results."""
    with app_with_retrainer.test_client() as c:
        resp = c.get("/ft-api/v1/retrain/history?symbol=NIFTY")
    assert resp.status_code == 200
