"""Durable SQLite JWT revocations, rate-limit events and OTP request history.

The authority is ``<workspace>/auth_state.sqlite``. Legacy DuckDB requires the
explicit offline migration CLI, never an automatic fallback or empty reset.
"""
from __future__ import annotations

import os
import threading
import time
from contextlib import contextmanager
from pathlib import Path

from flinttrade_core.auth_state_runtime import (
    AuthStateUnavailable,
    check_auth_migration_evidence,
    open_authority_database,
    validate_schema,
)


def _default_db_path() -> Path:
    """Return the workspace-scoped AuthState database path."""
    from .workspace import workspace_dir

    return workspace_dir() / "auth_state.sqlite"


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
    """SQLite-backed persistence, with process-safe atomic admission."""

    def __init__(self, db_path: str | Path | None = None) -> None:
        self._default_bound = db_path is None
        self._db_path = (Path(db_path) if db_path is not None else _default_db_path()).absolute()
        check_auth_migration_evidence(self._db_path)
        self._conn = open_authority_database(self._db_path, _CREATE_SCHEMA_SQL)
        self._lock = threading.Lock()
        stat = self._db_path.stat()
        self._identity = (stat.st_dev, stat.st_ino)
        self._pid = os.getpid()
        self._closed = False

    def _check_authority(self) -> None:
        if self._closed or self._pid != os.getpid():
            raise AuthStateUnavailable("closed or inherited auth owner")
        try:
            stat = self._db_path.stat()
        except OSError as exc:
            raise AuthStateUnavailable("auth authority disappeared") from exc
        if self._db_path.is_symlink() or (stat.st_dev, stat.st_ino) != self._identity:
            raise AuthStateUnavailable("auth authority was replaced")
        check_auth_migration_evidence(self._db_path)
        validate_schema(self._conn, _CREATE_SCHEMA_SQL)

    @contextmanager
    def _transaction(self):
        with self._lock:
            self._check_authority()
            self._conn.execute("BEGIN IMMEDIATE")
            try:
                validate_schema(self._conn, _CREATE_SCHEMA_SQL)
                yield
                validate_schema(self._conn, _CREATE_SCHEMA_SQL)
                self._conn.execute("COMMIT")
            except BaseException:
                self._conn.execute("ROLLBACK")
                raise

    def revoke_jti(self, jti: str, exp: float) -> None:
        """Persist a revoked JWT id with its UTC epoch expiry."""
        with self._transaction():
            self._conn.execute(
                "INSERT OR REPLACE INTO revoked_jtis (jti, exp, revoked_at) VALUES (?, ?, ?)",
                (jti, exp, time.time()),
            )
            self._conn.execute("DELETE FROM revoked_jtis WHERE exp <= ?", (time.time(),))

    def is_jti_revoked(self, jti: str) -> bool:
        """Read revocation without altering expired historical evidence."""
        with self._lock:
            self._check_authority()
            return self._conn.execute("SELECT 1 FROM revoked_jtis WHERE jti=?", (jti,)).fetchone() is not None

    def check_rate_limit(self, endpoint: str, ip: str, max_requests: int, window_seconds: int) -> bool:
        """Atomically prune/count/admit, recording only an allowed request."""
        with self._transaction():
            now = time.time()
            self._conn.execute(
                "DELETE FROM rate_limit_events WHERE endpoint=? AND ip=? AND ts<=?",
                (endpoint, ip, now - window_seconds),
            )
            count = self._conn.execute(
                "SELECT COUNT(*) FROM rate_limit_events WHERE endpoint=? AND ip=?", (endpoint, ip),
            ).fetchone()[0]
            if count >= max_requests:
                return False
            self._conn.execute("INSERT INTO rate_limit_events VALUES (?,?,?)", (endpoint, ip, now))
            return True

    def record_otp_request(self, email: str) -> None:
        """Append an OTP request, including equal-timestamp duplicates."""
        with self._transaction():
            self._conn.execute("INSERT INTO otp_requests VALUES (?,?)", (email, time.time()))

    def check_otp_request_limit(self, email: str, max_requests: int, window_seconds: int) -> bool:
        """Atomically count and record an allowed OTP request across processes."""
        with self._transaction():
            now = time.time()
            cutoff = now - window_seconds
            self._conn.execute("DELETE FROM otp_requests WHERE ts<=?", (cutoff,))
            count = self._conn.execute(
                "SELECT COUNT(*) FROM otp_requests WHERE email=? AND ts>?", (email, cutoff),
            ).fetchone()[0]
            if count >= max_requests:
                return False
            self._conn.execute("INSERT INTO otp_requests VALUES (?,?)", (email, now))
            return True

    def count_recent_otp_requests(self, email: str, window_seconds: int) -> int:
        """Prune expired history and count the remaining requests for an email."""
        with self._transaction():
            cutoff = time.time() - window_seconds
            self._conn.execute("DELETE FROM otp_requests WHERE ts<=?", (cutoff,))
            return self._conn.execute(
                "SELECT COUNT(*) FROM otp_requests WHERE email=? AND ts>?", (email, cutoff),
            ).fetchone()[0]

    def close(self) -> None:
        """Close this owner's connection."""
        with self._lock:
            if not self._closed:
                self._conn.close()
                self._closed = True


_SINGLETON: AuthState | None = None
_SINGLETON_LOCK = threading.Lock()


def get_auth_state(db_path: str | Path | None = None) -> AuthState:
    """Return the process-wide auth owner, explicitly bindable on first use."""
    global _SINGLETON
    with _SINGLETON_LOCK:
        if _SINGLETON is not None:
            if db_path is not None and Path(db_path).absolute() != _SINGLETON._db_path:
                raise AuthStateUnavailable("auth owner already bound to a different path")
            if db_path is None and _SINGLETON._default_bound and _default_db_path().absolute() != _SINGLETON._db_path:
                raise AuthStateUnavailable("default auth workspace changed; owner cannot be rebound")
            if _SINGLETON._closed or _SINGLETON._pid != os.getpid():
                _SINGLETON = AuthState(None if _SINGLETON._default_bound else _SINGLETON._db_path)
        if _SINGLETON is None:
            _SINGLETON = AuthState(db_path=db_path)
        return _SINGLETON


def reset_singleton_for_tests() -> None:
    """Drop the singleton — tests only; production must retain its authority."""
    global _SINGLETON
    with _SINGLETON_LOCK:
        if _SINGLETON is not None:
            _SINGLETON.close()
        _SINGLETON = None
