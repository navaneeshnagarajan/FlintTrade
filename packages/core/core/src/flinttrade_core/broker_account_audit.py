"""Redacted, stable account audit evidence and verified durable delivery."""

from __future__ import annotations

import hashlib
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from typing import Any
from uuid import UUID

from .account_lifecycle_contracts import (
    AccountContractError,
    AccountMutationKind,
    AccountOperationStage,
    _digest,
    _uuid,
    canonical_account_json,
)
from .broker_identity import INT64_MAX

ACCOUNT_AUDIT_EVENT_TYPE = "BROKER_ACCOUNT_MUTATION_SETTLED"
_TERMINAL = frozenset((
    AccountOperationStage.COMMITTED, AccountOperationStage.REJECTED,
    AccountOperationStage.AUTHENTICATION_UNKNOWN, AccountOperationStage.BLOCKED,
))


class AccountAuditUnavailable(ValueError):
    """Audit delivery failed without exposing a sink or account detail."""

    def __init__(self) -> None:
        super().__init__("account_audit_unavailable")


@dataclass(frozen=True, slots=True)
class AccountMutationAudit:
    """Only keyed references and durable terminal evidence leave the vault."""

    event_id: UUID
    operation_ref: str
    selector_ref: str
    actor_ref: str
    session_ref: str
    kind: AccountMutationKind
    state: AccountOperationStage
    expected_credential_generation: int
    credential_generation: int | None
    expected_workspace_generation: int
    workspace_generation: int | None
    expected_broker_generation: int
    broker_generation: int | None

    def __post_init__(self) -> None:
        _uuid(self.event_id)
        for value in (self.operation_ref, self.selector_ref, self.actor_ref, self.session_ref):
            _digest(value)
        if type(self.kind) is not AccountMutationKind or type(self.state) is not AccountOperationStage:
            raise AccountContractError
        if self.state not in _TERMINAL:
            raise AccountContractError
        expected = (self.expected_credential_generation, self.expected_workspace_generation,
                    self.expected_broker_generation)
        committed = (self.credential_generation, self.workspace_generation, self.broker_generation)
        for value in expected:
            if type(value) is not int or not 0 <= value <= INT64_MAX:
                raise AccountContractError
        for value in committed:
            if value is not None and (type(value) is not int or not 0 <= value <= INT64_MAX):
                raise AccountContractError
        if self.state is AccountOperationStage.COMMITTED:
            if any(value is None for value in committed):
                raise AccountContractError
            if (self.credential_generation != self.expected_credential_generation + 1
                    or self.workspace_generation <= self.expected_workspace_generation
                    or self.broker_generation < self.expected_broker_generation):
                raise AccountContractError
        elif any(value is not None for value in committed):
            raise AccountContractError

    def _evidence(self) -> dict[str, object]:
        return {
            "schema": 1,
            "operation_ref": self.operation_ref,
            "selector_ref": self.selector_ref,
            "actor_ref": self.actor_ref,
            "session_ref": self.session_ref,
            "kind": self.kind.value,
            "state": self.state.value,
            "expected_credential_generation": self.expected_credential_generation,
            "credential_generation": self.credential_generation,
            "expected_workspace_generation": self.expected_workspace_generation,
            "workspace_generation": self.workspace_generation,
            "expected_broker_generation": self.expected_broker_generation,
            "broker_generation": self.broker_generation,
        }

    def fields(self) -> dict[str, object]:
        """Detach the exact safe fields, excluding the logger's reserved ID."""
        self.__post_init__()
        evidence = self._evidence()
        encoded = canonical_account_json({"event_id": str(self.event_id), **evidence})
        evidence["evidence_digest"] = hashlib.sha256(("account-audit/v1\0" + encoded).encode()).hexdigest()
        return evidence

    def to_dict(self) -> dict[str, object]:
        """Serialise the safe outbox schema with its stable event identity."""
        return {"event_id": str(self.event_id), **self.fields()}

    @classmethod
    def from_dict(cls, value: Mapping[str, object]) -> AccountMutationAudit:
        """Refuse alternate, extended or inconsistent outbox evidence."""
        try:
            body = dict(value)
            event_id = body.pop("event_id")
            digest = body.pop("evidence_digest")
            schema = body.pop("schema")
            if type(schema) is not int or schema != 1 or type(event_id) is not str:
                raise AccountContractError
            identifier = UUID(event_id)
            if str(identifier) != event_id:
                raise AccountContractError
            body["kind"] = AccountMutationKind(body["kind"])
            body["state"] = AccountOperationStage(body["state"])
            result = cls(event_id=identifier, **body)
            if result.fields()["evidence_digest"] != digest:
                raise AccountContractError
            return result
        except (TypeError, ValueError, KeyError):
            raise AccountContractError from None


def build_account_audit_sink(audit_logger: Any) -> Callable[[AccountMutationAudit], UUID]:
    """Accept delivery only after exact-ID, full-evidence chain verification."""

    def deliver(event: AccountMutationAudit) -> UUID:
        try:
            if type(event) is not AccountMutationAudit:
                raise AccountAuditUnavailable
            fields = event.fields()
            identifier = str(event.event_id)
            acknowledgement = audit_logger.log_idempotent_event(
                ACCOUNT_AUDIT_EVENT_TYPE, event_id=identifier, fields=fields,
            )
            if type(acknowledgement) is not str or acknowledgement != identifier:
                raise AccountAuditUnavailable
            if audit_logger.verify_idempotent_event_receipt(
                ACCOUNT_AUDIT_EVENT_TYPE, event_id=identifier, fields=fields,
            ) is not True:
                raise AccountAuditUnavailable
            return event.event_id
        except Exception:
            raise AccountAuditUnavailable from None

    return deliver
