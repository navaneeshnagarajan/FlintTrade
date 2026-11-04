"""Durable bounded-run authority, owned by ExecutionSessions, not a broker book.

Legacy v1 requires independently issued qualification. The versioned mounted
workflow evaluates available canonical observations and installed SDK evidence,
but missing genuine eligibility, history, tariff and custody evidence still
blocks entry. Neither configuration nor an HTTP assertion qualifies a run.
"""
from __future__ import annotations

import hashlib
import json
import math
import re
import sys
import time
from dataclasses import asdict, dataclass
from decimal import Decimal
from pathlib import Path
from typing import Any

from .execution_session import ExecutionSession
from .run_adoption_store import ModelEvidenceDatabase

_SCHEMA = """
CREATE TABLE runs (run_id TEXT PRIMARY KEY, data TEXT NOT NULL);
CREATE TABLE commands (run_id TEXT NOT NULL, command_id TEXT NOT NULL, data TEXT NOT NULL,
 PRIMARY KEY(run_id,command_id));
"""


def _encoded(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False)


def _digest(value: Any) -> str:
    return hashlib.sha256(_encoded(value).encode()).hexdigest()


def _text(value: Any) -> str:
    if type(value) is not str or not re.fullmatch(r"[A-Za-z0-9_.:-]{1,128}", value):
        raise ValueError("exact autonomy identity required")
    return value


def _positive(value: Any, *, integer: bool = False) -> int | float:
    if (type(value) not in {int, float} or not math.isfinite(value) or value <= 0
            or (integer and type(value) is not int)):
        raise ValueError("explicit positive finite limit required")
    return value


@dataclass(frozen=True)
class NativeQualificationEvidence:
    """Verified external attestation supplied only by trusted server composition.

    This record is NOT an operator assertion or a self-attestation by a model.
    The bootstrap must install an independent verifier with current_evidence().
    No production verifier is bundled: native activation remains blocked until
    its broker-specific evidence and custody are implemented and reviewed.
    """

    binding_revision: str
    runtime_fingerprint: str
    evidence_id: str
    provenance: str
    expires_at: float

    def __post_init__(self) -> None:
        for value in (self.binding_revision, self.runtime_fingerprint):
            if type(value) is not str or re.fullmatch(r"[0-9a-f]{64}", value) is None:
                raise ValueError("qualification digest required")
        _text(self.evidence_id)
        _text(self.provenance)
        _positive(self.expires_at)


class NativeDispatchAuthority:
    """Core-local one-use ticket; never accepted from JSON, headers or a model."""

    def __init__(self, owner: NativeAutonomy, row: dict[str, Any], command: dict[str, Any]) -> None:
        self.owner, self.row, self.command = owner, row, command
        self._laya: tuple[Any, object] | None = None
        self._financial_contract_digest: str | None = None

    def request_context(self, body: dict[str, Any], broker: str, account: str) -> Any:
        """Bind a canonical request context to the still-valid native command ticket.

        Args:
            body: JSON request body sent unchanged to the bounded-run route.
            broker: Broker identity that must match the retained command binding.
            account: Exact synthetic account label sent to account setup.

        Returns:
            Agent request context retaining the grant's JTI, actor, account selector and intent source.

        Raises:
            ValueError: The ticket is invalid or the body, broker or exact account was retargeted.
        """
        from flinttrade_engine.request_context import RequestContext
        self.owner._check_ticket(self)
        binding = self.row["binding"]
        if (broker != binding["broker"] or account != binding["account_id"]
                or _digest(body) != _digest(self.command["body"])):
            raise ValueError("native command retargeted")
        return RequestContext(jti=self.row["grant"]["jti"], actor_type="agent", actor_id=binding["actor"],
                              mode="live", selector=binding["account"], intent_source=self.command["source"])

    def read_context(self, body: dict[str, Any], broker: str, account: str) -> Any:
        """Revalidate retained command read authority, without issuing entry rights.

        Full qualification remains at command admission, the producer's existing
        read-budget frontier and canonical mint/invocation. Repeating strategy
        construction for every read-owner metadata check adds no authority fence.

        Args:
            body: Original canonical command body, compared by digest without coercion.
            broker: Broker identity that must match the retained run binding.
            account: Case-sensitive account identity that must match the retained run binding.

        Returns:
            Agent context retaining the existing grant, actor, account selector and intent source.

        Raises:
            ValueError: The ticket, run binding, grant or pending-command authority has retired or changed.
        """
        from flinttrade_engine.request_context import RequestContext

        self.owner.registry.require_native_admission()
        with self.owner.registry.lock, self.owner.db.transaction() as db:
            if self.owner._tickets.get(self.command["source"]) is not self:
                raise ValueError("native ticket missing or consumed")
            row = self.owner._get(db, self.command["run_id"], self.row["operator"])
            binding = row["binding"]
            if (binding != self.row["binding"] or row["revision"] != self.row["revision"]
                    or broker != binding["broker"] or account != binding["account_id"]
                    or _digest(body) != _digest(self.command["body"])
                    or not self.owner._grant_current(row)
                    or self.owner.app.config["SAFETY"].l5_kill.is_active):
                raise ValueError("native read command retired")
            current = json.loads(db.execute(
                "SELECT data FROM commands WHERE run_id=? AND command_id=?",
                (self.command["run_id"], self.command["command_id"])).fetchone()[0])
            self.owner._check_command_authority(db, current, {"pending_admission"})
            return RequestContext(jti=row["grant"]["jti"], actor_type="agent", actor_id=binding["actor"],
                                  mode="live", selector=binding["account"], intent_source=self.command["source"])

    def bind_preparation(self, target: Any, order: Any) -> None:
        """Bind option budgeting to the same real retained native preparation.

        Listing revisions are digests of the complete captured native evidence.
        Broker tokens remain separate from public symbols. Expiry comparison is
        date correspondence only: no native session-close instant is invented.

        Args:
            target: Retained router target carrying the real broker-specific preparation.
            order: Canonical order compared with the preparation's exact captured intent.

        Raises:
            ValueError: The option allocation, native listing, contract or retained intent disagrees.
        """
        if self.row.get("schema_version") != "2-options-1":
            return
        from datetime import datetime
        from fractions import Fraction
        from zoneinfo import ZoneInfo

        from flinttrade_gateway.brokers.dhan import DhanOrderPreparation
        from flinttrade_gateway.brokers.kotakneo_preparation import KotakOrderPreparation

        preparation = getattr(target, "preparation", None)
        expected_type = {"dhan": DhanOrderPreparation, "kotakneo": KotakOrderPreparation}.get(
            self.row["binding"]["broker"])
        contract = self.command.get("financial_contract")
        if expected_type is None or type(preparation) is not expected_type or type(contract) is not dict:
            raise ValueError("exact option financial preparation unavailable")
        evidence = preparation.contract_evidence()
        if type(evidence) is not dict:
            raise ValueError("native option listing unavailable")
        dhan = expected_type is DhanOrderPreparation
        token = evidence.get("security_id" if dhan else "instrument_id")
        strike = evidence.get("strike_price" if dhan else "strike")
        expiry_date = datetime.fromtimestamp(contract["expiry_at_ms"] / 1000, ZoneInfo("Asia/Kolkata")).date()
        if (contract["listing_ref"]["revision"] != _digest(evidence)
                or contract["token"] != token or evidence.get("symbol") != order.symbol
                or contract["exchange"] != evidence.get("exchange") or contract["exchange"] != order.exchange
                or contract["product"] != order.product or contract["units_per_lot"] != evidence.get("lot_size")
                or contract["right"] != evidence.get("option_type") or strike is None
                or Fraction(contract["strike"]) != Fraction(strike)
                or expiry_date.isoformat() != evidence.get("expiry")
                or json.loads(preparation.intent_json) != order.model_dump(mode="json")):
            raise ValueError("option financial allocation differs from retained native listing")
        self._financial_contract_digest = _digest(contract)

    def capture_laya(self) -> None:
        """Pin real factory qualification before a versioned entry decision.

        Raises:
            ValueError: A versioned run lacks the current factory qualification owner or valid captured evidence.
        """
        if self.row.get("schema_version") not in {"2", "2-options-1"}:
            return
        from .laya_qualification import LayaQualificationOwner

        producer = self.owner.app.config.get("LAYA_QUALIFICATION_OWNER")
        if type(producer) is not LayaQualificationOwner:
            raise ValueError("factory Laya qualification owner unavailable")
        self._laya = producer, producer.capture()

    def _revalidate_laya(self) -> None:
        if (self.row.get("schema_version") == "2-options-1" and self.command.get("operation") != "cancel"
                and self._financial_contract_digest != _digest(self.command.get("financial_contract"))):
            raise ValueError("option allocation has no retained native preparation")
        if self.row.get("schema_version") in {"2", "2-options-1"} and self.command.get("operation") != "cancel":
            if self._laya is None:
                raise ValueError("entry has no retained Laya qualification")
            producer, captured = self._laya
            producer.revalidate(captured)

    def on_invoke(self) -> None:
        """Recheck expiry/revocation/current scope at the actual write frontier."""
        with self.owner.registry.lock:
            self.owner._check_ticket(self, states={"admitted"})
            self._revalidate_laya()
            self.owner._transition(self.command, "dispatched", cause="adapter_invocation_started")
            self.owner._tickets.pop(self.command["source"])

    def on_admitted(self) -> None:
        """Record admission only after canonical risk and gate checks passed."""
        with self.owner.registry.lock:
            self.owner._check_ticket(self, states={"pending_admission"})
            self._revalidate_laya()
            self.owner._transition(self.command, "admitted", cause="canonical_risk_and_gate_admitted")

    def check_account(self) -> None:
        """Recheck canonical books under the shared account admission lease."""
        with self.owner.registry.lock:
            self.owner._check_ticket(self)
            revision = self.owner._observation_revision(self.row)
        books = self.owner._books(self.row)
        with self.owner.registry.lock:
            self.owner._revalidate_observation(self.row, revision, entry=True)
            self.owner._check_ticket(self)
        if self.command.get("operation") == "cancel":
            self.owner._cancel_observation(books, self.command)
            return
        if any((books.positions, books.holdings, books.orders, books.trades)):
            raise ValueError("shared account changed; no allocation is inferred")


class NativeExecutionPort:
    """Least-privileged producer interface: no token, grant or broker methods."""

    __slots__ = ("__submit",)

    def __init__(self, submit: Any) -> None:
        self.__submit = submit

    def submit(self, command: dict[str, Any]) -> dict[str, Any]:
        """Submit through the retained scoped callback without exposing grant controls.

        Args:
            command: Original bounded command body whose scope and revision are retained.

        Returns:
            The authority owner's command disposition; acknowledgement alone does not prove a fill.

        Raises:
            ValueError: The retained scope, grant or command no longer admits submission.
        """
        return self.__submit(command)


class NativeRecoveryAssessment:
    """Same-owner volatile witness retained only by an existing account attempt."""

    def __init__(self, owner: Any, request: Any, census: str, run_ids: tuple[str, ...]) -> None:
        """Retain the complete owner-issued census for one exact account request."""
        self.owner, self.request, self.census, self.run_ids = owner, request, census, run_ids


class NativeAutonomy:
    """Registry child: grants and command receipts, never synthetic balances."""

    @staticmethod
    def storage_present(path: Path) -> bool:
        """Either custody member requires inspection; incomplete is not absent.

        ModelEvidenceDatabase remains the sole integrity/custody validator.
        Never let a missing marker hide an established database from lifecycle
        retirement, or recreate a missing database beside its surviving marker.
        """
        from .secure_file import HeldOwnerDirectory
        with HeldOwnerDirectory(path) as directory:
            return directory.exists("autonomy.sqlite") or directory.exists("autonomy.sqlite.authority.json")

    def __init__(self, registry: Any) -> None:
        self.registry, self.app = registry, registry.app
        from .native_workflow_v2 import NativeWorkflowV2
        self.v2 = NativeWorkflowV2(self)
        self._tickets: dict[str, NativeDispatchAuthority] = {}
        # A restored setting cannot resurrect observed-stale evidence. Across
        # owner restart the durable recovery transaction retires ALL authority.
        self._retired_evidence: set[str] = set()
        self.db = ModelEvidenceDatabase(registry.path / "autonomy.sqlite", _SCHEMA)
        with self.db.transaction() as db:
            for identity, data in db.execute("SELECT run_id,data FROM runs").fetchall():
                row = json.loads(data)
                if type(row) is not dict or row.get("schema_version") not in {None, "2", "2-options-1"}:
                    raise ValueError("unsupported native authority storage version")
                if row.get("grant") is not None:
                    row["grant"]["revoked"] = True
                row.update(qualification=None, state="reconciliation_required")
                if row.get("schema_version") in {"2", "2-options-1"}:
                    row["entry_state"] = "retired"
                    if row["producer_state"] in {"running", "stopping"}:
                        row["producer_state"] = "stopped"
                db.execute("UPDATE runs SET data=? WHERE run_id=?", (_encoded(row), identity))
            for run, identity, data in db.execute("SELECT run_id,command_id,data FROM commands").fetchall():
                command = json.loads(data)
                if command["state"] not in {"settled", "refused"}:
                    command["state"] = "reconciling"
                    command["cause"] = (
                        command["cause"] if self._completion_conflict(command) else "owner_restarted_no_replay"
                    )
                    db.execute("UPDATE commands SET data=? WHERE run_id=? AND command_id=?",
                               (_encoded(command), run, identity))

    def _operator(self, token: str, *, live: bool = False, write: bool = True) -> tuple[Any, dict[str, Any]]:
        from .auth_routes import decode_token, verify_operator_session_token
        self.registry._require()
        with self.app.app_context():
            who = verify_operator_session_token(token)
            claims = decode_token(token)
        action = "write" if write else "read"
        if "admin.accounts." + action not in who.scopes or "admin.services." + action not in who.scopes:
            raise ValueError("operator scope required")
        if live and (claims.get("mode") != "live" or claims.get("live_mode_unlocked") is not True):
            raise ValueError("unlocked Live operator required")
        return who, claims

    def _get(self, db: Any, run_id: str, actor: str) -> dict[str, Any]:
        self.registry._require()
        found = db.execute("SELECT data FROM runs WHERE run_id=?", (run_id,)).fetchone()
        if found is None:
            raise ValueError("native run unavailable")
        row = json.loads(found[0])
        if row["operator"] != actor:
            raise ValueError("native run not owned")
        scope = self.registry.scope(run_id, actor)
        if scope.account != row["binding"]["account"] or scope.environment != "live":
            raise ValueError("native registry binding changed")
        return row

    def _legacy_get(self, db: Any, run_id: str, actor: str) -> dict[str, Any]:
        """Keep legacy entry/read owners outside versioned producer custody."""
        row = self._get(db, run_id, actor)
        if row.get("schema_version") is not None:
            raise ValueError("versioned native run requires its versioned owner")
        return row

    def require_empty_account_custody(self, live_ids: set[str]) -> None:
        """Refuse every real command, financial, permission, ticket and worker duty."""
        from .native_financial_v2 import has_financial_obligations

        with self.db.transaction() as db:
            rows = [json.loads(raw[0]) for raw in db.execute("SELECT data FROM runs")]
            commands = [json.loads(raw[0]) for raw in db.execute("SELECT data FROM commands")]
            ids = {row["binding"]["run_id"] for row in rows}
            if live_ids != ids or any(command["run_id"] not in ids for command in commands):
                raise ValueError("native custody orphaned")
            for row in rows:
                self._get(db, row["binding"]["run_id"], row["operator"])
                if has_financial_obligations(row) or row.get("grant") is not None and not row["grant"]["revoked"]:
                    raise ValueError("native financial or permission custody retained")
            if (self._tickets or any(identity in self.registry.owners for identity in ids)
                    or any(c["state"] not in {"settled", "refused"} or c.get("filled_quantity", 0) > 0
                           for c in commands)):
                raise ValueError("native command or worker custody retained")

    def assess_read_only_recovery(self, live_ids: set[str], request: Any, previous: Any = None) -> Any:
        """Assess exact retained custody inside the real account mutation lane.

        Revocation is durable. Drained workers may remain retained; active
        invocation/model tickets never permit replacement. The returned witness
        binds this owner, request, workspace and full unchanged duty census.
        """
        from .account_lifecycle_contracts import AccountMutationKind, AccountMutationRequest
        from .native_producer_v2 import NativeProducerOwner

        if type(request) is not AccountMutationRequest or request.kind is not AccountMutationKind.RECONNECT:
            raise ValueError("read_only_recovery_requires_reconnect")
        if previous is None:
            try:
                self.require_empty_account_custody(live_ids)
                return None
            except ValueError:
                pass  # Continue through the same strict store/owner census, never assume emptiness.
        with self.db.transaction() as db:
            rows = [json.loads(raw[0]) for raw in db.execute("SELECT data FROM runs ORDER BY run_id")]
            commands = [
                json.loads(raw[0]) for raw in db.execute("SELECT data FROM commands ORDER BY run_id,command_id")
            ]
            ids = {row["binding"]["run_id"] for row in rows}
            if not ids or live_ids != ids or any(command["run_id"] not in ids for command in commands):
                raise ValueError("native_recovery_custody_incomplete")
            for row in rows:
                self.v2._get(db, row["binding"]["run_id"], row["operator"])
                expected = {"broker": request.selector.adapter_id, "account_id": request.selector.account_id,
                            "workspace_instance_id": str(request.expected_workspace.instance_id)}
                if (row.get("native_identity") != expected or row["binding"]["broker"] != request.selector.adapter_id
                        or row["binding"]["account_id"] != request.selector.account_id
                        or row["operator"] != request.actor.actor):
                    raise ValueError("native_recovery_identity_unavailable")
        if previous is None:
            for row in rows:
                self.retire(self.registry.scope(row["binding"]["run_id"], row["operator"]))
        if self._tickets:
            raise ValueError("native_recovery_invocation_owned")
        for identity, owner in self.registry.owners.items():
            if identity in ids and (type(owner) is not NativeProducerOwner or not owner.shutdown(0)):
                raise ValueError("native_recovery_worker_owned")
        with self.db.transaction() as db:
            rows = [json.loads(raw[0]) for raw in db.execute("SELECT data FROM runs ORDER BY run_id")]
            if any(row["entry_state"] != "retired" or row.get("grant") is not None and not row["grant"]["revoked"]
                   for row in rows):
                raise ValueError("native_recovery_authority_retained")
            registry_rows = [self.registry._get(self.registry.scope(row["binding"]["run_id"], row["operator"]))
                             for row in rows]
            census = _digest([rows, commands, registry_rows,
                              [(identity, id(self.registry.owners.get(identity))) for identity in sorted(ids)]])
        if previous is not None:
            if (type(previous) is not NativeRecoveryAssessment or previous.owner is not self
                    or previous.request != request or previous.census != census
                    or previous.run_ids != tuple(sorted(ids))):
                raise ValueError("native_recovery_census_changed")
            return previous
        return NativeRecoveryAssessment(self, request, census, tuple(sorted(ids)))

    def record_read_only_recovery(self, assessment: Any, version: Any) -> None:
        """Issue read-only correspondence without replacing historical write pins.

        Called only by the existing account publication fence after the exact
        verified candidate is installed. Every later read still revalidates the
        current provider/registry/version and permanently restricted session.
        """
        from .account_mutation_contracts import SessionVersion
        if (type(assessment) is not NativeRecoveryAssessment or assessment.owner is not self
                or type(version) is not SessionVersion or version.selector != assessment.request.selector):
            raise ValueError("native_recovery_publication_mismatch")
        with self.db.transaction() as db:
            for identity in assessment.run_ids:
                row = self._get(db, identity, assessment.request.actor.actor)
                old_pin = row["account_pin"]
                row["read_only_recovery"] = {
                    "operation_id": str(assessment.request.operation_id), "census": assessment.census,
                    "historical_binding": _digest(old_pin), "native_identity": row["native_identity"],
                    "account_pin": {**old_pin,
                        "registry_incarnation": str(version.registry_version.registry_incarnation),
                        "registry_generation": version.registry_version.generation,
                        "vault_incarnation": str(version.credential_version.vault_incarnation),
                        "credential_generation": version.credential_version.generation,
                        "workspace_instance_id": str(version.workspace_version.instance_id),
                        "workspace_generation": version.workspace_version.generation,
                        "broker_workspace_generation": version.broker_workspace_version.generation},
                }
                self._save(db, row)

    def _save(self, db: Any, row: dict[str, Any]) -> None:
        db.execute("UPDATE runs SET data=? WHERE run_id=?", (_encoded(row), row["binding"]["run_id"]))

    def create(self, token: str, config: dict[str, Any]) -> dict[str, Any]:
        """Reserve a native identity without arming a producer or touching a broker."""
        who, _claims = self._operator(token, live=True)
        keys = {"run_id", "broker", "account_id", "strategy_revision", "config_revision", "policy_revision",
                "provider_revision"}
        if type(config) is not dict or set(config) != keys:
            raise ValueError("exact native configuration required")
        config = {k: _text(v) for k, v in config.items()}
        from .broker_identity import parse_broker_selector
        parse_broker_selector(config["broker"] + ":" + config["account_id"])
        run_id = config["run_id"]
        binding = {**config, "actor": "bounded:" + run_id,
                   "account": config["broker"] + ":" + config["account_id"], "environment": "live"}
        scope = ExecutionSession(run_id, who.actor_ref, binding["account"], "live")
        with self.registry.lock:
            self.registry.create(scope, kind="strategy", config=config)
            row = {"binding": binding, "operator": who.actor_ref, "revision": _digest(binding),
                   "state": "configured", "qualification": None, "grant": None}
            with self.db.transaction() as db:
                db.execute("INSERT INTO runs VALUES (?,?)", (run_id, _encoded(row)))
        return self.status(token, run_id)

    def status(self, token: str, run_id: str) -> dict[str, Any]:
        """Return durable observations, never infer flatness from worker state."""
        who, _claims = self._operator(token, write=False)
        with self.registry.lock, self.db.transaction() as db:
            row = self._legacy_get(db, run_id, who.actor_ref)
            commands = [json.loads(value[0]) for value in db.execute(
                "SELECT data FROM commands WHERE run_id=? ORDER BY command_id", (run_id,))]
        return self._public(row, commands)

    def projection(self, scope: ExecutionSession) -> dict[str, Any] | None:
        """Attach native receipts to the existing registry's exact read model."""
        with self.registry.lock, self.db.transaction() as db:
            if db.execute("SELECT 1 FROM runs WHERE run_id=?", (scope.run_id,)).fetchone() is None:
                return None
            row = self._get(db, scope.run_id, scope.actor)
            if scope.environment != "live" or scope.account != row["binding"]["account"]:
                raise ValueError("native projection scope mismatch")
            commands = [json.loads(value[0]) for value in db.execute(
                "SELECT data FROM commands WHERE run_id=? ORDER BY command_id", (scope.run_id,))]
        return self._public(row, commands)

    def _public(self, row: dict[str, Any], commands: list[dict[str, Any]]) -> dict[str, Any]:
        if row.get("schema_version") in {"2", "2-options-1"}:
            return self.v2.view(row)
        qualified = self._qualified(row)
        blocker = self._entry_blocker(row)
        authorised = blocker is None
        obligations = [c["command_id"] for c in commands if c["state"] not in {"settled", "refused"}]
        if row["grant"] is not None:
            row["grant"] = {key: value for key, value in row["grant"].items() if key not in {"jti", "session_binding"}}
        state = "entries_stopped" if blocker == "kill_switch_latched" else row["state"]
        return {**row, "state": state, "configured": True, "qualified": qualified, "authorised": authorised,
                "native_ready": authorised and not obligations, "commands": commands,
                "admission_reason": blocker or ("reconciliation_required" if obligations 
                    else "canonical_admission_required"),
                "obligations": obligations,
                "protection": "operator_handback_required" if obligations else "not_granted",
                "admission_required": True,
                "qualification_reason": "current_server_evidence" if qualified else "server_qualification_required"}

    def qualification_binding(self, run_id: str) -> str:
        """Read the server runtime binding for the independent evidence verifier.

        Process identities intentionally invalidate old attestations on restart.
        This method grants no authority and does not write evidence.
        """
        from flinttrade_engine.local_state_provider import OrderLifecycleLedger
        from flinttrade_engine.safety import SafetyGate
        from flinttrade_gateway.router import BrokerRouter

        from .safety_config import require_ready_safety
        self.registry._require()
        config = self.app.config["NATIVE_AUTONOMY_BINDINGS"][run_id]
        router = self.app.config["BROKER_ROUTER"]
        source = self.app.config["NATIVE_ADAPTERS"][config["broker"]]
        registry = self.app.config["REGISTRY"]
        session = registry.get_session_for(config["broker"], config["account_id"])
        if (type(router) is not BrokerRouter or router.backend_lease_proof is not self.registry.proof
                or self.app.config.get("RUNTIME_ACCEPTING_REQUESTS") is not True):
            raise ValueError("native runtime unavailable")
        ledger = self.app.config.get("ORDER_LIFECYCLE_LEDGER")
        if (type(ledger) is not OrderLifecycleLedger or router._lifecycle_store is not ledger
                or type(getattr(router._consume_gate, "__self__", None)) is not SafetyGate
                or getattr(router._consume_gate, "__func__", None) is not SafetyGate.consume):
            raise ValueError("canonical durable lifecycle and one-shot gate required")
        writer = router._adapters[config["broker"]]
        from . import order_routes
        modules = {__name__, order_routes.__name__, type(source).__module__, type(writer).__module__,
                   type(router).__module__, "flinttrade_engine.safety"}
        source_identity = {}
        for name in sorted(modules):
            path = vars(sys.modules[name]).get("__file__")
            if type(path) is not str:
                raise ValueError("runtime source identity unavailable")
            source_identity[name] = hashlib.sha256(Path(path).read_bytes()).hexdigest()
        safety = require_ready_safety(self.app.config)
        return _digest({"config": config, "backend": str(self.registry.proof.incarnation),
                        "owner": id(self), "router": id(router), "source": id(source), "registry": id(registry),
                        "writer": id(writer), "source_identity": source_identity, "python": sys.version,
                        "session": id(session), "safety": asdict(safety.snapshot_config()),
                        "qualifier": id(self.app.config.get("NATIVE_AUTONOMY_QUALIFIER"))})

    def _evidence(self, row: dict[str, Any]) -> dict[str, Any]:
        binding = row["binding"]
        config = self.app.config["NATIVE_AUTONOMY_BINDINGS"][binding["run_id"]]
        if any(binding.get(key) != value for key, value in config.items()) or set(config) != {
            "run_id", "broker", "account_id", "strategy_revision", "config_revision", "policy_revision",
                "provider_revision"
        }:
            raise ValueError("configured binding changed")
        evidence = self.app.config["NATIVE_AUTONOMY_QUALIFIER"].current_evidence()
        if type(evidence) is not NativeQualificationEvidence:
            raise ValueError("independent evidence unavailable")
        evidence.__post_init__()
        if (evidence.binding_revision != row["revision"] or evidence.expires_at <= time.time()
                or evidence.runtime_fingerprint != self.qualification_binding(binding["run_id"])):
            raise ValueError("qualification binding changed")
        return asdict(evidence)

    def _qualified(self, row: dict[str, Any]) -> bool:
        if row.get("schema_version") in {"2", "2-options-1"}:
            try:
                self.v2.require_qualification(row, row["grant"]["claims"])
                return True
            except (ValueError, TypeError, KeyError):
                return False
        qualification = row["qualification"]
        if qualification is None or _digest(qualification) in self._retired_evidence:
            return False
        try:
            if qualification == self._evidence(row):
                return True
        except Exception:
            pass
        self._retired_evidence.add(_digest(qualification))
        return False

    def _grant_current(self, row: dict[str, Any]) -> bool:
        from .auth_routes import _is_jti_revoked
        grant = row["grant"]
        try:
            return bool(grant is not None and not grant["revoked"]
                        and time.time() < min(grant["expires_at"], grant["session_expires_at"])
                        and grant["binding_revision"] == row["revision"]
                        and grant["qualification"] == (row["report_v2"]["report_ref"]
                            if row.get("schema_version") in {"2", "2-options-1"} else row["qualification"])
                        and (row.get("schema_version") not in {"2", "2-options-1"}
                             or row.get("grant_kill_epoch") == self.v2.kill_epoch())
                        and not _is_jti_revoked(grant["jti"]))
        except Exception:
            return False

    def qualify(self, token: str, run_id: str) -> dict[str, Any]:
        """Qualification requires server-owned current evidence, never HTTP claims."""
        who, _claims = self._operator(token, live=True)
        with self.registry.lock, self.db.transaction() as db:
            row = self._legacy_get(db, run_id, who.actor_ref)
            try:
                row["qualification"] = self._evidence(row)
                if _digest(row["qualification"]) in self._retired_evidence:
                    raise ValueError("retired evidence requires new independent qualification")
            except Exception:
                raise ValueError("server qualification unavailable") from None
            row["state"] = "qualified"
            self._save(db, row)
        return self.status(token, run_id)

    def grant(self, token: str, run_id: str, body: dict[str, Any]) -> dict[str, Any]:
        """Issue explicit finite authority; no producer-facing grant method."""
        who, claims = self._operator(token, live=True)
        keys = {"grant_id", "expires_at", "instruments", "actions", "max_order_quantity", "max_total_quantity",
                "max_total_notional", "max_loss", "max_commands"}
        if type(body) is not dict or set(body) != keys:
            raise ValueError("exact grant fields required")
        body = json.loads(_encoded(body))
        _text(body["grant_id"])
        for key in keys - {"grant_id", "instruments", "actions"}:
            _positive(body[key], integer=key in {"max_order_quantity", "max_total_quantity", "max_commands"})
        if (not time.time() < body["expires_at"] <= min(time.time() + 86400, claims["exp"])
                or body["max_order_quantity"] > body["max_total_quantity"]
                or body["max_loss"] < body["max_total_notional"]
                or body["actions"] not in (["place"], ["place", "cancel"])):
            raise ValueError("unsupported bounded policy")
        instruments = body["instruments"]
        if type(instruments) is not list or not 1 <= len(instruments) <= 20:
            raise ValueError("bounded instruments required")
        for instrument in instruments:
            if (type(instrument) is not dict or set(instrument) != {"symbol", "exchange"}
                    or instrument["exchange"] not in {"NSE", "BSE"}):
                raise ValueError("cash instruments only")
            _text(instrument["symbol"])
        with self.registry.lock, self.db.transaction() as db:
            row = self._legacy_get(db, run_id, who.actor_ref)
            if not self._qualified(row) or row["grant"] is not None:
                raise ValueError("qualification required; grants are not replaceable")
            row["grant"] = {**body, "operator": who.actor_ref, "session_binding": who.session_binding,
                            "jti": claims["jti"], "session_expires_at": claims["exp"],
                            "binding_revision": row["revision"], "qualification": row["qualification"],
                                "revoked": False}
            row["state"] = "authorised"
            self._save(db, row)
        return self.status(token, run_id)

    def revoke(self, token: str, run_id: str, grant_id: str) -> dict[str, Any]:
        """Retire entries, not ownership, protection, broker orders or exposure."""
        who, _claims = self._operator(token)
        with self.registry.lock, self.db.transaction() as db:
            row = self._legacy_get(db, run_id, who.actor_ref)
            if row["grant"] is None or row["grant"]["grant_id"] != grant_id:
                raise ValueError("exact grant required")
            row["grant"]["revoked"] = True
            row["state"] = "entries_stopped"
            self._save(db, row)
        return self.status(token, run_id)

    def port(self, token: str, run_id: str) -> NativeExecutionPort:
        """Bind a producer to one immutable run; do not pass it operator tokens."""
        who, _claims = self._operator(token, live=True)
        with self.registry.lock, self.db.transaction() as db:
            row = self._legacy_get(db, run_id, who.actor_ref)
            self._entry_authority(row)
        return NativeExecutionPort(lambda command: self._submit(run_id, who.actor_ref, command))

    def retire(self, scope: ExecutionSession) -> None:
        """Existing registry stop retires native permission without liquidation."""
        if self.registry.scope(scope.run_id, scope.actor) != scope:
            raise ValueError("native retirement scope mismatch")
        with self.registry.lock, self.db.transaction() as db:
            if db.execute("SELECT 1 FROM runs WHERE run_id=?", (scope.run_id,)).fetchone() is None:
                return
            row = self._get(db, scope.run_id, scope.actor)
            if row["grant"] is not None:
                row["grant"]["revoked"] = True
            row.update(state="entries_stopped", qualification=None)
            if row.get("schema_version") in {"2", "2-options-1"}:
                row["entry_state"] = "retired"
                from .native_producer_v2 import NativeProducerOwner

                owner = self.registry.owners.get(scope.run_id)
                if type(owner) is NativeProducerOwner:
                    owner.stop.set()
                    if owner.thread is not None and owner.thread.is_alive():
                        row["producer_state"] = "stopping"
            self._save(db, row)

    def retire_all(self, *, actor: str | None = None) -> bool:
        """Logout/drain keeps every unresolved obligation; no flatness inference."""
        with self.registry.lock, self.db.transaction() as db:
            rows = [json.loads(r[0]) for r in db.execute("SELECT data FROM runs")]
        scopes = [self.registry.scope(row["binding"]["run_id"], row["operator"])
                  for row in rows if actor is None or row["operator"] == actor]
        for scope in scopes:
            self.retire(scope)
        with self.db.transaction() as db:
            commands = [json.loads(r[0]) for r in db.execute("SELECT data FROM commands")]
        ids = {scope.run_id for scope in scopes}
        from .native_financial_v2 import has_financial_obligations

        with self.db.transaction() as db:
            current = [json.loads(value[0]) for value in db.execute("SELECT data FROM runs")]
        return (not any(c["run_id"] in ids and c["state"] not in {"settled", "refused"} for c in commands)
                and not any(row["binding"]["run_id"] in ids and has_financial_obligations(row) for row in current))

    def submit(self, token: str, run_id: str, command: dict[str, Any]) -> dict[str, Any]:
        """Authenticated command ingress; identical durable replay does no I/O."""
        who, _claims = self._operator(token, live=True)
        return self._submit(run_id, who.actor_ref, command)

    def _entry_authority(self, row: dict[str, Any]) -> None:
        blocker = self._entry_blocker(row)
        if blocker is not None:
            raise ValueError(blocker)

    def _entry_blocker(self, row: dict[str, Any]) -> str | None:
        """One effective-authority decision for inspection and command ingress."""
        self.registry.require_native_admission()
        if row.get("schema_version") in {"2", "2-options-1"} and row["entry_state"] != "started":
            return "separate_start_required"
        if not self._qualified(row) or not self._grant_current(row):
            return "current_grant_and_qualification_required"
        from .safety_config import require_ready_safety
        try:
            if not require_ready_safety(self.app.config).l5_kill.validate().passed:
                return "kill_switch_latched"
        except Exception:
            return "safety_runtime_unavailable"
        return None

    def _books(self, row: dict[str, Any]) -> Any:
        from .l2_state import _read_accounting_snapshot, _resolve_account_source
        from .order_routes import _run_on_client_loop
        binding = row["binding"]
        source = _resolve_account_source(self.app.config, binding["broker"], binding["account_id"])

        def check_scope() -> None:
            current = _resolve_account_source(self.app.config, binding["broker"], binding["account_id"])
            if (current.target is not source.target or current.session is not source.session
                    or getattr(source.session, "account_id", None) != binding["account_id"]
                    or getattr(source.session, "adapter_id", None) != binding["broker"]):
                raise ValueError("account observation scope changed")

        async def complete_snapshot() -> Any:
            previous = None
            for _attempt in range(3):
                snapshot = await _read_accounting_snapshot(source)
                books = (snapshot.positions, snapshot.holdings, snapshot.orders, snapshot.trades)
                # This bounded slice accepts only complete canonical collections,
                # not absent results, error envelopes, pages or filtered prefixes.
                for book in books:
                    if type(book) is not list or any(type(item) is not dict for item in book):
                        raise ValueError("complete account books unavailable")
                    for item in book:
                        for key, expected in (("account_id", binding["account_id"]),
                                              ("adapter_id", binding["broker"]), ("broker", binding["broker"])):
                            if key in item and item[key] != expected:
                                raise ValueError("account book scope mismatch")
                fingerprint = _encoded(books)
                if fingerprint == previous:
                    return snapshot
                previous = fingerprint
            raise ValueError("account books changed during observation")

        check_scope()
        with self.app.app_context():
            books = _run_on_client_loop(complete_snapshot())
        check_scope()
        return books

    def _transition(self, command: dict[str, Any], state: str, *, cause: str, **fields: Any) -> dict[str, Any]:
        with self.registry.lock, self.db.transaction() as db:
            raw = db.execute("SELECT data FROM commands WHERE run_id=? AND command_id=?",
                             (command["run_id"], command["command_id"])).fetchone()
            current = json.loads(raw[0])
            known_fill = current.get("filled_quantity", 0)
            if fields.get("filled_quantity", known_fill) < known_fill or (
                    known_fill > 0 and state in {"settled", "refused"}):
                fields["filled_quantity"] = known_fill
                state, cause = "reconciling", "broker_evidence_missing_or_conflicting"
            if self._completion_conflict(current):
                state, cause = "reconciling", current["cause"]
            current.update(state=state, cause=cause, updated_at=time.time(), **fields)
            current["events"].append(state)
            db.execute("UPDATE commands SET data=? WHERE run_id=? AND command_id=?",
                       (_encoded(current), command["run_id"], command["command_id"]))
        return current

    def _check_ticket(self, ticket: NativeDispatchAuthority, *, states: set[str] | None = None) -> None:
        if self._tickets.get(ticket.command["source"]) is not ticket:
            raise ValueError("native ticket missing or consumed")
        with self.registry.lock, self.db.transaction() as db:
            row = self._get(db, ticket.command["run_id"], ticket.row["operator"])
            self._entry_authority(row)
            from .native_financial_v2 import has_financial_obligations

            for other_data, in db.execute("SELECT data FROM runs WHERE run_id!=?", (row["binding"]["run_id"],)):
                other = json.loads(other_data)
                if other["binding"]["account"] == row["binding"]["account"] and has_financial_obligations(other):
                    raise ValueError("another run owns unresolved account financial custody")
            current = json.loads(db.execute(
                "SELECT data FROM commands WHERE run_id=? AND command_id=?",
                (ticket.command["run_id"], ticket.command["command_id"])).fetchone()[0])
            self._check_command_authority(db, current, states)

    def _observation_revision(self, row: dict[str, Any]) -> str:
        """Account-scoped optimistic fence; caller holds the registry lock."""
        scope = self.registry.scope(row["binding"]["run_id"], row["operator"])
        generation = self.registry._get(scope)["generation"]
        with self.db.transaction() as db:
            current = self._get(db, scope.run_id, scope.actor)
            commands = []
            for run, command in db.execute(
                    "SELECT runs.data,commands.data FROM runs JOIN commands USING(run_id) "
                    "ORDER BY runs.run_id,commands.command_id"):
                if json.loads(run)["binding"]["account"] == current["binding"]["account"]:
                    commands.append(command)
            account_runs = [json.loads(value[0]) for value in db.execute("SELECT data FROM runs ORDER BY run_id")
                            if json.loads(value[0])["binding"]["account"] == current["binding"]["account"]]
        # SDK-frontier read reservations are monotonic usage, not an account
        # observation or permission change. They are checked independently at
        # every invocation and must not invalidate their own in-flight capture.
        def authority_fields(value: dict[str, Any]) -> dict[str, Any]:
            return {key: item for key, item in value.items() if key != "producer_reads"}

        return _digest([authority_fields(current), generation, commands,
                        [authority_fields(item) for item in account_runs]])

    def _revalidate_observation(self, row: dict[str, Any], revision: str, *, entry: bool = False) -> None:
        if self._observation_revision(row) != revision:
            raise ValueError("account obligations or execution authority changed during observation")
        if entry:
            self._entry_authority(row)

    def _replay(self, run_id: str, identity: str, request: dict[str, Any]) -> dict[str, Any] | None:
        with self.db.transaction() as db:
            raw = db.execute("SELECT data FROM commands WHERE run_id=? AND command_id=?", (run_id, identity)).fetchone()
        if raw is None:
            return None
        previous = json.loads(raw[0])
        if previous["request_digest"] != _digest(request):
            raise ValueError("command identity conflict; never replay")
        return previous

    def _submit(self, run_id: str, actor: str, request: dict[str, Any]) -> dict[str, Any]:
        if type(request) is not dict or set(request) not in (
            {"command_id", "grant_id", "expected_revision", "order"},
            {"command_id", "grant_id", "expected_revision", "cancel"},
        ):
            raise ValueError("exact command fields required")
        request = json.loads(_encoded(request))
        # Both HTTP ingress and previously retained legacy ports use this seam.
        # Nominal v2 commands belong exclusively to the registered producer;
        # reject before replay, book reads, reservations or canonical dispatch.
        with self.registry.lock, self.db.transaction() as db:
            self._legacy_get(db, run_id, actor)
        if "cancel" in request:
            return self._cancel(run_id, actor, request)
        identity = _text(request["command_id"])
        with self.registry.lock:
            with self.db.transaction() as db:
                row = self._get(db, run_id, actor)
                previous = db.execute("SELECT data FROM commands WHERE run_id=? AND command_id=?",
                                      (run_id, identity)).fetchone()
                if previous is not None:
                    previous = json.loads(previous[0])
                    if previous["request_digest"] != _digest(request):
                        raise ValueError("command identity conflict; never replay")
                    return previous
                self._entry_authority(row)
                from .native_financial_v2 import has_financial_obligations

                for other_data, in db.execute("SELECT data FROM runs WHERE run_id!=?", (run_id,)):
                    other_row = json.loads(other_data)
                    if (other_row["binding"]["account"] == row["binding"]["account"]
                            and has_financial_obligations(other_row)):
                        raise ValueError("another run owns unresolved account financial custody")
                # Changing a run ID cannot discard another run's unresolved
                # account obligation. This adds no account/book ledger.
                for other_run, other_command in db.execute(
                    "SELECT runs.data,commands.data FROM runs JOIN commands USING(run_id) WHERE runs.run_id!=?",
                    (run_id,),
                ):
                    other_row, other = json.loads(other_run), json.loads(other_command)
                    if (other_row["binding"]["account"] == row["binding"]["account"]
                            and other["state"] not in {"settled", "refused"}):
                        raise ValueError("another run owns unresolved account obligations")
                grant = row["grant"]
                if request["expected_revision"] != row["revision"] or request["grant_id"] != grant["grant_id"]:
                    raise ValueError("command scope changed")
                order = request["order"]
                if (type(order) is not dict or set(order) != {"symbol", "exchange", "action", "product",
                    "order_type", "quantity", "price"}
                        or order["action"] != "BUY" or order["product"] != "CNC" or order["order_type"] != "LIMIT"
                        or {"symbol": order["symbol"], "exchange": order["exchange"]} not in grant["instruments"]):
                    raise ValueError("only explicitly scoped cash limit buys are supported")
                quantity = _positive(order["quantity"], integer=True)
                price = _positive(order["price"])
                notional = str(Decimal(str(quantity)) * Decimal(str(price)))
                commands = [json.loads(r[0]) for r in db.execute("SELECT data FROM commands WHERE run_id=?", (run_id,))]
                if (quantity > grant["max_order_quantity"]
                        or quantity + sum(c["quantity"] for c in commands) > grant["max_total_quantity"]
                        or Decimal(notional) + sum(Decimal(str(c["notional"])) for c in commands)
                        > min(Decimal(str(grant["max_total_notional"])), Decimal(str(grant["max_loss"])))
                        or len(commands) >= grant["max_commands"]
                        or any(c["state"] not in {"settled", "refused"} for c in commands)):
                    raise ValueError("run budget exhausted or reconciliation required")
            revision = self._observation_revision(row)
        # No registry lock may span the shared-client-loop wait. A simultaneous
        # command must be visible to the account fence before either dispatches.
        books = self._books(row)
        if any((books.positions, books.holdings, books.orders, books.trades)):
            raise ValueError("shared account requires reconciliation")
        with self.registry.lock:
            previous = self._replay(run_id, identity, request)
            if previous is not None:
                return previous
            self._revalidate_observation(row, revision, entry=True)
            binding = row["binding"]
            body = {**order, "broker": binding["broker"], "account_id": binding["account_id"],
                    "strategy": binding["actor"]}
            command = {"run_id": run_id, "command_id": identity, "request_digest": _digest(request),
                       "source": "bounded:" + _digest([run_id, identity]), "body": body, "quantity": quantity,
                       "notional": notional, "state": "pending_admission", "cause": "bounded_policy_authorised",
                       "broker_order_id": None, "events": ["pending_admission"], "created_at": time.time()}
            with self.db.transaction() as db:
                db.execute("INSERT INTO commands VALUES (?,?,?)", (run_id, identity, _encoded(command)))
            ticket = NativeDispatchAuthority(self, row, command)
            self._tickets[command["source"]] = ticket
        return self._execute(row, command, ticket)

    def _cancel(self, run_id: str, actor: str, request: dict[str, Any]) -> dict[str, Any]:
        identity = _text(request["command_id"])
        target = request["cancel"]
        if type(target) is not dict or set(target) != {"placement_command_id"}:
            raise ValueError("exact owned placement required")
        placement = _text(target["placement_command_id"])
        with self.registry.lock:
            with self.db.transaction() as db:
                row = self._get(db, run_id, actor)
                commands = [json.loads(r[0]) for r in db.execute("SELECT data FROM commands WHERE run_id=?", (run_id,))]
                previous = next((c for c in commands if c["command_id"] == identity), None)
                if previous is not None:
                    if previous["request_digest"] != _digest(request):
                        raise ValueError("command identity conflict")
                    return previous
                self._entry_authority(row)
                grant = row["grant"]
                original = next((c for c in commands if c["command_id"] == placement), None)
                if (request["grant_id"] != grant["grant_id"] or request["expected_revision"] != row["revision"]
                        or "cancel" not in grant["actions"] or len(commands) >= grant["max_commands"]
                        or original is None or original.get("operation") == "cancel"
                        or not self._unfilled_placement(original)
                        or any(c.get("placement_command_id") == placement for c in commands)):
                    raise ValueError("owned cancellation not authorised")
                command = {"run_id": run_id, "command_id": identity, "operation": "cancel",
                           "placement_command_id": placement, "request_digest": _digest(request),
                           "source": "bounded:" + _digest([run_id, identity]),
                           "body": {"_op": "cancel", "order_id": original["broker_order_id"]},
                           "expected_order": original["body"], "quantity": 0, "notional": "0",
                           "broker_order_id": original["broker_order_id"], "state": "pending_admission",
                           "cause": "bounded_cancellation_authorised", "events": ["pending_admission"],
                           "created_at": time.time()}
            revision = self._observation_revision(row)
        self._cancel_observation(self._books(row), command)
        with self.registry.lock:
            previous = self._replay(run_id, identity, request)
            if previous is not None:
                return previous
            self._revalidate_observation(row, revision, entry=True)
            with self.db.transaction() as db:
                db.execute("INSERT INTO commands VALUES (?,?,?)", (run_id, identity, _encoded(command)))
            ticket = NativeDispatchAuthority(self, row, command)
            self._tickets[command["source"]] = ticket
        return self._execute(row, command, ticket)

    @staticmethod
    def _cancel_observation(books: Any, command: dict[str, Any]) -> None:
        if books.positions or books.holdings or books.trades:
            raise ValueError("cancel requires reconciled zero exposure")
        state, filled = _observed_order(books.orders, command["broker_order_id"], command["expected_order"])
        if filled or state not in {"OPEN", "PENDING"}:
            raise ValueError("cancel requires exact unfilled ordinary entry")

    def _execute(self, row: dict[str, Any], command: dict[str, Any], ticket: NativeDispatchAuthority) -> dict[str, Any]:
        # Never hold the registry lock across a client-loop wait. The final
        # callback rechecks durable revocation/expiry before actual invocation.
        from .order_routes import CanonicalDispatchOutcome, CompletedPreInvocationRefusal, dispatch_native_command
        binding, body = row["binding"], command["body"]
        cancelling = command.get("operation") == "cancel"
        try:
            with self.app.test_request_context(json=body):
                outcome = dispatch_native_command(
                    body, adapter_id=binding["broker"], account_id=binding["account_id"], authority=ticket,
                    cancel_order_id=command["broker_order_id"] if cancelling else None)
                if type(outcome) is not CanonicalDispatchOutcome:
                    raise ValueError("canonical outcome unavailable")
                if type(outcome.refusal) is CompletedPreInvocationRefusal:
                    return self._transition(command, "refused", cause=outcome.refusal.cause)
                status = outcome.status
                data = outcome.response.get_json() if outcome.response is not None else {}
            ids = data.get("order_ids")
            if (status == 200 and type(data.get("orderid")) is str and data["orderid"]
                    and (ids is None or ids == [data["orderid"]])):
                return self._adopt_ack(command, "cancel_requested" if cancelling else "acknowledged",
                                       identifier=data["orderid"])
            # A sync timeout may return before the invocation callback runs.
            # Absence of that callback is NOT proof of non-execution.
            return self._adopt_unknown(command, cause="canonical_dispatch_not_confirmed",
                conflicting_ids=ids is not None)
        except Exception:
            # Includes failed persistence after a possible broker write. No retry.
            return self._adopt_unknown(command, cause="dispatch_outcome_unknown")
        finally:
            with self.registry.lock:
                self._tickets.pop(command["source"], None)

    def reconcile(self, token: str, run_id: str) -> dict[str, Any]:
        """Observe exact known broker identity; never replay or invent allocation."""
        who, _claims = self._operator(token)
        with self.registry.lock:
            with self.db.transaction() as db:
                row = self._legacy_get(db, run_id, who.actor_ref)
                commands = [json.loads(r[0]) for r in db.execute("SELECT data FROM commands WHERE run_id=?", (run_id,))]
            revision = self._observation_revision(row)
        books = self._books(row)
        with self.registry.lock:
            self._revalidate_observation(row, revision)
            for command in commands:
                if command["state"] in {"settled", "refused"} or command["source"] in self._tickets:
                    continue
                identifier = command["broker_order_id"]
                if identifier is None:
                    # Existing canonical recovery may resolve an uncertain write;
                    # only its exact actor/source/account mapping can be adopted.
                    attempts = self.app.config["ORDER_LIFECYCLE_LEDGER"].list_dispatch_attempts()
                    matches = [a for a in attempts if a["actor_id"] == row["binding"]["actor"]
                               and a["intent_source"] == command["source"]
                               and a["adapter_id"] == row["binding"]["broker"]
                               and a["account_id"] == row["binding"]["account_id"] and a["broker_order_id"]]
                    if len(matches) == 1:
                        identifier = matches[0]["broker_order_id"]
                try:
                    expected = command.get("expected_order", command["body"])
                    observed = _observed_order(books.orders, identifier, expected)
                    state, filled = observed
                    if books.positions or books.holdings or books.trades:
                        # A fill observation is retained, but shared account
                        # allocation and protective duty are NOT inferred here.
                        state = "filled" if filled == expected["quantity"] else "partial" if filled else "reconciling"
                    elif state in {"REJECTED", "CANCELLED"} and filled == 0:
                        self._transition(command, "settled", cause="broker_" + state.lower() + "_zero_fill",
                                         broker_order_id=identifier, filled_quantity=filled)
                        continue
                    else:
                        state = "filled" if filled == expected["quantity"] else "partial" if filled else "working"
                        if command.get("operation") == "cancel" and state == "working":
                            state = "cancel_requested"
                    self._transition(command, state, cause="broker_observation_exposure_not_settled",
                                     broker_order_id=identifier, filled_quantity=filled)
                except (ValueError, TypeError, KeyError, ArithmeticError):
                    self._transition(command, "reconciling", cause="broker_evidence_missing_or_conflicting")
        return self.status(token, run_id)

    @staticmethod
    def _unfilled_placement(command: dict[str, Any]) -> bool:
        """Durable evidence is independent of a new zero-fill book response."""
        return (command.get("operation") != "cancel" and bool(command["broker_order_id"])
                and command["state"] in {"acknowledged", "working"}
                and command.get("filled_quantity", 0) == 0 and not NativeAutonomy._completion_conflict(command))

    def _check_command_authority(self, db: Any, command: dict[str, Any], states: set[str] | None) -> None:
        if command["state"] not in (states if states is not None else {"pending_admission", "admitted"}):
            raise ValueError("command already dispatched or retired")
        if command.get("operation") != "cancel":
            return
        raw = db.execute("SELECT data FROM commands WHERE run_id=? AND command_id=?",
                         (command["run_id"], command["placement_command_id"])).fetchone()
        original = json.loads(raw[0]) if raw else None
        if (original is None or not self._unfilled_placement(original)
                or original["broker_order_id"] != command["broker_order_id"]
                or original["body"] != command["expected_order"]):
            raise ValueError("owned cancellation no longer authorised")

    @staticmethod
    def _completion_conflict(command: dict[str, Any]) -> bool:
        # One order's book cannot disprove another possible identity/write.
        # Retain this obligation across ordinary reconciliation and restart.
        return command.get("cause") in {"broker_ack_identity_conflicting", "canonical_completion_conflicting"}

    def _adopt_unknown(self, command: dict[str, Any], *, cause: str,
                       conflicting_ids: bool = False) -> dict[str, Any]:
        with self.registry.lock:
            with self.db.transaction() as db:
                raw = db.execute("SELECT data FROM commands WHERE run_id=? AND command_id=?",
                                 (command["run_id"], command["command_id"])).fetchone()
                current = json.loads(raw[0])
            if conflicting_ids or current["state"] not in {"pending_admission", "admitted", "dispatched"}:
                cause = "canonical_completion_conflicting"
            return self._transition(current, "uncertain", cause=cause)

    def _adopt_ack(self, command: dict[str, Any], state: str, *, identifier: str) -> dict[str, Any]:
        """Merge this invocation's ACK, not a newer observation of its order.

        A compatible completion can add identity, but cannot erase evidence
        observed while its caller was waiting. Conflicting identity is not a
        stale state: it retains an unresolved obligation even after settlement.
        Unknown outcomes deliberately do not use this compatibility rule.
        """
        with self.registry.lock:
            with self.db.transaction() as db:
                raw = db.execute("SELECT data FROM commands WHERE run_id=? AND command_id=?",
                                 (command["run_id"], command["command_id"])).fetchone()
                current = json.loads(raw[0])
                known = current["broker_order_id"]
                conflict = known is not None and known != identifier
                if not conflict and current["state"] not in {"pending_admission", "admitted", "dispatched"}:
                    if known is None:
                        current.update(broker_order_id=identifier, updated_at=time.time())
                        db.execute("UPDATE commands SET data=? WHERE run_id=? AND command_id=?",
                                   (_encoded(current), current["run_id"], current["command_id"]))
                    return current
            if conflict:
                return self._transition(current, "reconciling", cause="broker_ack_identity_conflicting")
            return self._transition(current, state, cause="broker_ack_not_settlement", broker_order_id=identifier)


def _observed_order(rows: Any, identifier: str | None, expected: dict[str, Any]) -> tuple[str, int]:
    """Strict evidence for this slice, not a competing order or balance book."""
    if not identifier or type(rows) is not list:
        raise ValueError("exact broker observation missing")
    found = []
    def field(row: dict[str, Any], *names: str) -> Any:
        values = [row[name] for name in names if name in row]
        if not values or any(str(v) != str(values[0]) for v in values):
            raise ValueError("observation aliases missing or conflicting")
        return values[0]
    for row in rows:
        if type(row) is not dict:
            raise ValueError("malformed broker book")
        if field(row, "order_id", "orderid", "orderId") == identifier:
            found.append(row)
    if len(found) != 1 or len(rows) != 1:
        raise ValueError("shared account or missing order requires reconciliation")
    row = found[0]
    for key, aliases in {"symbol": ("symbol", "trading_symbol"), "exchange": ("exchange",),
                         "product": ("product",), "action": ("action", "transaction_type"),
                         "order_type": ("pricetype", "price_type", "order_type")}.items():
        if field(row, *aliases) != expected[key]:
            raise ValueError("broker identity changed")
    quantity = Decimal(str(field(row, "quantity", "qty")))
    filled = Decimal(str(field(row, "filled_qty", "filled_quantity")))
    price = Decimal(str(field(row, "price")))
    if (not all(v.is_finite() for v in (quantity, filled, price)) or quantity != expected["quantity"]
            or filled < 0 or filled > quantity or filled != int(filled) or price != Decimal(str(expected["price"]))):
        raise ValueError("broker quantity changed")
    state = field(row, "status", "order_status")
    if state not in {"OPEN", "PENDING", "PARTIAL", "COMPLETE", "FILLED", "REJECTED", "CANCELLED"}:
        raise ValueError("broker state unknown")
    if (state in {"COMPLETE", "FILLED"} and filled != quantity) or (state == "REJECTED" and filled != 0):
        raise ValueError("broker state contradicts fill")
    return state, int(filled)
