"""Shared native history uses real read authority; HTTP cutover stays closed."""
from __future__ import annotations

import time

from datetime import UTC, datetime
from threading import Event
from uuid import uuid4

import pytest

from flinttrade_core.app import _BrokerRuntimeDependencies
from flinttrade_core.broker_identity import BrokerSelector, CredentialVersion
from flinttrade_core.broker_read_port import HistoricalRequest, InstrumentRef
from flinttrade_core.workspace_migrations import broker_workspace_version, compare_and_swap_workspace
from flinttrade_gateway.broker_read_service import create_broker_read_owner
from flinttrade_gateway.brokers._base import Session
from flinttrade_gateway.brokers.dhan import DhanAdapter
from flinttrade_gateway.registry import ManagedSessionAuthority, create_owned_registry
from flinttrade_gateway.routing_config import RoutingConfig
from flinttrade_gateway.session_provider import AuthenticatingSessionProvider
from packages.core.core.tests.test_data_runtime import install, mounted  # noqa: F401
from packages.core.historical.tests.test_history_manifest import history_input

pytestmark = pytest.mark.integration


@pytest.fixture
def native(mounted):  # noqa: F811 - imported real factory fixture
    app, client, root, headers = mounted
    calls, entered, finish = [], Event(), Event()
    finish.set()
    registry, publication = create_owned_registry()
    selector = BrokerSelector("dhan", "Synthetic")
    def configure(config):
        config["brokers"]["registered"] = ["dhan:Synthetic"]
        config["brokers"]["data"]["historical"] = "dhan:Synthetic"
        config["brokers"]["account_acls"] = {"dhan": {"Synthetic": ["operator"]}}
    from flinttrade_core.workspace_migrations import read_workspace_snapshot
    workspace = compare_and_swap_workspace(root, read_workspace_snapshot(root).version, configure)
    credential = CredentialVersion(selector, uuid4(), 1)
    authority = ManagedSessionAuthority(credential, workspace.version, broker_workspace_version(workspace))
    class SDK:
        def intraday_minute_data(self, security_id, exchange_segment, instrument_type, from_date, to_date, interval):
            args = (security_id, exchange_segment, instrument_type, from_date, to_date, interval)
            assert args == ("101", "NSE_EQ", "EQUITY", "2026-01-05", "2026-01-05", 1)
            calls.append(args)
            entered.set()
            assert finish.wait(8)
            return {"status": "success", "data": {
                "timestamp": [int(datetime(2026, 1, 5, 14, 30, tzinfo=UTC).timestamp())],
                "open": [100], "high": [102], "low": [99], "close": [101], "volume": [5]}}
    sdk = SDK()
    candidate = publication.prepare_session_candidate(
        selector, Session("inert-session", time.time() + 3600, "Synthetic", "dhan"),
        expected_registry=registry.snapshot_selector(selector), authority=authority,
        broker="dhan", label="Synthetic", client=sdk)
    publication.publish_prepared_candidate(candidate, current_authority=authority)
    routing = RoutingConfig.from_workspace(workspace.as_dict()["brokers"])
    provider = AuthenticatingSessionProvider(registry, routing.account_acls, workspace_snapshot=workspace,
        workspace_path=root, credential_version_for=lambda target: credential if target == selector else None)
    adapter = DhanAdapter(client_factory=lambda session: sdk, security_resolver=lambda symbol, exchange: "101")
    adapters = {"dhan": adapter}
    owner = create_broker_read_owner(registry=registry, session_provider=provider, adapters=adapters,
        workspace_path=root, rate_limiter=None, runtime_accepting_requests=lambda: True)
    from flinttrade_core.broker_client import BrokerClient
    broker_client = BrokerClient()
    replacement = _BrokerRuntimeDependencies(registry=registry, config=routing, session_provider=provider,
        adapters=adapters, native_adapters=adapters, brokers_config=workspace.as_dict()["brokers"],
        broker_client=broker_client, rate_limiter=None, lifecycle_store=None,
        workspace_snapshot=workspace, workspace_path=root, registry_publication_owner=publication, read_owner=owner)
    assert isinstance(replacement, _BrokerRuntimeDependencies)
    app.extensions["flinttrade_broker_dependencies"] = replacement
    app.extensions["flinttrade.registry_publication_owner"] = publication
    app.config.update(REGISTRY=registry, ACTIVE_BROKER_ADAPTERS=adapters, CLIENT=broker_client, BROKER_CLIENT=broker_client)
    runtime = install(app, root)
    identity, _, policy, _ = history_input()
    identity.update(instrument_id="declared-dhan-test", native_symbol="TCS", native_exchange="NSE",
                    native_timestamp_encoding="unix_seconds")
    policy.update(priority=["dhan:Synthetic"], sessions=[{"start": "2026-01-05T14:30:00+00:00",
                                                      "end": "2026-01-05T14:31:00+00:00"}])
    query = HistoricalRequest(InstrumentRef("TCS", "NSE", "declared-dhan-test"), "1m", "2026-01-05", "2026-01-05")
    try:
        yield runtime, app, client, headers, identity, policy, query, owner, registry, publication, calls, entered, finish
    finally:
        finish.set()
        runtime.close()
        owner.close(timeout=5)
        import asyncio
        asyncio.run(broker_client.close())


def test_real_native_source_is_shared_but_http_stays_frozen(native):
    runtime, app, client, headers, identity, policy, query, owner, registry, publication, calls, entered, finish = native
    assert callable(getattr(runtime, "acquire_native_history", None)), "native read owner is not composed"
    with app.app_context():
        one = runtime.acquire_native_history(identity=identity, query=query, policy=policy,
                                             token=headers["Authorization"][7:])
        two = runtime.acquire_native_history(identity=identity, query=query, policy=policy,
                                             token=headers["Authorization"][7:])
    assert entered.wait(3)
    deadline = time.monotonic() + 3
    scope = one["snapshot"]["scope"]
    while time.monotonic() < deadline:
        frame = runtime.acquisition.read(one["lease_id"], scope=scope)
        if frame["payload"] is not None:
            break
        time.sleep(0.02)
    assert frame["payload"]["bars"][0]["close"] == 101
    assert len(calls) == 1
    assert scope["account_id"] == "dhan:Synthetic"
    from flinttrade_core.auth_routes import decode_token
    with app.app_context():
        assert scope["environment"] == decode_token(headers["Authorization"][7:])["mode"]
    assert scope["run_id"] is None
    assert frame["source"]["auth_generation"] == 1
    assert frame["published_at"] is None
    assert client.post("/api/v1/data/leases", headers=headers, json={"dataset_id": "native:historical"}).status_code == 503
    assert len(calls) == 1
    assert runtime.acquisition.release(one["lease_id"], scope=scope)
    assert runtime.active_sources == 1
    assert runtime.acquisition.release(two["lease_id"], scope=scope)
    assert runtime.active_sources == 0


def test_native_cancel_retains_blocked_exact_source_until_shutdown_retry(native):
    runtime, app, client, headers, identity, policy, query, owner, registry, publication, calls, entered, finish = native
    finish.clear()
    try:
        with app.app_context():
            lease = runtime.acquire_native_history(identity=identity, query=query, policy=policy,
                                                   token=headers["Authorization"][7:])
        assert entered.wait(3)
        with pytest.raises(RuntimeError, match="draining"):
            runtime.close()
        assert runtime.active_sources == 1
        assert not runtime.closed
        assert client.get("/api/v1/data/portfolio/evidence", headers=headers).status_code == 503
        # The dependent store is deliberately still open until the real read returns.
        assert runtime.history.connection.execute("SELECT 1").fetchone() == (1,)
    finally:
        finish.set()
    runtime.close()
    assert runtime.closed
    assert runtime.active_sources == 0
    assert len(calls) == 1
    with pytest.raises(KeyError):
        runtime.acquisition.read(lease["lease_id"], scope=lease["snapshot"]["scope"])


def test_native_disconnect_retires_source_without_account_retarget(native):
    runtime, app, _, headers, identity, policy, query, owner, registry, publication, calls, entered, finish = native
    with app.app_context():
        lease = runtime.acquire_native_history(identity=identity, query=query, policy=policy,
                                               token=headers["Authorization"][7:])
    assert entered.wait(3)
    selector = BrokerSelector("dhan", "Synthetic")
    publication.remove_session_for_exact(selector, expected_registry=registry.snapshot_selector(selector))
    deadline = time.monotonic() + 3
    while runtime.active_sources and time.monotonic() < deadline:
        time.sleep(0.02)
    assert runtime.active_sources == 0
    with pytest.raises((KeyError, PermissionError)):
        runtime.acquisition.read(lease["lease_id"], scope=lease["snapshot"]["scope"])
    with app.app_context(), pytest.raises(Exception):
        runtime.acquire_native_history(identity=identity, query=query, policy=policy, token=headers["Authorization"][7:])
    assert len(calls) == 1


@pytest.mark.parametrize("missing", ["calendar_revision", "currency", "native_symbol", "native_timestamp_encoding"])
def test_native_missing_qualification_refuses_before_transport(native, missing):
    runtime, app, _, headers, identity, policy, query, owner, registry, publication, calls, entered, finish = native
    identity.pop(missing)
    with app.app_context(), pytest.raises(ValueError):
        runtime.acquire_native_history(identity=identity, query=query, policy=policy, token=headers["Authorization"][7:])
    assert calls == []


def test_native_history_pins_calendar_before_blocked_transport(native):
    runtime, app, _, headers, identity, policy, query, owner, registry, publication, calls, entered, finish = native
    finish.clear()
    try:
        with app.app_context():
            lease = runtime.acquire_native_history(identity=identity, query=query, policy=policy,
                                                   token=headers["Authorization"][7:])
        assert entered.wait(3)
        policy["revision"] = "mutated-after-dispatch"
        policy["sessions"][0]["end"] = "2026-01-05T14:32:00+00:00"
    finally:
        finish.set()
    deadline = time.monotonic() + 3
    frame = None
    while time.monotonic() < deadline:
        frame = runtime.acquisition.read(lease["lease_id"], scope=lease["snapshot"]["scope"])
        if frame["payload"]:
            break
        time.sleep(0.02)
    assert frame["payload"]["coverage"]["expected"] == 1
    assert frame["payload"]["policy"]["revision"] == "test-policy-1"
