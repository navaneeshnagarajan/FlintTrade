"""Tick flush barriers for durable order-flow checkpoints."""

from __future__ import annotations

import threading

from flinttrade_data.tick_recorder import TickRecorder


class _Storage:
    def __init__(self) -> None:
        self.batches: list[list[tuple[object, ...]]] = []

    def insert_ticks_batch(self, rows) -> None:
        self.batches.append(list(rows))


def test_successful_flush_checkpoints_inside_storage_barrier_before_buffer_clear() -> None:
    storage = _Storage()
    storage_lock = threading.Lock()
    events: list[str] = []
    recorder: TickRecorder

    def checkpoint() -> None:
        assert storage_lock.locked()
        assert recorder.pending_tick_count == 1
        assert len(storage.batches) == 1
        events.append("checkpoint")

    recorder = TickRecorder(
        storage=storage,
        storage_lock=storage_lock,
        post_flush_callback=checkpoint,
    )
    recorder._buffer.append(("tick",))

    assert recorder.flush_pending() is True

    assert events == ["checkpoint"]
    assert recorder.pending_tick_count == 0
    assert recorder.persisted_tick_count == 1
    assert recorder.status_snapshot()["checkpoint_error"] == ""


def test_checkpoint_failure_never_reinserts_an_already_committed_batch() -> None:
    storage = _Storage()
    attempts = 0

    def checkpoint() -> None:
        nonlocal attempts
        attempts += 1
        if attempts == 1:
            raise RuntimeError("checkpoint unavailable")

    recorder = TickRecorder(storage=storage, post_flush_callback=checkpoint)
    recorder._buffer.append(("first",))

    assert recorder.flush_pending() is True
    assert storage.batches == [[("first",)]]
    assert recorder.pending_tick_count == 0
    assert recorder.status_snapshot()["checkpoint_error"] == (
        "Order-flow checkpoint failed (RuntimeError)"
    )

    recorder._buffer.append(("second",))
    assert recorder.flush_pending() is True

    assert storage.batches == [[("first",)], [("second",)]]
    assert recorder.persisted_tick_count == 2
    assert recorder.status_snapshot()["checkpoint_error"] == ""
