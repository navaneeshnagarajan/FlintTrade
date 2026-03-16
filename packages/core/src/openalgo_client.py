"""Synchronous OpenAlgo v1 API client with retry, rate-limiting, and typed responses."""

from __future__ import annotations

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
# Token-bucket rate limiter
# ---------------------------------------------------------------------------

class _RateLimiter:
    """Simple token-bucket rate limiter."""

    def __init__(self, rate: float, per: float = 1.0) -> None:
        self.rate = rate
        self.per = per
        self.tokens = rate
        self._last = time.monotonic()

    def acquire(self) -> None:
        now = time.monotonic()
        elapsed = now - self._last
        self._last = now
        self.tokens = min(self.rate, self.tokens + elapsed * (self.rate / self.per))
        if self.tokens < 1:
            sleep_time = (1 - self.tokens) * (self.per / self.rate)
            time.sleep(sleep_time)
            self.tokens = 0
        else:
            self.tokens -= 1


# ---------------------------------------------------------------------------
# Client
# ---------------------------------------------------------------------------

class OpenAlgoClient:
    """Synchronous client for all OpenAlgo v1 REST endpoints.

    Features:
    - Automatic retry with exponential backoff (3 attempts)
    - Per-category rate limiting (orders: 10/s, smart: 2/s, general: 50/s)
    - Typed request/response models
    - Structured logging
    """

    def __init__(self, settings: Settings | None = None) -> None:
        self.settings = settings or Settings.from_env()
        self._base = f"{self.settings.openalgo_host}/api/v1"
        self._http = httpx.Client(timeout=30.0)
        self._api_key = self.settings.openalgo_api_key

        # Rate limiters per category
        self._order_limiter = _RateLimiter(10, 1.0)
        self._smart_limiter = _RateLimiter(2, 1.0)
        self._general_limiter = _RateLimiter(50, 1.0)

    def close(self) -> None:
        """Close the underlying HTTP client."""
        self._http.close()

    def __enter__(self) -> OpenAlgoClient:
        return self

    def __exit__(self, *args: Any) -> None:
        self.close()

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _body(self, extra: dict[str, Any] | None = None) -> dict[str, Any]:
        """Build request body with apikey injected."""
        payload: dict[str, Any] = {"apikey": self._api_key}
        if extra:
            payload.update(extra)
        return payload

    def _post(
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
        rl.acquire()

        last_exc: Exception | None = None
        for attempt in range(1, max_retries + 1):
            try:
                logger.debug("POST %s attempt=%d", endpoint, attempt)
                resp = self._http.post(url, json=payload)

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
                    time.sleep(wait)
            except RateLimitError:
                last_exc = None
                if attempt < max_retries:
                    wait = 2 ** (attempt - 1)
                    logger.warning("Rate limited on %s, retry in %ds", endpoint, wait)
                    time.sleep(wait)
                else:
                    raise

        raise APIError(0, f"Failed after {max_retries} retries: {last_exc}", endpoint)

    def _get(self, endpoint: str, *, params: dict[str, str] | None = None, headers: dict[str, str] | None = None) -> Any:
        """GET with retry."""
        url = f"{self._base}/{endpoint}"
        self._general_limiter.acquire()

        last_exc: Exception | None = None
        for attempt in range(1, 4):
            try:
                resp = self._http.get(url, params=params, headers=headers or {})
                if resp.status_code >= 400:
                    raise APIError(resp.status_code, resp.text, endpoint)
                return resp.json()
            except (httpx.ConnectError, httpx.TimeoutException) as exc:
                last_exc = exc
                if attempt < 3:
                    time.sleep(2 ** (attempt - 1))
        raise APIError(0, f"GET failed after 3 retries: {last_exc}", endpoint)

    # ==================================================================
    # Order APIs
    # ==================================================================

    def place_order(self, order: Order) -> OrderResponse:
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
        data = self._post("placeorder", payload, limiter=self._order_limiter)
        return OrderResponse(**data)

    def place_smart_order(self, order: SmartOrder) -> OrderResponse:
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
        data = self._post("placesmartorder", payload, limiter=self._smart_limiter)
        return OrderResponse(**data)

    def place_options_order(self, order: OptionsOrder) -> OrderResponse:
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
        data = self._post("optionsorder", payload, limiter=self._order_limiter)
        return OrderResponse(**data)

    def place_options_multi_order(self, order: OptionsMultiOrder) -> OrderResponse:
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
        data = self._post("optionsmultiorder", payload, limiter=self._order_limiter)
        return OrderResponse(**data)

    def place_basket_order(self, basket: BasketOrder) -> OrderResponse:
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
        data = self._post("basketorder", payload, limiter=self._order_limiter)
        return OrderResponse(**data)

    def place_split_order(self, order: SplitOrder) -> OrderResponse:
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
        data = self._post("splitorder", payload, limiter=self._order_limiter)
        return OrderResponse(**data)

    def modify_order(self, order: ModifyOrder) -> OrderResponse:
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
        data = self._post("modifyorder", payload, limiter=self._order_limiter)
        return OrderResponse(**data)

    def cancel_order(self, orderid: str, strategy: str = "Flint") -> OrderResponse:
        """POST /api/v1/cancelorder"""
        payload = self._body({"strategy": strategy, "orderid": orderid})
        data = self._post("cancelorder", payload, limiter=self._order_limiter)
        return OrderResponse(**data)

    def cancel_all_orders(self, strategy: str = "Flint") -> OrderResponse:
        """POST /api/v1/cancelallorder"""
        payload = self._body({"strategy": strategy})
        data = self._post("cancelallorder", payload, limiter=self._order_limiter)
        return OrderResponse(**data)

    def close_position(self, strategy: str = "Flint") -> OrderResponse:
        """POST /api/v1/closeposition"""
        payload = self._body({"strategy": strategy})
        data = self._post("closeposition", payload, limiter=self._order_limiter)
        return OrderResponse(**data)

    def order_status(self, orderid: str, strategy: str = "Flint") -> OrderStatus:
        """POST /api/v1/orderstatus"""
        payload = self._body({"strategy": strategy, "orderid": orderid})
        data = self._post("orderstatus", payload)
        return OrderStatus(**data) if isinstance(data, dict) else OrderStatus()

    def open_position(
        self, symbol: str, exchange: str = "NSE", product: str = "MIS", strategy: str = "Flint"
    ) -> dict[str, Any]:
        """POST /api/v1/openposition"""
        payload = self._body({
            "strategy": strategy,
            "symbol": symbol,
            "exchange": exchange,
            "product": product,
        })
        return self._post("openposition", payload)

    # ==================================================================
    # Data APIs
    # ==================================================================

    def quotes(self, symbol: str, exchange: str = "NSE") -> Quote:
        """POST /api/v1/quotes"""
        payload = self._body({"symbol": symbol, "exchange": exchange})
        data = self._post("quotes", payload)
        return Quote(**data) if isinstance(data, dict) else Quote()

    def multi_quotes(self, symbols: list[dict[str, str]]) -> list[Quote]:
        """POST /api/v1/multiquotes — symbols=[{"symbol": "X", "exchange": "NSE"}, ...]"""
        payload = self._body({"symbols": symbols})
        data = self._post("multiquotes", payload)
        if isinstance(data, list):
            return [Quote(**q) for q in data]
        return []

    def depth(self, symbol: str, exchange: str = "NSE") -> Depth:
        """POST /api/v1/depth"""
        payload = self._body({"symbol": symbol, "exchange": exchange})
        data = self._post("depth", payload)
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

    def history(
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
        data = self._post("history", payload)
        if isinstance(data, list):
            return [OHLCV(**bar) for bar in data]
        return []

    def intervals(self) -> list[str]:
        """POST /api/v1/intervals"""
        data = self._post("intervals", self._body())
        return data if isinstance(data, list) else []

    def option_chain(self, symbol: str, exchange: str = "NFO") -> OptionChain:
        """POST /api/v1/optionchain"""
        payload = self._body({"symbol": symbol, "exchange": exchange})
        data = self._post("optionchain", payload)
        if isinstance(data, dict):
            strikes = [OptionChainStrike(**s) for s in data.get("strikes", [])]
            return OptionChain(
                underlying=data.get("underlying", symbol),
                exchange=data.get("exchange", exchange),
                strikes=strikes,
            )
        return OptionChain()

    def option_greeks(self, symbol: str, exchange: str = "NFO") -> OptionGreek:
        """POST /api/v1/optiongreeks"""
        payload = self._body({"symbol": symbol, "exchange": exchange})
        data = self._post("optiongreeks", payload)
        return OptionGreek(**data) if isinstance(data, dict) else OptionGreek()

    def multi_option_greeks(self, symbols: list[dict[str, str]]) -> list[OptionGreek]:
        """POST /api/v1/multioptiongreeks"""
        payload = self._body({"symbols": symbols})
        data = self._post("multioptiongreeks", payload)
        if isinstance(data, list):
            return [OptionGreek(**g) for g in data]
        return []

    def option_symbol(
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
        return self._post("optionsymbol", payload)

    def synthetic_future(self, symbol: str, exchange: str = "NFO", expiry_date: str = "") -> dict[str, Any]:
        """POST /api/v1/syntheticfuture"""
        payload = self._body({"symbol": symbol, "exchange": exchange, "expiry_date": expiry_date})
        return self._post("syntheticfuture", payload)

    def expiry(self, symbol: str, exchange: str = "NFO") -> dict[str, Any]:
        """POST /api/v1/expiry"""
        payload = self._body({"symbol": symbol, "exchange": exchange})
        return self._post("expiry", payload)

    def symbol(self, symbol: str, exchange: str = "NSE") -> dict[str, Any]:
        """POST /api/v1/symbol"""
        payload = self._body({"symbol": symbol, "exchange": exchange})
        return self._post("symbol", payload)

    def search(self, query: str) -> dict[str, Any]:
        """POST /api/v1/search"""
        payload = self._body({"query": query})
        return self._post("search", payload)

    def ticker(self, exchange: str, symbol: str, interval: str = "5m", from_date: str = "", to_date: str = "") -> Any:
        """GET /api/v1/ticker/{exchange}:{symbol} — uses X-API-KEY header."""
        endpoint = f"ticker/{exchange}:{symbol}"
        params: dict[str, str] = {"interval": interval}
        if from_date:
            params["from"] = from_date
        if to_date:
            params["to"] = to_date
        return self._get(endpoint, params=params, headers={"X-API-KEY": self._api_key})

    # ==================================================================
    # Account APIs
    # ==================================================================

    def funds(self) -> Fund:
        """POST /api/v1/funds"""
        data = self._post("funds", self._body())
        if isinstance(data, dict):
            return Fund(
                available_balance=str(data.get("available_balance", "0")),
                used_margin=str(data.get("used_margin", "0")),
                total_balance=str(data.get("total_balance", "0")),
                extra={k: v for k, v in data.items() if k not in ("available_balance", "used_margin", "total_balance", "status")},
            )
        return Fund()

    def margin(self, positions: list[dict[str, Any]]) -> dict[str, Any]:
        """POST /api/v1/margin"""
        payload = self._body({"positions": positions})
        return self._post("margin", payload)

    def orderbook(self) -> list[OrderStatus]:
        """POST /api/v1/orderbook"""
        data = self._post("orderbook", self._body())
        if isinstance(data, list):
            return [OrderStatus(**o) for o in data]
        return []

    def tradebook(self) -> list[Trade]:
        """POST /api/v1/tradebook"""
        data = self._post("tradebook", self._body())
        if isinstance(data, list):
            return [Trade(**t) for t in data]
        return []

    def positionbook(self) -> list[Position]:
        """POST /api/v1/positionbook"""
        data = self._post("positionbook", self._body())
        if isinstance(data, list):
            return [Position(**p) for p in data]
        return []

    def holdings(self) -> list[Holding]:
        """POST /api/v1/holdings"""
        data = self._post("holdings", self._body())
        if isinstance(data, list):
            return [Holding(**h) for h in data]
        return []

    # ==================================================================
    # Utility APIs
    # ==================================================================

    def ping(self) -> dict[str, Any]:
        """POST /api/v1/ping — health check."""
        return self._post("ping", self._body())

    def holidays(self, year: str = "2026") -> dict[str, Any]:
        """POST /api/v1/holidays"""
        return self._post("holidays", self._body({"year": year}))

    def timings(self, date: str = "") -> dict[str, Any]:
        """POST /api/v1/timings"""
        return self._post("timings", self._body({"date": date}))

    def telegram(self, message: str) -> dict[str, Any]:
        """POST /api/v1/telegram"""
        return self._post("telegram", self._body({"message": message}))

    def instruments(self, exchange: str = "NSE") -> dict[str, Any]:
        """POST /api/v1/instruments"""
        return self._post("instruments", self._body({"exchange": exchange}))

    def analyzer_status(self) -> dict[str, Any]:
        """POST /api/v1/analyzer/status — check if sandbox mode is active."""
        return self._post("analyzer/status", self._body())

    def analyzer_toggle(self) -> dict[str, Any]:
        """POST /api/v1/analyzer/toggle — toggle sandbox/live mode."""
        return self._post("analyzer/toggle", self._body())
