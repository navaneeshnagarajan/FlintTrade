"""Optional, version-pinned training management; no bundled runtime or credentials.

Only a configured core gateway may perform I/O. It composes LearningConsentLedger
and ServiceUsageLedger at send initiation; inference enablement is not training
permission. Publication/selection/reset are deliberately not exposed.
"""
from __future__ import annotations

import json
from pathlib import Path

from .evaluation import canonical, digest

UNSLOTH_PIN = "3e7898659344873423a9a09438c80d51bc056655"


class UnslothTrainingBackend:
    """Management protocol, not a promise of deployed entitlement or capacity.

    gateway(operation, method, path, payload) must synchronously gate the actual
    send. No retries, redirect following, ambient auth or default HTTP client.
    capacity_isolated is trusted deployment configuration, not an HTTP input.
    """

    def __init__(self, *, version, principal_role, capacity_isolated=False, gateway=None):
        if version != UNSLOTH_PIN:
            raise ValueError("Unqualified Unsloth management version")
        self.version, self.principal_role = version, principal_role
        self.capacity_isolated, self.gateway = capacity_isolated, gateway

    def validate(self, payload):
        allowed = {"model_name", "training_type", "format_type", "hf_dataset", "local_datasets",
                   "local_eval_datasets", "train_split", "eval_split", "eval_steps", "is_decision",
                   "resume_from_checkpoint", "streaming"}
        if not isinstance(payload, dict) or set(payload) - allowed:
            raise ValueError("Unsupported training field/operation; publication disabled")
        if not all(payload.get(k) for k in ("model_name", "training_type", "format_type")):
            raise ValueError("Exact model/method/format required")
        if not payload.get("local_datasets") and not payload.get("hf_dataset"):
            raise ValueError("Explicit remote dataset handle required")
        if not self.capacity_isolated:
            raise ValueError("Training must not displace protection-critical serving")
        if payload.get("is_decision"):
            if self.principal_role != "owner":
                raise ValueError("Decision training requires Studio owner")
            if payload.get("resume_from_checkpoint") or payload.get("streaming"):
                raise ValueError("Decision resume and streaming unsupported")
        if self.gateway is None:
            raise ValueError("Training authority/gateway unavailable")
        canonical(payload)

    def start(self, request_id, payload):
        self.validate(payload)
        return self.gateway("training.start", "POST", "/api/train/start", {**payload, "start_request_id": request_id})

    def status(self):
        return self.gateway("training.status", "GET", "/api/train/status", {})

    def cancel(self, job_id):
        return self.gateway("training.cancel", "POST", "/api/train/stop", {"expected_job_id": job_id, "save": False})


class LearningTrainingGateway:
    """Compose the existing consent/usage authority at the actual send seam.

    context is a trusted core resolver of exact batch, recipient, limits and
    control evidence; it must not consume an agent-supplied grant as authority.
    transport is owned here, so workers cannot retain a permit for later I/O.
    Post-revocation status/cancel uses a separate minimal management dispatcher.
    """

    def __init__(self, *, consent, context, transport, management=None):
        self.consent, self.context = consent, context
        self.transport, self.management = transport, management

    def __call__(self, operation, method, path, payload):
        from urllib.parse import urlsplit

        if operation == "training.start" and (method, path) == ("POST", "/api/train/start"):
            wire = canonical(payload).encode()
            context = dict(self.context(operation, method, path, wire))
            recipient = context["recipient"]
            if urlsplit(recipient.endpoint).path != path or recipient.method != operation:
                raise ValueError("Exact training destination/method mismatch")
            return self.consent.dispatch(**context, purpose="fine-tuning", operation=operation,
                payload=wire, send=lambda: self.transport(method, path, json.loads(wire)))
        if self.management is None:
            raise ValueError("Separate management authority required")
        allowed = {"training.status": ("GET", "/api/train/status"),
                   "training.cancel": ("POST", "/api/train/stop")}
        if allowed.get(operation) != (method, path):
            raise ValueError("Unsupported management operation; publication disabled")
        return self.management(operation, method, path, payload,
                               lambda: self.transport(method, path, payload))


class TrainingJobs:
    """Durable immutable requests plus append-only remote observations.

    A committed start intent always fences replay, including process death before
    the transport call. Status reconciliation is read-only and exact-job scoped;
    a provider-global status response for another job cannot settle this request.
    """

    def __init__(self, path, backend):
        self.path, self.backend = Path(path), backend
        from .run_adoption_store import ModelEvidenceDatabase
        self._database = ModelEvidenceDatabase(self.path, """
            CREATE TABLE jobs(id TEXT PRIMARY KEY, identity TEXT NOT NULL, lineage TEXT NOT NULL);
            CREATE TABLE events(seq INTEGER PRIMARY KEY, job TEXT NOT NULL, body TEXT NOT NULL);
            CREATE TABLE cancellations(job TEXT PRIMARY KEY);
        """)

    def _db(self):
        return self._database.transaction()

    def _event(self, identity, **body):
        with self._db() as db:
            db.execute("INSERT INTO events(job,body) VALUES (?,?)", (identity, canonical(body)))
        return self.get(identity)

    def get(self, identity):
        with self._db() as db:
            row = db.execute("SELECT identity,lineage FROM jobs WHERE id=?", (identity,)).fetchone()
            events = [json.loads(r[0]) for r in db.execute("SELECT body FROM events WHERE job=? ORDER BY seq", (identity,))]
        if row is None:
            raise KeyError(identity)
        result = {"id": identity, "request_digest": row[0], "lineage": json.loads(row[1]), "state": "unknown",
                  "remote_job_id": None, "cancellation": "not-requested", "deletion": "not-requested",
                  "weight_unlearning": "unavailable", "publication": "disabled", "events": events}
        for event in events:
            result.update(event)
        return result

    def start(self, identity, payload, *, lineage):
        self.backend.validate(payload)
        if not isinstance(identity, str) or not identity or not lineage.get("dataset"):
            raise ValueError("Core request and immutable dataset lineage required")
        fingerprint = digest({"payload": payload, "lineage": lineage, "backend": self.backend.version})
        with self._db() as db:
            row = db.execute("SELECT identity FROM jobs WHERE id=?", (identity,)).fetchone()
            if row:
                if row[0] != fingerprint:
                    raise ValueError("Immutable request identity conflict")
                existed = True
            else:
                db.execute("INSERT INTO jobs VALUES (?,?,?)", (identity, fingerprint, canonical(lineage)))
                existed = False
        if existed:
            return self.get(identity)
        try:
            response = self.backend.start(identity, payload)
            remote_id = response.get("job_id")
            status = response.get("status")
            state = "failed" if status == "error" else "accepted" if remote_id and status in {"pending", "queued", "success"} else "unknown"
            return self._event(identity, state=state, remote_job_id=remote_id, raw_status=status)
        except Exception as exc:
            # Dispatch refusals, unknown paid starts and losses remain visible;
            # no body/credentials or private dataset is stored in failure text.
            return self._event(identity, state="unknown", reason=type(exc).__name__)

    def cancel(self, identity):
        record = self.get(identity)
        if not record["remote_job_id"]:
            raise ValueError("Exact provider job ID required; reconcile unknown start")
        if record["state"] in {"completed", "failed", "cancelled"}:
            return record
        with self._db() as db:
            existed = db.execute("SELECT 1 FROM cancellations WHERE job=?", (identity,)).fetchone()
            if not existed:
                db.execute("INSERT INTO cancellations VALUES (?)", (identity,))
        if existed:
            return self.get(identity)
        self._event(identity, cancellation="unknown")
        try:
            response = self.backend.cancel(record["remote_job_id"])
            return self._event(identity, cancellation="unknown" if response.get("status") == "error" else "requested")
        except Exception as exc:
            return self._event(identity, cancellation="unknown", reason=type(exc).__name__)

    def reconcile(self, identity):
        record = self.get(identity)
        if record["state"] in {"completed", "failed", "cancelled"}:
            return record
        try:
            response = self.backend.status()
            if not record["remote_job_id"] or response.get("job_id") != record["remote_job_id"]:
                return self._event(identity, state="unknown", reason="Provider identity not reconciled")
            phase = response.get("phase", response.get("status"))
            state = {"completed": "completed", "error": "failed", "stopped": "cancelled",
                     "training": "running", "loading_model": "running", "loading_dataset": "running",
                     "configuring": "running", "finalizing": "running", "queued": "accepted"}.get(phase, "unknown")
            event = {"state": state, "raw_status": phase}
            if state == "cancelled":
                event["cancellation"] = "confirmed"
            return self._event(identity, **event)
        except Exception as exc:
            return self._event(identity, state="unknown", reason=type(exc).__name__)
