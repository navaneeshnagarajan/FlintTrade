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
        with patch.object(_mod.get_health_monitor(), "check_all", return_value=report):
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
        with patch.object(_mod.get_health_monitor(), "check_all", return_value=report):
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
        with patch.object(_mod.get_health_monitor(), "check_all", return_value=report):
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
        with patch.object(_mod.get_health_monitor(), "check_all", return_value=report):
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
            patch.object(_mod.get_health_monitor(), "check_memory", return_value=mem),
            patch.object(_mod.get_health_monitor(), "check_disk", return_value=disk),
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
            patch.object(_mod.get_health_monitor(), "check_memory", return_value=mem),
            patch.object(_mod.get_health_monitor(), "check_disk", return_value=disk),
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


# ---------------------------------------------------------------------------
# /api/v1/health (aggregated subsystem health — canonical surface)
# ---------------------------------------------------------------------------


class TestHealthAggregated:
    def test_health_returns_200_or_503(self, client):
        """Aggregated health endpoint returns 200 or 503 with a status field.

        Args:
            client: Flask test client.
        """
        resp = client.get("/api/v1/health")
        assert resp.status_code in (200, 503)
        data = resp.get_json()
        assert "status" in data
        assert data["status"] in ("ok", "degraded", "error")

    def test_health_has_all_subsystems(self, client):
        """Aggregated health response includes broker, disk, and memory keys.

        Args:
            client: Flask test client.
        """
        resp = client.get("/api/v1/health")
        data = resp.get_json()
        assert "broker" in data
        assert "disk" in data
        assert "memory" in data


# ---------------------------------------------------------------------------
# Lazy singletons (workspace path unification, wave 1)
# ---------------------------------------------------------------------------


@pytest.fixture()
def fresh_singletons():
    """Drop the module singletons before and after the test.

    The monitor caches its disk-probe directory for its lifetime, so a test
    that changes ``FLINTTRADE_WORKSPACE_DIR`` must start from a clean slate
    and must not leave an instance pinned to a deleted ``tmp_path`` behind
    for whichever test the randomised order runs next.

    Yields:
        The imported ``flinttrade_core.health_routes`` module.
    """
    import flinttrade_core.health_routes as _mod

    _mod.reset_health_singletons_for_tests()
    try:
        yield _mod
    finally:
        _mod.reset_health_singletons_for_tests()


class TestLazySingletons:
    @pytest.mark.unit
    def test_singletons_are_not_built_until_first_use(self, fresh_singletons):
        """Nothing is constructed until a getter is called."""
        assert fresh_singletons._monitor is None
        assert fresh_singletons._health_agg is None

        fresh_singletons.get_health_monitor()
        fresh_singletons.get_health_aggregator()

        assert fresh_singletons._monitor is not None
        assert fresh_singletons._health_agg is not None

    @pytest.mark.unit
    def test_getters_return_the_same_instance(self, fresh_singletons):
        """Repeated getter calls hand back one shared instance."""
        assert fresh_singletons.get_health_monitor() is fresh_singletons.get_health_monitor()
        assert fresh_singletons.get_health_aggregator() is fresh_singletons.get_health_aggregator()

    @pytest.mark.unit
    def test_monitor_honours_a_workspace_override_set_after_import(
        self, tmp_path, monkeypatch, fresh_singletons
    ):
        """The monitor probes the workspace active at first use, not at import.

        This is the regression test for the import-time
        ``_monitor = HealthMonitor()`` singleton: it froze the workspace that
        happened to be active while the blueprint module was being imported.
        """
        workspace = tmp_path / "ws"
        monkeypatch.delenv("FLINTTRADE_HOME", raising=False)
        monkeypatch.setenv("FLINTTRADE_WORKSPACE_DIR", str(workspace))

        check = fresh_singletons.get_health_monitor().check_disk()

        probed = [d["path"] for d in check.metrics["directories"]]
        assert probed == [str(workspace.resolve())]

    @pytest.mark.unit
    def test_init_health_monitor_replaces_the_lazy_singleton(self, fresh_singletons):
        """Injected instances still win over the lazily built one."""
        injected = MagicMock()
        fresh_singletons.init_health_monitor(injected)
        assert fresh_singletons.get_health_monitor() is injected

    @pytest.mark.unit
    def test_init_health_aggregator_replaces_the_lazy_singleton(self, fresh_singletons):
        """Injected aggregators still win over the lazily built one."""
        injected = MagicMock()
        fresh_singletons.init_health_aggregator(injected)
        assert fresh_singletons.get_health_aggregator() is injected
