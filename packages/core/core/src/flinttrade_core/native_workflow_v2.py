"""Versioned native workflow within the existing execution-authority owner.

The run and command tables of ``NativeAutonomy`` remain the only durable
custody. Request references are selections, never qualification evidence.
Local reads never bind read permissions, fetch a broker or start a producer.
"""
from __future__ import annotations

import json
import time
from typing import TYPE_CHECKING, Any

from .broker_identity import BrokerSelector, serialise_broker_selector
from .execution_session import ExecutionSession
from .native_autonomy_contracts_v2 import (
    ConfigureRequestV2,
    InspectRequestV2,
    OptionsConfigureRequestV2,
    OptionsRunViewV2,
    QualificationReportV2,
    RunScopeV2,
    RunViewV2,
)

if TYPE_CHECKING:
    from .native_autonomy import NativeAutonomy


def _hash(value: Any) -> str:
    from .native_autonomy import _digest

    return _digest(value)


def _json(value: Any) -> str:
    from .native_autonomy import _encoded

    return _encoded(value)


def _require_model_budget(
    calls: list[dict[str, Any]], pin: dict[str, Any], *, tokens: int, micros: int,
) -> None:
    """Check conservative lifetime debit plus a prospective reservation.

    Args:
        calls: Durable native calls with the existing dispatcher's receipts.
        pin: Exact registered native model limits, not the connection budget.
        tokens: Additional tokens not already represented by a retained call.
        micros: Additional currency micros not already represented by a call.

    Raises:
        ValueError: Known usage or still-reserved usage exceeds the native cap.
    """
    from fractions import Fraction

    used_tokens, used_cost = tokens, micros
    for call in calls:
        attempts = (call.get("receipt") or {}).get("attempts", [])
        charged_tokens = sum(a["charged"]["input_tokens"] + a["charged"]["output_tokens"] for a in attempts)
        charged_cost = sum(a["charged"]["currency_micros"] for a in attempts)
        used_tokens += max(call["tokens_reserved"], charged_tokens)
        used_cost += max(call["cost_micros_reserved"], charged_cost)
    if used_tokens > pin["max_tokens"] or Fraction(used_cost, 1_000_000) > Fraction(pin["cost_cap"]["amount"]):
        raise ValueError("non-replenishing model allowance exhausted")


class NativeWorkflowV2:
    """Versioned operations on the incumbent run/command custody.

    Args:
        native: Exact owning NativeAutonomy, already bound to its backend lease.
            This module creates no database, account or independent authority.
    """

    def __init__(self, native: NativeAutonomy) -> None:
        self.native = native
        self.registry = native.registry
        self.app = native.app
        self._primitive_source: Any = None
        self._safety = self.app.config.get("SAFETY")
        self._producers: dict[str, Any] = {}
        self._model_sources: dict[str, tuple[Any, Any, Any, Any]] = {}
        from .native_custody_v2 import NativeCustodyV2

        self.custody = NativeCustodyV2(self)

    def install_primitive_fixture_source(self, *, transport: object, transport_binding: object,
                                         current_transport_binding: Any) -> Any:
        """Bind an explicit server-owned inert source; never reachable via HTTP.

        This supports labelled synthetic primitives only. The source resolves
        current backend/account/canonical/transport bindings on every use.
        """
        from .native_financial_v2 import PrimitiveFixtureSource

        with self.registry.lock:
            if self._primitive_source is not None:
                raise ValueError("primitive fixture source already bound")
            self._primitive_source = PrimitiveFixtureSource(
                self, transport=transport, transport_binding=transport_binding,
                current_transport_binding=current_transport_binding,
            )
            return self._primitive_source

    def kill_epoch(self) -> int:
        """Bind permission to the actual kill owner's monotonic activation epoch."""
        from flinttrade_engine.safety import KillSwitch

        if self.app.config.get("SAFETY") is not self._safety or type(self._safety.l5_kill) is not KillSwitch:
            raise ValueError("safety owner changed")
        kill = self._safety.l5_kill
        with kill._condition:
            return kill._activation_sequence

    def register_producer(self, registration: Any) -> dict[str, Any]:
        """Register reviewed server code; HTTP selections cannot install code."""
        from .native_financial_v2 import primitive_copy
        from .native_producer_v2 import ProducerRegistration

        if type(registration) is not ProducerRegistration:
            raise ValueError("registered bounded producer required")
        registration.require_current()
        identity = registration.pin["producer_ref"]["id"]
        with self.registry.lock:
            self.registry._require()
            if identity in self._producers:
                raise ValueError("producer registration already exists")
            self._producers[identity] = registration
        return primitive_copy(registration.pin)

    def register_model_producer(self, *, name: str, order: dict[str, Any], threshold: str,
                                interval_ms: int, max_decisions: int, selection: dict[str, Any],
                                max_requests: int, max_tokens: int, cost_cap: dict[str, str]) -> dict[str, Any]:
        """Bind a finite strategy to the actual existing model task owner.

        Service connection, admission, privacy, quota and tariff remain with
        their existing owners. No model client, callback or evidence boolean is
        accepted from a native request, and registration sends no request.
        """
        from .native_financial_v2 import primitive_copy, reference
        from .native_producer_v2 import ProducerRegistration
        from .run_adoption import ModelRunServices
        from .service_task_dispatch import ServiceTaskDispatcher

        services = self.app.config.get("MODEL_RUN_SERVICES")
        if type(services) is not ModelRunServices:
            raise ValueError("actual model services required")
        dispatcher = services.dispatcher()
        if type(dispatcher) is not ServiceTaskDispatcher:
            raise ValueError("actual task dispatcher required")
        selection = primitive_copy(selection)
        if set(selection) != {"connection_id", "connection_revision", "model", "effort"}:
            raise ValueError("exact existing model selection required")
        snapshot = dispatcher.store.read_snapshot()
        admission = dispatcher.admission(selection["connection_id"])
        policy = admission["policy"]
        if (policy is None or not policy["enabled"] or snapshot.etag != selection["connection_revision"]
                or selection["effort"] not in policy["efforts"]
                or policy["tariff"]["currency"] != cost_cap.get("currency")
                or not any(str(c.connection_id) == selection["connection_id"] and c.model == selection["model"]
                           and c.auth_mode == "api_key" for c in snapshot.connections)):
            raise ValueError("current qualified model selection required")
        binding = {"selection": selection, "admission": admission}
        model_pin = {"connection_ref": reference(selection["connection_id"], selection["connection_revision"]),
                     "model_ref": reference(selection["model"], policy["model_revision"]),
                     "protocol": policy["protocol"], "effort": selection["effort"],
                     "max_requests": max_requests, "max_tokens": max_tokens, "cost_cap": cost_cap}
        registered = ProducerRegistration.model_entry(name=name, order=order, threshold=threshold,
            interval_ms=interval_ms, max_decisions=max_decisions, binding=binding, model_pin=model_pin)
        pin = self.register_producer(registered)
        with self.registry.lock:
            self._model_sources[name] = (services, dispatcher, dispatcher.transport,
                                         getattr(dispatcher.transport, "handler", None))
        return pin

    def _model_source(self, registration: Any) -> Any:
        name = registration.pin["producer_ref"]["id"]
        services, dispatcher, transport, handler = self._model_sources[name]
        if (self.app.config.get("MODEL_RUN_SERVICES") is not services or services.closed
                or self.app.config.get("SERVICE_TASK_DISPATCHER") is not dispatcher
                or dispatcher.transport is not transport or getattr(transport, "handler", None) is not handler):
            raise ValueError("model execution owner or transport changed")
        selection = registration.model_binding["selection"]
        if (dispatcher.store.read_snapshot().etag != selection["connection_revision"]
                or dispatcher.admission(selection["connection_id"]) != registration.model_binding["admission"]):
            raise ValueError("model configuration changed")
        return dispatcher

    def financial_status(self, token: str, run_id: str) -> dict[str, Any]:
        """Read the incumbent owner's persisted floors, holds and loss latch."""
        from .native_financial_v2 import initial_financial

        who, _claims = self.native._operator(token, write=False)
        with self.registry.lock, self.native.db.transaction() as db:
            row = self._get(db, run_id, who.actor_ref)
            return row.get("financial_v2", initial_financial())

    def grant(self, token: str, run_id: str, body: dict[str, Any]) -> dict[str, Any]:
        """Issue finite permission after exact receiving acceptance; never Start."""
        from uuid import uuid4

        from .native_autonomy_contracts_v2 import EntryGrantV2, OptionsEntryGrantV2
        from .native_financial_v2 import has_financial_obligations, reference

        who, claims = self.native._operator(token, live=True)
        with self.registry.lock, self.native.db.transaction() as db:
            row = self._get(db, run_id, who.actor_ref)
            selection = self.custody._selection(row, body)
            pins = self.custody._pins(db, row, claims)
            preview = row.get("preview_v2")
            if (preview is None or not preview["consumed"] or preview["selection"] != selection
                    or preview["pins"] != pins or row["grant"] is not None or row["entry_state"] != "ungranted"):
                raise ValueError("exact unused finite receiving acceptance required")
            self.require_qualification(row, claims)
            for raw, in db.execute("SELECT data FROM runs WHERE run_id!=?", (run_id,)):
                other = json.loads(raw)
                if other["binding"]["account"] == row["binding"]["account"] and (
                        has_financial_obligations(other)
                        or other.get("grant") is not None and not other["grant"]["revoked"]):
                    raise ValueError("another run retains account custody")
            expires = selection["expires_at_ms"]
            if expires > min(row["report_v2"]["expires_at_ms"], int(claims["exp"] * 1000)):
                raise ValueError("grant exceeds current qualification or session")
            model = EntryGrantV2 if row["schema_version"] == "2" else OptionsEntryGrantV2
            public = model.model_validate({
                "grant_ref": reference("grant:" + uuid4().hex, [selection, pins]),
                "scope": row["scope_v2"], "report_ref": selection["report_ref"],
                "policy_ref": selection["policy_ref"], "risk": row["config_v2"]["risk"],
                "limits": selection["limits"], "issued_by": who.actor_ref,
                "issued_at_ms": int(time.time() * 1000), "expires_at_ms": expires, "state": "active",
            }).model_dump(mode="json")
            row["grant_v2"] = public
            row["grant_plan_digest"] = pins["proposal"]
            row["grant_kill_epoch"] = self.kill_epoch()
            row["grant"] = {"grant_id": public["grant_ref"]["id"], "revoked": False,
                            "jti": claims["jti"], "session_expires_at": claims["exp"],
                            "expires_at": expires / 1000, "binding_revision": row["revision"],
                            "qualification": row["report_v2"]["report_ref"],
                            "claims": {key: claims[key] for key in ("sub", "jti", "mode")},
                            "max_commands": selection["limits"]["max_commands"],
                            "actions": ["cancel" if a == "cancel_unfilled" else a
                                        for a in selection["limits"]["actions"]]}
            row["entry_state"] = "granted"
            self.native._save(db, row)
        return self.status(token, run_id)

    def _producer(self, row: dict[str, Any]) -> Any:
        from .native_producer_v2 import ProducerRegistration

        pin = row["config_v2"]["producer"]
        registered = self._producers.get(pin["producer_ref"]["id"])
        if type(registered) is not ProducerRegistration or registered.pin != pin:
            raise ValueError("exact registered producer unavailable")
        registered.require_current()
        if registered.model_binding is not None:
            try:
                self._model_source(registered)
            except (KeyError, RuntimeError) as exc:
                raise ValueError("registered model owner unavailable") from exc
        return registered

    def require_qualification(self, row: dict[str, Any], claims: dict[str, Any]) -> None:
        """Recheck the actual account, source, implementation and assessed risk."""
        config = self._config({"schema_version": row["schema_version"], "config": row["config_v2"]}).config
        if self._account_pin(claims, config) != row["account_pin"]:
            raise ValueError("qualification account changed")
        dependencies = self._dependencies()
        selector = BrokerSelector(config.broker, config.account_id)
        handle = dependencies.registry.get_connected_session_for(
            selector, current_authority=dependencies.session_provider.current_authority_for(selector))
        if handle.is_read_only:
            raise ValueError("read-only session cannot qualify entry authority")
        # An accepted plan revalidates this same producer below. Avoid building
        # and recursively inspecting the identical strategy twice per read
        # frontier; ungranted qualification still performs its own check.
        planned = row.get("grant") is not None and row.get("grant_plan_digest") is not None
        if not planned:
            self._producer(row)
        report = row["report_v2"]
        if (report is None or report["status"] != "eligible"
                or report["expires_at_ms"] <= int(time.time() * 1000)
                or row["loss_threshold_latched"] or self.app.config["SAFETY"].l5_kill.is_active):
            raise ValueError("current owner qualification required")
        snapshot = self._dependencies().lifecycle_store.observation_snapshot(
            BrokerSelector(config.broker, config.account_id))
        detail = row["inspection_detail"]
        if (detail["canonical_generation"] != snapshot.generation
                or detail["canonical_digest"] != _hash(snapshot.evidence_json)
                or self._primitive_source is None
                or self._primitive_source.generations.get(row["binding"]["run_id"])
                != row.get("_evaluated_primitive_generation")
                or _hash(self._primitive_source.resolve(row, snapshot)) != row.get("_evaluated_primitive_digest")):
            raise ValueError("qualification source changed")
        if planned:
            self._plan(row)

    def start(self, token: str, run_id: str, body: dict[str, Any]) -> dict[str, Any]:
        """Acquire and start the registered finite worker once, separately from grant."""
        from .native_autonomy_contracts_v2 import StartRequestV2
        from .native_producer_v2 import NativeProducerOwner

        request = StartRequestV2.model_validate(body)
        who, claims = self.native._operator(token, live=True)
        with self.registry.lock, self.native.db.transaction() as db:
            row = self._get(db, run_id, who.actor_ref)
            if (request.run_id != run_id or request.expected_binding_revision != row["revision"]
                    or row["entry_state"] != "granted" or row["grant"] is None
                    or request.grant_ref.model_dump() != row["grant_v2"]["grant_ref"]
                    or run_id in self.registry.owners or not self.native._grant_current(row)
                    or self.app.config.get("RUNTIME_ACCEPTING_REQUESTS") is not True):
                raise ValueError("current unused grant and producer required")
            self.require_qualification(row, claims)
            self._plan(row)
            owner = NativeProducerOwner(self, row, self._producer(row))
            self.registry.owners[run_id] = owner
            row["entry_state"] = "started"
            row["producer_state"] = "not_started"
            row["producer_reads"] = 0
            row["producer_decisions"] = []
            self.native._save(db, row)
            with self.registry.db.transaction() as registry_db:
                registry_db.execute("UPDATE sessions SET entries=1,generation=generation+1,state='starting' "
                                    "WHERE run_id=?", (run_id,))
        try:
            owner.start()
        except BaseException:
            self.native.retire(owner.scope)
            raise
        return self.status(token, run_id)

    def _plan(self, row: dict[str, Any]) -> dict[str, Any]:
        snapshot = self._dependencies().lifecycle_store.observation_snapshot(
            BrokerSelector(row["binding"]["broker"], row["binding"]["account_id"]))
        plan = self._primitive_source.resolve_plan(row, snapshot)
        if (row.get("grant_plan_digest") != _hash(plan)
                or plan["order"] != self._producer(row).order):
            raise ValueError("finite accepted proposal changed")
        return plan

    def _worker_row(self, db: Any, owner: Any) -> dict[str, Any]:
        from .native_producer_v2 import NativeProducerOwner

        if (type(owner) is not NativeProducerOwner or self.registry.owners.get(owner.scope.run_id) is not owner
                or owner.stop.is_set() or time.monotonic() >= owner.deadline):
            raise ValueError("exact producer no longer admitted")
        row = self._get(db, owner.scope.run_id, owner.scope.actor)
        self.native._entry_authority(row)
        return row

    def producer_observation(self, owner: Any) -> Any:
        """Consume one finite source observation; no implicit provider polling."""
        from fractions import Fraction

        from .models import Quote

        with self.registry.lock, self.native.db.transaction() as db:
            row = self._worker_row(db, owner)
            plan = self._plan(row)
            limits = row["grant_v2"]["limits"]
            if row["producer_reads"] >= limits["max_reads"]:
                raise ValueError("finite read allowance exhausted")
            market = plan["market"]
            order = owner.registration.order
            if (set(market) != {"instrument_id", "exchange", "product", "mark", "observed_at_ms"}
                    or (market["instrument_id"], market["exchange"], market["product"])
                    != (order["symbol"], order["exchange"], order["product"])
                    or type(market["mark"]) is not str or Fraction(market["mark"]) <= 0
                    or type(market["observed_at_ms"]) is not int
                    or not 0 <= int(time.time() * 1000) - market["observed_at_ms"]
                    <= row["config_v2"]["risk"]["max_mark_age_ms"]):
                raise ValueError("current exact market observation required")
            row["producer_reads"] += 1
            row["producer_state"] = "running"
            self.native._save(db, row)
            return Quote(symbol=order["symbol"], exchange=order["exchange"], ltp=market["mark"])

    def model_decision(self, owner: Any, index: int, quote: Any) -> bool:
        """Reserve one finite advisory task before the existing dispatcher.

        A model can only propose the already-registered order. Its text never
        selects accounts, instruments, size, authority or custody. Reservations
        remain monotonic even for late, refused or unknown provider outcomes.
        """
        from uuid import uuid4

        from .native_financial_v2 import primitive_copy

        registration = owner.registration
        binding = registration.model_binding
        if binding is None:
            raise ValueError("registered model binding required")
        dispatcher = self._model_source(registration)
        reserve = binding["admission"]["policy"]["reservation"]
        pin = registration.pin["model"]
        tokens = reserve["input_tokens"] + reserve["output_tokens"]
        micros = reserve["currency_micros"]
        with self.registry.lock, self.native.db.transaction() as db:
            row = self._worker_row(db, owner)
            calls = row.setdefault("model_calls", [])
            if len(calls) != index or len(calls) >= pin["max_requests"]:
                raise ValueError("non-replenishing model allowance exhausted")
            _require_model_budget(calls, pin, tokens=tokens, micros=micros)
            remaining = row["grant_v2"]["expires_at_ms"] - int(time.time() * 1000)
            if remaining <= 0:
                raise ValueError("model permission expired")
            task = {"request_id": str(uuid4()), "mode": "fixed", "selection": binding["selection"],
                    "prompt": _json({"instruction": "Return only JSON: decision is hold or propose. No tools.",
                                     "order_proposal": registration.order, "threshold": registration.threshold,
                                     "observed_mark": str(quote.ltp)}),
                    "classification": "private", "context_refs": [], "purpose": "assistant",
                    "deadline_ms": min(120_000, remaining), "max_output_tokens": reserve["output_tokens"],
                    "required_hard_controls": ["output_tokens"]}
            calls.append({"index": index, "request_id": task["request_id"], "task_digest": _hash(task),
                          "tokens_reserved": tokens, "cost_micros_reserved": micros,
                          "currency": pin["cost_cap"]["currency"], "state": "reserved", "receipt": None,
                          "usage_owner": dispatcher.ledger.identity})
            self.native._save(db, row)

        def current() -> None:
            """Recheck the native cap at the dispatcher's real invocation frontier."""
            with self.registry.lock, self.native.db.transaction() as db:
                row = self._worker_row(db, owner)
                self._model_source(registration)
                call = row["model_calls"][index]
                call["receipt"] = dispatcher.ledger.task_observation(
                    call["request_id"], owner.scope.actor,
                    expected_digest=call["task_digest"], expected_owner=call["usage_owner"],
                )
                self.native._save(db, row)
                _require_model_budget(row["model_calls"], pin, tokens=0, micros=0)

        result = dispatcher.dispatch(task, actor=owner.scope.actor, authority_check=current)
        # Settlement recording must survive Stop. It is evidence, not authority.
        with self.registry.lock, self.native.db.transaction() as db:
            row = self._get(db, owner.scope.run_id, owner.scope.actor)
            call = row["model_calls"][index]
            if call["request_id"] != result["request_id"] or call["state"] != "reserved":
                raise ValueError("model receipt identity conflicts")
            call["receipt"] = primitive_copy({key: value for key, value in result.items() if key != "output"})
            call["state"] = result["outcome"]
            self.native._save(db, row)
        current()  # Late text after Stop, expiry or source change cannot propose.
        if (result["outcome"] != "completed" or result.get("accounting") != "settled"
                or result.get("resolved_model") != binding["admission"]["policy"]["model_revision"]):
            raise ValueError("model outcome, accounting or serving identity unavailable")
        with self.registry.lock, self.native.db.transaction() as db:
            row = self._worker_row(db, owner)
            _require_model_budget(row["model_calls"], pin, tokens=0, micros=0)
        decision = json.loads(result["output"])
        if type(decision) is not dict or set(decision) != {"decision"} or decision["decision"] not in {"hold",
            "propose"}:
            raise ValueError("model did not return an exact bounded proposal")
        return decision["decision"] == "propose"

    def reconcile_model_calls(self, token: str, run_id: str) -> dict[str, Any]:
        """Adopt current exact-owner usage receipts, never settle or resend a task.

        Args:
            token: Current operator session authorised for the retained run.
            run_id: Immutable native run whose original task identities are read.

        Returns:
            The persisted producer history, including conservative reservations.

        Raises:
            ValueError: A worker is live or the original owner/identity is absent.
            RuntimeError: Existing durable service custody cannot be validated.
        """
        from .native_financial_v2 import primitive_copy
        from .run_adoption import ModelRunServices
        from .service_task_dispatch import ServiceTaskDispatcher
        from .service_usage import ServiceUsageLedger

        who, _ = self.native._operator(token)
        with self.registry.lock, self.native.db.transaction() as db:
            row = self._get(db, run_id, who.actor_ref)
            owner = self.registry.owners.get(run_id)
            if owner is not None and owner.snapshot()["alive"]:
                raise ValueError("live native model custody cannot be reconciled")
            services = self.app.config.get("MODEL_RUN_SERVICES")
            if type(services) is not ModelRunServices or services.app is not self.app or services.closed:
                raise ValueError("current model service owner unavailable")
            dispatcher = services.dispatcher()
            if (type(dispatcher) is not ServiceTaskDispatcher
                    or self.app.config.get("SERVICE_TASK_DISPATCHER") is not dispatcher
                    or type(dispatcher.ledger) is not ServiceUsageLedger
                    or dispatcher.store.workspace_dir != services.workspace):
                raise ValueError("current model ledger owner unavailable")
            for call in row.get("model_calls", []):
                if "usage_owner" not in call:
                    raise ValueError("original model ledger identity unavailable")
                observed = dispatcher.ledger.task_observation(
                    call["request_id"], who.actor_ref,
                    expected_digest=call["task_digest"], expected_owner=call["usage_owner"],
                )
                call["receipt"] = primitive_copy(observed)
                call["state"] = observed["outcome"]
            self.native._save(db, row)
        return self.producer_status(token, run_id)

    def producer_status(self, token: str, run_id: str) -> dict[str, Any]:
        """Read durable decisions and conservative task reservations; no calls."""
        from .native_financial_v2 import primitive_copy

        who, _ = self.native._operator(token, write=False)
        with self.registry.lock, self.native.db.transaction() as db:
            row = self._get(db, run_id, who.actor_ref)
            return primitive_copy({"decisions": row.get("producer_decisions", []),
                                   "model_calls": row.get("model_calls", []),
                                   "reads": row.get("producer_reads", 0)})

    def record_decision(self, owner: Any, index: int, proposals: int) -> None:
        """Persist the genuine strategy decision before any command is considered."""
        with self.registry.lock, self.native.db.transaction() as db:
            row = self._worker_row(db, owner)
            if len(row["producer_decisions"]) != index or proposals not in {0, 1}:
                raise ValueError("decision identity or count conflicts")
            row["producer_decisions"].append({"index": index, "proposals": proposals})
            self.native._save(db, row)

    def submit_proposal(self, owner: Any, index: int, order: Any) -> dict[str, Any]:
        """Atomically reserve a genuine decision before the existing canonical gate.

        The route retains its actual router preparation. This owner neither
        reconstructs that pin nor releases a possible write on a timeout.
        """
        from fractions import Fraction

        from .models import Order
        from .native_autonomy import NativeDispatchAuthority
        from .native_financial_v2 import _money, has_financial_obligations, primitive_copy, project_financial

        if type(order) is not Order:
            raise ValueError("exact typed strategy proposal required")
        request = {"decision": index, "order": order.model_dump(mode="json")}
        identity = "decision-" + str(index)
        with self.registry.lock, self.native.db.transaction() as db:
            prior = db.execute("SELECT data FROM commands WHERE run_id=? AND command_id=?",
                               (owner.scope.run_id, identity)).fetchone()
            if prior is not None:
                replay = json.loads(prior[0])
                if replay["request_digest"] != _hash(request):
                    raise ValueError("decision identity conflict; never replay")
                return replay
            row = self._worker_row(db, owner)
            plan = self._plan(row)
            if request["order"] != plan["order"]:
                raise ValueError("proposal differs from finite accepted plan")
            limits = row["grant_v2"]["limits"]
            instrument = {"instrument_id": order.symbol, "exchange": str(order.exchange), "product": str(order.product)}
            quantity = int(order.quantity)
            if (str(quantity) != order.quantity or quantity <= 0 or instrument not in limits["instruments"]
                    or quantity > limits["max_order_quantity"] or order.pricetype != "LIMIT"
                    or Fraction(order.price) <= 0 or "place" not in limits["actions"]):
                raise ValueError("proposal outside explicit entry limits")
            commands = [json.loads(raw[0]) for raw in db.execute("SELECT data FROM commands WHERE run_id=?",
                                                               (owner.scope.run_id,))]
            if (len(commands) >= limits["max_commands"]
                    or quantity + sum(c["quantity"] for c in commands) > limits["max_total_quantity"]
                    or any(c["state"] not in {"settled", "refused"} for c in commands)):
                raise ValueError("non-replenishing command allowance exhausted")
            for raw, in db.execute("SELECT data FROM runs WHERE run_id!=?", (owner.scope.run_id,)):
                other = json.loads(raw)
                if other["binding"]["account"] == row["binding"]["account"] and has_financial_obligations(other):
                    raise ValueError("another run retains financial custody")
            entry = plan["entry"]
            if row["schema_version"] == "2":
                if (order.action != "BUY" or order.product != "CNC" or entry["lots"]
                        or entry["remaining_possible_quantity"] != quantity or entry["unknown_possible_write"]
                        or Fraction(entry["remaining_price_upper_bound"]) < Fraction(order.price)):
                    raise ValueError("cash prospective allocation does not cover the proposal")
            else:
                writes = entry["writes"]
                if (entry["fills"] or len(writes) != 1 or writes[0]["purpose"] != "entry"
                        or writes[0]["original_quantity"] != quantity or writes[0]["remaining_quantity"] != quantity
                        or writes[0]["released_quantity"] != 0
                        or writes[0]["side"] != ("buy" if order.action == "BUY" else "sell")
                        or entry["contract"]["exchange"] != order.exchange
                        or entry["contract"]["product"] != order.product
                        or writes[0]["side"] == "buy" and (
                            writes[0]["premium_upper_bound"] is None
                            or Fraction(writes[0]["premium_upper_bound"]) < Fraction(order.price))):
                    raise ValueError("options prospective allocation does not cover the proposal")
            if row["producer_reads"] >= limits["max_reads"]:
                raise ValueError("finite canonical read allowance unavailable")
            snapshot = self._dependencies().lifecycle_store.observation_snapshot(
                BrokerSelector(row["binding"]["broker"], row["binding"]["account_id"]))
            previous_history = primitive_copy(row["financial_v2"]["history"])
            assessment = project_financial(self, row, snapshot, int(time.time() * 1000), prospective=plan)
            if assessment["status"] != "within_bounds" or row["loss_threshold_latched"]:
                raise ValueError("prospective financial assessment refused")
            self._revalidate_primitive_source(row, snapshot)
            reservation_id = entry["entry_ref"]["id"]
            hold = row["financial_v2"]["reservations"][reservation_id]
            hold["command_id"] = identity
            hold["prospective"] = True
            # A proposal is not historical broker observation. Its exact entry
            # remains durable in the reservation until positively represented.
            row["financial_v2"]["history"] = previous_history
            # Preserve the accepted intent; authenticated attribution belongs to
            # the request context, not the operator's signed strategy field.
            body = {**order.model_dump(mode="json", exclude_none=True), "broker": row["binding"]["broker"],
                    "account_id": row["binding"]["account_id"], "rationale": order.admission_note}
            command = {"run_id": owner.scope.run_id, "command_id": identity, "request_digest": _hash(request),
                       "source": "bounded:" + _hash([owner.scope.run_id, identity]), "body": body,
                       "quantity": quantity, "notional": _money(Fraction(order.price) * quantity),
                       "state": "pending_admission", "cause": "bounded_policy_authorised", "broker_order_id": None,
                       "events": ["pending_admission"], "created_at": time.time(),
                           "financial_reservation": reservation_id}
            if row["schema_version"] == "2-options-1":
                command["financial_contract"] = primitive_copy(entry["contract"])
            db.execute("INSERT INTO commands VALUES (?,?,?)", (owner.scope.run_id, identity, _json(command)))
            self.native._save(db, row)
            ticket = NativeDispatchAuthority(self.native, row, command)
            self.native._tickets[command["source"]] = ticket
        from flinttrade_gateway.read_frontier import read_invocation_guard

        def bound_read() -> None:
            # The adapter invokes this after executor/transport-lock waits.
            # It narrows existing read admission; it cannot mint any capability.
            with self.registry.lock, self.native.db.transaction() as db:
                current = self._worker_row(db, owner)
                if current["producer_reads"] >= current["grant_v2"]["limits"]["max_reads"]:
                    raise ValueError("finite canonical read allowance exhausted")
                current["producer_reads"] += 1
                self.native._save(db, current)

        with read_invocation_guard(bound_read):
            result = self.native._execute(row, command, ticket)
        if result["state"] == "refused":
            with self.registry.lock, self.native.db.transaction() as db:
                current = self._get(db, owner.scope.run_id, owner.scope.actor)
                persisted = json.loads(db.execute("SELECT data FROM commands WHERE run_id=? AND command_id=?",
                                                 (owner.scope.run_id, identity)).fetchone()[0])
                if persisted["state"] == "refused" and not persisted.get("filled_quantity", 0):
                    current["financial_v2"]["reservations"][reservation_id]["state"] = "released"
                    project_financial(self, current, snapshot, int(time.time() * 1000))
                    self.native._save(db, current)
        return result

    def producer_finished(self, owner: Any) -> None:
        """Retire future writes without claiming fills, settlement or flatness."""
        with self.registry.lock:
            if self.registry.owners.get(owner.scope.run_id) is not owner:
                raise ValueError("producer custody replaced")
            self.native.retire(owner.scope)
            with self.native.db.transaction() as db:
                row = self._get(db, owner.scope.run_id, owner.scope.actor)
                row["producer_state"] = "failed" if owner.failed else "stopped"
                self.native._save(db, row)
            self.registry.observe(owner.scope, "failed" if owner.failed else "completed")

    def _revalidate_primitive_source(self, row: dict[str, Any], snapshot: Any) -> None:
        expected = row.get("_evaluated_primitive_digest")
        if expected is not None and (self._primitive_source is None
                or self._primitive_source.generations.get(row["binding"]["run_id"])
                != row.get("_evaluated_primitive_generation")
                or _hash(self._primitive_source.resolve(row, snapshot)) != expected):
            raise ValueError("primitive source changed during evaluation")

    def _dependencies(self) -> Any:
        from flinttrade_gateway.broker_read_service import BrokerReadOwner
        from flinttrade_gateway.registry import RegistryPublicationOwner

        from .app import _BrokerRuntimeDependencies

        dependencies = self.app.extensions.get("flinttrade_broker_dependencies")
        if (
            self.app.config.get("EXECUTION_SESSIONS") is not self.registry
            or type(dependencies) is not _BrokerRuntimeDependencies
            or type(dependencies.read_owner) is not BrokerReadOwner
            or self.app.extensions.get("flinttrade_broker_dependencies_draining") is not None
            or self.app.config.get("REGISTRY") is not dependencies.registry
            or self.app.config.get("ACTIVE_BROKER_ADAPTERS") is not dependencies.adapters
            or self.app.config.get("ORDER_LIFECYCLE_LEDGER") is not dependencies.lifecycle_store
            or type(dependencies.registry_publication_owner) is not RegistryPublicationOwner
            or self.app.extensions.get("flinttrade.registry_publication_owner")
            is not dependencies.registry_publication_owner
            or not dependencies.registry_publication_owner.owns(dependencies.registry)
        ):
            raise ValueError("current canonical account owner required")
        return dependencies

    def _account_pin(self, claims: dict[str, Any], config: Any) -> dict[str, Any]:
        """Resolve both human and bounded ACLs locally, without a read grant."""
        from flinttrade_engine.request_context import RequestContext

        from .account_mutation_contracts import RegistrySessionUnavailable
        from .exceptions import SafetyBypassError
        from .workspace_migrations import broker_workspace_version, read_workspace_snapshot

        dependencies = self._dependencies()
        selector = BrokerSelector(config.broker, config.account_id)
        selected = serialise_broker_selector(selector)
        self.registry.require_native_admission()
        snapshot = read_workspace_snapshot(dependencies.workspace_path)
        if snapshot.version != dependencies.workspace_snapshot.version:
            raise ValueError("workspace binding changed")
        if broker_workspace_version(snapshot) != dependencies.session_provider.broker_workspace_version:
            raise ValueError("broker workspace binding changed")
        human = RequestContext(claims["jti"], "human", claims["sub"], claims["mode"], selector=selected)
        agent = RequestContext(claims["jti"], "agent", "bounded:" + config.run_id, "live", selector=selected)
        try:
            handle = dependencies.session_provider(human, config.broker, config.account_id)
            bounded = dependencies.session_provider(agent, config.broker, config.account_id)
        except (SafetyBypassError, RegistrySessionUnavailable) as exc:
            raise ValueError("canonical account scope unavailable") from exc
        if bounded.version != handle.version:
            raise ValueError("account changed during binding")
        version = handle.version
        return {
            "broker": config.broker,
            "account_id": config.account_id,
            "registry_incarnation": str(version.registry_version.registry_incarnation),
            "registry_generation": version.registry_version.generation,
            "vault_incarnation": str(version.credential_version.vault_incarnation),
            "credential_generation": version.credential_version.generation,
            "workspace_instance_id": str(version.workspace_version.instance_id),
            "workspace_generation": version.workspace_version.generation,
            "broker_workspace_generation": version.broker_workspace_version.generation,
            "requested_role": None,
        }

    def recovery_account_pin(self, row: dict[str, Any]) -> dict[str, Any]:
        """Validate a published read-only correspondence without rebinding write authority."""
        from .account_lifecycle_contracts import ReadOnlyRecoveryOutcome

        receipt = row.get("read_only_recovery")
        if type(receipt) is not dict or receipt["historical_binding"] != _hash(row["account_pin"]):
            raise ValueError("read-only recovery correspondence unavailable")
        dependencies = self._dependencies()
        selector = BrokerSelector(row["binding"]["broker"], row["binding"]["account_id"])
        handle = dependencies.registry.get_connected_session_for(
            selector, current_authority=dependencies.session_provider.current_authority_for(selector))
        outcome = handle.read_only_recovery
        version = handle.version
        pin = {**row["account_pin"],
               "registry_incarnation": str(version.registry_version.registry_incarnation),
               "registry_generation": version.registry_version.generation,
               "vault_incarnation": str(version.credential_version.vault_incarnation),
               "credential_generation": version.credential_version.generation,
               "workspace_instance_id": str(version.workspace_version.instance_id),
               "workspace_generation": version.workspace_version.generation,
               "broker_workspace_generation": version.broker_workspace_version.generation}
        if (type(outcome) is not ReadOnlyRecoveryOutcome or not handle.is_read_only
                or outcome.census_revision != receipt["census"] or row["binding"]["run_id"] not in outcome.run_ids
                or handle.verified_native_account != row["native_identity"]["account_id"]
                or receipt["native_identity"] != row["native_identity"] or pin != receipt["account_pin"]):
            raise ValueError("read-only recovery correspondence changed")
        return pin

    def _observation_account_pin(self, row: dict[str, Any], claims: dict[str, Any], config: Any) -> dict[str, Any]:
        """Keep authenticated read correspondence separate from historical grant pins."""
        current = self._account_pin(claims, config)
        expected = self.recovery_account_pin(row) if row.get("read_only_recovery") is not None else row["account_pin"]
        if current != expected:
            raise ValueError("observation account binding changed")
        return current

    @staticmethod
    def _config(body: dict[str, Any]) -> ConfigureRequestV2 | OptionsConfigureRequestV2:
        if type(body) is not dict:
            raise ValueError("exact versioned configuration required")
        if body.get("schema_version") == "2":
            return ConfigureRequestV2.model_validate(body)
        if body.get("schema_version") == "2-options-1":
            return OptionsConfigureRequestV2.model_validate(body)
        raise ValueError("unsupported native configuration version")

    def configure(self, token: str, body: dict[str, Any]) -> dict[str, Any]:
        """Persist immutable configuration without qualification or execution.

        Args:
            token: Actual authenticated operator session, never a producer token.
            body: Exact cash or options ConfigureRequestV2 JSON selection.

        Returns:
            The corresponding nominal RunViewV2, initially ungranted.

        Raises:
            ValueError: The schema, operator, environment or canonical binding
                is unavailable, contradictory or already reserved.
        """
        request = self._config(body)
        who, claims = self.native._operator(token)
        config = request.config
        # The incumbent broker runtime is production-only. A caller cannot turn
        # real sessions into a synthetic/demo transport by selecting a label.
        if config.environment != "production":
            if config.environment != "synthetic" or self._primitive_source is None:
                raise ValueError("trusted broker environment does not match request")
            self._primitive_source.require_current()
        pin = self._account_pin(claims, config)
        dependencies = self._dependencies()
        selector = BrokerSelector(config.broker, config.account_id)
        handle = dependencies.registry.get_connected_session_for(
            selector, current_authority=dependencies.session_provider.current_authority_for(selector))
        native_identity = None if handle.verified_native_account is None else {
            "broker": config.broker, "account_id": handle.verified_native_account,
            "workspace_instance_id": pin["workspace_instance_id"],
        }
        config_json = config.model_dump(mode="json")
        revision = _hash({"config": config_json, "operator": who.actor_ref, "account": pin})
        scope = RunScopeV2(
            run_id=config.run_id, operator=who.actor_ref, actor="bounded:" + config.run_id,
            broker=config.broker, account_id=config.account_id, environment=config.environment,
            registry_generation=pin["registry_generation"], binding_revision=revision,
        )
        binding = {
            "run_id": config.run_id, "actor": scope.actor, "broker": config.broker,
            "account_id": config.account_id, "account": serialise_broker_selector(BrokerSelector(
                config.broker, config.account_id)), "environment": "live",
        }
        row = {
            "schema_version": request.schema_version, "binding": binding, "operator": who.actor_ref,
            "revision": revision, "scope_v2": scope.model_dump(mode="json"), "config_v2": config_json,
            "account_pin": pin, "native_identity": native_identity,
            "configured_at_ms": int(time.time() * 1000), "state": "configured",
            "qualification": None, "grant": None, "report_v2": None, "entry_state": "ungranted",
            "producer_state": "not_started", "duty_v2": None, "loss_threshold_latched": False, "events_v2": [],
        }
        with self.registry.lock:
            if self._account_pin(claims, config) != pin:
                raise ValueError("account changed before configuration")
            self.registry.create(ExecutionSession(config.run_id, who.actor_ref, binding["account"], "live"),
                                 kind="strategy", config=config_json)
            with self.native.db.transaction() as db:
                db.execute("INSERT INTO runs VALUES (?,?)", (config.run_id, _json(row)))
        return self.view(row)

    def _get(self, db: Any, run_id: str, actor: str) -> dict[str, Any]:
        row = self.native._get(db, run_id, actor)
        if row.get("schema_version") not in {"2", "2-options-1"}:
            raise ValueError("versioned run required")
        request = self._config({"schema_version": row["schema_version"], "config": row["config_v2"]})
        scope = RunScopeV2.model_validate(row["scope_v2"])
        if scope.binding_revision != row["revision"] or scope.run_id != request.config.run_id:
            raise ValueError("persisted native binding conflicts")
        return row

    def status(self, token: str, run_id: str) -> dict[str, Any]:
        """Read an exact versioned run without provider I/O or new authority.

        Args:
            token: Current operator session with read scopes.
            run_id: Exact existing run identity, not a selected UI account.

        Returns:
            A validated nominal cash/options view of retained custody.

        Raises:
            ValueError: The operator, version, identity or custody is invalid.
        """
        who, claims = self.native._operator(token, write=False)
        with self.registry.lock, self.native.db.transaction() as db:
            row = self._get(db, run_id, who.actor_ref)
        return self.view(row, claims=claims)

    def inspect(self, token: str, run_id: str, body: dict[str, Any]) -> dict[str, Any]:
        """Collect an explicitly authorised bounded canonical observation.

        Args:
            token: Current operator session with account/service write scopes.
            run_id: Exact configured run, unchanged by UI selection.
            body: InspectRequestV2 selecting its binding and finite read plan.

        Returns:
            The nominal view with a persisted, independently evaluated report.
            Daily trade availability is not lifetime completeness or eligibility.

        Raises:
            ValueError: The selection, supported read scope, deadline, budget or
                binding is invalid or changes while the read is outstanding.
        """
        from flinttrade_core.broker_read_port import BrokerReadFailure, ExactReadTarget
        from flinttrade_engine.request_context import RequestContext

        from .order_routes import _run_on_client_loop

        request = InspectRequestV2.model_validate(body)
        who, claims = self.native._operator(token)
        with self.registry.lock:
            with self.native.db.transaction() as db:
                row = self._get(db, run_id, who.actor_ref)
            if request.run_id != run_id or request.expected_binding_revision != row["revision"]:
                raise ValueError("inspection binding changed")
            config = self._config({"schema_version": row["schema_version"], "config": row["config_v2"]}).config
            revision = self.native._observation_revision(row)
        # The existing canonical owner owns the complete finite plan. Missing
        # quote/window selections remain explicit unavailable surfaces; this
        # caller must never guess them or introduce another read budget.
        plan = request.read_plan
        remaining = (plan.deadline_ms - time.time() * 1000) / 1000
        if not 0 < remaining <= 60:
            raise ValueError("supported bounded canonical read plan required")
        observation_pin = self._observation_account_pin(row, claims, config)
        dependencies = self._dependencies()
        read_owner = dependencies.read_owner
        selector = BrokerSelector(config.broker, config.account_id)

        def authority() -> Any:
            """Fence each read frontier against the original session, deadline and observation pin."""
            current, fresh_claims = self.native._operator(token)
            if (current.actor_ref != who.actor_ref or current.session_binding != who.session_binding
                    or int(time.time() * 1000) >= plan.deadline_ms
                    or self._dependencies() is not dependencies
                    or self._observation_account_pin(row, fresh_claims, config) != observation_pin):
                raise ValueError("inspection authority changed")
            return RequestContext(claims["jti"], "human", claims["sub"], claims["mode"],
                                  selector=serialise_broker_selector(selector))

        port = read_owner.bind(target=ExactReadTarget(selector), verify_current_authority=authority)
        if type(port) is BrokerReadFailure:
            raise ValueError("bounded canonical read permission unavailable")
        try:
            async def capture() -> Any:
                seconds = (plan.deadline_ms - time.time() * 1000) / 1000
                if seconds <= 0:
                    raise ValueError("inspection deadline expired")
                await dependencies.lifecycle_store.refresh_observations(
                    read_owner, port, read_plan=plan, timeout_seconds=min(seconds, 60),
                )
                return dependencies.lifecycle_store.observation_snapshot(
                    selector, read_owner=read_owner, port=port,
                    max_age_seconds=config.risk.max_mark_age_ms / 1000,
                )

            # Never wait on the shared client loop while holding the registry.
            with self.app.app_context():
                snapshot = _run_on_client_loop(capture())
            authority()
            report, detail = self._evaluate(row, snapshot)
            with self.registry.lock:
                self.native._revalidate_observation(row, revision)
                authority()
                if dependencies.lifecycle_store.observation_snapshot(
                        selector, read_owner=read_owner, port=port,
                        max_age_seconds=config.risk.max_mark_age_ms / 1000) != snapshot:
                    raise ValueError("inspection evidence changed during evaluation")
                self._revalidate_primitive_source(row, snapshot)
                with self.native.db.transaction() as db:
                    current = self._get(db, run_id, who.actor_ref)
                    current.update({key: row[key] for key in ("financial_v2", "loss_threshold_latched",
                                                               "events_v2", "entry_state", "grant",
                                                                   "_evaluated_primitive_digest",
                                                                   "_evaluated_primitive_generation") if key in row})
                    self._reconcile_commands(db, current, row["_command_observations"])
                    current["report_v2"], current["inspection_detail"] = report, detail
                    current["observation_generation"] = snapshot.generation
                    current["observation_digest"] = _hash(snapshot.evidence_json)
                    current["observed_at_ms"] = report["generated_at_ms"]
                    self.native._save(db, current)
            return self.status(token, run_id)
        finally:
            read_owner.revoke(port)

    def qualify(self, token: str, run_id: str) -> dict[str, Any]:
        """Evaluate current local owner records; accept no caller attestation.

        Args:
            token: Authenticated operator with mutation scopes.
            run_id: Exact configured run to evaluate, never retargeted.

        Returns:
            A nominal view with independently evaluated dimensions. Missing
            provider, account, history or tariff evidence remains blocked.

        Raises:
            ValueError: Account/authority/source revisions change during the
                local evaluation, or the exact configured run is unavailable.
        """
        who, claims = self.native._operator(token)
        with self.registry.lock:
            with self.native.db.transaction() as db:
                row = self._get(db, run_id, who.actor_ref)
            revision = self.native._observation_revision(row)
        config = self._config({"schema_version": row["schema_version"], "config": row["config_v2"]}).config
        observation_pin = self._observation_account_pin(row, claims, config)
        dependencies = self._dependencies()
        selector = BrokerSelector(config.broker, config.account_id)
        snapshot = dependencies.lifecycle_store.observation_snapshot(selector)
        report, detail = self._evaluate(row, snapshot)
        with self.registry.lock:
            self.native._revalidate_observation(row, revision)
            self._revalidate_primitive_source(row, snapshot)
            if (self._dependencies() is not dependencies
                    or self._observation_account_pin(row, claims, config) != observation_pin
                    or dependencies.lifecycle_store.observation_snapshot(selector) != snapshot):
                raise ValueError("qualification evidence changed")
            with self.native.db.transaction() as db:
                current = self._get(db, run_id, who.actor_ref)
                current.update({key: row[key] for key in ("financial_v2", "loss_threshold_latched",
                                                           "events_v2", "entry_state", "grant",
                                                               "_evaluated_primitive_digest",
                                                               "_evaluated_primitive_generation") if key in row})
                self._reconcile_commands(db, current, row["_command_observations"])
                current["report_v2"], current["inspection_detail"] = report, detail
                self.native._save(db, current)
        return self.status(token, run_id)

    def _command_observations(self, row: dict[str, Any], snapshot: Any) -> dict[str, Any]:
        """Read exact sealed command evidence without adding authority or I/O."""
        from .models import Order

        with self.native.db.transaction() as db:
            commands = [json.loads(value[0]) for value in db.execute(
                "SELECT data FROM commands WHERE run_id=?", (row["binding"]["run_id"],))]
        observations = {}
        for command in commands:
            if command["state"] == "refused" or command["source"] in self.native._tickets:
                continue
            try:
                if self.native._completion_conflict(command):
                    raise ValueError("conflicting command completion")
                evidence = self._dependencies().lifecycle_store.native_command_observation(
                    snapshot.selector, actor=row["binding"]["actor"], intent_source=command["source"],
                    intent=Order.model_validate(command["body"]).model_dump(mode="json"),
                    generation=snapshot.generation, evidence_digest=_hash(json.loads(snapshot.evidence_json)),
                    max_age_seconds=row["config_v2"]["risk"]["max_mark_age_ms"] / 1000,
                )
                if (command.get("broker_order_id") not in evidence["order_ids"]
                        or command.get("filled_quantity", 0) > evidence["filled_quantity"]):
                    raise ValueError("retained command identity or quantity conflicting")
                observations[command["command_id"]] = evidence
            except (ValueError, TypeError, KeyError, ArithmeticError):
                # Invalid/missing evidence cannot erase a hold or old high-water.
                observations[command["command_id"]] = None
                prior = command.get("settlement_v2", {}).get("observation")
                if prior is not None:
                    # The canonical owner already attributed these monotonic
                    # facts to the original invocation and exact native scope.
                    # Unavailable, unrelated and foreign-date captures cannot
                    # manufacture an increased high-water for this resource.
                    from fractions import Fraction

                    from flinttrade_gateway.native_scope_primitives import scope_key

                    scopes = {(row["binding"]["broker"], *scope_key(resource))
                              for resource in prior["resources"]}
                    constraints = [item for item in snapshot.order_fills
                                   if item.owner_attempt_id == prior["attempt_id"]
                                   and item.native_order_scope in scopes]
                    high_water = sum((Fraction(item.cumulative_high_water)
                                      for item in constraints), Fraction(0))
                    if high_water.denominator == 1 and high_water > command.get("filled_quantity", 0):
                        observations[command["command_id"]] = {
                            "filled_quantity": int(high_water), "zero_fill_terminal": False,
                            "conflicting": True, "attempt_id": prior["attempt_id"],
                            "generation": snapshot.generation, "evidence_digest": _hash(snapshot.evidence_json),
                            "scope_high_waters": [{"scope": list(item.native_order_scope),
                                                   "quantity": item.cumulative_high_water}
                                                  for item in constraints],
                        }
        return observations

    def _reconcile_commands(self, db: Any, row: dict[str, Any], observations: dict[str, Any]) -> None:
        """Commit evidenced command progress with the existing financial transaction.

        Only complete zero-fill terminal evidence can settle an unfilled command.
        Filled execution, fees and model duties retain their independent owners;
        ACK, Stop and custody transfer never release them.
        """
        from .native_financial_v2 import has_financial_obligations

        for identity, evidence in observations.items():
            command = json.loads(db.execute("SELECT data FROM commands WHERE run_id=? AND command_id=?",
                                (row["binding"]["run_id"], identity)).fetchone()[0])
            if command["state"] == "refused":
                continue
            was_settled = command["state"] == "settled"
            if was_settled and (evidence is None or evidence["zero_fill_terminal"]):
                # Mere unavailability or an identical terminal observation is
                # not new liability and must not rewrite a legitimate settlement.
                continue
            if was_settled:
                command["settlement_v2"].setdefault("cause", command["cause"])
                command["settlement_v2"].setdefault("settled_at", command["updated_at"])
            retained_conflict = command.get("late_evidence_v2", {}).get("conflicting", False)
            state, cause = "reconciling", "bounded_evidence_missing_or_conflicting"
            if evidence is not None and not self.native._completion_conflict(command):
                filled = evidence["filled_quantity"]
                command["filled_quantity"] = max(command.get("filled_quantity", 0), filled)
                state = "filled" if filled == command["quantity"] else "partial" if filled else "working"
                cause = "bounded_broker_observation_not_settlement"
                if was_settled or command.get("late_evidence_v2") is not None:
                    # Replaying an earlier benign observation is not a
                    # resolution of an already witnessed exact-resource conflict.
                    if not retained_conflict or evidence.get("conflicting"):
                        command["late_evidence_v2"] = evidence
                    cause = "bounded_late_evidence_after_settlement"
                if retained_conflict or evidence.get("conflicting"):
                    state, cause = "reconciling", "bounded_late_fill_conflicting_after_settlement"
                finance = row["financial_v2"]
                hold = finance["reservations"].get(command["financial_reservation"])
                if (not retained_conflict and evidence["zero_fill_terminal"] and command["filled_quantity"] == 0
                        and hold is not None and hold["state"] == "released"
                        and finance["assessment"]["status"] != "unavailable"
                        and not has_financial_obligations(row)):
                    state, cause = "settled", "bounded_terminal_zero_fill_financially_settled"
                    command["settlement_v2"] = {"observation": evidence, "financial_source": finance["source_ref"],
                                                "financial_revision": finance["revision"]}
            if self.native._completion_conflict(command):
                state, cause = "reconciling", command["cause"]
            command.update(state=state, cause=cause, updated_at=time.time())
            command["events"].append(state)
            db.execute("UPDATE commands SET data=? WHERE run_id=? AND command_id=?",
                       (_json(command), command["run_id"], identity))

    def _evaluate(self, row: dict[str, Any], snapshot: Any) -> tuple[dict[str, Any], dict[str, Any]]:
        """Evaluate current sealed primitives and command evidence without acquiring write authority."""
        from .broker_sdk_attest import STATUS_OK, attest_all

        now = int(time.time() * 1000)
        config = row["config_v2"]
        profile = config["operation_profile_ref"]
        verifier = {"id": "native-v2-mounted-verifier", "revision": _hash({"version": 1, "module": __name__})}
        expiry = now + config["risk"]["max_mark_age_ms"]
        pins = {"dhan": "dhanhq", "kotakneo": "kotakneoapi", "upstox": "upstox-python-sdk", "groww": "growwapi"}
        attestations = [item.to_dict() for item in attest_all() if item.broker == pins.get(config["broker"])]
        software_ok = len(attestations) == 1 and attestations[0]["status"] == STATUS_OK
        detail = {
            "sdk": attestations, "canonical_generation": snapshot.generation,
            "canonical_digest": _hash(snapshot.evidence_json), "missing_evidence": list(snapshot.missing_evidence),
            "conflicts": list(snapshot.conflicts), "unallocated_count": len(snapshot.unallocated_trades),
            "unexplained_fill_orders": [item.orderid for item in snapshot.order_fills
                                        if item.unexplained_quantity != "0"],
            "standalone_margin": "unqualified_provider_order_estimates_only",
            "provider_acceptance": "no_demonstrated_versioned_action",
            "account_eligibility": "acl_verified_product_eligibility_not_verified",
            "fee_tariff": "effective_dated_allocation_producer_unavailable",
        }

        def fact(status: str, provenance: str, operation: str, payload: Any = None) -> dict[str, Any]:
            return {
                "status": status, "provenance": provenance, "verifier_ref": verifier, "profile_ref": profile,
                "evidence_ref": None if payload is None else {"id": operation, "revision": _hash(payload)},
                "observed_at_ms": now if payload is not None else None,
                "expires_at_ms": expiry if payload is not None else None,
                "operation": operation, "coverage": ["trades"],
            }

        observations = "conflicting" if snapshot.conflicts else "missing"
        # Source/read availability is retained even though the missing lifetime,
        # payment and allocation producer dimensions prevent entry qualification.
        facts = {
            "software": fact(
                "verified" if software_ok else "missing", "installed_runtime", "installed_sdk", attestations,
            ),
            "account_eligibility": fact("missing", "broker_read", "product_eligibility", row["account_pin"]),
            "observations": fact(observations, "broker_read", "lifetime_census", detail),
            "demonstrated_action": fact("missing", "demonstrated_broker_action", "provider_acceptance"),
            "custody": fact("missing", "operator_policy", "pre_entry_custody"),
            "fees": fact("missing", "documented_contract", "effective_dated_tariff"),
            "producer": fact("missing", "reviewed_software", "registered_producer"),
        }
        from .native_financial_v2 import project_financial

        row["_command_observations"] = self._command_observations(row, snapshot)
        assessment = project_financial(self, row, snapshot, now)
        detail["financial"] = assessment
        reasons = ["evidence_missing", "fees_unknown", "custody_required", "producer_unavailable"]
        if assessment["status"] != "unavailable":
            for key, operation in (("observations", "primitive_lifetime"), ("fees", "primitive_tariff")):
                facts[key] = fact("verified", "synthetic", operation, row["financial_v2"]["source_ref"])
            reasons = ["evidence_missing", "custody_required", "producer_unavailable"]
            if assessment["status"] != "within_bounds":
                reasons.append("reconciliation_required")
            if row["loss_threshold_latched"]:
                reasons.append("loss_threshold_latched")
        if config["environment"] == "synthetic" and assessment["status"] == "within_bounds":
            try:
                registered = self._producer(row)
                self._primitive_source.require_current()
                if registered.model_binding is not None:
                    from httpx import MockTransport

                    if type(self._model_source(registered).transport) is not MockTransport:
                        raise ValueError("synthetic issuer has no bound inert model evidence")
                facts["producer"] = fact("verified", "reviewed_software", "registered_strategy", registered.pin)
                facts["account_eligibility"] = fact("verified", "synthetic", "bound_inert_account", row["account_pin"])
                # This explicit server source is engineering-only. Production
                # provider acceptance is not asserted or waived by a DTO label.
                facts["demonstrated_action"] = fact(
                    "not_required", "documented_contract", "synthetic_no_provider_qualification")
                facts["custody"] = fact("verified", "operator_policy", "finite_acceptance_required_at_grant",
                                        config["custody"])
                reasons = [] if software_ok and not row["loss_threshold_latched"] else ["evidence_missing"]
            except ValueError:
                pass
        if row.get("read_only_recovery") is not None:
            reasons.append("reconciliation_required")
            detail["read_only_recovery"] = "read_correspondence_not_write_qualification"
        if snapshot.conflicts:
            reasons.append("evidence_conflicting")
        content = {
            "schema_version": "2", "scope": row["scope_v2"], "profile_ref": profile,
            "policy_ref": config["risk"]["policy_ref"], "generated_at_ms": now, "expires_at_ms": expiry,
            "status": "blocked" if reasons else "eligible", "dimensions": facts,
            "blocking_reasons": reasons, "next_actions": ["review_evidence", "accept_transfer"],
        }
        content["report_ref"] = {"id": "qualification:" + row["binding"]["run_id"], "revision": _hash(content)}
        return QualificationReportV2.model_validate(content).model_dump(mode="json"), detail

    def _freshness(self, row: dict[str, Any], claims: dict[str, Any] | None) -> str:
        from datetime import datetime

        if "observation_generation" not in row:
            return "missing"
        if claims is None:
            return "stale"
        try:
            config = self._config({"schema_version": row["schema_version"], "config": row["config_v2"]}).config
            if self._account_pin(claims, config) != row["account_pin"]:
                return "stale"
            snapshot = self._dependencies().lifecycle_store.observation_snapshot(
                BrokerSelector(config.broker, config.account_id),
            )
            if snapshot.conflicts:
                return "conflicting"
            if (snapshot.generation != row["observation_generation"]
                    or _hash(snapshot.evidence_json) != row["observation_digest"]):
                return "stale"
            started = datetime.fromisoformat(json.loads(snapshot.evidence_json)["started_at"]).timestamp()
            age = time.time() * 1000 - started * 1000
            return "fresh" if 0 <= age <= config.risk.max_mark_age_ms else "stale"
        except Exception:
            # Inspection cannot assert freshness after authority or evidence
            # becomes unavailable, and cannot repair it by acquiring/fetching.
            return "stale"

    def view(self, row: dict[str, Any], *, claims: dict[str, Any] | None = None) -> dict[str, Any]:
        """Project custody, applying observed kill retirement without provider I/O.

        Args:
            row: Existing durable run row obtained under the native owner lock.
            claims: Already authenticated claims for local current-account
                validation. Absence never establishes observation freshness.

        Returns:
            A nominal cash/options view; configuration supplies no authority.
        """
        model = RunViewV2 if row["schema_version"] == "2" else OptionsRunViewV2
        from .native_custody_v2 import duty_projection

        killed = self.app.config["SAFETY"].l5_kill.is_active
        if type(killed) is not bool:
            raise ValueError("current global kill observation unavailable")
        with self.registry.lock:
            if killed:
                # Use the existing retirement owner: request Stop but retain a
                # held thread and every duty. Never translate kill to stopped.
                scope = self.registry.scope(row["binding"]["run_id"], row["operator"])
                self.native.retire(scope)
            with self.native.db.transaction() as db:
                row = self._get(db, row["binding"]["run_id"], row["operator"])
                commands = [json.loads(item[0]) for item in db.execute(
                    "SELECT data FROM commands WHERE run_id=? ORDER BY command_id", (row["binding"]["run_id"],))]
        duty = duty_projection(row, commands)
        from .native_financial_v2 import primitive_copy

        grant = primitive_copy(row.get("grant_v2"))
        if grant is not None:
            if row["grant"]["revoked"] or killed:
                grant["state"] = "revoked"
            elif int(time.time() * 1000) >= grant["expires_at_ms"]:
                grant["state"] = "expired"
        return model.model_validate({
            "schema_version": row["schema_version"], "scope": row["scope_v2"], "config": row["config_v2"],
            "requested_authority": "bounded_entry" if grant is not None else "none", "effective_authority": "none",
            "entry_state": "retired" if killed else row["entry_state"],
            "producer_state": row["producer_state"],
            "duty_state": ("none" if duty is None else
                           "retained" if duty["custody"] == "run_retained" else duty["custody"]),
            "observation_freshness": self._freshness(row, claims),
            "report": row["report_v2"], "grant": grant, "duty": duty, "global_kill": killed,
            "transfer_receipts": primitive_copy(row.get("transfers_v2", [])),
            "loss_threshold_latched": row["loss_threshold_latched"], "events": row["events_v2"],
            "next_actions": ["inspect"],
        }).model_dump(mode="json")
