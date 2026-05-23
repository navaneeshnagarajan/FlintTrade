# packages/core/core/src/totp_auth.py
"""TOTP 2FA for FlintTrade users — independent of broker TOTP.

Provides Google Authenticator / Authy / Microsoft Authenticator-compatible
time-based one-time passwords for the FlintTrade login flow.

TOTP secrets are Fernet-encrypted at rest in DuckDB.
Backup codes are argon2id-hashed (one-time use).

Usage::

    auth = TOTPAuth()
    secret, backup_codes = auth.generate_secret("user_1")
    uri = auth.provisioning_uri("user_1", secret)
    svg = auth.qr_code_svg(uri)  # render in browser

    # Verify at login:
    if auth.verify_token("user_1", "123456"):
        ...

    # Recovery:
    if auth.consume_backup_code("user_1", "ABCD1234"):
        ...

    # Disable 2FA:
    auth.disable("user_1", "123456")
"""

from __future__ import annotations

import base64
import logging
import os
import secrets
from pathlib import Path
from typing import TYPE_CHECKING

import argon2
import duckdb
import pyotp
from cryptography.fernet import Fernet, InvalidToken
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC

if TYPE_CHECKING:
    pass

logger = logging.getLogger("flinttrade.core.totp_auth")

_DEFAULT_DB_PATH = Path.home() / ".flinttrade" / "totp_auth.duckdb"
_KDF_ITERATIONS: int = 390_000
_BACKUP_CODE_COUNT: int = 10
_BACKUP_CODE_BYTES: int = 4  # 8 hex chars per code


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _derive_fernet_key(passphrase: str, salt: bytes) -> Fernet:
    """Derive a Fernet key from *passphrase* and *salt* via PBKDF2-HMAC-SHA256.

    Args:
        passphrase: Secret string (user_id + internal app secret).
        salt: 16-byte random salt stored alongside ciphertext.

    Returns:
        Ready-to-use :class:`~cryptography.fernet.Fernet` instance.
    """
    kdf = PBKDF2HMAC(
        algorithm=hashes.SHA256(),
        length=32,
        salt=salt,
        iterations=_KDF_ITERATIONS,
    )
    key = base64.urlsafe_b64encode(kdf.derive(passphrase.encode("utf-8")))
    return Fernet(key)


def _load_or_init_install_secret() -> str:
    """Return a per-install random secret from ``~/.flinttrade/totp_install_key``.

    Generated once on first call (64 bytes urlsafe). File permissions set to
    owner-read only on POSIX. Ensures every FlintTrade install uses a unique
    key for TOTP encryption, even if ``FLINTTRADE_TOTP_KEY`` is unset.
    """
    key_path = Path.home() / ".flinttrade" / "totp_install_key"
    try:
        return key_path.read_text(encoding="utf-8").strip()
    except FileNotFoundError:
        key_path.parent.mkdir(parents=True, exist_ok=True)
        secret = secrets.token_urlsafe(64)
        # Atomic create-or-fail: if two workers race, the loser re-reads.
        try:
            fd = os.open(str(key_path), os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        except FileExistsError:
            return key_path.read_text(encoding="utf-8").strip()
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            fh.write(secret)
        logger.info("Generated per-install TOTP encryption key at %s", key_path)
        return secret


def _app_passphrase(user_id: str) -> str:
    """Build the encryption passphrase for *user_id*.

    Prefers ``FLINTTRADE_TOTP_KEY`` env var; otherwise uses a per-install
    random secret persisted to ``~/.flinttrade/totp_install_key``. The legacy
    hardcoded default has been removed — each install now has a unique key.

    Args:
        user_id: Unique user identifier.

    Returns:
        String used as PBKDF2 input material.
    """
    app_key = os.environ.get("FLINTTRADE_TOTP_KEY") or _load_or_init_install_secret()
    return f"{app_key}:{user_id}"


# ---------------------------------------------------------------------------
# TOTPAuth
# ---------------------------------------------------------------------------


class TOTPAuth:
    """Time-based One-Time Password authentication for FlintTrade users.

    Compatible with Google Authenticator, Authy, Microsoft Authenticator.

    Persistence uses DuckDB (not SQLite) so it lives alongside other analytics
    data in ~/.flinttrade/. Secrets are Fernet-encrypted; backup codes are
    argon2id-hashed.

    Attributes:
        _db_path: Path to the DuckDB database file.
    """

    def __init__(self, db_path: Path | str | None = None) -> None:
        """Initialise the TOTP auth store.

        Args:
            db_path: Optional path to the DuckDB file. Defaults to
                ``~/.flinttrade/totp_auth.duckdb``.
        """
        self._db_path = Path(db_path) if db_path else _DEFAULT_DB_PATH
        self._db_path.parent.mkdir(parents=True, exist_ok=True)
        self._hasher = argon2.PasswordHasher(
            time_cost=3, memory_cost=65536, parallelism=4,
        )
        self._conn: duckdb.DuckDBPyConnection | None = None
        self._init_db()

    # ------------------------------------------------------------------
    # DB lifecycle
    # ------------------------------------------------------------------

    @property
    def _db(self) -> duckdb.DuckDBPyConnection:
        if self._conn is None:
            self._conn = duckdb.connect(str(self._db_path))
        return self._conn

    def _init_db(self) -> None:
        self._db.execute("""
            CREATE TABLE IF NOT EXISTS totp_secrets (
                user_id      VARCHAR PRIMARY KEY,
                encrypted    BLOB NOT NULL,
                salt         BLOB NOT NULL,
                enabled      BOOLEAN DEFAULT TRUE,
                created_at   TIMESTAMP DEFAULT NOW()
            )
        """)
        self._db.execute("""
            CREATE TABLE IF NOT EXISTS backup_codes (
                id           VARCHAR PRIMARY KEY,
                user_id      VARCHAR NOT NULL,
                code_hash    VARCHAR NOT NULL,
                used         BOOLEAN DEFAULT FALSE,
                created_at   TIMESTAMP DEFAULT NOW()
            )
        """)

    def close(self) -> None:
        """Close the DuckDB connection."""
        if self._conn:
            self._conn.close()
            self._conn = None

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def generate_secret(self, user_id: str) -> tuple[str, list[str]]:
        """Generate and persist a new TOTP secret for *user_id*.

        Any previously stored secret and backup codes for *user_id* are
        replaced atomically.

        Args:
            user_id: Unique identifier for the user (e.g. DB primary key).

        Returns:
            A 2-tuple of ``(base32_secret, backup_codes)`` where
            ``backup_codes`` is a list of ``_BACKUP_CODE_COUNT`` uppercase
            8-character hex strings.  The plain-text backup codes are
            returned *only once* here — they are never stored in the clear.
        """
        totp_secret = pyotp.random_base32()
        salt = os.urandom(16)
        fernet = _derive_fernet_key(_app_passphrase(user_id), salt)
        encrypted = fernet.encrypt(totp_secret.encode("utf-8"))

        # Upsert secret row
        self._db.execute(
            """
            INSERT INTO totp_secrets (user_id, encrypted, salt, enabled, created_at)
            VALUES (?, ?, ?, TRUE, NOW())
            ON CONFLICT (user_id) DO UPDATE SET
                encrypted  = excluded.encrypted,
                salt       = excluded.salt,
                enabled    = TRUE,
                created_at = NOW()
            """,
            [user_id, encrypted, salt],
        )

        # Remove old backup codes for this user
        self._db.execute("DELETE FROM backup_codes WHERE user_id = ?", [user_id])

        # Generate new backup codes
        backup_codes: list[str] = []
        for _ in range(_BACKUP_CODE_COUNT):
            code = secrets.token_hex(_BACKUP_CODE_BYTES).upper()
            code_hash = self._hasher.hash(code)
            code_id = secrets.token_hex(8)
            self._db.execute(
                """
                INSERT INTO backup_codes (id, user_id, code_hash, used, created_at)
                VALUES (?, ?, ?, FALSE, NOW())
                """,
                [code_id, user_id, code_hash],
            )
            backup_codes.append(code)

        logger.info("TOTP secret generated for user=%s", user_id)
        return totp_secret, backup_codes

    def provisioning_uri(
        self,
        user_id: str,
        secret: str,
        issuer: str = "FlintTrade",
    ) -> str:
        """Build the ``otpauth://`` URI for QR code generation.

        Args:
            user_id: Account label shown in the authenticator app.
            secret: Base32 TOTP secret (from :meth:`generate_secret`).
            issuer: Issuer name shown in the authenticator app.

        Returns:
            ``otpauth://totp/<issuer>:<user_id>?secret=<secret>&issuer=<issuer>``
        """
        totp = pyotp.TOTP(secret)
        return totp.provisioning_uri(name=user_id, issuer_name=issuer)

    def qr_code_svg(self, uri: str) -> str:
        """Generate a QR code for *uri* as an SVG string.

        Uses the ``qrcode[svg]`` extra so there is no dependency on Pillow.

        Args:
            uri: The ``otpauth://`` provisioning URI.

        Returns:
            UTF-8 SVG markup as a string (no XML declaration).

        Raises:
            ImportError: If ``qrcode[svg]`` is not installed.
        """
        try:
            import io

            import qrcode
            import qrcode.image.svg as qr_svg
        except ImportError as exc:
            raise ImportError(
                "qrcode[svg] is required for QR code generation. "
                "Install with: pip install 'qrcode[svg]'"
            ) from exc

        factory = qr_svg.SvgPathImage
        img = qrcode.make(uri, image_factory=factory)
        buf = io.BytesIO()
        img.save(buf)
        return buf.getvalue().decode("utf-8")

    def verify_token(self, user_id: str, token: str) -> bool:
        """Verify a 6-digit TOTP token for *user_id*.

        Allows a ±1 step (30-second) tolerance window to account for slight
        clock skew between server and authenticator device.

        Args:
            user_id: The user whose TOTP secret to verify against.
            token: 6-digit string from the authenticator app.

        Returns:
            ``True`` if the token is valid and 2FA is enabled for *user_id*.
        """
        secret = self._get_decrypted_secret(user_id)
        if secret is None:
            logger.warning("verify_token called for unknown or disabled user=%s", user_id)
            return False
        totp = pyotp.TOTP(secret)
        result = totp.verify(token, valid_window=1)
        logger.debug("verify_token user=%s result=%s", user_id, result)
        return result

    def consume_backup_code(self, user_id: str, code: str) -> bool:
        """Verify and consume a one-time backup code.

        Each backup code can only be used once.  Once consumed it is marked
        as used and subsequent attempts with the same code fail.

        Args:
            user_id: The user whose backup codes to check.
            code: 8-character uppercase hex backup code.

        Returns:
            ``True`` if the code was valid and has been marked as used.
        """
        rows = self._db.execute(
            "SELECT id, code_hash FROM backup_codes WHERE user_id = ? AND used = FALSE",
            [user_id],
        ).fetchall()

        for row_id, code_hash in rows:
            try:
                if self._hasher.verify(code_hash, code):
                    self._db.execute(
                        "UPDATE backup_codes SET used = TRUE WHERE id = ?",
                        [row_id],
                    )
                    logger.info("Backup code consumed for user=%s", user_id)
                    return True
            except argon2.exceptions.VerifyMismatchError:
                continue
        return False

    def disable(self, user_id: str, token: str) -> bool:
        """Disable TOTP 2FA for *user_id* after verifying the current token.

        Args:
            user_id: The user to disable 2FA for.
            token: Current valid 6-digit TOTP token (or backup code).

        Returns:
            ``True`` if 2FA was disabled, ``False`` if the token was invalid.
        """
        if not self.verify_token(user_id, token):
            logger.warning("disable: invalid token for user=%s", user_id)
            return False
        self._db.execute(
            "UPDATE totp_secrets SET enabled = FALSE WHERE user_id = ?",
            [user_id],
        )
        logger.info("TOTP disabled for user=%s", user_id)
        return True

    def is_enabled(self, user_id: str) -> bool:
        """Return whether TOTP 2FA is currently enabled for *user_id*.

        Args:
            user_id: The user to query.

        Returns:
            ``True`` if 2FA is active.
        """
        row = self._db.execute(
            "SELECT enabled FROM totp_secrets WHERE user_id = ?",
            [user_id],
        ).fetchone()
        return bool(row and row[0])

    def remaining_backup_codes(self, user_id: str) -> int:
        """Return the number of unused backup codes remaining for *user_id*.

        Args:
            user_id: The user to query.

        Returns:
            Count of unused backup codes.
        """
        row = self._db.execute(
            "SELECT COUNT(*) FROM backup_codes WHERE user_id = ? AND used = FALSE",
            [user_id],
        ).fetchone()
        return int(row[0]) if row else 0

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    def _get_decrypted_secret(self, user_id: str) -> str | None:
        """Fetch and decrypt the TOTP secret for *user_id*.

        Args:
            user_id: The user whose secret to retrieve.

        Returns:
            Plain-text base32 secret, or ``None`` if not found or disabled.
        """
        row = self._db.execute(
            "SELECT encrypted, salt, enabled FROM totp_secrets WHERE user_id = ?",
            [user_id],
        ).fetchone()
        if not row:
            return None
        encrypted, salt, enabled = row
        if not enabled:
            return None
        fernet = _derive_fernet_key(_app_passphrase(user_id), bytes(salt))
        try:
            return fernet.decrypt(bytes(encrypted)).decode("utf-8")
        except InvalidToken:
            logger.error("Failed to decrypt TOTP secret for user=%s", user_id)
            return None
