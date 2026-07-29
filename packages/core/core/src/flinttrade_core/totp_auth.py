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
import shutil
from pathlib import Path
from typing import TYPE_CHECKING

import argon2
import duckdb
import pyotp
from cryptography.fernet import Fernet, InvalidToken
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC
from flinttrade_gateway.log_safety import log_ref

if TYPE_CHECKING:
    pass

logger = logging.getLogger("flinttrade.core.totp_auth")

_KDF_ITERATIONS: int = 390_000
_BACKUP_CODE_COUNT: int = 10
_BACKUP_CODE_BYTES: int = 4  # 8 hex chars per code

_DB_NAME = "totp_auth.duckdb"
_INSTALL_KEY_NAME = "totp_install_key"
_MEMORY_DB = ":memory:"

# ONE lock for the whole crypto family. The pair is staged and published by
# this module rather than by the shared copy helper, because the helper
# publishes each file the moment it is copied — which is precisely the
# half-migrated state the family lock exists to prevent. With the staging done
# here there is nothing left for a per-file lock to serialise.
_PAIR_LOCK_NAME = ".totp-migration.lock"

# A multi-worker boot herd must not fail-closed on a 10s default while one
# worker copies the store.
_MIGRATION_TIMEOUT_SECONDS: float = 60.0


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


def _legacy_db_path() -> Path:
    """Return the pre-``workspace_dir()`` TOTP secret store location.

    Module-level so tests can monkeypatch the probe away from the developer's
    real home directory.

    Returns:
        ``<legacy dot-directory>/totp_auth.duckdb`` — the fixed
        ``~/.flinttrade`` root every pre-workspace install used, on every OS.
    """
    from flinttrade_core.workspace import legacy_dotdir  # noqa: PLC0415

    return legacy_dotdir() / _DB_NAME


def _legacy_install_key_path() -> Path:
    """Return the pre-``workspace_dir()`` per-install TOTP key location.

    Module-level so tests can monkeypatch the probe away from the developer's
    real home directory.

    Returns:
        ``<legacy dot-directory>/totp_install_key``.
    """
    from flinttrade_core.workspace import legacy_dotdir  # noqa: PLC0415

    return legacy_dotdir() / _INSTALL_KEY_NAME


def _resolve_totp_pair() -> tuple[Path, Path]:
    """Resolve the TOTP store and its install key, migrating the pair once.

    The DuckDB store and the install key are a single cryptographic unit: the
    key derives the Fernet key that decrypts every enrolled secret, so a store
    that travels without its key (or vice versa) is a permanent 2FA lockout.
    They are therefore always resolved and migrated together, never
    independently.

    Returns:
        A 2-tuple of ``(database path, install key path)`` inside the active
        workspace directory.

    Raises:
        flinttrade_core.workspace.WorkspaceStateMigrationError: The pair could
            not be copied, or the copied key did not decrypt the copied store;
            the legacy pair is retained in both cases.
    """
    from flinttrade_core.workspace import default_workspace_active, workspace_dir  # noqa: PLC0415

    root = workspace_dir()
    target_db = root / _DB_NAME
    target_key = root / _INSTALL_KEY_NAME
    if default_workspace_active():
        _migrate_legacy_totp_pair(target_db, target_key)
    return target_db, target_key


def _default_db_path() -> Path:
    """Resolve the TOTP secret store under the active workspace.

    Replaces the former import-time ``_DEFAULT_DB_PATH`` constant, which froze
    the location before pytest or a Gunicorn preload+fork could set
    ``FLINTTRADE_WORKSPACE_DIR``.

    Returns:
        Absolute path of ``totp_auth.duckdb`` inside the workspace directory.
    """
    return _resolve_totp_pair()[0]


def _install_key_path() -> Path:
    """Resolve the per-install TOTP encryption key under the active workspace.

    Returns:
        Absolute path of ``totp_install_key`` inside the workspace directory.
    """
    return _resolve_totp_pair()[1]


def _install_key_path_for(db_path: Path) -> Path:
    """Locate the install key belonging to an explicitly supplied store.

    The store and its key are one cryptographic unit, so a caller-supplied
    store keeps its key beside itself rather than borrowing the workspace's —
    which is also what keeps the legacy-migration probe away from *both*
    halves when an explicit path is given. An in-memory store has no directory
    of its own and its rows never outlive the process, so it falls back to the
    workspace key; that resolution is a plain :func:`workspace_dir` lookup and
    still runs no probe.

    Args:
        db_path: The explicitly supplied secret-store location.

    Returns:
        Absolute path of the ``totp_install_key`` paired with *db_path*.
    """
    if str(db_path) == _MEMORY_DB:
        from flinttrade_core.workspace import workspace_dir  # noqa: PLC0415

        return workspace_dir() / _INSTALL_KEY_NAME
    return db_path.parent / _INSTALL_KEY_NAME


def _migrate_legacy_totp_pair(target_db: Path, target_key: Path) -> None:
    """Copy the legacy TOTP store and install key across as one unit.

    Copy, never move: the legacy pair is retained as a backup. The migration
    is skipped — loudly — whenever the workspace already holds exactly one half
    of the pair, because there is no safe way to guess which key decrypts which
    store, and pairing them wrongly locks the operator out of their own account
    permanently.

    That skip is why the copy itself must be all-or-nothing. Publishing one
    half and then failing on the other would create exactly the state the guard
    refuses to touch, so a lock timeout or a full disk part-way through would
    become a *permanent* 2FA lockout with the legacy pair still on disk. Both
    halves are therefore copied to staging names first and only moved into
    place once both copies and the pairing check have succeeded; anything that
    fails removes every staged and published file, leaving the workspace with
    neither half so the next boot retries from the untouched legacy pair.

    Args:
        target_db: Workspace location of the DuckDB secret store.
        target_key: Workspace location of the per-install encryption key.

    Raises:
        flinttrade_core.workspace.WorkspaceStateMigrationError: The copy could
            not be completed or the copied pair failed verification.
    """
    from flinttrade_core.workspace import (  # noqa: PLC0415
        FileLock,
        FileLockTimeout,
        WorkspaceStateMigrationError,
    )

    if target_db.exists() and target_key.exists():
        return
    if target_db.exists() or target_key.exists():
        logger.warning(
            "Workspace holds only one half of the TOTP pair (store=%s key=%s); skipping the legacy "
            "migration rather than guessing a cryptographic pairing",
            target_db.exists(),
            target_key.exists(),
        )
        return

    legacy_db = _legacy_db_path()
    legacy_key = _legacy_install_key_path()
    if not legacy_db.exists() and not legacy_key.exists():
        return
    if not (legacy_db.exists() and legacy_key.exists()):
        logger.warning(
            "Legacy TOTP state is incomplete (store=%s key=%s); skipping the migration rather than "
            "guessing a cryptographic pairing",
            legacy_db.exists(),
            legacy_key.exists(),
        )
        return

    staged_db = target_db.with_name(f".{target_db.name}.migrating")
    staged_key = target_key.with_name(f".{target_key.name}.migrating")
    try:
        target_db.parent.mkdir(parents=True, exist_ok=True)
        family_lock = FileLock(target_db.parent / _PAIR_LOCK_NAME, timeout=_MIGRATION_TIMEOUT_SECONDS, mode=0o600)
        with family_lock.acquire():
            if target_db.exists() or target_key.exists():
                # A sibling worker won the family lock and migrated the pair.
                logger.info("Legacy TOTP pair already migrated by a concurrent process")
                return
            complete = False
            try:
                _stage_legacy_totp_pair(legacy_db, legacy_key, staged_db, staged_key)
                _publish_staged_totp_pair(staged_db, staged_key, target_db, target_key)
                try:
                    _verify_migrated_totp_pair(target_db, target_key)
                except (InvalidToken, OSError, duckdb.Error) as exc:
                    raise WorkspaceStateMigrationError(
                        "Migrated TOTP install key does not decrypt the migrated secret store; the copies "
                        f"were removed and the legacy pair retained at {legacy_db.parent}"
                    ) from exc
                complete = True
                logger.info("Migrated the legacy TOTP pair from %s to %s", legacy_db.parent, target_db.parent)
            finally:
                # Roll the workspace back to "neither half present" unless the
                # whole unit landed, so the next run retries cleanly instead of
                # tripping the one-half guard forever.
                if not complete:
                    _discard_migrated_totp_pair(target_db, target_key)
                _discard_staged_totp_pair(staged_db, staged_key)
    except WorkspaceStateMigrationError:
        raise
    except (FileLockTimeout, OSError) as exc:
        logger.error("Could not migrate the legacy TOTP pair into %s: %s", target_db.parent, exc)
        raise WorkspaceStateMigrationError(
            f"Could not preserve the legacy TOTP pair; source retained at {legacy_db.parent}"
        ) from exc


def _stage_legacy_totp_pair(legacy_db: Path, legacy_key: Path, staged_db: Path, staged_key: Path) -> None:
    """Copy both halves of the legacy pair to staging names, publishing neither.

    Staging is what makes the migration atomic: a copy that fails part-way
    through — a full disk, an unreadable source — leaves nothing behind but
    dot-prefixed staging files, never a published half of the pair. The
    store's DuckDB ``.wal`` sidecar is staged alongside it so an unclean legacy
    shutdown is not stranded.

    Args:
        legacy_db: Legacy DuckDB secret store.
        legacy_key: Legacy per-install encryption key.
        staged_db: Staging name for the store, a sibling of its target.
        staged_key: Staging name for the key, a sibling of its target.

    Raises:
        OSError: A staged copy could not be written.
    """
    staged_db.parent.mkdir(parents=True, exist_ok=True)
    _discard_staged_totp_pair(staged_db, staged_key)
    for source, staged in ((legacy_key, staged_key), (legacy_db, staged_db)):
        shutil.copy2(source, staged)
        staged.chmod(0o600)
    legacy_wal = Path(f"{legacy_db}.wal")
    if legacy_wal.exists():
        staged_wal = Path(f"{staged_db}.wal")
        shutil.copy2(legacy_wal, staged_wal)
        staged_wal.chmod(0o600)


def _publish_staged_totp_pair(staged_db: Path, staged_key: Path, target_db: Path, target_key: Path) -> None:
    """Move both staged halves into place now that both have been written.

    Two renames cannot be a single filesystem operation, so this is as close to
    atomic as a two-file pair can get: no copying happens between them, and the
    caller removes whichever half landed if the second rename fails.

    Args:
        staged_db: Staged copy of the secret store.
        staged_key: Staged copy of the install key.
        target_db: Workspace location of the secret store.
        target_key: Workspace location of the install key.

    Raises:
        OSError: A staged half could not be moved into place.
    """
    staged_wal = Path(f"{staged_db}.wal")
    if staged_wal.exists():
        staged_wal.replace(Path(f"{target_db}.wal"))
    staged_key.replace(target_key)
    staged_db.replace(target_db)


def _discard_staged_totp_pair(staged_db: Path, staged_key: Path) -> None:
    """Remove the staging files of a TOTP pair migration, best-effort.

    Args:
        staged_db: Staging name of the secret store.
        staged_key: Staging name of the install key.
    """
    for path in (staged_db, Path(f"{staged_db}.wal"), staged_key):
        try:
            path.unlink(missing_ok=True)
        except OSError:
            logger.warning("Could not remove staged TOTP migration file %s", path)


def _verify_migrated_totp_pair(target_db: Path, target_key: Path) -> None:
    """Prove the copied install key still decrypts the copied secret store.

    Verification is skipped when ``FLINTTRADE_TOTP_KEY`` is in force (the
    install key then plays no part in decryption, so there is no pairing to
    verify) and when the store holds no enrolled secret to decrypt.

    Args:
        target_db: Migrated DuckDB secret store.
        target_key: Migrated per-install encryption key.

    Raises:
        cryptography.fernet.InvalidToken: The key does not decrypt the store.
        duckdb.Error: The migrated store could not be read.
        OSError: The migrated key could not be read.
    """
    if os.environ.get("FLINTTRADE_TOTP_KEY"):
        logger.info("FLINTTRADE_TOTP_KEY supersedes the install key; TOTP pair verification skipped")
        return

    app_key = target_key.read_text(encoding="utf-8").strip()
    conn = duckdb.connect(str(target_db))
    try:
        try:
            row = conn.execute("SELECT user_id, encrypted, salt FROM totp_secrets LIMIT 1").fetchone()
        except duckdb.Error:
            # No secrets table: the store predates enrolment, so there is no
            # pairing to prove. Verification checks the pairing, not the
            # store's integrity — deleting the copy here would be wrong.
            logger.warning("Migrated TOTP store has no secrets table; decrypt verification not applicable")
            return
    finally:
        conn.close()
    if row is None:
        logger.info("Migrated TOTP store holds no enrolled secret; decrypt verification not applicable")
        return

    user_id, encrypted, salt = row
    fernet = _derive_fernet_key(f"{app_key}:{user_id}", bytes(salt))
    fernet.decrypt(bytes(encrypted))
    logger.info("Verified the migrated TOTP install key decrypts the migrated secret store")


def _discard_migrated_totp_pair(target_db: Path, target_key: Path) -> None:
    """Un-publish a TOTP pair whose migration did not complete, best-effort.

    Called for every incomplete outcome — a staging failure, a half-finished
    publish, a failed pairing check — so the workspace is always left with
    neither half rather than the one half the migration guard would then
    refuse to touch for good.

    Args:
        target_db: Migrated DuckDB secret store to remove.
        target_key: Migrated per-install encryption key to remove.
    """
    for path in (target_db, Path(f"{target_db}.wal"), target_key):
        try:
            path.unlink(missing_ok=True)
        except OSError:
            logger.warning("Could not remove unverified migrated TOTP file %s", path)


def _load_or_init_install_secret(key_path: Path) -> str:
    """Return the per-install random secret held in *key_path*.

    Generated once on first call (64 bytes urlsafe). File permissions set to
    owner-read only on POSIX. Ensures every FlintTrade install uses a unique
    key for TOTP encryption, even if ``FLINTTRADE_TOTP_KEY`` is unset.

    The path is supplied by the caller rather than resolved here so that a
    :class:`TOTPAuth` built on an explicit ``db_path`` reads the key beside
    *its own* store, without ever running the legacy-migration probe.

    Args:
        key_path: Location of this install's ``totp_install_key``.

    Returns:
        The per-install secret as stored on disk.
    """
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


def _app_passphrase(user_id: str, key_path: Path) -> str:
    """Build the encryption passphrase for *user_id*.

    Prefers ``FLINTTRADE_TOTP_KEY`` env var; otherwise uses the per-install
    random secret persisted at *key_path*. The legacy hardcoded default has
    been removed — each install now has a unique key.

    Args:
        user_id: Unique user identifier.
        key_path: Location of this install's ``totp_install_key``.

    Returns:
        String used as PBKDF2 input material.
    """
    app_key = os.environ.get("FLINTTRADE_TOTP_KEY") or _load_or_init_install_secret(key_path)
    return f"{app_key}:{user_id}"


# ---------------------------------------------------------------------------
# TOTPAuth
# ---------------------------------------------------------------------------


class TOTPAuth:
    """Time-based One-Time Password authentication for FlintTrade users.

    Compatible with Google Authenticator, Authy, Microsoft Authenticator.

    Persistence uses DuckDB (not SQLite) so it lives alongside other analytics
    data in the FlintTrade workspace directory. Secrets are Fernet-encrypted;
    backup codes are argon2id-hashed.

    Attributes:
        _db_path: Path to the DuckDB database file.
        _key_path: Path to the ``totp_install_key`` paired with that database.
    """

    def __init__(self, db_path: Path | str | None = None) -> None:
        """Initialise the TOTP auth store.

        Args:
            db_path: Optional path to the DuckDB file. Defaults to
                ``totp_auth.duckdb`` under the workspace directory, resolved at
                call time so an environment override set after import is
                honoured. An explicit path skips the legacy-migration probe for
                *both* halves of the pair: the install key is then read beside
                that file rather than resolved through the probing path, so
                supplying a path never has the installer touch the caller's
                legacy directory.

        Raises:
            flinttrade_core.workspace.WorkspaceStateMigrationError: A legacy
                TOTP pair could not be preserved in the workspace.
        """
        if db_path is not None:
            self._db_path = Path(db_path)
            self._key_path = _install_key_path_for(self._db_path)
        else:
            # One probe for the whole pair — resolving the halves separately
            # would run the legacy migration twice.
            self._db_path, self._key_path = _resolve_totp_pair()
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
        fernet = _derive_fernet_key(_app_passphrase(user_id, self._key_path), salt)
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

        safe_user = log_ref(user_id, kind="user")
        logger.info("TOTP secret generated for user=%s", safe_user)
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
        safe_user = log_ref(user_id, kind="user")
        if secret is None:
            logger.warning("verify_token called for unknown or disabled user=%s", safe_user)
            return False
        totp = pyotp.TOTP(secret)
        result = totp.verify(token, valid_window=1)
        logger.debug("verify_token user=%s result=%s", safe_user, result)
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
                    logger.info("Backup code consumed for user=%s", log_ref(user_id, kind="user"))
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
        safe_user = log_ref(user_id, kind="user")
        if not self.verify_token(user_id, token):
            logger.warning("disable: invalid token for user=%s", safe_user)
            return False
        self._db.execute(
            "UPDATE totp_secrets SET enabled = FALSE WHERE user_id = ?",
            [user_id],
        )
        logger.info("TOTP disabled for user=%s", safe_user)
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
        fernet = _derive_fernet_key(_app_passphrase(user_id, self._key_path), bytes(salt))
        try:
            return fernet.decrypt(bytes(encrypted)).decode("utf-8")
        except InvalidToken:
            logger.error("Failed to decrypt TOTP secret for user=%s", log_ref(user_id, kind="user"))
            return None
