"""Recovery commands for a database that already has two operator accounts."""

from __future__ import annotations

import os
import sqlite3
import stat
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


def _account_count(db_path: Path) -> int:
    conn = sqlite3.connect(db_path)
    try:
        row = conn.execute("SELECT COUNT(*) FROM account").fetchone()
    finally:
        conn.close()
    assert row is not None
    return int(row[0])


@pytest.mark.unit
def test_operators_keep_leaves_one_operator_backup_and_migrates(tmp_path, monkeypatch, capsys) -> None:
    monkeypatch.setenv("FLINTTRADE_WORKSPACE_DIR", str(tmp_path))
    db_path = tmp_path / "auth.db"
    _seed_two_operators(db_path)
    monkeypatch.setattr(sys.stdin, "isatty", lambda: False)
    monkeypatch.setattr(sys, "argv", ["flinttrade", "operators", "keep", "1", "--yes"])

    from flinttrade_core.auth_service import AuthService
    from flinttrade_core.cli import main

    previous_umask = os.umask(0)
    try:
        main()
    finally:
        os.umask(previous_umask)

    out = capsys.readouterr().out
    assert "Keeping 1 alice" in out
    assert "Removing 2 bob" in out
    assert "Kept operator 1." in out
    assert "One operator account remains. Open FlintTrade and choose Retry." in out
    assert "This backup contains login secrets. Keep it private and delete it once FlintTrade works again." in out

    backups = list(tmp_path.glob("auth.db.bak-*Z"))
    assert len(backups) == 1
    assert stat.S_IMODE(backups[0].stat().st_mode) == 0o600
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


@pytest.mark.unit
@pytest.mark.parametrize("answer", ["", "n", "no", "N"])
def test_operators_keep_aborts_unless_the_answer_is_yes(
    tmp_path, monkeypatch, capsys, answer: str,
) -> None:
    monkeypatch.setenv("FLINTTRADE_WORKSPACE_DIR", str(tmp_path))
    db_path = tmp_path / "auth.db"
    _seed_two_operators(db_path)
    monkeypatch.setattr(sys.stdin, "isatty", lambda: True)
    monkeypatch.setattr("builtins.input", lambda: answer)
    monkeypatch.setattr(sys, "argv", ["flinttrade", "operators", "keep", "1"])

    from flinttrade_core.cli import main

    with pytest.raises(SystemExit) as exc:
        main()

    assert exc.value.code == 1
    captured = capsys.readouterr()
    assert "Keeping 1 alice" in captured.out
    assert "Removing 2 bob" in captured.out
    assert "Remove 1 other operator account(s)? [y/N]" in captured.out
    assert "No data was changed." in captured.err
    assert list(tmp_path.glob("auth.db.bak-*")) == []
    assert _account_count(db_path) == 2


@pytest.mark.unit
def test_operators_keep_refuses_without_a_terminal(tmp_path, monkeypatch, capsys) -> None:
    monkeypatch.setenv("FLINTTRADE_WORKSPACE_DIR", str(tmp_path))
    db_path = tmp_path / "auth.db"
    _seed_two_operators(db_path)
    monkeypatch.setattr(sys.stdin, "isatty", lambda: False)

    def unexpected_prompt() -> str:
        raise AssertionError("prompted without a terminal")

    monkeypatch.setattr("builtins.input", unexpected_prompt)
    monkeypatch.setattr(sys, "argv", ["flinttrade", "operators", "keep", "1"])

    from flinttrade_core.cli import main

    with pytest.raises(SystemExit) as exc:
        main()

    assert exc.value.code == 1
    captured = capsys.readouterr()
    assert "Keeping 1 alice" in captured.out
    assert "Removing 2 bob" in captured.out
    assert "Remove " not in captured.out
    assert captured.err == "No data was changed. A terminal is required, or pass --yes.\n"
    assert list(tmp_path.glob("auth.db.bak-*")) == []
    assert _account_count(db_path) == 2


def _seed_keep_two(db_path: Path) -> None:
    """Two operators, with sessions, settings, and notes owned by each."""
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
                account_id INTEGER NOT NULL,
                token TEXT NOT NULL
            )
        """)
        conn.execute("""
            CREATE TABLE settings (
                operator_id INTEGER NOT NULL,
                key TEXT NOT NULL,
                value TEXT NOT NULL
            )
        """)
        conn.execute("""
            CREATE TABLE desk_notes (
                id INTEGER PRIMARY KEY,
                user_id INTEGER NOT NULL,
                body TEXT NOT NULL
            )
        """)
        created = datetime(2026, 1, 2, 3, 4, 5, tzinfo=UTC).isoformat()
        rows = (
            (1, "alice", "alice-hash", "alice-session", "light", "alice note"),
            (2, "bob", "bob-hash", "bob-session", "dark", "bob note"),
        )
        for operator_id, username, password_hash, token, theme, note in rows:
            conn.execute(
                """INSERT INTO account (
                       id, username, email, password_hash, pin_hash,
                       totp_secret_encrypted, totp_salt, totp_enabled, created_at
                   ) VALUES (?, ?, ?, ?, 'pin', ?, ?, 0, ?)""",
                (
                    operator_id,
                    username,
                    f"{username}@example.com",
                    password_hash,
                    b"secret",
                    b"salt",
                    created,
                ),
            )
            conn.execute(
                "INSERT INTO sessions (account_id, token) VALUES (?, ?)",
                (operator_id, token),
            )
            conn.execute(
                "INSERT INTO settings (operator_id, key, value) VALUES (?, 'theme', ?)",
                (operator_id, theme),
            )
            conn.execute(
                "INSERT INTO desk_notes (user_id, body) VALUES (?, ?)",
                (operator_id, note),
            )
        conn.commit()
    finally:
        conn.close()


def _kept_operator_snapshot(db_path: Path) -> dict[str, object]:
    conn = sqlite3.connect(db_path)
    try:
        account = conn.execute(
            "SELECT id, username, email, password_hash, created_at FROM account ORDER BY id"
        ).fetchall()
        sessions = conn.execute(
            "SELECT account_id, token FROM sessions ORDER BY token"
        ).fetchall()
        settings = conn.execute(
            "SELECT operator_id, key, value FROM settings ORDER BY value"
        ).fetchall()
        notes = conn.execute(
            "SELECT user_id, body FROM desk_notes ORDER BY body"
        ).fetchall()
    finally:
        conn.close()
    return {
        "account": account,
        "sessions": sessions,
        "settings": settings,
        "notes": notes,
    }


@pytest.mark.unit
def test_operators_keep_renumbers_survivor_and_is_idempotent(
    tmp_path, monkeypatch, capsys,
) -> None:
    monkeypatch.setenv("FLINTTRADE_WORKSPACE_DIR", str(tmp_path))
    db_path = tmp_path / "auth.db"
    _seed_keep_two(db_path)
    monkeypatch.setattr(sys.stdin, "isatty", lambda: False)
    monkeypatch.setattr(sys, "argv", ["flinttrade", "operators", "keep", "2", "--yes"])

    from flinttrade_core.auth_service import AuthService
    from flinttrade_core.cli import main

    main()
    captured = capsys.readouterr()
    assert "Keeping 2 bob" in captured.out
    assert "Removing 1 alice" in captured.out
    assert "Kept operator 2." in captured.out

    expected = {
        "account": [(1, "bob", "bob@example.com", "bob-hash", "2026-01-02T03:04:05+00:00")],
        "sessions": [(1, "bob-session")],
        "settings": [(1, "theme", "dark")],
        "notes": [(1, "bob note")],
    }
    assert _kept_operator_snapshot(db_path) == expected
    assert AuthService(db_path=db_path).migration_blocked() is None
    assert AuthService(db_path=db_path).is_setup() is True

    monkeypatch.setattr(sys, "argv", ["flinttrade", "operators", "keep", "1", "--yes"])
    main()
    assert _kept_operator_snapshot(db_path) == expected
    assert AuthService(db_path=db_path).is_setup() is True


@pytest.mark.unit
def test_operators_keep_rolls_back_when_the_renumber_fails(
    tmp_path, monkeypatch, capsys,
) -> None:
    monkeypatch.setenv("FLINTTRADE_WORKSPACE_DIR", str(tmp_path))
    db_path = tmp_path / "auth.db"
    _seed_keep_two(db_path)
    before = _kept_operator_snapshot(db_path)
    conn = sqlite3.connect(db_path)
    try:
        conn.execute("""
            CREATE TRIGGER abort_operator_renumber
            BEFORE UPDATE OF id ON account
            BEGIN
                SELECT RAISE(ABORT, 'renumber failed');
            END
        """)
        conn.commit()
    finally:
        conn.close()
    monkeypatch.setattr(sys.stdin, "isatty", lambda: False)
    monkeypatch.setattr(sys, "argv", ["flinttrade", "operators", "keep", "2", "--yes"])

    from flinttrade_core.cli import main

    with pytest.raises(SystemExit) as exc:
        main()

    assert exc.value.code == 1
    assert "No data was changed." in capsys.readouterr().err
    assert list(tmp_path.glob("auth.db.bak-*")) == []
    assert _kept_operator_snapshot(db_path) == before
