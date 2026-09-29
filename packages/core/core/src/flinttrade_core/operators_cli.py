"""Operator recovery commands for a paused single-operator update.

``flinttrade operators list`` prints id, username, and created time.
``flinttrade operators keep <id>`` copies the database beside itself, removes
every other operator row and session rows that name those operators, then
runs the single-operator migration.
"""

from __future__ import annotations

import re
import sqlite3
import sys
from datetime import UTC, datetime
from pathlib import Path

from .workspace import workspace_dir

_IDENTIFIER = re.compile(r"[A-Za-z_][A-Za-z0-9_]*")
_OPERATOR_REF_COLUMNS = ("account_id", "operator_id", "user_id")


def auth_db_path() -> Path:
    """Return the operator database path for this process.

    Resolved when the command runs, so ``FLINTTRADE_WORKSPACE_DIR`` is honoured
    even if :mod:`flinttrade_core.auth_service` was imported earlier.
    """
    return workspace_dir() / "auth.db"


def cmd_operators_list() -> None:
    """Print each operator's id, username, and created time."""
    db_path = auth_db_path()
    if not db_path.is_file():
        print("No operator database was found.", file=sys.stderr)
        raise SystemExit(1)
    conn = sqlite3.connect(db_path)
    try:
        rows = conn.execute(
            "SELECT id, username, created_at FROM account ORDER BY id"
        ).fetchall()
    finally:
        conn.close()
    if not rows:
        print("No operator accounts.")
        return
    print("id\tusername\tcreated")
    for operator_id, username, created_at in rows:
        print(f"{operator_id}\t{username}\t{created_at}")


def cmd_operators_keep(operator_id: int) -> None:
    """Keep one operator, then continue the single-operator migration.

    Writes ``auth.db.bak-YYYYMMDDTHHMMSSZ`` beside the database before any
    row is removed. The delete and the session cleanup commit together. The
    backup file is removed if that transaction does not commit.

    Args:
        operator_id: The account id to keep.

    Raises:
        SystemExit: When the database or the id is missing, or the update
            cannot be committed.
    """
    if operator_id < 1:
        print("No operator with that id.", file=sys.stderr)
        raise SystemExit(1)
    db_path = auth_db_path()
    if not db_path.is_file():
        print("No operator database was found.", file=sys.stderr)
        raise SystemExit(1)
    if not _operator_exists(db_path, operator_id):
        print("No operator with that id.", file=sys.stderr)
        raise SystemExit(1)

    backup_path = _backup_database(db_path)
    try:
        _keep_operator(db_path, operator_id)
    except Exception:
        backup_path.unlink(missing_ok=True)
        print(
            "The operator update could not be finished. No data was changed.",
            file=sys.stderr,
        )
        raise SystemExit(1) from None

    # Import after the delete so a paused migration is not logged for the
    # rows this command has just removed.
    from .auth_service import AuthService

    AuthService(db_path=db_path)
    print(f"Kept operator {operator_id}.")
    print(f"Backup: {backup_path}")
    print("One operator account remains. Open FlintTrade and choose Retry.")


def _operator_exists(db_path: Path, operator_id: int) -> bool:
    conn = sqlite3.connect(db_path)
    try:
        row = conn.execute(
            "SELECT 1 FROM account WHERE id = ?",
            (operator_id,),
        ).fetchone()
    finally:
        conn.close()
    return row is not None


def _backup_database(db_path: Path) -> Path:
    """Copy ``db_path`` to a timestamped file in the same directory."""
    stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    dest = db_path.with_name(f"{db_path.name}.bak-{stamp}")
    if dest.exists():
        stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%S%fZ")
        dest = db_path.with_name(f"{db_path.name}.bak-{stamp}")
    source = sqlite3.connect(db_path)
    target = sqlite3.connect(dest)
    try:
        source.backup(target)
    finally:
        target.close()
        source.close()
    try:
        dest.chmod(0o600)
    except OSError:
        pass
    return dest


def _keep_operator(db_path: Path, operator_id: int) -> None:
    conn = sqlite3.connect(db_path, isolation_level=None)
    try:
        conn.execute("PRAGMA busy_timeout = 5000")
        conn.execute("BEGIN IMMEDIATE")
        try:
            found = conn.execute(
                "SELECT 1 FROM account WHERE id = ?",
                (operator_id,),
            ).fetchone()
            if found is None:
                raise RuntimeError("operator disappeared before the update committed")
            removed = [
                int(row[0])
                for row in conn.execute(
                    "SELECT id FROM account WHERE id != ?",
                    (operator_id,),
                )
            ]
            _delete_operator_sessions(conn, removed)
            conn.execute("DELETE FROM account WHERE id != ?", (operator_id,))
            conn.execute("COMMIT")
        except Exception:
            conn.execute("ROLLBACK")
            raise
    finally:
        conn.close()


def _delete_operator_sessions(conn: sqlite3.Connection, removed_ids: list[int]) -> None:
    """Delete session rows that name a removed operator, in this transaction.

    ``account`` is removed by the caller. Login attempts are not stored
    against an operator, so they stay. A table is treated as session data
    when it has ``account_id``, ``operator_id``, or ``user_id``.
    """
    if not removed_ids:
        return
    placeholders = ",".join("?" for _ in removed_ids)
    tables = conn.execute(
        "SELECT name FROM sqlite_master WHERE type = 'table' AND name NOT LIKE 'sqlite_%'"
    ).fetchall()
    for (table_name,) in tables:
        if table_name == "account" or not _IDENTIFIER.fullmatch(str(table_name)):
            continue
        columns = [
            str(row[1])
            for row in conn.execute(f'PRAGMA table_info("{table_name}")')
        ]
        for column in _OPERATOR_REF_COLUMNS:
            if column not in columns:
                continue
            conn.execute(
                f'DELETE FROM "{table_name}" WHERE "{column}" IN ({placeholders})',
                removed_ids,
            )
