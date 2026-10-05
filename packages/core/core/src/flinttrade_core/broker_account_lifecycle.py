"""App-lifetime runtime custody for the offline account transaction foundation.

The rebuild lock is also the publication fence. No owner condition, rebuild
lock or registry lock spans a worker join, generation drain or local cleanup.
Durable operation claims belong to AccountTransactionStore, not this owner.
"""

from __future__ import annotations

import asyncio
import inspect
import math
import os
import threading
import time
from collections.abc import Callable
from concurrent.futures import Future, TimeoutError as FutureTimeout
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any
from uuid import RFC_4122, UUID

from .backend_instance import BackendLeaseProof, BackendLeaseUnavailable, require_backend_lease_proof
from .broker_identity import BrokerSelector, _validate_selector

_OWNERS: dict[tuple[Path, UUID], BrokerAccountLifecycleOwner] = {}
_OWNERS_LOCK = threading.Lock()


class _OpaqueCapability:
    __slots__ = ()

    def __repr__(self) -> str:
        return f"<{type(self).__name__}>"

    def __reduce_ex__(self, protocol: int) -> Any:
        raise TypeError("account_lifecycle_capability_not_serialisable")


class AccountMutationLease(_OpaqueCapability):
    """Identity-sealed borrower capability; identity fields stay owner-side."""


class RuntimeRebuildLease(_OpaqueCapability):
    """Process/thread-bound volatile rebuild intent, with no durable authority."""


class CleanupTicket(_OpaqueCapability):
    """Strong custody of exactly one payload and an explicit cleanup contract."""


@dataclass(frozen=True)
class AccountLifecycleSnapshot:
    """Counts only: no credentials, candidates, callbacks or SDK representations."""

    accepting: bool
    active: bool
    workers: int
    cleanup_pending: int
    quarantined: int
    live_owned: int


@dataclass(repr=False)
class _Candidate:
    payload: object
    cleanup: Callable[[object], None] | None
    release: Callable[[object], None] | None = None
    worker: Future | None = None
    complete: bool = False
    registry_owner: Any = None
    registry_binding: Any = None
    raw_payload: object = None


@dataclass(repr=False)
class _Operation:
    operation_id: UUID
    selector: BrokerSelector
    abandoned: bool = False
    settled: bool = False
    workers: set[Future] = field(default_factory=set)
    candidates: dict[CleanupTicket, _Candidate] = field(default_factory=dict)
    retirements: dict[object, tuple[object, CleanupTicket]] = field(default_factory=dict)
    retirement_worker: Future | None = None
    durable_claim_release: Callable[[], None] | None = None


@dataclass(repr=False)
class _RebuildIntent:
    token: RuntimeRebuildLease
    thread_id: int
    retire: Callable[[float], bool]
    publication_current: Callable[[], bool]
    mutation_lease: AccountMutationLease | None = None
    depth: int = 1
    worker: Future | None = None


def _timeout(value: float) -> float:
    if type(value) not in (int, float) or not math.isfinite(value) or value < 0:
        raise ValueError("account_lifecycle_timeout_invalid")
    return float(value)


def _require_sync_wait(timeout: float) -> None:
    if timeout == 0:
        return
    try:
        asyncio.get_running_loop()
    except RuntimeError:
        return
    raise RuntimeError("account_lifecycle_use_async_drain")


def _launch(future: Future, operation: Callable[[], Any]) -> None:
    """Start only an already-running genuine future, with no cancellable wrapper."""
    def run() -> None:
        try:
            future.set_result(operation())
        except BaseException as exc:  # noqa: BLE001 - retain failures without rendering SDK details
            future.set_exception(exc)

    threading.Thread(target=run, name="account-lifecycle-worker", daemon=True).start()


def _running_future() -> Future:
    future = Future()
    future.set_running_or_notify_cancel()
    return future


class BrokerAccountLifecycleOwner:
    """One process owner per live backend proof/workspace, retaining all borrowers.

    Cleanup callbacks must be isolated, idempotent local operations. None means
    QUARANTINED_UNDISPOSED; there is intentionally no SDK disposal inference.
    Publication callbacks are synchronous short local commit/publication work:
    no provider calls, awaits, drain or cleanup. Use run_worker for blocking work.
    """

    def __init__(self, workspace_path: Path, backend_proof: BackendLeaseProof, *,
                 retire_generations: Callable[[float], bool], rebuild_lock: object) -> None:
        proof = require_backend_lease_proof(backend_proof)
        path = Path(workspace_path).resolve()
        if (path != proof.workspace_path or not callable(retire_generations)
                or inspect.iscoroutinefunction(retire_generations)):
            raise RuntimeError("account_lifecycle_authority_invalid")
        if not callable(getattr(rebuild_lock, "acquire", None)) or not callable(getattr(rebuild_lock, "release", None)):
            raise RuntimeError("account_lifecycle_fence_invalid")
        self._creator_pid = os.getpid()
        self._proof = proof
        self._key = path, proof.incarnation
        self._retire_generations = retire_generations
        self._rebuild_lock = rebuild_lock
        self._condition = threading.Condition()
        self._accepting = True
        self._active: AccountMutationLease | None = None
        self._operations: dict[AccountMutationLease, _Operation] = {}
        self._candidates: dict[int, tuple[AccountMutationLease, CleanupTicket, _Candidate]] = {}
        self._custody_moves: set[int] = set()
        self._rebuild_intent: _RebuildIntent | None = None
        self._publication_thread: int | None = None
        self._shutdown_retirement: Future | None = None
        self._async_shutdown: Future | None = None
        with _OWNERS_LOCK:
            if self._key in _OWNERS:
                raise RuntimeError("account_lifecycle_owner_exists")
            _OWNERS[self._key] = self

    def _require_process(self) -> None:
        # This check must precede every condition/fence access. Cleanup is
        # valid after proof revocation, but never in a fork-inherited process.
        if os.getpid() != self._creator_pid:
            raise RuntimeError("account_lifecycle_foreign_process")

    def assert_bound(self, workspace_path: Path, backend_proof: BackendLeaseProof) -> None:
        """Revalidate explicit composition; a cached owner never supplies authority."""
        self._require_process()
        proof = require_backend_lease_proof(backend_proof)
        if proof is not self._proof or Path(workspace_path).resolve() != self._key[0]:
            raise RuntimeError("account_lifecycle_authority_invalid")

    def _operation(self, lease: AccountMutationLease) -> _Operation:
        self._require_process()
        if type(lease) is not AccountMutationLease or lease not in self._operations:
            raise RuntimeError("account_mutation_lease_invalid")
        operation = self._operations[lease]
        if operation.settled:
            raise RuntimeError("account_mutation_lease_settled")
        return operation

    def begin(self, operation_id: UUID, selector: BrokerSelector, *,
              durable_claim_release: Callable[[], None] | None = None) -> AccountMutationLease:
        """Borrow the one active lane; same exact identity returns its original lease."""
        self._require_process()
        if type(operation_id) is not UUID or operation_id.version != 4 or operation_id.variant != RFC_4122:
            raise ValueError("account_operation_id_invalid")
        _validate_selector(selector)
        if durable_claim_release is not None and (
                not callable(durable_claim_release) or inspect.iscoroutinefunction(durable_claim_release)):
            raise TypeError("account_durable_claim_callback_invalid")
        with self._rebuild_lock:
            require_backend_lease_proof(self._proof)
            with self._condition:
                if not self._accepting:
                    raise RuntimeError("account_lifecycle_closed")
                if self._rebuild_intent is not None:
                    raise RuntimeError("account_mutation_busy")
                if self._active is not None:
                    current = self._operations[self._active]
                    if current.operation_id == operation_id and current.selector == selector:
                        return self._active
                    raise RuntimeError("account_mutation_busy")
                if any(item.operation_id == operation_id for item in self._operations.values()):
                    raise RuntimeError("account_mutation_already_settled")
                lease = AccountMutationLease()
                self._operations[lease] = _Operation(
                    operation_id, selector, durable_claim_release=durable_claim_release)
                self._active = lease
                return lease

    def legacy_publication_allowed(self) -> bool:
        """Call under the shared rebuild fence; owner-issued callbacks are the exception."""
        self._require_process()
        try:
            require_backend_lease_proof(self._proof)
        except BackendLeaseUnavailable:
            return False
        with self._condition:
            thread_id = threading.get_ident()
            rebuild = self._rebuild_intent
            account_current = self._active is None or (
                self._publication_thread == thread_id and not self._operations[self._active].abandoned)
            return self._accepting and account_current and (
                rebuild is None or (rebuild.thread_id == thread_id and rebuild.depth > 0
                                    and self._rebuild_scope_current(rebuild)))

    def legacy_mutation_admission_allowed(self) -> bool:
        """A rotation/auth borrower cannot use an occupied account or rebuild lane."""
        self._require_process()
        try:
            require_backend_lease_proof(self._proof)
        except BackendLeaseUnavailable:
            return False
        with self._condition:
            return self._accepting and self._active is None and self._rebuild_intent is None

    def begin_rebuild(self, *, retire_generations: Callable[[float], bool],
                      publication_current: Callable[[], bool]) -> RuntimeRebuildLease:
        """Reserve runtime-only generation intent; no UUID, selector or store claim."""
        self._require_process()
        if any(not callable(callback) or inspect.iscoroutinefunction(callback)
               for callback in (retire_generations, publication_current)):
            raise TypeError("account_rebuild_callback_invalid")
        with self._rebuild_lock:
            require_backend_lease_proof(self._proof)
            with self._condition:
                thread_id = threading.get_ident()
                if not self._accepting or (self._active is not None and (
                        self._publication_thread != thread_id or self._operations[self._active].abandoned)):
                    raise RuntimeError("account_rebuild_busy")
                existing = self._rebuild_intent
                if existing is not None:
                    if existing.thread_id != thread_id or existing.depth == 0:
                        raise RuntimeError("account_rebuild_busy")
                    existing.depth += 1
                    return existing.token
                token = RuntimeRebuildLease()
                self._rebuild_intent = _RebuildIntent(token, thread_id, retire_generations, publication_current,
                                                     mutation_lease=self._active)
                return token

    def current_rebuild(self) -> RuntimeRebuildLease | None:
        """Return only this thread's still-admitted runtime intent."""
        self._require_process()
        with self._condition:
            intent = self._rebuild_intent
            return (intent.token if intent is not None and intent.depth > 0
                    and intent.thread_id == threading.get_ident() else None)

    def _rebuild(self, token: RuntimeRebuildLease) -> _RebuildIntent:
        self._require_process()
        intent = self._rebuild_intent
        if (type(token) is not RuntimeRebuildLease or intent is None or intent.token is not token
                or intent.thread_id != threading.get_ident() or intent.depth == 0):
            raise RuntimeError("account_rebuild_lease_invalid")
        return intent

    def _rebuild_scope_current(self, intent: _RebuildIntent) -> bool:
        self._require_process()
        lease = intent.mutation_lease
        if lease is None:
            return self._active is None
        return (self._active is lease and self._publication_thread == threading.get_ident()
                and not self._operations[lease].abandoned and not self._operations[lease].settled)

    def publish_rebuild_if_current(self, token: RuntimeRebuildLease, callback: Callable[[], Any]) -> Any:
        """Revalidate exact runtime generation after unlocked drain, then publish locally."""
        self._require_process()
        if not callable(callback) or inspect.iscoroutinefunction(callback):
            raise TypeError("account_publication_callback_invalid")
        with self._rebuild_lock:
            require_backend_lease_proof(self._proof)
            with self._condition:
                intent = self._rebuild(token)
                if not self._accepting or not self._rebuild_scope_current(intent) or (intent.worker is not None and (
                        not intent.worker.done() or intent.worker.exception() is not None or intent.worker.result() is not True)):
                    raise RuntimeError("account_rebuild_publication_revoked")
            if intent.publication_current() is not True:
                raise RuntimeError("account_rebuild_generation_conflict")
            result = callback()
            if inspect.isawaitable(result):
                if inspect.iscoroutine(result):
                    result.close()
                raise TypeError("account_publication_callback_invalid")
            return result

    def _finish_rebuild(self, intent: _RebuildIntent) -> None:
        self._require_process()
        with self._condition:
            if self._rebuild_intent is intent and intent.depth == 0:
                if intent.worker is None or intent.worker.done():
                    self._rebuild_intent = None
            self._condition.notify_all()

    def end_rebuild(self, token: RuntimeRebuildLease) -> None:
        """Release the borrower; genuine pending drain keeps its lane and strong owner."""
        self._require_process()
        with self._condition:
            intent = self._rebuild(token)
            intent.depth -= 1
        self._finish_rebuild(intent)

    def retire_rebuild_generations(self, token: RuntimeRebuildLease, timeout: float) -> bool:
        """Zero-wait revoke, then an explicitly owned unlocked blocking drain."""
        self._require_process()
        timeout = _timeout(timeout)
        if self._publication_thread != threading.get_ident():
            _require_sync_wait(timeout)
        with self._condition:
            intent = self._rebuild(token)
            future = intent.worker
            if future is None:
                future = _running_future()
                intent.worker = future
                launch = True
            else:
                launch = False
        if launch:
            future.add_done_callback(lambda _future: self._finish_rebuild(intent))
            def retire(wait: float) -> bool:
                result = intent.retire(wait)
                if type(result) is not bool:
                    if inspect.iscoroutine(result):
                        result.close()
                    raise TypeError("account_generation_retirement_invalid")
                return result
            try:
                zero_drained = retire(0.0)
            except BaseException as exc:  # noqa: BLE001 - retain the failed real bridge
                future.set_exception(exc)
            else:
                if zero_drained:
                    future.set_result(True)
                elif self._publication_thread == threading.get_ident():
                    # An owner-issued publication already holds the outer fence;
                    # it may revoke only, never perform a positive nested drain.
                    future.set_result(False)
                else:
                    _launch(future, lambda: retire(timeout))
        try:
            return future.result(timeout) is True
        except Exception:  # noqa: BLE001 - composition fails closed; worker stays owned
            return False

    def publish_if_current(self, lease: AccountMutationLease, callback: Callable[[], Any]) -> Any:
        """Serialise short synchronous publication against abandonment and shutdown."""
        self._require_process()
        if not callable(callback) or inspect.iscoroutinefunction(callback):
            raise TypeError("account_publication_callback_invalid")
        with self._rebuild_lock:
            require_backend_lease_proof(self._proof)
            with self._condition:
                operation = self._operation(lease)
                if not self._accepting or operation.abandoned or self._active is not lease:
                    raise RuntimeError("account_mutation_publication_revoked")
                if any(not worker.done() for worker in operation.workers):
                    raise RuntimeError("account_mutation_worker_pending")
                if any(
                    worker.cancelled() or worker.exception() is not None
                    for worker in operation.workers
                ):
                    raise RuntimeError("account_mutation_worker_failed")
                retired = operation.retirement_worker
                if retired is not None and (retired.exception() is not None or retired.result() is not True):
                    raise RuntimeError("account_mutation_retirement_pending")
                self._publication_thread = threading.get_ident()
            try:
                result = callback()
                if inspect.isawaitable(result):
                    if inspect.iscoroutine(result):
                        result.close()
                    raise TypeError("account_publication_callback_invalid")
                return result
            finally:
                with self._condition:
                    self._publication_thread = None

    def abandon(self, lease: AccountMutationLease) -> None:
        """Revoke publication only; actual worker/candidate custody remains intact."""
        self._require_process()
        with self._rebuild_lock:
            with self._condition:
                self._operation(lease).abandoned = True
                self._condition.notify_all()

    def with_disposition_fence(self, lease: AccountMutationLease, callback: Callable[[], Any]) -> Any:
        """Serialise a durable decision after volatile publication is revoked.

        This grants no publication/dispatch authority. The coordinator uses it
        solely to inspect the actual workspace witness before abandonment.
        """
        self._require_process()
        if not callable(callback) or inspect.iscoroutinefunction(callback):
            raise TypeError("account_publication_callback_invalid")
        with self._rebuild_lock:
            require_backend_lease_proof(self._proof)
            with self._condition:
                self._operation(lease)
            result = callback()
            if inspect.isawaitable(result):
                if inspect.iscoroutine(result):
                    result.close()
                raise TypeError("account_publication_callback_invalid")
            return result

    def retain_worker(self, lease: AccountMutationLease, worker: Future) -> Future:
        """Retain a genuine concurrent future, never an asyncio wrapper/task."""
        self._require_process()
        if not isinstance(worker, Future) or worker.cancelled():
            raise TypeError("account_mutation_real_worker_required")
        with self._condition:
            operation = self._operation(lease)
            operation.workers.add(worker)
        worker.add_done_callback(lambda _future: self._notify())
        return worker

    def _notify(self) -> None:
        self._require_process()
        with self._condition:
            self._condition.notify_all()

    def run_worker(self, lease: AccountMutationLease, operation: Callable[[], Any], *,
                   accept_result: Callable[[Any], None] | None = None,
                   before_dispatch: Callable[[], None] | None = None) -> Future:
        """Reserve custody before dispatch; accept late results before real completion.

        An async adapter may run in this bridge via asyncio.run. Its existing
        run_blocking_sdk_call shielding must remain intact inside that coroutine.
        """
        self._require_process()
        if before_dispatch is not None and (
                not callable(before_dispatch) or inspect.iscoroutinefunction(before_dispatch)):
            raise TypeError("account_dispatch_callback_invalid")
        with self._rebuild_lock:
            require_backend_lease_proof(self._proof)
            with self._condition:
                owned = self._operation(lease)
                if not self._accepting or owned.abandoned:
                    raise RuntimeError("account_mutation_dispatch_revoked")
                future = _running_future()
                owned.workers.add(future)
            future.add_done_callback(lambda _future: self._notify())
            if before_dispatch is not None:
                try:
                    if before_dispatch() is not None:
                        raise TypeError("account_dispatch_callback_invalid")
                except BaseException as error:
                    future.set_exception(error)
                    return future
            def run() -> Any:
                require_backend_lease_proof(self._proof)
                result = operation()
                if accept_result is not None:
                    try:
                        accept_result(result)
                    except BaseException:
                        # A failed explicit transfer never drops a late SDK payload.
                        self.retain_candidate(lease, result, None)
                        raise
                return result
            _launch(future, run)
            return future

    async def wait_worker(self, lease: AccountMutationLease, worker: Future, *, timeout: float | None = None) -> Any:
        """Cancellation/timeout abandons publication, without cancelling real work."""
        self._require_process()
        with self._condition:
            if worker not in self._operation(lease).workers:
                raise RuntimeError("account_mutation_worker_invalid")
        wrapped = asyncio.wrap_future(worker)
        try:
            return await asyncio.wait_for(asyncio.shield(wrapped), timeout=timeout)
        except (asyncio.CancelledError, TimeoutError):
            self.abandon(lease)
            # Retrieve later errors even if this borrower no longer observes it.
            wrapped.add_done_callback(lambda value: None if value.cancelled() else value.exception())
            raise

    @staticmethod
    def _validate_cleanup(cleanup: Callable[[object], None] | None) -> None:
        if cleanup is not None and (not callable(cleanup) or inspect.iscoroutinefunction(cleanup)):
            raise TypeError("account_candidate_cleanup_invalid")

    def retain_candidate(self, lease: AccountMutationLease, candidate: object,
                         cleanup: Callable[[object], None] | None) -> CleanupTicket:
        """Reserve raw identity owner-wide; only an exact same-lane replay deduplicates."""
        self._require_process()
        self._validate_cleanup(cleanup)
        from flinttrade_gateway.registry import RetiredRegistryCandidate  # noqa: PLC0415
        raw = candidate.session if type(candidate) is RetiredRegistryCandidate else candidate
        with self._condition:
            operation = self._operation(lease)
            prior = self._candidates.get(id(raw))
            if prior is not None:
                prior_lease, ticket, owned = prior
                if prior_lease is not lease or owned.raw_payload is not raw:
                    raise RuntimeError("account_candidate_already_owned")
                return ticket
            ticket = CleanupTicket()
            owned = _Candidate(candidate, cleanup, raw_payload=raw)
            operation.candidates[ticket] = owned
            self._candidates[id(raw)] = (lease, ticket, owned)
            self._condition.notify_all()
            return ticket

    def transfer_candidate_to_registry(self, lease: AccountMutationLease, ticket: CleanupTicket,
                                       registry_owner: Any) -> None:
        """Bind live registry ownership while retaining the explicit cleanup contract.

        Call synchronously inside publish_if_current, after registry publication.
        Settlement releases the mutation lane, never this live cleanup custody.
        Shutdown drains generations, retires the exact binding and cleans locally.
        """
        self._require_process()
        with self._condition:
            operation = self._operation(lease)
            candidate = operation.candidates.get(ticket)
            if candidate is None or candidate.worker is not None or candidate.complete or candidate.registry_owner is not None:
                raise RuntimeError("account_candidate_ticket_invalid")
            payload = candidate.payload
        if self._publication_thread != threading.get_ident():
            raise RuntimeError("account_candidate_transfer_invalid")
        from flinttrade_gateway.registry import RegistryPublicationOwner  # noqa: PLC0415
        if type(registry_owner) is not RegistryPublicationOwner:
            raise RuntimeError("account_candidate_transfer_invalid")
        binding = registry_owner.live_candidate_version(payload)
        if binding is None:
            raise RuntimeError("account_candidate_transfer_invalid")
        with self._condition:
            candidate.registry_owner = registry_owner
            candidate.registry_binding = binding

    def _retired_candidate(self, payload: Any, previous: _Candidate | None,
                           cleanup: Callable[[object], None] | None, registry_owner: Any) -> _Candidate:
        """Build a replacement without consuming any previous custody."""
        self._require_process()
        effective = cleanup
        if previous is not None and previous.cleanup is not None:
            local_cleanup, original_payload = previous.cleanup, previous.payload
            def inherited_cleanup(_retired: object) -> None:
                return local_cleanup(original_payload)
            effective = inherited_cleanup
        return _Candidate(payload, effective, release=registry_owner.release_retired_candidate,
                          raw_payload=payload.session)

    def _transfer_retirement(self, lease: AccountMutationLease, operation: _Operation,
                             registry_owner: Any, receipt: object,
                             cleanup: Callable[[object], None] | None) -> CleanupTicket:
        """One same-ticket move, with precise rollback if registry acceptance fails."""
        self._require_process()
        move: dict[str, Any] = {}
        with self._condition:
            duplicate = operation.retirements.get(receipt)
            if duplicate is not None:
                if duplicate[0] is not registry_owner:
                    from .account_mutation_contracts import RegistryCapabilityError  # noqa: PLC0415
                    raise RegistryCapabilityError
                return duplicate[1]

        def accept(payload: Any) -> CleanupTicket:
            from .account_mutation_contracts import RegistryCapabilityError  # noqa: PLC0415
            if payload.selector != operation.selector or not payload.managed:
                raise RegistryCapabilityError
            raw = payload.session
            with self._condition:
                previous_entry = self._candidates.get(id(raw))
                previous = None if previous_entry is None else previous_entry[2]
                if previous is not None:
                    if previous.raw_payload is not raw or (
                            previous.registry_owner is not None and previous.registry_owner is not registry_owner):
                        raise RegistryCapabilityError
                    if previous.worker is not None and not previous.worker.done():
                        raise RuntimeError("account_candidate_cleanup_pending")
                replacement = self._retired_candidate(payload, previous, cleanup, registry_owner)
                ticket = CleanupTicket() if previous_entry is None else previous_entry[1]
                prior_operation = None if previous_entry is None else self._operations[previous_entry[0]]
                # Construct everything first; retain rollback authority before the move.
                move.update(raw=raw, previous_entry=previous_entry, replacement=replacement,
                            ticket=ticket, prior_operation=prior_operation)
                self._custody_moves.add(id(raw))
                if prior_operation is not None and prior_operation is not operation:
                    prior_operation.candidates.pop(ticket)
                operation.candidates[ticket] = replacement
                operation.retirements[receipt] = (registry_owner, ticket)
                self._candidates[id(raw)] = (lease, ticket, replacement)
                return ticket

        try:
            return registry_owner.transfer_retired_candidate(receipt, accept)
        except BaseException:
            with self._condition:
                if move:
                    raw, ticket = move["raw"], move["ticket"]
                    if operation.candidates.get(ticket) is move["replacement"]:
                        operation.candidates.pop(ticket)
                    operation.retirements.pop(receipt, None)
                    previous_entry = move["previous_entry"]
                    if previous_entry is None:
                        self._candidates.pop(id(raw), None)
                    else:
                        self._candidates[id(raw)] = previous_entry
                        move["prior_operation"].candidates[ticket] = previous_entry[2]
            raise
        finally:
            with self._condition:
                if move:
                    self._custody_moves.discard(id(move["raw"]))
                self._condition.notify_all()

    def retain_retirement(self, lease: AccountMutationLease, registry_owner: Any, receipt: object, *,
                          cleanup: Callable[[object], None] | None = None) -> CleanupTicket:
        """Atomically move raw/prepared/live custody into one exact retired ticket."""
        self._require_process()
        self._validate_cleanup(cleanup)
        from flinttrade_gateway.registry import RegistryPublicationOwner  # noqa: PLC0415
        if type(registry_owner) is not RegistryPublicationOwner:
            raise RuntimeError("account_registry_owner_invalid")
        with self._rebuild_lock:
            with self._condition:
                operation = self._operation(lease)
            return self._transfer_retirement(lease, operation, registry_owner, receipt, cleanup)

    def _drain_generations(self, timeout: float) -> bool:
        self._require_process()
        result = self._retire_generations(timeout)
        if type(result) is not bool:
            if inspect.iscoroutine(result):
                result.close()
            raise TypeError("account_generation_retirement_invalid")
        return result

    def _retirement_worker(self, lease: AccountMutationLease, timeout: float) -> Future:
        self._require_process()
        with self._condition:
            operation = self._operation(lease)
            prior = operation.retirement_worker
            if prior is not None and (not prior.done() or (prior.exception() is None and prior.result() is True)):
                return prior
            future = _running_future()
            operation.retirement_worker = future
            operation.workers.add(future)
        future.add_done_callback(lambda _future: self._notify())
        def retire() -> bool:
            # Callback contract: zero wait revokes BOTH reads and writes.
            if self._drain_generations(0.0):
                return True
            return bool(self._drain_generations(timeout)) if timeout else False
        _launch(future, retire)
        return future

    def retire_generations(self, lease: AccountMutationLease, timeout: float) -> bool:
        """Run blocking drains in retained custody; use async variant on a loop."""
        self._require_process()
        timeout = _timeout(timeout)
        _require_sync_wait(timeout)
        require_backend_lease_proof(self._proof)
        future = self._retirement_worker(lease, timeout)
        try:
            return future.result(timeout) is True
        except FutureTimeout:
            return False

    async def retire_generations_async(self, lease: AccountMutationLease, timeout: float) -> bool:
        """Yield the caller loop while its admitted operations finish retirement."""
        self._require_process()
        timeout = _timeout(timeout)
        require_backend_lease_proof(self._proof)
        future = self._retirement_worker(lease, timeout)
        try:
            return await self.wait_worker(lease, future, timeout=timeout) is True
        except TimeoutError:
            return False

    def _generations_drained(self, operation: _Operation) -> bool:
        self._require_process()
        retirement = self._shutdown_retirement if not self._accepting else operation.retirement_worker
        return retirement is None or (
            retirement.done() and retirement.exception() is None and retirement.result() is True)

    def _start_cleanup(self, operation: _Operation, attempted: set[CleanupTicket]) -> None:
        self._require_process()
        launches = []
        with self._condition:
            if not self._generations_drained(operation) or any(not worker.done() for worker in operation.workers):
                return
            for ticket, candidate in operation.candidates.items():
                if (candidate.complete or candidate.registry_owner is not None
                        or candidate.cleanup is None or ticket in attempted
                        or id(candidate.raw_payload) in self._custody_moves):
                    continue
                prior = candidate.worker
                if prior is not None and (not prior.done() or prior.exception() is None):
                    continue
                attempted.add(ticket)
                future = _running_future()
                candidate.worker = future
                launches.append((future, ticket, candidate))
        for future, ticket, candidate in launches:
            def clean(candidate: _Candidate = candidate) -> None:
                result = candidate.cleanup(candidate.payload)
                if result is not None:
                    if inspect.iscoroutine(result):
                        result.close()
                    raise RuntimeError("account_candidate_cleanup_incomplete")
                if candidate.release is not None:
                    candidate.release(candidate.payload)
            def finished(future: Future, ticket: CleanupTicket = ticket, candidate: _Candidate = candidate) -> None:
                with self._condition:
                    if future.exception() is None:
                        identity = id(candidate.raw_payload)
                        retained = self._candidates.get(identity)
                        if retained is not None and retained[1] is ticket and retained[2] is candidate:
                            self._candidates.pop(identity)
                        candidate.complete = True
                        candidate.payload = None
                        candidate.raw_payload = None
                        candidate.cleanup = None
                        candidate.release = None
                    self._condition.notify_all()
            future.add_done_callback(finished)
            _launch(future, clean)

    def settle(self, lease: AccountMutationLease, *, durable_disposition: bool = False) -> bool:
        """Release the volatile lane only after workers and explicit cleanup finish.

        The coordinator alone decides whether its durable claim may be released.
        Do not invoke settlement for authentication-unknown/blocked durable claims.
        """
        self._require_process()
        if type(durable_disposition) is not bool:
            raise TypeError("account_durable_disposition_invalid")
        with self._rebuild_lock:
            with self._condition:
                if (type(lease) is AccountMutationLease and lease in self._operations
                        and self._operations[lease].settled):
                    return True
                operation = self._operation(lease)
                # A terminal settlement attempt closes publication before local
                # cleanup can touch the unpublished payload, even on timeout.
                operation.abandoned = True
            self._start_cleanup(operation, set())
            with self._condition:
                if not self._generations_drained(operation) or any(not worker.done() for worker in operation.workers):
                    return False
                if any((not candidate.complete and candidate.registry_owner is None)
                       or (candidate.worker is not None and not candidate.worker.done())
                       for candidate in operation.candidates.values()):
                    return False
                if operation.durable_claim_release is not None:
                    if not durable_disposition:
                        return False
                    result = operation.durable_claim_release()
                    if result is not None:
                        raise RuntimeError("account_durable_disposition_incomplete")
                    operation.durable_claim_release = None
                operation.settled = True
                operation.workers.clear()
                if self._active is lease:
                    self._active = None
                self._condition.notify_all()
                return True

    def forget_settled(self, lease: AccountMutationLease) -> None:
        """Drop a settled pre-admission lease so the same operation can begin again.

        A durable claim must already have been released. This does not grant a
        new lane; the caller has to ``begin`` one.
        """
        self._require_process()
        with self._condition:
            operation = self._operations.get(lease)
            if (operation is None or not operation.settled or self._active is lease
                    or operation.durable_claim_release is not None):
                raise RuntimeError("account_mutation_lease_unforgettable")
            del self._operations[lease]

    def _retire_live_candidates(self, deadline: float) -> None:
        """Recover only exact registry custody; an unclaimable payload stays owned."""
        self._require_process()
        if not self._rebuild_lock.acquire(timeout=max(0.0, deadline - time.monotonic())):
            return
        try:
            with self._condition:
                live = tuple((lease, operation, candidate) for lease, operation in self._operations.items()
                             for candidate in operation.candidates.values()
                             if not candidate.complete and candidate.registry_owner is not None)
            from .account_mutation_contracts import RegistryVersionConflict  # noqa: PLC0415
            for lease, operation, candidate in live:
                publication = candidate.registry_owner
                payload = candidate.payload
                binding = candidate.registry_binding
                current = publication.live_candidate_version(payload)
                if current == binding:
                    try:
                        result = publication.remove_session_for_exact(
                            binding.selector, expected_registry=binding.registry_version)
                    except RegistryVersionConflict:
                        receipt = publication.retirement_for_candidate(payload)
                    else:
                        receipt = result.retired
                else:
                    # A successor is untouchable. Only the original payload's
                    # retained retirement can give local cleanup authority.
                    receipt = publication.retirement_for_candidate(payload)
                if receipt is None:
                    continue
                self._transfer_retirement(lease, operation, publication, receipt, None)
        finally:
            self._rebuild_lock.release()

    def close_and_drain(self, timeout: float) -> bool:
        """Close admission first, then drain without holding completion/publication locks."""
        self._require_process()
        timeout = _timeout(timeout)
        _require_sync_wait(timeout)
        deadline = time.monotonic() + timeout
        with self._condition:
            self._accepting = False
            for operation in self._operations.values():
                operation.abandoned = True
        if not self._rebuild_lock.acquire(timeout=max(0.0, deadline - time.monotonic())):
            return False
        self._rebuild_lock.release()
        with self._condition:
            retirement = self._shutdown_retirement
            if retirement is None or (retirement.done() and (
                    retirement.exception() is not None or retirement.result() is not True)):
                retirement = _running_future()
                self._shutdown_retirement = retirement
                launch = True
            else:
                launch = False
        def launch_retirement(future: Future) -> None:
            try:
                zero_drained = self._drain_generations(0.0)
            except BaseException as exc:  # noqa: BLE001 - preserve exact failed retirement
                future.set_exception(exc)
            else:
                if zero_drained:
                    future.set_result(True)
                else:
                    _launch(future, lambda: bool(self._drain_generations(
                        max(0.0, deadline - time.monotonic()))))
            future.add_done_callback(lambda _future: self._notify())

        if launch:
            launch_retirement(retirement)
        attempted: set[CleanupTicket] = set()
        while True:
            if retirement.done() and retirement.exception() is None and retirement.result() is True:
                self._retire_live_candidates(deadline)
            operations = tuple(self._operations.items())
            for _, operation in operations:
                self._start_cleanup(operation, attempted)
            with self._condition:
                ready = (self._rebuild_intent is None and not self._custody_moves and retirement.done()
                         and retirement.exception() is None and retirement.result() is True)
                for lease, operation in operations:
                    pending = not self._generations_drained(operation) or any(
                        not worker.done() for worker in operation.workers)
                    pending = pending or any(not item.complete or (item.worker is not None and not item.worker.done())
                                             for item in operation.candidates.values())
                    pending = pending or operation.durable_claim_release is not None
                    if not pending:
                        operation.settled = True
                        operation.workers.clear()
                        if self._active is lease:
                            self._active = None
                    ready = ready and not pending
                if ready:
                    with _OWNERS_LOCK:
                        if _OWNERS.get(self._key) is self:
                            _OWNERS.pop(self._key)
                    return True
                if (retirement.done() and retirement.exception() is None and retirement.result() is True
                        and any(op.durable_claim_release is not None for _, op in operations)
                        and all(self._generations_drained(op) and all(worker.done() for worker in op.workers)
                                and all(item.complete for item in op.candidates.values()) for _, op in operations)):
                    return False
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    return False
                # Failures/quarantine need a later explicit local retry.
                if retirement.done() and (retirement.exception() is not None or retirement.result() is not True):
                    if launch:
                        return False
                    # A previous attempt may finish False during this retry.
                    # Restart only after that genuine bridge is terminal.
                    current = self._shutdown_retirement
                    if current is retirement:
                        retirement = _running_future()
                        self._shutdown_retirement = retirement
                        retry_launch = True
                    else:
                        retirement = current
                        retry_launch = False
                    launch = True
                else:
                    retry_launch = False
                if any(item.cleanup is None and not item.complete for _, op in operations for item in op.candidates.values()):
                    return False
                if any(item.worker is not None and item.worker.done() and item.worker.exception() is not None
                       for _, op in operations for item in op.candidates.values()):
                    return False
                if not retry_launch:
                    self._condition.wait(remaining)
            if retry_launch:
                launch_retirement(retirement)

    async def close_and_drain_async(self, timeout: float) -> bool:
        """Retain the shutdown bridge even if its asyncio borrower is cancelled."""
        self._require_process()
        timeout = _timeout(timeout)
        deadline = time.monotonic() + timeout
        with self._condition:
            future = self._async_shutdown
            if future is None or future.done():
                future = _running_future()
                self._async_shutdown = future
                launch = True
            else:
                launch = False
        if launch:
            _launch(future, lambda: self.close_and_drain(timeout))
        wrapped = asyncio.wrap_future(future)
        wrapped.add_done_callback(lambda value: None if value.cancelled() else value.exception())
        try:
            return await asyncio.wait_for(asyncio.shield(wrapped), max(0.0, deadline - time.monotonic()))
        except TimeoutError:
            return False

    def snapshot(self) -> AccountLifecycleSnapshot:
        """Return redacted volatile status; never a durable committed outcome."""
        self._require_process()
        with self._condition:
            operations = tuple(self._operations.values())
            candidates = tuple(item for operation in operations for item in operation.candidates.values())
            rebuild = self._rebuild_intent
            return AccountLifecycleSnapshot(
                self._accepting, self._active is not None or rebuild is not None,
                sum(not worker.done() for operation in operations for worker in operation.workers)
                + int(rebuild is not None and rebuild.worker is not None and not rebuild.worker.done()),
                sum((not item.complete and (not self._accepting or item.registry_owner is None))
                    or (item.worker is not None and not item.worker.done()) for item in candidates),
                sum(not item.complete and item.cleanup is None for item in candidates),
                sum(not item.complete and item.registry_owner is not None for item in candidates))
