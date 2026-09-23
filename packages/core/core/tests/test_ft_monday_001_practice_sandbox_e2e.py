"""FT-MONDAY-001 — Practice SandboxEngine E2E + no live leak.

Acceptance lock (2026-09-20):

- Practice JWT places and records fills on the real ``SandboxEngine``
- Desk/AI read those fills from the same sandbox book
- Practice never wakes live broker / OpenAlgo / ``BrokerRouter`` handles
- A forged Live header or the routed live path cannot leak a live order

This is the product tip for tracking PR #255. Live native placement stays
frozen. Kotak Neo has no Practice sandbox and is not implemented here.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from flask import Flask

from flinttrade_core.auth_routes import _create_token
from flinttrade_engine.laya import DecisionStatus, process_laya
from flinttrade_core.order_routes import orders_bp
from flinttrade_core.rate_limiter import RateLimiter
from flinttrade_data.sandbox_engine import SandboxEngine
from flinttrade_data.sandbox_routes import data_sandbox_bp

_PRACTICE_BODY = {
    "symbol": "NIFTY",
    "exchange": "NSE",
    "action": "BUY",
    "quantity": 1,
    "price": 100.0,
    "product": "MIS",
    "order_type": "MARKET",
}


class _LivePathSentinel:
    """Fail-fast stand-in for live broker / OpenAlgo handles."""

    def __init__(self) -> None:
        self.accesses: list[str] = []

    def __getattr__(self, name: str) -> object:
        self.accesses.append(name)
        raise RuntimeError(f"live-path sentinel accessed: {name}")


@pytest.fixture(autouse=True)
def _laya_ready_for_open_place() -> None:
    """Seed Ready so this Practice proof still reaches the sandbox."""
    process_laya().set_status(DecisionStatus.READY)
    yield


def _practice_token() -> str:
    """Mint a Practice JWT against the module scratch-workspace secret."""
    return _create_token("ft-monday-001", mode="practice", live_mode_unlocked=False)


def _practice_headers(**extra: str) -> dict[str, str]:
    headers = {
        "Authorization": f"Bearer {_practice_token()}",
        "Content-Type": "application/json",
    }
    headers.update(extra)
    return headers


def _monday_app(db_path: Path) -> Flask:
    """Minimal Flask app: real sandbox + order routes + desk read routes."""
    app = Flask(__name__)
    app.config["TESTING"] = True
    app.config["DATA_SANDBOX_ENGINE"] = SandboxEngine(
        db_path=str(db_path),
        initial_capital=100_000.0,
    )
    app.config["RATE_LIMITER"] = RateLimiter(global_rate=100, per_user_rate=10)
    app.config["BROKER_ROUTER"] = _LivePathSentinel()
    app.config["CLIENT"] = _LivePathSentinel()
    app.config["OPENALGO_CLIENT"] = _LivePathSentinel()
    app.config["TICK_RECORDER"] = None
    app.register_blueprint(orders_bp)
    app.register_blueprint(data_sandbox_bp)
    return app


@pytest.fixture
def monday_app(tmp_path: Path) -> Flask:
    """Isolated Practice app with its own sandbox database."""
    return _monday_app(tmp_path / "monday-sandbox.sqlite3")


def _assert_live_path_dark(app: Flask) -> None:
    """Practice dispatch must never read live broker handles."""
    assert app.config["BROKER_ROUTER"].accesses == []
    assert app.config["CLIENT"].accesses == []
    assert app.config["OPENALGO_CLIENT"].accesses == []


@pytest.mark.unit
def test_practice_place_records_sandbox_fill_for_desk_reads(monday_app: Flask) -> None:
    """Practice place → COMPLETE fill → desk sandbox book can read it."""
    client = monday_app.test_client()
    sandbox = monday_app.config["DATA_SANDBOX_ENGINE"]

    resp = client.post(
        "/api/v1/orders/place",
        json=_PRACTICE_BODY,
        headers=_practice_headers(),
    )

    assert resp.status_code == 200
    body = resp.get_json()
    assert body["status"] == "COMPLETE"
    order_id = body["order_id"]
    assert order_id

    orders = sandbox.get_orders()
    assert len(orders) == 1
    assert orders[0]["symbol"] == "NIFTY"
    assert orders[0]["action"] == "BUY"
    assert str(orders[0]["status"]).upper() == "COMPLETE"

    trades = sandbox.get_trades()
    assert len(trades) == 1
    assert trades[0]["symbol"] == "NIFTY"
    assert str(trades[0].get("order_id") or trades[0].get("orderid") or "") == str(order_id)

    positions = sandbox.get_positions()
    assert len(positions) == 1
    assert positions[0]["symbol"] == "NIFTY"
    assert int(positions[0]["net_qty"]) == 1

    desk_orders = client.get("/v1/sandbox/orders")
    assert desk_orders.status_code == 200
    desk_order_rows = desk_orders.get_json()["data"]["orders"]
    assert len(desk_order_rows) == 1
    assert desk_order_rows[0]["order_id"] == order_id

    desk_trades = client.get("/v1/sandbox/trades")
    assert desk_trades.status_code == 200
    assert len(desk_trades.get_json()["data"]["trades"]) == 1

    desk_positions = client.get("/v1/sandbox/positions")
    assert desk_positions.status_code == 200
    assert len(desk_positions.get_json()["data"]["positions"]) == 1

    _assert_live_path_dark(monday_app)


@pytest.mark.unit
def test_practice_path_cannot_submit_live_broker_orders(monday_app: Flask) -> None:
    """A Practice JWT cannot retarget Live or wake the routed live path."""
    client = monday_app.test_client()
    sandbox = monday_app.config["DATA_SANDBOX_ENGINE"]

    forged = client.post(
        "/api/v1/orders/place",
        json=_PRACTICE_BODY,
        headers=_practice_headers(**{"X-FlintTrade-Mode": "live"}),
    )
    assert forged.status_code == 403
    assert "mode" in forged.get_json()["message"].lower()
    assert sandbox.get_orders() == []
    assert sandbox.get_trades() == []

    routed = client.post(
        "/api/v1/orders/dhan/place",
        json=_PRACTICE_BODY,
        headers=_practice_headers(),
    )
    assert routed.status_code in (400, 403)
    assert sandbox.get_orders() == []
    assert sandbox.get_trades() == []

    _assert_live_path_dark(monday_app)
