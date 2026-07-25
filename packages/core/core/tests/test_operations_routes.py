"""Tests for operations REST endpoints — safety, security, logs, errors, cron, ditto.

Run with:
    python -m pytest packages/core/core/tests/test_operations_routes.py -v --import-mode=importlib
"""

from __future__ import annotations

import hashlib
import hmac
import json
import os
import subprocess
import sys
import time
from unittest.mock import MagicMock

import pytest


_TEST_API_KEY = "test-operations-routes-key"


_WEBHOOK_REGISTRY_PROCESS_SCRIPT = r"""
import sys

from filelock import Timeout
from flinttrade_core import operations_routes
from flinttrade_webhooks.webhook_secret_store import WebhookSecretStore

workspace_home, db_path, slug, secret, timeout = sys.argv[1:]
operations_routes._WEBHOOK_REGISTRY_LOCK_TIMEOUT_SECONDS = float(timeout)
path = f"/v1/webhook/custom/{slug}"
try:
    with operations_routes._webhook_registry_lock():
        workspace, rows = operations_routes._load_webhook_registry()
        row = operations_routes._webhook_dict(path, slug, True)
        rows = [existing for existing in rows if existing["path"] != path]
        rows.append(row)
        store = WebhookSecretStore(db_path, "process-test-master-password")
        store.store_secret(path, "custom", slug, secret)
        operations_routes._save_webhook_registry(workspace, rows)
except Timeout:
    raise SystemExit(75)
"""


@pytest.fixture(scope="module")
def monkeypatch_module():
    """Module-scoped monkeypatch fixture."""
    from _pytest.monkeypatch import MonkeyPatch

    mp = MonkeyPatch()
    yield mp
    mp.undo()


@pytest.fixture(scope="module")
def flask_app(monkeypatch_module):
    """Create a Flask app with operations blueprint registered."""
    monkeypatch_module.setenv("OPENALGO_API_KEY", _TEST_API_KEY)
    monkeypatch_module.setenv("FLINTTRADE_DEV", "1")
    from flinttrade_core.app import create_flask_app

    app = create_flask_app()
    app.config["TESTING"] = True
    return app


@pytest.fixture()
def client(flask_app):
    """Flask test client with API key header."""
    with flask_app.test_client() as c:
        yield c


@pytest.fixture(autouse=True)
def isolated_emergency_journal(flask_app):
    """Give each route test a fresh emergency episode/intent namespace."""
    from flinttrade_engine.daily_pnl_state import InMemoryDailyPnLStateStore
    from flinttrade_engine.emergency_intents import InMemoryEmergencyIntentJournal

    original_journal = flask_app.config.get("EMERGENCY_INTENT_JOURNAL")
    original_wrapper = flask_app.config.get("EMERGENCY_INTENT_JOURNAL_WRAPPER")
    original_ready = flask_app.config.get("EMERGENCY_INTENT_JOURNAL_READY")
    original_daily_store = flask_app.config.get("DAILY_PNL_STATE_STORE")
    original_daily_ready = flask_app.config.get("DAILY_PNL_STATE_READY")
    journal = InMemoryEmergencyIntentJournal()
    daily_store = InMemoryDailyPnLStateStore()
    flask_app.config.update(
        EMERGENCY_INTENT_JOURNAL=journal,
        # Null the app-built wrapper so route dispatchers fall back to the
        # per-test journal above; tests that exercise the shared wrapper set
        # their own.
        EMERGENCY_INTENT_JOURNAL_WRAPPER=None,
        EMERGENCY_INTENT_JOURNAL_READY=True,
        DAILY_PNL_STATE_STORE=daily_store,
        DAILY_PNL_STATE_READY=True,
    )
    safety = flask_app.config.get("SAFETY")
    bind = getattr(safety, "bind_emergency_journal", None)
    bind_daily = getattr(safety, "bind_daily_pnl_state_store", None)
    if callable(bind):
        bind(journal)
    if callable(bind_daily):
        bind_daily(daily_store)
    yield
    flask_app.config.update(
        EMERGENCY_INTENT_JOURNAL=original_journal,
        EMERGENCY_INTENT_JOURNAL_WRAPPER=original_wrapper,
        EMERGENCY_INTENT_JOURNAL_READY=original_ready,
        DAILY_PNL_STATE_STORE=original_daily_store,
        DAILY_PNL_STATE_READY=original_daily_ready,
    )
    if callable(bind):
        bind(original_journal)
    if callable(bind_daily) and original_daily_store is not None:
        bind_daily(original_daily_store)


def _auth_headers() -> dict[str, str]:
    return {
        "X-API-Key": _TEST_API_KEY,
        "Content-Type": "application/json",
    }


def _live_headers(*, unlocked: bool = True) -> dict[str, str]:
    from flinttrade_core.auth_routes import _create_token

    headers = _auth_headers()
    token = _create_token("testuser", mode="live", live_mode_unlocked=unlocked)
    headers["Authorization"] = f"Bearer {token}"
    return headers


def _session_headers(mode: str = "explore") -> dict[str, str]:
    """Headers carrying a valid any-mode session JWT.

    Broker-management writes (G9) require the operator's session in any mode —
    explore here proves a live unlock is deliberately NOT required for them.
    """
    from flinttrade_core.auth_routes import _create_token

    headers = _auth_headers()
    headers["Authorization"] = f"Bearer {_create_token('testuser', mode=mode)}"
    return headers


# ---------------------------------------------------------------------------
# Safety config
# ---------------------------------------------------------------------------


class TestSafetyConfigGet:
    """GET /api/v1/safety/config — return safety system configuration."""

    def test_returns_503_when_safety_not_configured(self, flask_app, client):
        """When SAFETY is None, returns 503."""
        original = flask_app.config.get("SAFETY")
        flask_app.config["SAFETY"] = None
        try:
            resp = client.get("/api/v1/safety/config", headers=_auth_headers())
            assert resp.status_code == 503
            data = resp.get_json()
            assert data["status"] == "error"
            assert "SafetySystem" in data["message"]
        finally:
            flask_app.config["SAFETY"] = original

    def test_returns_nested_config(self, flask_app, client):
        """When SAFETY is configured, returns the 5-layer nested config."""
        mock_safety = MagicMock()
        mock_safety.l1_order.price_deviation_pct = 5.0
        mock_safety.l1_order.check_market_hours = True
        mock_safety.l1_order.qty_limits = {"NSE": 1000}
        mock_safety.l2_position.max_positions = 10
        mock_safety.l2_position.max_margin_pct = 80.0
        mock_safety.l3_portfolio.max_net_delta = 50000.0
        mock_safety.l3_portfolio.max_net_vega = 10000.0
        mock_safety.l4_pnl.pause_pct = 2.0
        mock_safety.l4_pnl.kill_pct = 5.0
        mock_safety.l4_pnl.is_paused = False
        mock_safety.l4_pnl.is_killed = False
        mock_safety.l5_kill.is_active = False
        mock_safety.l5_kill.reason = ""

        original = flask_app.config.get("SAFETY")
        flask_app.config["SAFETY"] = mock_safety
        try:
            resp = client.get("/api/v1/safety/config", headers=_auth_headers())
            assert resp.status_code == 200
            data = resp.get_json()
            assert data["status"] == "success"
            assert "l1_order" in data["data"]
            assert "l2_position" in data["data"]
            assert "l3_portfolio" in data["data"]
            assert "l4_pnl" in data["data"]
            assert "l5_kill" in data["data"]
            assert data["data"]["l1_order"]["price_deviation_pct"] == 5.0
            assert data["data"]["l4_pnl"]["is_paused"] is False
        finally:
            flask_app.config["SAFETY"] = original

    def test_reports_incomplete_emergency_result_for_recovery_ui(self, flask_app, client):
        from flinttrade_engine.safety import SafetySystem

        safety = SafetySystem()
        safety.l5_kill.activate("dispatcher unavailable")
        original = flask_app.config.get("SAFETY")
        flask_app.config["SAFETY"] = safety
        try:
            resp = client.get("/api/v1/safety/config", headers=_auth_headers())

            assert resp.status_code == 200
            l5 = resp.get_json()["data"]["l5_kill"]
            assert l5["is_active"] is True
            assert l5["flatten_complete"] is False
            assert l5["emergency_result"]["complete"] is False
            assert l5["emergency_result"]["summary"] == "0/1 targets complete"
        finally:
            safety.l5_kill.reset()
            flask_app.config["SAFETY"] = original


class TestSafetyConfigUpdate:
    """POST /api/v1/safety/config — update safety parameters."""

    def test_updates_single_field(self, flask_app, client):
        from flinttrade_engine.safety import SafetySystem

        safety = SafetySystem()
        original = flask_app.config.get("SAFETY")
        flask_app.config["SAFETY"] = safety
        try:
            resp = client.post(
                "/api/v1/safety/config",
                json={
                    "price_deviation_pct": 10.0,
                },
                headers=_live_headers(),
            )
            assert resp.status_code == 200
            data = resp.get_json()
            assert data["status"] == "success"
            assert safety.l1_order.price_deviation_pct == 10.0
            from flinttrade_core.safety_config import load_workspace_safety_config
            from flinttrade_core.workspace import workspace_dir

            assert load_workspace_safety_config(workspace_dir()).price_deviation_pct == 10.0
        finally:
            flask_app.config["SAFETY"] = original

    def test_invalid_value_returns_400(self, flask_app, client):
        from flinttrade_engine.safety import SafetySystem

        safety = SafetySystem()
        original = flask_app.config.get("SAFETY")
        flask_app.config["SAFETY"] = safety
        try:
            resp = client.post(
                "/api/v1/safety/config",
                json={
                    "price_deviation_pct": "not-a-number",
                },
                headers=_live_headers(),
            )
            assert resp.status_code == 400
            data = resp.get_json()
            assert data["status"] == "error"
        finally:
            flask_app.config["SAFETY"] = original

    def test_persistence_failure_leaves_live_config_unchanged(self, flask_app, client, monkeypatch):
        from flinttrade_engine.safety import SafetySystem
        import flinttrade_core.safety_config as safety_config_module

        safety = SafetySystem()
        original = flask_app.config.get("SAFETY")
        flask_app.config["SAFETY"] = safety
        monkeypatch.setattr(
            safety_config_module,
            "persist_workspace_safety_config",
            MagicMock(side_effect=OSError("disk unavailable")),
        )
        try:
            response = client.post(
                "/api/v1/safety/config",
                json={"price_deviation_pct": 10.0},
                headers=_live_headers(),
            )

            assert response.status_code == 503
            assert safety.l1_order.price_deviation_pct == 5.0
            assert flask_app.config["SAFETY_CONFIG_READY"] is True
        finally:
            flask_app.config["SAFETY"] = original

    @pytest.mark.parametrize("field", ["pnl_pause_pct", "pnl_kill_pct"])
    def test_boolean_daily_loss_threshold_returns_400(self, flask_app, client, field):
        response = client.post(
            "/api/v1/safety/config",
            json={field: True},
            headers=_live_headers(),
        )

        assert response.status_code == 400

    def test_returns_503_when_safety_not_configured(self, flask_app, client):
        original = flask_app.config.get("SAFETY")
        flask_app.config["SAFETY"] = None
        try:
            resp = client.post("/api/v1/safety/config", json={}, headers=_auth_headers())
            assert resp.status_code == 503
        finally:
            flask_app.config["SAFETY"] = original

    def test_update_requires_unlocked_live_session(self, flask_app, client):
        mock_safety = MagicMock()
        mock_safety.l1_order.price_deviation_pct = 5.0
        original = flask_app.config.get("SAFETY")
        flask_app.config["SAFETY"] = mock_safety
        try:
            response = client.post(
                "/api/v1/safety/config",
                json={"price_deviation_pct": 10.0},
                headers=_auth_headers(),
            )

            assert response.status_code == 401
            assert mock_safety.l1_order.price_deviation_pct == 5.0
        finally:
            flask_app.config["SAFETY"] = original

    def test_invalid_mixed_update_does_not_freeze_opening_capital(self, flask_app, client):
        safety = flask_app.config["SAFETY"]
        original_router = flask_app.config.get("BROKER_ROUTER")
        flask_app.config["BROKER_ROUTER"] = TestDailyPnLAccountState._authorised_router()
        try:
            response = client.post(
                "/api/v1/safety/config",
                json={
                    "broker": "openalgo",
                    "account_id": "default",
                    "opening_risk_capital": 100_000,
                    "price_deviation_pct": "not-a-number",
                },
                headers=_live_headers(),
            )

            assert response.status_code == 400
            assert safety.l4_pnl.state("openalgo:default") is None
        finally:
            flask_app.config["BROKER_ROUTER"] = original_router


class TestDailyPnLAccountState:
    """Account-scoped opening capital and Layer 4 reset controls."""

    @staticmethod
    def _authorised_router() -> MagicMock:
        router = MagicMock()
        router.authorised_selectors.return_value = ("openalgo:default",)
        return router

    def test_get_returns_selected_account_capital_and_latch(self, flask_app, client):
        safety = flask_app.config["SAFETY"]
        safety.l4_pnl.configure_opening_capital("openalgo:default", 100_000)
        safety.l4_pnl.validate(
            daily_pnl=-4_000,
            starting_capital=0,
            selector="openalgo:default",
        )

        original_router = flask_app.config.get("BROKER_ROUTER")
        flask_app.config["BROKER_ROUTER"] = self._authorised_router()
        try:
            response = client.get(
                "/api/v1/safety/config?broker=openalgo&account_id=default",
                headers=_live_headers(),
            )
        finally:
            flask_app.config["BROKER_ROUTER"] = original_router

        assert response.status_code == 200
        l4 = response.get_json()["data"]["l4_pnl"]
        assert l4["selector"] == "openalgo:default"
        assert l4["opening_risk_capital"] == 100_000
        assert l4["is_paused"] is True
        assert l4["is_killed"] is False

    def test_openalgo_capital_requires_unlock_and_is_immutable(self, flask_app, client):
        original_router = flask_app.config.get("BROKER_ROUTER")
        flask_app.config["BROKER_ROUTER"] = self._authorised_router()
        try:
            locked = client.post(
                "/api/v1/safety/config",
                json={
                    "broker": "openalgo",
                    "account_id": "default",
                    "opening_risk_capital": 100_000,
                },
                headers=_live_headers(unlocked=False),
            )
            assert locked.status_code == 403

            configured = client.post(
                "/api/v1/safety/config",
                json={
                    "broker": "openalgo",
                    "account_id": "default",
                    "opening_risk_capital": 100_000,
                },
                headers=_live_headers(),
            )
            assert configured.status_code == 200

            diluted = client.post(
                "/api/v1/safety/config",
                json={
                    "broker": "openalgo",
                    "account_id": "default",
                    "opening_risk_capital": 200_000,
                },
                headers=_live_headers(),
            )
            assert diluted.status_code == 409
            state = flask_app.config["SAFETY"].l4_pnl.state("openalgo:default")
            assert state is not None and state.opening_risk_capital == 100_000
        finally:
            flask_app.config["BROKER_ROUTER"] = original_router

    def test_reset_requires_unlock_and_clears_only_selected_latches(self, flask_app, client):
        safety = flask_app.config["SAFETY"]
        safety.l4_pnl.configure_opening_capital("openalgo:default", 100_000)
        safety.l4_pnl.validate(
            daily_pnl=-20_000,
            starting_capital=0,
            selector="openalgo:default",
        )
        original_router = flask_app.config.get("BROKER_ROUTER")
        flask_app.config["BROKER_ROUTER"] = self._authorised_router()
        try:
            refused = client.delete(
                "/api/v1/safety/l4?broker=openalgo&account_id=default",
                headers=_auth_headers(),
            )
            assert refused.status_code == 401
            assert safety.l4_pnl.state("openalgo:default").killed is True

            reset = client.delete(
                "/api/v1/safety/l4?broker=openalgo&account_id=default",
                headers=_live_headers(),
            )
            assert reset.status_code == 200
            state = safety.l4_pnl.state("openalgo:default")
            assert state is not None
            assert state.killed is False and state.paused is False
            assert state.opening_risk_capital == 100_000
        finally:
            flask_app.config["BROKER_ROUTER"] = original_router


# ---------------------------------------------------------------------------
# Emergency kill switch — gated broker writes
# ---------------------------------------------------------------------------


class _EmergencyAdapter:
    """Token-checking adapter used by the kill-switch route integration tests."""

    def __init__(self) -> None:
        self.calls: list[str] = []
        self.completed_by_account: dict[str, set[str]] = {}

    async def plan_emergency_reduction(self, session, *, policy, **_kwargs):
        from flinttrade_engine.safety import (
            EmergencyBrokerWrite,
            EmergencyReductionPlan,
        )

        completed = self.completed_by_account.get(session.account_id, set())
        pending = frozenset(verb for verb in policy.verbs if verb not in completed)
        return EmergencyReductionPlan(
            writes=tuple(
                EmergencyBrokerWrite(
                    parent_verb=verb,
                    verb=verb,
                    payload={"_op": verb},
                )
                for verb in policy.verbs
                if verb in pending
            ),
            pending_verbs=pending,
        )

    @staticmethod
    def _require_router(token: object | None) -> None:
        from flinttrade_core.exceptions import SafetyBypassError
        from flinttrade_gateway.brokers._base import ROUTER_TOKEN

        if token is not ROUTER_TOKEN:
            raise SafetyBypassError("emergency adapter write bypassed BrokerRouter")

    async def cancel_all_orders(self, session, *, _router_token=None):
        self._require_router(_router_token)
        self.calls.append("cancel_all_orders")
        self.completed_by_account.setdefault(session.account_id, set()).add("cancel_all_orders")
        return {"errors": [], "total": 1, "success": 1}

    async def exit_all_positions(self, session, *, _router_token=None):
        self._require_router(_router_token)
        self.calls.append("exit_all_positions")
        self.completed_by_account.setdefault(session.account_id, set()).add("exit_all_positions")
        return {"errors": [], "total": 1, "success": 1}


class TestKillSwitchGatedWrites:
    """POST /safety/kill-switch latches L5 and uses the current BrokerRouter."""

    @staticmethod
    def _live_headers(*, unlocked: bool = False) -> dict[str, str]:
        from flinttrade_core.auth_routes import _create_token

        headers = _auth_headers()
        # Emergency flattening deliberately does not require a PIN re-unlock,
        # but it still requires an authenticated live principal for selector ACL.
        token = _create_token("testuser", mode="live", live_mode_unlocked=unlocked)
        headers["Authorization"] = f"Bearer {token}"
        return headers

    @staticmethod
    def _router(adapter, *, allowed_actor: str = "testuser"):
        from datetime import datetime, timezone

        from flinttrade_core.exceptions import SafetyBypassError
        from flinttrade_engine.safety import SafetyGate
        from flinttrade_gateway.brokers._base import Session
        from flinttrade_gateway.router import BrokerRouter
        from flinttrade_gateway.routing_config import RoutingConfig

        def session_provider(request_ctx, adapter_id, account_id):
            if request_ctx.actor_id != allowed_actor:
                raise SafetyBypassError("selector ACL refused actor")
            return Session(
                access_token="token",
                expires_at=datetime.now(tz=timezone.utc).timestamp() + 3600,
                account_id=account_id,
                adapter_id=adapter_id,
            )

        gate = SafetyGate()
        config = RoutingConfig.from_workspace(
            {
                "registered": ["dhan:acct-1"],
                "account_acls": {"dhan": {"acct-1": [allowed_actor]}},
                "execution": {"default": "dhan:acct-1"},
                "data": {
                    "ticks": "dhan:acct-1",
                    "historical": "dhan:acct-1",
                    "option_chains": "dhan:acct-1",
                    "quote": "dhan:acct-1",
                },
                "failover": {"enabled": False, "order": []},
                "cost_aware": {"enabled": False, "tasks": []},
            }
        )
        return BrokerRouter(
            {"dhan": adapter},
            session_provider,
            consume_gate=gate.consume,
            config=config,
        )

    def test_routes_cancel_and_exit_through_gated_token_adapter(self, flask_app, client):
        from flinttrade_engine.emergency_intents import InMemoryEmergencyIntentJournal
        from flinttrade_engine.safety import SafetySystem

        class CountingJournal(InMemoryEmergencyIntentJournal):
            def __init__(self):
                super().__init__()
                self.reserve_calls = 0

            def reserve(self, **kwargs):
                self.reserve_calls += 1
                return super().reserve(**kwargs)

        adapter = _EmergencyAdapter()
        safety = SafetySystem()
        journal = CountingJournal()
        original = {
            "SAFETY": flask_app.config.get("SAFETY"),
            "BROKER_ROUTER": flask_app.config.get("BROKER_ROUTER"),
            "CLIENT": flask_app.config.get("CLIENT"),
            "EMERGENCY_INTENT_JOURNAL": flask_app.config.get("EMERGENCY_INTENT_JOURNAL"),
        }
        flask_app.config.update(
            SAFETY=safety,
            BROKER_ROUTER=self._router(adapter),
            CLIENT=None,
            EMERGENCY_INTENT_JOURNAL=journal,
        )
        try:
            response = client.post(
                "/api/v1/safety/kill-switch",
                json={"reason": "test emergency"},
                headers=self._live_headers(),
            )

            assert response.status_code == 200
            assert safety.l5_kill.is_active
            assert adapter.calls == ["cancel_all_orders", "exit_all_positions"]
            assert journal.reserve_calls == 2
            assert response.get_json()["data"]["emergency_actions"]["complete"] is True
        finally:
            safety.l5_kill.reset()
            flask_app.config.update(original)

    def test_global_activation_latches_when_an_account_acl_refuses_dispatch(self, flask_app, client):
        from flinttrade_engine.safety import SafetySystem

        adapter = _EmergencyAdapter()
        safety = SafetySystem()
        original_safety = flask_app.config.get("SAFETY")
        original_router = flask_app.config.get("BROKER_ROUTER")
        flask_app.config["SAFETY"] = safety
        flask_app.config["BROKER_ROUTER"] = self._router(adapter, allowed_actor="someone-else")
        try:
            response = client.post(
                "/api/v1/safety/kill-switch",
                json={"reason": "global ACL refusal"},
                headers=self._live_headers(),
            )

            assert response.status_code == 207
            assert safety.l5_kill.is_active is True
            assert adapter.calls == []
            payload = response.get_json()
            assert payload["status"] == "partial"
            assert {
                outcome["failure_code"]
                for outcome in payload["data"]["emergency_actions"]["outcomes"]
            } == {"safety_refused"}
        finally:
            safety.l5_kill.reset()
            flask_app.config["SAFETY"] = original_safety
            flask_app.config["BROKER_ROUTER"] = original_router

    def test_explicit_account_narrowing_is_refused_before_latching_l5(self, flask_app, client):
        from flinttrade_engine.safety import SafetySystem

        adapter = _EmergencyAdapter()
        safety = SafetySystem()
        original = {
            "SAFETY": flask_app.config.get("SAFETY"),
            "BROKER_ROUTER": flask_app.config.get("BROKER_ROUTER"),
        }
        flask_app.config.update(SAFETY=safety, BROKER_ROUTER=self._router(adapter))
        try:
            response = client.post(
                "/api/v1/safety/kill-switch",
                json={"broker": "dhan", "account_id": "typo-account"},
                headers=self._live_headers(),
            )

            assert response.status_code == 400
            assert safety.l5_kill.is_active is False
            assert safety.l5_kill.last_emergency_result is None
            assert adapter.calls == []
        finally:
            flask_app.config.update(original)

    def test_full_scope_activation_holds_generation_lease_through_dispatch(self, flask_app):
        from threading import Event, RLock, Thread

        from flinttrade_engine.safety import SafetySystem

        class BlockingEmergencyAdapter(_EmergencyAdapter):
            def __init__(self):
                super().__init__()
                self.entered = Event()
                self.release = Event()

            async def cancel_all_orders(self, session, *, _router_token=None):
                import asyncio

                self._require_router(_router_token)
                self.calls.append("cancel_all_orders")
                self.completed_by_account.setdefault(session.account_id, set()).add("cancel_all_orders")
                self.entered.set()
                assert await asyncio.to_thread(self.release.wait, 2)
                return {"errors": [], "total": 1, "success": 1}

        adapter = BlockingEmergencyAdapter()
        safety = SafetySystem()
        old_router = self._router(adapter)
        replacement_router = self._router(_EmergencyAdapter())
        rebuild_lock = RLock()
        original = {
            "SAFETY": flask_app.config.get("SAFETY"),
            "BROKER_ROUTER": flask_app.config.get("BROKER_ROUTER"),
            "BROKER_ROUTER_REBUILD_LOCK": flask_app.config.get("BROKER_ROUTER_REBUILD_LOCK"),
        }
        flask_app.config.update(
            SAFETY=safety,
            BROKER_ROUTER=old_router,
            BROKER_ROUTER_REBUILD_LOCK=rebuild_lock,
        )
        response_details = {}
        rebuild_attempted = Event()
        rebuild_finished = Event()

        def activate():
            with flask_app.test_client() as thread_client:
                response = thread_client.post(
                    "/api/v1/safety/kill-switch",
                    json={"reason": "generation race"},
                    headers=self._live_headers(),
                )
                response_details["status_code"] = response.status_code

        def replace_router():
            rebuild_attempted.set()
            with rebuild_lock:
                flask_app.config["BROKER_ROUTER"] = replacement_router
            rebuild_finished.set()

        activation_thread = Thread(target=activate, daemon=True)
        rebuild_thread = Thread(target=replace_router, daemon=True)
        try:
            activation_thread.start()
            assert adapter.entered.wait(timeout=2)
            rebuild_thread.start()
            assert rebuild_attempted.wait(timeout=2)
            assert rebuild_finished.wait(timeout=0.1) is False
            adapter.release.set()
            activation_thread.join(timeout=10)
            rebuild_thread.join(timeout=10)

            assert not activation_thread.is_alive()
            assert not rebuild_thread.is_alive()
            assert response_details["status_code"] == 200
            assert adapter.calls == ["cancel_all_orders", "exit_all_positions"]
            assert flask_app.config["BROKER_ROUTER"] is replacement_router
        finally:
            adapter.release.set()
            activation_thread.join(timeout=10)
            rebuild_thread.join(timeout=10)
            if safety.l5_kill.is_active:
                safety.l5_kill.reset()
            flask_app.config.update(original)

    def test_generation_lease_timeout_latches_l5_and_defers_sweep(self, flask_app, client, monkeypatch):
        """A busy router rebuild must not prevent the L5 LATCH.

        Latch-before-lease: activation latches the kill switch first; only the
        broker sweep needs the generation lease, so a busy rebuild degrades to
        a bounded generation_lease_unavailable outcome (207 partial) with the
        latch held and normal writes refused — never a 503 with no latch.
        """
        from threading import Event, RLock, Thread

        from flinttrade_core import operations_routes
        from flinttrade_engine.safety import SafetySystem

        adapter = _EmergencyAdapter()
        safety = SafetySystem()
        rebuild_lock = RLock()
        lock_held = Event()
        release_lock = Event()

        def hold_lock():
            with rebuild_lock:
                lock_held.set()
                assert release_lock.wait(timeout=2)

        holder = Thread(target=hold_lock, daemon=True)
        original = {
            "SAFETY": flask_app.config.get("SAFETY"),
            "BROKER_ROUTER": flask_app.config.get("BROKER_ROUTER"),
            "BROKER_ROUTER_REBUILD_LOCK": flask_app.config.get("BROKER_ROUTER_REBUILD_LOCK"),
        }
        flask_app.config.update(
            SAFETY=safety,
            BROKER_ROUTER=self._router(adapter),
            BROKER_ROUTER_REBUILD_LOCK=rebuild_lock,
        )
        monkeypatch.setattr(operations_routes, "_ROUTER_GENERATION_LEASE_TIMEOUT_SECONDS", 0.01, raising=False)
        holder.start()
        assert lock_held.wait(timeout=2)
        try:
            response = client.post(
                "/api/v1/safety/kill-switch",
                json={"reason": "lease timeout"},
                headers=self._live_headers(),
            )

            assert response.status_code == 207
            payload = response.get_json()
            assert payload["status"] == "partial"
            assert safety.l5_kill.is_active is True
            result = safety.l5_kill.last_emergency_result
            assert result is not None and not result.complete
            assert "generation_lease_unavailable" in str(payload["data"]["emergency_actions"])
            assert adapter.calls == []
        finally:
            release_lock.set()
            holder.join(timeout=10)
            flask_app.config.update(original)

    def test_missing_target_fails_closed_and_never_uses_raw_client(self, flask_app, client):
        from flinttrade_engine.safety import SafetySystem

        safety = SafetySystem()
        raw_client = MagicMock()
        original = {
            "SAFETY": flask_app.config.get("SAFETY"),
            "BROKER_ROUTER": flask_app.config.get("BROKER_ROUTER"),
            "CLIENT": flask_app.config.get("CLIENT"),
        }
        flask_app.config.update(SAFETY=safety, BROKER_ROUTER=None, CLIENT=raw_client)
        try:
            response = client.post(
                "/api/v1/safety/kill-switch",
                json={"reason": "router unavailable"},
                headers=self._live_headers(),
            )

            assert response.status_code == 207
            assert safety.l5_kill.is_active
            assert response.get_json()["status"] == "partial"
            raw_client.cancel_all_orders.assert_not_called()
            raw_client.close_position.assert_not_called()
        finally:
            safety.l5_kill.reset()
            flask_app.config.update(original)

    def test_omitted_target_sweeps_all_actor_authorised_registered_accounts(self, flask_app, client):
        from datetime import datetime, timezone

        from flinttrade_engine.safety import SafetyGate, SafetySystem
        from flinttrade_gateway.brokers._base import Session
        from flinttrade_gateway.router import BrokerRouter
        from flinttrade_gateway.routing_config import RoutingConfig

        dhan = _EmergencyAdapter()
        upstox = _EmergencyAdapter()
        config = RoutingConfig.from_workspace(
            {
                "registered": ["dhan:primary", "upstox:secondary"],
                "account_acls": {
                    "dhan": {"primary": ["testuser"]},
                    "upstox": {"secondary": ["testuser"]},
                },
                "execution": {"default": "dhan:primary"},
                "data": {
                    "ticks": "dhan:primary",
                    "historical": "dhan:primary",
                    "option_chains": "dhan:primary",
                    "quote": "dhan:primary",
                },
                "failover": {"enabled": False, "order": []},
                "cost_aware": {"enabled": False, "tasks": []},
            }
        )

        def session_provider(request_ctx, adapter_id, account_id):
            assert request_ctx.actor_id == "testuser"
            return Session(
                access_token="token",
                expires_at=datetime.now(tz=timezone.utc).timestamp() + 3600,
                account_id=account_id,
                adapter_id=adapter_id,
            )

        router = BrokerRouter(
            {"dhan": dhan, "upstox": upstox},
            session_provider,
            consume_gate=SafetyGate().consume,
            config=config,
        )
        safety = SafetySystem()
        original = {
            "SAFETY": flask_app.config.get("SAFETY"),
            "BROKER_ROUTER": flask_app.config.get("BROKER_ROUTER"),
            "CLIENT": flask_app.config.get("CLIENT"),
        }
        flask_app.config.update(SAFETY=safety, BROKER_ROUTER=router, CLIENT=None)
        try:
            response = client.post(
                "/api/v1/safety/kill-switch",
                json={"reason": "all configured accounts"},
                headers=self._live_headers(),
            )

            assert response.status_code == 200
            assert dhan.calls == ["cancel_all_orders", "exit_all_positions"]
            assert upstox.calls == ["cancel_all_orders", "exit_all_positions"]
            actions = response.get_json()["data"]["emergency_actions"]
            assert actions["target_count"] == 2
            assert actions["completed_target_count"] == 2
        finally:
            safety.l5_kill.reset()
            flask_app.config.update(original)

    def test_global_l5_keeps_configured_account_without_active_adapter_in_incomplete_scope(
        self,
        flask_app,
        client,
    ):
        from datetime import datetime, timezone

        from flinttrade_engine.safety import SafetyGate, SafetySystem
        from flinttrade_gateway.brokers._base import Session
        from flinttrade_gateway.router import BrokerRouter
        from flinttrade_gateway.routing_config import RoutingConfig

        dhan = _EmergencyAdapter()
        config = RoutingConfig.from_workspace(
            {
                "registered": ["dhan:primary", "upstox:dormant"],
                "account_acls": {
                    "dhan": {"primary": ["testuser"]},
                    "upstox": {"dormant": ["testuser"]},
                },
                "execution": {"default": "dhan:primary"},
                "data": {
                    "ticks": "dhan:primary",
                    "historical": "dhan:primary",
                    "option_chains": "dhan:primary",
                    "quote": "dhan:primary",
                },
                "failover": {"enabled": False, "order": []},
                "cost_aware": {"enabled": False, "tasks": []},
            }
        )

        def session_provider(request_ctx, adapter_id, account_id):
            assert request_ctx.actor_id == "testuser"
            return Session(
                access_token="token",
                expires_at=datetime.now(tz=timezone.utc).timestamp() + 3600,
                account_id=account_id,
                adapter_id=adapter_id,
            )

        router = BrokerRouter(
            {"dhan": dhan},
            session_provider,
            consume_gate=SafetyGate().consume,
            config=config,
        )
        safety = SafetySystem()
        original = {
            "SAFETY": flask_app.config.get("SAFETY"),
            "BROKER_ROUTER": flask_app.config.get("BROKER_ROUTER"),
        }
        flask_app.config.update(SAFETY=safety, BROKER_ROUTER=router)
        try:
            activation = client.post(
                "/api/v1/safety/kill-switch",
                json={"reason": "configured dormant account"},
                headers=self._live_headers(),
            )

            assert activation.status_code == 207
            actions = activation.get_json()["data"]["emergency_actions"]
            assert actions["target_count"] == 2
            assert actions["completed_target_count"] == 1
            assert {target["selector"] for target in actions["targets"]} == {
                "dhan:primary",
                "upstox:dormant",
            }
            assert dhan.calls == ["cancel_all_orders", "exit_all_positions"]

            reset = client.delete(
                "/api/v1/safety/kill-switch",
                headers=self._live_headers(unlocked=True),
            )
            assert reset.status_code == 409
            assert safety.l5_kill.is_active is True
        finally:
            safety.l5_kill.reset()
            flask_app.config.update(original)

    def test_global_l5_cannot_reset_after_only_the_authorised_account_flattens(
        self,
        flask_app,
        client,
    ):
        from datetime import datetime, timezone

        from flinttrade_core.exceptions import SafetyBypassError
        from flinttrade_engine.safety import SafetyGate, SafetySystem
        from flinttrade_gateway.brokers._base import Session
        from flinttrade_gateway.router import BrokerRouter
        from flinttrade_gateway.routing_config import RoutingConfig

        dhan = _EmergencyAdapter()
        upstox = _EmergencyAdapter()
        config = RoutingConfig.from_workspace(
            {
                "registered": ["dhan:primary", "upstox:secondary"],
                "account_acls": {"dhan": {"primary": ["testuser"]}},
                "execution": {"default": "dhan:primary"},
                "data": {
                    "ticks": "dhan:primary",
                    "historical": "dhan:primary",
                    "option_chains": "dhan:primary",
                    "quote": "dhan:primary",
                },
                "failover": {"enabled": False, "order": []},
                "cost_aware": {"enabled": False, "tasks": []},
            }
        )

        def session_provider(request_ctx, adapter_id, account_id):
            if f"{adapter_id}:{account_id}" != "dhan:primary":
                raise SafetyBypassError("selector ACL refused actor")
            return Session(
                access_token="token",
                expires_at=datetime.now(tz=timezone.utc).timestamp() + 3600,
                account_id=account_id,
                adapter_id=adapter_id,
            )

        router = BrokerRouter(
            {"dhan": dhan, "upstox": upstox},
            session_provider,
            consume_gate=SafetyGate().consume,
            config=config,
        )
        safety = SafetySystem()
        original = {
            "SAFETY": flask_app.config.get("SAFETY"),
            "BROKER_ROUTER": flask_app.config.get("BROKER_ROUTER"),
        }
        flask_app.config.update(SAFETY=safety, BROKER_ROUTER=router)
        try:
            activation = client.post(
                "/api/v1/safety/kill-switch",
                json={"reason": "global partial flatten"},
                headers=self._live_headers(),
            )

            assert activation.status_code == 207
            assert safety.l5_kill.is_active
            assert dhan.calls == ["cancel_all_orders", "exit_all_positions"]
            assert upstox.calls == []
            actions = activation.get_json()["data"]["emergency_actions"]
            assert actions["target_count"] == 2
            assert actions["completed_target_count"] == 1

            reset = client.delete(
                "/api/v1/safety/kill-switch",
                json={
                    "confirm_incomplete": True,
                    "confirmation": "RESET WITH OPEN EXPOSURE",
                },
                headers=self._live_headers(unlocked=True),
            )

            assert reset.status_code == 403
            assert safety.l5_kill.is_active
        finally:
            safety.l5_kill.reset()
            flask_app.config.update(original)

    def test_activation_remains_truthful_when_audit_write_fails(self, flask_app, client):
        from flinttrade_engine.safety import SafetySystem

        adapter = _EmergencyAdapter()
        safety = SafetySystem()
        failing_audit = MagicMock()
        failing_audit.log_kill_switch.side_effect = OSError("audit storage unavailable")
        original = {
            "SAFETY": flask_app.config.get("SAFETY"),
            "BROKER_ROUTER": flask_app.config.get("BROKER_ROUTER"),
            "AUDIT": flask_app.config.get("AUDIT"),
        }
        flask_app.config.update(
            SAFETY=safety,
            BROKER_ROUTER=self._router(adapter),
            AUDIT=failing_audit,
        )
        try:
            response = client.post(
                "/api/v1/safety/kill-switch",
                json={"reason": "audit failure"},
                headers=self._live_headers(),
            )

            assert response.status_code == 200
            assert response.get_json()["data"]["audit_recorded"] is False
            assert safety.l5_kill.is_active is True
        finally:
            safety.l5_kill.reset()
            flask_app.config.update(original)

    def test_reset_requires_live_operator_jwt_and_keeps_latch(self, flask_app, client):
        from flinttrade_engine.safety import SafetySystem

        safety = SafetySystem()
        safety.l5_kill.activate("authentication test")
        original = flask_app.config.get("SAFETY")
        flask_app.config["SAFETY"] = safety
        try:
            response = client.delete(
                "/api/v1/safety/kill-switch",
                headers=_auth_headers(),
            )

            assert response.status_code == 401
            assert safety.l5_kill.is_active is True
        finally:
            safety.l5_kill.reset()
            flask_app.config["SAFETY"] = original

    def test_reset_refuses_incomplete_flatten_without_explicit_override(self, flask_app, client):
        from flinttrade_engine.safety import SafetySystem

        safety = SafetySystem()
        safety.l5_kill.activate("incomplete flatten")
        original = flask_app.config.get("SAFETY")
        flask_app.config["SAFETY"] = safety
        try:
            response = client.delete(
                "/api/v1/safety/kill-switch",
                headers=self._live_headers(unlocked=True),
            )

            assert response.status_code == 409
            assert response.get_json()["data"]["emergency_actions"]["complete"] is False
            assert safety.l5_kill.is_active is True
        finally:
            safety.l5_kill.reset()
            flask_app.config["SAFETY"] = original

    def test_reset_requires_pin_unlocked_live_session(self, flask_app, client):
        from flinttrade_engine.safety import SafetySystem

        safety = SafetySystem()
        safety.l5_kill.activate("locked reset")
        original = flask_app.config.get("SAFETY")
        flask_app.config["SAFETY"] = safety
        try:
            response = client.delete(
                "/api/v1/safety/kill-switch",
                headers=self._live_headers(unlocked=False),
            )

            assert response.status_code == 403
            assert safety.l5_kill.is_active is True
        finally:
            safety.l5_kill.reset()
            flask_app.config["SAFETY"] = original

    def test_reset_requires_acl_for_every_known_emergency_selector(self, flask_app, client):
        from flinttrade_engine.safety import (
            EmergencyDispatchResult,
            EmergencyVerbOutcome,
            SafetySystem,
        )

        class CompleteDispatcher:
            def dispatch(self, policy, *, reason):
                return EmergencyDispatchResult(
                    policy=policy,
                    outcomes=tuple(
                        EmergencyVerbOutcome(
                            verb,
                            succeeded=True,
                            selector="dhan:acct-1",
                        )
                        for verb in policy.verbs
                    ),
                )

        safety = SafetySystem()
        safety.l5_kill.activate("known account", emergency_dispatcher=CompleteDispatcher())
        router = MagicMock()
        router.authorised_selectors.return_value = ()
        original = {
            "SAFETY": flask_app.config.get("SAFETY"),
            "BROKER_ROUTER": flask_app.config.get("BROKER_ROUTER"),
        }
        flask_app.config.update(SAFETY=safety, BROKER_ROUTER=router)
        try:
            response = client.delete(
                "/api/v1/safety/kill-switch",
                headers=self._live_headers(unlocked=True),
            )

            assert response.status_code == 403
            assert safety.l5_kill.is_active is True
        finally:
            safety.l5_kill.reset()
            flask_app.config.update(original)

    def test_reset_waits_for_emergency_work_before_acquiring_router_generation(self, flask_app):
        from threading import Event, RLock, Thread
        from types import SimpleNamespace

        from flinttrade_engine.safety import KillSwitchResetAuthorisationError

        entered_wait = Event()
        release_wait = Event()

        class WaitingKillSwitch:
            is_active = True
            last_emergency_result = SimpleNamespace(complete=True)

            def wait_for_idle(self):
                entered_wait.set()
                assert release_wait.wait(timeout=2)

            def reset(self, *, require_complete, timeout, authorise_selectors):
                assert require_complete is True
                assert timeout == 0
                if not authorise_selectors(frozenset({"dhan:acct-1"})):
                    raise KillSwitchResetAuthorisationError("replacement router refused selector")
                self.is_active = False

        class RouterAcl:
            def __init__(self, selectors):
                self.selectors = selectors
                self.actor_ids = []

            def authorised_selectors(self, actor_id):
                self.actor_ids.append(actor_id)
                return self.selectors

        old_router = RouterAcl(("dhan:acct-1",))
        replacement_router = RouterAcl(())
        safety = SimpleNamespace(l5_kill=WaitingKillSwitch())
        rebuild_lock = RLock()
        original = {
            "SAFETY": flask_app.config.get("SAFETY"),
            "BROKER_ROUTER": flask_app.config.get("BROKER_ROUTER"),
            "BROKER_ROUTER_REBUILD_LOCK": flask_app.config.get("BROKER_ROUTER_REBUILD_LOCK"),
        }
        flask_app.config.update(
            SAFETY=safety,
            BROKER_ROUTER=old_router,
            BROKER_ROUTER_REBUILD_LOCK=rebuild_lock,
        )
        response_details = {}
        rebuild_attempted = Event()
        rebuild_finished = Event()

        def request_reset():
            with flask_app.test_client() as thread_client:
                response = thread_client.delete(
                    "/api/v1/safety/kill-switch",
                    headers=self._live_headers(unlocked=True),
                )
                response_details["status_code"] = response.status_code
                response_details["payload"] = response.get_json()

        def replace_router():
            rebuild_attempted.set()
            with rebuild_lock:
                flask_app.config["BROKER_ROUTER"] = replacement_router
            rebuild_finished.set()

        reset_thread = Thread(target=request_reset, daemon=True)
        rebuild_thread = Thread(target=replace_router, daemon=True)
        try:
            reset_thread.start()
            assert entered_wait.wait(timeout=2)
            rebuild_thread.start()
            assert rebuild_attempted.wait(timeout=2)
            rebuild_completed_during_wait = rebuild_finished.wait(timeout=0.5)
            release_wait.set()
            reset_thread.join(timeout=10)
            rebuild_thread.join(timeout=10)

            assert rebuild_completed_during_wait is True
            assert not reset_thread.is_alive()
            assert not rebuild_thread.is_alive()
            assert response_details["status_code"] == 403
            assert safety.l5_kill.is_active is True
            assert old_router.actor_ids == []
            assert replacement_router.actor_ids == ["testuser"]
        finally:
            release_wait.set()
            reset_thread.join(timeout=10)
            rebuild_thread.join(timeout=10)
            flask_app.config.update(original)

    def test_reset_holds_router_generation_lease_through_l5_transition(self, flask_app):
        from threading import Event, RLock, Thread
        from types import SimpleNamespace

        from flinttrade_engine.safety import KillSwitchResetAuthorisationError

        acl_entered = Event()
        allow_acl_return = Event()
        l5_transitioned = Event()
        rebuild_attempted = Event()
        rebuild_finished = Event()

        class TransitioningKillSwitch:
            is_active = True
            last_emergency_result = SimpleNamespace(complete=True)

            def wait_for_idle(self):
                return None

            def reset(self, *, require_complete, timeout, authorise_selectors):
                assert require_complete is True
                assert timeout == 0
                if not authorise_selectors(frozenset({"dhan:acct-1"})):
                    raise KillSwitchResetAuthorisationError("selector refused")
                self.is_active = False
                l5_transitioned.set()

        class BlockingAclRouter:
            retired = False

            def authorised_selectors(self, actor_id):
                assert actor_id == "testuser"
                acl_entered.set()
                assert allow_acl_return.wait(timeout=2)
                return ("dhan:acct-1",)

        old_router = BlockingAclRouter()
        replacement_router = object()
        safety = SimpleNamespace(l5_kill=TransitioningKillSwitch())
        rebuild_lock = RLock()
        original = {
            "SAFETY": flask_app.config.get("SAFETY"),
            "AUDIT": flask_app.config.get("AUDIT"),
            "BROKER_ROUTER": flask_app.config.get("BROKER_ROUTER"),
            "BROKER_ROUTER_REBUILD_LOCK": flask_app.config.get("BROKER_ROUTER_REBUILD_LOCK"),
        }
        flask_app.config.update(
            SAFETY=safety,
            AUDIT=None,
            BROKER_ROUTER=old_router,
            BROKER_ROUTER_REBUILD_LOCK=rebuild_lock,
        )
        response_details = {}
        retired_before_transition = []

        def request_reset():
            with flask_app.test_client() as thread_client:
                response = thread_client.delete(
                    "/api/v1/safety/kill-switch",
                    headers=self._live_headers(unlocked=True),
                )
                response_details["status_code"] = response.status_code

        def rebuild_router():
            rebuild_attempted.set()
            with rebuild_lock:
                retired_before_transition.append(not l5_transitioned.is_set())
                old_router.retired = True
                flask_app.config["BROKER_ROUTER"] = replacement_router
            rebuild_finished.set()

        reset_thread = Thread(target=request_reset, daemon=True)
        rebuild_thread = Thread(target=rebuild_router, daemon=True)
        try:
            reset_thread.start()
            assert acl_entered.wait(timeout=2)
            rebuild_thread.start()
            assert rebuild_attempted.wait(timeout=2)
            rebuild_completed_during_acl = rebuild_finished.wait(timeout=0.1)
            allow_acl_return.set()
            reset_thread.join(timeout=10)
            rebuild_thread.join(timeout=10)

            assert rebuild_completed_during_acl is False
            assert not reset_thread.is_alive()
            assert not rebuild_thread.is_alive()
            assert response_details["status_code"] == 200
            assert l5_transitioned.is_set()
            assert retired_before_transition == [False]
            assert flask_app.config["BROKER_ROUTER"] is replacement_router
        finally:
            allow_acl_return.set()
            reset_thread.join(timeout=10)
            rebuild_thread.join(timeout=10)
            flask_app.config.update(original)

    def test_reset_does_not_starve_an_activation_waiting_for_the_generation_lease(self, flask_app):
        from contextlib import contextmanager
        from threading import Event, RLock, Thread

        from flinttrade_engine.safety import (
            EmergencyDispatchResult,
            EmergencyVerbOutcome,
            SafetySystem,
            bounded_generation_lease,
        )

        lease_requested = Event()
        allow_lease_attempt = Event()
        rebuild_lock = RLock()

        class LeasedDispatcher:
            @contextmanager
            def generation_lease(self):
                lease_requested.set()
                assert allow_lease_attempt.wait(timeout=2)
                with bounded_generation_lease(rebuild_lock, timeout_seconds=0.1):
                    yield

            def dispatch(self, policy, *, reason):
                del reason
                return EmergencyDispatchResult(
                    policy=policy,
                    outcomes=tuple(
                        EmergencyVerbOutcome(verb, succeeded=True, selector="dhan:acct-1")
                        for verb in policy.verbs
                    ),
                )

        class RouterAcl:
            def authorised_selectors(self, actor_id):
                assert actor_id == "testuser"
                return ("dhan:acct-1",)

        safety = SafetySystem()
        original = {
            "SAFETY": flask_app.config.get("SAFETY"),
            "AUDIT": flask_app.config.get("AUDIT"),
            "BROKER_ROUTER": flask_app.config.get("BROKER_ROUTER"),
            "BROKER_ROUTER_REBUILD_LOCK": flask_app.config.get("BROKER_ROUTER_REBUILD_LOCK"),
        }
        flask_app.config.update(
            SAFETY=safety,
            AUDIT=None,
            BROKER_ROUTER=RouterAcl(),
            BROKER_ROUTER_REBUILD_LOCK=rebuild_lock,
        )
        activation: dict[str, object] = {}
        reset: dict[str, object] = {}

        activation_thread = Thread(
            target=lambda: activation.setdefault(
                "result",
                safety.l5_kill.activate("lease race", emergency_dispatcher=LeasedDispatcher()),
            ),
            daemon=True,
        )

        def request_reset():
            with flask_app.test_client() as thread_client:
                response = thread_client.delete(
                    "/api/v1/safety/kill-switch",
                    json={
                        "confirm_incomplete": True,
                        "confirmation": "RESET WITH OPEN EXPOSURE",
                    },
                    headers=self._live_headers(unlocked=True),
                )
                reset["status_code"] = response.status_code

        reset_thread = Thread(target=request_reset, daemon=True)
        try:
            activation_thread.start()
            assert lease_requested.wait(timeout=2)
            reset_thread.start()
            # Give the reset request time to reach its idle wait. It must not
            # own the same generation lock needed by this admitted activation.
            reset_thread.join(timeout=0.05)
            assert reset_thread.is_alive()
            allow_lease_attempt.set()
            activation_thread.join(timeout=10)
            reset_thread.join(timeout=10)

            assert not activation_thread.is_alive()
            assert not reset_thread.is_alive()
            assert activation["result"].complete is True
            assert reset["status_code"] == 200
            assert safety.l5_kill.is_active is False
        finally:
            allow_lease_attempt.set()
            activation_thread.join(timeout=10)
            reset_thread.join(timeout=10)
            if safety.l5_kill.is_active:
                safety.l5_kill.reset()
            flask_app.config.update(original)

    def test_reset_reports_actual_state_when_audit_write_fails(self, flask_app, client):
        from flinttrade_engine.safety import (
            EmergencyDispatchResult,
            EmergencyVerbOutcome,
            L5_EMERGENCY_POLICY,
            SafetySystem,
        )

        class CompleteDispatcher:
            def dispatch(self, policy, *, reason):
                return EmergencyDispatchResult(
                    policy=policy,
                    outcomes=tuple(EmergencyVerbOutcome(verb, succeeded=True) for verb in L5_EMERGENCY_POLICY.verbs),
                )

        safety = SafetySystem()
        safety.l5_kill.activate("completed flatten", emergency_dispatcher=CompleteDispatcher())
        failing_audit = MagicMock()
        failing_audit.log_kill_switch.side_effect = OSError("audit storage unavailable")
        original = {
            "SAFETY": flask_app.config.get("SAFETY"),
            "AUDIT": flask_app.config.get("AUDIT"),
        }
        flask_app.config.update(SAFETY=safety, AUDIT=failing_audit)
        try:
            response = client.delete(
                "/api/v1/safety/kill-switch",
                headers=self._live_headers(unlocked=True),
            )

            payload = response.get_json()
            assert response.status_code == 200
            assert payload["message"] == "Kill switch reset — trading may resume"
            assert payload["data"]["audit_recorded"] is False
            assert safety.l5_kill.is_active is False
        finally:
            safety.l5_kill.reset()
            flask_app.config.update(original)


# ---------------------------------------------------------------------------
# Security settings
# ---------------------------------------------------------------------------


class TestSecuritySettingsGet:
    """GET /api/v1/security/settings — return security monitor config."""

    def test_returns_settings(self, flask_app, client):
        """SecurityMonitor is auto-created by create_flask_app."""
        resp = client.get("/api/v1/security/settings", headers=_auth_headers())
        assert resp.status_code == 200
        data = resp.get_json()
        assert data["status"] == "success"
        assert "auto_ban_enabled" in data["data"]
        assert "ban_threshold" in data["data"]
        assert "notfound_ban_threshold" in data["data"]
        assert "ban_duration" in data["data"]

    def test_returns_503_when_monitor_not_configured(self, flask_app, client):
        original = flask_app.config.get("SECURITY_MONITOR")
        flask_app.config["SECURITY_MONITOR"] = None
        try:
            resp = client.get("/api/v1/security/settings", headers=_auth_headers())
            assert resp.status_code == 503
        finally:
            flask_app.config["SECURITY_MONITOR"] = original


class TestSecuritySettingsUpdate:
    """POST /api/v1/security/settings — update security monitor config."""

    def test_update_threshold(self, flask_app, client):
        resp = client.post(
            "/api/v1/security/settings",
            json={
                "notfound_ban_threshold": 50,
            },
            headers=_auth_headers(),
        )
        assert resp.status_code == 200
        data = resp.get_json()
        assert data["status"] == "success"
        assert data["data"]["notfound_ban_threshold"] == 50

    def test_invalid_value_returns_400(self, flask_app, client):
        resp = client.post(
            "/api/v1/security/settings",
            json={
                "notfound_ban_threshold": "not-a-number",
            },
            headers=_auth_headers(),
        )
        assert resp.status_code == 400
        data = resp.get_json()
        assert data["status"] == "error"


# ---------------------------------------------------------------------------
# Frontend error reporting
# ---------------------------------------------------------------------------


class TestFrontendErrors:
    """POST /api/v1/errors — receive error reports from the React frontend."""

    def test_receives_error_report(self, client):
        """Error endpoint is public (no API key needed) and always returns 200."""
        resp = client.post(
            "/api/v1/errors",
            json={
                "message": "Uncaught TypeError: Cannot read properties of null",
                "url": "http://localhost:5173/trade",
                "stack": "TypeError: Cannot read properties...",
                "userAgent": "Mozilla/5.0",
            },
            headers={"Content-Type": "application/json"},
        )
        assert resp.status_code == 200
        data = resp.get_json()
        assert data["status"] == "success"

    def test_empty_error_body_returns_200(self, client):
        """Even an empty body should not crash."""
        resp = client.post("/api/v1/errors", json={}, headers={"Content-Type": "application/json"})
        assert resp.status_code == 200
        data = resp.get_json()
        assert data["status"] == "success"


# ---------------------------------------------------------------------------
# Trade journal — shared store wiring + frontend contract
# ---------------------------------------------------------------------------


class TestTradesJournal:
    """GET /api/v1/trades/journal — reads the shared trade store.

    The order dispatch writes to ``TRADE_STORAGE`` and this route reads the same
    store, so a row inserted there must surface here — keyed as ``timestamp``
    (the terminal's JournalTrade contract), not the DuckDB ``ts`` column.
    """

    @staticmethod
    def _temp_store(flask_app, tmp_path):
        """Swap an isolated temp-file store into the app (restored by caller).

        The DEV fixture wires TRADE_STORAGE at the real default DuckDB path;
        writing test rows there would pollute a real file and accumulate across
        runs, so each write-test gets its own throwaway store.
        """
        from flinttrade_data.storage import StorageManager

        store = StorageManager(db_path=str(tmp_path / "journal.duckdb"))
        store.initialise()
        flask_app.config["TRADE_STORAGE"] = store
        return store

    def test_shared_store_is_wired_in_dev(self, flask_app):
        assert flask_app.config.get("TRADE_STORAGE") is not None
        assert flask_app.config.get("TRADE_STORAGE_LOCK") is not None

    def test_returns_inserted_trade_with_timestamp_key(self, flask_app, client, tmp_path):
        from datetime import datetime, timedelta, timezone

        ist = timezone(timedelta(hours=5, minutes=30))
        orig = flask_app.config.get("TRADE_STORAGE")
        store = self._temp_store(flask_app, tmp_path)
        try:
            store.insert_trade(
                ts=datetime.now(ist),
                orderid="JNL-1",
                symbol="RELIANCE",
                exchange="NSE",
                action="BUY",
                quantity=5,
                price=2500.0,
                product="MIS",
                strategy="manual",
            )

            resp = client.get("/api/v1/trades/journal", headers=_auth_headers())
            assert resp.status_code == 200
            data = resp.get_json()
            assert data["status"] == "success"
            rows = data["data"]["trades"]
            mine = [r for r in rows if r.get("orderid") == "JNL-1"]
            assert len(mine) == 1
            row = mine[0]
            # Frontend contract: `timestamp`, not the DuckDB `ts` column.
            assert "timestamp" in row
            assert "ts" not in row
            assert row["symbol"] == "RELIANCE"
            assert row["action"] == "BUY"
        finally:
            flask_app.config["TRADE_STORAGE"] = orig
            store.close()

    def test_date_range_without_strategy_uses_range_query(self, flask_app, client, tmp_path):
        """start+end with no strategy must hit the range query, not single-day.

        Previously a start+end (no strategy) fell through to a single-day lookup —
        the recurring contract bug the performance dashboard would have tripped.
        """
        from datetime import datetime, timedelta, timezone

        ist = timezone(timedelta(hours=5, minutes=30))
        orig = flask_app.config.get("TRADE_STORAGE")
        store = self._temp_store(flask_app, tmp_path)
        try:
            base = datetime.now(ist)
            store.insert_trade(
                ts=base - timedelta(days=20),
                orderid="RNG-OLD",
                symbol="TCS",
                exchange="NSE",
                action="BUY",
                quantity=1,
                price=100.0,
                strategy="manual",
            )
            store.insert_trade(
                ts=base,
                orderid="RNG-NEW",
                symbol="TCS",
                exchange="NSE",
                action="SELL",
                quantity=1,
                price=110.0,
                strategy="manual",
            )

            start = (base - timedelta(days=30)).strftime("%Y-%m-%d")
            end = base.strftime("%Y-%m-%d")
            resp = client.get(
                f"/api/v1/trades/journal?start_date={start}&end_date={end}",
                headers=_auth_headers(),
            )
            assert resp.status_code == 200
            ids = {r.get("orderid") for r in resp.get_json()["data"]["trades"]}
            # The 20-day-old trade is only reachable via the range query.
            assert "RNG-OLD" in ids
            assert "RNG-NEW" in ids
        finally:
            flask_app.config["TRADE_STORAGE"] = orig
            store.close()


# ---------------------------------------------------------------------------
# Recent logs
# ---------------------------------------------------------------------------


class TestRecentLogs:
    """GET /api/v1/logs/recent — return recent structured log entries."""

    def test_returns_200(self, client):
        resp = client.get("/api/v1/logs/recent", headers=_auth_headers())
        assert resp.status_code == 200
        data = resp.get_json()
        assert data["status"] == "success"
        assert isinstance(data["data"], list)

    def test_with_custom_n(self, client):
        resp = client.get("/api/v1/logs/recent?n=10", headers=_auth_headers())
        assert resp.status_code == 200
        data = resp.get_json()
        assert data["status"] == "success"

    def test_invalid_n_returns_400(self, client):
        resp = client.get("/api/v1/logs/recent?n=abc", headers=_auth_headers())
        assert resp.status_code == 400
        data = resp.get_json()
        assert data["status"] == "error"
        assert "positive integer" in data["message"]

    def test_negative_n_returns_400(self, client):
        resp = client.get("/api/v1/logs/recent?n=-5", headers=_auth_headers())
        assert resp.status_code == 400


# ---------------------------------------------------------------------------
# Ditto — multi-account endpoints
# ---------------------------------------------------------------------------


class _FakeDittoRuntime:
    def __init__(self) -> None:
        self.start_calls: list[dict[str, object]] = []
        self.stop_calls: list[float] = []
        self.kill_calls: list[dict[str, str]] = []
        self._status = {
            "active": False,
            "lifecycle": "idle",
            "source_account": None,
            "target_accounts": [],
            "mode": "equal",
            "mirrored_positions": 0,
            "last_sync": None,
            "errors": [],
        }

    def status(self) -> dict[str, object]:
        return dict(self._status)

    def start(self, **kwargs: object) -> dict[str, object]:
        self.start_calls.append(kwargs)
        self._status.update(
            active=True,
            lifecycle="active",
            source_account=kwargs["source_account"],
            target_accounts=kwargs["target_accounts"],
            mode="weighted",
        )
        return self.status()

    def stop(self, *, timeout: float = 5.0) -> dict[str, object]:
        self.stop_calls.append(timeout)
        self._status.update(
            active=False,
            lifecycle="idle",
            source_account=None,
            target_accounts=[],
        )
        return self.status()

    def risk_snapshot(self) -> dict[str, object]:
        return {
            "complete": True,
            "aggregate_pnl": 125.0,
            "aggregate_capital": 10000.0,
            "accounts": [],
        }

    def kill_all(self, **kwargs: str) -> dict[str, object]:
        self.kill_calls.append(kwargs)
        return {
            "complete": False,
            "message": "One or more managed accounts could not be fully flattened",
            "accounts_affected": 2,
            "emergency_actions": {"complete": False},
        }


class TestDittoMirrorStatus:
    """GET /api/v1/ditto/mirror/status — position mirroring status."""

    def test_returns_runtime_status(self, flask_app, client):
        runtime = _FakeDittoRuntime()
        original = flask_app.config.get("DITTO_RUNTIME")
        flask_app.config["DITTO_RUNTIME"] = runtime
        try:
            resp = client.get("/api/v1/ditto/mirror/status", headers=_auth_headers())
            assert resp.status_code == 200
            data = resp.get_json()
            assert data["status"] == "success"
            assert data["data"] == runtime.status()
        finally:
            flask_app.config["DITTO_RUNTIME"] = original

    def test_returns_503_when_runtime_is_unavailable(self, flask_app, client):
        original = flask_app.config.get("DITTO_RUNTIME")
        flask_app.config["DITTO_RUNTIME"] = None
        try:
            resp = client.get("/api/v1/ditto/mirror/status", headers=_auth_headers())
            assert resp.status_code == 503
            assert resp.get_json()["message"] == "Ditto runtime unavailable"
        finally:
            flask_app.config["DITTO_RUNTIME"] = original


class TestDittoAccountCrud:
    """Ditto account CRUD endpoints."""

    class _FakeAccount:
        def __init__(
            self,
            account_id: str,
            name: str = "Demo",
            openalgo_host: str = "http://127.0.0.1:5001",
            api_key: str = "secret",
            enabled: bool = True,
            group: str = "default",
            allocation_weight: float = 1.0,
            max_loss_daily: float = 50000.0,
            is_master: bool = False,
        ) -> None:
            self.account_id = account_id
            self.name = name
            self.openalgo_host = openalgo_host
            self.api_key = api_key
            self.enabled = enabled
            self.group = group
            self.allocation_weight = allocation_weight
            self.max_loss_daily = max_loss_daily
            self.is_master = is_master

    class _FakeManager:
        accounts: dict[str, "TestDittoAccountCrud._FakeAccount"] = {}

        def __init__(self, *args, **kwargs) -> None:
            pass

        def list_accounts(self):
            return list(self.accounts.values())

        def add_account(self, account) -> None:
            self.accounts[account.account_id] = account

        def get_account(self, account_id: str):
            return self.accounts.get(account_id)

        def enable_account(self, account_id: str) -> None:
            self.accounts[account_id].enabled = True

        def disable_account(self, account_id: str) -> None:
            self.accounts[account_id].enabled = False

        def remove_account(self, account_id: str) -> None:
            self.accounts.pop(account_id, None)

    def _patch_manager(self, monkeypatch, accounts=None):
        import flinttrade_ditto.account_manager as account_manager

        self._FakeManager.accounts = {account.account_id: account for account in (accounts or [])}
        monkeypatch.setattr(account_manager, "AccountManager", self._FakeManager)

    def test_list_accounts_returns_configured_accounts(self, client, monkeypatch):
        self._patch_manager(monkeypatch, [self._FakeAccount("acc_1", name="Primary", enabled=True)])

        resp = client.get("/api/v1/ditto/accounts", headers=_session_headers())

        assert resp.status_code == 200
        data = resp.get_json()
        assert data["status"] == "success"
        assert data["data"]["accounts"] == [
            {
                "id": "acc_1",
                "name": "Primary",
                "broker": "OpenAlgo",
                "capital": None,
                "pnl_today": None,
                "status": "active",
                "positions": None,
                "group": "default",
                "allocation_weight": 1.0,
                "max_loss_daily": 50000.0,
                "is_master": False,
            }
        ]
        assert "api_key" not in data["data"]["accounts"][0]

    def test_list_accounts_returns_empty_list_when_none_configured(self, client, monkeypatch):
        self._patch_manager(monkeypatch)

        resp = client.get("/api/v1/ditto/accounts", headers=_session_headers())

        assert resp.status_code == 200
        data = resp.get_json()
        assert data["status"] == "success"
        assert data["data"]["accounts"] == []

    def test_list_accounts_returns_503_when_manager_unavailable(self, client, monkeypatch):
        class _BoomManager:
            def __init__(self, *args, **kwargs) -> None:
                raise RuntimeError("database unavailable")

        monkeypatch.setattr("flinttrade_ditto.account_manager.AccountManager", _BoomManager)

        resp = client.get("/api/v1/ditto/accounts", headers=_session_headers())

        assert resp.status_code == 503
        data = resp.get_json()
        assert data["status"] == "error"
        assert data["message"] == "Account service unavailable"

    def test_create_account_returns_sanitised_account(self, client, monkeypatch):
        self._patch_manager(monkeypatch)
        resp = client.post(
            "/api/v1/ditto/accounts",
            json={
                "account_id": "family_01",
                "name": "Family Account",
                "openalgo_host": "http://127.0.0.1:5001",
                "api_key": "secret-key",
                "group": "Family",
                "allocation_weight": 1.25,
                "max_loss_daily": 25000,
                "enabled": True,
                "is_master": False,
            },
            headers=_session_headers(),
        )

        assert resp.status_code == 201
        data = resp.get_json()
        assert data["status"] == "success"
        assert data["data"]["account"]["id"] == "family_01"
        assert data["data"]["account"]["name"] == "Family Account"
        assert "api_key" not in data["data"]["account"]

    def test_create_account_validates_required_fields(self, client, monkeypatch):
        self._patch_manager(monkeypatch)
        resp = client.post(
            "/api/v1/ditto/accounts",
            json={
                "account_id": "missing_host",
                "api_key": "secret-key",
            },
            headers=_session_headers(),
        )
        assert resp.status_code == 400

    @pytest.mark.parametrize(
        ("field", "value"),
        [
            ("allocation_weight", "nan"),
            ("allocation_weight", "inf"),
            ("max_loss_daily", "nan"),
            ("max_loss_daily", "inf"),
        ],
    )
    def test_create_account_rejects_non_finite_risk_configuration(
        self, client, monkeypatch, field, value
    ):
        self._patch_manager(monkeypatch)
        payload = {
            "account_id": "family_01",
            "openalgo_host": "http://127.0.0.1:5001",
            "api_key": "secret-key",
            field: value,
        }

        response = client.post(
            "/api/v1/ditto/accounts",
            json=payload,
            headers=_session_headers(),
        )

        assert response.status_code == 400

    def test_updating_active_target_stops_runtime_before_replacing_store_row(
        self, flask_app, client, monkeypatch
    ):
        events: list[str] = []
        existing = self._FakeAccount("acc_2", name="Old name")
        manager = self._FakeManager()
        manager.accounts = {existing.account_id: existing}

        def add_account(account) -> None:
            events.append("manager.add")
            manager.accounts[account.account_id] = account

        manager.add_account = add_account
        monkeypatch.setattr(
            "flinttrade_ditto.account_manager.AccountManager",
            lambda **_kwargs: manager,
        )

        class _Runtime:
            state = {
                "active": True,
                "lifecycle": "active",
                "source_account": "acc_1",
                "target_accounts": ["acc_2"],
            }

            def status(self):
                events.append("runtime.status")
                return dict(self.state)

            def stop(self, *, timeout: float):
                events.append("runtime.stop")
                assert timeout == 5.0
                self.state.update(
                    active=False,
                    lifecycle="idle",
                    source_account=None,
                    target_accounts=[],
                )
                return dict(self.state)

        original_runtime = flask_app.config.get("DITTO_RUNTIME")
        flask_app.config["DITTO_RUNTIME"] = _Runtime()
        try:
            response = client.post(
                "/api/v1/ditto/accounts",
                json={
                    "account_id": "acc_2",
                    "name": "New name",
                    "openalgo_host": "http://127.0.0.1:5002",
                    "api_key": "replacement-key",
                },
                headers=_session_headers(),
            )
        finally:
            flask_app.config["DITTO_RUNTIME"] = original_runtime

        assert response.status_code == 201
        assert manager.accounts["acc_2"].name == "New name"
        assert events == [
            "runtime.status",
            "runtime.stop",
            "runtime.status",
            "manager.add",
        ]

    def test_updating_active_account_fails_closed_when_runtime_cannot_drain(
        self, flask_app, client, monkeypatch
    ):
        existing = self._FakeAccount("acc_2", name="Old name")
        manager = self._FakeManager()
        manager.accounts = {existing.account_id: existing}
        manager.add_account = MagicMock()
        monkeypatch.setattr(
            "flinttrade_ditto.account_manager.AccountManager",
            lambda **_kwargs: manager,
        )
        runtime = _FakeDittoRuntime()
        runtime._status.update(
            active=True,
            lifecycle="active",
            source_account="acc_1",
            target_accounts=["acc_2"],
        )
        runtime.stop = MagicMock(side_effect=RuntimeError("private broker response"))
        original_runtime = flask_app.config.get("DITTO_RUNTIME")
        flask_app.config["DITTO_RUNTIME"] = runtime
        try:
            response = client.post(
                "/api/v1/ditto/accounts",
                json={
                    "account_id": "acc_2",
                    "name": "New name",
                    "openalgo_host": "http://127.0.0.1:5002",
                    "api_key": "replacement-key",
                },
                headers=_session_headers(),
            )
        finally:
            flask_app.config["DITTO_RUNTIME"] = original_runtime

        assert response.status_code == 503
        assert manager.accounts["acc_2"] is existing
        manager.add_account.assert_not_called()

    def test_enable_disable_and_delete_account(self, client, monkeypatch):
        account = self._FakeAccount("acc_1", name="Primary", enabled=True)
        self._patch_manager(monkeypatch, [account])

        disable_resp = client.post("/api/v1/ditto/accounts/acc_1/disable", headers=_session_headers())
        assert disable_resp.status_code == 200
        assert disable_resp.get_json()["data"]["account"]["status"] == "disabled"

        enable_resp = client.post("/api/v1/ditto/accounts/acc_1/enable", headers=_session_headers())
        assert enable_resp.status_code == 200
        assert enable_resp.get_json()["data"]["account"]["status"] == "active"

        delete_resp = client.delete("/api/v1/ditto/accounts/acc_1", headers=_session_headers())
        assert delete_resp.status_code == 200
        assert delete_resp.get_json()["data"]["removed"] is True

    def test_disabling_active_source_stops_runtime_before_mutating_store(
        self, flask_app, client, monkeypatch
    ):
        events: list[str] = []
        account = self._FakeAccount("acc_1", enabled=True)
        manager = self._FakeManager()
        manager.accounts = {account.account_id: account}

        def disable_account(account_id: str) -> None:
            events.append("manager.disable")
            manager.accounts[account_id].enabled = False

        manager.disable_account = disable_account
        monkeypatch.setattr(
            "flinttrade_ditto.account_manager.AccountManager",
            lambda **_kwargs: manager,
        )

        class _Runtime:
            state = {
                "active": True,
                "lifecycle": "active",
                "source_account": "acc_1",
                "target_accounts": ["acc_2"],
            }

            def status(self):
                events.append("runtime.status")
                return dict(self.state)

            def stop(self, *, timeout: float):
                events.append("runtime.stop")
                assert timeout == 5.0
                self.state.update(
                    active=False,
                    lifecycle="idle",
                    source_account=None,
                    target_accounts=[],
                )
                return dict(self.state)

        original_runtime = flask_app.config.get("DITTO_RUNTIME")
        flask_app.config["DITTO_RUNTIME"] = _Runtime()
        try:
            response = client.post(
                "/api/v1/ditto/accounts/acc_1/disable",
                headers=_session_headers(),
            )
        finally:
            flask_app.config["DITTO_RUNTIME"] = original_runtime

        assert response.status_code == 200
        assert account.enabled is False
        assert events == [
            "runtime.status",
            "runtime.stop",
            "runtime.status",
            "manager.disable",
        ]

    def test_deleting_active_target_stops_runtime_before_mutating_store(
        self, flask_app, client, monkeypatch
    ):
        events: list[str] = []
        account = self._FakeAccount("acc_2", enabled=True)
        manager = self._FakeManager()
        manager.accounts = {account.account_id: account}

        def remove_account(account_id: str) -> None:
            events.append("manager.remove")
            manager.accounts.pop(account_id)

        manager.remove_account = remove_account
        monkeypatch.setattr(
            "flinttrade_ditto.account_manager.AccountManager",
            lambda **_kwargs: manager,
        )

        class _Runtime:
            state = {
                "active": True,
                "lifecycle": "active",
                "source_account": "acc_1",
                "target_accounts": ["acc_2"],
            }

            def status(self):
                events.append("runtime.status")
                return dict(self.state)

            def stop(self, *, timeout: float):
                events.append("runtime.stop")
                assert timeout == 5.0
                self.state.update(
                    active=False,
                    lifecycle="idle",
                    source_account=None,
                    target_accounts=[],
                )
                return dict(self.state)

        original_runtime = flask_app.config.get("DITTO_RUNTIME")
        flask_app.config["DITTO_RUNTIME"] = _Runtime()
        try:
            response = client.delete(
                "/api/v1/ditto/accounts/acc_2",
                headers=_session_headers(),
            )
        finally:
            flask_app.config["DITTO_RUNTIME"] = original_runtime

        assert response.status_code == 200
        assert "acc_2" not in manager.accounts
        assert events == [
            "runtime.status",
            "runtime.stop",
            "runtime.status",
            "manager.remove",
        ]

    @pytest.mark.parametrize("stop_mode", ["raises", "retained"])
    def test_participating_account_mutation_fails_closed_without_drain_proof(
        self, flask_app, client, monkeypatch, caplog, stop_mode
    ):
        secret = "http://private-host.invalid/path?api_key=credential-value"
        account = self._FakeAccount("acc_1", enabled=True)
        manager = self._FakeManager()
        manager.accounts = {account.account_id: account}
        manager.disable_account = MagicMock()
        monkeypatch.setattr(
            "flinttrade_ditto.account_manager.AccountManager",
            lambda **_kwargs: manager,
        )

        class _Runtime:
            state = {
                "active": True,
                "lifecycle": "active",
                "source_account": "acc_1",
                "target_accounts": ["acc_2"],
            }

            def status(self):
                return dict(self.state)

            def stop(self, *, timeout: float):
                assert timeout == 5.0
                if stop_mode == "raises":
                    raise RuntimeError(secret)
                self.state.update(active=False, lifecycle="retained-shutdown")
                return dict(self.state)

        original_runtime = flask_app.config.get("DITTO_RUNTIME")
        flask_app.config["DITTO_RUNTIME"] = _Runtime()
        try:
            with caplog.at_level("WARNING", logger="flinttrade"):
                response = client.post(
                    "/api/v1/ditto/accounts/acc_1/disable",
                    headers=_session_headers(),
                )
        finally:
            flask_app.config["DITTO_RUNTIME"] = original_runtime

        assert response.status_code == 503
        assert account.enabled is True
        manager.disable_account.assert_not_called()
        assert secret not in response.get_data(as_text=True)
        assert secret not in caplog.text
        assert "credential-value" not in caplog.text

    def test_participating_account_delete_fails_closed_when_drain_fails(
        self, flask_app, client, monkeypatch
    ):
        account = self._FakeAccount("acc_2", enabled=True)
        manager = self._FakeManager()
        manager.accounts = {account.account_id: account}
        manager.remove_account = MagicMock()
        monkeypatch.setattr(
            "flinttrade_ditto.account_manager.AccountManager",
            lambda **_kwargs: manager,
        )
        runtime = _FakeDittoRuntime()
        runtime._status.update(
            active=True,
            lifecycle="active",
            source_account="acc_1",
            target_accounts=["acc_2"],
        )
        runtime.stop = MagicMock(side_effect=RuntimeError("private broker response"))
        original_runtime = flask_app.config.get("DITTO_RUNTIME")
        flask_app.config["DITTO_RUNTIME"] = runtime
        try:
            response = client.delete(
                "/api/v1/ditto/accounts/acc_2",
                headers=_session_headers(),
            )
        finally:
            flask_app.config["DITTO_RUNTIME"] = original_runtime

        assert response.status_code == 503
        assert manager.accounts == {"acc_2": account}
        manager.remove_account.assert_not_called()

    def test_non_participating_account_mutation_does_not_stop_runtime(
        self, flask_app, client, monkeypatch
    ):
        account = self._FakeAccount("acc_3", enabled=True)
        manager = self._FakeManager()
        manager.accounts = {account.account_id: account}
        monkeypatch.setattr(
            "flinttrade_ditto.account_manager.AccountManager",
            lambda **_kwargs: manager,
        )
        runtime = _FakeDittoRuntime()
        runtime._status.update(
            active=True,
            lifecycle="active",
            source_account="acc_1",
            target_accounts=["acc_2"],
        )
        original_runtime = flask_app.config.get("DITTO_RUNTIME")
        flask_app.config["DITTO_RUNTIME"] = runtime
        try:
            response = client.post(
                "/api/v1/ditto/accounts/acc_3/disable",
                headers=_session_headers(),
            )
        finally:
            flask_app.config["DITTO_RUNTIME"] = original_runtime

        assert response.status_code == 200
        assert account.enabled is False
        assert runtime.stop_calls == []

    @pytest.mark.parametrize(
        ("cleanup_succeeds", "expected_status"),
        [(True, 200), (False, 503)],
    )
    def test_retained_one_shot_owner_is_global_account_mutation_barrier(
        self,
        flask_app,
        client,
        monkeypatch,
        cleanup_succeeds,
        expected_status,
    ):
        from flinttrade_ditto.account_manager import BrokerAccount
        from flinttrade_ditto.runtime import DittoCapabilityUnavailable, DittoRuntime

        account = self._FakeAccount("acc_3", enabled=True)
        manager = self._FakeManager()
        manager.accounts = {account.account_id: account}
        manager.disable_account = MagicMock()
        monkeypatch.setattr(
            "flinttrade_ditto.account_manager.AccountManager",
            lambda **_kwargs: manager,
        )

        managed_account = BrokerAccount(
            account_id="acc_3",
            openalgo_host="http://127.0.0.1:5103",
            api_key="retained-owner-key",
            enabled=True,
        )

        class _RetainedOwner:
            def __init__(self) -> None:
                self.close_calls = 0

            def risk_state(self, _account):
                return {
                    "available_balance": 100_000.0,
                    "used_margin": 0.0,
                    "total_balance": 100_000.0,
                    "pnl_today": 0.0,
                    "positions": 0,
                }

            def close(self, *, timeout: float) -> bool:
                assert timeout >= 0
                self.close_calls += 1
                if self.close_calls == 1:
                    return False
                return cleanup_succeeds

        retained_owner = _RetainedOwner()
        runtime = DittoRuntime(
            account_provider=lambda: [managed_account],
            router_owner_factory=lambda _accounts, _actor_id: retained_owner,
        )
        with pytest.raises(DittoCapabilityUnavailable, match="snapshot cleanup"):
            runtime.risk_snapshot()
        assert runtime.status() == {
            "active": False,
            "lifecycle": "retained-shutdown",
            "source_account": None,
            "target_accounts": [],
            "mode": "equal",
            "mirrored_positions": 0,
            "last_sync": None,
            "errors": [],
        }

        original_runtime = flask_app.config.get("DITTO_RUNTIME")
        flask_app.config["DITTO_RUNTIME"] = runtime
        try:
            response = client.post(
                "/api/v1/ditto/accounts/acc_3/disable",
                headers=_session_headers(),
            )
        finally:
            flask_app.config["DITTO_RUNTIME"] = original_runtime

        assert response.status_code == expected_status
        assert retained_owner.close_calls == 2
        if cleanup_succeeds:
            manager.disable_account.assert_called_once_with("acc_3")
            assert account.enabled is False
            assert runtime.status()["lifecycle"] == "idle"
        else:
            manager.disable_account.assert_not_called()
            assert account.enabled is True
            assert runtime.status()["lifecycle"] == "retained-shutdown"

    def test_account_drain_and_new_start_are_serialised(
        self, flask_app, monkeypatch
    ):
        from threading import Event, Thread

        account = self._FakeAccount("acc_1", enabled=True)
        manager = self._FakeManager()
        manager.accounts = {account.account_id: account}
        monkeypatch.setattr(
            "flinttrade_ditto.account_manager.AccountManager",
            lambda **_kwargs: manager,
        )
        stop_entered = Event()
        release_stop = Event()
        start_entered = Event()

        class _Runtime(_FakeDittoRuntime):
            def __init__(self):
                super().__init__()
                self._status.update(
                    active=True,
                    lifecycle="active",
                    source_account="acc_1",
                    target_accounts=["acc_2"],
                )

            def stop(self, *, timeout: float = 5.0):
                stop_entered.set()
                assert release_stop.wait(timeout=2.0)
                return super().stop(timeout=timeout)

            def start(self, **kwargs: object):
                start_entered.set()
                return super().start(**kwargs)

        runtime = _Runtime()
        original_runtime = flask_app.config.get("DITTO_RUNTIME")
        flask_app.config["DITTO_RUNTIME"] = runtime
        responses: dict[str, int] = {}

        def disable_request() -> None:
            with flask_app.test_client() as thread_client:
                responses["disable"] = thread_client.post(
                    "/api/v1/ditto/accounts/acc_1/disable",
                    headers=_session_headers(),
                ).status_code

        def start_request() -> None:
            with flask_app.test_client() as thread_client:
                responses["start"] = thread_client.post(
                    "/api/v1/ditto/mirror/start",
                    json={"source_account": "acc_3", "target_accounts": ["acc_4"]},
                    headers=_live_headers(),
                ).status_code

        disable_thread = Thread(target=disable_request)
        start_thread = Thread(target=start_request)
        try:
            disable_thread.start()
            assert stop_entered.wait(timeout=2.0)
            start_thread.start()
            assert not start_entered.wait(timeout=0.1)
            release_stop.set()
            disable_thread.join(timeout=2.0)
            start_thread.join(timeout=2.0)
        finally:
            release_stop.set()
            disable_thread.join(timeout=2.0)
            if start_thread.ident is not None:
                start_thread.join(timeout=2.0)
            flask_app.config["DITTO_RUNTIME"] = original_runtime

        assert not disable_thread.is_alive()
        assert not start_thread.is_alive()
        assert responses == {"disable": 200, "start": 200}
        assert start_entered.is_set()

    def test_account_operation_exception_logs_only_exception_class(
        self, client, monkeypatch, caplog
    ):
        secret = "acct-secret http://private-host.invalid/vault/path"

        class _FailingManager(self._FakeManager):
            def add_account(self, account) -> None:
                raise RuntimeError(secret)

        monkeypatch.setattr(
            "flinttrade_ditto.account_manager.AccountManager",
            lambda **_kwargs: _FailingManager(),
        )
        with caplog.at_level("WARNING", logger="flinttrade"):
            response = client.post(
                "/api/v1/ditto/accounts",
                json={
                    "account_id": "family_01",
                    "openalgo_host": "http://127.0.0.1:5001",
                    "api_key": "secret-key",
                },
                headers=_session_headers(),
            )

        assert response.status_code == 503
        assert secret not in response.get_data(as_text=True)
        assert secret not in caplog.text
        assert "RuntimeError" in caplog.text


class TestDittoMirrorStart:
    """POST /api/v1/ditto/mirror/start — start position mirroring."""

    def test_missing_source_returns_400(self, client):
        resp = client.post(
            "/api/v1/ditto/mirror/start",
            json={
                "target_accounts": ["acc_2"],
            },
            headers=_auth_headers(),
        )
        assert resp.status_code == 400

    def test_missing_targets_returns_400(self, client):
        resp = client.post(
            "/api/v1/ditto/mirror/start",
            json={
                "source_account": "acc_1",
                "target_accounts": [],
            },
            headers=_auth_headers(),
        )
        assert resp.status_code == 400

    def test_valid_start_requires_live_operator_jwt(self, flask_app, client):
        runtime = _FakeDittoRuntime()
        original = flask_app.config.get("DITTO_RUNTIME")
        flask_app.config["DITTO_RUNTIME"] = runtime
        try:
            resp = client.post(
                "/api/v1/ditto/mirror/start",
                json={
                    "source_account": "acc_1",
                    "target_accounts": ["acc_2"],
                    "mode": "proportional",
                },
                headers=_auth_headers(),
            )
            assert resp.status_code == 401
            assert runtime.start_calls == []
        finally:
            flask_app.config["DITTO_RUNTIME"] = original

    def test_valid_start_requires_live_pin_unlock(self, flask_app, client):
        runtime = _FakeDittoRuntime()
        original = flask_app.config.get("DITTO_RUNTIME")
        flask_app.config["DITTO_RUNTIME"] = runtime
        try:
            response = client.post(
                "/api/v1/ditto/mirror/start",
                json={
                    "source_account": "acc_1",
                    "target_accounts": ["acc_2"],
                    "mode": "weighted",
                },
                headers=_live_headers(unlocked=False),
            )
        finally:
            flask_app.config["DITTO_RUNTIME"] = original

        assert response.status_code == 403
        assert runtime.start_calls == []

    def test_valid_start_delegates_to_runtime(self, flask_app, client):
        runtime = _FakeDittoRuntime()
        original = flask_app.config.get("DITTO_RUNTIME")
        flask_app.config["DITTO_RUNTIME"] = runtime
        try:
            resp = client.post(
                "/api/v1/ditto/mirror/start",
                json={
                    "source_account": "acc_1",
                    "target_accounts": ["acc_2", "acc_3"],
                    "mode": "proportional",
                },
                headers=_live_headers(),
            )
            assert resp.status_code == 200
            data = resp.get_json()
            assert data["status"] == "success"
            assert data["data"]["active"] is True
            assert runtime.start_calls[0]["source_account"] == "acc_1"
            assert runtime.start_calls[0]["target_accounts"] == ["acc_2", "acc_3"]
            assert runtime.start_calls[0]["mode"] == "proportional"
            assert runtime.start_calls[0]["actor_id"] == "testuser"
            assert runtime.start_calls[0]["jti"]
        finally:
            flask_app.config["DITTO_RUNTIME"] = original

    def test_runtime_failure_is_sanitised(self, flask_app, client):
        runtime = _FakeDittoRuntime()
        runtime.start = MagicMock(side_effect=RuntimeError("broker secret response"))
        original = flask_app.config.get("DITTO_RUNTIME")
        flask_app.config["DITTO_RUNTIME"] = runtime
        try:
            resp = client.post(
                "/api/v1/ditto/mirror/start",
                json={"source_account": "acc_1", "target_accounts": ["acc_2"]},
                headers=_live_headers(),
            )
            assert resp.status_code == 503
            assert resp.get_json()["message"] == "Ditto runtime operation unavailable"
            assert "secret" not in resp.get_data(as_text=True)
        finally:
            flask_app.config["DITTO_RUNTIME"] = original


class TestDittoRuntimeActions:
    def test_stop_delegates_to_runtime(self, flask_app, client):
        runtime = _FakeDittoRuntime()
        runtime._status["active"] = True
        original = flask_app.config.get("DITTO_RUNTIME")
        flask_app.config["DITTO_RUNTIME"] = runtime
        try:
            resp = client.post("/api/v1/ditto/mirror/stop", headers=_session_headers())
            assert resp.status_code == 200
            assert resp.get_json()["data"]["active"] is False
            assert runtime.stop_calls == [5.0]
        finally:
            flask_app.config["DITTO_RUNTIME"] = original

    def test_risk_uses_real_runtime_snapshot(self, flask_app, client):
        runtime = _FakeDittoRuntime()
        original = flask_app.config.get("DITTO_RUNTIME")
        flask_app.config["DITTO_RUNTIME"] = runtime
        try:
            resp = client.get("/api/v1/ditto/risk", headers=_session_headers())
            assert resp.status_code == 200
            assert resp.get_json()["data"]["aggregate_pnl"] == 125.0
            assert resp.get_json()["data"]["complete"] is True
        finally:
            flask_app.config["DITTO_RUNTIME"] = original

    def test_kill_all_requires_live_operator_and_reports_partial_result(self, flask_app, client):
        runtime = _FakeDittoRuntime()
        original = flask_app.config.get("DITTO_RUNTIME")
        flask_app.config["DITTO_RUNTIME"] = runtime
        try:
            unauthenticated = client.post(
                "/api/v1/ditto/kill-all",
                json={"reason": "operator requested flatten"},
                headers=_auth_headers(),
            )
            assert unauthenticated.status_code == 401
            assert runtime.kill_calls == []

            response = client.post(
                "/api/v1/ditto/kill-all",
                json={"reason": "operator requested flatten"},
                headers=_live_headers(unlocked=False),
            )
            assert response.status_code == 207
            assert response.get_json()["status"] == "partial"
            assert response.get_json()["data"]["complete"] is False
            assert runtime.kill_calls[0]["actor_id"] == "testuser"
            assert runtime.kill_calls[0]["jti"]
        finally:
            flask_app.config["DITTO_RUNTIME"] = original


class TestDittoWriteAuthG9:
    """G9 pin: every Ditto broker-management write requires a session JWT.

    These routes mutate the Ditto vault, account registry, or mirror runtime;
    an API key alone (no Authorization header) must be refused with 401 and
    must never reach the account manager or runtime.
    """

    @pytest.mark.parametrize(
        ("method", "path"),
        [
            ("post", "/api/v1/ditto/accounts"),
            ("post", "/api/v1/ditto/accounts/acc_1/enable"),
            ("post", "/api/v1/ditto/accounts/acc_1/disable"),
            ("delete", "/api/v1/ditto/accounts/acc_1"),
            ("post", "/api/v1/ditto/mirror/stop"),
        ],
    )
    def test_write_without_session_jwt_is_401(self, client, method, path):
        response = getattr(client, method)(path, headers=_auth_headers())
        assert response.status_code == 401
        assert response.get_json()["status"] == "error"

    def test_write_with_any_mode_session_passes_auth(self, client):
        """An explore-mode session clears the G9 gate (later checks may still 4xx/5xx)."""
        response = client.post("/api/v1/ditto/mirror/stop", headers=_session_headers())
        assert response.status_code != 401


class TestAccountsStatus:
    """GET /api/v1/accounts/status — Account Manager per-broker reauth summary."""

    class _FakeStatus:
        def __init__(self, connected: bool, authenticated: bool, needs_reauth: bool):
            self._d = {
                "connected": connected,
                "authenticated": authenticated,
                "needs_reauth": needs_reauth,
            }

        def to_dict(self) -> dict:
            return self._d

    class _FakeAM:
        def __init__(self, statuses):
            self._statuses = statuses

        def __enter__(self):
            return self

        def __exit__(self, *_a):
            return False

        def account_status_all(self):
            return self._statuses

    class _NativeStore:
        def __init__(self, rows):
            self._rows = rows

        def list_accounts(self):
            return self._rows

    class _NativeRegistry:
        def __init__(self, sessions=None):
            self._sessions = sessions or {}

        def get_session_for(self, adapter_id, account_id):
            key = (adapter_id, account_id)
            if key not in self._sessions:
                raise KeyError(key)
            return self._sessions[key]

    def test_returns_summary_and_per_account_status(self, client, monkeypatch):
        statuses = [
            self._FakeStatus(connected=True, authenticated=True, needs_reauth=False),
            self._FakeStatus(connected=True, authenticated=False, needs_reauth=True),
            self._FakeStatus(connected=False, authenticated=False, needs_reauth=False),
        ]
        monkeypatch.setattr(
            "flinttrade_ditto.account_manager.AccountManager",
            lambda **_kw: self._FakeAM(statuses),
        )

        resp = client.get("/api/v1/accounts/status", headers=_auth_headers())
        assert resp.status_code == 200
        data = resp.get_json()
        assert data["status"] == "success"
        assert len(data["data"]["accounts"]) == 3
        assert data["data"]["summary"] == {
            "total": 3,
            "connected": 2,
            "authenticated": 1,
            "needs_reauth": 1,
        }

    def test_merges_native_account_status(self, flask_app, client, monkeypatch):
        monkeypatch.setattr(
            "flinttrade_ditto.account_manager.AccountManager",
            lambda **_kw: self._FakeAM([]),
        )
        session = type("Session", (), {"expires_at": 4_102_444_800.0})()
        original_store = flask_app.config.get("CREDENTIAL_STORE")
        original_registry = flask_app.config.get("REGISTRY")
        original_login_status = flask_app.config.get("NATIVE_SESSION_STATUS")
        flask_app.config["CREDENTIAL_STORE"] = self._NativeStore(
            [
                {
                    "adapter_id": "upstox",
                    "account_id": "UPX-LIVE",
                    "label": "Upstox main",
                    "is_primary": True,
                }
            ]
        )
        flask_app.config["REGISTRY"] = self._NativeRegistry({("upstox", "UPX-LIVE"): session})
        flask_app.config["NATIVE_SESSION_STATUS"] = {}
        try:
            resp = client.get("/api/v1/accounts/status", headers=_auth_headers())
        finally:
            flask_app.config["CREDENTIAL_STORE"] = original_store
            flask_app.config["REGISTRY"] = original_registry
            flask_app.config["NATIVE_SESSION_STATUS"] = original_login_status

        assert resp.status_code == 200
        data = resp.get_json()["data"]
        assert data["summary"] == {
            "total": 1,
            "connected": 1,
            "authenticated": 1,
            "needs_reauth": 0,
        }
        row = data["accounts"][0]
        assert row["source"] == "native"
        assert row["broker"] == "upstox"
        assert row["broker_display"] == "Upstox"
        assert row["name"] == "Upstox main"
        assert row["connected"] is True
        assert row["authenticated"] is True
        assert row["expires_at"] == 4_102_444_800.0

    def test_returns_native_status_when_ditto_unavailable(self, flask_app, client, monkeypatch):
        def _boom():
            raise RuntimeError("credential vault locked")

        monkeypatch.setattr("flinttrade_ditto.account_manager.AccountManager", _boom)
        original_store = flask_app.config.get("CREDENTIAL_STORE")
        original_registry = flask_app.config.get("REGISTRY")
        original_login_status = flask_app.config.get("NATIVE_SESSION_STATUS")
        flask_app.config["CREDENTIAL_STORE"] = self._NativeStore(
            [
                {
                    "adapter_id": "dhan",
                    "account_id": "DHAN-LIVE",
                    "label": "Dhan main",
                }
            ]
        )
        flask_app.config["REGISTRY"] = self._NativeRegistry()
        flask_app.config["NATIVE_SESSION_STATUS"] = {"dhan:DHAN-LIVE": "login-failed: token expired"}
        try:
            resp = client.get("/api/v1/accounts/status", headers=_auth_headers())
        finally:
            flask_app.config["CREDENTIAL_STORE"] = original_store
            flask_app.config["REGISTRY"] = original_registry
            flask_app.config["NATIVE_SESSION_STATUS"] = original_login_status

        assert resp.status_code == 200
        data = resp.get_json()["data"]
        assert data["summary"] == {
            "total": 1,
            "connected": 0,
            "authenticated": 0,
            "needs_reauth": 1,
        }
        row = data["accounts"][0]
        assert row["source"] == "native"
        assert row["broker"] == "dhan"
        assert row["needs_reauth"] is True
        assert row["login_retryable"] is False
        assert row["error"] == "login-failed: token expired"

    def test_native_retryable_login_status_is_not_reauth(self, flask_app, client, monkeypatch):
        from flinttrade_gateway.native_login import BROKER_LOGIN_RETRY_MESSAGE

        def _boom():
            raise RuntimeError("credential vault locked")

        monkeypatch.setattr("flinttrade_ditto.account_manager.AccountManager", _boom)
        original_store = flask_app.config.get("CREDENTIAL_STORE")
        original_registry = flask_app.config.get("REGISTRY")
        original_login_status = flask_app.config.get("NATIVE_SESSION_STATUS")
        flask_app.config["CREDENTIAL_STORE"] = self._NativeStore(
            [
                {
                    "adapter_id": "upstox",
                    "account_id": "UPX-RETRY",
                    "label": "Upstox retry",
                }
            ]
        )
        flask_app.config["REGISTRY"] = self._NativeRegistry()
        flask_app.config["NATIVE_SESSION_STATUS"] = {"upstox:UPX-RETRY": BROKER_LOGIN_RETRY_MESSAGE}
        try:
            resp = client.get("/api/v1/accounts/status", headers=_auth_headers())
        finally:
            flask_app.config["CREDENTIAL_STORE"] = original_store
            flask_app.config["REGISTRY"] = original_registry
            flask_app.config["NATIVE_SESSION_STATUS"] = original_login_status

        assert resp.status_code == 200
        data = resp.get_json()["data"]
        assert data["summary"] == {
            "total": 1,
            "connected": 0,
            "authenticated": 0,
            "needs_reauth": 0,
        }
        row = data["accounts"][0]
        assert row["source"] == "native"
        assert row["broker"] == "upstox"
        assert row["needs_reauth"] is False
        assert row["login_retryable"] is True
        assert row["error"] == BROKER_LOGIN_RETRY_MESSAGE

    def test_returns_503_when_account_manager_unavailable(self, client, monkeypatch):
        def _boom():
            raise RuntimeError("credential vault locked")

        monkeypatch.setattr("flinttrade_ditto.account_manager.AccountManager", _boom)

        resp = client.get("/api/v1/accounts/status", headers=_auth_headers())
        assert resp.status_code == 503
        assert resp.get_json()["status"] == "error"

    def test_connection_status_exception_log_is_redacted(self, client, monkeypatch, caplog):
        secret = "account-id host.invalid credential-store/path api-key-value"

        def _boom(**_kwargs):
            raise RuntimeError(secret)

        monkeypatch.setattr("flinttrade_ditto.account_manager.AccountManager", _boom)
        with caplog.at_level("WARNING", logger="flinttrade"):
            response = client.get("/api/v1/accounts/status", headers=_auth_headers())

        assert response.status_code == 503
        assert secret not in response.get_data(as_text=True)
        assert secret not in caplog.text
        assert "RuntimeError" in caplog.text


class TestWebhooksManagement:
    """GET/POST/PATCH/DELETE /api/v1/webhooks — the endpoints behind the Flows panel.

    The list must emit ``id`` and ``type`` per webhook: the panel keys its table
    and its delete action off ``id`` (so a missing id breaks delete entirely) and
    renders the source badge off ``type``.
    """

    @pytest.fixture(autouse=True)
    def registry(self):
        from flinttrade_core.workspace import Workspace

        workspace = Workspace()
        workspace.load()
        previous = workspace.get("automation.webhooks", [])
        workspace.set("automation.webhooks", [])
        yield
        workspace.set("automation.webhooks", previous)

    def _create(
        self,
        client,
        *,
        path: str,
        name: str,
        webhook_type: str = "custom",
        secret: str = "test-management-secret",
        enabled: bool = True,
    ):
        return client.post(
            "/api/v1/webhooks",
            headers=_auth_headers(),
            json={"path": path, "name": name, "type": webhook_type, "secret": secret, "enabled": enabled},
        )

    def _signed_headers(self, body: bytes, secret: str, *, nonce: str = "ops-nonce-1") -> dict[str, str]:
        from flinttrade_webhooks.webhook_hmac import build_webhook_signature_payload

        timestamp = str(time.time())
        signed_payload = build_webhook_signature_payload(body, nonce=nonce, timestamp=timestamp)
        return {
            "Content-Type": "application/json",
            "X-Signature": "sha256=" + hmac.new(
                secret.encode("utf-8"), signed_payload, hashlib.sha256
            ).hexdigest(),
            "X-Webhook-Nonce": nonce,
            "X-Webhook-Timestamp": timestamp,
        }

    def test_list_starts_empty_without_standalone_server(self, client):
        resp = client.get("/api/v1/webhooks", headers=_auth_headers())
        assert resp.status_code == 200
        data = resp.get_json()["data"]
        assert data == {"webhooks": []}

    def test_create_returns_full_config(self, client):
        resp = self._create(
            client,
            path="/webhook/custom/scan1",
            name="Custom Scan",
            webhook_type="custom",
        )
        assert resp.status_code == 201
        data = resp.get_json()["data"]
        assert data["id"] == "v1/webhook/custom/scan1"
        assert data["path"] == "/v1/webhook/custom/scan1"
        assert data["type"] == "custom"
        assert data["enabled"] is True
        assert data["secret_configured"] is True
        assert "secret" not in data

    def test_create_retired_provider_source_is_rejected(self, client):
        """Retired provider sources cannot be registered any more."""
        for retired in ("tradingview", "chartink", "gocharting"):
            resp = self._create(
                client,
                path=f"/webhook/{retired}/momentum",
                name=f"{retired} endpoint",
                webhook_type=retired,
            )
            assert resp.status_code == 400, retired

    def test_cross_process_mutations_preserve_both_registry_rows_and_secrets(self, tmp_path, monkeypatch):
        from flinttrade_core.operations_routes import _webhook_registry_lock

        monkeypatch.setenv("FLINTTRADE_WORKSPACE_DIR", str(tmp_path))
        db_path = tmp_path / "webhooks.db"
        env = {**os.environ, "FLINTTRADE_WORKSPACE_DIR": str(tmp_path)}

        def mutate(slug: str, secret: str, timeout: float) -> subprocess.CompletedProcess[str]:
            return subprocess.run(
                [
                    sys.executable,
                    "-c",
                    _WEBHOOK_REGISTRY_PROCESS_SCRIPT,
                    str(tmp_path),
                    str(db_path),
                    slug,
                    secret,
                    str(timeout),
                ],
                env=env,
                capture_output=True,
                text=True,
                timeout=10,
                check=False,
            )

        first = mutate("concurrent-one", "secret-one", 5)
        assert first.returncode == 0, first.stderr

        with _webhook_registry_lock():
            blocked = mutate("concurrent-two", "secret-two", 0.25)
        assert blocked.returncode == 75, blocked.stderr

        second = mutate("concurrent-two", "secret-two", 5)
        assert second.returncode == 0, second.stderr
        from flinttrade_core.workspace import Workspace
        from flinttrade_webhooks.webhook_secret_store import WebhookSecretStore

        rows = Workspace(home_dir=tmp_path).get("automation.webhooks", [])
        paths = {row["path"] for row in rows}
        assert "/v1/webhook/custom/concurrent-one" in paths
        assert "/v1/webhook/custom/concurrent-two" in paths
        store = WebhookSecretStore(db_path, "process-test-master-password")
        assert store.get_secret("/v1/webhook/custom/concurrent-one") == "secret-one"
        assert store.get_secret("/v1/webhook/custom/concurrent-two") == "secret-two"

    def test_create_requires_signing_secret(self, client):
        resp = self._create(
            client,
            path="/webhook/custom/unsigned",
            name="Unsigned",
            secret="",
        )

        assert resp.status_code == 400
        assert resp.get_json()["message"] == "signing secret is required"

    def test_patch_toggles_enabled_state(self, client):
        from urllib.parse import quote

        created = self._create(
            client,
            path="/webhook/custom/toggle-me",
            name="Toggle Me",
        )
        target = created.get_json()["data"]

        disabled = client.patch(
            f"/api/v1/webhooks/{quote(target['id'], safe='')}",
            headers=_auth_headers(),
            json={"enabled": False},
        )

        assert disabled.status_code == 200
        assert disabled.get_json()["data"]["enabled"] is False
        listed = client.get("/api/v1/webhooks", headers=_auth_headers()).get_json()["data"]["webhooks"]
        assert next(row for row in listed if row["id"] == target["id"])["enabled"] is False

    def test_patch_rejects_non_boolean_enabled_state(self, client):
        from urllib.parse import quote

        created = self._create(
            client,
            path="/webhook/custom/toggle-me",
            name="Toggle Me",
        )
        target = created.get_json()["data"]

        resp = client.patch(
            f"/api/v1/webhooks/{quote(target['id'], safe='')}",
            headers=_auth_headers(),
            json={"enabled": "false"},
        )

        assert resp.status_code == 400
        assert resp.get_json()["message"] == "enabled must be a boolean"

    def test_legacy_secretless_row_is_listed_unconfigured_and_cannot_be_enabled(
        self,
        flask_app,
        client,
    ):
        from urllib.parse import quote

        from flinttrade_core.workspace import Workspace

        path = "/v1/webhook/custom/legacy-secretless"
        flask_app.config["WEBHOOK_SECRET_STORE"].delete_secret(path)
        Workspace().set("automation.webhooks", [{
            "path": path,
            "name": "Legacy Secretless",
            "type": "custom",
            "enabled": True,
        }])

        listed = client.get("/api/v1/webhooks", headers=_auth_headers())
        row = listed.get_json()["data"]["webhooks"][0]
        assert row["enabled"] is False
        assert row["secret_configured"] is False

        enabled = client.patch(
            f"/api/v1/webhooks/{quote(row['id'], safe='')}",
            headers=_auth_headers(),
            json={"enabled": True},
        )
        assert enabled.status_code == 409
        assert "recreate" in enabled.get_json()["message"].lower()

    def test_display_name_is_not_an_ambiguous_patch_or_delete_identifier(
        self,
        flask_app,
        client,
    ):
        from urllib.parse import quote

        first = self._create(
            client,
            path="/webhook/custom/duplicate-name-one",
            name="Shared Display Name",
            secret="first-secret",
        ).get_json()["data"]
        second = self._create(
            client,
            path="/webhook/custom/duplicate-name-two",
            name="Shared Display Name",
            secret="second-secret",
        ).get_json()["data"]

        ambiguous_id = quote("Shared Display Name", safe="")
        patched = client.patch(
            f"/api/v1/webhooks/{ambiguous_id}",
            headers=_auth_headers(),
            json={"enabled": False},
        )
        deleted = client.delete(
            f"/api/v1/webhooks/{ambiguous_id}",
            headers=_auth_headers(),
        )

        assert patched.status_code == 404
        assert deleted.status_code == 404
        listed = client.get("/api/v1/webhooks", headers=_auth_headers()).get_json()["data"]["webhooks"]
        assert {row["id"] for row in listed} == {first["id"], second["id"]}
        store = flask_app.config["WEBHOOK_SECRET_STORE"]
        assert store.get_secret(first["path"]) == "first-secret"
        assert store.get_secret(second["path"]) == "second-secret"

    def test_create_rolls_back_registry_when_secret_store_fails(self, flask_app, client, monkeypatch):
        store = flask_app.config["WEBHOOK_SECRET_STORE"]

        def _fail_store(*_args, **_kwargs):
            raise OSError("vault unavailable")

        monkeypatch.setattr(store, "store_secret", _fail_store)
        resp = self._create(
            client,
            path="/webhook/custom/atomic-create",
            name="Atomic Create",
        )

        assert resp.status_code == 503
        rows = client.get("/api/v1/webhooks", headers=_auth_headers()).get_json()["data"]["webhooks"]
        assert all(row["name"] != "Atomic Create" for row in rows)

    def test_create_removes_new_secret_when_registry_save_fails(
        self, flask_app, client, monkeypatch
    ):
        def _fail_save(*_args, **_kwargs):
            raise OSError("workspace unavailable")

        monkeypatch.setattr("flinttrade_core.operations_routes._save_webhook_registry", _fail_save)
        resp = self._create(
            client,
            path="/webhook/custom/registry-save-failure",
            name="Registry Save Failure",
            secret="must-be-removed",
        )

        assert resp.status_code == 500
        store = flask_app.config["WEBHOOK_SECRET_STORE"]
        assert store.has_secret("/v1/webhook/custom/registry-save-failure") is False
        rows = client.get("/api/v1/webhooks", headers=_auth_headers()).get_json()["data"]["webhooks"]
        assert all(row["name"] != "Registry Save Failure" for row in rows)

    def test_replace_restores_previous_secret_when_registry_save_fails(
        self, flask_app, client, monkeypatch
    ):
        created = self._create(
            client,
            path="/webhook/custom/replace-failure",
            name="Original Endpoint",
            secret="original-secret",
        )
        assert created.status_code == 201

        def _fail_save(*_args, **_kwargs):
            raise OSError("workspace unavailable")

        monkeypatch.setattr("flinttrade_core.operations_routes._save_webhook_registry", _fail_save)
        resp = self._create(
            client,
            path="/webhook/custom/replace-failure",
            name="Replacement Endpoint",
            secret="replacement-secret",
        )

        assert resp.status_code == 500
        store = flask_app.config["WEBHOOK_SECRET_STORE"]
        assert store.get_secret("/v1/webhook/custom/replace-failure") == "original-secret"
        rows = client.get("/api/v1/webhooks", headers=_auth_headers()).get_json()["data"]["webhooks"]
        assert next(row for row in rows if row["path"].endswith("/replace-failure"))["name"] == "Original Endpoint"

    def test_delete_rolls_back_registry_when_secret_delete_fails(
        self, flask_app, client, monkeypatch
    ):
        from urllib.parse import quote

        created = self._create(
            client,
            path="/webhook/custom/atomic-delete",
            name="Atomic Delete",
        )
        target = created.get_json()["data"]
        store = flask_app.config["WEBHOOK_SECRET_STORE"]

        def _fail_delete(*_args, **_kwargs):
            raise OSError("vault unavailable")

        monkeypatch.setattr(store, "delete_secret", _fail_delete)
        resp = client.delete(
            f"/api/v1/webhooks/{quote(target['id'], safe='')}",
            headers=_auth_headers(),
        )

        assert resp.status_code == 503
        rows = client.get("/api/v1/webhooks", headers=_auth_headers()).get_json()["data"]["webhooks"]
        assert any(row["id"] == target["id"] for row in rows)

    def test_delete_restores_secret_when_registry_save_fails(
        self, flask_app, client, monkeypatch
    ):
        from urllib.parse import quote

        created = self._create(
            client,
            path="/webhook/custom/delete-save-failure",
            name="Delete Save Failure",
            secret="restore-after-failure",
        )
        target = created.get_json()["data"]

        def _fail_save(*_args, **_kwargs):
            raise OSError("workspace unavailable")

        monkeypatch.setattr("flinttrade_core.operations_routes._save_webhook_registry", _fail_save)
        resp = client.delete(
            f"/api/v1/webhooks/{quote(target['id'], safe='')}",
            headers=_auth_headers(),
        )

        assert resp.status_code == 500
        store = flask_app.config["WEBHOOK_SECRET_STORE"]
        assert store.get_secret(target["path"]) == "restore-after-failure"
        rows = client.get("/api/v1/webhooks", headers=_auth_headers()).get_json()["data"]["webhooks"]
        assert any(row["id"] == target["id"] for row in rows)

    def test_path_without_source_uses_selected_type(self, client):
        resp = self._create(
            client,
            path="/webhook/nifty-breakout",
            name="Nifty Breakout",
            webhook_type="custom",
        )
        assert resp.status_code == 201
        data = resp.get_json()["data"]
        assert data["id"] == "v1/webhook/custom/nifty-breakout"
        assert data["path"] == "/v1/webhook/custom/nifty-breakout"
        assert data["type"] == "custom"

    def test_create_with_secret_uses_encrypted_store_without_echoing_secret(self, flask_app, client):
        resp = self._create(
            client,
            path="/webhook/custom/scan1",
            name="Custom Scan",
            webhook_type="custom",
            secret="do-not-store-in-workspace-json",
        )
        assert resp.status_code == 201
        body = resp.get_json()
        assert body["status"] == "success"
        data = body["data"]
        assert data["path"] == "/v1/webhook/custom/scan1"
        assert "secret" not in data

        from flinttrade_core.workspace import Workspace

        workspace_rows = Workspace().get("automation.webhooks", [])
        assert workspace_rows
        assert all("secret" not in row for row in workspace_rows)

        store = flask_app.config["WEBHOOK_SECRET_STORE"]
        assert store.get_secret("/v1/webhook/custom/scan1") == "do-not-store-in-workspace-json"

    def test_list_id_round_trips_through_delete(self, client):
        """The id the list emits must, URL-encoded as the frontend does, delete
        that exact webhook — proving the encoded-path id survives routing."""
        from urllib.parse import quote

        created = self._create(
            client,
            path="/webhook/custom/my_signal",
            name="My Signal",
            webhook_type="custom",
        )
        assert created.status_code == 201

        listed = client.get("/api/v1/webhooks", headers=_auth_headers()).get_json()["data"]["webhooks"]
        target = next(w for w in listed if w["name"] == "My Signal")

        # mirror the frontend's encodeURIComponent(id)
        resp = client.delete(
            f"/api/v1/webhooks/{quote(target['id'], safe='')}",
            headers=_auth_headers(),
        )
        assert resp.status_code == 200

        remaining = client.get("/api/v1/webhooks", headers=_auth_headers()).get_json()["data"]["webhooks"]
        assert all(w["name"] != "My Signal" for w in remaining)

    def test_delete_removes_matching_webhook_secret(self, flask_app, client):
        from urllib.parse import quote

        created = self._create(
            client,
            path="/webhook/custom/private_signal",
            name="Private Signal",
            webhook_type="custom",
            secret="delete-me-too",
        )
        assert created.status_code == 201
        target = created.get_json()["data"]

        store = flask_app.config["WEBHOOK_SECRET_STORE"]
        assert store.has_secret(target["path"]) is True

        resp = client.delete(
            f"/api/v1/webhooks/{quote(target['id'], safe='')}",
            headers=_auth_headers(),
        )
        assert resp.status_code == 200
        assert store.has_secret(target["path"]) is False

    def test_signed_webhook_post_is_public_but_still_hmac_checked(self, client):
        secret = "public-post-secret"
        created = self._create(
            client,
            path="/webhook/custom/public-signal",
            name="Public Signal",
            webhook_type="custom",
            secret=secret,
        )
        assert created.status_code == 201

        body = json.dumps({"action": "signal", "symbol": "TCS"}).encode("utf-8")
        resp = client.post(
            "/ft-api/v1/webhook/custom/public-signal",
            data=body,
            headers=self._signed_headers(body, secret, nonce=f"public-post-{time.time_ns()}"),
        )
        assert resp.status_code == 200
        payload = resp.get_json()
        assert payload["status"] == "success"
        assert payload["data"]["status"] == "received"

        bad_headers = self._signed_headers(body, "wrong-secret", nonce=f"public-post-bad-{time.time_ns()}")
        rejected = client.post(
            "/ft-api/v1/webhook/custom/public-signal",
            data=body,
            headers=bad_headers,
        )
        assert rejected.status_code == 401

    def test_disabled_registered_webhook_is_rejected_before_dispatch(self, client):
        secret = "disabled-post-secret"
        created = self._create(
            client,
            path="/webhook/custom/disabled-signal",
            name="Disabled Signal",
            webhook_type="custom",
            secret=secret,
            enabled=False,
        )
        assert created.status_code == 201

        body = json.dumps({"action": "signal", "symbol": "TCS"}).encode("utf-8")
        resp = client.post(
            "/ft-api/v1/webhook/custom/disabled-signal",
            data=body,
            headers=self._signed_headers(body, secret, nonce=f"disabled-post-{time.time_ns()}"),
        )
        assert resp.status_code == 503
        assert resp.get_json()["message"] == "Webhook endpoint disabled"

    @pytest.mark.parametrize(
        ("source", "body_data", "router_method"),
        [
            (
                "custom",
                {"action": "place_order", "side": "BUY", "symbol": "NIFTY", "exchange": "NFO", "quantity": 1},
                "place_order",
            ),
            (
                "custom",
                {"action": "cancel_order", "orderid": "ORDER-7"},
                "cancel_order",
            ),
        ],
    )
    def test_registered_write_endpoint_cannot_reach_router_while_unarmed(
        self,
        flask_app,
        client,
        source,
        body_data,
        router_method,
    ):
        secret = f"unarmed-{source}-secret"
        endpoint = f"unarmed-{router_method}"
        created = self._create(
            client,
            path=f"/webhook/{source}/{endpoint}",
            name=f"Unarmed {router_method}",
            webhook_type=source,
            secret=secret,
        )
        assert created.status_code == 201

        router = MagicMock()
        original_router = flask_app.config.get("BROKER_ROUTER")
        flask_app.config["BROKER_ROUTER"] = router
        body = json.dumps(body_data).encode("utf-8")
        try:
            response = client.post(
                f"/ft-api/v1/webhook/{source}/{endpoint}",
                data=body,
                headers=self._signed_headers(
                    body,
                    secret,
                    nonce=f"unarmed-{router_method}-{time.time_ns()}",
                ),
            )
        finally:
            flask_app.config["BROKER_ROUTER"] = original_router

        assert response.status_code == 422
        payload = response.get_json()
        assert payload["status"] == "error"
        assert "not armed" in payload["message"].lower()
        getattr(router, router_method).assert_not_called()
