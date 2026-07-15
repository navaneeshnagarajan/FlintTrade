"""Crash-recovery tests for boot-time DuckDB WAL handling."""

from __future__ import annotations

import os
import subprocess
import sys

import duckdb
import pytest


@pytest.mark.unit
def test_cleanup_checkpoints_recoverable_wal_without_losing_crash_commits(
    tmp_path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import flinttrade_core.app as app_module

    database = tmp_path / "crash.duckdb"
    script = """
import os
import sys
import duckdb

connection = duckdb.connect(sys.argv[1])
connection.execute("CREATE TABLE crash_rows(value INTEGER)")
connection.execute("INSERT INTO crash_rows VALUES (42)")
os._exit(0)
"""
    completed = subprocess.run(  # noqa: S603 - fixed interpreter and local test script
        [sys.executable, "-c", script, str(database)],
        check=False,
        env={**os.environ, "PYTHONUNBUFFERED": "1"},
        capture_output=True,
        text=True,
        timeout=10,
    )
    assert completed.returncode == 0, completed.stderr
    wal = tmp_path / "crash.duckdb.wal"
    assert wal.exists(), "fixture did not leave a crash WAL"
    monkeypatch.setattr(app_module, "_workspace_dir", lambda: tmp_path)

    app_module._cleanup_stale_duckdb_wals()

    with duckdb.connect(str(database), read_only=True) as connection:
        assert connection.execute("SELECT value FROM crash_rows").fetchall() == [(42,)]


@pytest.mark.unit
def test_cleanup_leaves_paired_wal_when_database_recovery_fails(
    tmp_path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import flinttrade_core.app as app_module

    database = tmp_path / "broken.duckdb"
    wal = tmp_path / "broken.duckdb.wal"
    database.write_bytes(b"not a duckdb database")
    wal.write_bytes(b"recoverable evidence")
    monkeypatch.setattr(app_module, "_workspace_dir", lambda: tmp_path)

    app_module._cleanup_stale_duckdb_wals()

    assert wal.read_bytes() == b"recoverable evidence"
