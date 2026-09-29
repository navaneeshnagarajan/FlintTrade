# packages/core/core/tests/test_auth_service.py
"""Tests for auth service — credential storage, hashing, verification."""

from __future__ import annotations

import logging
import sqlite3
import threading
from datetime import UTC, datetime
from pathlib import Path

import pytest

from flinttrade_core.auth_service import AuthService


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

    def test_setup_finished_stays_false_until_marked_and_clears_on_wipe(self, tmp_path: Path):
        svc = AuthService(db_path=tmp_path / "auth.db")
        assert svc.is_setup_finished() is False
        svc.setup_account(
            username="alice", email="alice@example.com",
            password="StrongP@ss123!", pin="",
        )
        assert svc.is_setup_finished() is False
        svc.mark_setup_finished()
        assert svc.is_setup_finished() is True
        reopened = AuthService(db_path=tmp_path / "auth.db")
        assert reopened.is_setup_finished() is True
        reopened.wipe_account()
        assert reopened.is_setup() is False
        assert reopened.is_setup_finished() is False

    def test_vault_presecured_freezes_at_the_first_record(self, tmp_path: Path):
        svc = AuthService(db_path=tmp_path / "auth.db")
        assert svc.setup_vault_presecured() is None
        svc.setup_account("alice", "alice@example.com", "StrongP@ss123!")
        assert svc.setup_vault_presecured() is None
        svc.record_setup_vault_presecured(False)
        assert svc.setup_vault_presecured() is False
        svc.record_setup_vault_presecured(True)
        assert svc.setup_vault_presecured() is False
        reopened = AuthService(db_path=tmp_path / "auth.db")
        assert reopened.setup_vault_presecured() is False


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


class TestSetPin:
    """Post-setup PIN set/change — ASCII ^\\d{6}$ only (FT-SET-003)."""

    def _ready(self, tmp_path: Path) -> AuthService:
        svc = AuthService(db_path=tmp_path / "auth.db")
        svc.setup_account(
            username="alice",
            email="alice@example.com",
            password="StrongP@ss123!",
            pin="",
        )
        return svc

    @pytest.mark.parametrize("pin", ["12345", "1234567", "12ab56", "１２３４５６"])
    def test_set_pin_rejects_non_six_ascii_digits(self, tmp_path: Path, pin: str):
        svc = self._ready(tmp_path)
        with pytest.raises(ValueError, match="exactly 6 digits"):
            svc.set_pin("StrongP@ss123!", pin)
        assert svc.has_pin() is False

    def test_set_pin_accepts_six_ascii_digits(self, tmp_path: Path):
        svc = self._ready(tmp_path)
        assert svc.set_pin("StrongP@ss123!", "654321") is True
        assert svc.has_pin() is True
        assert svc.verify_pin("654321") is True


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

    def test_setup_leaves_authenticator_deferred(self, tmp_path: Path):
        """FT-SETUP-002: Explore/Practice start password-only. TOTP is
        provisioned but not enrolled until the operator confirms a code."""
        svc = AuthService(db_path=tmp_path / "auth.db")
        svc.setup_account(
            username="alice", email="alice@example.com",
            password="StrongP@ss123!", pin="123456",
        )
        assert svc.is_totp_enabled() is False

    def test_enable_totp_requires_a_live_code(self, tmp_path: Path):
        import pyotp
        svc = AuthService(db_path=tmp_path / "auth.db")
        svc.setup_account(
            username="alice", email="alice@example.com",
            password="StrongP@ss123!", pin="123456",
        )
        assert svc.enable_totp("000000") is False
        assert svc.is_totp_enabled() is False
        code = pyotp.TOTP(svc.get_totp_secret()).now()
        assert svc.enable_totp(code) is True
        assert svc.is_totp_enabled() is True

    def test_regenerate_totp_defers_enrolment_again(self, tmp_path: Path):
        import pyotp
        svc = AuthService(db_path=tmp_path / "auth.db")
        svc.setup_account(
            username="alice", email="alice@example.com",
            password="StrongP@ss123!", pin="123456",
        )
        svc.enable_totp(pyotp.TOTP(svc.get_totp_secret()).now())
        assert svc.is_totp_enabled() is True
        result = svc.regenerate_totp("StrongP@ss123!")
        assert result is not None
        assert svc.is_totp_enabled() is False


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

    def test_wipe_account_without_password(self, tmp_path: Path):
        svc = self._fresh(tmp_path)
        svc.wipe_account()
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


class TestPasswordChangedAtStamp:
    """update_password() must stamp ``password_changed_at`` so previously
    issued JWTs (whose ``iat`` predates the change) can be rejected at
    decode time. Mirrors OpenAlgo v2.0.0.7's session-invalidation behaviour.
    """

    def _fresh(self, tmp_path: Path) -> AuthService:
        svc = AuthService(db_path=tmp_path / "auth.db")
        svc.setup_account(
            username="alice",
            email="alice@example.com",
            password="StrongP@ss123!",
            pin="123456",
        )
        return svc

    def test_get_password_changed_at_zero_after_setup(self, tmp_path: Path):
        svc = self._fresh(tmp_path)
        # The new column starts at 0 — setup_account does NOT touch it
        # because there is no prior session to invalidate.
        assert svc.get_password_changed_at() == 0.0

    def test_update_password_stamps_password_changed_at(self, tmp_path: Path):
        import time as _time
        svc = self._fresh(tmp_path)
        before = _time.time()
        assert svc.update_password("alice", "NewStrongP@ss!234")
        stamp = svc.get_password_changed_at()
        # Stamp should be a fresh epoch — never zero, never far in the past.
        assert stamp >= before - 1.0
        assert stamp <= _time.time() + 1.0

    def test_update_password_with_unknown_username_does_not_stamp(self, tmp_path: Path):
        svc = self._fresh(tmp_path)
        assert svc.update_password("bob", "NewStrongP@ss!234") is False
        # Stamp stays at the post-setup zero because no row was updated.
        assert svc.get_password_changed_at() == 0.0


def _operator_count(db_path: Path) -> int:
    conn = sqlite3.connect(db_path)
    try:
        row = conn.execute("SELECT COUNT(*) FROM account").fetchone()
    finally:
        conn.close()
    assert row is not None
    return int(row[0])


def _login_attempt_count(db_path: Path) -> int:
    conn = sqlite3.connect(db_path)
    try:
        row = conn.execute("SELECT COUNT(*) FROM login_attempts").fetchone()
    finally:
        conn.close()
    assert row is not None
    return int(row[0])


def _assert_already_has_operator(errors: list[BaseException]) -> None:
    """Losers take the normal already-set-up refusal, not a lock or busy error."""
    assert errors
    for exc in errors:
        assert type(exc) is RuntimeError
        assert str(exc) == "Account already set up"
        assert exc.__cause__ is None


def _index_names(db_path: Path) -> set[str]:
    conn = sqlite3.connect(db_path)
    try:
        rows = conn.execute(
            "SELECT name FROM sqlite_master WHERE type = 'index'"
        ).fetchall()
    finally:
        conn.close()
    return {str(row[0]) for row in rows}


def _seed_unchecked_operators(db_path: Path, usernames: list[str]) -> None:
    """Create an account table that does not yet enforce a single operator."""
    conn = sqlite3.connect(db_path)
    try:
        conn.execute("""
            CREATE TABLE account (
                id INTEGER PRIMARY KEY,
                username TEXT NOT NULL,
                email TEXT NOT NULL,
                password_hash TEXT NOT NULL,
                pin_hash TEXT NOT NULL,
                totp_secret_encrypted BLOB NOT NULL,
                totp_salt BLOB NOT NULL,
                totp_enabled INTEGER NOT NULL DEFAULT 0,
                created_at TEXT NOT NULL
            )
        """)
        created = datetime.now(UTC).isoformat()
        for operator_id, username in enumerate(usernames, start=1):
            conn.execute(
                """INSERT INTO account (
                       id, username, email, password_hash, pin_hash,
                       totp_secret_encrypted, totp_salt, totp_enabled, created_at
                   ) VALUES (?, ?, ?, 'hash', '', ?, ?, 0, ?)""",
                (
                    operator_id,
                    username,
                    f"{username}@example.com",
                    b"secret",
                    b"salt",
                    created,
                ),
            )
        conn.commit()
    finally:
        conn.close()


def _backup_code_count(db_path: Path) -> int:
    conn = sqlite3.connect(db_path)
    try:
        row = conn.execute("SELECT COUNT(*) FROM backup_codes").fetchone()
    finally:
        conn.close()
    assert row is not None
    return int(row[0])


class TestAuthStoreConcurrency:
    """Status reads stay consistent while writes run, and setup cannot double-create."""

    @pytest.mark.unit
    def test_status_reads_stay_consistent_during_writes(self, tmp_path: Path) -> None:
        db_path = tmp_path / "auth.db"
        svc = AuthService(db_path=db_path)
        svc.setup_account(
            username="alice",
            email="alice@example.com",
            password="StrongP@ss123!",
            pin="123456",
        )
        svc.record_setup_vault_presecured(True)
        svc.mark_setup_finished()

        journal = svc._db.execute("PRAGMA journal_mode").fetchone()
        busy = svc._db.execute("PRAGMA busy_timeout").fetchone()
        assert journal is not None
        assert str(journal[0]).lower() == "wal"
        assert busy is not None
        assert int(busy[0]) >= 5000

        reader_count = 8
        reads_each = 1_500
        stop = threading.Event()
        errors: list[BaseException] = []
        wrong_setup: list[object] = []
        missing_vault: list[object] = []
        wrong_finished: list[object] = []
        wrong_profile: list[object] = []
        record: threading.Lock = threading.Lock()

        def reader() -> None:
            try:
                for _ in range(reads_each):
                    setup = svc.is_setup()
                    finished = svc.is_setup_finished()
                    vault = svc.setup_vault_presecured()
                    profile = svc.get_profile()
                    locked = svc.is_locked()
                    has_pin = svc.has_pin()
                    if setup is not True:
                        with record:
                            wrong_setup.append(setup)
                    if vault is None or vault is not True:
                        with record:
                            missing_vault.append(vault)
                    if finished is not True:
                        with record:
                            wrong_finished.append(finished)
                    if profile.get("username") != "alice" or locked is not False or has_pin is not True:
                        with record:
                            wrong_profile.append((profile, locked, has_pin))
            except BaseException as exc:
                with record:
                    errors.append(exc)

        def writer() -> None:
            while not stop.is_set():
                svc.mark_setup_finished()
                svc.record_setup_vault_presecured(False)
                svc._record_attempt(success=True)

        readers = [threading.Thread(target=reader) for _ in range(reader_count)]
        writer_thread = threading.Thread(target=writer)
        writer_thread.start()
        for thread in readers:
            thread.start()
        for thread in readers:
            thread.join(timeout=30)
        stop.set()
        writer_thread.join(timeout=5)

        read_total = reader_count * reads_each
        assert all(not thread.is_alive() for thread in readers)
        assert not writer_thread.is_alive()
        attempts = _login_attempt_count(db_path)
        assert errors == [], f"{len(errors)} exceptions in {read_total} reads: {errors[:3]}"
        assert wrong_setup == [], f"is_setup was wrong {len(wrong_setup)} times in {read_total} reads"
        assert missing_vault == [], (
            f"vault state was missing or wrong {len(missing_vault)} times in {read_total} reads"
        )
        assert wrong_finished == [], f"setup_finished was wrong {len(wrong_finished)} times in {read_total} reads"
        assert wrong_profile == []
        assert attempts > 0, "status reads finished before any concurrent write"
        assert _operator_count(db_path) == 1

    @pytest.mark.unit
    def test_parallel_setup_against_existing_operator_all_refuse(self, tmp_path: Path) -> None:
        db_path = tmp_path / "auth.db"
        svc = AuthService(db_path=db_path)
        svc.setup_account(
            username="alice",
            email="alice@example.com",
            password="StrongP@ss123!",
            pin="123456",
        )
        # A stale "not set up" answer must still refuse inside the write.
        svc.is_setup = lambda: False  # type: ignore[method-assign]

        callers = 8
        errors: list[BaseException] = []
        successes: list[list[str]] = []
        record = threading.Lock()

        def attempt(index: int) -> None:
            try:
                codes = svc.setup_account(
                    username=f"user{index}",
                    email=f"user{index}@example.com",
                    password="StrongP@ss123!",
                    pin="654321",
                )
            except BaseException as exc:
                with record:
                    errors.append(exc)
            else:
                with record:
                    successes.append(codes)

        threads = [threading.Thread(target=attempt, args=(index,)) for index in range(callers)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join(timeout=60)

        assert all(not thread.is_alive() for thread in threads)
        assert successes == []
        assert len(errors) == callers
        _assert_already_has_operator(errors)
        assert _operator_count(db_path) == 1
        assert _backup_code_count(db_path) == 8
        assert svc.get_profile()["username"] == "alice"

    @pytest.mark.unit
    def test_fresh_setup_race_lets_exactly_one_create_win(self, tmp_path: Path) -> None:
        db_path = tmp_path / "auth.db"
        svc = AuthService(db_path=db_path)
        callers = 8
        errors: list[BaseException] = []
        successes: list[list[str]] = []
        record = threading.Lock()

        def attempt(index: int) -> None:
            try:
                codes = svc.setup_account(
                    username=f"user{index}",
                    email=f"user{index}@example.com",
                    password="StrongP@ss123!",
                    pin="123456",
                )
            except BaseException as exc:
                with record:
                    errors.append(exc)
            else:
                with record:
                    successes.append(codes)

        threads = [threading.Thread(target=attempt, args=(index,)) for index in range(callers)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join(timeout=60)

        assert all(not thread.is_alive() for thread in threads)
        assert len(successes) == 1
        assert len(successes[0]) == 8
        assert len(errors) == callers - 1
        _assert_already_has_operator(errors)
        assert _operator_count(db_path) == 1
        assert _backup_code_count(db_path) == 8


class TestSingleOperatorMigration:
    """A second operator row is refused, and an already-duplicated file is kept."""

    @pytest.mark.unit
    def test_one_existing_operator_gains_the_single_row_index(self, tmp_path: Path) -> None:
        db_path = tmp_path / "auth.db"
        _seed_unchecked_operators(db_path, ["alice"])

        AuthService(db_path=db_path)

        assert "account_one_operator" in _index_names(db_path)
        assert _operator_count(db_path) == 1
        conn = sqlite3.connect(db_path)
        try:
            with pytest.raises(sqlite3.IntegrityError):
                conn.execute(
                    """INSERT INTO account (
                           id, username, email, password_hash, pin_hash,
                           totp_secret_encrypted, totp_salt, created_at
                       )
                       SELECT 2, 'bob', email, password_hash, pin_hash,
                              totp_secret_encrypted, totp_salt, created_at
                       FROM account WHERE id = 1"""
                )
        finally:
            conn.close()
        assert _operator_count(db_path) == 1

    @pytest.mark.unit
    def test_existing_duplicate_operators_are_kept_and_the_migration_is_refused(
        self, tmp_path: Path, caplog: pytest.LogCaptureFixture,
    ) -> None:
        db_path = tmp_path / "auth.db"
        _seed_unchecked_operators(db_path, ["alice", "bob"])

        with caplog.at_level(logging.ERROR, logger="flinttrade.auth"):
            svc = AuthService(db_path=db_path)

        assert _operator_count(db_path) == 2
        assert "account_one_operator" not in _index_names(db_path)
        assert any(
            "Refusing the single-operator migration" in record.message
            and "2 operator rows already exist" in record.message
            and "Leaving the existing rows in place" in record.message
            for record in caplog.records
        )
        with pytest.raises(RuntimeError, match="Account already set up"):
            svc.setup_account(
                username="carol",
                email="carol@example.com",
                password="StrongP@ss123!",
                pin="123456",
            )
        assert _operator_count(db_path) == 2
        conn = sqlite3.connect(db_path)
        try:
            names = {
                str(row[0])
                for row in conn.execute("SELECT username FROM account ORDER BY id")
            }
        finally:
            conn.close()
        assert names == {"alice", "bob"}
