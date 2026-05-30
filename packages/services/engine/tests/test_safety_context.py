"""Replay-vector tests for SafetyContext (broker-adapter-contract §8.0).

The SafetyContext is the load-bearing trading-safety primitive: a one-shot
HMAC-signed ticket that binds an order to the live caller's mode/jti/actor
identity, the resolved adapter, and the operator's failover allowlist. Each
test below exercises one replay/forgery vector the canonical signed tuple is
meant to close (contract §8.2 matrix) plus the §8.0 structural guards.
"""

from __future__ import annotations

import types
from datetime import datetime, timedelta, timezone

import pytest

from flinttrade_core.exceptions import SafetyBypassError
from flinttrade_engine.request_context import RequestContext
from flinttrade_engine.safety import (
    SafetyContext,
    _get_safety_gate_secret,
    set_safety_gate_secret,
)

SECRET = b"0123456789abcdef0123456789abcdef"  # 32 bytes
OTHER_SECRET = b"fedcba9876543210fedcba9876543210"


@pytest.fixture(autouse=True)
def _bind_secret() -> None:
    """Bind a deterministic test secret before each test."""
    set_safety_gate_secret(SECRET)


def _order(symbol: str = "RELIANCE", qty: int = 10, side: str = "BUY") -> object:
    return types.SimpleNamespace(symbol=symbol, quantity=qty, side=side, exchange="NSE")


def _ctx(**over) -> RequestContext:
    base = dict(
        jti="jti-123",
        actor_type="human",
        actor_id="user-1",
        mode="live",
        intent_source=None,
        external_nonce_hash=None,
    )
    base.update(over)
    return RequestContext(**base)


def _mint(order=None, **over) -> SafetyContext:
    kwargs = dict(
        mode="live",
        user_jti="jti-123",
        adapter_id="dhan",
        actor_type="human",
    )
    kwargs.update(over)
    return SafetyContext.mint(order or _order(), **kwargs)


# ---------------------------------------------------------------------------
# Happy path
# ---------------------------------------------------------------------------


def test_minted_context_verifies_for_matching_request() -> None:
    order = _order()
    ctx = _mint(order)
    assert ctx.verify(order, _ctx(), "dhan") is True


# ---------------------------------------------------------------------------
# Replay vectors — each must make verify() return False
# ---------------------------------------------------------------------------


def test_order_substitution_rejected() -> None:
    """Context minted for order A must not verify against order B."""
    ctx = _mint(_order(symbol="RELIANCE"))
    assert ctx.verify(_order(symbol="TCS"), _ctx(), "dhan") is False


def test_adapter_mismatch_rejected() -> None:
    """S1: context bound to adapter 'dhan' must not verify when routed to 'upstox'."""
    order = _order()
    ctx = _mint(order, adapter_id="dhan")
    assert ctx.verify(order, _ctx(), "upstox") is False


def test_mode_mismatch_rejected() -> None:
    order = _order()
    ctx = _mint(order, mode="live")
    assert ctx.verify(order, _ctx(mode="practice"), "dhan") is False


def test_jti_mismatch_rejected() -> None:
    order = _order()
    ctx = _mint(order, user_jti="jti-123")
    assert ctx.verify(order, _ctx(jti="jti-999"), "dhan") is False


def test_actor_type_mismatch_rejected() -> None:
    """A webhook-minted (external_intent) context must not verify from a human session."""
    order = _order()
    ctx = _mint(
        order,
        actor_type="external_intent",
        intent_source="webhook",
        external_nonce_hash="nonce-abc",
    )
    human = _ctx(actor_type="human", intent_source=None, external_nonce_hash=None)
    assert ctx.verify(order, human, "dhan") is False


def test_intent_source_mismatch_rejected() -> None:
    order = _order()
    ctx = _mint(
        order,
        actor_type="external_intent",
        intent_source="webhook",
        external_nonce_hash="nonce-abc",
    )
    other = _ctx(actor_type="external_intent", intent_source="telegram", external_nonce_hash="nonce-abc")
    assert ctx.verify(order, other, "dhan") is False


def test_external_nonce_mismatch_rejected() -> None:
    """external_nonce_hash binds the ctx to one webhook payload (no payload swap)."""
    order = _order()
    ctx = _mint(
        order,
        actor_type="external_intent",
        intent_source="webhook",
        external_nonce_hash="nonce-abc",
    )
    swapped = _ctx(actor_type="external_intent", intent_source="webhook", external_nonce_hash="nonce-xyz")
    assert ctx.verify(order, swapped, "dhan") is False


def test_expired_context_rejected() -> None:
    order = _order()
    ctx = _mint(order, ttl_seconds=-5)  # already expired at mint
    assert ctx.verify(order, _ctx(), "dhan") is False


def test_signature_tamper_rejected() -> None:
    order = _order()
    ctx = _mint(order)
    forged = SafetyContext(
        gate_id=ctx.gate_id,
        order_hash=ctx.order_hash,
        mode=ctx.mode,
        user_jti=ctx.user_jti,
        adapter_id=ctx.adapter_id,
        account_id=ctx.account_id,
        actor_type=ctx.actor_type,
        intent_source=ctx.intent_source,
        external_nonce_hash=ctx.external_nonce_hash,
        failover_allowed_adapters=ctx.failover_allowed_adapters,
        expires_at=ctx.expires_at,
        signature=b"\x00" * len(ctx.signature),
    )
    assert forged.verify(order, _ctx(), "dhan") is False


def test_wrong_secret_rejected() -> None:
    """A context signed under secret A must not verify after a key rotation to B."""
    order = _order()
    ctx = _mint(order)
    set_safety_gate_secret(OTHER_SECRET)
    assert ctx.verify(order, _ctx(), "dhan") is False


# ---------------------------------------------------------------------------
# Structural guards (§8.0)
# ---------------------------------------------------------------------------


def test_subclassing_is_forbidden() -> None:
    """M15 final-class guard: no module may subclass + override verify()."""
    with pytest.raises(TypeError, match="final"):

        class _Evil(SafetyContext):  # noqa: D401 — intentional violation
            pass


def test_secret_required_before_mint() -> None:
    """Minting/verifying without an initialised secret fails closed."""
    import flinttrade_engine.safety as safety_mod

    saved = safety_mod._SAFETY_GATE_SECRET
    try:
        safety_mod._SAFETY_GATE_SECRET = None
        with pytest.raises(SafetyBypassError, match="not initialised"):
            _get_safety_gate_secret()
    finally:
        safety_mod._SAFETY_GATE_SECRET = saved


def test_set_secret_rejects_short_key() -> None:
    with pytest.raises(ValueError, match=">= 32"):
        set_safety_gate_secret(b"tooshort")


def test_failover_allowed_adapters_is_immutable_tuple() -> None:
    ctx = _mint(_order(), failover_allowed_adapters=("upstox", "kotak"))
    assert isinstance(ctx.failover_allowed_adapters, tuple)


# ---------------------------------------------------------------------------
# Failover verification (§8.0 verify_for_failover, §11.5)
# ---------------------------------------------------------------------------


def test_failover_to_authorised_candidate_passes() -> None:
    order = _order()
    ctx = _mint(order, adapter_id="dhan", failover_allowed_adapters=("upstox", "kotak"))
    assert ctx.verify_for_failover(order, _ctx(), "upstox") is True


def test_failover_to_unauthorised_candidate_raises() -> None:
    order = _order()
    ctx = _mint(order, adapter_id="dhan", failover_allowed_adapters=("upstox",))
    with pytest.raises(SafetyBypassError, match="candidate_not_in_failover_allowlist"):
        ctx.verify_for_failover(order, _ctx(), "zerodha")


def test_failover_empty_allowlist_raises() -> None:
    """Empty allowlist means 'no failover authorised' — every candidate is rejected."""
    order = _order()
    ctx = _mint(order, adapter_id="dhan", failover_allowed_adapters=())
    with pytest.raises(SafetyBypassError, match="candidate_not_in_failover_allowlist"):
        ctx.verify_for_failover(order, _ctx(), "upstox")


def test_failover_with_forged_signature_raises_signature_mismatch() -> None:
    order = _order()
    ctx = _mint(order, adapter_id="dhan", failover_allowed_adapters=("upstox",))
    forged = SafetyContext(
        gate_id=ctx.gate_id,
        order_hash=ctx.order_hash,
        mode=ctx.mode,
        user_jti=ctx.user_jti,
        adapter_id=ctx.adapter_id,
        account_id=ctx.account_id,
        actor_type=ctx.actor_type,
        intent_source=ctx.intent_source,
        external_nonce_hash=ctx.external_nonce_hash,
        failover_allowed_adapters=ctx.failover_allowed_adapters,
        expires_at=ctx.expires_at,
        signature=b"\x00" * len(ctx.signature),
    )
    with pytest.raises(SafetyBypassError, match="signature_mismatch"):
        forged.verify_for_failover(order, _ctx(), "upstox")
