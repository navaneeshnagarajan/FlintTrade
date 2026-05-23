"""Tests for packages/core/core/src/health_routes.py (Flask Blueprint).

Covers all five endpoints: /health, /health/detail, /healthz, /readyz,
/api/v1/ping — with healthy and degraded/unhealthy mocked HealthMonitor states.
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest
from flask import Flask


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_check(status: str, name: str = "test") -> MagicMock:
    """Build a mock HealthCheck dataclass-like object.

    Args:
        status: One of ``"healthy"``, ``"degraded"``, or ``"unhealthy"``.
        name:   Check name label.

    Returns:
        MagicMock with ``status``, ``name``, and ``message`` attributes.
    """
    c = MagicMock()
    c.status = status
    c.name = name
    c.message = ""
    return c


def _make_report(overall: str) -> MagicMock:
    """Build a mock HealthReport.

    Args:
        overall: Overall status string.

    Returns:
        MagicMock with ``overall_status``, ``timestamp``, and ``to_dict``.
    """
    from datetime import datetime, timezone, timedelta

    report = MagicMock()
    report.overall_status = overall
    report.timestamp = datetime.now(timezone(timedelta(hours=5, minutes=30)))
    report.to_dict.return_value = {"overall_status": overall, "checks": []}
    return report


# ---------------------------------------------------------------------------
# Fixture
# ---------------------------------------------------------------------------


@pytest.fixture()
def app():
    """Flask test app with health_bp registered and monitor injectable.

    Yields:
        Configured Flask application instance.
    """
    import flinttrade_core.health_routes as _mod

    flask_app = Flask(__name__)
    flask_app.config["TESTING"] = True
    flask_app.register_blueprint(_mod.health_bp)
    return flask_app


@pytest.fixture()
def client(app):
    """Flask test client.

    Args:
        app: Fixture-provided Flask application.

    Returns:
        Test client instance.
    """
    return app.test_client()


# ---------------------------------------------------------------------------
# /health
# ---------------------------------------------------------------------------


class TestHealthSimple:
    def test_returns_200_when_healthy(self, client):
        """Healthy monitor → 200 with status=healthy.

        Args:
            client: Flask test client.
        """
        import flinttrade_core.health_routes as _mod

        report = _make_report("healthy")
        with patch.object(_mod._monitor, "check_all", return_value=report):
            resp = client.get("/health")
        assert resp.status_code == 200
        data = resp.get_json()
        assert data["status"] == "healthy"
        assert "timestamp" in data

    def test_returns_503_when_degraded(self, client):
        """Degraded monitor → 503 status code.

        Args:
            client: Flask test client.
        """
        import flinttrade_core.health_routes as _mod

        report = _make_report("degraded")
        with patch.object(_mod._monitor, "check_all", return_value=report):
            resp = client.get("/health")
        assert resp.status_code == 503
        assert resp.get_json()["status"] == "degraded"


# ---------------------------------------------------------------------------
# /health/detail
# ---------------------------------------------------------------------------


class TestHealthDetail:
    def test_detail_200_healthy(self, client):
        """Detail endpoint returns full report dict when healthy.

        Args:
            client: Flask test client.
        """
        import flinttrade_core.health_routes as _mod

        report = _make_report("healthy")
        with patch.object(_mod._monitor, "check_all", return_value=report):
            resp = client.get("/health/detail")
        assert resp.status_code == 200
        data = resp.get_json()
        assert data["overall_status"] == "healthy"

    def test_detail_503_unhealthy(self, client):
        """Detail endpoint returns 503 when unhealthy.

        Args:
            client: Flask test client.
        """
        import flinttrade_core.health_routes as _mod

        report = _make_report("unhealthy")
        with patch.object(_mod._monitor, "check_all", return_value=report):
            resp = client.get("/health/detail")
        assert resp.status_code == 503


# ---------------------------------------------------------------------------
# /healthz
# ---------------------------------------------------------------------------


class TestHealthz:
    def test_always_200(self, client):
        """Kubernetes liveness probe always returns 200.

        Args:
            client: Flask test client.
        """
        resp = client.get("/healthz")
        assert resp.status_code == 200
        assert resp.get_json()["status"] == "ok"


# ---------------------------------------------------------------------------
# /readyz
# ---------------------------------------------------------------------------


class TestReadyz:
    def test_ready_when_mem_and_disk_healthy(self, client):
        """Readiness probe returns 200 when both memory and disk are healthy.

        Args:
            client: Flask test client.
        """
        import flinttrade_core.health_routes as _mod

        mem = _make_check("healthy", "memory")
        disk = _make_check("healthy", "disk")
        with (
            patch.object(_mod._monitor, "check_memory", return_value=mem),
            patch.object(_mod._monitor, "check_disk", return_value=disk),
        ):
            resp = client.get("/readyz")
        assert resp.status_code == 200
        assert resp.get_json()["status"] == "ready"

    def test_not_ready_when_memory_unhealthy(self, client):
        """Readiness probe returns 503 when memory is unhealthy.

        Args:
            client: Flask test client.
        """
        import flinttrade_core.health_routes as _mod

        mem = _make_check("unhealthy", "memory")
        disk = _make_check("healthy", "disk")
        with (
            patch.object(_mod._monitor, "check_memory", return_value=mem),
            patch.object(_mod._monitor, "check_disk", return_value=disk),
        ):
            resp = client.get("/readyz")
        assert resp.status_code == 503
        assert resp.get_json()["status"] == "not_ready"


# ---------------------------------------------------------------------------
# /api/v1/ping
# ---------------------------------------------------------------------------


class TestPing:
    def test_ping_returns_ok_with_timestamp(self, client):
        """Ping endpoint returns 200 with status=ok and an ISO timestamp.

        Args:
            client: Flask test client.
        """
        resp = client.get("/api/v1/ping")
        assert resp.status_code == 200
        data = resp.get_json()
        assert data["status"] == "ok"
        assert "timestamp" in data
        assert "+" in data["timestamp"] or "IST" in data["timestamp"] or "T" in data["timestamp"]
