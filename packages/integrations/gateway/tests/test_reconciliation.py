"""Reconciliation-wave tests (contract §14): the pure diff model in
``flinttrade_gateway.reconciliation`` plus every native adapter's ``reconcile()``
happy path (fakes via the established client_factory/transport injections).
"""

from __future__ import annotations

import dataclasses
import json
from datetime import datetime, timezone
from typing import Any

import pytest

from flinttrade_core.exceptions import BrokerError
from flinttrade_gateway import reconciliation as reconciliation_module
from flinttrade_gateway.brokers import (
    dhan_mapping,
    groww_mapping,
    indmoney_mapping,
    kotakneo_mapping,
    upstox_mapping,
)
from flinttrade_gateway.brokers._base import Session
from flinttrade_gateway.brokers.dhan import DhanAdapter
from flinttrade_gateway.brokers.indmoney import IndMoneyAdapter
from flinttrade_gateway.brokers.kotakneo import KotakNeoAdapter
from flinttrade_gateway.brokers.upstox import UpstoxAdapter
from flinttrade_gateway.reconciliation import (
    DISCREPANCY_ONLY_IN_FLINTTRADE,
    DISCREPANCY_ONLY_ON_BROKER,
    DISCREPANCY_QTY_MISMATCH,
    DISCREPANCY_STATUS_MISMATCH,
    EMPTY_LOCAL_STATE,
    SEVERITY_CRITICAL,
    SEVERITY_WARNING,
    LocalStateSnapshot,
    ReconciliationReport,
    build_report,
    declare_unavailable_order_fields,
)

pytestmark = pytest.mark.unit

_NOW = datetime(2026, 6, 12, 9, 30, tzinfo=timezone.utc)


# ---------------------------------------------------------------------------
# Row helpers (the adapters' normalised read shapes)
# ---------------------------------------------------------------------------


def _order(
    oid: str = "O1", status: str = "open", symbol: str = "TCS", qty: str = "5", filled: str = "0", **extra: Any
) -> dict[str, Any]:
    row = {
        "orderid": oid,
        "status": status,
        "symbol": symbol,
        "exchange": "NSE",
        "product": "CNC",
        "action": "BUY",
        "quantity": qty,
        "filled_quantity": filled,
        "price": "2500",
        "trigger_price": "0",
        "price_type": "LIMIT",
        "variety": "regular",
        "validity": "DAY",
        "strategy": "Flint",
        "average_price": "0",
    }
    row.update(extra)
    return row


def _pos(symbol: str = "TCS", qty: str = "5", exchange: str = "NSE", product: str = "CNC") -> dict[str, Any]:
    return {"symbol": symbol, "exchange": exchange, "product": product, "quantity": qty}


def _hold(symbol: str = "INFY", qty: str = "10", exchange: str = "NSE") -> dict[str, Any]:
    return {"symbol": symbol, "exchange": exchange, "quantity": qty}


def _report(**kw: Any) -> ReconciliationReport:
    base: dict[str, Any] = {"adapter_id": "dhan", "account_id": "A1", "generated_at": _NOW}
    base.update(kw)
    return build_report(**base)


def _assert_input_error(report: ReconciliationReport, fragment: str) -> None:
    assert report.error.startswith("invalid reconciliation input:")
    assert fragment in report.error
    assert report.severity == SEVERITY_CRITICAL
    assert not report.clean
    assert report.orders_diff == () and report.positions_diff == () and report.holdings_diff == ()
    assert report.broker_orders == () and report.broker_positions == () and report.broker_holdings == ()
    assert report.local_state == EMPTY_LOCAL_STATE
    assert report._evidence_sha256 == ""  # noqa: SLF001 - error reports retain no private evidence
    assert {"broker_orders", "broker_positions", "broker_holdings", "local_state"}.isdisjoint(report.as_dict())


class _ModelDumpOrder:
    def model_dump(self) -> dict[str, Any]:
        return _order()


class _LegacyDictOrder:
    def dict(self) -> dict[str, Any]:
        return _order()


class _PairIterableOrder:
    def __iter__(self):
        return iter(_order().items())


class _ExplodingQuantity:
    def __float__(self) -> float:
        raise RuntimeError("cannot convert")


class _ExplodingModelDumpAttribute:
    @property
    def model_dump(self):
        raise RuntimeError("cannot inspect")


class _ExplodingValueAttribute:
    @property
    def value(self):
        raise RuntimeError("cannot inspect value")


@dataclasses.dataclass
class _ObjectOrder:
    orderid: str = "O1"
    status: str = "open"
    symbol: str = "TCS"
    exchange: str = "NSE"
    product: str = "CNC"
    action: str = "BUY"
    quantity: str = "5"
    filled_quantity: str = "0"
    price: str = "2500"
    trigger_price: str = "0"
    price_type: str = "LIMIT"
    variety: str = "regular"
    validity: str = "DAY"
    strategy: str = "Flint"
    average_price: str = "0"


# ---------------------------------------------------------------------------
# Pure diff model
# ---------------------------------------------------------------------------


def test_identical_state_is_clean() -> None:
    local = LocalStateSnapshot(orders=(_order(),), positions=(_pos(),), holdings=(_hold(),))
    report = _report(broker_orders=[_order()], broker_positions=[_pos()], broker_holdings=[_hold()], local_state=local)
    assert report.clean
    assert report.severity == ""
    assert report.severity_counts == {"info": 0, "warning": 0, "critical": 0}
    assert report.adapter_id == "dhan" and report.account_id == "A1"
    assert report.generated_at is _NOW


def test_broker_only_order_is_warning() -> None:
    report = _report(broker_orders=[_order(oid="O9", status="complete")])
    (diff,) = report.orders_diff
    assert diff.order_id == "O9"
    assert diff.discrepancy == DISCREPANCY_ONLY_ON_BROKER
    assert diff.severity == SEVERITY_WARNING
    assert diff.broker_status == "COMPLETE" and diff.flinttrade_status == ""
    assert not report.clean


def test_local_only_order_is_critical() -> None:
    local = LocalStateSnapshot(orders=(_order(oid="GHOST", status="open"),))
    report = _report(local_state=local)
    (diff,) = report.orders_diff
    assert diff.discrepancy == DISCREPANCY_ONLY_IN_FLINTTRADE
    assert diff.severity == SEVERITY_CRITICAL
    assert diff.flinttrade_status == "OPEN"


def test_order_status_comparison_is_case_insensitive() -> None:
    local = LocalStateSnapshot(orders=(_order(status="OPEN"),))
    report = _report(broker_orders=[_order(status="open")], local_state=local)
    assert report.clean


@pytest.mark.parametrize(
    ("broker_status", "local_status", "canonical"),
    [
        pytest.param("NEW", "pending", "OPEN", id="open"),
        pytest.param("PARTIALLY_EXECUTED", "partially filled", "PARTIALLY_FILLED", id="partial"),
        pytest.param("CANCELLATION_REQUESTED", "cancel_pending", "CANCEL_PENDING", id="cancel-pending"),
        pytest.param("CLOSED", "closed", "CLOSED", id="closed"),
        pytest.param("EXECUTED", "complete", "COMPLETE", id="complete"),
    ],
)
def test_order_status_aliases_normalise_without_losing_lifecycle_semantics(
    broker_status: str,
    local_status: str,
    canonical: str,
) -> None:
    local = LocalStateSnapshot(orders=(_order(status=local_status),))
    report = _report(broker_orders=[_order(status=broker_status)], local_state=local)

    assert report.clean
    assert report.error == ""
    assert report.broker_orders[0]["status"] == broker_status
    assert reconciliation_module.normalise_order_status(broker_status) == canonical
    assert reconciliation_module.normalise_order_status(local_status) == canonical


def test_order_status_normaliser_infers_partial_without_masking_stronger_states() -> None:
    normalise = reconciliation_module.normalise_order_status

    assert normalise("open", quantity=5.0, filled_quantity=2.0) == "PARTIALLY_FILLED"
    assert normalise("cancellation requested", quantity=5.0, filled_quantity=2.0) == "CANCEL_PENDING"
    assert normalise("closed", quantity=5.0, filled_quantity=5.0) == "CLOSED"
    assert normalise("future broker state", quantity=5.0, filled_quantity=0.0) == "UNKNOWN"


def test_closed_status_does_not_compare_equal_to_complete() -> None:
    local = LocalStateSnapshot(orders=(_order(status="complete"),))
    report = _report(broker_orders=[_order(status="closed")], local_state=local)

    (diff,) = report.orders_diff
    assert diff.discrepancy == DISCREPANCY_STATUS_MISMATCH
    assert diff.flinttrade_status == "COMPLETE"
    assert diff.broker_status == "CLOSED"


def test_unknown_order_status_is_visible_and_not_equal_to_known_status() -> None:
    local = LocalStateSnapshot(orders=(_order(status="open"),))
    report = _report(broker_orders=[_order(status="future broker state")], local_state=local)

    (diff,) = report.orders_diff
    assert diff.discrepancy == DISCREPANCY_STATUS_MISMATCH
    assert diff.flinttrade_status == "OPEN"
    assert diff.broker_status == "UNKNOWN"


def test_order_status_mismatch_is_warning() -> None:
    local = LocalStateSnapshot(orders=(_order(status="open"),))
    report = _report(broker_orders=[_order(status="complete")], local_state=local)
    (diff,) = report.orders_diff
    assert diff.discrepancy == DISCREPANCY_STATUS_MISMATCH
    assert diff.severity == SEVERITY_WARNING
    assert diff.flinttrade_status == "OPEN" and diff.broker_status == "COMPLETE"


def test_order_qty_mismatch_detail_names_both_fields() -> None:
    local = LocalStateSnapshot(orders=(_order(qty="5", filled="0"),))
    report = _report(broker_orders=[_order(qty="10", filled="10")], local_state=local)
    (diff,) = report.orders_diff
    assert diff.discrepancy == DISCREPANCY_QTY_MISMATCH
    assert "quantity: flinttrade=5 broker=10" in diff.detail
    assert "filled_quantity: flinttrade=0 broker=10" in diff.detail


def test_order_status_and_qty_mismatch_coexist() -> None:
    local = LocalStateSnapshot(orders=(_order(status="open", filled="0"),))
    report = _report(broker_orders=[_order(status="complete", filled="5")], local_state=local)
    assert {d.discrepancy for d in report.orders_diff} == {
        DISCREPANCY_STATUS_MISMATCH,
        DISCREPANCY_QTY_MISMATCH,
    }


def test_position_qty_mismatch_is_critical() -> None:
    local = LocalStateSnapshot(positions=(_pos(qty="5"),))
    report = _report(broker_positions=[_pos(qty="3")], local_state=local)
    (diff,) = report.positions_diff
    assert diff.discrepancy == DISCREPANCY_QTY_MISMATCH
    assert diff.severity == SEVERITY_CRITICAL
    assert diff.flinttrade_qty == 5.0 and diff.broker_qty == 3.0


def test_position_missing_either_side_is_critical() -> None:
    local = LocalStateSnapshot(positions=(_pos(symbol="GHOST"),))
    report = _report(broker_positions=[_pos(symbol="REAL")], local_state=local)
    by_symbol = {d.symbol: d for d in report.positions_diff}
    assert by_symbol["REAL"].discrepancy == DISCREPANCY_ONLY_ON_BROKER
    assert by_symbol["GHOST"].discrepancy == DISCREPANCY_ONLY_IN_FLINTTRADE
    assert all(d.severity == SEVERITY_CRITICAL for d in report.positions_diff)


def test_flat_positions_are_not_discrepancies() -> None:
    # A closed (qty 0) row broker-side and no local row both mean "flat".
    report = _report(broker_positions=[_pos(qty="0")])
    assert report.clean


def test_position_key_includes_product() -> None:
    # Same scrip under MIS vs CNC are different positions, not a qty mismatch.
    local = LocalStateSnapshot(positions=(_pos(product="MIS"),))
    report = _report(broker_positions=[_pos(product="CNC")], local_state=local)
    assert {d.discrepancy for d in report.positions_diff} == {
        DISCREPANCY_ONLY_ON_BROKER,
        DISCREPANCY_ONLY_IN_FLINTTRADE,
    }


def test_holdings_discrepancies_are_warnings() -> None:
    local = LocalStateSnapshot(holdings=(_hold(qty="10"),))
    report = _report(broker_holdings=[_hold(qty="8")], local_state=local)
    (diff,) = report.holdings_diff
    assert diff.discrepancy == DISCREPANCY_QTY_MISMATCH
    assert diff.severity == SEVERITY_WARNING


def test_severity_is_worst_across_surfaces_and_counts_add_up() -> None:
    report = _report(
        broker_orders=[_order(oid="O9")],  # warning
        broker_positions=[_pos(symbol="REAL")],  # critical
        broker_holdings=[_hold(symbol="HODL")],  # warning
    )
    assert report.severity == SEVERITY_CRITICAL
    assert report.severity_counts == {"info": 0, "warning": 2, "critical": 1}


def test_error_short_circuits_diffs() -> None:
    report = _report(broker_orders=[_order()], error="broker fetch failed: boom")
    assert report.error == "broker fetch failed: boom"
    assert report.orders_diff == () and report.positions_diff == () and report.holdings_diff == ()
    assert report.broker_orders == () and report.broker_positions == () and report.broker_holdings == ()
    assert report.local_state == EMPTY_LOCAL_STATE
    assert report._evidence_sha256 == ""  # noqa: SLF001 - error reports retain no private evidence
    assert not report.clean
    assert report.severity == SEVERITY_CRITICAL


def test_report_is_frozen() -> None:
    report = _report()
    with pytest.raises(dataclasses.FrozenInstanceError):
        report.error = "mutated"  # type: ignore[misc]


def test_as_dict_is_json_serialisable() -> None:
    local = LocalStateSnapshot(orders=(_order(status="open"),))
    report = _report(broker_orders=[_order(status="complete")], local_state=local)
    payload = json.loads(json.dumps(report.as_dict()))
    assert payload["adapter_id"] == "dhan"
    assert payload["generated_at"] == _NOW.isoformat()
    assert payload["clean"] is False
    assert payload["orders_diff"][0]["discrepancy"] == DISCREPANCY_STATUS_MISMATCH


def test_report_retains_validated_snapshots_without_exposing_them_in_payload() -> None:
    order = _order(status="complete")
    position = _pos()
    holding = _hold()
    local = LocalStateSnapshot(
        orders=(_order(status="open"),),
        positions=(_pos(qty="4"),),
        holdings=(_hold(qty="9"),),
    )

    report = _report(
        broker_orders=[order],
        broker_positions=[position],
        broker_holdings=[holding],
        local_state=local,
    )

    assert report.broker_orders == (order,)
    assert report.broker_positions == (position,)
    assert report.broker_holdings == (holding,)
    assert report.local_state == local
    assert report.local_state is not local
    assert "broker_orders" not in report.as_dict()
    assert "broker_positions" not in report.as_dict()
    assert "broker_holdings" not in report.as_dict()
    assert "local_state" not in report.as_dict()


def test_report_evidence_is_deeply_immutable_and_detached_from_source_rows() -> None:
    source = _order(metadata={"labels": ["original"]})
    report = _report(broker_orders=[source])

    source["price"] = "2600"
    source["metadata"]["labels"][0] = "mutated"

    assert report.broker_orders[0]["price"] == "2500"
    assert report.broker_orders[0]["metadata"]["labels"] == ("original",)
    with pytest.raises(TypeError):
        report.broker_orders[0]["price"] = "2600"  # type: ignore[index]
    with pytest.raises(TypeError):
        report.broker_orders[0]["metadata"]["new"] = True  # type: ignore[index]


@pytest.mark.parametrize(
    ("metadata", "fragment"),
    [
        ({"valid": "value", 1: "invalid"}, "non-string object key"),
        ({"value": float("nan")}, "non-finite number"),
        ({"value": _ExplodingValueAttribute()}, "value could not be read"),
    ],
)
def test_non_json_nested_evidence_fails_closed(metadata: dict[Any, Any], fragment: str) -> None:
    report = _report(broker_orders=[_order(metadata=metadata)])

    _assert_input_error(report, fragment)


def test_cyclic_nested_evidence_fails_closed() -> None:
    metadata: dict[str, Any] = {}
    metadata["self"] = metadata

    report = _report(broker_orders=[_order(metadata=metadata)])

    _assert_input_error(report, "cyclic JSON value")


def test_evidence_binding_is_stable_across_input_row_order_and_private() -> None:
    first_order = _order(oid="B")
    reordered_first = dict(reversed(tuple(first_order.items())))
    first = _report(broker_orders=[first_order, _order(oid="A")])
    second = _report(broker_orders=[_order(oid="A"), reordered_first])

    assert first._evidence_sha256  # noqa: SLF001 - private contract exercised at its trust boundary
    assert first._evidence_sha256 == second._evidence_sha256  # noqa: SLF001
    assert "evidence" not in json.dumps(first.as_dict()).casefold()


def test_diffs_are_deterministic_and_sorted() -> None:
    broker = [_order(oid="B"), _order(oid="A"), _order(oid="C")]
    first = _report(broker_orders=broker)
    second = _report(broker_orders=list(reversed(broker)))
    assert first == second
    assert [d.order_id for d in first.orders_diff] == ["A", "B", "C"]


def test_rows_without_order_id_fail_closed() -> None:
    report = _report(broker_orders=[{"status": "open", "symbol": "TCS"}])
    _assert_input_error(report, "missing order id")


@pytest.mark.parametrize(
    "row",
    [_order(), _ModelDumpOrder(), _LegacyDictOrder(), _PairIterableOrder(), _ObjectOrder()],
    ids=["mapping", "model-dump", "legacy-dict", "dict-conversion", "object-attributes"],
)
def test_supported_row_objects_convert_without_type_errors(row: Any) -> None:
    local = LocalStateSnapshot(orders=(row,))  # type: ignore[arg-type]
    report = _report(broker_orders=[row], local_state=local)

    assert report.clean
    assert report.error == ""
    assert report.broker_orders == (_order(),)
    assert report.local_state.orders == (_order(),)


@pytest.mark.parametrize(
    "row",
    [None, object(), 7, "not-a-row", _ExplodingModelDumpAttribute()],
    ids=["none", "object", "integer", "string", "exploding-protocol"],
)
@pytest.mark.parametrize("side", ["broker", "local"])
def test_invalid_row_objects_fail_closed_without_raw_type_errors(row: Any, side: str) -> None:
    if side == "broker":
        report = _report(broker_orders=[row])
    else:
        report = _report(local_state=LocalStateSnapshot(orders=(row,)))  # type: ignore[arg-type]

    _assert_input_error(report, f"{side} orders row 0 is not a valid row object")


_MALFORMED_ROWS = [
    pytest.param("orders", {**_order(), "orderid": "  "}, "missing order id", id="blank-order-id"),
    pytest.param(
        "orders",
        {key: value for key, value in _order().items() if key != "status"},
        "missing status",
        id="missing-status",
    ),
    pytest.param("orders", {**_order(), "status": "  "}, "missing status", id="blank-status"),
    pytest.param(
        "orders",
        {key: value for key, value in _order().items() if key != "quantity"},
        "missing quantity",
        id="missing-order-quantity",
    ),
    pytest.param("orders", _order(qty="nan"), "quantity must be finite", id="nan-order-quantity"),
    pytest.param("orders", _order(qty="inf"), "quantity must be finite", id="infinite-order-quantity"),
    pytest.param(
        "orders",
        _order(qty=_ExplodingQuantity()),
        "quantity must be finite",
        id="unconvertible-order-quantity",
    ),
    pytest.param("orders", _order(qty="-1"), "quantity must not be negative", id="negative-order-quantity"),
    pytest.param("orders", _order(filled="nan"), "filled_quantity must be finite", id="nan-filled-quantity"),
    pytest.param("orders", _order(filled="-1"), "filled_quantity must not be negative", id="negative-filled-quantity"),
    pytest.param("orders", _order(qty="5", filled="6"), "filled_quantity exceeds quantity", id="overfilled-order"),
    pytest.param(
        "orders",
        _order(qty="5", filled="5.0000000001"),
        "filled_quantity exceeds quantity",
        id="fractionally-overfilled-order",
    ),
    pytest.param("positions", {**_pos(), "symbol": ""}, "missing symbol", id="position-symbol"),
    pytest.param("positions", {**_pos(), "exchange": None}, "missing exchange", id="position-exchange"),
    pytest.param("positions", {**_pos(), "product": " "}, "missing product", id="position-product"),
    pytest.param("positions", _pos(qty="nan"), "quantity must be finite", id="position-quantity"),
    pytest.param("holdings", {**_hold(), "symbol": ""}, "missing symbol", id="holding-symbol"),
    pytest.param("holdings", {**_hold(), "exchange": None}, "missing exchange", id="holding-exchange"),
    pytest.param("holdings", _hold(qty="inf"), "quantity must be finite", id="holding-infinite-quantity"),
    pytest.param("holdings", _hold(qty="-1"), "quantity must not be negative", id="holding-negative-quantity"),
]


@pytest.mark.parametrize(
    "missing_field",
    [
        "status",
        "symbol",
        "exchange",
        "product",
        "action",
        "quantity",
        "filled_quantity",
        "price",
        "trigger_price",
        "price_type",
        "variety",
        "validity",
        "strategy",
        "average_price",
    ],
)
def test_broker_order_evidence_requires_every_material_field(missing_field: str) -> None:
    row = _order()
    row.pop(missing_field)

    report = _report(broker_orders=[row])

    _assert_input_error(report, f"missing {missing_field}")


@pytest.mark.parametrize(
    "field",
    ["quantity", "filled_quantity", "price", "trigger_price", "average_price"],
)
@pytest.mark.parametrize("value", [float("nan"), float("inf"), float("-inf"), True, "not-a-number"])
def test_broker_order_numeric_evidence_must_be_finite(field: str, value: Any) -> None:
    report = _report(broker_orders=[_order(**{field: value})])

    _assert_input_error(report, f"{field} must be finite")


def test_order_evidence_preserves_legitimate_numeric_zero_values() -> None:
    zero_order = _order(qty="0", filled="0", price=0, trigger_price=0.0, average_price="0")

    report = _report(
        broker_orders=[zero_order],
        local_state=LocalStateSnapshot(orders=(zero_order,)),
    )

    assert report.error == ""
    assert report.clean
    assert report.broker_orders[0]["quantity"] == "0"
    assert report.broker_orders[0]["price"] == 0
    assert report.broker_orders[0]["trigger_price"] == 0.0
    assert report.broker_orders[0]["average_price"] == "0"


_ORDER_BOOK_NUMERIC_MAPPING_CASES = [
    pytest.param(
        dhan_mapping.from_dhan_order,
        {
            "quantity": "quantity",
            "filled_quantity": "filledQty",
            "price": "price",
            "trigger_price": "triggerPrice",
            "average_price": "averageTradedPrice",
        },
        id="dhan",
    ),
    pytest.param(
        upstox_mapping.from_upstox_order,
        {
            "quantity": "quantity",
            "filled_quantity": "filled_quantity",
            "price": "price",
            "trigger_price": "trigger_price",
            "average_price": "average_price",
        },
        id="upstox",
    ),
    pytest.param(
        kotakneo_mapping.from_kotak_order,
        {
            "quantity": "qty",
            "filled_quantity": "fldQty",
            "price": "prc",
            "trigger_price": "trgPrc",
            "average_price": "avgPrc",
        },
        id="kotakneo",
    ),
    pytest.param(
        indmoney_mapping.from_indmoney_order,
        {
            "quantity": "requested_qty",
            "filled_quantity": "traded_qty",
            "price": "requested_price",
            "trigger_price": "sl_trigger_price",
            "average_price": "traded_price",
        },
        id="indmoney",
    ),
    pytest.param(
        groww_mapping.from_order,
        {
            "quantity": "quantity",
            "filled_quantity": "filled_quantity",
            "price": "price",
            "trigger_price": "trigger_price",
            "average_price": "average_price",
        },
        id="groww",
    ),
]


@pytest.mark.parametrize(("normalise", "source_fields"), _ORDER_BOOK_NUMERIC_MAPPING_CASES)
def test_order_book_mapping_keeps_absent_and_blank_numeric_evidence_omitted(
    normalise,
    source_fields: dict[str, str],
) -> None:
    material_fields = set(source_fields)

    assert material_fields.isdisjoint(normalise({}))
    blank = normalise({source: "  " for source in source_fields.values()})
    assert material_fields.isdisjoint(blank)


@pytest.mark.parametrize(("normalise", "source_fields"), _ORDER_BOOK_NUMERIC_MAPPING_CASES)
def test_order_book_mapping_preserves_present_zero_and_malformed_numeric_evidence(
    normalise,
    source_fields: dict[str, str],
) -> None:
    zero = normalise({source: 0 for source in source_fields.values()})
    malformed = normalise({source: "not-a-number" for source in source_fields.values()})

    assert all(field in zero and float(zero[field]) == 0.0 for field in source_fields)
    assert all(malformed[field] == "not-a-number" for field in source_fields)


def test_adapter_must_explicitly_declare_unavailable_text_evidence() -> None:
    incomplete = _order()
    for field in ("variety", "validity", "strategy"):
        incomplete.pop(field)

    declared = declare_unavailable_order_fields(
        [incomplete],
        fields=("variety", "validity", "strategy"),
    )
    report = _report(broker_orders=declared)

    assert report.error == ""
    assert report.broker_orders[0]["variety"] == "UNKNOWN"
    assert report.broker_orders[0]["validity"] == "UNKNOWN"
    assert report.broker_orders[0]["strategy"] == "UNKNOWN"
    with pytest.raises(ValueError, match="text evidence"):
        declare_unavailable_order_fields([incomplete], fields=("price",))
    with pytest.raises(ValueError, match="iterable"):
        declare_unavailable_order_fields(None, fields=("strategy",))  # type: ignore[arg-type]


@pytest.mark.parametrize(("surface", "row", "fragment"), _MALFORMED_ROWS)
@pytest.mark.parametrize("side", ["broker", "local"])
def test_malformed_rows_fail_closed(
    surface: str,
    row: dict[str, Any],
    fragment: str,
    side: str,
) -> None:
    if side == "broker":
        report = _report(**{f"broker_{surface}": [row]})
    else:
        report = _report(local_state=LocalStateSnapshot(**{surface: (row,)}))

    _assert_input_error(report, fragment)


@pytest.mark.parametrize(
    ("surface", "rows"),
    [
        pytest.param("orders", [_order(), _order(status="complete")], id="orders"),
        pytest.param("positions", [_pos(), _pos(symbol="tcs", exchange="nse", product="cnc")], id="positions"),
        pytest.param("holdings", [_hold(), _hold(symbol="infy", exchange="nse")], id="holdings"),
    ],
)
@pytest.mark.parametrize("side", ["broker", "local"])
def test_duplicate_natural_keys_fail_closed(surface: str, rows: list[dict[str, Any]], side: str) -> None:
    if side == "broker":
        report = _report(**{f"broker_{surface}": rows})
    else:
        report = _report(local_state=LocalStateSnapshot(**{surface: tuple(rows)}))

    _assert_input_error(report, f"duplicate {surface} natural key")


def test_signed_position_quantity_remains_valid_for_short_positions() -> None:
    short = _pos(qty="-5")
    report = _report(broker_positions=[short], local_state=LocalStateSnapshot(positions=(short,)))

    assert report.clean
    assert report.error == ""


def test_order_without_filled_quantity_fails_closed_without_fabricating_zero() -> None:
    broker_order = {key: value for key, value in _order().items() if key != "filled_quantity"}
    local_order = _order(filled="0")

    report = _report(
        broker_orders=[broker_order],
        local_state=LocalStateSnapshot(orders=(local_order,)),
    )

    _assert_input_error(report, "missing filled_quantity")


def test_default_local_state_is_empty() -> None:
    report = _report(broker_orders=[_order()], local_state=None)
    (diff,) = report.orders_diff
    assert diff.discrepancy == DISCREPANCY_ONLY_ON_BROKER
    assert EMPTY_LOCAL_STATE.orders == () and EMPTY_LOCAL_STATE.positions == ()


# ---------------------------------------------------------------------------
# Adapter fakes
# ---------------------------------------------------------------------------

_DHAN_ORDER = {
    "orderId": "OID1",
    "orderStatus": "PENDING",
    "tradingSymbol": "TCS",
    "exchangeSegment": "NSE_EQ",
    "transactionType": "BUY",
    "orderType": "LIMIT",
    "productType": "CNC",
    "quantity": 5,
    "filledQty": 0,
    "price": 3500,
    "triggerPrice": 0,
    "averageTradedPrice": 0,
}
_DHAN_POSITION = {
    "tradingSymbol": "TCS",
    "exchangeSegment": "NSE_EQ",
    "productType": "CNC",
    "netQty": 5,
    "costPrice": 3450.0,
    "buyQty": 5,
    "buyAvg": 3450.0,
}
_DHAN_HOLDING = {"tradingSymbol": "INFY", "exchange": "NSE", "totalQty": 10, "avgCostPrice": 1500}


class _DhanClient:
    """Read-surface stand-in for the dhanhq client (reconcile inputs only)."""

    def __init__(self, *, fail_orders: bool = False) -> None:
        self._fail_orders = fail_orders

    def get_order_list(self):
        if self._fail_orders:
            raise BrokerError("boom")
        return {"status": "success", "data": [_DHAN_ORDER]}

    def get_positions(self):
        return {"status": "success", "data": [_DHAN_POSITION]}

    def get_holdings(self):
        return {"status": "success", "data": [_DHAN_HOLDING]}


class _UpstoxClient:
    """Read-surface stand-in for the UpstoxClient facade."""

    def order_book(self):
        return {
            "status": "success",
            "data": [
                {
                    "order_id": "U1",
                    "status": "open",
                    "trading_symbol": "RELIANCE",
                    "exchange": "NSE",
                    "transaction_type": "BUY",
                    "order_type": "LIMIT",
                    "product": "D",
                    "quantity": 10,
                    "price": 2900,
                    "filled_quantity": 0,
                    "trigger_price": 0,
                    "average_price": 0,
                },
            ],
        }

    def positions(self):
        return {
            "status": "success",
            "data": [
                {
                    "trading_symbol": "RELIANCE",
                    "exchange": "NSE",
                    "product": "D",
                    "quantity": 10,
                    "average_price": 2900.0,
                    "last_price": 2950.0,
                    "pnl": 500.0,
                },
            ],
        }

    def holdings(self):
        return {
            "status": "success",
            "data": [
                {"trading_symbol": "TCS", "exchange": "NSE", "quantity": 5, "average_price": 3450.0},
            ],
        }


class _KotakClient:
    """Read-surface stand-in for the KotakNeoClient facade."""

    def order_book(self):
        return {
            "data": [
                {
                    "nOrdNo": "K1",
                    "ordSt": "open",
                    "trdSym": "IDEA-EQ",
                    "exSeg": "nse_cm",
                    "trnsTp": "B",
                    "prcTp": "L",
                    "prod": "CNC",
                    "qty": 10,
                    "prc": "9.5",
                    "fldQty": 0,
                    "trgPrc": 0,
                    "avgPrc": 0,
                },
            ]
        }

    def positions(self):
        return {
            "data": [
                {
                    "trdSym": "IDEA-EQ",
                    "exSeg": "nse_cm",
                    "prod": "CNC",
                    "flBuyQty": 10,
                    "buyAmt": 95.0,
                    "cfBuyQty": 0,
                    "cfSellQty": 0,
                    "flSellQty": 0,
                    "genNum": 1,
                    "genDen": 1,
                    "prcNum": 1,
                    "prcDen": 1,
                    "precision": 2,
                },
            ]
        }

    def holdings(self):
        return {
            "data": [
                {"displaySymbol": "IDEA", "exchangeSegment": "nse_cm", "quantity": 10, "averagePrice": 9.5},
            ]
        }


_IND_ORDER = {
    "id": "DRV-1",
    "status": "SUCCESS",
    "name": "NIFTY 3 JUL 25700 CE",
    "exchange": "NSE",
    "segment": "DERIVATIVE",
    "product": "MARGIN",
    "txn_type": "BUY",
    "order_type": "MARKET",
    "requested_qty": 75,
    "traded_qty": 75,
    "requested_price": "43.55",
    "sl_trigger_price": 0,
    "traded_price": "43.55",
    "security_id": "56998",
}
_IND_POSITION = {
    "trading_symbol": "NIFTY 3 JUL 25700 CE",
    "exchange_segment": "NSE_FNO",
    "net_quantity": 75,
    "average_price": 43.55,
    "last_traded_price": 44.0,
    "pnl_absolute": 33.75,
}
_IND_HOLDING = {"trading_symbol": "TCS", "exchange_segment": "NSE_EQ", "quantity": 5, "average_price": 3450}


def _ind_transport(method, url, *, headers, params=None, json_body=None):
    """Params-aware fake httpx transport for the IndMoney adapter.

    Positions are returned for the derivative/margin combo ONLY, so the
    adapter's four-combo aggregation yields exactly one position row.
    """
    path = url.replace(indmoney_mapping.BASE_URL, "")
    if path == "/order-book":
        return 200, {"status": "success", "data": [_IND_ORDER]}
    if path == "/portfolio/positions":
        if params == {"segment": "derivative", "product": "margin"}:
            return 200, {"status": "success", "data": {"net_positions": [_IND_POSITION], "day_positions": []}}
        return 200, {"status": "success", "data": {"net_positions": [], "day_positions": []}}
    if path == "/portfolio/holdings":
        return 200, {"status": "success", "data": [_IND_HOLDING]}
    return 200, {"status": "success", "data": {}}


def _session(adapter_id: str, account_id: str) -> Session:
    return Session(access_token="TOK", expires_at=4_000_000_000.0, account_id=account_id, adapter_id=adapter_id)


async def _own_reads_snapshot(adapter, session: Session) -> LocalStateSnapshot:
    """A flinttrade-side mirror that matches the broker exactly (clean case)."""
    return LocalStateSnapshot(
        orders=declare_unavailable_order_fields(
            await adapter.order_book(session),
            fields=("variety", "validity", "strategy"),
        ),
        positions=tuple(await adapter.positions(session)),
        holdings=tuple(await adapter.holdings(session)),
    )


# ---------------------------------------------------------------------------
# Per-adapter reconcile()
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_dhan_reconcile_clean_round_trip() -> None:
    holder: dict[str, LocalStateSnapshot] = {}
    adapter = DhanAdapter(client_factory=lambda _s: _DhanClient(), local_state_provider=lambda _s: holder["snap"])
    session = _session("dhan", "ACC-D")
    holder["snap"] = await _own_reads_snapshot(adapter, session)
    report = await adapter.reconcile(session)
    assert report.adapter_id == "dhan" and report.account_id == "ACC-D"
    assert report.clean and report.error == ""


@pytest.mark.asyncio
async def test_dhan_reconcile_rejects_omitted_numeric_evidence_without_retaining_it() -> None:
    class MissingPriceDhanClient(_DhanClient):
        def get_order_list(self):
            order = dict(_DHAN_ORDER)
            order.pop("price")
            return {"status": "success", "data": [order]}

    adapter = DhanAdapter(client_factory=lambda _s: MissingPriceDhanClient())

    report = await adapter.reconcile(_session("dhan", "ACC-D"))

    _assert_input_error(report, "missing price")


@pytest.mark.asyncio
async def test_dhan_reconcile_default_empty_local_flags_broker_rows() -> None:
    adapter = DhanAdapter(client_factory=lambda _s: _DhanClient())
    report = await adapter.reconcile(_session("dhan", "ACC-D"))
    assert not report.clean
    assert [d.discrepancy for d in report.orders_diff] == [DISCREPANCY_ONLY_ON_BROKER]
    assert [d.discrepancy for d in report.positions_diff] == [DISCREPANCY_ONLY_ON_BROKER]
    assert [d.discrepancy for d in report.holdings_diff] == [DISCREPANCY_ONLY_ON_BROKER]
    assert report.severity == SEVERITY_CRITICAL  # the untracked position dominates


@pytest.mark.asyncio
async def test_dhan_reconcile_fetch_error_is_captured_not_raised() -> None:
    adapter = DhanAdapter(client_factory=lambda _s: _DhanClient(fail_orders=True))
    report = await adapter.reconcile(_session("dhan", "ACC-D"))
    assert "boom" in report.error and report.error.startswith("broker fetch failed")
    assert not report.clean and report.severity == SEVERITY_CRITICAL
    assert report.orders_diff == () and report.positions_diff == () and report.holdings_diff == ()


@pytest.mark.asyncio
async def test_upstox_reconcile_clean_then_flags_local_qty_drift() -> None:
    holder: dict[str, LocalStateSnapshot] = {}
    adapter = UpstoxAdapter(client_factory=lambda _s: _UpstoxClient(), local_state_provider=lambda _s: holder["snap"])
    session = _session("upstox", "ACC-U")
    snap = await _own_reads_snapshot(adapter, session)
    holder["snap"] = snap
    assert (await adapter.reconcile(session)).clean

    # Drift the local mirror's position quantity → one critical qty mismatch.
    drifted = tuple({**row, "quantity": "7"} for row in snap.positions)
    holder["snap"] = LocalStateSnapshot(orders=snap.orders, positions=drifted, holdings=snap.holdings)
    report = await adapter.reconcile(session)
    (diff,) = report.positions_diff
    assert diff.discrepancy == DISCREPANCY_QTY_MISMATCH and diff.severity == SEVERITY_CRITICAL
    assert diff.flinttrade_qty == 7.0 and diff.broker_qty == 10.0
    assert report.orders_diff == () and report.holdings_diff == ()


@pytest.mark.asyncio
async def test_kotakneo_reconcile_clean_round_trip() -> None:
    holder: dict[str, LocalStateSnapshot] = {}
    adapter = KotakNeoAdapter(client_factory=lambda _s: _KotakClient(), local_state_provider=lambda _s: holder["snap"])
    session = _session("kotakneo", "ACC-K")
    holder["snap"] = await _own_reads_snapshot(adapter, session)
    report = await adapter.reconcile(session)
    assert report.adapter_id == "kotakneo" and report.account_id == "ACC-K"
    assert report.clean and report.error == ""


@pytest.mark.asyncio
async def test_indmoney_reconcile_clean_round_trip() -> None:
    holder: dict[str, LocalStateSnapshot] = {}
    adapter = IndMoneyAdapter(http_factory=lambda: _ind_transport, local_state_provider=lambda _s: holder["snap"])
    session = _session("indmoney", "ACC-I")
    holder["snap"] = await _own_reads_snapshot(adapter, session)
    report = await adapter.reconcile(session)
    assert report.adapter_id == "indmoney" and report.account_id == "ACC-I"
    assert report.clean and report.error == ""
    # The fake serves exactly one of everything — prove the snapshot was real.
    assert len(holder["snap"].orders) == 1
    assert len(holder["snap"].positions) == 1
    assert len(holder["snap"].holdings) == 1
