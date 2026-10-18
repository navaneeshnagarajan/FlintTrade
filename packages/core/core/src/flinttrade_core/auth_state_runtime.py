"""Strict SQLite opening for auth and its migrated webhook consumer.

Unlike the generic recovery helper, these stores must never quarantine a file,
recreate a missing established authority, or repair an incomplete schema.
"""
from __future__ import annotations

import os
import sqlite3
from contextlib import closing
from functools import lru_cache
from pathlib import Path

from flinttrade_core.legacy_sqlite_migration import fsync_directory, require_regular
from flinttrade_core.secure_file import harden

BUSY_TIMEOUT_SECONDS = 5.0


class AuthStateUnavailable(RuntimeError):
    """Auth authority needs explicit reconciliation; no fallback is permitted."""


def authority_marker(path: Path) -> Path:
    """Return the durable witness preventing recreation after file loss."""
    return path.with_name(f".{path.name}.authority")


def require_database(path: Path) -> None:
    """Validate SQLite format without opening/altering legacy or corrupt bytes."""
    require_regular(path)
    with path.open("rb") as stream:
        if stream.read(16) != b"SQLite format 3\x00":
            raise AuthStateUnavailable("auth authority is not SQLite; explicit migration required")


@lru_cache(maxsize=8)
def _schema_shape(schema: str) -> tuple:
    with closing(sqlite3.connect(":memory:")) as reference:
        reference.executescript(schema)
        names = [r[0] for r in reference.execute("SELECT name FROM sqlite_master WHERE type='table'")]
        return tuple((name, tuple(reference.execute(f'PRAGMA table_info("{name}")'))) for name in names)


def validate_schema(conn: sqlite3.Connection, schema: str, *, integrity: bool = False) -> None:
    """Check complete columns/constraints, without creating replacement tables."""
    if integrity and conn.execute("PRAGMA integrity_check").fetchall() != [("ok",)]:
        raise AuthStateUnavailable("auth authority integrity check failed")
    for name, columns in _schema_shape(schema):
        if tuple(conn.execute(f'PRAGMA table_info("{name}")')) != columns:
            raise AuthStateUnavailable("auth authority schema missing or incompatible")
        if conn.execute("SELECT 1 FROM sqlite_master WHERE type='trigger' AND tbl_name=?", (name,)).fetchone():
            raise AuthStateUnavailable("unexpected auth authority trigger")
        invalid = []
        for _, column, declared, required, _, primary_key in columns:
            quoted = f'"{column}"'
            if required or primary_key:
                invalid.append(f"{quoted} IS NULL")
            affinity = {"VARCHAR": "text", "TEXT": "text", "DOUBLE": "real", "REAL": "real",
                        "INTEGER": "integer", "BLOB": "blob"}[declared.upper()]
            invalid.append(f"({quoted} IS NOT NULL AND typeof({quoted}) != '{affinity}')")
            if affinity == "real":
                invalid.append(f"abs({quoted}) > 1.7976931348623157e308")
        if conn.execute(f'SELECT 1 FROM "{name}" WHERE ' + " OR ".join(invalid) + " LIMIT 1").fetchone():
            raise AuthStateUnavailable("invalid typed auth authority value")


def _mark_authority(path: Path) -> None:
    marker = authority_marker(path)
    require_regular(marker)
    expected = b"flinttrade-auth-authority-v1\n"
    try:
        fd = os.open(marker, os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0), 0o600)
    except FileExistsError:
        if marker.read_bytes() != expected:
            raise AuthStateUnavailable("invalid auth authority witness") from None
    else:
        with os.fdopen(fd, "wb") as stream:
            stream.write(expected)
            stream.flush()
            os.fsync(stream.fileno())
        harden(marker)
        fsync_directory(path.parent)


def open_authority_database(path: Path, schema: str) -> sqlite3.Connection:
    """Open/create one explicit authority; creation leaves a durable loss witness."""
    if any(p.is_symlink() for p in (path, *path.parents)):
        raise AuthStateUnavailable("symlinked auth authority refused")
    path.parent.mkdir(parents=True, exist_ok=True)
    require_regular(path)
    marker = authority_marker(path)
    require_regular(marker)
    existing = path.exists()
    if existing:
        require_database(path)
        with closing(sqlite3.connect(path.absolute().as_uri() + "?mode=ro", uri=True)) as check:
            validate_schema(check, schema, integrity=True)
    elif marker.exists() or any(path.with_name(path.name + suffix).exists() for suffix in ("-wal", "-shm", "-journal")):
        raise AuthStateUnavailable("established auth authority is missing")
    _mark_authority(path)
    if not existing:
        # A racing constructor may refuse, but must not initialise an empty
        # established file. Only this exclusive creator may execute the DDL.
        fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0), 0o600)
        os.close(fd)
    conn = sqlite3.connect(path.absolute().as_uri() + "?mode=rw", uri=True,
                           isolation_level=None, check_same_thread=False, timeout=BUSY_TIMEOUT_SECONDS)
    try:
        conn.execute("PRAGMA synchronous=FULL")
        if not existing:
            conn.executescript("BEGIN IMMEDIATE;\n" + schema + "\nCOMMIT;")
            harden(path)
            fsync_directory(path.parent)
        conn.execute("PRAGMA journal_mode=WAL")
        validate_schema(conn, schema)
        return conn
    except BaseException:
        conn.close()
        raise


def check_auth_migration_evidence(path: Path) -> None:
    """Refuse implicit creation/cutover in a legacy or interrupted workspace."""
    if path.name != "auth_state.sqlite":
        return
    from flinttrade_core.auth_state_migration import verified_auth_migration

    verified_auth_migration(path.parent)
