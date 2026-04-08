"""Tests for Security Dashboard Flask endpoints.

Run with:
    python -m pytest packages/core/tests/test_security_routes.py -v --import-mode=importlib
"""

from __future__ import annotations

import pytest

from packages.core.src.security import SecurityMonitor
from packages.core.src.security_routes import register_security_middleware, security_bp


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture()
def monitor():
    """Fresh SecurityMonitor for each test."""
    return SecurityMonitor(auth_ban_threshold=3, notfound_ban_threshold=10, ban_duration=3600)


@pytest.fixture()
def client(monitor):
    """Flask test client wired to a fresh SecurityMonitor."""
    from flask import Flask

    app = Flask(__name__)
    app.config["SECURITY_MONITOR"] = monitor
    app.config["TESTING"] = True
    app.register_blueprint(security_bp)
    register_security_middleware(app, monitor)
    with app.test_client() as c:
        yield c


# ---------------------------------------------------------------------------
# GET /stats
# ---------------------------------------------------------------------------


class TestGetStats:
    def test_empty_stats(self, client):
        resp = client.get("/api/v1/security/stats")
        assert resp.status_code == 200
        data = resp.get_json()
        assert data["status"] == "success"
        assert "total_ips" in data["data"]

    def test_stats_counts_banned(self, client, monitor):
        monitor.ban_ip("1.1.1.1", "test")
        resp = client.get("/api/v1/security/stats")
        data = resp.get_json()
        assert data["data"]["banned_count"] == 1


# ---------------------------------------------------------------------------
# GET /bans
# ---------------------------------------------------------------------------


class TestGetBans:
    def test_empty_bans_list(self, client):
        resp = client.get("/api/v1/security/bans")
        assert resp.status_code == 200
        data = resp.get_json()
        assert data["data"]["bans"] == []

    def test_banned_ip_appears_in_list(self, client, monitor):
        monitor.ban_ip("2.2.2.2", "flood")
        resp = client.get("/api/v1/security/bans")
        bans = resp.get_json()["data"]["bans"]
        assert any(b["ip"] == "2.2.2.2" for b in bans)


# ---------------------------------------------------------------------------
# GET /records
# ---------------------------------------------------------------------------


class TestGetRecords:
    def test_records_after_requests(self, client, monitor):
        monitor.record_request("3.3.3.3")
        resp = client.get("/api/v1/security/records")
        assert resp.status_code == 200
        records = resp.get_json()["data"]["records"]
        assert any(r["ip"] == "3.3.3.3" for r in records)


# ---------------------------------------------------------------------------
# POST /ban
# ---------------------------------------------------------------------------


class TestBanEndpoint:
    def test_ban_ip_returns_200(self, client):
        resp = client.post(
            "/api/v1/security/ban",
            json={"ip": "5.5.5.5", "reason": "manual ban test"},
            content_type="application/json",
        )
        assert resp.status_code == 200
        data = resp.get_json()
        assert data["status"] == "success"
        assert data["data"]["ip"] == "5.5.5.5"

    def test_ban_missing_ip_returns_400(self, client):
        resp = client.post(
            "/api/v1/security/ban",
            json={"reason": "no ip given"},
            content_type="application/json",
        )
        assert resp.status_code == 400

    def test_ban_missing_reason_returns_400(self, client):
        resp = client.post(
            "/api/v1/security/ban",
            json={"ip": "6.6.6.6"},
            content_type="application/json",
        )
        assert resp.status_code == 400


# ---------------------------------------------------------------------------
# POST /unban
# ---------------------------------------------------------------------------


class TestUnbanEndpoint:
    def test_unban_ip_returns_200(self, client, monitor):
        monitor.ban_ip("7.7.7.7", "to be unbanned")
        resp = client.post(
            "/api/v1/security/unban",
            json={"ip": "7.7.7.7"},
            content_type="application/json",
        )
        assert resp.status_code == 200
        assert not monitor.is_banned("7.7.7.7")

    def test_unban_missing_ip_returns_400(self, client):
        resp = client.post(
            "/api/v1/security/unban",
            json={},
            content_type="application/json",
        )
        assert resp.status_code == 400
