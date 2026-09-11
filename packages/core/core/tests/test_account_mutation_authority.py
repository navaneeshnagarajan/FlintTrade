"""Offline transaction authority: real owner files, kernel locks and SQLite."""

from __future__ import annotations

import importlib
import json
import shutil
import sqlite3
from dataclasses import replace
from pathlib import PurePosixPath
from uuid import uuid4

import pytest


def test_mutation_contracts_and_eight_method_port_exist():
    contracts = importlib.import_module("flinttrade_core.account_mutation_contracts")
    assert hasattr(contracts, "AccountMutationRequest"), "neutral account admission contract is missing"
    port = importlib.import_module("flinttrade_gateway.account_mutation").AccountMutationProtocol
    assert {name for name in port.__dict__ if not name.startswith("_")} == {
        "connect", "reconnect", "delete", "set_execution_default", "rotate_credentials",
        "begin_auth_flow", "complete_auth_flow", "adopt_legacy",
    }


def test_recovery_authority_is_available_without_gateway():
    import importlib.util

    assert importlib.util.find_spec("flinttrade_core.account_mutation_journal") is not None, (
        "installation-bound transaction journal is missing"
    )


@pytest.mark.parametrize("namespace", [
    "account-coordinator", "account-candidates", "account-transaction-backups",
    "account-receipts", "account-auth-challenges",
])
def test_account_namespaces_are_excluded_recursively_before_enumeration(namespace):
    from flinttrade_core.backup_sensitivity import WorkspaceBackupSensitivity

    policy = WorkspaceBackupSensitivity()
    assert policy.classify(PurePosixPath("data/bhavcopy/equity") / namespace, directory=True) == "excluded"
    assert policy.classify(PurePosixPath(namespace) / "fixture.csv", directory=False) == "excluded"


def test_operation_lock_requires_live_kernel_proof(tmp_path):
    import flinttrade_core.account_mutation_locks as locks
    from flinttrade_core.backend_instance import BackendLeaseUnavailable
    from flinttrade_core.installation_state import InstallationState

    owner = locks.CoordinatorOperationLock(InstallationState(tmp_path / "installation"))
    with pytest.raises(BackendLeaseUnavailable), owner.hold(None):
        pytest.fail("forged proof acquired the coordinator")


def test_order_check_rejects_inverse_before_wait_and_expires_token(tmp_path, backend_lease_proof):
    from flinttrade_core.account_mutation_locks import (
        AccountLockOrderError, CoordinatorOperationLock, LockLevel, authority_fence, require_operation_lock,
    )
    from flinttrade_core.installation_state import InstallationState
    from flinttrade_core.owner_file_lock import OwnerSafeFileLock

    owner = CoordinatorOperationLock(InstallationState(tmp_path / "installation"))
    with owner.hold(backend_lease_proof) as token:
        require_operation_lock(token)
        with authority_fence(LockLevel.SOURCE_WRITER, "ditto", OwnerSafeFileLock(tmp_path / "source.lock")):
            with pytest.raises(AccountLockOrderError), owner.hold(backend_lease_proof):
                pytest.fail("inverse coordinator acquisition admitted")
            with pytest.raises(AccountLockOrderError), authority_fence(
                LockLevel.BACKUP_CONTROL, "backup", OwnerSafeFileLock(tmp_path / "backup.lock"),
            ):
                pytest.fail("inverse backup acquisition admitted")
    with pytest.raises(AccountLockOrderError):
        require_operation_lock(token)


def test_auth_flow_ref_rejects_zero_bool_and_noncanonical_uuid():
    from flinttrade_core.account_mutation_contracts import AuthFlowRef, AccountMutationValidationError

    reference = AuthFlowRef("dhan", uuid4(), uuid4(), "otp", 1, "Synthetic")
    for revision in (0, True, 1 << 63):
        with pytest.raises(AccountMutationValidationError):
            replace(reference, flow_version=revision)
    with pytest.raises(AccountMutationValidationError):
        replace(reference, flow_id=str(reference.flow_id))


@pytest.fixture
def account_owner(tmp_path, backend_lease_proof):
    from flinttrade_core.account_mutation_journal import AccountMutationJournal
    from flinttrade_core.account_mutation_locks import CoordinatorOperationLock
    from flinttrade_core.account_mutation_principals import AccountPrincipalIssuer
    from flinttrade_core.installation_state import InstallationState
    from flinttrade_core.operator_session import VerifiedOperatorSession

    installation = InstallationState(tmp_path / "installation")
    issuer = AccountPrincipalIssuer(lambda: VerifiedOperatorSession("operator:" + "a" * 64, "session:" + "b" * 64, ("admin.accounts.read", "admin.accounts.write")))
    principal = issuer.operator()
    owner = CoordinatorOperationLock(installation)
    with owner.hold(backend_lease_proof) as token:
        with AccountMutationJournal(
            installation, installation.root / "account-coordinator", token=token,
        ) as journal:
            yield journal, principal, token, installation


def request_for(principal, **changes):
    from flinttrade_core.account_mutation_contracts import (
        AccountAuthoritySnapshot, AccountMutationRequest, AccountOperation, RegistrySelectorVersion,
    )
    from flinttrade_core.broker_identity import BrokerSelector, CredentialVersion

    selector = BrokerSelector("dhan", "Synthetic")
    vault, registry = uuid4(), uuid4()
    request = AccountMutationRequest(
        AccountOperation.CONNECT, uuid4(), str(uuid4()),
        AccountAuthoritySnapshot(None, vault, registry,
            (CredentialVersion(selector, vault, 0),), (RegistrySelectorVersion(selector, registry, 0, False),)),
        principal=principal, selector=selector, private_input=b"fixture-secret-not-a-real-credential",
    )
    return replace(request, **changes)


def test_receipt_and_redacted_outbox_commit_before_effect_and_duplicate_is_stable(account_owner):
    from flinttrade_core.account_mutation_contracts import AccountMutationConflict, MutationPhase

    journal, principal, *_ = account_owner
    request = request_for(principal)
    result = journal.admit(request)
    assert result.phase is MutationPhase.PREPARED
    assert journal.anchor_sequence == journal.event_sequence > 0
    assert journal.admit(request) == result
    with pytest.raises(AccountMutationConflict):
        journal.admit(replace(request, private_input=b"different-otp"))
    events = journal.pending_audit()
    assert [event.outcome for event in events] == ["pending", "conflict"]
    assert all(event.actor_ref == "operator:" + "a" * 64 for event in events)
    public = repr(result) + repr(events)
    assert "fixture-secret" not in public
    assert "different-otp" not in public
    assert "candidate" not in public


def test_external_invocation_is_once_and_unknown_never_restores_route(account_owner):
    from flinttrade_core.account_mutation_contracts import MutationPhase

    journal, principal, *_ = account_owner
    result = journal.admit(request_for(principal))
    result = journal.advance(result.reference, MutationPhase.ROUTER_DRAINED)
    calls = []

    def interrupted():
        calls.append(journal.anchor_sequence)
        assert journal.anchor_sequence == journal.event_sequence
        assert journal.get(result.reference.operation_id).phase is MutationPhase.EXTERNAL_INVOKED
        raise TimeoutError("fixture-token-must-not-escape")

    outcome = journal.invoke_external(result.reference, interrupted)
    assert outcome.phase is MutationPhase.EXTERNAL_UNKNOWN
    assert len(calls) == 1
    assert journal.invoke_external(outcome.reference, interrupted) == outcome
    assert len(calls) == 1
    assert "fixture-token" not in repr(journal.pending_audit())


def test_candidate_is_encrypted_and_mac_bound_after_invocation(account_owner):
    from flinttrade_core.account_mutation_contracts import MutationPhase

    journal, principal, *_ = account_owner
    result = journal.admit(request_for(principal))
    result = journal.advance(result.reference, MutationPhase.ROUTER_DRAINED)
    result = journal.invoke_external(result.reference, lambda: b"fixture-returned-token")
    assert result.phase is MutationPhase.CANDIDATE_STAGED
    assert journal.read_candidate(result.reference) == b"fixture-returned-token"
    for path in journal.root.rglob("*"):
        if path.is_file():
            assert b"fixture-returned-token" not in path.read_bytes()
    assert f"candidate-{result.reference.operation_id}.json" not in repr(result)


@pytest.mark.parametrize("replacement", ["delete_db", "replace_db", "replace_namespace", "rollback"])
def test_replaced_or_rolled_back_store_is_never_first_installation(account_owner, replacement, tmp_path):
    from flinttrade_core.account_mutation_contracts import AccountRecoveryUnavailable, MutationPhase
    from flinttrade_core.account_mutation_journal import AccountMutationJournal

    journal, principal, token, installation = account_owner
    result = journal.admit(request_for(principal))
    journal.checkpoint()
    snapshot = tmp_path / "snapshot.sqlite3"
    shutil.copyfile(journal.database_path, snapshot)
    result = journal.advance(result.reference, MutationPhase.ROUTER_DRAINED)
    journal.close()
    if replacement == "delete_db":
        journal.database_path.unlink()
    elif replacement == "replace_db":
        journal.database_path.unlink()
        shutil.copyfile(snapshot, journal.database_path)
    elif replacement == "replace_namespace":
        journal.root.rename(tmp_path / "old-namespace")
        journal.root.mkdir(mode=0o700)
    else:
        # Preserve the inode: anti-rollback cannot rely on pathname pins alone.
        with snapshot.open("rb") as source, journal.database_path.open("wb") as destination:
            shutil.copyfileobj(source, destination)
    with pytest.raises(AccountRecoveryUnavailable):
        with AccountMutationJournal(installation, journal.root, token=token):
            pytest.fail("replaced authority admitted")


def test_unanchored_prepared_commit_recovers_but_effect_phase_does_not(account_owner):
    from flinttrade_core.account_mutation_contracts import AccountRecoveryUnavailable, MutationPhase
    from flinttrade_core.account_mutation_journal import AccountMutationJournal

    journal, principal, token, installation = account_owner
    class PowerLoss(BaseException):
        pass

    def stop_at_commit(point):
        if point == "after_store_commit":
            raise PowerLoss

    journal.kill_point = stop_at_commit
    request = request_for(principal)
    with pytest.raises(PowerLoss):
        journal.admit(request)
    journal.close()
    with AccountMutationJournal(installation, journal.root, token=token) as reopened:
        result = reopened.admit(request)
        assert result.phase is MutationPhase.PREPARED
        assert reopened.event_sequence == reopened.anchor_sequence
        result = reopened.advance(result.reference, MutationPhase.ROUTER_DRAINED)
        result = reopened.advance(result.reference, MutationPhase.EXTERNAL_INVOCATION_PREPARED)
        reopened.kill_point = stop_at_commit
        with pytest.raises(PowerLoss):
            reopened.advance(result.reference, MutationPhase.EXTERNAL_INVOKED)
    with pytest.raises(AccountRecoveryUnavailable):
        with AccountMutationJournal(installation, journal.root, token=token):
            pytest.fail("unanchored invocation accepted")


def test_tampered_projection_or_zero_revision_fails_closed(account_owner):
    from flinttrade_core.account_mutation_contracts import AccountRecoveryUnavailable

    journal, principal, *_ = account_owner
    result = journal.admit(request_for(principal))
    with sqlite3.connect(journal.database_path) as connection:
        row = connection.execute("SELECT body FROM operations WHERE entity_id=?", (str(result.reference.operation_id),)).fetchone()
        value = json.loads(row[0])
        value["phase"] = "committed"
        connection.execute("UPDATE operations SET body=?", (json.dumps(value),))
    with pytest.raises(AccountRecoveryUnavailable):
        journal.get(result.reference.operation_id)


def test_idempotency_keys_and_sealed_principals_reject_forgery(account_owner):
    from flinttrade_core.account_mutation_contracts import (
        AccountMutationValidationError, AccountPrincipalDenied, OperatorSessionPrincipal,
    )

    journal, principal, *_ = account_owner
    request = request_for(principal)
    for invalid in ("", request.idempotency_key.upper(), request.idempotency_key.replace("-", "")):
        with pytest.raises(AccountMutationValidationError):
            replace(request, idempotency_key=invalid)
    with pytest.raises(AccountPrincipalDenied):
        journal.admit(replace(request, principal=object.__new__(OperatorSessionPrincipal)))
    with pytest.raises(AccountPrincipalDenied):
        principal.scopes = ("invented",)


def test_provider_refusal_is_durable_and_audit_sink_outage_preserves_receipt(account_owner):
    from flinttrade_core.account_mutation_contracts import MutationPhase
    from flinttrade_core.account_mutation_journal import ProviderRejected

    journal, principal, *_ = account_owner
    request = request_for(principal)
    result = journal.advance(journal.admit(request).reference, MutationPhase.ROUTER_DRAINED)

    def reject():
        raise ProviderRejected

    result = journal.invoke_external(result.reference, reject)
    assert result.phase is MutationPhase.PROVIDER_REJECTED
    assert journal.admit(request) == result
    events = journal.pending_audit()

    def outage(_event):
        raise RuntimeError("fixture-audit-token")

    assert journal.replay_audit(outage) == 0
    assert journal.pending_audit() == events
    delivered = []
    assert journal.replay_audit(delivered.append) == len(events)
    assert journal.pending_audit() == ()


@pytest.mark.parametrize("point, expected", [
    ("before_external_invocation", "external_unknown"),
    ("after_candidate_fsync", "candidate_staged"),
])
def test_restart_never_repeats_exchange_at_candidate_kill_boundaries(account_owner, point, expected):
    from flinttrade_core.account_mutation_contracts import MutationPhase
    from flinttrade_core.account_mutation_journal import AccountMutationJournal

    journal, principal, token, installation = account_owner
    result = journal.advance(journal.admit(request_for(principal)).reference, MutationPhase.ROUTER_DRAINED)
    class PowerLoss(BaseException):
        pass

    def kill(observed):
        if observed == point:
            raise PowerLoss

    journal.kill_point = kill
    invocations = []
    with pytest.raises(PowerLoss):
        journal.invoke_external(result.reference, lambda: invocations.append(1) or b"fixture-secret")
    journal.close()
    with AccountMutationJournal(installation, journal.root, token=token) as reopened:
        current = reopened.get(result.reference.operation_id)
        outcome = reopened.invoke_external(current.reference, lambda: pytest.fail("provider repeated"))
        assert outcome.phase.value == expected
    assert len(invocations) == (point == "after_candidate_fsync")


def test_manifest_requires_frozen_versions_and_rolls_forward_after_source_retirement(account_owner):
    from flinttrade_core.account_mutation_contracts import AccountMutationConflict, MutationPhase

    journal, principal, *_ = account_owner
    request = request_for(principal)
    result = journal.admit(request)
    manifest = {
        "operation_id": str(request.operation_id),
        "steps": ["workspace_committed", "vault_committed"],
        "expected_authorities": journal.authority_snapshot(result.reference),
        "intended_workspace": {"instance_id": str(uuid4()), "generation": 1},
        "intended_credentials": [{"selector": {"adapter_id": "dhan", "account_id": "Synthetic"},
                                  "vault_incarnation": str(request.authorities.vault_incarnation), "generation": 1}],
        "touched_selectors": [{"adapter_id": "dhan", "account_id": "Synthetic"}],
        "prior_snapshot": None,
        "source_retirement": {"operation_id": str(request.operation_id), "source_incarnation": str(uuid4()), "generation": 1},
    }
    result = journal.prepare_commit(result.reference, manifest)
    effects = []
    for phase in (MutationPhase.WORKSPACE_COMMITTED, MutationPhase.VAULT_COMMITTED):
        result = journal.commit_step(result.reference, phase,
            observe=lambda: "expected", apply=lambda: effects.append(journal.anchor_sequence))
    result = journal.advance(result.reference, MutationPhase.DURABLE_COMMITTED)
    source = {"retired": None}

    def retire():
        assert journal.get(request.operation_id).phase is MutationPhase.DURABLE_COMMITTED
        source["retired"] = manifest["source_retirement"]

    result = journal.retire_source(result.reference, observe=lambda: source["retired"], retire=retire)
    assert result.phase is MutationPhase.SOURCE_RETIRED
    with pytest.raises(AccountMutationConflict):
        journal.prepare_commit(result.reference, manifest)
    with pytest.raises(AccountMutationConflict):
        journal.advance(result.reference, MutationPhase.WORKSPACE_COMMITTED)
    for phase in (MutationPhase.REGISTRY_PUBLISHED, MutationPhase.FACADE_PUBLISHED, MutationPhase.ROUTER_REBUILT):
        result = journal.publish(result.reference, phase, lambda: effects.append(journal.anchor_sequence))
    result = journal.advance(result.reference, MutationPhase.COMMITTED_DISCONNECTED)
    assert result.outcome == "success"
    assert len(effects) == 5


def begin_flow(account_owner, *, kind="otp_multistep"):
    import time
    from flinttrade_core.account_mutation_contracts import AccountOperation
    from flinttrade_core.account_mutation_flows import AccountAuthFlows

    journal, principal, *_ = account_owner
    request = request_for(principal, operation=AccountOperation.BEGIN_AUTH_FLOW, selector=None, adapter_id="dhan")
    result = journal.admit(request)
    flows = AccountAuthFlows(journal)
    flow = flows.begin(result.reference, kind=kind, expected_account_id="Synthetic",
        expires_at=int(time.time()) + 600, redirect="http://127.0.0.1/callback",
        retired_selectors=tuple(v.selector for v in request.authorities.registry_versions), adapter_wide=True)
    return flows, flow, request


def completion_request(flows, flow, begin_request, *, secret=b"fixture-otp"):
    from flinttrade_core.account_mutation_contracts import AccountOperation

    return replace(begin_request, operation=AccountOperation.COMPLETE_AUTH_FLOW,
        operation_id=flows.current_child(flow), idempotency_key=str(uuid4()),
        flow_ref=flow, private_input=secret)


def test_auth_parent_allocates_one_child_and_same_otp_resumes_it(account_owner):
    from flinttrade_core.account_mutation_contracts import AccountMutationConflict

    flows, flow, begun = begin_flow(account_owner)
    request = completion_request(flows, flow, begun)
    result = flows.claim(request)
    assert flows.claim(request) == result
    with pytest.raises(AccountMutationConflict):
        flows.claim(replace(request, private_input=b"different-otp"))
    with pytest.raises(AccountMutationConflict):
        flows.claim(replace(request, operation_id=uuid4()))
    status = flows.status(flow, begun.principal)
    assert status.state.value == "completing"
    assert status.retired_selectors == tuple(v.selector for v in begun.authorities.registry_versions)
    assert "fixture-otp" not in repr(status)


def test_multistep_next_child_is_allocated_before_challenge_response(account_owner):
    from flinttrade_core.account_mutation_contracts import MutationPhase

    journal, *_ = account_owner
    flows, flow, begun = begin_flow(account_owner)
    request = completion_request(flows, flow, begun)
    child = flows.claim(request)
    child = journal.advance(child.reference, MutationPhase.ROUTER_DRAINED)
    child = journal.invoke_external(child.reference, lambda: b"fixture-provider-challenge")
    next_flow = flows.finish_step(flow, child.reference, final=False)
    assert next_flow.flow_version > flow.flow_version
    assert flows.current_child(next_flow) != request.operation_id
    status = flows.status(next_flow, begun.principal)
    assert status.state.value == "challenge_staged"
    assert status.lease_released is False
    released = flows.release_for_input(next_flow)
    assert flows.status(released, begun.principal).lease_released is True


def test_unknown_auth_child_keeps_adapter_retired_and_blocks_overlapping_mutation(account_owner):
    from flinttrade_core.account_mutation_contracts import AccountMutationConflict, MutationPhase

    journal, principal, *_ = account_owner
    flows, flow, begun = begin_flow(account_owner)
    child = flows.claim(completion_request(flows, flow, begun))
    child = journal.advance(child.reference, MutationPhase.ROUTER_DRAINED)

    def unknown():
        raise TimeoutError("fixture-provider-token")

    child = journal.invoke_external(child.reference, unknown)
    updated = flows.finish_step(flow, child.reference, final=False)
    assert flows.status(updated, principal).state.value == "external_unknown"
    with pytest.raises(AccountMutationConflict):
        journal.admit(request_for(principal))
    with pytest.raises(AccountMutationConflict):
        flows.claim(completion_request(flows, updated, begun))
    cancelled = flows.cancel(updated, principal)
    assert flows.status(cancelled, principal).retirement_retained is True


def test_auth_cancel_without_invocation_tombstones_child_and_releases_ownership(account_owner):
    journal, principal, *_ = account_owner
    flows, flow, _ = begin_flow(account_owner)
    cancelled = flows.cancel(flow, principal)
    status = flows.status(cancelled, principal)
    assert status.state.value == "cancelled"
    assert status.retirement_retained is False
    assert journal.admit(request_for(principal)).outcome == "pending"


def test_auth_status_new_same_operator_session_cannot_exchange_old_child(account_owner):
    from flinttrade_core.account_mutation_contracts import AccountPrincipalDenied
    from flinttrade_core.account_mutation_principals import AccountPrincipalIssuer
    from flinttrade_core.operator_session import VerifiedOperatorSession

    flows, flow, begun = begin_flow(account_owner)
    new_principal = AccountPrincipalIssuer(lambda: VerifiedOperatorSession(
        "operator:" + "a" * 64, "session:" + "c" * 64, ("admin.accounts.read", "admin.accounts.write"),
    )).operator()
    assert flows.status(flow, new_principal).state.value == "pending"
    request = completion_request(flows, flow, begun)
    with pytest.raises(AccountPrincipalDenied):
        flows.claim(replace(request, principal=new_principal))


def test_cancelled_claim_cannot_invoke_provider_from_an_old_child_handle(account_owner):
    from flinttrade_core.account_mutation_contracts import AccountMutationConflict, MutationPhase

    journal, principal, *_ = account_owner
    flows, flow, begun = begin_flow(account_owner)
    child = flows.claim(completion_request(flows, flow, begun))
    child = journal.advance(child.reference, MutationPhase.ROUTER_DRAINED)
    flows.cancel(flows.status(flow, principal).reference, principal)
    with pytest.raises(AccountMutationConflict):
        journal.invoke_external(child.reference, lambda: pytest.fail("cancelled child invoked"))


def test_internal_openalgo_manifest_commits_vault_before_workspace(account_owner):
    from flinttrade_core.account_mutation_contracts import (
        AccountMutationConflict, AccountOperation, MutationPhase, OpenAlgoMigrationPrincipal,
    )
    from flinttrade_core.account_mutation_principals import AccountPrincipalIssuer, BoundedAccountClaim
    from flinttrade_core.broker_identity import BrokerSelector

    journal, _principal, token, installation = account_owner
    selector = BrokerSelector("openalgo", "default")
    operation_id = uuid4()
    principal = AccountPrincipalIssuer.bounded(token, lambda: BoundedAccountClaim(
        installation.installation_id, operation_id, selector, uuid4(), OpenAlgoMigrationPrincipal))
    base = request_for(principal)
    authorities = replace(base.authorities,
        credential_versions=(replace(base.authorities.credential_versions[0], selector=selector),),
        registry_versions=(replace(base.authorities.registry_versions[0], selector=selector),))
    request = replace(base, selector=selector, authorities=authorities, operation_id=operation_id,
                      operation=AccountOperation.CONNECT)
    result = journal.admit(request)
    manifest = {
        "operation_id": str(operation_id), "steps": ["vault_committed", "workspace_committed", "projection_committed"],
        "expected_authorities": journal.authority_snapshot(result.reference),
        "intended_workspace": {"instance_id": str(uuid4()), "generation": 1},
        "intended_credentials": [{"selector": {"adapter_id": "openalgo", "account_id": "default"},
                                  "vault_incarnation": str(authorities.vault_incarnation), "generation": 1}],
        "touched_selectors": [{"adapter_id": "openalgo", "account_id": "default"}],
        "prior_snapshot": None, "source_retirement": None,
    }
    result = journal.prepare_commit(result.reference, manifest)
    effects = []
    with pytest.raises(AccountMutationConflict):
        journal.commit_step(result.reference, MutationPhase.WORKSPACE_COMMITTED,
                            observe=lambda: "expected", apply=lambda: pytest.fail("skipped vault"))
    for phase in (MutationPhase.VAULT_COMMITTED, MutationPhase.WORKSPACE_COMMITTED, MutationPhase.PROJECTION_COMMITTED):
        result = journal.commit_step(result.reference, phase, observe=lambda: "expected", apply=lambda phase=phase: effects.append(phase))
        assert journal.commit_step(result.reference, phase, observe=lambda: pytest.fail("reobserved"),
                                   apply=lambda: pytest.fail("reapplied")) == result
    assert journal.advance(result.reference, MutationPhase.DURABLE_COMMITTED).phase is MutationPhase.DURABLE_COMMITTED
    assert effects == [MutationPhase.VAULT_COMMITTED, MutationPhase.WORKSPACE_COMMITTED, MutationPhase.PROJECTION_COMMITTED]


def test_complete_flow_cannot_bypass_allocated_child_admission(account_owner):
    from flinttrade_core.account_mutation_contracts import AccountMutationConflict, AccountOperation, AuthFlowRef

    journal, principal, *_ = account_owner
    reference = AuthFlowRef("dhan", uuid4(), journal.store_incarnation, "otp", 1, "Synthetic")
    with pytest.raises(AccountMutationConflict):
        journal.admit(request_for(principal, operation=AccountOperation.COMPLETE_AUTH_FLOW, flow_ref=reference))


@pytest.mark.parametrize("phase", ["pending", "completing", "external_invoked", "candidate_staged", "challenge_staged", "cancelled"])
@pytest.mark.parametrize("replacement", ["delete_db", "replace_db", "replace_namespace", "rollback"])
def test_auth_lineage_replacement_cannot_repeat_a_child(account_owner, tmp_path, phase, replacement):
    from flinttrade_core.account_mutation_contracts import AccountRecoveryUnavailable, MutationPhase
    from flinttrade_core.account_mutation_journal import AccountMutationJournal

    journal, principal, token, installation = account_owner
    flows, flow, begun = begin_flow(account_owner)
    if phase != "pending":
        child = flows.claim(completion_request(flows, flow, begun))
        if phase in {"external_invoked", "candidate_staged", "challenge_staged"}:
            child = journal.advance(child.reference, MutationPhase.ROUTER_DRAINED)
            if phase == "external_invoked":
                child = journal.advance(child.reference, MutationPhase.EXTERNAL_INVOCATION_PREPARED)
                journal.advance(child.reference, MutationPhase.EXTERNAL_INVOKED)
            else:
                child = journal.invoke_external(child.reference, lambda: b"fixture-auth-challenge")
                if phase == "challenge_staged":
                    flows.finish_step(flow, child.reference, final=False)
        elif phase == "cancelled":
            flows.cancel(flows.status(flow, principal).reference, principal)
    journal.checkpoint()
    snapshot = tmp_path / "auth-snapshot.sqlite3"
    shutil.copyfile(journal.database_path, snapshot)
    # Advance independent durable audit authority, leaving workspace/vault fixed.
    journal.replay_audit(lambda event: None)
    journal.checkpoint()
    journal.close()
    if replacement == "delete_db":
        journal.database_path.unlink()
    elif replacement == "replace_namespace":
        journal.root.rename(tmp_path / "old-auth-namespace")
        journal.root.mkdir(mode=0o700)
    elif replacement == "replace_db":
        journal.database_path.unlink()
        shutil.copyfile(snapshot, journal.database_path)
    else:
        with snapshot.open("rb") as source, journal.database_path.open("wb") as destination:
            shutil.copyfileobj(source, destination)
    with pytest.raises(AccountRecoveryUnavailable):
        with AccountMutationJournal(installation, journal.root, token=token):
            pytest.fail("replaced auth authority admitted")


@pytest.mark.parametrize("point", ["before_source_commit", "after_source_commit", "after_source_retired_fsync",
                                   "after_registry_published", "after_facade_published", "after_router_rebuilt"])
def test_source_retirement_crash_recovers_exact_tombstone(account_owner, tmp_path, point):
    from flinttrade_core.account_mutation_contracts import MutationPhase
    from flinttrade_core.account_mutation_journal import AccountMutationJournal

    journal, principal, token, installation = account_owner
    request = request_for(principal)
    result = journal.admit(request)
    marker = {"operation_id": str(request.operation_id), "source_incarnation": str(uuid4()), "generation": 1}
    manifest = {"operation_id": str(request.operation_id), "steps": [],
                "expected_authorities": journal.authority_snapshot(result.reference), "intended_workspace": None,
                "intended_credentials": journal.authority_snapshot(result.reference)["credential_versions"],
                "touched_selectors": [{"adapter_id": "dhan", "account_id": "Synthetic"}],
                "prior_snapshot": None, "source_retirement": marker}
    result = journal.prepare_commit(result.reference, manifest)
    result = journal.advance(result.reference, MutationPhase.DURABLE_COMMITTED)
    source = sqlite3.connect(tmp_path / "synthetic-source.sqlite3")
    source.execute("PRAGMA synchronous=FULL")
    source.execute("CREATE TABLE retirement (marker TEXT)")
    source.commit()
    commits = []
    def observe():
        value = source.execute("SELECT marker FROM retirement").fetchone()
        return json.loads(value[0]) if value else None
    def retire():
        source.execute("INSERT INTO retirement VALUES (?)", (json.dumps(marker),))
        source.commit()
        commits.append(1)
    class PowerLoss(BaseException):
        pass
    def kill(observed):
        if observed == point:
            raise PowerLoss
    journal.kill_point = kill
    with pytest.raises(PowerLoss):
        result = journal.retire_source(result.reference, observe=observe, retire=retire)
        for phase in (MutationPhase.REGISTRY_PUBLISHED, MutationPhase.FACADE_PUBLISHED, MutationPhase.ROUTER_REBUILT):
            result = journal.publish(result.reference, phase, lambda: None)
    journal.close()
    with AccountMutationJournal(installation, journal.root, token=token) as reopened:
        result = reopened.get(request.operation_id)
        if result.phase is MutationPhase.DURABLE_COMMITTED:
            result = reopened.retire_source(result.reference, observe=observe, retire=retire)
        phases = [MutationPhase.SOURCE_RETIRED, MutationPhase.REGISTRY_PUBLISHED,
                  MutationPhase.FACADE_PUBLISHED, MutationPhase.ROUTER_REBUILT]
        for phase in phases[phases.index(result.phase) + 1:]:
            result = reopened.publish(result.reference, phase, lambda: None)
        assert reopened.advance(result.reference, MutationPhase.COMMITTED).outcome == "success"
    assert observe() == marker
    assert commits == [1]
    source.close()


def test_core_account_authority_has_no_gateway_imports():
    import ast
    import flinttrade_core.account_mutation_journal as module
    from pathlib import Path

    for path in Path(module.__file__).parent.glob("account_mutation*.py"):
        tree = ast.parse(path.read_text())
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                assert all(not alias.name.startswith("flinttrade_gateway") for alias in node.names)
            elif isinstance(node, ast.ImportFrom):
                assert not (node.module or "").startswith("flinttrade_gateway")


def _account_lock_process(tmp_path, outer, inner, outer_held, inner_held, inverse):
    """Spawnable worker uses real file locks without inheriting pytest threads."""
    import os
    from flinttrade_core.account_mutation_locks import AccountLockOrderError, LockLevel, authority_fence
    from flinttrade_core.owner_file_lock import OwnerSafeFileLock
    try:
        if not inverse:
            with authority_fence(LockLevel(outer), "outer", OwnerSafeFileLock(tmp_path / "outer.lock", timeout=2)):
                outer_held.set()
                assert inner_held.wait(3)
                with authority_fence(LockLevel(inner), "inner", OwnerSafeFileLock(tmp_path / "inner.lock", timeout=2)):
                    pass
        else:
            with authority_fence(LockLevel(inner), "inner", OwnerSafeFileLock(tmp_path / "inner.lock", timeout=2)):
                inner_held.set()
                assert outer_held.wait(3)
                try:
                    with authority_fence(LockLevel(outer), "outer", OwnerSafeFileLock(tmp_path / "outer.lock", timeout=2)):
                        os._exit(2)
                except AccountLockOrderError:
                    pass
    except BaseException:
        os._exit(3)


@pytest.mark.parametrize("outer,inner", [(10, 20), (20, 30), (30, 40), (40, 80), (80, 90), (90, 100), (100, 110)])
def test_concurrent_process_inverse_attempt_rejects_before_wait(tmp_path, monkeypatch, outer, inner):
    import multiprocessing
    from pathlib import Path

    # importlib-mode pytest gives this file a synthetic ``tests`` namespace;
    # expose its real directory for a fresh interpreter's worker import.
    monkeypatch.syspath_prepend(str(Path(__file__).parent))
    worker = importlib.import_module("test_account_mutation_authority")._account_lock_process
    context = multiprocessing.get_context("spawn")
    outer_held, inner_held = context.Event(), context.Event()
    processes = [context.Process(target=worker,
                                 args=(tmp_path, outer, inner, outer_held, inner_held, inverse))
                 for inverse in (False, True)]
    try:
        for process in processes:
            process.start()
        for process in processes:
            process.join(timeout=6)
        assert [process.exitcode for process in processes] == [0, 0]
    finally:
        for process in processes:
            if process.is_alive():
                process.terminate()
                process.join(timeout=3)


def test_route_attempts_never_fabricate_operation_or_selector(account_owner):
    from flinttrade_core.account_mutation_contracts import RouteMutationAttempt

    journal, *_ = account_owner
    attempt = RouteMutationAttempt(uuid4(), "unknown_selector")
    journal.record_route_attempt(attempt)
    assert journal._row("route_attempts", str(attempt.attempt_id))[1] == {"reason": "unknown_selector"}
    assert journal.pending_audit() == ()
    assert journal._connection.execute("SELECT COUNT(*) FROM operations").fetchone()[0] == 0


@pytest.mark.parametrize("namespace", [".account-coordinator-binding.json", ".account-coordinator-anchor.json",
                                      ".account-coordinator-keys.json", ".account-coordinator.lock"])
def test_recovery_bootstrap_members_are_recursively_sensitive(namespace):
    from flinttrade_core.backup_sensitivity import WorkspaceBackupSensitivity

    assert WorkspaceBackupSensitivity().classify(PurePosixPath("data/bhavcopy/equity") / namespace,
                                                 directory=False) == "excluded"


def test_finished_auth_step_returns_same_receipt_on_lost_response(account_owner):
    from flinttrade_core.account_mutation_contracts import MutationPhase

    journal, *_ = account_owner
    flows, flow, begun = begin_flow(account_owner)
    request = completion_request(flows, flow, begun)
    child = flows.claim(request)
    child = journal.advance(child.reference, MutationPhase.ROUTER_DRAINED)
    child = journal.invoke_external(child.reference, lambda: b"fixture-challenge")
    flows.finish_step(flow, child.reference, final=False)
    assert flows.claim(request) == child


def test_retired_selector_conflict_has_durable_actor_receipt(account_owner):
    from flinttrade_core.account_mutation_contracts import AccountMutationConflict

    journal, principal, *_ = account_owner
    begin_flow(account_owner)
    request = request_for(principal)
    with pytest.raises(AccountMutationConflict):
        journal.admit(request)
    assert journal.get(request.operation_id).outcome == "conflict"
    assert journal.pending_audit()[-1].operation_id == request.operation_id
    assert journal.pending_audit()[-1].outcome == "conflict"


def test_read_only_operator_can_observe_flow_but_cannot_cancel(account_owner):
    from flinttrade_core.account_mutation_contracts import AccountPrincipalDenied
    from flinttrade_core.account_mutation_principals import AccountPrincipalIssuer
    from flinttrade_core.operator_session import VerifiedOperatorSession

    flows, flow, _ = begin_flow(account_owner)
    issuer = AccountPrincipalIssuer(lambda: VerifiedOperatorSession(
        "operator:" + "a" * 64, "session:" + "c" * 64, ("admin.accounts.read",)))
    principal = issuer.operator(required_scope="admin.accounts.read")
    assert flows.status(flow, principal).state.value == "pending"
    with pytest.raises(AccountPrincipalDenied):
        flows.cancel(flow, principal)


def test_cancelled_multistep_flow_destroys_prior_challenge_after_tombstone(account_owner):
    from flinttrade_core.account_mutation_contracts import MutationPhase

    journal, principal, *_ = account_owner
    flows, flow, begun = begin_flow(account_owner)
    child = flows.claim(completion_request(flows, flow, begun))
    child = journal.advance(child.reference, MutationPhase.ROUTER_DRAINED)
    child = journal.invoke_external(child.reference, lambda: b"fixture-discarded-challenge")
    current = flows.finish_step(flow, child.reference, final=False)
    candidate = journal.root / journal._candidate_name(child.reference.operation_id)
    assert candidate.exists()
    flows.cancel(current, principal)
    assert not candidate.exists()
