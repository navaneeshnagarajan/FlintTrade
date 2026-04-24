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


class TestSetupEscapeHatches:
    """Reset/regenerate paths exposed to the setup wizard."""

    def _fresh(self, tmp_path: Path) -> AuthService:
        svc = AuthService(db_path=tmp_path / "auth.db")
        svc.setup_account(
            username="alice", email="alice@example.com",
            password="StrongP@ss123!", pin="",
        )
        return svc

    def test_reset_account_wipes_user(self, tmp_path: Path):
        svc = self._fresh(tmp_path)
        assert svc.is_setup() is True
        assert svc.reset_account("StrongP@ss123!") is True
        assert svc.is_setup() is False

    def test_reset_account_rejects_wrong_password(self, tmp_path: Path):
        svc = self._fresh(tmp_path)
        assert svc.reset_account("WrongPassword") is False
        assert svc.is_setup() is True

    def test_reset_account_allows_fresh_setup_after(self, tmp_path: Path):
        svc = self._fresh(tmp_path)
        svc.reset_account("StrongP@ss123!")
        # Account was wiped — a fresh setup_account should succeed, not 409.
        svc.setup_account(
            username="bob", email="bob@example.com",
            password="AnotherP@ss123!", pin="",
        )
        assert svc.get_profile()["username"] == "bob"

    def test_regenerate_totp_issues_fresh_secret(self, tmp_path: Path):
        svc = self._fresh(tmp_path)
        svc.verify_password("StrongP@ss123!")  # prime the TOTP cache
        original_uri = svc.get_totp_provisioning_uri()
        result = svc.regenerate_totp("StrongP@ss123!")
        assert result is not None
        new_uri, codes = result
        assert new_uri != original_uri  # different secret encoded in URI
        assert new_uri.startswith("otpauth://totp/")
        assert len(codes) == 8
        assert all(len(c) == 8 for c in codes)

    def test_regenerate_totp_invalidates_old_backup_codes(self, tmp_path: Path):
        # Fresh service so the first 8 codes are the ones we capture.
        svc = AuthService(db_path=tmp_path / "auth.db")
        old_codes = svc.setup_account(
            username="alice", email="alice@example.com",
            password="StrongP@ss123!", pin="",
        )
        result = svc.regenerate_totp("StrongP@ss123!")
        assert result is not None
        _, new_codes = result
        # None of the old codes should still verify — they were deleted.
        for code in old_codes:
            assert svc.verify_backup_code(code) is False
        # The newly issued codes DO verify.
        assert svc.verify_backup_code(new_codes[0]) is True

    def test_regenerate_totp_rejects_wrong_password(self, tmp_path: Path):
        svc = self._fresh(tmp_path)
        assert svc.regenerate_totp("WrongPassword") is None
