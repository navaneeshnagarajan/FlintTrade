"""U1–U5/R1 regressions at the legacy mapper and injected adapter seams.

Only synthetic intentions/identities and deterministic facade responses are used.
Normal package startup is exercised by the approved credential-hidden runner.
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from flinttrade_core.broker_read_port import BrokerReadResponseInvalid
from flinttrade_gateway.brokers import upstox_mapping as m
from flinttrade_gateway.brokers._base import Session
from flinttrade_gateway.brokers.upstox import _ROUTER_TOKEN, UpstoxAdapter, UpstoxClient

pytestmark = pytest.mark.unit


def order(**changes):
    values = {
        "symbol": "SYNTHETIC", "exchange": "NSE", "product": "MIS", "action": "BUY",
        "pricetype": "LIMIT", "quantity": "10", "price": "100", "trigger_price": "99",
        "disclosed_quantity": "0", "variety": "regular", "validity": "IOC",
        "stop_loss_price": "90", "target_price": "110", "stop_loss_trailing_gap": "0.5",
        "entry_trigger_type": "BELOW", "stop_loss_trigger_type": "IMMEDIATE", "target_trigger_type": "IMMEDIATE",
    }
    values.update(changes)
    return SimpleNamespace(**values)


def replacement(**changes):
    values = {
        "type": "MULTIPLE", "quantity": "10", "trigger_price": "99", "entry_trigger_type": "BELOW",
        "stop_loss_price": "90", "target_price": "110", "stop_loss_trailing_gap": "0.5",
        "stop_loss_trigger_type": "IMMEDIATE", "target_trigger_type": "IMMEDIATE",
    }
    values.update(changes)
    return values


def request(family, quantity, disclosed_quantity="0"):
    intention = order(quantity=quantity, disclosed_quantity=disclosed_quantity)
    if family == "v2":
        return m.to_place_order_params(intention, "NSE_EQ|SYNTHETIC", tag="synthetic-tag")
    if family == "amo":
        intention.variety = "amo"
        return m.to_place_order_params(intention, "NSE_EQ|SYNTHETIC")
    if family == "v3":
        intention.variety = "iceberg"
        return m.to_place_order_v3_params(intention, "NSE_EQ|SYNTHETIC")
    if family == "multi":
        return m.to_multi_order_params([(intention, "NSE_EQ|SYNTHETIC")])[0]
    if family == "gtt":
        return m.to_gtt_place_params(intention, "NSE_EQ|SYNTHETIC")
    if family == "modify":
        return m.to_modify_order_params("SYNTHETIC-ORDER", {"quantity": quantity, "disclosed_quantity": disclosed_quantity})
    if family == "gtt-modify":
        return m.to_gtt_modify_params("GTT-SYNTHETIC", replacement(quantity=quantity))
    if family == "margin":
        return m.to_margin_instrument(intention, "NSE_EQ|SYNTHETIC")
    if family == "convert":
        return m.to_convert_position_params({
            "instrument_token": "NSE_EQ|SYNTHETIC", "old_product": "MIS", "new_product": "CNC",
            "transaction_type": "BUY", "quantity": quantity,
        })
    raise AssertionError(family)


@pytest.mark.parametrize("family", ["v2", "amo", "v3", "multi", "gtt", "modify", "gtt-modify"])
@pytest.mark.parametrize("quantity", [True, False, 1.5, "1.5", float("nan"), "NaN", float("inf"), "Infinity", -1, 0, "", None])
def test_u2_request_quantities_reject_lossy_or_invalid_intent(family, quantity):
    with pytest.raises(m.UpstoxMappingError):
        request(family, quantity)


@pytest.mark.parametrize("family", ["v2", "amo", "v3", "multi", "gtt", "modify", "gtt-modify"])
@pytest.mark.parametrize("quantity,expected", [(1, 1), ("10", 10), ("9007199254740993", 9007199254740993)])
def test_u2_request_quantities_preserve_exact_positive_values(family, quantity, expected):
    payload = request(family, quantity)
    assert type(payload["quantity"]) is int
    assert payload["quantity"] == expected


@pytest.mark.parametrize("family", ["v2", "amo", "v3", "multi", "modify"])
@pytest.mark.parametrize("disclosure", [True, -1, "1.5", "NaN", float("inf")])
def test_u2_disclosures_are_exact_nonnegative_quantities(family, disclosure):
    with pytest.raises(m.UpstoxMappingError):
        request(family, "10", disclosure)


class RecordingClient:
    def __init__(self):
        self.calls = []

    def place_order(self, params):
        self.calls.append(("v2", params))
        return {"status": "success", "data": {"order_id": "SYNTHETIC-ORDER"}}

    def place_order_v3(self, params):
        self.calls.append(("v3", params))
        return {"status": "success", "data": {"order_ids": ["SYNTHETIC-SLICE-1", "SYNTHETIC-SLICE-2"]}}

    def place_gtt_order(self, params):
        self.calls.append(("gtt", params))
        return {"status": "success", "data": {"gtt_order_id": "GTT-SYNTHETIC"}}

    def place_multi_order(self, params):
        self.calls.append(("multi", params))
        return {
            "status": "success", "data": [{"order_id": "SYNTHETIC-ORDER", "correlation_id": "1"}],
            "errors": [], "summary": {"total": 1, "success": 1},
        }

    def modify_order(self, params):
        self.calls.append(("modify", params))
        return {"status": "success", "data": {"order_id": "SYNTHETIC-ORDER"}}

    def modify_gtt_order(self, params):
        self.calls.append(("gtt-modify", params))
        return {"status": "success", "data": {"gtt_order_id": "GTT-SYNTHETIC"}}


def adapter_session(client):
    adapter = UpstoxAdapter(
        client_factory=lambda _session: client,
        instrument_resolver=lambda _symbol, _exchange: "NSE_EQ|SYNTHETIC",
    )
    session = Session(access_token="synthetic-token", expires_at=9999999999, account_id="synthetic-account",
                      adapter_id="upstox", algo_id="synthetic-tag")
    return adapter, session


@pytest.mark.asyncio
@pytest.mark.parametrize("family", ["v2", "amo", "v3", "gtt", "modify", "gtt-modify"])
async def test_u2_adapter_rejects_fractional_quantity_before_dispatch(family):
    client = RecordingClient()
    adapter, session = adapter_session(client)
    with pytest.raises(m.UpstoxMappingError):
        if family == "modify":
            await adapter.modify_order(session, "SYNTHETIC-ORDER", {"quantity": "1.5"}, _router_token=_ROUTER_TOKEN)
        elif family == "gtt-modify":
            await adapter.modify_order(session, "GTT-SYNTHETIC", replacement(quantity="1.5"), _router_token=_ROUTER_TOKEN)
        else:
            variety = {"v2": "regular", "v3": "iceberg", "amo": "amo", "gtt": "gtt"}[family]
            await adapter.place_order(session, order(quantity="1.5", variety=variety), _router_token=_ROUTER_TOKEN)
    assert client.calls == []


@pytest.mark.asyncio
@pytest.mark.parametrize("verb", ["modify_order", "modify_forever"])
async def test_u1_adapter_forwards_explicit_gtt_strategy_protection(verb):
    client = RecordingClient()
    adapter, session = adapter_session(client)
    await getattr(adapter, verb)(
        session, "GTT-SYNTHETIC", replacement(market_protection_by_strategy={"ENTRY": -1, "STOPLOSS": 0}),
        _router_token=_ROUTER_TOKEN,
    )
    assert client.calls == [("gtt-modify", {
        "gtt_order_id": "GTT-SYNTHETIC", "type": "MULTIPLE", "quantity": 10,
        "rules": [
            {"strategy": "ENTRY", "trigger_type": "BELOW", "trigger_price": 99.0, "market_protection": -1},
            {"strategy": "STOPLOSS", "trigger_type": "IMMEDIATE", "trigger_price": 90.0,
             "trailing_gap": 0.5, "market_protection": 0},
            {"strategy": "TARGET", "trigger_type": "IMMEDIATE", "trigger_price": 110.0},
        ],
    })]


@pytest.mark.parametrize("protection", [-1, 0, 1, 25])
@pytest.mark.parametrize("pricetype", ["MARKET", "SL-M", "LIMIT", "SL"])
def test_u1_explicit_protection_at_planned_legacy_signatures(protection, pricetype):
    intention = order(pricetype=pricetype, variety="iceberg")
    plain = m.to_place_order_v3_params(intention, "NSE_EQ|SYNTHETIC")
    assert "market_protection" not in plain
    payload = m.to_place_order_v3_params(intention, "NSE_EQ|SYNTHETIC", market_protection=protection)
    assert payload["market_protection"] == protection
    assert type(payload["market_protection"]) is int
    assert payload["order_type"] == pricetype and payload["slice"] is True
    assert "protection_active" not in payload
    batch = m.to_multi_order_params(
        [(intention, "NSE_EQ|A"), (order(variety="amo"), "NSE_EQ|B")],
        tag="synthetic-tag", market_protection_by_index={1: protection},
    )
    assert "market_protection" not in batch[0]
    assert batch[1]["market_protection"] == protection and batch[1]["is_amo"] is True
    assert [p["correlation_id"] for p in batch] == ["1", "2"]
    assert batch[0]["slice"] is True and batch[0]["validity"] == "IOC"
    assert batch[0]["tag"] == batch[1]["tag"] == "synthetic-tag"
    for payload in (
        m.to_gtt_place_params(intention, "NSE_EQ|SYNTHETIC", market_protection_by_strategy={"TARGET": protection}),
        m.to_gtt_modify_params("GTT-SYNTHETIC", replacement(), market_protection_by_strategy={"TARGET": protection}),
    ):
        assert payload["rules"][2]["market_protection"] == protection
        assert all("market_protection" not in rule for rule in payload["rules"][:2])
        assert payload["rules"][1]["trailing_gap"] == 0.5


@pytest.mark.parametrize("protection", [True, False, 1.5, 1.0, "1", -2, 26, float("nan")])
def test_u1_invalid_explicit_protection_is_refused_at_every_legacy_builder(protection):
    with pytest.raises(m.UpstoxMappingError):
        m.to_place_order_v3_params(order(), "NSE_EQ|SYNTHETIC", market_protection=protection)
    with pytest.raises(m.UpstoxMappingError):
        m.to_multi_order_params([(order(), "NSE_EQ|SYNTHETIC")], market_protection_by_index={0: protection})
    with pytest.raises(m.UpstoxMappingError):
        m.to_gtt_place_params(order(), "NSE_EQ|SYNTHETIC", market_protection_by_strategy={"ENTRY": protection})
    with pytest.raises(m.UpstoxMappingError):
        m.to_gtt_modify_params("GTT-SYNTHETIC", replacement(), market_protection_by_strategy={"ENTRY": protection})


@pytest.mark.parametrize("assignment", [{-1: 1}, {1: 1}, {True: 1}, {0.0: 1}, {"0": 1}, [], {0: None}])
def test_u1_invalid_batch_protection_indexes_are_refused(assignment):
    with pytest.raises(m.UpstoxMappingError):
        m.to_multi_order_params([(order(), "NSE_EQ|SYNTHETIC")], market_protection_by_index=assignment)


@pytest.mark.parametrize("assignment", [{"UNKNOWN": 1}, {"TARGET": 1}, {"STOPLOSS": 1}, {True: 1}, [], {"ENTRY": None}])
def test_u1_unknown_or_absent_rule_assignments_are_refused(assignment):
    single = order(stop_loss_price="0", target_price="0", stop_loss_trailing_gap="0")
    changes = replacement(type="SINGLE", stop_loss_price="0", target_price="0", stop_loss_trailing_gap="0")
    with pytest.raises(m.UpstoxMappingError):
        m.to_gtt_place_params(single, "NSE_EQ|SYNTHETIC", market_protection_by_strategy=assignment)
    with pytest.raises(m.UpstoxMappingError):
        m.to_gtt_modify_params("GTT-SYNTHETIC", changes, market_protection_by_strategy=assignment)


def test_u1_absent_gtt_and_batch_protection_stays_absent():
    assert all("market_protection" not in r for r in m.to_gtt_place_params(order(), "NSE_EQ|SYNTHETIC")["rules"])
    assert all("market_protection" not in r for r in m.to_gtt_modify_params("GTT-SYNTHETIC", replacement())["rules"])
    assert "market_protection" not in m.to_multi_order_params([(order(), "NSE_EQ|SYNTHETIC")])[0]


@pytest.mark.asyncio
async def test_u1_adapter_preserves_numeric_v3_batch_and_rule_intent():
    client = RecordingClient()
    adapter, session = adapter_session(client)
    await adapter.place_order(session, order(variety="iceberg", market_protection=25), _router_token=_ROUTER_TOKEN)
    await adapter.place_multi_order(session, [order(market_protection=0)], _router_token=_ROUTER_TOKEN)
    await adapter.place_order(
        session, order(variety="gtt", market_protection_by_strategy={"STOPLOSS": 1}), _router_token=_ROUTER_TOKEN,
    )
    assert [kind for kind, _params in client.calls] == ["v3", "multi", "gtt"]
    assert client.calls[0][1]["market_protection"] == 25
    assert client.calls[1][1][0]["market_protection"] == 0
    assert client.calls[2][1]["rules"][1]["market_protection"] == 1


@pytest.mark.asyncio
@pytest.mark.parametrize("variety,protection", [("regular", 1), ("amo", 0), ("iceberg", True), ("gtt", True)])
async def test_u1_adapter_refuses_unrepresented_or_boolean_protection_before_dispatch(variety, protection):
    client = RecordingClient()
    adapter, session = adapter_session(client)
    with pytest.raises(m.UpstoxMappingError, match="protection"):
        await adapter.place_order(session, order(variety=variety, market_protection=protection), _router_token=_ROUTER_TOKEN)
    assert client.calls == []


def test_u1_real_pinned_sdk_serialises_legacy_facade_protection_without_transport():
    from importlib.metadata import version

    import upstox_client

    assert version("upstox-python-sdk") == "2.30.0"
    serialiser = upstox_client.ApiClient()
    seen = []

    class Transport:
        def place_order(self, body):
            seen.append(("v3", serialiser.sanitize_for_serialization(body)))
            return SimpleNamespace(to_dict=lambda: {"status": "success"})

        def place_multi_order(self, body):
            seen.append(("multi", serialiser.sanitize_for_serialization(body)))
            return SimpleNamespace(to_dict=lambda: {"status": "success"})

        def place_gtt_order(self, body):
            seen.append(("gtt", serialiser.sanitize_for_serialization(body)))
            return SimpleNamespace(to_dict=lambda: {"status": "success"})

        def modify_gtt_order(self, body):
            seen.append(("gtt-modify", serialiser.sanitize_for_serialization(body)))
            return SimpleNamespace(to_dict=lambda: {"status": "success"})

    facade = object.__new__(UpstoxClient)
    facade._upstox = upstox_client
    facade._order = facade._order_v3 = Transport()
    facade.place_order_v3(m.to_place_order_v3_params(order(variety="iceberg"), "NSE_EQ|SYNTHETIC", market_protection=-1))
    facade.place_multi_order(m.to_multi_order_params([(order(), "NSE_EQ|SYNTHETIC")], market_protection_by_index={0: 0}))
    facade.place_gtt_order(m.to_gtt_place_params(order(), "NSE_EQ|SYNTHETIC", market_protection_by_strategy={"ENTRY": 1}))
    facade.modify_gtt_order(m.to_gtt_modify_params("GTT-SYNTHETIC", replacement(), market_protection_by_strategy={"STOPLOSS": 25}))
    assert [kind for kind, _body in seen] == ["v3", "multi", "gtt", "gtt-modify"]
    assert seen[0][1]["market_protection"] == -1 and seen[0][1]["slice"] is True
    assert seen[1][1][0]["market_protection"] == 0 and seen[1][1][0]["slice"] is False
    assert seen[2][1]["rules"][0]["market_protection"] == 1
    assert "market_protection" not in seen[2][1]["rules"][1]
    assert seen[3][1]["rules"][1]["market_protection"] == 25
    assert seen[3][1]["rules"][1]["trailing_gap"] == 0.5
    assert set(seen[3][1]) == {"type", "quantity", "gtt_order_id", "rules"}


@pytest.mark.parametrize("row", [
    {"quantity": 1, "filled_quantity": 2},
    {"quantity": "9007199254740992", "filled_quantity": "9007199254740993"},
    {"quantity": 10, "pending_quantity": 11},
    {"quantity": 10, "filled_quantity": 6, "pending_quantity": 5},
])
def test_r1_order_projection_rejects_contradictory_quantity_evidence(row):
    with pytest.raises(BrokerReadResponseInvalid):
        m.from_upstox_order({"order_id": "SYNTHETIC-ORDER", "status": "cancelled", **row})


@pytest.mark.parametrize("field", ["quantity", "filled_quantity", "pending_quantity"])
@pytest.mark.parametrize("value", [-1, "-1", 0.5, "0.5", True, "NaN", float("inf")])
def test_r1_order_projection_requires_nonnegative_whole_quantities(field, value):
    with pytest.raises(BrokerReadResponseInvalid):
        m.from_upstox_order({field: value})


def test_r1_order_projection_preserves_unknown_zero_and_cancelled_partial_fills():
    absent = m.from_upstox_order({"order_id": "SYNTHETIC-ORDER"})
    assert all(key not in absent for key in ("quantity", "filled_quantity", "pending_quantity"))
    cancelled = m.from_upstox_order({"status": "cancelled", "quantity": 100, "filled_quantity": 40, "pending_quantity": 0})
    assert cancelled["status"] == "cancelled"
    assert cancelled["quantity"] == "100" and cancelled["filled_quantity"] == "40" and cancelled["pending_quantity"] == "0"
    exact = m.from_upstox_order({"quantity": "100000000000000000000000000000001", "filled_quantity": "100000000000000000000000000000000"})
    assert exact["quantity"] == "100000000000000000000000000000001" and exact["pending_quantity"] == "1"
    assert m.from_upstox_position({"quantity": -10})["quantity"] == "-10"


@pytest.mark.asyncio
@pytest.mark.parametrize("verb", ["order_book", "order_details", "order_history"])
async def test_r1_actual_adapter_refuses_impossible_order_evidence(verb):
    row = {"order_id": "SYNTHETIC-ORDER", "quantity": 10, "filled_quantity": 11}
    client = SimpleNamespace(
        order_book=lambda: {"status": "success", "data": [row]},
        order_details=lambda _id: {"status": "success", "data": row},
        order_history=lambda _id, _tag: {"status": "success", "data": [row]},
    )
    adapter, session = adapter_session(client)
    with pytest.raises(BrokerReadResponseInvalid):
        if verb == "order_book":
            await adapter.order_book(session)
        else:
            await getattr(adapter, verb)(session, "SYNTHETIC-ORDER")


@pytest.mark.asyncio
@pytest.mark.parametrize("response", [None, {}, {"status": "success"}, {"status": "success", "data": []},
                                      {"status": "success", "data": None}, {"status": "success", "data": "bad"}])
async def test_r1_adapter_order_details_refuses_unavailable_or_malformed_envelope(response):
    client = SimpleNamespace(order_details=lambda _id: response)
    adapter, session = adapter_session(client)
    with pytest.raises(BrokerReadResponseInvalid):
        await adapter.order_details(session, "SYNTHETIC-ORDER")


@pytest.mark.asyncio
async def test_r1_adapter_order_details_refuses_error_envelope_even_with_a_valid_row():
    client = SimpleNamespace(order_details=lambda _id: {"status": "error", "data": {"quantity": 10}})
    adapter, session = adapter_session(client)
    with pytest.raises(m.UpstoxMappingError):
        await adapter.order_details(session, "SYNTHETIC-ORDER")


def gtt_row(**changes):
    row = {
        "gtt_order_id": "GTT-SYNTHETIC", "type": "MULTIPLE", "quantity": 10,
        "instrument_token": "NSE_EQ|SYNTHETIC", "product": "D", "status": "RESOURCE-UNKNOWN",
        "rules": [
            {"strategy": "ENTRY", "status": "COMPLETED", "trigger_type": "BELOW", "trigger_price": 99,
             "transaction_type": "BUY", "order_id": "SYNTHETIC-CHILD", "market_protection": -1, "message": "submitted"},
            {"strategy": "STOPLOSS", "status": "PENDING", "trigger_type": "IMMEDIATE", "trigger_price": 90,
             "transaction_type": "SELL", "order_id": None, "trailing_gap": 0.5, "market_protection": 0,
             "message": "awaiting entry", "broker_extension": {"source": "synthetic"}},
            {"strategy": "TARGET", "status": "FAILED", "trigger_type": "IMMEDIATE", "trigger_price": 110,
             "transaction_type": "SELL", "order_id": None, "market_protection": 25, "message": "synthetic rejection"},
        ],
        "created_at": 100, "expires_at": 200,
    }
    row.update(changes)
    return row


def test_u3_gtt_resource_and_entry_evidence_are_independent_and_lossless():
    source = gtt_row()
    observed = m.from_upstox_gtt_order(source)
    assert observed["status"] == observed["resource_status"] == "RESOURCE-UNKNOWN"
    assert observed["entry_status"] == "COMPLETED"
    assert observed["pricetype"] == ""
    assert observed["action"] == "BUY" and observed["quantity"] == "10"
    assert observed["rules"][0]["order_id"] == "SYNTHETIC-CHILD"
    assert observed["rules"][0]["market_protection"] == -1
    assert observed["rules"][1]["order_id"] == "" and observed["rules"][1]["transaction_type"] == "SELL"
    assert observed["rules"][1]["status"] == "PENDING" and observed["rules"][1]["trailing_gap"] == "0.5"
    assert observed["rules"][1]["market_protection"] == 0
    assert observed["rules"][2]["message"] == "synthetic rejection" and observed["rules"][2]["market_protection"] == 25
    assert observed["created_at"] == 100 and observed["expires_at"] == 200
    assert all(field not in observed for field in ("filled_quantity", "average_price", "position_closed", "protection_active"))
    assert observed["broker_fields"] == source and observed["broker_fields"] is not source
    observed["rules"][1]["broker_extension"]["source"] = "changed"
    assert source["rules"][1]["broker_extension"]["source"] == "synthetic"


@pytest.mark.parametrize("status", ["SCHEDULED", "TRIGGERED", "EXPIRED", "OPEN", "COMPLETED", "CANCELLED",
                                   "PENDING", "FAILED", "INACTIVE", "Unknown broker token"])
def test_u3_all_rule_statuses_survive_without_execution_inference(status):
    source = gtt_row()
    del source["status"]
    for rule in source["rules"]:
        rule["status"] = status
    observed = m.from_upstox_gtt_order(source)
    assert observed["status"] == observed["entry_status"] == status
    assert "resource_status" not in observed
    assert [rule["status"] for rule in observed["rules"]] == [status, status, status]
    assert "filled_quantity" not in observed


@pytest.mark.parametrize("strategy", ["ENTRY", "STOPLOSS", "TARGET", "entry"])
def test_u3_duplicate_gtt_strategies_are_refused(strategy):
    source = gtt_row()
    source["rules"].append({"strategy": strategy, "status": "FAILED", "message": "duplicate"})
    with pytest.raises(BrokerReadResponseInvalid):
        m.from_upstox_gtt_order(source)


@pytest.mark.parametrize("segment,exchange,product", [("NSE_EQ", "NSE", "CNC"), ("BSE_EQ", "BSE", "CNC"), ("NSE_FO", "NFO", "NRML")])
def test_u3_gtt_read_retains_segment_disambiguation_and_observed_execution_type(segment, exchange, product):
    source = gtt_row(instrument_token=f"{segment}|SYNTHETIC", exchange=segment)
    source["rules"][0]["trigger_type"] = "IMMEDIATE"
    observed = m.from_upstox_gtt_order(source)
    assert observed["exchange"] == exchange and observed["product"] == product
    assert observed["pricetype"] == "LIMIT"
    source["rules"][0]["trigger_type"] = "ABOVE"
    source["rules"][0]["order_type"] = "SL-M"
    assert m.from_upstox_gtt_order(source)["pricetype"] == "SL-M"


def test_u3_gtt_mapper_refuses_an_envelope_instead_of_a_resource():
    with pytest.raises(BrokerReadResponseInvalid):
        m.from_upstox_gtt_order({"status": "success", "data": [gtt_row()]})


@pytest.mark.asyncio
@pytest.mark.parametrize("verb", ["gtt_orders", "forever_orders"])
async def test_u3_actual_adapter_preserves_rule_status_and_rejection_evidence(verb):
    source = gtt_row()
    client = SimpleNamespace(gtt_order_details=lambda _id=None: {"status": "success", "data": [source]})
    adapter, session = adapter_session(client)
    observed, = await getattr(adapter, verb)(session)
    assert observed["entry_status"] == "COMPLETED" and observed["resource_status"] == "RESOURCE-UNKNOWN"
    assert observed["rules"][2]["message"] == "synthetic rejection"
    assert observed["rules"][1]["status"] == "PENDING" and observed["pricetype"] == ""
    source["rules"].append({"strategy": "ENTRY"})
    with pytest.raises(BrokerReadResponseInvalid):
        await getattr(adapter, verb)(session)


def multi_response(**changes):
    response = {
        "status": "partial_success",
        "data": [
            {"order_id": "SYNTHETIC-SLICE-1", "correlation_id": "1", "instrument_token": "NSE_EQ|SYNTHETIC",
             "status": "ACK", "broker_extension": {"child": 1}},
            {"order_id": "SYNTHETIC-SLICE-2", "correlation_id": "1", "status": "ACK"},
        ],
        "errors": [{"correlation_id": "2", "error_code": "SYNTHETIC-REJECT", "message": "synthetic rejection",
                    "property_path": "quantity", "invalid_value": 0, "broker_extension": {"detail": "retained"}}],
        "summary": {"total": 2, "success": 1, "error": 1, "payload_error": 0, "broker_extension": "retained"},
        "broker_extension": {"batch": "retained"},
    }
    response.update(changes)
    return response


def test_u4_multi_outcome_preserves_every_native_field_and_slice_child():
    source = multi_response()
    observed = m.from_upstox_multi_order(source)
    assert observed["status"] == "partial_success"
    assert observed["data"] == observed["order_results"] == source["data"]
    assert observed["errors"] == source["errors"] and observed["summary"] == source["summary"]
    assert observed["order_ids"] == ["SYNTHETIC-SLICE-1", "SYNTHETIC-SLICE-2"]
    assert observed["total"] == 2 and observed["success"] == 1
    assert observed["broker_extension"] == {"batch": "retained"}
    assert "filled_quantity" not in observed and "position_closed" not in observed
    observed["order_results"][0]["broker_extension"]["child"] = 9
    observed["errors"][0]["broker_extension"]["detail"] = "changed"
    assert source["data"][0]["broker_extension"]["child"] == 1
    assert source["errors"][0]["broker_extension"]["detail"] == "retained"


def test_u4_multi_payload_failure_preserves_error_only_and_missing_evidence():
    source = {
        "status": "error", "errors": [{"error_code": "SYNTHETIC-PAYLOAD", "message": "invalid quantity", "correlation_id": "2"}],
        "summary": {"total": 2, "success": 0, "error": 0, "payload_error": 1},
    }
    observed = m.from_upstox_multi_order(source)
    assert observed["errors"] == source["errors"] and observed["summary"] == source["summary"]
    assert observed["status"] == "error" and observed["total"] == 2 and observed["success"] == 0
    assert "order_ids" not in observed and "order_results" not in observed and "data" not in observed
    del source["summary"]
    observed = m.from_upstox_multi_order(source)
    assert all(field not in observed for field in ("total", "success", "summary", "order_ids", "order_results"))


def test_u4_multi_request_accepts_ten_lines_but_refuses_eleven():
    pairs = [(order(variety="iceberg"), "NSE_EQ|SYNTHETIC") for _ in range(10)]
    observed = m.to_multi_order_params(pairs, tag="synthetic-tag")
    assert len(observed) == 10
    assert [row["correlation_id"] for row in observed] == ["1", "2", "3", "4", "5", "6", "7", "8", "9", "10"]
    assert all(row["slice"] is True and row["is_amo"] is False and row["tag"] == "synthetic-tag" for row in observed)
    with pytest.raises(m.UpstoxMappingError):
        m.to_multi_order_params([*pairs, (order(), "NSE_EQ|SYNTHETIC")])


@pytest.mark.parametrize("field,value", [
    ("data", {}), ("data", "bad"), ("data", ["bad"]), ("data", [{}]),
    ("data", [{"order_id": None, "correlation_id": "1"}]),
    ("data", [{"order_id": " PADDED ", "correlation_id": "1"}]),
    ("data", [{"order_id": "SYNTHETIC", "correlation_id": True}]),
    ("data", [{"order_id": "SYNTHETIC", "correlation_id": "1"}, {"order_id": "SYNTHETIC", "correlation_id": "2"}]),
    ("errors", {}), ("errors", "bad"), ("errors", ["bad"]), ("errors", [{}]),
    ("summary", []), ("summary", "bad"), ("status", "unknown"), ("status", True), ("status", "success"),
])
def test_u4_multi_malformed_rows_lists_and_contradictory_status_are_refused(field, value):
    with pytest.raises(m.UpstoxMappingError):
        m.from_upstox_multi_order(multi_response(**{field: value}))


@pytest.mark.parametrize("field", ["total", "success", "error", "payload_error"])
@pytest.mark.parametrize("value", [True, False, 1.5, 1.0, "1.5", "NaN", float("inf"), -1])
def test_u4_multi_counts_are_exact_nonnegative_integers(field, value):
    source = multi_response()
    source["summary"][field] = value
    with pytest.raises(m.UpstoxMappingError):
        m.from_upstox_multi_order(source)


@pytest.mark.parametrize("summary", [
    {"total": 2, "success": 2, "error": 1, "payload_error": 0},
    {"total": 1, "success": 2, "error": 1, "payload_error": 0},
    {"total": 2, "success": 1, "error": 1, "payload_error": 1},
    {"total": 2, "success": 0, "error": 2, "payload_error": 0},
])
def test_u4_multi_contradictory_summary_is_refused(summary):
    with pytest.raises(m.UpstoxMappingError):
        m.from_upstox_multi_order(multi_response(summary=summary))


def test_u4_all_success_status_cannot_hide_missing_input_line_outcomes():
    with pytest.raises(m.UpstoxMappingError):
        m.from_upstox_multi_order(multi_response(status="success", errors=[], summary={"total": 2, "success": 1}))


def test_u4_multi_counts_preserve_native_strings_without_float_conversion():
    source = multi_response(summary={"total": "2", "success": "1", "error": "1", "payload_error": "0"})
    observed = m.from_upstox_multi_order(source)
    assert observed["summary"] == {"total": "2", "success": "1", "error": "1", "payload_error": "0"}
    assert observed["total"] == 2 and type(observed["total"]) is int
    assert observed["success"] == 1 and type(observed["success"]) is int


@pytest.mark.asyncio
async def test_u4_actual_adapter_preserves_partial_slice_outcomes_and_refuses_oversized_request():
    source = multi_response()
    client = RecordingClient()

    def submit(params):
        client.calls.append(("multi", params))
        return source

    client.place_multi_order = submit
    adapter, session = adapter_session(client)
    observed = await adapter.place_multi_order(session, [order(variety="iceberg"), order(variety="amo")], _router_token=_ROUTER_TOKEN)
    assert observed["data"] == source["data"] and observed["summary"] == source["summary"]
    assert observed["errors"][0]["message"] == "synthetic rejection" and observed["success"] == 1
    assert observed["order_ids"] == ["SYNTHETIC-SLICE-1", "SYNTHETIC-SLICE-2"]
    assert client.calls[0][1][0]["slice"] is True and client.calls[0][1][1]["is_amo"] is True
    client.calls.clear()
    with pytest.raises(m.UpstoxMappingError):
        await adapter.place_multi_order(session, [order() for _ in range(11)], _router_token=_ROUTER_TOKEN)
    assert client.calls == []


def test_u4_pinned_sdk_null_optional_fields_are_preserved_as_unknown_not_empty():
    import upstox_client

    source = upstox_client.MultiOrderResponse(
        status="success", data=[upstox_client.MultiOrderData(order_id="SYNTHETIC-ORDER", correlation_id="1")],
        summary=upstox_client.MultiOrderSummary(total=1, success=1),
    ).to_dict()
    assert source["errors"] is None and source["summary"]["error"] is None
    observed = m.from_upstox_multi_order(source)
    assert observed["errors"] is None and observed["summary"] == source["summary"]
    assert observed["order_ids"] == ["SYNTHETIC-ORDER"] and observed["success"] == 1


@pytest.mark.asyncio
async def test_u5_sliced_placement_returns_all_child_ids_with_string_compatibility():
    import json

    client = RecordingClient()
    adapter, session = adapter_session(client)
    acknowledgement = await adapter.place_order(session, order(variety="iceberg"), _router_token=_ROUTER_TOKEN)
    assert isinstance(acknowledgement, str) and acknowledgement == "SYNTHETIC-SLICE-1"
    assert json.dumps(acknowledgement) == '"SYNTHETIC-SLICE-1"'
    assert acknowledgement.order_ids == ("SYNTHETIC-SLICE-1", "SYNTHETIC-SLICE-2")
    assert acknowledgement.broker_response == {
        "status": "success", "data": {"order_ids": ["SYNTHETIC-SLICE-1", "SYNTHETIC-SLICE-2"]},
    }
    assert "filled_quantity" not in acknowledgement.broker_response and "position_closed" not in acknowledgement.broker_response


@pytest.mark.parametrize("response", [
    {"status": "error", "data": {"order_ids": ["SYNTHETIC-ID"]}},
    {"status": "success", "errors": [{"message": "synthetic rejection"}], "data": {"order_id": "SYNTHETIC-ID"}},
    {"status": "success", "data": {"order_ids": ["SYNTHETIC-ID", "SYNTHETIC-ID"]}},
    {"status": "success", "data": {"order_ids": ["SYNTHETIC-ID", " PADDED "]}},
    {"status": "success", "data": {"order_ids": ["SYNTHETIC-ID", None]}},
    {"status": "success", "data": {"order_ids": ["SYNTHETIC-ID", 1]}},
    {"status": "success", "data": {"order_ids": []}},
    {"status": "success", "data": {"order_ids": "SYNTHETIC-ID"}},
    {"status": "success", "data": {"order_ids": ["SYNTHETIC-ID"], "order_id": "CONFLICTING-ID"}},
])
def test_u5_legacy_extractor_refuses_every_invalid_child_and_error_ids(response):
    with pytest.raises(m.UpstoxMappingError):
        m.extract_order_id(response)


@pytest.mark.asyncio
@pytest.mark.parametrize("response", [
    {"status": "error", "data": {"order_ids": ["SYNTHETIC-ID"]}},
    {"status": "success", "data": {"order_ids": ["SYNTHETIC-ID", "SYNTHETIC-ID"]}},
    {"status": "success", "data": {"order_ids": ["SYNTHETIC-ID", "BAD ID"]}},
])
async def test_u5_actual_adapter_refuses_invalid_sliced_acknowledgements(response):
    client = SimpleNamespace(place_order_v3=lambda _params: response)
    adapter, session = adapter_session(client)
    with pytest.raises(m.UpstoxMappingError):
        await adapter.place_order(session, order(variety="iceberg"), _router_token=_ROUTER_TOKEN)


@pytest.mark.asyncio
async def test_u5_each_attempt_keeps_detached_ids_and_native_response_without_durable_claims():
    source = {"status": "success", "data": {"order_ids": ["SYNTHETIC-FIRST", "SYNTHETIC-SECOND"]},
              "metadata": {"state": "synthetic acknowledgement"}}
    client = SimpleNamespace(place_order_v3=lambda _params: source)
    adapter, session = adapter_session(client)
    first = await adapter.place_order(session, order(variety="iceberg"), _router_token=_ROUTER_TOKEN)
    source["data"]["order_ids"] = ["SYNTHETIC-NEXT"]
    source["metadata"]["state"] = "next acknowledgement"
    second = await adapter.place_order(session, order(variety="iceberg"), _router_token=_ROUTER_TOKEN)
    assert first.order_ids == ("SYNTHETIC-FIRST", "SYNTHETIC-SECOND") and second.order_ids == ("SYNTHETIC-NEXT",)
    assert first.broker_response["metadata"]["state"] == "synthetic acknowledgement"
    assert "readiness" not in first.broker_response and "durable" not in first.broker_response


@pytest.mark.parametrize("family", ["margin", "convert"])
@pytest.mark.parametrize("quantity", [True, "1.5", "NaN", "Infinity", 0, -1])
def test_u2_remaining_quantity_callers_reject_lossy_intent(family, quantity):
    with pytest.raises(m.UpstoxMappingError):
        request(family, quantity)


@pytest.mark.parametrize("family", ["margin", "convert"])
def test_u2_remaining_quantity_callers_preserve_exact_units(family):
    assert request(family, "9007199254740993")["quantity"] == 9007199254740993


@pytest.mark.asyncio
async def test_u5_sliced_acknowledgement_keeps_evidence_through_a_deep_copy():
    from copy import deepcopy

    client = RecordingClient()
    adapter, session = adapter_session(client)
    original = await adapter.place_order(session, order(variety="iceberg"), _router_token=_ROUTER_TOKEN)
    copied = deepcopy(original)
    assert copied == "SYNTHETIC-SLICE-1" and copied.order_ids == ("SYNTHETIC-SLICE-1", "SYNTHETIC-SLICE-2")
    assert copied.broker_response == original.broker_response and copied.broker_response is not original.broker_response


@pytest.mark.parametrize("field", ["trigger_price", "stop_loss_price", "target_price", "stop_loss_trailing_gap"])
@pytest.mark.parametrize("value", [True, False, -1, "NaN", float("inf"), "not-numeric"])
def test_u3_gtt_invalid_rule_numbers_cannot_dispatch_or_silently_drop_protective_intent(field, value):
    with pytest.raises(m.UpstoxMappingError):
        m.to_gtt_place_params(order(**{field: value}), "NSE_EQ|SYNTHETIC")
    with pytest.raises(m.UpstoxMappingError):
        m.to_gtt_modify_params("GTT-SYNTHETIC", replacement(**{field: value}))


@pytest.mark.asyncio
async def test_u3_adapter_refuses_invalid_target_before_gtt_dispatch():
    client = RecordingClient()
    adapter, session = adapter_session(client)
    with pytest.raises(m.UpstoxMappingError):
        await adapter.place_order(session, order(variety="gtt", target_price="NaN"), _router_token=_ROUTER_TOKEN)
    assert client.calls == []


@pytest.mark.parametrize("response", [
    {"status": "error", "data": {"gtt_order_ids": ["GTT-SYNTHETIC"]}},
    {"status": "success", "data": {"gtt_order_ids": ["GTT-SYNTHETIC", "GTT-SYNTHETIC"]}},
    {"status": "success", "data": {"gtt_order_ids": ["GTT-SYNTHETIC", " PADDED "]}},
    {"status": "success", "data": {"gtt_order_id": True}},
])
def test_u5_gtt_placement_extractor_rejects_error_or_invalid_resource_ids(response):
    with pytest.raises(m.UpstoxMappingError):
        m.extract_gtt_order_id(response)


@pytest.mark.asyncio
async def test_u5_actual_gtt_placement_retains_every_resource_id_and_refuses_error_ids():
    source = {"status": "success", "data": {"gtt_order_ids": ["GTT-SYNTHETIC-1", "GTT-SYNTHETIC-2"]}}
    client = SimpleNamespace(place_gtt_order=lambda _params: source)
    adapter, session = adapter_session(client)
    observed = await adapter.place_order(session, order(variety="gtt"), _router_token=_ROUTER_TOKEN)
    assert observed == "GTT-SYNTHETIC-1" and observed.order_ids == ("GTT-SYNTHETIC-1", "GTT-SYNTHETIC-2")
    assert observed.broker_response == source
    source["status"] = "error"
    with pytest.raises(m.UpstoxMappingError):
        await adapter.place_order(session, order(variety="gtt"), _router_token=_ROUTER_TOKEN)
