"""Super read observations cannot lose a conflicting consumed quantity alias.

Finite raw observations stay observations; sign/integrality/cross-bounds and
independent-child authority are established by the existing L2 classifier.
"""

from __future__ import annotations

import json
from typing import Any

import pytest

from flinttrade_core.broker_read_port import (
    BrokerOrderFamily,
    BrokerReadErrorCode,
    BrokerReadFailure,
    BrokerReadResponseInvalid,
    BrokerReadSuccess,
    OrderStateRequest,
)
from flinttrade_gateway.brokers.dhan_mapping import from_dhan_super_order
from packages.integrations.gateway.tests.test_dhan_read_evidence_runtime import (
    official_super_row,
    read_stack as read_stack,
)


def test_existing_super_mapper_refuses_conflicting_native_child_fill_aliases() -> None:
    with pytest.raises(BrokerReadResponseInvalid):
        from_dhan_super_order({"legDetails": [{"quantity": 10, "filledQty": 0, "tradedQty": 1}]})


ALIASES = ("quantity", "qty", "order_quantity", "filled_quantity", "filled_qty", "filledQty", "tradedQty",
           "remaining_quantity", "remainingQuantity")


def independent_row() -> dict[str, Any]:
    return {
        "quantity": 10, "qty": "10.0", "order_quantity": "1e1",
        "filled_quantity": 0, "filled_qty": "0.0", "filledQty": 0, "tradedQty": "0e0",
        "remaining_quantity": 10, "remainingQuantity": "10.0",
    }


@pytest.mark.parametrize("location", ["parent", "child"])
@pytest.mark.parametrize("alias", ALIASES)
@pytest.mark.parametrize("bad", [True, False, "invalid", "NaN", "Infinity", float("nan"), float("inf"), object()])
def test_existing_super_mapper_validates_every_primary_and_secondary_consumed_alias(
    location: str, alias: str, bad: Any,
) -> None:
    row = {**independent_row(), alias: bad}
    raw = row if location == "parent" else {"legDetails": [row]}

    with pytest.raises(BrokerReadResponseInvalid):
        from_dhan_super_order(raw)


@pytest.mark.parametrize("location", ["parent", "child"])
@pytest.mark.parametrize("changes", [
    {"qty": 11}, {"order_quantity": 9}, {"filled_qty": 1}, {"filledQty": 1}, {"tradedQty": 11},
    {"remainingQuantity": 9},
    {"quantity": "9007199254740993", "qty": "9007199254740992", "order_quantity": "9007199254740993"},
    {"quantity": 9007199254740993, "qty": 9007199254740992.0, "order_quantity": "9007199254740993"},
])
def test_existing_super_mapper_refuses_alias_conflicts_in_exact_not_float_domain(location: str, changes) -> None:
    row = {**independent_row(), **changes}

    with pytest.raises(BrokerReadResponseInvalid):
        from_dhan_super_order(row if location == "parent" else {"legDetails": [row]})


@pytest.mark.parametrize("absence", [None, "", "   "])
def test_super_mapper_keeps_raw_absence_without_manufacturing_zero_or_parent_evidence(absence) -> None:
    leg = {"legName": "TARGET_LEG", **dict.fromkeys(ALIASES, absence), "totalQuatity": 0, "triggeredQuantity": 0}

    mapped = from_dhan_super_order({"quantity": 99, "filledQty": 50, "legDetails": [leg]})

    assert mapped["legs"] == [leg]
    assert not {"quantity", "filled_quantity", "remaining_quantity"}.intersection(from_dhan_super_order(
        dict.fromkeys(ALIASES, absence),
    ))


def test_super_mapper_preserves_compatible_finite_observations_without_granting_integral_authority() -> None:
    # The established raw read union includes fractions/sign observations. It
    # is not an admission filter; the actual classifier independently refuses.
    raw = {
        "legName": "TARGET_LEG", "quantity": "1.5", "qty": 1.5, "order_quantity": "1.50",
        "filledQty": -1, "tradedQty": "-1.0", "remainingQuantity": None,
    }

    assert from_dhan_super_order({"legDetails": [raw]})["legs"] == [raw]


def test_super_mapper_preserves_large_exact_agreement_and_detaches_native_observations() -> None:
    raw = {
        "legName": "TARGET_LEG", "quantity": 9007199254740993, "qty": "9007199254740993.0",
        "filledQty": 0, "tradedQty": "0.0", "remainingQuantity": "9007199254740993",
    }
    mapped = from_dhan_super_order({"legDetails": [raw]})

    assert mapped["legs"] == [raw]
    raw["quantity"] = 1
    assert mapped["legs"][0]["quantity"] == 9007199254740993


@pytest.mark.parametrize("changes", [
    {"qty": 11}, {"order_quantity": "NaN"}, {"filled_qty": 1}, {"tradedQty": 11},
    {"remaining_quantity": 10, "remainingQuantity": 9}, {"remaining_quantity": True},
])
async def test_real_bound_super_port_remains_malformed_not_complete_on_conflicting_or_invalid_aliases(
    read_stack, changes,
) -> None:
    port, transport = read_stack
    raw = official_super_row()
    raw["legDetails"][0].update({"quantity": 10, "filledQty": 0, **changes})
    transport.rows["/super/orders"] = [raw]

    assert await port.order_states(OrderStateRequest(BrokerOrderFamily.SUPER)) == BrokerReadFailure(
        BrokerReadErrorCode.MALFORMED_RESPONSE,
    )
    assert transport.calls == ["/super/orders"]


async def test_real_bound_super_port_retains_agreeing_aliases_as_observations_not_readiness(read_stack) -> None:
    port, transport = read_stack
    raw = official_super_row()
    raw["legDetails"][0].update(independent_row())
    transport.rows["/super/orders"] = [raw]

    result = await port.order_states(OrderStateRequest(BrokerOrderFamily.SUPER))

    assert isinstance(result, BrokerReadSuccess)
    stop, target = result.value[0].legs
    assert (stop.quantity, stop.filled_quantity, stop.remaining_quantity) == ("10", "0", "10")
    assert json.loads(stop.raw_observation_json) == raw["legDetails"][0]
    assert stop.exchange_order_id is None
    assert target.quantity is None and target.filled_quantity is None and target.exchange_order_id is None
    assert transport.calls == ["/super/orders"]


def nested_extension(containers: int, empty_leaf: bool) -> Any:
    value: Any = [] if empty_leaf else None
    for _ in range(containers - int(empty_leaf)):
        value = [value]
    return value


@pytest.mark.parametrize("empty_leaf", [False, True])
def test_existing_dhan_super_caller_keeps_exact_64_container_json_detachment_and_nulls(empty_leaf: bool) -> None:
    # A leg is itself the root container passed to the shared validator.
    source = {"legName": "TARGET_LEG", "extension": nested_extension(63, empty_leaf)}

    leg = from_dhan_super_order({"legDetails": [source]})["legs"][0]

    assert leg == source and leg is not source
    assert leg["extension"] is not source["extension"]
    source["extension"].append("source-only")
    assert len(leg["extension"]) == 1


@pytest.mark.parametrize("empty_leaf", [False, True])
@pytest.mark.parametrize("containers", [64, 1000])
def test_existing_dhan_super_caller_translates_shared_depth_failure_to_read_error(containers, empty_leaf) -> None:
    source = {"legName": "TARGET_LEG", "extension": nested_extension(containers, empty_leaf)}

    with pytest.raises(BrokerReadResponseInvalid) as error:
        from_dhan_super_order({"legDetails": [source]})

    assert type(error.value) is BrokerReadResponseInvalid
    assert error.value.__cause__ is None and error.value.__suppress_context__


def test_existing_dhan_super_caller_detaches_shared_acyclic_extensions_without_aliases() -> None:
    shared = {"observed": [None, False, -0.0]}
    source = {"legName": "TARGET_LEG", "extension": {"left": shared, "right": shared}}

    copied = from_dhan_super_order({"legDetails": [source]})["legs"][0]["extension"]

    assert copied["left"] == copied["right"] == shared
    assert copied["left"] is not copied["right"] and copied["left"] is not shared
    assert copied["left"]["observed"][2].hex() == "-0x0.0p+0"
    copied["left"]["observed"].append("copy-only")
    assert copied["right"]["observed"] == [None, False, -0.0]
    assert shared["observed"] == [None, False, -0.0]


@pytest.mark.parametrize("empty_leaf", [False, True])
@pytest.mark.parametrize("containers", [63, 64])
async def test_real_bound_super_port_keeps_shared_json_depth_policy_and_unknown_child_authority(
    read_stack, containers, empty_leaf,
) -> None:
    port, transport = read_stack
    raw = official_super_row()
    raw["legDetails"][0]["extension"] = nested_extension(containers, empty_leaf)
    transport.rows["/super/orders"] = [raw]

    result = await port.order_states(OrderStateRequest(BrokerOrderFamily.SUPER))

    if containers == 64:
        assert result == BrokerReadFailure(BrokerReadErrorCode.MALFORMED_RESPONSE)
    else:
        assert isinstance(result, BrokerReadSuccess)
        stop = result.value[0].legs[0]
        assert json.loads(stop.raw_observation_json) == raw["legDetails"][0]
        assert stop.quantity is None and stop.filled_quantity is None and stop.exchange_order_id is None
    assert transport.calls == ["/super/orders"]
