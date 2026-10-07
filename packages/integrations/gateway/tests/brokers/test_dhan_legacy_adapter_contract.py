"""Real legacy mapper → DhanAdapter → pinned SDK, with an inert HTTP recorder.

No SDK auth/client/network construction: use actual SDK resource methods and
signatures, replacing only their transport. This proves local invocation and
wire preservation, never live broker acceptance or readiness.
"""
from __future__ import annotations

from importlib.metadata import version
from inspect import signature
from types import SimpleNamespace
from typing import Any

import pytest
from dhanhq import ForeverOrder, Funds, Order as SDKOrder, Portfolio, SuperOrder

from flinttrade_core.broker_read_port import BrokerReadResponseInvalid
from flinttrade_core.exceptions import UnsupportedCapabilityError
from flinttrade_engine.safety import SafetyBypassError
from flinttrade_gateway.brokers import dhan_mapping as m
from flinttrade_gateway.brokers._base import Session
from flinttrade_gateway.brokers.dhan import DhanAdapter, _ROUTER_TOKEN

pytestmark = pytest.mark.unit


class RecordingHTTP:
    """Deterministic test transport, not a DhanHTTP instance."""

    def __init__(self) -> None:
        self.calls: list[tuple[str, str, dict[str, Any] | None]] = []
        self.responses: dict[tuple[str, str], dict[str, Any]] = {}

    def get(self, endpoint: str) -> dict[str, Any]:
        self.calls.append(("GET", endpoint, None))
        return self.responses[("GET", endpoint)]

    def post(self, endpoint: str, payload: dict[str, Any]) -> dict[str, Any]:
        self.calls.append(("POST", endpoint, payload))
        return self.responses.get(("POST", endpoint), {"status": "success", "data": {"orderId": "ack-example"}})

    def put(self, endpoint: str, payload: dict[str, Any]) -> dict[str, Any]:
        self.calls.append(("PUT", endpoint, payload))
        return self.responses.get(("PUT", endpoint), {"status": "success", "data": {}})


class RecordingSDK(SDKOrder, ForeverOrder, SuperOrder, Portfolio, Funds):
    def __init__(self, transport: RecordingHTTP) -> None:
        # Resource classes all obtain this same field from the real SDK context.
        # Supply only that field: never construct its authenticated DhanHTTP.
        self.dhan_http = transport


def adapter_and_session(transport: RecordingHTTP) -> tuple[DhanAdapter, Session]:
    sdk = RecordingSDK(transport)
    adapter = DhanAdapter(client_factory=lambda _session: sdk, security_resolver=lambda _symbol, _exchange: "11536")
    return adapter, Session(access_token="offline-fixture", expires_at=9e9, account_id="offline-account",
                            adapter_id="dhan", algo_id="offline-contract")


def test_sdk_version_is_the_repository_pin() -> None:
    assert version("dhanhq") == "2.2.0"
    assert RecordingSDK.modify_super_order is SuperOrder.modify_super_order
    assert RecordingSDK.modify_forever is ForeverOrder.modify_forever
    assert RecordingSDK.modify_order is SDKOrder.modify_order


async def test_super_stop_edit_without_trailing_intent_is_refused_before_sdk() -> None:
    transport = RecordingHTTP()
    adapter, session = adapter_and_session(transport)
    with pytest.raises(m.DhanMappingError, match="trailing"):
        await adapter.modify_super_order(session, "super-example",
                                         {"leg_name": "STOP_LOSS_LEG", "stop_loss_price": 90},
                                         _router_token=_ROUTER_TOKEN)
    assert transport.calls == []


async def test_super_listing_preserves_remaining_evidence_through_real_sdk() -> None:
    transport = RecordingHTTP()
    transport.responses[("GET", "/super/orders")] = {
        "status": "success", "data": [{"orderId": "super-example", "orderStatus": "PENDING", "remainingQuantity": 3}],
    }
    adapter, session = adapter_and_session(transport)
    rows = await adapter.super_orders(session)
    assert rows[0]["remaining_quantity"] == "3"
    assert "filled_quantity" not in rows[0]
    assert transport.calls == [("GET", "/super/orders", None)]


@pytest.mark.parametrize("value", [True, "NaN", "invalid", float("inf"), object()])
async def test_super_listing_invalid_remaining_is_a_read_error_not_an_empty_book(value: Any) -> None:
    transport = RecordingHTTP()
    transport.responses[("GET", "/super/orders")] = {
        "status": "success", "data": [{"orderId": "super-example", "remainingQuantity": value}],
    }
    adapter, session = adapter_and_session(transport)
    with pytest.raises(BrokerReadResponseInvalid):
        await adapter.super_orders(session)


@pytest.mark.parametrize("field", ["totalQuatity", "remainingQuantity", "triggeredQuantity", "price", "trailingJump",
                                   "quantity", "filledQty", "tradedQty", "triggerPrice"])
async def test_super_listing_rejects_invalid_nested_evidence_at_the_adapter(field: str) -> None:
    transport = RecordingHTTP()
    transport.responses[("GET", "/super/orders")] = {
        "status": "success", "data": [{"orderId": "super-example", "legDetails": [
            {"legName": "TARGET_LEG", "orderStatus": "PENDING", field: "NaN"},
        ]}],
    }
    adapter, session = adapter_and_session(transport)
    with pytest.raises(BrokerReadResponseInvalid):
        await adapter.super_orders(session)


def request(**changes: Any) -> SimpleNamespace:
    fields = {"symbol": "TCS", "action": "BUY", "exchange": "NSE", "product": "CNC", "pricetype": "LIMIT",
              "quantity": "9007199254740993", "disclosed_quantity": "0", "price": "100", "trigger_price": "99",
              "validity": "IOC", "variety": "regular", "target_price": "0", "stop_loss_price": "0",
              "trailing_jump": "0"}
    fields.update(changes)
    return SimpleNamespace(**fields)


def forever_replacement(**changes: Any) -> dict[str, Any]:
    fields = {"order_flag": "OCO", "leg_name": "STOP_LOSS_LEG", "pricetype": "STOP_LOSS",
              "quantity": "9007199254740993", "price": "90", "trigger_price": "91",
              "disclosed_quantity": "0", "validity": "IOC"}
    fields.update(changes)
    return fields


@pytest.mark.parametrize(("variety", "endpoint"), [("regular", "/orders"), ("iceberg", "/orders/slicing")])
async def test_place_normal_and_slice_preserve_exact_wire_fields(variety: str, endpoint: str) -> None:
    transport = RecordingHTTP()
    adapter, session = adapter_and_session(transport)
    result = await adapter.place_order(session, request(variety=variety), _router_token=_ROUTER_TOKEN)
    assert result == "ack-example"  # ACK only: this is not fill evidence.
    assert transport.calls == [("POST", endpoint, {
        "transactionType": "BUY", "exchangeSegment": "NSE_EQ", "productType": "CNC", "orderType": "LIMIT",
        "validity": "IOC", "securityId": "11536", "quantity": 9007199254740993, "disclosedQuantity": 0,
        "price": 100.0, "afterMarketOrder": False, "boProfitValue": None, "boStopLossValue": None,
        "triggerPrice": 99.0, "correlationId": "offline-contract",
    })]


@pytest.mark.parametrize("window", ["PRE_OPEN", "OPEN", "OPEN_30", "OPEN_60"])
async def test_amo_windows_reach_direct_rest_without_sdk_window_loss(window: str) -> None:
    transport = RecordingHTTP()
    adapter, session = adapter_and_session(transport)
    await adapter.place_order(session, request(variety="amo", amo_time=window), _router_token=_ROUTER_TOKEN)
    assert transport.calls == [("POST", "/orders", {
        "transactionType": "BUY", "exchangeSegment": "NSE_EQ", "productType": "CNC", "orderType": "LIMIT",
        "validity": "IOC", "securityId": "11536", "quantity": 9007199254740993, "disclosedQuantity": 0,
        "price": 100.0, "triggerPrice": 99.0, "afterMarketOrder": True, "amoTime": window,
        "correlationId": "offline-contract",
    })]


CONDITION = {"comparisonType": "TECHNICAL_WITH_VALUE", "exchangeSegment": "NSE_EQ", "securityId": "11536",
             "indicatorName": "SMA_5", "operator": "CROSSING_UP", "timeFrame": "DAY", "expDate": "2026-12-31",
             "frequency": "ONCE", "comparingValue": 250}


@pytest.mark.parametrize("surface", ["regular", "amo", "iceberg", "modify", "forever", "super", "convert",
                                    "conditional", "modify_conditional", "margin"])
@pytest.mark.parametrize("value", [True, "1.5", "invalid", float("inf")])
async def test_invalid_quantities_are_refused_before_the_real_sdk_or_http(surface: str, value: Any) -> None:
    transport = RecordingHTTP()
    adapter, session = adapter_and_session(transport)
    with pytest.raises(m.DhanMappingError, match="quantity"):
        if surface in ("regular", "amo", "iceberg"):
            await adapter.place_order(session, request(variety=surface, quantity=value), _router_token=_ROUTER_TOKEN)
        elif surface == "modify":
            await adapter.modify_order(session, "order-example", {"quantity": value}, _router_token=_ROUTER_TOKEN)
        elif surface == "forever":
            await adapter.modify_forever(session, "forever-example", forever_replacement(quantity=value),
                                         _router_token=_ROUTER_TOKEN)
        elif surface == "super":
            await adapter.modify_super_order(session, "super-example", {
                "leg_name": "ENTRY_LEG", "pricetype": "LIMIT", "quantity": value, "price": 100,
                "target_price": 110, "stop_loss_price": 90, "trailing_jump": 5,
            }, _router_token=_ROUTER_TOKEN)
        elif surface == "convert":
            await adapter.convert_position(session, {"symbol": "TCS", "exchange": "NSE", "from_product": "MIS",
                                                     "to_product": "CNC", "quantity": value},
                                           _router_token=_ROUTER_TOKEN)
        elif surface == "margin":
            await adapter.margin_calculator(session, request(quantity=value))
        elif surface == "conditional":
            await adapter.place_conditional_trigger(session, CONDITION, [request(quantity=value)],
                                                    _router_token=_ROUTER_TOKEN)
        else:
            await adapter.modify_conditional_trigger(session, "alert-example", CONDITION, [request(quantity=value)],
                                                     _router_token=_ROUTER_TOKEN)
    assert transport.calls == []


@pytest.mark.parametrize("validity", ["GTC", "GTD", "GTT", "FOREVER"])
async def test_invalid_ordinary_modify_validity_never_reaches_sdk(validity: str) -> None:
    transport = RecordingHTTP()
    adapter, session = adapter_and_session(transport)
    with pytest.raises(m.DhanMappingError, match="validity"):
        await adapter.modify_order(session, "order-example", {"quantity": 10, "validity": validity},
                                   _router_token=_ROUTER_TOKEN)
    assert transport.calls == []


async def test_normal_modify_preserves_exact_quantity_disclosure_and_ioc_in_sdk_body() -> None:
    transport = RecordingHTTP()
    adapter, session = adapter_and_session(transport)
    await adapter.modify_order(session, "order-example", {
        "pricetype": "SL", "leg_name": "ENTRY_LEG", "quantity": "9007199254740993", "price": "100",
        "trigger_price": "99", "disclosed_quantity": "0010", "validity": "ioc",
    }, _router_token=_ROUTER_TOKEN)
    assert transport.calls == [("PUT", "/orders/order-example", {
        "orderId": "order-example", "orderType": "STOP_LOSS", "legName": "ENTRY_LEG",
        "quantity": 9007199254740993, "price": 100.0, "disclosedQuantity": 10, "triggerPrice": 99.0, "validity": "IOC",
    })]


@pytest.mark.parametrize("order_type", ["STOP_LOSS", "STOP_LOSS_MARKET"])
async def test_forever_modify_keeps_stop_types_and_complete_replacement_on_actual_sdk(order_type: str) -> None:
    transport = RecordingHTTP()
    adapter, session = adapter_and_session(transport)
    await adapter.modify_forever(session, "forever-example", forever_replacement(pricetype=order_type),
                                 _router_token=_ROUTER_TOKEN)
    assert transport.calls == [("PUT", "/forever/orders/forever-example", {
        "orderId": "forever-example", "orderFlag": "OCO", "orderType": order_type, "legName": "STOP_LOSS_LEG",
        "quantity": 9007199254740993, "disclosedQuantity": 0, "price": 90.0, "triggerPrice": 91.0, "validity": "IOC",
    })]


@pytest.mark.parametrize(("changes", "body"), [
    ({"leg_name": "TARGET_LEG", "target_price": "110"},
     {"orderId": "super-example", "legName": "TARGET_LEG", "targetPrice": 110.0}),
    ({"leg_name": "STOP_LOSS_LEG", "stopLossPrice": "90", "trailingJump": "0"},
     {"orderId": "super-example", "legName": "STOP_LOSS_LEG", "stopLossPrice": 90.0, "trailingJump": 0.0}),
    ({"leg_name": "STOP_LOSS_LEG", "stop_loss_price": "90", "trailing_jump": "5"},
     {"orderId": "super-example", "legName": "STOP_LOSS_LEG", "stopLossPrice": 90.0, "trailingJump": 5.0}),
    ({"leg_name": "ENTRY_LEG", "order_type": "LIMIT", "quantity": "9007199254740993", "price": "100",
      "targetPrice": "110", "stopLossPrice": "90", "trailingJump": "5"},
     {"orderId": "super-example", "orderType": "LIMIT", "legName": "ENTRY_LEG", "quantity": 9007199254740993,
      "price": 100.0, "targetPrice": 110.0, "stopLossPrice": 90.0, "trailingJump": 5.0}),
])
async def test_super_edits_have_pinned_leg_specific_sdk_wire_correspondence(
    changes: dict[str, Any], body: dict[str, Any],
) -> None:
    transport = RecordingHTTP()
    adapter, session = adapter_and_session(transport)
    await adapter.modify_super_order(session, "super-example", changes, _router_token=_ROUTER_TOKEN)
    assert transport.calls == [("PUT", "/super/orders/super-example", body)]


@pytest.mark.parametrize("changes", [
    {"leg_name": "ENTRY_LEG", "quantity": 10},
    {"leg_name": "TARGET_LEG", "price": 110},
    {"leg_name": "STOP_LOSS_LEG", "stop_loss_price": 90, "trailing_jump": "invalid"},
    {"leg_name": "STOP_LOSS_LEG", "stop_loss_price": 90, "trailing_jump": True},
])
async def test_partial_or_malformed_super_replacements_never_reach_sdk(changes: dict[str, Any]) -> None:
    transport = RecordingHTTP()
    adapter, session = adapter_and_session(transport)
    with pytest.raises(m.DhanMappingError):
        await adapter.modify_super_order(session, "super-example", changes, _router_token=_ROUTER_TOKEN)
    assert transport.calls == []


async def test_conditional_quantities_and_native_spelling_reach_direct_http() -> None:
    transport = RecordingHTTP()
    transport.responses[("POST", "/alerts/orders")] = {"status": "success", "data": {"alertId": "alert-example"}}
    adapter, session = adapter_and_session(transport)
    result = await adapter.place_conditional_trigger(session, CONDITION, [request()], _router_token=_ROUTER_TOKEN)
    assert result == "alert-example"
    assert transport.calls == [("POST", "/alerts/orders", {"condition": CONDITION, "orders": [{
        "transactionType": "BUY", "exchangeSegment": "NSE_EQ", "productType": "CNC", "orderType": "LIMIT",
        "securityId": "11536", "quantity": 9007199254740993, "validity": "IOC", "price": "100.0",
        "discQuantity": "0", "triggerPrice": "99.0",
    }]})]


async def test_conversion_and_margin_keep_exact_quantities_in_pinned_sdk() -> None:
    transport = RecordingHTTP()
    transport.responses[("POST", "/margincalculator")] = {"status": "success", "data": {"totalMargin": 100}}
    adapter, session = adapter_and_session(transport)
    await adapter.convert_position(session, {"symbol": "TCS", "exchange": "NSE", "from_product": "MIS",
                                             "to_product": "CNC", "position_type": "LONG",
                                             "convert_qty": "9007199254740993"}, _router_token=_ROUTER_TOKEN)
    margin = await adapter.margin_calculator(session, request())
    assert margin["required_margin"] == "100"
    assert transport.calls == [
        ("POST", "/positions/convert", {"fromProductType": "INTRADAY", "exchangeSegment": "NSE_EQ",
                                        "positionType": "LONG", "securityId": "11536",
                                        "convertQty": 9007199254740993, "toProductType": "CNC"}),
        ("POST", "/margincalculator", {"securityId": "11536", "exchangeSegment": "NSE_EQ",
                                       "transactionType": "BUY", "quantity": 9007199254740993,
                                       "productType": "CNC", "price": 100.0, "triggerPrice": 99.0}),
    ]


async def test_forever_listing_keeps_native_family_products_missing_evidence_and_timestamps() -> None:
    transport = RecordingHTTP()
    transport.responses[("GET", "/forever/orders")] = {"status": "success", "data": [
        {"orderId": "forever-example", "orderType": "OCO", "orderStatus": "CONFIRM", "productType": "BO",
         "exchangeSegment": "MCX_COMM", "quantity1": 10, "price1": 110, "triggerPrice1": 109,
         "createTime": "2026-06-01 10:00:00", "updateTime": "2026-06-01 10:01:00",
         "exchangeTime": "2026-06-01 10:00:01"},
    ]}
    adapter, session = adapter_and_session(transport)
    rows = await adapter.forever_orders(session)
    assert len(rows) == 1
    row = rows[0]
    assert (row["order_flag"], row["broker_order_type"], row["pricetype"]) == ("OCO", "OCO", "")
    assert (row["broker_product"], row["product"], row["exchange"]) == ("BO", "MIS", "MCX")
    assert (row["quantity1"], row["price1"], row["trigger_price1"]) == ("10", "110", "109")
    assert row["oco_leg_complete"] is True
    assert (row["created_at"], row["updated_at"], row["exchange_time"]) == (
        "2026-06-01 10:00:00", "2026-06-01 10:01:00", "2026-06-01 10:00:01",
    )
    for absent in ("validity", "filled_quantity", "execution_order_id", "reduce_only", "closed", "terminal"):
        assert absent not in row


async def test_forever_conflicting_family_is_a_read_error_at_real_sdk_adapter_seam() -> None:
    transport = RecordingHTTP()
    transport.responses[("GET", "/forever/orders")] = {
        "status": "success", "data": [{"orderFlag": "SINGLE", "orderType": "OCO"}],
    }
    adapter, session = adapter_and_session(transport)
    with pytest.raises(BrokerReadResponseInvalid):
        await adapter.forever_orders(session)


async def test_super_listing_preserves_same_id_live_legs_and_detaches_observations() -> None:
    raw = {"orderId": "super-example", "orderStatus": "TRADED", "remainingQuantity": 0,
           "createTime": "2026-06-01 10:00:00", "updateTime": "2026-06-01 10:01:00", "legDetails": [
               {"orderId": "super-example", "parentOrderId": "super-example", "legName": "TARGET_LEG",
                "orderStatus": "PENDING", "totalQuatity": 10, "remainingQuantity": "3", "price": 110},
               {"orderId": "super-example", "legName": "STOP_LOSS_LEG", "orderStatus": "CANCEL_PENDING",
                "totalQuatity": 10, "remainingQuantity": 10, "triggeredQuantity": 0, "price": "90"},
           ]}
    transport = RecordingHTTP()
    transport.responses[("GET", "/super/orders")] = {"status": "success", "data": [raw]}
    adapter, session = adapter_and_session(transport)
    row = (await adapter.super_orders(session))[0]
    assert row["status"] == "TRADED" and row["remaining_quantity"] == "0"
    assert row["legs"] == raw["legDetails"]
    assert row["leg_details_valid"] is True
    assert row["updated_at"] == "2026-06-01 10:01:00"
    raw["legDetails"][0]["price"] = 999
    assert row["legs"][0]["price"] == 110
    assert [leg["orderStatus"] for leg in row["legs"]] == ["PENDING", "CANCEL_PENDING"]
    for observation in (row, *row["legs"]):
        assert "filled_quantity" not in observation and "closed" not in observation


@pytest.mark.parametrize("variety", ["gtt", "bracket", "cover"])
async def test_creation_freezes_remain_closed_even_with_valid_builders(variety: str) -> None:
    transport = RecordingHTTP()
    adapter, session = adapter_and_session(transport)
    with pytest.raises(UnsupportedCapabilityError):
        await adapter.place_order(session, request(variety=variety), _router_token=_ROUTER_TOKEN)
    assert transport.calls == []


def test_creation_builders_fit_actual_pinned_sdk_signatures_without_dispatch_enablement() -> None:
    sdk = RecordingSDK(RecordingHTTP())
    forever = m.to_forever_kwargs(request(price1="110", trigger_price1="109", quantity1="9007199254740993"), "11536")
    bound = signature(sdk.place_forever).bind(**forever)
    assert bound.arguments["trigger_Price"] == 99.0
    assert bound.arguments["trigger_Price1"] == 109.0
    assert bound.arguments["quantity1"] == 9007199254740993
    super_order = m.to_super_order_kwargs(request(target_price="110", stop_loss_price="90", trailing_jump="5"), "11536")
    super_bound = signature(sdk.place_super_order).bind(**super_order)
    assert super_bound.arguments["quantity"] == 9007199254740993
    assert super_bound.arguments["targetPrice"] == 110.0
    assert super_bound.arguments["stopLossPrice"] == 90.0
    assert super_bound.arguments["trailingJump"] == 5.0
    assert sdk.dhan_http.calls == []  # No creation/resource call was made.


async def test_write_token_identity_gate_stays_ahead_of_valid_mapping() -> None:
    transport = RecordingHTTP()
    adapter, session = adapter_and_session(transport)
    with pytest.raises(SafetyBypassError):
        await adapter.modify_super_order(session, "super-example", {"leg_name": "TARGET_LEG", "target_price": 110})
    with pytest.raises(SafetyBypassError):
        await adapter.modify_forever(session, "forever-example", forever_replacement())
    with pytest.raises(SafetyBypassError):
        await adapter.place_order(session, request())
    assert transport.calls == []
