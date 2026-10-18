"""One app-owned operational incident timeline, separate from trading custody.

Retained until separately authorised manual deletion. There is deliberately no
purge, TTL, truncation or read-side construction. Only fixed-field evidence is
accepted; logs, payloads, destinations and exception messages are never stored.
"""
from __future__ import annotations

import hashlib
import json
import logging
import math
import re
import threading
import time
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from datetime import UTC, datetime, timedelta
from functools import partial
from pathlib import Path
from typing import Any
from uuid import UUID, uuid4

from flask import Flask, current_app, g, has_app_context, has_request_context

from .incident_delivery import ConfiguredAlertBinding
from .owner_file_lock import OwnerSafeFileLock
from .run_adoption_store import ModelEvidenceDatabase

SCHEMA = """
CREATE TABLE incidents(seq INTEGER PRIMARY KEY AUTOINCREMENT, id TEXT UNIQUE NOT NULL,
 correlation TEXT UNIQUE NOT NULL, observed TEXT NOT NULL, body TEXT NOT NULL);
CREATE TABLE deliveries(id TEXT PRIMARY KEY, incident TEXT NOT NULL REFERENCES incidents(id),
 channel TEXT NOT NULL, binding TEXT NOT NULL, state TEXT NOT NULL, attempts INTEGER NOT NULL,
 updated TEXT NOT NULL, reader TEXT, claim TEXT, UNIQUE(incident, channel));
CREATE TABLE delivery_events(seq INTEGER PRIMARY KEY AUTOINCREMENT, delivery TEXT NOT NULL,
 state TEXT NOT NULL, observed TEXT NOT NULL);
CREATE INDEX delivery_pending ON deliveries(state);
CREATE TABLE channels(channel TEXT PRIMARY KEY, enabled INTEGER NOT NULL, binding TEXT NOT NULL);
"""

class IncidentUnavailable(RuntimeError):
    """Evidence could not be retained; never silently replace it with a ring."""

class IncidentAuthorityChanged(RuntimeError):
    """The request lost its original write permission before commit."""

    def __init__(self, status: int) -> None:
        super().__init__("incident_authority_changed")
        self.status = status


class IncidentConflict(RuntimeError):
    """Stale, revoked or already consumed delivery permission."""


def now() -> str:
    return datetime.now(UTC).isoformat()


def identity(value: str) -> str:
    if not isinstance(value, str) or str(UUID(value)) != value:
        raise ValueError("canonical incident identity required")
    return value


class IncidentTimeline:
    def __init__(self, path: Path) -> None:
        # Reuse the existing FULL-sync, hardened, schema/inode-checked SQLite
        # custody helper. This instance owns only operational incident records.
        path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        self._ownership = OwnerSafeFileLock(str(path) + ".owner.lock", timeout=0, thread_local=False)
        self._ownership.acquire()
        try:
            self._database = ModelEvidenceDatabase(path, SCHEMA)
        except BaseException:
            self._ownership.release()
            raise
        self._condition = threading.Condition(threading.RLock())
        self._active = 0
        self._accepting = True
        self.closed: bool = False
        self.storage_state: str = "available"
        self._bindings = {}
        self._delivery_lock = threading.RLock()
        self._wake = threading.Event()
        self._stop = threading.Event()
        self._thread = None
        try:
            with self._db() as db:
                # Exclusive app custody proves these are abandoned, not another
                # live sender. A possibly-sent message must never be replayed.
                for (delivery,) in db.execute("SELECT id FROM deliveries WHERE state='sending'").fetchall():
                    self._transition(db, delivery, "unknown")
        except BaseException:
            self._ownership.release()
            raise

    @contextmanager
    def admitted(self) -> Iterator[None]:
        with self._condition:
            if not self._accepting:
                raise IncidentUnavailable("incident_owner_retired")
            if self._active >= 64:
                raise IncidentUnavailable("incident_backpressure")
            self._active += 1
        try:
            yield
        finally:
            with self._condition:
                self._active -= 1
                self._condition.notify_all()

    @contextmanager
    def _db(self):
        try:
            with self._database.transaction() as db:
                yield db
        except (IncidentConflict, IncidentAuthorityChanged):
            raise
        except Exception as error:
            self.storage_state = "unavailable"
            raise IncidentUnavailable("incident_storage_unavailable") from error

    def observe_http(self, correlation_id: str, status_code: int, duration_ms: float, *, critical: bool = False, operation: str = "unmatched_route") -> dict[str, Any]:
        # Correlation comes from the server, never a client header.
        UUID(correlation_id.replace(".", "-"))
        if type(critical) is not bool or type(status_code) is not int or not (100 if critical else 400) <= status_code <= 599:
            raise ValueError("failed HTTP observation required")
        if type(duration_ms) not in (int, float) or not math.isfinite(duration_ms) or duration_ms < 0:
            raise ValueError("measured nonnegative duration required")
        if type(operation) is not str or not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_.]{0,95}", operation):
            operation = "unclassified_operation"
        return self._observe(correlation_id, status_code, duration_ms, "core_http", critical=critical, operation=operation)

    def observe_log(self) -> dict[str, Any]:
        return self._observe(str(uuid4()), None, None, "core_log")

    def observe_failure(self, reference: str, *, source: str) -> None:
        """Accept only opaque identities from the exact bound passive producer."""
        identity(reference)
        producers = {"history_job": "historify_job_manager", "model_task": "service_usage_ledger"}
        if source not in producers:
            raise ValueError("unsupported incident producer")
        try:
            self._observe(reference, None, None, source, operation=producers[source],
                          failure={"kind": producers[source], "reference": reference})
        except IncidentUnavailable:
            pass  # The owner exposes unavailable storage; never invent a receipt.

    def _observe(self, correlation_id, status_code, duration_ms, source, *, critical=False, operation="critical_log", failure=None):
        with self.admitted(), self._db() as db:
            existing = db.execute("SELECT body FROM incidents WHERE correlation=?", (correlation_id,)).fetchone()
            if existing:
                return json.loads(existing[0])
            observed = now()
            body = {"id": str(uuid4()), "correlation_id": correlation_id,
                    "observed_at": observed, "source": source, "scope": "core_process",
                    "severity": "critical" if critical or status_code is None or status_code >= 500 else "warning",
                    "code": "http_failure" if status_code is not None and status_code >= 400 else "application_failure", "freshness": "observed",
                    "operation": operation,
                    "measurement": {"state": "measured" if duration_ms is not None else "unmeasured", "duration_ms": duration_ms, "status_code": status_code},
                    "root_cause": {"state": "unknown", "code": None}}
            if failure is not None:
                body.update(severity="warning", code=source + "_failure", producer=failure)
            db.execute("INSERT INTO incidents(id,correlation,observed,body) VALUES (?,?,?,?)",
                       (body["id"], correlation_id, observed, json.dumps(body, allow_nan=False)))
            if body["severity"] == "critical":
                from .desktop_notify import desktop_shell_active
                backlog = db.execute("SELECT COUNT(*) FROM deliveries WHERE state IN ('pending','browser_pending','sending')").fetchone()[0]
                for channel in ("desktop", "telegram", "email"):
                    binding = "native" if desktop_shell_active() else "browser"
                    state = "pending" if binding == "native" else "browser_pending"
                    if channel != "desktop":
                        config = db.execute("SELECT enabled,binding FROM channels WHERE channel=?", (channel,)).fetchone()
                        state, binding = ("pending", config[1]) if config and config[0] else ("disabled", "disabled")
                    if state in ("pending", "browser_pending") and backlog >= 1000:
                        state = "backpressure"
                    delivery = str(uuid4())
                    db.execute("INSERT INTO deliveries(id,incident,channel,binding,state,attempts,updated) VALUES (?,?,?,?,?,?,?)",
                               (delivery, body["id"], channel, binding, state, 0, observed))
                    self._transition(db, delivery, state)
            self._wake.set()
            return body

    @staticmethod
    def _transition(db, delivery, state):
        observed = now()
        db.execute("UPDATE deliveries SET state=?,updated=? WHERE id=?", (state, observed, delivery))
        db.execute("INSERT INTO delivery_events(delivery,state,observed) VALUES (?,?,?)", (delivery, state, observed))

    @staticmethod
    def _receipts(db, incident):
        return [dict(zip(("id","channel","state","attempts","updated_at"), row)) for row in db.execute(
            "SELECT id,channel,state,attempts,updated FROM deliveries WHERE incident=? ORDER BY channel", (incident,))]

    def configure(self, channel: str, *, enabled: bool, binding: ConfiguredAlertBinding | None = None, authority_check: Callable[[], None] | None = None) -> dict[str, Any]:
        if channel not in ("telegram", "email") or type(enabled) is not bool:
            raise ValueError("explicit optional channel required")
        fingerprint = binding.fingerprint() if enabled and binding else None
        if enabled and not fingerprint:
            raise ValueError("configured binding required")
        with self.admitted(), self._condition:
            with self._db() as db:
                if authority_check is not None:
                    authority_check()
                db.execute("INSERT INTO channels VALUES (?,?,?) ON CONFLICT(channel) DO UPDATE SET enabled=excluded.enabled,binding=excluded.binding",
                           (channel, int(enabled), fingerprint or "disabled"))
                for (delivery,) in db.execute("SELECT id FROM deliveries WHERE channel=? AND state='pending'", (channel,)).fetchall():
                    self._transition(db, delivery, "revoked")
                # Refuse and roll back if authority retired during persistence.
                if authority_check is not None:
                    authority_check()
            if enabled:
                self._bindings[channel] = binding
            else:
                self._bindings.pop(channel, None)
        return {"channel": channel, "enabled": enabled, "binding": fingerprint,
                "restart": "explicit_rebind_required", "in_flight": "not_recalled"}

    def delivery(self, delivery: str) -> dict[str, Any]:
        identity(delivery)
        with self.admitted(), self._db() as db:
            row = db.execute("SELECT incident FROM deliveries WHERE id=?", (delivery,)).fetchone()
            if not row:
                raise IncidentConflict("delivery_not_found")
            value = next(r for r in self._receipts(db, row[0]) if r["id"] == delivery)
            value["history"] = [dict(zip(("state", "observed_at"), event)) for event in db.execute(
                "SELECT state,observed FROM delivery_events WHERE delivery=? ORDER BY seq DESC LIMIT 20", (delivery,))]
            return value

    def channel(self, channel: str) -> dict[str, Any]:
        if channel not in ("telegram", "email"):
            raise ValueError("optional channel required")
        with self.admitted(), self._db() as db:
            row = db.execute("SELECT enabled,binding FROM channels WHERE channel=?", (channel,)).fetchone()
            enabled, fingerprint = row or (0, None)
            binding = self._bindings.get(channel)
            return {"channel": channel, "enabled": bool(enabled), "binding": fingerprint if enabled else None,
                    "effective": bool(enabled and binding and binding.fingerprint() == fingerprint),
                    "restart": "explicit_rebind_required", "in_flight": "not_recalled"}

    def delivery_action(self, delivery: str, action: str) -> dict[str, Any]:
        identity(delivery)
        if action not in ("retry", "cancel"):
            raise ValueError("invalid delivery action")
        with self.admitted(), self._condition, self._db() as db:
            row = db.execute("SELECT state,attempts,channel,binding FROM deliveries WHERE id=?", (delivery,)).fetchone()
            if not row:
                raise IncidentConflict("delivery_not_found")
            state, attempts, channel, fingerprint = row
            if action == "retry":
                if state != "failed" or attempts >= 3:
                    raise IncidentConflict("delivery_not_retryable")
                if channel != "desktop":
                    config = db.execute("SELECT enabled,binding FROM channels WHERE channel=?", (channel,)).fetchone()
                    binding = self._bindings.get(channel)
                    if not binding or config != (1, fingerprint) or binding.fingerprint() != fingerprint:
                        raise IncidentConflict("delivery_binding_retired")
                state = "browser_pending" if fingerprint == "browser" else "pending"
            else:
                if state not in ("pending", "browser_pending", "failed", "backpressure"):
                    raise IncidentConflict("delivery_already_started_or_terminal")
                state = "cancelled"
            self._transition(db, delivery, state)
        self._wake.set()
        return self.delivery(delivery)

    def claim_browser(self, delivery: str, reader: str) -> dict[str, str]:
        identity(delivery)
        claim = str(uuid4())
        with self.admitted(), self._db() as db:
            row = db.execute("SELECT channel,binding,state,attempts FROM deliveries WHERE id=?", (delivery,)).fetchone()
            if not row or row[:3] != ("desktop", "browser", "browser_pending") or row[3] >= 3:
                raise IncidentConflict("browser_delivery_already_claimed")
            db.execute("UPDATE deliveries SET reader=?,claim=?,attempts=attempts+1 WHERE id=?",
                       (reader, hashlib.sha256(claim.encode()).hexdigest(), delivery))
            self._transition(db, delivery, "sending")
        return {"id": delivery, "claim": claim, "state": "sending"}

    def browser_receipt(self, delivery: str, reader: str, claim: str, state: str) -> dict[str, Any]:
        identity(delivery)
        identity(claim)
        if state not in ("submitted_unobserved", "failed", "unknown"):
            raise ValueError("unsupported browser observation")
        with self.admitted(), self._db() as db:
            row = db.execute("SELECT state,reader,claim FROM deliveries WHERE id=?", (delivery,)).fetchone()
            if not row or row[1:] != (reader, hashlib.sha256(claim.encode()).hexdigest()):
                raise IncidentConflict("browser_delivery_reader_retired")
            if row[0] != state:
                if row[0] != "sending":
                    raise IncidentConflict("browser_delivery_already_final")
                self._transition(db, delivery, state)
        return self.delivery(delivery)

    def start(self) -> None:
        with self._condition:
            if self._thread is not None or not self._accepting:
                return
            self._thread = threading.Thread(target=self._run, name="system-incident-delivery", daemon=True)
            self._thread.start()

    def _run(self):
        while not self._stop.is_set():
            self._wake.wait(1)
            self._wake.clear()
            if self._stop.is_set():
                return
            try:
                self.deliver_pending()
            except IncidentUnavailable:
                pass  # Storage state remains explicit; no second evidence store.

    def deliver_pending(self) -> None:
        from .desktop_notify import submit_incident
        with self.admitted(), self._delivery_lock:
            with self._db() as db:
                expired = (datetime.now(UTC) - timedelta(seconds=30)).isoformat()
                for (delivery,) in db.execute("SELECT id FROM deliveries WHERE binding='browser' AND state='sending' AND updated<? LIMIT 20", (expired,)).fetchall():
                    self._transition(db, delivery, "unknown")
                pending = db.execute("SELECT id,channel,binding FROM deliveries WHERE state='pending' ORDER BY updated LIMIT 20").fetchall()
            for delivery, channel, fingerprint in pending:
                if self._stop.is_set():
                    break
                binding = self._bindings.get(channel)
                with self._condition, self._db() as db:
                    if channel != "desktop":
                        config = db.execute("SELECT enabled,binding FROM channels WHERE channel=?", (channel,)).fetchone()
                        if not binding or not config or config != (1, fingerprint) or binding.fingerprint() != fingerprint:
                            self._transition(db, delivery, "revoked")
                            continue
                    row = db.execute("SELECT state,attempts FROM deliveries WHERE id=?", (delivery,)).fetchone()
                    if row[0] != "pending" or row[1] >= 3:
                        continue
                    self._transition(db, delivery, "sending")
                    db.execute("UPDATE deliveries SET attempts=attempts+1 WHERE id=?", (delivery,))
                # Only the durable claim permits I/O. No transaction spans a
                # network call. Any exception/lost result is unknown, not retry.
                try:
                    result = submit_incident() if channel == "desktop" else binding.send(fingerprint)
                    if result not in ("submitted_unobserved", "failed", "unknown", "revoked"):
                        result = "unknown"
                except Exception:
                    result = "unknown"
                with self._db() as db:
                    self._transition(db, delivery, result)

    def snapshot(self, *, limit: int = 50, before: int | None = None) -> dict[str, Any]:
        if type(limit) is not int or not 1 <= limit <= 100:
            raise ValueError("bounded incident limit required")
        if before is not None and (type(before) is not int or before <= 0):
            raise ValueError("invalid incident cursor")
        with self.admitted(), self._db() as db:
            rows = db.execute("SELECT seq,body FROM incidents WHERE (? IS NULL OR seq<?) ORDER BY seq DESC LIMIT ?",
                              (before, before, limit + 1)).fetchall()
            selected = rows[:limit]
            return {"status": "available", "durable": True, "retention": "until_manual_deletion",
                    "storage": self.storage_state, "source": "operational_sqlite", "observed_at": now(),
                    "scope": "core_process", "incidents": [dict(json.loads(row[1]), deliveries=self._receipts(db, json.loads(row[1])["id"])) for row in selected],
                    "has_more": len(rows) > limit, "next_cursor": selected[-1][0] if len(rows) > limit else None}

    def close(self, timeout: float = 5.0) -> None:
        deadline = time.monotonic() + max(0, timeout)
        with self._condition:
            self._accepting = False
            self._stop.set()
            self._wake.set()
            while self._active:
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    raise IncidentUnavailable("incident_producers_not_drained")
                self._condition.wait(remaining)
        if self._thread and self._thread is not threading.current_thread():
            self._thread.join(max(0, deadline - time.monotonic()))
            if self._thread.is_alive():
                raise IncidentUnavailable("incident_worker_not_drained")
        with self._condition:
            if self.closed:
                return
            # Retain this exact owner after checkpoint/storage failure for retry.
            with self._db():
                pass
            self.closed = True
            self._ownership.release()
            handler = getattr(self, "_capture", None)
            if handler is not None:
                for name in ("flinttrade", "flinttrade_core"):
                    logging.getLogger(name).removeHandler(handler)


def install_incident_timeline(app: Flask, root: Path) -> None:
    if "SYSTEM_INCIDENTS" not in app.config:
        app.config["SYSTEM_INCIDENTS"] = IncidentTimeline(Path(root) / "operational" / "incidents.sqlite")
        manager = app.config.get("HISTORIFY_JOB_MANAGER")
        if manager is not None:
            manager.failure_sink = partial(app.config["SYSTEM_INCIDENTS"].observe_failure, source="history_job")
        app.config["SYSTEM_INCIDENTS"].start()
        handler = IncidentCapture(app.config["SYSTEM_INCIDENTS"])
        app.config["SYSTEM_INCIDENTS"]._capture = handler
        for name in ("flinttrade", "flinttrade_core"):
            logging.getLogger(name).addHandler(handler)


class IncidentCapture(logging.Handler):
    """Capture critical signals, never log text or attributes containing secrets."""
    def __init__(self, owner: IncidentTimeline) -> None:
        super().__init__(logging.CRITICAL)
        self.owner: IncidentTimeline = owner

    def emit(self, record: logging.LogRecord) -> None:
        # HTTP completion already creates one correlated incident. A request's
        # propagating log must not create another incident for the same action.
        if has_app_context() and current_app.config.get("SYSTEM_INCIDENTS") is not self.owner:
            return
        if has_request_context():
            g.diagnostic_critical = True
            return
        if not has_app_context() and sum(isinstance(h, IncidentCapture) for h in logging.getLogger("flinttrade").handlers) != 1:
            return  # Ambiguous multi-app background ownership, never cross-scope.
        try:
            self.owner.observe_log()
        except IncidentUnavailable:
            pass  # Owner exposes storage failure; logging never recursively logs.
