"""Crash-durable, connection-scoped provider-attempt admission.

Prepare and invocation are separate durable commits. Only a successful first
``mark_invoked`` return permits one external attempt. Lost responses, cancelled
streams and abandoned INVOKED rows retain their reservation; they never replay.
This neutral authority does not authenticate operators, select providers or run
transports. The app-owned caller supplies verified configuration and receipts.
"""

from __future__ import annotations

import json
import os
import sqlite3
import threading
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from uuid import UUID, uuid4

from .db import open_sqlite
from .owner_file_lock import OwnerSafeFileLock
from .secure_file import HeldOwnerDirectory, harden_directory, validate_owner_owned_regular_file
from .service_connections import ServiceConnectionRef
from .service_usage_contracts import (
    USAGE_DIMENSIONS as USAGE_DIMENSIONS,
    BudgetPolicy as BudgetPolicy,
    ExchangeRate as ExchangeRate,
    TariffSnapshot as TariffSnapshot,
    UnitPrice as UnitPrice,
    UsageAmounts as UsageAmounts,
    canonical,
    integer,
    text,
    utc,
)

_OUTSTANDING = {"PREPARED", "INVOKED", "UNKNOWN"}
_SCHEMA = (
    "CREATE TABLE metadata (identity TEXT NOT NULL)",
    "CREATE TABLE budgets (connection_id TEXT PRIMARY KEY, revision INTEGER NOT NULL, policy TEXT NOT NULL)",
    (
        "CREATE TABLE budget_history (connection_id TEXT NOT NULL, revision INTEGER NOT NULL, policy TEXT NOT NULL, "
        "PRIMARY KEY(connection_id, revision))"
    ),
    "CREATE TABLE tariffs (digest TEXT PRIMARY KEY, snapshot TEXT NOT NULL)",
    (
        "CREATE TABLE attempts (attempt_id TEXT PRIMARY KEY, connection_id TEXT NOT NULL, identity TEXT NOT NULL, "
        "state TEXT NOT NULL, charged TEXT NOT NULL, created_at TEXT NOT NULL, updated_at TEXT NOT NULL, "
        "budget_revision INTEGER NOT NULL, evidence TEXT NOT NULL)"
    ),
    "CREATE INDEX attempts_connection ON attempts(connection_id)",
)


class UsageConflict(RuntimeError):
    """A duplicate identity, stale revision or invalid state transition."""


class BudgetExceeded(RuntimeError):
    """The attempt would exceed a configured ceiling."""


class UsageUnavailable(RuntimeError):
    """Durable accounting is unavailable; provider I/O must fail closed."""


def _ref(value: dict[str, str]) -> ServiceConnectionRef:
    return ServiceConnectionRef(value["provider_id"], UUID(value["connection_id"]))


@dataclass(frozen=True, slots=True)
class AttemptRecord:
    """Detached immutable receipt. It is evidence, never invocation authority."""

    attempt_id: str
    connection: ServiceConnectionRef
    connection_revision: str
    request_id: str
    run_id: str
    model: str
    model_revision: str
    tariff: TariffSnapshot
    reservation: UsageAmounts
    charged: UsageAmounts
    state: str
    created_at: datetime
    updated_at: datetime
    budget_revision: int
    evidence: str

    def to_dict(self) -> dict[str, Any]:
        """Return independent JSON-ready values for routes and reports."""
        return {
            "attempt_id": self.attempt_id,
            "connection": self.connection.to_dict(),
            "connection_revision": self.connection_revision,
            "request_id": self.request_id,
            "run_id": self.run_id,
            "model": self.model,
            "model_revision": self.model_revision,
            "tariff": self.tariff.to_dict(),
            "tariff_digest": self.tariff.digest,
            "reservation": self.reservation.to_dict(),
            "charged": self.charged.to_dict(),
            "state": self.state,
            "created_at": self.created_at.isoformat(),
            "updated_at": self.updated_at.isoformat(),
            "budget_revision": self.budget_revision,
            "evidence": self.evidence,
        }


class ServiceUsageLedger:
    """Dedicated owner-only SQLite directory; safe across threads and processes.

    Each operation opens FULL-durability SQLite beneath a held owner directory
    and persistent cross-process lock. Reopening never resets usage or converts
    INVOKED into permission to retry. A supervisor may mark specific abandoned
    attempts UNKNOWN; opening another process must not mutate active attempts.
    """

    def __init__(self, root: Path, *, clock: Callable[[], datetime] | None = None) -> None:
        self._root = Path(root).absolute()
        self._clock = clock or (lambda: datetime.now(UTC))
        self._thread_lock = threading.RLock()
        self._pid = os.getpid()
        self._closed = False
        try:
            self._root.mkdir(mode=0o700)
        except FileExistsError:
            pass
        else:
            harden_directory(self._root)
        self._directory = HeldOwnerDirectory(self._root).__enter__()
        self._lock = OwnerSafeFileLock(str(self._root / "ledger.lock"), timeout=10)
        self._path = self._root / "usage.sqlite"
        try:
            with self._lock:
                exists = self._directory.exists("usage.sqlite")
                if not exists:
                    if self._directory.exists("authority.json"):
                        raise UsageUnavailable("usage database is missing")
                    self._directory.create_empty_hardened_member("usage.sqlite")
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
                        self._directory.write_text("authority.json", canonical({"identity": identity}))
                    if db.execute("PRAGMA user_version").fetchone()[0] != 1:
                        raise UsageUnavailable("unsupported or incomplete usage database")
                    marker = json.loads(self._directory.read_text("authority.json"))
                    if db.execute("SELECT identity FROM metadata").fetchall() != [(marker["identity"],)]:
                        raise UsageUnavailable("usage database identity mismatch")
                info = validate_owner_owned_regular_file(self._path, require_hardened=True)
                self._file_identity = (info.st_dev, info.st_ino)
        except BaseException:
            self._directory.__exit__()
            raise

    def _validate_files(self) -> None:
        self._directory.revalidate()
        for suffix in ("", "-wal", "-shm", "-journal"):
            name = "usage.sqlite" + suffix
            if self._directory.exists(name):
                info = validate_owner_owned_regular_file(self._root / name, require_hardened=True)
                if not suffix and hasattr(self, "_file_identity"):
                    if (info.st_dev, info.st_ino) != self._file_identity:
                        raise UsageUnavailable("usage database was replaced")
            elif not suffix:
                raise UsageUnavailable("usage database is missing")

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
        if os.getpid() != self._pid:
            raise UsageUnavailable("usage ledger inherited across fork")
        with self._thread_lock:
            if self._closed or os.getpid() != self._pid:
                raise UsageUnavailable("usage ledger is closed or inherited across fork")
            with self._lock:
                self._validate_files()
                with self._database() as db:
                    db.execute("BEGIN IMMEDIATE")
                    try:
                        yield db
                        self._validate_files()
                        db.commit()
                    except BaseException:
                        db.rollback()
                        raise

    def close(self) -> None:
        """Release retained directory handles without refunding attempts."""
        if os.getpid() != self._pid:
            raise UsageUnavailable("usage ledger inherited across fork")
        with self._thread_lock:
            if not self._closed:
                self._closed = True
                self._directory.__exit__()

    def __enter__(self) -> ServiceUsageLedger:
        return self

    def __exit__(self, *args: object) -> None:
        self.close()

    def configure_budget(self, policy: BudgetPolicy, *, expected_revision: int) -> int:
        """CAS the current policy; keep old policy snapshots and all usage."""
        if type(policy) is not BudgetPolicy:
            raise ValueError("exact BudgetPolicy required")
        integer(expected_revision, "expected_revision")
        key = str(policy.connection.connection_id)
        with self._transaction() as db:
            previous = db.execute("SELECT revision, policy FROM budgets WHERE connection_id=?", (key,)).fetchone()
            revision = previous[0] if previous else 0
            if revision != expected_revision:
                raise UsageConflict("budget revision changed")
            if previous:
                old = json.loads(previous[1])
                if old["connection"] != policy.connection.to_dict() or old["currency"] != policy.currency:
                    raise UsageConflict("budget connection and currency are immutable")
                bounds_changed = (old["window_start"], old["window_end"]) != (
                    policy.window_start.isoformat(),
                    policy.window_end.isoformat(),
                )
                old_end = datetime.fromisoformat(old["window_end"])
                if bounds_changed and (utc(self._clock()) < old_end or policy.window_start < old_end):
                    raise UsageConflict("only an expired budget period may roll forward")
            revision = integer(revision + 1, "budget revision", minimum=1)
            encoded = canonical(policy.to_dict())
            db.execute("INSERT INTO budget_history VALUES (?, ?, ?)", (key, revision, encoded))
            db.execute(
                "INSERT INTO budgets VALUES (?, ?, ?) ON CONFLICT(connection_id) DO UPDATE SET "
                "revision=excluded.revision, policy=excluded.policy",
                (key, revision, encoded),
            )
            return revision

    @staticmethod
    def _budget(db: sqlite3.Connection, connection: ServiceConnectionRef, now: datetime) -> tuple[int, dict[str, Any]]:
        row = db.execute(
            "SELECT revision, policy FROM budgets WHERE connection_id=?", (str(connection.connection_id),)
        ).fetchone()
        if row is None:
            raise UsageUnavailable("connection has no budget policy")
        value = json.loads(row[1])
        if value["connection"] != connection.to_dict():
            raise UsageConflict("budget connection identity mismatch")
        if not datetime.fromisoformat(value["window_start"]) <= now < datetime.fromisoformat(value["window_end"]):
            raise UsageUnavailable("budget period is not current")
        return row[0], value

    @staticmethod
    def _check_budget(
        db: sqlite3.Connection, connection: ServiceConnectionRef, policy: dict[str, Any], extra: UsageAmounts
    ) -> None:
        totals = extra.to_dict()
        for state, charged, created in db.execute(
            "SELECT state, charged, created_at FROM attempts WHERE connection_id=?",
            (str(connection.connection_id),),
        ):
            outstanding = state in _OUTSTANDING
            in_window = policy["window_start"] <= created < policy["window_end"]
            values = json.loads(charged)
            for dimension in USAGE_DIMENSIONS:
                if (
                    dimension == "storage_bytes"
                    or (dimension == "concurrency" and outstanding)
                    or (dimension != "concurrency" and (outstanding or in_window))
                ):
                    totals[dimension] += values[dimension]
        if any(totals[dimension] > limit for dimension, limit in policy["limits"].items()):
            raise BudgetExceeded("service usage ceiling exceeded")

    def prepare(
        self,
        *,
        attempt_id: str,
        connection: ServiceConnectionRef,
        connection_revision: str,
        request_id: str,
        run_id: str,
        model: str,
        model_revision: str,
        tariff: TariffSnapshot,
        reservation: UsageAmounts,
        conservative_cost_ceiling: int | None = None,
    ) -> AttemptRecord:
        """Atomically reserve one attempt; an identical duplicate never invokes.

        Upper bounds must include every billable unit, hidden reasoning and
        retries separately. Unknown prices require an explicit positive ceiling
        equal to the reserved price dimension. This does not infer entitlement.
        """
        for name, value in (
            ("attempt_id", attempt_id),
            ("connection_revision", connection_revision),
            ("request_id", request_id),
            ("run_id", run_id),
            ("model", model),
            ("model_revision", model_revision),
        ):
            text(value, name)
        if type(connection) is not ServiceConnectionRef or type(tariff) is not TariffSnapshot:
            raise ValueError("exact connection and tariff required")
        if type(reservation) is not UsageAmounts or reservation.requests != 1 or reservation.concurrency != 1:
            raise ValueError("one request and concurrency slot required per attempt")
        if (tariff.provider_id, tariff.model, tariff.model_revision) != (connection.provider_id, model, model_revision):
            raise ValueError("tariff provider/model identity mismatch")
        if conservative_cost_ceiling is not None:
            integer(conservative_cost_ceiling, "conservative_cost_ceiling", minimum=1)
        reserved_cost = getattr(reservation, tariff.price_dimension)
        if tariff.prices is None:
            if conservative_cost_ceiling is None or reserved_cost != conservative_cost_ceiling:
                raise ValueError("unknown prices require the explicit reserved conservative ceiling")
        elif reserved_cost < tariff.quote(reservation):
            raise ValueError("reservation is below the tariff quote")
        identity = canonical(
            {
                "attempt_id": attempt_id,
                "connection": connection.to_dict(),
                "connection_revision": connection_revision,
                "request_id": request_id,
                "run_id": run_id,
                "model": model,
                "model_revision": model_revision,
                "tariff_digest": tariff.digest,
                "reservation": reservation.to_dict(),
                "conservative_cost_ceiling": conservative_cost_ceiling,
            }
        )
        with self._transaction() as db:
            previous = db.execute("SELECT identity FROM attempts WHERE attempt_id=?", (attempt_id,)).fetchone()
            if previous:
                if previous[0] != identity:
                    raise UsageConflict("attempt identity conflicts")
                return self._record(db, attempt_id)
            now = utc(self._clock())
            if not tariff.effective_from <= now < tariff.effective_until:
                raise ValueError("tariff is not effective")
            revision, policy = self._budget(db, connection, now)
            if policy["currency"] != tariff.currency:
                raise ValueError("budget currency does not match tariff")
            self._check_budget(db, connection, policy, reservation)
            db.execute("INSERT OR IGNORE INTO tariffs VALUES (?, ?)", (tariff.digest, canonical(tariff.to_dict())))
            db.execute(
                "INSERT INTO attempts VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    attempt_id,
                    str(connection.connection_id),
                    identity,
                    "PREPARED",
                    canonical(reservation.to_dict()),
                    now.isoformat(),
                    now.isoformat(),
                    revision,
                    "",
                ),
            )
            return self._record(db, attempt_id)

    @staticmethod
    def _record(db: sqlite3.Connection, attempt_id: str) -> AttemptRecord:
        row = db.execute(
            "SELECT identity, state, charged, created_at, updated_at, budget_revision, evidence "
            "FROM attempts WHERE attempt_id=?",
            (attempt_id,),
        ).fetchone()
        if row is None:
            raise KeyError(attempt_id)
        identity = json.loads(row[0])
        tariff_row = db.execute("SELECT snapshot FROM tariffs WHERE digest=?", (identity["tariff_digest"],)).fetchone()
        tariff = TariffSnapshot.from_dict(json.loads(tariff_row[0]))
        if tariff.digest != identity["tariff_digest"]:
            raise UsageUnavailable("tariff digest mismatch")
        return AttemptRecord(
            attempt_id=attempt_id,
            connection=_ref(identity["connection"]),
            connection_revision=identity["connection_revision"],
            request_id=identity["request_id"],
            run_id=identity["run_id"],
            model=identity["model"],
            model_revision=identity["model_revision"],
            tariff=tariff,
            reservation=UsageAmounts(**identity["reservation"]),
            charged=UsageAmounts(**json.loads(row[2])),
            state=row[1],
            created_at=datetime.fromisoformat(row[3]),
            updated_at=datetime.fromisoformat(row[4]),
            budget_revision=row[5],
            evidence=row[6],
        )

    def get_attempt(self, attempt_id: str) -> AttemptRecord:
        """Read one detached immutable attempt receipt."""
        text(attempt_id, "attempt_id")
        with self._transaction() as db:
            return self._record(db, attempt_id)

    def list_attempts(self) -> tuple[AttemptRecord, ...]:
        """Read detached receipts ordered by attempt ID."""
        with self._transaction() as db:
            return tuple(
                self._record(db, row[0]) for row in db.execute("SELECT attempt_id FROM attempts ORDER BY attempt_id")
            )

    def _update(
        self, db: sqlite3.Connection, attempt_id: str, state: str, charged: UsageAmounts, evidence: str = ""
    ) -> AttemptRecord:
        db.execute(
            "UPDATE attempts SET state=?, charged=?, updated_at=?, evidence=? WHERE attempt_id=?",
            (state, canonical(charged.to_dict()), utc(self._clock()).isoformat(), evidence, attempt_id),
        )
        return self._record(db, attempt_id)

    def mark_invoked(self, attempt_id: str) -> AttemptRecord:
        """Commit invocation once, immediately before provider I/O; never retry."""
        with self._transaction() as db:
            record = self._record(db, attempt_id)
            if record.state != "PREPARED":
                raise UsageConflict("attempt cannot be invoked again")
            now = utc(self._clock())
            _, policy = self._budget(db, record.connection, now)
            if not (
                datetime.fromisoformat(policy["window_start"])
                <= record.created_at
                < datetime.fromisoformat(policy["window_end"])
            ):
                raise UsageConflict("attempt belongs to an earlier budget period; cancel and prepare a new attempt")
            if not record.tariff.effective_from <= now < record.tariff.effective_until:
                raise UsageConflict("attempt tariff is no longer effective; cancel and prepare a new attempt")
            self._check_budget(db, record.connection, policy, UsageAmounts())
            return self._update(db, attempt_id, "INVOKED", record.charged)

    def cancel_prepared(self, attempt_id: str) -> AttemptRecord:
        """Release only a durable reservation proved never invoked."""
        with self._transaction() as db:
            record = self._record(db, attempt_id)
            if record.state == "CANCELLED":
                return record
            if record.state != "PREPARED":
                raise UsageConflict("invoked reservations cannot be cancelled")
            return self._update(db, attempt_id, "CANCELLED", UsageAmounts())

    def mark_unknown(self, attempt_id: str) -> AttemptRecord:
        """Keep every reserved unit after an uncertain externally invoked outcome."""
        with self._transaction() as db:
            record = self._record(db, attempt_id)
            if record.state == "UNKNOWN":
                return record
            if record.state != "INVOKED":
                raise UsageConflict("only invoked attempts become unknown")
            return self._update(db, attempt_id, "UNKNOWN", record.charged)

    def settle(self, attempt_id: str, observed: UsageAmounts) -> AttemptRecord:
        """Persist complete observed usage; missing usage must use mark_unknown."""
        return self._settle(attempt_id, observed, reconciliation=False, evidence="")

    def reconcile(self, attempt_id: str, observed: UsageAmounts, *, evidence: str) -> AttemptRecord:
        """Resolve an UNKNOWN/orphan INVOKED outcome using explicit receipt evidence."""
        text(evidence, "reconciliation evidence")
        return self._settle(attempt_id, observed, reconciliation=True, evidence=evidence)

    def _settle(self, attempt_id: str, observed: UsageAmounts, *, reconciliation: bool, evidence: str) -> AttemptRecord:
        if type(observed) is not UsageAmounts or observed.requests != 1 or observed.concurrency != 0:
            raise ValueError("complete observed usage must count one request and release its concurrency slot")
        with self._transaction() as db:
            record = self._record(db, attempt_id)
            if record.state == "SETTLED":
                if record.charged != observed or record.evidence != evidence:
                    raise UsageConflict("settlement conflicts with recorded usage")
                return record
            allowed = {"INVOKED", "UNKNOWN"} if reconciliation else {"INVOKED"}
            if record.state not in allowed:
                raise UsageConflict("attempt cannot be settled in this state")
            # Complete receipt normalisation belongs to the trusted transport
            # adapter. Repricing observations here could erase an overage on
            # arithmetic overflow or reject a genuine provider billing discount.
            # The immutable admission tariff remains attached for reconciliation.
            return self._update(db, attempt_id, "SETTLED", observed, evidence)
