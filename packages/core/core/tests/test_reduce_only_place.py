"""Reduce-only exits on POST /api/v1/orders/place.

The server decides. A client flag is ignored. Practice closes run while
Laya is Down. Live still enters SafetySystem after a proven exit.
"""

from __future__ import annotations

import json
import threading
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest
from flask import Flask

from flinttrade_core.auth_routes import _create_token
from flinttrade_core.order_routes import orders_bp, place_order
from flinttrade_engine.laya import LAYA_DOWN_REASON, DecisionStatus, process_laya, reset_process_laya_for_tests
from flinttrade_engine.reduce_only import (
    exit_already_pending_message,
    exit_orders_unreadable_message,
    classify_reduce_only,
    reset_reduce_only_for_tests,
)
from flinttrade_engine.safety import SafetyConfig, SafetySystem, set_safety_gate_secret

_SECRET = b"0123456789abcdef0123456789abcdef"


@pytest.fixture(autouse=True)
def _down_laya() -> None:
    set_safety_gate_secret(_SECRET)
    reset_process_laya_for_tests()
    reset_reduce_only_for_tests()
    yield
    reset_process_laya_for_tests()
    reset_reduce_only_for_tests()


def _headers(mode: str, *, unlocked: bool = False) -> dict[str, str]:
    token = _create_token("operator", mode=mode, live_mode_unlocked=unlocked)
    return {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}


def _practice_app(engine: object) -> Flask:
    app = Flask(__name__)
    app.config["TESTING"] = True
    app.config["DATA_SANDBOX_ENGINE"] = engine
    app.register_blueprint(orders_bp)
    return app


def _order(symbol: str, action: str, quantity: int, price: float = 100.0) -> dict[str, object]:
    return {
        "symbol": symbol,
        "exchange": "NSE",
        "action": action,
        "quantity": quantity,
        "price": price,
        "price_basis": "ltp",
        "product": "MIS",
        "order_type": "MARKET",
    }


def _seed(engine: object, positions: list[dict[str, object]], orders: list[dict[str, object]] | None = None) -> None:
    engine.import_data(json.dumps({
        "schema_version": 2,
        "capital": {"initial": 1_000_000.0, "current": 1_000_000.0},
        "positions": positions,
        "orders": orders or [],
        "trades": [],
        "pnl_history": [],
    }))


@pytest.mark.unit
def test_practice_close_of_a_long_and_a_short_succeeds_while_laya_is_down() -> None:
    from flinttrade_data.sandbox_engine import SandboxEngine

    engine = SandboxEngine(db_path=":memory:")
    _seed(engine, [
        {
            "symbol": "INFY",
            "exchange": "NSE",
            "product": "MIS",
            "net_qty": 10,
            "avg_price": 100.0,
            "buy_qty": 10,
            "buy_value": 1000.0,
        },
        {
            "symbol": "TCS",
            "exchange": "NSE",
            "product": "MIS",
            "net_qty": -8,
            "avg_price": 200.0,
            "sell_qty": 8,
            "sell_value": 1600.0,
        },
    ])
    client = _practice_app(engine).test_client()
    assert process_laya().status is DecisionStatus.DOWN

    long_close = client.post("/api/v1/orders/place", json=_order("INFY", "SELL", 10, 110.0), headers=_headers("practice"))
    short_close = client.post("/api/v1/orders/place", json=_order("TCS", "BUY", 8, 190.0), headers=_headers("practice"))
    assert long_close.status_code == 200, long_close.get_json()
    assert short_close.status_code == 200, short_close.get_json()
    assert engine.get_positions() == []
    proofs = [row.proof_kind for row in process_laya().decision_log()]
    assert proofs == ["reduce_only", "reduce_only"]


@pytest.mark.unit
def test_oversized_practice_close_while_down_is_refused() -> None:
    from flinttrade_data.sandbox_engine import SandboxEngine

    engine = SandboxEngine(db_path=":memory:")
    _seed(engine, [{
        "symbol": "INFY",
        "exchange": "NSE",
        "product": "MIS",
        "net_qty": 10,
        "avg_price": 100.0,
        "buy_qty": 10,
        "buy_value": 1000.0,
    }])
    client = _practice_app(engine).test_client()
    response = client.post(
        "/api/v1/orders/place",
        json={**_order("INFY", "SELL", 11, 110.0), "reduce_only": True},
        headers=_headers("practice"),
    )
    body = response.get_json()
    assert response.status_code == 403
    assert body["code"] == "laya_denied"
    assert body["reason"] == LAYA_DOWN_REASON
    assert engine.get_positions()[0]["net_qty"] == 10
    assert process_laya().decision_log() == ()


@pytest.mark.unit
def test_a_second_practice_exit_is_refused_while_one_is_pending() -> None:
    from flinttrade_data.sandbox_engine import SandboxEngine

    engine = SandboxEngine(db_path=":memory:")
    _seed(
        engine,
        [{
            "symbol": "INFY",
            "exchange": "NSE",
            "product": "MIS",
            "net_qty": 10,
            "avg_price": 100.0,
            "buy_qty": 10,
            "buy_value": 1000.0,
        }],
        [{
            "symbol": "INFY",
            "exchange": "NSE",
            "product": "MIS",
            "action": "SELL",
            "quantity": 4,
            "price": 120.0,
            "order_type": "LIMIT",
            "status": "PENDING",
            "filled_qty": 0,
        }],
    )
    client = _practice_app(engine).test_client()
    for quantity in (7, 6):
        refused = client.post(
            "/api/v1/orders/place",
            json=_order("INFY", "SELL", quantity, 110.0),
            headers=_headers("practice"),
        )
        body = refused.get_json()
        assert refused.status_code == 409, body
        assert body["code"] == "exit_pending"
        assert body["message"] == exit_already_pending_message("INFY")
        assert body["reason"] == exit_already_pending_message("INFY")
        assert engine.get_positions()[0]["net_qty"] == 10
    assert process_laya().decision_log() == ()


@pytest.mark.unit
def test_two_concurrent_closes_cannot_flip_the_position() -> None:
    from flinttrade_data.sandbox_engine import SandboxEngine

    engine = SandboxEngine(db_path=":memory:")
    _seed(engine, [{
        "symbol": "TCS",
        "exchange": "NSE",
        "product": "MIS",
        "net_qty": -10,
        "avg_price": 200.0,
        "sell_qty": 10,
        "sell_value": 2000.0,
    }])
    app = _practice_app(engine)
    barrier = threading.Barrier(2)
    statuses: list[int] = []
    lock = threading.Lock()

    def close() -> None:
        barrier.wait(timeout=5)
        with app.test_request_context(
            "/api/v1/orders/place",
            method="POST",
            json=_order("TCS", "BUY", 10, 190.0),
            headers=_headers("practice"),
        ):
            _response, status = place_order()
        with lock:
            statuses.append(status)

    threads = [threading.Thread(target=close), threading.Thread(target=close)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=10)
    assert sorted(statuses) == [200, 403]
    for row in engine.get_positions():
        assert row["net_qty"] <= 0
    assert engine.get_positions() == []


def _passing_safety() -> SafetySystem:
    safety = SafetySystem(SafetyConfig(check_market_hours=False))
    blocked = MagicMock(passed=False, layer="L1_ORDER", reason="price band")
    safety.check_order = MagicMock(return_value=[blocked])  # type: ignore[method-assign]
    return safety


def _live_app(safety: SafetySystem) -> Flask:
    app = Flask(__name__)
    app.config["TESTING"] = True
    app.config["BROKER_ROUTER"] = MagicMock()
    app.config["SAFETY"] = safety
    app.config["SAFETY_CONFIG_READY"] = True
    app.register_blueprint(orders_bp)
    return app


def _portfolio_state() -> SimpleNamespace:
    return SimpleNamespace(
        positions=[],
        used_margin=0.0,
        total_balance=100_000.0,
        daily_pnl=0.0,
        starting_capital=100_000.0,
        net_delta=0.0,
        net_vega=0.0,
        ltp_for=lambda _order: 100.0,
        admission_for=lambda _index: SimpleNamespace(
            positions=[],
            used_margin=0.0,
            net_delta=0.0,
            net_vega=0.0,
        ),
        reconciled_reservation_ids=(),
    )


@pytest.mark.unit
def test_live_broker_exit_reduces_the_cap_and_an_unreadable_book_stays_reduce_only(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from flinttrade_core import order_routes

    safety = _passing_safety()
    app = _live_app(safety)
    monkeypatch.setattr(order_routes, "_gather_safety_state", lambda *_args, **_kwargs: _portfolio_state())
    position = {"symbol": "INFY", "exchange": "NSE", "product": "MIS", "net_qty": 10}
    broker_exit = {
        "symbol": "INFY",
        "exchange": "NSE",
        "product": "MIS",
        "action": "SELL",
        "quantity": 4,
        "status": "OPEN",
        "order_id": "broker-1",
    }

    def readable(_adapter_id: str, _account_id: str):
        return [position], [], [broker_exit]

    app.config["REDUCE_ONLY_LIVE_BOOKS"] = readable
    client = app.test_client()
    headers = _headers("live", unlocked=True)
    over = client.post("/api/v1/orders/openalgo/place", json=_order("INFY", "SELL", 7, 0), headers=headers)
    assert over.status_code == 403
    assert over.get_json()["code"] == "laya_denied"
    safety.check_order.assert_not_called()

    inside = client.post("/api/v1/orders/openalgo/place", json=_order("INFY", "SELL", 6, 0), headers=headers)
    assert inside.status_code == 403
    assert "L1_ORDER" in inside.get_json()["message"]
    safety.check_order.assert_called_once()
    assert process_laya().decision_log()[-1].proof_kind == "reduce_only"

    def unreadable(_adapter_id: str, _account_id: str):
        return [position], [], None

    app.config["REDUCE_ONLY_LIVE_BOOKS"] = unreadable
    safety.check_order.reset_mock()
    assert process_laya().status is DecisionStatus.DOWN
    closed = client.post("/api/v1/orders/openalgo/place", json=_order("INFY", "SELL", 10, 0), headers=headers)
    assert closed.status_code == 403
    assert closed.get_json().get("code") != "laya_denied"
    assert "L1_ORDER" in closed.get_json()["message"]
    safety.check_order.assert_called_once()
    assert process_laya().decision_log()[-1].proof_kind == "reduce_only"


@pytest.mark.unit
def test_live_unreadable_book_is_capped_by_our_exits_and_a_second_exit_is_refused(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from flinttrade_core import order_routes

    safety = _passing_safety()
    app = _live_app(safety)
    monkeypatch.setattr(order_routes, "_gather_safety_state", lambda *_args, **_kwargs: _portfolio_state())
    position = {"symbol": "INFY", "exchange": "NSE", "product": "MIS", "net_qty": 10}
    our_exit = {
        "symbol": "INFY",
        "exchange": "NSE",
        "product": "MIS",
        "action": "SELL",
        "quantity": 4,
        "status": "PENDING",
        "order_id": "ours-1",
    }
    within = classify_reduce_only(
        symbol="INFY",
        exchange="NSE",
        product="MIS",
        action="SELL",
        quantity=6,
        positions=[position],
        our_orders=[our_exit],
        broker_orders=None,
        live=True,
    )
    assert within.qualifies is True
    assert within.pending_exits == 4
    assert within.cap == 6
    over_cap = classify_reduce_only(
        symbol="INFY",
        exchange="NSE",
        product="MIS",
        action="SELL",
        quantity=7,
        positions=[position],
        our_orders=[our_exit],
        broker_orders=None,
        live=True,
    )
    assert over_cap.qualifies is False
    assert over_cap.cap == 6

    def unreadable(_adapter_id: str, _account_id: str):
        return [position], [our_exit], None

    app.config["REDUCE_ONLY_LIVE_BOOKS"] = unreadable
    client = app.test_client()
    headers = _headers("live", unlocked=True)
    for quantity in (6, 7):
        refused = client.post(
            "/api/v1/orders/openalgo/place",
            json=_order("INFY", "SELL", quantity, 0),
            headers=headers,
        )
        body = refused.get_json()
        assert refused.status_code == 409, body
        assert body["code"] == "exit_orders_unreadable"
        assert body["message"] == exit_orders_unreadable_message("INFY")
        assert body["reason"] == exit_orders_unreadable_message("INFY")
        assert body.get("code") != "laya_denied"
    safety.check_order.assert_not_called()
    assert process_laya().decision_log() == ()


def _books(net_qty: int, orders: list[dict[str, object]] | None = None):
    position = {"symbol": "INFY", "exchange": "NSE", "product": "MIS", "net_qty": net_qty}

    def hook(_adapter_id: str, _account_id: str):
        return [position], [], orders if orders is not None else []

    return hook


@pytest.mark.unit
def test_successful_reduce_only_reservation_releases_when_the_fill_lands(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A completed exit must not keep its reservation after the position moves."""
    from flinttrade_core import order_routes

    app = _live_app(_passing_safety())
    state = {"net": 10, "orders": []}

    def hook(_adapter_id: str, _account_id: str):
        position = {"symbol": "INFY", "exchange": "NSE", "product": "MIS", "net_qty": state["net"]}
        return [position], [], state["orders"]

    app.config["REDUCE_ONLY_LIVE_BOOKS"] = hook
    monkeypatch.setattr(order_routes, "_admit_and_route_live_order", lambda *_a, **_k: (True, "OID-1"))
    client = app.test_client()
    headers = _headers("live", unlocked=True)
    first = client.post("/api/v1/orders/openalgo/place", json=_order("INFY", "SELL", 4, 0), headers=headers)
    assert first.status_code == 200, first.get_json()

    blocked = client.post("/api/v1/orders/openalgo/place", json=_order("INFY", "SELL", 6, 0), headers=headers)
    assert blocked.status_code == 409
    assert blocked.get_json()["code"] == "exit_pending"

    state["net"] = 6
    state["orders"] = [{
        "symbol": "INFY",
        "exchange": "NSE",
        "product": "MIS",
        "action": "SELL",
        "quantity": 4,
        "status": "COMPLETE",
        "order_id": "OID-1",
    }]
    remainder = client.post("/api/v1/orders/openalgo/place", json=_order("INFY", "SELL", 6, 0), headers=headers)
    assert remainder.status_code == 200, remainder.get_json()


@pytest.mark.unit
def test_reduce_only_reservation_is_scoped_to_the_broker_adapter(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Account id ``default`` on two adapters does not share one exit lock."""
    from flinttrade_core import order_routes

    app = _live_app(_passing_safety())
    app.config["REDUCE_ONLY_LIVE_BOOKS"] = _books(10)
    monkeypatch.setattr(order_routes, "_admit_and_route_live_order", lambda *_a, **_k: (True, "OID-2"))
    client = app.test_client()
    headers = _headers("live", unlocked=True)
    body = _order("INFY", "SELL", 4, 0)
    first = client.post("/api/v1/orders/openalgo/place", json=body, headers=headers)
    other = client.post("/api/v1/orders/dhan/place", json=body, headers=headers)
    assert first.status_code == 200, first.get_json()
    assert other.status_code == 200, other.get_json()
    same = client.post("/api/v1/orders/openalgo/place", json=_order("INFY", "SELL", 6, 0), headers=headers)
    assert same.status_code == 409
    assert same.get_json()["code"] == "exit_pending"


@pytest.mark.unit
def test_typed_openalgo_position_rows_can_prove_a_reduce_only_exit(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Attribute rows from a broker position book are not dropped."""
    from flinttrade_core import l2_state, order_routes

    class _Position:
        symbol = "INFY"
        exchange = "NSE"
        product = "MIS"
        net_qty = 10

    async def _read(_source: object, *names: str) -> list[object]:
        if "positionbook" in names:
            return [_Position()]
        return []

    monkeypatch.setattr(l2_state, "_read", _read)
    monkeypatch.setattr(l2_state, "_resolve_account_source", lambda *_a, **_k: object())
    monkeypatch.setattr(order_routes, "_gather_safety_state", lambda *_a, **_k: _portfolio_state())
    safety = _passing_safety()
    app = _live_app(safety)
    client = app.test_client()
    closed = client.post(
        "/api/v1/orders/openalgo/place",
        json=_order("INFY", "SELL", 10, 0),
        headers=_headers("live", unlocked=True),
    )
    assert closed.status_code == 403, closed.get_json()
    assert closed.get_json().get("code") != "laya_denied"
    assert "L1_ORDER" in closed.get_json()["message"]
    assert process_laya().decision_log()[-1].proof_kind == "reduce_only"
