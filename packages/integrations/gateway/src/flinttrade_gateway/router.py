"""Safety-gated broker router."""

from __future__ import annotations

from typing import Any, Callable

from flinttrade_engine.request_context import RequestContext, parse_selector
from flinttrade_engine.safety import SafetyBypassError, SafetyContext

from .brokers._base import BrokerAdapter, Session
from .brokers.dhan import _ROUTER_TOKEN
from .routing_config import RoutingConfig, RoutingHint


class BrokerRouter:
    """Dispatch broker writes only after SafetyContext verification.

    Routing is config-driven (contract §13): when a :class:`RoutingHint` is
    supplied — or no explicit ``adapter_id`` is passed — the router resolves the
    target ``(adapter_id, account_id)`` from the operator's :class:`RoutingConfig`
    (and the hint's per-call overrides) via :meth:`_resolve`, then runs the
    unchanged verify-then-consume sequence. Passing an explicit ``adapter_id`` /
    ``account_id`` (the legacy direct form) still works and bypasses resolution.
    The router never mints a :class:`SafetyContext`; it only verifies one minted
    by ``flinttrade_engine.safety.gate_order`` (contract §8.1).
    """

    def __init__(
        self,
        adapters: dict[str, BrokerAdapter],
        session_provider: Callable[[RequestContext, str, str], Session],
        *,
        consume_gate: Callable[[str], bool] | None = None,
        config: RoutingConfig | None = None,
    ) -> None:
        self._adapters = adapters
        self._session_provider = session_provider
        # The HMAC secret now lives process-wide in flinttrade_engine.safety
        # (contract §8.0b); verify() reads it internally, so the router no
        # longer threads it through. consume_gate is the atomic one-shot
        # SafetyGate.consume (contract §8.0a); default-True only for tests.
        self._consume_gate = consume_gate or (lambda _gate_id: True)
        # The parsed workspace.json routing config (contract §13). Optional so
        # tests and the legacy explicit-target form work without one.
        self._config = config

    # ------------------------------------------------------------------
    # Resolution (contract §13.2)
    # ------------------------------------------------------------------

    def _resolve(
        self,
        routing_key: str,
        order: Any,
        hint: RoutingHint | None,
    ) -> tuple[str, str]:
        """Resolve ``routing_key`` to a concrete ``(adapter_id, account_id)``.

        Order of precedence (contract §13.2/§13.4):
        1. ``hint.adapter_id`` overrides the adapter; otherwise the selector is
           looked up from the config for ``routing_key`` and split on the first
           colon to recover the adapter and account.
        2. ``hint.account_id`` overrides the parsed account.
        3. The account falls back to ``"default"`` when neither yields one.

        Raises:
            ValueError: For an unknown ``routing_key``, or when no config and no
                ``hint.adapter_id`` are available to resolve from.
        """
        adapter_id = ""
        account_id = ""

        if hint is not None and hint.adapter_id:
            adapter_id = hint.adapter_id
            # Borrow the account from the config selector for this task, if any,
            # so a pure adapter override still picks up the configured account.
            if self._config is not None:
                selector = self._config.resolve(routing_key, order)
                if selector is not None:
                    try:
                        _adapter, account_id = parse_selector(selector)
                    except ValueError:
                        account_id = ""
        else:
            if self._config is None:
                raise ValueError(
                    f"cannot resolve routing key {routing_key!r}: BrokerRouter has "
                    "no RoutingConfig and no RoutingHint.adapter_id override"
                )
            selector = self._config.resolve(routing_key, order)
            if selector is None:
                raise ValueError(f"unknown routing key {routing_key!r}")
            adapter_id, account_id = parse_selector(selector)

        if hint is not None and hint.account_id:
            account_id = hint.account_id
        if not account_id:
            account_id = "default"
        return adapter_id, account_id

    # ------------------------------------------------------------------
    # Write path
    # ------------------------------------------------------------------

    async def place_order(
        self,
        request_ctx: RequestContext,
        *,
        order: Any,
        safety_ctx: SafetyContext,
        adapter_id: str | None = None,
        account_id: str | None = None,
        hint: RoutingHint | None = None,
        routing_key: str = "execution",
    ) -> Any:
        if hint is not None or adapter_id is None:
            adapter_id, account_id = self._resolve(routing_key, order, hint)
        session = self._session_provider(request_ctx, adapter_id, account_id)
        if session.is_read_only:
            raise SafetyBypassError(f"session {account_id!r} is read-only")
        self._verify_safety(request_ctx, order, safety_ctx, adapter_id, account_id)
        return await self._adapters[adapter_id].place_order(session, order, _router_token=_ROUTER_TOKEN)

    # ------------------------------------------------------------------
    # Read path
    # ------------------------------------------------------------------

    async def quotes(
        self,
        request_ctx: RequestContext,
        *,
        symbols: list[str],
        adapter_id: str | None = None,
        account_id: str | None = None,
        hint: RoutingHint | None = None,
        routing_key: str = "data.quote",
    ) -> list[Any]:
        if hint is not None or adapter_id is None:
            adapter_id, account_id = self._resolve(routing_key, None, hint)
        session = self._session_provider(request_ctx, adapter_id, account_id)
        return await self._adapters[adapter_id].quotes(session, symbols)

    def _verify_safety(
        self,
        request_ctx: RequestContext,
        order: Any,
        safety_ctx: SafetyContext,
        adapter_id: str,
        account_id: str,
    ) -> None:
        # 1. cryptographic + field-by-field verification against THIS order,
        #    mode, caller, actor, and resolved (adapter_id, account_id) selector
        #    (contract §8.0 S1/S10 + identity X7).
        if not safety_ctx.verify(order, request_ctx, adapter_id, account_id):
            raise SafetyBypassError("SafetyContext verification failed")
        # 2. atomic one-shot consumption — guards same-order/same-jti replay.
        if not self._consume_gate(safety_ctx.gate_id):
            raise SafetyBypassError("SafetyContext gate was already consumed")
