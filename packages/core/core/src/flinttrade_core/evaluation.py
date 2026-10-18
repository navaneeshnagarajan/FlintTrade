"""Immutable experiments and sealed evaluation owned by core.

No default qualification policy. Trusted bootstrap installs independent graders
and freezes suites; HTTP callers cannot install graders, change criteria or read
labels. This is evidence ownership, not a training/data-export permission store.
"""
from __future__ import annotations

import hashlib
import json
import math
import sqlite3
from contextlib import nullcontext
from pathlib import Path
from uuid import uuid4


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False)


def digest(value):
    return hashlib.sha256(canonical(value).encode()).hexdigest()


class EvaluationStore:
    """Create/begin/finish/read immutable evidence; only configured graders score.

    A begun trial with no terminal evidence is unknown across all readers. An
    interrupted final access stays consumed, so recovery cannot reveal labels
    to another adaptively chosen candidate. Grader exceptions remain evidence.
    """

    def __init__(self, path, *, graders=None):
        self.path = Path(path)
        self._graders = dict(graders or {})
        self.admission_owner = None
        from .run_adoption_store import ModelEvidenceDatabase
        self._database = ModelEvidenceDatabase(self.path, """
            CREATE TABLE experiments(id TEXT PRIMARY KEY, manifest TEXT NOT NULL);
            CREATE TABLE trials(id TEXT PRIMARY KEY, experiment TEXT NOT NULL);
            CREATE TABLE outcomes(trial TEXT PRIMARY KEY, status TEXT NOT NULL, evidence TEXT NOT NULL);
            CREATE TABLE suites(id TEXT PRIMARY KEY, payload TEXT NOT NULL);
            CREATE TABLE accesses(suite TEXT PRIMARY KEY, trial TEXT NOT NULL);
        """)

    def _db(self):
        return self._database.transaction()

    def create(self, manifest):
        required = {"data", "model", "skill", "strategy", "config", "evaluator", "producer", "role"}
        if manifest.get("schema_version") != 1 or any(not manifest.get(key) for key in required):
            raise ValueError("Versioned data/model/skill/strategy/config/evaluator manifest required")
        identity = uuid4().hex
        with self._db() as db:
            db.execute("INSERT INTO experiments VALUES (?,?)", (identity, canonical(manifest)))
        return identity

    def begin(self, experiment):
        identity = uuid4().hex
        with self._db() as db:
            if not db.execute("SELECT 1 FROM experiments WHERE id=?", (experiment,)).fetchone():
                raise KeyError(experiment)
            db.execute("INSERT INTO trials VALUES (?,?)", (identity, experiment))
        return identity

    def finish(self, trial, *, status, evidence):
        if status not in {"completed", "partial", "failed", "unknown", "cancelled"}:
            raise ValueError("Invalid terminal status")
        with self._db() as db:
            if not db.execute("SELECT 1 FROM trials WHERE id=?", (trial,)).fetchone():
                raise KeyError(trial)
            try:
                db.execute("INSERT INTO outcomes VALUES (?,?,?)", (trial, status, canonical(evidence)))
            except sqlite3.IntegrityError as exc:
                raise ValueError("Trial is terminal and immutable") from exc
        return self.trial(trial)

    def trial(self, identity):
        with self._db() as db:
            row = db.execute("SELECT experiment FROM trials WHERE id=?", (identity,)).fetchone()
            outcome = db.execute("SELECT status,evidence FROM outcomes WHERE trial=?", (identity,)).fetchone()
        if row is None:
            raise KeyError(identity)
        return {"id": identity, "experiment_id": row[0], "status": outcome[0] if outcome else "unknown",
                "evidence": json.loads(outcome[1]) if outcome else {"reason": "No terminal evidence; do not replay"}}

    def experiment(self, identity):
        with self._db() as db:
            row = db.execute("SELECT manifest FROM experiments WHERE id=?", (identity,)).fetchone()
            trials = [r[0] for r in db.execute("SELECT id FROM trials WHERE experiment=? ORDER BY rowid", (identity,))]
        if row is None:
            raise KeyError(identity)
        return {"id": identity, "manifest": json.loads(row[0]), "trials": trials}

    def freeze(self, identity, partitions, *, evaluator, policy):
        """Trusted configuration operation. Partition rows never enter read models."""
        if not policy or not policy.get("thresholds") or not policy.get("budgets"):
            raise ValueError("Explicit qualification policy and budgets required")
        if type(policy["budgets"].get("max_trials")) is not int or policy["budgets"]["max_trials"] < 1:
            raise ValueError("Explicit positive max_trials policy required")
        for bounds in policy["thresholds"].values():
            if not bounds or set(bounds) - {"min", "max"} or not all(
                type(v) in (int, float) and math.isfinite(v) for v in bounds.values()
            ):
                raise ValueError("Invalid numeric policy")
        seen_ids, seen_groups = set(), set()
        last_end = None
        for split in ("development", "calibration", "final"):
            rows = partitions.get(split)
            if not rows:
                raise ValueError("All frozen partitions required")
            ids = {r["id"] for r in rows}
            groups = {r["group"] for r in rows}
            if len(ids) != len(rows) or ids & seen_ids or groups & seen_groups:
                raise ValueError("Duplicate/related cases cross partitions")
            if last_end is not None and min(r["as_of"] for r in rows) <= last_end:
                raise ValueError("Overlapping chronological label horizons")
            last_end = max(r.get("label_end", r["as_of"]) for r in rows)
            seen_ids |= ids
            seen_groups |= groups
        payload = {"partitions": partitions, "evaluator": evaluator, "policy": policy}
        with self._db() as db:
            try:
                db.execute("INSERT INTO suites VALUES (?,?)", (identity, canonical(payload)))
            except sqlite3.IntegrityError as exc:
                raise ValueError("Suite is frozen") from exc

    def suite(self, identity):
        with self._db() as db:
            row = db.execute("SELECT payload FROM suites WHERE id=?", (identity,)).fetchone()
            access = db.execute("SELECT trial FROM accesses WHERE suite=?", (identity,)).fetchone()
        if row is None:
            raise KeyError(identity)
        payload = json.loads(row[0])
        return {"id": identity, "digest": digest(payload), "evaluator": payload["evaluator"],
                "policy": payload["policy"], "consumed_by": access[0] if access else None,
                "partitions": {k: {"count": len(v), "digest": digest(v)} for k, v in payload["partitions"].items()}}

    def score_final(self, suite, trial, *, prospective):
        manifest = self.experiment(self.trial(trial)["experiment_id"])["manifest"]
        if not prospective or prospective.get("candidate") != manifest or not prospective.get("receipt"):
            raise ValueError("Exact frozen-candidate prospective evidence required")
        admission = self.admission_owner.evaluation_fence(suite, trial) if self.admission_owner is not None else nullcontext()
        # Revalidate authenticated scope under the run fence at the durable final
        # claim, then release before grading so evaluation cannot starve protection.
        with admission, self._db() as db:
            row = db.execute("SELECT payload FROM suites WHERE id=?", (suite,)).fetchone()
            if row is None:
                raise KeyError(suite)
            payload = json.loads(row[0])
            grader = self._graders.get(payload["evaluator"])
            if grader is None or payload["evaluator"] != manifest["evaluator"] or manifest["producer"] == payload["evaluator"]:
                raise ValueError("Independent exact evaluator required")
            if db.execute("SELECT 1 FROM outcomes WHERE trial=?", (trial,)).fetchone():
                raise ValueError("Trial is terminal")
            experiment = db.execute("SELECT experiment FROM trials WHERE id=?", (trial,)).fetchone()[0]
            count = db.execute("SELECT count(*) FROM trials WHERE experiment=?", (experiment,)).fetchone()[0]
            if count > payload["policy"]["budgets"]["max_trials"]:
                raise ValueError("Trial budget exhausted")
            try:
                db.execute("INSERT INTO accesses VALUES (?,?)", (suite, trial))
            except sqlite3.IntegrityError as exc:
                raise ValueError("Final set already consumed") from exc
        try:
            candidate_digest = digest(manifest)
            suite_digest = digest(payload)
            metrics = grader(manifest, payload["partitions"]["final"])
            if digest(manifest) != candidate_digest or digest(payload) != suite_digest:
                raise ValueError("Evaluator mutated frozen identity or observations")
            qualified = True
            for name, bounds in payload["policy"]["thresholds"].items():
                value = metrics.get(name)
                if type(value) not in (int, float) or not math.isfinite(value):
                    raise ValueError("Required metric missing/non-finite")
                qualified &= ("min" not in bounds or value >= bounds["min"]) and ("max" not in bounds or value <= bounds["max"])
            # Release only policy-named scalar measurements, never debug rows or labels.
            metrics = {name: metrics[name] for name in payload["policy"]["thresholds"]}
            return self.finish(trial, status="completed", evidence={"metrics": metrics, "qualified": qualified,
                "suite": suite, "suite_digest": digest(payload), "candidate": manifest, "prospective": prospective})
        except Exception as exc:
            return self.finish(trial, status="failed", evidence={"stage": "independent_grading", "reason": type(exc).__name__, "qualified": False})
