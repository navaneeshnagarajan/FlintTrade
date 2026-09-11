"""Coordinator-owned cross-process lock order and scoped ownership capabilities.

Authority adapters enter ``authority_fence`` around their existing locks. The
check precedes acquisition, so an inverse attempt cannot wait on a peer. This
module does not claim that an unintegrated legacy facade uses these guards.
"""

from __future__ import annotations

import os
import threading
from contextlib import AbstractContextManager, contextmanager
from contextvars import ContextVar
from enum import IntEnum
from typing import Iterator
from weakref import WeakSet

from .backend_instance import BackendLeaseProof, require_backend_lease_proof
from .installation_state import InstallationState
from .owner_file_lock import OwnerSafeFileLock
from .secure_file import HeldOwnerDirectory


class AccountLockOrderError(RuntimeError):
    """An inverse acquisition or expired held capability was refused."""

    def __init__(self) -> None:
        super().__init__("account_lock_order_invalid")


class LockLevel(IntEnum):
    """The approved order; irrelevant levels may be skipped."""

    BACKUP_CONTROL = 10
    COORDINATOR = 20
    SOURCE_WRITER = 30
    ROUTER = 40
    DITTO_METADATA = 50
    DITTO_SOURCE_VAULT = 60
    TICK_LIFECYCLE = 70
    WORKSPACE = 80
    SECRET_STORE = 90
    SQLITE_IMMEDIATE = 100
    REGISTRY = 110


_STACK: ContextVar[tuple[tuple[int, str], ...]] = ContextVar("account_lock_order", default=())
_SEAL = object()
_TOKENS: WeakSet[OperationLockToken] = WeakSet()


class OperationLockToken:
    """Non-serialisable proof of the live coordinator scope on this thread."""

    def __init__(self, seal: object, proof: BackendLeaseProof, installation: InstallationState) -> None:
        if seal is not _SEAL:
            raise AccountLockOrderError
        self._proof = proof
        self._installation = installation
        self._pid = os.getpid()
        self._thread = threading.get_ident()
        self._active = True
        _TOKENS.add(self)

    def __reduce__(self) -> object:
        raise AccountLockOrderError


def require_operation_lock(token: object, *, installation: InstallationState | None = None) -> OperationLockToken:
    """Validate issuance, process/thread, live backend and installation binding."""
    if (
        type(token) is not OperationLockToken or token not in _TOKENS or not token._active
        or token._pid != os.getpid() or token._thread != threading.get_ident()
        or not any(level == LockLevel.COORDINATOR for level, _ in _STACK.get())
        or (installation is not None and token._installation.root != installation.root)
    ):
        raise AccountLockOrderError
    require_backend_lease_proof(token._proof)
    token._installation.assert_mutation_ready()
    return token


@contextmanager
def authority_fence(
    level: LockLevel, authority_id: str, lock: AbstractContextManager[object],
) -> Iterator[None]:
    """Enter an existing authority lock after rejecting inverse and equal IDs."""
    if type(level) is not LockLevel or type(authority_id) is not str or not authority_id:
        raise AccountLockOrderError
    key = (int(level), authority_id)
    held = _STACK.get()
    if held and key <= held[-1]:
        raise AccountLockOrderError
    # There is exactly one coordinator, router, workspace, tick and SQLite tier.
    if any(rank == level for rank, _ in held) and level not in {LockLevel.SOURCE_WRITER, LockLevel.SECRET_STORE}:
        raise AccountLockOrderError
    reset = _STACK.set((*held, key))
    try:
        with lock:
            yield
    finally:
        _STACK.reset(reset)


class CoordinatorOperationLock:
    """One persistent owner-safe kernel lock in the installation root."""

    def __init__(self, installation: InstallationState, *, timeout: float = 10) -> None:
        self.installation = installation
        self.timeout = timeout
        self.path = installation.root / ".account-coordinator.lock"

    @contextmanager
    def hold(self, proof: BackendLeaseProof) -> Iterator[OperationLockToken]:
        """Hold backend → optional backup control → coordinator continuously."""
        require_backend_lease_proof(proof)
        self.installation.assert_mutation_ready()
        lock = OwnerSafeFileLock(self.path, mode=0o600, timeout=self.timeout)
        with authority_fence(LockLevel.COORDINATOR, "accounts", lock):
            with HeldOwnerDirectory(self.installation.root) as directory:
                # The owner-safe lock validates its inode; also require its mode.
                directory.read_text(self.path.name, max_bytes=1)
                self.installation.assert_mutation_ready()
                token = OperationLockToken(_SEAL, proof, self.installation)
                try:
                    yield token
                finally:
                    token._active = False
