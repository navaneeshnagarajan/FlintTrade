"""Webhook order intents rely on gate_order's external-intent contract.

These tests pin the ``gate_order`` contract the webhook dispatch path
(``flinttrade_core.webhook_dispatch.WebhookOrderDispatcher``) relies on:

  - a RequestContext carrying ``actor_type='external_intent'`` with a matching
    ``intent_source`` and ``external_nonce_hash`` mints a real one-shot
    SafetyContext stamped with the same external-intent metadata;
  - a mismatch — a RequestContext whose ``external_nonce_hash`` does not match
    the raw nonce handed to ``gate_order`` — is rejected
    (``SafetyBypassError``), so a gated context cannot be replayed against a
    different webhook payload.

No live network is required: ``gate_order`` needs only the process-wide
safety-gate secret (set in a fixture).
"""

from __future__ import annotations

import hashlib

import pytest

from flinttrade_core.exceptions import SafetyBypassError
from flinttrade_engine.safety import gate_order, set_safety_gate_secret
from flinttrade_engine.request_context import RequestContext

_WEBHOOK_NONCE = "replay-nonce-abc123"


@pytest.fixture(autouse=True)
def _safety_secret() -> None:
    """Bind a dedicated safety-gate HMAC secret so ``gate_order`` can mint."""
    set_safety_gate_secret(b"x" * 32)


def test_gate_order_invoked_with_matching_external_intent_metadata() -> None:
    """Directly assert gate_order accepts matching external_intent metadata + nonce.

    This is the contract the webhook path relies on: the minted RequestContext
    and the kwargs passed to ``gate_order`` agree, so a real SafetyContext is
    produced rather than rejected.
    """
    nonce = _WEBHOOK_NONCE
    nonce_hash = hashlib.sha256(nonce.encode("utf-8")).hexdigest()
    request_ctx = RequestContext(
        jti="webhook-test",
        actor_type="external_intent",
        actor_id="external_intent:webhook:my-signal",
        mode="live",
        intent_source="custom",
        external_nonce_hash=nonce_hash,
        selector="openalgo:default",
    )

    safety_ctx = gate_order(
        {"symbol": "RELIANCE", "action": "BUY"},
        request_ctx,
        adapter_id="openalgo",
        account_id="default",
        actor_type="external_intent",
        intent_source="custom",
        external_nonce=nonce,
    )

    assert safety_ctx.actor_type == "external_intent"
    assert safety_ctx.intent_source == "custom"
    assert safety_ctx.external_nonce_hash == nonce_hash


def test_gate_order_rejects_mismatched_external_nonce() -> None:
    """A nonce that does not match the context's external_nonce_hash is rejected.

    This is the replay defence: a gated external-intent context minted for one
    webhook payload (nonce) cannot be presented with a different raw nonce.
    """
    real_hash = hashlib.sha256(_WEBHOOK_NONCE.encode("utf-8")).hexdigest()
    request_ctx = RequestContext(
        jti="webhook-test",
        actor_type="external_intent",
        actor_id="external_intent:webhook:my-signal",
        mode="live",
        intent_source="custom",
        external_nonce_hash=real_hash,
        selector="openalgo:default",
    )

    with pytest.raises(SafetyBypassError, match="external_nonce_mismatch"):
        gate_order(
            {"symbol": "RELIANCE", "action": "BUY"},
            request_ctx,
            adapter_id="openalgo",
            account_id="default",
            actor_type="external_intent",
            intent_source="custom",
            external_nonce="a-different-nonce",  # does not match real_hash
        )
