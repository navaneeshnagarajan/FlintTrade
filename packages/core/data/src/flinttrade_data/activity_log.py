"""Activity log for all state-changing mutations (data-layer §8.1 + observability §6).

Every order, position change, setting update, and admin action is persisted to
the SQLite ``activity.db`` (WAL via :func:`flinttrade_core.db.open_sqlite`) with
timestamp, user, action, IP, and a JSON details blob. Operator-facing forensics
("what did I / my agents do?") — plain operational record, not a regulatory
artefact.

Timestamps are stored as ISO-8601 TEXT (IST offset). The ``.timestamp`` field of
:class:`ActivityEntry` is rehydrated to an aware ``datetime`` so callers keep the
datetime-typed API across the DuckDB→SQLite migration.
"""

from __future__ import annotations

import json
import logging
import secrets
import sqlite3
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Any

from flinttrade_core.db import open_sqlite

logger = logging.getLogger("flinttrade.data.activity_log")

IST = timezone(timedelta(hours=5, minutes=30))


def _monotonic_timestamp(previous: datetime | None) -> datetime:
    """Return *now* that is strictly later than ``previous``.

    Windows clock resolution can make successive ``datetime.now`` calls
    collide, which then makes ``ORDER BY timestamp DESC`` unstable.
    """
    now = datetime.now(IST)
    if previous is not None and now <= previous:
        return previous + timedelta(milliseconds=1)
    return now

# observability §6.2 — canonical action catalogue. Every literal logged across
# packages/ should appear here; gateway.*, mcp.tool.*, audit.*, and the auth
# lifecycle verbs join the legacy order/position/auth set.
KNOWN_ACTIONS: frozenset[str] = frozenset(
    {
        "order.placed", "order.modified", "order.cancelled", "order.rejected",
        "position.opened", "position.closed", "position.adjusted",
        "settings.changed",
        "auth.login", "auth.logout", "auth.failed_login", "auth.pin_failed",
        "auth.totp_failed", "auth.rate_limit_hit",
        "mode.transitioned",
        "strategy.started", "strategy.stopped", "strategy.errored",
        "bracket.created", "bracket.exited",
        "sandbox.session_started", "sandbox.session_reset",
        "killswitch.engaged", "killswitch.released",
        "gateway.credential.connect", "gateway.credential.disconnect",
        "gateway.credential.rotate", "gateway.credential.rotated",
        "gateway.session.refresh", "gateway.session.expire",
        "auth.dek_rotated", "auth.password_changed",
        "auth.totp_regenerated", "auth.backup_codes_regenerated",
        "audit.frozen", "audit.unfrozen", "audit.chain_break", "audit.chain_restored",
        "mcp.tool.call", "mcp.tool.result", "mcp.tool.error",
    }
)

_CREATE_TABLE_SQL = """
CREATE TABLE IF NOT EXISTS activity_log (
    log_id      TEXT PRIMARY KEY,
    timestamp   TEXT NOT NULL,
    action      TEXT NOT NULL,
    user        TEXT NOT NULL,
    ip          TEXT,
    details     TEXT NOT NULL,
    source      TEXT
)
"""

_INDEX_SQL = [
    "CREATE INDEX IF NOT EXISTS idx_activity_action ON activity_log(action)",
    "CREATE INDEX IF NOT EXISTS idx_activity_user   ON activity_log(user)",
    "CREATE INDEX IF NOT EXISTS idx_activity_ts     ON activity_log(timestamp)",
    "CREATE INDEX IF NOT EXISTS idx_activity_source ON activity_log(source)",
]

# Migration: add source column to existing databases that lack it.
_MIGRATE_ADD_SOURCE = "ALTER TABLE activity_log ADD COLUMN source TEXT"


def _as_iso(value: str | datetime) -> str:
    """Normalise a since-bound to an ISO-8601 string for TEXT comparison."""
    return value if isinstance(value, str) else value.isoformat()


@dataclass
class ActivityEntry:
    """A single record from the activity log.

    Attributes:
        log_id: Unique identifier for this log entry (16-char hex token).
        timestamp: Timezone-aware datetime of the event.
        action: Dot-namespaced action string (e.g. ``order.placed``).
        user: Username or ``system`` for automated actions.
        ip: Remote IP address if available; ``None`` for internal actions.
        details: Arbitrary JSON-serialisable payload describing the mutation.
        source: Origin of the action (e.g. ``"SCALPER"``, ``"WEBHOOK"``).
    """

    log_id: str
    timestamp: datetime
    action: str
    user: str
    ip: str | None
    details: dict[str, Any] = field(default_factory=dict)
    source: str | None = None


class ActivityLog:
    """Append-only activity log for all mutations.

    Backed by a SQLite database (in-memory by default; provide a file path for
    persistence). Entries are never deleted through this API.

    Args:
        db_path: SQLite path. Defaults to ``:memory:`` (ephemeral).
    """

    def __init__(self, db_path: str = ":memory:") -> None:
        self._conn = open_sqlite(db_path, durability="normal")
        self._last_timestamp: datetime | None = None
        self._conn.execute(_CREATE_TABLE_SQL)
        # Migrate existing databases that lack the source column.
        try:
            self._conn.execute(_MIGRATE_ADD_SOURCE)
        except sqlite3.OperationalError:
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

        Unlisted actions are accepted — :data:`KNOWN_ACTIONS` is the reference
        catalogue, not an enforcement gate.
        """
        log_id = secrets.token_hex(8)
        stamped = _monotonic_timestamp(self._last_timestamp)
        self._last_timestamp = stamped
        timestamp = stamped.isoformat()
        details_json = json.dumps(details, default=str, ensure_ascii=False)

        self._conn.execute(
            "INSERT INTO activity_log "
            "(log_id, timestamp, action, user, ip, details, source) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
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
        """Query the activity log with optional filters (most recent first)."""
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
            params.append(_as_iso(since))
        if source is not None:
            clauses.append("source = ?")
            params.append(source)

        where = ("WHERE " + " AND ".join(clauses)) if clauses else ""
        params.append(int(limit))
        sql = f"""
            SELECT log_id, timestamp, action, user, ip, details, source
            FROM activity_log
            {where}
            ORDER BY timestamp DESC, rowid DESC
            LIMIT ?
        """
        rows = self._conn.execute(sql, params).fetchall()
        result: list[ActivityEntry] = []
        for row in rows:
            ts = row[1]
            ts_dt = datetime.fromisoformat(ts) if isinstance(ts, str) else ts
            result.append(
                ActivityEntry(
                    log_id=row[0],
                    timestamp=ts_dt,
                    action=row[2],
                    user=row[3],
                    ip=row[4],
                    details=json.loads(row[5]),
                    source=row[6],
                )
            )
        return result

    def count_actions(self, action: str, since: str | datetime | None = None) -> int:
        """Count occurrences of an action, optionally after a timestamp."""
        if since is not None:
            row = self._conn.execute(
                "SELECT COUNT(*) FROM activity_log WHERE action = ? AND timestamp >= ?",
                [action, _as_iso(since)],
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
        """Close the underlying SQLite connection."""
        self._conn.close()

    def __enter__(self) -> ActivityLog:
        return self

    def __exit__(self, *args: Any) -> None:
        self.close()


# ---------------------------------------------------------------------------
# LoginActivity — per-login event tracking
# ---------------------------------------------------------------------------

_CREATE_LOGIN_TABLE_SQL = """
CREATE TABLE IF NOT EXISTS login_activity (
    event_id    TEXT PRIMARY KEY,
    timestamp   TEXT NOT NULL,
    user_id     TEXT NOT NULL,
    ip          TEXT NOT NULL,
    user_agent  TEXT,
    success     INTEGER NOT NULL,
    failure_reason TEXT
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

    Backed by a SQLite ``login_activity`` table. Powers the security dashboard
    and suspicious-login alerts.

    Args:
        db_path: SQLite path. Defaults to ``:memory:`` (ephemeral).
    """

    def __init__(self, db_path: str = ":memory:") -> None:
        self._conn = open_sqlite(db_path, durability="normal")
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
        """Record a login attempt; return the generated ``event_id``."""
        event_id = secrets.token_hex(8)
        timestamp = datetime.now(IST).isoformat()
        self._conn.execute(
            "INSERT INTO login_activity "
            "(event_id, timestamp, user_id, ip, user_agent, success, failure_reason) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            [event_id, timestamp, user_id, ip, user_agent, int(bool(success)), failure_reason],
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
        """Return recent login events, newest first."""
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
                "timestamp": r[1],
                "user_id": r[2],
                "ip": r[3],
                "user_agent": r[4],
                "success": bool(r[5]),
                "failure_reason": r[6],
            }
            for r in rows
        ]

    def suspicious_logins(self, window_hours: int = 24) -> list[dict[str, Any]]:
        """Return IPs with more than 3 failed login attempts within *window_hours*."""
        since = (datetime.now(IST) - timedelta(hours=window_hours)).isoformat()
        sql = """
            SELECT ip,
                   COUNT(*)                                     AS failed_count,
                   MAX(timestamp)                               AS last_attempt,
                   COUNT(DISTINCT user_id)                      AS affected_users
            FROM login_activity
            WHERE success = 0
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
                "last_attempt": r[2],
                "affected_users": int(r[3]),
            }
            for r in rows
        ]

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    def close(self) -> None:
        """Close the underlying SQLite connection."""
        self._conn.close()

    def __enter__(self) -> LoginActivity:
        return self

    def __exit__(self, *args: Any) -> None:
        self.close()


# ---------------------------------------------------------------------------
# SessionTracker — active authenticated session management
# ---------------------------------------------------------------------------

_CREATE_SESSION_TABLE_SQL = """
CREATE TABLE IF NOT EXISTS active_sessions (
    session_id  TEXT PRIMARY KEY,
    user_id     TEXT NOT NULL,
    ip          TEXT NOT NULL,
    user_agent  TEXT,
    device_id   TEXT,
    created_at  TEXT NOT NULL,
    last_active TEXT NOT NULL,
    ended_at    TEXT
)
"""

_SESSION_INDEXES_SQL = [
    "CREATE INDEX IF NOT EXISTS idx_sess_user    ON active_sessions(user_id)",
    "CREATE INDEX IF NOT EXISTS idx_sess_active  ON active_sessions(last_active)",
    "CREATE INDEX IF NOT EXISTS idx_sess_ended   ON active_sessions(ended_at)",
]


class SessionTracker:
    """Track active authenticated sessions with heartbeat support.

    Each session is a row in the SQLite ``active_sessions`` table. A session is
    active while ``ended_at`` is ``NULL``.

    Args:
        db_path: SQLite path. Defaults to ``:memory:`` (ephemeral).
    """

    def __init__(self, db_path: str = ":memory:") -> None:
        self._conn = open_sqlite(db_path, durability="normal")
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
        """Register a new authenticated session."""
        now = datetime.now(IST).isoformat()
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
        """Update the last_active timestamp for a live session."""
        now = datetime.now(IST).isoformat()
        self._conn.execute(
            "UPDATE active_sessions SET last_active = ? WHERE session_id = ? AND ended_at IS NULL",
            [now, session_id],
        )

    def end_session(self, session_id: str) -> None:
        """Mark a session as ended (logout or forced termination)."""
        now = datetime.now(IST).isoformat()
        self._conn.execute(
            "UPDATE active_sessions SET ended_at = ? WHERE session_id = ? AND ended_at IS NULL",
            [now, session_id],
        )

    def expire_stale(self, idle_minutes: int = 60) -> int:
        """End all sessions idle longer than *idle_minutes*; return the count."""
        cutoff = (datetime.now(IST) - timedelta(minutes=idle_minutes)).isoformat()
        result = self._conn.execute(
            "SELECT COUNT(*) FROM active_sessions WHERE ended_at IS NULL AND last_active < ?",
            [cutoff],
        ).fetchone()
        count = int(result[0]) if result else 0
        if count > 0:
            now = datetime.now(IST).isoformat()
            self._conn.execute(
                "UPDATE active_sessions SET ended_at = ? WHERE ended_at IS NULL AND last_active < ?",
                [now, cutoff],
            )
        return count

    # ------------------------------------------------------------------
    # Read
    # ------------------------------------------------------------------

    def active_sessions(self, user_id: str | None = None) -> list[dict[str, Any]]:
        """Return currently active (non-ended) sessions, newest first."""
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
        return [
            {
                "session_id": r[0],
                "user_id": r[1],
                "ip": r[2],
                "user_agent": r[3],
                "device_id": r[4],
                "created_at": r[5],
                "last_active": r[6],
            }
            for r in rows
        ]

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    def close(self) -> None:
        """Close the underlying SQLite connection."""
        self._conn.close()

    def __enter__(self) -> SessionTracker:
        return self

    def __exit__(self, *args: Any) -> None:
        self.close()
