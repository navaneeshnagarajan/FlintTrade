"""Safety-gated broker router."""

from __future__ import annotations

from collections.abc import Awaitable, Mapping
from typing import Any, Callable

from flinttrade_core.exceptions import UnsupportedCapabilityError
from flinttrade_engine.request_context import RequestContext, parse_selector
from flinttrade_engine.safety import GATED_WRITE_VERBS, SafetyBypassError, SafetyContext

from .brokers._base import ROUTER_TOKEN as _ROUTER_TOKEN
from .brokers._base import BrokerAdapter, Session
from .routing_config import RoutingConfig, RoutingHint


# ---------------------------------------------------------------------------
# Extended gated write verbs (contract §8.1 — table-driven, single gated path)
# ---------------------------------------------------------------------------
#
# Every dispatcher below extracts the adapter call arguments FROM the verified
# canonical payload (the mapping gate_broker_write signed), so no unhashed
# mutable field can ever reach the broker, and passes the per-process
# _ROUTER_TOKEN so the adapter's write guard recognises a real router dispatch.

_GatedDispatch = Callable[[BrokerAdapter, Session, Mapping[str, Any]], Awaitable[Any]]


def _adapter_write(adapter: BrokerAdapter, verb: str) -> Callable[..., Awaitable[Any]]:
    """Resolve ``verb`` on ``adapter``, or refuse with a capability error.

    Raises:
        UnsupportedCapabilityError: When the adapter does not implement ``verb``
            (e.g. ``cancel_all_orders`` on a broker without a sweep endpoint).
    """
    method = getattr(adapter, verb, None)
    if not callable(method):
        broker = getattr(adapter, "broker_id", type(adapter).__name__)
        raise UnsupportedCapabilityError(
            f"broker adapter {broker!r} does not support the gated write verb {verb!r}"
        )
    return method


def _required(payload: Mapping[str, Any], key: str) -> Any:
    """Fetch a required field from a verified gated payload.

    Raises:
        ValueError: When the signed payload lacks ``key`` (a caller bug — the
            payload was minted without a field its verb requires).
    """
    if key not in payload:
        raise ValueError(f"gated payload is missing required field {key!r}")
    return payload[key]


def _optional_kwargs(payload: Mapping[str, Any], *keys: str) -> dict[str, Any]:
    """Collect optional pass-through kwargs: only fields present and not None.

    Adapters differ in which optional narrowing kwargs they accept (e.g. Upstox
    ``exit_all_positions`` takes ``tag``/``segment``; Dhan's takes none), so a
    field omitted from the signed payload is simply not forwarded — the absence
    itself is covered by the canonical hash.
    """
    return {k: payload[k] for k in keys if payload.get(k) is not None}


async def _dispatch_modify_forever(adapter: BrokerAdapter, session: Session, p: Mapping[str, Any]) -> Any:
    fn = _adapter_write(adapter, "modify_forever")
    return await fn(session, str(_required(p, "order_id")), dict(_required(p, "changes")), _router_token=_ROUTER_TOKEN)


async def _dispatch_cancel_forever(adapter: BrokerAdapter, session: Session, p: Mapping[str, Any]) -> Any:
    fn = _adapter_write(adapter, "cancel_forever")
    return await fn(session, str(_required(p, "order_id")), _router_token=_ROUTER_TOKEN)


async def _dispatch_modify_super_order(adapter: BrokerAdapter, session: Session, p: Mapping[str, Any]) -> Any:
    fn = _adapter_write(adapter, "modify_super_order")
    return await fn(session, str(_required(p, "order_id")), dict(_required(p, "changes")), _router_token=_ROUTER_TOKEN)


async def _dispatch_cancel_super_order(adapter: BrokerAdapter, session: Session, p: Mapping[str, Any]) -> Any:
    fn = _adapter_write(adapter, "cancel_super_order")
    return await fn(
        session, str(_required(p, "order_id")), str(p.get("leg", "ENTRY_LEG")), _router_token=_ROUTER_TOKEN
    )


async def _dispatch_place_conditional_trigger(adapter: BrokerAdapter, session: Session, p: Mapping[str, Any]) -> Any:
    fn = _adapter_write(adapter, "place_conditional_trigger")
    return await fn(
        session, dict(_required(p, "condition")), list(_required(p, "orders")), _router_token=_ROUTER_TOKEN
    )


async def _dispatch_modify_conditional_trigger(adapter: BrokerAdapter, session: Session, p: Mapping[str, Any]) -> Any:
    fn = _adapter_write(adapter, "modify_conditional_trigger")
    return await fn(
        session,
        str(_required(p, "alert_id")),
        dict(_required(p, "condition")),
        list(_required(p, "orders")),
        _router_token=_ROUTER_TOKEN,
    )


async def _dispatch_cancel_conditional_trigger(adapter: BrokerAdapter, session: Session, p: Mapping[str, Any]) -> Any:
    fn = _adapter_write(adapter, "cancel_conditional_trigger")
    return await fn(session, str(_required(p, "alert_id")), _router_token=_ROUTER_TOKEN)


async def _dispatch_convert_position(adapter: BrokerAdapter, session: Session, p: Mapping[str, Any]) -> Any:
    fn = _adapter_write(adapter, "convert_position")
    return await fn(session, dict(_required(p, "req")), _router_token=_ROUTER_TOKEN)


async def _dispatch_exit_all_positions(adapter: BrokerAdapter, session: Session, p: Mapping[str, Any]) -> Any:
    fn = _adapter_write(adapter, "exit_all_positions")
    return await fn(session, **_optional_kwargs(p, "tag", "segment"), _router_token=_ROUTER_TOKEN)


async def _dispatch_place_multi_order(adapter: BrokerAdapter, session: Session, p: Mapping[str, Any]) -> Any:
    fn = _adapter_write(adapter, "place_multi_order")
    return await fn(session, list(_required(p, "orders")), _router_token=_ROUTER_TOKEN)


async def _dispatch_cancel_all_orders(adapter: BrokerAdapter, session: Session, p: Mapping[str, Any]) -> Any:
    fn = _adapter_write(adapter, "cancel_all_orders")
    return await fn(session, **_optional_kwargs(p, "tag", "segment"), _router_token=_ROUTER_TOKEN)


async def _dispatch_cancel_smart_order(adapter: BrokerAdapter, session: Session, p: Mapping[str, Any]) -> Any:
    fn = _adapter_write(adapter, "cancel_smart_order")
    return await fn(
        session, str(_required(p, "order_id")), **_optional_kwargs(p, "segment"), _router_token=_ROUTER_TOKEN
    )


_GATED_VERB_DISPATCH: dict[str, _GatedDispatch] = {
    "modify_forever": _dispatch_modify_forever,
    "cancel_forever": _dispatch_cancel_forever,
    "modify_super_order": _dispatch_modify_super_order,
    "cancel_super_order": _dispatch_cancel_super_order,
    "place_conditional_trigger": _dispatch_place_conditional_trigger,
    "modify_conditional_trigger": _dispatch_modify_conditional_trigger,
    "cancel_conditional_trigger": _dispatch_cancel_conditional_trigger,
    "convert_position": _dispatch_convert_position,
    "exit_all_positions": _dispatch_exit_all_positions,
    "place_multi_order": _dispatch_place_multi_order,
    "cancel_all_orders": _dispatch_cancel_all_orders,
    "cancel_smart_order": _dispatch_cancel_smart_order,
}

# Lock-step guard: the dispatch table and the engine's verb registry MUST agree.
# A real `if` (not `assert`) so the check survives `python -O`.
if set(_GATED_VERB_DISPATCH) != GATED_WRITE_VERBS:  # pragma: no cover - import-time invariant
    raise RuntimeError(
        "BrokerRouter verb table out of lock-step with flinttrade_engine.safety.GATED_WRITE_VERBS: "
        f"table-only={sorted(set(_GATED_VERB_DISPATCH) - GATED_WRITE_VERBS)} "
        f"registry-only={sorted(GATED_WRITE_VERBS - set(_GATED_VERB_DISPATCH))}"
    )


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
        rate_limiter: Any | None = None,
        algo_tag_guard: Any | None = None,
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
        # Optional per-broker API rate limiter. A pure throttle that runs BELOW
        # the gate (after verify + gate-consume), so it can only delay a dispatch,
        # never bypass safety. None → no throttle (unchanged behaviour).
        self._rate_limiter = rate_limiter
        # Optional algo-tag guard (flinttrade_engine.algo_tag_guard.AlgoTagGuard).
        # For adapters advertising ``capabilities.algo_tag_required`` it relays
        # the operator's broker-registered algo_id onto the dispatch session and
        # enforces the per-(broker, exchange) per-second algo-order ceiling.
        # Below the gate like the rate limiter — it can only tag or refuse a
        # dispatch, never bypass safety. None → no tagging (the adapters'
        # retail-default algo ids apply unchanged).
        self._algo_tag_guard = algo_tag_guard

    @property
    def rate_limiter(self) -> Any | None:
        """The per-broker rate limiter (or None when unthrottled).

        Exposed read-only so the rate-limits settings API can snapshot the live
        effective limits and apply runtime overrides.
        """
        return self._rate_limiter

    async def _throttle(self, adapter_id: str, kind: str) -> None:
        if self._rate_limiter is not None:
            await self._rate_limiter.acquire(adapter_id, kind)

    def _algo_tag(self, adapter_id: str, session: Session, order: Any) -> None:
        """Relay the configured algo_id and count this write for algo-tag brokers.

        Applies only when a guard is wired AND the resolved adapter advertises
        ``capabilities.algo_tag_required`` AND the guard holds a config for this
        broker — an operator without an exchange-registered algo keeps the
        adapter/mapping retail defaults. Runs after ``_verify_safety`` (below
        the gate) so it can only stamp or refuse a verified dispatch.

        Raises:
            flinttrade_engine.algo_tag_guard.AlgoTagLimitError: When the
                per-(broker, exchange) per-second algo-order ceiling would be
                breached — the dispatch is refused before the broker can flag
                the account.
        """
        guard = self._algo_tag_guard
        if guard is None:
            return
        caps = getattr(self._adapters[adapter_id], "capabilities", None)
        if not getattr(caps, "algo_tag_required", False):
            return
        if guard.algo_id_for(adapter_id) is None:
            return
        exchange = getattr(order, "exchange", None)
        if exchange is None and isinstance(order, Mapping):
            exchange = order.get("exchange")
        session.algo_id = guard.tag_order(adapter_id, str(exchange or ""))

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
        self._algo_tag(adapter_id, session, order)
        await self._throttle(adapter_id, "order")
        return await self._adapters[adapter_id].place_order(session, order, _router_token=_ROUTER_TOKEN)

    async def modify_order(
        self,
        request_ctx: RequestContext,
        *,
        order: Any,
        order_id: str,
        changes: dict[str, Any],
        safety_ctx: SafetyContext,
        adapter_id: str | None = None,
        account_id: str | None = None,
        hint: RoutingHint | None = None,
        routing_key: str = "execution",
    ) -> Any:
        """Modify a live order through the same verify-then-consume gate as place.

        ``order`` is the canonical modify fingerprint that ``gate_order`` signed;
        ``order_id`` + ``changes`` are the dispatch payload forwarded to the
        adapter. Resolution, ACL, read-only, SafetyContext verification, and
        one-shot gate consumption are identical to :meth:`place_order`.
        """
        if hint is not None or adapter_id is None:
            adapter_id, account_id = self._resolve(routing_key, order, hint)
        session = self._session_provider(request_ctx, adapter_id, account_id)
        if session.is_read_only:
            raise SafetyBypassError(f"session {account_id!r} is read-only")
        self._verify_safety(request_ctx, order, safety_ctx, adapter_id, account_id)
        self._algo_tag(adapter_id, session, order)
        await self._throttle(adapter_id, "order")
        return await self._adapters[adapter_id].modify_order(
            session, order_id, changes, _router_token=_ROUTER_TOKEN
        )

    async def cancel_order(
        self,
        request_ctx: RequestContext,
        *,
        order: Any,
        order_id: str,
        safety_ctx: SafetyContext,
        adapter_id: str | None = None,
        account_id: str | None = None,
        hint: RoutingHint | None = None,
        routing_key: str = "execution",
        extras: Mapping[str, Any] | None = None,
    ) -> Any:
        """Cancel a live order through the same verify-then-consume gate as place.

        ``order`` is the canonical cancel fingerprint that ``gate_order`` signed;
        ``order_id`` is the dispatch payload. Resolution, ACL, read-only,
        SafetyContext verification, and one-shot gate consumption mirror
        :meth:`place_order`.

        ``extras`` are optional adapter-level cancel kwargs (e.g. Kotak Neo's
        ``variety``/``amo`` for bracket/cover leg exits). They are forwarded ONLY
        when every extra is field-matched against the signed ``order``
        fingerprint, so an extra the gate did not cover can never reach the
        broker.
        """
        if hint is not None or adapter_id is None:
            adapter_id, account_id = self._resolve(routing_key, order, hint)
        session = self._session_provider(request_ctx, adapter_id, account_id)
        if session.is_read_only:
            raise SafetyBypassError(f"session {account_id!r} is read-only")
        self._verify_safety(request_ctx, order, safety_ctx, adapter_id, account_id)
        if extras:
            # Field-by-field coverage check: every dispatched extra must appear
            # verbatim in the verified canonical fingerprint (contract §8.0 — no
            # unhashed mutable field may reach the broker).
            if not isinstance(order, Mapping):
                raise SafetyBypassError(
                    "cancel extras require a Mapping cancel fingerprint that covers them"
                )
            mismatched = sorted(k for k, v in extras.items() if order.get(k) != v)
            if mismatched:
                raise SafetyBypassError(
                    f"cancel extras not covered by the signed cancel fingerprint: {mismatched}"
                )
        self._algo_tag(adapter_id, session, order)
        await self._throttle(adapter_id, "order")
        return await self._adapters[adapter_id].cancel_order(
            session, order_id, **dict(extras or {}), _router_token=_ROUTER_TOKEN
        )

    async def execute_gated(
        self,
        request_ctx: RequestContext,
        *,
        verb: str,
        payload: Mapping[str, Any],
        safety_ctx: SafetyContext,
        adapter_id: str | None = None,
        account_id: str | None = None,
        hint: RoutingHint | None = None,
        routing_key: str = "execution",
    ) -> Any:
        """Dispatch an extended gated write verb (contract §8.1, table-driven).

        The SAME verify-then-consume sequence as :meth:`place_order`: resolve the
        target, refuse read-only sessions, verify the one-shot
        :class:`SafetyContext` minted by ``flinttrade_engine.safety.gate_broker_write``
        against THIS payload/mode/jti/actor/selector, consume the gate exactly
        once, throttle, then dispatch with the per-process router token.

        ``payload`` is BOTH the signed canonical fingerprint AND the dispatch
        payload: the verb's dispatcher extracts every adapter argument from this
        verified mapping, so no unhashed mutable field can reach the broker. The
        payload's ``"_op"`` field must equal ``verb`` (it is inside the signed
        canonical hash), so a context minted for one verb can never dispatch
        another.

        Args:
            request_ctx: The live caller's identity bundle.
            verb: One of ``flinttrade_engine.safety.GATED_WRITE_VERBS``.
            payload: The canonical fingerprint mapping the gate was minted over.
            safety_ctx: The one-shot context from ``gate_broker_write``.
            adapter_id: Explicit target adapter (legacy direct form), or None to
                resolve from config/hint.
            account_id: Explicit target account for the direct form.
            hint: Optional per-call routing overrides (contract §13).
            routing_key: Routing-config task key; writes default to "execution".

        Returns:
            Whatever the adapter verb returns (id string, summary dict, or None).

        Raises:
            SafetyBypassError: Unknown verb, ``_op`` mismatch, read-only session,
                failed SafetyContext verification, or replayed gate.
            UnsupportedCapabilityError: The resolved adapter does not implement
                ``verb``.
        """
        dispatch = _GATED_VERB_DISPATCH.get(verb)
        if dispatch is None:
            raise SafetyBypassError(f"unknown gated write verb {verb!r}")
        if not isinstance(payload, Mapping) or payload.get("_op") != verb:
            raise SafetyBypassError(
                f"gated payload _op does not match verb {verb!r} — a SafetyContext "
                "minted for one verb cannot dispatch another"
            )
        if hint is not None or adapter_id is None:
            adapter_id, account_id = self._resolve(routing_key, payload, hint)
        session = self._session_provider(request_ctx, adapter_id, account_id)
        if session.is_read_only:
            raise SafetyBypassError(f"session {account_id!r} is read-only")
        self._verify_safety(request_ctx, payload, safety_ctx, adapter_id, account_id)
        self._algo_tag(adapter_id, session, payload)
        await self._throttle(adapter_id, "order")
        return await dispatch(self._adapters[adapter_id], session, payload)

    # ------------------------------------------------------------------
    # Operator onboarding (trust-on-first-use)
    # ------------------------------------------------------------------

    def authorise_default_actor(self, actor_id: str) -> tuple[str, str] | None:
        """TOFU-authorise ``actor_id`` for the default execution selector if unclaimed.

        Returns the claimed ``(adapter_id, account_id)``, or ``None`` if the
        selector is already authorised, or there is no config/default, or the
        session provider does not support trust-on-first-use. Lets a freshly
        authenticated human operator place gated orders without a manual
        ``account_acls`` edit; non-human actors must still be listed explicitly.
        """
        if self._config is None:
            return None
        selector = self._config.execution.default
        if not selector:
            return None
        try:
            adapter_id, account_id = parse_selector(selector)
        except ValueError:
            return None
        claim = getattr(self._session_provider, "authorise_if_unclaimed", None)
        if claim is None:
            return None
        if claim(adapter_id, account_id, actor_id):
            return adapter_id, account_id
        return None

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
        await self._throttle(adapter_id, "data")
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
