"""Regression coverage for upgrading pre-deferred-TOTP account databases."""

from __future__ import annotations

import sqlite3
from datetime import UTC, datetime
from pathlib import Path

import argon2
import pyotp
from flask import Flask

from flinttrade_core.auth_routes import auth_bp
from flinttrade_core.auth_service import AuthService, _derive_fernet_key


_PASSWORD = "LegacyStrongP@ss123!"
_TOTP_SECRET = "JBSWY3DPEHPK3PXP"


def _create_legacy_account_db(db_path: Path) -> None:
    """Create the account schema used before optional TOTP enrolment."""
    password_hash = argon2.PasswordHasher(
        time_cost=3,
        memory_cost=65_536,
        parallelism=4,
    ).hash(_PASSWORD)
    salt = b"legacy-salt-1234"
    encrypted_secret = _derive_fernet_key(_PASSWORD, salt).encrypt(
        _TOTP_SECRET.encode("utf-8")
    )

    with sqlite3.connect(db_path) as db:
        db.execute("""
            CREATE TABLE account (
                id INTEGER PRIMARY KEY CHECK (id = 1),
                username TEXT NOT NULL,
                email TEXT NOT NULL,
                password_hash TEXT NOT NULL,
                pin_hash TEXT NOT NULL,
                totp_secret_encrypted BLOB NOT NULL,
                totp_salt BLOB NOT NULL,
                created_at TEXT NOT NULL,
                password_changed_at REAL NOT NULL DEFAULT 0
            )
        """)
        db.execute(
            """INSERT INTO account
               (id, username, email, password_hash, pin_hash,
                totp_secret_encrypted, totp_salt, created_at)
               VALUES (1, ?, ?, ?, '', ?, ?, ?)""",
            (
                "legacy",
                "legacy@example.com",
                password_hash,
                encrypted_secret,
                salt,
                datetime.now(UTC).isoformat(),
            ),
        )


def _auth_client(svc: AuthService, tmp_path: Path, monkeypatch):
    """Return a real auth-route client isolated to the temporary workspace."""
    monkeypatch.setenv("FLINTTRADE_WORKSPACE_DIR", str(tmp_path / "workspace"))
    app = Flask(__name__)
    app.config.update(TESTING=True, AUTH_SERVICE=svc, LIMITER=object())
    app.register_blueprint(auth_bp)
    return app.test_client()


def test_legacy_upgrade_keeps_totp_required_for_daily_login(tmp_path, monkeypatch):
    """Adding the enrolment flag must not weaken an established account."""
    db_path = tmp_path / "auth.db"
    _create_legacy_account_db(db_path)

    svc = AuthService(db_path=db_path)
    assert svc.is_totp_enabled() is True

    with _auth_client(svc, tmp_path, monkeypatch) as client:
        missing = client.post("/v1/auth/login", json={"password": _PASSWORD})
        wrong = client.post(
            "/v1/auth/login",
            json={"password": _PASSWORD, "totp_code": "000000"},
        )
        correct = client.post(
            "/v1/auth/login",
            json={
                "password": _PASSWORD,
                "totp_code": pyotp.TOTP(_TOTP_SECRET).now(),
            },
        )

    assert missing.status_code == 401
    assert wrong.status_code == 401
    assert correct.status_code == 200


def test_fresh_and_reopened_deferred_account_keeps_totp_optional(
    tmp_path,
    monkeypatch,
):
    """A new deferred account stays password-only after service restart."""
    db_path = tmp_path / "auth.db"
    svc = AuthService(db_path=db_path)
    svc.setup_account(
        username="fresh",
        email="fresh@example.com",
        password=_PASSWORD,
        pin="",
    )
    assert svc.is_totp_enabled() is False
    svc._db.close()

    svc = AuthService(db_path=db_path)
    assert svc.is_totp_enabled() is False

    with _auth_client(svc, tmp_path, monkeypatch) as client:
        response = client.post("/v1/auth/login", json={"password": _PASSWORD})

    assert response.status_code == 200


def test_legacy_upgrade_then_wipe_creates_a_deferred_account(tmp_path):
    """The legacy-only schema default must not affect later account setup."""
    db_path = tmp_path / "auth.db"
    _create_legacy_account_db(db_path)
    svc = AuthService(db_path=db_path)
    assert svc.is_totp_enabled() is True

    svc.wipe_account()
    svc.setup_account(
        username="replacement",
        email="replacement@example.com",
        password=_PASSWORD,
        pin="",
    )

    assert svc.is_totp_enabled() is False
