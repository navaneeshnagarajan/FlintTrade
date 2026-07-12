"""Tests for bounded, durable order-flow checkpoints."""

from __future__ import annotations

import json
import os
import stat
from datetime import datetime, timezone
from pathlib import Path

import pytest

import flinttrade_data.orderflow_checkpoint as checkpoint_module
from flinttrade_data.orderflow_checkpoint import (
    CHECKPOINT_FILENAME,
    OrderFlowCheckpointChecksumError,
    OrderFlowCheckpointCorruptError,
    OrderFlowCheckpointIncompatibleError,
    OrderFlowCheckpointTooLargeError,
    OrderFlowCheckpointValidationError,
    OrderFlowCheckpointWriteError,
    load_orderflow_checkpoint,
    orderflow_checkpoint_path,
    store_orderflow_checkpoint,
)
from flinttrade_data.storage import TickReplayCursor


_CURSOR = TickReplayCursor("12345678-1234-4abc-8def-1234567890ab", 42)
_STATE = {
    "version": 1,
    "config": {"time_bin_seconds": 60, "tick_size": 0.0001},
    "identities": [],
}


def test_checkpoint_round_trip_uses_the_canonical_filename_and_cursor(tmp_path) -> None:
    path = store_orderflow_checkpoint(tmp_path, _STATE, _CURSOR)
    loaded = load_orderflow_checkpoint(tmp_path)

    assert path == tmp_path / CHECKPOINT_FILENAME
    assert path == orderflow_checkpoint_path(tmp_path)
    assert loaded is not None
    assert loaded.orderflow_state == _STATE
    assert loaded.cursor == _CURSOR


def test_parent_capture_load_validate_and_tail_replay_contract(tmp_path) -> None:
    from flinttrade_data.orderflow_aggregator import OrderFlowAggregator
    from flinttrade_data.storage import StorageManager

    db_path = tmp_path / "ticks.duckdb"
    storage = StorageManager(str(db_path))
    storage.initialise()
    source = OrderFlowAggregator()
    timestamp = datetime(2026, 3, 16, 4, 0, tzinfo=timezone.utc)
    for offset, volume in enumerate((1000, 1100)):
        tick_time = timestamp.replace(second=offset)
        storage.insert_tick(
            tick_time,
            "RELIANCE",
            "NSE",
            "quote",
            ltp=100.0 + offset,
            volume=volume,
            timestamp_provenance="source",
        )
        source.feed_market_tick(
            "RELIANCE",
            100.0 + offset,
            volume,
            exchange="NSE",
            timestamp=tick_time.timestamp(),
        )

    cursor = storage.get_tick_replay_cursor()
    store_orderflow_checkpoint(tmp_path, source.export_state(), cursor)
    tail_time = timestamp.replace(second=2)
    storage.insert_tick(
        tail_time,
        "RELIANCE",
        "NSE",
        "quote",
        ltp=102.0,
        volume=1125,
        timestamp_provenance="source",
    )

    loaded = load_orderflow_checkpoint(tmp_path)
    assert loaded is not None
    storage.validate_tick_replay_cursor(loaded.cursor)
    tail = storage.get_ticks_after_cursor(
        loaded.cursor,
        "RELIANCE",
        "NSE",
        "2026-03-16",
        limit=10_001,
    )
    assert len(tail) <= 10_000
    restarted = OrderFlowAggregator()
    restarted.restore_state(loaded.orderflow_state, now=tail_time.timestamp() + 1)
    restarted.replay_current_session_tail(
        tail,
        now=tail_time.timestamp() + 1,
        max_ticks=10_000,
        history_complete=True,
    )

    assert [row["ingest_seq"] for row in tail] == [3]
    assert sum(
        bucket.total_volume
        for bucket in restarted.get_footprint("RELIANCE", exchange="NSE")
    ) == 125
    storage.close()


def test_missing_checkpoint_returns_none(tmp_path) -> None:
    assert load_orderflow_checkpoint(tmp_path) is None


@pytest.mark.skipif(os.name == "nt", reason="POSIX mode bits are not portable to Windows")
def test_checkpoint_replacement_is_owner_read_write_only(tmp_path) -> None:
    path = orderflow_checkpoint_path(tmp_path)
    path.write_text("old", encoding="utf-8")
    path.chmod(0o644)

    store_orderflow_checkpoint(tmp_path, _STATE, _CURSOR)

    assert stat.S_IMODE(path.stat().st_mode) == 0o600


def test_checkpoint_writer_retries_partial_os_writes(tmp_path, monkeypatch) -> None:
    real_write = os.write
    calls = 0

    def partial_write(fd, data):  # noqa: ANN001
        nonlocal calls
        calls += 1
        chunk_size = max(1, len(data) // 3)
        return real_write(fd, data[:chunk_size])

    monkeypatch.setattr(checkpoint_module.os, "write", partial_write)

    store_orderflow_checkpoint(tmp_path, _STATE, _CURSOR)

    assert calls > 1
    assert load_orderflow_checkpoint(tmp_path).orderflow_state == _STATE


def test_torn_json_is_rejected_without_payload_details(tmp_path) -> None:
    secret = "do-not-expose-this-payload"
    orderflow_checkpoint_path(tmp_path).write_text(
        '{"format":"flinttrade.orderflow-checkpoint","payload":{"secret":"' + secret,
        encoding="utf-8",
    )

    with pytest.raises(OrderFlowCheckpointCorruptError) as raised:
        load_orderflow_checkpoint(tmp_path)

    assert secret not in str(raised.value)
    assert raised.value.__cause__ is None


def test_oversized_checkpoint_is_rejected_before_json_parsing(tmp_path) -> None:
    orderflow_checkpoint_path(tmp_path).write_bytes(b"{" + (b"x" * 64))

    with pytest.raises(OrderFlowCheckpointTooLargeError, match="size limit"):
        load_orderflow_checkpoint(tmp_path, max_bytes=32)


def test_wrong_checksum_is_rejected(tmp_path) -> None:
    path = store_orderflow_checkpoint(tmp_path, _STATE, _CURSOR)
    document = json.loads(path.read_text(encoding="utf-8"))
    document["payload"]["orderflow_state"]["version"] = 2
    path.write_text(json.dumps(document), encoding="utf-8")

    with pytest.raises(OrderFlowCheckpointChecksumError, match="checksum"):
        load_orderflow_checkpoint(tmp_path)


@pytest.mark.parametrize(
    ("field", "value"),
    [("format", "other"), ("version", 2), ("version", 1.0)],
)
def test_wrong_outer_format_or_version_is_incompatible(tmp_path, field, value) -> None:
    path = store_orderflow_checkpoint(tmp_path, _STATE, _CURSOR)
    document = json.loads(path.read_text(encoding="utf-8"))
    document[field] = value
    path.write_text(json.dumps(document), encoding="utf-8")

    with pytest.raises(OrderFlowCheckpointIncompatibleError, match="incompatible"):
        load_orderflow_checkpoint(tmp_path)


@pytest.mark.parametrize(
    "state",
    [
        {"version": float("nan")},
        {"version": object()},
    ],
)
def test_non_json_checkpoint_state_is_rejected_before_write(tmp_path, state) -> None:
    with pytest.raises(
        OrderFlowCheckpointValidationError,
        match="not valid JSON",
    ) as raised:
        store_orderflow_checkpoint(tmp_path, state, _CURSOR)

    assert raised.value.__cause__ is None
    assert not orderflow_checkpoint_path(tmp_path).exists()


def test_replace_failure_preserves_the_previous_checkpoint(tmp_path, monkeypatch) -> None:
    path = store_orderflow_checkpoint(tmp_path, _STATE, _CURSOR)
    original = path.read_bytes()
    replacement_state = {**_STATE, "identities": [{"symbol": "RELIANCE"}]}
    monkeypatch.setattr(checkpoint_module.time, "sleep", lambda _delay: None)

    def replace_fails(_source, _target):  # noqa: ANN001
        raise PermissionError("simulated indexer lock")

    monkeypatch.setattr(checkpoint_module.os, "replace", replace_fails)

    with pytest.raises(OrderFlowCheckpointWriteError, match="could not be written"):
        store_orderflow_checkpoint(tmp_path, replacement_state, _CURSOR)

    assert path.read_bytes() == original
    assert list(tmp_path.glob(f".{CHECKPOINT_FILENAME}.*.tmp")) == []


def test_file_fsync_failure_preserves_the_previous_checkpoint(tmp_path, monkeypatch) -> None:
    path = store_orderflow_checkpoint(tmp_path, _STATE, _CURSOR)
    original = path.read_bytes()

    def fsync_fails(_fd):  # noqa: ANN001
        raise OSError("simulated file fsync failure")

    monkeypatch.setattr(checkpoint_module.os, "fsync", fsync_fails)

    with pytest.raises(OrderFlowCheckpointWriteError, match="could not be written"):
        store_orderflow_checkpoint(
            tmp_path,
            {**_STATE, "identities": [{"symbol": "TCS"}]},
            _CURSOR,
        )

    assert path.read_bytes() == original
    assert list(tmp_path.glob(f".{CHECKPOINT_FILENAME}.*.tmp")) == []


def test_replace_retries_transient_windows_style_locks(tmp_path, monkeypatch) -> None:
    real_replace = os.replace
    attempts = 0
    monkeypatch.setattr(checkpoint_module.time, "sleep", lambda _delay: None)

    def flaky_replace(source, target):  # noqa: ANN001
        nonlocal attempts
        attempts += 1
        if attempts < 3:
            raise PermissionError("simulated indexer lock")
        real_replace(source, target)

    monkeypatch.setattr(checkpoint_module.os, "replace", flaky_replace)

    store_orderflow_checkpoint(tmp_path, _STATE, _CURSOR)

    assert attempts == 3
    assert load_orderflow_checkpoint(tmp_path).cursor == _CURSOR


@pytest.mark.parametrize("error_type", [OSError, NotImplementedError])
def test_parent_directory_fsync_is_best_effort(tmp_path, monkeypatch, error_type) -> None:
    def unsupported_directory_fsync(_path: Path) -> None:
        raise error_type("directory fsync unsupported")

    monkeypatch.setattr(
        checkpoint_module,
        "_fsync_parent_directory",
        unsupported_directory_fsync,
    )

    store_orderflow_checkpoint(tmp_path, _STATE, _CURSOR)

    assert load_orderflow_checkpoint(tmp_path).cursor == _CURSOR


def test_excessively_nested_json_is_reported_as_corrupt(tmp_path) -> None:
    nested = '{"x":' * 2_000 + "0" + "}" * 2_000
    orderflow_checkpoint_path(tmp_path).write_text(nested, encoding="utf-8")

    with pytest.raises(OrderFlowCheckpointCorruptError) as raised:
        load_orderflow_checkpoint(tmp_path)

    assert raised.value.__cause__ is None


def test_symlink_checkpoint_is_rejected(tmp_path) -> None:
    if not hasattr(os, "symlink"):
        pytest.skip("symlinks unavailable")
    target = tmp_path / "target.json"
    target.write_text("{}", encoding="utf-8")
    path = orderflow_checkpoint_path(tmp_path)
    try:
        path.symlink_to(target)
    except OSError:
        pytest.skip("symlink creation is not permitted")

    with pytest.raises(OrderFlowCheckpointCorruptError):
        load_orderflow_checkpoint(tmp_path)
