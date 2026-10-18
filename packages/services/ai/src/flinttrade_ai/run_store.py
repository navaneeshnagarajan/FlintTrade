"""SQLite evidence store for autonomous Practice runs.

Writes are synchronous and fail closed: a caller must never continue a run
after its evidence cannot be committed. Connections are serialised across
threads; SQLite transactions coordinate independent processes.
"""

from __future__ import annotations

import base64
import binascii
import json
import math
import re
import sqlite3
import threading
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

_MAX_PAYLOAD_BYTES = 64 * 1024
_MAX_PAYLOAD_NODES = 4096
_MAX_PAYLOAD_DEPTH = 16
_CREDENTIAL_KEYS = ("credential", "password", "token", "secret", "authorization", "apikey")
_COMPACT_AUTH = re.compile(r"(?<![A-Za-z0-9_-])([A-Za-z0-9_-]{2,})\.[A-Za-z0-9_-]*\.[A-Za-z0-9_-]*")
_BEARER = re.compile(r"\bBearer\s+\S+", re.IGNORECASE)
_TRANSITIONS = {
    "starting": {"waiting", "running", "stopping", "stopped", "completed", "failed", "reconciliation_required"},
    "waiting": {"running", "stopping", "stopped", "completed", "failed", "reconciliation_required"},
    "running": {"waiting", "stopping", "stopped", "completed", "failed", "reconciliation_required"},
    "stopping": {"stopped", "failed", "reconciliation_required"},
    "stopped": set(),
    "completed": set(),
    "failed": set(),
    "reconciliation_required": {"stopped", "failed"},
}


def _safe_text(value: str) -> None:
    if _BEARER.search(value):
        raise ValueError("credential material is not permitted in run evidence")
    # JSON permits whitespace before a header's first property, so JWTs do
    # not always begin with "eyJ". Decode only bounded compact candidates;
    # ordinary dotted symbols or version strings are not credentials.
    for match in _COMPACT_AUTH.finditer(value):
        encoded = match.group(1)
        try:
            header = json.loads(base64.urlsafe_b64decode(encoded + "=" * (-len(encoded) % 4)))
        except (ValueError, UnicodeDecodeError, binascii.Error):
            continue
        if type(header) is dict:
            raise ValueError("credential material is not permitted in run evidence")


def _identifier(value: object) -> str:
    if type(value) is not str or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.:-]{0,127}", value):
        raise ValueError("run identifiers and event kinds must be bounded identifier text")
    _safe_text(value)
    return value


def _bounded_integer(value: object, *, minimum: int, maximum: int) -> int:
    if type(value) is not int or not minimum <= value <= maximum:
        raise ValueError(f"integer must be between {minimum} and {maximum}")
    return value


def _payload(value: object) -> str:
    if type(value) is not dict:
        raise ValueError("run payload must be a JSON object")
    nodes = 0

    def validate(item: object, depth: int) -> None:
        nonlocal nodes
        nodes += 1
        if depth > _MAX_PAYLOAD_DEPTH or nodes > _MAX_PAYLOAD_NODES:
            raise ValueError("run payload nesting or node limit exceeded")
        if item is None or type(item) is bool:
            return
        if type(item) is str:
            if len(item) > _MAX_PAYLOAD_BYTES:
                raise ValueError("run payload byte limit exceeded")
            _safe_text(item)
            return
        if type(item) is int and -(1 << 63) <= item < (1 << 63):
            return
        if type(item) is float and math.isfinite(item):
            return
        if type(item) is list:
            for child in item:
                validate(child, depth + 1)
            return
        if type(item) is dict:
            for key, child in item.items():
                if type(key) is not str:
                    raise ValueError("run JSON object keys must be strings")
                normalised = re.sub(r"[^a-z0-9]", "", key.lower())
                if any(part in normalised for part in _CREDENTIAL_KEYS):
                    raise ValueError("credential fields are not permitted in run evidence")
                validate(key, depth + 1)
                validate(child, depth + 1)
            return
        raise ValueError("run payload must contain only finite JSON values")

    validate(value, 0)
    encoded = json.dumps(value, allow_nan=False, ensure_ascii=True, separators=(",", ":"), sort_keys=True)
    if len(encoded.encode("utf-8")) > _MAX_PAYLOAD_BYTES:
        raise ValueError("run payload byte limit exceeded")
    return encoded


def _stamp(now: datetime | None = None) -> str:
    if now is None:
        now = datetime.now(UTC)
    if type(now) is not datetime or now.tzinfo is None or now.utcoffset() is None:
        raise ValueError("run timestamps must be timezone-aware datetimes")
    return now.astimezone(UTC).isoformat(timespec="microseconds")


class AgentRunStore:
    """Persist run snapshots and ordered evidence with full SQLite durability.

    Args:
        path: SQLite file path; ``:memory:`` is supported for isolated tests.
    """

    def __init__(self, path: str | Path, *, strict_existing: bool = False) -> None:
        if str(path) != ":memory:":
            path = Path(path).expanduser().resolve()
            path.parent.mkdir(parents=True, exist_ok=True)
        self._database_path = str(path)
        if strict_existing and (str(path) == ":memory:" or not Path(path).is_file()):
            raise ValueError("Established execution history unavailable")
        self._lock = threading.RLock()
        self._conn = sqlite3.connect(self._database_path, isolation_level=None, check_same_thread=False, timeout=10.0)
        self._conn.row_factory = sqlite3.Row
        try:
            if strict_existing:
                expected = {"agent_runs", "agent_run_events", "agent_runs_one_active", "agent_runs_newest", "agent_run_events_by_run"}
                names = {row[0] for row in self._conn.execute("SELECT name FROM sqlite_master")}
                if not expected <= names:
                    raise ValueError("Established execution schema unavailable")
            self._conn.execute("PRAGMA journal_mode = WAL")
            self._conn.execute("PRAGMA synchronous = FULL")
            self._conn.execute("PRAGMA foreign_keys = ON")
            with self._transaction():
                self._conn.execute(
                    """
                    CREATE TABLE IF NOT EXISTS agent_runs (
                        run_id TEXT PRIMARY KEY,
                        mode TEXT NOT NULL CHECK (mode = 'practice'),
                        status TEXT NOT NULL CHECK (status IN (
                            'starting', 'waiting', 'running', 'stopping', 'stopped',
                            'completed', 'failed', 'reconciliation_required'
                        )),
                        config TEXT NOT NULL,
                        snapshot TEXT NOT NULL,
                        error TEXT,
                        created_at TEXT NOT NULL,
                        updated_at TEXT NOT NULL
                    )
                    """
                )
                # An unresolved interruption owns the same singleton slot as
                # a running worker. The database, not a process-local check,
                # enforces exclusion even across independent connections.
                self._conn.execute(
                    """
                    CREATE UNIQUE INDEX IF NOT EXISTS agent_runs_one_active ON agent_runs ((1))
                    WHERE status IN ('starting', 'waiting', 'running', 'stopping', 'reconciliation_required')
                    """
                )
                self._conn.execute(
                    "CREATE INDEX IF NOT EXISTS agent_runs_newest ON agent_runs (created_at DESC, run_id DESC)"
                )
                self._conn.execute(
                    """
                    CREATE TABLE IF NOT EXISTS agent_run_events (
                        seq INTEGER PRIMARY KEY AUTOINCREMENT,
                        run_id TEXT NOT NULL REFERENCES agent_runs(run_id),
                        kind TEXT NOT NULL,
                        data TEXT NOT NULL,
                        created_at TEXT NOT NULL
                    )
                    """
                )
                self._conn.execute(
                    "CREATE INDEX IF NOT EXISTS agent_run_events_by_run ON agent_run_events (run_id, seq)"
                )
        except BaseException:
            self._conn.close()
            raise

    @property
    def database_path(self) -> str:
        """Return the canonical database identity for runtime ownership locks."""
        return self._database_path

    @contextmanager
    def _transaction(self) -> Iterator[None]:
        with self._lock:
            self._conn.execute("BEGIN IMMEDIATE")
            try:
                yield
                self._conn.commit()
            except BaseException:
                self._conn.rollback()
                raise

    @staticmethod
    def _run(row: sqlite3.Row) -> dict[str, Any]:
        result = dict(row)
        result["config"] = json.loads(result["config"])
        result["snapshot"] = json.loads(result["snapshot"])
        return result

    def create_run(
        self,
        *,
        run_id: str,
        mode: str,
        config: dict[str, Any],
        now: datetime | None = None,
    ) -> dict[str, Any]:
        """Commit a new run before the caller starts executing it."""
        _identifier(run_id)
        if type(mode) is not str or mode != "practice":
            raise ValueError("only practice runs may be persisted")
        encoded = _payload(config)
        timestamp = _stamp(now)
        with self._transaction():
            if self._conn.execute("SELECT 1 FROM agent_runs WHERE run_id = ?", (run_id,)).fetchone() is not None:
                raise ValueError("run identity already exists")
            if self._conn.execute(
                """SELECT 1 FROM agent_runs WHERE status IN
                ('starting', 'waiting', 'running', 'stopping', 'reconciliation_required') LIMIT 1"""
            ).fetchone() is not None:
                raise RuntimeError("an active run or unresolved interruption already exists")
            self._conn.execute(
                "INSERT INTO agent_runs VALUES (?, ?, 'starting', ?, '{}', NULL, ?, ?)",
                (run_id, mode, encoded, timestamp, timestamp),
            )
            row = self._conn.execute("SELECT * FROM agent_runs WHERE run_id = ?", (run_id,)).fetchone()
            return self._run(row)

    def update_run(
        self,
        run_id: str,
        *,
        status: str,
        snapshot: dict[str, Any] | None = None,
        error: str | None = None,
    ) -> dict[str, Any]:
        """Commit a lifecycle transition and, when supplied, its snapshot."""
        return self._update_run(run_id, status=status, snapshot=snapshot, error=error)

    def transition_run(
        self,
        run_id: str,
        *,
        status: str,
        snapshot: dict[str, Any] | None = None,
        error: str | None = None,
        event_kind: str = "status_changed",
        event_data: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Atomically commit a changed lifecycle, its snapshot and evidence.

        Default evidence names the previous durable status, read under the
        same transaction. Callers may supply a specific lifecycle event, such
        as reconciliation resolution. Same-status refreshes emit no event.
        """
        _identifier(event_kind)
        encoded_event = None if event_data is None else _payload(event_data)
        return self._update_run(run_id, status=status, snapshot=snapshot, error=error,
                                event_kind=event_kind, encoded_event=encoded_event)

    def _update_run(
        self,
        run_id: str,
        *,
        status: str,
        snapshot: dict[str, Any] | None,
        error: str | None,
        event_kind: str | None = None,
        encoded_event: str | None = None,
    ) -> dict[str, Any]:
        _identifier(run_id)
        if type(status) is not str or status not in _TRANSITIONS:
            raise ValueError("unknown run status")
        encoded = None if snapshot is None else _payload(snapshot)
        if error is not None:
            if type(error) is not str or len(error) > 4096:
                raise ValueError("run error must be bounded text")
            _safe_text(error)
        with self._transaction():
            current = self._conn.execute("SELECT status FROM agent_runs WHERE run_id = ?", (run_id,)).fetchone()
            if current is None:
                raise KeyError(run_id)
            previous = current["status"]
            if status != previous and status not in _TRANSITIONS[previous]:
                raise ValueError(f"invalid run status transition: {previous} to {status}")
            timestamp = _stamp()
            if event_kind is not None and status != previous:
                self._conn.execute(
                    "INSERT INTO agent_run_events (run_id, kind, data, created_at) VALUES (?, ?, ?, ?)",
                    (run_id, event_kind, encoded_event or _payload({"previous": previous, "status": status}), timestamp),
                )
            self._conn.execute(
                """
                UPDATE agent_runs SET status = ?, snapshot = COALESCE(?, snapshot), error = ?, updated_at = ?
                WHERE run_id = ?
                """,
                (status, encoded, error, timestamp, run_id),
            )
            row = self._conn.execute("SELECT * FROM agent_runs WHERE run_id = ?", (run_id,)).fetchone()
            return self._run(row)

    def append_event(self, run_id: str, *, kind: str, data: dict[str, Any]) -> int:
        """Commit evidence and return its monotonically increasing sequence."""
        _identifier(run_id)
        _identifier(kind)
        encoded = _payload(data)
        with self._transaction():
            if self._conn.execute("SELECT 1 FROM agent_runs WHERE run_id = ?", (run_id,)).fetchone() is None:
                raise KeyError(run_id)
            cursor = self._conn.execute(
                "INSERT INTO agent_run_events (run_id, kind, data, created_at) VALUES (?, ?, ?, ?)",
                (run_id, kind, encoded, _stamp()),
            )
            return int(cursor.lastrowid)

    def get_run(self, run_id: str) -> dict[str, Any] | None:
        """Return a detached run snapshot, or ``None`` for an unknown run."""
        _identifier(run_id)
        with self._lock:
            row = self._conn.execute("SELECT * FROM agent_runs WHERE run_id = ?", (run_id,)).fetchone()
            return None if row is None else self._run(row)

    def list_runs(self, limit: int = 20) -> list[dict[str, Any]]:
        """Return at most 100 runs, newest first, breaking ties by run identity."""
        _bounded_integer(limit, minimum=1, maximum=100)
        with self._lock:
            rows = self._conn.execute(
                "SELECT * FROM agent_runs ORDER BY created_at DESC, run_id DESC LIMIT ?", (limit,)
            ).fetchall()
            return [self._run(row) for row in rows]

    def rearm_execution(self, scope: dict[str, str]) -> dict[str, Any]:
        """Rearm an exact retired owner after core flat proof; never replay writes.

        The caller must hold the backend/run/book fence. This changes lifecycle
        only: order events, model controls, config and execution identity remain.
        """
        _payload(scope)
        run_id = _identifier(scope.get("run_id"))
        with self._transaction():
            row = self.get_run(run_id)
            if (row is None or row["config"].get("execution_session") != scope
                    or row["config"].get("owner") != scope.get("actor")
                    or row["status"] not in {"stopped", "completed", "failed", "reconciliation_required"}):
                raise ValueError("execution scope or lifecycle mismatch")
            pending = None
            for event in self._conn.execute("SELECT kind,data FROM agent_run_events WHERE run_id=? ORDER BY seq", (run_id,)):
                value = json.loads(event["data"])
                if event["kind"] == "dispatch_started":
                    if pending is not None:
                        raise ValueError("uncertain dispatch requires reconciliation")
                    pending = value.get("order")
                    if not isinstance(pending, dict):
                        raise ValueError("uncertain dispatch evidence")
                elif event["kind"] == "dispatch_result":
                    response = value.get("response", {})
                    if (pending is None or value.get("order") != pending or not isinstance(response, dict)
                            or response.get("status") not in {"COMPLETE", "success", "error"}
                            or any(word in str(response.get("code", "")) for word in ("uncertain", "unknown", "reconciliation"))):
                        raise ValueError("uncertain dispatch requires reconciliation")
                    pending = None
            if pending is not None:
                raise ValueError("uncertain dispatch requires reconciliation")
            stamp = _stamp()
            self._conn.execute("UPDATE agent_runs SET status='starting',updated_at=? WHERE run_id=?", (stamp, run_id))
            self._conn.execute("INSERT INTO agent_run_events(run_id,kind,data,created_at) VALUES (?,'execution_rearmed',?,?)",
                               (run_id, _payload({"scope": scope}), stamp))
            result = self.get_run(run_id)
            assert result is not None
            return result

    def ownership_census(self) -> list[dict[str, Any]]:
        """Unpaginated durable owner identities for maintenance, never UI state."""
        with self._lock:
            return [self._run(row) for row in self._conn.execute("SELECT * FROM agent_runs ORDER BY run_id")]

    def events(self, run_id: str, *, after: int = 0, limit: int = 100) -> list[dict[str, Any]]:
        """Return at most 1,000 events after an exclusive global sequence cursor."""
        _identifier(run_id)
        _bounded_integer(after, minimum=0, maximum=(1 << 63) - 1)
        _bounded_integer(limit, minimum=1, maximum=1000)
        with self._lock:
            rows = self._conn.execute(
                "SELECT * FROM agent_run_events WHERE run_id = ? AND seq > ? ORDER BY seq LIMIT ?",
                (run_id, after, limit),
            ).fetchall()
            return [{**dict(row), "data": json.loads(row["data"])} for row in rows]

    def recover_interrupted(self) -> int:
        """Fence interrupted runs and commit their evidence in one transaction.

        Invoke only when acquiring runtime ownership at startup, never as a
        periodic health check against a live worker. No run is resumed here.
        Repeated calls leave already-fenced or terminal runs untouched.
        """
        with self._transaction():
            rows = self._conn.execute(
                "SELECT run_id, status FROM agent_runs WHERE status IN ('starting', 'waiting', 'running', 'stopping')"
            ).fetchall()
            timestamp = _stamp()
            for row in rows:
                self._conn.execute(
                    "UPDATE agent_runs SET status = 'reconciliation_required', updated_at = ? WHERE run_id = ?",
                    (timestamp, row["run_id"]),
                )
                self._conn.execute(
                    "INSERT INTO agent_run_events (run_id, kind, data, created_at) VALUES (?, ?, ?, ?)",
                    (
                        row["run_id"],
                        "run_interrupted",
                        _payload({"previous_status": row["status"], "status": "reconciliation_required"}),
                        timestamp,
                    ),
                )
            return len(rows)

    @contextmanager
    def run_fence(self, run_id: str) -> Iterator[None]:
        """Serialise model control with this store's lifecycle/evidence writers."""
        _identifier(run_id)
        with self._lock:
            if self.get_run(run_id) is None:
                raise KeyError(run_id)
            yield

    def model_control(self, run_id: str, key: str) -> tuple[int, dict[str, Any] | None]:
        """Read the latest append-only model control, never execution state."""
        _identifier(run_id)
        _identifier(key)
        with self._lock:
            row = self._conn.execute(
                "SELECT data FROM agent_run_events WHERE run_id=? AND kind='model_control' "
                "AND json_extract(data, '$.key')=? ORDER BY seq DESC LIMIT 1", (run_id, key),
            ).fetchone()
            if row is None:
                return 0, None
            value = json.loads(row[0])
            return value["revision"], value["value"]

    def configure_model_control(
        self, run_id: str, key: str, value: dict[str, Any], *, expected_revision: int,
    ) -> int:
        """CAS model metadata into the existing run's durable event history."""
        _identifier(run_id)
        _identifier(key)
        _bounded_integer(expected_revision, minimum=0, maximum=(1 << 63) - 2)
        encoded = _payload({"key": key, "revision": expected_revision + 1, "value": value})
        with self._transaction():
            if self.get_run(run_id) is None:
                raise KeyError(run_id)
            revision, _ = self.model_control(run_id, key)
            if revision != expected_revision:
                raise ValueError("model control revision changed")
            self._conn.execute(
                "INSERT INTO agent_run_events(run_id,kind,data,created_at) VALUES (?,'model_control',?,?)",
                (run_id, encoded, _stamp()),
            )
        return expected_revision + 1

    def close(self) -> None:
        """Close the connection after serialising with any pending operation."""
        with self._lock:
            self._conn.close()
