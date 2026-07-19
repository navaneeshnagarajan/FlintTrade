"""Tests for monitoring Flask endpoints.

Run with:
    python -m pytest packages/core/core/tests/test_monitoring_routes.py -v --import-mode=importlib
"""
from __future__ import annotations

import json

import pytest


_TEST_API_KEY = "test-monitoring-routes-key"


@pytest.fixture(scope="module")
def monkeypatch_module():
    """Module-scoped monkeypatch fixture."""
    from _pytest.monkeypatch import MonkeyPatch
    mp = MonkeyPatch()
    yield mp
    mp.undo()


@pytest.fixture(scope="module")
def app_client(monkeypatch_module):
    """Return a Flask test client with pre-seeded monitoring data."""
    from flinttrade_core.app import create_flask_app
    from flinttrade_core.monitoring import TrafficCounter, LatencyTracker
    from flinttrade_core.monitoring_routes import init_monitoring_routes

    monkeypatch_module.setenv("OPENALGO_API_KEY", _TEST_API_KEY)

    traffic = TrafficCounter()
    traffic.record("GET", "/api/v1/health", 200, 12.0)
    traffic.record("POST", "/api/v1/pnl-tracker", 201, 5.0)
    traffic.record("GET", "/api/v1/bad", 500, 3.0)

    latency = LatencyTracker()
    latency.record_order_latency("BROKER_A", "NIFTY", 42.0)
    latency.record_order_latency("BROKER_A", "BANKNIFTY", 38.0)

    init_monitoring_routes(traffic=traffic, latency=latency)

    flask_app = create_flask_app()
    flask_app.config["TESTING"] = True
    with flask_app.test_client() as c:
        yield c


def _get(client, url):
    return client.get(url, headers={"X-API-Key": _TEST_API_KEY})


class TestMonitoringRoutes:

    def test_traffic_stats_returns_data(self, app_client):
        resp = _get(app_client, "/api/v1/traffic/stats")
        assert resp.status_code == 200
        data = json.loads(resp.data)
        assert data["status"] == "success"
        assert "total_requests" in data["data"]
        assert "error_rate" in data["data"]
        assert "avg_latency_ms" in data["data"]

    def test_traffic_recent_returns_list(self, app_client):
        resp = _get(app_client, "/api/v1/traffic/recent")
        assert resp.status_code == 200
        data = json.loads(resp.data)
        assert data["status"] == "success"
        assert isinstance(data["data"], list)

    def test_latency_stats_has_broker(self, app_client):
        resp = _get(app_client, "/api/v1/latency/stats")
        assert resp.status_code == 200
        data = json.loads(resp.data)
        assert data["status"] == "success"
        assert "BROKER_A" in data["data"]
        broker = data["data"]["BROKER_A"]
        assert broker["count"] == 2
        assert "avg_ms" in broker
        assert "p50_ms" in broker
        assert "p95_ms" in broker
        assert "p99_ms" in broker

    def test_latency_recent_returns_list(self, app_client):
        resp = _get(app_client, "/api/v1/latency/recent")
        assert resp.status_code == 200
        data = json.loads(resp.data)
        assert data["status"] == "success"
        assert isinstance(data["data"], list)
        assert len(data["data"]) >= 1


class TestPersistentTrafficStore:
    """U12: /traffic/* serves from the DuckDB TrafficLogger, not the counter."""

    def test_stats_and_recent_serve_from_the_persistent_logger(self, app_client):
        flask_app = app_client.application
        traffic_logger = flask_app.config.get("TRAFFIC_LOGGER")
        assert traffic_logger is not None

        traffic_logger.log(
            ip="127.0.0.1",
            method="GET",
            path="/api/v1/persistent-probe",
            status_code=200,
            duration_ms=7.5,
        )

        resp = _get(app_client, "/api/v1/traffic/stats?minutes=60")
        assert resp.status_code == 200
        data = json.loads(resp.data)["data"]
        assert data["total_requests"] >= 1
        assert data["window_minutes"] == 60
        assert "p95_latency_ms" in data
        assert any(
            row["path"] == "/api/v1/persistent-probe" for row in data["top_paths"]
        )

        resp = _get(app_client, "/api/v1/traffic/recent?n=50")
        rows = json.loads(resp.data)["data"]
        probe = [r for r in rows if r["path"] == "/api/v1/persistent-probe"]
        assert probe, "logged row did not surface in /traffic/recent"
        # Documented response keys preserved (status, not status_code).
        assert probe[0]["status"] == 200
        assert probe[0]["duration_ms"] == 7.5
