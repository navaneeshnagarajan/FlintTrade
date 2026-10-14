"""Canonical run learning over the shared immutable knowledge owner.

Local recording is not consent to send or independent evaluation. Only an exact
configured binding may reflect remotely; candidates never become active here.
"""
from __future__ import annotations

import json
from dataclasses import asdict
from datetime import UTC, datetime
from typing import Any
from uuid import uuid4

from flinttrade_ai.knowledge_store import KnowledgeScope
from flinttrade_ai.memory_ledger import MemoryDomain, MemoryEvent

from .evaluation import canonical, digest
from .learning_consent import DatasetRecord, LearningRefused
from .service_providers import RightsResolution

SOURCE = "autonomous-trader.closed-trades:v1"
FIELDS = ("symbol", "exchange", "action", "entry_price", "exit_price", "quantity", "pnl", "pnl_pct",
          "exit_reason", "exit_price_estimated", "timestamp")


class LocalRunLearning:
    """One exact existing producer, no vector fallback or mutable UI selection."""

    def __init__(self, runtime: Any, scope: KnowledgeScope, run: Any) -> None:
        self.runtime, self.scope, self.run = runtime, scope, run
        self.services: Any = None
        self.policy: Any = None

    def __call__(self, rows: list[dict[str, Any]]) -> tuple[DatasetRecord, ...]:
        """Freeze actual producer rows before a model sees them, including estimates."""
        if self.services is not None and self.services.closed:
            raise LearningRefused("learning owner closed")
        producer = json.loads(canonical(self.run.trader.state.closed_trades))
        remaining = list(enumerate(producer))
        records = []
        for row in rows:
            match = next(((i, item) for i, item in remaining if item == row), None)
            if match is None or set(row) != set(FIELDS):
                raise LearningRefused("closed-trade producer mismatch")
            remaining.remove(match)
            ordinal, value = match
            as_of = datetime.fromisoformat(value["timestamp"]).astimezone(UTC)
            dataset = self.policy.control("dataset")[1] if self.policy is not None else None
            rights, parents = RightsResolution(), ()
            recorded_at = as_of
            if dataset:
                try:
                    source = self.policy.rights(dataset["source_rights"], "source")
                    rights, parents = source.rights, (source.event_id,)
                    recorded_at = max(as_of, source.as_of)
                except (ValueError, RuntimeError, KeyError):
                    pass  # Retain local evidence with UNKNOWN rights; no export fallback.
            identity = "closed-trade:" + digest([asdict(self.scope), ordinal, value, rights.digest])
            event = MemoryEvent(identity, MemoryDomain.EPISODIC,
                {**asdict(self.scope), "kind": "closed-trade", "values": value, "ordinal": ordinal,
                 "observation": "producer-record-not-broker-reconciliation"}, recorded_at, (SOURCE,),
                provenance_refs=("agent-run:" + self.scope.run_id,), rights=rights, parent_ids=parents)
            self.runtime.ledger.append(event)
            records.append(DatasetRecord(identity, self.scope.account_id, self.scope.environment, self.scope.run_id,
                                         SOURCE, as_of, "observations", value, event.rights))
        return tuple(records)

    def learning_chat(self, messages: Any, *, purpose: str, records: Any) -> Any:
        """Absence of remote configuration never falls back to ordinary inference."""
        if self.policy is None:
            raise LearningRefused("Local evidence is not remote learning permission")
        return self.policy.chat(messages, purpose=purpose, records=records)

    def persist(self, result: Any, rows: list[dict[str, Any]]) -> list[str]:
        """Retain scoped candidates and actual evidence parents, without activation."""
        records = self(rows)
        parents = tuple(record.record_id for record in records)
        rights = RightsResolution()
        dataset = self.policy.control("dataset")[1] if self.policy is not None else None
        if dataset:
            try:
                output = self.policy.rights(dataset["output_rights"], "output")
                rights = output.rights
                parents += (output.event_id,)
            except (ValueError, RuntimeError, KeyError):
                pass  # Candidate retention is not entitlement or decision influence.
        learning_state = "candidate"
        if result.generation == "remote-model-candidate":
            if not result.learning_receipt or self.policy is None:
                learning_state = "unattested-output"
                rights = RightsResolution()
            else:
                receipt = self.policy.consent().receipt(result.learning_receipt)
                manifest = self.policy.consent().manifest(receipt["batch_id"])
                status = self.policy.consent().status(receipt["grant_id"])
                if (receipt["run_id"] != self.scope.run_id or receipt["purpose"] != "reflection"
                        or {m["record_id"] for m in manifest["members"]} != {r.record_id for r in records}):
                    learning_state = "lineage-changed-after-send"
                    rights = RightsResolution()
                elif status["egress_blocked"]:
                    learning_state = "revoked-after-send"
                    rights = RightsResolution()
        symbols = sorted({row["symbol"] for row in rows})
        lessons = result.recommendations + result.losing_patterns + result.winning_patterns
        candidates = []
        for symbol in symbols:
            for lesson in lessons:
                if not str(lesson).strip():
                    continue
                identity = str(uuid4())
                self.runtime.ledger.append(MemoryEvent(identity, MemoryDomain.EPISODIC,
                    {**asdict(self.scope), "kind": "memory-candidate", "symbol": symbol,
                     "text": "trading lessons: " + str(lesson), "proposer": "reflection",
                     "generation": result.generation, "learning_receipt": result.learning_receipt,
                     "learning_state": learning_state},
                    datetime.now(UTC), (SOURCE,), rights=rights, parent_ids=parents))
                candidates.append(identity)
        # R10's adaptation writer intersects every parent, including new text.
        for name in self.run.trader.selected_skills:
            base = self.runtime.store.resolve(name, run_id=self.scope.run_id, scope=self.scope)
            package = self.runtime.store.version(base)["files"]
            main = name + ".md" if name + ".md" in package else "SKILL.md"
            package[main] += "\n\n## Candidate session lessons\n" + "\n".join(lessons)
            if candidates:
                self.runtime.store.adapt(base, package, proposer="reflection", scope=self.scope,
                                         evidence_ids=tuple(candidates))
        return candidates


class RunLearning(LocalRunLearning):
    """Remote-capable consumer bound to an actual registered run owner."""

    def __init__(self, services: Any, run: Any) -> None:
        from .learning_binding import RunLearningPolicy
        scope = services.runs.scope(run.run_id)
        super().__init__(services.app.config["KNOWLEDGE_RUNTIME"],
                         KnowledgeScope(scope.account, scope.environment, scope.run_id), run)
        self.services = services
        self.policy = RunLearningPolicy(self)
