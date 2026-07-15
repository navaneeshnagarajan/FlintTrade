"""Tests for flinttrade_core.db SQLite helpers (legacy-engine recovery)."""

from __future__ import annotations

import sqlite3
import threading
import time
from pathlib import Path

import pytest

from flinttrade_core.db import _SQLITE_MAGIC, open_sqlite

pytestmark = pytest.mark.unit

# First 16 bytes of a DuckDB storage file: 4-byte checksum then "DUCK".
_FAKE_DUCKDB_HEADER = b"\x06\x31\x87\xb8\x9f\x14\x11\x6cDUCK@\x00\x00\x00"


def test_open_sqlite_creates_fresh_db(tmp_path: Path) -> None:
    db = tmp_path / "fresh.db"
    conn = open_sqlite(db)
    conn.execute("CREATE TABLE t (x INTEGER)")
    conn.close()
    assert db.read_bytes()[: len(_SQLITE_MAGIC)] == _SQLITE_MAGIC


def test_open_sqlite_quarantines_legacy_duckdb_file(tmp_path: Path) -> None:
    db = tmp_path / "security.db"
    db.write_bytes(_FAKE_DUCKDB_HEADER + b"\x00" * 4096)
    sidecar = tmp_path / "security.db.wal"
    sidecar.write_bytes(b"duckdb-wal")

    conn = open_sqlite(db)
    conn.execute("CREATE TABLE t (x INTEGER)")
    conn.close()

    backup = tmp_path / "security.db.pre-sqlite.bak"
    assert backup.exists(), "legacy file must be preserved, not deleted"
    assert backup.read_bytes()[:16] == _FAKE_DUCKDB_HEADER
    assert (tmp_path / "security.db.pre-sqlite.bak.wal").exists()
    assert not sidecar.exists()
    assert db.read_bytes()[: len(_SQLITE_MAGIC)] == _SQLITE_MAGIC


def test_open_sqlite_quarantine_does_not_overwrite_existing_backup(tmp_path: Path) -> None:
    db = tmp_path / "activity.db"
    existing = tmp_path / "activity.db.pre-sqlite.bak"
    existing.write_bytes(b"older backup")
    db.write_bytes(_FAKE_DUCKDB_HEADER + b"\x00" * 1024)

    conn = open_sqlite(db)
    conn.close()

    assert existing.read_bytes() == b"older backup"
    assert (tmp_path / "activity.db.pre-sqlite.bak.1").exists()


def test_open_sqlite_still_raises_on_corrupt_sqlite_file(tmp_path: Path) -> None:
    db = tmp_path / "auth.db"
    # Valid SQLite magic followed by garbage: genuine corruption, not a
    # foreign engine file — must NOT be silently quarantined.
    db.write_bytes(_SQLITE_MAGIC + b"\xff" * 4096)

    with pytest.raises(sqlite3.DatabaseError):
        open_sqlite(db)

    assert db.exists()
    assert not (tmp_path / "auth.db.pre-sqlite.bak").exists()


def test_open_sqlite_concurrent_legacy_recovery_no_spurious_raise(tmp_path: Path) -> None:
    """Many threads opening the same legacy DuckDB file must all recover.

    Guards the rename race (Window A): a thread that loses the quarantine
    race must retry under the lock and succeed, not re-raise at the instant
    the winner has renamed the legacy file but not yet recreated it.

    Connection initialisation is serialised because first-time WAL access
    memory-maps SQLite's ``-shm`` index; a concurrent ``xShmMap`` stampede on
    a just-recreated database can SIGBUS the whole process before Python can
    report an exception.
    """
    db = tmp_path / "activity.db"
    db.write_bytes(_FAKE_DUCKDB_HEADER + b"\x00" * 4096)

    n_threads = 8
    barrier = threading.Barrier(n_threads)
    errors: list[Exception] = []
    errors_lock = threading.Lock()

    def worker() -> None:
        barrier.wait()
        try:
            conn = open_sqlite(db)
            conn.execute("CREATE TABLE IF NOT EXISTS t (x INTEGER)")
            conn.close()
        except Exception as exc:  # noqa: BLE001 — the assertion is "no thread raises"
            with errors_lock:
                errors.append(exc)

    threads = [threading.Thread(target=worker) for _ in range(n_threads)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert not errors, f"{len(errors)} threads raised, e.g. {errors[0]!r}"
    # The legacy file is quarantined exactly once; the result is fresh SQLite.
    assert (tmp_path / "activity.db.pre-sqlite.bak").exists()
    assert db.read_bytes()[: len(_SQLITE_MAGIC)] == _SQLITE_MAGIC


def test_open_sqlite_serialises_connection_initialisation(monkeypatch, tmp_path: Path) -> None:
    from flinttrade_core import db as db_module

    n_threads = 8
    barrier = threading.Barrier(n_threads)
    state_lock = threading.Lock()
    active = 0
    max_active = 0

    def observed_connect(*_args, **_kwargs):
        nonlocal active, max_active
        with state_lock:
            active += 1
            max_active = max(max_active, active)
        time.sleep(0.02)
        with state_lock:
            active -= 1
        return object()

    monkeypatch.setattr(db_module, "_connect", observed_connect)

    def worker() -> None:
        barrier.wait()
        db_module.open_sqlite(tmp_path / "shared.db")

    threads = [threading.Thread(target=worker) for _ in range(n_threads)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()

    assert max_active == 1


def test_open_sqlite_raises_on_unknown_garbage_header(tmp_path: Path) -> None:
    db = tmp_path / "auth.db"
    # Neither SQLite nor DuckDB: a zeroed/destroyed header must stay loud —
    # quarantining is reserved for positively identified legacy DuckDB files.
    db.write_bytes(b"\x00" * 4096)

    with pytest.raises(sqlite3.DatabaseError):
        open_sqlite(db)

    assert db.exists()
    assert not (tmp_path / "auth.db.pre-sqlite.bak").exists()
