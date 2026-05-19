"""Tests for packages/ai/src/swarm_executor.py."""

from __future__ import annotations

import asyncio
from unittest.mock import MagicMock

import pytest

from packages.ai.src.swarm_executor import (
    SwarmEvent,
    SwarmExecutor,
    SwarmTask,
    _safe_format,
    build_dag,
    detect_cycle,
    topological_layers,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


def _make_task(
    task_id: str,
    agent_role: str = "analyst",
    prompt: str = "Analyse the market.",
    depends_on: list[str] | None = None,
    timeout_seconds: int = 10,
) -> SwarmTask:
    return SwarmTask(
        id=task_id,
        name=task_id,
        agent_role=agent_role,
        prompt=prompt,
        depends_on=depends_on or [],
        timeout_seconds=timeout_seconds,
    )


class _FakeLLMClient:
    """Synchronous fake LLM client for testing."""

    def __init__(self, response: str = "mock result") -> None:
        self._response = response
        self.calls: list[tuple[str, str]] = []

    def complete(self, system_prompt: str, user_prompt: str) -> str:
        self.calls.append((system_prompt, user_prompt))
        return self._response


class _AsyncFakeLLMClient:
    """Asynchronous fake LLM client for testing."""

    def __init__(self, response: str = "async result") -> None:
        self._response = response
        self.calls: list[tuple[str, str]] = []

    async def async_complete(self, system_prompt: str, user_prompt: str) -> str:
        self.calls.append((system_prompt, user_prompt))
        return self._response


# ---------------------------------------------------------------------------
# _safe_format
# ---------------------------------------------------------------------------


class TestSafeFormat:
    def test_replaces_known_keys(self) -> None:
        result = _safe_format("Hello {name}!", {"name": "world"})
        assert result == "Hello world!"

    def test_leaves_unknown_keys_intact(self) -> None:
        result = _safe_format("Given {upstream}: analyse {unknown}.", {"upstream": "data"})
        assert result == "Given data: analyse {unknown}."

    def test_empty_values(self) -> None:
        result = _safe_format("No placeholders here.", {})
        assert result == "No placeholders here."

    def test_multiple_replacements(self) -> None:
        result = _safe_format("{a} + {b} = {c}", {"a": "1", "b": "2", "c": "3"})
        assert result == "1 + 2 = 3"


# ---------------------------------------------------------------------------
# build_dag
# ---------------------------------------------------------------------------


class TestBuildDag:
    def test_linear_chain(self) -> None:
        tasks = [
            _make_task("a"),
            _make_task("b", depends_on=["a"]),
            _make_task("c", depends_on=["b"]),
        ]
        dag = build_dag(tasks)
        assert dag["a"] == ["b"]
        assert dag["b"] == ["c"]
        assert dag["c"] == []

    def test_independent_tasks(self) -> None:
        tasks = [_make_task("x"), _make_task("y"), _make_task("z")]
        dag = build_dag(tasks)
        assert dag["x"] == []
        assert dag["y"] == []

    def test_fan_out(self) -> None:
        tasks = [
            _make_task("root"),
            _make_task("child1", depends_on=["root"]),
            _make_task("child2", depends_on=["root"]),
        ]
        dag = build_dag(tasks)
        assert set(dag["root"]) == {"child1", "child2"}


# ---------------------------------------------------------------------------
# detect_cycle
# ---------------------------------------------------------------------------


class TestDetectCycle:
    def test_acyclic_dag_no_exception(self) -> None:
        tasks = [
            _make_task("a"),
            _make_task("b", depends_on=["a"]),
        ]
        detect_cycle(tasks)  # should not raise

    def test_direct_cycle_raises(self) -> None:
        tasks = [
            _make_task("a", depends_on=["b"]),
            _make_task("b", depends_on=["a"]),
        ]
        with pytest.raises(ValueError, match="Cycle detected"):
            detect_cycle(tasks)

    def test_self_loop_raises(self) -> None:
        tasks = [_make_task("a", depends_on=["a"])]
        with pytest.raises(ValueError):
            detect_cycle(tasks)

    def test_three_node_cycle_raises(self) -> None:
        tasks = [
            _make_task("a", depends_on=["c"]),
            _make_task("b", depends_on=["a"]),
            _make_task("c", depends_on=["b"]),
        ]
        with pytest.raises(ValueError, match="Cycle detected"):
            detect_cycle(tasks)

    def test_unknown_dependency_raises(self) -> None:
        tasks = [_make_task("a", depends_on=["nonexistent"])]
        with pytest.raises(ValueError, match="unknown task"):
            detect_cycle(tasks)


# ---------------------------------------------------------------------------
# topological_layers
# ---------------------------------------------------------------------------


class TestTopologicalLayers:
    def test_single_task(self) -> None:
        layers = topological_layers([_make_task("a")])
        assert layers == [["a"]]

    def test_linear_chain(self) -> None:
        tasks = [
            _make_task("a"),
            _make_task("b", depends_on=["a"]),
            _make_task("c", depends_on=["b"]),
        ]
        layers = topological_layers(tasks)
        assert len(layers) == 3
        assert "a" in layers[0]
        assert "b" in layers[1]
        assert "c" in layers[2]

    def test_parallel_tasks_in_same_layer(self) -> None:
        tasks = [
            _make_task("root"),
            _make_task("p1", depends_on=["root"]),
            _make_task("p2", depends_on=["root"]),
            _make_task("p3", depends_on=["root"]),
        ]
        layers = topological_layers(tasks)
        assert layers[0] == ["root"]
        assert set(layers[1]) == {"p1", "p2", "p3"}

    def test_diamond_dag(self) -> None:
        # root → left, right → merge
        tasks = [
            _make_task("root"),
            _make_task("left", depends_on=["root"]),
            _make_task("right", depends_on=["root"]),
            _make_task("merge", depends_on=["left", "right"]),
        ]
        layers = topological_layers(tasks)
        assert "root" in layers[0]
        assert set(layers[1]) == {"left", "right"}
        assert "merge" in layers[2]

    def test_cyclic_raises(self) -> None:
        tasks = [
            _make_task("a", depends_on=["b"]),
            _make_task("b", depends_on=["a"]),
        ]
        with pytest.raises(ValueError, match="cycle"):
            topological_layers(tasks)


# ---------------------------------------------------------------------------
# SwarmExecutor — sync client
# ---------------------------------------------------------------------------


class TestSwarmExecutorSyncClient:
    @pytest.mark.asyncio
    async def test_single_task(self) -> None:
        client = _FakeLLMClient("result_a")
        executor = SwarmExecutor(llm_client=client)
        tasks = [_make_task("a", prompt="Analyse Nifty.")]
        results = await executor.execute(tasks)
        assert results["a"] == "result_a"

    @pytest.mark.asyncio
    async def test_linear_dependency_injects_upstream_result(self) -> None:
        client = _FakeLLMClient("downstream_result")
        executor = SwarmExecutor(llm_client=client)
        tasks = [
            _make_task("macro", prompt="Analyse macro."),
            _make_task("risk", depends_on=["macro"],
                       prompt="Given macro: {macro} — assess risk."),
        ]
        results = await executor.execute(tasks)
        assert "macro" in results
        assert "risk" in results
        # The risk task's prompt should have had {macro} replaced
        risk_call = next(
            (call for call in client.calls if "Given macro" in call[1]), None
        )
        assert risk_call is not None, "Risk prompt was not injected with macro result"

    @pytest.mark.asyncio
    async def test_parallel_tasks_all_executed(self) -> None:
        client = _FakeLLMClient("ok")
        executor = SwarmExecutor(llm_client=client)
        tasks = [
            _make_task("t1"),
            _make_task("t2"),
            _make_task("t3"),
        ]
        results = await executor.execute(tasks)
        assert set(results.keys()) == {"t1", "t2", "t3"}
        assert all(v == "ok" for v in results.values())

    @pytest.mark.asyncio
    async def test_empty_tasks_returns_empty(self) -> None:
        client = _FakeLLMClient()
        executor = SwarmExecutor(llm_client=client)
        results = await executor.execute([])
        assert results == {}

    @pytest.mark.asyncio
    async def test_cycle_raises_before_execution(self) -> None:
        client = _FakeLLMClient()
        executor = SwarmExecutor(llm_client=client)
        tasks = [
            _make_task("a", depends_on=["b"]),
            _make_task("b", depends_on=["a"]),
        ]
        with pytest.raises(ValueError, match="Cycle detected"):
            await executor.execute(tasks)
        assert client.calls == []  # LLM never called

    @pytest.mark.asyncio
    async def test_events_emitted(self) -> None:
        client = _FakeLLMClient("ok")
        executor = SwarmExecutor(llm_client=client)
        events: list[SwarmEvent] = []

        async def capture(event: SwarmEvent) -> None:
            events.append(event)

        tasks = [_make_task("a"), _make_task("b", depends_on=["a"])]
        await executor.execute(tasks, on_event=capture)

        event_types = [e.event_type for e in events]
        assert "started" in event_types
        assert "completed" in event_types

    @pytest.mark.asyncio
    async def test_sync_event_callback_supported(self) -> None:
        client = _FakeLLMClient("ok")
        executor = SwarmExecutor(llm_client=client)
        collected: list[str] = []

        def sync_callback(event: SwarmEvent) -> None:
            collected.append(event.event_type)

        await executor.execute([_make_task("x")], on_event=sync_callback)
        assert "started" in collected
        assert "completed" in collected


# ---------------------------------------------------------------------------
# SwarmExecutor — async client
# ---------------------------------------------------------------------------


class TestSwarmExecutorAsyncClient:
    @pytest.mark.asyncio
    async def test_async_llm_client_used(self) -> None:
        client = _AsyncFakeLLMClient("async_ok")
        executor = SwarmExecutor(llm_client=client)
        results = await executor.execute([_make_task("z")])
        assert results["z"] == "async_ok"
        assert len(client.calls) == 1


# ---------------------------------------------------------------------------
# Timeout handling
# ---------------------------------------------------------------------------


class TestSwarmExecutorTimeout:
    @pytest.mark.asyncio
    async def test_timeout_returns_sentinel_string(self) -> None:
        async def slow_complete(system_prompt: str, user_prompt: str) -> str:
            await asyncio.sleep(999)
            return "never"

        client = MagicMock()
        client.async_complete = slow_complete

        executor = SwarmExecutor(llm_client=client)
        tasks = [_make_task("slow", timeout_seconds=1)]
        results = await executor.execute(tasks)
        assert "[TIMEOUT" in results["slow"]

    @pytest.mark.asyncio
    async def test_timeout_event_emitted(self) -> None:
        async def slow_complete(system_prompt: str, user_prompt: str) -> str:
            await asyncio.sleep(999)
            return "never"

        client = MagicMock()
        client.async_complete = slow_complete

        executor = SwarmExecutor(llm_client=client)
        events: list[SwarmEvent] = []

        async def capture(event: SwarmEvent) -> None:
            events.append(event)

        await executor.execute([_make_task("slow", timeout_seconds=1)], on_event=capture)
        assert any(e.event_type == "timeout" for e in events)


# ---------------------------------------------------------------------------
# _build_dag method (public on executor for UI use)
# ---------------------------------------------------------------------------


class TestBuildDagMethod:
    def test_returns_adjacency_list(self) -> None:
        executor = SwarmExecutor(llm_client=_FakeLLMClient())
        tasks = [
            _make_task("a"),
            _make_task("b", depends_on=["a"]),
        ]
        dag = executor._build_dag(tasks)
        assert dag["a"] == ["b"]
        assert dag["b"] == []
