"""Safety-gated broker router."""

from __future__ import annotations

from typing import Any, Callable

from flinttrade_engine.request_context import RequestContext
from flinttrade_engine.safety import SafetyBypassError, SafetyContext

from .brokers._base import BrokerAdapter, Session
from .brokers.dhan import _ROUTER_TOKEN


class BrokerRouter:
    """Dispatch broker writes only after SafetyContext verification."""

    def __init__(
        self,
        adapters: dict[str, BrokerAdapter],
        session_provider: Callable[[RequestContext, str, str], Session],
        *,
        safety_gate_secret: str,
        consume_gate: Callable[[str], bool] | None = None,
    ) -> None:
        self._adapters = adapters
        self._session_provider = session_provider
        self._safety_gate_secret = safety_gate_secret
        self._consume_gate = consume_gate or (lambda _gate_id: True)

    def place_order(
        self,
        request_ctx: RequestContext,
        *,
        adapter_id: str,
        account_id: str,
        order: Any,
        safety_ctx: SafetyContext,
    ) -> Any:
        session = self._session_provider(request_ctx, adapter_id, account_id)
        if session.is_read_only:
            raise SafetyBypassError(f"session {account_id!r} is read-only")
        self._verify_safety(request_ctx, order, safety_ctx)
        return self._adapters[adapter_id].place_order(session, order, _router_token=_ROUTER_TOKEN)

    def quotes(self, request_ctx: RequestContext, *, adapter_id: str, account_id: str, symbols: list[str]) -> dict[str, Any]:
        session = self._session_provider(request_ctx, adapter_id, account_id)
        return self._adapters[adapter_id].quotes(session, symbols)

    def _verify_safety(self, request_ctx: RequestContext, order: Any, safety_ctx: SafetyContext) -> None:
        if not safety_ctx.verify(
            order,
            mode=request_ctx.mode,
            jti=request_ctx.jti,
            actor_type=request_ctx.actor_type,
            actor_id=request_ctx.actor_id,
            intent_source=request_ctx.intent_source,
            external_nonce_hash=request_ctx.external_nonce_hash,
            secret=self._safety_gate_secret,
        ):
            raise SafetyBypassError("SafetyContext verification failed")
        if not self._consume_gate(safety_ctx.gate_id):
            raise SafetyBypassError("SafetyContext gate was already consumed")
