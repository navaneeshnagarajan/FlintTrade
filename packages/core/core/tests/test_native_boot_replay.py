"""Native replay wiring evidence with genuine disposable registry authority.

Native selectors must never use the legacy bridge authenticator. The native
wrapper forwards the exact owner and durable path, including inside an event loop.
"""

from __future__ import annotations

import asyncio
import importlib.util
import logging
from pathlib import Path
from types import SimpleNamespace

import pytest

from flinttrade_core.broker_identity import BrokerSelector, parse_broker_selector, serialise_broker_selector
from flinttrade_core.workspace_migrations import compare_and_swap_workspace

_fixture_spec = importlib.util.spec_from_file_location(
    "_registry_fixtures", Path(__file__).resolve().parents[4] / "tests" / "registry_fixtures.py"
)
_fixture_module = importlib.util.module_from_spec(_fixture_spec)
_fixture_spec.loader.exec_module(_fixture_module)
RegistryFixture = _fixture_module.RegistryFixture


@pytest.fixture
def authority(tmp_path, monkeypatch):
    monkeypatch.setenv("FLINTTRADE_WORKSPACE_DIR", str(tmp_path))
    fixture = RegistryFixture(tmp_path)
    yield fixture
    fixture.close()


def test_reconnect_saved_accounts_skips_native_rows(monkeypatch, authority):
    from flinttrade_core.app import _reconnect_saved_accounts

    native = BrokerSelector("dhan", "D1")
    bridge = BrokerSelector("openalgo", "OA1")
    for selector, broker in ((native, "dhan"), (bridge, "zerodha")):
        authority.store.put_credentials(
            selector, broker, "Synthetic", {"api_key": selector.account_id},
            expected=authority.store.selector_state(selector).version,
        )
    workspace = compare_and_swap_workspace(
        authority.path, authority.workspace.version,
        lambda config: config["brokers"]["execution"].update({"default": serialise_broker_selector(bridge)}),
    )
    calls = []

    class BridgeAdapter:
        def authenticate(self, credentials):
            calls.append(credentials["api_key"])
            return "synthetic-token", None

    def load_adapter(broker):
        assert broker == "zerodha", "Native rows must never reach the bridge loader"
        return BridgeAdapter()

    monkeypatch.setattr("flinttrade_gateway.session.load_broker_adapter", load_adapter)
    _reconnect_saved_accounts(
        authority.registry, authority.store, logging.getLogger("test.replay"),
        mutation_admission=lambda: None, registry_publication_owner=authority.owner,
        workspace_path=authority.path,
        execution_default_selector=parse_broker_selector(workspace.as_dict()["brokers"]["execution"]["default"]),
    )

    assert calls == ["OA1"]
    assert authority.registry.snapshot_selector(native).generation == 0
    assert authority.registry.snapshot_exact_state(bridge).status == "connected"
    assert authority.registry.get_primary_session().info.account_id == "OA1"


def _replay_app(authority, native_adapters, selectors):
    compare_and_swap_workspace(
        authority.path, authority.workspace.version,
        lambda config: config["brokers"].update({"registered": selectors}),
    )
    return SimpleNamespace(
        config={
            "BROKER_ACCOUNT_MUTATION_ADMISSION": lambda: None,
            "NATIVE_ADAPTERS": native_adapters,
            "REGISTRY": authority.registry,
            "CREDENTIAL_STORE": authority.store,
        },
        extensions={"flinttrade.registry_publication_owner": authority.owner},
    )


def test_reestablish_native_sessions_runs_inside_existing_event_loop(monkeypatch, authority):
    from flinttrade_core import app as app_module

    object_marker = {"dhan": object(), "upstox": object()}
    selectors = ["dhan:D1", "upstox:U1", "indmoney:I1", "kotakneo:K1", "groww:G1"]
    fake_app = _replay_app(authority, object_marker, selectors)

    async def fake_establish(
        native_adapters, registry, credential_store, received_selectors, *,
        verify=False, mutation_admission=None, registry_publication_owner=None, workspace_path=None,
    ):
        # Wrapper wiring evidence only; actual replay/activation refusals have
        # separate real-registry tests. This fake invokes no provider.
        assert native_adapters == object_marker
        assert registry is authority.registry
        assert credential_store is authority.store
        assert registry_publication_owner is authority.owner
        assert workspace_path == authority.path
        assert received_selectors == selectors
        assert verify is True
        mutation_admission()
        return {"dhan:D1": "ok", "upstox:U1": "ok"}

    monkeypatch.setattr("flinttrade_gateway.native_login.establish_native_sessions", fake_establish)

    async def run_from_loop():
        return app_module._reestablish_native_sessions(fake_app, verify=True)

    assert asyncio.run(run_from_loop()) == {"dhan:D1": "ok", "upstox:U1": "ok"}
    assert fake_app.config["NATIVE_SESSION_STATUS"] == {"dhan:D1": "ok", "upstox:U1": "ok"}
    assert authority.registry.list_exact_states() == ()


def test_reestablish_native_sessions_verifies_by_default(monkeypatch, authority):
    from flinttrade_core import app as app_module

    seen = {}
    fake_app = _replay_app(authority, {"upstox": object()}, ["upstox:U1"])

    async def fake_establish(
        native_adapters, registry, credential_store, selectors, *,
        verify=False, mutation_admission=None, registry_publication_owner=None, workspace_path=None,
    ):
        seen["verify"] = verify
        assert selectors == ["upstox:U1"]
        assert registry is authority.registry
        assert credential_store is authority.store
        assert registry_publication_owner is authority.owner
        assert workspace_path == authority.path
        mutation_admission()
        return {"upstox:U1": "ok"}

    monkeypatch.setattr("flinttrade_gateway.native_login.establish_native_sessions", fake_establish)

    assert app_module._reestablish_native_sessions(fake_app) == {"upstox:U1": "ok"}
    assert seen == {"verify": True}
    assert fake_app.config["NATIVE_SESSION_STATUS"] == {"upstox:U1": "ok"}
    assert authority.registry.list_exact_states() == ()
