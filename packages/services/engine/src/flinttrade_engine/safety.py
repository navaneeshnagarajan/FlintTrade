"""5-layer safety system for order validation and risk management.

Layer 1: Order validation (price, qty, exchange, symbol, market hours)
Layer 2: Position limits (max simultaneous, margin usage)
Layer 3: Portfolio risk (net delta/vega limits for options)
Layer 4: Daily P&L limits (reversible pause, latched new-order hard stop)
Layer 5: Explicit kill switch (cancel all + close all)

Additional guards (not part of the 5-layer per-order pipeline):
- OvertradingGuard: per-symbol cooldown, consecutive-loss streak, daily trade count
- MTMCircuitBreaker: account-level daily MTM loss auto-exit
"""

from __future__ import annotations

import asyncio
import copy
import hashlib
import hmac
import json
import logging
import math
import os
import secrets
import sqlite3
import threading
import time
from collections import defaultdict
from collections.abc import Awaitable, Callable, Iterable, Mapping
from contextlib import asynccontextmanager, closing, contextmanager, nullcontext
from dataclasses import dataclass, field
from datetime import UTC, date, datetime, time as dt_time, timedelta, timezone
from enum import StrEnum
from pathlib import Path
from typing import Any, AsyncIterator, ContextManager, Iterator, Literal, Protocol

from flinttrade_core.exceptions import BrokerError, SafetyBypassError, UnsupportedCapabilityError
from flinttrade_core.models import Order, Position
from flinttrade_core.secure_file import harden
from flinttrade_engine.daily_pnl_state import (
    DailyPnLState,
    DailyPnLStateError,
    DailyPnLStateStoreProtocol,
    InMemoryDailyPnLStateStore,
)
from flinttrade_engine.emergency_intents import (
    EmergencyDispatchIntentJournal,
    EmergencyEpisodeRecord,
    EmergencyIntentConflict,
    EmergencyIntentJournalProtocol,
    EmergencyIntentRecord,
    InMemoryEmergencyIntentJournal,
)
from flinttrade_engine.request_context import RequestContext

logger = logging.getLogger("flinttrade.engine.safety")

IST = timezone(timedelta(hours=5, minutes=30))


class GenerationLeaseUnavailableError(SafetyBypassError):
    """A routing generation could not be leased within its bounded deadline."""


@contextmanager
def bounded_generation_lease(
    lock: Any,
    *,
    timeout_seconds: float,
) -> Iterator[None]:
    """Acquire a re-entrant routing-generation lock with a bounded wait.

    The global lock order is generation lease, then :class:`KillSwitch`
    condition, then router-generation condition. Callers must never acquire this
    outer lease from a callback already running under the kill-switch condition.
    """
    timeout = float(timeout_seconds)
    if timeout < 0:
        raise ValueError("generation lease timeout must be non-negative")
    acquire = getattr(lock, "acquire", None)
    release = getattr(lock, "release", None)
    if not callable(acquire) or not callable(release):
        raise GenerationLeaseUnavailableError("routing generation lease is unavailable")
    if not acquire(timeout=timeout):
        raise GenerationLeaseUnavailableError("routing generation lease acquisition timed out")
    try:
        yield
    finally:
        release()


# ---------------------------------------------------------------------------
# SafetyContext — one-shot HMAC ticket gating broker writes (contract §8.0)
# ---------------------------------------------------------------------------

# Dedicated process-wide safety-gate HMAC secret (contract §8.0b). MUST be a
# separate key from jwt_secret / webhook_hmac_secret, loaded once at startup
# from ~/.flinttrade/safety_gate_secret. Kept module-private so it never enters
# the SafetyContext dataclass (and therefore never leaks via repr/eq).
_SAFETY_GATE_SECRET: bytes | None = None


def set_safety_gate_secret(secret: bytes) -> None:
    """Bind the process-wide dedicated safety-gate HMAC secret (contract §8.0b).

    Called once at process start with the >=32-byte key. Re-binding (rotation
    or tests) instantly invalidates every in-flight :class:`SafetyContext`;
    that is acceptable because the 10 s TTL guarantees a natural drain window
    (contract §8.0b rotation procedure).
    """
    global _SAFETY_GATE_SECRET
    if not isinstance(secret, (bytes, bytearray)) or len(secret) < 32:
        raise ValueError("safety_gate_secret must be >= 32 random bytes")
    _SAFETY_GATE_SECRET = bytes(secret)


def _get_safety_gate_secret() -> bytes:
    if _SAFETY_GATE_SECRET is None:
        raise SafetyBypassError(
            "safety_gate_secret not initialised; call set_safety_gate_secret() "
            "at process start before minting or verifying any SafetyContext."
        )
    return _SAFETY_GATE_SECRET


def _canonical_order_hash(order: object) -> str:
    """sha256 of the deterministic canonical-JSON of the order (contract §8.0).

    The same order hashed at mint time and at verify time MUST yield the same
    digest; any field change flips the hash and the context fails to verify,
    closing the order-substitution replay vector.

    The routed-order path feeds a plain ``dict`` body straight through
    ``gate_order`` (see ``order_routes.py``), so a :class:`~collections.abc.Mapping`
    MUST be canonicalised directly — ``sort_keys`` makes the digest independent
    of dict-key *insertion* order, keeping mint and verify consistent. Ordinary
    objects are canonicalised via their ``__dict__``; only a genuinely
    un-serialisable non-mapping falls back to ``repr``.
    """
    if isinstance(order, Mapping):
        data: object = order
    else:
        attrs = getattr(order, "__dict__", None)
        data = attrs if isinstance(attrs, dict) else {"_repr": repr(order)}
    payload = json.dumps(data, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _hmac_canonical(
    *,
    gate_id: str,
    order_hash: str,
    mode: str,
    user_jti: str,
    adapter_id: str,
    account_id: str,
    actor_type: str,
    intent_source: str | None,
    external_nonce_hash: str | None,
    failover_allowed_adapters: tuple[str, ...],
    expires_at: datetime,
) -> bytes:
    """HMAC-SHA256 over the canonical signed tuple (contract §8.0).

    The tuple is the *complete* set of fields that must match at verify time.
    `account_id` is signed alongside `adapter_id` (the selector-bound principal,
    identity X7) so the resolved account cannot be swapped after the gate is
    minted. `failover_allowed_adapters` is signed as an ordered list so the
    operator's pre-authorised failover allowlist cannot be tampered with after
    minting.
    """
    material = json.dumps(
        [
            gate_id,
            order_hash,
            mode,
            user_jti,
            adapter_id,
            account_id,
            actor_type,
            intent_source,
            external_nonce_hash,
            list(failover_allowed_adapters),
            expires_at.astimezone(UTC).isoformat(),
        ],
        separators=(",", ":"),
        ensure_ascii=False,
    )
    return hmac.new(_get_safety_gate_secret(), material.encode("utf-8"), hashlib.sha256).digest()


@dataclass(frozen=True)
class SafetyContext:
    """One-shot cryptographic ticket gating broker-router write methods.

    The signed canonical tuple (contract §8.0, v1.0.1 actor-identity closure)
    binds the order, the live caller's mode/jti/actor identity, the resolved
    adapter, and the operator's pre-authorised failover allowlist. A context
    minted for one order/mode/caller/adapter cannot be replayed against any
    other within its 10 s window, and `gate_id` is consumed exactly once.
    """

    gate_id: str
    order_hash: str
    mode: Literal["explore", "practice", "live"]
    user_jti: str
    adapter_id: str
    account_id: str
    actor_type: Literal["human", "agent", "external_intent"]
    intent_source: str | None
    external_nonce_hash: str | None
    failover_allowed_adapters: tuple[str, ...]  # immutable: tuple, not list
    expires_at: datetime
    signature: bytes

    def __init_subclass__(cls, **kwargs: object) -> None:
        """Security M15: SafetyContext is final — subclassing is forbidden.

        Raises at class-creation time so no sibling module can subclass and
        override :meth:`verify` to weaken the invariant.
        """
        raise TypeError(
            f"SafetyContext is final; subclass {cls.__name__!r} is forbidden "
            "(Security M15). Adapters and sibling modules MUST consume "
            "SafetyContext as-is."
        )

    @staticmethod
    def order_hash_for(order: object) -> str:
        """Public helper so callers can pre-compute the order hash if needed."""
        return _canonical_order_hash(order)

    @classmethod
    def mint(
        cls,
        order: object,
        *,
        mode: Literal["explore", "practice", "live"],
        user_jti: str,
        adapter_id: str,
        account_id: str = "default",
        actor_type: Literal["human", "agent", "external_intent"],
        intent_source: str | None = None,
        external_nonce_hash: str | None = None,
        failover_allowed_adapters: tuple[str, ...] = (),
        ttl_seconds: int = 10,
    ) -> SafetyContext:
        """Mint a fresh one-shot context. Only ``engine.safety`` mints; adapters
        MUST NOT (contract §8.1).

        ``account_id`` is the resolved account within ``adapter_id`` (the
        selector-bound principal); it is signed into the canonical tuple so the
        gate cannot be replayed against a different account.
        """
        gate_id = secrets.token_urlsafe(18)
        expires_at = datetime.now(tz=UTC) + timedelta(seconds=ttl_seconds)
        order_hash = _canonical_order_hash(order)
        failover = tuple(failover_allowed_adapters)
        signature = _hmac_canonical(
            gate_id=gate_id,
            order_hash=order_hash,
            mode=mode,
            user_jti=user_jti,
            adapter_id=adapter_id,
            account_id=account_id,
            actor_type=actor_type,
            intent_source=intent_source,
            external_nonce_hash=external_nonce_hash,
            failover_allowed_adapters=failover,
            expires_at=expires_at,
        )
        return cls(
            gate_id=gate_id,
            order_hash=order_hash,
            mode=mode,
            user_jti=user_jti,
            adapter_id=adapter_id,
            account_id=account_id,
            actor_type=actor_type,
            intent_source=intent_source,
            external_nonce_hash=external_nonce_hash,
            failover_allowed_adapters=failover,
            expires_at=expires_at,
            signature=signature,
        )

    def verify(
        self,
        order: object,
        request_ctx: RequestContext,
        adapter_id: str,
        account_id: str = "default",
    ) -> bool:
        """Verify this context against the live request and resolved selector.

        Returns True iff the signature is authentic AND every signed dimension
        matches the live request: order shape, mode, jti, resolved adapter,
        resolved account, actor_type, intent_source, external_nonce_hash, and
        not-expired. Any mismatch returns False (the router then raises
        SafetyBypassError).
        """
        expected_sig = _hmac_canonical(
            gate_id=self.gate_id,
            order_hash=self.order_hash,
            mode=self.mode,
            user_jti=self.user_jti,
            adapter_id=self.adapter_id,
            account_id=self.account_id,
            actor_type=self.actor_type,
            intent_source=self.intent_source,
            external_nonce_hash=self.external_nonce_hash,
            failover_allowed_adapters=self.failover_allowed_adapters,
            expires_at=self.expires_at,
        )
        if not hmac.compare_digest(expected_sig, self.signature):
            return False
        if not hmac.compare_digest(_canonical_order_hash(order), self.order_hash):
            return False
        if request_ctx.mode != self.mode:
            return False
        if request_ctx.jti != self.user_jti:
            return False
        if adapter_id != self.adapter_id:
            return False
        if account_id != self.account_id:
            return False
        if request_ctx.actor_type != self.actor_type:
            return False
        if request_ctx.intent_source != self.intent_source:
            return False
        if request_ctx.external_nonce_hash != self.external_nonce_hash:
            return False
        if datetime.now(tz=UTC) >= self.expires_at:
            return False
        return True

    def verify_for_failover(
        self,
        order: object,
        request_ctx: RequestContext,
        candidate_adapter_id: str,
    ) -> bool:
        """Failover-routing verification (contract §8.0 / §11.5, decision 6).

        The HMAC was signed against the PRIMARY ``adapter_id`` at mint time, so
        re-verifying against the candidate would always fail. Instead:

        1. Verify authenticity against ``self.adapter_id`` (the operator-signed
           primary). Failure raises ``SafetyBypassError('signature_mismatch')``.
        2. Separately assert the candidate is in the operator's pre-authorised
           ``failover_allowed_adapters``. Failure raises
           ``SafetyBypassError('candidate_not_in_failover_allowlist')``.

        Failover never re-mints; both gates MUST pass. The distinct reasons keep
        the operator forensic trail unambiguous.

        Contract (the caller MUST honour all of these):

        - ``failover_allowed_adapters`` are BARE adapter ids (e.g. ``"upstox"``),
          NOT ``adapter:account`` selectors. Only the candidate *adapter* is
          re-checked here.
        - The PRIMARY account binding (``self.account_id``) carries over to the
          candidate unchanged. This method neither re-binds nor re-resolves the
          candidate account; the candidate leg executes against the same
          ``account_id`` that was signed into the primary gate.
        - The ``gate_id`` is one-shot. This method does NOT consume a gate. The
          CALLER MUST consume a DISTINCT one-shot gate per dispatched leg and
          MUST NEVER reuse this context's ``gate_id`` across legs (primary +
          each failover candidate), or the one-shot replay guard is defeated.

        Status: failover *dispatch* is NOT yet wired — no caller in ``router.py``
        invokes this path today (the routed-order flow uses :meth:`verify`). This
        method exists as the signed-and-checked contract a future failover
        dispatcher MUST satisfy; the §11.5 multi-leg wiring is deferred.
        """
        # NOT-YET-WIRED (see docstring): no router caller exercises this path
        # yet; it only re-verifies authenticity + allowlist membership and does
        # NOT consume a gate or re-bind the candidate account. The future
        # failover dispatcher owns per-leg gate consumption.
        if not self.verify(order, request_ctx, self.adapter_id, self.account_id):
            raise SafetyBypassError(
                "verify_for_failover: signature_mismatch — context did not verify "
                "against the operator-signed primary adapter"
            )
        if candidate_adapter_id not in self.failover_allowed_adapters:
            raise SafetyBypassError(
                "verify_for_failover: candidate_not_in_failover_allowlist — operator "
                f"gate authorised {sorted(self.failover_allowed_adapters)}, router "
                f"attempted {candidate_adapter_id!r}"
            )
        return True


# ---------------------------------------------------------------------------
# gate_order — the SOLE SafetyContext producer (contract §8.0 / §8.1)
# ---------------------------------------------------------------------------


def gate_order(
    order: object,
    request_ctx: RequestContext,
    adapter_id: str,
    *,
    account_id: str = "default",
    actor_type: Literal["human", "agent", "external_intent"] | None = None,
    intent_source: str | None = None,
    external_nonce: str | None = None,
    failover_allowed_adapters: tuple[str, ...] = (),
    ttl_seconds: int = 10,
) -> SafetyContext:
    """Mint the one-shot :class:`SafetyContext` that authorises a single broker write.

    This is the *only* sanctioned producer of a ``SafetyContext`` (contract §8.1 — the
    grep gate ``test_only_gate_order_mints_safety_context`` asserts adapters never call
    ``SafetyContext(`` directly). ``request_ctx`` is the authoritative identity bundle,
    minted at the verified request boundary (HTTP middleware for human/agent callers, the
    webhook layer for ``external_intent``); the order can only be dispatched by
    :meth:`BrokerRouter.place_order`, which re-verifies the returned context against the
    live request.

    The optional ``actor_type`` / ``intent_source`` / ``external_nonce`` kwargs exist so
    the webhook path can pass actor metadata explicitly (Identity-Trust H11). When passed
    they MUST agree with ``request_ctx`` — a mismatch raises :class:`SafetyBypassError`,
    closing the v1.0.1 C2 loophole where a context minted under one actor identity could
    be presented from another caller path. ``external_nonce`` is hashed (sha256) and the
    hash must match ``request_ctx.external_nonce_hash`` so an external-intent context
    cannot be replayed with a different webhook payload.

    Returns:
        A freshly-minted ``SafetyContext`` bound to ``order``, the resolved ``adapter_id``,
        and the full signed actor-identity tuple.
    """
    if actor_type is not None and actor_type != request_ctx.actor_type:
        raise SafetyBypassError(
            f"gate_order: actor_type_mismatch — caller passed {actor_type!r} but "
            f"request_ctx carries {request_ctx.actor_type!r}"
        )
    if intent_source is not None and intent_source != request_ctx.intent_source:
        raise SafetyBypassError(
            f"gate_order: intent_source_mismatch — caller passed {intent_source!r} but "
            f"request_ctx carries {request_ctx.intent_source!r}"
        )

    external_nonce_hash = request_ctx.external_nonce_hash
    if external_nonce is not None:
        computed = hashlib.sha256(external_nonce.encode("utf-8")).hexdigest()
        if request_ctx.external_nonce_hash is not None and not hmac.compare_digest(
            computed, request_ctx.external_nonce_hash
        ):
            raise SafetyBypassError(
                "gate_order: external_nonce_mismatch — sha256(external_nonce) does not "
                "match request_ctx.external_nonce_hash (payload-replay vector)"
            )
        external_nonce_hash = computed

    return SafetyContext.mint(
        order,
        mode=request_ctx.mode,
        user_jti=request_ctx.jti,
        adapter_id=adapter_id,
        account_id=account_id,
        actor_type=request_ctx.actor_type,
        intent_source=request_ctx.intent_source,
        external_nonce_hash=external_nonce_hash,
        failover_allowed_adapters=tuple(failover_allowed_adapters),
        ttl_seconds=ttl_seconds,
    )


# ---------------------------------------------------------------------------
# Extended gated write verbs (contract §8.1 — ONE gated path for EVERY write)
# ---------------------------------------------------------------------------

GATED_WRITE_VERBS: frozenset[str] = frozenset(
    {
        # Dhan forever (GTT) management
        "modify_forever",
        "cancel_forever",
        # Dhan super-order (bracket/cover leg) management
        "modify_super_order",
        "cancel_super_order",
        # Dhan conditional triggers (v2.5 alerts/orders)
        "place_conditional_trigger",
        "modify_conditional_trigger",
        "cancel_conditional_trigger",
        # Portfolio writes (Dhan + Upstox)
        "convert_position",
        "exit_all_positions",
        "place_reducing_order",
        # Upstox batch writes
        "place_multi_order",
        "cancel_all_orders",
        # IndMoney smart-order family
        "cancel_smart_order",
    }
)
"""Adapter write verbs beyond the place/modify/cancel trio that are dispatchable
ONLY through :meth:`BrokerRouter.execute_gated`. The router's verb table must
stay in lock-step with this registry (it fails at import time if it drifts), and
``gate_broker_write`` refuses to mint a context for any verb not listed here."""


def gate_broker_write(
    verb: str,
    payload: Mapping[str, object],
    request_ctx: RequestContext,
    adapter_id: str,
    *,
    account_id: str = "default",
    actor_type: Literal["human", "agent", "external_intent"] | None = None,
    intent_source: str | None = None,
    external_nonce: str | None = None,
    failover_allowed_adapters: tuple[str, ...] = (),
    ttl_seconds: int = 10,
) -> SafetyContext:
    """Mint the one-shot :class:`SafetyContext` for an extended broker write verb.

    Sibling of :func:`gate_order` (and delegates to it, so ``gate_order`` remains
    the SOLE :class:`SafetyContext` producer — contract §8.1). ``payload`` is the
    verb's complete canonical fingerprint: a mapping whose ``"_op"`` field MUST
    equal ``verb`` and which carries EVERY field the adapter will receive. The
    canonical hash therefore covers the verb discriminator and the whole payload,
    so a context minted for one verb/payload can never be replayed against
    another, and no unhashed mutable field can reach the broker —
    :meth:`BrokerRouter.execute_gated` extracts the dispatch arguments from this
    same verified mapping.

    Args:
        verb: One of :data:`GATED_WRITE_VERBS`.
        payload: The canonical fingerprint mapping (``payload["_op"] == verb``).
        request_ctx: The authoritative identity bundle minted at the verified
            request boundary.
        adapter_id: The broker adapter the write will be routed to.
        account_id: The resolved account within ``adapter_id`` (selector-bound
            principal, identity X7).
        actor_type: Optional explicit actor metadata; must agree with
            ``request_ctx`` (Identity-Trust H11).
        intent_source: Optional explicit intent source; must agree with
            ``request_ctx``.
        external_nonce: Optional per-payload nonce for external-intent callers.
        failover_allowed_adapters: Operator-pre-authorised failover allowlist.
        ttl_seconds: Context time-to-live (default 10 s).

    Returns:
        A freshly-minted one-shot ``SafetyContext`` bound to the verb payload.

    Raises:
        SafetyBypassError: For an unknown verb, a non-mapping payload, or a
            payload whose ``_op`` does not match ``verb``.
    """
    if verb not in GATED_WRITE_VERBS:
        raise SafetyBypassError(f"gate_broker_write: unknown gated write verb {verb!r}")
    if not isinstance(payload, Mapping):
        raise SafetyBypassError(
            "gate_broker_write: payload must be a Mapping — it is the signed "
            "canonical fingerprint the router re-verifies and dispatches from"
        )
    if payload.get("_op") != verb:
        raise SafetyBypassError(
            f"gate_broker_write: payload _op {payload.get('_op')!r} does not match verb {verb!r} — "
            "the verb discriminator must be inside the signed payload"
        )
    return gate_order(
        payload,
        request_ctx,
        adapter_id,
        account_id=account_id,
        actor_type=actor_type,
        intent_source=intent_source,
        external_nonce=external_nonce,
        failover_allowed_adapters=failover_allowed_adapters,
        ttl_seconds=ttl_seconds,
    )


# ---------------------------------------------------------------------------
# Explicit L5/MTM emergency broker-write policy and parent injection contract
# ---------------------------------------------------------------------------

_EMERGENCY_POLICY_VERBS = frozenset({"cancel_all_orders", "exit_all_positions"})
_EMERGENCY_REDUCING_VERBS = _EMERGENCY_POLICY_VERBS | frozenset(
    {
        "cancel_order",
        "cancel_forever",
        "cancel_super_order",
        "cancel_conditional_trigger",
        "cancel_smart_order",
        "place_reducing_order",
    }
)
EMERGENCY_REDUCING_VERBS = _EMERGENCY_REDUCING_VERBS
EMERGENCY_INTENT_SOURCE = "emergency_reduction"


def _emergency_selector_scope(adapter_id: str | None, account_id: str | None) -> str:
    """Return one canonical selector, or an empty string for explicit full scope."""
    if (adapter_id is None) != (account_id is None):
        raise SafetyBypassError("emergency selector requires both adapter_id and account_id")
    if adapter_id is None:
        return ""
    canonical_adapter = str(adapter_id).strip()
    canonical_account = str(account_id).strip()
    if not canonical_adapter or canonical_adapter != adapter_id:
        raise SafetyBypassError("emergency selector adapter_id is missing or non-canonical")
    if not canonical_account or canonical_account != account_id:
        raise SafetyBypassError("emergency selector account_id is missing or non-canonical")
    return f"{canonical_adapter}:{canonical_account}"


@dataclass(frozen=True)
class EmergencyWritePolicy:
    """A closed list of exposure-reducing writes allowed during an emergency.

    Emergency status changes *when* these writes may run; it never changes how
    they reach a broker. Every verb still mints through :func:`gate_broker_write`
    and dispatches through the current :class:`BrokerRouter` generation.
    """

    name: str
    verbs: tuple[str, ...]

    def __post_init__(self) -> None:
        if not self.name.strip():
            raise ValueError("emergency policy name must be non-empty")
        if not self.verbs:
            raise ValueError("emergency policy must contain at least one verb")
        if len(set(self.verbs)) != len(self.verbs):
            raise ValueError("emergency policy verbs must be unique")
        forbidden = sorted(set(self.verbs) - _EMERGENCY_POLICY_VERBS)
        if forbidden:
            raise ValueError(f"emergency policy may contain only exposure-reducing verbs; forbidden={forbidden}")


L5_EMERGENCY_POLICY = EmergencyWritePolicy(
    name="l5_emergency_flatten",
    verbs=("cancel_all_orders", "exit_all_positions"),
)
"""L5 kill-switch policy: cancel resting orders, then flatten positions."""

MTM_EMERGENCY_POLICY = EmergencyWritePolicy(
    name="mtm_loss_flatten",
    verbs=("cancel_all_orders", "exit_all_positions"),
)
"""MTM breaker policy: cancel and flatten only the breached account selector."""


@dataclass(frozen=True)
class EmergencyBrokerTarget:
    """Selector-bound principal supplied by the verified parent boundary."""

    request_ctx: RequestContext
    adapter_id: str
    account_id: str

    def __post_init__(self) -> None:
        adapter_id = self.adapter_id.strip()
        account_id = self.account_id.strip()
        if not adapter_id or adapter_id != self.adapter_id:
            raise SafetyBypassError("emergency target adapter_id is missing or non-canonical")
        if not account_id or account_id != self.account_id:
            raise SafetyBypassError("emergency target account_id is missing or non-canonical")
        if self.request_ctx.mode != "live":
            raise SafetyBypassError("emergency broker target requires an authenticated live principal")
        if not self.request_ctx.jti or not self.request_ctx.actor_id:
            raise SafetyBypassError("emergency broker target requires a non-empty jti and actor_id")
        expected_selector = f"{adapter_id}:{account_id}"
        if self.request_ctx.selector != expected_selector:
            raise SafetyBypassError("emergency broker target must exactly match the RequestContext selector")


@dataclass(frozen=True)
class EmergencyBrokerWrite:
    """One concrete broker mutation generated from an exact account snapshot."""

    parent_verb: str
    verb: str
    payload: Mapping[str, object]

    def __post_init__(self) -> None:
        if self.parent_verb not in _EMERGENCY_POLICY_VERBS:
            raise ValueError(f"unknown emergency parent verb {self.parent_verb!r}")
        if self.verb not in _EMERGENCY_REDUCING_VERBS:
            raise ValueError(f"unknown emergency concrete verb {self.verb!r}")
        if not isinstance(self.payload, Mapping) or self.payload.get("_op") != self.verb:
            raise ValueError("emergency concrete write payload must include its exact _op")


@dataclass(frozen=True)
class EmergencyReductionPlan:
    """Exact broker-state plan returned by an optional adapter planner."""

    writes: tuple[EmergencyBrokerWrite, ...]
    pending_verbs: frozenset[str]

    def __post_init__(self) -> None:
        forbidden = sorted(set(self.pending_verbs) - _EMERGENCY_POLICY_VERBS)
        if forbidden:
            raise ValueError(f"emergency plan contains unknown pending verbs: {forbidden}")
        if len(self.writes) > 10:
            raise ValueError("emergency plan may contain at most 10 concrete writes")
        if any(write.parent_verb not in self.pending_verbs for write in self.writes):
            raise ValueError("every concrete write must reduce a currently pending policy verb")


@dataclass(frozen=True)
class EmergencyVerbOutcome:
    """Bounded result for one policy verb; raw broker errors never escape."""

    verb: str
    succeeded: bool
    attempted: bool = True
    failure_code: str = ""
    selector: str = ""

    def __post_init__(self) -> None:
        if self.verb not in _EMERGENCY_POLICY_VERBS:
            raise ValueError(f"unknown emergency verb {self.verb!r}")
        if self.succeeded and (not self.attempted or self.failure_code):
            raise ValueError("a successful emergency outcome must be attempted and have no failure code")
        if not self.succeeded and not self.failure_code:
            raise ValueError("a failed emergency outcome requires a bounded failure code")
        if self.selector and ":" not in self.selector:
            raise ValueError("an emergency outcome selector must be '<adapter_id>:<account_id>'")


@dataclass(frozen=True)
class EmergencyDispatchResult:
    """Aggregate result for one explicit emergency-policy dispatch."""

    policy: EmergencyWritePolicy
    outcomes: tuple[EmergencyVerbOutcome, ...]

    def __post_init__(self) -> None:
        if not self.outcomes:
            raise ValueError("emergency result must contain at least one policy outcome")
        grouped_verbs: dict[str, list[str]] = {}
        for outcome in self.outcomes:
            grouped_verbs.setdefault(outcome.selector, []).append(outcome.verb)
        if any(tuple(verbs) != self.policy.verbs for verbs in grouped_verbs.values()):
            raise ValueError("emergency outcomes must match policy verbs in each target's policy order")

    @classmethod
    def failed(
        cls,
        policy: EmergencyWritePolicy,
        failure_code: str,
        *,
        attempted: bool = False,
        selector: str = "",
    ) -> EmergencyDispatchResult:
        """Return the same bounded failure for every verb in ``policy``."""
        return cls(
            policy=policy,
            outcomes=tuple(
                EmergencyVerbOutcome(
                    verb,
                    succeeded=False,
                    attempted=attempted,
                    failure_code=failure_code,
                    selector=selector,
                )
                for verb in policy.verbs
            ),
        )

    @property
    def complete(self) -> bool:
        """Whether every required policy verb reached a successful adapter result."""
        return bool(self.outcomes) and all(outcome.succeeded for outcome in self.outcomes)

    @property
    def failure_codes(self) -> tuple[str, ...]:
        """Bounded failure codes in policy order (successful verbs omitted)."""
        return tuple(outcome.failure_code for outcome in self.outcomes if not outcome.succeeded)

    @property
    def target_count(self) -> int:
        """Number of distinct targets or unresolved target scopes represented."""
        return len(tuple(dict.fromkeys(outcome.selector for outcome in self.outcomes)))

    @property
    def completed_target_count(self) -> int:
        """Number of targets for which every required reducing verb succeeded."""
        if not self.outcomes:
            return 0
        selectors = tuple(dict.fromkeys(outcome.selector for outcome in self.outcomes))
        return sum(
            all(outcome.succeeded for outcome in self.outcomes if outcome.selector == selector)
            for selector in selectors
        )

    def succeeded(self, verb: str) -> bool:
        """Return whether one named policy verb completed successfully."""
        matching = tuple(outcome for outcome in self.outcomes if outcome.verb == verb)
        return bool(matching) and all(outcome.succeeded for outcome in matching)

    def as_dict(self) -> dict[str, Any]:
        """Return a JSON-safe result without raw broker exception text."""
        selectors = tuple(dict.fromkeys(outcome.selector for outcome in self.outcomes))

        def _outcome_dict(outcome: EmergencyVerbOutcome) -> dict[str, Any]:
            return {
                "verb": outcome.verb,
                "attempted": outcome.attempted,
                "succeeded": outcome.succeeded,
                "failure_code": outcome.failure_code or None,
            }

        targets = [
            {
                "selector": selector or None,
                "complete": all(outcome.succeeded for outcome in self.outcomes if outcome.selector == selector),
                "outcomes": [_outcome_dict(outcome) for outcome in self.outcomes if outcome.selector == selector],
            }
            for selector in selectors
        ]
        return {
            "policy": self.policy.name,
            "complete": self.complete,
            "target_count": self.target_count,
            "completed_target_count": self.completed_target_count,
            "summary": f"{self.completed_target_count}/{self.target_count} targets complete",
            "targets": targets,
            "outcomes": [_outcome_dict(outcome) for outcome in self.outcomes],
        }


class EmergencyRouter(Protocol):
    """BrokerRouter surface required by the injected emergency dispatcher."""

    def plan_emergency_reduction(
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
    ) -> Awaitable[EmergencyReductionPlan | None]: ...

    def cancel_order(
        self,
        request_ctx: RequestContext,
        *,
        order: Mapping[str, Any],
        order_id: str,
        safety_ctx: SafetyContext,
        adapter_id: str,
        account_id: str,
        extras: Mapping[str, Any] | None = None,
        on_adapter_invoke: Callable[[], None] | None = None,
    ) -> Awaitable[Any]: ...

    def execute_gated(
        self,
        request_ctx: RequestContext,
        *,
        verb: str,
        payload: Mapping[str, Any],
        safety_ctx: SafetyContext,
        adapter_id: str,
        account_id: str,
        on_adapter_invoke: Callable[[], None] | None = None,
    ) -> Awaitable[Any]: ...


class EmergencyDispatcher(Protocol):
    """Parent-injected synchronous emergency execution contract."""

    def dispatch(
        self,
        policy: EmergencyWritePolicy,
        *,
        reason: str,
        adapter_id: str | None = None,
        account_id: str | None = None,
    ) -> EmergencyDispatchResult: ...


class GatedEmergencyBrokerDispatcher:
    """Mint and dispatch emergency verbs through the current BrokerRouter.

    The parent owns all environment-specific dependencies:

    * exactly one of ``target_provider`` / ``targets_provider`` returns one or
      more authenticated, selector-bound live principals;
    * ``router_provider`` resolves the *currently published* router separately for
      every verb, so retained references cannot evade generation revocation; and
    * ``run_awaitable`` marshals router work onto the owning broker event loop.

    There is deliberately no raw-client fallback. Missing targets, missing or
    retired routers, ACL refusals, unsupported verbs, and broker errors become
    bounded failed outcomes while the caller's L5 latch remains active.
    """

    def __init__(
        self,
        *,
        router_provider: Callable[[], EmergencyRouter | None],
        run_awaitable: Callable[[Awaitable[Any]], Any],
        target_provider: Callable[[], EmergencyBrokerTarget] | None = None,
        targets_provider: Callable[[], Iterable[EmergencyBrokerTarget]] | None = None,
        generation_lease_provider: Callable[[], ContextManager[None]] | None = None,
        intent_journal: EmergencyIntentJournalProtocol | None = None,
        planned_readback_attempts: int = 64,
        planned_quiet_reads: int = 3,
        planned_readback_delay_seconds: float = 0.05,
    ) -> None:
        if (target_provider is None) == (targets_provider is None):
            raise ValueError("provide exactly one emergency target provider")
        self._router_provider = router_provider
        self._target_provider = target_provider
        self._targets_provider = targets_provider
        self._run_awaitable = run_awaitable
        self._generation_lease_provider = generation_lease_provider
        base_journal = intent_journal or InMemoryEmergencyIntentJournal()
        self._intent_journal = (
            base_journal
            if intent_journal is None or isinstance(base_journal, EmergencyDispatchIntentJournal)
            else EmergencyDispatchIntentJournal(base_journal)
        )
        self._planned_readback_attempts = int(planned_readback_attempts)
        self._planned_quiet_reads = int(planned_quiet_reads)
        self._planned_readback_delay_seconds = float(planned_readback_delay_seconds)
        if self._planned_readback_attempts < self._planned_quiet_reads or self._planned_quiet_reads < 1:
            raise ValueError("planned readback attempts must cover at least one quiet window")
        if self._planned_readback_delay_seconds < 0:
            raise ValueError("planned readback delay must be non-negative")

    @property
    def intent_journal_degraded(self) -> bool:
        """Whether emergency writes are using process-local intent durability."""
        return bool(getattr(self._intent_journal, "degraded", False))

    @property
    def durable_intent_journal(self) -> EmergencyIntentJournalProtocol:
        """Return the app-owned journal that remains authoritative for reset."""
        return getattr(self._intent_journal, "primary", self._intent_journal)

    def ensure_degraded_episode(
        self,
        *,
        source: str,
        selector: str,
        session_key: str,
        reason_hash: str,
    ) -> bool:
        """Record an emergency episode in this dispatcher's intent journal.

        The safety latches call this ONLY after the durable journal refused the
        episode write. The dispatcher's wrapper journal records the episode
        process-locally (degrading itself when the durable store is down) so an
        already-latched cancel/flatten can still reserve and dispatch its
        reducing writes instead of being vetoed. Returns ``False`` when even the
        process-local write failed — the caller then keeps its fail-closed
        veto. Durable latch reset never consults the fallback, so this cannot
        clear or mask a durable episode.
        """
        try:
            self._intent_journal.activate_episode(
                source=source,
                selector=selector,
                session_key=session_key,
                reason_hash=reason_hash,
            )
        except Exception:  # noqa: BLE001 - the caller keeps its fail-closed veto
            logger.exception("emergency episode fallback write failed")
            return False
        return True

    def generation_lease(self) -> ContextManager[None]:
        """Return the parent-owned lease spanning target snapshot and dispatch.

        Runtime parents that can replace ``BROKER_ROUTER`` must provide this
        lease. The no-op default preserves isolated/test dispatchers whose router
        generation is immutable.
        """
        if self._generation_lease_provider is None:
            return nullcontext()
        lease = self._generation_lease_provider()
        if not hasattr(lease, "__enter__") or not hasattr(lease, "__exit__"):
            raise GenerationLeaseUnavailableError("generation lease provider returned an invalid context manager")
        return lease

    @staticmethod
    def _failure_code(exc: Exception) -> str:
        if isinstance(exc, SafetyBypassError):
            return "safety_refused"
        if isinstance(exc, UnsupportedCapabilityError):
            return "unsupported_capability"
        if isinstance(exc, KeyError):
            return "target_unavailable"
        if isinstance(exc, BrokerError):
            return "broker_refused"
        return "dispatch_failed"

    @staticmethod
    def _broker_result_failure(result: Any) -> str:
        """Classify broker acknowledgements without exposing broker error bodies."""
        if not isinstance(result, Mapping):
            return ""
        if not result:
            return "invalid_broker_result"
        error = result.get("error")
        if error not in (None, "", (), [], {}):
            return "broker_refused"
        successful_status = False
        if "status" in result:
            status = result.get("status")
            if not isinstance(status, str):
                return "invalid_broker_result"
            canonical_status = status.strip().lower()
            if canonical_status in {"error", "failed", "failure", "rejected", "refused"}:
                return "broker_refused"
            if canonical_status not in {"ok", "success", "succeeded", "accepted", "complete", "completed"}:
                return "invalid_broker_result"
            successful_status = True
        summary_keys = {"errors", "total", "success"}
        present = summary_keys.intersection(result)
        if present:
            if present != summary_keys:
                return "invalid_broker_result"
            errors = result.get("errors")
            total = result.get("total")
            success = result.get("success")
            if (
                not isinstance(errors, (list, tuple))
                or isinstance(total, bool)
                or isinstance(success, bool)
                or not isinstance(total, int)
                or not isinstance(success, int)
            ):
                return "invalid_broker_result"
            total_count = total
            success_count = success
            if total_count < 0 or success_count < 0 or success_count > total_count:
                return "invalid_broker_result"
            if errors or success_count != total_count:
                return "partial_broker_result"
            return ""

        if successful_status:
            return ""
        if "order_ids" in result:
            return ""
        return "invalid_broker_result"

    @classmethod
    def _concrete_result_failure(cls, write: EmergencyBrokerWrite, result: Any) -> str:
        """Apply verb-specific acknowledgement requirements to one mutation."""
        failure = cls._broker_result_failure(result)
        if failure:
            return failure
        if write.verb in {"cancel_all_orders", "exit_all_positions"}:
            if not isinstance(result, Mapping) or not {
                "errors",
                "total",
                "success",
            }.issubset(result):
                return "invalid_broker_result"
        if write.verb == "place_reducing_order":
            try:
                order_ids = cls._result_order_ids(result)
            except SafetyBypassError:
                return "invalid_broker_result"
            if len(order_ids) != 1:
                return "invalid_broker_result"
        return ""

    @staticmethod
    def _journal_source(policy: EmergencyWritePolicy) -> str:
        if policy == L5_EMERGENCY_POLICY:
            return "l5"
        if policy == MTM_EMERGENCY_POLICY:
            return "mtm"
        return "adhoc"

    def _bind_episode_targets(
        self,
        policy: EmergencyWritePolicy,
        selectors: tuple[str, ...],
        *,
        reason_hash: str,
    ) -> None:
        source = self._journal_source(policy)
        if source == "adhoc":
            return
        if source == "mtm" and len(selectors) != 1:
            raise SafetyBypassError("MTM emergency dispatch requires one exact account selector")
        episode_selector = "*" if source == "l5" else selectors[0]
        episode = self._intent_journal.active_episode(
            source=source,
            selector=episode_selector,
        )
        if episode is None:
            episode, _created = self._intent_journal.activate_episode(
                source=source,
                selector=episode_selector,
                session_key=("manual" if source == "l5" else datetime.now(IST).date().isoformat()),
                reason_hash=reason_hash,
            )
        self._intent_journal.record_episode_targets(
            expected=episode,
            selectors=selectors,
        )

    @staticmethod
    def _selector_scope(adapter_id: str | None, account_id: str | None) -> str:
        return _emergency_selector_scope(adapter_id, account_id)

    def _targets(
        self,
        *,
        adapter_id: str | None = None,
        account_id: str | None = None,
    ) -> tuple[EmergencyBrokerTarget, ...]:
        requested_selector = self._selector_scope(adapter_id, account_id)
        if self._targets_provider is not None:
            candidates = tuple(self._targets_provider())
        else:
            assert self._target_provider is not None  # constructor invariant
            candidates = (self._target_provider(),)
        if not candidates or not all(isinstance(target, EmergencyBrokerTarget) for target in candidates):
            raise SafetyBypassError("emergency target provider returned invalid or empty targets")
        selectors = tuple(target.request_ctx.selector for target in candidates)
        if len(set(selectors)) != len(selectors):
            raise SafetyBypassError("emergency target provider returned duplicate selectors")
        if requested_selector:
            candidates = tuple(
                target for target in candidates if target.request_ctx.selector == requested_selector
            )
            if not candidates:
                raise SafetyBypassError("requested emergency selector is unavailable or unauthorised")
        return candidates

    def prepare_targets(
        self,
        *,
        adapter_id: str | None = None,
        account_id: str | None = None,
    ) -> tuple[EmergencyBrokerTarget, ...]:
        """Resolve one immutable target snapshot for coordinated L5 dispatch."""
        return self._targets(adapter_id=adapter_id, account_id=account_id)

    @contextmanager
    def authority(
        self,
        *,
        adapter_id: str | None = None,
        account_id: str | None = None,
    ) -> Iterator[tuple[EmergencyBrokerTarget, ...]]:
        """Hold one router generation and ACL snapshot through caller dispatch.

        Command transports enter this context before changing L5 state and pass
        the yielded targets into :meth:`KillSwitch.activate`. The lease remains
        held until activation and every prepared write return, closing the gap
        between a read-only preflight and the safety latch.
        """
        with self.generation_lease():
            if self._router_provider() is None:
                raise SafetyBypassError("emergency router is unavailable")
            yield self.prepare_targets(adapter_id=adapter_id, account_id=account_id)

    def preflight(self) -> tuple[EmergencyBrokerTarget, ...]:
        """Validate the current router generation and authenticated targets.

        This is intentionally read-only: command transports call it before
        latching L5 so a missing operator profile, ACL identity, selector, or
        current router cannot turn a rejected command into an active kill
        switch. The real dispatch still takes its own generation lease and
        target snapshot immediately before its writes.
        """
        with self.authority() as targets:
            return targets

    def dispatch(
        self,
        policy: EmergencyWritePolicy,
        *,
        reason: str,
        adapter_id: str | None = None,
        account_id: str | None = None,
    ) -> EmergencyDispatchResult:
        """Execute ``policy`` under one optional routing-generation lease."""
        selector = ""
        try:
            selector = self._selector_scope(adapter_id, account_id)
            with self.generation_lease():
                targets = self.prepare_targets(adapter_id=adapter_id, account_id=account_id)
                return self.dispatch_prepared(policy, reason=reason, targets=targets)
        except GenerationLeaseUnavailableError as exc:
            logger.error(
                "Emergency policy %s refused before dispatch: generation_lease_unavailable (%s)",
                policy.name,
                type(exc).__name__,
            )
            return EmergencyDispatchResult.failed(
                policy,
                "generation_lease_unavailable",
                selector=selector,
            )
        except Exception as exc:  # noqa: BLE001 - target failure is bounded and fail-closed
            logger.error(
                "Emergency policy %s refused before dispatch: target_unavailable (%s)",
                policy.name,
                type(exc).__name__,
            )
            return EmergencyDispatchResult.failed(
                policy,
                "target_unavailable",
                selector=selector,
            )

    @staticmethod
    def _emergency_request_context(target: EmergencyBrokerTarget) -> RequestContext:
        return RequestContext(
            jti=target.request_ctx.jti,
            actor_type=target.request_ctx.actor_type,
            actor_id=target.request_ctx.actor_id,
            mode=target.request_ctx.mode,
            intent_source=EMERGENCY_INTENT_SOURCE,
            external_nonce_hash=target.request_ctx.external_nonce_hash,
            selector=target.request_ctx.selector,
        )

    @staticmethod
    def _target_result(
        policy: EmergencyWritePolicy,
        target: EmergencyBrokerTarget,
        *,
        succeeded: bool,
        failure_code: str = "",
        attempted: bool = True,
    ) -> EmergencyDispatchResult:
        return EmergencyDispatchResult(
            policy=policy,
            outcomes=tuple(
                EmergencyVerbOutcome(
                    verb,
                    succeeded=succeeded,
                    attempted=attempted,
                    failure_code=failure_code,
                    selector=target.request_ctx.selector,
                )
                for verb in policy.verbs
            ),
        )

    @staticmethod
    def _pending_target_result(
        policy: EmergencyWritePolicy,
        target: EmergencyBrokerTarget,
        *,
        pending_verbs: frozenset[str],
        failure_code: str,
        attempted: bool,
    ) -> EmergencyDispatchResult:
        """Preserve verbs proven quiet when another policy verb remains blocked."""
        return EmergencyDispatchResult(
            policy=policy,
            outcomes=tuple(
                EmergencyVerbOutcome(
                    verb,
                    succeeded=verb not in pending_verbs,
                    attempted=True if verb not in pending_verbs else attempted,
                    failure_code=failure_code if verb in pending_verbs else "",
                    selector=target.request_ctx.selector,
                )
                for verb in policy.verbs
            ),
        )

    @staticmethod
    def _result_order_ids(result: Any) -> tuple[str, ...]:
        if isinstance(result, str):
            candidates = (result,)
        elif isinstance(result, Mapping):
            raw = result.get("order_ids", ())
            candidates = tuple(raw) if isinstance(raw, (list, tuple)) else ()
        else:
            candidates = ()
        order_ids: list[str] = []
        for candidate in candidates:
            if not isinstance(candidate, str) or not candidate or candidate != candidate.strip():
                raise SafetyBypassError("emergency broker returned a non-canonical order id")
            if not candidate.isprintable() or any(character.isspace() for character in candidate):
                raise SafetyBypassError("emergency broker returned a non-canonical order id")
            order_ids.append(candidate)
        if len(set(order_ids)) != len(order_ids):
            raise SafetyBypassError("emergency broker returned duplicate order ids")
        return tuple(order_ids)

    @staticmethod
    def _planned_cancel_target_id(write: EmergencyBrokerWrite) -> str:
        """Return the canonical broker id targeted by one concrete cancellation."""
        value = write.payload.get("order_id") or write.payload.get("alert_id")
        if not isinstance(value, str) or not value or value != value.strip():
            raise SafetyBypassError("planned emergency cancellation has a non-canonical target id")
        if not value.isprintable() or any(character.isspace() for character in value):
            raise SafetyBypassError("planned emergency cancellation has a non-canonical target id")
        return value

    @classmethod
    def _intent_scope(cls, write: EmergencyBrokerWrite) -> str:
        """Return the stable resource protected by one unresolved mutation."""
        if write.verb.startswith("cancel_") and write.verb != "cancel_all_orders":
            return f"order:{cls._planned_cancel_target_id(write)}"
        if write.verb == "cancel_all_orders":
            raw_target_ids = write.payload.get("_emergency_target_order_ids")
            if raw_target_ids is not None:
                if not isinstance(raw_target_ids, (list, tuple)) or not raw_target_ids:
                    raise SafetyBypassError("planned bulk cancellation has no canonical target set")
                target_ids = cls._result_order_ids({"order_ids": raw_target_ids})
                if target_ids != tuple(sorted(target_ids)):
                    raise SafetyBypassError("planned bulk cancellation target set must be sorted")
                digest = hashlib.sha256(
                    json.dumps(target_ids, separators=(",", ":")).encode("utf-8")
                ).hexdigest()
                return f"orders:{digest}"
            return "orders:*"
        if write.verb == "exit_all_positions":
            return "positions:*"
        if write.verb == "place_reducing_order":
            identity = {
                "symbol": write.payload.get("symbol"),
                "exchange": write.payload.get("exchange"),
                "product": write.payload.get("product"),
            }
            if any(not isinstance(value, str) or not value.strip() for value in identity.values()):
                raise SafetyBypassError("planned reducing write has no canonical position identity")
            digest = hashlib.sha256(
                json.dumps(identity, sort_keys=True, separators=(",", ":")).encode("utf-8")
            ).hexdigest()
            return f"position:{digest}"
        return f"payload:{_canonical_order_hash(write.payload)}"

    @staticmethod
    def _apply_intent_protections(
        records: Iterable[EmergencyIntentRecord],
        *,
        protected_order_ids: set[str],
        protected_exit_order_ids: set[str],
        protected_exit_tags: set[str],
    ) -> None:
        for record in records:
            if record.target_order_id:
                protected_order_ids.add(record.target_order_id)
            if record.exit_tag:
                protected_exit_tags.add(record.exit_tag)
            if record.parent_verb == "exit_all_positions":
                protected_exit_order_ids.update(record.broker_order_ids)
            else:
                protected_order_ids.update(record.broker_order_ids)

    @staticmethod
    def _remove_intent_protections(
        record: EmergencyIntentRecord,
        *,
        protected_order_ids: set[str],
        protected_exit_order_ids: set[str],
        protected_exit_tags: set[str],
    ) -> None:
        """Undo protections for an intent released before adapter invocation."""
        if record.target_order_id:
            protected_order_ids.discard(record.target_order_id)
        if record.exit_tag:
            protected_exit_tags.discard(record.exit_tag)
        if record.parent_verb == "exit_all_positions":
            protected_exit_order_ids.difference_update(record.broker_order_ids)
        else:
            protected_order_ids.difference_update(record.broker_order_ids)

    @staticmethod
    def _prepare_concrete_write(
        target: EmergencyBrokerTarget,
        request_ctx: RequestContext,
        write: EmergencyBrokerWrite,
        *,
        policy: EmergencyWritePolicy,
        reason_hash: str,
    ) -> tuple[dict[str, Any], SafetyContext]:
        """Canonicalise and mint before an intent can become outcome-unknown."""
        canonical: dict[str, Any] = {
            **dict(write.payload),
            "_emergency_policy": policy.name,
            "_emergency_reason_hash": reason_hash,
        }
        if write.verb == "cancel_order":
            order_id = str(canonical.get("order_id") or "")
            if not order_id:
                raise SafetyBypassError("planned emergency cancellation has no order id")
            safety_ctx = gate_order(
                canonical,
                request_ctx,
                target.adapter_id,
                account_id=target.account_id,
            )
        else:
            safety_ctx = gate_broker_write(
                write.verb,
                canonical,
                request_ctx,
                target.adapter_id,
                account_id=target.account_id,
            )
        return canonical, safety_ctx

    def _execute_concrete_write(
        self,
        router: EmergencyRouter,
        target: EmergencyBrokerTarget,
        request_ctx: RequestContext,
        write: EmergencyBrokerWrite,
        *,
        canonical: Mapping[str, Any],
        safety_ctx: SafetyContext,
        on_adapter_invoke: Callable[[], None],
    ) -> Any:
        if write.verb == "cancel_order":
            order_id = str(canonical.get("order_id") or "")
            extras = {
                key: canonical[key]
                for key in ("variety", "amo", "trading_symbol", "segment")
                if key in canonical
            }
            kwargs: dict[str, Any] = {}
            if extras:
                kwargs["extras"] = extras
            return self._run_awaitable(
                router.cancel_order(
                    request_ctx,
                    order=canonical,
                    order_id=order_id,
                    safety_ctx=safety_ctx,
                    adapter_id=target.adapter_id,
                    account_id=target.account_id,
                    on_adapter_invoke=on_adapter_invoke,
                    **kwargs,
                )
            )

        return self._run_awaitable(
            router.execute_gated(
                request_ctx,
                verb=write.verb,
                payload=canonical,
                safety_ctx=safety_ctx,
                adapter_id=target.adapter_id,
                account_id=target.account_id,
                on_adapter_invoke=on_adapter_invoke,
            )
        )

    def _dispatch_planned_target(
        self,
        policy: EmergencyWritePolicy,
        target: EmergencyBrokerTarget,
        request_ctx: RequestContext,
        *,
        reason_hash: str,
    ) -> tuple[EmergencyDispatchResult | None, EmergencyRouter | None]:
        journal_source = self._journal_source(policy)
        protected_order_ids: set[str] = set()
        protected_exit_order_ids: set[str] = set()
        protected_exit_tags: set[str] = set()
        consecutive_quiet = 0
        attempted = False
        successful_writes = 0
        terminal_failures: dict[tuple[str, str], str] = {}

        try:
            unresolved_records = self._intent_journal.unresolved(
                target.request_ctx.selector,
                policy.verbs,
                source=journal_source,
            )
        except Exception as exc:  # noqa: BLE001 - no journal means no broker mutation
            logger.error("Emergency intent journal unavailable (%s)", type(exc).__name__)
            return (
                self._target_result(
                    policy,
                    target,
                    succeeded=False,
                    failure_code="intent_journal_unavailable",
                    attempted=False,
                ),
                None,
            )
        unresolved_by_scope = {
            (record.parent_verb, record.scope): record for record in unresolved_records
        }
        self._apply_intent_protections(
            unresolved_records,
            protected_order_ids=protected_order_ids,
            protected_exit_order_ids=protected_exit_order_ids,
            protected_exit_tags=protected_exit_tags,
        )

        def write_key(write: EmergencyBrokerWrite) -> tuple[str, str]:
            return write.verb, _canonical_order_hash(write.payload)

        for attempt in range(self._planned_readback_attempts):
            try:
                router = self._router_provider()
            except Exception as exc:  # noqa: BLE001 - provider failure is bounded
                logger.error("Emergency planner could not resolve current router (%s)", type(exc).__name__)
                return (
                    self._target_result(
                        policy,
                        target,
                        succeeded=False,
                        failure_code="router_unavailable",
                        attempted=attempted,
                    ),
                    None,
                )
            if router is None:
                return (
                    self._target_result(
                        policy,
                        target,
                        succeeded=False,
                        failure_code="router_unavailable",
                        attempted=attempted,
                    ),
                    None,
                )
            planner = getattr(router, "plan_emergency_reduction", None)
            if not callable(planner):
                return (
                    self._target_result(
                        policy,
                        target,
                        succeeded=False,
                        failure_code="authoritative_readback_unavailable",
                        attempted=attempted,
                    ),
                    None,
                )
            try:
                plan = self._run_awaitable(
                    planner(
                        request_ctx,
                        policy=policy,
                        protected_order_ids=frozenset(protected_order_ids),
                        protected_exit_order_ids=frozenset(protected_exit_order_ids),
                        protected_exit_tags=frozenset(protected_exit_tags),
                        unidentified_exit_inflight=any(
                            record.verb == "exit_all_positions"
                            and not record.exit_tag
                            and not record.broker_order_ids
                            for record in unresolved_by_scope.values()
                        ),
                        adapter_id=target.adapter_id,
                        account_id=target.account_id,
                    )
                )
            except Exception as exc:  # noqa: BLE001 - planner read failure is bounded
                failure_code = self._failure_code(exc)
                logger.error("Emergency state planning failed closed: %s (%s)", failure_code, type(exc).__name__)
                return (
                    self._target_result(
                        policy,
                        target,
                        succeeded=False,
                        failure_code=failure_code,
                        attempted=attempted,
                    ),
                    None,
                )
            if plan is None:
                return (
                    self._target_result(
                        policy,
                        target,
                        succeeded=False,
                        failure_code="authoritative_readback_unavailable",
                        attempted=attempted,
                    ),
                    None,
                )
            if not isinstance(plan, EmergencyReductionPlan):
                return (
                    self._target_result(
                        policy,
                        target,
                        succeeded=False,
                        failure_code="invalid_broker_result",
                        attempted=attempted,
                    ),
                    None,
                )
            if not plan.pending_verbs:
                consecutive_quiet += 1
                if consecutive_quiet >= self._planned_quiet_reads:
                    try:
                        expected_intent_ids = tuple(
                            sorted(record.intent_id for record in unresolved_by_scope.values())
                        )
                        settled = self._intent_journal.settle(
                            target.request_ctx.selector,
                            policy.verbs,
                            source=journal_source,
                            expected_intent_ids=expected_intent_ids,
                        )
                        if not settled:
                            return (
                                self._target_result(
                                    policy,
                                    target,
                                    succeeded=False,
                                    failure_code="intent_journal_conflict",
                                    attempted=attempted,
                                ),
                                None,
                            )
                    except Exception as exc:  # noqa: BLE001 - unresolved intent remains fail-closed
                        logger.error("Emergency intent settlement failed (%s)", type(exc).__name__)
                        return (
                            self._target_result(
                                policy,
                                target,
                                succeeded=False,
                                failure_code="intent_journal_unavailable",
                                attempted=attempted,
                            ),
                            None,
                        )
                    return self._target_result(policy, target, succeeded=True, attempted=True), None
            else:
                consecutive_quiet = 0
                blocked_failures: list[str] = []
                newly_attempted = 0
                for write in plan.writes:
                    key = write_key(write)
                    if key in terminal_failures:
                        blocked_failures.append(terminal_failures[key])
                        continue
                    try:
                        scope = self._intent_scope(write)
                    except Exception as exc:  # noqa: BLE001 - malformed plans cannot reach a broker
                        terminal_failures[key] = self._failure_code(exc)
                        blocked_failures.append(terminal_failures[key])
                        continue
                    existing = unresolved_by_scope.get((write.parent_verb, scope))
                    if existing is not None:
                        blocked_failures.append("dispatch_uncertain")
                        continue
                    try:
                        current_router = self._router_provider()
                    except Exception as exc:  # noqa: BLE001 - provider failure is bounded
                        logger.error("Emergency write could not resolve current router (%s)", type(exc).__name__)
                        return (
                            self._target_result(
                                policy,
                                target,
                                succeeded=False,
                                failure_code="router_unavailable",
                                attempted=attempted,
                            ),
                            None,
                        )
                    if current_router is not router:
                        break
                    try:
                        canonical, safety_ctx = self._prepare_concrete_write(
                            target,
                            request_ctx,
                            write,
                            policy=policy,
                            reason_hash=reason_hash,
                        )
                    except SafetyBypassError as exc:
                        failure_code = self._failure_code(exc)
                        terminal_failures[key] = failure_code
                        blocked_failures.append(failure_code)
                        continue
                    try:
                        target_order_id = (
                            self._planned_cancel_target_id(write)
                            if write.verb.startswith("cancel_") and write.verb != "cancel_all_orders"
                            else ""
                        )
                        exit_tag = (
                            str(write.payload.get("emergency_tag") or "")
                            if write.parent_verb == "exit_all_positions"
                            else ""
                        )
                        intent_record, created = self._intent_journal.reserve(
                            source=journal_source,
                            selector=target.request_ctx.selector,
                            parent_verb=write.parent_verb,
                            verb=write.verb,
                            payload_hash=_canonical_order_hash(write.payload),
                            scope=scope,
                            target_order_id=target_order_id,
                            exit_tag=exit_tag,
                        )
                    except Exception as exc:  # noqa: BLE001 - reservation must commit before dispatch
                        logger.error("Emergency intent reservation failed (%s)", type(exc).__name__)
                        return (
                            self._target_result(
                                policy,
                                target,
                                succeeded=False,
                                failure_code="intent_journal_unavailable",
                                attempted=attempted,
                            ),
                            None,
                        )
                    unresolved_by_scope[(write.parent_verb, scope)] = intent_record
                    self._apply_intent_protections(
                        (intent_record,),
                        protected_order_ids=protected_order_ids,
                        protected_exit_order_ids=protected_exit_order_ids,
                        protected_exit_tags=protected_exit_tags,
                    )
                    if not created:
                        blocked_failures.append("dispatch_uncertain")
                        continue
                    adapter_invoked = False

                    def _mark_adapter_invoked() -> None:
                        nonlocal adapter_invoked, attempted, newly_attempted
                        if adapter_invoked:
                            return
                        adapter_invoked = True
                        attempted = True
                        newly_attempted += 1

                    try:
                        result = self._execute_concrete_write(
                            router,
                            target,
                            request_ctx,
                            write,
                            canonical=canonical,
                            safety_ctx=safety_ctx,
                            on_adapter_invoke=_mark_adapter_invoked,
                        )
                        # Custom EmergencyRouter implementations may not expose
                        # the callback, but a returned broker result still proves
                        # the dispatch crossed their invocation boundary.
                        _mark_adapter_invoked()
                        broker_failure = self._concrete_result_failure(write, result)
                        if broker_failure:
                            self._intent_journal.mark_unknown(intent_record.intent_id)
                            terminal_failures[key] = broker_failure
                            continue
                        result_order_ids: tuple[str, ...] = ()
                        if write.verb.startswith("cancel_") and write.verb != "cancel_all_orders":
                            protected_order_ids.add(self._planned_cancel_target_id(write))
                        elif write.parent_verb == "cancel_all_orders":
                            result_order_ids = self._result_order_ids(result)
                            protected_order_ids.update(result_order_ids)
                        elif write.verb == "place_reducing_order":
                            tag = str(write.payload.get("emergency_tag") or "")
                            if not tag:
                                raise SafetyBypassError("exact emergency exit has no settlement tag")
                            result_order_ids = self._result_order_ids(result)
                            if len(result_order_ids) != 1:
                                return (
                                    self._target_result(
                                        policy,
                                        target,
                                        succeeded=False,
                                        failure_code="invalid_broker_result",
                                        attempted=True,
                                    ),
                                    None,
                                )
                            protected_exit_tags.add(tag)
                            protected_exit_order_ids.update(result_order_ids)
                        elif write.verb == "exit_all_positions":
                            result_order_ids = self._result_order_ids(result)
                            complete_summary = isinstance(result, Mapping) and {
                                "errors",
                                "total",
                                "success",
                            }.issubset(result)
                            if not result_order_ids and not complete_summary:
                                return (
                                    self._target_result(
                                        policy,
                                        target,
                                        succeeded=False,
                                        failure_code="invalid_broker_result",
                                        attempted=True,
                                    ),
                                    None,
                                )
                            protected_exit_order_ids.update(result_order_ids)
                        self._intent_journal.acknowledge(intent_record.intent_id, result_order_ids)
                        successful_writes += 1
                    except Exception as exc:  # noqa: BLE001 - concrete write failure is bounded
                        failure_code = self._failure_code(exc)
                        logger.error(
                            "Emergency concrete verb %s failed closed: %s (%s)",
                            write.verb,
                            failure_code,
                            type(exc).__name__,
                        )
                        if adapter_invoked:
                            try:
                                self._intent_journal.mark_unknown(intent_record.intent_id)
                            except Exception as journal_exc:  # noqa: BLE001 - retaining reserved is fail-closed
                                logger.error(
                                    "Emergency intent unknown-state update failed (%s)",
                                    type(journal_exc).__name__,
                                )
                        else:
                            try:
                                self._intent_journal.release(intent_record.intent_id)
                            except Exception as journal_exc:  # noqa: BLE001 - retaining reserved is fail-closed
                                logger.error(
                                    "Emergency pre-dispatch intent release failed (%s)",
                                    type(journal_exc).__name__,
                                )
                            else:
                                unresolved_by_scope.pop((write.parent_verb, scope), None)
                                self._remove_intent_protections(
                                    intent_record,
                                    protected_order_ids=protected_order_ids,
                                    protected_exit_order_ids=protected_exit_order_ids,
                                    protected_exit_tags=protected_exit_tags,
                                )
                        terminal_failures[key] = failure_code
                        continue

                # A failed concrete write is read back once before it becomes a
                # terminal partial result: brokers can accept a cancellation and
                # still lose the response. If the next snapshot is quiet, the
                # authoritative state wins; if the same signed mutation remains
                # pending, do not replay it under another outer batch.
                if blocked_failures and newly_attempted == 0:
                    known_failures = tuple(terminal_failures.values())
                    failure_code = (
                        "partial_broker_result"
                        if successful_writes or "partial_broker_result" in known_failures
                        else blocked_failures[0]
                    )
                    return (
                        self._pending_target_result(
                            policy,
                            target,
                            pending_verbs=plan.pending_verbs,
                            failure_code=failure_code,
                            attempted=attempted,
                        ),
                        None,
                    )
            if attempt < self._planned_readback_attempts - 1 and self._planned_readback_delay_seconds:
                time.sleep(self._planned_readback_delay_seconds)

        return (
            self._target_result(
                policy,
                target,
                succeeded=False,
                failure_code=(
                    "partial_broker_result"
                    if successful_writes or terminal_failures
                    else "broker_state_not_quiet"
                ),
                attempted=attempted,
            ),
            None,
        )

    def dispatch_prepared(
        self,
        policy: EmergencyWritePolicy,
        *,
        reason: str,
        targets: tuple[EmergencyBrokerTarget, ...],
    ) -> EmergencyDispatchResult:
        """Dispatch a target snapshot already reserved by :class:`KillSwitch`."""
        if not targets or not all(isinstance(target, EmergencyBrokerTarget) for target in targets):
            raise SafetyBypassError("prepared emergency targets are invalid or empty")
        selectors = tuple(target.request_ctx.selector for target in targets)
        if len(set(selectors)) != len(selectors):
            raise SafetyBypassError("prepared emergency targets contain duplicate selectors")

        reason_hash = hashlib.sha256(str(reason).encode("utf-8")).hexdigest()
        self._bind_episode_targets(policy, selectors, reason_hash=reason_hash)
        outcomes: list[EmergencyVerbOutcome] = []
        for target in targets:
            request_ctx = self._emergency_request_context(target)
            planned, _legacy_router = self._dispatch_planned_target(
                policy,
                target,
                request_ctx,
                reason_hash=reason_hash,
            )
            assert planned is not None
            outcomes.extend(planned.outcomes)

        return EmergencyDispatchResult(policy=policy, outcomes=tuple(outcomes))


# ---------------------------------------------------------------------------
# SafetyGate — the one-shot gate_id consumer (contract §8.0a)
# ---------------------------------------------------------------------------


class SafetyGate:
    """Process-local one-shot consumer for ``SafetyContext.gate_id`` (contract §8.0a).

    A ``gate_id`` may be consumed exactly once; a second :meth:`consume` of the
    same id returns ``False`` so :class:`BrokerRouter` rejects the replay. The
    consumed marker is held for ``ttl_seconds`` (>= the SafetyContext 10 s TTL),
    then pruned — this bounds memory WITHOUT opening a replay hole, because a
    gate older than its TTL fails :meth:`SafetyContext.verify` (expiry) anyway.

    In-memory and thread-safe, which is sufficient for the single-process
    personal deployment FlintTrade targets. A future multi-process deployment
    would swap this for the spec's atomic SELECT-and-DELETE DB gate.
    """

    def __init__(self) -> None:
        self._consumed: dict[str, float] = {}  # gate_id -> marker-expiry epoch
        self._lock = threading.Lock()

    def consume(self, gate_id: str, ttl_seconds: float = 60.0) -> bool:
        """Consume ``gate_id`` once. Returns ``True`` the first time, ``False`` after.

        Args:
            gate_id: The :attr:`SafetyContext.gate_id` to consume.
            ttl_seconds: How long to remember the consumed id (>= the context TTL).

        Returns:
            ``True`` if this is the first consumption, ``False`` if already consumed
            (a replay).
        """
        now = time.time()
        with self._lock:
            # Opportunistic prune of expired markers (bounded memory).
            if len(self._consumed) > 256:
                self._consumed = {g: e for g, e in self._consumed.items() if e > now}
            existing = self._consumed.get(gate_id)
            if existing is not None and existing > now:
                return False
            self._consumed[gate_id] = now + ttl_seconds
            return True


# ---------------------------------------------------------------------------
# Result type shared by all layers
# ---------------------------------------------------------------------------


class SafetyVerdict(StrEnum):
    PASS = "PASS"
    FAIL = "FAIL"


@dataclass
class SafetyResult:
    """Result from a single safety layer check."""

    verdict: SafetyVerdict
    layer: str
    reason: str = ""

    @property
    def passed(self) -> bool:
        return self.verdict == SafetyVerdict.PASS


# ---------------------------------------------------------------------------
# Per-exchange market hours (IST)
# ---------------------------------------------------------------------------

MARKET_HOURS: dict[str, tuple[dt_time, dt_time]] = {
    "NSE": (dt_time(9, 15), dt_time(15, 30)),
    "BSE": (dt_time(9, 15), dt_time(15, 30)),
    "NFO": (dt_time(9, 15), dt_time(15, 30)),
    "BFO": (dt_time(9, 15), dt_time(15, 30)),
    "CDS": (dt_time(9, 0), dt_time(17, 0)),
    "BCD": (dt_time(9, 0), dt_time(17, 0)),
    "MCX": (dt_time(9, 0), dt_time(23, 30)),
    "NCDEX": (dt_time(10, 0), dt_time(17, 0)),
    "NCO": (dt_time(9, 0), dt_time(17, 0)),  # NSE Commodities — Zerodha-only on upstream
    "DELTA": (dt_time(0, 0), dt_time(23, 59)),  # 24/7 crypto
}

# Exchanges that are quote-only — orders always rejected.
# Index segments cannot be traded directly; they price the underlying baskets
# that NSE/BSE/MCX list as derivatives instruments. MCX_INDEX (commodity
# indices) and GLOBAL_INDEX (foreign + IFSC reference indices) are added
# alongside NSE_INDEX / BSE_INDEX in the OpenAlgo v2.0.1.0 sync.
_QUOTE_ONLY_EXCHANGES = {
    "NSE_INDEX",
    "BSE_INDEX",
    "MCX_INDEX",
    "GLOBAL_INDEX",
}

# Exchange routing: all exchanges route through OpenAlgo (including Delta Exchange).
OPENALGO_EXCHANGES = {
    "NSE",
    "BSE",
    "NFO",
    "BFO",
    "CDS",
    "BCD",
    "MCX",
    "NSE_INDEX",
    "BSE_INDEX",
    "NCDEX",
    "NCO",
    "MCX_INDEX",
    "GLOBAL_INDEX",
    "DELTA",
}


def is_market_open(exchange: str, at: datetime | None = None) -> bool:
    """Check if the given exchange is currently open for trading.

    - NSE_INDEX / BSE_INDEX: always False (quote-only, no orders)
    - DELTA: always True (24/7 crypto via ccxt, not OpenAlgo)
    - Unknown exchanges: False
    - Known exchanges: True only if current IST time is within market hours
    """
    if exchange in _QUOTE_ONLY_EXCHANGES:
        return False

    # Delta Exchange — 24/7 via native OpenAlgo broker integration
    if exchange == "DELTA":
        return True

    if exchange not in MARKET_HOURS:
        return False

    now = at or datetime.now(IST)
    current_time = now.time().replace(tzinfo=None)
    open_time, close_time = MARKET_HOURS[exchange]
    return open_time <= current_time < close_time


def get_expiry_time(exchange: str) -> dt_time:
    """Return the expiry/settlement time for the given exchange.

    Used for accurate Greeks/theta calculations.
    """
    expiry_times: dict[str, dt_time] = {
        "NFO": dt_time(15, 30),
        "BFO": dt_time(15, 30),
        "CDS": dt_time(12, 30),
        "BCD": dt_time(12, 30),
        "MCX": dt_time(23, 30),
        "NCO": dt_time(17, 0),
        "DELTA": dt_time(18, 0),  # BTC/ETH weekly options + daily futures: 12:30 UTC = 18:00 IST
    }
    return expiry_times.get(exchange, dt_time(15, 30))


def _format_market_hours(exchange: str) -> str:
    """Format market hours for error messages."""
    if exchange in MARKET_HOURS:
        o, c = MARKET_HOURS[exchange]
        return f"{o.strftime('%H:%M')}–{c.strftime('%H:%M')} IST"
    return "unknown"


# ---------------------------------------------------------------------------
# Layer 1 — Order Validation
# ---------------------------------------------------------------------------

# Valid exchanges that can receive orders (excludes index-only segments)
_TRADEABLE_EXCHANGES = {
    "NSE",
    "BSE",
    "NFO",
    "BFO",
    "MCX",
    "CDS",
    "BCD",
    "NCDEX",
    "NCO",
    "DELTA",
}

# Order validities accepted on the pass-through field (Order.validity). DAY/IOC
# everywhere it is supported; GTC/GTD (MCX) and EOS (BSE/MCX) are broker-side
# constraints enforced by the adapter mappings — L1 only rejects unknown codes.
_ALLOWED_VALIDITIES = frozenset({"DAY", "IOC", "GTC", "GTD", "EOS"})

# Per-exchange max single-order quantity defaults (can be overridden)
_DEFAULT_QTY_LIMITS: dict[str, int] = {
    "NSE": 50_000,
    "BSE": 50_000,
    "NFO": 5_000,
    "BFO": 5_000,
    "MCX": 1_000,
    "CDS": 10_000,
    "BCD": 10_000,
    "NCDEX": 5_000,
    "NCO": 5_000,
}


class OrderValidation:
    """Layer 1: Validates individual order fields before submission.

    Checks:
    - Exchange is tradeable (not NSE_INDEX/BSE_INDEX)
    - Market is open for the exchange (per-exchange hours)
    - Symbol is non-empty
    - Quantity is positive and within exchange limits
    - For LIMIT/SL orders, price is within 5% of LTP
    """

    def __init__(
        self,
        price_deviation_pct: float = 5.0,
        qty_limits: dict[str, int] | None = None,
        check_market_hours: bool = True,
    ) -> None:
        self.price_deviation_pct = price_deviation_pct
        self.qty_limits = qty_limits or dict(_DEFAULT_QTY_LIMITS)
        self.check_market_hours = check_market_hours

    def validate(self, order: Order, ltp: float | None = None, at: datetime | None = None) -> SafetyResult:
        exchange = order.exchange.value if hasattr(order.exchange, "value") else str(order.exchange)

        # Exchange check
        if exchange not in _TRADEABLE_EXCHANGES:
            return SafetyResult(SafetyVerdict.FAIL, "L1_ORDER", f"Exchange {exchange} is not tradeable")

        # Market hours check
        if self.check_market_hours and not is_market_open(exchange, at=at):
            now = at or datetime.now(IST)
            current_time = now.time().replace(tzinfo=None).strftime("%H:%M")
            hours = _format_market_hours(exchange)
            return SafetyResult(
                SafetyVerdict.FAIL,
                "L1_ORDER",
                f"{exchange} is open {hours}. Current time: {current_time}. Market closed.",
            )

        # Log Delta Exchange orders routed through native OpenAlgo broker
        if exchange == "DELTA":
            logger.info(
                "Order for DELTA exchange — routes via OpenAlgo Delta Exchange broker integration",
            )

        # Symbol check
        if not order.symbol or not order.symbol.strip():
            return SafetyResult(SafetyVerdict.FAIL, "L1_ORDER", "Symbol is empty")

        # Quantity check
        qty = int(order.quantity)
        if qty <= 0:
            return SafetyResult(SafetyVerdict.FAIL, "L1_ORDER", f"Quantity must be positive, got {qty}")

        max_qty = self.qty_limits.get(exchange, 50_000)
        if qty > max_qty:
            return SafetyResult(
                SafetyVerdict.FAIL,
                "L1_ORDER",
                f"Quantity {qty} exceeds {exchange} limit of {max_qty}",
            )

        # Advanced orders may carry a second executable OCO leg. It is covered
        # by the same SafetyContext, so its quantity must satisfy the same L1
        # limit before the composite order can be admitted.
        raw_quantity1 = getattr(order, "quantity1", None)
        if raw_quantity1 is not None:
            try:
                quantity1 = int(raw_quantity1)
            except (TypeError, ValueError):
                return SafetyResult(SafetyVerdict.FAIL, "L1_ORDER", "Second-leg quantity must be an integer")
            if quantity1 <= 0:
                return SafetyResult(
                    SafetyVerdict.FAIL,
                    "L1_ORDER",
                    f"Second-leg quantity must be positive, got {quantity1}",
                )
            if quantity1 > max_qty:
                return SafetyResult(
                    SafetyVerdict.FAIL,
                    "L1_ORDER",
                    f"Second-leg quantity {quantity1} exceeds {exchange} limit of {max_qty}",
                )

        # Validity pass-through check (optional field; None = adapter default).
        # The field is part of the SafetyContext-hashed order, so it is also
        # validated here before any gate is minted for it.
        validity = getattr(order, "validity", None)
        if validity is not None and str(validity).upper() not in _ALLOWED_VALIDITIES:
            return SafetyResult(
                SafetyVerdict.FAIL,
                "L1_ORDER",
                f"Validity {validity!r} is not one of {sorted(_ALLOWED_VALIDITIES)}",
            )

        # Price check for LIMIT / SL orders
        pricetype = order.pricetype.value if hasattr(order.pricetype, "value") else str(order.pricetype)
        if pricetype in ("LIMIT", "SL") and ltp is not None and ltp > 0:
            order_price = float(order.price)
            if order_price > 0:
                deviation = abs(order_price - ltp) / ltp * 100
                if deviation > self.price_deviation_pct:
                    return SafetyResult(
                        SafetyVerdict.FAIL,
                        "L1_ORDER",
                        f"Price {order_price} deviates {deviation:.1f}% from LTP {ltp} "
                        f"(max {self.price_deviation_pct}%)",
                    )

        return SafetyResult(SafetyVerdict.PASS, "L1_ORDER")


# ---------------------------------------------------------------------------
# Layer 2 — Position Limits
# ---------------------------------------------------------------------------


class PositionLimits:
    """Layer 2: Enforces portfolio-level position and margin constraints.

    Checks:
    - Max simultaneous open positions (default 5)
    - Max margin usage percentage (default 60%)
    """

    def __init__(
        self,
        max_positions: int = 5,
        max_margin_pct: float = 60.0,
    ) -> None:
        self.max_positions = max_positions
        self.max_margin_pct = max_margin_pct

    @staticmethod
    def _qty(value: object) -> int:
        """Tolerant quantity parse — brokers return "0", "10", or even "10.0".

        Catches OverflowError too: ``int(float("inf"))`` raises it (an
        ArithmeticError, NOT a ValueError), and an uncaught OverflowError here
        would 500 a live order on a pathologically malformed broker quantity.
        """
        try:
            return int(float(str(value)))
        except (TypeError, ValueError, OverflowError):
            return 0

    @staticmethod
    def _normalise(value: object) -> str:
        raw = value.value if hasattr(value, "value") else value
        return str(raw or "").strip().upper()

    @classmethod
    def _is_strict_reduction(cls, order: Order | None, positions: list[Position]) -> bool:
        """Return whether an order can only move one exact position toward zero."""
        if order is None:
            return False
        order_qty = cls._qty(order.quantity)
        if order_qty <= 0:
            return False
        order_key = (
            cls._normalise(order.symbol),
            cls._normalise(order.exchange),
            cls._normalise(order.product),
        )
        if not all(order_key):
            return False
        net_quantity = sum(
            cls._qty(position.quantity)
            for position in positions
            if (
                cls._normalise(position.symbol),
                cls._normalise(position.exchange),
                cls._normalise(position.product),
            )
            == order_key
        )
        action = cls._normalise(order.action)
        if net_quantity > 0:
            return action == "SELL" and order_qty <= net_quantity
        if net_quantity < 0:
            return action == "BUY" and order_qty <= abs(net_quantity)
        return False

    def validate(
        self,
        current_positions: list[Position],
        used_margin: float,
        total_balance: float,
        *,
        order: Order | None = None,
    ) -> SafetyResult:
        # Count positions with non-zero quantity
        active = [p for p in current_positions if self._qty(p.quantity) != 0]
        strict_reduction = self._is_strict_reduction(order, active)
        if len(active) >= self.max_positions:
            if strict_reduction:
                return SafetyResult(SafetyVerdict.PASS, "L2_POSITION")
            return SafetyResult(
                SafetyVerdict.FAIL,
                "L2_POSITION",
                f"Already at max positions ({len(active)}/{self.max_positions})",
            )

        # Margin usage check
        if total_balance > 0:
            margin_pct = (used_margin / total_balance) * 100
            if margin_pct >= self.max_margin_pct:
                if strict_reduction:
                    return SafetyResult(SafetyVerdict.PASS, "L2_POSITION")
                return SafetyResult(
                    SafetyVerdict.FAIL,
                    "L2_POSITION",
                    f"Margin usage {margin_pct:.1f}% exceeds limit of {self.max_margin_pct}%",
                )

        return SafetyResult(SafetyVerdict.PASS, "L2_POSITION")


# ---------------------------------------------------------------------------
# Layer 3 — Portfolio Risk (Options Greeks)
# ---------------------------------------------------------------------------


class PortfolioRisk:
    """Layer 3: Net Greeks limits for options portfolios.

    Checks:
    - Absolute net delta doesn't exceed limit
    - Absolute net vega doesn't exceed limit
    """

    def __init__(
        self,
        max_net_delta: float = 500.0,
        max_net_vega: float = 10_000.0,
    ) -> None:
        self.max_net_delta = max_net_delta
        self.max_net_vega = max_net_vega

    def validate(
        self,
        net_delta: float,
        net_vega: float,
    ) -> SafetyResult:
        if abs(net_delta) > self.max_net_delta:
            return SafetyResult(
                SafetyVerdict.FAIL,
                "L3_PORTFOLIO",
                f"Net delta {net_delta:.1f} exceeds limit of ±{self.max_net_delta}",
            )

        if abs(net_vega) > self.max_net_vega:
            return SafetyResult(
                SafetyVerdict.FAIL,
                "L3_PORTFOLIO",
                f"Net vega {net_vega:.1f} exceeds limit of ±{self.max_net_vega}",
            )

        return SafetyResult(SafetyVerdict.PASS, "L3_PORTFOLIO")


# ---------------------------------------------------------------------------
# Layer 4 — Daily P&L Limits
# ---------------------------------------------------------------------------


class DailyPnLLimits:
    """Layer 4: Daily P&L circuit breakers.

    - Pause trigger: 3% loss blocks subsequent new orders (reversible).
    - Hard stop: 15% loss blocks subsequent new orders until manual reset.

    Layer 4 never cancels orders or flattens positions. Those broker actions
    belong exclusively to the explicit Layer 5 kill switch.
    """

    def __init__(
        self,
        pause_pct: float = 3.0,
        kill_pct: float = 15.0,
    ) -> None:
        self.pause_pct = pause_pct
        self.kill_pct = kill_pct
        self._state_store: DailyPnLStateStoreProtocol = InMemoryDailyPnLStateStore()
        self._persistence_faults: set[tuple[str, str]] = set()
        self._persistence_fault_lock = threading.RLock()

    @staticmethod
    def session_key(at: datetime | None = None) -> str:
        """Return the IST trading-session date used for frozen Layer 4 state."""
        value = at or datetime.now(IST)
        if value.tzinfo is None:
            value = value.replace(tzinfo=IST)
        return value.astimezone(IST).date().isoformat()

    def bind_state_store(self, store: DailyPnLStateStoreProtocol) -> None:
        """Bind the production durable store before live routing is published."""
        self._state_store = store

    def state(self, selector: str, *, at: datetime | None = None) -> DailyPnLState | None:
        """Return one selector's current-session state, if capital is configured."""
        return self._state_store.get(selector=selector, session_key=self.session_key(at))

    def states(self, *, at: datetime | None = None) -> tuple[DailyPnLState, ...]:
        """Return all selector states for the current session."""
        return self._state_store.list_session(session_key=self.session_key(at))

    @property
    def is_paused(self) -> bool:
        return any(state.paused for state in self.states())

    @property
    def is_killed(self) -> bool:
        return any(state.killed for state in self.states())

    def configure_opening_capital(
        self,
        selector: str,
        opening_risk_capital: float,
        *,
        at: datetime | None = None,
    ) -> DailyPnLState:
        """Freeze an operator-supplied capital baseline for this session."""
        return self._state_store.configure(
            selector=selector,
            session_key=self.session_key(at),
            opening_risk_capital=opening_risk_capital,
        )

    def reset(self, selector: str, *, at: datetime | None = None) -> DailyPnLState:
        """Manually clear one selector's pause and hard-stop latches."""
        session_key = self.session_key(at)
        with self._persistence_fault_lock:
            state = self._state_store.reset(selector=selector, session_key=session_key)
            self._persistence_faults.discard((selector, session_key))
        logger.warning("Daily P&L latches reset for %s — manual override", selector)
        return state

    def reset_pause(self, selector: str = "test:default") -> None:
        """Compatibility wrapper that clears both account-scoped L4 latches."""
        self.reset(selector)

    def reset_kill(self, selector: str = "test:default") -> None:
        """Compatibility wrapper that clears both account-scoped L4 latches."""
        self.reset(selector)

    def validate(
        self,
        daily_pnl: float,
        starting_capital: float,
        *,
        selector: str,
        at: datetime | None = None,
    ) -> SafetyResult:
        """Validate one selector atomically against its current-session L4 state."""
        with self._persistence_fault_lock:
            return self._validate_locked(
                daily_pnl,
                starting_capital,
                selector=selector,
                at=at,
            )

    def _validate_locked(
        self,
        daily_pnl: float,
        starting_capital: float,
        *,
        selector: str,
        at: datetime | None = None,
    ) -> SafetyResult:
        session_key = self.session_key(at)
        try:
            current_pnl = float(daily_pnl)
        except (TypeError, ValueError):
            current_pnl = math.nan
        if not math.isfinite(current_pnl):
            return SafetyResult(
                SafetyVerdict.FAIL,
                "L4_PNL",
                "Current daily P&L is unavailable",
            )
        fault_key = (selector, session_key)
        with self._persistence_fault_lock:
            persistence_faulted = fault_key in self._persistence_faults
        if persistence_faulted:
            return SafetyResult(
                SafetyVerdict.FAIL,
                "L4_PNL",
                "Durable daily-loss latch is unavailable — manual reset required",
            )
        try:
            state = self._state_store.resolve(
                selector=selector,
                session_key=session_key,
                observed_opening_capital=starting_capital,
            )
        except (DailyPnLStateError, OSError, sqlite3.Error, ValueError):
            logger.exception("Daily P&L state unavailable for %s", selector)
            return SafetyResult(
                SafetyVerdict.FAIL,
                "L4_PNL",
                "Opening risk capital or durable daily-loss state is unavailable",
            )

        if state.killed:
            return SafetyResult(
                SafetyVerdict.FAIL,
                "L4_PNL",
                "Daily-loss hard stop active — manual reset required",
            )

        if state.paused:
            return SafetyResult(
                SafetyVerdict.FAIL,
                "L4_PNL",
                "Trading paused due to daily P&L limit — manual reset required",
            )

        loss_pct = (-current_pnl / state.opening_risk_capital) * 100 if current_pnl < 0 else 0.0

        if loss_pct >= self.kill_pct:
            try:
                self._state_store.latch(
                    selector=selector,
                    session_key=session_key,
                    killed=True,
                )
            except Exception:  # noqa: BLE001 - admission still fails closed
                with self._persistence_fault_lock:
                    self._persistence_faults.add(fault_key)
                logger.exception("Daily P&L hard stop could not be persisted for %s", selector)
            logger.critical(
                "DAILY-LOSS HARD STOP triggered for %s: daily loss %.1f%% exceeds %.1f%%",
                selector,
                loss_pct,
                self.kill_pct,
            )
            return SafetyResult(
                SafetyVerdict.FAIL,
                "L4_PNL",
                f"Hard stop triggered: daily loss {loss_pct:.1f}% exceeds {self.kill_pct}%",
            )

        if loss_pct >= self.pause_pct:
            try:
                self._state_store.latch(
                    selector=selector,
                    session_key=session_key,
                    paused=True,
                )
            except Exception:  # noqa: BLE001 - admission still fails closed
                with self._persistence_fault_lock:
                    self._persistence_faults.add(fault_key)
                logger.exception("Daily P&L pause could not be persisted for %s", selector)
            logger.warning(
                "PAUSE triggered for %s: daily loss %.1f%% exceeds %.1f%%",
                selector,
                loss_pct,
                self.pause_pct,
            )
            return SafetyResult(
                SafetyVerdict.FAIL,
                "L4_PNL",
                f"Pause triggered: daily loss {loss_pct:.1f}% exceeds {self.pause_pct}%",
            )

        return SafetyResult(SafetyVerdict.PASS, "L4_PNL")


# ---------------------------------------------------------------------------
# Layer 5 — Kill Switch
# ---------------------------------------------------------------------------


class KillSwitchResetAuthorisationError(SafetyBypassError):
    """Raised when a reset principal cannot manage every affected selector."""


class KillSwitch:
    """Layer 5: Emergency kill — cancel all orders + close all positions.

    Once activated, blocks ALL orders until manually reset. Broker actions use
    only an injected :class:`EmergencyDispatcher`; a missing dispatcher latches
    L5 and reports failure without falling back to a raw client.
    """

    def __init__(
        self,
        emergency_dispatcher: EmergencyDispatcher | None = None,
        *,
        normal_write_drain_timeout: float = 15.0,
    ) -> None:
        if normal_write_drain_timeout < 0:
            raise ValueError("normal_write_drain_timeout must be non-negative")
        self._active = False
        self._reason: str = ""
        self._emergency_dispatcher = emergency_dispatcher
        self._emergency_journal: EmergencyIntentJournalProtocol | None = None
        self._last_emergency_result: EmergencyDispatchResult | None = None
        self._emergency_outcomes: dict[tuple[str, str], tuple[int, EmergencyVerbOutcome]] = {}
        self._activation_sequence = 0
        self._latest_full_scope_sequence = 0
        self._dispatches_in_progress = 0
        self._selectors_in_progress: set[str] = set()
        self._normal_writes_in_progress = 0
        self._normal_write_drain_timeout = float(normal_write_drain_timeout)
        self._condition = threading.Condition()

    @property
    def is_active(self) -> bool:
        with self._condition:
            return self._active

    @property
    def reason(self) -> str:
        with self._condition:
            return self._reason

    @property
    def last_emergency_result(self) -> EmergencyDispatchResult | None:
        """Most recent bounded L5 broker-action result, if activation ran."""
        with self._condition:
            if self._dispatches_in_progress:
                return EmergencyDispatchResult.failed(
                    L5_EMERGENCY_POLICY,
                    "dispatch_in_progress",
                )
            return self._last_emergency_result

    @contextmanager
    def broker_write_admission(self, emergency_reduction: bool, selector: str = "") -> Iterator[None]:
        """Atomically admit a normal write or a signed emergency reduction.

        A normal write admitted before activation is counted until its adapter
        call returns. Activation latches L5 under the same condition and drains
        those leases before sweeping. A normal write arriving after the latch is
        rejected at the router boundary even if its SafetyContext was minted
        earlier. Only the router-verified emergency intent may bypass this
        counter; an ordinary cancellation might remove a protective exit.
        """
        if emergency_reduction:
            yield
            return
        with self._condition:
            journal = self._emergency_journal
            if journal is not None:
                try:
                    durable_sources = journal.blocking_sources(selector)
                except Exception as exc:
                    raise SafetyBypassError("emergency journal unavailable; broker write refused") from exc
                if "l5" in durable_sources:
                    self._active = True
                    if not self._reason:
                        self._reason = "restored durable emergency episode"
            if self._active:
                raise SafetyBypassError("kill switch is active; broker write refused")
            self._normal_writes_in_progress += 1
        try:
            yield
        finally:
            with self._condition:
                self._normal_writes_in_progress -= 1
                if self._normal_writes_in_progress == 0:
                    self._condition.notify_all()

    def bind_emergency_dispatcher(self, dispatcher: EmergencyDispatcher | None) -> None:
        """Bind the parent-owned gated dispatcher used by later activations."""
        with self._condition:
            self._emergency_dispatcher = dispatcher

    def bind_emergency_journal(self, journal: EmergencyIntentJournalProtocol | None) -> None:
        """Restore a durable L5 latch before the router admits live writes."""
        episodes = () if journal is None else journal.active_episodes("l5")
        with self._condition:
            self._emergency_journal = journal
            if episodes:
                self._active = True
                if not self._reason:
                    self._reason = "restored durable emergency episode"

    def _selector_complete_locked(self, selector: str) -> bool:
        return all(
            (entry := self._emergency_outcomes.get((selector, verb))) is not None and entry[1].succeeded
            for verb in L5_EMERGENCY_POLICY.verbs
        )

    def _result_for_selectors_locked(
        self,
        selectors: tuple[str, ...],
    ) -> EmergencyDispatchResult:
        return EmergencyDispatchResult(
            policy=L5_EMERGENCY_POLICY,
            outcomes=tuple(
                self._emergency_outcomes[(selector, verb)][1]
                for selector in selectors
                for verb in L5_EMERGENCY_POLICY.verbs
            ),
        )

    @staticmethod
    def _failed_for_targets(
        targets: tuple[EmergencyBrokerTarget, ...],
        failure_code: str,
        *,
        attempted: bool = False,
    ) -> EmergencyDispatchResult:
        return EmergencyDispatchResult(
            policy=L5_EMERGENCY_POLICY,
            outcomes=tuple(
                EmergencyVerbOutcome(
                    verb,
                    succeeded=False,
                    attempted=attempted,
                    failure_code=failure_code,
                    selector=target.request_ctx.selector,
                )
                for target in targets
                for verb in L5_EMERGENCY_POLICY.verbs
            ),
        )

    def _dispatch_coordinated(
        self,
        dispatcher: EmergencyDispatcher,
        reason: str,
        *,
        owned_selectors: set[str] | None = None,
        prepared_targets: tuple[EmergencyBrokerTarget, ...] | None = None,
    ) -> tuple[EmergencyDispatchResult, set[str], set[str] | None]:
        """Dispatch under the parent's immutable routing-generation lease."""
        owned_selectors = set() if owned_selectors is None else owned_selectors
        if prepared_targets is not None:
            return self._dispatch_coordinated_under_lease(
                dispatcher,
                reason,
                owned_selectors=owned_selectors,
                prepared_targets=prepared_targets,
            )
        lease_method = getattr(type(dispatcher), "generation_lease", None)
        lease = dispatcher.generation_lease if callable(lease_method) else None
        try:
            with lease() if callable(lease) else nullcontext():
                return self._dispatch_coordinated_under_lease(
                    dispatcher,
                    reason,
                    owned_selectors=owned_selectors,
                )
        except GenerationLeaseUnavailableError as exc:
            logger.error("Emergency routing generation lease failed closed (%s)", type(exc).__name__)
            return (
                EmergencyDispatchResult.failed(
                    L5_EMERGENCY_POLICY,
                    "generation_lease_unavailable",
                ),
                owned_selectors,
                None,
            )

    def _dispatch_coordinated_under_lease(
        self,
        dispatcher: EmergencyDispatcher,
        reason: str,
        *,
        owned_selectors: set[str] | None = None,
        prepared_targets: tuple[EmergencyBrokerTarget, ...] | None = None,
    ) -> tuple[EmergencyDispatchResult, set[str], set[str] | None]:
        """Prepare, reserve, dispatch, and assemble while one generation is leased."""
        owned_selectors = set() if owned_selectors is None else owned_selectors
        prepare_method = getattr(type(dispatcher), "prepare_targets", None)
        dispatch_prepared_method = getattr(type(dispatcher), "dispatch_prepared", None)
        if prepared_targets is None and (not callable(prepare_method) or not callable(dispatch_prepared_method)):
            return dispatcher.dispatch(L5_EMERGENCY_POLICY, reason=reason), owned_selectors, None
        if prepared_targets is not None and not callable(dispatch_prepared_method):
            raise SafetyBypassError("prepared emergency authority requires dispatch_prepared support")
        prepare = getattr(dispatcher, "prepare_targets", None)
        dispatch_prepared = dispatcher.dispatch_prepared

        if prepared_targets is None:
            try:
                prepared = tuple(prepare())
            except Exception as exc:  # noqa: BLE001 - target lookup remains bounded
                logger.error("Emergency target preparation failed closed (%s)", type(exc).__name__)
                return (
                    EmergencyDispatchResult.failed(
                        L5_EMERGENCY_POLICY,
                        "target_unavailable",
                    ),
                    owned_selectors,
                    None,
                )
        else:
            prepared = tuple(prepared_targets)
        if not prepared or not all(isinstance(target, EmergencyBrokerTarget) for target in prepared):
            return (
                EmergencyDispatchResult.failed(
                    L5_EMERGENCY_POLICY,
                    "target_unavailable",
                ),
                owned_selectors,
                None,
            )
        prepared_selectors = tuple(target.request_ctx.selector for target in prepared)
        if len(set(prepared_selectors)) != len(prepared_selectors):
            return (
                EmergencyDispatchResult.failed(
                    L5_EMERGENCY_POLICY,
                    "target_unavailable",
                ),
                owned_selectors,
                None,
            )

        deadline = time.monotonic() + self._normal_write_drain_timeout
        pending = list(prepared)
        waited_selectors: set[str] = set()
        authoritative_selectors: set[str] = set()
        outcomes_by_selector: dict[str, tuple[EmergencyVerbOutcome, ...]] = {}

        while pending:
            targets: tuple[EmergencyBrokerTarget, ...] = ()
            with self._condition:
                still_waiting: list[EmergencyBrokerTarget] = []
                free_targets: list[EmergencyBrokerTarget] = []
                for target in pending:
                    selector = target.request_ctx.selector
                    if selector in self._selectors_in_progress:
                        waited_selectors.add(selector)
                        still_waiting.append(target)
                    elif selector in waited_selectors and self._selector_complete_locked(selector):
                        outcomes_by_selector[selector] = tuple(
                            self._emergency_outcomes[(selector, verb)][1] for verb in L5_EMERGENCY_POLICY.verbs
                        )
                    else:
                        free_targets.append(target)

                if free_targets:
                    targets = tuple(free_targets)
                    newly_owned = {target.request_ctx.selector for target in targets}
                    self._selectors_in_progress.update(newly_owned)
                    owned_selectors.update(newly_owned)
                    authoritative_selectors.update(newly_owned)
                    pending = still_waiting
                elif still_waiting:
                    remaining = deadline - time.monotonic()
                    if remaining <= 0:
                        timeout_result = self._failed_for_targets(
                            tuple(still_waiting),
                            "dispatch_in_progress_timeout",
                        )
                        for target in still_waiting:
                            selector = target.request_ctx.selector
                            outcomes_by_selector[selector] = tuple(
                                outcome for outcome in timeout_result.outcomes if outcome.selector == selector
                            )
                        pending = []
                    else:
                        pending = still_waiting
                        self._condition.wait(timeout=remaining)
                    continue
                else:
                    pending = []
                    continue

            try:
                batch_result = dispatch_prepared(
                    L5_EMERGENCY_POLICY,
                    reason=reason,
                    targets=targets,
                )
                if not isinstance(batch_result, EmergencyDispatchResult):
                    raise TypeError("emergency dispatcher returned an invalid result")
                if batch_result.policy != L5_EMERGENCY_POLICY:
                    raise TypeError("emergency dispatcher returned the wrong write policy")
            except Exception as exc:  # noqa: BLE001 - reservation remains owned through merge
                logger.error(
                    "Emergency target dispatch failed closed (%s)",
                    type(exc).__name__,
                )
                batch_result = self._failed_for_targets(
                    targets,
                    "dispatch_failed",
                    attempted=True,
                )

            for target in targets:
                selector = target.request_ctx.selector
                selector_outcomes = tuple(outcome for outcome in batch_result.outcomes if outcome.selector == selector)
                if tuple(outcome.verb for outcome in selector_outcomes) != L5_EMERGENCY_POLICY.verbs:
                    selector_outcomes = self._failed_for_targets(
                        (target,),
                        "invalid_dispatch_result",
                        attempted=True,
                    ).outcomes
                outcomes_by_selector[selector] = selector_outcomes

        result = EmergencyDispatchResult(
            policy=L5_EMERGENCY_POLICY,
            outcomes=tuple(
                outcome for target in prepared for outcome in outcomes_by_selector[target.request_ctx.selector]
            ),
        )
        return result, owned_selectors, authoritative_selectors

    def _aggregate_locked(self) -> EmergencyDispatchResult | None:
        grouped: dict[str, dict[str, EmergencyVerbOutcome]] = {}
        for _sequence, outcome in self._emergency_outcomes.values():
            grouped.setdefault(outcome.selector, {})[outcome.verb] = outcome
        if not grouped:
            return None
        return EmergencyDispatchResult(
            policy=L5_EMERGENCY_POLICY,
            outcomes=tuple(outcomes[verb] for outcomes in grouped.values() for verb in L5_EMERGENCY_POLICY.verbs),
        )

    def activate(
        self,
        reason: str,
        *,
        emergency_dispatcher: EmergencyDispatcher | None = None,
        replace_scope: bool = False,
        prepared_targets: tuple[EmergencyBrokerTarget, ...] | None = None,
    ) -> EmergencyDispatchResult:
        """Latch L5, then synchronously run its explicit reducing-write policy.

        Disjoint selectors may execute independently. Overlapping selector sets
        are reserved atomically, so a concurrent activation joins a successful
        in-flight flatten instead of submitting a second square-off.
        """
        with self._condition:
            self._active = True
            self._reason = str(reason)
            self._dispatches_in_progress += 1
            self._activation_sequence += 1
            activation_sequence = self._activation_sequence
            if replace_scope:
                self._latest_full_scope_sequence = activation_sequence
            journal = self._emergency_journal
            dispatcher = emergency_dispatcher if emergency_dispatcher is not None else self._emergency_dispatcher
            journal_ready = True
            if journal is not None:
                reason_hash = hashlib.sha256(str(reason).encode("utf-8")).hexdigest()
                try:
                    journal.activate_episode(
                        source="l5",
                        selector="*",
                        session_key="manual",
                        reason_hash=reason_hash,
                    )
                except Exception as exc:  # noqa: BLE001 - the local latch remains active
                    # A dead durable store must not veto an already-latched
                    # flatten: fall back to the dispatcher's process-local
                    # intent journal so the reducing writes can still reserve
                    # and dispatch. Durable reset authority is untouched.
                    ensure = getattr(dispatcher, "ensure_degraded_episode", None)
                    journal_ready = callable(ensure) and bool(
                        ensure(
                            source="l5",
                            selector="*",
                            session_key="manual",
                            reason_hash=reason_hash,
                        )
                    )
                    if journal_ready:
                        logger.critical(
                            "Kill switch durable episode failed (%s); continuing on the "
                            "dispatcher's process-local intent journal",
                            type(exc).__name__,
                        )
                    else:
                        logger.error("Kill switch durable episode failed closed (%s)", type(exc).__name__)
            deadline = time.monotonic() + self._normal_write_drain_timeout
            normal_writes_drained = True
            while self._normal_writes_in_progress:
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    normal_writes_drained = False
                    break
                self._condition.wait(timeout=remaining)

        logger.critical("KILL SWITCH ACTIVATED: %s", reason)
        owned_selectors: set[str] = set()
        authoritative_selectors: set[str] | None = None
        try:
            if not journal_ready:
                result = EmergencyDispatchResult.failed(
                    L5_EMERGENCY_POLICY,
                    "intent_journal_unavailable",
                )
            elif not normal_writes_drained:
                logger.error("Kill switch broker actions deferred: admitted normal writes did not drain")
                result = EmergencyDispatchResult.failed(
                    L5_EMERGENCY_POLICY,
                    "normal_write_drain_timeout",
                )
            elif dispatcher is None:
                logger.error("Kill switch broker actions failed closed: emergency dispatcher unavailable")
                result = EmergencyDispatchResult.failed(
                    L5_EMERGENCY_POLICY,
                    "dispatcher_unavailable",
                )
            else:
                candidate, owned_selectors, authoritative_selectors = self._dispatch_coordinated(
                    dispatcher,
                    str(reason),
                    owned_selectors=owned_selectors,
                    prepared_targets=prepared_targets,
                )
                if not isinstance(candidate, EmergencyDispatchResult):
                    raise TypeError("emergency dispatcher returned an invalid result")
                if candidate.policy != L5_EMERGENCY_POLICY:
                    raise TypeError("emergency dispatcher returned the wrong write policy")
                result = candidate
        except Exception as exc:  # noqa: BLE001 - L5 remains latched on parent failure
            logger.error(
                "Kill switch broker actions failed closed: dispatch_failed (%s)",
                type(exc).__name__,
            )
            if owned_selectors:
                result = EmergencyDispatchResult(
                    policy=L5_EMERGENCY_POLICY,
                    outcomes=tuple(
                        EmergencyVerbOutcome(
                            verb,
                            succeeded=False,
                            attempted=True,
                            failure_code="dispatch_failed",
                            selector=selector,
                        )
                        for selector in sorted(owned_selectors)
                        for verb in L5_EMERGENCY_POLICY.verbs
                    ),
                )
                authoritative_selectors = set(owned_selectors)
            else:
                result = EmergencyDispatchResult.failed(
                    L5_EMERGENCY_POLICY,
                    "dispatch_failed",
                    attempted=True,
                )
        finally:
            with self._condition:
                target_bound = any(outcome.selector for outcome in result.outcomes)
                if replace_scope and target_bound:
                    for key, (sequence, _outcome) in tuple(self._emergency_outcomes.items()):
                        if not key[0] and sequence <= activation_sequence:
                            del self._emergency_outcomes[key]
                for outcome in result.outcomes:
                    if authoritative_selectors is not None and outcome.selector not in authoritative_selectors:
                        continue
                    if not outcome.selector and activation_sequence < self._latest_full_scope_sequence:
                        continue
                    key = (outcome.selector, outcome.verb)
                    current = self._emergency_outcomes.get(key)
                    if current is None or activation_sequence >= current[0]:
                        self._emergency_outcomes[key] = (activation_sequence, outcome)

                aggregate = self._aggregate_locked() or result
                self._last_emergency_result = aggregate
                self._selectors_in_progress.difference_update(owned_selectors)
                self._dispatches_in_progress -= 1
                self._condition.notify_all()
        return aggregate

    def wait_for_idle(self, timeout: float | None = None) -> None:
        """Wait until admitted normal and emergency writes reach a final state.

        This wait deliberately owns only the kill-switch condition. Callers that
        also need a routing-generation lease must wait here first, acquire that
        outer lease, then call :meth:`reset` with ``timeout=0`` for an atomic
        recheck and transition.
        """
        wait_timeout = self._normal_write_drain_timeout if timeout is None else float(timeout)
        if wait_timeout < 0:
            raise ValueError("idle wait timeout must be non-negative")
        deadline = time.monotonic() + wait_timeout
        with self._condition:
            while self._dispatches_in_progress or self._normal_writes_in_progress:
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    raise SafetyBypassError(
                        "emergency broker work is still in progress; kill switch remains active"
                    )
                self._condition.wait(timeout=remaining)

    def reset(
        self,
        *,
        require_complete: bool = False,
        timeout: float | None = None,
        authorise_selectors: Callable[[frozenset[str]], bool] | None = None,
    ) -> None:
        """Manually deactivate L5 after all admitted work reaches a final state.

        Callers that need an external routing-generation lease must call
        :meth:`wait_for_idle` before acquiring it, then use ``timeout=0`` here.
        Authorisation callbacks run while the internal condition is held and
        therefore must not acquire outer locks.
        """
        wait_timeout = self._normal_write_drain_timeout if timeout is None else float(timeout)
        if wait_timeout < 0:
            raise ValueError("reset timeout must be non-negative")
        deadline = time.monotonic() + wait_timeout
        with self._condition:
            while self._dispatches_in_progress or self._normal_writes_in_progress:
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    raise SafetyBypassError("emergency broker work is still in progress; kill switch remains active")
                self._condition.wait(timeout=remaining)
            if (
                require_complete
                and self._active
                and (self._last_emergency_result is None or not self._last_emergency_result.complete)
            ):
                raise SafetyBypassError("emergency broker actions are incomplete; kill switch remains active")
            episode = None
            if self._emergency_journal is not None:
                try:
                    episode = self._emergency_journal.active_episode(source="l5", selector="*")
                except Exception as exc:
                    raise SafetyBypassError(
                        "emergency journal unavailable; kill switch remains active"
                    ) from exc
                if self._active and episode is None:
                    raise SafetyBypassError("durable kill-switch episode is missing; kill switch remains active")
            if authorise_selectors is not None:
                selectors = frozenset(
                    {
                        *(selector for selector, _verb in self._emergency_outcomes if selector),
                        *(episode.affected_selectors if episode is not None else ()),
                    }
                )
                try:
                    authorised = bool(authorise_selectors(selectors))
                except Exception as exc:
                    raise KillSwitchResetAuthorisationError(
                        "kill-switch reset authorisation could not be verified"
                    ) from exc
                if not authorised:
                    raise KillSwitchResetAuthorisationError(
                        "kill-switch reset is not authorised for every affected account"
                    )
            if self._emergency_journal is not None and episode is not None:
                try:
                    self._emergency_journal.deactivate_episode(expected=episode)
                except SafetyBypassError:
                    raise
                except Exception as exc:
                    raise SafetyBypassError(
                        "emergency journal unavailable; kill switch remains active"
                    ) from exc
            self._active = False
            self._reason = ""
            self._emergency_outcomes.clear()
        logger.warning("Kill switch deactivated — manual override by operator")

    def validate(self) -> SafetyResult:
        with self._condition:
            active = self._active
            reason = self._reason
        if active:
            return SafetyResult(
                SafetyVerdict.FAIL,
                "L5_KILL",
                f"Kill switch active: {reason}",
            )
        return SafetyResult(SafetyVerdict.PASS, "L5_KILL")


# ---------------------------------------------------------------------------
# Composite SafetySystem
# ---------------------------------------------------------------------------


@dataclass
class SafetyConfig:
    """Tuneable parameters for the safety system."""

    price_deviation_pct: float = 5.0
    qty_limits: dict[str, int] = field(default_factory=lambda: dict(_DEFAULT_QTY_LIMITS))
    max_positions: int = 5
    max_margin_pct: float = 60.0
    max_net_delta: float = 500.0
    max_net_vega: float = 10_000.0
    pnl_pause_pct: float = 3.0
    pnl_kill_pct: float = 15.0
    check_market_hours: bool = True

    def __post_init__(self) -> None:
        def finite_number(name: str, value: Any, *, minimum: float, maximum: float | None = None) -> float:
            if isinstance(value, bool) or not isinstance(value, (int, float)):
                raise ValueError(f"{name} must be numeric")
            parsed = float(value)
            if not math.isfinite(parsed) or parsed < minimum or (maximum is not None and parsed > maximum):
                raise ValueError(f"{name} is outside its permitted range")
            return parsed

        self.price_deviation_pct = finite_number(
            "price_deviation_pct",
            self.price_deviation_pct,
            minimum=0.0,
            maximum=100.0,
        )
        if isinstance(self.max_positions, bool) or not isinstance(self.max_positions, int):
            raise ValueError("max_positions must be an integer")
        if self.max_positions < 0:
            raise ValueError("max_positions cannot be negative")
        self.max_margin_pct = finite_number(
            "max_margin_pct",
            self.max_margin_pct,
            minimum=0.0,
            maximum=100.0,
        )
        self.max_net_delta = finite_number("max_net_delta", self.max_net_delta, minimum=0.0)
        self.max_net_vega = finite_number("max_net_vega", self.max_net_vega, minimum=0.0)
        self.pnl_pause_pct = finite_number("pnl_pause_pct", self.pnl_pause_pct, minimum=0.0)
        self.pnl_kill_pct = finite_number("pnl_kill_pct", self.pnl_kill_pct, minimum=0.0)
        if self.pnl_pause_pct <= 0 or self.pnl_kill_pct <= self.pnl_pause_pct:
            raise ValueError("pnl_kill_pct must be greater than the positive pnl_pause_pct")
        if not isinstance(self.check_market_hours, bool):
            raise ValueError("check_market_hours must be a boolean")
        if not isinstance(self.qty_limits, Mapping) or not self.qty_limits:
            raise ValueError("qty_limits must be a non-empty mapping")
        normalised_limits: dict[str, int] = {}
        for raw_exchange, raw_limit in self.qty_limits.items():
            exchange = str(raw_exchange).strip().upper()
            if not exchange:
                raise ValueError("qty_limits contains an empty exchange")
            if isinstance(raw_limit, bool) or not isinstance(raw_limit, int) or raw_limit <= 0:
                raise ValueError(f"qty_limits.{exchange} must be a positive integer")
            normalised_limits[exchange] = raw_limit
        self.qty_limits = normalised_limits

    @classmethod
    def from_mapping(cls, values: Mapping[str, Any]) -> SafetyConfig:
        """Build a complete, strict configuration from persisted data."""
        expected = {
            "price_deviation_pct",
            "qty_limits",
            "max_positions",
            "max_margin_pct",
            "max_net_delta",
            "max_net_vega",
            "pnl_pause_pct",
            "pnl_kill_pct",
            "check_market_hours",
        }
        supplied = set(values)
        missing = sorted(expected - supplied)
        unknown = sorted(supplied - expected)
        if missing or unknown:
            details = []
            if missing:
                details.append(f"missing {', '.join(missing)}")
            if unknown:
                details.append(f"unknown {', '.join(unknown)}")
            raise ValueError(f"invalid safety configuration: {'; '.join(details)}")
        return cls(**dict(values))

    def to_mapping(self) -> dict[str, Any]:
        """Return a detached JSON-safe full configuration snapshot."""
        return {
            "price_deviation_pct": self.price_deviation_pct,
            "qty_limits": dict(self.qty_limits),
            "max_positions": self.max_positions,
            "max_margin_pct": self.max_margin_pct,
            "max_net_delta": self.max_net_delta,
            "max_net_vega": self.max_net_vega,
            "pnl_pause_pct": self.pnl_pause_pct,
            "pnl_kill_pct": self.pnl_kill_pct,
            "check_market_hours": self.check_market_hours,
        }


class SafetyConfigApplicationError(RuntimeError):
    """Durable safety configuration was written but could not be published in memory."""


@dataclass
class OrderExposureReservation:
    """One broker write whose exposure is not yet authoritative in account state."""

    reservation_id: str
    selector: str
    order: Any
    starting_quantity: float
    broker_order_id: str = ""
    created_at: str = ""


def _reservation_order_payload(order: Any) -> dict[str, Any]:
    """Return a detached JSON-safe order intent for crash recovery."""
    model_dump = getattr(order, "model_dump", None)
    if callable(model_dump):
        raw = model_dump(mode="json")
    elif isinstance(order, Mapping):
        raw = dict(order)
    elif hasattr(order, "__dict__"):
        raw = dict(vars(order))
    else:
        raise SafetyBypassError("order exposure reservation cannot serialise the order intent")
    try:
        payload = json.loads(json.dumps(raw, default=str))
    except (TypeError, ValueError) as exc:
        raise SafetyBypassError("order exposure reservation cannot serialise the order intent") from exc
    if not isinstance(payload, dict):
        raise SafetyBypassError("order exposure reservation produced an invalid order intent")
    return payload


class _OrderExposureReservationStore:
    """FULL-sync SQLite store for unresolved live-order exposure."""

    def __init__(self, path: str | Path) -> None:
        self._path = Path(path).expanduser()
        self._lock = threading.RLock()
        self._initialise()

    def _connect(self) -> sqlite3.Connection:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        if self._path.is_symlink():
            raise SafetyBypassError("order exposure reservation store cannot be a symbolic link")
        flags = os.O_RDWR | os.O_CREAT | getattr(os, "O_NOFOLLOW", 0)
        descriptor = os.open(self._path, flags, 0o600)
        os.close(descriptor)
        harden(self._path)
        connection = sqlite3.connect(str(self._path), timeout=5.0)
        connection.execute("PRAGMA journal_mode=WAL")
        connection.execute("PRAGMA synchronous=FULL")
        connection.execute("PRAGMA busy_timeout=5000")
        return connection

    def _initialise(self) -> None:
        with self._lock, closing(self._connect()) as connection, connection:
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS order_exposure_reservations (
                    reservation_id TEXT PRIMARY KEY,
                    selector TEXT NOT NULL,
                    order_json TEXT NOT NULL,
                    starting_quantity REAL NOT NULL,
                    broker_order_id TEXT NOT NULL DEFAULT '',
                    created_at TEXT NOT NULL
                )
                """
            )

    def load(self) -> tuple[OrderExposureReservation, ...]:
        with self._lock, closing(self._connect()) as connection, connection:
            rows = connection.execute(
                """
                SELECT reservation_id, selector, order_json, starting_quantity,
                       broker_order_id, created_at
                FROM order_exposure_reservations
                ORDER BY created_at, reservation_id
                """
            ).fetchall()
        reservations: list[OrderExposureReservation] = []
        for reservation_id, selector, order_json, starting_quantity, broker_order_id, created_at in rows:
            try:
                order = json.loads(str(order_json))
                quantity = float(starting_quantity)
            except (TypeError, ValueError, json.JSONDecodeError) as exc:
                raise SafetyBypassError("order exposure reservation store contains invalid state") from exc
            if not isinstance(order, dict) or not math.isfinite(quantity):
                raise SafetyBypassError("order exposure reservation store contains invalid state")
            reservations.append(
                OrderExposureReservation(
                    reservation_id=str(reservation_id),
                    selector=str(selector),
                    order=order,
                    starting_quantity=quantity,
                    broker_order_id=str(broker_order_id),
                    created_at=str(created_at),
                )
            )
        return tuple(reservations)

    def insert(self, reservation: OrderExposureReservation) -> None:
        order_json = json.dumps(
            _reservation_order_payload(reservation.order),
            separators=(",", ":"),
            sort_keys=True,
        )
        with self._lock, closing(self._connect()) as connection, connection:
            connection.execute(
                """
                INSERT INTO order_exposure_reservations (
                    reservation_id, selector, order_json, starting_quantity,
                    broker_order_id, created_at
                ) VALUES (?, ?, ?, ?, ?, ?)
                """,
                (
                    reservation.reservation_id,
                    reservation.selector,
                    order_json,
                    reservation.starting_quantity,
                    reservation.broker_order_id,
                    reservation.created_at,
                ),
            )

    def acknowledge(self, reservation_id: str, broker_order_id: str) -> None:
        with self._lock, closing(self._connect()) as connection, connection:
            cursor = connection.execute(
                """
                UPDATE order_exposure_reservations
                SET broker_order_id = ?
                WHERE reservation_id = ?
                """,
                (broker_order_id, reservation_id),
            )
            if cursor.rowcount != 1:
                raise SafetyBypassError("durable order exposure reservation is unavailable")

    def delete(self, reservation_ids: set[str]) -> None:
        if not reservation_ids:
            return
        with self._lock, closing(self._connect()) as connection, connection:
            connection.executemany(
                "DELETE FROM order_exposure_reservations WHERE reservation_id = ?",
                ((reservation_id,) for reservation_id in sorted(reservation_ids)),
            )


def _reservation_order_id(result: Any) -> str:
    """Return one canonical broker order id from a placement acknowledgement."""
    candidates: list[Any] = [result]
    if isinstance(result, Mapping):
        candidates.extend(result.get(key) for key in ("orderid", "order_id", "id"))
        data = result.get("data")
        if isinstance(data, Mapping):
            candidates.extend(data.get(key) for key in ("orderid", "order_id", "id"))
    else:
        candidates.extend(getattr(result, key, None) for key in ("orderid", "order_id", "id"))
    for candidate in candidates:
        if candidate is None or isinstance(candidate, (Mapping, list, tuple, set)):
            continue
        value = str(candidate)
        if value and value == value.strip() and value.isprintable() and not any(char.isspace() for char in value):
            return value
    return ""


class OrderAdmissionLease:
    """Selector-exclusive lease spanning snapshot, checks, gate, and dispatch."""

    def __init__(self, safety: SafetySystem, selector: str) -> None:
        self._safety = safety
        self.selector = selector
        self._open = True

    def _require_open(self) -> None:
        if not self._open:
            raise SafetyBypassError("order admission lease is no longer active")

    @property
    def reservations(self) -> tuple[OrderExposureReservation, ...]:
        """Return detached unresolved exposures to include in the broker snapshot."""
        self._require_open()
        return self._safety._reservation_snapshot(self.selector)

    def reconcile(self, reservation_ids: Iterable[str]) -> None:
        """Release reservations proven represented or terminal by authoritative state."""
        self._require_open()
        self._safety._reconcile_order_reservations(self.selector, reservation_ids)

    def reserve(self, order: Any, positions: Iterable[Any]) -> OrderExposureReservation:
        """Reserve the exact order before handing its one-shot gate to the router."""
        self._require_open()
        return self._safety._reserve_order_exposure(self.selector, order, positions)

    def acknowledge(self, reservation: OrderExposureReservation, result: Any) -> None:
        """Attach a broker order id without releasing unresolved exposure."""
        self._require_open()
        self._safety._acknowledge_order_reservation(
            self.selector,
            reservation.reservation_id,
            _reservation_order_id(result),
        )

    def _close(self) -> None:
        self._open = False


class SafetySystem:
    """Composite of all 5 safety layers, run in order.

    Usage::

        safety = SafetySystem()
        results = safety.check_order(
            order,
            selector="dhan:primary",
            positions=positions,
            used_margin=used_margin,
            total_balance=total_balance,
            daily_pnl=daily_pnl,
            starting_capital=starting_capital,
        )
        if not all(r.passed for r in results):
            blocked_by = [r for r in results if not r.passed]
            ...
    """

    def __init__(
        self,
        config: SafetyConfig | None = None,
        *,
        emergency_dispatcher: EmergencyDispatcher | None = None,
        reservation_db_path: str | Path | None = None,
    ) -> None:
        cfg = config or SafetyConfig()
        self.l1_order = OrderValidation(cfg.price_deviation_pct, cfg.qty_limits, cfg.check_market_hours)
        self.l2_position = PositionLimits(cfg.max_positions, cfg.max_margin_pct)
        self.l3_portfolio = PortfolioRisk(cfg.max_net_delta, cfg.max_net_vega)
        self.l4_pnl = DailyPnLLimits(cfg.pnl_pause_pct, cfg.pnl_kill_pct)
        self.l5_kill = KillSwitch(emergency_dispatcher=emergency_dispatcher)
        self.mtm_circuit_breaker = MTMCircuitBreaker(emergency_dispatcher=emergency_dispatcher)
        self._runtime_loop: asyncio.AbstractEventLoop | None = None
        self._runtime_loop_lock = threading.RLock()
        self._configuration_lock = threading.RLock()
        self._order_admission_registry_lock = threading.RLock()
        self._order_admission_locks: dict[str, threading.Lock] = {}
        self._order_exposure_reservations: dict[str, dict[str, OrderExposureReservation]] = {}
        self._order_reservation_store = (
            _OrderExposureReservationStore(reservation_db_path)
            if reservation_db_path is not None
            else None
        )
        if self._order_reservation_store is not None:
            for reservation in self._order_reservation_store.load():
                selector = self._canonical_order_selector(reservation.selector)
                if (
                    len(reservation.reservation_id) != 32
                    or any(character not in "0123456789abcdef" for character in reservation.reservation_id)
                    or not reservation.created_at
                ):
                    raise SafetyBypassError("order exposure reservation store contains invalid identity")
                if reservation.broker_order_id and not _reservation_order_id(reservation.broker_order_id):
                    raise SafetyBypassError("order exposure reservation store contains invalid broker identity")
                self._order_exposure_reservations.setdefault(selector, {})[
                    reservation.reservation_id
                ] = reservation

    @property
    def order_reservations_durable(self) -> bool:
        """Whether unresolved live-order exposure survives process restarts."""
        return self._order_reservation_store is not None

    @staticmethod
    def _canonical_order_selector(selector: str) -> str:
        value = str(selector or "")
        adapter_id, separator, account_id = value.partition(":")
        if (
            separator != ":"
            or not adapter_id
            or not account_id
            or adapter_id != adapter_id.strip().lower()
            or account_id != account_id.strip()
        ):
            raise SafetyBypassError("order admission requires an exact canonical account selector")
        return value

    def _selector_order_lock(self, selector: str) -> tuple[str, threading.Lock]:
        canonical = self._canonical_order_selector(selector)
        with self._order_admission_registry_lock:
            return canonical, self._order_admission_locks.setdefault(canonical, threading.Lock())

    @contextmanager
    def order_admission(
        self,
        selector: str,
        *,
        timeout_seconds: float = 30.0,
    ) -> Iterator[OrderAdmissionLease]:
        """Serialise one synchronous live-order admission for an exact selector."""
        canonical, lock = self._selector_order_lock(selector)
        timeout = float(timeout_seconds)
        if not math.isfinite(timeout) or timeout < 0:
            raise ValueError("order admission timeout must be finite and non-negative")
        if not lock.acquire(timeout=timeout):
            raise SafetyBypassError("order admission is already in progress for this account")
        lease = OrderAdmissionLease(self, canonical)
        try:
            yield lease
        finally:
            lease._close()
            lock.release()

    @asynccontextmanager
    async def order_admission_async(
        self,
        selector: str,
        *,
        timeout_seconds: float = 30.0,
    ) -> AsyncIterator[OrderAdmissionLease]:
        """Serialise one async live-order admission without blocking its event loop."""
        canonical, lock = self._selector_order_lock(selector)
        timeout = float(timeout_seconds)
        if not math.isfinite(timeout) or timeout < 0:
            raise ValueError("order admission timeout must be finite and non-negative")
        acquired = await asyncio.to_thread(lock.acquire, True, timeout)
        if not acquired:
            raise SafetyBypassError("order admission is already in progress for this account")
        lease = OrderAdmissionLease(self, canonical)
        try:
            yield lease
        finally:
            lease._close()
            lock.release()

    @staticmethod
    def _reservation_position_quantity(order: Any, positions: Iterable[Any]) -> float:
        normalise = PositionLimits._normalise
        key = (
            normalise(getattr(order, "symbol", None)),
            normalise(getattr(order, "exchange", None)),
            normalise(getattr(order, "product", None)),
        )
        if not all(key):
            raise SafetyBypassError("order exposure reservation requires canonical instrument identity")
        quantity = 0.0
        for position in positions:
            candidate = (
                normalise(getattr(position, "symbol", None)),
                normalise(getattr(position, "exchange", None)),
                normalise(getattr(position, "product", None)),
            )
            if candidate != key:
                continue
            try:
                parsed = float(str(getattr(position, "quantity", 0)))
            except (TypeError, ValueError) as exc:
                raise SafetyBypassError("order exposure reservation found invalid position quantity") from exc
            if not math.isfinite(parsed):
                raise SafetyBypassError("order exposure reservation found non-finite position quantity")
            quantity += parsed
        return quantity

    def _reservation_snapshot(self, selector: str) -> tuple[OrderExposureReservation, ...]:
        with self._order_admission_registry_lock:
            rows = self._order_exposure_reservations.get(selector, {})
            return tuple(copy.deepcopy(row) for row in rows.values())

    def _reserve_order_exposure(
        self,
        selector: str,
        order: Any,
        positions: Iterable[Any],
    ) -> OrderExposureReservation:
        reservation = OrderExposureReservation(
            reservation_id=secrets.token_hex(16),
            selector=selector,
            order=copy.deepcopy(order),
            starting_quantity=self._reservation_position_quantity(order, positions),
            created_at=datetime.now(UTC).isoformat(),
        )
        with self._order_admission_registry_lock:
            if self._order_reservation_store is not None:
                self._order_reservation_store.insert(reservation)
            self._order_exposure_reservations.setdefault(selector, {})[reservation.reservation_id] = reservation
        return copy.deepcopy(reservation)

    def _acknowledge_order_reservation(
        self,
        selector: str,
        reservation_id: str,
        broker_order_id: str,
    ) -> None:
        if not broker_order_id:
            raise SafetyBypassError("broker placement acknowledgement lacks a canonical order id")
        with self._order_admission_registry_lock:
            try:
                reservation = self._order_exposure_reservations[selector][reservation_id]
            except KeyError as exc:
                raise SafetyBypassError("order exposure reservation is unavailable") from exc
            if self._order_reservation_store is not None:
                self._order_reservation_store.acknowledge(reservation_id, broker_order_id)
            reservation.broker_order_id = broker_order_id

    def _reconcile_order_reservations(self, selector: str, reservation_ids: Iterable[str]) -> None:
        canonical_ids = {str(value) for value in reservation_ids if str(value)}
        if not canonical_ids:
            return
        with self._order_admission_registry_lock:
            rows = self._order_exposure_reservations.get(selector)
            if rows is None:
                return
            existing_ids = canonical_ids.intersection(rows)
            if self._order_reservation_store is not None:
                self._order_reservation_store.delete(existing_ids)
            for reservation_id in canonical_ids:
                rows.pop(reservation_id, None)
            if not rows:
                self._order_exposure_reservations.pop(selector, None)

    def snapshot_config(self) -> SafetyConfig:
        """Return one coherent snapshot of every tuneable L1-L4 threshold."""
        with self._configuration_lock:
            return self._snapshot_config_locked()

    def _snapshot_config_locked(self) -> SafetyConfig:
        return SafetyConfig(
            price_deviation_pct=self.l1_order.price_deviation_pct,
            qty_limits=dict(self.l1_order.qty_limits),
            max_positions=self.l2_position.max_positions,
            max_margin_pct=self.l2_position.max_margin_pct,
            max_net_delta=self.l3_portfolio.max_net_delta,
            max_net_vega=self.l3_portfolio.max_net_vega,
            pnl_pause_pct=self.l4_pnl.pause_pct,
            pnl_kill_pct=self.l4_pnl.kill_pct,
            check_market_hours=self.l1_order.check_market_hours,
        )

    def persist_and_apply_config(
        self,
        config: SafetyConfig,
        persist: Callable[[SafetyConfig], Any],
    ) -> None:
        """Persist a complete candidate before atomically publishing it in memory."""
        if not isinstance(config, SafetyConfig):
            raise TypeError("config must be a validated SafetyConfig")
        with self._configuration_lock:
            self._persist_and_apply_config_locked(config, persist)

    def update_and_persist_config(
        self,
        updates: Mapping[str, Any],
        persist: Callable[[SafetyConfig], Any],
    ) -> SafetyConfig:
        """Merge a partial update into the latest snapshot and publish it durably."""
        if not isinstance(updates, Mapping) or not updates:
            raise ValueError("safety configuration update must be a non-empty mapping")
        with self._configuration_lock:
            candidate_values = self._snapshot_config_locked().to_mapping()
            candidate_values.update(dict(updates))
            candidate = SafetyConfig.from_mapping(candidate_values)
            self._persist_and_apply_config_locked(candidate, persist)
            return candidate

    def _persist_and_apply_config_locked(
        self,
        config: SafetyConfig,
        persist: Callable[[SafetyConfig], Any],
    ) -> None:
        persist(config)
        try:
            self.l1_order.price_deviation_pct = config.price_deviation_pct
            self.l1_order.qty_limits = dict(config.qty_limits)
            self.l1_order.check_market_hours = config.check_market_hours
            self.l2_position.max_positions = config.max_positions
            self.l2_position.max_margin_pct = config.max_margin_pct
            self.l3_portfolio.max_net_delta = config.max_net_delta
            self.l3_portfolio.max_net_vega = config.max_net_vega
            self.l4_pnl.pause_pct = config.pnl_pause_pct
            self.l4_pnl.kill_pct = config.pnl_kill_pct
        except Exception as exc:
            raise SafetyConfigApplicationError(
                "persisted safety configuration could not be published"
            ) from exc

    def bind_emergency_dispatcher(self, dispatcher: EmergencyDispatcher | None) -> None:
        """Expose the parent injection point without importing Flask or gateway."""
        self.l5_kill.bind_emergency_dispatcher(dispatcher)
        self.mtm_circuit_breaker.bind_emergency_dispatcher(dispatcher)

    def bind_emergency_journal(self, journal: EmergencyIntentJournalProtocol | None) -> None:
        """Restore durable L5 and account MTM latches before routing starts."""
        self.l5_kill.bind_emergency_journal(journal)
        self.mtm_circuit_breaker.bind_emergency_journal(journal)

    def bind_daily_pnl_state_store(self, store: DailyPnLStateStoreProtocol) -> None:
        """Bind the durable account-scoped Layer 4 store before live routing."""
        self.l4_pnl.bind_state_store(store)

    @contextmanager
    def broker_write_admission(self, emergency_reduction: bool, selector: str) -> Iterator[None]:
        """Apply global L5 and account-scoped MTM admission around one write."""
        with self.l5_kill.broker_write_admission(emergency_reduction, selector):
            with self.mtm_circuit_breaker.broker_write_admission(emergency_reduction, selector):
                yield

    def bind_runtime_loop(self, loop: asyncio.AbstractEventLoop) -> None:
        """Bind production MTM checks to the application's long-lived loop."""
        if loop.is_closed() or not loop.is_running():
            raise RuntimeError("Safety runtime loop is not running")
        with self._runtime_loop_lock:
            current = self._runtime_loop
            if current is not None and current is not loop and current.is_running():
                raise RuntimeError("Safety system is already bound to another runtime loop")
            self._runtime_loop = loop

    def unbind_runtime_loop(self, loop: asyncio.AbstractEventLoop | None = None) -> None:
        """Release a stopped runtime loop without creating a replacement monitor."""
        with self._runtime_loop_lock:
            if loop is None or self._runtime_loop is loop:
                self._runtime_loop = None

    @property
    def runtime_loop_ready(self) -> bool:
        """Whether automatic emergency checks own a live runtime loop."""
        with self._runtime_loop_lock:
            loop = self._runtime_loop
            return loop is not None and not loop.is_closed() and loop.is_running()

    def submit_daily_mtm(
        self,
        daily_pnl: float,
        *,
        adapter_id: str,
        account_id: str,
    ) -> bool:
        """Schedule one non-blocking authoritative MTM check from a live update.

        The submitted coroutine uses the single circuit breaker owned by this
        safety system.  Its dispatcher is the already-bound gated dispatcher,
        so any resulting broker mutation still mints a fresh SafetyContext and
        crosses BrokerRouter rather than touching an adapter directly.
        """
        try:
            value = float(daily_pnl)
        except (TypeError, ValueError):
            logger.error("Runtime MTM update rejected because its value is invalid")
            return False
        if not math.isfinite(value):
            logger.error("Runtime MTM update rejected because its value is non-finite")
            return False
        try:
            if not _emergency_selector_scope(adapter_id, account_id):
                raise SafetyBypassError("runtime MTM update requires an exact account selector")
        except SafetyBypassError:
            logger.error("Runtime MTM update rejected because its account selector is invalid")
            return False
        with self._runtime_loop_lock:
            loop = self._runtime_loop
            if loop is None or loop.is_closed() or not loop.is_running():
                logger.error("Runtime MTM update refused because the safety loop is unavailable")
                return False
            future = asyncio.run_coroutine_threadsafe(
                self.mtm_circuit_breaker.check_and_act(
                    value,
                    adapter_id=adapter_id,
                    account_id=account_id,
                ),
                loop,
            )

        def log_failure(completed: Any) -> None:
            try:
                completed.result()
            except Exception as exc:  # noqa: BLE001 - breaker remains latched on dispatch failure
                logger.error("Runtime MTM circuit-breaker task failed closed (%s)", type(exc).__name__)

        future.add_done_callback(log_failure)
        return True

    def check_order(
        self,
        order: Order,
        *,
        selector: str,
        ltp: float | None = None,
        positions: list[Position] | None = None,
        used_margin: float = 0.0,
        total_balance: float = 0.0,
        net_delta: float = 0.0,
        net_vega: float = 0.0,
        daily_pnl: float = 0.0,
        starting_capital: float = 0.0,
        at: datetime | None = None,
    ) -> list[SafetyResult]:
        """Run order through all 5 layers and return results.

        Stops at the first failing layer (fail-fast).
        """
        with self._configuration_lock:
            return self._check_order_locked(
                order,
                selector=selector,
                ltp=ltp,
                positions=positions,
                used_margin=used_margin,
                total_balance=total_balance,
                net_delta=net_delta,
                net_vega=net_vega,
                daily_pnl=daily_pnl,
                starting_capital=starting_capital,
                at=at,
            )

    def _check_order_locked(
        self,
        order: Order,
        *,
        selector: str,
        ltp: float | None = None,
        positions: list[Position] | None = None,
        used_margin: float = 0.0,
        total_balance: float = 0.0,
        net_delta: float = 0.0,
        net_vega: float = 0.0,
        daily_pnl: float = 0.0,
        starting_capital: float = 0.0,
        at: datetime | None = None,
    ) -> list[SafetyResult]:
        results: list[SafetyResult] = []

        # L5 first — if kill switch is on, nothing passes
        r5 = self.l5_kill.validate()
        results.append(r5)
        if not r5.passed:
            return results

        # L4 — daily P&L
        r4 = self.l4_pnl.validate(daily_pnl, starting_capital, selector=selector, at=at)
        results.append(r4)
        if not r4.passed:
            return results

        # L1 — order validation (exchange, market hours, symbol, qty, price)
        r1 = self.l1_order.validate(order, ltp, at=at)
        results.append(r1)
        if not r1.passed:
            return results

        # L2 — position limits
        r2 = self.l2_position.validate(
            positions or [],
            used_margin,
            total_balance,
            order=order,
        )
        results.append(r2)
        if not r2.passed:
            return results

        # L3 — portfolio greeks
        r3 = self.l3_portfolio.validate(net_delta, net_vega)
        results.append(r3)

        return results


# ---------------------------------------------------------------------------
# OvertradingGuard
# ---------------------------------------------------------------------------


@dataclass
class OvertradingConfig:
    """Configurable thresholds for the OvertradingGuard."""

    cooldown_seconds: int = 60
    """Minimum seconds between successive orders for the same symbol."""

    max_consecutive_losses: int = 3
    """Pause all new orders for ``loss_pause_seconds`` after this many consecutive losses."""

    loss_pause_seconds: int = 300
    """How long (seconds) to pause after hitting ``max_consecutive_losses``."""

    max_hold_hours: float = 6.0
    """Warn (but do not block) when a position has been held beyond this many hours."""

    daily_trade_limit_per_symbol: int = 10
    """Maximum trades per symbol per day (0 = unlimited)."""


@dataclass
class OvertradingGuardState:
    """Internal per-symbol state tracked by OvertradingGuard."""

    last_order_at: datetime | None = None
    daily_trade_count: int = 0
    last_count_reset_date: str = ""  # ISO date string, e.g. "2026-04-13"


class OvertradingGuard:
    """Additional trade-frequency and loss-streak safety guard.

    This guard is **not** part of the 5-layer per-order pipeline.  It is
    meant to be called *before* :meth:`SafetySystem.check_order` as a
    pre-filter, or used independently inside strategy logic.

    Adapted from LLM-TradeBot's ``OvertradingGuard`` (decision_core_agent.py)
    and adapted to FlintTrade's time-based (rather than cycle-based) design.

    Features:
    - Per-symbol cooldown (configurable, default 60 s between orders).
    - Consecutive-loss streak tracker — pause after N consecutive losses.
    - 6-hour max position hold warning (non-blocking).
    - Daily trade count limit per symbol.

    Args:
        config: Tuneable thresholds.  Defaults to :class:`OvertradingConfig`.

    Example::

        guard = OvertradingGuard()
        ok, reason = guard.can_trade("NIFTY25APRFUT")
        if not ok:
            raise OrderBlockedError(reason)
        # ... place order ...
        guard.record_order("NIFTY25APRFUT")
        # ... on trade completion ...
        guard.record_trade_result("NIFTY25APRFUT", pnl=-800.0)
    """

    def __init__(self, config: OvertradingConfig | None = None) -> None:
        self._cfg = config or OvertradingConfig()
        self._symbol_state: dict[str, OvertradingGuardState] = defaultdict(OvertradingGuardState)
        self._consecutive_losses: int = 0
        self._pause_until: datetime | None = None

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def can_trade(self, symbol: str, at: datetime | None = None) -> tuple[bool, str]:
        """Check whether a new order for *symbol* is allowed right now.

        Args:
            symbol: Trading symbol (e.g. ``"NIFTY25APRFUT"``).
            at:     Override "now" for testing.  Defaults to current IST time.

        Returns:
            ``(allowed, reason)`` — if *allowed* is ``False``, *reason*
            describes which guard triggered.
        """
        now = at or datetime.now(IST)

        # 1. Consecutive-loss pause (global — not per symbol)
        if self._pause_until is not None and now < self._pause_until:
            remaining = int((self._pause_until - now).total_seconds())
            return (
                False,
                f"Trading paused after {self._consecutive_losses} consecutive losses — resumes in {remaining}s",
            )

        state = self._symbol_state[symbol]
        self._reset_daily_count_if_needed(state, now)

        # 2. Per-symbol cooldown
        if state.last_order_at is not None:
            elapsed = (now - state.last_order_at).total_seconds()
            if elapsed < self._cfg.cooldown_seconds:
                remaining = int(self._cfg.cooldown_seconds - elapsed)
                return (
                    False,
                    f"{symbol}: cooldown active — next order allowed in {remaining}s",
                )

        # 3. Daily trade count limit
        if (
            self._cfg.daily_trade_limit_per_symbol > 0
            and state.daily_trade_count >= self._cfg.daily_trade_limit_per_symbol
        ):
            return (
                False,
                f"{symbol}: daily trade limit of {self._cfg.daily_trade_limit_per_symbol} reached",
            )

        return True, ""

    def check_hold_duration(
        self,
        symbol: str,
        position_opened_at: datetime,
        at: datetime | None = None,
    ) -> tuple[bool, str]:
        """Warn if a position has been held beyond the configured hold limit.

        This is a *warning only* — it never blocks an order.  Callers should
        log or surface the message without preventing execution.

        Args:
            symbol:             Trading symbol.
            position_opened_at: When the position was originally opened (IST-aware).
            at:                 Override "now" for testing.

        Returns:
            ``(over_limit, message)`` — *over_limit* is ``True`` when the
            hold duration exceeds :attr:`OvertradingConfig.max_hold_hours`.
        """
        now = at or datetime.now(IST)
        hold_hours = (now - position_opened_at).total_seconds() / 3600.0
        if hold_hours > self._cfg.max_hold_hours:
            msg = f"{symbol}: position held for {hold_hours:.1f}h (warning limit {self._cfg.max_hold_hours}h)"
            logger.warning("OvertradingGuard: %s", msg)
            return True, msg
        return False, ""

    def record_order(self, symbol: str, at: datetime | None = None) -> None:
        """Record that an order was placed for *symbol*.

        Call this immediately after an order is submitted to update the
        cooldown clock and daily count.

        Args:
            symbol: Trading symbol.
            at:     Override "now" for testing.
        """
        now = at or datetime.now(IST)
        state = self._symbol_state[symbol]
        self._reset_daily_count_if_needed(state, now)
        state.last_order_at = now
        state.daily_trade_count += 1
        logger.debug("OvertradingGuard: recorded order for %s (daily count=%d)", symbol, state.daily_trade_count)

    def record_trade_result(self, symbol: str, pnl: float) -> None:
        """Record the P&L outcome of a completed trade.

        Updates the consecutive-loss streak.  A loss is any trade where
        ``pnl < 0``.

        Args:
            symbol: Trading symbol.
            pnl:    Realised P&L of the trade (negative = loss).
        """
        if pnl < 0:
            self._consecutive_losses += 1
            if self._consecutive_losses >= self._cfg.max_consecutive_losses:
                self._pause_until = datetime.now(IST) + timedelta(
                    seconds=self._cfg.loss_pause_seconds,
                )
                logger.warning(
                    "OvertradingGuard: %d consecutive losses — trading paused for %ds",
                    self._consecutive_losses,
                    self._cfg.loss_pause_seconds,
                )
        else:
            self._consecutive_losses = 0
        logger.debug(
            "OvertradingGuard: trade result for %s pnl=%.2f consecutive_losses=%d",
            symbol,
            pnl,
            self._consecutive_losses,
        )

    def reset_daily(self) -> None:
        """Reset daily trade counts for all symbols (call at market open)."""
        for state in self._symbol_state.values():
            state.daily_trade_count = 0
            state.last_count_reset_date = ""
        logger.info("OvertradingGuard: daily trade counts reset")


# ---------------------------------------------------------------------------
# IntradayAllowList
# ---------------------------------------------------------------------------


class IntradayAllowList:
    """Configurable intraday (MIS) allow-list guard.

    NSE periodically publishes a list of scrips blocked for intraday trading
    (e.g. recently suspended stocks, SME/IND-AS scrips, and securities under
    T2T or Trade-for-Trade settlement).  This guard maintains a configurable
    blocked set and refuses MIS orders for any symbol in that set.

    Key design decisions:
    - Only applies when ``product`` is ``"MIS"`` (intraday).  CNC and NRML
      orders are always allowed regardless of the blocked list.
    - Default state is an *empty* blocked set — everything is permitted.
    - The blocked set is populated by the user via ``workspace.json``
      (``intraday_blocked_scrips`` key) or programmatically via
      :meth:`add` / :meth:`update_blocked`.
    - Symbols are stored and compared case-insensitively (uppercased).

    Args:
        blocked_scrips: Initial set of blocked symbols (optional).

    Example::

        allow_list = IntradayAllowList(blocked_scrips={"ZZZTEST", "SMEFOO"})
        ok, reason = allow_list.is_allowed_intraday("SMEFOO", "NSE", "MIS")
        # ok == False, reason contains "SMEFOO"

        ok, _ = allow_list.is_allowed_intraday("RELIANCE", "NSE", "CNC")
        # ok == True  (CNC is never blocked)
    """

    # The canonical attribute name that workspace.json loaders populate.
    WORKSPACE_KEY: str = "intraday_blocked_scrips"

    def __init__(
        self,
        blocked_scrips: set[str] | None = None,
    ) -> None:
        self.BLOCKED_SCRIPS: set[str] = {s.upper() for s in (blocked_scrips or set())}

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def is_allowed_intraday(
        self,
        symbol: str,
        exchange: str,  # noqa: ARG002 — reserved for future per-exchange rules
        product: str,
    ) -> tuple[bool, str]:
        """Check whether *symbol* is permitted for intraday trading.

        Only MIS orders are subject to the blocked-list check.  CNC and NRML
        products are unconditionally allowed.

        Args:
            symbol:   Trading symbol (e.g. ``"RELIANCE"``).
            exchange: Exchange code (e.g. ``"NSE"``).  Reserved for
                      future per-exchange rules; not used currently.
            product:  Order product type — ``"MIS"``, ``"CNC"``,
                      ``"NRML"``, etc.

        Returns:
            ``(allowed, reason)`` tuple.  When *allowed* is ``False``,
            *reason* contains a human-readable explanation suitable for
            logging or surfacing in the UI.
        """
        if product.upper() != "MIS":
            return True, ""

        normalised = symbol.upper()
        if normalised in self.BLOCKED_SCRIPS:
            return (
                False,
                (
                    f"{symbol} is blocked for intraday (MIS) trading. "
                    "Use CNC/NRML or remove it from the blocked list in Settings."
                ),
            )

        return True, ""

    def add(self, symbol: str) -> None:
        """Add a single symbol to the blocked set.

        Args:
            symbol: Symbol to block (stored in uppercase).
        """
        self.BLOCKED_SCRIPS.add(symbol.upper())
        logger.info("IntradayAllowList: blocked %s for MIS trading", symbol.upper())

    def remove(self, symbol: str) -> None:
        """Remove a symbol from the blocked set (no-op if not present).

        Args:
            symbol: Symbol to unblock.
        """
        removed = self.BLOCKED_SCRIPS.discard(symbol.upper())
        if removed is None:  # discard always returns None; log anyway
            logger.info("IntradayAllowList: unblocked %s", symbol.upper())

    def update_blocked(self, symbols: set[str] | list[str]) -> None:
        """Replace the entire blocked set with a new collection.

        This is the primary integration point for workspace.json loaders:
        call this method at startup with the value of
        ``workspace["intraday_blocked_scrips"]``.

        Args:
            symbols: Iterable of symbols to block (case-insensitive).
        """
        self.BLOCKED_SCRIPS = {s.upper() for s in symbols}
        logger.info("IntradayAllowList: updated blocked set (%d symbols)", len(self.BLOCKED_SCRIPS))

    def is_blocked(self, symbol: str) -> bool:
        """Return True if *symbol* is in the blocked set.

        Args:
            symbol: Trading symbol (case-insensitive).

        Returns:
            ``True`` when the symbol is blocked for MIS.
        """
        return symbol.upper() in self.BLOCKED_SCRIPS

    def __len__(self) -> int:
        return len(self.BLOCKED_SCRIPS)

    def __repr__(self) -> str:
        return f"IntradayAllowList(blocked={len(self.BLOCKED_SCRIPS)} symbols)"


# NOTE: The OvertradingGuard.consecutive_losses property, OvertradingGuard.is_paused
# property, and OvertradingGuard._reset_daily_count_if_needed method are defined
# below (after IntradayAllowList) and attached to the class directly.  This is
# necessary because the original class body was split when IntradayAllowList was
# inserted mid-class.  The methods are semantically part of OvertradingGuard.

OvertradingGuard.consecutive_losses = property(  # type: ignore[assignment]
    lambda self: self._consecutive_losses,
    doc="Current consecutive-loss streak count.",
)

OvertradingGuard.is_paused = property(  # type: ignore[assignment]
    lambda self: False if self._pause_until is None else datetime.now(IST) < self._pause_until,
    doc="True if the guard is currently in loss-streak pause.",
)


def _overtrading_guard_reset_daily_count_if_needed(
    self: OvertradingGuard,
    state: OvertradingGuardState,
    now: datetime,
) -> None:
    today = now.strftime("%Y-%m-%d")
    if state.last_count_reset_date != today:
        state.daily_trade_count = 0
        state.last_count_reset_date = today


OvertradingGuard._reset_daily_count_if_needed = (  # type: ignore[assignment]
    _overtrading_guard_reset_daily_count_if_needed
)


# ---------------------------------------------------------------------------
# MTMCircuitBreaker
# ---------------------------------------------------------------------------


@dataclass
class MTMCircuitBreakerConfig:
    """Configuration for the account-level MTM circuit breaker."""

    daily_loss_limit: float = -50_000.0
    """Daily MTM loss threshold (negative INR).  When total P&L across all
    positions drops below this value, all positions are exited."""


class MTMCircuitBreaker:
    """Account-level daily MTM loss circuit breaker.

    Monitors total P&L across all positions and auto-exits everything when
    the configurable daily loss threshold is breached. The breaker latches for
    the trading day, suppresses concurrent duplicate dispatches, and retries an
    incomplete gated flatten on later breached updates until it completes.

    Adapted from the MTM-based short straddle pattern in
    ``algo_trading_strategies_india``, adapted for gated router execution.

    Args:
        config: :class:`MTMCircuitBreakerConfig` with the loss limit.
        emergency_dispatcher: Parent-owned gated dispatcher. Missing injection
            fails closed without weakening the triggered breaker state.

    Example::

        mtm_cb = MTMCircuitBreaker(config=MTMCircuitBreakerConfig(daily_loss_limit=-30000))
        fired = await mtm_cb.check_and_act(
            daily_pnl=-35000,
            activity_logger=my_logger,
            adapter_id="dhan",
            account_id="primary",
        )
        if fired and mtm_cb.last_emergency_result and mtm_cb.last_emergency_result.complete:
            # breaker fired and the gated exit-all completed
    """

    def __init__(
        self,
        config: MTMCircuitBreakerConfig | None = None,
        *,
        emergency_dispatcher: EmergencyDispatcher | None = None,
        normal_write_drain_timeout: float = 5.0,
        session_key_provider: Callable[[], str] | None = None,
    ) -> None:
        self._cfg = config or MTMCircuitBreakerConfig()
        self._emergency_dispatcher = emergency_dispatcher
        self._emergency_journal: EmergencyIntentJournalProtocol | None = None
        self._normal_write_drain_timeout = float(normal_write_drain_timeout)
        if self._normal_write_drain_timeout < 0:
            raise ValueError("normal-write drain timeout must be non-negative")
        self._triggered = False
        self._triggered_selectors: set[str] = set()
        self._triggered_session_keys: dict[str, str] = {}
        self._triggered_episodes: dict[str, EmergencyEpisodeRecord] = {}
        self._dispatching_selectors: dict[str, int] = {}
        self._normal_writes_in_progress: dict[str, int] = defaultdict(int)
        self._reset_generation = 0
        self._last_emergency_result: EmergencyDispatchResult | None = None
        self._condition = threading.Condition()
        self._session_key_provider = session_key_provider or (lambda: datetime.now(IST).date().isoformat())

    @property
    def is_triggered(self) -> bool:
        """True after the circuit breaker has fired today."""
        with self._condition:
            return self._triggered

    @property
    def last_emergency_result(self) -> EmergencyDispatchResult | None:
        """Most recent bounded MTM flatten result."""
        with self._condition:
            return self._last_emergency_result

    def bind_emergency_dispatcher(self, dispatcher: EmergencyDispatcher | None) -> None:
        """Bind the parent-owned gated dispatcher used by later breaches."""
        with self._condition:
            self._emergency_dispatcher = dispatcher

    def bind_emergency_journal(self, journal: EmergencyIntentJournalProtocol | None) -> None:
        """Restore account MTM latches left active by a prior process."""
        episodes = () if journal is None else journal.active_episodes("mtm")
        current_session_key = self._current_session_key()
        if journal is not None:
            for episode in episodes:
                if not self._is_prior_session(episode.session_key, current_session_key):
                    continue
                try:
                    journal.deactivate_episode(expected=episode)
                except EmergencyIntentConflict:
                    logger.warning(
                        "Prior-session MTM episode remains active for %s because broker intent is unsettled",
                        episode.selector,
                    )
            episodes = journal.active_episodes("mtm")
        selectors = {episode.selector for episode in episodes}
        with self._condition:
            self._emergency_journal = journal
            self._triggered_selectors = selectors
            self._triggered_session_keys = {
                episode.selector: episode.session_key for episode in episodes
            }
            self._triggered_episodes = {episode.selector: episode for episode in episodes}
            self._triggered = bool(self._triggered_selectors)

    def _current_session_key(self) -> str:
        try:
            session_key = str(self._session_key_provider())
            date.fromisoformat(session_key)
        except Exception as exc:
            raise SafetyBypassError("MTM session date is unavailable; broker write refused") from exc
        return session_key

    @staticmethod
    def _is_prior_session(session_key: str, current_session_key: str) -> bool:
        try:
            return date.fromisoformat(session_key) < date.fromisoformat(current_session_key)
        except ValueError:
            return False

    def _roll_over_prior_session_locked(self, selector: str) -> None:
        episode = self._triggered_episodes.get(selector)
        session_key = self._triggered_session_keys.get(selector)
        if session_key is None or not self._is_prior_session(session_key, self._current_session_key()):
            return
        if selector in self._dispatching_selectors or self._normal_writes_in_progress.get(selector, 0):
            return
        journal = self._emergency_journal
        if journal is not None:
            try:
                journal.deactivate_episode(expected=episode)
            except EmergencyIntentConflict:
                return
            except Exception as exc:
                raise SafetyBypassError("emergency journal unavailable; broker write refused") from exc
        self._triggered_selectors.discard(selector)
        self._triggered_session_keys.pop(selector, None)
        self._triggered_episodes.pop(selector, None)
        self._triggered = bool(self._triggered_selectors)

    @staticmethod
    def _canonical_selector(selector: str) -> str:
        adapter_id, separator, account_id = str(selector).partition(":")
        if not separator or _emergency_selector_scope(adapter_id, account_id) != selector:
            raise SafetyBypassError("broker write requires a canonical account selector")
        return selector

    @contextmanager
    def broker_write_admission(self, emergency_reduction: bool, selector: str) -> Iterator[None]:
        """Block normal writes for an account as soon as its MTM latch fires."""
        if emergency_reduction:
            yield
            return
        canonical_selector = self._canonical_selector(selector)
        with self._condition:
            self._roll_over_prior_session_locked(canonical_selector)
            journal = self._emergency_journal
            if journal is not None:
                try:
                    durable_sources = journal.blocking_sources(canonical_selector)
                except Exception as exc:
                    raise SafetyBypassError("emergency journal unavailable; broker write refused") from exc
                if "mtm" in durable_sources:
                    try:
                        episode = next(
                            episode
                            for episode in journal.active_episodes("mtm")
                            if episode.selector == canonical_selector
                        )
                    except StopIteration as exc:
                        raise SafetyBypassError("MTM emergency state changed; broker write refused") from exc
                    except Exception as exc:
                        raise SafetyBypassError("emergency journal unavailable; broker write refused") from exc
                    self._triggered = True
                    self._triggered_selectors.add(canonical_selector)
                    self._triggered_session_keys[canonical_selector] = episode.session_key
                    self._triggered_episodes[canonical_selector] = episode
                    self._roll_over_prior_session_locked(canonical_selector)
            if canonical_selector in self._triggered_selectors:
                raise SafetyBypassError(
                    f"MTM circuit breaker is active for {canonical_selector}; broker write refused"
                )
            self._normal_writes_in_progress[canonical_selector] += 1
        try:
            yield
        finally:
            with self._condition:
                remaining = self._normal_writes_in_progress[canonical_selector] - 1
                if remaining > 0:
                    self._normal_writes_in_progress[canonical_selector] = remaining
                else:
                    self._normal_writes_in_progress.pop(canonical_selector, None)
                self._condition.notify_all()

    def _wait_for_normal_writes(self, selector: str) -> bool:
        deadline = time.monotonic() + self._normal_write_drain_timeout
        with self._condition:
            while self._normal_writes_in_progress.get(selector, 0):
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    return False
                self._condition.wait(timeout=remaining)
            return True

    async def check_and_act(
        self,
        daily_pnl: float,
        activity_logger: logging.Logger | None = None,
        *,
        adapter_id: str,
        account_id: str,
    ) -> bool:
        """Check daily P&L and trigger auto-exit if threshold is breached.

        Args:
            daily_pnl:        Current total daily MTM P&L (negative = loss).
            activity_logger:  Optional logger for structured audit output.
                              If ``None`` the module logger is used.
            adapter_id:       Exact adapter whose account MTM was measured.
            account_id:       Exact account whose MTM was measured.

        Returns:
            ``True`` if the breaker fired (and gated flattening was requested),
            ``False`` if within limits, already flattened, or already dispatching.
        """
        selector = _emergency_selector_scope(adapter_id, account_id)
        if not selector:
            raise SafetyBypassError("MTM circuit breaker requires an exact account selector")
        with self._condition:
            self._roll_over_prior_session_locked(selector)
            if daily_pnl > self._cfg.daily_loss_limit:
                return False
            self._triggered = True
            self._triggered_selectors.add(selector)
            if selector in self._dispatching_selectors:
                return False
            journal = self._emergency_journal
            dispatcher = self._emergency_dispatcher
            journal_ready = True
            if journal is not None:
                session_key = self._current_session_key()
                reason_hash = hashlib.sha256(
                    f"{selector}:{daily_pnl:.2f}:{self._cfg.daily_loss_limit:.2f}".encode()
                ).hexdigest()
                try:
                    episode, _created = journal.activate_episode(
                        source="mtm",
                        selector=selector,
                        session_key=session_key,
                        reason_hash=reason_hash,
                    )
                    self._triggered_session_keys[selector] = episode.session_key
                    self._triggered_episodes[selector] = episode
                except Exception as exc:  # noqa: BLE001 - the local latch remains active
                    # Mirror the L5 posture: a dead durable store must not veto
                    # the account flatten — fall back to the dispatcher's
                    # process-local intent journal. The durable episode map is
                    # deliberately NOT populated, so latch reset stays bound to
                    # the durable journal alone.
                    ensure = getattr(dispatcher, "ensure_degraded_episode", None)
                    journal_ready = callable(ensure) and bool(
                        ensure(
                            source="mtm",
                            selector=selector,
                            session_key=session_key,
                            reason_hash=reason_hash,
                        )
                    )
                    if journal_ready:
                        self._triggered_session_keys[selector] = session_key
                        logger.critical(
                            "MTMCircuitBreaker: durable episode failed (%s); continuing on the "
                            "dispatcher's process-local intent journal",
                            type(exc).__name__,
                        )
                    else:
                        logger.error("MTMCircuitBreaker: durable episode failed closed (%s)", type(exc).__name__)
            else:
                self._triggered_session_keys[selector] = self._current_session_key()
            generation = self._reset_generation
            self._dispatching_selectors[selector] = generation

        log = activity_logger or logger
        log.critical(
            "MTMCircuitBreaker: %s daily P&L %.2f breached limit %.2f — exiting that account's positions",
            selector,
            daily_pnl,
            self._cfg.daily_loss_limit,
        )

        result: EmergencyDispatchResult | None = None
        try:
            normal_writes_drained = (
                await asyncio.to_thread(self._wait_for_normal_writes, selector) if journal_ready else False
            )
            if not journal_ready:
                result = EmergencyDispatchResult.failed(
                    MTM_EMERGENCY_POLICY,
                    "intent_journal_unavailable",
                    selector=selector,
                )
            elif not normal_writes_drained:
                result = EmergencyDispatchResult.failed(
                    MTM_EMERGENCY_POLICY,
                    "normal_write_drain_timeout",
                    selector=selector,
                )
            elif dispatcher is None:
                result = EmergencyDispatchResult.failed(
                    MTM_EMERGENCY_POLICY,
                    "dispatcher_unavailable",
                    selector=selector,
                )
            else:
                candidate = await asyncio.to_thread(
                    dispatcher.dispatch,
                    MTM_EMERGENCY_POLICY,
                    reason=(f"daily P&L {daily_pnl:.2f} breached limit {self._cfg.daily_loss_limit:.2f}"),
                    adapter_id=adapter_id,
                    account_id=account_id,
                )
                valid_candidate = (
                    isinstance(candidate, EmergencyDispatchResult)
                    and candidate.policy == MTM_EMERGENCY_POLICY
                    and len(candidate.outcomes) == len(MTM_EMERGENCY_POLICY.verbs)
                    and tuple(outcome.verb for outcome in candidate.outcomes)
                    == MTM_EMERGENCY_POLICY.verbs
                    and {outcome.selector for outcome in candidate.outcomes} == {selector}
                )
                result = (
                    candidate
                    if valid_candidate
                    else EmergencyDispatchResult.failed(
                        MTM_EMERGENCY_POLICY,
                        "invalid_dispatch_result",
                        attempted=True,
                        selector=selector,
                    )
                )
        except Exception as exc:  # noqa: BLE001 - breaker remains triggered
            log.error(
                "MTMCircuitBreaker: gated emergency dispatch failed closed (%s)",
                type(exc).__name__,
            )
            result = EmergencyDispatchResult.failed(
                MTM_EMERGENCY_POLICY,
                "dispatch_failed",
                attempted=True,
                selector=selector,
            )
        finally:
            with self._condition:
                if self._dispatching_selectors.get(selector) == generation:
                    self._dispatching_selectors.pop(selector, None)
                if result is not None and self._reset_generation == generation:
                    self._last_emergency_result = result
                self._condition.notify_all()

        assert result is not None  # all ordinary dispatcher failures are converted above
        if result.complete:
            log.info("MTMCircuitBreaker: gated exit-all completed")
        else:
            log.error(
                "MTMCircuitBreaker: gated exit-all incomplete (%s)",
                ",".join(result.failure_codes),
            )

        return True

    def reset_daily(self, *, timeout: float = 5.0) -> None:
        """Reset only after every in-flight MTM flatten reaches a final state."""
        wait_timeout = float(timeout)
        if wait_timeout < 0:
            raise ValueError("MTM reset timeout must be non-negative")
        deadline = time.monotonic() + wait_timeout
        with self._condition:
            while self._dispatching_selectors or any(
                self._normal_writes_in_progress.get(selector, 0)
                for selector in self._triggered_selectors
            ):
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    raise SafetyBypassError("MTM emergency work is still in progress; daily reset refused")
                self._condition.wait(timeout=remaining)
            if self._emergency_journal is not None:
                try:
                    current = {
                        episode.selector: episode
                        for episode in self._emergency_journal.active_episodes("mtm")
                    }
                    expected = tuple(
                        current[selector] for selector in sorted(self._triggered_selectors)
                    )
                    if len(expected) != len(self._triggered_selectors):
                        raise EmergencyIntentConflict("MTM emergency episode changed during reset")
                    self._emergency_journal.deactivate_episodes(expected=expected)
                except SafetyBypassError:
                    raise
                except Exception as exc:
                    raise SafetyBypassError(
                        "emergency journal unavailable; MTM reset refused"
                    ) from exc
            self._reset_generation += 1
            self._triggered = False
            self._triggered_selectors.clear()
            self._triggered_session_keys.clear()
            self._triggered_episodes.clear()
            self._dispatching_selectors.clear()
            self._last_emergency_result = None
        logger.info("MTMCircuitBreaker: reset for new trading day")
