"""Pure, bounded redacted service-connection audit contracts."""

import re
from dataclasses import dataclass
from uuid import UUID

from .service_connections import ServiceConnectionRef


def _safe_reference(value: object) -> str:
    if type(value) is not str or not re.fullmatch(r"[A-Za-z0-9_.:@-]{1,256}", value):
        raise ValueError("invalid actor reference")
    return value


@dataclass(frozen=True, slots=True)
class ConnectionActorContext:
    """Trusted actor and one-way session binding supplied by composition.

    Composition must derive the binding with its private session-keyed MAC;
    neither the JSON request nor a raw JWT/JTI is accepted as this context.
    """

    actor: str
    session_binding: str

    def __post_init__(self) -> None:
        _safe_reference(self.actor)
        if type(self.session_binding) is not str or not re.fullmatch(r"session:[0-9a-f]{64}", self.session_binding):
            raise ValueError("invalid session binding")


@dataclass(frozen=True, slots=True)
class RouteMutationAttempt:
    """Pre-domain attempt: invalid inputs never receive invented identities."""

    route_template: str
    method: str
    authentication_class: str
    outcome: str
    actor: str | None = None
    connection_ref: ServiceConnectionRef | None = None

    def __post_init__(self) -> None:
        if self.route_template not in {
            "/ft-api/v1/services/connections",
            "/ft-api/v1/services/connections/{connection_id}",
        }:
            raise ValueError("invalid route template")
        if self.method not in {"POST", "PATCH", "DELETE"}:
            raise ValueError("invalid mutation method")
        if self.authentication_class not in {"anonymous", "authenticated", "invalid"}:
            raise ValueError("invalid authentication class")
        if self.outcome not in {"accepted", "rejected", "failed"}:
            raise ValueError("invalid route outcome")
        if self.actor is not None:
            _safe_reference(self.actor)
        if self.connection_ref is not None and type(self.connection_ref) is not ServiceConnectionRef:
            raise ValueError("invalid connection reference")


@dataclass(frozen=True, slots=True)
class ConnectionMutationAudit:
    """Safe immutable outbox event; sinks deduplicate its stable event ID."""

    event_id: UUID
    operation: str
    connection_ref: ServiceConnectionRef
    actor: str
    session_binding: str | None
    expected_epoch: int
    before_epoch: int
    after_epoch: int
    outcome: str
    failure_class: str | None

    def __post_init__(self) -> None:
        if type(self.event_id) is not UUID or self.event_id.version != 4:
            raise ValueError("invalid audit event")
        if self.operation not in {"create", "update", "delete"}:
            raise ValueError("invalid audit operation")
        if type(self.connection_ref) is not ServiceConnectionRef:
            raise ValueError("invalid audit reference")
        if self.actor == "service-connection-recovery":
            if self.session_binding is not None:
                raise ValueError("invalid recovery principal")
        else:
            ConnectionActorContext(self.actor, self.session_binding)
        for value in (self.expected_epoch, self.before_epoch, self.after_epoch):
            if type(value) is not int or not 0 <= value <= (1 << 63) - 1:
                raise ValueError("invalid audit epoch")
        if self.outcome not in {"prepared", "succeeded", "failed", "recovered"}:
            raise ValueError("invalid audit outcome")
        if self.failure_class not in {None, "transaction_rolled_back", "revision_conflict", "store_unavailable"}:
            raise ValueError("invalid audit failure class")

    def to_dict(self) -> dict[str, object]:
        """Return only the exact safe outbox schema."""
        return {
            "event_id": str(self.event_id),
            "operation": self.operation,
            "connection_ref": self.connection_ref.to_dict(),
            "actor": self.actor,
            "session_binding": self.session_binding,
            "expected_epoch": self.expected_epoch,
            "before_epoch": self.before_epoch,
            "after_epoch": self.after_epoch,
            "outcome": self.outcome,
            "failure_class": self.failure_class,
        }
