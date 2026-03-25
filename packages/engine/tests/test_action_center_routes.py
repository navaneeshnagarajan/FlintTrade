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

    def test_get_pending_filters_non_pending(self, client, action_center):
        """Verify that get_pending only returns orders in PENDING status."""
        _submit(action_center, "pending-ord")
        _submit(action_center, "approved-ord")
        _submit(action_center, "rejected-ord")

        action_center.approve("approved-ord")
        action_center.reject("rejected-ord")

        resp = client.get("/ft-api/v1/action-center/pending")
        assert resp.status_code == 200
        data = resp.get_json()

        assert data["status"] == "success"
        orders = data["data"]["orders"]
        assert len(orders) == 1
        assert orders[0]["order_id"] == "pending-ord"
        assert orders[0]["status"] == "pending"


# ---------------------------------------------------------------------------
# GET /all
# ---------------------------------------------------------------------------


class TestGetAll:
    def test_all_returns_empty_list(self, client):
        resp = client.get("/ft-api/v1/action-center/all")
        assert resp.status_code == 200
        data = resp.get_json()
        assert data["status"] == "success"
        assert data["data"]["orders"] == []

    def test_all_includes_approved(self, client, action_center):
        _submit(action_center)
        action_center.approve("ord-1")
        resp = client.get("/ft-api/v1/action-center/all")
        data = resp.get_json()
        assert len(data["data"]["orders"]) == 1
        assert data["data"]["orders"][0]["status"] == "approved"

    def test_all_includes_all_statuses(self, client, action_center):
        import time
        from packages.engine.src.action_center import OrderApprovalStatus

        # Pending
        _submit(action_center, "ord-1")

        # Approved
        _submit(action_center, "ord-2")
        action_center.approve("ord-2")

        # Rejected
        _submit(action_center, "ord-3")
        action_center.reject("ord-3")

        # Expired
        _submit(action_center, "ord-4")
        # Manually backdate the created_at timestamp to make it expired when evaluated
        with action_center._lock:
            po = action_center._get_or_raise("ord-4")
            po.created_at = time.time() - action_center.ttl_seconds - 10

        resp = client.get("/ft-api/v1/action-center/all")
        assert resp.status_code == 200
        data = resp.get_json()
        orders = data["data"]["orders"]
        assert len(orders) == 4

        statuses = {o["order_id"]: o["status"] for o in orders}
        assert statuses["ord-1"] == OrderApprovalStatus.PENDING
        assert statuses["ord-2"] == OrderApprovalStatus.APPROVED
        assert statuses["ord-3"] == OrderApprovalStatus.REJECTED
        assert statuses["ord-4"] == OrderApprovalStatus.EXPIRED


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
        assert resp.get_json()["status"] == "error"
        assert "ttl_seconds must be >= 1" in resp.get_json()["message"]

# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

class TestInternalHelpers:
    def test_get_ac_outside_app_context(self):
        from packages.engine.src.action_center_routes import _get_ac, _default_action_center  # noqa: PLC0415
        # Since we are outside any Flask test client context, current_app will raise RuntimeError
        ac = _get_ac()
        assert ac is _default_action_center
