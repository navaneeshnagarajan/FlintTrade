"""Regression tests for process-scoped pytest workspace isolation."""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

from .scratch_workspace import _MARKER_NAME, _STALE_AGE_SECONDS, register, release, sweep_stale


REPO_ROOT = Path(__file__).resolve().parents[1]
ROOT_CONFTEST = REPO_ROOT / "conftest.py"
_PROBE = """
import os
import runpy
import sys

runpy.run_path(sys.argv[1])
print(os.environ["FLINTTRADE_WORKSPACE_DIR"])
"""


def _probe_workspace(*, worker: str | None = None, explicit: Path | None = None) -> Path:
    env = dict(os.environ)
    env.pop("FLINTTRADE_WORKSPACE_DIR", None)
    env.pop("PYTEST_XDIST_WORKER", None)
    if worker is not None:
        env["PYTEST_XDIST_WORKER"] = worker
    if explicit is not None:
        env["FLINTTRADE_WORKSPACE_DIR"] = str(explicit)
    output = subprocess.check_output(
        [sys.executable, "-c", _PROBE, str(ROOT_CONFTEST)],
        cwd=REPO_ROOT,
        env=env,
        text=True,
    )
    return Path(output.strip())


def test_serial_pytest_processes_get_distinct_workspaces() -> None:
    first = _probe_workspace()
    second = _probe_workspace()
    # The probe subprocess never reaches pytest_sessionfinish, so its scratch
    # workspace has to be released from here or this test leaks two trees a run.
    try:
        assert first != second
        assert first.name.startswith("flinttrade-pytest-main-")
        assert second.name.startswith("flinttrade-pytest-main-")
    finally:
        release(first)
        release(second)


def test_xdist_worker_processes_get_distinct_workspaces() -> None:
    first = _probe_workspace(worker="gw0")
    second = _probe_workspace(worker="gw0")
    try:
        assert first != second
        assert first.name.startswith("flinttrade-pytest-gw0-")
        assert second.name.startswith("flinttrade-pytest-gw0-")
    finally:
        release(first)
        release(second)


def test_explicit_workspace_override_is_preserved(tmp_path: Path) -> None:
    assert _probe_workspace(explicit=tmp_path) == tmp_path


def test_release_unwinds_a_hardened_scratch_workspace() -> None:
    """A scratch workspace hardened with a protected DACL is still removable."""
    from flinttrade_core.secure_file import harden, harden_directory

    scratch = Path(tempfile.mkdtemp(prefix="flinttrade-pytest-main-"))
    nested = scratch / "runtime" / "leaf"
    nested.mkdir(parents=True)
    for directory in (scratch, scratch / "runtime", nested):
        harden_directory(directory)
    secret = nested / "secret.txt"
    secret.write_text("x", encoding="utf-8")
    harden(secret)

    release(scratch)

    assert not scratch.exists()


def test_release_refuses_a_path_it_did_not_create(tmp_path: Path) -> None:
    """Only this suite's own temp-rooted scratch workspaces are ever removed."""
    operator_workspace = tmp_path / "operator-workspace"
    operator_workspace.mkdir()
    (operator_workspace / "keep.txt").write_text("keep", encoding="utf-8")

    release(operator_workspace)

    assert (operator_workspace / "keep.txt").read_text(encoding="utf-8") == "keep"

    misnamed = Path(tempfile.mkdtemp(prefix="flinttrade-pytest-main-")) / "child"
    misnamed.mkdir()
    try:
        release(misnamed)
        assert misnamed.exists(), "a nested directory is not a scratch workspace root"
    finally:
        release(misnamed.parent)


def test_sweep_collects_only_marked_workspaces_a_previous_run_left() -> None:
    """The sweep never touches an unmarked or recent temp directory.

    An app-building test keeps store handles open past every in-process finaliser,
    so its workspace outlives its own session and the next run collects it. That
    collection has to be narrow: directories from before this finaliser existed
    carry no marker, and a directory a sibling process is still using is recent.
    """
    stale = register(tempfile.mkdtemp(prefix="flinttrade-pytest-main-"))
    recent = register(tempfile.mkdtemp(prefix="flinttrade-pytest-main-"))
    unmarked = Path(tempfile.mkdtemp(prefix="flinttrade-pytest-main-"))
    try:
        assert (stale / _MARKER_NAME).is_file()
        assert not (unmarked / _MARKER_NAME).exists()

        # Ask as if it were long enough after `stale` was marked, but not `recent`.
        marked_at = (stale / _MARKER_NAME).stat().st_mtime
        swept = sweep_stale(now=marked_at + _STALE_AGE_SECONDS + 1.0)

        assert stale in swept
        assert not stale.exists()
        assert unmarked.exists(), "an unmarked directory predates the finaliser"
        assert unmarked not in swept
    finally:
        release(stale)
        release(recent)
        shutil.rmtree(unmarked, ignore_errors=True)


def test_sweep_leaves_a_workspace_a_sibling_process_may_still_be_using() -> None:
    """A freshly marked workspace belongs to a live run and is never swept."""
    live = register(tempfile.mkdtemp(prefix="flinttrade-pytest-main-"))
    try:
        assert live not in sweep_stale()
        assert live.exists()
    finally:
        release(live)
