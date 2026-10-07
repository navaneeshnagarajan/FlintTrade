"""Observed Dhan evidence at the actual bound read-port/installed SDK seam.

The native fixtures are observations, never exchange-child identities, fills,
complete-book authority or readiness. Only the HTTP transport is inert.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any
from uuid import uuid4

import pytest
from dhanhq import ForeverOrder, Order as SDKOrder, SuperOrder

from flinttrade_core.broker_identity import BrokerSelector, CredentialVersion
from flinttrade_core.broker_read_port import (
    BrokerOrderFamily,
    BrokerReadErrorCode,
    BrokerReadFailure,
    BrokerReadSuccess,
    ExactReadTarget,
    OrderStateRequest,
)
from flinttrade_core.secure_file import harden_directory
from flinttrade_core.workspace_migrations import broker_workspace_version, compare_and_swap_workspace
from flinttrade_engine.request_context import RequestContext
from flinttrade_gateway import registry as registry_api
from flinttrade_gateway.broker_read_service import create_broker_read_owner
from flinttrade_gateway.brokers._base import Session
from flinttrade_gateway.brokers.dhan import DhanAdapter
from flinttrade_gateway.session_provider import AuthenticatingSessionProvider

pytestmark = pytest.mark.integration


class RecordingHTTP:
    def __init__(self) -> None:
        self.calls: list[str] = []
        self.rows: dict[str, Any] = {
            "/orders": [], "/forever/orders": [], "/super/orders": [], "/alerts/orders": [],
        }

    def get(self, endpoint: str) -> dict[str, Any]:
        self.calls.append(endpoint)
        return {"status": "success", "data": self.rows[endpoint]}


class RecordingSDK(SDKOrder, ForeverOrder, SuperOrder):
    def __init__(self, transport: RecordingHTTP) -> None:
        self.dhan_http = transport


@pytest.fixture
def read_stack(tmp_path: Path):
    selector = BrokerSelector("dhan", "Synthetic")
    workspace_path = tmp_path / "workspace"
    workspace_path.mkdir()
    harden_directory(workspace_path)

    def initialise(config: dict[str, Any]) -> None:
        config["brokers"]["account_acls"] = {"dhan": {"Synthetic": ["actor"]}}

    workspace = compare_and_swap_workspace(workspace_path, None, initialise)
    credential = CredentialVersion(selector, uuid4(), 1)
    authority = registry_api.ManagedSessionAuthority(
        credential, workspace.version, broker_workspace_version(workspace),
    )
    registry, registry_owner = registry_api.create_owned_registry()
    session = Session("synthetic-token", 4102444800.0, "Synthetic", "dhan")
    transport = RecordingHTTP()
    sdk = RecordingSDK(transport)
    receipt = registry_owner.prepare_session_candidate(
        selector, session, expected_registry=registry.snapshot_selector(selector), authority=authority,
        broker="dhan", label="Synthetic", client=sdk,
    )
    registry_owner.publish_prepared_candidate(receipt, current_authority=authority)
    provider = AuthenticatingSessionProvider(
        registry, {"dhan": {"Synthetic": ["actor"]}}, workspace_snapshot=workspace, workspace_path=workspace_path,
        credential_version_for=lambda target: credential if target == selector else None,
    )
    adapter = DhanAdapter(client_factory=lambda _session: sdk)
    owner = create_broker_read_owner(
        registry=registry, session_provider=provider, adapters={"dhan": adapter}, workspace_path=workspace_path,
        runtime_accepting_requests=lambda: True,
    )
    context = RequestContext("jti", "human", "actor", "practice", selector="dhan:Synthetic")
    port = owner.bind(target=ExactReadTarget(selector), verify_current_authority=lambda: context)
    assert not isinstance(port, BrokerReadFailure)
    yield port, transport
    owner.close(timeout=1.0)


async def test_forever_bound_port_preserves_native_product_family_and_timestamps(read_stack) -> None:
    port, transport = read_stack
    transport.rows["/forever/orders"] = [{
        "orderId": "forever-fixture", "orderType": "OCO", "orderStatus": "CONFIRM", "productType": "BO",
        "exchangeSegment": "MCX_COMM", "tradingSymbol": "GOLD-FIXTURE", "securityId": "fixture-security",
        "transactionType": "BUY", "quantity": 10, "quantity1": 10, "price1": 110, "triggerPrice1": 109,
        "createTime": "2026-06-01 10:00:00", "updateTime": "2026-06-01 10:01:00",
        "exchangeTime": "2026-06-01 10:00:01",
    }]

    outcome = await port.order_states(OrderStateRequest(BrokerOrderFamily.FOREVER))

    assert isinstance(outcome, BrokerReadSuccess)
    row = outcome.value[0]
    assert (row.broker_product, row.product, row.broker_order_type, row.order_flag) == ("BO", "MIS", "OCO", "OCO")
    assert (row.created_at, row.updated_at, row.exchange_time) == (
        "2026-06-01 10:00:00", "2026-06-01 10:01:00", "2026-06-01 10:00:01",
    )
    assert row.pricetype is None and row.filled_quantity is None and row.validity is None
    assert (row.legs[0].quantity, row.legs[0].price, row.legs[0].trigger_price) == ("10", "110", "109")
    assert row.legs[0].order_id is None and row.legs[0].filled_quantity is None
    assert transport.calls == ["/forever/orders"]


def official_super_row() -> dict[str, Any]:
    """Official v2 Super Order List, with identifiers replaced by fixture labels.

    https://dhanhq.co/docs/v2/super-order/ — retrieved body SHA-256
    4a04b343a8014826693433cbc24fa9dfce2cf7ee7570616196977d378e80923e.
    Preserve the actual zero/missing quantities and shared resource order ID.
    """
    return {
        "orderId": "super-fixture", "correlationId": "fixture-correlation", "orderStatus": "PENDING",
        "transactionType": "BUY", "exchangeSegment": "NSE_EQ", "productType": "CNC", "orderType": "LIMIT",
        "validity": "DAY", "tradingSymbol": "HDFCBANK", "securityId": "1333", "quantity": 10,
        "remainingQuantity": 10, "ltp": 1660.95, "price": 1500, "afterMarketOrder": False,
        "legName": "ENTRY_LEG", "exchangeOrderId": "fixture-exchange",
        "createTime": "2025-02-27 19:09:42", "updateTime": "2025-02-27 19:09:42",
        "exchangeTime": "2025-02-27 19:09:42", "omsErrorDescription": "", "averageTradedPrice": 0, "filledQty": 0,
        "legDetails": [
            {"orderId": "super-fixture", "legName": "STOP_LOSS_LEG", "transactionType": "SELL",
             "totalQuatity": 0, "remainingQuantity": 0, "triggeredQuantity": 0, "price": 1400,
             "orderStatus": "PENDING", "trailingJump": 10},
            {"orderId": "super-fixture", "legName": "TARGET_LEG", "transactionType": "SELL",
             "remainingQuantity": 0, "triggeredQuantity": 0, "price": 1550,
             "orderStatus": "PENDING", "trailingJump": 0},
        ],
    }


async def test_official_super_observation_survives_the_bound_port_without_invented_fills_or_children(read_stack) -> None:
    port, transport = read_stack
    raw = official_super_row()
    transport.rows["/super/orders"] = [raw]

    outcome = await port.order_states(OrderStateRequest(BrokerOrderFamily.SUPER))

    assert isinstance(outcome, BrokerReadSuccess)
    row = outcome.value[0]
    assert row.remaining_quantity == "10"
    assert (row.broker_product, row.broker_order_type, row.validity) == ("CNC", "LIMIT", "DAY")
    assert (row.created_at, row.updated_at, row.exchange_time) == ("2025-02-27 19:09:42",) * 3
    assert row.quantity == "10" and row.filled_quantity == "0" and row.average_price == "0"
    assert row.leg_details_valid is True
    stop, target = row.legs
    assert (stop.total_quantity, stop.remaining_quantity, stop.triggered_quantity, stop.trailing_jump) == (
        "0", "0", "0", "10",
    )
    assert target.total_quantity is None and target.remaining_quantity == "0" and target.trailing_jump == "0"
    for typed, native in zip(row.legs, raw["legDetails"], strict=True):
        assert typed.order_id == row.orderid == "super-fixture"
        assert typed.exchange_order_id is None and typed.filled_quantity is None and typed.quantity is None
        assert json.loads(typed.raw_observation_json) == native
    raw["legDetails"][0]["price"] = 999
    assert stop.price == "1400" and json.loads(stop.raw_observation_json)["price"] == 1400
    assert transport.calls == ["/super/orders"]


async def test_traded_super_entry_keeps_pending_and_cancel_pending_native_legs(read_stack) -> None:
    port, transport = read_stack
    raw = official_super_row()
    raw.update({"orderStatus": "TRADED", "filledQty": 10, "remainingQuantity": 0})
    raw["legDetails"][0]["orderStatus"] = "CANCEL_PENDING"
    transport.rows["/super/orders"] = [raw]

    outcome = await port.order_states(OrderStateRequest(BrokerOrderFamily.SUPER))

    assert isinstance(outcome, BrokerReadSuccess)
    row = outcome.value[0]
    assert row.status == "TRADED" and row.filled_quantity == "10" and row.remaining_quantity == "0"
    assert [leg.status for leg in row.legs] == ["CANCEL_PENDING", "PENDING"]
    assert all(leg.filled_quantity is None and leg.exchange_order_id is None for leg in row.legs)


@pytest.mark.parametrize("family", ["regular", "forever", "super"])
async def test_existing_safety_horizon_keeps_observed_resource_evidence_when_it_can_be_admitted(
    read_stack, family: str,
) -> None:
    port, transport = read_stack
    raw = official_super_row()
    raw.update({"productType": "BO", "orderType": "LIMIT", "validity": "IOC"})
    if family == "regular":
        raw.pop("legDetails")
        transport.rows["/orders"] = [raw]
    elif family == "forever":
        raw.pop("legDetails")
        raw["orderFlag"] = "SINGLE"
        transport.rows["/forever/orders"] = [raw]
    else:
        # A historical compatible shape, not a reconstruction of the official
        # fixture: independently supplied child quantities/fills/IDs are present.
        for leg, child in zip(raw["legDetails"], ("stop-fixture", "target-fixture"), strict=True):
            leg.update({"orderId": child, "quantity": 10, "filledQty": 0, "orderType": "LIMIT"})
        transport.rows["/super/orders"] = [raw]

    outcome = await port.order_states(OrderStateRequest(BrokerOrderFamily.REGULAR))

    assert isinstance(outcome, BrokerReadSuccess)
    row = next(item for item in outcome.value if item.orderid == "super-fixture")
    assert (row.broker_product, row.broker_order_type, row.validity) == ("BO", "LIMIT", "IOC")
    assert (row.created_at, row.updated_at, row.exchange_time) == ("2025-02-27 19:09:42",) * 3
    assert row.remaining_quantity == "10" and row.average_price == "0"
    assert row.order_family.value == family
    if family == "super":
        assert json.loads(row.legs[0].raw_observation_json) == raw["legDetails"][0]
    assert transport.calls == ["/orders", "/forever/orders", "/super/orders", "/alerts/orders"]


@pytest.mark.parametrize("value", [None, "", "   "])
@pytest.mark.parametrize("native, attribute", [
    ("price", "price"), ("triggerPrice", "trigger_price"), ("totalQuatity", "total_quantity"),
    ("remainingQuantity", "remaining_quantity"), ("triggeredQuantity", "triggered_quantity"),
    ("trailingJump", "trailing_jump"), ("filledQty", "filled_quantity"),
])
async def test_super_leg_null_blank_observations_remain_raw_but_never_become_values(
    read_stack, native: str, attribute: str, value: Any,
) -> None:
    port, transport = read_stack
    raw = official_super_row()
    raw["legDetails"][0][native] = value
    transport.rows["/super/orders"] = [raw]

    outcome = await port.order_states(OrderStateRequest(BrokerOrderFamily.SUPER))

    assert isinstance(outcome, BrokerReadSuccess)
    leg = outcome.value[0].legs[0]
    assert getattr(leg, attribute) is None
    assert json.loads(leg.raw_observation_json)[native] == value


@pytest.mark.parametrize("native, attribute", [
    ("quantity", "quantity"), ("filledQty", "filled_quantity"), ("tradedQty", "filled_quantity"),
    ("totalQuatity", "total_quantity"), ("remainingQuantity", "remaining_quantity"),
    ("triggeredQuantity", "triggered_quantity"), ("price", "price"), ("triggerPrice", "trigger_price"),
    ("trailingJump", "trailing_jump"), ("targetPrice", "target_price"), ("stopLossPrice", "stop_loss_price"),
    ("averageTradedPrice", "average_price"), ("disclosedQuantity", "disclosed_quantity"),
])
@pytest.mark.parametrize("value", [0, "9007199254740993", "3.50"])
async def test_every_supplied_super_leg_number_and_json_extension_survives_exactly(
    read_stack, native: str, attribute: str, value: Any,
) -> None:
    port, transport = read_stack
    raw = official_super_row()
    raw["legDetails"][0].update({native: value, "extension": {"observations": [None, False, "", {"n": 3.5}]}})
    transport.rows["/super/orders"] = [raw]

    outcome = await port.order_states(OrderStateRequest(BrokerOrderFamily.SUPER))

    assert isinstance(outcome, BrokerReadSuccess)
    leg = outcome.value[0].legs[0]
    assert getattr(leg, attribute) == str(value)
    assert json.loads(leg.raw_observation_json) == raw["legDetails"][0]
    if native == "triggeredQuantity":
        assert leg.filled_quantity is None


@pytest.mark.parametrize("native", [
    "totalQuatity", "remainingQuantity", "triggeredQuantity", "quantity", "filledQty", "tradedQty",
    "price", "triggerPrice", "trailingJump", "targetPrice", "stopLossPrice", "averageTradedPrice", "disclosedQuantity",
])
@pytest.mark.parametrize("value", [True, "NaN", "invalid", float("inf"), object()])
async def test_malformed_super_leg_evidence_is_malformed_response_never_successful_empty(
    read_stack, native: str, value: Any,
) -> None:
    port, transport = read_stack
    raw = official_super_row()
    raw["legDetails"][0][native] = value
    transport.rows["/super/orders"] = [raw]

    assert await port.order_states(OrderStateRequest(BrokerOrderFamily.SUPER)) == BrokerReadFailure(
        BrokerReadErrorCode.MALFORMED_RESPONSE,
    )
    assert transport.calls == ["/super/orders"]


@pytest.mark.parametrize("changes", [
    {"triggerPrice": 5, "trigger_price": 6}, {"filledQty": 1, "tradedQty": 2},
    {"remaining_quantity": 5, "remainingQuantity": 6}, {"total_quantity": 5, "totalQuatity": 6},
    {"parentOrderId": "one", "parent_order_id": "another"}, {"extension": {"bad": object()}},
])
async def test_shared_typed_projection_refuses_conflicts_and_opaque_leg_extensions(read_stack, changes) -> None:
    port, transport = read_stack
    raw = official_super_row()
    raw["legDetails"][0].update(changes)
    transport.rows["/super/orders"] = [raw]

    assert await port.order_states(OrderStateRequest(BrokerOrderFamily.SUPER)) == BrokerReadFailure(
        BrokerReadErrorCode.MALFORMED_RESPONSE,
    )


@pytest.mark.parametrize("changes", [{"orderFlag": "SINGLE", "orderType": "OCO"}, {"remainingQuantity": "NaN"}])
async def test_conflicting_forever_family_or_parent_remaining_is_not_a_successful_book(read_stack, changes) -> None:
    port, transport = read_stack
    transport.rows["/forever/orders"] = [{
        "orderId": "forever-fixture", "orderStatus": "PENDING", "orderFlag": "SINGLE", "orderType": "LIMIT",
        "productType": "CNC", "exchangeSegment": "NSE_EQ", "tradingSymbol": "HDFCBANK", "securityId": "1333",
        "transactionType": "BUY", "quantity": 10, **changes,
    }]

    assert await port.order_states(OrderStateRequest(BrokerOrderFamily.FOREVER)) == BrokerReadFailure(
        BrokerReadErrorCode.MALFORMED_RESPONSE,
    )


@pytest.mark.parametrize("shape", ["official", "quantities-without-fills", "same-id-with-independent-quantities-and-fills"])
async def test_native_super_safety_horizon_remains_guarded_until_identity_and_quantity_correspondence_exists(
    read_stack, shape: str,
) -> None:
    port, transport = read_stack
    raw = official_super_row()
    if shape != "official":
        for leg in raw["legDetails"]:
            leg["quantity"] = 10
            if shape == "same-id-with-independent-quantities-and-fills":
                leg["filledQty"] = 0
    transport.rows["/super/orders"] = [raw]

    assert await port.order_states(OrderStateRequest(BrokerOrderFamily.REGULAR)) == BrokerReadFailure(
        BrokerReadErrorCode.MALFORMED_RESPONSE,
    )
    assert transport.calls == ["/orders", "/forever/orders", "/super/orders", "/alerts/orders"]
