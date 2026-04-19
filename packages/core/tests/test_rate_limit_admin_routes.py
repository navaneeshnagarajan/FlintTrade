"""Tests for packages/core/src/rate_limit_admin_routes.py (Flask Blueprint).

Covers GET /admin/rate-limits/overrides, POST, and DELETE via a MagicMock
rate_limiter dependency — no real RateLimiter is constructed.
"""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest
from flask import Flask


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture()
def limiter() -> MagicMock:
    """Return a mock RateLimiter with the required interface methods.

    Returns:
        MagicMock with list_overrides, set_user_override, remove_user_override.
    """
    m = MagicMock()
    m.list_overrides.return_value = []
    m.set_user_override.return_value = None
    m.remove_user_override.return_value = True
    return m


@pytest.fixture()
def client(limiter: MagicMock):
    """Flask test client with rate-limit admin blueprint registered.

    Args:
        limiter: Mock RateLimiter fixture.

    Yields:
        Flask test client.
    """
    from packages.core.src.rate_limit_admin_routes import create_rate_limit_admin_blueprint

    flask_app = Flask(__name__)
    flask_app.config["TESTING"] = True
    flask_app.register_blueprint(create_rate_limit_admin_blueprint(limiter))
    with flask_app.test_client() as c:
        yield c


# ---------------------------------------------------------------------------
# GET /admin/rate-limits/overrides
# ---------------------------------------------------------------------------


class TestListOverrides:
    def test_returns_empty_list_by_default(self, client: MagicMock) -> None:
        """List endpoint returns an empty overrides list when none are set.

        Args:
            client: Flask test client.
        """
        resp = client.get("/admin/rate-limits/overrides")
        assert resp.status_code == 200
        data = resp.get_json()
        assert data["status"] == "ok"
        assert data["overrides"] == []

    def test_returns_populated_list(self, client: MagicMock, limiter: MagicMock) -> None:
        """List endpoint surfaces entries returned by the limiter mock.

        Args:
            client:  Flask test client.
            limiter: Mock limiter with pre-loaded overrides.
        """
        limiter.list_overrides.return_value = [
            {"user_id": "nav", "endpoint": "orders", "user_rate": 5}
        ]
        resp = client.get("/admin/rate-limits/overrides")
        data = resp.get_json()
        assert len(data["overrides"]) == 1
        assert data["overrides"][0]["user_id"] == "nav"


# ---------------------------------------------------------------------------
# POST /admin/rate-limits/overrides
# ---------------------------------------------------------------------------


class TestSetOverride:
    def test_creates_override_successfully(self, client: MagicMock, limiter: MagicMock) -> None:
        """Valid payload creates override via limiter.set_user_override.

        Args:
            client:  Flask test client.
            limiter: Mock limiter fixture.
        """
        resp = client.post(
            "/admin/rate-limits/overrides",
            json={"user_id": "nav", "endpoint": "orders", "rate": 5},
        )
        assert resp.status_code == 200
        data = resp.get_json()
        assert data["status"] == "ok"
        limiter.set_user_override.assert_called_once_with("nav", "orders", 5)

    def test_missing_user_id_returns_400(self, client: MagicMock) -> None:
        """Missing user_id field returns HTTP 400.

        Args:
            client: Flask test client.
        """
        resp = client.post(
            "/admin/rate-limits/overrides",
            json={"endpoint": "orders", "rate": 5},
        )
        assert resp.status_code == 400
        assert "user_id" in resp.get_json()["message"]

    def test_missing_endpoint_returns_400(self, client: MagicMock) -> None:
        """Missing endpoint field returns HTTP 400.

        Args:
            client: Flask test client.
        """
        resp = client.post(
            "/admin/rate-limits/overrides",
            json={"user_id": "nav", "rate": 5},
        )
        assert resp.status_code == 400
        assert "endpoint" in resp.get_json()["message"]

    def test_missing_rate_returns_400(self, client: MagicMock) -> None:
        """Missing rate field returns HTTP 400.

        Args:
            client: Flask test client.
        """
        resp = client.post(
            "/admin/rate-limits/overrides",
            json={"user_id": "nav", "endpoint": "orders"},
        )
        assert resp.status_code == 400
        assert "rate" in resp.get_json()["message"]

    def test_invalid_rate_raises_value_error_400(self, client: MagicMock, limiter: MagicMock) -> None:
        """ValueError from limiter.set_user_override surfaces as HTTP 400.

        Args:
            client:  Flask test client.
            limiter: Mock limiter that raises ValueError.
        """
        limiter.set_user_override.side_effect = ValueError("rate must be positive")
        resp = client.post(
            "/admin/rate-limits/overrides",
            json={"user_id": "nav", "endpoint": "orders", "rate": -1},
        )
        assert resp.status_code == 400


# ---------------------------------------------------------------------------
# DELETE /admin/rate-limits/overrides/<user_id>/<endpoint>
# ---------------------------------------------------------------------------


class TestRemoveOverride:
    def test_removes_existing_override(self, client: MagicMock, limiter: MagicMock) -> None:
        """DELETE returns removed=True when the override existed.

        Args:
            client:  Flask test client.
            limiter: Mock limiter that returns True.
        """
        limiter.remove_user_override.return_value = True
        resp = client.delete("/admin/rate-limits/overrides/nav/orders")
        assert resp.status_code == 200
        data = resp.get_json()
        assert data["status"] == "ok"
        assert data["removed"] is True

    def test_reports_not_found_gracefully(self, client: MagicMock, limiter: MagicMock) -> None:
        """DELETE returns removed=False (not 404) when override did not exist.

        Args:
            client:  Flask test client.
            limiter: Mock limiter that returns False.
        """
        limiter.remove_user_override.return_value = False
        resp = client.delete("/admin/rate-limits/overrides/unknown/orders")
        assert resp.status_code == 200
        data = resp.get_json()
        assert data["removed"] is False
