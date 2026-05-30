"""S8/T8 — ChartInk webhook order path routed through the safety-gated BrokerRouter.

These tests prove that when a :class:`ChartInkWebhook` is given a (fake) safety-gated
``broker_router``, an ingested ChartInk scan is *placed* through
``gate_order`` -> ``router.place_order`` with the EXTERNAL-intent identity ChartInk
requires:

  - the minted :class:`RequestContext` carries ``actor_type='external_intent'`` and
    ``intent_source='chartink'``;
  - ``gate_order`` is genuinely invoked (a real one-shot SafetyContext is minted) and
    the resulting context carries the same external-intent metadata bound to the
    ``openalgo:<account_id>`` selector and the sha256 of the webhook nonce;
  - a mismatch — a RequestContext whose ``external_nonce_hash`` does not match the
    raw nonce handed to ``gate_order`` — is rejected (``SafetyBypassError``), so a
    gated context cannot be replayed against a different webhook payload.

No live network is required: a fake router records calls, and ``gate_order`` needs
only the process-wide safety-gate secret (set in a fixture).
"""

from __future__ import annotations

import hashlib

import pytest

from flinttrade_core.exceptions import SafetyBypassError
from flinttrade_engine.safety import gate_order, set_safety_gate_secret
from flinttrade_engine.request_context import RequestContext
from flinttrade_webhooks.chartink import ChartInkConfig, ChartInkWebhook


# A valid, signed ChartInk scan body (JSON form ChartInk actually sends).
_CHARTINK_BODY = (
    '{"scan_name": "OI Spurt Bullish", "stocks": "RELIANCE,TCS", '
    '"triggered_at": "2026-05-30 10:30:00"}'
)
_WEBHOOK_NONCE = "replay-nonce-abc123"


@pytest.fixture(autouse=True)
def _safety_secret() -> None:
    """Bind a dedicated safety-gate HMAC secret so ``gate_order`` can mint."""
    set_safety_gate_secret(b"x" * 32)


class FakeRouter:
    """Records ``place_order`` calls instead of touching a broker.

    The router never verifies the SafetyContext here (that is the gateway's own
    contract, tested elsewhere); it only proves the gated dispatch path *reaches*
    ``place_order`` with the right request context and a real SafetyContext.
    """

    def __init__(self) -> None:
        self.calls: list[dict] = []

    async def place_order(self, request_ctx, *, order, safety_ctx, hint=None, **kwargs):
        self.calls.append(
            {
                "request_ctx": request_ctx,
                "order": order,
                "safety_ctx": safety_ctx,
                "hint": hint,
            }
        )
        return "BROKER-ORDER-1"


def test_chartink_gated_dispatch_routes_through_router_as_external_intent() -> None:
    """A valid ChartInk ingest with a fake router places each order, gated as external_intent."""
    router = FakeRouter()
    handler = ChartInkWebhook(
        config=ChartInkConfig(action="BUY", quantity_per_symbol="5", account_id="acc1"),
        broker_router=router,
    )

    result = handler.handle(_CHARTINK_BODY)
    assert result.is_valid
    assert result.symbols == ["RELIANCE", "TCS"]

    placements = handler.place_orders(result, nonce=_WEBHOOK_NONCE)

    # One placement per symbol, all routed successfully.
    assert len(placements) == 2
    assert all(p.success for p in placements)
    assert {p.symbol for p in placements} == {"RELIANCE", "TCS"}
    assert all(p.broker_order_id == "BROKER-ORDER-1" for p in placements)

    # The router was actually called once per order.
    assert len(router.calls) == 2

    expected_hash = hashlib.sha256(_WEBHOOK_NONCE.encode("utf-8")).hexdigest()
    for call in router.calls:
        ctx: RequestContext = call["request_ctx"]
        # EXTERNAL-intent identity is stamped on the request context.
        assert ctx.actor_type == "external_intent"
        assert ctx.intent_source == "chartink"
        assert ctx.actor_id.startswith("external_intent:chartink:")
        assert ctx.mode == "live"
        assert ctx.selector == "openalgo:acc1"
        assert ctx.external_nonce_hash == expected_hash

        # A real one-shot SafetyContext reached the router, carrying the same
        # external-intent metadata bound to the resolved openalgo account.
        sctx = call["safety_ctx"]
        assert sctx.actor_type == "external_intent"
        assert sctx.intent_source == "chartink"
        assert sctx.external_nonce_hash == expected_hash
        assert sctx.adapter_id == "openalgo"
        assert sctx.account_id == "acc1"

        # The routing hint binds the OpenAlgo selector.
        assert call["hint"].adapter_id == "openalgo"
        assert call["hint"].account_id == "acc1"


def test_gate_order_invoked_with_matching_external_intent_metadata() -> None:
    """Directly assert gate_order accepts matching external_intent metadata + nonce.

    This is the contract the webhook path relies on: the minted RequestContext
    and the kwargs passed to ``gate_order`` agree, so a real SafetyContext is
    produced rather than rejected.
    """
    nonce = _WEBHOOK_NONCE
    nonce_hash = hashlib.sha256(nonce.encode("utf-8")).hexdigest()
    request_ctx = RequestContext(
        jti="chartink-test",
        actor_type="external_intent",
        actor_id="external_intent:chartink:OI Spurt Bullish",
        mode="live",
        intent_source="chartink",
        external_nonce_hash=nonce_hash,
        selector="openalgo:default",
    )

    safety_ctx = gate_order(
        {"symbol": "RELIANCE", "action": "BUY"},
        request_ctx,
        adapter_id="openalgo",
        account_id="default",
        actor_type="external_intent",
        intent_source="chartink",
        external_nonce=nonce,
    )

    assert safety_ctx.actor_type == "external_intent"
    assert safety_ctx.intent_source == "chartink"
    assert safety_ctx.external_nonce_hash == nonce_hash


def test_gate_order_rejects_mismatched_external_nonce() -> None:
    """A nonce that does not match the context's external_nonce_hash is rejected.

    This is the replay defence: a gated external-intent context minted for one
    webhook payload (nonce) cannot be presented with a different raw nonce.
    """
    real_hash = hashlib.sha256(_WEBHOOK_NONCE.encode("utf-8")).hexdigest()
    request_ctx = RequestContext(
        jti="chartink-test",
        actor_type="external_intent",
        actor_id="external_intent:chartink:scan",
        mode="live",
        intent_source="chartink",
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
            intent_source="chartink",
            external_nonce="a-different-nonce",  # does not match real_hash
        )


def test_place_orders_requires_router() -> None:
    """Without an injected router, place_orders raises — the caller-places path is unchanged."""
    handler = ChartInkWebhook(config=ChartInkConfig())
    result = handler.handle(_CHARTINK_BODY)
    assert result.is_valid

    assert not handler.has_router
    with pytest.raises(RuntimeError, match="requires a broker_router"):
        handler.place_orders(result, nonce=_WEBHOOK_NONCE)

    # The legacy parse -> to_orders path still works without a router.
    orders = handler.to_orders(result)
    assert [o.symbol for o in orders] == ["RELIANCE", "TCS"]


def test_synthetic_nonce_is_generated_when_absent() -> None:
    """When no webhook nonce is threaded through, a synthetic uuid nonce binds the gate.

    The router still receives a populated external_nonce_hash (sha256 of the
    generated nonce), proving the dispatch is never left unbound.
    """
    router = FakeRouter()
    handler = ChartInkWebhook(
        config=ChartInkConfig(account_id="default"),
        broker_router=router,
    )
    result = handler.handle(_CHARTINK_BODY)

    placements = handler.place_orders(result)  # no nonce supplied

    assert all(p.success for p in placements)
    assert len(router.calls) == 2
    for call in router.calls:
        ctx: RequestContext = call["request_ctx"]
        assert ctx.actor_type == "external_intent"
        assert ctx.external_nonce_hash  # non-empty synthetic hash
        # 64 hex chars == sha256 digest
        assert len(ctx.external_nonce_hash) == 64
