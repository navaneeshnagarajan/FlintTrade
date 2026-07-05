"""Broker Interface — Protocol, models, registry, and OpenAlgo concrete implementation.

Adapts patterns from openbull (per-broker plugin directory with standard interface)
and adapts them to FlintTrade's architecture where OpenAlgo is the single
broker gateway layer.

The :class:`BrokerInterface` Protocol defines the contract every broker adapter
must satisfy.  Duck-typing (structural subtyping) is used instead of ABC
inheritance, keeping adapters independent and testable in isolation.

The :class:`OpenAlgoBroker` is the primary concrete implementation that
delegates all calls to OpenAlgo's REST API via
``flinttrade_core.openalgo_client``.  Broker-specific adapters (future) can
implement the same Protocol independently.

Usage::

    from flinttrade_gateway.broker_interface import BrokerRegistry, OpenAlgoBroker
    from flinttrade_core.openalgo_client import OpenAlgoClient

    client = OpenAlgoClient(host="http://localhost:5000", api_key="...")
    broker = OpenAlgoBroker(client=client)

    registry = BrokerRegistry()
    registry.register("openalgo", broker)

    positions = registry.get_broker("openalgo").get_positions()
"""

from __future__ import annotations

import logging
from datetime import datetime
from typing import Any, Callable, Protocol, runtime_checkable

from pydantic import BaseModel, Field

from .log_safety import log_ref

logger = logging.getLogger("flinttrade.gateway.broker_interface")


_SENSITIVE_ERROR_FRAGMENTS = (
    "\n",
    "\r",
    "traceback",
    'file "',
    "password",
    "secret",
    "token",
    "api_key",
    "api key",
    "jwt",
    "http://",
    "https://",
)


def _safe_error_message(exc: BaseException, fallback: str) -> str:
    """Return a bounded operational error without exposing sensitive details."""
    message = str(exc).strip()
    if not message or len(message) > 160:
        return fallback
    lowered = message.lower()
    if any(fragment in lowered for fragment in _SENSITIVE_ERROR_FRAGMENTS):
        return fallback
    return message


# ---------------------------------------------------------------------------
# Shared model types
# ---------------------------------------------------------------------------


class BrokerCredentials(BaseModel):
    """Credentials used to authenticate with a broker.

    Args:
        api_key: Broker API key or access token.
        api_secret: Broker API secret (optional — not all brokers require it).
        client_id: Client / user ID used by the broker.
        access_token: Pre-obtained session token (e.g. from OAuth callback).
        extra: Any additional broker-specific credential fields.
    """

    api_key: str = ""
    api_secret: str = ""
    client_id: str = ""
    access_token: str = ""
    extra: dict[str, Any] = Field(default_factory=dict)


class AuthResult(BaseModel):
    """Result of a broker authentication attempt.

    Args:
        success: Whether authentication succeeded.
        access_token: Session token to use for subsequent API calls.
        expires_at: UTC expiry datetime of the token (``None`` if not known).
        error: Human-readable error message on failure.
        raw: Raw broker response for debugging.
    """

    success: bool
    access_token: str = ""
    expires_at: datetime | None = None
    error: str | None = None
    raw: dict[str, Any] = Field(default_factory=dict)


class OrderRequest(BaseModel):
    """A normalised order request for any broker.

    Args:
        symbol: Instrument symbol (e.g. ``"NIFTY26APR24500CE"``).
        exchange: Exchange code (e.g. ``"NFO"``, ``"NSE"``, ``"MCX"``).
        side: ``"BUY"`` or ``"SELL"``.
        quantity: Number of units / lots.
        order_type: ``"MARKET"``, ``"LIMIT"``, ``"SL"``, ``"SL-M"``.
        product: Product type — ``"MIS"``, ``"CNC"``, ``"NRML"``.
        price: Limit price (0.0 for market orders).
        trigger_price: Trigger price for SL / SL-M orders.
        disclosed_qty: Disclosed quantity (exchange-visible portion).
        validity: Order validity — ``"DAY"`` or ``"IOC"``.
        tag: Strategy or user tag attached to the order.
    """

    symbol: str
    exchange: str
    side: str
    quantity: int
    order_type: str = "MARKET"
    product: str = "MIS"
    price: float = 0.0
    trigger_price: float = 0.0
    disclosed_qty: int = 0
    validity: str = "DAY"
    tag: str = ""


class OrderResponse(BaseModel):
    """Normalised broker order response.

    Args:
        success: Whether the order was accepted by the broker.
        order_id: Broker-assigned order ID.
        status: Order status string (broker-specific).
        message: Human-readable message from the broker.
        raw: Raw broker response payload.
    """

    success: bool
    order_id: str = ""
    status: str = ""
    message: str = ""
    raw: dict[str, Any] = Field(default_factory=dict)


class Position(BaseModel):
    """A single open position.

    Args:
        symbol: Instrument symbol.
        exchange: Exchange code.
        product: Product type (``"MIS"``, ``"CNC"``, ``"NRML"``).
        quantity: Net position quantity (negative for short).
        avg_price: Average entry price.
        ltp: Last traded price.
        pnl: Unrealised P&L.
        day_pnl: Intraday P&L (may equal ``pnl`` for MIS).
    """

    symbol: str
    exchange: str
    product: str = ""
    quantity: int = 0
    avg_price: float = 0.0
    ltp: float = 0.0
    pnl: float = 0.0
    day_pnl: float = 0.0


class Order(BaseModel):
    """A single order in the order book.

    Args:
        order_id: Broker-assigned order ID.
        symbol: Instrument symbol.
        exchange: Exchange code.
        side: ``"BUY"`` or ``"SELL"``.
        quantity: Ordered quantity.
        filled_quantity: Executed quantity so far.
        price: Limit price (0 for market).
        order_type: Order type string.
        status: Current order status from the broker.
        product: Product type.
        placed_at: UTC timestamp of order placement.
        tag: Strategy / user tag.
    """

    order_id: str = ""
    symbol: str
    exchange: str
    side: str = ""
    quantity: int = 0
    filled_quantity: int = 0
    price: float = 0.0
    order_type: str = "MARKET"
    status: str = ""
    product: str = ""
    placed_at: datetime | None = None
    tag: str = ""


class Holding(BaseModel):
    """A long-term demat holding.

    Args:
        symbol: Instrument symbol (NSE / BSE equity).
        exchange: Exchange code.
        quantity: Number of shares held.
        avg_price: Average purchase price.
        ltp: Current market price.
        pnl: Unrealised P&L (current value minus cost).
        pnl_pct: Unrealised P&L as a percentage.
        product: Typically ``"CNC"``.
    """

    symbol: str
    exchange: str
    quantity: int = 0
    avg_price: float = 0.0
    ltp: float = 0.0
    pnl: float = 0.0
    pnl_pct: float = 0.0
    product: str = "CNC"


class FundsInfo(BaseModel):
    """Account funds and margin information.

    Args:
        available_cash: Liquid cash available for new orders.
        used_margin: Margin currently blocked.
        total_balance: Total account value.
        collateral: Value of collateral pledged.
        pnl: Realised P&L for the day.
        currency: Currency code (default ``"INR"``).
    """

    available_cash: float = 0.0
    used_margin: float = 0.0
    total_balance: float = 0.0
    collateral: float = 0.0
    pnl: float = 0.0
    currency: str = "INR"


class Quote(BaseModel):
    """Live market quote for a single instrument.

    Args:
        symbol: Instrument symbol.
        exchange: Exchange code.
        ltp: Last traded price.
        open: Day open price.
        high: Day high price.
        low: Day low price.
        close: Previous close price.
        volume: Traded volume.
        bid: Best bid price.
        ask: Best ask price.
        oi: Open interest (futures / options).
        timestamp: Quote timestamp (UTC).
    """

    symbol: str
    exchange: str
    ltp: float = 0.0
    open: float = 0.0
    high: float = 0.0
    low: float = 0.0
    close: float = 0.0
    volume: int = 0
    bid: float = 0.0
    ask: float = 0.0
    oi: int = 0
    timestamp: datetime | None = None


# ---------------------------------------------------------------------------
# BrokerInterface Protocol
# ---------------------------------------------------------------------------


@runtime_checkable
class BrokerInterface(Protocol):
    """Structural interface every FlintTrade broker adapter must satisfy.

    Implemented as a :class:`typing.Protocol` so adapters can be duck-typed
    without requiring explicit inheritance.  Use ``isinstance(obj, BrokerInterface)``
    at runtime (requires ``@runtime_checkable``).

    All methods are synchronous.  Async adapters should wrap IO in
    ``asyncio.run`` or use ``concurrent.futures`` internally.
    """

    def authenticate(self, credentials: BrokerCredentials) -> AuthResult:
        """Authenticate with the broker and return a session token.

        Args:
            credentials: Broker-specific credentials.

        Returns:
            :class:`AuthResult` with ``success=True`` and ``access_token`` set
            on success, or ``success=False`` with ``error`` set on failure.
        """
        ...

    def place_order(self, order: OrderRequest) -> OrderResponse:
        """Place a regular order.

        Args:
            order: Normalised :class:`OrderRequest`.

        Returns:
            :class:`OrderResponse` with broker's order ID and status.
        """
        ...

    def modify_order(self, order_id: str, modifications: dict[str, Any]) -> OrderResponse:
        """Modify an existing open order.

        Args:
            order_id: Broker-assigned order ID.
            modifications: Fields to modify (e.g. ``{"price": 150.0, "quantity": 100}``).

        Returns:
            Updated :class:`OrderResponse`.
        """
        ...

    def cancel_order(self, order_id: str) -> bool:
        """Cancel a single open order.

        Args:
            order_id: Broker-assigned order ID.

        Returns:
            ``True`` if cancellation was accepted, ``False`` otherwise.
        """
        ...

    def get_positions(self) -> list[Position]:
        """Fetch all current open positions.

        Returns:
            List of :class:`Position` objects (empty list if no positions).
        """
        ...

    def get_orders(self) -> list[Order]:
        """Fetch today's order book.

        Returns:
            List of :class:`Order` objects for all orders placed today.
        """
        ...

    def get_holdings(self) -> list[Holding]:
        """Fetch long-term demat holdings.

        Returns:
            List of :class:`Holding` objects.
        """
        ...

    def get_funds(self) -> FundsInfo:
        """Fetch account funds and margin summary.

        Returns:
            :class:`FundsInfo` with available cash and margin details.
        """
        ...

    def get_quote(self, symbol: str, exchange: str) -> Quote:
        """Fetch a live market quote.

        Args:
            symbol: Instrument symbol.
            exchange: Exchange code.

        Returns:
            :class:`Quote` with LTP, OHLCV, and bid/ask.
        """
        ...

    def subscribe_ticks(
        self,
        symbols: list[str],
        callback: Callable[[dict[str, Any]], None],
    ) -> None:
        """Subscribe to real-time tick feed for a list of symbols.

        Args:
            symbols: List of exchange-qualified symbol strings
                (e.g. ``["NIFTY:NSE_INDEX", "RELIANCE:NSE"]``).
            callback: Callable invoked for each incoming tick dict.
        """
        ...

    def unsubscribe_ticks(self, symbols: list[str]) -> None:
        """Unsubscribe from the real-time tick feed.

        Args:
            symbols: List of symbol strings to unsubscribe.
        """
        ...


# ---------------------------------------------------------------------------
# BrokerRegistry
# ---------------------------------------------------------------------------


class BrokerRegistry:
    """Registry for named broker adapter instances.

    Provides a simple name → adapter lookup so application code can retrieve
    the correct adapter without hardcoding broker names throughout the codebase.

    Usage::

        registry = BrokerRegistry()
        registry.register("openalgo", OpenAlgoBroker(client))
        broker = registry.get_broker("openalgo")
        positions = broker.get_positions()
    """

    def __init__(self) -> None:
        self._adapters: dict[str, BrokerInterface] = {}

    def register(self, name: str, adapter: BrokerInterface) -> None:
        """Register a broker adapter under a logical name.

        If an adapter is already registered under ``name`` it is silently
        replaced.

        Args:
            name: Logical broker name (e.g. ``"openalgo"``, ``"zerodha"``).
            adapter: An object satisfying the :class:`BrokerInterface` Protocol.

        Raises:
            TypeError: If ``adapter`` does not implement :class:`BrokerInterface`.
        """
        if not isinstance(adapter, BrokerInterface):
            raise TypeError(
                f"Adapter {adapter!r} does not implement BrokerInterface. "
                "Ensure all required methods are present."
            )
        self._adapters[name] = adapter
        logger.info("Broker adapter registered: %r", name)

    def unregister(self, name: str) -> None:
        """Remove a registered adapter.

        Args:
            name: Name of the adapter to remove.

        Raises:
            KeyError: If no adapter is registered under ``name``.
        """
        if name not in self._adapters:
            raise KeyError(f"No broker adapter registered under name {name!r}")
        del self._adapters[name]
        logger.info("Broker adapter unregistered: %r", name)

    def get_broker(self, name: str) -> BrokerInterface:
        """Look up a registered broker adapter.

        Args:
            name: Logical broker name.

        Returns:
            The :class:`BrokerInterface` adapter registered under ``name``.

        Raises:
            KeyError: If ``name`` is not registered.
        """
        if name not in self._adapters:
            raise KeyError(
                f"No broker adapter registered under name {name!r}. "
                f"Available: {sorted(self._adapters)}"
            )
        return self._adapters[name]

    def list_brokers(self) -> list[str]:
        """Return a sorted list of all registered adapter names.

        Returns:
            Sorted list of registered broker names.
        """
        return sorted(self._adapters)

    def is_registered(self, name: str) -> bool:
        """Check whether a broker name is registered.

        Args:
            name: Logical broker name.

        Returns:
            ``True`` if registered, ``False`` otherwise.
        """
        return name in self._adapters


# ---------------------------------------------------------------------------
# OpenAlgoBroker — concrete implementation delegating to OpenAlgo REST API
# ---------------------------------------------------------------------------


class OpenAlgoBroker:
    """Concrete :class:`BrokerInterface` implementation backed by OpenAlgo REST API.

    Delegates all broker operations to ``flinttrade_core.openalgo_client``
    and normalises the responses into FlintTrade's typed models.

    OpenAlgo is an optional external integration path for this adapter. Native
    FlintTrade broker adapters can exist alongside it.

    Args:
        client: An initialised ``OpenAlgoClient`` instance.  Injected to
            keep the adapter testable without a live OpenAlgo instance.

    Example::

        from flinttrade_core.openalgo_client import OpenAlgoClient
        client = OpenAlgoClient(host="http://localhost:5000", api_key="...")
        broker = OpenAlgoBroker(client=client)
        funds = broker.get_funds()
    """

    def __init__(self, client: Any) -> None:
        self._client = client

    # ------------------------------------------------------------------
    # Authentication
    # ------------------------------------------------------------------

    def authenticate(self, credentials: BrokerCredentials) -> AuthResult:
        """Validate connectivity to OpenAlgo using the ping endpoint.

        OpenAlgo handles broker authentication internally.  This method
        verifies that the API key is accepted and the server is reachable.

        Args:
            credentials: Must contain ``api_key``.

        Returns:
            :class:`AuthResult` reflecting the ping response.
        """
        try:
            raw = self._client.ping()
            success = isinstance(raw, dict) and raw.get("status") == "success"
            return AuthResult(
                success=success,
                access_token=credentials.api_key,
                error=None if success else str(raw),
                raw=raw if isinstance(raw, dict) else {},
            )
        except Exception as exc:
            logger.exception("OpenAlgo authentication failed")
            return AuthResult(success=False, error=str(exc))

    # ------------------------------------------------------------------
    # Orders
    # ------------------------------------------------------------------

    def place_order(self, order: OrderRequest) -> OrderResponse:
        """Place an order via the OpenAlgo ``/api/v1/placeorder`` endpoint.

        Args:
            order: Normalised :class:`OrderRequest`.

        Returns:
            :class:`OrderResponse` with broker-assigned order ID.
        """
        try:
            raw = self._client.place_order(
                symbol=order.symbol,
                exchange=order.exchange,
                action=order.side,
                quantity=order.quantity,
                price_type=order.order_type,
                product=order.product,
                price=order.price,
                trigger_price=order.trigger_price,
                disclosed_quantity=order.disclosed_qty,
            )
            success = isinstance(raw, dict) and raw.get("status") == "success"
            order_id = str(raw.get("orderid", "")) if isinstance(raw, dict) else ""
            return OrderResponse(
                success=success,
                order_id=order_id,
                status=raw.get("status", "") if isinstance(raw, dict) else "",
                message=raw.get("message", "") if isinstance(raw, dict) else str(raw),
                raw=raw if isinstance(raw, dict) else {},
            )
        except Exception as exc:
            logger.exception("place_order failed for %s", order.symbol)
            return OrderResponse(success=False, message=_safe_error_message(exc, "Order placement failed"))

    def modify_order(self, order_id: str, modifications: dict[str, Any]) -> OrderResponse:
        """Modify an open order via ``/api/v1/modifyorder``.

        Args:
            order_id: Broker-assigned order ID.
            modifications: Fields to change — merged with ``orderid``.

        Returns:
            Updated :class:`OrderResponse`.
        """
        try:
            payload = {"orderid": order_id, **modifications}
            raw = self._client.modify_order(**payload)
            success = isinstance(raw, dict) and raw.get("status") == "success"
            return OrderResponse(
                success=success,
                order_id=order_id,
                status=raw.get("status", "") if isinstance(raw, dict) else "",
                message=raw.get("message", "") if isinstance(raw, dict) else str(raw),
                raw=raw if isinstance(raw, dict) else {},
            )
        except Exception as exc:
            logger.exception("modify_order failed for order_id=%s", log_ref(order_id, kind="order"))
            return OrderResponse(
                success=False,
                order_id=order_id,
                message=_safe_error_message(exc, "Order modification failed"),
            )

    def cancel_order(self, order_id: str) -> bool:
        """Cancel an open order via ``/api/v1/cancelorder``.

        Args:
            order_id: Broker-assigned order ID.

        Returns:
            ``True`` if cancelled, ``False`` on failure.
        """
        try:
            raw = self._client.cancel_order(orderid=order_id)
            return isinstance(raw, dict) and raw.get("status") == "success"
        except Exception:
            logger.exception("cancel_order failed for order_id=%s", log_ref(order_id, kind="order"))
            return False

    # ------------------------------------------------------------------
    # Account data
    # ------------------------------------------------------------------

    def get_positions(self) -> list[Position]:
        """Fetch open positions from ``/api/v1/positionbook``.

        Returns:
            List of :class:`Position` objects.
        """
        try:
            raw = self._client.get_positions()
            rows = raw if isinstance(raw, list) else raw.get("data", [])
            return [
                Position(
                    symbol=r.get("symbol", ""),
                    exchange=r.get("exchange", ""),
                    product=r.get("product", ""),
                    quantity=int(r.get("quantity", r.get("netqty", 0))),
                    avg_price=float(r.get("average_price", r.get("buyavg", 0.0))),
                    ltp=float(r.get("ltp", 0.0)),
                    pnl=float(r.get("pnl", r.get("unrealised", 0.0))),
                    day_pnl=float(r.get("day_pnl", r.get("realised", 0.0))),
                )
                for r in rows
                if isinstance(r, dict)
            ]
        except Exception:
            logger.exception("get_positions failed")
            return []

    def get_orders(self) -> list[Order]:
        """Fetch today's order book from ``/api/v1/orderbook``.

        Returns:
            List of :class:`Order` objects.
        """
        try:
            raw = self._client.get_order_book()
            rows = raw if isinstance(raw, list) else raw.get("data", [])
            return [
                Order(
                    order_id=str(r.get("orderid", "")),
                    symbol=r.get("symbol", ""),
                    exchange=r.get("exchange", ""),
                    side=r.get("action", r.get("transactiontype", "")),
                    quantity=int(r.get("quantity", 0)),
                    filled_quantity=int(r.get("filled_quantity", r.get("filledshares", 0))),
                    price=float(r.get("price", 0.0)),
                    order_type=r.get("price_type", r.get("ordertype", "MARKET")),
                    status=r.get("status", ""),
                    product=r.get("product", ""),
                    tag=r.get("tag", r.get("strategy", "")),
                )
                for r in rows
                if isinstance(r, dict)
            ]
        except Exception:
            logger.exception("get_orders failed")
            return []

    def get_holdings(self) -> list[Holding]:
        """Fetch demat holdings from ``/api/v1/holdings``.

        Returns:
            List of :class:`Holding` objects.
        """
        try:
            raw = self._client.get_holdings()
            rows = raw if isinstance(raw, list) else raw.get("data", [])
            return [
                Holding(
                    symbol=r.get("symbol", r.get("tradingsymbol", "")),
                    exchange=r.get("exchange", "NSE"),
                    quantity=int(r.get("quantity", r.get("cnc_used_quantity", 0))),
                    avg_price=float(r.get("average_price", r.get("average_cost", 0.0))),
                    ltp=float(r.get("ltp", r.get("last_price", 0.0))),
                    pnl=float(r.get("pnl", 0.0)),
                    pnl_pct=float(r.get("pnl_percentage", 0.0)),
                    product=r.get("product", "CNC"),
                )
                for r in rows
                if isinstance(r, dict)
            ]
        except Exception:
            logger.exception("get_holdings failed")
            return []

    def get_funds(self) -> FundsInfo:
        """Fetch account funds from ``/api/v1/funds``.

        Returns:
            :class:`FundsInfo` with margin breakdown.
        """
        try:
            raw = self._client.get_funds()
            data = raw.get("data", raw) if isinstance(raw, dict) else {}
            return FundsInfo(
                available_cash=float(data.get("availablecash", data.get("net", 0.0))),
                used_margin=float(data.get("utilisedmargin", data.get("used_margin", 0.0))),
                total_balance=float(data.get("totalcollateral", data.get("total", 0.0))),
                collateral=float(data.get("collateral", 0.0)),
                pnl=float(data.get("realisedpnl", data.get("realized_pnl", 0.0))),
            )
        except Exception:
            logger.exception("get_funds failed")
            return FundsInfo()

    def get_quote(self, symbol: str, exchange: str) -> Quote:
        """Fetch a live quote from ``/api/v1/quotes``.

        Args:
            symbol: Instrument symbol.
            exchange: Exchange code.

        Returns:
            :class:`Quote` with OHLCV and bid/ask data.
        """
        try:
            raw = self._client.get_quotes(symbol=symbol, exchange=exchange)
            data = raw.get("data", raw) if isinstance(raw, dict) else {}
            return Quote(
                symbol=symbol,
                exchange=exchange,
                ltp=float(data.get("ltp", data.get("last_price", 0.0))),
                open=float(data.get("open", data.get("ohlc", {}).get("open", 0.0))),
                high=float(data.get("high", data.get("ohlc", {}).get("high", 0.0))),
                low=float(data.get("low", data.get("ohlc", {}).get("low", 0.0))),
                close=float(data.get("close", data.get("ohlc", {}).get("close", 0.0))),
                volume=int(data.get("volume", data.get("volume_traded", 0))),
                bid=float(data.get("bid", 0.0)),
                ask=float(data.get("ask", 0.0)),
                oi=int(data.get("oi", data.get("open_interest", 0))),
            )
        except Exception:
            logger.exception("get_quote failed for %s/%s", symbol, exchange)
            return Quote(symbol=symbol, exchange=exchange)

    # ------------------------------------------------------------------
    # Streaming — delegates to OpenAlgo WebSocket bridge
    # ------------------------------------------------------------------

    def subscribe_ticks(
        self,
        symbols: list[str],
        callback: Callable[[dict[str, Any]], None],
    ) -> None:
        """Subscribe to real-time ticks via the OpenAlgo WebSocket bridge.

        The actual WebSocket connection is managed by
        :class:`~ws_bridge.OpenAlgoWebSocketBridge`.  This method is a thin
        delegation shim so code using :class:`BrokerInterface` does not need
        to import the bridge directly.

        Args:
            symbols: Exchange-qualified symbol strings.
            callback: Invoked with each tick dict from the bridge.
        """
        try:
            self._client.subscribe(symbols=symbols, callback=callback)
        except AttributeError:
            logger.warning(
                "OpenAlgoClient does not expose subscribe(). "
                "Use ws_bridge.OpenAlgoWebSocketBridge directly for streaming."
            )

    def unsubscribe_ticks(self, symbols: list[str]) -> None:
        """Unsubscribe from real-time tick feed.

        Args:
            symbols: Symbol strings to unsubscribe.
        """
        try:
            self._client.unsubscribe(symbols=symbols)
        except AttributeError:
            logger.warning(
                "OpenAlgoClient does not expose unsubscribe(). "
                "Use ws_bridge.OpenAlgoWebSocketBridge directly."
            )
