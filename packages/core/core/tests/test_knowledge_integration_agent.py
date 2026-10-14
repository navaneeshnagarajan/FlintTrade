"""Actual start-route composition and protection-preserving owner lifetimes."""
from __future__ import annotations

import asyncio
import threading
from datetime import datetime
from unittest.mock import MagicMock

import pytest

from packages.core.core.tests.test_knowledge_integration import knowledge as _knowledge_fixture
from packages.core.core.tests.test_service_tasks import HEADERS
from packages.core.core.tests.test_service_tasks import mounted as _mounted_fixture

knowledge = _knowledge_fixture
mounted = _mounted_fixture
pytestmark = pytest.mark.integration


def test_agent_start_uses_exact_backend_run_and_never_legacy_memory(knowledge, monkeypatch):
    import flinttrade_core.agent_routes as routes
    import flinttrade_core.order_routes as orders
    from flinttrade_ai.knowledge_store import KnowledgeMemory
    from flinttrade_ai.autonomous_agent import AutonomousTrader
    from flinttrade_engine.safety import SafetySystem, SafetyConfig
    app, client, store, calls = knowledge
    routes._reset_runner_for_tests()
    # Replace external execution/calendar/model inputs only; use real trader
    # construction and real route composition, but never run its order loop.
    constructed = []
    stop = threading.Event()
    async def inert_session(self):
        await asyncio.to_thread(stop.wait)
    def trader(**kwargs):
        result = AutonomousTrader(**kwargs)
        constructed.append(result)
        return result
    monkeypatch.setattr(routes, "_trader_factory", trader)
    monkeypatch.setattr(AutonomousTrader, "run_session", inert_session)
    monkeypatch.setattr(routes, "_agent_flag_enabled", lambda: True)
    monkeypatch.setattr(routes, "_acl_grants_agent", lambda *_: True)
    monkeypatch.setattr(routes, "_build_llm", lambda: MagicMock())
    monkeypatch.setattr(routes, "_build_vault", lambda: None)
    monkeypatch.setattr(orders, "_decode_request_payload", lambda: {"mode": "live", "sub": "fixture", "jti": "jti-fixture"})
    monkeypatch.setattr(orders, "_is_live_mode_unlocked", lambda: True)
    monkeypatch.setattr(orders, "_gated_target", lambda body: ("synthetic", "account-a"))
    monkeypatch.setattr(orders, "_require_live_safety", lambda: SafetySystem(SafetyConfig(check_market_hours=False)))
    from flinttrade_core import auth_routes
    from flinttrade_core.auth_routes import VerifiedOperatorSession
    principal = VerifiedOperatorSession("operator:" + "a" * 64, "session:" + "b" * 64,
                                        ("admin.services.read", "admin.services.write"))
    monkeypatch.setattr(auth_routes, "verify_operator_session_token", lambda token: principal)
    monkeypatch.setattr(auth_routes, "decode_token", lambda token: {"type": "session"})
    monkeypatch.setattr(auth_routes, "_is_jti_revoked", lambda jti: False)
    app.config.update(BROKER_ROUTER=object(), BROKER_CLIENT=object(), PENDING_ORDER_QUEUE=MagicMock(),
                      TIME_SCHEDULER=MagicMock(now_ist=lambda: datetime.fromisoformat("2026-07-13T10:00:00+05:30")))
    try:
        response = client.post("/api/v1/ai/agent/start", headers=HEADERS,
                               json={"symbols": ["FIXTURE"], "account_id": "forged", "run_id": "forged",
                                     "active_app": "Sandbox"})
        assert response.status_code == 202, response.json
        current = constructed[0]
        assert isinstance(current.memory, KnowledgeMemory), "legacy raw/vector memory reached actual trader"
        assert current.memory.scope.account_id == "native:synthetic:account-a"
        assert current.memory.scope.environment == "live"
        assert current.memory.scope.run_id == routes._RUNNER["producer_ref"]
        assert current.memory.scope.run_id != "forged"
        assert current.skill_registry.knowledge_scope == current.memory.scope
        assert current.memory.ledger is app.config["KNOWLEDGE_RUNTIME"].ledger
        resolver = app.config["SERVICE_TASK_CONTEXT_RESOLVER"]
        assert resolver.scope(principal.actor_ref) == current.memory.scope
        assert resolver.scope("operator:" + "c" * 64) is None
        assert current.automatic_learning is True
        current.state.closed_trades = [current._closed_trade_record(
            symbol="FIXTURE", action="BUY", entry_price=100, exit_price=101, quantity=1, pnl=1,
            exit_reason="synthetic-reconciled-test", exit_price_estimated=True)]
        asyncio.run(current._run_post_session_learning())
        assert current.join_background_learning(5)
        assert current.learning_candidates
        assert current._memory_context("FIXTURE") == "", "local candidate is not validation"
        for identity in current.learning_candidates:
            event = current.memory.ledger.get_event(identity)
            assert event.payload["run_id"] == routes._RUNNER["producer_ref"]
            assert event.payload["generation"] == "local-rule-candidate"
        assert current.learning_client.policy is None, "legacy native binding is not remote permission"
    finally:
        stop.set()
        thread = routes._RUNNER.get("thread")
        if thread:
            thread.join(5)
            assert not thread.is_alive()
        routes._reset_runner_for_tests()
    assert app.config["KNOWLEDGE_RUNTIME"].registry.context(["risk_management"])[0]
    assert not calls


def test_permission_family_redacts_arbitrary_body_path_and_request_id(knowledge, caplog):
    app, client, store, calls = knowledge
    marker = "synthetic-private-marker-never-log"
    for path in ("/v1/knowledge/" + marker, "/v1/learning/" + marker):
        result = client.post(path, headers={**HEADERS, "X-Request-ID": marker}, json={"secret": marker})
        assert result.status_code == 404
    assert marker not in caplog.text


def test_shutdown_waits_for_real_reflection_thread_before_shared_owner_close(knowledge):
    import flinttrade_core.agent_routes as routes
    from flinttrade_ai.autonomous_agent import AutonomousTrader, AgentStatus
    from flinttrade_ai.knowledge_store import KnowledgeScope
    from flinttrade_core.service_providers import RightsResolution
    app, client, store, calls = knowledge
    runtime = app.config["KNOWLEDGE_RUNTIME"]
    scope = KnowledgeScope("native:synthetic:account-a", "paper", "backend-run")
    trader = AutonomousTrader(object(), None, memory=runtime.memory(scope, rights=RightsResolution()))
    trader._status = AgentStatus.STOPPED
    entered, release = threading.Event(), threading.Event()
    def learner():
        entered.set()
        release.wait(5)
        runtime.registry.context(["risk_management"])
    worker = threading.Thread(target=learner)
    trader._learning_thread = worker
    session = threading.Thread(target=lambda: None)
    session.start()
    session.join()
    worker.start()
    routes._reset_runner_for_tests()
    try:
        assert entered.wait(2)
        with routes._RUNNER_LOCK:
            routes._RUNNER.update(trader=trader, thread=session)
        assert routes.shutdown_agent_runtime(app, timeout=0.01) is False
        assert worker.is_alive()
        # The shared owner remains available while the real reflection borrower
        # still has work; parent must honour the false drain result.
        assert runtime.registry.context(["risk_management"])[0]
        release.set()
        assert routes.shutdown_agent_runtime(app, timeout=3) is True
        assert not worker.is_alive()
        assert runtime.registry.context(["risk_management"])[0]
    finally:
        release.set()
        worker.join(5)
        routes._reset_runner_for_tests()


def test_boot_failure_is_unavailable_not_an_empty_registry(monkeypatch, request):
    from flinttrade_core import knowledge_integration
    attempts = []
    def broken(*args, **kwargs):
        attempts.append(True)
        raise RuntimeError("synthetic storage failure")
    # The normal factory now owns installation. Inject the storage fault before
    # obtaining its fixture, not after an already-successful idempotent install.
    monkeypatch.setattr(knowledge_integration.KnowledgeRuntime, "__init__", broken)
    app, client, store, calls = request.getfixturevalue("mounted")
    assert attempts == [True]
    assert app.config["KNOWLEDGE_RUNTIME"] is None
    assert app.config["SKILL_REGISTRY"] is None
    assert client.get("/v1/knowledge/skills", headers=HEADERS).status_code == 503
    assert app.config.get("SERVICE_TASK_DISPATCHER") is None
    assert not calls
