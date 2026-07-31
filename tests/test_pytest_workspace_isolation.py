"""Regression tests for process-scoped pytest workspace isolation."""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path

from . import scratch_workspace
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


def _abandon(workspace: Path, *, age_seconds: float) -> None:
    """Make *workspace* look like one a finished run left behind.

    Drops this process's liveness claim and back-dates the marker, which between
    them are the whole of what distinguishes an abandoned workspace from a live
    one.

    Args:
        workspace: A registered scratch workspace.
        age_seconds: How long ago the marker should claim to have been stamped.
    """
    scratch_workspace._unclaim(workspace)
    marker = workspace / _MARKER_NAME
    stamped = time.time() - age_seconds
    os.utime(marker, (stamped, stamped))


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

        # Age the decoy itself rather than asking the sweep to pretend it is
        # later than it is. `sweep_stale` used to take a `now` override for
        # exactly this, and the shifted reference aged every live sibling xdist
        # worker's workspace along with the decoy - see the regression test below.
        _abandon(stale, age_seconds=_STALE_AGE_SECONDS + 1.0)

        swept = sweep_stale()

        assert stale in swept
        assert not stale.exists()
        assert recent.exists(), "a workspace this process still holds is live"
        assert recent not in swept
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


_HOLD_WORKSPACE = """
import os, runpy, sys, time

runpy.run_path(sys.argv[1])
print(os.environ["FLINTTRADE_WORKSPACE_DIR"], flush=True)
time.sleep(float(sys.argv[2]))
"""
"""Acquire a scratch workspace exactly as a worker does, then hold it open.

Runs the repo-root conftest rather than reaching into the helper directly, so
the workspace under test is built by the production path - package sys.path
wiring, env pinning, master-password seeding and the liveness claim included.
"""


def test_sweep_spares_a_live_sibling_process_however_old_its_marker_looks() -> None:
    """A workspace another *process* is using survives a sweep that condemns it.

    This is the fix for the cross-process wipe. The sweep globs the whole shared
    system temp directory, so most of what it sees belongs to concurrently
    running xdist workers, and it used to decide liveness purely from the
    marker's age. Anything that made that age look large - a caller-supplied
    reference time, a clock that skewed, a run that outlasted the window -
    recursively removed live workers' workspaces mid-run, taking their seeded
    ``master_password`` with them and failing every later app-building test in
    those workers with "master password required but no TTY available".

    So the marker here is back-dated well past the staleness window, which is
    the strongest form of the condition that used to destroy it, and the only
    thing standing between the sweep and the directory is the sibling's claim.
    """
    holder = subprocess.Popen(  # noqa: S603
        [sys.executable, "-c", _HOLD_WORKSPACE, str(ROOT_CONFTEST), "60"],
        stdout=subprocess.PIPE,
        text=True,
        env={**os.environ, "PYTEST_XDIST_WORKER": "gw-sibling"},
    )
    sibling: Path | None = None
    try:
        assert holder.stdout is not None
        sibling = Path(holder.stdout.readline().strip())
        password = sibling / "master_password"
        assert password.is_file(), "the sibling seeded its workspace before we looked"

        marker = sibling / _MARKER_NAME
        ancient = time.time() - (_STALE_AGE_SECONDS * 10)
        os.utime(marker, (ancient, ancient))

        swept = sweep_stale()

        assert sibling not in swept
        assert sibling.exists(), "a live sibling's workspace was removed"
        assert password.is_file(), "a live sibling's master password was removed"
    finally:
        holder.kill()
        holder.wait(timeout=30)
        if holder.stdout is not None:
            holder.stdout.close()
        # The holder is killed, so it never releases its own workspace.
        if sibling is not None:
            shutil.rmtree(sibling, ignore_errors=True)


def test_a_dead_process_workspace_is_still_collected() -> None:
    """The liveness claim must not make abandoned workspaces immortal.

    Mutation guard for the test above: sparing everything would pass it, and
    would reintroduce the unbounded temp-directory growth the sweep exists to
    stop. The claim has to die with its process.
    """
    holder = subprocess.Popen(  # noqa: S603
        [sys.executable, "-c", _HOLD_WORKSPACE, str(ROOT_CONFTEST), "0"],
        stdout=subprocess.PIPE,
        text=True,
        env={**os.environ, "PYTEST_XDIST_WORKER": "gw-departed"},
    )
    assert holder.stdout is not None
    departed = Path(holder.stdout.readline().strip())
    holder.wait(timeout=60)
    holder.stdout.close()

    try:
        assert departed.exists(), "the holder left its workspace behind, as a killed worker would"
        marker = departed / _MARKER_NAME
        ancient = time.time() - (_STALE_AGE_SECONDS + 1.0)
        os.utime(marker, (ancient, ancient))

        assert departed in sweep_stale()
        assert not departed.exists()
    finally:
        shutil.rmtree(departed, ignore_errors=True)


_COUNT_WORKSPACES = """
import os, pathlib, runpy, sys, tempfile

repo = sys.argv[1]
sys.path.insert(0, repo)
for conftest in (
    "conftest.py",
    os.path.join("packages", "core", "core", "tests", "conftest.py"),
    os.path.join("packages", "core", "data", "tests", "conftest.py"),
):
    runpy.run_path(os.path.join(repo, conftest))
minted = list(pathlib.Path(tempfile.gettempdir()).glob("flinttrade-pytest-*"))
print(len(minted))
print(os.environ["FLINTTRADE_WORKSPACE_DIR"])
"""


def test_every_conftest_shares_one_workspace_per_process(tmp_path: Path) -> None:
    """Loading all three isolating conftests mints exactly one workspace.

    Each used to mint and seed its own, so a worker created three, whichever was
    imported last silently won ``FLINTTRADE_WORKSPACE_DIR``, and the other two
    sat registered and abandoned. That churn is what made the workspace a
    process-global nobody owned.
    """
    env = dict(os.environ)
    env.pop("FLINTTRADE_WORKSPACE_DIR", None)
    env["PYTEST_XDIST_WORKER"] = "gw7"
    for var in ("TMPDIR", "TEMP", "TMP"):
        env[var] = str(tmp_path)

    output = subprocess.check_output(  # noqa: S603
        [sys.executable, "-c", _COUNT_WORKSPACES, str(REPO_ROOT)],
        cwd=REPO_ROOT,
        env=env,
        text=True,
    ).splitlines()

    assert output[0] == "1", f"expected one workspace, got {output[0]}"
    workspace = Path(output[1])
    assert workspace.parent == tmp_path
    assert workspace.name.startswith("flinttrade-pytest-gw7-")
    assert (workspace / "master_password").is_file()
