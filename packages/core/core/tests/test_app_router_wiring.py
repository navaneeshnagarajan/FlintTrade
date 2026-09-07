"""T6 (gap G1): config-driven BrokerRouter assembled at app startup.

``build_broker_router`` parses workspace.json.brokers into a RoutingConfig,
wires the AuthenticatingSessionProvider over its account_acls and a one-shot
SafetyGate, and is strict (raises on a malformed config). The create_flask_app
wrapper is resilient (covered by the app construction suite): a bad config logs
and leaves BROKER_ROUTER unset rather than bricking the app.
"""

from __future__ import annotations

import importlib.util
from pathlib import Path
from flinttrade_core.account_mutation_contracts import RegistrySessionUnavailable
from flinttrade_core.broker_identity import BrokerSelector
from flinttrade_gateway.brokers._base import Session
from flinttrade_core.workspace_migrations import read_workspace_snapshot

from collections.abc import Callable
import threading
from types import SimpleNamespace
from typing import Any
from unittest.mock import MagicMock

from flask import Flask
import pytest

from flinttrade_core.app import build_broker_router
from flinttrade_core.workspace_migrations import default_workspace_config
from flinttrade_gateway.registry import BrokerRegistry
from flinttrade_gateway.router import BrokerRouter
from flinttrade_gateway.routing_config import RoutingConfig, RoutingConfigError
from flinttrade_gateway.session_provider import AuthenticatingSessionProvider



_fixture_spec = importlib.util.spec_from_file_location("_registry_fixtures", Path(__file__).resolve().parents[4] / "tests" / "registry_fixtures.py")
_fixture_module = importlib.util.module_from_spec(_fixture_spec)
_fixture_spec.loader.exec_module(_fixture_module)
RegistryFixture = _fixture_module.RegistryFixture


_BRIDGE_FIXTURES = []


@pytest.fixture(autouse=True)
def _close_bridge_fixtures():
    yield
    for fixture, client in _BRIDGE_FIXTURES:
        client.close_sync()
        fixture.close()
    _BRIDGE_FIXTURES.clear()


def _bridge_fixture(path, app=None):
    from flinttrade_core.config import Settings
    from flinttrade_core.openalgo_client import OpenAlgoClient
    fixture = RegistryFixture(path)
    config = read_workspace_snapshot(path).as_dict()["openalgo"]
    client = OpenAlgoClient(Settings(openalgo_host=config["host"], openalgo_api_key=config["api_key"],
        openalgo_port=int(config["port"]), openalgo_ws_port=int(config["ws_port"])))
    if app is not None:
        app.extensions["flinttrade.registry_publication_owner"] = fixture.owner
        app.config["REGISTRY"] = fixture.registry
    _BRIDGE_FIXTURES.append((fixture, client))
    return fixture, client


def _build_bridge(path, **kwargs):
    from flinttrade_core.workspace import Workspace
    workspace = Workspace(path)
    workspace.initialise()
    workspace.set("openalgo.api_key", "synthetic-key")
    fixture, client = _bridge_fixture(path)
    snapshot = read_workspace_snapshot(path)
    router = build_broker_router(fixture.registry, snapshot.as_dict()["brokers"],
        openalgo_client=client, workspace_snapshot=snapshot, workspace_path=path,
        registry_publication_owner=fixture.owner, **kwargs)
    return router, fixture


def _owned_registry(app):
    from flinttrade_gateway.registry import create_owned_registry
    if "TEST_REGISTRY" not in app.config:
        registry, owner = create_owned_registry()
        app.config["TEST_REGISTRY"] = registry
        app.extensions["flinttrade.registry_publication_owner"] = owner
    app.config["REGISTRY"] = app.config["TEST_REGISTRY"]
    return app.config["TEST_REGISTRY"]


@pytest.mark.parametrize("composition", ["internal", "injected"])
def test_app_constructor_retains_its_matching_publication_owner(tmp_path, monkeypatch, composition):
    from flinttrade_core.app import create_flask_app
    from flinttrade_gateway.registry import create_owned_registry, RegistryPublicationOwner

    monkeypatch.setenv("FLINTTRADE_WORKSPACE_DIR", str(tmp_path))
    registry, owner = create_owned_registry()
    kwargs = {"registry": registry, "registry_publication_owner": owner} if composition == "injected" else {}
    app = create_flask_app(**kwargs)
    retained = app.extensions["flinttrade.registry_publication_owner"]
    assert type(retained) is RegistryPublicationOwner
    assert retained.owns(app.config["REGISTRY"])
    if composition == "injected":
        assert app.config["REGISTRY"] is registry
        assert retained is owner


@pytest.mark.parametrize("composition", ["missing", "foreign", "wrong_type", "owner_only"])
@pytest.mark.parametrize("safety_mode", ["default", "injected"])
def test_app_constructor_refuses_unowned_registry_before_application_work(
    tmp_path, monkeypatch, composition, safety_mode,
):
    import flinttrade_core.app as app_module
    from flinttrade_gateway.registry import create_owned_registry

    monkeypatch.setenv("FLINTTRADE_WORKSPACE_DIR", str(tmp_path))
    registry, owner = create_owned_registry()
    _, foreign = create_owned_registry()
    owners = {"missing": None, "foreign": foreign, "wrong_type": object(), "owner_only": owner}
    downstream = []

    def forbidden():
        downstream.append("workspace")
        raise AssertionError("workspace access before ownership validation")

    class UninspectedSafety:
        @property
        def order_reservations_durable(self):
            downstream.append("safety")
            raise AssertionError("safety inspection before ownership validation")

    # These are the first boundaries of the default and injected safety paths,
    # well before Flask, filesystem hygiene, logging and gateway construction.
    monkeypatch.setattr(app_module, "_workspace_dir", forbidden)
    with pytest.raises(RegistrySessionUnavailable, match="^registry_session_unavailable$"):
        app_module.create_flask_app(safety=None if safety_mode == "default" else UninspectedSafety(),
            registry=None if composition == "owner_only" else registry,
            registry_publication_owner=owners[composition])
    assert downstream == []
    assert list(tmp_path.iterdir()) == []


def _mark_router_prerequisites_ready(app: Flask, *, admission: object | None = None) -> object:
    guard = admission or MagicMock(name="broker_write_admission")
    app.config.update(
        EMERGENCY_INTENT_JOURNAL_READY=True,
        EMERGENCY_INTENT_JOURNAL=object(),
        DAILY_PNL_STATE_READY=True,
        DAILY_PNL_STATE_STORE=object(),
        SAFETY_CONFIG_READY=True,
        EMERGENCY_DISPATCHER=object(),
        EMERGENCY_RUNTIME_READY=True,
        SAFETY=SimpleNamespace(
            broker_write_admission=guard,
            order_reservations_durable=True,
        ),
    )
    return guard


@pytest.mark.parametrize("key,value,stales", [
    ("services.connection_epoch", 1, False), ("llm.model", "fixture", False),
    ("openalgo.telegram_username", "fixture-user", False),
    ("brokers.execution.default", "openalgo:sibling", True),
    ("brokers.registered", ["openalgo:default", "openalgo:sibling", "openalgo:new"], True),
    ("brokers.account_acls.openalgo.default", ["operator", "another"], True),
    ("brokers.data.ticks", "openalgo:sibling", True),
    ("openalgo.api_key", "fixture-key", True), ("openalgo.host", "https://fixture.invalid", True),
])
def test_app_rebuild_never_rebinds_managed_siblings(tmp_path, monkeypatch, key, value, stales):
    import flinttrade_core.app as app_module
    from flinttrade_core.workspace import Workspace
    from flinttrade_engine.request_context import RequestContext

    monkeypatch.setenv("FLINTTRADE_WORKSPACE_DIR", str(tmp_path))
    ws = Workspace(tmp_path)
    ws.initialise()
    def configure_accounts(config):
        config["openalgo"]["api_key"] = "initial-key"
        config["brokers"]["registered"] = ["openalgo:default", "openalgo:sibling"]
        config["brokers"]["account_acls"] = {"openalgo": {"default": ["operator"], "sibling": ["operator"]}}
    ws.update(configure_accounts)
    app = Flask("workspace-liveness")
    _mark_router_prerequisites_ready(app)
    monkeypatch.setattr(app_module, "_native_activation_checks", lambda _store: (lambda _aid: False, lambda _aid: False))
    exact, client = _bridge_fixture(tmp_path, app)
    registry = exact.registry
    exact.publish("openalgo", "sibling", Session("synthetic", 4102444800.0, "sibling", "openalgo"), client=object())
    assert app_module.configure_broker_router(app, registry, exact.store, client)
    old = app.config["BROKER_ROUTER"]
    context = RequestContext(jti="fixture", actor_type="human", actor_id="operator", mode="explore")
    assert old._session_provider(context, "openalgo", "sibling").account_id == "sibling"

    ws.set(key, value)
    if not stales:
        assert old._session_provider(context, "openalgo", "sibling").account_id == "sibling"
        return
    with pytest.raises(RegistrySessionUnavailable):
        old._session_provider(context, "openalgo", "sibling")
    if key.startswith("openalgo."):
        from flinttrade_core.config import Settings
        cfg = read_workspace_snapshot(tmp_path).as_dict()["openalgo"]
        client.reconfigure(Settings(openalgo_host=cfg["host"], openalgo_api_key=cfg["api_key"],
            openalgo_port=int(cfg["port"]), openalgo_ws_port=int(cfg["ws_port"])))
    assert app_module.configure_broker_router(app, registry, exact.store, client)
    rebound = app.config["BROKER_ROUTER"]
    assert rebound is not old
    assert rebound._session_provider(context, "openalgo", "default").account_id == "default"
    with pytest.raises(RegistrySessionUnavailable):
        rebound._session_provider(context, "openalgo", "sibling")


def test_rate_limit_endpoint_invalidates_managed_siblings(tmp_path, monkeypatch):
    import flinttrade_core.app as app_module
    from flinttrade_core.workspace import Workspace
    from flinttrade_engine.request_context import RequestContext
    from flinttrade_gateway.auth import gateway_bp

    monkeypatch.setenv("FLINTTRADE_WORKSPACE_DIR", str(tmp_path))
    ws = Workspace(tmp_path)
    ws.initialise()
    def accounts(config):
        config["openalgo"]["api_key"] = "initial-key"
        config["brokers"]["registered"] = ["openalgo:default", "openalgo:sibling"]
        config["brokers"]["account_acls"] = {"openalgo": {"default": ["operator"], "sibling": ["operator"]}}
    ws.update(accounts)
    app = Flask("rate-limit-rebind")
    app.config["BROKER_ACCOUNT_MUTATION_ADMISSION"] = lambda: None
    app.register_blueprint(gateway_bp)
    _mark_router_prerequisites_ready(app)
    monkeypatch.setattr(app_module, "_native_activation_checks", lambda _store: (lambda _aid: False, lambda _aid: False))
    exact, client = _bridge_fixture(tmp_path, app)
    registry = exact.registry
    exact.publish("openalgo", "sibling", Session("synthetic", 4102444800.0, "sibling", "openalgo"), client=object())
    app.config.update(REGISTRY=registry, CREDENTIAL_STORE=exact.store, CLIENT=client)
    assert app_module.configure_broker_router(app, registry, exact.store, client)
    old = app.config["BROKER_ROUTER"]
    response = app.test_client().put("/v1/rate-limits", json={"broker_id": "openalgo", "order": 3})
    assert response.status_code == 200
    rebound = app.config["BROKER_ROUTER"]
    assert rebound is not old
    context = RequestContext(jti="fixture", actor_type="human", actor_id="operator", mode="explore")
    assert rebound._session_provider(context, "openalgo", "default").account_id == "default"
    with pytest.raises(RegistrySessionUnavailable):
        rebound._session_provider(context, "openalgo", "sibling")
    assert rebound.rate_limiter.snapshot()["openalgo"]["order"] == 3.0
    assert rebound._session_provider.broker_workspace_version.generation == 3


def test_rate_limit_endpoint_refreshes_reads_when_execution_default_is_blank(tmp_path, monkeypatch):
    import flinttrade_core.app as app_module
    from flinttrade_core.workspace import Workspace
    from flinttrade_gateway.auth import gateway_bp

    monkeypatch.setenv("FLINTTRADE_WORKSPACE_DIR", str(tmp_path))
    workspace = Workspace(tmp_path)
    workspace.initialise()

    def configure_reads_only(config):
        config["openalgo"]["api_key"] = "initial-key"
        config["brokers"]["execution"]["default"] = ""
        config["brokers"]["account_acls"] = {"openalgo": {"default": ["operator"]}}

    workspace.update(configure_reads_only)
    app = Flask("rate-limit-read-refresh")
    app.config["BROKER_ACCOUNT_MUTATION_ADMISSION"] = lambda: None
    app.register_blueprint(gateway_bp)
    _mark_router_prerequisites_ready(app)
    monkeypatch.setattr(app_module, "_native_activation_checks", lambda _store: (lambda _aid: False, lambda _aid: False))
    exact, client = _bridge_fixture(tmp_path, app)
    app.config.update(REGISTRY=exact.registry, CREDENTIAL_STORE=exact.store, CLIENT=client)
    assert app_module.configure_broker_router(app, exact.registry, exact.store, client) is False
    prior = app.extensions["flinttrade_broker_dependencies"]

    read_response = app.test_client().get("/v1/rate-limits")

    assert read_response.status_code == 200
    assert read_response.get_json()["limits"] == prior.rate_limiter.snapshot()
    assert read_response.get_json()["limits"]

    response = app.test_client().put("/v1/rate-limits", json={"broker_id": "openalgo", "data": 7})

    assert response.status_code == 200
    current = app.extensions["flinttrade_broker_dependencies"]
    assert current is not prior
    assert current.registry is exact.registry
    assert current.read_owner is not prior.read_owner
    assert current.rate_limiter is not prior.rate_limiter
    assert current.rate_limiter.snapshot()["openalgo"]["data"] == 7.0
    assert app.config.get("BROKER_ROUTER") is None


@pytest.mark.parametrize("race,expected", [("service", True), ("broker", False), ("corrupt", False), ("removed", False)])
def test_router_rebuild_rechecks_only_broker_authority_and_contains_read_failures(tmp_path, monkeypatch, race, expected):
    import flinttrade_core.app as app_module
    from flinttrade_core.workspace import Workspace

    monkeypatch.setenv("FLINTTRADE_WORKSPACE_DIR", str(tmp_path))
    workspace = Workspace(tmp_path)
    workspace.initialise()
    app = Flask("rebuild-interleave")
    _mark_router_prerequisites_ready(app)
    monkeypatch.setattr(app_module, "_native_activation_checks", lambda _store: (lambda _aid: False, lambda _aid: False))
    original_prepare = app_module._prepare_broker_dependencies
    def racing_prepare(*args, **kwargs):
        candidate = original_prepare(*args, **kwargs)
        if race == "service":
            workspace.set("services.connection_epoch", 1)
        elif race == "broker":
            workspace.set("brokers.execution.default", "")
        elif race == "corrupt":
            workspace.config_path.write_text("broken-json")
        else:
            workspace.config_path.unlink()
        return candidate
    monkeypatch.setattr(app_module, "_prepare_broker_dependencies", racing_prepare)
    assert app_module.configure_broker_router(app, _owned_registry(app), None, None) is expected
    assert (app.config.get("BROKER_ROUTER") is not None) is expected


def _call_while_lock_is_held(lock: Any, callback: Callable[[], bool]) -> tuple[bool, list[bool]]:
    holder_ready = threading.Event()
    release_holder = threading.Event()
    results: list[bool] = []
    errors: list[BaseException] = []

    def hold_lock() -> None:
        with lock:
            holder_ready.set()
            release_holder.wait(timeout=2.0)

    def invoke() -> None:
        try:
            results.append(callback())
        except BaseException as exc:  # noqa: BLE001 - propagate worker failures to the test
            errors.append(exc)

    holder = threading.Thread(target=hold_lock, daemon=True)
    caller = threading.Thread(target=invoke, daemon=True)
    holder.start()
    assert holder_ready.wait(timeout=1.0)
    caller.start()
    caller.join(timeout=0.15)
    completed_while_held = not caller.is_alive()
    release_holder.set()
    holder.join(timeout=1.0)
    caller.join(timeout=1.0)
    assert not holder.is_alive()
    assert not caller.is_alive()
    if errors:
        raise errors[0]
    return completed_while_held, results


@pytest.mark.unit
def test_configure_broker_router_revokes_old_generation_before_publish(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import flinttrade_core.app as app_module

    app = Flask("router-generation-swap")
    old_router = MagicMock()
    old_router.revoke_and_drain.side_effect = (
        lambda **_kwargs: app.config["BROKER_ROUTER"] is None
    )
    candidate = object()
    app.config["BROKER_ROUTER"] = old_router
    _mark_router_prerequisites_ready(app)
    monkeypatch.setattr(
        app_module,
        "_read_workspace_brokers",
        lambda: default_workspace_config()["brokers"],
    )
    monkeypatch.setattr(app_module, "_native_activation_checks", lambda _store: (lambda _aid: False, lambda _aid: False))
    monkeypatch.setattr(app_module, "_build_broker_router_from_dependencies", lambda *_args, **_kwargs: candidate)
    monkeypatch.setattr(app_module, "_snapshot_brokers_bak", lambda _config: None)

    assert app_module.configure_broker_router(app, _owned_registry(app), object(), None) is True

    old_router.revoke_and_drain.assert_called_once_with(timeout=0.0)
    assert app.config["BROKER_ROUTER"] is candidate
    provider = app.config["LOCAL_STATE_PROVIDER"]
    assert callable(provider)
    assert callable(provider.record_dispatched_order)
    assert callable(provider.record_broker_snapshot)


@pytest.mark.unit
def test_configure_broker_router_forwards_composite_safety_admission_to_every_generation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import flinttrade_core.app as app_module

    guard = MagicMock(name="broker_write_admission")
    first = MagicMock(name="first_router")
    first.revoke_and_drain.return_value = True
    second = MagicMock(name="second_router")
    build = MagicMock(side_effect=[first, second])
    app = Flask("router-safety-admission")
    _mark_router_prerequisites_ready(app, admission=guard)
    monkeypatch.setattr(
        app_module,
        "_read_workspace_brokers",
        lambda: default_workspace_config()["brokers"],
    )
    monkeypatch.setattr(app_module, "_native_activation_checks", lambda _store: (lambda _aid: False, lambda _aid: False))
    monkeypatch.setattr(app_module, "_build_broker_router_from_dependencies", build)
    monkeypatch.setattr(app_module, "_snapshot_brokers_bak", lambda _config: None)

    assert app_module.configure_broker_router(app, _owned_registry(app), object(), None) is True
    assert app_module.configure_broker_router(app, _owned_registry(app), object(), None) is True

    assert build.call_count == 2
    assert all(
        call.kwargs["write_admission"] is guard
        for call in build.call_args_list
    )
    lifecycle_stores = [call.args[0].lifecycle_store for call in build.call_args_list]
    assert lifecycle_stores[0] is lifecycle_stores[1]
    assert app.config["ORDER_LIFECYCLE_LEDGER"] is lifecycle_stores[0]
    assert app.config["LOCAL_STATE_PROVIDER"] is lifecycle_stores[0]
    first.revoke_and_drain.assert_called_once_with(timeout=0.0)
    assert app.config["BROKER_ROUTER"] is second


@pytest.mark.unit
def test_configure_broker_router_binds_lifecycle_audit_receipt_verifier(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import flinttrade_core.app as app_module

    router = MagicMock(name="router")
    lifecycle_store = MagicMock(name="lifecycle_store")
    audit = MagicMock(name="audit")
    app = Flask("router-audit-receipt")
    _mark_router_prerequisites_ready(app)
    app.config.update(ORDER_LIFECYCLE_LEDGER=lifecycle_store, AUDIT=audit)
    monkeypatch.setattr(
        app_module,
        "_read_workspace_brokers",
        lambda: default_workspace_config()["brokers"],
    )
    monkeypatch.setattr(app_module, "_native_activation_checks", lambda _store: (lambda _aid: False, lambda _aid: False))
    monkeypatch.setattr(app_module, "_build_broker_router_from_dependencies", MagicMock(return_value=router))
    monkeypatch.setattr(app_module, "_snapshot_brokers_bak", lambda _config: None)

    assert app_module.configure_broker_router(app, _owned_registry(app), object(), None) is True

    lifecycle_store.set_audit_receipt_verifier.assert_called_once_with(
        audit.verify_event_receipt
    )


@pytest.mark.unit
def test_configure_broker_router_build_failure_revokes_and_fails_closed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import flinttrade_core.app as app_module

    app = Flask("router-generation-build-failure")
    old_router = MagicMock()
    old_router.revoke_and_drain.return_value = True
    app.config["BROKER_ROUTER"] = old_router
    _mark_router_prerequisites_ready(app)
    monkeypatch.setattr(
        app_module,
        "_build_broker_router_from_dependencies",
        MagicMock(side_effect=ValueError("invalid routing")),
    )

    assert app_module.configure_broker_router(app, _owned_registry(app), object(), None) is False

    old_router.revoke_and_drain.assert_called_once_with(timeout=0.0)
    assert app.config["BROKER_ROUTER"] is None


@pytest.mark.unit
def test_configure_broker_router_refuses_an_unhealthy_emergency_journal(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import flinttrade_core.app as app_module

    app = Flask("router-emergency-journal-failure")
    old_router = MagicMock()
    old_router.revoke_and_drain.return_value = True
    build = MagicMock(return_value=object())
    app.config.update(
        BROKER_ROUTER=old_router,
        EMERGENCY_INTENT_JOURNAL_READY=False,
        SAFETY=SimpleNamespace(broker_write_admission=MagicMock()),
    )
    monkeypatch.setattr(
        app_module,
        "_read_workspace_brokers",
        lambda: default_workspace_config()["brokers"],
    )
    monkeypatch.setattr(app_module, "_native_activation_checks", lambda _store: (lambda _aid: False, lambda _aid: False))
    monkeypatch.setattr(app_module, "_build_broker_router_from_dependencies", build)

    assert app_module.configure_broker_router(app, _owned_registry(app), object(), None) is False

    old_router.revoke_and_drain.assert_called_once_with(timeout=0.0)
    build.assert_not_called()
    assert app.config["BROKER_ROUTER"] is None


@pytest.mark.unit
def test_configure_broker_router_refuses_an_unhealthy_daily_pnl_store(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import flinttrade_core.app as app_module

    app = Flask("router-daily-pnl-store-failure")
    old_router = MagicMock()
    old_router.revoke_and_drain.return_value = True
    build = MagicMock(return_value=object())
    app.config.update(
        BROKER_ROUTER=old_router,
        EMERGENCY_INTENT_JOURNAL_READY=True,
        EMERGENCY_INTENT_JOURNAL=object(),
        DAILY_PNL_STATE_READY=False,
        DAILY_PNL_STATE_STORE=None,
        SAFETY_CONFIG_READY=True,
        EMERGENCY_DISPATCHER=object(),
        EMERGENCY_RUNTIME_READY=True,
        SAFETY=SimpleNamespace(broker_write_admission=MagicMock()),
    )
    monkeypatch.setattr(app_module, "_build_broker_router_from_dependencies", build)

    assert app_module.configure_broker_router(app, _owned_registry(app), object(), None) is False

    old_router.revoke_and_drain.assert_called_once_with(timeout=0.0)
    build.assert_not_called()
    assert app.config["BROKER_ROUTER"] is None


@pytest.mark.unit
def test_configure_broker_router_refuses_invalid_durable_safety_config(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import flinttrade_core.app as app_module

    app = Flask("router-safety-config-failure")
    old_router = MagicMock()
    old_router.revoke_and_drain.return_value = True
    build = MagicMock(return_value=object())
    app.config["BROKER_ROUTER"] = old_router
    _mark_router_prerequisites_ready(app)
    app.config["SAFETY_CONFIG_READY"] = False
    monkeypatch.setattr(app_module, "_build_broker_router_from_dependencies", build)

    assert app_module.configure_broker_router(app, _owned_registry(app), object(), None) is False

    old_router.revoke_and_drain.assert_called_once_with(timeout=0.0)
    build.assert_not_called()
    assert app.config["BROKER_ROUTER"] is None


@pytest.mark.unit
def test_configure_broker_router_refuses_non_durable_order_reservations(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import flinttrade_core.app as app_module

    app = Flask("router-reservation-store-failure")
    build = MagicMock(return_value=object())
    _mark_router_prerequisites_ready(app)
    app.config["SAFETY"] = SimpleNamespace(
        broker_write_admission=MagicMock(),
        order_reservations_durable=False,
    )
    monkeypatch.setattr(app_module, "_build_broker_router_from_dependencies", build)

    assert app_module.configure_broker_router(app, _owned_registry(app), object(), None) is False

    build.assert_not_called()
    assert app.config.get("BROKER_ROUTER") is None


@pytest.mark.unit
def test_configure_broker_router_refuses_publication_without_emergency_runtime(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import flinttrade_core.app as app_module

    app = Flask("router-emergency-runtime-failure")
    app.config.update(
        EMERGENCY_INTENT_JOURNAL_READY=True,
        EMERGENCY_INTENT_JOURNAL=object(),
        SAFETY=SimpleNamespace(broker_write_admission=MagicMock()),
    )
    build = MagicMock(return_value=object())
    monkeypatch.setattr(app_module, "_build_broker_router_from_dependencies", build)

    assert app_module.configure_broker_router(app, _owned_registry(app), object(), None) is False

    build.assert_not_called()
    assert app.config.get("BROKER_ROUTER") is None


@pytest.mark.unit
@pytest.mark.parametrize(
    "config",
    [
        {},
        {
            "EMERGENCY_INTENT_JOURNAL_READY": None,
            "EMERGENCY_INTENT_JOURNAL": object(),
            "SAFETY": SimpleNamespace(broker_write_admission=MagicMock()),
        },
        {
            "EMERGENCY_INTENT_JOURNAL_READY": 1,
            "EMERGENCY_INTENT_JOURNAL": object(),
            "SAFETY": SimpleNamespace(broker_write_admission=MagicMock()),
        },
        {
            "EMERGENCY_INTENT_JOURNAL_READY": True,
            "EMERGENCY_INTENT_JOURNAL": None,
            "SAFETY": SimpleNamespace(broker_write_admission=MagicMock()),
        },
        {
            "EMERGENCY_INTENT_JOURNAL_READY": True,
            "EMERGENCY_INTENT_JOURNAL": object(),
        },
        {
            "EMERGENCY_INTENT_JOURNAL_READY": True,
            "EMERGENCY_INTENT_JOURNAL": object(),
            "SAFETY": SimpleNamespace(broker_write_admission=None),
        },
    ],
)
def test_configure_broker_router_requires_explicit_journal_and_safety_readiness(
    monkeypatch: pytest.MonkeyPatch,
    config: dict[str, object],
) -> None:
    import flinttrade_core.app as app_module

    app = Flask("router-explicit-readiness")
    app.config.update(config)
    build = MagicMock(return_value=object())
    monkeypatch.setattr(app_module, "_build_broker_router_from_dependencies", build)

    assert app_module.configure_broker_router(app, _owned_registry(app), object(), None) is False

    build.assert_not_called()
    assert app.config.get("BROKER_ROUTER") is None


@pytest.mark.unit
def test_configure_broker_router_snapshots_before_publication_and_fails_closed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import flinttrade_core.app as app_module

    app = Flask("router-snapshot-publication")
    candidate = object()
    _mark_router_prerequisites_ready(app)
    monkeypatch.setattr(
        app_module,
        "_read_workspace_brokers",
        lambda: default_workspace_config()["brokers"],
    )
    monkeypatch.setattr(app_module, "_native_activation_checks", lambda _store: (lambda _aid: False, lambda _aid: False))
    monkeypatch.setattr(app_module, "_build_broker_router_from_dependencies", lambda *_args, **_kwargs: candidate)

    def fail_snapshot(_config: object) -> None:
        assert app.config.get("BROKER_ROUTER") is None
        raise OSError("snapshot failed")

    monkeypatch.setattr(app_module, "_snapshot_brokers_bak", fail_snapshot)

    assert app_module.configure_broker_router(app, _owned_registry(app), object(), None) is False
    assert app.config.get("BROKER_ROUTER") is None


@pytest.mark.unit
def test_configure_broker_router_drain_timeout_never_publishes_candidate(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import flinttrade_core.app as app_module

    app = Flask("router-generation-drain-timeout")
    old_router = MagicMock()
    old_router.revoke_and_drain.return_value = False
    candidate = object()
    app.config.update(
        BROKER_ROUTER=old_router,
        BROKER_ROUTER_DRAIN_TIMEOUT_SECONDS=0.25,
    )
    monkeypatch.setattr(app_module, "_build_broker_router_from_dependencies", lambda *_args, **_kwargs: candidate)

    assert app_module.configure_broker_router(app, _owned_registry(app), object(), None) is False

    assert old_router.revoke_and_drain.call_count == 2
    assert old_router.revoke_and_drain.call_args_list[0].kwargs == {"timeout": 0.0}
    assert app.config["BROKER_ROUTER"] is None
    assert app.config["BROKER_ROUTER_DRAINING"] is old_router


@pytest.mark.unit
def test_retire_broker_router_generation_times_out_waiting_for_rebuild_lease() -> None:
    import flinttrade_core.app as app_module

    app = Flask("router-rebuild-lease-retire-timeout")
    lock = threading.RLock()
    router = MagicMock()
    app.config.update(
        BROKER_ROUTER=router,
        BROKER_ROUTER_REBUILD_LOCK=lock,
        BROKER_ROUTER_DRAIN_TIMEOUT_SECONDS=0.01,
    )

    completed, results = _call_while_lock_is_held(
        lock,
        lambda: app_module.retire_broker_router_generation(app),
    )

    assert completed is True
    assert results == [False]
    assert app.config["BROKER_ROUTER"] is router
    router.revoke_and_drain.assert_not_called()


@pytest.mark.unit
def test_configure_broker_router_times_out_waiting_for_rebuild_lease(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import flinttrade_core.app as app_module

    app = Flask("router-rebuild-lease-configure-timeout")
    lock = threading.RLock()
    router = MagicMock()
    build = MagicMock()
    app.config.update(
        BROKER_ROUTER=router,
        BROKER_ROUTER_REBUILD_LOCK=lock,
        BROKER_ROUTER_DRAIN_TIMEOUT_SECONDS=0.01,
    )
    monkeypatch.setattr(app_module, "_build_broker_router_from_dependencies", build)
    completed, results = _call_while_lock_is_held(
        lock,
        lambda: app_module.configure_broker_router(app, _owned_registry(app), object(), None),
    )

    assert completed is True
    assert results == [False]
    assert app.config["BROKER_ROUTER"] is router
    build.assert_not_called()


@pytest.mark.unit
def test_configure_broker_router_retries_retained_generation_before_build(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import flinttrade_core.app as app_module

    app = Flask("router-generation-drain-retry")
    old_router = MagicMock()
    old_router.revoke_and_drain.side_effect = [False, True]
    candidate = object()
    build = MagicMock(return_value=candidate)
    app.config.update(
        BROKER_ROUTER=old_router,
        BROKER_ROUTER_DRAIN_TIMEOUT_SECONDS=0,
    )
    _mark_router_prerequisites_ready(app)
    monkeypatch.setattr(
        app_module,
        "_read_workspace_brokers",
        lambda: default_workspace_config()["brokers"],
    )
    monkeypatch.setattr(app_module, "_native_activation_checks", lambda _store: (lambda _aid: False, lambda _aid: False))
    monkeypatch.setattr(app_module, "_build_broker_router_from_dependencies", build)
    monkeypatch.setattr(app_module, "_snapshot_brokers_bak", lambda _config: None)

    assert app_module.configure_broker_router(app, _owned_registry(app), object(), None) is False
    build.assert_not_called()
    assert app.config["BROKER_ROUTER"] is None
    assert app.config["BROKER_ROUTER_DRAINING"] is old_router

    assert app_module.configure_broker_router(app, _owned_registry(app), object(), None) is True

    assert old_router.revoke_and_drain.call_count == 2
    assert app.config["BROKER_ROUTER_DRAINING"] is None
    assert app.config["BROKER_ROUTER"] is candidate


@pytest.mark.unit
def test_configure_broker_router_refuses_and_retires_during_shutdown(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import flinttrade_core.app as app_module

    app = Flask("router-rebuild-during-shutdown")
    router = MagicMock()
    router.revoke_and_drain.return_value = True
    build = MagicMock()
    app.config.update(
        BROKER_ROUTER=router,
        RUNTIME_ACCEPTING_REQUESTS=False,
    )
    monkeypatch.setattr(app_module, "_build_broker_router_from_dependencies", build)

    assert app_module.configure_broker_router(app, _owned_registry(app), object(), None) is False

    router.revoke_and_drain.assert_called_once_with(timeout=0.0)
    build.assert_not_called()
    assert app.config["BROKER_ROUTER"] is None
    assert app.config["BROKER_ROUTER_DRAINING"] is None


@pytest.mark.unit
def test_configure_publishes_reads_before_independent_write_readiness(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import flinttrade_core.app as app_module
    from flinttrade_core.workspace import Workspace

    monkeypatch.setenv("FLINTTRADE_WORKSPACE_DIR", str(tmp_path))
    workspace = Workspace(tmp_path)
    workspace.initialise()
    app = Flask("read-before-write-readiness")
    registry = _owned_registry(app)
    monkeypatch.setattr(app_module, "_native_activation_checks", lambda _store: (lambda _aid: False, lambda _aid: False))

    assert app_module.configure_broker_router(app, registry, object(), None) is False
    dependencies = app.extensions["flinttrade_broker_dependencies"]
    assert dependencies.registry is registry
    assert dependencies.registry_publication_owner is app.extensions["flinttrade.registry_publication_owner"]
    assert dependencies.read_owner is not None
    assert dependencies.read_owner._adapters is dependencies.adapters
    assert app.config.get("BROKER_ROUTER") is None
    assert app.config["ACTIVE_BROKER_ADAPTERS"] is dependencies.adapters

    _mark_router_prerequisites_ready(app)
    assert app_module._configure_broker_writes(app, dependencies) is True
    assert app.config["BROKER_ROUTER"]._adapters is dependencies.adapters


@pytest.mark.parametrize(
    "composition",
    [
        "missing_dependency_owner",
        "foreign_dependency_owner",
        "missing_app_owner",
        "replaced_app_owner",
        "registry_mismatch",
        "missing_app_registry",
        "foreign_app_registry",
    ],
)
def test_dependency_publication_refuses_owner_or_registry_mismatch_without_partial_publication(composition) -> None:
    import flinttrade_core.app as app_module
    from flinttrade_gateway.registry import create_owned_registry

    registry, owner = create_owned_registry()
    foreign_registry, foreign_owner = create_owned_registry()
    dependency_registry = foreign_registry if composition == "registry_mismatch" else registry
    dependency_owner = (
        None
        if composition == "missing_dependency_owner"
        else foreign_owner
        if composition == "foreign_dependency_owner"
        else owner
    )
    app = Flask(f"publication-{composition}")
    if composition != "missing_app_owner":
        app.extensions["flinttrade.registry_publication_owner"] = (
            foreign_owner if composition == "replaced_app_owner" else owner
        )
    if composition != "missing_app_registry":
        app.config["REGISTRY"] = foreign_registry if composition == "foreign_app_registry" else registry
    dependencies = app_module._BrokerRuntimeDependencies(
        registry=dependency_registry,
        registry_publication_owner=dependency_owner,
        config=SimpleNamespace(execution=SimpleNamespace(default=""), registered=()),
        brokers_config={},
        session_provider=object(),
        adapters={},
        rate_limiter=None,
        lifecycle_store=None,
        workspace_snapshot=None,
        workspace_path=None,
        openalgo_client=None,
        native_adapters={},
        read_owner=object(),
    )

    assert app_module._publish_broker_dependencies(app, dependencies) is False
    assert "flinttrade_broker_dependencies" not in app.extensions
    for key in (
        "OPENALGO_CLIENT",
        "SMART_ROUTING",
        "NATIVE_ADAPTERS",
        "ACTIVE_BROKER_ADAPTERS",
        "ORDER_LIFECYCLE_LEDGER",
        "LOCAL_STATE_PROVIDER",
        "RECONCILE_TARGETS",
    ):
        assert key not in app.config


def _published_write_dependency_fixture(app: Flask, app_module, *, ready: bool = True):
    registry = _owned_registry(app)
    if ready:
        _mark_router_prerequisites_ready(app)
    read_owner = MagicMock()
    read_owner.close.return_value = True
    borrowed_client = MagicMock()
    dependencies = app_module._BrokerRuntimeDependencies(
        registry=registry,
        registry_publication_owner=app.extensions["flinttrade.registry_publication_owner"],
        config=SimpleNamespace(execution=SimpleNamespace(default="openalgo:default"), registered=()),
        brokers_config={},
        session_provider=object(),
        adapters={},
        rate_limiter=None,
        lifecycle_store=object(),
        workspace_snapshot=None,
        workspace_path=None,
        openalgo_client=borrowed_client,
        native_adapters={},
        read_owner=read_owner,
    )
    old_router = MagicMock()
    old_router.revoke_and_drain.return_value = True
    app.extensions["flinttrade_broker_dependencies"] = dependencies
    app.config.update(
        BROKER_ROUTER=old_router,
        BROKER_ROUTER_DRAIN_TIMEOUT_SECONDS=0.1,
        BROKER_ROUTER_REBUILD_LOCK=threading.RLock(),
        ACTIVE_BROKER_ADAPTERS=dependencies.adapters,
        NATIVE_ADAPTERS=dependencies.native_adapters,
    )
    return dependencies, read_owner, borrowed_client, old_router


@pytest.mark.parametrize("replacement", ["owner", "registry"])
def test_write_configuration_retires_exact_stale_dependency_before_build(
    monkeypatch: pytest.MonkeyPatch,
    replacement,
) -> None:
    import flinttrade_core.app as app_module
    from flinttrade_gateway.registry import create_owned_registry

    app = Flask(f"write-stale-before-{replacement}")
    dependencies, read_owner, borrowed_client, old_router = _published_write_dependency_fixture(app, app_module)
    foreign_registry, foreign_owner = create_owned_registry()
    if replacement == "owner":
        app.extensions["flinttrade.registry_publication_owner"] = foreign_owner
    else:
        app.config["REGISTRY"] = foreign_registry
    build = MagicMock()
    monkeypatch.setattr(app_module, "_build_broker_router_from_dependencies", build)

    assert app_module._configure_broker_writes(app, dependencies) is False

    build.assert_not_called()
    old_router.revoke_and_drain.assert_called_once_with(timeout=0.0)
    read_owner.close.assert_called_once_with(timeout=0.0)
    assert "flinttrade_broker_dependencies" not in app.extensions
    assert app.config["BROKER_ROUTER"] is None
    assert app.config["ACTIVE_BROKER_ADAPTERS"] == {}
    assert app.config["NATIVE_ADAPTERS"] == {}
    borrowed_client.close.assert_not_called()


@pytest.mark.parametrize("replacement", ["owner", "registry"])
def test_write_configuration_rechecks_dependency_authority_after_candidate_build(
    monkeypatch: pytest.MonkeyPatch,
    replacement,
) -> None:
    import flinttrade_core.app as app_module
    from flinttrade_gateway.registry import create_owned_registry

    app = Flask(f"write-stale-during-{replacement}")
    dependencies, read_owner, borrowed_client, old_router = _published_write_dependency_fixture(app, app_module)
    foreign_registry, foreign_owner = create_owned_registry()
    candidate = object()

    def build(*_args, **_kwargs):
        if replacement == "owner":
            app.extensions["flinttrade.registry_publication_owner"] = foreign_owner
        else:
            app.config["REGISTRY"] = foreign_registry
        return candidate

    monkeypatch.setattr(app_module, "_build_broker_router_from_dependencies", build)

    assert app_module._configure_broker_writes(app, dependencies) is False

    old_router.revoke_and_drain.assert_called_once_with(timeout=0.0)
    read_owner.close.assert_called_once_with(timeout=0.0)
    assert "flinttrade_broker_dependencies" not in app.extensions
    assert app.config["BROKER_ROUTER"] is None
    assert app.config["BROKER_ROUTER"] is not candidate
    borrowed_client.close.assert_not_called()


def test_write_configuration_holds_rebuild_lock_through_build_and_both_publications(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import flinttrade_core.app as app_module

    app = Flask("write-transaction-lock")
    dependencies, _read_owner, _borrowed_client, _old_router = _published_write_dependency_fixture(app, app_module)
    rebuild_lock = app.config["BROKER_ROUTER_REBUILD_LOCK"]
    candidate = object()
    reconcile = object()

    def build(*_args, **_kwargs):
        assert rebuild_lock._is_owned()
        return candidate

    def build_reconcile(*_args, **_kwargs):
        assert rebuild_lock._is_owned()
        assert app.config["BROKER_ROUTER"] is None
        return reconcile

    monkeypatch.setattr(app_module, "_build_broker_router_from_dependencies", build)
    monkeypatch.setattr(app_module, "_build_reconcile_targets_provider", build_reconcile)

    assert app_module._configure_broker_writes(app, dependencies) is True

    assert app.config["BROKER_ROUTER"] is candidate
    assert app.config["RECONCILE_TARGETS"] is reconcile


def test_stale_supplied_dependency_cannot_retire_a_newer_current_generation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import flinttrade_core.app as app_module

    app = Flask("write-stale-supplied-record")
    current, read_owner, _borrowed_client, current_router = _published_write_dependency_fixture(app, app_module)
    stale = app_module._BrokerRuntimeDependencies(
        registry=current.registry,
        registry_publication_owner=current.registry_publication_owner,
        config=current.config,
        brokers_config=current.brokers_config,
        session_provider=current.session_provider,
        adapters=current.adapters,
        rate_limiter=current.rate_limiter,
        lifecycle_store=current.lifecycle_store,
        workspace_snapshot=current.workspace_snapshot,
        workspace_path=current.workspace_path,
        openalgo_client=current.openalgo_client,
        native_adapters=current.native_adapters,
        read_owner=MagicMock(),
    )
    build = MagicMock()
    monkeypatch.setattr(app_module, "_build_broker_router_from_dependencies", build)

    assert app_module._configure_broker_writes(app, stale) is False

    assert app.extensions["flinttrade_broker_dependencies"] is current
    assert app.config["BROKER_ROUTER"] is current_router
    current_router.revoke_and_drain.assert_not_called()
    read_owner.close.assert_not_called()
    build.assert_not_called()


def test_runtime_staleness_retires_reads_but_readiness_only_failure_preserves_them(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import flinttrade_core.app as app_module

    stale_app = Flask("write-runtime-stale")
    stale, stale_reads, _client, stale_router = _published_write_dependency_fixture(stale_app, app_module)
    stale_app.config["RUNTIME_ACCEPTING_REQUESTS"] = False
    build = MagicMock()
    monkeypatch.setattr(app_module, "_build_broker_router_from_dependencies", build)

    assert app_module._configure_broker_writes(stale_app, stale) is False
    assert "flinttrade_broker_dependencies" not in stale_app.extensions
    stale_reads.close.assert_called_once_with(timeout=0.0)
    stale_router.revoke_and_drain.assert_called_once_with(timeout=0.0)
    build.assert_not_called()

    readiness_app = Flask("write-readiness-only")
    valid, valid_reads, _client, valid_router = _published_write_dependency_fixture(
        readiness_app,
        app_module,
        ready=False,
    )

    assert app_module._configure_broker_writes(readiness_app, valid) is False
    assert readiness_app.extensions["flinttrade_broker_dependencies"] is valid
    valid_reads.close.assert_not_called()
    valid_router.revoke_and_drain.assert_called_once_with(timeout=0.0)


@pytest.mark.unit
def test_write_only_retry_reuses_the_published_dependency_identity(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import flinttrade_core.app as app_module

    app = Flask("write-only-retry")
    _mark_router_prerequisites_ready(app)
    dependencies = app_module._BrokerRuntimeDependencies(
        registry=_owned_registry(app),
        registry_publication_owner=app.extensions["flinttrade.registry_publication_owner"],
        config=SimpleNamespace(execution=SimpleNamespace(default="openalgo:default"), registered=()),
        brokers_config={},
        session_provider=object(),
        adapters={},
        rate_limiter=None,
        lifecycle_store=object(),
        workspace_snapshot=None,
        workspace_path=None,
        openalgo_client=object(),
        native_adapters={},
        read_owner=object(),
    )
    app.extensions["flinttrade_broker_dependencies"] = dependencies
    router = object()
    build = MagicMock(return_value=router)
    monkeypatch.setattr(app_module, "_build_broker_router_from_dependencies", build)

    assert app_module._configure_broker_writes(app, dependencies) is True
    build.assert_called_once_with(
        dependencies,
        write_admission=app.config["SAFETY"].broker_write_admission,
    )
    assert app.extensions["flinttrade_broker_dependencies"] is dependencies
    assert app.config["BROKER_ROUTER"] is router


@pytest.mark.unit
def test_combined_retirement_retains_and_retries_the_exact_timed_out_record() -> None:
    import flinttrade_core.app as app_module

    app = Flask("combined-retirement")
    read_owner = MagicMock()
    read_owner.close.side_effect = [False, True, True]
    router = MagicMock()
    router.revoke_and_drain.side_effect = [False, True, True]
    dependencies = SimpleNamespace(read_owner=read_owner)
    app.extensions["flinttrade_broker_dependencies"] = dependencies
    active_adapters = {"openalgo": object()}
    native_adapters = {"dhan": object()}
    reconcile_targets = object()
    app.config.update(
        BROKER_ROUTER=router,
        BROKER_ROUTER_DRAIN_TIMEOUT_SECONDS=0,
        ACTIVE_BROKER_ADAPTERS=active_adapters,
        NATIVE_ADAPTERS=native_adapters,
        RECONCILE_TARGETS=reconcile_targets,
    )

    assert app_module.retire_broker_dependencies(app) is False
    assert "flinttrade_broker_dependencies" not in app.extensions
    assert app.extensions["flinttrade_broker_dependencies_draining"] is dependencies
    assert app.config["BROKER_ROUTER_DRAINING"] is router
    assert app.config["ACTIVE_BROKER_ADAPTERS"] == {}
    assert app.config["NATIVE_ADAPTERS"] == {}
    assert app.config["RECONCILE_TARGETS"] is None

    assert app_module.retire_broker_dependencies(app) is True
    assert "flinttrade_broker_dependencies_draining" not in app.extensions
    assert app.config["BROKER_ROUTER_DRAINING"] is None


@pytest.mark.parametrize("failure_stage", ["read_lookup", "read_close", "write_lookup", "write_revoke"])
def test_combined_retirement_contains_each_ordinary_invalidation_exception_and_attempts_both_sides(
    failure_stage,
) -> None:
    import flinttrade_core.app as app_module

    events: list[str] = []

    class ReadOwner:
        def close(self, *, timeout: float) -> bool:
            events.append(f"read_close:{timeout}")
            if failure_stage == "read_close":
                raise RuntimeError("private read failure")
            return True

    class Dependencies:
        @property
        def read_owner(self):
            events.append("read_lookup")
            if failure_stage == "read_lookup":
                raise RuntimeError("private read lookup failure")
            return ReadOwner()

    class Router:
        @property
        def revoke_and_drain(self):
            events.append("write_lookup")
            if failure_stage == "write_lookup":
                raise RuntimeError("private write lookup failure")

            def revoke(*, timeout: float) -> bool:
                events.append(f"write_revoke:{timeout}")
                if failure_stage == "write_revoke":
                    raise RuntimeError("private write failure")
                return True

            return revoke

    app = Flask(f"combined-retirement-{failure_stage}")
    dependencies = Dependencies()
    router = Router()
    app.extensions["flinttrade_broker_dependencies"] = dependencies
    app.config.update(BROKER_ROUTER=router, BROKER_ROUTER_DRAIN_TIMEOUT_SECONDS=0.0)

    assert app_module.retire_broker_dependencies(app) is False

    assert "read_lookup" in events
    assert "write_lookup" in events
    if failure_stage not in {"read_lookup", "read_close"}:
        assert any(event.startswith("read_close:") for event in events)
    if failure_stage != "write_lookup":
        assert any(event.startswith("write_revoke:") for event in events)
    assert app.extensions["flinttrade_broker_dependencies_draining"] is dependencies
    assert app.config["BROKER_ROUTER_DRAINING"] is router


def test_combined_retirement_retries_contained_exceptions_with_one_remaining_budget() -> None:
    import flinttrade_core.app as app_module

    app = Flask("combined-retirement-exception-retry")
    read_owner = MagicMock()
    read_owner.close.side_effect = [RuntimeError("private read failure"), True]
    router = MagicMock()
    router.revoke_and_drain.side_effect = [RuntimeError("private write failure"), True]
    dependencies = SimpleNamespace(read_owner=read_owner)
    app.extensions["flinttrade_broker_dependencies"] = dependencies
    app.config.update(BROKER_ROUTER=router, BROKER_ROUTER_DRAIN_TIMEOUT_SECONDS=0.1)

    assert app_module.retire_broker_dependencies(app) is True

    assert read_owner.close.call_count == 2
    assert router.revoke_and_drain.call_count == 2
    assert read_owner.close.call_args_list[0].kwargs == {"timeout": 0.0}
    assert router.revoke_and_drain.call_args_list[0].kwargs == {"timeout": 0.0}
    assert "flinttrade_broker_dependencies_draining" not in app.extensions
    assert app.config["BROKER_ROUTER_DRAINING"] is None


@pytest.mark.unit
def test_combined_retirement_retries_the_real_read_owner_until_provider_work_releases(
    tmp_path: Path,
) -> None:
    import asyncio

    import flinttrade_core.app as app_module
    from flinttrade_core.broker_read_port import (
        BrokerReadErrorCode,
        BrokerReadFailure,
        ExactReadTarget,
        InstrumentRef,
        QuoteRequest,
    )
    from flinttrade_core.workspace import Workspace
    from flinttrade_engine.request_context import RequestContext
    from flinttrade_gateway.broker_read_service import create_broker_read_owner

    class BlockingAdapter:
        started: asyncio.Event
        release: asyncio.Event

        async def quotes(self, _session, _symbols):
            self.started.set()
            await self.release.wait()
            return [{"symbol": "NIFTY", "exchange": "NSE", "ltp": 100.0}]

    class BorrowedClient:
        def __init__(self) -> None:
            self.close_calls = 0

        async def close(self) -> None:
            self.close_calls += 1

        def close_sync(self) -> None:
            self.close_calls += 1

    class TrackingRouter:
        def __init__(self) -> None:
            self.revoke_calls: list[float] = []

        def revoke_and_drain(self, *, timeout: float) -> bool:
            self.revoke_calls.append(timeout)
            return True

    workspace = Workspace(tmp_path)
    workspace.initialise()

    def configure(config):
        selector = "dhan:Synthetic"
        config["brokers"]["registered"] = [selector]
        config["brokers"]["execution"]["default"] = selector
        config["brokers"]["account_acls"] = {"dhan": {"Synthetic": ["actor"]}}
        for role in config["brokers"]["data"]:
            config["brokers"]["data"][role] = selector

    workspace.update(configure)
    fixture = RegistryFixture(tmp_path)
    fixture.publish(
        "dhan",
        "Synthetic",
        Session("synthetic", 4_102_444_800.0, "Synthetic", "dhan"),
    )
    snapshot = read_workspace_snapshot(tmp_path)
    adapter = BlockingAdapter()
    dependencies = app_module._prepare_broker_dependencies(
        fixture.registry,
        snapshot.as_dict()["brokers"],
        adapters={"dhan": adapter},
        workspace_snapshot=snapshot,
        workspace_path=tmp_path,
        registry_publication_owner=fixture.owner,
        credential_version_for=lambda selector: fixture.store.selector_state(selector).version,
    )
    dependencies.read_owner = create_broker_read_owner(
        registry=dependencies.registry,
        session_provider=dependencies.session_provider,
        adapters=dependencies.adapters,
        workspace_path=tmp_path,
        rate_limiter=dependencies.rate_limiter,
        runtime_accepting_requests=lambda: True,
    )
    borrowed_client = BorrowedClient()
    dependencies.openalgo_client = borrowed_client
    router = TrackingRouter()
    app = Flask("real-combined-retirement")
    app.extensions["flinttrade.registry_publication_owner"] = fixture.owner
    app.config.update(
        REGISTRY=fixture.registry,
        BROKER_ROUTER=router,
        BROKER_ROUTER_DRAIN_TIMEOUT_SECONDS=0.0,
    )
    assert app_module._publish_broker_dependencies(app, dependencies) is True
    assert app.config["REGISTRY"] is fixture.registry
    assert app.config["OPENALGO_CLIENT"] is borrowed_client
    assert app.config["ACTIVE_BROKER_ADAPTERS"] is dependencies.adapters
    assert app.config["NATIVE_ADAPTERS"] is dependencies.native_adapters
    port = dependencies.read_owner.bind(
        target=ExactReadTarget(BrokerSelector("dhan", "Synthetic")),
        verify_current_authority=lambda: RequestContext(
            "jti",
            "human",
            "actor",
            "practice",
            selector="dhan:Synthetic",
        ),
    )
    assert not isinstance(port, BrokerReadFailure)

    async def scenario() -> None:
        adapter.started = asyncio.Event()
        adapter.release = asyncio.Event()
        read = asyncio.create_task(port.quote(QuoteRequest(InstrumentRef("NIFTY", "NSE"))))
        await adapter.started.wait()

        assert await asyncio.to_thread(app_module.retire_broker_dependencies, app, timeout=0.0) is False
        assert app.extensions["flinttrade_broker_dependencies_draining"] is dependencies
        assert app.config["BROKER_ROUTER_DRAINING"] is router
        assert router.revoke_calls == [0.0]
        assert app.config["ACTIVE_BROKER_ADAPTERS"] == {}
        assert app.config["NATIVE_ADAPTERS"] == {}
        assert app.config["RECONCILE_TARGETS"] is None
        assert borrowed_client.close_calls == 0
        assert await asyncio.to_thread(app_module.retire_broker_dependencies, app, timeout=0.0) is False
        assert app.extensions["flinttrade_broker_dependencies_draining"] is dependencies
        assert app.config["BROKER_ROUTER_DRAINING"] is router
        assert router.revoke_calls == [0.0, 0.0]
        assert app.config["ACTIVE_BROKER_ADAPTERS"] == {}
        assert app.config["NATIVE_ADAPTERS"] == {}
        assert app.config["RECONCILE_TARGETS"] is None
        assert borrowed_client.close_calls == 0
        adapter.release.set()
        assert await read == BrokerReadFailure(BrokerReadErrorCode.REVOKED)
        assert await asyncio.to_thread(app_module.retire_broker_dependencies, app, timeout=0.0) is True
        assert "flinttrade_broker_dependencies_draining" not in app.extensions
        assert app.config["BROKER_ROUTER_DRAINING"] is None
        assert router.revoke_calls == [0.0, 0.0, 0.0]
        assert borrowed_client.close_calls == 0

    try:
        asyncio.run(scenario())
    finally:
        fixture.close()


@pytest.mark.unit
def test_no_execution_default_still_refreshes_reads_and_two_apps_never_share_owners(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import flinttrade_core.app as app_module
    from flinttrade_core.workspace import Workspace

    records = []
    for name in ("first", "second"):
        workspace_path = tmp_path / name
        workspace = Workspace(workspace_path)
        workspace.initialise()
        workspace.set("brokers.execution.default", "")
        monkeypatch.setenv("FLINTTRADE_WORKSPACE_DIR", str(workspace_path))
        app = Flask(f"no-default-{name}")
        registry = _owned_registry(app)
        monkeypatch.setattr(
            app_module,
            "_native_activation_checks",
            lambda _store: (lambda _aid: False, lambda _aid: False),
        )

        assert app_module.configure_broker_router(app, registry, object(), None) is False
        record = app.extensions["flinttrade_broker_dependencies"]
        assert record.registry is registry
        assert record.read_owner is not None
        assert app.config.get("BROKER_ROUTER") is None
        records.append(record)

    assert records[0] is not records[1]
    assert records[0].read_owner is not records[1].read_owner


def test_build_broker_router_from_default_config() -> None:
    router = build_broker_router(BrokerRegistry(), default_workspace_config()["brokers"])
    assert isinstance(router, BrokerRouter)
    assert isinstance(router._config, RoutingConfig)
    assert isinstance(router._session_provider, AuthenticatingSessionProvider)
    assert router._config.execution.default == "openalgo:default"
    # Public accessor mirrors the private config (used by order/bracket routes).
    assert router.default_selector == "openalgo:default"


def test_build_broker_router_forwards_write_admission_guard() -> None:
    guard = MagicMock(name="write_admission")

    router = build_broker_router(
        BrokerRegistry(),
        default_workspace_config()["brokers"],
        write_admission=guard,
    )

    assert router._write_admission is guard


def test_build_broker_router_invalid_config_raises() -> None:
    bad = {**default_workspace_config()["brokers"], "execution": {"default": "dhan"}}  # no colon
    with pytest.raises(RoutingConfigError):
        build_broker_router(BrokerRegistry(), bad)


def test_build_broker_router_threads_account_acls() -> None:
    brokers = {
        "registered": ["dhan:personal"],
        "account_acls": {"dhan": {"personal": ["nava@flinttrade.local"]}},
        "execution": {"default": "dhan:personal"},
        "data": {
            "ticks": "dhan:personal",
            "historical": "dhan:personal",
            "option_chains": "dhan:personal",
            "quote": "dhan:personal",
        },
        "failover": {"enabled": False, "order": []},
        "cost_aware": {"enabled": False, "tasks": []},
    }
    router = build_broker_router(BrokerRegistry(), brokers)
    assert router._session_provider._acls == {"dhan": {"personal": ["nava@flinttrade.local"]}}


def test_safety_gate_is_one_shot() -> None:
    from flinttrade_engine.safety import SafetyGate

    gate = SafetyGate()
    assert gate.consume("gate-abc") is True
    assert gate.consume("gate-abc") is False  # replay rejected
    assert gate.consume("gate-xyz") is True


def test_safety_gate_reconsume_allowed_after_ttl_expiry() -> None:
    """L4: once the consumed marker expires, the slot re-opens.

    ``ttl_seconds=0`` makes the marker expire immediately, so a second consume
    returns True. This never widens the real replay window because
    SafetyContext.verify independently enforces the order's own ~10s expiry — a
    gate old enough to be re-consumable is already expired at verify time.
    """
    from flinttrade_engine.safety import SafetyGate

    gate = SafetyGate()
    assert gate.consume("g0", ttl_seconds=0) is True
    assert gate.consume("g0", ttl_seconds=0) is True  # expired marker re-opens


def test_safety_gate_prune_does_not_evict_live_marker() -> None:
    """L4: the >256 opportunistic prune drops expired markers but keeps live ones."""
    from flinttrade_engine.safety import SafetyGate

    gate = SafetyGate()
    assert gate.consume("live", ttl_seconds=60.0) is True
    # Overflow the prune threshold with already-expired markers.
    for i in range(300):
        gate.consume(f"expired-{i}", ttl_seconds=0)
    # The live marker survived the prune, so its replay is still rejected.
    assert gate.consume("live") is False


def test_openalgo_client_registers_bridge_adapter_and_session(tmp_path) -> None:
    router, fixture = _build_bridge(tmp_path)
    assert "openalgo" in router._adapters
    assert type(router._adapters["openalgo"]).__name__ == "OpenAlgoAdapter"
    assert fixture.registry.snapshot_exact_state(BrokerSelector("openalgo", "default")).status == "connected"


def test_no_openalgo_client_leaves_adapters_empty() -> None:
    # Back-compat: the create_flask_app path passes client=None in most tests.
    router = build_broker_router(BrokerRegistry(), default_workspace_config()["brokers"])
    assert router._adapters == {}


def _native_brokers_cfg() -> dict:
    return {
        "registered": ["dhan:personal", "upstox:main"],
        "account_acls": {"dhan": {"personal": ["me"]}, "upstox": {"main": ["me"]}},
        "execution": {"default": "dhan:personal"},
        "data": {
            "ticks": "dhan:personal", "historical": "dhan:personal",
            "option_chains": "dhan:personal", "quote": "dhan:personal",
        },
        "failover": {"enabled": False, "order": []},
        "cost_aware": {"enabled": False, "tasks": []},
    }


def _all_native_brokers_cfg() -> dict:
    return {
        "registered": ["dhan:D1", "upstox:U1", "indmoney:I1", "kotakneo:K1", "groww:G1"],
        "account_acls": {
            "dhan": {"D1": ["me"]},
            "upstox": {"U1": ["me"]},
            "indmoney": {"I1": ["me"]},
            "kotakneo": {"K1": ["me"]},
            "groww": {"G1": ["me"]},
        },
        "execution": {"default": "dhan:D1"},
        "data": {
            "ticks": "dhan:D1", "historical": "dhan:D1",
            "option_chains": "dhan:D1", "quote": "dhan:D1",
        },
        "failover": {"enabled": False, "order": []},
        "cost_aware": {"enabled": False, "tasks": []},
    }


def test_natives_stay_dormant_without_activation_checks() -> None:
    # Default: no native_* callables → no native adapter constructed.
    router = build_broker_router(BrokerRegistry(), _native_brokers_cfg())
    assert router._adapters == {}


def test_native_activates_only_when_attested_and_credentialled() -> None:
    router = build_broker_router(
        BrokerRegistry(),
        _native_brokers_cfg(),
        native_attest_ok=lambda b: b in {"dhan", "upstox"},
        native_has_credentials=lambda b: b == "dhan",  # only dhan has creds
    )
    # dhan passes both gates; upstox is attested but has no creds → dormant.
    assert set(router._adapters) == {"dhan"}
    assert type(router._adapters["dhan"]).__name__ == "DhanAdapter"


def test_only_connectable_natives_activate_from_registered_selectors() -> None:
    """Boot activation follows the activation-cleared native set, not stale rows.

    Kotak Neo, INDmoney, and Groww are built/catalogued but still
    ``connectable=false`` while declared blockers remain, so even
    attested+credentialled stale rows must remain dormant after restart.
    Capability metadata remains available via the recommendation/capability
    routes; this only guards runtime activation.
    """
    router = build_broker_router(
        BrokerRegistry(),
        _all_native_brokers_cfg(),
        native_attest_ok=lambda _b: True,
        native_has_credentials=lambda _b: True,
    )
    assert set(router._adapters) == {"dhan", "upstox"}
    assert "indmoney" not in router._adapters
    assert "kotakneo" not in router._adapters
    assert "groww" not in router._adapters


def test_native_activation_gates_fail_closed() -> None:
    router = build_broker_router(
        BrokerRegistry(),
        _native_brokers_cfg(),
        native_attest_ok=lambda _b: False,
        native_has_credentials=lambda _b: True,
    )
    assert router._adapters == {}


def test_injected_adapter_wins_over_factory() -> None:
    sentinel = object()
    router = build_broker_router(
        BrokerRegistry(),
        _native_brokers_cfg(),
        adapters={"dhan": sentinel},
        native_attest_ok=lambda _b: True,
        native_has_credentials=lambda _b: True,
    )
    # Explicit injection takes precedence; the factory does not overwrite it.
    assert router._adapters["dhan"] is sentinel


def test_native_activation_checks_attestation_and_credential_presence() -> None:
    """``_native_activation_checks`` reflects SDK and vault state.

    ``has_credentials`` must mirror the vault's ``list_accounts`` adapter ids.
    ``attest_ok`` now depends on the pinned SDK being INSTALLED (dhan/upstox/
    kotakneo/groww all carry real pins) — so its per-broker value is environment-
    dependent and not hard-asserted here. INDmoney is the exception: its SDK pin
    is ``None`` (REST-only), so it always attests. PLACEHOLDER-pin dormancy is
    covered against a fixture lock in ``test_broker_sdk_attest``. Catalogue
    blockers and authoritative emergency planning remain separate factory gates.
    """
    from flinttrade_core.app import _native_activation_checks

    class _FakeVault:
        def list_accounts(self) -> list[dict]:
            return [{"account_id": "personal", "adapter_id": "dhan", "broker": "dhan"}]

    attest_ok, has_credentials = _native_activation_checks(_FakeVault())
    assert has_credentials("dhan") is True
    assert has_credentials("upstox") is False
    # REST-only native: no SDK attestation is required; the other gates remain.
    assert attest_ok("indmoney") is True
    # A non-native id never attests.
    assert attest_ok("not-a-broker") is False


def test_native_activation_checks_no_vault_fails_closed() -> None:
    from flinttrade_core.app import _native_activation_checks

    _attest_ok, has_credentials = _native_activation_checks(None)
    # No vault → nothing is credentialled, so nothing activates even if attested.
    assert has_credentials("dhan") is False
    assert has_credentials("upstox") is False
    assert has_credentials("indmoney") is False


def test_dhan_activates_end_to_end_when_sdk_present() -> None:
    """Real bridge: with dhanhq installed (pin match) + creds in the vault, the
    router registers a live DhanAdapter via the activation factory.

    Skipped where dhanhq is not installed (the PLACEHOLDER-pinned natives can
    never reach this state, so this only exercises the one real pin).
    """
    pytest.importorskip("dhanhq")
    from flinttrade_core.app import _native_activation_checks, build_broker_router

    class _FakeVault:
        def list_accounts(self) -> list[dict]:
            return [{"account_id": "personal", "adapter_id": "dhan", "broker": "dhan"}]

    attest_ok, has_credentials = _native_activation_checks(_FakeVault())
    if not attest_ok("dhan"):  # dhanhq present but version != pin → nothing to prove
        pytest.skip("dhanhq installed but version does not match brokers.lock pin")

    router = build_broker_router(
        BrokerRegistry(),
        _native_brokers_cfg(),
        native_attest_ok=attest_ok,
        native_has_credentials=has_credentials,
    )
    assert "dhan" in router._adapters
    assert type(router._adapters["dhan"]).__name__ == "DhanAdapter"
    # upstox is registered in config but the vault holds no upstox creds → dormant
    # (has_credentials gate), regardless of whether its SDK is installed.
    assert "upstox" not in router._adapters


@pytest.mark.unit
def test_native_adapter_kwargs_thread_local_state_provider() -> None:
    """The §14 wiring: adapter_kwargs reaches the native constructor, so the
    journal-backed ``local_state_provider`` lands on the adapter."""
    sentinel_provider = lambda _session: None  # noqa: E731 - shape only; never called

    router = build_broker_router(
        BrokerRegistry(),
        _native_brokers_cfg(),
        native_attest_ok=lambda b: b == "dhan",
        native_has_credentials=lambda b: b == "dhan",
        native_adapter_kwargs=lambda _b: {"local_state_provider": sentinel_provider},
    )
    assert router._adapters["dhan"]._local_state_provider is sentinel_provider


@pytest.mark.unit
def test_native_adapter_kwargs_adds_cached_dhan_security_resolver(monkeypatch) -> None:
    """App-activated Dhan adapters must resolve symbols like the live probe.

    Dhan market-data and order-write calls require a security id. The app
    factory injects a lazy resolver only for Dhan, so the resolver works for
    reads/writes without making every native adapter accept Dhan-only kwargs.
    """
    from flinttrade_core.app import _native_adapter_kwargs_for

    csv_text = "\n".join(
        [
            "SEM_SMST_SECURITY_ID,SEM_EXM_EXCH_ID,SEM_SEGMENT,SEM_TRADING_SYMBOL,SEM_CUSTOM_SYMBOL,SM_SYMBOL_NAME",
            "11536,NSE,E,RELIANCE,RELIANCE,RELIANCE",
        ]
    )
    downloads: list[str] = []

    def _fake_download(url: str) -> str:
        downloads.append(url)
        return csv_text

    monkeypatch.setattr("flinttrade_gateway.brokers.dhan._download_text", _fake_download)
    sentinel_provider = lambda _session: None  # noqa: E731 - shape only; never called

    kwargs_for = _native_adapter_kwargs_for(sentinel_provider)
    dhan_kwargs = kwargs_for("dhan")
    upstox_kwargs = kwargs_for("upstox")

    assert dhan_kwargs["local_state_provider"] is sentinel_provider
    assert upstox_kwargs == {"local_state_provider": sentinel_provider}
    resolve = dhan_kwargs["security_resolver"]
    assert resolve("RELIANCE", "NSE") == "11536"
    assert resolve("RELIANCE", "NSE") == "11536"
    assert len(downloads) == 1


@pytest.mark.unit
def test_on_native_activated_sink_receives_active_natives_only() -> None:
    """The sink sees exactly the ACTIVE native map — bridge excluded, injected
    natives included — so the reconciliation runner can enumerate them."""

    class _FakeNative:
        broker_id = "upstox"

    activated: dict[str, object] = {}
    router = build_broker_router(
        BrokerRegistry(),
        _native_brokers_cfg(),
        adapters={"upstox": _FakeNative()},
        openalgo_client=object(),
        native_attest_ok=lambda b: b == "dhan",
        native_has_credentials=lambda b: b == "dhan",
        on_native_activated=activated.update,
    )
    assert set(activated) == {"dhan", "upstox"}
    assert "openalgo" not in activated  # bridge never qualifies
    assert activated["dhan"] is router._adapters["dhan"]


@pytest.mark.unit
def test_all_adapter_sink_includes_openalgo_for_reconciliation(tmp_path) -> None:
    active = {}
    router, fixture = _build_bridge(tmp_path, on_adapters_activated=active.update)
    assert set(active) == {"openalgo"}
    assert active["openalgo"] is router._adapters["openalgo"]


@pytest.mark.unit
def test_on_native_activated_sink_empty_when_dormant() -> None:
    activated: dict[str, object] = {}
    build_broker_router(
        BrokerRegistry(),
        _native_brokers_cfg(),
        openalgo_client=object(),
        on_native_activated=activated.update,
    )
    assert activated == {}


@pytest.mark.unit
def test_reconcile_targets_provider_refuses_unversioned_native_read(tmp_path) -> None:
    """Real registry refuses until the verified read-port cutover (7C.2)."""
    from flinttrade_core.app import _build_reconcile_targets_provider
    fixture = RegistryFixture(tmp_path)
    calls = []
    class Adapter:
        broker_id = "dhan"
        def funds(self, *args):
            calls.append(args)
            raise AssertionError("provider must not run")
    fixture.publish("dhan", "personal", Session("test", 4102444800.0, "raw-id", "dhan"))
    targets = _build_reconcile_targets_provider(fixture.registry, {"dhan": Adapter()}, ["dhan:personal"])
    assert targets() == []
    assert calls == []
    fixture.close()


@pytest.mark.unit
def test_current_reconcile_helpers_follow_router_rebuilds() -> None:
    from flinttrade_core.app import (
        _current_reconcile_targets,
        _record_current_reconcile_snapshot,
    )

    app = Flask("dynamic-reconcile-provider")
    first_targets = [(object(), object())]
    second_targets = [(object(), object())]
    ditto_targets = [(object(), object())]
    first_recorder = MagicMock()
    second_recorder = MagicMock()
    app.config.update(
        RECONCILE_TARGETS=lambda: first_targets,
        ORDER_LIFECYCLE_LEDGER=SimpleNamespace(record_broker_snapshot=first_recorder),
        DITTO_RUNTIME=SimpleNamespace(reconciliation_targets=lambda: ditto_targets),
    )

    assert _current_reconcile_targets(app) == [*first_targets, *ditto_targets]
    _record_current_reconcile_snapshot(app, adapter_id="dhan", account_id="a", orders=(), positions=(), holdings=())

    app.config.update(
        RECONCILE_TARGETS=lambda: second_targets,
        ORDER_LIFECYCLE_LEDGER=SimpleNamespace(record_broker_snapshot=second_recorder),
    )
    assert _current_reconcile_targets(app) == [*second_targets, *ditto_targets]
    _record_current_reconcile_snapshot(app, adapter_id="upstox", account_id="b", orders=(), positions=(), holdings=())

    first_recorder.assert_called_once()
    second_recorder.assert_called_once()

@pytest.mark.unit
def test_create_flask_app_defaults_reconcile_config_keys() -> None:
    """A bare WSGI factory remains read-only without an emergency runtime."""
    from flinttrade_core.app import create_flask_app

    app = create_flask_app()
    assert app.config["NATIVE_ADAPTERS"] == {}
    from flinttrade_engine.emergency_intents import EmergencyIntentJournal
    from flinttrade_engine.daily_pnl_state import DailyPnLStateStore

    assert isinstance(app.config["EMERGENCY_INTENT_JOURNAL"], EmergencyIntentJournal)
    assert app.config["EMERGENCY_INTENT_JOURNAL_READY"] is True
    assert isinstance(app.config["DAILY_PNL_STATE_STORE"], DailyPnLStateStore)
    assert app.config["DAILY_PNL_STATE_READY"] is True
    assert app.config["RECONCILE_TARGETS"] is None
    assert app.config.get("BROKER_ROUTER") is None
    from flinttrade_ditto.runtime import DittoRuntime

    assert isinstance(app.config["DITTO_RUNTIME"], DittoRuntime)


@pytest.mark.unit
def test_create_flask_app_marks_memory_only_injected_safety_unready(
    tmp_path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from flinttrade_core.app import create_flask_app
    from flinttrade_engine.safety import SafetySystem

    monkeypatch.setenv("FLINTTRADE_WORKSPACE_DIR", str(tmp_path))
    master_password = tmp_path / "master_password"
    master_password.write_text("memory-only-safety-test-password", encoding="utf-8")
    master_password.chmod(0o600)

    app = create_flask_app(safety=SafetySystem())

    assert app.config["SAFETY_CONFIG_READY"] is False
    assert app.config.get("BROKER_ROUTER") is None


@pytest.mark.unit
def test_create_flask_app_keeps_routing_disabled_for_invalid_safety_config(
    tmp_path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from flinttrade_core.app import create_flask_app

    from flinttrade_core.workspace import Workspace
    workspace = Workspace(tmp_path)
    workspace.initialise()
    workspace.update(lambda config: config.pop("safety") and None)
    master_password = tmp_path / "master_password"
    master_password.write_text("invalid-safety-config-test-password", encoding="utf-8")
    master_password.chmod(0o600)
    monkeypatch.setenv("FLINTTRADE_WORKSPACE_DIR", str(tmp_path))

    app = create_flask_app()

    assert app.config["SAFETY_CONFIG_READY"] is False
    assert app.config.get("BROKER_ROUTER") is None
    from flinttrade_ditto.runtime import DittoCapabilityUnavailable

    with pytest.raises(DittoCapabilityUnavailable, match="safety runtime is unavailable"):
        app.config["DITTO_RUNTIME"]._router_owner_factory([object()], "operator-1")


@pytest.mark.unit
def test_configure_ditto_runtime_forwards_complete_safety_dependencies(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import flinttrade_core.app as app_module
    import flinttrade_ditto.runtime as runtime_module

    guard = MagicMock(name="broker_write_admission")
    safety = SimpleNamespace(
        check_order=MagicMock(),
        broker_write_admission=guard,
        order_reservations_durable=True,
    )
    journal = object()
    daily_pnl_state = object()
    scheduler = object()
    lifecycle_store = object()
    captured: dict[str, Any] = {}

    class _Owner:
        def __init__(self, accounts: list[Any], actor_id: str, **kwargs: Any) -> None:
            captured.update(accounts=accounts, actor_id=actor_id, **kwargs)

    monkeypatch.setattr(runtime_module, "DittoRouterOwner", _Owner)
    app = Flask("ditto-complete-safety")
    app.config.update(
        DITTO_CREDENTIAL_STORE=object(),
        RUNTIME_ACCEPTING_REQUESTS=True,
        EMERGENCY_INTENT_JOURNAL_READY=True,
        EMERGENCY_INTENT_JOURNAL=journal,
        DAILY_PNL_STATE_READY=True,
        DAILY_PNL_STATE_STORE=daily_pnl_state,
        SAFETY_CONFIG_READY=True,
        EMERGENCY_RUNTIME_READY=True,
        EMERGENCY_DISPATCHER=object(),
        SAFETY=safety,
        TIME_SCHEDULER=scheduler,
        ORDER_LIFECYCLE_LEDGER=lifecycle_store,
    )

    app_module._configure_ditto_runtime(app, safety)
    accounts = [object()]
    owner = app.config["DITTO_RUNTIME"]._router_owner_factory(accounts, "operator-1")

    assert isinstance(owner, _Owner)
    assert captured == {
        "accounts": accounts,
        "actor_id": "operator-1",
        "write_admission": guard,
        "intent_journal": journal,
        "safety_system": safety,
        "time_scheduler": scheduler,
        "lifecycle_store": lifecycle_store,
    }


def test_authorise_default_actor_trust_on_first_use(tmp_path) -> None:
    """A freshly authenticated operator claims the default execution selector once."""
    from flinttrade_engine.request_context import RequestContext

    router, fixture = _build_bridge(tmp_path)
    # Default execution selector is openalgo:default with an empty ACL.
    assert router._config.execution.default == "openalgo:default"

    claimed = router.authorise_default_actor("nava")
    assert claimed == ("openalgo", "default")
    # The provider now authorises that actor for the gated path (no SafetyBypassError).
    ctx = RequestContext(jti="x", actor_type="human", actor_id="nava", mode="live")
    assert router._session_provider(ctx, "openalgo", "default") is not None
    # A second, different actor is NOT auto-claimed (TOFU is one-shot per selector).
    assert router.authorise_default_actor("someone-else") is None


def test_build_broker_router_builds_algo_tag_guard_from_config() -> None:
    """workspace brokers.algo_tags builds an engine AlgoTagGuard on the router
    (G10 — algo-id relay + per-exchange per-second ceiling for algo_tag_required
    natives). Without the block the router stays untagged (retail defaults)."""
    from flinttrade_engine.algo_tag_guard import AlgoTagGuard

    brokers = {
        **default_workspace_config()["brokers"],
        "algo_tags": {"dhan": {"algo_id": "ALGO-REG-1", "max_orders_per_sec": 8}},
    }
    router = build_broker_router(BrokerRegistry(), brokers)
    guard = router._algo_tag_guard
    assert isinstance(guard, AlgoTagGuard)
    assert guard.algo_id_for("dhan") == "ALGO-REG-1"

    untagged = build_broker_router(BrokerRegistry(), default_workspace_config()["brokers"])
    assert untagged._algo_tag_guard is None


@pytest.mark.unit
def test_build_broker_router_malformed_algo_tags_are_dropped_not_fatal() -> None:
    """A malformed algo_tags entry is DROPPED (loud error log), never raised —
    a bad compliance-config block must not brick broker reads/reconciliation/
    dispatch (audit finding: over-broad blast radius). The adapter/mapping
    retail default takes over, so no order dispatches in a broker-flagging
    state. A mix of valid + invalid keeps only the valid entry."""
    from flinttrade_engine.algo_tag_guard import AlgoTagGuard

    base = default_workspace_config()["brokers"]
    for bad in (
        {"dhan": {"algo_id": "", "max_orders_per_sec": 8}},
        {"dhan": {"algo_id": "A", "max_orders_per_sec": 0}},
        {"dhan": "not-an-object"},
        {"dhan": {"algo_id": "A", "max_orders_per_sec": "not-an-int"}},
    ):
        router = build_broker_router(BrokerRegistry(), {**base, "algo_tags": bad})
        assert isinstance(router, BrokerRouter)
        assert router._algo_tag_guard is None  # the only entry was dropped

    mixed = {"dhan": {"algo_id": "OK", "max_orders_per_sec": 5}, "indmoney": "bad"}
    router = build_broker_router(BrokerRegistry(), {**base, "algo_tags": mixed})
    assert isinstance(router._algo_tag_guard, AlgoTagGuard)
    assert router._algo_tag_guard.algo_id_for("dhan") == "OK"
    assert router._algo_tag_guard.algo_id_for("indmoney") is None
