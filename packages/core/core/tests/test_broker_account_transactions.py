"""Offline end-to-end account transactions; production HTTP remains frozen."""

import asyncio
import importlib
import importlib.util
from dataclasses import replace

import pytest

from flinttrade_core.account_lifecycle_contracts import AccountMutationKind, AccountOperationStage
from flinttrade_core.broker_read_port import (
    BrokerReadErrorCode, BrokerReadFailure, BrokerReadSuccess, InstrumentRef, QuoteRequest,
)
from flinttrade_gateway.account_transaction_store import AccountOperationConflict

from .account_lifecycle_test_support import SyntheticAccountHarness


@pytest.fixture
def api():
    name = "flinttrade_core.broker_account_transactions"
    assert importlib.util.find_spec(name) is not None, "synthetic transaction coordinator is missing"
    return importlib.import_module(name)


@pytest.fixture
def harness(api, tmp_path, monkeypatch, backend_lease_factory):
    monkeypatch.setenv("FLINTTRADE_WORKSPACE_DIR", str(tmp_path))
    value = SyntheticAccountHarness(tmp_path, backend_lease_factory(), api)
    yield value
    value.close()


@pytest.mark.asyncio
async def test_connect_commits_real_stores_and_authenticated_exact_reads(harness):
    request = harness.request(roles=("quote",))
    result = await harness.coordinator.mutate(request, timeout=2.0)
    assert result.receipt.state is AccountOperationStage.COMMITTED
    assert result.runtime_status == "ready"
    assert harness.store.head() == harness.store.operation(request.operation_id).witness
    assert harness.credentials.selector_state(request.selector).version == result.receipt.credential_version
    assert harness.credentials.retrieve_for("dhan", "Synthetic") == {"token": "synthetic-replay"}
    port = harness.bind(request.selector)
    quote = await port.quote(QuoteRequest(InstrumentRef("INFY", "NSE")))
    balance = await port.balance()
    assert type(quote) is BrokerReadSuccess and quote.value.ltp == 100.0
    assert type(balance) is BrokerReadSuccess and balance.value.available_balance == 100.0
    assert harness.adapter.logins == 1
    data = (harness.path / "vault.db").read_bytes()
    assert b"synthetic-input" not in data and b"synthetic-replay" not in data


@pytest.mark.asyncio
async def test_reconnect_rotation_remove_are_once_only_and_removal_has_no_session(harness):
    connect = harness.request()
    first = await harness.coordinator.mutate(connect, timeout=2.0)
    assert (await harness.coordinator.mutate(connect, timeout=2.0)).receipt == first.receipt
    for kind in (AccountMutationKind.RECONNECT, AccountMutationKind.ROTATE):
        request = harness.request(kind)
        result = await harness.coordinator.mutate(request, timeout=2.0)
        assert result.runtime_status == "ready"
        assert (await harness.coordinator.mutate(request, timeout=2.0)).receipt == result.receipt
    request = harness.request(AccountMutationKind.REMOVE)
    result = await harness.coordinator.mutate(request, timeout=2.0)
    assert result.runtime_status == "removed"
    assert harness.adapter.logins == 3
    assert harness.registry.snapshot_exact_state(request.selector).binding is None
    assert harness.runtime.read_owner is None
    assert not harness.credentials.selector_state(request.selector).present
    assert len(harness.adapter.cleaned) == 3


@pytest.mark.asyncio
async def test_changed_keyed_identity_and_wrong_actor_refuse_before_auth(harness):
    request = harness.request()
    await harness.coordinator.mutate(request, timeout=2.0)
    for changed in (replace(request, label="Other"), replace(request, credentials={"token": "changed"})):
        with pytest.raises(AccountOperationConflict):
            await harness.coordinator.mutate(changed, timeout=2.0)
    with harness.app.app_context():
        from flinttrade_core.auth_routes import _create_token
        harness.token = _create_token("wrong-actor")
    port = harness.bind(request.selector)
    assert type(port) is BrokerReadFailure and port.code is BrokerReadErrorCode.UNAUTHORISED
    with pytest.raises(ValueError):
        await harness.coordinator.mutate(harness.request(AccountMutationKind.RECONNECT), timeout=2.0)
    assert harness.adapter.logins == 1


@pytest.mark.asyncio
async def test_auth_timeout_retains_worker_and_unknown_claim_without_retry(harness):
    request = harness.request()
    harness.adapter.auth_release.clear()
    result = await harness.coordinator.mutate(request, timeout=0.75)
    assert result.receipt.state is AccountOperationStage.AUTHENTICATION_UNKNOWN
    assert harness.lifecycle.snapshot().workers == 1
    assert (await harness.coordinator.mutate(request, timeout=0.05)).receipt == result.receipt
    assert harness.adapter.logins == 1
    harness.adapter.auth_release.set()
    for _ in range(100):
        if harness.lifecycle.snapshot().workers == 0:
            break
        await asyncio.sleep(0.01)
    assert harness.registry.snapshot_exact_state(request.selector).binding is None
    assert harness.store.active_operation(harness.store.owner_capability(harness.lifecycle._proof)) is not None


def test_coordinator_module_is_present():
    assert importlib.util.find_spec("flinttrade_core.broker_account_transactions") is not None, (
        "synthetic transaction coordinator is missing"
    )


@pytest.mark.asyncio
async def test_terminal_replay_survives_incoherence_and_is_read_only(harness, monkeypatch):
    request = harness.request()
    first = await harness.coordinator.mutate(request, timeout=2.0)
    monkeypatch.setattr(harness.workspace, "assert_coherent", lambda: (_ for _ in ()).throw(ValueError("unavailable")))
    monkeypatch.setattr(harness.store, "admit", lambda *_: pytest.fail("terminal replay mutated admission"))
    replay = await harness.coordinator.mutate(request, timeout=2.0)
    assert replay.receipt == first.receipt and replay.runtime_status == "session_unavailable"
    assert harness.adapter.logins == 1


@pytest.mark.asyncio
async def test_registry_successor_during_generation_drain_is_preserved(harness, monkeypatch):
    request = harness.request()
    await harness.coordinator.mutate(request, timeout=2.0)
    reconnect = harness.request(AccountMutationKind.RECONNECT)
    original = harness.lifecycle._retire_generations
    from flinttrade_gateway.brokers._base import Session
    from flinttrade_gateway.registry import ManagedSessionAuthority
    from flinttrade_core.workspace_migrations import broker_workspace_version
    import time
    successor = Session("synthetic-successor", time.time() + 3600, "Synthetic", "dhan")
    installed = []

    def replace_during_drain(timeout):
        result = original(timeout)
        if not installed:
            snapshot = harness.workspace.assert_coherent()
            authority = ManagedSessionAuthority(reconnect.expected_credential, snapshot.version,
                                                broker_workspace_version(snapshot))
            prepared = harness.registry_owner.prepare_session_candidate(
                reconnect.selector, successor, expected_registry=harness.registry.snapshot_selector(reconnect.selector),
                authority=authority, broker="dhan", label="Successor")
            publication = harness.registry_owner.publish_prepared_candidate(prepared, current_authority=authority)
            installed.append(publication.version)
        return result

    monkeypatch.setattr(harness.lifecycle, "_retire_generations", replace_during_drain)
    result = await harness.coordinator.mutate(reconnect, timeout=2.0)
    assert result.receipt.state is AccountOperationStage.REJECTED
    assert harness.registry.snapshot_exact_state(reconnect.selector).binding == installed[0]
    assert harness.adapter.logins == 1


@pytest.mark.asyncio
async def test_shutdown_between_runtime_lease_and_durable_admission_refuses_row(harness, monkeypatch):
    request = harness.request()
    admit = harness.store.admit

    def shutdown_then_admit(value):
        assert harness.lifecycle.snapshot().active
        harness.lifecycle.close_and_drain(0.0)
        return admit(value)

    monkeypatch.setattr(harness.store, "admit", shutdown_then_admit)
    result = await harness.coordinator.mutate(request, timeout=2.0)
    assert result.receipt.state is AccountOperationStage.REJECTED
    assert harness.store.active_operation(harness.store.owner_capability(harness.lifecycle._proof)) is None
    assert harness.adapter.logins == 0


@pytest.mark.asyncio
async def test_lost_workspace_replace_result_is_forward_only(harness, monkeypatch):
    from flinttrade_core import workspace_migrations
    request = harness.request()
    writer = workspace_migrations._atomic_write
    attempts = []

    def commit_then_raise(*args, **kwargs):
        attempts.append(True)
        writer(*args, **kwargs)
        raise OSError("synthetic lost replace result")

    monkeypatch.setattr(workspace_migrations, "_atomic_write", commit_then_raise)
    result = await harness.coordinator.mutate(request, timeout=2.0)
    assert result.receipt.state is AccountOperationStage.COMMITTED
    assert result.runtime_status == "ready"
    assert not harness.store.operation(request.operation_id).abandoned
    assert harness.credentials.selector_state(request.selector).version.generation == 1
    assert len(attempts) == 1
    assert (await harness.coordinator.mutate(request, timeout=2.0)).receipt == result.receipt
    assert len(attempts) == 1 and harness.adapter.logins == 1


@pytest.mark.asyncio
async def test_actual_jwt_revocation_while_auth_blocked_prevents_commit(harness):
    request = harness.request()
    harness.adapter.auth_release.clear()
    task = asyncio.create_task(harness.coordinator.mutate(request, timeout=3.0))
    await asyncio.to_thread(harness.adapter.auth_entered.wait, 2.0)
    with harness.app.app_context():
        from flinttrade_core import auth_routes
        payload = auth_routes.decode_token(harness.token)
        auth_routes._revoke_jti(payload["jti"], payload["exp"])
    harness.adapter.auth_release.set()
    result = await task
    assert result.receipt.state is AccountOperationStage.REJECTED
    assert harness.credentials.selector_state(request.selector).version.generation == 0
    assert harness.registry.snapshot_exact_state(request.selector).binding is None
    assert harness.adapter.logins == 1


@pytest.mark.asyncio
async def test_unchecked_actor_and_default_mutation_admission_remain_denied(harness, api):
    request = harness.request()
    coordinator = api.BrokerAccountTransactionCoordinator(
        harness.store, harness.workspace, harness.lifecycle, harness.registry_owner, harness.adapter, harness.runtime,
    )
    with pytest.raises(Exception, match="cutover"):
        await coordinator.mutate(request, timeout=2.0)
    coordinator._admission = lambda: None
    with pytest.raises(ValueError, match="principal"):
        await coordinator.mutate(request, timeout=2.0)
    assert harness.store.existing_request(request) is None and harness.adapter.logins == 0


@pytest.fixture
def two_accounts(api, tmp_path, monkeypatch, backend_lease_factory):
    monkeypatch.setenv("FLINTTRADE_WORKSPACE_DIR", str(tmp_path))

    def seed(config):
        config["brokers"]["registered"] += ["dhan:Synthetic", "dhan:Other"]
        config["brokers"]["execution"]["default"] = "dhan:Other"
        config["brokers"]["failover"]["order"] = ["dhan:Synthetic", "dhan:Other"]

    value = SyntheticAccountHarness(tmp_path, backend_lease_factory(), api, accounts=("Synthetic", "Other"), seed=seed)
    yield value
    value.close()


@pytest.mark.asyncio
async def test_two_accounts_token_only_preserves_other_through_fresh_facade(two_accounts):
    first = two_accounts.request()
    await two_accounts.coordinator.mutate(first, timeout=2.0)
    other = two_accounts.request(account="Other")
    # First connect did not change the preconfigured broker domain.
    await two_accounts.coordinator.mutate(other, timeout=2.0)
    old = two_accounts.bind(other.selector)
    before = two_accounts.workspace.assert_coherent()
    reconnect = two_accounts.request(AccountMutationKind.RECONNECT)
    result = await two_accounts.coordinator.mutate(reconnect, timeout=2.0)
    after = two_accounts.workspace.assert_coherent()
    assert result.runtime_status == "ready"
    assert before.config["_broker_account_store"]["epoch"] + 1 == after.config["_broker_account_store"]["epoch"]
    assert reconnect.expected_broker_workspace == result.receipt.commit_broker_workspace
    assert (await old.balance()).code is BrokerReadErrorCode.REVOKED
    assert type(await two_accounts.bind(other.selector).balance()) is BrokerReadSuccess
    assert two_accounts.adapter.logins == 3
    assert after.config["brokers"]["execution"]["default"] == "dhan:Other"
    assert after.config["brokers"]["account_acls"] == before.config["brokers"]["account_acls"]


@pytest.mark.asyncio
async def test_two_accounts_real_role_change_leaves_other_unavailable_without_reauth(two_accounts):
    first = two_accounts.request()
    await two_accounts.coordinator.mutate(first, timeout=2.0)
    other = two_accounts.request(account="Other")
    await two_accounts.coordinator.mutate(other, timeout=2.0)
    before = two_accounts.workspace.assert_coherent()
    other_payload = two_accounts.adapter.sessions[1]
    two_accounts.adapter.read_only = True
    reconnect = two_accounts.request(AccountMutationKind.RECONNECT)
    result = await two_accounts.coordinator.mutate(reconnect, timeout=2.0)
    after = two_accounts.workspace.assert_coherent()
    assert result.runtime_status == "ready"
    assert result.receipt.commit_broker_workspace.generation == reconnect.expected_broker_workspace.generation + 1
    refusal = two_accounts.bind(other.selector)
    assert type(refusal) is BrokerReadFailure
    assert two_accounts.adapter.logins == 3
    assert not any(value is other_payload for value in two_accounts.adapter.cleaned)
    assert after.config["brokers"]["execution"]["default"] == "dhan:Other"
    assert after.config["brokers"]["failover"]["order"] == ("dhan:Other",)
    assert after.config["brokers"]["account_acls"] == before.config["brokers"]["account_acls"]


@pytest.mark.asyncio
async def test_read_only_target_demotes_only_its_own_default(two_accounts):
    from flinttrade_core import workspace_migrations
    # The real temporary seed is adjusted through a valid owned account patch,
    # never a production configuration bypass.
    before = two_accounts.workspace.assert_coherent()
    from flinttrade_core.broker_account_workspace import BrokerAccountPatch
    from flinttrade_core.broker_identity import BrokerSelector
    patch = BrokerAccountPatch(AccountMutationKind.RECONNECT, BrokerSelector("dhan", "Other"), (), True)
    projected = patch.apply(before.config)
    assert projected["brokers"]["execution"]["default"] == ""
    assert projected["brokers"]["failover"]["order"] == ["dhan:Synthetic"]
    assert projected["brokers"]["account_acls"] == before.as_dict()["brokers"]["account_acls"]
    assert workspace_migrations.broker_workspace_version(before) == two_accounts.store.head().commit_broker_workspace
    await two_accounts.coordinator.mutate(two_accounts.request(account="Other"), timeout=2.0)
    two_accounts.adapter.read_only = True
    result = await two_accounts.coordinator.mutate(
        two_accounts.request(AccountMutationKind.RECONNECT, account="Other"), timeout=2.0)
    assert result.runtime_status == "ready"
    after = two_accounts.workspace.assert_coherent()
    assert after.config["brokers"]["execution"]["default"] == ""
    assert after.config["brokers"]["failover"]["order"] == ("dhan:Synthetic",)


@pytest.mark.asyncio
async def test_reconnect_keeps_exhausted_shared_read_budget(harness):
    from flinttrade_gateway.rate_limiter import BrokerRateLimiter
    clock = [0.0]
    sleeping = asyncio.Event()
    release = asyncio.Event()

    async def sleep(delay):
        sleeping.set()
        await release.wait()
        clock[0] += delay

    limiter = BrokerRateLimiter({"dhan": {"data": 1.0, "quote": 1.0}}, clock=lambda: clock[0], sleep=sleep)
    harness.runtime._rate_limiter = limiter
    request = harness.request()
    await harness.coordinator.mutate(request, timeout=2.0)
    assert type(await harness.bind(request.selector).quote(QuoteRequest(InstrumentRef("INFY", "NSE")))) is BrokerReadSuccess
    await harness.coordinator.mutate(harness.request(AccountMutationKind.RECONNECT), timeout=2.0)
    read_count = harness.adapter.reads
    pending = asyncio.create_task(harness.bind(request.selector).quote(QuoteRequest(InstrumentRef("INFY", "NSE"))))
    await asyncio.wait_for(sleeping.wait(), 1.0)
    assert not pending.done() and harness.adapter.reads == read_count
    assert harness.runtime.read_owner._rate_limiter is limiter
    release.set()
    assert type(await pending) is BrokerReadSuccess and harness.adapter.reads == read_count + 1


@pytest.mark.asyncio
@pytest.mark.parametrize("phase", ["admission", "stage", "vault_apply", "registry_prepare", "registry_publish", "runtime_build"])
async def test_phase_result_loss_never_reauthenticates_or_bumps_again(harness, monkeypatch, phase):
    request = harness.request()
    if phase == "admission":
        target, name = harness.store, "admit"
    elif phase == "stage":
        target, name = harness.store, "stage_plan"
    elif phase == "vault_apply":
        target, name = harness.store, "apply"
    elif phase == "registry_prepare":
        target, name = harness.registry_owner, "prepare_session_candidate"
    elif phase == "registry_publish":
        target, name = harness.registry_owner, "publish_prepared_candidate"
    else:
        target, name = harness.runtime, "rebuild"
    actual = getattr(target, name)
    calls = []

    def changed(*args, **kwargs):
        calls.append(True)
        actual(*args, **kwargs)
        raise OSError("synthetic lost phase result")

    monkeypatch.setattr(target, name, changed)
    result = await harness.coordinator.mutate(request, timeout=2.0)
    generation = harness.credentials.selector_state(request.selector).version.generation
    replay = await harness.coordinator.mutate(request, timeout=2.0)
    assert replay.receipt == result.receipt
    assert harness.credentials.selector_state(request.selector).version.generation == generation
    assert harness.adapter.logins <= 1
    assert len(calls) == 1
    assert harness.store.active_operation(harness.store.owner_capability(harness.lifecycle._proof)) is None
    if phase == "registry_prepare":
        assert not harness.registry._prepared and not harness.registry._managed_sessions


@pytest.mark.asyncio
async def test_cancelled_auth_worker_finishes_without_publication_or_clean_shutdown(harness):
    request = harness.request()
    harness.adapter.auth_release.clear()
    task = asyncio.create_task(harness.coordinator.mutate(request, timeout=3.0))
    assert await asyncio.to_thread(harness.adapter.auth_entered.wait, 2.0)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    operation = harness.store.operation(request.operation_id)
    assert operation.abandoned and operation.state is AccountOperationStage.AUTHENTICATION_UNKNOWN
    assert not await harness.lifecycle.close_and_drain_async(0.01)
    harness.adapter.auth_release.set()
    for _ in range(100):
        if harness.lifecycle.snapshot().workers == 0:
            break
        await asyncio.sleep(0.01)
    assert not await harness.lifecycle.close_and_drain_async(1.0)
    assert len(harness.adapter.cleaned) == 1
    assert harness.registry.snapshot_exact_state(request.selector).binding is None
    assert harness.store.active_operation(harness.store.owner_capability(harness.lifecycle._proof)) is not None


@pytest.mark.asyncio
async def test_blocked_read_drain_yields_loop_and_prevents_auth(harness):
    request = harness.request()
    await harness.coordinator.mutate(request, timeout=2.0)
    old = harness.bind(request.selector)
    harness.adapter.read_release.clear()
    read = asyncio.create_task(old.quote(QuoteRequest(InstrumentRef("INFY", "NSE"))))
    assert await asyncio.to_thread(harness.adapter.read_entered.wait, 1.0)
    reconnect = harness.request(AccountMutationKind.RECONNECT)
    mutation = asyncio.create_task(harness.coordinator.mutate(reconnect, timeout=0.5))
    await asyncio.sleep(0.2)
    assert harness.adapter.logins == 1 and not mutation.done()
    harness.adapter.read_release.set()
    assert (await read).code is BrokerReadErrorCode.REVOKED
    result = await mutation
    assert result.receipt.state is AccountOperationStage.COMMITTED
    assert result.runtime_status == "ready" and harness.adapter.logins == 2


@pytest.mark.asyncio
async def test_cleanup_timeout_retains_committed_claim_and_exact_ticket(harness):
    await harness.coordinator.mutate(harness.request(), timeout=2.0)
    request = harness.request(AccountMutationKind.REMOVE)
    harness.adapter.cleanup_release.clear()
    result = await harness.coordinator.mutate(request, timeout=0.6)
    assert result.receipt.state is AccountOperationStage.COMMITTED and result.runtime_status == "cleanup_pending"
    assert harness.store.active_operation(harness.store.owner_capability(harness.lifecycle._proof)) is not None
    assert not await harness.lifecycle.close_and_drain_async(0.01)
    harness.adapter.cleanup_release.set()
    replay = await harness.coordinator.mutate(request, timeout=2.0)
    assert replay.receipt == result.receipt and replay.runtime_status == "removed"
    assert len(harness.adapter.cleaned) == 1


@pytest.mark.asyncio
async def test_definite_rejection_vs_generic_auth_unknown(harness, api):
    harness.adapter.auth_error = api.AccountAuthenticationRejected()
    request = harness.request()
    definite = await harness.coordinator.mutate(request, timeout=2.0)
    assert definite.receipt.state is AccountOperationStage.REJECTED
    assert harness.store.active_operation(harness.store.owner_capability(harness.lifecycle._proof)) is None
    harness.adapter.auth_error = RuntimeError("synthetic ambiguous auth effect")
    uncertain = await harness.coordinator.mutate(harness.request(), timeout=2.0)
    assert uncertain.receipt.state is AccountOperationStage.AUTHENTICATION_UNKNOWN
    assert harness.store.active_operation(harness.store.owner_capability(harness.lifecycle._proof)) is not None


@pytest.mark.asyncio
async def test_cancelled_committed_cleanup_records_publication_abandonment(harness):
    await harness.coordinator.mutate(harness.request(), timeout=2.0)
    request = harness.request(AccountMutationKind.RECONNECT)
    harness.adapter.cleanup_release.clear()
    task = asyncio.create_task(harness.coordinator.mutate(request, timeout=3.0))
    for _ in range(200):
        existing = harness.store.existing_request(request)
        if existing is not None and existing.receipt is not None:
            break
        await asyncio.sleep(0.01)
    assert existing.receipt.state is AccountOperationStage.COMMITTED
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    operation = harness.store.operation(request.operation_id)
    assert operation.abandoned and operation.abandonment_committed
    harness.adapter.cleanup_release.set()
    replay = await harness.coordinator.mutate(request, timeout=2.0)
    assert replay.receipt == operation.receipt and replay.runtime_status == "session_unavailable"


@pytest.mark.asyncio
async def test_same_process_admitted_retry_retains_original_tombstone_without_double_retirement(harness):
    await harness.coordinator.mutate(harness.request(), timeout=2.0)
    request = harness.request(AccountMutationKind.RECONNECT)
    # Model an interrupted borrower after definite provider-free retirement.
    def release():
        harness.store.release_claim(request.operation_id)
    lease = harness.lifecycle.begin(request.operation_id, request.selector, durable_claim_release=release)
    from flinttrade_core.broker_account_transactions import _Attempt
    attempt = _Attempt(lease, expected_registry=harness.registry.snapshot_selector(request.selector))
    harness.coordinator._attempts[request.operation_id] = attempt
    harness.store.admit(request)
    assert await harness.lifecycle.retire_generations_async(lease, 2.0)
    harness.coordinator._retire_target(request, attempt)
    original_tombstone = attempt.tombstone
    result = await harness.coordinator.mutate(request, timeout=2.0)
    assert result.runtime_status == "ready"
    assert harness.registry.snapshot_selector(request.selector).generation == original_tombstone.generation + 1
    assert harness.adapter.logins == 2 and len(harness.adapter.cleaned) == 1


@pytest.mark.asyncio
async def test_unrelated_edit_between_preparation_and_publication_uses_one_current_snapshot(harness, monkeypatch):
    from flinttrade_core.workspace_migrations import update_workspace_config, read_workspace_snapshot
    request = harness.request()
    apply = harness.store.apply
    called = []

    def edited(*args, **kwargs):
        receipt = apply(*args, **kwargs)
        update_workspace_config(harness.path, lambda config: config["ui"].update(theme="light"))
        called.append(read_workspace_snapshot(harness.path).version)
        return receipt

    monkeypatch.setattr(harness.store, "apply", edited)
    result = await harness.coordinator.mutate(request, timeout=2.0)
    assert result.runtime_status == "ready"
    assert harness.workspace.assert_coherent().config["ui"]["theme"] == "light"
    assert result.receipt.commit_workspace.generation < called[0].generation
    binding = harness.registry.snapshot_exact_state(request.selector).binding
    assert binding.workspace_version == called[0]


@pytest.mark.asyncio
async def test_enrolled_session_provider_requires_explicit_coherence_verifier(harness):
    from flinttrade_gateway.session_provider import AuthenticatingSessionProvider
    from flinttrade_core.account_mutation_contracts import RegistrySessionUnavailable
    request = harness.request()
    await harness.coordinator.mutate(request, timeout=2.0)
    snapshot = harness.workspace.assert_coherent()
    provider = AuthenticatingSessionProvider(
        harness.registry, snapshot.as_dict()["brokers"]["account_acls"], workspace_snapshot=snapshot,
        workspace_path=harness.path, credential_version_for=lambda selector: harness.credentials.selector_state(selector).version,
    )
    with pytest.raises(RegistrySessionUnavailable):
        provider(harness.verify_read(request.selector), "dhan", "Synthetic")
    assert harness.adapter.logins == 1


@pytest.mark.asyncio
async def test_unreadable_workspace_after_attempt_preserves_uncertainty_and_one_cas(harness, monkeypatch):
    from flinttrade_core import workspace_migrations
    from flinttrade_core.broker_account_workspace import BrokerAccountWorkspaceUnavailable
    request = harness.request()
    original = workspace_migrations._atomic_write
    count = []

    def hidden_result(*args, **kwargs):
        count.append(True)
        original(*args, **kwargs)
        own = (harness.path / "workspace.json").read_bytes()
        (harness.path / "own-witness.json").write_bytes(own)
        (harness.path / "workspace.json").write_text("{invalid", encoding="utf-8")
        raise OSError("synthetic unreadable decision")

    monkeypatch.setattr(workspace_migrations, "_atomic_write", hidden_result)
    with pytest.raises((BrokerAccountWorkspaceUnavailable, ValueError)):
        await harness.coordinator.mutate(request, timeout=2.0)
    operation = harness.store.operation(request.operation_id)
    assert operation.workspace_attempted and operation.workspace_conflicted
    assert operation.state is AccountOperationStage.PLAN_READY and not operation.abandoned
    assert harness.store.recovery_material(harness.store.owner_capability(harness.lifecycle._proof), request.operation_id).request
    (harness.path / "workspace.json").write_bytes((harness.path / "own-witness.json").read_bytes())
    recovered = harness.coordinator.recover()
    assert recovered[0].state is AccountOperationStage.COMMITTED
    assert harness.store.operation(request.operation_id).workspace_conflicted
    assert (await harness.coordinator.mutate(request, timeout=2.0)).runtime_status == "session_unavailable"
    assert len(count) == 1 and harness.adapter.logins == 1


@pytest.mark.asyncio
async def test_removed_receipt_cannot_fabricate_absence_after_successor(harness):
    await harness.coordinator.mutate(harness.request(), timeout=2.0)
    remove = harness.request(AccountMutationKind.REMOVE)
    removed = await harness.coordinator.mutate(remove, timeout=2.0)
    await harness.coordinator.mutate(harness.request(), timeout=2.0)
    replay = await harness.coordinator.mutate(remove, timeout=2.0)
    assert replay.receipt == removed.receipt and replay.runtime_status == "session_unavailable"
    assert harness.adapter.logins == 2


@pytest.mark.asyncio
@pytest.mark.parametrize("changed", ["workspace", "broker", "credential", "actor", "session"])
async def test_rebound_identity_and_stale_versions_refuse_before_auth(harness, changed):
    from dataclasses import replace
    from flinttrade_core.account_lifecycle_contracts import AccountActorContext
    from flinttrade_core.broker_identity import CredentialVersion
    from flinttrade_core.workspace_migrations import WorkspaceVersion, BrokerWorkspaceVersion
    request = harness.request()
    await harness.coordinator.mutate(request, timeout=2.0)
    if changed == "workspace":
        changed_request = replace(request, expected_workspace=WorkspaceVersion(
            request.expected_workspace.instance_id, request.expected_workspace.generation + 1))
    elif changed == "broker":
        changed_request = replace(request, expected_broker_workspace=BrokerWorkspaceVersion(
            request.expected_broker_workspace.instance_id, request.expected_broker_workspace.generation + 1))
    elif changed == "credential":
        changed_request = replace(request, expected_credential=CredentialVersion(
            request.selector, request.expected_credential.vault_incarnation, 1))
    elif changed == "actor":
        changed_request = replace(request, actor=AccountActorContext("other", request.actor.session_binding))
    else:
        changed_request = replace(request, actor=AccountActorContext(request.actor.actor, "session:" + "b" * 64))
    with pytest.raises(AccountOperationConflict):
        await harness.coordinator.mutate(changed_request, timeout=2.0)
    assert harness.adapter.logins == 1


@pytest.mark.parametrize("boundary", ["admission", "auth_start", "plan", "workspace", "vault", "registry"])
def test_fresh_process_recovery_is_provider_free_at_actual_pipeline_boundaries(
        api, tmp_path, monkeypatch, boundary):
    import json
    import os
    import subprocess
    import sys
    import threading
    from pathlib import Path
    from flinttrade_core.account_lifecycle_contracts import _request_from
    from flinttrade_core.backend_instance import acquire_backend_instance_lease
    from flinttrade_core.broker_account_lifecycle import BrokerAccountLifecycleOwner
    from flinttrade_core.broker_account_workspace import BrokerAccountWorkspace
    from flinttrade_gateway.account_transaction_store import AccountTransactionStore
    from flinttrade_gateway.credentials import CredentialStore
    from flinttrade_gateway.registry import create_owned_registry
    monkeypatch.setenv("FLINTTRADE_WORKSPACE_DIR", str(tmp_path))
    support_path = str(Path(__file__).parent)
    script = r"""
import asyncio, json, os
from pathlib import Path
from flinttrade_core.account_lifecycle_contracts import _request_dict
from flinttrade_core.backend_instance import acquire_backend_instance_lease
from flinttrade_core.secure_file import write_secret_text
from flinttrade_core import broker_account_transactions as api
from account_lifecycle_test_support import SyntheticAccountHarness
path = Path(os.environ["FLINTTRADE_WORKSPACE_DIR"])
lease = acquire_backend_instance_lease()
harness = SyntheticAccountHarness(path, lease.proof, api)
request = harness.request()
write_secret_text(path / "synthetic-session.jwt", harness.token)
(path / "public-identity.json").write_text(json.dumps(_request_dict(request, private=False)))
boundary = os.environ["SYNTHETIC_BOUNDARY"]
choices = {
    "admission": (harness.store, "admit"),
    "auth_start": (harness.store, "mark_authentication_started"),
    "plan": (harness.store, "stage_plan"),
    "workspace": (harness.workspace, "commit"),
    "vault": (harness.store, "apply"),
    "registry": (harness.registry_owner, "publish_prepared_candidate"),
}
target, name = choices[boundary]
actual = getattr(target, name)
def die_after(*args, **kwargs):
    actual(*args, **kwargs)
    os._exit(23)
setattr(target, name, die_after)
asyncio.run(harness.coordinator.mutate(request, timeout=5.0))
"""
    environment = dict(os.environ, SYNTHETIC_BOUNDARY=boundary)
    environment["PYTHONPATH"] = os.environ["PYTHONPATH"] + os.pathsep + support_path
    process = subprocess.run([sys.executable, "-c", script], env=environment, capture_output=True, text=True, timeout=20)
    assert process.returncode == 23, process.stderr
    identity = json.loads((tmp_path / "public-identity.json").read_text())
    request = _request_from({**identity, "credentials": {"token": "synthetic-input"}})
    lease = acquire_backend_instance_lease()
    credentials = CredentialStore(tmp_path / "vault.db", "synthetic-password")
    store = AccountTransactionStore(credentials, workspace_path=tmp_path, backend_proof=lease.proof)
    workspace = BrokerAccountWorkspace(tmp_path, store, lease.proof)
    registry, publication = create_owned_registry(mutation_admission=lambda: None)
    runtime = api.BrokerAccountReadRuntime(
        registry=registry, workspace_path=tmp_path, credential_version_for=lambda selector: credentials.selector_state(selector).version,
        adapters={}, rate_limiter=None, runtime_accepting_requests=lambda: True)
    owner = BrokerAccountLifecycleOwner(tmp_path, lease.proof, retire_generations=runtime.retire,
                                         rebuild_lock=threading.RLock())

    class NeverAuthenticate:
        def authenticate(self, *args):
            pytest.fail("recovery dispatched auth")
        def cleanup(self, payload):
            pytest.fail("recovery invented a payload")

    from flask import Flask
    from flinttrade_core import auth_routes
    from flinttrade_core.auth_service import AuthService
    from flinttrade_core.account_lifecycle_contracts import AccountActorContext

    auth = AuthService(tmp_path / "auth.db")
    app = Flask("recovered-synthetic-principal")
    app.config["AUTH_SERVICE"] = auth
    monkeypatch.setattr(auth_routes, "_JWT_SECRET_KEY", None)
    token = (tmp_path / "synthetic-session.jwt").read_text()

    def verify_recovered_actor():
        with app.app_context():
            principal = auth_routes.verify_operator_session_token(token)
            return AccountActorContext(principal.actor_ref, principal.session_binding)

    coordinator = api.BrokerAccountTransactionCoordinator(
        store, workspace, owner, publication, NeverAuthenticate(), runtime, lambda: None,
        verify_current_actor=verify_recovered_actor)
    try:
        receipts = coordinator.recover()
        operation = store.operation(request.operation_id)
        if boundary == "admission":
            assert receipts == () and operation.state is AccountOperationStage.ADMITTED
        elif boundary == "auth_start":
            assert receipts[0].state is operation.state is AccountOperationStage.AUTHENTICATION_UNKNOWN
        else:
            assert receipts[0].state is operation.state is AccountOperationStage.COMMITTED
            replay = asyncio.run(coordinator.mutate(request, timeout=1.0))
            assert replay.receipt == receipts[0] and replay.runtime_status == "session_unavailable"
            assert credentials.selector_state(request.selector).version.generation == 1
        before = operation
        coordinator.recover()
        assert store.operation(request.operation_id) == before
        assert registry.snapshot_exact_state(request.selector) is None
        assert runtime.read_owner is None
    finally:
        closed = owner.close_and_drain(1.0)
        assert closed is (boundary not in {"admission", "auth_start"})
        credentials.close()
        auth.close()
        lease.release()


@pytest.mark.asyncio
async def test_blocked_synthetic_gated_write_drains_before_reconnect(harness):
    from flinttrade_core.models import Order
    from flinttrade_core.exceptions import SafetyBypassError
    from flinttrade_engine.safety import gate_order, set_safety_gate_secret
    from flinttrade_gateway.brokers._base import ROUTER_TOKEN
    from flinttrade_gateway.router import BrokerRouter
    request = harness.request()
    await harness.coordinator.mutate(request, timeout=2.0)
    entered = asyncio.Event()
    release = asyncio.Event()
    calls = []

    class SyntheticWrite:
        async def place_order(self, session, order, *, _router_token=None):
            assert _router_token is ROUTER_TOKEN
            calls.append(order)
            entered.set()
            await release.wait()
            return "synthetic-order"

    set_safety_gate_secret(b"synthetic-gate-secret-012345678901")
    context = harness.verify_read(request.selector)
    router = BrokerRouter({"dhan": SyntheticWrite()}, harness.runtime._provider,
                          backend_lease_proof=harness.lifecycle._proof)
    order = Order(symbol="INFY", action="BUY", exchange="NSE", quantity="1")

    async def gated_write():
        return await router.place_order(context, adapter_id="dhan", account_id="Synthetic", order=order,
            safety_ctx=gate_order(order, context, "dhan", account_id="Synthetic", backend_lease_proof=harness.lifecycle._proof))

    write = asyncio.create_task(gated_write())
    await asyncio.wait_for(entered.wait(), 1.0)
    retire = harness.lifecycle._retire_generations

    def retire_both(timeout):
        reads = retire(0.0)
        writes = router.revoke_and_drain(timeout=0.0)
        if timeout:
            reads = retire(timeout)
            writes = router.revoke_and_drain(timeout=timeout)
        return reads and writes

    harness.lifecycle._retire_generations = retire_both
    mutation = asyncio.create_task(harness.coordinator.mutate(harness.request(AccountMutationKind.RECONNECT), timeout=2.0))
    await asyncio.sleep(0.2)
    assert harness.adapter.logins == 1 and not mutation.done()
    with pytest.raises(SafetyBypassError, match="revoked"):
        await gated_write()
    assert len(calls) == 1
    release.set()
    assert await write == "synthetic-order"
    result = await mutation
    assert result.runtime_status == "ready" and harness.adapter.logins == 2


def test_definite_authentication_rejection_contract_is_neutral(api):
    from flinttrade_core import account_lifecycle_contracts as contracts
    assert getattr(contracts, "AccountAuthenticationRejected", None) is api.AccountAuthenticationRejected


@pytest.mark.asyncio
@pytest.mark.parametrize("boundary", ["owner_return", "projection_return"])
async def test_exact_removal_result_loss_preserves_owned_tombstone_and_cleanup(harness, monkeypatch, boundary):
    first = harness.request()
    await harness.coordinator.mutate(first, timeout=2.0)
    request = harness.request(AccountMutationKind.RECONNECT)
    old = harness.adapter.sessions[0]
    calls = []
    if boundary == "owner_return":
        target, name = harness.registry_owner, "remove_session_for_exact"
    else:
        target, name = harness.registry, "_project"
    actual = getattr(target, name)

    def lose_once(*args, **kwargs):
        result = actual(*args, **kwargs)
        calls.append(True)
        if len(calls) == 1:
            raise OSError("synthetic lost exact removal result")
        return result

    monkeypatch.setattr(target, name, lose_once)
    result = await harness.coordinator.mutate(request, timeout=2.0)
    assert result.receipt.state is AccountOperationStage.COMMITTED and result.runtime_status == "ready"
    assert harness.adapter.logins == 2
    assert sum(value is old for value in harness.adapter.cleaned) == 1
    original = harness.coordinator._attempts[request.operation_id].tombstone
    assert harness.registry.snapshot_selector(request.selector).generation == original.generation + 1
    assert (await harness.coordinator.mutate(request, timeout=2.0)).receipt == result.receipt
    assert harness.store.active_operation(harness.store.owner_capability(harness.lifecycle._proof)) is None
    assert harness.adapter.logins == 2


@pytest.mark.asyncio
async def test_exact_removal_result_loss_cannot_consume_a_successor(harness, monkeypatch):
    import time
    from flinttrade_gateway.brokers._base import Session
    from flinttrade_gateway.registry import ManagedSessionAuthority
    from flinttrade_core.workspace_migrations import broker_workspace_version
    await harness.coordinator.mutate(harness.request(), timeout=2.0)
    request = harness.request(AccountMutationKind.RECONNECT)
    actual = harness.registry_owner.remove_session_for_exact
    successor = Session("synthetic-successor", time.time() + 3600, "Synthetic", "dhan")
    versions = []

    def replace_after_remove(*args, **kwargs):
        result = actual(*args, **kwargs)
        snapshot = harness.workspace.assert_coherent()
        authority = ManagedSessionAuthority(request.expected_credential, snapshot.version, broker_workspace_version(snapshot))
        prepared = harness.registry_owner.prepare_session_candidate(
            request.selector, successor, expected_registry=result.version, authority=authority, broker="dhan", label="Successor")
        versions.append(harness.registry_owner.publish_prepared_candidate(prepared, current_authority=authority).version)
        raise OSError("synthetic lost removal result with successor")

    monkeypatch.setattr(harness.registry_owner, "remove_session_for_exact", replace_after_remove)
    result = await harness.coordinator.mutate(request, timeout=2.0)
    assert result.receipt.state is AccountOperationStage.REJECTED
    assert harness.registry.snapshot_exact_state(request.selector).binding == versions[0]
    assert harness.adapter.logins == 1
    assert len(harness.adapter.cleaned) == 1
    assert harness.store.active_operation(harness.store.owner_capability(harness.lifecycle._proof)) is None


@pytest.mark.asyncio
async def test_removal_decision_identity_and_consumed_custody_replay_are_exact(harness):
    from flinttrade_core.account_mutation_contracts import RegistryCapabilityError
    from flinttrade_core.broker_identity import BrokerSelector
    await harness.coordinator.mutate(harness.request(), timeout=2.0)
    request = harness.request(AccountMutationKind.RECONNECT)
    await harness.coordinator.mutate(request, timeout=2.0)
    attempt = harness.coordinator._attempts[request.operation_id]
    current = harness.registry.snapshot_selector(request.selector)
    result = harness.registry_owner.removal_result_for(
        request.operation_id, request.selector, expected_registry=attempt.expected_registry)
    assert result.version == attempt.tombstone and result.retired is None
    replay = harness.registry_owner.remove_session_for_exact(
        request.selector, expected_registry=attempt.expected_registry, operation_id=request.operation_id)
    assert replay == result and harness.registry.snapshot_selector(request.selector) == current
    with pytest.raises(RegistryCapabilityError):
        harness.registry_owner.removal_result_for(request.operation_id, request.selector, expected_registry=current)
    with pytest.raises(RegistryCapabilityError):
        harness.registry_owner.removal_result_for(request.operation_id, BrokerSelector("dhan", "Other"),
                                                  expected_registry=attempt.expected_registry)
    assert harness.adapter.logins == 2 and len(harness.adapter.cleaned) == 1


@pytest.mark.asyncio
async def test_target_removal_and_retirement_custody_share_short_owner_fence(harness, monkeypatch):
    import threading
    await harness.coordinator.mutate(harness.request(), timeout=2.0)
    request = harness.request(AccountMutationKind.RECONNECT)
    events = []
    remove = harness.registry_owner.remove_session_for_exact
    retain = harness.lifecycle.retain_retirement

    def fenced_remove(*args, **kwargs):
        events.append(("remove", harness.lifecycle._publication_thread == threading.get_ident()))
        return remove(*args, **kwargs)

    def fenced_custody(*args, **kwargs):
        events.append(("custody", harness.lifecycle._publication_thread == threading.get_ident()))
        return retain(*args, **kwargs)

    monkeypatch.setattr(harness.registry_owner, "remove_session_for_exact", fenced_remove)
    monkeypatch.setattr(harness.lifecycle, "retain_retirement", fenced_custody)
    result = await harness.coordinator.mutate(request, timeout=2.0)
    assert result.runtime_status == "ready"
    assert events == [("remove", True), ("custody", True)]


@pytest.mark.asyncio
@pytest.mark.parametrize("kind", [AccountMutationKind.RECONNECT, AccountMutationKind.ROTATE])
async def test_reconstructed_ineligible_roles_refuse_before_admission_or_auth(harness, kind):
    await harness.coordinator.mutate(harness.request(), timeout=2.0)
    request = replace(harness.request(kind), data_roles=("quote",))
    workspace = harness.workspace.assert_coherent()
    credential = harness.credentials.selector_state(request.selector)
    registry = harness.registry.snapshot_selector(request.selector)
    with pytest.raises(ValueError, match="account"):
        await harness.coordinator.mutate(request, timeout=2.0)
    assert harness.store.existing_request(request) is None
    assert harness.store.active_operation(harness.store.owner_capability(harness.lifecycle._proof)) is None
    assert harness.adapter.logins == 1
    assert harness.workspace.assert_coherent().version == workspace.version
    assert harness.credentials.selector_state(request.selector) == credential
    assert harness.registry.snapshot_selector(request.selector) == registry


@pytest.mark.asyncio
@pytest.mark.parametrize("deny", ["admission", "principal"])
async def test_reconstructed_terminal_replay_requires_current_authority(harness, monkeypatch, deny):
    from flinttrade_core.broker_account_cutover import require_broker_account_mutations
    request = harness.request()
    committed = await harness.coordinator.mutate(request, timeout=2.0)
    calls = []

    async def forbidden_settlement(*args):
        calls.append(True)
        pytest.fail("denied terminal borrower reached settlement")

    monkeypatch.setattr(harness.coordinator, "_settle", forbidden_settlement)
    if deny == "admission":
        monkeypatch.setattr(harness.coordinator, "_admission", require_broker_account_mutations)
        expected = RuntimeError
    else:
        monkeypatch.setattr(harness.coordinator, "_verify_actor", lambda: None)
        expected = ValueError
    with pytest.raises(expected):
        await harness.coordinator.mutate(request, timeout=2.0)
    assert calls == [] and harness.adapter.logins == 1
    assert harness.store.operation(request.operation_id).receipt == committed.receipt


@pytest.mark.asyncio
@pytest.mark.parametrize("deny", ["admission", "principal"])
async def test_reconstructed_denied_terminal_borrower_cannot_release_cleanup_claim(harness, monkeypatch, deny):
    from flinttrade_core.broker_account_cutover import require_broker_account_mutations
    await harness.coordinator.mutate(harness.request(), timeout=2.0)
    request = harness.request(AccountMutationKind.REMOVE)
    harness.adapter.cleanup_release.clear()
    result = await harness.coordinator.mutate(request, timeout=0.6)
    assert result.runtime_status == "cleanup_pending"
    original_admission = harness.coordinator._admission
    original_verifier = harness.coordinator._verify_actor
    original_settlement = harness.coordinator._settle
    calls = []

    async def forbidden_settlement(*args):
        calls.append(True)
        pytest.fail("denied borrower attempted cleanup/claim settlement")

    monkeypatch.setattr(harness.coordinator, "_settle", forbidden_settlement)
    if deny == "admission":
        monkeypatch.setattr(harness.coordinator, "_admission", require_broker_account_mutations)
        expected = RuntimeError
    else:
        monkeypatch.setattr(harness.coordinator, "_verify_actor", lambda: None)
        expected = ValueError
    try:
        with pytest.raises(expected):
            await harness.coordinator.mutate(request, timeout=2.0)
        assert calls == []
        assert harness.store.active_operation(harness.store.owner_capability(harness.lifecycle._proof)) is not None
        assert harness.adapter.logins == 1
    finally:
        monkeypatch.setattr(harness.coordinator, "_admission", original_admission)
        monkeypatch.setattr(harness.coordinator, "_verify_actor", original_verifier)
        monkeypatch.setattr(harness.coordinator, "_settle", original_settlement)
        harness.adapter.cleanup_release.set()
        assert (await harness.coordinator.mutate(request, timeout=2.0)).receipt == result.receipt


@pytest.mark.asyncio
async def test_reconstructed_removed_receipt_reports_actual_absence_in_fresh_registry(harness, api):
    from flinttrade_gateway.registry import create_owned_registry
    await harness.coordinator.mutate(harness.request(), timeout=2.0)
    request = harness.request(AccountMutationKind.REMOVE)
    removed = await harness.coordinator.mutate(request, timeout=2.0)
    registry, owner = create_owned_registry(mutation_admission=lambda: None)
    runtime = api.BrokerAccountReadRuntime(
        registry=registry, workspace_path=harness.path,
        credential_version_for=lambda selector: harness.credentials.selector_state(selector).version,
        adapters={"dhan": harness.adapter}, rate_limiter=harness.limiter,
        runtime_accepting_requests=lambda: True)
    coordinator = api.BrokerAccountTransactionCoordinator(
        harness.store, harness.workspace, harness.lifecycle, owner, harness.adapter, runtime, lambda: None,
        verify_current_actor=harness.verify_actor)
    replay = await coordinator.mutate(request, timeout=2.0)
    assert replay.receipt == removed.receipt and replay.runtime_status == "removed"
    assert registry.snapshot_exact_state(request.selector) is None and runtime.read_owner is None
    assert harness.adapter.logins == 1 and len(harness.adapter.cleaned) == 1
