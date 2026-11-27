"""Explicit, deterministic pytest shards for the exhaustive CI gate.

Run ``python -m pytest -p scripts.pytest_shard`` from the repository root and
provide both ``--ft-shard-index`` and ``--ft-shard-count``. Loading the plugin
without either option leaves collection unchanged. Each shard must use the
same collection arguments.

By default a stable hash of each node ID picks its shard. Adding
``--ft-shard-durations=scripts/pytest_shard_durations.json`` instead places
whole test files by recorded run time (keyed by a hash of each file path), so shards finish close together.
Regenerate that record from CI JUnit files with
``python scripts/update_shard_durations.py``.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

# Seconds charged per test in a file the timing record does not list, when
# the record itself does not say.
DEFAULT_TEST_SECONDS = 0.25


def shard_for_nodeid(nodeid: str, count: int) -> int:
    """Return a node ID's stable, zero-based shard for a positive shard count.

    Pytest node IDs use repository-relative paths with forward slashes. Hash
    their UTF-8 bytes rather than Python's process-randomised ``hash()`` so
    membership is independent of collection order, worker and platform.
    """
    if count < 1:
        raise ValueError("shard count must be positive")
    digest = hashlib.sha256(nodeid.encode("utf-8")).digest()
    return int.from_bytes(digest, "big") % count


def file_key(path: str) -> str:
    """Return the timing-record key for a test file path.

    Keys are the first 16 hex digits of the SHA-256 of the repository-relative
    path, so the record carries no file names of its own and repository-wide
    text scans never match it.
    """
    return hashlib.sha256(path.encode("utf-8")).hexdigest()[:16]


def load_file_durations(path: str | Path) -> tuple[dict[str, float], float]:
    """Read a timing record: ``{"default_test_seconds": x, "files": {key: seconds}}``.

    Returns the seconds keyed by ``file_key`` and the per-test charge for files
    the record leaves out. ``default_test_seconds`` is optional.
    """
    try:
        raw = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise pytest.UsageError(f"--ft-shard-durations could not be read: {exc}") from exc
    files = raw.get("files") if isinstance(raw, dict) else None
    if not isinstance(files, dict):
        raise pytest.UsageError("--ft-shard-durations must contain a 'files' mapping")
    default = raw.get("default_test_seconds", DEFAULT_TEST_SECONDS)
    if not isinstance(default, (int, float)) or isinstance(default, bool) or default < 0:
        raise pytest.UsageError("--ft-shard-durations has an invalid default_test_seconds")
    durations: dict[str, float] = {}
    for name, seconds in files.items():
        if not isinstance(seconds, (int, float)) or isinstance(seconds, bool) or seconds < 0:
            raise pytest.UsageError(f"--ft-shard-durations has an invalid entry for {name!r}")
        durations[name] = float(seconds)
    return durations, float(default)


def file_of(nodeid: str) -> str:
    """Return the test file part of a pytest node ID."""
    return nodeid.split("::", 1)[0]


def plan_weighted_shards(
    nodeids: list[str],
    count: int,
    durations: dict[str, float],
    default_test_seconds: float = DEFAULT_TEST_SECONDS,
) -> dict[str, int]:
    """Assign whole test files to shards so recorded run time is balanced.

    Files are placed longest first onto the shard with the least time so far
    (ties go to the lowest shard index). The plan depends only on the set of
    collected node IDs and the timing record, never on collection order, so
    every shard computes the same partition independently. A file without a
    recorded duration is charged ``default_test_seconds`` per collected test.
    """
    if count < 1:
        raise ValueError("shard count must be positive")
    tests_per_file: dict[str, int] = {}
    for nodeid in nodeids:
        name = file_of(nodeid)
        tests_per_file[name] = tests_per_file.get(name, 0) + 1
    weights = {
        name: durations.get(name, default_test_seconds * tests)
        for name, tests in tests_per_file.items()
    }
    loads = [0.0] * count
    file_shard: dict[str, int] = {}
    for name in sorted(weights, key=lambda item: (-weights[item], item)):
        target = min(range(count), key=lambda index: (loads[index], index))
        file_shard[name] = target
        loads[target] += weights[name]
    return {nodeid: file_shard[file_of(nodeid)] for nodeid in nodeids}


def pytest_addoption(parser: pytest.Parser) -> None:
    """Register opt-in shard arguments without changing the default run."""
    group = parser.getgroup("FlintTrade sharding")
    group.addoption(
        "--ft-shard-index",
        type=int,
        default=None,
        metavar="INDEX",
        help="Zero-based shard index; requires --ft-shard-count.",
    )
    group.addoption(
        "--ft-shard-count",
        type=int,
        default=None,
        metavar="COUNT",
        help="Positive shard count; requires --ft-shard-index.",
    )
    group.addoption(
        "--ft-shard-durations",
        default=None,
        metavar="PATH",
        help="Balance whole files across shards using recorded per-file seconds.",
    )


def _shard_settings(config: pytest.Config) -> tuple[int, int] | None:
    index: int | None = config.getoption("ft_shard_index")
    count: int | None = config.getoption("ft_shard_count")
    if index is None and count is None:
        return None
    if index is None or count is None:
        raise pytest.UsageError("--ft-shard-index and --ft-shard-count must be supplied together")
    if count < 1:
        raise pytest.UsageError("--ft-shard-count must be positive")
    if not 0 <= index < count:
        raise pytest.UsageError("--ft-shard-index must be at least 0 and less than --ft-shard-count")
    return index, count


def pytest_configure(config: pytest.Config) -> None:
    """Reject invalid arguments before collecting or executing tests."""
    settings = _shard_settings(config)
    durations_path = config.getoption("ft_shard_durations")
    if durations_path is not None:
        if settings is None:
            raise pytest.UsageError("--ft-shard-durations requires --ft-shard-index and --ft-shard-count")
        load_file_durations(durations_path)


@pytest.hookimpl(trylast=True)
def pytest_collection_modifyitems(config: pytest.Config, items: list[pytest.Item]) -> None:
    """Keep this shard's items, preserving other plugins' selection and order."""
    settings = _shard_settings(config)
    if settings is None:
        return
    index, count = settings
    durations_path = config.getoption("ft_shard_durations")
    if durations_path is None:
        plan = {item.nodeid: shard_for_nodeid(item.nodeid, count) for item in items}
    else:
        recorded, default_test_seconds = load_file_durations(durations_path)
        nodeids = [item.nodeid for item in items]
        durations = {
            name: recorded[file_key(name)]
            for name in {file_of(nodeid) for nodeid in nodeids}
            if file_key(name) in recorded
        }
        plan = plan_weighted_shards(nodeids, count, durations, default_test_seconds)
    selected: list[pytest.Item] = []
    deselected: list[pytest.Item] = []
    for item in items:
        target = selected if plan[item.nodeid] == index else deselected
        target.append(item)
    items[:] = selected
    if deselected:
        config.hook.pytest_deselected(items=deselected)
    # Leave an empty shard to pytest's normal NO_TESTS_COLLECTED exit status.
