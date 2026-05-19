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
_DEFAULT_CPU_HEADROOM_SECONDS = 30  # added to the caller's timeout
_DEFAULT_NOFILE = 64
_STDOUT_CAP_BYTES = 1 * 1024 * 1024  # 1 MiB cap on captured stdout


def _apply_rlimits(memory_limit_bytes: int, timeout_seconds: int) -> None:
    """Apply POSIX rlimits. Silent no-op on Windows (no resource module).

    Sets AS (address space), CPU, NOFILE, and FSIZE so the strategy
    cannot exhaust memory, burn CPU forever, open arbitrarily many
    file descriptors, or fill the filesystem. Each ``setrlimit`` is
    independently best-effort; if one fails (kernel restriction, etc.)
    we log to stderr and continue with whatever limits did stick.

    The CPU limit is derived from the caller's wall-clock timeout plus
    a headroom of ``_DEFAULT_CPU_HEADROOM_SECONDS`` so that legitimate
    long-running strategies (e.g. a 120 s walk-forward backtest cell)
    don't get killed by the kernel before the parent's wall-clock kill
    has a chance to fire and surface a clean ``TimeoutError`` instead
    of a ``SandboxCrash``.
    """
    try:
        import resource  # type: ignore[import]
    except ImportError:
        # Windows path — the parent applies Job Object limits.
        return

    cpu_limit = max(int(timeout_seconds) + _DEFAULT_CPU_HEADROOM_SECONDS, 10)

    for which, soft, hard, label in (
        (resource.RLIMIT_AS, memory_limit_bytes, memory_limit_bytes, "AS"),
        (resource.RLIMIT_CPU, cpu_limit, cpu_limit, "CPU"),
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


def _load_executor_module():
    """Load ``sandbox_executor.py`` from the directory this file lives in.

    Returns the loaded module, or ``None`` after emitting an error frame
    if the load fails for any reason. Using
    ``importlib.util.spec_from_file_location`` means the child does not
    care whether it was invoked from the source checkout
    (``packages.engine.src._sandbox_child``) or from an installed wheel
    (``flint_engine._sandbox_child``) — it simply loads the sibling
    file by absolute path. The module is registered in
    ``sys.modules`` under a private name (``_flinttrade_sandbox_exec``)
    so any internal lookups via ``__name__`` continue to work.
    """
    import importlib.util
    import os as _os

    exec_path = _os.path.join(
        _os.path.dirname(_os.path.abspath(__file__)),
        "sandbox_executor.py",
    )
    if not _os.path.isfile(exec_path):
        _emit_error(
            "SandboxBootstrapError",
            f"sandbox_executor.py not found next to _sandbox_child.py at {exec_path}",
            "",
        )
        return None

    try:
        spec = importlib.util.spec_from_file_location(
            "_flinttrade_sandbox_exec", exec_path,
        )
        if spec is None or spec.loader is None:
            raise ImportError(f"Could not build spec for {exec_path}")
        module = importlib.util.module_from_spec(spec)
        sys.modules[spec.name] = module
        spec.loader.exec_module(module)
        return module
    except Exception as exc:
        _emit_error("SandboxBootstrapError", str(exc), traceback.format_exc())
        return None


def _json_safe(obj):
    """Recursively coerce a value into a JSON-serialisable shape.

    The strategy namespace includes ``datetime``, ``date``, ``timedelta``,
    ``timezone`` (see ``_ALLOWED_MODULES``), so a perfectly legitimate
    strategy can attach a datetime to signal metadata via e.g.
    ``long_entry(price=1.0, at=datetime.now())``. Without coercion,
    ``json.dumps(result_dict)`` raises ``TypeError`` and the child
    exits without a result frame, so the parent reports ``SandboxCrash``
    even though the strategy was well-formed and produced a valid
    signal. Coerce to a JSON-safe shape instead.

    Handled conversions (best-effort):
    - ``datetime``, ``date``, ``time`` → ``isoformat()``
    - ``timedelta`` → total seconds (float)
    - ``set``, ``frozenset``, ``tuple`` → list
    - bytes → ``decode("utf-8", errors="replace")``
    - anything else → ``str(obj)`` as a last-resort fallback so the
      JSON encoder never raises.
    """
    import datetime as _dt
    if isinstance(obj, (str, int, float, bool)) or obj is None:
        return obj
    if isinstance(obj, dict):
        return {str(k): _json_safe(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple, set, frozenset)):
        return [_json_safe(v) for v in obj]
    if isinstance(obj, (_dt.datetime, _dt.date, _dt.time)):
        return obj.isoformat()
    if isinstance(obj, _dt.timedelta):
        return obj.total_seconds()
    if isinstance(obj, bytes):
        return obj.decode("utf-8", errors="replace")
    # Last resort — repr keeps the value visible in the result without
    # raising. Strategy authors who want structured metadata should
    # use plain dicts/lists/primitives.
    try:
        return str(obj)
    except Exception:
        return f"<unserialisable {type(obj).__name__}>"


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
    timeout_seconds: int = int(payload.get("timeout", 30))

    _apply_rlimits(memory_limit, timeout_seconds)

    # Load sandbox_executor.py from THIS module's directory regardless
    # of how the child was spawned. The previous version did
    # ``from packages.engine.src import sandbox_executor`` which only
    # resolves in the source checkout — once ``flint-engine`` is
    # installed from its wheel (which maps ``src/`` to ``flint_engine``
    # per packages/engine/pyproject.toml), the ``packages.engine.src``
    # dotted name doesn't exist and the child crashed with ImportError
    # on every single sandbox call. Loading the sibling file directly
    # via ``importlib.util.spec_from_file_location`` sidesteps package
    # naming entirely. Codex stop-gate 2026-05-19 BLOCK after commit
    # 5779e59.
    se = _load_executor_module()
    if se is None:
        # _load_executor_module already wrote the error frame to stdout
        # via _emit_error before returning None.
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
    """Write the result as JSON with an 8-byte big-endian length prefix.

    Coerces the dict through ``_json_safe`` first so a strategy that
    attaches a datetime / set / bytes to signal metadata still produces
    a valid result frame instead of crashing the child on
    ``json.dumps`` raising ``TypeError``.
    """
    safe = _json_safe(result_dict)
    body = json.dumps(safe).encode("utf-8")
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
