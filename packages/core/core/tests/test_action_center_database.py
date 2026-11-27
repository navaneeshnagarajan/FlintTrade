"""Action Centre keeps one live DuckDB writer per file.

A later app boot used to checkpoint ``action_center.duckdb`` while the
previous app's queue still held it. That write failed with ``Bad file
descriptor`` and DuckDB then refused every later open of the same path.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from flinttrade_core.app import _cleanup_stale_duckdb_wals
from flinttrade_core.factory_lifecycle import FACTORY_STORES
from flinttrade_engine.action_center import ActionCenterError, PendingOrderQueue


def _enqueue(queue: PendingOrderQueue, request_id: str) -> None:
    queue.enqueue(
        {"symbol": "RELIANCE", "qty": 1, "action": "BUY"},
        reason="boot",
        request_id=request_id,
    )


@pytest.mark.unit
def test_wal_recovery_closes_the_live_writer_before_checkpoint(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The next boot must not checkpoint over a connection the last app left open."""
    monkeypatch.setenv("FLINTTRADE_WORKSPACE_DIR", str(tmp_path))
    database = tmp_path / "action_center.duckdb"
    leaked = PendingOrderQueue(db_path=database)
    _enqueue(leaked, "still-open")
    assert (tmp_path / "action_center.duckdb.wal").exists()

    _cleanup_stale_duckdb_wals()

    with pytest.raises(ActionCenterError, match="closed"):
        leaked.list_pending()
    replacement = PendingOrderQueue(db_path=database)
    try:
        assert [row.id for row in replacement.list_pending()] == ["still-open"]
        _enqueue(replacement, "after-recovery")
        assert {row.id for row in replacement.list_pending()} == {"still-open", "after-recovery"}
    finally:
        replacement.close()
        replacement.close()


@pytest.mark.unit
def test_repeated_boots_do_not_invalidate_the_shared_database(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Many leaked app instances on one module workspace must keep the file usable."""
    monkeypatch.setenv("FLINTTRADE_WORKSPACE_DIR", str(tmp_path))
    database = tmp_path / "action_center.duckdb"
    for index in range(25):
        leaked = PendingOrderQueue(db_path=database)
        _enqueue(leaked, f"boot-{index}")
        _cleanup_stale_duckdb_wals()
        current = PendingOrderQueue(db_path=database)
        try:
            ids = {row.id for row in current.list_pending()}
        finally:
            current.close()
        assert f"boot-{index}" in ids


@pytest.mark.unit
def test_app_teardown_owns_the_action_centre_queue() -> None:
    """Factory shutdown closes the queue instead of leaving its descriptor open."""
    assert "PENDING_ORDER_QUEUE" in FACTORY_STORES
