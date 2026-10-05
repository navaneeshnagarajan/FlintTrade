"""Owned broker-domain commitment and deterministic provider-free recovery.

The marker is a workspace decision, outside broker liveness. A matching
vault application is mandatory before short publication callbacks can run.
"""

from __future__ import annotations

import inspect
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING
from uuid import UUID

from . import secure_file
from .account_lifecycle_contracts import (
    _DATA_ROLES,
    AccountContractError,
    AccountMutationKind,
    AccountMutationReceipt,
    AccountOperationSnapshot,
    AccountOperationStage,
    BrokerAccountWitness,
    _uuid,
    broker_account_digest,
)
from .backend_instance import BackendLeaseProof, require_backend_lease_proof
from .broker_identity import BrokerSelector, CredentialVersion, _validate_selector, serialise_broker_selector
from .workspace_migrations import (
    WorkspaceSnapshot,
    _account_workspace_transaction,
    broker_workspace_version,
)

if TYPE_CHECKING:
    from flinttrade_gateway.account_transaction_store import AccountTransactionStore

_MARKER = "_broker_account_store"


class BrokerAccountWorkspaceUnavailable(ValueError):
    """Stable refusal; preserve foreign state and durable operation evidence."""

    def __init__(self) -> None:
        super().__init__("broker_account_workspace_unavailable")


@dataclass(frozen=True, slots=True)
class BrokerAccountPatch:
    """Exact native registration/data roles, removal or read-only demotion."""

    kind: AccountMutationKind
    selector: BrokerSelector
    data_roles: tuple[str, ...]
    read_only: bool | None

    def __post_init__(self) -> None:
        _validate_selector(self.selector)
        if (
            type(self.kind) is not AccountMutationKind
            or type(self.data_roles) is not tuple
            or any(type(role) is not str or role not in _DATA_ROLES for role in self.data_roles)
            or len(set(self.data_roles)) != len(self.data_roles)
            or self.kind is not AccountMutationKind.CONNECT
            and self.data_roles
            or (self.kind is AccountMutationKind.REMOVE and self.read_only is not None)
            or (self.kind is not AccountMutationKind.REMOVE and type(self.read_only) is not bool)
        ):
            raise AccountContractError

    def apply(self, config: Mapping[str, object]) -> dict[str, object]:
        """Return a detached patch without adding ACLs, defaults or fallbacks."""
        self.__post_init__()
        result = WorkspaceSnapshot(config, None).as_dict()
        try:
            brokers = result["brokers"]
            selector = serialise_broker_selector(self.selector)
            if self.kind is AccountMutationKind.CONNECT and selector not in brokers["registered"]:
                brokers["registered"].append(selector)
            if self.kind is AccountMutationKind.CONNECT:
                for role in self.data_roles:
                    brokers["data"][role] = selector
            if self.kind is AccountMutationKind.REMOVE:
                brokers["registered"] = [value for value in brokers["registered"] if value != selector]
                for role, value in brokers["data"].items():
                    if value == selector:
                        brokers["data"][role] = ""
                acls = brokers["account_acls"]
                adapter = acls.get(self.selector.adapter_id)
                if adapter is not None:
                    adapter.pop(self.selector.account_id, None)
                    if not adapter:
                        acls.pop(self.selector.adapter_id)
            if self.kind is AccountMutationKind.REMOVE or self.read_only:
                if brokers["execution"].get("default") == selector:
                    brokers["execution"]["default"] = ""
                brokers["failover"]["order"] = [value for value in brokers["failover"]["order"] if value != selector]
            return result
        except (KeyError, TypeError, AttributeError):
            raise BrokerAccountWorkspaceUnavailable from None


class BrokerAccountWorkspace:
    """One real backend owner participating in the vault/workspace protocol."""

    def __init__(self, path: Path, store: AccountTransactionStore, backend_proof: BackendLeaseProof) -> None:
        from flinttrade_gateway.account_transaction_store import AccountTransactionStore

        if type(store) is not AccountTransactionStore:
            raise BrokerAccountWorkspaceUnavailable
        self._path = Path(path).expanduser().resolve()
        self._proof = require_backend_lease_proof(backend_proof)
        self._store = store
        self._capability = store.owner_capability(backend_proof)
        store._require_workspace_capability(self._capability, self._path, backend_proof)

    def _locked[T](self, callback: Callable[..., T]) -> T:
        require_backend_lease_proof(self._proof)
        return _account_workspace_transaction(self._path, self._store, self._proof, callback)

    def _operation_locked[T](self, operation_id: UUID | None, callback: Callable[..., T]) -> T:
        try:
            return self._locked(callback)
        except Exception:
            # The durable attempt alone forbids any second CAS. When the
            # vault/owner remain valid, additionally retain the publication
            # fence even if workspace evidence is currently unreadable.
            try:
                operation = (
                    self._store.active_operation(self._capability)
                    if operation_id is None
                    else self._store.operation(operation_id)
                )
                if (
                    operation is not None
                    and operation.workspace_attempted
                    and not operation.workspace_conflicted
                    and operation.state in (AccountOperationStage.PLAN_READY, AccountOperationStage.COMMITTED)
                ):
                    self._store.mark_workspace_conflicted(operation.operation_id)
            except Exception:
                # Unavailable/invalid vault or revoked ownership cannot
                # authorise an evidence write. Retain the original refusal.
                pass
            raise

    @staticmethod
    def _marker(snapshot: WorkspaceSnapshot) -> BrokerAccountWitness:
        try:
            return BrokerAccountWitness.from_dict(snapshot.as_dict()[_MARKER])
        except (KeyError, ValueError, TypeError):
            raise BrokerAccountWorkspaceUnavailable from None

    @staticmethod
    def _assert_snapshot(snapshot: WorkspaceSnapshot, witness: BrokerAccountWitness) -> None:
        if (
            snapshot.version is None
            or snapshot.version.instance_id != witness.workspace_instance
            or snapshot.version.generation < witness.commit_workspace.generation
            or broker_workspace_version(snapshot) != witness.commit_broker_workspace
            or broker_account_digest(snapshot) != witness.after_digest
        ):
            raise BrokerAccountWorkspaceUnavailable

    def _coherent(self, snapshot: WorkspaceSnapshot) -> BrokerAccountWitness:
        marker = self._marker(snapshot)
        if self._store.head() != marker:
            raise BrokerAccountWorkspaceUnavailable
        self._assert_snapshot(snapshot, marker)
        return marker

    def _committed_coherent(
        self,
        snapshot: WorkspaceSnapshot,
        operation_id: UUID | None = None,
    ) -> BrokerAccountWitness:
        """Fence positively foreign state against the trusted committed head.

        Only the current vault head identifies the operation, even after claim
        release. Parsing and validated vault reads precede any conflict write;
        callback exceptions are outside this evidence boundary.
        """
        marker = self._marker(snapshot)
        head = self._store.head()
        try:
            if marker != head:
                raise BrokerAccountWorkspaceUnavailable
            self._assert_snapshot(snapshot, marker)
        except BrokerAccountWorkspaceUnavailable:
            if head is not None and head.epoch > 0 and (operation_id is None or operation_id == head.operation_id):
                operation = self._store.operation(head.operation_id)
                if operation.state is AccountOperationStage.COMMITTED and operation.witness == head:
                    self._store.mark_workspace_conflicted(head.operation_id)
            raise
        return marker

    def _guard_original_authority(
        self,
        snapshot: WorkspaceSnapshot,
        operation: AccountOperationSnapshot,
        marker: BrokerAccountWitness,
        head: BrokerAccountWitness,
    ) -> None:
        """Retain a terminal conflict only with positively validated evidence.

        Parsing/reading both participants happens before this boundary. An
        own-operation marker or committed-abandonment evidence might already
        decide commitment: preserve its candidate for forward recovery even
        when other state is damaged. Unreadable/malformed evidence and failed
        persistence barriers likewise must never imply absence of commitment.
        """
        if (
            operation.receipt is not None
            or operation.abandonment_committed
            or marker.operation_id == operation.operation_id
        ):
            return
        if (
            marker != head
            or snapshot.version.instance_id != head.workspace_instance
            or snapshot.version.generation < head.commit_workspace.generation
            or snapshot.version.generation < operation.expected_workspace.generation
            or broker_workspace_version(snapshot) != head.commit_broker_workspace
            or broker_workspace_version(snapshot) != operation.expected_broker_workspace
            or broker_account_digest(snapshot) != head.after_digest
            or self._store.current_credential_version(self._capability, operation.selector)
            != operation.expected_credential
        ):
            if operation.workspace_attempted:
                self._store.mark_workspace_conflicted(operation.operation_id)
            else:
                self._store.settle(
                    operation.operation_id,
                    state=AccountOperationStage.BLOCKED,
                    reason="foreign_account_authority",
                )
            raise BrokerAccountWorkspaceUnavailable

    def _enrol(self, snapshot: WorkspaceSnapshot, commit: Callable[..., WorkspaceSnapshot]) -> BrokerAccountWitness:
        head = self._store.head()
        if head is not None:
            return self._coherent(snapshot)
        try:
            intent = self._store.prepare_enrolment(snapshot)
        except Exception:
            raise BrokerAccountWorkspaceUnavailable from None
        if _MARKER in snapshot.config:
            witness = self._marker(snapshot)
            if (
                witness.epoch != 0
                or witness.operation_id != intent.operation_id
                or witness.workspace_instance != intent.workspace_instance
                or witness.vault_incarnation != intent.vault_incarnation
                or witness.before_digest != intent.before_digest
                or witness.after_digest != intent.before_digest
                or witness.commit_workspace.generation <= intent.expected_workspace.generation
                or witness.commit_broker_workspace != intent.expected_broker_workspace
            ):
                raise BrokerAccountWorkspaceUnavailable
            self._assert_snapshot(snapshot, witness)
            secure_file.fsync_parent_directory(self._path / "workspace.json")
        else:
            if (
                snapshot.version.instance_id != intent.workspace_instance
                or broker_workspace_version(snapshot) != intent.expected_broker_workspace
                or broker_account_digest(snapshot) != intent.before_digest
                or snapshot.version.generation < intent.expected_workspace.generation
            ):
                raise BrokerAccountWorkspaceUnavailable

            def stamp(actual):
                return BrokerAccountWitness(
                    1,
                    intent.workspace_instance,
                    intent.vault_incarnation,
                    intent.operation_id,
                    0,
                    intent.before_digest,
                    intent.before_digest,
                    actual.version,
                    broker_workspace_version(actual),
                ).to_dict()

            snapshot = commit(lambda config: config, stamp)
            witness = self._marker(snapshot)
        try:
            self._store.complete_enrolment(witness)
        except Exception:
            if self._store.head() != witness:
                raise
        return witness

    def enrol(self) -> BrokerAccountWitness:
        """Finish only this genesis intent or its exact durable own witness."""
        return self._locked(self._enrol)

    def assert_coherent(self) -> WorkspaceSnapshot:
        """Require matching workspace marker, vault anchor and broker domain."""

        def check(snapshot, _commit):
            self._coherent(snapshot)
            return snapshot

        return self._locked(check)

    def _commit(
        self,
        operation_id: UUID,
        patch: BrokerAccountPatch,
        snapshot: WorkspaceSnapshot,
        commit: Callable[..., WorkspaceSnapshot],
    ) -> BrokerAccountWitness:
        operation = self._store.operation(operation_id)
        marker = self._marker(snapshot)
        head = self._store.head()
        self._guard_original_authority(snapshot, operation, marker, head)
        self._assert_snapshot(snapshot, marker)
        if operation.state is AccountOperationStage.COMMITTED:
            self._coherent(snapshot)
            return operation.witness
        material = self._store.recovery_material(self._capability, operation_id)
        request = material.request
        if (
            operation.state is not AccountOperationStage.PLAN_READY
            or request is None
            or patch != BrokerAccountPatch(request.kind, request.selector, request.data_roles, material.read_only)
        ):
            raise BrokerAccountWorkspaceUnavailable
        if marker != head:
            if (
                marker.operation_id != operation_id
                or marker.epoch != head.epoch + 1
                or marker.vault_incarnation != head.vault_incarnation
                or marker.workspace_instance != head.workspace_instance
                or marker.before_digest != head.after_digest
                or marker.before_digest != material.before_digest
                or marker.after_digest != material.after_digest
                or marker.commit_workspace.generation <= request.expected_workspace.generation
                or marker.commit_broker_workspace.generation
                != head.commit_broker_workspace.generation + int(marker.before_digest != marker.after_digest)
            ):
                raise BrokerAccountWorkspaceUnavailable
            secure_file.fsync_parent_directory(self._path / "workspace.json")
            return marker
        if (
            operation.abandoned
            or request.expected_workspace.instance_id != snapshot.version.instance_id
            or request.expected_workspace.generation > snapshot.version.generation
            or request.expected_broker_workspace != broker_workspace_version(snapshot)
            or material.before_digest != marker.after_digest
            or broker_account_digest(patch.apply(snapshot.config)) != material.after_digest
        ):
            raise BrokerAccountWorkspaceUnavailable
        if operation.workspace_attempted:
            self._store.mark_workspace_conflicted(operation_id)
            raise BrokerAccountWorkspaceUnavailable
        self._store.assert_original_credentials(self._capability, operation_id)
        self._store.mark_workspace_attempted(operation_id)

        def stamp(actual):
            return BrokerAccountWitness(
                1,
                marker.workspace_instance,
                marker.vault_incarnation,
                operation_id,
                marker.epoch + 1,
                material.before_digest,
                material.after_digest,
                actual.version,
                broker_workspace_version(actual),
            ).to_dict()

        return self._marker(commit(patch.apply, stamp))

    def commit(self, operation_id: UUID, patch: BrokerAccountPatch) -> BrokerAccountWitness:
        """Decide this exact staged plan, rebasing only unrelated workspace edits."""
        _uuid(operation_id)
        if type(patch) is not BrokerAccountPatch:
            raise AccountContractError
        patch.__post_init__()
        return self._operation_locked(
            operation_id, lambda snapshot, commit: self._commit(operation_id, patch, snapshot, commit)
        )

    def _apply(self, operation_id: UUID, witness: BrokerAccountWitness) -> AccountMutationReceipt:
        try:
            return self._store.apply(operation_id, witness)
        except Exception:
            operation = self._store.operation(operation_id)
            if (
                operation.state is not AccountOperationStage.COMMITTED
                or operation.witness != witness
                or self._store.head() != witness
            ):
                raise
            return operation.receipt

    def recover(self) -> tuple[AccountMutationReceipt, ...]:
        """Recover deterministic local effects, retaining runtime-owner custody."""

        def recover_locked(snapshot, commit):
            head = self._store.head()
            if head is None:
                self._enrol(snapshot, commit)
                return ()
            operation = self._store.active_operation(self._capability)
            if operation is None:
                self._committed_coherent(snapshot)
                return ()
            if operation.receipt is not None:
                self._coherent(snapshot)
                return (operation.receipt,)
            marker = self._marker(snapshot)
            self._guard_original_authority(snapshot, operation, marker, head)
            material = self._store.recovery_material(self._capability, operation.operation_id)
            if operation.state is AccountOperationStage.PLAN_READY:
                patch = BrokerAccountPatch(
                    material.request.kind, material.request.selector, material.request.data_roles, material.read_only
                )
                marker = self._marker(snapshot)
                if marker != head:
                    witness = self._commit(operation.operation_id, patch, snapshot, commit)
                    return (self._apply(operation.operation_id, witness),)
            self._coherent(snapshot)
            self._store.assert_original_credentials(self._capability, operation.operation_id)
            if operation.abandoned or operation.state is AccountOperationStage.AUTHENTICATION_STARTED:
                unknown = operation.state is AccountOperationStage.AUTHENTICATION_STARTED
                receipt = self._store.settle(
                    operation.operation_id,
                    state=AccountOperationStage.AUTHENTICATION_UNKNOWN if unknown else AccountOperationStage.REJECTED,
                    reason="authentication_outcome_unknown" if unknown else "operation_abandoned",
                )
                return (receipt,)
            if operation.state is AccountOperationStage.ADMITTED:
                return ()
            witness = self._commit(operation.operation_id, patch, snapshot, commit)
            return (self._apply(operation.operation_id, witness),)

        return self._operation_locked(None, recover_locked)

    def abandon(self, operation_id: UUID, *, reason: str) -> AccountMutationReceipt:
        """Decide abandonment from the actual locked witness, never an exception.

        The caller holds the lifecycle disposition fence. An attempted CAS
        without readable exact decision evidence remains uncertain and owned.
        """

        def abandon_locked(snapshot, commit):
            operation = self._store.operation(operation_id)
            if operation.receipt is not None:
                active = self._store.active_operation(self._capability)
                if (
                    operation.state is AccountOperationStage.COMMITTED
                    and not operation.abandoned
                    and active is not None
                    and active.operation_id == operation_id
                ):
                    self._store.abandon(operation_id, committed=True, reason=reason)
                return operation.receipt
            marker = self._marker(snapshot)
            self._assert_snapshot(snapshot, marker)
            if marker.operation_id == operation_id:
                material = self._store.recovery_material(self._capability, operation_id)
                patch = BrokerAccountPatch(
                    material.request.kind, material.request.selector, material.request.data_roles, material.read_only
                )
                witness = self._commit(operation_id, patch, snapshot, commit)
                self._store.abandon(operation_id, committed=True, reason=reason)
                return self._apply(operation_id, witness)
            if operation.workspace_attempted:
                self._store.mark_workspace_conflicted(operation_id)
                raise BrokerAccountWorkspaceUnavailable
            self._coherent(snapshot)
            self._store.abandon(operation_id, committed=False, reason=reason)
            unknown = operation.state is AccountOperationStage.AUTHENTICATION_STARTED
            return self._store.settle(
                operation_id,
                state=AccountOperationStage.AUTHENTICATION_UNKNOWN if unknown else AccountOperationStage.REJECTED,
                reason="authentication_outcome_unknown" if unknown else reason,
            )

        return self._operation_locked(operation_id, abandon_locked)

    def with_current_authority[T](
        self,
        operation_id: UUID,
        callback: Callable[[WorkspaceSnapshot, CredentialVersion], T],
    ) -> T:
        """Run one short synchronous callback against exact committed authority.

        The caller supplies the outer lifecycle/rebuild publication fences.
        The callback must not await, acquire another workspace lock or perform
        provider work, drain or cleanup while this workspace lock is held.
        """
        _uuid(operation_id)
        if inspect.iscoroutinefunction(callback) or inspect.isasyncgenfunction(callback):
            raise BrokerAccountWorkspaceUnavailable

        def current(snapshot, _commit):
            marker = self._committed_coherent(snapshot, operation_id)
            operation = self._store.operation(operation_id)
            if (
                operation.state is not AccountOperationStage.COMMITTED
                or operation.witness != marker
                or operation.abandoned
                or operation.workspace_conflicted
                or operation.kind is AccountMutationKind.REMOVE
            ):
                raise BrokerAccountWorkspaceUnavailable
            version = self._store.current_credential_version(self._capability, operation.selector)
            if version != operation.receipt.credential_version:
                raise BrokerAccountWorkspaceUnavailable
            result = callback(snapshot, version)
            if inspect.isawaitable(result) or inspect.isasyncgen(result):
                if inspect.iscoroutine(result):
                    result.close()
                raise BrokerAccountWorkspaceUnavailable
            require_backend_lease_proof(self._proof)
            return result

        return self._locked(current)
