"""Tests for the durable, dispatching Action Centre HTTP workflow."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock

import pytest
from flask import Flask


@pytest.fixture()
def queue(tmp_path: Path):
    from flinttrade_engine.action_center import PendingOrderQueue

    instance = PendingOrderQueue(tmp_path / "action-centre.duckdb")
    yield instance
    instance.close()


@pytest.fixture()
def app(queue):
    from flinttrade_engine.action_center import ApprovalDispatchResult
    from flinttrade_engine.action_center_routes import (
        action_center_bp,
        admin_action_center_bp,
    )

    flask_app = Flask(__name__)
    flask_app.config.update(
        TESTING=True,
        PENDING_ORDER_QUEUE=queue,
        ACTION_CENTER_AUTHORISER=lambda require_live_unlock: None,
        ACTION_CENTER_APPROVAL_DISPATCHER=lambda request: ApprovalDispatchResult.success("BROKER-1"),
    )
    flask_app.register_blueprint(action_center_bp)
    flask_app.register_blueprint(admin_action_center_bp)
    return flask_app


@pytest.fixture()
def client(app):
    return app.test_client()


def _enqueue(queue, request_id: str = "intent-1", *, ttl_minutes: int = 5):
    return queue.enqueue(
        {
            "symbol": "RELIANCE",
            "exchange": "NSE",
            "action": "BUY",
            "quantity": "2",
            "price": "0",
            "pricetype": "MARKET",
            "product": "MIS",
            "strategy": "AutonomousAgent",
        },
        reason="Autonomous-agent BUY entry requires operator approval",
        ttl_minutes=ttl_minutes,
        request_id=request_id,
        adapter_id="upstox",
        account_id="primary",
        source="autonomous-agent",
        intent_type="entry",
        producer_ref="agent-session-1",
        intent_context={"entry_price": 2500.0, "signal": "BUY"},
    )


def test_pending_returns_flattened_durable_intents(client, queue):
    _enqueue(queue)

    response = client.get("/api/v1/action-center/pending")

    assert response.status_code == 200
    order = response.get_json()["data"]["orders"][0]
    assert order == {
        "id": "intent-1",
        "symbol": "RELIANCE",
        "exchange": "NSE",
        "action": "BUY",
        "quantity": 2,
        "price": 0.0,
        "order_type": "MARKET",
        "product": "MIS",
        "strategy": "AutonomousAgent",
        "created_at": order["created_at"],
        "expires_at": order["expires_at"],
        "reason": "Autonomous-agent BUY entry requires operator approval",
        "broker": "upstox",
        "account_id": "primary",
        "source": "autonomous-agent",
        "status": "pending",
    }


def test_routes_fail_closed_without_fresh_authoriser(client, app, queue):
    _enqueue(queue)
    app.config.pop("ACTION_CENTER_AUTHORISER")

    response = client.post("/api/v1/action-center/approve/intent-1")

    assert response.status_code == 503
    assert queue.get("intent-1").status == "pending"


def test_approval_requires_live_unlock_and_dispatches_once(client, app, queue):
    request = _enqueue(queue)
    authoriser = MagicMock(return_value=None)
    dispatcher = MagicMock(return_value=app.config["ACTION_CENTER_APPROVAL_DISPATCHER"](request))
    app.config["ACTION_CENTER_AUTHORISER"] = authoriser
    app.config["ACTION_CENTER_APPROVAL_DISPATCHER"] = dispatcher

    response = client.post("/api/v1/action-center/approve/intent-1")

    assert response.status_code == 200
    assert response.get_json()["data"]["order"]["status"] == "approved"
    authoriser.assert_called_once_with(require_live_unlock=True)
    dispatcher.assert_called_once()
    resolved = queue.get("intent-1")
    assert resolved.status == "approved"
    assert resolved.broker_order_id == "BROKER-1"
    assert resolved.resolved_at is not None

    replay = client.post("/api/v1/action-center/approve/intent-1")
    assert replay.status_code == 409
    dispatcher.assert_called_once()


def test_rejection_never_dispatches(client, app, queue):
    _enqueue(queue)
    dispatcher = MagicMock()
    app.config["ACTION_CENTER_APPROVAL_DISPATCHER"] = dispatcher

    response = client.post(
        "/api/v1/action-center/reject/intent-1",
        json={"reason": "Operator rejected the entry"},
    )

    assert response.status_code == 200
    assert queue.get("intent-1").status == "rejected"
    dispatcher.assert_not_called()


def test_expired_intent_cannot_dispatch(client, app, queue):
    _enqueue(queue, ttl_minutes=0)
    dispatcher = MagicMock()
    app.config["ACTION_CENTER_APPROVAL_DISPATCHER"] = dispatcher

    response = client.post("/api/v1/action-center/approve/intent-1")

    assert response.status_code == 409
    assert queue.get("intent-1").status == "expired"
    dispatcher.assert_not_called()


def test_refused_dispatch_is_terminal_and_not_reported_as_pending(client, app, queue):
    from flinttrade_engine.action_center import ApprovalDispatchResult

    _enqueue(queue)
    app.config["ACTION_CENTER_APPROVAL_DISPATCHER"] = lambda _request: ApprovalDispatchResult.refused(
        403,
        "Fresh safety check blocked the order",
    )

    response = client.post("/api/v1/action-center/approve/intent-1")

    assert response.status_code == 403
    assert "not dispatched" in response.get_json()["message"].lower()
    failed = queue.get("intent-1")
    assert failed.status == "failed"
    assert failed.outcome_uncertain is False
    assert queue.list_pending() == []


def test_dispatch_exception_is_terminal_and_truthfully_uncertain(client, app, queue):
    _enqueue(queue)

    def fail(_request):
        raise TimeoutError("private broker detail")

    app.config["ACTION_CENTER_APPROVAL_DISPATCHER"] = fail

    response = client.post("/api/v1/action-center/approve/intent-1")

    assert response.status_code == 503
    assert "inspect" in response.get_json()["message"].lower()
    failed = queue.get("intent-1")
    assert failed.status == "failed"
    assert failed.outcome_uncertain is True
    assert "private broker detail" not in response.get_data(as_text=True)


def test_missing_dispatcher_leaves_request_pending(client, app, queue):
    _enqueue(queue)
    app.config.pop("ACTION_CENTER_APPROVAL_DISPATCHER")

    response = client.post("/api/v1/action-center/approve/intent-1")

    assert response.status_code == 503
    assert queue.get("intent-1").status == "pending"


def test_approve_all_is_disabled_and_dispatches_nothing(client, app, queue):
    _enqueue(queue, "intent-1")
    _enqueue(queue, "intent-2")
    dispatcher = MagicMock()
    app.config["ACTION_CENTER_APPROVAL_DISPATCHER"] = dispatcher

    response = client.post("/api/v1/action-center/approve-all")

    assert response.status_code == 405
    assert dispatcher.call_count == 0
    assert {request.id for request in queue.list_pending()} == {"intent-1", "intent-2"}


def test_admin_history_uses_the_same_queue(client, queue):
    request = _enqueue(queue)
    queue.claim_for_dispatch(request.id)
    queue.mark_approved(request.id, broker_order_id="BROKER-1")

    response = client.get("/admin/action-center/history")

    assert response.status_code == 200
    assert response.get_json()["data"]["requests"][0]["broker_order_id"] == "BROKER-1"
