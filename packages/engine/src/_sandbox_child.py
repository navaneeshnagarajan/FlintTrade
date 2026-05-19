"""Sandbox child-process entry point.

Run as ``python -I -S -m packages.engine.src._sandbox_child``. Reads a
single pickled payload from stdin, executes the strategy source code in
the in-process sandbox (the same AST validator + restricted namespace
the parent uses), and emits a length-prefixed JSON result frame on
stdout.

Critical design properties:

- **No pickle on stdout.** The parent will ONLY ``json.loads`` from us.
  A hostile child cannot send a ``__reduce__`` payload that would run
  in the parent — we ship plain JSON only. Pickle on stdin is fine
  because the parent is the trusted side writing into us.
- **Length prefix on stdout.** 8-byte big-endian unsigned integer
  followed by exactly that many UTF-8 JSON bytes. The parent reads
  exactly the prefix it advertises, so a hostile child can't desync
  the stream by emitting extra bytes (those go to stderr instead, which
  the parent only captures into a truncated diagnostic field).
- **POSIX resource limits applied here**, before ``exec()`` runs. The
  parent applies the Windows Job Object equivalent on its side.
- **Isolated interpreter (``-I -S``):** ignores ``PYTHON*`` env vars,
  skips ``site.py``, omits ``sys.path[0]``. The child still imports
  the FlintTrade package because it's installed editable in the venv,
  but it cannot pick up arbitrary user-supplied paths.

Failure modes:

- Parent never reads our stdin: we hang on ``sys.stdin.buffer.read()``.
  The parent's wall-clock timeout kills us via SIGKILL/TerminateProcess.
- We raise before writing: parent sees an empty stdout, treats it as
  ``SandboxCrash`` with stderr tail.
- We hit a memory limit: ``MemoryError`` is caught and reported as a
  normal ExecutionResult error, NOT a crash, so the parent gets a
  structured response instead of "the child died mysteriously".

This module MUST NOT import anything from the wider FlintTrade engine
that could trigger heavy initialization (DB connections, schedulers,
event buses, etc.). The only safe import is the leaf
``sandbox_executor`` module — which is hardened to be import-safe.
"""

from __future__ import annotations

import json
import pickle
import struct
import sys
import traceback


# Memory + CPU limits as soft signals — exceeding triggers MemoryError
# inside the child's exec() rather than a SIGKILL with no diagnostic.
_DEFAULT_MEMORY_LIMIT_BYTES = 256 * 1024 * 1024  # 256 MiB
_DEFAULT_CPU_SECONDS = 60  # 2x the wall-clock cap as a safety net
_DEFAULT_NOFILE = 64
_STDOUT_CAP_BYTES = 1 * 1024 * 1024  # 1 MiB cap on captured stdout


def _apply_rlimits(memory_limit_bytes: int) -> None:
    """Apply POSIX rlimits. Silent no-op on Windows (no resource module).

    Sets AS (address space), CPU, NOFILE, and FSIZE so the strategy
    cannot exhaust memory, burn CPU forever, open arbitrarily many
    file descriptors, or fill the filesystem. Each ``setrlimit`` is
    independently best-effort; if one fails (kernel restriction, etc.)
    we log to stderr and continue with whatever limits did stick.
    """
    try:
        import resource  # type: ignore[import]
    except ImportError:
        # Windows path — the parent applies Job Object limits.
        return

    for which, soft, hard, label in (
        (resource.RLIMIT_AS, memory_limit_bytes, memory_limit_bytes, "AS"),
        (resource.RLIMIT_CPU, _DEFAULT_CPU_SECONDS, _DEFAULT_CPU_SECONDS, "CPU"),
        (resource.RLIMIT_NOFILE, _DEFAULT_NOFILE, _DEFAULT_NOFILE, "NOFILE"),
        # FSIZE=0 → strategy cannot create or extend any file on disk.
        (resource.RLIMIT_FSIZE, 0, 0, "FSIZE"),
    ):
        try:
            resource.setrlimit(which, (soft, hard))
        except (ValueError, OSError) as exc:
            print(
                f"[_sandbox_child] could not apply RLIMIT_{label}: {exc}",
                file=sys.stderr,
            )


def main() -> None:
    """Read pickle from stdin, exec strategy, write length-prefixed JSON to stdout."""
    try:
        raw = sys.stdin.buffer.read()
        if not raw:
            _emit_error("EmptyPayloadError", "Child received empty stdin", "")
            sys.exit(2)
        payload = pickle.loads(raw)
    except pickle.UnpicklingError as exc:
        _emit_error(
            "UnpicklingError",
            f"Parent payload could not be unpickled: {exc}",
            traceback.format_exc(),
        )
        sys.exit(2)
    except Exception as exc:
        _emit_error("ChildBootstrapError", str(exc), traceback.format_exc())
        sys.exit(2)

    source: str = str(payload.get("source", ""))
    context: dict = dict(payload.get("context") or {})
    memory_limit: int = int(payload.get("memory_limit", _DEFAULT_MEMORY_LIMIT_BYTES))

    _apply_rlimits(memory_limit)

    # Import the executor module AFTER applying rlimits so allocation
    # for the import itself counts against the limit.
    try:
        from packages.engine.src import sandbox_executor as se
    except Exception as exc:
        _emit_error("ImportError", str(exc), traceback.format_exc())
        sys.exit(2)

    # Run via the in-process helper that performs AST validation + exec.
    # This is the SAME code path the legacy in-thread executor uses; the
    # subprocess boundary is the additional layer of isolation.
    try:
        result_dict = se._execute_in_process(  # noqa: SLF001 — internal helper
            source_code=source,
            context=context,
        )
    except Exception as exc:
        _emit_error("ExecutorError", str(exc), traceback.format_exc())
        sys.exit(2)

    # Truncate stdout if a hostile strategy produced megabytes of print() output.
    stdout_str = str(result_dict.get("stdout", ""))
    if len(stdout_str) > _STDOUT_CAP_BYTES:
        result_dict["stdout"] = (
            stdout_str[:_STDOUT_CAP_BYTES] + "\n…[truncated]"
        )

    _emit_result(result_dict)
    sys.exit(0)


def _emit_result(result_dict: dict) -> None:
    """Write the result as JSON with an 8-byte big-endian length prefix."""
    body = json.dumps(result_dict).encode("utf-8")
    sys.stdout.buffer.write(struct.pack(">Q", len(body)))
    sys.stdout.buffer.write(body)
    sys.stdout.buffer.flush()


def _emit_error(error_type: str, error: str, tb: str) -> None:
    """Emit a structured error result rather than a raw exception."""
    # Forward the traceback to stderr so the parent can stash it for
    # debugging (parent will truncate to 4 KiB). Never put the
    # traceback in the JSON body — keeps the protocol stable and avoids
    # leaking internal paths to the strategy author.
    if tb:
        print(tb, file=sys.stderr)
    _emit_result({
        "success": False,
        "signals": [],
        "stdout": "",
        "error": error,
        "error_type": error_type,
        "timed_out": False,
    })


if __name__ == "__main__":
    main()
