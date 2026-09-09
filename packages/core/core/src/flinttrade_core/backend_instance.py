"""Cross-process ownership for one FlintTrade backend per workspace."""

from __future__ import annotations

import errno
import os
import secrets
import select
import struct
import threading
from collections.abc import Callable
from contextlib import suppress
from typing import Any
from uuid import UUID, uuid4
from weakref import WeakSet

from filelock import BaseFileLock, FileLock, Timeout as FileLockTimeout

if os.name == "posix":
    import fcntl

from .workspace import workspace_dir


class BackendInstanceAlreadyRunning(RuntimeError):
    """Raised when another backend owns the active workspace."""


class BackendLeaseUnavailable(RuntimeError):
    """A backend no longer owns the capability required for runtime work."""

    def __init__(self) -> None:
        super().__init__("backend_lease_unavailable")


_PROOF_SEAL = object()
_ISSUED_PROOFS: WeakSet[BackendLeaseProof] = WeakSet()
_ISSUED_HANDOFFS: WeakSet[BackendLeaseHandoff] = WeakSet()


class BackendLeaseProof:
    """Opaque, process-bound live capability; never serialised or reconstructed."""

    def __init__(
        self, seal: object, *, lease: BackendInstanceLease | None = None, guardian_fd: int | None = None,
    ) -> None:
        if seal is not _PROOF_SEAL:
            raise BackendLeaseUnavailable
        self._incarnation = uuid4()
        self._pid = os.getpid()
        self._uid = os.getuid() if hasattr(os, "getuid") else None
        self._lease = lease
        self._workspace_path = (lease._lock_path.parent if lease is not None else workspace_dir()).resolve()
        self._guardian_fd = guardian_fd
        self._revoked = threading.Event()
        self._watch_lock = threading.Lock()
        self._local_watching = False
        _ISSUED_PROOFS.add(self)

    @property
    def incarnation(self) -> UUID:
        """Non-secret generation bound into later write admission."""
        return self._incarnation

    def wait_revoked(self, timeout: float | None = None) -> bool:
        """Wait for one-way revocation without exposing a mutable event."""
        return self._revoked.wait(timeout)

    def revoke(self) -> None:
        """Invalidate admission before any lease/channel cleanup."""
        self._revoked.set()
        if self._lease is not None:
            for handoff in tuple(self._lease._handoffs):
                handoff.close()

    def _watch_guardian(self) -> None:
        try:
            # The initial frame is the only permitted payload. EOF, another
            # frame or a broken descriptor all end this capability.
            os.read(self._guardian_fd, 1)
        except (OSError, TypeError):
            pass
        finally:
            self.revoke()
            with suppress(OSError):
                os.close(self._guardian_fd)

    def _watch_local(self) -> None:
        while not self._revoked.wait(0.05):
            if not self._lease._is_live():
                self.revoke()
                for handoff in tuple(self._lease._handoffs):
                    handoff.close()
                return

    def _start_local_watcher(self) -> None:
        with self._watch_lock:
            if not self._local_watching:
                self._local_watching = True
                threading.Thread(target=self._watch_local, name="backend-owner-watch", daemon=True).start()


def require_backend_lease_proof(proof: object) -> BackendLeaseProof:
    """Require a minted capability for the current process and live owner."""
    if type(proof) is not BackendLeaseProof or proof not in _ISSUED_PROOFS:
        raise BackendLeaseUnavailable
    uid = os.getuid() if hasattr(os, "getuid") else None
    if proof._pid != os.getpid() or proof._uid != uid or proof._revoked.is_set():
        raise BackendLeaseUnavailable
    if proof._workspace_path != workspace_dir().resolve():
        raise BackendLeaseUnavailable
    if proof._lease is not None and not proof._lease._is_live():
        proof.revoke()
        raise BackendLeaseUnavailable
    if proof._guardian_fd is not None:
        try:
            if select.select([proof._guardian_fd], [], [], 0)[0]:
                proof.revoke()
                raise BackendLeaseUnavailable
        except (OSError, ValueError):
            proof.revoke()
            raise BackendLeaseUnavailable from None
    return proof


def initialise_backend_runtime[T](proof: BackendLeaseProof, builder: Callable[[], T]) -> T:
    """Single ownership boundary before constructing process-owned runtimes.

    Recover-first account publication is installed behind this boundary by
    the coordinator cutover. Until then the account-mutation guard stays shut.
    """
    require_backend_lease_proof(proof)
    return builder()


class BackendLeaseHandoff:
    """Private inherited pipe and nonce, issued by an actual kernel owner."""

    def __init__(self, seal: object, lease: BackendInstanceLease) -> None:
        if seal is not _PROOF_SEAL:
            raise BackendLeaseUnavailable
        self._lease = lease
        self._owner_pid = os.getpid()
        self._workspace_path = lease._lock_path.parent.resolve()
        self._nonce = secrets.token_bytes(32)
        self._read_fd, self._write_fd = os.pipe()
        self._consumed = False
        self._guard = threading.Lock()
        _ISSUED_HANDOFFS.add(self)

    def close(self) -> None:
        """Close the guardian's live endpoint before releasing its kernel lock."""
        if os.getpid() != self._owner_pid:
            return
        with self._guard:
            descriptor, self._write_fd = self._write_fd, None
            if descriptor is not None:
                os.close(descriptor)
            descriptor, self._read_fd = self._read_fd, None
            if descriptor is not None:
                os.close(descriptor)

    def publish(self, child_pid: int) -> None:
        """Guardian sends exactly one private frame and retains the live end."""
        if type(self) is not BackendLeaseHandoff or self not in _ISSUED_HANDOFFS:
            raise BackendLeaseUnavailable
        require_backend_lease_proof(self._lease.proof)
        with self._guard:
            if self._consumed or type(child_pid) is not int or child_pid <= 0 or child_pid == self._owner_pid:
                raise BackendLeaseUnavailable
            self._consumed = True
            os.close(self._read_fd)
            self._read_fd = None
            frame = struct.pack("!QQ32s", self._owner_pid, child_pid, self._nonce)
            if os.write(self._write_fd, frame) != len(frame):
                raise BackendLeaseUnavailable

    def claim(self) -> BackendLeaseProof:
        """Child validates and consumes its inherited authority exactly once."""
        if type(self) is not BackendLeaseHandoff or self not in _ISSUED_HANDOFFS:
            raise BackendLeaseUnavailable
        with self._guard:
            if (
                self._consumed or os.getpid() == self._owner_pid or os.getppid() != self._owner_pid
                or workspace_dir().resolve() != self._workspace_path
            ):
                raise BackendLeaseUnavailable
            self._consumed = True
            os.close(self._write_fd)
            self._write_fd = None
            descriptor, self._read_fd = self._read_fd, None
        try:
            if not select.select([descriptor], [], [], 5)[0]:
                raise BackendLeaseUnavailable
            frame = os.read(descriptor, 48)
            expected = struct.pack("!QQ32s", self._owner_pid, os.getpid(), self._nonce)
            if not secrets.compare_digest(frame, expected):
                raise BackendLeaseUnavailable
            proof = BackendLeaseProof(_PROOF_SEAL, guardian_fd=descriptor)
            require_backend_lease_proof(proof)
        except BaseException:
            os.close(descriptor)
            raise
        threading.Thread(target=proof._watch_guardian, name="backend-lease-watch", daemon=True).start()
        return proof


def prepare_backend_lease_handoff(lease: BackendInstanceLease) -> BackendLeaseHandoff:
    """Prepare the anonymous channel before the owning guardian forks."""
    if type(lease) is not BackendInstanceLease:
        raise BackendLeaseUnavailable
    # Do not start a local watcher until the guardian's post-fork publish.
    require_backend_lease_proof(lease._proof)
    handoff = BackendLeaseHandoff(_PROOF_SEAL, lease)
    lease._handoffs.append(handoff)
    return handoff


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
        self._proof: BackendLeaseProof | None = None
        self._lock_path = None
        self._lock_identity = None
        self._handoffs: list[BackendLeaseHandoff] = []
        _LIVE_BACKEND_LEASES.add(self)

    @property
    def proof(self) -> BackendLeaseProof:
        """Return proof only for a lease minted by kernel acquisition."""
        proof = require_backend_lease_proof(self._proof)
        proof._start_local_watcher()
        return proof

    def _is_live(self) -> bool:
        if self._released or self._owner_pid != os.getpid() or self._lock_identity is None:
            return False
        try:
            stat = self._lock_path.stat()
            if (stat.st_dev, stat.st_ino) != self._lock_identity:
                return False
            if isinstance(self._raw_lease, _PosixBackendFileLease):
                descriptor = self._raw_lease._descriptor
                return descriptor is not None and os.fstat(descriptor).st_ino == stat.st_ino
            return self._raw_lease.is_locked is True
        except OSError:
            return False

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
            if self._proof is not None:
                self._proof.revoke()
            for handoff in self._handoffs:
                handoff.close()
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
    lease = BackendInstanceLease(raw_lease)
    lease._lock_path = lock_path
    stat = lock_path.stat()
    lease._lock_identity = stat.st_dev, stat.st_ino
    lease._proof = BackendLeaseProof(_PROOF_SEAL, lease=lease)
    return lease
