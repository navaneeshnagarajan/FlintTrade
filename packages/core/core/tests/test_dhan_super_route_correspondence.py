"""Actual Super TARGET HTTP → SafetyGate → BrokerRouter → pinned Dhan SDK.

Only HTTP and synthetic session lookup are injected. No live credentials,
readiness changes or native HTTP listing cutover are involved.
"""

from __future__ import annotations

from copy import deepcopy
from types import SimpleNamespace
from typing import Any

import pytest
from dhanhq import ForeverOrder, Funds, Order as SDKOrder, Portfolio, SuperOrder

from flinttrade_core.app import create_flask_app
from flinttrade_core.auth_routes import _create_token
from flinttrade_engine.reduce_only import reset_reduce_only_for_tests
from flinttrade_engine.safety import SafetyConfig, SafetyGate, SafetySystem
from flinttrade_gateway.brokers._base import Session
from flinttrade_gateway.brokers.dhan import DhanAdapter
from flinttrade_gateway.router import BrokerRouter

pytestmark = pytest.mark.integration


class RecordingHTTP:
    def __init__(self) -> None:
        self.calls: list[tuple[str, str, Any]] = []
        self.super_row = {
            "orderId": "super-fixture", "orderStatus": "PENDING", "tradingSymbol": "HDFCBANK",
            "securityId": "1333", "exchangeSegment": "NSE_EQ", "transactionType": "BUY", "productType": "CNC",
            "orderType": "LIMIT", "quantity": 10, "filledQty": 0, "price": 1500, "legDetails": [
                {"legName": "TARGET_LEG", "orderStatus": "PENDING", "orderId": "super-fixture",
                 "quantity": 10, "filledQty": 0, "price": 1550, "orderType": "LIMIT", "transactionType": "SELL"},
                {"legName": "STOP_LOSS_LEG", "orderStatus": "PENDING", "orderId": "super-fixture",
                 "quantity": 10, "filledQty": 0, "price": 1400, "orderType": "LIMIT", "transactionType": "SELL"},
            ],
        }

    def get(self, endpoint: str) -> dict[str, Any]:
        self.calls.append(("GET", endpoint, None))
        if endpoint == "/super/orders":
            return {"status": "success", "data": [deepcopy(self.super_row)]}
        assert endpoint in {"/positions", "/orders", "/forever/orders", "/alerts/orders", "/trades", "/holdings"}
        return {"status": "success", "data": []}

    def post(self, endpoint: str, payload: dict[str, Any]) -> dict[str, Any]:
        assert endpoint == "/margincalculator"
        self.calls.append(("POST", endpoint, deepcopy(payload)))
        return {"status": "success", "data": {"totalMargin": 100}}

    def put(self, endpoint: str, payload: dict[str, Any]) -> dict[str, Any]:
        assert endpoint == "/super/orders/super-fixture"
        self.calls.append(("PUT", endpoint, deepcopy(payload)))
        return {"status": "success", "data": {"orderId": "super-fixture", "orderStatus": "TRANSIT"}}


class RecordingSDK(SDKOrder, ForeverOrder, SuperOrder, Portfolio, Funds):
    def __init__(self, transport: RecordingHTTP) -> None:
        self.dhan_http = transport


@pytest.fixture
def route_stack(backend_lease_factory):
    reset_reduce_only_for_tests()
    safety = SafetySystem(SafetyConfig(check_market_hours=False))
    app = create_flask_app(safety=safety, safety_config_ready=True, backend_lease_proof=backend_lease_factory())
    app.config["TESTING"] = True
    transport = RecordingHTTP()
    sdk = RecordingSDK(transport)
    adapter = DhanAdapter(client_factory=lambda _session: sdk, security_resolver=lambda _symbol, _exchange: "1333")
    session = Session("synthetic-token", 4102444800.0, "route-account", "dhan")

    def session_for(_context: Any, broker: str, account: str) -> Session:
        assert (broker, account) == ("dhan", "route-account")
        return session

    consumed = []
    gate = SafetyGate()

    def consume(*args: Any, **kwargs: Any) -> Any:
        result = gate.consume(*args, **kwargs)
        consumed.append(result)
        return result

    router = BrokerRouter(
        {"dhan": adapter}, session_for, consume_gate=consume, backend_lease_proof=backend_lease_factory(),
    )
    app.config["BROKER_ROUTER"] = router
    app.config["NATIVE_ADAPTERS"] = {"dhan": adapter}
    app.config["REGISTRY"] = SimpleNamespace(get_session_for=lambda broker, account: session_for(None, broker, account))
    yield app, transport, consumed
    router.revoke_and_drain(timeout=0.0)
    reset_reduce_only_for_tests()


def modify(app, changes: dict[str, Any], *, mode: str = "live", unlocked: bool = True):
    return app.test_client().put(
        "/api/v1/orders/super/super-fixture",
        json={"broker": "dhan", "account_id": "route-account", "changes": changes},
        headers={"Authorization": f"Bearer {_create_token('operator', mode=mode, live_mode_unlocked=unlocked)}"},
    )


def test_super_target_actual_route_preserves_documented_target_price_and_consumes_real_gate(route_stack) -> None:
    app, transport, consumed = route_stack

    response = modify(app, {"leg_name": "TARGET_LEG", "target_price": "1555"})

    assert response.status_code == 200, response.get_json()
    assert len(consumed) == 1
    assert [call for call in transport.calls if call[0] == "PUT"] == [
        ("PUT", "/super/orders/super-fixture", {
            "orderId": "super-fixture", "legName": "TARGET_LEG", "targetPrice": 1555.0,
        }),
    ]
    assert transport.calls[0] == ("GET", "/super/orders", None)
    assert len([call for call in transport.calls if call[:2] == ("POST", "/margincalculator")]) == 2
    assert "filled_quantity" not in response.get_json() and "closed" not in response.get_json()


def test_super_target_price_alias_is_not_repaired_into_native_intent(route_stack) -> None:
    app, transport, consumed = route_stack

    response = modify(app, {"leg_name": "TARGET_LEG", "price": "1555"})

    # A pure malformed request is a pre-dispatch 400, not a broker failure;
    # keep the no-invented-alias/no-native-PUT assertion and strengthen it.
    assert response.status_code == 400, response.get_json()
    assert not [call for call in transport.calls if call[0] == "PUT"]
    assert consumed == [] and transport.calls == []


@pytest.mark.parametrize("mode,unlocked", [("practice", True), ("live", False)])
def test_super_target_route_retains_mode_and_unlock_guards(route_stack, mode: str, unlocked: bool) -> None:
    app, transport, consumed = route_stack

    response = modify(app, {"leg_name": "TARGET_LEG", "target_price": "1555"}, mode=mode, unlocked=unlocked)

    assert response.status_code == 403, response.get_json()
    assert transport.calls == [] and consumed == []


@pytest.mark.parametrize("missing", ["quantity", "filledQty"])
def test_native_super_child_missing_quantity_or_fill_cannot_borrow_parent_evidence(route_stack, missing: str) -> None:
    app, transport, consumed = route_stack
    target = transport.super_row["legDetails"][0]
    del target[missing]
    target.update({"totalQuatity": 0, "remainingQuantity": 0, "triggeredQuantity": 0})

    response = modify(app, {"leg_name": "TARGET_LEG", "target_price": "1555"})

    assert response.status_code == 409, response.get_json()
    assert consumed == []
    assert transport.calls == [("GET", "/super/orders", None)]


def test_official_zero_missing_super_leg_fixture_is_observable_but_not_modification_authority(route_stack) -> None:
    app, transport, consumed = route_stack
    # Official v2 list schema: same resource ID, native totalQuatity zero only
    # on STOP, remaining/triggered zero on both, no confirmed leg fills.
    transport.super_row["legDetails"] = [
        {"orderId": "super-fixture", "legName": "STOP_LOSS_LEG", "transactionType": "SELL",
         "totalQuatity": 0, "remainingQuantity": 0, "triggeredQuantity": 0, "price": 1400,
         "orderStatus": "PENDING", "trailingJump": 10},
        {"orderId": "super-fixture", "legName": "TARGET_LEG", "transactionType": "SELL",
         "remainingQuantity": 0, "triggeredQuantity": 0, "price": 1550, "orderStatus": "PENDING", "trailingJump": 0},
    ]

    response = modify(app, {"leg_name": "TARGET_LEG", "target_price": "1555"})

    assert response.status_code == 409, response.get_json()
    assert response.get_json()["message"] == "Authoritative super-order leg quantity is unavailable"
    assert consumed == [] and transport.calls == [("GET", "/super/orders", None)]
