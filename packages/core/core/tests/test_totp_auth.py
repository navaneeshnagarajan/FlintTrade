# packages/core/core/tests/test_totp_auth.py
"""Tests for TOTPAuth — user-facing TOTP 2FA.

Coverage:
- Secret generation: returns valid base32, correct backup code count,
  uniqueness, regeneration replaces old secret and codes
- Provisioning URI: format, secret presence, issuer, user label
- Token verification: valid/invalid/wrong user/disabled
- Backup code consumption: valid, one-time use, decrements count
- Disable flow: valid token disables, invalid token rejected, re-enable
- QR code SVG generation
- Persistence across DB reopen
"""

from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import patch

import pyotp
import pytest

from flinttrade_core.totp_auth import TOTPAuth, _BACKUP_CODE_COUNT


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture()
def auth(tmp_path: Path) -> TOTPAuth:
    """Fresh TOTPAuth backed by a temp DuckDB file."""
    instance = TOTPAuth(db_path=tmp_path / "totp.duckdb")
    yield instance
    instance.close()


# ---------------------------------------------------------------------------
# Secret generation
# ---------------------------------------------------------------------------


def test_generate_returns_valid_base32_secret(auth: TOTPAuth) -> None:
    """generate_secret returns a secret that pyotp accepts."""
    secret, _ = auth.generate_secret("u1")
    totp = pyotp.TOTP(secret)
    assert len(totp.now()) == 6


def test_generate_returns_correct_backup_code_count(auth: TOTPAuth) -> None:
    _, codes = auth.generate_secret("u2")
    assert len(codes) == _BACKUP_CODE_COUNT


def test_backup_codes_are_8_char_uppercase_hex(auth: TOTPAuth) -> None:
    _, codes = auth.generate_secret("u3")
    for code in codes:
        assert len(code) == 8
        assert code == code.upper()
        int(code, 16)  # Raises ValueError if not valid hex


def test_backup_codes_are_unique(auth: TOTPAuth) -> None:
    _, codes = auth.generate_secret("u4")
    assert len(set(codes)) == len(codes)


def test_regenerating_replaces_secret(auth: TOTPAuth) -> None:
    secret1, _ = auth.generate_secret("u5")
    secret2, _ = auth.generate_secret("u5")
    assert secret1 != secret2


def test_regenerating_replaces_backup_codes(auth: TOTPAuth) -> None:
    _, codes1 = auth.generate_secret("u6")
    _, codes2 = auth.generate_secret("u6")
    assert set(codes1).isdisjoint(set(codes2))


def test_is_enabled_true_after_generate(auth: TOTPAuth) -> None:
    auth.generate_secret("u7")
    assert auth.is_enabled("u7") is True


def test_is_enabled_false_for_unknown_user(auth: TOTPAuth) -> None:
    assert auth.is_enabled("nonexistent") is False


# ---------------------------------------------------------------------------
# Provisioning URI
# ---------------------------------------------------------------------------


def test_provisioning_uri_starts_with_otpauth(auth: TOTPAuth) -> None:
    secret, _ = auth.generate_secret("uri1")
    uri = auth.provisioning_uri("uri1", secret)
    assert uri.startswith("otpauth://totp/")


def test_provisioning_uri_contains_secret(auth: TOTPAuth) -> None:
    secret, _ = auth.generate_secret("uri2")
    uri = auth.provisioning_uri("uri2", secret)
    assert f"secret={secret}" in uri


def test_provisioning_uri_contains_issuer(auth: TOTPAuth) -> None:
    secret, _ = auth.generate_secret("uri3")
    uri = auth.provisioning_uri("uri3", secret, issuer="FlintTrade")
    assert "FlintTrade" in uri


def test_provisioning_uri_contains_user_id(auth: TOTPAuth) -> None:
    user_id = "trader@example.com"
    secret, _ = auth.generate_secret(user_id)
    uri = auth.provisioning_uri(user_id, secret)
    assert "trader" in uri


# ---------------------------------------------------------------------------
# Token verification
# ---------------------------------------------------------------------------


def test_valid_token_returns_true(auth: TOTPAuth) -> None:
    secret, _ = auth.generate_secret("vt1")
    token = pyotp.TOTP(secret).now()
    assert auth.verify_token("vt1", token) is True


def test_invalid_token_returns_false(auth: TOTPAuth) -> None:
    auth.generate_secret("vt2")
    assert auth.verify_token("vt2", "000000") is False


def test_wrong_user_returns_false(auth: TOTPAuth) -> None:
    auth.generate_secret("vt3")
    assert auth.verify_token("nonexistent_user", "123456") is False


def test_token_after_disable_returns_false(auth: TOTPAuth) -> None:
    secret, _ = auth.generate_secret("vt4")
    token = pyotp.TOTP(secret).now()
    auth.disable("vt4", token)
    # After disable, even a fresh token must fail
    fresh_token = pyotp.TOTP(secret).now()
    assert auth.verify_token("vt4", fresh_token) is False


def test_token_wrong_length_returns_false(auth: TOTPAuth) -> None:
    auth.generate_secret("vt5")
    assert auth.verify_token("vt5", "12345") is False


# ---------------------------------------------------------------------------
# Backup code consumption
# ---------------------------------------------------------------------------


def test_valid_backup_code_returns_true(auth: TOTPAuth) -> None:
    _, codes = auth.generate_secret("bc1")
    assert auth.consume_backup_code("bc1", codes[0]) is True


def test_same_backup_code_cannot_be_used_twice(auth: TOTPAuth) -> None:
    _, codes = auth.generate_secret("bc2")
    auth.consume_backup_code("bc2", codes[0])
    assert auth.consume_backup_code("bc2", codes[0]) is False


def test_invalid_backup_code_returns_false(auth: TOTPAuth) -> None:
    auth.generate_secret("bc3")
    assert auth.consume_backup_code("bc3", "FFFFFFFF") is False


def test_remaining_backup_codes_decrements_on_consume(auth: TOTPAuth) -> None:
    _, codes = auth.generate_secret("bc4")
    before = auth.remaining_backup_codes("bc4")
    auth.consume_backup_code("bc4", codes[0])
    assert auth.remaining_backup_codes("bc4") == before - 1


def test_all_backup_codes_usable_exactly_once(auth: TOTPAuth) -> None:
    _, codes = auth.generate_secret("bc5")
    for code in codes:
        assert auth.consume_backup_code("bc5", code) is True
    assert auth.remaining_backup_codes("bc5") == 0


def test_remaining_backup_codes_zero_for_unknown_user(auth: TOTPAuth) -> None:
    assert auth.remaining_backup_codes("nobody") == 0


# ---------------------------------------------------------------------------
# Disable flow
# ---------------------------------------------------------------------------


def test_disable_with_valid_token_returns_true(auth: TOTPAuth) -> None:
    secret, _ = auth.generate_secret("d1")
    token = pyotp.TOTP(secret).now()
    assert auth.disable("d1", token) is True


def test_disable_with_invalid_token_returns_false(auth: TOTPAuth) -> None:
    auth.generate_secret("d2")
    assert auth.disable("d2", "000000") is False


def test_is_enabled_false_after_disable(auth: TOTPAuth) -> None:
    secret, _ = auth.generate_secret("d3")
    token = pyotp.TOTP(secret).now()
    auth.disable("d3", token)
    assert auth.is_enabled("d3") is False


def test_is_enabled_true_after_regenerate_following_disable(auth: TOTPAuth) -> None:
    secret, _ = auth.generate_secret("d4")
    token = pyotp.TOTP(secret).now()
    auth.disable("d4", token)
    auth.generate_secret("d4")
    assert auth.is_enabled("d4") is True


# ---------------------------------------------------------------------------
# QR code generation
# ---------------------------------------------------------------------------


def test_qr_code_svg_returns_svg_markup(auth: TOTPAuth) -> None:
    pytest.importorskip("qrcode", reason="qrcode[svg] not installed")
    secret, _ = auth.generate_secret("qr1")
    uri = auth.provisioning_uri("qr1", secret)
    svg = auth.qr_code_svg(uri)
    assert "svg" in svg.lower()


def test_qr_code_svg_raises_import_error_without_qrcode(auth: TOTPAuth) -> None:
    secret, _ = auth.generate_secret("qr2")
    uri = auth.provisioning_uri("qr2", secret)
    with patch.dict(sys.modules, {"qrcode": None, "qrcode.image.svg": None}):
        with pytest.raises(ImportError, match="qrcode"):
            auth.qr_code_svg(uri)


# ---------------------------------------------------------------------------
# Persistence
# ---------------------------------------------------------------------------


def test_secret_persists_across_db_reopen(tmp_path: Path) -> None:
    db = tmp_path / "persist.duckdb"
    auth1 = TOTPAuth(db_path=db)
    user_id = "persist_user"
    secret, _ = auth1.generate_secret(user_id)
    auth1.close()

    auth2 = TOTPAuth(db_path=db)
    token = pyotp.TOTP(secret).now()
    assert auth2.verify_token(user_id, token) is True
    auth2.close()


def test_backup_codes_persist_across_db_reopen(tmp_path: Path) -> None:
    db = tmp_path / "persist2.duckdb"
    auth1 = TOTPAuth(db_path=db)
    user_id = "persist_bc"
    _, codes = auth1.generate_secret(user_id)
    auth1.close()

    auth2 = TOTPAuth(db_path=db)
    assert auth2.consume_backup_code(user_id, codes[1]) is True
    auth2.close()
