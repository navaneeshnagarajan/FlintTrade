"""Tests for packages/core/core/src/infra_routes.py — traffic log, latency, API analyser."""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest
from flask import Flask

import flinttrade_core.infra_routes as mod


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


def _traffic_logger() -> MagicMock:
    tl = MagicMock()
    tl.recent.return_value = [{"path": "/api/v1/funds", "status": 200}]
    tl.count.return_value = 42
    tl.stats.return_value = {
        "total_requests": 42,
        "error_rate": 0.02,
        "avg_duration_ms": 12.3,
        "p95_duration_ms": 45.0,
        "top_paths": [],
    }
    tl.export_csv.return_value = "path,status\n/api/v1/funds,200\n"
    return tl


def _latency_monitor() -> MagicMock:
    lm = MagicMock()
    lm.percentiles_by_broker.return_value = {"broker1": {"p50": 10, "p95": 50}}
    lm.histogram.return_value = [{"bucket_start": 0, "bucket_end": 10, "count": 5}]
    lm.slowest_recent.return_value = [{"order_id": "OID1", "latency_ms": 800}]
    return lm


def _api_analyzer() -> MagicMock:
    az = MagicMock()
    az.recent.return_value = [{"call_id": "c1", "route": "/api/v1/funds"}]
    az.count.return_value = 10
    az.replay.return_value = {"call_id": "c1", "request": {}, "response": {}}
    return az


@pytest.fixture()
def app():
    flask_app = Flask(__name__)
    flask_app.config["TESTING"] = True
    flask_app.config["TRAFFIC_LOGGER"] = _traffic_logger()
    flask_app.config["LATENCY_MONITOR"] = _latency_monitor()
    flask_app.config["API_ANALYZER"] = _api_analyzer()
    flask_app.register_blueprint(mod.infra_bp)
    return flask_app


@pytest.fixture()
def client(app):
    return app.test_client()


# ---------------------------------------------------------------------------
# Traffic routes
# ---------------------------------------------------------------------------


def test_traffic_list_ok(client):
    """200 with entries and total."""
    resp = client.get("/v1/admin/traffic")
    assert resp.status_code == 200
    body = resp.get_json()
    assert body["status"] == "success"
    assert "entries" in body["data"]


def test_traffic_stats_ok(client):
    """200 with aggregate stats."""
    resp = client.get("/v1/admin/traffic/stats")
    assert resp.status_code == 200
    assert resp.get_json()["status"] == "success"


def test_traffic_export_ok(client):
    """200 CSV download."""
    resp = client.get("/v1/admin/traffic/export")
    assert resp.status_code == 200
    assert resp.content_type.startswith("text/csv")


def test_traffic_invalid_limit(client):
    """400 for non-integer limit."""
    resp = client.get("/v1/admin/traffic?limit=abc")
    assert resp.status_code == 400


# ---------------------------------------------------------------------------
# Latency routes
# ---------------------------------------------------------------------------


def test_latency_stats_ok(client):
    """200 with broker percentiles."""
    resp = client.get("/v1/admin/latency/stats")
    assert resp.status_code == 200


def test_latency_histogram_ok(client):
    """200 with histogram data."""
    resp = client.get("/v1/admin/latency/histogram?broker=broker1")
    assert resp.status_code == 200


def test_latency_histogram_missing_broker(client):
    """400 when broker param absent."""
    resp = client.get("/v1/admin/latency/histogram")
    assert resp.status_code == 400


def test_latency_slow_ok(client):
    """200 with slowest orders."""
    resp = client.get("/v1/admin/latency/slow")
    assert resp.status_code == 200


# ---------------------------------------------------------------------------
# API analyser routes
# ---------------------------------------------------------------------------


def test_analyzer_calls_ok(client):
    """200 with call list."""
    resp = client.get("/v1/admin/analyzer/calls")
    assert resp.status_code == 200
    assert "calls" in resp.get_json()["data"]


def test_analyzer_replay_ok(client):
    """200 with call detail."""
    resp = client.get("/v1/admin/analyzer/c1/replay")
    assert resp.status_code == 200
    assert resp.get_json()["data"]["call_id"] == "c1"


def test_analyzer_replay_not_found(app):
    """404 when call ID not found."""
    az = app.config["API_ANALYZER"]
    az.replay.return_value = None

    with app.test_client() as c:
        resp = c.get("/v1/admin/analyzer/notexist/replay")
    assert resp.status_code == 404
