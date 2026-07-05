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
_ORIGINAL_BUILD_VAULT = mod._build_vault  # noqa: SLF001


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


def _make_app(broker_router: object | None = None) -> Flask:
    app = Flask(__name__)
    app.config["TESTING"] = True
    app.config["BROKER_ROUTER"] = broker_router if broker_router is not None else object()
    app.config["OPENALGO_CLIENT"] = object()
    app.config["SAFETY"] = SafetySystem(SafetyConfig(check_market_hours=False))
    app.register_blueprint(mod.agent_bp)
    return app


def _start_body() -> dict:
    return {"symbols": ["RELIANCE"], "exchange": "NSE", "cycle_interval_sec": 1}


# ---------------------------------------------------------------------------
# Optional context builders
# ---------------------------------------------------------------------------


def test_build_vault_uses_configured_path(monkeypatch, tmp_path):
    monkeypatch.setenv("FLINTTRADE_OBSIDIAN_VAULT", str(tmp_path))

    vault = _ORIGINAL_BUILD_VAULT()

    assert vault is not None
    assert vault.root == tmp_path


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


def test_start_uses_configured_execution_default_when_target_omitted(live_auth):
    """Direct agent starts inherit brokers.execution.default when no target is sent."""

    class _Execution:
        default = "upstox:U1"

    class _Config:
        execution = _Execution()

    class _Router:
        _config = _Config()

    app = _make_app(broker_router=_Router())
    resp = app.test_client().post("/api/v1/ai/agent/start", json=_start_body())
    assert resp.status_code == 202

    executor = _FakeTrader.instances[-1].kwargs["order_executor"]
    assert executor._request_ctx.selector == "upstox:U1"  # noqa: SLF001


def test_double_start_409(live_auth):
    app = _make_app()
    client = app.test_client()
    assert client.post("/api/v1/ai/agent/start", json=_start_body()).status_code == 202
    resp = client.post("/api/v1/ai/agent/start", json=_start_body())
    assert resp.status_code == 409


def test_start_claims_slot_atomically(live_auth, monkeypatch):
    """A second /start that races in while the first is still constructing
    (the 'starting' sentinel set, runner not yet registered) is refused —
    not allowed to spawn a second live agent that orphans the first."""
    # Simulate the in-construction window: claim the slot via the sentinel.
    with mod._RUNNER_LOCK:  # noqa: SLF001
        mod._RUNNER["starting"] = True  # noqa: SLF001
    try:
        resp = _make_app().test_client().post("/api/v1/ai/agent/start", json=_start_body())
        assert resp.status_code == 409
        assert _FakeTrader.instances == []  # no trader was constructed
    finally:
        mod._reset_runner_for_tests()  # noqa: SLF001


def test_failed_construction_releases_the_slot(live_auth, monkeypatch):
    """If trader construction raises, the 'starting' sentinel is rolled back so
    the slot is not wedged forever."""
    monkeypatch.setattr(
        mod, "_trader_factory",
        lambda **k: (_ for _ in ()).throw(RuntimeError("boom")),
    )
    resp = _make_app().test_client().post("/api/v1/ai/agent/start", json=_start_body())
    assert resp.status_code == 500
    with mod._RUNNER_LOCK:  # noqa: SLF001
        assert not mod._RUNNER.get("starting")  # noqa: SLF001
    # A subsequent valid start is accepted (slot was released).
    monkeypatch.setattr(mod, "_trader_factory", _FakeTrader)
    assert _make_app().test_client().post("/api/v1/ai/agent/start", json=_start_body()).status_code == 202


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


def test_stop_and_status_require_auth(monkeypatch):
    """Snapshot exposes live positions; stop is an operator action — both
    need a JWT (parity with the smart-route read endpoints)."""
    monkeypatch.setattr(order_routes_mod, "_decode_request_payload", lambda: None)
    client = _make_app().test_client()
    assert client.get("/api/v1/ai/agent/status").status_code == 401
    assert client.post("/api/v1/ai/agent/stop", json={}).status_code == 401
