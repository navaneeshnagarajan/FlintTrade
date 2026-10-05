"""Frozen read facade retained for package consumer interfaces.

HTTP reads return 409 and background consumers return 503 until an authorised
native read integration is available. Internal native readers use BrokerReadOwner.
Writes remain owned by the safety gate and BrokerRouter; this facade contains no
broker credentials, network endpoints, or order dispatch method.
"""

from __future__ import annotations

import asyncio
import threading
from typing import Any

from .config import Settings
from .exceptions import APIError


class BrokerClient:
    """Share one event loop for native read calls and routed operations."""

    def __init__(self, settings: Settings | None = None) -> None:
        self.settings = settings or Settings()
        self._app: Any | None = None
        self._loop: asyncio.AbstractEventLoop | None = None
        self._thread: threading.Thread | None = None
        self._lock = threading.Lock()
        self._closed = False

    def bind(self, app: Any) -> None:
        """Bind the application whose current generation owns native sessions."""
        self._app = app

    def run_sync(self, coro: Any, timeout: float = 45.0) -> Any:
        """Run on the same persistent loop used by all native adapter calls."""
        with self._lock:
            if self._closed:
                coro.close()
                raise RuntimeError("Broker read client is closed")
            if self._loop is None:
                loop = asyncio.new_event_loop()
                self._loop = loop
                self._thread = threading.Thread(target=loop.run_forever, name="broker-read-loop", daemon=True)
                self._thread.start()
            loop = self._loop
        return asyncio.run_coroutine_threadsafe(coro, loop).result(timeout)

    async def _read_port(self, operation: str, read_request: Any = None, *, role: str = "quote") -> Any:
        """Preserve the native HTTP read cutover; internal readers use BrokerReadOwner."""
        from flask import has_request_context

        if has_request_context():
            raise APIError(409, "Native broker HTTP reads are unavailable until the read cutover", operation)
        raise APIError(503, "This consumer has no authorised native broker read integration", operation)

    async def ping(self) -> dict[str, Any]:
        await self.funds()
        return {"status": "success", "data": {"connected": True}}

    async def quotes(self, symbol: str, exchange: str) -> Any:
        from dataclasses import asdict

        from .broker_read_port import InstrumentRef, QuoteRequest
        from .models import Quote

        snapshot = await self._read_port("quote", QuoteRequest(InstrumentRef(symbol, exchange)))
        if not snapshot.available or snapshot.ltp is None:
            raise APIError(503, "Native quote is unavailable", "quotes")
        values = asdict(snapshot)
        values.pop("instrument")
        values.pop("available")
        return Quote(
            symbol=symbol, exchange=exchange, **{key: value for key, value in values.items() if value is not None}
        )

    async def multi_quotes(self, symbols: list[dict[str, str]]) -> list[Any]:
        return await asyncio.gather(*(self.quotes(item["symbol"], item["exchange"]) for item in symbols))

    async def depth(self, symbol: str, exchange: str) -> Any:
        from dataclasses import asdict

        from .broker_read_port import InstrumentRef, QuoteRequest
        from .models import Depth

        snapshot = await self._read_port("depth", QuoteRequest(InstrumentRef(symbol, exchange)))
        return Depth(
            symbol=symbol,
            exchange=exchange,
            bids=[asdict(row) for row in snapshot.bids],
            asks=[asdict(row) for row in snapshot.asks],
        )

    async def history(self, symbol: str, exchange: str, interval: str, start_date: str, end_date: str) -> Any:
        from dataclasses import asdict

        from .broker_read_port import HistoricalRequest, InstrumentRef
        from .models import OHLCV

        snapshot = await self._read_port(
            "historical",
            HistoricalRequest(InstrumentRef(symbol, exchange), interval, start_date, end_date),
            role="historical",
        )
        return [OHLCV(**asdict(bar)) for bar in snapshot.bars]

    async def positionbook(self) -> Any:
        return await self._read_port("positions", role="execution")

    async def orderbook(self) -> Any:
        from .broker_read_port import BrokerOrderFamily, OrderStateRequest

        return await self._read_port("order_states", OrderStateRequest(BrokerOrderFamily.REGULAR), role="execution")

    async def tradebook(self) -> Any:
        return await self._read_port("trades", role="execution")

    async def holdings(self) -> Any:
        return await self._read_port("holdings", role="execution")

    async def funds(self) -> Any:
        return await self._read_port("balance", role="execution")

    async def margin(self, positions: Any) -> Any:
        return await self._read_port("margin")

    async def instruments(self, exchange: str = "NSE") -> Any:
        return await self._read_port("instruments")

    async def search(self, query: str, exchange: str = "NSE") -> Any:
        return await self._read_port("search")

    async def option_chain(self, symbol: str, exchange: str, expiry_date: str, **kwargs: Any) -> Any:
        from dataclasses import asdict

        from .broker_read_port import InstrumentRef, OptionChainRequest
        from .models import OptionChain

        snapshot = await self._read_port(
            "option_chain", OptionChainRequest(InstrumentRef(symbol, exchange), expiry_date), role="option_chains"
        )
        if snapshot.spot_price is None:
            raise APIError(503, "Native option-chain spot price is unavailable", "option_chain")
        strikes = [
            {key: value for key, value in asdict(row).items() if value is not None or key in {"ce_oi", "pe_oi"}}
            for row in snapshot.strikes
        ]
        return OptionChain(
            underlying=snapshot.underlying.symbol,
            underlying_key=snapshot.underlying.instrument_id or "",
            exchange=snapshot.underlying.exchange,
            expiry=snapshot.expiry,
            expiry_date=snapshot.expiry,
            spot_price=snapshot.spot_price,
            strikes=strikes,
        )

    async def market_holidays(self, year: int | None = None) -> Any:
        return await self._read_port("market_holidays")

    async def market_timings(self, date: str | None = None) -> Any:
        return await self._read_port("market_timings")

    async def holidays(self, year: str | None = None, **kwargs: Any) -> Any:
        return await self.market_holidays(int(year) if year else None)

    def __getattr__(self, name: str) -> Any:
        read_names = {
            "expiry",
            "expiries",
            "expiry_list",
            "symbol",
            "option_greeks",
            "portfolio_greeks",
            "futures",
            "gtt_list",
            "gtt_get",
            "order_status",
            "intervals",
            "market_status",
        }
        if name not in read_names:
            raise AttributeError(name)

        async def unavailable(*args: Any, **kwargs: Any) -> Any:
            return await self._read_port(name)

        return unavailable

    async def close(self) -> None:
        """Native sessions are disposed by their registry owner, never this facade."""

    async def shutdown(self) -> None:
        self.close_sync()

    def close_sync(self) -> None:
        with self._lock:
            self._closed = True
            loop, thread = self._loop, self._thread
        if loop is not None:
            loop.call_soon_threadsafe(loop.stop)
            if thread is not None and thread is not threading.current_thread():
                thread.join(timeout=5)
            if not loop.is_running():
                loop.close()


def resolve_broker_client(app: Any | None = None) -> tuple[Any, bool]:
    """Return the app-owned native reader; never create an implicit data source."""
    if app is None:
        from flask import current_app

        app = current_app._get_current_object()
    client = app.config.get("CLIENT")
    if client is None:
        raise APIError(503, "Native broker reader is unavailable", "broker_read")
    return client, False


def get_broker_client(app: Any | None = None) -> Any:
    return resolve_broker_client(app)[0]


def client_call_sync(client: Any, coro: Any, timeout: float = 45.0) -> Any:
    if isinstance(client, BrokerClient):
        return client.run_sync(coro, timeout)
    return asyncio.run(coro)


def client_close_sync(client: Any) -> None:
    if isinstance(client, BrokerClient):
        client.close_sync()
    else:
        asyncio.run(client.close())


# Calendar parsing is independent of broker transport and has its own interface.
from .market_calendar import (  # noqa: E402,F401
    is_authoritative_market_calendar,
    normalise_holiday_dates,
    normalise_market_calendar,
)
