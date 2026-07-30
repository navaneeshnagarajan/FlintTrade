"""Core wiring for cursor-bound order-flow restart checkpoints."""

from __future__ import annotations

import json
import os
import threading
from datetime import datetime
from unittest.mock import MagicMock, call
from zoneinfo import ZoneInfo

import pytest

from flinttrade_core.app import (
    _OrderFlowCheckpointOwner,
    _prepare_tick_orderflow_state,
)
from flinttrade_data.orderflow_aggregator import DEFAULT_RESTORE_MAX_TICKS
from flinttrade_data.orderflow_checkpoint import (
    OrderFlowCheckpoint,
    OrderFlowCheckpointChecksumError,
)
from flinttrade_data.storage import TickReplayCursor


@pytest.mark.unit
def test_checkpoint_owner_throttles_periodic_writes_but_forces_shutdown_snapshot(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path,
) -> None:
    import flinttrade_data.orderflow_checkpoint as checkpoint_module

    cursor = TickReplayCursor(
        store_id="12345678-1234-5678-1234-567812345678",
        ingest_seq=17,
    )
    storage_lock = threading.Lock()
    storage = MagicMock()
    storage.get_tick_replay_cursor.return_value = cursor
    storage.get_tick_replay_lineage_handoff.return_value = None
    storage.get_tick_replay_lineage_recovery.return_value = None
    orderflow = MagicMock()
    orderflow.export_state.return_value = {"version": 1, "identities": []}
    observed: list[tuple[object, object, object]] = []

    def store_checkpoint(workspace_dir, state, replay_cursor, **_kwargs) -> None:
        assert storage_lock.locked()
        observed.append((workspace_dir, state, replay_cursor))

    monkeypatch.setattr(
        checkpoint_module,
        "store_orderflow_checkpoint",
        store_checkpoint,
    )
    times = iter((100.0, 110.0, 131.0, 132.0))
    owner = _OrderFlowCheckpointOwner(
        storage,
        orderflow,
        workspace_dir=tmp_path,
        storage_lock=storage_lock,
        interval_seconds=30.0,
        clock=lambda: next(times),
    )

    assert owner.persist() is True
    assert owner.persist() is False
    assert owner.persist() is True
    assert owner.persist(force=True) is True
    assert observed == [
        (tmp_path, {"version": 1, "identities": []}, cursor),
        (tmp_path, {"version": 1, "identities": []}, cursor),
        (tmp_path, {"version": 1, "identities": []}, cursor),
    ]


@pytest.mark.unit
def test_checkpoint_owner_performs_and_acknowledges_metadata_lineage_handoff(
    tmp_path,
) -> None:
    from flinttrade_data.orderflow_aggregator import OrderFlowAggregator
    from flinttrade_data.orderflow_checkpoint import (
        load_orderflow_checkpoint,
        store_orderflow_checkpoint,
    )
    from flinttrade_data.storage import StorageManager

    db_path = tmp_path / "ticks.duckdb"
    original = StorageManager(str(db_path))
    original.initialise()
    old_cursor = original.get_tick_replay_cursor()
    state = OrderFlowAggregator().export_state()
    store_orderflow_checkpoint(tmp_path, state, old_cursor)
    original.connection.execute("DELETE FROM flinttrade_storage_metadata WHERE key = 'tick_pruned_ingest_high_water'")
    original.close()

    rotated = StorageManager(str(db_path))
    rotated.initialise()
    new_cursor = rotated.get_tick_replay_cursor()
    owner = _OrderFlowCheckpointOwner(
        rotated,
        OrderFlowAggregator(),
        workspace_dir=tmp_path,
        interval_seconds=0,
    )

    assert owner.persist(force=True) is True

    loaded = load_orderflow_checkpoint(tmp_path)
    assert loaded is not None
    assert loaded.cursor == new_cursor
    assert loaded.cursor.store_id != old_cursor.store_id
    assert loaded.publication_generation == 2
    assert rotated.get_tick_replay_lineage_handoff() is None
    rotated.close()


@pytest.mark.unit
def test_checkpoint_owner_explicitly_recovers_missing_tick_store_identity(
    tmp_path,
) -> None:
    from flinttrade_data.orderflow_aggregator import OrderFlowAggregator
    from flinttrade_data.orderflow_checkpoint import (
        load_orderflow_checkpoint,
        store_orderflow_checkpoint,
    )
    from flinttrade_data.storage import StorageManager

    db_path = tmp_path / "ticks.duckdb"
    original = StorageManager(str(db_path))
    original.initialise()
    old_cursor = original.get_tick_replay_cursor()
    state = OrderFlowAggregator().export_state()
    store_orderflow_checkpoint(tmp_path, state, old_cursor)
    original.connection.execute("DELETE FROM flinttrade_storage_metadata WHERE key = 'tick_store_id'")
    original.close()

    recovered = StorageManager(str(db_path))
    recovered.initialise()
    new_cursor = recovered.get_tick_replay_cursor()
    recovery = recovered.get_tick_replay_lineage_recovery()
    assert recovery is not None
    owner = _OrderFlowCheckpointOwner(
        recovered,
        OrderFlowAggregator(),
        workspace_dir=tmp_path,
        interval_seconds=0,
    )

    assert owner.persist(force=True) is True

    loaded = load_orderflow_checkpoint(tmp_path)
    assert loaded is not None
    assert loaded.cursor == new_cursor
    assert loaded.cursor.store_id != old_cursor.store_id
    assert loaded.publication_generation == 2
    assert recovered.get_tick_replay_lineage_recovery() is None
    recovered.close()


@pytest.mark.unit
def test_checkpoint_owner_rejects_missing_identity_without_recovery_authority(
    tmp_path,
) -> None:
    from flinttrade_data.orderflow_aggregator import OrderFlowAggregator
    from flinttrade_data.orderflow_checkpoint import store_orderflow_checkpoint
    from flinttrade_data.storage import StorageManager, TickReplayStoreMismatchError

    db_path = tmp_path / "ticks.duckdb"
    original = StorageManager(str(db_path))
    original.initialise()
    old_cursor = original.get_tick_replay_cursor()
    store_orderflow_checkpoint(tmp_path, OrderFlowAggregator().export_state(), old_cursor)
    original.connection.execute("DELETE FROM flinttrade_storage_metadata WHERE key = 'tick_store_id'")
    original.close()

    recovered = StorageManager(str(db_path))
    recovered.initialise()
    recovered.connection.execute("DELETE FROM flinttrade_storage_metadata WHERE key = 'tick_lineage_recovery'")
    owner = _OrderFlowCheckpointOwner(
        recovered,
        OrderFlowAggregator(),
        workspace_dir=tmp_path,
        interval_seconds=0,
    )

    with pytest.raises(TickReplayStoreMismatchError):
        owner.persist(force=True)

    recovered.close()


@pytest.mark.unit
def test_checkpoint_owner_accepts_older_source_across_repeated_rotations(
    tmp_path,
) -> None:
    from flinttrade_data.orderflow_aggregator import OrderFlowAggregator
    from flinttrade_data.orderflow_checkpoint import load_orderflow_checkpoint, store_orderflow_checkpoint
    from flinttrade_data.storage import StorageManager

    db_path = tmp_path / "ticks.duckdb"
    original = StorageManager(str(db_path))
    original.initialise()
    original_cursor = original.get_tick_replay_cursor()
    state = OrderFlowAggregator().export_state()
    store_orderflow_checkpoint(tmp_path, state, original_cursor)
    original.connection.execute("DELETE FROM flinttrade_storage_metadata WHERE key = 'tick_pruned_ingest_high_water'")
    original.close()

    first_rotation = StorageManager(str(db_path))
    first_rotation.initialise()
    first_rotation.connection.execute("DELETE FROM flinttrade_storage_metadata WHERE key = 'tick_pruned_before_utc'")
    first_rotation.close()

    second_rotation = StorageManager(str(db_path))
    second_rotation.initialise()
    final_cursor = second_rotation.get_tick_replay_cursor()
    handoff = second_rotation.get_tick_replay_lineage_handoff()
    assert handoff is not None
    assert original_cursor.store_id in handoff.source_store_ids
    owner = _OrderFlowCheckpointOwner(
        second_rotation,
        OrderFlowAggregator(),
        workspace_dir=tmp_path,
        interval_seconds=0,
    )

    assert owner.persist(force=True) is True

    loaded = load_orderflow_checkpoint(tmp_path)
    assert loaded is not None
    assert loaded.cursor == final_cursor
    assert loaded.publication_generation == 2
    assert second_rotation.get_tick_replay_lineage_handoff() is None
    second_rotation.close()


@pytest.mark.unit
def test_checkpoint_owner_uses_immediate_predecessor_after_publication_before_ack(
    tmp_path,
) -> None:
    from flinttrade_data.orderflow_aggregator import OrderFlowAggregator
    from flinttrade_data.orderflow_checkpoint import load_orderflow_checkpoint, store_orderflow_checkpoint
    from flinttrade_data.storage import StorageManager

    db_path = tmp_path / "ticks.duckdb"
    original = StorageManager(str(db_path))
    original.initialise()
    original_cursor = original.get_tick_replay_cursor()
    state = OrderFlowAggregator().export_state()
    store_orderflow_checkpoint(tmp_path, state, original_cursor)
    original.connection.execute("DELETE FROM flinttrade_storage_metadata WHERE key = 'tick_pruned_ingest_high_water'")
    original.close()

    first_rotation = StorageManager(str(db_path))
    first_rotation.initialise()
    first_cursor = first_rotation.get_tick_replay_cursor()
    store_orderflow_checkpoint(
        tmp_path,
        state,
        first_cursor,
        handoff_from_store_id=original_cursor.store_id,
        owner_epoch="12345678-1234-5678-1234-567812345678",
        expected_generation=1,
    )
    first_rotation.connection.execute("DELETE FROM flinttrade_storage_metadata WHERE key = 'tick_pruned_before_utc'")
    first_rotation.close()

    second_rotation = StorageManager(str(db_path))
    second_rotation.initialise()
    final_cursor = second_rotation.get_tick_replay_cursor()
    handoff = second_rotation.get_tick_replay_lineage_handoff()
    assert handoff is not None
    assert handoff.from_store_id == first_cursor.store_id
    owner = _OrderFlowCheckpointOwner(
        second_rotation,
        OrderFlowAggregator(),
        workspace_dir=tmp_path,
        interval_seconds=0,
    )

    assert owner.persist(force=True) is True

    loaded = load_orderflow_checkpoint(tmp_path)
    assert loaded is not None
    assert loaded.cursor == final_cursor
    assert loaded.publication_generation == 3
    assert second_rotation.get_tick_replay_lineage_handoff() is None
    second_rotation.close()


@pytest.mark.unit
def test_restart_repairs_missing_handoff_evidence_before_superseding_and_acknowledging(tmp_path) -> None:
    import flinttrade_data.orderflow_checkpoint as checkpoint_module
    from flinttrade_data.orderflow_aggregator import OrderFlowAggregator
    from flinttrade_data.orderflow_checkpoint import load_orderflow_checkpoint, store_orderflow_checkpoint
    from flinttrade_data.storage import StorageManager

    db_path = tmp_path / "ticks.duckdb"
    original = StorageManager(str(db_path))
    original.initialise()
    old_cursor = original.get_tick_replay_cursor()
    state = OrderFlowAggregator().export_state()
    store_orderflow_checkpoint(tmp_path, state, old_cursor)
    original.connection.execute("DELETE FROM flinttrade_storage_metadata WHERE key = 'tick_pruned_ingest_high_water'")
    original.close()

    rotated = StorageManager(str(db_path))
    rotated.initialise()
    new_cursor = rotated.get_tick_replay_cursor()
    handoff = rotated.get_tick_replay_lineage_handoff()
    assert handoff is not None
    store_orderflow_checkpoint(
        tmp_path,
        state,
        new_cursor,
        handoff_from_store_id=old_cursor.store_id,
        owner_epoch="12345678-1234-5678-1234-567812345678",
        expected_generation=1,
    )
    evidence_path = tmp_path / checkpoint_module.LINEAGE_EVIDENCE_FILENAME
    evidence_path.unlink()
    loaded_without_evidence = load_orderflow_checkpoint(tmp_path)
    assert loaded_without_evidence is not None
    assert loaded_without_evidence.lineage_handoff_evidence is not None
    assert evidence_path.exists() is False
    rotated.close()

    restarted = StorageManager(str(db_path))
    restarted.initialise()
    assert restarted.get_tick_replay_lineage_handoff() == handoff
    owner = _OrderFlowCheckpointOwner(
        restarted,
        OrderFlowAggregator(),
        workspace_dir=tmp_path,
        interval_seconds=0,
    )

    assert owner.persist(force=True) is True

    evidence = json.loads(evidence_path.read_bytes())
    assert [record["to_generation"] for record in evidence["records"]] == [2]
    published = load_orderflow_checkpoint(tmp_path)
    assert published is not None
    assert published.publication_generation == 3
    assert restarted.get_tick_replay_lineage_handoff() is None
    restarted.close()


@pytest.mark.unit
@pytest.mark.parametrize("evidence_state", ["missing", "conflicting"])
def test_checkpoint_owner_retains_exact_lineage_obligation_until_acknowledged(
    tmp_path,
    evidence_state: str,
) -> None:
    import flinttrade_data.orderflow_checkpoint as checkpoint_module
    from flinttrade_data.orderflow_checkpoint import (
        OrderFlowCheckpointCorruptError,
        load_orderflow_checkpoint,
        store_orderflow_checkpoint,
    )
    from flinttrade_data.storage import TickReplayLineageHandoff

    previous = TickReplayCursor("12345678-1234-4abc-8def-1234567890ab", 100)
    replacement = TickReplayCursor("87654321-4321-4cba-8fed-ba0987654321", 100)
    state = {"version": 1, "identities": []}
    store_orderflow_checkpoint(
        tmp_path,
        state,
        previous,
        owner_epoch="aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa",
        expected_generation=0,
    )
    handoff = TickReplayLineageHandoff(previous.store_id, replacement.store_id)
    storage = MagicMock()
    storage.get_tick_replay_cursor.return_value = replacement
    storage.get_tick_replay_lineage_handoff.return_value = handoff
    storage.get_tick_replay_lineage_recovery.return_value = None
    storage.acknowledge_tick_replay_lineage_handoff.side_effect = [
        RuntimeError("simulated acknowledgement failure"),
        True,
    ]
    orderflow = MagicMock()
    orderflow.export_state.return_value = state
    owner = _OrderFlowCheckpointOwner(storage, orderflow, workspace_dir=tmp_path, interval_seconds=0)

    with pytest.raises(RuntimeError, match="acknowledgement failure"):
        owner.persist(force=True)

    published = load_orderflow_checkpoint(tmp_path)
    assert published is not None
    assert published.publication_generation == 2
    assert published.lineage_handoff_evidence is not None
    assert owner._handoff_from_store_id == previous.store_id
    assert owner._pending_checkpoint_publication is not None
    evidence_path = tmp_path / checkpoint_module.LINEAGE_EVIDENCE_FILENAME
    original_evidence = evidence_path.read_bytes()
    if evidence_state == "missing":
        evidence_path.unlink()
    else:
        evidence = json.loads(original_evidence)
        evidence["records"][0]["prior_payload_hash"] = "0" * 64
        evidence_path.write_text(json.dumps(evidence), encoding="utf-8")

    if evidence_state == "conflicting":
        with pytest.raises(OrderFlowCheckpointCorruptError, match="does not match"):
            owner.persist(force=True)
        assert storage.acknowledge_tick_replay_lineage_handoff.call_count == 1
        assert load_orderflow_checkpoint(tmp_path).publication_generation == 2
        evidence_path.write_bytes(original_evidence)

    assert owner.persist(force=True) is True

    acknowledged = load_orderflow_checkpoint(tmp_path)
    assert acknowledged is not None
    assert acknowledged.publication_generation == 2
    assert owner._handoff_from_store_id is None
    assert owner._pending_checkpoint_publication is None
    assert storage.acknowledge_tick_replay_lineage_handoff.call_count == 2
    assert [record["to_generation"] for record in json.loads(evidence_path.read_bytes())["records"]] == [2]


@pytest.mark.unit
@pytest.mark.skipif(
    os.name == "nt",
    reason="Windows publishes write-through; the parent-directory fsync path is POSIX-only",
)
def test_checkpoint_owner_retries_uncertain_publication_before_newer_live_state(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path,
) -> None:
    import flinttrade_data.orderflow_checkpoint as checkpoint_module

    store_id = "12345678-1234-5678-1234-567812345678"
    first_cursor = TickReplayCursor(store_id=store_id, ingest_seq=17)
    advanced_cursor = TickReplayCursor(store_id=store_id, ingest_seq=18)
    first_state = {"version": 1, "identities": [{"symbol": "FIRST"}]}
    advanced_state = {"version": 1, "identities": [{"symbol": "ADVANCED"}]}
    storage = MagicMock()
    storage.get_tick_replay_cursor.side_effect = [first_cursor, advanced_cursor]
    storage.get_tick_replay_lineage_handoff.return_value = None
    storage.get_tick_replay_lineage_recovery.return_value = None
    orderflow = MagicMock()
    orderflow.export_state.return_value = first_state
    owner = _OrderFlowCheckpointOwner(
        storage,
        orderflow,
        workspace_dir=tmp_path,
        interval_seconds=0,
    )
    real_fsync_parent = checkpoint_module._fsync_parent_directory
    calls = 0

    def fail_once(path) -> None:
        nonlocal calls
        calls += 1
        if calls == 1:
            raise OSError("injected post-rename directory fsync failure")
        real_fsync_parent(path)

    monkeypatch.setattr(checkpoint_module, "_fsync_parent_directory", fail_once)

    with pytest.raises(checkpoint_module.OrderFlowCheckpointWriteError):
        owner.persist(force=True)

    published = checkpoint_module.load_orderflow_checkpoint(tmp_path)
    assert published is not None
    assert published.cursor == first_cursor
    assert published.orderflow_state == first_state
    assert published.publication_generation == 1

    orderflow.export_state.return_value = advanced_state
    assert owner.persist(force=True) is True

    recovered = checkpoint_module.load_orderflow_checkpoint(tmp_path)
    assert recovered is not None
    assert recovered.cursor == first_cursor
    assert recovered.orderflow_state == first_state
    assert recovered.publication_generation == 1

    assert owner.persist(force=True) is True
    advanced = checkpoint_module.load_orderflow_checkpoint(tmp_path)
    assert advanced is not None
    assert advanced.cursor == advanced_cursor
    assert advanced.orderflow_state == advanced_state
    assert advanced.publication_generation == 2


@pytest.mark.unit
def test_checkpoint_owner_never_replaces_a_future_checkpoint(tmp_path) -> None:
    from flinttrade_data.orderflow_checkpoint import (
        load_orderflow_checkpoint,
        store_orderflow_checkpoint,
    )
    from flinttrade_data.storage import TickReplayCursorAheadError

    current = TickReplayCursor("12345678-1234-4abc-8def-1234567890ab", 1)
    future = TickReplayCursor(current.store_id, 2)
    future_state = {"version": 1, "identities": [{"symbol": "FUTURE"}]}
    store_orderflow_checkpoint(tmp_path, future_state, future)
    storage = MagicMock()
    storage.get_tick_replay_cursor.return_value = current
    storage.get_tick_replay_lineage_handoff.return_value = None
    storage.get_tick_replay_lineage_recovery.return_value = None
    storage.validate_tick_replay_cursor.side_effect = TickReplayCursorAheadError("cursor is ahead of tick storage")
    orderflow = MagicMock()
    orderflow.export_state.return_value = {"version": 1, "identities": []}
    owner = _OrderFlowCheckpointOwner(
        storage,
        orderflow,
        workspace_dir=tmp_path,
        interval_seconds=0,
    )

    with pytest.raises(TickReplayCursorAheadError):
        owner.persist(force=True)

    loaded = load_orderflow_checkpoint(tmp_path)
    assert loaded is not None
    assert loaded.cursor == future
    assert loaded.orderflow_state == future_state


@pytest.mark.unit
def test_restore_binds_publication_generation_before_a_later_publisher_can_advance(tmp_path) -> None:
    from flinttrade_data.orderflow_aggregator import OrderFlowAggregator
    from flinttrade_data.orderflow_checkpoint import (
        OrderFlowCheckpointWriteError,
        load_orderflow_checkpoint,
        store_orderflow_checkpoint,
    )
    from flinttrade_data.storage import StorageManager

    storage = StorageManager(str(tmp_path / "ticks.duckdb"))
    storage.initialise()
    cursor = storage.get_tick_replay_cursor()
    source = OrderFlowAggregator()
    source.add_tick("RELIANCE", 100.0, 1, "BUY", exchange="NSE", timestamp=1_786_557_600.0)
    store_orderflow_checkpoint(tmp_path, source.export_state(), cursor)
    restored = OrderFlowAggregator()
    owner = _OrderFlowCheckpointOwner(storage, restored, workspace_dir=tmp_path, interval_seconds=0)

    summary = _prepare_tick_orderflow_state(
        storage,
        restored,
        [{"exchange": "NSE", "symbol": "RELIANCE"}],
        now=1_786_557_601.0,
        workspace_dir=tmp_path,
        checkpoint_owner=owner,
    )
    newer = OrderFlowAggregator()
    newer.add_tick("RELIANCE", 200.0, 2, "SELL", exchange="NSE", timestamp=1_786_557_600.0)
    store_orderflow_checkpoint(
        tmp_path,
        newer.export_state(),
        cursor,
        owner_epoch="aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa",
        expected_generation=1,
    )

    assert summary["checkpoint_restored"] == 1
    with pytest.raises(OrderFlowCheckpointWriteError, match="generation"):
        owner.persist(force=True)

    published = load_orderflow_checkpoint(tmp_path)
    assert published is not None
    assert published.orderflow_state == newer.export_state()
    assert published.publication_generation == 2
    storage.close()


@pytest.mark.unit
@pytest.mark.parametrize("transition", ["handoff", "missing_identity"])
def test_prepare_consumes_valid_lineage_authority_before_reset(tmp_path, transition: str) -> None:
    from flinttrade_data.orderflow_aggregator import OrderFlowAggregator
    from flinttrade_data.orderflow_checkpoint import load_orderflow_checkpoint, store_orderflow_checkpoint
    from flinttrade_data.storage import StorageManager

    db_path = tmp_path / "ticks.duckdb"
    original = StorageManager(str(db_path))
    original.initialise()
    old_cursor = original.get_tick_replay_cursor()
    source = OrderFlowAggregator()
    source.add_tick("RELIANCE", 100.0, 7, "BUY", exchange="NSE", timestamp=1_786_557_600.0)
    store_orderflow_checkpoint(tmp_path, source.export_state(), old_cursor)
    metadata_key = "tick_pruned_ingest_high_water" if transition == "handoff" else "tick_store_id"
    original.connection.execute(
        "DELETE FROM flinttrade_storage_metadata WHERE key = ?",
        [metadata_key],
    )
    original.close()

    rotated = StorageManager(str(db_path))
    rotated.initialise()
    restored = OrderFlowAggregator()
    owner = _OrderFlowCheckpointOwner(rotated, restored, workspace_dir=tmp_path, interval_seconds=0)

    summary = _prepare_tick_orderflow_state(
        rotated,
        restored,
        [{"exchange": "NSE", "symbol": "RELIANCE"}],
        now=1_786_557_601.0,
        workspace_dir=tmp_path,
        checkpoint_owner=owner,
    )

    assert summary["checkpoint_restored"] == 1
    assert summary["checkpoint_failures"] == 0
    assert sum(bucket.total_volume for bucket in restored.get_footprint("RELIANCE", exchange="NSE")) == 7
    assert owner.persist(force=True) is True
    published = load_orderflow_checkpoint(tmp_path)
    assert published is not None
    assert published.cursor.store_id == rotated.get_tick_replay_cursor().store_id
    assert rotated.get_tick_replay_lineage_handoff() is None
    assert rotated.get_tick_replay_lineage_recovery() is None
    rotated.close()


@pytest.mark.unit
def test_pristine_replacement_store_can_supersede_workspace_checkpoint_once(tmp_path) -> None:
    from flinttrade_data.orderflow_aggregator import OrderFlowAggregator
    from flinttrade_data.orderflow_checkpoint import load_orderflow_checkpoint, store_orderflow_checkpoint
    from flinttrade_data.storage import StorageManager

    original = StorageManager(str(tmp_path / "old.duckdb"))
    original.initialise()
    source = OrderFlowAggregator()
    source.add_tick("RELIANCE", 100.0, 7, "BUY", exchange="NSE", timestamp=1_786_557_600.0)
    store_orderflow_checkpoint(tmp_path, source.export_state(), original.get_tick_replay_cursor())
    original.close()
    replacement = StorageManager(str(tmp_path / "replacement.duckdb"))
    replacement.initialise()
    recovery = replacement.get_tick_replay_lineage_recovery()
    assert recovery is not None
    assert recovery.reason == "pristine_store_replacement"
    restored = OrderFlowAggregator()
    owner = _OrderFlowCheckpointOwner(replacement, restored, workspace_dir=tmp_path, interval_seconds=0)

    summary = _prepare_tick_orderflow_state(
        replacement,
        restored,
        [{"exchange": "NSE", "symbol": "RELIANCE"}],
        now=1_786_557_601.0,
        workspace_dir=tmp_path,
        checkpoint_owner=owner,
    )
    assert summary["checkpoint_restored"] == 1
    assert owner.persist(force=True) is True

    published = load_orderflow_checkpoint(tmp_path)
    assert published is not None
    assert published.cursor.store_id == replacement.get_tick_replay_cursor().store_id
    assert replacement.get_tick_replay_lineage_recovery() is None
    replacement.close()


@pytest.mark.unit
def test_pristine_replacement_authority_rejects_a_non_pristine_store(tmp_path) -> None:
    from datetime import datetime

    from flinttrade_data.orderflow_aggregator import OrderFlowAggregator
    from flinttrade_data.orderflow_checkpoint import store_orderflow_checkpoint
    from flinttrade_data.storage import StorageManager, TickReplayStoreMismatchError

    original = StorageManager(str(tmp_path / "old.duckdb"))
    original.initialise()
    store_orderflow_checkpoint(tmp_path, OrderFlowAggregator().export_state(), original.get_tick_replay_cursor())
    original.close()
    replacement = StorageManager(str(tmp_path / "replacement.duckdb"))
    replacement.initialise()
    replacement.insert_tick(
        datetime(2026, 8, 12, 4, 0),
        "RELIANCE",
        "NSE",
        "quote",
        ltp=100.0,
        volume=1,
        timestamp_provenance="source",
    )
    owner = _OrderFlowCheckpointOwner(
        replacement,
        OrderFlowAggregator(),
        workspace_dir=tmp_path,
        interval_seconds=0,
    )

    with pytest.raises(TickReplayStoreMismatchError):
        owner.persist(force=True)

    replacement.close()


@pytest.mark.unit
def test_missing_identity_with_unknown_prune_history_never_attests_complete_prefix(tmp_path) -> None:
    from datetime import datetime

    from flinttrade_data.orderflow_aggregator import OrderFlowAggregator
    from flinttrade_data.orderflow_checkpoint import store_orderflow_checkpoint
    from flinttrade_data.storage import StorageManager

    db_path = tmp_path / "ticks.duckdb"
    original = StorageManager(str(db_path))
    original.initialise()
    old_cursor = original.get_tick_replay_cursor()
    store_orderflow_checkpoint(tmp_path, OrderFlowAggregator().export_state(), old_cursor)
    original.insert_tick(
        datetime(2026, 8, 12, 4, 0),
        "RELIANCE",
        "NSE",
        "quote",
        ltp=100.0,
        volume=1,
        timestamp_provenance="source",
    )
    original.connection.execute("DELETE FROM flinttrade_storage_metadata WHERE key IN (?, ?, ?)", [
        "tick_store_id",
        "tick_pruned_ingest_high_water",
        "tick_pruned_before_utc",
    ])
    original.close()
    recovered = StorageManager(str(db_path))
    recovered.initialise()
    orderflow = MagicMock()
    orderflow.replay_current_session_tail.return_value = {"restored_ticks": 0, "skipped_ticks": 0}
    owner = _OrderFlowCheckpointOwner(recovered, orderflow, workspace_dir=tmp_path, interval_seconds=0)

    summary = _prepare_tick_orderflow_state(
        recovered,
        orderflow,
        [{"exchange": "NSE", "symbol": "RELIANCE"}],
        now=1_786_557_600.0,
        workspace_dir=tmp_path,
        checkpoint_owner=owner,
    )

    assert summary["checkpoint_failures"] == 1
    assert summary["restore_failures"] == 1
    orderflow.replay_current_session_tail.assert_not_called()
    recovered.close()


@pytest.mark.unit
def test_prepare_restores_checkpoint_then_replays_only_the_cursor_tail(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path,
) -> None:
    import flinttrade_data.orderflow_checkpoint as checkpoint_module

    cursor = TickReplayCursor(
        store_id="12345678-1234-5678-1234-567812345678",
        ingest_seq=41,
    )
    state = {
        "version": 1,
        "identities": [{"exchange": "nse", "symbol": "reliance"}],
    }
    monkeypatch.setattr(
        checkpoint_module,
        "load_orderflow_checkpoint",
        lambda workspace_dir: OrderFlowCheckpoint(state, cursor),
    )
    storage_lock = threading.Lock()
    storage = MagicMock()
    storage.prune_ticks.return_value = 3
    storage.get_ticks_after_cursor.return_value = [{"ingest_seq": 42}]
    orderflow = MagicMock()
    orderflow.replay_current_session_tail.return_value = {
        "restored_ticks": 1,
        "skipped_ticks": 0,
    }

    summary = _prepare_tick_orderflow_state(
        storage,
        orderflow,
        [{"exchange": "NSE", "symbol": "RELIANCE"}],
        storage_lock=storage_lock,
        now=1_786_557_600.0,
        workspace_dir=tmp_path,
    )

    assert summary == {
        "pruned_ticks": 3,
        "restored_ticks": 1,
        "skipped_ticks": 0,
        "restore_failures": 0,
        "checkpoint_restored": 1,
        "checkpoint_failures": 0,
        "unavailable_identities": 0,
    }
    storage.validate_tick_replay_cursor.assert_called_once_with(cursor)
    orderflow.restore_state.assert_called_once_with(state, now=1_786_557_600.0)
    orderflow.retain_identities.assert_called_once_with({("NSE", "RELIANCE")})
    storage.get_ticks_after_cursor.assert_called_once_with(
        cursor,
        "RELIANCE",
        "NSE",
        None,
        limit=DEFAULT_RESTORE_MAX_TICKS + 1,
    )
    storage.get_ticks.assert_not_called()
    orderflow.replay_current_session_tail.assert_called_once_with(
        [{"ingest_seq": 42}],
        now=1_786_557_600.0,
        max_ticks=DEFAULT_RESTORE_MAX_TICKS,
        history_complete=True,
    )


@pytest.mark.unit
def test_prepare_merges_retained_session_tail_in_global_ingest_order(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path,
) -> None:
    import flinttrade_data.orderflow_checkpoint as checkpoint_module

    cursor = TickReplayCursor(
        store_id="12345678-1234-5678-1234-567812345678",
        ingest_seq=41,
    )
    state = {
        "version": 1,
        "identities": [
            {
                "exchange": "NSE",
                "symbol": "RELIANCE",
                "last_tick": {"session": "2026-08-11"},
            }
        ],
    }
    monkeypatch.setattr(
        checkpoint_module,
        "load_orderflow_checkpoint",
        lambda _workspace_dir: OrderFlowCheckpoint(state, cursor),
    )
    storage = MagicMock()
    storage.prune_ticks.return_value = 0

    def tail(_cursor, _symbol, _exchange, session_date, *, limit):
        assert session_date is None
        assert limit == DEFAULT_RESTORE_MAX_TICKS + 1
        return [
            {"ingest_seq": 42, "session": "2026-08-12"},
            {"ingest_seq": 43, "session": "2026-08-11"},
        ]

    storage.get_ticks_after_cursor.side_effect = tail
    orderflow = MagicMock()
    orderflow.replay_current_session_tail.return_value = {
        "restored_ticks": 2,
        "skipped_ticks": 0,
    }

    summary = _prepare_tick_orderflow_state(
        storage,
        orderflow,
        [{"exchange": "NSE", "symbol": "RELIANCE"}],
        now=1_786_557_600.0,
        workspace_dir=tmp_path,
    )

    assert summary["restored_ticks"] == 2
    replayed = orderflow.replay_current_session_tail.call_args.args[0]
    assert [row["ingest_seq"] for row in replayed] == [42, 43]
    assert [call.args[3] for call in storage.get_ticks_after_cursor.call_args_list] == [None]


@pytest.mark.unit
def test_checkpoint_tail_query_is_not_partitioned_when_retention_is_disabled(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path,
) -> None:
    import flinttrade_data.orderflow_checkpoint as checkpoint_module

    cursor = TickReplayCursor(
        store_id="12345678-1234-5678-1234-567812345678",
        ingest_seq=41,
    )
    state = {
        "version": 1,
        "identities": [
            {
                "exchange": "NSE",
                "symbol": "RELIANCE",
                "last_tick": {"session": "2026-08-01"},
            }
        ],
    }
    monkeypatch.setattr(
        checkpoint_module,
        "load_orderflow_checkpoint",
        lambda _workspace_dir: OrderFlowCheckpoint(state, cursor),
    )
    storage = MagicMock()
    storage.get_ticks_after_cursor.return_value = [{"ingest_seq": 42}]
    orderflow = MagicMock()
    orderflow.replay_current_session_tail.return_value = {
        "restored_ticks": 1,
        "skipped_ticks": 0,
    }

    summary = _prepare_tick_orderflow_state(
        storage,
        orderflow,
        [{"exchange": "NSE", "symbol": "RELIANCE"}],
        retention_days=0,
        now=1_786_557_600.0,
        workspace_dir=tmp_path,
    )

    assert summary["restored_ticks"] == 1
    storage.prune_ticks.assert_not_called()
    storage.get_ticks_after_cursor.assert_called_once_with(
        cursor,
        "RELIANCE",
        "NSE",
        None,
        limit=DEFAULT_RESTORE_MAX_TICKS + 1,
    )


@pytest.mark.unit
def test_fresh_restore_replays_the_next_session_admitted_by_clock_skew(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path,
) -> None:
    import flinttrade_data.orderflow_checkpoint as checkpoint_module

    monkeypatch.setattr(
        checkpoint_module,
        "load_orderflow_checkpoint",
        lambda _workspace_dir: None,
    )
    now = datetime(2026, 8, 12, 23, 59, 58, tzinfo=ZoneInfo("Asia/Kolkata")).timestamp()
    storage = MagicMock()
    storage.get_tick_replay_cursor.return_value = TickReplayCursor(
        store_id="12345678-1234-5678-1234-567812345678",
        ingest_seq=2,
    )

    def tail(_cursor, _symbol, _exchange, session_date, *, limit):
        assert limit in {
            DEFAULT_RESTORE_MAX_TICKS,
            DEFAULT_RESTORE_MAX_TICKS + 1,
        }
        return [{"ingest_seq": 1 if session_date == "2026-08-12" else 2}]

    storage.get_ticks_after_cursor.side_effect = tail
    orderflow = MagicMock()
    orderflow.replay_current_session_tail.return_value = {
        "restored_ticks": 2,
        "skipped_ticks": 0,
    }

    summary = _prepare_tick_orderflow_state(
        storage,
        orderflow,
        [{"exchange": "NSE", "symbol": "RELIANCE"}],
        now=now,
        workspace_dir=tmp_path,
    )

    assert summary["restored_ticks"] == 2
    assert [query.args[3] for query in storage.get_ticks_after_cursor.call_args_list] == ["2026-08-12", "2026-08-13"]
    orderflow.replay_current_session_tail.assert_called_once()
    orderflow.restore_current_session.assert_not_called()


@pytest.mark.unit
def test_rejected_checkpoint_and_truncated_prefix_reset_unavailable_identity(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path,
) -> None:
    import flinttrade_data.orderflow_checkpoint as checkpoint_module

    def reject_checkpoint(_workspace_dir):
        raise OrderFlowCheckpointChecksumError("injected")

    monkeypatch.setattr(
        checkpoint_module,
        "load_orderflow_checkpoint",
        reject_checkpoint,
    )
    storage = MagicMock()
    storage.prune_ticks.return_value = 0
    storage.get_tick_replay_cursor.return_value = TickReplayCursor(
        store_id="12345678-1234-5678-1234-567812345678",
        ingest_seq=DEFAULT_RESTORE_MAX_TICKS + 1,
    )
    storage.get_ticks_after_cursor.return_value = [
        {"ingest_seq": index} for index in range(DEFAULT_RESTORE_MAX_TICKS + 1)
    ]
    orderflow = MagicMock()

    summary = _prepare_tick_orderflow_state(
        storage,
        orderflow,
        [{"exchange": "NFO", "symbol": "NIFTY"}],
        now=1_786_557_600.0,
        workspace_dir=tmp_path,
    )

    assert summary == {
        "pruned_ticks": 0,
        "restored_ticks": 0,
        "skipped_ticks": 0,
        "restore_failures": 1,
        "checkpoint_restored": 0,
        "checkpoint_failures": 1,
        "unavailable_identities": 1,
    }
    assert orderflow.reset.call_args_list == [
        call(),
        call("NIFTY", exchange="NFO"),
    ]
    orderflow.restore_current_session.assert_not_called()
    storage.get_ticks.assert_not_called()
    zero_cursor = storage.get_ticks_after_cursor.call_args.args[0]
    assert zero_cursor.store_id == "12345678-1234-5678-1234-567812345678"
    assert zero_cursor.ingest_seq == 0
