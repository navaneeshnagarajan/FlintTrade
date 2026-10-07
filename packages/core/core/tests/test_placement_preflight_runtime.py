"""Pure placement refusal before admission; real factory/gates/router/SDK IO.

Synthetic external books, sessions and exact inert transports only. These
controls establish request correspondence, not account eligibility or fills.
"""
from __future__ import annotations

import json
from copy import deepcopy
from types import SimpleNamespace
from urllib.parse import urlsplit

import pytest

from flinttrade_core.auth_routes import _create_token
from flinttrade_core.exceptions import UnsupportedCapabilityError
from flinttrade_engine.reduce_only import contract_key, reserved_exit
from flinttrade_gateway.brokers._base import Session
from flinttrade_gateway.brokers.dhan import DhanAdapter
from flinttrade_gateway.brokers.groww import GrowwAdapter
from flinttrade_gateway.router import BrokerRouter
from packages.core.core.tests.test_ingress_safety_runtime import (
    DispatchSDK,
    exact_egress_latch as exact_egress_latch,
    route_stack as route_stack,
)

pytestmark = pytest.mark.integration


class _Wire:
    """Exact transport behind the installed Dhan resource or Groww REST adapter."""

    def __init__(self):
        self.calls = []
        self.error = None

    def post(self, endpoint, payload):
        assert endpoint in {"/orders", "/orders/slicing"}
        self.calls.append((endpoint, deepcopy(payload)))
        if self.error is not None:
            raise self.error
        return {"status": "success", "data": {"orderId": "preflight-ack", "orderStatus": "TRANSIT"}}

    def groww(self, method, url, *, headers, params=None, json_body=None):
        assert (method, urlsplit(url).path, params) == ("POST", "/v1/order/create", None)
        self.calls.append(("/v1/order/create", deepcopy(json_body)))
        if self.error is not None:
            raise self.error
        return 200, {"status": "SUCCESS", "payload": {"groww_order_id": "preflight-ack"}}


@pytest.fixture
def preflight_stack(request, route_stack, monkeypatch):
    from flinttrade_core import order_routes
    from flinttrade_engine import safety as safety_module
    from flinttrade_engine.safety import SafetyGate
    from flinttrade_gateway.brokers import dhan_mapping, groww_mapping

    broker = request.param
    app, source, _sdk, old_router = route_stack
    wire = _Wire()
    resolved = []

    def security(symbol, exchange):
        resolved.append((symbol, exchange))
        return "fixture-security"

    adapter = DhanAdapter(client_factory=lambda _s: DispatchSDK(wire), security_resolver=security) if broker == "dhan" else (
        GrowwAdapter(http_factory=lambda: wire.groww)
    )
    session = Session("synthetic", 4102444800.0, "route-account", broker)
    gate = SafetyGate()
    minted, consumed, invoked, builds, reads, checks = [], [], [], [], [], []

    def consume(identifier):
        result = gate.consume(identifier)
        consumed.append(result)
        return result

    def session_for(context, selected, account):
        assert (selected, account) == (broker, "route-account")
        if context is not None:
            assert context.selector == broker + ":route-account"
        return session

    router = BrokerRouter({broker: adapter}, session_for, consume_gate=consume,
                          backend_lease_proof=old_router.backend_lease_proof)
    assert router._lifecycle_store is None
    app.config["BROKER_ROUTER"] = router
    app.config["NATIVE_ADAPTERS"] = {broker: source}
    app.config["REGISTRY"] = SimpleNamespace(get_session_for=lambda b, a: session_for(None, b, a))
    original_mint = safety_module.gate_order

    def mint(order, context, **kwargs):
        result = original_mint(order, context, **kwargs)
        minted.append(order.model_dump(mode="json"))
        return result

    monkeypatch.setattr(safety_module, "gate_order", mint)
    original_invoke = order_routes._LiveWriteProgress.on_adapter_invoke

    def invoke(progress):
        invoked.append(True)
        original_invoke(progress)

    monkeypatch.setattr(order_routes._LiveWriteProgress, "on_adapter_invoke", invoke)
    mapper, name = (dhan_mapping, "to_place_order_kwargs") if broker == "dhan" else (
        groww_mapping, "to_place_order_payload"
    )
    original_build = getattr(mapper, name)

    def build(order, *args, **kwargs):
        builds.append(order.model_dump(mode="json"))
        return original_build(order, *args, **kwargs)

    monkeypatch.setattr(mapper, name, build)
    for name in ("positions", "order_book", "funds", "quotes", "margin_calculator", "holdings", "trade_book"):
        original = getattr(source, name)

        async def read(*args, _name=name, _original=original, **kwargs):
            reads.append(_name)
            return await _original(*args, **kwargs)

        monkeypatch.setattr(source, name, read)
    original_check = app.config["SAFETY"].check_order

    def check(*args, **kwargs):
        result = original_check(*args, **kwargs)
        checks.append([row.passed for row in result])
        return result

    monkeypatch.setattr(app.config["SAFETY"], "check_order", check)
    state = SimpleNamespace(app=app, broker=broker, wire=wire, minted=minted, consumed=consumed,
                            invoked=invoked, builds=builds, reads=reads, checks=checks, resolved=resolved)
    yield state
    router.revoke_and_drain(timeout=0)


def _request(stack, fields, path="/api/v1/orders/place"):
    return stack.app.test_client().post(path, json={
        "broker": stack.broker, "account_id": "route-account", "symbol": "INFY", "exchange": "NSE",
        "product": "MIS", "action": "SELL", "quantity": "2", "price": "100", "pricetype": "LIMIT",
        "variety": "regular", "strategy": "preflight-ref", **fields,
    }, headers={"Authorization": "Bearer " + _create_token("operator", mode="live", live_mode_unlocked=True)})


def _observe(stack, response):
    key = contract_key(mode="live", adapter=stack.broker, account="route-account",
                       symbol="INFY", exchange="NSE", product="MIS")
    with stack.app.config["SAFETY"].order_admission(stack.broker + ":route-account") as lease:
        holds = [{"quantity": row.order.quantity, "broker_order_id": row.broker_order_id} for row in lease.reservations]
    return {"status": response.status_code, "body": response.get_json(), "builds": deepcopy(stack.builds),
            "reads": list(stack.reads), "checks": deepcopy(stack.checks), "minted": deepcopy(stack.minted),
            "consumed": list(stack.consumed), "invoked": list(stack.invoked), "resolved": list(stack.resolved),
            "wire": deepcopy(stack.wire.calls), "reducing_hold": reserved_exit(key), "exposure_holds": holds}


def _assert_refused_before_admission(stack, response, fields):
    from flinttrade_engine.laya import process_laya

    observed = _observe(stack, response)
    print("SAFETY_FINAL_PREFLIGHT_FIRST " + json.dumps({"broker": stack.broker, "fields": fields,
          **observed}, sort_keys=True), flush=True)
    assert response.status_code == 400, observed
    assert all(observed[key] == [] for key in ("reads", "checks", "minted", "consumed", "invoked", "wire", "resolved")), observed
    assert observed["reducing_hold"] == 0 and observed["exposure_holds"] == []
    assert process_laya().decision_log() == ()
    assert not {"dispatch_outcome", "retry_safe"}.intersection(observed["body"])
    assert len(observed["builds"]) == 1
    return observed


@pytest.mark.parametrize("preflight_stack", ["dhan"], indirect=True)
@pytest.mark.parametrize("path", ["/api/v1/orders/place", "/api/v1/orders/dhan/place"])
@pytest.mark.parametrize("fields", [{"trailing_jump": "5"}, {"stop_loss_price": "105"}, {"target_price": "95"}])
def test_dhan_active_ordinary_protection_refuses_before_admission_and_does_not_poison_next_order(preflight_stack, fields, path):
    stack = preflight_stack
    response = _request(stack, fields, path)
    first = _assert_refused_before_admission(stack, response, fields)
    for name, value in fields.items():
        assert first["builds"][0][name] == value
    second = _request(stack, {}, path)
    observed = _observe(stack, second)
    print("SAFETY_FINAL_PREFLIGHT_NEXT " + json.dumps({"broker": "dhan", "first": first, "next": observed}, sort_keys=True), flush=True)
    assert second.status_code == 200, observed
    assert observed["consumed"] == [True] and observed["invoked"] == [True] and len(observed["minted"]) == 1
    assert stack.wire.calls == [("/orders", {
        "afterMarketOrder": False, "boProfitValue": None, "boStopLossValue": None, "disclosedQuantity": 0,
        "exchangeSegment": "NSE_EQ", "orderType": "LIMIT", "price": 100.0, "productType": "INTRADAY",
        "quantity": 2, "securityId": "fixture-security", "transactionType": "SELL", "triggerPrice": 0.0, "validity": "DAY",
    })]


@pytest.mark.parametrize("preflight_stack", ["groww"], indirect=True)
@pytest.mark.parametrize("path", ["/api/v1/orders/place", "/api/v1/orders/groww/place"])
@pytest.mark.parametrize("fields", [{"market_protection": False}, {"market_protection": True}, {"validity": "GTC"}])
def test_groww_existing_pure_refusal_precedes_authority_and_next_valid_order_is_accepted(preflight_stack, fields, path):
    stack = preflight_stack
    response = _request(stack, fields, path)
    first = _assert_refused_before_admission(stack, response, fields)
    for name, value in fields.items():
        assert first["builds"][0][name] == value
    second = _request(stack, {}, path)
    observed = _observe(stack, second)
    print("SAFETY_FINAL_PREFLIGHT_NEXT " + json.dumps({"broker": "groww", "first": first, "next": observed}, sort_keys=True), flush=True)
    assert second.status_code == 200, observed
    assert observed["consumed"] == [True] and observed["invoked"] == [True] and len(observed["minted"]) == 1
    assert stack.wire.calls == [("/v1/order/create", {
        "trading_symbol": "INFY", "quantity": 2, "validity": "DAY", "exchange": "NSE", "segment": "CASH",
        "product": "MIS", "order_type": "LIMIT", "transaction_type": "SELL", "order_reference_id": "preflight-ref", "price": 100.0,
    })]


@pytest.mark.parametrize("preflight_stack", ["dhan", "groww"], indirect=True)
@pytest.mark.parametrize("fields", [{}, {"validity": "IOC"}, {"variety": "amo"},
                                   {"trailing_jump": "0", "stop_loss_price": "0", "target_price": "0"}])
def test_ordinary_inactive_day_ioc_and_amo_controls_remain_ack_only(preflight_stack, fields):
    stack = preflight_stack
    response = _request(stack, fields)
    observed = _observe(stack, response)
    print("SAFETY_FINAL_PREFLIGHT_POSITIVE " + json.dumps({"broker": stack.broker, "fields": fields,
          **observed}, sort_keys=True), flush=True)
    assert response.status_code == 200, observed
    assert len(stack.minted) == 1 and stack.consumed == [True] and stack.invoked == [True] and len(stack.wire.calls) == 1
    assert len(stack.builds) == 2 and stack.reads and stack.checks == [[True] * 5]
    assert observed["reducing_hold"] == 2
    assert observed["exposure_holds"] == [{"quantity": "2", "broker_order_id": "preflight-ack"}]
    assert not {"filled", "closed", "execution_confirmed"}.intersection(observed["body"])
    endpoint, body = stack.wire.calls[0]
    assert body["validity"] == fields.get("validity", "DAY")
    if stack.broker == "groww":
        assert endpoint == "/v1/order/create" and body["order_reference_id"] == "preflight-ref"
    else:
        assert endpoint == "/orders" and body["quantity"] == 2
        assert body["afterMarketOrder"] is (fields.get("variety") == "amo")
        if fields.get("variety") == "amo":
            assert body["amoTime"] == "OPEN"
        else:
            assert body["boProfitValue"] is None and body["boStopLossValue"] is None


@pytest.mark.parametrize("preflight_stack", ["dhan", "groww"], indirect=True)
@pytest.mark.parametrize("fault", ["timeout", "unsupported"])
def test_actual_wire_exception_stays_unknown_with_both_holds_and_no_replacement(preflight_stack, fault):
    stack = preflight_stack
    stack.wire.error = TimeoutError("synthetic accepted request") if fault == "timeout" else (
        UnsupportedCapabilityError("synthetic fault after accepted request", broker_id=stack.broker)
    )
    response = _request(stack, {})
    first = _observe(stack, response)
    second = _request(stack, {})
    print("SAFETY_FINAL_PREFLIGHT_UNKNOWN " + json.dumps({"broker": stack.broker, "fault": fault, "first": first,
          "next_status": second.status_code, "next_body": second.get_json(), "wire": stack.wire.calls}, sort_keys=True), flush=True)
    assert first["status"] == 500 and first["body"]["dispatch_outcome"] == "unknown_after_dispatch"
    assert first["body"]["retry_safe"] is False
    assert first["reducing_hold"] == 2 and first["exposure_holds"] == [{"quantity": "2", "broker_order_id": ""}]
    assert second.status_code == 409 and second.get_json()["code"] == "exit_pending"
    assert len(stack.wire.calls) == 1 and stack.consumed == [True] and stack.invoked == [True]
