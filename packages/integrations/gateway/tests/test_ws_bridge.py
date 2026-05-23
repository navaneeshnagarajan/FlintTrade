"""Tests for TickDispatcher and BrokerTicker.

All tests are async, using pytest-asyncio.  No sleeps — assertions are
event-driven using asyncio primitives.
"""
from __future__ import annotations

import asyncio
import logging
from typing import Any
from unittest.mock import MagicMock

import pytest
import pytest_asyncio  # noqa: F401 — registers the pytest-asyncio plugin

from ws_bridge import TickDispatcher
from ticker import BrokerTicker


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_tick(
    symbol: str = "NIFTY",
    exchange: str = "NSE_INDEX",
    mode: str = "LTP",
    ltp: float = 22_000.0,
) -> dict[str, Any]:
    """Build a minimal tick dict."""
    return {
        "symbol": symbol,
        "exchange": exchange,
        "mode": mode,
        "ltp": ltp,
    }


async def _recv(
    queue: asyncio.Queue[dict[str, Any]],
    timeout: float = 1.0,
) -> dict[str, Any]:
    """Wait for one item from *queue*, raising TimeoutError after *timeout* s."""
    return await asyncio.wait_for(queue.get(), timeout=timeout)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def dispatcher() -> TickDispatcher:
    """Fresh TickDispatcher for each test."""
    return TickDispatcher()


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_enqueue_and_dispatch(dispatcher: TickDispatcher) -> None:
    """A subscribed client receives the tick it subscribed for."""
    client_q: asyncio.Queue[dict[str, Any]] = asyncio.Queue()
    dispatcher.subscribe(
        [{"symbol": "NIFTY", "exchange": "NSE_INDEX"}], "LTP", client_q
    )

    run_task = asyncio.create_task(dispatcher.run())

    tick = _make_tick()
    dispatcher.enqueue(tick)

    received = await _recv(client_q)
    assert received["symbol"] == "NIFTY"
    assert received["ltp"] == 22_000.0

    dispatcher.stop()
    await run_task


@pytest.mark.asyncio
async def test_subscribe_multiple_symbols(dispatcher: TickDispatcher) -> None:
    """A client subscribed to 3 symbols receives ticks for all three."""
    client_q: asyncio.Queue[dict[str, Any]] = asyncio.Queue()
    symbols = [
        {"symbol": "NIFTY", "exchange": "NSE_INDEX"},
        {"symbol": "BANKNIFTY", "exchange": "NSE_INDEX"},
        {"symbol": "SENSEX", "exchange": "BSE_INDEX"},
    ]
    dispatcher.subscribe(symbols, "LTP", client_q)

    run_task = asyncio.create_task(dispatcher.run())

    for sym, ltp in [("NIFTY", 22_000.0), ("BANKNIFTY", 48_000.0), ("SENSEX", 72_000.0)]:
        dispatcher.enqueue(_make_tick(symbol=sym, exchange="NSE_INDEX" if sym != "SENSEX" else "BSE_INDEX", ltp=ltp))

    received_symbols: set[str] = set()
    for _ in range(3):
        item = await _recv(client_q)
        received_symbols.add(item["symbol"])

    assert received_symbols == {"NIFTY", "BANKNIFTY", "SENSEX"}

    dispatcher.stop()
    await run_task


@pytest.mark.asyncio
async def test_unsubscribe_stops_delivery(dispatcher: TickDispatcher) -> None:
    """After unsubscribing, the client queue receives no further ticks.

    Sentinel approach: a second client subscribes to SENSEX.  After we
    unsubscribe the first client from NIFTY, we enqueue a NIFTY tick AND a
    SENSEX sentinel.  When the second client receives the sentinel we know
    the dispatcher processed at least up to that point — so if client_1_q
    is still empty, the unsubscribe worked.
    """
    client_1_q: asyncio.Queue[dict[str, Any]] = asyncio.Queue()
    sentinel_q: asyncio.Queue[dict[str, Any]] = asyncio.Queue()

    dispatcher.subscribe(
        [{"symbol": "NIFTY", "exchange": "NSE_INDEX"}], "LTP", client_1_q
    )
    dispatcher.subscribe(
        [{"symbol": "SENSEX", "exchange": "BSE_INDEX"}], "LTP", sentinel_q
    )

    run_task = asyncio.create_task(dispatcher.run())

    # Confirm initial subscription is working
    dispatcher.enqueue(_make_tick("NIFTY", "NSE_INDEX"))
    first = await _recv(client_1_q)
    assert first["symbol"] == "NIFTY"

    # Unsubscribe client_1_q from NIFTY
    dispatcher.unsubscribe(
        [{"symbol": "NIFTY", "exchange": "NSE_INDEX"}], "LTP", client_1_q
    )

    # Enqueue a NIFTY tick (should NOT reach client_1_q) then a sentinel
    dispatcher.enqueue(_make_tick("NIFTY", "NSE_INDEX", ltp=99_999.0))
    dispatcher.enqueue(_make_tick("SENSEX", "BSE_INDEX"))

    # Wait for sentinel to confirm processing reached this point
    sentinel = await _recv(sentinel_q)
    assert sentinel["symbol"] == "SENSEX"

    # client_1_q must be empty — the NIFTY tick after unsubscribe was dropped
    assert client_1_q.empty()

    dispatcher.stop()
    await run_task


@pytest.mark.asyncio
async def test_latest_updated(dispatcher: TickDispatcher) -> None:
    """get_latest returns the most-recent tick after enqueue."""
    tick = _make_tick("NIFTY", "NSE_INDEX", ltp=21_500.0)
    dispatcher.enqueue(tick)
    latest = dispatcher.get_latest("NIFTY", "NSE_INDEX")
    assert latest is not None
    assert latest["ltp"] == 21_500.0


@pytest.mark.asyncio
async def test_latest_returns_none_for_unknown(dispatcher: TickDispatcher) -> None:
    """get_latest returns None for a symbol that has never been enqueued."""
    result = dispatcher.get_latest("UNKNOWN", "FAKE_EXCHANGE")
    assert result is None


@pytest.mark.asyncio
async def test_multiple_subscribers(dispatcher: TickDispatcher) -> None:
    """Two client queues subscribed to the same symbol both receive the tick."""
    client_a: asyncio.Queue[dict[str, Any]] = asyncio.Queue()
    client_b: asyncio.Queue[dict[str, Any]] = asyncio.Queue()

    sym = [{"symbol": "NIFTY", "exchange": "NSE_INDEX"}]
    dispatcher.subscribe(sym, "LTP", client_a)
    dispatcher.subscribe(sym, "LTP", client_b)

    run_task = asyncio.create_task(dispatcher.run())

    dispatcher.enqueue(_make_tick("NIFTY", "NSE_INDEX", ltp=22_100.0))

    tick_a = await _recv(client_a)
    tick_b = await _recv(client_b)

    assert tick_a["ltp"] == 22_100.0
    assert tick_b["ltp"] == 22_100.0

    dispatcher.stop()
    await run_task


@pytest.mark.asyncio
async def test_dispatcher_stop(dispatcher: TickDispatcher) -> None:
    """Calling stop() causes run() to exit cleanly."""
    run_task = asyncio.create_task(dispatcher.run())

    # Give the loop a moment to start
    await asyncio.sleep(0)

    dispatcher.stop()
    # run() should finish within a reasonable time (timeout guard = 2 s)
    await asyncio.wait_for(run_task, timeout=2.0)
    assert run_task.done()
    assert not run_task.cancelled()


# ---------------------------------------------------------------------------
# BrokerTicker tests
# ---------------------------------------------------------------------------

def test_broker_ticker_on_tick() -> None:
    """BrokerTicker.on_tick enriches the tick with account_id and calls enqueue."""
    mock_dispatcher = MagicMock()
    ticker = BrokerTicker("ACC001", mock_dispatcher)

    tick: dict[str, Any] = {"symbol": "NIFTY", "exchange": "NSE_INDEX", "ltp": 22_000.0}
    ticker.on_tick(tick)

    # Verify account_id was injected
    assert tick["account_id"] == "ACC001"
    # Verify dispatcher.enqueue was called with the enriched tick
    mock_dispatcher.enqueue.assert_called_once_with(tick)


def test_broker_ticker_on_error_logs(caplog: pytest.LogCaptureFixture) -> None:
    """BrokerTicker.on_error logs an error message containing account_id and error text."""
    mock_dispatcher = MagicMock()
    ticker = BrokerTicker("ACC002", mock_dispatcher)

    with caplog.at_level(logging.ERROR, logger="flinttrade.gateway.ticker"):
        ticker.on_error("Connection reset by peer")

    assert any(
        "ACC002" in record.message and "Connection reset by peer" in record.message
        for record in caplog.records
    )
