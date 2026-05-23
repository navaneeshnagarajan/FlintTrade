"""Tests for packages/core/core/src/api_analyzer.py.

Covers: log_call(), recent(), replay(), count(), sanitisation,
        pagination, route filter, context manager.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from flinttrade_core.api_analyzer import APIAnalyzer, _sanitise


@pytest.fixture
def az() -> APIAnalyzer:
    """In-memory APIAnalyzer for isolated tests."""
    return APIAnalyzer(":memory:")


# ---------------------------------------------------------------------------
# _sanitise() helper
# ---------------------------------------------------------------------------


def test_sanitise_redacts_sensitive_keys() -> None:
    """_sanitise() replaces known sensitive keys with [REDACTED]."""
    raw = {
        "symbol": "NIFTY",
        "password": "hunter2",
        "api_key": "secret-key",
        "apikey": "another-key",
        "token": "jwt.token",
        "totp": "123456",
        "otp": "654321",
        "pin": "1234",
        "secret": "top-secret",
    }
    sanitised = _sanitise(raw)
    assert sanitised["symbol"] == "NIFTY"
    for key in ("password", "api_key", "apikey", "token", "totp", "otp", "pin", "secret"):
        assert sanitised[key] == "[REDACTED]"


def test_sanitise_none_returns_none() -> None:
    """_sanitise(None) returns None unchanged."""
    assert _sanitise(None) is None


def test_sanitise_non_dict_passthrough() -> None:
    """_sanitise() returns non-dict values unchanged."""
    assert _sanitise("plain string") == "plain string"  # type: ignore[arg-type]


def test_sanitise_preserves_non_sensitive_keys() -> None:
    """Non-sensitive keys are preserved exactly."""
    raw = {"symbol": "NIFTY", "qty": 50, "side": "BUY"}
    sanitised = _sanitise(raw)
    assert sanitised == raw


# ---------------------------------------------------------------------------
# log_call()
# ---------------------------------------------------------------------------


def test_log_call_returns_call_id(az: APIAnalyzer) -> None:
    """log_call() returns a 16-character hex call_id."""
    cid = az.log_call("/v1/health", "GET", None, 200, None, 3.1)
    assert isinstance(cid, str)
    assert len(cid) == 16


def test_log_call_increments_count(az: APIAnalyzer) -> None:
    """Each log_call() increases count() by 1."""
    assert az.count() == 0
    az.log_call("/v1/health", "GET", None, 200, None, 3.1)
    assert az.count() == 1
    az.log_call("/v1/orders/place", "POST", {"symbol": "NIFTY"}, 200, {"status": "ok"}, 18.5)
    assert az.count() == 2


def test_log_call_sensitive_fields_redacted(az: APIAnalyzer) -> None:
    """Sensitive keys in request/response bodies are redacted on storage."""
    az.log_call(
        "/v1/auth/login",
        "POST",
        request_body={"username": "nav", "password": "s3cr3t"},
        response_status=200,
        response_body={"token": "jwt.abc", "status": "ok"},
        duration_ms=5.0,
    )
    records = az.recent(limit=1)
    r = records[0]
    assert r["request_body"]["password"] == "[REDACTED]"
    assert r["request_body"]["username"] == "nav"
    assert r["response_body"]["token"] == "[REDACTED]"
    assert r["response_body"]["status"] == "ok"


def test_log_call_none_bodies_stored(az: APIAnalyzer) -> None:
    """None request/response bodies are stored and returned as None."""
    az.log_call("/v1/health", "GET", None, 200, None, 2.0)
    records = az.recent(limit=1)
    assert records[0]["request_body"] is None
    assert records[0]["response_body"] is None


def test_log_call_all_fields_stored(az: APIAnalyzer) -> None:
    """All fields passed to log_call() are persisted and retrieved."""
    cid = az.log_call(
        route="/v1/orders/place",
        method="POST",
        request_body={"symbol": "NIFTY", "qty": 50},
        response_status=201,
        response_body={"orderid": "ORD001"},
        duration_ms=25.7,
        user_id="nav",
    )
    records = az.recent(limit=1)
    r = records[0]
    assert r["call_id"] == cid
    assert r["route"] == "/v1/orders/place"
    assert r["method"] == "POST"
    assert r["response_status"] == 201
    assert abs(r["duration_ms"] - 25.7) < 0.01
    assert r["user_id"] == "nav"
    assert r["request_body"]["qty"] == 50
    assert r["response_body"]["orderid"] == "ORD001"


# ---------------------------------------------------------------------------
# recent()
# ---------------------------------------------------------------------------


def test_recent_ordered_newest_first(az: APIAnalyzer) -> None:
    """recent() returns entries ordered by timestamp descending."""
    az.log_call("/v1/a", "GET", None, 200, None, 1.0)
    az.log_call("/v1/b", "GET", None, 200, None, 1.0)
    az.log_call("/v1/c", "GET", None, 200, None, 1.0)
    records = az.recent(limit=3)
    routes = [r["route"] for r in records]
    assert routes[0] == "/v1/c"


def test_recent_route_filter(az: APIAnalyzer) -> None:
    """route_filter restricts results to matching prefix."""
    az.log_call("/v1/orders/place", "POST", None, 200, None, 10.0)
    az.log_call("/v1/orders/cancel", "POST", None, 200, None, 5.0)
    az.log_call("/v1/health", "GET", None, 200, None, 2.0)

    orders = az.recent(route_filter="/v1/orders")
    assert len(orders) == 2
    assert all(r["route"].startswith("/v1/orders") for r in orders)


def test_recent_pagination(az: APIAnalyzer) -> None:
    """offset skips rows correctly."""
    for i in range(6):
        az.log_call(f"/v1/r{i}", "GET", None, 200, None, 1.0)

    page1 = az.recent(limit=3, offset=0)
    page2 = az.recent(limit=3, offset=3)
    all_records = az.recent(limit=6)

    combined = [r["call_id"] for r in page1] + [r["call_id"] for r in page2]
    assert combined == [r["call_id"] for r in all_records]


def test_recent_limit_clamped(az: APIAnalyzer) -> None:
    """limit is clamped to 1000 and does not raise."""
    for i in range(3):
        az.log_call(f"/v1/r{i}", "GET", None, 200, None, 1.0)
    records = az.recent(limit=9999)
    assert len(records) == 3


# ---------------------------------------------------------------------------
# replay()
# ---------------------------------------------------------------------------


def test_replay_returns_full_record(az: APIAnalyzer) -> None:
    """replay(call_id) returns a dict with all fields populated."""
    cid = az.log_call(
        "/v1/orders/place", "POST",
        {"symbol": "NIFTY"}, 200, {"orderid": "ORD001"}, 20.0,
    )
    replayed = az.replay(cid)
    assert replayed["call_id"] == cid
    assert replayed["route"] == "/v1/orders/place"
    assert replayed["request_body"]["symbol"] == "NIFTY"


def test_replay_not_found_returns_empty(az: APIAnalyzer) -> None:
    """replay() returns an empty dict when call_id does not exist."""
    result = az.replay("nonexistent_id_12345")
    assert result == {}


# ---------------------------------------------------------------------------
# count()
# ---------------------------------------------------------------------------


def test_count_route_filter(az: APIAnalyzer) -> None:
    """count(route_filter=...) counts only matching routes."""
    az.log_call("/v1/orders/place", "POST", None, 200, None, 5.0)
    az.log_call("/v1/orders/cancel", "POST", None, 200, None, 5.0)
    az.log_call("/v1/health", "GET", None, 200, None, 2.0)
    assert az.count(route_filter="/v1/orders") == 2
    assert az.count(route_filter="/v1/health") == 1
    assert az.count() == 3


def test_count_since_filter(az: APIAnalyzer) -> None:
    """count(since=future) returns 0 when all records pre-date the cutoff."""
    az.log_call("/v1/health", "GET", None, 200, None, 1.0)
    future = datetime.now(timezone.utc) + timedelta(hours=1)
    assert az.count(since=future) == 0


# ---------------------------------------------------------------------------
# Context manager
# ---------------------------------------------------------------------------


def test_context_manager() -> None:
    """APIAnalyzer can be used as a context manager."""
    with APIAnalyzer(":memory:") as az:
        az.log_call("/v1/health", "GET", None, 200, None, 1.0)
        assert az.count() == 1


# ---------------------------------------------------------------------------
# enable / disable / is_enabled
# ---------------------------------------------------------------------------


def test_enable_disable_toggle(az: APIAnalyzer) -> None:
    """enable() / disable() toggle the _enabled flag."""
    az.disable()
    assert az.is_enabled() is False
    az.enable()
    assert az.is_enabled() is True


def test_disabled_analyzer_does_not_persist_call(az: APIAnalyzer) -> None:
    """When disabled, log_call() returns a call_id but writes no row."""
    az.disable()
    call_id = az.log_call("/v1/health", "GET", None, 200, None, 1.0)
    assert isinstance(call_id, str)
    assert az.count() == 0  # no row written


def test_reenabled_analyzer_resumes_logging(az: APIAnalyzer) -> None:
    """After re-enabling, log_call() persists normally again."""
    az.disable()
    az.log_call("/v1/a", "GET", None, 200, None, 1.0)  # not stored
    az.enable()
    az.log_call("/v1/b", "GET", None, 200, None, 1.0)  # stored
    assert az.count() == 1


# ---------------------------------------------------------------------------
# clear_logs
# ---------------------------------------------------------------------------


def test_clear_logs_deletes_all_rows(az: APIAnalyzer) -> None:
    """clear_logs() with no arguments removes every row."""
    for _ in range(5):
        az.log_call("/v1/health", "GET", None, 200, None, 1.0)
    deleted = az.clear_logs()
    assert deleted == 5
    assert az.count() == 0


def test_clear_logs_older_than_keeps_recent(az: APIAnalyzer) -> None:
    """clear_logs(older_than_days=0) deletes only rows older than cutoff."""
    # All rows are inserted now; with older_than_days=0 they are NOT older
    # than 0 days (cutoff = now), so nothing should be deleted.
    az.log_call("/v1/health", "GET", None, 200, None, 1.0)
    az.log_call("/v1/health", "GET", None, 200, None, 1.0)
    # Rows are current — older_than_days=1 should keep them all.
    deleted = az.clear_logs(older_than_days=1)
    assert deleted == 0
    assert az.count() == 2
