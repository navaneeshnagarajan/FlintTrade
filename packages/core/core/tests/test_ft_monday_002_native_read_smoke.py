"""FT-MONDAY-002 — native Dhan + Neo Connected (read) smoke + fail-closed Live.

Acceptance lock (2026-09-20):

- Dhan and Kotak Neo login + ticks/depth/latency smoke (non-funded)
- Neo v3 hist/chain where the SDK allows; Neo never Practice
- Chrome is Connected (read) / API smoke — never placeable Live orders
- Live place stays fail-closed without funded unlock
"""

from __future__ import annotations

from pathlib import Path

import pytest
from flask import Flask

from flinttrade_core.auth_routes import _create_token
from flinttrade_core.order_routes import orders_bp
from flinttrade_core.rate_limiter import RateLimiter
from flinttrade_data.sandbox_engine import SandboxEngine
from flinttrade_gateway.monday_read_smoke import (
    CHROME_CONNECTED_READ,
    MONDAY_READ_BROKERS,
    NEO_OPERATOR_COPY,
    WRITE_VERBS,
    monday_read_chrome,
    monday_read_connectable,
    monday_read_smoke_ok,
    probe_monday_session_reads,
    run_monday_read_smoke,
    stamp_monday_read_smoke,
)


class _SmokeAdapter:
    def __init__(self, *, fail_quotes: bool = False) -> None:
        self.calls: list[str] = []
        self.fail_quotes = fail_quotes

    async def login(self, credentials: dict) -> object:
        self.calls.append("login")
        assert credentials.get("token") == "non-funded"
        return object()

    async def quotes(self, _session: object, symbols: list[str]) -> list[dict]:
        self.calls.append("quotes")
        if self.fail_quotes:
            raise RuntimeError("quote probe failed")
        return [{"symbol": symbols[0], "ltp": 1.0}]

    async def market_depth(self, _session: object, symbols: list[str]) -> list[dict]:
        self.calls.append("depth")
        return [{"symbol": symbols[0], "bids": [], "asks": []}]

    async def historical(self, _session: object, req: dict) -> dict:
        self.calls.append("history")
        return {"bars": [], "symbol": req.get("symbol")}

    async def option_chain(self, _session: object, req: dict) -> dict:
        self.calls.append("optionchain")
        return {"strikes": [], "underlying": req.get("underlying")}

    async def place_order(self, *_a: object, **_k: object) -> None:
        self.calls.append("place_order")
        raise AssertionError("Monday read-smoke must not place")


class _LivePathSentinel:
    def __init__(self) -> None:
        self.accesses: list[str] = []

    def __getattr__(self, name: str) -> object:
        self.accesses.append(name)
        raise RuntimeError(f"live-path sentinel accessed: {name}")


def _live_token(*, unlocked: bool = False) -> str:
    return _create_token("ft-monday-002", mode="live", live_mode_unlocked=unlocked)


def _live_headers(*, unlocked: bool = False) -> dict[str, str]:
    return {
        "Authorization": f"Bearer {_live_token(unlocked=unlocked)}",
        "Content-Type": "application/json",
    }


def _monday_app(db_path: Path) -> Flask:
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
    return app


@pytest.mark.unit
@pytest.mark.parametrize("broker_id", sorted(MONDAY_READ_BROKERS))
@pytest.mark.asyncio
async def test_monday_read_smoke_connects_without_writes(broker_id: str) -> None:
    adapter = _SmokeAdapter()
    result = await run_monday_read_smoke(
        broker_id,
        adapter,
        {"token": "non-funded"},
        historical_req={"symbol": "RELIANCE", "exchange": "NSE", "interval": "D"},
        option_chain_req={"underlying": "NIFTY", "exchange": "NFO"},
    )
    assert result.ok is True
    assert result.chrome == CHROME_CONNECTED_READ
    assert {step.name for step in result.steps if step.ok} >= {"login", "quotes", "depth"}
    assert "place_order" not in adapter.calls
    assert not any(verb in adapter.calls for verb in WRITE_VERBS)
    if broker_id == "kotakneo":
        assert result.operator_copy == NEO_OPERATOR_COPY
        assert "history" in adapter.calls
        assert "optionchain" in adapter.calls
    else:
        assert result.operator_copy is None


@pytest.mark.unit
@pytest.mark.asyncio
async def test_failed_read_never_paints_connected() -> None:
    adapter = _SmokeAdapter(fail_quotes=True)
    result = await run_monday_read_smoke("dhan", adapter, {"token": "non-funded"})
    assert result.ok is False
    assert result.chrome == ""
    assert monday_read_chrome("dhan", connected=True, reads_ok=False) is None
    assert "place_order" not in adapter.calls


@pytest.mark.unit
def test_live_place_stays_fail_closed_without_funded_unlock(tmp_path: Path) -> None:
    app = _monday_app(tmp_path / "monday-002.sqlite3")
    client = app.test_client()
    body = {
        "symbol": "RELIANCE",
        "exchange": "NSE",
        "action": "BUY",
        "quantity": 1,
        "price": 100.0,
        "product": "MIS",
        "order_type": "MARKET",
    }
    locked = client.post("/api/v1/orders/place", json=body, headers=_live_headers(unlocked=False))
    assert locked.status_code == 403
    assert "live mode not unlocked" in locked.get_json()["message"].lower()
    assert app.config["BROKER_ROUTER"].accesses == []
    assert app.config["CLIENT"].accesses == []
    assert app.config["OPENALGO_CLIENT"].accesses == []


@pytest.mark.unit
def test_neo_has_no_practice_sandbox_copy() -> None:
    assert "Practice" not in NEO_OPERATOR_COPY
    assert monday_read_chrome("kotakneo", connected=True, reads_ok=True) == CHROME_CONNECTED_READ
    assert monday_read_chrome("upstox", connected=True, reads_ok=True) is None
    assert monday_read_connectable("kotakneo", False) is True
    assert monday_read_connectable("dhan", False) is True
    assert monday_read_connectable("groww", False) is False


@pytest.mark.unit
@pytest.mark.asyncio
async def test_chrome_requires_stamped_read_smoke() -> None:
    class _Session:
        def __init__(self) -> None:
            self.extra: dict = {}

    adapter = _SmokeAdapter()
    session = _Session()
    assert monday_read_smoke_ok(session) is False
    assert monday_read_chrome("kotakneo", connected=True, reads_ok=False) is None
    ok = await probe_monday_session_reads(adapter, session)
    assert ok is True
    assert monday_read_smoke_ok(session) is True
    stamp_monday_read_smoke(session, False)
    assert monday_read_smoke_ok(session) is False
