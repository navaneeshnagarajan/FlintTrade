"""Cross-process ownership for one FlintTrade backend per workspace."""

from __future__ import annotations

from contextlib import suppress
import errno
import os
import threading
from typing import Any
from weakref import WeakSet

from filelock import BaseFileLock, FileLock, Timeout as FileLockTimeout

if os.name == "posix":
    import fcntl

from .workspace import workspace_dir


class BackendInstanceAlreadyRunning(RuntimeError):
    """Raised when another backend owns the active workspace."""


class _PosixBackendFileLease:
    """Explicit POSIX lock owner with no destructor-side unlock."""

    def __init__(self, descriptor: int) -> None:
        self._descriptor = descriptor

    def release(self) -> None:
        descriptor = self._descriptor
        if descriptor is None:
            return
        fcntl.flock(descriptor, fcntl.LOCK_UN)
        os.close(descriptor)
        self._descriptor = None

    def detach_after_fork(self) -> None:
        """Close only the child's descriptor duplicate, never the shared lock."""
        descriptor = self._descriptor
        self._descriptor = None
        if descriptor is not None:
            with suppress(OSError):
                os.close(descriptor)


class BackendInstanceLease:
    """PID-bound wrapper around the kernel-backed workspace lock.

    A pre-fork child inherits the parent's Python objects and lock descriptor.
    It must never release that descriptor or treat the inherited lease as its
    own backend authority.
    """

    def __init__(self, raw_lease: BaseFileLock | Any, *, owner_pid: int | None = None) -> None:
        self._raw_lease = raw_lease
        self._owner_pid = os.getpid() if owner_pid is None else int(owner_pid)
        self._guard = threading.Lock()
        self._released = False
        self._recovery_owner: Any | None = None
        _LIVE_BACKEND_LEASES.add(self)

    @property
    def owner_pid(self) -> int:
        """Process that acquired the underlying kernel lock."""
        return self._owner_pid

    @property
    def recovery_owner(self) -> Any | None:
        """Runtime retaining exact cleanup authority after an incomplete exit."""
        with self._guard:
            return self._recovery_owner

    def retain_recovery_owner(self, owner: Any) -> None:
        """Tie this retained lease to the runtime that can finish cleanup."""
        with self._guard:
            if self._released:
                raise RuntimeError("released backend lease cannot retain recovery authority")
            self._recovery_owner = owner

    def release(self) -> None:
        """Release only from the process that acquired this lease."""
        if os.getpid() != self._owner_pid:
            raise RuntimeError("inherited backend lease cannot be released by a forked process")
        with self._guard:
            if self._released:
                return
            try:
                self._raw_lease.release()
            except BaseException:  # noqa: BLE001 - failed authority must remain reachable
                retain_backend_instance_lease(self)
                raise
            self._released = True
            self._recovery_owner = None
            with _RETAINED_FAILED_LEASES_LOCK:
                _RETAINED_FAILED_LEASES[:] = [
                    retained for retained in _RETAINED_FAILED_LEASES if retained is not self
                ]


_LIVE_BACKEND_LEASES: WeakSet[BackendInstanceLease] = WeakSet()
_RETAINED_FAILED_LEASES: list[BackendInstanceLease | Any] = []
_RETAINED_FAILED_LEASES_LOCK = threading.Lock()


def _detach_inherited_backend_lock_descriptors() -> None:
    """Close fork-inherited descriptors without unlocking the parent's lease.

    ``flock`` ownership follows the open file description shared across a
    fork. Closing the child-side descriptor without issuing ``LOCK_UN`` leaves
    the parent's duplicate descriptor, and its lock, intact.
    """
    child_pid = os.getpid()
    for lease in tuple(_LIVE_BACKEND_LEASES):
        if lease._owner_pid == child_pid:  # noqa: SLF001 - module-owned lease state
            continue
        raw_lease = lease._raw_lease  # noqa: SLF001 - module-owned lease state
        detach = getattr(raw_lease, "detach_after_fork", None)
        if callable(detach):
            detach()
        lease._released = True  # noqa: SLF001 - child must never own this lease


if hasattr(os, "register_at_fork"):
    os.register_at_fork(after_in_child=_detach_inherited_backend_lock_descriptors)


def retain_backend_instance_lease(lease: BackendInstanceLease | Any) -> None:
    """Keep an unsafe-to-release lease alive until operating-system teardown."""
    with _RETAINED_FAILED_LEASES_LOCK:
        if not any(retained is lease for retained in _RETAINED_FAILED_LEASES):
            _RETAINED_FAILED_LEASES.append(lease)


def release_retained_backend_instance_lease(lease: BackendInstanceLease | Any) -> None:
    """Release a retained lease after its recovery owner proves cleanup."""
    lease.release()
    with _RETAINED_FAILED_LEASES_LOCK:
        _RETAINED_FAILED_LEASES[:] = [retained for retained in _RETAINED_FAILED_LEASES if retained is not lease]


def acquire_backend_instance_lease() -> BackendInstanceLease:
    """Acquire the process-lifetime backend lease without waiting.

    Ownership comes exclusively from the operating system lock held by
    :mod:`filelock`. Lock-file contents are never interpreted, so stale text
    cannot create or revoke ownership.

    Returns:
        The acquired lease. Its owner must retain it for the complete backend
        lifetime and call :meth:`~filelock.BaseFileLock.release` on exit.

    Raises:
        BackendInstanceAlreadyRunning: If another process owns this workspace.
    """
    lock_path = workspace_dir() / "backend_instance.lock"
    if os.name == "posix":
        descriptor = os.open(lock_path, os.O_RDWR | os.O_CREAT, 0o600)
        try:
            fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError as exc:
            with suppress(OSError):
                os.close(descriptor)
            if exc.errno not in {errno.EACCES, errno.EAGAIN}:
                raise
            raise BackendInstanceAlreadyRunning(
                "another FlintTrade backend already owns this workspace\n"
                f"  lock file: {lock_path}\n"
                "  stop the other backend or choose a different workspace"
            ) from None
        raw_lease: BaseFileLock | Any = _PosixBackendFileLease(descriptor)
    else:
        raw_lease = FileLock(lock_path, timeout=0, mode=0o600, thread_local=False)
        try:
            raw_lease.acquire()
        except FileLockTimeout:
            raise BackendInstanceAlreadyRunning(
                "another FlintTrade backend already owns this workspace\n"
                f"  lock file: {lock_path}\n"
                "  stop the other backend or choose a different workspace"
            ) from None

    # ``mode`` applies when filelock creates the inode. Tighten a pre-existing
    # stale file as well; ownership still comes only from the kernel lock.
    with suppress(OSError):
        lock_path.chmod(0o600)
    return BackendInstanceLease(raw_lease)
