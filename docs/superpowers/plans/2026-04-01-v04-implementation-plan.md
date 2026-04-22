# FlintTrade v0.4.0 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add login/security system, theme overhaul, three execution modes (Demo/Sandbox/Live), and welcome flow changes to FlintTrade.

**Architecture:** 4 independent phases built sequentially. Phase A (auth) is foundational. Phase B (themes) runs independently. Phase C (modes) depends on A. Phase D (welcome flow) depends on A+C. Each phase produces working, testable software.

**Tech Stack:** Python 3.12 (Flask, argon2-cffi, PyJWT, pyotp, qrcode), React 19 (TypeScript, Zustand, TanStack Query, shadcn/ui, Tailwind v4), DuckDB.

**Spec:** `docs/superpowers/specs/2026-04-01-v04-security-themes-modes-design.md`

**Rule:** No deletions/modifications outside spec scope without explicit user confirmation.

---

## Phase A: Login & Security System

### Task A1: Python Auth Service — Credential Storage

**Files:**
- Create: `packages/core/src/auth_service.py`
- Create: `packages/core/tests/test_auth_service.py`

- [ ] **Step 1: Write failing tests for credential storage**

```python
# packages/core/tests/test_auth_service.py
"""Tests for auth service — credential storage, hashing, verification."""

from __future__ import annotations
import pytest
from pathlib import Path
from packages.core.src.auth_service import AuthService


class TestAccountSetup:
    """One-time account creation."""

    def test_setup_creates_auth_db(self, tmp_path: Path):
        svc = AuthService(db_path=tmp_path / "auth.db")
        svc.setup_account(
            username="alice",
            email="alice@example.com",
            password="StrongP@ss123!",
            pin="123456",
        )
        assert (tmp_path / "auth.db").exists()

    def test_setup_stores_username_and_email(self, tmp_path: Path):
        svc = AuthService(db_path=tmp_path / "auth.db")
        svc.setup_account(
            username="alice",
            email="alice@example.com",
            password="StrongP@ss123!",
            pin="123456",
        )
        profile = svc.get_profile()
        assert profile["username"] == "alice"
        assert profile["email"] == "nav@example.com"

    def test_setup_rejects_weak_password(self, tmp_path: Path):
        svc = AuthService(db_path=tmp_path / "auth.db")
        with pytest.raises(ValueError, match="too weak"):
            svc.setup_account(
                username="nav", email="alice@example.com",
                password="123", pin="123456",
            )

    def test_setup_rejects_non_6_digit_pin(self, tmp_path: Path):
        svc = AuthService(db_path=tmp_path / "auth.db")
        with pytest.raises(ValueError, match="6 digits"):
            svc.setup_account(
                username="nav", email="alice@example.com",
                password="StrongP@ss123!", pin="12345",
            )

    def test_is_setup_returns_false_before_setup(self, tmp_path: Path):
        svc = AuthService(db_path=tmp_path / "auth.db")
        assert svc.is_setup() is False

    def test_is_setup_returns_true_after_setup(self, tmp_path: Path):
        svc = AuthService(db_path=tmp_path / "auth.db")
        svc.setup_account(
            username="nav", email="alice@example.com",
            password="StrongP@ss123!", pin="123456",
        )
        assert svc.is_setup() is True


class TestPasswordVerification:
    """Password login."""

    def test_verify_correct_password(self, tmp_path: Path):
        svc = AuthService(db_path=tmp_path / "auth.db")
        svc.setup_account(
            username="nav", email="alice@example.com",
            password="StrongP@ss123!", pin="123456",
        )
        assert svc.verify_password("StrongP@ss123!") is True

    def test_verify_wrong_password(self, tmp_path: Path):
        svc = AuthService(db_path=tmp_path / "auth.db")
        svc.setup_account(
            username="nav", email="alice@example.com",
            password="StrongP@ss123!", pin="123456",
        )
        assert svc.verify_password("wrong") is False


class TestPinVerification:
    """PIN quick-unlock."""

    def test_verify_correct_pin(self, tmp_path: Path):
        svc = AuthService(db_path=tmp_path / "auth.db")
        svc.setup_account(
            username="nav", email="alice@example.com",
            password="StrongP@ss123!", pin="123456",
        )
        assert svc.verify_pin("123456") is True

    def test_verify_wrong_pin(self, tmp_path: Path):
        svc = AuthService(db_path=tmp_path / "auth.db")
        svc.setup_account(
            username="nav", email="alice@example.com",
            password="StrongP@ss123!", pin="123456",
        )
        assert svc.verify_pin("000000") is False


class TestTOTP:
    """2FA TOTP setup and verification."""

    def test_setup_generates_totp_secret(self, tmp_path: Path):
        svc = AuthService(db_path=tmp_path / "auth.db")
        svc.setup_account(
            username="nav", email="alice@example.com",
            password="StrongP@ss123!", pin="123456",
        )
        secret = svc.get_totp_secret()
        assert secret is not None
        assert len(secret) >= 16

    def test_verify_totp_with_valid_code(self, tmp_path: Path):
        import pyotp
        svc = AuthService(db_path=tmp_path / "auth.db")
        svc.setup_account(
            username="nav", email="alice@example.com",
            password="StrongP@ss123!", pin="123456",
        )
        secret = svc.get_totp_secret()
        totp = pyotp.TOTP(secret)
        assert svc.verify_totp(totp.now()) is True

    def test_verify_totp_with_invalid_code(self, tmp_path: Path):
        svc = AuthService(db_path=tmp_path / "auth.db")
        svc.setup_account(
            username="nav", email="alice@example.com",
            password="StrongP@ss123!", pin="123456",
        )
        assert svc.verify_totp("000000") is False


class TestBackupCodes:
    """Recovery backup codes."""

    def test_setup_generates_8_backup_codes(self, tmp_path: Path):
        svc = AuthService(db_path=tmp_path / "auth.db")
        codes = svc.setup_account(
            username="nav", email="alice@example.com",
            password="StrongP@ss123!", pin="123456",
        )
        assert len(codes) == 8
        assert all(len(c) >= 8 for c in codes)

    def test_backup_code_works_once(self, tmp_path: Path):
        svc = AuthService(db_path=tmp_path / "auth.db")
        codes = svc.setup_account(
            username="nav", email="alice@example.com",
            password="StrongP@ss123!", pin="123456",
        )
        assert svc.verify_backup_code(codes[0]) is True
        assert svc.verify_backup_code(codes[0]) is False  # Used, can't reuse


class TestLoginAttempts:
    """Rate limiting — 5 failures → lockout."""

    def test_lockout_after_5_failures(self, tmp_path: Path):
        svc = AuthService(db_path=tmp_path / "auth.db")
        svc.setup_account(
            username="nav", email="alice@example.com",
            password="StrongP@ss123!", pin="123456",
        )
        for _ in range(5):
            svc.verify_password("wrong")
        assert svc.is_locked() is True

    def test_locked_rejects_even_correct_password(self, tmp_path: Path):
        svc = AuthService(db_path=tmp_path / "auth.db")
        svc.setup_account(
            username="nav", email="alice@example.com",
            password="StrongP@ss123!", pin="123456",
        )
        for _ in range(5):
            svc.verify_password("wrong")
        assert svc.verify_password("StrongP@ss123!") is False
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd c:/Users/navan/Documents/GitHub/FlintTrade && python -m pytest packages/core/tests/test_auth_service.py -v --tb=short`
Expected: All tests FAIL with `ImportError: cannot import name 'AuthService'`

- [ ] **Step 3: Install dependencies**

Run: `pip install argon2-cffi PyJWT pyotp qrcode`

- [ ] **Step 4: Implement AuthService**

```python
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
            self._conn = sqlite3.connect(str(self._db_path))
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
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `cd c:/Users/navan/Documents/GitHub/FlintTrade && python -m pytest packages/core/tests/test_auth_service.py -v --tb=short`
Expected: All 16 tests PASS

- [ ] **Step 6: Commit**

```bash
git add packages/core/src/auth_service.py packages/core/tests/test_auth_service.py
git commit -m "feat(auth): add AuthService — password, PIN, TOTP, backup codes, lockout"
```

---

### Task A2: Auth REST API Routes

**Files:**
- Create: `packages/core/src/auth_routes.py`
- Create: `packages/core/tests/test_auth_routes.py`
- Modify: `packages/core/src/app.py` (register blueprint)

- [ ] **Step 1: Write failing tests for auth endpoints**

```python
# packages/core/tests/test_auth_routes.py
"""Tests for auth REST endpoints."""

from __future__ import annotations
import json
import pytest
from unittest.mock import patch
from packages.core.src.app import create_flask_app


@pytest.fixture()
def client(tmp_path):
    """Flask test client with auth service pointed at tmp_path."""
    with patch("packages.core.src.auth_routes._get_auth_service") as mock:
        from packages.core.src.auth_service import AuthService
        svc = AuthService(db_path=tmp_path / "auth.db")
        mock.return_value = svc
        app = create_flask_app()
        app.config["TESTING"] = True
        with app.test_client() as c:
            yield c, svc


class TestSetupEndpoint:
    def test_setup_creates_account(self, client):
        c, svc = client
        resp = c.post("/v1/auth/setup", json={
            "username": "nav",
            "email": "nav@example.com",
            "password": "StrongP@ss123!",
            "pin": "123456",
        }, headers={"Content-Type": "application/json"})
        assert resp.status_code == 201
        data = resp.get_json()
        assert data["status"] == "success"
        assert len(data["data"]["backup_codes"]) == 8
        assert "totp_uri" in data["data"]

    def test_setup_rejects_duplicate(self, client):
        c, svc = client
        c.post("/v1/auth/setup", json={
            "username": "nav", "email": "nav@example.com",
            "password": "StrongP@ss123!", "pin": "123456",
        }, headers={"Content-Type": "application/json"})
        resp = c.post("/v1/auth/setup", json={
            "username": "nav2", "email": "nav2@example.com",
            "password": "StrongP@ss123!", "pin": "654321",
        }, headers={"Content-Type": "application/json"})
        assert resp.status_code == 409


class TestLoginEndpoint:
    def test_login_with_correct_credentials(self, client):
        c, svc = client
        c.post("/v1/auth/setup", json={
            "username": "nav", "email": "nav@example.com",
            "password": "StrongP@ss123!", "pin": "123456",
        }, headers={"Content-Type": "application/json"})
        # Get TOTP code
        import pyotp
        secret = svc.get_totp_secret()
        code = pyotp.TOTP(secret).now()
        resp = c.post("/v1/auth/login", json={
            "password": "StrongP@ss123!",
            "totp_code": code,
        }, headers={"Content-Type": "application/json"})
        assert resp.status_code == 200
        data = resp.get_json()
        assert "token" in data["data"]

    def test_login_with_wrong_password(self, client):
        c, svc = client
        c.post("/v1/auth/setup", json={
            "username": "nav", "email": "nav@example.com",
            "password": "StrongP@ss123!", "pin": "123456",
        }, headers={"Content-Type": "application/json"})
        resp = c.post("/v1/auth/login", json={
            "password": "wrong",
            "totp_code": "000000",
        }, headers={"Content-Type": "application/json"})
        assert resp.status_code == 401


class TestStatusEndpoint:
    def test_status_returns_setup_state(self, client):
        c, svc = client
        resp = c.get("/v1/auth/status")
        data = resp.get_json()
        assert data["data"]["is_setup"] is False

    def test_status_after_setup(self, client):
        c, svc = client
        c.post("/v1/auth/setup", json={
            "username": "nav", "email": "nav@example.com",
            "password": "StrongP@ss123!", "pin": "123456",
        }, headers={"Content-Type": "application/json"})
        resp = c.get("/v1/auth/status")
        data = resp.get_json()
        assert data["data"]["is_setup"] is True


class TestPinEndpoint:
    def test_pin_verify_correct(self, client):
        c, svc = client
        c.post("/v1/auth/setup", json={
            "username": "nav", "email": "nav@example.com",
            "password": "StrongP@ss123!", "pin": "123456",
        }, headers={"Content-Type": "application/json"})
        resp = c.post("/v1/auth/pin", json={"pin": "123456"},
                       headers={"Content-Type": "application/json"})
        assert resp.status_code == 200

    def test_pin_verify_wrong(self, client):
        c, svc = client
        c.post("/v1/auth/setup", json={
            "username": "nav", "email": "nav@example.com",
            "password": "StrongP@ss123!", "pin": "123456",
        }, headers={"Content-Type": "application/json"})
        resp = c.post("/v1/auth/pin", json={"pin": "000000"},
                       headers={"Content-Type": "application/json"})
        assert resp.status_code == 401
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest packages/core/tests/test_auth_routes.py -v --tb=short`
Expected: FAIL — `auth_routes` module not found

- [ ] **Step 3: Implement auth routes blueprint**

```python
# packages/core/src/auth_routes.py
"""Auth REST API — setup, login, PIN verify, status, logout.

Blueprint prefix: /v1/auth
Public endpoints (no API key required):
  - GET  /v1/auth/status   — check if setup complete
  - POST /v1/auth/setup    — one-time account creation
  - POST /v1/auth/login    — daily password + TOTP login
  - POST /v1/auth/pin      — PIN quick-unlock
  - POST /v1/auth/logout   — invalidate session
"""

from __future__ import annotations

import logging
import time
from datetime import datetime, timezone, timedelta
from typing import Any

import jwt
from flask import Blueprint, jsonify, request, current_app

logger = logging.getLogger("flinttrade.auth")

auth_bp = Blueprint("auth", __name__, url_prefix="/v1/auth")

# JWT config
_JWT_SECRET_KEY = ""  # Set from env or generated at startup
_JWT_ALGORITHM = "HS256"

# IST timezone offset
_IST_OFFSET = timedelta(hours=5, minutes=30)


def _get_auth_service():
    """Get the AuthService instance from app config."""
    return current_app.config.get("AUTH_SERVICE")


def _get_jwt_secret() -> str:
    """Get or generate the JWT secret."""
    global _JWT_SECRET_KEY
    if not _JWT_SECRET_KEY:
        import secrets
        _JWT_SECRET_KEY = current_app.config.get("JWT_SECRET", secrets.token_urlsafe(64))
    return _JWT_SECRET_KEY


def _next_8am_ist() -> datetime:
    """Calculate the next 8:00 AM IST from now."""
    now_utc = datetime.now(timezone.utc)
    now_ist = now_utc + _IST_OFFSET
    today_8am_ist = now_ist.replace(hour=8, minute=0, second=0, microsecond=0)
    if now_ist >= today_8am_ist:
        today_8am_ist += timedelta(days=1)
    # Convert back to UTC
    return today_8am_ist - _IST_OFFSET


def _create_token(username: str) -> str:
    """Create a JWT that expires at next 8:00 AM IST."""
    exp = _next_8am_ist()
    payload = {
        "sub": username,
        "iat": datetime.now(timezone.utc),
        "exp": exp,
        "type": "session",
    }
    return jwt.encode(payload, _get_jwt_secret(), algorithm=_JWT_ALGORITHM)


@auth_bp.route("/status", methods=["GET"])
def auth_status() -> tuple[Any, int]:
    """Check if account is set up and if user is locked out."""
    svc = _get_auth_service()
    if svc is None:
        return jsonify({"status": "error", "message": "Auth service not available."}), 503
    return jsonify({
        "status": "success",
        "data": {
            "is_setup": svc.is_setup(),
            "is_locked": svc.is_locked(),
        },
    }), 200


@auth_bp.route("/setup", methods=["POST"])
def auth_setup() -> tuple[Any, int]:
    """One-time account setup. Returns backup codes and TOTP URI."""
    svc = _get_auth_service()
    if svc is None:
        return jsonify({"status": "error", "message": "Auth service not available."}), 503

    body = request.get_json(silent=True) or {}
    username = str(body.get("username", "")).strip()
    email = str(body.get("email", "")).strip()
    password = str(body.get("password", ""))
    pin = str(body.get("pin", ""))

    if not username or not email or not password or not pin:
        return jsonify({"status": "error", "message": "All fields required: username, email, password, pin."}), 400

    try:
        backup_codes = svc.setup_account(username, email, password, pin)
    except ValueError as exc:
        return jsonify({"status": "error", "message": str(exc)}), 400
    except RuntimeError as exc:
        return jsonify({"status": "error", "message": str(exc)}), 409

    return jsonify({
        "status": "success",
        "data": {
            "backup_codes": backup_codes,
            "totp_uri": svc.get_totp_provisioning_uri(),
        },
    }), 201


@auth_bp.route("/login", methods=["POST"])
def auth_login() -> tuple[Any, int]:
    """Daily login with password + TOTP."""
    svc = _get_auth_service()
    if svc is None:
        return jsonify({"status": "error", "message": "Auth service not available."}), 503

    if svc.is_locked():
        return jsonify({
            "status": "error",
            "message": "Account locked after too many failed attempts. Reset via email.",
        }), 423

    body = request.get_json(silent=True) or {}
    password = str(body.get("password", ""))
    totp_code = str(body.get("totp_code", ""))

    if not svc.verify_password(password):
        return jsonify({"status": "error", "message": "Invalid credentials."}), 401

    if not svc.verify_totp(totp_code):
        # Try backup code as fallback
        if not svc.verify_backup_code(totp_code):
            return jsonify({"status": "error", "message": "Invalid TOTP code."}), 401

    profile = svc.get_profile()
    token = _create_token(profile.get("username", "user"))

    return jsonify({
        "status": "success",
        "data": {
            "token": token,
            "username": profile.get("username"),
            "expires_at": _next_8am_ist().isoformat(),
        },
    }), 200


@auth_bp.route("/pin", methods=["POST"])
def auth_pin_verify() -> tuple[Any, int]:
    """PIN quick-unlock — returns new session token."""
    svc = _get_auth_service()
    if svc is None:
        return jsonify({"status": "error", "message": "Auth service not available."}), 503

    body = request.get_json(silent=True) or {}
    pin = str(body.get("pin", ""))

    if not svc.verify_pin(pin):
        return jsonify({"status": "error", "message": "Invalid PIN."}), 401

    profile = svc.get_profile()
    token = _create_token(profile.get("username", "user"))

    return jsonify({
        "status": "success",
        "data": {"token": token},
    }), 200


@auth_bp.route("/logout", methods=["POST"])
def auth_logout() -> tuple[Any, int]:
    """Invalidate current session."""
    # JWT is stateless — client discards token
    # Server-side: log the logout event
    logger.info("User logged out")
    return jsonify({"status": "success", "data": {"message": "Logged out."}}), 200
```

- [ ] **Step 4: Register auth blueprint in app.py**

Add after the existing blueprint registrations in `packages/core/src/app.py` (around line 258):

```python
    # Register Auth blueprint (/v1/auth/*) — public endpoints, no API key required
    from packages.core.src.auth_service import AuthService as _AuthService  # noqa: PLC0415
    from packages.core.src.auth_routes import auth_bp  # noqa: PLC0415
    _auth_db = Path.home() / ".flinttrade" / "auth.db"
    app.config["AUTH_SERVICE"] = _AuthService(db_path=_auth_db)
    app.register_blueprint(auth_bp)
```

Also add `/v1/auth/` to the public path exemptions in `require_auth` (around line 274):

```python
    _PUBLIC_V1_PREFIXES = (
        "/v1/admin/health",
        "/v1/admin/introspect",
        "/v1/auth/",          # Auth endpoints are public (login, setup, status)
        "/v1/auth/callback",
    )
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `python -m pytest packages/core/tests/test_auth_routes.py packages/core/tests/test_auth_service.py -v --tb=short`
Expected: All tests PASS

- [ ] **Step 6: Commit**

```bash
git add packages/core/src/auth_routes.py packages/core/tests/test_auth_routes.py packages/core/src/app.py
git commit -m "feat(auth): add auth REST API — setup, login, PIN, logout endpoints"
```

---

### Task A3: Frontend Auth Store + Login Route

**Files:**
- Create: `packages/terminal/src/stores/authStore.ts`
- Create: `packages/terminal/src/hooks/useAuthGuard.ts`
- Create: `packages/terminal/src/routes/LoginRoute.tsx`
- Modify: `packages/terminal/src/main.tsx` (add auth guard)

- [ ] **Step 1: Create authStore**

```typescript
// packages/terminal/src/stores/authStore.ts
/**
 * Auth session store — manages JWT token, login state, and idle timeout.
 *
 * Token stored in memory only (never localStorage) for security.
 * Session expires at 08:00 IST daily.
 */

import { create } from "zustand";

type AuthStatus = "unknown" | "logged-in" | "logged-out" | "pin-required" | "setup-required";

interface AuthState {
  status: AuthStatus;
  token: string | null;
  username: string | null;
  expiresAt: string | null;
  lastActivity: number;

  setLoggedIn: (token: string, username: string, expiresAt: string) => void;
  setLoggedOut: () => void;
  setPinRequired: () => void;
  setSetupRequired: () => void;
  touchActivity: () => void;
  checkIdle: () => void;
}

const IDLE_PIN_THRESHOLD = 5 * 60 * 1000;  // 5 min → PIN required
const IDLE_LOGOUT_THRESHOLD = 30 * 60 * 1000;  // 30 min → full logout

export const useAuthStore = create<AuthState>((set, get) => ({
  status: "unknown",
  token: null,
  username: null,
  expiresAt: null,
  lastActivity: Date.now(),

  setLoggedIn: (token, username, expiresAt) =>
    set({ status: "logged-in", token, username, expiresAt, lastActivity: Date.now() }),

  setLoggedOut: () =>
    set({ status: "logged-out", token: null, username: null, expiresAt: null }),

  setPinRequired: () =>
    set({ status: "pin-required", token: null }),

  setSetupRequired: () =>
    set({ status: "setup-required", token: null, username: null }),

  touchActivity: () => set({ lastActivity: Date.now() }),

  checkIdle: () => {
    const { status, lastActivity } = get();
    if (status !== "logged-in") return;

    const idle = Date.now() - lastActivity;
    if (idle >= IDLE_LOGOUT_THRESHOLD) {
      set({ status: "logged-out", token: null });
    } else if (idle >= IDLE_PIN_THRESHOLD) {
      set({ status: "pin-required", token: null });
    }
  },
}));
```

- [ ] **Step 2: Create useAuthGuard hook**

```typescript
// packages/terminal/src/hooks/useAuthGuard.ts
/**
 * Auth guard hook — checks session status on mount and redirects to login.
 *
 * Usage: call at the top of every protected route component.
 * Returns { isAuthenticated, isLoading } so the route can show a loader.
 */

import { useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";
import { useAuthStore } from "@/stores/authStore";

export function useAuthGuard(): { isAuthenticated: boolean; isLoading: boolean } {
  const navigate = useNavigate();
  const status = useAuthStore((s) => s.status);
  const [isLoading, setIsLoading] = useState(status === "unknown");

  useEffect(() => {
    if (status === "unknown") {
      // Check backend for setup status
      fetch("/ft-api/v1/auth/status")
        .then((r) => r.json())
        .then((data) => {
          if (!data.data?.is_setup) {
            useAuthStore.getState().setSetupRequired();
          } else {
            useAuthStore.getState().setLoggedOut();
          }
          setIsLoading(false);
        })
        .catch(() => {
          useAuthStore.getState().setLoggedOut();
          setIsLoading(false);
        });
      return;
    }

    if (status === "setup-required") {
      navigate("/welcome", { replace: true });
    } else if (status === "logged-out") {
      navigate("/welcome", { replace: true });
    } else if (status === "pin-required") {
      navigate("/welcome", { replace: true });
    }
  }, [status, navigate]);

  return {
    isAuthenticated: status === "logged-in",
    isLoading,
  };
}
```

- [ ] **Step 3: Create LoginRoute**

```typescript
// packages/terminal/src/routes/LoginRoute.tsx
/**
 * LoginRoute — daily login screen (password + TOTP or PIN).
 *
 * Rendered inside /welcome flow for returning users.
 * Not a standalone route — it's a component used by WelcomeRoute.
 */

import { useState } from "react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { LogoIcon } from "@/components/brand/Logo";
import { Lock, KeyRound, ShieldCheck, AlertTriangle } from "lucide-react";
import { useAuthStore } from "@/stores/authStore";

interface LoginRouteProps {
  onSuccess: () => void;
  mode: "full" | "pin";
}

export default function LoginRoute({ onSuccess, mode }: LoginRouteProps) {
  const [password, setPassword] = useState("");
  const [totpCode, setTotpCode] = useState("");
  const [pin, setPin] = useState("");
  const [error, setError] = useState("");
  const [isLoading, setIsLoading] = useState(false);

  async function handlePasswordLogin() {
    setIsLoading(true);
    setError("");
    try {
      const resp = await fetch("/ft-api/v1/auth/login", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ password, totp_code: totpCode }),
      });
      const data = await resp.json();
      if (resp.ok && data.data?.token) {
        useAuthStore.getState().setLoggedIn(
          data.data.token,
          data.data.username,
          data.data.expires_at,
        );
        onSuccess();
      } else {
        setError(data.message || "Invalid credentials.");
      }
    } catch {
      setError("Cannot reach server.");
    } finally {
      setIsLoading(false);
    }
  }

  async function handlePinLogin() {
    setIsLoading(true);
    setError("");
    try {
      const resp = await fetch("/ft-api/v1/auth/pin", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ pin }),
      });
      const data = await resp.json();
      if (resp.ok && data.data?.token) {
        useAuthStore.getState().setLoggedIn(
          data.data.token,
          useAuthStore.getState().username || "user",
          "",
        );
        onSuccess();
      } else {
        setError(data.message || "Invalid PIN.");
      }
    } catch {
      setError("Cannot reach server.");
    } finally {
      setIsLoading(false);
    }
  }

  return (
    <div className="flex items-center justify-center min-h-screen bg-surface-base p-6">
      <div className="w-full max-w-sm space-y-6">
        {/* Logo */}
        <div className="flex justify-center">
          <LogoIcon size={40} className="text-accent" />
        </div>

        <div className="text-center space-y-1">
          <h1 className="font-heading font-bold text-xl text-text-primary">
            {mode === "pin" ? "Quick Unlock" : "Welcome Back"}
          </h1>
          <p className="text-sm text-text-muted">
            {mode === "pin"
              ? "Enter your PIN to continue"
              : "Enter your password and 2FA code"}
          </p>
        </div>

        {error && (
          <div className="flex items-center gap-2 p-3 rounded-lg bg-loss/10 border border-loss/30 text-sm text-loss">
            <AlertTriangle className="size-4 shrink-0" />
            {error}
          </div>
        )}

        {mode === "pin" ? (
          <div className="space-y-4">
            <div>
              <label htmlFor="pin" className="text-xs text-text-secondary font-medium block mb-1.5">
                PIN
              </label>
              <Input
                id="pin"
                type="password"
                inputMode="numeric"
                maxLength={6}
                value={pin}
                onChange={(e) => setPin(e.target.value.replace(/\D/g, ""))}
                placeholder="6-digit PIN"
                aria-label="Enter your 6-digit PIN"
                className="text-center font-mono text-lg tracking-widest"
                onKeyDown={(e) => e.key === "Enter" && handlePinLogin()}
                autoFocus
              />
            </div>
            <Button
              onClick={handlePinLogin}
              disabled={pin.length !== 6 || isLoading}
              className="w-full"
            >
              <KeyRound className="size-4" />
              {isLoading ? "Verifying..." : "Unlock"}
            </Button>
            <button
              type="button"
              onClick={() => useAuthStore.getState().setLoggedOut()}
              className="w-full text-xs text-text-muted hover:text-text-primary transition-colors"
            >
              Use password instead
            </button>
          </div>
        ) : (
          <div className="space-y-4">
            <div>
              <label htmlFor="password" className="text-xs text-text-secondary font-medium block mb-1.5">
                Password
              </label>
              <Input
                id="password"
                type="password"
                value={password}
                onChange={(e) => setPassword(e.target.value)}
                placeholder="Enter password"
                aria-label="Enter your password"
                autoFocus
              />
            </div>
            <div>
              <label htmlFor="totp" className="text-xs text-text-secondary font-medium block mb-1.5">
                2FA Code
              </label>
              <Input
                id="totp"
                type="text"
                inputMode="numeric"
                maxLength={6}
                value={totpCode}
                onChange={(e) => setTotpCode(e.target.value.replace(/\D/g, ""))}
                placeholder="6-digit code from Authenticator"
                aria-label="Enter your 2FA code"
                className="font-mono tracking-widest"
                onKeyDown={(e) => e.key === "Enter" && handlePasswordLogin()}
              />
            </div>
            <Button
              onClick={handlePasswordLogin}
              disabled={!password || totpCode.length !== 6 || isLoading}
              className="w-full"
            >
              <ShieldCheck className="size-4" />
              {isLoading ? "Signing in..." : "Sign In"}
            </Button>
          </div>
        )}
      </div>
    </div>
  );
}
```

- [ ] **Step 4: Run TypeScript check**

Run: `cd packages/terminal && npx tsc --noEmit`
Expected: No errors

- [ ] **Step 5: Commit**

```bash
git add packages/terminal/src/stores/authStore.ts packages/terminal/src/hooks/useAuthGuard.ts packages/terminal/src/routes/LoginRoute.tsx
git commit -m "feat(auth): add authStore, useAuthGuard hook, LoginRoute component"
```

---

### Task A4: Wire Auth Into Router + Idle Detection

**Files:**
- Modify: `packages/terminal/src/main.tsx`
- Modify: `packages/terminal/src/routes/AppLayout.tsx`

- [ ] **Step 1: Add auth guard wrapper to main.tsx**

In `packages/terminal/src/main.tsx`, wrap all protected routes with an auth check. Add a new `ProtectedRoute` component:

```typescript
// Add after existing imports (around line 12)
import { useAuthGuard } from "./hooks/useAuthGuard";

function ProtectedRoute({ children }: { children: React.ReactNode }) {
  const { isAuthenticated, isLoading } = useAuthGuard();
  if (isLoading) return <Loading />;
  if (!isAuthenticated) return null; // useAuthGuard handles redirect
  return <>{children}</>;
}
```

Then wrap each app route's element with `<ProtectedRoute>`:

```typescript
// Change line 75 from:
{ path: "trade", element: <RouteErrorBoundary routeName="Trade">...
// To:
{ path: "trade", element: <ProtectedRoute><RouteErrorBoundary routeName="Trade">...
```

Apply to all app routes: trade, invest, learn, lab, automate, ai, ditto.
Settings route also needs protection.

- [ ] **Step 2: Add idle detection to AppLayout**

In `packages/terminal/src/routes/AppLayout.tsx`, add an effect that checks idle state:

```typescript
// Add to existing imports
import { useAuthStore } from "@/stores/authStore";

// Inside AppLayout component, add:
useEffect(() => {
  const interval = setInterval(() => {
    useAuthStore.getState().checkIdle();
  }, 60_000); // Check every minute

  // Touch activity on user interaction
  function onActivity() { useAuthStore.getState().touchActivity(); }
  window.addEventListener("mousemove", onActivity, { passive: true });
  window.addEventListener("keydown", onActivity, { passive: true });

  return () => {
    clearInterval(interval);
    window.removeEventListener("mousemove", onActivity);
    window.removeEventListener("keydown", onActivity);
  };
}, []);
```

- [ ] **Step 3: Run TypeScript + vitest**

Run: `cd packages/terminal && npx tsc --noEmit && npx vitest run`
Expected: tsc clean, all tests pass

- [ ] **Step 4: Commit**

```bash
git add packages/terminal/src/main.tsx packages/terminal/src/routes/AppLayout.tsx
git commit -m "feat(auth): wire auth guards into router + idle detection"
```

---

## Phase B: Theme System v4

### Task B1: Define 3 New Themes

**Files:**
- Modify: `packages/terminal/src/lib/cinematicThemes.ts`
- Create: `packages/terminal/src/lib/__tests__/cinematicThemesV4.test.ts`

- [ ] **Step 1: Write tests for v4 theme structure**

Test that each theme has both dark AND light variants with all required token groups.

- [ ] **Step 2: Rewrite cinematicThemes.ts with 3 themes (Graphite, Midnight, Ember)**

Each theme defines complete dark + light palettes: surfaces (4), text (4), borders (2), accent, trading semantics, chart colours, particle config.

- [ ] **Step 3: Run tests**
- [ ] **Step 4: Commit**

### Task B2: Update ThemeStore for v4

**Files:**
- Modify: `packages/terminal/src/stores/themeStore.ts`

- [ ] **Step 1: Update themeStore** — `mode: "dark" | "light" | "system"`, glass toggle, custom theme storage
- [ ] **Step 2: Add system mode listener** — `matchMedia("(prefers-color-scheme: dark)")` event listener
- [ ] **Step 3: Run tests**
- [ ] **Step 4: Commit**

### Task B3: Update ThemePicker UI

**Files:**
- Modify: `packages/terminal/src/components/theme/ThemePicker.tsx`

- [ ] **Step 1: Redesign picker** — 3 theme cards + dark/light/system toggle + glass toggle + custom builder
- [ ] **Step 2: Run tsc + vitest**
- [ ] **Step 3: Commit**

### Task B4: Remove Legacy Theme Files

**Files:**
- Remove: `packages/terminal/src/themes/light.css`
- Remove: `packages/terminal/src/themes/midnight.css`
- Remove: `packages/terminal/src/themes/obsidian.css`
- Remove: `packages/terminal/src/themes/ocean-blue.css`
- Remove: `packages/terminal/src/themes/terminal-green.css`
- Modify: `packages/terminal/src/index.css` (remove `@import "./themes/light.css"`)

- [ ] **Step 1: Remove 5 CSS files and their import**
- [ ] **Step 2: Remove `V1_THEME_MAP` and dead welcome icons**
- [ ] **Step 3: Run build to verify no broken imports**
- [ ] **Step 4: Commit**

---

## Phase C: Three Execution Modes

### Task C1: Mode Store

**Files:**
- Create: `packages/terminal/src/stores/modeStore.ts`
- Create: `packages/terminal/src/stores/__tests__/modeStore.test.ts`

- [ ] **Step 1: Create modeStore** — `mode: "demo" | "sandbox" | "live"`, persist to session (not localStorage)
- [ ] **Step 2: Tests for mode transitions** — PIN required for live, confirmation for all switches
- [ ] **Step 3: Commit**

### Task C2: Mock Data Engine

**Files:**
- Create: `packages/terminal/src/services/mockDataEngine.ts`
- Create: `packages/terminal/src/services/__tests__/mockDataEngine.test.ts`

- [ ] **Step 1: Build mock data generator** — realistic Indian market prices (NIFTY ~24,000, etc.), random walk ticks, simulated positions/orders/holdings/option chain
- [ ] **Step 2: Tests for price generation** — verify ranges, tick format, data completeness
- [ ] **Step 3: Commit**

### Task C3: Sandbox Paper Trading Engine

**Files:**
- Create: `packages/data/src/sandbox_engine.py`
- Create: `packages/data/tests/test_sandbox_engine.py`

- [ ] **Step 1: Build sandbox engine** — virtual capital, paper order validation, DuckDB `sandbox_trades` table, capital adjustment, data reset, JSON export/import
- [ ] **Step 2: Tests for paper trading** — place order, validate capital, compute P&L, reset, export/import
- [ ] **Step 3: Add sandbox API routes** — GET /sandbox/capital, POST /sandbox/adjust, POST /sandbox/reset, GET /sandbox/export, POST /sandbox/import
- [ ] **Step 4: Commit**

### Task C4: Mode Selection UI + TopBar Pill

**Files:**
- Create: `packages/terminal/src/routes/ModeSelectRoute.tsx`
- Modify: `packages/terminal/src/chrome/TopBar.tsx` (replace SandboxToggle with 3-way mode pill)
- Modify: `packages/terminal/src/chrome/SandboxToggle.tsx` (refactor to ModePill)

- [ ] **Step 1: Create ModeSelectRoute** — 3 cards (Demo/Sandbox/Live) shown at login
- [ ] **Step 2: Create ModePill** — grey DEMO / amber SANDBOX / green LIVE in TopBar with switch dialog + PIN for live
- [ ] **Step 3: Wire demo mode** — when mode=demo, use mockDataEngine instead of real API/WebSocket
- [ ] **Step 4: Run tsc + vitest**
- [ ] **Step 5: Commit**

### Task C5: Demo Mode Guided Tour

**Files:**
- Create: `packages/terminal/src/components/demo/DemoChoice.tsx`
- Modify: `packages/terminal/src/lib/tourDefinitions.ts` (add full guided tour)

- [ ] **Step 1: Create DemoChoice** — "Free Explore" vs "Guided Tour" choice card on first demo entry
- [ ] **Step 2: Extend tour definitions** — cover all routes (/trade, /invest, /learn, /lab, /automate, /ai)
- [ ] **Step 3: Commit**

### Task C6: Sandbox Controls UI

**Files:**
- Create: `packages/terminal/src/components/sandbox/SandboxControls.tsx`

- [ ] **Step 1: Build SandboxControls** — capital display + adjust, reset button with confirm, export JSON, import JSON
- [ ] **Step 2: Wire into Settings → Sandbox section and TopBar dropdown
- [ ] **Step 3: Commit**

---

## Phase D: Welcome Flow Changes

### Task D1: Remove Skip Button + Legacy Icons

**Files:**
- Modify: `packages/terminal/src/routes/WelcomeRoute.tsx`

- [ ] **Step 1: Remove skip button** (lines 332-341) and legacy theme icons (lines 47-53, 312-328)
- [ ] **Step 2: Run tsc + vitest**
- [ ] **Step 3: Commit**

### Task D2: New Welcome Flow — Setup + Login + Mode + Broker Dashboard

**Files:**
- Create: `packages/terminal/src/routes/SetupAccountRoute.tsx`
- Create: `packages/terminal/src/routes/BrokerDashboardRoute.tsx`
- Modify: `packages/terminal/src/routes/WelcomeRoute.tsx`
- Modify: `packages/terminal/src/main.tsx`

- [ ] **Step 1: Create SetupAccountRoute** — 6-step wizard merging account security (new) + persona/broker/trading/risk (from /setup) + mode selection (new)
- [ ] **Step 2: Create BrokerDashboardRoute** — all connected brokers with status, click to authenticate, "Skip for now" option
- [ ] **Step 3: Update WelcomeRoute** — cinematic → check if setup → SetupAccountRoute or LoginRoute → ModeSelect → BrokerDashboard → enter app
- [ ] **Step 4: Update main.tsx** — new route structure, remove /setup and /explore routes (redirect to /welcome)
- [ ] **Step 5: Run full test suite** — `npx vitest run` + `python -m pytest packages/ --import-mode=importlib -q`
- [ ] **Step 6: Commit**

### Task D3: Session Expiry at 8 AM IST

**Files:**
- Modify: `packages/terminal/src/stores/authStore.ts`
- Modify: `packages/terminal/src/routes/AppLayout.tsx`

- [ ] **Step 1: Add 8 AM IST timer** — on login, calculate ms until next 8:00 AM IST, setTimeout to force logout
- [ ] **Step 2: On expiry** — clear token, set status to "logged-out", redirect to /welcome
- [ ] **Step 3: Run tests**
- [ ] **Step 4: Commit**

---

## Execution Summary

| Phase | Tasks | Est. New Files | Est. Modified Files |
|-------|-------|---------------|-------------------|
| A: Auth | 4 tasks | 6 | 3 |
| B: Themes | 4 tasks | 1 | 4 + remove 5 |
| C: Modes | 6 tasks | 7 | 4 |
| D: Welcome | 3 tasks | 2 | 4 |
| **Total** | **17 tasks** | **16 new** | **15 modified** |

Build order: **A → B (can run parallel with A) → C (needs A) → D (needs A + C)**
