"""Append-only memory evidence and transactionally recorded decision influence.

The runtime writer supplies centrally resolved rights; payload text and source
references are untrusted data, never permission grants or executable queries.
Vector and temporal caches may index these events but do not own their history.
"""

from __future__ import annotations

import hashlib
import json
import math
import os
import re
import sqlite3
import threading
from collections.abc import Iterator, Mapping
from contextlib import contextmanager
from dataclasses import dataclass, field, replace
from datetime import UTC, datetime
from enum import StrEnum
from pathlib import Path
from types import MappingProxyType
from typing import Any
from uuid import UUID, uuid4

from flinttrade_core.db import open_sqlite
from flinttrade_core.owner_file_lock import OwnerSafeFileLock
from flinttrade_core.secure_file import HeldOwnerDirectory, harden_directory, validate_owner_owned_regular_file
from flinttrade_core.service_providers import (
    EvidenceUseScope,
    LicenceFact,
    ModelIdentity,
    PermissionState,
    RightsBasis,
    RightsGrant,
    RightsResolution,
    UsageRights,
    intersect_rights,
)

MAX_PAYLOAD_BYTES = 64 * 1024
MAX_EVENT_BYTES = 128 * 1024
MAX_CONTEXT_BYTES = 1024 * 1024
_SCOPES = tuple(EvidenceUseScope)


class MemoryDomain(StrEnum):
    """The four explicit authoritative memory domains."""

    KNOWLEDGE = "knowledge"
    EPISODIC = "episodic"
    EXPERIMENT = "experiment"
    PROCEDURAL = "procedural"


class MemoryConflict(RuntimeError):
    """An immutable event or influence identity was reused inconsistently."""


class MemoryUnavailable(RuntimeError):
    """The authority cannot be proved intact; do not return decision context."""


def _id(value: object) -> str:
    if type(value) is not str or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.:-]{0,127}", value):
        raise ValueError("memory identity must be bounded identifier text")
    return value


def _utc(value: object) -> datetime:
    if type(value) is not datetime or value.tzinfo is None or value.utcoffset() != UTC.utcoffset(value):
        raise ValueError("memory times must be UTC datetimes")
    return value.replace(tzinfo=UTC)


def _stamp(value: datetime) -> str:
    return value.isoformat(timespec="microseconds")


def _canonical(value: object) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True, allow_nan=False)


def _digest(value: object) -> str:
    return hashlib.sha256(_canonical(value).encode()).hexdigest()


def _freeze(value: object, depth: int = 0, nodes: list[int] | None = None) -> Any:
    nodes = [0] if nodes is None else nodes
    nodes[0] += 1
    if depth > 16 or nodes[0] > 4096:
        raise ValueError("memory payload nesting or node limit exceeded")
    if value is None or type(value) in (str, bool):
        return value
    if type(value) is int:
        if not -(1 << 63) <= value < (1 << 63):
            raise ValueError("memory JSON integers must fit signed 64 bits")
        return value
    if type(value) is float and math.isfinite(value):
        return value
    if isinstance(value, Mapping):
        if any(type(key) is not str for key in value):
            raise ValueError("memory JSON object keys must be strings")
        return MappingProxyType({key: _freeze(item, depth + 1, nodes) for key, item in value.items()})
    if type(value) in (list, tuple):
        return tuple(_freeze(item, depth + 1, nodes) for item in value)
    raise ValueError("memory payload must be finite JSON data or text")


def _thaw(value: Any) -> Any:
    if isinstance(value, Mapping):
        return {key: _thaw(item) for key, item in value.items()}
    if type(value) is tuple:
        return [_thaw(item) for item in value]
    return value


def _refs(values: object, *, required: bool = False) -> tuple[str, ...]:
    if type(values) not in (tuple, list) or len(values) > 64:
        raise ValueError("memory references must be a bounded sequence")
    if any(
        type(value) is not str or not value.strip() or len(value) > 1024 or any(ord(c) < 32 for c in value)
        for value in values
    ):
        raise ValueError("invalid memory reference")
    if len(set(values)) != len(values) or (required and not values):
        raise ValueError("memory references must be unique and include required sources")
    return tuple(values)


def _rights(value: Mapping[str, Any]) -> RightsResolution:
    """Decode only previously persisted runtime-resolved rights, never payload fields."""

    def usage(raw: Mapping[str, Any]) -> UsageRights:
        return UsageRights(
            **{
                key: EvidenceUseScope(item)
                if key == "max_evidence_use_scope"
                else tuple(item)
                if key == "restrictions"
                else PermissionState(item)
                for key, item in raw.items()
            }
        )

    grants = []
    for raw in value["grants"]:
        facts = tuple(LicenceFact(**{**fact, "basis": RightsBasis(fact["basis"])}) for fact in raw["evidence"])
        grants.append(
            RightsGrant(
                grant_id=raw["grant_id"],
                basis=RightsBasis(raw["basis"]),
                rights=usage(raw["rights"]),
                evidence=facts,
                model_identity=None if raw["model_identity"] is None else ModelIdentity(**raw["model_identity"]),
            )
        )
    result = RightsResolution(rights=usage(value["rights"]), grants=tuple(grants))
    if result.to_public_dict() != value:
        raise ValueError("noncanonical stored memory rights")
    return result


@dataclass(frozen=True, slots=True)
class MemoryEvent:
    """Immutable evidence; a correction is an additional event, never a replacement."""

    event_id: str
    domain: MemoryDomain
    payload: Any
    as_of: datetime
    source_refs: tuple[str, ...]
    provenance_refs: tuple[str, ...] = ()
    rights: RightsResolution = field(default_factory=RightsResolution)
    parent_ids: tuple[str, ...] = ()
    correction_of: str | None = None

    def __post_init__(self) -> None:
        _id(self.event_id)
        if type(self.domain) is not MemoryDomain or type(self.rights) is not RightsResolution:
            raise ValueError("explicit memory domain and runtime-resolved rights required")
        object.__setattr__(self, "as_of", _utc(self.as_of))
        object.__setattr__(self, "source_refs", _refs(self.source_refs, required=True))
        object.__setattr__(self, "provenance_refs", _refs(self.provenance_refs))
        parents = _refs(self.parent_ids)
        for parent in parents:
            _id(parent)
        if self.correction_of is not None:
            _id(self.correction_of)
        if self.event_id in parents or self.correction_of == self.event_id:
            raise ValueError("memory event cannot reference itself")
        object.__setattr__(self, "parent_ids", parents)
        object.__setattr__(self, "payload", _freeze(self.payload))
        if len(_canonical(_thaw(self.payload)).encode()) > MAX_PAYLOAD_BYTES:
            raise ValueError("memory payload byte limit exceeded")
        # Revalidate canonical evidence rather than trusting a dict disguised
        # as rights; bounded encoding also constrains the provenance graph.
        _rights(self.rights.to_public_dict())
        if len(_canonical(self._body()).encode()) > MAX_EVENT_BYTES:
            raise ValueError("memory event byte limit exceeded")

    @property
    def payload_digest(self) -> str:
        """Canonical digest of the immutable JSON/text payload alone."""
        return _digest(_thaw(self.payload))

    def _body(self) -> dict[str, Any]:
        return {
            "event_id": self.event_id,
            "domain": self.domain.value,
            "payload": _thaw(self.payload),
            "as_of": _stamp(self.as_of),
            "source_refs": list(self.source_refs),
            "provenance_refs": list(self.provenance_refs),
            "rights": self.rights.to_public_dict(),
            "parent_ids": list(self.parent_ids),
            "correction_of": self.correction_of,
        }

    @property
    def digest(self) -> str:
        """Digest binding payload, time, lineage and resolved rights."""
        return _digest(self._body())

    def to_dict(self) -> dict[str, Any]:
        """Detach event evidence for an API or derived index."""
        return {**self._body(), "payload_digest": self.payload_digest, "digest": self.digest}


@dataclass(frozen=True, slots=True)
class MemoryQuery:
    """Bounded deterministic filters; text is a literal case-insensitive substring."""

    domain: MemoryDomain | None = None
    event_ids: tuple[str, ...] = ()
    text: str = ""
    limit: int = 50
    minimum_scope: EvidenceUseScope = EvidenceUseScope.ISOLATED_RESEARCH

    def __post_init__(self) -> None:
        if self.domain is not None and type(self.domain) is not MemoryDomain:
            raise ValueError("invalid memory query domain")
        if type(self.minimum_scope) is not EvidenceUseScope:
            raise ValueError("invalid memory evidence scope")
        if type(self.limit) is not int or not 1 <= self.limit <= 100:
            raise ValueError("memory result limit must be in 1..100")
        if type(self.text) is not str or len(self.text) > 1024:
            raise ValueError("memory text query must be bounded text")
        ids = _refs(self.event_ids)
        for identity in ids:
            _id(identity)
        object.__setattr__(self, "event_ids", tuple(sorted(ids)))

    def to_dict(self) -> dict[str, Any]:
        """Detach the exact query/filter used for influence selection."""
        return {
            "domain": self.domain.value if self.domain else None,
            "event_ids": list(self.event_ids),
            "text": self.text,
            "limit": self.limit,
            "minimum_scope": self.minimum_scope.value,
        }


@dataclass(frozen=True, slots=True)
class InfluenceReceipt:
    """Exact immutable decision inputs and their policy/provenance intersection."""

    receipt_id: str
    decision_id: str
    request_id: str
    decision_time: datetime
    query: MemoryQuery
    event_ids: tuple[str, ...]
    payload_digests: tuple[str, ...]
    event_digests: tuple[str, ...]
    rights: RightsResolution
    ledger_incarnation: str

    def _body(self) -> dict[str, Any]:
        return {
            "receipt_id": self.receipt_id,
            "decision_id": self.decision_id,
            "request_id": self.request_id,
            "decision_time": _stamp(self.decision_time),
            "query": self.query.to_dict(),
            "event_ids": list(self.event_ids),
            "payload_digests": list(self.payload_digests),
            "event_digests": list(self.event_digests),
            "rights": self.rights.to_public_dict(),
            "ledger_incarnation": self.ledger_incarnation,
        }

    @property
    def digest(self) -> str:
        """Canonical digest of this exact decision influence receipt."""
        return _digest(self._body())

    def to_dict(self) -> dict[str, Any]:
        """Detach the receipt including its canonical digest."""
        return {**self._body(), "digest": self.digest}


@dataclass(frozen=True, slots=True)
class DecisionMemoryContext:
    """Recorded inputs and receipt returned only after the transaction commits."""

    events: tuple[MemoryEvent, ...]
    receipt: InfluenceReceipt

    def to_dict(self) -> dict[str, Any]:
        """Detach the recorded context without exposing ledger handles."""
        return {"events": [event.to_dict() for event in self.events], "receipt": self.receipt.to_dict()}


_SCHEMA = (
    "CREATE TABLE metadata (incarnation TEXT PRIMARY KEY)",
    (
        "CREATE TABLE events (event_id TEXT PRIMARY KEY, domain TEXT NOT NULL, as_of TEXT NOT NULL, "
        "scope TEXT NOT NULL, search_text TEXT NOT NULL, body TEXT NOT NULL, digest TEXT NOT NULL)"
    ),
    "CREATE INDEX events_selection ON events(as_of, event_id)",
    (
        "CREATE TABLE receipts (receipt_id TEXT PRIMARY KEY, decision_id TEXT NOT NULL, request_id TEXT NOT NULL, "
        "body TEXT NOT NULL, digest TEXT NOT NULL, UNIQUE(decision_id, request_id))"
    ),
    *(
        f"CREATE TRIGGER {table}_no_{operation.lower()} BEFORE {operation} ON {table} "
        "BEGIN SELECT RAISE(ABORT, 'immutable memory evidence'); END"
        for table in ("events", "receipts", "metadata")
        for operation in ("UPDATE", "DELETE")
    ),
)


def _event_from_body(body: str) -> MemoryEvent:
    value = json.loads(body)
    return MemoryEvent(
        **{
            **value,
            "domain": MemoryDomain(value["domain"]),
            "as_of": datetime.fromisoformat(value["as_of"]),
            "rights": _rights(value["rights"]),
        }
    )


class MemoryLedger:
    """Owner-only FULL-durability authority with no update/delete API.

    The trusted composition root owns this writer. `read_projection` exposes
    only receipt-backed retrieval/replay, not the event writer. That object is
    an API capability boundary, not a defence against arbitrary Python object
    introspection; untrusted workers still require process/gateway isolation.
    """

    def __init__(self, root: Path) -> None:
        self._root = Path(root).absolute()
        self._closed = False
        self._pid = os.getpid()
        self._thread_lock = threading.RLock()
        try:
            self._root.mkdir(mode=0o700)
        except FileExistsError:
            pass
        else:
            harden_directory(self._root)
        self._directory = HeldOwnerDirectory(self._root).__enter__()
        self._lock = OwnerSafeFileLock(str(self._root / "ledger.lock"), timeout=10)
        self._path = self._root / "memory.sqlite"
        try:
            with self._lock:
                exists = self._directory.exists("memory.sqlite")
                if not exists:
                    if self._directory.exists("authority.json"):
                        raise MemoryUnavailable("memory database is missing")
                    self._directory.create_empty_hardened_member("memory.sqlite")
                self._validate_files()
                with self._database() as db:
                    if not exists:
                        identity = str(uuid4())
                        db.execute("BEGIN IMMEDIATE")
                        for statement in _SCHEMA:
                            db.execute(statement)
                        db.execute("INSERT INTO metadata VALUES (?)", (identity,))
                        db.execute("PRAGMA user_version = 1")
                        db.commit()
                        self._directory.write_text("authority.json", _canonical({"incarnation": identity}))
                    marker = json.loads(self._directory.read_text("authority.json"))
                    identity = marker["incarnation"]
                    if set(marker) != {"incarnation"} or str(UUID(identity)) != identity:
                        raise MemoryUnavailable("invalid memory authority marker")
                    self._incarnation = identity
                    self._validate_schema(db)
                info = validate_owner_owned_regular_file(self._path, require_hardened=True)
                self._file_identity = (info.st_dev, info.st_ino)
        except BaseException:
            self._directory.__exit__()
            raise

    def _validate_files(self) -> None:
        self._directory.revalidate()
        for suffix in ("", "-wal", "-shm", "-journal"):
            name = "memory.sqlite" + suffix
            if self._directory.exists(name):
                info = validate_owner_owned_regular_file(self._root / name, require_hardened=True)
                if not suffix and hasattr(self, "_file_identity"):
                    if (info.st_dev, info.st_ino) != self._file_identity:
                        raise MemoryUnavailable("memory database was replaced")
            elif not suffix:
                raise MemoryUnavailable("memory database is missing")

    def _validate_schema(self, db: sqlite3.Connection) -> None:
        actual = {row[0] for row in db.execute("SELECT sql FROM sqlite_master WHERE name NOT GLOB 'sqlite_*'")}
        if db.execute("PRAGMA user_version").fetchone()[0] != 1 or actual != set(_SCHEMA):
            raise MemoryUnavailable("memory database schema changed")
        if db.execute("SELECT incarnation FROM metadata").fetchall() != [(self._incarnation,)]:
            raise MemoryUnavailable("memory database incarnation changed")
        if json.loads(self._directory.read_text("authority.json")) != {"incarnation": self._incarnation}:
            raise MemoryUnavailable("memory authority marker changed")

    @contextmanager
    def _database(self) -> Iterator[sqlite3.Connection]:
        db = open_sqlite(self._path, durability="full", strict_existing=True)
        try:
            self._validate_files()
            yield db
        finally:
            db.close()

    @contextmanager
    def _transaction(self) -> Iterator[sqlite3.Connection]:
        with self._thread_lock:
            if self._closed or os.getpid() != self._pid:
                raise MemoryUnavailable("memory authority closed or inherited across fork")
            with self._lock:
                self._validate_files()
                with self._database() as db:
                    db.execute("BEGIN IMMEDIATE")
                    try:
                        self._validate_schema(db)
                        yield db
                        self._validate_files()
                        db.commit()
                    except BaseException:
                        db.rollback()
                        raise

    def close(self) -> None:
        """Release filesystem ownership handles; never remove evidence."""
        with self._thread_lock:
            if not self._closed:
                self._closed = True
                self._directory.__exit__()

    def __enter__(self) -> MemoryLedger:
        return self

    def __exit__(self, *args: object) -> None:
        self.close()

    @staticmethod
    def _event(db: sqlite3.Connection, identity: str) -> MemoryEvent:
        row = db.execute("SELECT body, digest FROM events WHERE event_id=?", (identity,)).fetchone()
        if row is None:
            raise KeyError(identity)
        try:
            event = _event_from_body(row[0])
            if event.event_id != identity or event.digest != row[1]:
                raise ValueError("memory event digest mismatch")
            return event
        except (ValueError, TypeError, KeyError) as exc:
            raise MemoryUnavailable("invalid stored memory event") from exc

    def append(self, event: MemoryEvent) -> MemoryEvent:
        """Append exact evidence idempotently, intersecting every parent ceiling."""
        if type(event) is not MemoryEvent:
            raise ValueError("exact MemoryEvent required")
        with self._transaction() as db:
            ancestors = []
            identities = tuple(
                dict.fromkeys((*event.parent_ids, *((event.correction_of,) if event.correction_of else ())))
            )
            for identity in identities:
                try:
                    parent = self._event(db, identity)
                except KeyError as exc:
                    raise ValueError("memory parent must exist") from exc
                if parent.as_of > event.as_of:
                    raise ValueError("memory parent cannot come from the future")
                if identity == event.correction_of and (
                    parent.domain is not event.domain or parent.as_of >= event.as_of
                ):
                    raise ValueError("correction must follow its original within the same domain")
                ancestors.append(parent.rights)
            if ancestors:
                event = replace(event, rights=intersect_rights(event.rights, *ancestors))
            previous = db.execute("SELECT digest FROM events WHERE event_id=?", (event.event_id,)).fetchone()
            if previous:
                if previous[0] != event.digest:
                    raise MemoryConflict("memory event identity conflicts")
                return self._event(db, event.event_id)
            db.execute(
                "INSERT INTO events VALUES (?, ?, ?, ?, ?, ?, ?)",
                (
                    event.event_id,
                    event.domain.value,
                    _stamp(event.as_of),
                    event.rights.rights.max_evidence_use_scope.value,
                    _canonical(_thaw(event.payload)).casefold(),
                    _canonical(event._body()),
                    event.digest,
                ),
            )
            return event

    def read_projection(self) -> MemoryReadProjection:
        """Return only receipt-backed retrieval/replay operations for the gateway."""
        return MemoryReadProjection(self)

    def _select(self, db: sqlite3.Connection, decision_time: datetime, query: MemoryQuery) -> tuple[MemoryEvent, ...]:
        clauses, arguments = ["as_of <= ?"], [_stamp(decision_time)]
        if query.domain is not None:
            clauses.append("domain=?")
            arguments.append(query.domain.value)
        if query.event_ids:
            clauses.append("event_id IN (" + ",".join("?" for _ in query.event_ids) + ")")
            arguments.extend(query.event_ids)
        if query.text:
            clauses.append("instr(search_text, ?) > 0")
            arguments.append(query.text.casefold())
        scopes = _SCOPES[_SCOPES.index(query.minimum_scope) :]
        clauses.append("scope IN (" + ",".join("?" for _ in scopes) + ")")
        arguments.extend(scope.value for scope in scopes)
        rows = db.execute(
            "SELECT event_id FROM events WHERE " + " AND ".join(clauses) + " ORDER BY as_of, event_id LIMIT ?",
            (*arguments, query.limit),
        ).fetchall()
        events = tuple(self._event(db, row[0]) for row in rows)
        if any(
            event.as_of > decision_time
            or _SCOPES.index(event.rights.rights.max_evidence_use_scope) < _SCOPES.index(query.minimum_scope)
            for event in events
        ):
            raise MemoryUnavailable("memory selection metadata mismatch")
        if sum(len(_canonical(event._body()).encode()) for event in events) > MAX_CONTEXT_BYTES:
            raise ValueError("memory context byte limit exceeded")
        return events

    def _recall(
        self, *, receipt_id: str, decision_id: str, request_id: str, decision_time: datetime, query: MemoryQuery
    ) -> DecisionMemoryContext:
        for identity in (receipt_id, decision_id, request_id):
            _id(identity)
        decision_time = _utc(decision_time)
        if type(query) is not MemoryQuery:
            raise ValueError("exact MemoryQuery required")
        with self._transaction() as db:
            previous = db.execute(
                "SELECT receipt_id FROM receipts WHERE receipt_id=? OR (decision_id=? AND request_id=?)",
                (receipt_id, decision_id, request_id),
            ).fetchone()
            if previous:
                context = self._replay(db, previous[0])
                recorded = context.receipt
                if (
                    recorded.receipt_id,
                    recorded.decision_id,
                    recorded.request_id,
                    recorded.decision_time,
                    recorded.query,
                ) != (
                    receipt_id,
                    decision_id,
                    request_id,
                    decision_time,
                    query,
                ):
                    raise MemoryConflict("decision influence identity conflicts")
                return context
            events = self._select(db, decision_time, query)
            receipt = InfluenceReceipt(
                receipt_id,
                decision_id,
                request_id,
                decision_time,
                query,
                tuple(event.event_id for event in events),
                tuple(event.payload_digest for event in events),
                tuple(event.digest for event in events),
                intersect_rights(*(event.rights for event in events)),
                self._incarnation,
            )
            if len(_canonical(receipt._body()).encode()) > MAX_CONTEXT_BYTES:
                raise ValueError("memory receipt byte limit exceeded")
            db.execute(
                "INSERT INTO receipts VALUES (?, ?, ?, ?, ?)",
                (receipt_id, decision_id, request_id, _canonical(receipt._body()), receipt.digest),
            )
            return DecisionMemoryContext(events, receipt)

    def _replay(self, db: sqlite3.Connection, receipt_id: str) -> DecisionMemoryContext:
        row = db.execute("SELECT body, digest FROM receipts WHERE receipt_id=?", (receipt_id,)).fetchone()
        if row is None:
            raise KeyError(receipt_id)
        try:
            values = json.loads(row[0])
            query = values["query"]
            receipt = InfluenceReceipt(
                **{
                    **values,
                    "decision_time": _utc(datetime.fromisoformat(values["decision_time"])),
                    "query": MemoryQuery(
                        **{
                            **query,
                            "domain": None if query["domain"] is None else MemoryDomain(query["domain"]),
                            "minimum_scope": EvidenceUseScope(query["minimum_scope"]),
                        }
                    ),
                    "event_ids": tuple(values["event_ids"]),
                    "payload_digests": tuple(values["payload_digests"]),
                    "event_digests": tuple(values["event_digests"]),
                    "rights": _rights(values["rights"]),
                }
            )
            if (
                receipt.receipt_id != receipt_id
                or receipt.digest != row[1]
                or receipt.ledger_incarnation != self._incarnation
            ):
                raise ValueError("influence digest or incarnation mismatch")
            events = tuple(self._event(db, identity) for identity in receipt.event_ids)
            if (
                tuple(event.digest for event in events) != receipt.event_digests
                or tuple(event.payload_digest for event in events) != receipt.payload_digests
                or any(event.as_of > receipt.decision_time for event in events)
            ):
                raise ValueError("recorded memory influence changed")
            return DecisionMemoryContext(events, receipt)
        except (ValueError, TypeError, KeyError) as exc:
            raise MemoryUnavailable("invalid stored memory influence") from exc


class MemoryReadProjection:
    """Public retrieval/replay capability; no writer or raw ledger accessor."""

    __slots__ = ("__ledger",)

    def __init__(self, ledger: MemoryLedger) -> None:
        self.__ledger = ledger

    def recall(
        self, *, receipt_id: str, decision_id: str, request_id: str, decision_time: datetime, query: MemoryQuery
    ) -> DecisionMemoryContext:
        """Persist exact selected inputs before returning them for a decision."""
        return self.__ledger._recall(
            receipt_id=receipt_id,
            decision_id=decision_id,
            request_id=request_id,
            decision_time=decision_time,
            query=query,
        )

    def replay(self, receipt_id: str) -> DecisionMemoryContext:
        """Return recorded inputs verbatim; never rerun retrieval or ranking."""
        _id(receipt_id)
        with self.__ledger._transaction() as db:
            return self.__ledger._replay(db, receipt_id)
