"""Actual legacy adapter contracts with injected, offline transport only."""
from types import SimpleNamespace

import pytest

from flinttrade_core.broker_read_port import BrokerReadResponseInvalid
from flinttrade_core.exceptions import BrokerError
from flinttrade_engine.safety import SafetyBypassError
from flinttrade_gateway.brokers import indmoney_mapping as m
from flinttrade_gateway.brokers._base import Session
from flinttrade_gateway.brokers.indmoney import IndMoneyAdapter, _ROUTER_TOKEN

pytestmark = pytest.mark.unit


class Transport:
    def __init__(self, response=None, *, status=200):
        self.response = response if response is not None else {"status": "success", "data": {"order_id": "EQ-TEST"}}
        self.status = status
        self.calls = []

    def __call__(self, method, url, *, headers, params=None, json_body=None):
        self.calls.append({"method": method, "path": url.removeprefix(m.BASE_URL),
                           "params": params, "body": json_body})
        return self.status, self.response


def setup(response=None, *, status=200):
    transport = Transport(response, status=status)
    adapter = IndMoneyAdapter(http_factory=lambda: transport, security_resolver=lambda symbol, exchange: "123")
    session = Session(access_token="SYNTHETIC", expires_at=4_102_444_800, account_id="OFFLINE", adapter_id="indmoney")
    return adapter, session, transport


def request(**changes):
    values = dict(symbol="SYNTHETIC", exchange="NSE", product="CNC", action="BUY", pricetype="LIMIT",
                  quantity="5", price="100", trigger_price="0", variety="regular", validity="DAY",
                  stop_loss_price="0", target_price="0")
    values.update(changes)
    return SimpleNamespace(**values)


@pytest.mark.asyncio
@pytest.mark.parametrize("changes", [{"quantity": "1.5"}, {"exchange": "NFO", "product": "CNC"},
                                      {"price": "NaN"}, {"trailing_jump": "1"}, {"is_tsl": True}])
async def test_i1_i4_adapter_refuses_invalid_intent_without_transport(changes):
    adapter, session, transport = setup()
    with pytest.raises(m.IndMoneyMappingError):
        await adapter.place_order(session, request(**changes), _router_token=_ROUTER_TOKEN)
    assert transport.calls == []


@pytest.mark.asyncio
async def test_i2_adapter_trigger_keeps_sell_legs_on_the_actual_wire():
    adapter, session, transport = setup()
    assert await adapter.place_order(session, request(
        variety="trigger", action="SELL", trigger_price="99", price="100",
        stop_loss_price="110", sl_limit_price="111", target_price="90", tgt_limit_price="89",
    ), _router_token=_ROUTER_TOKEN) == "EQ-TEST"
    assert transport.calls[0]["path"] == "/smart/order"
    body = transport.calls[0]["body"]
    assert body["trigger_limit_price"] == 100 and "limit_price" not in body
    assert body["sl_limit_price"] == 111 and body["tgt_limit_price"] == 89
    assert not {"requested_type", "effective_type", "trailing_active", "limitations"} & body.keys()


@pytest.mark.asyncio
async def test_i3_adapter_edit_uses_current_trigger_type_and_exact_wire():
    adapter, session, transport = setup()
    await adapter.modify_order(session, "EQ-TEST", {
        "variety": "trigger", "existing_order_type": "TRIGGER", "exchange": "NSE",
        "trigger_price": "101", "price": "102", "qty": 5,
    }, _router_token=_ROUTER_TOKEN)
    assert transport.calls == [{"method": "POST", "path": "/smart/order/modify", "params": None,
                               "body": {"order_id": "EQ-TEST", "segment": "EQUITY", "algo_id": "99999",
                                        "qty": 5, "trigger_price": 101, "trigger_limit_price": 102}}]


@pytest.mark.asyncio
async def test_runtime_write_controls_reject_missing_token_without_transport():
    adapter, session, transport = setup()
    for call in (lambda: adapter.place_order(session, request()),
                 lambda: adapter.modify_order(session, "EQ-TEST", {"qty": 5, "price": 100}),
                 lambda: adapter.cancel_order(session, "EQ-TEST"),
                 lambda: adapter.cancel_smart_order(session, "EQ-TEST", segment="EQUITY")):
        with pytest.raises(SafetyBypassError):
            await call()
    assert transport.calls == []


def row(**changes):
    values = {"id": "EQ-TEST", "name": "SYNTHETIC", "exchange": "NSE", "segment": "EQUITY",
              "product": "CNC", "txn_type": "BUY", "order_type": "LIMIT", "status": "CANCELLED",
              "requested_qty": "100", "traded_qty": "40", "security_id": "123"}
    values.update(changes)
    return values


@pytest.mark.asyncio
@pytest.mark.parametrize("book", [True, False])
@pytest.mark.parametrize("changes", [{"requested_qty": "1.5"}, {"traded_qty": "101"}, {"traded_qty": -1}])
async def test_r1_actual_order_read_refuses_impossible_quantities(book, changes):
    data = [row(**changes)] if book else row(**changes)
    adapter, session, _ = setup({"status": "success", "data": data})
    with pytest.raises(BrokerReadResponseInvalid):
        if book:
            await adapter.order_book(session)
        else:
            await adapter.order_details(session, "EQ-TEST")


@pytest.mark.asyncio
async def test_i5_actual_per_order_endpoint_binds_requested_id_and_keeps_each_fill():
    fill = {"fill_id": 1279916, "exch_order_id": "EX-FILL", "quantity": 25, "price": 73.55,
            "trade_date": "2026-01-02T09:02:00+05:30"}
    adapter, session, transport = setup({"status": "success", "data": [fill, {**fill, "fill_id": 1279917}]})
    result = await adapter.order_trades(session, "DRV-TEST")
    assert [item["orderid"] for item in result] == ["DRV-TEST", "DRV-TEST"]
    assert [item["fill_id"] for item in result] == [1279916, 1279917]
    assert result[0]["timestamp"] == "2026-01-02T09:02:00+05:30"
    assert transport.calls[0]["path"] == "/trades/DRV-TEST"


@pytest.mark.asyncio
@pytest.mark.parametrize("data", [None, {}, ["garbage"], [None]])
@pytest.mark.parametrize("segment_book", [True, False])
async def test_i5_malformed_fill_books_cannot_be_verified_empty(data, segment_book):
    adapter, session, _ = setup({"status": "success", "data": data})
    with pytest.raises(BrokerReadResponseInvalid):
        if segment_book:
            await adapter.trade_book_segment(session, "EQUITY")
        else:
            await adapter.order_trades(session, "DRV-TEST")


@pytest.mark.asyncio
async def test_i5_real_empty_fill_books_remain_supported():
    adapter, session, _ = setup({"status": "success", "data": []})
    assert await adapter.order_trades(session, "DRV-TEST") == []
    assert await adapter.trade_book_segment(session, "EQUITY") == []


@pytest.mark.asyncio
async def test_i6_adapter_retains_all_smart_results_then_refuses_a_single_id_for_many():
    response = {"status": "success", "data": {"order_data": [
        {"order_id": "EQ-FIRST", "order_status": "CREATED", "child_order_details": {
            "order_id": "GTT-FIRST", "order_status": "CREATED"}},
        {"order_id": "EQ-SECOND", "order_status": "FAILED", "error": "RMS denied"},
    ]}}
    adapter, session, transport = setup(response)
    with pytest.raises(m.IndMoneyMappingError, match="single|multiple"):
        await adapter.place_order(session, request(variety="trigger", trigger_price=101), _router_token=_ROUTER_TOKEN)
    assert len(transport.calls) == 1
    assert [item["parent_order_id"] for item in adapter.last_smart_order_results] == ["EQ-FIRST", "EQ-SECOND"]
    assert adapter.last_smart_order_results[1]["error"] == "RMS denied"
    assert adapter.last_child_order_id is None


@pytest.mark.asyncio
@pytest.mark.parametrize("error_type,status,exception_name", [
    ("RequestValidationException", 400, "OrderError"), ("TokenException", 403, "SessionExpired"),
    ("GatewayTimeoutException", 504, "BrokerTimeout"), ("RequestValidationException", 429, "RateLimitError"),
])
async def test_i7_actual_transport_raises_typed_error_with_broker_reason(error_type, status, exception_name):
    from flinttrade_core import exceptions

    adapter, session, transport = setup({"status": "error", "error_type": error_type, "error_code": "TEST-CODE",
                                        "message": "broker reason retained"}, status=status)
    with pytest.raises(getattr(exceptions, exception_name)) as error:
        await adapter.place_order(session, request(), _router_token=_ROUTER_TOKEN)
    assert error.value.broker_code == "TEST-CODE" and str(error.value) == "broker reason retained"
    assert len(transport.calls) == 1  # No retry or inference of definite non-execution.


@pytest.mark.asyncio
async def test_i8_family_cache_cannot_authorise_a_modify_after_missing_evidence_or_restart():
    adapter, session, transport = setup()
    session.extra["indmoney_order_families"] = {"EQ-TEST": "smart"}
    for extra in (session.extra, {}):
        session.extra = extra
        with pytest.raises(BrokerError, match="family|variety"):
            await adapter.modify_order(session, "EQ-TEST", {"qty": 5, "price": 100}, _router_token=_ROUTER_TOKEN)
    assert transport.calls == []


@pytest.mark.asyncio
async def test_i8_same_prefix_explicit_normal_and_smart_modify_remain_distinct():
    adapter, session, transport = setup()
    await adapter.modify_order(session, "EQ-TEST", {"variety": "regular", "qty": 5, "price": 100},
                               _router_token=_ROUTER_TOKEN)
    await adapter.modify_order(session, "EQ-TEST", {
        "variety": "gtt", "existing_order_type": "LIMIT", "exchange": "NSE", "sl_limit_price": 89,
    }, _router_token=_ROUTER_TOKEN)
    assert [call["path"] for call in transport.calls] == ["/order/modify", "/smart/order/modify"]
    assert transport.calls[1]["body"] == {"order_id": "EQ-TEST", "segment": "EQUITY",
                                         "algo_id": "99999", "sl_limit_price": 89}


@pytest.mark.asyncio
@pytest.mark.parametrize("data", [[], None, {}, ["bad"]])
async def test_i8_unavailable_gtt_segment_never_defaults_to_equity_or_writes(data):
    adapter, session, transport = setup({"status": "success", "data": data})
    with pytest.raises((BrokerError, BrokerReadResponseInvalid)):
        await adapter.cancel_smart_order(session, "GTT-OPAQUE", _router_token=_ROUTER_TOKEN)
    assert all(call["method"] == "GET" for call in transport.calls)


@pytest.mark.asyncio
async def test_i8_explicit_smart_cancellation_does_not_infer_role_or_sibling_effect():
    adapter, session, transport = setup({"status": "success", "data": {}})
    await adapter.cancel_smart_order(session, "GTT-OPAQUE", segment="DERIVATIVE", _router_token=_ROUTER_TOKEN)
    assert transport.calls == [{"method": "POST", "path": "/smart/order/cancel", "params": None,
                               "body": {"order_id": "GTT-OPAQUE", "segment": "DERIVATIVE"}}]


@pytest.mark.asyncio
@pytest.mark.parametrize("data", [[], [row(id="GTT-TEST", order_type="OCO")]])
async def test_i8_smart_visibility_cannot_claim_a_complete_book_from_ordinary_rows(data):
    adapter, session, transport = setup({"status": "success", "data": data})
    with pytest.raises(BrokerError, match="visibility|complete|unavailable"):
        await adapter.smart_orders(session)
    assert all(call["path"] == "/order-book" for call in transport.calls)


@pytest.mark.asyncio
async def test_i4_actual_adapter_retains_requested_effective_market_metadata_without_wire_leakage():
    adapter, session, transport = setup()
    await adapter.place_order(session, request(pricetype="MARKET", price=0), _router_token=_ROUTER_TOKEN)
    assert adapter.last_execution_effects == {
        "requested_type": "MARKET", "effective_type": "LIMIT", "effective_limit_price": None,
        "trailing_active": False, "limitations": ["MARKET_TO_LIMIT"],
    }
    assert transport.calls[0]["body"]["order_type"] == "MARKET"
    assert "effective_type" not in transport.calls[0]["body"]


@pytest.mark.asyncio
@pytest.mark.parametrize("status", ["failed", False, None])
async def test_ack_actual_write_refuses_non_success_envelope_even_when_it_has_an_id(status):
    adapter, session, transport = setup({"status": status, "data": {"order_id": "EQ-TEST"}})
    with pytest.raises((BrokerError, BrokerReadResponseInvalid, m.IndMoneyMappingError)):
        await adapter.place_order(session, request(), _router_token=_ROUTER_TOKEN)
    assert len(transport.calls) == 1


@pytest.mark.asyncio
@pytest.mark.parametrize("edit", [{"remarks": "mutate"}, {"trailing_jump": 0}, {"is_tsl": False},
                                  {"limit_price": 102}, {"quantity": "1.5"}, {"quantity": 0},
                                  {"trigger_price": "NaN"}, {"order_type": "LIMIT"}])
async def test_i3_actual_smart_edit_refusals_never_reach_transport(edit):
    adapter, session, transport = setup()
    changes = {"variety": "trigger", "existing_order_type": "TRIGGER", "exchange": "NSE", "trigger_price": 101}
    changes.update(edit)
    with pytest.raises(m.IndMoneyMappingError):
        await adapter.modify_order(session, "EQ-TEST", changes, _router_token=_ROUTER_TOKEN)
    assert transport.calls == []


@pytest.mark.asyncio
async def test_i8_opaque_gtt_segment_resolution_requires_one_valid_matching_observation():
    observed = row(id="GTT-TEST", exchange="BSE", segment="DERIVATIVE", product="MARGIN", order_type="OCO")
    adapter, session, transport = setup({"status": "success", "data": [observed, observed]})
    with pytest.raises(BrokerError, match="ambiguous"):
        await adapter.cancel_smart_order(session, "GTT-TEST", _router_token=_ROUTER_TOKEN)
    assert [call["method"] for call in transport.calls] == ["GET"]
