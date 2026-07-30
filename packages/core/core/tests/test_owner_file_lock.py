"""Cross-platform tests for owner-validated persistent file locks."""

from __future__ import annotations

import errno
import os
import sys
from types import SimpleNamespace

import pytest
from filelock import Timeout

from flinttrade_core import owner_file_lock, secure_file


class _FakeWindowsDescriptorSecurity:
    def __init__(
        self,
        events: list[str],
        *,
        owner_error: Exception | None = None,
        dacl_results: list[tuple[bool, str]] | None = None,
    ) -> None:
        self._events = events
        self._owner_error = owner_error
        self._dacl_results = list(dacl_results or [(True, ""), (True, "")])

    def prepare(self, descriptor: int) -> int:
        self._events.append("prepare")
        return descriptor

    def assert_current_user_owns(self, _descriptor: int, _path_stat: os.stat_result) -> None:
        self._events.append("owner")
        if self._owner_error is not None:
            raise self._owner_error

    def harden(self, _descriptor: int) -> None:
        self._events.append("harden")

    def verify_exact_dacl(self, _descriptor: int) -> tuple[bool, str]:
        self._events.append("dacl")
        return self._dacl_results.pop(0)


def _install_fake_msvcrt(  # type: ignore[no-untyped-def]
    monkeypatch,
    events: list[str],
    *,
    lock_error: OSError | None = None,
    on_lock=None,
) -> None:
    def locking(descriptor: int, operation: int, length: int) -> None:
        assert descriptor >= 0
        assert length == 1
        if operation == 1:
            events.append("lock")
            if on_lock is not None:
                on_lock()
            if lock_error is not None:
                raise lock_error
        elif operation == 2:
            events.append("unlock")
        else:  # pragma: no cover - test harness assertion
            raise AssertionError(f"unexpected operation: {operation}")

    monkeypatch.setitem(
        sys.modules,
        "msvcrt",
        SimpleNamespace(LK_NBLCK=1, LK_UNLCK=2, locking=locking),
    )


def test_windows_owner_lock_creation_hardens_before_lock_and_persists(tmp_path, monkeypatch) -> None:
    events: list[str] = []
    security = _FakeWindowsDescriptorSecurity(events)
    _install_fake_msvcrt(monkeypatch, events)
    monkeypatch.setattr(owner_file_lock, "_windows_descriptor_security", lambda: security)
    lock_path = tmp_path / "owner.lock"
    lock = owner_file_lock._WindowsOwnerSafeFileLock(lock_path, timeout=0, mode=0o600)

    lock._acquire()

    assert lock.is_locked
    assert events == [
        "prepare",
        "owner",
        "lock",
        "harden",
        "owner",
        "dacl",
        "owner",
        "dacl",
    ]
    identity = lock_path.stat().st_dev, lock_path.stat().st_ino

    lock._release()

    assert events[-1] == "unlock"
    assert lock_path.exists()
    assert (lock_path.stat().st_dev, lock_path.stat().st_ino) == identity


def test_windows_owner_lock_existing_file_is_validated_without_replacement(tmp_path, monkeypatch) -> None:
    events: list[str] = []
    security = _FakeWindowsDescriptorSecurity(events)
    _install_fake_msvcrt(monkeypatch, events)
    monkeypatch.setattr(owner_file_lock, "_windows_descriptor_security", lambda: security)
    lock_path = tmp_path / "owner.lock"
    lock_path.write_bytes(b"do-not-truncate")
    identity = lock_path.stat().st_dev, lock_path.stat().st_ino
    lock = owner_file_lock._WindowsOwnerSafeFileLock(lock_path, timeout=0, mode=0o600)

    lock._acquire()

    assert lock.is_locked
    assert events == ["prepare", "owner", "lock", "harden", "owner", "dacl", "owner", "dacl"]
    assert (lock_path.stat().st_dev, lock_path.stat().st_ino) == identity
    assert lock_path.read_bytes() == b"do-not-truncate"
    lock._release()


def test_windows_owner_lock_waiter_retries_during_creator_hardening_window(tmp_path, monkeypatch) -> None:
    events: list[str] = []
    security = _FakeWindowsDescriptorSecurity(
        events,
        dacl_results=[(False, "creator has not hardened the new inode yet")],
    )
    _install_fake_msvcrt(monkeypatch, events, lock_error=OSError(errno.EACCES, "busy"))
    monkeypatch.setattr(owner_file_lock, "_windows_descriptor_security", lambda: security)
    lock_path = tmp_path / "owner.lock"
    lock_path.write_bytes(b"")
    lock = owner_file_lock._WindowsOwnerSafeFileLock(lock_path, timeout=0, mode=0o600)

    lock._acquire()

    assert lock.is_locked is False
    assert events == ["prepare", "owner", "lock"]


def test_windows_owner_lock_repairs_a_crash_left_owner_owned_inode(tmp_path, monkeypatch) -> None:
    events: list[str] = []
    security = _FakeWindowsDescriptorSecurity(events)
    _install_fake_msvcrt(monkeypatch, events)
    monkeypatch.setattr(owner_file_lock, "_windows_descriptor_security", lambda: security)
    lock_path = tmp_path / "owner.lock"
    lock_path.write_bytes(b"crash-left-lock-inode")
    lock = owner_file_lock._WindowsOwnerSafeFileLock(lock_path, timeout=0, mode=0o600)

    lock._acquire()

    assert lock.is_locked
    assert events == ["prepare", "owner", "lock", "harden", "owner", "dacl", "owner", "dacl"]
    assert lock_path.read_bytes() == b"crash-left-lock-inode"
    lock._release()


@pytest.mark.parametrize(
    ("owner_error", "dacl_results"),
    [
        (PermissionError("wrong owner"), None),
        (None, [(False, "unexpected ACL")]),
    ],
)
def test_windows_owner_lock_rejects_unsafe_descriptor_security(
    tmp_path,
    monkeypatch,
    owner_error,
    dacl_results,
) -> None:
    events: list[str] = []
    security = _FakeWindowsDescriptorSecurity(
        events,
        owner_error=owner_error,
        dacl_results=dacl_results,
    )
    _install_fake_msvcrt(monkeypatch, events)
    monkeypatch.setattr(owner_file_lock, "_windows_descriptor_security", lambda: security)
    lock_path = tmp_path / "owner.lock"
    lock_path.write_bytes(b"")
    lock = owner_file_lock._WindowsOwnerSafeFileLock(lock_path, timeout=0, mode=0o600)

    with pytest.raises(owner_file_lock.UnsafeFileLockPathError):
        lock._acquire()

    if owner_error is not None:
        assert "lock" not in events
    else:
        assert events[-1] == "unlock"
    assert lock.is_locked is False
    assert lock_path.exists()


@pytest.mark.skipif(
    os.name == "nt",
    reason=(
        "the substitution is staged with rename-over-an-open-handle plus an unprivileged symlink, "
        "neither of which Windows provides; "
        "test_windows_owner_lock_rejects_post_lock_identity_rebinding covers the same product "
        "branch on every host"
    ),
)
def test_windows_owner_lock_rejects_post_lock_path_substitution(tmp_path, monkeypatch) -> None:
    events: list[str] = []
    security = _FakeWindowsDescriptorSecurity(events)
    lock_path = tmp_path / "owner.lock"
    original_path = tmp_path / "owner.original"
    substitute = tmp_path / "substitute"
    substitute.write_text("do-not-touch", encoding="utf-8")
    lock_path.write_bytes(b"")

    def substitute_path() -> None:
        lock_path.replace(original_path)
        lock_path.symlink_to(substitute)

    _install_fake_msvcrt(monkeypatch, events, on_lock=substitute_path)
    monkeypatch.setattr(owner_file_lock, "_windows_descriptor_security", lambda: security)
    lock = owner_file_lock._WindowsOwnerSafeFileLock(lock_path, timeout=0, mode=0o600)

    with pytest.raises(owner_file_lock.UnsafeFileLockPathError):
        lock._acquire()

    assert events == ["prepare", "owner", "lock", "harden", "owner", "dacl", "unlock"]
    assert lock.is_locked is False
    assert original_path.exists()
    assert lock_path.is_symlink()
    assert substitute.read_text(encoding="utf-8") == "do-not-touch"


def test_windows_owner_lock_rejects_post_lock_identity_rebinding(tmp_path, monkeypatch) -> None:
    """The lock path must still name the locked inode after hardening.

    The sibling test stages the rebinding with real filesystem calls, which only
    POSIX permits: Windows refuses to rename, replace or unlink a file while a
    handle without ``FILE_SHARE_DELETE`` is open on it (WinError 5/32), and it
    refuses unprivileged symlink creation. This test therefore drives the same
    product branch through the one call the post-lock revalidation actually
    makes - ``os.lstat`` on the lock path - so the rejection stays covered on
    every host.
    """
    events: list[str] = []
    security = _FakeWindowsDescriptorSecurity(events)
    lock_path = tmp_path / "owner.lock"
    substitute = tmp_path / "substitute"
    substitute.write_text("do-not-touch", encoding="utf-8")
    lock_path.write_bytes(b"")
    real_lstat = os.lstat
    rebound = False

    def rebinding_lstat(path, *args, **kwargs):  # type: ignore[no-untyped-def]
        if rebound and os.fspath(path) == os.fspath(lock_path):
            # The kernel now resolves the lock path to a different inode.
            return real_lstat(substitute)
        return real_lstat(path, *args, **kwargs)

    def rebind_path() -> None:
        nonlocal rebound
        rebound = True

    _install_fake_msvcrt(monkeypatch, events, on_lock=rebind_path)
    monkeypatch.setattr(owner_file_lock, "_windows_descriptor_security", lambda: security)
    monkeypatch.setattr(owner_file_lock.os, "lstat", rebinding_lstat)
    lock = owner_file_lock._WindowsOwnerSafeFileLock(lock_path, timeout=0, mode=0o600)

    with pytest.raises(owner_file_lock.UnsafeFileLockPathError):
        lock._acquire()

    assert events == ["prepare", "owner", "lock", "harden", "owner", "dacl", "unlock"]
    assert lock.is_locked is False
    assert lock_path.exists()
    assert substitute.read_text(encoding="utf-8") == "do-not-touch"


def test_windows_owner_lock_revalidates_dacl_after_locking(tmp_path, monkeypatch) -> None:
    events: list[str] = []
    security = _FakeWindowsDescriptorSecurity(
        events,
        dacl_results=[(True, ""), (False, "changed after lock")],
    )
    lock_path = tmp_path / "owner.lock"
    lock_path.write_bytes(b"")
    _install_fake_msvcrt(monkeypatch, events)
    monkeypatch.setattr(owner_file_lock, "_windows_descriptor_security", lambda: security)
    lock = owner_file_lock._WindowsOwnerSafeFileLock(lock_path, timeout=0, mode=0o600)

    with pytest.raises(owner_file_lock.UnsafeFileLockPathError):
        lock._acquire()

    assert events == ["prepare", "owner", "lock", "harden", "owner", "dacl", "owner", "dacl", "unlock"]
    assert lock.is_locked is False
    assert lock_path.exists()


def test_windows_owner_lock_rejects_a_preexisting_reparse_path(tmp_path, monkeypatch) -> None:
    events: list[str] = []
    target = tmp_path / "target"
    target.write_text("do-not-touch", encoding="utf-8")
    lock_path = tmp_path / "owner.lock"
    lock_path.symlink_to(target)
    _install_fake_msvcrt(monkeypatch, events)
    monkeypatch.setattr(
        owner_file_lock,
        "_windows_descriptor_security",
        lambda: _FakeWindowsDescriptorSecurity(events),
    )
    lock = owner_file_lock._WindowsOwnerSafeFileLock(lock_path, timeout=0, mode=0o600)

    with pytest.raises(owner_file_lock.UnsafeFileLockPathError):
        lock._acquire()

    assert events == []
    assert target.read_text(encoding="utf-8") == "do-not-touch"


def test_windows_owner_lock_rejects_a_hard_link_without_truncation(tmp_path, monkeypatch) -> None:
    events: list[str] = []
    target = tmp_path / "target"
    target.write_text("do-not-truncate", encoding="utf-8")
    lock_path = tmp_path / "owner.lock"
    os.link(target, lock_path)
    _install_fake_msvcrt(monkeypatch, events)
    monkeypatch.setattr(
        owner_file_lock,
        "_windows_descriptor_security",
        lambda: _FakeWindowsDescriptorSecurity(events),
    )
    lock = owner_file_lock._WindowsOwnerSafeFileLock(lock_path, timeout=0, mode=0o600)

    with pytest.raises(owner_file_lock.UnsafeFileLockPathError):
        lock._acquire()

    assert events == []
    assert target.read_text(encoding="utf-8") == "do-not-truncate"


@pytest.mark.skipif(os.name != "nt", reason="Windows lock and ACL runtime semantics")
def test_windows_owner_lock_runtime_persists_inode_and_exact_dacl(tmp_path) -> None:
    lock_path = tmp_path / "owner.lock"
    moved_path = tmp_path / "owner.moved"
    first = owner_file_lock.OwnerSafeFileLock(lock_path, timeout=0, mode=0o600)
    second = owner_file_lock.OwnerSafeFileLock(lock_path, timeout=0, mode=0o600)

    with first:
        first_identity = lock_path.stat().st_dev, lock_path.stat().st_ino
        hardened, reason = secure_file._verify_exact_windows_dacl(lock_path)
        assert hardened, reason
        with pytest.raises(Timeout):
            second.acquire(timeout=0)
        with pytest.raises(OSError):
            lock_path.replace(moved_path)
        with pytest.raises(OSError):
            lock_path.unlink()

    assert lock_path.exists()
    lock_path.replace(moved_path)
    moved_path.replace(lock_path)
    with second:
        assert (lock_path.stat().st_dev, lock_path.stat().st_ino) == first_identity
