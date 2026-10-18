"""Core-owned, non-trading task admission, dispatch and durable receipts.

Only external HTTP varies at the transport seam. Connection custody and usage
remain owned by their existing stores. A configured policy is operator evidence,
not a provider probe or a claim of measured capacity. No tools are executed here.
"""

from __future__ import annotations

import hashlib
import json
import time
from collections.abc import Callable
from datetime import UTC, datetime
from typing import Any
from uuid import uuid4

import httpx

from .service_connection_audit import ConnectionActorContext
from .service_connection_store import ConnectionRevisionConflict, ServiceConnectionStore
from .service_connection_transactions import uuid_text
from .service_task_contracts import TaskContext, TaskRefused
from .service_task_protocols import build_request, decode_response, parse_result, validate_protocol
from .service_usage import BudgetExceeded, ServiceUsageLedger, UsageConflict, UsageUnavailable
from .service_usage_contracts import BudgetPolicy, TariffSnapshot, UsageAmounts, canonical, integer, text, utc


def _instant(value: object) -> datetime:
    if type(value) is not str:
        raise ValueError("timestamp required")
    return utc(datetime.fromisoformat(value))


def _object(value: object, fields: set[str]) -> dict[str, Any]:
    if type(value) is not dict or set(value) != fields:
        raise ValueError("invalid object fields")
    return value


def _digest(value: object) -> str:
    return hashlib.sha256(canonical(value).encode()).hexdigest()


def _budget(value: object, connection: Any) -> BudgetPolicy:
    value = _object(value, {"currency", "window_start", "window_end", "limits"})
    budget = BudgetPolicy(
        connection, value["currency"], _instant(value["window_start"]), _instant(value["window_end"]), value["limits"]
    )
    # This dispatcher cannot inherit the library's unrestricted dimensions.
    if not {"requests", "concurrency", "input_tokens", "output_tokens", "currency_micros"} <= budget.limits.keys():
        raise ValueError("explicit task limits required")
    return budget


class ServiceTaskDispatcher:
    """One synchronous attempt per phase, with no recovery, training or trading.

    ``transport`` is an httpx transport (not a dispatcher replacement). The
    default client uses no environment proxies, redirects or automatic retries.
    """

    def __init__(
        self,
        store: ServiceConnectionStore,
        ledger: ServiceUsageLedger,
        *,
        transport: httpx.BaseTransport | None = None,
        clock: Callable[[], datetime] | None = None,
        monotonic: Callable[[], float] = time.monotonic,
        context_resolver: Any = None,
    ) -> None:
        self.store = store
        self.ledger = ledger
        self.transport = transport
        self.clock = clock or (lambda: datetime.now(UTC))
        self.monotonic = monotonic
        self.context_resolver = context_resolver

    def close(self) -> None:
        """Release owned accounting handles, never refund uncertain requests."""
        self.ledger.close()

    def _connection(self, identifier: str, revision: str | None = None) -> Any:
        connection_id = uuid_text(identifier)
        snapshot = self.store.read_snapshot()
        if revision is not None and revision != snapshot.etag:
            raise TaskRefused("stale_configuration", 412)
        connection = next((row for row in snapshot.connections if row.connection_id == connection_id), None)
        if connection is None:
            raise TaskRefused("connection_not_found", 404)
        return connection

    def configure_group(self, group: str, value: dict[str, Any], revision: int) -> int:
        """Record an explicit shared account limit, not measured capacity."""
        text(group, "quota group")
        # The group has no credentials; use a real connection only to validate
        # the existing unit/period contract.
        snapshot = self.store.read_snapshot()
        if not snapshot.connections:
            raise TaskRefused("connection_not_found", 404)
        _budget(value, snapshot.connections[0].ref)
        return self.ledger.configure_control("quota:" + group, value, expected_revision=revision)

    def configure(self, identifier: str, value: dict[str, Any], revision: int) -> dict[str, Any]:
        """Bind explicit evidence, native controls and budget to an exact revision."""
        value = _object(
            value,
            {
                "connection_revision",
                "enabled",
                "protocol",
                "role",
                "model_revision",
                "qualification",
                "entitlement",
                "privacy",
                "efforts",
                "hard_controls",
                "quota_group",
                "downstream",
                "reservation",
                "tariff",
                "budget",
            },
        )
        connection = self._connection(identifier, value["connection_revision"])
        if type(value["enabled"]) is not bool:
            raise ValueError("invalid enablement")
        validate_protocol(connection, value)
        text(value["model_revision"], "model revision")
        text(value["qualification"], "qualification evidence")
        entitlement = _object(value["entitlement"], {"status", "evidence", "expires_at"})
        if entitlement["status"] not in {"verified", "unknown", "denied"}:
            raise ValueError("invalid entitlement status")
        text(entitlement["evidence"], "entitlement evidence")
        _instant(entitlement["expires_at"])
        privacy = _object(value["privacy"], {"classifications", "retention", "region"})
        if (
            type(privacy["classifications"]) is not list
            or not privacy["classifications"]
            or any(item not in {"public", "private"} for item in privacy["classifications"])
        ):
            raise ValueError("explicit data classifications required")
        if privacy["retention"] not in {"no_training", "zdr"}:
            raise ValueError("unsupported retention policy")
        text(privacy["region"], "privacy region")
        text(value["quota_group"], "quota group")
        tariff = TariffSnapshot.from_dict(value["tariff"])
        if (tariff.provider_id, tariff.model, tariff.model_revision) != (
            connection.provider_id,
            connection.model,
            value["model_revision"],
        ):
            raise ValueError("tariff identity mismatch")
        reservation = UsageAmounts(**value["reservation"])
        if reservation.requests != 1 or reservation.concurrency != 1 or not reservation.input_tokens:
            raise ValueError("complete reservation required")
        if (
            not reservation.output_tokens
            or not reservation.currency_micros
            or tariff.price_dimension != "currency_micros"
        ):
            raise ValueError("explicit token and monetary reservation required")
        if tariff.prices is not None and tariff.quote(reservation) > reservation.currency_micros:
            raise ValueError("under-reserved tariff")
        budget = _budget(value["budget"], connection.ref)
        key = "admission:" + identifier
        # Connection revision/secret changes cannot pass during configuration.
        with self.store.dispatch_binding(connection.ref, expected_etag=value["connection_revision"]):
            payload = json.loads(canonical(value))
            payload["evidence_source"] = "operator"
            configured, payload = self.ledger.configure_admission(key, payload, budget, expected_revision=revision)
        return {"revision": configured, "policy": payload, "measured_capacity": None}

    def admission(self, identifier: str) -> dict[str, Any]:
        """Report configuration separately from entitlement and measured capacity."""
        self._connection(identifier)
        revision, policy = self.ledger.control("admission:" + identifier)
        return {"revision": revision, "policy": policy, "measured_capacity": None}

    def configure_routing(self, value: dict[str, Any], revision: int) -> dict[str, Any]:
        """Pin one non-recursive bootstrap and a bounded exact advisory pool."""
        _object(value, {"bootstrap", "candidates"})
        if type(value["candidates"]) is not list or not 1 <= len(value["candidates"]) <= 32:
            raise ValueError("bounded candidate pool required")
        seen = set()
        for role, selections in (("task_router", [value["bootstrap"]]), ("assistant", value["candidates"])):
            for selection in selections:
                _object(selection, {"connection_id", "connection_revision", "model", "effort"})
                connection = self._connection(selection["connection_id"], selection["connection_revision"])
                _, policy = self.ledger.control("admission:" + selection["connection_id"])
                if policy is None or policy["role"] != role:
                    raise TaskRefused("qualification_missing")
                if connection.model != selection["model"] or selection["effort"] not in policy["efforts"]:
                    raise TaskRefused("model_unsupported", 422)
                key = _digest(selection)
                if key in seen:
                    raise ValueError("duplicate or recursive selection")
                seen.add(key)
        revision = self.ledger.configure_control("routing", value, expected_revision=revision)
        return {"revision": revision, "policy": value}

    def _eligible(
        self, selection: dict[str, Any], task: dict[str, Any], *, role: str = "assistant"
    ) -> tuple[Any, int, dict[str, Any]]:
        _object(selection, {"connection_id", "connection_revision", "model", "effort"})
        connection = self._connection(selection["connection_id"], selection["connection_revision"])
        revision, policy = self.ledger.control("admission:" + selection["connection_id"])
        if policy is None:
            raise TaskRefused("qualification_missing")
        if policy["connection_revision"] != selection["connection_revision"]:
            raise TaskRefused("stale_configuration", 412)
        if policy["role"] != role:
            raise TaskRefused("role_unsupported", 422)
        if not policy["enabled"]:
            raise TaskRefused("connection_disabled")
        if not connection.credential_configured:
            raise TaskRefused("authentication_required", 401)
        if policy["entitlement"]["status"] != "verified":
            raise TaskRefused("entitlement_unverified", 403)
        if _instant(policy["entitlement"]["expires_at"]) <= self.clock():
            raise TaskRefused("entitlement_expired", 403)
        if connection.model != selection["model"]:
            raise TaskRefused("model_unsupported", 422)
        if selection["effort"] not in policy["efforts"]:
            raise TaskRefused("effort_unsupported", 422)
        if task["classification"] not in policy["privacy"]["classifications"]:
            raise TaskRefused("privacy_denied", 403)
        if set(task["required_hard_controls"]) - set(policy["hard_controls"]):
            raise TaskRefused("hard_control_unsupported", 422)
        if task["max_output_tokens"] > policy["reservation"]["output_tokens"]:
            raise TaskRefused("reservation_exceeded")
        # A byte bound is deliberately conservative for UTF-8 text tokenisers.
        if len(task["prompt"].encode()) + 128 > policy["reservation"]["input_tokens"]:
            raise TaskRefused("context_budget_exceeded")
        budget_revision, _ = self.ledger.budget(connection.ref)
        if budget_revision != policy["budget_revision"]:
            raise TaskRefused("stale_budget", 412)
        self.ledger.check_capacity(connection.ref, UsageAmounts(**policy["reservation"]))
        return connection, revision, policy

    def _invoke(
        self,
        selection: dict[str, Any],
        task: dict[str, Any],
        deadline: float,
        receipt: dict[str, Any],
        *,
        role: str = "assistant",
        candidates: dict[str, Any] | None = None,
        expected_policy_revision: int | None = None,
        routing_revision: int | None = None,
        contexts: tuple[TaskContext, ...] = (),
        actor: str = "",
        oauth_actor=None,
        authority_check=None,
    ) -> tuple[str, dict[str, Any]]:
        if expected_policy_revision is not None:
            current_revision, _ = self.ledger.control("admission:" + selection["connection_id"])
            if current_revision != expected_policy_revision:
                raise TaskRefused("stale_configuration", 412)
        connection, revision, policy = self._eligible(selection, task, role=role)
        if connection.auth_mode == "chatgpt_oauth":
            if self.store.oauth is None or oauth_actor is None or authority_check is None:
                raise TaskRefused("oauth_not_configured", 422)
            admitted_revision = revision
            self.store.oauth.prepare(
                str(connection.connection_id), selection["connection_revision"], oauth_actor, authority_check
            )
            connection, revision, policy = self._eligible(selection, task, role=role)
            if revision != admitted_revision:
                raise TaskRefused("stale_configuration", 412)
        tariff = TariffSnapshot.from_dict(policy["tariff"])
        attempt_id = str(uuid4())
        self.ledger.prepare(
            attempt_id=attempt_id,
            connection=connection.ref,
            connection_revision=selection["connection_revision"],
            request_id=task["request_id"],
            run_id="advisory:" + task["request_id"],
            model=connection.model,
            model_revision=policy["model_revision"],
            tariff=tariff,
            reservation=UsageAmounts(**policy["reservation"]),
            conservative_cost_ceiling=policy["reservation"]["currency_micros"] if tariff.prices is None else None,
        )
        try:
            with self.store.dispatch_binding(
                connection.ref,
                expected_etag=selection["connection_revision"],
                oauth_actor=oauth_actor,
                authority_check=authority_check,
            ) as bound:
                if not bound[1]:
                    raise TaskRefused("authentication_required", 401)
                url, headers, body = build_request(connection, policy, task, selection["effort"], bound[1], candidates)
                if len(canonical(body).encode()) > policy["reservation"]["input_tokens"]:
                    raise TaskRefused("context_budget_exceeded")
                if self.monotonic() >= deadline:
                    raise TaskRefused("deadline_exceeded", 408)
                versions = {"admission:" + str(connection.connection_id): revision}
                if routing_revision is not None:
                    versions["routing"] = routing_revision
                if contexts:
                    self.context_resolver.validate_send(
                        contexts=contexts,
                        actor=actor,
                        purpose="assistant",
                        connection=connection.ref,
                        protocol=policy["protocol"],
                    )
                self.ledger.mark_invoked(
                    attempt_id,
                    control_versions=versions,
                    expected_budget_revision=policy["budget_revision"],
                    expires_at=_instant(policy["entitlement"]["expires_at"]),
                )
            with httpx.Client(transport=self.transport, trust_env=False, follow_redirects=False) as client:
                # Stream the bytes for a bounded response and one overall local
                # deadline. Expiry never claims remote cancellation or no charge.
                with client.stream(
                    "POST", url, json=body, headers=headers, timeout=max(0.001, deadline - self.monotonic())
                ) as response:
                    if response.status_code != 200:
                        raise TaskRefused(
                            {
                                401: "authentication_expired",
                                403: "entitlement_denied",
                                402: "provider_quota",
                                429: "provider_quota",
                            }.get(response.status_code, "provider_error"),
                            502,
                        )
                    raw = bytearray()
                    for chunk in response.iter_bytes():
                        if self.monotonic() >= deadline:
                            raise TaskRefused("deadline_exceeded", 408)
                        raw.extend(chunk)
                        if len(raw) > 1_000_000:
                            raise TaskRefused("provider_response_too_large", 502)
            output, observed, evidence = parse_result(
                decode_response(bytes(raw), policy["protocol"]), policy, candidates=candidates
            )
            if tariff.prices is None:
                self.ledger.mark_unknown(attempt_id)
                evidence["accounting"] = "unknown"
            else:
                observed = UsageAmounts(**{**observed.to_dict(), "currency_micros": tariff.quote(observed)})
                self.ledger.settle(attempt_id, observed)
                evidence["accounting"] = "settled"
            if self.monotonic() >= deadline:
                raise TaskRefused("deadline_exceeded", 408)
            evidence.update(
                policy_revision=revision,
                effective_effort=policy["efforts"][selection["effort"]],
                controls={"hard": policy["hard_controls"], "observational": ["currency_micros", "deadline"]},
                qualification=policy["qualification"],
                entitlement_evidence=policy["entitlement"]["evidence"],
            )
            return output, evidence
        finally:
            record = self.ledger.get_attempt(attempt_id)
            if record.state == "PREPARED":
                record = self.ledger.cancel_prepared(attempt_id)
            elif record.state == "INVOKED":
                record = self.ledger.mark_unknown(attempt_id)
            receipt["attempts"].append(record.to_dict())
            # A crash after this checkpoint retains attempts, never resend authority.
            self.ledger.finish_task(task["request_id"], receipt)

    def dispatch(
        self,
        task: dict[str, Any],
        *,
        actor: str,
        oauth_actor: ConnectionActorContext | None = None,
        authority_check: Callable[[], None] | None = None,
    ) -> dict[str, Any]:
        """Run one fixed or decision-routed advisory request without hidden fallback."""
        _object(
            task,
            {
                "request_id",
                "mode",
                "selection",
                "prompt",
                "classification",
                "context_refs",
                "purpose",
                "deadline_ms",
                "max_output_tokens",
                "required_hard_controls",
            },
        )
        uuid_text(task["request_id"])
        if task["mode"] not in {"fixed", "automatic"} or task["purpose"] != "assistant":
            raise TaskRefused("unsupported_task", 422)
        if task["mode"] == "automatic" and task["selection"] is not None:
            raise ValueError("automatic mode does not accept an override")
        if type(task["prompt"]) is not str or not task["prompt"].strip() or len(task["prompt"].encode()) > 65536:
            raise ValueError("bounded prompt required")
        if task["classification"] not in {"public", "private"}:
            raise ValueError("classification required")
        if type(task["context_refs"]) is not list or len(task["context_refs"]) > 16:
            raise ValueError("bounded context references required")
        for reference in task["context_refs"]:
            text(reference, "context reference")
        if len(set(task["context_refs"])) != len(task["context_refs"]):
            raise ValueError("duplicate context reference")
        if type(task["required_hard_controls"]) is not list or any(
            type(item) is not str for item in task["required_hard_controls"]
        ):
            raise ValueError("invalid required controls")
        integer(task["deadline_ms"], "deadline", minimum=1)
        integer(task["max_output_tokens"], "output tokens", minimum=1)
        if task["deadline_ms"] > 120000:
            raise ValueError("deadline too long")
        deadline = self.monotonic() + task["deadline_ms"] / 1000
        first, prior = self.ledger.begin_task(task["request_id"], actor, _digest(task))
        if not first:
            return prior
        receipt = {
            "request_id": task["request_id"],
            "outcome": "pending",
            "code": "outcome_unknown",
            "attempts": [],
            "selection": task["selection"],
            "context": [],
            "mode": task["mode"],
        }
        output = None
        started = self.monotonic()
        try:
            contexts = ()
            if task["context_refs"]:
                if self.context_resolver is None:
                    raise TaskRefused("context_unavailable", 422)
                contexts = self.context_resolver.resolve(
                    references=tuple(task["context_refs"]), actor=actor, purpose="assistant"
                )
                if type(contexts) is not tuple or any(type(item) is not TaskContext for item in contexts):
                    raise TaskRefused("context_contract_error", 422)
                if [item.reference for item in contexts] != task["context_refs"]:
                    raise TaskRefused("context_contract_error", 422)
                for item in contexts:
                    for value in (item.reference, item.version, item.receipt):
                        text(value, "context identity")
                    if item.classification not in {"public", "private"} or type(item.body) is not str or not item.body:
                        raise TaskRefused("context_contract_error", 422)
                classification = (
                    "private" if any(item.classification == "private" for item in contexts) else task["classification"]
                )
                task = {
                    **task,
                    "classification": classification,
                    "prompt": task["prompt"] + "\n\n" + "\n\n".join(item.body for item in contexts),
                }
                receipt["context"] = [
                    {
                        "reference": item.reference,
                        "version": item.version,
                        "body_digest": _digest(item.body),
                        "receipt": item.receipt,
                    }
                    for item in contexts
                ]
            selection = task["selection"]
            selected_revision = None
            routing_revision = None
            if task["mode"] == "automatic":
                routing_revision, routing = self.ledger.control("routing")
                if routing is None:
                    raise TaskRefused("router_unconfigured")
                eligible = {}
                versions = {}
                excluded = []
                for candidate in routing["candidates"]:
                    try:
                        _, revision, _ = self._eligible(candidate, task)
                    except (TaskRefused, BudgetExceeded, UsageUnavailable) as error:
                        excluded.append(getattr(error, "code", "budget_unavailable"))
                        continue
                    opaque = str(uuid4())
                    eligible[opaque] = candidate
                    versions[opaque] = revision
                if not eligible:
                    raise TaskRefused("eligible_pool_empty")
                router_task = {
                    **task,
                    "prompt": "Route this advisory task.",
                    "max_output_tokens": 1,
                    "required_hard_controls": [],
                }
                router_connection, _, router_policy = self._eligible(
                    routing["bootstrap"], router_task, role="task_router"
                )
                for opaque, candidate in tuple(eligible.items()):
                    try:
                        target, _, target_policy = self._eligible(candidate, task)
                        self.ledger.check_sequence_capacity(
                            (router_connection.ref, UsageAmounts(**router_policy["reservation"])),
                            (target.ref, UsageAmounts(**target_policy["reservation"])),
                        )
                    except (TaskRefused, BudgetExceeded, UsageUnavailable):
                        del eligible[opaque]
                        excluded.append("combined_budget_unavailable")
                if not eligible:
                    raise TaskRefused("eligible_pool_empty")
                receipt["routing"] = {
                    "revision": routing_revision,
                    "eligible_set_digest": _digest(eligible),
                    "eligible_count": len(eligible),
                    "excluded": excluded,
                    "bootstrap": routing["bootstrap"],
                }
                choice, evidence = self._invoke(
                    routing["bootstrap"],
                    router_task,
                    deadline,
                    receipt,
                    role="task_router",
                    candidates=eligible,
                    routing_revision=routing_revision,
                    contexts=contexts,
                    actor=actor,
                    oauth_actor=oauth_actor,
                    authority_check=authority_check,
                )
                receipt["routing"].update(evidence)
                if choice == "abstain":
                    raise TaskRefused("router_abstained")
                selection = eligible[choice]
                selected_revision = versions[choice]
                receipt["selection"] = selection
            output, evidence = self._invoke(
                selection,
                task,
                deadline,
                receipt,
                expected_policy_revision=selected_revision,
                routing_revision=routing_revision,
                contexts=contexts,
                actor=actor,
                oauth_actor=oauth_actor,
                authority_check=authority_check,
            )
            receipt.update(evidence)
            receipt.update(outcome="completed", code="ok", output_digest=_digest(output))
        except (
            TaskRefused,
            ConnectionRevisionConflict,
            BudgetExceeded,
            UsageUnavailable,
            UsageConflict,
            httpx.HTTPError,
            ValueError,
            KeyError,
            TypeError,
            IndexError,
        ) as error:
            if isinstance(error, TaskRefused):
                code = error.code
            elif isinstance(error, ConnectionRevisionConflict):
                code = "stale_configuration"
            elif isinstance(error, BudgetExceeded):
                code = "quota_exceeded"
            elif isinstance(error, UsageUnavailable):
                code = "budget_unavailable"
            elif isinstance(error, UsageConflict):
                code = "stale_configuration"
            elif isinstance(error, httpx.HTTPError):
                code = "provider_outcome_unknown"
            else:
                code = "provider_contract_error"
            receipt.update(outcome="refused", code=code)
            output = None
        finally:
            receipt["latency_ms"] = max(0, int((self.monotonic() - started) * 1000))
            self.ledger.finish_task(task["request_id"], receipt)
        return {**receipt, **({"output": output} if output is not None else {})}
