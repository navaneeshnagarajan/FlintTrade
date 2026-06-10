"""Tests for the autonomous-agent control plane (/api/v1/ai/agent/*).

The critical property: the route is the ONLY place an order executor is
wired into the AutonomousTrader, and it wires a GatedChildExecutor bound to
an AGENT principal — so agent orders cannot exist outside the gated path,
and cannot pass the router ACL unless the operator explicitly granted the
agent actor id in workspace.json.
"""

from __future__ import annotations

import time
from typing import Any

import pytest
from flask import Flask

import flinttrade_core.agent_routes as mod
import flinttrade_core.order_routes as order_routes_mod
from flinttrade_core.smart_order_routes import GatedChildExecutor
from flinttrade_engine.safety import SafetyConfig, SafetySystem, set_safety_gate_secret

pytestmark = pytest.mark.unit

SECRET = b"0123456789abcdef0123456789abcdef"


class _FakeTrader:
    """Stands in for AutonomousTrader: records ctor kwargs, runs briefly."""

    instances: list["_FakeTrader"] = []

    def __init__(self, **kwargs: Any) -> None:
        from flinttrade_ai.autonomous_agent import AgentState, AgentStatus

        self.kwargs = kwargs
        self.state = AgentState()
        self.status = AgentStatus.RUNNING
        self.stop_calls: list[bool] = []
        self._running = True
        _FakeTrader.instances.append(self)

    def request_stop(self, square_off: bool = True) -> None:
        self.stop_calls.append(square_off)
        self._running = False

    async def run_session(self) -> None:
        import asyncio

        while self._running:
            await asyncio.sleep(0.02)


@pytest.fixture(autouse=True)
def _reset(monkeypatch):
    set_safety_gate_secret(SECRET)
    mod._reset_runner_for_tests()  # noqa: SLF001
    _FakeTrader.instances = []
    monkeypatch.setattr(mod, "_agent_flag_enabled", lambda: True)
    monkeypatch.setattr(mod, "_acl_grants_agent", lambda a, b: True)
    monkeypatch.setattr(mod, "_build_llm", lambda: object())
    monkeypatch.setattr(mod, "_build_vault", lambda: None)
    monkeypatch.setattr(mod, "_trader_factory", _FakeTrader)
    yield
    # Stop any session the test left running so threads do not leak.
    for trader in _FakeTrader.instances:
        trader._running = False  # noqa: SLF001


@pytest.fixture()
def live_auth(monkeypatch):
    monkeypatch.setattr(
        order_routes_mod,
        "_decode_request_payload",
        lambda: {"mode": "live", "sub": "user-1", "jti": "jti-1"},
    )
    monkeypatch.setattr(order_routes_mod, "_is_live_mode_unlocked", lambda: True)


def _make_app() -> Flask:
    app = Flask(__name__)
    app.config["TESTING"] = True
    app.config["BROKER_ROUTER"] = object()
    app.config["OPENALGO_CLIENT"] = object()
    app.config["SAFETY"] = SafetySystem(SafetyConfig(check_market_hours=False))
    app.register_blueprint(mod.agent_bp)
    return app


def _start_body() -> dict:
    return {"symbols": ["RELIANCE"], "exchange": "NSE", "cycle_interval_sec": 1}


# ---------------------------------------------------------------------------
# Fail-closed preconditions
# ---------------------------------------------------------------------------


def test_disabled_flag_403(monkeypatch, live_auth):
    monkeypatch.setattr(mod, "_agent_flag_enabled", lambda: False)
    resp = _make_app().test_client().post("/api/v1/ai/agent/start", json=_start_body())
    assert resp.status_code == 403
    assert "autonomous_agent.enabled" in resp.get_json()["message"]


def test_no_jwt_401(monkeypatch):
    monkeypatch.setattr(order_routes_mod, "_decode_request_payload", lambda: None)
    resp = _make_app().test_client().post("/api/v1/ai/agent/start", json=_start_body())
    assert resp.status_code == 401


def test_practice_mode_403(monkeypatch):
    monkeypatch.setattr(
        order_routes_mod,
        "_decode_request_payload",
        lambda: {"mode": "practice", "sub": "user-1", "jti": "jti-1"},
    )
    resp = _make_app().test_client().post("/api/v1/ai/agent/start", json=_start_body())
    assert resp.status_code == 403


def test_missing_acl_grant_403_with_instruction(monkeypatch, live_auth):
    """The agent is its own principal — an ungrated actor must fail fast with
    the exact workspace.json fix, not start a session whose every order is
    refused downstream."""
    monkeypatch.setattr(mod, "_acl_grants_agent", lambda a, b: False)
    resp = _make_app().test_client().post("/api/v1/ai/agent/start", json=_start_body())
    assert resp.status_code == 403
    msg = resp.get_json()["message"]
    assert "autonomous-trader" in msg
    assert "account_acls" in msg


def test_empty_symbols_400(live_auth):
    resp = _make_app().test_client().post("/api/v1/ai/agent/start", json={"symbols": []})
    assert resp.status_code == 400


def test_router_unavailable_503(live_auth):
    app = _make_app()
    app.config["BROKER_ROUTER"] = None
    resp = app.test_client().post("/api/v1/ai/agent/start", json=_start_body())
    assert resp.status_code == 503


# ---------------------------------------------------------------------------
# Lifecycle
# ---------------------------------------------------------------------------


def test_start_wires_gated_executor_with_agent_principal(live_auth):
    """The trader receives a GatedChildExecutor bound to actor_type='agent'."""
    app = _make_app()
    resp = app.test_client().post("/api/v1/ai/agent/start", json=_start_body())
    assert resp.status_code == 202

    trader = _FakeTrader.instances[-1]
    executor = trader.kwargs["order_executor"]
    assert isinstance(executor, GatedChildExecutor)
    ctx = executor._request_ctx  # noqa: SLF001
    assert ctx.actor_type == "agent"
    assert ctx.actor_id == "autonomous-trader"
    assert ctx.mode == "live"
    assert ctx.selector == "openalgo:default"
    # The mid-flight revocation brake is wired.
    assert executor._pre_dispatch_check is not None  # noqa: SLF001

    snap = resp.get_json()["data"]
    assert snap["running"] is True
    assert snap["actor_id"] == "autonomous-trader"


def test_double_start_409(live_auth):
    app = _make_app()
    client = app.test_client()
    assert client.post("/api/v1/ai/agent/start", json=_start_body()).status_code == 202
    resp = client.post("/api/v1/ai/agent/start", json=_start_body())
    assert resp.status_code == 409


def test_stop_requests_square_off_and_status_reflects(live_auth):
    app = _make_app()
    client = app.test_client()
    client.post("/api/v1/ai/agent/start", json=_start_body())

    resp = client.post("/api/v1/ai/agent/stop", json={})
    assert resp.status_code == 200
    trader = _FakeTrader.instances[-1]
    assert trader.stop_calls == [True]  # square-off is the safe default

    # The session thread exits once the fake trader stops.
    deadline = time.monotonic() + 5.0
    while time.monotonic() < deadline:
        status = client.get("/api/v1/ai/agent/status").get_json()["data"]
        if not status["running"]:
            break
        time.sleep(0.02)
    assert status["running"] is False


def test_stop_without_session_404(live_auth):
    resp = _make_app().test_client().post("/api/v1/ai/agent/stop", json={})
    assert resp.status_code == 404


def test_status_idle_shape(live_auth):
    resp = _make_app().test_client().get("/api/v1/ai/agent/status")
    assert resp.status_code == 200
    data = resp.get_json()["data"]
    assert data["running"] is False
    assert data["enabled"] is True
