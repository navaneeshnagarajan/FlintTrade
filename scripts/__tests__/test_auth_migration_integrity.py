"""Public auth migration, runtime cutover and real AGE custody; synthetic keys only."""
from __future__ import annotations

import base64
import importlib.util
import json
import os
import secrets
import sqlite3
import subprocess
import sys
from pathlib import Path

import duckdb
import pytest
from cryptography.fernet import Fernet

from flinttrade_core.auth_service import AuthService
from flinttrade_core.auth_state import AuthState
from flinttrade_core.legacy_sqlite_migration import MigrationRefused
from flinttrade_webhooks.webhook_keys import decrypt_webhook_secret
from flinttrade_webhooks.webhook_secret_store import WebhookSecretStore

pytestmark = pytest.mark.integration
ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "scripts/migrate-auth-state-duckdb-to-sqlite.py"


def load_migrator():
    spec = importlib.util.spec_from_file_location("migrate_auth_integrity", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def invoke(workspace: Path, password: str, *args: str, fault: str | None = None) -> subprocess.CompletedProcess[str]:
    read_fd, write_fd = os.pipe()
    try:
        os.write(write_fd, (password + "\n").encode())
        os.close(write_fd)
        write_fd = -1
        prefix = ([str(ROOT / "scripts/__tests__/auth_migration_fault_driver.py"), fault, str(SCRIPT), str(workspace)]
                  if fault else [str(SCRIPT), "--workspace", str(workspace)])
        env = {k: v for k, v in os.environ.items() if not k.startswith("PYTEST_XDIST_")}
        result = subprocess.run(
            [sys.executable, *prefix, "--master-password-fd", str(read_fd), *args],
            pass_fds=(read_fd,), capture_output=True, text=True, timeout=60, check=False, env=env,
        )
        disclosed = password in result.stdout + result.stderr
        assert not disclosed, "CLI disclosed a synthetic password"
        return result
    finally:
        os.close(read_fd)
        if write_fd >= 0:
            os.close(write_fd)


@pytest.mark.parametrize("competing", [False, True])
def test_existing_standalone_webhooks_are_preserved_or_ambiguity_refused(tmp_path: Path, competing: bool) -> None:
    password = secrets.token_urlsafe(24)
    standalone = tmp_path / "webhook_secrets.db"
    secret = secrets.token_urlsafe(24)
    store = WebhookSecretStore(standalone, password)
    store.store_secret("/standalone", "synthetic", "retained", secret)
    assert store.check_and_record_nonce("/standalone", "retained", 4102444800.0, now=4102444800.0) is None
    source, password, key, _ = auth_source(tmp_path, with_hooks=competing, password=password)
    before_source, before_store = source.read_bytes(), standalone.read_bytes()
    key_path = tmp_path / "synthetic-fernet-key"
    key_path.write_bytes(key)
    result = invoke(tmp_path, password, "--legacy-fernet-key-path", str(key_path))
    assert standalone.read_bytes() == before_store
    if competing:
        assert result.returncode == 2
        assert source.read_bytes() == before_source
        assert not (tmp_path / "auth_state.sqlite").exists()
    else:
        assert result.returncode == 0, result.stdout
        from flinttrade_core.auth_state_migration import select_webhook_store_path

        assert select_webhook_store_path(tmp_path) == standalone
        reopened = WebhookSecretStore(select_webhook_store_path(tmp_path), password)
        matches = reopened.get_secret("/standalone") == secret
        assert matches, "standalone secret mismatch"
        assert reopened.check_and_record_nonce("/standalone", "retained", 4102444800.0,
                                               now=4102444800.0) == "WEBHOOK_REPLAY_REJECTED"


def test_auth_cli_never_certifies_corrupt_or_unowned_destination(tmp_path: Path) -> None:
    target = tmp_path / "auth_state.sqlite"
    target.write_bytes(b"corrupt")
    original = target.read_bytes()
    result = invoke(tmp_path, secrets.token_urlsafe(24))
    assert result.returncode != 0
    assert target.read_bytes() == original


def test_actual_duckdb_auth_state_migrates_to_default_runtime(tmp_path: Path, monkeypatch) -> None:
    from pyrage import passphrase

    from flinttrade_core import auth_state

    source, password, _, _ = auth_source(tmp_path)
    original = source.read_bytes()
    result = invoke(tmp_path, password)
    assert result.returncode == 0, result.stdout
    assert not source.exists()
    archives = list(tmp_path.glob("archive/migrations/*/auth_state.duckdb.age"))
    assert len(archives) == 1
    assert archives[0].read_bytes() != original
    assert passphrase.decrypt(archives[0].read_bytes(), password) == original
    assert not list(tmp_path.glob(".migration-*"))
    assert "Traceback" not in result.stdout + result.stderr
    monkeypatch.setenv("FLINTTRADE_WORKSPACE_DIR", str(tmp_path))
    assert auth_state._default_db_path() == tmp_path / "auth_state.sqlite"
    reader = AuthState()
    try:
        assert reader.is_jti_revoked("synthetic-jti")
        assert reader.is_jti_revoked("expired-jti")
        assert reader.count_recent_otp_requests("synthetic@example.invalid", 60) == 2
        assert not reader.check_rate_limit("endpoint", "fixture-ip", 2, 60)
    finally:
        reader.close()


@pytest.mark.parametrize("raw", [False, True])
def test_transcode_uses_real_current_webhook_crypto_and_reader(raw: bool, tmp_path: Path) -> None:
    password, secret = secrets.token_urlsafe(24), secrets.token_urlsafe(32)
    key = Fernet.generate_key()
    target = tmp_path / "staged.sqlite"
    store = WebhookSecretStore(target, password)
    store.store_secret("/synthetic-hook", "synthetic", "fixture", secret)
    token = Fernet(key).encrypt(secret.encode())
    if raw:
        token = base64.urlsafe_b64decode(token)
    with sqlite3.connect(target) as db:
        db.execute("UPDATE webhooks SET secret_encrypted_aes_gcm_siv=?, key_version=7", (token,))
        before = db.execute("SELECT webhook_id,path,source,name,key_version,created_at,updated_at FROM webhooks").fetchall()
    module = load_migrator()
    assert module._transcode_webhook_secrets(target, key, password) == 1
    matches = WebhookSecretStore(target, password).get_secret("/synthetic-hook") == secret
    assert matches, "transcoded secret mismatch"
    with sqlite3.connect(target) as db:
        after = db.execute("SELECT webhook_id,path,source,name,key_version,created_at,updated_at FROM webhooks").fetchall()
        blob = db.execute("SELECT secret_encrypted_aes_gcm_siv FROM webhooks").fetchone()[0]
    assert before == after
    matches = decrypt_webhook_secret(blob, "synthetic-hook", store._master_dek, 7).decode() == secret
    assert matches, "version-bound plaintext mismatch"
    assert module._transcode_webhook_secrets(target, key, password) == 0


def test_transcode_is_atomic_on_invalid_ciphertext(tmp_path: Path) -> None:
    password, secret = secrets.token_urlsafe(24), secrets.token_urlsafe(32)
    key = Fernet.generate_key()
    target = tmp_path / "staged.sqlite"
    store = WebhookSecretStore(target, password)
    store.store_secret("/first", "synthetic", "first", secret)
    store.store_secret("/second", "synthetic", "second", secret)
    with sqlite3.connect(target) as db:
        db.execute("UPDATE webhooks SET secret_encrypted_aes_gcm_siv=? WHERE path='/first'",
                   (Fernet(key).encrypt(secret.encode()),))
        db.execute("UPDATE webhooks SET secret_encrypted_aes_gcm_siv=? WHERE path='/second'", (b"bad-ciphertext",))
        before = db.execute("SELECT * FROM webhooks ORDER BY webhook_id").fetchall()
    with pytest.raises(MigrationRefused):
        load_migrator()._transcode_webhook_secrets(target, key, password)
    with sqlite3.connect(target) as db:
        assert db.execute("SELECT * FROM webhooks ORDER BY webhook_id").fetchall() == before


def auth_source(workspace: Path, *, with_hooks: bool = False, password: str | None = None) -> tuple[Path, str, bytes, str]:
    password = password or secrets.token_urlsafe(24)
    secret, key = secrets.token_urlsafe(32), Fernet.generate_key()
    source = workspace / "auth_state.duckdb"
    with duckdb.connect(str(source), config={"threads": 1}) as db:
        db.execute("CREATE TABLE revoked_jtis (jti VARCHAR PRIMARY KEY,exp DOUBLE NOT NULL,revoked_at DOUBLE NOT NULL)")
        db.execute("CREATE TABLE rate_limit_events (endpoint VARCHAR NOT NULL,ip VARCHAR NOT NULL,ts DOUBLE NOT NULL)")
        db.execute("CREATE TABLE otp_requests (email VARCHAR NOT NULL,ts DOUBLE NOT NULL)")
        db.execute("INSERT INTO revoked_jtis VALUES ('synthetic-jti', 4102444800.123456, 1735000000.654321)")
        db.execute("INSERT INTO revoked_jtis VALUES ('expired-jti', 1.125, 0.654321)")
        db.execute("INSERT INTO rate_limit_events VALUES ('endpoint','fixture-ip',4102444800.123456)")
        db.execute("INSERT INTO rate_limit_events VALUES ('endpoint','fixture-ip',4102444800.123456)")
        db.execute("INSERT INTO otp_requests VALUES ('synthetic@example.invalid',4102444800.654321)")
        db.execute("INSERT INTO otp_requests VALUES ('synthetic@example.invalid',4102444800.654321)")
    if with_hooks:
        fixture = workspace / "fixture-webhooks.sqlite"
        store = WebhookSecretStore(fixture, password)
        store.store_secret("/synthetic-hook", "synthetic", "fixture", secret)
        with sqlite3.connect(fixture) as db, duckdb.connect(str(source), config={"threads": 1}) as duck:
            db.execute("UPDATE webhooks SET secret_encrypted_aes_gcm_siv=?,key_version=3", (Fernet(key).encrypt(secret.encode()),))
            db.execute("INSERT INTO webhook_nonces VALUES ('synthetic-hook','fixture-nonce',4102444800.123456,NULL)")
            for table in ("webhooks", "webhook_nonces"):
                info = db.execute(f"PRAGMA table_info({table})").fetchall()
                columns = ",".join(row[1] + " " + row[2] for row in info)
                duck.execute(f"CREATE TABLE {table} ({columns})")
                duck.executemany(f"INSERT INTO {table} VALUES ({','.join('?' for _ in info)})",
                                 db.execute(f"SELECT * FROM {table}").fetchall())
    return source, password, key, secret


def test_auth_cli_preserves_every_typed_row_and_selects_real_webhook_reader(tmp_path: Path) -> None:
    source, password, key, secret = auth_source(tmp_path, with_hooks=True)
    key_path = tmp_path / "synthetic-fernet-key"
    key_path.write_bytes(key)
    # The current store intentionally retains replay evidence after deleting a
    # webhook: its nonce schema has no FK. Preserve that history, not invented links.
    with duckdb.connect(str(source), config={"threads": 1}) as db:
        db.execute("INSERT INTO webhook_nonces VALUES ('retired-hook','retained-nonce',4102444800.5,NULL)")
    with duckdb.connect(str(source), read_only=True, config={"threads": 1}) as duck:
        expected = {table: duck.execute(f"SELECT * FROM {table}").fetchall()
                    for table in ("revoked_jtis", "rate_limit_events", "otp_requests", "webhook_nonces")}
    result = invoke(tmp_path, password, "--legacy-fernet-key-path", str(key_path))
    assert result.returncode == 0, result.stdout
    from flinttrade_core.auth_state_migration import select_webhook_store_path

    target = tmp_path / "auth_state.sqlite"
    with sqlite3.connect(target) as db:
        for table, values in expected.items():
            actual = db.execute(f"SELECT * FROM {table}").fetchall()
            assert sorted(actual) == sorted(values)
            assert [[type(v) for v in row] for row in actual] == [[type(v) for v in row] for row in values]
    assert select_webhook_store_path(tmp_path) == target
    store = WebhookSecretStore(select_webhook_store_path(tmp_path), password)
    matches = store.get_secret("/synthetic-hook") == secret
    assert matches, "migrated consumer secret mismatch"
    assert store.check_and_record_nonce("/synthetic-hook", "fixture-nonce", 4102444800.123456,
                                        now=4102444800.123456) == "WEBHOOK_REPLAY_REJECTED"
    output = result.stdout + result.stderr
    disclosed = secret in output or key.decode() in output
    assert not disclosed, "synthetic credential was disclosed"
    result = invoke(tmp_path, password, "--legacy-fernet-key-path", str(key_path))
    assert result.returncode == 0
    assert not source.exists()
    assert json.loads((tmp_path / ".auth_state.sqlite.migration.json").read_text())["phase"] == "complete"


@pytest.mark.parametrize("fault", ["unknown_table", "missing_exp", "unknown_column", "null_jti",
                                    "wrong_path", "wrong_version", "corrupt_blob", "wrong_key", "ignore_unknown"])
def test_auth_invalid_schema_or_crypto_never_discards_data(fault: str, tmp_path: Path) -> None:
    source, password, key, secret = auth_source(tmp_path, with_hooks=True)
    key_path = tmp_path / "synthetic-fernet-key"
    key_path.write_bytes(Fernet.generate_key() if fault == "wrong_key" else key)
    with duckdb.connect(str(source), config={"threads": 1}) as db:
        if fault == "unknown_table":
            db.execute("CREATE TABLE retained_ciphertext (secret BLOB)")
            db.execute("INSERT INTO retained_ciphertext VALUES (?)", [secrets.token_bytes(32)])
        elif fault == "missing_exp":
            db.execute("ALTER TABLE revoked_jtis DROP COLUMN exp")
        elif fault == "unknown_column":
            db.execute("ALTER TABLE otp_requests ADD COLUMN retained_secret BLOB")
        elif fault == "null_jti":
            db.execute("CREATE TABLE copy AS SELECT * FROM revoked_jtis")
            db.execute("DROP TABLE revoked_jtis")
            db.execute("ALTER TABLE copy RENAME TO revoked_jtis")
            db.execute("UPDATE revoked_jtis SET jti=NULL")
        elif fault == "wrong_path":
            db.execute("UPDATE webhooks SET path='/different-identity'")
        elif fault == "wrong_version":
            db.execute("UPDATE webhooks SET key_version=0")
        elif fault == "corrupt_blob":
            db.execute("UPDATE webhooks SET secret_encrypted_aes_gcm_siv=?", [b"bad-ciphertext"])
    original = source.read_bytes()
    args = ["--legacy-fernet-key-path", str(key_path)]
    if fault == "ignore_unknown":
        args.append("--accept-unknown-tables")
    result = invoke(tmp_path, password, *args)
    assert result.returncode == 2
    assert "auth_state_reader_cutover_required" not in result.stdout, "invalid source reached reader gate"
    assert source.read_bytes() == original
    assert not (tmp_path / "auth_state.sqlite").exists()
    disclosed = secret in result.stdout + result.stderr
    assert not disclosed, "synthetic credential was disclosed"


@pytest.mark.parametrize("fault", ["copy", "write", "validation", "fsync_stage", "rename_receipt", "publish_before", "missing_age"])
def test_auth_prepublication_failure_preserves_and_resumes(fault: str, tmp_path: Path) -> None:
    source, password, _, _ = auth_source(tmp_path)
    original = source.read_bytes()
    result = invoke(tmp_path, password, fault=fault)
    assert result.returncode == 2, result.stdout
    assert source.read_bytes() == original
    assert not (tmp_path / "auth_state.sqlite").exists()
    retry = invoke(tmp_path, password)
    assert retry.returncode == 0, retry.stdout
    _assert_encrypted_custody(tmp_path, original, password)


@pytest.mark.parametrize("fault", ["publish_after", "archive_before", "archive_after", "archive_encrypt",
                                   "archive_decrypt", "fsync_archive", "unlink_source", "fsync_unlink", "cleanup_snapshot"])
def test_auth_published_archive_pending_resumes_real_age(fault: str, tmp_path: Path) -> None:
    source, password, _, _ = auth_source(tmp_path)
    original = source.read_bytes()
    result = invoke(tmp_path, password, fault=fault)
    assert result.returncode == 3, result.stdout
    assert "published/archive-pending" in result.stdout
    receipt = json.loads((tmp_path / ".auth_state.sqlite.migration.json").read_text())
    assert receipt["phase"] != "complete"
    with pytest.raises((RuntimeError, OSError, sqlite3.DatabaseError)):
        AuthState(tmp_path / "auth_state.sqlite")
    if source.exists():
        assert source.read_bytes() == original
    else:
        _assert_encrypted_custody(tmp_path, original, password, complete=False)
    retry = invoke(tmp_path, password)
    assert retry.returncode == 0, retry.stdout
    _assert_encrypted_custody(tmp_path, original, password)
    again = invoke(tmp_path, password)
    assert again.returncode == 0, again.stdout


def _assert_encrypted_custody(workspace: Path, original: bytes, password: str, *, complete: bool = True) -> None:
    from pyrage import passphrase

    archives = list(workspace.glob("archive/migrations/*/auth_state.duckdb.age"))
    assert len(archives) == 1
    encrypted = archives[0].read_bytes()
    assert encrypted != original and encrypted.startswith(b"age-encryption.org/v1\n")
    matches = passphrase.decrypt(encrypted, password) == original
    assert matches, "encrypted custody failed exact source-byte verification"
    if complete:
        assert not (workspace / "auth_state.duckdb").exists()
        assert not list(workspace.glob(".migration-*")), "plaintext staging retained after completion"
        assert json.loads((workspace / ".auth_state.sqlite.migration.json").read_text())["phase"] == "complete"


@pytest.mark.parametrize("fault", ["wrong_password", "corrupt_archive", "unrelated_archive", "divergent_destination", "publication_collision"])
def test_auth_conflicts_never_clobber_source_or_archive(fault: str, tmp_path: Path) -> None:
    source, password, _, _ = auth_source(tmp_path)
    original = source.read_bytes()
    initial = invoke(tmp_path, password, fault="publication_collision" if fault == "publication_collision" else "unlink_source")
    assert initial.returncode == (2 if fault == "publication_collision" else 3)
    target = tmp_path / "auth_state.sqlite"
    archives = list(tmp_path.glob("archive/migrations/*/auth_state.duckdb.age"))
    if fault == "corrupt_archive":
        encrypted = archives[0].read_bytes()
        archives[0].write_bytes(encrypted[:-16] + b"corrupted-footer")
    elif fault == "unrelated_archive":
        from pyrage import passphrase

        archives[0].write_bytes(passphrase.encrypt(secrets.token_bytes(64), password))
    elif fault == "divergent_destination":
        with sqlite3.connect(target) as db:
            db.execute("DELETE FROM revoked_jtis")
    before_archive = [p.read_bytes() for p in archives]
    before_target = target.read_bytes()
    retry = invoke(tmp_path, secrets.token_urlsafe(24) if fault == "wrong_password" else password)
    assert retry.returncode != 0
    assert source.read_bytes() == original
    assert [p.read_bytes() for p in archives] == before_archive
    assert target.read_bytes() == before_target
    assert json.loads((tmp_path / ".auth_state.sqlite.migration.json").read_text())["phase"] != "complete"


@pytest.mark.parametrize("lost", ["target", "receipt", "both", "metadata"])
def test_lost_migrated_authority_never_initialises_empty_state(lost: str, tmp_path: Path) -> None:
    _, password, _, _ = auth_source(tmp_path)
    result = invoke(tmp_path, password)
    assert result.returncode == 0
    target = tmp_path / "auth_state.sqlite"
    if lost in {"target", "both"}:
        target.unlink()
    if lost in {"receipt", "both"}:
        (tmp_path / ".auth_state.sqlite.migration.json").unlink()
    if lost == "metadata":
        with sqlite3.connect(target) as db:
            db.execute("DROP TABLE _auth_state_migration")
    from flinttrade_core.auth_state_migration import select_webhook_store_path

    for operation in (lambda: AuthState(target), lambda: select_webhook_store_path(tmp_path)):
        with pytest.raises((RuntimeError, OSError, sqlite3.DatabaseError)):
            operation()
    assert not (tmp_path / "webhook_secrets.db").exists()
    if lost in {"target", "both"}:
        assert not target.exists()


def test_real_maintenance_and_legacy_writer_exclude_auth_migration(tmp_path: Path, monkeypatch) -> None:
    from flinttrade_core.backend_instance import acquire_backend_instance_lease

    source, password, _, _ = auth_source(tmp_path)
    original = source.read_bytes()
    monkeypatch.setenv("FLINTTRADE_WORKSPACE_DIR", str(tmp_path))
    lease = acquire_backend_instance_lease()
    try:
        result = invoke(tmp_path, password)
        assert result.returncode == 2
    finally:
        lease.release()
    with duckdb.connect(str(source), config={"threads": 1}):
        result = invoke(tmp_path, password)
        assert result.returncode == 2
    assert source.read_bytes() == original
    assert not (tmp_path / "auth_state.sqlite").exists()
    result = invoke(tmp_path, password, fault="assert_lease")
    assert result.returncode == 0, result.stdout
    assert result.stdout.count("REAL_BACKEND_EXCLUDED") == 2


def test_age_temporary_archive_collision_is_never_clobbered(tmp_path: Path) -> None:
    source, password, _, _ = auth_source(tmp_path)
    original = source.read_bytes()
    result = invoke(tmp_path, password, fault="archive_before")
    assert result.returncode == 3
    temporary = next(tmp_path.glob("archive/migrations/*/auth_state.duckdb.age.tmp"))
    temporary.write_bytes(b"unrelated retained archive evidence")
    result = invoke(tmp_path, password)
    assert result.returncode == 3
    assert temporary.read_bytes() == b"unrelated retained archive evidence"
    assert source.read_bytes() == original


def test_age_temporary_cleanup_retry_retires_verified_copy(tmp_path: Path) -> None:
    source, password, _, _ = auth_source(tmp_path)
    original = source.read_bytes()
    result = invoke(tmp_path, password, fault="archive_temp_cleanup")
    assert result.returncode == 3
    assert source.read_bytes() == original
    assert list(tmp_path.glob("archive/migrations/*/*.age.tmp"))
    result = invoke(tmp_path, password)
    assert result.returncode == 0
    assert not list(tmp_path.glob("archive/migrations/*/*.age.tmp"))
    assert not list(tmp_path.glob(".migration-*"))


def test_missing_age_dependency_is_not_archive_success(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setitem(sys.modules, "pyrage", None)
    source = tmp_path / "source"
    source.write_bytes(secrets.token_bytes(64))
    original = source.read_bytes()
    archive = tmp_path / "source.age"
    with pytest.raises(ModuleNotFoundError, match="pyrage"):
        load_migrator()._archive_legacy(source, archive, None, secrets.token_urlsafe(24))
    assert source.read_bytes() == original
    assert not archive.exists()


def test_successful_cli_preserves_password_mfa_and_public_revocation(tmp_path: Path, monkeypatch) -> None:
    import jwt
    import pyotp
    from flask import Flask

    from flinttrade_core.auth_routes import _create_token, _get_jwt_secret

    monkeypatch.setenv("FLINTTRADE_WORKSPACE_DIR", str(tmp_path))
    source, password, _, _ = auth_source(tmp_path)
    account = tmp_path / "auth.db"
    auth = AuthService(account)
    app = Flask(__name__)
    app.config["AUTH_SERVICE"] = auth
    try:
        pin = "".join(secrets.choice("0123456789") for _ in range(6))
        auth.setup_account("synthetic", "synthetic@example.invalid", password, pin)
        seed = auth.get_totp_secret()
        assert seed is not None
        enabled = auth.enable_totp(pyotp.TOTP(seed).now())
        assert enabled
        with app.app_context():
            token = _create_token("synthetic")
            payload = jwt.decode(token, _get_jwt_secret(), algorithms=["HS256"])
        with duckdb.connect(str(source), config={"threads": 1}) as db:
            db.execute("UPDATE revoked_jtis SET jti=?,exp=? WHERE jti='synthetic-jti'",
                       (payload["jti"], payload["exp"]))
    finally:
        auth.close()
    original_account, original_source = account.read_bytes(), source.read_bytes()
    result = invoke(tmp_path, password)
    assert result.returncode == 0, result.stdout
    assert account.read_bytes() == original_account
    _assert_encrypted_custody(tmp_path, original_source, password)
    program = """import json,os,sys
from pathlib import Path
os.environ['FLINTTRADE_WORKSPACE_DIR']=sys.argv[1]
import pyotp
from flask import Flask
from flinttrade_core.auth_service import AuthService
from flinttrade_core.auth_state import get_auth_state
from flinttrade_core.auth_routes import auth_bp
values=json.load(sys.stdin)
auth=AuthService(Path(sys.argv[1])/'auth.db')
try:
 assert auth.verify_password(values['password'])
 assert auth.is_totp_enabled()
 assert auth.get_totp_secret()==values['seed']
 assert auth.verify_totp(pyotp.TOTP(values['seed']).now())
 app=Flask(__name__); app.config['AUTH_SERVICE']=auth; app.register_blueprint(auth_bp)
 response=app.test_client().post('/v1/auth/mode',json={'mode':'practice'},
                               headers={'Authorization':'Bearer '+values['token']})
 assert response.status_code==401, response.status_code
 state=get_auth_state(); assert state._db_path==Path(sys.argv[1])/'auth_state.sqlite'
 assert state.is_jti_revoked(values['jti'])
 print('ORIGINAL_PASSWORD_MFA_AND_REVOKED_API_VERIFIED')
finally:
 auth.close()
"""
    env = {k: v for k, v in os.environ.items() if not k.startswith("PYTEST_XDIST_")}
    consumer = subprocess.run([sys.executable, "-c", program, str(tmp_path)],
                              input=json.dumps({"password": password, "seed": seed, "token": token, "jti": payload["jti"]}),
                              capture_output=True, text=True, timeout=45, check=False, env=env)
    assert consumer.returncode == 0, "fresh password/MFA/API consumer failed"
    assert "ORIGINAL_PASSWORD_MFA_AND_REVOKED_API_VERIFIED" in consumer.stdout
    disclosed = any(value in consumer.stdout + consumer.stderr for value in (password, seed, token))
    assert not disclosed, "consumer disclosed generated credentials"


def test_migration_failure_does_not_touch_enrolled_authenticator(tmp_path: Path) -> None:
    import pyotp

    password = secrets.token_urlsafe(24)
    account = tmp_path / "auth.db"
    auth = AuthService(account)
    try:
        pin = "".join(secrets.choice("0123456789") for _ in range(6))
        auth.setup_account("synthetic", "synthetic@example.invalid", password, pin)
        seed = auth.get_totp_secret()
        assert seed is not None
        enabled = auth.enable_totp(pyotp.TOTP(seed).now())
        assert enabled
    finally:
        auth.close()
    before = account.read_bytes()
    (tmp_path / "auth_state.duckdb").write_bytes(b"broken source")
    result = invoke(tmp_path, password)
    assert result.returncode != 0
    assert account.read_bytes() == before
    fresh = AuthService(account)
    try:
        verified = fresh.verify_password(password)
        assert verified
        assert fresh.is_totp_enabled()
        matches = fresh.get_totp_secret() == seed
        assert matches, "original authenticator changed"
        verified = fresh.verify_totp(pyotp.TOTP(seed).now())
        assert verified
    finally:
        fresh.close()
