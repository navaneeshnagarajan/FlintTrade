"""BrokerAdapter Protocol and loader for the FlintTrade broker gateway.

Each broker is a module under ``packages/gateway/src/brokers/<name>/``
that exposes a class implementing the :class:`BrokerAdapter` Protocol.
The loader is intentionally lazy — adapters are only imported at the
moment a session requires them.
"""

from __future__ import annotations

import importlib
import logging
from typing import Any, Protocol, runtime_checkable

from exceptions import BrokerNotFoundError

logger = logging.getLogger("flinttrade.gateway.adapter")


# ---------------------------------------------------------------------------
# BrokerAdapter Protocol
# ---------------------------------------------------------------------------


@runtime_checkable
class BrokerAdapter(Protocol):
    """Structural interface every broker adapter must satisfy.

    Adapters implement the actual HTTP/WebSocket calls to a specific
    broker's API.  ``BrokerSession`` uses this Protocol so that any
    conforming object can be swapped in without subclassing.

    All methods that communicate with the broker are synchronous at
    this layer; async adapters will be added in a future task.
    """

    def authenticate(
        self, credentials: dict[str, str]
    ) -> tuple[str | None, str | None]:
        """Attempt authentication with the broker.

        Args:
            credentials: Key-value pairs required by the broker's auth
                flow (e.g. ``{"api_key": "...", "totp": "..."}``)

        Returns:
            A two-tuple ``(token, error)``.  On success ``token`` is a
            non-empty string and ``error`` is ``None``.  On failure
            ``token`` is ``None`` and ``error`` is a human-readable
            description.
        """
        ...

    def place_order(
        self, order_data: dict[str, Any], auth_token: str
    ) -> dict[str, Any]:
        """Submit a new order to the broker.

        Args:
            order_data: Order parameters (symbol, quantity, price, etc.).
            auth_token: Session token obtained during :meth:`authenticate`.

        Returns:
            Broker response dict (typically contains ``order_id`` etc.).
        """
        ...

    def modify_order(
        self, order_data: dict[str, Any], auth_token: str
    ) -> dict[str, Any]:
        """Modify an existing open order.

        Args:
            order_data: Modified order parameters including the order ID.
            auth_token: Session token.

        Returns:
            Broker response dict.
        """
        ...

    def cancel_order(
        self, order_data: dict[str, Any], auth_token: str
    ) -> dict[str, Any]:
        """Cancel a single open order.

        Args:
            order_data: Must contain the order ID to cancel.
            auth_token: Session token.

        Returns:
            Broker response dict.
        """
        ...

    def cancel_all_orders(self, auth_token: str) -> dict[str, Any]:
        """Cancel all open orders for the authenticated account.

        Args:
            auth_token: Session token.

        Returns:
            Broker response dict.
        """
        ...

    def close_position(
        self, position_data: dict[str, Any], auth_token: str
    ) -> dict[str, Any]:
        """Close (square-off) an open position.

        Args:
            position_data: Position identifier/parameters.
            auth_token: Session token.

        Returns:
            Broker response dict.
        """
        ...

    def place_options_order(
        self, order_data: dict[str, Any], auth_token: str
    ) -> dict[str, Any]:
        """Submit an options-specific order.

        Args:
            order_data: Options order parameters.
            auth_token: Session token.

        Returns:
            Broker response dict.
        """
        ...

    def get_positions(self, auth_token: str) -> dict[str, Any]:
        """Fetch current open positions.

        Args:
            auth_token: Session token.

        Returns:
            Broker response dict containing position list.
        """
        ...

    def get_orders(self, auth_token: str) -> dict[str, Any]:
        """Fetch today's order book.

        Args:
            auth_token: Session token.

        Returns:
            Broker response dict containing order list.
        """
        ...

    def get_trades(self, auth_token: str) -> dict[str, Any]:
        """Fetch today's trade book (executed orders).

        Args:
            auth_token: Session token.

        Returns:
            Broker response dict containing trade list.
        """
        ...

    def get_holdings(self, auth_token: str) -> dict[str, Any]:
        """Fetch long-term holdings (demat).

        Args:
            auth_token: Session token.

        Returns:
            Broker response dict containing holdings list.
        """
        ...

    def get_funds(self, auth_token: str) -> dict[str, Any]:
        """Fetch available funds / margin summary.

        Args:
            auth_token: Session token.

        Returns:
            Broker response dict containing fund details.
        """
        ...

    def get_margin(
        self, order_data: dict[str, Any], auth_token: str
    ) -> dict[str, Any]:
        """Calculate required margin for a hypothetical order.

        Args:
            order_data: Order parameters for margin estimation.
            auth_token: Session token.

        Returns:
            Broker response dict with margin breakdown.
        """
        ...

    def get_quotes(
        self, symbols: list[str], auth_token: str
    ) -> dict[str, Any]:
        """Fetch live quotes for a list of symbols.

        Args:
            symbols: List of exchange-qualified symbols.
            auth_token: Session token.

        Returns:
            Broker response dict with quote data per symbol.
        """
        ...

    def get_depth(
        self, symbol: str, auth_token: str
    ) -> dict[str, Any]:
        """Fetch market depth (order book) for a single symbol.

        Args:
            symbol: Exchange-qualified symbol string.
            auth_token: Session token.

        Returns:
            Broker response dict with bid/ask depth levels.
        """
        ...

    def get_history(
        self, params: dict[str, Any], auth_token: str
    ) -> dict[str, Any]:
        """Fetch historical OHLCV data.

        Args:
            params: Query parameters (symbol, interval, from/to dates).
            auth_token: Session token.

        Returns:
            Broker response dict with OHLCV candles.
        """
        ...

    def search_symbols(
        self, query: str, auth_token: str
    ) -> dict[str, Any]:
        """Search for instruments by name or ticker.

        Args:
            query: Free-text or partial symbol search string.
            auth_token: Session token.

        Returns:
            Broker response dict with matching instrument list.
        """
        ...


# ---------------------------------------------------------------------------
# Loader
# ---------------------------------------------------------------------------


def load_broker_adapter(broker_name: str) -> BrokerAdapter:
    """Import and return the adapter for *broker_name*.

    Adapters live at ``packages.gateway.src.brokers.<broker_name>.adapter``
    and must expose a top-level ``Adapter`` class that satisfies
    :class:`BrokerAdapter`.

    Args:
        broker_name: Canonical lowercase broker identifier
            (e.g. ``"zerodha"``, ``"angel"``).

    Returns:
        An instantiated :class:`BrokerAdapter`-compatible object.

    Raises:
        BrokerNotFoundError: If no adapter module exists for *broker_name*
            or the module does not expose an ``Adapter`` class.

    Example::

        adapter = load_broker_adapter("zerodha")
        token, err = adapter.authenticate({"api_key": "...", "totp": "123456"})
    """
    module_path = f"packages.gateway.src.brokers.{broker_name}.adapter"
    try:
        module = importlib.import_module(module_path)
    except ModuleNotFoundError as exc:
        raise BrokerNotFoundError(
            f"No adapter found for broker {broker_name!r} "
            f"(tried {module_path!r})"
        ) from exc

    adapter_cls = getattr(module, "Adapter", None)
    if adapter_cls is None:
        raise BrokerNotFoundError(
            f"Adapter module {module_path!r} does not expose an 'Adapter' class"
        )

    logger.debug("Loaded adapter for broker %r from %s", broker_name, module_path)
    return adapter_cls()  # type: ignore[return-value]
