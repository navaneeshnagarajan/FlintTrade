"""Groww's actual old mapper and injected adapter correspondence; no broker I/O."""

from copy import deepcopy
from typing import Any

import pytest

from flinttrade_core.broker_read_port import BrokerReadResponseInvalid
from flinttrade_core.exceptions import BrokerError
from flinttrade_core.models import Order
from flinttrade_engine.safety import SafetyBypassError
from flinttrade_gateway.brokers import groww_mapping as mapping
from flinttrade_gateway.brokers._base import ROUTER_TOKEN, Session
from flinttrade_gateway.brokers.groww import GrowwAdapter

pytestmark = pytest.mark.unit


class RecordingTransport:
    def __init__(self, response=None):
        self.calls: list[dict[str, Any]] = []
        self.response = response

    def __call__(self, method, url, *, headers, params=None, json_body=None):
        call = {
            "method": method,
            "path": url.removeprefix(mapping.BASE_URL),
            "params": params,
            "body": deepcopy(json_body),
        }
        self.calls.append(call)
        if self.response is not None:
            return self.response(call)
        if call["path"] == "/v1/order-advance/create":
            return 201, {"status": "SUCCESS", "payload": {"smart_order_id": "opaque-resource", "status": "ACTIVE"}}
        return 202, {"status": "SUCCESS", "payload": {"smart_order_id": "opaque-resource", "status": "ACTIVE"}}


def _session():
    return Session(access_token="fixture-token", expires_at=9e9, adapter_id="groww", account_id="fixture-account")


def _gtt_request():
    return {
        "reference_id": "sref-unique-123",
        "smart_order_type": "GTT",
        "segment": "CASH",
        "trading_symbol": "TCS",
        "quantity": 10,
        "trigger_price": "3985.00",
        "trigger_direction": "DOWN",
        "order": {"order_type": "LIMIT", "price": "3990.00", "transaction_type": "BUY"},
        "product_type": "CNC",
        "exchange": "NSE",
        "duration": "DAY",
    }


def _oco_request():
    return {
        "reference_id": "sref-unique-456",
        "smart_order_type": "OCO",
        "segment": "FNO",
        "trading_symbol": "NIFTY25OCT24000CE",
        "quantity": 50,
        "net_position_quantity": 50,
        "transaction_type": "SELL",
        "target": {"trigger_price": "120.50", "order_type": "LIMIT", "price": "121.00"},
        "stop_loss": {"trigger_price": "95.00", "order_type": "SL_M", "price": None},
        "product_type": "NRML",
        "exchange": "NSE",
        "duration": "DAY",
    }


def _gtt_order(**edits):
    return Order(
        **{
            "symbol": "TCS",
            "action": "BUY",
            "exchange": "NSE",
            "product": "CNC",
            "quantity": "10",
            "pricetype": "LIMIT",
            "price": "3990.00",
            "trigger_price": "3985.00",
            "strategy": "sref-unique-123",
            "validity": "DAY",
            "variety": "gtt",
            "entry_trigger_type": "DOWN",
            **edits,
        }
    )


@pytest.mark.asyncio
async def test_actual_adapter_gtt_create_uses_complete_native_resource_shape():
    def respond(call):
        assert call["body"] == _gtt_request()
        return 201, {"status": "SUCCESS", "payload": {"smart_order_id": "opaque-resource", "status": "ACTIVE"}}

    transport = RecordingTransport(respond)
    adapter = GrowwAdapter(http_factory=lambda: transport)
    result = await adapter.place_order(_session(), _gtt_order(), _router_token=ROUTER_TOKEN)
    assert result == "opaque-resource"  # ACK only, not a fill or position closure.
    assert transport.calls == [
        {
            "method": "POST",
            "path": "/v1/order-advance/create",
            "params": None,
            "body": _gtt_request(),
        }
    ]


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "edits",
    [
        {"entry_trigger_type": None},
        {"entry_trigger_type": "ABOVE"},
        {"variety": "oco"},
        {"target_price": "4100"},
        {"trailing_jump": "1"},
        {"validity": "IOC"},
    ],
)
async def test_actual_adapter_smart_create_refuses_absent_or_unrepresented_intent_before_transport(edits):
    transport = RecordingTransport()
    adapter = GrowwAdapter(http_factory=lambda: transport)
    with pytest.raises(BrokerError):
        await adapter.place_order(_session(), _gtt_order(**edits), _router_token=ROUTER_TOKEN)
    assert transport.calls == []


@pytest.mark.parametrize("native_request", [_gtt_request(), _oco_request()])
def test_actual_old_mapper_native_smart_create_preserves_documented_fields_and_units(native_request):
    original = deepcopy(native_request)
    payload = mapping.to_smart_create_payload(native_request)
    assert payload == original
    assert payload is not native_request
    assert native_request == original
    assert "reduce_only" not in payload


@pytest.mark.parametrize(("net", "side"), [(50, "SELL"), (-50, "BUY")])
def test_actual_old_mapper_oco_preserves_signed_position_and_opposing_side(net, side):
    request = _oco_request()
    request.update(net_position_quantity=net, transaction_type=side)
    assert mapping.to_smart_create_payload(request) == request
    request["quantity"] = 51
    with pytest.raises(BrokerError):
        mapping.to_smart_create_payload(request)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("exchange", "product", "segment", "native_exchange"),
    [
        ("NSE", "CNC", "CASH", "NSE"),
        ("BSE", "CNC", "CASH", "BSE"),
        ("NFO", "NRML", "FNO", "NSE"),
        ("BFO", "NRML", "FNO", "BSE"),
    ],
)
@pytest.mark.parametrize(
    ("kind", "native_kind"), [("LIMIT", "LIMIT"), ("MARKET", "MARKET"), ("SL", "SL"), ("SL-M", "SL_M")]
)
async def test_actual_adapter_gtt_keeps_supported_pairs_types_and_native_quantity_units(
    exchange,
    product,
    segment,
    native_exchange,
    kind,
    native_kind,
):
    transport = RecordingTransport()
    adapter = GrowwAdapter(http_factory=lambda: transport)
    await adapter.place_order(
        _session(),
        _gtt_order(exchange=exchange, product=product, quantity="51", pricetype=kind),
        _router_token=ROUTER_TOKEN,
    )
    body = transport.calls[0]["body"]
    assert body["segment"] == segment and body["exchange"] == native_exchange
    assert body["product_type"] == product and body["quantity"] == 51
    assert body["order"]["order_type"] == native_kind
    assert body["trigger_price"] == "3985.00"
    if native_kind in {"LIMIT", "SL"}:
        assert body["order"]["price"] == "3990.00"
    assert "net_position_quantity" not in body and "validity" not in body and "product" not in body


def _current(family="GTT"):
    current = _gtt_request() if family == "GTT" else _oco_request()
    current.pop("reference_id")
    current["smart_order_id"] = "opaque-resource"
    return current


@pytest.mark.asyncio
async def test_actual_adapter_gtt_modify_replays_current_side_and_native_market_null_price():
    transport = RecordingTransport()
    adapter = GrowwAdapter(http_factory=lambda: transport)
    current = _current()
    edits = {"variety": "gtt", "current": current, "quantity": 12, "order": {"order_type": "MARKET"}}
    original = deepcopy(edits)
    await adapter.modify_order(_session(), "opaque-resource", edits, _router_token=ROUTER_TOKEN)
    assert transport.calls == [
        {
            "method": "PUT",
            "path": "/v1/order-advance/modify/opaque-resource",
            "params": None,
            "body": {
                "smart_order_type": "GTT",
                "segment": "CASH",
                "quantity": 12,
                "order": {"order_type": "MARKET", "price": None, "transaction_type": "BUY"},
            },
        }
    ]
    assert edits == original


@pytest.mark.asyncio
async def test_actual_adapter_oco_modify_preserves_sparse_editable_fields_not_current_metadata():
    transport = RecordingTransport()
    adapter = GrowwAdapter(http_factory=lambda: transport)
    current = _current("OCO")
    current["child_legs"] = {"unknown_schema": ["opaque-child"]}
    changes = {
        "variety": "oco",
        "current": current,
        "quantity": 40,
        "duration": "DAY",
        "product_type": "NRML",
        "target": {"trigger_price": "122.00"},
        "stop_loss": {"trigger_price": "97.50"},
    }
    await adapter.modify_order(_session(), "opaque-resource", changes, _router_token=ROUTER_TOKEN)
    assert transport.calls[0]["path"] == "/v1/order-advance/modify/opaque-resource"
    assert transport.calls[0]["body"] == {
        "smart_order_type": "OCO",
        "segment": "FNO",
        "quantity": 40,
        "duration": "DAY",
        "product_type": "NRML",
        "target": {"trigger_price": "122.00"},
        "stop_loss": {"trigger_price": "97.50"},
    }


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("family", "edits"),
    [
        ("GTT", {"product_type": "CNC"}),
        ("GTT", {"duration": "DAY"}),
        ("GTT", {"order": {"transaction_type": "SELL"}}),
        ("GTT", {"child_legs": {}}),
        ("GTT", {"order": {"order_type": "SL_M", "price": "100.00"}}),
        ("GTT", {"quantity": 0}),
        ("GTT", {"trigger_price": "NaN"}),
        ("OCO", {"target": {"order_type": "MARKET"}}),
        ("OCO", {"target": {"price": "100"}}),
        ("OCO", {"stop_loss": {"order_type": "SL"}}),
        ("OCO", {"quantity": 51}),
        ("OCO", {"trigger_direction": "UP"}),
        ("OCO", {"unknown": 1}),
    ],
)
async def test_actual_adapter_smart_modify_refuses_resource_incompatible_or_unrepresented_edits(family, edits):
    transport = RecordingTransport()
    adapter = GrowwAdapter(http_factory=lambda: transport)
    with pytest.raises(BrokerError):
        await adapter.modify_order(
            _session(),
            "opaque-resource",
            {"variety": family.lower(), "current": _current(family), **edits},
            _router_token=ROUTER_TOKEN,
        )
    assert transport.calls == []


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "changes",
    [
        {"variety": "gtt", "quantity": 10},
        {"smart_order_type": "GTT", "segment": "CASH", "quantity": 10},
        {"current": {"smart_order_id": "other", "smart_order_type": "GTT", "segment": "CASH"}, "quantity": 10},
        {"current": {"smart_order_id": "opaque-resource", "smart_order_type": "GTT"}, "quantity": 10},
        {"variety": "oco", "current": _current("GTT"), "quantity": 10},
        {"segment": "FNO", "current": _current("GTT"), "quantity": 10},
        {"smart_order_type": "OCO", "current": _current("GTT"), "quantity": 10},
    ],
)
async def test_actual_adapter_smart_modify_requires_explicit_matching_current_resource_context(changes):
    transport = RecordingTransport()
    adapter = GrowwAdapter(http_factory=lambda: transport)
    with pytest.raises(BrokerError):
        await adapter.modify_order(_session(), "opaque-resource", changes, _router_token=ROUTER_TOKEN)
    assert transport.calls == []


@pytest.mark.asyncio
async def test_actual_adapter_does_not_authorise_smart_family_from_id_prefix():
    transport = RecordingTransport()
    adapter = GrowwAdapter(http_factory=lambda: transport)
    with pytest.raises(BrokerError):
        await adapter.modify_order(
            _session(),
            "gtt_untrusted_prefix",
            {"segment": "CASH", "pricetype": "LIMIT", "quantity": 10},
            _router_token=ROUTER_TOKEN,
        )
    assert transport.calls == []


@pytest.mark.asyncio
async def test_actual_adapter_oco_partial_edit_does_not_require_creation_only_position_fields():
    transport = RecordingTransport()
    adapter = GrowwAdapter(http_factory=lambda: transport)
    current = {"smart_order_id": "opaque-resource", "smart_order_type": "OCO", "segment": "FNO"}
    await adapter.modify_order(
        _session(),
        "opaque-resource",
        {"current": current, "target": {"trigger_price": "122.00"}},
        _router_token=ROUTER_TOKEN,
    )
    assert transport.calls[0]["body"] == {
        "smart_order_type": "OCO",
        "segment": "FNO",
        "target": {"trigger_price": "122.00"},
    }


def _ordinary_row(identifier, segment="CASH", **edits):
    return {
        "groww_order_id": identifier,
        "order_status": "OPEN",
        "trading_symbol": "TCS",
        "exchange": "MCX" if segment == "COMMODITY" else "NSE",
        "segment": segment,
        "transaction_type": "BUY",
        "product": "CNC" if segment == "CASH" else "NRML",
        "order_type": "LIMIT",
        "quantity": 10,
        "filled_quantity": 4,
        **edits,
    }


@pytest.mark.asyncio
async def test_actual_adapter_ordinary_book_reads_all_pages_of_all_segments():
    def respond(call):
        assert call["path"] == "/v1/order/list"
        params = call["params"]
        rows = []
        if params["segment"] == "CASH":
            rows = (
                [_ordinary_row(f"order-{index}") for index in range(100)]
                if params["page"] == 0
                else [_ordinary_row("last")]
            )
        return 200, {"status": "SUCCESS", "payload": {"order_list": rows}}

    transport = RecordingTransport(respond)
    adapter = GrowwAdapter(http_factory=lambda: transport)
    rows = await adapter.order_book(_session())
    assert [row["orderid"] for row in rows] == [f"order-{index}" for index in range(100)] + ["last"]
    assert [(call["params"]["segment"], call["params"]["page"]) for call in transport.calls] == [
        ("CASH", 0),
        ("CASH", 1),
        ("FNO", 0),
        ("COMMODITY", 0),
    ]


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "bad",
    [
        {"status": "SUCCESS", "payload": {}},
        {"status": "SUCCESS", "payload": {"order_list": None}},
        {"status": "SUCCESS", "payload": {"order_list": [None]}},
        {"status": "FAILURE", "payload": {"order_list": []}},
    ],
)
async def test_actual_adapter_later_malformed_or_unavailable_order_page_is_not_a_complete_partial_book(bad):
    def respond(call):
        if call["params"]["page"] == 0:
            return 200, {
                "status": "SUCCESS",
                "payload": {"order_list": [_ordinary_row(f"order-{i}") for i in range(100)]},
            }
        return 200, bad

    transport = RecordingTransport(respond)
    adapter = GrowwAdapter(http_factory=lambda: transport)
    with pytest.raises((BrokerReadResponseInvalid, BrokerError)):
        await adapter.order_book(_session())


@pytest.mark.asyncio
@pytest.mark.parametrize("method", ["order_book", "order_details", "order_status"])
async def test_actual_adapter_ordinary_reads_refuse_impossible_quantity_evidence(method):
    row = _ordinary_row("opaque-resource", quantity="9007199254740992", filled_quantity="9007199254740993")

    def respond(call):
        body = {"order_list": [row]} if call["path"] == "/v1/order/list" else row
        return 200, {"status": "SUCCESS", "payload": body}

    transport = RecordingTransport(respond)
    adapter = GrowwAdapter(http_factory=lambda: transport)
    args = () if method == "order_book" else ("opaque-resource",)
    with pytest.raises(BrokerReadResponseInvalid):
        await getattr(adapter, method)(_session(), *args)


@pytest.mark.asyncio
async def test_actual_adapter_documented_abbreviated_status_keeps_missing_requested_quantity_unknown():
    transport = RecordingTransport(
        lambda call: (
            200,
            {
                "status": "SUCCESS",
                "payload": {
                    "groww_order_id": "opaque-resource",
                    "order_status": "CANCELLATION_REQUESTED",
                    "filled_quantity": 4,
                    "order_reference_id": "sref-unique-123",
                    "remark": "pending cancellation",
                },
            },
        )
    )
    adapter = GrowwAdapter(http_factory=lambda: transport)
    result = await adapter.order_status(_session(), "opaque-resource", segment="FNO")
    assert result["status"] == "CANCEL_PENDING"
    assert result["filled_quantity"] == 4
    assert "quantity" not in result and "exchange" not in result


@pytest.mark.asyncio
async def test_actual_adapter_order_trades_reads_all_pages_without_order_total_checks_on_independent_fills():
    def respond(call):
        assert call["path"] == "/v1/order/trades/opaque-resource"
        count = 50 if call["params"]["page"] == 0 else 1
        rows = [
            {
                "groww_trade_id": f"fill-{call['params']['page']}-{i}",
                "groww_order_id": "opaque-resource",
                "trading_symbol": "TCS",
                "exchange": "NSE",
                "segment": "CASH",
                "transaction_type": "BUY",
                "quantity": 1,
                "price": "100.00",
                "product": "CNC",
                "created_at": "2026-10-07T10:00:00",
            }
            for i in range(count)
        ]
        return 200, {"status": "SUCCESS", "payload": {"trade_list": rows}}

    transport = RecordingTransport(respond)
    adapter = GrowwAdapter(http_factory=lambda: transport)
    fills = await adapter.order_trades(_session(), "opaque-resource")
    assert len(fills) == 51 and fills[-1]["tradeid"] == "fill-1-0"
    assert [call["params"]["page"] for call in transport.calls] == [0, 1]


@pytest.mark.asyncio
@pytest.mark.parametrize("family", ["GTT", "OCO"])
@pytest.mark.parametrize("segment", ["CASH", "FNO"])
async def test_actual_adapter_smart_detail_preserves_scoped_opaque_observations_without_fill_inference(family, segment):
    native = {
        "smart_order_id": "opaque-resource",
        "smart_order_type": family,
        "segment": segment,
        "exchange": "BSE",
        "product_type": "HISTORICAL_PRODUCT",
        "status": "COMPLETED",
        "child_legs": {"unknown": [{"failure": {"code": "REJECTED"}}]},
    }
    transport = RecordingTransport(lambda call: (200, {"status": "SUCCESS", "payload": native}))
    adapter = GrowwAdapter(http_factory=lambda: transport)
    result = await adapter.smart_order_details(_session(), "opaque-resource", segment=segment, smart_order_type=family)
    assert result["native"] == native
    assert result["status"] == "UNKNOWN" and result["raw_status"] == "COMPLETED"
    assert result["scope"] == {"segment": segment, "smart_order_type": family, "smart_order_id": "opaque-resource"}
    assert transport.calls[0]["path"] == f"/v1/order-advance/status/{segment}/{family}/internal/opaque-resource"
    result["native"]["child_legs"]["unknown"][0]["failure"]["code"] = "changed"
    assert native["child_legs"]["unknown"][0]["failure"]["code"] == "REJECTED"


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "orders", [[], [{"smart_order_id": "opaque-resource", "smart_order_type": "GTT", "status": "ACTIVE"}]]
)
async def test_actual_adapter_smart_page_has_explicit_query_scope_and_never_claims_complete_book(orders):
    transport = RecordingTransport(
        lambda call: (200, {"status": "SUCCESS", "payload": {"orders": orders, "next_page": 1}})
    )
    adapter = GrowwAdapter(http_factory=lambda: transport)
    result = await adapter.smart_orders_page(
        _session(),
        segment="FNO",
        smart_order_type="GTT",
        status="ACTIVE",
        start_date_time="2026-10-01T00:00:00",
        end_date_time="2026-10-07T23:59:59",
        page=0,
        page_size=50,
    )
    assert result["complete"] is False and len(result["orders"]) == len(orders)
    assert result["pagination"] == {"next_page": 1}
    assert (
        result["scope"]
        == transport.calls[0]["params"]
        == {
            "segment": "FNO",
            "smart_order_type": "GTT",
            "status": "ACTIVE",
            "page": 0,
            "page_size": 50,
            "start_date_time": "2026-10-01T00:00:00",
            "end_date_time": "2026-10-07T23:59:59",
        }
    )
    if orders:
        assert result["orders"][0]["status"] == "ARMED"
        assert result["orders"][0]["segment"] is None  # Query scope is not manufactured native evidence.


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "envelope",
    [
        {"status": "FAILURE", "payload": {"orders": []}},
        {"status": "SUCCESS", "payload": {}},
        {"status": "SUCCESS", "payload": {"orders": None}},
        {"status": "SUCCESS", "payload": {"orders": [None]}},
        {"payload": {"orders": []}},
    ],
)
async def test_actual_adapter_smart_page_unavailable_or_malformed_is_not_empty(envelope):
    transport = RecordingTransport(lambda call: (200, envelope))
    adapter = GrowwAdapter(http_factory=lambda: transport)
    with pytest.raises((BrokerReadResponseInvalid, BrokerError)):
        await adapter.smart_orders_page(
            _session(),
            segment="CASH",
            smart_order_type="GTT",
            status="ACTIVE",
            start_date_time="2026-10-01T00:00:00",
            end_date_time="2026-10-07T23:59:59",
        )


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "kwargs",
    [
        {},
        {"segment": "CASH"},
        {"smart_order_type": "GTT"},
        {"segment": None, "smart_order_type": "GTT"},
        {"segment": "EQUITY", "smart_order_type": "GTT"},
        {"segment": "FNO", "smart_order_type": "UNKNOWN"},
        {"segment": "cash", "smart_order_type": "GTT"},
        {"segment": "CASH", "smart_order_type": "gtt"},
        {"segment": [], "smart_order_type": "GTT"},
        {"segment": "FNO", "smart_order_type": []},
    ],
)
async def test_actual_adapter_smart_cancel_requires_explicit_native_family_and_segment(kwargs):
    transport = RecordingTransport()
    adapter = GrowwAdapter(http_factory=lambda: transport)
    with pytest.raises(BrokerError):
        await adapter.cancel_smart_order(_session(), "opaque-resource", **kwargs, _router_token=ROUTER_TOKEN)
    assert transport.calls == []


@pytest.mark.asyncio
@pytest.mark.parametrize("identifier", [None, True, "", " id", "id/path", "id?x", "id%2fpath", "ümlaut", ".."])
async def test_actual_adapter_smart_cancel_refuses_unsafe_id_before_transport(identifier):
    transport = RecordingTransport()
    adapter = GrowwAdapter(http_factory=lambda: transport)
    with pytest.raises(BrokerError):
        await adapter.cancel_smart_order(
            _session(), identifier, segment="FNO", smart_order_type="OCO", _router_token=ROUTER_TOKEN
        )
    assert transport.calls == []


@pytest.mark.asyncio
@pytest.mark.parametrize("family", ["GTT", "OCO"])
@pytest.mark.parametrize("segment", ["CASH", "FNO"])
async def test_actual_adapter_smart_cancel_addresses_explicit_resource_once_without_ordinary_body(family, segment):
    transport = RecordingTransport()
    adapter = GrowwAdapter(http_factory=lambda: transport)
    await adapter.cancel_smart_order(
        _session(), "opaque-resource", segment=segment, smart_order_type=family, _router_token=ROUTER_TOKEN
    )
    assert transport.calls == [
        {
            "method": "POST",
            "path": f"/v1/order-advance/cancel/{segment}/{family}/opaque-resource",
            "params": None,
            "body": None,
        }
    ]


@pytest.mark.asyncio
@pytest.mark.parametrize("operation", ["place", "modify", "cancel", "smart_cancel"])
@pytest.mark.parametrize("token", [None, object()])
async def test_actual_adapter_write_token_is_checked_before_identity_or_payload_and_transport(operation, token):
    transport = RecordingTransport()
    adapter = GrowwAdapter(http_factory=lambda: transport)
    with pytest.raises(SafetyBypassError):
        if operation == "place":
            await adapter.place_order(_session(), _gtt_order(), _router_token=token)
        elif operation == "modify":
            await adapter.modify_order(_session(), "unsafe/id", {}, _router_token=token)
        elif operation == "cancel":
            await adapter.cancel_order(_session(), "unsafe/id", _router_token=token)
        else:
            await adapter.cancel_smart_order(_session(), "unsafe/id", _router_token=token)
    assert transport.calls == []


@pytest.mark.asyncio
@pytest.mark.parametrize("variety", [[], {}, "", None, "GTT"])
async def test_actual_adapter_placement_refuses_malformed_or_noncanonical_variety_without_defaulting(variety):
    transport = RecordingTransport()
    adapter = GrowwAdapter(http_factory=lambda: transport)
    order = _gtt_order().model_copy(update={"variety": variety})
    with pytest.raises(BrokerError):
        await adapter.place_order(_session(), order, _router_token=ROUTER_TOKEN)
    assert transport.calls == []


@pytest.mark.asyncio
@pytest.mark.parametrize("variety", [[], {}])
async def test_actual_adapter_modification_refuses_non_string_variety_with_typed_error(variety):
    transport = RecordingTransport()
    adapter = GrowwAdapter(http_factory=lambda: transport)
    with pytest.raises(BrokerError):
        await adapter.modify_order(
            _session(),
            "opaque-resource",
            {"variety": variety, "segment": "CASH", "pricetype": "LIMIT"},
            _router_token=ROUTER_TOKEN,
        )
    assert transport.calls == []


@pytest.mark.asyncio
@pytest.mark.parametrize("allowed", [False, "true", 1, None])
async def test_actual_adapter_smart_modify_observed_permission_refusal_or_malformed_hint_is_not_authority(allowed):
    current = _current()
    current["is_modification_allowed"] = allowed
    transport = RecordingTransport()
    adapter = GrowwAdapter(http_factory=lambda: transport)
    with pytest.raises(BrokerError):
        await adapter.modify_order(
            _session(), "opaque-resource", {"current": current, "quantity": 10}, _router_token=ROUTER_TOKEN
        )
    assert transport.calls == []


@pytest.mark.asyncio
@pytest.mark.parametrize("variety", ["regular", "gtt"])
@pytest.mark.parametrize(
    "edits",
    [
        {"market_protection": True},
        {"market_protection": False},
        {"trailing_jump": "1"},
        {"target_price": "4100"},
        {"stop_loss_price": "3900"},
        {"iceberg_legs": "2"},
    ],
)
async def test_actual_adapter_does_not_silently_drop_unrepresented_active_features(variety, edits):
    transport = RecordingTransport()
    adapter = GrowwAdapter(http_factory=lambda: transport)
    order = _gtt_order(variety=variety, entry_trigger_type="DOWN" if variety == "gtt" else None, **edits)
    with pytest.raises(BrokerError):
        await adapter.place_order(_session(), order, _router_token=ROUTER_TOKEN)
    assert transport.calls == []


@pytest.mark.asyncio
@pytest.mark.parametrize("returned", [None, True, 123, " id", "id/path", "id%2f", "id?x"])
async def test_actual_adapter_smart_create_ack_requires_safe_exact_resource_id(returned):
    transport = RecordingTransport(
        lambda call: (201, {"status": "SUCCESS", "payload": {"smart_order_id": returned, "status": "ACTIVE"}})
    )
    adapter = GrowwAdapter(http_factory=lambda: transport)
    with pytest.raises(BrokerError):
        await adapter.place_order(_session(), _gtt_order(), _router_token=ROUTER_TOKEN)
    assert len(transport.calls) == 1  # Malformed/lost ACK is not permission to retry.


@pytest.mark.parametrize("variety", [[], {}])
def test_actual_old_mapper_smart_modify_refuses_non_string_variety_with_typed_error(variety):
    with pytest.raises(BrokerError):
        mapping.to_smart_modify_payload("opaque-resource", {"current": _current(), "variety": variety, "quantity": 10})


@pytest.mark.asyncio
@pytest.mark.parametrize("metadata", [{"has_more": True}, {"next_page": 1}])
async def test_actual_adapter_short_page_with_explicit_continuation_is_not_terminal(metadata):
    def respond(call):
        params = call["params"]
        if params["segment"] != "CASH":
            page = {"order_list": []}
        elif params["page"] == 0:
            page = {"order_list": [_ordinary_row("first")], **metadata}
        else:
            page = {"order_list": [_ordinary_row("last")], "has_more": False}
        return 200, {"status": "SUCCESS", "payload": page}

    adapter = GrowwAdapter(http_factory=lambda: RecordingTransport(respond))
    assert [row["orderid"] for row in await adapter.order_book(_session())] == ["first", "last"]


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "metadata",
    [
        {"has_more": "true"},
        {"next_page": True},
        {"next_page": 2},
        {"has_more": False, "next_page": 1},
        {"page": 1},
        {"page_size": True},
    ],
)
async def test_actual_adapter_malformed_pagination_is_not_complete_book(metadata):
    transport = RecordingTransport(
        lambda call: (
            200,
            {
                "status": "SUCCESS",
                "payload": {
                    "order_list": [_ordinary_row("first")],
                    **metadata,
                },
            },
        )
    )
    adapter = GrowwAdapter(http_factory=lambda: transport)
    with pytest.raises(BrokerReadResponseInvalid):
        await adapter.order_book(_session())


@pytest.mark.asyncio
async def test_actual_adapter_repeated_full_page_is_unavailable_not_deduplicated_or_truncated():
    transport = RecordingTransport(
        lambda call: (
            200,
            {
                "status": "SUCCESS",
                "payload": {
                    "order_list": [_ordinary_row(f"order-{i}") for i in range(100)],
                },
            },
        )
    )
    adapter = GrowwAdapter(http_factory=lambda: transport)
    with pytest.raises(BrokerReadResponseInvalid):
        await adapter.order_book(_session())
    assert len(transport.calls) == 2


@pytest.mark.asyncio
async def test_actual_adapter_explicit_empty_ordinary_book_is_distinct_from_unavailable_smart_book():
    transport = RecordingTransport(lambda call: (200, {"status": "SUCCESS", "payload": {"order_list": []}}))
    adapter = GrowwAdapter(http_factory=lambda: transport)
    assert await adapter.order_book(_session()) == []
    with pytest.raises(BrokerError, match="no unscoped complete smart book"):
        await adapter.smart_orders(_session())


@pytest.mark.asyncio
@pytest.mark.parametrize("family", ["GTT", "OCO"])
@pytest.mark.parametrize("segment", ["CASH", "FNO"])
async def test_actual_adapter_smart_pages_preserve_bse_unknown_states_opaque_children_and_duplicates(family, segment):
    native = {
        "smart_order_id": "opaque-resource",
        "smart_order_type": family,
        "segment": segment,
        "exchange": "BSE",
        "status": "NEW_STATUS",
        "product_type": "HISTORICAL",
        "child_legs": {"opaque": [{"failure": "unknown"}]},
    }
    transport = RecordingTransport(lambda call: (200, {"status": "SUCCESS", "payload": {"orders": [native, native]}}))
    adapter = GrowwAdapter(http_factory=lambda: transport)
    result = await adapter.smart_orders_page(
        _session(),
        segment=segment,
        smart_order_type=family,
        status="ACTIVE",
        start_date_time="2026-10-01T00:00:00",
        end_date_time="2026-10-07T23:59:59",
        page=1,
    )
    assert [row["native"] for row in result["orders"]] == [native, native]
    assert [row["status"] for row in result["orders"]] == ["UNKNOWN", "UNKNOWN"]
    assert result["complete"] is False and result["scope"]["page"] == 1
    result["orders"][0]["native"]["child_legs"]["opaque"][0]["failure"] = "changed"
    assert result["orders"][1]["native"]["child_legs"]["opaque"][0]["failure"] == "unknown"


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "edits",
    [
        {"segment": "COMMODITY"},
        {"smart_order_type": None},
        {"page": -1},
        {"page": 501},
        {"page_size": True},
        {"page_size": 51},
        {"status": ""},
        {"start_date_time": None},
        {"end_date_time": "2026-09-30T00:00:00"},
        {"end_date_time": "2026-12-01T00:00:00"},
    ],
)
async def test_actual_adapter_smart_page_scope_is_explicit_and_validated_before_transport(edits):
    transport = RecordingTransport()
    adapter = GrowwAdapter(http_factory=lambda: transport)
    scope = {
        "segment": "CASH",
        "smart_order_type": "GTT",
        "status": "ACTIVE",
        "start_date_time": "2026-10-01T00:00:00",
        "end_date_time": "2026-10-07T23:59:59",
        **edits,
    }
    with pytest.raises(BrokerError):
        await adapter.smart_orders_page(_session(), **scope)
    assert transport.calls == []


@pytest.mark.asyncio
async def test_actual_adapter_ordinary_decimal_wire_fields_remain_json_numbers_like_rest_schema():
    transport = RecordingTransport(
        lambda call: (200, {"status": "SUCCESS", "payload": {"groww_order_id": "ordinary-resource"}})
    )
    adapter = GrowwAdapter(http_factory=lambda: transport)
    order = Order(
        symbol="WIPRO",
        action="BUY",
        exchange="NSE",
        product="CNC",
        quantity="100",
        pricetype="SL",
        price="2500",
        trigger_price="2450",
        validity="DAY",
        strategy="Ab-654321234-1628190",
    )
    assert await adapter.place_order(_session(), order, _router_token=ROUTER_TOKEN) == "ordinary-resource"
    body = transport.calls[0]["body"]
    assert type(body["price"]) in (int, float) and body["price"] == 2500
    assert type(body["trigger_price"]) in (int, float) and body["trigger_price"] == 2450
    assert body["order_type"] == "SL" and body["order_reference_id"] == "Ab-654321234-1628190"


@pytest.mark.asyncio
@pytest.mark.parametrize("price", ["9007199254740993.01", "1e-1000", "1e1000"])
async def test_actual_adapter_ordinary_decimal_refuses_unrepresentable_json_number_instead_of_rounding(price):
    transport = RecordingTransport()
    adapter = GrowwAdapter(http_factory=lambda: transport)
    order = Order(
        symbol="TCS",
        action="BUY",
        exchange="NSE",
        product="CNC",
        quantity="10",
        pricetype="LIMIT",
        price=price,
        strategy="FlintTest",
    )
    with pytest.raises(BrokerError):
        await adapter.place_order(_session(), order, _router_token=ROUTER_TOKEN)
    assert transport.calls == []
