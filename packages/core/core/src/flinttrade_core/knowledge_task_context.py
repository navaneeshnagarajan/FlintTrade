"""Exact-reference full procedure resolver for the real service task dispatcher."""
from __future__ import annotations

import re
from dataclasses import asdict
from datetime import UTC, datetime
from typing import Any
from uuid import UUID, uuid4

from flinttrade_ai.knowledge_store import KnowledgeScope
from flinttrade_ai.memory_ledger import MemoryDomain, MemoryQuery
from flinttrade_core.knowledge_integration import KnowledgeUnavailable, require_knowledge_runtime
from flinttrade_core.service_providers import PermissionState
from flinttrade_core.service_task_contracts import TaskContext, TaskRefused

_SKILL = re.compile(r"skill:([a-z0-9][a-z0-9_-]{0,127})\Z")


class KnowledgeTaskContextResolver:
    """Share the durable knowledge owner; never treat client refs as account ACLs."""

    def __init__(self, app: Any) -> None:
        self.app = app

    def scope(self, actor: str) -> KnowledgeScope | None:
        """Consult server-owned execution authority, never HTTP account/run fields."""
        resolver = self.app.config.get("KNOWLEDGE_SCOPE_RESOLVER")
        scope = resolver(actor) if callable(resolver) else None
        if scope is not None and type(scope) is not KnowledgeScope:
            raise KnowledgeUnavailable("invalid execution scope")
        return scope

    def authorise_version(self, identifier: str, actor: str) -> dict[str, Any]:
        """Read historical stock, or an adaptation only in its exact authorised scope."""
        scope = self.scope(actor)
        value = self._version_in_scope(identifier, scope)
        self.assert_scope(actor, scope)
        return {**value, "context_scope": asdict(scope) if scope is not None else None}

    def assert_scope(self, actor: str, expected: KnowledgeScope | None) -> None:
        """Refuse a changed authority, including an explicit transition to no run."""
        if self.scope(actor) != expected:
            raise TaskRefused("context_changed", 409)

    def _version_in_scope(self, identifier: str, scope: KnowledgeScope | None) -> dict[str, Any]:
        value = require_knowledge_runtime(self.app).store.version(identifier)
        if value["origin"] != "stock":
            if scope is None or value.get("scope") != asdict(scope):
                raise TaskRefused("context_scope_required", 403)
        return value

    def _memory(self, reference: str, scope: KnowledgeScope | None) -> TaskContext:
        if scope is None:
            raise TaskRefused("context_scope_required", 403)
        identity = reference.removeprefix("memory:")
        if str(UUID(identity)) != identity:
            raise ValueError("canonical memory identity required")
        runtime = require_knowledge_runtime(self.app)
        receipt_id = str(uuid4())
        result = runtime.ledger.read_projection().recall(
            receipt_id=receipt_id, decision_id=receipt_id, request_id=receipt_id, decision_time=datetime.now(UTC),
            query=MemoryQuery(domain=MemoryDomain.EPISODIC, event_ids=(identity,),
                              metadata_filters=tuple({**asdict(scope), "kind": "validated-memory"}.items())),
        )
        if len(result.events) != 1:
            raise TaskRefused("context_unavailable", 422)
        event = result.events[0]
        if any(getattr(event.rights.rights, key) is not PermissionState.ALLOWED for key in ("output_use", "retention")):
            raise TaskRefused("context_rights_unavailable", 403)
        return TaskContext(reference, event.digest, str(event.payload["text"]), "private", receipt_id)

    def context_scope(self, context: TaskContext) -> dict[str, str] | None:
        """Read the original durable influence binding, never the newly active run."""
        ledger = require_knowledge_runtime(self.app).ledger
        if context.reference.startswith("memory:"):
            query = ledger.read_projection().replay(context.receipt).receipt.query
            filters = dict(query.metadata_filters)
            return {key: filters[key] for key in ("account_id", "environment", "run_id")}
        scope = ledger.get_event(context.receipt).payload["scope"]
        return dict(scope) if scope is not None else None

    def resolve(self, *, references: tuple[str, ...], actor: str, purpose: str) -> tuple[TaskContext, ...]:
        """Return exactly the requested order or refuse the whole selection."""
        if purpose != "assistant" or not actor:
            raise TaskRefused("context_forbidden", 403)
        try:
            runtime = require_knowledge_runtime(self.app)
            scope = self.scope(actor)
            result = []
            for reference in references:
                if reference.startswith("memory:"):
                    result.append(self._memory(reference, scope))
                    self.assert_scope(actor, scope)
                    continue
                match = _SKILL.fullmatch(reference)
                if match is None:
                    raise TaskRefused("context_reference_invalid", 422)
                name = match[1]
                registry = runtime.skills(scope) if scope else runtime.registry
                body, receipt = registry.context([name])
                version = receipt["skills"][0]["version_id"]
                value = self._version_in_scope(version, scope)
                self.assert_scope(actor, scope)
                classification = "public" if value["origin"] == "stock" else "private"
                result.append(TaskContext(reference, version, body, classification, receipt["receipt_id"]))
            self.assert_scope(actor, scope)
            return tuple(result)
        except KnowledgeUnavailable:
            raise TaskRefused("knowledge_unavailable", 503) from None
        except (KeyError, ValueError):
            raise TaskRefused("context_unavailable", 422) from None

    def validate_send(self, *, contexts: tuple[TaskContext, ...], actor: str, purpose: str,
                      connection: Any, protocol: str) -> None:
        """Recheck current eligibility at each send; do not re-enter the connection store."""
        current = self.resolve(references=tuple(item.reference for item in contexts), actor=actor, purpose=purpose)
        if any((old.version, old.body, old.classification, self.context_scope(old))
               != (new.version, new.body, new.classification, self.context_scope(new))
               for old, new in zip(contexts, current, strict=True)):
            raise TaskRefused("context_changed", 409)
