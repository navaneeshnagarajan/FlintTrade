"""Security event tracking — refused / rejected / blocked / failed-auth events.

Backing store: ``security.db`` via :func:`flinttrade_core.db.open_sqlite` (SQLite
WAL). The in-memory ``SecurityMonitor`` handles real-time enforcement; this module
is durable storage + analytics for the ``/admin/security`` surface.

Two layers:

  - legacy convenience tables (``security_404s``, ``security_invalid_api_keys``,
    ``security_ip_bans``) powering 404-flood / invalid-key / IP-ban tracking.
  - the observability §10.3 model: a unified ``security_events`` ledger plus
    per-``actor_scope`` ``security_counters`` and per-tool ``mcp_tool_counters``.
    ``actor_scope`` bucketing (Identity H5) stops a noisy IP from masking a
    targeted attack on one account, and vice versa.

All timestamps are unix-epoch ``REAL`` for unambiguous numeric comparison.
"""

from __future__ import annotations

import json
import logging
import secrets
import time
from typing import Any

from flinttrade_core.db import open_sqlite

logger = logging.getLogger("flinttrade.data.security_tracker")

# observability §10.2 — tracked security event taxonomy.
EVENT_TYPES: frozenset[str] = frozenset(
    {
        "WEBHOOK_REJECTED", "WEBHOOK_REPLAY_REJECTED",
        "MCP_TOOL_ERROR",
        "SANDBOX_BLOCKED_IMPORT", "SANDBOX_OS_HARDENING_LIMITED",
        "auth.failed_login", "auth.pin_failed", "auth.totp_failed", "auth.rate_limit_hit",
        "broker_401_or_403", "BROKER_IP_MISMATCH", "BROKER_RATE_LIMIT_HIT",
        "BROKER_READ_ONLY_ENGAGED", "BROKER_SESSION_REFRESH_FAILED",
        "BROKER_WS_DEAD", "BROKER_WS_STALE_INSTRUMENT", "BROKER_SDK_ATTEST_FAIL",
        "INSTRUMENTS_CACHE_REFUSED", "cert_validation_failure",
        "OTP_MAILER_DOWNGRADE_REFUSED",
    }
)

# valid mcp_tool_counters.decision values (§10.3)
MCP_DECISIONS: frozenset[str] = frozenset(
    {"allowed", "denied", "rate_limited", "external_input_refused", "other"}
)

_SCHEMA = """
-- legacy convenience tables (timestamps unix-epoch REAL) --------------------
CREATE TABLE IF NOT EXISTS security_404s (
    event_id    TEXT PRIMARY KEY,
    ts          REAL NOT NULL,
    ip          TEXT NOT NULL,
    path        TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS security_invalid_api_keys (
    event_id    TEXT PRIMARY KEY,
    ts          REAL NOT NULL,
    ip          TEXT NOT NULL,
    key_prefix  TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS security_ip_bans (
    ban_id      TEXT PRIMARY KEY,
    ip          TEXT NOT NULL,
    reason      TEXT NOT NULL,
    banned_at   REAL NOT NULL,
    expires_at  REAL,
    lifted_at   REAL
);
CREATE INDEX IF NOT EXISTS idx_404_ip     ON security_404s(ip);
CREATE INDEX IF NOT EXISTS idx_404_ts     ON security_404s(ts);
CREATE INDEX IF NOT EXISTS idx_apikey_ip  ON security_invalid_api_keys(ip);
CREATE INDEX IF NOT EXISTS idx_apikey_ts  ON security_invalid_api_keys(ts);
CREATE INDEX IF NOT EXISTS idx_ban_ip     ON security_ip_bans(ip);
CREATE INDEX IF NOT EXISTS idx_ban_ts     ON security_ip_bans(banned_at);

-- observability §10.3 model -------------------------------------------------
CREATE TABLE IF NOT EXISTS security_events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    event_type TEXT NOT NULL,
    reason TEXT,
    actor_type TEXT,
    actor_id TEXT,
    ip_hash TEXT,
    ua_hash TEXT,
    fields_json TEXT,
    ts REAL NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_security_events_type_ts ON security_events(event_type, ts);
CREATE INDEX IF NOT EXISTS idx_security_events_actor_ts ON security_events(actor_type, actor_id, ts);

CREATE TABLE IF NOT EXISTS security_counters (
    event_type TEXT NOT NULL,
    actor_scope TEXT NOT NULL,
    count_total INTEGER NOT NULL DEFAULT 0,
    count_last_1h INTEGER NOT NULL DEFAULT 0,
    count_last_24h INTEGER NOT NULL DEFAULT 0,
    last_event_ts REAL,
    PRIMARY KEY (event_type, actor_scope)
);

CREATE TABLE IF NOT EXISTS mcp_tool_counters (
    tool_name TEXT NOT NULL,
    decision TEXT NOT NULL,
    count_total INTEGER NOT NULL DEFAULT 0,
    last_ts REAL,
    PRIMARY KEY (tool_name, decision)
);
"""


def _actor_scopes(actor_id: str | None, ip_hash: str | None) -> list[str]:
    """Resolve the §10.3 actor_scope buckets an event increments (Identity H5)."""
    if actor_id and ip_hash:
        return [f"ip_hash:{ip_hash}", f"actor_id:{actor_id}", f"(actor_id,ip_hash):{actor_id}|{ip_hash}"]
    if actor_id:
        return [f"actor_id:{actor_id}"]
    if ip_hash:
        return [f"ip_hash:{ip_hash}"]
    return ["global"]


class SecurityTracker:
    """Persistent security event log backed by SQLite.

    Args:
        db_path: SQLite path. Defaults to ``:memory:`` (ephemeral).
    """

    def __init__(self, db_path: str = ":memory:") -> None:
        self._conn = open_sqlite(db_path, durability="normal")
        self._conn.executescript(_SCHEMA)

    # ------------------------------------------------------------------
    # 404 tracking
    # ------------------------------------------------------------------

    def track_404(self, ip: str, path: str) -> int:
        """Record a 404 hit for *ip*; return the running all-time total."""
        self._conn.execute(
            "INSERT INTO security_404s (event_id, ts, ip, path) VALUES (?, ?, ?, ?)",
            [secrets.token_hex(8), time.time(), ip, path],
        )
        row = self._conn.execute(
            "SELECT COUNT(*) FROM security_404s WHERE ip = ?", [ip]
        ).fetchone()
        return int(row[0]) if row else 1

    # ------------------------------------------------------------------
    # Invalid API key tracking
    # ------------------------------------------------------------------

    def track_invalid_api_key(self, ip: str, key_prefix: str) -> None:
        """Record an invalid API key attempt (stores the 8-char prefix only)."""
        self._conn.execute(
            "INSERT INTO security_invalid_api_keys (event_id, ts, ip, key_prefix) VALUES (?, ?, ?, ?)",
            [secrets.token_hex(8), time.time(), ip, key_prefix[:8]],
        )

    # ------------------------------------------------------------------
    # IP bans
    # ------------------------------------------------------------------

    def ban_ip(self, ip: str, reason: str, duration_hours: int = 24) -> str:
        """Persistently ban an IP. ``duration_hours=0`` is a permanent ban."""
        ban_id = secrets.token_hex(8)
        now = time.time()
        expires_at = (now + duration_hours * 3600) if duration_hours > 0 else None
        self._conn.execute(
            "INSERT INTO security_ip_bans (ban_id, ip, reason, banned_at, expires_at, lifted_at) "
            "VALUES (?, ?, ?, ?, ?, NULL)",
            [ban_id, ip, reason, now, expires_at],
        )
        logger.warning("Banned IP %s — reason: %s — duration: %sh", ip, reason, duration_hours)
        return ban_id

    def unban_ip(self, ip: str) -> bool:
        """Lift all active bans on *ip*; return whether any were active."""
        now = time.time()
        row = self._conn.execute(
            "SELECT COUNT(*) FROM security_ip_bans "
            "WHERE ip = ? AND lifted_at IS NULL AND (expires_at IS NULL OR expires_at > ?)",
            [ip, now],
        ).fetchone()
        active_count = int(row[0]) if row else 0
        if active_count == 0:
            return False
        self._conn.execute(
            "UPDATE security_ip_bans SET lifted_at = ? WHERE ip = ? AND lifted_at IS NULL",
            [now, ip],
        )
        logger.info("Unbanned IP %s — lifted %d active ban(s)", ip, active_count)
        return True

    def is_banned(self, ip: str) -> bool:
        """Return True if *ip* has any active, non-expired, non-lifted ban."""
        now = time.time()
        row = self._conn.execute(
            "SELECT COUNT(*) FROM security_ip_bans "
            "WHERE ip = ? AND lifted_at IS NULL AND (expires_at IS NULL OR expires_at > ?)",
            [ip, now],
        ).fetchone()
        return bool(row and int(row[0]) > 0)

    # ------------------------------------------------------------------
    # §10.3 unified event ledger + counters
    # ------------------------------------------------------------------

    def record_event(
        self,
        event_type: str,
        *,
        reason: str | None = None,
        actor_type: str | None = None,
        actor_id: str | None = None,
        ip_hash: str | None = None,
        ua_hash: str | None = None,
        fields: dict[str, Any] | None = None,
        ts: float | None = None,
    ) -> None:
        """Append a security event and increment its per-actor_scope counters."""
        ts = time.time() if ts is None else ts
        fields_json = json.dumps(fields, default=str, ensure_ascii=False) if fields else None
        self._conn.execute(
            "INSERT INTO security_events "
            "(event_type, reason, actor_type, actor_id, ip_hash, ua_hash, fields_json, ts) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            [event_type, reason, actor_type, actor_id, ip_hash, ua_hash, fields_json, ts],
        )
        for scope in _actor_scopes(actor_id, ip_hash):
            self._conn.execute(
                "INSERT INTO security_counters "
                "(event_type, actor_scope, count_total, last_event_ts) VALUES (?, ?, 1, ?) "
                "ON CONFLICT (event_type, actor_scope) DO UPDATE SET "
                "count_total = count_total + 1, last_event_ts = excluded.last_event_ts",
                [event_type, scope, ts],
            )

    def mcp_tool_decision(self, tool_name: str, decision: str, ts: float | None = None) -> None:
        """Increment the per-(tool, decision) counter for the mcp pivot table."""
        if decision not in MCP_DECISIONS:
            decision = "other"
        ts = time.time() if ts is None else ts
        self._conn.execute(
            "INSERT INTO mcp_tool_counters (tool_name, decision, count_total, last_ts) "
            "VALUES (?, ?, 1, ?) "
            "ON CONFLICT (tool_name, decision) DO UPDATE SET "
            "count_total = count_total + 1, last_ts = excluded.last_ts",
            [tool_name, decision, ts],
        )

    def count_events_in_window(
        self,
        event_type: str,
        *,
        actor_id: str | None = None,
        ip_hash: str | None = None,
        window_seconds: float = 300.0,
        now: float | None = None,
    ) -> int:
        """Count matching events within the trailing window (§10.4 threshold input)."""
        now = time.time() if now is None else now
        clauses = ["event_type = ?", "ts > ?"]
        params: list[Any] = [event_type, now - window_seconds]
        if actor_id is not None:
            clauses.append("actor_id = ?")
            params.append(actor_id)
        if ip_hash is not None:
            clauses.append("ip_hash = ?")
            params.append(ip_hash)
        row = self._conn.execute(
            f"SELECT COUNT(*) FROM security_events WHERE {' AND '.join(clauses)}", params
        ).fetchone()
        return int(row[0]) if row else 0

    def threshold_crossed(
        self,
        event_type: str,
        *,
        limit: int,
        window_seconds: float,
        actor_id: str | None = None,
        ip_hash: str | None = None,
        now: float | None = None,
    ) -> bool:
        """True if the per-actor_scope event count reached *limit* in the window."""
        return (
            self.count_events_in_window(
                event_type,
                actor_id=actor_id,
                ip_hash=ip_hash,
                window_seconds=window_seconds,
                now=now,
            )
            >= limit
        )

    def recent_events(self, event_type: str | None = None, limit: int = 100) -> list[dict[str, Any]]:
        """Return the most recent security events, newest first."""
        where, params = "", []
        if event_type is not None:
            where = "WHERE event_type = ?"
            params.append(event_type)
        params.append(int(limit))
        rows = self._conn.execute(
            f"SELECT event_type, reason, actor_type, actor_id, ip_hash, ua_hash, fields_json, ts "
            f"FROM security_events {where} ORDER BY ts DESC LIMIT ?",
            params,
        ).fetchall()
        return [
            {
                "event_type": r[0],
                "reason": r[1],
                "actor_type": r[2],
                "actor_id": r[3],
                "ip_hash": r[4],
                "ua_hash": r[5],
                "fields": json.loads(r[6]) if r[6] else None,
                "ts": r[7],
            }
            for r in rows
        ]

    # ------------------------------------------------------------------
    # Read / query
    # ------------------------------------------------------------------

    def recent_bans(self, limit: int = 50) -> list[dict[str, Any]]:
        """Return the most recently created ban records, newest first."""
        now = time.time()
        rows = self._conn.execute(
            "SELECT ban_id, ip, reason, banned_at, expires_at, lifted_at "
            "FROM security_ip_bans ORDER BY banned_at DESC LIMIT ?",
            [int(limit)],
        ).fetchall()
        result = []
        for r in rows:
            expires_at, lifted_at = r[4], r[5]
            is_active = lifted_at is None and (expires_at is None or expires_at > now)
            result.append(
                {
                    "ban_id": r[0],
                    "ip": r[1],
                    "reason": r[2],
                    "banned_at": r[3],
                    "expires_at": expires_at,
                    "lifted_at": lifted_at,
                    "is_active": is_active,
                }
            )
        return result

    def suspicious_ips(self, threshold: int = 10) -> list[dict[str, Any]]:
        """Return IPs whose combined 404 + invalid-key count exceeds *threshold*.

        Uses a portable ``UNION ALL`` aggregation rather than ``FULL OUTER JOIN``
        so the query runs on any SQLite build the deploy targets.
        """
        sql = """
            SELECT ip,
                   SUM(nf) AS not_found_count,
                   SUM(ik) AS invalid_key_count,
                   SUM(nf) + SUM(ik) AS total_failed
            FROM (
                SELECT ip, 1 AS nf, 0 AS ik FROM security_404s
                UNION ALL
                SELECT ip, 0 AS nf, 1 AS ik FROM security_invalid_api_keys
            )
            GROUP BY ip
            HAVING total_failed > ?
            ORDER BY total_failed DESC
        """
        rows = self._conn.execute(sql, [int(threshold)]).fetchall()
        return [
            {
                "ip": r[0],
                "not_found_count": int(r[1]),
                "invalid_key_count": int(r[2]),
                "total_failed": int(r[3]),
            }
            for r in rows
        ]

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    def close(self) -> None:
        """Close the underlying SQLite connection."""
        self._conn.close()

    def __enter__(self) -> "SecurityTracker":
        return self

    def __exit__(self, *args: Any) -> None:
        self.close()
