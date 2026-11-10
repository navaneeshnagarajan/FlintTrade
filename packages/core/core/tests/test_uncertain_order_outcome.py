"""Uncertain order submits and unconfirmed cancels stay honest.

A dropped or timed-out response is not a rejection, and a cancel
acknowledgement is not a confirmed cancel. These cases add outcome fields
without removing the existing status envelope.
"""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from flinttrade_ai.mcp_bridge import MCPBridge
from packages.core.core.tests.test_order_routes import _auth_headers
from packages.core.core.tests.test_practice_agent_adapter import _order
from packages.core.core.tests.test_practice_agent_adapter import runtime as runtime  # noqa: F401

_UNKNOWN = "Order status unknown. Check Orders before trying again."
_CANCEL_REQUESTED = "Cancellation requested"
_CANCELLED = "Order cancelled"

_LIMIT = {
    "symbol": "INFY",
    "exchange": "NSE",
    "action": "BUY",
    "quantity": 1,
    "price": 100,
    "product": "MIS",
    "order_type": "LIMIT",
}


@pytest.fixture(scope="module")
def practice_client(tmp_path_factory):
    """One app: the incident owner lock is process-wide for this workspace."""
    import os

    tmp_path = tmp_path_factory.mktemp("uncertain-outcome")
    previous_key = os.environ.get("FLINTTRADE_API_KEY")
    previous_dist = os.environ.get("FLINTTRADE_FRONTEND_DIST")
    os.environ["FLINTTRADE_API_KEY"] = "test-order-routes-key"
    os.environ["FLINTTRADE_FRONTEND_DIST"] = str(tmp_path / "absent")
    from flinttrade_core.app import create_flask_app
    from flinttrade_engine.laya import DecisionStatus, process_laya

    process_laya().set_status(DecisionStatus.READY)
    app = create_flask_app()
    app.config["TESTING"] = True
    app.config["TICK_RECORDER"] = MagicMock()
    sandbox = MagicMock()
    sandbox.get_positions.return_value = []
    sandbox.get_orders.return_value = []
    app.config["DATA_SANDBOX_ENGINE"] = sandbox
    client = app.test_client()
    try:
        yield client, sandbox
    finally:
        if previous_key is None:
            os.environ.pop("FLINTTRADE_API_KEY", None)
        else:
            os.environ["FLINTTRADE_API_KEY"] = previous_key
        if previous_dist is None:
            os.environ.pop("FLINTTRADE_FRONTEND_DIST", None)
        else:
            os.environ["FLINTTRADE_FRONTEND_DIST"] = previous_dist


def _ready_laya() -> None:
    from flinttrade_engine.laya import DecisionStatus, process_laya

    process_laya().set_status(DecisionStatus.READY)


def test_practice_place_timeout_is_unknown_and_not_a_rejection(practice_client):
    _ready_laya()
    client, sandbox = practice_client
    sandbox.place_order.reset_mock()
    sandbox.place_order.side_effect = TimeoutError("response dropped")

    response = client.post("/api/v1/orders/place", json=_LIMIT, headers=_auth_headers(mode="practice"))
    body = response.get_json()

    assert response.status_code == 500
    assert body["status"] == "error"
    assert body["order_outcome"] == "unknown"
    assert body["reason"] == "response_unconfirmed"
    assert body["message"] == _UNKNOWN
    assert body["retry_safe"] is False
    assert "reject" not in body["message"].lower()
    assert sandbox.place_order.call_count == 1


def test_practice_place_rejection_stays_a_rejection(practice_client):
    _ready_laya()
    client, sandbox = practice_client
    sandbox.place_order.side_effect = None
    sandbox.place_order.return_value = {
        "order_id": "",
        "status": "REJECTED",
        "message": "Practice order rejected",
    }

    response = client.post("/api/v1/orders/place", json=_LIMIT, headers=_auth_headers(mode="practice"))
    body = response.get_json()

    assert response.status_code == 400
    assert body["status"] == "error"
    assert body["message"] == "Practice order rejected"
    assert body["order_outcome"] == "rejected"
    assert body["reason"] == "broker_rejected"


def test_acknowledged_practice_cancel_is_not_cancelled(practice_client):
    client, sandbox = practice_client
    sandbox.cancel_order.return_value = {
        "order_id": "SB-1",
        "status": "CANCEL_PENDING",
        "message": "cancel accepted",
    }

    response = client.post(
        "/api/v1/orders/cancel",
        json={"order_id": "SB-1"},
        headers=_auth_headers(mode="practice"),
    )
    body = response.get_json()

    assert response.status_code == 200
    assert body["status"] == "CANCEL_PENDING"
    assert body["order_outcome"] == "cancel_requested"
    assert body["reason"] == "awaiting_confirmation"
    assert body["message"] == _CANCEL_REQUESTED
    assert body["message"] != _CANCELLED


def test_confirmed_practice_cancel_says_order_cancelled(practice_client):
    client, sandbox = practice_client
    sandbox.cancel_order.return_value = {
        "order_id": "SB-1",
        "status": "CANCELLED",
        "message": "Practice order cancelled",
    }

    response = client.post(
        "/api/v1/orders/cancel",
        json={"order_id": "SB-1"},
        headers=_auth_headers(mode="practice"),
    )
    body = response.get_json()

    assert response.status_code == 200
    assert body["status"] == "CANCELLED"
    assert body["order_outcome"] == "cancelled"
    assert body["reason"] == "status_confirmed"
    assert body["message"] == _CANCELLED


async def test_practice_agent_dropped_dispatch_is_unknown(runtime, monkeypatch):
    monkeypatch.setattr(runtime.sandbox, "place_order", MagicMock(side_effect=TimeoutError("response dropped")))

    result = await runtime.create().route_order(_order())

    assert result.passed is False
    assert result.response["order_outcome"] == "unknown"
    assert result.response["reason"] == "response_unconfirmed"
    assert result.response["message"] == _UNKNOWN
    assert result.response["retry_safe"] is False
    assert result.response["code"] == "practice_reconciliation_required"
    assert result.error == _UNKNOWN


def test_mcp_order_intent_is_a_refusal_and_a_dropped_tool_result_is_unknown():
    bridge = MCPBridge()
    refused = bridge.execute("Buy RELIANCE 1 share")
    assert refused.error == "Order-capable tools are unavailable"
    assert refused.result["order_outcome"] == "rejected"
    assert refused.result["reason"] == "tool_unavailable"
    assert refused.result["retry_safe"] is False

    described = bridge.describe_order_tool_outcome(None, dropped=True)
    assert described["order_outcome"] == "unknown"
    assert described["reason"] == "response_unconfirmed"
    assert described["message"] == _UNKNOWN
    assert described["retry_safe"] is False

    acknowledged = bridge.describe_order_tool_outcome({"status": "CANCEL_PENDING", "order_id": "SB-1"})
    assert acknowledged["order_outcome"] == "cancel_requested"
    assert acknowledged["message"] == _CANCEL_REQUESTED

    confirmed = bridge.describe_order_tool_outcome({"status": "CANCELLED", "order_id": "SB-1"})
    assert confirmed["message"] == _CANCELLED
    assert confirmed["order_outcome"] == "cancelled"

    rejected = bridge.describe_order_tool_outcome({"status": "REJECTED", "message": "Practice order rejected"})
    assert rejected["order_outcome"] == "rejected"
    assert rejected["message"] == "Practice order rejected"
