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
from uuid import UUID, uuid4, uuid5

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

    def __init__(self, root: Path, *, clock: Callable[[], datetime] | None = None,
                 failure_sink: Callable[[str], None] | None = None) -> None:
        self._failure_sink = failure_sink
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
                    version = db.execute("PRAGMA user_version").fetchone()[0]
                    if version not in {1, 2}:
                        raise UsageUnavailable("unsupported or incomplete usage database")
                    marker = json.loads(self._directory.read_text("authority.json"))
                    if db.execute("SELECT identity FROM metadata").fetchall() != [(marker["identity"],)]:
                        raise UsageUnavailable("usage database identity mismatch")
                    if version == 1:
                        # One transactional migration, never recreate a missing
                        # v2 authority table after it has contained receipts.
                        db.execute("BEGIN IMMEDIATE")
                        db.execute(
                            "CREATE TABLE task_controls (key TEXT PRIMARY KEY, "
                            "revision INTEGER NOT NULL, payload TEXT NOT NULL)"
                        )
                        db.execute(
                            "CREATE TABLE task_receipts (request_id TEXT PRIMARY KEY, "
                            "actor TEXT NOT NULL, digest TEXT NOT NULL, payload TEXT NOT NULL)"
                        )
                        db.execute(
                            "CREATE TABLE task_control_history (key TEXT NOT NULL, "
                            "revision INTEGER NOT NULL, payload TEXT NOT NULL, PRIMARY KEY(key,revision))"
                        )
                        db.execute(
                            "CREATE TABLE quota_members (connection_id TEXT PRIMARY KEY, group_id TEXT NOT NULL)"
                        )
                        db.execute("PRAGMA user_version = 2")
                        db.commit()
                    expected = {
                        "metadata",
                        "budgets",
                        "budget_history",
                        "tariffs",
                        "attempts",
                        "task_controls",
                        "task_receipts",
                        "task_control_history",
                        "quota_members",
                    }
                    present = {row[0] for row in db.execute("SELECT name FROM sqlite_master WHERE type='table'")}
                    if not expected <= present:
                        raise UsageUnavailable("usage authority table is missing")
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
        """CAS the explicit connection budget without discarding usage."""
        with self._transaction() as db:
            return self._configure_budget(db, policy, expected_revision=expected_revision)

    def _configure_budget(self, db: sqlite3.Connection, policy: BudgetPolicy, *, expected_revision: int) -> int:
        """CAS the current policy; keep old policy snapshots and all usage."""
        if type(policy) is not BudgetPolicy:
            raise ValueError("exact BudgetPolicy required")
        integer(expected_revision, "expected_revision")
        key = str(policy.connection.connection_id)
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

    def control(self, key: str) -> tuple[int, dict[str, Any] | None]:
        """Read a detached task-policy snapshot from the accounting authority."""
        text(key, "control key")
        with self._transaction() as db:
            row = db.execute("SELECT revision,payload FROM task_controls WHERE key=?", (key,)).fetchone()
            return (row[0], json.loads(row[1])) if row else (0, None)

    def check_available(self) -> None:
        """Require retained control custody without constructing or repairing it."""
        with self._transaction() as db:
            db.execute("SELECT key,revision,payload FROM task_controls LIMIT 0")
            db.execute("SELECT key,revision,payload FROM task_control_history LIMIT 0")

    def diagnostic_observation(self) -> dict[str, Any]:
        """Bounded passive counts from this exact existing usage owner.

        Pending receipts may be abandoned; they do not measure active compute.
        No prompt, identity, tariff source, destination or configuration escapes.
        """
        with self._transaction() as db:
            receipts = db.execute("SELECT json_extract(payload,'$.outcome') FROM task_receipts ORDER BY rowid DESC LIMIT 1001").fetchall()
            attempts = db.execute("SELECT state FROM attempts ORDER BY rowid DESC LIMIT 1001").fetchall()
        tasks = dict.fromkeys(("completed", "failed", "refused", "unknown"), 0)
        states = dict.fromkeys(("PREPARED", "INVOKED", "UNKNOWN", "SETTLED", "CANCELLED", "other"), 0)
        for (value,) in receipts[:1000]:
            tasks[value if value in tasks else "unknown"] += 1
        for (value,) in attempts[:1000]:
            states[value if value in states else "other"] += 1
        return {"status": "available", "source": "service_usage_ledger", "observed_at": datetime.now(UTC).isoformat(),
                "freshness": "observed", "measurement": "retained_receipt_counts", "coverage": "latest_1000_per_kind",
                "has_more": len(receipts) > 1000 or len(attempts) > 1000,
                "tasks": tasks, "attempts": states, "active": None, "latency_ms": None,
                "capacity": None, "reason": "receipts_do_not_measure_serving_capacity_or_active_compute"}

    def control_snapshot(self, key: str) -> tuple[int, dict[str, Any] | None]:
        """Exact current/history read; lost established history is not unissued.

        No constructors, migrations or repair writes belong in a readback. Keep
        this stronger receipt contract separate from ordinary policy lookups.
        """
        text(key, "control key")
        with self._transaction() as db:
            row = db.execute("SELECT revision,payload FROM task_controls WHERE key=?", (key,)).fetchone()
            history = db.execute("SELECT revision,payload FROM task_control_history WHERE key=? "
                                 "ORDER BY revision", (key,)).fetchall()
            if row is None and not history:
                return 0, None
            if row is None or not history or type(row[0]) is not int or row != history[-1]:
                raise UsageUnavailable("control history unavailable")
            for expected, (revision, encoded) in enumerate(history, start=1):
                if type(revision) is not int or revision != expected:
                    raise UsageUnavailable("control history unavailable")
                try:
                    payload = json.loads(encoded)
                    if type(payload) is not dict or canonical(payload) != encoded:
                        raise ValueError("non-canonical control payload")
                except (ValueError, TypeError) as exc:
                    raise UsageUnavailable("control payload unavailable") from exc
            return row[0], json.loads(row[1])

    def configure_control(
        self, key: str, payload: dict[str, Any], *, expected_revision: int,
        expected_controls: dict[str, dict[str, Any]] | None = None,
    ) -> int:
        """CAS one policy and its exact dependency payloads in the same transaction."""
        with self._transaction() as db:
            for dependency, expected in (expected_controls or {}).items():
                row = db.execute("SELECT payload FROM task_controls WHERE key=?", (dependency,)).fetchone()
                if row is None or row[0] != canonical(expected):
                    raise UsageConflict("dependent control changed")
            return self._configure_control(db, key, payload, expected_revision=expected_revision)

    def _configure_control(
        self, db: sqlite3.Connection, key: str, payload: dict[str, Any], *, expected_revision: int
    ) -> int:
        """CAS validated core policy; this method never establishes entitlement."""
        text(key, "control key")
        integer(expected_revision, "control revision")
        encoded = canonical(payload)
        row = db.execute("SELECT revision,payload FROM task_controls WHERE key=?", (key,)).fetchone()
        revision = row[0] if row else 0
        if revision != expected_revision:
            raise UsageConflict("control revision changed")
        if key.startswith("quota:") and row:
            previous = json.loads(row[1])
            if previous["currency"] != payload["currency"]:
                raise UsageConflict("quota currency is immutable")
            if (previous["window_start"], previous["window_end"]) != (payload["window_start"], payload["window_end"]):
                old_end = datetime.fromisoformat(previous["window_end"])
                if utc(self._clock()) < old_end or datetime.fromisoformat(payload["window_start"]) < old_end:
                    raise UsageConflict("quota period cannot reset existing usage")
        if key.startswith("admission:"):
            connection_id = key.removeprefix("admission:")
            group = payload["quota_group"]
            member = db.execute("SELECT group_id FROM quota_members WHERE connection_id=?", (connection_id,)).fetchone()
            if member and member[0] != group:
                raise UsageConflict("quota membership cannot discard accumulated usage")
            if db.execute("SELECT 1 FROM task_controls WHERE key=?", ("quota:" + group,)).fetchone() is None:
                raise UsageUnavailable("shared quota is not configured")
            db.execute("INSERT OR IGNORE INTO quota_members VALUES (?,?)", (connection_id, group))
        revision += 1
        db.execute("INSERT INTO task_control_history VALUES (?,?,?)", (key, revision, encoded))
        db.execute(
            "INSERT INTO task_controls VALUES (?,?,?) ON CONFLICT(key) DO UPDATE SET "
            "revision=excluded.revision,payload=excluded.payload",
            (key, revision, encoded),
        )
        return revision

    def configure_admission(
        self, key: str, payload: dict[str, Any], budget: BudgetPolicy, *, expected_revision: int
    ) -> tuple[int, dict[str, Any]]:
        """Commit policy, quota membership and its budget in one transaction."""
        with self._transaction() as db:
            row = db.execute(
                "SELECT revision FROM budgets WHERE connection_id=?", (str(budget.connection.connection_id),)
            ).fetchone()
            budget_revision = self._configure_budget(db, budget, expected_revision=row[0] if row else 0)
            value = {**payload, "budget_revision": budget_revision}
            revision = self._configure_control(db, key, value, expected_revision=expected_revision)
            return revision, value

    def begin_task(self, request_id: str, actor: str, digest: str) -> tuple[bool, dict[str, Any]]:
        """Claim a durable task identity once; crash recovery never resends it."""
        for value in (request_id, actor, digest):
            text(value, "task identity")
        with self._transaction() as db:
            row = db.execute(
                "SELECT actor,digest,payload FROM task_receipts WHERE request_id=?", (request_id,)
            ).fetchone()
            if row:
                if row[:2] != (actor, digest):
                    raise UsageConflict("task identity conflict")
                return False, json.loads(row[2])
            receipt = {"request_id": request_id, "outcome": "pending", "code": "outcome_unknown", "attempts": []}
            db.execute("INSERT INTO task_receipts VALUES (?,?,?,?)", (request_id, actor, digest, canonical(receipt)))
            return True, receipt

    def finish_task(self, request_id: str, receipt: dict[str, Any]) -> None:
        """Persist redacted context/selection evidence, never prompt or secrets."""
        with self._transaction() as db:
            changed = db.execute(
                "UPDATE task_receipts SET payload=? WHERE request_id=?", (canonical(receipt), request_id)
            ).rowcount
            if changed != 1:
                raise UsageConflict("task was not claimed")
            # The durable owner identity plus the claimed key, NOT receipt text,
            # names this observation consistently across reopen/repeated finish.
            reference = str(uuid5(UUID(db.execute("SELECT identity FROM metadata").fetchone()[0]),
                                  "task:" + request_id))
        if receipt.get("outcome") == "failed" and self._failure_sink is not None:
            self._failure_sink(reference)

    def task_receipt(self, request_id: str, actor: str) -> dict[str, Any]:
        """Read only the exact requesting principal's task receipt."""
        with self._transaction() as db:
            row = db.execute(
                "SELECT payload FROM task_receipts WHERE request_id=? AND actor=?", (request_id, actor)
            ).fetchone()
            if row is None:
                raise KeyError(request_id)
            return json.loads(row[0])

    def budget(self, connection: ServiceConnectionRef) -> tuple[int, dict[str, Any]]:
        """Read the current explicit budget; absence and expiry are not unlimited."""
        with self._transaction() as db:
            return self._budget(db, connection, utc(self._clock()))

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

    def check_capacity(self, connection: ServiceConnectionRef, reservation: UsageAmounts) -> None:
        """Preflight both connection and shared quota before even router egress."""
        with self._transaction() as db:
            _, policy = self._budget(db, connection, utc(self._clock()))
            self._check_budget(db, connection, policy, reservation)

    def check_sequence_capacity(
        self, first: tuple[ServiceConnectionRef, UsageAmounts], second: tuple[ServiceConnectionRef, UsageAmounts]
    ) -> None:
        """Check router plus task spend atomically; their concurrency is sequential."""
        with self._transaction() as db:
            for connection, amount in (first, second):
                _, policy = self._budget(db, connection, utc(self._clock()))
                self._check_budget(db, connection, policy, amount)
            combined = UsageAmounts(
                **{
                    dimension: max(getattr(first[1], dimension), getattr(second[1], dimension))
                    if dimension == "concurrency"
                    else getattr(first[1], dimension) + getattr(second[1], dimension)
                    for dimension in USAGE_DIMENSIONS
                }
            )
            if first[0] == second[0]:
                _, policy = self._budget(db, first[0], utc(self._clock()))
                self._check_budget(db, first[0], policy, combined)
                return
            groups = [
                db.execute(
                    "SELECT group_id FROM quota_members WHERE connection_id=?", (str(pair[0].connection_id),)
                ).fetchone()
                for pair in (first, second)
            ]
            if groups[0] is not None and groups[0] == groups[1]:
                group_id = groups[0][0]
                row = db.execute("SELECT payload FROM task_controls WHERE key=?", ("quota:" + group_id,)).fetchone()
                if row is None:
                    raise UsageUnavailable("shared quota is missing")
                rows = db.execute(
                    "SELECT a.state,a.charged,a.created_at FROM attempts a JOIN quota_members m "
                    "ON a.connection_id=m.connection_id WHERE m.group_id=?",
                    (group_id,),
                ).fetchall()
                self._check_rows(rows, json.loads(row[0]), combined)

    def _check_budget(
        self, db: sqlite3.Connection, connection: ServiceConnectionRef, policy: dict[str, Any], extra: UsageAmounts
    ) -> None:
        rows = db.execute(
            "SELECT state,charged,created_at FROM attempts WHERE connection_id=?", (str(connection.connection_id),)
        ).fetchall()
        self._check_rows(rows, policy, extra)
        member = db.execute(
            "SELECT group_id FROM quota_members WHERE connection_id=?", (str(connection.connection_id),)
        ).fetchone()
        if member:
            row = db.execute("SELECT payload FROM task_controls WHERE key=?", ("quota:" + member[0],)).fetchone()
            if row is None:
                raise UsageUnavailable("shared quota is missing")
            group = json.loads(row[0])
            if group["currency"] != policy["currency"] or not (
                datetime.fromisoformat(group["window_start"])
                <= utc(self._clock())
                < datetime.fromisoformat(group["window_end"])
            ):
                raise UsageUnavailable("shared quota is not current")
            rows = db.execute(
                "SELECT a.state,a.charged,a.created_at FROM attempts a JOIN quota_members m "
                "ON a.connection_id=m.connection_id WHERE m.group_id=?",
                (member[0],),
            ).fetchall()
            self._check_rows(rows, group, extra)

    @staticmethod
    def _check_rows(rows: list[tuple[str, str, str]], policy: dict[str, Any], extra: UsageAmounts) -> None:
        totals = extra.to_dict()
        for state, charged, created in rows:
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

    def mark_invoked(
        self,
        attempt_id: str,
        *,
        control_versions: dict[str, int] | None = None,
        expected_budget_revision: int | None = None,
        expires_at: datetime | None = None,
    ) -> AttemptRecord:
        """Commit invocation once, immediately before provider I/O; never retry."""
        with self._transaction() as db:
            record = self._record(db, attempt_id)
            if record.state != "PREPARED":
                raise UsageConflict("attempt cannot be invoked again")
            now = utc(self._clock())
            for key, version in (control_versions or {}).items():
                row = db.execute("SELECT revision FROM task_controls WHERE key=?", (key,)).fetchone()
                if row is None or row[0] != version:
                    raise UsageConflict("admission configuration changed")
            if expires_at is not None and now >= utc(expires_at):
                raise UsageConflict("admission entitlement expired")
            budget_revision, policy = self._budget(db, record.connection, now)
            if expected_budget_revision is not None and budget_revision != expected_budget_revision:
                raise UsageConflict("budget changed")
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
