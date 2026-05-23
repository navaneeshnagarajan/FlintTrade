"""MockBrokerAdapter — synthetic tick generator for testing.

Produces realistic-looking ticks at a configurable rate without requiring
a real broker connection.  Useful for unit tests, integration tests, and
demo/explore mode.

Tick generation strategy:
- LTP ticks: random walk around a base price per symbol
- QUOTE ticks: LTP + open/high/low/close synthesised from the random walk
- DEPTH ticks: QUOTE + 5-level synthetic order book on each side
- DEPTH20 ticks: QUOTE + 20-level synthetic order book (OpenAlgo v2 mode 4)
"""

from __future__ import annotations

import asyncio
import logging
import random
import time

from .broker_adapter import AbstractBrokerAdapter, Mode, TickCallback
from .depth_20 import Depth20Tick, parse_depth_20_payload

logger = logging.getLogger("flinttrade.gateway.ws_proxy.mock_adapter")

# Mode 4 string constant (OpenAlgo v2 depth with 20 levels)
_MODE_DEPTH20 = "DEPTH20"

# Default base prices for well-known Indian indices and stocks
_DEFAULT_PRICES: dict[str, float] = {
    "NIFTY": 22_000.0,
    "BANKNIFTY": 48_000.0,
    "SENSEX": 72_000.0,
    "FINNIFTY": 21_000.0,
    "RELIANCE": 2_800.0,
    "INFY": 1_500.0,
    "TCS": 3_800.0,
    "HDFCBANK": 1_650.0,
    "ICICIBANK": 1_100.0,
}

_DEFAULT_BASE_PRICE = 1_000.0


class MockBrokerAdapter(AbstractBrokerAdapter):
    """Synthetic tick adapter that generates random-walk ticks.

    Args:
        broker_name: Identifier for this mock instance (default ``"mock"``).
        tick_interval: Seconds between generated ticks per symbol
            (default ``0.1``).
        price_volatility: Fractional price movement per tick
            (default ``0.001`` — 0.1 % per tick).
    """

    def __init__(
        self,
        broker_name: str = "mock",
        tick_interval: float = 0.1,
        price_volatility: float = 0.001,
    ) -> None:
        super().__init__(broker_name)
        self._tick_interval = tick_interval
        self._price_volatility = price_volatility
        # (symbol, exchange) → current price
        self._prices: dict[tuple[str, str], float] = {}
        # (symbol, exchange) → mode
        self._subscriptions: dict[tuple[str, str], Mode] = {}
        self._generator_task: asyncio.Task[None] | None = None

    # ------------------------------------------------------------------
    # AbstractBrokerAdapter implementation
    # ------------------------------------------------------------------

    async def connect(self, credentials: dict) -> None:
        """Simulate a successful broker connection.

        Args:
            credentials: Ignored for the mock adapter.
        """
        self._connected = True
        logger.info("MockBrokerAdapter '%s' connected", self.broker_name)

    async def disconnect(self) -> None:
        """Stop tick generation and mark as disconnected."""
        if self._generator_task is not None and not self._generator_task.done():
            self._generator_task.cancel()
            try:
                await self._generator_task
            except asyncio.CancelledError:
                pass
            self._generator_task = None

        self._connected = False
        logger.info("MockBrokerAdapter '%s' disconnected", self.broker_name)

    async def subscribe(
        self,
        symbol: str,
        exchange: str,
        mode: Mode,
    ) -> None:
        """Add a symbol to the tick generation loop.

        If this is the first subscription, starts the background generator
        task.

        Args:
            symbol: Instrument symbol.
            exchange: Exchange code.
            mode: Tick granularity.
        """
        key = (symbol.upper(), exchange.upper())
        if key not in self._prices:
            self._prices[key] = _DEFAULT_PRICES.get(symbol.upper(), _DEFAULT_BASE_PRICE)
        self._subscriptions[key] = mode

        if self._generator_task is None or self._generator_task.done():
            self._generator_task = asyncio.create_task(
                self._generate_ticks(),
                name=f"mock_tick_generator_{self.broker_name}",
            )
            logger.debug(
                "MockBrokerAdapter '%s': started tick generator", self.broker_name
            )

        logger.debug(
            "MockBrokerAdapter '%s': subscribed %s/%s mode=%s",
            self.broker_name,
            symbol,
            exchange,
            mode,
        )

    async def unsubscribe(self, symbol: str, exchange: str) -> None:
        """Remove a symbol from the tick generation loop.

        Args:
            symbol: Instrument symbol.
            exchange: Exchange code.
        """
        key = (symbol.upper(), exchange.upper())
        self._subscriptions.pop(key, None)
        logger.debug(
            "MockBrokerAdapter '%s': unsubscribed %s/%s",
            self.broker_name,
            symbol,
            exchange,
        )

    def on_tick(self, callback: TickCallback) -> None:
        """Register a tick callback.

        Args:
            callback: Callable receiving a single tick dict.
        """
        self._register_callback(callback)

    # ------------------------------------------------------------------
    # Internal tick generation
    # ------------------------------------------------------------------

    async def _generate_ticks(self) -> None:
        """Background coroutine that emits a tick for every subscribed symbol."""
        logger.debug("MockBrokerAdapter '%s': generator started", self.broker_name)
        try:
            while True:
                for key, mode in list(self._subscriptions.items()):
                    symbol, exchange = key
                    tick = self._build_tick(symbol, exchange, mode)
                    self._dispatch_tick(tick)
                await asyncio.sleep(self._tick_interval)
        except asyncio.CancelledError:
            logger.debug("MockBrokerAdapter '%s': generator cancelled", self.broker_name)

    def _build_tick(self, symbol: str, exchange: str, mode: Mode) -> dict:
        """Build one synthetic tick dict, updating the random-walk price.

        Args:
            symbol: Instrument symbol.
            exchange: Exchange code.
            mode: Tick mode.

        Returns:
            Normalised tick dict.
        """
        key = (symbol, exchange)
        price = self._prices[key]

        # Random walk
        delta = price * self._price_volatility * random.gauss(0, 1)
        price = max(0.05, price + delta)
        self._prices[key] = price

        tick: dict = {
            "symbol": symbol,
            "exchange": exchange,
            "mode": mode,
            "ltp": round(price, 2),
            "timestamp": time.time(),
        }

        if mode in ("QUOTE", "DEPTH", _MODE_DEPTH20):
            spread = price * 0.002
            tick.update(
                {
                    "open": round(price * 0.998, 2),
                    "high": round(price * 1.003, 2),
                    "low": round(price * 0.995, 2),
                    "close": round(price * 0.999, 2),
                    "volume": random.randint(10_000, 500_000),
                    "avg_price": round(price * 1.001, 2),
                }
            )

        if mode == "DEPTH":
            tick["bids"] = [
                {
                    "price": round(price - spread * (i + 1), 2),
                    "qty": random.randint(50, 2_000),
                    "orders": random.randint(1, 20),
                }
                for i in range(5)
            ]
            tick["asks"] = [
                {
                    "price": round(price + spread * (i + 1), 2),
                    "qty": random.randint(50, 2_000),
                    "orders": random.randint(1, 20),
                }
                for i in range(5)
            ]

        if mode == _MODE_DEPTH20:
            # OpenAlgo v2 mode 4 — 20 levels, list-of-lists format
            tick["mode"] = _MODE_DEPTH20
            tick["bids"] = [
                [
                    round(price - spread * (i + 1), 2),
                    random.randint(50, 2_000),
                    random.randint(1, 30),
                ]
                for i in range(20)
            ]
            tick["asks"] = [
                [
                    round(price + spread * (i + 1), 2),
                    random.randint(50, 2_000),
                    random.randint(1, 30),
                ]
                for i in range(20)
            ]
            tick["total_buy_qty"] = sum(lvl[1] for lvl in tick["bids"])
            tick["total_sell_qty"] = sum(lvl[1] for lvl in tick["asks"])

        return tick

    # ------------------------------------------------------------------
    # Test helpers
    # ------------------------------------------------------------------

    def inject_tick(self, tick: dict) -> None:
        """Directly inject a pre-built tick, bypassing the generator.

        Useful in unit tests where precise tick values are required.

        Args:
            tick: Tick dict to dispatch to all registered callbacks.
        """
        self._dispatch_tick(tick)

    def build_depth20_tick(self, symbol: str, exchange: str) -> Depth20Tick:
        """Build a realistic synthetic :class:`~ws_proxy.depth_20.Depth20Tick`.

        Generates a 20-level depth snapshot by calling :meth:`_build_tick`
        with mode ``"DEPTH20"`` and parsing the resulting raw dict.

        Args:
            symbol: Instrument symbol (e.g. ``"NIFTY"``).
            exchange: Exchange code (e.g. ``"NSE_INDEX"``).

        Returns:
            A fully populated :class:`~ws_proxy.depth_20.Depth20Tick`.
        """
        key = (symbol.upper(), exchange.upper())
        if key not in self._prices:
            self._prices[key] = _DEFAULT_PRICES.get(symbol.upper(), _DEFAULT_BASE_PRICE)
        raw = self._build_tick(symbol.upper(), exchange.upper(), _MODE_DEPTH20)  # type: ignore[arg-type]
        return parse_depth_20_payload(raw)

    @property
    def subscribed_symbols(self) -> list[tuple[str, str]]:
        """Return currently subscribed (symbol, exchange) pairs."""
        return list(self._subscriptions.keys())
