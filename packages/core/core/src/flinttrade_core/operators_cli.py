"""Operator recovery commands for a paused single-operator update.

``flinttrade operators list`` prints id, username, and created time.
``flinttrade operators keep <id>`` copies the database beside itself, removes
every other operator row and session rows that name those operators,
renumbers the kept operator to id 1, then runs the single-operator migration.
"""

from __future__ import annotations

import os
import re
import sqlite3
import sys
from datetime import UTC, datetime
from pathlib import Path

from .secure_file import harden
from .workspace import workspace_dir

_IDENTIFIER = re.compile(r"[A-Za-z_][A-Za-z0-9_]*")
_OPERATOR_REF_COLUMNS = ("account_id", "operator_id", "user_id")
# Sessions, defaults, and foreign keys address the single operator as id 1.
_CANONICAL_OPERATOR_ID = 1


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
        rows = conn.execute("SELECT id, username, created_at FROM account ORDER BY id").fetchall()
    finally:
        conn.close()
    if not rows:
        print("No operator accounts.")
        return
    print("id\tusername\tcreated")
    for operator_id, username, created_at in rows:
        print(f"{operator_id}\t{username}\t{created_at}")


def cmd_operators_keep(operator_id: int, *, assume_yes: bool = False) -> None:
    """Keep one operator, then continue the single-operator migration.

    Prints the account that stays and the accounts that would be removed,
    then asks before any file is written. ``assume_yes`` skips that question.
    Without a terminal, the command stops unless ``assume_yes`` is set.

    Writes ``auth.db.bak-YYYYMMDDTHHMMSSZ`` beside the database before any
    row is removed. The file is owner-only. The delete, the session
    cleanup, and the renumber to id 1 commit together. The backup file is
    removed if that transaction does not commit. Repeating the command for
    the stored id 1 leaves that operator's rows in place.

    Args:
        operator_id: The account id to keep.
        assume_yes: Skip the confirmation prompt.

    Raises:
        SystemExit: When the database or the id is missing, the operator
            declines, there is no terminal, or the update cannot be committed.
    """
    if operator_id < 1:
        print("No operator with that id.", file=sys.stderr)
        raise SystemExit(1)
    db_path = auth_db_path()
    if not db_path.is_file():
        print("No operator database was found.", file=sys.stderr)
        raise SystemExit(1)
    operators = _operator_rows(db_path)
    kept = next((row for row in operators if row[0] == operator_id), None)
    if kept is None:
        print("No operator with that id.", file=sys.stderr)
        raise SystemExit(1)
    removed = [row for row in operators if row[0] != operator_id]
    print(f"Keeping {kept[0]} {kept[1]}")
    for other_id, username in removed:
        print(f"Removing {other_id} {username}")
    if not _confirm_removal(len(removed), assume_yes=assume_yes):
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
    print("This backup contains login secrets. Keep it private and delete it once FlintTrade works again.")


def _confirm_removal(remove_count: int, *, assume_yes: bool) -> bool:
    """Ask before deleting. Only ``y`` or ``yes`` continues.

    Returns:
        ``True`` when the operator confirmed, or ``assume_yes`` is set.
    """
    if assume_yes:
        return True
    if not sys.stdin.isatty():
        print(
            "No data was changed. A terminal is required, or pass --yes.",
            file=sys.stderr,
        )
        return False
    print(f"Remove {remove_count} other operator account(s)? [y/N]")
    try:
        answer = input().strip().lower()
    except EOFError:
        answer = ""
    if answer in {"y", "yes"}:
        return True
    print("No data was changed.", file=sys.stderr)
    return False


def _operator_rows(db_path: Path) -> list[tuple[int, str]]:
    conn = sqlite3.connect(db_path)
    try:
        rows = conn.execute("SELECT id, username FROM account ORDER BY id").fetchall()
    finally:
        conn.close()
    return [(int(row[0]), str(row[1])) for row in rows]


def _backup_database(db_path: Path) -> Path:
    """Copy ``db_path`` to an owner-only timestamped file beside it.

    The file is created with mode ``0600`` before the database bytes are
    copied. :func:`flinttrade_core.secure_file.harden` then applies that mode
    again on POSIX and the owner-only ACL on Windows.
    """
    stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    dest = db_path.with_name(f"{db_path.name}.bak-{stamp}")
    if dest.exists():
        stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%S%fZ")
        dest = db_path.with_name(f"{db_path.name}.bak-{stamp}")
    try:
        descriptor = os.open(dest, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
        os.close(descriptor)
        harden(dest)
        source = sqlite3.connect(db_path)
        target = sqlite3.connect(dest)
        try:
            source.backup(target)
        finally:
            target.close()
            source.close()
        harden(dest)
    except Exception:
        dest.unlink(missing_ok=True)
        raise
    return dest


def _keep_operator(db_path: Path, operator_id: int) -> None:
    conn = sqlite3.connect(db_path, isolation_level=None)
    try:
        conn.execute("PRAGMA busy_timeout = 5000")
        conn.execute("BEGIN IMMEDIATE")
        # Check foreign keys at COMMIT so a mid-update reference still rolls
        # back with the rest of the transaction when they are enabled.
        conn.execute("PRAGMA defer_foreign_keys = ON")
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
            _renumber_operator(conn, operator_id, _CANONICAL_OPERATOR_ID)
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
    tables = conn.execute("SELECT name FROM sqlite_master WHERE type = 'table' AND name NOT LIKE 'sqlite_%'").fetchall()
    for (table_name,) in tables:
        if table_name == "account" or not _IDENTIFIER.fullmatch(str(table_name)):
            continue
        columns = [str(row[1]) for row in conn.execute(f'PRAGMA table_info("{table_name}")')]
        for column in _OPERATOR_REF_COLUMNS:
            if column not in columns:
                continue
            conn.execute(
                f'DELETE FROM "{table_name}" WHERE "{column}" IN ({placeholders})',
                removed_ids,
            )


def _renumber_operator(conn: sqlite3.Connection, operator_id: int, canonical_id: int) -> None:
    """Store the kept operator as ``canonical_id`` inside this transaction.

    Already-canonical rows are left unchanged, so keeping id 1 again is a
    no-op. Every ``account_id``, ``operator_id``, and ``user_id`` that names
    the kept operator moves with the account row. A failure here raises and
    the caller rolls the whole transaction back.
    """
    if operator_id == canonical_id:
        return
    tables = conn.execute("SELECT name FROM sqlite_master WHERE type = 'table' AND name NOT LIKE 'sqlite_%'").fetchall()
    for (table_name,) in tables:
        if table_name == "account" or not _IDENTIFIER.fullmatch(str(table_name)):
            continue
        columns = [str(row[1]) for row in conn.execute(f'PRAGMA table_info("{table_name}")')]
        for column in _OPERATOR_REF_COLUMNS:
            if column not in columns:
                continue
            conn.execute(
                f'UPDATE "{table_name}" SET "{column}" = ? WHERE "{column}" = ?',
                (canonical_id, operator_id),
            )
    updated = conn.execute(
        "UPDATE account SET id = ? WHERE id = ?",
        (canonical_id, operator_id),
    )
    if updated.rowcount != 1:
        raise RuntimeError("operator disappeared before the update committed")
