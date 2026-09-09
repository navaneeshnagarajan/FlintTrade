"""Neutral registry version contracts; no provider or mutation implementation."""

from dataclasses import dataclass
from uuid import RFC_4122, UUID

from .broker_identity import INT64_MAX, BrokerSelector, CredentialVersion, _validate_selector
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
