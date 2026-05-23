"""TickRouter — fan-out engine for the WS proxy.

Maintains a subscription table (symbol + exchange + mode → set of client
queues) and routes each incoming tick to every matching client.

Thread safety: all public methods must be called from the asyncio event loop.
"""

from __future__ import annotations

import asyncio
import logging
import time
from typing import Any

logger = logging.getLogger("flinttrade.gateway.ws_proxy.router")

# Subscription key: "SYMBOL:EXCHANGE:MODE"
_SubKey = str


def _sub_key(symbol: str, exchange: str, mode: str) -> _SubKey:
    """Build a normalised subscription key.

    Args:
        symbol: Instrument symbol.
        exchange: Exchange code.
        mode: Subscription mode.

    Returns:
        Colon-separated upper-case key string.
    """
    return f"{symbol.upper()}:{exchange.upper()}:{mode.upper()}"


class TickRouter:
    """Fan-out engine: routes ticks from broker adapters to client queues.

    Each client queue is an :class:`asyncio.Queue` owned by the corresponding
    :class:`~ws_proxy.client_manager.ClientSession`.  The router does **not**
    own or manage those queues — it only holds weak references via the
    subscription table.

    Args:
        max_client_queue_size: Maximum number of pending ticks per client
            queue before the router starts dropping.  Default ``1_000``.
    """

    def __init__(self, max_client_queue_size: int = 1_000) -> None:
        # sub_key → {client_queue, ...}
        self._table: dict[_SubKey, set[asyncio.Queue[dict[str, Any]]]] = {}
        self._max_queue_size = max_client_queue_size
        # Metrics
        self._ticks_routed: int = 0
        self._ticks_dropped: int = 0
        self._last_tick_ts: float = 0.0
        # Simple per-second counter
        self._tps_window: list[float] = []  # timestamps of recent ticks (1 s window)

    # ------------------------------------------------------------------
    # Subscription management
    # ------------------------------------------------------------------

    def subscribe(
        self,
        symbol: str,
        exchange: str,
        mode: str,
        client_queue: asyncio.Queue[dict[str, Any]],
    ) -> None:
        """Register *client_queue* to receive ticks for a given instrument + mode.

        Args:
            symbol: Instrument symbol.
            exchange: Exchange code.
            mode: Subscription mode (``"LTP"``, ``"QUOTE"``, ``"DEPTH"``).
            client_queue: Asyncio queue to deliver matching ticks into.
        """
        key = _sub_key(symbol, exchange, mode)
        self._table.setdefault(key, set()).add(client_queue)
        logger.debug("TickRouter: subscribed client to %s", key)

    def unsubscribe(
        self,
        symbol: str,
        exchange: str,
        mode: str,
        client_queue: asyncio.Queue[dict[str, Any]],
    ) -> None:
        """Remove *client_queue* from the subscription for this instrument + mode.

        Args:
            symbol: Instrument symbol.
            exchange: Exchange code.
            mode: Subscription mode.
            client_queue: The client queue to remove.
        """
        key = _sub_key(symbol, exchange, mode)
        queues = self._table.get(key)
        if queues:
            queues.discard(client_queue)
            if not queues:
                del self._table[key]
        logger.debug("TickRouter: unsubscribed client from %s", key)

    def unsubscribe_all(self, client_queue: asyncio.Queue[dict[str, Any]]) -> None:
        """Remove *client_queue* from every subscription key it appears in.

        Called when a client disconnects.

        Args:
            client_queue: The client queue to purge from all keys.
        """
        empty_keys = []
        for key, queues in self._table.items():
            queues.discard(client_queue)
            if not queues:
                empty_keys.append(key)
        for key in empty_keys:
            del self._table[key]
        logger.debug("TickRouter: purged disconnected client from all subscriptions")

    # ------------------------------------------------------------------
    # Tick routing
    # ------------------------------------------------------------------

    def route(self, tick: dict[str, Any]) -> None:
        """Dispatch *tick* to every client queue subscribed to this instrument.

        This method is synchronous and non-blocking.  It uses
        :meth:`asyncio.Queue.put_nowait` and silently drops ticks when a
        client's queue is full rather than blocking.

        Args:
            tick: Normalised tick dict.  Must contain ``"symbol"``,
                ``"exchange"``, and ``"mode"`` keys.
        """
        symbol = tick.get("symbol", "")
        exchange = tick.get("exchange", "")
        mode = tick.get("mode", "LTP")
        key = _sub_key(symbol, exchange, mode)

        queues = self._table.get(key)
        if not queues:
            return

        now = time.monotonic()
        self._last_tick_ts = now
        self._tps_window.append(now)
        # Keep only ticks from the last second
        self._tps_window = [t for t in self._tps_window if now - t <= 1.0]

        dead: list[asyncio.Queue[dict[str, Any]]] = []
        for q in list(queues):
            if q.qsize() >= self._max_queue_size:
                self._ticks_dropped += 1
                logger.warning(
                    "TickRouter: client queue full for key=%s — dropping tick", key
                )
                continue
            try:
                q.put_nowait(tick)
                self._ticks_routed += 1
            except asyncio.QueueFull:
                self._ticks_dropped += 1
                logger.warning(
                    "TickRouter: put_nowait QueueFull for key=%s — dropping tick", key
                )
            except Exception:
                dead.append(q)

        for q in dead:
            queues.discard(q)

    # ------------------------------------------------------------------
    # Introspection
    # ------------------------------------------------------------------

    @property
    def subscription_count(self) -> int:
        """Total number of active subscription keys (symbol × mode combos)."""
        return len(self._table)

    @property
    def ticks_per_second(self) -> float:
        """Rolling 1-second tick throughput estimate."""
        now = time.monotonic()
        self._tps_window = [t for t in self._tps_window if now - t <= 1.0]
        return float(len(self._tps_window))

    def stats(self) -> dict[str, Any]:
        """Return router performance counters.

        Returns:
            Dict with ``ticks_routed``, ``ticks_dropped``,
            ``ticks_per_second``, and ``subscription_count``.
        """
        return {
            "ticks_routed": self._ticks_routed,
            "ticks_dropped": self._ticks_dropped,
            "ticks_per_second": self.ticks_per_second,
            "subscription_count": self.subscription_count,
        }

    def subscribed_keys(self) -> list[str]:
        """Return a snapshot of all active subscription keys.

        Returns:
            List of ``"SYMBOL:EXCHANGE:MODE"`` strings.
        """
        return list(self._table.keys())
