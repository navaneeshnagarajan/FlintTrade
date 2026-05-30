"""Ticker: connects broker streaming adapters to TickDispatcher.

When a BrokerSession starts streaming, the broker's WebSocket adapter
fires tick callbacks. This module bridges those callbacks to the
TickDispatcher's enqueue() method.
"""
from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger("flinttrade.gateway.ticker")


class BrokerTicker:
    """Bridges one broker's streaming adapter to the TickDispatcher.

    The broker SDK fires raw tick dicts through :meth:`on_tick`.  This
    class enriches each tick with the account identifier and forwards it
    to the :class:`~ws_bridge.TickDispatcher` for fan-out to all
    subscribed WebSocket clients.

    Args:
        account_id: Unique identifier for the broker account (e.g. client
            code).  Injected into every tick as ``"account_id"``.
        dispatcher: The :class:`~ws_bridge.TickDispatcher` that receives
            the enriched ticks.
    """

    def __init__(self, account_id: str, dispatcher: Any) -> None:
        self.account_id = account_id
        self._dispatcher = dispatcher

    def on_tick(self, tick: dict[str, Any]) -> None:
        """Called by the broker streaming adapter on each tick.

        Enriches the tick dict in-place with :attr:`account_id` and
        forwards it to the dispatcher via :meth:`~TickDispatcher.enqueue`.

        Args:
            tick: Raw tick dict from the broker SDK.  Modified in place to
                add ``"account_id"``.
        """
        tick["account_id"] = self.account_id
        self._dispatcher.enqueue(tick)

    def on_error(self, error: str) -> None:
        """Called by the broker streaming adapter on a streaming error.

        Args:
            error: Human-readable error description from the broker SDK.
        """
        logger.error("[%s] Streaming error: %s", self.account_id, error)

    def on_disconnect(self) -> None:
        """Called when the broker streaming adapter disconnects."""
        logger.warning("[%s] Streaming disconnected", self.account_id)
