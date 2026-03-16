"""Async OpenAlgo v1 API client with retry, rate-limiting, and typed responses."""

from __future__ import annotations

import asyncio
import logging
import time
from typing import Any

import httpx

from .config import Settings
from .exceptions import APIError, AuthError, RateLimitError
from .models import (
    BasketOrder,
    Depth,
    DepthLevel,
    Fund,
    Holding,
    ModifyOrder,
    OHLCV,
    OptionChain,
    OptionChainStrike,
    OptionGreek,
    OptionsMultiOrder,
    OptionsOrder,
    Order,
    OrderResponse,
    OrderStatus,
    Position,
    Quote,
    SmartOrder,
    SplitOrder,
    Trade,
)

logger = logging.getLogger("flinttrade.core")


# ---------------------------------------------------------------------------
# Token-bucket rate limiter (async-compatible)
# ---------------------------------------------------------------------------

class _RateLimiter:
    """Simple token-bucket rate limiter with async acquire."""

    def __init__(self, rate: float, per: float = 1.0) -> None:
        self.rate = rate
        self.per = per
        self.tokens = rate
        self._last = time.monotonic()

    async def acquire(self) -> None:
        now = time.monotonic()
        elapsed = now - self._last
        self._last = now
        self.tokens = min(self.rate, self.tokens + elapsed * (self.rate / self.per))
        if self.tokens < 1:
            sleep_time = (1 - self.tokens) * (self.per / self.rate)
            await asyncio.sleep(sleep_time)
            self.tokens = 0
        else:
            self.tokens -= 1


# ---------------------------------------------------------------------------
# Client
# ---------------------------------------------------------------------------

class OpenAlgoClient:
    """Async client for all OpenAlgo v1 REST endpoints.

    Features:
    - Automatic retry with exponential backoff (3 attempts)
    - Per-category rate limiting (orders: 10/s, smart: 2/s, general: 50/s)
    - Typed request/response models
    - Structured logging
    """

    def __init__(self, settings: Settings | None = None) -> None:
        self.settings = settings or Settings.from_env()
        self._base = f"{self.settings.openalgo_host}/api/v1"
        self._http = httpx.AsyncClient(timeout=30.0)
        self._api_key = self.settings.openalgo_api_key

        # Rate limiters per category
        self._order_limiter = _RateLimiter(10, 1.0)
        self._smart_limiter = _RateLimiter(2, 1.0)
        self._general_limiter = _RateLimiter(50, 1.0)

    async def close(self) -> None:
        """Close the underlying HTTP client."""
        await self._http.aclose()

    async def __aenter__(self) -> OpenAlgoClient:
        return self

    async def __aexit__(self, *args: Any) -> None:
        await self.close()

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _body(self, extra: dict[str, Any] | None = None) -> dict[str, Any]:
        """Build request body with apikey injected."""
        payload: dict[str, Any] = {"apikey": self._api_key}
        if extra:
            payload.update(extra)
        return payload

    @staticmethod
    def _unwrap(data: Any) -> Any:
        """Unwrap OpenAlgo's nested response format.

        OpenAlgo wraps responses as {"status": "success", "data": <payload>}.
        This extracts the "data" value if present, otherwise returns as-is.
        """
        if isinstance(data, dict) and "data" in data:
            return data["data"]
        return data

    async def _post(
        self,
        endpoint: str,
        payload: dict[str, Any],
        *,
        limiter: _RateLimiter | None = None,
        max_retries: int = 3,
    ) -> dict[str, Any]:
        """POST with retry + exponential backoff."""
        url = f"{self._base}/{endpoint}"
        rl = limiter or self._general_limiter
        await rl.acquire()

        last_exc: Exception | None = None
        for attempt in range(1, max_retries + 1):
            try:
                logger.debug("POST %s attempt=%d", endpoint, attempt)
                resp = await self._http.post(url, json=payload)

                if resp.status_code == 429:
                    retry_after = float(resp.headers.get("Retry-After", "1"))
                    raise RateLimitError(endpoint, retry_after)
                if resp.status_code in (401, 403):
                    data = resp.json() if resp.content else {}
                    raise AuthError(endpoint, data.get("message", "Authentication failed"))
                if resp.status_code >= 400:
                    data = resp.json() if resp.content else {}
                    raise APIError(resp.status_code, data.get("message", resp.text), endpoint)

                data = resp.json()
                if isinstance(data, dict) and data.get("status") == "error":
                    raise APIError(resp.status_code, data.get("message", "Unknown error"), endpoint)
                return data

            except (httpx.ConnectError, httpx.TimeoutException) as exc:
                last_exc = exc
                if attempt < max_retries:
                    wait = 2 ** (attempt - 1)
                    logger.warning("Retry %s in %ds: %s", endpoint, wait, exc)
                    await asyncio.sleep(wait)
            except RateLimitError:
                last_exc = None
                if attempt < max_retries:
                    wait = 2 ** (attempt - 1)
                    logger.warning("Rate limited on %s, retry in %ds", endpoint, wait)
                    await asyncio.sleep(wait)
                else:
                    raise

        raise APIError(0, f"Failed after {max_retries} retries: {last_exc}", endpoint)

    async def _get(self, endpoint: str, *, params: dict[str, str] | None = None, headers: dict[str, str] | None = None) -> Any:
        """GET with retry."""
        url = f"{self._base}/{endpoint}"
        await self._general_limiter.acquire()

        last_exc: Exception | None = None
        for attempt in range(1, 4):
            try:
                resp = await self._http.get(url, params=params, headers=headers or {})
                if resp.status_code >= 400:
                    raise APIError(resp.status_code, resp.text, endpoint)
                return resp.json()
            except (httpx.ConnectError, httpx.TimeoutException) as exc:
                last_exc = exc
                if attempt < 3:
                    await asyncio.sleep(2 ** (attempt - 1))
        raise APIError(0, f"GET failed after 3 retries: {last_exc}", endpoint)

    # ==================================================================
    # Order APIs
    # ==================================================================

    async def place_order(self, order: Order) -> OrderResponse:
        """POST /api/v1/placeorder"""
        payload = self._body({
            "strategy": order.strategy,
            "symbol": order.symbol,
            "action": order.action.value,
            "exchange": order.exchange.value,
            "pricetype": order.pricetype.value,
            "product": order.product.value,
            "quantity": order.quantity,
            "price": order.price,
            "trigger_price": order.trigger_price,
            "disclosed_quantity": order.disclosed_quantity,
        })
        data = await self._post("placeorder", payload, limiter=self._order_limiter)
        return OrderResponse(**data)

    async def place_smart_order(self, order: SmartOrder) -> OrderResponse:
        """POST /api/v1/placesmartorder"""
        payload = self._body({
            "strategy": order.strategy,
            "symbol": order.symbol,
            "action": order.action.value,
            "exchange": order.exchange.value,
            "pricetype": order.pricetype.value,
            "product": order.product.value,
            "quantity": order.quantity,
            "price": order.price,
            "trigger_price": order.trigger_price,
            "disclosed_quantity": order.disclosed_quantity,
            "position_size": order.position_size,
        })
        data = await self._post("placesmartorder", payload, limiter=self._smart_limiter)
        return OrderResponse(**data)

    async def place_options_order(self, order: OptionsOrder) -> OrderResponse:
        """POST /api/v1/optionsorder"""
        payload = self._body({
            "strategy": order.strategy,
            "underlying": order.underlying,
            "exchange": order.exchange.value,
            "expiry_date": order.expiry_date,
            "offset": order.offset,
            "option_type": order.option_type.value,
            "action": order.action.value,
            "quantity": order.quantity,
            "pricetype": order.pricetype.value,
            "product": order.product.value,
            "splitsize": order.splitsize,
        })
        data = await self._post("optionsorder", payload, limiter=self._order_limiter)
        return OrderResponse(**data)

    async def place_options_multi_order(self, order: OptionsMultiOrder) -> OrderResponse:
        """POST /api/v1/optionsmultiorder"""
        legs = [
            {
                "offset": leg.offset,
                "option_type": leg.option_type.value,
                "action": leg.action.value,
                "quantity": leg.quantity,
            }
            for leg in order.legs
        ]
        payload = self._body({
            "strategy": order.strategy,
            "underlying": order.underlying,
            "exchange": order.exchange.value,
            "expiry_date": order.expiry_date,
            "legs": legs,
            "pricetype": order.pricetype.value,
            "product": order.product.value,
        })
        data = await self._post("optionsmultiorder", payload, limiter=self._order_limiter)
        return OrderResponse(**data)

    async def place_basket_order(self, basket: BasketOrder) -> OrderResponse:
        """POST /api/v1/basketorder"""
        orders = [
            {
                "symbol": o.symbol,
                "exchange": o.exchange.value,
                "action": o.action.value,
                "quantity": o.quantity,
                "pricetype": o.pricetype.value,
                "product": o.product.value,
            }
            for o in basket.orders
        ]
        payload = self._body({"strategy": basket.strategy, "orders": orders})
        data = await self._post("basketorder", payload, limiter=self._order_limiter)
        return OrderResponse(**data)

    async def place_split_order(self, order: SplitOrder) -> OrderResponse:
        """POST /api/v1/splitorder"""
        payload = self._body({
            "strategy": order.strategy,
            "symbol": order.symbol,
            "action": order.action.value,
            "exchange": order.exchange.value,
            "pricetype": order.pricetype.value,
            "product": order.product.value,
            "quantity": order.quantity,
            "price": order.price,
            "trigger_price": order.trigger_price,
            "disclosed_quantity": order.disclosed_quantity,
            "splitsize": order.splitsize,
        })
        data = await self._post("splitorder", payload, limiter=self._order_limiter)
        return OrderResponse(**data)

    async def modify_order(self, order: ModifyOrder) -> OrderResponse:
        """POST /api/v1/modifyorder"""
        payload = self._body({
            "strategy": order.strategy,
            "orderid": order.orderid,
            "symbol": order.symbol,
            "exchange": order.exchange.value,
            "action": order.action.value,
            "pricetype": order.pricetype.value,
            "product": order.product.value,
            "quantity": order.quantity,
            "price": order.price,
        })
        data = await self._post("modifyorder", payload, limiter=self._order_limiter)
        return OrderResponse(**data)

    async def cancel_order(self, orderid: str, strategy: str = "Flint") -> OrderResponse:
        """POST /api/v1/cancelorder"""
        payload = self._body({"strategy": strategy, "orderid": orderid})
        data = await self._post("cancelorder", payload, limiter=self._order_limiter)
        return OrderResponse(**data)

    async def cancel_all_orders(self, strategy: str = "Flint") -> OrderResponse:
        """POST /api/v1/cancelallorder"""
        payload = self._body({"strategy": strategy})
        data = await self._post("cancelallorder", payload, limiter=self._order_limiter)
        return OrderResponse(**data)

    async def close_position(self, strategy: str = "Flint") -> OrderResponse:
        """POST /api/v1/closeposition"""
        payload = self._body({"strategy": strategy})
        data = await self._post("closeposition", payload, limiter=self._order_limiter)
        return OrderResponse(**data)

    async def order_status(self, orderid: str, strategy: str = "Flint") -> OrderStatus:
        """POST /api/v1/orderstatus"""
        payload = self._body({"strategy": strategy, "orderid": orderid})
        data = self._unwrap(await self._post("orderstatus", payload))
        return OrderStatus(**data) if isinstance(data, dict) else OrderStatus()

    async def open_position(
        self, symbol: str, exchange: str = "NSE", product: str = "MIS", strategy: str = "Flint"
    ) -> dict[str, Any]:
        """POST /api/v1/openposition"""
        payload = self._body({
            "strategy": strategy,
            "symbol": symbol,
            "exchange": exchange,
            "product": product,
        })
        return await self._post("openposition", payload)

    # ==================================================================
    # Data APIs
    # ==================================================================

    async def quotes(self, symbol: str, exchange: str = "NSE") -> Quote:
        """POST /api/v1/quotes"""
        payload = self._body({"symbol": symbol, "exchange": exchange})
        data = self._unwrap(await self._post("quotes", payload))
        return Quote(**data) if isinstance(data, dict) else Quote()

    async def multi_quotes(self, symbols: list[dict[str, str]]) -> list[Quote]:
        """POST /api/v1/multiquotes — symbols=[{"symbol": "X", "exchange": "NSE"}, ...]"""
        payload = self._body({"symbols": symbols})
        data = self._unwrap(await self._post("multiquotes", payload))
        if isinstance(data, list):
            return [Quote(**q) for q in data]
        return []

    async def depth(self, symbol: str, exchange: str = "NSE") -> Depth:
        """POST /api/v1/depth"""
        payload = self._body({"symbol": symbol, "exchange": exchange})
        data = self._unwrap(await self._post("depth", payload))
        if not isinstance(data, dict):
            return Depth()
        bids = [DepthLevel(**b) for b in data.get("bids", [])]
        asks = [DepthLevel(**a) for a in data.get("asks", [])]
        return Depth(
            symbol=data.get("symbol", symbol),
            exchange=data.get("exchange", exchange),
            bids=bids,
            asks=asks,
        )

    async def history(
        self,
        symbol: str,
        exchange: str = "NSE",
        interval: str = "5m",
        start_date: str = "",
        end_date: str = "",
    ) -> list[OHLCV]:
        """POST /api/v1/history"""
        payload = self._body({
            "symbol": symbol,
            "exchange": exchange,
            "interval": interval,
            "start_date": start_date,
            "end_date": end_date,
        })
        data = self._unwrap(await self._post("history", payload))
        if isinstance(data, list):
            return [OHLCV(**bar) for bar in data]
        return []

    async def intervals(self) -> list[str]:
        """POST /api/v1/intervals"""
        data = self._unwrap(await self._post("intervals", self._body()))
        return data if isinstance(data, list) else []

    async def option_chain(self, symbol: str, exchange: str = "NFO") -> OptionChain:
        """POST /api/v1/optionchain"""
        payload = self._body({"symbol": symbol, "exchange": exchange})
        data = self._unwrap(await self._post("optionchain", payload))
        if isinstance(data, dict):
            strikes = [OptionChainStrike(**s) for s in data.get("strikes", [])]
            return OptionChain(
                underlying=data.get("underlying", symbol),
                exchange=data.get("exchange", exchange),
                strikes=strikes,
            )
        return OptionChain()

    async def option_greeks(self, symbol: str, exchange: str = "NFO") -> OptionGreek:
        """POST /api/v1/optiongreeks"""
        payload = self._body({"symbol": symbol, "exchange": exchange})
        data = self._unwrap(await self._post("optiongreeks", payload))
        return OptionGreek(**data) if isinstance(data, dict) else OptionGreek()

    async def multi_option_greeks(self, symbols: list[dict[str, str]]) -> list[OptionGreek]:
        """POST /api/v1/multioptiongreeks"""
        payload = self._body({"symbols": symbols})
        data = self._unwrap(await self._post("multioptiongreeks", payload))
        if isinstance(data, list):
            return [OptionGreek(**g) for g in data]
        return []

    async def option_symbol(
        self,
        symbol: str,
        exchange: str = "NFO",
        expiry_date: str = "",
        offset: str = "0",
        option_type: str = "CE",
    ) -> dict[str, Any]:
        """POST /api/v1/optionsymbol"""
        payload = self._body({
            "symbol": symbol,
            "exchange": exchange,
            "expiry_date": expiry_date,
            "offset": offset,
            "option_type": option_type,
        })
        return await self._post("optionsymbol", payload)

    async def synthetic_future(self, symbol: str, exchange: str = "NFO", expiry_date: str = "") -> dict[str, Any]:
        """POST /api/v1/syntheticfuture"""
        payload = self._body({"symbol": symbol, "exchange": exchange, "expiry_date": expiry_date})
        return await self._post("syntheticfuture", payload)

    async def expiry(self, symbol: str, exchange: str = "NFO") -> dict[str, Any]:
        """POST /api/v1/expiry"""
        payload = self._body({"symbol": symbol, "exchange": exchange})
        return await self._post("expiry", payload)

    async def symbol(self, symbol: str, exchange: str = "NSE") -> dict[str, Any]:
        """POST /api/v1/symbol"""
        payload = self._body({"symbol": symbol, "exchange": exchange})
        return await self._post("symbol", payload)

    async def search(self, query: str) -> dict[str, Any]:
        """POST /api/v1/search"""
        payload = self._body({"query": query})
        return await self._post("search", payload)

    async def ticker(self, exchange: str, symbol: str, interval: str = "5m", from_date: str = "", to_date: str = "") -> Any:
        """GET /api/v1/ticker/{exchange}:{symbol} — uses X-API-KEY header."""
        endpoint = f"ticker/{exchange}:{symbol}"
        params: dict[str, str] = {"interval": interval}
        if from_date:
            params["from"] = from_date
        if to_date:
            params["to"] = to_date
        return await self._get(endpoint, params=params, headers={"X-API-KEY": self._api_key})

    # ==================================================================
    # Account APIs
    # ==================================================================

    async def funds(self) -> Fund:
        """POST /api/v1/funds"""
        raw = await self._post("funds", self._body())
        data = self._unwrap(raw)
        if isinstance(data, dict):
            # OpenAlgo uses flat names: availablecash, usedmargin, totalbalance
            avail = data.get("availablecash", data.get("available_balance", "0"))
            used = data.get("usedmargin", data.get("used_margin", "0"))
            total = data.get("totalbalance", data.get("total_balance", "0"))
            known = {"availablecash", "usedmargin", "totalbalance",
                     "available_balance", "used_margin", "total_balance", "status"}
            return Fund(
                available_balance=str(avail),
                used_margin=str(used),
                total_balance=str(total),
                extra={k: v for k, v in data.items() if k not in known},
            )
        return Fund()

    async def margin(self, positions: list[dict[str, Any]]) -> dict[str, Any]:
        """POST /api/v1/margin"""
        payload = self._body({"positions": positions})
        return await self._post("margin", payload)

    async def orderbook(self) -> list[OrderStatus]:
        """POST /api/v1/orderbook"""
        data = self._unwrap(await self._post("orderbook", self._body()))
        if isinstance(data, list):
            return [OrderStatus(**o) for o in data]
        return []

    async def tradebook(self) -> list[Trade]:
        """POST /api/v1/tradebook"""
        data = self._unwrap(await self._post("tradebook", self._body()))
        if isinstance(data, list):
            return [Trade(**t) for t in data]
        return []

    async def positionbook(self) -> list[Position]:
        """POST /api/v1/positionbook"""
        data = self._unwrap(await self._post("positionbook", self._body()))
        if isinstance(data, list):
            return [Position(**p) for p in data]
        return []

    async def holdings(self) -> list[Holding]:
        """POST /api/v1/holdings"""
        data = self._unwrap(await self._post("holdings", self._body()))
        if isinstance(data, list):
            return [Holding(**h) for h in data]
        return []

    # ==================================================================
    # Utility APIs
    # ==================================================================

    async def ping(self) -> dict[str, Any]:
        """POST /api/v1/ping — health check."""
        return await self._post("ping", self._body())

    async def holidays(self, year: str = "2026") -> dict[str, Any]:
        """POST /api/v1/holidays"""
        return await self._post("holidays", self._body({"year": year}))

    async def timings(self, date: str = "") -> dict[str, Any]:
        """POST /api/v1/timings"""
        return await self._post("timings", self._body({"date": date}))

    async def telegram(self, message: str) -> dict[str, Any]:
        """POST /api/v1/telegram"""
        return await self._post("telegram", self._body({"message": message}))

    async def instruments(self, exchange: str = "NSE") -> dict[str, Any]:
        """POST /api/v1/instruments"""
        return await self._post("instruments", self._body({"exchange": exchange}))

    async def analyzer_status(self) -> dict[str, Any]:
        """POST /api/v1/analyzer/status — check if sandbox mode is active."""
        return await self._post("analyzer/status", self._body())

    async def analyzer_toggle(self) -> dict[str, Any]:
        """POST /api/v1/analyzer/toggle — toggle sandbox/live mode."""
        return await self._post("analyzer/toggle", self._body())
