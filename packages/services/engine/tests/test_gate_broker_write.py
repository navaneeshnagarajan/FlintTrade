"""gate_broker_write — minting for the extended gated write verbs (contract §8.1).

Also pins the hash coverage of the new optional Order fields (validity + the
OCO leg trio): a gate minted over an Order must be invalidated by mutating ANY
of them afterwards — no unhashed mutable field may reach the broker.
"""

from __future__ import annotations

import pytest

from flinttrade_core.exceptions import SafetyBypassError
from flinttrade_core.models import Order
from flinttrade_engine.request_context import RequestContext
from flinttrade_engine.safety import (
    GATED_WRITE_VERBS,
    gate_broker_write,
    gate_order,
    set_safety_gate_secret,
)

pytestmark = pytest.mark.unit

set_safety_gate_secret(b"test-safety-gate-secret-0123456789")


def _ctx(**overrides) -> RequestContext:
    base = dict(
        jti="jti-1",
        actor_type="human",
        actor_id="navaneesh",
        mode="live",
        intent_source=None,
        external_nonce_hash=None,
    )
    base.update(overrides)
    return RequestContext(**base)


# ---------------------------------------------------------------------------
# Minting for the extended verbs
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("verb", sorted(GATED_WRITE_VERBS))
def test_gate_broker_write_mints_for_every_registered_verb(verb: str) -> None:
    ctx = _ctx()
    payload = {"_op": verb, "order_id": "X-1"}
    sc = gate_broker_write(verb, payload, ctx, "dhan", account_id="acct-1")
    assert sc.verify(payload, ctx, "dhan", "acct-1") is True


def test_gate_broker_write_refuses_unknown_verb() -> None:
    with pytest.raises(SafetyBypassError, match="unknown gated write verb"):
        gate_broker_write("transfer_funds", {"_op": "transfer_funds"}, _ctx(), "dhan")


def test_gate_broker_write_refuses_non_mapping_payload() -> None:
    with pytest.raises(SafetyBypassError, match="must be a Mapping"):
        gate_broker_write("cancel_forever", ["GTT-1"], _ctx(), "dhan")  # type: ignore[arg-type]


def test_gate_broker_write_refuses_op_mismatch() -> None:
    with pytest.raises(SafetyBypassError, match="_op .* does not match"):
        gate_broker_write(
            "cancel_forever", {"_op": "modify_forever", "order_id": "GTT-1"}, _ctx(), "dhan"
        )


def test_gate_broker_write_refuses_missing_op() -> None:
    with pytest.raises(SafetyBypassError, match="does not match"):
        gate_broker_write("cancel_forever", {"order_id": "GTT-1"}, _ctx(), "dhan")


def test_cross_verb_payload_does_not_verify() -> None:
    """The _op discriminator is inside the signed hash, so a gate minted for one
    verb can never verify against another verb's payload — even with identical
    remaining fields."""
    ctx = _ctx()
    cancel_payload = {"_op": "cancel_forever", "order_id": "GTT-1"}
    sc = gate_broker_write("cancel_forever", cancel_payload, ctx, "dhan")
    modify_payload = {"_op": "modify_forever", "order_id": "GTT-1"}
    assert sc.verify(modify_payload, ctx, "dhan") is False


def test_gate_is_bound_to_the_payload_fields() -> None:
    ctx = _ctx()
    payload = {"_op": "convert_position", "req": {"symbol": "RELIANCE", "quantity": 5}}
    sc = gate_broker_write("convert_position", payload, ctx, "dhan")
    tampered = {"_op": "convert_position", "req": {"symbol": "RELIANCE", "quantity": 500}}
    assert sc.verify(tampered, ctx, "dhan") is False


def test_gate_broker_write_actor_metadata_must_agree() -> None:
    ctx = _ctx(actor_type="human")
    with pytest.raises(SafetyBypassError, match="actor_type_mismatch"):
        gate_broker_write(
            "exit_all_positions", {"_op": "exit_all_positions"}, ctx, "dhan",
            actor_type="external_intent",
        )


# ---------------------------------------------------------------------------
# New Order fields are covered by the canonical hash (gate_order path)
# ---------------------------------------------------------------------------


def _order(**overrides) -> Order:
    fields = dict(
        symbol="RELIANCE", action="BUY", exchange="NSE", pricetype="LIMIT",
        product="CNC", quantity="5", price="2900", trigger_price="2890", variety="gtt",
    )
    fields.update(overrides)
    return Order(**fields)


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("validity", "IOC"),
        ("price1", "2800"),
        ("trigger_price1", "2805"),
        ("quantity1", "5"),
    ],
)
def test_mutating_new_order_field_after_minting_invalidates_gate(field: str, value: str) -> None:
    """Hash-coverage proof: every new optional Order field is inside the signed
    canonical hash, so post-mint mutation fails verification."""
    ctx = _ctx()
    order = _order()
    sc = gate_order(order, ctx, "dhan")
    assert sc.verify(order, ctx, "dhan") is True
    setattr(order, field, value)
    assert sc.verify(order, ctx, "dhan") is False


def test_orders_differing_only_in_new_fields_hash_differently() -> None:
    ctx = _ctx()
    plain = _order()
    oco = _order(price1="2800", trigger_price1="2805", quantity1="5")
    sc = gate_order(plain, ctx, "dhan")
    assert sc.verify(plain, ctx, "dhan") is True
    assert sc.verify(oco, ctx, "dhan") is False
    sc_validity = gate_order(_order(validity="GTC"), ctx, "dhan")
    assert sc_validity.verify(_order(validity="GTC"), ctx, "dhan") is True
    assert sc_validity.verify(_order(validity="DAY"), ctx, "dhan") is False
    assert sc_validity.verify(plain, ctx, "dhan") is False
