"""Custody of an unreturned factory generation, including bounded rollback.

The factory records its app before acquiring resources. Entrypoints retain this
same release owner, never reconstruct cleanup around an already-running worker.
Borrowed root dependencies remain with the calling runtime until recovery ends.
"""
from __future__ import annotations

import threading
import time
from contextvars import ContextVar
from functools import wraps
from typing import Any

_CONSTRUCTION: ContextVar[list[Any] | None] = ContextVar("flinttrade_factory_construction", default=None)
_RETAINED: dict[int, Any] = {}
_LOCK = threading.Lock()

# Files/handles opened by the common factory. Aliases are deliberately excluded.
# Close only after runtime workers and all admitted requests have quiesced.
FACTORY_STORES = (
    "SYSTEM_INCIDENTS",
    "PRACTICE_AGENT_RUN_STORE", "DATA_SANDBOX_ENGINE", "AI_SESSION_STORE",
    "AUTH_SERVICE", "WEBHOOK_SECRET_STORE", "SERVICE_CONNECTION_STORE",
    "ACTIVITY_LOG", "SESSION_TRACKER", "LOGIN_ACTIVITY", "SECURITY_TRACKER",
    "API_ANALYZER", "TRAFFIC_LOGGER", "ERROR_LOG", "JOURNAL", "TRADE_STORAGE",
    "CREDENTIAL_STORE",
)


def capture_factory_app(app: Any, *, borrowed: frozenset[str]) -> None:
    """Register the exact partial app before the first owned constructor."""
    state = _CONSTRUCTION.get()
    if state is None or state:
        raise RuntimeError("factory construction custody unavailable")
    state.extend((app, borrowed))


def forget_factory_recovery(owner: Any) -> None:
    """Retire strong failure custody only after exact successful cleanup."""
    with _LOCK:
        if _RETAINED.get(id(owner)) is owner:
            _RETAINED.pop(id(owner))


def recover_factory(operation: Any) -> Any:
    """Keep the original construction error and attach exact recovery custody."""
    @wraps(operation)
    def construct(*args: Any, **kwargs: Any) -> Any:
        state: list[Any] = []
        token = _CONSTRUCTION.set(state)
        try:
            return operation(*args, **kwargs)
        except BaseException as error:
            if state:
                from .desktop import DesktopBackendShutdownIncomplete, _DesktopShutdownRecoveryOwner

                app, borrowed = state
                owner = _DesktopShutdownRecoveryOwner(app, borrowed_keys=borrowed)
                app.extensions["flinttrade.factory_recovery"] = owner
                error.recovery_owner = owner
                with _LOCK:
                    _RETAINED[id(owner)] = owner
                raw = app.config.get("RUNTIME_FACTORY_ROLLBACK_TIMEOUT_SECONDS", 10.0)
                try:
                    timeout = max(0.0, float(raw))
                except (TypeError, ValueError):
                    timeout = 10.0
                try:
                    owner.release(deadline=time.monotonic() + timeout)
                except DesktopBackendShutdownIncomplete:
                    pass  # The exception, entrypoint and strong custody retain it.
            raise
        finally:
            _CONSTRUCTION.reset(token)
    return construct
