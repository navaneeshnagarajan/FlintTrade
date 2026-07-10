"""Compatibility facade for the retired swarm DAG executor.

The canonical implementation lives in :mod:`flinttrade_ai._team_dag`. This
module keeps the historical import surface while delegating all graph,
formatting, lifecycle, timeout, and execution behaviour to that implementation.
"""

from __future__ import annotations

import inspect
from collections.abc import Awaitable, Callable
from typing import Any, TypeAlias, cast

from ._team_dag import (
    TeamDagRunner,
    TeamEvent,
    TeamTask,
    _safe_format,
    build_dag,
    detect_cycle,
    topological_layers as _canonical_topological_layers,
)
from .llm_client import LLMClient, LLMMessage, LLMResponse


class SwarmTask(TeamTask):
    """Historical task model backed entirely by the canonical team schema."""


class SwarmEvent(TeamEvent):
    """Historical event model retaining its permissive event labels."""

    event_type: str


EventCallback: TypeAlias = Callable[[SwarmEvent], Awaitable[None] | None]

__all__ = [
    "SwarmEvent",
    "SwarmExecutor",
    "SwarmTask",
    "_safe_format",
    "build_dag",
    "detect_cycle",
    "topological_layers",
]


def _declared_callable(value: Any, name: str) -> Callable[..., Any] | None:
    """Return a real protocol method without triggering dynamic attributes."""
    if inspect.getattr_static(value, name, None) is None:
        return None
    candidate = getattr(value, name, None)
    return candidate if callable(candidate) else None


def _normalise_response(response: Any) -> LLMResponse:
    """Translate the legacy completion return type to the canonical response."""
    if isinstance(response, LLMResponse):
        return response
    if isinstance(response, str):
        return LLMResponse(content=response)
    raise TypeError("legacy LLM completions must return str or LLMResponse")


class _CompletionClientAdapter:
    """Expose legacy synchronous ``complete`` through canonical chat."""

    def __init__(self, client: Any) -> None:
        self._client = client
        if _declared_callable(client, "complete") is None:
            raise TypeError("llm_client must expose chat, async_complete, or complete")

    def chat(
        self,
        messages: list[LLMMessage],
        temperature: float | None = None,
    ) -> LLMResponse:
        """Call the historical completion API from the canonical worker thread."""
        del temperature
        system_prompt = messages[0].content
        user_prompt = messages[-1].content

        complete = _declared_callable(self._client, "complete")
        if complete is None:  # Guarded by __init__; retained for type narrowing.
            raise TypeError("llm_client must expose async_complete or complete")
        return _normalise_response(complete(system_prompt, user_prompt))


def _canonical_client(client: Any) -> LLMClient:
    """Use native canonical clients directly and adapt only legacy protocols."""
    if _declared_callable(client, "chat") is not None:
        return cast(LLMClient, client)
    return cast(LLMClient, _CompletionClientAdapter(client))


def topological_layers(tasks: list[SwarmTask]) -> list[list[str]]:
    """Delegate layering while preserving the legacy lowercase cycle message."""
    try:
        return _canonical_topological_layers(tasks)
    except ValueError as exc:
        message = str(exc)
        if "Cycle" in message:
            raise ValueError(message.replace("Cycle", "cycle", 1)) from exc
        raise


class SwarmExecutor:
    """Backward-compatible executor delegated to :class:`TeamDagRunner`."""

    def __init__(self, llm_client: Any) -> None:
        async_complete = _declared_callable(llm_client, "async_complete")
        if async_complete is None:
            self._runner = TeamDagRunner(_canonical_client(llm_client))
            return

        async def async_chat(
            messages: list[LLMMessage],
            temperature: float | None,
        ) -> LLMResponse:
            del temperature
            completion = async_complete(messages[0].content, messages[-1].content)
            if not inspect.isawaitable(completion):
                raise TypeError("async_complete must return an awaitable")
            return _normalise_response(await completion)

        self._runner = TeamDagRunner(None, async_chat=async_chat)

    async def execute(
        self,
        tasks: list[SwarmTask],
        on_event: EventCallback | None = None,
    ) -> dict[str, str]:
        """Execute legacy task declarations through the canonical DAG runner."""
        canonical_callback: Callable[[TeamEvent], Awaitable[None] | None] | None = None
        if on_event is not None:

            def canonical_callback(event: TeamEvent) -> Awaitable[None] | None:
                legacy_event = SwarmEvent.model_validate(event.model_dump())
                return on_event(legacy_event)

        return await self._runner.execute(tasks, on_event=canonical_callback)

    def _build_dag(self, tasks: list[SwarmTask]) -> dict[str, list[str]]:
        """Keep the historical graph-inspection helper as a thin delegation."""
        return build_dag(tasks)
