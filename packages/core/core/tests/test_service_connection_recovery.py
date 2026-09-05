"""Real-filesystem crash boundaries and compensation counter contracts."""

import json
import os
import subprocess
import sys
from dataclasses import replace
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


@pytest.mark.parametrize("kind", ["unrecognised", "generation", "binding"])
@pytest.mark.parametrize("boundary", ["backup", "new_target_read"])
def test_install_preserves_substituted_destination_after_backup(tmp_path, monkeypatch, kind, boundary):
    store = ServiceConnectionStore(tmp_path)
    first = store.mutate(
        "create",
        PAYLOAD,
        connection_id=None,
        expected_etag=store.read_snapshot().etag,
        idempotency_key=str(uuid4()),
        actor_context=ACTOR,
    )
    binding = store.read_snapshot().connections[0].secret_version
    with module.TransactionFiles(tmp_path) as files:
        if kind == "generation":
            hostile = files.envelope(replace(binding, generation=7), "fixture-substitution")
        elif kind == "binding":
            hostile = files.envelope(replace(binding, binding_id=uuid4()), "fixture-substitution")
        else:
            hostile = {"unrecognised": "retain this file"}
    replacement_bytes = json.dumps(hostile).encode()
    secret = tmp_path / "secrets" / "services" / first.body["connection_id"] / "credential"
    workspace_path = tmp_path / "workspace.json"
    workspace_before = workspace_path.read_bytes()

    def substitute(name):
        if name == boundary:
            temporary = secret.with_name("substitute")
            temporary.write_bytes(replacement_bytes)
            temporary.chmod(0o600)
            temporary.replace(secret)

    monkeypatch.setattr(module, "_checkpoint", substitute)
    with pytest.raises(ConnectionStoreUnavailable):
        store.mutate(
            "update",
            {"credential": "5678"},
            connection_id=first.body["connection_id"],
            expected_etag=first.etag,
            idempotency_key=str(uuid4()),
            actor_context=ACTOR,
        )
    assert secret.read_bytes() == replacement_bytes
    assert workspace_path.read_bytes() == workspace_before
    assert (tmp_path / "service-connections-state" / "transaction.json").exists()


@pytest.mark.parametrize(
    "boundary,generation,epoch",
    [
        ("new_target_read", 1, 1),
        ("new_claim_intent", 1, 1),
        ("new_claim", 1, 1),
        ("new_claim_verified", 1, 1),
        ("new_published", 3, 2),
    ],
)
def test_claim_crashes_restore_or_compensate_once(tmp_path, monkeypatch, boundary, generation, epoch):
    store = ServiceConnectionStore(tmp_path)
    first = store.mutate(
        "create",
        PAYLOAD,
        connection_id=None,
        expected_etag=store.read_snapshot().etag,
        idempotency_key=str(uuid4()),
        actor_context=ACTOR,
    )
    key = str(uuid4())

    def crash(name):
        if name == boundary:
            raise Crash()

    monkeypatch.setattr(module, "_checkpoint", crash)
    with pytest.raises(Crash):
        store.mutate(
            "update",
            {"credential": "5678"},
            connection_id=first.body["connection_id"],
            expected_etag=first.etag,
            idempotency_key=key,
            actor_context=ACTOR,
        )
    monkeypatch.setattr(module, "_checkpoint", lambda _name: None)
    result = store.recover()
    assert result.epoch == epoch
    assert result.connections[0].secret_version.generation == generation
    with module.TransactionFiles(tmp_path) as files:
        envelope = files.live(result.connections[0].secret_version)
        assert files.cipher.decrypt(envelope["ciphertext"].encode()).decode() == "1234"
    assert store.recover() == result
    assert (
        store.mutate(
            "update",
            {"credential": "5678"},
            connection_id=first.body["connection_id"],
            expected_etag=first.etag,
            idempotency_key=key,
            actor_context=ACTOR,
        ).status
        == 503
    )


@pytest.mark.parametrize("conflict", ["publication", "restoration"])
def test_claim_conflicts_preserve_both_members_and_workspace(tmp_path, monkeypatch, conflict):
    store = ServiceConnectionStore(tmp_path)
    first = store.mutate(
        "create",
        PAYLOAD,
        connection_id=None,
        expected_etag=store.read_snapshot().etag,
        idempotency_key=str(uuid4()),
        actor_context=ACTOR,
    )
    secret = tmp_path / "secrets" / "services" / first.body["connection_id"] / "credential"
    key = str(uuid4())
    claim = tmp_path / "service-connections-state" / "candidates" / f"{key}.new.claimed"
    original = secret.read_bytes()
    workspace = tmp_path / "workspace.json"
    before = workspace.read_bytes()

    def write_entry(value):
        temporary = secret.with_name("entrant")
        temporary.write_bytes(value)
        temporary.chmod(0o600)
        temporary.replace(secret)

    def conflict_at_boundary(name):
        if conflict == "restoration" and name == "new_target_read":
            write_entry(b"unrecognised substituted member")
        if name == ("new_claim_verified" if conflict == "publication" else "claim_restore_before"):
            write_entry(b"retain concurrent entrant")

    monkeypatch.setattr(module, "_checkpoint", conflict_at_boundary)
    with pytest.raises(ConnectionStoreUnavailable):
        store.mutate(
            "update",
            {"credential": "5678"},
            connection_id=first.body["connection_id"],
            expected_etag=first.etag,
            idempotency_key=key,
            actor_context=ACTOR,
        )
    assert secret.read_bytes() == b"retain concurrent entrant"
    assert claim.read_bytes() == (original if conflict == "publication" else b"unrecognised substituted member")
    assert workspace.read_bytes() == before
    monkeypatch.setattr(module, "_checkpoint", lambda _name: None)
    with pytest.raises(ConnectionStoreUnavailable):
        store.recover()
    assert secret.read_bytes() == b"retain concurrent entrant"
    assert claim.read_bytes() == (original if conflict == "publication" else b"unrecognised substituted member")
    assert workspace.read_bytes() == before


@pytest.mark.parametrize(
    "second_boundary",
    [
        "recovery_claim_intent",
        "recovery_claim",
        "recovery_claim_verified",
        "recovery_published",
        "claim_restored",
    ],
)
def test_second_claim_crash_does_not_remint_compensation(tmp_path, monkeypatch, second_boundary):
    store = ServiceConnectionStore(tmp_path)
    first = store.mutate(
        "create",
        PAYLOAD,
        connection_id=None,
        expected_etag=store.read_snapshot().etag,
        idempotency_key=str(uuid4()),
        actor_context=ACTOR,
    )

    def fail_at(boundary):
        def crash(name):
            if name == boundary:
                raise Crash()

        monkeypatch.setattr(module, "_checkpoint", crash)

    fail_at("secret_install")
    with pytest.raises(Crash):
        store.mutate(
            "update",
            {"credential": "5678"},
            connection_id=first.body["connection_id"],
            expected_etag=first.etag,
            idempotency_key=str(uuid4()),
            actor_context=ACTOR,
        )
    if second_boundary == "claim_restored":
        fail_at("recovery_claim")
        with pytest.raises(Crash):
            store.recover()
    fail_at(second_boundary)
    with pytest.raises(Crash):
        store.recover()
    monkeypatch.setattr(module, "_checkpoint", lambda _name: None)
    result = store.recover()
    assert result.epoch == 2
    assert result.connections[0].secret_version.generation == 3
    assert store.recover() == result


def test_bad_compensation_digest_cannot_restore_a_claim_before_rejection(tmp_path, monkeypatch):
    store = ServiceConnectionStore(tmp_path)
    first = store.mutate(
        "create",
        PAYLOAD,
        connection_id=None,
        expected_etag=store.read_snapshot().etag,
        idempotency_key=str(uuid4()),
        actor_context=ACTOR,
    )

    def fail_at(boundary):
        def crash(name):
            if name == boundary:
                raise Crash()

        monkeypatch.setattr(module, "_checkpoint", crash)

    fail_at("secret_install")
    with pytest.raises(Crash):
        store.mutate(
            "update",
            {"credential": "5678"},
            connection_id=first.body["connection_id"],
            expected_etag=first.etag,
            idempotency_key=str(uuid4()),
            actor_context=ACTOR,
        )
    fail_at("recovery_claim")
    with pytest.raises(Crash):
        store.recover()
    journal_path = tmp_path / "service-connections-state" / "transaction.json"
    journal = json.loads(journal_path.read_text())
    journal["recovery"]["after_digest"] = "0" * 64
    journal_path.write_text(json.dumps(journal))
    secret = tmp_path / "secrets" / "services" / first.body["connection_id"] / "credential"
    assert not secret.exists()
    before = journal_path.read_bytes()
    monkeypatch.setattr(module, "_checkpoint", lambda _name: None)
    with pytest.raises(ConnectionStoreUnavailable):
        store.recover()
    assert not secret.exists(), "malformed recovery changed live state before refusal"
    assert journal_path.read_bytes() == before


@pytest.mark.parametrize("barrier", [1, 2])
@pytest.mark.parametrize("phase", ["new", "recovery", "restore"])
@pytest.mark.skipif(os.name == "nt", reason="POSIX namespace fsync boundaries")
def test_claim_namespace_barrier_crash_is_recoverable(tmp_path, monkeypatch, barrier, phase):
    from flinttrade_core import secure_file

    store = ServiceConnectionStore(tmp_path)
    first = store.mutate(
        "create",
        PAYLOAD,
        connection_id=None,
        expected_etag=store.read_snapshot().etag,
        idempotency_key=str(uuid4()),
        actor_context=ACTOR,
    )
    if phase != "new":

        def interrupt_initial(name):
            if name == ("secret_install" if phase == "recovery" else "new_claim"):
                raise Crash()

        monkeypatch.setattr(module, "_checkpoint", interrupt_initial)
        with pytest.raises(Crash):
            store.mutate(
                "update",
                {"credential": "5678"},
                connection_id=first.body["connection_id"],
                expected_etag=first.etag,
                idempotency_key=str(uuid4()),
                actor_context=ACTOR,
            )
        monkeypatch.setattr(module, "_checkpoint", lambda _name: None)
    move, sync = secure_file._posix_move_no_replace, os.fsync
    state = {"claimed": False, "barriers": 0}

    def moved(source_fd, source, target_fd, target):
        move(source_fd, source, target_fd, target)
        if (
            source == "credential"
            and target.endswith(f".{phase}.claimed")
            or phase == "restore"
            and source.endswith(".new.claimed")
            and target == "credential"
        ):
            state["claimed"] = True

    def synced(descriptor):
        sync(descriptor)
        if state["claimed"]:
            state["barriers"] += 1
            if state["barriers"] == barrier:
                raise Crash()

    monkeypatch.setattr(secure_file, "_posix_move_no_replace", moved)
    monkeypatch.setattr(os, "fsync", synced)
    with pytest.raises(Crash):
        if phase == "new":
            store.mutate(
                "update",
                {"credential": "5678"},
                connection_id=first.body["connection_id"],
                expected_etag=first.etag,
                idempotency_key=str(uuid4()),
                actor_context=ACTOR,
            )
        else:
            store.recover()
    monkeypatch.setattr(secure_file, "_posix_move_no_replace", move)
    monkeypatch.setattr(os, "fsync", sync)
    recovered = store.recover()
    assert recovered.epoch == (2 if phase == "recovery" else 1)
    assert recovered.connections[0].secret_version.generation == (3 if phase == "recovery" else 1)
    assert store.recover() == recovered


def test_claim_identity_corruption_is_retained_without_restoration(tmp_path, monkeypatch):
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
        if name == "new_claim":
            raise Crash()

    key = str(uuid4())
    monkeypatch.setattr(module, "_checkpoint", crash)
    with pytest.raises(Crash):
        store.mutate(
            "update",
            {"credential": "5678"},
            connection_id=first.body["connection_id"],
            expected_etag=first.etag,
            idempotency_key=key,
            actor_context=ACTOR,
        )
    path = tmp_path / "service-connections-state" / "transaction.json"
    journal = json.loads(path.read_text())
    journal["claims"]["new"]["identity"]["object"] += 1
    path.write_text(json.dumps(journal))
    claim = tmp_path / "service-connections-state" / "candidates" / f"{key}.new.claimed"
    before = path.read_bytes(), claim.read_bytes()
    monkeypatch.setattr(module, "_checkpoint", lambda _name: None)
    with pytest.raises(ConnectionStoreUnavailable):
        store.recover()
    assert (path.read_bytes(), claim.read_bytes()) == before
    assert not (tmp_path / "secrets" / "services" / first.body["connection_id"] / "credential").exists()


def test_first_install_does_not_clobber_a_last_moment_entrant(tmp_path, monkeypatch):
    from flinttrade_core.secure_file import HeldOwnerDirectory

    store = ServiceConnectionStore(tmp_path)
    etag, key = store.read_snapshot().etag, str(uuid4())
    real_move = HeldOwnerDirectory.move_no_replace
    entrant = []

    def race(source, name, destination, target):
        if name.endswith(".new") and target == "credential":
            path = destination.path / target
            path.write_text("retain unexpected member")
            path.chmod(0o600)
            entrant.append(path)
        return real_move(source, name, destination, target)

    monkeypatch.setattr(HeldOwnerDirectory, "move_no_replace", race)
    with pytest.raises(ConnectionStoreUnavailable):
        store.mutate(
            "create", PAYLOAD, connection_id=None, expected_etag=etag, idempotency_key=key, actor_context=ACTOR
        )
    assert entrant[0].read_text() == "retain unexpected member"
    assert not (tmp_path / "workspace.json").exists()
    assert (tmp_path / "service-connections-state" / "candidates" / f"{key}.new").exists()


def test_cas_rechecks_the_actual_intended_live_binding(tmp_path, monkeypatch):
    store = ServiceConnectionStore(tmp_path)
    first = store.mutate(
        "create",
        PAYLOAD,
        connection_id=None,
        expected_etag=store.read_snapshot().etag,
        idempotency_key=str(uuid4()),
        actor_context=ACTOR,
    )
    binding = store.read_snapshot().connections[0].secret_version
    with module.TransactionFiles(tmp_path) as files:
        hostile = files.envelope(replace(binding, generation=2, binding_id=uuid4()), "fixture-substitution")
    secret = tmp_path / "secrets" / "services" / first.body["connection_id"] / "credential"
    workspace = tmp_path / "workspace.json"
    before = workspace.read_bytes()
    altered = json.dumps(hostile).encode()

    def substitute(name):
        if name == "secret_install":
            secret.write_bytes(altered)

    monkeypatch.setattr(module, "_checkpoint", substitute)
    with pytest.raises(ConnectionStoreUnavailable):
        store.mutate(
            "update",
            {"credential": "5678"},
            connection_id=first.body["connection_id"],
            expected_etag=first.etag,
            idempotency_key=str(uuid4()),
            actor_context=ACTOR,
        )
    assert workspace.read_bytes() == before
    assert secret.read_bytes() == altered


def test_occupied_claim_destination_preserves_original_and_unknown_claim(tmp_path, monkeypatch):
    store = ServiceConnectionStore(tmp_path)
    first = store.mutate(
        "create",
        PAYLOAD,
        connection_id=None,
        expected_etag=store.read_snapshot().etag,
        idempotency_key=str(uuid4()),
        actor_context=ACTOR,
    )
    key = str(uuid4())
    claim = tmp_path / "service-connections-state" / "candidates" / f"{key}.new.claimed"
    secret = tmp_path / "secrets" / "services" / first.body["connection_id"] / "credential"
    workspace = tmp_path / "workspace.json"
    original, before = secret.read_bytes(), workspace.read_bytes()

    def occupy(name):
        if name == "new_claim_intent":
            claim.write_text("retain occupied claim")
            claim.chmod(0o600)

    monkeypatch.setattr(module, "_checkpoint", occupy)
    with pytest.raises(ConnectionStoreUnavailable):
        store.mutate(
            "update",
            {"credential": "5678"},
            connection_id=first.body["connection_id"],
            expected_etag=first.etag,
            idempotency_key=key,
            actor_context=ACTOR,
        )
    assert secret.read_bytes() == original
    assert workspace.read_bytes() == before
    assert claim.read_text() == "retain occupied claim"
    monkeypatch.setattr(module, "_checkpoint", lambda _name: None)
    with pytest.raises(ConnectionStoreUnavailable):
        store.recover()
    assert secret.read_bytes() == original
    assert claim.read_text() == "retain occupied claim"


def test_claim_replaced_after_terminal_receipt_is_not_deleted_by_cleanup_or_replay(tmp_path, monkeypatch):
    store = ServiceConnectionStore(tmp_path)
    first = store.mutate(
        "create",
        PAYLOAD,
        connection_id=None,
        expected_etag=store.read_snapshot().etag,
        idempotency_key=str(uuid4()),
        actor_context=ACTOR,
    )
    key = str(uuid4())
    claim = tmp_path / "service-connections-state" / "candidates" / f"{key}.new.claimed"

    def substitute(name):
        if name == "terminal_receipt":
            temporary = claim.with_name("replacement")
            temporary.write_text("retain unknown claim")
            temporary.chmod(0o600)
            temporary.replace(claim)

    monkeypatch.setattr(module, "_checkpoint", substitute)
    with pytest.raises(ConnectionStoreUnavailable):
        store.mutate(
            "update",
            {"credential": "5678"},
            connection_id=first.body["connection_id"],
            expected_etag=first.etag,
            idempotency_key=key,
            actor_context=ACTOR,
        )
    assert claim.read_text() == "retain unknown claim"
    monkeypatch.setattr(module, "_checkpoint", lambda _name: None)
    replay = store.mutate(
        "update",
        {"credential": "5678"},
        connection_id=first.body["connection_id"],
        expected_etag=first.etag,
        idempotency_key=key,
        actor_context=ACTOR,
    )
    assert replay.status == 200
    assert claim.read_text() == "retain unknown claim"
    with pytest.raises(ConnectionStoreUnavailable):
        store.recover()
    assert claim.read_text() == "retain unknown claim"


@pytest.mark.parametrize(
    "boundary,epoch,count,status",
    [
        ("prepared_journal", 0, 0, 503),
        ("workspace_cas", 2, 0, 503),
        ("committed", 1, 1, 201),
    ],
)
def test_first_connection_in_existing_empty_workspace_recovers(tmp_path, monkeypatch, boundary, epoch, count, status):
    from flinttrade_core.workspace_migrations import compare_and_swap_workspace

    original = compare_and_swap_workspace(tmp_path, None, lambda config: config.update(unrelated="kept"))
    store = ServiceConnectionStore(tmp_path)
    etag, key = store.read_snapshot().etag, str(uuid4())
    payload = {"provider_id": "llm:ollama", "label": "Local"}

    def crash(name):
        if name == boundary:
            raise Crash()

    monkeypatch.setattr(module, "_checkpoint", crash)
    with pytest.raises(Crash):
        store.mutate(
            "create", payload, connection_id=None, expected_etag=etag, idempotency_key=key, actor_context=ACTOR
        )
    monkeypatch.setattr(module, "_checkpoint", lambda _name: None)
    reopened = ServiceConnectionStore(tmp_path)
    result = reopened.recover()
    assert (result.epoch, len(result.connections)) == (epoch, count)
    assert result.workspace_version.instance_id == original.version.instance_id
    assert json.loads((tmp_path / "workspace.json").read_text())["unrelated"] == "kept"
    assert reopened.recover() == result
    assert (
        reopened.mutate(
            "create", payload, connection_id=None, expected_etag=etag, idempotency_key=key, actor_context=ACTOR
        ).status
        == status
    )


def test_cas_retry_retains_last_generation_for_compensation(tmp_path, monkeypatch):
    store = ServiceConnectionStore(tmp_path)
    first = store.mutate(
        "create",
        PAYLOAD,
        connection_id=None,
        expected_etag=store.read_snapshot().etag,
        idempotency_key=str(uuid4()),
        actor_context=ACTOR,
    )
    workspace_path = tmp_path / "workspace.json"
    config = json.loads(workspace_path.read_text())
    maximum = (1 << 63) - 1
    config["workspace_generation"] = maximum - 2
    workspace_path.write_text(json.dumps(config))
    before = store.read_snapshot()
    real_cas = module.compare_and_swap_workspace
    conflicts = []

    def collide(path, expected, updater):
        if not conflicts:
            conflicts.append(True)
            real_cas(path, expected, lambda latest: latest.update(unrelated="retained"))
        return real_cas(path, expected, updater)

    published = []

    def crash_if_published(name):
        if name == "workspace_cas":
            published.append(True)
            raise Crash()

    monkeypatch.setattr(module, "compare_and_swap_workspace", collide)
    monkeypatch.setattr(module, "_checkpoint", crash_if_published)
    key = str(uuid4())
    try:
        store.mutate(
            "update",
            {"credential": "5678"},
            connection_id=first.body["connection_id"],
            expected_etag=before.etag,
            idempotency_key=key,
            actor_context=ACTOR,
        )
    except (Crash, ConnectionStoreUnavailable):
        pass
    assert not published, "forward retry consumed the only compensation generation"
    assert json.loads(workspace_path.read_text())["workspace_generation"] == maximum - 1
    monkeypatch.setattr(module, "_checkpoint", lambda _name: None)
    result = ServiceConnectionStore(tmp_path).recover()
    assert result.workspace_version.generation == maximum
    assert result.epoch == 2
    assert result.connections[0].secret_version.generation == 3
    assert json.loads(workspace_path.read_text())["unrelated"] == "retained"
    assert ServiceConnectionStore(tmp_path).recover() == result
    assert (
        store.mutate(
            "update",
            {"credential": "5678"},
            connection_id=first.body["connection_id"],
            expected_etag=before.etag,
            idempotency_key=key,
            actor_context=ACTOR,
        ).status
        == 503
    )


def test_missing_preexisting_anchor_still_blocks_recovery(tmp_path, monkeypatch):
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
        if name == "prepared_journal":
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
    (tmp_path / "service-connections-state" / "workspace-anchor.json").unlink()
    journal = tmp_path / "service-connections-state" / "transaction.json"
    evidence = journal.read_bytes()
    monkeypatch.setattr(module, "_checkpoint", lambda _name: None)
    with pytest.raises(ConnectionStoreUnavailable):
        store.recover()
    assert journal.read_bytes() == evidence


@pytest.mark.parametrize("corruption", ["generation", "presence", "digest", "digest_type"])
def test_malformed_compensation_is_rejected_before_effects(tmp_path, monkeypatch, corruption):
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
        if name == "secret_install":
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

    def crash_recovery(name):
        if name == "recovery_decision":
            raise Crash()

    monkeypatch.setattr(module, "_checkpoint", crash_recovery)
    with pytest.raises(Crash):
        store.recover()
    journal_path = tmp_path / "service-connections-state" / "transaction.json"
    journal = json.loads(journal_path.read_text())
    if corruption == "generation":
        journal["recovery"]["after_binding"]["generation"] = 2
    elif corruption == "presence":
        journal["recovery"]["after_binding"]["present"] = False
    else:
        journal["recovery"]["after_digest"] = "0" * 64 if corruption == "digest" else False
    journal_path.write_text(json.dumps(journal))
    secret = tmp_path / "secrets" / "services" / first.body["connection_id"] / "credential"
    workspace = tmp_path / "workspace.json"
    before = (journal_path.read_bytes(), secret.read_bytes(), workspace.read_bytes())
    monkeypatch.setattr(module, "_checkpoint", lambda _name: None)
    with pytest.raises(ConnectionStoreUnavailable):
        store.recover()
    assert (journal_path.read_bytes(), secret.read_bytes(), workspace.read_bytes()) == before


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
