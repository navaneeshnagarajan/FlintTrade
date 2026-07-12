"""Regression tests for durable tick-replay cursors."""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

import pytest

from flinttrade_data.storage import (
    MAX_TICK_REPLAY_QUERY_ROWS,
    StorageManager,
    TickReplayCursor,
    TickReplayCursorAheadError,
    TickReplayStoreMismatchError,
)


def _storage(path: str) -> StorageManager:
    storage = StorageManager(path)
    storage.initialise()
    return storage


def _insert(storage: StorageManager, ltp: float, *, second: int = 0) -> None:
    storage.insert_tick(
        datetime(2026, 3, 16, 4, 0, second),
        "RELIANCE",
        "NSE",
        "quote",
        ltp=ltp,
        volume=int(ltp),
        timestamp_provenance="source",
    )


def test_tick_store_identity_is_stable_across_reopen(tmp_path) -> None:
    db_path = tmp_path / "ticks.duckdb"
    first = _storage(str(db_path))
    first_cursor = first.get_tick_replay_cursor()
    first.close()

    reopened = _storage(str(db_path))
    reopened_cursor = reopened.get_tick_replay_cursor()

    assert reopened_cursor == first_cursor
    assert str(UUID(reopened_cursor.store_id)) == reopened_cursor.store_id
    assert reopened_cursor.ingest_seq == 0
    reopened.close()


def test_cursor_tracks_latest_committed_global_ingest_sequence() -> None:
    storage = _storage(":memory:")
    initial = storage.get_tick_replay_cursor()
    _insert(storage, 100.0)
    first = storage.get_tick_replay_cursor()
    storage.insert_tick(
        datetime(2026, 3, 16, 4, 0, 1),
        "TCS",
        "NSE",
        "quote",
        ltp=200.0,
        volume=200,
        timestamp_provenance="source",
    )
    second = storage.get_tick_replay_cursor()

    assert initial.ingest_seq == 0
    assert first == TickReplayCursor(initial.store_id, 1)
    assert second == TickReplayCursor(initial.store_id, 2)
    storage.close()


def test_tail_after_cursor_preserves_duplicate_timestamp_ingest_order() -> None:
    storage = _storage(":memory:")
    _insert(storage, 100.0)
    _insert(storage, 101.0)
    cursor = storage.get_tick_replay_cursor()
    _insert(storage, 102.0)
    _insert(storage, 103.0)
    _insert(storage, 104.0, second=1)

    rows = storage.get_ticks_after_cursor(
        cursor,
        "RELIANCE",
        "NSE",
        "2026-03-16",
        limit=4,
    )

    assert [row["ltp"] for row in rows] == [102.0, 103.0, 104.0]
    assert [row["ingest_seq"] for row in rows] == [3, 4, 5]
    assert {row["timestamp_provenance"] for row in rows} == {"source"}
    storage.close()


def test_tail_limit_supports_an_m_plus_one_completeness_probe() -> None:
    storage = _storage(":memory:")
    cursor = storage.get_tick_replay_cursor()
    for offset in range(5):
        _insert(storage, 100.0 + offset, second=offset)

    rows = storage.get_ticks_after_cursor(
        cursor,
        "RELIANCE",
        "NSE",
        "2026-03-16",
        limit=3,
    )

    assert [row["ltp"] for row in rows] == [100.0, 101.0, 102.0]
    assert [row["ingest_seq"] for row in rows] == [1, 2, 3]
    storage.close()


def test_tail_query_rejects_a_cursor_from_a_replaced_store(tmp_path) -> None:
    db_path = tmp_path / "ticks.duckdb"
    original = _storage(str(db_path))
    _insert(original, 100.0)
    cursor = original.get_tick_replay_cursor()
    original.close()
    db_path.unlink()

    replacement = _storage(str(db_path))
    with pytest.raises(TickReplayStoreMismatchError, match="different tick store"):
        replacement.get_ticks_after_cursor(
            cursor,
            "RELIANCE",
            "NSE",
            "2026-03-16",
            limit=2,
        )
    replacement.close()


def test_cursor_ahead_of_same_store_fails_closed() -> None:
    storage = _storage(":memory:")
    current = storage.get_tick_replay_cursor()
    impossible = TickReplayCursor(current.store_id, current.ingest_seq + 1)

    with pytest.raises(TickReplayCursorAheadError, match="ahead of tick storage"):
        storage.validate_tick_replay_cursor(impossible)
    storage.close()


@pytest.mark.parametrize("limit", [True, 0, -1, MAX_TICK_REPLAY_QUERY_ROWS + 1])
def test_tail_query_rejects_invalid_or_unbounded_limits(limit) -> None:
    storage = _storage(":memory:")
    cursor = storage.get_tick_replay_cursor()

    with pytest.raises(ValueError, match="limit"):
        storage.get_ticks_after_cursor(
            cursor,
            "RELIANCE",
            "NSE",
            "2026-03-16",
            limit=limit,
        )
    storage.close()


def test_legacy_database_gains_identity_without_rewriting_tick_order(tmp_path) -> None:
    import duckdb

    db_path = tmp_path / "legacy.duckdb"
    legacy = duckdb.connect(str(db_path))
    legacy.execute(
        """CREATE TABLE ticks (
            ts TIMESTAMP NOT NULL,
            symbol VARCHAR NOT NULL,
            exchange VARCHAR NOT NULL,
            mode VARCHAR NOT NULL,
            ltp DOUBLE,
            open DOUBLE,
            high DOUBLE,
            low DOUBLE,
            close DOUBLE,
            volume BIGINT,
            bid DOUBLE,
            ask DOUBLE,
            oi BIGINT,
            prev_close DOUBLE,
            depth_json VARCHAR
        )"""
    )
    timestamp = datetime(2026, 3, 16, 4, 0)
    legacy.executemany(
        "INSERT INTO ticks (ts, symbol, exchange, mode, ltp) VALUES (?, 'RELIANCE', 'NSE', 'quote', ?)",
        [(timestamp, 100.0), (timestamp, 101.0)],
    )
    legacy.close()

    storage = _storage(str(db_path))
    cursor = storage.get_tick_replay_cursor()
    rows = storage.get_ticks_after_cursor(
        TickReplayCursor(cursor.store_id, 0),
        "RELIANCE",
        "NSE",
        "2026-03-16",
        limit=3,
    )

    assert cursor.ingest_seq == 2
    assert [row["ltp"] for row in rows] == [100.0, 101.0]
    assert [row["ingest_seq"] for row in rows] == [1, 2]
    assert [row["timestamp_provenance"] for row in rows] == ["unknown", "unknown"]
    storage.close()
