"""Alert trigger log — durable audit trail of alert fire events.

Pattern absorbed from YFinance-Alert-Manager:
- Alert fires → log the trigger with full price context
- Debounce: suppress re-triggers within a configurable cooldown (default 60 s)
- Auto-pause: one-shot alerts are marked paused immediately after their first
  trigger so the caller can stop re-evaluating them

Storage: DuckDB.  Pass ``db_path=":memory:"`` for tests or ephemeral use.
The table is created on first use (CREATE TABLE IF NOT EXISTS).

Usage::

    log = AlertTriggerLog(db_path=":memory:")
    tid = log.log_trigger(
        alert_id="alert-001",
        trigger_price=24500.0,
        alert_price=24500.0,
        symbol="NIFTY",
        condition="PRICE_CROSS_ABOVE",
    )
    if not log.should_debounce("alert-001", cooldown_sec=60):
        # fire the notification
        pass
    log.auto_pause_alert("alert-001")
"""

from __future__ import annotations

import logging
import time
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone

logger = logging.getLogger("flinttrade.integration.alert_trigger_log")

IST = timezone(timedelta(hours=5, minutes=30))

_CREATE_TRIGGERS = """
CREATE TABLE IF NOT EXISTS alert_triggers (
    trigger_id  VARCHAR PRIMARY KEY,
    alert_id    VARCHAR NOT NULL,
    symbol      VARCHAR NOT NULL,
    condition   VARCHAR NOT NULL,
    alert_price DOUBLE  NOT NULL,
    trigger_price DOUBLE NOT NULL,
    triggered_at VARCHAR NOT NULL,
    triggered_epoch DOUBLE NOT NULL
)
"""

_CREATE_PAUSED = """
CREATE TABLE IF NOT EXISTS alert_paused (
    alert_id    VARCHAR PRIMARY KEY,
    paused_at   VARCHAR NOT NULL
)
"""


@dataclass
class TriggerEvent:
    """A single alert trigger record.

    Attributes:
        trigger_id: UUID string — unique per trigger event.
        alert_id: Identifier of the alert definition that fired.
        symbol: Trading symbol that triggered the alert (e.g. ``"NIFTY"``).
        condition: Human-readable condition string (e.g. ``"PRICE_CROSS_ABOVE"``).
        alert_price: The price threshold defined in the alert.
        trigger_price: Actual LTP at the moment the alert fired.
        triggered_at: ISO-8601 timestamp string in IST.
    """

    trigger_id: str
    alert_id: str
    symbol: str
    condition: str
    alert_price: float
    trigger_price: float
    triggered_at: str
    triggered_epoch: float = field(default_factory=time.time)


class AlertTriggerLog:
    """Durable DuckDB-backed audit trail of alert trigger events.

    Each call to :meth:`log_trigger` writes one row to the ``alert_triggers``
    table.  :meth:`should_debounce` checks whether the same alert has already
    fired within the cooldown window.  :meth:`auto_pause_alert` records the
    alert ID in a separate ``alert_paused`` table so the caller can skip
    evaluation on subsequent ticks.

    Args:
        db_path: DuckDB file path.  Use ``":memory:"`` for in-process storage.
    """

    def __init__(self, db_path: str = ":memory:") -> None:
        self._db_path = db_path
        # For in-memory databases, keep a persistent connection open so the
        # schema (and data) survive across method calls.  For file-backed
        # databases, each method opens and closes its own connection, which
        # is safe for concurrent access.
        self._mem_conn = None
        if db_path == ":memory:":
            import duckdb
            self._mem_conn = duckdb.connect(":memory:")
        self._ensure_schema()

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def log_trigger(
        self,
        alert_id: str,
        trigger_price: float,
        alert_price: float,
        symbol: str,
        condition: str,
    ) -> str:
        """Record that an alert fired.

        Args:
            alert_id: Identifier of the alert definition.
            trigger_price: Actual price at the moment of trigger.
            alert_price: The threshold price from the alert definition.
            symbol: Trading symbol (e.g. ``"NIFTY"``).
            condition: Condition description (e.g. ``"PRICE_CROSS_ABOVE"``).

        Returns:
            The ``trigger_id`` (UUID string) of the newly created record.
        """
        trigger_id = str(uuid.uuid4())
        now_epoch = time.time()
        now_str = datetime.fromtimestamp(now_epoch, tz=IST).isoformat()

        try:
            conn = self._connect()
            conn.execute(
                """
                INSERT INTO alert_triggers
                    (trigger_id, alert_id, symbol, condition,
                     alert_price, trigger_price, triggered_at, triggered_epoch)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                [
                    trigger_id, alert_id, symbol, condition,
                    alert_price, trigger_price, now_str, now_epoch,
                ],
            )
            self._close(conn)
            logger.info(
                "Trigger logged: alert_id=%s symbol=%s condition=%s trigger_price=%.2f",
                alert_id, symbol, condition, trigger_price,
            )
        except Exception as exc:
            logger.error("Failed to log trigger for alert_id=%s: %s", alert_id, exc)

        return trigger_id

    def should_debounce(self, alert_id: str, cooldown_sec: int = 60) -> bool:
        """Return ``True`` if the alert fired within the cooldown window.

        If ``True``, the caller should suppress the notification for this tick.

        Args:
            alert_id: Alert to check.
            cooldown_sec: Minimum seconds that must elapse between triggers.

        Returns:
            ``True`` if the alert is within its cooldown period.
        """
        try:
            conn = self._connect()
            row = conn.execute(
                """
                SELECT MAX(triggered_epoch)
                FROM alert_triggers
                WHERE alert_id = ?
                """,
                [alert_id],
            ).fetchone()
            self._close(conn)

            if row is None or row[0] is None:
                return False

            elapsed = time.time() - row[0]
            return elapsed < cooldown_sec

        except Exception as exc:
            logger.error("should_debounce query failed for alert_id=%s: %s", alert_id, exc)
            return False

    def get_triggers(
        self,
        alert_id: str | None = None,
        limit: int = 50,
    ) -> list[TriggerEvent]:
        """Retrieve trigger history, newest first.

        Args:
            alert_id: Optional filter — if provided, only returns triggers for
                that alert.
            limit: Maximum number of records to return.

        Returns:
            List of :class:`TriggerEvent` objects ordered by
            ``triggered_epoch`` descending.
        """
        try:
            conn = self._connect()
            if alert_id is not None:
                rows = conn.execute(
                    """
                    SELECT trigger_id, alert_id, symbol, condition,
                           alert_price, trigger_price, triggered_at, triggered_epoch
                    FROM alert_triggers
                    WHERE alert_id = ?
                    ORDER BY triggered_epoch DESC
                    LIMIT ?
                    """,
                    [alert_id, limit],
                ).fetchall()
            else:
                rows = conn.execute(
                    """
                    SELECT trigger_id, alert_id, symbol, condition,
                           alert_price, trigger_price, triggered_at, triggered_epoch
                    FROM alert_triggers
                    ORDER BY triggered_epoch DESC
                    LIMIT ?
                    """,
                    [limit],
                ).fetchall()
            self._close(conn)

            return [
                TriggerEvent(
                    trigger_id=r[0],
                    alert_id=r[1],
                    symbol=r[2],
                    condition=r[3],
                    alert_price=r[4],
                    trigger_price=r[5],
                    triggered_at=r[6],
                    triggered_epoch=r[7],
                )
                for r in rows
            ]

        except Exception as exc:
            logger.error("get_triggers failed: %s", exc)
            return []

    def auto_pause_alert(self, alert_id: str) -> None:
        """Mark an alert as paused (one-shot pattern).

        Writes the ``alert_id`` into the ``alert_paused`` table with a
        timestamp.  Does nothing if the alert is already paused.

        Args:
            alert_id: Alert to pause.
        """
        try:
            now_str = datetime.now(tz=IST).isoformat()
            conn = self._connect()
            # INSERT OR IGNORE equivalent — only insert when not already present
            conn.execute(
                """
                INSERT OR IGNORE INTO alert_paused (alert_id, paused_at)
                VALUES (?, ?)
                """,
                [alert_id, now_str],
            )
            self._close(conn)
            logger.info("Alert paused: alert_id=%s", alert_id)
        except Exception as exc:
            logger.error("auto_pause_alert failed for alert_id=%s: %s", alert_id, exc)

    def is_paused(self, alert_id: str) -> bool:
        """Check whether an alert has been paused.

        Args:
            alert_id: Alert to check.

        Returns:
            ``True`` if the alert appears in the ``alert_paused`` table.
        """
        try:
            conn = self._connect()
            row = conn.execute(
                "SELECT 1 FROM alert_paused WHERE alert_id = ?",
                [alert_id],
            ).fetchone()
            self._close(conn)
            return row is not None
        except Exception as exc:
            logger.error("is_paused query failed for alert_id=%s: %s", alert_id, exc)
            return False

    def resume_alert(self, alert_id: str) -> None:
        """Un-pause an alert so it can fire again.

        Args:
            alert_id: Alert to resume.
        """
        try:
            conn = self._connect()
            conn.execute(
                "DELETE FROM alert_paused WHERE alert_id = ?",
                [alert_id],
            )
            self._close(conn)
            logger.info("Alert resumed: alert_id=%s", alert_id)
        except Exception as exc:
            logger.error("resume_alert failed for alert_id=%s: %s", alert_id, exc)

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _connect(self):
        """Return a DuckDB connection.

        For in-memory databases the same persistent connection is always
        returned (so the schema survives across calls).  For file-backed
        databases a new connection is opened each time; the caller is
        responsible for closing it.
        """
        if self._mem_conn is not None:
            return self._mem_conn
        import duckdb
        return duckdb.connect(self._db_path)

    def _close(self, conn) -> None:
        """Close conn only if it is not the persistent in-memory connection."""
        if conn is not self._mem_conn:
            conn.close()

    def _ensure_schema(self) -> None:
        """Create tables if they do not yet exist."""
        try:
            conn = self._connect()
            conn.execute(_CREATE_TRIGGERS)
            conn.execute(_CREATE_PAUSED)
            self._close(conn)
        except Exception as exc:
            logger.error("Schema creation failed for db_path=%s: %s", self._db_path, exc)
