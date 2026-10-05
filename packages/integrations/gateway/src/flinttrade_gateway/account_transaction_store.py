"""Owner-bound encrypted operation evidence within the existing credential vault.

The workspace participant decides commitment. This store applies that exact
witness once; it never contacts a provider or reconstructs a live session.
"""

from __future__ import annotations

import hashlib
import hmac
import sqlite3
from collections.abc import Callable, Iterator, Mapping
from contextlib import contextmanager
from dataclasses import dataclass, field
from pathlib import Path
from uuid import UUID, uuid4

from flinttrade_core.account_lifecycle_contracts import (
    _TERMINAL,
    ACCOUNT_MAX_OPERATIONS,
    AccountEnrolmentIntent,
    AccountMutationKind,
    AccountMutationReceipt,
    AccountMutationRequest,
    AccountOperationSnapshot,
    AccountOperationStage,
    BrokerAccountWitness,
    _digest,
    _freeze,
    _PrivateValue,
    _reason,
    _request_dict,
    _request_from,
    _thaw,
    _uuid,
    _uuid_from,
    _version_dict,
    _version_from,
    broker_account_digest,
    canonical_account_json,
    parse_account_json,
)
from flinttrade_core.backend_instance import BackendLeaseProof, require_backend_lease_proof
from flinttrade_core.broker_account_audit import AccountMutationAudit
from flinttrade_core.broker_identity import INT64_MAX, BrokerSelector, CredentialVersion
from flinttrade_core.workspace_migrations import (
    BrokerWorkspaceVersion,
    WorkspaceSnapshot,
    WorkspaceVersion,
    broker_workspace_version,
)

from .credentials import _ACCOUNT_AUDIT_SQL, CredentialError, CredentialSelectorState, CredentialStore


class AccountTransactionError(CredentialError):
    """Stable, secret-free refusal of invalid or incoherent account evidence."""

    def __init__(self) -> None:
        super().__init__("account_transaction_unavailable")


class AccountOperationConflict(CredentialError):
    """A retained identity, generation, claim or stage cannot be replaced."""

    def __init__(self) -> None:
        super().__init__("account_operation_conflict")


@dataclass(frozen=True, slots=True)
class _RecoveryMaterial(_PrivateValue):
    """Private, copied/frozen material for the capability-holding coordinator."""

    request: AccountMutationRequest | None = field(repr=False)
    replay_credentials: Mapping[str, object] | None = field(repr=False)
    read_only: bool | None
    before_digest: str | None
    after_digest: str | None


def _receipt_dict(value: AccountMutationReceipt) -> dict:
    return {
        "operation_id": str(value.operation_id),
        "selector": {"adapter_id": value.selector.adapter_id, "account_id": value.selector.account_id},
        "kind": value.kind.value,
        "state": value.state.value,
        "reason": value.reason,
        "credential_version": None
        if value.credential_version is None
        else {
            "vault_incarnation": str(value.credential_version.vault_incarnation),
            "generation": value.credential_version.generation,
        },
        "commit_workspace": None if value.commit_workspace is None else _version_dict(value.commit_workspace),
        "commit_broker_workspace": None
        if value.commit_broker_workspace is None
        else _version_dict(value.commit_broker_workspace),
    }


def _receipt_from(value: dict) -> AccountMutationReceipt:
    selector = BrokerSelector(**value["selector"])
    version = value["credential_version"]
    result = AccountMutationReceipt(
        _uuid_from(value["operation_id"]),
        selector,
        AccountMutationKind(value["kind"]),
        AccountOperationStage(value["state"]),
        value["reason"],
        None
        if version is None
        else CredentialVersion(selector, _uuid_from(version["vault_incarnation"]), version["generation"]),
        None if value["commit_workspace"] is None else _version_from(value["commit_workspace"], WorkspaceVersion),
        None
        if value["commit_broker_workspace"] is None
        else _version_from(value["commit_broker_workspace"], BrokerWorkspaceVersion),
    )
    if _receipt_dict(result) != value:
        raise AccountTransactionError
    return result


def _preflight_terminal_envelopes(request: AccountMutationRequest, body: dict) -> None:
    """Reserve every later retained shape before claiming or authenticating.

    These sizing values never become durable evidence. Maximum counters,
    digests and reasons dominate all future values. False booleans use more
    JSON bytes than true, conservatively covering either abandonment state.
    Private input and replay payloads stay in their separate encrypted cells.
    """
    workspace = WorkspaceVersion(request.expected_workspace.instance_id, INT64_MAX)
    broker_workspace = BrokerWorkspaceVersion(request.expected_workspace.instance_id, INT64_MAX)
    witness = BrokerAccountWitness(
        1,
        request.expected_workspace.instance_id,
        request.expected_credential.vault_incarnation,
        request.operation_id,
        INT64_MAX,
        "0" * 64,
        "f" * 64,
        workspace,
        broker_workspace,
    )
    for state in _TERMINAL:
        committed = state is AccountOperationStage.COMMITTED
        receipt = AccountMutationReceipt(
            request.operation_id,
            request.selector,
            request.kind,
            state,
            None if committed else "r" * 64,
            CredentialVersion(request.selector, request.expected_credential.vault_incarnation, INT64_MAX)
            if committed
            else None,
            workspace if committed else None,
            broker_workspace if committed else None,
        )
        canonical_account_json(
            {
                **body,
                "stage": state.value,
                "witness": witness.to_dict() if committed else None,
                "receipt": _receipt_dict(receipt),
                "abandonment_reason": "r" * 64,
                "before_digest": "0" * 64,
                "after_digest": "f" * 64,
            }
        )



def _ledger_mac(key: bytes, domain: str, *parts: str | bytes | None) -> str:
    result = hmac.new(key, ("account-ledger/v1/" + domain).encode(), hashlib.sha256)
    for part in parts:
        raw = b"" if part is None else part.encode() if type(part) is str else part
        result.update(len(raw).to_bytes(8, "big"))
        result.update(raw)
    return result.hexdigest()


def _operations_digest(conn: sqlite3.Connection, mac: Callable[..., str]) -> str:
    """Bind every retained row, including released receipts and audit acknowledgements.

    Fixed-width identities avoid the JSON envelope's 64 KiB limit at capacity.
    Separate domain tags prevent operation/outbox substitutions.
    """
    parts = []
    for row in conn.execute("SELECT operation_id,mac FROM account_operations ORDER BY operation_id COLLATE BINARY"):
        parts.extend(("operation", row["operation_id"], row["mac"]))
    for row in conn.execute(
        "SELECT operation_id,event_id,mac FROM account_audit_outbox ORDER BY operation_id COLLATE BINARY"
    ):
        parts.extend(("audit", row["operation_id"], row["event_id"], row["mac"]))
    return mac("retained-rows", *parts)


def _audit_event(body: dict, mac: Callable[..., str]) -> AccountMutationAudit:
    source = _operation_snapshot(body)
    if source.state not in _TERMINAL or source.receipt is None:
        raise AccountTransactionError
    incarnation = str(source.expected_credential.vault_incarnation)
    operation_id = str(source.operation_id)
    receipt = source.receipt
    return AccountMutationAudit(
        event_id=UUID(bytes=bytes.fromhex(mac("audit-id", incarnation, operation_id))[:16], version=4),
        operation_ref=mac("audit-operation", incarnation, operation_id),
        selector_ref=mac("audit-selector", incarnation, source.selector.adapter_id, source.selector.account_id),
        actor_ref=mac("audit-actor", incarnation, source.actor.actor),
        session_ref=mac("audit-session", incarnation, source.actor.session_binding),
        kind=source.kind,
        state=source.state,
        expected_credential_generation=source.expected_credential.generation,
        credential_generation=None if receipt.credential_version is None else receipt.credential_version.generation,
        expected_workspace_generation=source.expected_workspace.generation,
        workspace_generation=None if receipt.commit_workspace is None else receipt.commit_workspace.generation,
        expected_broker_generation=source.expected_broker_workspace.generation,
        broker_generation=None if receipt.commit_broker_workspace is None else receipt.commit_broker_workspace.generation,
    )


def _audit_row_mac(row: Mapping, mac: Callable[..., str]) -> str:
    return mac("audit-outbox", row["operation_id"], row["event_id"], row["body"], str(row["delivered"]))


def _ensure_audit_event(conn: sqlite3.Connection, body: dict, mac: Callable[..., str]) -> None:
    event = _audit_event(body, mac)
    operation_id = body["identity"]["operation_id"]
    encoded = canonical_account_json(event.to_dict())
    existing = conn.execute("SELECT * FROM account_audit_outbox WHERE operation_id=?", (operation_id,)).fetchone()
    if existing is not None:
        if existing["body"] != encoded or existing["event_id"] != str(event.event_id):
            raise AccountTransactionError
        return
    row = {"operation_id": operation_id, "event_id": str(event.event_id), "body": encoded, "delivered": 0}
    conn.execute(
        "INSERT INTO account_audit_outbox VALUES(?,?,?,?,?)",
        (operation_id, row["event_id"], encoded, 0, _audit_row_mac(row, mac)),
    )


def _upgrade_account_ledger_v4(credentials: CredentialStore, conn: sqlite3.Connection, incarnation: UUID) -> None:
    """One authenticated schema-3 upgrade inside the vault's owned transaction.

    Migration grants no backend capability and contacts no provider. Legacy
    head acceptance exists only here, never in a runtime schema-4 read.
    """
    row = conn.execute("SELECT * FROM account_store_key").fetchone()
    secret = credentials._decrypt(row)
    if (set(secret) != {"schema", "vault_incarnation", "mac_key"}
            or type(secret["schema"]) is not int or secret["schema"] != 1
            or secret["vault_incarnation"] != str(incarnation)):
        raise AccountTransactionError
    _digest(secret["mac_key"])
    key = bytes.fromhex(secret["mac_key"])

    def mac(domain: str, *parts: str | bytes | None) -> str:
        return _ledger_mac(key, domain, *parts)

    key_storage = (row["salt"], row["encrypted_creds"])
    _validate_ledger(conn, key_storage=key_storage, incarnation=incarnation, mac=mac, legacy=True)
    conn.execute(_ACCOUNT_AUDIT_SQL)
    for operation in conn.execute("SELECT body FROM account_operations").fetchall():
        body = parse_account_json(operation[0])
        if AccountOperationStage(body["stage"]) in _TERMINAL:
            _ensure_audit_event(conn, body, mac)
    head = conn.execute("SELECT body FROM account_store_head").fetchone()
    if head is not None:
        body = canonical_account_json({**parse_account_json(head[0]), "operations_digest": _operations_digest(conn, mac)})
        conn.execute("UPDATE account_store_head SET body=?,mac=? WHERE singleton=1", (body, mac("head", body)))
    _validate_ledger(conn, key_storage=key_storage, incarnation=incarnation, mac=mac)


def _operation_snapshot(body: dict) -> AccountOperationSnapshot:
    identity = _request_from({**body["identity"], "credentials": None})
    return AccountOperationSnapshot(
        identity.operation_id,
        identity.selector,
        identity.kind,
        identity.actor,
        AccountOperationStage(body["stage"]),
        identity.expected_workspace,
        identity.expected_broker_workspace,
        identity.expected_credential,
        None if body["witness"] is None else BrokerAccountWitness.from_dict(body["witness"]),
        None if body["receipt"] is None else _receipt_from(body["receipt"]),
        body["abandoned"],
        body["abandonment_committed"],
        body["abandonment_reason"],
        body["before_digest"],
        body["after_digest"],
        body["workspace_attempted"],
        body["workspace_conflicted"],
    )


def _validate_ledger(
    conn: sqlite3.Connection, *, key_storage: tuple[bytes, bytes], incarnation: UUID,
    mac: Callable[..., str], legacy: bool = False,
) -> None:
    try:
        key = conn.execute("SELECT salt,encrypted_creds FROM account_store_key").fetchone()
        if tuple(key) != key_storage:
            raise AccountTransactionError
        heads = conn.execute("SELECT * FROM account_store_head").fetchall()
        rows = conn.execute("SELECT * FROM account_operations").fetchall()
        outbox = [] if legacy else conn.execute("SELECT * FROM account_audit_outbox").fetchall()
        if not heads:
            if rows or outbox:
                raise AccountTransactionError
            return
        if len(heads) != 1 or not hmac.compare_digest(heads[0]["mac"], mac("head", heads[0]["body"])):
            raise AccountTransactionError
        head = parse_account_json(heads[0]["body"])
        expected = {"intent", "witness", "claim", "operation_count"}
        if not legacy:
            expected.add("operations_digest")
        if set(head) != expected:
            raise AccountTransactionError
        if not legacy and not hmac.compare_digest(head["operations_digest"], _operations_digest(conn, mac)):
            raise AccountTransactionError
        intent = AccountEnrolmentIntent.from_dict(head["intent"])
        if intent.vault_incarnation != incarnation:
            raise AccountTransactionError
        witness = None if head["witness"] is None else BrokerAccountWitness.from_dict(head["witness"])
        if witness is not None and (
            witness.vault_incarnation != intent.vault_incarnation
            or witness.workspace_instance != intent.workspace_instance
        ):
            raise AccountTransactionError
        if (
            type(head["operation_count"]) is not int
            or head["operation_count"] != len(rows)
            or not 0 <= len(rows) <= ACCOUNT_MAX_OPERATIONS
            or (witness is None and rows)
        ):
            raise AccountTransactionError
        snapshots = {}
        for row in rows:
            if not hmac.compare_digest(
                row["mac"],
                mac(
                    "operation",
                    *(
                        row[name]
                        for name in (
                            "operation_id",
                            "body",
                            "request_mac",
                            "private_salt",
                            "private_cipher",
                            "plan_salt",
                            "plan_cipher",
                        )
                    ),
                ),
            ):
                raise AccountTransactionError
            _digest(row["request_mac"])
            body = parse_account_json(row["body"])
            if set(body) != {
                "identity",
                "stage",
                "witness",
                "receipt",
                "abandoned",
                "abandonment_committed",
                "abandonment_reason",
                "before_digest",
                "after_digest",
                "workspace_attempted",
                "workspace_conflicted",
            }:
                raise AccountTransactionError
            snapshot = _operation_snapshot(body)
            if (
                str(snapshot.operation_id) != row["operation_id"]
                or snapshot.expected_workspace.instance_id != intent.workspace_instance
                or snapshot.expected_credential.vault_incarnation != intent.vault_incarnation
            ):
                raise AccountTransactionError
            terminal = snapshot.state in _TERMINAL
            if (row["private_cipher"] is None) != terminal or (row["plan_cipher"] is not None) != (
                snapshot.state is AccountOperationStage.PLAN_READY
            ):
                raise AccountTransactionError
            if snapshot.state is AccountOperationStage.COMMITTED:
                if (
                    snapshot.witness is None
                    or snapshot.receipt.commit_workspace != snapshot.witness.commit_workspace
                    or snapshot.receipt.commit_broker_workspace != snapshot.witness.commit_broker_workspace
                    or snapshot.receipt.credential_version.vault_incarnation != intent.vault_incarnation
                    or snapshot.receipt.credential_version.generation != snapshot.expected_credential.generation + 1
                ):
                    raise AccountTransactionError
            elif snapshot.witness is not None:
                raise AccountTransactionError
            snapshots[row["operation_id"]] = snapshot
        if not legacy:
            events = {}
            for row in outbox:
                if (
                    type(row["delivered"]) is not int or row["delivered"] not in (0, 1)
                    or row["operation_id"] not in snapshots
                    or not hmac.compare_digest(row["mac"], _audit_row_mac(row, mac))
                ):
                    raise AccountTransactionError
                event = AccountMutationAudit.from_dict(parse_account_json(row["body"]))
                source = conn.execute(
                    "SELECT body FROM account_operations WHERE operation_id=?", (row["operation_id"],)
                ).fetchone()
                if str(event.event_id) != row["event_id"] or event != _audit_event(parse_account_json(source[0]), mac):
                    raise AccountTransactionError
                events[row["operation_id"]] = event
            if set(events) != {key for key, snapshot in snapshots.items() if snapshot.state in _TERMINAL}:
                raise AccountTransactionError
        if head["claim"] is not None:
            if type(head["claim"]) is not str or head["claim"] not in snapshots:
                raise AccountTransactionError
        if any(snapshot.state not in _TERMINAL and key != head["claim"] for key, snapshot in snapshots.items()):
            raise AccountTransactionError
        if witness is not None:
            if witness.epoch == 0:
                if witness.operation_id != intent.operation_id or witness.before_digest != intent.before_digest:
                    raise AccountTransactionError
            elif (
                str(witness.operation_id) not in snapshots
                or snapshots[str(witness.operation_id)].witness != witness
            ):
                raise AccountTransactionError
    except Exception:
        raise AccountTransactionError from None


class AccountTransactionStore:
    """Durable single-operation claim and atomic target plan application."""

    def __init__(self, credentials: CredentialStore, *, workspace_path: Path, backend_proof: BackendLeaseProof) -> None:
        if type(credentials) is not CredentialStore:
            raise AccountTransactionError
        self._proof = require_backend_lease_proof(backend_proof)
        self._workspace_path = Path(workspace_path).resolve()
        if self._workspace_path != self._proof.workspace_path:
            raise AccountTransactionError
        self._credentials = credentials
        self._capability = credentials._issue_account_capability(self._proof)
        try:
            with credentials._transaction(_account_capability=self._capability) as conn:
                row = conn.execute("SELECT * FROM account_store_key").fetchone()
                secret = credentials._decrypt(row)
                if (
                    set(secret) != {"schema", "vault_incarnation", "mac_key"}
                    or type(secret["schema"]) is not int
                    or secret["schema"] != 1
                    or secret["vault_incarnation"] != str(credentials._incarnation)
                ):
                    raise AccountTransactionError
                _digest(secret["mac_key"])
                self._key = bytes.fromhex(secret["mac_key"])
                self._key_storage = (row["salt"], row["encrypted_creds"])
                self._validate(conn)
        except Exception:
            raise AccountTransactionError from None

    def __repr__(self) -> str:
        return "<AccountTransactionStore>"

    def __reduce__(self):
        raise TypeError("account_store_not_serialisable")

    def _require_owner(self) -> None:
        require_backend_lease_proof(self._proof)
        if self._proof.workspace_path != self._workspace_path:
            raise AccountTransactionError

    def owner_capability(self, backend_proof: BackendLeaseProof) -> object:
        """Return the sole opaque recovery capability to this exact live owner."""
        self._require_owner()
        if backend_proof is not self._proof:
            raise AccountTransactionError
        return self._capability

    def _require_workspace_capability(self, capability: object, path: Path, backend_proof: BackendLeaseProof) -> None:
        """Validate the narrow workspace participant without exporting credentials."""
        self._require_owner()
        if capability is not self._capability or backend_proof is not self._proof or path != self._workspace_path:
            raise AccountTransactionError

    def current_credential_version(self, capability: object, selector: BrokerSelector) -> CredentialVersion:
        """Read exact selector authority for a short capability-owned callback."""
        self._require_workspace_capability(capability, self._workspace_path, self._proof)
        with self._transaction() as conn:
            return self._credentials._state(conn, selector).version

    def assert_original_credentials(self, capability: object, operation_id: UUID) -> None:
        """Check the retained operation's original vault state before witnessing."""
        self._require_workspace_capability(capability, self._workspace_path, self._proof)
        with self._transaction() as conn:
            row, body, _ = self._active(conn, operation_id)
            request = self._material(row, body).request
            if request is None:
                raise AccountOperationConflict
            self._credentials._expected(conn, request.selector, request.expected_credential)
            self._credentials._check_bump(conn, request.selector)

    @contextmanager
    def _transaction(self, *, write: bool = False) -> Iterator[sqlite3.Connection]:
        self._require_owner()
        with self._credentials._transaction(write=write, _account_capability=self._capability) as conn:
            self._validate(conn)
            yield conn
            self._require_owner()
            self._validate(conn)

    def _mac(self, domain: str, *parts: str | bytes | None) -> str:
        return _ledger_mac(self._key, domain, *parts)

    def _read_head(self, conn: sqlite3.Connection) -> dict | None:
        row = conn.execute("SELECT * FROM account_store_head").fetchone()
        return None if row is None else parse_account_json(row["body"])

    def _write_head(self, conn: sqlite3.Connection, value: dict) -> None:
        body = canonical_account_json({**value, "operations_digest": _operations_digest(conn, self._mac)})
        conn.execute(
            "INSERT INTO account_store_head VALUES(1,?,?) ON CONFLICT(singleton) DO UPDATE SET body=excluded.body,mac=excluded.mac",
            (body, self._mac("head", body)),
        )

    def _row(self, conn: sqlite3.Connection, operation_id: UUID) -> dict:
        _uuid(operation_id)
        row = conn.execute("SELECT * FROM account_operations WHERE operation_id=?", (str(operation_id),)).fetchone()
        if row is None:
            raise AccountOperationConflict
        return dict(row)

    def _save(self, conn: sqlite3.Connection, row: dict, body: dict) -> None:
        row["body"] = canonical_account_json(body)
        row["mac"] = self._mac(
            "operation",
            *(
                row[name]
                for name in (
                    "operation_id",
                    "body",
                    "request_mac",
                    "private_salt",
                    "private_cipher",
                    "plan_salt",
                    "plan_cipher",
                )
            ),
        )
        conn.execute(
            """INSERT INTO account_operations VALUES(?,?,?,?,?,?,?,?) ON CONFLICT(operation_id) DO UPDATE SET
            body=excluded.body,private_salt=excluded.private_salt,private_cipher=excluded.private_cipher,
            plan_salt=excluded.plan_salt,plan_cipher=excluded.plan_cipher,mac=excluded.mac""",
            tuple(
                row[name]
                for name in (
                    "operation_id",
                    "body",
                    "request_mac",
                    "private_salt",
                    "private_cipher",
                    "plan_salt",
                    "plan_cipher",
                    "mac",
                )
            ),
        )

        if AccountOperationStage(body["stage"]) in _TERMINAL:
            _ensure_audit_event(conn, body, self._mac)
        head = self._read_head(conn)
        if head is not None:
            self._write_head(conn, head)

    def _snapshot(self, body: dict) -> AccountOperationSnapshot:
        return _operation_snapshot(body)

    def _validate(self, conn: sqlite3.Connection) -> None:
        _validate_ledger(
            conn, key_storage=self._key_storage, incarnation=self._credentials._incarnation, mac=self._mac,
        )

    def prepare_enrolment(self, workspace: WorkspaceSnapshot) -> AccountEnrolmentIntent:
        self._require_owner()
        if type(workspace) is not WorkspaceSnapshot or workspace.version is None:
            raise AccountTransactionError
        intent = AccountEnrolmentIntent(
            workspace.version.instance_id,
            self._credentials._incarnation,
            uuid4(),
            workspace.version,
            broker_workspace_version(workspace),
            broker_account_digest(workspace),
        )
        with self._transaction(write=True) as conn:
            current = self._read_head(conn)
            if current is not None:
                original = AccountEnrolmentIntent.from_dict(current["intent"])
                if (
                    intent.workspace_instance != original.workspace_instance
                    or intent.expected_broker_workspace != original.expected_broker_workspace
                    or intent.before_digest != original.before_digest
                ):
                    raise AccountOperationConflict
                return original
            if workspace.config.get("_broker_account_store") is not None:
                raise AccountOperationConflict
            conn.execute("UPDATE credential_vault_metadata SET account_enrolled=1 WHERE singleton=1")
            self._write_head(conn, {"intent": intent.to_dict(), "witness": None, "claim": None, "operation_count": 0})
            return intent

    def complete_enrolment(self, witness: BrokerAccountWitness) -> None:
        if type(witness) is not BrokerAccountWitness:
            raise AccountTransactionError
        witness.__post_init__()
        with self._transaction(write=True) as conn:
            head = self._read_head(conn)
            if head is None:
                raise AccountOperationConflict
            if head["witness"] is not None:
                if BrokerAccountWitness.from_dict(head["witness"]) != witness:
                    raise AccountOperationConflict
                return
            intent = AccountEnrolmentIntent.from_dict(head["intent"])
            if (
                witness.operation_id != intent.operation_id
                or witness.epoch != 0
                or witness.workspace_instance != intent.workspace_instance
                or witness.vault_incarnation != intent.vault_incarnation
                or witness.before_digest != intent.before_digest
                or witness.after_digest != intent.before_digest
                or witness.commit_workspace.generation <= intent.expected_workspace.generation
                or witness.commit_broker_workspace != intent.expected_broker_workspace
            ):
                raise AccountOperationConflict
            head["witness"] = witness.to_dict()
            self._write_head(conn, head)

    def head(self) -> BrokerAccountWitness | None:
        with self._transaction() as conn:
            head = self._read_head(conn)
            return None if head is None or head["witness"] is None else BrokerAccountWitness.from_dict(head["witness"])

    def admit(self, request: AccountMutationRequest) -> AccountOperationSnapshot:
        if type(request) is not AccountMutationRequest:
            raise AccountTransactionError
        request.__post_init__()
        complete = canonical_account_json(_request_dict(request))
        body = {
            "identity": _request_dict(request, private=False),
            "stage": AccountOperationStage.ADMITTED.value,
            "witness": None,
            "receipt": None,
            "abandoned": False,
            "abandonment_committed": False,
            "abandonment_reason": None,
            "before_digest": None,
            "after_digest": None,
            "workspace_attempted": False,
            "workspace_conflicted": False,
        }
        _preflight_terminal_envelopes(request, body)
        request_mac = self._mac("request", complete)
        with self._transaction(write=True) as conn:
            head = self._read_head(conn)
            if head is None or head["witness"] is None:
                raise AccountOperationConflict
            existing = conn.execute(
                "SELECT * FROM account_operations WHERE operation_id=?", (str(request.operation_id),)
            ).fetchone()
            if existing is not None:
                if not hmac.compare_digest(existing["request_mac"], request_mac):
                    raise AccountOperationConflict
                return self._snapshot(parse_account_json(existing["body"]))
            witness = BrokerAccountWitness.from_dict(head["witness"])
            if (
                head["claim"] is not None
                or head["operation_count"] >= ACCOUNT_MAX_OPERATIONS
                or witness.epoch == INT64_MAX
                or request.expected_workspace.generation == INT64_MAX
                or request.operation_id == AccountEnrolmentIntent.from_dict(head["intent"]).operation_id
                or request.expected_workspace.instance_id != witness.workspace_instance
                or request.expected_workspace.generation < witness.commit_workspace.generation
                or request.expected_broker_workspace != witness.commit_broker_workspace
            ):
                raise AccountOperationConflict
            self._credentials._expected(conn, request.selector, request.expected_credential)
            self._credentials._check_bump(conn, request.selector)
            self._credentials._admit_new_component(conn, request.selector)
            salt, cipher = self._credentials._encrypt({"request": _request_dict(request)})
            row = {
                "operation_id": str(request.operation_id),
                "request_mac": request_mac,
                "private_salt": salt,
                "private_cipher": cipher,
                "plan_salt": None,
                "plan_cipher": None,
            }
            self._save(conn, row, body)
            head["claim"] = str(request.operation_id)
            head["operation_count"] += 1
            self._write_head(conn, head)
            return self._snapshot(body)

    def operation(self, operation_id: UUID) -> AccountOperationSnapshot:
        with self._transaction() as conn:
            return self._snapshot(parse_account_json(self._row(conn, operation_id)["body"]))

    def existing_request(self, request: AccountMutationRequest) -> AccountOperationSnapshot | None:
        """Compare a retained keyed identity without admission or coherence writes."""
        if type(request) is not AccountMutationRequest:
            raise AccountTransactionError
        request.__post_init__()
        request_mac = self._mac("request", canonical_account_json(_request_dict(request)))
        with self._transaction() as conn:
            row = conn.execute(
                "SELECT * FROM account_operations WHERE operation_id=?", (str(request.operation_id),)
            ).fetchone()
            if row is None:
                return None
            if not hmac.compare_digest(row["request_mac"], request_mac):
                raise AccountOperationConflict
            return self._snapshot(parse_account_json(row["body"]))

    def native_state(self, selector: BrokerSelector) -> CredentialSelectorState:
        """Read exact provenance under this store's live backend authority."""
        self._require_owner()
        return self._credentials.selector_state(selector)

    def native_credentials(self, selector: BrokerSelector, expected: CredentialVersion) -> dict[str, object]:
        """Replay only recognised managed native material at its captured version."""
        self._require_owner()
        before = self._credentials.selector_state(selector)
        if (selector.adapter_id == "openalgo" or not before.credential_present
                or before.origin != "managed" or before.version != expected):
            raise AccountOperationConflict
        value = self._credentials.retrieve_for(selector.adapter_id, selector.account_id)
        if self._credentials.selector_state(selector) != before:
            raise AccountOperationConflict
        self._require_owner()
        return value

    def _active(self, conn: sqlite3.Connection, operation_id: UUID) -> tuple[dict, dict, dict]:
        row = self._row(conn, operation_id)
        body = parse_account_json(row["body"])
        head = self._read_head(conn)
        if head["claim"] != str(operation_id):
            raise AccountOperationConflict
        return row, body, head

    def mark_authentication_started(self, operation_id: UUID) -> None:
        with self._transaction(write=True) as conn:
            row, body, _ = self._active(conn, operation_id)
            if (
                body["stage"] != AccountOperationStage.ADMITTED.value
                or body["abandoned"]
                or body["identity"]["kind"] == AccountMutationKind.REMOVE.value
            ):
                raise AccountOperationConflict
            body["stage"] = AccountOperationStage.AUTHENTICATION_STARTED.value
            self._save(conn, row, body)

    def stage_plan(
        self,
        operation_id: UUID,
        *,
        replay_credentials: Mapping[str, object] | None,
        read_only: bool | None,
        before_digest: str,
        after_digest: str,
    ) -> None:
        _digest(before_digest)
        _digest(after_digest)
        if replay_credentials is not None and not isinstance(replay_credentials, Mapping):
            raise AccountTransactionError
        candidate = {"replay_credentials": _thaw(_freeze(replay_credentials)), "read_only": read_only}
        canonical_account_json(candidate)
        with self._transaction(write=True) as conn:
            row, body, head = self._active(conn, operation_id)
            remove = body["identity"]["kind"] == AccountMutationKind.REMOVE.value
            expected_stage = AccountOperationStage.ADMITTED if remove else AccountOperationStage.AUTHENTICATION_STARTED
            if (
                body["stage"] != expected_stage.value
                or body["abandoned"]
                or before_digest != BrokerAccountWitness.from_dict(head["witness"]).after_digest
                or (remove and (replay_credentials is not None or read_only is not None))
                or (not remove and (replay_credentials is None or type(read_only) is not bool))
            ):
                raise AccountOperationConflict
            row["plan_salt"], row["plan_cipher"] = self._credentials._encrypt(candidate)
            body.update(
                stage=AccountOperationStage.PLAN_READY.value, before_digest=before_digest, after_digest=after_digest
            )
            self._save(conn, row, body)

    def mark_workspace_attempted(self, operation_id: UUID) -> None:
        """Persist the sole CAS-dispatch phase before any workspace write."""
        with self._transaction(write=True) as conn:
            row, body, _ = self._active(conn, operation_id)
            if (
                body["stage"] != AccountOperationStage.PLAN_READY.value
                or body["abandoned"]
                or body["workspace_conflicted"]
            ):
                raise AccountOperationConflict
            if body["workspace_attempted"]:
                return
            body["workspace_attempted"] = True
            self._save(conn, row, body)

    def mark_workspace_conflicted(self, operation_id: UUID) -> None:
        """Latch uncertainty/publication refusal without discarding a plan.

        A retained committed operation may also be fenced after claim release;
        this never changes its receipt, head or credential authority.
        """
        with self._transaction(write=True) as conn:
            row = self._row(conn, operation_id)
            body = parse_account_json(row["body"])
            if (
                not body["workspace_attempted"]
                or body["stage"] not in (AccountOperationStage.PLAN_READY.value, AccountOperationStage.COMMITTED.value)
            ):
                raise AccountOperationConflict
            if body["stage"] == AccountOperationStage.PLAN_READY.value:
                self._active(conn, operation_id)
            if body["workspace_conflicted"]:
                return
            body["workspace_conflicted"] = True
            self._save(conn, row, body)

    def active_operation(self, capability: object) -> AccountOperationSnapshot | None:
        """Discover the retained durable claim without exposing private payload."""
        self._require_owner()
        if capability is not self._capability:
            raise AccountTransactionError
        with self._transaction() as conn:
            head = self._read_head(conn)
            if head is None or head["claim"] is None:
                return None
            return self._snapshot(parse_account_json(self._row(conn, _uuid_from(head["claim"]))["body"]))

    def _pending_audit_sources(
        self, capability: object, limit: int,
    ) -> tuple[tuple[AccountMutationAudit, str, str], ...]:
        self._require_owner()
        if capability is not self._capability or type(limit) is not int or not 1 <= limit <= ACCOUNT_MAX_OPERATIONS:
            raise AccountTransactionError
        with self._transaction() as conn:
            rows = conn.execute(
                """SELECT audit.body,audit.operation_id,operation.mac AS source_mac
                FROM account_audit_outbox AS audit JOIN account_operations AS operation
                ON operation.operation_id=audit.operation_id WHERE audit.delivered=0
                ORDER BY audit.operation_id COLLATE BINARY LIMIT ?""", (limit,),
            ).fetchall()
            return tuple(
                (AccountMutationAudit.from_dict(parse_account_json(row["body"])), row["operation_id"], row["source_mac"])
                for row in rows
            )

    def pending_audit_events(self, capability: object, limit: int = 100) -> tuple[AccountMutationAudit, ...]:
        """Read immutable, vault-bound redacted terminal events without dispatching work."""
        return tuple(event for event, _, _ in self._pending_audit_sources(capability, limit))

    def export_audit_events(
        self, capability: object, sink: Callable[[AccountMutationAudit], UUID], limit: int = 100,
    ) -> int:
        """Deliver outside locks; acknowledge only the exact unchanged owned source.

        Sink failures or unverified acknowledgements retain pending evidence.
        A crash after delivery retries the same stable ID; the sink is responsible
        for verifying an idempotent durable receipt before returning that UUID.
        No authentication, credential mutation or claim disposition is replayed.
        """
        if not callable(sink):
            raise AccountTransactionError
        pending = self._pending_audit_sources(capability, limit)
        acknowledged = 0
        for event, operation_id, source_mac in pending:
            self._require_owner()
            try:
                acknowledgement = sink(event)
                _uuid(acknowledgement)
                if acknowledgement != event.event_id:
                    continue
            except Exception:
                continue
            # Re-enter only after the arbitrary sink has returned. Both the
            # backend owner and the authenticated ledger are revalidated here.
            with self._transaction(write=True) as conn:
                operation = self._row(conn, _uuid_from(operation_id))
                row = conn.execute(
                    "SELECT * FROM account_audit_outbox WHERE operation_id=?", (operation_id,),
                ).fetchone()
                if (
                    row is None or not hmac.compare_digest(operation["mac"], source_mac)
                    or AccountMutationAudit.from_dict(parse_account_json(row["body"])) != event
                    or row["event_id"] != str(event.event_id)
                ):
                    raise AccountTransactionError
                if row["delivered"]:
                    continue
                delivered = {**dict(row), "delivered": 1}
                conn.execute(
                    "UPDATE account_audit_outbox SET delivered=1,mac=? WHERE operation_id=?",
                    (_audit_row_mac(delivered, self._mac), operation_id),
                )
                self._write_head(conn, self._read_head(conn))
                acknowledged += 1
        return acknowledged

    def recovery_material(self, capability: object, operation_id: UUID) -> _RecoveryMaterial:
        """Read frozen private staging only with this store's opaque capability."""
        self._require_owner()
        if capability is not self._capability:
            raise AccountTransactionError
        with self._transaction() as conn:
            row = self._row(conn, operation_id)
            body = parse_account_json(row["body"])
            return self._material(row, body)

    def _material(self, row: dict, body: dict) -> _RecoveryMaterial:
        try:
            request = None
            plan = {"replay_credentials": None, "read_only": None}
            if row["private_cipher"] is not None:
                private = self._credentials._decrypt(
                    {"salt": row["private_salt"], "encrypted_creds": row["private_cipher"]}
                )
                if set(private) != {"request"}:
                    raise AccountTransactionError
                request = _request_from(private["request"])
                if _request_dict(request, private=False) != body["identity"] or not hmac.compare_digest(
                    row["request_mac"], self._mac("request", canonical_account_json(_request_dict(request)))
                ):
                    raise AccountTransactionError
            if row["plan_cipher"] is not None:
                plan = self._credentials._decrypt({"salt": row["plan_salt"], "encrypted_creds": row["plan_cipher"]})
                if set(plan) != {"replay_credentials", "read_only"}:
                    raise AccountTransactionError
                canonical_account_json(plan)
                remove = body["identity"]["kind"] == AccountMutationKind.REMOVE.value
                if (remove and plan != {"replay_credentials": None, "read_only": None}) or (
                    not remove and (type(plan["replay_credentials"]) is not dict or type(plan["read_only"]) is not bool)
                ):
                    raise AccountTransactionError
            return _RecoveryMaterial(
                request,
                _freeze(plan["replay_credentials"]),
                plan["read_only"],
                body["before_digest"],
                body["after_digest"],
            )
        except Exception:
            raise AccountTransactionError from None

    def abandon(self, operation_id: UUID, *, committed: bool, reason: str) -> None:
        _reason(reason)
        if type(committed) is not bool or reason is None:
            raise AccountTransactionError
        with self._transaction(write=True) as conn:
            row, body, _ = self._active(conn, operation_id)
            if body["abandoned"]:
                if body["abandonment_committed"] != committed or body["abandonment_reason"] != reason:
                    raise AccountOperationConflict
                return
            stage = AccountOperationStage(body["stage"])
            if (
                body["workspace_attempted"] and not committed
                or committed and not body["workspace_attempted"]
                or stage is AccountOperationStage.COMMITTED
                and not committed
                or committed
                and stage not in (AccountOperationStage.PLAN_READY, AccountOperationStage.COMMITTED)
            ):
                raise AccountOperationConflict
            body.update(abandoned=True, abandonment_committed=committed, abandonment_reason=reason)
            self._save(conn, row, body)

    @staticmethod
    def _discard_private(row: dict) -> None:
        for name in ("private_salt", "private_cipher", "plan_salt", "plan_cipher"):
            row[name] = None

    def apply(self, operation_id: UUID, witness: BrokerAccountWitness) -> AccountMutationReceipt:
        if type(witness) is not BrokerAccountWitness:
            raise AccountTransactionError
        witness.__post_init__()
        with self._transaction(write=True) as conn:
            row = self._row(conn, operation_id)
            body = parse_account_json(row["body"])
            if body["stage"] == AccountOperationStage.COMMITTED.value:
                if BrokerAccountWitness.from_dict(body["witness"]) != witness:
                    raise AccountOperationConflict
                return _receipt_from(body["receipt"])
            row, body, head = self._active(conn, operation_id)
            original = BrokerAccountWitness.from_dict(head["witness"])
            snapshot = self._snapshot(body)
            if (
                snapshot.state is not AccountOperationStage.PLAN_READY
                or not snapshot.workspace_attempted
                or snapshot.abandoned
                and not snapshot.abandonment_committed
                or witness.operation_id != operation_id
                or witness.epoch != original.epoch + 1
                or witness.workspace_instance != original.workspace_instance
                or witness.vault_incarnation != original.vault_incarnation
                or witness.before_digest != body["before_digest"]
                or witness.before_digest != original.after_digest
                or witness.after_digest != body["after_digest"]
                or witness.commit_workspace.generation <= snapshot.expected_workspace.generation
                or witness.commit_broker_workspace.generation
                != original.commit_broker_workspace.generation + int(witness.before_digest != witness.after_digest)
            ):
                raise AccountOperationConflict
            material = self._material(row, body)
            request = material.request
            self._credentials._expected(conn, request.selector, request.expected_credential)
            self._credentials._check_bump(conn, request.selector)
            if request.kind is AccountMutationKind.REMOVE:
                version = self._credentials._remove(conn, request.selector, credentials=True, setup=True)
            else:
                self._credentials._put(
                    conn, request.selector, request.broker, request.label, _thaw(material.replay_credentials)
                )
                if material.read_only:
                    conn.execute(
                        "UPDATE accounts SET is_primary=0 WHERE adapter_id=? AND account_id=?",
                        (request.selector.adapter_id, request.selector.account_id),
                    )
                version = self._credentials._bump(conn, request.selector)
            receipt = AccountMutationReceipt(
                operation_id,
                request.selector,
                request.kind,
                AccountOperationStage.COMMITTED,
                None,
                version,
                witness.commit_workspace,
                witness.commit_broker_workspace,
            )
            body.update(stage=receipt.state.value, witness=witness.to_dict(), receipt=_receipt_dict(receipt))
            self._discard_private(row)
            self._save(conn, row, body)
            head["witness"] = witness.to_dict()
            self._write_head(conn, head)
            return receipt

    def settle(self, operation_id: UUID, *, state: AccountOperationStage, reason: str) -> AccountMutationReceipt:
        _reason(reason)
        if (
            type(state) is not AccountOperationStage
            or state not in _TERMINAL
            or state is AccountOperationStage.COMMITTED
            or reason is None
        ):
            raise AccountTransactionError
        with self._transaction(write=True) as conn:
            row = self._row(conn, operation_id)
            body = parse_account_json(row["body"])
            if body["receipt"] is not None:
                receipt = _receipt_from(body["receipt"])
                if receipt.state != state or receipt.reason != reason:
                    raise AccountOperationConflict
                return receipt
            row, body, _ = self._active(conn, operation_id)
            snapshot = self._snapshot(body)
            if snapshot.workspace_attempted or snapshot.abandonment_committed or (
                state is AccountOperationStage.AUTHENTICATION_UNKNOWN
                and snapshot.state is not AccountOperationStage.AUTHENTICATION_STARTED
            ):
                raise AccountOperationConflict
            identity = _request_from({**body["identity"], "credentials": None})
            receipt = AccountMutationReceipt(
                operation_id, identity.selector, identity.kind, state, reason, None, None, None
            )
            body.update(stage=state.value, receipt=_receipt_dict(receipt))
            self._discard_private(row)
            self._save(conn, row, body)
            return receipt

    def release_claim(self, operation_id: UUID) -> None:
        """Coordinator calls only after its real worker and cleanup have settled.

        Unknown/blocked outcomes retain custody even when the worker has exited;
        their resolution policy deliberately remains outside this foundation.
        """
        with self._transaction(write=True) as conn:
            row = self._row(conn, operation_id)
            body = parse_account_json(row["body"])
            if body["stage"] not in (AccountOperationStage.COMMITTED.value, AccountOperationStage.REJECTED.value):
                raise AccountOperationConflict
            head = self._read_head(conn)
            if head["claim"] is None:
                return
            if head["claim"] != str(operation_id):
                raise AccountOperationConflict
            head["claim"] = None
            self._write_head(conn, head)
