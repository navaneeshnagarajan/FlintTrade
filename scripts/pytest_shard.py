"""Explicit, deterministic pytest shards for the exhaustive CI gate.

Run ``python -m pytest -p scripts.pytest_shard`` from the repository root and
provide both ``--ft-shard-index`` and ``--ft-shard-count``. Loading the plugin
without either option leaves collection unchanged. Each shard must use the
same collection arguments.
"""

from __future__ import annotations

import hashlib

import pytest


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
    _shard_settings(config)


@pytest.hookimpl(trylast=True)
def pytest_collection_modifyitems(config: pytest.Config, items: list[pytest.Item]) -> None:
    """Keep this shard's items, preserving other plugins' selection and order."""
    settings = _shard_settings(config)
    if settings is None:
        return
    index, count = settings
    selected: list[pytest.Item] = []
    deselected: list[pytest.Item] = []
    for item in items:
        target = selected if shard_for_nodeid(item.nodeid, count) == index else deselected
        target.append(item)
    items[:] = selected
    if deselected:
        config.hook.pytest_deselected(items=deselected)
    # Leave an empty shard to pytest's normal NO_TESTS_COLLECTED exit status.
