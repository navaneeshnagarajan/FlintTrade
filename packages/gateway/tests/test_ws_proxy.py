"""Tests for the FlintTrade WebSocket proxy subsystem.

Covers:
- MockBrokerAdapter: connect/disconnect/subscribe/unsubscribe/inject
- TickRouter: subscribe, unsubscribe, route, fan-out, drop on full queue, stats
- ClientManager: add/remove/get, duplicate rejection, aggregate stats
- ApiKeyValidator: static key and callable modes
- WSProxyServer: start/stop, stats, add_broker, auth flow, subscribe flow,
  unsubscribe flow, ping/pong, unknown action, missing fields, invalid JSON
"""

from __future__ import annotations

import asyncio
import json
import time
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from ws_proxy.mock_adapter import MockBrokerAdapter
from ws_proxy.router import TickRouter
from ws_proxy.client_manager import ClientManager, ClientSession
from ws_proxy.auth import validate_api_key, ApiKeyValidator
from ws_proxy.server import WSProxyServer


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _tick(
    symbol: str = "NIFTY",
    exchange: str = "NSE_INDEX",
    mode: str = "LTP",
    ltp: float = 22_000.0,
) -> dict[str, Any]:
    return {"symbol": symbol, "exchange": exchange, "mode": mode, "ltp": ltp}


async def _get(q: asyncio.Queue, timeout: float = 1.0) -> Any:
    return await asyncio.wait_for(q.get(), timeout=timeout)


# ===========================================================================
# MockBrokerAdapter tests
# ===========================================================================


@pytest.mark.asyncio
async def test_mock_adapter_connect_sets_connected() -> None:
    """connect() marks the adapter as connected."""
    adapter = MockBrokerAdapter()
    assert not adapter.is_connected
    await adapter.connect({})
    assert adapter.is_connected


@pytest.mark.asyncio
async def test_mock_adapter_disconnect_clears_connected() -> None:
    """disconnect() marks the adapter as disconnected."""
    adapter = MockBrokerAdapter()
    await adapter.connect({})
    await adapter.disconnect()
    assert not adapter.is_connected


@pytest.mark.asyncio
async def test_mock_adapter_subscribe_adds_symbol() -> None:
    """subscribe() adds the symbol to the subscribed set."""
    adapter = MockBrokerAdapter(tick_interval=100.0)  # high interval — no auto ticks
    await adapter.connect({})
    await adapter.subscribe("NIFTY", "NSE_INDEX", "LTP")
    assert ("NIFTY", "NSE_INDEX") in adapter.subscribed_symbols
    await adapter.disconnect()


@pytest.mark.asyncio
async def test_mock_adapter_unsubscribe_removes_symbol() -> None:
    """unsubscribe() removes the symbol from the subscribed set."""
    adapter = MockBrokerAdapter(tick_interval=100.0)
    await adapter.connect({})
    await adapter.subscribe("NIFTY", "NSE_INDEX", "LTP")
    await adapter.unsubscribe("NIFTY", "NSE_INDEX")
    assert ("NIFTY", "NSE_INDEX") not in adapter.subscribed_symbols
    await adapter.disconnect()


@pytest.mark.asyncio
async def test_mock_adapter_inject_tick_dispatches() -> None:
    """inject_tick() calls all registered callbacks synchronously."""
    adapter = MockBrokerAdapter()
    received: list[dict] = []
    adapter.on_tick(received.append)
    adapter.inject_tick(_tick())
    assert len(received) == 1
    assert received[0]["symbol"] == "NIFTY"


@pytest.mark.asyncio
async def test_mock_adapter_multiple_callbacks() -> None:
    """Multiple registered callbacks all receive the same tick."""
    adapter = MockBrokerAdapter()
    recv_a: list[dict] = []
    recv_b: list[dict] = []
    adapter.on_tick(recv_a.append)
    adapter.on_tick(recv_b.append)
    adapter.inject_tick(_tick(ltp=12345.0))
    assert recv_a[0]["ltp"] == 12345.0
    assert recv_b[0]["ltp"] == 12345.0


@pytest.mark.asyncio
async def test_mock_adapter_generates_ticks() -> None:
    """After subscribing, at least one tick arrives within a generous window."""
    adapter = MockBrokerAdapter(tick_interval=0.05)
    received: list[dict] = []
    adapter.on_tick(received.append)
    await adapter.connect({})
    await adapter.subscribe("BANKNIFTY", "NSE_INDEX", "LTP")
    # Wait up to 0.5 s for at least one generated tick
    deadline = time.monotonic() + 0.5
    while not received and time.monotonic() < deadline:
        await asyncio.sleep(0.02)
    assert received, "Expected at least one generated tick"
    assert received[0]["symbol"] == "BANKNIFTY"
    await adapter.disconnect()


@pytest.mark.asyncio
async def test_mock_adapter_quote_mode_includes_ohlc() -> None:
    """inject_tick with QUOTE mode tick contains open/high/low/close."""
    adapter = MockBrokerAdapter(tick_interval=100.0)
    received: list[dict] = []
    adapter.on_tick(received.append)
    await adapter.connect({})
    await adapter.subscribe("SENSEX", "BSE_INDEX", "QUOTE")
    # Manually produce one QUOTE tick via internal helper
    tick = adapter._build_tick("SENSEX", "BSE_INDEX", "QUOTE")
    assert "open" in tick
    assert "high" in tick
    assert "low" in tick
    assert "close" in tick
    await adapter.disconnect()


@pytest.mark.asyncio
async def test_mock_adapter_depth_mode_includes_order_book() -> None:
    """DEPTH mode ticks include bids and asks lists."""
    adapter = MockBrokerAdapter(tick_interval=100.0)
    await adapter.connect({})
    await adapter.subscribe("NIFTY", "NSE_INDEX", "DEPTH")
    tick = adapter._build_tick("NIFTY", "NSE_INDEX", "DEPTH")
    assert "bids" in tick
    assert "asks" in tick
    assert len(tick["bids"]) == 5
    assert len(tick["asks"]) == 5
    await adapter.disconnect()


# ===========================================================================
# TickRouter tests
# ===========================================================================


def test_router_subscribe_and_route() -> None:
    """A subscribed queue receives the routed tick."""
    router = TickRouter()
    q: asyncio.Queue[dict] = asyncio.Queue()
    router.subscribe("NIFTY", "NSE_INDEX", "LTP", q)
    router.route(_tick())
    assert not q.empty()
    result = q.get_nowait()
    assert result["symbol"] == "NIFTY"


def test_router_unsubscribe_stops_delivery() -> None:
    """After unsubscribing, the queue receives no further ticks."""
    router = TickRouter()
    q: asyncio.Queue[dict] = asyncio.Queue()
    router.subscribe("NIFTY", "NSE_INDEX", "LTP", q)
    router.unsubscribe("NIFTY", "NSE_INDEX", "LTP", q)
    router.route(_tick())
    assert q.empty()


def test_router_fanout_multiple_clients() -> None:
    """Two queues subscribed to the same key both receive the tick."""
    router = TickRouter()
    q1: asyncio.Queue[dict] = asyncio.Queue()
    q2: asyncio.Queue[dict] = asyncio.Queue()
    router.subscribe("NIFTY", "NSE_INDEX", "LTP", q1)
    router.subscribe("NIFTY", "NSE_INDEX", "LTP", q2)
    router.route(_tick(ltp=9999.0))
    assert q1.get_nowait()["ltp"] == 9999.0
    assert q2.get_nowait()["ltp"] == 9999.0


def test_router_no_delivery_for_unsubscribed_symbol() -> None:
    """A tick for BANKNIFTY is not delivered to a NIFTY subscriber."""
    router = TickRouter()
    q: asyncio.Queue[dict] = asyncio.Queue()
    router.subscribe("NIFTY", "NSE_INDEX", "LTP", q)
    router.route(_tick(symbol="BANKNIFTY"))
    assert q.empty()


def test_router_unsubscribe_all_removes_client() -> None:
    """unsubscribe_all() removes the client from every key."""
    router = TickRouter()
    q: asyncio.Queue[dict] = asyncio.Queue()
    router.subscribe("NIFTY", "NSE_INDEX", "LTP", q)
    router.subscribe("BANKNIFTY", "NSE_INDEX", "LTP", q)
    router.unsubscribe_all(q)
    router.route(_tick("NIFTY"))
    router.route(_tick("BANKNIFTY"))
    assert q.empty()


def test_router_stats_returns_counts() -> None:
    """stats() includes expected keys."""
    router = TickRouter()
    q: asyncio.Queue[dict] = asyncio.Queue()
    router.subscribe("NIFTY", "NSE_INDEX", "LTP", q)
    router.route(_tick())
    s = router.stats()
    assert s["ticks_routed"] >= 1
    assert s["subscription_count"] == 1


def test_router_subscription_count() -> None:
    """subscription_count reflects the number of active sub keys."""
    router = TickRouter()
    q: asyncio.Queue[dict] = asyncio.Queue()
    router.subscribe("NIFTY", "NSE_INDEX", "LTP", q)
    router.subscribe("BANKNIFTY", "NSE_INDEX", "LTP", q)
    assert router.subscription_count == 2


def test_router_subscribed_keys() -> None:
    """subscribed_keys() returns all active subscription key strings."""
    router = TickRouter()
    q: asyncio.Queue[dict] = asyncio.Queue()
    router.subscribe("NIFTY", "NSE_INDEX", "LTP", q)
    keys = router.subscribed_keys()
    assert "NIFTY:NSE_INDEX:LTP" in keys


# ===========================================================================
# ClientManager tests
# ===========================================================================


def test_client_manager_add_creates_session() -> None:
    """add() returns a ClientSession with the given client_id."""
    mgr = ClientManager()
    session = mgr.add("c1")
    assert session.client_id == "c1"
    assert mgr.connected_count == 1


def test_client_manager_remove_deletes_session() -> None:
    """remove() returns the session and reduces connected_count."""
    mgr = ClientManager()
    mgr.add("c1")
    removed = mgr.remove("c1")
    assert removed is not None
    assert mgr.connected_count == 0


def test_client_manager_duplicate_raises() -> None:
    """Adding a duplicate client_id raises ValueError."""
    mgr = ClientManager()
    mgr.add("c1")
    with pytest.raises(ValueError, match="already registered"):
        mgr.add("c1")


def test_client_manager_get_returns_none_for_unknown() -> None:
    """get() returns None for an unknown client_id."""
    mgr = ClientManager()
    assert mgr.get("nonexistent") is None


def test_client_manager_authenticated_count() -> None:
    """authenticated_count reflects only sessions with authenticated=True."""
    mgr = ClientManager()
    s1 = mgr.add("c1")
    mgr.add("c2")
    s1.authenticated = True
    assert mgr.authenticated_count == 1


def test_client_manager_stats_keys() -> None:
    """stats() dict contains expected keys."""
    mgr = ClientManager()
    s = mgr.stats()
    assert "connected_clients" in s
    assert "authenticated_clients" in s
    assert "total_subscriptions" in s


def test_client_session_subscriptions() -> None:
    """add_subscription / remove_subscription work correctly on ClientSession."""
    session = ClientSession(client_id="x")
    session.add_subscription("NIFTY", "NSE_INDEX", "LTP")
    assert "NIFTY:NSE_INDEX:LTP" in session.subscriptions
    session.remove_subscription("NIFTY", "NSE_INDEX", "LTP")
    assert "NIFTY:NSE_INDEX:LTP" not in session.subscriptions


# ===========================================================================
# Auth tests
# ===========================================================================


def test_validate_api_key_match() -> None:
    """validate_api_key returns True for matching non-empty keys."""
    assert validate_api_key("secret", "secret") is True


def test_validate_api_key_mismatch() -> None:
    """validate_api_key returns False for non-matching keys."""
    assert validate_api_key("wrong", "secret") is False


def test_validate_api_key_empty_provided() -> None:
    """validate_api_key rejects an empty provided key."""
    assert validate_api_key("", "secret") is False


def test_validate_api_key_empty_expected() -> None:
    """validate_api_key rejects an empty expected key."""
    assert validate_api_key("key", "") is False


@pytest.mark.asyncio
async def test_api_key_validator_static_valid() -> None:
    """ApiKeyValidator with static key accepts the correct key."""
    v = ApiKeyValidator(api_key="mykey")
    assert await v.check("mykey") is True


@pytest.mark.asyncio
async def test_api_key_validator_static_invalid() -> None:
    """ApiKeyValidator with static key rejects wrong key."""
    v = ApiKeyValidator(api_key="mykey")
    assert await v.check("wrong") is False


@pytest.mark.asyncio
async def test_api_key_validator_callable_async() -> None:
    """ApiKeyValidator delegates to an async callable validator."""

    async def _validator(key: str) -> bool:
        return key == "async_key"

    v = ApiKeyValidator(validator=_validator)
    assert await v.check("async_key") is True
    assert await v.check("bad") is False


@pytest.mark.asyncio
async def test_api_key_validator_callable_sync() -> None:
    """ApiKeyValidator delegates to a sync callable validator."""
    v = ApiKeyValidator(validator=lambda k: k == "sync_key")
    assert await v.check("sync_key") is True


# ===========================================================================
# WSProxyServer tests
# ===========================================================================


@pytest.mark.asyncio
async def test_server_stats_before_start() -> None:
    """stats() returns expected keys even before start() is called."""
    server = WSProxyServer(api_key="test")
    s = server.stats()
    assert "connected_clients" in s
    assert "brokers" in s
    assert "ticks_total" in s
    assert "uptime_seconds" in s


@pytest.mark.asyncio
async def test_server_add_broker_registers_adapter() -> None:
    """add_broker() registers the adapter's name in stats."""
    server = WSProxyServer(api_key="test")
    adapter = MockBrokerAdapter(broker_name="mock")
    server.add_broker(adapter)
    assert "mock" in server.stats()["brokers"]


@pytest.mark.asyncio
async def test_server_add_broker_wires_tick_callback() -> None:
    """Injecting a tick via adapter increments server ticks_total."""
    server = WSProxyServer(api_key="test")
    adapter = MockBrokerAdapter(broker_name="mock")
    server.add_broker(adapter)
    adapter.inject_tick(_tick())
    assert server.stats()["ticks_total"] == 1


@pytest.mark.asyncio
async def test_server_handle_auth_valid_key() -> None:
    """A valid api_key in authenticate message sets session.authenticated."""
    server = WSProxyServer(api_key="goodkey")
    ws = AsyncMock()
    ws.remote_address = ("127.0.0.1", 9999)

    session = server._client_manager.add("test-client")
    msg = {"action": "authenticate", "api_key": "goodkey"}
    await server._handle_auth(session, ws, msg)

    assert session.authenticated is True
    call_args = ws.send.call_args[0][0]
    data = json.loads(call_args)
    assert data["type"] == "auth"
    assert data["status"] == "authenticated"


@pytest.mark.asyncio
async def test_server_handle_auth_invalid_key() -> None:
    """An invalid api_key in authenticate message leaves session unauthenticated."""
    server = WSProxyServer(api_key="goodkey")
    ws = AsyncMock()
    session = server._client_manager.add("test-client-2")
    msg = {"action": "authenticate", "api_key": "wrongkey"}
    await server._handle_auth(session, ws, msg)

    assert session.authenticated is False
    call_args = ws.send.call_args[0][0]
    data = json.loads(call_args)
    assert data["status"] == "failed"


@pytest.mark.asyncio
async def test_server_handle_subscribe_requires_auth() -> None:
    """subscribe message is rejected when session is not authenticated."""
    server = WSProxyServer(api_key="key")
    ws = AsyncMock()
    session = server._client_manager.add("test-client-3")
    msg = {"action": "subscribe", "symbol": "NIFTY", "exchange": "NSE_INDEX", "mode": "LTP"}
    await server._dispatch_message(session, ws, msg)

    call_args = ws.send.call_args[0][0]
    data = json.loads(call_args)
    assert data["type"] == "error"
    assert "not authenticated" in data["message"]


@pytest.mark.asyncio
async def test_server_handle_subscribe_valid() -> None:
    """Authenticated subscribe message registers the subscription."""
    server = WSProxyServer(api_key="key")
    ws = AsyncMock()
    session = server._client_manager.add("test-client-4")
    session.authenticated = True
    msg = {"action": "subscribe", "symbol": "NIFTY", "exchange": "NSE_INDEX", "mode": "LTP"}
    await server._dispatch_message(session, ws, msg)

    call_args = ws.send.call_args[0][0]
    data = json.loads(call_args)
    assert data["type"] == "subscribed"
    assert data["symbol"] == "NIFTY"
    assert "NIFTY:NSE_INDEX:LTP" in session.subscriptions


@pytest.mark.asyncio
async def test_server_handle_unsubscribe() -> None:
    """unsubscribe message removes the subscription."""
    server = WSProxyServer(api_key="key")
    ws = AsyncMock()
    session = server._client_manager.add("test-client-5")
    session.authenticated = True
    # Subscribe first
    await server._handle_subscribe(
        session, ws, {"symbol": "NIFTY", "exchange": "NSE_INDEX", "mode": "LTP"}
    )
    assert "NIFTY:NSE_INDEX:LTP" in session.subscriptions
    # Now unsubscribe
    await server._handle_unsubscribe(
        session, ws, {"symbol": "NIFTY", "exchange": "NSE_INDEX", "mode": "LTP"}
    )
    call_args = ws.send.call_args[0][0]
    data = json.loads(call_args)
    assert data["type"] == "unsubscribed"
    assert "NIFTY:NSE_INDEX:LTP" not in session.subscriptions


@pytest.mark.asyncio
async def test_server_ping_returns_pong() -> None:
    """ping action receives a pong response."""
    server = WSProxyServer(api_key="key")
    ws = AsyncMock()
    session = server._client_manager.add("test-client-6")
    session.authenticated = True
    await server._dispatch_message(session, ws, {"action": "ping"})
    call_args = ws.send.call_args[0][0]
    data = json.loads(call_args)
    assert data["type"] == "pong"


@pytest.mark.asyncio
async def test_server_unknown_action_returns_error() -> None:
    """An unrecognised action returns a type=error response."""
    server = WSProxyServer(api_key="key")
    ws = AsyncMock()
    session = server._client_manager.add("test-client-7")
    session.authenticated = True
    await server._dispatch_message(session, ws, {"action": "fly_to_moon"})
    call_args = ws.send.call_args[0][0]
    data = json.loads(call_args)
    assert data["type"] == "error"


@pytest.mark.asyncio
async def test_server_subscribe_missing_symbol_returns_error() -> None:
    """subscribe without symbol field returns an error."""
    server = WSProxyServer(api_key="key")
    ws = AsyncMock()
    session = server._client_manager.add("test-client-8")
    session.authenticated = True
    # Missing symbol
    await server._handle_subscribe(session, ws, {"exchange": "NSE_INDEX", "mode": "LTP"})
    call_args = ws.send.call_args[0][0]
    data = json.loads(call_args)
    assert data["type"] == "error"


@pytest.mark.asyncio
async def test_server_subscribe_invalid_mode_returns_error() -> None:
    """subscribe with an unsupported mode returns an error."""
    server = WSProxyServer(api_key="key")
    ws = AsyncMock()
    session = server._client_manager.add("test-client-9")
    session.authenticated = True
    await server._handle_subscribe(
        session, ws, {"symbol": "NIFTY", "exchange": "NSE_INDEX", "mode": "TICKER"}
    )
    call_args = ws.send.call_args[0][0]
    data = json.loads(call_args)
    assert data["type"] == "error"
    assert "mode" in data["message"]


@pytest.mark.asyncio
async def test_server_tick_delivered_to_subscribed_client() -> None:
    """A tick injected via a broker adapter reaches a subscribed client queue."""
    server = WSProxyServer(api_key="key")
    adapter = MockBrokerAdapter(broker_name="mock")
    server.add_broker(adapter)

    session = server._client_manager.add("test-tick-client")
    session.authenticated = True
    server._router.subscribe("NIFTY", "NSE_INDEX", "LTP", session.queue)

    adapter.inject_tick(_tick("NIFTY", "NSE_INDEX", "LTP", 22_500.0))
    result = await _get(session.queue, timeout=1.0)
    assert result["ltp"] == 22_500.0
