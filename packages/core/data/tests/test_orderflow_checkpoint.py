"""Tests for bounded, durable order-flow checkpoints."""

from __future__ import annotations

import json
import os
import stat
import subprocess
import sys
import threading
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

import flinttrade_data.orderflow_checkpoint as checkpoint_module
from flinttrade_data.orderflow_checkpoint import (
    CHECKPOINT_FILENAME,
    OrderFlowCheckpointChecksumError,
    OrderFlowCheckpointCorruptError,
    OrderFlowCheckpointDurabilityUncertainError,
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
_OWNER_A = "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa"
_OWNER_B = "bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb"
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
    assert loaded.publication_generation == 1
    assert loaded.publication_predecessor_generation == 0


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
    tail_time = timestamp + timedelta(days=1, seconds=2)
    storage.insert_tick(
        tail_time,
        "RELIANCE",
        "NSE",
        "quote",
        ltp=102.0,
        volume=1125,
        timestamp_provenance="source",
    )
    storage.insert_tick(
        tail_time.replace(second=3),
        "RELIANCE",
        "NSE",
        "quote",
        ltp=103.0,
        volume=1200,
        timestamp_provenance="source",
    )

    loaded = load_orderflow_checkpoint(tmp_path)
    assert loaded is not None
    storage.validate_tick_replay_cursor(loaded.cursor)
    tail = storage.get_ticks_after_cursor(
        loaded.cursor,
        "RELIANCE",
        "NSE",
        None,
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

    assert [row["ingest_seq"] for row in tail] == [3, 4]
    assert sum(bucket.total_volume for bucket in restarted.get_footprint("RELIANCE", exchange="NSE")) == 75
    storage.close()


def test_missing_checkpoint_returns_none(tmp_path) -> None:
    assert load_orderflow_checkpoint(tmp_path) is None


def test_checkpoint_load_never_deletes_another_writers_temp_file(tmp_path) -> None:
    in_progress = [tmp_path / f".{CHECKPOINT_FILENAME}.crash-{index}.tmp" for index in range(3)]
    for path in in_progress:
        path.write_bytes(b"partial checkpoint")
    unrelated = tmp_path / ".unrelated.tmp"
    unrelated.write_bytes(b"keep")

    assert load_orderflow_checkpoint(tmp_path) is None

    assert all(path.read_bytes() == b"partial checkpoint" for path in in_progress)
    assert unrelated.read_bytes() == b"keep"


def test_checkpoint_load_removes_only_abandoned_old_temp_files(tmp_path) -> None:
    stale = tmp_path / f".{CHECKPOINT_FILENAME}.stale.tmp"
    live = tmp_path / f".{CHECKPOINT_FILENAME}.live.tmp"
    stale.write_bytes(b"abandoned")
    live.write_bytes(b"in progress")
    old = time.time() - checkpoint_module.STALE_CHECKPOINT_TEMP_AGE_SECONDS - 1
    os.utime(stale, (old, old))

    assert load_orderflow_checkpoint(tmp_path) is None

    assert not stale.exists()
    assert live.read_bytes() == b"in progress"


def test_checkpoint_load_reaps_only_old_lineage_evidence_temp_files(tmp_path) -> None:
    prefix = checkpoint_module.LINEAGE_EVIDENCE_FILENAME
    stale = tmp_path / f".{prefix}.stale.tmp"
    live = tmp_path / f".{prefix}.live.tmp"
    stale.write_bytes(b"abandoned evidence")
    live.write_bytes(b"in progress")
    old = time.time() - checkpoint_module.STALE_CHECKPOINT_TEMP_AGE_SECONDS - 1
    os.utime(stale, (old, old))

    assert load_orderflow_checkpoint(tmp_path) is None

    assert not stale.exists()
    assert live.read_bytes() == b"in progress"


def test_temp_cleanup_enumeration_failure_does_not_hide_valid_checkpoint(
    tmp_path,
    monkeypatch,
) -> None:
    store_orderflow_checkpoint(tmp_path, _STATE, _CURSOR)

    def glob_fails(_self, _pattern):
        raise OSError("simulated directory enumeration failure")

    monkeypatch.setattr(checkpoint_module.Path, "glob", glob_fails)

    loaded = load_orderflow_checkpoint(tmp_path)
    assert loaded is not None
    assert loaded.cursor == _CURSOR


@pytest.mark.skipif(os.name == "nt", reason="POSIX mode bits are not portable to Windows")
def test_checkpoint_replacement_is_owner_read_write_only(tmp_path) -> None:
    path = store_orderflow_checkpoint(tmp_path, _STATE, _CURSOR)
    path.chmod(0o644)

    store_orderflow_checkpoint(
        tmp_path,
        {**_STATE, "identities": [{"symbol": "REPLACEMENT"}]},
        _CURSOR,
    )

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


def test_older_writer_cannot_replace_a_newer_cursor_for_the_same_store(tmp_path) -> None:
    newer = TickReplayCursor(_CURSOR.store_id, 200)
    older = TickReplayCursor(_CURSOR.store_id, 100)
    newer_state = {**_STATE, "identities": [{"symbol": "NEWER"}]}
    older_state = {**_STATE, "identities": [{"symbol": "OLDER"}]}
    store_orderflow_checkpoint(tmp_path, newer_state, newer)

    store_orderflow_checkpoint(tmp_path, older_state, older)

    loaded = load_orderflow_checkpoint(tmp_path)
    assert loaded is not None
    assert loaded.cursor == newer
    assert loaded.orderflow_state == newer_state


def test_smaller_writer_limit_cannot_hide_and_replace_a_newer_checkpoint(tmp_path) -> None:
    newer = TickReplayCursor(_CURSOR.store_id, 200)
    older = TickReplayCursor(_CURSOR.store_id, 100)
    newer_state = {**_STATE, "padding": "x" * 10_000}
    older_state = {**_STATE, "identities": [{"symbol": "OLDER"}]}
    store_orderflow_checkpoint(tmp_path, newer_state, newer)

    store_orderflow_checkpoint(tmp_path, older_state, older, max_bytes=2_048)

    loaded = load_orderflow_checkpoint(tmp_path)
    assert loaded is not None
    assert loaded.cursor == newer
    assert loaded.orderflow_state == newer_state


def test_contended_publication_lock_fails_within_a_finite_deadline(
    tmp_path,
    monkeypatch,
) -> None:
    checkpoint_path = orderflow_checkpoint_path(tmp_path)
    checkpoint_path.parent.mkdir(parents=True, exist_ok=True)
    acquired_path = tmp_path / "lock-acquired"
    holder = subprocess.Popen(
        [
            sys.executable,
            "-c",
            (
                "import sys,time; from pathlib import Path; "
                "from flinttrade_data.orderflow_checkpoint import _checkpoint_publication_lock; "
                "path=Path(sys.argv[1]); acquired=Path(sys.argv[2]); "
                "lock=_checkpoint_publication_lock(path); lock.__enter__(); "
                "acquired.write_text('acquired'); time.sleep(0.5); lock.__exit__(None,None,None)"
            ),
            str(checkpoint_path),
            str(acquired_path),
        ],
    )
    try:
        deadline = time.monotonic() + 5
        while not acquired_path.exists() and time.monotonic() < deadline:
            time.sleep(0.01)
        assert acquired_path.exists()
        monkeypatch.setattr(
            checkpoint_module,
            "_PUBLICATION_LOCK_TIMEOUT_SECONDS",
            0.05,
            raising=False,
        )

        with pytest.raises(OrderFlowCheckpointWriteError, match="publication lock"):
            store_orderflow_checkpoint(tmp_path, _STATE, _CURSOR)
    finally:
        try:
            holder.wait(timeout=2)
        except subprocess.TimeoutExpired:
            holder.terminate()
            holder.wait(timeout=2)
    assert holder.returncode == 0


def test_stale_different_lineage_cannot_replace_the_current_checkpoint(tmp_path) -> None:
    current = TickReplayCursor("87654321-4321-4cba-8fed-ba0987654321", 1)
    stale = TickReplayCursor(_CURSOR.store_id, 100)
    current_state = {**_STATE, "identities": [{"symbol": "CURRENT"}]}
    stale_state = {**_STATE, "identities": [{"symbol": "STALE"}]}
    store_orderflow_checkpoint(tmp_path, current_state, current)

    with pytest.raises(OrderFlowCheckpointWriteError, match="lineage"):
        store_orderflow_checkpoint(tmp_path, stale_state, stale)

    loaded = load_orderflow_checkpoint(tmp_path)
    assert loaded is not None
    assert loaded.cursor == current
    assert loaded.orderflow_state == current_state


def test_explicit_lineage_handoff_records_bounded_private_evidence(tmp_path) -> None:
    previous = TickReplayCursor(_CURSOR.store_id, 100)
    replacement = TickReplayCursor("87654321-4321-4cba-8fed-ba0987654321", 1)
    previous_state = {**_STATE, "identities": [{"symbol": "PREVIOUS"}]}
    replacement_state = {**_STATE, "identities": [{"symbol": "REPLACEMENT"}]}
    store_orderflow_checkpoint(
        tmp_path,
        previous_state,
        previous,
        owner_epoch=_OWNER_A,
        expected_generation=0,
    )

    store_orderflow_checkpoint(
        tmp_path,
        replacement_state,
        replacement,
        handoff_from_store_id=previous.store_id,
        owner_epoch=_OWNER_B,
        expected_generation=1,
    )

    loaded = load_orderflow_checkpoint(tmp_path)
    assert loaded is not None
    assert loaded.cursor == replacement
    assert loaded.orderflow_state == replacement_state
    assert loaded.publication_generation == 2
    assert list(tmp_path.glob(f".{CHECKPOINT_FILENAME}.*.quarantine")) == []
    evidence_path = tmp_path / ".orderflow-checkpoint-lineage-evidence-v1.json"
    evidence_raw = evidence_path.read_bytes()
    evidence = json.loads(evidence_raw)
    assert len(evidence["records"]) == 1
    assert previous.store_id.encode() not in evidence_raw
    assert replacement.store_id.encode() not in evidence_raw
    assert b"PREVIOUS" not in evidence_raw
    assert b"REPLACEMENT" not in evidence_raw
    assert stat.S_IMODE(evidence_path.stat().st_mode) == stat.S_IRUSR | stat.S_IWUSR

    with pytest.raises(OrderFlowCheckpointWriteError, match="lineage"):
        store_orderflow_checkpoint(
            tmp_path,
            previous_state,
            TickReplayCursor(previous.store_id, 101),
            owner_epoch=_OWNER_A,
            expected_generation=2,
        )
    assert load_orderflow_checkpoint(tmp_path).cursor == replacement


def test_failed_canonical_handoff_does_not_publish_lineage_evidence(tmp_path, monkeypatch) -> None:
    previous = TickReplayCursor(_CURSOR.store_id, 100)
    replacement = TickReplayCursor("87654321-4321-4cba-8fed-ba0987654321", 1)
    store_orderflow_checkpoint(
        tmp_path,
        _STATE,
        previous,
        owner_epoch=_OWNER_A,
        expected_generation=0,
    )
    checkpoint_path = orderflow_checkpoint_path(tmp_path)
    real_replace = checkpoint_module._replace_with_retry

    def fail_canonical_replace(source, target):  # noqa: ANN001
        if target == checkpoint_path:
            raise PermissionError("simulated canonical replace failure")
        real_replace(source, target)

    monkeypatch.setattr(checkpoint_module, "_replace_with_retry", fail_canonical_replace)

    with pytest.raises(OrderFlowCheckpointWriteError, match="could not be written"):
        store_orderflow_checkpoint(
            tmp_path,
            _STATE,
            replacement,
            handoff_from_store_id=previous.store_id,
            owner_epoch=_OWNER_B,
            expected_generation=1,
        )

    loaded = load_orderflow_checkpoint(tmp_path)
    assert loaded is not None
    assert loaded.cursor == previous
    assert not (tmp_path / ".orderflow-checkpoint-lineage-evidence-v1.json").exists()


def test_post_canonical_evidence_failure_retries_the_exact_publication(tmp_path, monkeypatch) -> None:
    previous = TickReplayCursor(_CURSOR.store_id, 100)
    replacement = TickReplayCursor("87654321-4321-4cba-8fed-ba0987654321", 1)
    replacement_state = {**_STATE, "identities": [{"symbol": "REPLACEMENT"}]}
    store_orderflow_checkpoint(
        tmp_path,
        _STATE,
        previous,
        owner_epoch=_OWNER_A,
        expected_generation=0,
    )
    real_write_evidence = checkpoint_module._write_lineage_handoff_evidence
    attempts = 0

    def fail_once(path, records):  # noqa: ANN001
        nonlocal attempts
        attempts += 1
        if attempts == 1:
            raise OrderFlowCheckpointWriteError("simulated lineage evidence failure")
        real_write_evidence(path, records)

    monkeypatch.setattr(checkpoint_module, "_write_lineage_handoff_evidence", fail_once)

    with pytest.raises(OrderFlowCheckpointDurabilityUncertainError):
        store_orderflow_checkpoint(
            tmp_path,
            replacement_state,
            replacement,
            handoff_from_store_id=previous.store_id,
            owner_epoch=_OWNER_B,
            expected_generation=1,
        )

    published = load_orderflow_checkpoint(tmp_path)
    assert published is not None
    assert published.cursor == replacement
    assert published.publication_generation == 2
    assert not (tmp_path / checkpoint_module.LINEAGE_EVIDENCE_FILENAME).exists()

    store_orderflow_checkpoint(
        tmp_path,
        replacement_state,
        replacement,
        handoff_from_store_id=previous.store_id,
        owner_epoch=_OWNER_B,
        expected_generation=1,
    )

    retried = load_orderflow_checkpoint(tmp_path)
    assert retried is not None
    assert retried.publication_generation == 2
    assert len(json.loads((tmp_path / checkpoint_module.LINEAGE_EVIDENCE_FILENAME).read_bytes())["records"]) == 1
    assert attempts == 2


def test_conflicting_handoff_evidence_blocks_canonical_supersession(tmp_path) -> None:
    previous = TickReplayCursor(_CURSOR.store_id, 100)
    replacement = TickReplayCursor("87654321-4321-4cba-8fed-ba0987654321", 1)
    store_orderflow_checkpoint(
        tmp_path,
        _STATE,
        previous,
        owner_epoch=_OWNER_A,
        expected_generation=0,
    )
    store_orderflow_checkpoint(
        tmp_path,
        _STATE,
        replacement,
        handoff_from_store_id=previous.store_id,
        owner_epoch=_OWNER_B,
        expected_generation=1,
    )
    checkpoint_path = orderflow_checkpoint_path(tmp_path)
    original_checkpoint = checkpoint_path.read_bytes()
    evidence_path = tmp_path / checkpoint_module.LINEAGE_EVIDENCE_FILENAME
    evidence = json.loads(evidence_path.read_bytes())
    evidence["records"][0]["prior_payload_hash"] = "0" * 64
    evidence_path.write_text(json.dumps(evidence), encoding="utf-8")

    with pytest.raises(OrderFlowCheckpointCorruptError, match="does not match"):
        store_orderflow_checkpoint(
            tmp_path,
            {**_STATE, "identities": [{"symbol": "NEWER"}]},
            TickReplayCursor(replacement.store_id, 2),
            owner_epoch=_OWNER_A,
            expected_generation=2,
        )

    assert checkpoint_path.read_bytes() == original_checkpoint


def test_expired_current_handoff_evidence_blocks_canonical_supersession(tmp_path, monkeypatch) -> None:
    previous = TickReplayCursor(_CURSOR.store_id, 100)
    replacement = TickReplayCursor("87654321-4321-4cba-8fed-ba0987654321", 1)
    recorded_at = 1_800_000_000
    monkeypatch.setattr(checkpoint_module.time, "time", lambda: recorded_at)
    store_orderflow_checkpoint(
        tmp_path,
        _STATE,
        previous,
        owner_epoch=_OWNER_A,
        expected_generation=0,
    )
    store_orderflow_checkpoint(
        tmp_path,
        _STATE,
        replacement,
        handoff_from_store_id=previous.store_id,
        owner_epoch=_OWNER_B,
        expected_generation=1,
    )
    checkpoint_path = orderflow_checkpoint_path(tmp_path)
    original_checkpoint = checkpoint_path.read_bytes()
    evidence_path = tmp_path / checkpoint_module.LINEAGE_EVIDENCE_FILENAME
    monkeypatch.setattr(
        checkpoint_module.time,
        "time",
        lambda: recorded_at + checkpoint_module._LINEAGE_EVIDENCE_MAX_AGE_SECONDS + 1,
    )

    loaded = load_orderflow_checkpoint(tmp_path)
    assert loaded is not None
    assert json.loads(evidence_path.read_bytes())["records"] != []
    with pytest.raises(OrderFlowCheckpointCorruptError, match="expired"):
        store_orderflow_checkpoint(
            tmp_path,
            {**_STATE, "identities": [{"symbol": "NEWER"}]},
            TickReplayCursor(replacement.store_id, 2),
            owner_epoch=_OWNER_A,
            expected_generation=2,
        )

    assert checkpoint_path.read_bytes() == original_checkpoint


def test_normal_checkpoint_load_expires_historical_lineage_evidence(tmp_path, monkeypatch) -> None:
    previous = TickReplayCursor(_CURSOR.store_id, 100)
    replacement = TickReplayCursor("87654321-4321-4cba-8fed-ba0987654321", 1)
    recorded_at = 1_800_000_000
    monkeypatch.setattr(checkpoint_module.time, "time", lambda: recorded_at)
    store_orderflow_checkpoint(
        tmp_path,
        _STATE,
        previous,
        owner_epoch=_OWNER_A,
        expected_generation=0,
    )
    store_orderflow_checkpoint(
        tmp_path,
        _STATE,
        replacement,
        handoff_from_store_id=previous.store_id,
        owner_epoch=_OWNER_B,
        expected_generation=1,
    )
    evidence_path = tmp_path / ".orderflow-checkpoint-lineage-evidence-v1.json"
    assert len(json.loads(evidence_path.read_bytes())["records"]) == 1
    successor = TickReplayCursor(replacement.store_id, 2)
    store_orderflow_checkpoint(
        tmp_path,
        _STATE,
        successor,
        owner_epoch=_OWNER_A,
        expected_generation=2,
    )

    monkeypatch.setattr(
        checkpoint_module.time,
        "time",
        lambda: recorded_at + checkpoint_module._LINEAGE_EVIDENCE_MAX_AGE_SECONDS + 1,
    )

    loaded = load_orderflow_checkpoint(tmp_path)
    assert loaded is not None
    assert loaded.cursor == successor
    assert json.loads(evidence_path.read_bytes())["records"] == []


@pytest.mark.parametrize("canonical_state", ["missing", "corrupt"])
def test_lineage_evidence_expiry_does_not_depend_on_a_valid_canonical_checkpoint(
    tmp_path,
    monkeypatch,
    canonical_state: str,
) -> None:
    previous = TickReplayCursor(_CURSOR.store_id, 100)
    replacement = TickReplayCursor("87654321-4321-4cba-8fed-ba0987654321", 1)
    recorded_at = 1_800_000_000
    monkeypatch.setattr(checkpoint_module.time, "time", lambda: recorded_at)
    store_orderflow_checkpoint(
        tmp_path,
        _STATE,
        previous,
        owner_epoch=_OWNER_A,
        expected_generation=0,
    )
    store_orderflow_checkpoint(
        tmp_path,
        _STATE,
        replacement,
        handoff_from_store_id=previous.store_id,
        owner_epoch=_OWNER_B,
        expected_generation=1,
    )
    canonical_path = orderflow_checkpoint_path(tmp_path)
    if canonical_state == "missing":
        canonical_path.unlink()
    else:
        canonical_path.write_bytes(b"not-json")
    monkeypatch.setattr(
        checkpoint_module.time,
        "time",
        lambda: recorded_at + checkpoint_module._LINEAGE_EVIDENCE_MAX_AGE_SECONDS + 1,
    )

    if canonical_state == "missing":
        assert load_orderflow_checkpoint(tmp_path) is None
    else:
        with pytest.raises(OrderFlowCheckpointCorruptError, match="checkpoint is corrupt"):
            load_orderflow_checkpoint(tmp_path)

    evidence_path = tmp_path / checkpoint_module.LINEAGE_EVIDENCE_FILENAME
    assert json.loads(evidence_path.read_bytes())["records"] == []


def test_handoff_evidence_retains_only_a_strict_bounded_history(tmp_path) -> None:
    current_cursor = _CURSOR
    generation = 0
    owner = _OWNER_A
    store_orderflow_checkpoint(
        tmp_path,
        _STATE,
        current_cursor,
        owner_epoch=owner,
        expected_generation=generation,
    )
    generation += 1

    for index in range(20):
        replacement_cursor = TickReplayCursor(
            f"{index + 1:08x}-1234-4abc-8def-{index + 1:012x}",
            index,
        )
        replacement_state = {
            **_STATE,
            "identities": [{"symbol": f"PRIVATE-{index}"}],
        }
        store_orderflow_checkpoint(
            tmp_path,
            replacement_state,
            replacement_cursor,
            handoff_from_store_id=current_cursor.store_id,
            owner_epoch=owner,
            expected_generation=generation,
        )
        current_cursor = replacement_cursor
        generation += 1

    evidence_raw = (tmp_path / ".orderflow-checkpoint-lineage-evidence-v1.json").read_bytes()
    evidence = json.loads(evidence_raw)
    assert len(evidence["records"]) <= 16
    assert len(evidence_raw) <= 64 * 1024
    assert b"PRIVATE-" not in evidence_raw


def test_delayed_equal_cursor_writer_is_rejected_by_predecessor_generation(
    tmp_path,
) -> None:
    initial_state = {**_STATE, "identities": [{"symbol": "INITIAL"}]}
    current_state = {**_STATE, "identities": [{"symbol": "CURRENT"}]}
    stale_state = {**_STATE, "identities": [{"symbol": "STALE"}]}
    store_orderflow_checkpoint(
        tmp_path,
        initial_state,
        _CURSOR,
        owner_epoch=_OWNER_A,
        expected_generation=0,
    )
    stale_ready = threading.Event()
    release_stale = threading.Event()
    stale_errors: list[BaseException] = []

    def delayed_stale_writer() -> None:
        stale_ready.set()
        release_stale.wait(timeout=2)
        try:
            store_orderflow_checkpoint(
                tmp_path,
                stale_state,
                _CURSOR,
                owner_epoch=_OWNER_A,
                expected_generation=1,
            )
        except BaseException as exc:  # pragma: no cover - asserted below
            stale_errors.append(exc)

    stale = threading.Thread(target=delayed_stale_writer)
    stale.start()
    assert stale_ready.wait(timeout=1)
    store_orderflow_checkpoint(
        tmp_path,
        current_state,
        _CURSOR,
        owner_epoch=_OWNER_B,
        expected_generation=1,
    )
    release_stale.set()
    stale.join(timeout=2)

    assert not stale.is_alive()
    assert len(stale_errors) == 1
    assert isinstance(stale_errors[0], OrderFlowCheckpointWriteError)
    assert "generation" in str(stale_errors[0])
    loaded = load_orderflow_checkpoint(tmp_path)
    assert loaded is not None
    assert loaded.orderflow_state == current_state
    assert loaded.publication_generation == 2


def test_corrupt_checkpoint_cannot_be_treated_as_absent_during_publication(
    tmp_path,
) -> None:
    path = orderflow_checkpoint_path(tmp_path)
    path.write_bytes(b"not-json")
    original = path.read_bytes()

    with pytest.raises(OrderFlowCheckpointCorruptError):
        store_orderflow_checkpoint(
            tmp_path,
            _STATE,
            _CURSOR,
            owner_epoch=_OWNER_A,
            expected_generation=0,
        )

    assert path.read_bytes() == original


def test_post_rename_directory_fsync_failure_retries_idempotently(
    tmp_path,
    monkeypatch,
) -> None:
    first_state = {**_STATE, "identities": [{"symbol": "FIRST"}]}
    replacement_state = {**_STATE, "identities": [{"symbol": "REPLACEMENT"}]}
    store_orderflow_checkpoint(
        tmp_path,
        first_state,
        _CURSOR,
        owner_epoch=_OWNER_A,
        expected_generation=0,
    )
    real_fsync_parent = checkpoint_module._fsync_parent_directory
    attempts = 0

    def fail_once(parent):
        nonlocal attempts
        attempts += 1
        if attempts == 1:
            raise OSError("simulated directory durability failure")
        real_fsync_parent(parent)

    monkeypatch.setattr(
        checkpoint_module,
        "_fsync_parent_directory",
        fail_once,
    )

    with pytest.raises(OrderFlowCheckpointWriteError, match="could not be written"):
        store_orderflow_checkpoint(
            tmp_path,
            replacement_state,
            _CURSOR,
            owner_epoch=_OWNER_A,
            expected_generation=1,
        )

    published_after_error = load_orderflow_checkpoint(tmp_path)
    assert published_after_error is not None
    assert published_after_error.orderflow_state == replacement_state
    assert published_after_error.publication_generation == 2

    store_orderflow_checkpoint(
        tmp_path,
        replacement_state,
        _CURSOR,
        owner_epoch=_OWNER_A,
        expected_generation=1,
    )

    retried = load_orderflow_checkpoint(tmp_path)
    assert retried is not None
    assert retried.orderflow_state == replacement_state
    assert retried.publication_generation == 2
    assert attempts == 2


def test_delayed_equal_cursor_writer_publishes_before_later_writer(
    tmp_path,
    monkeypatch,
) -> None:
    first_entered = threading.Event()
    release_first = threading.Event()
    real_write_all = checkpoint_module._write_all
    calls = 0

    def blocking_first_write(fd, data):
        nonlocal calls
        calls += 1
        if calls == 1:
            first_entered.set()
            release_first.wait(timeout=1)
        real_write_all(fd, data)

    monkeypatch.setattr(checkpoint_module, "_write_all", blocking_first_write)
    old_state = {**_STATE, "identities": [{"symbol": "OLD"}]}
    new_state = {**_STATE, "identities": [{"symbol": "NEW"}]}
    errors: list[BaseException] = []

    def store(state):
        try:
            store_orderflow_checkpoint(tmp_path, state, _CURSOR)
        except BaseException as exc:  # pragma: no cover - asserted below
            errors.append(exc)

    first = threading.Thread(target=store, args=(old_state,))
    second = threading.Thread(target=store, args=(new_state,))
    first.start()
    assert first_entered.wait(timeout=1)
    second.start()
    try:
        time.sleep(0.05)
    finally:
        release_first.set()
    first.join(timeout=1)
    second.join(timeout=1)

    assert errors == []
    assert not first.is_alive()
    assert not second.is_alive()
    loaded = load_orderflow_checkpoint(tmp_path)
    assert loaded is not None
    assert loaded.orderflow_state == new_state


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


def test_unsupported_parent_directory_fsync_fails_closed(tmp_path, monkeypatch) -> None:
    def unsupported_directory_fsync(_path: Path) -> None:
        raise NotImplementedError("directory fsync unsupported")

    monkeypatch.setattr(
        checkpoint_module,
        "_fsync_parent_directory",
        unsupported_directory_fsync,
    )

    with pytest.raises(OrderFlowCheckpointDurabilityUncertainError):
        store_orderflow_checkpoint(tmp_path, _STATE, _CURSOR)

    assert load_orderflow_checkpoint(tmp_path).cursor == _CURSOR


def test_windows_replace_uses_atomic_write_through_flags() -> None:
    calls: list[tuple[str, str, int]] = []

    def move_file_ex(source: str, target: str, flags: int) -> int:
        calls.append((source, target, flags))
        return 1

    checkpoint_module._replace_windows_write_through(
        Path("source.tmp"),
        Path("checkpoint.json"),
        move_file_ex=move_file_ex,
        get_last_error=lambda: 0,
    )

    assert calls == [
        (
            "source.tmp",
            "checkpoint.json",
            checkpoint_module._MOVEFILE_REPLACE_EXISTING | checkpoint_module._MOVEFILE_WRITE_THROUGH,
        )
    ]


def test_windows_write_through_failure_does_not_publish_checkpoint(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(checkpoint_module, "_uses_windows_write_through", lambda: True)
    monkeypatch.setattr(
        checkpoint_module,
        "_replace_windows_write_through",
        lambda _source, _target: (_ for _ in ()).throw(OSError("write-through replacement failed")),
    )

    with pytest.raises(OrderFlowCheckpointWriteError, match="could not be written"):
        store_orderflow_checkpoint(tmp_path, _STATE, _CURSOR)

    assert not orderflow_checkpoint_path(tmp_path).exists()


def test_parent_directory_io_failure_is_reported_as_failed_persistence(
    tmp_path,
    monkeypatch,
) -> None:
    def directory_fsync_fails(_path: Path) -> None:
        raise OSError("simulated directory I/O failure")

    monkeypatch.setattr(
        checkpoint_module,
        "_fsync_parent_directory",
        directory_fsync_fails,
    )

    with pytest.raises(OrderFlowCheckpointWriteError, match="could not be written"):
        store_orderflow_checkpoint(tmp_path, _STATE, _CURSOR)


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
