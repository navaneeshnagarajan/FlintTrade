"""Ditto's legacy journal must run before startup opens its target vault."""

from __future__ import annotations

import json
import os
import sqlite3
import subprocess
import sys
import time
from contextlib import contextmanager
from pathlib import Path


def _wait_for_path(path: Path, *, timeout: float = 10.0) -> bool:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if path.exists():
            return True
        time.sleep(0.01)
    return path.exists()


def _database(path: Path, value: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(path) as connection:
        connection.execute("CREATE TABLE state (value TEXT)")
        connection.execute("INSERT INTO state VALUES (?)", (value,))


def test_ditto_store_open_runs_migration_first(tmp_path, monkeypatch):
    from flinttrade_core import app, installation_state, workspace

    events: list[str] = []
    state_root = tmp_path / "installation"

    class FakeState:
        root = state_root

        @contextmanager
        def ditto_fence(self):  # type: ignore[no-untyped-def]
            events.append("fence-enter")
            yield
            events.append("fence-exit")

    class FakeStore:
        def __init__(self, path, password):  # type: ignore[no-untyped-def]
            assert events == ["fence-enter", "migration"]
            events.append("store")

    def migrate(*, installation_state_root):  # type: ignore[no-untyped-def]
        assert installation_state_root == state_root
        events.append("migration")

    monkeypatch.setattr(installation_state, "InstallationState", lambda: FakeState())
    monkeypatch.setattr(workspace, "ditto_accounts_path", migrate)
    monkeypatch.setattr(app, "CredentialStore", FakeStore)
    monkeypatch.setattr(app, "_workspace_dir", lambda: tmp_path)
    monkeypatch.setattr(app, "_get_master_password", lambda: "not-a-real-secret")

    app._open_ditto_credential_store()
    assert events == ["fence-enter", "migration", "store", "fence-exit"]


def test_app_vault_open_cannot_interleave_with_consumed_migration(tmp_path):
    """A real app process must not expose the vault while migration owns the fence."""
    workspace = tmp_path / "workspace"
    legacy = tmp_path / "legacy"
    installation = tmp_path / "installation"
    fake_home = tmp_path / "must-not-be-created-home"
    consumed = tmp_path / "migration-consumed"
    release = tmp_path / "release-migration"
    migration_done = tmp_path / "migration-done"
    opener_ready = tmp_path / "opener-ready"
    opener_done = tmp_path / "opener-done"
    target_vault = workspace / "ditto_credentials.db"
    _database(legacy / "ditto_accounts.sqlite", "accounts")
    _database(legacy / "ditto_credentials.db", "vault")
    workspace.mkdir()
    master_password = workspace / "master_password"
    master_password.write_text("test-master-password\n")
    master_password.chmod(0o600)

    migration_code = "\n".join(
        (
            "import pathlib, sys, time",
            "from flinttrade_core.workspace import _migrate_legacy_ditto_state",
            "legacy, target, installation, consumed, release, done = map(pathlib.Path, sys.argv[1:])",
            "def hook(phase):",
            "    if phase == 'consumed':",
            "        consumed.write_text('consumed')",
            "        while not release.exists():",
            "            time.sleep(0.01)",
            "_migrate_legacy_ditto_state(legacy, target / 'data', installation_state_root=installation, "
            "target_vault_path=target / 'ditto_credentials.db', phase_hook=hook)",
            "done.write_text('done')",
        )
    )
    opener_code = "\n".join(
        (
            "import pathlib, sys",
            "from flinttrade_core.app import _open_ditto_credential_store",
            "pathlib.Path(sys.argv[1]).write_text('ready')",
            "_open_ditto_credential_store()",
            "pathlib.Path(sys.argv[2]).write_text('done')",
        )
    )
    env = {
        **os.environ,
        "FLINTTRADE_WORKSPACE_DIR": str(workspace),
        "FLINTTRADE_INSTALLATION_STATE_DIR": str(installation),
        "HOME": str(fake_home),
    }
    migration = subprocess.Popen(  # noqa: S603
        [
            sys.executable,
            "-c",
            migration_code,
            str(legacy),
            str(workspace),
            str(installation),
            str(consumed),
            str(release),
            str(migration_done),
        ],
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    opener: subprocess.Popen[str] | None = None
    opened_while_consumed = False
    try:
        assert _wait_for_path(consumed), migration.communicate(timeout=1)
        receipt = json.loads((installation / "ditto-legacy-migration.json").read_text())
        assert receipt["phase"] == "consumed"
        opener = subprocess.Popen(  # noqa: S603
            [sys.executable, "-c", opener_code, str(opener_ready), str(opener_done)],
            env=env,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
        assert _wait_for_path(opener_ready)
        deadline = time.monotonic() + 1.0
        while time.monotonic() < deadline and not target_vault.exists():
            time.sleep(0.01)
        opened_while_consumed = target_vault.exists()
    finally:
        release.write_text("release")
        migration_stdout, migration_stderr = migration.communicate(timeout=10)
        if opener is not None:
            opener_stdout, opener_stderr = opener.communicate(timeout=10)
        else:
            opener_stdout, opener_stderr = "", "opener was not started"

    assert not opened_while_consumed, "the app exposed the Ditto vault while migration held the fence"
    assert migration.returncode == 0, (migration_stdout, migration_stderr)
    assert opener is not None and opener.returncode == 0, (opener_stdout, opener_stderr)
    assert migration_done.exists()
    assert opener_done.exists()
    assert not fake_home.exists()
    with sqlite3.connect(target_vault) as connection:
        assert connection.execute("SELECT value FROM state").fetchone()[0] == "vault"
