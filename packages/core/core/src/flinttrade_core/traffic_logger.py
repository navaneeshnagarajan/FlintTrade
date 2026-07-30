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
import threading
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

logger = logging.getLogger("flinttrade.core.traffic_logger")

# IST as a fixed-offset timezone — no pytz dependency required.
IST = timezone(timedelta(hours=5, minutes=30))

# Retention defaults — every HTTP request is one row, so an always-on logger
# grows without bound unless pruned. 30 days / 200k rows keeps weeks of
# debugging history while bounding the DuckDB file to a few tens of MB.
# Override per install via workspace.json (see _workspace_retention_overrides)
# or per instance via the constructor.
DEFAULT_RETENTION_DAYS = 30
DEFAULT_MAX_ROWS = 200_000

# Amortised prune cadence: the retention sweep runs once per this many writes
# (plus once at startup), so the steady-state insert path stays a single
# INSERT rather than INSERT + 2 DELETE scans.
_PRUNE_EVERY_WRITES = 512


def _default_db_path() -> Path:
    """Resolve the traffic-log database path under the active workspace.

    No legacy migration is attempted: the traffic log is disposable
    observability data and production never relies on this default
    (``create_flask_app`` and the infra routes both pass an explicit
    workspace-resolved path). Resolved at call time so environment
    overrides set after import — pytest workers, Gunicorn preload+fork —
    are honoured.

    Returns:
        Absolute path of ``traffic_log.duckdb`` inside the workspace directory.
    """
    from flinttrade_core.workspace import workspace_dir

    return workspace_dir() / "traffic_log.duckdb"


def _workspace_retention_overrides() -> dict[str, int]:
    """Read traffic-log retention overrides from ``workspace.json`` (best effort).

    Keys: ``observability.traffic_log.retention_days`` and
    ``observability.traffic_log.max_rows``. ``0`` disables that cap. Any
    failure (missing file, malformed value) falls back to the defaults —
    retention must never stop the backend from booting.

    Returns:
        Dict with any of ``retention_days`` / ``max_rows`` that were set.
    """
    try:
        from .workspace import Workspace  # noqa: PLC0415 — lazy: avoid import cost when unused

        ws = Workspace()
        overrides: dict[str, int] = {}
        days = ws.get("observability.traffic_log.retention_days")
        rows = ws.get("observability.traffic_log.max_rows")
        if days is not None:
            overrides["retention_days"] = max(0, int(days))
        if rows is not None:
            overrides["max_rows"] = max(0, int(rows))
        return overrides
    except Exception as exc:  # noqa: BLE001 - config read must stay non-fatal
        logger.debug("Traffic-log retention overrides unavailable: %s", exc)
        return {}

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

    Thread safety: all eight Flask worker threads share this ONE instance and
    its ONE DuckDB connection, and a single DuckDB connection is NOT safe for
    concurrent statement execution — so every connection use is serialised
    behind an internal ``threading.Lock``.

    Retention: the table is capped by age (``retention_days``) and row count
    (``max_rows``), swept once at startup and then amortised every
    ``_PRUNE_EVERY_WRITES`` inserts. Either cap can be disabled with ``0``.
    Defaults are overridable via ``workspace.json``
    (``observability.traffic_log.retention_days`` / ``.max_rows``) for
    file-backed instances; ``":memory:"`` instances skip the workspace read so
    unit tests never touch the operator's real workspace.

    The database file is created at *db_path* on first instantiation.
    The parent directory is created automatically if it does not exist.

    Args:
        db_path: Path to the DuckDB file.  Defaults to
            ``traffic_log.duckdb`` inside the active workspace directory
            (resolved at construction via
            :func:`flinttrade_core.workspace.workspace_dir`).  Pass
            ``":memory:"`` for ephemeral in-process storage (useful in
            tests).
        retention_days: Delete rows older than this many days (``0`` keeps
            forever). ``None`` uses the workspace override or the default.
        max_rows: Keep at most this many newest rows (``0`` keeps all).
            ``None`` uses the workspace override or the default.

    Example::

        log = TrafficLogger(":memory:")
        log.log("10.0.0.1", "POST", "/v1/orders/place", 200, 18.5)
        assert log.stats()["total_requests"] == 1
    """

    def __init__(
        self,
        db_path: Path | str | None = None,
        *,
        retention_days: int | None = None,
        max_rows: int | None = None,
    ) -> None:
        import duckdb  # lazy — avoids penalising startup if unused

        if db_path is None:
            db_path = _default_db_path()

        if isinstance(db_path, str) and db_path != ":memory:":
            db_path = Path(db_path)

        if isinstance(db_path, Path):
            db_path.parent.mkdir(parents=True, exist_ok=True)
            self._db_path: str = str(db_path)
        else:
            self._db_path = str(db_path)

        overrides = _workspace_retention_overrides() if self._db_path != ":memory:" else {}
        self._retention_days = retention_days if retention_days is not None else overrides.get(
            "retention_days", DEFAULT_RETENTION_DAYS
        )
        self._max_rows = max_rows if max_rows is not None else overrides.get("max_rows", DEFAULT_MAX_ROWS)

        # DuckDB connections are not thread-safe for concurrent statement
        # execution; Flask serves from a thread pool, so serialise ALL use.
        self._lock = threading.Lock()
        self._writes_since_prune = 0

        self._conn = duckdb.connect(self._db_path)
        with self._lock:
            self._init_schema()
            # Startup sweep: an existing file may have grown unbounded before
            # retention existed (or while the backend was down).
            self._prune_locked()

    # ------------------------------------------------------------------
    # Schema
    # ------------------------------------------------------------------

    def _init_schema(self) -> None:
        """Create table and indexes if they do not already exist. Caller holds the lock."""
        self._conn.execute(_CREATE_TABLE_SQL)
        for idx_sql in _INDEX_SQL:
            self._conn.execute(idx_sql)

    # ------------------------------------------------------------------
    # Retention
    # ------------------------------------------------------------------

    def prune(self) -> int:
        """Apply the retention policy (age cap, then row cap).

        Returns:
            Number of rows deleted.
        """
        with self._lock:
            return self._prune_locked()

    def _prune_locked(self) -> int:
        """Delete rows beyond ``retention_days`` / ``max_rows``. Caller holds the lock."""
        deleted = 0
        try:
            if self._retention_days > 0:
                cutoff = datetime.now(IST) - timedelta(days=self._retention_days)
                row = self._conn.execute(
                    "DELETE FROM traffic_log WHERE timestamp < ?", [cutoff]
                ).fetchone()
                deleted += int(row[0]) if row else 0
            if self._max_rows > 0:
                count_row = self._conn.execute("SELECT COUNT(*) FROM traffic_log").fetchone()
                overflow = (int(count_row[0]) if count_row else 0) - self._max_rows
                if overflow > 0:
                    row = self._conn.execute(
                        """
                        DELETE FROM traffic_log WHERE entry_id IN (
                            SELECT entry_id FROM traffic_log ORDER BY timestamp ASC LIMIT ?
                        )
                        """,
                        [overflow],
                    ).fetchone()
                    deleted += int(row[0]) if row else 0
        except Exception as exc:  # noqa: BLE001 - retention must never break request logging
            logger.warning("Traffic-log prune failed: %s", exc)
        if deleted:
            logger.debug("Traffic-log retention pruned %d rows", deleted)
        return deleted

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

        with self._lock:
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
            self._writes_since_prune += 1
            if self._writes_since_prune >= _PRUNE_EVERY_WRITES:
                self._writes_since_prune = 0
                self._prune_locked()
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

        with self._lock:
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

        with self._lock:
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

        total = int(agg_row[0]) if agg_row and agg_row[0] else 0
        errors = int(agg_row[1]) if agg_row and agg_row[1] else 0
        avg_ms = float(agg_row[2]) if agg_row and agg_row[2] else 0.0
        p95_ms = float(agg_row[3]) if agg_row and agg_row[3] else 0.0

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
        with self._lock:
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

        with self._lock:
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
        with self._lock:
            self._conn.close()

    def __enter__(self) -> TrafficLogger:
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
