"""Tests for Action Center Flask endpoints.

Run with:
    python -m pytest packages/engine/tests/test_action_center_routes.py -v --import-mode=importlib
"""

from __future__ import annotations

import pytest


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture()
def action_center():
    """Fresh ActionCenter for each test."""
    from packages.engine.src.action_center import ActionCenter  # noqa: PLC0415
    return ActionCenter(ttl_seconds=300)


@pytest.fixture()
def client(action_center):
    """Flask test client wired to a fresh ActionCenter."""
    from flask import Flask  # noqa: PLC0415
    from packages.engine.src.action_center_routes import action_center_bp  # noqa: PLC0415

    app = Flask(__name__)
    app.config["ACTION_CENTER"] = action_center
    app.config["TESTING"] = True
    app.register_blueprint(action_center_bp)
    with app.test_client() as c:
        yield c


def _submit(action_center, order_id: str = "ord-1") -> None:
    action_center.submit(order_id, "acct-1", {"symbol": "NIFTY", "action": "BUY", "quantity": "50"})


def test_get_ac_no_app_context():
    """Verify _get_ac falls back to the default singleton outside a request context."""
    # Explicitly import the module to test directly. The `current_app` mock
    # is implicit since we aren't within a Flask app or test client context.
    from packages.engine.src.action_center_routes import _default_action_center, _get_ac  # noqa: PLC0415

    assert _get_ac() is _default_action_center


# ---------------------------------------------------------------------------
# GET /pending
# ---------------------------------------------------------------------------


class TestGetPending:
    def test_empty_queue_returns_empty_list(self, client):
        resp = client.get("/ft-api/v1/action-center/pending")
        assert resp.status_code == 200
        data = resp.get_json()
        assert data["status"] == "success"
        assert data["data"]["orders"] == []

    def test_pending_orders_appear(self, client, action_center):
        _submit(action_center)
        resp = client.get("/ft-api/v1/action-center/pending")
        data = resp.get_json()
        assert len(data["data"]["orders"]) == 1
        assert data["data"]["orders"][0]["order_id"] == "ord-1"


# ---------------------------------------------------------------------------
# GET /all
# ---------------------------------------------------------------------------


class TestGetAll:
    def test_all_includes_approved(self, client, action_center):
        _submit(action_center)
        action_center.approve("ord-1")
        resp = client.get("/ft-api/v1/action-center/all")
        data = resp.get_json()
        assert len(data["data"]["orders"]) == 1
        assert data["data"]["orders"][0]["status"] == "approved"


# ---------------------------------------------------------------------------
# POST /approve/<order_id>
# ---------------------------------------------------------------------------


class TestApproveEndpoint:
    def test_approve_pending_order_returns_200(self, client, action_center):
        _submit(action_center)
        resp = client.post("/ft-api/v1/action-center/approve/ord-1")
        assert resp.status_code == 200
        data = resp.get_json()
        assert data["status"] == "success"
        assert data["data"]["order"]["status"] == "approved"

    def test_approve_nonexistent_returns_409(self, client):
        resp = client.post("/ft-api/v1/action-center/approve/no-such-order")
        assert resp.status_code == 409
        assert resp.get_json()["status"] == "error"


# ---------------------------------------------------------------------------
# POST /reject/<order_id>
# ---------------------------------------------------------------------------


class TestRejectEndpoint:
    def test_reject_pending_order_returns_200(self, client, action_center):
        _submit(action_center)
        resp = client.post("/ft-api/v1/action-center/reject/ord-1")
        assert resp.status_code == 200
        data = resp.get_json()
        assert data["data"]["order"]["status"] == "rejected"

    def test_reject_already_approved_returns_409(self, client, action_center):
        _submit(action_center)
        action_center.approve("ord-1")
        resp = client.post("/ft-api/v1/action-center/reject/ord-1")
        assert resp.status_code == 409


# ---------------------------------------------------------------------------
# POST /approve-all
# ---------------------------------------------------------------------------


class TestApproveAllEndpoint:
    def test_approve_all_returns_count(self, client, action_center):
        _submit(action_center, "m1")
        _submit(action_center, "m2")
        resp = client.post("/ft-api/v1/action-center/approve-all")
        assert resp.status_code == 200
        data = resp.get_json()
        assert data["data"]["approved_count"] == 2


# ---------------------------------------------------------------------------
# GET /config and POST /config
# ---------------------------------------------------------------------------


class TestConfigEndpoints:
    def test_get_config_returns_defaults(self, client):
        resp = client.get("/ft-api/v1/action-center/config")
        assert resp.status_code == 200
        data = resp.get_json()
        assert "enabled" in data["data"]
        assert "ttl_seconds" in data["data"]

    def test_post_config_updates_enabled(self, client, action_center):
        resp = client.post(
            "/ft-api/v1/action-center/config",
            json={"enabled": True},
            content_type="application/json",
        )
        assert resp.status_code == 200
        assert resp.get_json()["data"]["enabled"] is True
        assert action_center.enabled is True

    def test_post_config_updates_ttl(self, client, action_center):
        resp = client.post(
            "/ft-api/v1/action-center/config",
            json={"ttl_seconds": 120},
            content_type="application/json",
        )
        assert resp.status_code == 200
        assert action_center.ttl_seconds == 120

    def test_post_config_updates_both(self, client, action_center):
        resp = client.post(
            "/ft-api/v1/action-center/config",
            json={"enabled": False, "ttl_seconds": 600},
            content_type="application/json",
        )
        assert resp.status_code == 200
        data = resp.get_json()["data"]
        assert data["enabled"] is False
        assert data["ttl_seconds"] == 600
        assert action_center.enabled is False
        assert action_center.ttl_seconds == 600

    def test_post_config_invalid_ttl_returns_400(self, client):
        resp = client.post(
            "/ft-api/v1/action-center/config",
            json={"ttl_seconds": "bad"},
            content_type="application/json",
        )
        assert resp.status_code == 400

    def test_post_config_invalid_ttl_value_returns_400(self, client):
        resp = client.post(
            "/ft-api/v1/action-center/config",
            json={"ttl_seconds": 0},
            content_type="application/json",
        )
        assert resp.status_code == 400
        assert resp.get_json()["message"] == "ttl_seconds must be >= 1"
