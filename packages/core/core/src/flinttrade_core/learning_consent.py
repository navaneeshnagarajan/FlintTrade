"""Core-owned learning permission at send initiation, separate from inference.

No credential or raw private payload is retained here. ServiceUsageLedger owns
provider reservations; this ledger adds immutable consent/membership evidence and
cumulative dataset limits. Only the trusted gateway calls dispatch. Its callback
must initiate the exact bounded send now, not hand a permit to an untrusted worker.
"""
from __future__ import annotations

import hashlib
import json
import os
import sqlite3
import threading
from collections.abc import Callable, Iterator, Mapping
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from types import MappingProxyType
from typing import Any
from urllib.parse import urlsplit
from uuid import uuid4

from flinttrade_core.db import open_sqlite
from flinttrade_core.owner_file_lock import OwnerSafeFileLock
from flinttrade_core.secure_file import HeldOwnerDirectory, harden_directory, validate_owner_owned_regular_file
from flinttrade_core.service_connections import ServiceConnectionRef
from flinttrade_core.service_providers import PermissionState, RightsResolution
from flinttrade_core.service_usage import ServiceUsageLedger
from flinttrade_core.service_usage_contracts import (
    USAGE_DIMENSIONS,
    TariffSnapshot,
    UsageAmounts,
    canonical,
    integer,
    text,
    utc,
)

PURPOSES = frozenset({"reflection", "teacher", "judge", "labelling", "synthesis", "evaluation",
                      "embedding", "ocr", "fine-tuning", "dataset-transfer"})


class LearningRefused(RuntimeError):
    """The requested learning send has no current exact bounded authority."""


def _hash(value: Any) -> str:
    return hashlib.sha256(canonical(value).encode()).hexdigest()


def _sequence(values: tuple[str, ...], name: str) -> tuple[str, ...]:
    if not values or len(values) > 256 or len(set(values)) != len(values):
        raise ValueError(f"explicit unique {name} required")
    return tuple(text(value, name) for value in values)


@dataclass(frozen=True)
class DatasetScope:
    """Versioned bounded future-membership policy, not a mutable dataset filename."""

    dataset_id: str
    revision: str
    accounts: tuple[str, ...]
    environments: tuple[str, ...]
    runs: tuple[str, ...]
    sources: tuple[str, ...]
    fields: tuple[str, ...]
    splits: tuple[str, ...]
    transform: str
    as_of_start: datetime
    as_of_end: datetime

    def __post_init__(self) -> None:
        for key in ("dataset_id", "revision", "transform"):
            text(getattr(self, key), key)
        for key in ("accounts", "environments", "runs", "sources", "fields", "splits"):
            object.__setattr__(self, key, _sequence(getattr(self, key), key))
        utc(self.as_of_start)
        utc(self.as_of_end)
        if self.as_of_end <= self.as_of_start:
            raise ValueError("empty dataset interval")

    def to_dict(self) -> dict[str, Any]:
        """Detached immutable scope material for membership and UI preview."""
        return {key: value.isoformat() if isinstance(value, datetime) else list(value) if isinstance(value, tuple)
                else value for key, value in vars(self).items()}


@dataclass(frozen=True)
class DatasetRecord:
    """Canonical writer-supplied row metadata and rights, not model assertions."""

    record_id: str
    account: str
    environment: str
    run: str
    source: str
    as_of: datetime
    split: str
    values: Mapping[str, Any]
    rights: RightsResolution

    def __post_init__(self) -> None:
        for key in ("record_id", "account", "environment", "run", "source", "split"):
            text(getattr(self, key), key)
        utc(self.as_of)
        if type(self.rights) is not RightsResolution:
            raise ValueError("resolved rights required")
        # Canonicalise immediately; caller mutations cannot change membership hashes.
        object.__setattr__(self, "values", MappingProxyType(json.loads(canonical(dict(self.values)))))


@dataclass(frozen=True)
class Recipient:
    """Exact non-secret recipient identity including every approved downstream hop."""

    connection: ServiceConnectionRef
    connection_revision: str
    principal: str
    credential_generation: str
    auth_route: str
    endpoint: str
    region: str
    terms_revision: str
    model: str
    model_revision: str
    method: str
    downstream: tuple[str, ...]

    def __post_init__(self) -> None:
        if type(self.connection) is not ServiceConnectionRef:
            raise ValueError("canonical connection required")
        for key, value in vars(self).items():
            if key not in {"connection", "downstream"}:
                text(value, key)
        url = urlsplit(self.endpoint)
        if url.scheme not in {"https", "http"} or not url.netloc or url.username or url.password or url.query or url.fragment:
            raise ValueError("exact non-secret endpoint required")
        object.__setattr__(self, "downstream", tuple(text(hop, "processor identity") for hop in self.downstream))

    def to_dict(self) -> dict[str, Any]:
        """Public identity only; no credential bodies."""
        return {**vars(self), "connection": self.connection.to_dict(), "downstream": list(self.downstream)}


_SCHEMA = (
    "CREATE TABLE documents (id TEXT PRIMARY KEY, kind TEXT NOT NULL, body TEXT NOT NULL, digest TEXT NOT NULL)",
    "CREATE TABLE events (seq INTEGER PRIMARY KEY, subject TEXT NOT NULL, body TEXT NOT NULL, digest TEXT NOT NULL)",
    *(f"CREATE TRIGGER {table}_no_{op.lower()} BEFORE {op} ON {table} "
      "BEGIN SELECT RAISE(ABORT, 'immutable learning evidence'); END"
      for table in ("documents", "events") for op in ("UPDATE", "DELETE")),
)


class LearningConsentLedger:
    """Durable grant/manifest/receipt authority; no provider I/O during construction.

    dispatch serialises revocation with send initiation, commits the attempt before
    I/O, and never retries. A synchronous callback holds the fence until it returns;
    gateways should use bounded initiation, then reconcile remote completion.
    """

    def __init__(self, root: Path, *, usage: ServiceUsageLedger,
                 clock: Callable[[], datetime] | None = None) -> None:
        self.root, self.usage = Path(root).absolute(), usage
        self.clock = clock or (lambda: datetime.now(UTC))
        self.root.mkdir(mode=0o700, parents=True, exist_ok=True)
        harden_directory(self.root)
        self._directory = HeldOwnerDirectory(self.root).__enter__()
        self._lock = OwnerSafeFileLock(str(self.root / "learning.lock"), timeout=10)
        self._thread_lock = threading.RLock()
        self._pid, self._closed = os.getpid(), False
        self.path = self.root / "consent.sqlite"
        with self._lock:
            exists = self._directory.exists("consent.sqlite")
            if not exists:
                if self._directory.exists("authority.json"):
                    raise LearningRefused("learning database missing")
                self._directory.create_empty_hardened_member("consent.sqlite")
                with self._db() as db:
                    for statement in _SCHEMA:
                        db.execute(statement)
                self._directory.write_text("authority.json", canonical({"id": str(uuid4())}))
            self._marker = self._directory.read_text("authority.json")
            self._identity = self.path.stat().st_ino
            with self._db():
                pass

    @contextmanager
    def _db(self) -> Iterator[sqlite3.Connection]:
        if self._closed or self._pid != os.getpid():
            raise LearningRefused("learning authority closed or inherited")
        self._directory.revalidate()
        info = validate_owner_owned_regular_file(self.path, require_hardened=True)
        if hasattr(self, "_identity") and (info.st_ino != self._identity or
                                           self._directory.read_text("authority.json") != self._marker):
            raise LearningRefused("learning authority replaced")
        db = open_sqlite(self.path, durability="full", strict_existing=True)
        try:
            db.execute("BEGIN IMMEDIATE")
            if hasattr(self, "_identity"):
                schema = {row[0] for row in db.execute("SELECT sql FROM sqlite_master WHERE name NOT GLOB 'sqlite_*'")}
                if schema != set(_SCHEMA):
                    raise LearningRefused("learning schema changed")
            yield db
            db.commit()
        except BaseException:
            db.rollback()
            raise
        finally:
            db.close()

    def close(self) -> None:
        """Release ownership without purging consent evidence or provider usage."""
        with self._thread_lock:
            if not self._closed:
                self._directory.__exit__()
                self._closed = True

    @staticmethod
    def _put(db: sqlite3.Connection, identity: str, kind: str, body: dict[str, Any]) -> None:
        encoded = canonical(body)
        old = db.execute("SELECT kind, body, digest FROM documents WHERE id=?", (identity,)).fetchone()
        if old:
            if old != (kind, encoded, _hash(body)):
                raise LearningRefused("immutable learning identity conflict")
        else:
            db.execute("INSERT INTO documents VALUES (?, ?, ?, ?)", (identity, kind, encoded, _hash(body)))

    @staticmethod
    def _get(db: sqlite3.Connection, identity: str, kind: str) -> dict[str, Any]:
        row = db.execute("SELECT kind, body, digest FROM documents WHERE id=?", (identity,)).fetchone()
        if row is None or row[0] != kind:
            raise LearningRefused(f"missing {kind}")
        value = json.loads(row[1])
        if _hash(value) != row[2]:
            raise LearningRefused("learning evidence corrupted")
        return value

    @staticmethod
    def _event(db: sqlite3.Connection, subject: str, body: dict[str, Any]) -> None:
        db.execute("INSERT INTO events(subject, body, digest) VALUES (?, ?, ?)",
                   (subject, canonical(body), _hash(body)))

    @staticmethod
    def _events(db: sqlite3.Connection, subject: str) -> list[dict[str, Any]]:
        result = []
        for encoded, digest in db.execute("SELECT body, digest FROM events WHERE subject=? ORDER BY seq", (subject,)):
            value = json.loads(encoded)
            if _hash(value) != digest:
                raise LearningRefused("learning lifecycle evidence corrupted")
            result.append(value)
        return result

    def grant(self, *, scope: DatasetScope, recipient: Recipient, purpose: str, operations: tuple[str, ...],
              approver: str, valid_from: datetime, valid_until: datetime, limits: Mapping[str, int],
              max_rows: int, max_trials: int, retention: str, derivatives: str,
              confirmation: str, objective: str, supersedes: str | None = None) -> str:
        """Mint one explicitly confirmed dataset/recipient/purpose tuple, never defaults.

        The authenticated core action supplies approver and confirmation evidence.
        This writer must not be exposed directly to an agent or unauthenticated UI.
        """
        if purpose not in PURPOSES or not operations or any(op in {"publish", "export"} for op in operations):
            raise ValueError("explicit learning purpose/operations required; publication needs separate authority")
        if set(limits) != set(USAGE_DIMENSIONS):
            raise ValueError("all learning limits must be explicit")
        for name, amount in limits.items():
            integer(amount, name)
        integer(max_rows, "max_rows")
        integer(max_trials, "max_trials")
        if utc(valid_until) <= utc(valid_from):
            raise ValueError("empty consent interval")
        for name, value in (("approver", approver), ("retention", retention), ("derivatives", derivatives),
                            ("confirmation", confirmation), ("objective", objective)):
            text(value, name)
        identity = str(uuid4())
        value = {"revision": 1, "scope": scope.to_dict(), "scope_hash": _hash(scope.to_dict()),
                 "recipient": recipient.to_dict(), "purpose": purpose, "operations": list(operations),
                 "approver": approver, "valid_from": valid_from.isoformat(), "valid_until": valid_until.isoformat(),
                 "limits": dict(limits), "max_rows": max_rows, "max_trials": max_trials, "retention": retention,
                 "derivatives": derivatives, "confirmation_hash": _hash(confirmation), "objective": objective,
                 # Connection/revision cloning and new batches cannot reset dataset counters.
                 "budget_key": _hash([scope.dataset_id, recipient.connection.provider_id, recipient.principal, purpose])}
        with self._thread_lock, self._lock, self._db() as db:
            if supersedes is not None:
                previous = self._get(db, supersedes, "grant")
                value["revision"] = previous["revision"] + 1
                value["supersedes"] = supersedes
                # Explicit confirmation may narrow or expand scope. Neither
                # action resets cumulative use or leaves an old queued grant alive.
                value["budget_key"] = previous["budget_key"]
                self._event(db, supersedes, {"kind": "revoked", "actor": approver,
                                            "at": self.clock().isoformat(), "replacement": identity})
            self._put(db, identity, "grant", value)
        return identity

    def batch(self, scope: DatasetScope, records: tuple[DatasetRecord, ...], payload: bytes, *, transform: str) -> str:
        """Freeze an exact send projection and rights/membership proof, without raw data retention."""
        if type(payload) is not bytes or not records or len({r.record_id for r in records}) != len(records):
            raise ValueError("non-empty unique records and exact bytes required")
        if transform != scope.transform:
            raise LearningRefused("dataset transform scope changed")
        members = []
        for record in records:
            if (record.account not in scope.accounts or record.environment not in scope.environments
                or record.run not in scope.runs or record.source not in scope.sources or record.split not in scope.splits
                or not scope.as_of_start <= record.as_of < scope.as_of_end
                or record.as_of > utc(self.clock())
                or not set(record.values) <= set(scope.fields)):
                raise LearningRefused("dataset membership scope expansion")
            if any(getattr(record.rights.rights, key) is not PermissionState.ALLOWED
                   for key in ("training_distillation", "output_use", "retention")):
                raise LearningRefused("learning rights denied or unresolved")
            members.append({"record_id": record.record_id, "account": record.account, "environment": record.environment,
                            "run": record.run, "source": record.source, "as_of": record.as_of.isoformat(),
                            "split": record.split, "fields": sorted(record.values), "record_hash": _hash(dict(record.values)),
                            "rights": record.rights.to_public_dict(), "rights_hash": record.rights.digest})
        body = {"scope": scope.to_dict(), "scope_hash": _hash(scope.to_dict()), "members": members,
                "payload_hash": hashlib.sha256(payload).hexdigest(), "payload_bytes": len(payload), "transform": transform}
        identity = "batch:" + _hash(body)
        with self._thread_lock, self._lock, self._db() as db:
            self._put(db, identity, "batch", body)
        return identity

    def manifest(self, batch_id: str) -> dict[str, Any]:
        """Return immutable membership/rights/hash evidence, not a remote handle."""
        with self._thread_lock, self._lock, self._db() as db:
            return self._get(db, batch_id, "batch")

    def revoke(self, grant_id: str, *, actor: str) -> None:
        """Block new sends; this is not remote stop, deletion or weight erasure."""
        text(actor, "actor")
        with self._thread_lock, self._lock, self._db() as db:
            self._get(db, grant_id, "grant")
            self._event(db, grant_id, {"kind": "revoked", "actor": actor, "at": self.clock().isoformat()})

    def lifecycle(self, grant_id: str, *, operation: str, state: str, evidence_ref: str) -> None:
        """Record independently observed remote management, never simulate cancellation."""
        allowed = {"remote_cancellation": {"requested", "confirmed", "unknown"},
                   "deletion": {"requested", "confirmed", "partial", "unsupported", "unknown"}}
        if operation not in allowed or state not in allowed[operation]:
            raise ValueError("invalid independent lifecycle state")
        text(evidence_ref, "lifecycle evidence")
        with self._thread_lock, self._lock, self._db() as db:
            self._get(db, grant_id, "grant")
            self._event(db, grant_id, {"kind": operation, "state": state, "evidence_ref": evidence_ref})

    def status(self, grant_id: str) -> dict[str, Any]:
        """Expose opt-out and remote uncertainty separately for every caller."""
        with self._thread_lock, self._lock, self._db() as db:
            grant = self._get(db, grant_id, "grant")
            events = self._events(db, grant_id)
            active = datetime.fromisoformat(grant["valid_from"]) <= utc(self.clock()) < datetime.fromisoformat(grant["valid_until"])
            result = {"grant": grant, "egress_blocked": not active or any(e["kind"] == "revoked" for e in events),
                      "remote_cancellation": "not-requested", "deletion": "not-requested",
                      "weight_unlearning": "unavailable"}
            for event in events:
                if event["kind"] in {"remote_cancellation", "deletion"}:
                    result[event["kind"]] = event["state"]
            return result

    def receipt(self, attempt_id: str) -> dict[str, Any]:
        """Read exact durable send evidence, even after a lost response/restart."""
        with self._thread_lock, self._lock, self._db() as db:
            return self._get(db, attempt_id, "attempt")

    def dispatch(self, *, grant_id: str, batch_id: str, recipient: Recipient,
                 current_recipient: Callable[[], Recipient], purpose: str, operation: str, payload: bytes,
                 attempt_id: str, request_id: str, run_id: str, trial_id: str, reservation: UsageAmounts,
                 tariff: TariffSnapshot, controls: Mapping[str, str], controls_evidence: str,
                 send: Callable[[], Any], rights_check: Callable[[dict[str, Any]], bool] | None = None,
                 conservative_cost_ceiling: int | None = None) -> Any:
        """Revalidate and commit immediately before exact I/O; never issue reusable permits.

        bounds cover hidden tokens, compute/storage and paid retries, not merely
        visible output. Unknown/observational controls refuse. The qualified core
        adapter supplies current rights and identity, never the model or payload.
        """
        text(controls_evidence, "controls evidence")
        with self._thread_lock, self._lock:
            with self._db() as db:
                grant, batch = self._get(db, grant_id, "grant"), self._get(db, batch_id, "batch")
                events = self._events(db, grant_id)
                if any(event["kind"] == "revoked" for event in events):
                    raise LearningRefused("learning grant revoked")
                now = utc(self.clock())
                if not datetime.fromisoformat(grant["valid_from"]) <= now < datetime.fromisoformat(grant["valid_until"]):
                    raise LearningRefused("learning grant expired or not active")
                if (grant["recipient"] != recipient.to_dict() or current_recipient() != recipient
                    or grant["scope_hash"] != batch["scope_hash"] or grant["purpose"] != purpose
                    or operation not in grant["operations"] or recipient.method != operation):
                    raise LearningRefused("learning scope, purpose or recipient changed")
                if type(payload) is not bytes or hashlib.sha256(payload).hexdigest() != batch["payload_hash"]:
                    raise LearningRefused("learning payload changed")
                if rights_check is None or rights_check(batch) is not True:
                    raise LearningRefused("current learning rights not established")
                if set(controls) != set(USAGE_DIMENSIONS) or any(
                    controls[key] not in {"hard-local", "hard-provider", "not-applicable"}
                    or controls[key] == "not-applicable" and getattr(reservation, key) != 0
                    for key in USAGE_DIMENSIONS
                ):
                    raise LearningRefused("required hard learning controls unavailable")
                if reservation.bytes < len(payload) or reservation.requests != 1 or reservation.concurrency != 1:
                    raise LearningRefused("learning reservation does not cover send")
                previous = [self._get(db, identity, "attempt") for (identity,) in
                            db.execute("SELECT id FROM documents WHERE kind='attempt'")]
                if any(item["attempt_id"] == attempt_id for item in previous):
                    raise LearningRefused("learning attempt already dispatched or unknown")
                family = [item for item in previous if item["budget_key"] == grant["budget_key"]]
                trials = {item["trial_id"] for item in family} | {trial_id}
                totals = {key: sum(item["reservation"][key] for item in family) for key in USAGE_DIMENSIONS}
                totals["concurrency"] = sum(self.usage.get_attempt(item["attempt_id"]).charged.concurrency for item in family)
                if (sum(item["rows"] for item in family) + len(batch["members"]) > grant["max_rows"]
                    or len(trials) > grant["max_trials"] or any(
                        totals[key] + getattr(reservation, key) > grant["limits"][key]
                        for key in USAGE_DIMENSIONS)):
                    raise LearningRefused("cumulative learning limit exhausted")
                # Shared provider quota remains authoritative; no second spend ledger.
                self.usage.prepare(attempt_id=attempt_id, connection=recipient.connection,
                                   connection_revision=recipient.connection_revision, request_id=request_id, run_id=run_id,
                                   model=recipient.model, model_revision=recipient.model_revision, tariff=tariff,
                                   reservation=reservation, conservative_cost_ceiling=conservative_cost_ceiling)
                self.usage.mark_invoked(attempt_id)
                self._put(db, attempt_id, "attempt", {"attempt_id": attempt_id, "grant_id": grant_id,
                    "grant_revision": grant["revision"], "revocation_epoch": len(events), "batch_id": batch_id,
                    "batch_hash": _hash(batch), "payload_hash": batch["payload_hash"], "recipient": recipient.to_dict(),
                    "purpose": purpose, "operation": operation, "request_id": request_id, "run_id": run_id,
                    "trial_id": trial_id, "rows": len(batch["members"]), "reservation": reservation.to_dict(),
                    "budget_key": grant["budget_key"], "controls": dict(controls), "controls_evidence": controls_evidence,
                    "at": now.isoformat(), "outcome": "invoked-or-unknown"})
            # The durable receipt is committed before the gateway starts I/O, under
            # the same revocation fence. Crash/retry cannot create a second start.
            try:
                return send()
            finally:
                self.usage.mark_unknown(attempt_id)
