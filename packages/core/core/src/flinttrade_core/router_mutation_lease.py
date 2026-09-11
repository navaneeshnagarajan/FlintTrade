"""One app-owned exclusion lease for broker-router authority mutations."""

from __future__ import annotations

import math
import os
import threading
from contextlib import contextmanager
from typing import Any, Iterator
from uuid import UUID
from weakref import WeakSet

from .backend_instance import BackendLeaseProof, require_backend_lease_proof


class RouterMutationLeaseUnavailable(RuntimeError):
    """The exact router-mutation exclusion capability is unavailable."""

    def __init__(self) -> None:
        super().__init__("router_mutation_lease_unavailable")


_TOKEN_SEAL = object()
_ISSUED_TOKENS: WeakSet[RouterMutationLeaseToken] = WeakSet()
_ACTIVE_GUARD = threading.Lock()
_ACTIVE_BY_LOCK: dict[object, RouterMutationLeaseToken | _RouterRetirementLeaseOwner] = {}


class _RouterRetirementLeaseOwner:
    """Private owner marker for proof-independent retirement-only cleanup."""

    def __init__(self, lock: object) -> None:
        self._lock = lock
        self._pid = os.getpid()
        self._thread = threading.current_thread()


class RouterMutationLeaseToken:
    """Opaque, thread-bound proof that one exact app rebuild lock is held."""

    def __init__(
        self,
        seal: object,
        *,
        app: Any | None = None,
        lock: object | None = None,
        operation_id: UUID | None = None,
        backend_lease_proof: BackendLeaseProof | None = None,
    ) -> None:
        if seal is not _TOKEN_SEAL:
            raise RouterMutationLeaseUnavailable
        self._app = app
        self._lock = lock
        self._operation_id = operation_id
        self._backend_lease_proof = backend_lease_proof
        self._backend_incarnation = backend_lease_proof.incarnation
        self._pid = os.getpid()
        self._thread = threading.current_thread()
        self._thread_ident = threading.get_ident()
        self._active = True
        _ISSUED_TOKENS.add(self)

    @property
    def operation_id(self) -> UUID:
        """Return the non-secret operation identity bound at acquisition."""
        return self._operation_id

    @property
    def backend_incarnation(self) -> UUID:
        """Return the live backend incarnation bound at acquisition."""
        return self._backend_incarnation

    def _revoke(self) -> None:
        self._active = False


def require_router_mutation_token(
    app: Any,
    token: object,
    *,
    operation_id: UUID | None = None,
) -> RouterMutationLeaseToken:
    """Validate one issued, active token for this app and calling thread."""
    if (
        type(token) is not RouterMutationLeaseToken
        or token not in _ISSUED_TOKENS
        or token._active is not True
        or token._app is not app
        or token._pid != os.getpid()
        or token._thread is not threading.current_thread()
        or token._thread_ident != threading.get_ident()
        or (operation_id is not None and token._operation_id != operation_id)
    ):
        raise RouterMutationLeaseUnavailable
    if app.config.get("BROKER_ROUTER_REBUILD_LOCK") is not token._lock:
        raise RouterMutationLeaseUnavailable
    configured_proof = app.config.get("BACKEND_LEASE_PROOF")
    if configured_proof is not None and configured_proof is not token._backend_lease_proof:
        raise RouterMutationLeaseUnavailable
    require_backend_lease_proof(token._backend_lease_proof)
    with _ACTIVE_GUARD:
        if _ACTIVE_BY_LOCK.get(token._lock) is not token:
            raise RouterMutationLeaseUnavailable
    return token


@contextmanager
def router_mutation_lease(
    app: Any,
    operation_id: UUID,
    *,
    backend_lease_proof: BackendLeaseProof,
    timeout: float,
) -> Iterator[RouterMutationLeaseToken]:
    """Hold the app's rebuild lock for one exact authority mutation.

    Nested rebuild helpers must receive and validate the yielded token. Calling
    this function again from the owning thread is deliberately refused even
    though the underlying lock is reentrant.
    """
    if type(operation_id) is not UUID or operation_id.version != 4:
        raise RouterMutationLeaseUnavailable
    try:
        bounded_timeout = float(timeout)
    except (TypeError, ValueError):
        raise RouterMutationLeaseUnavailable from None
    if not math.isfinite(bounded_timeout) or bounded_timeout < 0.0:
        raise RouterMutationLeaseUnavailable
    proof = require_backend_lease_proof(backend_lease_proof)
    lock = app.config.setdefault("BROKER_ROUTER_REBUILD_LOCK", threading.RLock())
    current_thread = threading.current_thread()
    with _ACTIVE_GUARD:
        active = _ACTIVE_BY_LOCK.get(lock)
        if active is not None and active._pid == os.getpid() and active._thread is current_thread:
            raise RouterMutationLeaseUnavailable
    try:
        acquired = bool(lock.acquire(timeout=bounded_timeout))
    except Exception:
        raise RouterMutationLeaseUnavailable from None
    if not acquired:
        raise RouterMutationLeaseUnavailable

    token: RouterMutationLeaseToken | None = None
    try:
        require_backend_lease_proof(proof)
        token = RouterMutationLeaseToken(
            _TOKEN_SEAL,
            app=app,
            lock=lock,
            operation_id=operation_id,
            backend_lease_proof=proof,
        )
        with _ACTIVE_GUARD:
            if _ACTIVE_BY_LOCK.get(lock) is not None:
                raise RouterMutationLeaseUnavailable
            _ACTIVE_BY_LOCK[lock] = token
        yield token
    finally:
        if token is not None:
            token._revoke()
            with _ACTIVE_GUARD:
                if _ACTIVE_BY_LOCK.get(lock) is token:
                    del _ACTIVE_BY_LOCK[lock]
        lock.release()


@contextmanager
def router_retirement_lease(
    app: Any,
    *,
    timeout: float,
) -> Iterator[None]:
    """Hold only the exclusion needed to retire already-owned generations.

    Cleanup remains possible after backend authority is revoked, but this
    context yields no mutation token and therefore cannot authorise a rebuild
    or publication. It also refuses same-thread RLock re-entry while either a
    mutation or another retirement owner is active.
    """
    try:
        bounded_timeout = float(timeout)
    except (TypeError, ValueError):
        raise RouterMutationLeaseUnavailable from None
    if not math.isfinite(bounded_timeout) or bounded_timeout < 0.0:
        raise RouterMutationLeaseUnavailable
    lock = app.config.setdefault("BROKER_ROUTER_REBUILD_LOCK", threading.RLock())
    current_thread = threading.current_thread()
    with _ACTIVE_GUARD:
        active = _ACTIVE_BY_LOCK.get(lock)
        if active is not None and active._pid == os.getpid() and active._thread is current_thread:
            raise RouterMutationLeaseUnavailable
    try:
        acquired = bool(lock.acquire(timeout=bounded_timeout))
    except Exception:
        raise RouterMutationLeaseUnavailable from None
    if not acquired:
        raise RouterMutationLeaseUnavailable

    owner = _RouterRetirementLeaseOwner(lock)
    try:
        with _ACTIVE_GUARD:
            if _ACTIVE_BY_LOCK.get(lock) is not None:
                raise RouterMutationLeaseUnavailable
            _ACTIVE_BY_LOCK[lock] = owner
        yield
    finally:
        with _ACTIVE_GUARD:
            if _ACTIVE_BY_LOCK.get(lock) is owner:
                del _ACTIVE_BY_LOCK[lock]
        lock.release()
