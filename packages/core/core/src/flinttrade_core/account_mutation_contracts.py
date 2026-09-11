"""Neutral registry version contracts; no provider or mutation implementation."""

from dataclasses import dataclass, field
from enum import StrEnum
from typing import Literal
from uuid import RFC_4122, UUID
from weakref import WeakSet

from .broker_identity import INT64_MAX, BrokerSelector, CredentialVersion, QuarantineRef, _validate_selector
from .workspace_migrations import BrokerWorkspaceVersion, WorkspaceVersion


class RegistryVersionValidationError(ValueError):
    """Malformed registry authority."""

    def __init__(self) -> None:
        super().__init__("registry_version_invalid")


class RegistryCapabilityError(RuntimeError):
    """An opaque ownership capability is invalid."""

    def __init__(self) -> None:
        super().__init__("registry_capability_invalid")


class RegistryVersionConflict(RuntimeError):
    """Complete comparison failed; optionally carries an opaque retirement."""

    def __init__(self, *, retirement_receipt: object | None = None) -> None:
        super().__init__("registry_version_conflict")
        self.retirement_receipt = retirement_receipt


class RegistrySessionUnavailable(RuntimeError):
    """No authorised connected session is available."""

    def __init__(self) -> None:
        super().__init__("registry_session_unavailable")


class BrokerAccountAmbiguousError(LookupError):
    """A bare account matches multiple exact selectors."""

    def __init__(self) -> None:
        super().__init__("broker_account_ambiguous")


def validate_workspace_versions(workspace: WorkspaceVersion, broker: BrokerWorkspaceVersion) -> None:
    """Validate canonical, positive independent counters under one workspace."""
    if type(workspace) is not WorkspaceVersion or type(broker) is not BrokerWorkspaceVersion:
        raise RegistryVersionValidationError
    for value in (workspace, broker):
        if type(value.instance_id) is not UUID or type(value.generation) is not int:
            raise RegistryVersionValidationError
        if not 1 <= value.generation <= INT64_MAX:
            raise RegistryVersionValidationError
    if workspace.instance_id != broker.instance_id:
        raise RegistryVersionValidationError


@dataclass(frozen=True)
class RegistrySelectorVersion:
    """Exact in-memory state, including unseen zero and retained tombstones."""

    selector: BrokerSelector
    registry_incarnation: UUID
    generation: int
    present: bool

    def __post_init__(self) -> None:
        _validate_selector(self.selector)
        if (
            type(self.registry_incarnation) is not UUID
            or self.registry_incarnation.version != 4
            or self.registry_incarnation.variant != RFC_4122
            or type(self.generation) is not int
            or not 0 <= self.generation <= INT64_MAX
            or type(self.present) is not bool
            or (self.generation == 0 and self.present)
        ):
            raise RegistryVersionValidationError


@dataclass(frozen=True)
class SessionVersion:
    """Published managed session bound to final durable build authority."""

    selector: BrokerSelector
    registry_version: RegistrySelectorVersion
    credential_version: CredentialVersion
    workspace_version: WorkspaceVersion
    broker_workspace_version: BrokerWorkspaceVersion

    def __post_init__(self) -> None:
        _validate_selector(self.selector)
        if (
            type(self.registry_version) is not RegistrySelectorVersion
            or type(self.credential_version) is not CredentialVersion
        ):
            raise RegistryVersionValidationError
        self.registry_version.__post_init__()
        self.credential_version.__post_init__()
        if (
            self.registry_version.selector != self.selector
            or self.credential_version.selector != self.selector
            or not self.registry_version.present
            or self.credential_version.generation == 0
        ):
            raise RegistryVersionValidationError
        validate_workspace_versions(self.workspace_version, self.broker_workspace_version)


class AccountMutationValidationError(ValueError):
    """An invalid request; values and secrets never appear in the message."""

    def __init__(self) -> None:
        super().__init__("account_mutation_invalid")


class AccountMutationConflict(RuntimeError):
    """An admitted immutable request or authority expectation conflicts."""

    status_code = 409

    def __init__(self) -> None:
        super().__init__("account_mutation_conflict")


class AccountRecoveryUnavailable(RuntimeError):
    """Durable lineage or ownership cannot safely authorise more work."""

    def __init__(self) -> None:
        super().__init__("account_recovery_unavailable")


class AccountPrincipalDenied(RuntimeError):
    """No live principal permits this exact operation and target."""

    def __init__(self) -> None:
        super().__init__("account_principal_denied")


def require_uuid4(value: object) -> UUID:
    """Require an actual UUID4 value, including the RFC variant."""
    if type(value) is not UUID or value.version != 4 or value.variant != RFC_4122:
        raise AccountMutationValidationError
    return value


def parse_idempotency_key(value: object) -> UUID:
    """HTTP keys are canonical lower-case, hyphenated UUID4 strings."""
    if type(value) is not str:
        raise AccountMutationValidationError
    try:
        parsed = require_uuid4(UUID(value))
    except (ValueError, AttributeError):
        raise AccountMutationValidationError from None
    if str(parsed) != value:
        raise AccountMutationValidationError
    return parsed


def require_revision(value: object, *, unseen: bool = False) -> int:
    """Booleans, overflow and zero-valued retained revisions fail closed."""
    if type(value) is not int or not (0 if unseen else 1) <= value <= INT64_MAX:
        raise AccountMutationValidationError
    return value


class AccountOperation(StrEnum):
    CONNECT = "connect"
    RECONNECT = "reconnect"
    DELETE = "delete"
    SET_EXECUTION_DEFAULT = "set_execution_default"
    ROTATE_CREDENTIALS = "rotate_credentials"
    BEGIN_AUTH_FLOW = "begin_auth_flow"
    COMPLETE_AUTH_FLOW = "complete_auth_flow"
    ADOPT_LEGACY = "adopt_legacy"


class MutationPhase(StrEnum):
    PREPARED = "prepared"
    ROUTER_DRAINED = "router_drained"
    EXTERNAL_INVOCATION_PREPARED = "external_invocation_prepared"
    EXTERNAL_INVOKED = "external_invoked"
    CANDIDATE_STAGED = "candidate_staged"
    PROVIDER_REJECTED = "provider_rejected"
    EXTERNAL_UNKNOWN = "external_unknown"
    DURABLE_COMMIT_PREPARED = "durable_commit_prepared"
    WORKSPACE_COMMITTED = "workspace_committed"
    VAULT_COMMITTED = "vault_committed"
    PROJECTION_COMMITTED = "projection_committed"
    DURABLE_COMMITTED = "durable_committed"
    SOURCE_RETIRED = "source_retired"
    REGISTRY_PUBLISHED = "registry_published"
    FACADE_PUBLISHED = "facade_published"
    ROUTER_REBUILT = "router_rebuilt"
    COMMITTED = "committed"
    COMMITTED_DISCONNECTED = "committed_disconnected"


class AuthFlowState(StrEnum):
    PENDING = "pending"
    COMPLETING = "completing"
    FLOW_PENDING = "flow_pending"
    CHALLENGE_STAGED = "challenge_staged"
    COMPLETED = "completed"
    PROVIDER_REJECTED = "provider_rejected"
    FLOW_DENIED = "flow_denied"
    EXTERNAL_UNKNOWN = "external_unknown"
    IDENTITY_MISMATCH = "identity_mismatch"
    EXPIRED = "expired"
    CANCELLED = "cancelled"


AuthFlowKind = Literal["oauth", "otp", "otp_multistep"]
AuthFlowAction = Literal["complete", "status", "cancel", "reconcile", "claim_callback"]


@dataclass(frozen=True)
class AuthFlowRef:
    """An exact durable flow, never a selector fabricated for an unknown account."""

    adapter_id: str
    flow_id: UUID
    flow_store_incarnation: UUID
    flow_kind: AuthFlowKind
    flow_version: int
    expected_account_id: str | None

    def __post_init__(self) -> None:
        try:
            BrokerSelector(self.adapter_id, self.expected_account_id or "Validation")
            if self.expected_account_id == "":
                raise AccountMutationValidationError
            require_uuid4(self.flow_id)
            require_uuid4(self.flow_store_incarnation)
            require_revision(self.flow_version)
            if self.flow_kind not in {"oauth", "otp", "otp_multistep"}:
                raise AccountMutationValidationError
        except (ValueError, TypeError):
            raise AccountMutationValidationError from None


@dataclass(frozen=True)
class AccountAuthoritySnapshot:
    """Frozen full workspace and exact sorted durable/ephemeral authorities."""

    workspace_version: WorkspaceVersion | None
    vault_incarnation: UUID
    registry_incarnation: UUID
    credential_versions: tuple[CredentialVersion, ...]
    registry_versions: tuple[RegistrySelectorVersion, ...]

    def __post_init__(self) -> None:
        require_uuid4(self.vault_incarnation)
        require_uuid4(self.registry_incarnation)
        if self.workspace_version is not None:
            if type(self.workspace_version) is not WorkspaceVersion:
                raise AccountMutationValidationError
            require_uuid4(self.workspace_version.instance_id)
            require_revision(self.workspace_version.generation)
        for values, expected_type, incarnation, attribute in (
            (self.credential_versions, CredentialVersion, self.vault_incarnation, "vault_incarnation"),
            (self.registry_versions, RegistrySelectorVersion, self.registry_incarnation, "registry_incarnation"),
        ):
            if type(values) is not tuple or any(type(value) is not expected_type for value in values):
                raise AccountMutationValidationError
            selectors = [value.selector for value in values]
            if selectors != sorted(set(selectors)):
                raise AccountMutationValidationError
            for value in values:
                value.__post_init__()
                if getattr(value, attribute) != incarnation:
                    raise AccountMutationValidationError
        if [v.selector for v in self.credential_versions] != [v.selector for v in self.registry_versions]:
            raise AccountMutationValidationError


_PRINCIPAL_SEAL = object()
_PRINCIPALS: WeakSet = WeakSet()


class _AccountPrincipal:
    """Opaque trusted-issuer output, never a deserialised HTTP identity."""

    def __init__(
        self, seal: object, *, actor_ref: str, session_binding: str | None,
        scopes: tuple[str, ...], operation_id: UUID | None = None,
        selector: BrokerSelector | None = None, claim_ref: str | None = None,
    ) -> None:
        if seal is not _PRINCIPAL_SEAL:
            raise AccountPrincipalDenied
        self.actor_ref = actor_ref
        self.session_binding = session_binding
        self.scopes = scopes
        self.operation_id = operation_id
        self.selector = selector
        self.claim_ref = claim_ref
        _PRINCIPALS.add(self)
        self._sealed = True

    def __setattr__(self, name: str, value: object) -> None:
        if getattr(self, "_sealed", False):
            raise AccountPrincipalDenied
        object.__setattr__(self, name, value)

    def __reduce__(self) -> object:
        raise AccountPrincipalDenied


class OperatorSessionPrincipal(_AccountPrincipal):
    """A trusted full-session verifier has authenticated this operator."""


class ScheduledRotationPrincipal(_AccountPrincipal):
    """One persisted due-run claim and exact rotation child."""


class InternalMigrationPrincipal(_AccountPrincipal):
    """One installation-bound adoption operation."""


class OpenAlgoMigrationPrincipal(_AccountPrincipal):
    """One ledger-bound reserved OpenAlgo connection migration."""


class StartupReconnectPrincipal(_AccountPrincipal):
    """One recover-first managed-selector reconnect."""


AccountPrincipal = (
    OperatorSessionPrincipal | ScheduledRotationPrincipal | InternalMigrationPrincipal
    | OpenAlgoMigrationPrincipal | StartupReconnectPrincipal
)


@dataclass(frozen=True)
class AccountMutationRequest:
    """Immutable admitted input; the private envelope is never represented."""

    operation: AccountOperation
    operation_id: UUID
    idempotency_key: str
    authorities: AccountAuthoritySnapshot
    principal: AccountPrincipal = field(repr=False)
    selector: BrokerSelector | None = None
    adapter_id: str | None = None
    quarantine: QuarantineRef | None = None
    flow_ref: AuthFlowRef | None = None
    flow_action: AuthFlowAction = "complete"
    credential_action: Literal["preserve", "replace"] = "replace"
    private_input: bytes = field(default=b"", repr=False, compare=False)

    def __post_init__(self) -> None:
        if type(self.operation) is not AccountOperation or type(self.authorities) is not AccountAuthoritySnapshot:
            raise AccountMutationValidationError
        require_uuid4(self.operation_id)
        parse_idempotency_key(self.idempotency_key)
        self.authorities.__post_init__()
        if type(self.private_input) is not bytes or len(self.private_input) > 64 * 1024:
            raise AccountMutationValidationError
        if self.credential_action not in {"preserve", "replace"}:
            raise AccountMutationValidationError
        if self.selector is not None:
            _validate_selector(self.selector)
            if self.selector not in {v.selector for v in self.authorities.registry_versions}:
                raise AccountMutationValidationError
            if self.adapter_id is not None and self.adapter_id != self.selector.adapter_id:
                raise AccountMutationValidationError
        elif self.operation is AccountOperation.BEGIN_AUTH_FLOW:
            BrokerSelector(self.adapter_id, "Validation")
        elif self.operation is AccountOperation.COMPLETE_AUTH_FLOW:
            if type(self.flow_ref) is not AuthFlowRef:
                raise AccountMutationValidationError
        elif self.operation is not AccountOperation.DELETE or self.quarantine is None:
            raise AccountMutationValidationError
        if self.quarantine is not None:
            if type(self.quarantine) is not QuarantineRef or self.operation not in {
                AccountOperation.ADOPT_LEGACY, AccountOperation.DELETE,
            }:
                raise AccountMutationValidationError
            self.quarantine.__post_init__()
        if self.flow_ref is not None:
            self.flow_ref.__post_init__()
        if self.flow_action not in {"complete", "status", "cancel", "reconcile", "claim_callback"}:
            raise AccountMutationValidationError


@dataclass(frozen=True)
class OperationRef:
    """CAS handle bound to the journal incarnation and exact row revision."""

    operation_id: UUID
    store_incarnation: UUID
    revision: int

    def __post_init__(self) -> None:
        require_uuid4(self.operation_id)
        require_uuid4(self.store_incarnation)
        require_revision(self.revision)


@dataclass(frozen=True)
class AccountMutationResult:
    """Only redacted phase/version facts cross the mutation boundary."""

    reference: OperationRef
    phase: MutationPhase
    outcome: Literal["pending", "success", "conflict", "provider_rejected", "external_unknown", "internal_failure", "partial_batch"]
    selector: BrokerSelector | None
    authorities: AccountAuthoritySnapshot | None = None
    flow_ref: AuthFlowRef | None = None


@dataclass(frozen=True)
class RouteMutationAttempt:
    """Pre-domain failures have no fabricated operation or selector."""

    attempt_id: UUID
    reason: Literal["malformed", "missing_selector", "unknown_selector", "authentication_denied"]

    def __post_init__(self) -> None:
        require_uuid4(self.attempt_id)
        if self.reason not in {"malformed", "missing_selector", "unknown_selector", "authentication_denied"}:
            raise AccountMutationValidationError
