"""Tests for packages/data/src/activity_routes.py (Flask Blueprint).

Covers the GET /api/v1/admin/activity endpoint — filtering, pagination,
and the 503 path when ACTIVITY_LOG is not initialised.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any
from unittest.mock import MagicMock
import uuid

import pytest
from flask import Flask


# ---------------------------------------------------------------------------
# Minimal stub for ActivityEntry
# ---------------------------------------------------------------------------


@dataclass
class _FakeEntry:
    """Minimal ActivityEntry stub for testing the serialisation path.

    Attributes:
        log_id:    Unique identifier.
        timestamp: ISO-8601 string.
        action:    Dot-namespaced action string.
        user:      Username.
        ip:        IP address or None.
        details:   Arbitrary metadata dict.
    """

    log_id: str
    timestamp: str
    action: str
    user: str
    ip: str | None
    details: dict[str, Any]


def _make_entry(action: str = "order.place", user: str = "test") -> _FakeEntry:
    """Create a fake activity entry with sensible defaults.

    Args:
        action: Action string.
        user:   Username string.

    Returns:
        Populated _FakeEntry.
    """
    return _FakeEntry(
        log_id=str(uuid.uuid4()),
        timestamp="2026-04-19T10:00:00+05:30",
        action=action,
        user=user,
        ip="10.0.0.1",
        details={"symbol": "NIFTY"},
    )


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture()
def activity_log() -> MagicMock:
    """Return a mock activity log with a query() interface.

    Returns:
        MagicMock configured to return an empty list by default.
    """
    m = MagicMock()
    m.query.return_value = []
    return m


@pytest.fixture()
def client(activity_log: MagicMock):
    """Flask test client with ACTIVITY_LOG injected into app config.

    Args:
        activity_log: Mock activity log fixture.

    Yields:
        Flask test client.
    """
    from packages.data.src.activity_routes import activity_bp

    flask_app = Flask(__name__)
    flask_app.config["TESTING"] = True
    flask_app.config["ACTIVITY_LOG"] = activity_log
    flask_app.register_blueprint(activity_bp)
    with flask_app.test_client() as c:
        yield c


@pytest.fixture()
def client_no_log():
    """Flask test client without ACTIVITY_LOG set (simulates uninitialised state).

    Yields:
        Flask test client.
    """
    from packages.data.src.activity_routes import activity_bp

    flask_app = Flask(__name__)
    flask_app.config["TESTING"] = True
    flask_app.register_blueprint(activity_bp)
    with flask_app.test_client() as c:
        yield c


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestGetActivity:
    def test_returns_empty_entries(self, client: MagicMock) -> None:
        """Empty activity log returns an empty entries list with count=0.

        Args:
            client: Flask test client.
        """
        resp = client.get("/api/v1/admin/activity")
        assert resp.status_code == 200
        data = resp.get_json()
        assert data["status"] == "success"
        assert data["data"]["entries"] == []
        assert data["data"]["count"] == 0

    def test_returns_entries_with_correct_shape(
        self, client: MagicMock, activity_log: MagicMock
    ) -> None:
        """Activity entries are serialised with all expected fields.

        Args:
            client:       Flask test client.
            activity_log: Mock log fixture.
        """
        entry = _make_entry("order.cancel", "alice")
        activity_log.query.return_value = [entry]

        resp = client.get("/api/v1/admin/activity")
        data = resp.get_json()
        assert data["data"]["count"] == 1
        e = data["data"]["entries"][0]
        assert e["action"] == "order.cancel"
        assert e["user"] == "alice"
        assert "log_id" in e
        assert "timestamp" in e

    def test_passes_filters_to_query(
        self, client: MagicMock, activity_log: MagicMock
    ) -> None:
        """Query parameters are forwarded to activity_log.query().

        Args:
            client:       Flask test client.
            activity_log: Mock log fixture.
        """
        client.get("/api/v1/admin/activity?action=order.place&user=nav&limit=10")
        activity_log.query.assert_called_once_with(
            action="order.place", user="nav", since=None, limit=10
        )

    def test_invalid_limit_returns_400(self, client: MagicMock) -> None:
        """Non-integer limit query parameter returns HTTP 400.

        Args:
            client: Flask test client.
        """
        resp = client.get("/api/v1/admin/activity?limit=abc")
        assert resp.status_code == 400
        assert resp.get_json()["status"] == "error"

    def test_missing_activity_log_returns_503(self, client_no_log) -> None:
        """Missing ACTIVITY_LOG config returns HTTP 503.

        Args:
            client_no_log: Flask test client without ACTIVITY_LOG.
        """
        resp = client_no_log.get("/api/v1/admin/activity")
        assert resp.status_code == 503
        assert resp.get_json()["status"] == "error"

    def test_limit_clamped_to_500(
        self, client: MagicMock, activity_log: MagicMock
    ) -> None:
        """Limit above 500 is clamped to 500 before querying.

        Args:
            client:       Flask test client.
            activity_log: Mock log fixture.
        """
        client.get("/api/v1/admin/activity?limit=9999")
        _, kwargs = activity_log.query.call_args
        assert kwargs["limit"] == 500 or activity_log.query.call_args[0][3] <= 500
