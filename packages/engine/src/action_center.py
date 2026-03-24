"""Action Center: semi-automatic order approval queue.

When enabled, orders are held for manual approval before execution.
Thread-safe with configurable TTL for pending orders.
"""

from __future__ import annotations

import logging
import threading
import time
import uuid
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any

logger = logging.getLogger("flinttrade.engine.action_center")


class OrderApprovalStatus(StrEnum):
    """Status values for a pending order in the approval queue."""

    PENDING = "pending"
    APPROVED = "approved"
    REJECTED = "rejected"
    EXPIRED = "expired"


@dataclass
class PendingOrder:
    """A single order held in the Action Center approval queue.

    Attributes:
        order_id: Unique identifier for this queued order.
        account_id: Broker account that submitted the order.
        order_data: Raw order payload to be forwarded to the router on approval.
        status: Current approval status.
        created_at: Unix timestamp when the order was submitted.
        resolved_at: Unix timestamp when the order was approved/rejected/expired,
            or ``None`` if still pending.
    """

    order_id: str
    account_id: str
    order_data: dict[str, Any]
    status: OrderApprovalStatus = OrderApprovalStatus.PENDING
    created_at: float = field(default_factory=time.time)
    resolved_at: float | None = None

    def to_dict(self) -> dict[str, Any]:
        """Serialise to a JSON-safe dict.

        Returns:
            dict representation with all fields JSON-serialisable.
        """
        return {
            "order_id": self.order_id,
            "account_id": self.account_id,
            "order_data": self.order_data,
            "status": str(self.status),
            "created_at": self.created_at,
            "resolved_at": self.resolved_at,
        }


class ActionCenterError(Exception):
    """Raised when an Action Center operation cannot be completed."""


class ActionCenter:
    """Thread-safe order approval queue for semi-automatic trading.

    When :attr:`enabled` is ``True``, orders submitted via :meth:`submit`
    are held in a pending queue rather than being executed immediately.
    A human operator (or UI widget) must call :meth:`approve` or
    :meth:`reject` before execution proceeds.

    Stale orders whose age exceeds *ttl_seconds* are automatically
    transitioned to :attr:`OrderApprovalStatus.EXPIRED` on the next read.

    Args:
        ttl_seconds: Maximum age in seconds before a pending order expires.
            Defaults to 300 (5 minutes).

    Example:
        >>> ac = ActionCenter(ttl_seconds=60)
        >>> ac.enabled = True
        >>> po = ac.submit("ord-1", "acct-1", {"symbol": "NIFTY"})
        >>> ac.approve("ord-1")
        PendingOrder(order_id='ord-1', status=<OrderApprovalStatus.APPROVED: 'approved'>, ...)
    """

    def __init__(self, ttl_seconds: int = 300) -> None:
        self._ttl_seconds = ttl_seconds
        self._enabled: bool = False
        self._orders: dict[str, PendingOrder] = {}
        self._lock = threading.Lock()

    # ------------------------------------------------------------------
    # Properties
    # ------------------------------------------------------------------

    @property
    def enabled(self) -> bool:
        """Whether the Action Center intercept is active."""
        return self._enabled

    @enabled.setter
    def enabled(self, value: bool) -> None:
        with self._lock:
            prev = self._enabled
            self._enabled = bool(value)
        if prev != self._enabled:
            logger.info(
                "Action Center %s", "ENABLED" if self._enabled else "DISABLED"
            )

    @property
    def ttl_seconds(self) -> int:
        """Pending-order TTL in seconds."""
        return self._ttl_seconds

    @ttl_seconds.setter
    def ttl_seconds(self, value: int) -> None:
        if value < 1:
            raise ValueError("ttl_seconds must be >= 1")
        with self._lock:
            self._ttl_seconds = value

    # ------------------------------------------------------------------
    # Queue operations
    # ------------------------------------------------------------------

    def submit(
        self,
        order_id: str | None,
        account_id: str,
        order_data: dict[str, Any],
    ) -> PendingOrder:
        """Add an order to the approval queue.

        Args:
            order_id: Caller-supplied identifier, or ``None`` to auto-generate
                a UUID.
            account_id: Broker account submitting the order.
            order_data: The order payload dict (symbol, action, qty, etc.).

        Returns:
            The newly created :class:`PendingOrder`.

        Raises:
            ActionCenterError: If an order with the same *order_id* already
                exists in the queue.
        """
        oid = order_id or str(uuid.uuid4())
        with self._lock:
            if oid in self._orders:
                raise ActionCenterError(
                    f"Order '{oid}' already exists in the Action Center queue"
                )
            po = PendingOrder(
                order_id=oid,
                account_id=account_id,
                order_data=order_data,
            )
            self._orders[oid] = po
        logger.info(
            "Queued order %s for account %s (symbol=%s)",
            oid,
            account_id,
            order_data.get("symbol", "?"),
        )
        return po

    def approve(self, order_id: str) -> PendingOrder:
        """Approve a pending order and mark it ready for execution.

        Args:
            order_id: The identifier of the order to approve.

        Returns:
            The updated :class:`PendingOrder` with status APPROVED.

        Raises:
            ActionCenterError: If the order does not exist or is not in
                PENDING status.
        """
        with self._lock:
            self._expire_stale()
            po = self._get_or_raise(order_id)
            if po.status != OrderApprovalStatus.PENDING:
                raise ActionCenterError(
                    f"Order '{order_id}' is {po.status}, not PENDING"
                )
            po.status = OrderApprovalStatus.APPROVED
            po.resolved_at = time.time()
        logger.info("Approved order %s", order_id)
        return po

    def reject(self, order_id: str) -> PendingOrder:
        """Reject a pending order.

        Args:
            order_id: The identifier of the order to reject.

        Returns:
            The updated :class:`PendingOrder` with status REJECTED.

        Raises:
            ActionCenterError: If the order does not exist or is not in
                PENDING status.
        """
        with self._lock:
            self._expire_stale()
            po = self._get_or_raise(order_id)
            if po.status != OrderApprovalStatus.PENDING:
                raise ActionCenterError(
                    f"Order '{order_id}' is {po.status}, not PENDING"
                )
            po.status = OrderApprovalStatus.REJECTED
            po.resolved_at = time.time()
        logger.info("Rejected order %s", order_id)
        return po

    def approve_all(self) -> list[PendingOrder]:
        """Approve every currently pending (non-expired) order.

        Returns:
            List of :class:`PendingOrder` objects that were approved.  May be
            empty if no orders were pending.
        """
        approved: list[PendingOrder] = []
        with self._lock:
            self._expire_stale()
            now = time.time()
            for po in self._orders.values():
                if po.status == OrderApprovalStatus.PENDING:
                    po.status = OrderApprovalStatus.APPROVED
                    po.resolved_at = now
                    approved.append(po)
        logger.info("Approved %d order(s) in bulk", len(approved))
        return approved

    def get_pending(self) -> list[PendingOrder]:
        """Return all orders currently in PENDING status.

        Stale orders are expired before the list is built.

        Returns:
            List of :class:`PendingOrder` with status PENDING.
        """
        with self._lock:
            self._expire_stale()
            return [
                po
                for po in self._orders.values()
                if po.status == OrderApprovalStatus.PENDING
            ]

    def get_all(self) -> list[PendingOrder]:
        """Return all orders in the queue regardless of status.

        Returns:
            List of all :class:`PendingOrder` objects, newest first.
        """
        with self._lock:
            self._expire_stale()
            return sorted(self._orders.values(), key=lambda o: o.created_at, reverse=True)

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _expire_stale(self) -> None:
        """Mark orders past their TTL as EXPIRED.

        Must be called while holding ``self._lock``.
        """
        cutoff = time.time() - self._ttl_seconds
        for po in self._orders.values():
            if po.status == OrderApprovalStatus.PENDING and po.created_at < cutoff:
                po.status = OrderApprovalStatus.EXPIRED
                po.resolved_at = time.time()
                logger.debug("Expired order %s (age exceeded TTL %ds)", po.order_id, self._ttl_seconds)

    def _get_or_raise(self, order_id: str) -> PendingOrder:
        """Look up an order by ID or raise ActionCenterError.

        Must be called while holding ``self._lock``.

        Args:
            order_id: The order identifier to look up.

        Returns:
            The matching :class:`PendingOrder`.

        Raises:
            ActionCenterError: If *order_id* is not in the queue.
        """
        po = self._orders.get(order_id)
        if po is None:
            raise ActionCenterError(f"Order '{order_id}' not found in Action Center queue")
        return po
