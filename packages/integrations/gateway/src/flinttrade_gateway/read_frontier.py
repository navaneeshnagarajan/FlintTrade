"""Owner-bound read checks carried across SDK executor and transport waits.

Only the existing read owner installs a check. This context is not a public
capability, an adapter-wide latest request, or evidence of worker cancellation.
Adapters with additional queues must check again after their final wait and
immediately before the uninvoked resource. Work already invoked stays owned.
"""

from __future__ import annotations

import asyncio
import threading
import time
import weakref
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from contextvars import ContextVar

_READ_INVOCATION: ContextVar[Callable[[], None] | None] = ContextVar("broker_read_invocation", default=None)


@contextmanager
def read_invocation_guard(check: Callable[[], None]) -> Iterator[None]:
    """Carry an existing owner's verification through one adapter operation.

    Args:
        check: Owner-bound current grant, session, authority and deadline check.

    Yields:
        No new authority; the context only constrains this operation.
    """
    previous = _READ_INVOCATION.get()

    def combined() -> None:
        if previous is not None:
            previous()
        check()

    token = _READ_INVOCATION.set(combined)
    try:
        yield
    finally:
        _READ_INVOCATION.reset(token)


def verify_read_invocation() -> None:
    """Refuse stale uninvoked work after a wait, without cancelling any worker.

    Direct adapter operations without a read-owner context keep their existing
    policy. In particular this helper neither grants nor changes write authority.
    """
    check = _READ_INVOCATION.get()
    if check is not None:
        check()


_DIAGNOSTIC_LOOP: ContextVar[weakref.ReferenceType[asyncio.AbstractEventLoop] | None] = ContextVar(
    "broker_read_diagnostic_loop", default=None
)


@contextmanager
def read_diagnostics(loop: asyncio.AbstractEventLoop) -> Iterator[None]:
    """Keep per-call error reporting without giving the caller worker custody.

    Args:
        loop: Originating caller loop; it may legitimately close before the SDK.

    Yields:
        A diagnostic context copied into this operation's callbacks.
    """
    token = _DIAGNOSTIC_LOOP.set(weakref.ref(loop))
    try:
        yield
    finally:
        _DIAGNOSTIC_LOOP.reset(token)


def _report_read_exception(loop: asyncio.AbstractEventLoop, context: dict[str, object]) -> None:
    """Report unchanged SDK diagnostics to a live origin, otherwise locally."""
    reference = _DIAGNOSTIC_LOOP.get()
    origin = reference() if reference is not None else None
    if origin is not None and origin is not loop and origin.is_running():
        try:
            origin.call_soon_threadsafe(origin.call_exception_handler, context)
            return
        except RuntimeError:
            pass  # The caller may finish between checking and scheduling.
    loop.default_exception_handler(context)


class ReadContinuation:
    """Private execution component drained only by its existing read owner.

    It has no grants, sessions or independent cleanup authority. Construction
    is lazy; the read owner serialises submission against retirement and never
    closes this loop while its admitted-operation count is nonzero.
    """

    def __init__(self) -> None:
        self.loop: asyncio.AbstractEventLoop = asyncio.new_event_loop()
        self._stop_lock = threading.Lock()
        self._stopping = False
        self._thread = threading.Thread(target=self._run, name="broker-read-continuation", daemon=True)
        self._thread.start()

    def _run(self) -> None:
        """Keep SDK tasks alive independently of disposable caller loops."""
        asyncio.set_event_loop(self.loop)
        self.loop.set_exception_handler(_report_read_exception)
        try:
            self.loop.run_forever()
        finally:
            try:
                # The owner must have drained every task before stopping. Never
                # cancel/gather held workers here to hide a premature close.
                self.loop.run_until_complete(self.loop.shutdown_asyncgens())
                self.loop.run_until_complete(self.loop.shutdown_default_executor())
            finally:
                self.loop.close()
                asyncio.set_event_loop(None)

    def close(self, deadline: float) -> bool:
        """Join this drained component under the owner's existing deadline.

        Args:
            deadline: Absolute monotonic deadline, not a fresh cleanup budget.

        Returns:
            Whether the original thread and its executor have actually exited.
        """
        with self._stop_lock:
            if not self._stopping:
                self._stopping = True
                self.loop.call_soon_threadsafe(self.loop.stop)
        if threading.current_thread() is self._thread:
            return False
        self._thread.join(max(0.0, deadline - time.monotonic()))
        return not self._thread.is_alive()
