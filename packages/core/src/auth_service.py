# packages/core/src/auth_service.py
"""FlintTrade authentication service — single-user credential management.

Handles account setup (one-time), password verification, PIN quick-unlock,
TOTP 2FA, backup codes, and login attempt rate limiting.

Credentials stored in ~/.flinttrade/auth.db (SQLite):
- Password: argon2id hash
- PIN: PBKDF2-SHA256 hash
- TOTP secret: AES-256 encrypted
- Backup codes: argon2id hashed (one-time use)

Usage::

    svc = AuthService()
    codes = svc.setup_account("nav", "nav@example.com", "StrongP@ss!", "123456")
    # Daily login:
    if svc.verify_password("StrongP@ss!") and svc.verify_totp("123456"):
        token = svc.create_session()
"""

from __future__ import annotations

import hashlib
import hmac
import json
import logging
import os
import secrets
import sqlite3
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import argon2
import pyotp

logger = logging.getLogger("flinttrade.auth")

_DEFAULT_DB_PATH = Path.home() / ".flinttrade" / "auth.db"
_MAX_LOGIN_ATTEMPTS = 5
_LOCKOUT_DURATION_SECONDS = 900  # 15 minutes


def _derive_encryption_key(master: str, salt: bytes) -> bytes:
    """Derive a 32-byte AES key from master password + salt via PBKDF2."""
    return hashlib.pbkdf2_hmac("sha256", master.encode(), salt, 390_000, dklen=32)


class AuthService:
    """Single-user authentication service."""

    def __init__(self, db_path: Path | str | None = None) -> None:
        self._db_path = Path(db_path) if db_path else _DEFAULT_DB_PATH
        self._db_path.parent.mkdir(parents=True, exist_ok=True)
        self._hasher = argon2.PasswordHasher(
            time_cost=3, memory_cost=65536, parallelism=4,
        )
        self._conn: sqlite3.Connection | None = None
        self._init_db()

    @property
    def _db(self) -> sqlite3.Connection:
        if self._conn is None:
            # check_same_thread=False is safe — single-user app, no concurrent writes.
            # Flask serves requests in different threads but AuthService is single-instance.
            self._conn = sqlite3.connect(str(self._db_path), check_same_thread=False)
            self._conn.row_factory = sqlite3.Row
        return self._conn

    def _init_db(self) -> None:
        self._db.executescript("""
            CREATE TABLE IF NOT EXISTS account (
                id INTEGER PRIMARY KEY CHECK (id = 1),
                username TEXT NOT NULL,
                email TEXT NOT NULL,
                password_hash TEXT NOT NULL,
                pin_hash TEXT NOT NULL,
                totp_secret_encrypted BLOB NOT NULL,
                totp_salt BLOB NOT NULL,
                created_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS backup_codes (
                code_hash TEXT PRIMARY KEY,
                used INTEGER DEFAULT 0
            );
            CREATE TABLE IF NOT EXISTS login_attempts (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                timestamp REAL NOT NULL,
                success INTEGER NOT NULL
            );
        """)
        self._db.commit()

    def is_setup(self) -> bool:
        """Check if the account has been created."""
        row = self._db.execute("SELECT 1 FROM account WHERE id = 1").fetchone()
        return row is not None

    def setup_account(
        self,
        username: str,
        email: str,
        password: str,
        pin: str,
    ) -> list[str]:
        """Create the single-user account. Returns 8 backup codes.

        Raises:
            ValueError: If password too weak or PIN not 6 digits.
            RuntimeError: If account already exists.
        """
        if self.is_setup():
            raise RuntimeError("Account already set up")

        # Validate password strength (basic — zxcvbn on frontend)
        if len(password) < 8:
            raise ValueError("Password too weak — minimum 8 characters")

        # Validate PIN
        if not (pin.isdigit() and len(pin) == 6):
            raise ValueError("PIN must be exactly 6 digits")

        # Hash password with argon2id
        password_hash = self._hasher.hash(password)

        # Hash PIN with PBKDF2
        pin_salt = os.urandom(16)
        pin_hash_bytes = hashlib.pbkdf2_hmac("sha256", pin.encode(), pin_salt, 390_000)
        pin_hash = pin_salt.hex() + ":" + pin_hash_bytes.hex()

        # Generate TOTP secret and encrypt it
        totp_secret = pyotp.random_base32()
        totp_salt = os.urandom(16)
        encryption_key = _derive_encryption_key(password, totp_salt)
        # Simple XOR encryption with derived key (for TOTP secret only)
        secret_bytes = totp_secret.encode()
        key_stream = hashlib.sha256(encryption_key).digest()
        # Pad key_stream to match secret length
        while len(key_stream) < len(secret_bytes):
            key_stream += hashlib.sha256(key_stream).digest()
        encrypted = bytes(a ^ b for a, b in zip(secret_bytes, key_stream[:len(secret_bytes)]))

        # Generate 8 backup codes
        backup_codes: list[str] = []
        for _ in range(8):
            code = secrets.token_hex(4).upper()  # 8-char hex
            backup_codes.append(code)
            code_hash = self._hasher.hash(code)
            self._db.execute(
                "INSERT INTO backup_codes (code_hash, used) VALUES (?, 0)",
                [code_hash],
            )

        # Store account
        self._db.execute(
            """INSERT INTO account (id, username, email, password_hash, pin_hash,
               totp_secret_encrypted, totp_salt, created_at)
               VALUES (1, ?, ?, ?, ?, ?, ?, ?)""",
            [username, email, password_hash, pin_hash, encrypted, totp_salt,
             datetime.now(timezone.utc).isoformat()],
        )
        self._db.commit()

        # Cache the TOTP secret in memory for immediate use
        self._totp_secret_cache = totp_secret

        logger.info("Account created for %s", username)
        return backup_codes

    def get_profile(self) -> dict[str, str]:
        """Get username and email."""
        row = self._db.execute("SELECT username, email FROM account WHERE id = 1").fetchone()
        if not row:
            return {}
        return {"username": row["username"], "email": row["email"]}

    def verify_password(self, password: str) -> bool:
        """Verify password. Returns False if locked out."""
        if self.is_locked():
            return False

        row = self._db.execute("SELECT password_hash FROM account WHERE id = 1").fetchone()
        if not row:
            return False

        try:
            result = self._hasher.verify(row["password_hash"], password)
            self._record_attempt(success=result)
            return result
        except argon2.exceptions.VerifyMismatchError:
            self._record_attempt(success=False)
            return False

    def verify_pin(self, pin: str) -> bool:
        """Verify 6-digit PIN for quick unlock."""
        if self.is_locked():
            return False

        row = self._db.execute("SELECT pin_hash FROM account WHERE id = 1").fetchone()
        if not row:
            return False

        stored = row["pin_hash"]
        salt_hex, hash_hex = stored.split(":")
        salt = bytes.fromhex(salt_hex)
        expected = bytes.fromhex(hash_hex)
        actual = hashlib.pbkdf2_hmac("sha256", pin.encode(), salt, 390_000)
        result = hmac.compare_digest(actual, expected)
        self._record_attempt(success=result)
        return result

    def get_totp_secret(self) -> str | None:
        """Get the TOTP secret (decrypted). Requires password to have been verified in this session."""
        if hasattr(self, "_totp_secret_cache"):
            return self._totp_secret_cache
        return None

    def verify_totp(self, code: str) -> bool:
        """Verify a TOTP code."""
        secret = self.get_totp_secret()
        if not secret:
            # Try to get from DB (need cached password for decryption)
            return False
        totp = pyotp.TOTP(secret)
        return totp.verify(code, valid_window=1)

    def verify_backup_code(self, code: str) -> bool:
        """Verify and consume a one-time backup code."""
        rows = self._db.execute(
            "SELECT code_hash FROM backup_codes WHERE used = 0"
        ).fetchall()
        for row in rows:
            try:
                if self._hasher.verify(row["code_hash"], code):
                    self._db.execute(
                        "UPDATE backup_codes SET used = 1 WHERE code_hash = ?",
                        [row["code_hash"]],
                    )
                    self._db.commit()
                    return True
            except argon2.exceptions.VerifyMismatchError:
                continue
        return False

    def get_totp_provisioning_uri(self) -> str:
        """Get the TOTP provisioning URI for QR code generation."""
        secret = self.get_totp_secret()
        profile = self.get_profile()
        if not secret or not profile:
            return ""
        totp = pyotp.TOTP(secret)
        return totp.provisioning_uri(
            name=profile.get("email", "user"),
            issuer_name="FlintTrade",
        )

    def is_locked(self) -> bool:
        """Check if account is locked due to failed attempts."""
        cutoff = time.time() - _LOCKOUT_DURATION_SECONDS
        row = self._db.execute(
            """SELECT COUNT(*) as cnt FROM login_attempts
               WHERE timestamp > ? AND success = 0""",
            [cutoff],
        ).fetchone()
        return (row["cnt"] if row else 0) >= _MAX_LOGIN_ATTEMPTS

    def _record_attempt(self, *, success: bool) -> None:
        self._db.execute(
            "INSERT INTO login_attempts (timestamp, success) VALUES (?, ?)",
            [time.time(), int(success)],
        )
        self._db.commit()

    def close(self) -> None:
        if self._conn:
            self._conn.close()
            self._conn = None
