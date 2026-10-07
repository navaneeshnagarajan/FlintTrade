"""Independent regressions at the legacy Kotak mapper's public seams."""

from __future__ import annotations

import pytest

from flinttrade_core.broker_read_port import BrokerReadResponseInvalid
from flinttrade_core.models import Order
from flinttrade_gateway.brokers import kotakneo_mapping as M

pytestmark = pytest.mark.unit


@pytest.mark.parametrize("operation", ["place", "modify"])
@pytest.mark.parametrize(
    "quantity,disclosed",
    [("2", "3"), ("9007199254740992", "9007199254740993")],
)
def test_legacy_disclosure_cannot_exceed_exact_order_quantity(operation, quantity, disclosed):
    if operation == "place":
        order = Order(
            symbol="SYNTHETIC", action="BUY", exchange="NSE", product="MIS",
            pricetype="LIMIT", price="9.40", quantity=quantity, disclosed_quantity=disclosed,
        )
        with pytest.raises(M.KotakNeoMappingError, match="disclosed quantity"):
            M.to_place_order_params(order, "SYNTHETIC-EQ")
    else:
        with pytest.raises(M.KotakNeoMappingError, match="disclosed quantity"):
            M.to_modify_order_params(
                "OID-1", {"price": "9.40", "quantity": quantity, "disclosed_quantity": disclosed},
            )


@pytest.mark.parametrize(
    "pricetype,order_type", [("LIMIT", "MKT"), ("MARKET", "L"), ("SL", "SL-M"), ("LIMIT", "INVALID")],
)
def test_legacy_modify_reconciles_all_supplied_order_type_aliases(pricetype, order_type):
    with pytest.raises(M.KotakNeoMappingError):
        M.to_modify_order_params(
            "OID-1",
            {"pricetype": pricetype, "order_type": order_type, "price": "9.40", "quantity": "10"},
        )


@pytest.mark.parametrize("quantity,disclosed", [("10", "10"), ("9007199254740993", "9007199254740993")])
def test_legacy_equivalent_modify_aliases_preserve_exact_wire_and_signed_context(quantity, disclosed):
    assert M.to_modify_order_params(
        "OID-1",
        {
            "pricetype": "LIMIT", "order_type": "L", "quantity": quantity,
            "disclosed_quantity": disclosed, "price": "9.40", "validity": "IOC", "amo": "YES",
            "symbol": "SYNTHETIC", "exchange": "NSE", "action": "BUY", "product": "MIS",
            "broker_product": "MIS", "variety": "amo", "strategy": "Synthetic Strategy",
        },
    ) == {
        "order_id": "OID-1", "order_type": "L", "price": "9.40", "quantity": quantity,
        "validity": "IOC", "trigger_price": "0", "disclosed_quantity": disclosed, "amo": "YES",
    }


def _order_row(**observations):
    row = {
        "nOrdNo": "OID-1", "ordSt": "cancelled", "trdSym": "SYNTHETIC-EQ", "exSeg": "nse_cm",
        "trnsTp": "B", "prcTp": "L", "prod": "NRML", "qty": "100", "fldQty": "40",
        "prc": "9.40", "trgPrc": "0", "avgPrc": "9.35",
    }
    row.update(observations)
    return row


@pytest.mark.parametrize("field", ["qty", "fldQty"])
@pytest.mark.parametrize("value", ["-1", "1.5", True, "NaN", "Infinity"])
def test_legacy_order_quantities_are_nonnegative_whole_observations(field, value):
    with pytest.raises(BrokerReadResponseInvalid):
        M.from_kotak_order(_order_row(**{field: value}))


@pytest.mark.parametrize(
    "quantity,filled", [("1", "2"), ("9007199254740992", "9007199254740993")],
)
def test_legacy_order_rejects_filled_above_total_without_float_rounding(quantity, filled):
    with pytest.raises(BrokerReadResponseInvalid):
        M.from_kotak_order(_order_row(qty=quantity, fldQty=filled))


def test_legacy_order_partial_cancel_and_absent_quantities_remain_observations():
    mapped = M.from_kotak_order(_order_row())
    assert (mapped["quantity"], mapped["filled_quantity"], mapped["status"]) == ("100", "40", "cancelled")
    large = M.from_kotak_order(_order_row(qty="9007199254740993", fldQty="9007199254740992"))
    assert (large["quantity"], large["filled_quantity"]) == ("9007199254740993", "9007199254740992")
    for quantity, filled in [(None, None), ("", ""), (None, "40"), ("100", None)]:
        mapped = M.from_kotak_order(_order_row(qty=quantity, fldQty=filled))
        assert ("quantity" in mapped) is bool(quantity)
        assert ("filled_quantity" in mapped) is bool(filled)


def test_legacy_trade_quantities_prices_and_event_times_are_not_order_aliases():
    # Pinned trade_report documentation returns qty=0 beside fldQty=1.
    # avgPrc/flPrc and ordDtTm/flDtTm describe different observations too.
    mapped = M.from_kotak_trade({
        "nOrdNo": "OID-1", "trdSym": "SYNTHETIC-EQ", "exSeg": "nse_cm", "trnsTp": "B", "prod": "NRML",
        "qty": "0", "fldQty": "1", "avgPrc": "9.39", "flPrc": "9.40",
        "ordDtTm": "22-Jan-2025 14:28:01", "flDtTm": "22-Jan-2025 14:32:53",
    })
    assert mapped["quantity"] == "1"
    assert mapped["price"] == "9.39"
    assert mapped["timestamp"] == "22-Jan-2025 14:32:53"
    assert mapped["orderid"] == "OID-1"


@pytest.mark.parametrize("order_id", [" OID-1", "OID-1 ", "OID 1", "OID\t1", "OID\n1"])
def test_legacy_order_id_must_already_be_canonical(order_id):
    with pytest.raises(BrokerReadResponseInvalid):
        M.from_kotak_order(_order_row(nOrdNo=order_id))


@pytest.mark.parametrize(
    "observations",
    [
        {"exOrdId": "EX-1", "exchOrdId": "EX-2"},
        {"vldt": "DAY", "ordDur": "IOC"},
        {"dscQty": "10", "dclQty": "20"},

        {"exOrdId": " EX-1"},
        {"exchOrdId": "EX 1"},
        {"dscQty": "-1"},
        {"dclQty": "1.5"},
    ],
)
def test_legacy_order_true_identity_validity_and_disclosure_aliases_cannot_conflict(observations):
    with pytest.raises(BrokerReadResponseInvalid):
        M.from_kotak_order(_order_row(**observations))


def test_legacy_order_equivalent_aliases_keep_optional_fields_and_distinct_timestamps():
    mapped = M.from_kotak_order(_order_row(
        sym="SYNTHETIC", exOrdId="EX-1", exchOrdId="EX-1", vldt="DAY", ordDur="DAY",
        dscQty="10", dclQty=10, GuiOrdId="TAG-1", rejRsn="RMS reason",
        ordDtTm="22-Jan-2025 14:28:01", exchTmstp="22-Jan-2025 14:32:53",
    ))
    assert mapped["exchange_order_id"] == "EX-1"
    assert mapped["symbol"] == "SYNTHETIC-EQ"
    assert mapped["validity"] == "DAY"
    assert mapped["disclosed_quantity"] == "10"
    assert mapped["timestamp"] == "22-Jan-2025 14:28:01"
    assert mapped["tag"] == "TAG-1"
    assert mapped["rejection_reason"] == "RMS reason"


@pytest.mark.parametrize(
    "status,state",
    [
        ("complete", "FILLED"), ("  TrAdEd  ", "FILLED"), ("cancelled", "CANCELLED"),
        ("rejected", "REJECTED"), ("OPEN", "WORKING"), ("CANCEL_PENDING", "CANCEL_PENDING"),
        ("cancel_requested", "CANCEL_PENDING"), ("NOT_CANCELLED", "UNKNOWN"),
        ("COMPLETE_PENDING", "UNKNOWN"), ("put order req received", "UNKNOWN"), ("", "UNKNOWN"),
    ],
)
def test_legacy_additive_attempt_state_preserves_exact_raw_order_status(status, state):
    assert M.kotak_attempt_state(status) == state
    if status:
        mapped = M.from_kotak_order(_order_row(ordSt=status))
        assert mapped["status"] == status
        assert mapped["attempt_state"] == state
        assert mapped["filled_quantity"] == "40"


@pytest.mark.parametrize("status", [None, True, 200, {}, []])
def test_legacy_attempt_state_never_coerces_nontext_evidence(status):
    assert M.kotak_attempt_state(status) == "UNKNOWN"


@pytest.mark.parametrize(
    "response",
    [
        "garbage", None, {}, {"Error": "provider failure"}, {"stat": "Not_Ok", "errMsg": "RMS reason"},
        {"stat": "Ok", "data": [None]}, {"stat": "Ok", "data": {}},
        {"data": {"stat": "Ok", "data": [None]}}, {"stat": "Ok"},
        {"stat": "Ok", "data": [{1: "not a field name"}]},
    ],
)
def test_legacy_history_helper_refuses_failure_or_malformed_rows_instead_of_empty(response):
    with pytest.raises(BrokerReadResponseInvalid):
        M.order_history_rows(response)


@pytest.mark.parametrize("nested", [False, True])
def test_legacy_history_preserves_real_empty_lists_and_every_duplicate_transition(nested):
    empty = {"stat": "Ok", "stCode": 200, "data": []}
    if nested:
        empty = {"data": empty}
    assert M.order_history_rows(empty) == []
    rows = [_order_row(prod="BO", exSeg="cde_fo"), _order_row(prod="MTF"), _order_row(prod="MTF")]
    response = {"stat": "Ok", "stCode": 200, "data": rows}
    if nested:
        response = {"data": response}
    assert M.order_history_rows(response) == rows
    assert len(M.order_history_rows(response)) == 3


@pytest.mark.parametrize("http_code", [400, 503, True, "200"])
def test_legacy_ack_rejects_every_contradictory_or_malformed_supplied_http_status(http_code):
    with pytest.raises(M.KotakNeoMappingError):
        M.require_write_success({"stat": "Ok", "stCode": 200, "status_code": http_code, "nOrdNo": "OID-1"})


@pytest.mark.parametrize("native_code,http_code", [(1021, 400), (400, 400)])
def test_legacy_code_only_write_refusal_retains_supplied_broker_reason(native_code, http_code):
    with pytest.raises(M.KotakNeoMappingError, match="order is completed"):
        M.require_write_success({
            "stat": "Ok", "stCode": native_code, "status_code": http_code,
            "errMsg": "order is completed", "nOrdNo": "OID-1",
        })


@pytest.mark.parametrize("key", ["Error", "Error Message", "error"])
def test_legacy_error_id_and_boolean_native_code_are_not_an_ack(key):
    with pytest.raises(M.KotakNeoMappingError):
        M.require_write_success({"stat": "Ok", "stCode": 200, "nOrdNo": "OID-1", key: "RMS reason"})
    with pytest.raises(M.KotakNeoMappingError):
        M.require_write_success({"stat": "Ok", "stCode": True, "nOrdNo": "OID-1"})


def test_legacy_ack_is_only_ack_and_never_execution_or_closure():
    response = {"stat": "Ok", "stCode": 200, "status_code": 200, "nOrdNo": "OID-1"}
    assert M.require_write_success(response, expected_order_id="OID-1") is response
    assert response == {"stat": "Ok", "stCode": 200, "status_code": 200, "nOrdNo": "OID-1"}
    with pytest.raises(M.KotakNeoMappingError, match="different order id"):
        M.require_write_success(response, expected_order_id="OID-2")


def test_canonical_mtf_intention_preserves_documented_placement_parameters_without_eligibility_claim():
    order = Order(
        symbol="SYNTHETIC", action="BUY", exchange="NSE", product="MTF", pricetype="LIMIT",
        quantity="10", price="9.40", disclosed_quantity="2", validity="DAY",
    )
    assert order.model_dump(mode="json")["product"] == "MTF"
    assert M.to_place_order_params(order, "SYNTHETIC-EQ", tag="TAG-1") == {
        "exchange_segment": "nse_cm", "product": "MTF", "price": "9.40", "order_type": "L",
        "quantity": "10", "validity": "DAY", "trading_symbol": "SYNTHETIC-EQ", "transaction_type": "B",
        "trigger_price": "0", "disclosed_quantity": "2", "amo": "NO", "tag": "TAG-1",
    }


@pytest.mark.parametrize("context", [{"product": "MTF"}, {"broker_product": "MTF"}])
def test_mtf_placement_serialisation_does_not_grant_unverified_modify_eligibility(context):
    with pytest.raises(M.KotakNeoMappingError, match="MTF.*eligibility.*unverified"):
        M.to_modify_order_params("OID-1", {"quantity": "10", "price": "9.40", **context})


@pytest.mark.parametrize("product", ["BO", "CO", "MTF"])
def test_legacy_historical_product_observation_survives_without_outbound_promotion(product):
    assert M.from_kotak_order(_order_row(prod=product))["broker_product"] == product


@pytest.mark.parametrize(
    "nested",
    [
        {"stat": "Not_Ok", "errMsg": "Nested refusal"},
        {"stCode": 400, "errMsg": "Nested refusal"},
        {"status_code": 503, "errMsg": "Nested refusal"},
        {"error": [{"message": "Nested refusal"}]},
        {"Error": "Nested refusal"},
        {"Error Message": "Nested refusal"},
        {"nOrdNo": "OID-2"},
        {"orderId": "OID-2"},
    ],
)
def test_legacy_ack_cannot_ignore_contradictory_nested_evidence(nested):
    with pytest.raises(M.KotakNeoMappingError):
        M.require_write_success({"stat": "Ok", "stCode": 200, "nOrdNo": "OID-1", "data": nested})


def test_legacy_ack_accepts_agreeing_nested_identity_without_manufacturing_status():
    response = {"stat": "Ok", "stCode": 200, "nOrdNo": "OID-1", "data": {"nOrdNo": "OID-1", "orderId": "OID-1"}}
    assert M.require_write_success(response, expected_order_id="OID-1") is response
