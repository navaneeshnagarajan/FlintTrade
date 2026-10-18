"""Optional pinned Unsloth jobs composed with real connection/consent owners.

Only start/status/stop is supported. Dataset upload, recipe generation, retrieval,
checkpoint export and publication are not implemented or implicitly invoked.
"""
from __future__ import annotations

import hashlib
import re
from datetime import datetime
from typing import Any
from urllib.parse import urlsplit

import httpx

from .evaluation import canonical, digest
from .learning_consent import Recipient
from .run_adoption import _positive, _text
from .service_providers import PermissionState
from .service_usage_contracts import USAGE_DIMENSIONS, BudgetPolicy, TariffSnapshot, UsageAmounts
from .training_jobs import UNSLOTH_PIN, TrainingJobs, UnslothTrainingBackend


class IntegratedTraining:
    """Configure exact workload, prepare immutable request, use existing R5 jobs.

    Configuration is a trusted core interface, not accepted from job HTTP bodies.
    Deployment hard-control/isolation evidence must be independently qualified;
    the adapter neither measures capacity nor invents a provider hard cap.
    """

    def __init__(self, owner: Any) -> None:
        self.owner = owner
        self.path = owner.workspace / "training-jobs.sqlite"

    def consent(self) -> Any:
        from .knowledge_integration import get_learning_consent_ledger
        return get_learning_consent_ledger(self.owner.app)

    def register_dataset(self, scope: Any, *, actor: str, rights_versions: list[str]) -> None:
        """Register canonical knowledge membership before permission preview.

        This grants nothing. Only the real owner can supply scoped canonical
        version IDs; the HTTP consent body cannot register or expand a dataset.
        """
        from .learning_consent import DatasetScope
        if type(scope) is not DatasetScope or not rights_versions or len(set(rights_versions)) != len(rights_versions):
            raise ValueError("Canonical dataset scope and members required")
        for run_id in scope.runs:
            run = self.owner.runs.scope(run_id)
            if run.actor != actor or scope.accounts != (run.account,) or scope.environments != (run.environment,):
                raise ValueError("Dataset scope not owned")
        runtime = self.owner.app.config["KNOWLEDGE_RUNTIME"]
        resolved = []
        for version in rights_versions:
            runtime.store._require_eligible(version)
            resolved.append(runtime.ledger.get_event(version).rights)
        if any(value != resolved[0] for value in resolved) or any(
                getattr(resolved[0].rights, key) is not PermissionState.ALLOWED
                for key in ("training_distillation", "output_use", "retention")):
            raise ValueError("Exact current homogeneous learning rights required")
        self.owner.dispatcher().ledger.configure_control("training-dataset:" + digest(scope.to_dict()),
            {"scope": scope.to_dict(), "actor": actor, "rights_versions": rights_versions,
             "rights_digest": resolved[0].digest}, expected_revision=0)

    def resolve_permission(self, *, actor: str, scope: Any, recipient: Recipient,
                           purpose: str, operations: tuple[str, ...]) -> Any:
        """R7 permission resolver over canonical registry and current R1 custody."""
        if purpose != "fine-tuning" or operations != ("training.start",):
            return None
        try:
            value = self.owner.dispatcher().ledger.control("training-dataset:" + digest(scope.to_dict()))[1]
            if not value or value["actor"] != actor or value["scope"] != scope.to_dict():
                return None
            if recipient != self.recipient(str(recipient.connection.connection_id)):
                return None
            for run_id in scope.runs:
                run = self.owner.runs.scope(run_id)
                if (run.actor != actor or scope.accounts != (run.account,)
                        or scope.environments != (run.environment,)):
                    return None
            runtime = self.owner.app.config["KNOWLEDGE_RUNTIME"]
            resolved = None
            for version in value["rights_versions"]:
                runtime.store._require_eligible(version)
                resolved = runtime.ledger.get_event(version).rights
                if resolved.digest != value["rights_digest"]:
                    return None
            return scope, recipient, resolved
        except (KeyError, ValueError, RuntimeError):
            return None

    def backend_configuration(self, connection_id: str, policy: dict[str, Any]) -> Any:
        """Validate operator policy without claiming measured deployment entitlement."""
        fields = {"connection_revision", "budget", "tariff", "reservation", "quota_group", "version", "principal",
                  "principal_role", "region", "terms_revision", "model_revision", "valid_until", "isolation",
                  "controls", "controls_evidence", "timeout_seconds"}
        if type(policy) is not dict or set(policy) != fields:
            raise ValueError("Exact training workload policy required")
        dispatcher = self.owner.dispatcher()
        connection = dispatcher._connection(connection_id, policy["connection_revision"])
        if (connection.provider_id != "llm:custom" or connection.auth_mode != "api_key"
                or not connection.credential_configured or policy["version"] != UNSLOTH_PIN
                or policy["principal_role"] not in {"owner", "member"}):
            raise ValueError("Pinned Studio API-key contract required")
        url = urlsplit(connection.endpoint)
        if url.path not in {"", "/"} or url.query or url.fragment:
            raise ValueError("Exact Studio root required")
        for key in ("principal", "region", "terms_revision", "model_revision", "controls_evidence", "quota_group"):
            _text(policy[key])
        if _positive(policy["valid_until"]) <= self.owner.now() or _positive(policy["timeout_seconds"]) > 120:
            raise ValueError("Current bounded training policy required")
        isolated = policy["isolation"]
        if (type(isolated) is not dict or set(isolated) != {"dedicated", "pool", "evidence"}
                or isolated["dedicated"] is not True):
            raise ValueError("Protection-independent training pool required")
        _text(isolated["pool"])
        _text(isolated["evidence"])
        if set(policy["reservation"]) != set(USAGE_DIMENSIONS) or set(policy["controls"]) != set(USAGE_DIMENSIONS):
            raise ValueError("Every training dimension must be explicit")
        reservation = UsageAmounts(**policy["reservation"])
        if reservation.requests != 1 or reservation.concurrency != 1 or not reservation.bytes:
            raise ValueError("Complete send reservation required")
        if any(policy["controls"][key] not in {"hard-provider", "hard-local", "not-applicable"}
               or policy["controls"][key] == "not-applicable" and getattr(reservation, key)
               for key in USAGE_DIMENSIONS):
            raise ValueError("Qualified deployment controls required")
        tariff = TariffSnapshot.from_dict(policy["tariff"])
        if (tariff.provider_id, tariff.model, tariff.model_revision) != (
                connection.provider_id, connection.model, policy["model_revision"]):
            raise ValueError("Tariff identity mismatch")
        budget = policy["budget"]
        if set(budget["limits"]) != set(USAGE_DIMENSIONS):
            raise ValueError("Every budget dimension must be explicit")
        budget_value = BudgetPolicy(connection.ref, budget["currency"], datetime.fromisoformat(budget["window_start"]),
                                    datetime.fromisoformat(budget["window_end"]), budget["limits"])
        return connection, budget_value

    def configure_backend(self, connection_id: str, policy: dict[str, Any], *, expected_revision: int) -> None:
        """Commit explicitly supplied policy; no training, export or load occurs."""
        connection, budget_value = self.backend_configuration(connection_id, policy)
        dispatcher = self.owner.dispatcher()
        dispatcher.configure_group(policy["quota_group"], policy["budget"], 0)
        with dispatcher.store.dispatch_binding(connection.ref, expected_etag=policy["connection_revision"]):
            dispatcher.ledger.configure_admission("admission:" + connection_id,
                {**policy, "role": "training", "protocol": "unsloth_training"}, budget_value,
                expected_revision=expected_revision)

    def _policy(self, connection_id: str) -> dict[str, Any]:
        _, value = self.owner.dispatcher().ledger.control("admission:" + connection_id)
        if not value or value.get("protocol") != "unsloth_training" or value["version"] != UNSLOTH_PIN:
            raise ValueError("Training workload not configured")
        return value

    def recipient(self, connection_id: str) -> Recipient:
        policy = self._policy(connection_id)
        connection = self.owner.dispatcher()._connection(connection_id, policy["connection_revision"])
        return self._recipient(connection, policy)

    @staticmethod
    def _recipient(connection: Any, policy: dict[str, Any]) -> Recipient:
        version = connection.secret_version
        if version is None or not version.present:
            raise ValueError("Exact destination credential required")
        return Recipient(connection.ref, policy["connection_revision"], policy["principal"],
                         f"{version.store_incarnation}:{version.binding_id}:{version.generation}",
                         connection.auth_mode, connection.endpoint.rstrip("/") + "/api/train/start",
                         policy["region"], policy["terms_revision"], connection.model, policy["model_revision"],
                         "training.start", ())

    @staticmethod
    def _payload(payload: dict[str, Any]) -> None:
        # Accept only an explicitly registered remote Hugging Face dataset.
        # Local path handles, resume, recipes and uploads need separate adapters.
        fields = {"model_name", "training_type", "format_type", "hf_dataset", "is_decision"}
        if type(payload) is not dict or set(payload) - fields or not fields - {"is_decision"} <= payload.keys():
            raise ValueError("Unsupported dataset/recipe/export field")
        if not re.fullmatch(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+", payload["hf_dataset"]):
            raise ValueError("Registered remote dataset handle required; no client-local upload")
        for key in fields - {"is_decision"}:
            _text(payload[key])
        if "is_decision" in payload and type(payload["is_decision"]) is not bool:
            raise ValueError("Decision selection must be boolean")

    def _rights(self, manifest: dict[str, Any], versions: list[str]) -> bool:
        runtime = self.owner.app.config.get("KNOWLEDGE_RUNTIME")
        if runtime is None or set(versions) != {member["record_id"] for member in manifest["members"]}:
            return False
        try:
            for member in manifest["members"]:
                version = member["record_id"]
                runtime.store._require_eligible(version)
                rights = runtime.ledger.get_event(version).rights
                if (rights.digest != member["rights_hash"] or any(
                    getattr(rights.rights, key) is not PermissionState.ALLOWED
                    for key in ("training_distillation", "output_use", "retention"))):
                    return False
            return True
        except Exception:
            return False

    def prepare(self, identity: str, *, actor: str, run_id: str, connection_id: str, payload: dict[str, Any],
                grant_id: str, batch_id: str, rights_versions: list[str]) -> None:
        """Bind one remote dataset request to existing immutable consent evidence."""
        _text(identity)
        self._payload(payload)
        if self.owner.runs.scope(run_id).actor != actor:
            raise ValueError("Run owner mismatch")
        consent = self.consent()
        grant = consent.status(grant_id)["grant"]
        batch = consent.manifest(batch_id)
        policy = self._policy(connection_id)
        recipient = self.recipient(connection_id)
        wire = canonical({**payload, "start_request_id": identity}).encode()
        if (grant["approver"] != actor or grant["recipient"] != recipient.to_dict()
                or grant["scope_hash"] != batch["scope_hash"] or run_id not in grant["scope"]["runs"]
                or batch["payload_hash"] != hashlib.sha256(wire).hexdigest()
                or not self._rights(batch, rights_versions)):
            raise ValueError("Exact scope, wire manifest and current rights required")
        self.owner.dispatcher().ledger.configure_control("training-request:" + identity,
            {"actor": actor, "run_id": run_id, "connection_id": connection_id, "payload": payload,
             "grant_id": grant_id, "batch_id": batch_id, "rights_versions": rights_versions,
             "policy_digest": digest(policy), "recipient": recipient.to_dict()}, expected_revision=0)

    def _request(self, identity: str) -> dict[str, Any]:
        value = self.owner.dispatcher().ledger.control("training-request:" + identity)[1]
        if value is None:
            raise ValueError("Training request not prepared by core")
        return value

    def _jobs(self, identity: str, actor: str) -> TrainingJobs:
        value = self._request(identity)
        policy = self._policy(value["connection_id"])
        backend = UnslothTrainingBackend(version=policy["version"], principal_role=policy["principal_role"],
            capacity_isolated=policy["isolation"]["dedicated"],
            gateway=lambda operation, method, path, payload: self._send(identity, actor, operation, method, path, payload))
        return TrainingJobs(self.path, backend)

    def get(self, identity: str) -> dict[str, Any]:
        value = self._request(identity)
        return self._jobs(identity, value["actor"]).get(identity)

    def provenance(self, identity: str) -> dict[str, Any]:
        """Validate portable job/dataset/send lineage, never assert exported weights.

        Pinned Studio export responses expose paths; decision exports add a
        source-subset fingerprint, not exported-file digests or served readback.
        Resource provenance attests input snapshots, not resulting weights.
        """
        value = self._request(identity)
        job = self.get(identity)
        manifest = self.consent().manifest(value["batch_id"])
        attempt = self.consent().receipt("training:" + identity)
        lineage = {"dataset": value["batch_id"], "run_id": value["run_id"]}
        if (job["lineage"] != lineage or job["request_digest"] != digest({"payload": value["payload"],
                "lineage": lineage, "backend": UNSLOTH_PIN}) or attempt["batch_id"] != value["batch_id"]
                or attempt["payload_hash"] != manifest["payload_hash"] or attempt["run_id"] != value["run_id"]
                or attempt["recipient"] != value["recipient"] or attempt["grant_id"] != value["grant_id"]):
            raise ValueError("Training provenance mismatch")
        return {"request_id": identity, "request_digest": job["request_digest"], "backend_version": UNSLOTH_PIN,
                "run_id": value["run_id"], "remote_job_id": job["remote_job_id"], "state": job["state"],
                "dataset": manifest, "send_receipt": attempt, "serving_attestation": "unavailable",
                "exported_artifact_digest": None, "automatic_activation_eligible": False,
                "refusal": "pinned-api-does-not-attest-exported-and-served-weights"}

    def command(self, operation: str, identity: str, *args: Any, actor: str, run_id: str, **kwargs: Any) -> Any:
        value = self._request(identity)
        if (actor, run_id) != (value["actor"], value["run_id"]):
            raise ValueError("Training receipt scope mismatch")
        jobs = self._jobs(identity, actor)
        if operation == "start":
            if (args != (value["payload"],) or kwargs != {"lineage": {"dataset": value["batch_id"], "run_id": run_id}}):
                raise ValueError("Immutable prepared payload/lineage required")
            self._payload(args[0])
            return jobs.start(identity, args[0], **kwargs)
        if operation not in {"get", "cancel", "reconcile"} or args or kwargs:
            raise ValueError("Unsupported training operation")
        return getattr(jobs, operation)(identity)

    def _send(self, identity: str, actor: str, operation: str, method: str, path: str,
              payload: dict[str, Any]) -> dict[str, Any]:
        value = self._request(identity)
        policy = self._policy(value["connection_id"])
        start = operation == "training.start"
        control = {"training.start": "start", "training.status": "reconcile", "training.cancel": "cancel"}[operation]
        with self.owner.runs.fence(value["run_id"], "reasoning"):
            self.owner.authorise(actor, "training", control, identity=None, body={"lineage": {"run_id": value["run_id"]}})
            if digest(policy) != value["policy_digest"]:
                raise ValueError("Training policy changed; no silent credential/config adoption")
            if start and self.owner.now() >= policy["valid_until"]:
                raise ValueError("Training entitlement expired")
            dispatcher = self.owner.dispatcher()
            connection = dispatcher._connection(value["connection_id"], policy["connection_revision"])
            # Hold the exact connection and consent revocation fences through the
            # synchronous bounded send. No worker retains a credential or permit.
            with dispatcher.store.dispatch_binding(connection.ref, expected_etag=policy["connection_revision"]) as (bound, secret):
                recipient = self._recipient(bound, policy)
                if recipient.to_dict() != value["recipient"] or not secret:
                    raise ValueError("Training recipient changed")
                wire = canonical(payload).encode()
                def send() -> dict[str, Any]:
                    with httpx.Client(transport=self.owner.app.config.get("MODEL_TRAINING_TRANSPORT"),
                                      trust_env=False, follow_redirects=False, timeout=policy["timeout_seconds"]) as client:
                        response = client.request(method, bound.endpoint.rstrip("/") + path,
                            headers={"Authorization": "Bearer " + secret, "Content-Type": "application/json"},
                            content=wire if method != "GET" else None)
                        response.raise_for_status()
                        result = response.json()
                    if type(result) is not dict:
                        raise ValueError("Unknown training response")
                    # Never retain remote paths, dataset bodies or another user's
                    # provider-global progress/logs in an exact-job read response.
                    return {key: result[key] for key in ("job_id", "status", "phase")
                            if type(result.get(key)) is str and len(result[key]) <= 256}
                if not start:
                    return send()  # minimal current-owner job control, not export
                return self.consent().dispatch(grant_id=value["grant_id"], batch_id=value["batch_id"],
                    recipient=recipient, current_recipient=lambda: self._recipient(bound, policy),
                    purpose="fine-tuning", operation=operation, payload=wire, attempt_id="training:" + identity,
                    request_id=identity, run_id=value["run_id"], trial_id=identity,
                    reservation=UsageAmounts(**policy["reservation"]), tariff=TariffSnapshot.from_dict(policy["tariff"]),
                    controls=policy["controls"], controls_evidence=policy["controls_evidence"],
                    rights_check=lambda manifest: self._rights(manifest, value["rights_versions"]), send=send)
