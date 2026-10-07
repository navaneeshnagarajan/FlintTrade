"""Presence-sensitive intent controls before real gate mint/consume or wire IO."""
from __future__ import annotations

from copy import deepcopy
from types import SimpleNamespace
from urllib.parse import urlsplit

import pytest

from flinttrade_core.auth_routes import _create_token
from flinttrade_engine.safety import SafetyGate
from flinttrade_gateway.brokers._base import Session
from flinttrade_gateway.brokers.groww import GrowwAdapter
from flinttrade_gateway.router import BrokerRouter
from packages.core.core.tests.test_ingress_safety_runtime import exact_egress_latch as exact_egress_latch, route_stack as route_stack
from packages.core.core.tests.test_indmoney_http_evidence import native_http_stack as native_http_stack, _place as place_indmoney, _MARKET_BODY

pytestmark = pytest.mark.integration


@pytest.fixture
def groww_stack(route_stack, monkeypatch):
    import flinttrade_engine.safety as safety_module

    app, source, _sdk, old = route_stack
    wire, consumed, minted = [], [], []
    session = Session("synthetic", 4102444800.0, "route-account", "groww")
    gate = SafetyGate()

    def consume(identifier):
        result = gate.consume(identifier)
        consumed.append(result)
        return result

    def mint(*args, **kwargs):
        minted.append(args[0])
        return original_mint(*args, **kwargs)

    original_mint = safety_module.gate_order
    monkeypatch.setattr(safety_module, "gate_order", mint)

    def transport(method, url, *, headers, params=None, json_body=None):
        assert (method, urlsplit(url).path) == ("POST", "/v1/order/create")
        wire.append(deepcopy(json_body))
        return 200, {"status": "SUCCESS", "payload": {"groww_order_id": "groww-ack-1"}}

    def resolve(context, broker, account):
        assert (broker, account) == ("groww", "route-account")
        return session

    router = BrokerRouter({"groww": GrowwAdapter(http_factory=lambda: transport)}, resolve,
                          consume_gate=consume, backend_lease_proof=old.backend_lease_proof)
    app.config["BROKER_ROUTER"] = router
    app.config["NATIVE_ADAPTERS"] = {"groww": source}
    app.config["REGISTRY"] = SimpleNamespace(get_session_for=lambda b, a: resolve(None, b, a))
    yield SimpleNamespace(app=app, wire=wire, consumed=consumed, minted=minted)
    router.revoke_and_drain(timeout=0)


def groww_place(stack, fields):
    return stack.app.test_client().post("/api/v1/orders/place", json={
        "broker": "groww", "account_id": "route-account", "symbol": "INFY", "exchange": "NSE",
        "product": "MIS", "action": "SELL", "quantity": "2", "price": "100", "pricetype": "LIMIT",
        "strategy": "review-ref-01", **fields,
    }, headers={"Authorization": "Bearer " + _create_token("operator", mode="live", live_mode_unlocked=True)})


@pytest.mark.parametrize("fields", [
    {"trailing_jump": True}, {"trailing_jump": False}, {"trailing_jump": None}, {"trailing_jump": "NaN"},
    {"trailing_jump": []}, {"trailing_jump": -1}, {"trailing_jump": "0.01"}, {"trailing_jump": ""},
    {"iceberg_legs": True}, {"iceberg_legs": None}, {"iceberg_legs": 1.5}, {"iceberg_legs": "0.0001"},
    {"iceberg_legs": "Infinity"}, {"iceberg_legs": "2"}, {"iceberg_legs": {}},
    {"target_price": "110"}, {"stop_loss_price": "90"}, {"price1": "100"}, {"quantity1": "2"},
    {"target_trigger_type": "UP"}, {"entry_trigger_type": True}, {"stop_loss_trigger_type": []},
    {"is_tsl": True}, {"is_tsl": 0}, {"is_tsl": "false"}, {"tsl_step_size": "5"},
    {"trailingJump": "5"}, {"icebergLegs": "2"}, {"stop_loss_trailing_gap": "5"},
])
def test_active_or_malformed_groww_neighbour_intent_never_mints_or_dispatches(groww_stack, fields):
    response = groww_place(groww_stack, fields)
    assert response.status_code == 400, response.get_json()
    assert groww_stack.minted == [] and groww_stack.consumed == [] and groww_stack.wire == []


@pytest.mark.parametrize("fields", [
    {}, {"trailing_jump": "0"}, {"iceberg_legs": 0}, {"is_tsl": False}, {"tsl_step_size": 0},
    {"trailing_jump": 0.0, "iceberg_legs": "0", "is_tsl": False, "tsl_step_size": "0e0"},
])
def test_absent_and_exact_inactive_groww_intent_retains_ordinary_positive_control(groww_stack, fields):
    response = groww_place(groww_stack, fields)
    assert response.status_code == 200, response.get_json()
    assert len(groww_stack.minted) == 1 and groww_stack.consumed == [True]
    assert groww_stack.wire == [{
        "trading_symbol": "INFY", "quantity": 2, "validity": "DAY", "exchange": "NSE", "segment": "CASH",
        "product": "MIS", "order_type": "LIMIT", "transaction_type": "SELL", "order_reference_id": "review-ref-01",
        "price": 100.0,
    }]
    assert groww_stack.minted[0].market_protection is None


@pytest.mark.parametrize("fields", [
    {"trailing_jump": True}, {"trailing_jump": False}, {"trailing_jump": None}, {"trailing_jump": "NaN"},
    {"is_tsl": "true"}, {"is_tsl": 1}, {"is_tsl": None}, {"tsl_step_size": True},
    {"tsl_step_size": ""}, {"tsl_step_size": {}}, {"tsl_step_size": "Infinity"}, {"tsl_step_size": -1},
    {"trailingJump": 1}, {"isTSL": True},
])
@pytest.mark.parametrize("path", ["/api/v1/orders/place", "/api/v1/orders/indmoney/place"])
def test_indstocks_malformed_or_active_trailing_neighbours_cannot_disappear(native_http_stack, fields, path):
    stack = native_http_stack
    response = place_indmoney(stack, path=path, **fields)
    assert response.status_code == 400, response.get_json()
    assert stack.captured == [] and stack.sink.prepared == [] and stack.transport.calls == []


@pytest.mark.parametrize("fields", [{}, {"is_tsl": False}, {"tsl_step_size": 0}, {"trailing_jump": "0"},
                                   {"is_tsl": False, "tsl_step_size": "0", "trailing_jump": 0.0}])
def test_exact_inactive_indstocks_controls_keep_native_body_and_ack_limits(native_http_stack, fields):
    stack = native_http_stack
    stack.transport.expect("/order", _MARKET_BODY, {"status": "success", "data": {
        "order_id": "EQ-OFFLINE", "order_status": "INITIATED",
    }})
    response = place_indmoney(stack, **fields)
    assert response.status_code == 200, response.get_json()
    assert len(stack.transport.calls) == 1
    assert response.get_json()["execution_effects"]["trailing_active"] is False
    assert response.get_json()["execution_effects"]["limitations"] == ["MARKET_TO_LIMIT"]


@pytest.mark.parametrize("value", [0, 1, "false", "true", {}, []])
def test_canonical_market_protection_remains_strict_boolean_at_http(native_http_stack, value):
    stack = native_http_stack
    response = place_indmoney(stack, market_protection=value)
    assert response.status_code == 400, response.get_json()
    assert stack.captured == [] and stack.transport.calls == []
