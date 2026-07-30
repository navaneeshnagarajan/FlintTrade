"""WebSocket bridge: replaces OpenAlgo's ZMQ PUB/SUB + WS proxy.

TickDispatcher: receives ticks from broker streaming adapters via enqueue(),
dispatches to subscribed WebSocket clients via asyncio queues.

WebSocketServer: asyncio WebSocket server on port 8765, protocol-compatible
with the existing terminal websocket.ts client.
"""
from __future__ import annotations

import asyncio
import json
import logging
from typing import Any

logger = logging.getLogger("flinttrade.gateway.ws_bridge")

# Subscription key format: "SYMBOL:EXCHANGE:MODE"
_SubKey = str


def _make_key(symbol: str, exchange: str, mode: str) -> _SubKey:
    """Build a normalised subscription key."""
    return f"{symbol.upper()}:{exchange.upper()}:{mode.upper()}"


class TickDispatcher:
    """Central fan-out hub: one queue-in, many client queues-out.

    Thread-safe enqueue via call_soon_threadsafe when called from a
    non-asyncio thread (e.g. broker SDK callback threads).

    Args:
        maxsize: Maximum depth of the internal inbound queue.  Older
            ticks are dropped (queue full) rather than blocking the
            broker callback thread.
    """

    def __init__(self, maxsize: int = 10_000) -> None:
        self._queue: asyncio.Queue[dict[str, Any]] = asyncio.Queue(maxsize=maxsize)
        # _latest[symbol:exchange] → most-recent tick for REST polling
        self._latest: dict[str, dict[str, Any]] = {}
        # _subscribers[sub_key] → set of asyncio.Queue (one per client)
        self._subscribers: dict[_SubKey, set[asyncio.Queue[dict[str, Any]]]] = {}
        self._running: bool = False
        self._loop: asyncio.AbstractEventLoop | None = None

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def enqueue(self, tick: dict[str, Any]) -> None:
        """Accept a tick from a broker adapter.

        Safe to call from any thread.  If the inbound queue is full the
        tick is silently dropped (oldest-tick-drop strategy) to avoid
        blocking the caller.

        Args:
            tick: Raw tick dict.  Must contain at least ``"symbol"`` and
                ``"exchange"`` keys.
        """
        symbol = tick.get("symbol", "")
        exchange = tick.get("exchange", "")
        latest_key = f"{symbol.upper()}:{exchange.upper()}"
        self._latest[latest_key] = tick

        loop = self._loop
        if loop is not None and loop.is_running():
            try:
                loop.call_soon_threadsafe(self._queue.put_nowait, tick)
            except asyncio.QueueFull:
                logger.warning(
                    "TickDispatcher inbound queue full — dropping tick for %s",
                    latest_key,
                )
        else:
            # Called from within the asyncio thread (e.g. tests)
            try:
                self._queue.put_nowait(tick)
            except asyncio.QueueFull:
                logger.warning(
                    "TickDispatcher inbound queue full — dropping tick for %s",
                    latest_key,
                )

    async def run(self) -> None:
        """Main dispatch loop.  Run as an asyncio Task.

        Reads ticks from the inbound queue and fans them out to every
        subscriber whose key matches the tick's symbol, exchange and mode.
        Continues until :meth:`stop` is called.
        """
        self._loop = asyncio.get_running_loop()
        self._running = True
        logger.info("TickDispatcher started")

        while self._running:
            try:
                tick = await asyncio.wait_for(self._queue.get(), timeout=0.1)
            except TimeoutError:
                continue

            symbol = tick.get("symbol", "")
            exchange = tick.get("exchange", "")
            mode = tick.get("mode", "LTP")

            key = _make_key(symbol, exchange, mode)
            clients = self._subscribers.get(key, set())

            dead: list[asyncio.Queue[dict[str, Any]]] = []
            for client_queue in list(clients):
                try:
                    client_queue.put_nowait(tick)
                except asyncio.QueueFull:
                    logger.warning(
                        "Client queue full for key=%s — dropping tick", key
                    )
                except Exception:
                    # Queue may have been closed; collect for cleanup
                    dead.append(client_queue)

            for q in dead:
                clients.discard(q)

        logger.info("TickDispatcher stopped")

    def subscribe(
        self,
        symbols: list[dict[str, str]],
        mode: str,
        client_queue: asyncio.Queue[dict[str, Any]],
    ) -> None:
        """Register *client_queue* to receive ticks for *symbols* at *mode*.

        Args:
            symbols: List of ``{"symbol": str, "exchange": str}`` dicts.
            mode: Subscription mode string (``"LTP"``, ``"Quote"``, ``"Depth"``).
            client_queue: The asyncio Queue to which matching ticks are sent.
        """
        for sym_entry in symbols:
            key = _make_key(sym_entry["symbol"], sym_entry["exchange"], mode)
            self._subscribers.setdefault(key, set()).add(client_queue)
            logger.debug("Subscribed client to %s", key)

    def unsubscribe(
        self,
        symbols: list[dict[str, str]],
        mode: str,
        client_queue: asyncio.Queue[dict[str, Any]],
    ) -> None:
        """Deregister *client_queue* from *symbols* at *mode*.

        Args:
            symbols: List of ``{"symbol": str, "exchange": str}`` dicts.
            mode: Subscription mode string.
            client_queue: The client queue to remove.
        """
        for sym_entry in symbols:
            key = _make_key(sym_entry["symbol"], sym_entry["exchange"], mode)
            clients = self._subscribers.get(key)
            if clients:
                clients.discard(client_queue)
                logger.debug("Unsubscribed client from %s", key)

    def get_latest(self, symbol: str, exchange: str) -> dict[str, Any] | None:
        """Return the most-recent tick for REST polling fallback.

        Args:
            symbol: Instrument symbol.
            exchange: Exchange code.

        Returns:
            Most-recent tick dict, or ``None`` if no tick has arrived yet.
        """
        key = f"{symbol.upper()}:{exchange.upper()}"
        return self._latest.get(key)

    def stop(self) -> None:
        """Signal the :meth:`run` loop to exit after the current tick."""
        self._running = False


# ---------------------------------------------------------------------------
# WebSocketServer
# ---------------------------------------------------------------------------


class WebSocketServer:
    """asyncio WebSocket server on port 8765.

    Protocol-compatible with the existing ``terminal/websocket.ts`` client:
    - Auth: ``{"action": "authenticate", "api_key": "..."}``
    - Subscribe: ``{"action": "subscribe", "symbols": [...], "mode": "LTP"}``
    - Unsubscribe: ``{"action": "unsubscribe", "symbols": [...], "mode": "LTP"}``
    - Tick output: ``{"type": "market_data", "data": {...}}``

    Args:
        dispatcher: :class:`TickDispatcher` instance that provides tick data.
        host: Bind address (default ``"127.0.0.1"``).
        port: Bind port (default ``8765``).
    """

    def __init__(
        self,
        dispatcher: TickDispatcher,
        host: str = "127.0.0.1",
        port: int = 8765,
    ) -> None:
        self._dispatcher = dispatcher
        self._host = host
        self._port = port
        self._server: Any = None
        # Track all active client tasks for clean shutdown
        self._client_tasks: set[asyncio.Task[None]] = set()

    async def start(self) -> None:
        """Start the WebSocket server.

        The server runs until :meth:`stop` is called.
        """
        from websockets.asyncio.server import serve

        self._server = await serve(
            self._handle_client,
            self._host,
            self._port,
        )
        logger.info(
            "WebSocketServer listening on ws://%s:%d", self._host, self._port
        )

    async def _handle_client(self, websocket: Any) -> None:
        """Manage the full lifecycle of one WebSocket connection.

        Args:
            websocket: The websockets connection object for this client.
        """
        client_queue: asyncio.Queue[dict[str, Any]] = asyncio.Queue(maxsize=1000)
        authenticated = False
        active_symbols: list[dict[str, str]] = []
        active_mode: str = "LTP"

        logger.debug("New WebSocket client connected")

        # Pump ticks from client_queue → websocket in background
        async def _pump() -> None:
            while True:
                tick = await client_queue.get()
                try:
                    await websocket.send(
                        json.dumps({"type": "market_data", "data": tick})
                    )
                except Exception:
                    break

        pump_task = asyncio.create_task(_pump())

        try:
            async for raw in websocket:
                try:
                    msg = json.loads(raw)
                except json.JSONDecodeError:
                    logger.warning("Received non-JSON message from client")
                    continue

                action = msg.get("action", "")

                if action == "authenticate":
                    api_key = msg.get("api_key", "")
                    if api_key:
                        authenticated = True
                        await websocket.send(
                            json.dumps(
                                {"type": "auth", "status": "authenticated"}
                            )
                        )
                        logger.debug("Client authenticated")
                    else:
                        await websocket.send(
                            json.dumps(
                                {"type": "auth", "status": "failed", "reason": "empty key"}
                            )
                        )

                elif action == "subscribe":
                    if not authenticated:
                        await websocket.send(
                            json.dumps({"type": "error", "message": "not authenticated"})
                        )
                        continue
                    symbols: list[dict[str, str]] = msg.get("symbols", [])
                    mode: str = msg.get("mode", "LTP")
                    active_symbols = symbols
                    active_mode = mode
                    self._dispatcher.subscribe(symbols, mode, client_queue)
                    await websocket.send(
                        json.dumps({"type": "subscribed", "symbols": symbols, "mode": mode})
                    )
                    logger.debug(
                        "Client subscribed to %d symbol(s), mode=%s", len(symbols), mode
                    )

                elif action == "unsubscribe":
                    symbols = msg.get("symbols", [])
                    mode = msg.get("mode", active_mode)
                    self._dispatcher.unsubscribe(symbols, mode, client_queue)
                    await websocket.send(
                        json.dumps({"type": "unsubscribed", "symbols": symbols})
                    )
                    logger.debug("Client unsubscribed from %d symbol(s)", len(symbols))

                else:
                    logger.warning("Unknown action from client: %r", action)

        except Exception as exc:
            logger.debug("Client connection closed: %s", exc)
        finally:
            pump_task.cancel()
            if active_symbols:
                self._dispatcher.unsubscribe(active_symbols, active_mode, client_queue)
            logger.debug("Client disconnected, cleaned up")

    async def stop(self) -> None:
        """Close all connections and stop the server."""
        if self._server is not None:
            self._server.close()
            await self._server.wait_closed()
            self._server = None
            logger.info("WebSocketServer stopped")
