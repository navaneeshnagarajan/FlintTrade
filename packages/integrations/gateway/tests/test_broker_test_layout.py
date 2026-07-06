from __future__ import annotations

from pathlib import Path


def test_broker_package_does_not_duplicate_root_test_basenames() -> None:
    """Broker tests with the same basename are easy to run inconsistently."""
    tests_dir = Path(__file__).resolve().parent
    broker_dir = tests_dir / "brokers"

    root_names = {p.name for p in tests_dir.glob("test_*.py")}
    broker_names = {p.name for p in broker_dir.glob("test_*.py")}

    duplicates = sorted(root_names & broker_names)

    assert duplicates == []
