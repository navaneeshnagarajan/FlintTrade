"""INDstocks parent/leg numeric evidence at the actual legacy read seams.

Complete rows below explicitly supply every material observation. They are
synthetic controls, not a promise that the ordinary API supplies a parent zero.
First-party normal_orders response notes distinguish empty smart-leg values;
smart_orders defines the parent trigger separately from each protective leg.
"""
from __future__ import annotations

from typing import Any

import pytest

from flinttrade_core.broker_read_port import BrokerReadResponseInvalid
from flinttrade_gateway.brokers import indmoney_mapping
from flinttrade_gateway.brokers._base import Session
from flinttrade_gateway.brokers.indmoney import IndMoneyAdapter
from flinttrade_gateway.reconciliation import (
    EMPTY_LOCAL_STATE,
    SEVERITY_CRITICAL,
    LocalStateSnapshot,
    ReconciliationReport,
    declare_unavailable_order_fields,
)

pytestmark = pytest.mark.unit

_NUMERIC_FIELDS = (
    ("requested_qty", "quantity"),
    ("traded_qty", "filled_quantity"),
    ("requested_price", "price"),
    ("traded_price", "average_price"),
    ("trigger_price", "trigger_price"),
    ("trigger_limit_price", "trigger_limit_price"),
    ("sl_trigger_price", "sl_trigger_price"),
    ("sl_limit_price", "sl_limit_price"),
    ("tgt_trigger_price", "tgt_trigger_price"),
    ("tgt_limit_price", "tgt_limit_price"),
)
_MATERIAL_FIELDS = _NUMERIC_FIELDS[:5]
_COMPLETE_ROW = {
    "id": "EQ-SYNTHETIC",
    "status": "INITIATED",
    "name": "SYNTHETIC",
    "exchange": "NSE",
    "segment": "EQUITY",
    "txn_type": "BUY",
    "order_type": "TRIGGER",
    "product": "CNC",
    "security_id": "123",
    "requested_qty": 5,
    "traded_qty": 0,
    "requested_price": "102",
    "traded_price": "0",
    "trigger_price": "101",
    "trigger_limit_price": "102",
    "sl_trigger_price": "90",
    "sl_limit_price": "89",
    "tgt_trigger_price": "110",
    "tgt_limit_price": "111",
}
_ABSENCES = ("absent", "null", "blank", "whitespace")
_READ_LEDGER = [
    ("/order-book", None),
    ("/portfolio/positions", {"segment": "derivative", "product": "margin"}),
    ("/portfolio/positions", {"segment": "derivative", "product": "intraday"}),
    ("/portfolio/positions", {"segment": "equity", "product": "cnc"}),
    ("/portfolio/positions", {"segment": "equity", "product": "intraday"}),
    ("/portfolio/holdings", None),
]


def _with_absence(row: dict[str, Any], field: str, absence: str) -> dict[str, Any]:
    result = dict(row)
    if absence == "absent":
        result.pop(field)
    else:
        result[field] = {"null": None, "blank": "", "whitespace": "  "}[absence]
    return result


def _adapter(rows: list[dict[str, Any]]):
    calls = []
    holder = {"local": EMPTY_LOCAL_STATE}

    def transport(method, url, *, headers, params=None, json_body=None):
        assert method == "GET"
        assert url.startswith(indmoney_mapping.BASE_URL + "/")
        assert headers == {"Authorization": "SYNTHETIC", "Content-Type": "application/json"}
        assert json_body is None
        path = url.removeprefix(indmoney_mapping.BASE_URL)
        calls.append((path, params))
        if path == "/order-book":
            assert params is None
            data = rows
        elif path == "/portfolio/positions":
            assert (path, params) in _READ_LEDGER
            data = {"net_positions": [], "day_positions": []}
        elif path == "/portfolio/holdings":
            assert params is None
            data = []
        else:
            raise AssertionError(f"Unregistered inert transport invocation: {path}")
        return 200, {"status": "success", "data": data}

    adapter = IndMoneyAdapter(http_factory=lambda: transport, local_state_provider=lambda _session: holder["local"])
    session = Session("SYNTHETIC", 4102444800.0, "OBSERVATION-OFFLINE", "indmoney")
    return adapter, session, holder, calls


def _assert_unknown_report(report: ReconciliationReport, error_prefix: str) -> None:
    assert report.error.startswith(error_prefix)
    assert not report.clean and report.severity == SEVERITY_CRITICAL
    assert report.orders_diff == report.positions_diff == report.holdings_diff == ()
    assert report.broker_orders == report.broker_positions == report.broker_holdings == ()
    assert report.local_state == EMPTY_LOCAL_STATE
    assert report._evidence_sha256 == ""  # noqa: SLF001 - unknown evidence must not acquire a report binding
    assert report.as_dict()["clean"] is False
    assert {"broker_orders", "broker_positions", "broker_holdings", "local_state"}.isdisjoint(report.as_dict())


@pytest.mark.parametrize(("source", "target"), _NUMERIC_FIELDS)
@pytest.mark.parametrize("absence", _ABSENCES)
def test_each_native_number_keeps_absence_without_borrowing_parent_or_leg_evidence(source, target, absence):
    raw = _with_absence(_COMPLETE_ROW, source, absence)
    observed = indmoney_mapping.from_indmoney_order(raw)
    assert target not in observed
    for other_source, other_target in _NUMERIC_FIELDS:
        if other_source != source:
            assert observed[other_target] == str(_COMPLETE_ROW[other_source])
    if absence == "absent":
        assert source not in raw
    else:
        assert raw[source] == {"null": None, "blank": "", "whitespace": "  "}[absence]


@pytest.mark.parametrize(("source", "target"), _NUMERIC_FIELDS)
@pytest.mark.parametrize(("value", "expected"), [(0, "0"), (0.0, "0.0"), ("0", "0"), ("0.00", "0.00")])
def test_each_supplied_native_zero_is_retained_exactly_without_truthiness_fallback(source, target, value, expected):
    raw = {**_COMPLETE_ROW, source: value}
    observed = indmoney_mapping.from_indmoney_order(raw)
    assert observed[target] == expected
    for other_source, other_target in _NUMERIC_FIELDS:
        if other_source != source:
            assert observed[other_target] == str(_COMPLETE_ROW[other_source])
    assert type(raw[source]) is type(value) and raw[source] == value


@pytest.mark.asyncio
@pytest.mark.parametrize(("source", "target"), _MATERIAL_FIELDS)
@pytest.mark.parametrize("absence", _ABSENCES)
async def test_same_incomplete_local_mirror_cannot_make_missing_numeric_broker_evidence_clean(source, target, absence):
    raw = _with_absence(_COMPLETE_ROW, source, absence)
    adapter, session, holder, calls = _adapter([raw])
    rows = await adapter.order_book(session)
    assert target not in rows[0]
    holder["local"] = LocalStateSnapshot(
        orders=declare_unavailable_order_fields(rows, fields=("variety", "validity", "strategy")),
    )

    report = await adapter.reconcile(session)

    _assert_unknown_report(report, f"invalid reconciliation input: broker orders row 0 missing {target}")
    assert calls == [("/order-book", None), *_READ_LEDGER]


@pytest.mark.asyncio
@pytest.mark.parametrize(("source", "target"), _NUMERIC_FIELDS)
@pytest.mark.parametrize("value", ["not-a-number", "NaN", "Infinity", True, []],
                         ids=["malformed-text", "nan", "infinity", "boolean", "container"])
async def test_each_malformed_native_number_refuses_the_whole_book_without_a_valid_prefix(source, target, value):
    raw = {**_COMPLETE_ROW, source: value}
    with pytest.raises(BrokerReadResponseInvalid) as mapped_error:
        indmoney_mapping.from_indmoney_order(raw)
    assert type(mapped_error.value) is BrokerReadResponseInvalid
    adapter, session, _holder, calls = _adapter([{**_COMPLETE_ROW, "id": "EQ-VALID-PREFIX"}, raw])
    with pytest.raises(BrokerReadResponseInvalid) as read_error:
        await adapter.order_book(session)
    assert type(read_error.value) is BrokerReadResponseInvalid

    report = await adapter.reconcile(session)

    _assert_unknown_report(report, "broker fetch failed:")
    assert calls == [("/order-book", None), ("/order-book", None)]
    assert raw[source] is value


@pytest.mark.asyncio
@pytest.mark.parametrize("parent", ["101", 0, "0.00"])
async def test_real_read_and_clean_report_retain_independent_parent_and_stop_target_prices(parent):
    raw = {**_COMPLETE_ROW, "trigger_price": parent}
    adapter, session, holder, calls = _adapter([raw])
    rows = await adapter.order_book(session)
    assert rows[0]["trigger_price"] == str(parent)
    assert rows[0]["sl_trigger_price"] == "90"
    assert rows[0]["tgt_trigger_price"] == "110"
    holder["local"] = LocalStateSnapshot(
        orders=declare_unavailable_order_fields(rows, fields=("variety", "validity", "strategy")),
    )

    report = await adapter.reconcile(session)

    assert report.clean and report.error == ""
    assert report.broker_orders[0]["trigger_price"] == str(parent)
    assert report.broker_orders[0]["sl_trigger_price"] == "90"
    assert report.broker_orders[0]["tgt_trigger_price"] == "110"
    assert report.broker_orders == report.local_state.orders
    assert report.broker_orders[0]["price_type"] == "TRIGGER"
    assert holder["local"].orders[0]["pricetype"] == "TRIGGER"
    assert "pricetype" not in report.broker_orders[0]
    assert report._evidence_sha256  # noqa: SLF001 - complete exact evidence acquires the existing private binding
    assert calls == [("/order-book", None), *_READ_LEDGER]


@pytest.mark.asyncio
async def test_documented_ordinary_response_without_parent_trigger_remains_unknown_not_synthetic_clean():
    # First-party normal_orders Get Order Book ordinary sample, synthetic identity.
    raw = {"id": "DRV-SYNTHETIC", "status": "SUCCESS", "name": "SYNTHETIC", "exchange": "NSE",
           "segment": "DERIVATIVE", "product": "MARGIN", "txn_type": "BUY", "order_type": "MARKET",
           "requested_qty": 75, "traded_qty": 75, "requested_price": "43.55", "traded_price": "43.55",
           "sl_trigger_price": "", "sl_limit_price": "", "tgt_trigger_price": "", "tgt_limit_price": "",
           "validity": "DAY"}
    adapter, session, holder, calls = _adapter([raw])
    rows = await adapter.order_book(session)
    assert {"trigger_price", "sl_trigger_price", "sl_limit_price", "tgt_trigger_price", "tgt_limit_price"}.isdisjoint(
        rows[0],
    )
    holder["local"] = LocalStateSnapshot(
        orders=declare_unavailable_order_fields(rows, fields=("variety", "validity", "strategy")),
    )

    report = await adapter.reconcile(session)

    _assert_unknown_report(report, "invalid reconciliation input: broker orders row 0 missing trigger_price")
    assert calls == [("/order-book", None), *_READ_LEDGER]
    assert "trigger_price" not in raw and raw["sl_trigger_price"] == ""


@pytest.mark.asyncio
async def test_genuine_complete_empty_books_remain_distinct_from_unavailable_numeric_evidence():
    adapter, session, _holder, calls = _adapter([])

    report = await adapter.reconcile(session)

    assert report.clean and report.error == ""
    assert report.broker_orders == report.broker_positions == report.broker_holdings == ()
    assert report.local_state == EMPTY_LOCAL_STATE
    assert report._evidence_sha256  # noqa: SLF001 - an observed genuine empty book has a private evidence binding
    assert calls == _READ_LEDGER
