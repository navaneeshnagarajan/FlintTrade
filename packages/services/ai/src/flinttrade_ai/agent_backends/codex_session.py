"""Streaming Codex app-server session (layer 4).

A full :class:`~flinttrade_ai.agent_backends.session.AgentSession`
implementation over the real ``codex app-server`` protocol: newline-delimited
JSON-RPC 2.0 over stdio. It mirrors Hermes'
``agent/transports/codex_app_server.py`` (the wire client) and
``codex_app_server_session.py`` (the turn driver), reimplemented natively for
FlintTrade with ``asyncio`` instead of threads so it plugs straight into the
async SSE route surface.

Lifecycle::

    session = CodexAppServerSession(cwd="/path/to/proj")
    await session.ensure_started()          # spawn + initialize + thread/start
    done = await session.run_turn("hello", on_event)   # streams AgentEvents
    await session.close()

Fail closed + honest: if the ``codex`` binary is absent (or the spawn fails)
:class:`~flinttrade_ai.agent_backends.session.AgentBackendUnavailable` is
raised with a clear install pointer. Errors during a turn become an ``error``
event and are recorded on the terminal ``done`` event rather than bubbling
raw exceptions to the caller. ``CODEX_HOME`` is passed through to the child.

Dependency-light: stdlib ``asyncio`` + ``json`` only.
"""

from __future__ import annotations

import asyncio
import contextlib
import inspect
import json
import os
from collections.abc import Awaitable, Callable, Mapping, Sequence
from dataclasses import dataclass
from typing import Any, Protocol

from flinttrade_ai.agent_backends.session import (
    AgentBackendUnavailable,
    AgentEvent,
    AgentEventKind,
    AgentSession,
    EventCallback,
)

# Client identity sent in the initialize handshake.
_CLIENT_NAME = "flinttrade"
_CLIENT_TITLE = "FlintTrade"
_CLIENT_VERSION = "0.6.0"

# Timeouts (seconds). The turn timeout bounds a single prompt→response cycle;
# the poll cadence interleaves inbound reads with liveness/deadline checks.
_DEFAULT_TURN_TIMEOUT = 600.0
_HANDSHAKE_TIMEOUT = 15.0
_TURN_START_TIMEOUT = 15.0
_NOTIFICATION_POLL = 0.25
_CLOSE_TIMEOUT = 3.0

# How many tailing stderr lines to attach to a user-facing error.
_STDERR_TAIL_LINES = 12

# Stdout/stderr StreamReader buffer cap. asyncio's default is 64 KiB, but a
# single codex JSON-RPC frame — an ``item/completed`` carrying the full
# aggregated command output inline, a long agentMessage, or a big reasoning
# block — routinely exceeds that. Size the buffer generously so realistic
# frames fit; the reader additionally survives an over-limit frame by
# discarding it rather than dying (see ``_read_stdout``). Mirrors Hermes'
# blocking ``Popen`` reader, which has no per-line cap at all.
_STREAM_LIMIT = 16 * 1024 * 1024  # 16 MiB


@dataclass
class CodexAppServerError(RuntimeError):
    """Raised on a JSON-RPC ``error`` reply from the codex app-server."""

    code: int
    message: str
    data: Any | None = None

    def __str__(self) -> str:  # pragma: no cover - trivial
        return f"codex app-server error {self.code}: {self.message}"


class _ProcessLike(Protocol):
    """The subprocess surface the client needs (asyncio.subprocess.Process)."""

    stdin: Any
    stdout: Any
    stderr: Any
    returncode: int | None

    def terminate(self) -> None: ...

    def kill(self) -> None: ...

    async def wait(self) -> int: ...


# A spawn seam: given argv + env, produce a running process. Injectable so
# tests can drive the framing against a fake stdio pipe without codex present.
SpawnFn = Callable[[Sequence[str], Mapping[str, str]], Awaitable[_ProcessLike]]


async def _default_spawn(cmd: Sequence[str], env: Mapping[str, str]) -> _ProcessLike:
    """Spawn ``codex app-server`` as an asyncio subprocess over stdio pipes."""
    return await asyncio.create_subprocess_exec(
        *cmd,
        stdin=asyncio.subprocess.PIPE,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
        env=dict(env),
        # Raise the per-line StreamReader cap well above the 64 KiB default so a
        # large single JSON-RPC frame doesn't overrun the buffer mid-turn.
        limit=_STREAM_LIMIT,
    )


# --- notification projection ----------------------------------------------


def _truncate(text: str, limit: int = 4000) -> str:
    """Truncate ``text`` to ``limit`` characters for event payloads."""
    return text if len(text) <= limit else text[:limit] + "…"


def project_codex_notification(note: Mapping[str, Any]) -> list[AgentEvent]:
    """Project one codex app-server notification into ``AgentEvent``\\ s.

    Streaming ``*Delta`` notifications become streaming ``output`` events;
    ``item/completed`` items become ``output`` (assistant/reasoning) or
    ``tool`` events. Non-materialising notifications (``turn/started``,
    unknown deltas) produce no events. Pure and side-effect-free so it can be
    unit-tested directly.

    Args:
        note: A single JSON-RPC notification dict.

    Returns:
        Zero or more :class:`AgentEvent`\\ s in emission order.
    """
    method = str(note.get("method", ""))
    params = note.get("params") or {}

    # Streaming text deltas (display-only chunks before item/completed).
    if method.endswith("Delta") or method.endswith("/delta") or method.endswith("outputDelta"):
        delta = params.get("delta") or params.get("text") or ""
        if delta:
            return [AgentEvent(AgentEventKind.OUTPUT, text=str(delta), data={"streaming": True})]
        return []

    if method != "item/completed":
        return []

    item = params.get("item") or {}
    item_type = str(item.get("type") or "")
    item_id = str(item.get("id") or "")

    if item_type == "agentMessage":
        return [AgentEvent(AgentEventKind.OUTPUT, text=str(item.get("text") or ""))]

    if item_type == "reasoning":
        parts: list[str] = []
        parts.extend(str(x) for x in (item.get("summary") or []))
        parts.extend(str(x) for x in (item.get("content") or []))
        text = "\n".join(p for p in parts if p)
        if not text:
            return []
        return [AgentEvent(AgentEventKind.OUTPUT, text=text, data={"reasoning": True})]

    if item_type == "userMessage":
        # Echoed input — not surfaced as a new output event.
        return []

    if item_type == "commandExecution":
        command = str(item.get("command") or "")
        exit_code = item.get("exitCode")
        output = str(item.get("aggregatedOutput") or "")
        return [
            AgentEvent(
                AgentEventKind.TOOL,
                text=f"$ {command}".strip(),
                data={
                    "tool": "exec_command",
                    "item_id": item_id,
                    "command": command,
                    "cwd": item.get("cwd") or "",
                    "exit_code": exit_code,
                    "output": _truncate(output),
                },
            )
        ]

    if item_type == "fileChange":
        changes = []
        for change in item.get("changes") or []:
            kind = (change.get("kind") or {}).get("type") or "update"
            changes.append({"kind": kind, "path": change.get("path") or ""})
        return [
            AgentEvent(
                AgentEventKind.TOOL,
                text=f"apply_patch ({len(changes)} change(s))",
                data={
                    "tool": "apply_patch",
                    "item_id": item_id,
                    "status": item.get("status") or "unknown",
                    "changes": changes,
                },
            )
        ]

    if item_type == "mcpToolCall":
        server = str(item.get("server") or "mcp")
        tool = str(item.get("tool") or "unknown")
        error = item.get("error")
        result = item.get("result")
        return [
            AgentEvent(
                AgentEventKind.TOOL,
                text=f"mcp.{server}.{tool}",
                data={
                    "tool": f"mcp.{server}.{tool}",
                    "item_id": item_id,
                    "error": error,
                    "result": result,
                },
            )
        ]

    if item_type == "dynamicToolCall":
        tool = str(item.get("tool") or "unknown")
        return [
            AgentEvent(
                AgentEventKind.TOOL,
                text=tool,
                data={
                    "tool": tool,
                    "item_id": item_id,
                    "success": item.get("success"),
                },
            )
        ]

    # Unknown / rare items — record their existence without fabricating a
    # tool_call structure.
    return [
        AgentEvent(
            AgentEventKind.TOOL,
            text=f"[codex {item_type}]",
            data={"tool": item_type, "item_id": item_id},
        )
    ]


# --- wire-level JSON-RPC client -------------------------------------------


class _CodexAppServerClient:
    """Async newline-delimited JSON-RPC 2.0 client over the codex stdio pipes.

    One background task reads stdout, resolving reply futures and routing
    notifications + server-initiated requests onto a single inbound queue the
    session drains. A second task tails stderr for diagnostics.
    """

    def __init__(
        self,
        *,
        invocation: Sequence[str],
        codex_home: str | None = None,
        env: Mapping[str, str] | None = None,
        extra_args: Sequence[str] | None = None,
        spawn: SpawnFn | None = None,
    ) -> None:
        self._invocation = tuple(invocation)
        self._codex_home = codex_home
        self._extra_env = dict(env or {})
        self._extra_args = list(extra_args or [])
        self._spawn: SpawnFn = spawn or _default_spawn
        self._proc: _ProcessLike | None = None
        self._next_id = 1
        self._pending: dict[int, asyncio.Future[dict[str, Any]]] = {}
        self._inbound: asyncio.Queue[dict[str, Any]] = asyncio.Queue()
        self._stderr_lines: list[str] = []
        self._reader_task: asyncio.Task[None] | None = None
        self._stderr_task: asyncio.Task[None] | None = None
        self._reader_done = False
        self._closed = False
        self._initialized = False

    # ---- lifecycle ----

    def _build_env(self) -> dict[str, str]:
        """Assemble the child env: inherit, set CODEX_HOME, quiet tracing."""
        env = os.environ.copy()
        if self._codex_home:
            env["CODEX_HOME"] = self._codex_home
        # Keep codex's Rust tracing quiet unless the operator overrides it.
        env.setdefault("RUST_LOG", "warn")
        env.update(self._extra_env)
        return env

    def _build_cmd(self) -> list[str]:
        return [*self._invocation, *self._extra_args]

    async def start(self) -> None:
        """Spawn the subprocess and start the reader tasks. Idempotent.

        Raises:
            AgentBackendUnavailable: if the binary is absent or cannot launch.
        """
        if self._proc is not None:
            return
        cmd = self._build_cmd()
        try:
            self._proc = await self._spawn(cmd, self._build_env())
        except OSError as exc:
            # FileNotFoundError/NotADirectoryError/PermissionError and any other
            # OSError on spawn (bad interpreter, exec-format, resource limits …)
            # all become the honest fail-closed signal rather than a raw OSError.
            raise AgentBackendUnavailable(
                "codex",
                f"could not launch {cmd[0]!r}: install the Codex CLI "
                f"(npm i -g @openai/codex)",
                cause=exc,
            ) from exc
        self._reader_task = asyncio.ensure_future(self._read_stdout())
        if getattr(self._proc, "stderr", None) is not None:
            self._stderr_task = asyncio.ensure_future(self._read_stderr())

    def is_alive(self) -> bool:
        """Return whether the subprocess AND its stdout reader are still live.

        Once the reader task has stopped (EOF, fatal error, or a genuinely dead
        child) the session can make no further progress even if the child's
        ``returncode`` is not yet observable, so report not-alive. This lets
        ``run_turn``'s liveness break fire promptly instead of hanging out the
        full turn timeout.
        """
        if self._reader_done:
            return False
        return self._proc is not None and self._proc.returncode is None

    async def close(self, timeout: float = _CLOSE_TIMEOUT) -> None:
        """Close stdin, terminate the child, and cancel reader tasks."""
        if self._closed:
            return
        self._closed = True
        proc = self._proc
        if proc is not None:
            with contextlib.suppress(Exception):
                if proc.stdin is not None:
                    proc.stdin.close()
            with contextlib.suppress(Exception):
                proc.terminate()
            try:
                await asyncio.wait_for(proc.wait(), timeout)
            except Exception:
                with contextlib.suppress(Exception):
                    proc.kill()
                    await asyncio.wait_for(proc.wait(), 1.0)
        for task in (self._reader_task, self._stderr_task):
            if task is not None:
                task.cancel()
                with contextlib.suppress(asyncio.CancelledError, Exception):
                    await task
        self._proc = None

    # ---- send / receive ----

    def _take_id(self) -> int:
        rid = self._next_id
        self._next_id += 1
        return rid

    async def _send(self, obj: dict[str, Any]) -> None:
        if self._closed:
            raise RuntimeError("codex app-server client is closed")
        proc = self._proc
        if proc is None or proc.stdin is None:
            raise RuntimeError("codex app-server stdin is unavailable")
        data = (json.dumps(obj) + "\n").encode("utf-8")
        proc.stdin.write(data)
        drain = getattr(proc.stdin, "drain", None)
        if drain is not None:
            await drain()

    async def request(
        self,
        method: str,
        params: dict[str, Any] | None = None,
        timeout: float = 30.0,
    ) -> dict[str, Any]:
        """Send a JSON-RPC request and await its reply ``result``.

        Raises:
            CodexAppServerError: on a JSON-RPC ``error`` reply.
            TimeoutError: if no reply arrives within ``timeout``.
        """
        if self._proc is None:
            raise RuntimeError("codex app-server client is not started")
        rid = self._take_id()
        fut: asyncio.Future[dict[str, Any]] = asyncio.get_running_loop().create_future()
        self._pending[rid] = fut
        await self._send({"id": rid, "method": method, "params": params or {}})
        try:
            msg = await asyncio.wait_for(fut, timeout)
        except (asyncio.TimeoutError, TimeoutError) as exc:
            self._pending.pop(rid, None)
            raise TimeoutError(
                f"codex app-server method {method!r} timed out after {timeout}s"
            ) from exc
        if "error" in msg:
            err = msg.get("error") or {}
            raise CodexAppServerError(
                code=int(err.get("code", -1)),
                message=str(err.get("message", "")),
                data=err.get("data"),
            )
        return msg.get("result") or {}

    async def notify(self, method: str, params: dict[str, Any] | None = None) -> None:
        """Send a JSON-RPC notification (no id, no reply expected)."""
        await self._send({"method": method, "params": params or {}})

    async def respond(self, request_id: Any, result: dict[str, Any]) -> None:
        """Reply to a server-initiated request (e.g. an approval prompt)."""
        await self._send({"id": request_id, "result": result})

    async def initialize(
        self,
        *,
        capabilities: dict[str, Any] | None = None,
        timeout: float = _HANDSHAKE_TIMEOUT,
    ) -> dict[str, Any]:
        """Perform the ``initialize`` + ``initialized`` handshake. Idempotent."""
        if self._initialized:
            return {}
        params = {
            "clientInfo": {
                "name": _CLIENT_NAME,
                "title": _CLIENT_TITLE,
                "version": _CLIENT_VERSION,
            },
            "capabilities": capabilities or {},
        }
        result = await self.request("initialize", params, timeout=timeout)
        await self.notify("initialized")
        self._initialized = True
        return result

    async def next_inbound(self) -> dict[str, Any]:
        """Await the next notification or server-initiated request."""
        return await self._inbound.get()

    def drain_inbound(self) -> None:
        """Discard any buffered inbound frames.

        Called at the start of a turn so stale notifications/requests left in
        the queue by a prior or interrupted turn on a reused session are never
        replayed into the new turn.
        """
        while True:
            try:
                self._inbound.get_nowait()
            except asyncio.QueueEmpty:
                break

    def stderr_tail(self, n: int = _STDERR_TAIL_LINES) -> list[str]:
        """Return the last ``n`` captured stderr lines (for diagnostics)."""
        return list(self._stderr_lines[-n:])

    # ---- reader tasks ----

    def _dispatch(self, msg: dict[str, Any]) -> None:
        mid = msg.get("id")
        # Reply: has id + result/error, no method.
        if mid is not None and ("result" in msg or "error" in msg):
            fut = self._pending.pop(mid, None)
            if fut is not None and not fut.done():
                fut.set_result(msg)
            return
        # Notification (no id) or server-initiated request (id + method) —
        # both go onto the inbound queue for the session to route.
        self._inbound.put_nowait(msg)

    def _fail_pending_and_wake(self, reason: str) -> None:
        """Fail every pending request future and wake the inbound consumer.

        Invoked when the stdout reader stops so a caller awaiting a reply
        future (the handshake or ``turn/start``) or blocked on
        :meth:`next_inbound` observes the dead reader at once, ending the turn
        honestly instead of waiting out a long timeout.
        """
        if self._pending:
            exc = RuntimeError(reason)
            for rid in list(self._pending):
                fut = self._pending.pop(rid, None)
                if fut is not None and not fut.done():
                    fut.set_exception(exc)
        # Nudge run_turn's inbound poll so it re-checks liveness immediately.
        with contextlib.suppress(Exception):
            self._inbound.put_nowait({"__reader_stopped__": True})

    async def _read_stdout(self) -> None:
        proc = self._proc
        try:
            if proc is None or proc.stdout is None:
                return
            while True:
                try:
                    line = await proc.stdout.readline()
                except (ValueError, asyncio.LimitOverrunError) as exc:
                    # A single frame exceeded the StreamReader buffer cap.
                    # readline() has already drained the oversized bytes from
                    # the buffer, so discard this frame and keep reading — never
                    # return. If the reader returned here instead, the child
                    # would deadlock on stdout backpressure and the turn would
                    # hang to its full timeout.
                    self._stderr_lines.append(f"<stdout frame over buffer limit; discarded> {exc}")
                    continue
                if not line:
                    break
                stripped = line.strip()
                if not stripped:
                    continue
                try:
                    msg = json.loads(stripped)
                except json.JSONDecodeError:
                    self._stderr_lines.append(f"<non-json stdout> {stripped[:200]!r}")
                    continue
                if isinstance(msg, dict):
                    self._dispatch(msg)
        except asyncio.CancelledError:
            raise
        except Exception as exc:  # pragma: no cover - defensive
            self._stderr_lines.append(f"<stdout reader error> {exc}")
        finally:
            # The reader is stopping (EOF, fatal error, or cancellation). Mark
            # it done so ``is_alive`` reports False, fail any in-flight request
            # futures, and nudge a caller blocked on the inbound queue so the
            # turn ends honestly instead of hanging to its timeout.
            self._reader_done = True
            self._fail_pending_and_wake("codex app-server stdout reader stopped")

    async def _read_stderr(self) -> None:
        proc = self._proc
        if proc is None or proc.stderr is None:
            return
        try:
            while True:
                try:
                    line = await proc.stderr.readline()
                except (ValueError, asyncio.LimitOverrunError):
                    # An over-limit stderr line: readline() already discarded it
                    # from the buffer. Skip it and keep tailing rather than
                    # losing the diagnostics stream entirely.
                    continue
                if not line:
                    break
                self._stderr_lines.append(line.decode("utf-8", "replace").rstrip())
                if len(self._stderr_lines) > 500:
                    self._stderr_lines = self._stderr_lines[-500:]
        except asyncio.CancelledError:
            raise
        except Exception:  # pragma: no cover - defensive
            pass


# --- the session ----------------------------------------------------------

# Optional operator approval callback: given (method, params) it returns the
# decision string ("approved" / "denied"), sync or async.
ApprovalCallback = Callable[[str, Mapping[str, Any]], Awaitable[str] | str]


class CodexAppServerSession(AgentSession):
    """Streaming :class:`AgentSession` over the codex app-server protocol.

    Not thread-safe — one caller drives it at a time (the underlying client
    owns its own reader tasks). Owns one codex thread for the session's
    lifetime.
    """

    backend_id = "codex"

    def __init__(
        self,
        *,
        cwd: str | None = None,
        codex_bin: str = "codex",
        codex_home: str | None = None,
        extra_args: Sequence[str] | None = None,
        env: Mapping[str, str] | None = None,
        spawn: SpawnFn | None = None,
        approval_callback: ApprovalCallback | None = None,
        auto_approve: bool = False,
        turn_timeout: float = _DEFAULT_TURN_TIMEOUT,
        client_factory: Callable[[], _CodexAppServerClient] | None = None,
    ) -> None:
        """Configure a Codex session.

        Args:
            cwd: Working directory for the codex thread (defaults to CWD).
            codex_bin: The codex binary name/path (default ``"codex"``).
            codex_home: Value passed through as ``CODEX_HOME`` to the child;
                defaults to the process's own ``CODEX_HOME`` if set.
            extra_args: Extra args appended after ``app-server``.
            env: Extra environment overlaid on the child env.
            spawn: Injectable spawn seam (tests supply a fake stdio pipe).
            approval_callback: Optional decision maker for codex-side approval
                requests (exec / apply_patch). Returns ``"approved"`` /
                ``"denied"``.
            auto_approve: When no callback is set, whether to approve codex's
                approval requests. Defaults to ``False`` (fail closed).
            turn_timeout: Seconds a single turn may run before it is aborted.
            client_factory: Injectable factory for the wire client (tests).
        """
        self._cwd = cwd or os.getcwd()
        self._codex_bin = codex_bin
        self._codex_home = codex_home or os.environ.get("CODEX_HOME")
        self._extra_args = list(extra_args or [])
        self._env = dict(env or {})
        self._spawn = spawn
        self._approval_callback = approval_callback
        self._auto_approve = auto_approve
        self._turn_timeout = turn_timeout
        self._client_factory = client_factory or self._default_client_factory
        self._client: _CodexAppServerClient | None = None
        self._thread_id: str | None = None
        self._closed = False

    def _default_client_factory(self) -> _CodexAppServerClient:
        return _CodexAppServerClient(
            invocation=(self._codex_bin, "app-server"),
            codex_home=self._codex_home,
            env=self._env,
            extra_args=self._extra_args,
            spawn=self._spawn,
        )

    # ---- lifecycle ----

    async def ensure_started(self) -> None:
        """Spawn codex, handshake, and start a thread. Idempotent.

        Raises:
            AgentBackendUnavailable: if codex cannot be launched.
            CodexAppServerError: if the handshake or thread start fails.
        """
        if self._closed:
            raise RuntimeError("codex session is closed")
        if self._thread_id is not None:
            return
        if self._client is None:
            self._client = self._client_factory()
        await self._client.start()
        # start() has now spawned the child + reader tasks. If the handshake or
        # thread start fails from here, close the client so the subprocess and
        # both reader tasks don't leak, then re-raise the honest error.
        try:
            await self._client.initialize()
            result = await self._client.request(
                "thread/start", {"cwd": self._cwd}, timeout=_HANDSHAKE_TIMEOUT
            )
            thread = result.get("thread") or {}
            thread_id = (
                thread.get("id")
                or thread.get("sessionId")
                or result.get("sessionId")
                or result.get("threadId")
            )
            if not thread_id:
                raise CodexAppServerError(
                    code=-32603,
                    message=f"thread/start returned no thread id (keys: {sorted(result)})",
                )
        except BaseException:
            with contextlib.suppress(Exception):
                await self._client.close()
            self._client = None
            raise
        self._thread_id = str(thread_id)

    async def close(self) -> None:
        """Tear down the codex subprocess. Idempotent."""
        if self._closed:
            return
        self._closed = True
        if self._client is not None:
            await self._client.close()
            self._client = None
        self._thread_id = None

    # ---- per-turn ----

    async def run_turn(self, prompt: str, on_event: EventCallback | None = None) -> AgentEvent:
        """Send ``prompt`` and stream the turn's events via ``on_event``.

        Consumes streaming notifications and server-initiated approval
        requests until ``turn/completed`` (or a timeout / dead subprocess),
        projecting each into an :class:`AgentEvent`. Returns the terminal
        ``done`` event, whose ``data`` carries the aggregated summary.
        """
        await self.ensure_started()
        assert self._client is not None and self._thread_id is not None
        client = self._client
        # A reused session may still hold notifications from a prior/interrupted
        # turn in the inbound queue; drop them so this turn never replays them.
        client.drain_inbound()

        async def emit(event: AgentEvent) -> None:
            if on_event is not None:
                await on_event(event)

        final_text = ""
        tool_iterations = 0
        interrupted = False
        error: str | None = None
        turn_id: str | None = None

        try:
            ts = await client.request(
                "turn/start",
                {"threadId": self._thread_id, "input": [{"type": "text", "text": str(prompt)}]},
                timeout=_TURN_START_TIMEOUT,
            )
            turn_id = (ts.get("turn") or {}).get("id")
        except (CodexAppServerError, TimeoutError, RuntimeError) as exc:
            # RuntimeError covers a stdin already closed and a reader that died
            # mid-handshake (its pending future is failed with RuntimeError);
            # surface all three as an honest single error event, not a raw raise.
            error = f"turn/start failed: {exc}"
            # _finish emits the single terminal error event; keep the stderr
            # tail on the done summary rather than duplicating an error event.
            return await self._finish(
                emit, final_text, tool_iterations, interrupted, error, turn_id,
                stderr_tail=client.stderr_tail(),
            )

        loop = asyncio.get_running_loop()
        deadline = loop.time() + self._turn_timeout
        turn_complete = False

        while not turn_complete:
            remaining = deadline - loop.time()
            if remaining <= 0:
                error = f"codex turn timed out after {self._turn_timeout:.0f}s"
                await self._safe_interrupt(turn_id)
                interrupted = True
                break

            try:
                msg = await asyncio.wait_for(
                    client.next_inbound(), timeout=min(_NOTIFICATION_POLL, remaining)
                )
            except (asyncio.TimeoutError, TimeoutError):
                if not client.is_alive():
                    error = "codex app-server subprocess exited unexpectedly"
                    break
                continue

            # Server-initiated request (approval) — has both id and method.
            if "id" in msg and "method" in msg:
                await self._handle_server_request(client, msg, emit)
                continue

            method = str(msg.get("method", ""))
            for event in project_codex_notification(msg):
                if event.kind == AgentEventKind.TOOL:
                    tool_iterations += 1
                elif event.kind == AgentEventKind.OUTPUT and event.text:
                    meta = event.data or {}
                    if not meta.get("streaming") and not meta.get("reasoning"):
                        final_text = event.text
                await emit(event)

            if method == "turn/completed":
                turn_complete = True
                turn = (msg.get("params") or {}).get("turn") or {}
                status = turn.get("status")
                if status == "interrupted":
                    interrupted = True
                elif status and status != "completed":
                    err_obj = turn.get("error")
                    error = f"codex turn ended status={status}"
                    if err_obj:
                        error = f"{error}: {err_obj}"

        return await self._finish(emit, final_text, tool_iterations, interrupted, error, turn_id)

    async def _finish(
        self,
        emit: EventCallback,
        final_text: str,
        tool_iterations: int,
        interrupted: bool,
        error: str | None,
        turn_id: str | None,
        *,
        stderr_tail: list[str] | None = None,
    ) -> AgentEvent:
        """Emit a trailing error (if any) and the terminal ``done`` event."""
        if error:
            err_data = {"stderr": stderr_tail} if stderr_tail else None
            await emit(AgentEvent(AgentEventKind.ERROR, text=error, data=err_data))
        done_data: dict[str, Any] = {
            "final_text": final_text,
            "tool_iterations": tool_iterations,
            "interrupted": interrupted,
            "error": error,
            "turn_id": turn_id,
            "thread_id": self._thread_id,
        }
        if stderr_tail:
            done_data["stderr"] = stderr_tail
        done = AgentEvent(AgentEventKind.DONE, text=final_text, data=done_data)
        await emit(done)
        return done

    async def _handle_server_request(
        self,
        client: _CodexAppServerClient,
        req: Mapping[str, Any],
        emit: EventCallback,
    ) -> None:
        """Resolve a codex-side approval request and reply with a decision."""
        req_id = req.get("id")
        method = str(req.get("method", ""))
        params = req.get("params") or {}
        decision = "approved" if self._auto_approve else "denied"
        if self._approval_callback is not None:
            try:
                outcome = self._approval_callback(method, params)
                decision = await outcome if inspect.isawaitable(outcome) else str(outcome)
            except Exception:
                decision = "denied"
        await emit(
            AgentEvent(
                AgentEventKind.TOOL,
                text=f"approval:{method}",
                data={"approval_request": method, "decision": decision, "params": params},
            )
        )
        with contextlib.suppress(Exception):
            await client.respond(req_id, {"decision": decision})

    async def _safe_interrupt(self, turn_id: str | None) -> None:
        """Best-effort ``turn/interrupt`` to stop wasted compute on abort."""
        if self._client is None:
            return
        with contextlib.suppress(Exception):
            params = {"turnId": turn_id} if turn_id else {}
            await self._client.notify("turn/interrupt", params)
