"""Raw HTTP intent and bounded broker-error public caller regressions.

Normal factory, real gates/router and pinned inert resources; no broker IO.
"""
from __future__ import annotations

from types import SimpleNamespace

import pytest

from packages.core.core.tests.test_ingress_safety_runtime import exact_egress_latch as exact_egress_latch, route_stack as route_stack
from packages.core.core.tests.test_dhan_super_route_correspondence import (
    route_stack as _super_stack, modify as modify_super,
)
from packages.core.core.tests.test_upstox_native_propagation import _Books
from packages.integrations.gateway.tests.brokers.test_kotakneo_legacy_runtime import runtime as runtime
from packages.core.core.tests.test_indmoney_http_evidence import native_http_stack as native_http_stack

super_stack = _super_stack
pytestmark = pytest.mark.integration


def test_kotak_rejection_reason_survives_actual_gated_http(runtime, backend_lease_factory):
    from flinttrade_core.app import create_flask_app
    from flinttrade_core.auth_routes import _create_token
    from flinttrade_core.exceptions import OrderRejectedByBroker
    from flinttrade_engine.reduce_only import reset_reduce_only_for_tests
    from flinttrade_engine.safety import SafetyConfig, SafetyGate, SafetySystem
    from flinttrade_gateway.router import BrokerRouter

    reset_reduce_only_for_tests()
    adapter, session, facade, requests, _ = runtime({
        "stat": "Not_Ok", "stCode": 1021, "nOrdNo": "OID-1", "errMsg": "Order is completed",
    })
    session.algo_id = "TAG-1"
    # The upstream repair really retains the bounded native reason/code.
    with pytest.raises(OrderRejectedByBroker) as raised:
        facade.place_order({
            "exchange_segment": "nse_cm", "product": "MIS", "price": "100", "order_type": "L",
            "quantity": "2", "validity": "DAY", "trading_symbol": "SYNTHETIC-EQ",
            "transaction_type": "S", "amo": "NO", "disclosed_quantity": "0", "trigger_price": "0", "tag": "TAG-1",
        })
    assert raised.value.broker_code == "1021"
    assert raised.value.broker_message == "Order is completed"
    upstream_calls = len(requests)

    proof = backend_lease_factory()
    app = create_flask_app(safety=SafetySystem(SafetyConfig(check_market_hours=False)),
                           safety_config_ready=True, backend_lease_proof=proof)
    app.config["TESTING"] = True
    router = BrokerRouter({"kotakneo": adapter}, lambda _ctx, _broker, _account: session,
                          consume_gate=SafetyGate().consume, backend_lease_proof=proof)
    app.config["BROKER_ROUTER"] = router
    app.config["NATIVE_ADAPTERS"] = {"kotakneo": _Books()}
    app.config["REGISTRY"] = SimpleNamespace(get_session_for=lambda _b, _a: session)
    try:
        response = app.test_client().post("/api/v1/orders/place", json={
            "broker": "kotakneo", "account_id": "synthetic", "symbol": "INFY", "exchange": "NSE",
            "product": "MIS", "action": "SELL", "quantity": "2", "price": "100", "pricetype": "LIMIT",
        }, headers={"Authorization": "Bearer " + _create_token("operator", mode="live", live_mode_unlocked=True)})
        body = response.get_json()
        print("KOTAK_HTTP_NATIVE_REJECTION", {"http_status": response.status_code, "body": body,
              "new_transport_calls": len(requests) - upstream_calls,
              "upstream_broker_code": raised.value.broker_code, "upstream_broker_message": raised.value.broker_message})
        assert len(requests) - upstream_calls == 1
        assert "1021" in str(body) and "Order is completed" in str(body), "Native rejection reason/code lost at HTTP boundary"
    finally:
        router.revoke_and_drain(timeout=0)
        reset_reduce_only_for_tests()
@pytest.mark.parametrize("intent", [{"trailing_jump": 5}, {"is_tsl": True}, {"tsl_step_size": 5}])
def test_active_indstocks_trailing_intent_is_refused_at_actual_http(native_http_stack, intent):
    from packages.core.core.tests.test_indmoney_http_evidence import _place, _MARKET_BODY
    from flinttrade_gateway.brokers import indmoney_mapping as mapping

    # Positive upstream refusal proves this is not a missing broker feature:
    # the existing legacy mapper deliberately refuses this ignored intent.
    requested = SimpleNamespace(symbol="SYNTHETIC", exchange="NSE", product="CNC", action="BUY",
                                quantity="5", price="0", pricetype="MARKET", variety="regular", **intent)
    with pytest.raises(mapping.IndMoneyMappingError, match="TSL_IGNORED"):
        mapping.to_place_order_payload(requested, "123", algo_id="99999")
    stack = native_http_stack
    stack.transport.expect("/order", _MARKET_BODY, {"status": "success", "data": {
        "order_id": "EQ-OFFLINE", "order_status": "INITIATED",
    }})
    response = _place(stack, **intent)
    print("INDSTOCKS_TRAILING_HTTP", {"intent": intent, "http_status": response.status_code,
          "body": response.get_json(), "transport_calls": stack.transport.calls,
          "signed_canonical_trailing": [fields["order"].trailing_jump for _, fields in stack.captured]})
    assert response.status_code >= 400 and stack.transport.calls == [], "Raw active protection intent disappeared before canonical signing"


class _KotakBooks(_Books):
    async def order_book(self, _session):
        return [{"orderid": "OID-1", "symbol": "INFY", "exchange": "NSE", "product": "MIS",
                 "action": "SELL", "quantity": "2", "filled_quantity": "0", "status": "OPEN",
                 "pricetype": "LIMIT", "price": "100", "trigger_price": "0", "validity": "DAY",
                 "disclosed_quantity": "0", "broker_product": "MIS", "variety": "regular", "amo": False,
                 "broker_order_generation_type": "NA"}]


@pytest.mark.parametrize("operation", ["place", "modify", "cancel"])
def test_known_native_broker_reason_is_bounded_and_keeps_exact_origin(runtime, backend_lease_factory, operation):
    from flinttrade_core.app import create_flask_app
    from flinttrade_core.auth_routes import _create_token
    from flinttrade_engine.reduce_only import reset_reduce_only_for_tests
    from flinttrade_engine.safety import SafetyConfig, SafetyGate, SafetySystem
    from flinttrade_gateway.brokers.kotakneo_sdk import _install_sdk_log_filter
    from flinttrade_gateway.router import BrokerRouter

    secret = "SYNTHETIC-NOT-A-CREDENTIAL"
    _install_sdk_log_filter({"access_token": secret})
    reset_reduce_only_for_tests()
    adapter, session, _facade, requests, _ = runtime({
        "stat": "Not_Ok", "stCode": 1021, "errMsg": "Order is completed " + secret + " " + "reason " * 80,
    })
    proof = backend_lease_factory()
    app = create_flask_app(safety=SafetySystem(SafetyConfig(check_market_hours=False)),
                           safety_config_ready=True, backend_lease_proof=proof)
    app.config["TESTING"] = True
    gate = SafetyGate()
    consumed = []

    def consume(identifier):
        result = gate.consume(identifier)
        consumed.append(result)
        return result

    router = BrokerRouter({"kotakneo": adapter}, lambda _c, _b, _a: session,
                          consume_gate=consume, backend_lease_proof=proof)
    app.config["BROKER_ROUTER"] = router
    app.config["NATIVE_ADAPTERS"] = {"kotakneo": _KotakBooks() if operation != "place" else _Books()}
    app.config["REGISTRY"] = SimpleNamespace(get_session_for=lambda _b, _a: session)
    body = {"broker": "kotakneo", "account_id": "synthetic", "orderid": "OID-1", "symbol": "INFY",
            "exchange": "NSE", "product": "MIS", "action": "SELL", "quantity": "2", "price": "100",
            "pricetype": "LIMIT", "trigger_price": "0", "disclosed_quantity": "0", "validity": "DAY"}
    try:
        response = app.test_client().post("/api/v1/orders/" + operation, json=body,
            headers={"Authorization": "Bearer " + _create_token("operator", mode="live", live_mode_unlocked=True)})
        result = response.get_json()
        assert response.status_code == 500, result
        assert result["broker_code"] == "1021"
        assert result["broker_message"].startswith("Order is completed <redacted>")
        assert len(result["broker_message"]) <= 256 and secret not in str(result)
        assert result["dispatch_outcome"] == "unknown_after_dispatch" and result["retry_safe"] is False
        assert result["affected_item"]["broker"] == "kotakneo"
        assert result["affected_item"]["account_id"] == "synthetic"
        assert result["affected_item"]["operation"] == operation
        if operation != "place":
            assert result["affected_item"]["order_id"] == "OID-1"
        assert consumed == [True] and len(requests) == 1
    finally:
        router.revoke_and_drain(timeout=0)
        app.config["CLIENT"].close_sync()
        reset_reduce_only_for_tests()


@pytest.mark.parametrize("kind", ["timeout", "key", "unsupported", "not-implemented", "safety", "internal", "hostile", "hostile-known"])
def test_sdk_fault_class_is_not_proof_of_non_execution(route_stack, kind):
    from copy import deepcopy
    from flinttrade_core.exceptions import BrokerInternal, SafetyBypassError, UnsupportedCapabilityError
    from flinttrade_engine.reduce_only import contract_key, reserved_exit
    from flinttrade_gateway.brokers.dhan import DhanAdapter
    from packages.core.core.tests.test_ingress_safety_runtime import DispatchSDK
    from packages.core.core.tests.test_order_route_evidence_runtime import _place

    hooks = []

    class HostileFault(RuntimeError):
        @property
        def broker_message(self):
            hooks.append("message")
            raise AssertionError("Do not duck-type broker exceptions")

        @property
        def broker_code(self):
            hooks.append("code")
            raise AssertionError("Do not duck-type broker exceptions")

        def __str__(self):
            hooks.append("str")
            raise AssertionError("Do not stringify arbitrary exceptions")

    class HostileIdentity:
        def __eq__(self, other):
            hooks.append("identity-comparison")
            raise AssertionError("Validate broker identity type before comparison")

    malformed_known = BrokerInternal("Private native summary is not public", broker_id=HostileIdentity())
    error = {
        "timeout": TimeoutError("SYNTHETIC-private-context"), "key": KeyError("SYNTHETIC-private-context"),
        "unsupported": UnsupportedCapabilityError("SYNTHETIC-private-context"),
        "not-implemented": NotImplementedError("SYNTHETIC-private-context"),
        "safety": SafetyBypassError("SYNTHETIC-private-context"),
        "internal": BrokerInternal("SYNTHETIC-private-context", broker_id="dhan", broker_code="503"),
        "hostile": HostileFault(), "hostile-known": malformed_known,
    }[kind]
    wire = []

    class HTTP:
        def post(self, endpoint, payload):
            assert endpoint == "/orders"
            wire.append(deepcopy(payload))
            raise error

    app, source, _sdk, router = route_stack
    router._adapters["dhan"] = DhanAdapter(client_factory=lambda _s: DispatchSDK(HTTP()),
                                          security_resolver=lambda _s, _e: "fixture-security")
    response = _place(app, 10)
    result = response.get_json()
    assert response.status_code == 500, result
    assert result["dispatch_outcome"] == "unknown_after_dispatch" and result["retry_safe"] is False
    assert "SYNTHETIC-private-context" not in str(result)
    assert hooks == []
    key = contract_key(mode="live", adapter="dhan", account="route-account", symbol="INFY", exchange="NSE", product="MIS")
    assert reserved_exit(key) == 10
    with app.config["SAFETY"].order_admission("dhan:route-account") as lease:
        assert len(lease.reservations) == 1 and lease.reservations[0].broker_order_id == ""
    source.position_rows[0].update(net_qty=20, quantity="20")
    source.order_rows = [{"symbol": "INFY", "exchange": "NSE", "product": "MIS", "action": "SELL",
                          "order_id": "unrelated-exit", "quantity": "2", "filled_qty": "0", "status": "OPEN"}]
    second = _place(app, 10)
    assert second.status_code == 409, second.get_json()
    assert len(wire) == 1 and reserved_exit(key) == 10
    assert hooks == []


@pytest.mark.parametrize("kind", ["rejected", "timeout", "internal", "arbitrary"])
def test_extended_super_error_keeps_typed_broker_properties_and_unknown_origin(super_stack, kind):
    from copy import deepcopy
    from flinttrade_core.exceptions import BrokerInternal, BrokerTimeout, OrderRejectedByBroker

    app, transport, consumed = super_stack
    error = {
        "rejected": OrderRejectedByBroker("Private native summary is not public", broker_id="dhan", broker_code="DH-TEST"),
        "timeout": BrokerTimeout("Private native summary is not public", broker_id="dhan", broker_code="408"),
        "internal": BrokerInternal("Private native summary is not public", broker_id="dhan", broker_code="503"),
        "arbitrary": RuntimeError("Private native summary is not public"),
    }[kind]
    if kind == "rejected":
        error.broker_message = "Synthetic leg was refused; token=synthetic-secret"

    def fail_put(endpoint, payload):
        assert endpoint == "/super/orders/super-fixture"
        transport.calls.append(("PUT", endpoint, deepcopy(payload)))
        raise error

    transport.put = fail_put  # Only the inert transport fault changes, not the SDK/resource/router.
    response = modify_super(app, {"leg_name": "TARGET_LEG", "target_price": "1555"})
    result = response.get_json()
    assert response.status_code == (500 if kind == "arbitrary" else 502), result
    assert result["dispatch_outcome"] == "unknown_after_dispatch" and result["retry_safe"] is False
    assert result["affected_item"] == {"broker": "dhan", "account_id": "route-account", "operation": "modify_super_order",
                                       "order_id": "super-fixture", "leg_name": "TARGET_LEG"}
    assert "Private native summary" not in str(result) and "synthetic-secret" not in str(result)
    if kind == "rejected":
        assert result["broker_code"] == "DH-TEST"
        assert result["broker_message"].startswith("Synthetic leg was refused; token=")
    elif kind == "arbitrary":
        assert "broker_code" not in result and "broker_message" not in result
    else:
        assert result["broker_code"] == ("408" if kind == "timeout" else "503")
    assert consumed == [True]
    assert [call for call in transport.calls if call[0] == "PUT"] == [
        ("PUT", "/super/orders/super-fixture", {"orderId": "super-fixture", "legName": "TARGET_LEG", "targetPrice": 1555.0}),
    ]


def test_known_kotak_credential_value_cannot_escape_through_native_error_code(runtime, backend_lease_factory):
    from flinttrade_core.app import create_flask_app
    from flinttrade_core.auth_routes import _create_token
    from flinttrade_core.exceptions import OrderRejectedByBroker
    from flinttrade_engine.reduce_only import reset_reduce_only_for_tests
    from flinttrade_engine.safety import SafetyConfig, SafetyGate, SafetySystem
    from flinttrade_gateway.brokers.kotakneo_sdk import _install_sdk_log_filter
    from flinttrade_gateway.router import BrokerRouter

    secret = "synthetic-code-credential"
    _install_sdk_log_filter({"access_token": secret})
    adapter, session, facade, requests, _ = runtime({"stat": "Not_Ok", "stCode": secret, "errMsg": "Order is completed"})
    with pytest.raises(OrderRejectedByBroker) as upstream:
        facade.modify_order({"order_id": "OID-1", "order_type": "L", "price": "100", "quantity": "2", "validity": "DAY"})
    assert upstream.value.broker_code == secret  # The installed native facade really supplies this property.
    previous = len(requests)
    reset_reduce_only_for_tests()
    proof = backend_lease_factory()
    app = create_flask_app(safety=SafetySystem(SafetyConfig(check_market_hours=False)),
                           safety_config_ready=True, backend_lease_proof=proof)
    app.config["TESTING"] = True
    router = BrokerRouter({"kotakneo": adapter}, lambda _c, _b, _a: session,
                          consume_gate=SafetyGate().consume, backend_lease_proof=proof)
    app.config["BROKER_ROUTER"] = router
    app.config["NATIVE_ADAPTERS"] = {"kotakneo": _Books()}
    app.config["REGISTRY"] = SimpleNamespace(get_session_for=lambda _b, _a: session)
    try:
        response = app.test_client().post("/api/v1/orders/place", json={
            "broker": "kotakneo", "account_id": "synthetic", "symbol": "INFY", "exchange": "NSE", "product": "MIS",
            "action": "SELL", "quantity": "2", "price": "100", "pricetype": "LIMIT",
        }, headers={"Authorization": "Bearer " + _create_token("operator", mode="live", live_mode_unlocked=True)})
        assert len(requests) - previous == 1
        result = response.get_json()
        assert result["dispatch_outcome"] == "unknown_after_dispatch"
        assert result["broker_message"] == "Order is completed"
        assert secret not in str(result)
    finally:
        router.revoke_and_drain(timeout=0)
        app.config["CLIENT"].close_sync()
        reset_reduce_only_for_tests()



@pytest.mark.parametrize("extra", [
    {"is_tsl": True}, {"tsl_step_size": 5}, {"iceberg_legs": 1.5}, {"icebergLegs": 2},
    {"market_protection": 1}, {"market_protection": True}, {"market_protection_by_index": {"0": 5}},
])
def test_super_unrepresented_neighbours_are_refused_before_kwargs_selection(super_stack, extra):
    app, transport, consumed = super_stack
    response = modify_super(app, {"leg_name": "TARGET_LEG", "target_price": "1555", **extra})
    assert response.status_code == 400, response.get_json()
    assert transport.calls == [] and consumed == []


@pytest.mark.parametrize("changes", [
    {"leg_name": "TARGET_LEG", "targetPrice": "1555"},
    {"leg_name": "STOP_LOSS_LEG", "stopLossPrice": "1455", "trailingJump": "0"},
    {"leg_name": "TARGET_LEG", "target_price": "1555", "is_tsl": False, "tsl_step_size": 0,
     "market_protection": False},
])
def test_super_reviewed_aliases_and_exact_inactive_controls_still_reach_native_put(super_stack, changes):
    app, transport, consumed = super_stack
    response = modify_super(app, changes)
    assert response.status_code == 200, response.get_json()
    assert consumed == [True]
    puts = [call for call in transport.calls if call[0] == "PUT"]
    assert len(puts) == 1
    expected = {"orderId": "super-fixture", "legName": changes["leg_name"]}
    if changes["leg_name"] == "TARGET_LEG":
        expected["targetPrice"] = 1555.0
    else:
        expected.update(stopLossPrice=1455.0, trailingJump=0.0)
    assert puts[0] == ("PUT", "/super/orders/super-fixture", expected)



