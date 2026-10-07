"""Independent Super-child evidence at the actual HTTP and classifier seams.

Synthetic compatible child rows are not reconstructions of the incomplete
first-party Super fixture. Only the exact inert transport is substituted;
the existing normal factory, real one-shot gate, router and pinned SDK run.
"""

from __future__ import annotations

import json
from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock

import pytest

from flinttrade_core.l2_state import PortfolioSafetyStateError, classify_modify_intent
from packages.core.core.tests.test_dhan_super_route_correspondence import (
    modify,
    route_stack as route_stack,
)

pytestmark = pytest.mark.integration


@pytest.mark.parametrize("traded", [11, 1])
def test_contradictory_native_child_fills_refuse_before_consume_or_sdk_put(route_stack, traded: int) -> None:
    app, transport, consumed = route_stack
    transport.super_row["legDetails"][0]["tradedQty"] = traded

    response = modify(app, {"leg_name": "TARGET_LEG", "target_price": "1555"})

    observed: dict[str, Any] = {
        "child": transport.super_row["legDetails"][0], "status": response.status_code,
        "body": response.get_json(), "consumed": len(consumed), "sdk_calls": transport.calls,
    }
    print("SUPER_ALIAS_ROUTE " + json.dumps(observed), flush=True)
    # The mapper now rejects the malformed read before L2 sees a normalised row.
    assert response.status_code == 503, observed
    assert consumed == [], observed
    assert transport.calls == [("GET", "/super/orders", None)], observed


@pytest.fixture
def classifier_stack():
    child = {
        "legName": "TARGET_LEG", "orderStatus": "PENDING", "orderId": "super-fixture",
        "quantity": 10, "filled_quantity": 0, "price": 1550, "orderType": "LIMIT", "transactionType": "SELL",
    }
    parent = {
        "orderid": "super-fixture", "status": "PENDING", "symbol": "HDFCBANK", "exchange": "NSE",
        "action": "BUY", "product": "CNC", "pricetype": "LIMIT", "quantity": 10, "filled_quantity": 0,
        "price": 1500, "trigger_price": 0, "leg_details_valid": True,
        "legs": [child, {**child, "legName": "STOP_LOSS_LEG", "price": 1400}],
    }
    session = object()
    source = SimpleNamespace(
        super_orders=AsyncMock(return_value=[parent]),
        margin_calculator=AsyncMock(return_value={"required_margin": 100}),
    )
    config = {
        "NATIVE_ADAPTERS": {"dhan": source},
        "REGISTRY": SimpleNamespace(get_session_for=lambda broker, account: session),
    }
    return config, source, parent, child


async def test_existing_classifier_refuses_entry_fill_alias_conflict_before_margin(classifier_stack) -> None:
    config, source, parent, _child = classifier_stack
    parent["filledQty"] = 11

    with pytest.raises(PortfolioSafetyStateError, match="aliases disagree"):
        await classify_modify_intent(
            config, "dhan", "super-fixture", {"leg_name": "ENTRY_LEG"}, family="super", account_id="route-account",
        )

    source.margin_calculator.assert_not_awaited()


QUANTITY_ALIASES = ("quantity", "qty", "order_quantity")
FILL_ALIASES = ("filled_quantity", "filled_qty", "filledQty", "tradedQty")
REMAINING_ALIASES = ("remaining_quantity", "remainingQuantity")
CONSUMED_ALIASES = (*QUANTITY_ALIASES, *FILL_ALIASES, *REMAINING_ALIASES)


def agreeing_evidence(quantity: Any = 10, filled: Any = 0, remaining: Any = 10) -> dict[str, Any]:
    return {
        **dict.fromkeys(QUANTITY_ALIASES, quantity), **dict.fromkeys(FILL_ALIASES, filled),
        **dict.fromkeys(REMAINING_ALIASES, remaining),
    }


@pytest.mark.parametrize("location", ["entry", "child"])
@pytest.mark.parametrize("alias", CONSUMED_ALIASES)
@pytest.mark.parametrize("bad", [True, False, 1.5, "0.0000000000000000000000000001", "NaN", "Infinity",
                                 "invalid", float("nan"), float("inf"), object()])
async def test_each_supplied_classifier_alias_has_an_exact_whole_number_domain(
    classifier_stack, location: str, alias: str, bad: Any,
) -> None:
    config, source, parent, child = classifier_stack
    row = parent if location == "entry" else child
    row.update(agreeing_evidence())
    row[alias] = bad

    with pytest.raises(PortfolioSafetyStateError, match="super-order"):
        await classify_modify_intent(
            config, "dhan", "super-fixture", {"leg_name": "ENTRY_LEG" if location == "entry" else "TARGET_LEG"},
            family="super", account_id="route-account",
        )

    source.margin_calculator.assert_not_awaited()


@pytest.mark.parametrize("changes", [
    {"qty": 11}, {"order_quantity": 9}, {"filled_qty": 1}, {"filledQty": 1}, {"tradedQty": 11},
    {"remainingQuantity": 9},
    {"quantity": "9007199254740993", "qty": "9007199254740992", "order_quantity": "9007199254740993"},
])
async def test_classifier_checks_all_aliases_before_canonical_first_field_selection(classifier_stack, changes) -> None:
    config, source, _parent, child = classifier_stack
    child.update(agreeing_evidence())
    child.update(changes)

    with pytest.raises(PortfolioSafetyStateError, match="aliases disagree"):
        await classify_modify_intent(config, "dhan", "super-fixture", {"leg_name": "TARGET_LEG"}, family="super")

    source.margin_calculator.assert_not_awaited()


@pytest.mark.parametrize("quantity,filled,remaining", [
    (10, 11, 0), (10, 0, 11), (10, 5, 6),
    ("9007199254740992", "9007199254740993", 0),
    ("9007199254740993", "9007199254740992", 2),
])
async def test_classifier_cross_bounds_are_exact_before_margin_or_classification(
    classifier_stack, quantity: Any, filled: Any, remaining: Any,
) -> None:
    config, source, _parent, child = classifier_stack
    child.update(agreeing_evidence(quantity, filled, remaining))

    with pytest.raises(PortfolioSafetyStateError, match="quantity is inconsistent"):
        await classify_modify_intent(config, "dhan", "super-fixture", {"leg_name": "TARGET_LEG"}, family="super")

    source.margin_calculator.assert_not_awaited()


@pytest.mark.parametrize("missing", ["quantity", "filled_quantity"])
@pytest.mark.parametrize("absence", [None, "", "   "])
async def test_native_classifier_preserves_absence_and_cannot_borrow_parent_evidence(
    classifier_stack, missing: str, absence: Any,
) -> None:
    config, source, _parent, child = classifier_stack
    for key in QUANTITY_ALIASES if missing == "quantity" else FILL_ALIASES:
        child[key] = absence
    child.update({"totalQuatity": 10, "triggeredQuantity": 10, "remainingQuantity": 0})

    with pytest.raises(PortfolioSafetyStateError, match="leg.*quantity is unavailable"):
        await classify_modify_intent(config, "dhan", "super-fixture", {"leg_name": "TARGET_LEG"}, family="super")

    source.margin_calculator.assert_not_awaited()


async def test_classifier_uses_independent_agreeing_aliases_after_blank_aliases_not_parent(classifier_stack) -> None:
    config, source, parent, child = classifier_stack
    parent.update({"quantity": 99, "filled_quantity": 50})
    child.update({"quantity": None, "qty": "10.0", "order_quantity": 10, "filled_quantity": "",
                  "filledQty": "0e0", "tradedQty": 0, "remainingQuantity": 10})

    result = await classify_modify_intent(
        config, "dhan", "super-fixture", {"leg_name": "TARGET_LEG"}, family="super", account_id="route-account",
    )

    assert result.proposed_order.quantity == "10"
    assert result.risk_increasing is False and result.margin_delta == 0
    assert source.margin_calculator.await_count == 2
    assert all(call.args[1].quantity == "10" for call in source.margin_calculator.await_args_list)


class HostileQuantity:
    def __init__(self) -> None:
        self.hooks: list[str] = []

    def __str__(self) -> str:
        self.hooks.append("str")
        raise AssertionError("Opaque evidence cannot become numeric text")

    def __float__(self) -> float:
        self.hooks.append("float")
        raise AssertionError("Opaque evidence cannot become a number")


@pytest.mark.parametrize("alias", CONSUMED_ALIASES)
async def test_classifier_refuses_opaque_secondary_evidence_without_conversion_hooks(classifier_stack, alias) -> None:
    config, source, _parent, child = classifier_stack
    hostile = HostileQuantity()
    child.update(agreeing_evidence())
    child[alias] = hostile

    with pytest.raises(PortfolioSafetyStateError, match="evidence is invalid"):
        await classify_modify_intent(config, "dhan", "super-fixture", {"leg_name": "TARGET_LEG"}, family="super")

    assert hostile.hooks == []
    source.margin_calculator.assert_not_awaited()


@pytest.mark.parametrize("changes", [
    {"quantity": 10, "qty": 11}, {"filledQty": 0, "filled_qty": 1},
    {"remaining_quantity": 10, "remainingQuantity": 9},
    {"qty": True}, {"filled_qty": "NaN"}, {"remaining_quantity": "invalid"},
])
def test_actual_factory_refuses_bad_secondary_quantity_evidence_before_mint(route_stack, changes) -> None:
    app, transport, consumed = route_stack
    transport.super_row["legDetails"][0].update(changes)

    response = modify(app, {"leg_name": "TARGET_LEG", "target_price": "1555"})

    assert response.status_code == 503, response.get_json()
    assert consumed == [] and transport.calls == [("GET", "/super/orders", None)]


@pytest.mark.parametrize("quantity,filled,remaining", [(10, 11, 0), (10, 0, 11), (10, 5, 6), (1.5, 0, 0)])
def test_actual_factory_refuses_agreeing_but_inconsistent_or_fractional_evidence(
    route_stack, quantity, filled, remaining,
) -> None:
    app, transport, consumed = route_stack
    transport.super_row["legDetails"][0].update(agreeing_evidence(quantity, filled, remaining))

    response = modify(app, {"leg_name": "TARGET_LEG", "target_price": "1555"})

    assert response.status_code == 409, response.get_json()
    assert consumed == [] and transport.calls == [("GET", "/super/orders", None)]


@pytest.mark.parametrize("identity", [{"action": "BUY"}, {"product": "MIS"}, {"exchange": "BSE"},
                                     {"symbol": "ANOTHER-FIXTURE"}])
def test_valid_target_fields_cannot_spoof_independent_child_identity(route_stack, identity) -> None:
    app, transport, consumed = route_stack

    response = modify(app, {"leg_name": "TARGET_LEG", "target_price": "1555", **identity})

    assert response.status_code == 409, response.get_json()
    assert next(iter(identity)) in response.get_json()["message"]
    assert consumed == [] and transport.calls == [("GET", "/super/orders", None)]


@pytest.mark.parametrize("leg,filled,changes,body", [
    ("TARGET_LEG", 0, {"target_price": "1555"}, {"targetPrice": 1555.0}),
    ("TARGET_LEG", 3, {"target_price": "1555"}, {"targetPrice": 1555.0}),
    ("STOP_LOSS_LEG", 0, {"stop_loss_price": "1401", "trailing_jump": "0"},
     {"stopLossPrice": 1401.0, "trailingJump": 0.0}),
    ("STOP_LOSS_LEG", 0, {"stop_loss_price": "1401", "trailing_jump": "5"},
     {"stopLossPrice": 1401.0, "trailingJump": 5.0}),
    ("ENTRY_LEG", 0, {"quantity": 10, "pricetype": "LIMIT", "price": "1500", "target_price": "1555",
                       "stop_loss_price": "1401", "trailing_jump": "0"},
     {"quantity": 10, "orderType": "LIMIT", "price": 1500.0, "targetPrice": 1555.0,
      "stopLossPrice": 1401.0, "trailingJump": 0.0}),
])
def test_agreeing_independent_evidence_preserves_real_sdk_target_stop_and_entry_control_union(
    route_stack, leg: str, filled: int, changes: dict[str, Any], body: dict[str, Any],
) -> None:
    app, transport, consumed = route_stack
    row = transport.super_row if leg == "ENTRY_LEG" else next(
        child for child in transport.super_row["legDetails"] if child["legName"] == leg
    )
    row.update(agreeing_evidence(10, filled, 10 - filled))
    row.update({"qty": "10.0", "order_quantity": "1e1", "tradedQty": f"{filled}.0"})

    response = modify(app, {"leg_name": leg, **changes})

    assert response.status_code == 200, response.get_json()
    assert len(consumed) == 1
    assert [call for call in transport.calls if call[0] == "PUT"] == [
        ("PUT", "/super/orders/super-fixture", {"orderId": "super-fixture", "legName": leg, **body}),
    ]
    assert len([call for call in transport.calls if call[:2] == ("POST", "/margincalculator")]) == 2
    assert response.get_json() == {"status": "success", "orderid": "super-fixture", "data": None}
