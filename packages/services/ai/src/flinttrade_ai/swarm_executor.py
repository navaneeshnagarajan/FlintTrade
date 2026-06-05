"""Lightweight multi-agent swarm task executor.

Adapts the DAG orchestration pattern from Vibe-Trading's SwarmRuntime:
topological layering (Kahn's algorithm), parallel execution of independent
tasks via ``asyncio.gather``, upstream result injection, and SSE-ready event
emission — but adapted to FlintTrade's async-first architecture and existing
``LLMClient``.

Design choices:
- Pure asyncio (no threads, no LangGraph).
- Tasks in the same topological layer execute concurrently.
- Each task receives the results of its declared dependencies injected into
  the prompt automatically.
- Events are emitted as ``SwarmEvent`` objects via an optional async callback
  suitable for Server-Sent Events (SSE).
- Cycle detection raises ``ValueError`` with a readable cycle path before
  execution starts.

Usage::

    from flinttrade_ai.swarm_executor import SwarmExecutor, SwarmTask

    tasks = [
        SwarmTask(id="macro", agent_role="analyst",
                  prompt="Analyse current Nifty macro conditions."),
        SwarmTask(id="risk", agent_role="risk_manager",
                  prompt="Given the macro view: {macro} — assess risk.",
                  depends_on=["macro"]),
    ]

    async def on_event(event: SwarmEvent) -> None:
        print(event.event_type, event.task_id)

    executor = SwarmExecutor(llm_client=my_llm_client)
    results = await executor.execute(tasks, on_event=on_event)
    print(results["risk"])
"""

from __future__ import annotations

import asyncio
import logging
from collections import defaultdict, deque
from datetime import datetime, timezone
from typing import Any, Callable, Coroutine

from pydantic import BaseModel, Field

logger = logging.getLogger("flinttrade.ai.swarm")


# ---------------------------------------------------------------------------
# Models
# ---------------------------------------------------------------------------


class SwarmTask(BaseModel):
    """A single node in the swarm task DAG.

    Attributes:
        id: Unique task identifier (e.g. ``"macro_analysis"``).
        name: Human-readable display name.
        agent_role: Role label for the agent (e.g. ``"analyst"``,
            ``"risk_manager"``). Injected into the system prompt.
        prompt: Task prompt template. Use ``{task_id}`` placeholders to
            inject upstream results automatically, e.g.
            ``"Given the macro view: {macro} — now assess portfolio risk."``.
        depends_on: Task IDs this task must wait for before executing.
        timeout_seconds: Per-task wall-clock timeout. Defaults to 120 s.
    """

    id: str
    name: str = ""
    agent_role: str
    prompt: str
    depends_on: list[str] = Field(default_factory=list)
    timeout_seconds: int = 120


class SwarmEvent(BaseModel):
    """A lifecycle event emitted during swarm execution.

    Suitable for streaming via SSE (``data: <json>\\n\\n``).

    Attributes:
        task_id: ID of the task that triggered the event.
        agent_role: Role of the executing agent.
        event_type: One of ``"started"``, ``"progress"``, ``"completed"``,
            ``"error"``, ``"timeout"``.
        data: Arbitrary payload (result snippet, error message, etc.).
        timestamp: UTC ISO-8601 timestamp.
    """

    task_id: str
    agent_role: str
    event_type: str  # "started" | "progress" | "completed" | "error" | "timeout"
    data: dict[str, Any] = Field(default_factory=dict)
    timestamp: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


# ---------------------------------------------------------------------------
# Type alias for the event callback
# ---------------------------------------------------------------------------

EventCallback = Callable[[SwarmEvent], Coroutine[Any, Any, None]] | Callable[[SwarmEvent], None]


# ---------------------------------------------------------------------------
# DAG utilities (standalone functions, easy to unit-test independently)
# ---------------------------------------------------------------------------


def build_dag(tasks: list[SwarmTask]) -> dict[str, list[str]]:
    """Build an adjacency list (task_id → list of direct successors).

    Args:
        tasks: All tasks in the swarm.

    Returns:
        Adjacency list where each key maps to its downstream task IDs.
    """
    successors: dict[str, list[str]] = {t.id: [] for t in tasks}
    for task in tasks:
        for dep in task.depends_on:
            successors.setdefault(dep, []).append(task.id)
    return successors


def detect_cycle(tasks: list[SwarmTask]) -> None:
    """DFS cycle detection on the task DAG.

    Args:
        tasks: All tasks in the swarm.

    Raises:
        ValueError: If a dependency references an unknown task ID.
        ValueError: If a cycle is detected; the message includes the cycle path.
    """
    all_ids = {t.id for t in tasks}

    # Validate that all declared dependencies exist
    for task in tasks:
        for dep in task.depends_on:
            if dep not in all_ids:
                raise ValueError(
                    f"Task '{task.id}' depends on unknown task '{dep}'"
                )

    graph: dict[str, list[str]] = {t.id: list(t.depends_on) for t in tasks}

    WHITE, GRAY, BLACK = 0, 1, 2
    colour: dict[str, int] = {tid: WHITE for tid in all_ids}
    path: list[str] = []

    def _dfs(node: str) -> None:
        colour[node] = GRAY
        path.append(node)
        for neighbour in graph.get(node, []):
            if colour[neighbour] == GRAY:
                start = path.index(neighbour)
                cycle = " -> ".join(path[start:] + [neighbour])
                raise ValueError(f"Cycle detected in swarm task DAG: {cycle}")
            if colour[neighbour] == WHITE:
                _dfs(neighbour)
        path.pop()
        colour[node] = BLACK

    for tid in all_ids:
        if colour[tid] == WHITE:
            _dfs(tid)


def topological_layers(tasks: list[SwarmTask]) -> list[list[str]]:
    """Kahn's algorithm — group tasks into parallel execution layers.

    Tasks within the same layer have no mutual dependencies and can run
    concurrently.  Layers are ordered so all dependencies of layer N are
    resolved in layers 0..N-1.

    Args:
        tasks: All tasks in the swarm (must be a valid acyclic DAG).

    Returns:
        Ordered list of layers; each layer is a list of task IDs.

    Raises:
        ValueError: If the DAG contains a cycle (cannot complete sort).
    """
    in_degree: dict[str, int] = {t.id: len(t.depends_on) for t in tasks}
    dependents: dict[str, list[str]] = defaultdict(list)

    for task in tasks:
        for dep in task.depends_on:
            dependents[dep].append(task.id)

    queue: deque[str] = deque(tid for tid, deg in in_degree.items() if deg == 0)
    layers: list[list[str]] = []
    processed = 0

    while queue:
        layer = list(queue)
        queue.clear()
        layers.append(layer)
        processed += len(layer)
        for tid in layer:
            for downstream in dependents[tid]:
                in_degree[downstream] -= 1
                if in_degree[downstream] == 0:
                    queue.append(downstream)

    if processed != len(tasks):
        raise ValueError(
            f"Swarm DAG contains a cycle: only {processed}/{len(tasks)} tasks could be ordered"
        )

    return layers


# ---------------------------------------------------------------------------
# SwarmExecutor
# ---------------------------------------------------------------------------


class SwarmExecutor:
    """Async multi-agent task executor with DAG-aware scheduling.

    Executes a list of ``SwarmTask`` objects in dependency order. Independent
    tasks in the same topological layer run concurrently via ``asyncio.gather``.
    Upstream results are automatically injected into downstream task prompts
    using ``str.format_map``.

    Attributes:
        llm_client: FlintTrade ``LLMClient`` (or any object with a
            ``complete(system, user) -> str`` or async equivalent).
    """

    def __init__(self, llm_client: Any) -> None:
        """Initialise the executor.

        Args:
            llm_client: FlintTrade LLMClient instance. Must expose either
                ``async_complete(system_prompt, user_prompt) -> str`` or
                ``complete(system_prompt, user_prompt) -> str``.
        """
        self._llm = llm_client

    # ------------------------------------------------------------------
    # Public entry point
    # ------------------------------------------------------------------

    async def execute(
        self,
        tasks: list[SwarmTask],
        on_event: EventCallback | None = None,
    ) -> dict[str, str]:
        """Execute the swarm, respecting the dependency DAG.

        Args:
            tasks: Full list of tasks to execute.
            on_event: Optional async or sync callback invoked for every
                ``SwarmEvent``. Suitable for SSE streaming to the frontend.

        Returns:
            Mapping of ``task_id -> result_text`` for every completed task.

        Raises:
            ValueError: If the DAG contains a cycle or references an unknown
                task ID.
        """
        if not tasks:
            return {}

        detect_cycle(tasks)
        layers = topological_layers(tasks)
        task_map: dict[str, SwarmTask] = {t.id: t for t in tasks}
        results: dict[str, str] = {}

        for layer in layers:
            layer_tasks = [task_map[tid] for tid in layer]
            layer_results = await asyncio.gather(
                *[
                    self._run_task(task, results, on_event)
                    for task in layer_tasks
                ],
                return_exceptions=True,
            )
            for task, outcome in zip(layer_tasks, layer_results):
                if isinstance(outcome, BaseException):
                    logger.error(
                        "Task '%s' raised an unhandled exception: %s",
                        task.id, outcome, exc_info=outcome,
                    )
                    results[task.id] = f"[ERROR] {outcome}"
                else:
                    results[task.id] = outcome  # type: ignore[assignment]

        return results

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    async def _run_task(
        self,
        task: SwarmTask,
        upstream_results: dict[str, str],
        on_event: EventCallback | None,
    ) -> str:
        """Execute a single task with timeout and event emission.

        Injects upstream results into the task prompt via ``str.format_map``.
        Unknown placeholders (keys not in ``upstream_results``) are left
        unchanged so the LLM sees them literally.

        Args:
            task: The task to execute.
            upstream_results: Results accumulated from already-completed tasks.
            on_event: Optional event callback.

        Returns:
            The LLM-generated result text.
        """
        await self._emit(
            on_event,
            SwarmEvent(
                task_id=task.id,
                agent_role=task.agent_role,
                event_type="started",
                data={"name": task.name or task.id},
            ),
        )

        # Inject upstream dependency results into the prompt template
        prompt = _safe_format(task.prompt, upstream_results)

        system_prompt = (
            f"You are a specialist trading agent acting as a {task.agent_role}. "
            "Provide a concise, actionable analysis. Focus on Indian markets "
            "(NSE/BSE/MCX). Return only your analysis — no preamble."
        )

        try:
            result = await asyncio.wait_for(
                self._call_llm(system_prompt, prompt),
                timeout=task.timeout_seconds,
            )
        except asyncio.TimeoutError:
            logger.warning(
                "Task '%s' timed out after %d s", task.id, task.timeout_seconds
            )
            await self._emit(
                on_event,
                SwarmEvent(
                    task_id=task.id,
                    agent_role=task.agent_role,
                    event_type="timeout",
                    data={"timeout_seconds": task.timeout_seconds},
                ),
            )
            return f"[TIMEOUT after {task.timeout_seconds}s]"
        except Exception as exc:
            logger.error("Task '%s' LLM call failed: %s", task.id, exc, exc_info=True)
            await self._emit(
                on_event,
                SwarmEvent(
                    task_id=task.id,
                    agent_role=task.agent_role,
                    event_type="error",
                    data={"error": str(exc)},
                ),
            )
            return f"[ERROR] {exc}"

        await self._emit(
            on_event,
            SwarmEvent(
                task_id=task.id,
                agent_role=task.agent_role,
                event_type="completed",
                data={"result_preview": result[:200]},
            ),
        )
        return result

    async def _call_llm(self, system_prompt: str, user_prompt: str) -> str:
        """Call the LLM client, supporting both async and sync interfaces.

        Args:
            system_prompt: System role prompt.
            user_prompt: User message / task prompt.

        Returns:
            LLM-generated response text.
        """
        if hasattr(self._llm, "async_complete"):
            return await self._llm.async_complete(system_prompt, user_prompt)
        # Sync fallback — wrap in executor to avoid blocking the event loop
        loop = asyncio.get_running_loop()
        return await loop.run_in_executor(
            None, self._llm.complete, system_prompt, user_prompt
        )

    @staticmethod
    async def _emit(
        callback: EventCallback | None,
        event: SwarmEvent,
    ) -> None:
        """Fire the event callback if one is registered.

        Handles both async and sync callbacks transparently.

        Args:
            callback: Optional callback function.
            event: Event to emit.
        """
        if callback is None:
            return
        try:
            result = callback(event)
            if asyncio.iscoroutine(result):
                await result
        except Exception:
            logger.warning("SwarmEvent callback raised an exception", exc_info=True)

    # ------------------------------------------------------------------
    # DAG inspection helper (useful for debugging / UI preview)
    # ------------------------------------------------------------------

    def _build_dag(self, tasks: list[SwarmTask]) -> dict[str, list[str]]:
        """Return the dependency graph as an adjacency list.

        Thin wrapper around the module-level :func:`build_dag`.

        Args:
            tasks: Tasks to build the graph for.

        Returns:
            Dict mapping each task ID to its list of direct successor IDs.
        """
        return build_dag(tasks)


# ---------------------------------------------------------------------------
# Private utility
# ---------------------------------------------------------------------------


def _safe_format(template: str, values: dict[str, str]) -> str:
    """Format a template string, leaving unknown placeholders intact.

    Args:
        template: String with optional ``{key}`` placeholders.
        values: Available substitution values.

    Returns:
        Formatted string with matched placeholders replaced; unmatched
        placeholders are left as-is.
    """

    class _SafeDict(dict):  # type: ignore[type-arg]
        def __missing__(self, key: str) -> str:
            return f"{{{key}}}"

    try:
        return template.format_map(_SafeDict(values))
    except (ValueError, KeyError):
        return template
