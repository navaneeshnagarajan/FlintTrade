"""Disposable real authorities for exact registry integration tests."""

from flinttrade_core.broker_identity import BrokerSelector
from flinttrade_core.secure_file import harden_directory
from flinttrade_core.workspace_migrations import (
    broker_workspace_version,
    compare_and_swap_workspace,
    read_workspace_snapshot,
)
from flinttrade_gateway.credentials import CredentialStore
from flinttrade_gateway.registry import ManagedLookupAuthority, ManagedSessionAuthority, create_owned_registry


class RegistryFixture:
    """Explicit owner, registry and genuine workspace/vault; no private map injection."""

    def __init__(self, path):
        path.mkdir(parents=True, exist_ok=True)
        harden_directory(path)
        self.path = path
        self.workspace = (
            read_workspace_snapshot(path)
            if (path / "workspace.json").exists()
            else compare_and_swap_workspace(path, None, lambda config: None)
        )
        self.store = CredentialStore(path / "registry-vault.db", "synthetic-test-password")
        self.registry, self.owner = create_owned_registry()

    def authority(self, selector):
        state = self.store.selector_state(selector)
        if not state.present or not state.credential_present:
            raise RuntimeError("fixture credential missing")
        workspace = read_workspace_snapshot(self.path)
        return ManagedSessionAuthority(state.version, workspace.version, broker_workspace_version(workspace))

    def publish(self, adapter, account, session, *, broker=None, label="Synthetic", client=None):
        selector = BrokerSelector(adapter, account)
        state = self.store.selector_state(selector)
        if not state.present:
            self.store.put_credentials(
                selector, broker or adapter, label, {"token": "synthetic"}, expected=state.version
            )
        authority = self.authority(selector)
        receipt = self.owner.prepare_session_candidate(
            selector,
            session,
            expected_registry=self.registry.snapshot_selector(selector),
            authority=authority,
            broker=broker or adapter,
            label=label,
            client=client,
        )
        return self.owner.publish_prepared_candidate(receipt, current_authority=self.authority(selector))

    def session(self, adapter, account):
        selector = BrokerSelector(adapter, account)
        authority = self.authority(selector)
        return self.registry.get_connected_session_for(
            selector,
            current_authority=ManagedLookupAuthority(authority.credential_version, authority.broker_workspace_version),
        )

    def close(self):
        self.store.close()


def exact_openalgo_adapter(fixture, client, *, account="test-account", **kwargs):
    """Formatting/adapter tests still cross the real sealed-client boundary."""
    from flinttrade_gateway.brokers._base import Session
    from flinttrade_gateway.brokers.openalgo import OpenAlgoAdapter
    from flinttrade_gateway.session_provider import AuthenticatingSessionProvider, ConnectedSessionClientResolver

    fixture.publish("openalgo", account, Session("test-key", 4102444800.0, account, "openalgo"), client=client)
    provider = AuthenticatingSessionProvider(
        fixture.registry,
        {"openalgo": {account: ["test-actor"]}},
        workspace_snapshot=read_workspace_snapshot(fixture.path),
        workspace_path=fixture.path,
        credential_version_for=lambda selector: fixture.store.selector_state(selector).version,
    )
    adapter = OpenAlgoAdapter(session_clients=ConnectedSessionClientResolver(provider, fixture.registry), **kwargs)
    return adapter, fixture.session("openalgo", account)
