"""Async OpenAlgo v1 API client with retry, rate-limiting, and typed responses."""

from __future__ import annotations

import asyncio
import logging
import threading
import time
from concurrent.futures import TimeoutError as FuturesTimeoutError
from typing import Any

import httpx

from .config import Settings, openalgo_rest_base_url
from .exceptions import APIError, OpenAlgoAuthError, OpenAlgoRateLimitError
from .models import (
    BasketOrder,
    CancelGttOrder,
    Depth,
    DepthLevel,
    Fund,
    GttOrder,
    GttTrigger,
    Holding,
    ModifyGttOrder,
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
        self._lock = asyncio.Lock()

    async def acquire(self) -> None:
        async with self._lock:
            now = time.monotonic()
            elapsed = now - self._last
            self._last = now
            self.tokens = min(self.rate, self.tokens + elapsed * self.rate / self.per)
            if self.tokens < 1:
                sleep_time = (1 - self.tokens) * self.per / self.rate
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
        self._base = f"{openalgo_rest_base_url(self.settings)}/api/v1"
        self._http = httpx.AsyncClient(timeout=30.0)
        self._api_key = self.settings.openalgo_api_key

        # Rate limiters per category
        self._order_limiter = _RateLimiter(10, 1.0)
        self._smart_limiter = _RateLimiter(2, 1.0)
        self._general_limiter = _RateLimiter(50, 1.0)

        # Owner event loop for sync callers (created lazily by run_sync).
        # httpx pools keep-alive connections that are AFFINE to the loop they
        # were created on; driving one shared client from a fresh
        # asyncio.run()/new_event_loop() per request reuses a connection whose
        # transport belongs to an already-closed loop and fails with
        # "Event loop is closed" on alternating requests. All sync entry
        # points must marshal onto this single persistent loop instead.
        self._owner_loop: asyncio.AbstractEventLoop | None = None
        self._owner_thread: threading.Thread | None = None
        self._owner_guard = threading.Lock()
        self._config_guard = threading.RLock()

    def reconfigure(self, settings: Settings) -> OpenAlgoClient:
        """Atomically update endpoint and credentials without replacing this client.

        The broker router, schedulers, cron jobs and Telegram all retain this
        object. Updating it in place keeps every caller on one connection owner
        instead of closing an object that those live services still reference.
        """
        base = f"{openalgo_rest_base_url(settings)}/api/v1"
        api_key = settings.openalgo_api_key
        with self._config_guard:
            self.settings = settings
            self._base = base
            self._api_key = api_key
        return self

    def _ensure_owner_loop(self) -> asyncio.AbstractEventLoop:
        """Start (once) and return the client's dedicated event loop."""
        with self._owner_guard:
            if self._owner_loop is None or self._owner_loop.is_closed():
                loop = asyncio.new_event_loop()
                thread = threading.Thread(
                    target=loop.run_forever,
                    daemon=True,
                    name="openalgo-client-loop",
                )
                thread.start()
                self._owner_loop = loop
                self._owner_thread = thread
            return self._owner_loop

    def run_sync(self, coro: Any, timeout: float = 45.0) -> Any:
        """Run one of THIS client's coroutines from synchronous code.

        The coroutine executes on the client's own persistent event loop, so
        pooled connections always live and die on one loop — never drive this
        client through ad-hoc ``asyncio.run()`` loops. Thread-safe; for Flask
        request threads, cron jobs and background schedulers.

        Args:
            coro: A coroutine created from this client's async API.
            timeout: Seconds to wait for completion.

        Returns:
            The coroutine's result.

        Raises:
            TimeoutError: When the call does not finish within ``timeout``
                (the underlying task is cancelled).
        """
        future = asyncio.run_coroutine_threadsafe(coro, self._ensure_owner_loop())
        try:
            return future.result(timeout)
        except FuturesTimeoutError as exc:
            future.cancel()
            raise TimeoutError(f"OpenAlgo call timed out after {timeout:.0f}s") from exc

    async def close(self) -> None:
        """Close the underlying HTTP client."""
        await self._http.aclose()

    def close_sync(self, timeout: float = 10.0) -> None:
        """Close from synchronous code, tearing down the owner loop if any.

        Short-lived clients used by sync callers (``resolve_openalgo_client``
        fallbacks) must close on the SAME loop that served their requests —
        closing on a second fresh loop is the same cross-loop bug in reverse.
        """
        if self._owner_loop is not None and not self._owner_loop.is_closed():
            loop = self._owner_loop
            try:
                asyncio.run_coroutine_threadsafe(self.close(), loop).result(timeout)
            except Exception:  # pragma: no cover - best-effort shutdown
                logger.debug("OpenAlgo client close on owner loop failed", exc_info=True)
            loop.call_soon_threadsafe(loop.stop)
            if self._owner_thread is not None:
                self._owner_thread.join(timeout=5)
            loop.close()
            self._owner_loop = None
            self._owner_thread = None
        else:
            # Never used from sync code — no owner loop, close on a fresh one.
            asyncio.run(self.close())

    async def __aenter__(self) -> OpenAlgoClient:
        return self

    async def __aexit__(self, *args: Any) -> None:
        await self.close()

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _body(self, extra: dict[str, Any] | None = None) -> dict[str, Any]:
        """Build request body with apikey injected."""
        with self._config_guard:
            api_key = self._api_key
        payload: dict[str, Any] = {"apikey": api_key}
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
        with self._config_guard:
            url = f"{self._base}/{endpoint}"
            request_payload = dict(payload)
            if "apikey" in request_payload:
                request_payload["apikey"] = self._api_key
        rl = limiter or self._general_limiter
        await rl.acquire()

        last_exc: Exception | None = None
        for attempt in range(1, max_retries + 1):
            try:
                logger.debug("POST %s attempt=%d", endpoint, attempt)
                resp = await self._http.post(url, json=request_payload)

                if resp.status_code == 429:
                    retry_after = float(resp.headers.get("Retry-After", "1"))
                    raise OpenAlgoRateLimitError(endpoint, retry_after)
                if resp.status_code in (401, 403):
                    data = resp.json() if resp.content else {}
                    raise OpenAlgoAuthError(
                        endpoint,
                        data.get("message", "Authentication failed"),
                        status_code=resp.status_code,
                    )
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
            except OpenAlgoRateLimitError:
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
        with self._config_guard:
            url = f"{self._base}/{endpoint}"
            request_headers = dict(headers or {})
            for name in tuple(request_headers):
                if name.lower() in {"x-api-key", "x-api_key"}:
                    request_headers[name] = self._api_key
        await self._general_limiter.acquire()

        last_exc: Exception | None = None
        for attempt in range(1, 4):
            try:
                resp = await self._http.get(url, params=params, headers=request_headers)
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
        """POST /api/v1/placeorder

        Supports Market Price Protection (MPP): when ``order.market_protection``
        is True and the broker supports it, MARKET orders are converted to
        LIMIT orders with an exchange-regulated price buffer.
        """
        extras: dict[str, Any] = {
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
        }
        if order.market_protection is not None:
            extras["market_protection"] = order.market_protection
        payload = self._body(extras)
        data = await self._post("placeorder", payload, limiter=self._order_limiter)
        return OrderResponse(**data)

    async def place_smart_order(self, order: SmartOrder) -> OrderResponse:
        """POST /api/v1/placesmartorder

        Supports Market Price Protection (MPP) — see ``place_order``.
        """
        extras: dict[str, Any] = {
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
        }
        if order.market_protection is not None:
            extras["market_protection"] = order.market_protection
        payload = self._body(extras)
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
        """GET /api/v1/intervals"""
        data = self._unwrap(await self._get("intervals"))
        return data if isinstance(data, list) else []

    async def option_chain(self, symbol: str, exchange: str = "NFO", expiry: str = "") -> OptionChain:
        """POST /api/v1/optionchain"""
        payload_data = {"symbol": symbol, "underlying": symbol, "exchange": exchange}
        if expiry:
            payload_data["expiry"] = expiry
            payload_data["expiry_date"] = expiry.replace("-", "")
        payload = self._body(payload_data)
        data = self._unwrap(await self._post("optionchain", payload))
        if isinstance(data, dict):
            raw_strikes = data.get("strikes", data.get("chain", []))
            normalised_strikes: list[dict[str, Any]] = []
            for strike in raw_strikes:
                if not isinstance(strike, dict):
                    continue
                if "ce" in strike or "pe" in strike:
                    ce = strike.get("ce") if isinstance(strike.get("ce"), dict) else {}
                    pe = strike.get("pe") if isinstance(strike.get("pe"), dict) else {}
                    normalised_strikes.append({
                        "strike_price": strike.get("strike", strike.get("strike_price", 0.0)),
                        "ce_ltp": ce.get("ltp", ce.get("last_price", 0.0)),
                        "ce_oi": ce.get("oi", ce.get("open_interest", 0)),
                        "ce_volume": ce.get("volume", 0),
                        "ce_iv": ce.get("iv", ce.get("implied_volatility", 0.0)),
                        "pe_ltp": pe.get("ltp", pe.get("last_price", 0.0)),
                        "pe_oi": pe.get("oi", pe.get("open_interest", 0)),
                        "pe_volume": pe.get("volume", 0),
                        "pe_iv": pe.get("iv", pe.get("implied_volatility", 0.0)),
                    })
                else:
                    normalised_strikes.append(strike)
            strikes = [OptionChainStrike(**s) for s in normalised_strikes]
            return OptionChain(
                underlying=data.get("underlying", data.get("symbol", symbol)),
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

    async def search(
        self,
        query: str,
        exchange: str | None = None,
    ) -> dict[str, Any]:
        """POST /api/v1/search.

        Args:
            query: Search query / symbol prefix.
            exchange: Optional exchange filter. Upstream accepts a single
                exchange code (e.g. ``"NSE"``) and validates it against
                ``VALID_EXCHANGES``. Pass ``None`` (default) to search
                across all exchanges; this preserves the v0.5.0 behaviour.
                Mirrors the upstream OpenAlgo v2.0.1.x ``SearchSchema``.
        """
        body: dict[str, Any] = {"query": query}
        if exchange:
            body["exchange"] = exchange
        return await self._post("search", self._body(body))

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
        """GET /api/v1/holidays"""
        params: dict[str, str] = {"year": year}
        return await self._get("holidays", params=params)

    async def timings(self, date: str = "") -> dict[str, Any]:
        """GET /api/v1/timings"""
        params: dict[str, str] = {"date": date} if date else {}
        return await self._get("timings", params=params)

    async def telegram(self, message: str) -> dict[str, Any]:
        """POST /api/v1/telegram"""
        return await self._post("telegram", self._body({"message": message}))

    async def instruments(self, exchange: str = "NSE") -> dict[str, Any]:
        """POST /api/v1/instruments"""
        return await self._post("instruments", self._body({"exchange": exchange}))

    async def analyzer_status(self) -> dict[str, Any]:
        """POST /api/v1/analyzer/status — check whether sandbox trading
        mode is active on the connected OpenAlgo instance.

        Upstream renamed "virtual / paper trading" to "sandbox trading"
        in v2.0.0.6; route slugs (``analyzer/status``, ``analyzer/toggle``)
        and response keys (``analyzer_status``, ``analyzer_update``) were
        kept stable so this wrapper is unchanged.
        """
        return await self._post("analyzer/status", self._body())

    async def analyzer_toggle(self) -> dict[str, Any]:
        """POST /api/v1/analyzer/toggle — toggle between sandbox trading
        mode and live mode on the connected OpenAlgo instance.

        See :meth:`analyzer_status` for the v2.0.0.6 terminology note.
        """
        return await self._post("analyzer/toggle", self._body())

    # NOTE (HG1, removed 2026-07-06): eight wrappers formerly here (health, gex,
    # iv_smile, max_pain, oi_profile, broker_capabilities, pnl_symbols,
    # leverage_settings) called OpenAlgo routes that do not exist upstream
    # (verified against the pinned clone's restx_api) — guaranteed 404s with
    # zero callers. The analytics capabilities live natively in
    # flinttrade_screener (OIAnalysis, IV smile, GEX, max pain, OI profile) and
    # broker capability metadata is served by the unified catalogue routes.

    # ==================================================================
    # GTT (Good Till Triggered) — added in OpenAlgo v2.0.0.9
    # ==================================================================
    #
    # Live broker support upstream: Dhan + Zerodha. Other brokers return
    # a clean 501 ("GTT orders are not supported for broker 'X' yet").
    # FlintTrade forwards whatever OpenAlgo replies; we do NOT gate
    # client-side because broker support can change between releases.

    async def place_gtt(self, gtt: GttOrder) -> OrderResponse:
        """POST /api/v1/placegttorder — place a Good Till Triggered order.

        Single or two-leg OCO depending on ``gtt.trigger_type``. Upstream
        validates ``triggerprice_sl`` / ``triggerprice_tg`` against the
        trigger type and rejects ``MIS`` product at the schema layer.
        """
        payload = self._body(gtt.model_dump(exclude_none=True))
        raw = await self._post("placegttorder", payload)
        data = self._unwrap(raw)
        if isinstance(data, dict):
            return OrderResponse(
                status=str(data.get("status", "")),
                orderid=str(data.get("orderid", data.get("trigger_id", ""))),
                message=str(data.get("message", "")),
            )
        return OrderResponse(status="error", message=str(data))

    async def modify_gtt(self, gtt: ModifyGttOrder) -> OrderResponse:
        """POST /api/v1/modifygttorder — modify an active GTT.

        Modify is a full replacement: the broker's PUT semantics replace
        trigger prices, last price, and order params atomically.
        """
        payload = self._body(gtt.model_dump(exclude_none=True))
        raw = await self._post("modifygttorder", payload)
        data = self._unwrap(raw)
        if isinstance(data, dict):
            return OrderResponse(
                status=str(data.get("status", "")),
                orderid=str(data.get("orderid", data.get("trigger_id", ""))),
                message=str(data.get("message", "")),
            )
        return OrderResponse(status="error", message=str(data))

    async def cancel_gtt(self, cancel: CancelGttOrder) -> OrderResponse:
        """POST /api/v1/cancelgttorder — cancel an active GTT by ``trigger_id``."""
        payload = self._body(cancel.model_dump(exclude_none=True))
        raw = await self._post("cancelgttorder", payload)
        data = self._unwrap(raw)
        if isinstance(data, dict):
            return OrderResponse(
                status=str(data.get("status", "")),
                orderid=str(data.get("orderid", cancel.trigger_id)),
                message=str(data.get("message", "")),
            )
        return OrderResponse(status="error", message=str(data))

    async def gtt_orderbook(self) -> list[GttTrigger]:
        """POST /api/v1/gttorderbook — list active GTT triggers.

        Upstream broker mappers drop terminal-state rows (Dhan filters
        TRADED/EXPIRED/CANCELLED/REJECTED; Zerodha drops triggered/
        disabled/expired/cancelled/rejected/deleted) so the returned list
        reflects only live, waiting triggers.
        """
        raw = await self._post("gttorderbook", self._body())
        data = self._unwrap(raw)
        if isinstance(data, list):
            triggers: list[GttTrigger] = []
            for row in data:
                if isinstance(row, dict):
                    # Coerce non-string fields to str so the model never
                    # rejects a numeric payload from a broker SDK.
                    safe = {k: ("" if v is None else str(v)) for k, v in row.items()}
                    try:
                        triggers.append(GttTrigger(**{
                            k: safe[k] for k in safe
                            if k in GttTrigger.model_fields
                        }))
                    except Exception:  # pragma: no cover - tolerant boundary
                        triggers.append(GttTrigger())
            return triggers
        if isinstance(data, dict):
            inner = data.get("data") if isinstance(data.get("data"), list) else None
            if isinstance(inner, list):
                return [
                    GttTrigger(**{
                        k: ("" if v is None else str(v))
                        for k, v in row.items()
                        if k in GttTrigger.model_fields
                    })
                    for row in inner
                    if isinstance(row, dict)
                ]
        return []


def _configured_app_client(app: Any | None = None) -> Any | None:
    """Return the Flask app-owned OpenAlgo client when one is configured."""
    if app is None:
        try:
            from flask import current_app  # noqa: PLC0415

            app = current_app._get_current_object()
        except Exception:  # pragma: no cover - no Flask app context available
            return None

    try:
        return app.config.get("CLIENT")
    except AttributeError:
        return None


def resolve_openalgo_client(app: Any | None = None) -> tuple[Any, bool]:
    """Return an OpenAlgo client plus whether the caller owns its lifecycle.

    Flask routes should prefer the client held in ``app.config["CLIENT"]`` so
    workspace/UI OpenAlgo settings are honoured. Standalone imports and tests
    without an app context still receive a short-lived env/workspace-backed
    client and should close it after use.
    """
    configured_client = _configured_app_client(app)
    if configured_client is not None:
        return configured_client, False
    return OpenAlgoClient(Settings.from_env()), True


def get_openalgo_client(app: Any | None = None) -> Any:
    """Return the configured OpenAlgo client, falling back to Settings.from_env()."""
    client, _owns_client = resolve_openalgo_client(app)
    return client


def client_call_sync(client: Any, coro: Any, timeout: float = 45.0) -> Any:
    """Run a client coroutine from sync code on the client's OWNER loop.

    The one safe way to drive an :class:`OpenAlgoClient` from a Flask request
    thread or scheduler job — pooled httpx connections are loop-affine, so a
    fresh ``asyncio.run()`` per call poisons the shared pool ("Event loop is
    closed" on alternating requests). Falls back to ``asyncio.run`` only for
    duck-typed test fakes that expose no ``run_sync``.
    """
    if isinstance(client, OpenAlgoClient):
        return client.run_sync(coro, timeout)
    # Duck-typed fakes/mocks in tests: a plain fresh loop is correct there
    # (single call, no shared pool). getattr-probing is NOT safe here because
    # MagicMock fabricates a run_sync attribute.
    return asyncio.run(coro)


def client_close_sync(client: Any) -> None:
    """Close a client from sync code on the SAME loop that served its calls."""
    if isinstance(client, OpenAlgoClient):
        client.close_sync()
        return
    asyncio.run(client.close())
