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


def test_cancel_missing_orderid_returns_400() -> None:
    router = MagicMock()
    router.cancel_order = AsyncMock(return_value=None)
    client = _app(broker_router=router).test_client()
    resp = client.post("/api/v1/orders/cancel", json={}, headers=_live_headers())
    assert resp.status_code == 400
    router.cancel_order.assert_not_called()
