"""Operator place calls Laya before SafetySystem or the practice sandbox.

Open-place cases in this file seed Ready themselves. The process default stays Down.
"""

from __future__ import annotations

import json
from unittest.mock import AsyncMock, MagicMock

import pytest
from flask import Flask

from flinttrade_core.auth_routes import _create_token
from flinttrade_core.order_routes import orders_bp
from flinttrade_engine.laya import DecisionStatus, process_laya, reset_process_laya_for_tests
from flinttrade_engine.safety import SafetyConfig, SafetySystem, set_safety_gate_secret

_SECRET = b"0123456789abcdef0123456789abcdef"

_BODY = {
    "symbol": "RELIANCE",
    "exchange": "NSE",
    "action": "BUY",
    "quantity": 1,
    "price": 0,
    "product": "MIS",
    "order_type": "MARKET",
}


@pytest.fixture(autouse=True)
def _bind_secret() -> None:
    set_safety_gate_secret(_SECRET)
    reset_process_laya_for_tests()
    yield
    reset_process_laya_for_tests()


def _headers(mode: str, *, unlocked: bool = False) -> dict[str, str]:
    token = _create_token("operator", mode=mode, live_mode_unlocked=unlocked)
    return {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}


def _passing_safety() -> SafetySystem:
    safety = SafetySystem(SafetyConfig(check_market_hours=False))
    safety.check_order = MagicMock(return_value=[])
    return safety


def _live_app(backend_lease_proof: object, *, safety: SafetySystem | None = None) -> tuple[Flask, MagicMock, SafetySystem]:
    router = MagicMock()
    router.place_order = AsyncMock(return_value="SHOULD-NOT-REACH")
    router.backend_lease_proof = backend_lease_proof
    active_safety = safety or _passing_safety()
    app = Flask(__name__)
    app.config["TESTING"] = True
    app.config["BROKER_ROUTER"] = router
    app.config["SAFETY"] = active_safety
    app.config["SAFETY_CONFIG_READY"] = True
    app.register_blueprint(orders_bp)
    return app, router, active_safety


def _practice_app() -> tuple[Flask, MagicMock]:
    sandbox = MagicMock()
    sandbox.place_order.return_value = {"status": "success", "order_id": "PAPER-1"}
    app = Flask(__name__)
    app.config["TESTING"] = True
    app.config["DATA_SANDBOX_ENGINE"] = sandbox
    app.register_blueprint(orders_bp)
    return app, sandbox


@pytest.mark.unit
def test_live_down_denies_before_safety_and_the_gate(backend_lease_proof) -> None:
    app, router, safety = _live_app(backend_lease_proof)
    response = app.test_client().post(
        "/api/v1/orders/openalgo/place",
        json=_BODY,
        headers=_headers("live", unlocked=True),
    )
    body = response.get_json()
    assert response.status_code == 403
    assert body["code"] == "laya_denied"
    assert body["reason"] == body["message"]
    assert body["reason"] == "Laya is Down. Orders are paused until it's Ready."
    assert "Live" not in body["reason"]
    assert body["limits"]["max_quantity"] == 100
    safety.check_order.assert_not_called()
    router.place_order.assert_not_called()


@pytest.mark.unit
def test_live_clamp_stops_before_safety_and_names_the_reduced_quantity(backend_lease_proof) -> None:
    process_laya().set_status(DecisionStatus.READY)
    app, router, safety = _live_app(backend_lease_proof)
    response = app.test_client().post(
        "/api/v1/orders/openalgo/place",
        json={**_BODY, "quantity": 101},
        headers=_headers("live", unlocked=True),
    )
    body = response.get_json()
    assert response.status_code == 409
    assert body["code"] == "laya_clamp"
    assert body["message"] == "Qty reduced to 100 (Laya limit)"
    assert body["applied_quantity"] == 100
    safety.check_order.assert_not_called()
    router.place_order.assert_not_called()


@pytest.mark.unit
def test_degraded_live_stays_open_inside_the_tighter_ceiling(backend_lease_proof) -> None:
    process_laya().set_status(DecisionStatus.DEGRADED)
    app, router, safety = _live_app(backend_lease_proof)
    inside = app.test_client().post(
        "/api/v1/orders/openalgo/place",
        json=_BODY,
        headers=_headers("live", unlocked=True),
    )
    # Portfolio state is not stubbed here. Passing Laya reaches that safety
    # gather and stops there, which is past admission and short of a write.
    assert inside.status_code == 503
    assert inside.get_json().get("code") not in {"laya_denied", "laya_clamp"}
    assert "safety state" in inside.get_json()["message"].lower()
    router.place_order.assert_not_called()

    safety.check_order.reset_mock()
    router.place_order.reset_mock()
    over = app.test_client().post(
        "/api/v1/orders/openalgo/place",
        json={**_BODY, "quantity": 2},
        headers=_headers("live", unlocked=True),
    )
    over_body = over.get_json()
    assert over.status_code == 409
    assert over_body["code"] == "laya_clamp"
    assert over_body["message"] == "Qty reduced to 1 (Laya limit)"
    assert over_body["limits"]["max_quantity"] == 1
    safety.check_order.assert_not_called()
    router.place_order.assert_not_called()


@pytest.mark.unit
def test_client_cannot_mark_an_operator_place_as_chat(backend_lease_proof) -> None:
    process_laya().set_status(DecisionStatus.READY)
    app, router, _safety = _live_app(backend_lease_proof)
    response = app.test_client().post(
        "/api/v1/orders/openalgo/place",
        json={**_BODY, "source": "chat"},
        headers=_headers("live", unlocked=True),
    )
    assert response.status_code == 503
    body = response.get_json()
    assert body.get("code") != "laya_denied"
    assert "Chat" not in body["message"]
    assert "safety state" in body["message"].lower()
    router.place_order.assert_not_called()


@pytest.mark.unit
def test_practice_down_denies_before_the_sandbox() -> None:
    app, sandbox = _practice_app()
    response = app.test_client().post(
        "/api/v1/orders/place",
        json=_BODY,
        headers=_headers("practice"),
    )
    body = response.get_json()
    assert response.status_code == 403
    assert body["code"] == "laya_denied"
    assert body["reason"] == "Laya is Down. Orders are paused until it's Ready."
    assert "Live" not in body["reason"]
    sandbox.place_order.assert_not_called()


@pytest.mark.unit
def test_unqualified_ready_live_names_the_qualification_requirement(backend_lease_proof) -> None:
    process_laya().apply_runtime_status(DecisionStatus.READY, live_qualified=False)
    app, router, safety = _live_app(backend_lease_proof)
    response = app.test_client().post(
        "/api/v1/orders/openalgo/place",
        json=_BODY,
        headers=_headers("live", unlocked=True),
    )
    body = response.get_json()
    assert response.status_code == 403
    assert body["code"] == "laya_denied"
    assert body["reason"] == "Laya isn't qualified for Live yet. Practice orders are available."
    assert "Orders are paused" not in body["reason"]
    safety.check_order.assert_not_called()
    router.place_order.assert_not_called()


@pytest.mark.unit
def test_unqualified_degraded_live_uses_the_same_sentence(backend_lease_proof) -> None:
    process_laya().apply_runtime_status(DecisionStatus.DEGRADED, live_qualified=False)
    app, router, safety = _live_app(backend_lease_proof)
    response = app.test_client().post(
        "/api/v1/orders/openalgo/place",
        json=_BODY,
        headers=_headers("live", unlocked=True),
    )
    body = response.get_json()
    assert response.status_code == 403
    assert body["reason"] == "Laya isn't qualified for Live yet. Practice orders are available."
    safety.check_order.assert_not_called()
    router.place_order.assert_not_called()


@pytest.mark.unit
def test_unqualified_ready_practice_reaches_the_sandbox_without_saying_live() -> None:
    process_laya().apply_runtime_status(DecisionStatus.READY, live_qualified=False)
    app, sandbox = _practice_app()
    response = app.test_client().post(
        "/api/v1/orders/place",
        json=_BODY,
        headers=_headers("practice"),
    )
    assert response.status_code == 200
    assert "Live" not in response.get_data(as_text=True)
    sandbox.place_order.assert_called_once()


@pytest.mark.unit
def test_practice_ready_still_reaches_the_sandbox() -> None:
    process_laya().set_status(DecisionStatus.READY)
    app, sandbox = _practice_app()
    response = app.test_client().post(
        "/api/v1/orders/place",
        json=_BODY,
        headers=_headers("practice"),
    )
    assert response.status_code == 200
    sandbox.place_order.assert_called_once()


@pytest.mark.unit
def test_explore_stays_on_the_mode_refusal() -> None:
    process_laya().set_status(DecisionStatus.READY)
    app, _router, safety = _live_app(MagicMock())
    response = app.test_client().post(
        "/api/v1/orders/place",
        json=_BODY,
        headers=_headers("explore"),
    )
    body = response.get_json()
    assert response.status_code == 403
    assert body.get("code") == "mode_blocked"
    assert "Explore mode" in body["message"]
    safety.check_order.assert_not_called()


class _ScriptedHost:
    def __init__(self, answers: dict[str, object]) -> None:
        self.answers = answers
        self.calls: list[str] = []

    def decide(self, state: str, questions: object) -> dict[str, object]:
        self.calls.append(state)
        return {"answers": self.answers}


def _choice(deny_key: str, deny_p: float) -> dict[str, object]:
    other = "A" if deny_key == "B" else "B"
    return {"choice": other, "probabilities": {deny_key: deny_p, other: 1 - deny_p}}


def _allow_answers() -> dict[str, object]:
    return {
        "rationale": _choice("B", 0.1),
        "tilt": _choice("A", 0.1),
        "side": _choice("A", 0.1),
    }


def _deny_answers() -> dict[str, object]:
    return {**_allow_answers(), "tilt": _choice("A", 0.95)}


@pytest.mark.unit
def test_practice_place_without_a_note_clamps_instead_of_demanding_a_reason() -> None:
    host = _ScriptedHost(_allow_answers())
    process_laya().set_status(DecisionStatus.READY)
    process_laya().set_decision_client(host)
    app, sandbox = _practice_app()
    response = app.test_client().post(
        "/api/v1/orders/place",
        json=_BODY,
        headers=_headers("practice"),
    )
    body = response.get_json()
    assert response.status_code == 409
    assert body["code"] == "laya_clamp"
    assert body["reason"] == "Laya is uncertain. Quantity stays inside the tighter limit."
    assert body["message"] == "Qty held at 1 (Laya limit)"
    assert "concrete reason is required" not in json.dumps(body)
    assert "Live" not in body["reason"]
    sandbox.place_order.assert_not_called()
    assert host.calls == []

    blank = app.test_client().post(
        "/api/v1/orders/place",
        json={**_BODY, "note": "   ", "rationale": ""},
        headers=_headers("practice"),
    )
    assert blank.status_code == 409
    assert blank.get_json()["reason"] == "Laya is uncertain. Quantity stays inside the tighter limit."
    assert host.calls == []
    sandbox.place_order.assert_not_called()


@pytest.mark.unit
def test_live_place_without_a_note_denies_as_uncertain(backend_lease_proof) -> None:
    host = _ScriptedHost(_allow_answers())
    process_laya().set_status(DecisionStatus.READY)
    process_laya().set_decision_client(host)
    app, router, safety = _live_app(backend_lease_proof)
    response = app.test_client().post(
        "/api/v1/orders/openalgo/place",
        json=_BODY,
        headers=_headers("live", unlocked=True),
    )
    body = response.get_json()
    assert response.status_code == 403
    assert body["code"] == "laya_denied"
    assert body["reason"] == "Laya is uncertain. Live stays closed."
    assert "concrete reason is required" not in json.dumps(body)
    safety.check_order.assert_not_called()
    router.place_order.assert_not_called()
    assert host.calls == []


@pytest.mark.unit
def test_practice_model_deny_never_reaches_the_sandbox() -> None:
    host = _ScriptedHost(_deny_answers())
    process_laya().set_status(DecisionStatus.READY)
    process_laya().set_decision_client(host)
    app, sandbox = _practice_app()
    response = app.test_client().post(
        "/api/v1/orders/place",
        json={**_BODY, "rationale": "I am chasing the last loss."},
        headers=_headers("practice"),
    )
    assert response.status_code == 403
    assert response.get_json()["code"] == "laya_denied"
    sandbox.place_order.assert_not_called()
    assert host.calls


@pytest.mark.unit
def test_practice_model_allow_reaches_the_sandbox() -> None:
    host = _ScriptedHost(_allow_answers())
    process_laya().set_status(DecisionStatus.READY)
    process_laya().set_decision_client(host)
    app, sandbox = _practice_app()
    response = app.test_client().post(
        "/api/v1/orders/place",
        json={**_BODY, "rationale": "Buying the planned breakout."},
        headers=_headers("practice"),
    )
    assert response.status_code == 200
    sandbox.place_order.assert_called_once()


@pytest.mark.unit
def test_live_model_deny_stops_before_safety_and_the_router(backend_lease_proof) -> None:
    host = _ScriptedHost(_deny_answers())
    process_laya().set_status(DecisionStatus.READY)
    process_laya().set_decision_client(host)
    app, router, safety = _live_app(backend_lease_proof)
    response = app.test_client().post(
        "/api/v1/orders/openalgo/place",
        json={**_BODY, "rationale": "I need to win it back."},
        headers=_headers("live", unlocked=True),
    )
    assert response.status_code == 403
    assert response.get_json()["code"] == "laya_denied"
    safety.check_order.assert_not_called()
    router.place_order.assert_not_called()


@pytest.mark.unit
def test_action_center_model_deny_stops_before_safety(backend_lease_proof, monkeypatch) -> None:
    import threading
    import time

    from flinttrade_core.agent_routes import _RUNNER, _RUNNER_LOCK, _reset_runner_for_tests, dispatch_action_center_approval
    from flinttrade_engine.action_center import ApprovalRequest

    host = _ScriptedHost(_deny_answers())
    process_laya().set_status(DecisionStatus.READY)
    process_laya().set_decision_client(host)
    app, router, safety = _live_app(backend_lease_proof)
    monkeypatch.setattr(
        "flinttrade_core.order_routes._require_live_payload",
        lambda **_kwargs: ({"jti": "j", "sub": "operator"}, None),
    )
    monkeypatch.setattr("flinttrade_core.agent_routes._acl_grants_agent", lambda *_args, **_kwargs: True)
    trader = MagicMock()
    trader.stop_requested = False
    thread = threading.Thread(target=lambda: time.sleep(2), daemon=True)
    thread.start()
    approval = ApprovalRequest(
        id="approval-1",
        order_params={
            "symbol": "RELIANCE",
            "exchange": "NSE",
            "action": "BUY",
            "quantity": 1,
            "product": "MIS",
            "order_type": "MARKET",
        },
        reason="I need to win the last loss back.",
        created_at="t",
        expires_at="t",
        adapter_id="openalgo",
        account_id="default",
        source="autonomous-agent",
        intent_type="entry",
        producer_ref="prod-1",
        intent_context={"entry_price": 100.0, "stop_loss": 90.0, "take_profit": 110.0},
    )
    try:
        with _RUNNER_LOCK:
            _RUNNER.clear()
            _RUNNER.update(
                {
                    "producer_ref": "prod-1",
                    "trader": trader,
                    "thread": thread,
                    "loop": None,
                    "params": {"broker": "openalgo", "account_id": "default"},
                }
            )
        with app.app_context():
            result = dispatch_action_center_approval(approval)
    finally:
        _reset_runner_for_tests()
    assert result.succeeded is False
    assert result.status_code == 403
    assert "tilt or revenge" in result.message
    safety.check_order.assert_not_called()
    router.place_order.assert_not_called()
    assert host.calls
    assert "win the last loss back" in host.calls[0]
