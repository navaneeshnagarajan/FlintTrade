"""WSProxyServer — FlintTrade-native WebSocket proxy.

The server:
1. Accepts WebSocket client connections on a configurable host:port.
2. Authenticates clients via API key.
3. Receives subscribe/unsubscribe/ping messages from clients.
4. Registers clients with the :class:`~ws_proxy.router.TickRouter`.
5. Fan-outs ticks from registered :class:`~ws_proxy.broker_adapter.AbstractBrokerAdapter`
   instances to subscribed clients.
6. Handles broker reconnection with exponential back-off.
7. Exposes health stats via :meth:`WSProxyServer.stats`.

Wire protocol (JSON over WebSocket)
------------------------------------
Client → Server::

    {"action": "authenticate", "api_key": "<key>"}
    {"action": "subscribe",    "symbol": "NIFTY", "exchange": "NSE_INDEX", "mode": "LTP"}
    {"action": "unsubscribe",  "symbol": "NIFTY", "exchange": "NSE_INDEX", "mode": "LTP"}
    {"action": "ping"}

Server → Client::

    {"type": "auth",        "status": "authenticated"}
    {"type": "auth",        "status": "failed", "reason": "..."}
    {"type": "subscribed",  "symbol": "NIFTY", "exchange": "NSE_INDEX", "mode": "LTP"}
    {"type": "unsubscribed","symbol": "NIFTY", "exchange": "NSE_INDEX"}
    {"type": "market_data", "data": {<tick dict>}}
    {"type": "pong"}
    {"type": "error",       "message": "..."}
"""

from __future__ import annotations

import asyncio
import json
import logging
import secrets
import time
from typing import Any

from .auth import ApiKeyValidator
from .broker_adapter import AbstractBrokerAdapter
from .client_manager import ClientManager, ClientSession
from .router import TickRouter

logger = logging.getLogger("flinttrade.gateway.ws_proxy.server")

# Exponential back-off settings for broker reconnection
_BACKOFF_BASE: float = 1.0   # seconds
_BACKOFF_MAX: float = 60.0   # seconds
_BACKOFF_FACTOR: float = 2.0


class WSProxyServer:
    """FlintTrade WebSocket proxy server.

    Args:
        host: Bind address (default ``"127.0.0.1"``).
        port: Bind port (default ``18765``).
        api_key: Static API key for client authentication.  An empty string
            disables authentication (development only).
    """

    def __init__(
        self,
        host: str = "127.0.0.1",
        port: int = 18765,
        api_key: str = "",
    ) -> None:
        self._host = host
        self._port = port
        self._validator = ApiKeyValidator(api_key=api_key)
        self._router = TickRouter()
        self._client_manager = ClientManager()
        self._brokers: dict[str, AbstractBrokerAdapter] = {}
        self._reconnect_tasks: dict[str, asyncio.Task[None]] = {}
        self._server: Any = None
        self._started_at: float = 0.0
        self._total_ticks: int = 0

    # ------------------------------------------------------------------
    # Broker management
    # ------------------------------------------------------------------

    def add_broker(self, adapter: AbstractBrokerAdapter) -> None:
        """Register a broker adapter with the proxy.

        The adapter's tick callback is wired to the router immediately.
        The adapter is *not* connected here — call :meth:`start` or
        :meth:`connect_broker` separately.

        Args:
            adapter: A concrete :class:`~ws_proxy.broker_adapter.AbstractBrokerAdapter`.
        """
        name = adapter.broker_name
        self._brokers[name] = adapter

        def _on_tick(tick: dict) -> None:
            self._total_ticks += 1
            self._router.route(tick)

        adapter.on_tick(_on_tick)
        logger.info("WSProxyServer: registered broker '%s'", name)

    async def connect_broker(
        self,
        broker_name: str,
        credentials: dict,
    ) -> None:
        """Connect a registered broker adapter with exponential back-off.

        Args:
            broker_name: Name of a previously registered adapter.
            credentials: Broker-specific auth credentials.

        Raises:
            KeyError: If ``broker_name`` has not been registered.
        """
        if broker_name not in self._brokers:
            raise KeyError(f"Broker '{broker_name}' is not registered")

        task = asyncio.create_task(
            self._connect_with_backoff(broker_name, credentials),
            name=f"ws_proxy_broker_{broker_name}",
        )
        self._reconnect_tasks[broker_name] = task

    # ------------------------------------------------------------------
    # Server lifecycle
    # ------------------------------------------------------------------

    async def start(self) -> None:
        """Start the WebSocket server.

        Binds to the configured host and port and begins accepting clients.
        Returns immediately — the server runs until :meth:`stop` is called.
        """
        try:
            from websockets.asyncio.server import serve
        except ImportError as exc:
            raise ImportError(
                "The 'websockets' package is required. "
                "Install it with: pip install websockets>=13"
            ) from exc

        self._server = await serve(
            self._handle_client,
            self._host,
            self._port,
        )
        self._started_at = time.time()
        logger.info(
            "WSProxyServer started on ws://%s:%d", self._host, self._port
        )

    async def stop(self) -> None:
        """Gracefully shut down the server and all broker connections."""
        # Stop accepting new clients
        if self._server is not None:
            self._server.close()
            await self._server.wait_closed()
            self._server = None

        # Cancel reconnect tasks
        for task in self._reconnect_tasks.values():
            if not task.done():
                task.cancel()
                try:
                    await task
                except (asyncio.CancelledError, Exception):
                    pass
        self._reconnect_tasks.clear()

        # Disconnect all broker adapters
        for name, adapter in self._brokers.items():
            try:
                await adapter.disconnect()
            except Exception:
                logger.exception("Error disconnecting broker '%s'", name)

        logger.info("WSProxyServer stopped")

    # ------------------------------------------------------------------
    # Client handler
    # ------------------------------------------------------------------

    async def _handle_client(self, websocket: Any) -> None:
        """Manage the full lifecycle of one WebSocket client connection.

        Args:
            websocket: The ``websockets`` connection object.
        """
        client_id = secrets.token_hex(8)
        remote = getattr(websocket, "remote_address", ("?", 0))
        remote_str = f"{remote[0]}:{remote[1]}" if isinstance(remote, tuple) else str(remote)

        session = self._client_manager.add(client_id, remote_addr=remote_str)
        logger.debug("WSProxyServer: client '%s' connected from %s", client_id, remote_str)

        # Background pump: session.queue → websocket
        pump_task = asyncio.create_task(
            self._pump_ticks(session, websocket),
            name=f"ws_proxy_pump_{client_id}",
        )

        try:
            async for raw in websocket:
                try:
                    msg = json.loads(raw)
                except (json.JSONDecodeError, ValueError):
                    await self._send(websocket, {"type": "error", "message": "invalid JSON"})
                    continue

                await self._dispatch_message(session, websocket, msg)

        except Exception as exc:
            logger.debug("WSProxyServer: client '%s' connection closed: %s", client_id, exc)
        finally:
            pump_task.cancel()
            try:
                await pump_task
            except (asyncio.CancelledError, Exception):
                pass

            # Purge all subscriptions for this client
            for sub_key in list(session.subscriptions):
                parts = sub_key.split(":", 2)
                if len(parts) == 3:
                    sym, exch, mode = parts
                    self._router.unsubscribe(sym, exch, mode, session.queue)

            self._client_manager.remove(client_id)
            logger.debug("WSProxyServer: client '%s' cleaned up", client_id)

    async def _dispatch_message(
        self,
        session: ClientSession,
        websocket: Any,
        msg: dict,
    ) -> None:
        """Process one incoming message from a client.

        Args:
            session: The client's :class:`~ws_proxy.client_manager.ClientSession`.
            websocket: The websockets connection for sending responses.
            msg: Parsed JSON message dict.
        """
        action = msg.get("action", "")

        if action == "authenticate":
            await self._handle_auth(session, websocket, msg)

        elif action == "subscribe":
            if not session.authenticated:
                await self._send(websocket, {"type": "error", "message": "not authenticated"})
                return
            await self._handle_subscribe(session, websocket, msg)

        elif action == "unsubscribe":
            if not session.authenticated:
                await self._send(websocket, {"type": "error", "message": "not authenticated"})
                return
            await self._handle_unsubscribe(session, websocket, msg)

        elif action == "ping":
            await self._send(websocket, {"type": "pong"})

        else:
            logger.warning(
                "WSProxyServer: unknown action '%s' from client '%s'",
                action,
                session.client_id,
            )
            await self._send(websocket, {"type": "error", "message": f"unknown action: {action}"})

    async def _handle_auth(
        self,
        session: ClientSession,
        websocket: Any,
        msg: dict,
    ) -> None:
        """Process an authenticate message.

        Args:
            session: Client session.
            websocket: WS connection.
            msg: The authenticate message dict.
        """
        api_key = msg.get("api_key", "")
        valid = await self._validator.check(api_key)
        if valid:
            session.authenticated = True
            await self._send(websocket, {"type": "auth", "status": "authenticated"})
            logger.debug("WSProxyServer: client '%s' authenticated", session.client_id)
        else:
            await self._send(
                websocket,
                {"type": "auth", "status": "failed", "reason": "invalid api key"},
            )
            logger.warning(
                "WSProxyServer: client '%s' authentication failed", session.client_id
            )

    async def _handle_subscribe(
        self,
        session: ClientSession,
        websocket: Any,
        msg: dict,
    ) -> None:
        """Process a subscribe message.

        Args:
            session: Client session.
            websocket: WS connection.
            msg: The subscribe message dict.
        """
        symbol: str = msg.get("symbol", "")
        exchange: str = msg.get("exchange", "")
        mode: str = msg.get("mode", "LTP").upper()

        if not symbol or not exchange:
            await self._send(
                websocket,
                {"type": "error", "message": "subscribe requires symbol and exchange"},
            )
            return

        if mode not in ("LTP", "QUOTE", "DEPTH"):
            await self._send(
                websocket,
                {"type": "error", "message": f"unsupported mode: {mode}"},
            )
            return

        self._router.subscribe(symbol, exchange, mode, session.queue)
        session.add_subscription(symbol, exchange, mode)

        await self._send(
            websocket,
            {
                "type": "subscribed",
                "symbol": symbol.upper(),
                "exchange": exchange.upper(),
                "mode": mode,
            },
        )
        logger.debug(
            "WSProxyServer: client '%s' subscribed to %s/%s mode=%s",
            session.client_id,
            symbol,
            exchange,
            mode,
        )

    async def _handle_unsubscribe(
        self,
        session: ClientSession,
        websocket: Any,
        msg: dict,
    ) -> None:
        """Process an unsubscribe message.

        Args:
            session: Client session.
            websocket: WS connection.
            msg: The unsubscribe message dict.
        """
        symbol: str = msg.get("symbol", "")
        exchange: str = msg.get("exchange", "")
        mode: str = msg.get("mode", "LTP").upper()

        if not symbol or not exchange:
            await self._send(
                websocket,
                {"type": "error", "message": "unsubscribe requires symbol and exchange"},
            )
            return

        self._router.unsubscribe(symbol, exchange, mode, session.queue)
        session.remove_subscription(symbol, exchange, mode)

        await self._send(
            websocket,
            {"type": "unsubscribed", "symbol": symbol.upper(), "exchange": exchange.upper()},
        )

    # ------------------------------------------------------------------
    # Tick pump
    # ------------------------------------------------------------------

    async def _pump_ticks(self, session: ClientSession, websocket: Any) -> None:
        """Forward ticks from *session.queue* to the WebSocket connection.

        Args:
            session: Client session.
            websocket: WS connection to send ticks to.
        """
        while True:
            tick = await session.queue.get()
            try:
                await self._send(websocket, {"type": "market_data", "data": tick})
            except Exception:
                break

    # ------------------------------------------------------------------
    # Broker reconnection with exponential back-off
    # ------------------------------------------------------------------

    async def _connect_with_backoff(
        self,
        broker_name: str,
        credentials: dict,
    ) -> None:
        """Attempt to connect a broker adapter, retrying with back-off on failure.

        Args:
            broker_name: The broker adapter to connect.
            credentials: Auth credentials passed to the adapter.
        """
        adapter = self._brokers[broker_name]
        delay = _BACKOFF_BASE
        attempt = 0

        while True:
            attempt += 1
            try:
                logger.info(
                    "WSProxyServer: connecting broker '%s' (attempt %d)",
                    broker_name,
                    attempt,
                )
                await adapter.connect(credentials)
                logger.info(
                    "WSProxyServer: broker '%s' connected successfully", broker_name
                )
                return

            except asyncio.CancelledError:
                raise

            except Exception as exc:
                logger.warning(
                    "WSProxyServer: broker '%s' connection failed: %s. Retrying in %.1fs",
                    broker_name,
                    exc,
                    delay,
                )
                try:
                    await asyncio.sleep(delay)
                except asyncio.CancelledError:
                    raise
                delay = min(delay * _BACKOFF_FACTOR, _BACKOFF_MAX)

    # ------------------------------------------------------------------
    # Health / statistics
    # ------------------------------------------------------------------

    def stats(self) -> dict[str, Any]:
        """Return a health snapshot of the proxy server.

        Returns:
            Dict with:
            - ``connected_clients`` int
            - ``authenticated_clients`` int
            - ``subscriptions`` int (total across all clients)
            - ``ticks_total`` int
            - ``ticks_per_second`` float
            - ``brokers`` list[str] of registered broker names
            - ``uptime_seconds`` float
        """
        router_stats = self._router.stats()
        client_stats = self._client_manager.stats()
        uptime = time.time() - self._started_at if self._started_at else 0.0

        return {
            "connected_clients": client_stats["connected_clients"],
            "authenticated_clients": client_stats["authenticated_clients"],
            "subscriptions": router_stats["subscription_count"],
            "ticks_total": self._total_ticks,
            "ticks_per_second": router_stats["ticks_per_second"],
            "brokers": list(self._brokers.keys()),
            "uptime_seconds": uptime,
        }

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    @staticmethod
    async def _send(websocket: Any, payload: dict) -> None:
        """Serialise *payload* to JSON and send it over *websocket*.

        Silently swallows send errors (e.g. when the connection is already
        closed) to prevent cascading exceptions in the message handler.

        Args:
            websocket: WS connection.
            payload: Dict to serialise and send.
        """
        try:
            await websocket.send(json.dumps(payload))
        except Exception as exc:
            logger.debug("WSProxyServer: send failed: %s", exc)
