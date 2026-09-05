"""Real-filesystem crash boundaries and compensation counter contracts."""

import json
import os
import subprocess
import sys
from uuid import uuid4

import pytest

from flinttrade_core import service_connection_store as module
from flinttrade_core.service_connection_store import (
    ConnectionActorContext,
    ConnectionStoreUnavailable,
    ServiceConnectionStore,
)


class Crash(BaseException):
    pass


ACTOR = ConnectionActorContext("operator", "session:" + "a" * 64)
PAYLOAD = {"provider_id": "llm:openai", "label": "Primary", "auth_mode": "api_key", "credential": "1234"}


@pytest.mark.parametrize(
    "boundary, regressed_generation",
    [("prepared_journal", 1), ("workspace_cas", 2), ("workspace_bound", 2), ("committed", 2)],
)
def test_recovery_rejects_workspace_generation_below_journal_evidence(
    tmp_path, monkeypatch, boundary, regressed_generation
):
    from flinttrade_core.workspace_migrations import compare_and_swap_workspace

    store = ServiceConnectionStore(tmp_path)
    first = store.mutate(
        "create",
        PAYLOAD,
        connection_id=None,
        expected_etag=store.read_snapshot().etag,
        idempotency_key=str(uuid4()),
        actor_context=ACTOR,
    )
    compare_and_swap_workspace(
        tmp_path, store.read_snapshot().workspace_version, lambda config: config.update(unrelated=True)
    )

    def crash(name):
        if name == boundary:
            raise Crash()

    monkeypatch.setattr(module, "_checkpoint", crash)
    with pytest.raises(Crash):
        store.mutate(
            "update",
            {},
            connection_id=first.body["connection_id"],
            expected_etag=first.etag,
            idempotency_key=str(uuid4()),
            actor_context=ACTOR,
        )
    workspace_path = tmp_path / "workspace.json"
    config = json.loads(workspace_path.read_text())
    config["workspace_generation"] = regressed_generation
    workspace_path.write_text(json.dumps(config))
    journal_path = tmp_path / "service-connections-state" / "transaction.json"
    prior_workspace, prior_journal = workspace_path.read_bytes(), journal_path.read_bytes()
    monkeypatch.setattr(module, "_checkpoint", lambda _name: None)
    with pytest.raises(ConnectionStoreUnavailable):
        ServiceConnectionStore(tmp_path).recover()
    assert workspace_path.read_bytes() == prior_workspace
    assert journal_path.read_bytes() == prior_journal


@pytest.mark.parametrize(
    "boundary, epoch, count, status",
    [
        ("prepared_journal", 0, 0, 503),
        ("secret_install", 1, 0, 503),
        ("workspace_cas", 2, 0, 503),
        ("workspace_bound", 2, 0, 503),
        ("committed", 1, 1, 201),
        ("terminal_audit", 1, 1, 201),
        ("terminal_receipt", 1, 1, 201),
        ("candidate_cleanup", 1, 1, 201),
        ("journal_cleanup", 1, 1, 201),
    ],
)
def test_first_create_crash_recovery_is_exactly_once(tmp_path, monkeypatch, boundary, epoch, count, status):
    store = ServiceConnectionStore(tmp_path)
    etag, key = store.read_snapshot().etag, str(uuid4())

    def crash(name):
        if name == boundary:
            raise Crash()

    monkeypatch.setattr(module, "_checkpoint", crash)
    with pytest.raises(Crash):
        store.mutate(
            "create", PAYLOAD, connection_id=None, expected_etag=etag, idempotency_key=key, actor_context=ACTOR
        )
    monkeypatch.setattr(module, "_checkpoint", lambda _name: None)
    reopened = ServiceConnectionStore(tmp_path)
    recovered = reopened.recover()
    assert recovered.epoch == epoch
    assert len(recovered.connections) == count
    assert reopened.recover() == recovered
    replay = reopened.mutate(
        "create", PAYLOAD, connection_id=None, expected_etag=etag, idempotency_key=key, actor_context=ACTOR
    )
    assert replay.status == status
    assert reopened.read_snapshot() == recovered
    events = [
        json.loads(path.read_text()) for path in (tmp_path / "service-connections-state" / "outbox").glob("*.json")
    ]
    assert next(event for event in events if event["outcome"] != "prepared")["after_epoch"] == epoch


@pytest.mark.parametrize("second_boundary", ["recovery_decision", "recovery_install", "recovery_cas", "terminal_audit"])
def test_second_crash_during_rotate_compensation_does_not_consume_another_generation(
    tmp_path, monkeypatch, second_boundary
):
    store = ServiceConnectionStore(tmp_path)
    first = store.mutate(
        "create",
        PAYLOAD,
        connection_id=None,
        expected_etag=store.read_snapshot().etag,
        idempotency_key=str(uuid4()),
        actor_context=ACTOR,
    )

    def crash(name):
        if name == "workspace_cas":
            raise Crash()

    monkeypatch.setattr(module, "_checkpoint", crash)
    with pytest.raises(Crash):
        store.mutate(
            "update",
            {"credential": "5678"},
            connection_id=first.body["connection_id"],
            expected_etag=first.etag,
            idempotency_key=str(uuid4()),
            actor_context=ACTOR,
        )

    def crash_again(name):
        if name == second_boundary:
            raise Crash()

    monkeypatch.setattr(module, "_checkpoint", crash_again)
    with pytest.raises(Crash):
        ServiceConnectionStore(tmp_path).recover()
    monkeypatch.setattr(module, "_checkpoint", lambda _name: None)
    result = ServiceConnectionStore(tmp_path).recover()
    assert result.epoch == 3
    assert result.connections[0].secret_version.generation == 3
    assert result.connections[0].credential_configured is True
    assert ServiceConnectionStore(tmp_path).recover() == result


@pytest.mark.parametrize(
    "field,value",
    [("schema", True), ("secret_change", 1), ("extra", "unexpected"), ("before_epoch", -1), ("after_epoch", True)],
)
def test_malformed_journal_fails_closed_without_cleanup(tmp_path, monkeypatch, field, value):
    store = ServiceConnectionStore(tmp_path)
    etag = store.read_snapshot().etag

    def crash(name):
        if name == "prepared_journal":
            raise Crash()

    monkeypatch.setattr(module, "_checkpoint", crash)
    with pytest.raises(Crash):
        store.mutate(
            "create", PAYLOAD, connection_id=None, expected_etag=etag, idempotency_key=str(uuid4()), actor_context=ACTOR
        )
    path = tmp_path / "service-connections-state" / "transaction.json"
    journal = json.loads(path.read_text())
    journal[field] = value
    path.write_text(json.dumps(journal))
    prior = path.read_bytes()
    monkeypatch.setattr(module, "_checkpoint", lambda _name: None)
    with pytest.raises(ConnectionStoreUnavailable):
        ServiceConnectionStore(tmp_path).recover()
    assert path.read_bytes() == prior
    assert not (tmp_path / "workspace.json").exists()


def test_unjournalled_candidate_is_retained_and_fails_authority_closed(tmp_path, monkeypatch):
    store = ServiceConnectionStore(tmp_path)
    etag = store.read_snapshot().etag

    def crash(name):
        if name == "candidate":
            raise Crash()

    monkeypatch.setattr(module, "_checkpoint", crash)
    with pytest.raises(Crash):
        store.mutate(
            "create", PAYLOAD, connection_id=None, expected_etag=etag, idempotency_key=str(uuid4()), actor_context=ACTOR
        )
    candidates = list((tmp_path / "service-connections-state" / "candidates").iterdir())
    assert len(candidates) == 1
    prior = candidates[0].read_bytes()
    monkeypatch.setattr(module, "_checkpoint", lambda _name: None)
    with pytest.raises(ConnectionStoreUnavailable):
        store.recover()
    assert candidates[0].read_bytes() == prior


@pytest.mark.skipif(os.name == "nt", reason="Windows native directory handles reject rename")
def test_root_substitution_after_journal_never_reaches_workspace(tmp_path, monkeypatch):
    store = ServiceConnectionStore(tmp_path)
    etag = store.read_snapshot().etag

    def replace_root(name):
        if name == "prepared_journal":
            root = tmp_path / "secrets" / "services"
            root.rename(tmp_path / "original-secret-root")
            root.mkdir(mode=0o700)

    monkeypatch.setattr(module, "_checkpoint", replace_root)
    with pytest.raises(ConnectionStoreUnavailable):
        store.mutate(
            "create", PAYLOAD, connection_id=None, expected_etag=etag, idempotency_key=str(uuid4()), actor_context=ACTOR
        )
    assert list((tmp_path / "secrets" / "services").iterdir()) == []
    assert not (tmp_path / "workspace.json").exists()


@pytest.mark.parametrize(
    "boundary,epoch,count",
    [("secret_install", 1, 0), ("workspace_cas", 2, 0), ("committed", 1, 1), ("workspace_anchor", 1, 1)],
)
def test_process_exit_releases_locks_and_recovery_reopens(tmp_path, boundary, epoch, count):
    script = """
import os, sys
from pathlib import Path
from uuid import uuid4
from flinttrade_core import service_connection_store as m
store = m.ServiceConnectionStore(Path(sys.argv[1]))
etag = store.read_snapshot().etag
def crash(name):
    if name == sys.argv[2]: os._exit(73)
m._checkpoint = crash
store.mutate("create", {"provider_id":"llm:openai","label":"Primary","auth_mode":"api_key","credential":"1234"},
             connection_id=None, expected_etag=etag, idempotency_key=str(uuid4()),
             actor_context=m.ConnectionActorContext("operator", "session:" + "a" * 64))
"""
    child = subprocess.run([sys.executable, "-c", script, str(tmp_path), boundary], capture_output=True, timeout=20)
    assert child.returncode == 73, child.stderr.decode()
    result = ServiceConnectionStore(tmp_path).recover()
    assert (result.epoch, len(result.connections)) == (epoch, count)
    assert ServiceConnectionStore(tmp_path).recover() == result


@pytest.mark.parametrize("second_boundary", [None, "foreign_decision", "foreign_install", "foreign_terminal_audit"])
def test_foreign_first_creator_is_never_adopted_and_conflict_replays(tmp_path, monkeypatch, second_boundary):
    from flinttrade_core.workspace_migrations import compare_and_swap_workspace, read_workspace_snapshot

    store = ServiceConnectionStore(tmp_path)
    original_etag, key = store.read_snapshot().etag, str(uuid4())
    foreign = {}

    def compete(name):
        if name == "secret_install":
            snapshot = compare_and_swap_workspace(tmp_path, None, lambda config: config.update(winner="foreign"))
            foreign["version"] = snapshot.version
            foreign["bytes"] = (tmp_path / "workspace.json").read_bytes()
        if name == second_boundary:
            raise Crash()

    monkeypatch.setattr(module, "_checkpoint", compete)
    if second_boundary:
        with pytest.raises(Crash):
            store.mutate(
                "create",
                PAYLOAD,
                connection_id=None,
                expected_etag=original_etag,
                idempotency_key=key,
                actor_context=ACTOR,
            )
    else:
        result = store.mutate(
            "create", PAYLOAD, connection_id=None, expected_etag=original_etag, idempotency_key=key, actor_context=ACTOR
        )
        assert result.status == 409
    monkeypatch.setattr(module, "_checkpoint", lambda _name: None)
    with pytest.raises(ConnectionStoreUnavailable):
        store.recover()
    assert (tmp_path / "workspace.json").read_bytes() == foreign["bytes"]
    assert read_workspace_snapshot(tmp_path).version == foreign["version"]
    result = store.mutate(
        "create", PAYLOAD, connection_id=None, expected_etag=original_etag, idempotency_key=key, actor_context=ACTOR
    )
    assert result.status == 409 and result.etag == original_etag
    assert dict(result.body) == {"error": "connection_revision_conflict"}
    with pytest.raises(ConnectionStoreUnavailable):
        store.mutate(
            "create",
            PAYLOAD,
            connection_id=None,
            expected_etag=original_etag,
            idempotency_key=str(uuid4()),
            actor_context=ACTOR,
        )
    paths = list((tmp_path / "secrets" / "services").glob("*/credential"))
    assert len(paths) == 1
    version = json.loads(paths[0].read_text())["version"]
    assert version["generation"] == 2 and version["present"] is False
    (tmp_path / "service-connections-state" / "transaction.json").unlink()
    with pytest.raises(ConnectionStoreUnavailable):
        store.recover()


@pytest.mark.parametrize("boundary", ["receipt", "prepared_audit"])
def test_admission_crash_before_journal_has_durable_terminal_failure_audit(tmp_path, monkeypatch, boundary):
    store = ServiceConnectionStore(tmp_path)
    etag, key = store.read_snapshot().etag, str(uuid4())

    def crash(name):
        if name == boundary:
            raise Crash()

    monkeypatch.setattr(module, "_checkpoint", crash)
    with pytest.raises(Crash):
        store.mutate(
            "create", PAYLOAD, connection_id=None, expected_etag=etag, idempotency_key=key, actor_context=ACTOR
        )
    monkeypatch.setattr(module, "_checkpoint", lambda _name: None)
    result = store.mutate(
        "create", PAYLOAD, connection_id=None, expected_etag=etag, idempotency_key=key, actor_context=ACTOR
    )
    assert result.status == 503 and result.etag == etag
    events = [
        json.loads(path.read_text()) for path in (tmp_path / "service-connections-state" / "outbox").glob("*.json")
    ]
    terminal = [event for event in events if event["outcome"] == "failed"]
    assert len(terminal) == 1
    assert terminal[0]["after_epoch"] == 0
    assert terminal[0]["actor"] == ACTOR.actor
    assert store.read_snapshot().epoch == 0


def test_low_entropy_credential_and_unkeyed_hashes_never_enter_public_or_journal_state(tmp_path, monkeypatch, caplog):
    import hashlib

    secret = "pin=1111"
    store = ServiceConnectionStore(tmp_path)
    etag = store.read_snapshot().etag

    def crash(name):
        if name == "prepared_journal":
            raise Crash()

    monkeypatch.setattr(module, "_checkpoint", crash)
    with pytest.raises(Crash):
        store.mutate(
            "create",
            {**PAYLOAD, "credential": secret},
            connection_id=None,
            expected_etag=etag,
            idempotency_key=str(uuid4()),
            actor_context=ACTOR,
        )
    payloads = [path.read_bytes() for path in (tmp_path / "service-connections-state").rglob("*") if path.is_file()]
    payloads.append(caplog.text.encode())
    for payload in payloads:
        assert secret.encode() not in payload
        assert hashlib.sha256(secret.encode()).hexdigest().encode() not in payload
    for path in (tmp_path / "service-connections-state" / "outbox").glob("*.json"):
        event = json.loads(path.read_text())
        assert not set(event) & {"credential", "path", "mac", "digest", "request_mac", "candidate", "exception"}


def test_corrupt_backup_is_not_deleted_during_committed_cleanup(tmp_path, monkeypatch):
    store = ServiceConnectionStore(tmp_path)
    first = store.mutate(
        "create",
        PAYLOAD,
        connection_id=None,
        expected_etag=store.read_snapshot().etag,
        idempotency_key=str(uuid4()),
        actor_context=ACTOR,
    )

    def crash(name):
        if name == "committed":
            raise Crash()

    monkeypatch.setattr(module, "_checkpoint", crash)
    with pytest.raises(Crash):
        store.mutate(
            "update",
            {"credential": "5678"},
            connection_id=first.body["connection_id"],
            expected_etag=first.etag,
            idempotency_key=str(uuid4()),
            actor_context=ACTOR,
        )
    old = next((tmp_path / "service-connections-state" / "candidates").glob("*.old"))
    old.write_text("corrupt-unrecognised-content")
    monkeypatch.setattr(module, "_checkpoint", lambda _name: None)
    with pytest.raises(ConnectionStoreUnavailable):
        store.recover()
    assert old.read_text() == "corrupt-unrecognised-content"


def test_local_prepared_audit_failure_has_no_domain_effect(tmp_path, monkeypatch):
    from flinttrade_core.secure_file import HeldOwnerDirectory

    real_write = HeldOwnerDirectory.write_text

    def fail_audit(directory, name, value):
        if directory.path.name == "outbox":
            raise OSError("audit unavailable")
        return real_write(directory, name, value)

    monkeypatch.setattr(HeldOwnerDirectory, "write_text", fail_audit)
    store = ServiceConnectionStore(tmp_path)
    with pytest.raises(ConnectionStoreUnavailable):
        store.mutate(
            "create",
            PAYLOAD,
            connection_id=None,
            expected_etag=store.read_snapshot().etag,
            idempotency_key=str(uuid4()),
            actor_context=ACTOR,
        )
    assert not (tmp_path / "workspace.json").exists()
    assert list((tmp_path / "secrets" / "services").iterdir()) == []


def test_recovery_does_not_replace_a_corrupt_independent_anchor(tmp_path, monkeypatch):
    store = ServiceConnectionStore(tmp_path)
    first = store.mutate(
        "create",
        PAYLOAD,
        connection_id=None,
        expected_etag=store.read_snapshot().etag,
        idempotency_key=str(uuid4()),
        actor_context=ACTOR,
    )

    def crash(name):
        if name == "committed":
            raise Crash()

    monkeypatch.setattr(module, "_checkpoint", crash)
    with pytest.raises(Crash):
        store.mutate(
            "update",
            {},
            connection_id=first.body["connection_id"],
            expected_etag=first.etag,
            idempotency_key=str(uuid4()),
            actor_context=ACTOR,
        )
    path = tmp_path / "service-connections-state" / "workspace-anchor.json"
    anchor = json.loads(path.read_text())
    anchor["instance_id"] = str(uuid4())
    path.write_text(json.dumps(anchor))
    before = path.read_bytes()
    monkeypatch.setattr(module, "_checkpoint", lambda _name: None)
    with pytest.raises(ConnectionStoreUnavailable):
        store.recover()
    assert path.read_bytes() == before


def test_crash_after_key_tombstone_cannot_remint_or_change_admission(tmp_path, monkeypatch):
    from flinttrade_core.service_connection_store import ConnectionIdempotencyConflict

    store = ServiceConnectionStore(tmp_path)
    etag, key = store.read_snapshot().etag, str(uuid4())

    def crash(name):
        if name == "key_tombstone":
            raise Crash()

    monkeypatch.setattr(module, "_checkpoint", crash)
    with pytest.raises(Crash):
        store.mutate(
            "create", PAYLOAD, connection_id=None, expected_etag=etag, idempotency_key=key, actor_context=ACTOR
        )
    path = tmp_path / "service-connections-state" / "operation-keys" / f"{key}.json"
    admitted = path.read_bytes()
    monkeypatch.setattr(module, "_checkpoint", lambda _name: None)
    with pytest.raises(ConnectionStoreUnavailable):
        store.mutate(
            "create", PAYLOAD, connection_id=None, expected_etag=etag, idempotency_key=key, actor_context=ACTOR
        )
    with pytest.raises(ConnectionIdempotencyConflict):
        store.mutate(
            "create",
            {**PAYLOAD, "credential": "5678"},
            connection_id=None,
            expected_etag=etag,
            idempotency_key=key,
            actor_context=ACTOR,
        )
    assert path.read_bytes() == admitted
    assert not (tmp_path / "workspace.json").exists()


@pytest.mark.parametrize("member", ["journal", "backup", "outbox"])
def test_authenticated_delete_pending_artifacts_complete_cleanup(tmp_path, monkeypatch, member):
    from flinttrade_core.secure_file import pending_unlink_path

    store = ServiceConnectionStore(tmp_path)
    first = store.mutate(
        "create",
        PAYLOAD,
        connection_id=None,
        expected_etag=store.read_snapshot().etag,
        idempotency_key=str(uuid4()),
        actor_context=ACTOR,
    )

    def crash(name):
        if name == "committed":
            raise Crash()

    monkeypatch.setattr(module, "_checkpoint", crash)
    with pytest.raises(Crash):
        store.mutate(
            "update",
            {"credential": "5678"},
            connection_id=first.body["connection_id"],
            expected_etag=first.etag,
            idempotency_key=str(uuid4()),
            actor_context=ACTOR,
        )
    control = tmp_path / "service-connections-state"
    path = (
        control / "transaction.json"
        if member == "journal"
        else (
            next((control / "candidates").glob("*.old"))
            if member == "backup"
            else next((control / "outbox").glob("*.json"))
        )
    )
    path.rename(pending_unlink_path(path))
    monkeypatch.setattr(module, "_checkpoint", lambda _name: None)
    events = []
    reopened = ServiceConnectionStore(tmp_path, audit_sink=events.append)
    result = reopened.recover()
    assert result.epoch == 2
    assert reopened.recover() == result
    assert list((control / "candidates").iterdir()) == []
    assert list((control / "outbox").iterdir()) == []
    assert not pending_unlink_path(path).exists()
