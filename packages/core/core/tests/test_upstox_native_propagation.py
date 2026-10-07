"""Native Upstox intent/evidence through the existing factory, gates and router.

Actual installed SDK resources run against an inert call_api transport. Synthetic
books do not establish broker eligibility, effective protection or durability.
"""
from __future__ import annotations

from copy import deepcopy
from importlib.metadata import version
from types import SimpleNamespace
from typing import Any

import pytest
import upstox_client

from flinttrade_core.app import create_flask_app
from flinttrade_core.auth_routes import _create_token
from flinttrade_engine.reduce_only import reset_reduce_only_for_tests
from flinttrade_engine.safety import SafetyConfig, SafetyGate, SafetySystem
from flinttrade_gateway.brokers._base import Session
from flinttrade_gateway.brokers.upstox import UpstoxAdapter, UpstoxClient
from flinttrade_gateway.router import BrokerRouter

pytestmark = pytest.mark.integration


class _Books:
    async def positions(self, _session: Session) -> list[dict[str, Any]]:
        return [{"symbol": "INFY", "exchange": "NSE", "product": "MIS", "quantity": "10"}]

    async def order_book(self, _session: Session) -> list[Any]:
        return []

    async def funds(self, _session: Session) -> dict[str, str]:
        return {"used_margin": "0", "total_balance": "1000000", "opening_risk_capital": "1000000"}

    async def trade_book(self, _session: Session) -> list[Any]:
        return []

    async def holdings(self, _session: Session) -> list[Any]:
        return []

    async def quotes(self, _session: Session, symbols: list[str]) -> list[dict[str, Any]]:
        return [
            {"symbol": name.split(":", 1)[1], "exchange": name.split(":", 1)[0], "ltp": 100,
             "prev_close": 100, "previous_close_trusted": True}
            for name in symbols
        ]

    async def margin_calculator(self, _session: Session, _orders: list[Any]) -> dict[str, str]:
        return {"required_margin": "100"}

    async def forever_orders(self, _session: Session) -> list[dict[str, Any]]:
        return [{"orderid": "GTT-SYNTHETIC", "status": "SCHEDULED", "quantity": "2", "symbol": "INFY",
                 "exchange": "NSE", "action": "SELL", "product": "MIS", "pricetype": "LIMIT",
                 "price": "100", "trigger_price": "100", "filled_quantity": "0"}]


@pytest.fixture
def native_stack(backend_lease_factory, monkeypatch):
    assert version("upstox-python-sdk") == "2.30.0"
    reset_reduce_only_for_tests()
    safety = SafetySystem(SafetyConfig(check_market_hours=False))
    proof = backend_lease_factory()
    app = create_flask_app(safety=safety, safety_config_ready=True, backend_lease_proof=proof)
    app.config["TESTING"] = True
    facade = UpstoxClient("synthetic-not-a-broker-token")
    assert isinstance(facade._order, upstox_client.OrderApi)
    assert isinstance(facade._order_v3, upstox_client.OrderApiV3)
    wire: list[dict[str, Any]] = []
    native_ack = {"status": "success", "data": {"order_ids": ["SLICE-1", "SLICE-2"]},
                  "metadata": {"latency": 12, "native_items": [{"order_id": "SLICE-2", "message": "accepted"}]}}

    def transport(resource_path, method, *args, **kwargs):
        wire.append({"path": resource_path, "method": method,
                     "body": facade._order_v3.api_client.sanitize_for_serialization(kwargs.get("body"))})
        response = deepcopy(native_ack)
        return SimpleNamespace(to_dict=lambda: response)

    monkeypatch.setattr(facade._order.api_client, "call_api", transport)
    adapter = UpstoxAdapter(client_factory=lambda _session: facade, instrument_resolver=lambda _s, _e: "NSE_EQ|SYNTHETIC")
    session = Session("synthetic-not-a-broker-token", 4102444800.0, "native-account", "upstox")
    gate = SafetyGate()

    def session_for(ctx, broker, account):
        from flinttrade_core.exceptions import SafetyBypassError
        if (broker, account) != ("upstox", "native-account") or ctx is not None and ctx.actor_id != "operator":
            raise SafetyBypassError("synthetic ACL refused")
        return session

    audit_events: list[dict[str, Any]] = []
    app.config["AUDIT"] = SimpleNamespace(log_event=lambda event, **fields: audit_events.append({"event": event, **deepcopy(fields)}))
    router = BrokerRouter({"upstox": adapter}, session_for, consume_gate=gate.consume, backend_lease_proof=proof)
    app.config["BROKER_ROUTER"] = router
    app.config["NATIVE_ADAPTERS"] = {"upstox": _Books()}
    app.config["REGISTRY"] = SimpleNamespace(get_session_for=lambda b, a: session_for(None, b, a))
    yield SimpleNamespace(app=app, router=router, adapter=adapter, facade=facade, wire=wire,
                          audit=audit_events, ack=native_ack, session=session, gate=gate, proof=proof)
    router.revoke_and_drain(timeout=0)
    reset_reduce_only_for_tests()


def _headers(**claims):
    return {"Authorization": f"Bearer {_create_token('operator', mode='live', live_mode_unlocked=True, **claims)}"}


def _place(stack, **fields):
    return stack.app.test_client().post("/api/v1/orders/place", headers=_headers(), json={
        "broker": "upstox", "account_id": "native-account", "symbol": "INFY", "exchange": "NSE",
        "product": "MIS", "action": "SELL", "quantity": "2", "price": "100", "pricetype": "LIMIT",
        "variety": "iceberg", **fields,
    })


def test_sliced_http_and_audit_preserve_all_ids_and_detached_native_ack(native_stack):
    stack = native_stack
    response = _place(stack)
    assert response.status_code == 200, response.get_json()
    body = response.get_json()
    assert body["orderid"] == body["data"] == "SLICE-1"
    assert body["order_ids"] == ["SLICE-1", "SLICE-2"]
    assert body["broker_response"] == stack.ack
    assert "gtt_order_ids" not in body
    assert stack.wire == [{"path": "/v3/order/place", "method": "POST", "body": {
        "quantity": 2, "product": "I", "validity": "DAY", "price": 100.0, "tag": "",
        "instrument_token": "NSE_EQ|SYNTHETIC", "order_type": "LIMIT", "transaction_type": "SELL",
        "disclosed_quantity": 0, "trigger_price": 0.0, "is_amo": False, "slice": True,
    }}]
    placement = next(event for event in stack.audit if event["event"] == "ORDER_PLACED")
    assert placement["order_ids"] == body["order_ids"]
    assert placement["broker_response"] == body["broker_response"]
    stack.ack["data"]["order_ids"].append("LATER-MUTATION")
    assert body["order_ids"] == placement["order_ids"] == ["SLICE-1", "SLICE-2"]
    assert placement["broker_response"]["data"]["order_ids"] == ["SLICE-1", "SLICE-2"]
    assert not any(key in body for key in ("filled_quantity", "closed", "execution_confirmed"))


@pytest.mark.parametrize("value", [0, 1, -1, 25, 0.0, 1.0, "0", "1", "true"])
def test_canonical_market_protection_is_boolean_not_native_percentage(value):
    from pydantic import ValidationError
    from flinttrade_core.models import Order

    with pytest.raises(ValidationError):
        Order(symbol="INFY", action="SELL", market_protection=value)
    assert Order(symbol="INFY", action="SELL", market_protection=True).market_protection is True
    assert Order(symbol="INFY", action="SELL", market_protection=False).market_protection is False


@pytest.mark.parametrize("fields", [
    {"market_protection": True}, {"market_protection": False}, {"market_protection": 0},
    {"market_protection": 1}, {"market_protection": -1}, {"market_protection": 25},
    {"market_protection_by_strategy": {"ENTRY": 1}}, {"market_protection_by_index": {"0": 1}},
    {"rules": [{"strategy": "ENTRY", "market_protection": 25}]},
    {"slice": False}, {"is_amo": True}, {"transaction_type": "BUY"},
    {"target_price": "110"}, {"stop_loss_price": "90"}, {"stop_loss_trailing_gap": "0.5"},
    {"entry_trigger_type": "ABOVE"}, {"trailing_jump": "0.5"}, {"iceberg_legs": "2"},
    {"price1": "110"}, {"quantity1": "2"},
])
def test_unrepresented_place_intent_is_refused_before_gate_or_transport(native_stack, monkeypatch, fields):
    import flinttrade_engine.safety as safety_module

    minted = []
    real_gate = safety_module.gate_order

    def spy(*args, **kwargs):
        minted.append(deepcopy(args[0]))
        return real_gate(*args, **kwargs)

    monkeypatch.setattr(safety_module, "gate_order", spy)
    response = _place(native_stack, **fields)
    assert 400 <= response.status_code < 500 or response.status_code == 501, response.get_json()
    assert minted == []
    assert native_stack.wire == []


def _replacement(**fields):
    return {"type": "MULTIPLE", "quantity": 2, "trigger_price": 100, "entry_trigger_type": "ABOVE",
            "stop_loss_price": 90, "stop_loss_trailing_gap": 0.5, "target_price": 110,
            "stop_loss_trigger_type": "IMMEDIATE", "target_trigger_type": "IMMEDIATE", **fields}


def _modify(stack, changes):
    return stack.app.test_client().put("/api/v1/orders/forever/GTT-SYNTHETIC", headers=_headers(), json={
        "broker": "upstox", "account_id": "native-account", "changes": changes,
    })


@pytest.mark.parametrize("fields", [
    {"market_protection_by_strategy": {"STOPLOSS": True}},
    {"market_protection_by_strategy": {"TARGET": 1.5}},
    {"market_protection_by_strategy": {"UNKNOWN": 1}},
    {"stop_loss_price": 0, "market_protection_by_strategy": {"STOPLOSS": 1}},
    {"market_protection_by_strategy": []}, {"market_protection": True},
    {"rules": [{"strategy": "ENTRY", "market_protection": 1}]},
    {"market_protection_by_index": {"0": 1}}, {"gtt_order_id": "GTT-OTHER"},
    {"quantity": 2.5}, {"target_price": "NaN"}, {"stop_loss_trailing_gap": -1},
    {"price": 95}, {"pricetype": "MARKET"}, {"order_type": "LIMIT"},
    {"disclosed_quantity": 1}, {"validity": "IOC"}, {"strategy": "changed-tag"},
])
def test_invalid_or_unsigned_rule_intent_is_refused_before_mint(native_stack, monkeypatch, fields):
    import flinttrade_engine.safety as safety_module

    minted = []
    real_gate = safety_module.gate_broker_write

    def spy(*args, **kwargs):
        minted.append(deepcopy(args[1]))
        return real_gate(*args, **kwargs)

    monkeypatch.setattr(safety_module, "gate_broker_write", spy)
    response = _modify(native_stack, _replacement(**fields))
    assert response.status_code == 400, response.get_json()
    assert minted == []
    assert native_stack.wire == []


@pytest.mark.parametrize("percentage", [-1, 0, 1, 25])
def test_existing_gtt_modify_route_signs_exact_per_strategy_intent_and_real_sdk_body(
    native_stack, monkeypatch, percentage,
):
    stack = native_stack
    captured = []
    execute = stack.router.execute_gated

    async def spy(ctx, **kwargs):
        captured.append((ctx, deepcopy(kwargs)))
        return await execute(ctx, **kwargs)

    monkeypatch.setattr(stack.router, "execute_gated", spy)
    changes = _replacement(market_protection_by_strategy={"ENTRY": percentage, "STOPLOSS": 25})
    response = _modify(stack, changes)
    assert response.status_code == 200, response.get_json()
    assert len(captured) == len(stack.wire) == 1
    ctx, dispatch = captured[0]
    assert dispatch["payload"] == {"_op": "modify_forever", "order_id": "GTT-SYNTHETIC", "changes": changes}
    assert dispatch["safety_ctx"].verify(dispatch["payload"], ctx, "upstox", "native-account")
    wire = stack.wire[0]
    assert (wire["path"], wire["method"]) == ("/v3/order/gtt/modify", "PUT")
    assert wire["body"] == {"type": "MULTIPLE", "quantity": 2, "gtt_order_id": "GTT-SYNTHETIC", "rules": [
        {"strategy": "ENTRY", "trigger_type": "ABOVE", "trigger_price": 100.0, "market_protection": percentage},
        {"strategy": "STOPLOSS", "trigger_type": "IMMEDIATE", "trigger_price": 90.0,
         "trailing_gap": 0.5, "market_protection": 25},
        {"strategy": "TARGET", "trigger_type": "IMMEDIATE", "trigger_price": 110.0},
    ]}
    assert "market_protection" not in wire["body"]
    assert not any(key in response.get_json() for key in ("filled_quantity", "protection_active", "closed"))


def test_gtt_modify_absence_omits_native_percentages(native_stack):
    response = _modify(native_stack, _replacement())
    assert response.status_code == 200, response.get_json()
    assert all("market_protection" not in rule for rule in native_stack.wire[0]["body"]["rules"])


@pytest.mark.parametrize("tamper", ["percentage", "alias", "account", "incarnation", "generation", "read-only"])
def test_route_minted_native_intent_cannot_be_tampered_or_retargeted(native_stack, monkeypatch, tamper):
    from dataclasses import replace
    from flinttrade_gateway.routing_config import RoutingHint

    stack = native_stack
    execute = stack.router.execute_gated

    async def intercept(ctx, **kwargs):
        if tamper == "percentage":
            kwargs["payload"]["changes"]["market_protection_by_strategy"]["STOPLOSS"] = 0
        elif tamper == "alias":
            kwargs["payload"]["changes"]["rules"] = [{"strategy": "STOPLOSS", "market_protection": 0}]
        elif tamper == "account":
            kwargs["hint"] = RoutingHint(adapter_id="upstox", account_id="other-account")
        elif tamper == "incarnation":
            kwargs["safety_ctx"] = replace(kwargs["safety_ctx"], backend_incarnation="unowned-incarnation")
        elif tamper == "generation":
            stack.router.revoke_and_drain(timeout=0)
        elif tamper == "read-only":
            stack.session.read_only_until_at = 4102444800.0
        return await execute(ctx, **kwargs)

    monkeypatch.setattr(stack.router, "execute_gated", intercept)
    response = _modify(stack, _replacement(market_protection_by_strategy={"STOPLOSS": 25}))
    assert response.status_code == 403, response.get_json()
    assert stack.wire == []


def test_successful_native_modification_ticket_is_one_shot(native_stack, monkeypatch):
    import asyncio
    from flinttrade_core.exceptions import SafetyBypassError

    stack = native_stack
    captured = []
    execute = stack.router.execute_gated

    async def spy(ctx, **kwargs):
        captured.append((ctx, deepcopy(kwargs)))
        return await execute(ctx, **kwargs)

    monkeypatch.setattr(stack.router, "execute_gated", spy)
    response = _modify(stack, _replacement(market_protection_by_strategy={"TARGET": 1}))
    assert response.status_code == 200, response.get_json()
    ctx, fields = captured[0]
    with pytest.raises(SafetyBypassError, match="already consumed"):
        asyncio.run(execute(ctx, **fields))
    assert len(stack.wire) == 1


@pytest.mark.parametrize("variety,id_field,ids", [
    ("iceberg", "order_ids", ["SLICE-1", "SLICE-2"]),
    ("gtt", "gtt_order_ids", ["GTT-RESOURCE-1", "GTT-RESOURCE-2"]),
])
def test_existing_router_attempt_transport_retains_resource_kind_and_all_ack_evidence(native_stack, variety, id_field, ids):
    import asyncio
    import json
    from flinttrade_core.models import Order
    from flinttrade_engine.request_context import RequestContext
    from flinttrade_engine.safety import gate_order

    stack = native_stack
    stack.ack["data"] = {id_field: ids}
    observed = []
    sink = SimpleNamespace(
        assert_write_ready=lambda: None,
        prepare_dispatch=lambda **_fields: "synthetic-attempt",
        mark_invoked=lambda attempt: observed.append(("invoked", attempt)),
        acknowledge=lambda attempt, ack: observed.append(("ack", attempt, json.loads(json.dumps(ack)))),
    )
    router = BrokerRouter(
        {"upstox": stack.adapter}, lambda _ctx, _b, _a: stack.session,
        consume_gate=stack.gate.consume, backend_lease_proof=stack.proof, lifecycle_store=sink,
    )
    order = Order(symbol="INFY", action="SELL", quantity="2", variety=variety, trigger_price="100")
    ctx = RequestContext(jti="synthetic-attempt-caller", actor_type="human", actor_id="operator",
                         mode="live", selector="upstox:native-account")
    ticket = gate_order(order, ctx, adapter_id="upstox", account_id="native-account", backend_lease_proof=stack.proof)
    result = asyncio.run(router.place_order(ctx, order=order, safety_ctx=ticket, adapter_id="upstox", account_id="native-account"))
    assert result == ids[0]
    assert result.order_ids == tuple(ids)
    assert observed[0] == ("invoked", "synthetic-attempt")
    acknowledgement = observed[1][2]
    assert acknowledgement == {"orderid": ids[0], id_field: ids, "broker_response": stack.ack}
    assert ("order_ids" if variety == "gtt" else "gtt_order_ids") not in acknowledgement
    stack.ack["data"][id_field].append("LATER-MUTATION")
    assert len(acknowledgement[id_field]) == 2
    assert not any(key in acknowledgement for key in ("filled_quantity", "closed", "durable"))
    router.revoke_and_drain(timeout=0)


@pytest.mark.parametrize("native_fields", [
    {"market_protection_by_strategy": {"ENTRY": 1}}, {"market_protection_by_index": {0: 1}},
    {"rules": [{"strategy": "ENTRY", "market_protection": 1}]},
])
def test_canonical_order_cannot_silently_ignore_unrepresented_native_intent(native_fields):
    from pydantic import ValidationError
    from flinttrade_core.models import Order

    with pytest.raises(ValidationError):
        Order(symbol="INFY", action="SELL", **native_fields)


@pytest.mark.parametrize("fields", [
    {"market_protection": True}, {"market_protection": 0}, {"market_protection_by_strategy": {"ENTRY": 1}},
    {"rules": [{"strategy": "ENTRY", "market_protection": 1}]}, {"market_protection_by_index": {"0": 1}},
    {"variety": "gtt"}, {"validity": "GTC"}, {"disclosed_quantity": "0.5"},
    {"target_price": "110"}, {"stop_loss_price": "90"}, {"stop_loss_trailing_gap": "0.5"},
])
def test_ordinary_modify_cannot_drop_native_intent_or_sign_invalid_request(native_stack, monkeypatch, fields):
    import flinttrade_engine.safety as safety_module

    async def book(_session):
        return [{"orderid": "REGULAR-1", "status": "OPEN", "symbol": "INFY", "exchange": "NSE", "product": "MIS",
                 "action": "SELL", "quantity": "2", "filled_quantity": "0", "price": "100", "pricetype": "LIMIT",
                 "trigger_price": "0", "disclosed_quantity": "0", "validity": "DAY"}]

    native_stack.app.config["NATIVE_ADAPTERS"]["upstox"].order_book = book
    minted = []
    gate = safety_module.gate_order

    def spy(*args, **kwargs):
        minted.append(deepcopy(args[0]))
        return gate(*args, **kwargs)

    monkeypatch.setattr(safety_module, "gate_order", spy)
    response = native_stack.app.test_client().post("/api/v1/orders/upstox/modify", headers=_headers(), json={
        "account_id": "native-account", "orderid": "REGULAR-1", "symbol": "INFY", "exchange": "NSE",
        "product": "MIS", "action": "SELL", "quantity": "2", "price": "100", "pricetype": "LIMIT", **fields,
    })
    assert response.status_code in {400, 501}, response.get_json()
    assert minted == []
    assert native_stack.wire == []


@pytest.mark.parametrize("variety", ["regular", "amo"])
def test_regular_and_amo_keep_v2_and_preserve_native_ack_additively(native_stack, variety):
    stack = native_stack
    stack.ack["data"] = {"order_id": "REGULAR-1"}
    response = _place(stack, variety=variety, validity="IOC")
    assert response.status_code == 200, response.get_json()
    body = response.get_json()
    assert body["orderid"] == body["data"] == "REGULAR-1"
    assert body["order_ids"] == ["REGULAR-1"]
    assert body["broker_response"] == stack.ack
    assert len(stack.wire) == 1
    assert stack.wire[0]["path"] == "/v2/order/place"
    assert stack.wire[0]["body"]["is_amo"] is (variety == "amo")
    assert stack.wire[0]["body"]["validity"] == "IOC"
    assert "slice" not in stack.wire[0]["body"]
    assert "market_protection" not in stack.wire[0]["body"]


def test_real_audit_json_transport_preserves_all_placement_evidence(native_stack, tmp_path):
    from datetime import datetime
    from flinttrade_data.audit_logger import AuditLogger, IST

    stack = native_stack
    with AuditLogger(str(tmp_path / "synthetic-audit")) as audit:
        stack.app.config["AUDIT"] = audit
        response = _place(stack)
        assert response.status_code == 200, response.get_json()
        rows = audit.read_day(datetime.now(IST).date().isoformat())
        assert len(rows) == 1
        assert rows[0]["event_type"] == "ORDER_PLACED"
        assert rows[0]["order_ids"] == ["SLICE-1", "SLICE-2"]
        assert rows[0]["broker_response"] == response.get_json()["broker_response"] == stack.ack
        stack.ack["data"]["order_ids"].append("LATER-MUTATION")
        assert audit.read_day(datetime.now(IST).date().isoformat())[0]["order_ids"] == ["SLICE-1", "SLICE-2"]
        assert not any(key in rows[0] for key in ("filled_quantity", "closed", "execution_confirmed"))


def test_audit_failure_does_not_turn_native_ack_into_a_replay(native_stack):
    def fail(_event, **_fields):
        raise OSError("synthetic audit unavailable")

    native_stack.app.config["AUDIT"] = SimpleNamespace(log_event=fail)
    response = _place(native_stack)
    assert response.status_code == 200, response.get_json()
    assert response.get_json()["order_ids"] == ["SLICE-1", "SLICE-2"]
    assert len(native_stack.wire) == 1


def test_native_creation_and_read_freezes_are_unchanged(native_stack, monkeypatch):
    import flinttrade_engine.safety as safety_module

    minted = []
    for name in ("gate_order", "gate_broker_write"):
        real_gate = getattr(safety_module, name)

        def spy(*args, _gate=real_gate, **kwargs):
            minted.append(args)
            return _gate(*args, **kwargs)

        monkeypatch.setattr(safety_module, name, spy)
    assert _place(native_stack, variety="gtt", market_protection_by_strategy={"ENTRY": 1}).status_code == 422
    client = native_stack.app.test_client()
    body = {"broker": "upstox", "account_id": "native-account", "symbol": "INFY", "exchange": "NSE",
            "action": "SELL", "quantity": "2", "trigger_price": "100"}
    assert client.post("/api/v1/orders/forever", json=body, headers=_headers()).status_code == 501
    assert client.post("/api/v1/orders/multi", json={"orders": [body]}, headers=_headers()).status_code == 501
    assert client.get("/api/v1/orders/forever?broker=upstox&account_id=native-account", headers=_headers()).status_code == 409
    assert minted == []
    assert native_stack.wire == []


@pytest.mark.parametrize("variety", ["iceberg", "regular"])
def test_actual_sdk_response_models_survive_factory_http_and_audit(native_stack, monkeypatch, variety):
    stack = native_stack
    if variety == "iceberg":
        native = upstox_client.PlaceOrderV3Response(
            status="success", data=upstox_client.MultiOrderV3Data(order_ids=["TYPED-1", "TYPED-2"]),
            metadata=upstox_client.OrderMetadata(latency=12),
        )
        expected = {"status": "success", "data": {"order_ids": ["TYPED-1", "TYPED-2"]}, "metadata": {"latency": 12}}
        ids = ["TYPED-1", "TYPED-2"]
    else:
        native = upstox_client.PlaceOrderResponse(status="success", data=upstox_client.PlaceOrderData(order_id="TYPED-1"))
        expected = {"status": "success", "data": {"order_id": "TYPED-1"}}
        ids = ["TYPED-1"]
    calls = []

    def transport(path, method, *args, **kwargs):
        calls.append((path, method))
        return native

    monkeypatch.setattr(stack.facade._order.api_client, "call_api", transport)
    response = _place(stack, variety=variety)
    assert response.status_code == 200, response.get_json()
    assert response.get_json()["orderid"] == "TYPED-1"
    assert response.get_json()["order_ids"] == ids
    assert response.get_json()["broker_response"] == expected
    event = next(item for item in stack.audit if item["event"] == "ORDER_PLACED")
    assert event["order_ids"] == ids
    assert event["broker_response"] == expected
    assert calls == [("/v3/order/place" if variety == "iceberg" else "/v2/order/place", "POST")]


@pytest.mark.parametrize("zero", [0, "0.0"])
def test_inactive_optional_controls_do_not_invent_native_rules(native_stack, zero):
    response = _place(native_stack, **dict.fromkeys(
        ("target_price", "stop_loss_price", "stop_loss_trailing_gap", "trailing_jump", "iceberg_legs"), zero,
    ))
    assert response.status_code == 200, response.get_json()
    assert len(native_stack.wire) == 1
    assert "rules" not in native_stack.wire[0]["body"]
    assert "market_protection" not in native_stack.wire[0]["body"]


def test_ordinary_modify_still_executes_exact_v2_resource_contract(native_stack):
    async def book(_session):
        return [{"orderid": "REGULAR-1", "status": "OPEN", "symbol": "INFY", "exchange": "NSE", "product": "MIS",
                 "action": "SELL", "quantity": "2", "filled_quantity": "0", "price": "100", "pricetype": "LIMIT",
                 "trigger_price": "0", "disclosed_quantity": "0", "validity": "DAY"}]

    native_stack.app.config["NATIVE_ADAPTERS"]["upstox"].order_book = book
    response = native_stack.app.test_client().post("/api/v1/orders/upstox/modify", headers=_headers(), json={
        "account_id": "native-account", "orderid": "REGULAR-1", "symbol": "INFY", "exchange": "NSE",
        "product": "MIS", "action": "SELL", "quantity": "2", "price": "100", "pricetype": "LIMIT",
    })
    assert response.status_code == 200, response.get_json()
    assert native_stack.wire == [{"path": "/v2/order/modify", "method": "PUT", "body": {
        "order_id": "REGULAR-1", "order_type": "LIMIT", "quantity": 2, "price": 100.0, "trigger_price": 0.0,
        "disclosed_quantity": 0, "validity": "DAY",
    }}]


def test_zero_dhan_second_leg_still_hits_existing_safety_refusal(native_stack):
    response = _place(native_stack, quantity1="0")
    assert response.status_code == 403, response.get_json()
    assert "Second-leg quantity must be positive" in response.get_json()["message"]
    assert native_stack.wire == []
