"""Independent reducing authority through canonical admission and real books."""
from __future__ import annotations

import asyncio
import importlib.util
import time
from dataclasses import asdict
from uuid import uuid4

import pytest

from packages.core.core.tests.test_practice_agent_runtime import (
    _start,
    _supervisor,
    _wait_for,
    desk as desk,
)

pytestmark = pytest.mark.integration


@pytest.fixture
def protection_desk(desk, tmp_path, monkeypatch):
    """Real read grants/ACL/credential versions with inert quote transport."""
    from flinttrade_core.app import _BrokerRuntimeDependencies
    from flinttrade_core.broker_client import BrokerClient
    from flinttrade_core.broker_identity import BrokerSelector, CredentialVersion
    from flinttrade_core.config import Settings
    from flinttrade_core.workspace_migrations import broker_workspace_version, compare_and_swap_workspace
    from flinttrade_data.audit_logger import AuditLogger
    from flinttrade_gateway.session_provider import AuthenticatingSessionProvider
    from flinttrade_gateway.broker_read_service import create_broker_read_owner
    from flinttrade_gateway.brokers._base import Session

    from flinttrade_gateway.registry import ManagedSessionAuthority, create_owned_registry
    from flinttrade_gateway.routing_config import RoutingConfig
    import httpx

    selector = BrokerSelector("dhan", "Quotes")
    workspace_path = tmp_path / "read-workspace"

    def configure(value):
        value["brokers"]["registered"] = ["dhan:Quotes"]
        value["brokers"]["execution"] = {"default": "dhan:Quotes"}
        value["brokers"]["data"].update(quote="dhan:Quotes", historical="dhan:Quotes",
                                      ticks="dhan:Quotes", option_chains="dhan:Quotes")
        value["brokers"]["account_acls"] = {"dhan": {"Quotes": ["operator"]}}

    workspace = compare_and_swap_workspace(workspace_path, None, configure)
    routing = RoutingConfig.from_workspace(workspace.as_dict()["brokers"])
    registry, publication = create_owned_registry()
    credentials = {selector: CredentialVersion(selector, uuid4(), 1)}
    authority = ManagedSessionAuthority(credentials[selector], workspace.version, broker_workspace_version(workspace))
    session = Session("synthetic-protection-read", time.time() + 3600, "Quotes", "dhan")
    publication.publish_prepared_candidate(publication.prepare_session_candidate(
        selector, session, expected_registry=registry.snapshot_selector(selector), authority=authority,
        broker="dhan", label="Quotes", client=object()), current_authority=authority)
    provider = AuthenticatingSessionProvider(registry, routing.account_acls, workspace_snapshot=workspace,
        workspace_path=workspace_path, credential_version_for=credentials.__getitem__)
    calls = []

    class Source:
        async def quotes(self, session, symbols):
            calls.append(("RELIANCE", "NSE"))
            return [{"symbol": "RELIANCE", "exchange": "NSE", "ltp": 123.5, "available": True}]

    class NoNetwork(httpx.AsyncClient):
        def __init__(self, **kwargs):
            super().__init__(**kwargs, trust_env=False, transport=httpx.MockTransport(
                lambda request: pytest.fail("Unexpected transport")))

    monkeypatch.setattr(httpx, "AsyncClient", NoNetwork)
    client = BrokerClient(Settings(dhan_api_key=""))
    adapters = {"dhan": Source()}
    read_owner = create_broker_read_owner(registry=registry, session_provider=provider, adapters=adapters,
        workspace_path=workspace_path, rate_limiter=None, runtime_accepting_requests=lambda: True)
    audit = AuditLogger(str(tmp_path / "audit"))
    app = desk.app
    from flinttrade_core.auth_routes import auth_bp
    app.register_blueprint(auth_bp)
    app.extensions["flinttrade_broker_dependencies"] = _BrokerRuntimeDependencies(
        registry, routing, workspace.as_dict()["brokers"], provider, adapters, None, None,
        workspace, workspace_path, client, adapters, publication, read_owner)
    app.extensions["flinttrade.registry_publication_owner"] = publication
    app.config.update(CLIENT=client, BROKER_CLIENT=client, REGISTRY=registry,
                      ACTIVE_BROKER_ADAPTERS=adapters, AUDIT=audit)
    desk.protection = None
    desk.protection_path = tmp_path / "protection"
    if importlib.util.find_spec("flinttrade_core.protection_grants") is not None:
        from flinttrade_core.protection_grants import install_protection_services
        desk.protection = install_protection_services(app, desk.protection_path)
    desk.signal = "BUY"
    assert _start(desk, cycle_interval_sec=3600).status_code == 202
    supervisor = _supervisor(desk)
    _wait_for(lambda: supervisor.run.snapshot.get("cycle_count") == 1)
    run = supervisor.run
    from flinttrade_core.execution_session import ExecutionSession
    scope = ExecutionSession(run.run_id, desk.owner, "paper:sandbox", "paper")
    if desk.protection is not None:
        desk.protection.attach(scope, desk.store, run.adapter)
    desk.scope, desk.run, desk.read_calls, desk.credentials = scope, run, calls, credentials
    desk.policy = {
        "policy_revision": "synthetic-policy-v1", "valid_until": time.time() + 3600,
        "position": {"symbol": "RELIANCE", "exchange": "NSE", "product": "MIS",
                     "entry_order_ids": [desk.sandbox.get_trades()[0]["order_id"]], "quantity": 1},
        "hedge_scope": [], "risk_policy": "unhedged-cash-reduction-only",
        "max_quantity": 1, "max_notional": 1000.0,
        "read": {"selector": "dhan:Quotes", "valid_until": time.time() + 1800,
                 "max_reads": 20, "max_age_seconds": 30.0},
    }
    desk.operator_headers = {"Authorization": "Bearer " + desk.token(
        scopes=["admin.accounts.read", "admin.accounts.write"])}
    yield desk
    desk.revoked.clear()
    from flinttrade_core.practice_agent_runtime import shutdown_practice_agent
    shutdown_practice_agent(app, timeout=5)
    read_owner.close(timeout=2)
    asyncio.run(client.shutdown())
    audit.close()


def grant(desk, **changes):
    return desk.client.post("/api/v1/protection/grants", headers=desk.operator_headers,
        json={"run_id": desk.scope.run_id, "expected_revision": 0, "policy": {**desk.policy, **changes}})


def test_explicit_grant_fixed_supervisor_exit_survives_retired_jwt(protection_desk, tmp_path, monkeypatch):
    from flinttrade_core import auth_routes, auth_state
    desk = protection_desk
    state = auth_state.AuthState(tmp_path / "auth-revocations.sqlite")
    monkeypatch.setattr(auth_state, "get_auth_state", lambda: state)
    monkeypatch.setattr(auth_routes, "_is_jti_revoked", state.is_jti_revoked)
    result = grant(desk)
    assert result.status_code == 201, result.json
    assert result.json["data"]["scope"] == asdict(desk.scope)
    logged_out = desk.client.post("/v1/auth/logout", headers=desk.operator_headers, json={})
    assert logged_out.status_code == 200, logged_out.json
    assert state.is_jti_revoked("practice-session")
    refused = desk.client.post("/api/v1/orders/place", headers=desk.operator_headers,
        json={"symbol": "RELIANCE", "exchange": "NSE", "product": "MIS", "action": "SELL",
              "quantity": 1, "price": 123.5, "price_basis": "ltp"})
    assert refused.status_code == 401
    _supervisor(desk).stop(desk.owner)
    _wait_for(lambda: desk.run.cleanup_complete)
    assert desk.sandbox.get_positions() == [], desk.run.error
    assert len(desk.sandbox.get_trades()) == 2
    assert desk.read_calls == [("RELIANCE", "NSE")]
    events = desk.store.events(desk.scope.run_id, limit=1000)
    assert len([event for event in events if event["kind"] == "dispatch_result"]) == 2
    assert desk.token() not in repr(desk.protection.maintenance_snapshot())
    state.close()


def fixed(desk, **overrides):
    body = {"symbol": "RELIANCE", "exchange": "NSE", "product": "MIS", "action": "SELL", "quantity": 1}
    with desk.run.adapter.protective_action():
        return asyncio.run(desk.run.adapter.place_order(**{**body, **overrides}))


def test_read_credential_retirement_at_canonical_admission_refuses(protection_desk, monkeypatch):
    from flinttrade_core import order_routes
    desk = protection_desk
    assert grant(desk).status_code == 201
    original = order_routes._admit_place

    def retire(*args, **kwargs):
        result = original(*args, **kwargs)
        desk.credentials.clear()
        return result

    monkeypatch.setattr(order_routes, "_admit_place", retire)
    result = fixed(desk)
    assert result["status"] == "error", result
    assert len(desk.sandbox.get_trades()) == 1
    assert len(desk.read_calls) == 1


def test_restart_reconciles_exact_lost_ack_without_replaying_or_rearming(protection_desk, monkeypatch):
    from flinttrade_core.practice_agent_adapter import PracticeAgentAdapter
    from flinttrade_core.protection_grants import ProtectionServices
    desk = protection_desk
    assert grant(desk).status_code == 201
    original = desk.sandbox.place_order

    def lost_ack(**kwargs):
        original(**kwargs)
        raise TimeoutError("synthetic lost acknowledgement")

    with monkeypatch.context() as patch:
        patch.setattr(desk.sandbox, "place_order", lost_ack)
        result = fixed(desk)
    assert result["status"] == "error"
    assert len(desk.sandbox.get_trades()) == 2
    assert desk.protection.maintenance_snapshot()["runs"][0]["reconciliation_required"]
    desk.run.adapter.close()
    _wait_for(lambda: desk.run.cleanup_complete)
    restarted = ProtectionServices(desk.app, desk.protection_path)
    desk.app.config["PROTECTION_SERVICES"] = restarted
    assert hasattr(PracticeAgentAdapter, "for_protection"), "restart requires a JWT-free protection-only adapter"
    recovered = PracticeAgentAdapter.for_protection(desk.app, restarted, desk.scope)
    restarted.resume(desk.scope, desk.store, recovered)
    census = restarted.maintenance_snapshot()
    assert census["registry_complete"]
    assert not census["runs"][0]["reconciliation_required"]
    assert census["runs"][0]["attempts"][0]["state"] == "completed"
    assert len(desk.sandbox.get_trades()) == 2
    result = asyncio.run(recovered.place_order(symbol="RELIANCE", exchange="NSE", product="MIS",
                                              action="BUY", quantity=1))
    assert result["status"] == "error"
    assert len(desk.sandbox.get_trades()) == 2


def test_risk_change_after_quote_refuses_consumption(protection_desk, monkeypatch):
    from flinttrade_core import order_routes
    desk = protection_desk
    assert grant(desk).status_code == 201
    original = order_routes._admit_place

    def change_risk(*args, **kwargs):
        result = original(*args, **kwargs)
        desk.sandbox.update_config(equity_leverage=2)
        return result

    monkeypatch.setattr(order_routes, "_admit_place", change_risk)
    result = fixed(desk)
    assert result["status"] == "error", result
    assert len(desk.sandbox.get_trades()) == 1
    assert not desk.protection.maintenance_snapshot()["runs"][0]["attempts"]


def test_explicit_revocation_retains_duty_and_blocks_admission(protection_desk):
    desk = protection_desk
    assert grant(desk).status_code == 201
    response = desk.client.post(f"/api/v1/protection/grants/{desk.scope.run_id}/revoke",
        headers=desk.operator_headers, json={"expected_revision": 1})
    assert response.status_code == 200, response.json
    assert fixed(desk)["status"] == "error"
    assert len(desk.sandbox.get_trades()) == 1
    census = desk.protection.maintenance_snapshot()
    assert census["runs"][0]["revoked"]
    assert not census["disposal_authorised"]


def test_missing_registry_after_restart_is_unknown_not_empty(protection_desk):
    from flinttrade_core.protection_grants import ProtectionServices
    desk = protection_desk
    assert grant(desk).status_code == 201
    for suffix in ("", ".authority.json", "-wal", "-shm"):
        (desk.protection_path / ("protection.sqlite" + suffix)).unlink(missing_ok=True)
    reopened = ProtectionServices(desk.app, desk.protection_path)
    census = reopened.maintenance_snapshot()
    assert not census["registry_complete"]
    assert not census["disposal_authorised"]
    assert not (desk.protection_path / "protection.sqlite").exists()


@pytest.mark.parametrize("change", ["max_quantity", "max_notional", "valid_until", "read", "hedge_scope"])
def test_policy_is_explicit_and_never_invents_limits(protection_desk, change):
    desk = protection_desk
    policy = dict(desk.policy)
    del policy[change]
    result = desk.client.post("/api/v1/protection/grants", headers=desk.operator_headers,
        json={"run_id": desk.scope.run_id, "expected_revision": 0, "policy": policy})
    assert result.status_code == 403
    assert not (desk.protection_path / "protection.sqlite").exists()
    assert len(desk.sandbox.get_trades()) == 1


@pytest.mark.parametrize("kind", ["foreign", "scoped", "expired", "api", "origin", "conflicting"])
def test_grant_requires_exact_fresh_operator_authority(protection_desk, kind):
    desk = protection_desk
    headers = dict(desk.operator_headers)
    if kind == "foreign":
        headers["Authorization"] = "Bearer " + desk.token(sub="other", scopes=["admin.accounts.read", "admin.accounts.write"])
    elif kind == "scoped":
        headers["Authorization"] = "Bearer " + desk.token(scopes=["admin.accounts.read"])
    elif kind == "expired":
        headers["Authorization"] = "Bearer " + desk.token(exp=1)
    elif kind == "api":
        headers = {"X-API-Key": "synthetic"}
    elif kind == "origin":
        headers["Origin"] = "http://127.0.0.1:9999"
    else:
        headers["X-FlintTrade-Token"] = desk.token(jti="other")
    result = desk.client.post("/api/v1/protection/grants", headers=headers,
        json={"run_id": desk.scope.run_id, "expected_revision": 0, "policy": desk.policy})
    assert result.status_code in {400, 403}
    assert not (desk.protection_path / "protection.sqlite").exists()


@pytest.mark.parametrize("raw", ["[]", "null", "{", '{"run_id":"one","run_id":"two"}',
                                  '{"run_id": "x", "expected_revision":NaN}'])
def test_malformed_grant_http_is_zero_write(protection_desk, raw):
    desk = protection_desk
    response = desk.client.post("/api/v1/protection/grants", headers=desk.operator_headers,
                                data=raw, content_type="application/json")
    assert response.status_code == 400
    assert not (desk.protection_path / "protection.sqlite").exists()


@pytest.mark.parametrize("change", ["oversize", "wrong-side", "wrong-contract", "notional", "expiry", "read-expiry"])
def test_grant_never_expands_to_entry_foreign_or_unbounded_write(protection_desk, monkeypatch, change):
    desk = protection_desk
    policy = {"max_notional": 1.0} if change == "notional" else {}
    assert grant(desk, **policy).status_code == 201
    body = {}
    if change == "oversize":
        body["quantity"] = 2
    elif change == "wrong-side":
        body["action"] = "BUY"
    elif change == "wrong-contract":
        body["symbol"] = "TCS"
    elif change in {"expiry", "read-expiry"}:
        from flinttrade_core import protection_grants
        instant = desk.policy["valid_until"] + 1 if change == "expiry" else desk.policy["read"]["valid_until"] + 1
        monkeypatch.setattr(protection_grants.time, "time", lambda: instant)
    result = fixed(desk, **body)
    assert result["status"] == "error", result
    assert len(desk.sandbox.get_trades()) == 1
    assert not desk.protection.maintenance_snapshot()["disposal_authorised"]


def test_http_fields_cannot_forge_protection_and_manual_close_stays_separate(protection_desk):
    desk = protection_desk
    assert grant(desk).status_code == 201
    body = {"symbol": "RELIANCE", "exchange": "NSE", "product": "MIS", "action": "SELL", "quantity": 1,
            "price": 123.5, "price_basis": "ltp", "protection_principal": asdict(desk.scope),
            "protective_action": True, "run_id": desk.scope.run_id, "reduce_only": True}
    refused = desk.client.post("/api/v1/orders/place", json=body,
                               headers={"X-Protection-Grant": desk.scope.run_id, "X-FlintTrade-Mode": "practice"})
    assert refused.status_code == 401
    assert len(desk.sandbox.get_trades()) == 1
    # An explicitly authenticated manual reduction needs no model or protection grant.
    from flinttrade_engine.laya import DecisionStatus, process_laya
    process_laya().set_status(DecisionStatus.DOWN)
    for key in ("protection_principal", "protective_action", "run_id", "reduce_only"):
        body.pop(key)
    response = desk.client.post("/api/v1/orders/place", headers=desk.operator_headers, json=body)
    assert response.status_code == 200, response.json
    assert desk.sandbox.get_positions() == []


def test_one_shot_principal_is_consumed_and_cannot_be_copied_or_replayed(protection_desk, monkeypatch):
    from copy import copy
    from flinttrade_core import order_routes
    from flask import request
    desk = protection_desk
    assert grant(desk).status_code == 201
    captured = {}
    original = order_routes.place_order

    def capture():
        captured.update(body=request.get_json(), principal=request.environ["flinttrade.protection_principal"])
        assert "Authorization" not in request.headers
        return original()

    with monkeypatch.context() as patch:
        patch.setattr(order_routes, "place_order", capture)
        assert fixed(desk)["status"] == "COMPLETE"
    for principal in (captured["principal"], copy(captured["principal"]), asdict(desk.scope)):
        with desk.app.test_request_context("/api/v1/orders/place", method="POST", json=captured["body"],
                environ_overrides={"flinttrade.protection_principal": principal}):
            response = desk.app.make_response(original())
            assert response.status_code == 401
    assert len(desk.sandbox.get_trades()) == 2


def test_pending_entry_and_later_fill_never_become_granted_position(protection_desk):
    desk = protection_desk
    assert grant(desk).status_code == 201
    pending = desk.sandbox.place_order(symbol="RELIANCE", exchange="NSE", product="MIS", action="BUY",
                                      quantity=1, price=120.0, order_type="LIMIT")
    assert pending["status"] == "PENDING"
    assert fixed(desk)["status"] == "error"
    assert desk.sandbox.check_pending_fills({"RELIANCE": 119.0}) == [pending["order_id"]]
    assert fixed(desk)["status"] == "error"
    assert len(desk.sandbox.get_trades()) == 2
    assert desk.sandbox.get_positions()[0]["net_qty"] == 2


def test_restart_known_open_duty_can_reduce_but_never_rearms(protection_desk):
    from flinttrade_core.practice_agent_adapter import PracticeAgentAdapter
    from flinttrade_core.protection_grants import ProtectionServices
    desk = protection_desk
    assert grant(desk).status_code == 201
    desk.run.adapter.close()
    _wait_for(lambda: desk.run.cleanup_complete)
    assert len(desk.sandbox.get_trades()) == 1
    desk.revoked.add("practice-session")
    restarted = ProtectionServices(desk.app, desk.protection_path)
    desk.app.config["PROTECTION_SERVICES"] = restarted
    adapter = PracticeAgentAdapter.for_protection(desk.app, restarted, desk.scope)
    restarted.resume(desk.scope, desk.store, adapter)
    desk.app.config.update(MODE="live", ACTIVE_ACCOUNT="native:other:account")
    body = {"symbol": "RELIANCE", "exchange": "NSE", "product": "MIS", "action": "SELL", "quantity": 1}
    assert asyncio.run(adapter.place_order(**body))["status"] == "error"
    with adapter.protective_action():
        assert asyncio.run(adapter.place_order(**body))["status"] == "COMPLETE"
    assert desk.sandbox.get_positions() == []


def test_unknown_write_with_no_exact_order_remains_owned_on_restart(protection_desk, monkeypatch):
    from flinttrade_core.practice_agent_adapter import PracticeAgentAdapter, PracticeAgentError
    from flinttrade_core.protection_grants import ProtectionServices
    desk = protection_desk
    assert grant(desk).status_code == 201

    def interrupted(**kwargs):
        raise TimeoutError("synthetic crash at invocation")

    with monkeypatch.context() as patch:
        patch.setattr(desk.sandbox, "place_order", interrupted)
        assert fixed(desk)["status"] == "error"
    desk.run.adapter.close()
    _wait_for(lambda: desk.run.cleanup_complete)
    restarted = ProtectionServices(desk.app, desk.protection_path)
    desk.app.config["PROTECTION_SERVICES"] = restarted
    adapter = PracticeAgentAdapter.for_protection(desk.app, restarted, desk.scope)
    with pytest.raises(PracticeAgentError, match="reconciliation"):
        restarted.resume(desk.scope, desk.store, adapter)
    with pytest.raises(PracticeAgentError, match="duties_retained"):
        restarted.close()
    assert len(desk.sandbox.get_trades()) == 1
    assert restarted.maintenance_snapshot()["runs"][0]["reconciliation_required"]


@pytest.mark.parametrize("ui_mode", ["practice", "live"])
def test_exact_execution_session_uses_its_book_not_active_ui_scope(protection_desk, tmp_path, monkeypatch, ui_mode):
    from flinttrade_core.execution_session import ExecutionSession
    from flinttrade_core.execution_sessions import ExecutionSessions
    from flinttrade_core.practice_agent_runtime import validate_practice_config
    desk = protection_desk
    registry = ExecutionSessions(desk.app, tmp_path / "exact-runs")
    scope = ExecutionSession("paper-independent", desk.owner, "paper:run:paper-independent", "paper")
    config = validate_practice_config({"symbols": ["RELIANCE"], "cycle_interval_sec": 3600})
    registry.create(scope, kind="practice", config=config)
    try:
        registry.start(scope, token=desk.token(mode=ui_mode), expected_generation=0)
        supervisor = registry.owners[scope.run_id]
        _wait_for(lambda: supervisor.run.snapshot.get("cycle_count") == 1)
        run, book = supervisor.run, supervisor.sandbox
        assert book is not desk.sandbox
        assert len(book.get_trades()) == 1
        desk.protection.attach(scope, supervisor.store, run.adapter)
        policy = {**desk.policy, "position": {**desk.policy["position"],
                  "entry_order_ids": [book.get_trades()[0]["order_id"]]}}
        authorised = desk.client.post("/api/v1/protection/grants", headers=desk.operator_headers,
            json={"run_id": scope.run_id, "expected_revision": 0, "policy": policy})
        assert authorised.status_code == 201, authorised.json
        from flinttrade_core.practice_agent_adapter import PracticeAgentAdapter, PracticeAgentError
        with pytest.raises(PracticeAgentError):
            PracticeAgentAdapter.for_protection(desk.app, desk.protection, scope)
        recovered = PracticeAgentAdapter.for_protection(desk.app, desk.protection, scope,
                                                        execution_binding=registry.binding(scope))
        with pytest.raises(PracticeAgentError):
            recovered.validate_session()
        registry.retire_actor(desk.owner)
        desk.app.config.update(MODE="live", ACTIVE_ACCOUNT="native:other:account")
        body = {"symbol": "RELIANCE", "exchange": "NSE", "product": "MIS", "action": "BUY", "quantity": 1}
        assert asyncio.run(run.adapter.place_order(**body))["status"] == "error"
        from flask import request
        from flinttrade_core import order_routes
        canonical = order_routes.place_order

        def lose_binding():
            request.environ.pop("flinttrade.execution_binding")
            return canonical()

        with monkeypatch.context() as patch:
            patch.setattr(order_routes, "place_order", lose_binding)
            assert asyncio.run(run.adapter.place_order(**{**body, "action": "SELL"}))["status"] == "error"
            assert len(desk.sandbox.get_trades()) == 1, "Ordinary reductions must keep their exact run book too"
            with run.adapter.protective_action():
                assert asyncio.run(run.adapter.place_order(**{**body, "action": "SELL"}))["status"] == "error"
        assert len(desk.sandbox.get_trades()) == 1, "A missing bound book must never fall back to the UI book"
        with run.adapter.protective_action():
            reduced = asyncio.run(run.adapter.place_order(**{**body, "action": "SELL"}))
        assert reduced["status"] == "COMPLETE", reduced
        assert book.get_positions() == []
        assert len(book.get_trades()) == 2
        assert len(desk.sandbox.get_trades()) == 1
    finally:
        registry.shutdown(timeout=5)
        registry.close()


def test_unresolved_entry_dispatch_is_not_erased_by_protection_restart(protection_desk, monkeypatch):
    from flinttrade_core.practice_agent_adapter import PracticeAgentAdapter, PracticeAgentError
    from flinttrade_core.protection_grants import ProtectionServices
    desk = protection_desk
    assert grant(desk).status_code == 201

    def unknown(**kwargs):
        raise TimeoutError("synthetic entry outcome unknown")

    with monkeypatch.context() as patch:
        patch.setattr(desk.sandbox, "place_order", unknown)
        result = asyncio.run(desk.run.adapter.place_order(symbol="RELIANCE", exchange="NSE", product="MIS",
                                                          action="BUY", quantity=1))
    assert result["status"] == "error"
    assert desk.run.adapter.reconciliation_required
    desk.run.adapter.close()
    _wait_for(lambda: desk.run.cleanup_complete)
    services = ProtectionServices(desk.app, desk.protection_path)
    desk.app.config["PROTECTION_SERVICES"] = services
    recovered = PracticeAgentAdapter.for_protection(desk.app, services, desk.scope)
    with pytest.raises(PracticeAgentError, match="reconciliation"):
        services.resume(desk.scope, desk.store, recovered)
    assert len(desk.sandbox.get_trades()) == 1


def test_completed_exact_duty_can_be_reconciled_and_closed(protection_desk):
    desk = protection_desk
    assert grant(desk).status_code == 201
    _supervisor(desk).stop(desk.owner)
    _wait_for(lambda: desk.store.get_run(desk.scope.run_id)["status"] == "stopped")
    result = desk.protection.reconcile(desk.scope)
    assert result["remaining_quantity"] == 0
    census = desk.protection.maintenance_snapshot()
    assert census["registry_complete"]
    assert census["disposal_authorised"], census
    desk.protection.close()


def test_copied_execution_book_after_restart_cannot_transfer_grant(protection_desk, tmp_path):
    import shutil
    from flinttrade_core.practice_agent_adapter import PracticeAgentAdapter, PracticeAgentError
    from flinttrade_core.protection_grants import ProtectionServices
    from flinttrade_data.sandbox_engine import SandboxEngine
    desk = protection_desk
    assert grant(desk).status_code == 201
    desk.run.adapter.close()
    _wait_for(lambda: desk.run.cleanup_complete)
    desk.sandbox._conn.execute("PRAGMA wal_checkpoint(FULL)")
    target = tmp_path / "substituted.sqlite"
    shutil.copyfile(desk.sandbox._db_path, target)
    replacement = SandboxEngine(str(target), strict_existing=True)
    try:
        desk.app.config["DATA_SANDBOX_ENGINE"] = replacement
        services = ProtectionServices(desk.app, desk.protection_path)
        desk.app.config["PROTECTION_SERVICES"] = services
        recovered = PracticeAgentAdapter.for_protection(desk.app, services, desk.scope)
        with pytest.raises(PracticeAgentError):
            services.resume(desk.scope, desk.store, recovered)
        assert not services.maintenance_snapshot()["disposal_authorised"]
        assert len(replacement.get_trades()) == 1
    finally:
        desk.app.config["DATA_SANDBOX_ENGINE"] = desk.sandbox
        replacement.close()


def test_stale_model_reduction_never_uses_fixed_protection_grant(protection_desk):
    from flinttrade_core.execution_session import PracticeRunOwner
    desk = protection_desk
    assert grant(desk).status_code == 201
    owner = PracticeRunOwner(_supervisor(desk))

    class CurrentGeneration:
        def accepts(self, run_id, role, *, generation, candidate):
            return generation == 2 and candidate == "current"

    desk.run.adapter.bind_model_admission(owner, CurrentGeneration(), desk.scope.run_id, "reasoning")
    desk.run.adapter.record_model_proposal(1, "retired")
    result = asyncio.run(desk.run.adapter.place_order(symbol="RELIANCE", exchange="NSE", product="MIS",
                                                     action="SELL", quantity=1))
    assert result["code"] == "practice_model_generation_retired", result
    assert len(desk.sandbox.get_trades()) == 1
    assert fixed(desk)["status"] == "COMPLETE"


def test_fixed_close_cannot_open_after_ownership_proof_changes(protection_desk, monkeypatch):
    from flinttrade_core import order_routes
    desk = protection_desk
    assert grant(desk).status_code == 201
    original = order_routes._admit_place

    def changed(*args, **kwargs):
        result = original(*args, **kwargs)
        desk.sandbox.reset()
        return result

    monkeypatch.setattr(order_routes, "_admit_place", changed)
    assert fixed(desk)["status"] == "error"
    assert desk.sandbox.get_positions() == []
    assert desk.sandbox.get_trades() == []


def test_attaching_owner_does_not_retire_existing_session_protection(protection_desk):
    desk = protection_desk
    # Attachment supplies identity, not permission. Existing current-session
    # protection remains canonical until a separate policy is actually issued.
    assert fixed(desk)["status"] == "COMPLETE"
    assert len(desk.sandbox.get_trades()) == 2
    assert not (desk.protection_path / "protection.sqlite").exists()
