"""Core wiring for cursor-bound order-flow restart checkpoints."""

from __future__ import annotations

import threading
from unittest.mock import MagicMock, call

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
    orderflow = MagicMock()
    orderflow.export_state.return_value = {"version": 1, "identities": []}
    observed: list[tuple[object, object, object]] = []

    def store_checkpoint(workspace_dir, state, replay_cursor) -> None:
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
        "2026-08-12",
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
    storage.get_ticks.return_value = [
        {"ingest_seq": index}
        for index in range(DEFAULT_RESTORE_MAX_TICKS + 1)
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
    storage.get_ticks_after_cursor.assert_not_called()
