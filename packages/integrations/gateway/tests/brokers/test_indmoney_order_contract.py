"""INDstocks regressions at the legacy mapper used by IndMoneyAdapter.

Public REST schemas are evidence, not permission or runtime readiness.
"""
from types import SimpleNamespace

import pytest

from flinttrade_core.broker_read_port import BrokerReadResponseInvalid
from flinttrade_gateway.brokers import indmoney_mapping as m

pytestmark = pytest.mark.unit


def order(**changes):
    values = dict(symbol="SYNTHETIC", action="BUY", exchange="NSE", product="CNC", quantity="5",
                  pricetype="LIMIT", price="100", trigger_price="0", variety="regular",
                  stop_loss_price="0", target_price="0", validity="DAY")
    values.update(changes)
    return SimpleNamespace(**values)


@pytest.mark.parametrize("quantity", [True, False, "1.5", -1, 0, "NaN", "Infinity", float("inf"), "garbage"])
@pytest.mark.parametrize("variety", ["regular", "amo", "trigger", "gtt", "oco"])
def test_i1_requests_refuse_inexact_quantities(quantity, variety):
    request = order(quantity=quantity, variety=variety, trigger_price="101")
    builder = m.to_smart_order_payload if variety in m.SMART_VARIETIES else m.to_place_order_payload
    with pytest.raises(m.IndMoneyMappingError):
        builder(request, "123")


@pytest.mark.parametrize("exchange,product,segment,wire_product", [
    ("NSE", "CNC", "EQUITY", "CNC"), ("BSE", "MIS", "EQUITY", "INTRADAY"),
    ("NFO", "NRML", "DERIVATIVE", "MARGIN"), ("BFO", "MIS", "DERIVATIVE", "INTRADAY"),
])
def test_i1_preserves_valid_resource_pairs_and_exact_large_quantities(exchange, product, segment, wire_product):
    payload = m.to_place_order_payload(order(exchange=exchange, product=product, quantity="9007199254740993"), "123")
    assert payload["qty"] == 9007199254740993
    assert payload["segment"] == segment and payload["product"] == wire_product


@pytest.mark.parametrize("changes,security_id", [
    ({"exchange": "NSE", "product": "NRML"}, "123"),
    ({"exchange": "NFO", "product": "CNC"}, "123"),
    ({}, ""), ({}, "   "), ({}, None), ({"price": "NaN"}, "123"),
    ({"price": "Infinity"}, "123"), ({"price": True}, "123"),
    ({"qty": 6}, "123"), ({"limit_price": "101"}, "123"),
])
def test_i1_invalid_resource_and_price_evidence_is_refused(changes, security_id):
    with pytest.raises(m.IndMoneyMappingError):
        m.to_place_order_payload(order(**changes), security_id)


@pytest.mark.parametrize("changes,segment", [
    ({"qty": "1.5", "limit_price": 73}, None),
    ({"quantity": 75, "qty": 74, "price": 73}, None),
    ({"quantity": 75, "price": 73, "limit_price": 74}, None),
    ({"quantity": 75, "price": "NaN"}, None),
    ({"quantity": 75, "price": 73, "segment": "EQUITY"}, None),
    ({"quantity": 75, "price": 73, "exchange": "NSE"}, None),
    ({"quantity": 75, "price": 73}, "EQUITY"),
    ({"quantity": 75, "price": 73, "segment": "INVALID"}, None),
])
def test_i1_modify_rejects_alias_and_segment_conflicts(changes, segment):
    with pytest.raises(m.IndMoneyMappingError):
        m.to_modify_order_payload("DRV-2049", changes, segment=segment)


def test_i1_normal_modify_exact_wire_with_agreeing_aliases():
    assert m.to_modify_order_payload("DRV-2049", {
        "quantity": "75", "qty": 75, "price": "73", "limit_price": 73,
        "exchange": "NFO", "segment": "DERIVATIVE",
    }, segment="DERIVATIVE") == {"order_id": "DRV-2049", "segment": "DERIVATIVE", "qty": 75, "limit_price": 73}


@pytest.mark.parametrize("side,sl,sl_limit,tgt,tgt_limit", [("BUY", 90, 89, 110, 111), ("SELL", 110, 111, 90, 89)])
@pytest.mark.parametrize("variety", ["gtt", "oco", "trigger"])
def test_i2_trigger_retains_legs_and_mirrors_buy_sell(side, sl, sl_limit, tgt, tgt_limit, variety):
    payload = m.to_smart_order_payload(order(
        action=side, variety=variety, trigger_price=99, price=100,
        stop_loss_price=sl, sl_limit_price=sl_limit, target_price=tgt, tgt_limit_price=tgt_limit,
    ), "123")
    fields = ("sl_trigger_price", "sl_limit_price", "tgt_trigger_price", "tgt_limit_price")
    assert {key: payload[key] for key in fields} == {
        "sl_trigger_price": sl, "sl_limit_price": sl_limit, "tgt_trigger_price": tgt, "tgt_limit_price": tgt_limit,
    }
    if variety == "trigger":
        assert payload["trigger_price"] == 99 and payload["trigger_limit_price"] == 100
        assert "limit_price" not in payload


@pytest.mark.parametrize("changes", [
    {"stop_loss_price": 110, "sl_limit_price": 109}, {"stop_loss_price": 100, "sl_limit_price": 99},
    {"stop_loss_price": 90, "sl_limit_price": 90}, {"target_price": 90, "tgt_limit_price": 91},
    {"target_price": 100, "tgt_limit_price": 101}, {"target_price": 110, "tgt_limit_price": 110},
    {"stop_loss_price": 90}, {"sl_limit_price": 89},
    {"stop_loss_price": "NaN"}, {"target_price": -1}, {"validity": "IOC"}, {"validity": "GTC"},
    {"limit_price": 101}, {"trigger_limit_price": 101},
])
def test_i2_trigger_refuses_bad_legs_and_validity(changes):
    with pytest.raises(m.IndMoneyMappingError):
        m.to_smart_order_payload(order(variety="trigger", trigger_price=99, **changes), "123")


def test_i2_market_does_not_use_arbitrary_request_price_as_cmp():
    payload = m.to_smart_order_payload(order(
        variety="gtt", pricetype="MARKET", price=1,
        stop_loss_price=90, sl_limit_price=89, target_price=110, tgt_limit_price=111,
    ), "123")
    assert payload["order_type"] == "MARKET" and "limit_price" not in payload


def test_i2_trigger_without_explicit_limit_uses_trigger_for_leg_validation():
    with pytest.raises(m.IndMoneyMappingError):
        m.to_smart_order_payload(order(variety="trigger", price=0, trigger_price=100,
                                      stop_loss_price=101, sl_limit_price=100), "123")


def test_i3_trigger_edit_has_exact_fields_and_current_context_is_not_wire():
    assert m.to_smart_modify_payload("EQ-456", {
        "existing_order_type": "TRIGGER", "exchange": "NSE", "variety": "trigger",
        "order_type": "TRIGGER", "pricetype": "TRIGGER", "quantity": "10", "qty": 10,
        "trigger_price": "101", "price": "102", "trigger_limit_price": 102,
    }, segment="EQUITY", algo_id="99999") == {
        "order_id": "EQ-456", "segment": "EQUITY", "algo_id": "99999", "order_type": "TRIGGER",
        "qty": 10, "trigger_price": 101, "trigger_limit_price": 102,
    }


@pytest.mark.parametrize("changes", [
    {"order_type": "LIMIT"}, {"order_type": "BANANA"}, {"order_type": "TRIGGER", "pricetype": "LIMIT"},
    {"limit_price": 102}, {"qty": 0}, {"qty": "1.5"}, {"qty": True}, {"qty": 10, "quantity": 11},
    {"price": 102, "trigger_limit_price": 103}, {"trigger_price": 0}, {"trigger_price": "NaN"},
    {"remarks": "edit"}, {"is_tsl": False}, {"tsl_step_size": 0}, {"trailing_jump": 0},
    {"unknown_mutation": 1},
])
def test_i3_smart_edit_rejects_mutations_and_bad_numbers(changes):
    values = {"existing_order_type": "TRIGGER", "trigger_price": 101, "algo_id": "99999"}
    values.update(changes)
    with pytest.raises(m.IndMoneyMappingError):
        m.to_smart_modify_payload("EQ-456", values, segment="EQUITY")


@pytest.mark.parametrize("changes", [
    {"order_type": "LIMIT", "algo_id": "99999", "limit_price": 100},
    {"existing_order_type": "LIMIT", "limit_price": 100},
    {"existing_order_type": "TRIGGER", "algo_id": "99999", "price": 102},
])
def test_i3_smart_edit_requires_existing_type_trigger_and_algo_evidence(changes):
    with pytest.raises(m.IndMoneyMappingError):
        m.to_smart_modify_payload("EQ-456", changes, segment="EQUITY")


def test_i3_preserves_partial_protective_edit_without_inventing_unchanged_leg():
    assert m.to_smart_modify_payload("DRV-123", {
        "existing_order_type": "LIMIT", "exchange": "NFO", "sl_limit_price": "89",
    }) == {"order_id": "DRV-123", "segment": "DERIVATIVE", "algo_id": "99999", "sl_limit_price": 89}


@pytest.mark.parametrize("changes", [{"is_tsl": True}, {"tsl_step_size": "1.25"}, {"trailing_jump": "2"}])
def test_i4_trailing_metadata_discloses_ignored_but_payloads_refuse(changes):
    request = order(pricetype="MARKET", price=0, **changes)
    effects = m.indmoney_execution_effects(request)
    assert effects == {"requested_type": "MARKET", "effective_type": "LIMIT", "effective_limit_price": None,
                       "trailing_active": False, "limitations": ["MARKET_TO_LIMIT", "TSL_IGNORED"]}
    with pytest.raises(m.IndMoneyMappingError, match="TSL_IGNORED"):
        m.to_place_order_payload(request, "123")
    request.variety = "trigger"
    request.trigger_price = 100
    with pytest.raises(m.IndMoneyMappingError, match="TSL_IGNORED"):
        m.to_smart_order_payload(request, "123")


def test_i4_requested_trigger_has_effective_limit_and_no_wire_metadata():
    request = order(variety="trigger", price=0, trigger_price=100)
    assert m.indmoney_execution_effects(request) == {
        "requested_type": "TRIGGER", "effective_type": "TRIGGER_LIMIT", "effective_limit_price": 100,
        "trailing_active": False, "limitations": [],
    }
    payload = m.to_smart_order_payload(request, "123")
    metadata = {"requested_type", "effective_type", "effective_limit_price", "limitations", "trailing_active"}
    assert not metadata & payload.keys()


@pytest.mark.parametrize("changes", [{"is_tsl": "false"}, {"trailing_jump": "NaN"}, {"tsl_step_size": -1}])
def test_i4_malformed_trailing_is_not_silently_ignored(changes):
    with pytest.raises(m.IndMoneyMappingError):
        m.indmoney_execution_effects(order(**changes))


def order_row(**changes):
    values = {"id": "EQ-TEST", "status": "CANCELLED", "name": "SYNTHETIC", "exchange": "NSE",
              "segment": "EQUITY", "txn_type": "BUY", "order_type": "LIMIT", "product": "CNC",
              "requested_qty": "100", "traded_qty": "40", "security_id": "123"}
    values.update(changes)
    return values


@pytest.mark.parametrize("changes", [
    {"requested_qty": -1}, {"requested_qty": "1.5"}, {"requested_qty": True},
    {"traded_qty": "40.5"}, {"traded_qty": -1}, {"traded_qty": "101"},
    {"requested_qty": "9007199254740992", "traded_qty": "9007199254740993"},
    {"quantity": 99}, {"filled_quantity": 41}, {"order_id": "EQ-OTHER"},
    {"id": " EQ-TEST"}, {"id": True}, {"security_id": " "},
])
def test_r1_old_order_projection_refuses_impossible_or_conflicting_evidence(changes):
    with pytest.raises(BrokerReadResponseInvalid):
        m.from_indmoney_order(order_row(**changes))


def test_i4_read_preserves_parent_leg_timestamps_and_cancelled_fills():
    row = m.from_indmoney_order(order_row(
        trigger_price="101", trigger_limit_price="102", sl_trigger_price="90", sl_limit_price="89",
        tgt_trigger_price="110", tgt_limit_price="111", remarks="kept verbatim", extra_info="reason",
        created_at="2026-01-02T09:01:00+05:30", updated_at="2026-01-02T09:02:00+05:30",
        exch_order_id="EX-TEST", requested_price="100", traded_price="99.5", validity="DAY",
    ))
    assert row["trigger_price"] == "101" and row["sl_trigger_price"] == "90"
    assert row["trigger_limit_price"] == "102" and row["tgt_limit_price"] == "111"
    assert row["quantity"] == "100" and row["filled_quantity"] == "40"
    assert row["status"] == "CANCELLED" and row["attempt_state"] == "CANCELLED"
    assert row["created_at"] == "2026-01-02T09:01:00+05:30"
    assert row["updated_at"] == "2026-01-02T09:02:00+05:30" and row["remarks"] == "kept verbatim"
    assert row["exchange_order_id"] == "EX-TEST" and row["extra_info"] == "reason"
    absent = order_row(sl_trigger_price="90")
    del absent["requested_qty"], absent["traded_qty"]
    projected = m.from_indmoney_order(absent)
    assert not {"quantity", "filled_quantity", "trigger_price"} & projected.keys()


@pytest.mark.parametrize("status,state", [
    ("SUCCESS", "FILLED"), ("CANCELLED", "CANCELLED"), ("PARTIALLY FILLED - CANCELLED", "CANCELLED"),
    ("EXPIRED", "EXPIRED"), ("PARTIALLY FILLED - EXPIRED", "EXPIRED"), ("PARTIALLY FILLED", "PARTIALLY_FILLED"),
    ("INITIATED", "ACKNOWLEDGED"), ("QUEUED", "SUBMITTING"), ("PROCESSING", "SUBMITTING"),
    ("O-PENDING", "WORKING"), ("SL-PENDING", "WORKING"), ("PENDING", "WORKING"), ("MODIFIED", "WORKING"),
    ("CANCEL_PENDING", "CANCEL_PENDING"), ("FAILED", "UNKNOWN"), ("ABORTED", "UNKNOWN"),
    ("SUCCESSFUL", "UNKNOWN"), ("ACK", "UNKNOWN"), ("CREATED", "UNKNOWN"), ("", "UNKNOWN"),
])
def test_i4_exact_rest_attempt_states_not_fuzzy(status, state):
    assert m.indmoney_attempt_state(status) == state
    assert m.from_indmoney_order(order_row(status=status))["attempt_state"] == state
    resource = m.from_indmoney_order(order_row(id="GTT-TEST", order_type="OCO", status=status))
    assert resource["attempt_state"] == "UNKNOWN"


FILL = {"fill_id": 1279916, "exch_order_id": "EX-FILL", "quantity": 25, "price": 73.55,
        "trade_date": "2026-01-02T09:02:00+05:30"}


def test_i5_official_order_fill_preserves_all_independent_identities():
    result = m.from_indmoney_order_fill(FILL, order_id="DRV-TEST")
    assert result["orderid"] == "DRV-TEST" and result["fill_id"] == 1279916
    assert result["exchange_order_id"] == "EX-FILL"
    assert result["quantity"] == "25" and result["price"] == "73.55"
    assert result["timestamp"] == result["trade_date"] == "2026-01-02T09:02:00+05:30"
    segment_fill = m.from_indmoney_tradebook_row({**FILL, "scrip_code": "123"})
    assert segment_fill["orderid"] == "" and segment_fill["exchange_order_id"] == "EX-FILL"
    assert segment_fill["fill_id"] == 1279916


@pytest.mark.parametrize("changes", [{"fill_id": True}, {"fill_id": "1.5"}, {"exch_order_id": " "},
                                      {"order_id": "DRV-OTHER"}, {"quantity": "1.5"}, {"quantity": -1},
                                      {"price": "NaN"}, {"trade_date": []}])
def test_i5_official_fill_rejects_malformed_or_conflicting_evidence(changes):
    with pytest.raises(BrokerReadResponseInvalid):
        m.from_indmoney_order_fill({**FILL, **changes}, order_id="DRV-TEST")


SMART_RESULTS = {"status": "success", "data": {"order_data": [
    {"order_id": "EQ-PARENT", "order_status": "CREATED", "child_order_details": {
        "order_id": "GTT-CHILD", "order_status": "CREATED"}},
    {"order_id": "DRV-PARENT", "order_status": "FAILED", "error": {"code": "RMS", "message": "denied"}},
    {"error": "validation failed"},
]}}


def test_i6_smart_results_retain_each_parent_child_status_and_error():
    result = m.from_indmoney_smart_results(SMART_RESULTS)
    assert len(result) == 3
    assert result[0]["parent_order_id"] == "EQ-PARENT" and result[0]["parent_status"] == "CREATED"
    assert result[0]["child_order_id"] == "GTT-CHILD" and result[0]["child_status"] == "CREATED"
    assert result[1]["error"] == {"code": "RMS", "message": "denied"}
    assert result[1]["parent_status"] == "FAILED" and result[1]["child_order_id"] is None
    assert result[2]["parent_order_id"] is None and result[2]["error"] == "validation failed"
    with pytest.raises(m.IndMoneyMappingError, match="single|multiple"):
        m.extract_smart_order_ids(SMART_RESULTS)


@pytest.mark.parametrize("item", [None, "bad", {}, {"order_id": True}, {"order_id": " EQ-1"},
                                    {"order_id": "EQ-1", "child_order_details": []},
                                    {"order_id": "EQ-1", "child_order_details": {"order_id": []}},
                                    {"order_id": "EQ-1", "error": ["bad"]}])
def test_i6_malformed_result_items_are_not_filtered(item):
    with pytest.raises(BrokerReadResponseInvalid):
        m.from_indmoney_smart_results({"status": "success", "data": {"order_data": [item]}})


def test_i6_supported_flat_ack_is_preserved_and_rejection_is_not_success():
    assert m.extract_smart_order_ids({"status": "success", "data": {"order_id": "GTT-FLAT"}}) == ("GTT-FLAT", None)
    with pytest.raises(m.IndMoneyMappingError):
        rejected = SMART_RESULTS["data"]["order_data"][1]
        m.extract_smart_order_ids({"status": "success", "data": {"order_data": [rejected]}})


def test_i7_validation_exception_is_typed_and_preserves_broker_code_reason():
    from flinttrade_core.exceptions import OrderError

    mapped = m.map_error(400, {"error_type": "RequestValidationException", "error_code": "BAD_QTY",
                               "message": "qty must be integral"})
    assert type(mapped) is OrderError and mapped.broker_code == "BAD_QTY"
    assert str(mapped) == "qty must be integral" and mapped.broker_id == "indmoney"


@pytest.mark.parametrize("response", [
    {"status": "success", "data": {"order_id": True}},
    {"status": "success", "data": {"order_id": " EQ-1"}},
    {"status": "success", "data": {"order_id": "EQ-1", "id": "EQ-2"}},
    {"status": "failed", "data": {"order_id": "EQ-1"}},
    {"status": False, "data": {"order_id": "EQ-1"}},
    {"status": "success", "data": {"order_id": "EQ-1", "order_status": "FAILED"}},
])
def test_ack_old_normal_extractor_rejects_bad_identity_or_rejected_envelope(response):
    with pytest.raises(m.IndMoneyMappingError):
        m.extract_order_id(response)


@pytest.mark.parametrize("order_id,segment", [("GTT-1", None), ("EQ-1", "DERIVATIVE"), (" EQ-1", "EQUITY")])
def test_i8_cancel_builder_requires_noncontradictory_explicit_addressing(order_id, segment):
    with pytest.raises(m.IndMoneyMappingError):
        m.to_cancel_payload(order_id, segment)


def test_i3_bad_current_context_has_typed_refusal_not_attribute_error():
    with pytest.raises(m.IndMoneyMappingError):
        m.to_smart_modify_payload("EQ-1", {"existing_order_type": None, "price": 100},
                                 existing_order_type="LIMIT", algo_id="99999")


@pytest.mark.parametrize("changes", [{"order_id": True}, {"quantity": "1.5"}, {"quantity": -1},
                                      {"price": "NaN"}, {"trade_timestamp": []}])
def test_i5_historical_trade_mapper_remains_strict_without_schema_coercion(changes):
    historic = {"order_id": "EQ-TEST", "trading_symbol": "SYNTHETIC", "exchange_segment": "NSE_EQ",
                "transaction_type": "BUY", "product_type": "CNC", "quantity": 5, "price": 100,
                "trade_timestamp": "2026-01-02T09:02:00+05:30"}
    with pytest.raises(BrokerReadResponseInvalid):
        m.from_indmoney_trade({**historic, **changes})


@pytest.mark.parametrize("variety", ["regular", "trigger"])
def test_i4_documented_explicit_remarks_survive_the_old_payload_builder(variety):
    builder = m.to_place_order_payload if variety == "regular" else m.to_smart_order_payload
    payload = builder(order(variety=variety, trigger_price=101, remarks="strategy/signal retained"), "123")
    assert payload["remarks"] == "strategy/signal retained"
    with pytest.raises(m.IndMoneyMappingError):
        builder(order(variety=variety, trigger_price=101, remarks="x" * 101), "123")


@pytest.mark.parametrize("validity", ["", False, 0])
@pytest.mark.parametrize("smart", [True, False])
def test_i1_i2_explicit_bad_validity_cannot_become_day(validity, smart):
    builder = m.to_smart_order_payload if smart else m.to_place_order_payload
    with pytest.raises(m.IndMoneyMappingError):
        builder(order(variety="trigger" if smart else "regular", trigger_price=101, validity=validity), "123")


def test_ack_normal_malformed_status_uses_response_refusal_not_type_error():
    with pytest.raises(m.IndMoneyMappingError):
        m.extract_order_id({"status": "success", "data": {"order_id": "EQ-TEST", "order_status": []}})
