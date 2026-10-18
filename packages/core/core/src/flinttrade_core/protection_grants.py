"""Durable, separately authorised protection over canonical execution evidence.

This owner stores permission and admission receipts, never positions or fills.
Only the qualified unhedged cash sandbox is executable. Native/netted/hedged
protection remains unavailable, irrespective of UI mode or broker credentials.
"""
from __future__ import annotations

import hashlib
import json
import math
import time
from collections import Counter
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any
from uuid import uuid4

from flask import current_app, has_request_context, request

from .execution_session import ExecutionSession
from .practice_agent_adapter import PracticeAgentError
from .run_adoption_store import ModelEvidenceDatabase

_PRINCIPAL = "flinttrade.protection_principal"
_SCHEMA = """
CREATE TABLE grants(run_id TEXT PRIMARY KEY, revision INTEGER NOT NULL, value TEXT NOT NULL);
CREATE TABLE attempts(id TEXT PRIMARY KEY, run_id TEXT NOT NULL, revision INTEGER NOT NULL,
 body TEXT NOT NULL, state TEXT NOT NULL, order_id TEXT);
"""


def _encoded(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False)


def _digest(value: Any) -> str:
    return hashlib.sha256(_encoded(value).encode()).hexdigest()


def _positive(value: Any) -> bool:
    return type(value) in {int, float} and math.isfinite(value) and value > 0


@dataclass(frozen=True, eq=False)
class _ProtectionPrincipal:
    owner: Any
    scope: ExecutionSession
    revision: int
    nonce: str
    body_digest: str
    context: Any


class ProtectionServices:
    """App-owned grants with fail-closed custody and exact run attachment."""

    def __init__(self, app: Any, workspace: Path) -> None:
        self.app, self.workspace = app, Path(workspace)
        self._database: ModelEvidenceDatabase | None = None
        self._owners: dict[str, tuple[ExecutionSession, Any, Any]] = {}
        self._books: dict[str, Any] = {}
        self._custody: dict[str, str] = {}
        self._principals: dict[str, _ProtectionPrincipal] = {}
        self._read_receipts: dict[str, tuple[Any, ...]] = {}
        self._reconciled: set[str] = set()
        self._closed = False
        self._released: dict[str, tuple[Any, ...]] = {}
        self._had_registry = any((self.workspace / name).exists() for name in
            ("protection.sqlite", "protection.registry", "protection.sqlite.authority.json"))

    def _db(self, *, create: bool = False) -> ModelEvidenceDatabase:
        if self._closed:
            raise PracticeAgentError("protection_owner_closed")
        if self._database is None:
            from .secure_file import HeldOwnerDirectory

            path = self.workspace / "protection.sqlite"
            marker = self.workspace / "protection.registry"
            if marker.exists() != path.exists() or not path.exists() and not create:
                raise PracticeAgentError("protection_custody_unavailable")
            database = ModelEvidenceDatabase(path, _SCHEMA)
            with HeldOwnerDirectory(self.workspace) as directory:
                identity = _digest(database.anchor)
                if directory.exists(marker.name):
                    if directory.read_text(marker.name) != identity:
                        raise PracticeAgentError("protection_custody_unavailable")
                elif create:
                    directory.write_text(marker.name, identity)
                else:
                    raise PracticeAgentError("protection_custody_unavailable")
            self._database = database
        return self._database

    def attach(self, scope: ExecutionSession, store: Any, adapter: Any) -> None:
        """Attach existing immutable execution ownership; never infer permission."""
        from flinttrade_ai.run_store import AgentRunStore

        if type(scope) is not ExecutionSession or not isinstance(store, AgentRunStore):
            raise PracticeAgentError("protection_scope_invalid")
        binding = adapter._execution_binding
        if (scope.environment != "paper" or binding is None and scope.account != "paper:sandbox"
                or binding is not None and binding.scope != scope):
            raise PracticeAgentError("protection_scope_unqualified")
        row = store.get_run(scope.run_id)
        if row is None or row["config"].get("owner") != scope.actor or row["mode"] != "practice":
            raise PracticeAgentError("protection_owner_unproved")
        from .execution_session import execution_custody, run_drained
        custody = execution_custody(scope, store, adapter._sandbox())
        old = self._owners.get(scope.run_id)
        if old is not None and old != (scope, store, adapter):
            supervisor = getattr(old[2], "_protection_supervisor", None)
            if (old[0] != scope or supervisor is None or not run_drained(supervisor.run)
                    or self._custody.get(scope.run_id) != custody):
                raise PracticeAgentError("protection_owner_conflict")
        adapter.bind_protection(self, scope)
        self._released.pop(scope.run_id, None)
        self._custody[scope.run_id] = custody
        self._owners[scope.run_id] = (scope, store, adapter)
        self._books[scope.run_id] = adapter._sandbox()

    def _attachment(self, scope: ExecutionSession) -> tuple[Any, Any]:
        from .backend_instance import require_backend_lease_proof

        require_backend_lease_proof(self.app.config.get("BACKEND_LEASE_PROOF"))
        if self.app.config.get("PROTECTION_SERVICES") is not self or self._closed:
            raise PracticeAgentError("protection_owner_unavailable")
        attached = self._owners.get(scope.run_id)
        if attached is None or attached[0] != scope:
            raise PracticeAgentError("protection_owner_unproved")
        store, adapter = attached[1:]
        row = store.get_run(scope.run_id)
        if row is None or row["config"].get("owner") != scope.actor or row["mode"] != "practice":
            raise PracticeAgentError("protection_owner_unproved")
        if (row["config"].get("execution_session", asdict(scope)) != asdict(scope)
                or adapter._sandbox() is not self._books[scope.run_id]):
            raise PracticeAgentError("protection_owner_unproved")
        return store, adapter

    def _sandbox(self, scope: ExecutionSession) -> Any:
        self._attachment(scope)
        return self._books[scope.run_id]

    @contextmanager
    def _fence(self, scope: ExecutionSession) -> Iterator[None]:
        store, adapter = self._attachment(scope)
        binding = adapter._execution_binding
        fence = binding.fence() if binding is not None else self._sandbox(scope)._lock
        with fence, store.run_fence(scope.run_id):
            yield

    def _read(self, run_id: str) -> tuple[int, dict[str, Any]]:
        with self._db().transaction() as db:
            row = db.execute("SELECT revision,value FROM grants WHERE run_id=?", (run_id,)).fetchone()
        if row is None:
            raise PracticeAgentError("protection_not_authorised")
        return row[0], json.loads(row[1])

    def has_grant(self, scope: ExecutionSession) -> bool:
        """Observe issuance, not validity; retired grants must not fall back to JWTs."""
        self._attachment(scope)
        if self._database is None and not any((self.workspace / name).exists() for name in
                ("protection.sqlite", "protection.registry", "protection.sqlite.authority.json")):
            return False
        with self._db().transaction() as db:
            return db.execute("SELECT 1 FROM grants WHERE run_id=?", (scope.run_id,)).fetchone() is not None

    def validate(self, scope: ExecutionSession) -> tuple[int, dict[str, Any]]:
        """Revalidate independent authority; the UI JWT is deliberately irrelevant."""
        self._attachment(scope)
        revision, value = self._read(scope.run_id)
        if value["risk_fingerprint"] != self._risk(scope):
            raise PracticeAgentError("protection_risk_changed")
        if (value["scope"] != asdict(scope) or value["revoked"] or value.get("settled", False)
                or value["policy"]["valid_until"] <= time.time()):
            raise PracticeAgentError("protection_grant_retired")
        if scope.run_id not in self._reconciled:
            raise PracticeAgentError("protection_restart_reconciliation_required")
        with self._db().transaction() as db:
            if db.execute("SELECT 1 FROM attempts WHERE run_id=? AND state='unknown'", (scope.run_id,)).fetchone():
                raise PracticeAgentError("protection_reconciliation_required")
        return revision, value

    @staticmethod
    def _policy(policy: Any) -> dict[str, Any]:
        if type(policy) is not dict or set(policy) != {
            "policy_revision", "valid_until", "position", "hedge_scope", "risk_policy",
            "max_quantity", "max_notional", "read",
        }:
            raise PracticeAgentError("protection_policy_required")
        policy = json.loads(_encoded(policy))
        position, read = policy["position"], policy["read"]
        if (type(policy["policy_revision"]) is not str or not policy["policy_revision"]
                or len(policy["policy_revision"]) > 128
                or not _positive(policy["valid_until"]) or policy["valid_until"] <= time.time()
                or type(policy["max_quantity"]) is not int or policy["max_quantity"] <= 0
                or not _positive(policy["max_notional"])
                or policy["hedge_scope"] != [] or policy["risk_policy"] != "unhedged-cash-reduction-only"
                or type(position) is not dict or set(position) != {
                    "symbol", "exchange", "product", "entry_order_ids", "quantity"}
                or position["exchange"] not in {"NSE", "BSE"} or position["product"] not in {"CNC", "MIS"}
                or type(position["quantity"]) is not int or position["quantity"] <= 0
                or policy["max_quantity"] > position["quantity"]
                or type(position["entry_order_ids"]) is not list or not position["entry_order_ids"]
                or any(type(item) is not str or not item for item in position["entry_order_ids"])
                or len(set(position["entry_order_ids"])) != len(position["entry_order_ids"])
                or type(read) is not dict or set(read) != {"selector", "valid_until", "max_reads", "max_age_seconds"}
                or type(read["max_reads"]) is not int or read["max_reads"] <= 0
                or not _positive(read["max_age_seconds"]) or read["max_age_seconds"] > 60
                or not _positive(read["valid_until"]) or not time.time() < read["valid_until"] <= policy["valid_until"]):
            raise PracticeAgentError("protection_policy_invalid")
        from .broker_identity import parse_broker_selector
        parse_broker_selector(read["selector"])
        return policy

    def configure(self, run_id: str, policy: Any, expected_revision: int) -> dict[str, Any]:
        """Explicit HTTP operator action, reauthenticated at the durable mutation."""
        from .protection_routes import operator

        who, subject = operator()
        if type(expected_revision) is not int or expected_revision < 0:
            raise PracticeAgentError("protection_revision_invalid")
        attached = self._owners.get(run_id)
        if attached is None or attached[0].actor != who.actor_ref:
            raise PracticeAgentError("protection_owner_unproved")
        scope, store, _ = attached
        policy = self._policy(policy)
        with self._fence(scope):
            self._attachment(scope)
            self._position(scope, policy, [])
            if operator()[0] != who:
                raise PracticeAgentError("protection_operator_changed")
            with self._db(create=True).transaction() as db:
                old = db.execute("SELECT revision FROM grants WHERE run_id=?", (run_id,)).fetchone()
                if (old[0] if old else 0) != expected_revision:
                    raise PracticeAgentError("protection_revision_changed")
                if db.execute("SELECT 1 FROM attempts WHERE run_id=?", (run_id,)).fetchone():
                    raise PracticeAgentError("protection_reconciliation_required")
                value = {"scope": asdict(scope), "policy": policy, "subject": subject,
                         "monitor": self._monitor_rule(scope, policy),
                         "risk_fingerprint": self._risk(scope),
                         "revoked": False, "reads": 0, "quantity_used": 0, "notional_used": 0.0}
                revision = expected_revision + 1
                db.execute("INSERT OR REPLACE INTO grants VALUES (?,?,?)", (run_id, revision, _encoded(value)))
            self._reconciled.add(run_id)
        return {"scope": asdict(scope), "revision": revision, "policy": policy}

    def _monitor_rule(self, scope: ExecutionSession, policy: dict[str, Any]) -> dict[str, Any] | None:
        """Pin the existing fixed Practice rule; never invent strategy semantics."""
        store, adapter = self._attachment(scope)
        supervisor = getattr(adapter, "_protection_supervisor", None)
        from .practice_agent_runtime import PracticeAgentSupervisor
        if not isinstance(supervisor, PracticeAgentSupervisor):
            return None
        position = policy["position"]
        detail = store.get_run(scope.run_id)["snapshot"].get("position_details", {}).get(position["symbol"])
        if (type(detail) is not dict or set(detail) != {"entry_price", "stop_loss", "take_profit", "action", "quantity"}
                or detail["action"] != "BUY" or detail["quantity"] != position["quantity"]
                or any(not _positive(detail[key]) for key in ("entry_price", "stop_loss", "take_profit"))):
            return None
        return json.loads(_encoded({"symbol": position["symbol"], **detail}))

    def recovery_scopes(self) -> list[ExecutionSession]:
        """Enumerate issued duty identities only; missing custody is unavailable."""
        with self._db().transaction() as db:
            return [ExecutionSession(**json.loads(row[0])["scope"])
                    for row in db.execute("SELECT value FROM grants ORDER BY run_id").fetchall()]

    def readback(self, run_id: str, actor: str) -> dict[str, Any]:
        """Observe an existing owner only; never attach, reconcile or issue authority."""
        attached = self._owners.get(run_id)
        if attached is None:
            # Existing durable authority may be visible before successful
            # execution recovery. Observation cannot construct that owner or
            # certify flatness; keep the duty explicitly unknown.
            if self._database is None and not self._had_registry:
                raise PracticeAgentError("protection_owner_unproved")
            from .backend_instance import require_backend_lease_proof
            require_backend_lease_proof(self.app.config.get("BACKEND_LEASE_PROOF"))
            if self.app.config.get("PROTECTION_SERVICES") is not self or self._closed:
                raise PracticeAgentError("protection_owner_unavailable")
            try:
                revision, value = self._read(run_id)
            except PracticeAgentError as exc:
                if exc.code == "protection_not_authorised":
                    raise PracticeAgentError("protection_owner_unproved") from None
                raise
            if value["scope"]["actor"] != actor:
                raise PracticeAgentError("protection_owner_unproved")
            with self._db().transaction() as db:
                attempts = db.execute("SELECT id,state,order_id FROM attempts WHERE run_id=? ORDER BY id", (run_id,)).fetchall()
            return {"scope": value["scope"], "revision": revision, "policy": value["policy"],
                    "authority_state": "unavailable", "usage": {key: value[key] for key in
                    ("reads", "quantity_used", "notional_used")}, "supervision": "unavailable",
                    "duty": {"state": "unknown", "remaining_quantity": None, "reconciliation_required": True,
                             "attempts": [{"id": a[0], "state": a[1], "order_id": a[2]} for a in attempts]}}
        if attached[0].actor != actor:
            raise PracticeAgentError("protection_owner_unproved")
        scope, _store, adapter = attached
        self._attachment(scope)
        result = {"scope": asdict(scope), "revision": 0, "policy": None, "authority_state": "not_issued",
                  "usage": None, "duty": {"state": "not_granted", "remaining_quantity": None,
                  "reconciliation_required": False, "attempts": []}, "supervision": "unavailable"}
        if not self.has_grant(scope):
            return result
        with self._fence(scope):
            revision, value = self._read(run_id)
            with self._db().transaction() as db:
                attempts = db.execute("SELECT id,state,order_id FROM attempts WHERE run_id=? ORDER BY id", (run_id,)).fetchall()
            unknown = run_id not in self._reconciled or any(a[1] == "unknown" for a in attempts)
            remaining = None
            try:
                if value["scope"] != asdict(scope) or value["risk_fingerprint"] != self._risk(scope):
                    raise ValueError
                remaining = self._position(scope, value["policy"], attempts)
            except Exception:
                unknown = True
            settled = not unknown and remaining == 0 and value.get("settled", False) and self._owner_finished(scope)
            authority = "unavailable"
            try:
                self.validate(scope)
                authority = "active"
            except PracticeAgentError as exc:
                if exc.code == "protection_grant_retired":
                    authority = "retired"
            supervisor = getattr(adapter, "_protection_supervisor", None)
            run = getattr(supervisor, "run", None)
            supervising = bool(run and run.adapter is adapter and run.thread and run.thread.is_alive()
                               and not run.stop.is_set() and not adapter._closed)
            result.update(revision=revision, policy=value["policy"], authority_state=authority,
                          usage={key: value[key] for key in ("reads", "quantity_used", "notional_used")},
                          duty={"state": "unknown" if unknown else "settled" if settled else "retained",
                                "remaining_quantity": remaining, "reconciliation_required": unknown,
                                "attempts": [{"id": a[0], "state": a[1], "order_id": a[2]} for a in attempts]},
                          supervision="supervising" if supervising else "unavailable")
            return result

    def _risk(self, scope: ExecutionSession) -> str:
        store, _ = self._attachment(scope)
        from .secure_file import validate_owner_owned_regular_file

        sources = []
        for raw in (store.database_path, self._sandbox(scope)._db_path):
            path = Path(raw).absolute()
            info = validate_owner_owned_regular_file(path)
            sources.append({"path": str(path), "device": info.st_dev, "inode": info.st_ino})
        return _digest({"scope": asdict(scope), "config": store.get_run(scope.run_id)["config"],
                        "sandbox": asdict(self._sandbox(scope).config), "sources": sources})

    def revoke(self, run_id: str, expected_revision: int) -> dict[str, Any]:
        """Retire authority under the same write fence, retaining every duty."""
        from .protection_routes import operator

        who, _ = operator()
        revision, value = self._read(run_id)
        scope = ExecutionSession(**value["scope"])
        if scope.actor != who.actor_ref or type(expected_revision) is not int or expected_revision != revision:
            raise PracticeAgentError("protection_revision_or_owner")
        store, _ = self._attachment(scope)
        with self._fence(scope), self._db().transaction() as db:
            if operator()[0] != who or db.execute("SELECT revision FROM grants WHERE run_id=?", (run_id,)).fetchone()[0] != revision:
                raise PracticeAgentError("protection_revision_changed")
            value["revoked"] = True
            db.execute("UPDATE grants SET revision=?,value=? WHERE run_id=?", (revision + 1, _encoded(value), run_id))
        return {"scope": asdict(scope), "revision": revision + 1, "revoked": True, "duty_retained": True}

    def resume(self, scope: ExecutionSession, store: Any, adapter: Any) -> None:
        """Reattach only the known duty after exact read-only write reconciliation."""
        self.attach(scope, store, adapter)
        self.reconcile(scope)
        self.validate(scope)

    def _confirmed_order(self, scope: ExecutionSession, body: dict[str, Any], order_id: str) -> None:
        sandbox = self._sandbox(scope)
        orders = [row for row in sandbox.get_all_orders() if row.get("order_id") == order_id]
        trades = [row for row in sandbox.get_trades() if row.get("order_id") == order_id]
        if (len(orders) != 1 or len(trades) != 1 or orders[0].get("status") != "COMPLETE"
                or orders[0].get("filled_qty") != body["quantity"]
                or any(any(row.get(k) != body[k] for k in
                           ("symbol", "exchange", "product", "action", "quantity", "strategy"))
                       for row in (orders[0], trades[0]))
                or trades[0].get("price") != body["price"]):
            raise PracticeAgentError("protection_reconciliation_required")

    def reconcile(self, scope: ExecutionSession) -> dict[str, Any]:
        """Resolve only exact known writes; missing ACK/absence never permits replay."""
        store, _ = self._attachment(scope)
        sandbox = self._sandbox(scope)
        with self._fence(scope):
            revision, value = self._read(scope.run_id)
            if value["scope"] != asdict(scope):
                raise PracticeAgentError("protection_scope_invalid")
            if value["risk_fingerprint"] != self._risk(scope):
                raise PracticeAgentError("protection_risk_changed")
            with self._db().transaction() as db:
                attempts = db.execute("SELECT id,state,order_id,body FROM attempts WHERE run_id=?",
                                      (scope.run_id,)).fetchall()
                resolved = []
                for nonce, state, order_id, encoded in attempts:
                    body = json.loads(encoded)
                    if state == "unknown":
                        matches = [row for row in sandbox.get_all_orders() if row.get("strategy") == body["strategy"]]
                        if len(matches) != 1:
                            raise PracticeAgentError("protection_reconciliation_required")
                        order_id = matches[0]["order_id"]
                    self._confirmed_order(scope, body, order_id)
                    db.execute("UPDATE attempts SET state='completed',order_id=? WHERE id=?", (order_id, nonce))
                    resolved.append((nonce, "completed", order_id))
                remaining = self._position(scope, value["policy"], resolved)
                value["settled"] = remaining == 0 and self._owner_finished(scope)
                db.execute("UPDATE grants SET value=? WHERE run_id=?", (_encoded(value), scope.run_id))
            self._reconciled.add(scope.run_id)
            return {"scope": asdict(scope), "revision": revision, "remaining_quantity": remaining,
                    "entries_armed": False, "reconciliation_required": False}

    def _position(self, scope: ExecutionSession, policy: dict[str, Any], attempts: list[Any],
                  *, admitting: _ProtectionPrincipal | None = None) -> int:
        """Prove run-owned entry identities against the real, unnetted cash book."""
        store, _ = self._attachment(scope)
        sandbox = self._sandbox(scope)
        position = policy["position"]
        events, cursor = [], 0
        while True:
            batch = store.events(scope.run_id, after=cursor, limit=1000)
            events.extend(batch)
            if not batch:
                break
            cursor = batch[-1]["seq"]
        outstanding: Counter[str] = Counter()
        reconciled_tags = {"Protection:" + row[0] for row in attempts if row[1] == "completed"}
        if admitting is not None:
            reconciled_tags.add("Protection:" + admitting.nonce)
        for event in events:
            data = event["data"]
            if event["kind"] == "dispatch_started":
                if data["order"].get("strategy") not in reconciled_tags:
                    outstanding[_digest(data["order"])] += 1
            elif event["kind"] == "dispatch_result":
                response = data["response"]
                terminal = response.get("status") == "COMPLETE" or (
                    response.get("status") == "error" and 400 <= response.get("http_status", 0) < 500
                    and not response.get("order_id") and not response.get("orderid"))
                if terminal and outstanding[_digest(data["order"])] > 0:
                    outstanding[_digest(data["order"])] -= 1
        if any(outstanding.values()):
            raise PracticeAgentError("protection_entry_reconciliation_required")
        owned = {event["data"].get("response", {}).get("order_id") for event in events
                 if event["kind"] == "dispatch_result" and event["data"].get("response", {}).get("status") == "COMPLETE"}
        entry_ids = set(position["entry_order_ids"])
        if not entry_ids <= owned:
            raise PracticeAgentError("protection_owner_unproved")
        trades = sandbox.get_trades()
        entries = [trade for trade in trades if trade.get("order_id") in entry_ids]
        if len(entries) != len(entry_ids) or any(
            any(trade.get(field) != position[field] for field in ("symbol", "exchange", "product"))
            or trade.get("action") != "BUY" or type(trade.get("quantity")) is not int or trade["quantity"] <= 0
            for trade in entries
        ) or sum(trade["quantity"] for trade in entries) != position["quantity"]:
            raise PracticeAgentError("protection_owner_unproved")
        exits = {row[2] for row in attempts if row[1] == "completed"}
        known = entry_ids | exits
        contract_trades = [trade for trade in trades if all(trade.get(k) == position[k]
                                                          for k in ("symbol", "exchange", "product"))]
        if any(trade.get("order_id") not in known for trade in contract_trades):
            raise PracticeAgentError("protection_netted_or_unknown")
        if any(row.get("status") not in {"COMPLETE", "CANCELLED", "REJECTED"}
               for row in sandbox.get_all_orders()):
            raise PracticeAgentError("protection_pending_orders")
        positions = sandbox.get_positions()
        if any(any(row.get(k) != position[k] for k in ("symbol", "exchange", "product")) for row in positions):
            raise PracticeAgentError("protection_hedge_unqualified")
        expected = sum(trade["quantity"] * (1 if trade["action"] == "BUY" else -1) for trade in contract_trades)
        observed = sum(row["net_qty"] for row in positions)
        if expected != observed or expected < 0:
            raise PracticeAgentError("protection_owner_unproved")
        return expected

    def collect(self, scope: ExecutionSession, symbol: str, exchange: str) -> Any:
        """Read only the explicitly permitted quote through the existing read owner."""
        from .protection_reads import collect_protection_quote
        return collect_protection_quote(self, scope, symbol, exchange)

    def prepare(self, scope: ExecutionSession, body: dict[str, Any], context: Any) -> tuple[Any, dict[str, Any]]:
        """Mint an in-process, exact one-shot principal, not a bearer credential."""
        revision, _ = self.validate(scope)
        nonce = uuid4().hex
        body = {**body, "strategy": "Protection:" + nonce, "pricetype": body["order_type"]}
        principal = _ProtectionPrincipal(self, scope, revision, nonce, _digest(body), context)
        self._principals[nonce] = principal
        return principal, body

    def verify_read(self, scope: ExecutionSession, revision: int, context: Any) -> None:
        """Recheck exact read grant/credential generation at the actual write."""
        try:
            receipt = self._read_receipts[context.receipt["event_id"]]
            bound_scope, bound_revision, digest, observed, max_age, verify = receipt
            if (scope != bound_scope or revision != bound_revision or digest != _digest(context.market_data)
                    or not 0 <= time.time() - observed <= max_age):
                raise ValueError
            verify()
        except Exception:
            raise PracticeAgentError("protection_read_retired") from None

    def verify_principal(self, principal: Any, body: dict[str, Any]) -> None:
        if (type(principal) is not _ProtectionPrincipal or principal.owner is not self
                or self._principals.get(principal.nonce) is not principal or _digest(body) != principal.body_digest):
            raise PracticeAgentError("protection_principal_invalid")
        revision, _ = self.validate(principal.scope)
        if revision != principal.revision:
            raise PracticeAgentError("protection_revision_changed")

    @contextmanager
    def admit(self, principal: Any, body: dict[str, Any]) -> Iterator[None]:
        """Consume durably at the canonical write, under actual execution fences."""
        scope = principal.scope
        store, adapter = self._attachment(scope)
        with self._fence(scope):
            self.verify_principal(principal, body)
            revision, value = self.validate(scope)
            policy = value["policy"]
            self.verify_read(scope, revision, principal.context)
            with self._db().transaction() as db:
                attempts = db.execute("SELECT id,state,order_id FROM attempts WHERE run_id=?", (scope.run_id,)).fetchall()
                remaining = self._position(scope, policy, attempts, admitting=principal)
                position = policy["position"]
                quantity, price = body.get("quantity"), body.get("price")
                adapter._quote(principal.context, body["symbol"], body["exchange"])
                if (any(body.get(k) != position[k] for k in ("symbol", "exchange", "product"))
                        or body.get("action") != "SELL" or body.get("order_type") != "MARKET"
                        or type(quantity) is not int or not 0 < quantity <= remaining
                        or not _positive(price) or value["quantity_used"] + quantity > policy["max_quantity"]
                        or value["notional_used"] + price * quantity > policy["max_notional"]
                        or not adapter._is_reduction(body)):
                    raise PracticeAgentError("protection_bounds_or_reduction")
                db.execute("INSERT INTO attempts VALUES (?,?,?,?,?,NULL)",
                           (principal.nonce, scope.run_id, revision, _encoded(body), "unknown"))
                value["quantity_used"] += quantity
                value["notional_used"] += price * quantity
                db.execute("UPDATE grants SET value=? WHERE run_id=?", (_encoded(value), scope.run_id))
            # Consumption is committed before a possible write; exceptions never release it.
            self._principals.pop(principal.nonce, None)
            yield

    def record_result(self, principal: Any, result: Any) -> None:
        """Bind only a confirmed canonical identity, preserving unknown outcomes."""
        if type(result) is not dict or result.get("status") != "COMPLETE" or not result.get("order_id"):
            raise PracticeAgentError("protection_reconciliation_required")
        with self._db().transaction() as db:
            row = db.execute("SELECT body FROM attempts WHERE id=? AND state='unknown'", (principal.nonce,)).fetchone()
            if row is None:
                raise PracticeAgentError("protection_reconciliation_required")
            self._confirmed_order(principal.scope, json.loads(row[0]), result["order_id"])
            db.execute("UPDATE attempts SET state='completed',order_id=? WHERE id=? AND state='unknown'",
                       (result["order_id"], principal.nonce))

    @staticmethod
    def _closed_sources(paths: tuple[str, ...]) -> tuple[Any, ...]:
        from .secure_file import validate_owner_owned_regular_file
        result = []
        for raw in paths:
            path = Path(raw)
            info = validate_owner_owned_regular_file(path)
            result.append((raw, info.st_dev, info.st_ino, hashlib.sha256(path.read_bytes()).hexdigest()))
            wal = Path(raw + "-wal")
            if wal.exists():
                info = validate_owner_owned_regular_file(wal)
                result.append((str(wal), info.st_dev, info.st_ino, hashlib.sha256(wal.read_bytes()).hexdigest()))
        return tuple(result)

    def release_after_drain(self, scope: ExecutionSession, dispose: Any) -> None:
        """Seal exact terminal evidence before its registry closes borrowed books.

        The in-process receipt only permits dependency disposal, never a write,
        GET-created owner or restart authority. Any later source drift refuses.
        """
        from .execution_session import run_drained
        store, adapter = self._attachment(scope)
        if not self.has_grant(scope):
            dispose()
            return
        supervisor = getattr(adapter, "_protection_supervisor", None)
        if supervisor is None or not run_drained(supervisor.run):
            raise PracticeAgentError("protection_duties_retained")
        self.reconcile(scope)
        revision, value = self._read(scope.run_id)
        if not value.get("settled"):
            raise PracticeAgentError("protection_duties_retained")
        paths = (str(Path(store.database_path).absolute()), str(Path(self._books[scope.run_id]._db_path).absolute()))
        dispose()
        self._released[scope.run_id] = (scope, revision, _digest(value), paths, self._closed_sources(paths))

    def maintenance_snapshot(self) -> dict[str, Any]:
        """Complete protection-duty census; missing evidence is never an empty book."""
        try:
            with self._db().transaction() as db:
                rows = db.execute("SELECT run_id,revision,value FROM grants ORDER BY run_id").fetchall()
                attempts = db.execute("SELECT id,run_id,state,order_id FROM attempts ORDER BY id").fetchall()
            runs = []
            for run_id, revision, encoded in rows:
                value = json.loads(encoded)
                scope = ExecutionSession(**value["scope"])
                own = [(a[0], a[2], a[3]) for a in attempts if a[1] == run_id]
                unknown = run_id not in self._reconciled or any(a[1] == "unknown" for a in own)
                settled = False
                try:
                    released = self._released.get(run_id)
                    if released is not None:
                        released_scope, released_revision, value_digest, paths, sources = released
                        if (released_scope != scope or released_revision != revision or value_digest != _digest(value)
                                or sources != self._closed_sources(paths) or unknown or not value.get("settled")):
                            raise ValueError("retired custody changed")
                        settled = True
                    else:
                        with self._fence(scope):
                            if value["risk_fingerprint"] != self._risk(scope):
                                raise ValueError
                            flat = self._position(scope, value["policy"], own) == 0
                            settled = bool(value.get("settled") and flat and self._owner_finished(scope) and not unknown)
                except Exception:
                    unknown = True
                runs.append({"scope": asdict(scope), "revision": revision, "revoked": value["revoked"],
                             "duty_retained": not settled, "reconciliation_required": unknown,
                             "attempts": [{"id": a[0], "state": a[1], "order_id": a[2]} for a in own]})
            return {"registry_complete": True, "disposal_authorised": all(not r["duty_retained"] for r in runs),
                    "runs": runs}
        except Exception:
            return {"registry_complete": False, "disposal_authorised": False, "runs": [],
                    "error": "protection_custody_unavailable"}

    def _owner_finished(self, scope: ExecutionSession) -> bool:
        store, adapter = self._attachment(scope)
        row = store.get_run(scope.run_id)
        return adapter._closed and row["status"] in {"stopped", "completed"} and not row["error"]

    def close(self) -> None:
        """Refuse disposal while a durable protection duty remains owned."""
        if self._closed:
            return
        from .execution_session import run_drained
        for _scope, _store, adapter in self._owners.values():
            supervisor = getattr(adapter, "_protection_supervisor", None)
            if not adapter._closed or supervisor is not None and not run_drained(supervisor.run):
                raise PracticeAgentError("protection_duties_retained")
        if (self._database is None and not self._had_registry
                and not any((self.workspace / name).exists() for name in
                            ("protection.sqlite", "protection.registry", "protection.sqlite.authority.json"))):
            # Closing a never-issued in-process owner is not a complete
            # historical census or permission to erase any workspace.
            self._closed = True
            return
        if not self.maintenance_snapshot()["disposal_authorised"]:
            raise PracticeAgentError("protection_duties_retained")
        self._closed = True


def request_principal() -> _ProtectionPrincipal | None:
    """Resolve only the exact canonical in-process request, never HTTP fields."""
    if not has_request_context() or _PRINCIPAL not in request.environ:
        return None
    if request.path != "/api/v1/orders/place" or request.method != "POST":
        raise PracticeAgentError("protection_endpoint_forbidden")
    principal = request.environ[_PRINCIPAL]
    owner = current_app.config.get("PROTECTION_SERVICES")
    if type(owner) is not ProtectionServices:
        raise PracticeAgentError("protection_owner_unavailable")
    owner.verify_principal(principal, request.get_json())
    _, adapter = owner._attachment(principal.scope)
    if request.environ.get("flinttrade.execution_binding") is not adapter._execution_binding:
        raise PracticeAgentError("protection_execution_scope_missing")
    return principal


def install_protection_services(app: Any, workspace: Path) -> ProtectionServices:
    """Install lazy permission ownership and explicit authenticated controls."""
    existing = app.config.get("PROTECTION_SERVICES")
    if existing is not None:
        if type(existing) is not ProtectionServices or existing.workspace != Path(workspace):
            raise ValueError("Protection owner conflict")
        return existing
    from .protection_routes import protection_bp
    owner = ProtectionServices(app, workspace)
    app.config["PROTECTION_SERVICES"] = owner
    app.register_blueprint(protection_bp)
    return owner
