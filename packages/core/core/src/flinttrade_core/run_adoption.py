"""Lazy composition of exact-run adoption and optional training.

No setup I/O, default grants, invented thresholds, weight hashes or Live arming.
The existing Practice store owns model bindings; R1 owns credential custody and
usage; R2 owns learning consent; R5 owns evaluation, adoption and job receipts.
"""
from __future__ import annotations

import math
import threading
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace
from typing import Any
from uuid import uuid4

from .artifact_activation import ArtifactActivation
from .evaluation import canonical, digest
from .execution_session import PracticeRunOwner
from .model_control_auth import ModelControlDenied
from .service_usage import UsageConflict


def _text(value: Any) -> str:
    if type(value) is not str or not value or len(value) > 256:
        raise ValueError("Explicit bounded text required")
    return value


def _positive(value: Any) -> float:
    if type(value) not in {int, float} or not math.isfinite(value) or value <= 0:
        raise ValueError("Explicit positive numeric policy required")
    return value


class _Commands:
    def __init__(self, owner: ModelRunServices, kind: str) -> None:
        self.owner, self.kind = owner, kind

    def __getattr__(self, operation: str) -> Any:
        if operation not in {"adopt", "start", "get", "cancel", "reconcile"}:
            raise AttributeError(operation)
        def call(*args: Any, **kwargs: Any) -> Any:
            return self.owner.command(self.kind, operation, *args, **kwargs)
        return call


class _Runs:
    """Resolve exact existing owners without a mutable active run/account."""

    def __init__(self) -> None:
        self.owners: dict[str, PracticeRunOwner] = {}

    def owner(self, run_id: str) -> PracticeRunOwner:
        try:
            return self.owners[run_id]
        except KeyError:
            raise ModelControlDenied("run_not_owned") from None

    def __getattr__(self, name: str) -> Any:
        if name not in {"scope", "snapshot", "fence", "pause_entries", "control", "configure"}:
            raise AttributeError(name)
        return lambda run_id, *args, **kwargs: getattr(self.owner(run_id), name)(run_id, *args, **kwargs)

    def bind(self, candidate: str, state: Any) -> None:
        self.owner(state.run_id).bind(candidate, state)


class PinnedTaskServing:
    """Non-destructive hosted reasoning binding using R1's real wire adapter.

    Identity is only the provider-reported revision, never a weight digest.
    Readiness is a bounded successful request, rechecked on every inference.
    Local global selectors, action/admission roles and unknown identities refuse.
    No provider load/unload/failover/restart is exposed.
    """

    staging_preserves_incumbent = True

    def __init__(self, owner: ModelRunServices) -> None:
        self.owner = owner
        self.bound: dict[tuple[str, str], dict[str, Any]] = {}

    def _invoke(self, candidate: str, state: Any, prompt: str, *, classification: str) -> dict[str, Any]:
        value = self.owner.candidate(candidate)
        result = self.owner.dispatcher().dispatch({
            "request_id": str(uuid4()), "mode": "fixed", "selection": value["selection"], "prompt": prompt,
            "classification": classification, "context_refs": [], "purpose": "assistant",
            "deadline_ms": value["deadline_ms"], "max_output_tokens": value["max_output_tokens"],
            "required_hard_controls": ["output_tokens"],
        }, actor=self.owner.runs.scope(state.run_id).actor)
        if result.get("outcome") != "completed" or result.get("resolved_model") != value["model_revision"]:
            raise ValueError("Serving identity/readiness not verified")
        return result

    def stage(self, candidate: str, state: Any) -> dict[str, Any]:
        result = self._invoke(candidate, state, "Return READY. No tools or actions.", classification="public")
        evidence = self.owner.qualification(candidate)
        return {"candidate": candidate, "identity": evidence["identity"], "run_id": state.run_id, "role": state.role,
                "observed_at": self.owner.now(), "receipt": result["request_id"]}

    def identity(self, handle: dict[str, Any]) -> str:
        return handle["identity"]

    def commit(self, handle: dict[str, Any], run_id: str, role: str) -> None:
        if (handle["run_id"], handle["role"]) != (run_id, role):
            raise ValueError("Serving scope mismatch")
        self.bound[run_id, role] = dict(handle)

    def current(self, run_id: str, role: str) -> str | None:
        handle = self.bound.get((run_id, role))
        if handle is None:
            return None  # restart is not serving readback or permission to re-arm
        value = self.owner.candidate(handle["candidate"])
        if (self.owner.now() >= handle["observed_at"] + value["readiness_ttl_seconds"]
                or self.owner.qualification(handle["candidate"])["identity"] != handle["identity"]):
            return None
        return handle["identity"]

    def chat(self, state: Any, messages: Any) -> Any:
        # The caller captured this state before I/O; the proposal keeps that epoch
        # even if a different candidate commits while the request is outstanding.
        prompt = canonical([{"role": message.role, "content": message.content} for message in messages])
        result = self._invoke(state.binding, state, prompt, classification="private")
        handle = self.bound.get((state.run_id, state.role))
        if handle and handle["candidate"] == state.binding:
            handle["observed_at"] = self.owner.now()
            handle["receipt"] = result["request_id"]
        return SimpleNamespace(content=result["output"], error="")


class ModelRunServices:
    """Configuration, qualified commands and lifecycle over real shared owners."""

    def __init__(self, app: Any, workspace: Path) -> None:
        self.app, self.workspace = app, Path(workspace)
        self.lock = threading.RLock()
        self.closed = False
        self.runs = _Runs()
        self.serving = PinnedTaskServing(self)
        self._activation: ArtifactActivation | None = None
        self._training: Any = None
        self._configuration: Any = None
        self._learning: dict[str, Any] = {}
        self.adoptions = _Commands(self, "adoption")
        self.training = _Commands(self, "training")

    def dispatcher(self) -> Any:
        if self.closed:
            raise RuntimeError("Run services closed")
        from .service_task_routes import get_service_task_dispatcher
        with self.app.app_context():
            return get_service_task_dispatcher()

    def now(self) -> float:
        return self.dispatcher().clock().timestamp()

    def install_knowledge_scope(self) -> None:
        """Compose R7's exact Live resolver with Practice; ambiguous actors refuse."""
        previous = self.app.config.get("KNOWLEDGE_SCOPE_RESOLVER")
        if previous is getattr(self, "_knowledge_resolver", None):
            return
        def resolve(actor: str) -> Any:
            from flinttrade_ai.knowledge_store import KnowledgeScope
            scopes = []
            if callable(previous):
                old = previous(actor)
                if old is not None:
                    scopes.append(old)
            for run_id, owner in tuple(self.runs.owners.items()):
                run = owner.supervisor.run
                if (run is None or run.run_id != run_id or run.owner != actor or run.cleanup_complete
                        or run.thread is None or not run.thread.is_alive()):
                    continue
                try:
                    run.adapter.validate_session()
                    scope = owner.scope(run_id)
                    scopes.append(KnowledgeScope(scope.account, scope.environment, scope.run_id))
                except Exception:
                    continue
            return scopes[0] if len(scopes) == 1 else None
        self._knowledge_resolver = resolve
        self.app.config["KNOWLEDGE_SCOPE_RESOLVER"] = resolve

    def practice_context(self, run: Any) -> dict[str, Any]:
        """Bind the consumer directly; no UI-selected account or legacy Flask g."""
        from flinttrade_ai.knowledge_store import KnowledgeScope

        from .service_providers import RightsResolution
        runtime = self.app.config["KNOWLEDGE_RUNTIME"]
        scope = self.runs.scope(run.run_id)
        run.adapter.validate_session()
        knowledge_scope = KnowledgeScope(scope.account, scope.environment, scope.run_id)
        learning = self.learning(run.run_id)
        return {"memory": runtime.memory(knowledge_scope, rights=RightsResolution()),
                "skill_registry": runtime.skills(knowledge_scope), "skills_workspace": None,
                "automatic_learning": True, "learning_records": learning, "learning_client": learning}

    def learning(self, run_id: str) -> Any:
        """Keep the exact learner alive with its originating producer/dependencies."""
        with self.lock:
            if run_id not in self._learning:
                from .run_learning import RunLearning
                run = self.runs.owner(run_id).supervisor.run
                if run is None or run.run_id != run_id:
                    raise ValueError("Exact learning producer unavailable")
                self._learning[run_id] = RunLearning(self, run)
            return self._learning[run_id]

    def resolve_learning_permission(self, **kwargs: Any) -> Any:
        scope = kwargs["scope"]
        if kwargs["purpose"] == "reflection" and len(scope.runs) == 1:
            return self.learning(scope.runs[0]).policy.resolve_permission(**kwargs)
        return self.training_owner().resolve_permission(**kwargs)

    def attach_practice(self, supervisor: Any) -> None:
        """Attach the existing exact worker; never construct another sandbox."""
        if self.closed or supervisor.app is not self.app or supervisor.run is None:
            raise ValueError("Exact existing run owner required")
        run = supervisor.run
        with self.lock:
            from .execution_session import run_drained
            previous = self.runs.owners.get(run.run_id)
            if previous is not None and previous.supervisor is supervisor and previous.producer is run:
                return
            owner = PracticeRunOwner(supervisor)
            if previous is not None:
                if (not run_drained(previous.producer) or previous.identity != owner.identity
                        or previous.custody != owner.custody):
                    raise ValueError("Run ownership conflict")
                # Preserve the same policy/consent client, changing only its
                # proven drained producer. Ledger lineage and controls remain.
                learning = self._learning.get(run.run_id)
                if learning is not None:
                    if learning.run is not previous.producer:
                        raise ValueError("Run learning ownership conflict")
                    learning.run = run
            self.runs.owners[run.run_id] = owner
            try:
                if (run.adapter._model_admission is None and any(owner.control(run.run_id, key)[1] is not None
                        for key in ("grant:reasoning", "binding:reasoning"))):
                    run.adapter.bind_model_admission(self.runs, self._engine(), run.run_id, "reasoning")
            except BaseException:
                if previous is None:
                    self.runs.owners.pop(run.run_id, None)
                else:
                    self.runs.owners[run.run_id] = previous
                    if run.run_id in self._learning:
                        self._learning[run.run_id].run = previous.producer
                raise
            self.install_knowledge_scope()
        # Only managed/adopted proposals use R5. Legacy execution is unchanged
        # until explicit run authority is configured; attaching alone never arms.

    def _engine(self) -> ArtifactActivation:
        with self.lock:
            if self.closed:
                raise RuntimeError("Run services closed")
            if self._activation is None:
                self._activation = ArtifactActivation(self.workspace / "artifact-adoptions.sqlite", runs=self.runs,
                    serving=self.serving, authority=self.authority, qualification=self.qualification, clock=self.now)
            return self._activation

    def _identity(self, selection: dict[str, Any]) -> tuple[str, dict[str, Any]]:
        dispatcher = self.dispatcher()
        connection = dispatcher._connection(selection["connection_id"], selection["connection_revision"])
        policy = dispatcher.admission(selection["connection_id"])["policy"]
        if (not policy or policy["protocol"] not in {"openrouter_chat", "anthropic_messages", "openai_responses"}
                or not policy["enabled"] or policy["role"] != "assistant"
                or policy["connection_revision"] != selection["connection_revision"]
                or connection.model != selection["model"] or selection["effort"] not in policy["efforts"]
                or not connection.credential_configured or connection.auth_mode != "api_key"):
            raise ValueError("Precise provider/auth/model reasoning protocol not qualified")
        if (policy["entitlement"]["status"] != "verified"
                or datetime.fromisoformat(policy["entitlement"]["expires_at"]) <= dispatcher.clock()):
            raise ValueError("Provider entitlement expired or unverified")
        # This fingerprint names reported guarantees and config, NOT model weights.
        identity = {"provider": connection.provider_id, "endpoint": connection.endpoint,
                    "auth": connection.auth_mode, "selection": selection, "admission": policy}
        return "provider-reported-revision:" + digest(identity), policy

    def candidate_configuration(self, candidate: str, *, selection: dict[str, Any], role: str, identity_scope: str,
                            valid_until: float, deadline_ms: int, max_output_tokens: int,
                            readiness_ttl_seconds: float) -> dict[str, Any]:
        """Bind a sealed, independently scored trial to precise serving policy.

        Operator policy does not supply independent evaluation or entitlement.
        A configured identity scope explicitly accepts provider-reported revisions;
        it is not sufficient for trading-action or independent admission roles.
        """
        _text(candidate)
        if role != "reasoning" or identity_scope != "provider-reported-revision":
            raise ValueError("Role/identity guarantee unsupported")
        if (type(selection) is not dict or set(selection) != {"connection_id", "connection_revision", "model", "effort"}
                or type(deadline_ms) is not int or not 1 <= deadline_ms <= 120000
                or type(max_output_tokens) is not int or max_output_tokens <= 0):
            raise ValueError("Explicit serving workload required")
        _positive(readiness_ttl_seconds)
        if _positive(valid_until) <= self.now():
            raise ValueError("Qualification expired")
        identity, policy = self._identity(selection)
        value = {"selection": selection, "role": role, "identity_scope": identity_scope, "valid_until": valid_until,
                 "deadline_ms": deadline_ms, "max_output_tokens": max_output_tokens,
                 "readiness_ttl_seconds": readiness_ttl_seconds, "identity": identity,
                 "model_revision": policy["model_revision"]}
        self._qualified(candidate, value)
        return value

    def configure_candidate(self, candidate: str, *, expected_identity: str | None = None, **policy: Any) -> None:
        """Claim qualified policy under its server-held serving pin and current admission.

        Trusted non-preview callers still pin the derived identity. Connection
        custody precedes the usage CAS, as in ordinary admission/dispatch; no
        grading or provider work runs under either persistence fence.
        """
        value = self.candidate_configuration(candidate, **policy)
        dispatcher = self.dispatcher()
        selection = value["selection"]
        identity, admission = self._identity(selection)
        if identity != value["identity"] or expected_identity is not None and identity != expected_identity:
            raise UsageConflict("candidate identity changed")
        connection = dispatcher._connection(selection["connection_id"], selection["connection_revision"])
        with dispatcher.store.dispatch_binding(connection.ref, expected_etag=selection["connection_revision"]):
            dispatcher.ledger.configure_control("run-candidate:" + candidate, value, expected_revision=0,
                expected_controls={"admission:" + selection["connection_id"]: admission})

    def candidate(self, candidate: str) -> dict[str, Any]:
        _, value = self.dispatcher().ledger.control("run-candidate:" + _text(candidate))
        if value is None:
            raise ValueError("Candidate not configured")
        return value

    def _qualified(self, candidate: str, value: dict[str, Any]) -> dict[str, Any]:
        store = self.app.config.get("EVALUATION_STORE")
        if store is None:
            raise ValueError("Independent evaluation owner unavailable")
        trial = store.trial(candidate)
        evidence = trial["evidence"]
        manifest = store.experiment(trial["experiment_id"])["manifest"]
        if manifest.get("training_job") is not None:
            # The pinned management subset observes jobs but does not attest an
            # exported/served output artifact. Never infer that link from a job
            # label, an acknowledgement, a base-model name or a completed phase.
            raise ValueError("Training artifact provenance is not available from the management subset")
        suite = store.suite(evidence["suite"])
        if (trial["status"] != "completed" or evidence.get("qualified") is not True
                or suite["consumed_by"] != candidate or suite["digest"] != evidence["suite_digest"]
                or evidence["candidate"] != manifest or manifest["model"] != value["selection"]
                or manifest["role"] != value["role"] or manifest["producer"] == suite["evaluator"]
                or not evidence["prospective"].get("receipt") or self.now() >= value["valid_until"]
                or self._identity(value["selection"])[0] != value["identity"]):
            raise ValueError("Exact independent/prospective qualification required")
        return {"candidate": candidate, "qualified": True, "independent": True, "role": value["role"],
                "policy": digest(suite["policy"]), "prospective": evidence["prospective"]["receipt"],
                "identity": value["identity"], "receipt": candidate, "identity_scope": value["identity_scope"],
                "valid_until": value["valid_until"]}

    def qualification(self, candidate: str) -> dict[str, Any]:
        return self._qualified(candidate, self.candidate(candidate))

    def configure_grant(self, run_id: str, role: str, *, actor: str, expected_revision: int, valid_until: float,
                        risk_fingerprint: str, identity_scope: str, evidence: str) -> int:
        with self.runs.fence(run_id, role):
            scope = self.runs.scope(run_id)
            state = self.runs.snapshot(run_id, role)
            if (scope.actor != actor or state.risk_fingerprint != risk_fingerprint
                    or identity_scope != "provider-reported-revision" or _positive(valid_until) <= self.now()):
                raise ValueError("Exact current run/risk authority required")
            value = {"id": str(uuid4()), "run_id": run_id, "role": role, "account": scope.account,
                     "environment": scope.environment, "actor": actor, "risk_fingerprint": risk_fingerprint,
                     "valid_until": valid_until, "identity_scope": identity_scope, "evidence": _text(evidence),
                     "operation": "planned-adoption", "generation": expected_revision + 1}
            revision = self.runs.configure(run_id, "grant:" + role, value, expected_revision=expected_revision)
            run = self.runs.owner(run_id).supervisor.run
            if run.adapter._model_admission is None:
                run.adapter.bind_model_admission(self.runs, self._engine(), run_id, role)
            return revision

    def revoke_grant(self, run_id: str, role: str, *, actor: str, expected_revision: int) -> None:
        """Fence revocation with the actual write/bind owner; never cancel orders."""
        with self.runs.fence(run_id, role):
            revision, value = self.runs.control(run_id, "grant:" + role)
            if self.runs.scope(run_id).actor != actor or not value or revision != expected_revision:
                raise ValueError("Exact current grant owner required")
            self.runs.configure(run_id, "grant:" + role, {**value, "valid_until": 0, "generation": revision + 1},
                                expected_revision=revision)
            self.runs.pause_entries(run_id, role)

    def authority(self, state: Any, candidate: str) -> dict[str, Any] | None:
        grant = self.runs.control(state.run_id, "grant:" + state.role)[1]
        if not grant:
            return None
        self.authorise(grant["actor"], "adoption", "adopt", identity=None, body={"run_id": state.run_id})
        revision, _ = self.runs.control(state.run_id, "access")
        return {**grant, "access_revision": revision}

    def configure_access(self, run_id: str, *, actor: str, operations: list[str], valid_until: float,
                         evidence: str, expected_revision: int) -> int:
        allowed = {"adoption.adopt", "adoption.get", "adoption.reconcile", "training.start", "training.get",
                   "training.cancel", "training.reconcile", "evaluation.score", "evaluation.read"}
        if (self.runs.scope(run_id).actor != actor or type(operations) is not list or set(operations) - allowed
                or len(operations) != len(set(operations)) or _positive(valid_until) <= self.now()):
            raise ValueError("Explicit per-operation run access required")
        return self.runs.configure(run_id, "access", {"actor": actor, "operations": operations,
            "valid_until": valid_until, "evidence": _text(evidence)}, expected_revision=expected_revision)

    def authorise(self, actor: str, kind: str, operation: str, *, identity: str | None, body: dict[str, Any]) -> str:
        if self.closed:
            raise ModelControlDenied("model_services_closed")
        if identity is not None:
            if kind == "adoption":
                run_id = self._engine().get(identity)["request"]["run_id"]
            else:
                run_id = self.training_owner().get(identity)["lineage"]["run_id"]
        else:
            run_id = body["lineage"]["run_id"] if kind == "training" else body["run_id"]
        with self.runs.fence(run_id, "reasoning"):
            _, access = self.runs.control(run_id, "access")
            if (self.runs.scope(run_id).actor != actor or not access or access["actor"] != actor
                    or self.now() >= access["valid_until"] or kind + "." + operation not in access["operations"]):
                raise ModelControlDenied("model_operation_not_authorised")
        return run_id

    def evaluation_configuration(self, trial: str, *, suite: str) -> dict[str, Any]:
        """Pin exact sealed access independently of adoption/training permission."""
        store = self.app.config["EVALUATION_STORE"]
        record = store.trial(trial)
        manifest = store.experiment(record["experiment_id"])["manifest"]
        scope = manifest["control_scope"]
        if scope != vars(self.runs.scope(scope["run_id"])):
            raise ValueError("Exact evaluation run owner required")
        frozen = store.suite(suite)
        if frozen["consumed_by"] is not None or frozen["evaluator"] != manifest["evaluator"]:
            raise ValueError("Exact unused independent suite required")
        if store.admission_owner is not None and store.admission_owner is not self:
            raise ValueError("Evaluation admission owner already bound")
        return {"suite": suite, "suite_digest": frozen["digest"], "manifest_digest": digest(manifest)}

    def configure_evaluation(self, trial: str, *, suite: str) -> None:
        """Persist exact sealed access; consumed claims remain the evaluator's job."""
        value = self.evaluation_configuration(trial, suite=suite)
        self.dispatcher().ledger.configure_control("run-evaluation:" + trial,
                                                   value, expected_revision=0)
        self.app.config["EVALUATION_STORE"].admission_owner = self

    @contextmanager
    def evaluation_fence(self, suite: str, trial: str) -> Iterator[None]:
        """Recheck the real session and run access at the sealed claim, not grading."""
        from .model_control_auth import principal
        store = self.app.config["EVALUATION_STORE"]
        record = store.experiment(store.trial(trial)["experiment_id"])
        run_id = record["manifest"]["control_scope"]["run_id"]
        with self.runs.fence(run_id, "reasoning"):
            self.authorise_evaluation(principal().actor_ref, "score", trial, suite=suite)
            yield

    def authorise_evaluation(self, actor: str, operation: str, identity: str, *,
                             suite: str | None = None, experiment: bool = False) -> None:
        store = self.app.config.get("EVALUATION_STORE")
        if store is None:
            raise ModelControlDenied("evaluation_owner_unavailable")
        record = store.experiment(identity) if experiment else store.experiment(store.trial(identity)["experiment_id"])
        manifest = record["manifest"]
        scope = manifest.get("control_scope")
        if scope is None and operation == "read":
            from .model_control_auth import principal
            who = principal()
            resolver = self.app.config.get("DATA_SCOPE_RESOLVER")
            data = manifest.get("data")
            expected = data.get("scope") if type(data) is dict else None
            current = resolver() if callable(resolver) else None
            if (who.actor_ref == actor and type(expected) is dict and expected
                    and expected == current):
                return  # History read only: never sealed scoring or run authority.
        if type(scope) is not dict or scope.get("actor") != actor:
            raise ModelControlDenied("evaluation_scope_not_owned")
        run_id = scope.get("run_id")
        if scope != vars(self.runs.scope(run_id)):
            raise ModelControlDenied("evaluation_scope_not_owned")
        self.authorise(actor, "evaluation", operation, identity=None, body={"run_id": run_id})
        if operation == "score":
            _, access = self.dispatcher().ledger.control("run-evaluation:" + identity)
            if not access or access != {"suite": suite, "suite_digest": store.suite(suite)["digest"],
                                       "manifest_digest": digest(manifest)}:
                raise ModelControlDenied("sealed_access_not_authorised")

    def training_owner(self) -> Any:
        if self._training is None:
            from .training_integration import IntegratedTraining
            self._training = IntegratedTraining(self)
        return self._training

    def configuration(self) -> Any:
        """Lazy configuration interface; installation still performs no I/O."""
        with self.lock:
            if self._configuration is None:
                from .model_run_config import ModelRunConfiguration
                self._configuration = ModelRunConfiguration(self)
            return self._configuration

    def command(self, family: str, operation: str, *args: Any, **kwargs: Any) -> Any:
        from .model_control_auth import principal
        who = principal()  # no unauthenticated proxy access or generic inference key
        body = {**kwargs}
        if family == "training" and operation == "start":
            body["payload"] = args[1]
        identity = args[0] if operation in {"get", "cancel", "reconcile"} else None
        run_id = self.authorise(who.actor_ref, family, operation, identity=identity, body=body)
        engine = self._engine() if family == "adoption" else self.training_owner()
        # R5 adoption stages outside the run fence then revalidates its grant.
        # Start/management revalidate access inside their actual send fence too.
        if family == "adoption":
            return getattr(engine, operation)(*args, **kwargs)
        return engine.command(operation, *args, actor=who.actor_ref, run_id=run_id, **kwargs)

    def chat(self, run: Any, messages: Any) -> Any:
        state = self.runs.snapshot(run.run_id, "reasoning")
        if not self._engine().accepts(run.run_id, "reasoning", generation=state.generation, candidate=state.binding):
            raise ValueError("Run model no longer eligible")
        try:
            result = self.serving.chat(state, messages)
        except Exception:
            self.runs.pause_entries(run.run_id, "reasoning")
            raise
        run.adapter.record_model_proposal(state.generation, state.binding)
        return result

    def maintenance_snapshot(self) -> dict[str, Any]:
        """Read-only observations for maintenance; never a stop/disposal permit.

        The live registry is not a complete archive/protection-grant census.
        Missing processes, JWTs, ledgers or model owners cannot authorise erasure.
        Callers must retain state on unknown ownership and apply the separate
        shared maintenance exclusion; this method never acquires that authority.
        """
        with self.lock:
            owners = tuple(self.runs.owners.items())
        observations = []
        for run_id, owner in owners:
            run = owner.supervisor.run
            value = {"run_id": run_id, "worker_alive": bool(run and run.run_id == run_id
                     and run.thread and run.thread.is_alive()), "execution_evidence": "unavailable",
                     "protection_verified_now": None, "entries_armed": None}
            try:
                state = owner.snapshot(run_id, "reasoning")
                value.update(execution_evidence="observed", protection_verified_now=state.protection_verified,
                             entries_armed=state.entries_armed, frontier=state.frontier)
            except Exception:
                pass
            observations.append(value)
        return {"runs": observations, "registry_complete": False, "disposal_authorised": False,
                "protection_lifetime": "independent-grant-unqualified", "owner_closed": self.closed,
                "reason": "Independent durable protection lifetime and explicit maintenance authority required"}

    def close(self) -> None:
        """Parent must first drain requests and stop Practice; no borrowed closes."""
        with self.lock:
            if self.closed:
                return
            for owner in self.runs.owners.values():
                run = owner.supervisor.run
                if run and run.thread and run.thread.is_alive():
                    raise RuntimeError("Run consumers have not drained")
            for learning in self._learning.values():
                trader = learning.run.trader
                if trader is not None and not trader.join_background_learning(0):
                    raise RuntimeError("Run learning consumers have not drained")
            self.closed = True
            self.serving.bound.clear()


def install_run_services(app: Any, workspace: Path) -> ModelRunServices:
    """Install lazy R5 command owners and strict family guard before general auth."""
    existing = app.config.get("MODEL_RUN_SERVICES")
    if existing is not None:
        if not isinstance(existing, ModelRunServices) or existing.workspace != Path(workspace):
            raise ValueError("Run owner already installed with a different scope")
        return existing
    from .model_control_auth import guard_model_control, model_control_no_store
    owner = ModelRunServices(app, workspace)
    app.config.update(MODEL_RUN_SERVICES=owner, ARTIFACT_ACTIVATION=owner.adoptions, TRAINING_JOBS=owner.training)
    owner.install_knowledge_scope()
    app.config["LEARNING_PERMISSION_RESOLVER"] = owner.resolve_learning_permission
    hooks = app.before_request_funcs.setdefault(None, [])
    prefix = []
    for name in ("_bind_request_context", "_require_running_runtime"):
        hook = next((item for item in hooks if item.__name__ == name), None)
        if hook is not None:
            hooks.remove(hook)
            prefix.append(hook)
    # The factory's pure fixed-field metadata binder must cover early refusals.
    # It reads no body/auth/dependency owner. Runtime admission still precedes
    # every model/auth dependency access, including this strict family guard.
    hooks[:0] = [*prefix, guard_model_control]
    app.after_request(model_control_no_store)
    return owner
