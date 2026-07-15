"""Regression tests for durable tick-replay cursors."""

from __future__ import annotations

import json
import threading
from datetime import datetime, timedelta, timezone
from uuid import UUID

import pytest

from flinttrade_data.storage import (
    MAX_TICK_REPLAY_QUERY_ROWS,
    StorageManager,
    TickReplayCursor,
    TickReplayCursorAheadError,
    TickReplayCursorPrunedError,
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
    assert first.get_tick_replay_lineage_handoff() is None
    recovery = first.get_tick_replay_lineage_recovery()
    assert recovery is not None
    assert recovery.reason == "pristine_store_replacement"
    assert recovery.to_store_id == first_cursor.store_id
    first.close()

    reopened = _storage(str(db_path))
    reopened_cursor = reopened.get_tick_replay_cursor()

    assert reopened_cursor == first_cursor
    assert str(UUID(reopened_cursor.store_id)) == reopened_cursor.store_id
    assert reopened_cursor.ingest_seq == 0
    reopened.close()


def test_reinitialise_preserves_existing_ingest_sequences_and_cursor(tmp_path) -> None:
    storage = _storage(str(tmp_path / "ticks.duckdb"))
    _insert(storage, 100.0)
    before_cursor = storage.get_tick_replay_cursor()
    before_rows = storage.connection.execute("SELECT ltp, ingest_seq FROM ticks ORDER BY ingest_seq").fetchall()

    storage.initialise()

    assert storage.get_tick_replay_cursor() == before_cursor
    assert storage.connection.execute("SELECT ltp, ingest_seq FROM ticks ORDER BY ingest_seq").fetchall() == before_rows
    storage.close()


def test_upgrade_without_prune_history_rotates_tick_store_lineage(tmp_path) -> None:
    db_path = tmp_path / "ticks.duckdb"
    original = _storage(str(db_path))
    _insert(original, 100.0)
    old_cursor = original.get_tick_replay_cursor()
    original.connection.execute("DELETE FROM flinttrade_storage_metadata WHERE key = 'tick_pruned_ingest_high_water'")
    original.close()

    upgraded = _storage(str(db_path))
    new_cursor = upgraded.get_tick_replay_cursor()
    handoff = upgraded.get_tick_replay_lineage_handoff()

    assert new_cursor.store_id != old_cursor.store_id
    assert handoff is not None
    assert handoff.from_store_id == old_cursor.store_id
    assert handoff.to_store_id == new_cursor.store_id
    with pytest.raises(TickReplayStoreMismatchError):
        upgraded.validate_tick_replay_cursor(old_cursor)
    assert upgraded.acknowledge_tick_replay_lineage_handoff(handoff) is True
    assert upgraded.get_tick_replay_lineage_handoff() is None
    upgraded.close()

    reopened = _storage(str(db_path))
    assert reopened.get_tick_replay_cursor() == new_cursor
    reopened.close()


def test_missing_store_identity_preserves_prune_uncertainty(tmp_path) -> None:
    db_path = tmp_path / "ticks.duckdb"
    original = _storage(str(db_path))
    _insert(original, 100.0)
    old_cursor = original.get_tick_replay_cursor()
    original.connection.execute("DELETE FROM flinttrade_storage_metadata WHERE key = 'tick_store_id'")
    original.connection.execute(
        "UPDATE flinttrade_storage_metadata SET value = '999' WHERE key = 'tick_ingest_high_water'"
    )
    original.connection.execute(
        "UPDATE flinttrade_storage_metadata SET value = '1000' WHERE key = 'tick_pruned_ingest_high_water'"
    )
    original.connection.execute(
        "UPDATE flinttrade_storage_metadata SET value = '2099-01-01T00:00:00+00:00' "
        "WHERE key = 'tick_pruned_before_utc'"
    )
    original.close()

    recovered = _storage(str(db_path))
    cursor = recovered.get_tick_replay_cursor()
    metadata = dict(recovered.connection.execute("SELECT key, value FROM flinttrade_storage_metadata").fetchall())

    assert cursor.store_id != old_cursor.store_id
    assert cursor.ingest_seq == 1000
    assert metadata["tick_ingest_high_water"] == "1000"
    assert metadata["tick_pruned_ingest_high_water"] == "1000"
    assert metadata["tick_pruned_before_utc"] == "2099-01-01T00:00:00+00:00"
    assert recovered.get_tick_replay_lineage_handoff() is None
    recovery = recovered.get_tick_replay_lineage_recovery()
    assert recovery is not None
    assert recovery.reason == "missing_store_identity"
    assert recovery.to_store_id == cursor.store_id
    assert recovered.acknowledge_tick_replay_lineage_recovery(recovery) is True
    assert recovered.get_tick_replay_lineage_recovery() is None
    with pytest.raises(TickReplayCursorPrunedError):
        recovered.validate_tick_replay_cursor(TickReplayCursor(cursor.store_id, 0))
    recovered.close()


def test_repeated_metadata_rotation_preserves_the_unacknowledged_predecessor(
    tmp_path,
) -> None:
    db_path = tmp_path / "ticks.duckdb"
    original = _storage(str(db_path))
    original_cursor = original.get_tick_replay_cursor()
    original.connection.execute("DELETE FROM flinttrade_storage_metadata WHERE key = 'tick_pruned_ingest_high_water'")
    original.close()

    first_rotation = _storage(str(db_path))
    first_rotated_cursor = first_rotation.get_tick_replay_cursor()
    first_rotation.connection.execute("DELETE FROM flinttrade_storage_metadata WHERE key = 'tick_pruned_before_utc'")
    first_rotation.close()

    second_rotation = _storage(str(db_path))
    second_rotated_cursor = second_rotation.get_tick_replay_cursor()
    handoff = second_rotation.get_tick_replay_lineage_handoff()

    assert first_rotated_cursor.store_id != original_cursor.store_id
    assert second_rotated_cursor.store_id != first_rotated_cursor.store_id
    assert handoff is not None
    assert handoff.from_store_id == first_rotated_cursor.store_id
    assert handoff.to_store_id == second_rotated_cursor.store_id
    assert handoff.ancestor_store_ids == (original_cursor.store_id,)
    assert handoff.source_store_ids == (
        original_cursor.store_id,
        first_rotated_cursor.store_id,
    )
    second_rotation.close()


def test_repeated_metadata_rotation_keeps_bounded_recent_ancestry(tmp_path) -> None:
    db_path = tmp_path / "ticks.duckdb"
    storage = _storage(str(db_path))
    store_ids = [storage.get_tick_replay_cursor().store_id]

    for _ in range(20):
        storage.connection.execute(
            "DELETE FROM flinttrade_storage_metadata WHERE key = 'tick_pruned_ingest_high_water'"
        )
        storage.close()
        storage = _storage(str(db_path))
        store_ids.append(storage.get_tick_replay_cursor().store_id)

    handoff = storage.get_tick_replay_lineage_handoff()
    assert handoff is not None
    assert handoff.to_store_id == store_ids[-1]
    assert handoff.from_store_id == store_ids[-2]
    assert handoff.source_store_ids == tuple(store_ids[-17:-1])
    assert len(handoff.source_store_ids) == 16
    assert store_ids[0] not in handoff.source_store_ids
    storage.close()


def test_stale_handoff_acknowledgement_cannot_delete_a_concurrent_rotation(tmp_path, monkeypatch) -> None:
    db_path = tmp_path / "ticks.duckdb"
    original = _storage(str(db_path))
    original_id = original.get_tick_replay_cursor().store_id
    original.connection.execute(
        "DELETE FROM flinttrade_storage_metadata WHERE key = 'tick_pruned_ingest_high_water'"
    )
    original.close()

    acknowledging = _storage(str(db_path))
    stale_handoff = acknowledging.get_tick_replay_lineage_handoff()
    assert stale_handoff is not None
    read_complete = threading.Event()
    continue_ack = threading.Event()
    real_get = acknowledging.get_tick_replay_lineage_handoff
    first_read = True

    def paused_get():
        nonlocal first_read
        current = real_get()
        if first_read:
            first_read = False
            read_complete.set()
            assert continue_ack.wait(2)
        return current

    monkeypatch.setattr(acknowledging, "get_tick_replay_lineage_handoff", paused_get)
    errors: list[BaseException] = []

    def acknowledge() -> None:
        try:
            acknowledging.acknowledge_tick_replay_lineage_handoff(stale_handoff)
        except BaseException as exc:  # noqa: BLE001 - asserted below
            errors.append(exc)

    thread = threading.Thread(target=acknowledge)
    thread.start()
    assert read_complete.wait(1)
    writer = StorageManager(str(db_path))
    next_store_id = "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa"
    writer.connection.execute("BEGIN TRANSACTION")
    writer._set_metadata_value("tick_store_id", next_store_id)
    writer._set_metadata_value("tick_lineage_predecessor_store_id", stale_handoff.to_store_id)
    writer._set_metadata_value("tick_lineage_ancestor_store_ids", json.dumps([original_id]))
    writer.connection.execute("COMMIT")
    continue_ack.set()
    thread.join(2)

    assert not thread.is_alive()
    assert errors
    concurrent = writer.get_tick_replay_lineage_handoff()
    assert concurrent is not None
    assert concurrent.from_store_id == stale_handoff.to_store_id
    assert concurrent.to_store_id == next_store_id
    assert concurrent.ancestor_store_ids == (original_id,)
    acknowledging.close()
    writer.close()


def test_stale_recovery_acknowledgement_cannot_delete_new_authority(tmp_path, monkeypatch) -> None:
    db_path = tmp_path / "ticks.duckdb"
    acknowledging = _storage(str(db_path))
    stale_recovery = acknowledging.get_tick_replay_lineage_recovery()
    assert stale_recovery is not None
    read_complete = threading.Event()
    continue_ack = threading.Event()
    real_get = acknowledging.get_tick_replay_lineage_recovery
    first_read = True

    def paused_get():
        nonlocal first_read
        current = real_get()
        if first_read:
            first_read = False
            read_complete.set()
            assert continue_ack.wait(2)
        return current

    monkeypatch.setattr(acknowledging, "get_tick_replay_lineage_recovery", paused_get)
    errors: list[BaseException] = []

    def acknowledge() -> None:
        try:
            acknowledging.acknowledge_tick_replay_lineage_recovery(stale_recovery)
        except BaseException as exc:  # noqa: BLE001 - asserted below
            errors.append(exc)

    thread = threading.Thread(target=acknowledge)
    thread.start()
    assert read_complete.wait(1)
    writer = StorageManager(str(db_path))
    next_store_id = "bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb"
    writer.connection.execute("BEGIN TRANSACTION")
    writer._set_metadata_value("tick_store_id", next_store_id)
    writer._set_metadata_value(
        "tick_lineage_recovery",
        json.dumps(
            {"reason": "pristine_store_replacement", "to_store_id": next_store_id},
            separators=(",", ":"),
            sort_keys=True,
        ),
    )
    writer.connection.execute("COMMIT")
    continue_ack.set()
    thread.join(2)

    assert not thread.is_alive()
    assert errors
    concurrent = writer.get_tick_replay_lineage_recovery()
    assert concurrent is not None
    assert concurrent.to_store_id == next_store_id
    acknowledging.close()
    writer.close()


def test_lineage_metadata_reset_rolls_back_as_one_transaction(
    tmp_path,
    monkeypatch,
) -> None:
    db_path = tmp_path / "ticks.duckdb"
    original = _storage(str(db_path))
    original.connection.execute("DELETE FROM flinttrade_storage_metadata WHERE key = 'tick_store_id'")
    original.connection.execute(
        "UPDATE flinttrade_storage_metadata SET value = '1000' WHERE key = 'tick_pruned_ingest_high_water'"
    )
    original.connection.execute(
        "UPDATE flinttrade_storage_metadata SET value = '2099-01-01T00:00:00+00:00' "
        "WHERE key = 'tick_pruned_before_utc'"
    )
    metadata_before = dict(
        original.connection.execute("SELECT key, value FROM flinttrade_storage_metadata").fetchall()
    )
    original.close()

    recovered = StorageManager(str(db_path))
    real_set_metadata = recovered._set_metadata_value

    def fail_after_prune_high_water(key: str, value: str) -> None:
        real_set_metadata(key, value)
        if key == "tick_pruned_ingest_high_water":
            raise RuntimeError("simulated metadata write failure")

    monkeypatch.setattr(recovered, "_set_metadata_value", fail_after_prune_high_water)

    with pytest.raises(RuntimeError, match="simulated metadata write failure"):
        recovered.initialise()

    metadata = dict(recovered.connection.execute("SELECT key, value FROM flinttrade_storage_metadata").fetchall())
    assert metadata == metadata_before
    recovered.close()


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


def test_retention_cannot_move_the_committed_cursor_backwards() -> None:
    storage = _storage(":memory:")
    recent = datetime.now(timezone.utc).replace(tzinfo=None)
    old = recent - timedelta(days=30)
    storage.insert_tick(
        recent,
        "RELIANCE",
        "NSE",
        "quote",
        ltp=100.0,
        timestamp_provenance="source",
    )
    storage.insert_tick(
        old,
        "RELIANCE",
        "NSE",
        "quote",
        ltp=99.0,
        timestamp_provenance="source",
    )
    checkpoint_cursor = storage.get_tick_replay_cursor()

    assert storage.prune_ticks(7) == 1
    assert storage.get_tick_replay_cursor() == checkpoint_cursor
    assert storage.validate_tick_replay_cursor(checkpoint_cursor) == checkpoint_cursor
    storage.close()


def test_checkpoint_before_a_pruned_post_cursor_row_is_rejected() -> None:
    storage = _storage(":memory:")
    recent = datetime.now(timezone.utc).replace(tzinfo=None)
    storage.insert_tick(
        recent,
        "RELIANCE",
        "NSE",
        "quote",
        ltp=100.0,
        timestamp_provenance="source",
    )
    checkpoint_cursor = storage.get_tick_replay_cursor()
    storage.insert_tick(
        recent - timedelta(days=30),
        "RELIANCE",
        "NSE",
        "quote",
        ltp=99.0,
        timestamp_provenance="source",
    )

    assert storage.prune_ticks(7) == 1
    with pytest.raises(TickReplayCursorPrunedError, match="retention"):
        storage.validate_tick_replay_cursor(checkpoint_cursor)
    storage.close()


def test_current_session_zero_cursor_survives_unrelated_historical_prune() -> None:
    storage = _storage(":memory:")
    now = datetime.now(timezone.utc)
    storage.insert_tick(
        now - timedelta(days=100),
        "RELIANCE",
        "NSE",
        "quote",
        ltp=90.0,
        timestamp_provenance="source",
    )
    storage.insert_tick(
        now,
        "RELIANCE",
        "NSE",
        "quote",
        ltp=100.0,
        timestamp_provenance="source",
    )
    cursor = storage.get_tick_replay_cursor()

    assert storage.prune_ticks(90) == 1
    rows = storage.get_ticks_after_cursor(
        TickReplayCursor(cursor.store_id, 0),
        "RELIANCE",
        "NSE",
        now.astimezone(timezone(timedelta(hours=5, minutes=30))).date().isoformat(),
        limit=2,
    )

    assert [row["ltp"] for row in rows] == [100.0]
    storage.close()


def test_tail_validation_and_query_share_one_retention_snapshot(tmp_path) -> None:
    validated = threading.Event()
    release_reader = threading.Event()

    class BlockingValidationStorage(StorageManager):
        def _validate_tick_replay_cursor_in_transaction(self, cursor, *, session_start=None):
            current = super()._validate_tick_replay_cursor_in_transaction(
                cursor,
                session_start=session_start,
            )
            validated.set()
            release_reader.wait(timeout=2)
            return current

    db_path = tmp_path / "ticks.duckdb"
    reader = BlockingValidationStorage(str(db_path))
    reader.initialise()
    writer = StorageManager(str(db_path))
    writer.initialise()
    now = datetime.now(timezone.utc)
    reader.insert_tick(
        now,
        "RELIANCE",
        "NSE",
        "quote",
        ltp=100.0,
        timestamp_provenance="source",
    )
    cursor = reader.get_tick_replay_cursor()
    reader.insert_tick(
        now - timedelta(days=100),
        "RELIANCE",
        "NSE",
        "quote",
        ltp=101.0,
        timestamp_provenance="source",
    )
    reader.insert_tick(
        now,
        "RELIANCE",
        "NSE",
        "quote",
        ltp=102.0,
        timestamp_provenance="source",
    )
    rows: list[dict] = []
    errors: list[BaseException] = []

    def read_tail() -> None:
        try:
            rows.extend(
                reader.get_ticks_after_cursor(
                    cursor,
                    "RELIANCE",
                    "NSE",
                    None,
                    limit=3,
                )
            )
        except BaseException as exc:  # pragma: no cover - asserted below
            errors.append(exc)

    thread = threading.Thread(target=read_tail)
    thread.start()
    assert validated.wait(timeout=1)
    try:
        assert writer.prune_ticks(90) == 1
    finally:
        release_reader.set()
    thread.join(timeout=2)

    assert not thread.is_alive()
    assert errors == []
    assert [row["ltp"] for row in rows] == [101.0, 102.0]
    reader.close()
    writer.close()


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


def test_unpartitioned_tail_returns_every_post_cursor_commit() -> None:
    storage = _storage(":memory:")
    _insert(storage, 100.0)
    cursor = storage.get_tick_replay_cursor()
    storage.insert_tick(
        datetime(2026, 3, 17, 4, 0),
        "RELIANCE",
        "NSE",
        "quote",
        ltp=101.0,
        volume=101,
        timestamp_provenance="source",
    )
    storage.insert_tick(
        datetime(2026, 3, 15, 4, 0),
        "RELIANCE",
        "NSE",
        "quote",
        ltp=99.0,
        volume=99,
        timestamp_provenance="source",
    )

    rows = storage.get_ticks_after_cursor(
        cursor,
        "RELIANCE",
        "NSE",
        None,
        limit=3,
    )

    assert [row["ltp"] for row in rows] == [101.0, 99.0]
    assert [row["ingest_seq"] for row in rows] == [2, 3]
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
