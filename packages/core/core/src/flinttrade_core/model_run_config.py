"""Operator-confirmed exact-run policy, not self-grading or entitlement evidence."""
from __future__ import annotations

import hashlib
import re
import secrets
import time
from copy import deepcopy
from functools import wraps
from typing import Any
from uuid import UUID

from flask import Blueprint, current_app, jsonify, request

from .evaluation import digest
from .model_control_auth import ModelControlDenied, _body, principal
from .run_adoption import _positive, _text
from .service_connection_store import ConnectionRevisionConflict
from .service_usage import UsageConflict

model_run_config_bp = Blueprint("model_run_config", __name__)
PREFIX = "/v1/model-runs/<run_id>/configuration"
PROVENANCE = "operator-supplied-not-measured-entitlement"


class ConfigurationConflict(ValueError):
    """A preview expired, changed or was consumed; obtain a fresh preview."""


class ModelRunConfiguration:
    """Bounded one-shot confirmations; durable policy stays in the real owners."""

    def __init__(self, owner: Any) -> None:
        self.owner = owner
        self.pending: dict[str, tuple[float, str, dict[str, Any]]] = {}

    def scope(self, run_id: str, who: Any) -> dict[str, Any]:
        scope = self.owner.runs.scope(run_id)
        if self.owner.closed or scope.actor != who.actor_ref:
            raise ModelControlDenied("run_scope_not_owned")
        return vars(scope)

    def read(self, run_id: str, who: Any) -> dict[str, Any]:
        scope = self.scope(run_id, who)
        controls = {}
        for key in ("access", "grant:reasoning", "learning-dataset", "learning-policy", "learning-binding"):
            revision, value = (self.owner.learning(run_id).policy.control("policy") if key == "learning-policy"
                               else self.owner.runs.control(run_id, key))
            controls[key] = {"revision": revision, "value": value}
        return {"scope": scope, "controls": controls, "policy_provenance": PROVENANCE}

    @staticmethod
    def selector(action: str, value: dict[str, Any]) -> dict[str, str] | None:
        """Project a proposal's exact-read selector without validating its values.

        Args:
            action: Configuration action naming the control family.
            value: Proposal fields; required identity fields must be present.

        Returns:
            The selected identity fields, or None for a general control.
            Exact reads validate literal tokens separately before any lookup.
        """
        if action == "learning-rights":
            return {"action": action, "subject": value["subject"]}
        if action == "candidate":
            return {"action": action, "trial": value["candidate"]}
        if action == "evaluation":
            return {"action": action, "trial": value["trial"], "suite": value["suite"]}
        if action == "training-backend":
            return {"action": action, "connection_id": value["connection_id"]}
        return None

    @staticmethod
    def _validate_selector(run_id: str, selector: dict[str, str]) -> None:
        if not re.fullmatch(r"[A-Za-z0-9_.:-]{1,128}", run_id):
            raise ValueError("Exact run token required")
        fields = {"learning-rights": {"action", "subject"}, "candidate": {"action", "trial"},
                  "evaluation": {"action", "trial", "suite"}, "training-backend": {"action", "connection_id"}}
        if set(selector) != fields.get(selector.get("action")):
            raise ValueError("Exact control selector required")
        if selector["action"] == "training-backend":
            if str(UUID(selector["connection_id"])) != selector["connection_id"]:
                raise ValueError("Exact connection UUID required")
        elif selector["action"] == "learning-rights":
            if selector["subject"] not in {"source", "output"}:
                raise ValueError("Exact rights subject required")
        elif any(type(value) is not str or not re.fullmatch(r"[A-Za-z0-9_.:-]{1,128}", value)
                 for key, value in selector.items() if key != "action"):
            raise ValueError("Exact immutable token required")

    def _current(self, run_id: str, who: Any) -> dict[str, Any]:
        from .execution_session import execution_custody
        scope = self.scope(run_id, who)
        owned = self.owner.runs.owner(run_id)
        run = owned.supervisor.run
        if (run is None or run is not owned.producer or run.run_id != run_id or run.cleanup_complete
                or run.evidence_failed or run.adapter is None or run.adapter._closed
                or execution_custody(owned.identity, owned.store, owned.sandbox) != owned.custody):
            raise ModelControlDenied("run_producer_unavailable")
        run.adapter.validate_session()
        current = principal()
        if current.actor_ref != who.actor_ref or current.session_binding != who.session_binding:
            raise ModelControlDenied("operator_session_changed")
        return scope

    @staticmethod
    def _control(revision: Any, value: Any) -> None:
        if (type(revision) is not int or revision < 0 or (revision == 0) != (value is None)
                or value is not None and type(value) is not dict):
            raise RuntimeError("Exact control custody unavailable")

    def _rights(self, run_id: str, selector: dict[str, str]) -> tuple[Any, Any, Any]:
        learning = self.owner._learning.get(run_id)
        if learning is None or learning.runtime is not self.owner.app.config.get("KNOWLEDGE_RUNTIME"):
            raise RuntimeError("Learning custody unavailable")
        revision, stored = learning.policy.control("rights:" + selector["subject"])
        self._control(revision, stored)
        value, identity = None, None
        if stored is None:
            # Even unissued needs established healthy evidence custody.
            try:
                learning.runtime.ledger.get_event("unissued-rights:" + run_id + ":" + selector["subject"])
            except KeyError:
                pass
        else:
            dispatcher = self._dispatcher()
            dispatcher.ledger.check_available()
            event = learning.policy.rights(stored["event_id"], selector["subject"], now=dispatcher.clock())
            payload = event.to_dict()["payload"]
            if stored != {"event_id": event.event_id, "rights_digest": event.rights.digest,
                          "policy_provenance": "operator-reviewed-document-evidence"}:
                raise RuntimeError("Rights control evidence mismatch")
            value = {key: payload[key] for key in ("subject", "selection", "fields")}
            value["rights_digest"] = digest(payload["rights"])
            value["document_digests"] = {key: hashlib.sha256(text.encode()).hexdigest()
                                         for key, text in payload["documents"].items()}
            value["review_statement_digest"] = hashlib.sha256(payload["review_statement"].encode()).hexdigest()
            identity = {"event_id": event.event_id, "rights_digest": event.rights.digest}
            dispatcher.ledger.check_available()
            if self._dispatcher() is not dispatcher:
                raise RuntimeError("Usage owner replaced")
        return revision, value, identity

    def _dispatcher(self) -> Any:
        dispatcher = self.owner.app.config.get("SERVICE_TASK_DISPATCHER")
        if dispatcher is None:
            raise RuntimeError("Established usage custody unavailable")
        return dispatcher

    def _immutable(self, scope: dict[str, Any], selector: dict[str, str]) -> tuple[Any, Any, Any]:
        store = self.owner.app.config.get("EVALUATION_STORE")
        if store is None:
            raise RuntimeError("Established evaluation custody unavailable")
        trial = store.trial(selector["trial"])
        manifest = store.experiment(trial["experiment_id"])["manifest"]
        if manifest.get("control_scope") != scope:
            raise ModelControlDenied("evaluation_scope_not_owned")
        action = selector["action"]
        revision, stored = self._dispatcher().ledger.control_snapshot("run-" + action + ":" + selector["trial"])
        self._control(revision, stored)
        if revision not in {0, 1}:
            raise RuntimeError("Immutable control revision invalid")
        identity = {"trial": selector["trial"], "experiment_id": trial["experiment_id"],
                    "manifest_digest": digest(manifest)}
        value = None
        if action == "candidate":
            identity["evidence_digest"] = digest(trial)
            identity["serving_identity"] = self.owner._identity(manifest["model"])[0]
            if stored is not None:
                if set(stored) != {"selection", "role", "identity_scope", "valid_until", "deadline_ms",
                                   "max_output_tokens", "readiness_ttl_seconds", "identity", "model_revision"}:
                    raise RuntimeError("Candidate control fields unavailable")
                self.owner._qualified(selector["trial"], stored)
                value = {"candidate": selector["trial"], **stored}
        else:
            suite = store.suite(selector["suite"])
            if (suite["evaluator"] != manifest["evaluator"] or manifest["evaluator"] == manifest["producer"]
                    or suite["consumed_by"] not in {None, selector["trial"]}):
                raise ModelControlDenied("evaluation_scope_not_owned")
            identity["suite_digest"] = suite["digest"]
            if stored is not None:
                expected = {"suite": selector["suite"], "suite_digest": suite["digest"],
                            "manifest_digest": identity["manifest_digest"]}
                if stored != expected:
                    raise RuntimeError("Pinned evaluation changed")
                value = {"trial": selector["trial"], **stored}
        if self.owner.app.config.get("EVALUATION_STORE") is not store:
            raise RuntimeError("Evaluation owner replaced")
        return revision, value, identity

    def _training(self, selector: dict[str, str]) -> tuple[Any, Any, Any]:
        from .training_integration import IntegratedTraining
        dispatcher = self._dispatcher()
        connection_id = selector["connection_id"]
        etag = dispatcher.store.read_snapshot().etag
        connection = dispatcher._connection(connection_id, etag)
        if connection.provider_id != "llm:custom" or connection.auth_mode != "api_key":
            raise RuntimeError("Training connection unavailable")
        revision, stored = dispatcher.ledger.control_snapshot("admission:" + connection_id)
        self._control(revision, stored)
        value = None
        if stored is not None:
            if stored.get("role") != "training" or stored.get("protocol") != "unsloth_training":
                raise RuntimeError("Training policy unavailable")
            policy = {key: entry for key, entry in stored.items() if key not in {"role", "protocol", "budget_revision"}}
            # This validator only reads existing owners. Do not instantiate jobs,
            # claim resources, retrieve credentials or mutate the training owner.
            IntegratedTraining(self.owner).backend_configuration(connection_id, policy)
            value = {"connection_id": connection_id, "policy": policy}
        dispatcher._connection(connection_id, etag)
        return revision, value, {"connection_id": connection_id, "connection_revision": etag}

    def exact(self, run_id: str, who: Any, selector: dict[str, str]) -> dict[str, Any]:
        """Read one owned control. Never construct a missing durable dependency."""
        self._validate_selector(run_id, selector)
        try:
            with self.owner.lock, self.owner.runs.fence(run_id, "reasoning"):
                scope = self._current(run_id, who)
                if selector["action"] == "learning-rights":
                    revision, value, identity = self._rights(run_id, selector)
                elif selector["action"] == "training-backend":
                    revision, value, identity = self._training(selector)
                else:
                    revision, value, identity = self._immutable(scope, selector)
                if self._current(run_id, who) != scope:
                    raise ModelControlDenied("run_scope_not_owned")
                return {"scope": scope, "policy_provenance": PROVENANCE, "exact_control": {
                    "selector": selector, "revision": revision, "value": value, "identity": identity}}
        except ModelControlDenied:
            raise
        except Exception as exc:
            raise RuntimeError("Exact control unavailable") from exc

    def _proposal(self, run_id: str, who: Any, body: dict[str, Any]) -> tuple[str, int, dict[str, Any]]:
        if set(body) != {"action", "expected_revision", "value"} or type(body["value"]) is not dict:
            raise ValueError("exact configuration proposal required")
        action, revision, value = body["action"], body["expected_revision"], body["value"]
        if type(revision) is not int or revision < 0:
            raise ValueError("non-negative integer revision required")
        self.scope(run_id, who)
        run = self.owner.runs.owner(run_id).supervisor.run
        if run is None or run.run_id != run_id:
            raise ModelControlDenied("run_producer_unavailable")
        run.adapter.validate_session()
        if action == "training-backend":
            if set(value) != {"connection_id", "policy"} or type(value["policy"]) is not dict:
                raise ValueError("Exact training backend required")
            self.owner.training_owner().backend_configuration(**value)
            current = self.owner.dispatcher().ledger.control("admission:" + value["connection_id"])[0]
            if current != revision:
                raise ConfigurationConflict("configuration_revision_changed")
            return action, revision, value
        if action in {"grant", "revoke-grant"}:
            expected = {"role"} if action == "revoke-grant" else {"role", "valid_until", "identity_scope", "evidence"}
            if set(value) != expected or value["role"] != "reasoning":
                raise ValueError("Exact reasoning role required")
            if action == "grant":
                if value["identity_scope"] != "provider-reported-revision" or _positive(value["valid_until"]) <= self.owner.now():
                    raise ValueError("Current role/identity policy required")
                _text(value["evidence"])
            current, grant = self.owner.runs.control(run_id, "grant:reasoning")
            if current != revision or action == "revoke-grant" and not grant:
                raise ConfigurationConflict("configuration_revision_changed")
            return action, revision, value
        if action in {"candidate", "evaluation"}:
            fields = ({"candidate", "selection", "role", "identity_scope", "valid_until", "deadline_ms",
                       "max_output_tokens", "readiness_ttl_seconds"} if action == "candidate" else {"trial", "suite"})
            if set(value) != fields or revision != 0:
                raise ValueError("Exact immutable configuration required")
            trial = value["candidate"] if action == "candidate" else value["trial"]
            store = self.owner.app.config["EVALUATION_STORE"]
            manifest = store.experiment(store.trial(trial)["experiment_id"])["manifest"]
            if manifest.get("control_scope") != self.scope(run_id, who):
                raise ModelControlDenied("evaluation_scope_not_owned")
            if action == "candidate":
                self.owner.candidate_configuration(**value)
            else:
                self.owner.evaluation_configuration(**value)
            if self.owner.dispatcher().ledger.control("run-" + action + ":" + trial)[0] != revision:
                raise ConfigurationConflict("configuration_revision_changed")
            return action, revision, value
        if action in {"learning-rights", "learning-dataset", "learning-policy", "learning-binding"}:
            self.owner.learning(run_id).policy.validate(action, value, revision)
            key = "rights:" + value["subject"] if action == "learning-rights" else action.removeprefix("learning-")
            if self.owner.learning(run_id).policy.control(key)[0] != revision:
                raise ConfigurationConflict("configuration_revision_changed")
            return action, revision, value
        if action != "access" or set(value) != {"operations", "valid_until", "evidence"}:
            raise ValueError("unsupported configuration action or fields")
        if (type(value["operations"]) is not list or not all(type(op) is str for op in value["operations"])
                or len(set(value["operations"])) != len(value["operations"])
                or set(value["operations"]) - {"adoption.adopt", "adoption.get", "adoption.reconcile", "training.start",
                    "training.get", "training.cancel", "training.reconcile", "evaluation.read", "evaluation.score"}
                or _positive(value["valid_until"]) <= self.owner.now()):
            raise ValueError("explicit current run policy required")
        _text(value["evidence"])
        if self.owner.runs.control(run_id, "access")[0] != revision:
            raise ConfigurationConflict("configuration_revision_changed")
        return action, revision, value

    def _target(self, run_id: str, who: Any, body: dict[str, Any]) -> dict[str, Any]:
        selected = self.selector(body["action"], body["value"])
        if selected is None:
            return {}
        observed = self.exact(run_id, who, selected)["exact_control"]
        return {"target_identity": None if body["action"] == "learning-rights" else observed["identity"]}

    def _fingerprint(self, run_id: str, who: Any, body: dict[str, Any], target: dict[str, Any]) -> str:
        return digest({"scope": self.scope(run_id, who), "session": who.session_binding, "proposal": body,
                       "target": target, "risk": self.owner.runs.snapshot(run_id, "reasoning").risk_fingerprint})

    def preview(self, run_id: str, who: Any, body: dict[str, Any]) -> dict[str, Any]:
        with self.owner.lock, self.owner.runs.fence(run_id, "reasoning"):
            self._proposal(run_id, who, body)
            now = time.monotonic()
            self.pending = {key: value for key, value in self.pending.items() if value[0] > now}
            if len(self.pending) >= 128:
                raise ConfigurationConflict("confirmation_capacity_reached")
            token = secrets.token_urlsafe(32)
            target = self._target(run_id, who, body)
            self.pending[token] = (now + 120, self._fingerprint(run_id, who, body, target), deepcopy(target))
            return {"confirmation": token, "expires_in_seconds": 120, "scope": self.scope(run_id, who),
                    "proposal": body, "policy_provenance": PROVENANCE, **target}

    def confirm(self, run_id: str, who: Any, body: dict[str, Any]) -> dict[str, Any]:
        if set(body) != {"action", "expected_revision", "value", "confirmation"}:
            raise ValueError("exact confirmed proposal required")
        proposal = {key: value for key, value in body.items() if key != "confirmation"}
        token = _text(body["confirmation"])
        with self.owner.lock, self.owner.runs.fence(run_id, "reasoning"):
            pending = self.pending.pop(token, None)
            if not pending or pending[0] <= time.monotonic() or pending[1] != self._fingerprint(run_id, who, proposal, self._target(run_id, who, proposal)):
                raise ConfigurationConflict("confirmation_invalid_or_consumed")
            action, revision, value = self._proposal(run_id, who, proposal)
            result = None
            if action.startswith("learning-"):
                result = self.owner.learning(run_id).policy.configure(action, value, revision)
            elif action == "training-backend":
                self.owner.training_owner().configure_backend(**value, expected_revision=revision)
                current, configured = self.owner.dispatcher().ledger.control("admission:" + value["connection_id"])
                result = {"revision": current, "value": configured}
            elif action == "grant":
                state = self.owner.runs.snapshot(run_id, "reasoning")
                self.owner.configure_grant(run_id, actor=who.actor_ref, expected_revision=revision,
                                           risk_fingerprint=state.risk_fingerprint, **value)
            elif action == "revoke-grant":
                self.owner.revoke_grant(run_id, actor=who.actor_ref, expected_revision=revision, **value)
            elif action == "candidate":
                try:
                    self.owner.configure_candidate(
                        **value, expected_identity=pending[2]["target_identity"]["serving_identity"])
                except (UsageConflict, ConnectionRevisionConflict) as exc:
                    raise ConfigurationConflict("candidate_identity_changed") from exc
                result = {"candidate": value["candidate"], **self.owner.candidate(value["candidate"])}
            elif action == "evaluation":
                self.owner.configure_evaluation(**value)
                result = self.owner.dispatcher().ledger.control("run-evaluation:" + value["trial"])[1]
            else:
                self.owner.configure_access(run_id, actor=who.actor_ref, expected_revision=revision, **value)
            selected = self.selector(action, value)
            exact = self.exact(run_id, who, selected) if selected else {}
            return {**self.read(run_id, who), **exact, "result": result}


def _owner() -> ModelRunConfiguration:
    return current_app.config["MODEL_RUN_SERVICES"].configuration()


def _handled(function: Any) -> Any:
    @wraps(function)
    def invoke(*args: Any, **kwargs: Any) -> Any:
        try:
            return jsonify(function(*args, **kwargs))
        except ConfigurationConflict as exc:
            return jsonify(code=str(exc)), 409
        except ModelControlDenied as exc:
            return jsonify(code=str(exc)), 403
        except (ValueError, TypeError, KeyError):
            return jsonify(code="invalid_model_configuration"), 400
        except Exception:
            return jsonify(code="model_configuration_unavailable"), 503
    return invoke


@model_run_config_bp.get(PREFIX)
@_handled
def read(run_id: str) -> dict[str, Any]:
    return _owner().read(run_id, principal())


@model_run_config_bp.get(PREFIX + "/control")
@_handled
def exact_control(run_id: str) -> dict[str, Any]:
    """Read one literal selector under current authenticated run authority.

    Duplicate query fields are invalid. Established dependency loss returns
    unavailable through the route handler, never repaired custody or a guessed
    zero revision; genuine unissued controls remain distinguishable.
    """
    if any(len(values) != 1 for _, values in request.args.lists()):
        raise ValueError("Duplicate selectors")
    return _owner().exact(run_id, principal(), request.args.to_dict())


@model_run_config_bp.post(PREFIX + "/preview")
@_handled
def preview(run_id: str) -> dict[str, Any]:
    return _owner().preview(run_id, principal(), _body())


@model_run_config_bp.post(PREFIX + "/confirm")
@_handled
def confirm(run_id: str) -> dict[str, Any]:
    return _owner().confirm(run_id, principal(), _body())


@model_run_config_bp.get(PREFIX + "/training-provenance/<identity>")
@_handled
def training_provenance(run_id: str, identity: str) -> dict[str, Any]:
    configuration, who = _owner(), principal()
    configuration.scope(run_id, who)
    owner = configuration.owner
    authorised = owner.authorise(who.actor_ref, "training", "get", identity=identity, body={})
    if authorised != run_id:
        raise ModelControlDenied("run_scope_not_owned")
    return owner.training_owner().provenance(identity)
