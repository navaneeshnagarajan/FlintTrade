"""BrokerSession: wraps a single broker connection.

Manages auth state, delegates API calls to the broker adapter,
and tracks connection lifecycle.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any

from .adapter import load_broker_adapter, BrokerAdapter
from .models import BrokerAccountInfo, AccountStatus
from .exceptions import SessionError, AuthFlowError

logger = logging.getLogger("flinttrade.gateway.session")


class BrokerSession:
    """Manages the lifecycle of a single broker connection.

    A ``BrokerSession`` starts in the ``DISCONNECTED`` state.  The
    adapter module for the broker is loaded lazily on the first call
    that needs it, so constructing a session is cheap and never
    performs I/O.

    Typical usage::

        session = BrokerSession("AB1234", "zerodha", "Primary Zerodha")
        session.authenticate({"api_key": "...", "totp": "123456"})
        positions = session.get_positions()
        session.disconnect()

    Args:
        account_id: Unique identifier for the account (e.g. client code).
        broker_name: Canonical lowercase broker name (e.g. ``"zerodha"``).
        label: Human-readable label shown in the UI.
    """

    def __init__(
        self,
        account_id: str,
        broker_name: str,
        label: str,
    ) -> None:
        self._account_id: str = account_id
        self._broker_name: str = broker_name
        self._label: str = label
        self._status: AccountStatus = AccountStatus.disconnected
        self._connected_at: datetime | None = None
        self._error_message: str | None = None
        self._auth_token: str | None = None
        self._adapter: BrokerAdapter | None = None

    # ------------------------------------------------------------------
    # Properties
    # ------------------------------------------------------------------

    @property
    def info(self) -> BrokerAccountInfo:
        """Return a snapshot of the current session state.

        Returns:
            A :class:`~packages.gateway.src.models.BrokerAccountInfo`
            reflecting the account's current status.
        """
        return BrokerAccountInfo(
            account_id=self._account_id,
            broker=self._broker_name,
            label=self._label,
            status=self._status,
            connected_at=self._connected_at,
            error_message=self._error_message,
        )

    @property
    def is_connected(self) -> bool:
        """``True`` when the session is in the ``CONNECTED`` state.

        Returns:
            Whether this session has a valid authenticated connection.
        """
        return self._status == AccountStatus.connected

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    def _load_adapter(self) -> BrokerAdapter:
        """Return the broker adapter, loading it on first access.

        The adapter module is imported once and cached on ``self._adapter``
        for the lifetime of the session.

        Returns:
            The :class:`~packages.gateway.src.adapter.BrokerAdapter`
            instance for this session's broker.

        Raises:
            BrokerNotFoundError: If no adapter exists for this broker.
        """
        if self._adapter is None:
            self._adapter = load_broker_adapter(self._broker_name)
            logger.debug(
                "Adapter loaded for account %r (broker=%r)",
                self._account_id,
                self._broker_name,
            )
        return self._adapter

    def _ensure_connected(self) -> None:
        """Guard: raise :class:`SessionError` if the session is not connected.

        Raises:
            SessionError: If ``self._status`` is not
                :attr:`~AccountStatus.connected`.
        """
        if not self.is_connected:
            raise SessionError(
                f"Session for account {self._account_id!r} is not connected "
                f"(current status: {self._status!r}). "
                "Call authenticate() first."
            )

    # ------------------------------------------------------------------
    # Auth lifecycle
    # ------------------------------------------------------------------

    def authenticate(self, credentials: dict[str, str]) -> None:
        """Authenticate with the broker using the supplied credentials.

        On success the session transitions to ``CONNECTED`` and the auth
        token is stored internally.  On failure the session transitions to
        ``ERROR``, the error message is recorded, and :class:`AuthFlowError`
        is raised.

        Args:
            credentials: Key-value pairs required by the broker's auth flow
                (contents vary by broker, e.g. ``{"api_key": "...", "totp": "..."}``).

        Raises:
            AuthFlowError: If the broker rejects the credentials or the
                adapter reports an error.
            BrokerNotFoundError: If the adapter cannot be loaded.
        """
        self._status = AccountStatus.authenticating
        self._error_message = None
        logger.info(
            "Authenticating account %r with broker %r",
            self._account_id,
            self._broker_name,
        )

        adapter = self._load_adapter()
        token, error = adapter.authenticate(credentials)

        if token is not None and error is None:
            self._auth_token = token
            self._status = AccountStatus.connected
            self._connected_at = datetime.now(tz=timezone.utc)
            self._error_message = None
            logger.info(
                "Account %r connected to %r at %s",
                self._account_id,
                self._broker_name,
                self._connected_at.isoformat(),
            )
        else:
            error_msg = error or "Authentication failed (no error detail returned)"
            self._status = AccountStatus.error
            self._error_message = error_msg
            self._auth_token = None
            logger.warning(
                "Authentication failed for account %r: %s",
                self._account_id,
                error_msg,
            )
            raise AuthFlowError(error_msg)

    def disconnect(self) -> None:
        """Terminate the session and clear all auth state.

        After calling this method the session returns to the
        ``DISCONNECTED`` state with no stored token or timestamps.
        """
        self._status = AccountStatus.disconnected
        self._auth_token = None
        self._connected_at = None
        self._error_message = None
        logger.info(
            "Account %r disconnected from %r",
            self._account_id,
            self._broker_name,
        )

    # ------------------------------------------------------------------
    # Order management
    # ------------------------------------------------------------------

    def place_order(self, order_data: dict[str, Any]) -> dict[str, Any]:
        """Submit a new order to the broker.

        Args:
            order_data: Order parameters (symbol, qty, price, etc.).

        Returns:
            Broker response dict.

        Raises:
            SessionError: If the session is not connected.
        """
        self._ensure_connected()
        assert self._auth_token is not None  # guaranteed by _ensure_connected
        return self._load_adapter().place_order(order_data, self._auth_token)

    def modify_order(self, order_data: dict[str, Any]) -> dict[str, Any]:
        """Modify an existing open order.

        Args:
            order_data: Modified order parameters including the order ID.

        Returns:
            Broker response dict.

        Raises:
            SessionError: If the session is not connected.
        """
        self._ensure_connected()
        assert self._auth_token is not None
        return self._load_adapter().modify_order(order_data, self._auth_token)

    def cancel_order(self, order_data: dict[str, Any]) -> dict[str, Any]:
        """Cancel a single open order.

        Args:
            order_data: Must contain the order ID to cancel.

        Returns:
            Broker response dict.

        Raises:
            SessionError: If the session is not connected.
        """
        self._ensure_connected()
        assert self._auth_token is not None
        return self._load_adapter().cancel_order(order_data, self._auth_token)

    def cancel_all_orders(self) -> dict[str, Any]:
        """Cancel all open orders for the authenticated account.

        Returns:
            Broker response dict.

        Raises:
            SessionError: If the session is not connected.
        """
        self._ensure_connected()
        assert self._auth_token is not None
        return self._load_adapter().cancel_all_orders(self._auth_token)

    def close_position(self, position_data: dict[str, Any]) -> dict[str, Any]:
        """Close (square-off) an open position.

        Args:
            position_data: Position identifier/parameters.

        Returns:
            Broker response dict.

        Raises:
            SessionError: If the session is not connected.
        """
        self._ensure_connected()
        assert self._auth_token is not None
        return self._load_adapter().close_position(position_data, self._auth_token)

    def place_options_order(self, order_data: dict[str, Any]) -> dict[str, Any]:
        """Submit an options-specific order.

        Args:
            order_data: Options order parameters.

        Returns:
            Broker response dict.

        Raises:
            SessionError: If the session is not connected.
        """
        self._ensure_connected()
        assert self._auth_token is not None
        return self._load_adapter().place_options_order(order_data, self._auth_token)

    # ------------------------------------------------------------------
    # Account data
    # ------------------------------------------------------------------

    def get_positions(self) -> dict[str, Any]:
        """Fetch current open positions.

        Returns:
            Broker response dict containing position list.

        Raises:
            SessionError: If the session is not connected.
        """
        self._ensure_connected()
        assert self._auth_token is not None
        return self._load_adapter().get_positions(self._auth_token)

    def get_orders(self) -> dict[str, Any]:
        """Fetch today's order book.

        Returns:
            Broker response dict containing order list.

        Raises:
            SessionError: If the session is not connected.
        """
        self._ensure_connected()
        assert self._auth_token is not None
        return self._load_adapter().get_orders(self._auth_token)

    def get_trades(self) -> dict[str, Any]:
        """Fetch today's trade book (executed orders).

        Returns:
            Broker response dict containing trade list.

        Raises:
            SessionError: If the session is not connected.
        """
        self._ensure_connected()
        assert self._auth_token is not None
        return self._load_adapter().get_trades(self._auth_token)

    def get_holdings(self) -> dict[str, Any]:
        """Fetch long-term holdings (demat).

        Returns:
            Broker response dict containing holdings list.

        Raises:
            SessionError: If the session is not connected.
        """
        self._ensure_connected()
        assert self._auth_token is not None
        return self._load_adapter().get_holdings(self._auth_token)

    def get_funds(self) -> dict[str, Any]:
        """Fetch available funds / margin summary.

        Returns:
            Broker response dict containing fund details.

        Raises:
            SessionError: If the session is not connected.
        """
        self._ensure_connected()
        assert self._auth_token is not None
        return self._load_adapter().get_funds(self._auth_token)

    def get_margin(self, order_data: dict[str, Any]) -> dict[str, Any]:
        """Calculate required margin for a hypothetical order.

        Args:
            order_data: Order parameters for margin estimation.

        Returns:
            Broker response dict with margin breakdown.

        Raises:
            SessionError: If the session is not connected.
        """
        self._ensure_connected()
        assert self._auth_token is not None
        return self._load_adapter().get_margin(order_data, self._auth_token)

    # ------------------------------------------------------------------
    # Market data
    # ------------------------------------------------------------------

    def get_quotes(self, symbols: list[str]) -> dict[str, Any]:
        """Fetch live quotes for a list of symbols.

        Args:
            symbols: List of exchange-qualified symbols.

        Returns:
            Broker response dict with quote data per symbol.

        Raises:
            SessionError: If the session is not connected.
        """
        self._ensure_connected()
        assert self._auth_token is not None
        return self._load_adapter().get_quotes(symbols, self._auth_token)

    def get_depth(self, symbol: str) -> dict[str, Any]:
        """Fetch market depth (order book) for a single symbol.

        Args:
            symbol: Exchange-qualified symbol string.

        Returns:
            Broker response dict with bid/ask depth levels.

        Raises:
            SessionError: If the session is not connected.
        """
        self._ensure_connected()
        assert self._auth_token is not None
        return self._load_adapter().get_depth(symbol, self._auth_token)

    def get_history(self, params: dict[str, Any]) -> dict[str, Any]:
        """Fetch historical OHLCV data.

        Args:
            params: Query parameters (symbol, interval, from/to dates).

        Returns:
            Broker response dict with OHLCV candles.

        Raises:
            SessionError: If the session is not connected.
        """
        self._ensure_connected()
        assert self._auth_token is not None
        return self._load_adapter().get_history(params, self._auth_token)

    def search_symbols(self, query: str) -> dict[str, Any]:
        """Search for instruments by name or ticker.

        Args:
            query: Free-text or partial symbol search string.

        Returns:
            Broker response dict with matching instrument list.

        Raises:
            SessionError: If the session is not connected.
        """
        self._ensure_connected()
        assert self._auth_token is not None
        return self._load_adapter().search_symbols(query, self._auth_token)
