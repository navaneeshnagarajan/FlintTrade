"""Actual auth authority persistence; every database is disposable."""
from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from flinttrade_core.auth_state import AuthState, _default_db_path


@pytest.mark.integration
def test_sqlite_default_and_restart_preserve_auth_authority(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("FLINTTRADE_WORKSPACE_DIR", str(tmp_path))
    assert _default_db_path() == tmp_path / "auth_state.sqlite"
    monkeypatch.setattr("flinttrade_core.auth_state.time.time", lambda: 1735000000.125)
    state = AuthState()
    try:
        state.revoke_jti("revoked", 4102444800.25)
        state.record_otp_request("synthetic@example.invalid")
        state.record_otp_request("synthetic@example.invalid")
        assert state.check_rate_limit("endpoint", "fixture-ip", 2, 60)
        assert state.check_rate_limit("endpoint", "fixture-ip", 2, 60)
        assert not state.check_rate_limit("endpoint", "fixture-ip", 2, 60)
    finally:
        state.close()
    with sqlite3.connect(_default_db_path()) as db:
        assert db.execute("SELECT * FROM revoked_jtis").fetchall() == [("revoked", 4102444800.25, 1735000000.125)]
        assert db.execute("SELECT count(*) FROM rate_limit_events").fetchone() == (2,)
    reopened = AuthState()
    try:
        assert reopened.is_jti_revoked("revoked")
        assert reopened.count_recent_otp_requests("synthetic@example.invalid", 60) == 2
        assert not reopened.check_rate_limit("endpoint", "fixture-ip", 2, 60)
    finally:
        reopened.close()


@pytest.mark.integration
@pytest.mark.parametrize("damage", ["missing", "empty", "missing_table", "corrupt", "wrong_columns", "wrong_value"])
def test_established_auth_authority_is_never_reinitialised(damage: str, tmp_path: Path) -> None:
    path = tmp_path / "auth_state.sqlite"
    state = AuthState(path)
    state.revoke_jti("revoked", 4102444800.0)
    state.close()
    if damage == "missing":
        path.unlink()
    elif damage == "empty":
        path.write_bytes(b"")
    elif damage == "corrupt":
        path.write_bytes(b"broken authority")
    elif damage == "wrong_value":
        with sqlite3.connect(path) as db:
            db.execute("UPDATE revoked_jtis SET exp='broken-expiry'")
    else:
        with sqlite3.connect(path) as db:
            db.execute("DROP TABLE otp_requests")
            if damage == "wrong_columns":
                db.execute("CREATE TABLE otp_requests (email TEXT, changed REAL)")
    before = path.read_bytes() if path.exists() else None
    with pytest.raises((RuntimeError, sqlite3.DatabaseError)):
        AuthState(path)
    assert (path.read_bytes() if path.exists() else None) == before


@pytest.mark.integration
@pytest.mark.parametrize("damage", ["missing", "missing_table"])
def test_factory_selector_refuses_lost_or_incomplete_auth_authority(damage: str, tmp_path: Path) -> None:
    from flinttrade_core.auth_state_migration import select_webhook_store_path

    path = tmp_path / "auth_state.sqlite"
    state = AuthState(path)
    state.close()
    if damage == "missing":
        path.unlink()
    else:
        with sqlite3.connect(path) as db:
            db.execute("DROP TABLE revoked_jtis")
    with pytest.raises((RuntimeError, OSError, sqlite3.DatabaseError)):
        select_webhook_store_path(tmp_path)
    assert not (tmp_path / "webhook_secrets.db").exists()


@pytest.mark.integration
@pytest.mark.parametrize("evidence", ["legacy", "archive", "receipt", "pending", "orphan_stage", "legacy_custom"])
def test_unmigrated_evidence_refuses_empty_auth_state(evidence: str, tmp_path: Path) -> None:
    import duckdb

    path = tmp_path / "auth_state.sqlite"
    if evidence == "legacy":
        (tmp_path / "auth_state.duckdb").write_bytes(b"retained legacy authority")
    elif evidence == "archive":
        archive = tmp_path / "archive/migrations/fixture/auth_state.duckdb.age"
        archive.parent.mkdir(parents=True)
        archive.write_bytes(b"retained encrypted evidence")
    elif evidence == "receipt":
        (tmp_path / ".auth_state.sqlite.migration.json").write_text("{}")
    elif evidence == "pending":
        (tmp_path / "auth_state.sqlite.new").write_bytes(b"retained staging")
    elif evidence == "orphan_stage":
        stage = tmp_path / (".migration-" + "a" * 32)
        stage.mkdir()
        (stage / "source.duckdb").write_bytes(b"retained source snapshot without its receipt")
    else:
        path = tmp_path / "custom.sqlite"
        with duckdb.connect(str(path), config={"threads": 1}) as db:
            db.execute("CREATE TABLE retained (value VARCHAR)")
    original = {p: p.read_bytes() for p in tmp_path.rglob("*") if p.is_file()}
    with pytest.raises((RuntimeError, sqlite3.DatabaseError)):
        AuthState(path)
    assert {p: p.read_bytes() for p in original} == original
    if evidence != "legacy_custom":
        assert not path.exists()


@pytest.mark.integration
@pytest.mark.parametrize("kind", ["rate", "otp"])
def test_route_admission_refuses_unavailable_persistent_authority(kind: str) -> None:
    from flask import Flask

    from flinttrade_core import auth_routes
    from flinttrade_core.auth_state import get_auth_state

    state = get_auth_state()
    with sqlite3.connect(state._db_path) as db:
        db.execute("DROP TABLE otp_requests")
    app = Flask(__name__)
    with app.test_request_context("/", environ_base={"REMOTE_ADDR": "fixture-ip"}):
        admitted = (auth_routes._check_in_memory_rate_limit("migration-refusal", 1, 600) if kind == "rate"
                    else auth_routes._otp_rate_ok("synthetic-unavailable@example.invalid"))
    assert admitted is False, "lost authority must not create a fresh process-local allowance"


@pytest.mark.integration
def test_real_otp_route_admission_uses_one_atomic_transaction(monkeypatch: pytest.MonkeyPatch) -> None:
    import threading
    from concurrent.futures import ThreadPoolExecutor

    from flinttrade_core.auth_routes import _OTP_MAX_REQUESTS_PER_HOUR, _otp_rate_ok

    # If the old split count/record path is used, every caller observes the
    # same count before any insert. The atomic API never crosses this seam.
    workers = _OTP_MAX_REQUESTS_PER_HOUR + 1
    barrier = threading.Barrier(workers, timeout=5)
    original_count = AuthState.count_recent_otp_requests

    def synchronised_count(self, email, window_seconds):
        count = original_count(self, email, window_seconds)
        barrier.wait()
        return count

    monkeypatch.setattr(AuthState, "count_recent_otp_requests", synchronised_count)
    with ThreadPoolExecutor(max_workers=workers) as pool:
        results = list(pool.map(_otp_rate_ok, ["synthetic-race@example.invalid"] * workers))
    assert sum(results) == _OTP_MAX_REQUESTS_PER_HOUR


@pytest.mark.unit
def test_default_path_selection_is_pure(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("FLINTTRADE_WORKSPACE_DIR", str(tmp_path))
    assert _default_db_path().name == "auth_state.sqlite"
    assert not _default_db_path().exists()


@pytest.mark.integration
def test_live_owner_refuses_removed_file_or_table(tmp_path: Path) -> None:
    path = tmp_path / "auth_state.sqlite"
    state = AuthState(path)
    try:
        with sqlite3.connect(path) as db:
            db.execute("DROP TABLE otp_requests")
        with pytest.raises(RuntimeError):
            state.is_jti_revoked("previously-revoked")
        path.unlink()
        with pytest.raises(RuntimeError):
            state.is_jti_revoked("previously-revoked")
    finally:
        state.close()


@pytest.mark.integration
def test_singleton_rejects_path_rebinding_and_reopens_closed_authority(tmp_path: Path) -> None:
    from flinttrade_core.auth_state import get_auth_state, reset_singleton_for_tests

    reset_singleton_for_tests()
    path = tmp_path / "auth_state.sqlite"
    try:
        state = get_auth_state(path)
        state.revoke_jti("revoked", 4102444800.0)
        with pytest.raises(RuntimeError):
            get_auth_state(tmp_path / "parallel.sqlite")
        state.close()
        reopened = get_auth_state()
        assert reopened.is_jti_revoked("revoked")
        assert reopened is not state
    finally:
        reset_singleton_for_tests()


@pytest.mark.integration
def test_default_singleton_cannot_leak_across_workspace_change(tmp_path: Path, monkeypatch) -> None:
    from flinttrade_core.auth_state import get_auth_state, reset_singleton_for_tests

    reset_singleton_for_tests()
    monkeypatch.setenv("FLINTTRADE_WORKSPACE_DIR", str(tmp_path / "first"))
    try:
        get_auth_state()
        monkeypatch.setenv("FLINTTRADE_WORKSPACE_DIR", str(tmp_path / "second"))
        with pytest.raises(RuntimeError):
            get_auth_state()
    finally:
        reset_singleton_for_tests()


@pytest.mark.integration
@pytest.mark.parametrize("kind", ["rate", "otp"])
def test_two_processes_cannot_admit_the_same_final_slot(tmp_path: Path, kind: str) -> None:
    import os
    import subprocess
    import sys

    path = tmp_path / "auth_state.sqlite"
    state = AuthState(path)
    state.close()
    program = """import sys
from flinttrade_core.auth_state import AuthState
s=AuthState(sys.argv[1]); print('READY',flush=True); sys.stdin.readline()
allowed = (s.check_rate_limit('shared','fixture-ip',1,600) if sys.argv[2]=='rate'
           else s.check_otp_request_limit('synthetic@example.invalid',1,600))
print(int(allowed),flush=True); s.close()
"""
    env = {k: v for k, v in os.environ.items() if not k.startswith("PYTEST_XDIST_")}
    children = [subprocess.Popen([sys.executable, "-c", program, str(path), kind], stdin=subprocess.PIPE,
                                stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, env=env) for _ in range(4)]
    try:
        for child in children:
            assert child.stdout.readline().strip() == "READY"
        for child in children:
            child.stdin.write("go\n")
            child.stdin.flush()
        results = [child.communicate(timeout=20) for child in children]
        assert all(child.returncode == 0 for child in children), results
        assert sorted(out.strip() for out, _ in results) == ["0", "0", "0", "1"]
    finally:
        for child in children:
            if child.poll() is None:
                child.kill()
            child.wait(timeout=10)


@pytest.mark.integration
def test_invalid_expiry_rolls_back_without_corrupting_authority(tmp_path: Path) -> None:
    state = AuthState(tmp_path / "auth_state.sqlite")
    try:
        with pytest.raises((RuntimeError, sqlite3.DatabaseError)):
            state.revoke_jti("invalid", "not-an-expiry")
        assert not state.is_jti_revoked("invalid")
        state.revoke_jti("valid", 4102444800.0)
        assert state.is_jti_revoked("valid")
    finally:
        state.close()


@pytest.mark.integration
def test_locked_writer_refuses_without_losing_events(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("flinttrade_core.auth_state_runtime.BUSY_TIMEOUT_SECONDS", 0.05)
    path = tmp_path / "auth_state.sqlite"
    state = AuthState(path)
    with sqlite3.connect(path) as blocker:
        blocker.execute("BEGIN IMMEDIATE")
        try:
            with pytest.raises(sqlite3.OperationalError, match="locked"):
                state.check_rate_limit("endpoint", "fixture-ip", 1, 60)
        finally:
            blocker.rollback()
    try:
        assert state.check_rate_limit("endpoint", "fixture-ip", 1, 60)
        assert not state.check_rate_limit("endpoint", "fixture-ip", 1, 60)
    finally:
        state.close()
