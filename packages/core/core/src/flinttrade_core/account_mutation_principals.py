"""Trusted composition seams for sealed, narrowly bounded account principals."""

from __future__ import annotations

import re
from collections.abc import Callable
from dataclasses import dataclass
from uuid import UUID

from .account_mutation_contracts import (
    _PRINCIPAL_SEAL,
    _PRINCIPALS,
    AccountMutationRequest,
    AccountOperation,
    AccountPrincipal,
    AccountPrincipalDenied,
    InternalMigrationPrincipal,
    OpenAlgoMigrationPrincipal,
    OperatorSessionPrincipal,
    ScheduledRotationPrincipal,
    StartupReconnectPrincipal,
    require_uuid4,
)
from .account_mutation_locks import OperationLockToken, require_operation_lock
from .broker_identity import BrokerSelector
from .operator_session import VerifiedOperatorSession


@dataclass(frozen=True)
class BoundedAccountClaim:
    """Trusted ledger/claim reader output; not accepted from public requests."""

    installation_id: UUID
    operation_id: UUID
    selector: BrokerSelector
    claim_ref: UUID
    kind: type[ScheduledRotationPrincipal | InternalMigrationPrincipal | OpenAlgoMigrationPrincipal | StartupReconnectPrincipal]


class AccountPrincipalIssuer:
    """Composition injects the existing full-session verifier, never a flag."""

    def __init__(self, verify_operator: Callable[[], VerifiedOperatorSession]) -> None:
        self._verify_operator = verify_operator

    def operator(self, *, required_scope: str = "admin.accounts.write") -> OperatorSessionPrincipal:
        """Verify a live full session and retain only owner-keyed references."""
        try:
            evidence = self._verify_operator()
            if (
                required_scope not in {"admin.accounts.read", "admin.accounts.write"}
                or type(evidence) is not VerifiedOperatorSession
                or not re.fullmatch(r"operator:[0-9a-f]{64}", evidence.actor_ref)
                or not re.fullmatch(r"session:[0-9a-f]{64}", evidence.session_binding)
                or type(evidence.scopes) is not tuple
                or required_scope not in evidence.scopes
            ):
                raise AccountPrincipalDenied
            return OperatorSessionPrincipal(
                _PRINCIPAL_SEAL, actor_ref=evidence.actor_ref,
                session_binding=evidence.session_binding, scopes=evidence.scopes,
            )
        except Exception:
            raise AccountPrincipalDenied from None

    @staticmethod
    def bounded(
        token: OperationLockToken, load_claim: Callable[[], BoundedAccountClaim],
    ) -> AccountPrincipal:
        """Mint only while real ownership holds and the trusted ledger matches."""
        token = require_operation_lock(token)
        try:
            claim = load_claim()
            allowed = {
                ScheduledRotationPrincipal: AccountOperation.ROTATE_CREDENTIALS,
                InternalMigrationPrincipal: AccountOperation.ADOPT_LEGACY,
                OpenAlgoMigrationPrincipal: AccountOperation.CONNECT,
                StartupReconnectPrincipal: AccountOperation.RECONNECT,
            }
            if (
                type(claim) is not BoundedAccountClaim or claim.kind not in allowed
                or claim.installation_id != token._installation.installation_id
                or type(claim.selector) is not BrokerSelector
                or (claim.kind is OpenAlgoMigrationPrincipal and claim.selector != BrokerSelector("openalgo", "default"))
            ):
                raise AccountPrincipalDenied
            require_uuid4(claim.operation_id)
            require_uuid4(claim.claim_ref)
            claim.selector.__post_init__()
            return claim.kind(
                _PRINCIPAL_SEAL, actor_ref=claim.kind.__name__, session_binding=None,
                scopes=(allowed[claim.kind].value,), operation_id=claim.operation_id,
                selector=claim.selector, claim_ref=str(claim.claim_ref),
            )
        except Exception:
            raise AccountPrincipalDenied from None


def validate_principal(request: AccountMutationRequest) -> AccountPrincipal:
    """Enforce the sealed variant's exact method, operation and selector."""
    principal = request.principal
    if type(principal) not in {OperatorSessionPrincipal, ScheduledRotationPrincipal, InternalMigrationPrincipal,
                              OpenAlgoMigrationPrincipal, StartupReconnectPrincipal} or principal not in _PRINCIPALS:
        raise AccountPrincipalDenied
    if type(principal) is OperatorSessionPrincipal:
        if "admin.accounts.write" not in principal.scopes:
            raise AccountPrincipalDenied
        return principal
    operations = {
        ScheduledRotationPrincipal: AccountOperation.ROTATE_CREDENTIALS,
        InternalMigrationPrincipal: AccountOperation.ADOPT_LEGACY,
        OpenAlgoMigrationPrincipal: AccountOperation.CONNECT,
        StartupReconnectPrincipal: AccountOperation.RECONNECT,
    }
    if (
        operations.get(type(principal)) != request.operation
        or principal.operation_id != request.operation_id or principal.selector != request.selector
    ):
        raise AccountPrincipalDenied
    return principal
