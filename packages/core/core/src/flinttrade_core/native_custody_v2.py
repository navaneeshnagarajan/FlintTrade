"""Finite pre-entry custody in the incumbent native run/command transaction.

Acceptance is neither flatness nor permission. Every preview binds a finite
selection, real account pins, source generation and complete local census.
"""
from __future__ import annotations

import json
import time
from typing import Any
from uuid import uuid4

from .broker_identity import BrokerSelector
from .native_autonomy_contracts_v2 import DutyViewV2, GrantRequestV2, TransferAcceptRequestV2, TransferReceiptV2
from .native_financial_v2 import primitive_copy, reference


def _digest(value: Any) -> str:
    from .native_autonomy import _digest as digest

    return digest(value)


def duty_projection(row: dict[str, Any], commands: list[dict[str, Any]]) -> dict[str, Any] | None:
    """Keep every known fill and possible write independently of entry state."""
    from .native_model_custody_v2 import model_obligations

    models = model_obligations(row)
    finance = row.get("financial_v2", {})
    prior = row.get("duty_v2")
    history, holds = finance.get("history", {}), finance.get("reservations", {})
    unresolved = bool(finance.get("unresolved_entry_ids"))
    if prior is None and not history and not holds and not commands and not unresolved and not row.get("model_calls"):
        return None
    fills = list(finance.get("known_fills", {}).values())
    if not fills:
        fills = [fill for entry in history.values() for fill in entry["fills"].values()]
    obligations = []
    for identity, hold in sorted(holds.items()):
        if hold["state"] == "released":
            continue
        entry = hold["entry"]
        if row["schema_version"] == "2-options-1":
            for write in entry["writes"]:
                if write["remaining_quantity"] == 0:
                    continue
                obligations.append({"obligation_id": write["write_ref"]["id"], "attempt_ref": write["write_ref"],
                                    "kind": ("possible_entry" if write["purpose"] == "entry"
                                             else "independently_executable_exit"),
                                    "possible_quantity": write["remaining_quantity"]})
        else:
            obligations.append({"obligation_id": identity, "attempt_ref": entry["entry_ref"],
                                "kind": "unknown_write" if entry["unknown_possible_write"] else "possible_entry",
                                "possible_quantity": entry["remaining_possible_quantity"]})
    for command in commands:
        if command["state"] in {"settled", "refused"}:
            continue
        obligations.append({"obligation_id": "command:" + command["command_id"],
                            "attempt_ref": reference("command:" + command["command_id"], command),
                            "kind": "unknown_write", "possible_quantity": None})
    unknown = any(item["kind"] == "unknown_write" for item in obligations)
    quantities = [item["possible_quantity"] for item in obligations if item["kind"] == "possible_entry"]
    census = {"history": history, "holds": holds, "commands": commands, "model_calls": row.get("model_calls", []),
              "known_fills": finance.get("known_fills", {}),
              "fee_liabilities": finance.get("fee_liabilities"),
              "charge_history": finance.get("charge_history", {}),
              "payment_evidence": finance.get("payment_evidence", {}),
              "unresolved_entry_ids": finance.get("unresolved_entry_ids", [])}
    revision = _digest(census)
    acceptance = prior.get("receiving_acceptance_ref") if prior else None
    coverage = "operator_accepted" if acceptance else "absent"
    # Finite contingent acceptance is preserved as historical custody but does
    # not cover a changed duty census. A new preview/receiver action is needed.
    if prior and prior["obligation_revision"] != revision:
        acceptance, coverage = None, "stale"
    opened = sum(fill["quantity"] - fill["exited"] for fill in fills)
    state = "open" if opened or obligations or models else "contingent"
    if unresolved:
        state = "reconciliation_required"
    if row["entry_state"] == "retired" and (opened or obligations or models):
        state = "transferred" if acceptance else "handback_required"
    duty = {
        "duty_ref": reference("duty:" + row["binding"]["run_id"], [row["revision"], revision]),
        "scope": row["scope_v2"], "obligation_revision": revision,
        "possible_entry_quantity": None if unknown or None in quantities else sum(quantities),
        "cumulative_entry_fill": sum(fill["quantity"] for fill in fills),
        "cumulative_exit_fill": sum(fill["exited"] for fill in fills),
        "entry_fill_refs": [fill["fill_ref"] for fill in fills],
        # A cash source supplies an exact cumulative exit allocation, not a
        # fabricated exchange trade. The reference identifies that allocation.
        "exit_fill_refs": [reference("exit-allocation:" + fill["fill_ref"]["id"], fill)
                           for fill in fills if fill["exited"]],
        "obligations": obligations, "model_obligations": models, "unknown_possible_writes": unknown,
        "coverage": coverage, "custody": "operator" if acceptance else "run_retained",
        "custody_revision": _digest([revision, acceptance]), "receiving_acceptance_ref": acceptance,
        "state": state, "reasons": ["reconciliation_required"] if unknown or unresolved or models else [],
    }
    return DutyViewV2.model_validate(duty).model_dump(mode="json")


class NativeCustodyV2:
    """Short locked operations on existing native custody; no provider waits."""

    def __init__(self, workflow: Any) -> None:
        self.workflow = workflow
        self.native, self.registry = workflow.native, workflow.registry

    def _selection(self, row: dict[str, Any], body: dict[str, Any]) -> dict[str, Any]:
        selected = GrantRequestV2.model_validate(body).model_dump(mode="json")
        now = int(time.time() * 1000)
        if (selected["run_id"] != row["binding"]["run_id"]
                or selected["expected_binding_revision"] != row["revision"]
                or selected["policy_ref"] != row["config_v2"]["risk"]["policy_ref"]
                or row["report_v2"] is None or selected["report_ref"] != row["report_v2"]["report_ref"]
                or not now < selected["expires_at_ms"] <= now + selected["limits"]["max_duration_ms"]):
            raise ValueError("finite current custody selection required")
        return selected

    def _pins(self, db: Any, row: dict[str, Any], claims: dict[str, Any]) -> dict[str, Any]:
        config = self.workflow._config({"schema_version": row["schema_version"], "config": row["config_v2"]}).config
        account = self.workflow._account_pin(claims, config)
        if account != row["account_pin"]:
            raise ValueError("custody account binding changed")
        dependencies = self.workflow._dependencies()
        snapshot = dependencies.lifecycle_store.observation_snapshot(BrokerSelector(config.broker, config.account_id))
        rows = [json.loads(value[0]) for value in db.execute("SELECT data FROM runs ORDER BY run_id")]
        ids = {item["binding"]["run_id"] for item in rows if item["binding"]["account"] == row["binding"]["account"]}
        commands = [json.loads(value[0]) for value in db.execute(
            "SELECT data FROM commands ORDER BY run_id,command_id")]
        all_ids = {item["binding"]["run_id"] for item in rows}
        if any(command["run_id"] not in all_ids for command in commands):
            raise ValueError("native command custody orphaned")
        census = [{"binding": item["binding"], "financial": item.get("financial_v2"), "grant": item.get("grant"),
                   "model_calls": item.get("model_calls", []),
                   "generation": self.registry._get(
                       self.registry.scope(item["binding"]["run_id"], item["operator"]))["generation"]}
                  for item in rows if item["binding"]["run_id"] in ids]
        primitive = None
        proposal = None
        if self.workflow._primitive_source is not None and config.environment == "synthetic":
            primitive = _digest([self.workflow._primitive_source.generations.get(row["binding"]["run_id"]),
                                 self.workflow._primitive_source.resolve(row, snapshot)])
            if row["binding"]["run_id"] in self.workflow._primitive_source.plans:
                proposal = _digest(self.workflow._primitive_source.resolve_plan(row, snapshot))
        tickets = sorted(key for key, ticket in self.native._tickets.items()
                         if ticket.command["run_id"] in ids)
        workers = sorted((identity, id(owner)) for identity, owner in self.registry.owners.items() if identity in ids)
        return {"account": account, "canonical": _digest([snapshot.generation, snapshot.evidence_json]),
                "primitive": primitive, "proposal": proposal,
                "census": _digest([census, [c for c in commands if c["run_id"] in ids], tickets, workers]),
                "backend": str(self.registry.proof.incarnation)}

    def preview(self, token: str, run_id: str, body: dict[str, Any]) -> dict[str, Any]:
        """Select finite future custody without a grant or producer acquisition.

        Args:
            token: Authenticated current sending operator session.
            run_id: Existing immutable run identity.
            body: GrantRequestV2 used only as a finite preview selection.

        Returns:
            Owner-issued preview reference, exact selection and current duty.

        Raises:
            ValueError: Selection, account, source or custody is unavailable.
        """
        who, claims = self.native._operator(token)
        with self.registry.lock, self.native.db.transaction() as db:
            row = self.workflow._get(db, run_id, who.actor_ref)
            selected = self._selection(row, body)
            commands = [json.loads(value[0]) for value in db.execute(
                "SELECT data FROM commands WHERE run_id=?", (run_id,))]
            row["duty_v2"] = row.get("duty_v2") or {}
            row["duty_v2"] = duty_projection(row, commands)
            pins = self._pins(db, row, claims)
            payload = {"selection": selected, "duty": row["duty_v2"], "pins": pins,
                       "custody_policy": row["config_v2"]["custody"]}
            preview = {"preview_ref": reference("preview:" + uuid4().hex, payload), **payload, "consumed": False}
            # Replacing future selection cannot erase historical receiving custody.
            # Only this newly consumed preview can ever support its exact selection.
            row["preview_v2"] = preview
            self.native._save(db, row)
        return {key: primitive_copy(preview[key]) for key in ("preview_ref", "selection", "duty")}

    def accept(self, token: str, run_id: str, body: dict[str, Any]) -> dict[str, Any]:
        """Authenticate the actual receiver and consume one exact current preview.

        Args:
            token: Actual receiving operator session, checked against account ACLs.
            run_id: Existing run selected by the one-use preview.
            body: Exact TransferAcceptRequestV2, with no receiving identity claim.

        Returns:
            Durable TransferReceiptV2; neither a grant nor evidence of flatness.

        Raises:
            ValueError: Preview is consumed, expired, changed or not owned.
        """
        request = TransferAcceptRequestV2.model_validate(body)
        who, claims = self.native._operator(token)
        with self.registry.lock, self.native.db.transaction() as db:
            raw = db.execute("SELECT data FROM runs WHERE run_id=?", (run_id,)).fetchone()
            if raw is None:
                raise ValueError("native run unavailable")
            row = self.workflow._get(db, run_id, json.loads(raw[0])["operator"])
            preview = row.get("preview_v2")
            if preview is None:
                raise ValueError("current finite preview required")
            if preview["consumed"]:
                raise ValueError("custody preview already consumed")
            if (request.preview_ref.model_dump() != preview["preview_ref"]
                    or request.expected_duty_revision != preview["duty"]["duty_ref"]["revision"]
                    or self._pins(db, row, claims) != preview["pins"]
                    or int(time.time() * 1000) >= preview["selection"]["expires_at_ms"]):
                raise ValueError("custody preview binding changed")
            # _pins checks the real receiver's account ACL as well as the bounded
            # actor. Sender-provided receiving identities are never accepted.
            duty = row["duty_v2"]
            receipt = {
                "transfer_ref": reference("transfer:" + uuid4().hex, [preview, who.actor_ref]),
                "duty_ref": duty["duty_ref"], "scope": row["scope_v2"], "account_provenance": row["account_pin"],
                "obligation_revision": duty["obligation_revision"], "accepted_payload_digest": _digest(preview),
                "receiving_operator": who.actor_ref, "accepted_at_ms": int(time.time() * 1000),
                "custody_location_ref": reference("native-owner-custody", [row["revision"], who.actor_ref]),
                "obligations": duty["obligations"], "model_obligations": duty["model_obligations"],
                "unknown_possible_writes": duty["unknown_possible_writes"],
                "reconciliation_required": bool(
                    duty["obligations"] or duty["model_obligations"] or duty["cumulative_entry_fill"] != duty["cumulative_exit_fill"]),
                "custody": "operator", "outcome": "custody_transferred_not_flatness",
            }
            receipt = TransferReceiptV2.model_validate(receipt).model_dump(mode="json")
            preview["consumed"] = True
            row["transfer_v2"] = receipt
            row.setdefault("transfers_v2", []).append(receipt)
            duty.update(custody="operator", coverage="operator_accepted",
                        receiving_acceptance_ref=receipt["transfer_ref"],
                        custody_revision=_digest(receipt))
            if row["entry_state"] == "retired" and receipt["reconciliation_required"]:
                duty["state"] = "transferred"
            self.native._save(db, row)
        return receipt
