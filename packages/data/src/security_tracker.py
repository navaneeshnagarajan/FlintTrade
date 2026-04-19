"""Security event tracking — IP bans, failed API keys, suspicious activity.

Persists all security events in DuckDB tables so that the admin dashboard
can display historical data that survives server restarts.  The in-memory
:class:`~packages.core.src.security.SecurityMonitor` handles real-time
enforcement; this module handles durable storage and analytics.
"""

from __future__ import annotations

import logging
import secrets
from datetime import datetime, timedelta, timezone
from typing import Any

logger = logging.getLogger("flinttrade.data.security_tracker")

IST = timezone(timedelta(hours=5, minutes=30))

# ---------------------------------------------------------------------------
# DDL
# ---------------------------------------------------------------------------

_CREATE_404_TABLE = """
CREATE TABLE IF NOT EXISTS security_404s (
    event_id    VARCHAR PRIMARY KEY,
    timestamp   TIMESTAMP NOT NULL,
    ip          VARCHAR NOT NULL,
    path        VARCHAR NOT NULL
)
"""

_CREATE_APIKEY_TABLE = """
CREATE TABLE IF NOT EXISTS security_invalid_api_keys (
    event_id    VARCHAR PRIMARY KEY,
    timestamp   TIMESTAMP NOT NULL,
    ip          VARCHAR NOT NULL,
    key_prefix  VARCHAR NOT NULL
)
"""

_CREATE_BANS_TABLE = """
CREATE TABLE IF NOT EXISTS security_ip_bans (
    ban_id      VARCHAR PRIMARY KEY,
    ip          VARCHAR NOT NULL,
    reason      VARCHAR NOT NULL,
    banned_at   TIMESTAMP NOT NULL,
    expires_at  TIMESTAMP,
    lifted_at   TIMESTAMP
)
"""

_INDEXES = [
    "CREATE INDEX IF NOT EXISTS idx_404_ip     ON security_404s(ip)",
    "CREATE INDEX IF NOT EXISTS idx_404_ts     ON security_404s(timestamp)",
    "CREATE INDEX IF NOT EXISTS idx_apikey_ip  ON security_invalid_api_keys(ip)",
    "CREATE INDEX IF NOT EXISTS idx_apikey_ts  ON security_invalid_api_keys(timestamp)",
    "CREATE INDEX IF NOT EXISTS idx_ban_ip     ON security_ip_bans(ip)",
    "CREATE INDEX IF NOT EXISTS idx_ban_ts     ON security_ip_bans(banned_at)",
]


class SecurityTracker:
    """Persistent security event log backed by DuckDB.

    Tracks 404 floods, invalid API key attempts, and IP bans.  All writes
    are immediately committed to the database file so that data survives
    restarts.

    Args:
        db_path: DuckDB path.  Defaults to ``:memory:`` (ephemeral).
            Pass ``str(Path.home() / ".flinttrade" / "security.db")``
            for persistence.

    Example::

        st = SecurityTracker("~/.flinttrade/security.db")
        st.track_404("1.2.3.4", "/admin")
        st.track_invalid_api_key("1.2.3.4", "sk-abc")
        st.ban_ip("1.2.3.4", "too many 404s", duration_hours=24)
        print(st.is_banned("1.2.3.4"))  # True
        st.unban_ip("1.2.3.4")
        print(st.is_banned("1.2.3.4"))  # False
    """

    def __init__(self, db_path: str = ":memory:") -> None:
        import duckdb  # lazy import — avoids import penalty when unused

        self._conn = duckdb.connect(db_path)
        self._conn.execute(_CREATE_404_TABLE)
        self._conn.execute(_CREATE_APIKEY_TABLE)
        self._conn.execute(_CREATE_BANS_TABLE)
        for idx in _INDEXES:
            self._conn.execute(idx)

    # ------------------------------------------------------------------
    # 404 tracking
    # ------------------------------------------------------------------

    def track_404(self, ip: str, path: str) -> int:
        """Record a 404 hit for *ip* and return the running total.

        Args:
            ip: Client IP address.
            path: The requested path that returned 404.

        Returns:
            Total number of 404 events recorded for *ip* (all time).
        """
        event_id = secrets.token_hex(8)
        now = datetime.now(IST)
        self._conn.execute(
            "INSERT INTO security_404s VALUES (?, ?, ?, ?)",
            [event_id, now, ip, path],
        )
        row = self._conn.execute(
            "SELECT COUNT(*) FROM security_404s WHERE ip = ?", [ip]
        ).fetchone()
        return int(row[0]) if row else 1

    # ------------------------------------------------------------------
    # Invalid API key tracking
    # ------------------------------------------------------------------

    def track_invalid_api_key(self, ip: str, key_prefix: str) -> None:
        """Record an invalid API key attempt from *ip*.

        Args:
            ip: Client IP address.
            key_prefix: First 8 characters of the key that was rejected
                (never log the full key).
        """
        event_id = secrets.token_hex(8)
        now = datetime.now(IST)
        self._conn.execute(
            "INSERT INTO security_invalid_api_keys VALUES (?, ?, ?, ?)",
            [event_id, now, ip, key_prefix[:8]],
        )

    # ------------------------------------------------------------------
    # IP bans
    # ------------------------------------------------------------------

    def ban_ip(
        self,
        ip: str,
        reason: str,
        duration_hours: int = 24,
    ) -> str:
        """Persistently ban an IP address.

        If the IP already has an active ban this call adds a second ban
        record; the IP will remain banned until ALL active bans expire or
        are lifted.

        Args:
            ip: The IP address to ban.
            reason: Human-readable justification for the ban.
            duration_hours: How many hours the ban lasts.  Pass ``0``
                for a permanent ban (``expires_at = NULL``).

        Returns:
            The ``ban_id`` of the newly created ban record.
        """
        ban_id = secrets.token_hex(8)
        now = datetime.now(IST)
        expires_at = (now + timedelta(hours=duration_hours)) if duration_hours > 0 else None
        self._conn.execute(
            "INSERT INTO security_ip_bans VALUES (?, ?, ?, ?, ?, NULL)",
            [ban_id, ip, reason, now, expires_at],
        )
        logger.warning("Banned IP %s — reason: %s — duration: %sh", ip, reason, duration_hours)
        return ban_id

    def unban_ip(self, ip: str) -> bool:
        """Lift all active bans on *ip* by setting ``lifted_at``.

        Args:
            ip: The IP address to unban.

        Returns:
            ``True`` if at least one active ban was lifted, ``False`` if the
            IP had no active bans.
        """
        # DuckDB TIMESTAMP columns return naive datetimes; use naive comparison.
        now_naive = datetime.now(timezone.utc).replace(tzinfo=None)
        # Count active bans first
        row = self._conn.execute(
            """
            SELECT COUNT(*) FROM security_ip_bans
            WHERE ip = ? AND lifted_at IS NULL
              AND (expires_at IS NULL OR expires_at > ?)
            """,
            [ip, now_naive],
        ).fetchone()
        active_count = int(row[0]) if row else 0
        if active_count == 0:
            return False
        self._conn.execute(
            """
            UPDATE security_ip_bans
            SET lifted_at = ?
            WHERE ip = ? AND lifted_at IS NULL
            """,
            [now_naive, ip],
        )
        logger.info("Unbanned IP %s — lifted %d active ban(s)", ip, active_count)
        return True

    def is_banned(self, ip: str) -> bool:
        """Check whether *ip* currently has any active, non-expired ban.

        Args:
            ip: The IP address to check.

        Returns:
            ``True`` if the IP has an active ban, ``False`` otherwise.
        """
        # DuckDB TIMESTAMP columns return naive datetimes; use naive comparison.
        now_naive = datetime.now(timezone.utc).replace(tzinfo=None)
        row = self._conn.execute(
            """
            SELECT COUNT(*) FROM security_ip_bans
            WHERE ip = ? AND lifted_at IS NULL
              AND (expires_at IS NULL OR expires_at > ?)
            """,
            [ip, now_naive],
        ).fetchone()
        return bool(row and int(row[0]) > 0)

    # ------------------------------------------------------------------
    # Read / query
    # ------------------------------------------------------------------

    def recent_bans(self, limit: int = 50) -> list[dict[str, Any]]:
        """Return the most recently created ban records.

        Args:
            limit: Maximum number of records to return.  Defaults to 50.

        Returns:
            List of dicts with keys: ``ban_id``, ``ip``, ``reason``,
            ``banned_at``, ``expires_at``, ``lifted_at``, ``is_active``.
            Ordered by ``banned_at`` descending.
        """
        now = datetime.now(IST)
        # Use naive UTC equivalent for comparison — DuckDB returns naive datetimes
        # from TIMESTAMP columns; strip tzinfo so the comparison is apples-to-apples.
        now_naive = now.replace(tzinfo=None)
        rows = self._conn.execute(
            """
            SELECT ban_id, ip, reason, banned_at, expires_at, lifted_at
            FROM security_ip_bans
            ORDER BY banned_at DESC
            LIMIT ?
            """,
            [int(limit)],
        ).fetchall()

        def _iso(val: Any) -> str | None:
            if val is None:
                return None
            return val.isoformat() if hasattr(val, "isoformat") else str(val)

        result = []
        for r in rows:
            expires_at = r[4]
            lifted_at = r[5]
            # DuckDB returns naive datetimes — compare without timezone info.
            if expires_at is not None and hasattr(expires_at, "tzinfo") and expires_at.tzinfo is None:
                is_not_expired = expires_at > now_naive
            else:
                is_not_expired = expires_at is None or expires_at > now
            is_active = lifted_at is None and is_not_expired
            result.append({
                "ban_id": r[0],
                "ip": r[1],
                "reason": r[2],
                "banned_at": _iso(r[3]),
                "expires_at": _iso(expires_at),
                "lifted_at": _iso(lifted_at),
                "is_active": is_active,
            })
        return result

    def suspicious_ips(self, threshold: int = 10) -> list[dict[str, Any]]:
        """Return IPs with more than *threshold* total failed requests.

        Combines 404 counts and invalid API key counts per IP to identify
        the most likely scanners or attackers.

        Args:
            threshold: Minimum total failed request count to be included.
                Defaults to 10.

        Returns:
            List of dicts with keys: ``ip``, ``not_found_count``,
            ``invalid_key_count``, ``total_failed``.  Ordered by
            ``total_failed`` descending.
        """
        # Wrap in a subquery so the WHERE clause can reference the computed alias.
        sql = """
            SELECT ip, not_found_count, invalid_key_count, total_failed
            FROM (
                WITH counts_404 AS (
                    SELECT ip, COUNT(*) AS not_found_count
                    FROM security_404s
                    GROUP BY ip
                ),
                counts_key AS (
                    SELECT ip, COUNT(*) AS invalid_key_count
                    FROM security_invalid_api_keys
                    GROUP BY ip
                )
                SELECT
                    COALESCE(c4.ip, ck.ip)                                              AS ip,
                    COALESCE(c4.not_found_count, 0)                                     AS not_found_count,
                    COALESCE(ck.invalid_key_count, 0)                                   AS invalid_key_count,
                    COALESCE(c4.not_found_count, 0) + COALESCE(ck.invalid_key_count, 0) AS total_failed
                FROM counts_404 c4
                FULL OUTER JOIN counts_key ck ON c4.ip = ck.ip
            ) combined
            WHERE total_failed > ?
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
        """Close the underlying DuckDB connection."""
        self._conn.close()

    def __enter__(self) -> "SecurityTracker":
        return self

    def __exit__(self, *args: Any) -> None:
        self.close()
