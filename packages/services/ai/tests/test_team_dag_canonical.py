"""Focused contract tests for the canonical private team DAG helper."""

from __future__ import annotations

import asyncio
import threading
import time
from collections.abc import Callable

import pytest
from pydantic import ValidationError

from flinttrade_ai._team_dag import (
    TeamDagRunner,
    TeamEvent,
    TeamTask,
    _ThreadCallRunner,
    _safe_format,
    build_dag,
    topological_layers,
)
from flinttrade_ai.llm_client import LLMMessage, LLMResponse


def _task(
    task_id: str,
    *,
    prompt: str | None = None,
    depends_on: list[str] | None = None,
    timeout_seconds: int = 2,
    system_prompt: str | None = None,
    model_tier: str = "quick",
    temperature: float | None = None,
) -> TeamTask:
    """Build a compact task for runner tests."""
    return TeamTask(
        id=task_id,
        name=task_id,
        agent_role="analyst",
        prompt=prompt or task_id,
        depends_on=depends_on or [],
        timeout_seconds=timeout_seconds,
        system_prompt=system_prompt,
        model_tier=model_tier,
        temperature=temperature,
    )


class _RecordingLLM:
    """Thread-safe test double exposing the real synchronous chat contract."""

    def __init__(
        self,
        responder: Callable[[list[LLMMessage]], LLMResponse] | None = None,
    ) -> None:
        self._responder = responder or (lambda messages: LLMResponse(content=messages[-1].content))
        self._lock = threading.Lock()
        self.calls: list[list[LLMMessage]] = []
        self.thread_ids: list[int] = []

    def chat(self, messages: list[LLMMessage]) -> LLMResponse:
        """Record one chat call and return its configured response."""
        with self._lock:
            self.calls.append(messages)
            self.thread_ids.append(threading.get_ident())
        return self._responder(messages)


def test_models_restrict_tiers_and_lifecycle_values() -> None:
    """Pydantic models reject unsupported model tiers and event names."""
    task = _task("valid", model_tier="deep")
    event = TeamEvent(task_id="valid", agent_role="analyst", event_type="started")

    assert task.model_tier == "deep"
    assert event.event_type == "started"
    with pytest.raises(ValidationError):
        _task("invalid", model_tier="ultra")
    with pytest.raises(ValidationError):
        TeamEvent(task_id="valid", agent_role="analyst", event_type="finished")


def test_dag_utilities_preserve_deterministic_topological_layers() -> None:
    """DAG construction and layering retain task declaration order."""
    tasks = [
        _task("root"),
        _task("left", depends_on=["root"]),
        _task("right", depends_on=["root"]),
        _task("merge", depends_on=["left", "right"]),
    ]

    assert build_dag(tasks) == {
        "root": ["left", "right"],
        "left": ["merge"],
        "right": ["merge"],
        "merge": [],
    }
    assert topological_layers(tasks) == [["root"], ["left", "right"], ["merge"]]


def test_safe_format_replaces_known_values_and_preserves_missing_placeholders() -> None:
    """Safe formatting never drops a placeholder for which no value exists."""
    assert _safe_format("known={known}; missing={missing}", {"known": "value"}) == ("known=value; missing={missing}")
    assert _safe_format("malformed={known", {"known": "value"}) == "malformed={known"


@pytest.mark.asyncio
async def test_runner_uses_llm_messages_and_returns_raw_response_text() -> None:
    """The runner calls chat off-loop and returns LLMResponse.content unchanged."""
    main_thread = threading.get_ident()
    client = _RecordingLLM(lambda messages: LLMResponse(content="  raw response\n"))
    runner = TeamDagRunner(quick_llm=client)

    results = await runner.execute([_task("analysis", prompt="Review NIFTY", system_prompt="Custom system")])

    assert results == {"analysis": "  raw response\n"}
    assert client.thread_ids[0] != main_thread
    assert client.calls == [
        [
            LLMMessage(role="system", content="Custom system"),
            LLMMessage(role="user", content="Review NIFTY"),
        ]
    ]


@pytest.mark.asyncio
async def test_runner_injects_only_declared_dependency_results() -> None:
    """Completed but undeclared task results cannot leak into a prompt."""
    responses = {
        "declared": "DECLARED RESULT",
        "sibling": "SIBLING RESULT",
        "declared={declared}; sibling={sibling}; missing={missing}": "child",
        "declared=DECLARED RESULT; sibling={sibling}; missing={missing}": "child",
    }

    def respond(messages: list[LLMMessage]) -> LLMResponse:
        return LLMResponse(content=responses[messages[-1].content])

    client = _RecordingLLM(respond)
    tasks = [
        _task("declared"),
        _task("sibling"),
        _task(
            "child",
            depends_on=["declared"],
            prompt="declared={declared}; sibling={sibling}; missing={missing}",
        ),
    ]

    results = await TeamDagRunner(client).execute(tasks)

    child_prompt = next(call[-1].content for call in client.calls if call[-1].content.startswith("declared="))
    assert child_prompt == "declared=DECLARED RESULT; sibling={sibling}; missing={missing}"
    assert results["child"] == "child"


@pytest.mark.asyncio
async def test_runner_selects_quick_and_deep_clients_by_task_tier() -> None:
    """Deep tasks use the deep client while quick tasks use the quick client."""
    quick = _RecordingLLM(lambda messages: LLMResponse(content="quick result"))
    deep = _RecordingLLM(lambda messages: LLMResponse(content="deep result"))
    runner = TeamDagRunner(quick_llm=quick, deep_llm=deep)

    results = await runner.execute([_task("quick"), _task("deep", model_tier="deep")])

    assert results == {"quick": "quick result", "deep": "deep result"}
    assert [call[-1].content for call in quick.calls] == ["quick"]
    assert [call[-1].content for call in deep.calls] == ["deep"]


@pytest.mark.asyncio
async def test_runner_forwards_optional_agent_temperature() -> None:
    """Per-agent temperature remains part of the canonical role contract."""

    class TemperatureLLM(_RecordingLLM):
        def __init__(self) -> None:
            super().__init__()
            self.temperatures: list[float | None] = []

        def chat(self, messages: list[LLMMessage], temperature: float | None = None) -> LLMResponse:
            self.temperatures.append(temperature)
            return super().chat(messages)

    temperature_client = TemperatureLLM()
    await TeamDagRunner(temperature_client).execute([_task("analyst", temperature=0.2)])

    assert temperature_client.temperatures == [0.2]


@pytest.mark.asyncio
async def test_runner_emits_timeout_without_exception_details() -> None:
    """A task timeout produces typed lifecycle events and a stable sentinel."""
    release = threading.Event()

    def block(_messages: list[LLMMessage]) -> LLMResponse:
        release.wait(timeout=2)
        return LLMResponse(content="too late")

    client = _RecordingLLM(block)
    events: list[TeamEvent] = []
    try:
        results = await TeamDagRunner(client).execute(
            [_task("slow", timeout_seconds=1)],
            on_event=events.append,
        )
    finally:
        release.set()

    assert results == {"slow": "[TIMEOUT after 1s]"}
    assert [event.event_type for event in events] == ["started", "progress", "timeout"]
    assert events[-1].data == {"timeout_seconds": 1}


@pytest.mark.asyncio
async def test_timed_out_worker_keeps_concurrency_slot_until_chat_returns() -> None:
    """A timed-out sync chat still owns its slot until the worker exits."""
    release_first = threading.Event()
    first_started = threading.Event()
    active = 0
    peak_active = 0
    lock = threading.Lock()

    def respond(messages: list[LLMMessage]) -> LLMResponse:
        nonlocal active, peak_active
        with lock:
            active += 1
            peak_active = max(peak_active, active)
        try:
            if messages[-1].content == "first":
                first_started.set()
                release_first.wait(timeout=4)
            return LLMResponse(content=messages[-1].content)
        finally:
            with lock:
                active -= 1

    client = _RecordingLLM(respond)
    execution = asyncio.create_task(
        TeamDagRunner(client).execute(
            [_task("first", timeout_seconds=1), _task("second", timeout_seconds=2)],
            max_concurrent=1,
        )
    )
    assert await asyncio.to_thread(first_started.wait, 1)

    await asyncio.sleep(1.2)
    assert len(client.calls) == 1
    assert peak_active == 1
    release_first.set()
    results = await execution
    assert results == {"first": "[TIMEOUT after 1s]", "second": "second"}
    assert peak_active == 1


@pytest.mark.asyncio
async def test_repeated_timeouts_have_a_process_wide_worker_bound() -> None:
    """Independent timed-out analyses cannot grow live worker threads without bound."""
    release = threading.Event()
    lock = threading.Lock()
    active = 0
    peak_active = 0
    runners = [_ThreadCallRunner(1) for _ in range(10)]

    def blocking_call() -> str:
        nonlocal active, peak_active
        with lock:
            active += 1
            peak_active = max(peak_active, active)
        try:
            release.wait(timeout=3)
            return "late"
        finally:
            with lock:
                active -= 1

    try:
        outcomes = await asyncio.gather(
            *(runner.run(blocking_call, 0.2) for runner in runners),
            return_exceptions=True,
        )
        assert all(isinstance(outcome, TimeoutError) for outcome in outcomes)
        assert peak_active <= 8
    finally:
        release.set()
        for runner in runners:
            runner.close()

@pytest.mark.asyncio
async def test_runner_sanitises_llm_failures_in_results_and_events() -> None:
    """Raw exception details stay in logs and never enter returned/event data."""
    secret = "provider failed at /Users/private/.env with token"

    def fail(_messages: list[LLMMessage]) -> LLMResponse:
        raise RuntimeError(secret)

    events: list[TeamEvent] = []
    results = await TeamDagRunner(_RecordingLLM(fail)).execute(
        [_task("failed")],
        on_event=events.append,
    )

    assert results == {"failed": "[ERROR] Task failed"}
    assert [event.event_type for event in events] == ["started", "progress", "error"]
    assert events[-1].data == {"error": "Task failed"}
    assert secret not in repr(events)
    assert secret not in repr(results)


@pytest.mark.parametrize(
    ("tasks", "message"),
    [
        ([_task("   ")], "blank"),
        ([_task("duplicate"), _task("duplicate")], "duplicate"),
        ([_task("unknown", depends_on=["absent"])], "unknown"),
        ([_task("a", depends_on=["b"]), _task("b", depends_on=["a"])], "Cycle"),
        ([_task("timeout", timeout_seconds=0)], "timeout"),
    ],
)
@pytest.mark.asyncio
async def test_runner_validates_entire_dag_before_events_or_llm_calls(
    tasks: list[TeamTask],
    message: str,
) -> None:
    """Every structural validation failure is side-effect free."""
    client = _RecordingLLM()
    events: list[TeamEvent] = []

    with pytest.raises(ValueError, match=message):
        await TeamDagRunner(client).execute(tasks, on_event=events.append)

    assert client.calls == []
    assert events == []


@pytest.mark.asyncio
async def test_callback_failures_are_swallowed_for_every_event() -> None:
    """A broken event sink cannot abort task execution or later emissions."""
    callback_calls = 0

    async def broken_callback(_event: TeamEvent) -> None:
        nonlocal callback_calls
        callback_calls += 1
        raise RuntimeError("event transport failed")

    results = await TeamDagRunner(_RecordingLLM()).execute(
        [_task("task")],
        on_event=broken_callback,
    )

    assert results == {"task": "task"}
    assert callback_calls == 3


@pytest.mark.asyncio
async def test_same_layer_concurrency_is_bounded() -> None:
    """The runner never exceeds the configured number of simultaneous calls."""
    lock = threading.Lock()
    active = 0
    maximum_active = 0

    def track(messages: list[LLMMessage]) -> LLMResponse:
        nonlocal active, maximum_active
        with lock:
            active += 1
            maximum_active = max(maximum_active, active)
        time.sleep(0.04)
        with lock:
            active -= 1
        return LLMResponse(content=messages[-1].content)

    tasks = [_task(f"task-{index}") for index in range(5)]

    await TeamDagRunner(_RecordingLLM(track)).execute(tasks, max_concurrent=2)

    assert maximum_active == 2


@pytest.mark.asyncio
async def test_topological_layer_is_a_completion_barrier() -> None:
    """A downstream task waits for every peer in the preceding layer."""
    slow_started = threading.Event()
    fast_finished = threading.Event()
    child_started = threading.Event()
    release_slow = threading.Event()

    def coordinate(messages: list[LLMMessage]) -> LLMResponse:
        prompt = messages[-1].content
        if prompt == "slow":
            slow_started.set()
            release_slow.wait(timeout=2)
        elif prompt == "fast":
            fast_finished.set()
        elif prompt.startswith("child"):
            child_started.set()
        return LLMResponse(content=prompt.upper())

    tasks = [
        _task("slow"),
        _task("fast"),
        _task("child", prompt="child {fast}", depends_on=["fast"]),
    ]
    running = asyncio.create_task(TeamDagRunner(_RecordingLLM(coordinate)).execute(tasks, max_concurrent=2))

    for _ in range(100):
        if slow_started.is_set() and fast_finished.is_set():
            break
        await asyncio.sleep(0.005)
    assert slow_started.is_set()
    assert fast_finished.is_set()
    assert not child_started.is_set()

    release_slow.set()
    results = await running

    assert child_started.is_set()
    assert results["child"] == "CHILD FAST"
