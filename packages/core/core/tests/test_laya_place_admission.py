"""Operator place calls Laya before SafetySystem or the practice sandbox.

Open-place cases in this file seed Ready themselves. The process default stays Down.
"""

from __future__ import annotations

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
    assert "Down" in body["reason"]
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
    assert "Down" in body["reason"]
    sandbox.place_order.assert_not_called()


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
