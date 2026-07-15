"""Crash and concurrency guarantees for durable emergency broker episodes."""

from __future__ import annotations

import hashlib
import sqlite3
import threading

import pytest

from flinttrade_engine.emergency_intents import (
    EmergencyIntentConflict,
    EmergencyIntentJournal,
    InMemoryEmergencyIntentJournal,
)

pytestmark = pytest.mark.unit


def _hash(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def test_l5_episode_survives_restart_and_blocks_every_selector(tmp_path) -> None:
    path = tmp_path / "emergency.sqlite"
    first = EmergencyIntentJournal(path)

    episode, created = first.activate_episode(
        source="l5",
        selector="*",
        session_key="manual",
        reason_hash=_hash("operator kill"),
    )

    assert created is True
    assert episode.source == "l5"
    restarted = EmergencyIntentJournal(path)
    assert restarted.blocking_sources("dhan:primary") == frozenset({"l5"})
    assert restarted.blocking_sources("upstox:secondary") == frozenset({"l5"})

    restored = restarted.active_episode(source="l5", selector="*")
    assert restored is not None
    restarted.deactivate_episode(expected=restored)
    assert EmergencyIntentJournal(path).blocking_sources("dhan:primary") == frozenset()


def test_deactivation_refuses_an_unsettled_broker_intent(tmp_path) -> None:
    journal = EmergencyIntentJournal(tmp_path / "emergency.sqlite")
    episode, _created = journal.activate_episode(
        source="l5",
        selector="*",
        session_key="manual",
        reason_hash=_hash("operator kill"),
    )
    journal.reserve(
        source="l5",
        selector="dhan:primary",
        parent_verb="exit_all_positions",
        verb="place_reducing_order",
        payload_hash=_hash("signed exit"),
        scope="position:abc",
        exit_tag="FTE-1",
    )

    with pytest.raises(EmergencyIntentConflict, match="unsettled"):
        journal.deactivate_episode(expected=episode)

    assert journal.blocking_sources("dhan:primary") == frozenset({"l5"})


@pytest.mark.parametrize("kind", ["memory", "sqlite"])
def test_reservation_cannot_start_after_its_l5_episode_was_reset(tmp_path, kind: str) -> None:
    journal = (
        InMemoryEmergencyIntentJournal()
        if kind == "memory"
        else EmergencyIntentJournal(tmp_path / "reset-before-reserve.sqlite")
    )
    episode, _created = journal.activate_episode(
        source="l5",
        selector="*",
        session_key="manual",
        reason_hash=_hash("reset race"),
    )
    journal.deactivate_episode(expected=episode)

    with pytest.raises(EmergencyIntentConflict, match="active emergency episode"):
        journal.reserve(
            source="l5",
            selector="dhan:primary",
            parent_verb="exit_all_positions",
            verb="place_reducing_order",
            payload_hash=_hash("late broker write"),
            scope="position:late",
            exit_tag="FTE-LATE",
        )

    assert journal.unresolved("dhan:primary", ("exit_all_positions",), source="l5") == ()


def test_settlement_uses_an_exact_intent_set_and_keeps_tombstones(tmp_path) -> None:
    path = tmp_path / "emergency.sqlite"
    journal = EmergencyIntentJournal(path)
    journal.activate_episode(
        source="l5",
        selector="*",
        session_key="manual",
        reason_hash=_hash("settlement test"),
    )
    first, first_created = journal.reserve(
        source="l5",
        selector="dhan:primary",
        parent_verb="cancel_all_orders",
        verb="cancel_order",
        payload_hash=_hash("cancel one"),
        scope="order:ONE",
        target_order_id="ONE",
    )
    second, second_created = journal.reserve(
        source="l5",
        selector="dhan:primary",
        parent_verb="cancel_all_orders",
        verb="cancel_order",
        payload_hash=_hash("cancel two"),
        scope="order:TWO",
        target_order_id="TWO",
    )
    assert first_created is True
    assert second_created is True

    stale_settlement = journal.settle(
        "dhan:primary",
        ("cancel_all_orders",),
        source="l5",
        expected_intent_ids=(first.intent_id,),
    )

    assert stale_settlement is False
    assert {
        record.intent_id
        for record in journal.unresolved("dhan:primary", ("cancel_all_orders",), source="l5")
    } == {
        first.intent_id,
        second.intent_id,
    }
    assert journal.settle(
        "dhan:primary",
        ("cancel_all_orders",),
        source="l5",
        expected_intent_ids=(first.intent_id, second.intent_id),
    )
    assert journal.unresolved("dhan:primary", ("cancel_all_orders",), source="l5") == ()

    with sqlite3.connect(path) as conn:
        states = conn.execute("SELECT state FROM emergency_intents ORDER BY intent_id").fetchall()
    assert states == [("settled",), ("settled",)]

    later, later_created = journal.reserve(
        source="l5",
        selector="dhan:primary",
        parent_verb="cancel_all_orders",
        verb="cancel_order",
        payload_hash=_hash("later cancellation"),
        scope="order:ONE",
        target_order_id="ONE",
    )
    assert later_created is True
    assert later.intent_id > second.intent_id


def test_cross_instance_reservation_has_one_owner(tmp_path) -> None:
    path = tmp_path / "emergency.sqlite"
    EmergencyIntentJournal(path).activate_episode(
        source="mtm",
        selector="dhan:primary",
        session_key="2026-07-13",
        reason_hash=_hash("cross-instance reservation"),
    )
    barrier = threading.Barrier(2)
    results: list[bool] = []
    errors: list[BaseException] = []

    def reserve() -> None:
        try:
            barrier.wait(timeout=1.0)
            _record, created = EmergencyIntentJournal(path).reserve(
                source="mtm",
                selector="dhan:primary",
                parent_verb="exit_all_positions",
                verb="place_reducing_order",
                payload_hash=_hash("same position"),
                scope="position:abc",
                exit_tag="FTE-1",
            )
            results.append(created)
        except BaseException as exc:  # pragma: no cover - asserted below
            errors.append(exc)

    workers = [threading.Thread(target=reserve) for _index in range(2)]
    for worker in workers:
        worker.start()
    for worker in workers:
        worker.join(timeout=2.0)

    assert errors == []
    assert all(not worker.is_alive() for worker in workers)
    assert sorted(results) == [False, True]


def test_legacy_intent_schema_migrates_without_losing_the_unresolved_claim(tmp_path) -> None:
    path = tmp_path / "legacy-emergency.sqlite"
    with sqlite3.connect(path) as conn:
        conn.execute(
            """
            CREATE TABLE emergency_intents (
                intent_id INTEGER PRIMARY KEY AUTOINCREMENT,
                selector TEXT NOT NULL,
                parent_verb TEXT NOT NULL,
                verb TEXT NOT NULL,
                payload_hash TEXT NOT NULL,
                scope TEXT NOT NULL,
                target_order_id TEXT NOT NULL DEFAULT '',
                exit_tag TEXT NOT NULL DEFAULT '',
                broker_order_ids_json TEXT NOT NULL DEFAULT '[]',
                created_at TEXT NOT NULL,
                acknowledged_at TEXT,
                UNIQUE (selector, parent_verb, scope)
            )
            """
        )
        conn.execute(
            """
            INSERT INTO emergency_intents (
                selector, parent_verb, verb, payload_hash, scope,
                target_order_id, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                "dhan:primary",
                "cancel_all_orders",
                "cancel_order",
                _hash("legacy cancellation"),
                "order:LEGACY-1",
                "LEGACY-1",
                "2026-07-13T00:00:00+00:00",
            ),
        )

    journal = EmergencyIntentJournal(path)
    journal.healthcheck()
    records = journal.unresolved(
        "dhan:primary",
        ("cancel_all_orders",),
        source="adhoc",
    )

    assert len(records) == 1
    assert records[0].target_order_id == "LEGACY-1"
    assert records[0].state == "reserved"
    existing, created = journal.reserve(
        source="adhoc",
        selector="dhan:primary",
        parent_verb="cancel_all_orders",
        verb="cancel_order",
        payload_hash=_hash("retry"),
        scope="order:LEGACY-1",
        target_order_id="LEGACY-1",
    )
    assert created is False
    assert existing.intent_id == records[0].intent_id


def test_multi_account_mtm_deactivation_is_atomic_when_one_intent_is_unsettled(tmp_path) -> None:
    journal = EmergencyIntentJournal(tmp_path / "atomic-reset.sqlite")
    episodes = []
    for selector in ("dhan:primary", "dhan:family"):
        episode, _created = journal.activate_episode(
            source="mtm",
            selector=selector,
            session_key="2026-07-13",
            reason_hash=_hash(selector),
        )
        episodes.append(episode)
    journal.reserve(
        source="mtm",
        selector="dhan:family",
        parent_verb="exit_all_positions",
        verb="place_reducing_order",
        payload_hash=_hash("family exit"),
        scope="position:family",
        exit_tag="FTE-FAMILY",
    )

    with pytest.raises(EmergencyIntentConflict, match="unsettled"):
        journal.deactivate_episodes(expected=tuple(reversed(episodes)))

    assert journal.blocking_sources("dhan:primary") == frozenset({"mtm"})
    assert journal.blocking_sources("dhan:family") == frozenset({"mtm"})


@pytest.mark.parametrize("kind", ["memory", "sqlite"])
def test_latched_sources_require_an_active_episode_before_reservation(tmp_path, kind: str) -> None:
    journal = (
        InMemoryEmergencyIntentJournal()
        if kind == "memory"
        else EmergencyIntentJournal(tmp_path / "required-episode.sqlite")
    )

    for source in ("l5", "mtm"):
        with pytest.raises(EmergencyIntentConflict, match="active emergency episode"):
            journal.reserve(
                source=source,
                selector="dhan:primary",
                parent_verb="exit_all_positions",
                verb="place_reducing_order",
                payload_hash=_hash(source),
                scope=f"position:{source}",
                exit_tag=f"FTE-{source.upper()}",
            )


@pytest.mark.parametrize("kind", ["memory", "sqlite"])
def test_stale_episode_snapshot_cannot_deactivate_a_renewed_mtm_latch(tmp_path, kind: str) -> None:
    journal = (
        InMemoryEmergencyIntentJournal()
        if kind == "memory"
        else EmergencyIntentJournal(tmp_path / "renewed-episode.sqlite")
    )
    stale, _created = journal.activate_episode(
        source="mtm",
        selector="dhan:primary",
        session_key="2026-07-12",
        reason_hash=_hash("old session"),
    )
    renewed, created = journal.activate_episode(
        source="mtm",
        selector="dhan:primary",
        session_key="2026-07-13",
        reason_hash=_hash("new session"),
    )

    assert created is False
    assert renewed.episode_id == stale.episode_id
    assert renewed.revision == stale.revision + 1
    with pytest.raises(EmergencyIntentConflict, match="changed during reset"):
        journal.deactivate_episode(expected=stale)
    assert journal.blocking_sources("dhan:primary") == frozenset({"mtm"})

    journal.deactivate_episode(expected=renewed)
    assert journal.blocking_sources("dhan:primary") == frozenset()


@pytest.mark.parametrize("kind", ["memory", "sqlite"])
def test_l5_target_provenance_survives_restart_and_participates_in_reset_cas(tmp_path, kind: str) -> None:
    path = tmp_path / "episode-targets.sqlite"
    journal = InMemoryEmergencyIntentJournal() if kind == "memory" else EmergencyIntentJournal(path)
    stale, _created = journal.activate_episode(
        source="l5",
        selector="*",
        session_key="manual",
        reason_hash=_hash("operator kill"),
    )
    current = journal.record_episode_targets(
        expected=stale,
        selectors=("dhan:primary", "upstox:family"),
    )

    restored_journal = journal if kind == "memory" else EmergencyIntentJournal(path)
    restored = restored_journal.active_episode(source="l5", selector="*")
    assert restored is not None
    assert restored.affected_selectors == ("dhan:primary", "upstox:family")
    assert restored.revision == current.revision

    with pytest.raises(EmergencyIntentConflict, match="changed during reset"):
        restored_journal.deactivate_episode(expected=stale)
    restored_journal.deactivate_episode(expected=restored)


def test_full_schema_with_unconditional_unique_constraint_is_rebuilt(tmp_path) -> None:
    path = tmp_path / "intermediate-emergency.sqlite"
    with sqlite3.connect(path) as conn:
        conn.execute(
            """
            CREATE TABLE emergency_intents (
                intent_id INTEGER PRIMARY KEY AUTOINCREMENT,
                source TEXT NOT NULL,
                selector TEXT NOT NULL,
                parent_verb TEXT NOT NULL,
                verb TEXT NOT NULL,
                payload_hash TEXT NOT NULL,
                scope TEXT NOT NULL,
                target_order_id TEXT NOT NULL DEFAULT '',
                exit_tag TEXT NOT NULL DEFAULT '',
                broker_order_ids_json TEXT NOT NULL DEFAULT '[]',
                state TEXT NOT NULL,
                revision INTEGER NOT NULL DEFAULT 1,
                episode_id INTEGER,
                created_at TEXT NOT NULL,
                acknowledged_at TEXT,
                settled_at TEXT,
                UNIQUE (selector, parent_verb, scope)
            )
            """
        )
        conn.execute(
            """
            INSERT INTO emergency_intents (
                source, selector, parent_verb, verb, payload_hash, scope,
                target_order_id, state, created_at
            ) VALUES ('adhoc', 'dhan:primary', 'cancel_all_orders', 'cancel_order', ?,
                      'order:ONE', 'ONE', 'reserved', '2026-07-13T00:00:00+00:00')
            """,
            (_hash("first"),),
        )

    journal = EmergencyIntentJournal(path)
    journal.healthcheck()
    existing = journal.unresolved("dhan:primary", ("cancel_all_orders",), source="adhoc")
    assert len(existing) == 1
    assert journal.settle(
        "dhan:primary",
        ("cancel_all_orders",),
        source="adhoc",
        expected_intent_ids=(existing[0].intent_id,),
    )

    later, created = journal.reserve(
        source="adhoc",
        selector="dhan:primary",
        parent_verb="cancel_all_orders",
        verb="cancel_order",
        payload_hash=_hash("later"),
        scope="order:ONE",
        target_order_id="ONE",
    )
    assert created is True
    assert later.intent_id > existing[0].intent_id
