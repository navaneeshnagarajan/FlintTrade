"""Observable persistence and admission contracts for inert connections."""

import json
import shutil
from uuid import uuid4

import pytest

from flinttrade_core.service_connection_store import (
    ConnectionActorContext,
    ConnectionIdempotencyConflict,
    ConnectionRevisionConflict,
    ConnectionRevisionRequired,
    ConnectionStoreUnavailable,
    ServiceConnectionStore,
)
from flinttrade_core.workspace_migrations import compare_and_swap_workspace, read_workspace_snapshot


ACTOR = ConnectionActorContext("operator", "session:" + "a" * 64)
PAYLOAD = {"provider_id": "llm:openai", "label": "Primary", "auth_mode": "api_key", "credential": "1234"}


def test_absent_snapshot_does_not_eagerly_create_workspace(tmp_path):
    root = tmp_path / "workspace"
    store = ServiceConnectionStore(root)
    assert not root.exists()
    snapshot = store.read_snapshot()
    assert snapshot is not None, "an absent collection still has an explicit snapshot"
    assert snapshot.connections == ()
    assert snapshot.epoch == 0
    assert snapshot.workspace_version is None
    assert snapshot.etag.startswith('"') and snapshot.etag.endswith('"')
    assert ServiceConnectionStore(root).read_snapshot() == snapshot
    assert not (root / "workspace.json").exists()


def test_first_create_and_same_key_retry_survive_restart(tmp_path):
    store = ServiceConnectionStore(tmp_path)
    before = store.read_snapshot()
    assert before is not None, "first admission needs a collection revision"
    key = str(uuid4())
    result = store.mutate(
        "create", PAYLOAD, connection_id=None, expected_etag=before.etag, idempotency_key=key, actor_context=ACTOR
    )
    assert result is not None, "durable mutation must return its redacted receipt"
    reopened = ServiceConnectionStore(tmp_path)
    after = reopened.read_snapshot()
    assert after.epoch == 1
    assert len(after.connections) == 1
    assert after.connections[0].credential_configured is True
    assert result.status == 201
    assert result.body["connection_id"] == str(after.connections[0].connection_id)
    assert (
        reopened.mutate(
            "create", PAYLOAD, connection_id=None, expected_etag=before.etag, idempotency_key=key, actor_context=ACTOR
        )
        == result
    )
    assert reopened.read_snapshot() == after


def test_same_key_retry_normalises_only_outer_etag_ows(tmp_path):
    store = ServiceConnectionStore(tmp_path)
    before = store.read_snapshot()
    key = str(uuid4())
    result = store.mutate(
        "create",
        PAYLOAD,
        connection_id=None,
        expected_etag=before.etag,
        idempotency_key=key,
        actor_context=ACTOR,
    )
    reopened = ServiceConnectionStore(tmp_path)

    replay = reopened.mutate(
        "create",
        PAYLOAD,
        connection_id=None,
        expected_etag=f" \t{before.etag}\t ",
        idempotency_key=key,
        actor_context=ACTOR,
    )

    assert replay == result
    assert reopened.read_snapshot().epoch == 1


def create(store, **changes):
    return store.mutate(
        "create",
        {**PAYLOAD, **changes},
        connection_id=None,
        expected_etag=store.read_snapshot().etag,
        idempotency_key=str(uuid4()),
        actor_context=ACTOR,
    )


def test_rotate_preserve_clear_delete_and_same_provider_records(tmp_path):
    store = ServiceConnectionStore(tmp_path)
    first = create(store)
    create(store, label="Second")
    identifier = first.body["connection_id"]
    original = next(item for item in store.read_snapshot().connections if str(item.connection_id) == identifier)
    for payload, generation, present in [
        ({}, 1, True),
        ({"credential": "1234"}, 2, True),
        ({"clear_credential": True}, 3, False),
    ]:
        before = store.read_snapshot()
        store.mutate(
            "update",
            payload,
            connection_id=identifier,
            expected_etag=before.etag,
            idempotency_key=str(uuid4()),
            actor_context=ACTOR,
        )
        after = store.read_snapshot()
        record = next(item for item in after.connections if str(item.connection_id) == identifier)
        assert after.epoch == before.epoch + 1
        assert record.secret_version.generation == generation
        assert record.secret_version.binding_id == original.secret_version.binding_id
        assert record.credential_configured is present
    before = store.read_snapshot()
    store.mutate(
        "delete",
        {},
        connection_id=identifier,
        expected_etag=before.etag,
        idempotency_key=str(uuid4()),
        actor_context=ACTOR,
    )
    after = ServiceConnectionStore(tmp_path).read_snapshot()
    assert len(after.connections) == 1 and after.epoch == 6
    raw = json.loads((tmp_path / "workspace.json").read_text())
    tombstone = raw["services"]["_connection_store"]["bindings"][identifier]
    assert tombstone["generation"] == 4 and tombstone["present"] is False


def test_unrelated_workspace_write_preserves_collection_revision(tmp_path):
    store = ServiceConnectionStore(tmp_path)
    create(store)
    before = store.read_snapshot()
    compare_and_swap_workspace(tmp_path, before.workspace_version, lambda config: config.update(extra={"value": 7}))
    current = store.read_snapshot()
    assert current.etag == before.etag
    assert current.workspace_version.generation == before.workspace_version.generation + 1
    create(store, label="After unrelated edit")
    assert read_workspace_snapshot(tmp_path).as_dict()["extra"] == {"value": 7}


@pytest.mark.parametrize("change", [{"credential": "5678"}, {"label": "Changed"}])
def test_same_key_changed_request_conflicts_without_state_change(tmp_path, change):
    store = ServiceConnectionStore(tmp_path)
    etag, key = store.read_snapshot().etag, str(uuid4())
    store.mutate("create", PAYLOAD, connection_id=None, expected_etag=etag, idempotency_key=key, actor_context=ACTOR)
    before = store.read_snapshot()
    with pytest.raises(ConnectionIdempotencyConflict):
        store.mutate(
            "create",
            {**PAYLOAD, **change},
            connection_id=None,
            expected_etag=etag,
            idempotency_key=key,
            actor_context=ACTOR,
        )
    assert store.read_snapshot() == before


def test_stale_and_missing_revisions_do_not_mutate(tmp_path):
    store = ServiceConnectionStore(tmp_path)
    stale = store.read_snapshot().etag
    create(store)
    before = store.read_snapshot()
    for revision, error in [(stale, ConnectionRevisionConflict), (None, ConnectionRevisionRequired)]:
        with pytest.raises(error):
            store.mutate(
                "create",
                PAYLOAD,
                connection_id=None,
                expected_etag=revision,
                idempotency_key=str(uuid4()),
                actor_context=ACTOR,
            )
        assert store.read_snapshot() == before


@pytest.mark.parametrize("foreign_tag", ['""', '"short"', '"comma,slash\\value"'])
def test_valid_foreign_width_strong_tags_are_stale_not_malformed(tmp_path, foreign_tag):
    """Catch digest-width coupling that turns valid strong tags into client-shape errors."""
    store = ServiceConnectionStore(tmp_path)
    before = store.read_snapshot()
    with pytest.raises(ConnectionRevisionConflict):
        store.mutate(
            "create",
            PAYLOAD,
            connection_id=None,
            expected_etag=foreign_tag,
            idempotency_key=str(uuid4()),
            actor_context=ACTOR,
        )
    assert store.read_snapshot() == before


@pytest.mark.parametrize("kind", ["identity", "rollback"])
def test_independent_anchor_rejects_workspace_copy_or_rollback(tmp_path, kind):
    store = ServiceConnectionStore(tmp_path)
    create(store)
    prior = (tmp_path / "workspace.json").read_text()
    if kind == "identity":
        config = json.loads(prior)
        config["workspace_instance_id"] = str(uuid4())
        (tmp_path / "workspace.json").write_text(json.dumps(config))
    else:
        create(store, label="Second")
        (tmp_path / "workspace.json").write_text(prior)
    with pytest.raises(ConnectionStoreUnavailable):
        ServiceConnectionStore(tmp_path).read_snapshot()


def test_copied_secret_root_is_rejected(tmp_path):
    store = ServiceConnectionStore(tmp_path)
    create(store)
    secret_root = tmp_path / "secrets" / "services"
    secret_root.rename(tmp_path / "retained-original")
    shutil.copytree(tmp_path / "retained-original", secret_root)
    with pytest.raises(ConnectionStoreUnavailable):
        store.read_snapshot()


def test_receipt_corruption_cannot_escape_through_replay(tmp_path):
    store = ServiceConnectionStore(tmp_path)
    etag, key = store.read_snapshot().etag, str(uuid4())
    store.mutate("create", PAYLOAD, connection_id=None, expected_etag=etag, idempotency_key=key, actor_context=ACTOR)
    receipt_path = tmp_path / "service-connections-state" / "receipts" / f"{key}.json"
    receipt = json.loads(receipt_path.read_text())
    receipt["result"]["body"] = {"credential": "1234"}
    receipt_path.write_text(json.dumps(receipt))
    with pytest.raises(ConnectionStoreUnavailable):
        store.mutate(
            "create", PAYLOAD, connection_id=None, expected_etag=etag, idempotency_key=key, actor_context=ACTOR
        )


def test_throwing_audit_sink_leaves_pending_events_without_reapplying(tmp_path):
    def fail(event):
        raise RuntimeError("private sink error")

    store = ServiceConnectionStore(tmp_path, audit_sink=fail)
    result = create(store)
    assert store.read_snapshot().epoch == 1
    events = list((tmp_path / "service-connections-state" / "outbox").glob("*.json"))
    assert len(events) == 2
    seen = {}

    def accept(event):
        seen[event.event_id] = event

    recovered = ServiceConnectionStore(tmp_path, audit_sink=accept).recover()
    assert recovered.epoch == 1 and recovered.etag == result.etag
    assert len(seen) == 2
    assert list((tmp_path / "service-connections-state" / "outbox").iterdir()) == []


def test_utf8_credential_limit_counts_bytes_not_json_escape_expansion(tmp_path):
    store = ServiceConnectionStore(tmp_path)
    result = create(store, credential="é" * 8192)
    assert result.status == 201
    before = store.read_snapshot()
    with pytest.raises(ValueError):
        create(store, credential="é" * 8193)
    assert store.read_snapshot() == before


@pytest.mark.parametrize("kind", ["symlink", "hardlink", "missing", "mac", "generation_bool", "foreign_binding"])
def test_bad_live_secret_fails_only_connection_authority(tmp_path, kind):
    store = ServiceConnectionStore(tmp_path)
    result = create(store)
    path = tmp_path / "secrets" / "services" / result.body["connection_id"] / "credential"
    if kind == "missing":
        path.unlink()
    elif kind == "symlink":
        original = path.with_name("retained")
        path.rename(original)
        path.symlink_to(original)
    elif kind == "hardlink":
        import os

        os.link(path, path.with_name("retained-link"))
    else:
        value = json.loads(path.read_text())
        if kind == "mac":
            value["mac"] = "0" * 64
        elif kind == "generation_bool":
            value["version"]["generation"] = True
        else:
            value["version"]["binding_id"] = str(uuid4())
        path.write_text(json.dumps(value))
    with pytest.raises(ConnectionStoreUnavailable):
        store.read_snapshot()
    # Independent workspace reads continue to serve unrelated settings.
    assert read_workspace_snapshot(tmp_path).version is not None


@pytest.mark.parametrize(
    "changes",
    [
        {"credential": ""},
        {"credential": None},
        {"clear_credential": False},
        {"clear_credential": True, "credential": "x"},
        {"provider_id": "unknown"},
        {"connection_id": "caller-owned"},
    ],
)
def test_invalid_mutations_do_not_publish_domain_state(tmp_path, changes):
    store = ServiceConnectionStore(tmp_path)
    before = store.read_snapshot()
    with pytest.raises(ValueError):
        create(store, **changes)
    assert store.read_snapshot() == before
    assert not (tmp_path / "workspace.json").exists()


def test_same_key_is_bound_to_actor_and_session(tmp_path):
    store = ServiceConnectionStore(tmp_path)
    etag, key = store.read_snapshot().etag, str(uuid4())
    store.mutate("create", PAYLOAD, connection_id=None, expected_etag=etag, idempotency_key=key, actor_context=ACTOR)
    for actor in [
        ConnectionActorContext("other", ACTOR.session_binding),
        ConnectionActorContext("operator", "session:" + "b" * 64),
    ]:
        with pytest.raises(ConnectionIdempotencyConflict):
            store.mutate(
                "create", PAYLOAD, connection_id=None, expected_etag=etag, idempotency_key=key, actor_context=actor
            )


def test_workspace_lock_order_and_audit_sink_runs_outside_lock(tmp_path, monkeypatch):
    from filelock import Timeout
    from flinttrade_core import service_connection_store as module
    from flinttrade_core.owner_file_lock import OwnerSafeFileLock

    real_read, real_cas = module.read_workspace_snapshot, module.compare_and_swap_workspace
    lock_path = tmp_path / "service-connections-state" / "service.lock"
    observations = []

    def read(path):
        with pytest.raises(Timeout):
            with OwnerSafeFileLock(lock_path, timeout=0):
                pass
        observations.append("read")
        return real_read(path)

    def cas(path, version, updater):
        with pytest.raises(Timeout):
            with OwnerSafeFileLock(lock_path, timeout=0):
                pass
        observations.append("cas")
        return real_cas(path, version, updater)

    def sink(event):
        with OwnerSafeFileLock(lock_path, timeout=0):
            observations.append("sink")

    monkeypatch.setattr(module, "read_workspace_snapshot", read)
    monkeypatch.setattr(module, "compare_and_swap_workspace", cas)
    create(ServiceConnectionStore(tmp_path, audit_sink=sink))
    assert "read" in observations and "cas" in observations and "sink" in observations


def test_unrelated_cas_collision_retries_without_losing_other_fields(tmp_path, monkeypatch):
    from flinttrade_core import service_connection_store as module

    store = ServiceConnectionStore(tmp_path)
    first = create(store)
    real = module.compare_and_swap_workspace
    attempts = 0

    def collide(path, version, updater):
        nonlocal attempts
        attempts += 1
        if attempts == 1:
            real(path, version, lambda cfg: cfg.update(unrelated="retained"))
        return real(path, version, updater)

    monkeypatch.setattr(module, "compare_and_swap_workspace", collide)
    store.mutate(
        "update",
        {},
        connection_id=first.body["connection_id"],
        expected_etag=first.etag,
        idempotency_key=str(uuid4()),
        actor_context=ACTOR,
    )
    assert attempts == 2
    assert read_workspace_snapshot(tmp_path).as_dict()["unrelated"] == "retained"
    assert store.read_snapshot().epoch == 2


def test_unknown_control_state_without_bootstrap_is_not_an_absent_store(tmp_path):
    store = ServiceConnectionStore(tmp_path)
    store.read_snapshot()
    (tmp_path / "service-connections-state" / "unknown").write_text("retained")
    with pytest.raises(ConnectionStoreUnavailable):
        store.read_snapshot()


def test_audit_export_is_bounded_and_repeated_reads_drain_pending(tmp_path):
    store = ServiceConnectionStore(tmp_path)
    for index in range(17):
        create(store, label=f"Connection {index}")
    events = []
    exporting = ServiceConnectionStore(tmp_path, audit_sink=events.append)
    exporting.read_snapshot()
    assert len(events) == 32
    exporting.read_snapshot()
    assert len(events) == 34 and len({event.event_id for event in events}) == 34


def test_no_auth_profiles_reject_credential_instructions_and_remain_inert(tmp_path, monkeypatch):
    import socket
    import subprocess

    def forbidden(*args, **kwargs):
        pytest.fail("inert connection store invoked a runtime")

    monkeypatch.setattr(socket, "socket", forbidden)
    monkeypatch.setattr(subprocess, "Popen", forbidden)
    store = ServiceConnectionStore(tmp_path)
    payload = {"provider_id": "llm:ollama", "label": "Local"}
    for instruction in [{"credential": "1234"}, {"clear_credential": True}]:
        with pytest.raises(ValueError):
            store.mutate(
                "create",
                {**payload, **instruction},
                connection_id=None,
                expected_etag=store.read_snapshot().etag,
                idempotency_key=str(uuid4()),
                actor_context=ACTOR,
            )
    result = store.mutate(
        "create",
        payload,
        connection_id=None,
        expected_etag=store.read_snapshot().etag,
        idempotency_key=str(uuid4()),
        actor_context=ACTOR,
    )
    assert result.body["credential_configured"] is False
    assert store.read_snapshot().connections[0].secret_version is None


def test_pre_domain_audit_never_invents_a_reference_or_accepts_raw_urls():
    from flinttrade_core.service_connection_audit import RouteMutationAttempt

    attempt = RouteMutationAttempt(
        "/ft-api/v1/services/connections", "POST", "authenticated", "rejected", actor="operator"
    )
    assert attempt.connection_ref is None
    with pytest.raises(ValueError):
        RouteMutationAttempt("https://user:password@example.invalid", "POST", "authenticated", "failed")
    with pytest.raises(ValueError):
        ConnectionActorContext("operator", "raw-jti")


def test_directory_pin_retains_birth_representation_and_large_object_identity():
    from types import SimpleNamespace
    from flinttrade_core.service_connection_transactions import directory_pin

    original = SimpleNamespace(st_dev=3, st_ino=1 << 100, st_birthtime=1.25)
    pin = directory_pin(original)
    assert pin == {"device": 3, "object": 1 << 100, "birth_kind": "float", "birth": "0x1.4000000000000p+0"}
    richer = SimpleNamespace(st_dev=3, st_ino=1 << 100, st_birthtime=1.25, st_birthtime_ns=1250000000)
    assert directory_pin(richer, pin) == pin
    with pytest.raises(ValueError):
        directory_pin(SimpleNamespace(st_dev=3, st_ino=0))


def test_missing_detailed_receipt_never_turns_an_old_key_into_a_new_create(tmp_path):
    store = ServiceConnectionStore(tmp_path)
    etag, key = store.read_snapshot().etag, str(uuid4())
    store.mutate("create", PAYLOAD, connection_id=None, expected_etag=etag, idempotency_key=key, actor_context=ACTOR)
    before = (tmp_path / "workspace.json").read_bytes()
    (tmp_path / "service-connections-state" / "receipts" / f"{key}.json").unlink()
    with pytest.raises(ConnectionStoreUnavailable):
        store.mutate(
            "create", PAYLOAD, connection_id=None, expected_etag=etag, idempotency_key=key, actor_context=ACTOR
        )
    with pytest.raises(ConnectionIdempotencyConflict):
        store.mutate(
            "create",
            PAYLOAD,
            connection_id=None,
            expected_etag=store.read_snapshot().etag,
            idempotency_key=key,
            actor_context=ACTOR,
        )
    assert (tmp_path / "workspace.json").read_bytes() == before


def test_connection_count_ceiling_rejects_without_publishing(tmp_path):
    store = ServiceConnectionStore(tmp_path)
    for index in range(128):
        store.mutate(
            "create",
            {"provider_id": "llm:ollama", "label": f"Connection {index}"},
            connection_id=None,
            expected_etag=store.read_snapshot().etag,
            idempotency_key=str(uuid4()),
            actor_context=ACTOR,
        )
    before = store.read_snapshot()
    with pytest.raises(ValueError):
        store.mutate(
            "create",
            {"provider_id": "llm:ollama", "label": "Excess"},
            connection_id=None,
            expected_etag=before.etag,
            idempotency_key=str(uuid4()),
            actor_context=ACTOR,
        )
    assert store.read_snapshot() == before


def test_bounded_cas_retry_exhaustion_preserves_recoverable_receipt(tmp_path, monkeypatch):
    from flinttrade_core import service_connection_store as module

    store = ServiceConnectionStore(tmp_path)
    first = create(store)
    real = module.compare_and_swap_workspace
    attempts = 0

    def collide(path, version, updater):
        nonlocal attempts
        attempts += 1
        real(path, version, lambda config: config.update(noise=attempts))
        return real(path, version, updater)

    monkeypatch.setattr(module, "compare_and_swap_workspace", collide)
    key = str(uuid4())
    with pytest.raises(ConnectionStoreUnavailable):
        store.mutate(
            "update",
            {},
            connection_id=first.body["connection_id"],
            expected_etag=first.etag,
            idempotency_key=key,
            actor_context=ACTOR,
        )
    assert attempts == 8
    monkeypatch.setattr(module, "compare_and_swap_workspace", real)
    assert store.recover().epoch == 1
    result = store.mutate(
        "update",
        {},
        connection_id=first.body["connection_id"],
        expected_etag=first.etag,
        idempotency_key=key,
        actor_context=ACTOR,
    )
    assert result.status == 503


def test_epoch_exhaustion_refuses_before_secret_install(tmp_path):
    from flinttrade_core import service_connection_store as module

    store = ServiceConnectionStore(tmp_path)
    first = create(store)
    workspace = read_workspace_snapshot(tmp_path)
    maximum = (1 << 63) - 1
    high = compare_and_swap_workspace(
        tmp_path, workspace.version, lambda config: config["services"].update(connection_epoch=maximum - 1)
    )
    # Build a consistent high-counter fixture; the assertion concerns admission,
    # not the independent anchor's digest algorithm.
    path = tmp_path / "service-connections-state" / "workspace-anchor.json"
    anchor = json.loads(path.read_text())
    anchor.update(
        epoch=maximum - 1, generation=high.version.generation, domain_digest=module._domain_digest(high.as_dict())
    )
    path.write_text(json.dumps(anchor))
    before = store.read_snapshot()
    secret = tmp_path / "secrets" / "services" / first.body["connection_id"] / "credential"
    ciphertext = secret.read_bytes()
    with pytest.raises(ConnectionStoreUnavailable):
        store.mutate(
            "update",
            {"credential": "5678"},
            connection_id=first.body["connection_id"],
            expected_etag=before.etag,
            idempotency_key=str(uuid4()),
            actor_context=ACTOR,
        )
    assert secret.read_bytes() == ciphertext
    assert store.read_snapshot() == before


@pytest.mark.parametrize(
    "case,reason", [("input", "invalid_request"), ("missing", "not_found"), ("capacity", "connection_limit")]
)
def test_mutation_client_rejection_is_typed_closed_and_safe(tmp_path, monkeypatch, case, reason):
    from flinttrade_core import service_connection_store as module

    store = ServiceConnectionStore(tmp_path)
    before = store.read_snapshot()
    if case == "capacity":
        monkeypatch.setattr(module, "MAX_CONNECTIONS", 0)
    with pytest.raises(ValueError) as caught:
        store.mutate(
            "update" if case == "missing" else "create",
            {} if case == "missing" else {**PAYLOAD, "label": "" if case == "input" else "Local"},
            connection_id=str(uuid4()) if case == "missing" else None,
            expected_etag=before.etag,
            idempotency_key=str(uuid4()),
            actor_context=ACTOR,
        )
    assert isinstance(caught.value, getattr(module, "ConnectionMutationRejected", ()))
    assert caught.value.reason == reason
    assert str(caught.value) == reason
    assert repr(caught.value) == f"ConnectionMutationRejected({reason!r})"
    assert caught.value.__cause__ is None
    with pytest.raises(AttributeError):
        caught.value.reason = "private input"
    with pytest.raises(AttributeError):
        del caught.value._reason
    caught.value.__dict__["_reason"] = "private input"
    caught.value.args = ("private input",)
    assert str(caught.value) == reason
    assert repr(caught.value) == f"ConnectionMutationRejected({reason!r})"
    assert not (tmp_path / "workspace.json").exists()


@pytest.mark.parametrize("kind", ["workspace", "receipt", "secret", "counter", "uuid", "clock"])
def test_mutation_authority_failures_are_scoped_unavailable(tmp_path, monkeypatch, kind):
    from flinttrade_core import service_connection_store as module
    from flinttrade_core import service_connections as contracts
    from datetime import datetime
    from uuid import UUID

    store = ServiceConnectionStore(tmp_path)
    first = create(store)
    etag, key = store.read_snapshot().etag, str(uuid4())
    payload = {"label": "Updated"}
    if kind == "workspace":
        path = tmp_path / "workspace.json"
        value = json.loads(path.read_text())
        value["services"]["connections"][0]["label"] = ""
        path.write_text(json.dumps(value))
    elif kind == "receipt":
        store.mutate(
            "update",
            payload,
            connection_id=first.body["connection_id"],
            expected_etag=etag,
            idempotency_key=key,
            actor_context=ACTOR,
        )
        path = tmp_path / "service-connections-state" / "receipts" / f"{key}.json"
        path.write_text('{"private": "fixture diagnostic"}')
    elif kind == "secret":
        path = tmp_path / "secrets" / "services" / first.body["connection_id"] / "credential"
        path.write_text('{"private": "fixture diagnostic"}')
    elif kind == "counter":
        path = tmp_path / "workspace.json"
        value = json.loads(path.read_text())
        value["workspace_generation"] = (1 << 63) - 1
        path.write_text(json.dumps(value))
    elif kind == "uuid":
        monkeypatch.setattr(
            module,
            "create_service_connection",
            lambda value: contracts.create_service_connection(value, uuid_factory=lambda: UUID(int=0)),
        )
    else:
        monkeypatch.setattr(
            module,
            "update_service_connection",
            lambda current, value: contracts.update_service_connection(
                current, value, clock_factory=lambda: datetime(2026, 9, 5)
            ),
        )
    with pytest.raises(ConnectionStoreUnavailable) as caught:
        store.mutate(
            "create" if kind == "uuid" else "update",
            PAYLOAD if kind == "uuid" else payload,
            connection_id=None if kind == "uuid" else first.body["connection_id"],
            expected_etag=etag,
            idempotency_key=key,
            actor_context=ACTOR,
        )
    assert str(caught.value) == "service_connection_store_unavailable"
    assert "fixture" not in repr(caught.value)
    assert caught.value.__cause__ is None


def test_server_uuid_collision_cannot_replace_an_existing_connection(tmp_path, monkeypatch):
    from flinttrade_core import service_connection_store as module

    store = ServiceConnectionStore(tmp_path)
    create(store)
    before = store.read_snapshot()
    monkeypatch.setattr(module, "create_service_connection", lambda _payload: before.connections[0])
    with pytest.raises(ConnectionStoreUnavailable):
        create(store, label="Colliding create")
    assert store.read_snapshot() == before
