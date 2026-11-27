"""Immutable Kotak observations; issuance and invocation remain with the adapter.

A receipt is not a grant, native date, account qualification or callable wire
request. Only its issuing adapter can adopt the exact retained object.
"""
from __future__ import annotations

import json
import math
from dataclasses import dataclass
from types import SimpleNamespace
from typing import Any

from flinttrade_core.exceptions import UnsupportedCapabilityError


def intent_json(order: Any) -> str:
    """Detach complete canonical intent, never reconstruct it from SDK kwargs.

    Args:
        order: Canonical Order or legacy object with explicit primitive fields.

    Returns:
        Exact JSON intent including null/false values and canonical defaults.

    Raises:
        UnsupportedCapabilityError: Non-JSON or non-finite supplied intent.
    """
    from flinttrade_core.models import Order  # noqa: PLC0415

    def primitive(value: Any) -> Any:
        kind = type(value)
        if value is None or kind is str or kind is bool or kind is int:
            return value
        if kind is float and math.isfinite(value):
            return value
        if kind is list:
            return [primitive(item) for item in value]
        if kind is dict and all(type(key) is str for key in value):
            return {key: primitive(item) for key, item in value.items()}
        raise ValueError

    try:
        values = Order.model_dump(order, mode="json") if type(order) is Order else vars(order)
        return json.dumps(primitive(values), sort_keys=True, allow_nan=False)
    except (TypeError, ValueError, OverflowError, RecursionError):
        raise UnsupportedCapabilityError("Kotak preparation requires explicit JSON intent",
            broker_id="kotakneo") from None


def snapshot_order(order: Any) -> tuple[Any, str]:
    """Return detached proposal values and their full intent identity.

    Args:
        order: Canonical or explicit legacy proposal.

    Returns:
        A separate canonical Order or primitive namespace, and its JSON identity.
    """
    from flinttrade_core.models import Order  # noqa: PLC0415

    intent = intent_json(order)
    values = json.loads(intent)
    snapshot = Order.model_validate(values) if type(order) is Order else SimpleNamespace(**values)
    if intent_json(snapshot) != intent:
        raise UnsupportedCapabilityError("Kotak intent changed during capture", broker_id="kotakneo")
    return snapshot, intent


@dataclass(frozen=True, slots=True, eq=False, weakref_slot=True)
class KotakOrderPreparation:
    """Read-only captured observations, adopted only by actual issuance identity.

    Attributes:
        _owner: Exact issuing adapter, not an authority token.
        intent_json: Complete detached canonical proposal.
        wire_json: Exact installed SDK keyword arguments.
        tag: Exact captured native tag or its omission.
        _contract_json: Detached exact listed source and native contract evidence.
    """
    _owner: object
    intent_json: str
    wire_json: str
    tag: str | None
    _contract_json: str

    def sdk_kwargs(self) -> dict[str, Any]:
        """Return detached captured kwargs, never a full-intent substitute."""
        return json.loads(self.wire_json)

    def contract_evidence(self) -> dict[str, Any]:
        """Return detached listing/source facts without another resolver lookup."""
        return json.loads(self._contract_json)

    def __reduce_ex__(self, protocol: int) -> Any:
        """Refuse serialisation as a means of transferring adoption authority."""
        raise TypeError("Kotak preparation is request-local and not serialisable")


@dataclass(frozen=True, slots=True)
class _SessionCapture:
    """Private identity operands; never emitted as receipt metadata."""
    session: Any
    client: Any
    values: tuple[Any, ...]


def session_values(session: Any) -> tuple[Any, ...]:
    """Observe exact native session/account/version operands without a provider lookup."""
    return (session.account_id, session.adapter_id, session.access_token, session.expires_at,
            session.algo_id, session.read_only_until_at, getattr(session, "version", None))


@dataclass(frozen=True, slots=True)
class _PreparationCapture:
    """Adapter-owned immutable issuance record, independent of exposed metadata."""
    intent: str
    wire: str
    tag: str | None
    evidence: str
    resolver: Any
    generation: int
    contract: Any
    session: _SessionCapture | None
