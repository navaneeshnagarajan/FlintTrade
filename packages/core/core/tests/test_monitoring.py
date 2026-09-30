"""Tests for HealthAggregator, TrafficCounter, and LatencyTracker.

Run with:
    python -m pytest packages/core/core/tests/test_monitoring.py -v --import-mode=importlib
"""
from __future__ import annotations

from unittest.mock import MagicMock

import pytest


# ---------------------------------------------------------------------------
# HealthAggregator
# ---------------------------------------------------------------------------


class TestHealthAggregator:

    def _make(self):
        from flinttrade_core.monitoring import HealthAggregator
        return HealthAggregator()

    def test_check_memory_returns_dict(self):
        agg = self._make()
        result = agg.check_memory()
        assert "status" in result
        assert result["status"] in ("ok", "degraded", "error", "unavailable")
        # A missing host reading must not be painted as 0/0 RAM.
        assert not (result.get("used_mb") == 0 and result.get("total_mb") == 0)
        if result.get("scope") == "host":
            assert result["total_mb"] > 0
            assert "used_mb" in result
            assert "used_pct" in result

    def test_check_disk_space_ok(self, tmp_path):
        agg = self._make()
        result = agg.check_disk_space(data_dir=tmp_path)
        assert "status" in result
        assert "free_gb" in result
        assert result["free_gb"] > 0
        assert result["scope"] == "host"
        assert result["used_pct"] == result["percent_used"]
        assert result["total_gb"] > 0

    def test_check_duckdb_readable(self, tmp_path):
        """Creates a valid DuckDB file and verifies check passes."""
        import duckdb
        db_path = tmp_path / "test.duckdb"
        conn = duckdb.connect(str(db_path))
        conn.execute("CREATE TABLE t (x INT)")
        conn.close()

        agg = self._make()
        result = agg.check_duckdb([db_path])
        assert result["readable"] == 1
        assert result["unreadable"] == 0
        assert result["status"] == "ok"

    def test_check_duckdb_nonexistent_file(self, tmp_path):
        """A missing DuckDB path may be created as empty — but unreadable tables."""
        agg = self._make()
        # Pass a clearly non-existent file in a non-existent dir
        bad_path = tmp_path / "no_such_dir" / "bad.duckdb"
        result = agg.check_duckdb([bad_path])
        # DuckDB may auto-create, but we just check the structure
        assert "readable" in result
        assert "unreadable" in result

    def test_check_broker_connections_no_registry(self):
        """With no registry, get_health returns ok note."""
        agg = self._make()
        health = agg.get_health(registry=None, duckdb_paths=None)
        assert health["status"] in ("ok", "degraded", "error")
        assert "broker" in health
        assert health["broker"].get("note") == "no registry provided"

    def test_get_health_structure(self):
        agg = self._make()
        health = agg.get_health()
        assert "status" in health
        assert "disk" in health
        assert "memory" in health

    def test_check_broker_connections_with_mock_registry(self):
        """Mock registry with one connected session."""

        class MockRegistry:
            def list_sessions(self):
                return [
                    {"account_id": "ACC1", "is_connected": True},
                    {"account_id": "ACC2", "is_connected": False},
                ]

        agg = self._make()
        result = agg.check_broker_connections(MockRegistry())
        assert result["connected"] == 1
        assert result["disconnected"] == 1
        assert result["total"] == 2
        assert result["status"] == "degraded"


# ---------------------------------------------------------------------------
# Install-host resources (FT-SET-MONITOR-001)
# ---------------------------------------------------------------------------


class TestHostResourceReadings:
    """Host totals stay distinct from process RSS and from invented zeros."""

    def _make(self):
        from flinttrade_core.monitoring import HealthAggregator
        return HealthAggregator()

    def _psutil(self, monkeypatch):
        from flinttrade_core import monitoring as monitoring_mod

        mock = MagicMock()
        monkeypatch.setattr(monitoring_mod, "_load_psutil", lambda: mock)
        return monitoring_mod, mock

    @pytest.mark.unit
    def test_memory_reports_host_totals_and_nests_process(self, monkeypatch):
        monitoring_mod, mock = self._psutil(monkeypatch)
        mock.virtual_memory.return_value = MagicMock(
            total=16 * 1024 ** 3,
            available=12 * 1024 ** 3,
            percent=25.0,
        )
        mock.Process.return_value.memory_info.return_value = MagicMock(
            rss=200 * 1024 ** 2,
            vms=800 * 1024 ** 2,
        )
        mock.Process.return_value.memory_percent.return_value = 1.25

        result = monitoring_mod.HealthAggregator().check_memory()

        assert result["scope"] == "host"
        assert result["total_mb"] == pytest.approx(16384.0, rel=0.01)
        assert result["used_mb"] == pytest.approx(4096.0, rel=0.01)
        assert result["used_pct"] == 25.0
        assert result["process"]["scope"] == "process"
        assert result["process"]["rss_mb"] == pytest.approx(200.0, rel=0.01)
        assert result["used_mb"] != result["process"]["rss_mb"]
        assert "rss_mb" not in result

    @pytest.mark.unit
    def test_process_rss_is_not_reported_as_host_memory(self, monkeypatch):
        monitoring_mod, mock = self._psutil(monkeypatch)
        mock.virtual_memory.side_effect = OSError("host ram unreadable")
        mock.Process.return_value.memory_info.return_value = MagicMock(
            rss=180 * 1024 ** 2,
            vms=900 * 1024 ** 2,
        )
        mock.Process.return_value.memory_percent.return_value = 1.1

        result = monitoring_mod.HealthAggregator().check_memory()

        assert result["scope"] == "process"
        assert result["status"] == "unavailable"
        assert "used_mb" not in result
        assert "total_mb" not in result
        assert "used_pct" not in result
        assert result["process"]["rss_mb"] == pytest.approx(180.0, rel=0.01)
        assert result["process"]["scope"] == "process"

    @pytest.mark.unit
    def test_missing_psutil_does_not_invent_zero_memory(self, monkeypatch):
        from flinttrade_core import monitoring as monitoring_mod

        monkeypatch.setattr(monitoring_mod, "_load_psutil", lambda: None)
        result = monitoring_mod.HealthAggregator().check_memory()

        assert result == {
            "status": "unavailable",
            "scope": "unavailable",
            "note": "Host memory unavailable",
        }

    @pytest.mark.unit
    def test_zero_host_ram_total_is_unavailable(self, monkeypatch):
        monitoring_mod, mock = self._psutil(monkeypatch)
        mock.virtual_memory.return_value = MagicMock(total=0, available=0, percent=0.0)
        mock.Process.return_value.memory_info.side_effect = OSError("no process")

        result = monitoring_mod.HealthAggregator().check_memory()

        assert result["scope"] == "unavailable"
        assert "used_mb" not in result
        assert "total_mb" not in result

    @pytest.mark.unit
    def test_cpu_is_a_host_reading(self, monkeypatch):
        monitoring_mod, mock = self._psutil(monkeypatch)
        mock.cpu_percent.return_value = 12.5
        mock.cpu_count.return_value = 8

        result = monitoring_mod.HealthAggregator().check_cpu()

        assert result is not None
        assert result["scope"] == "host"
        assert result["used_pct"] == 12.5
        assert result["cores"] == 8
        mock.cpu_percent.assert_called_once_with(interval=0.1)

    @pytest.mark.unit
    def test_cpu_is_omitted_without_psutil(self, monkeypatch):
        from flinttrade_core import monitoring as monitoring_mod

        monkeypatch.setattr(monitoring_mod, "_load_psutil", lambda: None)
        assert monitoring_mod.HealthAggregator().check_cpu() is None

    @pytest.mark.unit
    def test_network_counters_are_host_scoped(self, monkeypatch):
        monitoring_mod, mock = self._psutil(monkeypatch)
        mock.net_io_counters.return_value = MagicMock(bytes_sent=1500, bytes_recv=2500)

        result = monitoring_mod.HealthAggregator().check_network()

        assert result == {
            "status": "ok",
            "scope": "host",
            "bytes_sent": 1500,
            "bytes_recv": 2500,
        }

    @pytest.mark.unit
    def test_network_is_omitted_when_counters_are_missing(self, monkeypatch):
        monitoring_mod, mock = self._psutil(monkeypatch)
        mock.net_io_counters.return_value = None
        assert monitoring_mod.HealthAggregator().check_network() is None

    @pytest.mark.unit
    def test_gpu_is_omitted_when_nvidia_smi_is_absent(self, monkeypatch):
        from flinttrade_core import monitoring as monitoring_mod

        monkeypatch.setattr(monitoring_mod.shutil, "which", lambda _name: None)
        assert monitoring_mod.HealthAggregator().check_gpu() is None

    @pytest.mark.unit
    def test_gpu_parses_a_real_nvidia_smi_row(self, monkeypatch):
        from flinttrade_core import monitoring as monitoring_mod

        monkeypatch.setattr(monitoring_mod.shutil, "which", lambda name: "/usr/bin/nvidia-smi")
        monkeypatch.setattr(
            monitoring_mod.subprocess,
            "run",
            lambda *args, **kwargs: MagicMock(returncode=0, stdout="Example GPU, 10, 512, 8192\n"),
        )

        result = monitoring_mod.HealthAggregator().check_gpu()

        assert result is not None
        assert result["scope"] == "host"
        assert result["name"] == "Example GPU"
        assert result["used_pct"] == 10.0
        assert result["used_mb"] == 512.0
        assert result["total_mb"] == 8192.0

    @pytest.mark.unit
    def test_gpu_does_not_invent_numbers_from_an_unreadable_probe(self, monkeypatch):
        from flinttrade_core import monitoring as monitoring_mod

        monkeypatch.setattr(monitoring_mod.shutil, "which", lambda name: "/usr/bin/nvidia-smi")
        monkeypatch.setattr(
            monitoring_mod.subprocess,
            "run",
            lambda *args, **kwargs: MagicMock(
                returncode=0,
                stdout="Example GPU, [N/A], [N/A], [N/A]\n",
            ),
        )

        assert monitoring_mod.HealthAggregator().check_gpu() is None

    @pytest.mark.unit
    def test_get_health_omits_unreadable_gpu_and_keeps_cpu_off_the_rollup(self, monkeypatch):
        agg = self._make()
        monkeypatch.setattr(agg, "check_cpu", lambda: {"status": "error", "scope": "host", "used_pct": 99.0})
        monkeypatch.setattr(agg, "check_gpu", lambda: None)
        monkeypatch.setattr(
            agg,
            "check_network",
            lambda: {"status": "ok", "scope": "host", "bytes_sent": 1, "bytes_recv": 2},
        )
        monkeypatch.setattr(
            agg,
            "check_disk_space",
            lambda data_dir=None: {
                "status": "ok",
                "scope": "host",
                "total_gb": 10.0,
                "free_gb": 5.0,
                "used_pct": 50.0,
                "percent_used": 50.0,
            },
        )
        monkeypatch.setattr(
            agg,
            "check_memory",
            lambda: {
                "status": "ok",
                "scope": "host",
                "used_mb": 1024.0,
                "total_mb": 2048.0,
                "used_pct": 50.0,
            },
        )

        health = agg.get_health()

        assert health["status"] == "ok"
        assert "gpu" not in health
        assert health["cpu"]["used_pct"] == 99.0
        assert health["network"]["scope"] == "host"
        assert health["memory"]["scope"] == "host"
        assert health["disk"]["used_pct"] == 50.0


# ---------------------------------------------------------------------------
# TrafficCounter
# ---------------------------------------------------------------------------


class TestTrafficCounter:

    def _make(self):
        from flinttrade_core.monitoring import TrafficCounter
        return TrafficCounter(buffer_size=1000)

    def test_empty_stats(self):
        tc = self._make()
        stats = tc.get_stats(minutes=5)
        assert stats["total_requests"] == 0
        assert stats["requests_per_sec"] == 0.0
        assert stats["error_rate"] == 0.0

    def test_record_and_get_recent(self):
        tc = self._make()
        tc.record("GET", "/v1/health", 200, 12.5)
        recent = tc.get_recent(n=10)
        assert len(recent) == 1
        assert recent[0]["method"] == "GET"
        assert recent[0]["path"] == "/v1/health"
        assert recent[0]["status"] == 200
        assert recent[0]["duration_ms"] == pytest.approx(12.5)

    def test_stats_error_rate(self):
        tc = self._make()
        tc.record("GET", "/v1/health", 200, 10.0)
        tc.record("GET", "/v1/bad", 500, 5.0)
        stats = tc.get_stats(minutes=60)
        assert stats["error_rate"] == pytest.approx(0.5)

    def test_stats_avg_latency(self):
        tc = self._make()
        tc.record("GET", "/a", 200, 10.0)
        tc.record("GET", "/b", 200, 20.0)
        stats = tc.get_stats(minutes=60)
        assert stats["avg_latency_ms"] == pytest.approx(15.0)

    def test_top_paths_sorted(self):
        tc = self._make()
        for _ in range(3):
            tc.record("GET", "/popular", 200, 1.0)
        tc.record("GET", "/less-popular", 200, 1.0)
        stats = tc.get_stats(minutes=60)
        assert stats["top_paths"][0]["path"] == "/popular"
        assert stats["top_paths"][0]["count"] == 3

    def test_get_recent_n_limit(self):
        tc = self._make()
        for i in range(10):
            tc.record("GET", f"/path/{i}", 200, float(i))
        recent = tc.get_recent(n=5)
        assert len(recent) == 5

    def test_circular_buffer_cap(self):
        from flinttrade_core.monitoring import TrafficCounter
        tc = TrafficCounter(buffer_size=3)
        for i in range(5):
            tc.record("GET", f"/path/{i}", 200, 1.0)
        recent = tc.get_recent(n=10)
        assert len(recent) == 3


# ---------------------------------------------------------------------------
# LatencyTracker
# ---------------------------------------------------------------------------


class TestLatencyTracker:

    def _make(self):
        from flinttrade_core.monitoring import LatencyTracker
        return LatencyTracker()

    def test_empty_stats(self):
        lt = self._make()
        assert lt.get_stats() == {}

    def test_record_and_get_stats(self):
        lt = self._make()
        lt.record_order_latency("BROKER_A", "NIFTY", 42.0)
        lt.record_order_latency("BROKER_A", "BANKNIFTY", 38.0)
        stats = lt.get_stats()
        assert "BROKER_A" in stats
        assert stats["BROKER_A"]["count"] == 2
        assert stats["BROKER_A"]["avg_ms"] == pytest.approx(40.0)

    def test_p95_p99_with_many_samples(self):
        lt = self._make()
        for i in range(100):
            lt.record_order_latency("BROKER_B", "NIFTY", float(i + 1))
        stats = lt.get_stats()
        broker = stats["BROKER_B"]
        assert broker["p50_ms"] < broker["p95_ms"]
        assert broker["p95_ms"] <= broker["p99_ms"]

    def test_per_broker_isolation(self):
        lt = self._make()
        lt.record_order_latency("BROKER_X", "RELIANCE", 10.0)
        lt.record_order_latency("BROKER_Y", "TCS", 200.0)
        stats = lt.get_stats()
        assert "BROKER_X" in stats
        assert "BROKER_Y" in stats
        assert stats["BROKER_X"]["avg_ms"] == pytest.approx(10.0)

    def test_get_recent(self):
        lt = self._make()
        lt.record_order_latency("BROKER_C", "HDFC", 55.0)
        recent = lt.get_recent(n=10)
        assert len(recent) == 1
        assert recent[0]["broker"] == "BROKER_C"
        assert recent[0]["symbol"] == "HDFC"
        assert recent[0]["latency_ms"] == pytest.approx(55.0)
        assert "timestamp" in recent[0]


# ---------------------------------------------------------------------------
# Default disk-probe directory (workspace path unification, wave 1)
# ---------------------------------------------------------------------------


class TestDefaultDataDir:
    """HealthAggregator's disk probe tracks the active workspace.

    Read-only probe: no legacy state is migrated, so these tests only pin
    *where* it looks. Every test sets ``FLINTTRADE_WORKSPACE_DIR`` explicitly
    so the resolver can never reach the developer's real home directory.
    """

    @staticmethod
    def _use_workspace(monkeypatch, root):
        """Point the workspace resolver at *root* and return its resolved form.

        Args:
            monkeypatch: pytest monkeypatch fixture.
            root: Directory to expose as the active workspace.

        Returns:
            The resolved workspace path the resolver will return.
        """
        monkeypatch.delenv("FLINTTRADE_HOME", raising=False)
        monkeypatch.setenv("FLINTTRADE_WORKSPACE_DIR", str(root))
        return root.resolve()

    @pytest.mark.unit
    def test_resolves_to_the_workspace_data_dir(self, tmp_path, monkeypatch):
        """_default_data_dir() returns ``data`` inside the overridden workspace."""
        from flinttrade_core.monitoring import _default_data_dir

        expected = self._use_workspace(monkeypatch, tmp_path / "ws")
        assert _default_data_dir() == expected / "data"

    @pytest.mark.unit
    def test_check_disk_space_probes_the_workspace_data_dir(self, tmp_path, monkeypatch):
        """A no-argument check_disk_space() measures the workspace data directory."""
        from flinttrade_core import monitoring as monitoring_mod

        expected = self._use_workspace(monkeypatch, tmp_path / "ws") / "data"
        expected.mkdir(parents=True)

        probed: list[str] = []
        real_disk_usage = monitoring_mod.shutil.disk_usage

        def _record(path):
            probed.append(path)
            return real_disk_usage(path)

        monkeypatch.setattr(monitoring_mod.shutil, "disk_usage", _record)

        result = monitoring_mod.HealthAggregator().check_disk_space()

        assert result["status"] in ("ok", "degraded", "error")
        assert probed == [str(expected)]

    @pytest.mark.unit
    def test_explicit_data_dir_bypasses_the_default(self, tmp_path, monkeypatch):
        """An explicit data_dir argument wins over the workspace default."""
        from flinttrade_core import monitoring as monitoring_mod

        self._use_workspace(monkeypatch, tmp_path / "ws")
        explicit = tmp_path / "elsewhere"
        explicit.mkdir()

        probed: list[str] = []
        real_disk_usage = monitoring_mod.shutil.disk_usage

        def _record(path):
            probed.append(path)
            return real_disk_usage(path)

        monkeypatch.setattr(monitoring_mod.shutil, "disk_usage", _record)

        monitoring_mod.HealthAggregator().check_disk_space(explicit)

        assert probed == [str(explicit)]

    @pytest.mark.unit
    def test_resolution_happens_per_call_not_at_import(self, tmp_path, monkeypatch):
        """Changing the override between calls changes the resolved directory."""
        from flinttrade_core.monitoring import _default_data_dir

        first = self._use_workspace(monkeypatch, tmp_path / "one")
        assert _default_data_dir() == first / "data"

        second = self._use_workspace(monkeypatch, tmp_path / "two")
        assert _default_data_dir() == second / "data"
        assert first != second
