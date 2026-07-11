"""Tests for the smart-order routing endpoints (/api/v1/orders/smart-route).

The critical property under test: every CHILD order the SmartOrderRouter
emits traverses the REAL gated execution path — a genuine ``gate_order``
mint verified and consumed by a genuine :class:`BrokerRouter` in front of a
no-I/O adapter guarded by the module-private router token. No mocked gate.
"""

from __future__ import annotations

import asyncio
import threading
import time
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock

import pytest
from flask import Flask

import flinttrade_core.order_routes as order_routes_mod
import flinttrade_core.smart_order_routes as mod
from flinttrade_core.exceptions import SafetyBypassError
from flinttrade_core.models import Action, Exchange, Order, PriceType
from flinttrade_engine.request_context import RequestContext
from flinttrade_engine.safety import SafetyConfig, SafetySystem, set_safety_gate_secret
from flinttrade_gateway.brokers._base import Session
from flinttrade_gateway.brokers.dhan import _ROUTER_TOKEN
from flinttrade_gateway.router import BrokerRouter

pytestmark = pytest.mark.unit

SECRET = b"0123456789abcdef0123456789abcdef"


@pytest.fixture(autouse=True)
def _bind_secret():
    set_safety_gate_secret(SECRET)
    mod._reset_jobs_for_tests()  # noqa: SLF001


class _NoIoAdapter:
    """Records gated dispatches; refuses any call without the router token."""

    def __init__(self) -> None:
        self.orders: list[object] = []
        self.sessions: list[object] = []

    async def place_order(self, session: object, order: object, *, _router_token: object = None) -> str:
        if _router_token is not _ROUTER_TOKEN:
            raise SafetyBypassError("adapter write method called outside BrokerRouter")
        self.sessions.append(session)
        self.orders.append(order)
        return f"OID-{len(self.orders)}"


def _session(_ctx: object, adapter_id: str, account_id: str) -> Session:
    return Session(
        access_token="tok",
        expires_at=datetime.now(tz=timezone.utc).timestamp() + 3600,
        account_id=account_id,
        adapter_id=adapter_id,
    )


class _FakeClient:
    """Depth/quotes provider stub for the market-data boundary."""

    def __init__(self, asks=None, bids=None, volume=1000):
        from flinttrade_core.models import Depth, DepthLevel, Quote

        self._depth = Depth(
            asks=[DepthLevel(price=p, quantity=q) for p, q in (asks or [])],
            bids=[DepthLevel(price=p, quantity=q) for p, q in (bids or [])],
        )
        self._quote = Quote(volume=volume)

    async def depth(self, symbol: str, exchange: str = "NSE"):
        return self._depth

    async def quotes(self, symbol: str, exchange: str = "NSE"):
        return self._quote


def _safety() -> SafetySystem:
    # Market-hours enforcement is real L1 behaviour (a smart route off-hours is
    # refused) — disable it here so the tests don't depend on wall-clock time.
    return SafetySystem(SafetyConfig(check_market_hours=False))


_DEFAULT_OPENALGO_CLIENT = object()


def _make_app(
    *,
    enabled: bool = True,
    adapter: _NoIoAdapter | None = None,
    adapter_id: str = "openalgo",
    openalgo_client: object = _DEFAULT_OPENALGO_CLIENT,
    execution_default: str | None = None,
) -> tuple[Flask, _NoIoAdapter]:
    from flinttrade_gateway.routing_config import RoutingConfig

    adapter = adapter or _NoIoAdapter()
    app = Flask(__name__)
    app.config["TESTING"] = True
    app.config["SMART_ROUTING"] = {"enabled": enabled, "twap_window_seconds": 1, "twap_slices": 2}
    router_config = None
    if execution_default is not None:
        router_config = RoutingConfig.from_workspace({
            "registered": [execution_default],
            "execution": {"default": execution_default},
            "data": {
                "ticks": execution_default,
                "historical": execution_default,
                "option_chains": execution_default,
                "quote": execution_default,
            },
        })
    app.config["BROKER_ROUTER"] = BrokerRouter({adapter_id: adapter}, _session, config=router_config)
    if openalgo_client is _DEFAULT_OPENALGO_CLIENT:
        openalgo_client = _FakeClient(asks=[(100.0, 500)], bids=[(99.5, 500)])
    app.config["OPENALGO_CLIENT"] = openalgo_client
    app.config["SAFETY"] = _safety()
    app.register_blueprint(mod.smart_order_bp)
    return app, adapter


@pytest.fixture()
def live_auth(monkeypatch):
    """Authenticated live-mode, PIN-unlocked request environment."""
    monkeypatch.setattr(
        order_routes_mod,
        "_decode_request_payload",
        lambda: {"mode": "live", "sub": "user-1", "jti": "jti-1"},
    )
    monkeypatch.setattr(order_routes_mod, "_is_live_mode_unlocked", lambda: True)


def _wait_done(client, job_id: str, timeout: float = 5.0) -> dict:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        resp = client.get(f"/api/v1/orders/smart-route/{job_id}")
        data = resp.get_json()["data"]
        if data["status"] != "running":
            return data
        time.sleep(0.05)
    raise AssertionError(f"smart-route job {job_id} did not finish within {timeout}s")


# ---------------------------------------------------------------------------
# Fail-closed preconditions
# ---------------------------------------------------------------------------


def test_disabled_flag_403(live_auth):
    app, _ = _make_app(enabled=False)
    resp = app.test_client().post(
        "/api/v1/orders/smart-route",
        json={"symbol": "RELIANCE", "exchange": "NSE", "action": "BUY", "quantity": 10},
    )
    assert resp.status_code == 403
    assert "smart_routing.enabled" in resp.get_json()["message"]


def test_no_jwt_401(monkeypatch):
    monkeypatch.setattr(order_routes_mod, "_decode_request_payload", lambda: None)
    app, _ = _make_app()
    resp = app.test_client().post(
        "/api/v1/orders/smart-route",
        json={"symbol": "RELIANCE", "exchange": "NSE", "action": "BUY", "quantity": 10},
    )
    assert resp.status_code == 401


def test_practice_mode_403(monkeypatch):
    monkeypatch.setattr(
        order_routes_mod,
        "_decode_request_payload",
        lambda: {"mode": "practice", "sub": "user-1", "jti": "jti-1"},
    )
    app, _ = _make_app()
    resp = app.test_client().post(
        "/api/v1/orders/smart-route",
        json={"symbol": "RELIANCE", "exchange": "NSE", "action": "BUY", "quantity": 10},
    )
    assert resp.status_code == 403
    assert "live mode only" in resp.get_json()["message"]


def test_validation_400(live_auth):
    app, _ = _make_app()
    client = app.test_client()
    assert client.post("/api/v1/orders/smart-route", json={}).status_code == 400
    assert client.post(
        "/api/v1/orders/smart-route",
        json={"symbol": "X", "exchange": "NSE", "action": "HOLD", "quantity": 10},
    ).status_code == 400
    assert client.post(
        "/api/v1/orders/smart-route",
        json={"symbol": "X", "exchange": "NSE", "action": "BUY", "quantity": 0},
    ).status_code == 400
    assert client.post(
        "/api/v1/orders/smart-route",
        json={"symbol": "X", "exchange": "NSE", "action": "BUY", "quantity": 10, "urgency": "now"},
    ).status_code == 400


def test_router_unavailable_503(live_auth):
    app, _ = _make_app()
    app.config["BROKER_ROUTER"] = None
    resp = app.test_client().post(
        "/api/v1/orders/smart-route",
        json={"symbol": "RELIANCE", "exchange": "NSE", "action": "BUY", "quantity": 10},
    )
    assert resp.status_code == 503


def test_unknown_job_404(live_auth):
    app, _ = _make_app()
    resp = app.test_client().get("/api/v1/orders/smart-route/nope")
    assert resp.status_code == 404


# ---------------------------------------------------------------------------
# End-to-end through the REAL gate + router
# ---------------------------------------------------------------------------


def test_high_urgency_places_one_gated_child(live_auth):
    """A high-urgency order yields one child placed through the real gate."""
    app, adapter = _make_app()
    client = app.test_client()

    resp = client.post(
        "/api/v1/orders/smart-route",
        json={
            "symbol": "RELIANCE", "exchange": "NSE", "action": "BUY",
            "quantity": 10, "urgency": "high",
        },
    )
    assert resp.status_code == 202
    job_id = resp.get_json()["data"]["job_id"]

    final = _wait_done(client, job_id)
    assert final["status"] == "done"
    assert final["completed"] is True
    assert final["filled_quantity"] == 10
    assert len(final["child_orders"]) == 1
    assert final["child_orders"][0]["status"] == "placed"
    assert final["child_orders"][0]["order_id"] == "OID-1"

    # The adapter saw exactly one typed child order — and it can ONLY have
    # been reached through BrokerRouter (token-guarded), proving the child
    # traversed gate_order → BrokerRouter → adapter.
    assert len(adapter.orders) == 1
    assert adapter.orders[0].quantity == "10"


def test_native_high_urgency_does_not_require_openalgo_client(live_auth):
    """Native high urgency can execute through BrokerRouter without bridge data."""
    app, adapter = _make_app(adapter_id="upstox", openalgo_client=None)
    client = app.test_client()

    resp = client.post(
        "/api/v1/orders/smart-route",
        json={
            "symbol": "RELIANCE",
            "exchange": "NSE",
            "action": "BUY",
            "quantity": 3,
            "urgency": "high",
            "broker": "upstox",
            "account_id": "U1",
        },
    )

    assert resp.status_code == 202
    final = _wait_done(client, resp.get_json()["data"]["job_id"])
    assert final["status"] == "done"
    assert final["filled_quantity"] == 3
    assert len(adapter.orders) == 1
    assert adapter.orders[0].quantity == "3"


def test_omitted_target_uses_configured_execution_default(live_auth):
    """Direct API callers inherit brokers.execution.default when target fields are absent."""
    app, adapter = _make_app(
        adapter_id="upstox",
        openalgo_client=None,
        execution_default="upstox:U1",
    )
    client = app.test_client()

    resp = client.post(
        "/api/v1/orders/smart-route",
        json={
            "symbol": "RELIANCE",
            "exchange": "NSE",
            "action": "BUY",
            "quantity": 3,
            "urgency": "high",
        },
    )

    assert resp.status_code == 202
    final = _wait_done(client, resp.get_json()["data"]["job_id"])
    assert final["status"] == "done"
    assert len(adapter.orders) == 1
    assert adapter.orders[0].quantity == "3"
    assert adapter.sessions[0].adapter_id == "upstox"
    assert adapter.sessions[0].account_id == "U1"


def test_native_medium_urgency_fails_closed_without_openalgo_depth(live_auth):
    """Native medium urgency is depth-aware; no bridge depth means no dispatch."""
    app, adapter = _make_app(adapter_id="upstox", openalgo_client=None)
    client = app.test_client()

    resp = client.post(
        "/api/v1/orders/smart-route",
        json={
            "symbol": "RELIANCE",
            "exchange": "NSE",
            "action": "BUY",
            "quantity": 3,
            "urgency": "medium",
            "broker": "upstox",
            "account_id": "U1",
        },
    )

    assert resp.status_code == 202
    final = _wait_done(client, resp.get_json()["data"]["job_id"])
    assert final["status"] == "error"
    assert "no market depth available" in final["error"]
    assert adapter.orders == []


def test_twap_splits_into_gated_slices(live_auth):
    """Low urgency TWAP: each slice is its own independently gated child."""
    app, adapter = _make_app()  # twap_slices=2, window=1s
    client = app.test_client()

    resp = client.post(
        "/api/v1/orders/smart-route",
        json={
            "symbol": "RELIANCE", "exchange": "NSE", "action": "SELL",
            "quantity": 10, "urgency": "low",
        },
    )
    assert resp.status_code == 202
    job_id = resp.get_json()["data"]["job_id"]

    final = _wait_done(client, job_id)
    assert final["status"] == "done"
    assert final["filled_quantity"] == 10
    assert [c["status"] for c in final["child_orders"]] == ["placed", "placed"]
    # Two distinct gated dispatches — one SafetyContext each (the one-shot
    # gate cannot be reused, so two placements REQUIRE two mints).
    assert len(adapter.orders) == 2
    assert sorted(int(o.quantity) for o in adapter.orders) == [5, 5]


def test_twap_resolves_a_rebuilt_router_before_its_next_child(live_auth):
    app, stale_adapter = _make_app()
    client = app.test_client()
    response = client.post(
        "/api/v1/orders/smart-route",
        json={
            "symbol": "RELIANCE",
            "exchange": "NSE",
            "action": "BUY",
            "quantity": 10,
            "urgency": "low",
        },
    )
    assert response.status_code == 202
    job_id = response.get_json()["data"]["job_id"]

    deadline = time.monotonic() + 5.0
    while time.monotonic() < deadline and not stale_adapter.orders:
        time.sleep(0.02)
    assert len(stale_adapter.orders) == 1

    stale_router = app.config["BROKER_ROUTER"]
    current_adapter = _NoIoAdapter()
    app.config["BROKER_ROUTER"] = BrokerRouter({"openalgo": current_adapter}, _session)
    assert stale_router.revoke_and_drain(timeout=0.5) is True

    final = _wait_done(client, job_id)
    assert final["status"] == "done"
    assert len(stale_adapter.orders) == 1
    assert len(current_adapter.orders) == 1


def test_status_shows_children_mid_flight(live_auth):
    """The live snapshot must expose children WHILE the route runs — TWAP
    jobs take minutes and the widget polls. Pins the result_observer wiring
    (deleting it would keep every end-state test green while live polling
    silently regressed to an empty list until completion)."""
    app, _adapter = _make_app()  # twap window 1s / 2 slices
    client = app.test_client()

    resp = client.post(
        "/api/v1/orders/smart-route",
        json={
            "symbol": "RELIANCE", "exchange": "NSE", "action": "BUY",
            "quantity": 10, "urgency": "low",
        },
    )
    job_id = resp.get_json()["data"]["job_id"]

    saw_mid_flight_child = False
    deadline = time.monotonic() + 5.0
    while time.monotonic() < deadline:
        data = client.get(f"/api/v1/orders/smart-route/{job_id}").get_json()["data"]
        if data["status"] == "running" and len(data["child_orders"]) >= 1:
            saw_mid_flight_child = True
            break
        if data["status"] != "running":
            break
        time.sleep(0.02)
    assert saw_mid_flight_child, "snapshot never showed children mid-flight (result_observer regressed)"
    _wait_done(client, job_id)


def test_app_factory_wires_smart_routing_from_workspace(monkeypatch):
    """create_flask_app must carry workspace brokers.smart_routing into
    app.config — a wiring typo would leave the feature permanently disabled
    with every route test green (they set the config key directly)."""
    import flinttrade_core.app as app_mod
    from flinttrade_core.workspace_migrations import default_workspace_config

    brokers = default_workspace_config()["brokers"]
    brokers["smart_routing"] = {"enabled": True, "twap_slices": 3, "twap_window_seconds": 60}
    monkeypatch.setattr(app_mod, "_read_workspace_brokers", lambda: brokers)

    app = app_mod.create_flask_app()
    assert app.config["SMART_ROUTING"]["enabled"] is True
    assert app.config["SMART_ROUTING"]["twap_slices"] == 3


def test_jobs_list_returns_snapshots(live_auth):
    app, _ = _make_app()
    client = app.test_client()
    resp = client.post(
        "/api/v1/orders/smart-route",
        json={
            "symbol": "RELIANCE", "exchange": "NSE", "action": "BUY",
            "quantity": 4, "urgency": "high",
        },
    )
    job_id = resp.get_json()["data"]["job_id"]
    _wait_done(client, job_id)

    listing = client.get("/api/v1/orders/smart-route")
    assert listing.status_code == 200
    jobs = listing.get_json()["data"]
    assert jobs[0]["job_id"] == job_id
    assert jobs[0]["symbol"] == "RELIANCE"


# ---------------------------------------------------------------------------
# GatedChildExecutor unit behaviour (fail-closed per child)
# ---------------------------------------------------------------------------


def _child_order(qty: int = 10) -> Order:
    return Order(
        symbol="RELIANCE",
        exchange=Exchange("NSE"),
        action=Action("BUY"),
        pricetype=PriceType.MARKET,
        quantity=str(qty),
        strategy="smart-route",
        product="MIS",
    )


def _ctx() -> RequestContext:
    return RequestContext(
        jti="jti-1", actor_type="human", actor_id="user-1", mode="live",
        selector="openalgo:default",
    )


async def _async_value(value):
    """Wrap a value in a coroutine (for portfolio_state_provider stubs)."""
    return value


async def test_executor_blocks_child_on_safety_layer():
    """A child failing L1–L5 returns a failed decision and never dispatches."""

    class _BlockingSafety:
        def check_order(self, order, **kwargs):
            class _R:
                passed = False
                layer = "L2"
                reason = "position limit"
            return [_R()]

    adapter = _NoIoAdapter()
    executor = mod.GatedChildExecutor(
        safety=_BlockingSafety(),
        router=BrokerRouter({"openalgo": adapter}, _session),
        request_ctx=_ctx(),
        adapter_id="openalgo",
        account_id="default",
    )
    decision = await executor.route_order(_child_order())
    assert decision.passed is False
    assert "L2" in decision.error
    assert adapter.orders == []


async def test_executor_fails_closed_on_router_refusal():
    """A SafetyBypassError from the router becomes a failed child, not a crash."""

    class _RefusingRouter:
        async def place_order(self, *args, **kwargs):
            raise SafetyBypassError("verification failed")

    executor = mod.GatedChildExecutor(
        safety=_safety(),
        router=_RefusingRouter(),
        request_ctx=_ctx(),
        adapter_id="openalgo",
        account_id="default",
    )
    decision = await executor.route_order(_child_order())
    assert decision.passed is False
    assert "verification failed" in decision.error


async def test_executor_passes_real_gate_and_returns_orderid():
    adapter = _NoIoAdapter()
    executor = mod.GatedChildExecutor(
        safety=_safety(),
        router=BrokerRouter({"openalgo": adapter}, _session),
        request_ctx=_ctx(),
        adapter_id="openalgo",
        account_id="default",
    )
    decision = await executor.route_order(_child_order())
    assert decision.passed is True
    assert decision.order_response.orderid == "OID-1"
    assert len(adapter.orders) == 1


async def test_executor_resolves_the_current_router_for_each_child():
    stale_adapter = _NoIoAdapter()
    current_adapter = _NoIoAdapter()
    stale_router = BrokerRouter({"openalgo": stale_adapter}, _session)
    current_router = stale_router
    executor = mod.GatedChildExecutor(
        safety=_safety(),
        router=stale_router,
        router_provider=lambda: current_router,
        request_ctx=_ctx(),
        adapter_id="openalgo",
        account_id="default",
    )

    first = await executor.route_order(_child_order(1))
    current_router = BrokerRouter({"openalgo": current_adapter}, _session)
    second = await executor.route_order(_child_order(2))

    assert first.passed is True
    assert second.passed is True
    assert [order.quantity for order in stale_adapter.orders] == ["1"]
    assert [order.quantity for order in current_adapter.orders] == ["2"]


async def test_executor_fails_closed_when_current_router_was_removed():
    stale_adapter = _NoIoAdapter()
    stale_router = BrokerRouter({"openalgo": stale_adapter}, _session)
    current_router = None
    executor = mod.GatedChildExecutor(
        safety=_safety(),
        router=stale_router,
        router_provider=lambda: current_router,
        request_ctx=_ctx(),
        adapter_id="openalgo",
        account_id="default",
    )

    decision = await executor.route_order(_child_order())

    assert decision.passed is False
    assert "verification failed" in decision.error
    assert stale_adapter.orders == []


async def test_executor_enforces_l2_from_portfolio_provider():
    """A portfolio_state_provider returning ≥ max positions blocks the child
    at L2 (the gated-executor paths now enforce cumulative exposure too)."""
    from flinttrade_core.models import Position

    adapter = _NoIoAdapter()
    executor = mod.GatedChildExecutor(
        safety=SafetySystem(SafetyConfig(check_market_hours=False, max_positions=1)),
        router=BrokerRouter({"openalgo": adapter}, _session),
        request_ctx=_ctx(),
        adapter_id="openalgo",
        account_id="default",
        portfolio_state_provider=lambda: _async_value(
            ([Position(symbol="INFY", exchange="NSE", quantity="50")], 0.0, 0.0)
        ),
    )
    decision = await executor.route_order(_child_order())
    assert decision.passed is False
    assert "L2_POSITION" in decision.error
    assert adapter.orders == []  # blocked before any dispatch


async def test_executor_l2_provider_failure_does_not_block():
    """A failing provider yields empty L2 state → the child still dispatches."""
    adapter = _NoIoAdapter()

    async def _boom() -> tuple:
        raise RuntimeError("broker down")

    executor = mod.GatedChildExecutor(
        safety=_safety(),
        router=BrokerRouter({"openalgo": adapter}, _session),
        request_ctx=_ctx(),
        adapter_id="openalgo",
        account_id="default",
        portfolio_state_provider=_boom,
    )
    decision = await executor.route_order(_child_order())
    assert decision.passed is True
    assert len(adapter.orders) == 1


async def test_gather_portfolio_state_scoped_to_selector():
    """The async gatherer reads OpenAlgo only for OpenAlgo selectors."""
    from types import SimpleNamespace

    from flinttrade_core.models import Position

    class _Client:
        async def positionbook(self):
            return [Position(symbol="INFY", exchange="NSE", quantity="10")]

        async def funds(self):
            return SimpleNamespace(used_margin="5", total_balance="10")

    pos, used, total = await mod.gather_portfolio_state(_Client(), "openalgo")
    assert len(pos) == 1 and used == 5.0 and total == 10.0
    assert await mod.gather_portfolio_state(_Client(), "dhan") == ([], 0.0, 0.0)
    assert await mod.gather_portfolio_state(None, "openalgo") == ([], 0.0, 0.0)


async def test_gather_portfolio_state_uses_native_adapter_and_account():
    """Native smart-route/agent L2 reads use the active native selector."""
    from flinttrade_core.models import Position

    client = MagicMock()
    client.positionbook = AsyncMock(side_effect=AssertionError("must not read OpenAlgo for native L2"))
    client.funds = AsyncMock(side_effect=AssertionError("must not read OpenAlgo for native L2"))

    session = object()
    registry = MagicMock()
    registry.get_session_for.return_value = session
    adapter = MagicMock()
    adapter.positions = AsyncMock(return_value=[Position(symbol="TCS", exchange="NSE", quantity="25")])
    adapter.funds = AsyncMock(return_value={"used_margin": "9", "total_balance": "10"})

    pos, used, total = await mod.gather_portfolio_state(
        client,
        "dhan",
        account_id="D1",
        native_adapters={"dhan": adapter},
        registry=registry,
    )

    assert pos[0].quantity == "25"
    assert used == 9.0
    assert total == 10.0
    registry.get_session_for.assert_called_once_with("dhan", "D1")
    adapter.positions.assert_awaited_once_with(session)
    adapter.funds.assert_awaited_once_with(session)
    client.positionbook.assert_not_awaited()
    client.funds.assert_not_awaited()


async def test_executor_pre_dispatch_check_aborts_before_the_gate():
    """A failing pre-dispatch check (revocation/cancel) raises SmartRouteAbort
    BEFORE any safety/gate/broker work — the adapter must never be touched."""
    from flinttrade_engine.smart_router import SmartRouteAbort

    adapter = _NoIoAdapter()
    executor = mod.GatedChildExecutor(
        safety=_safety(),
        router=BrokerRouter({"openalgo": adapter}, _session),
        request_ctx=_ctx(),
        adapter_id="openalgo",
        account_id="default",
        pre_dispatch_check=lambda: "session token revoked (logout or mode change)",
    )
    with pytest.raises(SmartRouteAbort, match="revoked"):
        await executor.route_order(_child_order())
    assert adapter.orders == []


async def test_executor_rechecks_cancel_after_awaited_portfolio_read():
    """Cancellation during L2 collection is an order barrier, not a hint."""
    from flinttrade_engine.smart_router import SmartRouteAbort

    adapter = _NoIoAdapter()
    provider_started = asyncio.Event()
    release_provider = asyncio.Event()
    cancel_reason: list[str] = []

    async def _blocked_portfolio_state():
        provider_started.set()
        await release_provider.wait()
        return [], 0.0, 0.0

    executor = mod.GatedChildExecutor(
        safety=_safety(),
        router=BrokerRouter({"openalgo": adapter}, _session),
        request_ctx=_ctx(),
        adapter_id="openalgo",
        account_id="default",
        pre_dispatch_check=lambda: cancel_reason[0] if cancel_reason else None,
        portfolio_state_provider=_blocked_portfolio_state,
    )

    pending = asyncio.create_task(executor.route_order(_child_order()))
    await provider_started.wait()
    cancel_reason.append("cancelled by operator")
    release_provider.set()

    with pytest.raises(SmartRouteAbort, match="cancelled"):
        await pending
    assert adapter.orders == []


def test_shutdown_owns_running_jobs_and_closes_new_submissions(live_auth):
    """Runtime shutdown cancels and joins workers before routing retirement."""
    app, adapter = _make_app()
    job = mod._SmartJob(job_id="owned-worker", params={"symbol": "INFY", "action": "BUY"})  # noqa: SLF001
    worker_started = threading.Event()

    def _worker() -> None:
        worker_started.set()
        while not job.cancel_requested:
            time.sleep(0.001)
        job.status = "cancelled"

    worker = threading.Thread(target=_worker, name="test-smart-route-owner", daemon=True)
    job.worker = worker
    mod._store_job(job)  # noqa: SLF001
    worker.start()
    assert worker_started.wait(timeout=1)

    assert mod.shutdown_smart_order_jobs(timeout=1) is True
    assert worker.is_alive() is False
    assert job.cancel_requested is True

    response = app.test_client().post(
        "/api/v1/orders/smart-route",
        json={
            "symbol": "RELIANCE",
            "exchange": "NSE",
            "action": "BUY",
            "quantity": 1,
            "urgency": "high",
        },
    )
    assert response.status_code == 503
    assert adapter.orders == []


# ---------------------------------------------------------------------------
# Mid-flight brakes: cancellation + revocation
# ---------------------------------------------------------------------------


def test_cancel_endpoint_aborts_a_running_twap(live_auth):
    """Cancelling between TWAP slices stops further children."""
    app, adapter = _make_app()  # twap window 1s / 2 slices → ~1s between slices
    client = app.test_client()

    resp = client.post(
        "/api/v1/orders/smart-route",
        json={
            "symbol": "RELIANCE", "exchange": "NSE", "action": "BUY",
            "quantity": 10, "urgency": "low",
        },
    )
    assert resp.status_code == 202
    job_id = resp.get_json()["data"]["job_id"]

    # Wait for the FIRST child to land, then cancel before the second slice.
    deadline = time.monotonic() + 5.0
    while time.monotonic() < deadline and len(adapter.orders) == 0:
        time.sleep(0.02)
    assert len(adapter.orders) >= 1

    cancel = client.post(f"/api/v1/orders/smart-route/{job_id}/cancel")
    assert cancel.status_code == 200
    assert cancel.get_json()["data"]["cancel_requested"] is True

    final = _wait_done(client, job_id)
    assert final["status"] == "cancelled"
    assert "cancelled" in final["error"]
    assert len(adapter.orders) == 1  # the second slice never dispatched


def test_revoked_jti_aborts_mid_route(live_auth, monkeypatch):
    """Logout / mode-downgrade revoke the jti — a running job must stop."""
    import flinttrade_core.auth_routes as auth_routes_mod

    monkeypatch.setattr(auth_routes_mod, "_is_jti_revoked", lambda jti: True)
    app, adapter = _make_app()
    client = app.test_client()

    resp = client.post(
        "/api/v1/orders/smart-route",
        json={
            "symbol": "RELIANCE", "exchange": "NSE", "action": "BUY",
            "quantity": 10, "urgency": "high",
        },
    )
    assert resp.status_code == 202
    final = _wait_done(client, resp.get_json()["data"]["job_id"])
    assert final["status"] == "error"
    assert "revoked" in final["error"]
    assert adapter.orders == []  # not a single child reached the broker


def test_cancel_unknown_job_404(live_auth):
    app, _ = _make_app()
    resp = app.test_client().post("/api/v1/orders/smart-route/nope/cancel")
    assert resp.status_code == 404


# ---------------------------------------------------------------------------
# Concurrency cap + duplicate guard + eviction safety
# ---------------------------------------------------------------------------


def test_running_job_cap_409(live_auth):
    app, _ = _make_app()
    for i in range(mod._MAX_RUNNING_JOBS):  # noqa: SLF001
        mod._store_job(mod._SmartJob(job_id=f"running-{i}", params={"symbol": f"S{i}", "action": "BUY"}))  # noqa: SLF001
    resp = app.test_client().post(
        "/api/v1/orders/smart-route",
        json={"symbol": "RELIANCE", "exchange": "NSE", "action": "BUY", "quantity": 5},
    )
    assert resp.status_code == 409
    assert "Too many" in resp.get_json()["message"]


def test_dup_guard_is_atomic_with_insert(live_auth):
    """The cap/dup check and the job insert happen in ONE lock section, so a
    job registered before the executor is built already blocks a duplicate —
    closing the check-then-insert TOCTOU window."""
    app, _ = _make_app()
    client = app.test_client()
    # First submit registers the job atomically (status "running").
    r1 = client.post(
        "/api/v1/orders/smart-route",
        json={"symbol": "RELIANCE", "exchange": "NSE", "action": "BUY", "quantity": 10, "urgency": "low"},
    )
    assert r1.status_code == 202
    # An immediate duplicate sees the already-registered running job and is refused.
    r2 = client.post(
        "/api/v1/orders/smart-route",
        json={"symbol": "RELIANCE", "exchange": "NSE", "action": "BUY", "quantity": 10, "urgency": "low"},
    )
    assert r2.status_code == 409
    _wait_done(client, r1.get_json()["data"]["job_id"])


def test_duplicate_symbol_action_409(live_auth):
    app, _ = _make_app()
    mod._store_job(mod._SmartJob(job_id="dup-1", params={"symbol": "RELIANCE", "action": "BUY"}))  # noqa: SLF001
    resp = app.test_client().post(
        "/api/v1/orders/smart-route",
        json={"symbol": "RELIANCE", "exchange": "NSE", "action": "BUY", "quantity": 5},
    )
    assert resp.status_code == 409
    assert "already running" in resp.get_json()["message"]
    # The OPPOSITE side is not a duplicate.
    resp2 = app.test_client().post(
        "/api/v1/orders/smart-route",
        json={"symbol": "RELIANCE", "exchange": "NSE", "action": "SELL", "quantity": 5, "urgency": "high"},
    )
    assert resp2.status_code == 202


def test_store_eviction_never_drops_a_running_job():
    """FIFO eviction must skip running jobs — deleting one orphans a live
    worker whose children keep placing with no observability."""
    running = mod._SmartJob(job_id="run-0", params={})  # status defaults to running
    mod._store_job(running)  # noqa: SLF001
    for i in range(mod._MAX_JOBS + 5):  # noqa: SLF001
        done = mod._SmartJob(job_id=f"done-{i}", params={})
        done.status = "done"
        mod._store_job(done)  # noqa: SLF001
    with mod._JOBS_LOCK:  # noqa: SLF001
        assert "run-0" in mod._JOBS  # noqa: SLF001
        assert len(mod._JOBS) <= mod._MAX_JOBS + 1  # noqa: SLF001


# ---------------------------------------------------------------------------
# Auth on read endpoints
# ---------------------------------------------------------------------------


def test_status_endpoints_require_auth(monkeypatch):
    monkeypatch.setattr(order_routes_mod, "_decode_request_payload", lambda: None)
    app, _ = _make_app()
    client = app.test_client()
    assert client.get("/api/v1/orders/smart-route").status_code == 401
    assert client.get("/api/v1/orders/smart-route/xyz").status_code == 401
    assert client.post("/api/v1/orders/smart-route/xyz/cancel").status_code == 401


# ---------------------------------------------------------------------------
# One-shot gate: distinct mints per child (strengthened)
# ---------------------------------------------------------------------------


def test_twap_children_use_distinct_safety_contexts(live_auth):
    """Each TWAP child must carry its OWN SafetyContext object — the one-shot
    gate cannot be reused, so reuse would fail the second child."""
    from flinttrade_engine.safety import SafetyContext

    app, adapter = _make_app()
    router = app.config["BROKER_ROUTER"]
    seen_ctx: list[object] = []
    orig_place = router.place_order

    async def spying_place(ctx, **kwargs):
        seen_ctx.append(kwargs.get("safety_ctx"))
        return await orig_place(ctx, **kwargs)

    router.place_order = spying_place
    client = app.test_client()

    resp = client.post(
        "/api/v1/orders/smart-route",
        json={
            "symbol": "RELIANCE", "exchange": "NSE", "action": "SELL",
            "quantity": 10, "urgency": "low",
        },
    )
    assert resp.status_code == 202
    final = _wait_done(client, resp.get_json()["data"]["job_id"])
    assert final["status"] == "done"
    assert len(seen_ctx) == 2
    assert all(isinstance(c, SafetyContext) for c in seen_ctx)
    assert seen_ctx[0] is not seen_ctx[1]
