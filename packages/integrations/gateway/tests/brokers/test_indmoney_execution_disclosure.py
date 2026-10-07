"""INDstocks per-call outcome disclosure through the actual gate and router."""
from __future__ import annotations

import pytest

from flinttrade_core.models import Order
from flinttrade_engine.request_context import RequestContext
from flinttrade_engine.safety import SafetyBypassError, SafetyGate, gate_order, set_safety_gate_secret
from flinttrade_gateway.brokers import indmoney_mapping as mapping
from flinttrade_gateway.brokers._base import Session
from flinttrade_gateway.brokers.indmoney import IndMoneyAdapter
from flinttrade_gateway.router import BrokerRouter

pytestmark = pytest.mark.unit


class ExactTransport:
    def __init__(self):
        self.calls = []
        self.response = {"status": "success", "data": {"order_id": "EQ-OFFLINE", "order_status": "INITIATED"}}
        self.path = "/order"
        self.read_response = None
        self.reads = []

    def __call__(self, method, url, *, headers, params=None, json_body=None):
        if method == "GET":
            assert url == "https://api.indstocks.com/order-book" and params is None and json_body is None
            assert self.read_response is not None
            self.reads.append(url)
            return 200, self.read_response
        assert method == "POST" and url == f"https://api.indstocks.com{self.path}"
        assert params is None
        assert headers == {"Authorization": "SYNTHETIC", "Content-Type": "application/json"}
        self.calls.append(json_body)
        return 200, self.response


def runtime(backend_lease_factory):
    set_safety_gate_secret(b"0123456789abcdef0123456789abcdef")
    transport = ExactTransport()
    adapter = IndMoneyAdapter(http_factory=lambda: transport, security_resolver=lambda symbol, exchange: "123")
    session = Session(access_token="SYNTHETIC", expires_at=4_102_444_800, account_id="OFFLINE", adapter_id="indmoney")
    proof = backend_lease_factory()
    gate = SafetyGate()
    router = BrokerRouter({"indmoney": adapter}, lambda ctx, aid, account: session,
                          consume_gate=gate.consume, backend_lease_proof=proof)
    ctx = RequestContext(jti="offline-disclosure", actor_type="human", actor_id="offline-human", mode="live")
    return adapter, router, proof, ctx, transport


async def place(router, proof, ctx, order):
    safety = gate_order(order, ctx, "indmoney", account_id="OFFLINE", backend_lease_proof=proof)
    return await router.place_order(ctx, order=order, safety_ctx=safety, adapter_id="indmoney", account_id="OFFLINE")


@pytest.mark.asyncio
async def test_market_ack_keeps_requested_effective_metadata_on_the_actual_return_value(backend_lease_factory):
    adapter, router, proof, ctx, transport = runtime(backend_lease_factory)
    result = await place(router, proof, ctx, Order(
        symbol="SYNTHETIC", action="BUY", exchange="NSE", product="CNC", pricetype="MARKET", quantity="5",
    ))
    assert result == "EQ-OFFLINE"  # Preserve the BrokerAdapter scalar ID contract.
    assert result.execution_effects == {
        "requested_type": "MARKET", "effective_type": "LIMIT", "effective_limit_price": None,
        "trailing_active": False, "limitations": ["MARKET_TO_LIMIT"],
    }
    assert result.broker_response == {"order_id": "EQ-OFFLINE", "order_status": "INITIATED"}
    assert result.order_ids == ("EQ-OFFLINE",)
    assert result.evidence_fields() == {
        "order_ids": ["EQ-OFFLINE"], "child_order_id": None,
        "broker_response": {"order_id": "EQ-OFFLINE", "order_status": "INITIATED"},
        "execution_effects": {
            "requested_type": "MARKET", "effective_type": "LIMIT", "effective_limit_price": None,
            "trailing_active": False, "limitations": ["MARKET_TO_LIMIT"],
        },
    }
    assert adapter.last_execution_effects == result.execution_effects
    assert transport.calls == [{
        "txn_type": "BUY", "exchange": "NSE", "segment": "EQUITY", "product": "CNC", "qty": 5,
        "order_type": "MARKET", "validity": "DAY", "security_id": "123", "is_amo": False, "algo_id": "99999",
    }]


@pytest.mark.asyncio
async def test_smart_ack_carries_trigger_effects_and_child_resource_without_claiming_protection(backend_lease_factory):
    _, router, proof, ctx, transport = runtime(backend_lease_factory)
    transport.path = "/smart/order"
    transport.response = {"status": "success", "data": {"order_data": [{
        "order_id": "EQ-PARENT", "order_status": "INITIATED",
        "child_order_details": {"order_id": "GTT-CHILD", "order_status": "CREATED"},
    }]}}
    result = await place(router, proof, ctx, Order(
        symbol="SYNTHETIC", action="BUY", exchange="NSE", product="CNC", pricetype="MARKET",
        quantity="5", variety="trigger", trigger_price="101",
    ))
    assert result == "EQ-PARENT"
    assert result.execution_effects == {
        "requested_type": "TRIGGER", "effective_type": "TRIGGER_LIMIT", "effective_limit_price": 101,
        "trailing_active": False, "limitations": [],
    }
    assert result.order_ids == ("EQ-PARENT",)
    assert result.child_order_id == "GTT-CHILD"
    assert result.broker_response == {"order_data": [{
        "order_id": "EQ-PARENT", "order_status": "INITIATED",
        "child_order_details": {"order_id": "GTT-CHILD", "order_status": "CREATED"},
    }]}
    assert transport.calls == [{
        "txn_type": "BUY", "exchange": "NSE", "segment": "EQUITY", "product": "CNC", "qty": 5,
        "validity": "DAY", "security_id": "123", "algo_id": "99999", "order_type": "TRIGGER", "trigger_price": 101,
    }]


@pytest.mark.asyncio
async def test_per_call_disclosure_is_detached_from_later_orders_and_mutable_last_result_fields(backend_lease_factory):
    adapter, router, proof, ctx, transport = runtime(backend_lease_factory)
    first = await place(router, proof, ctx, Order(symbol="SYNTHETIC", action="BUY", product="CNC"))
    transport.response["data"]["order_id"] = "EQ-SECOND"
    second = await place(router, proof, ctx, Order(
        symbol="SYNTHETIC", action="BUY", product="CNC", pricetype="LIMIT", price="73.55", variety="amo",
    ))
    assert first == "EQ-OFFLINE" and second == "EQ-SECOND"
    assert first.broker_response["order_id"] == "EQ-OFFLINE"
    assert first.execution_effects["requested_type"] == "MARKET"
    assert first.execution_effects["effective_limit_price"] is None
    assert second.execution_effects == {
        "requested_type": "LIMIT", "effective_type": "LIMIT", "effective_limit_price": 73.55,
        "trailing_active": False, "limitations": [],
    }
    assert transport.calls[1] == {
        "txn_type": "BUY", "exchange": "NSE", "segment": "EQUITY", "product": "CNC", "qty": 1,
        "order_type": "LIMIT", "validity": "DAY", "security_id": "123", "is_amo": True,
        "algo_id": "99999", "limit_price": 73.55,
    }
    adapter.last_execution_effects["effective_limit_price"] = 999
    assert second.execution_effects["effective_limit_price"] == 73.55
    assert first.execution_effects["effective_limit_price"] is None


@pytest.mark.asyncio
@pytest.mark.parametrize("variety", ["regular", "trigger", "gtt"])
async def test_signed_active_trailing_is_explicitly_refused_before_transport_and_cannot_be_replayed(
    backend_lease_factory, variety,
):
    _, router, proof, ctx, transport = runtime(backend_lease_factory)
    order = Order(symbol="SYNTHETIC", action="BUY", product="CNC", variety=variety,
                  trailing_jump="1", trigger_price="101")
    safety = gate_order(order, ctx, "indmoney", account_id="OFFLINE", backend_lease_proof=proof)
    with pytest.raises(mapping.IndMoneyMappingError, match="TSL_IGNORED: active trailing is unsupported"):
        await router.place_order(ctx, order=order, safety_ctx=safety, adapter_id="indmoney", account_id="OFFLINE")
    with pytest.raises(SafetyBypassError):
        await router.place_order(ctx, order=order, safety_ctx=safety, adapter_id="indmoney", account_id="OFFLINE")
    assert transport.calls == []


@pytest.mark.asyncio
async def test_ack_metadata_preserves_one_shot_refusal_after_an_actual_transport_invocation(backend_lease_factory):
    _, router, proof, ctx, transport = runtime(backend_lease_factory)
    order = Order(symbol="SYNTHETIC", action="BUY", product="CNC")
    safety = gate_order(order, ctx, "indmoney", account_id="OFFLINE", backend_lease_proof=proof)
    result = await router.place_order(ctx, order=order, safety_ctx=safety, adapter_id="indmoney", account_id="OFFLINE")
    assert result.execution_effects["effective_limit_price"] is None
    with pytest.raises(SafetyBypassError):
        await router.place_order(ctx, order=order, safety_ctx=safety, adapter_id="indmoney", account_id="OFFLINE")
    assert len(transport.calls) == 1


@pytest.mark.asyncio
async def test_execution_disclosure_does_not_weaken_signed_account_or_intent_guards(backend_lease_factory):
    adapter, router, proof, ctx, transport = runtime(backend_lease_factory)
    order = Order(symbol="SYNTHETIC", action="BUY", product="CNC")
    safety = gate_order(order, ctx, "indmoney", account_id="OFFLINE", backend_lease_proof=proof)
    with pytest.raises(SafetyBypassError):
        await router.place_order(ctx, order=order.model_copy(update={"trailing_jump": "1"}), safety_ctx=safety,
                                 adapter_id="indmoney", account_id="OFFLINE")
    other = gate_order(order, ctx, "indmoney", account_id="OFFLINE", backend_lease_proof=proof)
    with pytest.raises(SafetyBypassError):
        await router.place_order(ctx, order=order, safety_ctx=other, adapter_id="indmoney", account_id="OTHER")
    session = Session(access_token="SYNTHETIC", expires_at=4_102_444_800, account_id="OFFLINE", adapter_id="indmoney")
    with pytest.raises(SafetyBypassError):
        await adapter.place_order(session, order)
    assert transport.calls == []


@pytest.mark.asyncio
async def test_native_read_preserves_reported_order_and_trade_prices_without_rewriting_unknown_execution_effects(
    backend_lease_factory,
):
    adapter, router, proof, ctx, transport = runtime(backend_lease_factory)
    result = await place(router, proof, ctx, Order(symbol="SYNTHETIC", action="BUY", product="CNC", quantity="5"))
    transport.read_response = {"status": "success", "data": [{
        "id": "EQ-OFFLINE", "name": "SYNTHETIC", "exchange": "NSE", "segment": "EQUITY",
        "product": "CNC", "txn_type": "BUY", "order_type": "LIMIT", "status": "PARTIALLY FILLED - CANCELLED",
        "requested_qty": "5", "traded_qty": "2", "requested_price": "74.56", "traded_price": "74.51",
    }]}
    session = Session(access_token="SYNTHETIC", expires_at=4_102_444_800, account_id="OFFLINE", adapter_id="indmoney")
    observed = (await adapter.order_book(session))[0]
    assert observed["pricetype"] == "LIMIT" and observed["price"] == "74.56"
    assert observed["average_price"] == "74.51" and observed["filled_quantity"] == "2"
    assert observed["status"] == "PARTIALLY FILLED - CANCELLED" and observed["attempt_state"] == "CANCELLED"
    assert result.execution_effects["requested_type"] == "MARKET"
    assert result.execution_effects["effective_limit_price"] is None
    assert transport.reads == ["https://api.indstocks.com/order-book"]
