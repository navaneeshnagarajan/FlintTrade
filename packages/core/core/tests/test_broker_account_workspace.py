"""Real-file broker domain witnesses and exact publication authority."""

import importlib
import importlib.util
from dataclasses import replace
from uuid import uuid4

import pytest

from flinttrade_core.account_lifecycle_contracts import (
    AccountActorContext,
    AccountMutationKind,
    AccountMutationRequest,
    AccountOperationStage,
    broker_account_digest,
)
from flinttrade_core.backend_instance import acquire_backend_instance_lease
from flinttrade_core.broker_identity import BrokerSelector
from flinttrade_core.secure_file import harden_directory
from flinttrade_core.workspace_migrations import (
    broker_workspace_version,
    read_workspace_snapshot,
    update_workspace_config,
    write_workspace_config,
    default_workspace_config,
)
from flinttrade_gateway.account_transaction_store import AccountTransactionStore
from flinttrade_gateway.credentials import CredentialStore


def workspace_module():
    name = "flinttrade_core.broker_account_workspace"
    assert importlib.util.find_spec(name) is not None, "owned broker workspace participant is missing"
    return importlib.import_module(name)


@pytest.fixture
def owned(tmp_path, monkeypatch):
    harden_directory(tmp_path)
    monkeypatch.setenv("FLINTTRADE_WORKSPACE_DIR", str(tmp_path))
    write_workspace_config(tmp_path, default_workspace_config(), expected_version=None)
    lease = acquire_backend_instance_lease()
    credentials = CredentialStore(tmp_path / "vault.db", "synthetic-password")
    store = AccountTransactionStore(credentials, workspace_path=tmp_path, backend_proof=lease.proof)
    module = workspace_module()
    participant = module.BrokerAccountWorkspace(tmp_path, store, lease.proof)
    yield tmp_path, lease, credentials, store, participant, module
    credentials.close()
    lease.release()


def planned(owned, *, kind=AccountMutationKind.CONNECT, selector=None, roles=(), read_only=False):
    path, _, credentials, store, participant, module = owned
    participant.enrol()
    snapshot = participant.assert_coherent()
    selector = selector or BrokerSelector("dhan", "Synthetic")
    request = AccountMutationRequest(
        uuid4(),
        kind,
        selector,
        AccountActorContext("operator", "session:" + "a" * 64),
        snapshot.version,
        broker_workspace_version(snapshot),
        credentials.selector_state(selector).version,
        selector.adapter_id,
        "Synthetic",
        None if kind is AccountMutationKind.REMOVE else {"token": "input"},
        roles,
    )
    patch = module.BrokerAccountPatch(kind, selector, roles, None if kind is AccountMutationKind.REMOVE else read_only)
    store.admit(request)
    if kind is not AccountMutationKind.REMOVE:
        store.mark_authentication_started(request.operation_id)
    store.stage_plan(
        request.operation_id,
        replay_credentials=None if kind is AccountMutationKind.REMOVE else {"token": "replay"},
        read_only=None if kind is AccountMutationKind.REMOVE else read_only,
        before_digest=broker_account_digest(snapshot),
        after_digest=broker_account_digest(patch.apply(snapshot.config)),
    )
    return request, patch, snapshot


def finish(owned, request, patch):
    witness = owned[4].commit(request.operation_id, patch)
    receipt = owned[3].apply(request.operation_id, witness)
    owned[3].release_claim(request.operation_id)
    return witness, receipt


def test_genesis_stamps_actual_versions_without_changing_broker_liveness(owned):
    path, _, _, store, participant, _ = owned
    before = read_workspace_snapshot(path)
    witness = participant.enrol()
    after = participant.assert_coherent()
    assert witness.epoch == 0
    assert witness.commit_workspace == after.version
    assert witness.commit_workspace.generation == before.version.generation + 1
    assert witness.commit_broker_workspace == broker_workspace_version(before) == broker_workspace_version(after)
    assert witness.before_digest == witness.after_digest == broker_account_digest(before)
    assert after.as_dict()["_broker_account_store"] == witness.to_dict()
    assert store.head() == witness
    assert participant.enrol() == witness
    assert read_workspace_snapshot(path).version == after.version


@pytest.mark.parametrize("change", ["remove", "replace", "brokers", "registered"])
def test_generic_updates_cannot_change_enrolled_marker_or_broker_domain(owned, change):
    path, _, _, _, participant, _ = owned
    participant.enrol()
    before = (path / "workspace.json").read_bytes()

    def mutate(config):
        if change == "remove":
            config.pop("_broker_account_store")
        elif change == "replace":
            config["_broker_account_store"] = None
        elif change == "brokers":
            config["brokers"]["execution"]["default"] = "dhan:Other"
        else:
            config["brokers"]["registered"].append("upstox:Other")

    with pytest.raises(ValueError, match="broker_account_workspace_owned"):
        update_workspace_config(path, mutate)
    assert (path / "workspace.json").read_bytes() == before


def test_generic_writer_cannot_forge_first_marker(owned):
    path = owned[0]
    with pytest.raises(ValueError, match="broker_account_workspace_owned"):
        update_workspace_config(path, lambda config: config.update(_broker_account_store={"schema": 1}))


def test_connect_rebases_unrelated_ui_and_service_changes_without_acl_or_default_widening(owned):
    request, patch, before = planned(owned, roles=("quote",))
    path, _, credentials, store, participant, _ = owned

    def unrelated(config):
        config["ui"]["theme"] = "light"
        config["services"]["connection_epoch"] = 1
        config["ui"]["ordinary_metadata"] = "ordinary-metadata"

    update_workspace_config(path, unrelated)
    current = read_workspace_snapshot(path)
    witness, receipt = finish(owned, request, patch)
    after = participant.assert_coherent()
    assert witness.commit_workspace.generation == current.version.generation + 1
    assert witness.commit_workspace == receipt.commit_workspace == after.version
    assert witness.commit_broker_workspace.generation == broker_workspace_version(before).generation + 1
    assert after.config["ui"]["theme"] == "light"
    assert after.config["services"]["connection_epoch"] == 1
    assert after.config["ui"]["ordinary_metadata"] == "ordinary-metadata"
    assert after.config["brokers"]["data"]["quote"] == "dhan:Synthetic"
    assert after.config["brokers"]["execution"]["default"] == before.config["brokers"]["execution"]["default"]
    assert after.config["brokers"]["account_acls"] == before.config["brokers"]["account_acls"]
    assert credentials.selector_state(request.selector).version == receipt.credential_version
    assert store.operation(request.operation_id).state is AccountOperationStage.COMMITTED


def test_token_rotation_changes_epoch_and_full_version_only(owned):
    request, patch, _ = planned(owned)
    head, _ = finish(owned, request, patch)
    request, patch, before = planned(owned, kind=AccountMutationKind.ROTATE)
    witness, receipt = finish(owned, request, patch)
    after = owned[4].assert_coherent()
    assert witness.epoch == head.epoch + 1
    assert witness.before_digest == witness.after_digest
    assert witness.commit_workspace.generation == before.version.generation + 1
    assert witness.commit_broker_workspace == broker_workspace_version(before) == broker_workspace_version(after)
    assert receipt.credential_version.generation == 2


def test_read_only_demotion_and_remove_clear_only_exact_references(owned):
    path, _, _, _, participant, module = owned
    selector = BrokerSelector("dhan", "Synthetic")

    def seed(config):
        brokers = config["brokers"]
        brokers["registered"].extend(["dhan:Synthetic", "dhan:Other"])
        brokers["execution"]["default"] = "dhan:Synthetic"
        brokers["failover"]["order"] = ["dhan:Synthetic", "dhan:Other"]
        brokers["account_acls"] = {"dhan": {"Synthetic": ["operator"], "Other": ["other"]}}
        brokers["data"]["quote"] = "dhan:Synthetic"

    update_workspace_config(path, seed)
    before = read_workspace_snapshot(path)
    demoted = module.BrokerAccountPatch(AccountMutationKind.RECONNECT, selector, (), True).apply(before.config)
    assert demoted["brokers"]["execution"]["default"] == ""
    assert demoted["brokers"]["failover"]["order"] == ["dhan:Other"]
    assert demoted["brokers"]["account_acls"] == before.as_dict()["brokers"]["account_acls"]
    request, patch, _ = planned(owned, kind=AccountMutationKind.REMOVE, selector=selector)
    finish(owned, request, patch)
    after = participant.assert_coherent().as_dict()["brokers"]
    assert "dhan:Synthetic" not in after["registered"]
    assert after["account_acls"] == {"dhan": {"Other": ["other"]}}
    assert after["execution"]["default"] == ""
    assert after["data"]["quote"] == ""
    assert after["failover"]["order"] == ["dhan:Other"]


def test_patch_refuses_unsupported_roles_and_reconnect_role_changes(owned):
    module = owned[5]
    for kind, roles, read_only in [
        (AccountMutationKind.CONNECT, ("bad",), False),
        (AccountMutationKind.RECONNECT, ("quote",), False),
        (AccountMutationKind.REMOVE, (), False),
        (AccountMutationKind.CONNECT, (), 1),
    ]:
        with pytest.raises(ValueError):
            module.BrokerAccountPatch(kind, BrokerSelector("dhan", "Synthetic"), roles, read_only)


def test_commit_requires_exact_private_plan_and_is_witness_idempotent(owned):
    request, patch, _ = planned(owned)
    module = owned[5]
    before = (owned[0] / "workspace.json").read_bytes()
    with pytest.raises(ValueError):
        owned[4].commit(request.operation_id, replace(patch, selector=BrokerSelector("dhan", "Other")))
    assert (owned[0] / "workspace.json").read_bytes() == before
    witness = owned[4].commit(request.operation_id, patch)
    assert owned[3].head().epoch == 0  # workspace commit decides; vault still original
    assert owned[4].commit(request.operation_id, patch) == witness
    with pytest.raises(module.BrokerAccountWorkspaceUnavailable):
        owned[4].assert_coherent()


def test_publication_callback_uses_one_locked_current_snapshot_and_exact_credential(owned, monkeypatch):
    request, patch, _ = planned(owned)
    witness, receipt = finish(owned, request, patch)
    update_workspace_config(owned[0], lambda config: config["ui"].update(theme="light"))
    expected = read_workspace_snapshot(owned[0])
    # A second FileLock acquisition is forbidden, even in one process.
    from flinttrade_core import workspace_migrations

    original = workspace_migrations._migration_lock
    calls = []

    def counted(*args, **kwargs):
        calls.append(1)
        assert len(calls) == 1
        return original(*args, **kwargs)

    monkeypatch.setattr(workspace_migrations, "_migration_lock", counted)
    result = owned[4].with_current_authority(request.operation_id, lambda snapshot, version: (snapshot, version))
    assert result == (expected, receipt.credential_version)
    assert result[0].version.generation > witness.commit_workspace.generation
    assert len(calls) == 1


def test_foreign_marker_is_not_adopted_or_overwritten(owned):
    import json

    path, _, _, _, participant, module = owned
    witness = participant.enrol()
    config = read_workspace_snapshot(path).as_dict()
    config["_broker_account_store"] = replace(witness, operation_id=uuid4()).to_dict()
    (path / "workspace.json").write_text(json.dumps(config))
    before = (path / "workspace.json").read_bytes()
    for action in (participant.enrol, participant.assert_coherent, participant.recover):
        with pytest.raises(module.BrokerAccountWorkspaceUnavailable):
            action()
        assert (path / "workspace.json").read_bytes() == before


def test_constructor_and_each_action_require_live_same_workspace_proof(owned):
    path, lease, _, store, participant, module = owned
    with pytest.raises(Exception):
        module.BrokerAccountWorkspace(path.parent, store, lease.proof)
    participant.enrol()
    lease.release()
    for action in (participant.enrol, participant.assert_coherent, participant.recover):
        with pytest.raises(Exception):
            action()


def test_owned_workspace_participant_is_available():
    workspace_module()


def test_unowned_generic_marker_insertion_is_rejected(tmp_path):
    write_workspace_config(tmp_path, default_workspace_config(), expected_version=None)
    with pytest.raises(ValueError, match="broker_account_workspace_owned"):
        update_workspace_config(tmp_path, lambda config: config.update(_broker_account_store={"schema": 1}))


def test_workspace_replace_result_loss_returns_exact_written_witness(owned, monkeypatch):
    request, patch, _ = planned(owned)
    from flinttrade_core import workspace_migrations

    original = workspace_migrations._atomic_write

    def installed_then_error(*args, **kwargs):
        original(*args, **kwargs)
        raise OSError("synthetic result loss")

    monkeypatch.setattr(workspace_migrations, "_atomic_write", installed_then_error)
    witness = owned[4].commit(request.operation_id, patch)
    actual = read_workspace_snapshot(owned[0])
    assert actual.as_dict()["_broker_account_store"] == witness.to_dict()
    assert actual.version == witness.commit_workspace
    assert owned[4].commit(request.operation_id, patch) == witness


def test_publication_callback_refuses_awaitable_work(owned):
    request, patch, _ = planned(owned)
    finish(owned, request, patch)

    async def asynchronous(snapshot, version):
        return snapshot, version

    with pytest.raises(owned[5].BrokerAccountWorkspaceUnavailable):
        owned[4].with_current_authority(request.operation_id, asynchronous)


def test_superseded_operation_cannot_publish_against_new_marker(owned):
    request, patch, _ = planned(owned)
    finish(owned, request, patch)
    prior = request.operation_id
    request, patch, _ = planned(owned, kind=AccountMutationKind.ROTATE)
    finish(owned, request, patch)
    called = []
    with pytest.raises(owned[5].BrokerAccountWorkspaceUnavailable):
        owned[4].with_current_authority(prior, lambda *_args: called.append(True))
    assert called == []


@pytest.mark.parametrize("remove", [False, True])
def test_abandoned_commit_or_removal_has_no_publication_authority(owned, remove):
    request, patch, _ = planned(owned, kind=AccountMutationKind.REMOVE if remove else AccountMutationKind.CONNECT)
    witness = owned[4].commit(request.operation_id, patch)
    owned[3].apply(request.operation_id, witness)
    if not remove:
        owned[3].abandon(request.operation_id, committed=True, reason="caller_cancelled")
    called = []
    with pytest.raises(owned[5].BrokerAccountWorkspaceUnavailable):
        owned[4].with_current_authority(request.operation_id, lambda *_args: called.append(True))
    assert called == []
    assert owned[3].operation(request.operation_id).state is AccountOperationStage.COMMITTED


@pytest.mark.parametrize("persistent", [False, True])
def test_replace_result_reconciliation_requires_directory_persistence_barrier(owned, monkeypatch, persistent):
    request, patch, _ = planned(owned)
    from flinttrade_core import secure_file

    original = secure_file.fsync_parent_directory
    calls = []

    def flush(path):
        if path.name == "workspace.json":
            calls.append(path)
            if persistent or len(calls) == 1:
                raise OSError("synthetic persistence barrier failure")
        return original(path)

    monkeypatch.setattr(secure_file, "fsync_parent_directory", flush)
    if persistent:
        with pytest.raises(OSError):
            owned[4].commit(request.operation_id, patch)
        assert owned[3].head().epoch == 0
        assert owned[2].selector_state(request.selector).version.generation == 0
    else:
        witness = owned[4].commit(request.operation_id, patch)
        assert len(calls) == 2
        assert read_workspace_snapshot(owned[0]).as_dict()["_broker_account_store"] == witness.to_dict()


def test_private_writer_rejects_forged_duck_typed_workspace_owner(owned):
    from flinttrade_core import workspace_migrations

    class ForgedStore:
        def _require_workspace_capability(self, *args):
            pass

    before = (owned[0] / "workspace.json").read_bytes()
    with pytest.raises(ValueError):
        workspace_migrations._commit_update_locked(
            owned[0],
            read_workspace_snapshot(owned[0]).as_dict(),
            lambda config: config,
            _account_owner=(ForgedStore(), object(), object()),
            _account_stamp=lambda _actual: {"schema": 1},
        )
    assert (owned[0] / "workspace.json").read_bytes() == before


@pytest.mark.parametrize("field,value", [("schema", True), ("epoch", False), ("schema", 1.0)])
def test_generic_marker_protection_uses_exact_json_types(owned, field, value):
    owned[4].enrol()
    before = (owned[0] / "workspace.json").read_bytes()

    def mutate(config):
        config["_broker_account_store"][field] = value

    with pytest.raises(ValueError, match="broker_account_workspace_owned"):
        update_workspace_config(owned[0], mutate)
    assert (owned[0] / "workspace.json").read_bytes() == before


@pytest.mark.parametrize("target", ["cost_aware", "failover", "marker", "marker_version"])
def test_result_loss_reconciliation_requires_json_type_exact_full_config(owned, monkeypatch, target):
    import json

    request, patch, _ = planned(owned)
    from flinttrade_core import workspace_migrations

    original = workspace_migrations._atomic_write

    def foreign_after_install(*args, **kwargs):
        original(*args, **kwargs)
        path = owned[0] / "workspace.json"
        config = json.loads(path.read_text())
        if target in ("cost_aware", "failover"):
            config["brokers"][target]["enabled"] = 0
        elif target == "marker":
            config["_broker_account_store"]["schema"] = True
        else:
            version = config["_broker_account_store"]["commit_workspace"]
            version["generation"] = float(version["generation"])
        path.write_text(json.dumps(config))
        raise OSError("synthetic foreign result loss")

    monkeypatch.setattr(workspace_migrations, "_atomic_write", foreign_after_install)
    with pytest.raises(OSError, match="synthetic foreign result loss"):
        owned[4].commit(request.operation_id, patch)
    assert owned[3].operation(request.operation_id).state is AccountOperationStage.PLAN_READY
    assert owned[2].selector_state(request.selector).version.generation == 0


def test_attempt_phase_is_durable_before_locked_workspace_writer_dispatch(owned, monkeypatch):
    request, patch, _ = planned(owned)
    from flinttrade_core import workspace_migrations

    original = workspace_migrations._atomic_write

    def verify_before_write(*args, **kwargs):
        operation = owned[3].operation(request.operation_id)
        assert hasattr(operation, "workspace_attempted"), "the CAS was dispatched without durable attempt evidence"
        assert operation.workspace_attempted and not operation.workspace_conflicted
        return original(*args, **kwargs)

    monkeypatch.setattr(workspace_migrations, "_atomic_write", verify_before_write)
    witness = owned[4].commit(request.operation_id, patch)
    assert witness.operation_id == request.operation_id
