"""Tests for packages/services/engine/src/latency_monitor.py.

Covers: record(), percentiles(), percentiles_by_broker(), histogram(),
        slowest_recent(), count(), window filtering, context manager.
"""

from __future__ import annotations

import pytest

from flinttrade_engine.latency_monitor import LatencyMonitor


@pytest.fixture
def mon() -> LatencyMonitor:
    """In-memory LatencyMonitor for isolated tests."""
    return LatencyMonitor(":memory:")


# ---------------------------------------------------------------------------
# record()
# ---------------------------------------------------------------------------


def test_record_returns_entry_id(mon: LatencyMonitor) -> None:
    """record() returns a 16-character hex entry_id."""
    eid = mon.record("ZERODHA", "PLACE", 42.0)
    assert isinstance(eid, str)
    assert len(eid) == 16


def test_record_increments_count(mon: LatencyMonitor) -> None:
    """Each record() call increases count() by 1."""
    assert mon.count() == 0
    mon.record("ZERODHA", "PLACE", 10.0)
    assert mon.count() == 1
    mon.record("ZERODHA", "CANCEL", 5.0)
    assert mon.count() == 2


def test_record_optional_fields(mon: LatencyMonitor) -> None:
    """Optional fields default to None / SUCCESS without raising."""
    eid = mon.record("ZERODHA", "PLACE", 20.0)
    slow = mon.slowest_recent(limit=1)
    assert slow[0]["entry_id"] == eid
    assert slow[0]["status"] == "SUCCESS"
    assert slow[0]["symbol"] is None
    assert slow[0]["user_id"] is None


def test_record_all_fields(mon: LatencyMonitor) -> None:
    """All optional fields are stored correctly."""
    mon.record("ZERODHA", "PLACE", 99.9, status="FAILED", symbol="NIFTY", user_id="nav")
    slow = mon.slowest_recent(limit=1)
    r = slow[0]
    assert r["broker"] == "ZERODHA"
    assert r["order_type"] == "PLACE"
    assert abs(r["latency_ms"] - 99.9) < 0.01
    assert r["status"] == "FAILED"
    assert r["symbol"] == "NIFTY"
    assert r["user_id"] == "nav"


# ---------------------------------------------------------------------------
# percentiles()
# ---------------------------------------------------------------------------


def test_percentiles_empty(mon: LatencyMonitor) -> None:
    """percentiles() returns zeroed structure when no rows exist."""
    p = mon.percentiles()
    assert p["count"] == 0
    assert p["p50"] == 0.0
    assert p["p95"] == 0.0
    assert p["p99"] == 0.0
    assert p["mean"] == 0.0


def test_percentiles_single(mon: LatencyMonitor) -> None:
    """With one record, all percentiles equal that value."""
    mon.record("ZERODHA", "PLACE", 50.0)
    p = mon.percentiles(broker="ZERODHA")
    assert p["count"] == 1
    assert p["p50"] == 50.0
    assert p["p95"] == 50.0
    assert p["p99"] == 50.0
    assert p["mean"] == 50.0


def test_percentiles_broker_filter(mon: LatencyMonitor) -> None:
    """percentiles(broker=...) filters to that broker only."""
    for _ in range(5):
        mon.record("ZERODHA", "PLACE", 10.0)
    for _ in range(5):
        mon.record("ANGEL", "PLACE", 100.0)

    p_z = mon.percentiles(broker="ZERODHA")
    p_a = mon.percentiles(broker="ANGEL")

    assert p_z["count"] == 5
    assert p_a["count"] == 5
    # ANGEL mean is much higher than ZERODHA mean
    assert p_a["mean"] > p_z["mean"]


def test_percentiles_all_brokers(mon: LatencyMonitor) -> None:
    """percentiles() with no broker arg aggregates all."""
    mon.record("ZERODHA", "PLACE", 10.0)
    mon.record("ANGEL", "PLACE", 20.0)
    p = mon.percentiles()
    assert p["count"] == 2
    assert abs(p["mean"] - 15.0) < 0.01


# ---------------------------------------------------------------------------
# percentiles_by_broker()
# ---------------------------------------------------------------------------


def test_percentiles_by_broker_keys(mon: LatencyMonitor) -> None:
    """percentiles_by_broker() returns one key per unique broker."""
    mon.record("ZERODHA", "PLACE", 10.0)
    mon.record("ANGEL", "PLACE", 20.0)
    mon.record("ZERODHA", "CANCEL", 5.0)

    stats = mon.percentiles_by_broker()
    assert "ZERODHA" in stats
    assert "ANGEL" in stats
    assert stats["ZERODHA"]["count"] == 2
    assert stats["ANGEL"]["count"] == 1


# ---------------------------------------------------------------------------
# histogram()
# ---------------------------------------------------------------------------


def test_histogram_empty(mon: LatencyMonitor) -> None:
    """histogram() returns an empty list when no data exists."""
    result = mon.histogram("ZERODHA")
    assert result == []


def test_histogram_single_value(mon: LatencyMonitor) -> None:
    """With a single distinct value, one bucket contains all observations."""
    mon.record("ZERODHA", "PLACE", 50.0)
    buckets = mon.histogram("ZERODHA", bins=10)
    total_count = sum(b["count"] for b in buckets)
    assert total_count == 1


def test_histogram_bucket_count(mon: LatencyMonitor) -> None:
    """histogram() returns the requested number of bins."""
    for lat in [10.0, 20.0, 30.0, 40.0, 50.0, 60.0, 70.0, 80.0, 90.0, 100.0]:
        mon.record("ZERODHA", "PLACE", lat)
    buckets = mon.histogram("ZERODHA", bins=5)
    assert len(buckets) == 5


def test_histogram_counts_sum_to_total(mon: LatencyMonitor) -> None:
    """Sum of histogram bucket counts equals total records for that broker."""
    for lat in [10.0, 20.0, 30.0, 40.0, 50.0]:
        mon.record("ZERODHA", "PLACE", lat)
    buckets = mon.histogram("ZERODHA", bins=5)
    assert sum(b["count"] for b in buckets) == 5


def test_histogram_bucket_structure(mon: LatencyMonitor) -> None:
    """Each histogram bucket has bucket_start, bucket_end, count keys."""
    mon.record("ZERODHA", "PLACE", 20.0)
    mon.record("ZERODHA", "PLACE", 80.0)
    buckets = mon.histogram("ZERODHA", bins=4)
    for b in buckets:
        assert "bucket_start" in b
        assert "bucket_end" in b
        assert "count" in b
        assert b["bucket_end"] > b["bucket_start"]


# ---------------------------------------------------------------------------
# slowest_recent()
# ---------------------------------------------------------------------------


def test_slowest_recent_ordering(mon: LatencyMonitor) -> None:
    """slowest_recent() returns records ordered by latency descending."""
    for lat in [5.0, 100.0, 50.0, 200.0, 10.0]:
        mon.record("ZERODHA", "PLACE", lat)
    slow = mon.slowest_recent(limit=5)
    latencies = [r["latency_ms"] for r in slow]
    assert latencies == sorted(latencies, reverse=True)


def test_slowest_recent_limit(mon: LatencyMonitor) -> None:
    """slowest_recent(limit=N) returns at most N records."""
    for lat in [10.0, 20.0, 30.0, 40.0, 50.0]:
        mon.record("ZERODHA", "PLACE", lat)
    slow = mon.slowest_recent(limit=3)
    assert len(slow) == 3


def test_slowest_recent_limit_clamped(mon: LatencyMonitor) -> None:
    """slowest_recent() clamps limit to 200."""
    for i in range(5):
        mon.record("ZERODHA", "PLACE", float(i))
    slow = mon.slowest_recent(limit=9999)
    assert len(slow) == 5


# ---------------------------------------------------------------------------
# count()
# ---------------------------------------------------------------------------


def test_count_broker_filter(mon: LatencyMonitor) -> None:
    """count(broker=...) only counts rows for that broker."""
    mon.record("ZERODHA", "PLACE", 10.0)
    mon.record("ZERODHA", "PLACE", 10.0)
    mon.record("ANGEL", "PLACE", 10.0)
    assert mon.count(broker="ZERODHA") == 2
    assert mon.count(broker="ANGEL") == 1
    assert mon.count() == 3


# ---------------------------------------------------------------------------
# Context manager
# ---------------------------------------------------------------------------


def test_context_manager() -> None:
    """LatencyMonitor can be used as a context manager."""
    with LatencyMonitor(":memory:") as m:
        m.record("ZERODHA", "PLACE", 42.0)
        assert m.count() == 1


# ---------------------------------------------------------------------------
# Default database location (workspace path unification, wave 1)
# ---------------------------------------------------------------------------


class TestDefaultDbPath:
    """The default latency-log database lives inside the active workspace.

    The latency log is disposable observability data, so there is no legacy
    migration to test — only the routing. Every test sets
    ``FLINTTRADE_WORKSPACE_DIR`` explicitly so the resolver can never reach
    the developer's real home directory.
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
    def test_resolves_under_the_workspace(self, tmp_path, monkeypatch):
        """_default_db_path() names latency_log.duckdb inside the workspace."""
        from flinttrade_engine.latency_monitor import _default_db_path

        expected = self._use_workspace(monkeypatch, tmp_path / "ws")
        assert _default_db_path() == expected / "latency_log.duckdb"

    @pytest.mark.unit
    def test_no_argument_monitor_opens_the_workspace_database(self, tmp_path, monkeypatch):
        """LatencyMonitor() with no db_path writes into the active workspace."""
        expected = self._use_workspace(monkeypatch, tmp_path / "ws") / "latency_log.duckdb"

        mon = LatencyMonitor()
        try:
            assert mon._db_path == str(expected)
            assert expected.exists()
        finally:
            mon.close()

    @pytest.mark.unit
    def test_explicit_db_path_bypasses_the_default(self, tmp_path, monkeypatch):
        """An explicit db_path wins over the workspace default."""
        self._use_workspace(monkeypatch, tmp_path / "ws")
        explicit = tmp_path / "elsewhere" / "custom.duckdb"

        mon = LatencyMonitor(explicit)
        try:
            assert mon._db_path == str(explicit)
            assert not (tmp_path / "ws" / "latency_log.duckdb").exists()
        finally:
            mon.close()

    @pytest.mark.unit
    def test_resolution_happens_per_call_not_at_import(self, tmp_path, monkeypatch):
        """Changing the override between calls changes the resolved path."""
        from flinttrade_engine.latency_monitor import _default_db_path

        first = self._use_workspace(monkeypatch, tmp_path / "one")
        assert _default_db_path() == first / "latency_log.duckdb"

        second = self._use_workspace(monkeypatch, tmp_path / "two")
        assert _default_db_path() == second / "latency_log.duckdb"
        assert first != second
