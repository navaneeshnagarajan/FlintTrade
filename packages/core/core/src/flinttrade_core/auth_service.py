# packages/core/core/src/auth_service.py
"""FlintTrade authentication service — single-user credential management.

Handles account setup (one-time), password verification, PIN quick-unlock,
TOTP 2FA, backup codes, and login attempt rate limiting.

Credentials stored in ~/.flinttrade/auth.db (SQLite):
- Password: argon2id hash
- PIN: PBKDF2-SHA256 hash
- TOTP secret: Fernet-encrypted (AES-128-CBC + HMAC-SHA256, key derived via PBKDF2)
- Backup codes: argon2id hashed (one-time use)

Usage::

    svc = AuthService()
    codes = svc.setup_account("alice", "alice@example.com", "StrongP@ss!", "123456")
    # Daily login:
    if svc.verify_password("StrongP@ss!") and svc.verify_totp("123456"):
        token = svc.create_session()
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import logging
import os
import secrets
import sqlite3
from typing import Any
import time
from datetime import datetime, timezone
from pathlib import Path

import argon2
import pyotp
from cryptography.fernet import Fernet, InvalidToken
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC

from flinttrade_core.db import open_sqlite

from .workspace import workspace_dir as _workspace_dir

logger = logging.getLogger("flinttrade.auth")

# Evaluated at import time — set FLINTTRADE_WORKSPACE_DIR *before* importing
# this module (pytest fixtures that use monkeypatch.setenv should scope at
# session level, or pass db_path explicitly to AuthService).
_DEFAULT_DB_PATH = _workspace_dir() / "auth.db"
_MAX_LOGIN_ATTEMPTS = 5
_LOCKOUT_DURATION_SECONDS = 900  # 15 minutes


_KDF_ITERATIONS: int = 390_000  # NIST-recommended minimum for PBKDF2-SHA256


def _derive_fernet_key(master: str, salt: bytes) -> Fernet:
    """Derive a Fernet key from the master password and salt via PBKDF2-HMAC-SHA256.

    Fernet requires a 32-byte URL-safe base64-encoded key. PBKDF2 derives
    the raw 32 bytes; we then base64-encode for Fernet.

    Returns:
        A ready-to-use :class:`~cryptography.fernet.Fernet` instance.
    """
    kdf = PBKDF2HMAC(
        algorithm=hashes.SHA256(),
        length=32,
        salt=salt,
        iterations=_KDF_ITERATIONS,
    )
    key = base64.urlsafe_b64encode(kdf.derive(master.encode("utf-8")))
    return Fernet(key)


class AuthService:
    """Single-user authentication service.

    Thread-safety: the SQLite connection is opened with
    ``check_same_thread=False`` and every write goes through a single
    :class:`threading.Lock` (``self._write_lock``). Reads are safe in
    WAL mode without the lock; writes must hold it so concurrent Flask
    request threads do not interleave statements mid-transaction.
    """

    def __init__(self, db_path: Path | str | None = None) -> None:
        import threading  # local to keep module import surface small

        self._db_path = Path(db_path) if db_path else _DEFAULT_DB_PATH
        self._db_path.parent.mkdir(parents=True, exist_ok=True)
        self._hasher = argon2.PasswordHasher(
            time_cost=3, memory_cost=65536, parallelism=4,
        )
        self._conn: sqlite3.Connection | None = None
        self._write_lock: threading.Lock = threading.Lock()
        self._init_db()

    @property
    def _db(self) -> sqlite3.Connection:
        if self._conn is None:
            # check_same_thread=False + per-write Lock — reads safe via WAL,
            # writes serialised so interleaving cannot corrupt transactions.
            self._conn = open_sqlite(str(self._db_path), durability="full")
            self._conn.row_factory = sqlite3.Row
        return self._conn

    # ------------------------------------------------------------------
    # Write helpers — always acquire the write lock so concurrent Flask
    # request threads don't race and half-apply transactions.
    # ------------------------------------------------------------------
    def _execute_locked(self, sql: str, params: Any = ()) -> Any:
        """Execute a single write under the write lock and commit."""
        with self._write_lock:
            cur = self._db.execute(sql, params)
            self._db.commit()
            return cur

    def _executescript_locked(self, sql: str) -> None:
        """Execute a multi-statement script under the write lock and commit."""
        with self._write_lock:
            self._db.executescript(sql)
            self._db.commit()

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
                created_at TEXT NOT NULL,
                password_changed_at REAL NOT NULL DEFAULT 0
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
        # Idempotent migration — older DBs predate the password_changed_at
        # column. ADD COLUMN is cheap and avoids a destructive rebuild.
        try:
            self._db.execute(
                "ALTER TABLE account ADD COLUMN password_changed_at REAL NOT NULL DEFAULT 0"
            )
        except sqlite3.OperationalError:
            # Column already exists — fresh installs hit this on the
            # CREATE TABLE path above.
            pass
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
        pin: str = "",
    ) -> list[str]:
        """Create the single-user account. Returns 8 backup codes.

        Args:
            pin: Optional 6-digit PIN for quick unlock. Empty string to skip.

        Raises:
            ValueError: If password too weak or PIN invalid (when provided).
            RuntimeError: If account already exists.
        """
        if self.is_setup():
            raise RuntimeError("Account already set up")

        # Validate password strength (basic — zxcvbn on frontend)
        if len(password) < 8:
            raise ValueError("Password too weak — minimum 8 characters")

        # Validate PIN (optional — empty string means no PIN)
        if pin and not (pin.isdigit() and len(pin) == 6):
            raise ValueError("PIN must be exactly 6 digits")

        # Hash password with argon2id
        password_hash = self._hasher.hash(password)

        # Hash PIN with PBKDF2 (or store empty marker if no PIN set)
        if pin:
            pin_salt = os.urandom(16)
            pin_hash_bytes = hashlib.pbkdf2_hmac("sha256", pin.encode(), pin_salt, 390_000)
            pin_hash = pin_salt.hex() + ":" + pin_hash_bytes.hex()
        else:
            pin_salt = os.urandom(16)
            pin_hash = ""  # Empty = no PIN configured

        # Generate TOTP secret and encrypt it with Fernet
        totp_secret = pyotp.random_base32()
        totp_salt = os.urandom(16)
        fernet = _derive_fernet_key(password, totp_salt)
        encrypted = fernet.encrypt(totp_secret.encode("utf-8"))

        # Generate 8 backup codes — insert all rows + account under a
        # single write-lock acquisition so a concurrent reader never sees
        # a half-populated row set.
        backup_codes: list[str] = []
        with self._write_lock:
            for _ in range(8):
                code = secrets.token_hex(4).upper()  # 8-char hex
                backup_codes.append(code)
                code_hash = self._hasher.hash(code)
                self._db.execute(
                    "INSERT INTO backup_codes (code_hash, used) VALUES (?, 0)",
                    [code_hash],
                )
            # Store account in the same transaction.
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
        """Verify password and cache decrypted TOTP secret. Returns False if locked out."""
        if self.is_locked():
            return False

        row = self._db.execute("SELECT password_hash FROM account WHERE id = 1").fetchone()
        if not row:
            return False

        try:
            result = self._hasher.verify(row["password_hash"], password)
            self._record_attempt(success=result)
            if result:
                self._decrypt_and_cache_totp(password)
            return result
        except argon2.exceptions.VerifyMismatchError:
            self._record_attempt(success=False)
            return False

    def _decrypt_and_cache_totp(self, password: str) -> None:
        """Decrypt the TOTP secret from the database and cache it in memory.

        Falls back gracefully if the ciphertext uses the legacy XOR format
        (pre-Fernet) — attempts XOR decryption as a migration path, then
        re-encrypts with Fernet and updates the database. The XOR fallback
        is gated behind the ``FLINTTRADE_ALLOW_LEGACY_TOTP`` environment
        flag. After an installation has been migrated once (which happens
        automatically during the very next successful login) the flag can
        be removed; it will default to off in a future release.
        """
        row = self._db.execute(
            "SELECT totp_secret_encrypted, totp_salt FROM account WHERE id = 1"
        ).fetchone()
        if not row:
            return

        salt = bytes(row["totp_salt"])
        encrypted = bytes(row["totp_secret_encrypted"])
        fernet = _derive_fernet_key(password, salt)

        try:
            plaintext = fernet.decrypt(encrypted).decode("utf-8")
            self._totp_secret_cache = plaintext
        except InvalidToken:
            if not self._legacy_totp_fallback_enabled():
                logger.warning(
                    "Failed to decrypt TOTP secret and legacy XOR fallback is disabled. "
                    "Set FLINTTRADE_ALLOW_LEGACY_TOTP=1 once to migrate pre-Fernet installs."
                )
                return
            legacy_secret = self._try_legacy_xor_decrypt(password, salt, encrypted)
            if legacy_secret:
                self._totp_secret_cache = legacy_secret
                # Re-encrypt with Fernet and update the database
                self._migrate_totp_to_fernet(password, legacy_secret)
                logger.info("Migrated TOTP secret from legacy XOR to Fernet encryption")
            else:
                logger.warning("Failed to decrypt TOTP secret — neither Fernet nor legacy XOR succeeded")

    @staticmethod
    def _legacy_totp_fallback_enabled() -> bool:
        """Return True when the one-shot XOR-to-Fernet migration is permitted.

        Controlled by ``FLINTTRADE_ALLOW_LEGACY_TOTP`` — any truthy value
        (``1``, ``true``, ``yes``) enables the fallback. Defaulting off
        prevents a stolen DB from being downgraded back to XOR.
        """
        val = os.environ.get("FLINTTRADE_ALLOW_LEGACY_TOTP", "").strip().lower()
        return val in {"1", "true", "yes", "on"}

    @staticmethod
    def _try_legacy_xor_decrypt(password: str, salt: bytes, encrypted: bytes) -> str | None:
        """Attempt to decrypt a TOTP secret using the old XOR stream cipher.

        Returns the plaintext secret if it looks like a valid base32 TOTP
        secret, or None if decryption produced garbage.
        """
        import re
        legacy_key = hashlib.pbkdf2_hmac("sha256", password.encode(), salt, 390_000, dklen=32)
        key_stream = hashlib.sha256(legacy_key).digest()
        while len(key_stream) < len(encrypted):
            key_stream += hashlib.sha256(key_stream).digest()
        decrypted = bytes(a ^ b for a, b in zip(encrypted, key_stream[:len(encrypted)]))
        try:
            plaintext = decrypted.decode("utf-8")
            # TOTP secrets are base32-encoded (A-Z, 2-7, =)
            if re.fullmatch(r"[A-Z2-7=]+", plaintext) and len(plaintext) >= 16:
                return plaintext
        except UnicodeDecodeError:
            pass
        return None

    def _migrate_totp_to_fernet(self, password: str, totp_secret: str) -> None:
        """Re-encrypt TOTP secret with Fernet and update the database row."""
        new_salt = os.urandom(16)
        fernet = _derive_fernet_key(password, new_salt)
        new_encrypted = fernet.encrypt(totp_secret.encode("utf-8"))
        self._db.execute(
            "UPDATE account SET totp_secret_encrypted = ?, totp_salt = ? WHERE id = 1",
            [new_encrypted, new_salt],
        )
        self._db.commit()

    def has_pin(self) -> bool:
        """Check if a PIN was configured during setup."""
        row = self._db.execute("SELECT pin_hash FROM account WHERE id = 1").fetchone()
        return bool(row and row["pin_hash"])

    def verify_pin(self, pin: str) -> bool:
        """Verify 6-digit PIN for quick unlock. Returns False if no PIN configured."""
        if self.is_locked():
            return False

        row = self._db.execute("SELECT pin_hash FROM account WHERE id = 1").fetchone()
        if not row or not row["pin_hash"]:
            return False  # No PIN configured

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
        """Verify and consume a one-time backup code.

        The read-then-update sequence is serialised with the write lock
        so a concurrent request cannot double-consume the same code.
        """
        with self._write_lock:
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
        with self._write_lock:
            self._db.execute(
                "INSERT INTO login_attempts (timestamp, success) VALUES (?, ?)",
                [time.time(), int(success)],
            )
            self._db.commit()

    def get_email(self) -> str | None:
        """Return the account email, or None if no account is set up."""
        row = self._db.execute("SELECT email FROM account WHERE id = 1").fetchone()
        if not row:
            return None
        return row["email"]

    def update_password(self, username: str, new_password: str) -> bool:
        """Update the password for *username*.

        Stamps ``password_changed_at`` with the current epoch so that
        previously issued JWTs (whose ``iat`` predates the change) can be
        rejected at decode time — mirrors the upstream OpenAlgo v2.0.0.7
        session-invalidation behaviour. Without this stamp a leaked token
        would remain valid until natural expiry.

        Args:
            username: Must match the stored username.
            new_password: The new password (must pass strength check).

        Returns:
            True on success, False if no matching account.

        Raises:
            ValueError: If the new password is too weak.
        """
        if len(new_password) < 8:
            raise ValueError("Password too weak — minimum 8 characters")

        row = self._db.execute(
            "SELECT username FROM account WHERE id = 1"
        ).fetchone()
        if not row or row["username"] != username:
            return False

        password_hash = self._hasher.hash(new_password)
        with self._write_lock:
            self._db.execute(
                "UPDATE account SET password_hash = ?, password_changed_at = ? WHERE id = 1",
                [password_hash, time.time()],
            )
            self._db.commit()
        return True

    def get_password_changed_at(self) -> float:
        """Return the epoch timestamp of the most recent password change.

        Returns 0.0 when no account exists or when the column is unset
        (older DBs migrated in-place default to 0). Callers compare a JWT's
        ``iat`` against this value: any token with ``iat`` strictly less
        than the returned epoch was issued before the password change and
        MUST be rejected.
        """
        row = self._db.execute(
            "SELECT password_changed_at FROM account WHERE id = 1"
        ).fetchone()
        if not row:
            return 0.0
        try:
            return float(row["password_changed_at"] or 0.0)
        except (TypeError, ValueError):
            return 0.0

    def reset_account(self, password: str) -> bool:
        """Delete the single-user account entirely. Requires password confirmation.

        Intended for pre-login "start over" flows in the setup wizard: a user
        who has just created an account but wants to change username or email
        (either typed wrong, or changed their mind) can wipe the account and
        re-run setup from scratch.

        Wipes:
          * the ``account`` row (credentials, TOTP secret, salts)
          * all backup codes
          * all login attempts (so the fresh setup starts clean)

        Also clears the in-memory TOTP cache and resets any related state.

        Returns:
            True on successful reset; False if the password did not verify
            (so the caller can return 401 without exposing which field failed).
        """
        if not self.verify_password(password):
            return False

        with self._write_lock:
            self._db.execute("DELETE FROM account WHERE id = 1")
            self._db.execute("DELETE FROM backup_codes")
            self._db.execute("DELETE FROM login_attempts")
            self._db.commit()

        if hasattr(self, "_totp_secret_cache"):
            delattr(self, "_totp_secret_cache")

        logger.info("Account fully reset via setup-wizard escape hatch")
        return True

    def regenerate_totp(self, password: str) -> tuple[str, list[str]] | None:
        """Issue a fresh TOTP secret + backup codes for the existing account.

        Intended for pre-login "reset 2FA" flows in the setup wizard: a user
        who scanned the QR into the wrong device, lost their phone, or wants
        to start the 2FA step over before ever signing in. Requires password
        confirmation so a shoulder-surfer cannot invalidate 2FA.

        The encrypted TOTP secret is derived from the verified password +
        a fresh 16-byte salt, matching the format used by ``setup_account``.
        Old backup codes are invalidated and 8 new ones are generated.

        Returns:
            ``(provisioning_uri, backup_codes)`` on success, or ``None`` if
            the password did not verify or no account exists.
        """
        if not self.verify_password(password):
            return None
        row = self._db.execute(
            "SELECT 1 FROM account WHERE id = 1"
        ).fetchone()
        if not row:
            return None

        totp_secret = pyotp.random_base32()
        totp_salt = os.urandom(16)
        fernet = _derive_fernet_key(password, totp_salt)
        encrypted = fernet.encrypt(totp_secret.encode("utf-8"))

        backup_codes: list[str] = []
        with self._write_lock:
            self._db.execute(
                "UPDATE account SET totp_secret_encrypted = ?, totp_salt = ? WHERE id = 1",
                [encrypted, totp_salt],
            )
            self._db.execute("DELETE FROM backup_codes")
            for _ in range(8):
                code = secrets.token_hex(4).upper()
                backup_codes.append(code)
                code_hash = self._hasher.hash(code)
                self._db.execute(
                    "INSERT INTO backup_codes (code_hash, used) VALUES (?, 0)",
                    [code_hash],
                )
            self._db.commit()

        self._totp_secret_cache = totp_secret
        return (self.get_totp_provisioning_uri(), backup_codes)

    def close(self) -> None:
        if self._conn:
            self._conn.close()
            self._conn = None
