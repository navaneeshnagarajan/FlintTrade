"""API call analyser — DuckDB-backed request/response audit log.

Every inbound API call can be persisted as a structured row containing
the route, HTTP method, sanitised request body, response status,
sanitised response body, duration, and the authenticated user.  This
is distinct from the error log (which records only errors) — the
analyser captures ALL calls for debugging, replay, and latency analysis.

Activation is opt-in: the analyser is only active when the environment
variable ``ENABLE_ANALYZER=true`` is set (checked at Flask startup).

Sensitive fields are redacted from both request and response bodies
using the same ``_SENSITIVE_KEYS`` set as the error log.

Admin REST routes:

- ``GET /v1/admin/analyzer/calls``        — paginated call list
- ``GET /v1/admin/analyzer/<id>/replay``  — full request+response for replay

Example::

    from flinttrade_core.api_analyzer import APIAnalyzer

    az = APIAnalyzer(":memory:")
    az.log_call("/v1/orders/place", "POST", {"symbol": "NIFTY"}, 200, {"status": "ok"}, 18.3)
    recent = az.recent()
    assert len(recent) == 1
    replayed = az.replay(recent[0]["call_id"])
    assert replayed["route"] == "/v1/orders/place"
"""

from __future__ import annotations

import json
import logging
import secrets
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

logger = logging.getLogger("flinttrade.core.api_analyzer")

# IST as a fixed-offset timezone.
IST = timezone(timedelta(hours=5, minutes=30))

# Keys whose values must never be persisted (same set as error_log).
_SENSITIVE_KEYS: frozenset[str] = frozenset(
    {"password", "token", "api_key", "apikey", "secret", "totp", "otp", "pin"}
)

_CREATE_TABLE_SQL = """
CREATE TABLE IF NOT EXISTS api_calls (
    call_id         VARCHAR PRIMARY KEY,
    timestamp       TIMESTAMP NOT NULL,
    route           VARCHAR   NOT NULL,
    method          VARCHAR   NOT NULL,
    request_body    VARCHAR,
    response_status INTEGER   NOT NULL,
    response_body   VARCHAR,
    duration_ms     DOUBLE    NOT NULL,
    user_id         VARCHAR
)
"""

_INDEX_SQL: list[str] = [
    "CREATE INDEX IF NOT EXISTS idx_apicalls_ts     ON api_calls(timestamp)",
    "CREATE INDEX IF NOT EXISTS idx_apicalls_route  ON api_calls(route)",
    "CREATE INDEX IF NOT EXISTS idx_apicalls_status ON api_calls(response_status)",
]


def _sanitise(data: dict[str, Any] | None) -> dict[str, Any] | None:
    """Redact sensitive keys from *data* before persisting.

    Only the top level of *data* is inspected.  ``None`` is passed through
    unchanged.

    Args:
        data: Raw dict to sanitise, or ``None``.

    Returns:
        New dict with sensitive keys replaced by ``"[REDACTED]"``,
        or ``None`` when *data* is ``None``.
    """
    if data is None or not isinstance(data, dict):
        return data
    return {
        k: "[REDACTED]" if k.lower() in _SENSITIVE_KEYS else v
        for k, v in data.items()
    }


class APIAnalyzer:
    """Persistent API call log backed by DuckDB.

    Captures every API call (route, method, bodies, status, timing) for
    post-mortem debugging, latency tracking, and replay.

    Thread-safe — DuckDB handles concurrent writes within the same process.

    Args:
        db_path: Path to the DuckDB file.  Defaults to
            ``~/.flinttrade/api_analyzer.duckdb``.  Pass ``":memory:"``
            for ephemeral in-process storage (useful in tests).

    Example::

        az = APIAnalyzer(":memory:")
        az.log_call("/v1/health", "GET", None, 200, {"status": "ok"}, 3.1)
        assert az.count() == 1
    """

    def __init__(
        self,
        db_path: Path | str | None = None,
        enabled: bool | None = None,
    ) -> None:
        import os  # noqa: PLC0415
        import duckdb  # lazy import

        if db_path is None:
            db_path = Path.home() / ".flinttrade" / "api_analyzer.duckdb"

        if isinstance(db_path, str) and db_path != ":memory:":
            db_path = Path(db_path)

        if isinstance(db_path, Path):
            db_path.parent.mkdir(parents=True, exist_ok=True)
            self._db_path: str = str(db_path)
        else:
            self._db_path = str(db_path)

        self._conn = duckdb.connect(self._db_path)
        self._init_schema()

        # Enabled state: explicit parameter > env var > default True.
        if enabled is not None:
            self._enabled: bool = enabled
        else:
            env_val = os.getenv("ENABLE_ANALYZER", "true").lower()
            self._enabled = env_val in ("1", "true", "yes")

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

    def log_call(
        self,
        route: str,
        method: str,
        request_body: dict[str, Any] | None,
        response_status: int,
        response_body: dict[str, Any] | None,
        duration_ms: float,
        user_id: str | None = None,
    ) -> str:
        """Persist a single API call record.

        Args:
            route: Flask request path (e.g. ``"/v1/orders/place"``).
            method: HTTP method (``"GET"``, ``"POST"``, …).
            request_body: Raw request payload dict; sensitive keys are
                automatically redacted.
            response_status: HTTP response status code.
            response_body: Raw response payload dict; sensitive keys are
                automatically redacted.
            duration_ms: Request duration in milliseconds.
            user_id: Authenticated user identifier, or ``None``.

        Returns:
            The ``call_id`` assigned to this record (16-char hex string).
        """
        call_id = secrets.token_hex(8)
        timestamp = datetime.now(IST)

        req_json = (
            json.dumps(_sanitise(request_body), default=str)
            if request_body is not None
            else None
        )
        resp_json = (
            json.dumps(_sanitise(response_body), default=str)
            if response_body is not None
            else None
        )

        if not self._enabled:
            logger.debug("APIAnalyzer disabled — call not logged: %s %s", method, route)
            return call_id

        self._conn.execute(
            """
            INSERT INTO api_calls
                (call_id, timestamp, route, method, request_body,
                 response_status, response_body, duration_ms, user_id)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            [
                call_id,
                timestamp,
                route,
                method,
                req_json,
                response_status,
                resp_json,
                round(duration_ms, 3),
                user_id,
            ],
        )
        logger.debug(
            "APIAnalyzer: %s %s %d %.1fms call_id=%s",
            method, route, response_status, duration_ms, call_id,
        )
        return call_id

    # ------------------------------------------------------------------
    # Read
    # ------------------------------------------------------------------

    def recent(
        self,
        route_filter: str | None = None,
        limit: int = 100,
        offset: int = 0,
    ) -> list[dict[str, Any]]:
        """Return recent API call records as plain dicts.

        Args:
            route_filter: When provided, only calls whose ``route`` starts
                with this prefix are returned (SQL ``LIKE`` prefix match).
            limit: Maximum number of rows (default 100, clamped to 1000).
            offset: Row offset for pagination.

        Returns:
            List of dicts ordered by ``timestamp`` descending.  The
            ``request_body`` and ``response_body`` fields are
            deserialised from JSON back to dicts.
        """
        limit = max(1, min(int(limit), 1000))
        offset = max(0, int(offset))

        if route_filter is not None:
            rows = self._conn.execute(
                """
                SELECT call_id, timestamp, route, method, request_body,
                       response_status, response_body, duration_ms, user_id
                FROM api_calls
                WHERE route LIKE ?
                ORDER BY timestamp DESC
                LIMIT ? OFFSET ?
                """,
                [f"{route_filter}%", limit, offset],
            ).fetchall()
        else:
            rows = self._conn.execute(
                """
                SELECT call_id, timestamp, route, method, request_body,
                       response_status, response_body, duration_ms, user_id
                FROM api_calls
                ORDER BY timestamp DESC
                LIMIT ? OFFSET ?
                """,
                [limit, offset],
            ).fetchall()

        return [self._row_to_dict(row) for row in rows]

    def replay(self, call_id: str) -> dict[str, Any]:
        """Retrieve the full request and response for a single API call.

        Args:
            call_id: The ``call_id`` of the call to retrieve.

        Returns:
            Dict with all fields populated, or an empty dict if
            *call_id* is not found.
        """
        row = self._conn.execute(
            """
            SELECT call_id, timestamp, route, method, request_body,
                   response_status, response_body, duration_ms, user_id
            FROM api_calls
            WHERE call_id = ?
            """,
            [call_id],
        ).fetchone()

        if row is None:
            return {}
        return self._row_to_dict(row)

    def count(
        self,
        route_filter: str | None = None,
        since: datetime | None = None,
    ) -> int:
        """Count API call records.

        Args:
            route_filter: Optional route prefix filter (SQL ``LIKE``).
            since: Optional lower-bound timestamp (timezone-aware).

        Returns:
            Integer row count.
        """
        conditions: list[str] = []
        params: list[Any] = []

        if route_filter is not None:
            conditions.append("route LIKE ?")
            params.append(f"{route_filter}%")
        if since is not None:
            conditions.append("timestamp >= ?")
            params.append(since)

        where = ("WHERE " + " AND ".join(conditions)) if conditions else ""
        row = self._conn.execute(
            f"SELECT COUNT(*) FROM api_calls {where}", params
        ).fetchone()
        return int(row[0]) if row else 0

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _row_to_dict(row: tuple) -> dict[str, Any]:
        """Convert a raw DuckDB result row to a plain dict.

        Args:
            row: Tuple of 9 values from the ``api_calls`` table.

        Returns:
            Dict with deserialised ``request_body`` and ``response_body``.
        """
        ts = row[1]
        ts_str = ts.isoformat() if isinstance(ts, datetime) else str(ts)

        def _parse(json_str: str | None) -> dict[str, Any] | None:
            if json_str is None:
                return None
            try:
                return json.loads(json_str)
            except (json.JSONDecodeError, TypeError):
                return {"_raw": json_str}

        return {
            "call_id": row[0],
            "timestamp": ts_str,
            "route": row[2],
            "method": row[3],
            "request_body": _parse(row[4]),
            "response_status": row[5],
            "response_body": _parse(row[6]),
            "duration_ms": row[7],
            "user_id": row[8],
        }

    # ------------------------------------------------------------------
    # Enable / disable / clear
    # ------------------------------------------------------------------

    def enable(self) -> None:
        """Enable call logging.

        When enabled (the default), every :meth:`log_call` invocation
        persists a row to DuckDB.  This can be toggled at runtime without
        restarting the process.
        """
        self._enabled = True
        logger.info("APIAnalyzer enabled")

    def disable(self) -> None:
        """Disable call logging while retaining existing log rows.

        When disabled, :meth:`log_call` returns a ``call_id`` immediately
        without writing to the database.  Existing rows are preserved.
        """
        self._enabled = False
        logger.info("APIAnalyzer disabled")

    def is_enabled(self) -> bool:
        """Return whether call logging is currently active.

        Returns:
            ``True`` when :meth:`log_call` will persist records.
        """
        return self._enabled

    def clear_logs(self, older_than_days: int | None = None) -> int:
        """Delete API call log rows.

        Args:
            older_than_days: When provided, only rows whose ``timestamp``
                is more than this many days old are deleted.  When
                ``None`` (default), **all** rows are deleted.

        Returns:
            Number of rows deleted.

        Example::

            # Purge logs older than 30 days:
            deleted = az.clear_logs(older_than_days=30)
        """
        if older_than_days is not None:
            from datetime import timedelta  # noqa: PLC0415

            cutoff = datetime.now(IST) - timedelta(days=older_than_days)
            before = self.count()
            self._conn.execute(
                "DELETE FROM api_calls WHERE timestamp < ?", [cutoff]
            )
            after = self.count()
            deleted = before - after
        else:
            before = self.count()
            self._conn.execute("DELETE FROM api_calls")
            deleted = before

        logger.info("APIAnalyzer: cleared %d log rows", deleted)
        return deleted

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    def close(self) -> None:
        """Close the underlying DuckDB connection."""
        self._conn.close()

    def __enter__(self) -> "APIAnalyzer":
        return self

    def __exit__(self, *args: Any) -> None:
        self.close()
