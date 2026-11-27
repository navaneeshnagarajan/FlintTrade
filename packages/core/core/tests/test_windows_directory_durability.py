"""Windows branches of workspace hardening and directory durability."""

from __future__ import annotations

import os
import sys
from types import SimpleNamespace

import pytest

from flinttrade_core import legacy_sqlite_migration, workspace


def test_directory_sync_on_windows_uses_the_write_through_barrier(tmp_path, monkeypatch):
    barriers = []
    monkeypatch.setattr(legacy_sqlite_migration, "os", SimpleNamespace(name="nt"))
    monkeypatch.setattr(legacy_sqlite_migration, "barrier_directory", barriers.append)
    legacy_sqlite_migration.fsync_directory(tmp_path)
    assert barriers == [tmp_path]


@pytest.mark.skipif(sys.platform == "win32", reason="POSIX directory descriptor")
def test_directory_sync_on_posix_fsyncs_the_directory(tmp_path, monkeypatch):
    synced = []
    real_fsync = os.fsync

    def record(descriptor):
        synced.append(os.fstat(descriptor).st_ino)
        real_fsync(descriptor)

    monkeypatch.setattr(legacy_sqlite_migration, "barrier_directory", lambda path: pytest.fail("barrier on POSIX"))
    monkeypatch.setattr(os, "fsync", record)
    legacy_sqlite_migration.fsync_directory(tmp_path)
    assert synced == [tmp_path.stat().st_ino]


@pytest.mark.parametrize(("hardened", "expected"), [(False, 1), (True, 0)])
def test_windows_workspace_gets_the_owner_dacl_only_when_missing(tmp_path, monkeypatch, hardened, expected):
    installed = []
    monkeypatch.setattr(workspace, "os", SimpleNamespace(name="nt"))
    monkeypatch.setattr(workspace, "assert_hardened", lambda path: (hardened, ""))
    monkeypatch.setattr(workspace, "harden_directory", installed.append)
    workspace._lock_workspace_perms(tmp_path)
    assert installed == [tmp_path] * expected


def test_windows_workspace_hardening_failure_is_not_fatal(tmp_path, monkeypatch):
    def refuse(path):
        raise OSError("foreign ACL")

    monkeypatch.setattr(workspace, "os", SimpleNamespace(name="nt"))
    monkeypatch.setattr(workspace, "assert_hardened", lambda path: (False, "inherited"))
    monkeypatch.setattr(workspace, "harden_directory", refuse)
    workspace._lock_workspace_perms(tmp_path)


@pytest.mark.skipif(sys.platform == "win32", reason="POSIX mode bits")
def test_posix_workspace_is_owner_only(tmp_path, monkeypatch):
    monkeypatch.setattr(workspace, "harden_directory", lambda path: pytest.fail("DACL on POSIX"))
    tmp_path.chmod(0o755)
    workspace._lock_workspace_perms(tmp_path)
    assert tmp_path.stat().st_mode & 0o777 == 0o700
