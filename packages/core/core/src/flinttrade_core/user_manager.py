# packages/core/core/src/user_manager.py
"""Multi-user management for FlintTrade.

Opt-in scaffold — when ``FLINTTRADE_MULTI_USER=1`` the platform switches
from single-user (AuthService) to multi-user mode.  The users table lives
in the same ``~/.flinttrade/auth.db`` SQLite database so there is no extra
dependency.

Schema::

    users(
        id          INTEGER PRIMARY KEY AUTOINCREMENT,
        username    TEXT UNIQUE NOT NULL,
        email       TEXT NOT NULL,
        password_hash TEXT NOT NULL,
        role        TEXT NOT NULL DEFAULT 'trader',   -- admin | trader | viewer
        is_active   INTEGER NOT NULL DEFAULT 1,
        created_at  TEXT NOT NULL,
        updated_at  TEXT NOT NULL
    )

Usage::

    mgr = UserManager(db_path="~/.flinttrade/auth.db")
    mgr.create_user("alice", "Str0ng!Pass", "alice@example.com", role="trader")
    assert mgr.verify_password("alice", "Str0ng!Pass")
"""

from __future__ import annotations

import logging
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

import argon2

from flinttrade_core.db import open_sqlite

logger = logging.getLogger("flinttrade.users")

_VALID_ROLES = {"admin", "trader", "viewer"}


class UserManager:
    """Multi-user management for FlintTrade."""

    def __init__(self, db_path: str | Path) -> None:
        """Initialise with SQLite user database.

        Args:
            db_path: Path to the SQLite database file.  The ``users`` table
                is created automatically if it does not exist.
        """
        self._db_path = Path(db_path)
        self._db_path.parent.mkdir(parents=True, exist_ok=True)
        self._hasher = argon2.PasswordHasher(
            time_cost=3, memory_cost=65536, parallelism=4,
        )
        self._conn: sqlite3.Connection | None = None
        self._init_db()

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    @property
    def _db(self) -> sqlite3.Connection:
        if self._conn is None:
            self._conn = open_sqlite(str(self._db_path), durability="full")
            self._conn.row_factory = sqlite3.Row
        return self._conn

    def _init_db(self) -> None:
        self._db.executescript("""
            CREATE TABLE IF NOT EXISTS users (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                username    TEXT UNIQUE NOT NULL,
                email       TEXT NOT NULL,
                password_hash TEXT NOT NULL,
                role        TEXT NOT NULL DEFAULT 'trader',
                is_active   INTEGER NOT NULL DEFAULT 1,
                created_at  TEXT NOT NULL,
                updated_at  TEXT NOT NULL
            );
        """)
        self._db.commit()

    @staticmethod
    def _row_to_dict(row: sqlite3.Row) -> dict:
        """Convert a sqlite3.Row to a plain dict, excluding password_hash."""
        return {
            "id": row["id"],
            "username": row["username"],
            "email": row["email"],
            "role": row["role"],
            "is_active": bool(row["is_active"]),
            "created_at": row["created_at"],
            "updated_at": row["updated_at"],
        }

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def create_user(
        self,
        username: str,
        password: str,
        email: str,
        role: str = "trader",
    ) -> dict:
        """Create a new user account.

        Args:
            username: Unique username (3-32 chars, alphanumeric + underscore).
            password: Password (minimum 8 characters).
            email: Email address.
            role: One of ``admin``, ``trader``, ``viewer``.

        Returns:
            User dict (without password_hash).

        Raises:
            ValueError: If validation fails (weak password, bad role, etc.).
            RuntimeError: If username already exists.
        """
        # Validate
        username = username.strip().lower()
        if not username or len(username) < 3 or len(username) > 32:
            raise ValueError("Username must be 3-32 characters")
        if not all(c.isalnum() or c == "_" for c in username):
            raise ValueError("Username may only contain letters, digits, and underscores")
        if len(password) < 8:
            raise ValueError("Password too weak — minimum 8 characters")
        if role not in _VALID_ROLES:
            raise ValueError(f"Invalid role: {role}. Must be one of {_VALID_ROLES}")
        if not email or "@" not in email:
            raise ValueError("Invalid email address")

        now = datetime.now(timezone.utc).isoformat()
        password_hash = self._hasher.hash(password)

        try:
            self._db.execute(
                """INSERT INTO users (username, email, password_hash, role, is_active, created_at, updated_at)
                   VALUES (?, ?, ?, ?, 1, ?, ?)""",
                [username, email.strip(), password_hash, role, now, now],
            )
            self._db.commit()
        except sqlite3.IntegrityError:
            raise RuntimeError(f"Username '{username}' already exists")

        logger.info("User created: %s (role=%s)", username, role)
        return self.get_user(username)  # type: ignore[return-value]

    def get_user(self, username: str) -> dict | None:
        """Get user by username.  Returns None if not found."""
        row = self._db.execute(
            "SELECT * FROM users WHERE username = ?", [username.strip().lower()],
        ).fetchone()
        if row is None:
            return None
        return self._row_to_dict(row)

    def list_users(self) -> list[dict]:
        """List all users (admin only — access control enforced at route level)."""
        rows = self._db.execute(
            "SELECT * FROM users ORDER BY created_at",
        ).fetchall()
        return [self._row_to_dict(r) for r in rows]

    def update_user(self, username: str, **kwargs: object) -> bool:
        """Update user fields.

        Allowed fields: ``email``, ``role``, ``is_active``.
        To change password, use a dedicated ``change_password`` flow.

        Returns:
            True if the user was found and updated, False otherwise.
        """
        allowed = {"email", "role", "is_active"}
        updates = {k: v for k, v in kwargs.items() if k in allowed}
        if not updates:
            return False

        if "role" in updates and updates["role"] not in _VALID_ROLES:
            raise ValueError(f"Invalid role: {updates['role']}")

        username = username.strip().lower()
        now = datetime.now(timezone.utc).isoformat()

        set_clause = ", ".join(f"{k} = ?" for k in updates)
        values = list(updates.values()) + [now, username]

        cursor = self._db.execute(
            f"UPDATE users SET {set_clause}, updated_at = ? WHERE username = ?",
            values,
        )
        self._db.commit()

        if cursor.rowcount == 0:
            return False

        logger.info("User updated: %s (%s)", username, list(updates.keys()))
        return True

    def delete_user(self, username: str) -> bool:
        """Soft-delete a user (sets is_active=0).

        Returns:
            True if the user was found and deactivated, False otherwise.
        """
        return self.update_user(username, is_active=False)

    def verify_password(self, username: str, password: str) -> bool:
        """Verify password against stored hash.

        Returns False if the user does not exist, is inactive, or
        the password does not match.
        """
        username = username.strip().lower()
        row = self._db.execute(
            "SELECT password_hash, is_active FROM users WHERE username = ?",
            [username],
        ).fetchone()
        if row is None:
            return False
        if not row["is_active"]:
            return False

        try:
            return self._hasher.verify(row["password_hash"], password)
        except argon2.exceptions.VerifyMismatchError:
            return False

    def close(self) -> None:
        """Close the database connection."""
        if self._conn:
            self._conn.close()
            self._conn = None
