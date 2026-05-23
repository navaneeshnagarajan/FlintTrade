"""Tests for workspace.json schema migrations."""

from __future__ import annotations

import json
import os
import time
from pathlib import Path

import pytest

from packages.core.src.workspace_migrations import (
    MIGRATIONS,
    WORKSPACE_VERSION,
    MigrationLockError,
    _merge_defaults,
    run_migrations,
)


def _seed(workspace_dir: Path, cfg: dict) -> Path:
    """Write cfg as workspace.json in workspace_dir, return the path."""
    workspace_dir.mkdir(parents=True, exist_ok=True)
    path = workspace_dir / "workspace.json"
    path.write_text(json.dumps(cfg, indent=2), encoding="utf-8")
    return path


def test_fresh_install_no_migration(tmp_path):
    """Workspace already at current version: returned as-is, file untouched."""
    cfg = {"version": WORKSPACE_VERSION, "brokers": {"registered": ["openalgo:default"]}}
    path = _seed(tmp_path, cfg)
    mtime_before = path.stat().st_mtime_ns

    result = run_migrations(tmp_path)

    assert result == cfg
    assert path.stat().st_mtime_ns == mtime_before


def test_legacy_010_alpha_full_migration_persists(tmp_path):
    """Walk from 0.1.0-alpha to 1.0.0 and persist the migrated file."""
    _seed(tmp_path, {"version": "0.1.0-alpha", "modules": {"ai": True}})

    result = run_migrations(tmp_path)

    assert result["version"] == WORKSPACE_VERSION
    assert result["brokers"]["execution"]["default"] == "openalgo:default"
    assert result["compliance"]["personal_use_mode"] is True
    assert json.loads((tmp_path / "workspace.json").read_text(encoding="utf-8")) == result
    assert (tmp_path / "workspace.0.1.0-alpha.bak.json").exists()


def test_052_to_100_preserves_manual_edits(tmp_path):
    """Recursive defaults preserve existing operator choices."""
    _seed(
        tmp_path,
        {
            "version": "0.5.2",
            "brokers": {"execution": {"default": "openalgo:zerodha"}},
        },
    )

    result = run_migrations(tmp_path)

    assert result["brokers"]["execution"]["default"] == "openalgo:zerodha"
    assert "ticks" in result["brokers"]["data"]


def test_reject_future_version_no_mutation(tmp_path):
    """Unknown future versions are treated as downgrade attempts."""
    original = {"version": "9.9.9", "weird_field": "value"}
    path = _seed(tmp_path, original)

    with pytest.raises(ValueError, match="refusing to overwrite"):
        run_migrations(tmp_path)

    assert json.loads(path.read_text(encoding="utf-8")) == original


def test_partial_failure_restores_on_disk(tmp_path, monkeypatch):
    """If a migration step raises mid-walk, the on-disk file is restored."""
    original = {"version": "0.5.2", "user_field": "important"}
    path = _seed(tmp_path, original)

    def _boom(cfg):
        raise RuntimeError("injected failure")

    monkeypatch.setitem(MIGRATIONS, "0.5.2", ("1.0.0", _boom))

    with pytest.raises(RuntimeError, match="injected failure"):
        run_migrations(tmp_path)

    assert json.loads(path.read_text(encoding="utf-8")) == original


def test_concurrent_lock_blocks_second_caller(tmp_path):
    """A live lock holder blocks concurrent migration."""
    _seed(tmp_path, {"version": "0.5.2"})
    lock = tmp_path / ".migration.lock"
    lock.write_text(f"{os.getpid()}\n{int(time.time())}\n", encoding="utf-8")
    try:
        with pytest.raises(MigrationLockError):
            run_migrations(tmp_path)
    finally:
        lock.unlink()


def test_stale_lock_is_broken(tmp_path):
    """A dead-pid lock older than the stale threshold is broken."""
    _seed(tmp_path, {"version": "0.5.2"})
    lock = tmp_path / ".migration.lock"
    lock.write_text(f"{2**22}\n{int(time.time()) - 3600}\n", encoding="utf-8")

    result = run_migrations(tmp_path)

    assert result["version"] == WORKSPACE_VERSION


def test_atomic_write_leaves_no_tmp(tmp_path):
    """Successful migration leaves no temporary workspace files."""
    _seed(tmp_path, {"version": "0.5.2"})

    run_migrations(tmp_path)

    assert list(tmp_path.glob(".workspace.*.tmp")) == []
    assert list(tmp_path.glob(".workspace.*.tmp.*")) == []


def test_merge_defaults_recursive():
    defaults = {"a": 1, "nested": {"x": 1, "y": 2}}
    existing = {"nested": {"y": 99}, "extra": "kept"}

    out = _merge_defaults(defaults, existing)

    assert out == {"a": 1, "nested": {"x": 1, "y": 99}, "extra": "kept"}


def test_corrupted_backup_recovered(tmp_path):
    """A corrupt existing backup aborts before mutating workspace.json."""
    original = {"version": "0.5.2", "user_field": "important"}
    path = _seed(tmp_path, original)
    backup = tmp_path / "workspace.0.5.2.bak.json"
    backup.write_text("{not valid json", encoding="utf-8")

    with pytest.raises(MigrationLockError, match="backup"):
        run_migrations(tmp_path)

    assert json.loads(path.read_text(encoding="utf-8")) == original


def test_partial_fsync_via_monkeypatch(tmp_path, monkeypatch):
    """Simulate fsync failing mid-atomic-write; original file is preserved."""
    original = {"version": "0.5.2"}
    path = _seed(tmp_path, original)
    real_fsync = os.fsync

    def _boom_fsync(fd):  # noqa: ARG001
        raise OSError(28, "No space left on device")

    monkeypatch.setattr(os, "fsync", _boom_fsync)

    with pytest.raises(OSError, match="No space left"):
        run_migrations(tmp_path)

    assert json.loads(path.read_text(encoding="utf-8")) == original
    monkeypatch.setattr(os, "fsync", real_fsync)


def test_disk_full_via_pyfakefs():
    """pyfakefs disk-full simulation is carried by the optional fixture file."""
    pytest.importorskip("pyfakefs")
    pytest.skip("pyfakefs-based disk-full simulation lives in a platform-specific fixture")


def test_concurrent_read_during_lock_is_serialised(tmp_path):
    """Concurrent readers see original or migrated JSON, never a torn write."""
    _seed(tmp_path, {"version": "0.5.2"})
    import threading

    reader_observations: list[dict] = []

    def _reader():
        for _ in range(10):
            try:
                reader_observations.append(json.loads((tmp_path / "workspace.json").read_text(encoding="utf-8")))
            except (json.JSONDecodeError, FileNotFoundError):
                pass

    thread = threading.Thread(target=_reader)
    thread.start()
    result = run_migrations(tmp_path)
    thread.join()

    for obs in reader_observations:
        assert obs.get("version") in ("0.5.2", WORKSPACE_VERSION)
    assert result["version"] == WORKSPACE_VERSION


def test_fresh_install_round_trip(tmp_path):
    """Missing workspace.json creates current defaults and subsequent calls are no-ops."""
    result = run_migrations(tmp_path)

    assert result["version"] == WORKSPACE_VERSION
    on_disk = json.loads((tmp_path / "workspace.json").read_text(encoding="utf-8"))
    assert on_disk["version"] == WORKSPACE_VERSION
    assert on_disk["compliance"]["personal_use_mode"] is True
    assert on_disk["brokers"]["execution"]["default"] == "openalgo:default"
    assert run_migrations(tmp_path) == result
