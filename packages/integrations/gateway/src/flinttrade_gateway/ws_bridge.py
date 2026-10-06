"""Native tick dispatcher for local broker streaming and REST polling."""
from __future__ import annotations

import asyncio
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
        maxsize: Maximum depth of the internal inbound queue. Incoming
            ticks are dropped when the queue is full rather than blocking
            the broker callback thread; the polling snapshot still updates.
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

        Safe to call from any thread once :meth:`run` has started. If the
        inbound queue is full, the incoming tick is dropped without blocking
        the caller. The latest polling snapshot still records that tick.

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
            loop.call_soon_threadsafe(self._enqueue_nowait, tick, latest_key)
        else:
            self._enqueue_nowait(tick, latest_key)

    def _enqueue_nowait(self, tick: dict[str, Any], latest_key: str) -> None:
        """Handle backpressure where the queue operation actually executes."""
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
