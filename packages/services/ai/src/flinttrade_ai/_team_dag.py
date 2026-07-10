"""Private DAG execution primitives for the canonical multi-agent team."""

from __future__ import annotations

import asyncio
import inspect
import logging
import threading
from collections.abc import Awaitable, Callable, Mapping
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from string import Formatter
from typing import Any, Literal, TypeAlias, TypeVar

from pydantic import BaseModel, Field

from .llm_client import LLMClient, LLMMessage, LLMResponse

logger = logging.getLogger("flinttrade.ai.team_dag")

ModelTier: TypeAlias = Literal["quick", "deep"]
TeamEventType: TypeAlias = Literal["started", "progress", "completed", "error", "timeout"]

_ERROR_MESSAGE = "Task failed"
_ERROR_SENTINEL = f"[ERROR] {_ERROR_MESSAGE}"
_DEFAULT_MAX_CONCURRENT = 4
_FORMATTER = Formatter()
_T = TypeVar("_T")
_GLOBAL_MAX_WORKERS = 8
_GLOBAL_EXECUTOR = ThreadPoolExecutor(
    max_workers=_GLOBAL_MAX_WORKERS,
    thread_name_prefix="flinttrade-team",
)
_GLOBAL_WORKER_SLOTS = threading.BoundedSemaphore(_GLOBAL_MAX_WORKERS)


class TeamTask(BaseModel):
    """One executable node in a team dependency graph."""

    id: str
    name: str = ""
    agent_role: str
    prompt: str
    depends_on: list[str] = Field(default_factory=list)
    timeout_seconds: int = 120
    system_prompt: str | None = None
    model_tier: ModelTier = "quick"
    temperature: float | None = None


class TeamEvent(BaseModel):
    """A typed lifecycle event emitted while a team task runs."""

    task_id: str
    agent_role: str
    event_type: TeamEventType
    data: dict[str, Any] = Field(default_factory=dict)
    timestamp: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


EventCallback: TypeAlias = Callable[[TeamEvent], Awaitable[None] | None]
AsyncChatCallback: TypeAlias = Callable[
    [list[LLMMessage], float | None],
    Awaitable[LLMResponse],
]


def _validate_graph_references(tasks: list[TeamTask]) -> set[str]:
    """Validate identifiers and dependency references without executing tasks."""
    task_ids: set[str] = set()
    for task in tasks:
        if not task.id.strip():
            raise ValueError("task ID must not be blank")
        if task.id in task_ids:
            raise ValueError(f"duplicate task ID: {task.id!r}")
        task_ids.add(task.id)

    for task in tasks:
        for dependency_id in task.depends_on:
            if dependency_id not in task_ids:
                raise ValueError(f"Task {task.id!r} depends on unknown task {dependency_id!r}")
    return task_ids


def build_dag(tasks: list[TeamTask]) -> dict[str, list[str]]:
    """Return an adjacency list mapping each task to its direct successors."""
    _validate_graph_references(tasks)
    successors = {task.id: [] for task in tasks}
    for task in tasks:
        for dependency_id in task.depends_on:
            successors[dependency_id].append(task.id)
    return successors


def detect_cycle(tasks: list[TeamTask]) -> None:
    """Raise ``ValueError`` for invalid references or a dependency cycle."""
    task_ids = _validate_graph_references(tasks)
    dependencies = {task.id: task.depends_on for task in tasks}
    white, grey, black = 0, 1, 2
    colour = {task_id: white for task_id in task_ids}
    path: list[str] = []

    def visit(task_id: str) -> None:
        colour[task_id] = grey
        path.append(task_id)
        for dependency_id in dependencies[task_id]:
            if colour[dependency_id] == grey:
                cycle_start = path.index(dependency_id)
                cycle = " -> ".join([*path[cycle_start:], dependency_id])
                raise ValueError(f"Cycle detected in team task DAG: {cycle}")
            if colour[dependency_id] == white:
                visit(dependency_id)
        path.pop()
        colour[task_id] = black

    for task in tasks:
        if colour[task.id] == white:
            visit(task.id)


def topological_layers(tasks: list[TeamTask]) -> list[list[str]]:
    """Group task IDs into deterministic dependency-ordered layers."""
    detect_cycle(tasks)
    in_degree = {task.id: len(task.depends_on) for task in tasks}
    successors = build_dag(tasks)
    current_layer = [task.id for task in tasks if in_degree[task.id] == 0]
    layers: list[list[str]] = []
    processed = 0

    while current_layer:
        layers.append(current_layer)
        processed += len(current_layer)
        next_layer: list[str] = []
        for task_id in current_layer:
            for successor_id in successors[task_id]:
                in_degree[successor_id] -= 1
                if in_degree[successor_id] == 0:
                    next_layer.append(successor_id)
        current_layer = next_layer

    if processed != len(tasks):
        raise ValueError(f"Team task DAG contains a cycle: only {processed}/{len(tasks)} tasks could be ordered")
    return layers


def _placeholder(field_name: str, format_spec: str, conversion: str | None) -> str:
    """Reconstruct one replacement field exactly as parsed."""
    value = "{" + field_name
    if conversion is not None:
        value += f"!{conversion}"
    if format_spec:
        value += f":{format_spec}"
    return value + "}"


def _safe_format(template: str, values: Mapping[str, str]) -> str:
    """Format known fields while leaving missing or invalid fields intact."""
    try:
        parsed = list(_FORMATTER.parse(template))
    except ValueError:
        return template

    rendered: list[str] = []
    for literal, field_name, format_spec, conversion in parsed:
        rendered.append(literal)
        if field_name is None:
            continue

        placeholder = _placeholder(field_name, format_spec, conversion)
        if field_name not in values:
            rendered.append(placeholder)
            continue

        value: Any = values[field_name]
        if conversion == "s":
            value = str(value)
        elif conversion == "r":
            value = repr(value)
        elif conversion == "a":
            value = ascii(value)
        elif conversion is not None:
            rendered.append(placeholder)
            continue

        try:
            rendered.append(format(value, format_spec))
        except (TypeError, ValueError):
            rendered.append(placeholder)
    return "".join(rendered)


def _default_system_prompt(agent_role: str) -> str:
    """Build the legacy role-aware system prompt for a task."""
    return (
        f"You are a specialist trading agent acting as a {agent_role}. "
        "Provide a concise, actionable analysis. Focus on Indian markets "
        "(NSE/BSE/MCX). Return only your analysis, with no preamble."
    )


class _ThreadCallRunner:
    """Bound sync calls while retaining slots until their workers really exit."""

    def __init__(self, max_concurrent: int) -> None:
        if max_concurrent <= 0:
            raise ValueError("max_concurrent must be positive")
        self._semaphore = asyncio.Semaphore(max_concurrent)
        self._closed = False

    async def run(self, call: Callable[[], _T], timeout_seconds: float) -> _T:
        """Run one call with an await timeout and worker-owned concurrency slot."""
        if timeout_seconds <= 0:
            raise ValueError("timeout_seconds must be positive")
        if self._closed:
            raise RuntimeError("thread call runner is closed")

        loop = asyncio.get_running_loop()
        deadline = loop.time() + timeout_seconds
        await asyncio.wait_for(self._semaphore.acquire(), timeout=timeout_seconds)
        try:
            await self._acquire_global_slot(deadline)
        except BaseException:
            self._semaphore.release()
            raise

        def invoke() -> _T:
            try:
                return call()
            finally:
                _GLOBAL_WORKER_SLOTS.release()
                try:
                    loop.call_soon_threadsafe(self._semaphore.release)
                except RuntimeError:
                    # The owning analysis may have returned after a timeout.
                    pass

        try:
            remaining = deadline - loop.time()
            if remaining <= 0:
                raise TimeoutError
            future = loop.run_in_executor(_GLOBAL_EXECUTOR, invoke)
        except Exception:
            _GLOBAL_WORKER_SLOTS.release()
            self._semaphore.release()
            raise

        try:
            return await asyncio.wait_for(asyncio.shield(future), timeout=remaining)
        except TimeoutError:
            # Consume late exceptions without transferring ownership of the result.
            future.add_done_callback(self._consume_result)
            raise

    def close(self) -> None:
        """Reject new work without pretending active Python threads are cancellable."""
        self._closed = True

    @staticmethod
    async def _acquire_global_slot(deadline: float) -> None:
        """Acquire a process-wide worker slot without blocking the event loop."""
        loop = asyncio.get_running_loop()
        while not _GLOBAL_WORKER_SLOTS.acquire(blocking=False):
            remaining = deadline - loop.time()
            if remaining <= 0:
                raise TimeoutError
            await asyncio.sleep(min(0.01, remaining))

    @staticmethod
    def _consume_result(future: asyncio.Future[Any]) -> None:
        if future.cancelled():
            return
        try:
            future.exception()
        except (asyncio.CancelledError, Exception):  # noqa: BLE001
            pass


class _AsyncCallRunner:
    """Bound native async calls and cancel them when their timeout expires."""

    def __init__(self, max_concurrent: int) -> None:
        if max_concurrent <= 0:
            raise ValueError("max_concurrent must be positive")
        self._semaphore = asyncio.Semaphore(max_concurrent)

    async def run(
        self,
        call: Callable[[], Awaitable[_T]],
        timeout_seconds: float,
    ) -> _T:
        """Run one caller-loop coroutine within the shared concurrency bound."""
        if timeout_seconds <= 0:
            raise ValueError("timeout_seconds must be positive")

        async def invoke() -> _T:
            async with self._semaphore:
                return await call()

        return await asyncio.wait_for(invoke(), timeout=timeout_seconds)


class TeamDagRunner:
    """Execute validated team tasks layer by layer through ``LLMClient.chat``."""

    def __init__(
        self,
        quick_llm: LLMClient | None,
        deep_llm: LLMClient | None = None,
        *,
        call_runner: _ThreadCallRunner | None = None,
        async_chat: AsyncChatCallback | None = None,
    ) -> None:
        if quick_llm is None and async_chat is None:
            raise ValueError("quick_llm or async_chat is required")
        self._quick_llm = quick_llm
        self._deep_llm = deep_llm or quick_llm
        self._call_runner = call_runner
        self._async_chat = async_chat

    async def execute(
        self,
        tasks: list[TeamTask],
        on_event: EventCallback | None = None,
        max_concurrent: int = _DEFAULT_MAX_CONCURRENT,
    ) -> dict[str, str]:
        """Execute a task DAG and return raw outputs or stable failure sentinels."""
        self._validate_execution(tasks, max_concurrent)
        if not tasks:
            return {}

        layers = topological_layers(tasks)
        tasks_by_id = {task.id: task for task in tasks}
        results: dict[str, str] = {}
        call_runner = self._call_runner or _ThreadCallRunner(max_concurrent)
        owns_runner = self._call_runner is None
        async_call_runner = _AsyncCallRunner(max_concurrent) if self._async_chat is not None else None

        try:
            for layer in layers:
                layer_tasks = [tasks_by_id[task_id] for task_id in layer]
                layer_results = await asyncio.gather(
                    *(
                        self._run_task(
                            task,
                            results,
                            on_event,
                            call_runner,
                            async_call_runner,
                        )
                        for task in layer_tasks
                    )
                )
                for task, result in zip(layer_tasks, layer_results, strict=True):
                    results[task.id] = result
            return results
        finally:
            if owns_runner:
                call_runner.close()

    @staticmethod
    def _validate_execution(tasks: list[TeamTask], max_concurrent: int) -> None:
        """Validate every side-effect-free invariant before execution starts."""
        if max_concurrent <= 0:
            raise ValueError("max_concurrent must be positive")
        detect_cycle(tasks)
        for task in tasks:
            if task.timeout_seconds <= 0:
                raise ValueError(f"timeout_seconds must be positive for task {task.id!r}")

    async def _run_task(
        self,
        task: TeamTask,
        upstream_results: Mapping[str, str],
        on_event: EventCallback | None,
        call_runner: _ThreadCallRunner,
        async_call_runner: _AsyncCallRunner | None,
    ) -> str:
        """Run one task through the selected client with timeout and events."""
        await self._emit(
            on_event,
            TeamEvent(
                task_id=task.id,
                agent_role=task.agent_role,
                event_type="started",
                data={"name": task.name or task.id},
            ),
        )
        await self._emit(
            on_event,
            TeamEvent(
                task_id=task.id,
                agent_role=task.agent_role,
                event_type="progress",
                data={"stage": "llm"},
            ),
        )

        dependency_results = {
            dependency_id: upstream_results[dependency_id]
            for dependency_id in task.depends_on
            if dependency_id in upstream_results
        }
        prompt = _safe_format(task.prompt, dependency_results)
        system_prompt = (
            task.system_prompt if task.system_prompt is not None else _default_system_prompt(task.agent_role)
        )
        messages = [
            LLMMessage(role="system", content=system_prompt),
            LLMMessage(role="user", content=prompt),
        ]
        client = self._deep_llm if task.model_tier == "deep" else self._quick_llm

        try:
            if self._async_chat is not None:
                if async_call_runner is None:  # pragma: no cover - constructor invariant
                    raise RuntimeError("async call runner is unavailable")
                response = await async_call_runner.run(
                    lambda: self._async_chat(messages, task.temperature),
                    task.timeout_seconds,
                )
            else:
                if client is None:  # pragma: no cover - constructor invariant
                    raise RuntimeError("LLM client is unavailable")
                chat_kwargs = {"temperature": task.temperature} if task.temperature is not None else {}
                response = await call_runner.run(
                    lambda: client.chat(messages, **chat_kwargs),
                    task.timeout_seconds,
                )
            if not response.success or not response.content.strip():
                logger.warning(
                    "Team task %r returned an unsuccessful LLM response: %s",
                    task.id,
                    response.error or "empty response",
                )
                return await self._error_result(task, on_event)
            result = response.content
        except TimeoutError:
            logger.warning(
                "Team task %r timed out after %s seconds",
                task.id,
                task.timeout_seconds,
            )
            await self._emit(
                on_event,
                TeamEvent(
                    task_id=task.id,
                    agent_role=task.agent_role,
                    event_type="timeout",
                    data={"timeout_seconds": task.timeout_seconds},
                ),
            )
            return f"[TIMEOUT after {task.timeout_seconds}s]"
        except Exception:  # noqa: BLE001
            logger.exception("Team task %r LLM call failed", task.id)
            return await self._error_result(task, on_event)

        await self._emit(
            on_event,
            TeamEvent(
                task_id=task.id,
                agent_role=task.agent_role,
                event_type="completed",
                data={"result_preview": result[:200]},
            ),
        )
        return result

    async def _error_result(
        self,
        task: TeamTask,
        on_event: EventCallback | None,
    ) -> str:
        """Emit a sanitised error event and return its stable sentinel."""
        await self._emit(
            on_event,
            TeamEvent(
                task_id=task.id,
                agent_role=task.agent_role,
                event_type="error",
                data={"error": _ERROR_MESSAGE},
            ),
        )
        return _ERROR_SENTINEL

    @staticmethod
    async def _emit(on_event: EventCallback | None, event: TeamEvent) -> None:
        """Invoke a sync or async event callback without exposing its failures."""
        if on_event is None:
            return
        try:
            callback_result = on_event(event)
            if inspect.isawaitable(callback_result):
                await callback_result
        except Exception:  # noqa: BLE001
            logger.warning("Team event callback failed", exc_info=True)
