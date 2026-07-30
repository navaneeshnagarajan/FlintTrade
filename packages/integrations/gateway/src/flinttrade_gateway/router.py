"""Safety-gated broker router."""

from __future__ import annotations

import copy
import json
import logging
import threading
import time
import uuid
from collections.abc import Awaitable, Mapping
from contextlib import nullcontext
from dataclasses import dataclass
from typing import Any, Callable, ContextManager

from flinttrade_core.exceptions import UnsupportedCapabilityError
from flinttrade_engine.request_context import RequestContext, parse_selector
from flinttrade_engine.safety import (
    EMERGENCY_INTENT_SOURCE,
    EMERGENCY_REDUCING_VERBS,
    GATED_WRITE_VERBS,
    EmergencyReductionPlan,
    EmergencyWritePolicy,
    SafetyBypassError,
    SafetyContext,
)

from .brokers._base import ROUTER_TOKEN as _ROUTER_TOKEN
from .brokers._base import BrokerAdapter, Session
from .routing_config import RoutingConfig, RoutingHint

logger = logging.getLogger("flinttrade.gateway.router")


# ---------------------------------------------------------------------------
# Extended gated write verbs (contract §8.1 — table-driven, single gated path)
# ---------------------------------------------------------------------------
#
# Every dispatcher below extracts the adapter call arguments FROM the verified
# canonical payload (the mapping gate_broker_write signed), so no unhashed
# mutable field can ever reach the broker, and passes the per-process
# _ROUTER_TOKEN so the adapter's write guard recognises a real router dispatch.

_AdapterInvokeCallback = Callable[[], None] | None
_GatedDispatch = Callable[
    [BrokerAdapter, Session, Mapping[str, Any], _AdapterInvokeCallback],
    Awaitable[Any],
]

_CANCEL_EXTRA_KEYS = ("variety", "amo", "trading_symbol", "segment")


def _canonical_json(value: object) -> str:
    """Encode with the exact JSON semantics used by SafetyContext.order_hash_for."""
    if isinstance(value, Mapping):
        data: object = value
    else:
        attrs = getattr(value, "__dict__", None)
        data = attrs if isinstance(attrs, dict) else {"_repr": repr(value)}
    try:
        return json.dumps(data, sort_keys=True, separators=(",", ":"), default=str)
    except (TypeError, ValueError, RecursionError) as exc:
        raise SafetyBypassError("broker write payload is not canonically serialisable") from exc


def _detached_snapshot(value: Any) -> Any:
    """Deep-copy one signed value and prove canonical equivalence before awaits."""
    before = _canonical_json(value)
    try:
        snapshot = copy.deepcopy(value)
    except Exception as exc:
        raise SafetyBypassError("broker write payload cannot be detached safely") from exc
    if _canonical_json(snapshot) != before:
        raise SafetyBypassError("detached broker write payload changed canonical form")
    return snapshot


def _signed_mapping_snapshot(value: Any, *, operation: str) -> Mapping[str, Any]:
    """Detach and validate an operation-discriminated signed mapping."""
    if not isinstance(value, Mapping):
        raise SafetyBypassError(
            f"{operation} requires an operation-discriminated Mapping {operation} fingerprint"
        )
    snapshot = _detached_snapshot(value)
    if not isinstance(snapshot, Mapping):  # pragma: no cover - defensive against hostile deepcopy hooks
        raise SafetyBypassError(
            f"{operation} requires an operation-discriminated Mapping {operation} fingerprint"
        )
    if snapshot.get("_op") != operation:
        raise SafetyBypassError(f"signed payload _op does not match required operation {operation!r}")
    return snapshot


def _signed_order_id(payload: Mapping[str, Any]) -> str:
    """Return one non-empty, whitespace-canonical signed broker order id."""
    order_id = payload.get("order_id")
    if (
        not isinstance(order_id, str)
        or not order_id
        or order_id != order_id.strip()
        or not order_id.isprintable()
        or any(character.isspace() for character in order_id)
    ):
        raise SafetyBypassError("signed payload order_id must be a non-empty canonical string")
    return order_id


def _require_canonical_match(actual: object, expected: object, *, field: str) -> None:
    """Refuse Python-equal but canonically different compatibility arguments."""
    if _canonical_json(actual) != _canonical_json(expected):
        raise SafetyBypassError(f"unsigned compatibility {field} is not covered by the signed payload")


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


async def _invoke_adapter(
    method: Callable[..., Awaitable[Any]],
    on_adapter_invoke: _AdapterInvokeCallback,
    *args: Any,
    **kwargs: Any,
) -> Any:
    """Mark the exact boundary after argument validation and before adapter code."""
    if on_adapter_invoke is not None:
        on_adapter_invoke()
    return await method(*args, **kwargs)


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


def _optional_order_segment(payload: Mapping[str, Any]) -> dict[str, str]:
    """Return a present signed INDstocks segment without coercion."""
    if "segment" not in payload:
        return {}
    segment = payload["segment"]
    if not isinstance(segment, str) or segment not in {"EQUITY", "DERIVATIVE"}:
        raise SafetyBypassError("signed payload segment must be EQUITY or DERIVATIVE")
    return {"segment": segment}


async def _dispatch_modify_forever(
    adapter: BrokerAdapter,
    session: Session,
    p: Mapping[str, Any],
    on_adapter_invoke: _AdapterInvokeCallback,
) -> Any:
    fn = _adapter_write(adapter, "modify_forever")
    return await _invoke_adapter(
        fn,
        on_adapter_invoke,
        session,
        str(_required(p, "order_id")),
        dict(_required(p, "changes")),
        _router_token=_ROUTER_TOKEN,
    )


async def _dispatch_cancel_forever(
    adapter: BrokerAdapter,
    session: Session,
    p: Mapping[str, Any],
    on_adapter_invoke: _AdapterInvokeCallback,
) -> Any:
    fn = _adapter_write(adapter, "cancel_forever")
    return await _invoke_adapter(
        fn, on_adapter_invoke, session, str(_required(p, "order_id")), _router_token=_ROUTER_TOKEN
    )


async def _dispatch_modify_super_order(
    adapter: BrokerAdapter,
    session: Session,
    p: Mapping[str, Any],
    on_adapter_invoke: _AdapterInvokeCallback,
) -> Any:
    fn = _adapter_write(adapter, "modify_super_order")
    return await _invoke_adapter(
        fn,
        on_adapter_invoke,
        session,
        str(_required(p, "order_id")),
        dict(_required(p, "changes")),
        _router_token=_ROUTER_TOKEN,
    )


async def _dispatch_cancel_super_order(
    adapter: BrokerAdapter,
    session: Session,
    p: Mapping[str, Any],
    on_adapter_invoke: _AdapterInvokeCallback,
) -> Any:
    fn = _adapter_write(adapter, "cancel_super_order")
    return await _invoke_adapter(
        fn,
        on_adapter_invoke,
        session,
        str(_required(p, "order_id")),
        str(p.get("leg", "ENTRY_LEG")),
        _router_token=_ROUTER_TOKEN,
    )


async def _dispatch_place_conditional_trigger(
    adapter: BrokerAdapter,
    session: Session,
    p: Mapping[str, Any],
    on_adapter_invoke: _AdapterInvokeCallback,
) -> Any:
    fn = _adapter_write(adapter, "place_conditional_trigger")
    return await _invoke_adapter(
        fn,
        on_adapter_invoke,
        session,
        dict(_required(p, "condition")),
        list(_required(p, "orders")),
        _router_token=_ROUTER_TOKEN,
    )


async def _dispatch_modify_conditional_trigger(
    adapter: BrokerAdapter,
    session: Session,
    p: Mapping[str, Any],
    on_adapter_invoke: _AdapterInvokeCallback,
) -> Any:
    fn = _adapter_write(adapter, "modify_conditional_trigger")
    return await _invoke_adapter(
        fn,
        on_adapter_invoke,
        session,
        str(_required(p, "alert_id")),
        dict(_required(p, "condition")),
        list(_required(p, "orders")),
        _router_token=_ROUTER_TOKEN,
    )


async def _dispatch_cancel_conditional_trigger(
    adapter: BrokerAdapter,
    session: Session,
    p: Mapping[str, Any],
    on_adapter_invoke: _AdapterInvokeCallback,
) -> Any:
    fn = _adapter_write(adapter, "cancel_conditional_trigger")
    return await _invoke_adapter(
        fn, on_adapter_invoke, session, str(_required(p, "alert_id")), _router_token=_ROUTER_TOKEN
    )


async def _dispatch_convert_position(
    adapter: BrokerAdapter,
    session: Session,
    p: Mapping[str, Any],
    on_adapter_invoke: _AdapterInvokeCallback,
) -> Any:
    fn = _adapter_write(adapter, "convert_position")
    return await _invoke_adapter(
        fn, on_adapter_invoke, session, dict(_required(p, "req")), _router_token=_ROUTER_TOKEN
    )


async def _dispatch_exit_all_positions(
    adapter: BrokerAdapter,
    session: Session,
    p: Mapping[str, Any],
    on_adapter_invoke: _AdapterInvokeCallback,
) -> Any:
    fn = _adapter_write(adapter, "exit_all_positions")
    return await _invoke_adapter(
        fn,
        on_adapter_invoke,
        session,
        **_optional_kwargs(p, "tag", "segment"),
        _router_token=_ROUTER_TOKEN,
    )


async def _dispatch_place_reducing_order(
    adapter: BrokerAdapter,
    session: Session,
    p: Mapping[str, Any],
    on_adapter_invoke: _AdapterInvokeCallback,
) -> Any:
    fn = _adapter_write(adapter, "place_reducing_order")
    return await _invoke_adapter(fn, on_adapter_invoke, session, dict(p), _router_token=_ROUTER_TOKEN)


async def _dispatch_place_multi_order(
    adapter: BrokerAdapter,
    session: Session,
    p: Mapping[str, Any],
    on_adapter_invoke: _AdapterInvokeCallback,
) -> Any:
    fn = _adapter_write(adapter, "place_multi_order")
    return await _invoke_adapter(
        fn, on_adapter_invoke, session, list(_required(p, "orders")), _router_token=_ROUTER_TOKEN
    )


async def _dispatch_cancel_all_orders(
    adapter: BrokerAdapter,
    session: Session,
    p: Mapping[str, Any],
    on_adapter_invoke: _AdapterInvokeCallback,
) -> Any:
    fn = _adapter_write(adapter, "cancel_all_orders")
    return await _invoke_adapter(
        fn,
        on_adapter_invoke,
        session,
        **_optional_kwargs(p, "tag", "segment"),
        _router_token=_ROUTER_TOKEN,
    )


async def _dispatch_cancel_smart_order(
    adapter: BrokerAdapter,
    session: Session,
    p: Mapping[str, Any],
    on_adapter_invoke: _AdapterInvokeCallback,
) -> Any:
    fn = _adapter_write(adapter, "cancel_smart_order")
    return await _invoke_adapter(
        fn,
        on_adapter_invoke,
        session,
        _signed_order_id(p),
        **_optional_order_segment(p),
        _router_token=_ROUTER_TOKEN,
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
    "place_reducing_order": _dispatch_place_reducing_order,
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


@dataclass(frozen=True)
class LifecycleFaultClearReceipt:
    """Opaque proof that one exact router generation removed one exact fault."""

    receipt_id: str
    resolution_id: str
    attempt_id: str
    selector: str
    router_generation: str


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
        write_admission: Callable[[bool, str], ContextManager[None]] | None = None,
        lifecycle_store: Any | None = None,
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
        self._write_admission = write_admission
        # App-owned durable intent ledger. Kept as a duck-typed dependency so
        # the gateway does not import the engine's storage implementation.
        self._lifecycle_store = lifecycle_store
        self._lifecycle_faults: dict[str, str] = {}
        self._router_generation = uuid.uuid4().hex
        self._lifecycle_clear_receipts: dict[str, LifecycleFaultClearReceipt] = {}
        list_unresolved = getattr(lifecycle_store, "list_unresolved_outcomes", None)
        if callable(list_unresolved):
            try:
                for outcome in list_unresolved():
                    attempt_id = str(outcome.get("attempt_id") or "").strip()
                    if attempt_id:
                        self._lifecycle_faults[attempt_id] = str(
                            outcome.get("error_kind") or "durable unresolved broker outcome"
                        )
            except Exception:
                logger.exception("Could not hydrate durable lifecycle faults into router generation")
        # A router instance is one immutable routing generation. Runtime
        # rebuilds revoke the old generation before dropping it from app state;
        # retained references then fail closed, while writes admitted before
        # revocation are given a bounded opportunity to finish.
        self._write_condition = threading.Condition()
        self._writes_revoked = False
        self._admitted_writes = 0

    def _admit_write(self) -> None:
        """Admit one write unless this router generation was revoked."""
        with self._write_condition:
            if self._writes_revoked:
                raise SafetyBypassError("BrokerRouter generation has been revoked")
            self._admitted_writes += 1

    def _release_write(self) -> None:
        """Release one admitted write and wake drain waiters at zero."""
        with self._write_condition:
            self._admitted_writes -= 1
            if self._admitted_writes == 0:
                self._write_condition.notify_all()

    def revoke_and_drain(self, *, timeout: float = 5.0) -> bool:
        """Permanently revoke this generation and wait boundedly for writes.

        Revocation and the admission check share one condition lock, so a
        concurrent write is ordered atomically: it is either admitted before
        revocation (and included in the drain count) or refused. A timeout does
        not re-enable the router; it remains revoked and later releases can be
        observed by calling this method again.

        Args:
            timeout: Maximum seconds to wait for admitted writes. Zero performs
                an atomic revoke and non-blocking drain check.

        Returns:
            ``True`` when every admitted write drained before the deadline;
            ``False`` on timeout.

        Raises:
            ValueError: When ``timeout`` is negative.
        """
        if timeout < 0:
            raise ValueError("revoke timeout must be non-negative")
        deadline = time.monotonic() + timeout
        with self._write_condition:
            self._writes_revoked = True
            while self._admitted_writes:
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    return False
                self._write_condition.wait(timeout=remaining)
            return True

    @property
    def rate_limiter(self) -> Any | None:
        """The per-broker rate limiter (or None when unthrottled).

        Exposed read-only so the rate-limits settings API can snapshot the live
        effective limits and apply runtime overrides.
        """
        return self._rate_limiter

    @property
    def default_selector(self) -> str | None:
        """The configured ``brokers.execution.default`` selector, or ``None``.

        Exposed read-only so order-route target resolution (core order routes,
        engine bracket routes) can read the running execution default without
        reaching into the private ``_config`` chain. The raw selector string is
        returned; callers parse it themselves (the gateway must not import
        ``parse_selector`` from the engine layer) and keep their own
        ``("openalgo", "default")`` fallback. Returns ``None`` when no config is
        bound or the default is unset/empty.
        """
        if self._config is None:
            return None
        selector = getattr(getattr(self._config, "execution", None), "default", None)
        if not selector:
            return None
        return str(selector).strip() or None

    @property
    def registered_selectors(self) -> tuple[str, ...]:
        """Configured selectors backed by an adapter in this router generation."""
        if self._config is None:
            return ()
        return tuple(
            selector
            for selector in self._config.registered
            if parse_selector(selector)[0] in self._adapters
        )

    @property
    def configured_selectors(self) -> tuple[str, ...]:
        """Every configured account, including adapters unavailable this generation.

        Global emergency controls use this broader set so a dormant or failed
        adapter remains an explicit incomplete target instead of disappearing
        from the durable L5 scope.
        """
        if self._config is None:
            return ()
        return tuple(self._config.registered)

    def authorised_selectors(self, actor_id: str) -> tuple[str, ...]:
        """Return registered selectors explicitly authorised for ``actor_id``.

        This is a read-only snapshot used by parent-owned emergency controls to
        build one normal gated dispatch per account. The session provider still
        performs the authoritative ACL check immediately before every write, so
        a concurrent ACL removal fails closed rather than widening access.
        """
        actor_id = str(actor_id).strip()
        if not actor_id or self._config is None:
            return ()
        authorised: list[str] = []
        for selector in self._config.registered:
            try:
                adapter_id, account_id = parse_selector(selector)
            except ValueError:
                continue
            actors = self._config.account_acls.get(adapter_id, {}).get(account_id, ())
            if actor_id in actors:
                authorised.append(selector)
        return tuple(authorised)

    def clear_lifecycle_fault(
        self,
        attempt_id: str,
        *,
        resolution_id: str,
        selector: str,
    ) -> LifecycleFaultClearReceipt | None:
        """Clear one exact fault and return a receipt bound to this generation."""
        attempt_key = str(attempt_id).strip()
        resolution_key = str(resolution_id).strip()
        selector_key = str(selector).strip()
        store = self._lifecycle_store
        binding_reader = getattr(store, "outcome_resolution_binding", None)
        binding = binding_reader(attempt_key) if attempt_key and callable(binding_reader) else None
        if (
            not isinstance(binding, Mapping)
            or str(binding.get("attempt_id") or "") != attempt_key
            or str(binding.get("resolution_id") or "") != resolution_key
            or str(binding.get("selector") or "") != selector_key
            or str(binding.get("status") or "") != "PENDING_ROUTER_CLEAR"
        ):
            raise SafetyBypassError("order lifecycle attempt is not durably resolved")
        with self._write_condition:
            existing_receipt = self._lifecycle_clear_receipts.get(resolution_key)
            if existing_receipt is not None:
                return existing_receipt
            if attempt_key not in self._lifecycle_faults:
                return None
            del self._lifecycle_faults[attempt_key]
            receipt = LifecycleFaultClearReceipt(
                receipt_id=uuid.uuid4().hex,
                resolution_id=resolution_key,
                attempt_id=attempt_key,
                selector=selector_key,
                router_generation=self._router_generation,
            )
            self._lifecycle_clear_receipts[resolution_key] = receipt
            return receipt

    def verify_lifecycle_fault_clear(
        self,
        receipt: object,
        *,
        resolution_id: str,
        attempt_id: str,
        selector: str,
    ) -> bool:
        """Verify a receipt against this still-current in-process generation."""
        if not isinstance(receipt, LifecycleFaultClearReceipt):
            return False
        with self._write_condition:
            stored = self._lifecycle_clear_receipts.get(str(resolution_id).strip())
            return bool(
                stored == receipt
                and receipt.resolution_id == str(resolution_id).strip()
                and receipt.attempt_id == str(attempt_id).strip()
                and receipt.selector == str(selector).strip()
                and receipt.router_generation == self._router_generation
                and receipt.attempt_id not in self._lifecycle_faults
            )

    def _broker_write_lease(
        self,
        emergency_reduction: bool,
        selector: str,
    ) -> ContextManager[None]:
        """Order a normal write against L5 before generation admission."""
        if self._write_admission is None:
            return nullcontext()
        return self._write_admission(emergency_reduction, selector)

    def _prepare_lifecycle(
        self,
        *,
        request_ctx: RequestContext,
        adapter_id: str,
        account_id: str,
        operation: str,
        payload: Any,
        emergency: bool,
    ) -> str | None:
        """Persist normal-write intent before the adapter invocation boundary."""
        store = self._lifecycle_store
        if store is None:
            return None
        if not emergency:
            with self._write_condition:
                faulted = bool(self._lifecycle_faults)
            if faulted:
                raise SafetyBypassError(
                    "order lifecycle ledger requires reconciliation before another broker write"
                )
            try:
                store.assert_write_ready()
            except Exception as exc:
                raise SafetyBypassError(
                    "order lifecycle ledger is not ready for a broker write"
                ) from exc
        try:
            return str(store.prepare_dispatch(
                adapter_id=adapter_id,
                account_id=account_id,
                operation=operation,
                request_context=request_ctx,
                payload=payload,
            ))
        except Exception as exc:
            if emergency:
                logger.critical(
                    "Emergency broker write proceeding without lifecycle attempt: %s",
                    type(exc).__name__,
                )
                return None
            raise SafetyBypassError(
                "order lifecycle ledger could not persist the broker write intent"
            ) from exc

    def _invocation_callback(
        self,
        *,
        attempt_id: str | None,
        external_callback: _AdapterInvokeCallback,
        emergency: bool,
        invoked: list[bool],
    ) -> Callable[[], None]:
        """Build the exact-boundary callback shared by every gated write verb."""
        def callback() -> None:
            if external_callback is not None:
                external_callback()
            if attempt_id is not None:
                try:
                    self._lifecycle_store.mark_invoked(attempt_id)
                except Exception as exc:
                    if not emergency:
                        raise SafetyBypassError(
                            "order lifecycle ledger could not mark adapter invocation"
                        ) from exc
                    logger.critical(
                        "Emergency lifecycle invocation marker failed: %s",
                        type(exc).__name__,
                    )
            invoked[0] = True

        return callback

    def _record_lifecycle_failure(
        self,
        *,
        attempt_id: str | None,
        invoked: bool,
        error: BaseException,
        emergency: bool,
    ) -> None:
        if attempt_id is None:
            return
        operation = "mark_outcome_unknown" if invoked else "mark_failed_before_invoke"
        try:
            getattr(self._lifecycle_store, operation)(attempt_id, type(error).__name__)
        except Exception as ledger_error:
            logger.critical(
                "Lifecycle failure recording failed after broker dispatch error: %s",
                type(ledger_error).__name__,
            )
        if invoked and not emergency:
            with self._write_condition:
                self._lifecycle_faults[attempt_id] = type(error).__name__

    def _record_lifecycle_success(
        self,
        *,
        attempt_id: str | None,
        result: Any,
        emergency: bool,
    ) -> None:
        if attempt_id is None:
            return
        try:
            self._lifecycle_store.acknowledge(attempt_id, result)
        except Exception as exc:
            # The adapter already returned. Raising here could encourage a
            # duplicate broker write, so return its acknowledgement and block
            # later normal writes until reconciliation resolves the uncertainty.
            logger.critical(
                "Broker acknowledgement could not be persisted in lifecycle ledger: %s",
                type(exc).__name__,
            )
            try:
                self._lifecycle_store.mark_outcome_unknown(
                    attempt_id,
                    type(exc).__name__,
                )
            except Exception as transition_error:
                logger.critical(
                    "Lifecycle unknown-outcome marker could not be persisted: %s",
                    type(transition_error).__name__,
                )
                try:
                    self._lifecycle_store.mark_health_critical(type(exc).__name__)
                except Exception as health_error:
                    logger.critical(
                        "Lifecycle health marker could not be persisted: %s",
                        type(health_error).__name__,
                    )
            if not emergency:
                with self._write_condition:
                    self._lifecycle_faults[attempt_id] = type(exc).__name__

    async def _throttle(self, adapter_id: str, kind: str) -> None:
        if self._rate_limiter is not None:
            await self._rate_limiter.acquire(adapter_id, kind)

    @staticmethod
    def _order_exchange(order: Any) -> str:
        """Best-effort exchange for the per-exchange algo ceiling.

        place/modify orders carry it directly; the extended gated verbs
        (forever/super/trigger/…) carry the order under a nested key or per-leg
        list. When it cannot be recovered the caller buckets the write under a
        shared per-broker ``"*"`` key.

        Note the ``"*"`` bucket is a SEPARATE counter from a named exchange, so
        for a broker whose per-second ceiling would be exceeded by
        exchange-tagged + untagged writes combined, the two buckets can each
        stay under the limit while the true aggregate exceeds it — i.e. this is
        not a strict "never under-counts" guarantee. It is acceptable because
        the untagged writes are cancels/modifies of EXISTING orders (the gated
        verbs that carry no exchange), which do not add NEW order-placement rate
        the way place orders do; place orders always carry ``exchange`` and are
        counted correctly per-exchange.
        """
        exchange = getattr(order, "exchange", None)
        if exchange is None and isinstance(order, Mapping):
            exchange = order.get("exchange")
            if exchange is None:
                for key in ("order", "orders", "legs"):
                    nested = order.get(key)
                    if isinstance(nested, (list, tuple)) and nested:
                        nested = nested[0]
                    if isinstance(nested, Mapping) and nested.get("exchange"):
                        exchange = nested.get("exchange")
                        break
        return str(exchange) if exchange else ""

    def _algo_tag(self, adapter_id: str, session: Session, order: Any) -> None:
        """Relay the configured algo_id and count this write for algo-tag brokers.

        Applies only when a guard is wired AND the resolved adapter advertises
        ``capabilities.algo_tag_required`` AND the guard holds a config for this
        broker — an operator without an exchange-registered algo keeps the
        adapter/mapping retail defaults. Runs after ``_verify_safety`` (below
        the gate) so it can only stamp or refuse a verified dispatch.

        The dispatch session comes from the registry and is SHARED across
        writes, so ``session.algo_id`` is set on EVERY tagged path — cleared to
        ``""`` whenever this dispatch is not tagged — otherwise a stale id from
        an earlier order (or from before the operator removed the algo_tags
        config) would keep flowing to the broker uncounted.

        Raises:
            flinttrade_engine.algo_tag_guard.AlgoTagLimitError: When the
                per-(broker, exchange) per-second algo-order ceiling would be
                breached — the dispatch is refused before the broker can flag
                the account.
        """
        guard = self._algo_tag_guard
        caps = getattr(self._adapters[adapter_id], "capabilities", None)
        if (
            guard is None
            or not getattr(caps, "algo_tag_required", False)
            or guard.algo_id_for(adapter_id) is None
        ):
            session.algo_id = ""
            return
        # tag_order may raise AlgoTagLimitError (ceiling breach) — leave the
        # prior algo_id untouched on refusal; the dispatch is aborted anyway.
        session.algo_id = guard.tag_order(adapter_id, self._order_exchange(order) or "*")

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
        signed_order = _detached_snapshot(order)
        with self._broker_write_lease(False, f"{safety_ctx.adapter_id}:{safety_ctx.account_id}"):
            self._admit_write()
            try:
                if hint is not None or adapter_id is None:
                    adapter_id, account_id = self._resolve(routing_key, signed_order, hint)
                session = self._session_provider(request_ctx, adapter_id, account_id)
                if session.is_read_only:
                    raise SafetyBypassError(f"session {account_id!r} is read-only")
                self._verify_safety(request_ctx, signed_order, safety_ctx, adapter_id, account_id)
                self._algo_tag(adapter_id, session, signed_order)
                await self._throttle(adapter_id, "order")
                attempt_id = self._prepare_lifecycle(
                    request_ctx=request_ctx,
                    adapter_id=adapter_id,
                    account_id=account_id,
                    operation="place_order",
                    payload=signed_order,
                    emergency=False,
                )
                invoked = [False]
                try:
                    result = await _invoke_adapter(
                        self._adapters[adapter_id].place_order,
                        self._invocation_callback(
                            attempt_id=attempt_id,
                            external_callback=None,
                            emergency=False,
                            invoked=invoked,
                        ),
                        session,
                        signed_order,
                        _router_token=_ROUTER_TOKEN,
                    )
                except BaseException as exc:
                    self._record_lifecycle_failure(
                        attempt_id=attempt_id,
                        invoked=invoked[0],
                        error=exc,
                        emergency=False,
                    )
                    raise
                self._record_lifecycle_success(
                    attempt_id=attempt_id,
                    result=result,
                    emergency=False,
                )
                return result
            finally:
                self._release_write()

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

        ``order`` is the operation-discriminated modify fingerprint that
        ``gate_order`` signed. ``order_id`` and ``changes`` remain compatibility
        parameters for existing callers, but are validation-only: the adapter
        receives values derived solely from a detached copy of ``order``.
        """
        signed_order = _signed_mapping_snapshot(order, operation="modify")
        signed_order_id = _signed_order_id(signed_order)
        signed_changes = {
            key: value
            for key, value in signed_order.items()
            if key not in {"_op", "order_id", "_requested_change_fields"}
        }
        compatibility_changes = _detached_snapshot(changes)
        if not isinstance(compatibility_changes, Mapping):
            raise SafetyBypassError("modify changes must be a Mapping")
        _require_canonical_match(order_id, signed_order_id, field="order_id")
        _require_canonical_match(compatibility_changes, signed_changes, field="changes")

        with self._broker_write_lease(False, f"{safety_ctx.adapter_id}:{safety_ctx.account_id}"):
            self._admit_write()
            try:
                if hint is not None or adapter_id is None:
                    adapter_id, account_id = self._resolve(routing_key, signed_order, hint)
                session = self._session_provider(request_ctx, adapter_id, account_id)
                if session.is_read_only:
                    raise SafetyBypassError(f"session {account_id!r} is read-only")
                self._verify_safety(request_ctx, signed_order, safety_ctx, adapter_id, account_id)
                self._algo_tag(adapter_id, session, signed_order)
                await self._throttle(adapter_id, "order")
                attempt_id = self._prepare_lifecycle(
                    request_ctx=request_ctx,
                    adapter_id=adapter_id,
                    account_id=account_id,
                    operation="modify_order",
                    payload=signed_order,
                    emergency=False,
                )
                invoked = [False]
                try:
                    result = await _invoke_adapter(
                        self._adapters[adapter_id].modify_order,
                        self._invocation_callback(
                            attempt_id=attempt_id,
                            external_callback=None,
                            emergency=False,
                            invoked=invoked,
                        ),
                        session,
                        signed_order_id,
                        dict(signed_changes),
                        _router_token=_ROUTER_TOKEN,
                    )
                except BaseException as exc:
                    self._record_lifecycle_failure(
                        attempt_id=attempt_id,
                        invoked=invoked[0],
                        error=exc,
                        emergency=False,
                    )
                    raise
                self._record_lifecycle_success(
                    attempt_id=attempt_id,
                    result=result,
                    emergency=False,
                )
                return result
            finally:
                self._release_write()

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
        on_adapter_invoke: _AdapterInvokeCallback = None,
    ) -> Any:
        """Cancel a live order through the same verify-then-consume gate as place.

        ``order`` is the operation-discriminated cancel fingerprint that
        ``gate_order`` signed. ``order_id`` and ``extras`` remain compatibility
        parameters for existing callers, but are validation-only: every adapter
        argument is derived solely from a detached copy of ``order``.

        ``extras`` are optional adapter-level cancel kwargs (e.g. Kotak Neo's
        ``variety``/``amo`` for bracket/cover leg exits). They are forwarded ONLY
        when their exact canonical representation matches the signed fields, so
        Python-equal substitutions such as ``False``/``0`` cannot pass.
        """
        emergency_intent = safety_ctx.intent_source == EMERGENCY_INTENT_SOURCE
        operation = "cancel_order" if emergency_intent else "cancel"
        signed_order = _signed_mapping_snapshot(order, operation=operation)
        signed_order_id = _signed_order_id(signed_order)
        signed_extras = {
            key: signed_order[key]
            for key in _CANCEL_EXTRA_KEYS
            if key in signed_order
        }
        compatibility_extras: Mapping[str, Any]
        if extras is None:
            compatibility_extras = {}
        else:
            detached_extras = _detached_snapshot(extras)
            if not isinstance(detached_extras, Mapping):
                raise SafetyBypassError("cancel extras must be a Mapping")
            compatibility_extras = detached_extras
        _require_canonical_match(order_id, signed_order_id, field="order_id")
        _require_canonical_match(compatibility_extras, signed_extras, field="extras")

        with self._broker_write_lease(
            emergency_intent,
            f"{safety_ctx.adapter_id}:{safety_ctx.account_id}",
        ):
            self._admit_write()
            try:
                if hint is not None or adapter_id is None:
                    adapter_id, account_id = self._resolve(routing_key, signed_order, hint)
                session = self._session_provider(request_ctx, adapter_id, account_id)
                if session.is_read_only:
                    raise SafetyBypassError(f"session {account_id!r} is read-only")
                self._verify_safety(request_ctx, signed_order, safety_ctx, adapter_id, account_id)
                if emergency_intent:
                    session.algo_id = ""
                else:
                    self._algo_tag(adapter_id, session, signed_order)
                await self._throttle(adapter_id, "order")
                attempt_id = self._prepare_lifecycle(
                    request_ctx=request_ctx,
                    adapter_id=adapter_id,
                    account_id=account_id,
                    operation="cancel_order",
                    payload=signed_order,
                    emergency=emergency_intent,
                )
                invoked = [False]
                try:
                    result = await _invoke_adapter(
                        self._adapters[adapter_id].cancel_order,
                        self._invocation_callback(
                            attempt_id=attempt_id,
                            external_callback=on_adapter_invoke,
                            emergency=emergency_intent,
                            invoked=invoked,
                        ),
                        session,
                        signed_order_id,
                        **dict(signed_extras),
                        _router_token=_ROUTER_TOKEN,
                    )
                except BaseException as exc:
                    self._record_lifecycle_failure(
                        attempt_id=attempt_id,
                        invoked=invoked[0],
                        error=exc,
                        emergency=emergency_intent,
                    )
                    raise
                self._record_lifecycle_success(
                    attempt_id=attempt_id,
                    result=result,
                    emergency=emergency_intent,
                )
                return result
            finally:
                self._release_write()

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
        on_adapter_invoke: _AdapterInvokeCallback = None,
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
        signed_payload = _signed_mapping_snapshot(payload, operation=verb)
        emergency_intent = safety_ctx.intent_source == EMERGENCY_INTENT_SOURCE
        if emergency_intent and verb not in EMERGENCY_REDUCING_VERBS:
            raise SafetyBypassError(
                f"emergency intent cannot dispatch non-reducing verb {verb!r}"
            )
        with self._broker_write_lease(
            emergency_intent,
            f"{safety_ctx.adapter_id}:{safety_ctx.account_id}",
        ):
            self._admit_write()
            try:
                if hint is not None or adapter_id is None:
                    adapter_id, account_id = self._resolve(routing_key, signed_payload, hint)
                session = self._session_provider(request_ctx, adapter_id, account_id)
                if session.is_read_only:
                    raise SafetyBypassError(f"session {account_id!r} is read-only")
                self._verify_safety(request_ctx, signed_payload, safety_ctx, adapter_id, account_id)
                if emergency_intent:
                    session.algo_id = ""
                else:
                    self._algo_tag(adapter_id, session, signed_payload)
                await self._throttle(adapter_id, "order")
                attempt_id = self._prepare_lifecycle(
                    request_ctx=request_ctx,
                    adapter_id=adapter_id,
                    account_id=account_id,
                    operation=verb,
                    payload=signed_payload,
                    emergency=emergency_intent,
                )
                invoked = [False]
                try:
                    result = await dispatch(
                        self._adapters[adapter_id],
                        session,
                        signed_payload,
                        self._invocation_callback(
                            attempt_id=attempt_id,
                            external_callback=on_adapter_invoke,
                            emergency=emergency_intent,
                            invoked=invoked,
                        ),
                    )
                except BaseException as exc:
                    self._record_lifecycle_failure(
                        attempt_id=attempt_id,
                        invoked=invoked[0],
                        error=exc,
                        emergency=emergency_intent,
                    )
                    raise
                self._record_lifecycle_success(
                    attempt_id=attempt_id,
                    result=result,
                    emergency=emergency_intent,
                )
                return result
            finally:
                self._release_write()

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

    async def plan_emergency_reduction(
        self,
        request_ctx: RequestContext,
        *,
        policy: EmergencyWritePolicy,
        protected_order_ids: frozenset[str],
        protected_exit_order_ids: frozenset[str],
        protected_exit_tags: frozenset[str],
        unidentified_exit_inflight: bool,
        adapter_id: str,
        account_id: str,
    ) -> EmergencyReductionPlan | None:
        """Read one exact account snapshot and ask the adapter for a bounded plan.

        This method never mutates broker state and never receives the router
        token. Concrete writes from the returned plan must come back through the
        normal one-shot gated methods.
        """
        session = self._session_provider(request_ctx, adapter_id, account_id)
        if session.is_read_only:
            raise SafetyBypassError(f"session {account_id!r} is read-only")
        planner = getattr(self._adapters[adapter_id], "plan_emergency_reduction", None)
        if not callable(planner):
            return None
        await self._throttle(adapter_id, "data")
        plan = await planner(
            session,
            policy=policy,
            protected_order_ids=protected_order_ids,
            protected_exit_order_ids=protected_exit_order_ids,
            protected_exit_tags=protected_exit_tags,
            unidentified_exit_inflight=unidentified_exit_inflight,
        )
        if not isinstance(plan, EmergencyReductionPlan):
            raise SafetyBypassError("adapter returned an invalid emergency reduction plan")
        return plan

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
