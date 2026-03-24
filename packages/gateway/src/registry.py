"""BrokerRegistry: manages N broker sessions.

Thread-safe. Central dispatch for all broker operations.
Singleton created at app startup.
"""

from __future__ import annotations

import logging
import threading
from typing import Any

from session import BrokerSession
from models import BrokerInfo, BrokerAccountInfo
from adapter import BROKER_CATALOG
from exceptions import BrokerNotFoundError, SessionError

logger = logging.getLogger("flinttrade.gateway.registry")


class BrokerRegistry:
    """Central manager for multiple concurrent broker sessions.

    Maintains a thread-safe dictionary of :class:`~session.BrokerSession`
    instances keyed by ``account_id``.  All mutations (add, remove,
    reconnect, set_primary) acquire an internal :class:`threading.Lock`
    so the registry is safe to call from multiple threads.

    Typical usage::

        registry = BrokerRegistry()
        info = registry.add_account("AB1234", "zerodha", "Primary", {"api_key": "..."})
        registry.set_primary("AB1234")
        session = registry.get_primary_session()
        positions = registry.get_positions("AB1234")

    The registry does **not** own a :class:`~credentials.CredentialStore`
    directly; credential retrieval is the caller's responsibility and is
    injected via ``reconnect_account``.
    """

    def __init__(self) -> None:
        self._sessions: dict[str, BrokerSession] = {}
        self._primary: str | None = None  # account_id of the primary session
        self._lock: threading.Lock = threading.Lock()

    # ------------------------------------------------------------------
    # Catalog queries (read-only, no lock needed)
    # ------------------------------------------------------------------

    def get_supported_brokers(self) -> list[BrokerInfo]:
        """Return all non-sandbox broker entries from the catalog.

        Returns:
            A list of :class:`~models.BrokerInfo` objects where
            ``is_sandbox`` is ``False``, sorted by display name.
        """
        return [
            info
            for info in BROKER_CATALOG.values()
            if not info.is_sandbox
        ]

    # ------------------------------------------------------------------
    # Account management (mutating, require lock)
    # ------------------------------------------------------------------

    def add_account(
        self,
        account_id: str,
        broker_name: str,
        label: str,
        credentials: dict[str, Any],
    ) -> BrokerAccountInfo:
        """Create a new broker session, authenticate it, and register it.

        Args:
            account_id: Unique identifier for the account (e.g. client code).
            broker_name: Canonical broker name that must exist in
                :data:`~adapter.BROKER_CATALOG`.
            label: Human-readable label shown in the UI.
            credentials: Key-value credentials passed verbatim to
                :meth:`~session.BrokerSession.authenticate`.

        Returns:
            A :class:`~models.BrokerAccountInfo` snapshot after successful
            authentication.

        Raises:
            BrokerNotFoundError: If ``broker_name`` is not in the catalog.
            AuthFlowError: If the broker rejects the credentials.
        """
        if broker_name not in BROKER_CATALOG:
            raise BrokerNotFoundError(
                f"Broker '{broker_name}' not found in catalog. "
                f"Available brokers: {sorted(BROKER_CATALOG)}"
            )

        session = BrokerSession(account_id, broker_name, label)
        session.authenticate(credentials)

        with self._lock:
            self._sessions[account_id] = session
            logger.info(
                "Account %r (%s) added to registry",
                account_id,
                broker_name,
            )

        return self._build_info(session)

    def remove_account(self, account_id: str) -> None:
        """Disconnect and remove a session from the registry.

        Args:
            account_id: Identifier of the account to remove.

        Raises:
            BrokerNotFoundError: If ``account_id`` is not registered.
        """
        with self._lock:
            session = self._sessions.get(account_id)
            if session is None:
                raise BrokerNotFoundError(
                    f"Account '{account_id}' not found in registry."
                )
            session.disconnect()
            del self._sessions[account_id]
            if self._primary == account_id:
                self._primary = None
            logger.info("Account %r removed from registry", account_id)

    def reconnect_account(
        self,
        account_id: str,
        credentials: dict[str, Any] | None = None,
        credential_store: Any | None = None,
    ) -> BrokerAccountInfo:
        """Re-authenticate an existing registered session.

        Exactly one of ``credentials`` or ``credential_store`` must be
        provided.  If a ``credential_store`` is given its ``retrieve``
        method is called with ``account_id`` to fetch the credentials.

        Args:
            account_id: Identifier of the account to reconnect.
            credentials: Optional credentials dict passed directly to
                :meth:`~session.BrokerSession.authenticate`.
            credential_store: Optional store object exposing a
                ``retrieve(account_id) -> dict`` method.

        Returns:
            Updated :class:`~models.BrokerAccountInfo` snapshot after
            successful re-authentication.

        Raises:
            BrokerNotFoundError: If ``account_id`` is not registered.
            AuthFlowError: If the broker rejects the credentials.
            ValueError: If neither ``credentials`` nor ``credential_store``
                is provided.
        """
        with self._lock:
            session = self._sessions.get(account_id)
            if session is None:
                raise BrokerNotFoundError(
                    f"Account '{account_id}' not found in registry."
                )

        if credentials is None and credential_store is None:
            raise ValueError(
                "Either 'credentials' or 'credential_store' must be provided."
            )

        if credentials is None:
            credentials = credential_store.retrieve(account_id)

        session.authenticate(credentials)
        logger.info("Account %r reconnected", account_id)
        return self._build_info(session)

    def set_primary(self, account_id: str) -> None:
        """Designate one registered session as the primary account.

        Clears the primary flag on all other sessions.  The primary
        session is returned by :meth:`get_primary_session`.

        Args:
            account_id: Identifier of the session to promote.

        Raises:
            BrokerNotFoundError: If ``account_id`` is not registered.
        """
        with self._lock:
            if account_id not in self._sessions:
                raise BrokerNotFoundError(
                    f"Account '{account_id}' not found in registry."
                )
            self._primary = account_id
            logger.info("Primary account set to %r", account_id)

    # ------------------------------------------------------------------
    # Session lookup (read-only, no lock needed for dict reads in CPython,
    # but we use the lock for correctness under all implementations)
    # ------------------------------------------------------------------

    def get_session(self, account_id: str) -> BrokerSession:
        """Look up a registered session by account ID.

        Args:
            account_id: Identifier of the desired account.

        Returns:
            The :class:`~session.BrokerSession` for ``account_id``.

        Raises:
            BrokerNotFoundError: If ``account_id`` is not registered.
        """
        with self._lock:
            session = self._sessions.get(account_id)
        if session is None:
            raise BrokerNotFoundError(
                f"Account '{account_id}' not found in registry."
            )
        return session

    def get_primary_session(self) -> BrokerSession:
        """Return the session designated as primary.

        Returns:
            The primary :class:`~session.BrokerSession`.

        Raises:
            SessionError: If no primary session has been set.
        """
        with self._lock:
            primary_id = self._primary
            session = self._sessions.get(primary_id) if primary_id else None

        if session is None:
            raise SessionError(
                "No primary session set. Call set_primary(account_id) first."
            )
        return session

    def list_accounts(self) -> list[BrokerAccountInfo]:
        """Return a snapshot of info for all registered sessions.

        Returns:
            List of :class:`~models.BrokerAccountInfo` objects, one per
            registered session.  Order is insertion order (Python 3.7+
            dict guarantee).
        """
        with self._lock:
            sessions_snapshot = list(self._sessions.values())

        return [self._build_info(s) for s in sessions_snapshot]

    # ------------------------------------------------------------------
    # Delegated broker operations
    # ------------------------------------------------------------------

    def place_order(self, account_id: str, order_data: dict[str, Any]) -> dict[str, Any]:
        """Place an order on the specified account.

        Args:
            account_id: Target account identifier.
            order_data: Order parameters passed to the broker.

        Returns:
            Broker response dict.

        Raises:
            BrokerNotFoundError: If ``account_id`` is not registered.
            SessionError: If the session is not connected.
        """
        return self.get_session(account_id).place_order(order_data)

    def modify_order(self, account_id: str, order_data: dict[str, Any]) -> dict[str, Any]:
        """Modify an existing open order on the specified account.

        Args:
            account_id: Target account identifier.
            order_data: Modified order parameters including the order ID.

        Returns:
            Broker response dict.

        Raises:
            BrokerNotFoundError: If ``account_id`` is not registered.
            SessionError: If the session is not connected.
        """
        return self.get_session(account_id).modify_order(order_data)

    def cancel_order(self, account_id: str, order_data: dict[str, Any]) -> dict[str, Any]:
        """Cancel a single open order on the specified account.

        Args:
            account_id: Target account identifier.
            order_data: Must contain the order ID to cancel.

        Returns:
            Broker response dict.

        Raises:
            BrokerNotFoundError: If ``account_id`` is not registered.
            SessionError: If the session is not connected.
        """
        return self.get_session(account_id).cancel_order(order_data)

    def cancel_all_orders(self, account_id: str) -> dict[str, Any]:
        """Cancel all open orders on the specified account.

        Args:
            account_id: Target account identifier.

        Returns:
            Broker response dict.

        Raises:
            BrokerNotFoundError: If ``account_id`` is not registered.
            SessionError: If the session is not connected.
        """
        return self.get_session(account_id).cancel_all_orders()

    def close_position(self, account_id: str, position_data: dict[str, Any]) -> dict[str, Any]:
        """Close an open position on the specified account.

        Args:
            account_id: Target account identifier.
            position_data: Position identifier/parameters.

        Returns:
            Broker response dict.

        Raises:
            BrokerNotFoundError: If ``account_id`` is not registered.
            SessionError: If the session is not connected.
        """
        return self.get_session(account_id).close_position(position_data)

    def place_options_order(self, account_id: str, order_data: dict[str, Any]) -> dict[str, Any]:
        """Submit an options-specific order on the specified account.

        Args:
            account_id: Target account identifier.
            order_data: Options order parameters.

        Returns:
            Broker response dict.

        Raises:
            BrokerNotFoundError: If ``account_id`` is not registered.
            SessionError: If the session is not connected.
        """
        return self.get_session(account_id).place_options_order(order_data)

    def get_positions(self, account_id: str) -> list[dict[str, Any]]:
        """Fetch current open positions for the specified account.

        Args:
            account_id: Target account identifier.

        Returns:
            Broker response (positions list or wrapper dict).

        Raises:
            BrokerNotFoundError: If ``account_id`` is not registered.
            SessionError: If the session is not connected.
        """
        return self.get_session(account_id).get_positions()  # type: ignore[return-value]

    def get_orders(self, account_id: str) -> list[dict[str, Any]]:
        """Fetch today's order book for the specified account.

        Args:
            account_id: Target account identifier.

        Returns:
            Broker response (orders list or wrapper dict).

        Raises:
            BrokerNotFoundError: If ``account_id`` is not registered.
            SessionError: If the session is not connected.
        """
        return self.get_session(account_id).get_orders()  # type: ignore[return-value]

    def get_trades(self, account_id: str) -> list[dict[str, Any]]:
        """Fetch today's trade book for the specified account.

        Args:
            account_id: Target account identifier.

        Returns:
            Broker response (trades list or wrapper dict).

        Raises:
            BrokerNotFoundError: If ``account_id`` is not registered.
            SessionError: If the session is not connected.
        """
        return self.get_session(account_id).get_trades()  # type: ignore[return-value]

    def get_holdings(self, account_id: str) -> list[dict[str, Any]]:
        """Fetch long-term holdings for the specified account.

        Args:
            account_id: Target account identifier.

        Returns:
            Broker response (holdings list or wrapper dict).

        Raises:
            BrokerNotFoundError: If ``account_id`` is not registered.
            SessionError: If the session is not connected.
        """
        return self.get_session(account_id).get_holdings()  # type: ignore[return-value]

    def get_funds(self, account_id: str) -> dict[str, Any]:
        """Fetch available funds and margin summary for the specified account.

        Args:
            account_id: Target account identifier.

        Returns:
            Broker response dict with fund details.

        Raises:
            BrokerNotFoundError: If ``account_id`` is not registered.
            SessionError: If the session is not connected.
        """
        return self.get_session(account_id).get_funds()

    def get_margin(self, account_id: str, order_data: dict[str, Any]) -> dict[str, Any]:
        """Calculate required margin for a hypothetical order.

        Args:
            account_id: Target account identifier.
            order_data: Order parameters for margin estimation.

        Returns:
            Broker response dict with margin breakdown.

        Raises:
            BrokerNotFoundError: If ``account_id`` is not registered.
            SessionError: If the session is not connected.
        """
        return self.get_session(account_id).get_margin(order_data)

    def get_quotes(self, account_id: str, symbol: str, exchange: str) -> dict[str, Any]:
        """Fetch a live quote via the specified account.

        Args:
            account_id: Target account identifier.
            symbol: Instrument symbol string.
            exchange: Exchange code (e.g. ``"NSE"``).

        Returns:
            Broker response dict with quote data.

        Raises:
            BrokerNotFoundError: If ``account_id`` is not registered.
            SessionError: If the session is not connected.
        """
        return self.get_session(account_id).get_quotes([symbol])

    def get_depth(self, account_id: str, symbol: str) -> dict[str, Any]:
        """Fetch market depth for a symbol via the specified account.

        Args:
            account_id: Target account identifier.
            symbol: Exchange-qualified symbol string.

        Returns:
            Broker response dict with bid/ask depth levels.

        Raises:
            BrokerNotFoundError: If ``account_id`` is not registered.
            SessionError: If the session is not connected.
        """
        return self.get_session(account_id).get_depth(symbol)

    def get_history(self, account_id: str, params: dict[str, Any]) -> dict[str, Any]:
        """Fetch historical OHLCV data via the specified account.

        Args:
            account_id: Target account identifier.
            params: Query parameters (symbol, interval, from/to dates).

        Returns:
            Broker response dict with OHLCV candles.

        Raises:
            BrokerNotFoundError: If ``account_id`` is not registered.
            SessionError: If the session is not connected.
        """
        return self.get_session(account_id).get_history(params)

    def search_symbols(self, account_id: str, query: str) -> dict[str, Any]:
        """Search for instruments via the specified account.

        Args:
            account_id: Target account identifier.
            query: Free-text or partial symbol search string.

        Returns:
            Broker response dict with matching instrument list.

        Raises:
            BrokerNotFoundError: If ``account_id`` is not registered.
            SessionError: If the session is not connected.
        """
        return self.get_session(account_id).search_symbols(query)

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    def _build_info(self, session: BrokerSession) -> BrokerAccountInfo:
        """Construct a :class:`~models.BrokerAccountInfo` from a session.

        Merges the session's own :attr:`~session.BrokerSession.info`
        snapshot with the registry's ``is_primary`` tracking.

        Args:
            session: The session whose info is requested.

        Returns:
            A :class:`~models.BrokerAccountInfo` with ``is_primary``
            correctly set according to the registry's current state.
        """
        base = session.info
        with self._lock:
            is_primary = self._primary == base.account_id
        return base.model_copy(update={"is_primary": is_primary})
