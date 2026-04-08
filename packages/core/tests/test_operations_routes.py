"""Tests for operations REST endpoints — safety, security, logs, errors, cron, ditto.

Run with:
    python -m pytest packages/core/tests/test_operations_routes.py -v --import-mode=importlib
"""
from __future__ import annotations

import json
import os
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest


_TEST_API_KEY = "test-operations-routes-key"


@pytest.fixture(scope="module")
def monkeypatch_module():
    """Module-scoped monkeypatch fixture."""
    from _pytest.monkeypatch import MonkeyPatch
    mp = MonkeyPatch()
    yield mp
    mp.undo()


@pytest.fixture(scope="module")
def flask_app(monkeypatch_module):
    """Create a Flask app with operations blueprint registered."""
    monkeypatch_module.setenv("OPENALGO_API_KEY", _TEST_API_KEY)
    monkeypatch_module.setenv("FLINTTRADE_DEV", "1")
    from packages.core.src.app import create_flask_app
    app = create_flask_app()
    app.config["TESTING"] = True
    return app


@pytest.fixture()
def client(flask_app):
    """Flask test client with API key header."""
    with flask_app.test_client() as c:
        yield c


def _auth_headers() -> dict[str, str]:
    return {
        "X-API-Key": _TEST_API_KEY,
        "Content-Type": "application/json",
    }


# ---------------------------------------------------------------------------
# Safety config
# ---------------------------------------------------------------------------


class TestSafetyConfigGet:
    """GET /api/v1/safety/config — return safety system configuration."""

    def test_returns_503_when_safety_not_configured(self, flask_app, client):
        """When SAFETY is None, returns 503."""
        original = flask_app.config.get("SAFETY")
        flask_app.config["SAFETY"] = None
        try:
            resp = client.get("/api/v1/safety/config", headers=_auth_headers())
            assert resp.status_code == 503
            data = resp.get_json()
            assert data["status"] == "error"
            assert "SafetySystem" in data["message"]
        finally:
            flask_app.config["SAFETY"] = original

    def test_returns_nested_config(self, flask_app, client):
        """When SAFETY is configured, returns the 5-layer nested config."""
        mock_safety = MagicMock()
        mock_safety.l1_order.price_deviation_pct = 5.0
        mock_safety.l1_order.check_market_hours = True
        mock_safety.l1_order.qty_limits = {"NSE": 1000}
        mock_safety.l2_position.max_positions = 10
        mock_safety.l2_position.max_margin_pct = 80.0
        mock_safety.l3_portfolio.max_net_delta = 50000.0
        mock_safety.l3_portfolio.max_net_vega = 10000.0
        mock_safety.l4_pnl.pause_pct = 2.0
        mock_safety.l4_pnl.kill_pct = 5.0
        mock_safety.l4_pnl.is_paused = False
        mock_safety.l4_pnl.is_killed = False
        mock_safety.l5_kill.is_active = False
        mock_safety.l5_kill.reason = ""

        original = flask_app.config.get("SAFETY")
        flask_app.config["SAFETY"] = mock_safety
        try:
            resp = client.get("/api/v1/safety/config", headers=_auth_headers())
            assert resp.status_code == 200
            data = resp.get_json()
            assert data["status"] == "success"
            assert "l1_order" in data["data"]
            assert "l2_position" in data["data"]
            assert "l3_portfolio" in data["data"]
            assert "l4_pnl" in data["data"]
            assert "l5_kill" in data["data"]
            assert data["data"]["l1_order"]["price_deviation_pct"] == 5.0
            assert data["data"]["l4_pnl"]["is_paused"] is False
        finally:
            flask_app.config["SAFETY"] = original


class TestSafetyConfigUpdate:
    """POST /api/v1/safety/config — update safety parameters."""

    def test_updates_single_field(self, flask_app, client):
        mock_safety = MagicMock()
        mock_safety.l1_order.price_deviation_pct = 5.0
        original = flask_app.config.get("SAFETY")
        flask_app.config["SAFETY"] = mock_safety
        try:
            resp = client.post("/api/v1/safety/config", json={
                "price_deviation_pct": 10.0,
            }, headers=_auth_headers())
            assert resp.status_code == 200
            data = resp.get_json()
            assert data["status"] == "success"
            assert mock_safety.l1_order.price_deviation_pct == 10.0
        finally:
            flask_app.config["SAFETY"] = original

    def test_invalid_value_returns_400(self, flask_app, client):
        mock_safety = MagicMock()
        # Make float() conversion raise ValueError
        mock_safety.l1_order.price_deviation_pct = property(
            lambda self: 5.0,
        )
        original = flask_app.config.get("SAFETY")
        flask_app.config["SAFETY"] = mock_safety
        try:
            resp = client.post("/api/v1/safety/config", json={
                "price_deviation_pct": "not-a-number",
            }, headers=_auth_headers())
            assert resp.status_code == 400
            data = resp.get_json()
            assert data["status"] == "error"
        finally:
            flask_app.config["SAFETY"] = original

    def test_returns_503_when_safety_not_configured(self, flask_app, client):
        original = flask_app.config.get("SAFETY")
        flask_app.config["SAFETY"] = None
        try:
            resp = client.post("/api/v1/safety/config", json={},
                               headers=_auth_headers())
            assert resp.status_code == 503
        finally:
            flask_app.config["SAFETY"] = original


# ---------------------------------------------------------------------------
# Security settings
# ---------------------------------------------------------------------------


class TestSecuritySettingsGet:
    """GET /api/v1/security/settings — return security monitor config."""

    def test_returns_settings(self, flask_app, client):
        """SecurityMonitor is auto-created by create_flask_app."""
        resp = client.get("/api/v1/security/settings", headers=_auth_headers())
        assert resp.status_code == 200
        data = resp.get_json()
        assert data["status"] == "success"
        assert "auto_ban_enabled" in data["data"]
        assert "threshold_404" in data["data"]
        assert "ban_duration_404" in data["data"]

    def test_returns_503_when_monitor_not_configured(self, flask_app, client):
        original = flask_app.config.get("SECURITY_MONITOR")
        flask_app.config["SECURITY_MONITOR"] = None
        try:
            resp = client.get("/api/v1/security/settings", headers=_auth_headers())
            assert resp.status_code == 503
        finally:
            flask_app.config["SECURITY_MONITOR"] = original


class TestSecuritySettingsUpdate:
    """POST /api/v1/security/settings — update security monitor config."""

    def test_update_threshold(self, flask_app, client):
        resp = client.post("/api/v1/security/settings", json={
            "threshold_404": 50,
        }, headers=_auth_headers())
        assert resp.status_code == 200
        data = resp.get_json()
        assert data["status"] == "success"
        assert data["data"]["threshold_404"] == 50

    def test_invalid_value_returns_400(self, flask_app, client):
        resp = client.post("/api/v1/security/settings", json={
            "threshold_404": "not-a-number",
        }, headers=_auth_headers())
        assert resp.status_code == 400
        data = resp.get_json()
        assert data["status"] == "error"


# ---------------------------------------------------------------------------
# Frontend error reporting
# ---------------------------------------------------------------------------


class TestFrontendErrors:
    """POST /api/v1/errors — receive error reports from the React frontend."""

    def test_receives_error_report(self, client):
        """Error endpoint is public (no API key needed) and always returns 200."""
        resp = client.post("/api/v1/errors", json={
            "message": "Uncaught TypeError: Cannot read properties of null",
            "url": "http://localhost:5173/trade",
            "stack": "TypeError: Cannot read properties...",
            "userAgent": "Mozilla/5.0",
        }, headers={"Content-Type": "application/json"})
        assert resp.status_code == 200
        data = resp.get_json()
        assert data["status"] == "success"

    def test_empty_error_body_returns_200(self, client):
        """Even an empty body should not crash."""
        resp = client.post("/api/v1/errors", json={},
                           headers={"Content-Type": "application/json"})
        assert resp.status_code == 200
        data = resp.get_json()
        assert data["status"] == "success"


# ---------------------------------------------------------------------------
# Recent logs
# ---------------------------------------------------------------------------


class TestRecentLogs:
    """GET /api/v1/logs/recent — return recent structured log entries."""

    def test_returns_200(self, client):
        resp = client.get("/api/v1/logs/recent", headers=_auth_headers())
        assert resp.status_code == 200
        data = resp.get_json()
        assert data["status"] == "success"
        assert isinstance(data["data"], list)

    def test_with_custom_n(self, client):
        resp = client.get("/api/v1/logs/recent?n=10", headers=_auth_headers())
        assert resp.status_code == 200
        data = resp.get_json()
        assert data["status"] == "success"

    def test_invalid_n_returns_400(self, client):
        resp = client.get("/api/v1/logs/recent?n=abc", headers=_auth_headers())
        assert resp.status_code == 400
        data = resp.get_json()
        assert data["status"] == "error"
        assert "positive integer" in data["message"]

    def test_negative_n_returns_400(self, client):
        resp = client.get("/api/v1/logs/recent?n=-5", headers=_auth_headers())
        assert resp.status_code == 400


# ---------------------------------------------------------------------------
# Ditto — multi-account endpoints
# ---------------------------------------------------------------------------


class TestDittoMirrorStatus:
    """GET /api/v1/ditto/mirror/status — position mirroring status."""

    def test_returns_200_with_defaults(self, client):
        resp = client.get("/api/v1/ditto/mirror/status", headers=_auth_headers())
        assert resp.status_code == 200
        data = resp.get_json()
        assert data["status"] == "success"
        assert data["data"]["active"] is False


class TestDittoMirrorStart:
    """POST /api/v1/ditto/mirror/start — start position mirroring."""

    def test_missing_source_returns_400(self, client):
        resp = client.post("/api/v1/ditto/mirror/start", json={
            "target_accounts": ["acc_2"],
        }, headers=_auth_headers())
        assert resp.status_code == 400

    def test_missing_targets_returns_400(self, client):
        resp = client.post("/api/v1/ditto/mirror/start", json={
            "source_account": "acc_1",
            "target_accounts": [],
        }, headers=_auth_headers())
        assert resp.status_code == 400

    def test_valid_start_returns_200(self, client):
        resp = client.post("/api/v1/ditto/mirror/start", json={
            "source_account": "acc_1",
            "target_accounts": ["acc_2", "acc_3"],
            "mode": "proportional",
        }, headers=_auth_headers())
        assert resp.status_code == 200
        data = resp.get_json()
        assert data["status"] == "success"
        assert data["data"]["active"] is True
        assert data["data"]["source_account"] == "acc_1"
