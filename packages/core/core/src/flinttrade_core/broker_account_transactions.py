"""Internally composed native transactions; production admission stays denied.

No provider is installed here. Synthetic drivers carry explicit isolated local
cleanup contracts. The workspace witness decides commitment; the durable
receipt never substitutes for current read-generation authority.
"""

from __future__ import annotations

import asyncio
import math
import time
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol
from uuid import UUID

from flinttrade_gateway.account_transaction_store import AccountTransactionStore
from flinttrade_gateway.broker_read_service import BrokerReadOwner
from flinttrade_gateway.native_login import NativeSessionCandidate
from flinttrade_gateway.registry import (
    BrokerRegistry,
    ManagedSessionAuthority,
    RegistryPublicationOwner,
)
from flinttrade_gateway.session_provider import AuthenticatingSessionProvider

from .account_lifecycle_contracts import (
    AccountActorContext,
    AccountAuthenticationRejected,
    AccountMutationKind,
    AccountMutationOutcome,
    AccountMutationReceipt,
    AccountMutationRequest,
    AccountOperationStage,
    broker_account_digest,
)
from .account_mutation_contracts import RegistrySelectorVersion, RegistryVersionConflict, SessionVersion
from .broker_account_audit import AccountMutationAudit
from .broker_account_cutover import require_broker_account_mutations
from .broker_account_lifecycle import AccountMutationLease, BrokerAccountLifecycleOwner, CleanupTicket
from .broker_account_workspace import BrokerAccountPatch, BrokerAccountWorkspace, BrokerAccountWorkspaceUnavailable
from .broker_identity import BrokerSelector, CredentialVersion
from .workspace_migrations import WorkspaceSnapshot, broker_workspace_version


class _CandidateDriver(Protocol):
    def authenticate(self, request: AccountMutationRequest, credentials: Mapping[str, object],
                     prior_retirement: object | None) -> NativeSessionCandidate: ...

    def cleanup(self, payload: object) -> None: ...


@dataclass(repr=False)
class _Attempt:
    lease: AccountMutationLease
    expected_registry: RegistrySelectorVersion | None = None
    tombstone: RegistrySelectorVersion | None = None
    retirement: object | None = None
    retirement_ticket: CleanupTicket | None = None
    candidate: NativeSessionCandidate | None = None
    ticket: CleanupTicket | None = None
    borrowing: bool = False
    settled: bool = False


class BrokerAccountReadRuntime:
    """Read-only composition with a caller-owned shared limiter across rebuilds."""

    def __init__(self, *, registry: BrokerRegistry, workspace_path: Path,
                 credential_version_for: Callable[[BrokerSelector], CredentialVersion],
                 adapters: dict[str, object], rate_limiter: object,
                 runtime_accepting_requests: Callable[[], bool]) -> None:
        self.registry = registry
        self.workspace_path = Path(workspace_path)
        self._credential_version_for = credential_version_for
        self._adapters = dict(adapters)
        self._rate_limiter = rate_limiter
        self._accepting = runtime_accepting_requests
        self.read_owner: BrokerReadOwner | None = None
        self._retiring: list[BrokerReadOwner] = []
        self._provider: AuthenticatingSessionProvider | None = None

    def retire(self, timeout: float) -> bool:
        """Revoke immediately and drain the exact detached original owners."""
        if self.read_owner is not None:
            self._retiring.append(self.read_owner)
            self.read_owner = None
            self._provider = None
        owners = tuple(self._retiring)
        for owner in owners:
            owner.close(timeout=0.0)
        deadline = time.monotonic() + timeout
        complete = True
        for owner in owners:
            if owner.close(timeout=max(0.0, deadline - time.monotonic())):
                if owner in self._retiring:
                    self._retiring.remove(owner)
            else:
                complete = False
        return complete

    def rebuild(self, snapshot: WorkspaceSnapshot, *, coherence_verifier: Callable[[], WorkspaceSnapshot]) -> None:
        """Expose only sealed current native records, with no write router."""
        if self.read_owner is not None or self._retiring:
            raise BrokerAccountWorkspaceUnavailable
        verified = coherence_verifier()
        if (type(verified) is not WorkspaceSnapshot or verified.version is None
                or broker_workspace_version(verified) != broker_workspace_version(snapshot)):
            raise BrokerAccountWorkspaceUnavailable
        snapshot = verified
        provider = AuthenticatingSessionProvider(
            self.registry, snapshot.as_dict()["brokers"]["account_acls"], workspace_snapshot=snapshot,
            workspace_path=self.workspace_path, credential_version_for=self._credential_version_for,
            coherence_verifier=coherence_verifier,
        )
        current = broker_workspace_version(snapshot)
        usable = any(
            type(state.binding) is SessionVersion
            and state.binding.credential_version == self._credential_version_for(state.selector)
            and state.binding.broker_workspace_version == current
            and state.status == "connected"
            for state in self.registry.list_exact_states()
        )
        if not usable:
            self._provider = None
            return
        self._provider = provider
        self.read_owner = BrokerReadOwner(
            registry=self.registry, session_provider=provider, adapters=self._adapters,
            workspace_path=self.workspace_path, rate_limiter=self._rate_limiter,
            runtime_accepting_requests=self._accepting,
        )

    def ready(self, selector: BrokerSelector, version: CredentialVersion) -> bool:
        if self.read_owner is None or self._provider is None or self._accepting() is not True:
            return False
        try:
            authority = self._provider.current_authority_for(selector)
            if authority.credential_version != version:
                return False
            self.registry.get_connected_session_for(selector, current_authority=authority)
            return True
        except Exception:
            return False


class BrokerAccountTransactionCoordinator:
    """One app owner, exact durable participant and retained synthetic worker."""

    def __init__(self, store: AccountTransactionStore, workspace: BrokerAccountWorkspace,
                 lifecycle: BrokerAccountLifecycleOwner, registry_owner: RegistryPublicationOwner,
                 candidate_driver: _CandidateDriver, runtime_builder: BrokerAccountReadRuntime,
                 mutation_admission: Callable[[], None] = require_broker_account_mutations, *,
                 audit_sink: Callable[[AccountMutationAudit], UUID] | None = None,
                 verify_current_actor: Callable[[], AccountActorContext] | None = None) -> None:
        if (type(store) is not AccountTransactionStore or type(workspace) is not BrokerAccountWorkspace
                or type(lifecycle) is not BrokerAccountLifecycleOwner
                or type(registry_owner) is not RegistryPublicationOwner
                or workspace._store is not store
                or runtime_builder.registry is not registry_owner.registry
                or audit_sink is not None and not callable(audit_sink)):
            raise BrokerAccountWorkspaceUnavailable
        lifecycle.assert_bound(store._workspace_path, store._proof)
        self.store = store
        self.workspace = workspace
        self.lifecycle = lifecycle
        self.registry_owner = registry_owner
        self.registry = registry_owner.registry
        self.driver = candidate_driver
        self.runtime = runtime_builder
        self._admission = mutation_admission
        self._verify_actor = verify_current_actor
        self._audit_sink = audit_sink
        self._attempts: dict[object, _Attempt] = {}

    def _principal(self, request: AccountMutationRequest) -> None:
        try:
            actor = None if self._verify_actor is None else self._verify_actor()
            if type(actor) is not AccountActorContext or actor != request.actor:
                raise ValueError
            actor.__post_init__()
        except Exception:
            raise ValueError("account_principal_unavailable") from None

    def _provenance(self, request: AccountMutationRequest) -> None:
        state = self.store.native_state(request.selector)
        if state.version != request.expected_credential:
            raise BrokerAccountWorkspaceUnavailable
        if request.kind is AccountMutationKind.CONNECT:
            record = self.registry.snapshot_exact_state(request.selector)
            if state.present or record is not None and record.binding is not None:
                raise BrokerAccountWorkspaceUnavailable
        elif not state.present or not state.credential_present or state.origin != "managed":
            raise BrokerAccountWorkspaceUnavailable

    def _validate_new(self, request: AccountMutationRequest) -> WorkspaceSnapshot:
        snapshot = self.workspace.assert_coherent()
        if (snapshot.version != request.expected_workspace
                or broker_workspace_version(snapshot) != request.expected_broker_workspace):
            raise BrokerAccountWorkspaceUnavailable
        self._provenance(request)
        return snapshot

    def _outcome(self, receipt: AccountMutationReceipt, request: AccountMutationRequest | None = None) -> AccountMutationOutcome:
        attempt = self._attempts.get(receipt.operation_id)
        if receipt.state in (AccountOperationStage.BLOCKED, AccountOperationStage.AUTHENTICATION_UNKNOWN):
            status = "blocked"
        elif attempt is not None and not attempt.settled:
            status = "cleanup_pending"
        elif receipt.state is not AccountOperationStage.COMMITTED:
            status = "session_unavailable"
        else:
            try:
                operation = self.store.operation(receipt.operation_id)
                snapshot = self.workspace.assert_coherent()
                if request is not None:
                    self._principal(request)
                if (operation.abandoned or operation.workspace_conflicted
                        or self.store.native_state(receipt.selector).version != receipt.credential_version
                        or broker_workspace_version(snapshot) != receipt.commit_broker_workspace):
                    raise BrokerAccountWorkspaceUnavailable
                state = self.registry.snapshot_exact_state(receipt.selector)
                if receipt.kind is AccountMutationKind.REMOVE:
                    status = "removed" if (state is None or state.binding is None) and not self.store.native_state(receipt.selector).present else "session_unavailable"
                else:
                    status = "ready" if self.runtime.ready(receipt.selector, receipt.credential_version) else "session_unavailable"
            except Exception:
                status = "session_unavailable"
        return AccountMutationOutcome(receipt, status)

    async def _settle(self, receipt: AccountMutationReceipt, attempt: _Attempt, deadline: float) -> None:
        if receipt.state not in (AccountOperationStage.COMMITTED, AccountOperationStage.REJECTED):
            return
        if attempt.retirement is not None and attempt.retirement_ticket is None:
            attempt.retirement_ticket = self.lifecycle.retain_retirement(
                attempt.lease, self.registry_owner, attempt.retirement)
        while not attempt.settled:
            if self.lifecycle.settle(attempt.lease, durable_disposition=True):
                attempt.settled = True
                return
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                return
            # A completed False bridge proves only that the earlier drain
            # expired. Retry its exact owners before releasing either claim.
            try:
                drained = await self.lifecycle.retire_generations_async(attempt.lease, remaining)
            except Exception:
                return
            if not drained:
                return
            remaining = deadline - time.monotonic()
            if remaining > 0:
                await asyncio.sleep(min(0.01, remaining))

    def _drop_preadmission(self, request: AccountMutationRequest, attempt: _Attempt) -> None:
        """Settle and forget a lease that never admitted a durable claim."""
        if not self.lifecycle.settle(attempt.lease, durable_disposition=True):
            return
        attempt.settled = True
        self.lifecycle.forget_settled(attempt.lease)
        self._attempts.pop(request.operation_id, None)

    def _disposition(self, request: AccountMutationRequest, attempt: _Attempt, reason: str) -> AccountMutationReceipt:
        self.lifecycle.abandon(attempt.lease)
        return self.lifecycle.with_disposition_fence(
            attempt.lease, lambda: self.workspace.abandon(request.operation_id, reason=reason)
        )

    def _retire_target(self, request: AccountMutationRequest, attempt: _Attempt) -> None:
        if attempt.tombstone is not None:
            if self.registry.snapshot_selector(request.selector) != attempt.tombstone:
                raise BrokerAccountWorkspaceUnavailable
            return
        expected = attempt.expected_registry
        if expected is None or self.registry.snapshot_selector(request.selector) != expected:
            raise BrokerAccountWorkspaceUnavailable
        state = self.registry.snapshot_exact_state(request.selector)
        if state is not None and state.binding is not None:
            if (type(state.binding) is not SessionVersion
                    or state.binding.credential_version != request.expected_credential
                    or state.binding.broker_workspace_version != request.expected_broker_workspace):
                raise BrokerAccountWorkspaceUnavailable
        try:
            removed = self.registry_owner.remove_session_for_exact(
                request.selector, expected_registry=expected, operation_id=request.operation_id)
        except Exception:
            removed = self.registry_owner.removal_result_for(
                request.operation_id, request.selector, expected_registry=expected)
            if removed is None:
                self.store.settle(request.operation_id, state=AccountOperationStage.BLOCKED,
                                  reason="registry_removal_outcome_unknown")
                raise
        attempt.tombstone = removed.version
        attempt.retirement = removed.retired
        if removed.retired is not None:
            attempt.retirement_ticket = self.lifecycle.retain_retirement(
                attempt.lease, self.registry_owner, removed.retired)
        if self.registry.snapshot_selector(request.selector) != attempt.tombstone:
            raise BrokerAccountWorkspaceUnavailable

    def _publish(self, request: AccountMutationRequest, attempt: _Attempt) -> None:
        def publish(snapshot, version):
            self._principal(request)
            authority = ManagedSessionAuthority(version, snapshot.version, broker_workspace_version(snapshot))
            prepared = None
            try:
                prepared = self.registry_owner.prepare_session_candidate(
                    request.selector, attempt.candidate.session, expected_registry=attempt.tombstone,
                    authority=authority, broker=request.broker, label=request.label,
                )
                self.registry_owner.publish_prepared_candidate(prepared, current_authority=authority)
            except BaseException as error:
                # A raised result may conceal publication. Never clean a live payload.
                live = self.registry_owner.live_candidate_version(attempt.candidate.session)
                if live is not None and live.credential_version == version:
                    self.lifecycle.transfer_candidate_to_registry(attempt.lease, attempt.ticket, self.registry_owner)
                else:
                    retired = error.retirement_receipt if isinstance(error, RegistryVersionConflict) else None
                    if retired is None:
                        retired = self.registry_owner.retirement_for_candidate(attempt.candidate.session)
                    if retired is None:
                        prepared = self.registry_owner.prepared_candidate_for(
                            attempt.candidate.session, expected_registry=attempt.tombstone)
                        if prepared is not None:
                            retired = self.registry_owner.abandon_prepared_candidate(prepared)
                    if retired is not None:
                        self.lifecycle.retain_retirement(attempt.lease, self.registry_owner, retired)
                raise
            self.lifecycle.transfer_candidate_to_registry(attempt.lease, attempt.ticket, self.registry_owner)
            return snapshot

        snapshot = self.workspace.with_current_authority(request.operation_id, publish)
        self.runtime.rebuild(snapshot, coherence_verifier=self.workspace.assert_coherent)

    def _commit_and_publish(self, request: AccountMutationRequest, attempt: _Attempt, patch: BrokerAccountPatch) -> AccountMutationReceipt:
        self._principal(request)
        witness = self.workspace.commit(request.operation_id, patch)
        try:
            receipt = self.store.apply(request.operation_id, witness)
        except Exception:
            operation = self.store.operation(request.operation_id)
            if operation.receipt is None or operation.witness != witness:
                raise
            receipt = operation.receipt
        if request.kind is AccountMutationKind.REMOVE:
            if self.registry.snapshot_selector(request.selector) != attempt.tombstone:
                raise BrokerAccountWorkspaceUnavailable
            self.runtime.rebuild(self.workspace.assert_coherent(), coherence_verifier=self.workspace.assert_coherent)
        else:
            self._publish(request, attempt)
        return receipt

    async def mutate(self, request: AccountMutationRequest, *, timeout: float) -> AccountMutationOutcome:
        """Perform one bounded borrower operation without cancelling real workers."""
        if (type(request) is not AccountMutationRequest or type(timeout) not in (int, float)
                or isinstance(timeout, bool) or not math.isfinite(timeout) or timeout < 0):
            raise ValueError("account_mutation_invalid")
        request.__post_init__()
        deadline = time.monotonic() + timeout
        existing = self.store.existing_request(request)
        # Keyed replay is independent of current workspace coherence, while
        # both receipt access and caller-triggered settlement require authority.
        self._admission()
        self._principal(request)
        attempt = self._attempts.get(request.operation_id)
        if attempt is not None and attempt.settled:
            self._attempts.pop(request.operation_id, None)
            attempt = None
        if existing is not None and existing.receipt is not None:
            if attempt is not None and not attempt.borrowing:
                await self._settle(existing.receipt, attempt, deadline)
            return self._outcome(existing.receipt, request)
        # Operation-kind eligibility is known without authenticating a candidate.
        BrokerAccountPatch(request.kind, request.selector, request.data_roles,
                           None if request.kind is AccountMutationKind.REMOVE else False)
        if attempt is not None and attempt.borrowing:
            raise RuntimeError("account_mutation_busy")
        # Runtime admission precedes the durable row: shutdown cannot strand it.
        if attempt is None:
            def release_claim():
                if self.store.existing_request(request) is not None:
                    self.store.release_claim(request.operation_id)

            lease = self.lifecycle.begin(request.operation_id, request.selector, durable_claim_release=release_claim)
            attempt = _Attempt(lease, expected_registry=self.registry.snapshot_selector(request.selector))
            self._attempts[request.operation_id] = attempt
        attempt.borrowing = True
        admitted = existing is not None
        try:
            if existing is None:
                self._validate_new(request)
                existing = self.store.admit(request)
                admitted = True
            elif existing.state is not AccountOperationStage.ADMITTED:
                receipts = self.lifecycle.with_disposition_fence(attempt.lease, self.workspace.recover)
                if receipts:
                    await self._settle(receipts[0], attempt, deadline)
                    return self._outcome(receipts[0], request)
                raise BrokerAccountWorkspaceUnavailable
            if not await self.lifecycle.retire_generations_async(attempt.lease, max(0.0, deadline - time.monotonic())):
                receipt = self._disposition(request, attempt, "generation_drain_timeout")
                await self._settle(receipt, attempt, deadline)
                return self._outcome(receipt, request)
            self.lifecycle.publish_if_current(attempt.lease, lambda: self._retire_target(request, attempt))
            self._principal(request)
            snapshot = self.workspace.assert_coherent()
            self._provenance(request)
            if request.kind is not AccountMutationKind.REMOVE:
                credentials = request.credentials
                if credentials is None:
                    credentials = self.store.native_credentials(request.selector, request.expected_credential)
                def authenticate():
                    self._principal(request)
                    self._admission()
                    return self.driver.authenticate(request, credentials, attempt.retirement)

                def accept(candidate):
                    if type(candidate) is not NativeSessionCandidate:
                        raise ValueError("account_candidate_invalid")
                    attempt.candidate = candidate
                    attempt.ticket = self.lifecycle.retain_candidate(attempt.lease, candidate.session, self.driver.cleanup)

                worker = self.lifecycle.run_worker(
                    attempt.lease, authenticate, accept_result=accept,
                    before_dispatch=lambda: self.store.mark_authentication_started(request.operation_id))
                try:
                    await self.lifecycle.wait_worker(attempt.lease, worker, timeout=max(0.0, deadline - time.monotonic()))
                except AccountAuthenticationRejected:
                    receipt = self.lifecycle.with_disposition_fence(
                        attempt.lease, lambda: self.store.settle(request.operation_id,
                            state=AccountOperationStage.REJECTED, reason="authentication_rejected"))
                    await self._settle(receipt, attempt, deadline)
                    return self._outcome(receipt, request)
                if attempt.candidate.probe_error is not None:
                    raise ValueError("account_candidate_probe_unknown")
            read_only = None if request.kind is AccountMutationKind.REMOVE else attempt.candidate.is_read_only
            patch = BrokerAccountPatch(request.kind, request.selector, request.data_roles, read_only)
            self.store.stage_plan(
                request.operation_id, replay_credentials=None if request.kind is AccountMutationKind.REMOVE
                else attempt.candidate.replay_credentials, read_only=read_only,
                before_digest=broker_account_digest(snapshot), after_digest=broker_account_digest(patch.apply(snapshot.config)),
            )
            receipt = self.lifecycle.publish_if_current(
                attempt.lease, lambda: self._commit_and_publish(request, attempt, patch)
            )
            await self._settle(receipt, attempt, deadline)
            return self._outcome(receipt, request)
        except asyncio.CancelledError:
            if not admitted:
                admitted = self.store.existing_request(request) is not None
            if admitted:
                self._disposition(request, attempt, "caller_cancelled")
            else:
                self._drop_preadmission(request, attempt)
            raise
        except Exception:
            if not admitted:
                admitted = self.store.existing_request(request) is not None
            if not admitted:
                self._drop_preadmission(request, attempt)
                raise
            receipt = self._disposition(request, attempt, "operation_failed")
            await self._settle(receipt, attempt, deadline)
            return self._outcome(receipt, request)
        finally:
            attempt.borrowing = False

    def recover(self) -> tuple[AccountMutationReceipt, ...]:
        """Provider-free recovery; SDK objects are never rebuilt from receipts."""
        active = self.store.active_operation(self.store.owner_capability(self.store._proof))
        if active is None:
            receipts = self.workspace.recover()
            self.reconcile_audit()
            return receipts
        attempt = self._attempts.get(active.operation_id)
        if attempt is None:
            attempt = _Attempt(self.lifecycle.begin(
                active.operation_id, active.selector,
                durable_claim_release=lambda: self.store.release_claim(active.operation_id)),
                expected_registry=self.registry.snapshot_selector(active.selector))
            self._attempts[active.operation_id] = attempt
        receipts = self.lifecycle.with_disposition_fence(attempt.lease, self.workspace.recover)
        if receipts and receipts[0].state in (AccountOperationStage.COMMITTED, AccountOperationStage.REJECTED):
            try:
                settled = self.lifecycle.settle(attempt.lease, durable_disposition=True)
                if not settled:
                    # Recovery may start an owned local retry, but never wait
                    # for it or infer completion from its zero-time borrower.
                    self.lifecycle.retire_generations(attempt.lease, 0.0)
                    settled = self.lifecycle.settle(attempt.lease, durable_disposition=True)
            except Exception:
                settled = False
            if settled:
                attempt.settled = True
        self.reconcile_audit()
        return receipts

    def reconcile_audit(self, *, limit: int = 100) -> int:
        """Deliver retained terminal evidence outside mutation/publication fences.

        An explicit caller owns this bookkeeping operation. A bounded mutation
        borrower never acquires an arbitrary audit sink callback, and replaying
        these events never dispatches authentication or rebuilds sessions.
        """
        if type(limit) is not int or not 1 <= limit <= 100:
            raise ValueError("account_audit_limit_invalid")
        if self._audit_sink is None:
            return 0
        capability = self.store.owner_capability(self.store._proof)
        return self.store.export_audit_events(capability, self._audit_sink, limit=limit)
