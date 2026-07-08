"""Streaming session contract for agent backends.

This is layer 3 of the Hermes-mirrored 4-layer agent-backend stack
(profiles → registry → session → per-runtime session). It defines the
provider-agnostic streaming abstraction that the route layer surfaces over
Server-Sent Events:

* :class:`AgentEvent` — the typed, JSON-friendly unit that every backend
  streams (assistant output, tool activity, errors, and a terminal marker).
* :class:`AgentSession` — the abstract lifecycle a concrete runtime (Codex
  app-server, Hermes ACP, Antigravity CLI) implements:
  :meth:`~AgentSession.ensure_started`, :meth:`~AgentSession.run_turn`
  (which streams events through an async callback), and
  :meth:`~AgentSession.close`.
* :class:`AgentBackendUnavailable` — the fail-closed signal a session raises
  when its underlying CLI/entrypoint is absent or cannot be launched.

The abstraction is intentionally dependency-light (stdlib only) so it can be
imported by the detection registry, the route layer, and tests without
pulling in any heavy transport code.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from enum import StrEnum
from typing import Any


class AgentEventKind(StrEnum):
    """The four event kinds a backend streams during a turn.

    * ``output`` — assistant-authored text (streaming chunk or a completed
      message). Reasoning summaries are tagged in ``data`` but keep this kind.
    * ``tool`` — a tool call/result or an approval round-trip.
    * ``error`` — a recoverable or terminal error the operator should see.
    * ``done`` — the terminal marker; exactly one per turn, carrying the
      aggregated result in ``data``.
    """

    OUTPUT = "output"
    TOOL = "tool"
    ERROR = "error"
    DONE = "done"


@dataclass
class AgentEvent:
    """A single streamed event from an agent backend.

    Attributes:
        kind: The :class:`AgentEventKind` discriminator.
        text: Human-readable payload (assistant text, tool summary, error
            message). ``None`` when the event carries only structured data.
        data: Optional structured metadata (tool arguments, exit codes,
            streaming flags, terminal turn summary). JSON-serialisable.
    """

    kind: AgentEventKind
    text: str | None = None
    data: dict[str, Any] | None = None

    def to_dict(self) -> dict[str, Any]:
        """Return a JSON-friendly dict for SSE serialisation."""
        payload: dict[str, Any] = {"kind": str(self.kind)}
        if self.text is not None:
            payload["text"] = self.text
        if self.data is not None:
            payload["data"] = self.data
        return payload


# An async sink the session pushes each :class:`AgentEvent` into as it streams.
# The route layer supplies one that writes SSE frames; tests supply one that
# appends to a list.
EventCallback = Callable[[AgentEvent], Awaitable[None]]


class AgentBackendUnavailable(RuntimeError):
    """Raised when an agent backend cannot be started (fail closed, honest).

    The concrete session raises this instead of leaking a raw
    ``FileNotFoundError`` when its CLI/entrypoint is absent or the spawn
    fails, so callers can surface a clear "install/configure this backend"
    message rather than an opaque OS error.
    """

    def __init__(self, backend_id: str, message: str, *, cause: BaseException | None = None) -> None:
        self.backend_id = backend_id
        self.reason = message
        super().__init__(f"agent backend {backend_id!r} unavailable: {message}")
        if cause is not None:
            self.__cause__ = cause


class AgentSession(ABC):
    """Abstract streaming session for one agent backend.

    A session owns one live conversation with a backend runtime. The lifecycle
    mirrors Hermes' ``Session`` pattern but is fully asynchronous:

        session = SomeSession(...)
        await session.ensure_started()          # spawn + handshake (idempotent)
        done = await session.run_turn(prompt, on_event)  # streams events
        await session.close()                   # tear down

    ``run_turn`` streams every intermediate :class:`AgentEvent` through the
    ``on_event`` callback and returns the terminal ``done`` event, whose
    ``data`` carries the aggregated turn summary.

    Subclasses set :attr:`backend_id` to the catalogue id they implement.
    """

    #: The catalogue backend id this session drives (set by subclasses).
    backend_id: str = ""

    @abstractmethod
    async def ensure_started(self) -> None:
        """Spawn the runtime and perform any handshake. Idempotent.

        Raises:
            AgentBackendUnavailable: if the runtime cannot be launched.
        """
        raise NotImplementedError

    @abstractmethod
    async def run_turn(self, prompt: str, on_event: EventCallback | None = None) -> AgentEvent:
        """Run one prompt→response turn, streaming events via ``on_event``.

        Args:
            prompt: The user/operator message to send to the backend.
            on_event: Async callback invoked once per streamed
                :class:`AgentEvent` (output, tool, error) and once for the
                terminal ``done`` event. May be ``None`` to discard the stream.

        Returns:
            The terminal ``done`` :class:`AgentEvent`.
        """
        raise NotImplementedError

    @abstractmethod
    async def close(self) -> None:
        """Tear down the runtime and release resources. Idempotent."""
        raise NotImplementedError

    async def __aenter__(self) -> AgentSession:
        await self.ensure_started()
        return self

    async def __aexit__(self, *exc: object) -> None:
        await self.close()
