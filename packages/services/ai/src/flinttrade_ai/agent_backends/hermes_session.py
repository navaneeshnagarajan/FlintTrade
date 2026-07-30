"""Streaming Hermes ACP agent session (layer 4).

A full :class:`~flinttrade_ai.agent_backends.session.AgentSession`
implementation over the Nous Hermes agent's **Agent Client Protocol** (ACP):
JSON-RPC 2.0 over stdio, newline-delimited. FlintTrade acts as the ACP
*client*, driving a spawned ``hermes acp`` (or ``python -m acp_adapter``)
subprocess — the reference server lives in ``hermes-agent/acp_adapter/``.

It mirrors :mod:`~flinttrade_ai.agent_backends.codex_session` (the codex
app-server driver) so the two share the same robustness: a large stream limit,
a reader that survives oversized frames, honest failure on a dead reader,
drain-between-turns, and subprocess cleanup on ``close``/handshake-failure.

Lifecycle::

    session = HermesACPSession(cwd="/path/to/proj")
    await session.ensure_started()          # spawn + initialize + session/new
    done = await session.run_turn("hello", on_event)   # streams AgentEvents
    await session.close()

Protocol shape (client → agent):

* ``initialize`` — capability + version handshake.
* ``session/new`` — mints a session id (the turn thread).
* ``session/prompt`` — drives one turn; its reply arrives **at the end** of the
  turn carrying ``stopReason``. While it is outstanding the agent streams
  ``session/update`` notifications (assistant text chunks, thoughts, tool
  calls) which we project into :class:`AgentEvent`\\ s, plus server-initiated
  ``session/request_permission`` requests we answer with a decision.
* ``session/cancel`` — best-effort turn abort on timeout.

Fail closed + honest: if the Hermes entrypoint is absent (no ``hermes`` /
``hermes-acp`` on ``PATH`` and no importable ``acp_adapter`` module), or the
spawn fails,
:class:`~flinttrade_ai.agent_backends.session.AgentBackendUnavailable` is raised
with a clear install pointer. Errors during a turn become an ``error`` event
and are recorded on the terminal ``done`` event rather than bubbling raw
exceptions. ``HERMES_HOME`` is passed through to the child (the CODEX_HOME
equivalent).

Dependency-light: stdlib ``asyncio`` + ``json`` only — no ``acp`` /
``agent-client-protocol`` pip dependency.
"""

from __future__ import annotations

import asyncio
import contextlib
import importlib.util
import inspect
import json
import os
import shutil
import sys
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

# Client identity sent in the ACP initialize handshake.
_CLIENT_NAME = "flinttrade"
_CLIENT_TITLE = "FlintTrade"
_CLIENT_VERSION = "0.6.0"

# ACP protocol version we advertise. The Hermes server echoes its own supported
# version regardless, so this is the client's stated baseline.
_PROTOCOL_VERSION = 1

# Timeouts (seconds). The turn timeout bounds a single prompt→response cycle;
# the poll cadence interleaves inbound reads with liveness/deadline checks.
_DEFAULT_TURN_TIMEOUT = 600.0
_HANDSHAKE_TIMEOUT = 15.0
_NOTIFICATION_POLL = 0.25
_CLOSE_TIMEOUT = 3.0

# How many tailing stderr lines to attach to a user-facing error.
_STDERR_TAIL_LINES = 12

# Stdout/stderr StreamReader buffer cap. asyncio's default is 64 KiB, but a
# single ACP ``session/update`` frame — a large tool result inlined in a
# ``tool_call_update``, a long assistant chunk, or a big plan payload — can
# exceed that. Size the buffer generously so realistic frames fit; the reader
# additionally survives an over-limit frame by discarding it rather than dying
# (see ``_read_stdout``).
_STREAM_LIMIT = 16 * 1024 * 1024  # 16 MiB


@dataclass
class HermesACPError(RuntimeError):
    """Raised on a JSON-RPC ``error`` reply from the Hermes ACP server."""

    code: int
    message: str
    data: Any | None = None

    def __str__(self) -> str:  # pragma: no cover - trivial
        return f"hermes ACP error {self.code}: {self.message}"


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
# tests can drive the framing against a fake stdio pipe without hermes present.
SpawnFn = Callable[[Sequence[str], Mapping[str, str]], Awaitable[_ProcessLike]]

# A detection seam: returns the resolved argv for the ACP entrypoint, or None
# when no entrypoint is available. Injectable so tests exercise the fail-closed
# branch without touching ``PATH``.
DetectFn = Callable[[], list[str] | None]


async def _default_spawn(cmd: Sequence[str], env: Mapping[str, str]) -> _ProcessLike:
    """Spawn the Hermes ACP entrypoint as an asyncio subprocess over stdio."""
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


def _detect_hermes_invocation(
    hermes_bin: str = "hermes",
    acp_args: Sequence[str] = ("acp",),
    *,
    which: Callable[[str], str | None] | None = None,
    find_spec: Callable[[str], object | None] | None = None,
) -> list[str] | None:
    """Resolve the argv that launches the Hermes ACP stdio server.

    Detection order (first hit wins), mirroring the ``hermes`` profile's
    ``detect_binaries``:

    1. ``hermes`` on ``PATH`` → ``[hermes, *acp_args]`` (the ``hermes acp``
       subcommand form).
    2. ``hermes-acp`` on ``PATH`` → ``[hermes-acp]`` (the standalone binary).
    3. ``python -m acp_adapter`` — **only** when the ``acp_adapter`` module is
       importable in this interpreter. Falling back to it unconditionally would
       spawn a python that exits with an ``ImportError``, masquerading as a
       runtime failure rather than an honest "not installed".

    Args:
        hermes_bin: Primary binary name to probe (default ``"hermes"``).
        acp_args: Subcommand args appended to the primary binary.
        which: Injectable ``shutil.which`` seam (tests).
        find_spec: Injectable ``importlib.util.find_spec`` seam (tests).

    Returns:
        The resolved argv list, or ``None`` when no entrypoint is available.
    """
    which_fn = which or shutil.which
    find_spec_fn = find_spec or importlib.util.find_spec

    primary = which_fn(hermes_bin)
    if primary:
        return [primary, *acp_args]

    alias = which_fn("hermes-acp")
    if alias:
        return [alias]

    try:
        spec = find_spec_fn("acp_adapter")
    except (ImportError, ValueError):
        spec = None
    if spec is not None:
        return [sys.executable, "-m", "acp_adapter"]

    return None


# --- notification projection ----------------------------------------------


def _content_text(content: Any) -> str:
    """Extract plain text from an ACP content block (or list of blocks)."""
    if content is None:
        return ""
    if isinstance(content, str):
        return content
    if isinstance(content, Mapping):
        return str(content.get("text") or "")
    if isinstance(content, (list, tuple)):
        return "".join(_content_text(block) for block in content)
    return ""


def _is_internal_marker(msg: Mapping[str, Any]) -> bool:
    """Whether ``msg`` is an internal reader wake marker, not a wire frame."""
    return "__reply__" in msg or "__reader_stopped__" in msg


def project_acp_notification(note: Mapping[str, Any]) -> list[AgentEvent]:
    """Project one ACP ``session/update`` notification into ``AgentEvent``\\ s.

    Streaming ``agent_message_chunk`` updates become streaming ``output``
    events; ``agent_thought_chunk`` become reasoning-tagged ``output``;
    ``tool_call``/``tool_call_update`` become ``tool`` events; ``plan`` becomes
    a ``tool`` event. Echoed input and non-materialising metadata updates
    (``available_commands_update``, ``usage_update``, mode/config/info updates)
    produce no events. Pure and side-effect-free so it can be unit-tested
    directly.

    Tool ``start`` events carry ``data["phase"] == "start"`` so the turn loop
    can count distinct tool invocations without double-counting progress
    updates.

    Args:
        note: A single JSON-RPC notification dict.

    Returns:
        Zero or more :class:`AgentEvent`\\ s in emission order.
    """
    method = str(note.get("method", ""))
    if method not in ("session/update", "session_update"):
        return []

    params = note.get("params") or {}
    update = params.get("update") or {}
    disc = str(update.get("sessionUpdate") or update.get("session_update") or "")

    if disc == "agent_message_chunk":
        text = _content_text(update.get("content"))
        if not text:
            return []
        return [AgentEvent(AgentEventKind.OUTPUT, text=text, data={"streaming": True})]

    if disc == "agent_thought_chunk":
        text = _content_text(update.get("content"))
        if not text:
            return []
        return [AgentEvent(AgentEventKind.OUTPUT, text=text, data={"reasoning": True, "streaming": True})]

    if disc == "user_message_chunk":
        # Echoed input — not surfaced as a new output event.
        return []

    if disc == "tool_call":
        tool_id = str(update.get("toolCallId") or update.get("tool_call_id") or "")
        kind = update.get("kind")
        title = str(update.get("title") or kind or "tool")
        return [
            AgentEvent(
                AgentEventKind.TOOL,
                text=title,
                data={
                    "tool": str(kind or title),
                    "tool_call_id": tool_id,
                    "kind": kind,
                    "status": update.get("status"),
                    "phase": "start",
                    "raw_input": update.get("rawInput") or update.get("raw_input"),
                },
            )
        ]

    if disc == "tool_call_update":
        tool_id = str(update.get("toolCallId") or update.get("tool_call_id") or "")
        status = update.get("status")
        title = update.get("title")
        text = str(title) if title else f"tool {tool_id} {status or ''}".strip()
        return [
            AgentEvent(
                AgentEventKind.TOOL,
                text=text,
                data={"tool_call_id": tool_id, "status": status, "phase": "update"},
            )
        ]

    if disc == "plan":
        entries: list[dict[str, Any]] = []
        for entry in update.get("entries") or []:
            if isinstance(entry, Mapping):
                entries.append(
                    {
                        "content": str(entry.get("content") or ""),
                        "status": entry.get("status"),
                        "priority": entry.get("priority"),
                    }
                )
        return [
            AgentEvent(
                AgentEventKind.TOOL,
                text=f"plan ({len(entries)} step(s))",
                data={"tool": "plan", "plan": True, "phase": "update", "entries": entries},
            )
        ]

    # Non-materialising metadata updates — no turn events.
    if disc in (
        "available_commands_update",
        "current_mode_update",
        "usage_update",
        "session_info_update",
        "config_option_update",
    ):
        return []

    if not disc:
        return []

    # Unknown / rare update — record its existence without fabricating a
    # tool-call structure. Marked as an update phase so it never inflates the
    # tool-iteration count.
    return [AgentEvent(AgentEventKind.TOOL, text=f"[hermes {disc}]", data={"tool": disc, "phase": "update"})]


# --- wire-level JSON-RPC client -------------------------------------------


class _HermesACPClient:
    """Async newline-delimited JSON-RPC 2.0 client over the Hermes stdio pipes.

    One background task reads stdout, resolving reply futures and routing
    notifications + server-initiated requests onto a single inbound queue the
    session drains. A second task tails stderr for diagnostics. Because the
    ACP ``session/prompt`` reply arrives only at the end of a turn, the reader
    additionally nudges the inbound queue with a ``__reply__`` marker whenever
    it resolves a reply future so the turn loop can re-check without waiting the
    poll interval.
    """

    def __init__(
        self,
        *,
        invocation: Sequence[str],
        hermes_home: str | None = None,
        env: Mapping[str, str] | None = None,
        extra_args: Sequence[str] | None = None,
        spawn: SpawnFn | None = None,
    ) -> None:
        self._invocation = tuple(invocation)
        self._hermes_home = hermes_home
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
        """Assemble the child env: inherit, then set HERMES_HOME + overrides."""
        env = os.environ.copy()
        if self._hermes_home:
            env["HERMES_HOME"] = self._hermes_home
        env.update(self._extra_env)
        return env

    def _build_cmd(self) -> list[str]:
        return [*self._invocation, *self._extra_args]

    async def start(self) -> None:
        """Spawn the subprocess and start the reader tasks. Idempotent.

        Raises:
            AgentBackendUnavailable: if the entrypoint is absent or cannot launch.
        """
        if self._proc is not None:
            return
        cmd = self._build_cmd()
        try:
            self._proc = await self._spawn(cmd, self._build_env())
        except OSError as exc:
            # FileNotFoundError/NotADirectoryError/PermissionError and any other
            # OSError on spawn all become the honest fail-closed signal rather
            # than a raw OSError.
            raise AgentBackendUnavailable(
                "hermes",
                f"could not launch {cmd[0]!r}: install Hermes so `hermes acp` / "
                f"`hermes-acp` is available, or make the `acp_adapter` module importable",
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
            raise RuntimeError("hermes ACP client is closed")
        proc = self._proc
        if proc is None or proc.stdin is None:
            raise RuntimeError("hermes ACP stdin is unavailable")
        data = (json.dumps(obj) + "\n").encode("utf-8")
        proc.stdin.write(data)
        drain = getattr(proc.stdin, "drain", None)
        if drain is not None:
            await drain()

    async def send_request(
        self, method: str, params: dict[str, Any] | None = None
    ) -> tuple[int, asyncio.Future[dict[str, Any]]]:
        """Send a JSON-RPC request and return ``(id, reply_future)``.

        The caller awaits the future itself, which lets ``run_turn`` interleave
        the outstanding ``session/prompt`` reply with inbound notifications.

        Raises:
            RuntimeError: if the client is not started or stdin is unavailable.
        """
        if self._proc is None:
            raise RuntimeError("hermes ACP client is not started")
        rid = self._take_id()
        fut: asyncio.Future[dict[str, Any]] = asyncio.get_running_loop().create_future()
        self._pending[rid] = fut
        try:
            await self._send({"jsonrpc": "2.0", "id": rid, "method": method, "params": params or {}})
        except Exception:
            self._pending.pop(rid, None)
            raise
        return rid, fut

    async def request(
        self,
        method: str,
        params: dict[str, Any] | None = None,
        timeout: float = 30.0,
    ) -> dict[str, Any]:
        """Send a JSON-RPC request and await its reply ``result``.

        Raises:
            HermesACPError: on a JSON-RPC ``error`` reply.
            TimeoutError: if no reply arrives within ``timeout``.
        """
        rid, fut = await self.send_request(method, params)
        try:
            msg = await asyncio.wait_for(fut, timeout)
        except TimeoutError as exc:
            self._pending.pop(rid, None)
            raise TimeoutError(f"hermes ACP method {method!r} timed out after {timeout}s") from exc
        if "error" in msg:
            err = msg.get("error") or {}
            raise HermesACPError(
                code=int(err.get("code", -1)),
                message=str(err.get("message", "")),
                data=err.get("data"),
            )
        return msg.get("result") or {}

    async def notify(self, method: str, params: dict[str, Any] | None = None) -> None:
        """Send a JSON-RPC notification (no id, no reply expected)."""
        await self._send({"jsonrpc": "2.0", "method": method, "params": params or {}})

    async def respond(self, request_id: Any, result: dict[str, Any]) -> None:
        """Reply to a server-initiated request (e.g. a permission prompt)."""
        await self._send({"jsonrpc": "2.0", "id": request_id, "result": result})

    async def respond_error(self, request_id: Any, code: int, message: str) -> None:
        """Reply to a server-initiated request with a JSON-RPC error."""
        await self._send(
            {"jsonrpc": "2.0", "id": request_id, "error": {"code": int(code), "message": str(message)}}
        )

    async def initialize(
        self,
        *,
        protocol_version: int = _PROTOCOL_VERSION,
        capabilities: dict[str, Any] | None = None,
        timeout: float = _HANDSHAKE_TIMEOUT,
    ) -> dict[str, Any]:
        """Perform the ACP ``initialize`` handshake. Idempotent.

        We advertise no ``fs``/``terminal`` client capabilities (FlintTrade
        does not service filesystem/terminal round-trips), so the agent will
        not route those to us.
        """
        if self._initialized:
            return {}
        params = {
            "protocolVersion": protocol_version,
            "clientCapabilities": capabilities or {},
            "clientInfo": {
                "name": _CLIENT_NAME,
                "title": _CLIENT_TITLE,
                "version": _CLIENT_VERSION,
            },
        }
        result = await self.request("initialize", params, timeout=timeout)
        self._initialized = True
        return result

    async def new_session(
        self,
        *,
        cwd: str,
        mcp_servers: Sequence[Any] | None = None,
        timeout: float = _HANDSHAKE_TIMEOUT,
    ) -> str:
        """Create a new ACP session and return its id."""
        result = await self.request(
            "session/new",
            {"cwd": cwd, "mcpServers": list(mcp_servers or [])},
            timeout=timeout,
        )
        return str(result.get("sessionId") or result.get("session_id") or "")

    async def next_inbound(self) -> dict[str, Any]:
        """Await the next notification, server-initiated request, or marker."""
        return await self._inbound.get()

    def next_inbound_nowait(self) -> dict[str, Any] | None:
        """Return the next buffered inbound frame, or ``None`` if empty."""
        try:
            return self._inbound.get_nowait()
        except asyncio.QueueEmpty:
            return None

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
            # Nudge the turn loop so it re-checks the resolved reply future
            # without waiting out the poll interval.
            with contextlib.suppress(Exception):
                self._inbound.put_nowait({"__reply__": mid})
            return
        # Notification (no id) or server-initiated request (id + method) —
        # both go onto the inbound queue for the session to route.
        self._inbound.put_nowait(msg)

    def _fail_pending_and_wake(self, reason: str) -> None:
        """Fail every pending request future and wake the inbound consumer.

        Invoked when the stdout reader stops so a caller awaiting a reply
        future (the handshake or an outstanding ``session/prompt``) or blocked
        on :meth:`next_inbound` observes the dead reader at once, ending the
        turn honestly instead of waiting out a long timeout.
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
            self._fail_pending_and_wake("hermes ACP stdout reader stopped")

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
# decision string ("approved"/"allow" or "denied"/"reject"), sync or async.
ApprovalCallback = Callable[[str, Mapping[str, Any]], Awaitable[str] | str]


class HermesACPSession(AgentSession):
    """Streaming :class:`AgentSession` over the Hermes ACP protocol.

    Not thread-safe — one caller drives it at a time (the underlying client
    owns its own reader tasks). Owns one ACP session for its lifetime.
    """

    backend_id = "hermes"

    def __init__(
        self,
        *,
        cwd: str | None = None,
        hermes_bin: str = "hermes",
        acp_args: Sequence[str] = ("acp",),
        hermes_home: str | None = None,
        invocation: Sequence[str] | None = None,
        extra_args: Sequence[str] | None = None,
        env: Mapping[str, str] | None = None,
        spawn: SpawnFn | None = None,
        detect: DetectFn | None = None,
        approval_callback: ApprovalCallback | None = None,
        auto_approve: bool = False,
        turn_timeout: float = _DEFAULT_TURN_TIMEOUT,
        client_factory: Callable[[Sequence[str]], _HermesACPClient] | None = None,
    ) -> None:
        """Configure a Hermes ACP session.

        Args:
            cwd: Working directory for the ACP session (defaults to CWD).
            hermes_bin: Primary binary name to detect (default ``"hermes"``).
            acp_args: Subcommand args for the primary binary (``("acp",)``).
            hermes_home: Value passed through as ``HERMES_HOME`` to the child;
                defaults to the process's own ``HERMES_HOME`` if set.
            invocation: Explicit argv for the entrypoint. When given, detection
                is skipped entirely (tests supply this alongside ``spawn``).
            extra_args: Extra args appended after the resolved invocation.
            env: Extra environment overlaid on the child env.
            spawn: Injectable spawn seam (tests supply a fake stdio pipe).
            detect: Injectable detection seam returning the argv or ``None``.
            approval_callback: Optional decision maker for Hermes-side
                permission requests. Returns ``"approved"``/``"denied"``.
            auto_approve: When no callback is set, whether to approve permission
                requests. Defaults to ``False`` (fail closed).
            turn_timeout: Seconds a single turn may run before it is aborted.
            client_factory: Injectable factory for the wire client (tests).
        """
        self._cwd = cwd or os.getcwd()
        self._hermes_bin = hermes_bin
        self._acp_args = tuple(acp_args)
        self._hermes_home = hermes_home or os.environ.get("HERMES_HOME")
        self._invocation = tuple(invocation) if invocation is not None else None
        self._extra_args = list(extra_args or [])
        self._env = dict(env or {})
        self._spawn = spawn
        self._detect: DetectFn = detect or (
            lambda: _detect_hermes_invocation(self._hermes_bin, self._acp_args)
        )
        self._approval_callback = approval_callback
        self._auto_approve = auto_approve
        self._turn_timeout = turn_timeout
        self._client_factory = client_factory or self._default_client_factory
        self._client: _HermesACPClient | None = None
        self._session_id: str | None = None
        self._closed = False

    def _default_client_factory(self, invocation: Sequence[str]) -> _HermesACPClient:
        return _HermesACPClient(
            invocation=invocation,
            hermes_home=self._hermes_home,
            env=self._env,
            extra_args=self._extra_args,
            spawn=self._spawn,
        )

    def _resolve_invocation(self) -> list[str]:
        """Resolve the entrypoint argv, failing closed if none is found."""
        if self._invocation is not None:
            return list(self._invocation)
        detected = self._detect()
        if not detected:
            raise AgentBackendUnavailable(
                "hermes",
                "the Hermes ACP entrypoint was not found: install Hermes so "
                "`hermes`/`hermes-acp` is on PATH, or make the `acp_adapter` "
                "module importable",
            )
        return list(detected)

    # ---- lifecycle ----

    async def ensure_started(self) -> None:
        """Spawn Hermes, handshake, and open a session. Idempotent.

        Raises:
            AgentBackendUnavailable: if Hermes cannot be found or launched.
            HermesACPError: if the handshake or session/new fails.
        """
        if self._closed:
            raise RuntimeError("hermes ACP session is closed")
        if self._session_id is not None:
            return
        if self._client is None:
            # Detection happens before spawn so a missing entrypoint fails
            # closed early (no subprocess to leak).
            invocation = self._resolve_invocation()
            self._client = self._client_factory(invocation)
        await self._client.start()
        # start() has now spawned the child + reader tasks. If the handshake or
        # session start fails from here, close the client so the subprocess and
        # both reader tasks don't leak, then re-raise the honest error.
        try:
            await self._client.initialize()
            session_id = await self._client.new_session(cwd=self._cwd, mcp_servers=[])
            if not session_id:
                raise HermesACPError(code=-32603, message="session/new returned no session id")
        except BaseException:
            with contextlib.suppress(Exception):
                await self._client.close()
            self._client = None
            raise
        self._session_id = session_id

    async def close(self) -> None:
        """Tear down the Hermes subprocess. Idempotent."""
        if self._closed:
            return
        self._closed = True
        if self._client is not None:
            await self._client.close()
            self._client = None
        self._session_id = None

    # ---- per-turn ----

    async def run_turn(self, prompt: str, on_event: EventCallback | None = None) -> AgentEvent:
        """Send ``prompt`` and stream the turn's events via ``on_event``.

        Sends ``session/prompt`` and consumes ``session/update`` notifications
        and server-initiated permission requests until the prompt reply arrives
        (carrying ``stopReason``), or a timeout / dead subprocess ends the turn.
        Returns the terminal ``done`` event, whose ``data`` carries the
        aggregated summary. Always ends with a ``done`` event, even on error.
        """
        await self.ensure_started()
        assert self._client is not None and self._session_id is not None
        client = self._client
        session_id = self._session_id
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
        stop_reason: str | None = None

        async def consume(msg: Mapping[str, Any]) -> None:
            nonlocal final_text, tool_iterations
            for event in project_acp_notification(msg):
                if event.kind == AgentEventKind.TOOL:
                    if (event.data or {}).get("phase") == "start":
                        tool_iterations += 1
                elif event.kind == AgentEventKind.OUTPUT and event.text:
                    if not (event.data or {}).get("reasoning"):
                        final_text += event.text
                await emit(event)

        try:
            _rid, prompt_future = await client.send_request(
                "session/prompt",
                {"sessionId": session_id, "prompt": [{"type": "text", "text": str(prompt)}]},
            )
        except RuntimeError as exc:
            # Stdin already closed or the client not started — surface honestly
            # as a single error event, not a raw raise.
            error = f"session/prompt send failed: {exc}"
            return await self._finish(
                emit, final_text, tool_iterations, interrupted, error, stop_reason,
                stderr_tail=client.stderr_tail(),
            )

        loop = asyncio.get_running_loop()
        deadline = loop.time() + self._turn_timeout
        turn_complete = False

        while not turn_complete:
            if prompt_future.done():
                turn_complete = True
                try:
                    # The future carries the full JSON-RPC reply frame
                    # ({"id", "result"|"error"}); a dead reader fails it with
                    # RuntimeError instead.
                    reply = prompt_future.result()
                except Exception as exc:
                    error = f"session/prompt failed: {exc}"
                    break
                # Drain and project any notifications that landed alongside the
                # reply so a final assistant chunk is never dropped.
                while True:
                    pending = client.next_inbound_nowait()
                    if pending is None:
                        break
                    if _is_internal_marker(pending):
                        continue
                    if "id" in pending and "method" in pending:
                        await self._handle_server_request(client, pending, emit)
                        continue
                    await consume(pending)
                if "error" in reply:
                    err = reply.get("error") or {}
                    error = (
                        f"session/prompt failed: hermes ACP error "
                        f"{int(err.get('code', -1))}: {err.get('message', '')}"
                    )
                    break
                result = reply.get("result") or {}
                stop_reason = str(result.get("stopReason") or result.get("stop_reason") or "")
                if stop_reason in ("cancelled", "canceled"):
                    interrupted = True
                elif stop_reason == "refusal":
                    error = "hermes refused the prompt (stopReason=refusal)"
                break

            remaining = deadline - loop.time()
            if remaining <= 0:
                error = f"hermes ACP turn timed out after {self._turn_timeout:.0f}s"
                await self._safe_cancel(session_id)
                interrupted = True
                break

            try:
                msg = await asyncio.wait_for(
                    client.next_inbound(), timeout=min(_NOTIFICATION_POLL, remaining)
                )
            except TimeoutError:
                if not client.is_alive() and not prompt_future.done():
                    error = "hermes ACP subprocess exited unexpectedly"
                    break
                continue

            if _is_internal_marker(msg):
                # A reply landed or the reader stopped — loop back to re-check
                # the prompt future / liveness immediately.
                continue

            # Server-initiated request (permission) — has both id and method.
            if "id" in msg and "method" in msg:
                await self._handle_server_request(client, msg, emit)
                continue

            await consume(msg)

        return await self._finish(emit, final_text, tool_iterations, interrupted, error, stop_reason)

    async def _finish(
        self,
        emit: EventCallback,
        final_text: str,
        tool_iterations: int,
        interrupted: bool,
        error: str | None,
        stop_reason: str | None,
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
            "stop_reason": stop_reason,
            "session_id": self._session_id,
        }
        if stderr_tail:
            done_data["stderr"] = stderr_tail
        done = AgentEvent(AgentEventKind.DONE, text=final_text, data=done_data)
        await emit(done)
        return done

    async def _handle_server_request(
        self,
        client: _HermesACPClient,
        req: Mapping[str, Any],
        emit: EventCallback,
    ) -> None:
        """Resolve a Hermes-side server request (permission / fs / terminal)."""
        req_id = req.get("id")
        method = str(req.get("method", ""))
        params = req.get("params") or {}

        if method in ("session/request_permission", "request_permission"):
            decision = "approved" if self._auto_approve else "denied"
            if self._approval_callback is not None:
                try:
                    outcome = self._approval_callback(method, params)
                    decision = await outcome if inspect.isawaitable(outcome) else str(outcome)
                except Exception:
                    decision = "denied"
            response = self._build_permission_response(params, decision)
            await emit(
                AgentEvent(
                    AgentEventKind.TOOL,
                    text=f"approval:{method}",
                    data={"approval_request": method, "decision": decision, "params": params},
                )
            )
            with contextlib.suppress(Exception):
                await client.respond(req_id, response)
            return

        # Unhandled server request (fs/*, terminal/*): we advertised no such
        # capability. Reply with method-not-found so the agent's pending request
        # resolves instead of hanging, and note it as a tool event.
        await emit(
            AgentEvent(
                AgentEventKind.TOOL,
                text=f"[hermes unsupported request {method}]",
                data={"unsupported_request": method, "phase": "update"},
            )
        )
        with contextlib.suppress(Exception):
            await client.respond_error(
                req_id, -32601, f"method {method!r} not supported by FlintTrade ACP client"
            )

    @staticmethod
    def _build_permission_response(params: Mapping[str, Any], decision: str) -> dict[str, Any]:
        """Map an approve/deny decision onto an ACP permission option id."""
        approve = str(decision).strip().lower() in (
            "approved",
            "approve",
            "allow",
            "allow_once",
            "allow_always",
            "yes",
            "true",
        )
        preferred = ("allow_once", "allow_always") if approve else ("reject_once", "reject_always")
        options = params.get("options") or []
        for kind in preferred:
            for opt in options:
                if isinstance(opt, Mapping) and opt.get("kind") == kind:
                    option_id = opt.get("optionId") or opt.get("option_id")
                    if option_id is not None:
                        return {"outcome": {"outcome": "selected", "optionId": str(option_id)}}
        # No matching option offered — cancel the request (fail closed).
        return {"outcome": {"outcome": "cancelled"}}

    async def _safe_cancel(self, session_id: str) -> None:
        """Best-effort ``session/cancel`` to stop wasted compute on abort."""
        if self._client is None:
            return
        with contextlib.suppress(Exception):
            await self._client.notify("session/cancel", {"sessionId": session_id})
