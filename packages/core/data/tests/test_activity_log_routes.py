"""Tests for the enhanced audit trail endpoints.

Covers:
    GET /ft-api/v1/audit/log    — paginated, filterable audit log
    GET /ft-api/v1/audit/export — CSV export
    GET /ft-api/v1/audit/stats  — action-type counts

Run with:
    python -m pytest packages/core/data/tests/test_activity_log_routes.py -v --import-mode=importlib
"""

from __future__ import annotations

import csv
import io
import os

import pytest


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

_TEST_API_KEY = "test-audit-routes-key"

_ACTIONS = [
    ("order.place",   {"symbol": "NIFTY", "qty": 50},   "alice", "10.0.0.1"),
    ("order.place",   {"symbol": "BANKNIFTY", "qty": 25}, "alice", "10.0.0.1"),
    ("order.cancel",  {"orderid": "ORD001"},              "alice", None),
    ("order.modify",  {"orderid": "ORD002", "qty": 75},  "bob",   "10.0.0.2"),
    ("auth.login",    {"method": "password"},             "admin", "192.168.1.1"),
    ("auth.logout",   {"reason": "idle"},                 "admin", None),
    ("mode.switch",   {"from": "explore", "to": "live"}, "alice", "10.0.0.1"),
    ("settings.update", {"key": "theme", "value": "dark"}, "alice", None),
    ("strategy.start", {"name": "momentum"},              "system", None),
    ("strategy.stop",  {"name": "momentum"},              "system", None),
]


@pytest.fixture(scope="module")
def _restore_env():
    original = dict(os.environ)
    yield
    os.environ.clear()
    os.environ.update(original)


@pytest.fixture(scope="module")
def route_client(_restore_env):
    """Flask test client with a pre-seeded in-memory ActivityLog."""
    os.environ["OPENALGO_API_KEY"] = _TEST_API_KEY
    from flinttrade_core.app import create_flask_app
    from flinttrade_data.activity_log import ActivityLog

    app = create_flask_app()
    app.config["TESTING"] = True

    mem_log = ActivityLog(":memory:")
    for action, details, user, ip in _ACTIONS:
        mem_log.log(action, details, user=user, ip=ip)
    app.config["ACTIVITY_LOG"] = mem_log

    with app.test_client() as c:
        yield c


def _get(client, path: str, **params):
    """Issue an authenticated GET with optional query params."""
    from urllib.parse import urlencode

    qs = urlencode(params)
    url = f"{path}?{qs}" if qs else path
    return client.get(url, headers={"X-API-Key": _TEST_API_KEY})


# ---------------------------------------------------------------------------
# GET /ft-api/v1/audit/log
# ---------------------------------------------------------------------------


class TestAuditLog:
    """Test the paginated audit log endpoint."""

    def test_returns_200(self, route_client):
        resp = _get(route_client, "/v1/audit/log")
        assert resp.status_code == 200

    def test_response_shape(self, route_client):
        resp = _get(route_client, "/v1/audit/log")
        data = resp.get_json()
        assert data["status"] == "success"
        d = data["data"]
        for key in ("entries", "total", "page", "per_page", "pages"):
            assert key in d, f"Missing key in data: {key}"

    def test_total_matches_seeded_entries(self, route_client):
        resp = _get(route_client, "/v1/audit/log", per_page=500)
        data = resp.get_json()["data"]
        assert data["total"] == len(_ACTIONS)

    def test_default_page_is_1(self, route_client):
        resp = _get(route_client, "/v1/audit/log")
        assert resp.get_json()["data"]["page"] == 1

    def test_pagination_per_page(self, route_client):
        resp = _get(route_client, "/v1/audit/log", per_page=3)
        data = resp.get_json()["data"]
        assert len(data["entries"]) == 3
        assert data["per_page"] == 3

    def test_pagination_page_2(self, route_client):
        resp = _get(route_client, "/v1/audit/log", per_page=3, page=2)
        data = resp.get_json()["data"]
        assert len(data["entries"]) <= 3
        assert data["page"] == 2

    def test_pages_calculated_correctly(self, route_client):
        """10 entries with per_page=3 → 4 pages (ceil(10/3))."""
        resp = _get(route_client, "/v1/audit/log", per_page=3)
        data = resp.get_json()["data"]
        import math

        expected_pages = math.ceil(len(_ACTIONS) / 3)
        assert data["pages"] == expected_pages

    def test_filter_by_action(self, route_client):
        resp = _get(route_client, "/v1/audit/log", action="order.place", per_page=500)
        data = resp.get_json()["data"]
        assert data["total"] == 2
        assert all(e["action"] == "order.place" for e in data["entries"])

    def test_filter_by_user(self, route_client):
        resp = _get(route_client, "/v1/audit/log", user="bob", per_page=500)
        data = resp.get_json()["data"]
        assert data["total"] == 1
        assert data["entries"][0]["user"] == "bob"

    def test_filter_by_user_admin(self, route_client):
        resp = _get(route_client, "/v1/audit/log", user="admin", per_page=500)
        data = resp.get_json()["data"]
        assert data["total"] == 2

    def test_until_filter_excludes_later_entries(self, route_client):
        # until a far-past timestamp → 0 results
        resp = _get(route_client, "/v1/audit/log", until="2000-01-01T00:00:00+05:30", per_page=500)
        data = resp.get_json()["data"]
        assert data["total"] == 0

    def test_until_filter_includes_earlier_entries(self, route_client):
        # until a far-future timestamp → all results
        resp = _get(route_client, "/v1/audit/log", until="2099-12-31T23:59:59+05:30", per_page=500)
        data = resp.get_json()["data"]
        assert data["total"] == len(_ACTIONS)

    def test_invalid_page_returns_400(self, route_client):
        resp = _get(route_client, "/v1/audit/log", page="notanint")
        assert resp.status_code == 400

    def test_invalid_per_page_returns_400(self, route_client):
        resp = _get(route_client, "/v1/audit/log", per_page="notanint")
        assert resp.status_code == 400

    def test_entry_fields_complete(self, route_client):
        resp = _get(route_client, "/v1/audit/log", action="order.place", per_page=500)
        entry = resp.get_json()["data"]["entries"][0]
        for field in ("log_id", "timestamp", "action", "user", "ip", "details"):
            assert field in entry, f"Missing field: {field}"

    def test_page_beyond_range_returns_empty_entries(self, route_client):
        resp = _get(route_client, "/v1/audit/log", page=999, per_page=50)
        data = resp.get_json()["data"]
        assert data["entries"] == []

    def test_per_page_clamped_to_500(self, route_client):
        resp = _get(route_client, "/v1/audit/log", per_page=9999)
        data = resp.get_json()["data"]
        assert data["per_page"] == 500

    def test_no_activity_log_returns_503(self, _restore_env):
        """When ACTIVITY_LOG is not configured, return 503."""
        os.environ["OPENALGO_API_KEY"] = _TEST_API_KEY
        from flinttrade_core.app import create_flask_app

        app = create_flask_app()
        app.config["TESTING"] = True
        app.config.pop("ACTIVITY_LOG", None)
        # Override with None explicitly
        app.config["ACTIVITY_LOG"] = None

        with app.test_client() as c:
            resp = c.get(
                "/v1/audit/log",
                headers={"X-API-Key": _TEST_API_KEY},
            )
            assert resp.status_code == 503


# ---------------------------------------------------------------------------
# GET /ft-api/v1/audit/export
# ---------------------------------------------------------------------------


class TestAuditExport:
    """Test the CSV export endpoint."""

    def test_returns_200(self, route_client):
        resp = _get(route_client, "/v1/audit/export")
        assert resp.status_code == 200

    def test_content_type_is_csv(self, route_client):
        resp = _get(route_client, "/v1/audit/export")
        assert "text/csv" in resp.content_type

    def test_content_disposition_is_attachment(self, route_client):
        resp = _get(route_client, "/v1/audit/export")
        cd = resp.headers.get("Content-Disposition", "")
        assert "attachment" in cd
        assert "flinttrade_audit.csv" in cd

    def test_csv_has_header_row(self, route_client):
        resp = _get(route_client, "/v1/audit/export")
        reader = csv.reader(io.StringIO(resp.data.decode("utf-8")))
        header = next(reader)
        assert header == ["log_id", "timestamp", "action", "user", "ip", "details"]

    def test_csv_row_count_matches_entries(self, route_client):
        resp = _get(route_client, "/v1/audit/export")
        reader = csv.reader(io.StringIO(resp.data.decode("utf-8")))
        rows = list(reader)
        # First row is header; rest are data rows
        assert len(rows) - 1 == len(_ACTIONS)

    def test_csv_filter_by_action(self, route_client):
        resp = _get(route_client, "/v1/audit/export", action="auth.login")
        reader = csv.reader(io.StringIO(resp.data.decode("utf-8")))
        rows = list(reader)[1:]  # skip header
        assert len(rows) == 1
        assert rows[0][2] == "auth.login"  # action column

    def test_csv_filter_by_user(self, route_client):
        resp = _get(route_client, "/v1/audit/export", user="system")
        reader = csv.reader(io.StringIO(resp.data.decode("utf-8")))
        rows = list(reader)[1:]
        assert len(rows) == 2
        assert all(r[3] == "system" for r in rows)  # user column

    def test_csv_until_far_past_returns_only_header(self, route_client):
        resp = _get(route_client, "/v1/audit/export", until="2000-01-01T00:00:00+05:30")
        reader = csv.reader(io.StringIO(resp.data.decode("utf-8")))
        rows = list(reader)
        # Only header row
        assert len(rows) == 1

    def test_no_activity_log_returns_503(self, _restore_env):
        os.environ["OPENALGO_API_KEY"] = _TEST_API_KEY
        from flinttrade_core.app import create_flask_app

        app = create_flask_app()
        app.config["TESTING"] = True
        app.config["ACTIVITY_LOG"] = None

        with app.test_client() as c:
            resp = c.get(
                "/v1/audit/export",
                headers={"X-API-Key": _TEST_API_KEY},
            )
            assert resp.status_code == 503


# ---------------------------------------------------------------------------
# GET /ft-api/v1/audit/stats
# ---------------------------------------------------------------------------


class TestAuditStats:
    """Test the action-count stats endpoint."""

    def test_returns_200(self, route_client):
        resp = _get(route_client, "/v1/audit/stats")
        assert resp.status_code == 200

    def test_response_shape(self, route_client):
        resp = _get(route_client, "/v1/audit/stats")
        data = resp.get_json()
        assert data["status"] == "success"
        assert "total" in data["data"]
        assert "by_action" in data["data"]

    def test_total_matches_seeded_count(self, route_client):
        resp = _get(route_client, "/v1/audit/stats")
        data = resp.get_json()["data"]
        assert data["total"] == len(_ACTIONS)

    def test_by_action_counts_correct(self, route_client):
        resp = _get(route_client, "/v1/audit/stats")
        by_action = resp.get_json()["data"]["by_action"]
        # 2 order.place entries were seeded
        assert by_action.get("order.place") == 2
        # 1 auth.login entry
        assert by_action.get("auth.login") == 1

    def test_sum_of_by_action_equals_total(self, route_client):
        resp = _get(route_client, "/v1/audit/stats")
        data = resp.get_json()["data"]
        assert sum(data["by_action"].values()) == data["total"]

    def test_filter_by_user(self, route_client):
        resp = _get(route_client, "/v1/audit/stats", user="alice")
        data = resp.get_json()["data"]
        # alice has: order.place x2, order.cancel x1, mode.switch x1, settings.update x1
        assert data["total"] == 5

    def test_filter_by_since_far_future_returns_zero(self, route_client):
        resp = _get(route_client, "/v1/audit/stats", since="2099-01-01T00:00:00+05:30")
        data = resp.get_json()["data"]
        assert data["total"] == 0
        assert data["by_action"] == {}

    def test_no_activity_log_returns_503(self, _restore_env):
        os.environ["OPENALGO_API_KEY"] = _TEST_API_KEY
        from flinttrade_core.app import create_flask_app

        app = create_flask_app()
        app.config["TESTING"] = True
        app.config["ACTIVITY_LOG"] = None

        with app.test_client() as c:
            resp = c.get(
                "/v1/audit/stats",
                headers={"X-API-Key": _TEST_API_KEY},
            )
            assert resp.status_code == 503
