"""Recovery commands for a database that already has two operator accounts."""

from __future__ import annotations

import sqlite3
import sys
from datetime import UTC, datetime
from pathlib import Path

import pytest


def _seed_two_operators(db_path: Path) -> None:
    conn = sqlite3.connect(db_path)
    try:
        conn.execute("""
            CREATE TABLE account (
                id INTEGER PRIMARY KEY,
                username TEXT NOT NULL,
                email TEXT NOT NULL,
                password_hash TEXT NOT NULL,
                pin_hash TEXT NOT NULL,
                totp_secret_encrypted BLOB NOT NULL,
                totp_salt BLOB NOT NULL,
                totp_enabled INTEGER NOT NULL DEFAULT 0,
                created_at TEXT NOT NULL
            )
        """)
        conn.execute("""
            CREATE TABLE sessions (
                id INTEGER PRIMARY KEY,
                account_id INTEGER NOT NULL
            )
        """)
        created = datetime(2026, 1, 2, 3, 4, 5, tzinfo=UTC).isoformat()
        for operator_id, username in ((1, "alice"), (2, "bob")):
            conn.execute(
                """INSERT INTO account (
                       id, username, email, password_hash, pin_hash,
                       totp_secret_encrypted, totp_salt, totp_enabled, created_at
                   ) VALUES (?, ?, ?, 'hash', '', ?, ?, 0, ?)""",
                (operator_id, username, f"{username}@example.com", b"secret", b"salt", created),
            )
            conn.execute(
                "INSERT INTO sessions (account_id) VALUES (?)",
                (operator_id,),
            )
        conn.commit()
    finally:
        conn.close()


@pytest.mark.unit
def test_operators_list_shows_id_username_and_created_time(tmp_path, monkeypatch, capsys) -> None:
    monkeypatch.setenv("FLINTTRADE_WORKSPACE_DIR", str(tmp_path))
    _seed_two_operators(tmp_path / "auth.db")
    monkeypatch.setattr(sys, "argv", ["flinttrade", "operators", "list"])

    from flinttrade_core.cli import main

    main()

    out = capsys.readouterr().out
    assert "id\tusername\tcreated" in out
    assert "1\talice\t2026-01-02T03:04:05+00:00" in out
    assert "2\tbob\t2026-01-02T03:04:05+00:00" in out
    assert "example.com" not in out
    assert "hash" not in out


@pytest.mark.unit
def test_operators_keep_leaves_one_operator_backup_and_migrates(tmp_path, monkeypatch, capsys) -> None:
    monkeypatch.setenv("FLINTTRADE_WORKSPACE_DIR", str(tmp_path))
    db_path = tmp_path / "auth.db"
    _seed_two_operators(db_path)
    monkeypatch.setattr(sys, "argv", ["flinttrade", "operators", "keep", "1"])

    from flinttrade_core.auth_service import AuthService
    from flinttrade_core.cli import main

    main()

    out = capsys.readouterr().out
    assert "Kept operator 1." in out
    assert "One operator account remains. Open FlintTrade and choose Retry." in out
    assert "bob" not in out

    backups = list(tmp_path.glob("auth.db.bak-*Z"))
    assert len(backups) == 1
    assert f"Backup: {backups[0]}" in out
    backup = sqlite3.connect(backups[0])
    try:
        backed_up = backup.execute("SELECT COUNT(*) FROM account").fetchone()
    finally:
        backup.close()
    assert backed_up is not None
    assert int(backed_up[0]) == 2

    live = sqlite3.connect(db_path)
    try:
        names = [row[0] for row in live.execute("SELECT username FROM account ORDER BY id")]
        sessions = [row[0] for row in live.execute("SELECT account_id FROM sessions ORDER BY account_id")]
        indexes = {
            row[0]
            for row in live.execute("SELECT name FROM sqlite_master WHERE type = 'index'")
        }
    finally:
        live.close()
    assert names == ["alice"]
    assert sessions == [1]
    assert "account_one_operator" in indexes
    assert AuthService(db_path=db_path).migration_blocked() is None


@pytest.mark.unit
def test_operators_keep_unknown_id_does_not_change_the_database(tmp_path, monkeypatch, capsys) -> None:
    monkeypatch.setenv("FLINTTRADE_WORKSPACE_DIR", str(tmp_path))
    db_path = tmp_path / "auth.db"
    _seed_two_operators(db_path)
    monkeypatch.setattr(sys, "argv", ["flinttrade", "operators", "keep", "9"])

    from flinttrade_core.cli import main

    with pytest.raises(SystemExit) as exc:
        main()

    assert exc.value.code == 1
    err = capsys.readouterr().err
    assert "No operator with that id." in err
    assert list(tmp_path.glob("auth.db.bak-*")) == []
    conn = sqlite3.connect(db_path)
    try:
        count = conn.execute("SELECT COUNT(*) FROM account").fetchone()
    finally:
        conn.close()
    assert count is not None
    assert int(count[0]) == 2
