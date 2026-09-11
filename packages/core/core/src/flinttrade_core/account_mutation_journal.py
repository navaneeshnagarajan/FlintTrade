"""Installation-bound account receipts, phase journal and redacted audit outbox.

This is an inert transaction dependency. Trusted activation adapters supply the
effects; this module imports no gateway, provider, route or broker store. Every
write commits with SQLite FULL durability, advances the independent owner-keyed
anchor, and only then permits an effect. Rollback/copy never creates authority.
"""

from __future__ import annotations

import hashlib
import hmac
import sqlite3
import time
from collections.abc import Callable
from contextlib import ExitStack
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any
from uuid import UUID, uuid4

from cryptography.fernet import Fernet

from .account_mutation_contracts import (
    AccountMutationConflict,
    AccountMutationRequest,
    AccountMutationResult,
    AccountMutationValidationError,
    AccountRecoveryUnavailable,
    MutationPhase,
    OperationRef,
    require_revision,
    require_uuid4,
)
from .account_mutation_locks import OperationLockToken, require_operation_lock
from .account_mutation_principals import validate_principal
from .broker_identity import BrokerSelector
from .db import open_sqlite
from .installation_state import InstallationState
from .secure_file import HeldOwnerDirectory, assert_hardened, fsync_parent_directory
from .service_connection_transactions import canonical, decode, directory_pin

_BINDING = ".account-coordinator-binding.json"
_ANCHOR = ".account-coordinator-anchor.json"
_KEYS = ".account-coordinator-keys.json"
_DATABASE = "accounts.sqlite3"
_TABLES = ("operations", "auth_flows", "auth_children", "retirements", "outbox", "operation_tombstones", "route_attempts")
_TERMINAL = {MutationPhase.COMMITTED, MutationPhase.COMMITTED_DISCONNECTED,
             MutationPhase.PROVIDER_REJECTED, MutationPhase.EXTERNAL_UNKNOWN}
_TRANSITIONS = {
    MutationPhase.PREPARED: {MutationPhase.ROUTER_DRAINED, MutationPhase.DURABLE_COMMIT_PREPARED},
    MutationPhase.ROUTER_DRAINED: {MutationPhase.EXTERNAL_INVOCATION_PREPARED, MutationPhase.DURABLE_COMMIT_PREPARED},
    MutationPhase.EXTERNAL_INVOCATION_PREPARED: {MutationPhase.EXTERNAL_INVOKED},
    MutationPhase.EXTERNAL_INVOKED: {MutationPhase.CANDIDATE_STAGED, MutationPhase.PROVIDER_REJECTED, MutationPhase.EXTERNAL_UNKNOWN},
    MutationPhase.CANDIDATE_STAGED: {MutationPhase.DURABLE_COMMIT_PREPARED},
    MutationPhase.DURABLE_COMMIT_PREPARED: {MutationPhase.WORKSPACE_COMMITTED, MutationPhase.VAULT_COMMITTED, MutationPhase.PROJECTION_COMMITTED, MutationPhase.DURABLE_COMMITTED},
    MutationPhase.WORKSPACE_COMMITTED: {MutationPhase.VAULT_COMMITTED, MutationPhase.PROJECTION_COMMITTED, MutationPhase.DURABLE_COMMITTED},
    MutationPhase.VAULT_COMMITTED: {MutationPhase.PROJECTION_COMMITTED, MutationPhase.DURABLE_COMMITTED},
    MutationPhase.PROJECTION_COMMITTED: {MutationPhase.DURABLE_COMMITTED},
    MutationPhase.DURABLE_COMMITTED: {MutationPhase.SOURCE_RETIRED, MutationPhase.REGISTRY_PUBLISHED},
    MutationPhase.SOURCE_RETIRED: {MutationPhase.REGISTRY_PUBLISHED},
    MutationPhase.REGISTRY_PUBLISHED: {MutationPhase.FACADE_PUBLISHED, MutationPhase.ROUTER_REBUILT},
    MutationPhase.FACADE_PUBLISHED: {MutationPhase.ROUTER_REBUILT},
    MutationPhase.ROUTER_REBUILT: {MutationPhase.COMMITTED, MutationPhase.COMMITTED_DISCONNECTED},
}


def _json_value(value: object) -> object:
    """Encode neutral versions, not arbitrary user objects or exception text."""
    if isinstance(value, UUID):
        return str(value)
    if isinstance(value, dict):
        return {key: _json_value(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_value(item) for item in value]
    return value


def _identity(value: object) -> dict[str, int]:
    return {"device": value.st_dev, "object": value.st_ino}


@dataclass(frozen=True)
class AccountAuditRecord:
    """Typed sink payload; candidate refs, HMACs and private inputs are absent."""

    event_id: UUID
    operation_id: UUID
    store_incarnation: UUID
    revision: int
    actor_ref: str
    principal_kind: str
    scope: tuple[str, ...]
    operation: str
    selector: BrokerSelector | None
    phase: MutationPhase
    outcome: str


class ProviderRejected(RuntimeError):
    """A pinned adapter's definite refusal, as distinct from unknown outcome."""

    def __init__(self) -> None:
        super().__init__("provider_rejected")


class AccountMutationJournal:
    """A held, fully verified recovery-store scope under the coordinator lock."""

    def __init__(
        self, installation: InstallationState, recovery_root: Path, *, token: OperationLockToken,
        kill_point: Callable[[str], None] | None = None,
    ) -> None:
        self.installation = installation
        self.root = Path(recovery_root).absolute()
        self.database_path = self.root / _DATABASE
        self.token = token
        self.kill_point = kill_point or (lambda _point: None)
        self._stack = ExitStack()
        self._connection: sqlite3.Connection | None = None

    def __enter__(self) -> AccountMutationJournal:
        try:
            require_operation_lock(self.token, installation=self.installation)
            # InstallationState owns platform/topology resolution. This injected
            # namespace is one direct child, never an active/archive/restore path.
            if self.root.parent != self.installation.root or self.root.name != "account-coordinator":
                raise AccountRecoveryUnavailable
            self._owner = self._stack.enter_context(HeldOwnerDirectory(self.installation.root))
            if not self._owner.exists(_BINDING):
                if any(self._owner.exists(name) for name in (_ANCHOR, _KEYS, self.root.name)):
                    raise AccountRecoveryUnavailable
                # Ownership exists outside the replaceable namespace before its
                # first creation. Interrupted bootstrap stays unavailable.
                self._owner.write_text(_BINDING, canonical({"schema": 1, "ready": False}))
                self._directory = self._stack.enter_context(self._owner.child(self.root.name, create=True))
                self.store_incarnation = uuid4()
                keys = {name: Fernet.generate_key().decode("ascii") for name in ("encryption", "mac", "pepper")}
                self._owner.write_text(_KEYS, canonical(keys))
                self._load_keys()
                observed = self._directory.create_empty_hardened_member(_DATABASE)
                self._connection = open_sqlite(self.database_path, durability="full", strict_existing=True)
                self._create_schema()
                self._binding = {
                    "schema": 1, "ready": True, "installation_id": str(self.installation.installation_id),
                    "store_incarnation": str(self.store_incarnation),
                    "root_pin": directory_pin(self._directory.revalidate()), "database_pin": _identity(observed),
                }
                self._write_anchor(0, "0" * 64)
                self._owner.write_text(_BINDING, canonical(self._binding))
                fsync_parent_directory(self.database_path)
            else:
                self._binding = decode(self._owner.read_text(_BINDING))
                if (
                    self._binding.get("ready") is not True or self._binding.get("schema") != 1
                    or self._binding.get("installation_id") != str(self.installation.installation_id)
                ):
                    raise AccountRecoveryUnavailable
                self.store_incarnation = require_uuid4(UUID(self._binding["store_incarnation"]))
                self._directory = self._stack.enter_context(self._owner.child(self.root.name))
                self._load_keys()
                self._validate_files()
                self._connection = open_sqlite(self.database_path, durability="full", strict_existing=True)
            self._verify(recover_extension=True)
            return self
        except Exception:
            self.close()
            raise AccountRecoveryUnavailable from None
        except BaseException:
            self.close()
            raise

    def __exit__(self, *args: object) -> None:
        self.close()

    def close(self) -> None:
        """Release this database/directory scope; the caller still owns its lock."""
        if self._connection is not None:
            self._connection.close()
            self._connection = None
        self._stack.close()

    def _load_keys(self) -> None:
        keys = decode(self._owner.read_text(_KEYS, max_bytes=1024))
        if set(keys) != {"encryption", "mac", "pepper"} or len(set(keys.values())) != 3:
            raise AccountRecoveryUnavailable
        for value in keys.values():
            Fernet(value.encode("ascii"))
        self._cipher = Fernet(keys["encryption"].encode("ascii"))
        self._mac_key = keys["mac"].encode("ascii")
        self._pepper = keys["pepper"].encode("ascii")

    def _create_schema(self) -> None:
        self._connection.execute("PRAGMA foreign_keys=ON")
        self._connection.execute("CREATE TABLE events (sequence INTEGER PRIMARY KEY CHECK(sequence > 0), table_name TEXT NOT NULL, entity_id TEXT NOT NULL, revision INTEGER NOT NULL CHECK(revision > 0), body TEXT NOT NULL, head TEXT NOT NULL)")
        for table in _TABLES:
            self._connection.execute(f"CREATE TABLE {table} (entity_id TEXT PRIMARY KEY, revision INTEGER NOT NULL CHECK(revision > 0), body TEXT NOT NULL)")
        self._connection.execute("CREATE UNIQUE INDEX receipt_key ON operations(json_extract(body, '$.idempotency_key'))")
        self._connection.execute("CREATE UNIQUE INDEX current_child ON auth_flows(json_extract(body, '$.current_child'))")
        self._connection.execute("CREATE UNIQUE INDEX consumed_child ON auth_children(json_extract(body, '$.operation_id'))")
        self._connection.commit()

    def _validate_files(self) -> None:
        require_operation_lock(self.token, installation=self.installation)
        self._directory.revalidate()
        if directory_pin(self._directory.revalidate(), self._binding["root_pin"]) != self._binding["root_pin"]:
            raise AccountRecoveryUnavailable
        path_stat = self.database_path.lstat()
        if (
            self.database_path.is_symlink() or path_stat.st_nlink != 1
            or _identity(path_stat) != self._binding["database_pin"]
            or not assert_hardened(self.database_path)[0]
        ):
            raise AccountRecoveryUnavailable

    def _mac(self, domain: str, value: object, *, pepper: bool = False) -> str:
        return hmac.new(
            self._pepper if pepper else self._mac_key,
            (domain + "\0" + canonical(value)).encode(), hashlib.sha256,
        ).hexdigest()

    def _write_anchor(self, sequence: int, head: str) -> None:
        anchor = {"schema": 1, "installation_id": str(self.installation.installation_id),
                  "store_incarnation": str(self.store_incarnation), "sequence": sequence, "head": head}
        anchor["mac"] = self._mac("account-anchor/v1", anchor)
        self._owner.write_text(_ANCHOR, canonical(anchor))
        self.anchor_sequence = sequence

    def _verify(self, *, recover_extension: bool = False) -> None:
        try:
            self._validate_files()
            anchor = decode(self._owner.read_text(_ANCHOR))
            mac = anchor.pop("mac")
            if (
                anchor.get("store_incarnation") != str(self.store_incarnation)
                or anchor.get("installation_id") != str(self.installation.installation_id)
                or not hmac.compare_digest(mac, self._mac("account-anchor/v1", anchor))
            ):
                raise AccountRecoveryUnavailable
            anchored = require_revision(anchor["sequence"], unseen=True)
            expected = {table: {} for table in _TABLES}
            head, sequence, anchor_head = "0" * 64, 0, "0" * 64
            extension_safe = True
            for event in self._connection.execute("SELECT sequence, table_name, entity_id, revision, body, head FROM events ORDER BY sequence"):
                number, table, entity, revision, body, stored_head = event
                if number != sequence + 1 or table not in expected:
                    raise AccountRecoveryUnavailable
                require_revision(number)
                require_revision(revision)
                old = expected[table].get(entity)
                if revision != (old[0] + 1 if old else 1):
                    raise AccountRecoveryUnavailable
                payload = decode(body)
                if canonical(payload) != body:
                    raise AccountRecoveryUnavailable
                head = self._mac("account-event/v1", [str(self.store_incarnation), head, *event[:5]])
                if not hmac.compare_digest(head, stored_head):
                    raise AccountRecoveryUnavailable
                expected[table][entity] = (revision, body)
                sequence = number
                if sequence == anchored:
                    anchor_head = head
                if sequence > anchored and table == "operations" and payload["phase"] not in {
                    "prepared", "external_invocation_prepared", "durable_commit_prepared",
                }:
                    extension_safe = False
                if sequence > anchored and table not in {"operations", "outbox", "operation_tombstones"}:
                    extension_safe = False
            if anchored > sequence or anchor_head != anchor["head"]:
                raise AccountRecoveryUnavailable
            for table in _TABLES:
                observed = {key: (revision, body) for key, revision, body in self._connection.execute(f"SELECT entity_id, revision, body FROM {table}")}
                if expected[table] != observed:
                    raise AccountRecoveryUnavailable
            self.event_sequence, self._head, self.anchor_sequence = sequence, head, anchored
            if sequence != anchored:
                if not recover_extension or not extension_safe:
                    raise AccountRecoveryUnavailable
                self._write_anchor(sequence, head)
        except Exception:
            raise AccountRecoveryUnavailable from None

    def _write(self, updates: list[tuple[str, str, int | None, dict[str, Any]]]) -> None:
        """One atomic domain+audit transaction, then the independent fsync anchor."""
        self._verify()
        connection = self._connection
        connection.execute("BEGIN IMMEDIATE")
        sequence, head = self.event_sequence, self._head
        try:
            for table, entity, expected_revision, payload in updates:
                if table not in _TABLES:
                    raise AccountMutationValidationError
                current = connection.execute(f"SELECT revision FROM {table} WHERE entity_id=?", (entity,)).fetchone()
                if (current[0] if current else None) != expected_revision:
                    raise AccountMutationConflict
                revision = require_revision((expected_revision or 0) + 1)
                sequence = require_revision(sequence + 1)
                body = canonical(payload)
                if len(body.encode()) > 256 * 1024:
                    raise AccountMutationValidationError
                head = self._mac("account-event/v1", [str(self.store_incarnation), head, sequence, table, entity, revision, body])
                connection.execute("INSERT INTO events VALUES (?, ?, ?, ?, ?, ?)", (sequence, table, entity, revision, body, head))
                connection.execute(f"INSERT INTO {table} VALUES (?, ?, ?) ON CONFLICT(entity_id) DO UPDATE SET revision=excluded.revision, body=excluded.body", (entity, revision, body))
            connection.commit()
        except BaseException:
            connection.rollback()
            raise
        self.kill_point("after_store_commit")
        self._write_anchor(sequence, head)
        self.event_sequence, self._head = sequence, head
        self.kill_point("after_anchor")

    def _row(self, table: str, entity: str) -> tuple[int, dict[str, Any]] | None:
        if table not in _TABLES:
            raise AccountMutationValidationError
        row = self._connection.execute(f"SELECT revision, body FROM {table} WHERE entity_id=?", (entity,)).fetchone()
        return (row[0], decode(row[1])) if row else None

    def _operation(self, reference: OperationRef) -> tuple[int, dict[str, Any]]:
        reference.__post_init__()
        self._verify()
        if reference.store_incarnation != self.store_incarnation:
            raise AccountMutationConflict
        row = self._row("operations", str(reference.operation_id))
        if row is None or row[0] != reference.revision or row[1].get("admission_denied", False):
            raise AccountMutationConflict
        return row

    def _result(self, operation_id: UUID, revision: int, body: dict[str, Any]) -> AccountMutationResult:
        selector = BrokerSelector(**body["selector"]) if body["selector"] else None
        return AccountMutationResult(OperationRef(operation_id, self.store_incarnation, revision),
                                     MutationPhase(body["phase"]), body["outcome"], selector)

    def get(self, operation_id: UUID) -> AccountMutationResult:
        """Read only an authenticated projection; no stale cache can authorise."""
        require_uuid4(operation_id)
        self._verify()
        row = self._row("operations", str(operation_id))
        if row is None:
            raise AccountMutationConflict
        return self._result(operation_id, *row)

    @staticmethod
    def _audit_update(operation_id: UUID, revision: int, body: dict[str, Any], outcome: str | None = None) -> tuple:
        event_id = str(uuid4())
        public = {key: body[key] for key in ("actor_ref", "principal_kind", "scope", "operation", "selector", "phase")}
        public.update(operation_id=str(operation_id), operation_revision=revision, outcome=outcome or body["outcome"], delivered=False)
        return "outbox", event_id, None, public

    def admit(self, request: AccountMutationRequest) -> AccountMutationResult:
        """Bind UUID4 idempotency and actor receipt atomically before any effect."""
        return self._admit(request)

    def _admit(self, request: AccountMutationRequest, *, updates: tuple = ()) -> AccountMutationResult:
        """The flow owner may include its validated parent/child CAS atomically."""
        request.__post_init__()
        principal = validate_principal(request)
        self._verify()
        metadata = {
            "operation": request.operation.value, "operation_id": str(request.operation_id),
            "selector": asdict(request.selector) if request.selector else None,
            "adapter_id": request.adapter_id, "quarantine": _json_value(asdict(request.quarantine)) if request.quarantine else None,
            "flow_ref": _json_value(asdict(request.flow_ref)) if request.flow_ref else None,
            "flow_action": request.flow_action, "credential_action": request.credential_action,
            "authorities": _json_value(asdict(request.authorities)), "actor_ref": principal.actor_ref,
            "session_binding": principal.session_binding, "principal_kind": type(principal).__name__,
            "scope": list(principal.scopes), "claim_ref": principal.claim_ref,
        }
        digest = self._mac("account-request/v1", [metadata, request.private_input.hex()], pepper=True)
        existing = self._connection.execute("SELECT entity_id, revision, body FROM operations WHERE json_extract(body, '$.idempotency_key')=?", (request.idempotency_key,)).fetchone()
        if existing:
            operation_id, revision, encoded = existing
            body = decode(encoded)
            if not hmac.compare_digest(body["request_mac"], digest):
                self._write([self._audit_update(UUID(operation_id), revision, body, "conflict")])
                raise AccountMutationConflict
            return self._result(UUID(operation_id), revision, body)
        if self._row("operation_tombstones", str(request.operation_id)):
            raise AccountMutationConflict
        if request.operation.value == "complete_auth_flow":
            child = self._row("auth_children", str(request.operation_id))
            if (child is None or child[1]["state"] != "allocated" or request.flow_ref is None
                    or child[1]["flow_id"] != str(request.flow_ref.flow_id)
                    or not any(table == "auth_children" and entity == str(request.operation_id)
                               for table, entity, _revision, _body in updates)):
                raise AccountMutationConflict
        denied = False
        try:
            self._require_unretired(request)
        except AccountMutationConflict:
            denied = True
        body = {**metadata, "idempotency_key": request.idempotency_key, "request_mac": digest,
                "phase": "prepared", "outcome": "conflict" if denied else "pending", "candidate": None,
                "admission_denied": denied,
                "manifest": None, "source_retired": False, "created_at": int(time.time())}
        self._write([
            ("operations", str(request.operation_id), None, body),
            ("operation_tombstones", str(request.operation_id), None, {"operation_id": str(request.operation_id), "present": True}),
            self._audit_update(request.operation_id, 1, body),
            *(updates if not denied else ()),
        ])
        if denied:
            raise AccountMutationConflict
        return self._result(request.operation_id, 1, body)

    def _require_unretired(self, request: AccountMutationRequest) -> None:
        for _entity, _revision, encoded in self._connection.execute("SELECT entity_id, revision, body FROM retirements"):
            owner = decode(encoded)
            if not owner["present"]:
                continue
            if (request.flow_ref is not None and str(request.flow_ref.flow_id) == owner["flow_id"]
                    and str(request.operation_id) == owner["current_child"]):
                continue
            adapter = request.selector.adapter_id if request.selector else request.adapter_id
            targets = [asdict(v.selector) for v in request.authorities.registry_versions]
            if request.selector is not None:
                targets = [asdict(request.selector)]
            if (owner["adapter_wide"] and adapter == owner["adapter_id"]) or any(
                target in owner["selectors"] for target in targets
            ):
                raise AccountMutationConflict

    def record_route_attempt(self, attempt: object) -> None:
        """Persist pre-domain failure facts without inventing an account receipt."""
        from .account_mutation_contracts import RouteMutationAttempt

        if type(attempt) is not RouteMutationAttempt:
            raise AccountMutationValidationError
        attempt.__post_init__()
        self._write([("route_attempts", str(attempt.attempt_id), None, {"reason": attempt.reason})])

    def advance(self, reference: OperationRef, phase: MutationPhase) -> AccountMutationResult:
        """CAS one approved phase; invalid transitions never change a receipt."""
        revision, body = self._operation(reference)
        if type(phase) is not MutationPhase or phase not in _TRANSITIONS.get(MutationPhase(body["phase"]), set()):
            raise AccountMutationConflict
        if phase is MutationPhase.CANDIDATE_STAGED and body["candidate"] is None:
            raise AccountMutationConflict
        if phase is MutationPhase.DURABLE_COMMIT_PREPARED and body["manifest"] is None:
            raise AccountMutationConflict
        if phase is MutationPhase.DURABLE_COMMITTED and body.get("completed_steps", []) != body["manifest"]["steps"]:
            raise AccountMutationConflict
        if phase is MutationPhase.SOURCE_RETIRED and not body.get("source_marker_observed"):
            raise AccountMutationConflict
        if phase is MutationPhase.REGISTRY_PUBLISHED and body["manifest"].get("source_retirement") and not body["source_retired"]:
            raise AccountMutationConflict
        if phase is MutationPhase.ROUTER_REBUILT and body["source_retired"] and body["phase"] != "facade_published":
            raise AccountMutationConflict
        body["phase"] = phase.value
        if phase in _TERMINAL:
            body["outcome"] = "success" if phase in {MutationPhase.COMMITTED, MutationPhase.COMMITTED_DISCONNECTED} else phase.value
        if phase is MutationPhase.SOURCE_RETIRED:
            body["source_retired"] = True
        self._write([("operations", str(reference.operation_id), revision, body), self._audit_update(reference.operation_id, revision + 1, body)])
        return self._result(reference.operation_id, revision + 1, body)

    def authority_snapshot(self, reference: OperationRef) -> dict[str, Any]:
        """Return the frozen non-secret expectations, never resnapshot on retry."""
        return self._operation(reference)[1]["authorities"]

    def prepare_commit(self, reference: OperationRef, manifest: dict[str, Any]) -> AccountMutationResult:
        """Persist complete desired-state generations before the first CAS."""
        revision, body = self._operation(reference)
        if body["phase"] not in {"prepared", "router_drained", "candidate_staged"} or body["manifest"] is not None:
            raise AccountMutationConflict
        required = {"operation_id", "steps", "expected_authorities", "intended_workspace",
                    "intended_credentials", "touched_selectors", "prior_snapshot", "source_retirement"}
        if type(manifest) is not dict or set(manifest) != required:
            raise AccountMutationValidationError
        # Freeze before validation; no caller-owned mutable mapping is retained.
        manifest = decode(canonical(manifest))
        if manifest["operation_id"] != str(reference.operation_id) or manifest["expected_authorities"] != body["authorities"]:
            raise AccountMutationConflict
        steps = manifest["steps"]
        allowed = ["workspace_committed", "vault_committed", "projection_committed"]
        orders = [allowed]
        if (body["principal_kind"] == "OpenAlgoMigrationPrincipal" and body["operation"] == "connect"
                and body["selector"] == {"adapter_id": "openalgo", "account_id": "default"}):
            orders.append(["vault_committed", "workspace_committed", "projection_committed"])
        if type(steps) is not list or not any(steps == [phase for phase in order if phase in steps] for order in orders):
            raise AccountMutationValidationError
        touched = [BrokerSelector(**value) for value in manifest["touched_selectors"]]
        if not touched or touched != sorted(set(touched)):
            raise AccountMutationValidationError
        expected = body["authorities"]
        if any(asdict(selector) not in [v["selector"] for v in expected["credential_versions"]] for selector in touched):
            raise AccountMutationConflict
        intended_workspace = manifest["intended_workspace"]
        expected_workspace = expected["workspace_version"]
        if "workspace_committed" in steps:
            if type(intended_workspace) is not dict or set(intended_workspace) != {"instance_id", "generation"}:
                raise AccountMutationValidationError
            require_uuid4(UUID(intended_workspace["instance_id"]))
            require_revision(intended_workspace["generation"])
            if expected_workspace is not None:
                if (intended_workspace["instance_id"] != expected_workspace["instance_id"]
                        or intended_workspace["generation"] != expected_workspace["generation"] + 1):
                    raise AccountMutationConflict
            elif intended_workspace["generation"] != 1:
                raise AccountMutationConflict
        elif intended_workspace != expected_workspace:
            raise AccountMutationConflict
        credentials = manifest["intended_credentials"]
        if type(credentials) is not list:
            raise AccountMutationValidationError
        intended_selectors = []
        for value in credentials:
            if type(value) is not dict or set(value) != {"selector", "vault_incarnation", "generation"}:
                raise AccountMutationValidationError
            selector = BrokerSelector(**value["selector"])
            intended_selectors.append(selector)
            previous = next((v for v in expected["credential_versions"] if v["selector"] == value["selector"]), None)
            if previous is None or value["vault_incarnation"] != expected["vault_incarnation"]:
                raise AccountMutationConflict
            increment = int("vault_committed" in steps and selector in touched)
            if require_revision(value["generation"], unseen=True) != previous["generation"] + increment:
                raise AccountMutationConflict
        if intended_selectors != [BrokerSelector(**v["selector"]) for v in expected["credential_versions"]]:
            raise AccountMutationConflict
        source = manifest["source_retirement"]
        if source is not None:
            if type(source) is not dict or set(source) != {"operation_id", "source_incarnation", "generation"}:
                raise AccountMutationValidationError
            require_uuid4(UUID(source["source_incarnation"]))
            require_revision(source["generation"])
            if source["operation_id"] != str(reference.operation_id):
                raise AccountMutationConflict
        if manifest["prior_snapshot"] is not None:
            self._verify_prior(reference, manifest["prior_snapshot"])
        body["manifest"] = manifest
        body["completed_steps"] = []
        body["phase"] = "durable_commit_prepared"
        self._write([("operations", str(reference.operation_id), revision, body), self._audit_update(reference.operation_id, revision + 1, body)])
        return self._result(reference.operation_id, revision + 1, body)

    def commit_step(
        self, reference: OperationRef, phase: MutationPhase, *,
        observe: Callable[[], str], apply: Callable[[], None],
    ) -> AccountMutationResult:
        """A trusted adapter compares frozen expected/intended authority versions.

        ``observe`` returns expected/intended/diverged after its exact CAS read.
        Already-intended authority is recorded without applying it again. The
        adapter must make ``apply`` an exact expected-version CAS; a caller's
        assertion is never a production authority adapter.
        """
        revision, body = self._operation(reference)
        manifest = body["manifest"]
        if manifest is None or body["source_retired"] or phase.value not in manifest["steps"]:
            raise AccountMutationConflict
        done = body["completed_steps"]
        if phase.value in done:
            return self._result(reference.operation_id, revision, body)
        if manifest["steps"][len(done)] != phase.value:
            raise AccountMutationConflict
        state = observe()
        if state == "expected":
            require_operation_lock(self.token, installation=self.installation)
            apply()
            self.kill_point("after_" + phase.value.removesuffix("ted"))
        elif state != "intended":
            self.record_outcome(reference, "conflict")
            raise AccountMutationConflict
        # The adapter's exact CAS is the write proof. Recovery obtains fresh
        # ``observe`` evidence before entering this same step.
        body["completed_steps"] = [*done, phase.value]
        body["phase"] = phase.value
        self._write([("operations", str(reference.operation_id), revision, body), self._audit_update(reference.operation_id, revision + 1, body)])
        return self._result(reference.operation_id, revision + 1, body)

    def retire_source(
        self, reference: OperationRef, *, observe: Callable[[], dict[str, Any] | None], retire: Callable[[], None],
    ) -> AccountMutationResult:
        """Canonical commit precedes an exact operation-owned fsynced tombstone."""
        revision, body = self._operation(reference)
        if body["source_retired"]:
            return self._result(reference.operation_id, revision, body)
        if body["phase"] != "durable_committed" or body["manifest"]["source_retirement"] is None:
            raise AccountMutationConflict
        expected_marker = body["manifest"]["source_retirement"]
        observed = observe()
        if observed is None:
            self.kill_point("before_source_commit")
            require_operation_lock(self.token, installation=self.installation)
            retire()
            self.kill_point("after_source_commit")
            observed = observe()
        if observed != expected_marker:
            self.record_outcome(reference, "conflict")
            raise AccountMutationConflict
        body["source_marker_observed"] = expected_marker
        body["source_retired"] = True
        body["phase"] = "source_retired"
        self._write([("operations", str(reference.operation_id), revision, body), self._audit_update(reference.operation_id, revision + 1, body)])
        self.kill_point("after_source_retired_fsync")
        return self._result(reference.operation_id, revision + 1, body)

    def publish(
        self, reference: OperationRef, phase: MutationPhase, publish: Callable[[], None],
    ) -> AccountMutationResult:
        """Trusted idempotent registry/facade/router publication after durability."""
        _, body = self._operation(reference)
        if phase not in {MutationPhase.REGISTRY_PUBLISHED, MutationPhase.FACADE_PUBLISHED, MutationPhase.ROUTER_REBUILT}:
            raise AccountMutationValidationError
        if phase not in _TRANSITIONS.get(MutationPhase(body["phase"]), set()):
            raise AccountMutationConflict
        if body["manifest"].get("source_retirement") and not body["source_retired"]:
            raise AccountMutationConflict
        if phase is MutationPhase.ROUTER_REBUILT and body["source_retired"] and body["phase"] != "facade_published":
            raise AccountMutationConflict
        require_operation_lock(self.token, installation=self.installation)
        publish()
        self.kill_point("after_" + phase.value)
        return self.advance(reference, phase)

    def record_outcome(self, reference: OperationRef, outcome: str) -> AccountMutationResult:
        """Advance a typed redacted outcome without erasing the recovery phase."""
        if outcome not in {"conflict", "internal_failure", "partial_batch"}:
            raise AccountMutationValidationError
        revision, body = self._operation(reference)
        body["outcome"] = outcome
        self._write([("operations", str(reference.operation_id), revision, body), self._audit_update(reference.operation_id, revision + 1, body)])
        return self._result(reference.operation_id, revision + 1, body)

    def stage_prior_snapshot(self, reference: OperationRef, plaintext: bytes) -> dict[str, Any]:
        """Encrypt transaction-owned prior material before a desired-state commit."""
        _, body = self._operation(reference)
        if body["manifest"] is not None or body["phase"] not in {"prepared", "router_drained", "candidate_staged"}:
            raise AccountMutationConflict
        if type(plaintext) is not bytes or not plaintext or len(plaintext) > 64 * 1024:
            raise AccountMutationValidationError
        name = f"prior-{reference.operation_id}.json"
        if self._directory.exists(name):
            raise AccountMutationConflict
        envelope = {"operation_id": str(reference.operation_id), "store_incarnation": str(self.store_incarnation),
                    "ciphertext": self._cipher.encrypt(plaintext).decode("ascii")}
        envelope["mac"] = self._mac("account-prior/v1", envelope)
        self._directory.write_text(name, canonical(envelope))
        return {"name": name, "mac": envelope["mac"]}

    def _verify_prior(self, reference: OperationRef, expected: dict[str, Any]) -> bytes:
        if type(expected) is not dict or set(expected) != {"name", "mac"} or expected["name"] != f"prior-{reference.operation_id}.json":
            raise AccountMutationValidationError
        envelope = decode(self._directory.read_text(expected["name"], max_bytes=128 * 1024))
        mac = envelope.pop("mac")
        if (envelope.get("operation_id") != str(reference.operation_id)
                or envelope.get("store_incarnation") != str(self.store_incarnation)
                or mac != expected["mac"] or not hmac.compare_digest(mac, self._mac("account-prior/v1", envelope))):
            raise AccountRecoveryUnavailable
        return self._cipher.decrypt(envelope["ciphertext"].encode("ascii"))

    def invoke_external(self, reference: OperationRef, invoke: Callable[[], bytes]) -> AccountMutationResult:
        """At most once; returned credentials are encrypted only after invocation."""
        revision, body = self._operation(reference)
        child = self._row("auth_children", str(reference.operation_id))
        if child is not None:
            parent = self._row("auth_flows", child[1]["flow_id"])
            if (child[1]["state"] != "claimed" or parent is None or parent[1]["state"] != "completing"
                    or parent[1]["current_child"] != str(reference.operation_id)
                    or parent[1]["lease_released"] or parent[1]["expires_at"] <= int(time.time())):
                raise AccountMutationConflict
        phase = MutationPhase(body["phase"])
        if phase in _TERMINAL or phase is MutationPhase.CANDIDATE_STAGED:
            return self._result(reference.operation_id, revision, body)
        if phase is MutationPhase.EXTERNAL_INVOKED:
            return self.recover_invocation(reference)
        result = self._result(reference.operation_id, revision, body)
        if phase is MutationPhase.ROUTER_DRAINED:
            result = self.advance(result.reference, MutationPhase.EXTERNAL_INVOCATION_PREPARED)
        result = self.advance(result.reference, MutationPhase.EXTERNAL_INVOKED)
        self.kill_point("before_external_invocation")
        require_operation_lock(self.token, installation=self.installation)
        try:
            plaintext = invoke()
            if type(plaintext) is not bytes or not plaintext or len(plaintext) > 64 * 1024:
                raise ValueError
        except ProviderRejected:
            return self.advance(result.reference, MutationPhase.PROVIDER_REJECTED)
        except Exception:
            self.kill_point("external_unknown")
            return self.advance(result.reference, MutationPhase.EXTERNAL_UNKNOWN)
        return self._stage_candidate(result.reference, plaintext)

    def _candidate_name(self, operation_id: UUID) -> str:
        return f"candidate-{require_uuid4(operation_id)}.json"

    def _stage_candidate(self, reference: OperationRef, plaintext: bytes) -> AccountMutationResult:
        revision, body = self._operation(reference)
        if body["phase"] != "external_invoked":
            raise AccountMutationConflict
        name = self._candidate_name(reference.operation_id)
        if self._directory.exists(name):
            raise AccountRecoveryUnavailable
        envelope = {"schema": 1, "operation_id": str(reference.operation_id),
                    "store_incarnation": str(self.store_incarnation), "invocation_revision": revision,
                    "ciphertext": self._cipher.encrypt(plaintext).decode("ascii")}
        envelope["mac"] = self._mac("account-candidate/v1", envelope)
        self._directory.write_text(name, canonical(envelope))
        self.kill_point("after_candidate_fsync")
        body["candidate"] = {"name": name, "mac": envelope["mac"], "invocation_revision": revision}
        body["phase"] = "candidate_staged"
        self._write([("operations", str(reference.operation_id), revision, body), self._audit_update(reference.operation_id, revision + 1, body)])
        return self._result(reference.operation_id, revision + 1, body)

    def _read_envelope(self, operation_id: UUID, invocation_revision: int) -> dict[str, Any]:
        envelope = decode(self._directory.read_text(self._candidate_name(operation_id), max_bytes=128 * 1024))
        mac = envelope.pop("mac")
        if (
            set(envelope) != {"schema", "operation_id", "store_incarnation", "invocation_revision", "ciphertext"}
            or envelope["operation_id"] != str(operation_id) or envelope["store_incarnation"] != str(self.store_incarnation)
            or envelope["invocation_revision"] != invocation_revision
            or not hmac.compare_digest(mac, self._mac("account-candidate/v1", envelope))
        ):
            raise AccountRecoveryUnavailable
        envelope["mac"] = mac
        return envelope

    def read_candidate(self, reference: OperationRef) -> bytes:
        """Private encrypted material for the trusted canonical vault adapter."""
        _, body = self._operation(reference)
        candidate = body["candidate"]
        if candidate is None:
            raise AccountMutationConflict
        try:
            envelope = self._read_envelope(reference.operation_id, candidate["invocation_revision"])
            if not hmac.compare_digest(candidate["mac"], envelope["mac"]):
                raise AccountRecoveryUnavailable
            return self._cipher.decrypt(envelope["ciphertext"].encode("ascii"))
        except Exception:
            raise AccountRecoveryUnavailable from None

    def recover_invocation(self, reference: OperationRef) -> AccountMutationResult:
        """Never exchange twice; only an authenticated fsynced candidate resumes."""
        revision, body = self._operation(reference)
        if body["phase"] != "external_invoked":
            return self._result(reference.operation_id, revision, body)
        if not self._directory.exists(self._candidate_name(reference.operation_id)):
            return self.advance(reference, MutationPhase.EXTERNAL_UNKNOWN)
        try:
            envelope = self._read_envelope(reference.operation_id, revision)
            self._cipher.decrypt(envelope["ciphertext"].encode("ascii"))
        except Exception:
            raise AccountRecoveryUnavailable from None
        body["candidate"] = {"name": self._candidate_name(reference.operation_id), "mac": envelope["mac"], "invocation_revision": revision}
        body["phase"] = "candidate_staged"
        self._write([("operations", str(reference.operation_id), revision, body), self._audit_update(reference.operation_id, revision + 1, body)])
        return self._result(reference.operation_id, revision + 1, body)

    def pending_audit(self) -> tuple[AccountAuditRecord, ...]:
        """Return only the public allowlist; outage cannot discard these rows."""
        self._verify()
        records = []
        for entity, _revision, encoded in self._connection.execute("SELECT entity_id, revision, body FROM outbox ORDER BY rowid"):
            body = decode(encoded)
            if not body["delivered"]:
                records.append(AccountAuditRecord(
                    UUID(entity), UUID(body["operation_id"]), self.store_incarnation,
                    body["operation_revision"], body["actor_ref"], body["principal_kind"], tuple(body["scope"]),
                    body["operation"], BrokerSelector(**body["selector"]) if body["selector"] else None,
                    MutationPhase(body["phase"]), body["outcome"],
                ))
        return tuple(records)

    def replay_audit(self, sink: Callable[[AccountAuditRecord], None]) -> int:
        """Sink deduplicates event_id; failed delivery retains the durable item."""
        count = 0
        for event in self.pending_audit():
            try:
                sink(event)
            except Exception:
                break
            revision, body = self._row("outbox", str(event.event_id))
            body["delivered"] = True
            self._write([("outbox", str(event.event_id), revision, body)])
            count += 1
        return count

    def checkpoint(self) -> None:
        """Flush the authenticated store for owner-controlled maintenance."""
        self._verify()
        self._connection.execute("PRAGMA wal_checkpoint(TRUNCATE)")
