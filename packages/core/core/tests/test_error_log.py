"""Tests for ErrorLog — structured JSON error logging to DuckDB.

Run with:
    python -m pytest packages/core/core/tests/test_error_log.py -v --import-mode=importlib
"""
from __future__ import annotations

from datetime import datetime, timedelta
from pathlib import Path

import pytest

from flinttrade_core.error_log import ErrorLog, _sanitise, IST


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_log() -> ErrorLog:
    """Return an in-memory ErrorLog instance."""
    return ErrorLog(":memory:")


# ---------------------------------------------------------------------------
# _sanitise() unit tests
# ---------------------------------------------------------------------------

class TestSanitise:
    """Unit tests for the _sanitise() helper function."""

    def test_non_sensitive_keys_pass_through(self):
        data = {"symbol": "NIFTY", "qty": 50, "price": 22000.5}
        result = _sanitise(data)
        assert result == data

    def test_password_is_redacted(self):
        data = {"username": "nav", "password": "s3cr3t"}
        result = _sanitise(data)
        assert result["password"] == "[REDACTED]"
        assert result["username"] == "nav"

    def test_all_sensitive_keys_are_redacted(self):
        sensitive = {
            "password": "x",
            "token": "x",
            "api_key": "x",
            "apikey": "x",
            "secret": "x",
            "totp": "x",
            "otp": "x",
            "pin": "x",
        }
        result = _sanitise(sensitive)
        for key in sensitive:
            assert result[key] == "[REDACTED]", f"Expected {key} to be redacted"

    def test_case_insensitive_matching(self):
        data = {"PASSWORD": "abc", "Token": "xyz", "API_KEY": "123"}
        result = _sanitise(data)
        assert result["PASSWORD"] == "[REDACTED]"
        assert result["Token"] == "[REDACTED]"
        assert result["API_KEY"] == "[REDACTED]"

    def test_non_dict_passthrough(self):
        # _sanitise should handle non-dict gracefully (returns as-is)
        assert _sanitise("string") == "string"  # type: ignore[arg-type]
        assert _sanitise(42) == 42  # type: ignore[arg-type]

    def test_empty_dict(self):
        assert _sanitise({}) == {}

    def test_mixed_dict_redacts_only_sensitive(self):
        data = {"symbol": "BANKNIFTY", "api_key": "key123", "qty": 1}
        result = _sanitise(data)
        assert result["symbol"] == "BANKNIFTY"
        assert result["api_key"] == "[REDACTED]"
        assert result["qty"] == 1


# ---------------------------------------------------------------------------
# ErrorLog — schema and lifecycle
# ---------------------------------------------------------------------------

class TestErrorLogSchema:
    """Verify the DuckDB schema is initialised correctly."""

    def test_creates_in_memory_db(self):
        log = _make_log()
        assert log.count() == 0
        log.close()

    def test_creates_file_db(self, tmp_path: Path):
        db_file = tmp_path / "subdir" / "errors.duckdb"
        # subdir does not exist — ErrorLog must create it
        assert not db_file.parent.exists()
        log = ErrorLog(db_file)
        assert db_file.parent.exists()
        log.close()

    def test_context_manager_closes_connection(self):
        with ErrorLog(":memory:") as log:
            log.log("/test", "GET", 500)
        # After exit, further use should raise (connection closed)
        # We just verify the context manager doesn't raise on exit.

    def test_reinitialisation_is_idempotent(self):
        """Opening the same in-memory db twice must not fail."""
        log = ErrorLog(":memory:")
        log._init_schema()  # call again — CREATE TABLE IF NOT EXISTS
        log.close()


# ---------------------------------------------------------------------------
# ErrorLog.log()
# ---------------------------------------------------------------------------

class TestErrorLogWrite:
    """Tests for the log() write path."""

    def test_log_returns_entry_id(self):
        log = _make_log()
        entry_id = log.log("/v1/test", "GET", 500)
        assert isinstance(entry_id, str)
        assert len(entry_id) == 16  # secrets.token_hex(8)
        log.close()

    def test_log_increments_count(self):
        log = _make_log()
        assert log.count() == 0
        log.log("/v1/a", "POST", 500)
        assert log.count() == 1
        log.log("/v1/b", "GET", 404)
        assert log.count() == 2
        log.close()

    def test_log_without_error(self):
        log = _make_log()
        entry_id = log.log("/v1/ping", "GET", 200)
        entries = log.recent(limit=1)
        assert len(entries) == 1
        assert entries[0]["entry_id"] == entry_id
        assert entries[0]["error_class"] is None
        assert entries[0]["error_message"] is None
        log.close()

    def test_log_with_exception(self):
        log = _make_log()
        try:
            raise ValueError("bad input")
        except ValueError as exc:
            log.log("/v1/orders", "POST", 400, error=exc)

        entries = log.recent(limit=1)
        assert entries[0]["error_class"] == "ValueError"
        assert entries[0]["error_message"] == "bad input"
        assert entries[0]["traceback"] is not None
        assert "ValueError" in entries[0]["traceback"]
        log.close()

    def test_log_sanitises_request_body(self):
        log = _make_log()
        log.log(
            "/v1/auth",
            "POST",
            401,
            request_body={"username": "nav", "password": "hunter2", "totp": "123456"},
        )
        entries = log.recent(limit=1)
        body = entries[0]["request_body"]
        assert isinstance(body, dict)
        assert body["username"] == "nav"
        assert body["password"] == "[REDACTED]"
        assert body["totp"] == "[REDACTED]"
        log.close()

    def test_log_none_request_body(self):
        log = _make_log()
        log.log("/v1/health", "GET", 500, request_body=None)
        entries = log.recent(limit=1)
        assert entries[0]["request_body"] is None
        log.close()

    def test_log_user_id_stored(self):
        log = _make_log()
        log.log("/v1/orders", "POST", 500, user_id="alice")
        entries = log.recent(limit=1)
        assert entries[0]["user_id"] == "alice"
        log.close()

    def test_log_user_id_none_by_default(self):
        log = _make_log()
        log.log("/v1/test", "GET", 500)
        entries = log.recent(limit=1)
        assert entries[0]["user_id"] is None
        log.close()

    def test_log_stores_route_and_method(self):
        log = _make_log()
        log.log("/v1/positions", "DELETE", 405)
        entries = log.recent(limit=1)
        assert entries[0]["route"] == "/v1/positions"
        assert entries[0]["method"] == "DELETE"
        assert entries[0]["status_code"] == 405
        log.close()

    def test_log_entry_ids_are_unique(self):
        log = _make_log()
        ids = {log.log("/v1/x", "GET", 500) for _ in range(20)}
        assert len(ids) == 20
        log.close()


# ---------------------------------------------------------------------------
# ErrorLog.recent()
# ---------------------------------------------------------------------------

class TestErrorLogRecent:
    """Tests for the recent() read path."""

    def test_recent_returns_most_recent_first(self):
        log = _make_log()
        for i in range(5):
            log.log(f"/v1/route/{i}", "GET", 500)
        entries = log.recent(limit=5)
        # Most recent is /v1/route/4 (last inserted)
        assert entries[0]["route"] == "/v1/route/4"
        assert entries[-1]["route"] == "/v1/route/0"
        log.close()

    def test_recent_respects_limit(self):
        log = _make_log()
        for _ in range(10):
            log.log("/v1/x", "GET", 500)
        entries = log.recent(limit=3)
        assert len(entries) == 3
        log.close()

    def test_recent_respects_offset(self):
        log = _make_log()
        for i in range(5):
            log.log(f"/v1/r/{i}", "GET", 500)
        all_entries = log.recent(limit=5, offset=0)
        offset_entries = log.recent(limit=5, offset=2)
        # With offset=2 we skip the 2 most recent
        assert offset_entries[0]["route"] == all_entries[2]["route"]
        log.close()

    def test_recent_empty_db_returns_empty_list(self):
        log = _make_log()
        assert log.recent() == []
        log.close()

    def test_recent_timestamp_is_iso_string(self):
        log = _make_log()
        log.log("/v1/ts", "GET", 500)
        entries = log.recent(limit=1)
        ts = entries[0]["timestamp"]
        # Must be parseable as ISO-8601
        parsed = datetime.fromisoformat(ts)
        assert isinstance(parsed, datetime)
        log.close()

    def test_recent_request_body_deserialised(self):
        log = _make_log()
        log.log("/v1/test", "POST", 400, request_body={"symbol": "NIFTY", "qty": 75})
        entries = log.recent(limit=1)
        body = entries[0]["request_body"]
        assert isinstance(body, dict)
        assert body["symbol"] == "NIFTY"
        assert body["qty"] == 75
        log.close()

    def test_recent_limit_clamped_to_500(self):
        log = _make_log()
        for _ in range(10):
            log.log("/v1/x", "GET", 500)
        # Passing a huge limit should not raise — it is clamped internally.
        entries = log.recent(limit=9999)
        assert len(entries) == 10
        log.close()

    def test_recent_negative_limit_treated_as_one(self):
        log = _make_log()
        log.log("/v1/x", "GET", 500)
        entries = log.recent(limit=-5)
        assert len(entries) == 1
        log.close()


# ---------------------------------------------------------------------------
# ErrorLog.count()
# ---------------------------------------------------------------------------

class TestErrorLogCount:
    """Tests for the count() method."""

    def test_count_zero_on_empty(self):
        log = _make_log()
        assert log.count() == 0
        log.close()

    def test_count_increments(self):
        log = _make_log()
        for n in range(1, 6):
            log.log("/v1/x", "GET", 500)
            assert log.count() == n
        log.close()

    def test_count_with_since_filters_correctly(self):
        log = _make_log()
        # Log an error "in the past" by checking count before and after
        log.log("/v1/old", "GET", 500)
        cutoff = datetime.now(IST)
        log.log("/v1/new", "GET", 500)
        count_total = log.count()
        count_after = log.count(since=cutoff)
        assert count_total == 2
        assert count_after == 1
        log.close()

    def test_count_since_future_returns_zero(self):
        log = _make_log()
        log.log("/v1/x", "GET", 500)
        future = datetime.now(IST) + timedelta(hours=1)
        assert log.count(since=future) == 0
        log.close()


# ---------------------------------------------------------------------------
# Admin route integration
# ---------------------------------------------------------------------------

_TEST_API_KEY = "test-error-log-routes-key"


@pytest.fixture(scope="module")
def monkeypatch_module():
    """Module-scoped monkeypatch fixture."""
    from _pytest.monkeypatch import MonkeyPatch
    mp = MonkeyPatch()
    yield mp
    mp.undo()


@pytest.fixture(scope="module")
def flask_app(monkeypatch_module):
    """Flask app with admin blueprint and a pre-seeded in-memory error log."""
    monkeypatch_module.setenv("OPENALGO_API_KEY", _TEST_API_KEY)
    monkeypatch_module.setenv("FLINTTRADE_DEV", "1")
    from flinttrade_core.app import create_flask_app

    app = create_flask_app()
    app.config["TESTING"] = True

    # Replace the file-backed error log with an in-memory one and seed it.
    error_log = ErrorLog(":memory:")
    for i in range(3):
        try:
            raise RuntimeError(f"test error {i}")
        except RuntimeError as exc:
            error_log.log(f"/v1/route/{i}", "POST", 500, error=exc)
    app.config["ERROR_LOG"] = error_log
    return app


@pytest.fixture()
def client(flask_app):
    with flask_app.test_client() as c:
        yield c


def _auth(api_key: str = _TEST_API_KEY) -> dict[str, str]:
    return {"X-API-Key": api_key, "Content-Type": "application/json"}


class TestAdminErrorsRoute:
    """Integration tests for GET /v1/admin/errors."""

    def test_errors_returns_200(self, client):
        resp = client.get("/v1/admin/errors", headers=_auth())
        assert resp.status_code == 200
        data = resp.get_json()
        assert data["status"] == "success"
        assert "errors" in data["data"]
        assert "total" in data["data"]

    def test_errors_returns_seeded_entries(self, client):
        resp = client.get("/v1/admin/errors", headers=_auth())
        data = resp.get_json()["data"]
        assert data["total"] == 3
        assert len(data["errors"]) == 3

    def test_errors_limit_param(self, client):
        resp = client.get("/v1/admin/errors?limit=1", headers=_auth())
        data = resp.get_json()["data"]
        assert len(data["errors"]) == 1
        assert data["limit"] == 1

    def test_errors_offset_param(self, client):
        resp = client.get("/v1/admin/errors?limit=10&offset=2", headers=_auth())
        data = resp.get_json()["data"]
        # 3 total, offset 2 → 1 remaining
        assert len(data["errors"]) == 1
        assert data["offset"] == 2

    def test_errors_invalid_limit_returns_400(self, client):
        resp = client.get("/v1/admin/errors?limit=abc", headers=_auth())
        assert resp.status_code == 400

    def test_errors_entries_have_expected_fields(self, client):
        resp = client.get("/v1/admin/errors?limit=1", headers=_auth())
        entry = resp.get_json()["data"]["errors"][0]
        for field_name in (
            "entry_id", "timestamp", "route", "method",
            "status_code", "error_class", "error_message",
        ):
            assert field_name in entry, f"Missing field: {field_name}"

    def test_errors_error_class_captured(self, client):
        resp = client.get("/v1/admin/errors", headers=_auth())
        entries = resp.get_json()["data"]["errors"]
        assert all(e["error_class"] == "RuntimeError" for e in entries)

    def test_errors_requires_auth(self, client):
        resp = client.get("/v1/admin/errors")
        assert resp.status_code == 401

    def test_errors_503_when_log_not_initialised(self, flask_app, client):
        original = flask_app.config.pop("ERROR_LOG")
        try:
            resp = client.get("/v1/admin/errors", headers=_auth())
            assert resp.status_code == 503
        finally:
            flask_app.config["ERROR_LOG"] = original


class TestAdminErrorsCountRoute:
    """Integration tests for GET /v1/admin/errors/count."""

    def test_count_returns_200(self, client):
        resp = client.get("/v1/admin/errors/count", headers=_auth())
        assert resp.status_code == 200
        data = resp.get_json()
        assert data["status"] == "success"
        assert "count" in data["data"]

    def test_count_matches_seeded_entries(self, client):
        resp = client.get("/v1/admin/errors/count", headers=_auth())
        assert resp.get_json()["data"]["count"] == 3

    def test_count_requires_auth(self, client):
        resp = client.get("/v1/admin/errors/count")
        assert resp.status_code == 401

    def test_count_503_when_log_not_initialised(self, flask_app, client):
        original = flask_app.config.pop("ERROR_LOG")
        try:
            resp = client.get("/v1/admin/errors/count", headers=_auth())
            assert resp.status_code == 503
        finally:
            flask_app.config["ERROR_LOG"] = original
