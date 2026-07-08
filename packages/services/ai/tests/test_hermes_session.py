"""Tests for the streaming Hermes ACP agent session (Wave B2).

Covers :class:`~flinttrade_ai.agent_backends.hermes_session.HermesACPSession`:

* the pure ACP ``session/update`` → :class:`AgentEvent` projection,
* entrypoint detection (binary / alias / ``python -m acp_adapter`` fallback),
* the ACP JSON-RPC framing (initialize + session/new handshake, then a streamed
  ``session/prompt`` turn whose reply arrives last) driven against a fake stdio
  pipe — no real Hermes required,
* server-initiated ``session/request_permission`` handling,
* oversized-frame reader resilience (>64 KiB), and
* the ``AgentBackendUnavailable`` fail-closed signal on a missing entrypoint /
  spawn failure.

Every test uses in-process fakes; nothing is installed or shelled out.
"""

from __future__ import annotations

import asyncio
import json

import pytest

from flinttrade_ai.agent_backends import (
    AgentBackendUnavailable,
    AgentEvent,
    AgentEventKind,
    AgentSession,
)
from flinttrade_ai.agent_backends.hermes_session import (
    HermesACPError,
    HermesACPSession,
    _detect_hermes_invocation,
    project_acp_notification,
)

pytestmark = pytest.mark.unit


def _update(session_update: str, **fields: object) -> dict:
    """Wrap an ACP update body in a ``session/update`` notification."""
    body = {"sessionUpdate": session_update, **fields}
    return {"method": "session/update", "params": {"sessionId": "sess-1", "update": body}}


def _collect(sink: list[AgentEvent]):
    async def _on_event(ev: AgentEvent) -> None:
        sink.append(ev)

    return _on_event


# ======================================================================
# Notification projection (pure)
# ======================================================================


def test_project_agent_message_chunk_is_streaming_output() -> None:
    events = project_acp_notification(
        _update("agent_message_chunk", content={"type": "text", "text": "hi"})
    )
    assert len(events) == 1
    assert events[0].kind == AgentEventKind.OUTPUT
    assert events[0].text == "hi"
    assert (events[0].data or {}).get("streaming") is True
    assert not (events[0].data or {}).get("reasoning")


def test_project_agent_thought_chunk_is_reasoning_output() -> None:
    events = project_acp_notification(
        _update("agent_thought_chunk", content={"type": "text", "text": "thinking"})
    )
    assert len(events) == 1
    assert events[0].kind == AgentEventKind.OUTPUT
    assert (events[0].data or {}).get("reasoning") is True


def test_project_tool_call_is_tool_start() -> None:
    events = project_acp_notification(
        _update("tool_call", toolCallId="t1", title="Read file.py", kind="read", status="pending")
    )
    assert len(events) == 1
    assert events[0].kind == AgentEventKind.TOOL
    assert events[0].text == "Read file.py"
    assert events[0].data is not None
    assert events[0].data["tool_call_id"] == "t1"
    assert events[0].data["phase"] == "start"


def test_project_tool_call_update_is_tool_update() -> None:
    events = project_acp_notification(
        _update("tool_call_update", toolCallId="t1", status="completed")
    )
    assert len(events) == 1
    assert events[0].kind == AgentEventKind.TOOL
    assert (events[0].data or {}).get("phase") == "update"


def test_project_plan_is_tool() -> None:
    events = project_acp_notification(
        _update(
            "plan",
            entries=[
                {"content": "step 1", "status": "pending", "priority": "medium"},
                {"content": "step 2", "status": "in_progress", "priority": "high"},
            ],
        )
    )
    assert len(events) == 1
    assert events[0].kind == AgentEventKind.TOOL
    assert (events[0].data or {}).get("plan") is True
    assert len((events[0].data or {}).get("entries") or []) == 2


def test_project_user_message_chunk_is_empty() -> None:
    assert project_acp_notification(
        _update("user_message_chunk", content={"type": "text", "text": "echoed"})
    ) == []


def test_project_metadata_updates_are_empty() -> None:
    assert project_acp_notification(_update("available_commands_update", availableCommands=[])) == []
    assert project_acp_notification(_update("usage_update", size=1000, used=10)) == []
    assert project_acp_notification(_update("current_mode_update", currentModeId="default")) == []


def test_project_non_session_update_is_empty() -> None:
    assert project_acp_notification({"method": "something/else", "params": {}}) == []
    assert project_acp_notification({"method": "initialize", "params": {}}) == []


def test_project_unknown_update_records_existence_as_update() -> None:
    events = project_acp_notification(_update("brand_new_update_kind", foo="bar"))
    assert len(events) == 1
    assert events[0].kind == AgentEventKind.TOOL
    # Marked as an update phase so it never inflates the tool-iteration count.
    assert (events[0].data or {}).get("phase") == "update"


# ======================================================================
# Entrypoint detection
# ======================================================================


def test_detect_resolves_hermes_binary_with_acp_subcommand() -> None:
    invocation = _detect_hermes_invocation(
        which=lambda b: "/usr/local/bin/hermes" if b == "hermes" else None,
        find_spec=lambda _m: None,
    )
    assert invocation == ["/usr/local/bin/hermes", "acp"]


def test_detect_resolves_hermes_acp_alias() -> None:
    invocation = _detect_hermes_invocation(
        which=lambda b: "/usr/local/bin/hermes-acp" if b == "hermes-acp" else None,
        find_spec=lambda _m: None,
    )
    assert invocation == ["/usr/local/bin/hermes-acp"]


def test_detect_falls_back_to_python_module_when_importable() -> None:
    invocation = _detect_hermes_invocation(
        which=lambda _b: None,
        find_spec=lambda m: object() if m == "acp_adapter" else None,
    )
    assert invocation is not None
    assert invocation[1:] == ["-m", "acp_adapter"]


def test_detect_returns_none_when_nothing_available() -> None:
    invocation = _detect_hermes_invocation(which=lambda _b: None, find_spec=lambda _m: None)
    assert invocation is None


# ======================================================================
# Fake ACP stdio server (drives a real asyncio.StreamReader)
# ======================================================================


class _FakeWriter:
    """A stdin writer that parses newline-framed JSON and calls a server hook."""

    def __init__(self, on_line) -> None:
        self._buf = b""
        self._on_line = on_line
        self.closed = False

    def write(self, data: bytes) -> None:
        self._buf += data
        while b"\n" in self._buf:
            line, self._buf = self._buf.split(b"\n", 1)
            if line.strip():
                self._on_line(line)

    async def drain(self) -> None:
        return None

    def close(self) -> None:
        self.closed = True


class _FakeProcess:
    """A minimal asyncio.subprocess.Process stand-in over StreamReaders."""

    def __init__(self, stdout: asyncio.StreamReader, stdin: _FakeWriter, stderr: asyncio.StreamReader) -> None:
        self.stdout = stdout
        self.stdin = stdin
        self.stderr = stderr
        self.returncode: int | None = None

    def terminate(self) -> None:
        self.returncode = 0
        self.stdout.feed_eof()

    def kill(self) -> None:
        self.returncode = -9
        self.stdout.feed_eof()

    async def wait(self) -> int:
        return self.returncode or 0


class _FakeHermesServer:
    """Scripts Hermes ACP replies for the handshake + one streamed turn.

    The ``session/prompt`` reply is fed **last**, after the streaming
    ``session/update`` notifications, mirroring the real ACP contract where the
    prompt reply carries the turn's terminal ``stopReason``.
    """

    def __init__(
        self,
        *,
        extra_notifications=None,
        server_request=None,
        prompt_error=None,
        stop_reason: str = "end_turn",
        session_new_error=None,
    ) -> None:
        self.client_out = asyncio.StreamReader()
        self.stderr = asyncio.StreamReader()
        self.stderr.feed_eof()
        self.received: list[dict] = []
        self._extra_notifications = extra_notifications or []
        self._server_request = server_request
        self._prompt_error = prompt_error
        self._stop_reason = stop_reason
        self._session_new_error = session_new_error
        self.writer = _FakeWriter(self._on_client_line)
        self.proc = _FakeProcess(self.client_out, self.writer, self.stderr)

    async def spawn(self, _cmd, _env):  # matches the SpawnFn seam
        return self.proc

    def _feed(self, obj: dict) -> None:
        self.client_out.feed_data((json.dumps(obj) + "\n").encode("utf-8"))

    def _on_client_line(self, line: bytes) -> None:
        msg = json.loads(line)
        self.received.append(msg)
        method = msg.get("method")
        mid = msg.get("id")
        if method == "initialize":
            self._feed(
                {
                    "id": mid,
                    "result": {
                        "protocolVersion": 1,
                        "agentInfo": {"name": "hermes-agent", "version": "1.0.0"},
                        "agentCapabilities": {},
                        "authMethods": [],
                    },
                }
            )
        elif method == "session/new":
            if self._session_new_error is not None:
                self._feed({"id": mid, "error": self._session_new_error})
                return
            self._feed({"id": mid, "result": {"sessionId": "sess-1"}})
        elif method == "session/prompt":
            # Server-initiated request (e.g. a permission prompt) first.
            if self._server_request is not None:
                self._feed(self._server_request)
            # Stream the turn's updates: a thought, a tool call, two message
            # chunks, then any extras.
            self._feed(_update("agent_thought_chunk", content={"type": "text", "text": "planning"}))
            self._feed(
                _update("tool_call", toolCallId="t1", title="Read data.csv", kind="read", status="pending")
            )
            self._feed(_update("tool_call_update", toolCallId="t1", status="completed"))
            self._feed(_update("agent_message_chunk", content={"type": "text", "text": "Hello "}))
            self._feed(_update("agent_message_chunk", content={"type": "text", "text": "from hermes"}))
            for note in self._extra_notifications:
                self._feed(note)
            # The prompt reply arrives LAST, carrying the terminal stopReason.
            if self._prompt_error is not None:
                self._feed({"id": mid, "error": self._prompt_error})
            else:
                self._feed({"id": mid, "result": {"stopReason": self._stop_reason}})
        elif method == "session/cancel":
            return


# ======================================================================
# Handshake + streamed turn
# ======================================================================


async def test_hermes_session_handshake_and_turn_stream() -> None:
    server = _FakeHermesServer()
    session = HermesACPSession(
        spawn=server.spawn, invocation=("hermes", "acp"), hermes_home="/tmp/hermes-home"
    )

    events: list[AgentEvent] = []
    await session.ensure_started()
    done = await session.run_turn("do something", on_event=_collect(events))
    await session.close()

    # Handshake framing was exercised over the fake pipe.
    methods = [m.get("method") for m in server.received]
    assert methods[0] == "initialize"
    assert "session/new" in methods
    assert "session/prompt" in methods

    # session/prompt carried the prompt as a text input block + the session id.
    prompt_msg = next(m for m in server.received if m.get("method") == "session/prompt")
    assert prompt_msg["params"]["sessionId"] == "sess-1"
    assert prompt_msg["params"]["prompt"] == [{"type": "text", "text": "do something"}]

    # Notifications projected into events: reasoning output, tool events, and
    # a terminal done.
    kinds = [e.kind for e in events]
    assert AgentEventKind.OUTPUT in kinds
    assert AgentEventKind.TOOL in kinds
    assert kinds[-1] == AgentEventKind.DONE

    assert done.kind == AgentEventKind.DONE
    # Streaming message chunks accumulate into the final assistant text.
    assert done.text == "Hello from hermes"
    assert done.data is not None
    assert done.data["final_text"] == "Hello from hermes"
    # Only the tool_call start counts; the tool_call_update does not.
    assert done.data["tool_iterations"] == 1
    assert done.data["error"] is None
    assert done.data["stop_reason"] == "end_turn"
    assert done.data["session_id"] == "sess-1"


async def test_hermes_session_run_turn_without_callback_returns_done() -> None:
    server = _FakeHermesServer()
    session = HermesACPSession(spawn=server.spawn, invocation=("hermes", "acp"))
    done = await session.run_turn("hi")
    await session.close()
    assert done.kind == AgentEventKind.DONE
    assert done.text == "Hello from hermes"


async def test_hermes_session_context_manager() -> None:
    server = _FakeHermesServer()
    async with HermesACPSession(spawn=server.spawn, invocation=("hermes", "acp")) as session:
        done = await session.run_turn("hi", on_event=_collect([]))
    assert done.data is not None
    assert done.data["error"] is None


async def test_hermes_session_is_agent_session_subclass() -> None:
    session = HermesACPSession(invocation=("hermes", "acp"))
    assert isinstance(session, AgentSession)
    assert session.backend_id == "hermes"


# ======================================================================
# stopReason semantics
# ======================================================================


async def test_hermes_session_cancelled_stop_reason_marks_interrupted() -> None:
    server = _FakeHermesServer(stop_reason="cancelled")
    session = HermesACPSession(spawn=server.spawn, invocation=("hermes", "acp"))
    done = await session.run_turn("go", on_event=_collect([]))
    await session.close()
    assert done.data is not None
    assert done.data["interrupted"] is True
    assert done.data["error"] is None


async def test_hermes_session_prompt_error_emits_single_error() -> None:
    server = _FakeHermesServer(prompt_error={"code": -32000, "message": "no auth profile"})
    session = HermesACPSession(spawn=server.spawn, invocation=("hermes", "acp"))
    events: list[AgentEvent] = []
    done = await session.run_turn("go", on_event=_collect(events))
    await session.close()

    error_events = [e for e in events if e.kind == AgentEventKind.ERROR]
    assert len(error_events) == 1
    assert "session/prompt failed" in (error_events[0].text or "")
    assert done.kind == AgentEventKind.DONE
    assert done.data is not None
    assert done.data["error"] and "no auth profile" in done.data["error"]


# ======================================================================
# Server-initiated permission request
# ======================================================================


async def test_hermes_session_handles_permission_request() -> None:
    permission_req = {
        "id": 999,
        "method": "session/request_permission",
        "params": {
            "sessionId": "sess-1",
            "toolCall": {"toolCallId": "t9", "title": "rm -rf /", "kind": "execute"},
            "options": [
                {"optionId": "allow-1", "name": "Allow", "kind": "allow_once"},
                {"optionId": "reject-1", "name": "Reject", "kind": "reject_once"},
            ],
        },
    }
    server = _FakeHermesServer(server_request=permission_req)

    decisions: list[str] = []

    async def approval(method: str, params) -> str:
        decisions.append(method)
        return "denied"

    session = HermesACPSession(spawn=server.spawn, invocation=("hermes", "acp"), approval_callback=approval)
    events: list[AgentEvent] = []
    await session.run_turn("go", on_event=_collect(events))
    await session.close()

    assert decisions == ["session/request_permission"]
    # The client replied to the server-initiated request selecting the reject
    # option id (fail-closed decision maps onto reject_once).
    reply = next((m for m in server.received if m.get("id") == 999 and "result" in m), None)
    assert reply is not None
    assert reply["result"] == {"outcome": {"outcome": "selected", "optionId": "reject-1"}}


async def test_hermes_session_default_denies_permission_without_callback() -> None:
    permission_req = {
        "id": 42,
        "method": "session/request_permission",
        "params": {
            "sessionId": "sess-1",
            "toolCall": {"toolCallId": "t9", "title": "write", "kind": "edit"},
            "options": [
                {"optionId": "allow-1", "name": "Allow", "kind": "allow_once"},
                {"optionId": "reject-1", "name": "Reject", "kind": "reject_once"},
            ],
        },
    }
    server = _FakeHermesServer(server_request=permission_req)
    # auto_approve defaults to False → fail closed.
    session = HermesACPSession(spawn=server.spawn, invocation=("hermes", "acp"))
    await session.run_turn("go")
    await session.close()

    reply = next((m for m in server.received if m.get("id") == 42 and "result" in m), None)
    assert reply is not None
    assert reply["result"]["outcome"]["outcome"] == "selected"
    assert reply["result"]["outcome"]["optionId"] == "reject-1"


# ======================================================================
# Fail-closed: missing entrypoint / spawn failure → AgentBackendUnavailable
# ======================================================================


async def test_missing_entrypoint_raises_agent_backend_unavailable() -> None:
    # Detection returns None → the entrypoint is absent → fail closed WITHOUT
    # spawning anything.
    session = HermesACPSession(detect=lambda: None)
    with pytest.raises(AgentBackendUnavailable) as excinfo:
        await session.ensure_started()
    assert excinfo.value.backend_id == "hermes"
    assert "hermes" in str(excinfo.value).lower()
    # No client was constructed since detection failed before spawn.
    assert session._client is None


async def test_spawn_failure_raises_agent_backend_unavailable() -> None:
    async def boom_spawn(_cmd, _env):
        raise FileNotFoundError("hermes: command not found")

    session = HermesACPSession(spawn=boom_spawn, invocation=("hermes", "acp"))
    with pytest.raises(AgentBackendUnavailable) as excinfo:
        await session.ensure_started()
    assert excinfo.value.backend_id == "hermes"


async def test_run_turn_surfaces_generic_oserror_as_backend_unavailable() -> None:
    async def boom_spawn(_cmd, _env):
        raise OSError("Exec format error")

    session = HermesACPSession(spawn=boom_spawn, invocation=("hermes", "acp"))
    with pytest.raises(AgentBackendUnavailable):
        await session.run_turn("hello")


# ======================================================================
# No subprocess/reader leak on handshake failure
# ======================================================================


async def test_ensure_started_closes_client_when_session_new_fails() -> None:
    server = _FakeHermesServer(session_new_error={"code": -32000, "message": "no session"})
    session = HermesACPSession(spawn=server.spawn, invocation=("hermes", "acp"))

    with pytest.raises(HermesACPError):
        await session.ensure_started()

    # The subprocess was terminated (close() ran) and the client reference was
    # dropped, so neither the child nor its two reader tasks leak.
    assert session._client is None
    assert server.proc.returncode is not None


# ======================================================================
# Oversized-frame reader resilience (>64 KiB)
# ======================================================================


async def test_hermes_session_survives_oversized_stdout_frame() -> None:
    # A single session/update frame larger than asyncio's default 64 KiB
    # StreamReader cap must NOT wedge the reader: readline() raises on the
    # oversized line, the reader discards it and keeps going, so the turn
    # completes promptly on the following frames instead of hanging to the full
    # turn timeout while the child deadlocks on stdout backpressure.
    huge_text = "X" * (128 * 1024)  # 128 KiB — well over the 64 KiB default cap
    huge_frame = _update("agent_message_chunk", content={"type": "text", "text": huge_text})
    server = _FakeHermesServer(extra_notifications=[huge_frame])
    # A short turn timeout turns a regression (reader dies → long hang) into a
    # fast, unambiguous failure rather than a multi-minute wait.
    session = HermesACPSession(spawn=server.spawn, invocation=("hermes", "acp"), turn_timeout=5.0)

    events: list[AgentEvent] = []
    done = await asyncio.wait_for(session.run_turn("go", on_event=_collect(events)), timeout=30.0)
    client = session._client
    assert client is not None
    reader_alive = client.is_alive()  # reader survived the oversized frame
    diagnostics = client.stderr_tail()
    await session.close()

    # The turn completed normally — not interrupted, no timeout error.
    assert done.kind == AgentEventKind.DONE
    assert done.data is not None
    assert done.data["error"] is None
    assert done.data["interrupted"] is False
    # The small chunks before the oversized frame were still delivered; only the
    # oversized chunk was dropped.
    assert done.text == "Hello from hermes"
    # The reader logged a diagnostic and stayed alive through the whole turn.
    assert reader_alive is True
    assert any("over buffer limit" in line for line in diagnostics)


# ======================================================================
# Stale notifications don't leak across turns
# ======================================================================


async def test_hermes_session_drains_stale_notifications_between_turns() -> None:
    server = _FakeHermesServer()
    session = HermesACPSession(spawn=server.spawn, invocation=("hermes", "acp"))

    await session.run_turn("first")
    assert session._client is not None

    # Simulate a residual frame left in the inbound queue by a prior/interrupted
    # turn. run_turn must drop it, never replay it into the next turn.
    session._client._inbound.put_nowait(
        _update("agent_message_chunk", content={"type": "text", "text": "STALE-LEFTOVER"})
    )

    events: list[AgentEvent] = []
    await session.run_turn("second", on_event=_collect(events))
    await session.close()

    assert all(e.text != "STALE-LEFTOVER" for e in events)
