"""Regression tests for process-scoped pytest workspace isolation."""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path


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

    assert first != second
    assert first.name.startswith("flinttrade-pytest-main-")
    assert second.name.startswith("flinttrade-pytest-main-")


def test_xdist_worker_processes_get_distinct_workspaces() -> None:
    first = _probe_workspace(worker="gw0")
    second = _probe_workspace(worker="gw0")

    assert first != second
    assert first.name.startswith("flinttrade-pytest-gw0-")
    assert second.name.startswith("flinttrade-pytest-gw0-")


def test_explicit_workspace_override_is_preserved(tmp_path: Path) -> None:
    assert _probe_workspace(explicit=tmp_path) == tmp_path
