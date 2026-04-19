"""Abstract base class for FlintTrade WS broker adapters.

Every concrete adapter (live or mock) must extend ``AbstractBrokerAdapter``
and implement the five abstract methods below.  The adapter is responsible
for:

- Maintaining a connection to the upstream broker WebSocket
- Calling each registered tick callback when a tick arrives
- Reconnecting automatically (the server handles the retry schedule)
- Normalising the broker-specific payload into a standard tick dict

Standard tick dict keys
-----------------------
symbol          str      e.g. "NIFTY"
exchange        str      e.g. "NSE_INDEX"
mode            str      "LTP" | "QUOTE" | "DEPTH"
ltp             float    last-traded price
timestamp       float    Unix epoch seconds (float)

Additional keys for QUOTE mode:
open, high, low, close  float

Additional keys for DEPTH mode:
bids    list[dict]   [{"price": float, "qty": int, "orders": int}, ...]
asks    list[dict]   same shape
"""

from __future__ import annotations

import logging
from abc import ABC, abstractmethod
from typing import Callable, Literal

logger = logging.getLogger("flinttrade.gateway.ws_proxy.broker_adapter")

TickCallback = Callable[[dict], None]
Mode = Literal["LTP", "QUOTE", "DEPTH"]


class AbstractBrokerAdapter(ABC):
    """Base class for all FlintTrade WebSocket broker adapters.

    Subclasses must implement :meth:`connect`, :meth:`disconnect`,
    :meth:`subscribe`, :meth:`unsubscribe`, and :meth:`on_tick`.

    Args:
        broker_name: Canonical lower-case broker identifier (e.g. ``"zerodha"``).
    """

    broker_name: str

    def __init__(self, broker_name: str) -> None:
        self.broker_name = broker_name
        self._tick_callbacks: list[TickCallback] = []
        self._connected: bool = False

    # ------------------------------------------------------------------
    # Abstract interface
    # ------------------------------------------------------------------

    @abstractmethod
    async def connect(self, credentials: dict) -> None:
        """Open a connection to the broker's WebSocket feed.

        Args:
            credentials: Broker-specific auth credentials.
                For most brokers this contains ``api_key`` and ``access_token``.

        Raises:
            ConnectionError: If the broker's WS endpoint is unreachable.
        """
        ...

    @abstractmethod
    async def disconnect(self) -> None:
        """Gracefully close the broker WebSocket connection.

        Should be idempotent — calling on a disconnected adapter is a no-op.
        """
        ...

    @abstractmethod
    async def subscribe(
        self,
        symbol: str,
        exchange: str,
        mode: Mode,
    ) -> None:
        """Subscribe to live ticks for ``symbol`` on ``exchange`` at ``mode``.

        Args:
            symbol: Instrument symbol (e.g. ``"NIFTY"``).
            exchange: Exchange code (e.g. ``"NSE_INDEX"``).
            mode: Subscription granularity — ``"LTP"``, ``"QUOTE"``, or
                ``"DEPTH"``.
        """
        ...

    @abstractmethod
    async def unsubscribe(self, symbol: str, exchange: str) -> None:
        """Stop receiving ticks for ``symbol`` on ``exchange``.

        Args:
            symbol: Instrument symbol.
            exchange: Exchange code.
        """
        ...

    @abstractmethod
    def on_tick(self, callback: TickCallback) -> None:
        """Register a callback to be invoked for every incoming tick.

        Multiple callbacks may be registered; all will be called in
        registration order.

        Args:
            callback: Callable that accepts a single ``dict`` (the tick).
        """
        ...

    # ------------------------------------------------------------------
    # Concrete helpers
    # ------------------------------------------------------------------

    def _register_callback(self, callback: TickCallback) -> None:
        """Append *callback* to the internal list.

        Subclasses that override :meth:`on_tick` can delegate here to
        avoid re-implementing list management.

        Args:
            callback: Tick callback to register.
        """
        self._tick_callbacks.append(callback)

    def _dispatch_tick(self, tick: dict) -> None:
        """Call every registered callback with *tick*.

        Args:
            tick: Normalised tick dict to dispatch.
        """
        for cb in self._tick_callbacks:
            try:
                cb(tick)
            except Exception:
                logger.exception(
                    "Tick callback error for broker=%r symbol=%r",
                    self.broker_name,
                    tick.get("symbol"),
                )

    @property
    def is_connected(self) -> bool:
        """Return ``True`` when the adapter holds an active connection."""
        return self._connected
