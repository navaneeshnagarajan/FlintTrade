"""Retain the historical schema utility without claiming runtime migration.

These DDL controls are not proof of current AuthState reader compatibility.
Migration refuses unowned destinations and verifies the actual SQLite reader.
Public CLI/crypto regressions live under scripts/__tests__/.
"""

from __future__ import annotations

import argparse
import importlib.util
import sqlite3
from pathlib import Path

import pytest

pytestmark = pytest.mark.integration

_MIG_PATH = Path(__file__).resolve().parents[4] / "scripts" / "migrate-auth-state-duckdb-to-sqlite.py"


def _load():
    spec = importlib.util.spec_from_file_location("migrate_auth_state", _MIG_PATH)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture(scope="module")
def mig():
    return _load()


def _tables(db: Path) -> set[str]:
    conn = sqlite3.connect(db)
    try:
        return {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    finally:
        conn.close()


def _cols(db: Path, table: str) -> set[str]:
    conn = sqlite3.connect(db)
    try:
        return {r[1] for r in conn.execute(f"PRAGMA table_info({table})")}
    finally:
        conn.close()


def test_create_schema_makes_all_canonical_tables(mig, tmp_path: Path) -> None:
    db = tmp_path / "auth_state.sqlite"
    mig.create_schema(db)
    assert _tables(db) >= {
        "revoked_jtis",
        "rate_limit_events",
        "otp_requests",
        "consent_ledger",
        "agent_runs",
        "webhooks",
        "webhook_nonces",
        "login_sessions",
        "audit_chain_head",
        "auth_sessions",
    }


def test_webhooks_canonical_columns_not_legacy(mig, tmp_path: Path) -> None:
    """DL-06: webhooks must use the §7.1 shape, not the stub's wrong columns."""
    db = tmp_path / "auth_state.sqlite"
    mig.create_schema(db)
    cols = _cols(db, "webhooks")
    assert {"secret_encrypted_aes_gcm_siv", "dek_id", "source", "name", "user_id", "key_version"} <= cols
    assert "secret_encrypted" not in cols  # legacy stub column gone


def test_webhook_nonces_uses_nonce_not_nonce_hash(mig, tmp_path: Path) -> None:
    """DL-06: column is `nonce`; `source_ip_hash` is nullable."""
    db = tmp_path / "auth_state.sqlite"
    mig.create_schema(db)
    cols = _cols(db, "webhook_nonces")
    assert "nonce" in cols and "nonce_hash" not in cols


def test_login_sessions_has_dek_salt(mig, tmp_path: Path) -> None:
    """DL-09: per-row dek_salt BLOB must be present (Identity N1/NC2)."""
    db = tmp_path / "auth_state.sqlite"
    mig.create_schema(db)
    assert {"dek_salt", "nonce", "encrypted_api_key", "encrypted_api_secret"} <= _cols(db, "login_sessions")


def test_agent_runs_status_check_enum(mig, tmp_path: Path) -> None:
    db = tmp_path / "auth_state.sqlite"
    mig.create_schema(db)
    conn = sqlite3.connect(db)
    try:
        conn.execute(
            "INSERT INTO agent_runs (run_id, agent_name, parent_jti, started_at, status) "
            "VALUES ('r1','a','j',1.0,'running')"
        )
        with pytest.raises(sqlite3.IntegrityError):
            conn.execute(
                "INSERT INTO agent_runs (run_id, agent_name, parent_jti, started_at, status) "
                "VALUES ('r2','a','j',1.0,'bogus')"
            )
    finally:
        conn.close()


def test_webhook_id_immutability_check(mig, tmp_path: Path) -> None:
    """Security H14: empty webhook_id rejected by CHECK."""
    db = tmp_path / "auth_state.sqlite"
    mig.create_schema(db)
    conn = sqlite3.connect(db)
    try:
        with pytest.raises(sqlite3.IntegrityError):
            conn.execute(
                "INSERT INTO webhooks (webhook_id, source, name, user_id, "
                "secret_encrypted_aes_gcm_siv, dek_id, key_version, created_at, last_rotated_at) "
                "VALUES ('', 's', 'n', 'u', X'00', 'd', 1, 1.0, 1.0)"
            )
    finally:
        conn.close()


def test_migrate_fresh_install_uses_the_actual_runtime_schema(mig, tmp_path: Path) -> None:
    """The CLI's fresh path must be consumable by the actual AuthState."""
    args = argparse.Namespace(master_password_fd=None, accept_unknown_tables=False, legacy_fernet_key_path=None)
    from flinttrade_core.auth_state import AuthState

    assert mig.migrate(tmp_path, args) == 0
    state = AuthState(tmp_path / "auth_state.sqlite")
    try:
        assert not state.is_jti_revoked("new-installation")
        state.revoke_jti("new-installation", 4102444800.0)
        assert state.is_jti_revoked("new-installation")
    finally:
        state.close()


def test_migrate_repeatedly_refuses_unowned_sqlite_without_overwrite(mig, tmp_path: Path) -> None:
    args = argparse.Namespace(master_password_fd=None, accept_unknown_tables=False, legacy_fernet_key_path=None)
    from flinttrade_core.legacy_sqlite_migration import MigrationRefused

    target = tmp_path / "auth_state.sqlite"
    mig.create_schema(target)
    original = target.read_bytes()
    for _ in range(2):
        with pytest.raises(MigrationRefused, match="unowned destination"):
            mig.migrate(tmp_path, args)
        assert target.read_bytes() == original
