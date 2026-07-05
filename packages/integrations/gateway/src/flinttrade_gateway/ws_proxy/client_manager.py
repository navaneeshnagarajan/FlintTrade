"""ClientManager — tracks connected WebSocket clients and their subscriptions.

Each connected client is represented by a :class:`ClientSession` which holds
the client's asyncio queue and subscription metadata.  ``ClientManager`` owns
all sessions and provides clean-up helpers for disconnection.
"""

from __future__ import annotations

import asyncio
import logging
import time
from dataclasses import dataclass, field
from typing import Any

from flinttrade_gateway.log_safety import log_ref

logger = logging.getLogger("flinttrade.gateway.ws_proxy.client_manager")


@dataclass
class ClientSession:
    """Per-client state for one WebSocket connection.

    Attributes:
        client_id: Unique opaque identifier (assigned at connection time).
        queue: Asyncio queue for outgoing ticks.
        authenticated: Whether the client has presented a valid API key.
        connected_at: Unix epoch seconds when the session was created.
        subscriptions: Set of ``"SYMBOL:EXCHANGE:MODE"`` keys this client
            is subscribed to.
        remote_addr: Optional remote address string for logging.
    """

    client_id: str
    queue: asyncio.Queue[dict[str, Any]] = field(
        default_factory=lambda: asyncio.Queue(maxsize=1_000)
    )
    authenticated: bool = False
    connected_at: float = field(default_factory=time.time)
    subscriptions: set[str] = field(default_factory=set)
    remote_addr: str = ""

    def add_subscription(self, symbol: str, exchange: str, mode: str) -> None:
        """Record a subscription key on this session.

        Args:
            symbol: Instrument symbol.
            exchange: Exchange code.
            mode: Subscription mode.
        """
        key = f"{symbol.upper()}:{exchange.upper()}:{mode.upper()}"
        self.subscriptions.add(key)

    def remove_subscription(self, symbol: str, exchange: str, mode: str) -> None:
        """Remove a subscription key from this session.

        Args:
            symbol: Instrument symbol.
            exchange: Exchange code.
            mode: Subscription mode.
        """
        key = f"{symbol.upper()}:{exchange.upper()}:{mode.upper()}"
        self.subscriptions.discard(key)

    @property
    def age_seconds(self) -> float:
        """Return elapsed seconds since this session was created."""
        return time.time() - self.connected_at


class ClientManager:
    """Registry of active WebSocket client sessions.

    Provides thread-safe (within asyncio) add/remove/lookup operations
    and aggregate statistics for health monitoring.

    Typical lifecycle::

        session = manager.add(client_id="abc123")
        # … client interacts …
        manager.remove("abc123")
    """

    def __init__(self) -> None:
        self._sessions: dict[str, ClientSession] = {}

    # ------------------------------------------------------------------
    # Session lifecycle
    # ------------------------------------------------------------------

    def add(
        self,
        client_id: str,
        remote_addr: str = "",
        queue_maxsize: int = 1_000,
    ) -> ClientSession:
        """Create and register a new client session.

        Args:
            client_id: Unique identifier for this client.
            remote_addr: Remote address string (for logging).
            queue_maxsize: Maximum depth of the client's outgoing tick queue.

        Returns:
            The newly created :class:`ClientSession`.

        Raises:
            ValueError: If a session with ``client_id`` already exists.
        """
        if client_id in self._sessions:
            raise ValueError(f"Client '{client_id}' is already registered")

        session = ClientSession(
            client_id=client_id,
            queue=asyncio.Queue(maxsize=queue_maxsize),
            remote_addr=remote_addr,
        )
        self._sessions[client_id] = session
        logger.debug(
            "ClientManager: added client '%s' (%s)",
            log_ref(client_id, kind="client"),
            log_ref(remote_addr, kind="remote"),
        )
        return session

    def remove(self, client_id: str) -> ClientSession | None:
        """Remove and return the session for ``client_id``.

        Args:
            client_id: The client to remove.

        Returns:
            The removed :class:`ClientSession`, or ``None`` if not found.
        """
        session = self._sessions.pop(client_id, None)
        if session is not None:
            logger.debug("ClientManager: removed client '%s'", log_ref(client_id, kind="client"))
        return session

    def get(self, client_id: str) -> ClientSession | None:
        """Look up a client session by ID.

        Args:
            client_id: The client identifier.

        Returns:
            The :class:`ClientSession` or ``None`` if not found.
        """
        return self._sessions.get(client_id)

    # ------------------------------------------------------------------
    # Introspection
    # ------------------------------------------------------------------

    @property
    def connected_count(self) -> int:
        """Number of currently registered client sessions."""
        return len(self._sessions)

    @property
    def authenticated_count(self) -> int:
        """Number of sessions that have passed authentication."""
        return sum(1 for s in self._sessions.values() if s.authenticated)

    def all_sessions(self) -> list[ClientSession]:
        """Return a snapshot of all current sessions.

        Returns:
            List of :class:`ClientSession` objects.
        """
        return list(self._sessions.values())

    def stats(self) -> dict[str, Any]:
        """Return aggregate client statistics.

        Returns:
            Dict with ``connected_clients``, ``authenticated_clients``,
            and ``total_subscriptions``.
        """
        total_subs = sum(len(s.subscriptions) for s in self._sessions.values())
        return {
            "connected_clients": self.connected_count,
            "authenticated_clients": self.authenticated_count,
            "total_subscriptions": total_subs,
        }
