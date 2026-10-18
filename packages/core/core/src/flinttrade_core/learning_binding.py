"""Exact-run learning configuration and actual-send consent/credential fencing."""
from __future__ import annotations

import hashlib
from dataclasses import asdict
from datetime import datetime
from types import SimpleNamespace
from typing import Any
from uuid import uuid4

import httpx

from flinttrade_ai.learning_dispatch import LearningBinding

from .evaluation import canonical, digest
from .learning_consent import DatasetScope, LearningRefused, Recipient
from .run_adoption import _positive, _text
from .service_providers import PermissionState
from .service_task_protocols import build_request, decode_response, parse_result
from .service_usage_contracts import USAGE_DIMENSIONS, TariffSnapshot, UsageAmounts


class RunLearningPolicy:
    """Policy references canonical rights; HTTP policy cannot manufacture them."""

    def __init__(self, learning: Any) -> None:
        self.learning = learning
        self.owner, self.run = learning.services, learning.run

    def control(self, kind: str) -> tuple[int, dict[str, Any] | None]:
        if kind == "policy":
            return self.owner.dispatcher().ledger.control("run-learning-policy:" + self.run.run_id)
        return self.owner.runs.control(self.run.run_id, "learning-" + kind)

    def consent(self) -> Any:
        from .knowledge_integration import get_learning_consent_ledger
        return get_learning_consent_ledger(self.owner.app)

    def reviewed_rights(self, value: dict[str, Any]) -> Any:
        """Check an explicit operator-reviewed document package, never a checkbox.

        Hashes prove the reviewed bytes, not legal interpretation or provider
        entitlement. This provenance remains labelled operator-supplied.
        """
        from flinttrade_ai.memory_ledger import _rights

        from .run_learning import FIELDS
        from .service_providers import EvidenceUseScope, RightsBasis
        if (set(value) != {"subject", "selection", "rights", "documents", "fields", "review_statement"}
                or value["subject"] not in {"source", "output"} or value["fields"] != list(FIELDS)
                or type(value["documents"]) is not dict or not 1 <= len(value["documents"]) <= 8):
            raise ValueError("Exact scoped document rights review required")
        _text(value["review_statement"])
        selection = value["selection"]
        if type(selection) is not dict or set(selection) != {"connection_id", "connection_revision", "model", "effort"}:
            raise ValueError("Exact selection required")
        self.owner._identity(selection)
        resolved = _rights(value["rights"])
        allowed = {"output_use", "retention", "training_distillation"}
        if (not resolved.grants or any(getattr(resolved.rights, key) is not PermissionState.ALLOWED for key in allowed)
                or any(permission == "allowed" for key, permission in resolved.rights.to_public_dict().items()
                       if key not in allowed)
                or resolved.rights.max_evidence_use_scope is not EvidenceUseScope.ISOLATED_RESEARCH):
            raise ValueError("Only bounded learning use rights may be reviewed here")
        subject = value["subject"]
        expected_kind = "dataset" if subject == "source" else "provider-output"
        expected_id = "closed-trades:" + self.run.run_id if subject == "source" else selection["model"]
        stock_hashes = {fact.sha256 for grant in self.learning.runtime.stock_rights.grants for fact in grant.evidence}
        facts = []
        for grant in resolved.grants:
            if (grant.model_identity is not None or grant.basis not in (
                    {RightsBasis.LICENCE} if subject == "source" else {RightsBasis.PROVIDER_TERMS})):
                raise ValueError("Actual dataset or provider-output terms required")
            for fact in grant.evidence:
                document = value["documents"].get(fact.fact_id)
                if (type(document) is not str or not document.strip() or len(document.encode()) > 16384
                        or fact.subject_kind != expected_kind or fact.identifier != expected_id
                        or fact.sha256 in stock_hashes or hashlib.sha256(document.encode()).hexdigest() != fact.sha256
                        or datetime.fromisoformat(fact.reviewed_at) > self.owner.dispatcher().clock()):
                    raise ValueError("Missing or mismatched reviewed rights document")
                facts.append(fact.fact_id)
        if set(facts) != set(value["documents"]) or len(set(facts)) != len(facts):
            raise ValueError("Exact unique rights documents required")
        return resolved

    def rights(self, identity: str, subject: str, selection: Any = None, *, now: datetime | None = None) -> Any:
        """Validate current scoped rights, optionally using a caller-pinned clock.

        Exact readback supplies time from established healthy custody. Other
        consumers retain their existing lazy owner resolution.
        """
        from .run_learning import FIELDS, SOURCE
        runtime = self.learning.runtime
        runtime.store._require_eligible(identity)
        event = runtime.ledger.get_event(identity)
        current = self.control("rights:" + subject)[1]
        if not current or current["event_id"] != identity:
            raise ValueError("Rights review is no longer current")
        value = event.to_dict()["payload"]
        if (value.get("kind") != "learning-rights" or value.get("scope") != asdict(self.learning.scope)
                or value.get("subject") != subject or value.get("source") != SOURCE
                or value.get("fields") != list(FIELDS) or value.get("purpose") != "reflection"
                or selection is not None and value.get("selection") != selection
                or event.as_of > (now if now is not None else self.owner.dispatcher().clock())
                or any(getattr(event.rights.rights, key) is not PermissionState.ALLOWED
                       for key in ("output_use", "retention", "training_distillation"))):
            raise ValueError("Exact scoped canonical rights evidence required")
        return event

    def dataset(self, value: dict[str, Any], revision: int) -> DatasetScope:
        from .run_learning import FIELDS, SOURCE
        if set(value) != {"source_rights", "output_rights", "as_of_start", "as_of_end"}:
            raise ValueError("Exact learning dataset fields required")
        for subject in ("source", "output"):
            self.rights(value[subject + "_rights"], subject)
        scope = self.learning.scope
        return DatasetScope("closed-trades:" + scope.run_id, str(revision), (scope.account_id,), (scope.environment,),
            (scope.run_id,), (SOURCE,), FIELDS, ("observations",), "reflection-prompt:v1",
            datetime.fromisoformat(value["as_of_start"]), datetime.fromisoformat(value["as_of_end"]))

    def policy(self, value: dict[str, Any]) -> tuple[dict[str, Any], Recipient]:
        fields = {"selection", "reservation", "controls", "controls_evidence", "principal", "region",
                  "terms_revision", "valid_until", "max_output_tokens", "timeout_seconds"}
        if set(value) != fields:
            raise ValueError("Exact learning workload fields required")
        selection = value["selection"]
        if type(selection) is not dict or set(selection) != {"connection_id", "connection_revision", "model", "effort"}:
            raise ValueError("Exact learning selection required")
        _, admission = self.owner._identity(selection)
        if "private" not in admission["privacy"]["classifications"]:
            raise ValueError("Private learning destination not qualified")
        if (set(value["reservation"]) != set(USAGE_DIMENSIONS) or set(value["controls"]) != set(USAGE_DIMENSIONS)
                or type(value["max_output_tokens"]) is not int or value["max_output_tokens"] <= 0
                or _positive(value["valid_until"]) <= self.owner.now()
                or _positive(value["timeout_seconds"]) > 120):
            raise ValueError("All numeric learning limits required")
        reservation = UsageAmounts(**value["reservation"])
        if (reservation.requests != 1 or reservation.concurrency != 1 or reservation.bytes <= 0
                or reservation.output_tokens < value["max_output_tokens"] or reservation.input_tokens <= 0
                or any(value["controls"][k] not in {"hard-local", "hard-provider", "not-applicable"}
                       or value["controls"][k] == "not-applicable" and getattr(reservation, k) for k in USAGE_DIMENSIONS)):
            raise ValueError("Qualified complete reservation and controls required")
        for key in ("principal", "region", "terms_revision", "controls_evidence"):
            _text(value[key])
        if value["region"] != admission["privacy"]["region"]:
            raise ValueError("Recipient region changed")
        dataset = self.control("dataset")[1]
        if dataset is None:
            raise ValueError("Canonical learning dataset required")
        for subject in ("source", "output"):
            self.rights(dataset[subject + "_rights"], subject, selection)
        connection = self.owner.dispatcher()._connection(selection["connection_id"], selection["connection_revision"])
        endpoint, _, _ = build_request(connection, admission, {"prompt": "", "max_output_tokens": value["max_output_tokens"]},
                                       selection["effort"], "")
        version = connection.secret_version
        if version is None or not version.present:
            raise ValueError("Destination credential unavailable")
        recipient = Recipient(connection.ref, selection["connection_revision"], value["principal"],
            f"{version.store_incarnation}:{version.binding_id}:{version.generation}", connection.auth_mode, endpoint,
            value["region"], value["terms_revision"], connection.model, admission["model_revision"], "chat",
            (admission["downstream"],) if admission["downstream"] else ())
        return admission, recipient

    def validate(self, action: str, value: dict[str, Any], revision: int) -> dict[str, Any]:
        if action == "learning-rights":
            resolved = self.reviewed_rights(value)
            return {"rights_digest": resolved.digest, "policy_provenance": "operator-reviewed-document-evidence"}
        if action == "learning-dataset":
            return {"scope": self.dataset(value, revision + 1).to_dict()}
        if action == "learning-policy":
            admission, recipient = self.policy(value)
            return {"recipient": recipient.to_dict(), "admission_digest": digest(admission)}
        if action != "learning-binding" or set(value) != {"grant_id"}:
            raise ValueError("Unknown learning action")
        configured = self.control("policy")[1]
        if configured is None:
            raise ValueError("Learning policy required")
        _, recipient = self.policy(configured["value"])
        dataset_revision, dataset = self.control("dataset")
        status = self.consent().status(_text(value["grant_id"]))
        grant = status["grant"]
        if (status["egress_blocked"] or grant["scope"] != self.dataset(dataset, dataset_revision).to_dict()
                or grant["recipient"] != recipient.to_dict() or grant["purpose"] != "reflection"
                or grant["operations"] != ["chat"] or grant["approver"] != self.owner.runs.scope(self.run.run_id).actor):
            raise ValueError("Exact current learning grant required")
        return {"grant_id": value["grant_id"], "policy_digest": digest(configured), "dataset_revision": dataset_revision}

    def configure(self, action: str, value: dict[str, Any], revision: int) -> dict[str, Any]:
        result = self.validate(action, value, revision)
        if action == "learning-rights":
            from flinttrade_ai.memory_ledger import MemoryDomain, MemoryEvent

            from .run_learning import SOURCE
            identity = str(uuid4())
            event = MemoryEvent(identity, MemoryDomain.EXPERIMENT,
                {"kind": "learning-rights", "scope": asdict(self.learning.scope), "source": SOURCE,
                 "purpose": "reflection", **value, **result}, self.owner.dispatcher().clock(), (SOURCE,),
                rights=self.reviewed_rights(value))
            self.learning.runtime.ledger.append(event)
            result = {"event_id": identity, **result}
            self.owner.runs.configure(self.run.run_id, "learning-rights:" + value["subject"], result,
                                      expected_revision=revision)
            return result
        stored = {"value": value, **result} if action == "learning-policy" else result if action == "learning-binding" else value
        if action == "learning-policy":
            self.owner.dispatcher().ledger.configure_control("run-learning-policy:" + self.run.run_id,
                                                            stored, expected_revision=revision)
        else:
            self.owner.runs.configure(self.run.run_id, action, stored, expected_revision=revision)
        return result

    def resolve_permission(self, *, actor: str, scope: Any, recipient: Any, purpose: str, operations: Any) -> Any:
        try:
            if (actor != self.owner.runs.scope(self.run.run_id).actor or purpose != "reflection"
                    or operations != ("chat",)):
                return None
            revision, dataset = self.control("dataset")
            configured = self.control("policy")[1]
            _, current = self.policy(configured["value"])
            if scope != self.dataset(dataset, revision) or recipient != current:
                return None
            return scope, current, self.rights(dataset["source_rights"], "source", configured["value"]["selection"]).rights
        except (ValueError, TypeError, KeyError, RuntimeError):
            return None

    def _rights_check(self, manifest: dict[str, Any], records: Any, selection: Any) -> bool:
        dataset = self.control("dataset")[1]
        rights = self.rights(dataset["source_rights"], "source", selection).rights
        for member, record in zip(manifest["members"], records, strict=True):
            event = self.learning.runtime.ledger.get_event(record.record_id)
            if (member["record_id"] != record.record_id or member["rights_hash"] != rights.digest
                    or event.rights.digest != rights.digest or event.to_dict()["payload"]["values"] != dict(record.values)
                    or any(member[k] != v for k, v in {"account": self.learning.scope.account_id,
                        "environment": self.learning.scope.environment, "run": self.run.run_id}.items())):
                return False
        return True

    def chat(self, messages: Any, *, purpose: str, records: Any) -> Any:
        if purpose != "reflection":
            raise LearningRefused("Only the configured reflection purpose is supported")
        with self.owner.lock:
            binding = self.control("binding")[1]
            configured = self.control("policy")[1]
            if (not binding or not configured or digest(configured) != binding["policy_digest"]
                    or self.control("dataset")[0] != binding["dataset_revision"]):
                raise LearningRefused("Exact current run learning binding required")
            self.run.adapter.validate_session()
            value = configured["value"]
            admission, recipient = self.policy(value)
            if digest(admission) != configured["admission_digest"]:
                raise LearningRefused("Learning admission changed")
            dataset_revision, dataset = self.control("dataset")
            scope = self.dataset(dataset, dataset_revision)
            selection = value["selection"]
            dispatcher = self.owner.dispatcher()
            with dispatcher.store.dispatch_binding(recipient.connection, expected_etag=recipient.connection_revision) as (connection, secret):
                url, headers, payload = build_request(connection, admission,
                    {"prompt": canonical([{"role": m.role, "content": m.content} for m in messages]),
                     "max_output_tokens": value["max_output_tokens"]}, selection["effort"], secret)
                attempt_id = str(uuid4())
                exact = LearningBinding(self.consent(), binding["grant_id"], scope, recipient,
                    # The exact revision's metadata and credential are held by
                    # dispatch_binding until I/O ends; do not re-enter its lock.
                    lambda: recipient, lambda manifest: self._rights_check(manifest, records, selection),
                    lambda wire: UsageAmounts(**value["reservation"]), TariffSnapshot.from_dict(admission["tariff"]),
                    value["controls"], value["controls_evidence"], self.run.run_id, "reflection:" + self.run.run_id)
                def send(wire: bytes) -> Any:
                    if len(wire) > value["reservation"]["input_tokens"]:
                        raise LearningRefused("Conservative input bound exceeded")
                    with httpx.Client(transport=dispatcher.transport, trust_env=False, follow_redirects=False,
                                      timeout=value["timeout_seconds"]) as client:
                        response = client.post(url, headers=headers, content=wire)
                        response.raise_for_status()
                        return decode_response(response.content, admission["protocol"])
                raw = exact.dispatch(purpose=purpose, records=records, endpoint=url, payload=payload,
                                     send=send, attempt_id=attempt_id)
                output, _usage, _identity = parse_result(raw, admission)
                return SimpleNamespace(content=output, error="", learning_receipt=attempt_id)
