"""Tests for HealthAggregator, TrafficCounter, and LatencyTracker.

Run with:
    python -m pytest packages/core/core/tests/test_monitoring.py -v --import-mode=importlib
"""
from __future__ import annotations


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
        assert result["status"] in ("ok", "degraded", "error")

    def test_check_disk_space_ok(self, tmp_path):
        agg = self._make()
        result = agg.check_disk_space(data_dir=tmp_path)
        assert "status" in result
        assert "free_gb" in result
        assert result["free_gb"] > 0

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
