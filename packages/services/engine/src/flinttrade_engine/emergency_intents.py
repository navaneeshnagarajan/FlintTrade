"""Crash-safe write-ahead journal for emergency broker mutations."""

from __future__ import annotations

import json
import logging
import os
import sqlite3
import threading
from dataclasses import dataclass, replace
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Protocol

from flinttrade_core.db import open_sqlite
from flinttrade_core.exceptions import SafetyBypassError
from flinttrade_core.secure_file import harden

logger = logging.getLogger("flinttrade.engine.emergency_intents")


_ACTIVE_INTENT_STATES = frozenset({"reserved", "acknowledged", "outcome_unknown"})
_EPISODE_SOURCES = frozenset({"l5", "mtm", "adhoc"})
_INTENT_COLUMNS = frozenset(
    {
        "intent_id",
        "source",
        "selector",
        "parent_verb",
        "verb",
        "payload_hash",
        "scope",
        "target_order_id",
        "exit_tag",
        "broker_order_ids_json",
        "state",
        "revision",
        "episode_id",
        "created_at",
        "acknowledged_at",
        "settled_at",
    }
)
_INTENT_SCOPE_INDEX_COLUMNS = ("selector", "parent_verb", "scope")
_LEGACY_INTENT_COLUMNS = frozenset(
    {
        "intent_id",
        "selector",
        "parent_verb",
        "verb",
        "payload_hash",
        "scope",
        "target_order_id",
        "exit_tag",
        "broker_order_ids_json",
        "created_at",
        "acknowledged_at",
    }
)


class EmergencyIntentConflict(SafetyBypassError):
    """Raised when durable emergency state makes a reset or settlement unsafe."""


@dataclass(frozen=True)
class EmergencyEpisodeRecord:
    """One durable safety latch spanning broker mutations and process restarts."""

    episode_id: int
    source: str
    selector: str
    session_key: str
    state: str
    revision: int
    affected_selectors: tuple[str, ...] = ()


@dataclass(frozen=True)
class EmergencyIntentRecord:
    """One unresolved broker mutation reserved before adapter dispatch."""

    intent_id: int
    source: str
    selector: str
    parent_verb: str
    verb: str
    payload_hash: str
    scope: str
    target_order_id: str = ""
    exit_tag: str = ""
    broker_order_ids: tuple[str, ...] = ()
    state: str = "reserved"
    revision: int = 1
    episode_id: int | None = None


class EmergencyIntentJournalProtocol(Protocol):
    """Storage contract used by the gated emergency dispatcher."""

    def activate_episode(
        self,
        *,
        source: str,
        selector: str,
        session_key: str,
        reason_hash: str,
    ) -> tuple[EmergencyEpisodeRecord, bool]: ...

    def active_episodes(self, source: str | None = None) -> tuple[EmergencyEpisodeRecord, ...]: ...

    def active_episode(self, *, source: str, selector: str) -> EmergencyEpisodeRecord | None: ...

    def record_episode_targets(
        self,
        *,
        expected: EmergencyEpisodeRecord,
        selectors: tuple[str, ...],
    ) -> EmergencyEpisodeRecord: ...

    def blocking_sources(self, selector: str) -> frozenset[str]: ...

    def deactivate_episode(self, *, expected: EmergencyEpisodeRecord) -> None: ...

    def deactivate_episodes(self, *, expected: tuple[EmergencyEpisodeRecord, ...]) -> None: ...

    def unresolved(
        self,
        selector: str,
        parent_verbs: tuple[str, ...],
        *,
        source: str | None = None,
    ) -> tuple[EmergencyIntentRecord, ...]: ...

    def reserve(
        self,
        *,
        source: str,
        selector: str,
        parent_verb: str,
        verb: str,
        payload_hash: str,
        scope: str,
        target_order_id: str = "",
        exit_tag: str = "",
    ) -> tuple[EmergencyIntentRecord, bool]: ...

    def acknowledge(self, intent_id: int, broker_order_ids: tuple[str, ...]) -> None: ...

    def mark_unknown(self, intent_id: int) -> None: ...

    def release(self, intent_id: int) -> None: ...

    def settle(
        self,
        selector: str,
        parent_verbs: tuple[str, ...],
        *,
        source: str,
        expected_intent_ids: tuple[int, ...],
    ) -> bool: ...


def _normalise_order_ids(order_ids: tuple[str, ...]) -> tuple[str, ...]:
    canonical = tuple(str(order_id) for order_id in order_ids)
    if any(
        not order_id
        or order_id != order_id.strip()
        or not order_id.isprintable()
        or any(character.isspace() for character in order_id)
        for order_id in canonical
    ):
        raise ValueError("emergency intent order ids must be canonical")
    if len(set(canonical)) != len(canonical):
        raise ValueError("emergency intent order ids must be unique")
    return canonical


def _validate_record_fields(
    *,
    source: str,
    selector: str,
    parent_verb: str,
    verb: str,
    payload_hash: str,
    scope: str,
) -> None:
    if source not in _EPISODE_SOURCES:
        raise ValueError("emergency intent source is invalid")
    if ":" not in selector or selector != selector.strip():
        raise ValueError("emergency intent selector must be canonical")
    if not parent_verb or parent_verb != parent_verb.strip():
        raise ValueError("emergency intent parent verb must be canonical")
    if not verb or verb != verb.strip():
        raise ValueError("emergency intent verb must be canonical")
    if len(payload_hash) != 64 or any(character not in "0123456789abcdef" for character in payload_hash):
        raise ValueError("emergency intent payload hash must be sha256 hex")
    if not scope or scope != scope.strip():
        raise ValueError("emergency intent scope must be canonical")


def _validate_optional_token(value: str, *, field: str) -> None:
    if value and (
        value != value.strip()
        or not value.isprintable()
        or any(character.isspace() for character in value)
    ):
        raise ValueError(f"emergency intent {field} must be canonical")


def _validate_episode_fields(*, source: str, selector: str, session_key: str, reason_hash: str) -> None:
    if source not in {"l5", "mtm"}:
        raise ValueError("emergency episode source must be l5 or mtm")
    if selector != "*" and (":" not in selector or selector != selector.strip()):
        raise ValueError("emergency episode selector must be canonical")
    if source == "mtm" and selector == "*":
        raise ValueError("MTM emergency episodes require an account selector")
    if not session_key or session_key != session_key.strip():
        raise ValueError("emergency episode session key must be canonical")
    if source == "mtm":
        try:
            date.fromisoformat(session_key)
        except ValueError as exc:
            raise ValueError("MTM emergency episode session key must be an ISO date") from exc
    if len(reason_hash) != 64 or any(character not in "0123456789abcdef" for character in reason_hash):
        raise ValueError("emergency episode reason hash must be sha256 hex")


def _validate_episode_snapshot(expected: EmergencyEpisodeRecord) -> None:
    if not isinstance(expected, EmergencyEpisodeRecord):
        raise TypeError("expected emergency episode must be an EmergencyEpisodeRecord")
    if expected.source not in {"l5", "mtm"} or expected.state != "active":
        raise ValueError("expected emergency episode must be active")
    if expected.episode_id < 1 or expected.revision < 1:
        raise ValueError("expected emergency episode identity is invalid")
    if expected.selector != "*" and (
        ":" not in expected.selector or expected.selector != expected.selector.strip()
    ):
        raise ValueError("expected emergency episode selector must be canonical")


def _normalise_affected_selectors(selectors: tuple[str, ...]) -> tuple[str, ...]:
    if not isinstance(selectors, tuple):
        raise TypeError("emergency episode targets must be a tuple")
    canonical = tuple(sorted(selectors))
    if len(set(canonical)) != len(canonical) or any(
        not selector or ":" not in selector or selector != selector.strip()
        for selector in canonical
    ):
        raise ValueError("emergency episode target selector must be canonical and unique")
    return canonical


class InMemoryEmergencyIntentJournal:
    """Process-local journal used by isolated dispatchers and unit tests."""

    def __init__(self) -> None:
        self._records: dict[tuple[str, str, str], EmergencyIntentRecord] = {}
        self._episodes: dict[tuple[str, str], EmergencyEpisodeRecord] = {}
        self._next_id = 1
        self._next_episode_id = 1
        self._lock = threading.RLock()

    def activate_episode(
        self,
        *,
        source: str,
        selector: str,
        session_key: str,
        reason_hash: str,
    ) -> tuple[EmergencyEpisodeRecord, bool]:
        _validate_episode_fields(
            source=source,
            selector=selector,
            session_key=session_key,
            reason_hash=reason_hash,
        )
        key = (source, selector)
        with self._lock:
            existing = self._episodes.get(key)
            if existing is not None:
                if source == "mtm" and date.fromisoformat(session_key) > date.fromisoformat(existing.session_key):
                    existing = replace(
                        existing,
                        session_key=session_key,
                        revision=existing.revision + 1,
                    )
                    self._episodes[key] = existing
                return existing, False
            episode = EmergencyEpisodeRecord(
                episode_id=self._next_episode_id,
                source=source,
                selector=selector,
                session_key=session_key,
                state="active",
                revision=1,
            )
            self._next_episode_id += 1
            self._episodes[key] = episode
            return episode, True

    def active_episodes(self, source: str | None = None) -> tuple[EmergencyEpisodeRecord, ...]:
        if source is not None and source not in {"l5", "mtm"}:
            raise ValueError("emergency episode source must be l5 or mtm")
        with self._lock:
            return tuple(
                sorted(
                    (
                        episode
                        for episode in self._episodes.values()
                        if source is None or episode.source == source
                    ),
                    key=lambda episode: episode.episode_id,
                )
            )

    def active_episode(self, *, source: str, selector: str) -> EmergencyEpisodeRecord | None:
        if source not in {"l5", "mtm"}:
            raise ValueError("emergency episode source must be l5 or mtm")
        with self._lock:
            return self._episodes.get((source, selector))

    def record_episode_targets(
        self,
        *,
        expected: EmergencyEpisodeRecord,
        selectors: tuple[str, ...],
    ) -> EmergencyEpisodeRecord:
        _validate_episode_snapshot(expected)
        canonical = _normalise_affected_selectors(selectors)
        with self._lock:
            key = (expected.source, expected.selector)
            current = self._episodes.get(key)
            if current != expected:
                raise EmergencyIntentConflict("emergency episode changed while targets were recorded")
            affected = tuple(sorted(set(current.affected_selectors).union(canonical)))
            if affected == current.affected_selectors:
                return current
            updated = replace(
                current,
                affected_selectors=affected,
                revision=current.revision + 1,
            )
            self._episodes[key] = updated
            return updated

    def blocking_sources(self, selector: str) -> frozenset[str]:
        if ":" not in selector or selector != selector.strip():
            raise ValueError("emergency selector must be canonical")
        with self._lock:
            return frozenset(
                episode.source
                for episode in self._episodes.values()
                if episode.selector in {"*", selector}
            )

    def deactivate_episode(self, *, expected: EmergencyEpisodeRecord) -> None:
        self.deactivate_episodes(expected=(expected,))

    def deactivate_episodes(self, *, expected: tuple[EmergencyEpisodeRecord, ...]) -> None:
        if not expected:
            return
        for episode in expected:
            _validate_episode_snapshot(episode)
        if len({episode.episode_id for episode in expected}) != len(expected):
            raise ValueError("expected emergency episodes must be unique")
        sources = {episode.source for episode in expected}
        if len(sources) != 1:
            raise ValueError("expected emergency episodes must share a source")
        source = expected[0].source
        selectors = tuple(episode.selector for episode in expected)
        with self._lock:
            for episode in expected:
                if self._episodes.get((episode.source, episode.selector)) != episode:
                    raise EmergencyIntentConflict("emergency episode changed during reset")
            unsettled = tuple(
                record
                for record in self._records.values()
                if record.source == source and (source == "l5" or record.selector in selectors)
            )
            if unsettled:
                raise EmergencyIntentConflict("emergency episode has unsettled broker intents")
            for episode in expected:
                self._episodes.pop((episode.source, episode.selector), None)

    def unresolved(
        self,
        selector: str,
        parent_verbs: tuple[str, ...],
        *,
        source: str | None = None,
    ) -> tuple[EmergencyIntentRecord, ...]:
        if source is not None and source not in _EPISODE_SOURCES:
            raise ValueError("emergency intent source is invalid")
        requested = set(parent_verbs)
        with self._lock:
            return tuple(
                record
                for record in self._records.values()
                if record.selector == selector
                and record.parent_verb in requested
                and (source is None or record.source == source)
            )

    def reserve(
        self,
        *,
        source: str,
        selector: str,
        parent_verb: str,
        verb: str,
        payload_hash: str,
        scope: str,
        target_order_id: str = "",
        exit_tag: str = "",
    ) -> tuple[EmergencyIntentRecord, bool]:
        _validate_record_fields(
            source=source,
            selector=selector,
            parent_verb=parent_verb,
            verb=verb,
            payload_hash=payload_hash,
            scope=scope,
        )
        _validate_optional_token(target_order_id, field="target order id")
        _validate_optional_token(exit_tag, field="exit tag")
        key = (selector, parent_verb, scope)
        with self._lock:
            existing = self._records.get(key)
            if existing is not None:
                return existing, False
            episode_id = self._episode_id_for(source, selector)
            if source != "adhoc" and episode_id is None:
                raise EmergencyIntentConflict("active emergency episode is required before reservation")
            record = EmergencyIntentRecord(
                intent_id=self._next_id,
                source=source,
                selector=selector,
                parent_verb=parent_verb,
                verb=verb,
                payload_hash=payload_hash,
                scope=scope,
                target_order_id=target_order_id,
                exit_tag=exit_tag,
                episode_id=episode_id,
            )
            self._next_id += 1
            self._records[key] = record
            return record, True

    def _episode_id_for(self, source: str, selector: str) -> int | None:
        episode = self._episodes.get((source, selector)) or self._episodes.get((source, "*"))
        return None if episode is None else episode.episode_id

    def acknowledge(self, intent_id: int, broker_order_ids: tuple[str, ...]) -> None:
        canonical_ids = _normalise_order_ids(broker_order_ids)
        with self._lock:
            for key, record in self._records.items():
                if record.intent_id == intent_id:
                    self._records[key] = replace(
                        record,
                        broker_order_ids=canonical_ids,
                        state="acknowledged",
                        revision=record.revision + 1,
                    )
                    return
        raise KeyError(f"unknown emergency intent {intent_id}")

    def mark_unknown(self, intent_id: int) -> None:
        with self._lock:
            for key, record in self._records.items():
                if record.intent_id == intent_id:
                    self._records[key] = replace(
                        record,
                        state="outcome_unknown",
                        revision=record.revision + 1,
                    )
                    return
        raise KeyError(f"unknown emergency intent {intent_id}")

    def release(self, intent_id: int) -> None:
        with self._lock:
            for key, record in tuple(self._records.items()):
                if record.intent_id == intent_id:
                    del self._records[key]
                    return

    def settle(
        self,
        selector: str,
        parent_verbs: tuple[str, ...],
        *,
        source: str,
        expected_intent_ids: tuple[int, ...],
    ) -> bool:
        if source not in _EPISODE_SOURCES:
            raise ValueError("emergency intent source is invalid")
        requested = set(parent_verbs)
        with self._lock:
            matching = {
                record.intent_id
                for record in self._records.values()
                if record.selector == selector
                and record.parent_verb in requested
                and record.source == source
            }
            if matching != set(expected_intent_ids):
                return False
            for key, record in tuple(self._records.items()):
                if record.intent_id in matching:
                    del self._records[key]
            return True


class EmergencyDispatchIntentJournal:
    """Keep emergency reductions available if durable intent storage fails.

    The durable journal remains authoritative while it is healthy. Mutations
    are mirrored into a process-local journal so an I/O failure can degrade an
    already-latched cancel/flatten operation instead of vetoing it. Validation
    and concurrency conflicts are never degraded. Safety-latch reset code uses
    the durable journal directly, so this fallback cannot clear durable latches
    or unresolved intents after a storage outage.
    """

    _NON_STORAGE_FAILURES = (EmergencyIntentConflict, KeyError, TypeError, ValueError)
    _FALLBACK_REASON_HASH = "0" * 64

    def __init__(self, primary: EmergencyIntentJournalProtocol) -> None:
        self._primary = primary
        self._fallback = InMemoryEmergencyIntentJournal()
        self._lock = threading.RLock()
        self._degraded = False
        self._intent_ids: dict[int, int] = {}
        self._episode_ids: dict[int, int] = {}

    @property
    def degraded(self) -> bool:
        with self._lock:
            return self._degraded

    @property
    def primary(self) -> EmergencyIntentJournalProtocol:
        """Return the durable journal retained for latch/reset authority."""
        return self._primary

    def _degrade(self, exc: Exception) -> None:
        if isinstance(exc, self._NON_STORAGE_FAILURES):
            raise exc
        with self._lock:
            if self._degraded:
                return
            self._degraded = True
        logger.critical(
            "Emergency intent durability degraded to process-local fallback (%s); "
            "durable latch reset remains fail-closed",
            type(exc).__name__,
        )

    def _mirror_episode(self, episode: EmergencyEpisodeRecord) -> EmergencyEpisodeRecord:
        fallback, _created = self._fallback.activate_episode(
            source=episode.source,
            selector=episode.selector,
            session_key=episode.session_key,
            reason_hash=self._FALLBACK_REASON_HASH,
        )
        if episode.affected_selectors:
            fallback = self._fallback.record_episode_targets(
                expected=fallback,
                selectors=episode.affected_selectors,
            )
        self._episode_ids[episode.episode_id] = fallback.episode_id
        return fallback

    def _fallback_episode(self, expected: EmergencyEpisodeRecord) -> EmergencyEpisodeRecord:
        fallback = self._fallback.active_episode(
            source=expected.source,
            selector=expected.selector,
        )
        return fallback if fallback is not None else self._mirror_episode(expected)

    def _mirror_intent(self, record: EmergencyIntentRecord) -> EmergencyIntentRecord:
        if record.source != "adhoc":
            episode_selector = "*" if record.source == "l5" else record.selector
            episode = self._fallback.active_episode(
                source=record.source,
                selector=episode_selector,
            )
            if episode is None:
                session_key = "manual" if record.source == "l5" else date.today().isoformat()
                self._fallback.activate_episode(
                    source=record.source,
                    selector=episode_selector,
                    session_key=session_key,
                    reason_hash=self._FALLBACK_REASON_HASH,
                )
        fallback, _created = self._fallback.reserve(
            source=record.source,
            selector=record.selector,
            parent_verb=record.parent_verb,
            verb=record.verb,
            payload_hash=record.payload_hash,
            scope=record.scope,
            target_order_id=record.target_order_id,
            exit_tag=record.exit_tag,
        )
        self._intent_ids[record.intent_id] = fallback.intent_id
        if record.state == "acknowledged":
            self._fallback.acknowledge(fallback.intent_id, record.broker_order_ids)
        elif record.state == "outcome_unknown":
            self._fallback.mark_unknown(fallback.intent_id)
        return fallback

    def _fallback_intent_id(self, intent_id: int) -> int:
        return self._intent_ids.get(intent_id, intent_id)

    def activate_episode(
        self,
        *,
        source: str,
        selector: str,
        session_key: str,
        reason_hash: str,
    ) -> tuple[EmergencyEpisodeRecord, bool]:
        fallback = self._fallback.activate_episode(
            source=source,
            selector=selector,
            session_key=session_key,
            reason_hash=reason_hash,
        )
        if self.degraded:
            return fallback
        try:
            primary = self._primary.activate_episode(
                source=source,
                selector=selector,
                session_key=session_key,
                reason_hash=reason_hash,
            )
        except Exception as exc:
            self._degrade(exc)
            return fallback
        self._episode_ids[primary[0].episode_id] = fallback[0].episode_id
        return primary

    def active_episodes(self, source: str | None = None) -> tuple[EmergencyEpisodeRecord, ...]:
        if self.degraded:
            return self._fallback.active_episodes(source)
        try:
            episodes = self._primary.active_episodes(source)
        except Exception as exc:
            self._degrade(exc)
            return self._fallback.active_episodes(source)
        for episode in episodes:
            self._mirror_episode(episode)
        return episodes

    def active_episode(self, *, source: str, selector: str) -> EmergencyEpisodeRecord | None:
        if self.degraded:
            return self._fallback.active_episode(source=source, selector=selector)
        try:
            episode = self._primary.active_episode(source=source, selector=selector)
        except Exception as exc:
            self._degrade(exc)
            return self._fallback.active_episode(source=source, selector=selector)
        if episode is not None:
            self._mirror_episode(episode)
        return episode

    def record_episode_targets(
        self,
        *,
        expected: EmergencyEpisodeRecord,
        selectors: tuple[str, ...],
    ) -> EmergencyEpisodeRecord:
        fallback_expected = self._fallback_episode(expected)
        fallback = self._fallback.record_episode_targets(
            expected=fallback_expected,
            selectors=selectors,
        )
        if self.degraded:
            return fallback
        try:
            primary = self._primary.record_episode_targets(
                expected=expected,
                selectors=selectors,
            )
        except Exception as exc:
            self._degrade(exc)
            return fallback
        self._episode_ids[primary.episode_id] = fallback.episode_id
        return primary

    def blocking_sources(self, selector: str) -> frozenset[str]:
        if self.degraded:
            return self._fallback.blocking_sources(selector)
        try:
            return self._primary.blocking_sources(selector)
        except Exception as exc:
            self._degrade(exc)
            return self._fallback.blocking_sources(selector)

    def deactivate_episode(self, *, expected: EmergencyEpisodeRecord) -> None:
        self.deactivate_episodes(expected=(expected,))

    def deactivate_episodes(self, *, expected: tuple[EmergencyEpisodeRecord, ...]) -> None:
        self._primary.deactivate_episodes(expected=expected)
        translated = tuple(self._fallback_episode(episode) for episode in expected)
        self._fallback.deactivate_episodes(expected=translated)

    def unresolved(
        self,
        selector: str,
        parent_verbs: tuple[str, ...],
        *,
        source: str | None = None,
    ) -> tuple[EmergencyIntentRecord, ...]:
        if self.degraded:
            return self._fallback.unresolved(selector, parent_verbs, source=source)
        try:
            records = self._primary.unresolved(selector, parent_verbs, source=source)
        except Exception as exc:
            self._degrade(exc)
            return self._fallback.unresolved(selector, parent_verbs, source=source)
        for record in records:
            self._mirror_intent(record)
        return records

    def reserve(self, **kwargs: str) -> tuple[EmergencyIntentRecord, bool]:
        fallback = self._fallback.reserve(**kwargs)
        if self.degraded:
            return fallback
        try:
            primary = self._primary.reserve(**kwargs)
        except Exception as exc:
            self._degrade(exc)
            return fallback
        self._intent_ids[primary[0].intent_id] = fallback[0].intent_id
        return primary

    def acknowledge(self, intent_id: int, broker_order_ids: tuple[str, ...]) -> None:
        fallback_id = self._fallback_intent_id(intent_id)
        self._fallback.acknowledge(fallback_id, broker_order_ids)
        if self.degraded:
            return
        try:
            self._primary.acknowledge(intent_id, broker_order_ids)
        except Exception as exc:
            self._degrade(exc)

    def mark_unknown(self, intent_id: int) -> None:
        fallback_id = self._fallback_intent_id(intent_id)
        self._fallback.mark_unknown(fallback_id)
        if self.degraded:
            return
        try:
            self._primary.mark_unknown(intent_id)
        except Exception as exc:
            self._degrade(exc)

    def release(self, intent_id: int) -> None:
        fallback_id = self._fallback_intent_id(intent_id)
        if not self.degraded:
            try:
                self._primary.release(intent_id)
            except Exception as exc:
                self._degrade(exc)
        self._fallback.release(fallback_id)

    def settle(
        self,
        selector: str,
        parent_verbs: tuple[str, ...],
        *,
        source: str,
        expected_intent_ids: tuple[int, ...],
    ) -> bool:
        translated_ids = tuple(self._fallback_intent_id(intent_id) for intent_id in expected_intent_ids)
        if self.degraded:
            return self._fallback.settle(
                selector,
                parent_verbs,
                source=source,
                expected_intent_ids=translated_ids,
            )
        try:
            settled = self._primary.settle(
                selector,
                parent_verbs,
                source=source,
                expected_intent_ids=expected_intent_ids,
            )
        except Exception as exc:
            self._degrade(exc)
            return self._fallback.settle(
                selector,
                parent_verbs,
                source=source,
                expected_intent_ids=translated_ids,
            )
        if not settled:
            return False
        return self._fallback.settle(
            selector,
            parent_verbs,
            source=source,
            expected_intent_ids=translated_ids,
        )


class EmergencyIntentJournal:
    """FULL-sync SQLite journal for durable safety latches and broker intents."""

    def __init__(self, db_path: str | Path) -> None:
        self._db_path = Path(db_path).expanduser()
        self._lock = threading.RLock()
        self._schema_ready = False

    def _harden_path(self) -> None:
        self._db_path.parent.mkdir(parents=True, exist_ok=True)
        flags = os.O_RDWR | os.O_CREAT | getattr(os, "O_NOFOLLOW", 0)
        descriptor = os.open(self._db_path, flags, 0o600)
        os.close(descriptor)
        harden(self._db_path)

    @staticmethod
    def _create_intent_table(conn: sqlite3.Connection) -> None:
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
                settled_at TEXT
            )
            """
        )

    @staticmethod
    def _create_episode_target_table(conn: sqlite3.Connection) -> None:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS emergency_episode_targets (
                episode_id INTEGER NOT NULL,
                selector TEXT NOT NULL,
                PRIMARY KEY (episode_id, selector),
                FOREIGN KEY (episode_id) REFERENCES emergency_episodes(episode_id)
            )
            """
        )

    @staticmethod
    def _index_columns(conn: sqlite3.Connection, index_name: str) -> tuple[str, ...]:
        return tuple(str(row[2]) for row in conn.execute(f"PRAGMA index_info({index_name!r})"))

    @classmethod
    def _has_unconditional_scope_unique(cls, conn: sqlite3.Connection) -> bool:
        for row in conn.execute("PRAGMA index_list(emergency_intents)"):
            if not bool(row[2]):
                continue
            if cls._index_columns(conn, str(row[1])) != _INTENT_SCOPE_INDEX_COLUMNS:
                continue
            if not bool(row[4]):
                return True
        return False

    @classmethod
    def _rebuild_intent_table(cls, conn: sqlite3.Connection, columns: frozenset[str]) -> None:
        legacy = conn.execute(
            "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = 'emergency_intents_legacy'"
        ).fetchone()
        if legacy is not None:
            raise sqlite3.DatabaseError("incomplete emergency-intent schema migration")
        if not (_INTENT_COLUMNS.issubset(columns) or columns == _LEGACY_INTENT_COLUMNS):
            raise sqlite3.DatabaseError("unsupported emergency-intent schema; refusing lossy migration")

        conn.execute("DROP INDEX IF EXISTS uq_active_emergency_intent")
        conn.execute("ALTER TABLE emergency_intents RENAME TO emergency_intents_legacy")
        cls._create_intent_table(conn)
        if _INTENT_COLUMNS.issubset(columns):
            ordered = (
                "intent_id, source, selector, parent_verb, verb, payload_hash, scope, "
                "target_order_id, exit_tag, broker_order_ids_json, state, revision, "
                "episode_id, created_at, acknowledged_at, settled_at"
            )
            conn.execute(
                f"INSERT INTO emergency_intents ({ordered}) SELECT {ordered} FROM emergency_intents_legacy"
            )
        else:
            conn.execute(
                """
                INSERT INTO emergency_intents (
                    intent_id, source, selector, parent_verb, verb, payload_hash, scope,
                    target_order_id, exit_tag, broker_order_ids_json, state, revision,
                    episode_id, created_at, acknowledged_at, settled_at
                )
                SELECT
                    intent_id, 'adhoc', selector, parent_verb, verb, payload_hash, scope,
                    target_order_id, exit_tag, broker_order_ids_json,
                    CASE WHEN acknowledged_at IS NULL THEN 'reserved' ELSE 'acknowledged' END,
                    1, NULL, created_at, acknowledged_at, NULL
                FROM emergency_intents_legacy
                """
            )
        conn.execute("DROP TABLE emergency_intents_legacy")

    def _ensure_schema(self, conn: sqlite3.Connection) -> None:
        conn.execute("BEGIN IMMEDIATE")
        try:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS emergency_episodes (
                    episode_id INTEGER PRIMARY KEY AUTOINCREMENT,
                    source TEXT NOT NULL,
                    selector TEXT NOT NULL,
                    session_key TEXT NOT NULL,
                    reason_hash TEXT NOT NULL,
                    state TEXT NOT NULL,
                    revision INTEGER NOT NULL DEFAULT 1,
                    created_at TEXT NOT NULL,
                    settled_at TEXT
                )
                """
            )
            self._create_episode_target_table(conn)
            intent_table = conn.execute(
                "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = 'emergency_intents'"
            ).fetchone()
            if intent_table is None:
                self._create_intent_table(conn)
            else:
                columns = frozenset(
                    str(row[1]) for row in conn.execute("PRAGMA table_info(emergency_intents)")
                )
                if not _INTENT_COLUMNS.issubset(columns) or self._has_unconditional_scope_unique(conn):
                    self._rebuild_intent_table(conn, columns)
            conn.execute(
                """
                CREATE UNIQUE INDEX IF NOT EXISTS uq_active_emergency_episode
                ON emergency_episodes (source, selector)
                WHERE state = 'active'
                """
            )
            conn.execute("DROP INDEX IF EXISTS uq_active_emergency_intent")
            conn.execute(
                """
                CREATE UNIQUE INDEX IF NOT EXISTS uq_active_emergency_intent
                ON emergency_intents (selector, parent_verb, scope)
                WHERE state IN ('reserved', 'acknowledged', 'outcome_unknown')
                """
            )
            conn.execute("PRAGMA user_version = 2")
            conn.execute("COMMIT")
        except Exception:
            if conn.in_transaction:
                conn.execute("ROLLBACK")
            raise

    def _connect(self) -> sqlite3.Connection:
        self._harden_path()
        conn = open_sqlite(self._db_path, durability="full", temp_store="FILE", cache_size_kb=1024)
        conn.row_factory = sqlite3.Row
        try:
            if not self._schema_ready:
                self._ensure_schema(conn)
                self._schema_ready = True
            return conn
        except Exception:
            conn.close()
            raise

    def healthcheck(self) -> None:
        """Initialise the schema and reject a corrupt or unreadable journal."""
        with self._lock:
            conn = self._connect()
            try:
                row = conn.execute("PRAGMA quick_check").fetchone()
                if row is None or str(row[0]).lower() != "ok":
                    raise sqlite3.DatabaseError("emergency intent journal quick-check failed")
            finally:
                conn.close()

    @staticmethod
    def _record(row: sqlite3.Row) -> EmergencyIntentRecord:
        raw_order_ids = json.loads(str(row["broker_order_ids_json"]))
        if not isinstance(raw_order_ids, list):
            raise ValueError("emergency intent order-id payload is invalid")
        state = str(row["state"])
        if state not in _ACTIVE_INTENT_STATES and state != "settled":
            raise ValueError("emergency intent state is invalid")
        return EmergencyIntentRecord(
            intent_id=int(row["intent_id"]),
            source=str(row["source"]),
            selector=str(row["selector"]),
            parent_verb=str(row["parent_verb"]),
            verb=str(row["verb"]),
            payload_hash=str(row["payload_hash"]),
            scope=str(row["scope"]),
            target_order_id=str(row["target_order_id"]),
            exit_tag=str(row["exit_tag"]),
            broker_order_ids=_normalise_order_ids(tuple(raw_order_ids)),
            state=state,
            revision=int(row["revision"]),
            episode_id=None if row["episode_id"] is None else int(row["episode_id"]),
        )

    @staticmethod
    def _episode(
        row: sqlite3.Row,
        affected_selectors: tuple[str, ...] = (),
    ) -> EmergencyEpisodeRecord:
        return EmergencyEpisodeRecord(
            episode_id=int(row["episode_id"]),
            source=str(row["source"]),
            selector=str(row["selector"]),
            session_key=str(row["session_key"]),
            state=str(row["state"]),
            revision=int(row["revision"]),
            affected_selectors=affected_selectors,
        )

    @classmethod
    def _episode_from_row(
        cls,
        conn: sqlite3.Connection,
        row: sqlite3.Row,
    ) -> EmergencyEpisodeRecord:
        targets = tuple(
            str(target[0])
            for target in conn.execute(
                """
                SELECT selector FROM emergency_episode_targets
                WHERE episode_id = ? ORDER BY selector
                """,
                (int(row["episode_id"]),),
            ).fetchall()
        )
        return cls._episode(row, targets)

    def activate_episode(
        self,
        *,
        source: str,
        selector: str,
        session_key: str,
        reason_hash: str,
    ) -> tuple[EmergencyEpisodeRecord, bool]:
        _validate_episode_fields(
            source=source,
            selector=selector,
            session_key=session_key,
            reason_hash=reason_hash,
        )
        with self._lock:
            conn = self._connect()
            try:
                conn.execute("BEGIN IMMEDIATE")
                row = conn.execute(
                    """
                    SELECT * FROM emergency_episodes
                    WHERE source = ? AND selector = ? AND state = 'active'
                    """,
                    (source, selector),
                ).fetchone()
                if row is not None:
                    if source == "mtm" and date.fromisoformat(session_key) > date.fromisoformat(
                        str(row["session_key"])
                    ):
                        cursor = conn.execute(
                            """
                            UPDATE emergency_episodes
                            SET session_key = ?, reason_hash = ?, revision = revision + 1
                            WHERE episode_id = ? AND state = 'active' AND revision = ?
                            """,
                            (session_key, reason_hash, int(row["episode_id"]), int(row["revision"])),
                        )
                        if cursor.rowcount != 1:
                            raise EmergencyIntentConflict("emergency episode changed during renewal")
                        row = conn.execute(
                            "SELECT * FROM emergency_episodes WHERE episode_id = ?",
                            (int(row["episode_id"]),),
                        ).fetchone()
                        if row is None:
                            raise RuntimeError("renewed emergency episode is unavailable")
                    conn.execute("COMMIT")
                    return self._episode_from_row(conn, row), False
                cursor = conn.execute(
                    """
                    INSERT INTO emergency_episodes (
                        source, selector, session_key, reason_hash, state, revision, created_at
                    ) VALUES (?, ?, ?, ?, 'active', 1, ?)
                    """,
                    (source, selector, session_key, reason_hash, datetime.now(timezone.utc).isoformat()),
                )
                row = conn.execute(
                    "SELECT * FROM emergency_episodes WHERE episode_id = ?",
                    (int(cursor.lastrowid),),
                ).fetchone()
                conn.execute("COMMIT")
                if row is None:
                    raise RuntimeError("emergency episode was not persisted")
                return self._episode_from_row(conn, row), True
            except Exception:
                if conn.in_transaction:
                    conn.execute("ROLLBACK")
                raise
            finally:
                conn.close()

    def active_episodes(self, source: str | None = None) -> tuple[EmergencyEpisodeRecord, ...]:
        if source is not None and source not in {"l5", "mtm"}:
            raise ValueError("emergency episode source must be l5 or mtm")
        with self._lock:
            conn = self._connect()
            try:
                if source is None:
                    rows = conn.execute(
                        "SELECT * FROM emergency_episodes WHERE state = 'active' ORDER BY episode_id"
                    ).fetchall()
                else:
                    rows = conn.execute(
                        """
                        SELECT * FROM emergency_episodes
                        WHERE state = 'active' AND source = ?
                        ORDER BY episode_id
                        """,
                        (source,),
                    ).fetchall()
                return tuple(self._episode_from_row(conn, row) for row in rows)
            finally:
                conn.close()

    def active_episode(self, *, source: str, selector: str) -> EmergencyEpisodeRecord | None:
        if source not in {"l5", "mtm"}:
            raise ValueError("emergency episode source must be l5 or mtm")
        with self._lock:
            conn = self._connect()
            try:
                row = conn.execute(
                    """
                    SELECT * FROM emergency_episodes
                    WHERE source = ? AND selector = ? AND state = 'active'
                    """,
                    (source, selector),
                ).fetchone()
                return None if row is None else self._episode_from_row(conn, row)
            finally:
                conn.close()

    def record_episode_targets(
        self,
        *,
        expected: EmergencyEpisodeRecord,
        selectors: tuple[str, ...],
    ) -> EmergencyEpisodeRecord:
        _validate_episode_snapshot(expected)
        canonical = _normalise_affected_selectors(selectors)
        with self._lock:
            conn = self._connect()
            try:
                conn.execute("BEGIN IMMEDIATE")
                row = conn.execute(
                    "SELECT * FROM emergency_episodes WHERE episode_id = ? AND state = 'active'",
                    (expected.episode_id,),
                ).fetchone()
                if row is None or self._episode_from_row(conn, row) != expected:
                    raise EmergencyIntentConflict("emergency episode changed while targets were recorded")
                added = 0
                for selector in canonical:
                    cursor = conn.execute(
                        """
                        INSERT OR IGNORE INTO emergency_episode_targets (episode_id, selector)
                        VALUES (?, ?)
                        """,
                        (expected.episode_id, selector),
                    )
                    added += cursor.rowcount
                if added:
                    cursor = conn.execute(
                        """
                        UPDATE emergency_episodes SET revision = revision + 1
                        WHERE episode_id = ? AND state = 'active' AND revision = ?
                        """,
                        (expected.episode_id, expected.revision),
                    )
                    if cursor.rowcount != 1:
                        raise EmergencyIntentConflict("emergency episode changed while targets were recorded")
                row = conn.execute(
                    "SELECT * FROM emergency_episodes WHERE episode_id = ? AND state = 'active'",
                    (expected.episode_id,),
                ).fetchone()
                if row is None:
                    raise EmergencyIntentConflict("emergency episode changed while targets were recorded")
                current = self._episode_from_row(conn, row)
                conn.execute("COMMIT")
                return current
            except Exception:
                if conn.in_transaction:
                    conn.execute("ROLLBACK")
                raise
            finally:
                conn.close()

    def blocking_sources(self, selector: str) -> frozenset[str]:
        if ":" not in selector or selector != selector.strip():
            raise ValueError("emergency selector must be canonical")
        with self._lock:
            conn = self._connect()
            try:
                rows = conn.execute(
                    """
                    SELECT DISTINCT source FROM emergency_episodes
                    WHERE state = 'active' AND (selector = '*' OR selector = ?)
                    """,
                    (selector,),
                ).fetchall()
                return frozenset(str(row[0]) for row in rows)
            finally:
                conn.close()

    def deactivate_episode(self, *, expected: EmergencyEpisodeRecord) -> None:
        self.deactivate_episodes(expected=(expected,))

    def deactivate_episodes(self, *, expected: tuple[EmergencyEpisodeRecord, ...]) -> None:
        if not expected:
            return
        for episode in expected:
            _validate_episode_snapshot(episode)
        if len({episode.episode_id for episode in expected}) != len(expected):
            raise ValueError("expected emergency episodes must be unique")
        sources = {episode.source for episode in expected}
        if len(sources) != 1:
            raise ValueError("expected emergency episodes must share a source")
        source = expected[0].source
        selectors = tuple(episode.selector for episode in expected)
        with self._lock:
            conn = self._connect()
            try:
                conn.execute("BEGIN IMMEDIATE")
                episode_placeholders = ",".join("?" for _episode in expected)
                rows = conn.execute(
                    f"""
                    SELECT * FROM emergency_episodes
                    WHERE episode_id IN ({episode_placeholders}) AND state = 'active'
                    ORDER BY episode_id
                    """,  # noqa: S608 - placeholders are generated, not caller-controlled
                    tuple(episode.episode_id for episode in expected),
                ).fetchall()
                current_by_id = {
                    int(row["episode_id"]): self._episode_from_row(conn, row) for row in rows
                }
                if any(current_by_id.get(episode.episode_id) != episode for episode in expected):
                    raise EmergencyIntentConflict("emergency episode changed during reset")
                if source == "l5":
                    unsettled = conn.execute(
                        """
                        SELECT 1 FROM emergency_intents
                        WHERE source = 'l5'
                          AND state IN ('reserved', 'acknowledged', 'outcome_unknown')
                        LIMIT 1
                        """
                    ).fetchone()
                else:
                    selector_placeholders = ",".join("?" for _selector in selectors)
                    unsettled = conn.execute(
                        f"""
                        SELECT 1 FROM emergency_intents
                        WHERE source = 'mtm' AND selector IN ({selector_placeholders})
                          AND state IN ('reserved', 'acknowledged', 'outcome_unknown')
                        LIMIT 1
                        """,  # noqa: S608 - placeholders are generated, not caller-controlled
                        selectors,
                    ).fetchone()
                if unsettled is not None:
                    raise EmergencyIntentConflict("emergency episode has unsettled broker intents")
                settled_at = datetime.now(timezone.utc).isoformat()
                for episode in expected:
                    cursor = conn.execute(
                        """
                        UPDATE emergency_episodes
                        SET state = 'settled', revision = revision + 1, settled_at = ?
                        WHERE episode_id = ? AND state = 'active' AND revision = ?
                        """,
                        (settled_at, episode.episode_id, episode.revision),
                    )
                    if cursor.rowcount != 1:
                        raise EmergencyIntentConflict("emergency episode changed during reset")
                conn.execute("COMMIT")
            except Exception:
                if conn.in_transaction:
                    conn.execute("ROLLBACK")
                raise
            finally:
                conn.close()

    def unresolved(
        self,
        selector: str,
        parent_verbs: tuple[str, ...],
        *,
        source: str | None = None,
    ) -> tuple[EmergencyIntentRecord, ...]:
        if not parent_verbs:
            return ()
        if source is not None and source not in _EPISODE_SOURCES:
            raise ValueError("emergency intent source is invalid")
        placeholders = ",".join("?" for _verb in parent_verbs)
        source_clause = "" if source is None else " AND source = ?"
        params: tuple[object, ...] = (selector, *parent_verbs) if source is None else (selector, *parent_verbs, source)
        with self._lock:
            conn = self._connect()
            try:
                rows = conn.execute(
                    f"""
                    SELECT * FROM emergency_intents
                    WHERE selector = ? AND parent_verb IN ({placeholders})
                      AND state IN ('reserved', 'acknowledged', 'outcome_unknown')
                      {source_clause}
                    ORDER BY intent_id
                    """,  # noqa: S608 - only generated placeholders and a fixed clause
                    params,
                ).fetchall()
                return tuple(self._record(row) for row in rows)
            finally:
                conn.close()

    @staticmethod
    def _active_episode_id(conn: sqlite3.Connection, source: str, selector: str) -> int | None:
        if source == "adhoc":
            return None
        row = conn.execute(
            """
            SELECT episode_id FROM emergency_episodes
            WHERE source = ? AND state = 'active' AND (selector = ? OR selector = '*')
            ORDER BY CASE WHEN selector = ? THEN 0 ELSE 1 END
            LIMIT 1
            """,
            (source, selector, selector),
        ).fetchone()
        return None if row is None else int(row[0])

    def reserve(
        self,
        *,
        source: str,
        selector: str,
        parent_verb: str,
        verb: str,
        payload_hash: str,
        scope: str,
        target_order_id: str = "",
        exit_tag: str = "",
    ) -> tuple[EmergencyIntentRecord, bool]:
        _validate_record_fields(
            source=source,
            selector=selector,
            parent_verb=parent_verb,
            verb=verb,
            payload_hash=payload_hash,
            scope=scope,
        )
        _validate_optional_token(target_order_id, field="target order id")
        _validate_optional_token(exit_tag, field="exit tag")
        with self._lock:
            conn = self._connect()
            try:
                conn.execute("BEGIN IMMEDIATE")
                episode_id = self._active_episode_id(conn, source, selector)
                if source != "adhoc" and episode_id is None:
                    raise EmergencyIntentConflict("active emergency episode is required before reservation")
                cursor = conn.execute(
                    """
                    INSERT OR IGNORE INTO emergency_intents (
                        source, selector, parent_verb, verb, payload_hash, scope,
                        target_order_id, exit_tag, state, revision, episode_id, created_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'reserved', 1, ?, ?)
                    """,
                    (
                        source,
                        selector,
                        parent_verb,
                        verb,
                        payload_hash,
                        scope,
                        target_order_id,
                        exit_tag,
                        episode_id,
                        datetime.now(timezone.utc).isoformat(),
                    ),
                )
                row = conn.execute(
                    """
                    SELECT * FROM emergency_intents
                    WHERE selector = ? AND parent_verb = ? AND scope = ?
                      AND state IN ('reserved', 'acknowledged', 'outcome_unknown')
                    """,
                    (selector, parent_verb, scope),
                ).fetchone()
                conn.execute("COMMIT")
                if row is None:
                    raise RuntimeError("emergency intent reservation was not persisted")
                return self._record(row), cursor.rowcount == 1
            except Exception:
                if conn.in_transaction:
                    conn.execute("ROLLBACK")
                raise
            finally:
                conn.close()

    def acknowledge(self, intent_id: int, broker_order_ids: tuple[str, ...]) -> None:
        canonical_ids = _normalise_order_ids(broker_order_ids)
        with self._lock:
            conn = self._connect()
            try:
                cursor = conn.execute(
                    """
                    UPDATE emergency_intents
                    SET broker_order_ids_json = ?, acknowledged_at = ?,
                        state = 'acknowledged', revision = revision + 1
                    WHERE intent_id = ?
                      AND state IN ('reserved', 'acknowledged', 'outcome_unknown')
                    """,
                    (
                        json.dumps(canonical_ids, separators=(",", ":")),
                        datetime.now(timezone.utc).isoformat(),
                        int(intent_id),
                    ),
                )
                if cursor.rowcount != 1:
                    raise KeyError(f"unknown active emergency intent {intent_id}")
            finally:
                conn.close()

    def mark_unknown(self, intent_id: int) -> None:
        with self._lock:
            conn = self._connect()
            try:
                cursor = conn.execute(
                    """
                    UPDATE emergency_intents
                    SET state = 'outcome_unknown', revision = revision + 1
                    WHERE intent_id = ?
                      AND state IN ('reserved', 'acknowledged', 'outcome_unknown')
                    """,
                    (int(intent_id),),
                )
                if cursor.rowcount != 1:
                    raise KeyError(f"unknown active emergency intent {intent_id}")
            finally:
                conn.close()

    def release(self, intent_id: int) -> None:
        with self._lock:
            conn = self._connect()
            try:
                conn.execute(
                    "DELETE FROM emergency_intents WHERE intent_id = ? AND state = 'reserved'",
                    (int(intent_id),),
                )
            finally:
                conn.close()

    def settle(
        self,
        selector: str,
        parent_verbs: tuple[str, ...],
        *,
        source: str,
        expected_intent_ids: tuple[int, ...],
    ) -> bool:
        if source not in _EPISODE_SOURCES:
            raise ValueError("emergency intent source is invalid")
        if len(set(expected_intent_ids)) != len(expected_intent_ids) or any(
            not isinstance(intent_id, int) or intent_id < 1 for intent_id in expected_intent_ids
        ):
            raise ValueError("expected emergency intent ids must be unique positive integers")
        if not parent_verbs:
            return not expected_intent_ids
        verb_placeholders = ",".join("?" for _verb in parent_verbs)
        with self._lock:
            conn = self._connect()
            try:
                conn.execute("BEGIN IMMEDIATE")
                rows = conn.execute(
                    f"""
                    SELECT intent_id FROM emergency_intents
                    WHERE source = ? AND selector = ?
                      AND parent_verb IN ({verb_placeholders})
                      AND state IN ('reserved', 'acknowledged', 'outcome_unknown')
                    ORDER BY intent_id
                    """,  # noqa: S608 - placeholders are generated, not caller-controlled
                    (source, selector, *parent_verbs),
                ).fetchall()
                current_ids = tuple(int(row[0]) for row in rows)
                expected_ids = tuple(sorted(expected_intent_ids))
                if current_ids != expected_ids:
                    conn.execute("ROLLBACK")
                    return False
                if current_ids:
                    intent_placeholders = ",".join("?" for _intent_id in current_ids)
                    cursor = conn.execute(
                        f"""
                        UPDATE emergency_intents
                        SET state = 'settled', revision = revision + 1, settled_at = ?
                        WHERE intent_id IN ({intent_placeholders})
                          AND state IN ('reserved', 'acknowledged', 'outcome_unknown')
                        """,  # noqa: S608 - placeholders are generated, not caller-controlled
                        (datetime.now(timezone.utc).isoformat(), *current_ids),
                    )
                    if cursor.rowcount != len(current_ids):
                        raise EmergencyIntentConflict("emergency intent set changed during settlement")
                conn.execute("COMMIT")
                return True
            except Exception:
                if conn.in_transaction:
                    conn.execute("ROLLBACK")
                raise
            finally:
                conn.close()
