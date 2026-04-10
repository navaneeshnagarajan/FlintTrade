"""Tests for ActivityLog and the /api/v1/admin/activity endpoint.

Run with:
    python -m pytest packages/data/tests/test_activity_log.py -v --import-mode=importlib
"""

from __future__ import annotations

import os

import pytest


# ---------------------------------------------------------------------------
# ActivityLog unit tests
# ---------------------------------------------------------------------------


class TestActivityLog:
    """Test the ActivityLog DuckDB-backed mutation logger."""

    def _make_log(self):
        from packages.data.src.activity_log import ActivityLog

        return ActivityLog(":memory:")

    # --- log() ---

    def test_log_returns_log_id(self):
        log = self._make_log()
        log_id = log.log("order.place", {"symbol": "NIFTY"})
        assert isinstance(log_id, str)
        assert len(log_id) == 16  # 8 bytes → 16 hex chars
        log.close()

    def test_log_stores_action_and_details(self):
        log = self._make_log()
        log.log("order.place", {"symbol": "NIFTY", "qty": 50}, user="nav", ip="10.0.0.1")
        entries = log.query()
        assert len(entries) == 1
        e = entries[0]
        assert e.action == "order.place"
        assert e.user == "nav"
        assert e.ip == "10.0.0.1"
        assert e.details["symbol"] == "NIFTY"
        assert e.details["qty"] == 50
        log.close()

    def test_log_default_user_is_system(self):
        log = self._make_log()
        log.log("settings.update", {"key": "theme"})
        entries = log.query()
        assert entries[0].user == "system"
        log.close()

    def test_log_ip_can_be_none(self):
        log = self._make_log()
        log.log("auth.login", {}, user="admin", ip=None)
        entries = log.query()
        assert entries[0].ip is None
        log.close()

    def test_log_timestamp_is_datetime(self):
        from datetime import datetime

        log = self._make_log()
        log.log("mode.switch", {"from": "explore", "to": "live"})
        entries = log.query()
        ts = entries[0].timestamp
        # Timestamp is now a proper datetime object (TIMESTAMPTZ column).
        assert isinstance(ts, datetime)
        assert ts.year >= 2024
        log.close()

    # --- query() filters ---

    def test_query_filter_by_action(self):
        log = self._make_log()
        log.log("order.place", {"symbol": "NIFTY"})
        log.log("order.cancel", {"orderid": "123"})
        log.log("auth.login", {})
        results = log.query(action="order.place")
        assert len(results) == 1
        assert results[0].action == "order.place"
        log.close()

    def test_query_filter_by_user(self):
        log = self._make_log()
        log.log("order.place", {}, user="alice")
        log.log("order.place", {}, user="bob")
        log.log("order.place", {}, user="alice")
        results = log.query(user="alice")
        assert len(results) == 2
        assert all(e.user == "alice" for e in results)
        log.close()

    def test_query_limit_respected(self):
        log = self._make_log()
        for i in range(10):
            log.log("order.place", {"i": i})
        results = log.query(limit=3)
        assert len(results) == 3
        log.close()

    def test_query_returns_most_recent_first(self):
        log = self._make_log()
        log.log("strategy.start", {"name": "first"})
        log.log("strategy.start", {"name": "second"})
        log.log("strategy.start", {"name": "third"})
        results = log.query(action="strategy.start")
        # Most recent entry is "third" — ordered by TIMESTAMPTZ column DESC
        assert results[0].details["name"] == "third"
        log.close()

    def test_query_since_filter(self):
        """Entries before `since` must be excluded."""
        log = self._make_log()
        from datetime import datetime, timedelta, timezone

        IST = timezone(timedelta(hours=5, minutes=30))
        # Log an "old" entry with a backdated details field (timestamp is real)
        log.log("order.place", {"era": "old"}, user="ghost")
        log.log("auth.login", {"era": "new"})
        # Use a since value that excludes the first logged entry by using a
        # future bound — everything logged just now should pass
        future_bound = datetime(2099, 1, 1, tzinfo=IST).isoformat()
        results = log.query(since=future_bound)
        assert len(results) == 0
        log.close()

    # --- count_actions() ---

    def test_count_actions_basic(self):
        log = self._make_log()
        log.log("order.place", {})
        log.log("order.place", {})
        log.log("order.cancel", {})
        assert log.count_actions("order.place") == 2
        assert log.count_actions("order.cancel") == 1
        log.close()

    def test_count_actions_nonexistent_returns_zero(self):
        log = self._make_log()
        assert log.count_actions("ghost.action") == 0
        log.close()

    def test_count_actions_since_filters(self):
        from datetime import datetime, timedelta, timezone

        IST = timezone(timedelta(hours=5, minutes=30))
        log = self._make_log()
        log.log("order.place", {})
        future_bound = datetime(2099, 1, 1, tzinfo=IST).isoformat()
        assert log.count_actions("order.place", since=future_bound) == 0
        log.close()

    # --- context manager ---

    def test_context_manager(self):
        from packages.data.src.activity_log import ActivityLog

        with ActivityLog(":memory:") as log:
            log.log("auth.logout", {"reason": "idle"})
            assert log.count_actions("auth.logout") == 1


# ---------------------------------------------------------------------------
# Activity route tests
# ---------------------------------------------------------------------------

_TEST_API_KEY = "test-activity-route-key"


@pytest.fixture(scope="module")
def _restore_env():
    original = dict(os.environ)
    yield
    os.environ.clear()
    os.environ.update(original)


@pytest.fixture(scope="module")
def route_client(_restore_env):
    """Flask test client with an in-memory ActivityLog pre-seeded with entries."""
    os.environ["OPENALGO_API_KEY"] = _TEST_API_KEY
    from packages.core.src.app import create_flask_app
    from packages.data.src.activity_log import ActivityLog

    app = create_flask_app()
    app.config["TESTING"] = True

    # Replace the persistent ActivityLog with an in-memory one for isolation
    mem_log = ActivityLog(":memory:")
    mem_log.log("order.place", {"symbol": "NIFTY", "qty": 50}, user="nav", ip="10.0.0.1")
    mem_log.log("order.cancel", {"orderid": "ORD001"}, user="nav")
    mem_log.log("auth.login", {"method": "password"}, user="admin")
    mem_log.log("mode.switch", {"from": "explore", "to": "live"}, user="nav")
    app.config["ACTIVITY_LOG"] = mem_log

    with app.test_client() as c:
        yield c


def _get(client, path, **params):
    """Issue an authenticated GET with optional query params."""
    from urllib.parse import urlencode

    qs = urlencode(params)
    url = f"{path}?{qs}" if qs else path
    return client.get(url, headers={"X-API-Key": _TEST_API_KEY})


class TestActivityRoute:
    """Test GET /api/v1/admin/activity endpoint."""

    def test_returns_200(self, route_client):
        resp = _get(route_client, "/api/v1/admin/activity")
        assert resp.status_code == 200

    def test_response_shape(self, route_client):
        resp = _get(route_client, "/api/v1/admin/activity")
        data = resp.get_json()
        assert data["status"] == "success"
        assert "entries" in data["data"]
        assert "count" in data["data"]

    def test_returns_all_seeded_entries(self, route_client):
        resp = _get(route_client, "/api/v1/admin/activity")
        data = resp.get_json()
        assert data["data"]["count"] == 4

    def test_filter_by_action(self, route_client):
        resp = _get(route_client, "/api/v1/admin/activity", action="order.place")
        data = resp.get_json()
        assert data["data"]["count"] == 1
        assert data["data"]["entries"][0]["action"] == "order.place"

    def test_filter_by_user(self, route_client):
        resp = _get(route_client, "/api/v1/admin/activity", user="admin")
        data = resp.get_json()
        assert data["data"]["count"] == 1
        assert data["data"]["entries"][0]["user"] == "admin"

    def test_limit_param(self, route_client):
        resp = _get(route_client, "/api/v1/admin/activity", limit=2)
        data = resp.get_json()
        assert data["data"]["count"] == 2

    def test_limit_invalid_returns_400(self, route_client):
        resp = _get(route_client, "/api/v1/admin/activity", limit="notanint")
        assert resp.status_code == 400

    def test_entry_fields_complete(self, route_client):
        resp = _get(route_client, "/api/v1/admin/activity", action="order.place")
        entry = resp.get_json()["data"]["entries"][0]
        for field in ("log_id", "timestamp", "action", "user", "ip", "details"):
            assert field in entry, f"Missing field: {field}"
