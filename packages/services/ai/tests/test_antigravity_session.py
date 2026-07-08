"""Tests for the Antigravity (``agy``) CLI streaming session.

Every test drives an in-process fake ``agy`` (a subprocess stand-in that feeds
scripted stdout/stderr lines then exits) through the injectable ``spawn`` seam —
nothing is installed or shelled out, so ``agy`` need not be present. Coverage:

* a streamed run: stdout lines → ``output`` events + a terminal ``done`` event
  carrying the exit code,
* a non-zero exit surfaced as an ``error`` event and recorded on ``done``,
* over-limit-line survival (the reader discards a >64 KiB line and keeps going),
* fail-closed :class:`AgentBackendUnavailable` on a missing binary (both the
  ``ensure_started`` PATH probe and a spawn-time ``FileNotFoundError``),
* stderr surfaced as distinct diagnostic ``output`` events,
* the run-without-callback and async-context-manager paths.
"""

from __future__ import annotations

import asyncio
from collections.abc import Sequence

import pytest

from flinttrade_ai.agent_backends import (
    AgentBackendUnavailable,
    AgentEvent,
    AgentEventKind,
    AgentSession,
)
from flinttrade_ai.agent_backends.antigravity_session import AntigravitySession

pytestmark = pytest.mark.unit


# ======================================================================
# Fakes: a scripted one-shot ``agy`` over asyncio StreamReaders
# ======================================================================


def _reader_with(lines: Sequence[str], *, limit: int | None = None, newline: str = "\n") -> asyncio.StreamReader:
    """Build a StreamReader pre-fed with ``lines`` then EOF.

    ``limit=None`` uses asyncio's default 64 KiB cap so an over-long line
    exercises the reader's over-limit survival path exactly as production would.
    """
    reader = asyncio.StreamReader() if limit is None else asyncio.StreamReader(limit=limit)
    for line in lines:
        reader.feed_data(line.encode("utf-8") + newline.encode("utf-8"))
    reader.feed_eof()
    return reader


class _FakeProcess:
    """A minimal asyncio.subprocess.Process stand-in for a one-shot ``agy``."""

    def __init__(self, stdout: asyncio.StreamReader, stderr: asyncio.StreamReader, exit_code: int) -> None:
        self.stdout = stdout
        self.stderr = stderr
        self._exit_code = exit_code
        self.returncode: int | None = None
        self.terminated = False
        self.killed = False

    def terminate(self) -> None:
        self.terminated = True
        if self.returncode is None:
            self.returncode = self._exit_code
        self.stdout.feed_eof()
        self.stderr.feed_eof()

    def kill(self) -> None:
        self.killed = True
        if self.returncode is None:
            self.returncode = -9
        self.stdout.feed_eof()
        self.stderr.feed_eof()

    async def wait(self) -> int:
        # The scripted output was fed up front, so the child is "done": report
        # its exit code (mirrors a real process that has closed its pipes).
        if self.returncode is None:
            self.returncode = self._exit_code
        return self.returncode


class _FakeAgy:
    """Scripts one ``agy -p`` invocation: stdout/stderr lines then an exit code."""

    def __init__(
        self,
        *,
        stdout: Sequence[str] = (),
        stderr: Sequence[str] = (),
        exit_code: int = 0,
        stdout_limit: int | None = None,
    ) -> None:
        self._stdout = list(stdout)
        self._stderr = list(stderr)
        self._exit_code = exit_code
        self._stdout_limit = stdout_limit
        self.calls: list[tuple[Sequence[str], dict[str, str], str | None]] = []
        self.proc: _FakeProcess | None = None

    async def spawn(self, cmd: Sequence[str], env: dict[str, str], cwd: str | None) -> _FakeProcess:
        self.calls.append((list(cmd), dict(env), cwd))
        self.proc = _FakeProcess(
            _reader_with(self._stdout, limit=self._stdout_limit),
            _reader_with(self._stderr),
            self._exit_code,
        )
        return self.proc


def _collect(sink: list[AgentEvent]):
    async def _on_event(ev: AgentEvent) -> None:
        sink.append(ev)

    return _on_event


def _session(fake: _FakeAgy, **kwargs) -> AntigravitySession:
    # A custom spawn is injected, so ensure_started trusts it (no real PATH probe).
    return AntigravitySession(spawn=fake.spawn, **kwargs)


# ======================================================================
# Streamed run: stdout → output events + done with exit code
# ======================================================================


async def test_run_turn_streams_stdout_as_output_and_done() -> None:
    fake = _FakeAgy(stdout=["Hello from agy", "second line"], exit_code=0)
    session = _session(fake, cwd="/tmp/proj", model="Gemini 3.1 Pro (High)")

    events: list[AgentEvent] = []
    await session.ensure_started()
    done = await session.run_turn("summarise the repo", on_event=_collect(events))
    await session.close()

    # Argv carried the one-shot flag, the prompt, and the model; cwd was passed.
    cmd, _env, cwd = fake.calls[0]
    assert cmd[0] == "agy"
    assert "-p" in cmd
    assert "summarise the repo" in cmd
    assert "--model" in cmd and "Gemini 3.1 Pro (High)" in cmd
    assert cwd == "/tmp/proj"

    # Each stdout line became an output event, terminated by a single done.
    output_texts = [e.text for e in events if e.kind == AgentEventKind.OUTPUT]
    assert output_texts == ["Hello from agy", "second line"]
    assert events[-1].kind == AgentEventKind.DONE

    assert done.kind == AgentEventKind.DONE
    assert done.text == "Hello from agy\nsecond line"
    assert done.data is not None
    assert done.data["final_text"] == "Hello from agy\nsecond line"
    assert done.data["exit_code"] == 0
    assert done.data["error"] is None
    assert done.data["interrupted"] is False
    assert done.data["tool_iterations"] == 0


async def test_run_turn_does_not_inject_api_key_into_env() -> None:
    # Antigravity manages its own auth — the session must never add a key.
    fake = _FakeAgy(stdout=["ok"], exit_code=0)
    session = _session(fake)
    await session.run_turn("hi")
    await session.close()

    _cmd, env, _cwd = fake.calls[0]
    lowered = {k.lower() for k in env}
    assert not any("api_key" in k or "api-key" in k for k in lowered)
    assert "anthropic_api_key" not in lowered
    assert "--dangerously-skip-permissions" not in fake.calls[0][0]  # safe default


async def test_run_turn_without_callback_returns_done() -> None:
    fake = _FakeAgy(stdout=["result text"], exit_code=0)
    session = _session(fake)
    done = await session.run_turn("go")
    await session.close()
    assert done.kind == AgentEventKind.DONE
    assert done.text == "result text"


async def test_session_context_manager_runs_a_turn() -> None:
    fake = _FakeAgy(stdout=["from ctx"], exit_code=0)
    async with AntigravitySession(spawn=fake.spawn) as session:
        assert isinstance(session, AgentSession)
        done = await session.run_turn("hi", on_event=_collect([]))
    assert done.data is not None
    assert done.data["error"] is None
    assert done.text == "from ctx"


# ======================================================================
# stderr surfaced as distinct diagnostic output
# ======================================================================


async def test_stderr_lines_are_distinct_diagnostic_output() -> None:
    fake = _FakeAgy(stdout=["the answer"], stderr=["loading model", "thinking..."], exit_code=0)
    session = _session(fake)
    events: list[AgentEvent] = []
    done = await session.run_turn("go", on_event=_collect(events))
    await session.close()

    stderr_events = [e for e in events if (e.data or {}).get("stream") == "stderr"]
    assert {e.text for e in stderr_events} == {"loading model", "thinking..."}
    assert all((e.data or {}).get("diagnostic") is True for e in stderr_events)

    # stderr never pollutes the assistant answer text.
    assert done.text == "the answer"
    assert done.data is not None
    assert done.data["stderr"] == ["loading model", "thinking..."]


# ======================================================================
# Non-zero exit → error event + recorded on done
# ======================================================================


async def test_non_zero_exit_emits_error_and_records_on_done() -> None:
    fake = _FakeAgy(stdout=["partial output"], stderr=["fatal: not authenticated"], exit_code=2)
    session = _session(fake)
    events: list[AgentEvent] = []
    done = await session.run_turn("go", on_event=_collect(events))
    await session.close()

    errors = [e for e in events if e.kind == AgentEventKind.ERROR]
    assert len(errors) == 1
    assert "exited with code 2" in (errors[0].text or "")

    assert done.kind == AgentEventKind.DONE
    assert done.data is not None
    assert done.data["exit_code"] == 2
    assert done.data["error"] and "code 2" in done.data["error"]
    # The stderr tail is attached for diagnostics.
    assert done.data["stderr"] == ["fatal: not authenticated"]


# ======================================================================
# Over-limit line survival (reader must not wedge)
# ======================================================================


async def test_run_turn_survives_oversized_stdout_line() -> None:
    # A single stdout line larger than asyncio's default 64 KiB StreamReader cap
    # must NOT wedge the reader: readline() raises, the reader discards that line
    # and keeps going, so lines after it are still delivered and the turn
    # completes promptly instead of hanging to its full timeout while the child
    # deadlocks on stdout backpressure.
    huge = "X" * (128 * 1024)  # 128 KiB — well over the 64 KiB default
    fake = _FakeAgy(stdout=[huge, "after the big line"], exit_code=0, stdout_limit=None)
    session = _session(fake, turn_timeout=5.0)

    events: list[AgentEvent] = []
    done = await asyncio.wait_for(session.run_turn("go", on_event=_collect(events)), timeout=30.0)
    await session.close()

    assert done.kind == AgentEventKind.DONE
    assert done.data is not None
    assert done.data["error"] is None
    assert done.data["interrupted"] is False
    # The oversized line was dropped; the following line survived.
    output_texts = [e.text for e in events if e.kind == AgentEventKind.OUTPUT and (e.data or {}).get("stream") == "stdout"]
    assert output_texts == ["after the big line"]
    assert done.text == "after the big line"
    # The discard was recorded as a diagnostic for the operator.
    assert done.data["stderr"] is not None
    assert any("over buffer limit" in line for line in done.data["stderr"])


# ======================================================================
# Fail closed: missing binary → AgentBackendUnavailable
# ======================================================================


async def test_ensure_started_missing_binary_raises_unavailable() -> None:
    # PATH probe finds no ``agy`` → honest fail-closed before any turn.
    session = AntigravitySession(which=lambda _b: None)
    with pytest.raises(AgentBackendUnavailable) as excinfo:
        await session.ensure_started()
    assert excinfo.value.backend_id == "antigravity"
    assert "antigravity" in str(excinfo.value).lower()


async def test_run_turn_spawn_failure_raises_unavailable() -> None:
    # The binary vanished between probe and spawn → spawn OSError becomes the
    # honest fail-closed signal, not a leaked raw OSError.
    async def boom_spawn(_cmd, _env, _cwd):
        raise FileNotFoundError("agy: command not found")

    session = AntigravitySession(spawn=boom_spawn)
    with pytest.raises(AgentBackendUnavailable) as excinfo:
        await session.run_turn("hello")
    assert excinfo.value.backend_id == "antigravity"


async def test_run_turn_generic_oserror_raises_unavailable() -> None:
    async def boom_spawn(_cmd, _env, _cwd):
        raise OSError("Exec format error")

    session = AntigravitySession(spawn=boom_spawn)
    with pytest.raises(AgentBackendUnavailable):
        await session.run_turn("hello")


async def test_ensure_started_trusts_injected_spawn_without_binary() -> None:
    # With a custom spawn seam and no ``which``, ensure_started must not do a
    # real PATH probe (tests never install agy).
    fake = _FakeAgy(stdout=["ok"], exit_code=0)
    session = _session(fake)
    await session.ensure_started()  # must not raise
    done = await session.run_turn("hi")
    await session.close()
    assert done.data is not None
    assert done.data["exit_code"] == 0


# ======================================================================
# Timeout: a stalled child is bounded by turn_timeout, not hung forever
# ======================================================================


async def test_run_turn_times_out_on_stalled_child() -> None:
    class _StallProcess:
        """A child that never produces output and never exits on its own."""

        def __init__(self) -> None:
            self.stdout = asyncio.StreamReader()  # never fed, never EOF
            self.stderr = asyncio.StreamReader()
            self.returncode: int | None = None
            self.terminated = False

        def terminate(self) -> None:
            self.terminated = True
            self.returncode = -15
            self.stdout.feed_eof()
            self.stderr.feed_eof()

        def kill(self) -> None:
            self.returncode = -9
            self.stdout.feed_eof()
            self.stderr.feed_eof()

        async def wait(self) -> int:
            return self.returncode if self.returncode is not None else -15

    proc = _StallProcess()

    async def spawn(_cmd, _env, _cwd):
        return proc

    session = AntigravitySession(spawn=spawn, turn_timeout=0.3)
    events: list[AgentEvent] = []
    done = await asyncio.wait_for(session.run_turn("go", on_event=_collect(events)), timeout=10.0)
    await session.close()

    assert done.kind == AgentEventKind.DONE
    assert done.data is not None
    assert done.data["interrupted"] is True
    assert done.data["error"] and "timed out" in done.data["error"]
    # The stalled child was terminated on abort.
    assert proc.terminated is True
    errors = [e for e in events if e.kind == AgentEventKind.ERROR]
    assert len(errors) == 1
