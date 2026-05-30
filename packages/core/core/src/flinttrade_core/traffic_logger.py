"""Persistent HTTP traffic logger backed by DuckDB.

Every HTTP request flowing through the FlintTrade Flask application is
captured as a structured row: timestamp, IP address, method, path, HTTP
status code, duration in milliseconds, user-agent, request size, and
response size.

The logger is integrated via Flask ``@before_request`` / ``@after_request``
hooks inside ``create_flask_app()``.

Admin REST routes are registered at:

- ``GET /v1/admin/traffic``           — paginated request list
- ``GET /v1/admin/traffic/stats``     — summary statistics
- ``GET /v1/admin/traffic/export``    — CSV download

Example::

    from flinttrade_core.traffic_logger import TrafficLogger

    log = TrafficLogger(":memory:")
    log.log("127.0.0.1", "GET", "/v1/health", 200, 4.2)
    stats = log.stats()
    assert stats["total_requests"] == 1
"""

from __future__ import annotations

import csv
import io
import logging
import secrets
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

logger = logging.getLogger("flinttrade.core.traffic_logger")

# IST as a fixed-offset timezone — no pytz dependency required.
IST = timezone(timedelta(hours=5, minutes=30))

# Paths that should never be logged (avoids feedback loops and noise).
_SKIP_PREFIXES: tuple[str, ...] = (
    "/static/",
    "/favicon.ico",
    "/v1/admin/traffic",
    "/api/v1/traffic",
)

_CREATE_TABLE_SQL = """
CREATE TABLE IF NOT EXISTS traffic_log (
    entry_id       VARCHAR PRIMARY KEY,
    timestamp      TIMESTAMP NOT NULL,
    ip             VARCHAR   NOT NULL,
    method         VARCHAR   NOT NULL,
    path           VARCHAR   NOT NULL,
    status_code    INTEGER   NOT NULL,
    duration_ms    DOUBLE    NOT NULL,
    user_agent     VARCHAR,
    request_size   INTEGER,
    response_size  INTEGER,
    user_id        VARCHAR
)
"""

_INDEX_SQL: list[str] = [
    "CREATE INDEX IF NOT EXISTS idx_tlog_ts     ON traffic_log(timestamp)",
    "CREATE INDEX IF NOT EXISTS idx_tlog_path   ON traffic_log(path)",
    "CREATE INDEX IF NOT EXISTS idx_tlog_status ON traffic_log(status_code)",
    "CREATE INDEX IF NOT EXISTS idx_tlog_ip     ON traffic_log(ip)",
]


class TrafficLogger:
    """Persistent structured HTTP traffic log backed by DuckDB.

    Thread-safe for concurrent Flask workers via a single DuckDB
    file-backed connection (DuckDB handles multi-writer access within
    the same process).

    The database file is created at *db_path* on first instantiation.
    The parent directory is created automatically if it does not exist.

    Args:
        db_path: Path to the DuckDB file.  Defaults to
            ``~/.flinttrade/traffic_log.duckdb``.  Pass ``":memory:"``
            for ephemeral in-process storage (useful in tests).

    Example::

        log = TrafficLogger(":memory:")
        log.log("10.0.0.1", "POST", "/v1/orders/place", 200, 18.5)
        assert log.stats()["total_requests"] == 1
    """

    def __init__(self, db_path: Path | str | None = None) -> None:
        import duckdb  # lazy — avoids penalising startup if unused

        if db_path is None:
            db_path = Path.home() / ".flinttrade" / "traffic_log.duckdb"

        if isinstance(db_path, str) and db_path != ":memory:":
            db_path = Path(db_path)

        if isinstance(db_path, Path):
            db_path.parent.mkdir(parents=True, exist_ok=True)
            self._db_path: str = str(db_path)
        else:
            self._db_path = str(db_path)

        self._conn = duckdb.connect(self._db_path)
        self._init_schema()

    # ------------------------------------------------------------------
    # Schema
    # ------------------------------------------------------------------

    def _init_schema(self) -> None:
        """Create table and indexes if they do not already exist."""
        self._conn.execute(_CREATE_TABLE_SQL)
        for idx_sql in _INDEX_SQL:
            self._conn.execute(idx_sql)

    # ------------------------------------------------------------------
    # Write
    # ------------------------------------------------------------------

    def log(
        self,
        ip: str,
        method: str,
        path: str,
        status_code: int,
        duration_ms: float,
        user_agent: str | None = None,
        request_size: int | None = None,
        response_size: int | None = None,
        user_id: str | None = None,
    ) -> str:
        """Persist a single HTTP request record.

        Args:
            ip: Client IP address.
            method: HTTP method (e.g. ``"GET"``, ``"POST"``).
            path: Request path (e.g. ``"/v1/orders/place"``).
            status_code: HTTP response status code.
            duration_ms: Request duration in milliseconds.
            user_agent: ``User-Agent`` header value, if available.
            request_size: ``Content-Length`` of the request body, if known.
            response_size: ``Content-Length`` of the response body, if known.
            user_id: Authenticated user identifier, or ``None``.

        Returns:
            The ``entry_id`` assigned to this record (16-char hex string).
        """
        entry_id = secrets.token_hex(8)
        timestamp = datetime.now(IST)

        self._conn.execute(
            """
            INSERT INTO traffic_log
                (entry_id, timestamp, ip, method, path, status_code,
                 duration_ms, user_agent, request_size, response_size, user_id)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            [
                entry_id,
                timestamp,
                ip,
                method,
                path,
                status_code,
                round(duration_ms, 3),
                user_agent,
                request_size,
                response_size,
                user_id,
            ],
        )
        logger.debug(
            "Traffic: %s %s %d %.1fms entry_id=%s",
            method, path, status_code, duration_ms, entry_id,
        )
        return entry_id

    # ------------------------------------------------------------------
    # Read
    # ------------------------------------------------------------------

    def recent(
        self,
        limit: int = 100,
        offset: int = 0,
        status_filter: int | None = None,
    ) -> list[dict[str, Any]]:
        """Return recent traffic log entries as plain dicts.

        Args:
            limit: Maximum number of rows (default 100, clamped to 1000).
            offset: Row offset for pagination.
            status_filter: When provided, only rows with this exact
                ``status_code`` are returned.

        Returns:
            List of dicts ordered by ``timestamp`` descending.
        """
        limit = max(1, min(int(limit), 1000))
        offset = max(0, int(offset))

        if status_filter is not None:
            rows = self._conn.execute(
                """
                SELECT entry_id, timestamp, ip, method, path, status_code,
                       duration_ms, user_agent, request_size, response_size, user_id
                FROM traffic_log
                WHERE status_code = ?
                ORDER BY timestamp DESC
                LIMIT ? OFFSET ?
                """,
                [status_filter, limit, offset],
            ).fetchall()
        else:
            rows = self._conn.execute(
                """
                SELECT entry_id, timestamp, ip, method, path, status_code,
                       duration_ms, user_agent, request_size, response_size, user_id
                FROM traffic_log
                ORDER BY timestamp DESC
                LIMIT ? OFFSET ?
                """,
                [limit, offset],
            ).fetchall()

        result: list[dict[str, Any]] = []
        for row in rows:
            ts = row[1]
            ts_str = ts.isoformat() if isinstance(ts, datetime) else str(ts)
            result.append(
                {
                    "entry_id": row[0],
                    "timestamp": ts_str,
                    "ip": row[2],
                    "method": row[3],
                    "path": row[4],
                    "status_code": row[5],
                    "duration_ms": row[6],
                    "user_agent": row[7],
                    "request_size": row[8],
                    "response_size": row[9],
                    "user_id": row[10],
                }
            )
        return result

    def stats(self, since: datetime | None = None) -> dict[str, Any]:
        """Return aggregate traffic statistics.

        Computes total request count, error rate (4xx+5xx / total),
        average duration, p95 duration, and top-10 most-requested paths.

        Args:
            since: When provided, only entries at or after this
                timezone-aware datetime are included.

        Returns:
            Dict with keys: ``total_requests``, ``error_rate``,
            ``avg_duration_ms``, ``p95_duration_ms``, ``top_paths``.
        """
        where = "WHERE timestamp >= ?" if since is not None else ""
        params: list[Any] = [since] if since is not None else []

        agg_row = self._conn.execute(
            f"""
            SELECT
                COUNT(*)                                   AS total,
                SUM(CASE WHEN status_code >= 400 THEN 1 ELSE 0 END) AS errors,
                AVG(duration_ms)                           AS avg_ms,
                PERCENTILE_CONT(0.95) WITHIN GROUP (ORDER BY duration_ms) AS p95_ms
            FROM traffic_log {where}
            """,
            params,
        ).fetchone()

        total = int(agg_row[0]) if agg_row and agg_row[0] else 0
        errors = int(agg_row[1]) if agg_row and agg_row[1] else 0
        avg_ms = float(agg_row[2]) if agg_row and agg_row[2] else 0.0
        p95_ms = float(agg_row[3]) if agg_row and agg_row[3] else 0.0

        path_rows = self._conn.execute(
            f"""
            SELECT path, COUNT(*) AS cnt
            FROM traffic_log {where}
            GROUP BY path
            ORDER BY cnt DESC
            LIMIT 10
            """,
            params,
        ).fetchall()

        top_paths = [{"path": r[0], "count": int(r[1])} for r in path_rows]

        return {
            "total_requests": total,
            "error_rate": round(errors / total, 4) if total > 0 else 0.0,
            "avg_duration_ms": round(avg_ms, 2),
            "p95_duration_ms": round(p95_ms, 2),
            "top_paths": top_paths,
        }

    def count(self, since: datetime | None = None) -> int:
        """Count total traffic log entries.

        Args:
            since: Optional lower-bound timestamp (timezone-aware).

        Returns:
            Integer row count.
        """
        if since is not None:
            row = self._conn.execute(
                "SELECT COUNT(*) FROM traffic_log WHERE timestamp >= ?", [since]
            ).fetchone()
        else:
            row = self._conn.execute(
                "SELECT COUNT(*) FROM traffic_log"
            ).fetchone()
        return int(row[0]) if row else 0

    def export_csv(self, since: datetime | None = None) -> str:
        """Export traffic log entries to a CSV string.

        Args:
            since: When provided, only entries at or after this
                timezone-aware datetime are exported.

        Returns:
            CSV-formatted string with a header row.
        """
        where = "WHERE timestamp >= ?" if since is not None else ""
        params: list[Any] = [since] if since is not None else []

        rows = self._conn.execute(
            f"""
            SELECT entry_id, timestamp, ip, method, path, status_code,
                   duration_ms, user_agent, request_size, response_size, user_id
            FROM traffic_log {where}
            ORDER BY timestamp DESC
            """,
            params,
        ).fetchall()

        output = io.StringIO()
        writer = csv.writer(output)
        writer.writerow(
            [
                "entry_id", "timestamp", "ip", "method", "path",
                "status_code", "duration_ms", "user_agent",
                "request_size", "response_size", "user_id",
            ]
        )
        for row in rows:
            ts = row[1]
            ts_str = ts.isoformat() if isinstance(ts, datetime) else str(ts)
            writer.writerow(
                [
                    row[0], ts_str, row[2], row[3], row[4],
                    row[5], row[6], row[7],
                    row[8], row[9], row[10],
                ]
            )
        return output.getvalue()

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    def close(self) -> None:
        """Close the underlying DuckDB connection."""
        self._conn.close()

    def __enter__(self) -> "TrafficLogger":
        return self

    def __exit__(self, *args: Any) -> None:
        self.close()


# ---------------------------------------------------------------------------
# Flask middleware helpers
# ---------------------------------------------------------------------------


def should_skip_path(path: str) -> bool:
    """Return True if *path* should be excluded from traffic logging.

    Args:
        path: Flask request path string.

    Returns:
        True when the path matches a known skip prefix.
    """
    return any(path.startswith(prefix) for prefix in _SKIP_PREFIXES)
