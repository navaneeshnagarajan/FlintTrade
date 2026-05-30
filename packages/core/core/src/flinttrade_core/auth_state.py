"""Persistent backing stores for auth_routes rate-limit + revocation state.

Without persistence:
- A revoked JWT remains valid on every other gunicorn worker until its
  natural expiry — because each worker has its own ``_REVOKED_JTIS`` dict.
- Rate-limit counters reset on worker restart, letting an attacker reset
  lockout state by triggering recycling.
- OTP request history lives only in the worker that served the first
  call, so a second request on a different worker skips the cap.

This module backs all three stores with a single DuckDB file at
``~/.flinttrade/auth_state.duckdb``. DuckDB is chosen for consistency
with the rest of FlintTrade's persistence layer (same dependency already
in use). Every operation takes a per-process lock plus relies on DuckDB's
internal mutex so concurrent writes from multiple gunicorn workers
serialise correctly.

The module is intentionally import-light — call ``get_auth_state()`` at
app-factory time and pass the instance around through ``app.config``.
"""

from __future__ import annotations

import logging
import threading
import time
from pathlib import Path
from typing import Optional

logger = logging.getLogger("flinttrade.core.auth_state")

_DEFAULT_DB_PATH = Path.home() / ".flinttrade" / "auth_state.duckdb"

_CREATE_SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS revoked_jtis (
    jti        VARCHAR PRIMARY KEY,
    exp        DOUBLE NOT NULL,
    revoked_at DOUBLE NOT NULL
);
CREATE TABLE IF NOT EXISTS rate_limit_events (
    endpoint  VARCHAR NOT NULL,
    ip        VARCHAR NOT NULL,
    ts        DOUBLE NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_rl_key ON rate_limit_events (endpoint, ip, ts);
CREATE TABLE IF NOT EXISTS otp_requests (
    email VARCHAR NOT NULL,
    ts    DOUBLE NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_otp_email ON otp_requests (email, ts);
"""


class AuthState:
    """DuckDB-backed persistence for JWT revocation, OTP log, rate-limit buckets."""

    def __init__(self, db_path: str | Path | None = None) -> None:
        import duckdb  # lazy — deliberate; avoids cost when unused

        if db_path is None:
            db_path = _DEFAULT_DB_PATH
        self._db_path = Path(db_path)
        self._db_path.parent.mkdir(parents=True, exist_ok=True)
        self._conn = duckdb.connect(str(self._db_path))
        self._lock = threading.Lock()
        for stmt in _CREATE_SCHEMA_SQL.strip().split(";"):
            stmt = stmt.strip()
            if stmt:
                self._conn.execute(stmt)

    # ------------------------------------------------------------------
    # JWT revocation
    # ------------------------------------------------------------------

    def revoke_jti(self, jti: str, exp: float) -> None:
        """Persist a revoked JWT id. ``exp`` is the token's UTC epoch expiry."""
        with self._lock:
            self._conn.execute(
                "INSERT OR REPLACE INTO revoked_jtis (jti, exp, revoked_at) VALUES (?, ?, ?)",
                [jti, exp, time.time()],
            )
            self._cleanup_revoked_jtis_locked()

    def is_jti_revoked(self, jti: str) -> bool:
        with self._lock:
            row = self._conn.execute(
                "SELECT 1 FROM revoked_jtis WHERE jti = ? LIMIT 1",
                [jti],
            ).fetchone()
            return row is not None

    def _cleanup_revoked_jtis_locked(self) -> None:
        """Remove jtis whose token expiry has passed."""
        self._conn.execute(
            "DELETE FROM revoked_jtis WHERE exp <= ?",
            [time.time()],
        )

    # ------------------------------------------------------------------
    # Rate limiter (sliding window)
    # ------------------------------------------------------------------

    def check_rate_limit(
        self,
        endpoint: str,
        ip: str,
        max_requests: int,
        window_seconds: int,
    ) -> bool:
        """Return True when a request is within the limit, False otherwise.

        Records the new request timestamp only when allowed, to keep the
        bucket deterministic across concurrent workers.
        """
        now = time.time()
        cutoff = now - window_seconds
        with self._lock:
            # Prune expired events for this key so the count is tight.
            self._conn.execute(
                "DELETE FROM rate_limit_events WHERE endpoint = ? AND ip = ? AND ts <= ?",
                [endpoint, ip, cutoff],
            )
            count_row = self._conn.execute(
                "SELECT COUNT(*) FROM rate_limit_events WHERE endpoint = ? AND ip = ?",
                [endpoint, ip],
            ).fetchone()
            count = int(count_row[0]) if count_row else 0
            if count >= max_requests:
                return False
            self._conn.execute(
                "INSERT INTO rate_limit_events (endpoint, ip, ts) VALUES (?, ?, ?)",
                [endpoint, ip, now],
            )
            return True

    # ------------------------------------------------------------------
    # OTP request log
    # ------------------------------------------------------------------

    def record_otp_request(self, email: str) -> None:
        with self._lock:
            self._conn.execute(
                "INSERT INTO otp_requests (email, ts) VALUES (?, ?)",
                [email, time.time()],
            )

    def count_recent_otp_requests(self, email: str, window_seconds: int) -> int:
        cutoff = time.time() - window_seconds
        with self._lock:
            # Prune old rows so the table stays small.
            self._conn.execute(
                "DELETE FROM otp_requests WHERE ts <= ?",
                [cutoff],
            )
            row = self._conn.execute(
                "SELECT COUNT(*) FROM otp_requests WHERE email = ? AND ts > ?",
                [email, cutoff],
            ).fetchone()
            return int(row[0]) if row else 0

    def close(self) -> None:
        with self._lock:
            self._conn.close()


_SINGLETON: Optional[AuthState] = None
_SINGLETON_LOCK = threading.Lock()


def get_auth_state(db_path: str | Path | None = None) -> AuthState:
    """Return the process-wide AuthState singleton, creating it on first call.

    Subsequent calls ignore ``db_path`` — pass it only on first
    construction (usually at Flask app-factory time).
    """
    global _SINGLETON
    if _SINGLETON is None:
        with _SINGLETON_LOCK:
            if _SINGLETON is None:
                _SINGLETON = AuthState(db_path=db_path)
                logger.info("AuthState initialised at %s", _SINGLETON._db_path)
    return _SINGLETON


def reset_singleton_for_tests() -> None:
    """Drop the singleton — test-only helper so fixtures can rebind the DB path."""
    global _SINGLETON
    with _SINGLETON_LOCK:
        if _SINGLETON is not None:
            try:
                _SINGLETON.close()
            except Exception:  # noqa: BLE001
                pass
        _SINGLETON = None
