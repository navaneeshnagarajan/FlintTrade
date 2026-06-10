"""Tests for the smart-order routing endpoints (/api/v1/orders/smart-route).

The critical property under test: every CHILD order the SmartOrderRouter
emits traverses the REAL gated execution path — a genuine ``gate_order``
mint verified and consumed by a genuine :class:`BrokerRouter` in front of a
no-I/O adapter guarded by the module-private router token. No mocked gate.
"""

from __future__ import annotations

import time
from datetime import datetime, timezone

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

    async def place_order(self, session: object, order: object, *, _router_token: object = None) -> str:
        if _router_token is not _ROUTER_TOKEN:
            raise SafetyBypassError("adapter write method called outside BrokerRouter")
        self.orders.append(order)
        return f"OID-{len(self.orders)}"


def _session(_ctx: object, _adapter_id: str, _account_id: str) -> Session:
    return Session(
        access_token="tok",
        expires_at=datetime.now(tz=timezone.utc).timestamp() + 3600,
        account_id="default",
        adapter_id="openalgo",
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


def _make_app(*, enabled: bool = True, adapter: _NoIoAdapter | None = None) -> tuple[Flask, _NoIoAdapter]:
    adapter = adapter or _NoIoAdapter()
    app = Flask(__name__)
    app.config["TESTING"] = True
    app.config["SMART_ROUTING"] = {"enabled": enabled, "twap_window_seconds": 1, "twap_slices": 2}
    app.config["BROKER_ROUTER"] = BrokerRouter({"openalgo": adapter}, _session)
    app.config["OPENALGO_CLIENT"] = _FakeClient(asks=[(100.0, 500)], bids=[(99.5, 500)])
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


async def test_executor_blocks_child_on_safety_layer():
    """A child failing L1–L5 returns a failed decision and never dispatches."""

    class _BlockingSafety:
        def check_order(self, order):
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
