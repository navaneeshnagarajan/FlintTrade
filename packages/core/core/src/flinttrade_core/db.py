"""SQLite connection helpers for FlintTrade persistent state."""

from __future__ import annotations

import contextlib
import logging
import os
import sqlite3
import threading
from collections.abc import Iterator
from pathlib import Path
from typing import Literal

logger = logging.getLogger("flinttrade.db")

DurabilityProfile = Literal["normal", "full"]
TempStoreProfile = Literal["MEMORY", "FILE"]

_SQLITE_MAGIC = b"SQLite format 3\x00"
# DuckDB storage header: 4-byte checksum, then the literal "DUCK".
_DUCKDB_MAGIC_OFFSET = 8
_DUCKDB_MAGIC = b"DUCK"

# Serialises legacy-file recovery so two threads opening the same path
# cannot race the rename and quarantine each other's freshly created DB.
_RECOVERY_LOCK = threading.Lock()


def _connect(path_str: str, sync: str, temp_store: str, cache_size_kb: int) -> sqlite3.Connection:
    conn = sqlite3.connect(
        path_str,
        isolation_level=None,
        check_same_thread=False,
        timeout=10.0,
    )
    try:
        conn.executescript(
            f"""
            PRAGMA journal_mode       = WAL;
            PRAGMA synchronous        = {sync};
            PRAGMA busy_timeout       = 5000;
            PRAGMA foreign_keys       = ON;
            PRAGMA wal_autocheckpoint = 1000;
            PRAGMA temp_store         = {temp_store};
            PRAGMA cache_size         = -{int(cache_size_kb)};
            """
        )
    except sqlite3.DatabaseError:
        conn.close()
        raise
    return conn


def _quarantine_foreign_db(path_str: str) -> Path | None:
    """Move a legacy DuckDB file aside so a fresh database can be created.

    Several stores migrated DuckDB→SQLite in v0.6.0 (activity_log,
    security_tracker); a pre-migration workspace still holds the legacy
    DuckDB file, which sqlite3 rejects with "file is not a database".
    Quarantining preserves the legacy data for manual recovery. Only a
    positively identified DuckDB header is quarantined — anything else
    (including header-destroying SQLite corruption) returns ``None`` so
    the caller re-raises instead of silently discarding a possibly
    recoverable database.
    """
    db_file = Path(path_str)
    try:
        with db_file.open("rb") as fh:
            header = fh.read(_DUCKDB_MAGIC_OFFSET + len(_DUCKDB_MAGIC))
    except OSError:
        return None
    if header[_DUCKDB_MAGIC_OFFSET:] != _DUCKDB_MAGIC:
        return None
    backup = db_file.with_name(f"{db_file.name}.pre-sqlite.bak")
    counter = 1
    while backup.exists():
        backup = db_file.with_name(f"{db_file.name}.pre-sqlite.bak.{counter}")
        counter += 1
    db_file.rename(backup)
    # Sidecars from either engine (DuckDB `.wal`, SQLite `-wal`/`-shm`)
    # would poison the recreated database; move them with the main file.
    # ``replace`` keeps Windows rename semantics deterministic if a stale
    # sidecar backup is in the way.
    for suffix in (".wal", "-wal", "-shm"):
        sidecar = db_file.with_name(db_file.name + suffix)
        if sidecar.exists():
            sidecar.replace(backup.with_name(backup.name + suffix))
    return backup


def open_sqlite(
    path: str | os.PathLike[str],
    *,
    durability: DurabilityProfile = "normal",
    temp_store: TempStoreProfile = "MEMORY",
    cache_size_kb: int = 65_536,
) -> sqlite3.Connection:
    """Open a SQLite connection with FlintTrade WAL pragmas applied.

    A file in a foreign on-disk format (legacy DuckDB from before the
    v0.6.0 engine migration) is quarantined to ``<name>.pre-sqlite.bak``
    and the database recreated fresh; genuine SQLite corruption still
    raises :class:`sqlite3.DatabaseError`.
    """
    path_str = os.fspath(path)
    sync = "FULL" if durability == "full" else "NORMAL"
    try:
        return _connect(path_str, sync, temp_store, cache_size_kb)
    except sqlite3.DatabaseError:
        # In-memory databases are never on disk and can't be recovered.
        if path_str == ":memory:":
            raise
        with _RECOVERY_LOCK:
            # Double-checked: another thread may have already quarantined and
            # recreated this database while we waited for the lock. Retrying
            # the connect *inside* the lock also closes the rename race — a
            # thread that lost the race sees the recreated file here and
            # succeeds, instead of tripping the missing-file guard below at
            # the instant the winner has renamed but not yet recreated.
            try:
                return _connect(path_str, sync, temp_store, cache_size_kb)
            except sqlite3.DatabaseError:
                pass
            if not os.path.isfile(path_str):
                raise
            backup = _quarantine_foreign_db(path_str)
            if backup is None:
                raise
            logger.warning(
                "Database %s was not SQLite (legacy DuckDB engine file); "
                "moved it to %s and recreated fresh",
                path_str,
                backup,
            )
            return _connect(path_str, sync, temp_store, cache_size_kb)


@contextlib.contextmanager
def disable_journal_triggers(conn: sqlite3.Connection) -> Iterator[None]:
    """Temporarily drop journal FTS triggers for bulk tag updates."""
    trigger_names = [
        "journal_tag_ai",
        "journal_tag_ad",
        "journal_ai",
        "journal_au_before",
        "journal_au_after",
        "journal_ad",
    ]
    saved_ddl: dict[str, str] = {}
    for name in trigger_names:
        row = conn.execute(
            "SELECT sql FROM sqlite_master WHERE type='trigger' AND name = ?",
            (name,),
        ).fetchone()
        if row and row[0]:
            saved_ddl[name] = row[0]
            conn.execute(f"DROP TRIGGER IF EXISTS {name}")
    try:
        yield
    finally:
        for ddl in saved_ddl.values():
            conn.execute(ddl)
        has_fts = conn.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name='journal_fts'"
        ).fetchone()
        if has_fts:
            conn.execute("INSERT INTO journal_fts(journal_fts) VALUES('rebuild')")


_disable_journal_triggers = disable_journal_triggers
