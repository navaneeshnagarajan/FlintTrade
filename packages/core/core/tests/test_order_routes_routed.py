"""T7 (gap G5) + C1/M1: the selector-bound, safety-gated live order path.

Covers the ``/api/v1/orders/<broker>/place`` route's auth + routing-availability
gates AND the C1 fail-closed status mapping (SafetyBypassError -> 403,
BrokerNotFoundError -> 503, safety-layer block -> 403, bad body -> 400, happy
path -> 200) now that both the routed endpoint and the legacy ``/place`` flow
through the shared ``_dispatch_live_order`` helper.

A minimal Flask app (no full create_flask_app) with a mocked BrokerRouter +
SafetySystem is sufficient because the JWT secret is a process-global lazily
loaded by ``auth_routes._get_jwt_secret`` (no app context required).
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest
from flask import Flask

from flinttrade_core.auth_routes import _create_token
from flinttrade_core.exceptions import SafetyBypassError
from flinttrade_core.order_routes import orders_bp
from flinttrade_engine.safety import set_safety_gate_secret
from flinttrade_gateway.exceptions import BrokerNotFoundError

_SECRET = b"0123456789abcdef0123456789abcdef"  # 32 bytes

_LIVE_BODY = {
    "symbol": "RELIANCE",
    "exchange": "NSE",
    "action": "BUY",
    "quantity": 1,
    "price": 0,
    "product": "MIS",
    "order_type": "MARKET",
}


@pytest.fixture(autouse=True)
def _bind_secret() -> None:
    """Bind a deterministic safety-gate secret so gate_order can mint in tests."""
    set_safety_gate_secret(_SECRET)


def _app(broker_router: object | None = None, safety: object | None = None) -> Flask:
    app = Flask(__name__)
    app.config["BROKER_ROUTER"] = broker_router
    app.config["SAFETY"] = safety
    app.register_blueprint(orders_bp)
    return app


def _live_headers() -> dict[str, str]:
    token = _create_token("nava", mode="live", live_mode_unlocked=True)
    return {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}


def _passing_safety() -> MagicMock:
    """A SafetySystem stub whose check_order passes (no failed layers)."""
    safety = MagicMock()
    safety.check_order.return_value = []
    return safety


def _router_with_execution_default(selector: str) -> MagicMock:
    class _Execution:
        default = selector

    class _Config:
        execution = _Execution()

    router = MagicMock()
    router._config = _Config()
    return router


# ---------------------------------------------------------------------------
# Auth + registration (pre-existing)
# ---------------------------------------------------------------------------


def test_routed_order_requires_auth() -> None:
    client = _app().test_client()
    resp = client.post("/api/v1/orders/dhan/place", json={"symbol": "RELIANCE"})
    assert resp.status_code == 401


def test_routed_order_route_is_registered() -> None:
    rules = {r.rule for r in _app().url_map.iter_rules()}
    assert "/api/v1/orders/<broker>/place" in rules
    assert "/api/v1/orders/<broker>/modify" in rules
    assert "/api/v1/orders/<broker>/cancel" in rules


# ---------------------------------------------------------------------------
# C1/M1: fail-closed status mapping through _dispatch_live_order
# ---------------------------------------------------------------------------


def test_routed_order_no_broker_router_returns_503() -> None:
    client = _app(broker_router=None, safety=_passing_safety()).test_client()
    resp = client.post("/api/v1/orders/openalgo/place", json=_LIVE_BODY, headers=_live_headers())
    assert resp.status_code == 503
    assert "routing unavailable" in resp.get_json()["message"].lower()


def test_routed_order_safety_bypass_returns_403() -> None:
    router = MagicMock()
    router.place_order = AsyncMock(side_effect=SafetyBypassError("actor not authorised"))
    client = _app(broker_router=router, safety=_passing_safety()).test_client()
    resp = client.post("/api/v1/orders/openalgo/place", json=_LIVE_BODY, headers=_live_headers())
    assert resp.status_code == 403
    assert "refused" in resp.get_json()["message"].lower()


def test_routed_order_algo_tag_limit_returns_429() -> None:
    """The router's algo-tag guard refusing a dispatch (per-exchange per-second
    algo ceiling, G10) maps to 429 — a throttle refusal callers should retry,
    not a 403 safety bypass and not a 500."""
    from flinttrade_engine.algo_tag_guard import AlgoTagLimitError

    router = MagicMock()
    router.place_order = AsyncMock(side_effect=AlgoTagLimitError("dhan/NSE algo ceiling reached"))
    client = _app(broker_router=router, safety=_passing_safety()).test_client()
    resp = client.post("/api/v1/orders/openalgo/place", json=_LIVE_BODY, headers=_live_headers())
    assert resp.status_code == 429
    assert "refused" in resp.get_json()["message"].lower()


def test_routed_order_broker_not_found_returns_503() -> None:
    router = MagicMock()
    router.place_order = AsyncMock(side_effect=BrokerNotFoundError("no session for openalgo:default"))
    client = _app(broker_router=router, safety=_passing_safety()).test_client()
    resp = client.post("/api/v1/orders/openalgo/place", json=_LIVE_BODY, headers=_live_headers())
    assert resp.status_code == 503
    assert "not connected" in resp.get_json()["message"].lower()


def test_routed_order_safety_layer_block_returns_403() -> None:
    blocked = MagicMock()
    blocked.passed = False
    blocked.layer = "L5_KILL"
    blocked.reason = "Kill switch is active"
    safety = MagicMock()
    safety.check_order.return_value = [blocked]
    router = MagicMock()
    router.place_order = AsyncMock(return_value="SHOULD-NOT-REACH")
    client = _app(broker_router=router, safety=safety).test_client()
    resp = client.post("/api/v1/orders/openalgo/place", json=_LIVE_BODY, headers=_live_headers())
    assert resp.status_code == 403
    assert "L5_KILL" in resp.get_json()["message"]
    router.place_order.assert_not_called()  # blocked before any dispatch


def test_routed_order_invalid_body_returns_400() -> None:
    router = MagicMock()
    router.place_order = AsyncMock(return_value="X")
    client = _app(broker_router=router, safety=_passing_safety()).test_client()
    bad = {**_LIVE_BODY, "action": "SIDEWAYS"}  # not BUY/SELL — enum coercion fails
    resp = client.post("/api/v1/orders/openalgo/place", json=bad, headers=_live_headers())
    assert resp.status_code == 400
    assert "validation failed" in resp.get_json()["message"].lower()
    router.place_order.assert_not_called()


def test_routed_order_non_integer_quantity_returns_400() -> None:
    # A fat-finger non-integer quantity must be a clean 400, not a 500 from the
    # int(...) coercion inside SafetySystem.check_order (re-audit MEDIUM).
    router = MagicMock()
    router.place_order = AsyncMock(return_value="X")
    client = _app(broker_router=router, safety=_passing_safety()).test_client()
    bad = {**_LIVE_BODY, "quantity": "10.5"}
    resp = client.post("/api/v1/orders/openalgo/place", json=bad, headers=_live_headers())
    assert resp.status_code == 400
    assert "quantity" in resp.get_json()["message"].lower()
    router.place_order.assert_not_called()


def test_routed_happy_path_returns_200() -> None:
    router = MagicMock()
    router.place_order = AsyncMock(return_value="OA-999")
    client = _app(broker_router=router, safety=_passing_safety()).test_client()
    resp = client.post("/api/v1/orders/openalgo/place", json=_LIVE_BODY, headers=_live_headers())
    assert resp.status_code == 200
    data = resp.get_json()
    assert data["status"] == "success"
    # Both keys returned so the UI works regardless of which it reads.
    assert data["orderid"] == "OA-999"
    assert data["data"] == "OA-999"
    router.place_order.assert_awaited_once()
    # Regression guard (re-audit HIGH): the dispatched order MUST be the typed
    # Order, not the raw dict — a dict AttributeErrors at the OpenAlgoClient
    # boundary (order.symbol / order.action.value / …) and 500s every live order.
    from flinttrade_core.models import Order

    dispatched = router.place_order.await_args.kwargs["order"]
    assert isinstance(dispatched, Order)
    assert dispatched.symbol == "RELIANCE"


def test_legacy_place_uses_configured_execution_default_when_target_omitted() -> None:
    router = _router_with_execution_default("upstox:U1")
    router.place_order = AsyncMock(return_value="UP-1")
    client = _app(broker_router=router, safety=_passing_safety()).test_client()

    resp = client.post("/api/v1/orders/place", json=_LIVE_BODY, headers=_live_headers())

    assert resp.status_code == 200
    router.place_order.assert_awaited_once()
    request_ctx = router.place_order.await_args.args[0]
    kw = router.place_order.await_args.kwargs
    assert request_ctx.selector == "upstox:U1"
    assert kw["hint"].adapter_id == "upstox"
    assert kw["hint"].account_id == "U1"


# ---------------------------------------------------------------------------
# L2 enforcement from LIVE portfolio state (cumulative-exposure brake)
# ---------------------------------------------------------------------------


def _real_safety(**cfg):
    from flinttrade_engine.safety import SafetyConfig, SafetySystem

    return SafetySystem(SafetyConfig(check_market_hours=False, **cfg))


def _app_with_client(router, safety, client):
    app = _app(broker_router=router, safety=safety)
    app.config["OPENALGO_CLIENT"] = client
    return app


def _app_with_native_state(
    router,
    safety,
    *,
    adapter_id="dhan",
    account_id="D1",
    positions=None,
    funds=None,
    positions_side_effect=None,
    funds_side_effect=None,
):
    app = _app(broker_router=router, safety=safety)
    session = object()
    registry = MagicMock()
    registry.get_session_for.return_value = session
    adapter = MagicMock()
    adapter.positions = AsyncMock(side_effect=positions_side_effect, return_value=positions or [])
    adapter.funds = AsyncMock(side_effect=funds_side_effect, return_value=funds or {})
    app.config["REGISTRY"] = registry
    app.config["NATIVE_ADAPTERS"] = {adapter_id: adapter}
    return app, adapter, registry


def _fake_client(positions, used_margin="0", total_balance="0"):
    from types import SimpleNamespace

    c = MagicMock()
    c.positionbook = AsyncMock(return_value=positions)
    c.funds = AsyncMock(return_value=SimpleNamespace(used_margin=used_margin, total_balance=total_balance))
    return c


def _pos(symbol, qty):
    from flinttrade_core.models import Position

    return Position(symbol=symbol, exchange="NSE", quantity=str(qty))


def test_L2_blocks_when_at_max_positions_from_live_state() -> None:
    """With real live positions ≥ the configured max, L2 blocks the order —
    previously L2 ran on an empty list and never fired."""
    router = MagicMock()
    router.place_order = AsyncMock(return_value="X")
    safety = _real_safety(max_positions=1)
    client = _fake_client([_pos("INFY", 50)])  # already 1 open position; max is 1
    app = _app_with_client(router, safety, client)
    resp = app.test_client().post(
        "/api/v1/orders/openalgo/place", json=_LIVE_BODY, headers=_live_headers()
    )
    assert resp.status_code == 403
    assert "L2_POSITION" in resp.get_json()["message"]
    router.place_order.assert_not_called()


def test_L2_blocks_when_margin_over_limit_from_live_funds() -> None:
    router = MagicMock()
    router.place_order = AsyncMock(return_value="X")
    safety = _real_safety(max_positions=10, max_margin_pct=60.0)
    # 80% margin used → over the 60% cap.
    client = _fake_client([], used_margin="80000", total_balance="100000")
    app = _app_with_client(router, safety, client)
    resp = app.test_client().post(
        "/api/v1/orders/openalgo/place", json=_LIVE_BODY, headers=_live_headers()
    )
    assert resp.status_code == 403
    assert "Margin usage" in resp.get_json()["message"]
    router.place_order.assert_not_called()


def test_L2_float_string_quantity_tolerated() -> None:
    """A position quantity like "50.0" must not 500 the order (L2 tolerant parse)."""
    router = MagicMock()
    router.place_order = AsyncMock(return_value="OA-1")
    safety = _real_safety(max_positions=10)
    client = _fake_client([_pos("INFY", "50.0")])
    app = _app_with_client(router, safety, client)
    resp = app.test_client().post(
        "/api/v1/orders/openalgo/place", json=_LIVE_BODY, headers=_live_headers()
    )
    assert resp.status_code == 200


def test_L2_infinity_quantity_does_not_500() -> None:
    """A pathological "Infinity" position quantity must be tolerated (treated
    as unparseable → 0), not raise OverflowError out of L2 and 500 the order."""
    router = MagicMock()
    router.place_order = AsyncMock(return_value="OA-3")
    safety = _real_safety(max_positions=10)
    client = _fake_client([_pos("INFY", "Infinity")])
    app = _app_with_client(router, safety, client)
    resp = app.test_client().post(
        "/api/v1/orders/openalgo/place", json=_LIVE_BODY, headers=_live_headers()
    )
    assert resp.status_code == 200  # not a 500


def test_gather_l2_state_uses_selector_matched_broker_state() -> None:
    """_gather_l2_state must read the selector's broker account.

    OpenAlgo state is valid only for ``openalgo:*``; native selectors must use
    their active native adapter + registry session so L2 is enforced against the
    account that will receive the order.
    """
    from flinttrade_core.order_routes import _gather_l2_state

    app, adapter, registry = _app_with_native_state(
        MagicMock(),
        _passing_safety(),
        positions=[_pos("TCS", 25)],
        funds={"used_margin": "9", "total_balance": "10"},
    )
    openalgo_client = _fake_client([_pos("INFY", 50)], used_margin="90", total_balance="100")
    app.config["OPENALGO_CLIENT"] = openalgo_client
    with app.app_context():
        openalgo_positions, openalgo_used, openalgo_total = _gather_l2_state("openalgo")
        assert openalgo_positions[0].quantity == "50"
        assert openalgo_used == 90.0
        assert openalgo_total == 100.0

        openalgo_client.positionbook.reset_mock()
        openalgo_client.funds.reset_mock()

        native_positions, native_used, native_total = _gather_l2_state("dhan", account_id="D1")
        assert native_positions[0].quantity == "25"
        assert native_used == 9.0
        assert native_total == 10.0
        registry.get_session_for.assert_called_with("dhan", "D1")
        adapter.positions.assert_awaited_once()
        adapter.funds.assert_awaited_once()
        openalgo_client.positionbook.assert_not_awaited()
        openalgo_client.funds.assert_not_awaited()


def test_L2_state_fetch_failure_does_not_block_order() -> None:
    """A portfolio-state read hiccup must NOT block a live order — best-effort
    enrichment, never an availability regression."""
    router = MagicMock()
    router.place_order = AsyncMock(return_value="OA-2")
    safety = _real_safety(max_positions=1)
    client = MagicMock()
    client.positionbook = AsyncMock(side_effect=RuntimeError("broker down"))
    client.funds = AsyncMock(return_value=None)
    app = _app_with_client(router, safety, client)
    resp = app.test_client().post(
        "/api/v1/orders/openalgo/place", json=_LIVE_BODY, headers=_live_headers()
    )
    # L2 enforced nothing (empty state) → order proceeds through L1/L4/L5.
    assert resp.status_code == 200
    router.place_order.assert_awaited_once()


def test_native_L2_blocks_when_at_max_positions_from_live_state() -> None:
    """Native routed orders feed native live positions into L2 before dispatch."""
    router = MagicMock()
    router.place_order = AsyncMock(return_value="SHOULD-NOT-REACH")
    safety = _real_safety(max_positions=1)
    app, adapter, _registry = _app_with_native_state(
        router,
        safety,
        positions=[_pos("INFY", 50)],
        funds={"used_margin": "0", "total_balance": "100000"},
    )
    resp = app.test_client().post(
        "/api/v1/orders/dhan/place",
        json={**_LIVE_BODY, "account_id": "D1"},
        headers=_live_headers(),
    )
    assert resp.status_code == 403
    assert "L2_POSITION" in resp.get_json()["message"]
    router.place_order.assert_not_called()
    adapter.positions.assert_awaited_once()
    adapter.funds.assert_awaited_once()


def test_native_L2_blocks_when_margin_over_limit_from_live_funds() -> None:
    router = MagicMock()
    router.place_order = AsyncMock(return_value="SHOULD-NOT-REACH")
    safety = _real_safety(max_positions=10, max_margin_pct=60.0)
    app, adapter, _registry = _app_with_native_state(
        router,
        safety,
        positions=[],
        funds={"used_margin": "80000", "total_balance": "100000"},
    )
    resp = app.test_client().post(
        "/api/v1/orders/dhan/place",
        json={**_LIVE_BODY, "account_id": "D1"},
        headers=_live_headers(),
    )
    assert resp.status_code == 403
    assert "Margin usage" in resp.get_json()["message"]
    router.place_order.assert_not_called()
    adapter.positions.assert_awaited_once()
    adapter.funds.assert_awaited_once()


def test_native_L2_state_fetch_failure_does_not_block_order() -> None:
    router = MagicMock()
    router.place_order = AsyncMock(return_value="DH-1")
    safety = _real_safety(max_positions=1)
    app, adapter, _registry = _app_with_native_state(
        router,
        safety,
        positions_side_effect=RuntimeError("broker read unavailable"),
        funds={"used_margin": "80000", "total_balance": "100000"},
    )
    resp = app.test_client().post(
        "/api/v1/orders/dhan/place",
        json={**_LIVE_BODY, "account_id": "D1"},
        headers=_live_headers(),
    )
    assert resp.status_code == 200
    router.place_order.assert_awaited_once()
    adapter.positions.assert_awaited_once()


def test_routed_happy_path_feeds_latency_monitor(monkeypatch: pytest.MonkeyPatch) -> None:
    """H5: a successful live dispatch records per-broker order RTT.

    Without this producer the order-latency stats stayed empty forever, so the
    health monitors had nothing to show. Best-effort: the recording must never
    change the order result, but on the happy path it MUST fire once with the
    adapter id + symbol.
    """
    import flinttrade_core.monitoring_routes as mon

    tracker = MagicMock()
    monkeypatch.setattr(mon, "get_latency_tracker", lambda: tracker)

    router = MagicMock()
    router.place_order = AsyncMock(return_value="OA-999")
    client = _app(broker_router=router, safety=_passing_safety()).test_client()
    resp = client.post("/api/v1/orders/openalgo/place", json=_LIVE_BODY, headers=_live_headers())

    assert resp.status_code == 200
    tracker.record_order_latency.assert_called_once()
    args = tracker.record_order_latency.call_args.args
    assert args[0] == "openalgo"  # adapter/broker id
    assert args[1] == "RELIANCE"  # symbol
    assert isinstance(args[2], float) and args[2] >= 0.0  # latency_ms


def test_latency_recording_failure_never_breaks_the_order(monkeypatch: pytest.MonkeyPatch) -> None:
    """H5: monitoring is strictly best-effort — a tracker blow-up still 200s."""
    import flinttrade_core.monitoring_routes as mon

    def _boom() -> object:
        raise RuntimeError("tracker exploded")

    monkeypatch.setattr(mon, "get_latency_tracker", _boom)

    router = MagicMock()
    router.place_order = AsyncMock(return_value="OA-777")
    client = _app(broker_router=router, safety=_passing_safety()).test_client()
    resp = client.post("/api/v1/orders/openalgo/place", json=_LIVE_BODY, headers=_live_headers())

    assert resp.status_code == 200
    assert resp.get_json()["orderid"] == "OA-777"


# ---------------------------------------------------------------------------
# Trade journal producer — a successful live dispatch records the executed
# order in the same DuckDB store the /trades/journal route reads (was empty in
# Live because nothing ever wrote to it).
# ---------------------------------------------------------------------------


def test_routed_happy_path_journals_the_trade(tmp_path: object) -> None:
    """A successful live order is appended to the shared trade store."""
    import threading
    from datetime import datetime, timedelta, timezone

    from flinttrade_data.storage import StorageManager

    store = StorageManager(db_path=str(tmp_path / "journal.duckdb"))  # type: ignore[operator]
    store.initialise()

    router = MagicMock()
    router.place_order = AsyncMock(return_value="OA-555")
    app = _app(broker_router=router, safety=_passing_safety())
    app.config["TRADE_STORAGE"] = store
    app.config["TRADE_STORAGE_LOCK"] = threading.Lock()

    resp = app.test_client().post(
        "/api/v1/orders/openalgo/place", json=_LIVE_BODY, headers=_live_headers()
    )
    assert resp.status_code == 200

    today = datetime.now(timezone(timedelta(hours=5, minutes=30))).strftime("%Y-%m-%d")
    rows = store.get_trades_by_date(today)
    store.close()

    assert len(rows) == 1
    row = rows[0]
    assert row["orderid"] == "OA-555"
    assert row["symbol"] == "RELIANCE"
    assert row["action"] == "BUY"
    assert int(row["quantity"]) == 1
    assert row["strategy"] == "manual"


def test_journal_failure_never_breaks_the_order() -> None:
    """H-class best-effort: a journal store that raises still returns 200."""
    import threading

    bad_store = MagicMock()
    bad_store.insert_trade.side_effect = RuntimeError("duckdb is on fire")

    router = MagicMock()
    router.place_order = AsyncMock(return_value="OA-444")
    app = _app(broker_router=router, safety=_passing_safety())
    app.config["TRADE_STORAGE"] = bad_store
    app.config["TRADE_STORAGE_LOCK"] = threading.Lock()

    resp = app.test_client().post(
        "/api/v1/orders/openalgo/place", json=_LIVE_BODY, headers=_live_headers()
    )
    assert resp.status_code == 200
    assert resp.get_json()["orderid"] == "OA-444"
    bad_store.insert_trade.assert_called_once()


# ---------------------------------------------------------------------------
# Gated modify / cancel (the legacy /modify, /cancel endpoints now route through
# BrokerRouter.modify_order / cancel_order — same one-shot gate + ACL as place).
# ---------------------------------------------------------------------------

_MODIFY_BODY = {
    "orderid": "OA-1",
    "symbol": "RELIANCE",
    "exchange": "NSE",
    "action": "BUY",
    "quantity": 1,
    "price": 100,
    "product": "MIS",
    "order_type": "LIMIT",
}


def test_modify_happy_path_returns_200() -> None:
    router = MagicMock()
    router.modify_order = AsyncMock(return_value=None)
    client = _app(broker_router=router).test_client()
    resp = client.post("/api/v1/orders/modify", json=_MODIFY_BODY, headers=_live_headers())
    assert resp.status_code == 200
    assert resp.get_json()["orderid"] == "OA-1"
    router.modify_order.assert_awaited_once()
    kw = router.modify_order.await_args.kwargs
    assert kw["order_id"] == "OA-1"
    assert kw["changes"]["symbol"] == "RELIANCE"
    # The gated fingerprint is the canonical modify dict (mint == verify object).
    assert kw["order"]["_op"] == "modify"


def test_routed_modify_happy_path_targets_named_broker_account() -> None:
    router = MagicMock()
    router.modify_order = AsyncMock(return_value=None)
    client = _app(broker_router=router).test_client()
    resp = client.post(
        "/api/v1/orders/upstox/modify",
        json={**_MODIFY_BODY, "account_id": "U1"},
        headers=_live_headers(),
    )
    assert resp.status_code == 200
    router.modify_order.assert_awaited_once()
    request_ctx = router.modify_order.await_args.args[0]
    kw = router.modify_order.await_args.kwargs
    assert request_ctx.selector == "upstox:U1"
    assert kw["hint"].adapter_id == "upstox"
    assert kw["hint"].account_id == "U1"


def test_modify_missing_orderid_returns_400() -> None:
    router = MagicMock()
    router.modify_order = AsyncMock(return_value=None)
    client = _app(broker_router=router).test_client()
    body = {k: v for k, v in _MODIFY_BODY.items() if k != "orderid"}
    resp = client.post("/api/v1/orders/modify", json=body, headers=_live_headers())
    assert resp.status_code == 400
    router.modify_order.assert_not_called()


def test_modify_safety_bypass_returns_403() -> None:
    router = MagicMock()
    router.modify_order = AsyncMock(side_effect=SafetyBypassError("actor not authorised"))
    client = _app(broker_router=router).test_client()
    resp = client.post("/api/v1/orders/modify", json=_MODIFY_BODY, headers=_live_headers())
    assert resp.status_code == 403
    assert "refused" in resp.get_json()["message"].lower()


def test_cancel_happy_path_returns_200() -> None:
    router = MagicMock()
    router.cancel_order = AsyncMock(return_value=None)
    client = _app(broker_router=router).test_client()
    resp = client.post("/api/v1/orders/cancel", json={"orderid": "OA-7"}, headers=_live_headers())
    assert resp.status_code == 200
    assert resp.get_json()["orderid"] == "OA-7"
    router.cancel_order.assert_awaited_once()
    assert router.cancel_order.await_args.kwargs["order_id"] == "OA-7"


def test_routed_cancel_happy_path_targets_named_broker_account() -> None:
    router = MagicMock()
    router.cancel_order = AsyncMock(return_value=None)
    client = _app(broker_router=router).test_client()
    resp = client.post(
        "/api/v1/orders/groww/cancel",
        json={"orderid": "GW-7", "account_id": "G1", "segment": "FNO"},
        headers=_live_headers(),
    )
    assert resp.status_code == 200
    router.cancel_order.assert_awaited_once()
    request_ctx = router.cancel_order.await_args.args[0]
    kw = router.cancel_order.await_args.kwargs
    assert request_ctx.selector == "groww:G1"
    assert kw["hint"].adapter_id == "groww"
    assert kw["hint"].account_id == "G1"
    assert kw["extras"] == {"segment": "FNO"}
    assert kw["order"]["segment"] == "FNO"


def test_routed_cancel_ignores_segment_for_non_groww_brokers() -> None:
    router = MagicMock()
    router.cancel_order = AsyncMock(return_value=None)
    client = _app(broker_router=router).test_client()
    resp = client.post(
        "/api/v1/orders/upstox/cancel",
        json={"orderid": "UP-7", "account_id": "U1", "segment": "FNO"},
        headers=_live_headers(),
    )
    assert resp.status_code == 200
    kw = router.cancel_order.await_args.kwargs
    assert kw["extras"] is None
    assert "segment" not in kw["order"]


def test_cancel_missing_orderid_returns_400() -> None:
    router = MagicMock()
    router.cancel_order = AsyncMock(return_value=None)
    client = _app(broker_router=router).test_client()
    resp = client.post("/api/v1/orders/cancel", json={}, headers=_live_headers())
    assert resp.status_code == 400
    router.cancel_order.assert_not_called()
