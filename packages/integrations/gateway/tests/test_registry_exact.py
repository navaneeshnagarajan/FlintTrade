"""Exact publication is inert, sealed, monotonic and isolated by selector."""

import pickle
import time
from dataclasses import replace

import pytest

from flinttrade_core.account_mutation_contracts import (
    BrokerAccountAmbiguousError,
    RegistryCapabilityError,
    RegistrySessionUnavailable,
    RegistryVersionConflict,
)
from flinttrade_core.broker_identity import BrokerSelector
from flinttrade_core.secure_file import harden_directory
from flinttrade_core.workspace_migrations import broker_workspace_version, compare_and_swap_workspace
from flinttrade_gateway import registry as api
from flinttrade_gateway.brokers._base import Session
from flinttrade_gateway.credentials import CredentialStore
from flinttrade_gateway.session import BrokerSession


@pytest.fixture
def authority(tmp_path):
    parent = tmp_path / "owned"
    parent.mkdir()
    harden_directory(parent)
    stores = {}
    workspace = compare_and_swap_workspace(parent, None, lambda config: None)

    def make(selector):
        if selector.adapter_id not in stores:
            stores[selector.adapter_id] = CredentialStore(parent / f"{selector.adapter_id}.db", "synthetic-password")
        store = stores[selector.adapter_id]
        state = store.selector_state(selector)
        if not state.present:
            broker = "zerodha" if selector.adapter_id == "openalgo" else selector.adapter_id
            store.put_credentials(selector, broker, "Synthetic", {"token": "synthetic"}, expected=state.version)
        return api.ManagedSessionAuthority(
            store.selector_state(selector).version, workspace.version, broker_workspace_version(workspace)
        )

    yield make
    for store in stores.values():
        store.close()


def prepare(owner, registry, selector, authority, *, client=None, expires=None):
    session = Session("synthetic-secret", expires or time.time() + 3600, "broker-reported", selector.adapter_id)
    receipt = owner.prepare_session_candidate(
        selector,
        session,
        expected_registry=registry.snapshot_selector(selector),
        authority=authority,
        broker="zerodha" if selector.adapter_id == "openalgo" else selector.adapter_id,
        label="Synthetic",
        client=client,
    )
    return receipt, session


def test_exact_publish_remove_true_aba_and_retirement(authority):
    registry, owner = api.create_owned_registry()
    selector = BrokerSelector("dhan", "Case")
    auth = authority(selector)
    unseen = registry.snapshot_selector(selector)
    assert (unseen.generation, unseen.present) == (0, False)
    assert registry.list_exact_states() == ()
    receipt, session = prepare(owner, registry, selector, auth)
    result = owner.publish_prepared_candidate(receipt, current_authority=auth)
    assert result.version.registry_version.generation == 1
    assert registry.list_accounts()[0].account_id == "Case"
    assert registry.list_accounts()[0].adapter_id == "dhan"
    assert registry.list_accounts()[0].broker == "dhan"
    removed = owner.remove_session_for_exact(selector, expected_registry=result.version.registry_version)
    assert (removed.version.generation, removed.version.present) == (2, False)
    assert registry.list_exact_states()[0].status == "tombstoned"
    assert owner.claim_retired_candidate(removed.retired).session is session
    with pytest.raises(RegistryCapabilityError):
        owner.claim_retired_candidate(removed.retired)
    with pytest.raises(RegistryVersionConflict):
        owner.remove_session_for_exact(selector, expected_registry=unseen)


def test_wrong_owner_is_nonconsuming_but_owned_conflict_retires(authority):
    registry, owner = api.create_owned_registry()
    _, foreign = api.create_owned_registry()
    selector = BrokerSelector("dhan", "Case")
    auth = authority(selector)
    receipt, session = prepare(owner, registry, selector, auth)
    with pytest.raises(RegistryCapabilityError):
        foreign.publish_prepared_candidate(receipt, current_authority=auth)
    owner.remove_session_for_exact(selector, expected_registry=registry.snapshot_selector(selector))
    with pytest.raises(RegistryVersionConflict) as conflict:
        owner.publish_prepared_candidate(receipt, current_authority=auth)
    assert owner.claim_retired_candidate(conflict.value.retirement_receipt).session is session
    with pytest.raises(RegistryCapabilityError):
        owner.publish_prepared_candidate(receipt, current_authority=auth)
    assert "synthetic-secret" not in repr(receipt)
    with pytest.raises(TypeError):
        pickle.dumps(receipt)


def test_connected_handles_are_exact_and_supersession_invalidates_client(authority):
    registry, owner = api.create_owned_registry()
    selectors = [BrokerSelector("openalgo", "Case"), BrokerSelector("dhan", "Case")]
    clients = [object(), object()]
    for selector, client in zip(selectors, clients, strict=True):
        auth = authority(selector)
        receipt, _ = prepare(owner, registry, selector, auth, client=client)
        owner.publish_prepared_candidate(receipt, current_authority=auth)
    with pytest.raises(BrokerAccountAmbiguousError):
        registry.get_session("Case")
    auth = authority(selectors[0])
    lookup = api.ManagedLookupAuthority(auth.credential_version, auth.broker_workspace_version)
    handle = registry.get_connected_session_for(selectors[0], current_authority=lookup)
    assert handle.account_id == "broker-reported"
    handle.algo_id = "tag"
    assert handle.algo_id == "tag"
    assert registry.client_for_connected_session(handle, current_authority=lookup) is clients[0]
    owner.remove_session_for_exact(selectors[0], expected_registry=handle.version.registry_version)
    with pytest.raises(RegistrySessionUnavailable):
        registry.client_for_connected_session(handle, current_authority=lookup)


def test_expired_is_present_and_never_connected(authority):
    registry, owner = api.create_owned_registry()
    selector = BrokerSelector("dhan", "Case")
    auth = authority(selector)
    receipt, _ = prepare(owner, registry, selector, auth, expires=time.time() - 1)
    owner.publish_prepared_candidate(receipt, current_authority=auth)
    state = registry.list_exact_states()[0]
    assert state.registry_version.present and state.status == "expired"
    with pytest.raises(RegistrySessionUnavailable):
        registry.get_connected_session_for(
            selector,
            current_authority=api.ManagedLookupAuthority(
                auth.credential_version,
                auth.broker_workspace_version,
            ),
        )


def test_foreign_incarnation_and_full_workspace_cas(authority):
    registry, owner = api.create_owned_registry()
    other, _ = api.create_owned_registry()
    selector = BrokerSelector("dhan", "Case")
    with pytest.raises(RegistryVersionConflict):
        owner.remove_session_for_exact(selector, expected_registry=other.snapshot_selector(selector))
    auth = authority(selector)
    receipt, _ = prepare(owner, registry, selector, auth)
    changed = replace(auth, workspace_version=replace(auth.workspace_version, generation=2))
    with pytest.raises(RegistryVersionConflict):
        owner.publish_prepared_candidate(receipt, current_authority=changed)


def test_legacy_info_reports_transport_independently_from_broker():
    info = BrokerSession("raw-id", "zerodha", "Synthetic").info
    assert (info.adapter_id, info.broker, info.account_id) == ("openalgo", "zerodha", "raw-id")


def test_workspace_client_match_refuses_environment_and_reconfiguration(tmp_path):
    from flinttrade_core.config import Settings
    from flinttrade_core.openalgo_client import OpenAlgoClient

    workspace = compare_and_swap_workspace(
        tmp_path,
        None,
        lambda cfg: cfg.update(
            openalgo={
                "host": "https://one.invalid",
                "api_key": "synthetic-one",
                "port": 443,
                "ws_port": 8765,
            }
        ),
    )
    client = OpenAlgoClient(
        Settings(
            openalgo_host="https://one.invalid",
            openalgo_api_key="synthetic-one",
            openalgo_port=443,
            openalgo_ws_port=8765,
        )
    )
    assert client.matches_workspace_openalgo(workspace)
    client.reconfigure(Settings(openalgo_host="https://two.invalid", openalgo_api_key="synthetic-two"))
    assert not client.matches_workspace_openalgo(workspace)
    client.close_sync()


def test_provider_requires_workspace_and_present_exact_credential_reader(tmp_path):
    from flinttrade_gateway.session_provider import AuthenticatingSessionProvider

    registry, owner = api.create_owned_registry()
    selector = BrokerSelector("dhan", "Case")
    workspace = compare_and_swap_workspace(tmp_path, None, lambda cfg: None)
    harden_directory(tmp_path)
    store = CredentialStore(tmp_path / "vault.db", "synthetic")
    version = store.put_credentials(
        selector, "dhan", "Synthetic", {"token": "synthetic"}, expected=store.selector_state(selector).version
    )
    auth = api.ManagedSessionAuthority(version, workspace.version, broker_workspace_version(workspace))
    receipt, _ = prepare(owner, registry, selector, auth)
    owner.publish_prepared_candidate(receipt, current_authority=auth)

    def current_version(exact):
        state = store.selector_state(exact)
        if not state.present or not state.credential_present:
            raise RegistrySessionUnavailable
        return state.version

    provider = AuthenticatingSessionProvider(
        registry,
        {"dhan": {"Case": ["test-actor"]}},
        workspace_snapshot=workspace,
        workspace_path=tmp_path,
        credential_version_for=current_version,
    )
    from types import SimpleNamespace

    actor = SimpleNamespace(actor_id="test-actor")
    assert provider(actor, "dhan", "Case").selector == selector
    compare_and_swap_workspace(tmp_path, workspace.version, lambda cfg: cfg["services"].update(connection_epoch=1))
    assert provider(actor, "dhan", "Case").selector == selector
    store.remove_selector(selector, expected=version)
    with pytest.raises(RegistrySessionUnavailable):
        provider(actor, "dhan", "Case")
    store.close()


def test_openalgo_adapter_has_no_raw_session_client_escape():
    from flinttrade_gateway.brokers.openalgo import OpenAlgoAdapter
    from flinttrade_gateway.session_provider import AuthenticatingSessionProvider, ConnectedSessionClientResolver

    with pytest.raises(TypeError):
        OpenAlgoAdapter(default_client=object())
    with pytest.raises(TypeError):
        OpenAlgoAdapter(client_factory=lambda _: object())
    registry, owner = api.create_owned_registry()
    resolver = ConnectedSessionClientResolver(AuthenticatingSessionProvider(registry, {}), registry)
    with pytest.raises(RegistrySessionUnavailable):
        resolver.openalgo_client(object.__new__(api.ConnectedRegistrySession))


def test_app_and_native_consumers_do_not_access_registry_private_state():
    import inspect
    import re
    from flinttrade_core import app, native_account_routes

    forbidden = re.compile(
        r'(?:registry\._(?:sessions|adapter_sessions|primary|lock)|getattr\(registry, "_(?:sessions|adapter_sessions|primary|lock)")'
    )
    assert not forbidden.search(inspect.getsource(app))
    assert not forbidden.search(inspect.getsource(native_account_routes))


def test_ditto_denies_before_client_allocation(monkeypatch):
    from flinttrade_core.broker_account_cutover import BrokerAccountCutoverUnavailable
    from flinttrade_ditto.runtime import DittoRouterOwner

    with pytest.raises(BrokerAccountCutoverUnavailable):
        DittoRouterOwner([], "test", write_admission=None, intent_journal=None, safety_system=None)


@pytest.mark.asyncio
async def test_native_preparation_is_unpublished_and_guarded():
    from flinttrade_core.broker_account_cutover import BrokerAccountCutoverUnavailable
    from flinttrade_gateway import native_login

    class Adapter:
        calls = 0

        async def login(self, credentials):
            self.calls += 1
            return Session("synthetic", time.time() + 3600, "raw", "dhan")

        async def funds(self, session):
            self.calls += 1
            return {}

    adapter = Adapter()
    with pytest.raises(BrokerAccountCutoverUnavailable):
        await native_login.prepare_native_session(adapter, {}, verify=True)
    assert adapter.calls == 0
    candidate = await native_login.prepare_native_session(adapter, {}, verify=True, mutation_admission=lambda: None)
    assert candidate.session.account_id == "raw" and adapter.calls == 2
    assert "synthetic" not in repr(candidate)


def test_exact_status_is_detached_and_tombstone_has_no_live_metadata(authority):
    registry, owner = api.create_owned_registry()
    selector = BrokerSelector("dhan", "Case")
    assert registry.snapshot_exact_state(selector) is None
    auth = authority(selector)
    receipt, session = prepare(owner, registry, selector, auth)
    result = owner.publish_prepared_candidate(receipt, current_authority=auth)
    status = registry.snapshot_exact_state(selector)
    assert status.expires_at == session.expires_at and status.read_only is False
    owner.remove_session_for_exact(selector, expected_registry=result.version.registry_version)
    tombstone = registry.snapshot_exact_state(selector)
    assert tombstone.status == "tombstoned" and tombstone.expires_at is None and tombstone.read_only is None
    assert status.status == "connected"


@pytest.mark.asyncio
async def test_l2_registry_refusal_does_not_convert_to_empty_safety_data():
    from flinttrade_core.l2_state import PortfolioSafetyStateError, gather_l2_state

    registry = api.BrokerRegistry()

    class Adapter:
        async def positions(self, session):
            pytest.fail("provider must not run")

        async def funds(self, session):
            pytest.fail("provider must not run")

    with pytest.raises(PortfolioSafetyStateError):
        await gather_l2_state({"REGISTRY": registry, "NATIVE_ADAPTERS": {"dhan": Adapter()}}, "dhan", account_id="Case")


def test_reserved_compatibility_retains_telegram_but_rejects_unknown_setup_change(tmp_path):
    from flinttrade_core.config import Settings
    from flinttrade_core.openalgo_client import OpenAlgoClient
    from flinttrade_core.workspace_migrations import read_workspace_snapshot
    from flinttrade_gateway.session_provider import AuthenticatingSessionProvider, ConnectedSessionClientResolver
    from types import SimpleNamespace

    workspace = compare_and_swap_workspace(
        tmp_path,
        None,
        lambda cfg: cfg.update(
            openalgo={
                "host": "https://one.invalid",
                "api_key": "synthetic",
                "port": 443,
                "ws_port": 8765,
            }
        ),
    )
    registry, owner = api.create_owned_registry()
    selector = BrokerSelector("openalgo", "default")
    client = OpenAlgoClient(
        Settings(
            openalgo_host="https://one.invalid", openalgo_api_key="synthetic", openalgo_port=443, openalgo_ws_port=8765
        )
    )

    def seal():
        return owner.seal_openalgo_default_compatibility_authority(read_workspace_snapshot(tmp_path))

    receipt = owner.prepare_openalgo_default_compatibility_candidate(
        Session("", time.time() + 3600, "raw", "openalgo"),
        expected_registry=registry.snapshot_selector(selector),
        authority=seal(),
        client=client,
        broker=None,
        label="Synthetic",
    )
    owner.publish_prepared_candidate(receipt, current_authority=seal())
    provider = AuthenticatingSessionProvider(
        registry,
        {"openalgo": {"default": ["actor"]}},
        workspace_snapshot=workspace,
        workspace_path=tmp_path,
        compatibility_authority_for=seal,
    )
    resolver = ConnectedSessionClientResolver(provider, registry)
    handle = provider(SimpleNamespace(actor_id="actor"), "openalgo", "default")
    assert resolver.openalgo_client(handle) is client
    telegram = compare_and_swap_workspace(
        tmp_path, workspace.version, lambda cfg: cfg["openalgo"].update(telegram_username="synthetic-user")
    )
    assert resolver.openalgo_client(handle) is client
    compare_and_swap_workspace(tmp_path, telegram.version, lambda cfg: cfg["openalgo"].update(unknown_setup="changed"))
    with pytest.raises(RegistrySessionUnavailable):
        resolver.openalgo_client(handle)
    assert "synthetic" not in repr(registry.list_exact_states()[0].binding)
    client.close_sync()


def test_managed_client_cannot_alias_sibling_or_prior_setup(authority):
    registry, owner = api.create_owned_registry()
    a, b = BrokerSelector("openalgo", "A"), BrokerSelector("openalgo", "B")
    client = object()
    first, _ = prepare(owner, registry, a, authority(a), client=client)
    with pytest.raises(RegistrySessionUnavailable):
        prepare(owner, registry, b, authority(b), client=client)
    owner.abandon_prepared_candidate(first)
    with pytest.raises(RegistrySessionUnavailable):
        prepare(owner, registry, b, authority(b), client=client)


@pytest.mark.parametrize("state", ["prepared", "published", "abandoned", "conflicted"])
def test_managed_client_has_one_owner_until_retirement_claim(authority, state):
    registry, owner = api.create_owned_registry()
    _, foreign = api.create_owned_registry()
    selector = BrokerSelector("openalgo", "Case")
    auth = authority(selector)
    client = object()
    receipt, session = prepare(owner, registry, selector, auth, client=client)
    retirement = None
    if state == "published":
        owner.publish_prepared_candidate(receipt, current_authority=auth)
    elif state == "abandoned":
        retirement = owner.abandon_prepared_candidate(receipt)
    elif state == "conflicted":
        owner.remove_session_for_exact(selector, expected_registry=registry.snapshot_selector(selector))
        with pytest.raises(RegistryVersionConflict) as conflict:
            owner.publish_prepared_candidate(receipt, current_authority=auth)
        retirement = conflict.value.retirement_receipt

    # Even identical authority cannot make a second owner of a routable client.
    with pytest.raises(RegistrySessionUnavailable):
        prepare(owner, registry, selector, auth, client=client)
    if state == "published":
        handle = registry.get_connected_session_for(selector, current_authority=api.ManagedLookupAuthority(
            auth.credential_version, auth.broker_workspace_version))
        assert registry.client_for_connected_session(handle, current_authority=api.ManagedLookupAuthority(
            auth.credential_version, auth.broker_workspace_version)) is client
        retirement = owner.remove_session_for_exact(
            selector, expected_registry=registry.snapshot_selector(selector)).retired
    elif state == "prepared":
        retirement = owner.abandon_prepared_candidate(receipt)
    with pytest.raises(RegistryCapabilityError):
        foreign.claim_retired_candidate(retirement)
    with pytest.raises(RegistrySessionUnavailable):
        prepare(owner, registry, selector, auth, client=client)
    transferred = owner.claim_retired_candidate(retirement)
    assert transferred.client is client
    assert transferred.session is session
    # The claimant may transfer the now-unowned resource back explicitly.
    fresh, _ = prepare(owner, registry, selector, auth, client=transferred.client)
    owner.publish_prepared_candidate(fresh, current_authority=auth)


def test_reserved_default_client_remains_borrowed_during_retirement(tmp_path):
    registry, owner = api.create_owned_registry()
    workspace = compare_and_swap_workspace(tmp_path, None, lambda config: None)
    authority = owner.seal_openalgo_default_compatibility_authority(workspace)
    selector = BrokerSelector("openalgo", "default")
    client = object()

    def candidate():
        return owner.prepare_openalgo_default_compatibility_candidate(
            Session("synthetic", 4102444800, "raw", "openalgo"),
            expected_registry=registry.snapshot_selector(selector), authority=authority,
            client=client, broker=None, label="Synthetic")

    owner.publish_prepared_candidate(candidate(), current_authority=authority)
    retired = owner.abandon_prepared_candidate(candidate())
    assert owner.claim_retired_candidate(retired).client is client
    assert registry.snapshot_exact_state(selector).status == "connected"


def test_receipt_seals_do_not_accumulate_on_lookup(tmp_path):
    import gc
    import weakref

    registry, owner = api.create_owned_registry()
    workspace = compare_and_swap_workspace(tmp_path, None, lambda cfg: None)
    receipt = owner.seal_openalgo_default_compatibility_authority(workspace)
    observed = weakref.ref(receipt)
    del receipt
    gc.collect()
    assert observed() is None


@pytest.mark.parametrize("expiry", [True, False, float("inf"), float("nan"), "tomorrow", None])
def test_mutated_canonical_expiry_cannot_render_or_route_as_connected(authority, expiry):
    registry, owner = api.create_owned_registry()
    selector = BrokerSelector("dhan", "Case")
    auth = authority(selector)
    receipt, session = prepare(owner, registry, selector, auth)
    owner.publish_prepared_candidate(receipt, current_authority=auth)
    session.expires_at = expiry
    state = registry.snapshot_exact_state(selector)
    assert state.status == "disconnected"
    assert state.expires_at is None
    assert state.read_only is None
    with pytest.raises(RegistrySessionUnavailable):
        registry.get_connected_session_for(
            selector,
            current_authority=api.ManagedLookupAuthority(auth.credential_version, auth.broker_workspace_version),
        )


def test_claim_transfers_client_ownership_without_registry_retention(authority):
    import gc
    import weakref

    class Client:
        pass

    registry, owner = api.create_owned_registry()
    selector = BrokerSelector("openalgo", "Case")
    auth = authority(selector)
    client = Client()
    reference = weakref.ref(client)
    receipt, _ = prepare(owner, registry, selector, auth, client=client)
    retirement = owner.abandon_prepared_candidate(receipt)
    del client
    gc.collect()
    assert reference() is not None
    payload = owner.claim_retired_candidate(retirement)
    del payload
    gc.collect()
    assert reference() is None


def test_client_factory_is_not_a_concrete_candidate(authority):
    from flinttrade_core.account_mutation_contracts import RegistryVersionValidationError

    registry, owner = api.create_owned_registry()
    selector = BrokerSelector("openalgo", "Case")
    calls = []

    def factory():
        calls.append(1)
        raise AssertionError("factory must not run")

    with pytest.raises(RegistryVersionValidationError):
        prepare(owner, registry, selector, authority(selector), client=factory)
    assert calls == []


def test_registry_exhaustion_does_not_wrap_or_overwrite(authority, monkeypatch):
    # Lower only the registry increment ceiling so actual owned state reaches it.
    # Canonical DTO validation still uses the real signed-64-bit range.
    monkeypatch.setattr(api, "INT64_MAX", 1)
    registry, owner = api.create_owned_registry()
    selector = BrokerSelector("dhan", "Case")
    auth = authority(selector)
    receipt, _ = prepare(owner, registry, selector, auth)
    published = owner.publish_prepared_candidate(receipt, current_authority=auth)
    with pytest.raises(RegistryVersionConflict):
        owner.remove_session_for_exact(selector, expected_registry=published.version.registry_version)
    second, _ = prepare(owner, registry, selector, auth)
    with pytest.raises(RegistryVersionConflict) as error:
        owner.publish_prepared_candidate(second, current_authority=auth)
    assert error.value.retirement_receipt is not None
    assert registry.snapshot_selector(selector) == published.version.registry_version


def test_forged_foreign_and_replayed_handles_never_resolve_client(authority):
    registry, owner = api.create_owned_registry()
    foreign, foreign_owner = api.create_owned_registry()
    selector = BrokerSelector("openalgo", "Case")
    auth = authority(selector)
    lookup = api.ManagedLookupAuthority(auth.credential_version, auth.broker_workspace_version)
    for target, holder in ((registry, owner), (foreign, foreign_owner)):
        receipt, _ = prepare(holder, target, selector, auth, client=object())
        holder.publish_prepared_candidate(receipt, current_authority=auth)
    real = registry.get_connected_session_for(selector, current_authority=lookup)
    forged = object.__new__(api.ConnectedRegistrySession)
    other = foreign.get_connected_session_for(selector, current_authority=lookup)
    for invalid in (forged, other, Session("secret", 4102444800.0, "Case", "openalgo")):
        with pytest.raises(RegistrySessionUnavailable):
            registry.client_for_connected_session(invalid, current_authority=lookup)
    owner.remove_session_for_exact(selector, expected_registry=real.version.registry_version)
    receipt, _ = prepare(owner, registry, selector, auth, client=object())
    owner.publish_prepared_candidate(receipt, current_authority=auth)
    with pytest.raises(RegistrySessionUnavailable):
        registry.client_for_connected_session(real, current_authority=lookup)


@pytest.mark.asyncio
async def test_distinct_concrete_clients_ignore_raw_identity_and_setup_aba(tmp_path, monkeypatch, *, backend_lease_factory):
    import importlib.util
    from pathlib import Path
    from flinttrade_core.config import Settings
    from flinttrade_core.openalgo_client import OpenAlgoClient

    spec = importlib.util.spec_from_file_location(
        "_exact_fixtures", Path(__file__).parents[4] / "tests" / "registry_fixtures.py"
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    fixture = module.RegistryFixture(tmp_path)
    calls = []
    clients = [
        OpenAlgoClient(Settings(openalgo_host=f"https://client-{i}.invalid", openalgo_api_key=f"synthetic-{i}"))
        for i in (1, 2)
    ]
    try:
        adapters, handles = [], []
        for i, client in enumerate(clients):

            async def funds(index=i):
                calls.append(index)
                return {"source": index}

            monkeypatch.setattr(client, "funds", funds)
            adapter, handle = module.exact_openalgo_adapter(fixture, client, account=f"account-{i}")
            handle.extra["account_id"] = "other"
            handle.extra["api_key"] = "wrong-key"
            adapters.append(adapter)
            handles.append(handle)
        assert await adapters[0].funds(handles[0]) == {"source": 0}
        assert await adapters[1].funds(handles[1]) == {"source": 1}
        from types import SimpleNamespace
        from flinttrade_engine import safety
        from flinttrade_engine.request_context import RequestContext
        from flinttrade_gateway.router import BrokerRouter
        from flinttrade_gateway.session_provider import AuthenticatingSessionProvider
        monkeypatch.setattr(safety, "_SAFETY_GATE_SECRET", b"s" * 32)
        provider = AuthenticatingSessionProvider(fixture.registry,
            {"openalgo": {f"account-{i}": ["test-actor"] for i in (0, 1)}},
            workspace_snapshot=fixture.workspace, workspace_path=tmp_path,
            credential_version_for=lambda exact: fixture.store.selector_state(exact).version)
        router = BrokerRouter({"openalgo": adapters[0]}, provider, consume_gate=safety.SafetyGate().consume, backend_lease_proof=backend_lease_factory())
        for i, client in enumerate(clients):
            async def place(order, index=i):
                calls.append(("order", index))
                return SimpleNamespace(status="success", orderid=f"synthetic-{index}")
            monkeypatch.setattr(client, "place_order", place)
            context = RequestContext(jti=f"synthetic-{i}", actor_type="human", actor_id="test-actor", mode="live")
            order = SimpleNamespace(symbol="SYNTHETIC", exchange="NSE", action="BUY", quantity=1, pricetype="MARKET")
            permit = safety.gate_order(order, context, "openalgo", account_id=f"account-{i}", backend_lease_proof=backend_lease_factory())
            assert await router.place_order(context, adapter_id="openalgo", account_id=f"account-{i}",
                order=order, safety_ctx=permit) == f"synthetic-{i}"
        selector = handles[0].selector
        before = fixture.store.selector_state(selector).version
        creds = fixture.store.retrieve_credentials(selector)
        fixture.store.update_credentials(selector, creds, expected=before)
        assert fixture.store.selector_state(selector).version.generation == before.generation + 1
        with pytest.raises(RegistrySessionUnavailable):
            await adapters[0].funds(handles[0])
        with pytest.raises(RegistrySessionUnavailable):
            fixture.publish(
                selector.adapter_id,
                selector.account_id,
                Session("secret", 4102444800.0, "raw", "openalgo"),
                client=clients[0],
            )
        assert calls == [0, 1, ("order", 0), ("order", 1)]
    finally:
        for client in clients:
            await client.close()
        fixture.close()
