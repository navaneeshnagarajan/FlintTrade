"""Real, disposable vault ledger admission, migration, and crash evidence."""

import importlib
import importlib.util
import pickle
import shutil
import sqlite3
from contextlib import closing
from dataclasses import replace
from uuid import uuid4

import pytest

from flinttrade_core.backend_instance import BackendLeaseUnavailable, acquire_backend_instance_lease
from flinttrade_core.broker_identity import INT64_MAX, BrokerSelector
from flinttrade_core.secure_file import harden_directory
from flinttrade_core.workspace_migrations import (
    BrokerWorkspaceVersion,
    WorkspaceVersion,
    default_workspace_config,
    read_workspace_snapshot,
    write_workspace_config,
)
from flinttrade_gateway import credentials as vault


def modules():
    name = "flinttrade_gateway.account_transaction_store"
    assert importlib.util.find_spec(name) is not None, "durable account transaction store is missing"
    return importlib.import_module("flinttrade_core.account_lifecycle_contracts"), importlib.import_module(name)


@pytest.fixture
def owned(tmp_path, monkeypatch):
    harden_directory(tmp_path)
    monkeypatch.setenv("FLINTTRADE_WORKSPACE_DIR", str(tmp_path))
    write_workspace_config(tmp_path, default_workspace_config(), expected_version=None)
    lease = acquire_backend_instance_lease()
    credentials = vault.CredentialStore(tmp_path / "vault.db", "synthetic-password")
    yield tmp_path, lease, credentials
    credentials.close()
    lease.release()


def enrolled(owned):
    c, m = modules()
    path, lease, credentials = owned
    store = m.AccountTransactionStore(credentials, workspace_path=path, backend_proof=lease.proof)
    original = read_workspace_snapshot(path)
    intent = store.prepare_enrolment(original)
    witness = c.BrokerAccountWitness(
        schema=1,
        workspace_instance=intent.workspace_instance,
        vault_incarnation=intent.vault_incarnation,
        operation_id=intent.operation_id,
        epoch=0,
        before_digest=intent.before_digest,
        after_digest=intent.before_digest,
        commit_workspace=WorkspaceVersion(intent.workspace_instance, original.version.generation + 1),
        commit_broker_workspace=intent.expected_broker_workspace,
    )
    store.complete_enrolment(witness)
    return c, m, store, witness


def request(owned, c, head, **changes):
    selector = changes.pop("selector", BrokerSelector("dhan", "Synthetic"))
    values = dict(
        operation_id=uuid4(),
        kind=c.AccountMutationKind.CONNECT,
        selector=selector,
        actor=c.AccountActorContext("synthetic-user", "session:" + "a" * 64),
        expected_workspace=head.commit_workspace,
        expected_broker_workspace=head.commit_broker_workspace,
        expected_credential=owned[2].selector_state(selector).version,
        broker=selector.adapter_id,
        label="Synthetic",
        credentials={"token": "PRIVATE-admission"},
    )
    values.update(changes)
    return c.AccountMutationRequest(**values)


def plan(store, req, head, c, *, remove=False, attempt_workspace=True):
    if not remove:
        store.mark_authentication_started(req.operation_id)
    store.stage_plan(
        req.operation_id,
        replay_credentials=None if remove else {"token": "PRIVATE-replay"},
        read_only=None if remove else False,
        before_digest=head.after_digest,
        after_digest="b" * 64,
    )
    if attempt_workspace:
        store.mark_workspace_attempted(req.operation_id)
    return c.BrokerAccountWitness(
        schema=1,
        workspace_instance=head.workspace_instance,
        vault_incarnation=head.vault_incarnation,
        operation_id=req.operation_id,
        epoch=head.epoch + 1,
        before_digest=head.after_digest,
        after_digest="b" * 64,
        commit_workspace=WorkspaceVersion(head.workspace_instance, head.commit_workspace.generation + 1),
        commit_broker_workspace=BrokerWorkspaceVersion(
            head.workspace_instance, head.commit_broker_workspace.generation + 1
        ),
    )


def maximum_width_request(owned, c, head):
    return request(
        owned,
        c,
        head,
        selector=BrokerSelector("d" * 64, "A" * 128),
        actor=c.AccountActorContext("a" * 256, "session:" + "a" * 64),
        label="\U0001f600" * 256,
        credentials={"token": ""},
        data_roles=("ticks", "historical", "option_chains", "quote", "global_indices"),
    )


def maximum_committed_body(c, m, req):
    workspace = WorkspaceVersion(req.expected_workspace.instance_id, INT64_MAX)
    broker_workspace = BrokerWorkspaceVersion(req.expected_workspace.instance_id, INT64_MAX)
    witness = c.BrokerAccountWitness(
        1,
        req.expected_workspace.instance_id,
        req.expected_credential.vault_incarnation,
        req.operation_id,
        INT64_MAX,
        "a" * 64,
        "b" * 64,
        workspace,
        broker_workspace,
    )
    receipt = c.AccountMutationReceipt(
        req.operation_id,
        req.selector,
        req.kind,
        c.AccountOperationStage.COMMITTED,
        None,
        replace(req.expected_credential, generation=INT64_MAX),
        workspace,
        broker_workspace,
    )
    return {
        "identity": c._request_dict(req, private=False),
        "stage": "committed",
        "witness": witness.to_dict(),
        "receipt": m._receipt_dict(receipt),
        "abandoned": True,
        "abandonment_committed": True,
        "abandonment_reason": "r" * 64,
        "before_digest": "a" * 64,
        "after_digest": "b" * 64,
        "workspace_attempted": False,
        "workspace_conflicted": False,
    }


@pytest.mark.parametrize(
    "roles", [("quotes",), tuple("r" + str(index).zfill(4) + "a" * 56 for index in range(1008))]
)
def test_unsupported_roles_refuse_before_claim_or_authentication(owned, roles):
    c, _, store, head = enrolled(owned)
    operation_id = uuid4()
    with pytest.raises(c.AccountContractError):
        store.admit(request(owned, c, head, operation_id=operation_id, data_roles=roles))
    assert store.active_operation(store.owner_capability(owned[1].proof)) is None
    with closing(sqlite3.connect(owned[0] / "vault.db")) as db:
        assert db.execute("SELECT count(*) FROM account_operations").fetchone()[0] == 0
    with pytest.raises(vault.CredentialError):
        store.mark_authentication_started(operation_id)


def test_admission_reserves_maximum_terminal_envelope_before_claim(owned, monkeypatch):
    c, m, store, head = enrolled(owned)
    req = maximum_width_request(owned, c, head)
    # Shrink only the codec in this test so a valid bounded identity can expose
    # a missing preflight, without bypassing supported-role validation.
    limit = len(c.canonical_account_json(maximum_committed_body(c, m, req)).encode("utf-8")) - 1
    assert len(c.canonical_account_json(c._request_dict(req)).encode("utf-8")) < limit
    monkeypatch.setattr(c, "ACCOUNT_JSON_MAX_BYTES", limit)
    with pytest.raises((c.AccountContractError, vault.CredentialError)):
        store.admit(req)
    assert store.active_operation(store.owner_capability(owned[1].proof)) is None
    with closing(sqlite3.connect(owned[0] / "vault.db")) as db:
        assert db.execute("SELECT count(*) FROM account_operations").fetchone()[0] == 0
    with pytest.raises(vault.CredentialError):
        store.mark_authentication_started(req.operation_id)


def maximum_width_head(owned, c, store, head):
    # Retain a real signed operation before using a synthetic boundary anchor.
    prior = request(owned, c, head, kind=c.AccountMutationKind.REMOVE, credentials=None)
    store.admit(prior)
    witness = plan(store, prior, head, c, remove=True)
    store.apply(prior.operation_id, witness)
    store.release_claim(prior.operation_id)
    maximum = replace(
        witness,
        epoch=INT64_MAX - 1,
        commit_workspace=WorkspaceVersion(head.workspace_instance, INT64_MAX - 1),
        commit_broker_workspace=BrokerWorkspaceVersion(head.workspace_instance, INT64_MAX - 1),
    )
    with store._transaction(write=True) as db:
        row = store._row(db, prior.operation_id)
        body = c.parse_account_json(row["body"])
        body["witness"] = maximum.to_dict()
        body["receipt"]["commit_workspace"] = maximum.to_dict()["commit_workspace"]
        body["receipt"]["commit_broker_workspace"] = maximum.to_dict()["commit_broker_workspace"]
        # This signed boundary fixture changes receipt counters atomically.
        # Production transitions never rewrite an existing terminal receipt.
        db.execute("DELETE FROM account_audit_outbox WHERE operation_id=?", (str(prior.operation_id),))
        store._save(db, row, body)
        anchor = store._read_head(db)
        anchor["witness"] = maximum.to_dict()
        store._write_head(db, anchor)
    return maximum


@pytest.mark.parametrize("disposition", ["apply", "rejected", "authentication_unknown", "blocked", "abandon_before"])
def test_boundary_private_input_retains_terminal_receipts_and_abandonment(owned, disposition):
    c, m, store, head = enrolled(owned)
    head = maximum_width_head(owned, c, store, head)
    req = maximum_width_request(owned, c, head)
    with closing(sqlite3.connect(owned[0] / "vault.db")) as db:
        db.execute(
            "INSERT INTO credential_selector_versions VALUES(?,?,?,0,'managed')",
            (req.selector.adapter_id, req.selector.account_id, INT64_MAX - 1),
        )
        db.commit()
    req = replace(req, expected_credential=owned[2].selector_state(req.selector).version)
    spare = c.ACCOUNT_JSON_MAX_BYTES - len(c.canonical_account_json(c._request_dict(req)).encode("utf-8"))
    req = replace(req, credentials={"token": "x" * spare})
    assert c.ACCOUNT_JSON_MAX_BYTES == 65_536
    assert len(c.canonical_account_json(c._request_dict(req)).encode("utf-8")) == 65_536
    with pytest.raises(c.AccountContractError):
        replace(req, credentials={"token": "x" * (spare + 1)})
    store.admit(req)
    reason = "r" * 64
    if disposition == "apply":
        store.mark_authentication_started(req.operation_id)
        replay = {"replay_credentials": {"token": ""}, "read_only": False}
        remaining = 65_536 - len(c.canonical_account_json(replay).encode("utf-8"))
        replay["replay_credentials"]["token"] = "y" * remaining
        assert len(c.canonical_account_json(replay).encode("utf-8")) == 65_536
        store.stage_plan(
            req.operation_id,
            replay_credentials=replay["replay_credentials"],
            read_only=False,
            before_digest=head.after_digest,
            after_digest="c" * 64,
        )
        witness = c.BrokerAccountWitness(
            1,
            head.workspace_instance,
            head.vault_incarnation,
            req.operation_id,
            INT64_MAX,
            head.after_digest,
            "c" * 64,
            WorkspaceVersion(head.workspace_instance, INT64_MAX),
            BrokerWorkspaceVersion(head.workspace_instance, INT64_MAX),
        )
        store.mark_workspace_attempted(req.operation_id)
        store.abandon(req.operation_id, committed=True, reason=reason)
        receipt = store.apply(req.operation_id, witness)
        assert receipt.credential_version.generation == INT64_MAX
        assert store.apply(req.operation_id, witness) == receipt
        assert owned[2].retrieve_credentials(req.selector) == replay["replay_credentials"]
        store.abandon(req.operation_id, committed=True, reason=reason)
    else:
        store.mark_authentication_started(req.operation_id)
        store.abandon(req.operation_id, committed=False, reason=reason)
        state = (
            c.AccountOperationStage.REJECTED
            if disposition == "abandon_before"
            else c.AccountOperationStage(disposition)
        )
        receipt = store.settle(req.operation_id, state=state, reason=reason)
        assert store.settle(req.operation_id, state=state, reason=reason) == receipt
    reopened = m.AccountTransactionStore(owned[2], workspace_path=owned[0], backend_proof=owned[1].proof)
    retained = reopened.operation(req.operation_id)
    assert retained.receipt == receipt
    assert retained.abandoned and retained.abandonment_reason == reason
    assert reopened.admit(req).receipt == receipt
    with closing(sqlite3.connect(owned[0] / "vault.db")) as db:
        body = db.execute(
            "SELECT body FROM account_operations WHERE operation_id=?", (str(req.operation_id),)
        ).fetchone()[0]
        assert len(body.encode("utf-8")) <= 65_536


def test_schema_two_to_four_migration_preserves_all_original_cells(owned):
    path, _, credentials = owned
    selector = BrokerSelector("dhan", "Synthetic")
    version = credentials.put_credentials(
        selector, "dhan", "Synthetic", {"token": "old"}, expected=credentials.selector_state(selector).version
    )
    credentials.close()
    with closing(sqlite3.connect(path / "vault.db")) as db:
        # Reconstruct an authentic schema-2 source, retaining its exact rows.
        for (name,) in db.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name IN ('account_operations','account_store_head','account_store_key','account_audit_outbox')"
        ).fetchall():
            db.execute(f'DROP TABLE "{name}"')
        db.execute("DROP TABLE credential_vault_metadata")
        db.execute(vault._AUTHORITY_SCHEMA["credential_vault_metadata"])
        db.execute("INSERT INTO credential_vault_metadata VALUES(1,2,?)", (str(version.vault_incarnation),))
        db.execute("PRAGMA user_version=2")
        db.execute("UPDATE accounts SET is_primary=1")
        db.execute("INSERT INTO credential_selector_versions VALUES('dhan','Retired',41,0,'managed')")
        db.execute("INSERT INTO broker_selector_setup VALUES('dhan','Retired',0,NULL)")
        with closing(sqlite3.connect(":memory:")) as source:
            source.execute(vault._CREATE_TABLE_SQL)
            source.execute(
                "INSERT INTO accounts VALUES(?,?,?,?,?,?,?,?)",
                ("bad%", "dhan", "dhan", "dhan", b"0123456789abcdef", b"PRIVATE-opaque-cipher", 0, "original"),
            )
            raw = vault._encode_envelope(vault._raw_cells(source, "accounts", 1), None)
        db.execute(
            "INSERT INTO credential_quarantine VALUES(?,?,0,'accounts',1,1,?,?,?)",
            (
                str(uuid4()),
                str(version.vault_incarnation),
                "legacy_identity_invalid",
                "legacy_pre_workspace_authority",
                raw,
            ),
        )
        db.commit()
        before = {
            name: db.execute(f"SELECT * FROM {name}").fetchall()
            for name in ("accounts", "credential_selector_versions", "broker_selector_setup", "credential_quarantine")
        }
    reopened = vault.CredentialStore(path / "vault.db", "synthetic-password")
    try:
        with closing(sqlite3.connect(path / "vault.db")) as db:
            assert db.execute("PRAGMA user_version").fetchone()[0] == 4
            assert db.execute("SELECT schema_version,vault_incarnation FROM credential_vault_metadata").fetchone() == (
                4,
                str(version.vault_incarnation),
            )
            assert before == {name: db.execute(f"SELECT * FROM {name}").fetchall() for name in before}
        assert reopened.selector_state(selector).version == version
    finally:
        reopened.close()


def test_enrolment_is_stable_and_fences_legacy_writes(owned):
    c, m, store, head = enrolled(owned)
    assert store.head() == head
    store.complete_enrolment(head)
    selector = BrokerSelector("dhan", "Synthetic")
    with pytest.raises(vault.CredentialError):
        owned[2].put_credentials(
            selector, "dhan", "Synthetic", {"token": "old"}, expected=owned[2].selector_state(selector).version
        )
    reopened = m.AccountTransactionStore(owned[2], workspace_path=owned[0], backend_proof=owned[1].proof)
    assert reopened.head() == head
    with pytest.raises(vault.CredentialError):
        store.complete_enrolment(replace(head, operation_id=uuid4()))


def test_admission_is_encrypted_bound_and_exclusively_claimed(owned):
    c, m, store, head = enrolled(owned)
    req = request(owned, c, head)
    first = store.admit(req)
    assert first.state is c.AccountOperationStage.ADMITTED
    assert store.admit(req) == first
    assert "PRIVATE" not in repr(first)
    for changed in (
        replace(req, label="other"),
        replace(req, credentials={"token": "different"}),
        replace(req, actor=c.AccountActorContext("another", "session:" + "b" * 64)),
    ):
        with pytest.raises(vault.CredentialError):
            store.admit(changed)
    with pytest.raises(vault.CredentialError):
        store.admit(replace(req, operation_id=uuid4()))
    witness = plan(store, req, head, c)
    assert store.operation(req.operation_id).state is c.AccountOperationStage.PLAN_READY
    assert "PRIVATE" not in (owned[0] / "vault.db").read_bytes().decode(errors="ignore")
    cap = store.owner_capability(owned[1].proof)
    private = store.recovery_material(cap, req.operation_id)
    assert private.request.credentials["token"] == "PRIVATE-admission"
    assert private.replay_credentials["token"] == "PRIVATE-replay"
    assert "PRIVATE" not in repr(private)
    with pytest.raises(TypeError):
        pickle.dumps(private)
    with pytest.raises(vault.CredentialError):
        store.recovery_material(object(), req.operation_id)
    assert witness.epoch == 1


def test_apply_receipt_head_and_one_generation_are_atomic_and_replayable(owned):
    c, m, store, head = enrolled(owned)
    req = request(owned, c, head)
    store.admit(req)
    witness = plan(store, req, head, c)
    receipt = store.apply(req.operation_id, witness)
    assert receipt.state is c.AccountOperationStage.COMMITTED
    assert receipt.credential_version.generation == 1
    assert store.head() == witness
    assert owned[2].retrieve_credentials(req.selector) == {"token": "PRIVATE-replay"}
    assert store.apply(req.operation_id, witness) == receipt
    reopened = m.AccountTransactionStore(owned[2], workspace_path=owned[0], backend_proof=owned[1].proof)
    assert reopened.apply(req.operation_id, witness) == receipt
    assert reopened.admit(req).receipt == receipt
    assert owned[2].selector_state(req.selector).version.generation == 1
    assert reopened.recovery_material(reopened.owner_capability(owned[1].proof), req.operation_id).request is None
    with pytest.raises(vault.CredentialError):
        store.apply(req.operation_id, replace(witness, operation_id=uuid4()))
    store.release_claim(req.operation_id)
    next_req = request(owned, c, witness, kind=c.AccountMutationKind.REMOVE, credentials=None)
    assert store.admit(next_req).operation_id == next_req.operation_id


def test_remove_has_no_auth_plan_and_keeps_exact_tombstone(owned):
    selector = BrokerSelector("dhan", "Synthetic")
    owned[2].put_credentials(
        selector, "dhan", "Synthetic", {"token": "old"}, expected=owned[2].selector_state(selector).version
    )
    c, _, store, head = enrolled(owned)
    req = request(owned, c, head, kind=c.AccountMutationKind.REMOVE, credentials=None)
    store.admit(req)
    with pytest.raises(vault.CredentialError):
        store.mark_authentication_started(req.operation_id)
    witness = plan(store, req, head, c, remove=True)
    result = store.apply(req.operation_id, witness)
    assert result.credential_version.generation == 2
    assert not owned[2].selector_state(selector).present
    assert store.apply(req.operation_id, witness) == result


def test_authentication_unknown_and_abandonment_never_reopen(owned):
    c, _, store, head = enrolled(owned)
    req = request(owned, c, head)
    store.admit(req)
    store.mark_authentication_started(req.operation_id)
    store.abandon(req.operation_id, committed=False, reason="caller_cancelled")
    receipt = store.settle(
        req.operation_id, state=c.AccountOperationStage.AUTHENTICATION_UNKNOWN, reason="outcome_unknown"
    )
    assert store.operation(req.operation_id).abandoned
    assert store.settle(req.operation_id, state=receipt.state, reason=receipt.reason) == receipt
    with pytest.raises(vault.CredentialError):
        store.stage_plan(
            req.operation_id,
            replay_credentials={"token": "late"},
            read_only=False,
            before_digest=head.after_digest,
            after_digest="b" * 64,
        )
    with pytest.raises(vault.CredentialError):
        store.release_claim(req.operation_id)
    with pytest.raises(vault.CredentialError):
        store.settle(req.operation_id, state=c.AccountOperationStage.REJECTED, reason="changed")


def test_wrong_workspace_and_revoked_backend_refuse(owned):
    _, m = modules()
    with pytest.raises((ValueError, RuntimeError, vault.CredentialError)):
        m.AccountTransactionStore(owned[2], workspace_path=owned[0] / "other", backend_proof=owned[1].proof)
    _, _, store, _ = enrolled(owned)
    owned[1].proof.revoke()
    with pytest.raises((RuntimeError, vault.CredentialError)):
        store.head()


@pytest.mark.parametrize("damage", ["trigger", "index", "column", "replacement"])
def test_ledger_damage_and_replaced_vault_fail_closed(owned, damage):
    _, _, store, _ = enrolled(owned)
    path = owned[0] / "vault.db"
    if damage == "replacement":
        copy = path.with_suffix(".copy")
        shutil.copy2(path, copy)
        copy.replace(path)
    else:
        with closing(sqlite3.connect(path)) as db:
            if damage == "trigger":
                db.execute("CREATE TRIGGER unexpected AFTER UPDATE ON account_operations BEGIN SELECT 1; END")
            elif damage == "index":
                db.execute("CREATE INDEX unexpected ON account_operations(operation_id)")
            else:
                db.execute("ALTER TABLE account_operations ADD COLUMN unexpected TEXT")
            db.commit()
    with pytest.raises(vault.CredentialError):
        store.head()


def test_post_commit_exception_recovers_exact_receipt_without_extra_generation(owned, monkeypatch):
    c, m, store, head = enrolled(owned)
    req = request(owned, c, head)
    store.admit(req)
    witness = plan(store, req, head, c)
    original = owned[2]._validate_family
    reported = []

    def fail_after_commit():
        original()
        with closing(sqlite3.connect(owned[0] / "vault.db")) as db:
            row = db.execute(
                "SELECT body FROM account_operations WHERE operation_id=?", (str(req.operation_id),)
            ).fetchone()
        if row is not None and '"stage":"committed"' in row[0] and not reported:
            reported.append(True)
            raise vault.CredentialError

    monkeypatch.setattr(owned[2], "_validate_family", fail_after_commit)
    with pytest.raises(vault.CredentialError):
        store.apply(req.operation_id, witness)
    assert reported == [True]
    reopened = m.AccountTransactionStore(owned[2], workspace_path=owned[0], backend_proof=owned[1].proof)
    receipt = reopened.operation(req.operation_id).receipt
    assert receipt.state is c.AccountOperationStage.COMMITTED
    assert reopened.head() == witness
    assert reopened.apply(req.operation_id, witness) == receipt
    assert owned[2].selector_state(req.selector).version.generation == 1
    cap = reopened.owner_capability(owned[1].proof)
    assert len(reopened.pending_audit_events(cap)) == 1
    assert reopened.pending_audit_events(cap)[0].credential_generation == 1


def test_pre_commit_exception_rolls_back_credentials_head_and_receipt(owned, monkeypatch):
    c, _, store, head = enrolled(owned)
    req = request(owned, c, head)
    store.admit(req)
    witness = plan(store, req, head, c)
    original = owned[2]._bump

    def fail_before_commit(conn, selector):
        original(conn, selector)
        raise vault.CredentialError

    monkeypatch.setattr(owned[2], "_bump", fail_before_commit)
    with pytest.raises(vault.CredentialError):
        store.apply(req.operation_id, witness)
    assert owned[2].selector_state(req.selector).version.generation == 0
    assert store.head() == head
    assert store.operation(req.operation_id).state is c.AccountOperationStage.PLAN_READY
    assert store.pending_audit_events(store.owner_capability(owned[1].proof)) == ()
    monkeypatch.setattr(owned[2], "_bump", original)
    assert store.apply(req.operation_id, witness).credential_version.generation == 1


def test_post_witness_abandonment_preserves_forward_only_application(owned):
    c, _, store, head = enrolled(owned)
    req = request(owned, c, head)
    store.admit(req)
    witness = plan(store, req, head, c)
    store.abandon(req.operation_id, committed=True, reason="caller_cancelled")
    with pytest.raises(vault.CredentialError):
        store.settle(req.operation_id, state=c.AccountOperationStage.REJECTED, reason="cancelled")
    result = store.apply(req.operation_id, witness)
    assert result.state is c.AccountOperationStage.COMMITTED
    assert store.operation(req.operation_id).abandonment_committed
    with pytest.raises(vault.CredentialError):
        store.abandon(req.operation_id, committed=False, reason="caller_cancelled")


def test_capacity_refuses_new_ids_but_retains_terminal_replay(owned, monkeypatch):
    c, m, store, head = enrolled(owned)
    assert m.ACCOUNT_MAX_OPERATIONS == 10_000
    monkeypatch.setattr(m, "ACCOUNT_MAX_OPERATIONS", 1)
    req = request(owned, c, head, kind=c.AccountMutationKind.REMOVE, credentials=None)
    store.admit(req)
    witness = plan(store, req, head, c, remove=True)
    receipt = store.apply(req.operation_id, witness)
    store.release_claim(req.operation_id)
    with pytest.raises(vault.CredentialError):
        store.admit(request(owned, c, witness))
    assert store.admit(req).receipt == receipt
    assert store.operation(req.operation_id).receipt == receipt


def test_generation_exhaustion_refuses_before_admission(owned):
    selector = BrokerSelector("dhan", "Synthetic")
    owned[2].put_credentials(
        selector, "dhan", "Synthetic", {"token": "old"}, expected=owned[2].selector_state(selector).version
    )
    with closing(sqlite3.connect(owned[0] / "vault.db")) as db:
        db.execute("UPDATE credential_selector_versions SET generation=?", (2**63 - 1,))
        db.commit()
    c, _, store, head = enrolled(owned)
    req = request(owned, c, head)
    with pytest.raises(vault.CredentialError):
        store.admit(req)
    with closing(sqlite3.connect(owned[0] / "vault.db")) as db:
        assert db.execute("SELECT count(*) FROM account_operations").fetchone()[0] == 0
    assert owned[2].selector_state(selector).version.generation == 2**63 - 1


@pytest.mark.parametrize("damage", ["request_mac", "private_cipher", "head", "delete", "key"])
def test_authenticated_ledger_detects_tampering_without_echo(owned, damage):
    c, m, store, head = enrolled(owned)
    req = request(owned, c, head)
    store.admit(req)
    with closing(sqlite3.connect(owned[0] / "vault.db")) as db:
        statements = {
            "request_mac": "UPDATE account_operations SET request_mac='" + "a" * 64 + "'",
            "private_cipher": "UPDATE account_operations SET private_cipher=X'50524956415445'",
            "head": "UPDATE account_store_head SET body='PRIVATE-corrupt'",
            "delete": "DELETE FROM account_operations",
            "key": "UPDATE account_store_key SET encrypted_creds=X'50524956415445'",
        }
        db.execute(statements[damage])
        db.commit()
    for action in (
        store.head,
        lambda: m.AccountTransactionStore(owned[2], workspace_path=owned[0], backend_proof=owned[1].proof),
    ):
        with pytest.raises(vault.CredentialError) as caught:
            action()
        assert "PRIVATE" not in str(caught.value)


def test_read_only_demotion_changes_only_exact_target_and_one_generation(owned):
    a, b = BrokerSelector("dhan", "Synthetic"), BrokerSelector("dhan", "Other")
    for selector in (a, b):
        owned[2].put_credentials(
            selector, "dhan", "Synthetic", {"token": "old"}, expected=owned[2].selector_state(selector).version
        )
    owned[2].apply_primary_projection(owned[2].snapshot_primary_projection(a, True))
    before_a, before_b = owned[2].selector_state(a).version, owned[2].selector_state(b).version
    c, _, store, head = enrolled(owned)
    req = request(owned, c, head, kind=c.AccountMutationKind.ROTATE)
    store.admit(req)
    store.mark_authentication_started(req.operation_id)
    store.stage_plan(
        req.operation_id,
        replay_credentials={"token": "new"},
        read_only=True,
        before_digest=head.after_digest,
        after_digest=head.after_digest,
    )
    witness = replace(
        head,
        operation_id=req.operation_id,
        epoch=1,
        commit_workspace=WorkspaceVersion(head.workspace_instance, head.commit_workspace.generation + 1),
    )
    store.mark_workspace_attempted(req.operation_id)
    receipt = store.apply(req.operation_id, witness)
    assert receipt.credential_version.generation == before_a.generation + 1
    assert not owned[2].account_for_selector(a).is_primary
    assert owned[2].selector_state(b).version == before_b
    assert owned[2].retrieve_credentials(b) == {"token": "old"}


def test_extra_account_index_semantics_are_rejected(owned):
    path = owned[0] / "vault.db"
    owned[2].close()
    with closing(sqlite3.connect(path)) as db:
        db.execute("DROP INDEX idx_accounts_account_id")
        db.execute("CREATE INDEX idx_accounts_account_id ON accounts(account_id DESC)")
        db.commit()
    with pytest.raises(vault.CredentialError):
        vault.CredentialStore(path, "synthetic-password")


def test_owner_can_discover_retained_active_operation_for_recovery(owned):
    c, _, store, head = enrolled(owned)
    cap = store.owner_capability(owned[1].proof)
    assert hasattr(store, "active_operation"), "restart recovery cannot discover the durable claim"
    assert store.active_operation(cap) is None
    req = request(owned, c, head, kind=c.AccountMutationKind.REMOVE, credentials=None)
    snapshot = store.admit(req)
    assert store.active_operation(cap) == snapshot
    with pytest.raises(vault.CredentialError):
        store.active_operation(object())
    witness = plan(store, req, head, c, remove=True)
    receipt = store.apply(req.operation_id, witness)
    assert store.active_operation(cap).receipt == receipt
    store.release_claim(req.operation_id)
    assert store.active_operation(cap) is None


def test_workspace_counter_exhaustion_refuses_before_admission(owned):
    c, _, store, head = enrolled(owned)
    req = request(owned, c, head, expected_workspace=WorkspaceVersion(head.workspace_instance, 2**63 - 1))
    with pytest.raises(vault.CredentialError):
        store.admit(req)
    cap = store.owner_capability(owned[1].proof)
    assert store.active_operation(cap) is None


def test_enrolment_intent_has_no_invented_commit_and_pending_state_is_recoverable(owned):
    c, m = modules()
    store = m.AccountTransactionStore(owned[2], workspace_path=owned[0], backend_proof=owned[1].proof)
    workspace = read_workspace_snapshot(owned[0])
    intent = store.prepare_enrolment(workspace)
    assert intent.expected_workspace == workspace.version
    assert not hasattr(intent, "commit_workspace")
    assert store.prepare_enrolment(workspace) == intent
    assert store.head() is None
    reopened = m.AccountTransactionStore(owned[2], workspace_path=owned[0], backend_proof=owned[1].proof)
    assert reopened.prepare_enrolment(workspace) == intent
    assert reopened.active_operation(reopened.owner_capability(owned[1].proof)) is None
    selector = BrokerSelector("dhan", "Synthetic")
    with pytest.raises(vault.CredentialError):
        owned[2].remove_selector(selector, expected=owned[2].selector_state(selector).version)


def test_remove_refuses_any_provider_candidate(owned):
    c, _, store, head = enrolled(owned)
    req = request(owned, c, head, kind=c.AccountMutationKind.REMOVE, credentials=None)
    store.admit(req)
    for credentials, read_only in (({"token": "PRIVATE"}, None), (None, False)):
        with pytest.raises(vault.CredentialError):
            store.stage_plan(
                req.operation_id,
                replay_credentials=credentials,
                read_only=read_only,
                before_digest=head.after_digest,
                after_digest=head.after_digest,
            )
    assert store.operation(req.operation_id).state is c.AccountOperationStage.ADMITTED


def test_foreign_witness_cannot_apply_or_clear_original_plan(owned):
    c, _, store, head = enrolled(owned)
    req = request(owned, c, head)
    store.admit(req)
    witness = plan(store, req, head, c)
    for foreign in (
        replace(witness, operation_id=uuid4()),
        replace(witness, vault_incarnation=uuid4()),
        replace(witness, epoch=2),
        replace(witness, after_digest="c" * 64),
    ):
        with pytest.raises(vault.CredentialError):
            store.apply(req.operation_id, foreign)
    assert store.operation(req.operation_id).state is c.AccountOperationStage.PLAN_READY
    assert owned[2].selector_state(req.selector).version.generation == 0
    assert store.apply(req.operation_id, witness).credential_version.generation == 1


def test_reopened_vault_keeps_enrolment_fence_and_opaque_capabilities_local(owned):
    c, m, store, head = enrolled(owned)
    req = request(owned, c, head)
    store.admit(req)
    other_credentials = vault.CredentialStore(owned[0] / "vault.db", "synthetic-password")
    try:
        other = m.AccountTransactionStore(other_credentials, workspace_path=owned[0], backend_proof=owned[1].proof)
        assert other.active_operation(other.owner_capability(owned[1].proof)).operation_id == req.operation_id
        with pytest.raises(vault.CredentialError):
            other.recovery_material(store.owner_capability(owned[1].proof), req.operation_id)
        with pytest.raises(vault.CredentialError):
            other_credentials.remove_selector(req.selector, expected=req.expected_credential)
    finally:
        other_credentials.close()


def test_epoch_exhaustion_retains_replay_and_refuses_a_successor(owned):
    c, _, store, head = enrolled(owned)
    req = request(owned, c, head, kind=c.AccountMutationKind.REMOVE, credentials=None)
    store.admit(req)
    witness = plan(store, req, head, c, remove=True)
    receipt = store.apply(req.operation_id, witness)
    store.release_claim(req.operation_id)
    # A synthetic signed boundary fixture avoids billions of provider-free commits.
    maximum = replace(witness, epoch=2**63 - 1)
    with store._transaction(write=True) as db:
        row = store._row(db, req.operation_id)
        body = c.parse_account_json(row["body"])
        body["witness"] = maximum.to_dict()
        store._save(db, row, body)
        anchor = store._read_head(db)
        anchor["witness"] = maximum.to_dict()
        store._write_head(db, anchor)
    assert store.head() == maximum
    with pytest.raises(vault.CredentialError):
        store.admit(request(owned, c, maximum))
    assert store.admit(req).receipt == receipt


def test_failed_schema_two_migration_preserves_entire_database(owned, monkeypatch):
    path, _, credentials = owned
    credentials.close()
    with closing(sqlite3.connect(path / "vault.db")) as db:
        incarnation = db.execute("SELECT vault_incarnation FROM credential_vault_metadata").fetchone()[0]
        for name in ("account_operations", "account_store_head", "account_store_key", "account_audit_outbox", "credential_vault_metadata"):
            db.execute(f"DROP TABLE {name}")
        db.execute(vault._AUTHORITY_SCHEMA["credential_vault_metadata"])
        db.execute("INSERT INTO credential_vault_metadata VALUES(1,2,?)", (incarnation,))
        db.execute("PRAGMA user_version=2")
        db.commit()
        before = tuple(db.iterdump())

    def refuse_key(*args, **kwargs):
        raise RuntimeError("PRIVATE-key-failure")

    monkeypatch.setattr(vault.CredentialStore, "_encrypt", refuse_key)
    with pytest.raises(vault.CredentialError) as caught:
        vault.CredentialStore(path / "vault.db", "synthetic-password")
    assert "PRIVATE" not in str(caught.value)
    with closing(sqlite3.connect(path / "vault.db")) as db:
        assert tuple(db.iterdump()) == before


def test_missing_enrolled_genesis_head_cannot_reenable_legacy_mutation(owned):
    _, m, store, _ = enrolled(owned)
    with closing(sqlite3.connect(owned[0] / "vault.db")) as db:
        db.execute("DELETE FROM account_store_head")
        db.commit()
    selector = BrokerSelector("dhan", "Synthetic")
    with pytest.raises(vault.CredentialError):
        owned[2].remove_selector(selector, expected=owned[2].selector_state(selector).version)
    with pytest.raises(vault.CredentialError):
        store.head()
    with pytest.raises(vault.CredentialError):
        m.AccountTransactionStore(owned[2], workspace_path=owned[0], backend_proof=owned[1].proof)


def test_workspace_phase_records_are_monotonic_and_protect_private_staging(owned):
    c, m, store, head = enrolled(owned)
    req = request(owned, c, head)
    store.admit(req)
    assert callable(getattr(store, "mark_workspace_attempted", None)), "workspace attempt evidence is missing"
    assert callable(getattr(store, "mark_workspace_conflicted", None)), "workspace conflict evidence is missing"
    with pytest.raises(vault.CredentialError):
        store.mark_workspace_attempted(req.operation_id)
    with pytest.raises(vault.CredentialError):
        store.mark_workspace_conflicted(req.operation_id)
    store.mark_authentication_started(req.operation_id)
    store.stage_plan(req.operation_id, replay_credentials={"token": "PRIVATE-replay"}, read_only=False,
                     before_digest=head.after_digest, after_digest="b" * 64)
    operation = store.operation(req.operation_id)
    assert not operation.workspace_attempted and not operation.workspace_conflicted
    store.mark_workspace_attempted(req.operation_id)
    store.mark_workspace_attempted(req.operation_id)
    assert store.operation(req.operation_id).workspace_attempted
    for state in (c.AccountOperationStage.REJECTED, c.AccountOperationStage.BLOCKED, c.AccountOperationStage.AUTHENTICATION_UNKNOWN):
        with pytest.raises(vault.CredentialError):
            store.settle(req.operation_id, state=state, reason="must_retain")
    with pytest.raises(vault.CredentialError):
        store.abandon(req.operation_id, committed=False, reason="caller_cancelled")
    store.mark_workspace_conflicted(req.operation_id)
    store.mark_workspace_conflicted(req.operation_id)
    operation = store.operation(req.operation_id)
    assert operation.state is c.AccountOperationStage.PLAN_READY and operation.workspace_conflicted
    with pytest.raises(vault.CredentialError):
        store.mark_workspace_attempted(req.operation_id)
    cap = store.owner_capability(owned[1].proof)
    assert store.recovery_material(cap, req.operation_id).request is not None
    reopened = m.AccountTransactionStore(owned[2], workspace_path=owned[0], backend_proof=owned[1].proof)
    assert reopened.operation(req.operation_id) == operation
    witness = c.BrokerAccountWitness(
        1, head.workspace_instance, head.vault_incarnation, req.operation_id, 1, head.after_digest, "b" * 64,
        WorkspaceVersion(head.workspace_instance, head.commit_workspace.generation + 1),
        BrokerWorkspaceVersion(head.workspace_instance, head.commit_broker_workspace.generation + 1),
    )
    store.abandon(req.operation_id, committed=True, reason="caller_cancelled")
    receipt = store.apply(req.operation_id, witness)
    assert receipt.state is c.AccountOperationStage.COMMITTED
    assert store.operation(req.operation_id).workspace_conflicted
    assert store.recovery_material(cap, req.operation_id).request is None


def test_vault_apply_requires_durable_workspace_attempt_evidence(owned):
    c, _, store, head = enrolled(owned)
    req = request(owned, c, head)
    store.admit(req)
    witness = plan(store, req, head, c, attempt_workspace=False)
    with pytest.raises(vault.CredentialError):
        store.apply(req.operation_id, witness)
    assert owned[2].selector_state(req.selector).version.generation == 0


def _database_row(owned, table, operation_id):
    with closing(sqlite3.connect(owned[0] / "vault.db")) as db:
        db.row_factory = sqlite3.Row
        return dict(db.execute(f"SELECT * FROM {table} WHERE operation_id=?", (str(operation_id),)).fetchone())


def _restore_database_row(owned, table, row):
    with closing(sqlite3.connect(owned[0] / "vault.db")) as db:
        names = tuple(row)
        assignments = ",".join(f"{name}=?" for name in names if name != "operation_id")
        db.execute(
            f"UPDATE {table} SET {assignments} WHERE operation_id=?",
            (*[row[name] for name in names if name != "operation_id"], row["operation_id"]),
        )
        db.commit()


def test_authenticated_admitted_row_rewind_cannot_dispatch_authentication_again(owned):
    c, m, store, head = enrolled(owned)
    req = request(owned, c, head)
    store.admit(req)
    old = _database_row(owned, "account_operations", req.operation_id)
    store.mark_authentication_started(req.operation_id)
    store.settle(req.operation_id, state=c.AccountOperationStage.AUTHENTICATION_UNKNOWN, reason="auth_interrupted")
    _restore_database_row(owned, "account_operations", old)
    with pytest.raises(m.AccountTransactionError):
        store.operation(req.operation_id)
    with pytest.raises(m.AccountTransactionError):
        store.mark_authentication_started(req.operation_id)
    with pytest.raises(m.AccountTransactionError):
        m.AccountTransactionStore(owned[2], workspace_path=owned[0], backend_proof=owned[1].proof)


def test_authenticated_released_receipt_rewind_cannot_erase_conflict_fence(owned):
    c, m, store, head = enrolled(owned)
    req = request(owned, c, head)
    store.admit(req)
    witness = plan(store, req, head, c)
    store.apply(req.operation_id, witness)
    store.release_claim(req.operation_id)
    old = _database_row(owned, "account_operations", req.operation_id)
    store.mark_workspace_conflicted(req.operation_id)
    _restore_database_row(owned, "account_operations", old)
    with pytest.raises(m.AccountTransactionError):
        store.head()


def test_authenticated_pending_outbox_rewind_cannot_erase_acknowledgement(owned):
    c, m, store, head = enrolled(owned)
    req = request(owned, c, head)
    store.admit(req)
    store.settle(req.operation_id, state=c.AccountOperationStage.REJECTED, reason="synthetic_rejection")
    cap = store.owner_capability(owned[1].proof)
    old = _database_row(owned, "account_audit_outbox", req.operation_id)
    assert store.export_audit_events(cap, lambda event: event.event_id) == 1
    _restore_database_row(owned, "account_audit_outbox", old)
    with pytest.raises(m.AccountTransactionError):
        store.pending_audit_events(cap)


@pytest.mark.parametrize("state", ["committed", "rejected", "authentication_unknown", "blocked"])
def test_terminal_audit_is_stable_vault_bound_redacted_and_provider_free(owned, state):
    c, m, store, head = enrolled(owned)
    req = request(owned, c, head)
    store.admit(req)
    cap = store.owner_capability(owned[1].proof)
    assert store.pending_audit_events(cap) == ()
    if state == "committed":
        witness = plan(store, req, head, c)
        receipt = store.apply(req.operation_id, witness)
        assert store.apply(req.operation_id, witness) == receipt
    else:
        if state == "authentication_unknown":
            store.mark_authentication_started(req.operation_id)
        receipt = store.settle(req.operation_id, state=c.AccountOperationStage(state), reason="synthetic_private_reason")
        assert store.settle(req.operation_id, state=receipt.state, reason=receipt.reason) == receipt
    events = store.pending_audit_events(cap)
    assert type(events) is tuple and len(events) == 1
    event = events[0]
    assert event.event_id.version == 4 and event.event_id != req.operation_id
    assert event.state is receipt.state and event.kind is req.kind
    assert event.credential_generation == (1 if state == "committed" else None)
    encoded = c.canonical_account_json(event.to_dict())
    for secret in (
        str(req.operation_id), str(head.vault_incarnation), req.actor.actor, req.actor.session_binding,
        req.selector.adapter_id, req.selector.account_id, req.label, "PRIVATE-admission", "PRIVATE-replay",
        "synthetic_private_reason",
    ):
        assert secret not in encoded
    from dataclasses import FrozenInstanceError
    with pytest.raises(FrozenInstanceError):
        event.actor_ref = "0" * 64
    reopened = m.AccountTransactionStore(owned[2], workspace_path=owned[0], backend_proof=owned[1].proof)
    other_cap = reopened.owner_capability(owned[1].proof)
    assert reopened.pending_audit_events(other_cap) == events
    version = owned[2].selector_state(req.selector).version
    assert reopened.export_audit_events(other_cap, lambda value: value.event_id) == 1
    assert reopened.export_audit_events(other_cap, lambda value: pytest.fail("delivered event replayed")) == 0
    assert owned[2].selector_state(req.selector).version == version
    assert reopened.operation(req.operation_id).receipt == receipt


@pytest.mark.parametrize("ack", ["missing", "wrong", "string", "version_one", "raise"])
def test_unverified_or_failed_audit_delivery_keeps_exact_pending_event(owned, ack):
    from uuid import uuid1
    c, _, store, head = enrolled(owned)
    req = request(owned, c, head)
    store.admit(req)
    store.settle(req.operation_id, state=c.AccountOperationStage.REJECTED, reason="synthetic_rejection")
    cap = store.owner_capability(owned[1].proof)
    before = store.pending_audit_events(cap)

    def sink(event):
        assert event == before[0]
        if ack == "raise":
            raise RuntimeError("PRIVATE-sink-secret")
        return {"missing": None, "wrong": uuid4(), "string": str(event.event_id), "version_one": uuid1()}[ack]

    assert store.export_audit_events(cap, sink) == 0
    assert store.pending_audit_events(cap) == before
    assert store.export_audit_events(cap, lambda event: event.event_id) == 1


def test_sink_runs_outside_sqlite_locks_and_ack_does_not_release_claim(owned):
    c, _, store, head = enrolled(owned)
    req = request(owned, c, head)
    store.admit(req)
    store.settle(req.operation_id, state=c.AccountOperationStage.BLOCKED, reason="synthetic_blocked")
    cap = store.owner_capability(owned[1].proof)

    def sink(event):
        # A distinct connection can acquire the write reservation immediately.
        # A callback under the ledger transaction would fail this probe.
        with closing(sqlite3.connect(owned[0] / "vault.db", timeout=0.01)) as db:
            db.execute("BEGIN IMMEDIATE")
            db.rollback()
        assert store.pending_audit_events(cap) == (event,)
        return event.event_id

    assert store.export_audit_events(cap, sink) == 1
    assert store.active_operation(cap).operation_id == req.operation_id
    assert owned[2].selector_state(req.selector).version.generation == 0


def test_audit_ack_revalidates_exact_operation_source_after_unlocked_sink(owned):
    c, m, store, head = enrolled(owned)
    req = request(owned, c, head)
    store.admit(req)
    store.apply(req.operation_id, plan(store, req, head, c))
    cap = store.owner_capability(owned[1].proof)
    events = store.pending_audit_events(cap)

    def sink(event):
        store.mark_workspace_conflicted(req.operation_id)
        return event.event_id

    with pytest.raises(m.AccountTransactionError):
        store.export_audit_events(cap, sink)
    assert store.pending_audit_events(cap) == events
    assert store.export_audit_events(cap, lambda event: event.event_id) == 1


def test_audit_ack_revalidates_live_owner_after_unlocked_sink(owned):
    c, _, store, head = enrolled(owned)
    req = request(owned, c, head)
    store.admit(req)
    store.settle(req.operation_id, state=c.AccountOperationStage.REJECTED, reason="synthetic_rejection")
    cap = store.owner_capability(owned[1].proof)

    def sink(event):
        owned[1].release()
        return event.event_id

    with pytest.raises(BackendLeaseUnavailable):
        store.export_audit_events(cap, sink)
    assert _database_row(owned, "account_audit_outbox", req.operation_id)["delivered"] == 0


@pytest.mark.parametrize("limit", [0, -1, True, 1.0, 10_001])
def test_audit_limits_and_capabilities_cannot_bypass_owner_validation(owned, limit):
    _, m, store, _ = enrolled(owned)
    cap = store.owner_capability(owned[1].proof)
    with pytest.raises(m.AccountTransactionError):
        store.pending_audit_events(cap, limit)
    with pytest.raises(m.AccountTransactionError):
        store.pending_audit_events(object())
    with pytest.raises(m.AccountTransactionError):
        store.export_audit_events(object(), lambda event: event.event_id)


@pytest.mark.parametrize("state", ["admitted", "committed", "rejected", "authentication_unknown", "blocked"])
def test_schema_three_migration_authenticates_and_backfills_terminal_receipts_only(owned, state):
    c, m, store, head = enrolled(owned)
    req = request(owned, c, head)
    store.admit(req)
    if state == "committed":
        store.apply(req.operation_id, plan(store, req, head, c))
    elif state != "admitted":
        if state == "authentication_unknown":
            store.mark_authentication_started(req.operation_id)
        store.settle(req.operation_id, state=c.AccountOperationStage(state), reason="synthetic_migration")
    expected_operation = store.operation(req.operation_id)
    expected_events = store.pending_audit_events(store.owner_capability(owned[1].proof))
    path, lease, credentials = owned
    credentials.close()
    with closing(sqlite3.connect(path / "vault.db")) as db:
        db.row_factory = sqlite3.Row
        incarnation = db.execute("SELECT vault_incarnation FROM credential_vault_metadata").fetchone()[0]
        db.execute("DROP TABLE account_audit_outbox")
        db.execute("DROP TABLE credential_vault_metadata")
        db.execute(vault._AUTHORITY_SCHEMA_THREE["credential_vault_metadata"])
        db.execute("INSERT INTO credential_vault_metadata VALUES(1,3,?,1)", (incarnation,))
        body = c.parse_account_json(db.execute("SELECT body FROM account_store_head").fetchone()[0])
        body.pop("operations_digest")
        encoded = c.canonical_account_json(body)
        db.execute("UPDATE account_store_head SET body=?,mac=?", (encoded, store._mac("head", encoded)))
        db.execute("PRAGMA user_version=3")
        db.commit()
        preserved = {
            name: tuple(tuple(row) for row in db.execute(f"SELECT * FROM {name}"))
            for name in (
                "accounts", "credential_selector_versions", "broker_selector_setup", "credential_quarantine",
                "account_store_key", "account_operations",
            )
        }
    reopened_credentials = vault.CredentialStore(path / "vault.db", "synthetic-password")
    try:
        reopened = m.AccountTransactionStore(reopened_credentials, workspace_path=path, backend_proof=lease.proof)
        assert reopened.operation(req.operation_id) == expected_operation
        assert reopened.pending_audit_events(reopened.owner_capability(lease.proof)) == expected_events
        with closing(sqlite3.connect(path / "vault.db")) as db:
            assert db.execute("PRAGMA user_version").fetchone()[0] == 4
            assert preserved == {name: tuple(db.execute(f"SELECT * FROM {name}")) for name in preserved}
            assert "operations_digest" in c.parse_account_json(db.execute("SELECT body FROM account_store_head").fetchone()[0])
    finally:
        reopened_credentials.close()


def test_failed_schema_three_audit_migration_preserves_entire_database(owned, monkeypatch):
    c, m, store, head = enrolled(owned)
    req = request(owned, c, head)
    store.admit(req)
    store.settle(req.operation_id, state=c.AccountOperationStage.REJECTED, reason="synthetic_rejection")
    owned[2].close()
    with closing(sqlite3.connect(owned[0] / "vault.db")) as db:
        incarnation = db.execute("SELECT vault_incarnation FROM credential_vault_metadata").fetchone()[0]
        db.execute("DROP TABLE account_audit_outbox")
        db.execute("DROP TABLE credential_vault_metadata")
        db.execute(vault._AUTHORITY_SCHEMA_THREE["credential_vault_metadata"])
        db.execute("INSERT INTO credential_vault_metadata VALUES(1,3,?,1)", (incarnation,))
        body = c.parse_account_json(db.execute("SELECT body FROM account_store_head").fetchone()[0])
        body.pop("operations_digest")
        encoded = c.canonical_account_json(body)
        db.execute("UPDATE account_store_head SET body=?,mac=?", (encoded, store._mac("head", encoded)))
        db.execute("PRAGMA user_version=3")
        db.commit()
        before = tuple(db.iterdump())
    original = m._ensure_audit_event

    def fail_after_insertion(conn, body, mac):
        original(conn, body, mac)
        raise RuntimeError("PRIVATE-backfill-secret")

    monkeypatch.setattr(m, "_ensure_audit_event", fail_after_insertion)
    with pytest.raises(vault.CredentialVaultInvalidError) as caught:
        vault.CredentialStore(owned[0] / "vault.db", "synthetic-password")
    assert str(caught.value) == "credential_vault_invalid"
    with closing(sqlite3.connect(owned[0] / "vault.db")) as db:
        assert tuple(db.iterdump()) == before


def test_crash_after_audit_ack_commit_keeps_delivered_evidence_without_domain_replay(owned, monkeypatch):
    c, m, store, head = enrolled(owned)
    req = request(owned, c, head)
    store.admit(req)
    receipt = store.settle(req.operation_id, state=c.AccountOperationStage.REJECTED, reason="synthetic_rejection")
    cap = store.owner_capability(owned[1].proof)
    original = owned[2]._validate_family
    reported = []
    delivered_ids = []

    def fail_after_commit():
        original()
        if _database_row(owned, "account_audit_outbox", req.operation_id)["delivered"] and not reported:
            reported.append(True)
            raise vault.CredentialError

    def sink(event):
        delivered_ids.append(event.event_id)
        return event.event_id

    monkeypatch.setattr(owned[2], "_validate_family", fail_after_commit)
    with pytest.raises(vault.CredentialError):
        store.export_audit_events(cap, sink)
    assert reported == [True] and len(delivered_ids) == 1
    reopened = m.AccountTransactionStore(owned[2], workspace_path=owned[0], backend_proof=owned[1].proof)
    other_cap = reopened.owner_capability(owned[1].proof)
    assert reopened.pending_audit_events(other_cap) == ()
    assert reopened.export_audit_events(other_cap, sink) == 0
    assert len(delivered_ids) == 1
    assert reopened.operation(req.operation_id).receipt == receipt
    assert owned[2].selector_state(req.selector).version.generation == 0


@pytest.mark.parametrize("damage", ["delete", "event_id", "body", "delivered", "schema", "index", "trigger"])
def test_outbox_corruption_refuses_all_pending_and_export_reads(owned, damage):
    c, _, store, head = enrolled(owned)
    req = request(owned, c, head)
    store.admit(req)
    store.settle(req.operation_id, state=c.AccountOperationStage.REJECTED, reason="synthetic_rejection")
    cap = store.owner_capability(owned[1].proof)
    with closing(sqlite3.connect(owned[0] / "vault.db")) as db:
        statement = {
            "delete": "DELETE FROM account_audit_outbox",
            "event_id": "UPDATE account_audit_outbox SET event_id='not-a-uuid'",
            "body": "UPDATE account_audit_outbox SET body='{}'",
            "delivered": "UPDATE account_audit_outbox SET delivered=1",
            "schema": "ALTER TABLE account_audit_outbox ADD COLUMN unexpected TEXT",
            "index": "CREATE INDEX unexpected_audit_index ON account_audit_outbox(event_id)",
            "trigger": "CREATE TRIGGER unexpected_audit_trigger AFTER UPDATE ON account_audit_outbox BEGIN SELECT 1; END",
        }[damage]
        db.execute(statement)
        db.commit()
    with pytest.raises(vault.CredentialError):
        store.pending_audit_events(cap)
    with pytest.raises(vault.CredentialError):
        store.export_audit_events(cap, lambda event: pytest.fail("invalid source reached sink"))


def test_signed_outbox_evidence_must_still_match_exact_terminal_source(owned):
    c, m, store, head = enrolled(owned)
    req = request(owned, c, head)
    store.admit(req)
    store.settle(req.operation_id, state=c.AccountOperationStage.REJECTED, reason="synthetic_rejection")
    cap = store.owner_capability(owned[1].proof)
    event = store.pending_audit_events(cap)[0]
    # The source cross-check remains load-bearing even for a synthetic signed
    # envelope and manifest; another terminal event must never be substituted.
    wrong = replace(event, actor_ref="0" * 64)
    with closing(sqlite3.connect(owned[0] / "vault.db")) as db:
        db.row_factory = sqlite3.Row
        row = dict(db.execute("SELECT * FROM account_audit_outbox").fetchone())
        row["body"] = c.canonical_account_json(wrong.to_dict())
        db.execute("UPDATE account_audit_outbox SET body=?,mac=?", (row["body"], m._audit_row_mac(row, store._mac)))
        store._write_head(db, store._read_head(db))
        db.commit()
    with pytest.raises(m.AccountTransactionError):
        store.pending_audit_events(cap)
