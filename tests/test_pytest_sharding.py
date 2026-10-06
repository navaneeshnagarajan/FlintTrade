"""Coverage and subprocess regression tests for explicit pytest sharding."""

from __future__ import annotations

import importlib.util
import os
import subprocess
import sys
from collections import Counter
from pathlib import Path

import pytest

from scripts.pytest_shard import shard_for_nodeid


REPO_ROOT = Path(__file__).resolve().parents[1]
pytestmark = pytest.mark.unit


@pytest.fixture
def shard_project(tmp_path: Path) -> Path:
    """Make an isolated pytest project without loading repository fixtures."""
    (tmp_path / "pytest.ini").write_text(
        "[pytest]\nmarkers =\n    unit: an isolated test\n",
        encoding="utf-8",
    )
    (tmp_path / "test_sample.py").write_text(
        "import pytest\n\n"
        "@pytest.mark.parametrize('value', range(96))\n"
        "def test_value(value):\n"
        "    assert value >= 0\n\n"
        "class TestGroup:\n"
        "    @pytest.mark.unit\n"
        "    @pytest.mark.parametrize('name', ['alpha', 'beta', 'gamma', 'delta'])\n"
        "    def test_name(self, name):\n"
        "        assert name\n",
        encoding="utf-8",
    )
    return tmp_path


def _run_pytest(
    project: Path,
    *args: str,
    plugins: tuple[str, ...] = (),
    hash_seed: str = "0",
    from_repo_root: bool = False,
) -> subprocess.CompletedProcess[str]:
    env = dict(os.environ)
    env.pop("PYTEST_ADDOPTS", None)
    env["PYTEST_DISABLE_PLUGIN_AUTOLOAD"] = "1"
    env["PYTHONHASHSEED"] = hash_seed
    if from_repo_root:
        env.pop("PYTHONPATH", None)
    else:
        env["PYTHONPATH"] = os.pathsep.join(filter(None, (str(REPO_ROOT), env.get("PYTHONPATH", ""))))
    command = [sys.executable, "-m", "pytest", "-p", "scripts.pytest_shard"]
    for plugin in plugins:
        command.extend(("-p", plugin))
    command.extend(
        (
            "-c",
            str(project / "pytest.ini"),
            f"--confcutdir={project}",
            "--import-mode=importlib",
            "--strict-markers",
            *args,
        )
    )
    return subprocess.run(
        command,
        cwd=REPO_ROOT if from_repo_root else project,
        env=env,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        timeout=45,
        check=False,
    )


def _collect(project: Path, *args: str, **kwargs) -> tuple[list[str], str]:
    result = _run_pytest(project, "--collect-only", "-q", *args, **kwargs)
    assert result.returncode == pytest.ExitCode.OK, result.stdout
    nodeids = [line for line in result.stdout.splitlines() if line.startswith("test_") and "::" in line]
    return nodeids, result.stdout


@pytest.mark.parametrize("count", [1, 2, 4, 7])
def test_all_nodeids_belong_to_exactly_one_shard(count: int) -> None:
    """Hash membership covers every node, including parametrised and Unicode IDs."""
    nodeids = [f"packages/core/core/tests/test_sample.py::TestGroup::test_value[{value}]" for value in range(4096)]
    nodeids.extend(("tests/test_sample.py::test_name[हिन्दी]", "tests/test_sample.py::test_name[a/b]"))
    shards = [{nodeid for nodeid in nodeids if shard_for_nodeid(nodeid, count) == index} for index in range(count)]
    assert set().union(*shards) == set(nodeids)
    assert sum(map(len, shards)) == len(nodeids)
    membership = Counter(shard_for_nodeid(nodeid, count) for nodeid in nodeids)
    assert set(membership) == set(range(count))
    # Thousands of node IDs should distribute reasonably without timing data.
    assert max(membership.values()) - min(membership.values()) < len(nodeids) // 10


@pytest.mark.parametrize("count", [0, -1])
def test_hash_rejects_non_positive_counts(count: int) -> None:
    with pytest.raises(ValueError, match="positive"):
        shard_for_nodeid("tests/test_sample.py::test_value", count)


def test_loading_plugin_without_options_keeps_all_tests(shard_project: Path) -> None:
    nodeids, output = _collect(shard_project)
    assert len(nodeids) == 100
    assert "deselected" not in output


def test_module_invocation_loads_plugin_from_repo_root_without_pythonpath(shard_project: Path) -> None:
    """The CI entrypoint must import the plugin before any conftest is loaded."""
    nodeids, _ = _collect(
        shard_project,
        str(shard_project / "test_sample.py"),
        "--ft-shard-index=0",
        "--ft-shard-count=1",
        from_repo_root=True,
    )
    assert len(nodeids) == 100


def test_subprocess_shards_have_complete_disjoint_coverage(shard_project: Path) -> None:
    all_nodeids, _ = _collect(shard_project)
    shards = []
    for index in range(4):
        nodeids, output = _collect(shard_project, f"--ft-shard-index={index}", "--ft-shard-count=4")
        assert nodeids
        assert "deselected" in output
        # Filtering retains the surrounding runner's collected order.
        assert nodeids == [nodeid for nodeid in all_nodeids if nodeid in nodeids]
        shards.append(set(nodeids))
    assert set().union(*shards) == set(all_nodeids)
    assert sum(map(len, shards)) == len(all_nodeids)


def test_membership_does_not_depend_on_process_hash_seed_or_collection_order(shard_project: Path) -> None:
    args = ("--ft-shard-index=1", "--ft-shard-count=4")
    first, _ = _collect(shard_project, *args, hash_seed="1")
    (shard_project / "conftest.py").write_text(
        "import pytest\n\n"
        "@pytest.hookimpl(tryfirst=True)\n"
        "def pytest_collection_modifyitems(items):\n"
        "    items.reverse()\n",
        encoding="utf-8",
    )
    reversed_nodeids, _ = _collect(shard_project, *args, hash_seed="123")
    assert reversed_nodeids == list(reversed(first))


@pytest.mark.parametrize(
    ("args", "message"),
    [
        (("--ft-shard-index=0",), "must be supplied together"),
        (("--ft-shard-count=4",), "must be supplied together"),
        (("--ft-shard-index=0", "--ft-shard-count=0"), "must be positive"),
        (("--ft-shard-index=0", "--ft-shard-count=-1"), "must be positive"),
        (("--ft-shard-index=-1", "--ft-shard-count=4"), "must be at least 0"),
        (("--ft-shard-index=4", "--ft-shard-count=4"), "must be at least 0"),
        (("--ft-shard-index=invalid", "--ft-shard-count=4"), "invalid int value"),
        (("--ft-shard-index=0", "--ft-shard-count=invalid"), "invalid int value"),
    ],
)
def test_invalid_options_fail_before_collection(shard_project: Path, args: tuple[str, ...], message: str) -> None:
    (shard_project / "test_sample.py").write_text("raise RuntimeError('must not collect')\n", encoding="utf-8")
    result = _run_pytest(shard_project, *args)
    assert result.returncode == pytest.ExitCode.USAGE_ERROR, result.stdout
    assert message in result.stdout
    assert "must not collect" not in result.stdout


@pytest.mark.parametrize("workers", [0, 2])
def test_empty_shard_uses_pytest_no_tests_exit_code(shard_project: Path, workers: int) -> None:
    nodeid = "test_sample.py::test_only"
    absent_index = 1 - shard_for_nodeid(nodeid, 2)
    (shard_project / "test_sample.py").write_text("def test_only():\n    pass\n", encoding="utf-8")
    plugins = ("xdist.plugin",) if workers else ()
    if workers and importlib.util.find_spec("xdist") is None:
        pytest.skip("pytest-xdist is not installed")
    args = ("-n", str(workers)) if workers else ()
    result = _run_pytest(
        shard_project,
        f"--ft-shard-index={absent_index}",
        "--ft-shard-count=2",
        *args,
        plugins=plugins,
    )
    assert result.returncode == pytest.ExitCode.NO_TESTS_COLLECTED, result.stdout


def test_shards_preserve_marker_filtering_and_strict_marker_errors(shard_project: Path) -> None:
    nodeids, _ = _collect(shard_project, "-m", "unit", "--ft-shard-index=0", "--ft-shard-count=1")
    assert len(nodeids) == 4
    assert all("TestGroup::test_name" in nodeid for nodeid in nodeids)
    with (shard_project / "test_sample.py").open("a", encoding="utf-8") as source:
        source.write("\n@pytest.mark.unt\ndef test_typo():\n    pass\n")
    result = _run_pytest(shard_project, "--ft-shard-index=0", "--ft-shard-count=4")
    assert result.returncode == pytest.ExitCode.INTERRUPTED, result.stdout
    assert "'unt' not found in `markers` configuration option" in result.stdout


@pytest.mark.parametrize("workers", [0, 2])
def test_assertion_and_collection_failures_propagate(shard_project: Path, workers: int) -> None:
    if workers and importlib.util.find_spec("xdist") is None:
        pytest.skip("pytest-xdist is not installed")
    plugins = ("xdist.plugin",) if workers else ()
    args = ("-n", str(workers)) if workers else ()
    nodeid = "test_sample.py::test_failure"
    (shard_project / "test_sample.py").write_text(
        "def test_failure():\n    assert False, 'sentinel assertion failure'\n",
        encoding="utf-8",
    )
    result = _run_pytest(
        shard_project,
        f"--ft-shard-index={shard_for_nodeid(nodeid, 4)}",
        "--ft-shard-count=4",
        *args,
        plugins=plugins,
    )
    assert result.returncode == pytest.ExitCode.TESTS_FAILED, result.stdout
    assert "sentinel assertion failure" in result.stdout
    (shard_project / "test_sample.py").write_text("raise RuntimeError('sentinel collection failure')\n", encoding="utf-8")
    result = _run_pytest(shard_project, "--ft-shard-index=0", "--ft-shard-count=4", *args, plugins=plugins)
    assert result.returncode != pytest.ExitCode.OK, result.stdout
    assert "sentinel collection failure" in result.stdout


def test_randomisation_and_xdist_keep_consistent_shard_collection(shard_project: Path) -> None:
    if importlib.util.find_spec("pytest_randomly") is None or importlib.util.find_spec("xdist") is None:
        pytest.skip("pytest-randomly and pytest-xdist are not installed")
    all_nodeids, _ = _collect(shard_project, "--randomly-seed=137", plugins=("pytest_randomly",))
    shard_args = ("--ft-shard-index=2", "--ft-shard-count=4", "--randomly-seed=137")
    shard_nodeids, _ = _collect(shard_project, *shard_args, plugins=("pytest_randomly",))
    assert shard_nodeids == [nodeid for nodeid in all_nodeids if shard_for_nodeid(nodeid, 4) == 2]
    another_seed, _ = _collect(
        shard_project,
        "--ft-shard-index=2",
        "--ft-shard-count=4",
        "--randomly-seed=431",
        plugins=("pytest_randomly",),
    )
    assert set(another_seed) == set(shard_nodeids)
    assert another_seed != shard_nodeids
    result = _run_pytest(
        shard_project,
        *shard_args,
        "-n",
        "2",
        "-q",
        plugins=("pytest_randomly", "xdist.plugin"),
    )
    assert result.returncode == pytest.ExitCode.OK, result.stdout
    assert f"{len(shard_nodeids)} passed" in result.stdout
