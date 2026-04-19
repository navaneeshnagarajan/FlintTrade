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
import logging
import secrets
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Any

logger = logging.getLogger("flinttrade.data.activity_log")

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
    timestamp   TIMESTAMP NOT NULL,
    action      VARCHAR NOT NULL,
    user        VARCHAR NOT NULL,
    ip          VARCHAR,
    details     VARCHAR NOT NULL,
    source      VARCHAR
)
"""

_INDEX_SQL = [
    "CREATE INDEX IF NOT EXISTS idx_activity_action ON activity_log(action)",
    "CREATE INDEX IF NOT EXISTS idx_activity_user   ON activity_log(user)",
    "CREATE INDEX IF NOT EXISTS idx_activity_ts     ON activity_log(timestamp)",
    "CREATE INDEX IF NOT EXISTS idx_activity_source ON activity_log(source)",
]

# Migration: add source column to existing databases that lack it.
_MIGRATE_ADD_SOURCE = "ALTER TABLE activity_log ADD COLUMN source VARCHAR"


@dataclass
class ActivityEntry:
    """A single record from the activity log.

    Attributes:
        log_id: Unique identifier for this log entry (8-char hex token).
        timestamp: Timezone-aware datetime of the event (stored as TIMESTAMP).
        action: Dot-namespaced action string (e.g. ``order.place``).
        user: Username or ``system`` for automated actions.
        ip: Remote IP address if available; ``None`` for internal actions.
        details: Arbitrary JSON-serialisable payload describing the mutation.
        source: Origin of the action (e.g. ``"SCALPER"``, ``"ORDERPAD"``,
            ``"FLOW"``, ``"WEBHOOK"``, ``"API"``).  ``None`` for legacy entries.
    """

    log_id: str
    timestamp: datetime
    action: str
    user: str
    ip: str | None
    details: dict[str, Any] = field(default_factory=dict)
    source: str | None = None


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
        # Migrate existing databases that lack the source column.
        try:
            self._conn.execute(_MIGRATE_ADD_SOURCE)
        except duckdb.CatalogException:
            pass  # Column already exists — nothing to do.
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
        source: str | None = None,
    ) -> str:
        """Log an activity and return the generated ``log_id``.

        Args:
            action: Dot-namespaced action string (e.g. ``order.place``).
                    Unlisted actions are accepted — only known actions are
                    listed in ``KNOWN_ACTIONS`` for reference.
            details: Arbitrary JSON-serialisable payload.
            user: Actor performing the action; defaults to ``"system"``.
            ip: Remote IP address of the caller; ``None`` for internal calls.
            source: Origin widget or subsystem that triggered this action
                (e.g. ``"SCALPER"``, ``"ORDERPAD"``, ``"FLOW"``,
                ``"WEBHOOK"``, ``"API"``).  ``None`` for untagged entries.

        Returns:
            The unique ``log_id`` assigned to this entry (8-character hex).
        """
        log_id = secrets.token_hex(8)
        timestamp = datetime.now(IST)
        details_json = json.dumps(details, default=str, ensure_ascii=False)

        self._conn.execute(
            "INSERT INTO activity_log VALUES (?, ?, ?, ?, ?, ?, ?)",
            [log_id, timestamp, action, user, ip, details_json, source],
        )
        return log_id

    # ------------------------------------------------------------------
    # Read
    # ------------------------------------------------------------------

    def query(
        self,
        action: str | None = None,
        user: str | None = None,
        since: str | datetime | None = None,
        source: str | None = None,
        limit: int = 100,
    ) -> list[ActivityEntry]:
        """Query the activity log with optional filters.

        Args:
            action: Filter by exact action string (e.g. ``"order.place"``).
            user: Filter by username.
            since: Lower-bound datetime (inclusive).  Accepts a
                timezone-aware ``datetime`` object or an ISO-8601 string.
            source: Filter by source origin (e.g. ``"SCALPER"``).
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
            since_dt: datetime = datetime.fromisoformat(since) if isinstance(since, str) else since
            clauses.append("timestamp >= ?")
            params.append(since_dt)
        if source is not None:
            clauses.append("source = ?")
            params.append(source)

        where = ("WHERE " + " AND ".join(clauses)) if clauses else ""
        params.append(int(limit))
        sql = f"""
            SELECT log_id, timestamp, action, user, ip, details, source
            FROM activity_log
            {where}
            ORDER BY timestamp DESC
            LIMIT ?
        """
        rows = self._conn.execute(sql, params).fetchall()
        result: list[ActivityEntry] = []
        for row in rows:
            ts = row[1]
            # DuckDB returns TIMESTAMP as a datetime; guard against
            # legacy VARCHAR rows in existing databases.
            if isinstance(ts, str):
                ts = datetime.fromisoformat(ts)
            result.append(
                ActivityEntry(
                    log_id=row[0],
                    timestamp=ts,
                    action=row[2],
                    user=row[3],
                    ip=row[4],
                    details=json.loads(row[5]),
                    source=row[6],
                )
            )
        return result

    def count_actions(self, action: str, since: str | datetime | None = None) -> int:
        """Count occurrences of an action, optionally after a timestamp.

        Args:
            action: Exact action string to count.
            since: Lower-bound datetime (inclusive).  Accepts a
                timezone-aware ``datetime`` object or an ISO-8601 string.
                ``None`` counts all rows.

        Returns:
            Integer count of matching rows.
        """
        if since is not None:
            # Normalise string to datetime so DuckDB compares against TIMESTAMP.
            since_dt: datetime
            if isinstance(since, str):
                since_dt = datetime.fromisoformat(since)
            else:
                since_dt = since
            row = self._conn.execute(
                "SELECT COUNT(*) FROM activity_log WHERE action = ? AND timestamp >= ?",
                [action, since_dt],
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


# ---------------------------------------------------------------------------
# LoginActivity — per-login event tracking
# ---------------------------------------------------------------------------

_CREATE_LOGIN_TABLE_SQL = """
CREATE TABLE IF NOT EXISTS login_activity (
    event_id    VARCHAR PRIMARY KEY,
    timestamp   TIMESTAMP NOT NULL,
    user_id     VARCHAR NOT NULL,
    ip          VARCHAR NOT NULL,
    user_agent  VARCHAR,
    success     BOOLEAN NOT NULL,
    failure_reason VARCHAR
)
"""

_LOGIN_INDEXES_SQL = [
    "CREATE INDEX IF NOT EXISTS idx_login_user      ON login_activity(user_id)",
    "CREATE INDEX IF NOT EXISTS idx_login_ts        ON login_activity(timestamp)",
    "CREATE INDEX IF NOT EXISTS idx_login_ip        ON login_activity(ip)",
    "CREATE INDEX IF NOT EXISTS idx_login_success   ON login_activity(success)",
]


class LoginActivity:
    """Track every login attempt — successful and failed — with device info.

    Backed by a DuckDB table ``login_activity``.  Designed to power the
    admin security dashboard and suspicious-login alerts.

    Args:
        db_path: DuckDB path.  Defaults to ``:memory:`` (ephemeral).

    Example::

        la = LoginActivity("~/.flinttrade/activity.db")
        la.log_login("nav", "10.10.10.2", "Mozilla/5.0 ...", success=True)
        la.log_login("nav", "1.2.3.4", "curl/7.64", success=False,
                     failure_reason="bad_password")
        recent = la.recent_logins(user_id="nav", limit=10)
        suspicious = la.suspicious_logins(window_hours=24)
    """

    def __init__(self, db_path: str = ":memory:") -> None:
        import duckdb  # lazy import

        self._conn = duckdb.connect(db_path)
        self._conn.execute(_CREATE_LOGIN_TABLE_SQL)
        for idx in _LOGIN_INDEXES_SQL:
            self._conn.execute(idx)

    # ------------------------------------------------------------------
    # Write
    # ------------------------------------------------------------------

    def log_login(
        self,
        user_id: str,
        ip: str,
        user_agent: str | None,
        success: bool,
        failure_reason: str | None = None,
    ) -> str:
        """Record a login attempt.

        Args:
            user_id: Username attempting to log in.
            ip: Remote IP address of the client.
            user_agent: HTTP User-Agent header value, or ``None``.
            success: ``True`` for a successful login, ``False`` for failure.
            failure_reason: Short description of why login failed (e.g.
                ``"bad_password"``, ``"bad_totp"``, ``"account_locked"``).
                Should be ``None`` when *success* is ``True``.

        Returns:
            The unique ``event_id`` assigned to this entry (16-character hex).
        """
        event_id = secrets.token_hex(8)
        timestamp = datetime.now(IST)
        self._conn.execute(
            "INSERT INTO login_activity VALUES (?, ?, ?, ?, ?, ?, ?)",
            [event_id, timestamp, user_id, ip, user_agent, success, failure_reason],
        )
        return event_id

    # ------------------------------------------------------------------
    # Read
    # ------------------------------------------------------------------

    def recent_logins(
        self,
        user_id: str | None = None,
        limit: int = 100,
    ) -> list[dict[str, Any]]:
        """Return recent login events, newest first.

        Args:
            user_id: If given, filter to this user only.
            limit: Maximum number of rows to return.

        Returns:
            List of dicts with keys: ``event_id``, ``timestamp``,
            ``user_id``, ``ip``, ``user_agent``, ``success``,
            ``failure_reason``.
        """
        params: list[Any] = []
        where = ""
        if user_id is not None:
            where = "WHERE user_id = ?"
            params.append(user_id)
        params.append(int(limit))
        sql = f"""
            SELECT event_id, timestamp, user_id, ip, user_agent,
                   success, failure_reason
            FROM login_activity
            {where}
            ORDER BY timestamp DESC
            LIMIT ?
        """
        rows = self._conn.execute(sql, params).fetchall()
        return [
            {
                "event_id": r[0],
                "timestamp": r[1].isoformat() if hasattr(r[1], "isoformat") else str(r[1]),
                "user_id": r[2],
                "ip": r[3],
                "user_agent": r[4],
                "success": bool(r[5]),
                "failure_reason": r[6],
            }
            for r in rows
        ]

    def suspicious_logins(self, window_hours: int = 24) -> list[dict[str, Any]]:
        """Return IPs with more than 3 failed login attempts within *window_hours*.

        Args:
            window_hours: Lookback window in hours.  Defaults to 24.

        Returns:
            List of dicts with keys: ``ip``, ``failed_count``,
            ``last_attempt``, ``affected_users``.  Ordered by
            ``failed_count`` descending.
        """
        since = datetime.now(IST) - timedelta(hours=window_hours)
        sql = """
            SELECT ip,
                   COUNT(*)                                     AS failed_count,
                   MAX(timestamp)                               AS last_attempt,
                   COUNT(DISTINCT user_id)                      AS affected_users
            FROM login_activity
            WHERE success = FALSE
              AND timestamp >= ?
            GROUP BY ip
            HAVING COUNT(*) > 3
            ORDER BY failed_count DESC
        """
        rows = self._conn.execute(sql, [since]).fetchall()
        return [
            {
                "ip": r[0],
                "failed_count": int(r[1]),
                "last_attempt": r[2].isoformat() if hasattr(r[2], "isoformat") else str(r[2]),
                "affected_users": int(r[3]),
            }
            for r in rows
        ]

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    def close(self) -> None:
        """Close the underlying DuckDB connection."""
        self._conn.close()

    def __enter__(self) -> "LoginActivity":
        return self

    def __exit__(self, *args: Any) -> None:
        self.close()


# ---------------------------------------------------------------------------
# SessionTracker — active authenticated session management
# ---------------------------------------------------------------------------

_CREATE_SESSION_TABLE_SQL = """
CREATE TABLE IF NOT EXISTS active_sessions (
    session_id  VARCHAR PRIMARY KEY,
    user_id     VARCHAR NOT NULL,
    ip          VARCHAR NOT NULL,
    user_agent  VARCHAR,
    device_id   VARCHAR,
    created_at  TIMESTAMP NOT NULL,
    last_active TIMESTAMP NOT NULL,
    ended_at    TIMESTAMP
)
"""

_SESSION_INDEXES_SQL = [
    "CREATE INDEX IF NOT EXISTS idx_sess_user    ON active_sessions(user_id)",
    "CREATE INDEX IF NOT EXISTS idx_sess_active  ON active_sessions(last_active)",
    "CREATE INDEX IF NOT EXISTS idx_sess_ended   ON active_sessions(ended_at)",
]


class SessionTracker:
    """Track active authenticated sessions with heartbeat support.

    Each session is a row in the ``active_sessions`` DuckDB table.  A session
    is considered active when ``ended_at`` is ``NULL``.

    Args:
        db_path: DuckDB path.  Defaults to ``:memory:`` (ephemeral).

    Example::

        st = SessionTracker("~/.flinttrade/activity.db")
        st.register_session("sess-abc", "nav", "10.10.10.2",
                            "Mozilla/5.0 ...", device_id="laptop-1")
        st.heartbeat("sess-abc")
        sessions = st.active_sessions(user_id="nav")
        expired = st.expire_stale(idle_minutes=60)
        st.end_session("sess-abc")
    """

    def __init__(self, db_path: str = ":memory:") -> None:
        import duckdb  # lazy import

        self._conn = duckdb.connect(db_path)
        self._conn.execute(_CREATE_SESSION_TABLE_SQL)
        for idx in _SESSION_INDEXES_SQL:
            self._conn.execute(idx)

    # ------------------------------------------------------------------
    # Write
    # ------------------------------------------------------------------

    def register_session(
        self,
        session_id: str,
        user_id: str,
        ip: str,
        user_agent: str | None,
        device_id: str | None = None,
    ) -> None:
        """Register a new authenticated session.

        Args:
            session_id: Unique session token (e.g. JWT ID or UUID).
            user_id: Username that authenticated.
            ip: Remote IP address of the client.
            user_agent: HTTP User-Agent header value, or ``None``.
            device_id: Optional stable device fingerprint.
        """
        now = datetime.now(IST)
        self._conn.execute(
            """
            INSERT INTO active_sessions
                (session_id, user_id, ip, user_agent, device_id,
                 created_at, last_active, ended_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, NULL)
            """,
            [session_id, user_id, ip, user_agent, device_id, now, now],
        )

    def heartbeat(self, session_id: str) -> None:
        """Update the last_active timestamp for a live session.

        Args:
            session_id: The session to touch.
        """
        now = datetime.now(IST)
        self._conn.execute(
            "UPDATE active_sessions SET last_active = ? WHERE session_id = ? AND ended_at IS NULL",
            [now, session_id],
        )

    def end_session(self, session_id: str) -> None:
        """Mark a session as ended (logout or forced termination).

        Args:
            session_id: The session to terminate.
        """
        now = datetime.now(IST)
        self._conn.execute(
            "UPDATE active_sessions SET ended_at = ? WHERE session_id = ? AND ended_at IS NULL",
            [now, session_id],
        )

    def expire_stale(self, idle_minutes: int = 60) -> int:
        """End all sessions idle longer than *idle_minutes*.

        Args:
            idle_minutes: Sessions not updated within this many minutes are
                considered stale.  Defaults to 60.

        Returns:
            Number of sessions expired.
        """
        cutoff = datetime.now(IST) - timedelta(minutes=idle_minutes)
        result = self._conn.execute(
            "SELECT COUNT(*) FROM active_sessions WHERE ended_at IS NULL AND last_active < ?",
            [cutoff],
        ).fetchone()
        count = int(result[0]) if result else 0
        if count > 0:
            now = datetime.now(IST)
            self._conn.execute(
                "UPDATE active_sessions SET ended_at = ? WHERE ended_at IS NULL AND last_active < ?",
                [now, cutoff],
            )
        return count

    # ------------------------------------------------------------------
    # Read
    # ------------------------------------------------------------------

    def active_sessions(self, user_id: str | None = None) -> list[dict[str, Any]]:
        """Return currently active (non-ended) sessions.

        Args:
            user_id: If given, filter to this user only.

        Returns:
            List of dicts with keys: ``session_id``, ``user_id``, ``ip``,
            ``user_agent``, ``device_id``, ``created_at``, ``last_active``.
            Ordered by ``last_active`` descending.
        """
        params: list[Any] = []
        user_clause = ""
        if user_id is not None:
            user_clause = "AND user_id = ?"
            params.append(user_id)
        sql = f"""
            SELECT session_id, user_id, ip, user_agent, device_id,
                   created_at, last_active
            FROM active_sessions
            WHERE ended_at IS NULL
              {user_clause}
            ORDER BY last_active DESC
        """
        rows = self._conn.execute(sql, params).fetchall()

        def _iso(val: Any) -> str:
            return val.isoformat() if hasattr(val, "isoformat") else str(val)

        return [
            {
                "session_id": r[0],
                "user_id": r[1],
                "ip": r[2],
                "user_agent": r[3],
                "device_id": r[4],
                "created_at": _iso(r[5]),
                "last_active": _iso(r[6]),
            }
            for r in rows
        ]

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    def close(self) -> None:
        """Close the underlying DuckDB connection."""
        self._conn.close()

    def __enter__(self) -> "SessionTracker":
        return self

    def __exit__(self, *args: Any) -> None:
        self.close()
