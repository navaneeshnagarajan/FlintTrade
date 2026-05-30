"""Sandbox executor hardening tests (restructure §11.4; SC-03).

Covers the runtime import-block finder, the seccomp limited-hardening signal,
the close_fds/pass_fds FD-isolation contract, and the parent-never-pickle-loads
invariant. The finder is exercised in isolation — we never call
``_install_import_block()`` in the test process itself, because evicting
``pickle`` from the runner's ``sys.modules`` would break pytest-xdist's own IPC.
"""

from __future__ import annotations

import io
import re
from contextlib import redirect_stderr
from pathlib import Path

import pytest

from flinttrade_engine import _sandbox_child as child

_EXECUTOR_SRC = (
    Path(__file__).resolve().parents[1] / "src" / "flinttrade_engine" / "sandbox_executor.py"
).read_text(encoding="utf-8")


# --- runtime import-block finder (the real control; AST is bypassable) ------


@pytest.mark.parametrize("blocked", ["pickle", "subprocess", "socket", "ctypes", "marshal"])
def test_finder_blocks_dangerous_modules(blocked) -> None:
    finder = child._SandboxBlockedFinder()
    with pytest.raises(ImportError, match=f"SANDBOX_BLOCKED_IMPORT:{blocked}"):
        finder.find_spec(blocked, None)


def test_finder_blocks_submodule_imports() -> None:
    finder = child._SandboxBlockedFinder()
    with pytest.raises(ImportError, match="SANDBOX_BLOCKED_IMPORT:http.client"):
        finder.find_spec("http.client", None)


def test_finder_allows_innocuous_modules() -> None:
    finder = child._SandboxBlockedFinder()
    assert finder.find_spec("numpy", None) is None
    assert finder.find_spec("pandas", None) is None


def test_blocked_set_covers_escape_primitives() -> None:
    blocked = child._SANDBOX_BLOCKED_MODULES
    for name in ("pickle", "_pickle", "subprocess", "ctypes", "socket", "importlib", "multiprocessing"):
        assert name in blocked


# --- seccomp limited-hardening signal ---------------------------------------


def test_apply_seccomp_emits_limited_marker_off_linux(monkeypatch) -> None:
    """Without Linux+pyseccomp+opt-in, the child must signal reduced hardening."""
    monkeypatch.delenv("FLINTTRADE_SANDBOX_SECCOMP", raising=False)
    buf = io.StringIO()
    with redirect_stderr(buf):
        child._apply_seccomp()
    assert "SANDBOX_OS_HARDENING_LIMITED" in buf.getvalue()


# --- FD isolation + parent-never-pickle-loads (source-level invariants) ------


def test_popen_uses_close_fds_and_pass_fds() -> None:
    assert "close_fds" in _EXECUTOR_SRC and "True" in _EXECUTOR_SRC
    assert "pass_fds" in _EXECUTOR_SRC


def test_parent_never_pickle_loads_child_output() -> None:
    """The parent writes pickle.dumps to the child but must NEVER pickle.loads it."""
    assert "pickle.dumps" in _EXECUTOR_SRC      # parent → child (trusted direction)
    assert not re.search(r"pickle\.loads\s*\(", _EXECUTOR_SRC)  # never child → parent
