"""gate_order — the sole SafetyContext producer (contract §8.0/§8.1; audit S8)."""

from __future__ import annotations

import hashlib

import pytest

from flinttrade_core.exceptions import SafetyBypassError
from flinttrade_engine.request_context import RequestContext
from flinttrade_engine.safety import gate_order, set_safety_gate_secret

set_safety_gate_secret(b"test-safety-gate-secret-0123456789")

_ORDER = {"symbol": "NIFTY", "qty": 50, "side": "BUY", "price": 100.0}


def _ctx(**overrides):
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


def test_gate_order_mints_a_context_that_verifies():
    ctx = _ctx()
    sc = gate_order(_ORDER, ctx, "dhan")
    assert sc.verify(_ORDER, ctx, "dhan") is True


def test_gate_order_context_is_bound_to_the_order():
    ctx = _ctx()
    sc = gate_order(_ORDER, ctx, "dhan")
    other_order = {**_ORDER, "qty": 999}
    assert sc.verify(other_order, ctx, "dhan") is False


def test_gate_order_context_is_bound_to_the_adapter():
    ctx = _ctx()
    sc = gate_order(_ORDER, ctx, "dhan")
    assert sc.verify(_ORDER, ctx, "upstox") is False


def test_external_intent_carries_actor_metadata():
    nonce = "webhook-nonce-abc"
    nonce_hash = hashlib.sha256(nonce.encode()).hexdigest()
    ctx = _ctx(
        actor_type="external_intent",
        intent_source="webhook",
        external_nonce_hash=nonce_hash,
    )
    sc = gate_order(
        _ORDER, ctx, "dhan",
        actor_type="external_intent", intent_source="webhook", external_nonce=nonce,
    )
    assert sc.actor_type == "external_intent"
    assert sc.intent_source == "webhook"
    assert sc.external_nonce_hash == nonce_hash
    assert sc.verify(_ORDER, ctx, "dhan") is True


def test_actor_type_mismatch_is_refused():
    ctx = _ctx(actor_type="human")
    with pytest.raises(SafetyBypassError, match="actor_type_mismatch"):
        gate_order(_ORDER, ctx, "dhan", actor_type="external_intent")


def test_intent_source_mismatch_is_refused():
    ctx = _ctx(actor_type="external_intent", intent_source="webhook")
    with pytest.raises(SafetyBypassError, match="intent_source_mismatch"):
        gate_order(_ORDER, ctx, "dhan", intent_source="telegram")


def test_external_nonce_mismatch_is_refused():
    real_hash = hashlib.sha256(b"the-real-nonce").hexdigest()
    ctx = _ctx(actor_type="external_intent", external_nonce_hash=real_hash)
    with pytest.raises(SafetyBypassError, match="external_nonce_mismatch"):
        gate_order(_ORDER, ctx, "dhan", external_nonce="a-different-nonce")
