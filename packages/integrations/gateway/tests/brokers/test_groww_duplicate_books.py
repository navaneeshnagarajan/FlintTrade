"""Ordinary Groww collection identity through the actual adapter/read seams.

All resources and accounts are synthetic observations, not broker eligibility.
Run with normal initialisers/conftests inside the approved offline runtime.
"""

import json
from copy import deepcopy
from urllib.parse import urlsplit

import pytest

from flinttrade_core.broker_read_port import (
    BrokerOrderFamily,
    BrokerReadErrorCode,
    BrokerReadFailure,
    BrokerReadResponseInvalid,
    BrokerReadSuccess,
    OrderStateRequest,
)
from flinttrade_core.exceptions import UnsupportedCapabilityError
from flinttrade_gateway.brokers._base import Session
from flinttrade_gateway.brokers.groww import GrowwAdapter
from packages.integrations.gateway.tests import test_broker_read_concrete_adapters

pytestmark = pytest.mark.unit
# Reuse normal real ownership/session fixtures, not an adapter/provider success mock.
bind_adapter = test_broker_read_concrete_adapters.bind_adapter


def ordinary_row(identifier="opaque-identity", *, segment="CASH", **edits):
    return {
        "groww_order_id": identifier,
        "order_status": "OPEN",
        "trading_symbol": "TCS",
        "exchange": "MCX" if segment == "COMMODITY" else "NSE",
        "segment": segment,
        "transaction_type": "SELL",
        "product": "CNC" if segment == "CASH" else "NRML",
        "order_type": "LIMIT",
        "quantity": 10,
        "filled_quantity": 0,
        **edits,
    }


class BookTransport:
    def __init__(self, pages, *, fills=None, token="synthetic"):
        self.pages = pages
        self.fills = fills or {}
        self.token = token
        self.calls = []

    def __call__(self, method, url, *, headers, params=None, json_body=None):
        assert method == "GET"
        assert urlsplit(url).netloc == "api.groww.in"
        assert json_body is None
        assert headers["Authorization"] == f"Bearer {self.token}"
        assert type(params) is dict
        path = urlsplit(url).path
        if path == "/v1/order/list":
            assert params["page_size"] == 100
            key = (params["segment"], params["page"])
            assert key in self.pages, f"Unregistered synthetic book page: {key}"
            payload = self.pages[key]
        else:
            assert params["page_size"] == 50
            key = (path, params["segment"], params["page"])
            assert key in self.fills, f"Unregistered synthetic fill page: {key}"
            payload = self.fills[key]
        self.calls.append({"path": path, **deepcopy(params)})
        return 200, {"status": "SUCCESS", "payload": deepcopy(payload)}


def adapter_book(pages):
    transport = BookTransport(pages)
    adapter = GrowwAdapter(http_factory=lambda: transport)
    session = Session("synthetic", 4102444800.0, "Synthetic", "groww")
    return adapter, session, transport


@pytest.mark.asyncio
async def test_actual_ordinary_book_refuses_duplicate_resource_identity():
    row = ordinary_row()
    adapter, session, transport = adapter_book(
        {
            ("CASH", 0): {"order_list": [row, deepcopy(row)]},
            ("FNO", 0): {"order_list": []},
            ("COMMODITY", 0): {"order_list": []},
        }
    )

    with pytest.raises(BrokerReadResponseInvalid):
        await adapter.order_book(session)

    assert transport.calls == [{"path": "/v1/order/list", "segment": "CASH", "page": 0, "page_size": 100}]


@pytest.mark.asyncio
async def test_actual_trade_book_refuses_duplicate_discovery_before_reading_fills():
    row = ordinary_row()
    transport = BookTransport(
        {
            ("CASH", 0): {"order_list": [row, deepcopy(row)]},
            ("FNO", 0): {"order_list": []},
            ("COMMODITY", 0): {"order_list": []},
        },
        fills={
            ("/v1/order/trades/opaque-identity", "CASH", 0): {
                "trade_list": [
                    {
                        "groww_order_id": "opaque-identity",
                        "groww_trade_id": "independent-fill",
                        "trading_symbol": "TCS",
                        "exchange": "NSE",
                        "segment": "CASH",
                        "transaction_type": "SELL",
                        "product": "CNC",
                        "quantity": 1,
                        "price": "100.00",
                        "trade_date_time": "2026-10-07T09:30:00+05:30",
                    }
                ],
            },
        },
    )
    adapter = GrowwAdapter(http_factory=lambda: transport)
    session = Session("synthetic", 4102444800.0, "Synthetic", "groww")

    with pytest.raises(BrokerReadResponseInvalid):
        await adapter.trade_book(session)

    assert transport.calls == [
        {"path": "/v1/order/list", "segment": segment, "page": 0, "page_size": 100}
        for segment in ("CASH", "FNO", "COMMODITY")
    ]


def empty_pages():
    return {(segment, 0): {"order_list": []} for segment in ("CASH", "FNO", "COMMODITY")}


@pytest.mark.asyncio
@pytest.mark.parametrize("segment", ["CASH", "FNO", "COMMODITY"])
@pytest.mark.parametrize("method", ["order_book", "trade_book"])
@pytest.mark.parametrize(
    "edits",
    [
        {},
        {"order_status": "CANCELLED"},
        {"order_status": "CANCELLATION_REQUESTED"},
        {"transaction_type": "BUY"},
        {"filled_quantity": 4},
        {"trading_symbol": "UNRELATED"},
    ],
)
async def test_duplicate_ordinary_address_refuses_identical_and_conflicting_rows(segment, method, edits):
    pages = empty_pages()
    first = ordinary_row("repeated-address", segment=segment)
    pages[(segment, 0)] = {
        "order_list": [
            ordinary_row("valid-prefix", segment=segment),
            first,
            {**first, **edits},
        ]
    }
    adapter, session, transport = adapter_book(pages)

    with pytest.raises(BrokerReadResponseInvalid):
        await getattr(adapter, method)(session)

    assert all(call["path"] == "/v1/order/list" for call in transport.calls)
    assert (segment, 0) in [(call["segment"], call["page"]) for call in transport.calls]


@pytest.mark.asyncio
@pytest.mark.parametrize("segment", ["CASH", "FNO", "COMMODITY"])
@pytest.mark.parametrize("method", ["order_book", "trade_book"])
@pytest.mark.parametrize("middle_page", [False, True])
async def test_duplicate_address_across_overlapping_or_nonadjacent_pages_refuses_whole_collection(
    segment,
    method,
    middle_page,
):
    pages = empty_pages()
    pages[(segment, 0)] = {"order_list": [ordinary_row(f"first-{index}", segment=segment) for index in range(100)]}
    if middle_page:
        pages[(segment, 1)] = {"order_list": [ordinary_row(f"middle-{index}", segment=segment) for index in range(100)]}
    last_page = 2 if middle_page else 1
    pages[(segment, last_page)] = {
        "order_list": [
            ordinary_row("last-valid", segment=segment),
            ordinary_row("first-42", segment=segment, filled_quantity=4),
        ]
    }
    adapter, session, transport = adapter_book(pages)

    with pytest.raises(BrokerReadResponseInvalid):
        await getattr(adapter, method)(session)

    assert [call["page"] for call in transport.calls if call["segment"] == segment] == list(range(last_page + 1))
    assert all(call["path"] == "/v1/order/list" for call in transport.calls)


@pytest.mark.asyncio
@pytest.mark.parametrize("segment", ["CASH", "FNO"])
async def test_same_segment_same_id_on_different_exchanges_is_still_one_resource_address(segment):
    pages = empty_pages()
    pages[(segment, 0)] = {
        "order_list": [
            ordinary_row("one-address", segment=segment, exchange="NSE"),
            ordinary_row("one-address", segment=segment, exchange="BSE"),
        ]
    }
    adapter, session, _transport = adapter_book(pages)
    with pytest.raises(BrokerReadResponseInvalid):
        await adapter.order_book(session)


@pytest.mark.asyncio
@pytest.mark.parametrize("method", ["order_book", "trade_book"])
async def test_same_opaque_id_in_different_segments_preserves_separate_resource_addresses(method):
    pages = empty_pages()
    pages[("CASH", 0)] = {"order_list": [ordinary_row("shared-opaque")]}
    pages[("FNO", 0)] = {"order_list": [ordinary_row("shared-opaque", segment="FNO")]}
    fills = {
        ("/v1/order/trades/shared-opaque", segment, 0): {
            "trade_list": [
                {
                    "groww_order_id": "shared-opaque",
                    "groww_trade_id": fill,
                    "trading_symbol": "TCS",
                    "exchange": "NSE",
                    "segment": segment,
                    "transaction_type": "SELL",
                    "product": product,
                    "quantity": 1,
                    "price": "100.00",
                    "trade_date_time": "2026-10-07T09:30:00+05:30",
                }
            ]
        }
        for segment, fill, product in (("CASH", "cash-fill", "CNC"), ("FNO", "fno-fill", "NRML"))
    }
    transport = BookTransport(pages, fills=fills)
    adapter = GrowwAdapter(http_factory=lambda: transport)
    session = Session("synthetic", 4102444800.0, "Synthetic", "groww")
    rows = await getattr(adapter, method)(session)

    assert [row["orderid"] for row in rows] == ["shared-opaque", "shared-opaque"]
    assert [row["exchange"] for row in rows] == ["NSE", "NFO"]
    if method == "trade_book":
        assert [row["tradeid"] for row in rows] == ["cash-fill", "fno-fill"]
        assert [call["segment"] for call in transport.calls[3:]] == ["CASH", "FNO"]
    print("GROWW_DUPLICATE_SEGMENT_CONTROL " + json.dumps({"method": method, "rows": rows, "calls": transport.calls}))


@pytest.mark.asyncio
async def test_distinct_case_sensitive_and_smart_looking_ordinary_ids_keep_full_consumed_fields():
    pages = empty_pages()
    pages[("CASH", 0)] = {
        "order_list": [
            ordinary_row(
                "gtt_same-looking",
                filled_quantity=4,
                remaining_quantity=6,
                price="100.50",
                trigger_price="95",
                average_fill_price="100.25",
                created_at="2026-10-07T09:30:00+05:30",
                remark="partial",
            ),
            ordinary_row("GTT_same-looking", order_status="CANCELLATION_REQUESTED"),
        ]
    }
    adapter, session, _transport = adapter_book(pages)
    rows = await adapter.order_book(session)
    assert rows == [
        {
            "orderid": "gtt_same-looking",
            "status": "PARTIALLY_FILLED",
            "raw_status": "OPEN",
            "symbol": "TCS",
            "exchange": "NSE",
            "action": "SELL",
            "transaction_type": "SELL",
            "product": "CNC",
            "quantity": 10,
            "filled_quantity": 4,
            "remaining_quantity": 6,
            "price": "100.50",
            "trigger_price": "95",
            "average_price": "100.25",
            "order_timestamp": "2026-10-07T09:30:00+05:30",
            "remark": "partial",
            "order_type": "LIMIT",
            "pricetype": "LIMIT",
        },
        {
            "orderid": "GTT_same-looking",
            "status": "CANCEL_PENDING",
            "raw_status": "CANCELLATION_REQUESTED",
            "symbol": "TCS",
            "exchange": "NSE",
            "action": "SELL",
            "transaction_type": "SELL",
            "product": "CNC",
            "quantity": 10,
            "filled_quantity": 0,
            "order_type": "LIMIT",
            "pricetype": "LIMIT",
        },
    ]


@pytest.mark.asyncio
@pytest.mark.parametrize("bad_id", [None, "", "   ", False, 12, [], {}])
async def test_missing_or_malformed_ordinary_identity_cannot_return_a_valid_prefix(bad_id):
    pages = empty_pages()
    pages[("CASH", 0)] = {"order_list": [ordinary_row("valid-prefix"), ordinary_row(bad_id)]}
    adapter, session, _transport = adapter_book(pages)
    with pytest.raises(BrokerReadResponseInvalid):
        await adapter.order_book(session)


@pytest.mark.asyncio
async def test_genuine_empty_books_keep_all_three_explicit_segment_reads():
    adapter, session, transport = adapter_book(empty_pages())
    assert await adapter.order_book(session) == []
    assert transport.calls == [
        {"path": "/v1/order/list", "segment": segment, "page": 0, "page_size": 100}
        for segment in ("CASH", "FNO", "COMMODITY")
    ]


@pytest.mark.asyncio
@pytest.mark.parametrize("defect", ["duplicate-active", "duplicate-terminal", "duplicate-pending", "later-duplicate"])
async def test_real_managed_port_refuses_duplicate_whole_collection(bind_adapter, defect):
    pages = empty_pages()
    status = {
        "duplicate-active": "OPEN",
        "duplicate-terminal": "CANCELLED",
        "duplicate-pending": "CANCELLATION_REQUESTED",
        "later-duplicate": "OPEN",
    }[defect]
    row = ordinary_row("duplicate-address", order_status=status)
    if defect == "later-duplicate":
        pages[("CASH", 0)] = {"order_list": [row, *[ordinary_row(f"first-{index}") for index in range(99)]]}
        pages[("CASH", 1)] = {"order_list": [ordinary_row("valid-next"), deepcopy(row)]}
    else:
        pages[("CASH", 0)] = {"order_list": [row, deepcopy(row)]}
    transport = BookTransport(pages, token="synthetic-token")
    bound = bind_adapter("groww", GrowwAdapter(http_factory=lambda: transport), transport)
    result = await bound.port.order_states(OrderStateRequest(BrokerOrderFamily.REGULAR))
    assert result == BrokerReadFailure(BrokerReadErrorCode.MALFORMED_RESPONSE)
    assert all(call["path"] == "/v1/order/list" for call in transport.calls)
    print(
        "GROWW_DUPLICATE_BOUND_REFUSAL "
        + json.dumps({"defect": defect, "code": result.code.name, "calls": transport.calls})
    )


@pytest.mark.asyncio
@pytest.mark.parametrize("empty_segment", [None, "CASH", "FNO", "COMMODITY", "ALL"])
async def test_real_managed_port_preserves_valid_all_segment_union_and_genuine_empties(bind_adapter, empty_segment):
    pages = empty_pages()
    native = [
        ordinary_row("cash-resource", filled_quantity=4, remaining_quantity=6, price="100.50"),
        ordinary_row("fno-resource", segment="FNO", order_status="CANCELLATION_REQUESTED"),
        ordinary_row("commodity-resource", segment="COMMODITY", order_status="TRIGGER_PENDING"),
    ]
    for row in native:
        if empty_segment != "ALL" and row["segment"] != empty_segment:
            pages[(row["segment"], 0)] = {"order_list": [row]}
    transport = BookTransport(pages, token="synthetic-token")
    bound = bind_adapter("groww", GrowwAdapter(http_factory=lambda: transport), transport)
    result = await bound.port.order_states(OrderStateRequest(BrokerOrderFamily.REGULAR))
    assert type(result) is BrokerReadSuccess
    assert result.provenance.selector == bound.selector
    expected_ids = {
        None: ("cash-resource", "fno-resource", "commodity-resource"),
        "CASH": ("fno-resource", "commodity-resource"),
        "FNO": ("cash-resource", "commodity-resource"),
        "COMMODITY": ("cash-resource", "fno-resource"),
        "ALL": (),
    }[empty_segment]
    assert tuple(row.orderid for row in result.value) == expected_ids
    expected = {
        "cash-resource": ("NSE", "CNC", "PARTIALLY_FILLED", "10", "4"),
        "fno-resource": ("NFO", "NRML", "CANCEL_PENDING", "10", "0"),
        "commodity-resource": ("MCX", "NRML", "TRIGGER_PENDING", "10", "0"),
    }
    for row in result.value:
        assert (row.exchange, row.product, row.status, row.quantity, row.filled_quantity) == expected[row.orderid]
        if row.orderid == "cash-resource":
            assert row.remaining_quantity == "6" and row.price == "100.50"
    assert transport.calls == [
        {"path": "/v1/order/list", "segment": segment, "page": 0, "page_size": 100}
        for segment in ("CASH", "FNO", "COMMODITY")
    ]
    print(
        "GROWW_DUPLICATE_BOUND_SUCCESS "
        + json.dumps({"ids": expected_ids, "empty_segment": empty_segment, "calls": transport.calls})
    )


@pytest.mark.asyncio
@pytest.mark.parametrize("family", ["GTT", "OCO"])
@pytest.mark.parametrize("segment", ["CASH", "FNO"])
async def test_smart_duplicate_page_remains_incomplete_and_preserves_opaque_children(family, segment):
    native = {
        "smart_order_id": "same-opaque-parent",
        "smart_order_type": family,
        "segment": segment,
        "status": "ACTIVE",
        "child_legs": {"opaque": [{"groww_order_id": "opaque-child", "status": "CANCELLATION_REQUESTED"}]},
    }
    calls = []

    def transport(method, url, *, headers, params=None, json_body=None):
        assert method == "GET" and urlsplit(url).path == "/v1/order-advance/list"
        assert json_body is None and headers["Authorization"] == "Bearer synthetic"
        calls.append(deepcopy(params))
        return 200, {"status": "SUCCESS", "payload": {"orders": [native, deepcopy(native)]}}

    adapter = GrowwAdapter(http_factory=lambda: transport)
    session = Session("synthetic", 4102444800.0, "Synthetic", "groww")
    result = await adapter.smart_orders_page(
        session,
        segment=segment,
        smart_order_type=family,
        status="ACTIVE",
        start_date_time="2026-10-01T00:00:00",
        end_date_time="2026-10-07T23:59:59",
        page=2,
        page_size=50,
    )
    assert result["complete"] is False
    assert len(result["orders"]) == 2
    assert [row["native"] for row in result["orders"]] == [native, native]
    assert [row["status"] for row in result["orders"]] == ["ARMED", "ARMED"]
    assert (
        result["scope"]
        == calls[0]
        == {
            "segment": segment,
            "smart_order_type": family,
            "status": "ACTIVE",
            "page": 2,
            "page_size": 50,
            "start_date_time": "2026-10-01T00:00:00",
            "end_date_time": "2026-10-07T23:59:59",
        }
    )
    result["orders"][0]["native"]["child_legs"]["opaque"][0]["status"] = "mutated"
    assert native["child_legs"]["opaque"][0]["status"] == "CANCELLATION_REQUESTED"
    assert result["orders"][1]["native"] == native
    with pytest.raises(UnsupportedCapabilityError):
        await adapter.smart_orders(session)
    assert len(calls) == 1
