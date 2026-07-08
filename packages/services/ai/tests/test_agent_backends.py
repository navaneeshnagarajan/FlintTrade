"""Tests for the agent-backend streaming core.

Covers the four layers of ``flinttrade_ai.agent_backends``:

* the declarative catalogue + registry (all six backends, correct kinds),
* fail-closed detection (LLM config + CLI ``PATH`` probes, fully injected),
* the Codex app-server JSON-RPC framing (handshake + turn + notification →
  AgentEvent) driven against a fake stdio pipe — no real codex required, and
* the ``AgentBackendUnavailable`` fail-closed signal on spawn failure.

Every test uses in-process fakes; nothing is installed or shelled out.
"""

from __future__ import annotations

import asyncio
import json
import types

import pytest

from flinttrade_ai.agent_backends import (
    AGENT_BACKEND_CATALOGUE,
    CATALOGUE_IDS,
    AgentBackendKind,
    AgentBackendUnavailable,
    AgentEvent,
    AgentEventKind,
    AgentSession,
    BackendStatus,
    CodexAppServerSession,
    backend_ids,
    detect_backend,
    get_backend,
    get_session,
    list_backends,
    project_codex_notification,
)

pytestmark = pytest.mark.unit


# ======================================================================
# Catalogue + registry
# ======================================================================


def test_catalogue_lists_all_six_backends() -> None:
    ids = backend_ids()
    for expected in (
        "claude-code",
        "claude-code-oauth",
        "cerebras",
        "codex",
        "antigravity",
        "hermes",
    ):
        assert expected in ids
    assert len(AGENT_BACKEND_CATALOGUE) == 6
    assert set(CATALOGUE_IDS) == set(ids) & set(CATALOGUE_IDS)


def test_backend_kinds_are_correct() -> None:
    kinds = {p.id: p.kind for p in list_backends()}
    assert kinds["claude-code"] == AgentBackendKind.LLM
    assert kinds["claude-code-oauth"] == AgentBackendKind.LLM
    assert kinds["cerebras"] == AgentBackendKind.LLM
    assert kinds["codex"] == AgentBackendKind.CLI_AGENT
    assert kinds["antigravity"] == AgentBackendKind.CLI_AGENT
    assert kinds["hermes"] == AgentBackendKind.ACP_AGENT


def test_llm_backends_carry_provider_agents_carry_binaries() -> None:
    claude = get_backend("claude-code")
    assert claude.is_llm and claude.llm_provider == "anthropic"
    assert claude.detect_binaries == ()

    codex = get_backend("codex")
    assert codex.is_cli_agent and codex.requires_binary
    assert codex.detect_binaries == ("codex",)
    assert codex.invocation == ("codex", "app-server")

    hermes = get_backend("hermes")
    assert hermes.is_acp_agent
    assert hermes.detect_binaries == ("hermes", "hermes-acp")


def test_profile_to_dict_is_json_friendly() -> None:
    payload = get_backend("codex").to_dict()
    json.dumps(payload)  # must not raise
    assert payload["id"] == "codex"
    assert payload["kind"] == "cli_agent"
    assert payload["requires_binary"] is True


def test_get_backend_unknown_raises() -> None:
    with pytest.raises(KeyError):
        get_backend("does-not-exist")


# ======================================================================
# Detection — agent runtimes (PATH probes)
# ======================================================================


def test_detect_cli_not_installed_when_binary_absent() -> None:
    status = detect_backend("codex", which=lambda _b: None)
    assert status == BackendStatus.NOT_INSTALLED


def test_detect_cli_ready_when_binary_and_version_ok() -> None:
    status = detect_backend(
        "codex",
        which=lambda b: f"/usr/bin/{b}",
        version_probe=lambda _cmd: True,
    )
    assert status == BackendStatus.READY


def test_detect_cli_installed_when_version_probe_fails() -> None:
    status = detect_backend(
        "codex",
        which=lambda b: f"/usr/bin/{b}",
        version_probe=lambda _cmd: False,
    )
    assert status == BackendStatus.INSTALLED


def test_detect_hermes_resolves_alias_binary() -> None:
    # Primary "hermes" absent, alias "hermes-acp" present.
    seen: list[str] = []

    def which(binary: str) -> str | None:
        seen.append(binary)
        return "/usr/local/bin/hermes-acp" if binary == "hermes-acp" else None

    status = detect_backend("hermes", which=which, version_probe=lambda _cmd: True)
    assert status == BackendStatus.READY
    assert seen == ["hermes", "hermes-acp"]


# ======================================================================
# Detection — LLM providers (config)
# ======================================================================


def _cfg(provider: str, api_key: str) -> types.SimpleNamespace:
    return types.SimpleNamespace(provider=provider, api_key=api_key)


def test_detect_llm_ready_when_provider_and_key_match() -> None:
    status = detect_backend("cerebras", llm_config=_cfg("cerebras", "csk-abc123"))
    assert status == BackendStatus.READY


def test_detect_llm_needs_config_on_provider_mismatch() -> None:
    status = detect_backend("cerebras", llm_config=_cfg("anthropic", "sk-ant-api-xxx"))
    assert status == BackendStatus.NEEDS_CONFIG


def test_detect_llm_needs_config_when_key_missing() -> None:
    status = detect_backend("cerebras", llm_config=_cfg("cerebras", ""))
    assert status == BackendStatus.NEEDS_CONFIG


def test_detect_llm_needs_config_when_no_config() -> None:
    status = detect_backend("cerebras", llm_config=None)
    # No injected config and no workspace in the test env → needs_config.
    assert status in (BackendStatus.NEEDS_CONFIG, BackendStatus.READY)
    # Force the honest no-config branch with an explicit empty namespace.
    assert detect_backend("cerebras", llm_config=_cfg("", "")) == BackendStatus.NEEDS_CONFIG


def test_detect_claude_api_key_vs_oauth_by_token_shape() -> None:
    api_key_token = "sk-ant-api03-abcdef"
    oauth_token = "sk-ant-oat01-abcdef"

    # Standard API key → the api-key backend is ready, the oauth one is not.
    assert detect_backend("claude-code", llm_config=_cfg("anthropic", api_key_token)) == BackendStatus.READY
    assert (
        detect_backend("claude-code-oauth", llm_config=_cfg("anthropic", api_key_token))
        == BackendStatus.NEEDS_CONFIG
    )

    # OAuth-shaped token → the oauth backend is ready, the api-key one is not.
    assert detect_backend("claude-code-oauth", llm_config=_cfg("anthropic", oauth_token)) == BackendStatus.READY
    assert (
        detect_backend("claude-code", llm_config=_cfg("anthropic", oauth_token)) == BackendStatus.NEEDS_CONFIG
    )


def test_detect_claude_oauth_accepts_jwt_and_cc_tokens() -> None:
    for token in ("eyJhbGciOiJI.payload.sig", "cc-1234567890"):
        assert (
            detect_backend("claude-code-oauth", llm_config=_cfg("anthropic", token)) == BackendStatus.READY
        )


# ======================================================================
# get_session
# ======================================================================


def test_get_session_codex_returns_session() -> None:
    session = get_session("codex", cwd="/tmp/x")
    assert isinstance(session, CodexAppServerSession)
    assert isinstance(session, AgentSession)
    assert session.backend_id == "codex"


def test_get_session_llm_backend_raises_value_error() -> None:
    with pytest.raises(ValueError):
        get_session("cerebras")


def test_get_session_unimplemented_runtime_raises() -> None:
    with pytest.raises(NotImplementedError):
        get_session("antigravity")
    with pytest.raises(NotImplementedError):
        get_session("hermes")


# ======================================================================
# Notification projection (pure)
# ======================================================================


def test_project_agent_message_is_output() -> None:
    events = project_codex_notification(
        {"method": "item/completed", "params": {"item": {"type": "agentMessage", "text": "hi"}}}
    )
    assert len(events) == 1
    assert events[0].kind == AgentEventKind.OUTPUT
    assert events[0].text == "hi"


def test_project_command_execution_is_tool() -> None:
    events = project_codex_notification(
        {
            "method": "item/completed",
            "params": {
                "item": {
                    "type": "commandExecution",
                    "id": "c1",
                    "command": "ls -la",
                    "exitCode": 0,
                    "aggregatedOutput": "file.txt",
                }
            },
        }
    )
    assert len(events) == 1
    assert events[0].kind == AgentEventKind.TOOL
    assert events[0].data is not None
    assert events[0].data["tool"] == "exec_command"
    assert events[0].data["exit_code"] == 0


def test_project_reasoning_is_tagged_output() -> None:
    events = project_codex_notification(
        {"method": "item/completed", "params": {"item": {"type": "reasoning", "summary": ["plan"]}}}
    )
    assert len(events) == 1
    assert events[0].kind == AgentEventKind.OUTPUT
    assert (events[0].data or {}).get("reasoning") is True


def test_project_streaming_delta_is_streaming_output() -> None:
    events = project_codex_notification(
        {"method": "item/agentMessage/outputDelta", "params": {"delta": "par"}}
    )
    assert len(events) == 1
    assert events[0].kind == AgentEventKind.OUTPUT
    assert (events[0].data or {}).get("streaming") is True


def test_project_non_materialising_notifications_are_empty() -> None:
    assert project_codex_notification({"method": "turn/started", "params": {}}) == []
    assert (
        project_codex_notification(
            {"method": "item/completed", "params": {"item": {"type": "userMessage"}}}
        )
        == []
    )


# ======================================================================
# Codex session — framing against a fake stdio pipe
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


class _FakeCodexServer:
    """Scripts codex app-server replies for the handshake + one turn."""

    def __init__(self, *, extra_notifications=None, server_request=None, turn_start_error=None) -> None:
        self.client_out = asyncio.StreamReader()
        self.stderr = asyncio.StreamReader()
        self.stderr.feed_eof()
        self.received: list[dict] = []
        self._extra_notifications = extra_notifications or []
        self._server_request = server_request
        self._turn_start_error = turn_start_error
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
            self._feed({"id": mid, "result": {"userAgent": "codex/test"}})
        elif method == "initialized":
            return
        elif method == "thread/start":
            self._feed({"id": mid, "result": {"thread": {"id": "thread-1"}}})
        elif method == "turn/start":
            if self._turn_start_error is not None:
                self._feed({"id": mid, "error": self._turn_start_error})
                return
            self._feed({"id": mid, "result": {"turn": {"id": "turn-1"}}})
            if self._server_request is not None:
                self._feed(self._server_request)
            self._feed(
                {
                    "method": "item/completed",
                    "params": {"item": {"type": "reasoning", "id": "r1", "summary": ["thinking"]}},
                }
            )
            self._feed(
                {
                    "method": "item/completed",
                    "params": {
                        "item": {
                            "type": "commandExecution",
                            "id": "c1",
                            "command": "ls",
                            "exitCode": 0,
                            "aggregatedOutput": "out",
                        }
                    },
                }
            )
            self._feed(
                {
                    "method": "item/completed",
                    "params": {"item": {"type": "agentMessage", "id": "a1", "text": "Hello from codex"}},
                }
            )
            for note in self._extra_notifications:
                self._feed(note)
            self._feed({"method": "turn/completed", "params": {"turn": {"id": "turn-1", "status": "completed"}}})


async def test_codex_session_handshake_and_turn_stream() -> None:
    server = _FakeCodexServer()
    session = CodexAppServerSession(spawn=server.spawn, codex_home="/tmp/codex-home")

    events: list[AgentEvent] = []

    async def on_event(ev: AgentEvent) -> None:
        events.append(ev)

    await session.ensure_started()
    done = await session.run_turn("do something", on_event=on_event)
    await session.close()

    # Handshake framing was exercised over the fake pipe.
    methods = [m.get("method") for m in server.received]
    assert methods[0] == "initialize"
    assert "initialized" in methods
    assert "thread/start" in methods
    assert "turn/start" in methods

    # turn/start carried the prompt as a text input item.
    turn_start = next(m for m in server.received if m.get("method") == "turn/start")
    assert turn_start["params"]["input"] == [{"type": "text", "text": "do something"}]

    # Notifications projected into events: a reasoning output, a tool event,
    # an assistant output, and a terminal done.
    kinds = [e.kind for e in events]
    assert AgentEventKind.OUTPUT in kinds
    assert AgentEventKind.TOOL in kinds
    assert kinds[-1] == AgentEventKind.DONE

    assert done.kind == AgentEventKind.DONE
    assert done.text == "Hello from codex"
    assert done.data is not None
    assert done.data["final_text"] == "Hello from codex"
    assert done.data["tool_iterations"] == 1
    assert done.data["error"] is None
    assert done.data["thread_id"] == "thread-1"


async def test_codex_session_handles_server_approval_request() -> None:
    approval_req = {"id": 999, "method": "exec/approval", "params": {"command": "rm -rf /"}}
    server = _FakeCodexServer(server_request=approval_req)

    decisions: list[str] = []

    async def approval(method: str, params) -> str:
        decisions.append(method)
        return "denied"

    session = CodexAppServerSession(spawn=server.spawn, approval_callback=approval)
    events: list[AgentEvent] = []
    await session.run_turn("go", on_event=_collect(events))
    await session.close()

    assert decisions == ["exec/approval"]
    # The client replied to the server-initiated request with the decision.
    reply = next((m for m in server.received if m.get("id") == 999 and "result" in m), None)
    assert reply is not None
    assert reply["result"] == {"decision": "denied"}


def _collect(sink: list[AgentEvent]):
    async def _on_event(ev: AgentEvent) -> None:
        sink.append(ev)

    return _on_event


async def test_codex_session_run_turn_without_callback_returns_done() -> None:
    server = _FakeCodexServer()
    session = CodexAppServerSession(spawn=server.spawn)
    done = await session.run_turn("hi")
    await session.close()
    assert done.kind == AgentEventKind.DONE
    assert done.text == "Hello from codex"


async def test_codex_session_turn_start_error_emits_single_error() -> None:
    server = _FakeCodexServer(turn_start_error={"code": -32000, "message": "no auth profile"})
    session = CodexAppServerSession(spawn=server.spawn)
    events: list[AgentEvent] = []
    done = await session.run_turn("go", on_event=_collect(events))
    await session.close()

    error_events = [e for e in events if e.kind == AgentEventKind.ERROR]
    assert len(error_events) == 1
    assert "turn/start failed" in (error_events[0].text or "")
    assert done.kind == AgentEventKind.DONE
    assert done.data is not None
    assert done.data["error"] and "no auth profile" in done.data["error"]


async def test_codex_session_context_manager() -> None:
    server = _FakeCodexServer()
    async with CodexAppServerSession(spawn=server.spawn) as session:
        done = await session.run_turn("hi", on_event=_collect([]))
    assert done.data is not None
    assert done.data["error"] is None


# ======================================================================
# Fail-closed: spawn failure → AgentBackendUnavailable
# ======================================================================


async def test_spawn_failure_raises_agent_backend_unavailable() -> None:
    async def boom_spawn(_cmd, _env):
        raise FileNotFoundError("codex: command not found")

    session = CodexAppServerSession(spawn=boom_spawn)
    with pytest.raises(AgentBackendUnavailable) as excinfo:
        await session.ensure_started()
    assert excinfo.value.backend_id == "codex"
    assert "codex" in str(excinfo.value).lower()


async def test_run_turn_surfaces_spawn_failure() -> None:
    async def boom_spawn(_cmd, _env):
        raise FileNotFoundError("nope")

    session = CodexAppServerSession(spawn=boom_spawn)
    with pytest.raises(AgentBackendUnavailable):
        await session.run_turn("hello")
