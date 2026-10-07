"""Continuous runtime custody, using synthetic payloads and real backend leases."""

import asyncio
import importlib.util
import pickle
import threading
import time
from concurrent.futures import Future
from uuid import uuid4

from flask import Flask
import pytest

from flinttrade_core.account_mutation_contracts import RegistryCapabilityError, RegistrySessionUnavailable
from flinttrade_core.broker_identity import BrokerSelector
from flinttrade_core.secure_file import harden_directory
from flinttrade_core.workspace_migrations import broker_workspace_version, compare_and_swap_workspace
from flinttrade_gateway.brokers._base import Session, run_blocking_sdk_call
from flinttrade_gateway.credentials import CredentialStore
from flinttrade_gateway.registry import ManagedSessionAuthority, create_owned_registry

pytestmark = pytest.mark.unit
SELECTOR = BrokerSelector("dhan", "Synthetic")


@pytest.fixture
def lifecycle_api():
    # A missing foundation is a behavioural RED, rather than a collection error.
    if importlib.util.find_spec("flinttrade_core.broker_account_lifecycle") is None:
        from types import SimpleNamespace

        return SimpleNamespace(
            BrokerAccountLifecycleOwner=lambda *_args, **_kwargs: pytest.fail("runtime custody missing")
        )
    from flinttrade_core import broker_account_lifecycle

    return broker_account_lifecycle


@pytest.fixture
def owner_factory(lifecycle_api, tmp_path, monkeypatch, backend_lease_factory):
    monkeypatch.setenv("FLINTTRADE_WORKSPACE_DIR", str(tmp_path))
    proof = backend_lease_factory()
    owners = []

    def make(*, retire=lambda timeout: True, lock=None):
        owner = lifecycle_api.BrokerAccountLifecycleOwner(
            tmp_path, proof, retire_generations=retire, rebuild_lock=lock or threading.RLock()
        )
        owners.append(owner)
        return owner

    yield make, proof
    for owner in owners:
        owner.close_and_drain(1.0)


@pytest.fixture
def native_authority(tmp_path):
    path = tmp_path / "stores"
    path.mkdir()
    harden_directory(path)
    workspace = compare_and_swap_workspace(path, None, lambda config: None)
    store = CredentialStore(path / "vault.db", "synthetic-password")
    store.put_credentials(
        SELECTOR, "dhan", "Synthetic", {"token": "synthetic"}, expected=store.selector_state(SELECTOR).version
    )
    yield ManagedSessionAuthority(
        store.selector_state(SELECTOR).version, workspace.version, broker_workspace_version(workspace)
    )
    store.close()


def _prepare(registry, owner, authority, session=None):
    session = session or Session("synthetic-secret", time.time() + 3600, "broker-reported", "dhan")
    receipt = owner.prepare_session_candidate(
        SELECTOR,
        session,
        expected_registry=registry.snapshot_selector(SELECTOR),
        authority=authority,
        broker="dhan",
        label="Synthetic",
    )
    return receipt, session


def test_one_owner_per_live_proof_workspace(owner_factory):
    make, _ = owner_factory
    owner = make()
    with pytest.raises(RuntimeError, match="account_lifecycle_owner_exists"):
        make()
    assert owner.close_and_drain(0.0)
    assert make().close_and_drain(0.0)


def test_lane_is_exact_replay_and_opaque(owner_factory):
    make, _ = owner_factory
    owner = make()
    operation = uuid4()
    lease = owner.begin(operation, SELECTOR)
    assert owner.begin(operation, SELECTOR) is lease
    with pytest.raises(RuntimeError, match="account_mutation_busy"):
        owner.begin(uuid4(), SELECTOR)
    with pytest.raises(RuntimeError):
        owner.begin(operation, BrokerSelector("dhan", "Other"))
    assert "Synthetic" not in repr(lease)
    with pytest.raises(TypeError):
        pickle.dumps(lease)
    assert owner.settle(lease)
    with pytest.raises(RuntimeError):
        owner.publish_if_current(lease, lambda: pytest.fail("settled lease published"))


def test_backend_proof_loss_prevents_publication(owner_factory):
    make, proof = owner_factory
    owner = make()
    lease = owner.begin(uuid4(), SELECTOR)
    proof.revoke()
    with pytest.raises(RuntimeError, match="backend_lease_unavailable"):
        owner.publish_if_current(lease, lambda: pytest.fail("revoked backend published"))
    owner.abandon(lease)
    assert owner.settle(lease)


def test_timeout_retains_real_worker_and_lane(owner_factory):
    make, _ = owner_factory
    owner = make()
    lease = owner.begin(uuid4(), SELECTOR)
    release = threading.Event()
    worker = owner.run_worker(lease, lambda: release.wait(1.0))
    try:
        assert owner.settle(lease) is False
        owner.abandon(lease)
        assert owner.close_and_drain(0.01) is False
        assert owner.snapshot().workers == 1
        with pytest.raises(RuntimeError):
            owner.begin(uuid4(), SELECTOR)
    finally:
        release.set()
        worker.result(1.0)
    assert owner.close_and_drain(1.0)
    assert owner.snapshot().workers == 0


@pytest.mark.asyncio
async def test_cancelled_async_wrapper_does_not_complete_real_future(owner_factory):
    make, _ = owner_factory
    owner = make()
    lease = owner.begin(uuid4(), SELECTOR)
    release = threading.Event()
    worker = owner.run_worker(lease, lambda: release.wait(1.0))
    waiter = asyncio.create_task(owner.wait_worker(lease, worker))
    await asyncio.sleep(0)
    waiter.cancel()
    with pytest.raises(asyncio.CancelledError):
        await waiter
    try:
        assert not worker.done() and not worker.cancelled()
        assert owner.snapshot().workers == 1
        assert owner.settle(lease) is False
        with pytest.raises(RuntimeError):
            owner.publish_if_current(lease, lambda: pytest.fail("cancelled operation published"))
    finally:
        release.set()
        await asyncio.to_thread(worker.result, 1.0)
    assert owner.settle(lease)


@pytest.mark.asyncio
async def test_existing_sdk_shield_keeps_custody_until_worker_exits(owner_factory):
    make, _ = owner_factory
    owner = make()
    lease = owner.begin(uuid4(), SELECTOR)
    entered = threading.Event()
    release = threading.Event()

    def sdk():
        entered.set()
        release.wait(1.0)
        return object()

    worker = owner.run_worker(lease, lambda: asyncio.run(run_blocking_sdk_call(sdk)))
    await asyncio.to_thread(entered.wait, 1.0)
    waiter = asyncio.create_task(owner.wait_worker(lease, worker, timeout=0.01))
    with pytest.raises(TimeoutError):
        await waiter
    try:
        assert owner.snapshot().workers == 1
        assert not worker.done()
        assert owner.settle(lease) is False
    finally:
        release.set()
        await asyncio.to_thread(worker.result, 1.0)
    assert owner.settle(lease)


def test_late_candidate_is_retained_once_and_cleaned_explicitly(owner_factory):
    make, _ = owner_factory
    owner = make()
    lease = owner.begin(uuid4(), SELECTOR)
    release = threading.Event()
    candidate = object()
    cleaned = []

    def retain(value):
        first = owner.retain_candidate(lease, value, cleaned.append)
        assert owner.retain_candidate(lease, value, cleaned.append) is first

    worker = owner.run_worker(lease, lambda: (release.wait(1.0), candidate)[1], accept_result=retain)
    owner.abandon(lease)
    try:
        assert owner.close_and_drain(0.01) is False
    finally:
        release.set()
        worker.result(1.0)
    assert owner.close_and_drain(1.0)
    assert cleaned == [candidate]


def test_cleanup_failure_and_repeated_shutdown_retain_exact_ticket(owner_factory):
    make, _ = owner_factory
    owner = make()
    lease = owner.begin(uuid4(), SELECTOR)
    candidate = object()
    calls = []
    release = threading.Event()

    def cleanup(value):
        calls.append(value)
        if len(calls) == 1:
            raise RuntimeError("synthetic cleanup failure")
        release.wait(1.0)

    ticket = owner.retain_candidate(lease, candidate, cleanup)
    assert "object at" not in repr(ticket)
    with pytest.raises(TypeError):
        pickle.dumps(ticket)
    owner.abandon(lease)
    assert owner.close_and_drain(0.01) is False
    assert owner.snapshot().cleanup_pending == 1
    assert owner.close_and_drain(0.01) is False
    assert owner.close_and_drain(0.01) is False
    assert len(calls) == 2
    release.set()
    assert owner.close_and_drain(1.0)
    assert calls == [candidate, candidate]


def test_unsupported_cleanup_is_quarantined_without_reflection(owner_factory):
    make, _ = owner_factory
    owner = make()
    lease = owner.begin(uuid4(), SELECTOR)

    class Candidate:
        def close(self):
            pytest.fail("generic close must not run")

        extra = {"client": object()}

    owner.retain_candidate(lease, Candidate(), None)
    owner.abandon(lease)
    assert owner.close_and_drain(0.0) is False
    assert owner.snapshot().quarantined == 1


def test_registry_rejects_raw_managed_session_reuse(native_authority):
    registry, publication = create_owned_registry()
    receipt, session = _prepare(registry, publication, native_authority)
    with pytest.raises(RegistrySessionUnavailable):
        _prepare(registry, publication, native_authority, session)
    published = publication.publish_prepared_candidate(receipt, current_authority=native_authority)
    with pytest.raises(RegistrySessionUnavailable):
        _prepare(registry, publication, native_authority, session)
    retired = publication.remove_session_for_exact(SELECTOR, expected_registry=published.version.registry_version)
    with pytest.raises(RegistrySessionUnavailable):
        _prepare(registry, publication, native_authority, session)
    payload = publication.claim_retired_candidate(retired.retired)
    with pytest.raises(RegistrySessionUnavailable):
        _prepare(registry, publication, native_authority, session)
    publication.release_retired_candidate(payload)
    assert _prepare(registry, publication, native_authority, session)[0]


def test_registry_retirement_transfer_is_exact_and_cleanup_releases_reservation(owner_factory, native_authority):
    make, _ = owner_factory
    owner = make()
    lease = owner.begin(uuid4(), SELECTOR)
    registry, publication = create_owned_registry()
    prepared, session = _prepare(registry, publication, native_authority)
    receipt = publication.abandon_prepared_candidate(prepared)
    cleaned = []
    ticket = owner.retain_retirement(
        lease, publication, receipt, cleanup=lambda payload: cleaned.append(payload.session)
    )
    assert owner.retain_retirement(lease, publication, receipt) is ticket
    with pytest.raises(RegistryCapabilityError):
        publication.claim_retired_candidate(receipt)
    owner.abandon(lease)
    assert owner.close_and_drain(1.0)
    assert cleaned == [session]
    assert _prepare(registry, publication, native_authority, session)[0]


def test_foreign_registry_receipt_cannot_be_transferred(owner_factory, native_authority):
    make, _ = owner_factory
    owner = make()
    lease = owner.begin(uuid4(), SELECTOR)
    registry, publication = create_owned_registry()
    _, foreign = create_owned_registry()
    prepared, _ = _prepare(registry, publication, native_authority)
    receipt = publication.abandon_prepared_candidate(prepared)
    with pytest.raises(RegistryCapabilityError):
        owner.retain_retirement(lease, foreign, receipt)
    assert publication.claim_retired_candidate(receipt)
    assert owner.settle(lease)


def test_published_candidate_transfers_only_inside_exact_owner_publication(owner_factory, native_authority):
    make, _ = owner_factory
    owner = make()
    lease = owner.begin(uuid4(), SELECTOR)
    registry, publication = create_owned_registry()
    prepared, session = _prepare(registry, publication, native_authority)
    cleaned = []
    ticket = owner.retain_candidate(lease, session, cleaned.append)
    with pytest.raises(RuntimeError, match="account_candidate_transfer_invalid"):
        owner.transfer_candidate_to_registry(lease, ticket, publication)

    def publish():
        publication.publish_prepared_candidate(prepared, current_authority=native_authority)
        owner.transfer_candidate_to_registry(lease, ticket, publication)

    owner.publish_if_current(lease, publish)
    assert owner.settle(lease)
    assert cleaned == []
    assert owner.close_and_drain(1.0)
    assert cleaned == [session]


def test_retirement_from_another_selector_is_nonconsuming(owner_factory, native_authority):
    make, _ = owner_factory
    owner = make()
    lease = owner.begin(uuid4(), BrokerSelector("dhan", "Other"))
    registry, publication = create_owned_registry()
    prepared, _ = _prepare(registry, publication, native_authority)
    receipt = publication.abandon_prepared_candidate(prepared)
    with pytest.raises(RegistryCapabilityError):
        owner.retain_retirement(lease, publication, receipt, cleanup=lambda _: pytest.fail("foreign selector disposed"))
    assert publication.claim_retired_candidate(receipt)
    assert owner.settle(lease)


def _publish_owned_candidate(owner, lease, registry, publication, authority, cleanup):
    prepared, session = _prepare(registry, publication, authority)
    ticket = owner.retain_candidate(lease, session, cleanup)

    def publish():
        result = publication.publish_prepared_candidate(prepared, current_authority=authority)
        owner.transfer_candidate_to_registry(lease, ticket, publication)
        return result

    result = owner.publish_if_current(lease, publish)
    assert owner.settle(lease)
    return session, result


def test_shutdown_keeps_live_cleanup_custody_after_mutation_settles(owner_factory, native_authority):
    make, _ = owner_factory
    owner = make()
    lease = owner.begin(uuid4(), SELECTOR)
    registry, publication = create_owned_registry()
    cleaned = []
    session, _ = _publish_owned_candidate(owner, lease, registry, publication, native_authority, cleaned.append)
    assert cleaned == []
    assert owner.close_and_drain(1.0)
    assert cleaned == [session]
    assert registry.snapshot_selector(SELECTOR).present is False


def test_live_cleanup_waits_for_generation_drain(owner_factory, native_authority):
    make, _ = owner_factory
    release = threading.Event()
    owner = make(retire=lambda timeout: release.wait(timeout))
    lease = owner.begin(uuid4(), SELECTOR)
    registry, publication = create_owned_registry()
    cleaned = []
    session, _ = _publish_owned_candidate(owner, lease, registry, publication, native_authority, cleaned.append)
    assert owner.close_and_drain(0.01) is False
    assert cleaned == []
    release.set()
    assert owner.close_and_drain(1.0)
    assert cleaned == [session]


def test_shutdown_disposes_owned_retirement_without_retiring_successor(owner_factory, native_authority):
    make, _ = owner_factory
    owner = make()
    lease = owner.begin(uuid4(), SELECTOR)
    registry, publication = create_owned_registry()
    cleaned = []
    session, _ = _publish_owned_candidate(owner, lease, registry, publication, native_authority, cleaned.append)
    prepared, successor = _prepare(registry, publication, native_authority)
    newer = publication.publish_prepared_candidate(prepared, current_authority=native_authority)
    assert owner.close_and_drain(1.0)
    assert cleaned == [session]
    assert registry.snapshot_selector(SELECTOR) == newer.version.registry_version
    assert publication.owns_live_candidate(successor)


def test_unclaimable_live_retirement_keeps_shutdown_incomplete(owner_factory, native_authority):
    make, _ = owner_factory
    owner = make()
    lease = owner.begin(uuid4(), SELECTOR)
    registry, publication = create_owned_registry()
    cleaned = []
    _, published = _publish_owned_candidate(owner, lease, registry, publication, native_authority, cleaned.append)
    removed = publication.remove_session_for_exact(SELECTOR, expected_registry=published.version.registry_version)
    claimed_elsewhere = publication.claim_retired_candidate(removed.retired)
    assert owner.close_and_drain(0.01) is False
    assert cleaned == []
    assert claimed_elsewhere.session


def test_later_retirement_inherits_explicit_live_cleanup_contract(owner_factory, native_authority):
    make, _ = owner_factory
    owner = make()
    lease = owner.begin(uuid4(), SELECTOR)
    registry, publication = create_owned_registry()
    cleaned = []
    session, published = _publish_owned_candidate(owner, lease, registry, publication, native_authority, cleaned.append)
    next_lease = owner.begin(uuid4(), SELECTOR)
    removed = publication.remove_session_for_exact(SELECTOR, expected_registry=published.version.registry_version)
    owner.retain_retirement(next_lease, publication, removed.retired)
    owner.abandon(next_lease)
    assert owner.close_and_drain(1.0)
    assert cleaned == [session]


def test_published_unsupported_cleanup_is_honestly_quarantined(owner_factory, native_authority):
    make, _ = owner_factory
    owner = make()
    lease = owner.begin(uuid4(), SELECTOR)
    registry, publication = create_owned_registry()
    _publish_owned_candidate(owner, lease, registry, publication, native_authority, None)
    assert owner.close_and_drain(0.01) is False
    assert owner.snapshot().quarantined == 1


def test_shutdown_registry_race_never_retires_successor(owner_factory, native_authority, monkeypatch):
    make, _ = owner_factory
    owner = make()
    lease = owner.begin(uuid4(), SELECTOR)
    registry, publication = create_owned_registry()
    cleaned = []
    session, _ = _publish_owned_candidate(owner, lease, registry, publication, native_authority, cleaned.append)
    prepared, successor = _prepare(registry, publication, native_authority)
    original_remove = publication.remove_session_for_exact
    newer = []

    def race(selector, *, expected_registry):
        newer.append(publication.publish_prepared_candidate(prepared, current_authority=native_authority))
        return original_remove(selector, expected_registry=expected_registry)

    monkeypatch.setattr(publication, "remove_session_for_exact", race)
    assert owner.close_and_drain(1.0)
    assert cleaned == [session]
    assert registry.snapshot_selector(SELECTOR) == newer[0].version.registry_version
    assert publication.owns_live_candidate(successor)


def test_retirement_callback_requires_exact_boolean_completion(owner_factory):
    make, _ = owner_factory
    owner = make(retire=lambda timeout: "not a drain receipt")
    assert owner.close_and_drain(0.01) is False


@pytest.mark.parametrize("disposition", ["abandon", "publish_conflict"])
@pytest.mark.parametrize("explicit_cleanup", [False, True])
def test_retired_unpublished_session_moves_one_cleanup_ticket(
    owner_factory, native_authority, disposition, explicit_cleanup
):
    from flinttrade_core.account_mutation_contracts import RegistryVersionConflict

    make, _ = owner_factory
    owner = make()
    lease = owner.begin(uuid4(), SELECTOR)
    registry, publication = create_owned_registry()
    cleaned = []
    prepared, session = _prepare(registry, publication, native_authority)
    original_ticket = owner.retain_candidate(lease, session, cleaned.append)
    if disposition == "abandon":
        receipt = publication.abandon_prepared_candidate(prepared)
    else:
        publication.remove_session_for_exact(SELECTOR, expected_registry=registry.snapshot_selector(SELECTOR))
        with pytest.raises(RegistryVersionConflict) as conflict:
            publication.publish_prepared_candidate(prepared, current_authority=native_authority)
        receipt = conflict.value.retirement_receipt
    cleanup = (lambda value: cleaned.append(value.session)) if explicit_cleanup else None
    ticket = owner.retain_retirement(lease, publication, receipt, cleanup=cleanup)
    assert ticket is original_ticket
    assert owner.close_and_drain(1.0)
    assert cleaned == [session]
    assert owner.snapshot().quarantined == 0
    assert _prepare(registry, publication, native_authority, session)[0]


@pytest.mark.parametrize("registry_refusal_first", [False, True])
def test_owner_wide_reservation_refuses_cleanup_of_an_older_live_session(
    owner_factory, native_authority, registry_refusal_first
):
    make, _ = owner_factory
    owner = make()
    registry, publication = create_owned_registry()
    cleaned = []
    lease = owner.begin(uuid4(), SELECTOR)
    session, _ = _publish_owned_candidate(owner, lease, registry, publication, native_authority, cleaned.append)
    next_lease = owner.begin(uuid4(), SELECTOR)
    if registry_refusal_first:
        with pytest.raises(RegistrySessionUnavailable):
            _prepare(registry, publication, native_authority, session)
    with pytest.raises(RuntimeError, match="account_candidate_already_owned"):
        owner.retain_candidate(next_lease, session, lambda _: pytest.fail("older live session disposed"))
    assert owner.settle(next_lease)
    assert cleaned == []
    assert publication.owns_live_candidate(session)
    assert owner.close_and_drain(1.0)
    assert cleaned == [session]


@pytest.mark.parametrize("invalid", [object(), "async"])
def test_invalid_retirement_cleanup_preserves_original_live_custody(owner_factory, native_authority, invalid):
    make, _ = owner_factory
    owner = make()
    registry, publication = create_owned_registry()
    cleaned = []
    lease = owner.begin(uuid4(), SELECTOR)
    session, published = _publish_owned_candidate(owner, lease, registry, publication, native_authority, cleaned.append)
    next_lease = owner.begin(uuid4(), SELECTOR)
    removed = publication.remove_session_for_exact(SELECTOR, expected_registry=published.version.registry_version)

    async def async_cleanup(_payload):
        pytest.fail("invalid cleanup executed")

    cleanup = async_cleanup if invalid == "async" else invalid
    with pytest.raises(TypeError, match="account_candidate_cleanup_invalid"):
        owner.retain_retirement(next_lease, publication, removed.retired, cleanup=cleanup)
    assert owner.snapshot().live_owned == 1
    assert publication.retirement_for_candidate(session) is removed.retired
    owner.retain_retirement(next_lease, publication, removed.retired)
    assert owner.close_and_drain(1.0)
    assert cleaned == [session]


def test_failed_retirement_acceptance_rolls_back_the_owner_move(owner_factory, native_authority, monkeypatch):
    make, _ = owner_factory
    owner = make()
    registry, publication = create_owned_registry()
    cleaned = []
    lease = owner.begin(uuid4(), SELECTOR)
    session, published = _publish_owned_candidate(owner, lease, registry, publication, native_authority, cleaned.append)
    next_lease = owner.begin(uuid4(), SELECTOR)
    removed = publication.remove_session_for_exact(SELECTOR, expected_registry=published.version.registry_version)
    original = publication.transfer_retired_candidate

    def injected(receipt, accept):
        def fail_after_accept(payload):
            accept(payload)
            raise RuntimeError("synthetic acceptance failure")

        return original(receipt, fail_after_accept)

    with monkeypatch.context() as patch:
        patch.setattr(publication, "transfer_retired_candidate", injected)
        with pytest.raises(RuntimeError, match="synthetic acceptance failure"):
            owner.retain_retirement(next_lease, publication, removed.retired)
    assert owner.snapshot().live_owned == 1
    assert publication.retirement_for_candidate(session) is removed.retired
    owner.retain_retirement(next_lease, publication, removed.retired)
    assert owner.close_and_drain(1.0)
    assert cleaned == [session]


@pytest.mark.asyncio
async def test_each_async_shutdown_borrower_keeps_its_own_budget(owner_factory):
    make, _ = owner_factory
    release = threading.Event()
    entered = threading.Event()

    def retire(timeout):
        entered.set()
        return release.wait(timeout)

    owner = make(retire=retire)
    first = asyncio.create_task(owner.close_and_drain_async(0.5))
    await asyncio.to_thread(entered.wait, 1.0)
    first.cancel()
    with pytest.raises(asyncio.CancelledError):
        await first
    shared_bridge = owner._async_shutdown
    try:
        assert await asyncio.wait_for(owner.close_and_drain_async(0.01), 0.1) is False
        assert owner._async_shutdown is shared_bridge
        assert not shared_bridge.done() and not shared_bridge.cancelled()
        assert await asyncio.wait_for(owner.close_and_drain_async(0.01), 0.1) is False
        assert owner._async_shutdown is shared_bridge
    finally:
        release.set()
    assert await owner.close_and_drain_async(0.5)


def _fence_dependent_reads(lock, available, completed):
    class Reads:
        def close(self, *, timeout):
            if not timeout:
                return completed.is_set()

            def completion():
                acquired = lock.acquire(timeout=0.1)
                available.append(acquired)
                if acquired:
                    lock.release()
                    completed.set()

            thread = threading.Thread(target=completion)
            thread.start()
            thread.join(0.3)
            return completed.is_set()

    return Reads()


def test_actual_enrolled_configure_drains_outside_the_outer_fence(owner_factory, monkeypatch):
    from types import SimpleNamespace
    import flinttrade_core.app as app_api

    _, proof = owner_factory
    app = Flask("actual-configure-unlocked-drain")
    lock = threading.RLock()
    app.config.update(
        BACKEND_LEASE_PROOF=proof, BROKER_ROUTER_REBUILD_LOCK=lock, BROKER_ROUTER_DRAIN_TIMEOUT_SECONDS=0.5
    )
    registry, publication = create_owned_registry()
    app.config["REGISTRY"] = registry
    app.extensions["flinttrade.registry_publication_owner"] = publication
    owner = app_api.broker_account_lifecycle_owner_for(app, proof.workspace_path)
    available = []
    completed = threading.Event()
    app.extensions["flinttrade_broker_dependencies"] = SimpleNamespace(
        read_owner=_fence_dependent_reads(lock, available, completed)
    )
    built = []

    def stop_after_drain(*_args, **_kwargs):
        built.append(True)
        raise RuntimeError("synthetic stop after successful drain")

    monkeypatch.setattr(app_api, "_prepare_broker_dependencies", stop_after_drain)
    try:
        assert app_api.configure_broker_router(app, registry, None, None) is False
        assert available == [True]
        assert built == [True]
    finally:
        completed.set()
        assert owner.close_and_drain(1.0)


def test_enrolled_configure_revalidates_original_generation_after_unlocked_drain(owner_factory, monkeypatch):
    from types import SimpleNamespace
    import flinttrade_core.app as app_api

    _, proof = owner_factory
    app = Flask("exact-rebuild-generation")
    lock = threading.RLock()
    app.config.update(
        BACKEND_LEASE_PROOF=proof, BROKER_ROUTER_REBUILD_LOCK=lock, BROKER_ROUTER_DRAIN_TIMEOUT_SECONDS=0.5
    )
    registry, publication = create_owned_registry()
    app.config["REGISTRY"] = registry
    app.extensions["flinttrade.registry_publication_owner"] = publication
    owner = app_api.broker_account_lifecycle_owner_for(app, proof.workspace_path)
    successor = SimpleNamespace(read_owner=None)
    built = []

    raced = []

    class Reads:
        def close(self, *, timeout):
            if not timeout:
                return bool(raced)
            with lock:
                app.extensions["flinttrade_broker_dependencies"] = successor
                raced.append(True)
            return True

    app.extensions["flinttrade_broker_dependencies"] = SimpleNamespace(read_owner=Reads())
    monkeypatch.setattr(app_api, "_prepare_broker_dependencies", lambda *_args, **_kwargs: built.append(True))
    try:
        assert app_api.configure_broker_router(app, registry, None, None) is False
        assert built == []
        assert app.extensions["flinttrade_broker_dependencies"] is successor
    finally:
        app.extensions.pop("flinttrade_broker_dependencies", None)
        assert owner.close_and_drain(1.0)


def test_rotation_admission_refuses_an_active_account_mutation(owner_factory):
    from flinttrade_core.native_rotation import _rotation_admission

    make, _ = owner_factory
    app = Flask("rotation-admission-owner-lane")
    lock = threading.RLock()
    app.config["BROKER_ROUTER_REBUILD_LOCK"] = lock
    admission = _rotation_admission(app)
    owner = make(lock=lock)
    app.extensions["flinttrade.broker_account_lifecycle_owner"] = owner
    lease = owner.begin(uuid4(), SELECTOR)
    with pytest.raises(RuntimeError, match="account lifecycle"):
        admission.acquire()
    assert owner.settle(lease)


def test_runtime_rebuild_intent_retains_its_real_drain_after_borrower_timeout(owner_factory):
    make, _ = owner_factory
    owner = make()
    assert callable(getattr(owner, "begin_rebuild", None)), "explicit runtime rebuild intent missing"
    release = threading.Event()
    entered = threading.Event()

    def retire(timeout):
        if not timeout:
            return False
        entered.set()
        return release.wait(1.0)

    token = owner.begin_rebuild(retire_generations=retire, publication_current=lambda: True)
    with pytest.raises(TypeError):
        pickle.dumps(token)
    try:
        assert owner.retire_rebuild_generations(token, 0.01) is False
        assert entered.wait(1.0)
        owner.end_rebuild(token)
        with pytest.raises(RuntimeError, match="account_mutation_busy"):
            owner.begin(uuid4(), SELECTOR)
        assert owner.close_and_drain(0.01) is False
    finally:
        release.set()
    assert owner.close_and_drain(1.0)


def test_owner_issued_rebuild_cannot_escape_its_mutation_publication_scope(owner_factory):
    make, _ = owner_factory
    owner = make()
    lease = owner.begin(uuid4(), SELECTOR)
    token = owner.publish_if_current(
        lease, lambda: owner.begin_rebuild(retire_generations=lambda _: True, publication_current=lambda: True)
    )
    owner.abandon(lease)
    try:
        with pytest.raises(RuntimeError, match="account_rebuild_publication_revoked"):
            owner.publish_rebuild_if_current(token, lambda: pytest.fail("escaped rebuild published"))
    finally:
        owner.end_rebuild(token)
    assert owner.settle(lease)


@pytest.mark.asyncio
async def test_owner_issued_empty_rebuild_can_revoke_without_a_loop_wait(owner_factory):
    make, _ = owner_factory
    owner = make()
    lease = owner.begin(uuid4(), SELECTOR)

    def publish():
        token = owner.begin_rebuild(retire_generations=lambda _: True, publication_current=lambda: True)
        try:
            return owner.retire_rebuild_generations(token, 0.5)
        finally:
            owner.end_rebuild(token)

    assert owner.publish_if_current(lease, publish)
    assert owner.settle(lease)


def test_failed_retirement_acceptance_cannot_report_clean_mid_transfer(owner_factory, native_authority, monkeypatch):
    make, _ = owner_factory
    owner = make()
    registry, publication = create_owned_registry()
    cleaned = []
    lease = owner.begin(uuid4(), SELECTOR)
    session, published = _publish_owned_candidate(owner, lease, registry, publication, native_authority, cleaned.append)
    next_lease = owner.begin(uuid4(), SELECTOR)
    removed = publication.remove_session_for_exact(SELECTOR, expected_registry=published.version.registry_version)
    original = publication.transfer_retired_candidate
    observed = []

    def injected(receipt, accept):
        def fail_after_accept(payload):
            accept(payload)
            observed.append(owner.close_and_drain(0.0))
            raise RuntimeError("synthetic acceptance failure")

        return original(receipt, fail_after_accept)

    with monkeypatch.context() as patch:
        patch.setattr(publication, "transfer_retired_candidate", injected)
        with pytest.raises(RuntimeError, match="synthetic acceptance failure"):
            owner.retain_retirement(next_lease, publication, removed.retired)
    assert observed == [False]
    assert cleaned == []
    assert owner.snapshot().live_owned == 1
    assert owner.close_and_drain(1.0)
    assert cleaned == [session]


def test_enrolled_caller_process_fence_precedes_the_shared_rebuild_lock(owner_factory, monkeypatch):
    import flinttrade_core.app as app_api

    _, proof = owner_factory
    app = Flask("enrolled-caller-process-fence")
    app.config["BACKEND_LEASE_PROOF"] = proof
    owner = app_api.broker_account_lifecycle_owner_for(app, proof.workspace_path)

    class InheritedFence:
        def __enter__(self):
            pytest.fail("foreign process entered inherited rebuild fence")

        def __exit__(self, *_args):
            pass

        def acquire(self, **_kwargs):
            pytest.fail("foreign process acquired inherited rebuild fence")

        def release(self):
            pass

    with monkeypatch.context() as patch:
        patch.setattr(owner, "_creator_pid", -1)
        app.config["BROKER_ROUTER_REBUILD_LOCK"] = InheritedFence()
        assert app_api.configure_broker_router(app, None, None, None) is False
        with pytest.raises(RuntimeError, match="account_lifecycle_foreign_process"):
            app_api.broker_account_lifecycle_owner_for(app, proof.workspace_path)
    app.config["BROKER_ROUTER_REBUILD_LOCK"] = owner._rebuild_lock
    assert owner.close_and_drain(1.0)


def test_enrolled_rebuild_admission_is_bounded_by_the_app_budget(owner_factory):
    from concurrent.futures import ThreadPoolExecutor
    import flinttrade_core.app as app_api

    _, proof = owner_factory
    app = Flask("bounded-rebuild-admission")
    lock = threading.RLock()
    app.config.update(
        BACKEND_LEASE_PROOF=proof, BROKER_ROUTER_REBUILD_LOCK=lock, BROKER_ROUTER_DRAIN_TIMEOUT_SECONDS=0.01
    )
    owner = app_api.broker_account_lifecycle_owner_for(app, proof.workspace_path)
    held = threading.Event()
    release = threading.Event()

    def hold():
        with lock:
            held.set()
            release.wait(1.0)

    holder = threading.Thread(target=hold)
    holder.start()
    assert held.wait(1.0)
    with ThreadPoolExecutor(max_workers=1) as executor:
        worker = executor.submit(app_api.configure_broker_router, app, None, None, None)
        try:
            assert worker.result(0.2) is False
        finally:
            release.set()
            holder.join(1.0)
            worker.result(1.0)
    assert owner.close_and_drain(1.0)


# Bounded reconstruction: original bodies were not recovered. The retained
# fragments above are unchanged; these tests fill the documented coverage gaps.
def test_reconstructed_rotation_constructor_checks_refresh_admission():
    from flinttrade_core.native_rotation import NativeRotationAdmission

    allowed = [False]
    admission = NativeRotationAdmission(refresh_admission=lambda: allowed[0])
    with pytest.raises(RuntimeError, match="account lifecycle admission"):
        admission.acquire()
    allowed[0] = True
    generation = admission.acquire()
    admission.release(generation)
    assert admission.close_and_drain(0.0)


@pytest.mark.asyncio
async def test_reconstructed_revoke_both_before_wait_and_loop_release(owner_factory):
    from types import SimpleNamespace
    import flinttrade_core.app as app_api

    _, proof = owner_factory
    app = Flask("reconstructed-loop-release")
    app.config["BACKEND_LEASE_PROOF"] = proof
    owner = app_api.broker_account_lifecycle_owner_for(app, proof.workspace_path)
    lease = owner.begin(uuid4(), SELECTOR)
    events = []
    released = threading.Event()

    class Reads:
        def close(self, *, timeout):
            events.append(("read", bool(timeout)))
            if timeout:
                assert events[:2] == [("read", False), ("write", False)]
                return released.wait(timeout)
            return released.is_set()

    class Writes:
        def revoke_and_drain(self, *, timeout):
            events.append(("write", bool(timeout)))
            return released.wait(timeout) if timeout else released.is_set()

    app.extensions["flinttrade_broker_dependencies"] = SimpleNamespace(read_owner=Reads())
    app.config["BROKER_ROUTER"] = Writes()

    async def release_on_loop():
        await asyncio.sleep(0.01)
        released.set()

    release_task = asyncio.create_task(release_on_loop())
    try:
        assert await owner.retire_generations_async(lease, 0.5)
        assert events[:2] == [("read", False), ("write", False)]
    finally:
        released.set()
        await release_task
        assert await owner.close_and_drain_async(1.0)


@pytest.mark.asyncio
async def test_reconstructed_positive_sync_drain_rejects_caller_loop(owner_factory):
    make, _ = owner_factory
    owner = make()
    lease = owner.begin(uuid4(), SELECTOR)
    with pytest.raises(RuntimeError, match="use_async_drain"):
        owner.retire_generations(lease, 0.1)
    assert owner.settle(lease)


def test_reconstructed_actual_dispatch_rechecks_backend_proof(owner_factory, lifecycle_api, monkeypatch):
    make, proof = owner_factory
    owner = make()
    lease = owner.begin(uuid4(), SELECTOR)
    queued = []
    original = lifecycle_api._launch
    with monkeypatch.context() as patch:
        patch.setattr(lifecycle_api, "_launch", lambda future, operation: queued.append((future, operation)))
        worker = owner.run_worker(lease, lambda: pytest.fail("revoked worker dispatched"))
    assert not worker.done()
    proof.revoke()
    original(*queued[0])
    with pytest.raises(RuntimeError, match="backend_lease_unavailable"):
        worker.result(1.0)
    assert owner.settle(lease)


def test_reconstructed_publication_waits_for_real_worker(owner_factory):
    make, _ = owner_factory
    owner = make()
    lease = owner.begin(uuid4(), SELECTOR)
    worker = Future()
    worker.set_running_or_notify_cancel()
    owner.retain_worker(lease, worker)
    with pytest.raises(RuntimeError, match="worker_pending"):
        owner.publish_if_current(lease, lambda: pytest.fail("pending worker published"))
    worker.set_result(None)
    assert owner.publish_if_current(lease, lambda: "ready") == "ready"


def test_reconstructed_publication_refuses_failed_retained_worker(owner_factory):
    make, _ = owner_factory
    owner = make()
    lease = owner.begin(uuid4(), SELECTOR)
    worker = Future()
    worker.set_exception(RuntimeError("setup failed"))
    owner.retain_worker(lease, worker)
    with pytest.raises(RuntimeError, match="worker_failed"):
        owner.publish_if_current(lease, lambda: pytest.fail("failed worker published"))
    assert owner.settle(lease)


def test_reconstructed_failed_retirement_prevents_publication(owner_factory):
    make, _ = owner_factory
    drained = [False]
    owner = make(retire=lambda _: drained[0])
    lease = owner.begin(uuid4(), SELECTOR)
    assert owner.retire_generations(lease, 0.1) is False
    with pytest.raises(RuntimeError, match="retirement_pending"):
        owner.publish_if_current(lease, lambda: pytest.fail("undrained generation published"))
    assert owner.settle(lease) is False
    drained[0] = True
    assert owner.retire_generations(lease, 0.1)
    assert owner.settle(lease)


def test_reconstructed_result_acceptance_failure_quarantines_payload(owner_factory):
    make, _ = owner_factory
    owner = make()
    lease = owner.begin(uuid4(), SELECTOR)
    payload = object()

    def reject(_value):
        raise RuntimeError("synthetic result acceptance failure")

    worker = owner.run_worker(lease, lambda: payload, accept_result=reject)
    with pytest.raises(RuntimeError, match="synthetic result acceptance failure"):
        worker.result(1.0)
    assert owner.snapshot().quarantined == 1
    assert owner.settle(lease) is False
    assert owner.close_and_drain(0.0) is False


@pytest.mark.asyncio
async def test_reconstructed_asyncio_wrapper_is_not_a_real_worker(owner_factory):
    make, _ = owner_factory
    owner = make()
    lease = owner.begin(uuid4(), SELECTOR)
    wrapped = asyncio.get_running_loop().create_future()
    with pytest.raises(TypeError, match="real_worker_required"):
        owner.retain_worker(lease, wrapped)
    wrapped.cancel()
    assert owner.settle(lease)


def test_reconstructed_settle_revokes_publication_before_cleanup(owner_factory):
    make, _ = owner_factory
    owner = make()
    lease = owner.begin(uuid4(), SELECTOR)
    entered = threading.Event()
    release = threading.Event()

    def cleanup(_payload):
        entered.set()
        release.wait(1.0)

    owner.retain_candidate(lease, object(), cleanup)
    try:
        assert owner.settle(lease) is False
        assert entered.wait(1.0)
        with pytest.raises(RuntimeError, match="publication_revoked"):
            owner.publish_if_current(lease, lambda: pytest.fail("cleanup payload published"))
    finally:
        release.set()
    assert owner.close_and_drain(1.0)


def test_reconstructed_cleanup_requires_none_completion_and_can_retry(owner_factory):
    make, _ = owner_factory
    owner = make()
    lease = owner.begin(uuid4(), SELECTOR)
    calls = []

    def cleanup(payload):
        calls.append(payload)
        return False if len(calls) == 1 else None

    payload = object()
    owner.retain_candidate(lease, payload, cleanup)
    assert owner.close_and_drain(0.5) is False
    assert owner.snapshot().cleanup_pending == 1
    assert owner.close_and_drain(1.0)
    assert calls == [payload, payload]


@pytest.mark.parametrize("callback_kind", ["noncallable", "async", "awaitable_result"])
def test_reconstructed_publication_rejects_async_callbacks(owner_factory, callback_kind):
    make, _ = owner_factory
    owner = make()
    lease = owner.begin(uuid4(), SELECTOR)

    async def asynchronous():
        pytest.fail("async callback ran")

    callback = object() if callback_kind == "noncallable" else asynchronous
    if callback_kind == "awaitable_result":

        def callback():
            return asynchronous()

    with pytest.raises(TypeError, match="publication_callback_invalid"):
        owner.publish_if_current(lease, callback)
    assert owner.settle(lease)


def test_reconstructed_foreign_workspace_cannot_compose_owner(owner_factory, tmp_path, lifecycle_api):
    make, proof = owner_factory
    owner = make()
    with pytest.raises(RuntimeError, match="authority_invalid"):
        owner.assert_bound(tmp_path / "foreign", proof)
    with pytest.raises(RuntimeError, match="authority_invalid"):
        lifecycle_api.BrokerAccountLifecycleOwner(
            tmp_path / "foreign", proof, retire_generations=lambda _: True, rebuild_lock=threading.RLock()
        )


def test_reconstructed_creator_cleanup_survives_backend_revocation(owner_factory):
    make, proof = owner_factory
    owner = make()
    lease = owner.begin(uuid4(), SELECTOR)
    payload = object()
    cleaned = []
    owner.retain_candidate(lease, payload, cleaned.append)
    proof.revoke()
    assert owner.close_and_drain(1.0)
    assert cleaned == [payload]


@pytest.mark.filterwarnings("ignore:This process.*multi-threaded:DeprecationWarning")
def test_reconstructed_real_fork_refuses_before_inherited_locks(owner_factory):
    import os
    import selectors
    import signal

    if not hasattr(os, "fork"):
        pytest.skip("requires actual process fork")
    make, _ = owner_factory
    owner = make()
    lease = owner.begin(uuid4(), SELECTOR)
    cleaned = []
    owner.retain_candidate(lease, object(), cleaned.append)
    held = threading.Event()
    release = threading.Event()

    def hold_parent_locks():
        with owner._condition, owner._rebuild_lock:
            held.set()
            release.wait(3.0)

    holder = threading.Thread(target=hold_parent_locks)
    holder.start()
    assert held.wait(1.0)
    read_fd, write_fd = os.pipe()
    pid = os.fork()
    if pid == 0:
        os.close(read_fd)
        try:
            for action in (
                owner.snapshot,
                lambda: owner.close_and_drain(0.0),
                lambda: owner.settle(lease),
                owner.current_rebuild,
            ):
                try:
                    action()
                except RuntimeError as error:
                    if "account_lifecycle_foreign_process" not in str(error):
                        raise
                else:
                    raise AssertionError("fork-inherited owner accepted")
            assert cleaned == []
            os.write(write_fd, b"refused-before-locks")
        finally:
            os._exit(0)
    os.close(write_fd)
    try:
        with selectors.DefaultSelector() as readiness:
            readiness.register(read_fd, selectors.EVENT_READ)
            assert readiness.select(1.0), "child touched inherited locked condition/fence"
        assert os.read(read_fd, 100) == b"refused-before-locks"
    finally:
        os.close(read_fd)
        os.kill(pid, signal.SIGKILL)
        os.waitpid(pid, 0)
        release.set()
        holder.join(1.0)
    assert owner.close_and_drain(1.0)
    assert len(cleaned) == 1


def test_reconstructed_runtime_intent_checks_thread_proof_and_generation(owner_factory):
    from concurrent.futures import ThreadPoolExecutor

    make, proof = owner_factory
    owner = make()
    current = [True]
    token = owner.begin_rebuild(retire_generations=lambda _: True, publication_current=lambda: current[0])
    try:
        with ThreadPoolExecutor(max_workers=1) as pool:
            assert pool.submit(owner.current_rebuild).result() is None
            with pytest.raises(RuntimeError, match="rebuild_lease_invalid"):
                pool.submit(owner.publish_rebuild_if_current, token, lambda: None).result()
        assert owner.retire_rebuild_generations(token, 0.1)
        current[0] = False
        with pytest.raises(RuntimeError, match="generation_conflict"):
            owner.publish_rebuild_if_current(token, lambda: pytest.fail("foreign generation published"))
        current[0] = True
        proof.revoke()
        with pytest.raises(RuntimeError, match="backend_lease_unavailable"):
            owner.publish_rebuild_if_current(token, lambda: pytest.fail("revoked rebuild published"))
    finally:
        owner.end_rebuild(token)


def test_reconstructed_escaped_intent_refuses_without_mutation_abandonment(owner_factory):
    make, _ = owner_factory
    owner = make()
    lease = owner.begin(uuid4(), SELECTOR)
    token = owner.publish_if_current(
        lease, lambda: owner.begin_rebuild(retire_generations=lambda _: True, publication_current=lambda: True)
    )
    try:
        with pytest.raises(RuntimeError, match="rebuild_publication_revoked"):
            owner.publish_rebuild_if_current(token, lambda: pytest.fail("escaped current mutation intent published"))
    finally:
        owner.end_rebuild(token)
    assert owner.settle(lease)


@pytest.mark.parametrize("callback", [object(), "async"])
def test_reconstructed_runtime_intent_rejects_invalid_callbacks(owner_factory, callback):
    make, _ = owner_factory
    owner = make()

    async def invalid(_timeout):
        pytest.fail("invalid async retirement executed")

    retire = invalid if callback == "async" else callback
    with pytest.raises(TypeError, match="rebuild_callback_invalid"):
        owner.begin_rebuild(retire_generations=retire, publication_current=lambda: True)


def test_reconstructed_app_shutdown_keeps_worker_and_remaining_rotation_budget(owner_factory):
    import flinttrade_core.app as app_api
    from flinttrade_core.native_rotation import NativeRotationAdmission

    make, _ = owner_factory
    owner = make()
    lease = owner.begin(uuid4(), SELECTOR)
    release = threading.Event()
    worker = owner.run_worker(lease, lambda: release.wait(1.0))
    app = Flask("reconstructed-worker-shutdown")
    app.extensions["flinttrade.broker_account_lifecycle_owner"] = owner
    try:
        with pytest.raises(TimeoutError, match="account lifecycle"):
            app_api._shutdown_rotation_scheduler(app, timeout=0.01)
        assert not worker.done()
        assert owner.snapshot().workers == 1
    finally:
        release.set()
        worker.result(1.0)
    assert owner.close_and_drain(1.0)

    order = []

    class Lifecycle:
        def close_and_drain(self, timeout):
            order.append(("lifecycle", timeout))
            time.sleep(0.02)
            return True

    class Rotation(NativeRotationAdmission):
        def close_and_drain(self, timeout):
            order.append(("rotation", timeout))
            return super().close_and_drain(timeout)

    app.extensions["flinttrade.broker_account_lifecycle_owner"] = Lifecycle()
    app.config["NATIVE_ROTATION_ADMISSION"] = Rotation()
    app_api._shutdown_rotation_scheduler(app, timeout=0.1)
    assert [name for name, _timeout in order] == ["rotation", "lifecycle"]
    assert order[0][1] > 0.09
    assert order[1][1] < order[0][1]


def test_reconstructed_app_composition_is_explicit_and_uses_existing_fence(owner_factory):
    import flinttrade_core.app as app_api
    from flinttrade_core.native_rotation import _rotation_admission

    _, proof = owner_factory
    app = Flask("reconstructed-inert-owner")
    lock = threading.RLock()
    app.config.update(BACKEND_LEASE_PROOF=proof, BROKER_ROUTER_REBUILD_LOCK=lock)
    assert "flinttrade.broker_account_lifecycle_owner" not in app.extensions
    admission = _rotation_admission(app)
    owner = app_api.broker_account_lifecycle_owner_for(app, proof.workspace_path)
    assert app_api.broker_account_lifecycle_owner_for(app, proof.workspace_path) is owner
    assert owner._rebuild_lock is lock
    assert admission._publication_lock is lock
    lease = owner.begin(uuid4(), SELECTOR)
    assert app_api._account_publication_allowed(app) is False
    assert owner.publish_if_current(lease, lambda: app_api._account_publication_allowed(app)) is True
    assert owner.settle(lease)
    assert owner.close_and_drain(1.0)


def test_reconstructed_duplicate_retirement_rejects_different_registry_owner(owner_factory, native_authority):
    make, _ = owner_factory
    owner = make()
    lease = owner.begin(uuid4(), SELECTOR)
    registry, publication = create_owned_registry()
    _, foreign = create_owned_registry()
    prepared, _ = _prepare(registry, publication, native_authority)
    receipt = publication.abandon_prepared_candidate(prepared)
    ticket = owner.retain_retirement(lease, publication, receipt, cleanup=lambda _: None)
    with pytest.raises(RegistryCapabilityError):
        owner.retain_retirement(lease, foreign, receipt)
    assert owner.retain_retirement(lease, publication, receipt) is ticket
    assert owner.close_and_drain(1.0)
