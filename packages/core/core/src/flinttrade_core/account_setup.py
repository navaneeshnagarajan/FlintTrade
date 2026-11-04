"""Canonical account composition with explicit authentication and local custody.

Normal-factory drivers support setup, reconnect, removal and typed account
reads. Durable recovery never authenticates; unknown claims survive disposal.
Account evidence does not create ACLs, execution defaults or qualification.
"""

from __future__ import annotations

import asyncio
import inspect
import json
import threading
import time
from collections.abc import Callable, Mapping
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any
from uuid import UUID

from flask import Flask, Response

from flinttrade_gateway.account_transaction_store import AccountOperationConflict, AccountTransactionStore
from flinttrade_gateway.credentials import CredentialStore, _family_lock
from flinttrade_gateway.native_login import NativeSessionCandidate, prepare_native_session
from flinttrade_gateway.rate_limiter import BrokerRateLimiter

from .account_lifecycle_contracts import (
    ACCOUNT_JSON_MAX_BYTES,
    AccountActorContext,
    AccountContractError,
    AccountMutationKind,
    AccountMutationOutcome,
    AccountMutationRequest,
    canonical_account_json,
)
from .backend_instance import require_backend_lease_proof
from .broker_account_cutover import BrokerAccountCutoverUnavailable
from .broker_account_lifecycle import BrokerAccountLifecycleOwner
from .broker_account_transactions import BrokerAccountReadRuntime, BrokerAccountTransactionCoordinator
from .broker_account_workspace import BrokerAccountWorkspace
from .broker_identity import BrokerSelector
from .secure_file import HeldOwnerDirectory
from .workspace_migrations import broker_workspace_version, read_workspace_snapshot

_EXTENSION = "flinttrade.account_setup"
_LIFECYCLE = "flinttrade.broker_account_lifecycle_owner"


@dataclass(frozen=True)
class AccountSetupDriver:
    """Explicit external authentication and idempotent *local-only* disposal.

    There is deliberately no reflective SDK logout/close.
    The composer must supply a reviewed local cleanup contract, not an SDK
    logout which may send a broker request. This descriptor grants no custody.

    Attributes:
        adapter_id: Exact adapter identity admitted by this descriptor.
        adapter: Explicit external authentication/probe provider.
        local_cleanup: Idempotent synchronous local-only disposal; None confirms
            completion. The factory lifecycle, not this descriptor, owns retry.
        validate_request: Optional pure validation of the exact account and
            credential shape before any external authentication.
    """

    adapter_id: str
    adapter: object
    local_cleanup: Callable[[object], None]
    validate_request: Callable[[BrokerSelector, Mapping[str, object]], None] | None = None

    def __post_init__(self) -> None:
        BrokerSelector(self.adapter_id, "validation")
        if (
            self.adapter_id == "openalgo"
            or getattr(self.adapter, "broker_id", None) != self.adapter_id
            or not callable(getattr(self.adapter, "login", None))
            or not callable(self.local_cleanup)
            or inspect.iscoroutinefunction(self.local_cleanup)
            or self.validate_request is not None
            and not callable(self.validate_request)
        ):
            raise BrokerAccountCutoverUnavailable


def create_fresh_setup_store(path: Path, proof: object, password: str) -> CredentialStore:
    """Reject every existing vault family before its migrating constructor.

    The real backend lease excludes other cooperative processes; the vault's
    family lock excludes in-process constructors. Retained directory custody is
    checked on both sides. This is not a migration or legacy adoption protocol.

    Args:
        path: Exact workspace covered by the live backend proof.
        proof: Current process-bound backend lease proof.
        password: Key material for the newly created encrypted credential store.

    Returns:
        A fresh credential store, not an enrolled or authorised account.

    Raises:
        BrokerAccountCutoverUnavailable: Storage is not fresh or custody differs.
    """
    proof = require_backend_lease_proof(proof)
    if path != proof.workspace_path:
        raise BrokerAccountCutoverUnavailable
    with _family_lock(path / "credentials.db"), HeldOwnerDirectory(path) as directory:
        if any(
            directory.existing_member("credentials.db" + suffix) is not None
            for suffix in ("", "-wal", "-shm", "-journal")
        ):
            raise BrokerAccountCutoverUnavailable
        snapshot = read_workspace_snapshot(path)
        config = snapshot.as_dict()
        if config.get("_broker_account_store") is not None or config.get("brokers", {}).get("registered"):
            raise BrokerAccountCutoverUnavailable
        store = CredentialStore(path / "credentials.db", password)
        try:
            directory.revalidate()
            require_backend_lease_proof(proof)
        except BaseException:
            store.close()
            raise
        return store


def open_setup_store(path: Path, proof: object, password: str) -> CredentialStore:
    """Open/migrate the existing encrypted consumer under exact lease custody.

    A missing participant beside durable account metadata is not a fresh
    installation. The versioned vault migrations authenticate retained payloads
    and roll back atomically; workspace enrolment/recovery follows separately.

    Args:
        path: Exact workspace covered by the live backend proof.
        proof: Existing process-bound backend lease proof.
        password: Key for the existing encrypted credential consumer.

    Returns:
        The authenticated vault consumer, without any broker login or session.

    Raises:
        BrokerAccountCutoverUnavailable: Participant presence or custody differs.
        RuntimeError: Durable validation or decryption fails; no empty replacement
            is created for an unavailable enrolled participant.
    """
    proof = require_backend_lease_proof(proof)
    if path != proof.workspace_path:
        raise BrokerAccountCutoverUnavailable
    with _family_lock(path / "credentials.db"), HeldOwnerDirectory(path) as directory:
        config = read_workspace_snapshot(path).as_dict()
        if directory.existing_member("credentials.db") is None and (
            config.get("_broker_account_store") is not None or config.get("brokers", {}).get("registered")
        ):
            raise BrokerAccountCutoverUnavailable
        store = CredentialStore(path / "credentials.db", password, verify_existing_credentials=True)
        try:
            directory.revalidate()
            require_backend_lease_proof(proof)
        except BaseException:
            store.close()
            raise
        return store


class _OwnedDriver:
    def __init__(
        self, driver: AccountSetupDriver, admission: Callable[[], None], lifecycle: BrokerAccountLifecycleOwner
    ) -> None:
        self.driver = driver
        self.admission = admission
        self.lifecycle = lifecycle

    def authenticate(
        self, request: AccountMutationRequest, credentials: Mapping[str, object], prior_retirement: object | None
    ) -> NativeSessionCandidate:
        """Retain the real payload before strict probing; propagate uncertainty."""
        if (
            request.kind not in (AccountMutationKind.CONNECT, AccountMutationKind.RECONNECT)
            or request.selector.adapter_id != self.driver.adapter_id
        ):
            raise BrokerAccountCutoverUnavailable
        if self.driver.validate_request is not None:
            self.driver.validate_request(request.selector, credentials)
        # The coordinator already began this exact lane and installed its durable
        # release callback. Capture that same lease before external work: a late
        # result must remain retainable even after admission/shutdown is closed.
        lease = self.lifecycle.begin(request.operation_id, request.selector)

        def accept(candidate: NativeSessionCandidate) -> None:
            self.lifecycle.retain_candidate(lease, candidate.session, self.cleanup)

        return asyncio.run(
            prepare_native_session(
                self.driver.adapter,
                dict(credentials),
                verify=True,
                strict_probe=True,
                accept_candidate=accept,
                mutation_admission=self.admission,
            )
        )

    def cleanup(self, payload: object) -> None:
        """Delegate only the explicit local contract; never infer SDK disposal."""
        return self.driver.local_cleanup(payload)


class AccountSetup:
    """Factory-owned account facade over the existing durable coordinator."""

    def __init__(self, app: Flask, driver: AccountSetupDriver | tuple[AccountSetupDriver, ...]) -> None:
        """Compose exact factory owners before enrolment or durable recovery.

        Args:
            app: Normal factory application with its own vault, registry and lease.
            driver: Explicit external driver and local disposal contract, or the
                production tuple; every descriptor shares the existing owners.

        Raises:
            BrokerAccountCutoverUnavailable: Composition or owner identity differs.
        """
        from .app import credential_version_reader, registry_publication_owner_for, retire_broker_dependencies

        drivers = driver if type(driver) is tuple else (driver,)
        if (
            not drivers
            or any(type(item) is not AccountSetupDriver for item in drivers)
            or app.extensions.get(_EXTENSION) is not None
        ):
            raise BrokerAccountCutoverUnavailable
        for item in drivers:
            item.__post_init__()
        self.drivers = {item.adapter_id: item for item in drivers}
        if len(self.drivers) != len(drivers):
            raise BrokerAccountCutoverUnavailable
        self.production = type(driver) is tuple
        self.app = app
        self.driver = driver
        self.proof = require_backend_lease_proof(app.config.get("BACKEND_LEASE_PROOF"))
        self.path = self.proof.workspace_path
        self.credentials = app.config["CREDENTIAL_STORE"]
        self.registry = app.config["REGISTRY"]
        self.execution_owner = app.config.get("EXECUTION_SESSIONS")
        self.registry_owner = registry_publication_owner_for(app, self.registry)
        self._read_dependencies = None
        self.store = AccountTransactionStore(self.credentials, workspace_path=self.path, backend_proof=self.proof)
        self.workspace = BrokerAccountWorkspace(self.path, self.store, self.proof)
        self.runtime = BrokerAccountReadRuntime(
            registry=self.registry,
            workspace_path=self.path,
            credential_version_for=credential_version_reader(self.credentials),
            adapters={item.adapter_id: item.adapter for item in drivers},
            rate_limiter=BrokerRateLimiter.from_capabilities(
                {item.adapter_id: item.adapter.capabilities for item in drivers},
                overrides=read_workspace_snapshot(self.path).as_dict()["brokers"].get("rate_limits", {}),
            )
            if self.production
            else BrokerRateLimiter({}),
            runtime_accepting_requests=self.accepting,
            publish_generation=self._publish_reads if self.production else None,
        )

        def retire(timeout):
            deadline = time.monotonic() + timeout
            local = self.runtime.retire(timeout)
            shared = retire_broker_dependencies(app, timeout=max(0.0, deadline - time.monotonic()))
            if shared:
                self._read_dependencies = None
            return local and shared

        if app.extensions.get(_LIFECYCLE) is not None:
            raise BrokerAccountCutoverUnavailable
        self.lifecycle = BrokerAccountLifecycleOwner(
            self.path,
            self.proof,
            retire_generations=retire,
            rebuild_lock=app.config.setdefault("BROKER_ROUTER_REBUILD_LOCK", threading.RLock()),
        )
        # Publish custody before enrolment can fail; ordinary factory rollback
        # and shutdown retain and drain this exact owner.
        app.extensions[_LIFECYCLE] = self.lifecycle
        self._lane = threading.Lock()
        self._coordinators = {}
        self._recovery_coordinator = None
        if self.production:
            # Only an empty process-local registry may adopt durable storage.
            # No live reader/session is overwritten or recreated from a receipt.
            if any(state.binding is not None for state in self.registry.list_exact_states()) or not retire(5.0):
                raise BrokerAccountCutoverUnavailable
            active = self.store.active_operation(self.store.owner_capability(self.proof))
            recovery_driver = self.drivers.get(active.selector.adapter_id) if active is not None else drivers[0]
            if recovery_driver is None:
                raise BrokerAccountCutoverUnavailable
            self._recovery_coordinator = BrokerAccountTransactionCoordinator(
                self.store,
                self.workspace,
                self.lifecycle,
                self.registry_owner,
                _OwnedDriver(recovery_driver, self.require_current, self.lifecycle),
                self.runtime,
                self.require_current,
            )
            deadline = time.monotonic() + 5.0
            while True:
                receipts = self._recovery_coordinator.recover()
                active = self.store.active_operation(self.store.owner_capability(self.proof))
                if active is None or not receipts or receipts[0].state.value not in {"committed", "rejected"}:
                    break
                if time.monotonic() >= deadline:
                    raise BrokerAccountCutoverUnavailable
                time.sleep(0.01)
        else:
            self.workspace.enrol()
        app.extensions[_EXTENSION] = self
        self.require_current()
        if self.production:
            self.runtime.rebuild(self.workspace.assert_coherent(), coherence_verifier=self.workspace.assert_coherent)

    def _publish_reads(self, snapshot) -> None:
        """Publish the same typed read owner to normal app consumers, never writes."""
        from .app import _prepare_broker_dependencies, _publish_broker_dependencies_locked, credential_version_reader

        self._require_owners()
        with self.app.config["BROKER_ROUTER_REBUILD_LOCK"]:
            connected = {
                state.selector.adapter_id
                for state in self.registry.list_exact_states()
                if state.binding is not None and state.status == "connected"
            }
            dependencies = _prepare_broker_dependencies(
                self.registry,
                snapshot.as_dict()["brokers"],
                adapters={key: driver.adapter for key, driver in self.drivers.items() if key in connected},
                broker_client=self.app.config.get("CLIENT"),
                lifecycle_store=self.app.config.get("ORDER_LIFECYCLE_LEDGER"),
                workspace_snapshot=snapshot,
                workspace_path=self.path,
                registry_publication_owner=self.registry_owner,
                credential_version_for=credential_version_reader(self.credentials),
                coherence_verifier=self.workspace.assert_coherent,
                enrollment_required=self.credentials.account_protocol_enrolled,
            )
            dependencies.session_provider = self.runtime._provider
            dependencies.read_owner = self.runtime.read_owner
            dependencies.rate_limiter = self.runtime._rate_limiter
            if self.app.config.get("BROKER_ROUTER") is not None or not _publish_broker_dependencies_locked(
                self.app, dependencies
            ):
                raise BrokerAccountCutoverUnavailable
            self._read_dependencies = dependencies

    def accepting(self) -> bool:
        """Read admission status only, not session, read or trading availability.

        Returns:
            Whether the app currently permits requests; custody checks are separate.
        """
        return self.app.config.get("RUNTIME_ACCEPTING_REQUESTS", True) is True

    def _require_owners(self) -> None:
        if (
            self.app.extensions.get(_EXTENSION) is not self
            or self.app.extensions.get(_LIFECYCLE) is not self.lifecycle
            or self.app.config.get("CREDENTIAL_STORE") is not self.credentials
            or self.app.config.get("REGISTRY") is not self.registry
            or self.app.extensions.get("flinttrade.registry_publication_owner") is not self.registry_owner
            or self.app.config.get("BACKEND_LEASE_PROOF") is not self.proof
            or not self.registry_owner.owns(self.registry)
            or self._read_dependencies is not None
            and self.app.extensions.get("flinttrade_broker_dependencies") is not self._read_dependencies
            or not self.accepting()
            or not self.lifecycle.snapshot().accepting
        ):
            raise BrokerAccountCutoverUnavailable
        self.lifecycle.assert_bound(self.path, self.proof)

    def require_current(self) -> None:
        """Require current owner custody and coherent enrolled participants.

        Raises:
            BrokerAccountCutoverUnavailable: An owner or admission slot changed.
            RuntimeError: The lease or durable participant coherence is unavailable.
        """
        self._require_owners()
        self.workspace.assert_coherent()

    def _require_mutation_owners(self, *, empty_custody: bool = True) -> None:
        """Keep retained native custody out of an account cutover.

        The actual execution owner inspects its stores, not a storage-presence
        shortcut. Publication additionally holds its nonblocking local fence.
        Reads and account metadata do not receive this exclusion.
        """
        self._require_owners()
        if self.production:
            from .execution_sessions import ExecutionSessions

            owner = self.app.config.get("EXECUTION_SESSIONS")
            if (
                type(owner) is not ExecutionSessions
                or owner is not self.execution_owner
                or owner.app is not self.app
                or owner.proof is not self.proof
            ):
                raise BrokerAccountCutoverUnavailable
            owner._require()
            try:
                if empty_custody:
                    with owner.native_account_fence():
                        pass
            except (ValueError, RuntimeError):
                raise BrokerAccountCutoverUnavailable from None

    def _native_mutation_fence(self, lease):
        """Borrow local custody only inside the actual account lease publication."""
        from contextlib import contextmanager

        from .broker_account_lifecycle import AccountMutationLease

        @contextmanager
        def fenced():
            if type(lease) is not AccountMutationLease:
                raise BrokerAccountCutoverUnavailable
            self._require_mutation_owners()
            if self.production:
                with self.execution_owner.native_account_fence():
                    yield
            else:
                yield
        return fenced()

    def _native_recovery_fence(self, request: AccountMutationRequest, attempt: Any, phase: str) -> Any:
        """Validate candidate and final census under the actual local publication fence."""
        from contextlib import contextmanager

        from .account_lifecycle_contracts import ReadOnlyRecoveryOutcome

        @contextmanager
        def fenced() -> Any:
            """Hold same-owner custody only for local assessment or final publication."""
            self._require_mutation_owners(empty_custody=False)
            with self.execution_owner.native_recovery_fence(request, attempt.recovery) as assessment:
                attempt.recovery = assessment
                if assessment is not None and attempt.candidate is not None:
                    candidate = attempt.candidate
                    candidate.require_identity(
                        self.drivers[request.selector.adapter_id].adapter, request.selector.account_id
                    )
                    if candidate.expires_at <= time.time():
                        raise ValueError("native_recovery_candidate_expired")
                    candidate.session.read_only_lifetime = True
                    candidate.session.read_only_until_at = candidate.expires_at
                    candidate.session.extra["_read_only_recovery"] = ReadOnlyRecoveryOutcome(
                        request.selector, assessment.census, assessment.run_ids)
                yield
                if assessment is not None and phase == "publish":
                    version = self.registry_owner.live_candidate_version(attempt.candidate.session)
                    if version is None or version.credential_version == request.expected_credential:
                        raise ValueError("native_recovery_publication_unavailable")
                    self.execution_owner.autonomy.record_read_only_recovery(assessment, version)
        return fenced()

    def require_mutation_current(self) -> None:
        """Require exact custody and coherent participants before external work."""
        self._require_mutation_owners()
        self.workspace.assert_coherent()

    def _admit_legacy_reconnect(self, request: AccountMutationRequest) -> None:
        """Adopt only an exact migrated row through fresh explicit authentication.

        Legacy candidate/interim provenance is not a migration proof. Existing
        encrypted credentials and ACLs stay untouched until the normal witness
        commits; this callback grants neither reads nor execution.
        """
        self.require_current()
        state = self.credentials.selector_state(request.selector)
        if (
            not self.production
            or request.kind is not AccountMutationKind.RECONNECT
            or request.credentials is None
            or state.origin != "legacy_pre_workspace_authority"
            or state.version != request.expected_credential
            or f"{request.selector.adapter_id}:{request.selector.account_id}"
            not in self.workspace.assert_coherent().as_dict()["brokers"]["registered"]
        ):
            raise BrokerAccountCutoverUnavailable
        self.drivers[request.selector.adapter_id].validate_request(request.selector, request.credentials)

    def connect(
        self,
        body: dict[str, Any],
        operation_id: UUID,
        token: str,
        *,
        kind: AccountMutationKind = AccountMutationKind.CONNECT,
    ) -> AccountMutationOutcome:
        """Borrow the existing coordinator for CONNECT or exact durable replay.

        Args:
            body: Strictly parsed CONNECT body, with no ACL/default authority.
            operation_id: Literal canonical action identity from raw ingress.
            token: Full operator session reverified at admission and publication.
            kind: Explicit CONNECT, RECONNECT or REMOVE intent; replay must retain
                its original kind and exact account identity.

        Returns:
            Durable disposition and separate current runtime availability. Unknown
            authentication remains blocked and owned; it is never a retry grant.

        Raises:
            AccountOperationConflict: A key conflicts or a different lane is held.
            BrokerAccountCutoverUnavailable: Required admission/custody is absent.
            PermissionError: The verified principal lacks account management scope.
        """
        from .auth_routes import verify_operator_session_token

        def principal() -> AccountActorContext:
            # The coordinator may hold the workspace publication lock here;
            # its participant owns coherence. Never recursively take that lock.
            """Verify the current operator and exact factory owners without recursive workspace locking."""
            self._require_mutation_owners(empty_custody=False)
            with self.app.app_context():
                verified = verify_operator_session_token(token)
            if "admin.accounts.write" not in verified.scopes:
                raise PermissionError("account_setup_scope_required")
            return AccountActorContext(verified.actor_ref, verified.session_binding)

        actor = principal()
        self.require_current()
        selector = BrokerSelector(body["adapter_id"], body["account_id"])
        driver = self.drivers.get(selector.adapter_id)
        if driver is None:
            raise BrokerAccountCutoverUnavailable
        if kind is not AccountMutationKind.CONNECT and not self.production:
            raise BrokerAccountCutoverUnavailable
        if driver.validate_request is not None and body.get("credentials") is not None:
            driver.validate_request(selector, body["credentials"])
        if not self._lane.acquire(blocking=False):
            raise AccountOperationConflict
        try:
            try:
                original = self.store.operation(operation_id)
            except AccountOperationConflict:
                original = None
            if original is None:
                if self.production and kind is not AccountMutationKind.REMOVE:
                    from .native_account_routes import _native_sdk_not_ready_body

                    with self.app.app_context():
                        if _native_sdk_not_ready_body(selector.adapter_id) is not None:
                            raise BrokerAccountCutoverUnavailable
                snapshot = self.workspace.assert_coherent()
                expected_workspace = snapshot.version
                expected_brokers = broker_workspace_version(snapshot)
                expected_credential = self.credentials.selector_state(selector).version
                if (
                    kind is AccountMutationKind.RECONNECT
                    and body.get("credentials") is None
                    and driver.validate_request is not None
                ):
                    driver.validate_request(selector, self.store.native_credentials(selector, expected_credential))
            else:
                # Preserve original revisions, including after commit/restart.
                # The store's keyed request MAC, not these public observations,
                # decides equality of body, actor/session, kind and selector.
                if original.selector != selector or original.actor != actor or original.kind is not kind:
                    raise AccountOperationConflict
                expected_workspace = original.expected_workspace
                expected_brokers = original.expected_broker_workspace
                expected_credential = original.expected_credential
            if expected_workspace is None or expected_brokers is None:
                raise BrokerAccountCutoverUnavailable
            action = AccountMutationRequest(
                operation_id,
                kind,
                selector,
                actor,
                expected_workspace,
                expected_brokers,
                expected_credential,
                selector.adapter_id,
                body.get("label", selector.adapter_id),
                body.get("credentials"),
            )
            self.store.existing_request(action)  # Conflict before creating a new volatile owner.
            def admission() -> None:
                """Recheck actual owners and coherent storage; recovery is fenced by phase."""
                self._require_mutation_owners(empty_custody=kind is not AccountMutationKind.RECONNECT)
                self.workspace.assert_coherent()

            coordinator = self._coordinators.get(operation_id)
            if coordinator is None:
                if self._coordinators:
                    raise AccountOperationConflict
                coordinator = BrokerAccountTransactionCoordinator(
                    self.store,
                    self.workspace,
                    self.lifecycle,
                    self.registry_owner,
                    _OwnedDriver(driver, admission, self.lifecycle),
                    self.runtime,
                    admission,
                    verify_current_actor=principal,
                    mutation_fence=self._native_mutation_fence,
                    recovery_fence=self._native_recovery_fence if self.production else None,
                    legacy_reconnect_admission=self._admit_legacy_reconnect if self.production else None,
                )
                self._coordinators[operation_id] = coordinator
            try:
                return asyncio.run(coordinator.mutate(action, timeout=30.0))
            finally:
                # Only an unsettled attempt needs volatile callback custody.
                # Terminal replay uses the durable original revisions/MAC;
                # do not retain every completed request's session token.
                if not self.lifecycle.snapshot().active:
                    self._coordinators.pop(operation_id, None)
        finally:
            self._lane.release()


def setup_for(app: Flask) -> AccountSetup | None:
    """Find this app's exact facade without granting admission or availability.

    Args:
        app: Factory application whose extension slot is inspected.

    Returns:
        Its exact facade, or None for an absent/foreign owner.
    """
    value = app.extensions.get(_EXTENSION)
    if type(value) is not AccountSetup or value.app is not app:
        return None
    return value


def read_http(app: Flask, selector: BrokerSelector, kind: str) -> Response:
    """Borrow and revoke an exact typed read port under verified human ACLs.

    This path cannot authenticate, select a default, issue execution grants or
    treat an absent book as empty. Revocation is checked again before return.

    Args:
        app: Exact normal-factory application owning the read runtime.
        selector: Literal broker and account identity, never a default selector.
        kind: One of funds, positions, holdings, orders or trades.

    Returns:
        A no-store response with typed value and provenance, or explicit
        unauthorised/unavailable status without an invented empty book.
    """
    from flask import jsonify

    from flinttrade_engine.request_context import RequestContext

    from .auth_routes import decode_token, verify_operator_session_token
    from .auth_scopes import _session_token
    from .broker_read_port import (
        BrokerOrderFamily,
        BrokerReadFailure,
        BrokerReadSuccess,
        ExactReadTarget,
        OrderStateRequest,
    )

    def response(body, code):
        result = jsonify(body)
        result.status_code = code
        result.headers["Cache-Control"] = "no-store"
        return result

    setup = setup_for(app)
    token = _session_token() or ""
    port = None
    owner = None
    try:
        verified = verify_operator_session_token(token)
        if "admin.accounts.read" not in verified.scopes:
            return response({"error": "account_read_unauthorised"}, 403)
        if setup is None or not setup.production or kind not in {"funds", "positions", "holdings", "orders", "trades"}:
            return response({"error": "account_read_unsupported"}, 409)
        setup.require_current()
        owner = setup.runtime.read_owner
        if owner is None:
            return response({"error": "account_read_unavailable"}, 409)

        def authority():
            with app.app_context():
                setup.require_current()
                if setup.runtime.read_owner is not owner or verify_operator_session_token(token) != verified:
                    raise PermissionError
                payload = decode_token(token)
                return RequestContext(
                    payload["jti"],
                    "human",
                    payload["sub"],
                    payload["mode"],
                    selector=f"{selector.adapter_id}:{selector.account_id}",
                )

        port = owner.bind(target=ExactReadTarget(selector), verify_current_authority=authority)
        if type(port) is BrokerReadFailure:
            return response({"error": port.code.value}, 403 if port.code.value == "unauthorised" else 409)
        if kind == "orders":
            read = port.order_states(OrderStateRequest(BrokerOrderFamily.REGULAR))
        else:
            read = getattr(
                port, {"funds": "balance", "positions": "positions", "holdings": "holdings", "trades": "trades"}[kind]
            )()
        outcome = asyncio.run(read)
        authority()
        if type(outcome) is BrokerReadFailure:
            return response({"error": outcome.code.value}, 409)
        if type(outcome) is not BrokerReadSuccess:
            raise BrokerAccountCutoverUnavailable
        value = [asdict(item) for item in outcome.value] if type(outcome.value) is tuple else asdict(outcome.value)
        return response({"status": "success", "data": value, "provenance": asdict(outcome.provenance)}, 200)
    except PermissionError:
        return response({"error": "account_read_unauthorised"}, 403)
    except Exception:
        return response({"error": "account_read_unavailable"}, 409)
    finally:
        if owner is not None and port is not None:
            owner.revoke(port)


def parse_connect(raw: bytes, key: str, *, selector: BrokerSelector | None = None) -> tuple[dict[str, Any], UUID]:
    """Validate raw ingress without fallback, aliases, truthiness or ID repair.

    Args:
        raw: Bounded UTF-8 JSON bytes from the authenticated request.
        key: Literal canonical UUIDv4 Idempotency-Key header.
        selector: Exact route-bound selector for reconnect/remove bodies, or
            None for a new CONNECT body.

    Returns:
        Validated body and action identity; neither grants admission.

    Raises:
        AccountContractError: The body or key violates the narrow CONNECT schema.
    """

    def pairs(items):
        result = {}
        for name, value in items:
            if name in result:
                raise AccountContractError
            result[name] = value
        return result

    try:
        if len(raw) > ACCOUNT_JSON_MAX_BYTES or type(key) is not str:
            raise AccountContractError
        operation_id = UUID(key)
        if str(operation_id) != key or operation_id.version != 4:
            raise AccountContractError
        body = json.loads(raw.decode("utf-8"), object_pairs_hook=pairs)
        if selector is not None:
            if type(body) is not dict or set(body) - {"credentials"}:
                raise AccountContractError
            if "credentials" in body and (type(body["credentials"]) is not dict or not body["credentials"]):
                raise AccountContractError
            canonical_account_json(body)
            return {"adapter_id": selector.adapter_id, "account_id": selector.account_id, **body}, operation_id
        if type(body) is not dict or set(body) - {"adapter_id", "account_id", "label", "credentials", "is_primary"}:
            raise AccountContractError
        BrokerSelector(body["adapter_id"], body["account_id"])
        if "is_primary" in body and body["is_primary"] is not False:
            raise AccountContractError
        if "label" in body and (type(body["label"]) is not str or len(body["label"]) > 256):
            raise AccountContractError
        if type(body["credentials"]) is not dict or not body["credentials"]:
            raise AccountContractError
        canonical_account_json(body)
        return body, operation_id
    except (ValueError, KeyError, TypeError, RecursionError, UnicodeError):
        raise AccountContractError from None


def connect_http(
    app: Flask, *, selector: BrokerSelector | None = None, kind: AccountMutationKind | None = None
) -> Response:
    """Serialise durable disposition separately from current session evidence.

    Args:
        app: Exact factory application receiving the current Flask request.
        selector: Route-bound reconnect/remove identity, or None for CONNECT.
        kind: Explicit mutation kind; omission follows the route-bound selector.

    Returns:
        A no-store JSON response. A receipt or session_present is not human read
        permission, onboarding completion, qualification or trading authority.

    Raises:
        BrokerAccountCutoverUnavailable: The app has no owned setup facade.
    """
    from flask import jsonify, request
    from werkzeug.exceptions import Unauthorized

    from .auth_routes import _OperatorSessionVerificationError, verify_operator_session_token
    from .auth_scopes import _session_token

    def response(body, code):
        value = jsonify(body)
        value.status_code = code
        value.headers["Cache-Control"] = "no-store"
        return value

    try:
        token = _session_token() or ""
        verified = verify_operator_session_token(token)
    except (Unauthorized, _OperatorSessionVerificationError):
        return response({"error": "account_setup_session_required"}, 401)
    if "admin.accounts.write" not in verified.scopes:
        return response({"error": "account_setup_scope_required"}, 403)
    service = setup_for(app)
    if service is None:
        raise BrokerAccountCutoverUnavailable
    try:
        service.require_current()
        if not request.is_json or request.content_length is None or request.content_length > ACCOUNT_JSON_MAX_BYTES:
            raise AccountContractError
        body, key = parse_connect(
            request.get_data(cache=False), request.headers.get("Idempotency-Key", ""), selector=selector
        )
        kind = kind or (AccountMutationKind.CONNECT if selector is None else AccountMutationKind.RECONNECT)
        if kind is AccountMutationKind.REMOVE and body.get("credentials") is not None:
            raise AccountContractError
        outcome = service.connect(body, key, token, kind=kind)
    except AccountContractError:
        return response({"error": "account_setup_invalid"}, 400)
    except PermissionError:
        return response({"error": "account_setup_scope_required"}, 403)
    except AccountOperationConflict:
        return response({"error": "account_setup_conflict"}, 409)
    except Exception:
        return response({"error": "broker_account_cutover_unavailable"}, 503)
    receipt = outcome.receipt
    return response(
        {
            "receipt": {
                "operationId": str(receipt.operation_id),
                "kind": receipt.kind.value,
                "state": receipt.state.value,
                "reason": receipt.reason,
                "credentialGeneration": None
                if receipt.credential_version is None
                else receipt.credential_version.generation,
            },
            # Foundation 'ready' means a current session, not an ACL or trading gate.
            "runtimeStatus": "session_present" if outcome.runtime_status == "ready" else outcome.runtime_status,
            **({"recovery": {
                "broker": outcome.recovery.selector.adapter_id, "accountId": outcome.recovery.selector.account_id,
                "readOnly": True, "writeAuthority": "none", "grantAuthority": "none", "reconciliationRequired": True,
                "census": {"complete": True, "revision": outcome.recovery.census_revision,
                           "runIds": list(outcome.recovery.run_ids)},
            }} if outcome.recovery is not None else {}),
        },
        200,
    )
