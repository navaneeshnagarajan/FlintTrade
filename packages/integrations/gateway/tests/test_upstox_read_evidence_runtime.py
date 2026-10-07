"""Native GTT observations at the real managed-session typed read seam.

SDK resources run normally; only their HTTP transport is inert. Raw resource
extensions are distinct from the pin's narrower deserialised model schema.
"""

from __future__ import annotations

import copy
import json
from copy import deepcopy
from dataclasses import FrozenInstanceError, asdict
from importlib.metadata import version
from types import SimpleNamespace

import pytest
import upstox_client

from flinttrade_core.broker_read_port import (
    BrokerOrderFamily,
    BrokerReadErrorCode,
    BrokerReadFailure,
    BrokerReadSuccess,
    OrderStateRequest,
)
from flinttrade_gateway.brokers._base import Session
from flinttrade_gateway.brokers.upstox import UpstoxAdapter, UpstoxClient
from packages.integrations.gateway.tests import test_broker_read_concrete_adapters as read_fixtures

bind_adapter = read_fixtures.bind_adapter
pytestmark = pytest.mark.integration


def native_resource() -> dict:
    """SP-02's observed facade-returned resource, using synthetic identities.

    Resource status/protection are extension observations. The 2.30.0 response
    model omits those properties; this does not claim it deserialises them.
    """
    return {
        "gtt_order_id": "GTT-SYNTHETIC", "status": "PENDING", "type": "MULTIPLE", "trading_symbol": "TCS",
        "instrument_token": "NSE_EQ|INE467B01029", "exchange": "NSE", "product": "D", "quantity": 10,
        "rules": [
            {"strategy": "ENTRY", "status": "COMPLETED", "trigger_type": "IMMEDIATE", "trigger_price": 100,
             "transaction_type": "BUY", "order_id": "ENTRY-SYNTHETIC", "message": "accepted", "market_protection": -1},
            {"strategy": "STOPLOSS", "status": "PENDING", "trigger_type": "IMMEDIATE", "trigger_price": 90,
             "transaction_type": "SELL", "order_id": None, "message": "waiting", "market_protection": 5,
             "trailing_gap": 2},
        ],
    }


@pytest.fixture
def read_stack(bind_adapter, monkeypatch):
    assert version("upstox-python-sdk") == "2.30.0"
    facade = UpstoxClient("synthetic-not-a-broker-token")
    assert type(facade._order_v3) is upstox_client.OrderApiV3
    response = upstox_client.GetGttOrderResponse(status="success", data=[native_resource()])
    calls = []

    def transport(path, method, path_params, query_params, header_params, **kwargs):
        assert (path, method, path_params, query_params) == ("/v3/order/gtt", "GET", {}, [])
        assert kwargs["response_type"] == "GetGttOrderResponse"
        assert kwargs["body"] is None
        calls.append((path, method))
        return response

    monkeypatch.setattr(facade._order_v3.api_client, "call_api", transport)
    adapter = UpstoxAdapter(client_factory=lambda _session: facade)
    bound = bind_adapter("upstox", adapter, facade)
    return SimpleNamespace(facade=facade, adapter=adapter, bound=bound, response=response, calls=calls)


async def test_native_rule_evidence_survives_a_successful_actual_bound_port(read_stack) -> None:
    stack = read_stack
    upstream = await stack.adapter.forever_orders(Session("synthetic", 4102444800.0, "Synthetic", "upstox"))
    observed = upstream[0]
    assert (observed["status"], observed["resource_status"], observed["entry_status"]) == (
        "PENDING", "PENDING", "COMPLETED",
    )
    assert observed["rules"][1]["message"] == "waiting"
    assert observed["rules"][1]["market_protection"] == 5
    assert observed["stop_loss_trailing_gap"] == "2"
    result = await stack.bound.port.order_states(OrderStateRequest(BrokerOrderFamily.FOREVER))
    assert isinstance(result, BrokerReadSuccess)
    row = result.value[0]
    # Assert the upstream and successful read first: a guarded refusal is not
    # evidence of successful typed projection losing data.
    evidence = json.loads(row.raw_observation_json)
    for name in ("gtt_order_id", "type", "resource_status", "entry_status", "rules", "stop_loss_trailing_gap"):
        assert evidence[name] == observed[name]
    assert evidence["broker_fields"] == native_resource()
    assert row.status == "PENDING" and row.filled_quantity is None
    assert row.orderid == "GTT-SYNTHETIC" and row.legs == ()
    assert row.exchange_order_id is None and row.quantity == "10"
    assert "protection_active" not in evidence and "position_closed" not in evidence
    assert stack.calls == [("/v3/order/gtt", "GET")] * 2


async def test_malformed_supplied_native_numeric_alias_refuses_the_bound_read(read_stack) -> None:
    read_stack.response.data[0]["rules"][1]["trailingGap"] = "NaN"

    assert await read_stack.bound.port.order_states(OrderStateRequest(BrokerOrderFamily.FOREVER)) == BrokerReadFailure(
        BrokerReadErrorCode.MALFORMED_RESPONSE,
    )


async def test_official_pinned_response_models_preserve_nulls_and_native_epoch_times(read_stack) -> None:
    entry = upstox_client.Rule(
        strategy="ENTRY", status="PENDING", trigger_type="BELOW", trigger_price=100, transaction_type="BUY",
    )
    stop = upstox_client.Rule(strategy="STOPLOSS")
    native = upstox_client.GttOrderDetails(
        type="MULTIPLE", exchange="NSE", quantity=10, product="D", rules=[entry, stop], trading_symbol="TCS",
        instrument_token="NSE_EQ|INE467B01029", gtt_order_id="GTT-SYNTHETIC",
        created_at=1718272000123, expires_at=1749808000123,
    )
    read_stack.response.data = [native]
    upstream = await read_stack.adapter.forever_orders(Session("synthetic", 4102444800.0, "Synthetic", "upstox"))
    assert "resource_status" not in upstream[0] and upstream[0]["entry_status"] == "PENDING"
    assert upstream[0]["broker_fields"] == native.to_dict()
    result = await read_stack.bound.port.order_states(OrderStateRequest(BrokerOrderFamily.FOREVER))
    assert isinstance(result, BrokerReadSuccess)
    row = result.value[0]
    evidence = json.loads(row.raw_observation_json)
    assert evidence["broker_fields"] == native.to_dict()
    assert evidence["created_at"] == 1718272000123 and evidence["expires_at"] == 1749808000123
    assert row.created_at == "1718272000123"
    assert "resource_status" not in evidence
    assert "market_protection" not in evidence["rules"][0]
    assert evidence["broker_fields"]["rules"][1] == {
        "strategy": "STOPLOSS", "status": None, "message": None, "trigger_type": None, "trigger_price": None,
        "transaction_type": None, "order_id": None, "trailing_gap": None,
    }
    assert row.price == "100" and row.pricetype is None and row.filled_quantity is None and row.legs == ()


@pytest.mark.parametrize("field,value", [
    ("resource_status", "COMPLETED"), ("entry_status", "PENDING"), ("stop_loss_trailing_gap", "3"),
])
async def test_conflicting_projected_rule_or_resource_aliases_refuse_the_actual_bound_port(
    read_stack, monkeypatch, field, value,
) -> None:
    # Exercise the projection with a corrupted already-returned adapter row;
    # do not replace the owner or manufacture an alternative read facade.
    rows = await read_stack.adapter.forever_orders(Session("synthetic", 4102444800.0, "Synthetic", "upstox"))
    rows[0][field] = value

    async def returned(_session):
        return rows

    monkeypatch.setattr(read_stack.adapter, "forever_orders", returned)
    assert await read_stack.bound.port.order_states(OrderStateRequest(BrokerOrderFamily.FOREVER)) == BrokerReadFailure(
        BrokerReadErrorCode.MALFORMED_RESPONSE,
    )


@pytest.mark.parametrize("field", ["message", "order_id", "trailing_gap", "market_protection", "trigger_price"])
@pytest.mark.parametrize("presence", ["absent", "null", "blank"])
async def test_native_optional_presence_does_not_default_protection_or_children(read_stack, field, presence) -> None:
    native = read_stack.response.data[0]
    if presence == "absent":
        native["rules"][1].pop(field, None)
    else:
        native["rules"][1][field] = None if presence == "null" else ""
    result = await read_stack.bound.port.order_states(OrderStateRequest(BrokerOrderFamily.FOREVER))
    assert isinstance(result, BrokerReadSuccess)
    row = result.value[0]
    evidence = json.loads(row.raw_observation_json)
    assert evidence["broker_fields"] == native
    raw_rule = evidence["broker_fields"]["rules"][1]
    if presence == "absent":
        assert field not in raw_rule
    else:
        assert raw_rule[field] == (None if presence == "null" else "")
    assert row.filled_quantity is None and row.exchange_order_id is None and row.legs == ()
    assert "protection_active" not in evidence and "effective_protection" not in evidence


@pytest.mark.parametrize("field", ["trigger_price", "trailing_gap", "market_protection", "triggeredQuantity"])
@pytest.mark.parametrize("value", [0, 9007199254740993, "9007199254740993", "3.50"])
async def test_native_numbers_and_extensions_are_exact_and_deeply_detached(read_stack, field, value) -> None:
    native = read_stack.response.data[0]
    native["rules"][1][field] = value
    native["rules"][1]["extension"] = {"rows": [None, False, "", {"large": 9007199254740993, "decimal": "3.50"}]}
    original = deepcopy(native)
    result = await read_stack.bound.port.order_states(OrderStateRequest(BrokerOrderFamily.FOREVER))
    assert isinstance(result, BrokerReadSuccess)
    row = result.value[0]
    encoded = row.raw_observation_json
    assert json.loads(encoded)["broker_fields"] == original
    assert json.loads(encoded)["broker_fields"]["rules"][1][field] == value
    native["rules"][1]["extension"]["rows"][3]["large"] = 1
    assert json.loads(encoded)["broker_fields"] == original
    assert row.filled_quantity is None
    assert json.loads(json.dumps(asdict(row)))["raw_observation_json"] == encoded
    with pytest.raises(FrozenInstanceError):
        row.raw_observation_json = "{}"
    assert not hasattr(row, "__dict__")


@pytest.mark.parametrize("status", [
    "SCHEDULED", "TRIGGERED", "EXPIRED", "OPEN", "COMPLETED", "CANCELLED", "PENDING", "FAILED", "INACTIVE",
    "Unknown broker token", "CANCEL_PENDING",
])
async def test_each_native_status_remains_independent_without_execution_inference(read_stack, status) -> None:
    native = read_stack.response.data[0]
    native["rules"][0]["status"] = status
    native["rules"][1]["status"] = "CANCEL_PENDING"
    result = await read_stack.bound.port.order_states(OrderStateRequest(BrokerOrderFamily.FOREVER))
    assert isinstance(result, BrokerReadSuccess)
    row = result.value[0]
    evidence = json.loads(row.raw_observation_json)
    assert row.status == evidence["resource_status"] == "PENDING"
    assert evidence["entry_status"] == evidence["rules"][0]["status"] == status
    assert evidence["rules"][1]["status"] == "CANCEL_PENDING"
    assert evidence["broker_fields"] == native
    assert row.filled_quantity is None and row.legs == ()


@pytest.mark.parametrize("native_key", [
    "trigger_price", "triggerPrice", "trailing_gap", "trailingGap", "market_protection", "marketProtection",
    "quantity", "filled_quantity", "filledQty", "tradedQty", "remaining_quantity", "remainingQuantity",
    "triggered_quantity", "triggeredQuantity",
])
@pytest.mark.parametrize("value", [True, "NaN", "bad", float("inf"), object()])
async def test_every_supplied_rule_numeric_alias_is_validated(read_stack, native_key, value) -> None:
    read_stack.response.data[0]["rules"][1][native_key] = value
    assert await read_stack.bound.port.order_states(OrderStateRequest(BrokerOrderFamily.FOREVER)) == BrokerReadFailure(
        BrokerReadErrorCode.MALFORMED_RESPONSE,
    )


@pytest.mark.parametrize("changes", [
    {"triggerPrice": 91}, {"trailingGap": 3}, {"marketProtection": 6}, {"orderId": "unknown-child"},
    {"transactionType": "BUY"}, {"orderStatus": "CANCEL_PENDING"},
    {"filledQty": 1, "tradedQty": 2}, {"parent_order_id": "one", "parentOrderId": "two"},
    {"remaining_quantity": 1, "remainingQuantity": 2}, {"triggered_quantity": 1, "triggeredQuantity": 2},
])
async def test_conflicting_native_rule_aliases_are_malformed_not_a_known_empty_book(read_stack, changes) -> None:
    native = read_stack.response.data[0]
    native["rules"][1].update(changes)
    # Null native child IDs do not conflict with a genuinely observed alias;
    # use a known native value for the child-ID conflict control.
    if "orderId" in changes:
        native["rules"][1]["order_id"] = "stop-child"
    assert await read_stack.bound.port.order_states(OrderStateRequest(BrokerOrderFamily.FOREVER)) == BrokerReadFailure(
        BrokerReadErrorCode.MALFORMED_RESPONSE,
    )


@pytest.mark.parametrize("native_key", [
    "message", "order_id", "orderId", "exchange_order_id", "exchangeOrderId", "parent_order_id", "parentOrderId",
    "status", "orderStatus", "trigger_type", "triggerType", "transaction_type", "transactionType",
])
async def test_every_supplied_rule_text_alias_rejects_opaque_or_non_text_values(read_stack, native_key) -> None:
    read_stack.response.data[0]["rules"][1][native_key] = 42
    assert await read_stack.bound.port.order_states(OrderStateRequest(BrokerOrderFamily.FOREVER)) == BrokerReadFailure(
        BrokerReadErrorCode.MALFORMED_RESPONSE,
    )


@pytest.mark.parametrize("rules", [None, {}, [None], [], [{"strategy": "STOPLOSS"}], [{"strategy": "UNKNOWN"}]])
async def test_incomplete_rules_do_not_become_complete_empty_evidence(read_stack, rules) -> None:
    read_stack.response.data[0]["rules"] = rules
    assert await read_stack.bound.port.order_states(OrderStateRequest(BrokerOrderFamily.FOREVER)) == BrokerReadFailure(
        BrokerReadErrorCode.MALFORMED_RESPONSE,
    )


@pytest.mark.parametrize("status", ["ACTIVE", "OPEN", "Unknown broker token"])
async def test_missing_confirmed_fill_still_refuses_non_pretrigger_resource_states(read_stack, status) -> None:
    read_stack.response.data[0]["status"] = status
    assert await read_stack.bound.port.order_states(OrderStateRequest(BrokerOrderFamily.FOREVER)) == BrokerReadFailure(
        BrokerReadErrorCode.MALFORMED_RESPONSE,
    )


async def test_genuine_empty_sdk_collection_is_distinct_from_unavailable_evidence(read_stack) -> None:
    read_stack.response.data = []
    result = await read_stack.bound.port.order_states(OrderStateRequest(BrokerOrderFamily.FOREVER))
    assert isinstance(result, BrokerReadSuccess) and result.value == ()
    read_stack.response.data = None
    assert await read_stack.bound.port.order_states(OrderStateRequest(BrokerOrderFamily.FOREVER)) == BrokerReadFailure(
        BrokerReadErrorCode.MALFORMED_RESPONSE,
    )


async def test_resource_status_absence_is_not_relabelled_from_entry_or_envelope(read_stack) -> None:
    native = read_stack.response.data[0]
    native.pop("status")
    native["rules"][0]["status"] = "PENDING"
    result = await read_stack.bound.port.order_states(OrderStateRequest(BrokerOrderFamily.FOREVER))
    assert isinstance(result, BrokerReadSuccess)
    row = result.value[0]
    evidence = json.loads(row.raw_observation_json)
    assert row.status == evidence["entry_status"] == "PENDING"
    assert "resource_status" not in evidence and "status" not in evidence["broker_fields"]
    assert row.filled_quantity is None


async def test_rule_observations_do_not_grant_write_methods_and_keep_bound_provenance(read_stack) -> None:
    bound = read_stack.bound
    request = OrderStateRequest(BrokerOrderFamily.FOREVER)
    result = await bound.port.order_states(request)
    assert isinstance(result, BrokerReadSuccess)
    binding = bound.registry.snapshot_exact_state(bound.selector).binding
    assert result.provenance.selector == bound.selector
    assert result.provenance.registry_version == binding.registry_version
    assert result.provenance.credential_version == binding.credential_version
    assert result.provenance.workspace_version == binding.workspace_version
    assert result.provenance.broker_workspace_version == binding.broker_workspace_version
    assert result.provenance.requested_role is None
    assert not any(hasattr(bound.port, name) for name in ("place_order", "cancel_order", "modify_order"))
    before = len(read_stack.calls)
    assert await copy.copy(bound.port).order_states(request) == BrokerReadFailure(BrokerReadErrorCode.REVOKED)
    assert await copy.deepcopy(bound.port).order_states(request) == BrokerReadFailure(BrokerReadErrorCode.REVOKED)
    object.__setattr__(request, "family", "forever")
    assert await bound.port.order_states(request) == BrokerReadFailure(BrokerReadErrorCode.INVALID_REQUEST)
    assert len(read_stack.calls) == before
    bound.authority_context[0] = None
    assert await bound.port.order_states(OrderStateRequest(BrokerOrderFamily.FOREVER)) == BrokerReadFailure(
        BrokerReadErrorCode.UNAUTHORISED,
    )
    assert len(read_stack.calls) == before


async def test_conflicting_native_copy_cannot_disagree_with_retained_normalised_rule(read_stack, monkeypatch) -> None:
    rows = await read_stack.adapter.forever_orders(Session("synthetic", 4102444800.0, "Synthetic", "upstox"))
    rows[0]["broker_fields"]["rules"][1]["market_protection"] = 6

    async def returned(_session):
        return rows

    monkeypatch.setattr(read_stack.adapter, "forever_orders", returned)
    assert await read_stack.bound.port.order_states(OrderStateRequest(BrokerOrderFamily.FOREVER)) == BrokerReadFailure(
        BrokerReadErrorCode.MALFORMED_RESPONSE,
    )


@pytest.mark.parametrize("extension", ["opaque", "tuple", "non-string-key"])
async def test_unsafe_json_extensions_refuse_without_conversion_or_copy_hooks(read_stack, monkeypatch, extension) -> None:
    class HookTrap:
        def __init__(self):
            self.calls = []

        def __str__(self):
            self.calls.append("str")
            raise AssertionError("observation conversion hook ran")

        def __float__(self):
            self.calls.append("float")
            raise AssertionError("observation conversion hook ran")

        def __deepcopy__(self, memo):
            self.calls.append("deepcopy")
            raise AssertionError("observation copy hook ran")

    trap = HookTrap()
    rows = await read_stack.adapter.forever_orders(Session("synthetic", 4102444800.0, "Synthetic", "upstox"))
    unsafe = {"opaque": trap, "tuple": (1,), "non-string-key": {1: "value"}}[extension]
    rows[0]["broker_fields"]["rules"][1]["extension"] = {"children": [unsafe]}

    async def returned(_session):
        return rows

    monkeypatch.setattr(read_stack.adapter, "forever_orders", returned)
    assert await read_stack.bound.port.order_states(OrderStateRequest(BrokerOrderFamily.FOREVER)) == BrokerReadFailure(
        BrokerReadErrorCode.MALFORMED_RESPONSE,
    )
    assert trap.calls == []


async def test_native_observation_slot_is_additive_and_strictly_immutable(read_stack) -> None:
    from dataclasses import replace

    result = await read_stack.bound.port.order_states(OrderStateRequest(BrokerOrderFamily.FOREVER))
    assert isinstance(result, BrokerReadSuccess)
    row = result.value[0]
    assert replace(row, raw_observation_json=None).raw_observation_json is None

    class StringSubclass(str):
        pass

    for invalid in (False, {}, [], StringSubclass("{}")):
        with pytest.raises(ValueError, match="broker_read_contract_invalid"):
            replace(row, raw_observation_json=invalid)


@pytest.mark.parametrize("field,value", [("status", "OPEN"), ("gtt_order_id", "OTHER-GTT"), ("type", "SINGLE")])
async def test_conflicting_native_resource_copy_refuses_the_bound_read(read_stack, monkeypatch, field, value) -> None:
    rows = await read_stack.adapter.forever_orders(Session("synthetic", 4102444800.0, "Synthetic", "upstox"))
    rows[0]["broker_fields"][field] = value

    async def returned(_session):
        return rows

    monkeypatch.setattr(read_stack.adapter, "forever_orders", returned)
    assert await read_stack.bound.port.order_states(OrderStateRequest(BrokerOrderFamily.FOREVER)) == BrokerReadFailure(
        BrokerReadErrorCode.MALFORMED_RESPONSE,
    )


@pytest.mark.parametrize("containers", [64, 65])
async def test_native_rule_json_depth_is_enforced_at_the_real_bound_port(read_stack, containers) -> None:
    # The longest branch includes snapshot row, native resource, rules list and
    # rule dict before this diagnostic; primitives below the limit are valid.
    diagnostic = None
    for _ in range(containers - 4):
        diagnostic = {"child": diagnostic}
    read_stack.response.data[0]["rules"][1]["diagnostic"] = diagnostic
    result = await read_stack.bound.port.order_states(OrderStateRequest(BrokerOrderFamily.FOREVER))
    if containers == 64:
        assert isinstance(result, BrokerReadSuccess)
        assert json.loads(result.value[0].raw_observation_json)["broker_fields"]["rules"][1]["diagnostic"] == diagnostic
    else:
        assert result == BrokerReadFailure(BrokerReadErrorCode.MALFORMED_RESPONSE)


async def test_regular_sdk_order_keeps_existing_fields_without_inventing_gtt_observations(read_stack, monkeypatch) -> None:
    response = upstox_client.GetOrderBookResponse(status="success", data=[upstox_client.OrderData(
        order_id="REGULAR-SYNTHETIC", status="open", exchange="NSE", trading_symbol="TCS", product="D",
        instrument_token="NSE_EQ|INE467B01029", transaction_type="BUY", quantity=10, filled_quantity=0,
        price=100, trigger_price=0, order_type="LIMIT", disclosed_quantity=0, validity="DAY",
    )])

    def transport(path, method, path_params, query_params, header_params, **kwargs):
        assert (path, method, path_params, query_params) == ("/v2/order/retrieve-all", "GET", {}, [])
        assert header_params["Api-Version"] == "v2"
        assert kwargs["response_type"] == "GetOrderBookResponse" and kwargs["body"] is None
        read_stack.calls.append((path, method))
        return response

    monkeypatch.setattr(read_stack.facade._order.api_client, "call_api", transport)
    result = await read_stack.bound.port.order_states(OrderStateRequest(BrokerOrderFamily.REGULAR))
    assert isinstance(result, BrokerReadSuccess)
    row = result.value[0]
    assert row.orderid == "REGULAR-SYNTHETIC" and row.quantity == "10" and row.filled_quantity == "0"
    assert row.status == "open" and row.pricetype == "LIMIT" and row.raw_observation_json is None and row.legs == ()
    assert read_stack.calls == [("/v2/order/retrieve-all", "GET")]
