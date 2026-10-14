"""Independent durable Paper identities using the actual sandbox ledger."""
from __future__ import annotations

import importlib.util
from dataclasses import replace

import pytest

from flinttrade_core.execution_session import ExecutionSession

from packages.core.core.tests.test_practice_agent_runtime import desk as desk, _wait_for

pytestmark = pytest.mark.integration


def test_public_paper_start_beside_live_uses_real_independent_workers(desk, tmp_path):
    assert importlib.util.find_spec("flinttrade_core.execution_sessions_routes") is not None, "session routes missing"
    from flinttrade_core.execution_sessions_routes import install_execution_sessions
    install_execution_sessions(desk.app, tmp_path)
    headers = {"Authorization": "Bearer " + desk.token(mode="live", scopes=["admin.services.read", "admin.services.write", "admin.accounts.read", "admin.accounts.write"]), "X-FlintTrade-Mode": "live"}
    ids = ("paper-one", "paper-two")
    try:
        for run_id in ids:
            result = desk.client.post("/api/v1/execution-sessions", headers=headers,
                json={"run_id": run_id, "kind": "practice", "config": {"symbols": ["RELIANCE"], "cycle_interval_sec": 3600}})
            assert result.status_code == 201, result.json
            row = result.json["data"]
            target = {"account": row["account"], "environment": "paper", "expected_generation": row["generation"]}
            started = desk.client.post(f"/api/v1/execution-sessions/{run_id}/start", headers=headers, json=target)
            assert started.status_code == 202, started.json
        sessions = desk.app.config["EXECUTION_SESSIONS"]
        _wait_for(lambda: all(sessions.owners[i].run.snapshot.get("cycle_count") == 1 for i in ids))
        assert all(sessions.owners[i].app is desk.app for i in ids)
        assert all(sessions.owners[i].sandbox is not desk.sandbox for i in ids)
        assert sessions.owners[ids[0]].sandbox is not sessions.owners[ids[1]].sandbox
        assert desk.app.config["DATA_SANDBOX_ENGINE"] is desk.sandbox
        first = sessions.scope(ids[0], desk.owner)
        row = sessions.status(first)
        result = desk.client.post(f"/api/v1/execution-sessions/{ids[0]}/stop", headers=headers,
            json={"account": row["account"], "environment": "paper", "expected_generation": row["generation"]})
        assert result.status_code == 200, result.json
        assert not result.json["data"]["entries_armed"]
        assert sessions.owners[ids[0]].run.thread.is_alive(), "Stop entries retains protection owner"
        assert sessions.status(sessions.scope(ids[1], desk.owner))["entries_armed"]
    finally:
        sessions = desk.app.config.get("EXECUTION_SESSIONS")
        if sessions:
            assert sessions.shutdown(timeout=5)
            sessions.close()


def test_real_paper_fills_stop_entries_close_and_time_boundary_are_run_scoped(desk, tmp_path):
    from flinttrade_core.execution_sessions_routes import install_execution_sessions
    install_execution_sessions(desk.app, tmp_path)
    token = desk.token(mode="live", scopes=["admin.services.read", "admin.services.write", "admin.accounts.read", "admin.accounts.write"])
    headers = {"Authorization": "Bearer " + token, "X-FlintTrade-Mode": "live"}
    desk.signal = "BUY"
    sessions = None
    scopes = []
    def command(scope, operation):
        row = sessions.status(scope)
        return desk.client.post(f"/api/v1/execution-sessions/{scope.run_id}/{operation}", headers=headers,
            json={"account": scope.account, "environment": scope.environment, "expected_generation": row["generation"]})
    try:
        for identity in ("fills-one", "fills-two"):
            created = desk.client.post("/api/v1/execution-sessions", headers=headers,
                json={"run_id": identity, "kind": "practice", "config": {"symbols": ["RELIANCE"], "cycle_interval_sec": 3600}})
            assert created.status_code == 201, created.json
            sessions = desk.app.config["EXECUTION_SESSIONS"]
            scope = sessions.scope(identity, desk.owner)
            scopes.append(scope)
            assert command(scope, "start").status_code == 202
        _wait_for(lambda: all(sessions.status(scope)["books"]["positions"] for scope in scopes))
        for scope in scopes:
            assert sessions.status(scope)["books"]["positions"][0]["net_qty"] == 1
        assert desk.sandbox.get_trades() == []
        first, second = scopes
        assert command(first, "stop").status_code == 200
        assert sessions.status(first)["books"]["positions"][0]["net_qty"] == 1
        # No routine market-close liquidation in the independent owner.
        desk.now = desk.now.replace(hour=15, minute=20)
        assert not sessions.owners[first.run_id].run.trader._is_square_off_time()
        close = command(first, "close")
        assert close.status_code == 202, close.json
        _wait_for(lambda: not sessions.status(first)["books"]["positions"])
        assert len(sessions.status(first)["books"]["trades"]) == 2
        assert sessions.status(second)["books"]["positions"][0]["net_qty"] == 1
        assert command(second, "close").status_code == 202
        _wait_for(lambda: all(owner.run.cleanup_complete for owner in sessions.owners.values()))
        assert desk.sandbox.get_trades() == []
    finally:
        if sessions is not None:
            assert sessions.shutdown(timeout=5)
            sessions.close()


@pytest.mark.parametrize("loss", ["file", "orders", "capital"])
def test_missing_established_book_is_unknown_never_recreated(desk, tmp_path, loss):
    import sqlite3
    sessions = registry(desk.app, tmp_path / "custody")
    scope = ExecutionSession("custody", desk.owner, "paper:run:custody", "paper")
    sessions.create(scope, kind="practice", config={"symbols": ["RELIANCE"]})
    path = tmp_path / "custody" / "custody" / "state.sqlite"
    sessions.close()
    if loss == "file":
        path.unlink()
    else:
        with sqlite3.connect(path) as db:
            db.execute("DROP TABLE orders" if loss == "orders" else "DELETE FROM capital")
    sessions = registry(desk.app, tmp_path / "custody")
    try:
        assert sessions.status(scope)["state"] == "custody_unknown"
        assert sessions.status(scope)["books"] is None
        with pytest.raises((ValueError, OSError)):
            sessions.binding(scope)
        assert sessions.maintenance_snapshot()["disposal_authorised"] is False
    finally:
        sessions.close()


def test_census_includes_all_legacy_runs_and_default_book(desk, tmp_path):
    for n in range(105):
        identity = f"legacy-{n}"
        desk.store.create_run(run_id=identity, mode="practice", config={"owner": desk.owner})
        desk.store.transition_run(identity, status="stopped")
    desk.sandbox.place_order("RELIANCE", "NSE", "BUY", 1, 100.0)
    sessions = registry(desk.app, tmp_path / "census")
    try:
        census = sessions.maintenance_snapshot()
        assert len(census.get("legacy_runs", [])) == 105, "live dictionaries and first 100 rows are not a census"
        assert census["manual_paper"]["positions"][0]["net_qty"] == 1
        assert census["registry_complete"] is False
        assert census["disposal_authorised"] is False
    finally:
        sessions.close()


def test_restart_requires_explicit_rearm_and_does_not_replay(desk, tmp_path):
    from flinttrade_core.execution_sessions import ExecutionSessions
    from flinttrade_core.practice_agent_runtime import validate_practice_config
    scope = ExecutionSession("restart", desk.owner, "paper:run:restart", "paper")
    sessions = registry(desk.app, tmp_path / "restart-registry")
    sessions.create(scope, kind="practice", config=validate_practice_config({"symbols": ["RELIANCE"], "cycle_interval_sec": 3600}))
    token = desk.token(mode="live")
    sessions.start(scope, token=token, expected_generation=0)
    _wait_for(lambda: sessions.owners[scope.run_id].run.snapshot.get("cycle_count") == 1)
    assert sessions.shutdown(timeout=5)
    sessions.close()
    sessions = ExecutionSessions(desk.app, tmp_path / "restart-registry")
    try:
        before = sessions.status(scope)
        assert before["state"] == "rearm_required" and not before["entries_armed"]
        assert sessions.owners == {}
        with pytest.raises(ValueError):
            sessions.start(scope, token=token, expected_generation=before["generation"])
        result = sessions.start(scope, token=token, expected_generation=before["generation"], rearm=True)
        assert result["entries_armed"] and result["generation"] == before["generation"] + 1
        _wait_for(lambda: sessions.owners[scope.run_id].run.snapshot.get("cycle_count") == 1)
        assert sessions.status(scope)["books"]["trades"] == []
    finally:
        assert sessions.shutdown(timeout=5)
        sessions.close()


@pytest.mark.parametrize("mutation", ["account", "environment", "actor", "generation", "malformed", "array", "extra", "origin"])
def test_public_controls_refuse_retargeting_without_changing_either_run(desk, tmp_path, mutation):
    from flinttrade_core.execution_sessions_routes import install_execution_sessions, get_execution_sessions
    from dataclasses import asdict
    install_execution_sessions(desk.app, tmp_path)
    sessions = get_execution_sessions(desk.app)
    first = ExecutionSession("exact-one", desk.owner, "paper:run:exact-one", "paper")
    second = ExecutionSession("exact-two", desk.owner, "paper:run:exact-two", "paper")
    for scope in (first, second):
        sessions.create(scope, kind="practice", config={"symbols": ["RELIANCE"]})
    claims = {"scopes": ["admin.services.read", "admin.services.write", "admin.accounts.read", "admin.accounts.write"]}
    if mutation == "actor":
        claims["sub"] = "someone-else"
    headers = {"Authorization": "Bearer " + desk.token(**claims)}
    payload = {"account": first.account, "environment": first.environment, "expected_generation": 0}
    if mutation == "account":
        payload["account"] = second.account
    if mutation == "environment":
        payload["environment"] = "live"
    if mutation == "generation":
        payload["expected_generation"] = True
    if mutation == "extra":
        payload["scope"] = asdict(second)
    if mutation == "origin":
        headers["Origin"] = "https://foreign.invalid"
    before = sessions.list(desk.owner)
    try:
        if mutation in {"malformed", "array"}:
            result = desk.client.post("/api/v1/execution-sessions/exact-one/stop", headers=headers,
                                      data="{" if mutation == "malformed" else "[]", content_type="application/json")
        else:
            result = desk.client.post("/api/v1/execution-sessions/exact-one/stop", headers=headers, json=payload)
        assert result.status_code in {400, 403, 409}, result.json
        assert sessions.list(desk.owner) == before
    finally:
        sessions.close()


def test_rearm_existing_history_requires_exact_scope_and_complete_dispatch_pairs(tmp_path):
    from flinttrade_ai.run_store import AgentRunStore
    scope = ExecutionSession("rearm", "operator", "paper:run:rearm", "paper")
    from dataclasses import asdict
    store = AgentRunStore(tmp_path / "rearm.sqlite")
    try:
        store.create_run(run_id=scope.run_id, mode="practice", config={"owner": scope.actor, "execution_session": asdict(scope)})
        store.transition_run(scope.run_id, status="stopped")
        assert hasattr(store, "rearm_execution"), "exact durable rearm missing"
        with pytest.raises(ValueError):
            store.rearm_execution({**asdict(scope), "account": "paper:sandbox"})
        assert store.rearm_execution(asdict(scope))["status"] == "starting"
        store.append_event(scope.run_id, kind="dispatch_started", data={"order": {"symbol": "RELIANCE"}})
        store.recover_interrupted()
        with pytest.raises(ValueError, match="uncertain"):
            store.rearm_execution(asdict(scope))
        assert store.get_run(scope.run_id)["status"] == "reconciliation_required"
    finally:
        store.close()


def test_real_strategy_runner_has_two_exact_paper_owners_not_name_only(desk, tmp_path):
    from flinttrade_core.execution_sessions_routes import install_execution_sessions
    from flinttrade_engine.strategy import BaseStrategy
    from flinttrade_engine.strategy_execution import StrategyExecutionContract, StrategyExecutionMode
    from flinttrade_core.models import Order

    class SyntheticTickStrategy(BaseStrategy):
        """Internal synthetic strategy; no native/provider qualification."""
        supported_execution_modes = frozenset({StrategyExecutionMode.PRACTICE})
        def __init__(self, scope, config):
            super().__init__(name="same-strategy", execution_contract=StrategyExecutionContract.practice(),
                             strategy_id=scope.run_id, state_root=tmp_path / "strategy-state")
            self.pending = []
            self.entered = False
        def on_tick(self, quote):
            if not self.entered:
                self.pending.append(Order(symbol="RELIANCE", exchange="NSE", product="MIS", action="BUY", quantity="1"))
                self.entered = True
        def on_bar(self, bar): pass
        def on_signal(self, signal): pass
        def generate_orders(self):
            result, self.pending = self.pending, []
            return result

    from flinttrade_core.protection_grants import install_protection_services
    protection = install_protection_services(desk.app, tmp_path / "strategy-protection")
    desk.app.config["EXECUTION_STRATEGY_FACTORIES"] = {"synthetic-tick": SyntheticTickStrategy}
    desk.app.config["TIME_SCHEDULER"].is_market_open = lambda *_args, **_kwargs: True
    install_execution_sessions(desk.app, tmp_path)
    headers = {"Authorization": "Bearer " + desk.token(mode="live", scopes=["admin.services.read", "admin.services.write", "admin.accounts.read", "admin.accounts.write"])}
    sessions = None
    try:
        for identity in ("strategy-one", "strategy-two"):
            result = desk.client.post("/api/v1/execution-sessions", headers=headers,
                json={"run_id": identity, "kind": "strategy", "config": {"symbols": ["RELIANCE"], "strategy": "synthetic-tick"}})
            assert result.status_code == 201, result.json
            sessions = desk.app.config["EXECUTION_SESSIONS"]
            scope = sessions.scope(identity, desk.owner)
            sessions.start(scope, token=desk.token(mode="live"), expected_generation=0)
        _wait_for(lambda: all(sessions.status(sessions.scope(identity, desk.owner))["books"]["positions"]
                             for identity in ("strategy-one", "strategy-two")))
        for identity in ("strategy-one", "strategy-two"):
            scope = sessions.scope(identity, desk.owner)
            row = sessions.status(scope)
            assert row["books"]["positions"][0]["net_qty"] == 1
            assert sessions.owners[identity].run.adapter._protection == (protection, scope)
            assert not protection.has_grant(scope)
            sessions.close_positions(scope, expected_generation=row["generation"])
        _wait_for(lambda: all(owner.run.cleanup_complete for owner in sessions.owners.values()))
        assert desk.sandbox.get_trades() == []
    finally:
        if sessions:
            for identity, worker in sessions.owners.items():
                if worker.run.thread.is_alive():
                    scope = sessions.scope(identity, desk.owner)
                    sessions.close_positions(scope, expected_generation=sessions.status(scope)["generation"])
                    _wait_for(lambda worker=worker: not worker.run.thread.is_alive())
            assert sessions.shutdown(timeout=5)
            sessions.close()


def test_lost_registry_and_marker_do_not_recreate_empty_history(desk, tmp_path):
    path = tmp_path / "lost-registry"
    sessions = registry(desk.app, path)
    scope = ExecutionSession("live-identity", desk.owner, "native:dhan:synthetic", "live")
    sessions.create(scope, kind="practice", config={})
    assert sessions.status(scope)["state"] == "native_unavailable"
    with pytest.raises(ValueError):
        sessions.start(scope, token=desk.token(mode="live"), expected_generation=0)
    sessions.close()
    (path / "registry.sqlite").unlink()
    (path / "registry.sqlite.authority.json").unlink()
    with pytest.raises(ValueError, match="custody"):
        registry(desk.app, path)
    assert not (path / "registry.sqlite").exists()


def test_failed_owner_construction_never_leaves_entries_armed(desk, tmp_path, monkeypatch):
    from flinttrade_core import practice_agent_runtime
    sessions = registry(desk.app, tmp_path / "failed-construction")
    scope = ExecutionSession("constructor", desk.owner, "paper:run:constructor", "paper")
    sessions.create(scope, kind="practice", config={"symbols": ["RELIANCE"]})
    def fail(*_args, **_kwargs):
        raise RuntimeError("synthetic owner construction failure")
    monkeypatch.setattr(practice_agent_runtime, "PracticeAgentSupervisor", fail)
    try:
        with pytest.raises(RuntimeError):
            sessions.start(scope, token=desk.token(), expected_generation=0)
        assert not sessions.status(scope)["entries_armed"]
        assert sessions.status(scope)["state"] == "reconciliation_required"
    finally:
        sessions.close()


def test_new_run_books_copy_current_sandbox_policy_without_sharing_balances(desk, tmp_path):
    desk.sandbox.update_config(starting_capital=75_000, equity_leverage=2)
    sessions = registry(desk.app, tmp_path / "policy")
    scope = ExecutionSession("policy", desk.owner, "paper:run:policy", "paper")
    try:
        sessions.create(scope, kind="practice", config={"symbols": ["RELIANCE"]})
        book = sessions.binding(scope).sandbox
        assert book.config == desk.sandbox.config
        assert book.config is not desk.sandbox.config
        book.place_order("RELIANCE", "NSE", "BUY", 1, 100.0)
        assert book.get_capital() != desk.sandbox.get_capital()
        assert desk.sandbox.get_positions() == []
    finally:
        sessions.close()


def registry(app, path):
    assert importlib.util.find_spec("flinttrade_core.execution_sessions") is not None, "durable session registry missing"
    from flinttrade_core.execution_sessions import ExecutionSessions
    return ExecutionSessions(app, path)


def test_independent_books_exact_stop_and_restart(tmp_path, backend_lease_proof):
    from flask import Flask
    from flinttrade_data.sandbox_engine import SandboxEngine

    app = Flask(__name__)
    manual = SandboxEngine(str(tmp_path / "manual.sqlite"))
    app.config.update(BACKEND_LEASE_PROOF=backend_lease_proof, RUNTIME_ACCEPTING_REQUESTS=True,
                      DATA_SANDBOX_ENGINE=manual)
    sessions = registry(app, tmp_path / "sessions")
    a = ExecutionSession("paper-a", "operator", "paper:run:paper-a", "paper")
    b = ExecutionSession("paper-b", "operator", "paper:run:paper-b", "paper")
    try:
        for scope in (a, b):
            sessions.create(scope, kind="practice", config={"symbols": ["RELIANCE"]})
        first, second = sessions.binding(a), sessions.binding(b)
        assert first.sandbox is not second.sandbox and first.sandbox is not manual
        first.sandbox.place_order("RELIANCE", "NSE", "BUY", 1, 100.0)
        second.sandbox.place_order("RELIANCE", "NSE", "BUY", 2, 100.0)
        assert first.sandbox.get_positions()[0]["net_qty"] == 1
        assert second.sandbox.get_positions()[0]["net_qty"] == 2
        assert manual.get_positions() == []
        assert app.config["DATA_SANDBOX_ENGINE"] is manual
        with pytest.raises(ValueError, match="scope"):
            sessions.stop_entries(replace(a, account=b.account), expected_generation=0)
        stopped = sessions.stop_entries(a, expected_generation=0)
        assert stopped["generation"] == 1 and not stopped["entries_armed"]
        assert len(first.sandbox.get_trades()) == 1, "Stop entries is not Close"
        assert sessions.status(b)["generation"] == 0
        with pytest.raises(ValueError, match="generation"):
            sessions.stop_entries(a, expected_generation=0)
        census = sessions.maintenance_snapshot()
        assert census["registry_complete"] is False and census["history"] == "unknown"
        assert {row["run_id"] for row in census["runs"]} == {a.run_id, b.run_id}
        assert not census["disposal_authorised"]
    finally:
        sessions.close()
    reopened = registry(app, tmp_path / "sessions")
    try:
        assert reopened.status(b)["state"] == "rearm_required"
        assert not reopened.status(b)["entries_armed"]
        assert reopened.binding(a).sandbox.get_positions()[0]["net_qty"] == 1
    finally:
        reopened.close()
        manual.close()
