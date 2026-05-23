# packages/core/core/tests/test_system_metrics.py
"""Tests for system_metrics — psutil-based resource collection + admin route."""

from __future__ import annotations

from unittest.mock import MagicMock, patch


# ---------------------------------------------------------------------------
# SystemMetrics model
# ---------------------------------------------------------------------------


class TestSystemMetricsModel:
    def test_default_values_are_zero(self):
        from flinttrade_core.system_metrics import SystemMetrics

        m = SystemMetrics()
        assert m.cpu_percent == 0.0
        assert m.memory_percent == 0.0
        assert m.memory_used_gb == 0.0
        assert m.memory_total_gb == 0.0
        assert m.disk_percent == 0.0
        assert m.disk_used_gb == 0.0
        assert m.disk_total_gb == 0.0
        assert m.uptime_seconds == 0.0
        assert m.process_count == 0
        assert m.network_bytes_sent == 0
        assert m.network_bytes_recv == 0
        assert m.psutil_available is False

    def test_to_dict_returns_all_fields(self):
        from flinttrade_core.system_metrics import SystemMetrics

        m = SystemMetrics(cpu_percent=42.5, memory_percent=60.0, psutil_available=True)
        d = m.to_dict()
        assert d["cpu_percent"] == 42.5
        assert d["memory_percent"] == 60.0
        assert d["psutil_available"] is True
        assert "disk_percent" in d
        assert "network_bytes_sent" in d

    def test_fields_accept_real_values(self):
        from flinttrade_core.system_metrics import SystemMetrics

        m = SystemMetrics(
            cpu_percent=10.0,
            memory_used_gb=4.5,
            memory_total_gb=16.0,
            disk_used_gb=200.0,
            disk_total_gb=512.0,
            uptime_seconds=86400.0,
            process_count=250,
            network_bytes_sent=1024 * 1024,
            network_bytes_recv=2048 * 1024,
            psutil_available=True,
        )
        assert m.memory_total_gb == 16.0
        assert m.process_count == 250


# ---------------------------------------------------------------------------
# get_system_metrics — psutil available
# ---------------------------------------------------------------------------


class TestGetSystemMetricsPsutilAvailable:
    def _mock_psutil(self):
        """Build a mock psutil module with realistic return values."""
        mock = MagicMock()
        mock.cpu_percent.return_value = 35.0

        mem = MagicMock()
        mem.percent = 55.5
        mem.used = int(8.5 * 1024 ** 3)
        mem.total = int(16.0 * 1024 ** 3)
        mock.virtual_memory.return_value = mem

        disk = MagicMock()
        disk.percent = 40.0
        disk.used = int(200 * 1024 ** 3)
        disk.total = int(512 * 1024 ** 3)
        mock.disk_usage.return_value = disk

        mock.boot_time.return_value = 0.0  # will be subtracted from time.time()

        mock.pids.return_value = list(range(300))

        net = MagicMock()
        net.bytes_sent = 10_000_000
        net.bytes_recv = 20_000_000
        mock.net_io_counters.return_value = net

        return mock

    def test_returns_populated_metrics(self):
        import flinttrade_core.system_metrics as sm_module

        mock_psutil = self._mock_psutil()
        with (
            patch.object(sm_module, "_psutil", mock_psutil),
            patch.object(sm_module, "_PSUTIL_AVAILABLE", True),
            patch("time.time", return_value=86400.0),
        ):
            metrics = sm_module.get_system_metrics()

        assert metrics.psutil_available is True
        assert metrics.cpu_percent == 35.0
        assert metrics.memory_percent == 55.5
        assert metrics.memory_total_gb == 16.0
        assert metrics.process_count == 300
        assert metrics.network_bytes_sent == 10_000_000
        assert metrics.network_bytes_recv == 20_000_000

    def test_disk_gb_computed_correctly(self):
        import flinttrade_core.system_metrics as sm_module

        mock_psutil = self._mock_psutil()
        with (
            patch.object(sm_module, "_psutil", mock_psutil),
            patch.object(sm_module, "_PSUTIL_AVAILABLE", True),
            patch("time.time", return_value=100.0),
        ):
            metrics = sm_module.get_system_metrics()

        assert metrics.disk_total_gb == 512.0
        assert 199 < metrics.disk_used_gb < 201

    def test_uptime_is_positive(self):
        import flinttrade_core.system_metrics as sm_module

        mock_psutil = self._mock_psutil()
        mock_psutil.boot_time.return_value = 0.0
        with (
            patch.object(sm_module, "_psutil", mock_psutil),
            patch.object(sm_module, "_PSUTIL_AVAILABLE", True),
            patch("time.time", return_value=3600.0),
        ):
            metrics = sm_module.get_system_metrics()

        assert metrics.uptime_seconds == 3600.0

    def test_exception_returns_empty_metrics(self):
        import flinttrade_core.system_metrics as sm_module

        mock_psutil = MagicMock()
        mock_psutil.cpu_percent.side_effect = OSError("permission denied")
        with (
            patch.object(sm_module, "_psutil", mock_psutil),
            patch.object(sm_module, "_PSUTIL_AVAILABLE", True),
        ):
            metrics = sm_module.get_system_metrics()

        assert metrics.psutil_available is False
        assert metrics.cpu_percent == 0.0


# ---------------------------------------------------------------------------
# get_system_metrics — psutil unavailable
# ---------------------------------------------------------------------------


class TestGetSystemMetricsPsutilMissing:
    def test_returns_empty_metrics_when_psutil_missing(self):
        import flinttrade_core.system_metrics as sm_module

        with patch.object(sm_module, "_PSUTIL_AVAILABLE", False):
            metrics = sm_module.get_system_metrics()

        assert metrics.psutil_available is False
        assert metrics.cpu_percent == 0.0
        assert metrics.process_count == 0


# ---------------------------------------------------------------------------
# Admin route — GET /v1/admin/system
# ---------------------------------------------------------------------------

_TEST_API_KEY = "test-system-metrics-key"


def _auth_headers() -> dict[str, str]:
    return {"X-API-Key": _TEST_API_KEY}


class TestAdminSystemRoute:
    """GET /v1/admin/system — requires FLINTTRADE_DEV=1 and a valid API key."""

    def test_route_returns_200_with_metrics(self, monkeypatch):
        monkeypatch.setenv("OPENALGO_API_KEY", _TEST_API_KEY)
        monkeypatch.setenv("FLINTTRADE_DEV", "1")
        from flinttrade_core.app import create_flask_app
        from flinttrade_core.system_metrics import SystemMetrics

        fake_metrics = SystemMetrics(
            cpu_percent=25.0,
            memory_percent=50.0,
            psutil_available=True,
        )

        app = create_flask_app()
        app.config["TESTING"] = True

        # The route uses a lazy import so we patch at the source module level.
        with app.test_client() as c:
            with patch(
                "flinttrade_core.system_metrics.get_system_metrics",
                return_value=fake_metrics,
            ):
                resp = c.get("/v1/admin/system", headers=_auth_headers())

        assert resp.status_code == 200
        data = resp.get_json()
        assert data["status"] == "success"
        assert data["data"]["cpu_percent"] == 25.0
        assert data["data"]["memory_percent"] == 50.0
        assert data["data"]["psutil_available"] is True

    def test_route_returns_empty_metrics_when_psutil_missing(self, monkeypatch):
        monkeypatch.setenv("OPENALGO_API_KEY", _TEST_API_KEY)
        monkeypatch.setenv("FLINTTRADE_DEV", "1")
        from flinttrade_core.app import create_flask_app
        from flinttrade_core.system_metrics import SystemMetrics

        empty = SystemMetrics(psutil_available=False)

        app = create_flask_app()
        app.config["TESTING"] = True

        with app.test_client() as c:
            with patch(
                "flinttrade_core.system_metrics.get_system_metrics",
                return_value=empty,
            ):
                resp = c.get("/v1/admin/system", headers=_auth_headers())

        assert resp.status_code == 200
        data = resp.get_json()
        assert data["data"]["psutil_available"] is False
        assert data["data"]["cpu_percent"] == 0.0
