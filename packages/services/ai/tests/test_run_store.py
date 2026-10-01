"""Durable, credential-free evidence for the autonomous Practice harness."""

from __future__ import annotations

import base64
import math
import sqlite3
import threading
from collections.abc import Iterator
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime
from pathlib import Path

import pytest

from flinttrade_ai.run_store import AgentRunStore

pytestmark = pytest.mark.unit


@pytest.fixture
def store() -> Iterator[AgentRunStore]:
    result = AgentRunStore(":memory:")
    yield result
    result.close()


def test_run_and_ordered_events_survive_reopen(tmp_path: Path) -> None:
    """Losing committed run state or event order must fail this test."""
    path = tmp_path / "nested" / "runs.sqlite"
    store = AgentRunStore(path)
    now = datetime(2026, 9, 30, 9, 0, tzinfo=UTC)
    run = store.create_run(run_id="run-1", mode="practice", config={"symbols": ["NIFTY"]}, now=now)
    assert run == {
        "run_id": "run-1",
        "mode": "practice",
        "status": "starting",
        "config": {"symbols": ["NIFTY"]},
        "snapshot": {},
        "error": None,
        "created_at": now.isoformat(timespec="microseconds"),
        "updated_at": now.isoformat(timespec="microseconds"),
    }
    first = store.append_event("run-1", kind="cycle_started", data={"cycle": 1})
    second = store.append_event("run-1", kind="cycle_completed", data={"cycle": 1})
    assert first < second
    updated = store.update_run("run-1", status="completed", snapshot={"cycles": 1})
    store.close()

    reopened = AgentRunStore(str(path))
    try:
        assert reopened.get_run("run-1") == updated
        events = reopened.events("run-1")
        assert [event["seq"] for event in events] == [first, second]
        assert [event["kind"] for event in events] == ["cycle_started", "cycle_completed"]
        assert events[0]["run_id"] == "run-1"
        assert events[0]["data"] == {"cycle": 1}
        assert datetime.fromisoformat(events[0]["created_at"]).tzinfo is not None
        assert reopened.list_runs() == [updated]
        assert reopened.get_run("missing") is None
        assert reopened.events("missing") == []
    finally:
        reopened.close()


def test_database_path_is_stable_read_only_runtime_lock_identity(tmp_path: Path) -> None:
    store = AgentRunStore(tmp_path / "runs.sqlite")
    try:
        assert store.database_path == str((tmp_path / "runs.sqlite").resolve())
        with pytest.raises(AttributeError):
            store.database_path = "other.sqlite"
    finally:
        store.close()


@pytest.mark.parametrize("mode", ["live", "explore", "Practice", "", None, False])
def test_only_practice_runs_can_be_persisted(store: AgentRunStore, mode: object) -> None:
    with pytest.raises(ValueError):
        store.create_run(run_id="run-1", mode=mode, config={})
    assert store.list_runs() == []


@pytest.mark.parametrize("run_id", ["", " ", "x" * 129, "line\nbreak", "../path", 123, None, False])
def test_all_run_identifiers_are_validated(store: AgentRunStore, run_id: object) -> None:
    operations = [
        lambda: store.create_run(run_id=run_id, mode="practice", config={}),
        lambda: store.update_run(run_id, status="failed"),
        lambda: store.append_event(run_id, kind="cycle", data={}),
        lambda: store.get_run(run_id),
        lambda: store.events(run_id),
    ]
    for operation in operations:
        with pytest.raises(ValueError):
            operation()
    assert store.list_runs() == []


@pytest.mark.parametrize("payload", [[], None, {"x": math.nan}, {"x": math.inf}, {"x": -math.inf},
                                        {1: "value"}, {"x": (1, 2)}, {"x": {1, 2}}, {"x": b"bytes"},
                                        {"x": 2**64}, {"x": "a" * (64 * 1024)}])
def test_payloads_are_strict_bounded_finite_json(store: AgentRunStore, payload: object) -> None:
    with pytest.raises(ValueError):
        store.create_run(run_id="bad", mode="practice", config=payload)
    store.create_run(run_id="valid", mode="practice", config={})
    with pytest.raises(ValueError):
        store.append_event("valid", kind="cycle", data=payload)
    if payload is not None:  # None explicitly means retain the previous snapshot.
        with pytest.raises(ValueError):
            store.update_run("valid", status="running", snapshot=payload)
    assert store.get_run("valid")["status"] == "starting"
    assert store.events("valid") == []


def test_cyclic_and_deep_payloads_are_rejected(store: AgentRunStore) -> None:
    cyclic: dict = {}
    cyclic["child"] = cyclic
    deep: dict = {}
    for _ in range(18):
        deep = {"child": deep}
    for payload in [cyclic, deep, {"items": [0] * 5000}]:
        with pytest.raises(ValueError):
            store.create_run(run_id="bad", mode="practice", config=payload)
    assert store.list_runs() == []


@pytest.mark.parametrize("key", ["password", "secret", "token", "authorization", "credentials",
                                    "api_key", "brokerPassword", "ACCESS_TOKEN", "client-secret"])
def test_credential_keys_are_rejected_recursively(store: AgentRunStore, key: str) -> None:
    payload = {"nested": [{key: "must-never-be-written"}]}
    with pytest.raises(ValueError, match="credential"):
        store.create_run(run_id="bad", mode="practice", config=payload)
    store.create_run(run_id="valid", mode="practice", config={})
    with pytest.raises(ValueError, match="credential"):
        store.append_event("valid", kind="cycle", data=payload)
    with pytest.raises(ValueError, match="credential"):
        store.update_run("valid", status="running", snapshot=payload)
    assert store.get_run("valid")["snapshot"] == {}
    assert store.events("valid") == []


@pytest.mark.parametrize("value", [
    "eyJhbGciOiJIUzI1NiJ9.eyJzdWIiOiJleGFtcGxlIn0.c2lnbmF0dXJl",
    "response: eyJhbGciOiJub25lIn0.eyJzdWIiOiJleGFtcGxlIn0.",
    "Bearer opaque-example-auth-value",
])
def test_auth_strings_never_reach_evidence(store: AgentRunStore, value: str) -> None:
    with pytest.raises(ValueError, match="credential"):
        store.create_run(run_id="bad", mode="practice", config={"message": value})
    store.create_run(run_id="valid", mode="practice", config={})
    with pytest.raises(ValueError, match="credential"):
        store.append_event("valid", kind="cycle", data={"message": value})
    with pytest.raises(ValueError, match="credential"):
        store.update_run("valid", status="failed", error=value)
    assert store.get_run("valid")["error"] is None


def test_payloads_are_detached_from_callers(store: AgentRunStore) -> None:
    config = {"symbols": ["NIFTY"], "enabled": True, "weight": 0.5, "extra": None}
    created = store.create_run(run_id="run-1", mode="practice", config=config)
    config["symbols"].append("BANKNIFTY")
    created["config"]["symbols"].clear()
    assert store.get_run("run-1")["config"]["symbols"] == ["NIFTY"]
    snapshot = {"cycles": [1]}
    store.update_run("run-1", status="running", snapshot=snapshot)
    snapshot["cycles"].append(2)
    assert store.update_run("run-1", status="waiting")["snapshot"] == {"cycles": [1]}


@pytest.mark.parametrize("now", ["2026-09-30", datetime(2026, 9, 30), False])
def test_timestamp_requires_aware_datetime(store: AgentRunStore, now: object) -> None:
    with pytest.raises(ValueError):
        store.create_run(run_id="run-1", mode="practice", config={}, now=now)


@pytest.mark.parametrize("kind", ["", " ", "x" * 129, None, 1, "line\nbreak"])
def test_event_kind_is_bounded_identifier_text(store: AgentRunStore, kind: object) -> None:
    store.create_run(run_id="run-1", mode="practice", config={})
    with pytest.raises(ValueError):
        store.append_event("run-1", kind=kind, data={})
    assert store.events("run-1") == []


@pytest.mark.parametrize("error", [False, 1, {}, "x" * 4097])
def test_error_is_bounded_text(store: AgentRunStore, error: object) -> None:
    store.create_run(run_id="run-1", mode="practice", config={})
    with pytest.raises(ValueError):
        store.update_run("run-1", status="failed", error=error)
    assert store.get_run("run-1")["status"] == "starting"


def test_unknown_writes_raise_and_leave_no_orphan_events(store: AgentRunStore) -> None:
    with pytest.raises(KeyError):
        store.update_run("missing", status="failed")
    with pytest.raises(KeyError):
        store.append_event("missing", kind="cycle", data={})
    assert store.events("missing") == []


def test_corrupt_existing_database_is_not_replaced(tmp_path: Path) -> None:
    path = tmp_path / "runs.sqlite"
    original = b"not a database and must not be discarded"
    path.write_bytes(original)
    with pytest.raises(sqlite3.DatabaseError):
        AgentRunStore(path)
    assert path.read_bytes() == original


@pytest.mark.parametrize("status", ["pending", "live", "", None, False, [], {}])
def test_unknown_status_is_rejected_without_mutation(store: AgentRunStore, status: object) -> None:
    original = store.create_run(run_id="run-1", mode="practice", config={})
    with pytest.raises(ValueError):
        store.update_run("run-1", status=status, snapshot={"cycles": 1})
    assert store.get_run("run-1") == original


@pytest.mark.parametrize("status", ["starting", "waiting", "running", "stopping", "reconciliation_required"])
def test_every_active_status_blocks_another_run(store: AgentRunStore, status: str) -> None:
    store.create_run(run_id="run-1", mode="practice", config={})
    store.update_run("run-1", status=status)
    with pytest.raises(RuntimeError, match="active"):
        store.create_run(run_id="run-2", mode="practice", config={})
    assert len(store.list_runs()) == 1


@pytest.mark.parametrize("terminal", ["completed", "failed", "stopped"])
@pytest.mark.parametrize("new_status", ["starting", "running", "waiting", "stopping", "reconciliation_required"])
def test_terminal_runs_cannot_resume(store: AgentRunStore, terminal: str, new_status: str) -> None:
    store.create_run(run_id="run-1", mode="practice", config={})
    original = store.update_run("run-1", status=terminal)
    with pytest.raises(ValueError, match="transition"):
        store.update_run("run-1", status=new_status)
    assert store.get_run("run-1") == original
    assert store.create_run(run_id="run-2", mode="practice", config={})["status"] == "starting"


@pytest.mark.parametrize("source,target", [
    ("running", "starting"), ("waiting", "starting"), ("stopping", "running"),
    ("stopping", "waiting"), ("reconciliation_required", "running"),
    ("reconciliation_required", "starting"), ("reconciliation_required", "completed"),
    ("completed", "failed"),
])
def test_illegal_lifecycle_transitions_leave_run_intact(store: AgentRunStore, source: str, target: str) -> None:
    store.create_run(run_id="run-1", mode="practice", config={})
    original = store.update_run("run-1", status=source)
    with pytest.raises(ValueError, match="transition"):
        store.update_run("run-1", status=target, error="must not overwrite")
    assert store.get_run("run-1") == original


def test_waiting_running_stopping_lifecycle_and_same_state_updates(store: AgentRunStore) -> None:
    store.create_run(run_id="run-1", mode="practice", config={})
    for status in ["waiting", "running", "running", "waiting", "running", "stopping", "stopped"]:
        assert store.update_run("run-1", status=status)["status"] == status


def test_duplicate_run_id_cannot_replace_evidence(store: AgentRunStore) -> None:
    store.create_run(run_id="run-1", mode="practice", config={"original": True})
    original = store.update_run("run-1", status="completed")
    with pytest.raises(ValueError, match="already exists"):
        store.create_run(run_id="run-1", mode="practice", config={"replacement": True})
    assert store.get_run("run-1") == original


@pytest.mark.parametrize("independent_connections", [False, True])
def test_concurrent_starts_admit_exactly_one_run(tmp_path: Path, independent_connections: bool) -> None:
    first = AgentRunStore(tmp_path / "runs.sqlite")
    stores = [first, AgentRunStore(tmp_path / "runs.sqlite") if independent_connections else first]
    barrier = threading.Barrier(2)

    def start(index: int) -> str:
        barrier.wait(timeout=5)
        try:
            stores[index].create_run(run_id=f"run-{index}", mode="practice", config={})
        except RuntimeError as exc:
            assert "active" in str(exc)
            return "conflict"
        return "started"

    try:
        with ThreadPoolExecutor(max_workers=2) as pool:
            outcomes = list(pool.map(start, range(2)))
        assert sorted(outcomes) == ["conflict", "started"]
        assert len(first.list_runs()) == 1
    finally:
        for item in set(stores):
            item.close()


def test_partial_unique_index_guards_independent_database_writes(tmp_path: Path) -> None:
    path = tmp_path / "runs.sqlite"
    store = AgentRunStore(path)
    try:
        store.create_run(run_id="run-1", mode="practice", config={})
        with sqlite3.connect(path) as conn:
            with pytest.raises(sqlite3.IntegrityError):
                conn.execute(
                    """INSERT INTO agent_runs
                    SELECT 'bypass', mode, status, config, snapshot, error, created_at, updated_at
                    FROM agent_runs WHERE run_id = 'run-1'"""
                )
        assert len(store.list_runs()) == 1
    finally:
        store.close()


def test_concurrent_event_writers_do_not_lose_or_duplicate_evidence(tmp_path: Path) -> None:
    path = tmp_path / "runs.sqlite"
    stores = [AgentRunStore(path), AgentRunStore(path)]
    stores[0].create_run(run_id="run-1", mode="practice", config={})

    def append(index: int) -> int:
        return stores[index % 2].append_event("run-1", kind="cycle", data={"cycle": index})

    try:
        with ThreadPoolExecutor(max_workers=8) as pool:
            sequences = list(pool.map(append, range(100)))
        events = stores[0].events("run-1", limit=1000)
        assert len(set(sequences)) == 100
        assert [event["seq"] for event in events] == sorted(sequences)
        assert sorted(event["data"]["cycle"] for event in events) == list(range(100))
    finally:
        for item in stores:
            item.close()


@pytest.mark.parametrize("status", ["starting", "waiting", "running", "stopping"])
def test_recovery_requires_explicit_resolution_and_never_resumes(tmp_path: Path, status: str) -> None:
    path = tmp_path / "runs.sqlite"
    store = AgentRunStore(path)
    store.create_run(run_id="run-1", mode="practice", config={})
    original = store.update_run("run-1", status=status, snapshot={"cycles": 3}, error="interrupted")
    store.close()
    reopened = AgentRunStore(path)
    try:
        assert reopened.get_run("run-1") == original  # Opening alone does not claim ownership or resume.
        assert reopened.recover_interrupted() == 1
        recovered = reopened.get_run("run-1")
        assert recovered["status"] == "reconciliation_required"
        assert recovered["snapshot"] == {"cycles": 3}
        assert recovered["error"] == "interrupted"
        event = reopened.events("run-1")[0]
        assert event["kind"] == "run_interrupted"
        assert event["data"] == {"previous_status": status, "status": "reconciliation_required"}
        assert event["created_at"] == recovered["updated_at"]
        assert reopened.recover_interrupted() == 0
        assert len(reopened.events("run-1")) == 1
        with pytest.raises(RuntimeError, match="active"):
            reopened.create_run(run_id="new", mode="practice", config={})
        reopened.update_run("run-1", status="stopped")
        assert reopened.create_run(run_id="new", mode="practice", config={})["status"] == "starting"
    finally:
        reopened.close()


def test_recovery_does_not_touch_terminal_runs(store: AgentRunStore) -> None:
    originals = []
    for status in ["stopped", "completed", "failed"]:
        store.create_run(run_id=status, mode="practice", config={})
        originals.append(store.update_run(status, status=status))
    assert store.recover_interrupted() == 0
    assert [store.get_run(item["run_id"]) for item in originals] == originals
    assert all(store.events(item["run_id"]) == [] for item in originals)


def test_recovery_state_and_event_commit_atomically(tmp_path: Path) -> None:
    path = tmp_path / "runs.sqlite"
    store = AgentRunStore(path)
    original = store.create_run(run_id="run-1", mode="practice", config={})
    with sqlite3.connect(path) as conn:
        conn.execute("""CREATE TRIGGER reject_recovery BEFORE INSERT ON agent_run_events BEGIN
            SELECT RAISE(ABORT, 'evidence write unavailable'); END""")
    try:
        with pytest.raises(sqlite3.DatabaseError, match="evidence write unavailable"):
            store.recover_interrupted()
        assert store.get_run("run-1") == original
        assert store.events("run-1") == []
        with sqlite3.connect(path) as conn:
            conn.execute("DROP TRIGGER reject_recovery")
        assert store.recover_interrupted() == 1
        assert len(store.events("run-1")) == 1
    finally:
        store.close()


@pytest.mark.parametrize("limit", [0, -1, 101, True, 1.5, "20", None])
def test_run_listing_limit_is_strictly_bounded(store: AgentRunStore, limit: object) -> None:
    with pytest.raises(ValueError):
        store.list_runs(limit=limit)


@pytest.mark.parametrize("limit", [0, -1, 1001, True, 1.5, "100", None])
def test_event_limit_is_strictly_bounded(store: AgentRunStore, limit: object) -> None:
    with pytest.raises(ValueError):
        store.events("run-1", limit=limit)


@pytest.mark.parametrize("after", [-1, True, 1.5, "1", None, 2**63])
def test_event_cursor_is_strictly_bounded(store: AgentRunStore, after: object) -> None:
    with pytest.raises(ValueError):
        store.events("run-1", after=after)


def test_bounded_pagination_and_newest_first_listing(store: AgentRunStore) -> None:
    for index in range(3):
        run_id = f"run-{index}"
        store.create_run(run_id=run_id, mode="practice", config={}, now=datetime(2026, 9, 28 + index, tzinfo=UTC))
        for cycle in range(5):
            store.append_event(run_id, kind="cycle", data={"cycle": cycle})
        store.update_run(run_id, status="completed")
    assert [run["run_id"] for run in store.list_runs(limit=2)] == ["run-2", "run-1"]
    page_one = store.events("run-1", limit=2)
    page_two = store.events("run-1", after=page_one[-1]["seq"], limit=2)
    page_three = store.events("run-1", after=page_two[-1]["seq"], limit=2)
    assert [event["data"]["cycle"] for event in page_one + page_two + page_three] == list(range(5))
    assert store.events("run-1", after=page_three[-1]["seq"]) == []


def test_disk_full_raises_and_rolls_back_without_fallback(tmp_path: Path) -> None:
    path = tmp_path / "runs.sqlite"
    store = AgentRunStore(path)
    original = store.create_run(run_id="run-1", mode="practice", config={})
    pages = store._conn.execute("PRAGMA page_count").fetchone()[0]
    store._conn.execute(f"PRAGMA max_page_count = {pages}")
    try:
        with pytest.raises(sqlite3.OperationalError, match="full"):
            store.append_event("run-1", kind="cycle", data={"text": "x" * 60_000})
        assert store.events("run-1") == []
        with pytest.raises(sqlite3.OperationalError, match="full"):
            store.update_run("run-1", status="running", snapshot={"text": "x" * 60_000})
        assert store.get_run("run-1") == original
    finally:
        store.close()
    reopened = AgentRunStore(path)
    try:
        assert reopened.get_run("run-1") == original
        assert reopened.events("run-1") == []
    finally:
        reopened.close()


def test_closed_store_does_not_fall_back_to_memory(store: AgentRunStore) -> None:
    store.close()
    store.close()
    with pytest.raises(sqlite3.ProgrammingError):
        store.create_run(run_id="run-1", mode="practice", config={})
    with pytest.raises(sqlite3.ProgrammingError):
        store.list_runs()


@pytest.mark.parametrize("header", ['{ "alg": "HS256" }', '{\n"alg":"HS256"\n}', '{}'])
def test_jwt_header_whitespace_cannot_bypass_evidence_filter(store: AgentRunStore, header: str) -> None:
    encoded = base64.urlsafe_b64encode(header.encode()).decode().rstrip("=")
    jwt = f"{encoded}.eyJzdWIiOiJleGFtcGxlIn0.c2lnbmF0dXJl"
    with pytest.raises(ValueError, match="credential"):
        store.create_run(run_id="run-1", mode="practice", config={"message": jwt})
    assert store.list_runs() == []


def test_jwt_cannot_be_hidden_in_payload_keys_or_identifiers(store: AgentRunStore) -> None:
    jwt = "eyJhbGciOiJIUzI1NiJ9.eyJzdWIiOiJleGFtcGxlIn0.c2lnbmF0dXJl"
    with pytest.raises(ValueError, match="credential"):
        store.create_run(run_id=jwt, mode="practice", config={})
    with pytest.raises(ValueError, match="credential"):
        store.create_run(run_id="run-1", mode="practice", config={jwt: "value"})


def test_concurrent_recovery_emits_one_fencing_event(tmp_path: Path) -> None:
    path = tmp_path / "runs.sqlite"
    stores = [AgentRunStore(path), AgentRunStore(path)]
    stores[0].create_run(run_id="run-1", mode="practice", config={})
    barrier = threading.Barrier(2)

    def recover(index: int) -> int:
        barrier.wait(timeout=5)
        return stores[index].recover_interrupted()

    try:
        with ThreadPoolExecutor(max_workers=2) as pool:
            counts = list(pool.map(recover, range(2)))
        assert sorted(counts) == [0, 1]
        assert len(stores[0].events("run-1")) == 1
        assert stores[0].get_run("run-1")["status"] == "reconciliation_required"
    finally:
        for item in stores:
            item.close()


def test_sqlite_uses_full_durability_and_foreign_keys(tmp_path: Path) -> None:
    store = AgentRunStore(tmp_path / "runs.sqlite")
    try:
        assert store._conn.execute("PRAGMA synchronous").fetchone()[0] == 2
        assert store._conn.execute("PRAGMA journal_mode").fetchone()[0] == "wal"
        assert store._conn.execute("PRAGMA foreign_keys").fetchone()[0] == 1
    finally:
        store.close()


def test_database_path_is_canonical_and_read_only(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.chdir(tmp_path)
    store = AgentRunStore(Path("nested") / ".." / "runs.sqlite")
    try:
        assert store.database_path == str((tmp_path / "runs.sqlite").resolve())
        actual_path = store._conn.execute("PRAGMA database_list").fetchone()[2]
        assert Path(actual_path).resolve() == Path(store.database_path)
        with pytest.raises(AttributeError):
            store.database_path = str(tmp_path / "different.sqlite")
    finally:
        store.close()


def test_database_path_resolves_existing_alias(tmp_path: Path) -> None:
    actual = tmp_path / "actual"
    actual.mkdir()
    alias = tmp_path / "alias"
    try:
        alias.symlink_to(actual, target_is_directory=True)
    except OSError as exc:
        pytest.skip(f"Directory symlinks are unavailable on this runner: {exc}")
    first = AgentRunStore(actual / "runs.sqlite")
    second = AgentRunStore(alias / "runs.sqlite")
    try:
        assert first.database_path == second.database_path == str((actual / "runs.sqlite").resolve())
    finally:
        first.close()
        second.close()


def test_database_path_preserves_explicit_memory_store(store: AgentRunStore) -> None:
    assert store.database_path == ":memory:"


def test_transition_commits_snapshot_and_event_with_one_timestamp(store: AgentRunStore) -> None:
    store.create_run(run_id="run-1", mode="practice", config={})
    row = store.transition_run("run-1", status="running", snapshot={"cycles": 1})
    event = store.events("run-1")[0]
    assert row["status"] == "running"
    assert row["snapshot"] == {"cycles": 1}
    assert event["kind"] == "status_changed"
    assert event["data"] == {"previous": "starting", "status": "running"}
    assert event["created_at"] == row["updated_at"]
    refreshed = store.transition_run("run-1", status="running", snapshot={"cycles": 2})
    assert refreshed["snapshot"] == {"cycles": 2}
    assert store.events("run-1") == [event]


@pytest.mark.parametrize("target", ["agent_runs", "agent_run_events"])
def test_atomic_transition_rolls_back_both_writes_and_survives_reopen(tmp_path: Path, target: str) -> None:
    path = tmp_path / "runs.sqlite"
    store = AgentRunStore(path)
    original = store.create_run(run_id="run-1", mode="practice", config={})
    operation = "UPDATE" if target == "agent_runs" else "INSERT"
    after_event = ("WHEN EXISTS (SELECT 1 FROM agent_run_events WHERE run_id = 'run-1')"
                   if target == "agent_runs" else "")
    with sqlite3.connect(path) as conn:
        conn.execute(f"""CREATE TRIGGER reject_transition BEFORE {operation} ON {target} {after_event} BEGIN
            SELECT RAISE(ABORT, 'synthetic transition failure'); END""")
    try:
        with pytest.raises(sqlite3.DatabaseError, match="synthetic transition failure"):
            store.transition_run("run-1", status="stopped", snapshot={"cycles": 1})
        assert store.get_run("run-1") == original
        assert store.events("run-1") == []
        with pytest.raises(RuntimeError, match="active"):
            store.create_run(run_id="new-run", mode="practice", config={})
    finally:
        store.close()
    reopened = AgentRunStore(path)
    try:
        assert reopened.get_run("run-1") == original
        assert reopened.events("run-1") == []
    finally:
        reopened.close()


@pytest.mark.parametrize("source,target", [
    ("stopped", "running"), ("completed", "failed"), ("failed", "waiting"),
    ("reconciliation_required", "running"), ("stopping", "running"),
])
def test_invalid_atomic_transition_cannot_append_evidence(store: AgentRunStore, source: str, target: str) -> None:
    store.create_run(run_id="run-1", mode="practice", config={})
    original = store.update_run("run-1", status=source)
    with pytest.raises(ValueError, match="transition"):
        store.transition_run("run-1", status=target, snapshot={"cycles": 99})
    assert store.get_run("run-1") == original
    assert store.events("run-1") == []


@pytest.mark.parametrize("independent_connections", [False, True])
def test_concurrent_worker_and_stop_transitions_have_coherent_evidence(tmp_path: Path,
                                                                     independent_connections: bool) -> None:
    first = AgentRunStore(tmp_path / "runs.sqlite")
    stores = [first, AgentRunStore(tmp_path / "runs.sqlite") if independent_connections else first]
    first.create_run(run_id="run-1", mode="practice", config={})
    barrier = threading.Barrier(2)

    def transition(index: int) -> str:
        barrier.wait(timeout=5)
        try:
            stores[index].transition_run("run-1", status=["running", "stopping"][index])
        except ValueError:
            assert index == 0  # Only a worker overtaken by stop can be refused.
            return "refused"
        return "committed"

    try:
        with ThreadPoolExecutor(max_workers=2) as pool:
            outcomes = list(pool.map(transition, range(2)))
        assert outcomes[1] == "committed"
        events = first.events("run-1")
        previous = "starting"
        for event in events:
            assert event["kind"] == "status_changed"
            assert event["data"]["previous"] == previous
            previous = event["data"]["status"]
        assert previous == first.get_run("run-1")["status"] == "stopping"
        assert len(events) == outcomes.count("committed")
    finally:
        for item in set(stores):
            item.close()
