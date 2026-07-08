"""Streaming Antigravity (``agy``) CLI session (layer 4).

A full :class:`~flinttrade_ai.agent_backends.session.AgentSession`
implementation over Google's Antigravity CLI (``agy``). Unlike Codex's
structured ``app-server`` (a long-lived newline-delimited JSON-RPC 2.0 process),
``agy`` is a plain coding-agent CLI with **no persistent server surface**: its
non-interactive one-shot form ``agy -p '<prompt>'`` runs the prompt to
completion and then exits, emitting **plain text** on stdout (no
``--output-format json``, no result envelope — see the Hermes ``antigravity-cli``
skill's ``references/cli-docs.md``).

Design choice (honest, for how ``agy`` actually runs): **spawn one subprocess
per turn.** ``ensure_started`` performs a cheap, fail-closed readiness probe
(is ``agy`` on ``PATH``?) but does *not* hold a process open, because there is
nothing to keep alive between prompts. :meth:`AntigravitySession.run_turn`
spawns a fresh ``agy -p <prompt>``, streams its stdout line-by-line as
``output`` events (stderr is surfaced as distinct diagnostic ``output`` events
tagged ``data.stream == "stderr"``), and ends with a ``done`` event carrying the
child's exit code. A non-zero exit becomes an ``error`` event plus a ``done``
recording the code.

Lifecycle::

    session = AntigravitySession(cwd="/path/to/proj")
    await session.ensure_started()          # fail-closed PATH probe (idempotent)
    done = await session.run_turn("hello", on_event)   # spawns agy, streams
    await session.close()

Fail closed + honest: if the ``agy`` binary is absent (PATH probe or spawn
fails) :class:`~flinttrade_ai.agent_backends.session.AgentBackendUnavailable`
is raised with a clear install pointer. Antigravity **manages its own auth**
(OS keyring / browser Google sign-in), so this session never injects or
requires an API key or env token.

Robustness mirrors :mod:`~flinttrade_ai.agent_backends.codex_session`: a large
stdout/stderr :class:`asyncio.StreamReader` buffer, a reader that survives an
over-limit line by discarding it (never dies, so the child cannot deadlock on
stdout backpressure), a poll-based read loop bounded by the turn timeout (no
hang if the child stalls), and subprocess + reader-task cleanup on close.

Dependency-light: stdlib ``asyncio`` + ``subprocess`` only.
"""

from __future__ import annotations

import asyncio
import contextlib
import os
import shutil
from collections.abc import Awaitable, Callable, Mapping, Sequence
from typing import Any, Protocol

from flinttrade_ai.agent_backends.session import (
    AgentBackendUnavailable,
    AgentEvent,
    AgentEventKind,
    AgentSession,
    EventCallback,
)

# Timeouts (seconds). The turn timeout bounds a single ``agy -p`` run; the poll
# cadence interleaves inbound line reads with the deadline check so a stalled
# child is aborted rather than hanging forever.
_DEFAULT_TURN_TIMEOUT = 600.0
_POLL_INTERVAL = 0.25
_CLOSE_TIMEOUT = 3.0

# How many tailing stderr lines to attach to a user-facing error / done summary.
_STDERR_TAIL_LINES = 12
# Hard cap on retained stderr lines so a chatty child cannot grow memory without
# bound over a long turn.
_MAX_STDERR_LINES = 500

# Stdout/stderr StreamReader buffer cap. asyncio's default is 64 KiB, but a
# single ``agy`` output line — a big diff, a pasted file, a long reasoning
# paragraph — can exceed that. Size the buffer generously; the reader
# additionally survives an over-limit line by discarding it rather than dying
# (see ``_pump``). Mirrors the Codex session's 16 MiB cap.
_STREAM_LIMIT = 16 * 1024 * 1024  # 16 MiB


class _ProcessLike(Protocol):
    """The subprocess surface this session needs (asyncio.subprocess.Process)."""

    stdout: Any
    stderr: Any
    returncode: int | None

    def terminate(self) -> None: ...

    def kill(self) -> None: ...

    async def wait(self) -> int: ...


# A spawn seam: given argv + env + cwd, produce a running process. Injectable so
# tests can drive a fake ``agy`` (stdout lines then exit) without agy installed.
SpawnFn = Callable[[Sequence[str], Mapping[str, str], str | None], Awaitable[_ProcessLike]]

# A ``PATH`` lookup seam (defaults to ``shutil.which``). Injectable for tests.
WhichFn = Callable[[str], str | None]


async def _default_spawn(cmd: Sequence[str], env: Mapping[str, str], cwd: str | None) -> _ProcessLike:
    """Spawn ``agy`` as an asyncio subprocess with piped stdout/stderr.

    stdin is closed (``DEVNULL``) so a non-interactive one-shot never blocks
    waiting on a TTY. The prompt is passed as an argv element (no shell), so
    there is no shell-injection surface.
    """
    return await asyncio.create_subprocess_exec(
        *cmd,
        stdin=asyncio.subprocess.DEVNULL,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
        env=dict(env),
        cwd=cwd,
        # Raise the per-line StreamReader cap well above the 64 KiB default so a
        # large single output line doesn't overrun the buffer mid-turn.
        limit=_STREAM_LIMIT,
    )


class AntigravitySession(AgentSession):
    """Streaming :class:`AgentSession` over the Antigravity ``agy`` CLI.

    One session may be reused for many turns; each turn spawns its own
    ``agy -p`` subprocess (``agy`` has no persistent server to hold open). Not
    thread-safe — one caller drives it at a time.
    """

    backend_id = "antigravity"

    def __init__(
        self,
        *,
        cwd: str | None = None,
        agy_bin: str = "agy",
        print_flag: str = "-p",
        model: str | None = None,
        print_timeout: str | None = None,
        add_dirs: Sequence[str] | None = None,
        sandbox: bool = False,
        dangerously_skip_permissions: bool = False,
        extra_args: Sequence[str] | None = None,
        env: Mapping[str, str] | None = None,
        spawn: SpawnFn | None = None,
        which: WhichFn | None = None,
        turn_timeout: float = _DEFAULT_TURN_TIMEOUT,
    ) -> None:
        """Configure an Antigravity session.

        Args:
            cwd: Working directory ``agy`` is launched in (defaults to CWD).
                Antigravity's workspace identity depends on the launch
                directory, so this scopes the run to a project.
            agy_bin: The Antigravity binary name/path (default ``"agy"``).
            print_flag: The non-interactive one-shot flag (``"-p"`` /
                ``"--print"``). ``agy`` runs the prompt and exits.
            model: Optional engine display string passed via ``--model`` (e.g.
                ``"Gemini 3.1 Pro (High)"``); run ``agy models`` for exact
                strings. ``None`` uses ``agy``'s default model.
            print_timeout: Optional ``--print-timeout`` value (e.g. ``"20m"``)
                handed to ``agy`` to self-bound the run. When ``None`` only this
                session's ``turn_timeout`` bounds the run (the child is killed
                on deadline).
            add_dirs: Extra context roots, each passed as a repeatable
                ``--add-dir``.
            sandbox: Pass ``--sandbox`` to run under Antigravity's sandbox.
            dangerously_skip_permissions: Pass
                ``--dangerously-skip-permissions`` for unattended runs. Defaults
                ``False`` (fail safe); an operator opts in explicitly.
            extra_args: Extra args appended verbatim after the built argv.
            env: Extra environment overlaid on the inherited child env. No API
                key is ever injected — Antigravity owns its own auth.
            spawn: Injectable spawn seam (tests supply a fake ``agy``).
            which: Injectable ``PATH`` lookup for the readiness probe (defaults
                to :func:`shutil.which` unless a custom ``spawn`` is injected,
                in which case the probe trusts the seam).
            turn_timeout: Seconds a single turn may run before it is aborted and
                the child killed.
        """
        self._cwd = cwd or os.getcwd()
        self._agy_bin = agy_bin
        self._print_flag = print_flag
        self._model = model
        self._print_timeout = print_timeout
        self._add_dirs = list(add_dirs or [])
        self._sandbox = sandbox
        self._skip_permissions = dangerously_skip_permissions
        self._extra_args = list(extra_args or [])
        self._env = dict(env or {})
        self._spawn: SpawnFn = spawn or _default_spawn
        self._custom_spawn = spawn is not None
        self._which = which
        self._turn_timeout = turn_timeout
        self._started = False
        self._closed = False
        # Tracked only while a turn is in flight so ``close`` can reap them.
        self._current_proc: _ProcessLike | None = None
        self._current_pumps: list[asyncio.Task[None]] = []

    # ---- helpers ----

    def _build_env(self) -> dict[str, str]:
        """Assemble the child env: inherit the process env, overlay extras.

        Deliberately injects **no** credentials — ``agy`` authenticates itself
        via the OS keyring / browser sign-in.
        """
        env = os.environ.copy()
        env.update(self._env)
        return env

    def _build_cmd(self, prompt: str) -> list[str]:
        """Build the ``agy`` argv for one non-interactive prompt run."""
        cmd = [self._agy_bin, self._print_flag, str(prompt)]
        if self._model:
            cmd += ["--model", self._model]
        if self._print_timeout:
            cmd += ["--print-timeout", self._print_timeout]
        for directory in self._add_dirs:
            cmd += ["--add-dir", directory]
        if self._sandbox:
            cmd += ["--sandbox"]
        if self._skip_permissions:
            cmd += ["--dangerously-skip-permissions"]
        cmd += self._extra_args
        return cmd

    # ---- lifecycle ----

    async def ensure_started(self) -> None:
        """Probe that ``agy`` is available (fail closed). Idempotent.

        ``agy`` is one-shot, so there is no persistent process to spawn here —
        this only resolves the binary on ``PATH`` so an absent CLI fails fast
        and honestly rather than surprising the first turn. When a custom
        ``spawn`` seam is injected (tests), the probe trusts it.

        Raises:
            AgentBackendUnavailable: if the ``agy`` binary is not found.
        """
        if self._closed:
            raise RuntimeError("antigravity session is closed")
        if self._started:
            return
        which = self._which
        if which is None and not self._custom_spawn:
            which = shutil.which
        if which is not None and which(self._agy_bin) is None:
            raise AgentBackendUnavailable(
                "antigravity",
                f"the Antigravity CLI ({self._agy_bin!r}) was not found on PATH: "
                f"install it from https://antigravity.google/cli and sign in with `agy` "
                f"(it manages its own auth)",
            )
        self._started = True

    async def close(self) -> None:
        """Tear down any in-flight child + reader tasks. Idempotent."""
        if self._closed:
            return
        self._closed = True
        proc = self._current_proc
        pumps = self._current_pumps
        self._current_proc = None
        self._current_pumps = []
        await self._cleanup_turn(proc, pumps)

    # ---- per-turn ----

    async def run_turn(self, prompt: str, on_event: EventCallback | None = None) -> AgentEvent:
        """Spawn ``agy -p <prompt>`` and stream its output via ``on_event``.

        Streams each stdout line as an ``output`` event and each stderr line as
        a distinct diagnostic ``output`` event (``data.stream == "stderr"``),
        bounded by ``turn_timeout``. Ends with the terminal ``done`` event whose
        ``data`` carries the child exit code and aggregated text.

        Raises:
            AgentBackendUnavailable: if ``agy`` cannot be spawned (absent CLI).
        """
        await self.ensure_started()

        async def emit(event: AgentEvent) -> None:
            if on_event is not None:
                await on_event(event)

        cmd = self._build_cmd(prompt)
        try:
            proc = await self._spawn(cmd, self._build_env(), self._cwd)
        except OSError as exc:
            # FileNotFoundError / PermissionError / exec-format and any other
            # OSError on spawn become the honest fail-closed signal.
            raise AgentBackendUnavailable(
                "antigravity",
                f"could not launch {self._agy_bin!r}: install the Antigravity CLI "
                f"(https://antigravity.google/cli)",
                cause=exc,
            ) from exc

        self._current_proc = proc
        queue: asyncio.Queue[tuple[str, str] | None] = asyncio.Queue()
        pumps = [
            asyncio.ensure_future(self._pump(proc.stdout, "stdout", queue)),
            asyncio.ensure_future(self._pump(proc.stderr, "stderr", queue)),
        ]
        self._current_pumps = pumps

        stdout_lines: list[str] = []
        stderr_tail: list[str] = []
        interrupted = False
        error: str | None = None

        try:
            loop = asyncio.get_running_loop()
            deadline = loop.time() + self._turn_timeout
            eofs = 0
            # Two pumps → two ``None`` sentinels mark both streams at EOF.
            while eofs < 2:
                remaining = deadline - loop.time()
                if remaining <= 0:
                    error = f"antigravity turn timed out after {self._turn_timeout:.0f}s"
                    interrupted = True
                    break
                try:
                    item = await asyncio.wait_for(queue.get(), timeout=min(_POLL_INTERVAL, remaining))
                except (asyncio.TimeoutError, TimeoutError):
                    # No line this tick; loop re-checks the deadline. A stalled
                    # child is thus bounded by turn_timeout, never an infinite wait.
                    continue
                if item is None:
                    eofs += 1
                    continue
                stream, text = item
                if stream == "stdout":
                    stdout_lines.append(text)
                    if text.strip():
                        await emit(AgentEvent(AgentEventKind.OUTPUT, text=text, data={"stream": "stdout"}))
                elif stream == "stderr":
                    stderr_tail.append(text)
                    if len(stderr_tail) > _MAX_STDERR_LINES:
                        stderr_tail = stderr_tail[-_MAX_STDERR_LINES:]
                    if text.strip():
                        await emit(
                            AgentEvent(
                                AgentEventKind.OUTPUT,
                                text=text,
                                data={"stream": "stderr", "diagnostic": True},
                            )
                        )
                else:  # "diag" — a discarded over-limit line; keep as diagnostics only.
                    stderr_tail.append(text)
                    if len(stderr_tail) > _MAX_STDERR_LINES:
                        stderr_tail = stderr_tail[-_MAX_STDERR_LINES:]

            # Reap the child to learn its exit code (unless we timed out, in
            # which case the finally kills it and the code stays unknown).
            if not interrupted:
                with contextlib.suppress(asyncio.TimeoutError, TimeoutError):
                    await asyncio.wait_for(proc.wait(), _CLOSE_TIMEOUT)
            exit_code = proc.returncode
        finally:
            await self._cleanup_turn(proc, pumps)
            self._current_proc = None
            self._current_pumps = []

        if error is None and not interrupted:
            if exit_code is None:
                error = "antigravity subprocess did not report an exit code"
            elif exit_code != 0:
                error = f"agy exited with code {exit_code}"

        return await self._finish(
            emit,
            final_text="\n".join(stdout_lines).strip(),
            exit_code=exit_code,
            interrupted=interrupted,
            error=error,
            stderr_tail=stderr_tail,
        )

    async def _pump(self, reader: Any, stream: str, queue: asyncio.Queue[tuple[str, str] | None]) -> None:
        """Read one stream line-by-line onto ``queue``; emit a ``None`` at EOF.

        Survives an over-limit line: :meth:`asyncio.StreamReader.readline`
        raises (``ValueError`` / ``LimitOverrunError``) but has already drained
        the oversized bytes, so the line is discarded (recorded as a ``diag``
        note) and reading continues. Never returning early on an oversized line
        is what stops the child deadlocking on stdout backpressure and the turn
        hanging to its full timeout.
        """
        try:
            if reader is None:
                return
            while True:
                try:
                    raw = await reader.readline()
                except (ValueError, asyncio.LimitOverrunError):
                    queue.put_nowait(("diag", f"<{stream} line over buffer limit; discarded>"))
                    continue
                if not raw:
                    break
                text = raw.decode("utf-8", "replace").rstrip("\r\n")
                queue.put_nowait((stream, text))
        except asyncio.CancelledError:
            raise
        except Exception as exc:  # pragma: no cover - defensive
            with contextlib.suppress(Exception):
                queue.put_nowait(("diag", f"<{stream} reader error> {exc}"))
        finally:
            queue.put_nowait(None)

    async def _cleanup_turn(self, proc: _ProcessLike | None, pumps: Sequence[asyncio.Task[None]]) -> None:
        """Cancel reader tasks and terminate the child if still alive."""
        for task in pumps:
            task.cancel()
        for task in pumps:
            with contextlib.suppress(asyncio.CancelledError, Exception):
                await task
        if proc is not None and proc.returncode is None:
            with contextlib.suppress(Exception):
                proc.terminate()
            try:
                await asyncio.wait_for(proc.wait(), _CLOSE_TIMEOUT)
            except Exception:
                with contextlib.suppress(Exception):
                    proc.kill()
                    await asyncio.wait_for(proc.wait(), 1.0)

    async def _finish(
        self,
        emit: EventCallback,
        *,
        final_text: str,
        exit_code: int | None,
        interrupted: bool,
        error: str | None,
        stderr_tail: list[str],
    ) -> AgentEvent:
        """Emit a trailing error (if any) and the terminal ``done`` event."""
        tail = stderr_tail[-_STDERR_TAIL_LINES:] if stderr_tail else None
        if error:
            err_data = {"stderr": tail} if tail else None
            await emit(AgentEvent(AgentEventKind.ERROR, text=error, data=err_data))
        done_data: dict[str, Any] = {
            "final_text": final_text,
            "exit_code": exit_code,
            "interrupted": interrupted,
            "error": error,
            # ``agy -p`` is plain text with no structured tool envelope, so tool
            # activity is not machine-identifiable — reported honestly as 0.
            "tool_iterations": 0,
        }
        if tail:
            done_data["stderr"] = tail
        done = AgentEvent(AgentEventKind.DONE, text=final_text, data=done_data)
        await emit(done)
        return done
