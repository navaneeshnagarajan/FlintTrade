"""Tests for packages/core/src/traffic_logger.py.

Covers: log(), recent(), stats(), count(), export_csv(),
        should_skip_path(), status filter, pagination.
"""

from __future__ import annotations

import csv
import io
from datetime import datetime, timedelta, timezone

import pytest

from packages.core.src.traffic_logger import TrafficLogger, should_skip_path

IST = timezone(timedelta(hours=5, minutes=30))


@pytest.fixture
def tl() -> TrafficLogger:
    """In-memory TrafficLogger for isolated tests."""
    return TrafficLogger(":memory:")


# ---------------------------------------------------------------------------
# Logging / writes
# ---------------------------------------------------------------------------


def test_log_returns_entry_id(tl: TrafficLogger) -> None:
    """log() returns a non-empty hex entry_id string."""
    eid = tl.log("127.0.0.1", "GET", "/v1/health", 200, 4.2)
    assert isinstance(eid, str)
    assert len(eid) == 16  # secrets.token_hex(8) == 16 hex chars


def test_log_increments_count(tl: TrafficLogger) -> None:
    """Each log() call increases count() by 1."""
    assert tl.count() == 0
    tl.log("10.0.0.1", "POST", "/v1/orders/place", 200, 18.5)
    assert tl.count() == 1
    tl.log("10.0.0.2", "GET", "/v1/health", 200, 3.1)
    assert tl.count() == 2


def test_log_optional_fields_default_to_none(tl: TrafficLogger) -> None:
    """Calling log() with only required fields succeeds."""
    eid = tl.log("1.2.3.4", "GET", "/v1/test", 200, 5.0)
    entries = tl.recent(limit=1)
    assert entries[0]["entry_id"] == eid
    assert entries[0]["user_agent"] is None
    assert entries[0]["request_size"] is None
    assert entries[0]["response_size"] is None
    assert entries[0]["user_id"] is None


def test_log_all_fields_stored(tl: TrafficLogger) -> None:
    """All optional fields are stored and retrieved correctly."""
    eid = tl.log(
        ip="192.168.1.1",
        method="POST",
        path="/v1/orders/place",
        status_code=201,
        duration_ms=25.7,
        user_agent="Mozilla/5.0",
        request_size=128,
        response_size=256,
        user_id="nav",
    )
    entries = tl.recent(limit=1)
    e = entries[0]
    assert e["entry_id"] == eid
    assert e["ip"] == "192.168.1.1"
    assert e["method"] == "POST"
    assert e["path"] == "/v1/orders/place"
    assert e["status_code"] == 201
    assert e["user_agent"] == "Mozilla/5.0"
    assert e["request_size"] == 128
    assert e["response_size"] == 256
    assert e["user_id"] == "nav"


# ---------------------------------------------------------------------------
# recent()
# ---------------------------------------------------------------------------


def test_recent_ordered_newest_first(tl: TrafficLogger) -> None:
    """recent() returns entries in descending timestamp order."""
    tl.log("1.1.1.1", "GET", "/a", 200, 1.0)
    tl.log("1.1.1.1", "GET", "/b", 200, 2.0)
    tl.log("1.1.1.1", "GET", "/c", 200, 3.0)
    entries = tl.recent(limit=3)
    paths = [e["path"] for e in entries]
    # Most recent (/c) should be first
    assert paths[0] == "/c"


def test_recent_status_filter(tl: TrafficLogger) -> None:
    """status_filter param restricts results to that exact status code."""
    tl.log("1.1.1.1", "GET", "/ok", 200, 5.0)
    tl.log("1.1.1.1", "GET", "/err", 500, 5.0)
    tl.log("1.1.1.1", "GET", "/notfound", 404, 5.0)

    only_errors = tl.recent(status_filter=500)
    assert len(only_errors) == 1
    assert only_errors[0]["status_code"] == 500


def test_recent_pagination(tl: TrafficLogger) -> None:
    """Offset parameter skips rows correctly."""
    for i in range(10):
        tl.log("1.1.1.1", "GET", f"/p{i}", 200, float(i))

    page1 = tl.recent(limit=5, offset=0)
    page2 = tl.recent(limit=5, offset=5)
    all_entries = tl.recent(limit=10)

    assert len(page1) == 5
    assert len(page2) == 5
    combined = [e["entry_id"] for e in page1] + [e["entry_id"] for e in page2]
    assert combined == [e["entry_id"] for e in all_entries]


def test_recent_limit_clamped(tl: TrafficLogger) -> None:
    """limit is clamped to at most 1000."""
    for i in range(5):
        tl.log("1.1.1.1", "GET", f"/p{i}", 200, 1.0)
    entries = tl.recent(limit=9999)
    assert len(entries) == 5  # only 5 rows exist


# ---------------------------------------------------------------------------
# stats()
# ---------------------------------------------------------------------------


def test_stats_empty(tl: TrafficLogger) -> None:
    """stats() returns zeroed structure when no rows exist."""
    s = tl.stats()
    assert s["total_requests"] == 0
    assert s["error_rate"] == 0.0
    assert s["avg_duration_ms"] == 0.0
    assert s["p95_duration_ms"] == 0.0
    assert s["top_paths"] == []


def test_stats_error_rate(tl: TrafficLogger) -> None:
    """error_rate is computed as (4xx+5xx) / total."""
    tl.log("1.1.1.1", "GET", "/ok", 200, 10.0)
    tl.log("1.1.1.1", "GET", "/ok2", 200, 10.0)
    tl.log("1.1.1.1", "GET", "/bad", 500, 10.0)

    s = tl.stats()
    assert s["total_requests"] == 3
    assert abs(s["error_rate"] - (1 / 3)) < 0.001


def test_stats_top_paths(tl: TrafficLogger) -> None:
    """top_paths lists the most frequently requested paths."""
    for _ in range(5):
        tl.log("1.1.1.1", "GET", "/popular", 200, 1.0)
    tl.log("1.1.1.1", "GET", "/rare", 200, 1.0)

    s = tl.stats()
    assert s["top_paths"][0]["path"] == "/popular"
    assert s["top_paths"][0]["count"] == 5


def test_stats_since_filter(tl: TrafficLogger) -> None:
    """stats(since=...) only counts entries after the cutoff."""
    tl.log("1.1.1.1", "GET", "/old", 200, 5.0)

    # Query with a future cutoff — should return zero
    future = datetime.now(timezone.utc) + timedelta(hours=1)
    s = tl.stats(since=future)
    assert s["total_requests"] == 0


# ---------------------------------------------------------------------------
# export_csv()
# ---------------------------------------------------------------------------


def test_export_csv_headers(tl: TrafficLogger) -> None:
    """CSV export contains the expected header row."""
    tl.log("1.1.1.1", "GET", "/test", 200, 3.0)
    csv_str = tl.export_csv()
    reader = csv.reader(io.StringIO(csv_str))
    headers = next(reader)
    assert "entry_id" in headers
    assert "ip" in headers
    assert "status_code" in headers
    assert "duration_ms" in headers


def test_export_csv_row_count(tl: TrafficLogger) -> None:
    """CSV export has exactly N data rows (plus 1 header)."""
    for i in range(3):
        tl.log("1.1.1.1", "GET", f"/r{i}", 200, 1.0)
    csv_str = tl.export_csv()
    lines = [line for line in csv_str.strip().splitlines() if line]
    # 1 header + 3 data rows
    assert len(lines) == 4


# ---------------------------------------------------------------------------
# should_skip_path()
# ---------------------------------------------------------------------------


def test_skip_static_paths() -> None:
    """Static, favicon, and admin traffic routes are skipped."""
    assert should_skip_path("/static/css/main.css") is True
    assert should_skip_path("/favicon.ico") is True
    assert should_skip_path("/v1/admin/traffic") is True
    assert should_skip_path("/api/v1/traffic/stats") is True


def test_skip_does_not_skip_normal_paths() -> None:
    """Normal API paths are not skipped."""
    assert should_skip_path("/v1/orders/place") is False
    assert should_skip_path("/api/v1/health") is False
    assert should_skip_path("/v1/auth/login") is False


# ---------------------------------------------------------------------------
# Context manager
# ---------------------------------------------------------------------------


def test_context_manager() -> None:
    """TrafficLogger can be used as a context manager."""
    with TrafficLogger(":memory:") as tl:
        tl.log("1.1.1.1", "GET", "/cm", 200, 1.0)
        assert tl.count() == 1
    # No exception means close() was called successfully.
