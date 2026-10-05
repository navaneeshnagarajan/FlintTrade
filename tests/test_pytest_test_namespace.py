"""Regression coverage for independent package tests and shared broker mocks."""

from __future__ import annotations

import importlib.util
import os
import subprocess
import sys
from pathlib import Path

import pytest


REPO_ROOT = Path(__file__).resolve().parents[1]
pytestmark = pytest.mark.unit


@pytest.mark.parametrize("scope", ["focused", "package_union", "full_union"])
@pytest.mark.parametrize("workers", [0, 2])
def test_duplicate_test_basenames_keep_package_helpers_and_root_mocks(
    tmp_path: Path,
    scope: str,
    workers: int,
) -> None:
    """Focused and combined runs must execute each package's own test module."""
    if workers and importlib.util.find_spec("xdist") is None:
        pytest.skip("pytest-xdist is not installed")
    for name in ("alpha", "beta"):
        test_dir = tmp_path / name / "tests"
        test_dir.mkdir(parents=True)
        (test_dir / "__init__.py").write_text("", encoding="utf-8")
        (test_dir / "helper.py").write_text(f"IDENTITY = {name!r}\n", encoding="utf-8")
        (test_dir / "test_shared.py").write_text(
            "from .helper import IDENTITY\n"
            "from tests.mocks.rate_limit_clock import RateLimitClock\n\n"
            f"def test_{name}_namespace():\n"
            f"    assert IDENTITY == {name!r}\n"
            "    assert RateLimitClock().time() == 0\n",
            encoding="utf-8",
        )
    root_tests = tmp_path / "tests"
    root_tests.mkdir()
    (root_tests / "__init__.py").write_text("", encoding="utf-8")
    (root_tests / "test_shared.py").write_text(
        "from pathlib import Path\n"
        "import tests\n"
        "from tests.mocks.rate_limit_clock import RateLimitClock\n\n"
        "def test_root_namespace():\n"
        f"    assert Path(tests.__file__).resolve().parent == Path({str(REPO_ROOT / 'tests')!r})\n"
        "    assert RateLimitClock().time() == 0\n",
        encoding="utf-8",
    )
    paths = [str(tmp_path / "alpha" / "tests")]
    expected_nodeids = ["alpha/tests/test_shared.py::test_alpha_namespace"]
    if scope != "focused":
        paths.append(str(tmp_path / "beta" / "tests"))
        expected_nodeids.append("beta/tests/test_shared.py::test_beta_namespace")
    if scope == "full_union":
        paths.append(str(root_tests))
        expected_nodeids.append("tests/test_shared.py::test_root_namespace")
    env = dict(os.environ)
    env.pop("PYTEST_ADDOPTS", None)
    env["PYTEST_DISABLE_PLUGIN_AUTOLOAD"] = "1"
    # Each synthetic package is importable just as packages.* is in the repo.
    # python -m also places the repository root first for shared tests.mocks.
    env["PYTHONPATH"] = str(tmp_path)
    command = [
        sys.executable,
        "-m",
        "pytest",
        "-p",
        "pytest_asyncio.plugin",
        "-c",
        str(REPO_ROOT / "pyproject.toml"),
        f"--rootdir={tmp_path}",
        f"--confcutdir={tmp_path}",
        "-v",
        *paths,
    ]
    if workers:
        command.extend(("-p", "xdist.plugin", "-n", str(workers)))
    result = subprocess.run(
        command,
        cwd=REPO_ROOT,
        env=env,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        timeout=45,
        check=False,
    )
    assert result.returncode == pytest.ExitCode.OK, result.stdout
    assert f"{len(expected_nodeids)} passed" in result.stdout
    for nodeid in expected_nodeids:
        assert nodeid in result.stdout, result.stdout
