"""Invocation-local writer correspondence on the existing signed router path.

These receipts are not request DTOs or authority. Only the active verified router
frame can transfer one to the lifecycle transaction. No process-wide registry or
new SafetyContext fields are introduced. Missing native dates remain unknown.
"""
from __future__ import annotations

import hashlib
import json
from collections.abc import Iterator
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import asdict
from typing import Any
from uuid import UUID, uuid4

from flinttrade_core.exceptions import SafetyBypassError

_ACTIVE: ContextVar[object | None] = ContextVar("native_writer_frontier", default=None)


class NativeWriterSource:
    """Opaque retained facts; construction alone cannot establish correspondence."""

    __slots__ = ("facts_json", "payload_json", "request", "session", "adapter", "preparation", "attempt_id",
                 "native_scope_json", "workspace_path")
    facts_json: str
    payload_json: str
    request: Any
    session: Any
    adapter: Any
    preparation: Any
    attempt_id: str | None
    native_scope_json: str | None
    workspace_path: Any

    def __init__(self) -> None:
        raise TypeError("Native writer facts are issued only at the verified router frontier")

    def __reduce_ex__(self, protocol: int) -> Any:
        raise TypeError("native_writer_source_not_serialisable")


def _json(value: Any) -> str:
    def default(item: Any) -> str:
        if type(item) is UUID:
            return str(item)
        raise TypeError("noncanonical writer observation")
    return json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False, default=default)


@contextmanager
def _verified_writer_frontier(
    router: Any, session: Any, adapter: Any, order: Any, request: Any, safety: Any, pin: Any,
) -> Iterator[NativeWriterSource | None]:
    """Retain actual managed ownership after normal verification and consumption.

    Raw legacy sessions intentionally receive no historical native attribution.
    The provider/registry authenticates the retained handle, not its DTO shape.
    """
    from flinttrade_gateway.registry import ConnectedRegistrySession
    from flinttrade_gateway.router import _canonical_json
    from flinttrade_gateway.session_provider import AuthenticatingSessionProvider

    provider = router._session_provider
    if type(provider) is not AuthenticatingSessionProvider or type(session) is not ConnectedRegistrySession:
        yield None
        return
    if (provider._workspace_path is None
            or router.backend_lease_proof.workspace_path != provider._workspace_path.resolve()):
        raise SafetyBypassError("Historical writer backend workspace mismatch")
    authority = provider.current_authority_for(session.selector)
    provider._registry.client_for_connected_session(session, current_authority=authority)
    if not safety.verify(order, request, session.selector.adapter_id, session.selector.account_id):
        raise SafetyBypassError("Historical writer source does not match signed intent")
    payload_json = _canonical_json(order)
    intent = json.loads(payload_json)
    preparation = pin.preparation if pin is not None else None
    prepared = None
    segment = None
    if preparation is not None:
        from flinttrade_gateway.brokers.dhan import DhanOrderPreparation
        from flinttrade_gateway.brokers.kotakneo import KotakOrderPreparation
        if type(preparation) not in (DhanOrderPreparation, KotakOrderPreparation) or preparation._owner is not adapter:
            raise SafetyBypassError("Historical writer preparation owner mismatch")
        # This uses only the captured receipt, never another resolver call.
        if json.loads(preparation.intent_json) != intent:
            raise SafetyBypassError("Historical writer full intent mismatch")
        prepared = {"identity": uuid4().hex, "intent_json": preparation.intent_json,
                    "wire_json": preparation.wire_json, "contract": preparation.contract_evidence(),
                    "tag": preparation.tag}
        segment = preparation.sdk_kwargs().get("exchange_segment")
    elif pin is not None:
        observed = json.loads(pin.observation_json)
        prepared = {"identity": uuid4().hex, "intent_json": payload_json, "observation": observed}
        if type(observed) is dict:
            segment = observed.get("broker_exchange_segment")
    variety = intent.get("variety", "regular")
    source = object.__new__(NativeWriterSource)
    source.payload_json, source.request = payload_json, request
    source.session, source.adapter, source.preparation = session, adapter, preparation
    source.attempt_id = None
    source.native_scope_json = None
    source.workspace_path = provider._workspace_path.resolve()
    source.facts_json = _json({
        "invocation_id": uuid4().hex,
        "selector": asdict(session.selector),
        "session_version": asdict(session.version),
        "provider_account_id": session.account_id,
        "intent": intent,
        "signed_intent_hash": safety.order_hash,
        "gate_id_hash": hashlib.sha256(safety.gate_id.encode()).hexdigest(),
        "backend_incarnation": safety.backend_incarnation,
        "adapter_identity": {"router_generation": router._router_generation,
                             "instance_ref": str(id(adapter)),
                             "type": type(adapter).__module__ + "." + type(adapter).__qualname__},
        "preparation": prepared,
        "native_segment": segment,
        "resource_family": "ordinary" if variety in ("regular", "", "amo", "iceberg") else None,
        "resource_id": None,
        "leg": None,
        "native_order_date": None,
        "native_order_date_source": None,
    })
    token = _ACTIVE.set(source)
    try:
        yield source
    finally:
        _ACTIVE.reset(token)


def prepared_facts(source: object, *, adapter_id: str, account_id: str, operation: str,
                   request_context: Any, payload: Any, attempt_id: str) -> dict[str, Any]:
    """Accept only the active verified frame, once, for this exact transaction.

    Args:
        source: The actual opaque invocation receipt, not a constructed DTO.
        adapter_id: Exact selected adapter.
        account_id: Exact public alias.
        operation: The already verified router operation.
        request_context: Original authenticated caller object.
        payload: The complete canonical signed intent.
        attempt_id: Identifier allocated by the existing lifecycle transaction.

    Returns:
        Detached historically knowable facts, retaining unknown native dates.

    Raises:
        ValueError: If the current frame, receipt or signed correspondence differs.
    """
    from flinttrade_gateway.router import _canonical_json

    if (type(source) is not NativeWriterSource or _ACTIVE.get() is not source
            or source.attempt_id is not None or source.request is not request_context
            or source.payload_json != _canonical_json(payload) or operation != "place_order"):
        raise ValueError("active verified native writer source required")
    facts = json.loads(source.facts_json)
    if facts["selector"] != {"adapter_id": adapter_id, "account_id": account_id}:
        raise ValueError("native writer selector mismatch")
    source.attempt_id = attempt_id
    return {"kind": "prepared", "attempt_id": attempt_id, "facts": facts}


@contextmanager
def _acknowledgement_frontier(source: NativeWriterSource, attempt_id: str, result: Any) -> Iterator[None]:
    """Keep late per-call ACK correspondence, even after session retirement."""
    token = _ACTIVE.set((source, attempt_id, result))
    try:
        yield
    finally:
        _ACTIVE.reset(token)


def acknowledged_facts(source: object, attempt_id: str, result: Any) -> dict[str, Any]:
    """Detach the independently observed full identity set from this invocation.

    Args:
        source: Original retained invocation receipt.
        attempt_id: Original durable attempt identifier.
        result: Actual per-call scalar or recognised typed native ACK.

    Returns:
        Detached exact acknowledged ID set; no inferred execution or date.

    Raises:
        ValueError: If the active completion frame or native identity set is invalid.
    """
    from flinttrade_gateway.router import placement_acknowledgement_fields

    active = _ACTIVE.get()
    if (type(source) is not NativeWriterSource or type(active) is not tuple
            or active[0] is not source or active[1] != attempt_id or active[2] is not result
            or source.attempt_id != attempt_id):
        raise ValueError("active native acknowledgement frontier required")
    from .native_acknowledgement import UncertainNativeAcknowledgement

    if type(result) is UncertainNativeAcknowledgement:
        return {"kind": "uncertain_acknowledgement", "attempt_id": attempt_id,
                "invocation_id": json.loads(source.facts_json)["invocation_id"],
                "observed_order_ids": list(result.observed_order_ids), "full_set": "unverified"}
    fields = placement_acknowledgement_fields(result)
    ids = fields.get("order_ids") if fields else [result] if type(result) is str else None
    if (type(ids) not in (list, tuple) or not ids or len(set(ids)) != len(ids)
            or any(type(value) is not str or not value or value != value.strip()
                   or not value.isprintable() or any(char.isspace() for char in value) for value in ids)):
        raise ValueError("native acknowledgement identity set is unavailable")
    record = {"kind": "acknowledged", "attempt_id": attempt_id,
              "invocation_id": json.loads(source.facts_json)["invocation_id"], "order_ids": list(ids)}
    if source.native_scope_json is not None:
        observed = json.loads(source.native_scope_json)
        # Preserve the actual full ACK even if independent scope disagrees.
        record["native_scope_observation"] = observed
        record["native_scope_ack_matches"] = set(observed["order_ids"]) == set(ids)
    return record
