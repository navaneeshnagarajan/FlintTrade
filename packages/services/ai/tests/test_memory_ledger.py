"""Canonical memory evidence and immutable decision replay, using synthetic state."""

from __future__ import annotations

import os
import sqlite3
import subprocess
import sys
from datetime import UTC, datetime, timedelta

import pytest

from flinttrade_core.service_providers import (
    EvidenceUseScope,
    LicenceFact,
    PermissionState,
    RightsBasis,
    RightsGrant,
    RightsResolution,
    UsageRights,
    intersect_rights,
)

NOW = datetime(2026, 9, 10, 12, tzinfo=UTC)


def api():
    from flinttrade_ai import memory_ledger

    return memory_ledger


def permitted():
    return intersect_rights(
        RightsGrant(
            grant_id="fixture:grant",
            basis=RightsBasis.LICENCE,
            rights=UsageRights(
                output_use=PermissionState.ALLOWED,
                retention=PermissionState.ALLOWED,
                max_evidence_use_scope=EvidenceUseScope.LIVE_DECISION,
            ),
            evidence=(
                LicenceFact(
                    "fixture:fact",
                    "document",
                    "fixture",
                    "https://example.invalid/licence",
                    "1",
                    "a" * 64,
                    NOW.isoformat(),
                    RightsBasis.LICENCE,
                ),
            ),
        )
    )


def event(event_id="event-1", **kwargs):
    values = dict(
        event_id=event_id,
        domain=api().MemoryDomain.KNOWLEDGE,
        payload={"text": "market reference"},
        as_of=NOW,
        source_refs=("fixture:document",),
        provenance_refs=("fixture:receipt",),
    )
    values.update(kwargs)
    return api().MemoryEvent(**values)


def recall(reader, receipt_id="receipt-1", **kwargs):
    values = dict(
        receipt_id=receipt_id,
        decision_id="decision-1",
        request_id="request-1",
        decision_time=NOW,
        query=api().MemoryQuery(),
    )
    values.update(kwargs)
    return reader.recall(**values)


def test_future_inputs_excluded_and_corrections_keep_originals(tmp_path):
    """Removing the temporal predicate would admit a correction before it existed."""
    with api().MemoryLedger(tmp_path / "memory") as store:
        store.append(event())
        store.append(
            event(
                "correction-1",
                as_of=NOW + timedelta(seconds=1),
                correction_of="event-1",
                payload="corrected market reference",
            )
        )
        early = recall(store.read_projection())
        assert [e.event_id for e in early.events] == ["event-1"]
        late = recall(
            store.read_projection(), "receipt-2", request_id="request-2", decision_time=NOW + timedelta(seconds=1)
        )
        assert [e.event_id for e in late.events] == ["event-1", "correction-1"]
        assert late.events[1].correction_of == "event-1"
        assert store.read_projection().replay("receipt-1") == early


def test_recall_idempotency_and_replay_preserve_inputs_after_backdated_append(tmp_path):
    with api().MemoryLedger(tmp_path / "memory") as store:
        store.append(event())
        reader = store.read_projection()
        original = recall(reader)
        store.append(event("event-2", payload="later appended evidence", as_of=NOW - timedelta(seconds=1)))
        assert recall(reader) == original
        assert reader.replay("receipt-1") == original
        assert original.receipt.event_ids == ("event-1",)
        assert original.receipt.payload_digests == (event().payload_digest,)
        with pytest.raises(api().MemoryConflict):
            recall(reader, query=api().MemoryQuery(text="changed query"))
        with pytest.raises(api().MemoryConflict):
            recall(reader, "another-receipt")
        with pytest.raises(api().MemoryConflict):
            recall(reader, decision_time=NOW + timedelta(seconds=1))


def test_unknown_rights_taint_all_parents_and_corrections(tmp_path):
    with api().MemoryLedger(tmp_path / "memory") as store:
        store.append(event("allowed", rights=permitted()))
        store.append(event("unknown"))
        derived = store.append(event("derived", rights=permitted(), parent_ids=("allowed", "unknown")))
        assert derived.rights.rights.max_evidence_use_scope is EvidenceUseScope.ISOLATED_RESEARCH
        correction = store.append(
            event("corrected", rights=permitted(), correction_of="unknown", as_of=NOW + timedelta(seconds=1))
        )
        assert correction.rights.rights.output_use is PermissionState.UNKNOWN
        context = recall(store.read_projection())
        assert context.receipt.rights.rights.max_evidence_use_scope is EvidenceUseScope.ISOLATED_RESEARCH
        live = recall(
            store.read_projection(),
            "live",
            request_id="live-request",
            query=api().MemoryQuery(minimum_scope=EvidenceUseScope.LIVE_DECISION),
        )
        assert [e.event_id for e in live.events] == ["allowed"]
        assert live.receipt.rights == permitted()
        empty = recall(
            store.read_projection(), "empty", request_id="empty-request", query=api().MemoryQuery(text="not present")
        )
        assert empty.events == ()
        assert empty.receipt.rights == RightsResolution()


def test_provider_payload_cannot_mint_rights_and_dtos_are_detached(tmp_path):
    data = {"rights": {"output_use": "allowed"}, "nested": ["original"]}
    with api().MemoryLedger(tmp_path / "memory") as store:
        draft = event(payload=data)
        data["nested"][0] = "changed"
        stored = store.append(draft)
        assert stored.payload["nested"] == ("original",)
        assert stored.rights == RightsResolution()
        with pytest.raises(TypeError):
            stored.payload["nested"] = ()
        context = recall(store.read_projection())
        public = context.to_dict()
        public["events"][0]["payload"]["nested"][0] = "changed again"
        assert store.read_projection().replay("receipt-1").events[0].payload["nested"] == ("original",)
        with pytest.raises(ValueError):
            event(rights={"output_use": "allowed"})


def test_exact_append_duplicates_and_invalid_lineage(tmp_path):
    with api().MemoryLedger(tmp_path / "memory") as store:
        original = store.append(event())
        assert store.append(event()) == original
        with pytest.raises(api().MemoryConflict):
            store.append(event(payload="changed"))
        with pytest.raises(ValueError):
            store.append(event("bad-parent", parent_ids=("missing",)))
        with pytest.raises(ValueError):
            store.append(event("early-correction", correction_of="event-1", as_of=NOW - timedelta(seconds=1)))
        with pytest.raises(ValueError):
            store.append(
                event(
                    "wrong-domain",
                    correction_of="event-1",
                    domain=api().MemoryDomain.EPISODIC,
                    as_of=NOW + timedelta(seconds=1),
                )
            )


def test_domains_literal_query_and_order_are_deterministic(tmp_path):
    with api().MemoryLedger(tmp_path / "memory") as store:
        for domain in api().MemoryDomain:
            store.append(event(domain.value, domain=domain, payload="DROP TABLE events; %_ is just data"))
        context = recall(store.read_projection(), query=api().MemoryQuery(text="%_", limit=2))
        assert [e.event_id for e in context.events] == ["episodic", "experiment"]
        specific = recall(
            store.read_projection(),
            "specific",
            request_id="specific",
            query=api().MemoryQuery(domain=api().MemoryDomain.PROCEDURAL, event_ids=("procedural",)),
        )
        assert [e.event_id for e in specific.events] == ["procedural"]
        assert not hasattr(store.read_projection(), "append")
        assert not hasattr(store.read_projection(), "ledger")


@pytest.mark.parametrize(
    "payload",
    [float("nan"), float("inf"), {1: "ambiguous"}, {"bad": object()}, "x" * 70000],
    ids=["nan", "infinity", "non-string-key", "non-json-value", "oversized"],
)
def test_invalid_payload_is_rejected_before_write(payload):
    with pytest.raises(ValueError):
        event(payload=payload)


@pytest.mark.parametrize(
    "changes",
    [
        {"event_id": "../invalid"},
        {"as_of": NOW.replace(tzinfo=None)},
        {"domain": "knowledge"},
        {"parent_ids": ("event-1",)},
        {"source_refs": ()},
    ],
)
def test_invalid_identity_time_and_metadata_are_rejected(changes):
    with pytest.raises(ValueError):
        event(**changes)


def test_reopened_authority_validates_receipt_and_never_allows_updates(tmp_path):
    with api().MemoryLedger(tmp_path / "memory") as store:
        store.append(event(rights=permitted()))
        original = recall(store.read_projection())
    with api().MemoryLedger(tmp_path / "memory") as reopened:
        assert reopened.read_projection().replay("receipt-1") == original
    with sqlite3.connect(tmp_path / "memory" / "memory.sqlite") as db:
        with pytest.raises(sqlite3.DatabaseError):
            db.execute("DELETE FROM events")
        with pytest.raises(sqlite3.DatabaseError):
            db.execute("UPDATE receipts SET digest='changed'")


def test_owner_path_deletion_or_replacement_fails_closed(tmp_path):
    with api().MemoryLedger(tmp_path / "memory") as store:
        store.append(event())
        db = tmp_path / "memory" / "memory.sqlite"
        db.rename(tmp_path / "preserved.sqlite")
        with pytest.raises((api().MemoryUnavailable, OSError)):
            recall(store.read_projection())
        with pytest.raises((api().MemoryUnavailable, OSError)):
            api().MemoryLedger(tmp_path / "memory")
        db.write_bytes(b"not an authority")
        db.chmod(0o600)
        with pytest.raises((api().MemoryUnavailable, OSError)):
            store.append(event("new"))


_CHILD = """
import os, sys
from pathlib import Path
from datetime import UTC, datetime
from flinttrade_ai.memory_ledger import MemoryLedger, MemoryEvent, MemoryDomain, MemoryQuery
now = datetime(2026, 9, 10, 12, tzinfo=UTC)
with MemoryLedger(Path(sys.argv[1])) as store:
    if sys.argv[2] == 'fork':
        from flinttrade_ai.memory_ledger import MemoryUnavailable
        import warnings
        # This deliberately tests refusal of an inherited object, not normal
        # application startup through fork. The child only checks and exits.
        with warnings.catch_warnings():
            warnings.filterwarnings('ignore', message='.*multi-threaded.*', category=DeprecationWarning)
            pid = os.fork()
        if pid == 0:
            try:
                store.append(MemoryEvent(event_id='forked', domain=MemoryDomain.KNOWLEDGE,
                    payload='synthetic memory', source_refs=('fixture:source',), as_of=now))
            except MemoryUnavailable:
                try:
                    store.read_projection().recall(receipt_id='forked', decision_id='forked',
                        request_id='forked', decision_time=now, query=MemoryQuery())
                except MemoryUnavailable:
                    os._exit(0)
            os._exit(1)
        _, status = os.waitpid(pid, 0)
        sys.exit(os.waitstatus_to_exitcode(status))
    elif sys.argv[2] == 'append':
        result = store.append(MemoryEvent(event_id='shared', domain=MemoryDomain.KNOWLEDGE,
            payload='synthetic memory', source_refs=('fixture:source',), provenance_refs=(), as_of=now))
        print(result.digest)
    else:
        context = store.read_projection().recall(receipt_id='shared-receipt', decision_id='decision',
            request_id='request', decision_time=now, query=MemoryQuery())
        print(context.receipt.digest)
"""


def test_fresh_process_concurrent_idempotency_and_replay(tmp_path):
    root = tmp_path / "memory"
    with api().MemoryLedger(root):
        pass
    env = dict(os.environ)
    env["PYTHONPATH"] = os.pathsep.join(str(p) for p in sys.path if p)
    for mode in ("append", "recall"):
        children = [
            subprocess.Popen(
                [sys.executable, "-c", _CHILD, str(root), mode],
                env=env,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
            )
            for _ in range(4)
        ]
        digests = []
        for child in children:
            output, error = child.communicate(timeout=30)
            assert child.returncode == 0, error
            digests.append(output.strip())
        assert len(set(digests)) == 1
    with api().MemoryLedger(root) as store:
        assert store.read_projection().replay("shared-receipt").receipt.digest == digests[0]


@pytest.mark.parametrize("mutation", ["version", "schema", "schema-lookalike", "incarnation"])
def test_schema_and_incarnation_changes_fail_closed(tmp_path, mutation):
    with api().MemoryLedger(tmp_path / "memory") as store:
        store.append(event())
        original = recall(store.read_projection())
        if mutation == "incarnation":
            from uuid import uuid4

            marker = tmp_path / "memory" / "authority.json"
            marker.write_text('{"incarnation":"' + str(uuid4()) + '"}')
        else:
            with sqlite3.connect(tmp_path / "memory" / "memory.sqlite") as db:
                db.execute(
                    "PRAGMA user_version = 2"
                    if mutation == "version"
                    else "CREATE TABLE sqlitexhidden (x TEXT)"
                    if mutation == "schema-lookalike"
                    else "CREATE TABLE unexpected (x TEXT)"
                )
        with pytest.raises(api().MemoryUnavailable):
            store.read_projection().replay(original.receipt.receipt_id)
        with pytest.raises(api().MemoryUnavailable):
            api().MemoryLedger(tmp_path / "memory")


def test_closed_projection_refuses_and_failed_receipt_insert_returns_no_context(tmp_path):
    with api().MemoryLedger(tmp_path / "memory") as store:
        store.append(event())
        reader = store.read_projection()
        # A denied write on the actual SQLite connection exercises the atomic
        # read-before-receipt boundary without replacing selection with a mock.
        original_database = store._database

        from contextlib import contextmanager

        @contextmanager
        def read_only_database():
            with original_database() as db:
                db.execute("PRAGMA query_only=ON")
                yield db

        store._database = read_only_database
        with pytest.raises(sqlite3.DatabaseError):
            recall(reader)
        store._database = original_database
        with pytest.raises(KeyError):
            reader.replay("receipt-1")
        assert recall(reader).events[0].event_id == "event-1"
    with pytest.raises(api().MemoryUnavailable):
        reader.replay("receipt-1")


@pytest.mark.skipif(not hasattr(os, "fork"), reason="native POSIX fork ownership test")
def test_forked_writer_and_reader_cannot_use_parent_authority(tmp_path):
    env = dict(os.environ)
    env["PYTHONPATH"] = os.pathsep.join(str(p) for p in sys.path if p)
    completed = subprocess.run(
        [sys.executable, "-c", _CHILD, str(tmp_path / "memory"), "fork"],
        env=env,
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert completed.returncode == 0, completed.stderr
    assert not completed.stderr
    with api().MemoryLedger(tmp_path / "memory") as store:
        assert recall(store.read_projection()).events == ()


def test_exact_decision_cutoff_and_context_limits(tmp_path):
    with api().MemoryLedger(tmp_path / "memory") as store:
        store.append(event("at-cutoff"))
        store.append(event("after-cutoff", as_of=NOW + timedelta(microseconds=1)))
        assert [e.event_id for e in recall(store.read_projection()).events] == ["at-cutoff"]
        for i in range(20):
            store.append(event(f"large-{i}", payload="z" * 60000))
        with pytest.raises(ValueError):
            recall(store.read_projection(), "too-large", request_id="too-large", query=api().MemoryQuery(limit=100))
        with pytest.raises(KeyError):
            store.read_projection().replay("too-large")


@pytest.mark.parametrize(
    "query",
    [
        {"limit": True},
        {"limit": 101},
        {"event_ids": ("x", "x")},
        {"minimum_scope": "live_decision"},
        {"text": "x" * 1025},
    ],
)
def test_invalid_queries_refuse_before_receipt(query):
    with pytest.raises(ValueError):
        api().MemoryQuery(**query)
