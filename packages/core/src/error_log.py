"""Structured JSON error logging to DuckDB for post-mortem debugging.

Every unhandled API error is persisted as a structured row containing the
request path, HTTP method, status code, sanitised request body, exception
class/message/traceback, and the authenticated user (if known).

Entries are queryable via :class:`ErrorLog` directly or through the
``/v1/admin/errors`` REST endpoint exposed by
:mod:`packages.core.src.admin_routes`.

Example::

    from packages.core.src.error_log import ErrorLog

    log = ErrorLog()
    log.log(
        route="/v1/orders/place",
        method="POST",
        status_code=500,
        request_body={"symbol": "NIFTY", "password": "secret"},
        error=ValueError("order rejected"),
        user_id="alice",
    )
    recent = log.recent(limit=10)
    total  = log.count()
"""

from __future__ import annotations

import json
import logging
import secrets
import traceback as _traceback
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

logger = logging.getLogger("flinttrade.core.error_log")

# IST as a fixed-offset timezone — no pytz dependency required.
IST = timezone(timedelta(hours=5, minutes=30))

# Keys whose values must never be persisted.
_SENSITIVE_KEYS: frozenset[str] = frozenset(
    {"password", "token", "api_key", "apikey", "secret", "totp", "otp", "pin"}
)

_CREATE_TABLE_SQL = """
CREATE TABLE IF NOT EXISTS error_log (
    entry_id    VARCHAR PRIMARY KEY,
    timestamp   TIMESTAMP NOT NULL,
    route       VARCHAR   NOT NULL,
    method      VARCHAR   NOT NULL,
    status_code INTEGER,
    request_body VARCHAR,
    error_class  VARCHAR,
    error_message VARCHAR,
    traceback    VARCHAR,
    user_id      VARCHAR
)
"""

_INDEX_SQL = [
    "CREATE INDEX IF NOT EXISTS idx_errorlog_ts     ON error_log(timestamp)",
    "CREATE INDEX IF NOT EXISTS idx_errorlog_route  ON error_log(route)",
    "CREATE INDEX IF NOT EXISTS idx_errorlog_status ON error_log(status_code)",
]


@dataclass
class ErrorEntry:
    """A single row from the error log.

    Attributes:
        entry_id: Unique 16-character hex identifier for this error entry.
        timestamp: Timezone-aware datetime of the error (IST).
        route: Flask request path (e.g. ``/v1/orders/place``).
        method: HTTP method (``GET``, ``POST``, …).
        status_code: HTTP status code of the response (e.g. ``500``).
        request_body: Sanitised request payload; sensitive keys are redacted.
        error_class: ``__class__.__name__`` of the exception, if any.
        error_message: ``str(error)`` of the exception, if any.
        traceback: Full formatted traceback string from
            :func:`traceback.format_exc`, if any.
        user_id: Authenticated user identifier, or ``None`` for anonymous
            requests.
    """

    entry_id: str
    timestamp: datetime
    route: str
    method: str
    status_code: int | None
    request_body: dict[str, Any] | None = field(default=None)
    error_class: str | None = field(default=None)
    error_message: str | None = field(default=None)
    traceback: str | None = field(default=None)
    user_id: str | None = field(default=None)


def _sanitise(data: dict[str, Any]) -> dict[str, Any]:
    """Redact sensitive keys before persisting to the database.

    Only the top level of *data* is inspected — nested dicts are not
    recursed into intentionally to avoid misidentifying business fields
    that happen to have the same name at deeper nesting levels.

    Args:
        data: Raw request body dictionary.

    Returns:
        A new dict with sensitive keys replaced by ``"[REDACTED]"``.
    """
    if not isinstance(data, dict):
        return data
    return {
        k: "[REDACTED]" if k.lower() in _SENSITIVE_KEYS else v
        for k, v in data.items()
    }


class ErrorLog:
    """Persistent structured error log backed by DuckDB.

    Thread-safe for concurrent Flask workers via a single DuckDB file
    connection (DuckDB supports multi-writer access to file-backed
    databases within the same process).

    The database file is created at *db_path* on first instantiation.
    If the parent directory does not exist it is created automatically.

    Args:
        db_path: Path to the DuckDB file.  Defaults to
            ``~/.flinttrade/error_log.duckdb``.  Pass ``":memory:"`` for
            ephemeral in-process storage (useful in tests).

    Example::

        log = ErrorLog(":memory:")
        log.log("/v1/test", "GET", 500)
        assert log.count() == 1
    """

    def __init__(self, db_path: Path | str | None = None) -> None:
        import duckdb  # lazy — avoids penalising startup if unused

        if db_path is None:
            db_path = Path.home() / ".flinttrade" / "error_log.duckdb"

        if isinstance(db_path, str) and db_path != ":memory:":
            db_path = Path(db_path)

        if isinstance(db_path, Path):
            db_path.parent.mkdir(parents=True, exist_ok=True)
            self._db_path: str = str(db_path)
        else:
            # ":memory:"
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
        route: str,
        method: str,
        status_code: int,
        request_body: dict[str, Any] | None = None,
        error: BaseException | None = None,
        user_id: str | None = None,
    ) -> str:
        """Persist a structured error entry and return its ``entry_id``.

        Args:
            route: Flask request path (e.g. ``"/v1/orders/place"``).
            method: HTTP method string (``"GET"``, ``"POST"``, …).
            status_code: HTTP status code for this error response.
            request_body: Raw request body dict; sensitive keys are
                automatically redacted before storage.
            error: The exception instance that caused this error.  When
                provided, ``error_class``, ``error_message``, and
                ``traceback`` are extracted from it.  ``traceback`` is
                captured via :func:`traceback.format_exc` so it must be
                called **within an active exception context** for the
                traceback to be meaningful.
            user_id: Authenticated user ID, if known.

        Returns:
            The ``entry_id`` assigned to this entry (16-char hex string).
        """
        entry_id = secrets.token_hex(8)
        timestamp = datetime.now(IST)

        sanitised = _sanitise(request_body) if request_body else None
        body_json = json.dumps(sanitised, default=str) if sanitised is not None else None

        err_class: str | None = error.__class__.__name__ if error is not None else None
        err_msg: str | None = str(error) if error is not None else None
        # format_exc() only returns a useful traceback inside an active except
        # block.  Callers that invoke log() from within an except handler will
        # get a full traceback; callers outside an except block get "NoneType: None".
        err_tb: str | None = _traceback.format_exc() if error is not None else None
        # Normalise the useless default traceback.format_exc() return value.
        if err_tb and err_tb.strip() in ("NoneType: None", "None"):
            err_tb = None

        self._conn.execute(
            """
            INSERT INTO error_log
                (entry_id, timestamp, route, method, status_code,
                 request_body, error_class, error_message, traceback, user_id)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            [
                entry_id,
                timestamp,
                route,
                method,
                status_code,
                body_json,
                err_class,
                err_msg,
                err_tb,
                user_id,
            ],
        )
        logger.debug(
            "Error logged: entry_id=%s route=%s status=%d", entry_id, route, status_code
        )
        return entry_id

    # ------------------------------------------------------------------
    # Read
    # ------------------------------------------------------------------

    def recent(self, limit: int = 100, offset: int = 0) -> list[dict[str, Any]]:
        """Return the most recent error entries as plain dicts.

        The ``request_body`` field is deserialised from JSON back to a dict
        for callers.  ``timestamp`` is returned as an ISO-8601 string with
        UTC offset so that JSON serialisation is trivial.

        Args:
            limit: Maximum number of rows to return (default 100).
            offset: Row offset for pagination (default 0).

        Returns:
            List of dicts ordered by ``timestamp`` descending.
        """
        limit = max(1, min(int(limit), 500))
        offset = max(0, int(offset))

        rows = self._conn.execute(
            """
            SELECT entry_id, timestamp, route, method, status_code,
                   request_body, error_class, error_message, traceback, user_id
            FROM error_log
            ORDER BY timestamp DESC
            LIMIT ? OFFSET ?
            """,
            [limit, offset],
        ).fetchall()

        result: list[dict[str, Any]] = []
        for row in rows:
            ts = row[1]
            ts_str = ts.isoformat() if isinstance(ts, datetime) else str(ts)
            body = None
            if row[5] is not None:
                try:
                    body = json.loads(row[5])
                except (json.JSONDecodeError, TypeError):
                    body = row[5]
            result.append(
                {
                    "entry_id": row[0],
                    "timestamp": ts_str,
                    "route": row[2],
                    "method": row[3],
                    "status_code": row[4],
                    "request_body": body,
                    "error_class": row[6],
                    "error_message": row[7],
                    "traceback": row[8],
                    "user_id": row[9],
                }
            )
        return result

    def count(self, since: datetime | None = None) -> int:
        """Count persisted error entries.

        Args:
            since: When provided, only entries at or after this timestamp
                are counted.  Must be a timezone-aware
                :class:`~datetime.datetime`.

        Returns:
            Integer count of matching rows.
        """
        if since is not None:
            row = self._conn.execute(
                "SELECT COUNT(*) FROM error_log WHERE timestamp >= ?", [since]
            ).fetchone()
        else:
            row = self._conn.execute(
                "SELECT COUNT(*) FROM error_log"
            ).fetchone()
        return int(row[0]) if row else 0

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    def close(self) -> None:
        """Close the underlying DuckDB connection."""
        self._conn.close()

    def __enter__(self) -> "ErrorLog":
        return self

    def __exit__(self, *args: Any) -> None:
        self.close()
