"""Provider-free recovery through real vault/workspace durability boundaries."""

import json
import os
import subprocess
import sys
from dataclasses import replace
from uuid import uuid4

import pytest

from flinttrade_core.account_lifecycle_contracts import AccountMutationKind, AccountOperationStage
from flinttrade_core.workspace_migrations import read_workspace_snapshot, update_workspace_config

from .test_broker_account_workspace import finish, owned as _owned_fixture, planned

owned = _owned_fixture


class Crash(BaseException):
    """Injected process interruption; never interpreted as a provider outcome."""


@pytest.mark.parametrize("boundary", ["prepare", "replace", "complete"])
def test_genesis_recovers_exact_own_witness_after_each_durable_boundary(owned, monkeypatch, boundary):
    path, _, _, store, participant, _ = owned
    from flinttrade_core import workspace_migrations

    target, name = (workspace_migrations, "_atomic_write") if boundary == "replace" else (
        store, "prepare_enrolment" if boundary == "prepare" else "complete_enrolment"
    )
    original = getattr(target, name)

    def crash_after(*args, **kwargs):
        result = original(*args, **kwargs)
        raise Crash(result)

    monkeypatch.setattr(target, name, crash_after)
    with pytest.raises(Crash):
        participant.enrol()
    monkeypatch.setattr(target, name, original)
    before = read_workspace_snapshot(path)
    update_workspace_config(path, lambda config: config["ui"].update(theme="light"))
    assert participant.recover() == ()
    witness = participant.enrol()
    after = participant.assert_coherent()
    assert witness == store.head()
    assert witness.epoch == 0
    assert after.config["ui"]["theme"] == "light"
    assert after.version.generation == before.version.generation + 1 + int(boundary == "prepare")
    assert participant.recover() == ()
    assert read_workspace_snapshot(path).version == after.version


@pytest.mark.parametrize("boundary", ["plan", "replace", "apply"])
def test_prepared_or_witnessed_candidate_rolls_forward_once_without_authentication(owned, monkeypatch, boundary):
    request, patch, _ = planned(owned)
    path, _, credentials, store, participant, _ = owned
    from flinttrade_core import workspace_migrations

    if boundary != "plan":
        target, name = (workspace_migrations, "_atomic_write") if boundary == "replace" else (store, "apply")
        original = getattr(target, name)

        def crash_after(*args, **kwargs):
            result = original(*args, **kwargs)
            raise Crash(result)

        monkeypatch.setattr(target, name, crash_after)
        with pytest.raises(Crash):
            witness = participant.commit(request.operation_id, patch)
            store.apply(request.operation_id, witness)
        monkeypatch.setattr(target, name, original)

    def forbidden_auth(*args, **kwargs):
        pytest.fail("provider-free recovery attempted authentication")

    monkeypatch.setattr(store, "mark_authentication_started", forbidden_auth)
    update_workspace_config(path, lambda config: config["ui"].update(theme="light"))
    receipts = participant.recover()
    assert len(receipts) == 1
    receipt = receipts[0]
    assert receipt.state is AccountOperationStage.COMMITTED
    assert credentials.selector_state(request.selector).version == receipt.credential_version
    assert receipt.credential_version.generation == 1
    assert participant.assert_coherent().config["ui"]["theme"] == "light"
    version = read_workspace_snapshot(path).version
    assert participant.recover() == receipts
    assert read_workspace_snapshot(path).version == version


def test_second_crash_during_recovery_preserves_original_receipt_versions(owned, monkeypatch):
    request, _, _ = planned(owned)
    original = owned[3].apply

    def applied_then_crash(*args, **kwargs):
        original(*args, **kwargs)
        raise Crash()

    monkeypatch.setattr(owned[3], "apply", applied_then_crash)
    with pytest.raises(Crash):
        owned[4].recover()
    receipt = owned[3].operation(request.operation_id).receipt
    monkeypatch.setattr(owned[3], "apply", original)
    update_workspace_config(owned[0], lambda config: config["ui"].update(theme="light"))
    assert owned[4].recover() == (receipt,)
    assert receipt.commit_workspace.generation < read_workspace_snapshot(owned[0]).version.generation
    assert owned[2].selector_state(request.selector).version.generation == 1


@pytest.mark.parametrize("stage", ["admitted", "authentication_started"])
def test_admission_is_resumable_but_incomplete_authentication_is_unknown(owned, stage):
    from flinttrade_core.account_lifecycle_contracts import AccountActorContext, AccountMutationRequest
    from flinttrade_core.broker_identity import BrokerSelector
    from flinttrade_core.workspace_migrations import broker_workspace_version

    owned[4].enrol()
    snapshot = owned[4].assert_coherent()
    selector = BrokerSelector("dhan", "Synthetic")
    request = AccountMutationRequest(
        uuid4(), AccountMutationKind.CONNECT, selector, AccountActorContext("operator", "session:" + "a" * 64),
        snapshot.version, broker_workspace_version(snapshot), owned[2].selector_state(selector).version,
        "dhan", "Synthetic", {"token": "input"},
    )
    owned[3].admit(request)
    if stage == "authentication_started":
        owned[3].mark_authentication_started(request.operation_id)
    before = (owned[0] / "workspace.json").read_bytes()
    receipts = owned[4].recover()
    assert (owned[0] / "workspace.json").read_bytes() == before
    assert owned[2].selector_state(selector).version.generation == 0
    if stage == "admitted":
        assert receipts == ()
        assert owned[3].operation(request.operation_id).state is AccountOperationStage.ADMITTED
    else:
        assert receipts[0].state is AccountOperationStage.AUTHENTICATION_UNKNOWN
        assert owned[4].recover() == receipts
    assert owned[3].active_operation(owned[3].owner_capability(owned[1].proof)) is not None


@pytest.mark.parametrize("after_witness", [False, True])
def test_abandonment_before_witness_rejects_and_after_witness_rolls_forward(owned, after_witness):
    request, patch, _ = planned(owned)
    if after_witness:
        witness = owned[4].commit(request.operation_id, patch)
    owned[3].abandon(request.operation_id, committed=after_witness, reason="caller_cancelled")
    receipt, = owned[4].recover()
    assert receipt.state is (AccountOperationStage.COMMITTED if after_witness else AccountOperationStage.REJECTED)
    assert owned[2].selector_state(request.selector).version.generation == int(after_witness)
    if after_witness:
        assert receipt.commit_workspace == witness.commit_workspace
    assert owned[4].recover() == (receipt,)


@pytest.mark.parametrize("foreign", ["digest", "instance", "marker"])
def test_foreign_state_blocks_without_overwrite_or_compensation(owned, foreign):
    request, _, _ = planned(owned)
    config = read_workspace_snapshot(owned[0]).as_dict()
    if foreign == "digest":
        config["brokers"]["execution"]["default"] = "dhan:Newer"
    elif foreign == "instance":
        config["workspace_instance_id"] = str(uuid4())
    else:
        witness = owned[3].head()
        config["_broker_account_store"] = replace(witness, operation_id=uuid4()).to_dict()
    (owned[0] / "workspace.json").write_text(json.dumps(config))
    before = (owned[0] / "workspace.json").read_bytes()
    with pytest.raises(owned[5].BrokerAccountWorkspaceUnavailable):
        owned[4].recover()
    assert (owned[0] / "workspace.json").read_bytes() == before
    assert owned[2].selector_state(request.selector).version.generation == 0


def test_remove_recovery_has_no_auth_candidate_or_setup_invention(owned):
    request, patch, _ = planned(owned)
    finish(owned, request, patch)
    request, _, _ = planned(owned, kind=AccountMutationKind.REMOVE)
    receipt, = owned[4].recover()
    assert receipt.kind is AccountMutationKind.REMOVE
    state = owned[2].selector_state(request.selector)
    assert not state.credential_present and not state.setup_present
    assert state.version.generation == 2


@pytest.mark.parametrize("boundary", ["genesis_prepare", "genesis_replace", "workspace_replace", "vault_apply", "hidden_witness"])
def test_process_death_reopens_real_ledger_and_recovers_once(tmp_path, monkeypatch, boundary):
    from flinttrade_core.backend_instance import acquire_backend_instance_lease
    from flinttrade_core.secure_file import harden_directory
    from flinttrade_core.workspace_migrations import default_workspace_config, write_workspace_config
    from flinttrade_gateway.account_transaction_store import AccountTransactionStore
    from flinttrade_gateway.credentials import CredentialStore

    from .test_broker_account_workspace import workspace_module

    workspace_module()
    harden_directory(tmp_path)
    monkeypatch.setenv("FLINTTRADE_WORKSPACE_DIR", str(tmp_path))
    write_workspace_config(tmp_path, default_workspace_config(), expected_version=None)
    script = r"""
import json
import os
from pathlib import Path
from uuid import uuid4
from flinttrade_core.backend_instance import acquire_backend_instance_lease
from flinttrade_core.account_lifecycle_contracts import *
from flinttrade_core.broker_identity import BrokerSelector
from flinttrade_core.broker_account_workspace import BrokerAccountWorkspace, BrokerAccountPatch, BrokerAccountWorkspaceUnavailable
from flinttrade_core import workspace_migrations as wm
from flinttrade_gateway.credentials import CredentialStore
from flinttrade_gateway.account_transaction_store import AccountTransactionStore
path = Path(os.environ["FLINTTRADE_WORKSPACE_DIR"])
lease = acquire_backend_instance_lease()
credentials = CredentialStore(path / "vault.db", "synthetic-password")
store = AccountTransactionStore(credentials, workspace_path=path, backend_proof=lease.proof)
participant = BrokerAccountWorkspace(path, store, lease.proof)
boundary = os.environ["CRASH_BOUNDARY"]
def die_after(target, name):
    original = getattr(target, name)
    def die(*args, **kwargs):
        original(*args, **kwargs)
        os._exit(23)
    setattr(target, name, die)
if boundary == "genesis_prepare":
    die_after(store, "prepare_enrolment")
if boundary == "genesis_replace":
    die_after(wm, "_atomic_write")
participant.enrol()
snapshot = participant.assert_coherent()
selector = BrokerSelector("dhan", "Synthetic")
request = AccountMutationRequest(uuid4(), AccountMutationKind.CONNECT, selector,
    AccountActorContext("operator", "session:" + "a" * 64), snapshot.version,
    wm.broker_workspace_version(snapshot), credentials.selector_state(selector).version,
    "dhan", "Synthetic", {"token": "input"})
patch = BrokerAccountPatch(request.kind, selector, (), False)
store.admit(request)
store.mark_authentication_started(request.operation_id)
store.stage_plan(request.operation_id, replay_credentials={"token": "replay"}, read_only=False,
    before_digest=broker_account_digest(snapshot), after_digest=broker_account_digest(patch.apply(snapshot.config)))
if boundary == "workspace_replace":
    die_after(wm, "_atomic_write")
if boundary == "vault_apply":
    die_after(store, "apply")
witness = participant.commit(request.operation_id, patch)
if boundary == "hidden_witness":
    workspace = path / "workspace.json"
    (path / "own-witness.json").write_bytes(workspace.read_bytes())
    config = json.loads(workspace.read_text())
    config["_broker_account_store"]["operation_id"] = str(uuid4())
    workspace.write_text(json.dumps(config))
    try:
        participant.recover()
    except BrokerAccountWorkspaceUnavailable:
        pass
    operation = store.operation(request.operation_id)
    assert operation.state is AccountOperationStage.PLAN_READY and operation.workspace_conflicted
    os._exit(23)
store.apply(request.operation_id, witness)
"""
    env = dict(os.environ, CRASH_BOUNDARY=boundary)
    process = subprocess.run([sys.executable, "-c", script], env=env, capture_output=True, text=True, timeout=20)
    assert process.returncode == 23, process.stderr
    lease = acquire_backend_instance_lease()
    credentials = CredentialStore(tmp_path / "vault.db", "synthetic-password")
    try:
        store = AccountTransactionStore(credentials, workspace_path=tmp_path, backend_proof=lease.proof)
        participant = workspace_module().BrokerAccountWorkspace(tmp_path, store, lease.proof)
        if boundary == "hidden_witness":
            (tmp_path / "workspace.json").write_bytes((tmp_path / "own-witness.json").read_bytes())
        receipts = participant.recover()
        assert participant.recover() == receipts
        snapshot = participant.assert_coherent()
        assert store.head().to_dict() == snapshot.as_dict()["_broker_account_store"]
        assert len(receipts) == int(boundary.startswith("workspace") or boundary in ("vault_apply", "hidden_witness"))
        if receipts:
            assert receipts[0].credential_version.generation == 1
        if boundary == "hidden_witness":
            operation = store.operation(receipts[0].operation_id)
            assert operation.workspace_attempted and operation.workspace_conflicted
            called = []
            with pytest.raises(workspace_module().BrokerAccountWorkspaceUnavailable):
                participant.with_current_authority(operation.operation_id, lambda *_args: called.append(True))
            assert called == []
    finally:
        credentials.close()
        lease.release()


def test_vault_application_result_loss_is_reconciled_in_same_recovery(owned, monkeypatch):
    request, _, _ = planned(owned)
    original = owned[3].apply

    def applied_then_error(*args, **kwargs):
        original(*args, **kwargs)
        raise OSError("synthetic result loss")

    monkeypatch.setattr(owned[3], "apply", applied_then_error)
    receipt, = owned[4].recover()
    assert receipt == owned[3].operation(request.operation_id).receipt
    assert receipt.credential_version.generation == 1
    assert owned[4].recover() == (receipt,)


def test_newer_vault_state_is_not_witnessed_or_overwritten(owned):
    request, _, _ = planned(owned)
    with owned[3]._transaction(write=True) as conn:
        owned[2]._bump(conn, request.selector)
    before = (owned[0] / "workspace.json").read_bytes()
    with pytest.raises(Exception):
        owned[4].recover()
    assert (owned[0] / "workspace.json").read_bytes() == before
    assert owned[2].selector_state(request.selector).version.generation == 1


def test_pending_genesis_rejects_changed_broker_domain(owned, monkeypatch):
    original = owned[3].prepare_enrolment

    def prepared_then_crash(*args, **kwargs):
        original(*args, **kwargs)
        raise Crash()

    monkeypatch.setattr(owned[3], "prepare_enrolment", prepared_then_crash)
    with pytest.raises(Crash):
        owned[4].enrol()
    monkeypatch.setattr(owned[3], "prepare_enrolment", original)
    update_workspace_config(owned[0], lambda config: config["brokers"]["execution"].update(default="dhan:Newer"))
    before = (owned[0] / "workspace.json").read_bytes()
    with pytest.raises(owned[5].BrokerAccountWorkspaceUnavailable):
        owned[4].recover()
    assert (owned[0] / "workspace.json").read_bytes() == before
    assert owned[3].head() is None


def test_concurrent_ui_and_service_publications_preserve_owned_broker_commit(owned):
    from concurrent.futures import ThreadPoolExecutor
    from threading import Barrier

    from flinttrade_core.service_connection_store import ConnectionActorContext, ServiceConnectionStore

    request, _, _ = planned(owned)
    service = ServiceConnectionStore(owned[0])
    etag = service.read_snapshot().etag
    barrier = Barrier(3)

    def ui():
        barrier.wait()
        update_workspace_config(owned[0], lambda config: config["ui"].update(theme="light"))

    def connection():
        barrier.wait()
        return service.mutate(
            "create", {"provider_id": "llm:ollama", "label": "Local"}, connection_id=None,
            expected_etag=etag, idempotency_key=str(uuid4()),
            actor_context=ConnectionActorContext("operator", "session:" + "a" * 64),
        )

    def recover():
        barrier.wait()
        return owned[4].recover()

    with ThreadPoolExecutor(max_workers=3) as pool:
        ui_future, service_future, recovery_future = pool.submit(ui), pool.submit(connection), pool.submit(recover)
        ui_future.result(timeout=20)
        service_result = service_future.result(timeout=20)
        receipts = recovery_future.result(timeout=20)
    assert service_result.status == 201
    assert receipts[0].operation_id == request.operation_id
    snapshot = owned[4].assert_coherent()
    assert snapshot.config["ui"]["theme"] == "light"
    assert len(service.read_snapshot().connections) == 1
    assert "dhan:Synthetic" in snapshot.config["brokers"]["registered"]


def test_genesis_completion_result_loss_is_reconciled_in_same_enrolment(owned, monkeypatch):
    original = owned[3].complete_enrolment

    def completed_then_error(*args, **kwargs):
        original(*args, **kwargs)
        raise OSError("synthetic result loss")

    monkeypatch.setattr(owned[3], "complete_enrolment", completed_then_error)
    witness = owned[4].enrol()
    assert witness == owned[3].head()
    assert owned[4].assert_coherent().version == witness.commit_workspace


@pytest.mark.parametrize("entry", ["recover", "commit"])
@pytest.mark.parametrize("foreign", ["broker", "instance", "marker", "credential"])
def test_confirmed_foreign_conflict_remains_blocked_after_aba_restoration(owned, entry, foreign):
    request, patch, _ = planned(owned)
    path = owned[0] / "workspace.json"
    original = path.read_bytes()
    config = json.loads(original)
    if foreign == "broker":
        config["brokers"]["registered"].append("dhan:Newer")
        config["workspace_generation"] += 1
        config["broker_authority_generation"] += 1
    elif foreign == "instance":
        config["workspace_instance_id"] = str(uuid4())
    elif foreign == "marker":
        marker = config["_broker_account_store"]
        marker["operation_id"] = str(uuid4())
    else:
        with owned[3]._transaction(write=True) as conn:
            owned[2]._bump(conn, request.selector)
    path.write_text(json.dumps(config))
    foreign_bytes = path.read_bytes()
    action = owned[4].recover if entry == "recover" else lambda: owned[4].commit(request.operation_id, patch)
    with pytest.raises(Exception):
        action()
    operation = owned[3].operation(request.operation_id)
    assert operation.state is AccountOperationStage.BLOCKED
    assert operation.receipt.reason == "foreign_account_authority"
    assert owned[3].recovery_material(owned[3].owner_capability(owned[1].proof), request.operation_id).request is None
    assert path.read_bytes() == foreign_bytes
    path.write_bytes(original)
    if foreign == "credential":
        with owned[3]._transaction(write=True) as conn:
            conn.execute("DELETE FROM credential_selector_versions WHERE adapter_id=? AND account_id=?", (
                request.selector.adapter_id, request.selector.account_id,
            ))
    assert owned[4].recover() == (operation.receipt,)
    assert owned[4].recover() == (operation.receipt,)
    with pytest.raises(owned[5].BrokerAccountWorkspaceUnavailable):
        owned[4].commit(request.operation_id, patch)
    assert path.read_bytes() == original
    assert owned[2].selector_state(request.selector).version.generation == 0
    assert owned[3].active_operation(owned[3].owner_capability(owned[1].proof)).receipt == operation.receipt


@pytest.mark.parametrize("uncertain", ["missing_marker", "malformed_marker", "invalid_json", "read_error"])
def test_uncertain_workspace_preserves_plan_until_own_witness_can_be_read(owned, monkeypatch, uncertain):
    request, patch, _ = planned(owned)
    witness = owned[4].commit(request.operation_id, patch)
    path = owned[0] / "workspace.json"
    original = path.read_bytes()
    before = owned[3].recovery_material(owned[3].owner_capability(owned[1].proof), request.operation_id)
    config = json.loads(original)
    from flinttrade_core import workspace_migrations
    original_reader = workspace_migrations._run_migrations_locked
    if uncertain == "missing_marker":
        config.pop("_broker_account_store")
        path.write_text(json.dumps(config))
    elif uncertain == "malformed_marker":
        config["_broker_account_store"]["epoch"] = True
        path.write_text(json.dumps(config))
    elif uncertain == "invalid_json":
        path.write_text("{unreadable")
    else:
        def unavailable(_path):
            raise OSError("synthetic unavailable workspace")

        monkeypatch.setattr(workspace_migrations, "_run_migrations_locked", unavailable)
    uncertain_bytes = path.read_bytes()
    with pytest.raises(Exception):
        owned[4].recover()
    operation = owned[3].operation(request.operation_id)
    assert operation.state is AccountOperationStage.PLAN_READY and operation.receipt is None
    assert owned[3].recovery_material(owned[3].owner_capability(owned[1].proof), request.operation_id) == before
    assert path.read_bytes() == uncertain_bytes
    monkeypatch.setattr(workspace_migrations, "_run_migrations_locked", original_reader)
    path.write_bytes(original)
    receipt, = owned[4].recover()
    assert receipt.state is AccountOperationStage.COMMITTED
    assert receipt.commit_workspace == witness.commit_workspace
    assert receipt.credential_version.generation == 1


def test_own_witness_domain_damage_is_uncertainty_not_commit_absence(owned):
    request, patch, _ = planned(owned)
    witness = owned[4].commit(request.operation_id, patch)
    path = owned[0] / "workspace.json"
    original = path.read_bytes()
    config = json.loads(original)
    config["brokers"]["registered"].append("dhan:Other")
    path.write_text(json.dumps(config))
    with pytest.raises(owned[5].BrokerAccountWorkspaceUnavailable):
        owned[4].recover()
    assert owned[3].operation(request.operation_id).state is AccountOperationStage.PLAN_READY
    path.write_bytes(original)
    receipt, = owned[4].recover()
    assert receipt.commit_workspace == witness.commit_workspace


def test_invalid_vault_is_not_mutated_to_record_blocked_disposition(owned):
    import sqlite3

    request, patch, _ = planned(owned)
    owned[4].commit(request.operation_id, patch)
    with sqlite3.connect(owned[0] / "vault.db") as conn:
        original = conn.execute("SELECT mac FROM account_store_head").fetchone()[0]
        conn.execute("UPDATE account_store_head SET mac=?", ("0" * 64,))
    with pytest.raises(Exception):
        owned[4].recover()
    with sqlite3.connect(owned[0] / "vault.db") as conn:
        assert conn.execute("SELECT mac FROM account_store_head").fetchone()[0] == "0" * 64
        conn.execute("UPDATE account_store_head SET mac=?", (original,))
    assert owned[3].operation(request.operation_id).state is AccountOperationStage.PLAN_READY
    receipt, = owned[4].recover()
    assert receipt.state is AccountOperationStage.COMMITTED


def test_recovery_persistence_failure_preserves_own_witness_and_staging(owned, monkeypatch):
    from flinttrade_core import secure_file

    request, patch, _ = planned(owned)
    witness = owned[4].commit(request.operation_id, patch)
    original_flush = secure_file.fsync_parent_directory
    original = (owned[0] / "workspace.json").read_bytes()

    def unavailable(_path):
        raise OSError("synthetic unavailable persistence barrier")

    monkeypatch.setattr(secure_file, "fsync_parent_directory", unavailable)
    with pytest.raises(OSError):
        owned[4].recover()
    assert owned[3].operation(request.operation_id).state is AccountOperationStage.PLAN_READY
    assert (owned[0] / "workspace.json").read_bytes() == original
    monkeypatch.setattr(secure_file, "fsync_parent_directory", original_flush)
    receipt, = owned[4].recover()
    assert receipt.commit_workspace == witness.commit_workspace


def test_committed_abandonment_evidence_prevents_false_commit_absence_disposition(owned):
    request, patch, _ = planned(owned)
    witness = owned[4].commit(request.operation_id, patch)
    owned[3].abandon(request.operation_id, committed=True, reason="caller_cancelled")
    path = owned[0] / "workspace.json"
    original = path.read_bytes()
    config = json.loads(original)
    config["_broker_account_store"]["operation_id"] = str(uuid4())
    path.write_text(json.dumps(config))
    with pytest.raises(owned[5].BrokerAccountWorkspaceUnavailable):
        owned[4].recover()
    operation = owned[3].operation(request.operation_id)
    assert operation.state is AccountOperationStage.PLAN_READY and operation.abandonment_committed
    assert owned[3].recovery_material(owned[3].owner_capability(owned[1].proof), request.operation_id).request is not None
    path.write_bytes(original)
    receipt, = owned[4].recover()
    assert receipt.state is AccountOperationStage.COMMITTED
    assert receipt.commit_workspace == witness.commit_workspace


@pytest.mark.parametrize("entry", ["recover", "commit"])
def test_hidden_own_witness_retains_plan_rolls_forward_and_permanently_fences_publication(owned, entry):
    request, patch, _ = planned(owned)
    witness = owned[4].commit(request.operation_id, patch)
    path = owned[0] / "workspace.json"
    own_bytes = path.read_bytes()
    config = json.loads(own_bytes)
    config["_broker_account_store"]["operation_id"] = str(uuid4())
    path.write_text(json.dumps(config))
    foreign_bytes = path.read_bytes()
    action = owned[4].recover if entry == "recover" else lambda: owned[4].commit(request.operation_id, patch)
    with pytest.raises(owned[5].BrokerAccountWorkspaceUnavailable):
        action()
    operation = owned[3].operation(request.operation_id)
    assert operation.state is AccountOperationStage.PLAN_READY, "a hidden own commit must retain staging"
    assert operation.workspace_attempted and operation.workspace_conflicted
    assert owned[3].recovery_material(owned[3].owner_capability(owned[1].proof), request.operation_id).request is not None
    assert path.read_bytes() == foreign_bytes
    path.write_bytes(own_bytes)
    receipt, = owned[4].recover()
    assert receipt.state is AccountOperationStage.COMMITTED and receipt.commit_workspace == witness.commit_workspace
    assert receipt.credential_version.generation == 1
    assert owned[4].recover() == (receipt,)
    called = []
    with pytest.raises(owned[5].BrokerAccountWorkspaceUnavailable):
        owned[4].with_current_authority(request.operation_id, lambda *_args: called.append(True))
    assert called == []
    assert owned[3].operation(request.operation_id).workspace_conflicted
    from flinttrade_gateway.account_transaction_store import AccountTransactionStore

    reopened = AccountTransactionStore(owned[2], workspace_path=owned[0], backend_proof=owned[1].proof)
    participant = owned[5].BrokerAccountWorkspace(owned[0], reopened, owned[1].proof)
    with pytest.raises(owned[5].BrokerAccountWorkspaceUnavailable):
        participant.with_current_authority(request.operation_id, lambda *_args: called.append(True))
    assert called == []


@pytest.mark.parametrize("entry", ["recover", "commit"])
def test_attempted_unknown_write_never_re_cas_after_foreign_and_original_base_restoration(owned, monkeypatch, entry):
    from flinttrade_core import workspace_migrations

    request, patch, _ = planned(owned)
    path = owned[0] / "workspace.json"
    base_bytes = path.read_bytes()
    calls = []

    def write_unknown(*args, **kwargs):
        calls.append(True)
        raise OSError("synthetic uncertain workspace dispatch")

    monkeypatch.setattr(workspace_migrations, "_atomic_write", write_unknown)
    with pytest.raises(OSError):
        owned[4].commit(request.operation_id, patch)
    operation = owned[3].operation(request.operation_id)
    assert hasattr(operation, "workspace_attempted"), "the pre-dispatch phase is not recorded"
    assert operation.workspace_attempted and operation.workspace_conflicted
    config = json.loads(base_bytes)
    config["brokers"]["registered"].append("dhan:Foreign")
    config["workspace_generation"] += 1
    config["broker_authority_generation"] += 1
    path.write_text(json.dumps(config))
    action = owned[4].recover if entry == "recover" else lambda: owned[4].commit(request.operation_id, patch)
    with pytest.raises(owned[5].BrokerAccountWorkspaceUnavailable):
        action()
    assert owned[3].operation(request.operation_id).state is AccountOperationStage.PLAN_READY
    path.write_bytes(base_bytes)
    for _ in range(2):
        with pytest.raises(owned[5].BrokerAccountWorkspaceUnavailable):
            action()
    assert calls == [True], "an attempted operation dispatched another workspace CAS"
    assert path.read_bytes() == base_bytes
    assert owned[2].selector_state(request.selector).version.generation == 0
    assert owned[3].recovery_material(owned[3].owner_capability(owned[1].proof), request.operation_id).request is not None


def test_interruption_after_attempt_record_before_dispatch_stays_unresolved(owned, monkeypatch):
    request, patch, _ = planned(owned)
    store = owned[3]
    assert callable(getattr(store, "mark_workspace_attempted", None)), "durable workspace dispatch evidence is missing"
    original = store.mark_workspace_attempted

    def recorded_then_crash(*args, **kwargs):
        original(*args, **kwargs)
        raise Crash()

    monkeypatch.setattr(store, "mark_workspace_attempted", recorded_then_crash)
    before = (owned[0] / "workspace.json").read_bytes()
    with pytest.raises(Crash):
        owned[4].commit(request.operation_id, patch)
    monkeypatch.setattr(store, "mark_workspace_attempted", original)
    operation = store.operation(request.operation_id)
    assert operation.workspace_attempted and not operation.workspace_conflicted
    with pytest.raises(owned[5].BrokerAccountWorkspaceUnavailable):
        owned[4].recover()
    assert store.operation(request.operation_id).workspace_conflicted
    assert (owned[0] / "workspace.json").read_bytes() == before
    assert owned[2].selector_state(request.selector).version.generation == 0


def _committed_entry(owned, request, patch, entry, callback):
    if entry == "commit":
        return owned[4].commit(request.operation_id, patch)
    if entry == "recover":
        return owned[4].recover()
    return owned[4].with_current_authority(request.operation_id, callback)


def _foreign_committed_workspace(path, foreign):
    own_bytes = path.read_bytes()
    config = json.loads(own_bytes)
    if foreign == "marker":
        config["_broker_account_store"]["operation_id"] = str(uuid4())
    else:
        config["brokers"]["registered"].append("dhan:Foreign")
        config["workspace_generation"] += 1
        config["broker_authority_generation"] += 1
    path.write_text(json.dumps(config))
    return own_bytes, path.read_bytes()


@pytest.mark.parametrize("entry", ["commit", "recover", "publish"])
@pytest.mark.parametrize("release_claim", [False, True])
@pytest.mark.parametrize("foreign", ["marker", "domain"])
def test_foreign_committed_state_permanently_fences_retained_and_released_publication(
    owned, entry, release_claim, foreign,
):
    path, lease, credentials, store, participant, module = owned
    request, patch, _ = planned(owned)
    witness = participant.commit(request.operation_id, patch)
    receipt = store.apply(request.operation_id, witness)
    if release_claim:
        store.release_claim(request.operation_id)
    before = store.operation(request.operation_id)
    credential = credentials.selector_state(request.selector).version
    workspace = path / "workspace.json"
    own_bytes, foreign_bytes = _foreign_committed_workspace(workspace, foreign)
    called = []
    with pytest.raises(module.BrokerAccountWorkspaceUnavailable):
        _committed_entry(owned, request, patch, entry, lambda *_args: called.append(True))
    assert called == []
    assert workspace.read_bytes() == foreign_bytes
    operation = store.operation(request.operation_id)
    assert operation.workspace_conflicted, "observed foreign committed state must durably fence old publication"
    assert operation == replace(before, workspace_conflicted=True)
    assert store.head() == witness
    assert credentials.selector_state(request.selector).version == credential == receipt.credential_version
    workspace.write_bytes(own_bytes)
    reopened = type(store)(credentials, workspace_path=path, backend_proof=lease.proof)
    participant = module.BrokerAccountWorkspace(path, reopened, lease.proof)
    assert participant.recover() == (() if release_claim else (receipt,))
    with pytest.raises(module.BrokerAccountWorkspaceUnavailable):
        participant.with_current_authority(request.operation_id, lambda *_args: called.append(True))
    assert called == []
    assert reopened.operation(request.operation_id) == operation
    assert reopened.head() == witness
    assert credentials.selector_state(request.selector).version == credential
    assert workspace.read_bytes() == own_bytes

    # A genuinely new process/proof must retain the same publication refusal.
    credentials.close()
    lease.release()
    script = r"""
import sys
from pathlib import Path
from uuid import UUID
from flinttrade_core.backend_instance import acquire_backend_instance_lease
from flinttrade_core.broker_account_workspace import BrokerAccountWorkspace, BrokerAccountWorkspaceUnavailable
from flinttrade_gateway.account_transaction_store import AccountTransactionStore
from flinttrade_gateway.credentials import CredentialStore
path = Path(sys.argv[1])
operation_id = UUID(sys.argv[2])
lease = acquire_backend_instance_lease()
credentials = CredentialStore(path / "vault.db", "synthetic-password")
store = AccountTransactionStore(credentials, workspace_path=path, backend_proof=lease.proof)
participant = BrokerAccountWorkspace(path, store, lease.proof)
operation = store.operation(operation_id)
assert operation.workspace_conflicted and operation.workspace_attempted
assert store.head() == operation.witness
assert credentials.selector_state(operation.selector).version == operation.receipt.credential_version
called = []
try:
    participant.with_current_authority(operation_id, lambda *_args: called.append(True))
except BrokerAccountWorkspaceUnavailable:
    pass
else:
    raise AssertionError("old publication revived in a fresh process")
assert called == []
assert store.operation(operation_id) == operation
credentials.close()
lease.release()
"""
    result = subprocess.run(
        [sys.executable, "-c", script, str(path), str(request.operation_id)],
        capture_output=True, text=True, timeout=20,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert workspace.read_bytes() == own_bytes


@pytest.mark.parametrize("entry", ["recover", "publish"])
@pytest.mark.parametrize("release_claim", [False, True])
@pytest.mark.parametrize("unavailable", ["invalid", "unreadable", "revoked"])
def test_untrusted_committed_vault_cannot_authorise_foreign_conflict_write(
    owned, monkeypatch, entry, release_claim, unavailable,
):
    import sqlite3

    path, lease, credentials, store, _, _ = owned
    request, patch, _ = planned(owned)
    witness = owned[4].commit(request.operation_id, patch)
    receipt = store.apply(request.operation_id, witness)
    if release_claim:
        store.release_claim(request.operation_id)
    own_bytes, foreign_bytes = _foreign_committed_workspace(path / "workspace.json", "marker")
    original_transaction = credentials._transaction
    with sqlite3.connect(path / "vault.db") as conn:
        original_mac = conn.execute("SELECT mac FROM account_store_head").fetchone()[0]
        if unavailable == "invalid":
            conn.execute("UPDATE account_store_head SET mac=?", ("0" * 64,))
    if unavailable == "unreadable":
        def unreadable(*_args, **_kwargs):
            raise OSError("synthetic unavailable vault")

        monkeypatch.setattr(credentials, "_transaction", unreadable)
    elif unavailable == "revoked":
        lease.release()
    with sqlite3.connect(path / "vault.db") as conn:
        before_head = conn.execute("SELECT * FROM account_store_head").fetchall()
        before_operations = conn.execute("SELECT * FROM account_operations").fetchall()
    called = []
    with pytest.raises(Exception):
        _committed_entry(owned, request, patch, entry, lambda *_args: called.append(True))
    assert called == []
    assert (path / "workspace.json").read_bytes() == foreign_bytes
    with sqlite3.connect(path / "vault.db") as conn:
        assert conn.execute("SELECT * FROM account_store_head").fetchall() == before_head
        assert conn.execute("SELECT * FROM account_operations").fetchall() == before_operations
        if unavailable == "invalid":
            conn.execute("UPDATE account_store_head SET mac=?", (original_mac,))
    monkeypatch.setattr(credentials, "_transaction", original_transaction)
    (path / "workspace.json").write_bytes(own_bytes)
    if unavailable != "revoked":
        assert store.operation(request.operation_id).receipt == receipt
        assert not store.operation(request.operation_id).workspace_conflicted
        owned[4].with_current_authority(request.operation_id, lambda *_args: called.append(True))
        assert called == [True]


@pytest.mark.parametrize("release_claim", [False, True])
@pytest.mark.parametrize("failure", ["ordinary", "workspace_unavailable"])
def test_coherent_publication_callback_failure_does_not_imply_foreign_state(owned, release_claim, failure):
    request, patch, _ = planned(owned)
    witness = owned[4].commit(request.operation_id, patch)
    receipt = owned[3].apply(request.operation_id, witness)
    if release_claim:
        owned[3].release_claim(request.operation_id)
    before = owned[3].operation(request.operation_id)
    workspace = (owned[0] / "workspace.json").read_bytes()
    called = []
    error = RuntimeError if failure == "ordinary" else owned[5].BrokerAccountWorkspaceUnavailable

    def failed_callback(*_args):
        called.append(True)
        raise error()

    with pytest.raises(error):
        owned[4].with_current_authority(request.operation_id, failed_callback)
    assert called == [True]
    assert owned[3].operation(request.operation_id) == before
    assert owned[3].head() == witness
    assert owned[2].selector_state(request.selector).version == receipt.credential_version
    owned[4].with_current_authority(request.operation_id, lambda *_args: called.append(True))
    assert called == [True, True]
    assert (owned[0] / "workspace.json").read_bytes() == workspace
