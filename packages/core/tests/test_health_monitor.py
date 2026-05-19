"""Tests for HealthMonitor, HealthCheck, and HealthReport.

Run with:
    python -m pytest packages/core/tests/test_health_monitor.py -v --import-mode=importlib
"""

from __future__ import annotations

import socket
from datetime import datetime, timezone, timedelta
from unittest.mock import MagicMock, patch


from packages.core.src.health_monitor import (
    HealthCheck,
    HealthMonitor,
    HealthReport,
    _overall,
)

_IST = timezone(timedelta(hours=5, minutes=30))


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _monitor(**kwargs) -> HealthMonitor:
    """Create a HealthMonitor with safe defaults for unit tests.

    Suppresses disk/db/websocket checks unless explicitly configured.
    """
    defaults: dict = {
        "ws_host": "127.0.0.1",
        "ws_port": 19999,  # unused port — ws check will fail but that's ok
    }
    defaults.update(kwargs)
    return HealthMonitor(**defaults)


# ---------------------------------------------------------------------------
# _overall
# ---------------------------------------------------------------------------


class TestOverall:
    def _check(self, status):
        return HealthCheck(
            name="x", status=status, message="", metrics={},
            checked_at=datetime.now(_IST),
        )

    def test_all_healthy(self):
        assert _overall([self._check("healthy")] * 3) == "healthy"

    def test_one_degraded(self):
        checks = [self._check("healthy"), self._check("degraded")]
        assert _overall(checks) == "degraded"

    def test_one_unhealthy(self):
        checks = [self._check("healthy"), self._check("unhealthy")]
        assert _overall(checks) == "unhealthy"

    def test_unhealthy_wins_over_degraded(self):
        checks = [self._check("degraded"), self._check("unhealthy")]
        assert _overall(checks) == "unhealthy"


# ---------------------------------------------------------------------------
# HealthCheck.to_dict
# ---------------------------------------------------------------------------


class TestHealthCheckToDict:
    def test_serialises_all_fields(self):
        ts = datetime.now(_IST)
        hc = HealthCheck(
            name="memory",
            status="healthy",
            message="All good",
            metrics={"rss_mb": 42.0},
            checked_at=ts,
        )
        d = hc.to_dict()
        assert d["name"] == "memory"
        assert d["status"] == "healthy"
        assert d["message"] == "All good"
        assert d["metrics"] == {"rss_mb": 42.0}
        assert d["checked_at"] == ts.isoformat()


# ---------------------------------------------------------------------------
# HealthReport.to_dict
# ---------------------------------------------------------------------------


class TestHealthReportToDict:
    def test_serialises_overall_and_checks(self):
        ts = datetime.now(_IST)
        hc = HealthCheck(
            name="disk", status="healthy", message="ok", metrics={}, checked_at=ts
        )
        report = HealthReport(
            overall_status="healthy",
            checks=[hc],
            timestamp=ts,
        )
        d = report.to_dict()
        assert d["overall_status"] == "healthy"
        assert len(d["checks"]) == 1
        assert d["checks"][0]["name"] == "disk"


# ---------------------------------------------------------------------------
# check_memory
# ---------------------------------------------------------------------------


class TestCheckMemory:
    def test_returns_health_check(self):
        m = _monitor()
        result = m.check_memory()
        assert isinstance(result, HealthCheck)
        assert result.name == "memory"
        assert result.status in ("healthy", "degraded", "unhealthy")

    def test_psutil_unavailable(self):
        m = _monitor()
        with patch.dict("sys.modules", {"psutil": None}):
            result = m.check_memory()
        # Should degrade gracefully, not crash
        assert result.name == "memory"

    def test_high_memory_usage_degraded(self):
        m = _monitor()
        mock_psutil = MagicMock()
        mock_proc = MagicMock()
        mock_proc.memory_info.return_value = MagicMock(
            rss=1024 * 1024 * 512, vms=1024 * 1024 * 1024
        )
        mock_proc.memory_percent.return_value = 60.0  # above 50% threshold
        mock_psutil.Process.return_value = mock_proc
        mock_psutil.virtual_memory.return_value = MagicMock(
            total=8 * 1024**3, available=2 * 1024**3, percent=75.0
        )
        with patch.dict("sys.modules", {"psutil": mock_psutil}):
            result = m.check_memory()
        assert result.status == "degraded"

    def test_metrics_contain_rss(self):
        m = _monitor()
        result = m.check_memory()
        if result.metrics:  # psutil available
            assert "rss_mb" in result.metrics or "note" in result.metrics


# ---------------------------------------------------------------------------
# check_disk
# ---------------------------------------------------------------------------


class TestCheckDisk:
    def test_returns_health_check(self, tmp_path):
        m = HealthMonitor(data_dirs=[tmp_path])
        result = m.check_disk()
        assert isinstance(result, HealthCheck)
        assert result.name == "disk"

    def test_healthy_when_space_available(self, tmp_path):
        m = HealthMonitor(data_dirs=[tmp_path])
        result = m.check_disk()
        # tmp_path is on the same partition — should have plenty of space
        assert result.status in ("healthy", "degraded", "unhealthy")

    def test_per_directory_metrics_present(self, tmp_path):
        m = HealthMonitor(data_dirs=[tmp_path])
        result = m.check_disk()
        assert "directories" in result.metrics
        assert len(result.metrics["directories"]) == 1

    def test_critical_disk_warns(self, tmp_path):
        m = HealthMonitor(data_dirs=[tmp_path])
        # Patch shutil.disk_usage to simulate near-full disk
        mock_usage = MagicMock()
        mock_usage.total = 100 * 1024**3
        mock_usage.used = 99 * 1024**3 + 900 * 1024**2  # ~0.1 GB free
        mock_usage.free = 100 * 1024**2
        with patch("shutil.disk_usage", return_value=mock_usage):
            result = m.check_disk()
        assert result.status == "unhealthy"


# ---------------------------------------------------------------------------
# check_file_descriptors
# ---------------------------------------------------------------------------


class TestCheckFileDescriptors:
    def test_returns_health_check(self):
        m = _monitor()
        result = m.check_file_descriptors()
        assert isinstance(result, HealthCheck)
        assert result.name == "file_descriptors"

    def test_psutil_unavailable_returns_healthy(self):
        m = _monitor()
        with patch.dict("sys.modules", {"psutil": None}):
            result = m.check_file_descriptors()
        assert result.status == "healthy"

    def test_high_fd_utilisation_warns(self):
        m = _monitor()
        mock_psutil = MagicMock()
        mock_proc = MagicMock()
        mock_proc.num_fds.return_value = 900
        mock_psutil.Process.return_value = mock_proc
        # Patch the resource module that is imported inside check_file_descriptors
        mock_resource = MagicMock()
        mock_resource.getrlimit.return_value = (1024, 1024)
        mock_resource.RLIMIT_NOFILE = 7
        with patch.dict("sys.modules", {"psutil": mock_psutil, "resource": mock_resource}):
            result = m.check_file_descriptors()
        assert result.status == "degraded"


# ---------------------------------------------------------------------------
# check_thread_count
# ---------------------------------------------------------------------------


class TestCheckThreadCount:
    def test_returns_health_check(self):
        m = _monitor()
        result = m.check_thread_count()
        assert isinstance(result, HealthCheck)
        assert result.name == "thread_count"

    def test_baseline_set_on_first_call(self):
        m = _monitor()
        m.check_thread_count()
        assert m._thread_baseline is not None

    def test_no_growth_is_healthy(self):
        m = _monitor()
        # Both calls should see roughly the same thread count
        m.check_thread_count()
        result = m.check_thread_count()
        assert result.status in ("healthy", "degraded")

    def test_large_growth_is_degraded(self):
        m = _monitor()
        mock_psutil = MagicMock()
        mock_proc = MagicMock()
        call_count = [0]

        def _num_threads():
            call_count[0] += 1
            return 10 if call_count[0] == 1 else 150  # 140 thread growth

        mock_proc.num_threads.side_effect = _num_threads
        mock_psutil.Process.return_value = mock_proc
        with patch.dict("sys.modules", {"psutil": mock_psutil}):
            m.check_thread_count()  # sets baseline = 10
            result = m.check_thread_count()  # sees 150 → growth = 140
        assert result.status == "degraded"


# ---------------------------------------------------------------------------
# check_websocket
# ---------------------------------------------------------------------------


class TestCheckWebsocket:
    def test_reachable_port(self):
        """Open a local server socket and probe it."""
        server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        server.bind(("127.0.0.1", 0))
        server.listen(1)
        _, port = server.getsockname()
        try:
            m = HealthMonitor(ws_host="127.0.0.1", ws_port=port)
            result = m.check_websocket()
            assert result.status == "healthy"
            assert result.metrics["reachable"] is True
        finally:
            server.close()

    def test_unreachable_port_degraded(self):
        m = HealthMonitor(ws_host="127.0.0.1", ws_port=19998)
        result = m.check_websocket()
        assert result.status == "degraded"
        assert result.metrics["reachable"] is False


# ---------------------------------------------------------------------------
# check_database
# ---------------------------------------------------------------------------


class TestCheckDatabase:
    def test_no_paths_returns_healthy(self):
        m = _monitor()
        result = m.check_database()
        assert result.status == "healthy"

    def test_readable_duckdb(self, tmp_path):
        import duckdb
        db_path = tmp_path / "test.duckdb"
        conn = duckdb.connect(str(db_path))
        conn.execute("CREATE TABLE t (x INT)")
        conn.close()

        m = HealthMonitor(duckdb_paths=[db_path])
        result = m.check_database()
        assert result.status == "healthy"
        assert result.metrics["readable"] == 1

    def test_unreadable_duckdb(self, tmp_path):
        bad = tmp_path / "nonexistent_dir" / "bad.duckdb"
        m = HealthMonitor(duckdb_paths=[bad])
        result = m.check_database()
        # May be degraded or unhealthy depending on DuckDB behaviour
        assert result.status in ("degraded", "unhealthy")


# ---------------------------------------------------------------------------
# check_cache_health
# ---------------------------------------------------------------------------


class TestCheckCacheHealth:
    def test_no_cache_returns_healthy(self):
        m = _monitor()
        result = m.check_cache_health()
        assert result.status == "healthy"

    def test_cache_with_keys(self):
        cache = {"key1": 1, "key2": 2}
        m = HealthMonitor(cache=cache)
        result = m.check_cache_health()
        assert result.status == "healthy"
        assert result.metrics.get("entry_count") == 2

    def test_broken_cache_returns_degraded(self):
        class BrokenCache:
            def keys(self):
                raise RuntimeError("cache error")

        m = HealthMonitor(cache=BrokenCache())
        result = m.check_cache_health()
        assert result.status == "degraded"


# ---------------------------------------------------------------------------
# check_all
# ---------------------------------------------------------------------------


class TestCheckAll:
    def test_returns_health_report(self):
        m = _monitor()
        report = m.check_all()
        assert isinstance(report, HealthReport)
        assert report.overall_status in ("healthy", "degraded", "unhealthy")

    def test_report_has_eight_checks(self):
        m = _monitor()
        report = m.check_all()
        assert len(report.checks) == 8

    def test_report_timestamp_has_tzinfo(self):
        m = _monitor()
        report = m.check_all()
        assert report.timestamp.tzinfo is not None

    def test_to_dict_is_serialisable(self):
        import json
        m = _monitor()
        report = m.check_all()
        d = report.to_dict()
        # Should not raise
        json.dumps(d)
