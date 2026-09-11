"""Inert durable auth-parent/child ownership; no provider orchestration.

The account coordinator holds its operation lock throughout these calls. Route
draining and provider-specific challenge interpretation belong to activation.
"""

from __future__ import annotations

import hmac
import time
from dataclasses import asdict, dataclass
from uuid import UUID, uuid4

from .account_mutation_contracts import (
    _PRINCIPALS,
    AccountMutationConflict,
    AccountMutationRequest,
    AccountMutationResult,
    AccountMutationValidationError,
    AccountOperation,
    AccountPrincipalDenied,
    AuthFlowRef,
    AuthFlowState,
    MutationPhase,
    OperationRef,
    OperatorSessionPrincipal,
)
from .account_mutation_journal import AccountMutationJournal
from .account_mutation_principals import validate_principal
from .broker_identity import BrokerSelector
from .service_connection_transactions import decode


@dataclass(frozen=True)
class AuthFlowStatus:
    """Only redacted ownership and phase facts may leave the flow store."""

    reference: AuthFlowRef
    state: AuthFlowState
    retired_selectors: tuple[BrokerSelector, ...]
    lease_released: bool
    retirement_retained: bool


class AccountAuthFlows:
    """Versioned parent facts and one immutable receipt per consumed step."""

    def __init__(self, journal: AccountMutationJournal) -> None:
        self.journal = journal
        self._clean_terminal_candidates()

    def _clean_terminal_candidates(self) -> None:
        """Replay terminal material cleanup only after its anchored tombstone."""
        self.journal._verify()
        terminal = {"completed", "flow_denied", "provider_rejected", "identity_mismatch",
                    "cancelled", "expired", "external_unknown"}
        parents = {entity for entity, _, encoded in self.journal._connection.execute(
            "SELECT entity_id, revision, body FROM auth_flows") if decode(encoded)["state"] in terminal}
        for entity, _, encoded in self.journal._connection.execute("SELECT entity_id, revision, body FROM auth_children"):
            if decode(encoded)["flow_id"] in parents:
                name = self.journal._candidate_name(UUID(entity))
                if self.journal._directory.exists(name):
                    self.journal._directory.unlink(name)

    def _ref(self, flow_id: UUID, revision: int, body: dict) -> AuthFlowRef:
        return AuthFlowRef(body["adapter_id"], flow_id, self.journal.store_incarnation,
                           body["kind"], revision, body["expected_account_id"])

    def _load(self, reference: AuthFlowRef, *, observation: bool = False, claimed: bool = False) -> tuple[int, dict]:
        if type(reference) is not AuthFlowRef:
            raise AccountMutationValidationError
        reference.__post_init__()
        self.journal._verify()
        row = self.journal._row("auth_flows", str(reference.flow_id))
        if row is None or reference.flow_store_incarnation != self.journal.store_incarnation:
            raise AccountMutationConflict
        revision, body = row
        canonical = self._ref(reference.flow_id, reference.flow_version, body)
        if canonical != reference or reference.flow_version > revision:
            raise AccountMutationConflict
        if not observation and reference.flow_version != revision:
            if not claimed or body["state"] != "completing" or body["claimed_version"] != reference.flow_version:
                raise AccountMutationConflict
        return revision, body

    @staticmethod
    def _operator(body: dict, principal: object, *, exchange: bool = False, read_only: bool = False) -> None:
        scope = "admin.accounts.read" if read_only else "admin.accounts.write"
        if (type(principal) is not OperatorSessionPrincipal or principal not in _PRINCIPALS
                or principal.actor_ref != body["actor_ref"]
                or scope not in principal.scopes
                or (exchange and principal.session_binding != body["session_binding"])):
            raise AccountPrincipalDenied

    def begin(
        self, reference: OperationRef, *, kind: str, expected_account_id: str | None,
        expires_at: int, redirect: str, retired_selectors: tuple[BrokerSelector, ...], adapter_wide: bool,
    ) -> AuthFlowRef:
        """Allocate the first completion child and reserve its exact retired set."""
        _revision, operation = self.journal._operation(reference)
        if operation["operation"] != "begin_auth_flow" or operation["phase"] != "prepared":
            raise AccountMutationConflict
        adapter = operation["adapter_id"] or operation["selector"]["adapter_id"]
        flow = AuthFlowRef(adapter, reference.operation_id, self.journal.store_incarnation, kind, 1, expected_account_id)
        if (type(expires_at) is not int or expires_at <= int(time.time())
                or type(redirect) is not str or not redirect or len(redirect) > 2048
                or type(adapter_wide) is not bool or type(retired_selectors) is not tuple
                or list(retired_selectors) != sorted(set(retired_selectors))):
            raise AccountMutationValidationError
        frozen = [v["selector"] for v in operation["authorities"]["registry_versions"]]
        retired = [asdict(selector) for selector in retired_selectors]
        if any(value not in frozen or value["adapter_id"] != adapter for value in retired):
            raise AccountMutationConflict
        if adapter_wide and retired != [value for value in frozen if value["adapter_id"] == adapter]:
            raise AccountMutationConflict
        begin_mac = self.journal._mac("auth-begin/v1", [kind, expected_account_id, expires_at,
                                                       redirect, retired, adapter_wide], pepper=True)
        existing = self.journal._row("auth_flows", str(reference.operation_id))
        if existing is not None:
            if not hmac.compare_digest(existing[1]["begin_mac"], begin_mac):
                raise AccountMutationConflict
            return self._ref(reference.operation_id, *existing)
        child = str(uuid4())
        body = {"adapter_id": adapter, "kind": kind, "expected_account_id": expected_account_id,
                "actor_ref": operation["actor_ref"], "session_binding": operation["session_binding"],
                "authorities": operation["authorities"], "expires_at": expires_at,
                "redirect_mac": self.journal._mac("auth-redirect/v1", redirect, pepper=True),
                "state": "pending", "current_child": child, "claimed_version": None,
                "retired_selectors": retired, "adapter_wide": adapter_wide,
                "lease_released": False, "retirement_retained": True, "possibly_invalidating": False,
                "begin_mac": begin_mac}
        ownership = {"flow_id": str(flow.flow_id), "adapter_id": adapter, "adapter_wide": adapter_wide,
                     "selectors": retired, "current_child": child, "present": True}
        # Recheck overlap: admission and parent allocation are distinct inert APIs.
        for _, _, encoded in self.journal._connection.execute("SELECT entity_id, revision, body FROM retirements"):
            owner = decode(encoded)
            if owner["present"] and ((owner["adapter_id"] == adapter and (adapter_wide or owner["adapter_wide"]))
                                     or any(value in owner["selectors"] for value in retired)):
                raise AccountMutationConflict
        self.journal._write([
            ("auth_flows", str(flow.flow_id), None, body),
            ("auth_children", child, None, {"flow_id": str(flow.flow_id), "operation_id": child,
                                           "state": "allocated", "request_mac": None}),
            ("retirements", str(flow.flow_id), None, ownership),
        ])
        return flow

    def current_child(self, reference: AuthFlowRef) -> UUID:
        """Return the stable preallocated child; this call grants no authority."""
        return UUID(self._load(reference, observation=True)[1]["current_child"])

    def status(self, reference: AuthFlowRef, principal: object) -> AuthFlowStatus:
        """A fresh verified session for the same operator may inspect old flows."""
        revision, body = self._load(reference, observation=True)
        self._operator(body, principal, read_only=True)
        return AuthFlowStatus(self._ref(reference.flow_id, revision, body), AuthFlowState(body["state"]),
                              tuple(BrokerSelector(**v) for v in body["retired_selectors"]),
                              body["lease_released"], body["retirement_retained"])

    def claim(self, request: AccountMutationRequest) -> AccountMutationResult:
        """Atomically consume the allocated child with its private request MAC."""
        request.__post_init__()
        validate_principal(request)
        reference = request.flow_ref
        revision, body = self._load(reference, observation=True)
        self._operator(body, request.principal, exchange=True)
        old_child = self.journal._row("auth_children", str(request.operation_id))
        if (old_child is not None and old_child[1]["flow_id"] == str(reference.flow_id)
                and old_child[1]["state"] == "completed"):
            return self.journal.admit(request)
        revision, body = self._load(reference, claimed=True)
        if (request.operation is not AccountOperation.COMPLETE_AUTH_FLOW or request.flow_action != "complete"
                or str(request.operation_id) != body["current_child"]
                or body["state"] not in {"pending", "flow_pending", "challenge_staged", "completing"}
                or body["expires_at"] <= int(time.time())):
            raise AccountMutationConflict
        from .account_mutation_journal import _json_value
        if _json_value(asdict(request.authorities)) != body["authorities"]:
            raise AccountMutationConflict
        child_revision, child = self.journal._row("auth_children", body["current_child"])
        digest = self.journal._mac("auth-input/v1", request.private_input.hex(), pepper=True)
        if child["state"] == "claimed":
            if not hmac.compare_digest(child["request_mac"], digest):
                raise AccountMutationConflict
            return self.journal.admit(request)
        if child["state"] != "allocated" or body["lease_released"]:
            raise AccountMutationConflict
        child.update(state="claimed", request_mac=digest)
        body.update(state="completing", claimed_version=reference.flow_version)
        return self.journal._admit(request, updates=(
            ("auth_flows", str(reference.flow_id), revision, body),
            ("auth_children", body["current_child"], child_revision, child),
        ))

    def finish_step(self, reference: AuthFlowRef, child_ref: OperationRef, *, final: bool) -> AuthFlowRef:
        """Freeze the child's outcome and allocate one next step before response."""
        revision, body = self._load(reference, claimed=True)
        _, operation = self.journal._operation(child_ref)
        if body["state"] != "completing" or str(child_ref.operation_id) != body["current_child"]:
            raise AccountMutationConflict
        phase = MutationPhase(operation["phase"])
        outcomes = {MutationPhase.EXTERNAL_UNKNOWN: "external_unknown", MutationPhase.PROVIDER_REJECTED: "flow_denied"}
        if phase not in {*outcomes, MutationPhase.CANDIDATE_STAGED, MutationPhase.COMMITTED,
                         MutationPhase.COMMITTED_DISCONNECTED}:
            raise AccountMutationConflict
        if final and phase is MutationPhase.CANDIDATE_STAGED:
            raise AccountMutationConflict
        child_revision, child = self.journal._row("auth_children", body["current_child"])
        child["state"] = "completed"
        body["possibly_invalidating"] = True
        body["state"] = outcomes.get(phase, "completed" if final else "challenge_staged")
        updates = [("auth_children", body["current_child"], child_revision, child)]
        owner_revision, owner = self.journal._row("retirements", str(reference.flow_id))
        if body["state"] == "challenge_staged":
            body["current_child"] = str(uuid4())
            owner["current_child"] = body["current_child"]
            updates.append(("auth_children", body["current_child"], None,
                            {"flow_id": str(reference.flow_id), "operation_id": body["current_child"],
                             "state": "allocated", "request_mac": None}))
        if body["state"] == "completed":
            owner["present"] = body["retirement_retained"] = False
        updates.extend([("auth_flows", str(reference.flow_id), revision, body),
                        ("retirements", str(reference.flow_id), owner_revision, owner)])
        self.journal._write(updates)
        self._clean_terminal_candidates()
        return self._ref(reference.flow_id, revision + 1, body)

    def release_for_input(self, reference: AuthFlowRef) -> AuthFlowRef:
        """Record a safe human pause; durable retirement ownership remains held."""
        revision, body = self._load(reference)
        if body["state"] not in {"pending", "flow_pending", "challenge_staged"} or body["lease_released"]:
            raise AccountMutationConflict
        body["lease_released"] = True
        self.journal._write([("auth_flows", str(reference.flow_id), revision, body)])
        return self._ref(reference.flow_id, revision + 1, body)

    def reacquire(self, reference: AuthFlowRef, principal: object) -> AuthFlowRef:
        """Record the concrete coordinator's reacquisition after frozen CAS checks."""
        revision, body = self._load(reference)
        self._operator(body, principal, exchange=True)
        if not body["lease_released"] or body["state"] not in {"pending", "flow_pending", "challenge_staged"}:
            raise AccountMutationConflict
        body["lease_released"] = False
        self.journal._write([("auth_flows", str(reference.flow_id), revision, body)])
        return self._ref(reference.flow_id, revision + 1, body)

    def cancel(self, reference: AuthFlowRef, principal: object, *, expired: bool = False) -> AuthFlowRef:
        """Tombstone completion; possibly invalidating work never restores routes."""
        revision, body = self._load(reference)
        self._operator(body, principal)
        if body["state"] in {"completed", "cancelled", "expired"}:
            raise AccountMutationConflict
        if expired and body["expires_at"] > int(time.time()):
            raise AccountMutationConflict
        child_revision, child = self.journal._row("auth_children", body["current_child"])
        operation = self.journal._row("operations", body["current_child"])
        safe = {"prepared", "router_drained", "external_invocation_prepared"}
        invalidating = body["possibly_invalidating"] or (operation is not None and operation[1]["phase"] not in safe)
        body.update(state="expired" if expired else "cancelled", retirement_retained=invalidating)
        child["state"] = "tombstoned"
        owner_revision, owner = self.journal._row("retirements", str(reference.flow_id))
        owner["present"] = invalidating
        self.journal._write([("auth_flows", str(reference.flow_id), revision, body),
                             ("auth_children", body["current_child"], child_revision, child),
                             ("retirements", str(reference.flow_id), owner_revision, owner)])
        self._clean_terminal_candidates()
        return self._ref(reference.flow_id, revision + 1, body)
