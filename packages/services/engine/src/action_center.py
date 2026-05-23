"""Action Center: semi-automatic order approval queue.

When enabled, orders are held for manual approval before execution.
Thread-safe with configurable TTL for pending orders.

Includes a DuckDB-backed PendingOrderQueue with ApprovalRequest persistence
for a richer approval workflow with reason tracking and audit history.
"""

from __future__ import annotations

import logging
import threading
import time
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import StrEnum
from pathlib import Path
from typing import Any, Literal

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


# ---------------------------------------------------------------------------
# ApprovalRequest — richer approval workflow with DuckDB persistence
# ---------------------------------------------------------------------------

ApprovalStatus = Literal["pending", "approved", "rejected", "expired"]


@dataclass
class ApprovalRequest:
    """An approval request for an order awaiting human confirmation.

    Compared to :class:`PendingOrder`, ``ApprovalRequest`` carries an explicit
    human-readable *reason* and an *expires_at* deadline.  Instances are
    persisted to DuckDB so they survive process restarts.

    Attributes:
        id: UUID string uniquely identifying this request.
        order_params: The full order payload to be sent on approval.
        reason: Human-readable explanation of why approval is needed.
        created_at: UTC ISO-8601 timestamp when the request was created.
        expires_at: UTC ISO-8601 timestamp after which the request auto-expires.
        status: One of ``"pending"``, ``"approved"``, ``"rejected"``,
            ``"expired"``.
        rejection_reason: Operator-supplied reason when status is
            ``"rejected"``, or ``None`` otherwise.
    """

    id: str
    order_params: dict[str, Any]
    reason: str
    created_at: str
    expires_at: str
    status: ApprovalStatus = "pending"
    rejection_reason: str | None = None

    def to_dict(self) -> dict[str, Any]:
        """Serialise to a JSON-safe dict.

        Returns:
            All fields mapped to JSON-compatible Python types.
        """
        return {
            "id": self.id,
            "order_params": self.order_params,
            "reason": self.reason,
            "created_at": self.created_at,
            "expires_at": self.expires_at,
            "status": self.status,
            "rejection_reason": self.rejection_reason,
        }

    @classmethod
    def from_row(cls, row: tuple[Any, ...]) -> "ApprovalRequest":
        """Reconstruct from a DuckDB row (ordered by column definition).

        Args:
            row: Tuple ``(id, order_params_json, reason, created_at,
                expires_at, status, rejection_reason)`` as returned by
                DuckDB queries.

        Returns:
            Populated :class:`ApprovalRequest` instance.
        """
        import json as _json

        return cls(
            id=row[0],
            order_params=_json.loads(row[1]),
            reason=row[2],
            created_at=row[3],
            expires_at=row[4],
            status=row[5],
            rejection_reason=row[6],
        )


def _utc_now_iso() -> str:
    """Return the current UTC time as an ISO-8601 string."""
    return datetime.now(timezone.utc).isoformat()


def _iso_to_ts(iso: str) -> float:
    """Convert an ISO-8601 UTC string to a POSIX timestamp.

    Args:
        iso: ISO-8601 formatted datetime string (UTC).

    Returns:
        Float POSIX timestamp.
    """
    return datetime.fromisoformat(iso).timestamp()


def _default_db_path() -> Path:
    """Return the default DuckDB path under ``~/.flinttrade/``.

    Returns:
        Absolute :class:`~pathlib.Path` to ``action_center.duckdb``.
    """
    return Path.home() / ".flinttrade" / "action_center.duckdb"


class PendingOrderQueue:
    """Persistent approval-request queue backed by DuckDB.

    Extends the in-memory :class:`ActionCenter` design with full persistence
    so that pending approvals survive process restarts.  Each instance opens
    (or creates) its own DuckDB file; the class is thread-safe.

    Args:
        db_path: Path to the DuckDB database file.  Defaults to
            ``~/.flinttrade/action_center.duckdb``.

    Example:
        >>> queue = PendingOrderQueue()
        >>> req = queue.enqueue({"symbol": "NIFTY", "qty": 50}, "Manual review")
        >>> queue.approve(req.id)
        >>> pending = queue.list_pending()
        >>> assert len(pending) == 0
    """

    _DDL = """
        CREATE TABLE IF NOT EXISTS approval_requests (
            id               TEXT PRIMARY KEY,
            order_params     TEXT NOT NULL,
            reason           TEXT NOT NULL,
            created_at       TEXT NOT NULL,
            expires_at       TEXT NOT NULL,
            status           TEXT NOT NULL DEFAULT 'pending',
            rejection_reason TEXT
        );
    """

    def __init__(self, db_path: Path | str | None = None) -> None:
        self._db_path = Path(db_path) if db_path else _default_db_path()
        self._db_path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()
        self._conn = self._connect()

    # ------------------------------------------------------------------
    # Connection
    # ------------------------------------------------------------------

    def _connect(self):  # type: ignore[return]
        """Open DuckDB connection and ensure schema exists.

        Returns:
            Open ``duckdb.DuckDBPyConnection`` instance.
        """
        try:
            import duckdb  # lazy import — optional at module level

            conn = duckdb.connect(str(self._db_path))
            conn.execute(self._DDL)
            return conn
        except ImportError as exc:
            raise ActionCenterError(
                "duckdb is required for PendingOrderQueue persistence. "
                "Install it with: pip install duckdb"
            ) from exc

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def enqueue(
        self,
        order_params: dict[str, Any],
        reason: str,
        ttl_minutes: int = 5,
        request_id: str | None = None,
    ) -> ApprovalRequest:
        """Add an order to the persistent approval queue.

        Args:
            order_params: Full order payload to be forwarded on approval.
            reason: Human-readable reason why approval is required.
            ttl_minutes: Minutes until the request auto-expires.  Defaults
                to 5.
            request_id: Override the auto-generated UUID if desired.

        Returns:
            The persisted :class:`ApprovalRequest` with status ``"pending"``.
        """
        import json as _json
        from datetime import timedelta

        req_id = request_id or str(uuid.uuid4())
        now = datetime.now(timezone.utc)
        created_at = now.isoformat()
        expires_at = (now + timedelta(minutes=ttl_minutes)).isoformat()

        req = ApprovalRequest(
            id=req_id,
            order_params=order_params,
            reason=reason,
            created_at=created_at,
            expires_at=expires_at,
            status="pending",
        )

        with self._lock:
            self._conn.execute(
                """
                INSERT INTO approval_requests
                    (id, order_params, reason, created_at, expires_at, status)
                VALUES (?, ?, ?, ?, ?, 'pending')
                """,
                [req_id, _json.dumps(order_params), reason, created_at, expires_at],
            )

        logger.info(
            "Enqueued approval request %s for symbol=%s (expires %s)",
            req_id,
            order_params.get("symbol", "?"),
            expires_at,
        )
        return req

    def approve(self, request_id: str) -> ApprovalRequest:
        """Approve a pending approval request.

        Args:
            request_id: UUID of the request to approve.

        Returns:
            Updated :class:`ApprovalRequest` with status ``"approved"``.

        Raises:
            ActionCenterError: If the request is not found or is not
                ``"pending"``.
        """
        with self._lock:
            self._expire_stale()
            req = self._fetch_or_raise(request_id)
            if req.status != "pending":
                raise ActionCenterError(
                    f"Request '{request_id}' is '{req.status}', not 'pending'"
                )
            self._conn.execute(
                "UPDATE approval_requests SET status = 'approved' WHERE id = ?",
                [request_id],
            )
            req.status = "approved"

        logger.info("Approved approval request %s", request_id)
        return req

    def reject(self, request_id: str, reason: str = "") -> ApprovalRequest:
        """Reject a pending approval request.

        Args:
            request_id: UUID of the request to reject.
            reason: Optional explanation for the rejection.

        Returns:
            Updated :class:`ApprovalRequest` with status ``"rejected"``.

        Raises:
            ActionCenterError: If the request is not found or is not
                ``"pending"``.
        """
        with self._lock:
            self._expire_stale()
            req = self._fetch_or_raise(request_id)
            if req.status != "pending":
                raise ActionCenterError(
                    f"Request '{request_id}' is '{req.status}', not 'pending'"
                )
            self._conn.execute(
                """
                UPDATE approval_requests
                   SET status = 'rejected', rejection_reason = ?
                 WHERE id = ?
                """,
                [reason, request_id],
            )
            req.status = "rejected"
            req.rejection_reason = reason

        logger.info("Rejected approval request %s (reason: %s)", request_id, reason or "none")
        return req

    def list_pending(self) -> list[ApprovalRequest]:
        """Return all requests currently in ``"pending"`` status.

        Stale requests are expired before the list is built.

        Returns:
            List of :class:`ApprovalRequest` with status ``"pending"``,
            ordered oldest first.
        """
        with self._lock:
            self._expire_stale()
            rows = self._conn.execute(
                "SELECT * FROM approval_requests WHERE status = 'pending' ORDER BY created_at"
            ).fetchall()
        return [ApprovalRequest.from_row(r) for r in rows]

    def list_history(
        self,
        statuses: list[ApprovalStatus] | None = None,
        limit: int = 100,
    ) -> list[ApprovalRequest]:
        """Return resolved (non-pending) requests for audit purposes.

        Args:
            statuses: Filter by these status values.  ``None`` returns all
                non-pending statuses (approved, rejected, expired).
            limit: Maximum rows returned, ordered newest first.

        Returns:
            List of :class:`ApprovalRequest` matching the filter.
        """
        allowed = statuses or ["approved", "rejected", "expired"]
        placeholders = ", ".join("?" for _ in allowed)
        with self._lock:
            rows = self._conn.execute(
                f"""
                SELECT * FROM approval_requests
                 WHERE status IN ({placeholders})
                 ORDER BY created_at DESC
                 LIMIT ?
                """,
                [*allowed, limit],
            ).fetchall()
        return [ApprovalRequest.from_row(r) for r in rows]

    def expire_stale(self, minutes: int | None = None) -> int:
        """Manually expire requests that have passed their ``expires_at`` deadline.

        Args:
            minutes: If provided, expire requests older than *minutes* minutes
                from now (overrides the ``expires_at`` field).  Otherwise
                uses each request's own ``expires_at``.

        Returns:
            Number of requests that were transitioned to ``"expired"``.
        """
        with self._lock:
            return self._expire_stale(minutes)

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _expire_stale(self, minutes: int | None = None) -> int:
        """Expire stale pending requests.  Must be called under ``self._lock``.

        Args:
            minutes: If set, expire pending requests older than *minutes*
                from now.  Otherwise uses each request's ``expires_at``.

        Returns:
            Number of requests marked expired.
        """
        now_iso = _utc_now_iso()

        # Count pending requests that match the expiry predicate BEFORE updating.
        if minutes is not None:
            from datetime import timedelta

            cutoff = (
                datetime.now(timezone.utc) - timedelta(minutes=minutes)
            ).isoformat()
            pre_count: int = self._conn.execute(
                """
                SELECT COUNT(*) FROM approval_requests
                 WHERE status = 'pending' AND created_at < ?
                """,
                [cutoff],
            ).fetchone()[0]  # type: ignore[index]
            self._conn.execute(
                """
                UPDATE approval_requests
                   SET status = 'expired'
                 WHERE status = 'pending'
                   AND created_at < ?
                """,
                [cutoff],
            )
        else:
            pre_count = self._conn.execute(
                """
                SELECT COUNT(*) FROM approval_requests
                 WHERE status = 'pending' AND expires_at < ?
                """,
                [now_iso],
            ).fetchone()[0]  # type: ignore[index]
            self._conn.execute(
                """
                UPDATE approval_requests
                   SET status = 'expired'
                 WHERE status = 'pending'
                   AND expires_at < ?
                """,
                [now_iso],
            )

        count: int = pre_count
        if count:
            logger.debug("Expired %d stale approval request(s)", count)
        return count

    def _fetch_or_raise(self, request_id: str) -> ApprovalRequest:
        """Fetch a request by ID or raise :class:`ActionCenterError`.

        Must be called while holding ``self._lock``.

        Args:
            request_id: UUID to look up.

        Returns:
            The matching :class:`ApprovalRequest`.

        Raises:
            ActionCenterError: If *request_id* is not found.
        """
        row = self._conn.execute(
            "SELECT * FROM approval_requests WHERE id = ?",
            [request_id],
        ).fetchone()
        if row is None:
            raise ActionCenterError(f"Approval request '{request_id}' not found")
        return ApprovalRequest.from_row(row)

    def close(self) -> None:
        """Close the underlying DuckDB connection."""
        with self._lock:
            self._conn.close()
