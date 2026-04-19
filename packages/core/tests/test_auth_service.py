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
        assert profile["email"] == "alice@example.com"

    def test_setup_rejects_weak_password(self, tmp_path: Path):
        svc = AuthService(db_path=tmp_path / "auth.db")
        with pytest.raises(ValueError, match="too weak"):
            svc.setup_account(
                username="alice", email="alice@example.com",
                password="123", pin="123456",
            )

    def test_setup_rejects_non_6_digit_pin(self, tmp_path: Path):
        svc = AuthService(db_path=tmp_path / "auth.db")
        with pytest.raises(ValueError, match="6 digits"):
            svc.setup_account(
                username="alice", email="alice@example.com",
                password="StrongP@ss123!", pin="12345",
            )

    def test_is_setup_returns_false_before_setup(self, tmp_path: Path):
        svc = AuthService(db_path=tmp_path / "auth.db")
        assert svc.is_setup() is False

    def test_is_setup_returns_true_after_setup(self, tmp_path: Path):
        svc = AuthService(db_path=tmp_path / "auth.db")
        svc.setup_account(
            username="alice", email="alice@example.com",
            password="StrongP@ss123!", pin="123456",
        )
        assert svc.is_setup() is True


class TestPasswordVerification:
    """Password login."""

    def test_verify_correct_password(self, tmp_path: Path):
        svc = AuthService(db_path=tmp_path / "auth.db")
        svc.setup_account(
            username="alice", email="alice@example.com",
            password="StrongP@ss123!", pin="123456",
        )
        assert svc.verify_password("StrongP@ss123!") is True

    def test_verify_wrong_password(self, tmp_path: Path):
        svc = AuthService(db_path=tmp_path / "auth.db")
        svc.setup_account(
            username="alice", email="alice@example.com",
            password="StrongP@ss123!", pin="123456",
        )
        assert svc.verify_password("wrong") is False


class TestPinVerification:
    """PIN quick-unlock."""

    def test_verify_correct_pin(self, tmp_path: Path):
        svc = AuthService(db_path=tmp_path / "auth.db")
        svc.setup_account(
            username="alice", email="alice@example.com",
            password="StrongP@ss123!", pin="123456",
        )
        assert svc.verify_pin("123456") is True

    def test_verify_wrong_pin(self, tmp_path: Path):
        svc = AuthService(db_path=tmp_path / "auth.db")
        svc.setup_account(
            username="alice", email="alice@example.com",
            password="StrongP@ss123!", pin="123456",
        )
        assert svc.verify_pin("000000") is False


class TestTOTP:
    """2FA TOTP setup and verification."""

    def test_setup_generates_totp_secret(self, tmp_path: Path):
        svc = AuthService(db_path=tmp_path / "auth.db")
        svc.setup_account(
            username="alice", email="alice@example.com",
            password="StrongP@ss123!", pin="123456",
        )
        secret = svc.get_totp_secret()
        assert secret is not None
        assert len(secret) >= 16

    def test_verify_totp_with_valid_code(self, tmp_path: Path):
        import pyotp
        svc = AuthService(db_path=tmp_path / "auth.db")
        svc.setup_account(
            username="alice", email="alice@example.com",
            password="StrongP@ss123!", pin="123456",
        )
        secret = svc.get_totp_secret()
        totp = pyotp.TOTP(secret)
        assert svc.verify_totp(totp.now()) is True

    def test_verify_totp_with_invalid_code(self, tmp_path: Path):
        svc = AuthService(db_path=tmp_path / "auth.db")
        svc.setup_account(
            username="alice", email="alice@example.com",
            password="StrongP@ss123!", pin="123456",
        )
        assert svc.verify_totp("000000") is False


class TestBackupCodes:
    """Recovery backup codes."""

    def test_setup_generates_8_backup_codes(self, tmp_path: Path):
        svc = AuthService(db_path=tmp_path / "auth.db")
        codes = svc.setup_account(
            username="alice", email="alice@example.com",
            password="StrongP@ss123!", pin="123456",
        )
        assert len(codes) == 8
        assert all(len(c) >= 8 for c in codes)

    def test_backup_code_works_once(self, tmp_path: Path):
        svc = AuthService(db_path=tmp_path / "auth.db")
        codes = svc.setup_account(
            username="alice", email="alice@example.com",
            password="StrongP@ss123!", pin="123456",
        )
        assert svc.verify_backup_code(codes[0]) is True
        assert svc.verify_backup_code(codes[0]) is False  # Used, can't reuse


class TestLoginAttempts:
    """Rate limiting — 5 failures → lockout."""

    def test_lockout_after_5_failures(self, tmp_path: Path):
        svc = AuthService(db_path=tmp_path / "auth.db")
        svc.setup_account(
            username="alice", email="alice@example.com",
            password="StrongP@ss123!", pin="123456",
        )
        for _ in range(5):
            svc.verify_password("wrong")
        assert svc.is_locked() is True

    def test_locked_rejects_even_correct_password(self, tmp_path: Path):
        svc = AuthService(db_path=tmp_path / "auth.db")
        svc.setup_account(
            username="alice", email="alice@example.com",
            password="StrongP@ss123!", pin="123456",
        )
        for _ in range(5):
            svc.verify_password("wrong")
        assert svc.verify_password("StrongP@ss123!") is False
