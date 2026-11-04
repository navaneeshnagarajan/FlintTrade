"""Primitive projection and durable financial reducers in native run custody.

No account book or database is created here. The caller commits these reducers
in NativeAutonomy's existing run/command transaction with its source-generation
CAS. Production tariff, lifetime, native-date and margin issuers are unavailable.
"""
from __future__ import annotations

import json
import re
from dataclasses import fields, is_dataclass
from datetime import date
from decimal import Decimal
from fractions import Fraction
from types import UnionType
from typing import Any, Callable, Literal, get_args, get_origin, get_type_hints

from .native_autonomy_contracts_v2 import RevisionRefV2, RunScopeV2


def primitive_copy(value: Any) -> Any:
    """Detach exact JSON primitives without calling conversion hooks."""
    if value is None or type(value) in (str, int, bool):
        return value
    if type(value) is list:
        return [primitive_copy(item) for item in value]
    if type(value) is dict and all(type(key) is str for key in value):
        return {key: primitive_copy(item) for key, item in value.items()}
    raise ValueError("exact primitive facts required")


def _digest(value: Any) -> str:
    from .native_autonomy import _digest as digest

    return digest(value)


def reference(name: str, value: Any) -> dict[str, str]:
    """Describe a locally retained immutable revision; this is not a capability."""
    return {"id": name, "revision": _digest(value)}


def _decode(value: Any, schema: Any) -> Any:
    """Decode only the closed arithmetic vocabulary after owner resolution."""
    origin, args = get_origin(schema), get_args(schema)
    if origin is UnionType:
        for variant in args:
            try:
                return _decode(value, variant)
            except (ValueError, TypeError):
                pass
        raise ValueError("primitive variant unavailable")
    if schema is type(None) and value is None:
        return None
    if origin is Literal:
        if any(type(value) is type(item) and value == item for item in args):
            return value
        raise ValueError("primitive literal unavailable")
    if schema is Decimal:
        if type(value) is not str or re.fullmatch(r"(?:0|[1-9][0-9]*)(?:\.[0-9]+)?", value) is None:
            raise ValueError("exact decimal primitive required")
        return Decimal(value)
    if origin is tuple and type(value) is list:
        return tuple(_decode(item, args[0]) for item in value)
    if schema is RevisionRefV2:
        return RevisionRefV2.model_validate(value)
    if is_dataclass(schema) and type(value) is dict:
        hints = get_type_hints(schema)
        if set(value) != {field.name for field in fields(schema)}:
            raise ValueError("closed primitive record required")
        return schema(**{key: _decode(item, hints[key]) for key, item in value.items()})
    if schema in (str, int, bool) and type(value) is schema:
        return value
    raise ValueError("primitive structure unavailable")


def _money(value: Fraction) -> str:
    """Render exact finite decimals without mutable Decimal arithmetic context."""
    denominator, places = value.denominator, 0
    while denominator % 2 == 0:
        denominator //= 2
        places += 1
    fives = 0
    while denominator % 5 == 0:
        denominator //= 5
        fives += 1
    if denominator != 1 or value < 0:
        raise ValueError("finite non-negative money required")
    places = max(places, fives)
    digits = str(value.numerator * (10 ** places) // value.denominator)
    if not places:
        return digits
    digits = digits.zfill(places + 1)
    return (digits[:-places] + "." + digits[-places:]).rstrip("0").rstrip(".")


class PrimitiveFixtureSource:
    """Explicit trusted server composer for labelled synthetic primitive facts.

    The composer must own the inert transport and supply its actual current
    binding. No HTTP flag installs this source. It cannot serve production or
    survive backend, account, transport or canonical-source replacement. Its
    records are facts, never an eligible boolean or a preconstructed risk DTO.
    """

    def __init__(self, workflow: Any, *, transport: object, transport_binding: object,
                 current_transport_binding: Callable[[], object]) -> None:
        if transport is None or transport_binding is None or not callable(current_transport_binding):
            raise ValueError("explicit inert transport custody required")
        self.workflow, self.transport = workflow, transport
        self.binding, self.current = transport_binding, current_transport_binding
        self.send = getattr(transport, "send", None)
        if not callable(self.send):
            raise ValueError("actual inert transport send required")
        self.dependencies = workflow._dependencies()
        self.proof = workflow.registry.proof
        self.records: dict[str, tuple[str, str, dict[str, Any]]] = {}
        self.plans: dict[str, dict[str, Any]] = {}
        self.generations: dict[str, int] = {}
        self.plan_generations: dict[str, int] = {}
        self.require_current()

    def require_current(self) -> None:
        """Refuse replaced backend, canonical owner or external transport custody."""
        self.workflow.registry._require()
        send = getattr(self.transport, "send", None)
        if (getattr(send, "__self__", None) is not getattr(self.send, "__self__", None)
                or getattr(send, "__func__", send) is not getattr(self.send, "__func__", self.send)
                or self.workflow.registry.proof is not self.proof or self.current() is not self.binding
                or self.workflow._dependencies() is not self.dependencies):
            raise ValueError("synthetic primitive source binding changed")

    def rebind_read_only_recovery(self, run_id: str) -> None:
        """Attach this inert source to an owner-issued recovery, never rewrite old pins.

        This server-only synthetic seam cannot create provider/date/fee proof or
        grant authority. Its previously published records remain stale until an
        explicit new publication matches the new canonical source generation.
        """
        with self.workflow.registry.lock:
            self.workflow.registry._require()
            if self.workflow.registry.proof is not self.proof or self.current() is not self.binding:
                raise ValueError("synthetic primitive source owner changed")
            with self.workflow.native.db.transaction() as db:
                raw = db.execute("SELECT data FROM runs WHERE run_id=?", (run_id,)).fetchone()
                if raw is None:
                    raise ValueError("configured synthetic run required")
                row = json.loads(raw[0])
            if row.get("scope_v2", {}).get("environment") != "synthetic":
                raise ValueError("synthetic recovery source required")
            self.workflow.recovery_account_pin(row)
            self.dependencies = self.workflow._dependencies()
            self.require_current()

    def publish(self, run_id: str, facts: dict[str, Any]) -> None:
        """Issue immutable primitive fixtures bound to the actual local source."""
        from .broker_identity import BrokerSelector

        detached = primitive_copy(facts)
        with self.workflow.registry.lock:
            self.require_current()
            with self.workflow.native.db.transaction() as db:
                raw = db.execute("SELECT data FROM runs WHERE run_id=?", (run_id,)).fetchone()
                if raw is None:
                    raise ValueError("configured synthetic run required")
                row = json.loads(raw[0])
            if row.get("scope_v2", {}).get("environment") != "synthetic":
                raise ValueError("primitive fixtures require a synthetic run")
            snapshot = self.dependencies.lifecycle_store.observation_snapshot(BrokerSelector(
                row["binding"]["broker"], row["binding"]["account_id"],
            ))
            source = _digest([snapshot.generation, snapshot.evidence_json])
            self.records[run_id] = (row["revision"], source, detached)
            self.generations[run_id] = self.generations.get(run_id, 0) + 1

    def publish_plan(self, run_id: str, *, order: dict[str, Any], market: dict[str, Any],
                     entry: dict[str, Any], fees: list[dict[str, Any]]) -> None:
        """Issue a labelled prospective entry allocation, not an actual fill.

        Kept separate from lifetime observations until the command owner commits
        a durable hold. Only this trusted server source can issue such a plan.
        """
        from .models import Order

        with self.workflow.registry.lock:
            self.require_current()
            if run_id not in self.records:
                raise ValueError("bound lifetime source required")
            typed = Order.model_validate(primitive_copy(order))
            self.plans[run_id] = {"order": typed.model_dump(mode="json"), "market": primitive_copy(market),
                                  "entry": primitive_copy(entry), "fees": primitive_copy(fees),
                                  "source": self.records[run_id][:2]}
            self.plan_generations[run_id] = self.plan_generations.get(run_id, 0) + 1

    def resolve_plan(self, row: dict[str, Any], snapshot: Any) -> dict[str, Any]:
        """Resolve only the original account/source-bound prospective entry."""
        self.resolve(row, snapshot)
        identity = row["binding"]["run_id"]
        plan = self.plans.get(identity)
        if plan is None or tuple(plan["source"]) != self.records[identity][:2]:
            raise ValueError("bound prospective financial evidence unavailable")
        return {**{key: primitive_copy(value) for key, value in plan.items() if key != "source"},
                "publication": self.plan_generations[identity]}

    def resolve(self, row: dict[str, Any], snapshot: Any) -> dict[str, Any]:
        """Resolve detached facts for this exact current native/canonical binding.

        Args:
            row: Existing native owner record, never an HTTP evidence object.
            snapshot: Current snapshot from the incumbent canonical ledger.

        Returns:
            Exact primitive fixture facts, labelled synthetic by their run scope.

        Raises:
            ValueError: A source, account, transport or backend binding changed.
        """
        self.require_current()
        from .broker_identity import BrokerSelector
        from .workspace_migrations import read_workspace_snapshot

        selector = BrokerSelector(row["binding"]["broker"], row["binding"]["account_id"])
        current = self.dependencies.registry.snapshot_selector(selector)
        pin = (self.workflow.recovery_account_pin(row) if row.get("read_only_recovery") is not None
               else row["account_pin"])
        workspace = read_workspace_snapshot(self.dependencies.workspace_path).version
        if (workspace is None or str(current.registry_incarnation) != pin["registry_incarnation"]
                or current.generation != pin["registry_generation"]
                or str(workspace.instance_id) != pin["workspace_instance_id"]
                or workspace.generation != pin["workspace_generation"]):
            raise ValueError("primitive account owner changed")
        revision, source, facts = self.records[row["binding"]["run_id"]]
        if (row["scope_v2"]["environment"] != "synthetic" or revision != row["revision"]
                or source != _digest([snapshot.generation, snapshot.evidence_json])):
            raise ValueError("primitive source generation changed")
        return primitive_copy(facts)


def initial_financial() -> dict[str, Any]:
    """Initialise counters only for a newly configured run, without evidence."""
    return {"revision": 0, "floors": {}, "history": {}, "reservations": {},
            "loss_latch": {"revision": 0, "retired": False}, "assessment": None,
            "charge_history": {}, "fee_liabilities": "0", "unresolved_entry_ids": [], "known_fills": {}}


def has_financial_obligations(row: dict[str, Any]) -> bool:
    """Local census for retirement; transfer and worker exit are not settlement."""
    from .native_model_custody_v2 import model_obligations

    if model_obligations(row):
        return True
    state = row.get("financial_v2")
    if state is None:
        return False
    return (bool(state.get("unresolved_entry_ids")) or Fraction(state.get("fee_liabilities", "0")) > 0
            or any(hold["state"] != "released" for hold in state["reservations"].values())
            or any(fill["quantity"] != fill["exited"] for fill in state.get("known_fills", {}).values())
            or any(fill["quantity"] != fill["exited"] for entry in state["history"].values()
                   for fill in entry["fills"].values()))


def _history(entry: dict[str, Any], options: bool) -> dict[str, Any]:
    """Retain immutable fill identities and cumulative exit evidence, not a book."""
    fills = {}
    for fill in entry["fills" if options else "lots"]:
        identity = fill["fill_ref"]["id"]
        immutable = {key: value for key, value in fill.items()
                     if key not in {"exits", "exited_quantity", "gross_exit_proceeds"}}
        fills[identity] = {
            "immutable": _digest(immutable), "fill_ref": fill["fill_ref"], "quantity": fill["quantity"],
            "exited": sum(item["quantity"] for item in fill["exits"]) if options else fill["exited_quantity"],
            "exits": {item["execution_ref"]["id"]: _digest(item) for item in fill["exits"]} if options else {},
        }
    return {"entry_ref": entry["entry_ref"], "fills": fills,
            "possible": None if options else entry["remaining_possible_quantity"],
            "writes": {write["write_ref"]["id"]: {
                "identity": _digest({key: write[key] for key in ("write_ref", "contract_ref", "purpose", "side",
                                                               "original_quantity")}),
                "released": write["released_quantity"],
            } for write in entry["writes"]} if options else {}}


def _retain_known_fills(state: dict[str, Any], facts: dict[str, Any], options: bool) -> None:
    """Retain individually valid fills even when tariff or margin is unavailable."""
    from .native_options_risk_v2 import OptionFill
    from .native_risk_v2 import FilledLot

    observed = {}
    for entry in facts["entries"]:
        entry_ref = RevisionRefV2.model_validate(entry["entry_ref"])
        for raw in entry["fills" if options else "lots"]:
            fill = _decode(raw, OptionFill if options else FilledLot)
            exited = sum(item.quantity for item in fill.exits) if options else fill.exited_quantity
            if fill.quantity <= 0 or not 0 <= exited <= fill.quantity or fill.fill_ref.id in observed:
                raise ValueError("fill quantity or identity conflicting")
            immutable = {key: value for key, value in raw.items()
                         if key not in {"exits", "exited_quantity", "gross_exit_proceeds"}}
            observed[fill.fill_ref.id] = {
                "entry_ref": entry_ref.model_dump(), "fill_ref": fill.fill_ref.model_dump(),
                "quantity": fill.quantity, "exited": exited, "immutable": _digest(immutable),
                "exits": {item["execution_ref"]["id"]: _digest(item) for item in raw["exits"]} if options else {},
                "gross_exit_proceeds": None if options else raw["gross_exit_proceeds"],
            }
    known = state.setdefault("known_fills", {})
    conflict = False
    for identity, new in observed.items():
        old = known.get(identity)
        if old is not None and (
                old["entry_ref"] != new["entry_ref"] or old["immutable"] != new["immutable"]
                or old["exited"] > new["exited"]
                or any(new["exits"].get(key) != value for key, value in old["exits"].items())
                or (not options and Fraction(new["gross_exit_proceeds"]) < Fraction(old["gross_exit_proceeds"]))):
            conflict = True
            continue
        known[identity] = new
    if conflict or not set(known) <= set(observed):
        raise ValueError("known lifetime fill missing or conflicting")


def _retain_principal_floors(state: dict[str, Any], facts: dict[str, Any], row: dict[str, Any], now: int) -> None:
    """Retain independently observed commitment before unrelated fee validation.

    This raises a lifetime floor only. It cannot establish a current assessment,
    release a hold, or qualify an order when another required fact is missing.
    """
    options = row["schema_version"] == "2-options-1"
    for entry in facts["entries"]:
        identity = RevisionRefV2.model_validate(entry["entry_ref"]).id
        prior = state["floors"].get(identity, {"principal": "0", "fee": "0"})
        principal = Fraction(prior["principal"])
        fills = entry["fills" if options else "lots"]
        if not options or entry["side"] == "long":
            cost = sum((Fraction(_decode(fill["unit_price" if options else "unit_cost"], Decimal))
                        * fill["quantity"] for fill in fills), Fraction(0))
            principal = max(principal, cost)
        elif entry["side"] == "short" and entry["margin"] is not None:
            margin = entry["margin"]
            RevisionRefV2.model_validate(margin["margin_ref"])
            contract = RevisionRefV2.model_validate(margin["contract_ref"])
            opened = sum(fill["quantity"] - sum(exit_["quantity"] for exit_ in fill["exits"]) for fill in fills)
            if (contract.model_dump() != entry["contract"]["contract_ref"]
                    or entry["contract"] != entry["current_contract"]
                    or type(margin["filled_units"]) is not int or margin["filled_units"] != opened
                    or margin["allocation"] != "exact_standalone_disjoint"
                    or type(margin["observed_at_ms"]) is not int
                    or not 0 <= now - margin["observed_at_ms"] <= row["config_v2"]["risk"]["max_mark_age_ms"]):
                raise ValueError("independent margin floor unavailable")
            if margin["filled_floor"] is not None:
                floor = Fraction(_decode(margin["filled_floor"], Decimal))
                if (floor > 0) != (opened > 0):
                    raise ValueError("independent margin allocation conflicting")
                principal = max(principal, floor)
        state["floors"][identity] = {"principal": _money(principal), "fee": prior["fee"]}


def _required_money(value: Decimal | None) -> Fraction:
    if value is None:
        raise ValueError("fee liability unavailable")
    return Fraction(value)


def _fee_liabilities(inputs: Any) -> str:
    from .native_options_risk_v2 import OptionsFeeComponent

    unpaid = Fraction(0)
    for fee in inputs.fees:
        for component in fee.components:
            if isinstance(component, OptionsFeeComponent):
                paid = sum((_required_money(charge.amount) for charge in component.charges
                            if charge.payment == "paid"), Fraction(0))
            else:
                paid = sum((_required_money(charge.amount) for charge in component.incurred), Fraction(0))
            unpaid += _required_money(component.total_upper_bound) - paid
    return _money(unpaid)


def _resolve_charges(state: dict[str, Any], fees: list[dict[str, Any]], options: bool) -> None:
    """Retain unique immutable charges independently of uncertain payment."""
    observed = {}
    for fee in fees:
        for component in fee["components"]:
            for charge in component["charges" if options else "incurred"]:
                ref = RevisionRefV2.model_validate(charge["charge_ref"])
                if ref.id in observed:
                    raise ValueError("duplicate charge")
                observed[ref.id] = {"reference": ref.model_dump(), "amount": charge["amount"],
                                    "at": charge["observed_at_ms" if options else "charged_at_ms"]}
    previous = state.setdefault("charge_history", {})
    if any(observed.get(key) != value for key, value in previous.items()):
        raise ValueError("known charge disappeared or changed")
    previous.update(observed)
    if not options:
        for fee in fees:
            for component in fee["components"]:
                for charge in component["incurred"]:
                    if charge.get("payment") != "paid":
                        raise ValueError("cash charge payment unavailable")
                    proof = RevisionRefV2.model_validate(charge["payment_evidence_ref"]).model_dump()
                    evidence = state.setdefault("payment_evidence", {}).setdefault(charge["charge_ref"]["id"], [])
                    if proof not in evidence:
                        evidence.append(proof)
                    del charge["payment"], charge["payment_evidence_ref"]


def project_financial(workflow: Any, row: dict[str, Any], snapshot: Any, now: int,
                      *, prospective: dict[str, Any] | None = None) -> dict[str, Any]:
    """Resolve primitive facts, disjoint retained holds, floors and latch CAS.

    Mutates only the detached row. The caller must revalidate the exact native
    and canonical revisions before committing it in the incumbent transaction.
    A missing source cannot delete retained commitments or clear retirement.
    """
    state = row.setdefault("financial_v2", initial_financial())
    unavailable = {"status": "unavailable", "reasons": ["primitive_source_unavailable"],
                   "capital": None, "exposure": None, "loss": None}
    facts = None
    # A new bounded capture may invalidate the earlier primitive publication.
    # Missing facts must retain holds, not masquerade as an evaluated old source.
    row["_evaluated_primitive_digest"] = None
    row["_evaluated_primitive_generation"] = None
    try:
        issuer = workflow._primitive_source
        if type(issuer) is not PrimitiveFixtureSource:
            raise ValueError("primitive_source_unavailable")
        row["_evaluated_primitive_generation"] = issuer.generations[row["binding"]["run_id"]]
        facts = issuer.resolve(row, snapshot)
        row["_evaluated_primitive_digest"] = _digest(facts)
        if prospective is not None:
            # The command owner passes the actual source-issued plan, before
            # committing a hold. Never count it as an observed execution.
            if issuer.resolve_plan(row, snapshot) != prospective:
                raise ValueError("prospective source changed")
            if any(entry["entry_ref"] == prospective["entry"]["entry_ref"] for entry in facts["entries"]):
                raise ValueError("prospective entry already represented")
            facts["entries"].append(primitive_copy(prospective["entry"]))
            facts["fees"].extend(primitive_copy(prospective["fees"]))
        if set(facts) != {"history_from_ms", "observed_at_ms", "native_order_date", "tariff_ref",
                          "tariff_from_ms", "tariff_through_ms", "entries", "fees"}:
            raise ValueError("closed primitive history required")
        if (type(facts["history_from_ms"]) is not int or facts["history_from_ms"] > row["configured_at_ms"]
                or type(facts["native_order_date"]) is not str
                or date.fromisoformat(facts["native_order_date"]).isoformat() != facts["native_order_date"]):
            raise ValueError("history_or_native_date_unavailable")
        _retain_known_fills(state, facts, row["schema_version"] == "2-options-1")
        _retain_principal_floors(state, facts, row, now)
        _resolve_charges(state, facts["fees"], row["schema_version"] == "2-options-1")
        tariff = RevisionRefV2.model_validate(facts["tariff_ref"])
        scope = RunScopeV2.model_validate(row["scope_v2"])
        config = workflow._config({"schema_version": row["schema_version"], "config": row["config_v2"]}).config
        policy = config.risk
        source = RevisionRefV2.model_validate(reference("primitive-source", [snapshot.generation,
                                                                           snapshot.evidence_json,
                                                                           row["_evaluated_primitive_digest"]]))
        reservation = RevisionRefV2.model_validate(reference("native-reservations", state))
        latch_ref = RevisionRefV2.model_validate(reference("native-loss-latch", state["loss_latch"]))
        options = row["schema_version"] == "2-options-1"
        entries, fees = facts["entries"], facts["fees"]
        if type(entries) is not list or type(fees) is not list:
            raise ValueError("complete primitive census required")
        # A reservation is a disjoint owned proposal, never an extra copy of an
        # already represented entry. Missing representation retains its hold.
        entry_ids = {entry["entry_ref"]["id"] for entry in entries}
        if not set(state.get("unresolved_entry_ids", ())) <= entry_ids:
            raise ValueError("unresolved lifetime evidence missing")
        missing_representation = False
        for hold in state["reservations"].values():
            if hold["state"] != "released" and hold["entry"]["entry_ref"]["id"] not in entry_ids:
                missing_representation = True
                entries.append(primitive_copy(hold["entry"]))
                fees.extend(primitive_copy(hold["fees"]))
        for hold in state["reservations"].values():
            if hold["state"] == "released" or "command_id" not in hold:
                continue
            entry = next((item for item in entries if item["entry_ref"] == hold["entry"]["entry_ref"]), None)
            if entry is None:
                raise ValueError("command financial identity missing")
            releasing = (all(write["remaining_quantity"] == 0 for write in entry["writes"]) if options else
                         entry["remaining_possible_quantity"] == 0 and not entry["unknown_possible_write"])
            if releasing:
                evidence = row.get("_command_observations", {}).get(hold["command_id"])
                if (evidence is None or not evidence["zero_fill_terminal"]
                        or any(resource["native_order_date"] != facts["native_order_date"]
                               for resource in evidence["resources"])
                        or entry["fills" if options else "lots"]):
                    raise ValueError("command release requires exact terminal native and financial evidence")
        current_history = {entry["entry_ref"]["id"]: _history(entry, options) for entry in entries}
        for identity, prior in state["history"].items():
            current = current_history.get(identity)
            if current is None or current["entry_ref"] != prior["entry_ref"]:
                raise ValueError("lifetime_entry_missing_or_changed")
            for write_id, old_write in prior.get("writes", {}).items():
                new_write = current["writes"].get(write_id)
                if (new_write is None or new_write["identity"] != old_write["identity"]
                        or new_write["released"] < old_write["released"]):
                    raise ValueError("possible_write_history_changed")
            if not options and prior.get("possible") is not None:
                delta = (sum(fill["quantity"] for fill in current["fills"].values())
                         - sum(fill["quantity"] for fill in prior["fills"].values()))
                if current["possible"] is not None and current["possible"] + delta < prior["possible"]:
                    hold = state["reservations"].get(identity, {})
                    evidence = row.get("_command_observations", {}).get(hold.get("command_id"))
                    if (evidence is None or not evidence["zero_fill_terminal"] or current["fills"]
                            or current["possible"] != 0
                            or any(resource["native_order_date"] != facts["native_order_date"]
                                                               for resource in evidence["resources"])):
                        raise ValueError("possible_write_release_unproved")
            for fill_id, old in prior["fills"].items():
                new = current["fills"].get(fill_id)
                if (new is None or new["immutable"] != old["immutable"] or new["exited"] < old["exited"]
                        or any(new["exits"].get(key) != value for key, value in old["exits"].items())):
                    raise ValueError("lifetime_fill_missing_or_changed")
        if missing_representation:
            raise ValueError("held_write_source_missing")
        if options:
            from .native_options_risk_v2 import OptionsBasis, OptionsInputs, OptionsLatch, assess_options_risk

            basis = OptionsBasis(scope, policy.policy_ref, source, reservation, policy.fee_policy_ref, tariff, source)
            mapped = []
            from .native_options_risk_v2 import OptionEntry, OptionsFee
            for entry in entries:
                entry = dict(entry)
                prior = state["floors"].get(entry["entry_ref"]["id"], {"principal": "0", "fee": "0"})
                cost = sum((Fraction(fill["unit_price"]) * fill["quantity"] for fill in entry["fills"]), Fraction(0))
                principal = max(Fraction(prior["principal"]), cost if entry["side"] == "long" else Fraction(0))
                if entry["side"] == "short" and entry["margin"] is not None:
                    floor = entry["margin"]["filled_floor"]
                    if floor is not None:
                        principal = max(principal, Fraction(floor))
                margin = entry.pop("margin")
                entry.update(basis=basis, committed_principal=Decimal(_money(principal)),
                             committed_fee_allowance=Decimal(prior["fee"]))
                hints = get_type_hints(OptionEntry)
                values = {key: value if key in {"basis", "committed_principal", "committed_fee_allowance"}
                          else _decode(value, hints[key]) for key, value in entry.items()}
                from .native_options_risk_v2 import StandaloneMargin
                values["margin"] = None if margin is None else StandaloneMargin(
                    basis=basis, **{key: _decode(value, get_type_hints(StandaloneMargin)[key])
                                   for key, value in margin.items()},
                )
                mapped.append(OptionEntry(**values))
            inputs = OptionsInputs(
                basis, facts["history_from_ms"], facts["observed_at_ms"], "complete", "exact_disjoint",
                                   facts["tariff_from_ms"], facts["tariff_through_ms"], tuple(mapped),
                tuple(_decode({**fee, "tariff_ref": tariff.model_dump()}, OptionsFee) for fee in fees),
            )
            assessment = assess_options_risk(policy, inputs, OptionsLatch(scope, policy.policy_ref, latch_ref,
                                                                         state["loss_latch"]["retired"]), now_ms=now)
        else:
            from .native_risk_v2 import (
                EntryObservation,
                FeeAllocation,
                FeeSchedule,
                LatchObservation,
                RiskInputs,
                assess_risk,
            )

            mapped = []
            for entry in entries:
                prior = state["floors"].get(entry["entry_ref"]["id"], {"principal": "0", "fee": "0"})
                cost = sum((Fraction(lot["unit_cost"]) * lot["quantity"] for lot in entry["lots"]), Fraction(0))
                principal = max(Fraction(prior["principal"]), cost)
                hints = get_type_hints(EntryObservation)
                mapped.append(EntryObservation(
                    scope=scope, source_ref=source, currency="INR", family="cash_long",
                    committed_principal=Decimal(_money(principal)), committed_fee_allowance=Decimal(prior["fee"]),
                    **{key: _decode(value, hints[key]) for key, value in entry.items()},
                ))
            schedule = FeeSchedule(policy.fee_policy_ref, tariff, source, "INR", "cash_long", facts["tariff_from_ms"],
                                   facts["tariff_through_ms"], True, "exact_component_upper_bounds")
            inputs = RiskInputs(scope, policy.policy_ref, source, reservation, policy.fee_policy_ref,
                                facts["history_from_ms"], facts["observed_at_ms"], "INR", True, True,
                                tuple(mapped), schedule,
                                tuple(_decode({**fee, "tariff_ref": tariff.model_dump()}, FeeAllocation)
                                      for fee in fees))
            assessment = assess_risk(policy, inputs, LatchObservation(scope, policy.policy_ref, latch_ref,
                                                                    state["loss_latch"]["retired"]), now_ms=now)
        result = {"status": assessment.status, "reasons": list(assessment.reasons),
                  **{key: None if getattr(assessment, key) is None else str(getattr(assessment, key))
                     for key in ("capital", "exposure", "loss")}}
        if assessment.status == "unavailable":
            state["unresolved_entry_ids"] = sorted(set(state.get("unresolved_entry_ids", ())) | entry_ids)
        if assessment.status != "unavailable":
            state["unresolved_entry_ids"] = []
            state["fee_liabilities"] = _fee_liabilities(inputs)
            state["history"] = current_history
            for entry in entries:
                identity = entry["entry_ref"]["id"]
                pending = (any(write["remaining_quantity"] is None or write["remaining_quantity"] > 0
                               for write in entry["writes"]) if options else
                           entry["unknown_possible_write"] or entry["remaining_possible_quantity"] != 0)
                if pending:
                    state["reservations"][identity] = {
                        **state["reservations"].get(identity, {}),
                        "state": "held", "entry": primitive_copy(entry),
                        "fees": [primitive_copy(fee) for fee in fees if fee["entry_ref"] == entry["entry_ref"]],
                        "source_ref": source.model_dump(),
                    }
                elif identity in state["reservations"]:
                    state["reservations"][identity]["state"] = "released"
            for entry in inputs.entries:
                identity = entry.entry_ref.id
                prior = state["floors"].get(identity, {"principal": "0", "fee": "0"})
                principal, fee = Fraction(entry.committed_principal), Fraction(entry.committed_fee_allowance)
                from .native_options_risk_v2 import OptionsAssessment

                if isinstance(assessment, OptionsAssessment):
                    principal = max(principal, Fraction(dict(assessment.required_lifetime_principal)[entry.entry_ref]))
                    fee = max(fee, Fraction(dict(assessment.required_lifetime_fee_allowance)[entry.entry_ref]))
                else:
                    for allocation in inputs.fees:
                        if allocation.entry_ref == entry.entry_ref and allocation.phase not in {"entry_pending",
                            "exit_pending"}:
                            fee += sum((_required_money(c.total_upper_bound) for c in allocation.components),
                                       Fraction(0))
                    fee = max(Fraction(prior["fee"]), fee - Fraction(entry.committed_fee_allowance))
                old = {"principal": Fraction(prior["principal"]), "fee": Fraction(prior["fee"])}
                state["floors"][identity] = {"principal": _money(max(old["principal"], principal)),
                                             "fee": _money(max(old["fee"], fee))}
            if assessment.transition.action == "retire_entries_and_request_custody":
                if assessment.transition.expected_revision != latch_ref:
                    raise ValueError("loss latch revision changed")
                if not state["loss_latch"]["retired"]:
                    state["loss_latch"] = {"revision": state["loss_latch"]["revision"] + 1, "retired": True}
                    row["events_v2"].append(reference("loss-retirement", state["loss_latch"]))
                row["loss_threshold_latched"] = True
                row["entry_state"] = "retired"
                if row["grant"] is not None:
                    row["grant"]["revoked"] = True
        state["assessment"] = result
        state["source_ref"] = source.model_dump()
    except (ValueError, TypeError, KeyError, ArithmeticError):
        if type(facts) is dict and type(facts.get("entries")) is list:
            identities = set(state.get("unresolved_entry_ids", ()))
            for entry in facts["entries"]:
                if type(entry) is dict and type(entry.get("entry_ref")) is dict:
                    identity = entry["entry_ref"].get("id")
                    if type(identity) is str:
                        identities.add(identity)
            state["unresolved_entry_ids"] = sorted(identities)
        state["assessment"] = unavailable
    state["revision"] += 1
    return state["assessment"]
