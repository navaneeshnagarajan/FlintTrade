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

ApprovalStatus = Literal[
    "pending",
    "dispatching",
    "approved",
    "rejected",
    "expired",
    "failed",
]


@dataclass(frozen=True)
class ApprovalDispatchResult:
    """Result returned by the request-time gated approval dispatcher.

    The queue owns persistence and single-use state transitions; the injected
    dispatcher owns fresh authentication, safety evaluation, and BrokerRouter
    dispatch.  Keeping this small result type between those layers prevents a
    Flask response object or a stale request context from being persisted.
    """

    succeeded: bool
    status_code: int
    message: str = ""
    broker_order_id: str | None = None
    outcome_uncertain: bool = False

    @classmethod
    def success(cls, broker_order_id: str) -> "ApprovalDispatchResult":
        """Build a confirmed broker-dispatch result."""
        return cls(
            succeeded=True,
            status_code=200,
            broker_order_id=str(broker_order_id),
        )

    @classmethod
    def refused(
        cls,
        status_code: int,
        message: str,
        *,
        outcome_uncertain: bool = False,
    ) -> "ApprovalDispatchResult":
        """Build a failed or refused dispatch result."""
        return cls(
            succeeded=False,
            status_code=int(status_code),
            message=str(message),
            outcome_uncertain=bool(outcome_uncertain),
        )


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
    adapter_id: str = "openalgo"
    account_id: str = "default"
    source: str = "unknown"
    intent_type: str = "entry"
    producer_ref: str = ""
    intent_context: dict[str, Any] = field(default_factory=dict)
    resolved_at: str | None = None
    broker_order_id: str | None = None
    failure_reason: str | None = None
    outcome_uncertain: bool = False

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
            "adapter_id": self.adapter_id,
            "account_id": self.account_id,
            "source": self.source,
            "intent_type": self.intent_type,
            "producer_ref": self.producer_ref,
            "intent_context": self.intent_context,
            "resolved_at": self.resolved_at,
            "broker_order_id": self.broker_order_id,
            "failure_reason": self.failure_reason,
            "outcome_uncertain": self.outcome_uncertain,
        }

    def to_terminal_dict(self) -> dict[str, Any]:
        """Return the stable flattened shape consumed by the terminal widget."""

        def _number(value: Any) -> float:
            try:
                return float(value)
            except (TypeError, ValueError):
                return 0.0

        params = self.order_params
        return {
            "id": self.id,
            "symbol": str(params.get("symbol") or ""),
            "exchange": str(params.get("exchange") or ""),
            "action": str(params.get("action") or "").upper(),
            "quantity": int(_number(params.get("quantity"))),
            "price": _number(params.get("price")),
            "order_type": str(
                params.get("pricetype") or params.get("order_type") or "MARKET"
            ).upper(),
            "product": str(params.get("product") or ""),
            "strategy": str(params.get("strategy") or ""),
            "created_at": self.created_at,
            "expires_at": self.expires_at,
            "reason": self.reason,
            "broker": self.adapter_id,
            "account_id": self.account_id,
            "source": self.source,
            "status": self.status,
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
            adapter_id=row[7],
            account_id=row[8],
            source=row[9],
            intent_type=row[10],
            producer_ref=row[11],
            intent_context=_json.loads(row[12] or "{}"),
            resolved_at=row[13],
            broker_order_id=row[14],
            failure_reason=row[15],
            outcome_uncertain=bool(row[16]),
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
            rejection_reason TEXT,
            adapter_id       TEXT NOT NULL DEFAULT 'openalgo',
            account_id       TEXT NOT NULL DEFAULT 'default',
            source           TEXT NOT NULL DEFAULT 'unknown',
            intent_type      TEXT NOT NULL DEFAULT 'entry',
            producer_ref     TEXT NOT NULL DEFAULT '',
            intent_context   TEXT NOT NULL DEFAULT '{}',
            resolved_at      TEXT,
            broker_order_id  TEXT,
            failure_reason   TEXT,
            outcome_uncertain BOOLEAN NOT NULL DEFAULT FALSE
        );
    """

    _SELECT_COLUMNS = """
        id, order_params, reason, created_at, expires_at, status,
        rejection_reason, adapter_id, account_id, source, intent_type,
        producer_ref, intent_context, resolved_at, broker_order_id,
        failure_reason, outcome_uncertain
    """

    _MIGRATIONS = (
        "ALTER TABLE approval_requests ADD COLUMN IF NOT EXISTS adapter_id TEXT DEFAULT 'openalgo'",
        "ALTER TABLE approval_requests ADD COLUMN IF NOT EXISTS account_id TEXT DEFAULT 'default'",
        "ALTER TABLE approval_requests ADD COLUMN IF NOT EXISTS source TEXT DEFAULT 'unknown'",
        "ALTER TABLE approval_requests ADD COLUMN IF NOT EXISTS intent_type TEXT DEFAULT 'entry'",
        "ALTER TABLE approval_requests ADD COLUMN IF NOT EXISTS producer_ref TEXT DEFAULT ''",
        "ALTER TABLE approval_requests ADD COLUMN IF NOT EXISTS intent_context TEXT DEFAULT '{}'",
        "ALTER TABLE approval_requests ADD COLUMN IF NOT EXISTS resolved_at TEXT",
        "ALTER TABLE approval_requests ADD COLUMN IF NOT EXISTS broker_order_id TEXT",
        "ALTER TABLE approval_requests ADD COLUMN IF NOT EXISTS failure_reason TEXT",
        "ALTER TABLE approval_requests ADD COLUMN IF NOT EXISTS outcome_uncertain BOOLEAN DEFAULT FALSE",
    )

    _SENSITIVE_KEY_PARTS = (
        "token",
        "secret",
        "credential",
        "password",
        "authorization",
        "cookie",
        "api_key",
        "apikey",
        "safety_context",
        "request_context",
        "jti",
    )

    def __init__(self, db_path: Path | str | None = None) -> None:
        self._db_path = Path(db_path) if db_path else _default_db_path()
        self._db_path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()
        self._conn = self._connect()
        self._reconcile_interrupted_dispatches()

    # ------------------------------------------------------------------
    # Connection
    # ------------------------------------------------------------------

    def _reconcile_interrupted_dispatches(self) -> int:
        """Fail-close any dispatch left in flight by a previous process.

        A ``dispatching`` row is written just before the broker call and cleared
        only by :meth:`mark_approved`/:meth:`mark_failed`.  If the process dies
        in between, the row is orphaned: ``_expire_stale`` only touches
        ``pending`` rows, ``claim_for_dispatch`` will not re-claim it, and no
        surviving context can finalise it — so it lingers as a phantom in-flight
        intent forever.

        The broker outcome for such a row is genuinely unknown, so recovery must
        never silently re-dispatch (double-order risk) nor mark it approved.  We
        terminally close it as ``failed`` with ``outcome_uncertain`` set, which
        surfaces it to the operator through the existing uncertain-outcome
        affordance.  Returns the number of rows reconciled.
        """
        with self._lock:
            rows = self._conn.execute(
                """
                UPDATE approval_requests
                   SET status = 'failed', resolved_at = ?,
                       failure_reason = ?, outcome_uncertain = TRUE
                 WHERE status = 'dispatching'
                RETURNING id
                """,
                [
                    _utc_now_iso(),
                    "process restarted while the broker dispatch was in flight; outcome unknown",
                ],
            ).fetchall()
        reconciled = len(rows)
        if reconciled:
            logger.warning(
                "Reconciled %d interrupted Action Centre dispatch(es) to failed/outcome-uncertain "
                "after a restart (broker outcome unknown): %s",
                reconciled,
                ", ".join(str(row[0]) for row in rows),
            )
        return reconciled

    def _connect(self):  # type: ignore[return]
        """Open DuckDB connection and ensure schema exists.

        Returns:
            Open ``duckdb.DuckDBPyConnection`` instance.
        """
        try:
            import duckdb  # lazy import — optional at module level

            conn = duckdb.connect(str(self._db_path))
            conn.execute(self._DDL)
            for statement in self._MIGRATIONS:
                conn.execute(statement)
            return conn
        except ImportError as exc:
            raise ActionCenterError(
                "duckdb is required for PendingOrderQueue persistence. "
                "Install it with: pip install duckdb"
            ) from exc

    @classmethod
    def _reject_sensitive_material(cls, value: Any, *, path: str = "payload") -> None:
        """Reject auth, credential, and gate material before durable storage."""
        if isinstance(value, dict):
            for key, item in value.items():
                normalised = str(key).strip().lower().replace("-", "_")
                if any(part in normalised for part in cls._SENSITIVE_KEY_PARTS):
                    raise ActionCenterError(
                        "Authentication or credential material cannot be persisted in Action Centre intents"
                    )
                cls._reject_sensitive_material(item, path=f"{path}.{normalised}")
        elif isinstance(value, (list, tuple)):
            for index, item in enumerate(value):
                cls._reject_sensitive_material(item, path=f"{path}[{index}]")

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def enqueue(
        self,
        order_params: dict[str, Any],
        reason: str,
        ttl_minutes: int = 5,
        request_id: str | None = None,
        *,
        adapter_id: str = "openalgo",
        account_id: str = "default",
        source: str = "unknown",
        intent_type: str = "entry",
        producer_ref: str = "",
        intent_context: dict[str, Any] | None = None,
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

        if ttl_minutes < 0:
            raise ActionCenterError("ttl_minutes must be >= 0")
        context = dict(intent_context or {})
        self._reject_sensitive_material(order_params, path="order_params")
        self._reject_sensitive_material(context, path="intent_context")

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
            adapter_id=str(adapter_id or "").strip().lower() or "openalgo",
            account_id=str(account_id or "").strip() or "default",
            source=str(source or "").strip() or "unknown",
            intent_type=str(intent_type or "").strip() or "entry",
            producer_ref=str(producer_ref or "").strip(),
            intent_context=context,
        )

        with self._lock:
            try:
                self._conn.execute(
                    """
                    INSERT INTO approval_requests (
                        id, order_params, reason, created_at, expires_at, status,
                        adapter_id, account_id, source, intent_type, producer_ref,
                        intent_context
                    ) VALUES (?, ?, ?, ?, ?, 'pending', ?, ?, ?, ?, ?, ?)
                    """,
                    [
                        req_id,
                        _json.dumps(order_params),
                        reason,
                        created_at,
                        expires_at,
                        req.adapter_id,
                        req.account_id,
                        req.source,
                        req.intent_type,
                        req.producer_ref,
                        _json.dumps(context),
                    ],
                )
            except Exception as exc:
                raise ActionCenterError(
                    f"Approval request '{req_id}' already exists"
                ) from exc

        logger.info(
            "Enqueued approval request %s for symbol=%s (expires %s)",
            req_id,
            order_params.get("symbol", "?"),
            expires_at,
        )
        return req

    def get(self, request_id: str) -> ApprovalRequest:
        """Return one request after applying pending expiry."""
        with self._lock:
            self._expire_stale()
            return self._fetch_or_raise(request_id)

    def claim_for_dispatch(self, request_id: str) -> ApprovalRequest:
        """Atomically claim one unexpired pending request for broker dispatch.

        The ``pending -> dispatching`` transition happens before any broker
        operation. A replay, concurrent approval, or process retry therefore
        cannot dispatch the same intent twice.
        """
        with self._lock:
            self._expire_stale()
            rows = self._conn.execute(
                f"""
                UPDATE approval_requests
                   SET status = 'dispatching'
                 WHERE id = ? AND status = 'pending' AND expires_at >= ?
                RETURNING {self._SELECT_COLUMNS}
                """,
                [request_id, _utc_now_iso()],
            ).fetchall()
            if rows:
                return ApprovalRequest.from_row(rows[0])
            current = self._fetch_or_raise(request_id)
            raise ActionCenterError(
                f"Request '{request_id}' is '{current.status}', not 'pending'"
            )

    def mark_approved(
        self,
        request_id: str,
        *,
        broker_order_id: str,
    ) -> ApprovalRequest:
        """Finalise a claimed request after confirmed BrokerRouter success."""
        resolved_at = _utc_now_iso()
        with self._lock:
            rows = self._conn.execute(
                f"""
                UPDATE approval_requests
                   SET status = 'approved', resolved_at = ?, broker_order_id = ?,
                       failure_reason = NULL, outcome_uncertain = FALSE
                 WHERE id = ? AND status = 'dispatching'
                RETURNING {self._SELECT_COLUMNS}
                """,
                [resolved_at, str(broker_order_id), request_id],
            ).fetchall()
            if rows:
                return ApprovalRequest.from_row(rows[0])
            current = self._fetch_or_raise(request_id)
            raise ActionCenterError(
                f"Request '{request_id}' is '{current.status}', not 'dispatching'"
            )

    def mark_failed(
        self,
        request_id: str,
        *,
        reason: str,
        outcome_uncertain: bool = False,
    ) -> ApprovalRequest:
        """Terminally close a claimed request after refusal or uncertain I/O."""
        resolved_at = _utc_now_iso()
        with self._lock:
            rows = self._conn.execute(
                f"""
                UPDATE approval_requests
                   SET status = 'failed', resolved_at = ?, failure_reason = ?,
                       outcome_uncertain = ?
                 WHERE id = ? AND status = 'dispatching'
                RETURNING {self._SELECT_COLUMNS}
                """,
                [resolved_at, str(reason), bool(outcome_uncertain), request_id],
            ).fetchall()
            if rows:
                return ApprovalRequest.from_row(rows[0])
            current = self._fetch_or_raise(request_id)
            raise ActionCenterError(
                f"Request '{request_id}' is '{current.status}', not 'dispatching'"
            )

    def approve(self, request_id: str) -> ApprovalRequest:
        """Compatibility helper that resolves a request without broker output.

        Shipped HTTP routes do not call this method: they use
        :meth:`claim_for_dispatch` followed by :meth:`mark_approved` only after
        the injected gated dispatcher confirms success.

        Args:
            request_id: UUID of the request to approve.

        Returns:
            Updated :class:`ApprovalRequest` with status ``"approved"``.

        Raises:
            ActionCenterError: If the request is not found or is not
                ``"pending"``.
        """
        self.claim_for_dispatch(request_id)
        approved = self.mark_approved(request_id, broker_order_id="compatibility-only")
        logger.info("Resolved approval request %s through compatibility helper", request_id)
        return approved

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
        resolved_at = _utc_now_iso()
        with self._lock:
            self._expire_stale()
            rows = self._conn.execute(
                f"""
                UPDATE approval_requests
                   SET status = 'rejected', rejection_reason = ?, resolved_at = ?
                 WHERE id = ? AND status = 'pending'
                RETURNING {self._SELECT_COLUMNS}
                """,
                [reason, resolved_at, request_id],
            ).fetchall()
            if not rows:
                current = self._fetch_or_raise(request_id)
                raise ActionCenterError(
                    f"Request '{request_id}' is '{current.status}', not 'pending'"
                )
            req = ApprovalRequest.from_row(rows[0])

        logger.info("Rejected approval request %s (reason: %s)", request_id, reason or "none")
        return req

    def reject_pending_by_producer(self, producer_ref: str, reason: str) -> int:
        """Reject pending entry intents owned by an ended producer session."""
        if not producer_ref:
            return 0
        with self._lock:
            rows = self._conn.execute(
                f"""
                UPDATE approval_requests
                   SET status = 'rejected', rejection_reason = ?, resolved_at = ?
                 WHERE producer_ref = ? AND status = 'pending'
                RETURNING {self._SELECT_COLUMNS}
                """,
                [reason, _utc_now_iso(), producer_ref],
            ).fetchall()
        return len(rows)

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
                f"""
                SELECT {self._SELECT_COLUMNS}
                  FROM approval_requests
                 WHERE status = 'pending'
                 ORDER BY created_at
                """
            ).fetchall()
        return [ApprovalRequest.from_row(r) for r in rows]

    def list_all(self, limit: int = 500) -> list[ApprovalRequest]:
        """Return pending and resolved requests, newest first."""
        with self._lock:
            self._expire_stale()
            rows = self._conn.execute(
                f"""
                SELECT {self._SELECT_COLUMNS}
                  FROM approval_requests
                 ORDER BY created_at DESC
                 LIMIT ?
                """,
                [max(1, int(limit))],
            ).fetchall()
        return [ApprovalRequest.from_row(row) for row in rows]

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
        allowed = statuses or ["dispatching", "approved", "rejected", "expired", "failed"]
        placeholders = ", ".join("?" for _ in allowed)
        with self._lock:
            self._expire_stale()
            rows = self._conn.execute(
                f"""
                SELECT {self._SELECT_COLUMNS} FROM approval_requests
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
                   SET status = 'expired', resolved_at = ?
                 WHERE status = 'pending'
                   AND created_at < ?
                """,
                [now_iso, cutoff],
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
                   SET status = 'expired', resolved_at = ?
                 WHERE status = 'pending'
                   AND expires_at < ?
                """,
                [now_iso, now_iso],
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
            f"SELECT {self._SELECT_COLUMNS} FROM approval_requests WHERE id = ?",
            [request_id],
        ).fetchone()
        if row is None:
            raise ActionCenterError(f"Approval request '{request_id}' not found")
        return ApprovalRequest.from_row(row)

    def close(self) -> None:
        """Close the underlying DuckDB connection."""
        with self._lock:
            self._conn.close()
