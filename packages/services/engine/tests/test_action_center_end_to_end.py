"""End-to-end contract tests for durable Action Centre approval dispatch."""

from __future__ import annotations

from pathlib import Path
from typing import Any

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
    from flinttrade_engine.action_center_routes import action_center_bp

    flask_app = Flask(__name__)
    flask_app.config.update(
        TESTING=True,
        PENDING_ORDER_QUEUE=queue,
        ACTION_CENTER_AUTHORISER=lambda require_live_unlock: None,
    )
    flask_app.register_blueprint(action_center_bp)
    return flask_app


def _enqueue(queue, *, request_id: str = "intent-1", ttl_minutes: int = 5):
    return queue.enqueue(
        {
            "symbol": "RELIANCE",
            "exchange": "NSE",
            "action": "BUY",
            "quantity": "1",
            "pricetype": "MARKET",
            "product": "MIS",
            "strategy": "AutonomousAgent",
        },
        reason="Agent BUY signal awaiting operator approval",
        ttl_minutes=ttl_minutes,
        request_id=request_id,
        adapter_id="upstox",
        account_id="primary",
        source="autonomous-agent",
        intent_type="entry",
        producer_ref="agent-session-1",
    )


def test_pending_returns_terminal_shape_used_by_widget(app: Flask, queue) -> None:
    _enqueue(queue)

    response = app.test_client().get("/api/v1/action-center/pending")

    assert response.status_code == 200
    order = response.get_json()["data"]["orders"][0]
    assert order == {
        "id": "intent-1",
        "symbol": "RELIANCE",
        "exchange": "NSE",
        "action": "BUY",
        "quantity": 1,
        "price": 0.0,
        "order_type": "MARKET",
        "product": "MIS",
        "strategy": "AutonomousAgent",
        "created_at": order["created_at"],
        "expires_at": order["expires_at"],
        "reason": "Agent BUY signal awaiting operator approval",
        "broker": "upstox",
        "account_id": "primary",
        "source": "autonomous-agent",
        "status": "pending",
    }


def test_approve_claims_then_dispatches_once_and_records_success(app: Flask, queue) -> None:
    from flinttrade_engine.action_center import ApprovalDispatchResult

    _enqueue(queue)
    observed: list[tuple[str, str]] = []

    def dispatch(request: Any) -> ApprovalDispatchResult:
        observed.append((request.id, queue.get(request.id).status))
        return ApprovalDispatchResult.success("BROKER-42")

    app.config["ACTION_CENTER_APPROVAL_DISPATCHER"] = dispatch
    client = app.test_client()

    first = client.post("/api/v1/action-center/approve/intent-1")
    replay = client.post("/api/v1/action-center/approve/intent-1")

    assert first.status_code == 200
    assert first.get_json()["data"]["request"]["status"] == "approved"
    assert first.get_json()["data"]["request"]["broker_order_id"] == "BROKER-42"
    assert replay.status_code == 409
    assert observed == [("intent-1", "dispatching")]


def test_dispatch_refusal_is_terminal_and_never_retried(app: Flask, queue) -> None:
    from flinttrade_engine.action_center import ApprovalDispatchResult

    _enqueue(queue)
    calls = 0

    def dispatch(_request: Any) -> ApprovalDispatchResult:
        nonlocal calls
        calls += 1
        return ApprovalDispatchResult.refused(403, "Kill switch active")

    app.config["ACTION_CENTER_APPROVAL_DISPATCHER"] = dispatch
    client = app.test_client()

    first = client.post("/api/v1/action-center/approve/intent-1")
    replay = client.post("/api/v1/action-center/approve/intent-1")

    assert first.status_code == 403
    assert first.get_json()["data"]["request"]["status"] == "failed"
    assert queue.get("intent-1").status == "failed"
    assert replay.status_code == 409
    assert calls == 1


def test_dispatch_exception_records_uncertain_terminal_state(app: Flask, queue) -> None:
    _enqueue(queue)

    def dispatch(_request: Any) -> Any:
        raise RuntimeError("connection dropped")

    app.config["ACTION_CENTER_APPROVAL_DISPATCHER"] = dispatch

    response = app.test_client().post("/api/v1/action-center/approve/intent-1")

    assert response.status_code == 503
    request = queue.get("intent-1")
    assert request.status == "failed"
    assert request.outcome_uncertain is True
    assert "inspect" in request.failure_reason.lower()


def test_missing_dispatcher_leaves_request_pending(app: Flask, queue) -> None:
    _enqueue(queue)

    response = app.test_client().post("/api/v1/action-center/approve/intent-1")

    assert response.status_code == 503
    assert queue.get("intent-1").status == "pending"


def test_rejection_never_calls_dispatcher(app: Flask, queue) -> None:
    _enqueue(queue)
    calls: list[str] = []
    app.config["ACTION_CENTER_APPROVAL_DISPATCHER"] = lambda request: calls.append(request.id)

    response = app.test_client().post(
        "/api/v1/action-center/reject/intent-1",
        json={"reason": "Signal no longer valid"},
    )

    assert response.status_code == 200
    assert queue.get("intent-1").status == "rejected"
    assert calls == []


def test_expired_request_never_calls_dispatcher(app: Flask, queue) -> None:
    import time

    _enqueue(queue, ttl_minutes=0)
    time.sleep(0.05)
    calls: list[str] = []
    app.config["ACTION_CENTER_APPROVAL_DISPATCHER"] = lambda request: calls.append(request.id)

    response = app.test_client().post("/api/v1/action-center/approve/intent-1")

    assert response.status_code == 409
    assert queue.get("intent-1").status == "expired"
    assert calls == []


def test_all_endpoints_require_current_operator_auth(app: Flask, queue) -> None:
    _enqueue(queue)
    app.config["ACTION_CENTER_AUTHORISER"] = lambda require_live_unlock: (
        {"status": "error", "message": "Authentication required"},
        401,
    )
    client = app.test_client()

    assert client.get("/api/v1/action-center/pending").status_code == 401
    assert client.post("/api/v1/action-center/approve/intent-1").status_code == 401
    assert client.post("/api/v1/action-center/reject/intent-1").status_code == 401
    assert queue.get("intent-1").status == "pending"


def test_bulk_approval_is_disabled(app: Flask, queue) -> None:
    _enqueue(queue)

    response = app.test_client().post("/api/v1/action-center/approve-all")

    assert response.status_code == 405
    assert queue.get("intent-1").status == "pending"
