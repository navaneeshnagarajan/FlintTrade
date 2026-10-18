"""Core-owned planned adoption; never outage repair, arming or order replay.

Integration requires the *existing* run owner, not a second execution ledger.
Its fence must serialize grants/revocation, risk/config changes, order/fill
frontiers, proposal admission and binding changes. Provider adapters must stage
without unloading protection. Unsloth's global selector does not qualify.
"""
from __future__ import annotations

import json
import time
from dataclasses import asdict, dataclass, replace
from pathlib import Path

from .evaluation import canonical


@dataclass(frozen=True)
class RunState:
    run_id: str
    role: str
    account: str
    environment: str
    generation: int
    config_generation: int
    risk_fingerprint: str
    frontier: str
    protection_id: str
    protection_verified: bool
    binding: str
    entries_armed: bool


class ArtifactActivation:
    """Idempotent adopt/read/reconcile interface over a run-owned transaction.

    authority(state, candidate) reads a current exact grant; qualification reads
    independently owned frozen/prospective evidence. Neither is supplied by an
    HTTP request. A missing adapter/grant/policy refuses; no defaults are minted.
    bind(candidate, expected_state) conditionally updates only the role binding
    and generation. It must never change fills, orders, P&L, reservations or arm.
    """

    def __init__(self, path, *, runs, serving, authority, qualification, clock=time.time):
        self.path = Path(path)
        self.runs, self.serving = runs, serving
        self.authority, self.qualification, self.clock = authority, qualification, clock
        from .run_adoption_store import ModelEvidenceDatabase
        self._database = ModelEvidenceDatabase(self.path, """
            CREATE TABLE transitions(id TEXT PRIMARY KEY, request TEXT NOT NULL);
            CREATE TABLE events(seq INTEGER PRIMARY KEY, transition_id TEXT NOT NULL, body TEXT NOT NULL);
        """)

    def _db(self):
        return self._database.transaction()

    def get(self, identity):
        with self._db() as db:
            row = db.execute("SELECT request FROM transitions WHERE id=?", (identity,)).fetchone()
            events = [json.loads(r[0]) for r in db.execute(
                "SELECT body FROM events WHERE transition_id=? ORDER BY seq", (identity,))]
        if row is None:
            raise KeyError(identity)
        result = {"id": identity, "request": json.loads(row[0]), "status": "unknown", "events": events}
        for event in events:
            result.update(event)
        return result

    def _event(self, identity, **body):
        with self._db() as db:
            db.execute("INSERT INTO events(transition_id,body) VALUES (?,?)", (identity, canonical(body)))
        return self.get(identity)

    def _evidence(self, state, candidate):
        if not state.protection_verified or not state.protection_id or not state.frontier:
            raise ValueError("Verified protection and reconciliation frontier required")
        grant, evidence = self.authority(state, candidate), self.qualification(candidate)
        if not grant or not evidence:
            raise ValueError("Current grant and independent qualification required")
        for key in ("run_id", "role", "account", "environment", "risk_fingerprint"):
            if grant.get(key) != getattr(state, key):
                raise ValueError("Grant scope/risk mismatch")
        if (not grant.get("id") or type(grant.get("generation")) is not int
                or grant.get("valid_until", 0) <= self.clock()
                or grant.get("operation") != "planned-adoption"):
            raise ValueError("Grant expired/revoked or operation outside adoption envelope")
        if (evidence.get("candidate") != candidate or evidence.get("role") != state.role
                or evidence.get("qualified") is not True or evidence.get("independent") is not True
                or not all(evidence.get(k) for k in ("policy", "prospective", "identity", "receipt", "identity_scope"))
                or evidence.get("valid_until", 0) <= self.clock()
                or grant.get("identity_scope") != evidence["identity_scope"]):
            raise ValueError("Exact independent, prospective and role-specific qualification required")
        return grant, evidence

    def adopt(self, identity, *, run_id, role, candidate, expected_generation, kind="adopt"):
        if (not all(isinstance(v, str) and v for v in (identity, run_id, role, candidate))
                or type(expected_generation) is not int or kind not in {"adopt", "rollback"}):
            raise ValueError("Exact adoption identity/generation required")
        request = {"run_id": run_id, "role": role, "candidate": candidate,
                   "expected_generation": expected_generation, "kind": kind}
        with self._db() as db:
            row = db.execute("SELECT request FROM transitions WHERE id=?", (identity,)).fetchone()
            if row and row[0] != canonical(request):
                raise ValueError("Immutable adoption identity conflict")
            if row is None:
                db.execute("INSERT INTO transitions VALUES (?,?)", (identity, canonical(request)))
        if row:
            return self.get(identity)  # No selection replay, even for unknown requests.
        committing = False
        try:
            if self.serving.staging_preserves_incumbent is not True:
                raise ValueError("Destructive selector/restart requires separate approval and qualification")
            state = self.runs.snapshot(run_id, role)
            if (state.run_id, state.role, state.generation) != (run_id, role, expected_generation):
                raise ValueError("Stale run generation")
            grant, evidence = self._evidence(state, candidate)
            if kind == "rollback" and not self._retained(run_id, role, candidate):
                raise ValueError("Rollback target not retained")
            handle = self.serving.stage(candidate, state)
            if self.serving.identity(handle) != evidence["identity"]:
                raise ValueError("Staged identity mismatch")
            with self.runs.fence(run_id, role):
                current = self.runs.snapshot(run_id, role)
                if current != state:
                    raise ValueError("Run config/risk/order-fill/protection frontier changed")
                current_grant, current_evidence = self._evidence(current, candidate)
                if current_grant != grant or current_evidence != evidence:
                    raise ValueError("Grant or qualification generation changed")
                self._event(identity, status="unknown", phase="commit_intent", prior=asdict(state),
                            grant=grant, qualification=evidence)
                committing = True
                self.runs.bind(candidate, state)
                self.serving.commit(handle, run_id, role)
                bound = self.runs.snapshot(run_id, role)
                if (bound != replace(state, binding=candidate, generation=expected_generation + 1)
                        or self.serving.current(run_id, role) != evidence["identity"]):
                    raise ValueError("Serving/protection readback not verified")
                return self._event(identity, status="completed", phase="verified", bound=asdict(bound))
        except Exception as exc:
            state = self.runs.snapshot(run_id, role)
            if committing or kind == "rollback" or not state.protection_verified:
                self.runs.pause_entries(run_id, role)
            return self._event(identity, status="unknown" if committing else "refused", reason=str(exc),
                               protection_verified=state.protection_verified,
                               unresolved_exposure=not state.protection_verified)

    def _retained(self, run_id, role, candidate):
        with self._db() as db:
            rows = db.execute("SELECT t.request,e.body FROM transitions t JOIN events e ON t.id=e.transition_id")
            for request, body in rows:
                req, event = json.loads(request), json.loads(body)
                if req["run_id"] == run_id and req["role"] == role and event.get("prior", {}).get("binding") == candidate:
                    return True
        return False

    def reconcile(self, identity):
        """Read actual serving/binding; never rerun a lost select or re-arm."""
        record = self.get(identity)
        if record["status"] != "unknown":
            return record
        request = record["request"]
        run_id, role = request["run_id"], request["role"]
        with self.runs.fence(run_id, role):
            self.runs.pause_entries(run_id, role)
            state = self.runs.snapshot(run_id, role)
            try:
                _, evidence = self._evidence(state, request["candidate"])
                if ("prior" not in record or state.binding != request["candidate"]
                        or state.generation != request["expected_generation"] + 1
                        or self.serving.current(run_id, role) != evidence["identity"]):
                    return record
                return self._event(identity, status="completed", phase="reconciled_no_rearm", bound=asdict(state))
            except Exception:
                return record

    def check(self, run_id, role):
        """Invalidate eligibility and pause entries, never fail over on drift."""
        try:
            state = self.runs.snapshot(run_id, role)
            _, evidence = self._evidence(state, state.binding)
            valid = self.serving.current(run_id, role) == evidence["identity"]
        except Exception:
            valid = False
        if not valid:
            self.runs.pause_entries(run_id, role)
        return valid

    def accepts(self, run_id, role, *, generation, candidate):
        """Admission must call under the same run fence; dispatched intents survive."""
        with self.runs.fence(run_id, role):
            state = self.runs.snapshot(run_id, role)
            return (state.entries_armed and state.generation == generation and state.binding == candidate
                    and self.check(run_id, role))
