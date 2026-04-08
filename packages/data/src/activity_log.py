"""SEBI-compliant activity log for all state-changing mutations.

Every order, position change, setting update, and admin action is persisted
in a DuckDB table with timestamp, user, action type, IP address, and a JSON
details blob.  Designed for the FlintTrade admin dashboard and regulatory audit.

Actions logged:
    order.place, order.cancel, order.modify
    position.close
    settings.update
    auth.login, auth.logout
    mode.switch
    strategy.start, strategy.stop
    bracket.place, bracket.cancel
"""

from __future__ import annotations

import json
import secrets
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Any

IST = timezone(timedelta(hours=5, minutes=30))

# Actions that are considered valid mutations to log.
KNOWN_ACTIONS: frozenset[str] = frozenset(
    [
        "order.place",
        "order.cancel",
        "order.modify",
        "position.close",
        "settings.update",
        "auth.login",
        "auth.logout",
        "mode.switch",
        "strategy.start",
        "strategy.stop",
        "bracket.place",
        "bracket.cancel",
    ]
)

_CREATE_TABLE_SQL = """
CREATE TABLE IF NOT EXISTS activity_log (
    log_id      VARCHAR PRIMARY KEY,
    timestamp   VARCHAR NOT NULL,
    action      VARCHAR NOT NULL,
    user        VARCHAR NOT NULL,
    ip          VARCHAR,
    details     VARCHAR NOT NULL
)
"""

_INDEX_SQL = [
    "CREATE INDEX IF NOT EXISTS idx_activity_action ON activity_log(action)",
    "CREATE INDEX IF NOT EXISTS idx_activity_user   ON activity_log(user)",
    "CREATE INDEX IF NOT EXISTS idx_activity_ts     ON activity_log(timestamp)",
]


@dataclass
class ActivityEntry:
    """A single record from the activity log.

    Attributes:
        log_id: Unique identifier for this log entry (8-char hex token).
        timestamp: ISO-8601 timestamp in IST.
        action: Dot-namespaced action string (e.g. ``order.place``).
        user: Username or ``system`` for automated actions.
        ip: Remote IP address if available; ``None`` for internal actions.
        details: Arbitrary JSON-serialisable payload describing the mutation.
    """

    log_id: str
    timestamp: str
    action: str
    user: str
    ip: str | None
    details: dict[str, Any] = field(default_factory=dict)


class ActivityLog:
    """SEBI-compliant activity log for all mutations.

    Every order, position change, setting update, and admin action is logged
    with timestamp, user, action, and details.

    The log is backed by a DuckDB database (in-memory by default; provide a
    file path for persistence).  Entries are append-only — never deleted
    through this API.

    Example::

        log = ActivityLog("~/.flinttrade/activity.db")
        log_id = log.log("order.place", {"symbol": "NIFTY", "qty": 50},
                         user="navaneesh", ip="10.10.10.2")
        entries = log.query(action="order.place", limit=20)
        count = log.count_actions("order.place", since="2026-04-01T00:00:00")

    Args:
        db_path: DuckDB path. Defaults to ``:memory:`` (ephemeral).
    """

    def __init__(self, db_path: str = ":memory:") -> None:
        import duckdb  # lazy import — avoids penalising startup if not used

        self._conn = duckdb.connect(db_path)
        self._conn.execute(_CREATE_TABLE_SQL)
        for idx_sql in _INDEX_SQL:
            self._conn.execute(idx_sql)

    # ------------------------------------------------------------------
    # Write
    # ------------------------------------------------------------------

    def log(
        self,
        action: str,
        details: dict[str, Any],
        user: str = "system",
        ip: str | None = None,
    ) -> str:
        """Log an activity and return the generated ``log_id``.

        Args:
            action: Dot-namespaced action string (e.g. ``order.place``).
                    Unlisted actions are accepted — only known actions are
                    listed in ``KNOWN_ACTIONS`` for reference.
            details: Arbitrary JSON-serialisable payload.
            user: Actor performing the action; defaults to ``"system"``.
            ip: Remote IP address of the caller; ``None`` for internal calls.

        Returns:
            The unique ``log_id`` assigned to this entry (8-character hex).
        """
        log_id = secrets.token_hex(8)
        timestamp = datetime.now(IST).isoformat()
        details_json = json.dumps(details, default=str, ensure_ascii=False)

        self._conn.execute(
            "INSERT INTO activity_log VALUES (?, ?, ?, ?, ?, ?)",
            [log_id, timestamp, action, user, ip, details_json],
        )
        return log_id

    # ------------------------------------------------------------------
    # Read
    # ------------------------------------------------------------------

    def query(
        self,
        action: str | None = None,
        user: str | None = None,
        since: str | None = None,
        limit: int = 100,
    ) -> list[ActivityEntry]:
        """Query the activity log with optional filters.

        Args:
            action: Filter by exact action string (e.g. ``"order.place"``).
            user: Filter by username.
            since: ISO-8601 timestamp lower-bound (inclusive).
            limit: Maximum number of entries to return (most recent first).

        Returns:
            List of :class:`ActivityEntry` ordered by timestamp descending.
        """
        clauses: list[str] = []
        params: list[Any] = []

        if action is not None:
            clauses.append("action = ?")
            params.append(action)
        if user is not None:
            clauses.append("user = ?")
            params.append(user)
        if since is not None:
            clauses.append("timestamp >= ?")
            params.append(since)

        where = ("WHERE " + " AND ".join(clauses)) if clauses else ""
        sql = f"""
            SELECT log_id, timestamp, action, user, ip, details
            FROM activity_log
            {where}
            ORDER BY timestamp DESC
            LIMIT {int(limit)}
        """
        rows = self._conn.execute(sql, params).fetchall()
        return [
            ActivityEntry(
                log_id=row[0],
                timestamp=row[1],
                action=row[2],
                user=row[3],
                ip=row[4],
                details=json.loads(row[5]),
            )
            for row in rows
        ]

    def count_actions(self, action: str, since: str | None = None) -> int:
        """Count occurrences of an action, optionally after a timestamp.

        Args:
            action: Exact action string to count.
            since: ISO-8601 lower-bound timestamp (inclusive); ``None`` counts all.

        Returns:
            Integer count of matching rows.
        """
        if since is not None:
            row = self._conn.execute(
                "SELECT COUNT(*) FROM activity_log WHERE action = ? AND timestamp >= ?",
                [action, since],
            ).fetchone()
        else:
            row = self._conn.execute(
                "SELECT COUNT(*) FROM activity_log WHERE action = ?",
                [action],
            ).fetchone()
        return int(row[0]) if row else 0

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    def close(self) -> None:
        """Close the underlying DuckDB connection."""
        self._conn.close()

    def __enter__(self) -> "ActivityLog":
        return self

    def __exit__(self, *args: Any) -> None:
        self.close()
