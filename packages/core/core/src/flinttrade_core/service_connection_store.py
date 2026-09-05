"""Crash-durable inert connection admission, snapshots and recovery."""

from __future__ import annotations

import copy
import hashlib
import hmac
import os
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from pathlib import Path
from types import MappingProxyType
from typing import Any
from uuid import UUID, uuid4

from .service_connection_audit import ConnectionActorContext, ConnectionMutationAudit
from .service_connection_transactions import (
    MAX_CONNECTIONS,
    MAX_CREDENTIAL_BYTES,
    MAX_JOURNAL_BYTES,
    MAX_MUTATION_BYTES,
    TransactionFiles,
    canonical,
    decode,
    member_identity,
    parse_record,
    parse_version,
    record_dict,
    uuid_text,
    validate_journal,
    version_dict,
)
from .service_connections import (
    INT64_MAX,
    ServiceConnection,
    ServiceConnectionInputError,
    ServiceConnectionRef,
    ServiceSecretVersion,
    create_service_connection,
    update_service_connection,
)
from .workspace_migrations import (
    WorkspaceSnapshot,
    WorkspaceVersion,
    WorkspaceVersionConflict,
    compare_and_swap_workspace,
    read_workspace_snapshot,
)


class ConnectionRevisionRequired(RuntimeError):
    """The caller omitted its collection precondition."""


class ConnectionRevisionConflict(RuntimeError):
    """The caller collection revision is no longer current."""


class ConnectionIdempotencyConflict(RuntimeError):
    """A durable key belongs to another request or actor."""


class ConnectionStoreUnavailable(RuntimeError):
    """Only the connection authority is unavailable."""


class ConnectionMutationRejected(ValueError):
    """A closed, immutable client-rejection reason with no request data."""

    __slots__ = ("_reason",)

    def __init__(self, reason: str) -> None:
        if type(reason) is not str or reason not in {"invalid_request", "not_found", "connection_limit"}:
            raise ValueError("invalid rejection reason")
        super().__init__(reason)
        object.__setattr__(self, "_reason", reason)

    @property
    def reason(self) -> str:
        return self._reason

    def __setattr__(self, name: str, value: object) -> None:
        if name in {"reason", "_reason"}:
            raise AttributeError("rejection reason is immutable")
        super().__setattr__(name, value)

    def __str__(self) -> str:
        return self.reason

    def __delattr__(self, name: str) -> None:
        if name in {"reason", "_reason"}:
            raise AttributeError("rejection reason is immutable")
        super().__delattr__(name)

    def __repr__(self) -> str:
        return f"ConnectionMutationRejected({self.reason!r})"


def _freeze(value: object) -> Any:
    if type(value) is dict:
        return MappingProxyType({key: _freeze(item) for key, item in value.items()})
    if type(value) is list:
        return tuple(_freeze(item) for item in value)
    return value


def _thaw(value: object) -> Any:
    if isinstance(value, Mapping):
        return {key: _thaw(item) for key, item in value.items()}
    if isinstance(value, tuple):
        return [_thaw(item) for item in value]
    return value


@dataclass(frozen=True, slots=True)
class ConnectionCollectionSnapshot:
    connections: tuple[ServiceConnection, ...]
    epoch: int
    workspace_version: WorkspaceVersion | None
    etag: str


@dataclass(frozen=True, slots=True)
class ConnectionMutationResult:
    """Exact detached redacted response retained for permanent key replay."""

    status: int
    body: Mapping[str, object]
    etag: str

    def __post_init__(self) -> None:
        if type(self.status) is not int or self.status not in {200, 201, 409, 503}:
            raise ValueError("invalid result status")
        if type(self.etag) is not str or len(self.etag) != 66 or self.etag[0] != '"' or self.etag[-1] != '"':
            raise ValueError("invalid result revision")
        body = dict(self.body)
        if self.status in {409, 503}:
            if body != {"error": "transaction_rolled_back" if self.status == 503 else "connection_revision_conflict"}:
                raise ValueError("invalid failure result")
        elif body != {"deleted": True}:
            if type(body.pop("credential_configured", None)) is not bool:
                raise ValueError("invalid public connection result")
            parse_record(body, None)
        object.__setattr__(self, "body", _freeze(dict(self.body)))

    def to_dict(self) -> dict[str, object]:
        return {"status": self.status, "body": _thaw(self.body), "etag": self.etag}


def _etag(version: WorkspaceVersion | None, epoch: int) -> str:
    identity = "absent" if version is None else str(version.instance_id)
    return '"' + hashlib.sha256(f"service-collection/v1\0{identity}\0{epoch}".encode()).hexdigest() + '"'


def _domain(config: dict[str, Any]) -> dict[str, Any]:
    services = config["services"]
    return {key: services.get(key) for key in ("connections", "connection_epoch", "_connection_store")}


def _domain_digest(config: dict[str, Any]) -> str:
    return hashlib.sha256(("service-metadata/v1\0" + canonical(_domain(config))).encode()).hexdigest()


def _workspace_version(version: WorkspaceVersion | None) -> dict[str, object] | None:
    return None if version is None else {"instance_id": str(version.instance_id), "generation": version.generation}


def _checkpoint(_name: str) -> None:
    """Internal durability boundary for disposable fault-injection tests."""


class ServiceConnectionStore:
    """One lazy store and one orchestrator, without a credential getter."""

    def __init__(
        self, workspace_dir: Path, *, audit_sink: Callable[[ConnectionMutationAudit], None] | None = None
    ) -> None:
        self.workspace_dir = Path(workspace_dir)
        self.audit_sink = audit_sink

    def read_snapshot(self) -> ConnectionCollectionSnapshot:
        try:
            with TransactionFiles(self.workspace_dir) as files:
                self._recover(files)
                snapshot = self._snapshot(files, read_workspace_snapshot(self.workspace_dir))
            self._flush()
            return snapshot
        except Exception:
            self._flush()
            raise ConnectionStoreUnavailable("service_connection_store_unavailable") from None

    def recover(self) -> ConnectionCollectionSnapshot:
        """Resume the recovery path shared by all reads and writes."""
        return self.read_snapshot()

    def _snapshot(
        self,
        files: TransactionFiles,
        workspace: WorkspaceSnapshot,
        *,
        verify_live: bool = True,
        verify_anchor: bool = True,
    ) -> ConnectionCollectionSnapshot:
        services = workspace.as_dict()["services"]
        epoch, records, metadata = (
            services["connection_epoch"],
            services["connections"],
            services.get("_connection_store"),
        )
        if (
            type(epoch) is not int
            or not 0 <= epoch <= INT64_MAX
            or type(records) is not list
            or len(records) > MAX_CONNECTIONS
        ):
            raise ValueError("invalid service collection")
        bindings = {}
        if metadata is None:
            if epoch != 0 or records:
                raise ValueError("missing connection authority")
        else:
            if type(metadata) is not dict or set(metadata) != {"schema", "root", "bindings", "transition"}:
                raise ValueError("invalid connection authority")
            if type(metadata["schema"]) is not int or metadata["schema"] != 1 or type(metadata["bindings"]) is not dict:
                raise ValueError("invalid connection authority")
            uuid_text(metadata["transition"])
            if files.bootstrap is None or metadata["root"] != files.root_evidence():
                raise ValueError("connection authority root mismatch")
            for identifier, value in metadata["bindings"].items():
                uuid_text(identifier)
                binding = parse_version(value)
                if binding is None or str(binding.connection_ref.connection_id) != identifier:
                    raise ValueError("invalid retained binding")
                if str(binding.store_incarnation) != files.bootstrap["incarnation"]:
                    raise ValueError("foreign secret incarnation")
                bindings[identifier] = binding
        connections, seen = [], set()
        for raw in records:
            if type(raw) is not dict:
                raise ValueError("invalid stored connection")
            identifier = raw.get("connection_id")
            if identifier in seen:
                raise ValueError("duplicate connection UUID")
            seen.add(identifier)
            connections.append(parse_record(raw, bindings.get(identifier)))
        if verify_live:
            for binding in bindings.values():
                files.live(binding)
        if verify_anchor:
            self._check_anchor(files, workspace, required=metadata is not None)
        return ConnectionCollectionSnapshot(
            tuple(connections), epoch, workspace.version, _etag(workspace.version, epoch)
        )

    @staticmethod
    def _check_anchor(files: TransactionFiles, workspace: WorkspaceSnapshot, *, required: bool) -> None:
        if not files.control.exists("workspace-anchor.json"):
            if required:
                raise ValueError("missing independent workspace anchor")
            return
        anchor = files.read(files.control, "workspace-anchor.json")
        if set(anchor) != {"schema", "instance_id", "generation", "epoch", "domain_digest"}:
            raise ValueError("invalid workspace anchor")
        if type(anchor["schema"]) is not int or anchor["schema"] != 1:
            raise ValueError("invalid workspace anchor")
        for name in ("generation", "epoch"):
            if type(anchor[name]) is not int or not 1 <= anchor[name] <= INT64_MAX:
                raise ValueError("invalid workspace anchor counter")
        if type(anchor["instance_id"]) is not str or str(UUID(anchor["instance_id"])) != anchor["instance_id"]:
            raise ValueError("invalid workspace anchor identity")
        if (
            workspace.version is None
            or str(workspace.version.instance_id) != anchor["instance_id"]
            or workspace.version.generation < anchor["generation"]
            or workspace.as_dict()["services"]["connection_epoch"] != anchor["epoch"]
            or _domain_digest(workspace.as_dict()) != anchor["domain_digest"]
        ):
            raise ValueError("workspace anchor mismatch")

    @staticmethod
    def _save_anchor(files: TransactionFiles, workspace: WorkspaceSnapshot) -> None:
        if workspace.version is not None and workspace.as_dict()["services"]["connection_epoch"] > 0:
            files.write(
                files.control,
                "workspace-anchor.json",
                {
                    "schema": 1,
                    "instance_id": str(workspace.version.instance_id),
                    "generation": workspace.version.generation,
                    "epoch": workspace.as_dict()["services"]["connection_epoch"],
                    "domain_digest": _domain_digest(workspace.as_dict()),
                },
            )

    @staticmethod
    def _receipt(files: TransactionFiles, name: str, *, admission: bool = False) -> dict[str, Any]:
        try:
            value = files.read(files.operation_keys if admission else files.receipts, name)
            if set(value) != {
                "schema",
                "key",
                "operation",
                "request_mac",
                "actor",
                "session",
                "expected_etag",
                "ref",
                "result",
                "prepared_event",
                "terminal_event",
                "expected_epoch",
            }:
                raise ValueError("invalid receipt schema")
            if (
                type(value["schema"]) is not int
                or value["schema"] != 1
                or value["operation"] not in {"create", "update", "delete"}
            ):
                raise ValueError("invalid receipt")
            if str(uuid_text(value["key"])) + ".json" != name:
                raise ValueError("receipt identity mismatch")
            ConnectionActorContext(value["actor"], value["session"])
            uuid_text(value["prepared_event"])
            uuid_text(value["terminal_event"])
            if type(value["expected_epoch"]) is not int or not 0 <= value["expected_epoch"] <= INT64_MAX:
                raise ValueError("invalid receipt epoch")
            if type(value["request_mac"]) is not str or len(value["request_mac"]) != 64:
                raise ValueError("invalid private authenticator")
            ServiceConnectionRef(value["ref"]["provider_id"], uuid_text(value["ref"]["connection_id"]))
            if value["result"] is not None:
                ConnectionMutationResult(**value["result"])
            if admission:
                if value["result"] is not None:
                    raise ValueError("immutable admission contains a mutable result")
            else:
                expected = ServiceConnectionStore._receipt(files, name, admission=True)
                if {**value, "result": None} != expected:
                    raise ValueError("receipt admission binding changed")
            return value
        except Exception:
            raise ConnectionStoreUnavailable("service_connection_store_unavailable") from None

    def mutate(
        self,
        operation: str,
        payload: Mapping[str, object],
        *,
        connection_id: str | None,
        expected_etag: str | None,
        idempotency_key: str,
        actor_context: ConnectionActorContext,
    ) -> ConnectionMutationResult:
        """Durably admit exactly one actor-bound create, update or delete."""
        try:
            result = self._mutate(
                operation,
                payload,
                connection_id=connection_id,
                expected_etag=expected_etag,
                idempotency_key=idempotency_key,
                actor_context=actor_context,
            )
        except ServiceConnectionInputError:
            raise ConnectionMutationRejected("invalid_request") from None
        except (
            ConnectionMutationRejected,
            ConnectionRevisionRequired,
            ConnectionRevisionConflict,
            ConnectionIdempotencyConflict,
            ConnectionStoreUnavailable,
        ):
            raise
        except Exception:
            raise ConnectionStoreUnavailable("service_connection_store_unavailable") from None
        self._flush()
        return result

    def _mutate(
        self,
        operation: str,
        payload: Mapping[str, object],
        *,
        connection_id: str | None,
        expected_etag: str | None,
        idempotency_key: str,
        actor_context: ConnectionActorContext,
    ) -> ConnectionMutationResult:
        if expected_etag is None:
            raise ConnectionRevisionRequired("connection_revision_required")
        if (
            type(expected_etag) is not str
            or len(expected_etag) != 66
            or not expected_etag.startswith('"')
            or not expected_etag.endswith('"')
        ):
            raise ConnectionMutationRejected("invalid_request")
        try:
            uuid_text(idempotency_key)
        except ValueError:
            raise ConnectionMutationRejected("invalid_request") from None
        if type(actor_context) is not ConnectionActorContext:
            raise ValueError("trusted actor context required")
        if type(operation) is not str or operation not in {"create", "update", "delete"} or type(payload) is not dict:
            raise ConnectionMutationRejected("invalid_request")
        if operation == "create":
            if connection_id is not None:
                raise ConnectionMutationRejected("invalid_request")
        else:
            try:
                uuid_text(connection_id)
            except ValueError:
                raise ConnectionMutationRejected("invalid_request") from None
        request = {
            "schema": 1,
            "key": idempotency_key,
            "operation": operation,
            "target": connection_id,
            "actor": actor_context.actor,
            "session": actor_context.session_binding,
            "etag": expected_etag,
            "payload": payload,
        }
        try:
            request_size = len(canonical(request).encode())
        except (ValueError, TypeError, UnicodeError):
            raise ConnectionMutationRejected("invalid_request") from None
        if request_size > MAX_MUTATION_BYTES:
            raise ConnectionMutationRejected("invalid_request")
        request = copy.deepcopy(request)
        payload = request["payload"]
        metadata_payload = dict(payload)
        credential = metadata_payload.pop("credential", None)
        replace_credential = "credential" in payload
        clear = metadata_payload.pop("clear_credential", False)
        if "clear_credential" in payload and clear is not True:
            raise ConnectionMutationRejected("invalid_request")
        if replace_credential and (
            type(credential) is not str or not credential or len(credential.encode()) > MAX_CREDENTIAL_BYTES
        ):
            raise ConnectionMutationRejected("invalid_request")
        if replace_credential and clear:
            raise ConnectionMutationRejected("invalid_request")
        if operation == "delete" and payload:
            raise ConnectionMutationRejected("invalid_request")
        try:
            with TransactionFiles(self.workspace_dir) as files:
                # Completed receipt replay is independent of a later collection
                # revision, including an explicitly blocked foreign-first race.
                if files.bootstrap is not None and files.operation_keys.exists(f"{idempotency_key}.json"):
                    admission = self._receipt(files, f"{idempotency_key}.json", admission=True)
                    if not hmac.compare_digest(admission["request_mac"], files.request_mac(request)):
                        raise ConnectionIdempotencyConflict("connection_idempotency_conflict")
                    if not files.receipts.exists(f"{idempotency_key}.json"):
                        raise ConnectionStoreUnavailable("service_connection_store_unavailable")
                if files.bootstrap is not None and files.receipts.exists(f"{idempotency_key}.json"):
                    receipt = self._receipt(files, f"{idempotency_key}.json")
                    if not hmac.compare_digest(receipt["request_mac"], files.request_mac(request)):
                        raise ConnectionIdempotencyConflict("connection_idempotency_conflict")
                    if receipt["result"] is not None:
                        return ConnectionMutationResult(**receipt["result"])
                self._recover(files)
                workspace = read_workspace_snapshot(self.workspace_dir)
                before = self._snapshot(files, workspace)
                files.initialise()
                mac = files.request_mac(request)
                receipt_name = f"{idempotency_key}.json"
                if files.receipts.exists(receipt_name):
                    receipt = self._receipt(files, receipt_name)
                    if not hmac.compare_digest(receipt["request_mac"], mac):
                        raise ConnectionIdempotencyConflict("connection_idempotency_conflict")
                    if receipt["result"] is None:
                        self._audit(
                            files,
                            {**receipt, "before_epoch": receipt["expected_epoch"]},
                            receipt,
                            "failed",
                            receipt["expected_epoch"],
                        )
                        receipt["result"] = ConnectionMutationResult(
                            503, {"error": "transaction_rolled_back"}, receipt["expected_etag"]
                        ).to_dict()
                        files.write(files.receipts, receipt_name, receipt)
                    result = ConnectionMutationResult(**receipt["result"])
                else:
                    if before.etag != expected_etag:
                        raise ConnectionRevisionConflict("connection_revision_conflict")
                    current = next(
                        (item for item in before.connections if str(item.connection_id) == connection_id), None
                    )
                    if operation != "create" and current is None:
                        raise ConnectionMutationRejected("not_found")
                    if operation == "create":
                        if len(before.connections) >= MAX_CONNECTIONS:
                            raise ConnectionMutationRejected("connection_limit")
                        desired = create_service_connection(metadata_payload)
                        connection_id = str(desired.connection_id)
                        if any(item.connection_id == desired.connection_id for item in before.connections):
                            raise ValueError("server connection identity collision")
                    elif operation == "update":
                        desired = update_service_connection(current, metadata_payload)
                    else:
                        desired = None
                    subject = desired or current
                    if subject.auth_mode is None and (replace_credential or clear):
                        raise ConnectionMutationRejected("invalid_request")
                    config = workspace.as_dict()
                    private = config["services"].get("_connection_store")
                    old_binding = parse_version(private["bindings"].get(connection_id)) if private else None
                    change_secret = (
                        replace_credential
                        or clear
                        or (
                            old_binding is not None
                            and (desired is None or desired.secret_version != current.secret_version)
                        )
                    )
                    new_binding = old_binding
                    if change_secret:
                        generation = old_binding.generation if old_binding else 0
                        if generation > INT64_MAX - 2:
                            raise ValueError("secret generation exhausted")
                        new_binding = ServiceSecretVersion(
                            subject.ref,
                            uuid_text(files.bootstrap["incarnation"]),
                            old_binding.binding_id if old_binding else uuid4(),
                            generation + 1,
                            replace_credential,
                        )
                    if before.epoch > INT64_MAX - 2 or (
                        workspace.version and workspace.version.generation > INT64_MAX - 2
                    ):
                        raise ValueError("workspace counter exhausted")
                    if desired is not None:
                        desired = desired.with_secret_version(new_binding if desired.auth_mode is not None else None)
                    receipt = {
                        "schema": 1,
                        "key": idempotency_key,
                        "operation": operation,
                        "request_mac": mac,
                        "actor": actor_context.actor,
                        "session": actor_context.session_binding,
                        "expected_etag": expected_etag,
                        "ref": subject.ref.to_dict(),
                        "result": None,
                        "prepared_event": str(uuid4()),
                        "terminal_event": str(uuid4()),
                        "expected_epoch": before.epoch,
                    }
                    files.write(files.operation_keys, receipt_name, receipt)
                    _checkpoint("key_tombstone")
                    files.write(files.receipts, receipt_name, receipt)
                    _checkpoint("receipt")
                    journal = {
                        "schema": 1,
                        "phase": "prepared",
                        "key": idempotency_key,
                        "operation": operation,
                        "expected_workspace": _workspace_version(workspace.version),
                        "published_workspace": None,
                        "before_epoch": before.epoch,
                        "after_epoch": before.epoch + 1,
                        "before_record": record_dict(current),
                        "after_record": record_dict(desired),
                        "before_binding": version_dict(old_binding),
                        "after_binding": version_dict(new_binding),
                        "ref": subject.ref.to_dict(),
                        "root": files.root_evidence(),
                        "witness": str(uuid4()),
                        "before_digest": _domain_digest(config),
                        "after_digest": None,
                        "prepared_event": receipt["prepared_event"],
                        "terminal_event": receipt["terminal_event"],
                        "recovery": None,
                        "result": None,
                        "secret_change": bool(change_secret),
                        "claims": {},
                    }
                    self._audit(files, journal, receipt, "prepared", before.epoch)
                    _checkpoint("prepared_audit")
                    if change_secret:
                        files.write(files.candidates, f"{idempotency_key}.new", files.envelope(new_binding, credential))
                        _checkpoint("candidate")
                    desired_config = self._apply(config, journal, "after")
                    journal["after_digest"] = _domain_digest(desired_config)
                    self._journal(files, journal)
                    _checkpoint("prepared_journal")
                    if old_binding is not None and change_secret:
                        files.write(files.candidates, f"{idempotency_key}.old", files.live(old_binding))
                        _checkpoint("backup")
                    if change_secret:
                        self._install(files, journal, new_binding, f"{idempotency_key}.new")
                        _checkpoint("secret_install")
                    try:
                        published = self._cas(files, journal, workspace, desired_config)
                    except ConnectionRevisionConflict:
                        if journal["expected_workspace"] is None:
                            return self._foreign_first(files, journal, receipt)
                        raise
                    _checkpoint("workspace_cas")
                    journal["published_workspace"] = _workspace_version(published.version)
                    result = ConnectionMutationResult(
                        201 if operation == "create" else 200,
                        desired.to_public_dict() if desired else {"deleted": True},
                        _etag(published.version, journal["after_epoch"]),
                    )
                    journal["result"] = result.to_dict()
                    self._journal(files, journal)
                    _checkpoint("workspace_bound")
                    journal["phase"] = "committed"
                    self._journal(files, journal)
                    _checkpoint("committed")
                    self._finish(files, journal, receipt, result, "succeeded")
            self._flush()
            return result
        except (
            ConnectionRevisionConflict,
            ConnectionIdempotencyConflict,
            ConnectionMutationRejected,
            ServiceConnectionInputError,
        ):
            raise
        except Exception:
            raise ConnectionStoreUnavailable("service_connection_store_unavailable") from None

    def _apply(self, config: dict[str, Any], journal: dict[str, Any], side: str) -> dict[str, Any]:
        result = copy.deepcopy(config)
        services = result["services"]
        identifier = journal["ref"]["connection_id"]
        services["connections"] = [item for item in services["connections"] if item["connection_id"] != identifier]
        if journal[f"{side}_record"] is not None:
            services["connections"].append(journal[f"{side}_record"])
        services["connections"].sort(key=lambda item: item["connection_id"])
        private = services.get("_connection_store")
        if private is None:
            private = {"schema": 1, "root": journal["root"], "bindings": {}, "transition": journal["witness"]}
            services["_connection_store"] = private
        private["transition"] = journal["witness"]
        binding = journal[f"{side}_binding"]
        if binding is not None:
            private["bindings"][identifier] = binding
        services["connection_epoch"] = journal["after_epoch"]
        return result

    def _cas(
        self,
        files: TransactionFiles,
        journal: dict[str, Any],
        workspace: WorkspaceSnapshot,
        desired: dict[str, Any],
        *,
        recovery: bool = False,
    ) -> WorkspaceSnapshot:
        expected_instance = workspace.version.instance_id if workspace.version else None
        for _ in range(8):

            def update(latest: dict[str, object]) -> None:
                files.revalidate()
                if _domain_digest(latest) != journal["before_digest"]:
                    raise ConnectionRevisionConflict("connection_revision_conflict")
                # Forward publication must leave one legal physical generation
                # for compensation, including after an unrelated-writer retry.
                if latest.get("workspace_generation", 0) > INT64_MAX - (1 if recovery else 2):
                    raise ConnectionStoreUnavailable("service_connection_store_unavailable")
                self._check_claims(files, journal)
                for binding in desired["services"]["_connection_store"]["bindings"].values():
                    files.live(parse_version(binding))
                for key, value in _domain(desired).items():
                    latest["services"][key] = copy.deepcopy(value)

            try:
                return compare_and_swap_workspace(self.workspace_dir, workspace.version, update)
            except WorkspaceVersionConflict:
                workspace = read_workspace_snapshot(self.workspace_dir)
                instance = workspace.version.instance_id if workspace.version else None
                if instance != expected_instance or _domain_digest(workspace.as_dict()) != journal["before_digest"]:
                    raise ConnectionRevisionConflict("connection_revision_conflict") from None
        raise ConnectionStoreUnavailable("service_connection_store_unavailable")

    @staticmethod
    def _journal(files: TransactionFiles, journal: dict[str, Any]) -> None:
        files.write(files.control, "transaction.json", journal, MAX_JOURNAL_BYTES)

    def _install(
        self, files: TransactionFiles, journal: dict[str, Any], version: ServiceSecretVersion, candidate: str
    ) -> None:
        try:
            phase = "new" if candidate == f"{journal['key']}.new" else "recovery"
            if candidate != f"{journal['key']}.{phase}":
                raise ValueError("invalid install phase")
            files.revalidate()
            files.verify(files.read(files.candidates, candidate), version)
            expected = parse_version(journal["before_binding"] if phase == "new" else journal["after_binding"])
            claim_name = f"{candidate}.claimed"
            with files.binding_directory(journal["ref"]["connection_id"], create=True) as directory:
                if expected is None:
                    if directory.existing_member("credential") is not None:
                        raise OSError("expected credential absence")
                else:
                    envelope, identity = files.read_identity(directory, "credential")
                    files.verify(envelope, expected)
                    _checkpoint(f"{phase}_target_read")
                    claim = {
                        "identity": identity,
                        "expected": version_dict(expected),
                        "intended": version_dict(version),
                    }
                    previous = journal["claims"].get(phase)
                    if previous is not None and previous != claim:
                        raise ValueError("claim intent changed")
                    journal["claims"][phase] = claim
                    self._journal(files, journal)
                    _checkpoint(f"{phase}_claim_intent")
                    directory.move_no_replace("credential", files.candidates, claim_name)
                    _checkpoint(f"{phase}_claim")
                    claimed_text, claimed_stat = files.candidates.read_text_with_identity(claim_name)
                    moved_identity = member_identity(claimed_stat)
                    try:
                        if moved_identity != identity:
                            raise ValueError("destination changed before claim")
                        files.verify(decode(claimed_text), expected)
                    except (ValueError, KeyError, TypeError):
                        # Only the exact just-observed moved object is eligible
                        # for immediate restoration; restart requires the durable
                        # expected identity and full binding authentication.
                        _text, current_stat = files.candidates.read_text_with_identity(claim_name)
                        if member_identity(current_stat) != moved_identity:
                            raise OSError("claimed object changed before restoration") from None
                        _checkpoint("claim_restore_before")
                        files.candidates.move_no_replace(claim_name, directory, "credential")
                        _checkpoint("claim_restored")
                        raise OSError("destination claim rejected") from None
                    _checkpoint(f"{phase}_claim_verified")
                files.candidates.move_no_replace(candidate, directory, "credential")
                _checkpoint(f"{phase}_published")
            files.live(version)
        except (ValueError, KeyError, TypeError):
            raise OSError("credential install authority mismatch") from None

    def _check_claims(
        self, files: TransactionFiles, journal: dict[str, Any], *, restore_phase: str | None = None
    ) -> str | None:
        """Inspect all claims without effects; return one admitted claim gap."""
        claims = journal["claims"]
        pending = None
        projected_live = None
        if "recovery" in claims and journal["recovery"] is None and not files.control.exists("blocked.json"):
            raise ValueError("compensation claim lacks a durable decision")
        for phase in ("recovery", "new"):
            name = f"{journal['key']}.{phase}.claimed"
            actual = files.candidates.existing_member(name)
            if actual is None:
                continue
            claim = claims.get(phase)
            if claim is None:
                raise ValueError("unjournalled claim retained")
            envelope, identity = files.read_identity(files.candidates, actual)
            expected, intended = parse_version(claim["expected"]), parse_version(claim["intended"])
            if identity != claim["identity"]:
                raise ValueError("claimed object identity mismatch")
            files.verify(envelope, expected)
            with files.binding_directory(journal["ref"]["connection_id"]) as directory:
                if directory.existing_member("credential") is None:
                    if projected_live is None:
                        if phase != restore_phase or actual != name:
                            raise ValueError("missing credential with an unresumable claim")
                        # A consumed candidate cannot prove an interrupted claim:
                        # its intended generation may already have been installed.
                        files.verify(files.read(files.candidates, f"{journal['key']}.{phase}"), intended)
                        pending, projected_live = phase, expected
                        continue
                    live_version = projected_live
                else:
                    live = files.read(directory, "credential")
                    live_version = parse_version(live["version"])
                    files.verify(live, live_version)
                allowed = {intended}
                if phase == "new" and journal["recovery"] is not None:
                    allowed.add(parse_version(journal["recovery"]["after_binding"]))
                if live_version not in allowed:
                    raise ValueError("unexpected entrant beside claim")
        return pending

    @staticmethod
    def _restore_claim(files: TransactionFiles, journal: dict[str, Any], phase: str) -> None:
        """Execute a previously admitted claim restoration without clobbering."""
        name = f"{journal['key']}.{phase}.claimed"
        claim = journal["claims"][phase]
        envelope, identity = files.read_identity(files.candidates, name)
        expected = parse_version(claim["expected"])
        if identity != claim["identity"]:
            raise ValueError("claimed object changed after admission")
        files.verify(envelope, expected)
        files.verify(files.read(files.candidates, f"{journal['key']}.{phase}"), parse_version(claim["intended"]))
        with files.binding_directory(journal["ref"]["connection_id"]) as directory:
            _checkpoint("claim_restore_before")
            files.candidates.move_no_replace(name, directory, "credential")
            _checkpoint("claim_restored")
        files.live(expected)

    @staticmethod
    def _audit(
        files: TransactionFiles, journal: dict[str, Any], receipt: dict[str, Any], outcome: str, epoch: int
    ) -> None:
        connection_ref = ServiceConnectionRef(journal["ref"]["provider_id"], uuid_text(journal["ref"]["connection_id"]))
        event_id = journal["prepared_event"] if outcome == "prepared" else journal["terminal_event"]
        event = ConnectionMutationAudit(
            uuid_text(event_id),
            journal["operation"],
            connection_ref,
            receipt["actor"],
            receipt["session"],
            journal["before_epoch"],
            journal["before_epoch"],
            epoch,
            outcome,
            "transaction_rolled_back" if outcome == "failed" else None,
        )
        previous = files.outbox.existing_member(f"{event_id}.json")
        if previous is not None:
            if files.read(files.outbox, previous) != event.to_dict():
                raise ValueError("audit event changed under its stable identity")
            return
        files.write(files.outbox, f"{event_id}.json", event.to_dict())

    def _finish(
        self,
        files: TransactionFiles,
        journal: dict[str, Any],
        receipt: dict[str, Any],
        result: ConnectionMutationResult,
        outcome: str,
    ) -> None:
        self._check_claims(files, journal)
        for suffix, version in (
            ("new", journal["after_binding"]),
            ("old", journal["before_binding"]),
            ("recovery", journal["recovery"]["after_binding"] if journal["recovery"] else None),
        ):
            name = f"{journal['key']}.{suffix}"
            actual = files.candidates.existing_member(name)
            if actual is not None:
                binding = parse_version(version)
                if binding is None:
                    raise ValueError("unowned cleanup candidate")
                files.verify(files.read(files.candidates, actual), binding)
        self._save_anchor(files, read_workspace_snapshot(self.workspace_dir))
        _checkpoint("workspace_anchor")
        self._audit(files, journal, receipt, outcome, journal["after_epoch"])
        _checkpoint("terminal_audit")
        receipt["result"] = result.to_dict()
        files.write(files.receipts, f"{journal['key']}.json", receipt)
        _checkpoint("terminal_receipt")
        self._check_claims(files, journal)
        for suffix in ("new", "old", "recovery", "new.claimed", "recovery.claimed"):
            name = f"{journal['key']}.{suffix}"
            if files.candidates.existing_member(name) is not None:
                files.candidates.unlink(name)
        _checkpoint("candidate_cleanup")
        files.control.unlink("transaction.json")
        _checkpoint("journal_cleanup")

    def _recover(self, files: TransactionFiles) -> None:
        if files.bootstrap is None:
            return
        journal_member = files.control.existing_member("transaction.json")
        if journal_member is None:
            if files.control.exists("blocked.json"):
                raise ValueError("blocked connection authority lacks its journal")
            with os.scandir(files.candidates.path) as candidates:
                if next(candidates, None) is not None:
                    raise ValueError("unjournalled candidate retained")
            return
        journal = files.read(files.control, journal_member, MAX_JOURNAL_BYTES)
        validate_journal(journal)
        if journal["root"] != files.root_evidence():
            raise ValueError("foreign transaction root")
        receipt = self._receipt(files, f"{journal['key']}.json")
        workspace = read_workspace_snapshot(self.workspace_dir)
        config = workspace.as_dict()
        observed_digest = _domain_digest(config)
        expected = journal["expected_workspace"]
        if files.control.exists("workspace-anchor.json"):
            anchor = files.read(files.control, "workspace-anchor.json")
            allowed = {journal["before_digest"], journal["after_digest"]}
            if journal["recovery"]:
                allowed.add(journal["recovery"]["after_digest"])
            if (
                set(anchor) != {"schema", "instance_id", "generation", "epoch", "domain_digest"}
                or type(anchor["schema"]) is not int
                or anchor["schema"] != 1
                or workspace.version is None
                or anchor["instance_id"] != str(workspace.version.instance_id)
                or type(anchor["generation"]) is not int
                or not 1 <= anchor["generation"] <= workspace.version.generation
                or type(anchor["epoch"]) is not int
                or not 1 <= anchor["epoch"] <= INT64_MAX
                or anchor["domain_digest"] not in allowed
            ):
                raise ValueError("recovery independent anchor mismatch")
        elif expected is not None and not (
            journal["operation"] == "create"
            and journal["before_epoch"] == 0
            and journal["before_record"] is None
            and journal["before_binding"] is None
            and journal["before_digest"]
            == _domain_digest(
                {
                    "services": {
                        "connections": [],
                        "connection_epoch": 0,
                        "_connection_store": None,
                    }
                }
            )
        ):
            raise ValueError("recovery independent anchor is missing")
        same_instance = (workspace.version is None and expected is None) or (
            expected is not None
            and workspace.version is not None
            and str(workspace.version.instance_id) == expected["instance_id"]
        )
        own_first = (
            expected is None
            and observed_digest == journal["after_digest"]
            and (config["services"].get("_connection_store", {}).get("transition") == journal["witness"])
        )
        recovery = journal["recovery"]
        own_recovery = (
            recovery is not None
            and observed_digest == recovery["after_digest"]
            and (config["services"].get("_connection_store", {}).get("transition") == recovery["witness"])
        )
        if not same_instance and not own_first and not own_recovery:
            if expected is None and workspace.version is not None:
                self._foreign_first(files, journal, receipt)
                raise ConnectionStoreUnavailable("service_connection_store_unavailable")
            raise ValueError("foreign workspace during recovery")
        for authority in (expected, journal["published_workspace"]):
            if authority is not None and (
                workspace.version is None
                or str(workspace.version.instance_id) != authority["instance_id"]
                or workspace.version.generation < authority["generation"]
            ):
                raise ValueError("workspace regressed below journal authority")
        if (
            expected is not None
            and (observed_digest == journal["after_digest"] or own_recovery)
            and workspace.version.generation <= expected["generation"]
        ):
            raise ValueError("published workspace did not advance journal authority")
        if recovery is not None and (
            observed_digest not in {recovery["before_digest"], recovery["after_digest"]}
            or _domain_digest(self._apply(config, {**journal, **recovery}, "after")) != recovery["after_digest"]
        ):
            raise ValueError("recovery decision does not reconstruct authenticated state")
        forward_published = observed_digest == journal["after_digest"]
        if observed_digest not in {journal["before_digest"], journal["after_digest"]} and not own_recovery:
            raise ValueError("ambiguous service slice")
        if journal["phase"] == "committed" and not forward_published:
            raise ValueError("committed state cannot be authenticated")
        observed_binding = (
            config["services"].get("_connection_store", {}).get("bindings", {}).get(journal["ref"]["connection_id"])
        )
        expected_binding = journal["before_binding"]
        if forward_published:
            expected_binding = journal["after_binding"]
        if own_recovery:
            expected_binding = recovery["after_binding"]
        if parse_version(observed_binding) != parse_version(expected_binding):
            raise ValueError("retained binding does not admit recovery")
        restore_phase = None
        if journal["phase"] == "prepared" and not own_recovery:
            if recovery is not None:
                restore_phase = "recovery"
            elif not forward_published and journal["published_workspace"] is None:
                restore_phase = "new"
        pending = self._check_claims(files, journal, restore_phase=restore_phase)
        if pending is not None:
            self._restore_claim(files, journal, pending)
        if journal["phase"] == "committed":
            self._snapshot(files, workspace, verify_anchor=False)
            self._finish(files, journal, receipt, ConnectionMutationResult(**journal["result"]), "succeeded")
            return
        old_version, intended = parse_version(journal["before_binding"]), parse_version(journal["after_binding"])
        live_version = None
        if journal["secret_change"]:
            with files.binding_directory(journal["ref"]["connection_id"], create=True) as directory:
                if directory.exists("credential"):
                    live = files.read(directory, "credential")
                    live_version = parse_version(live["version"])
                    allowed = [old_version, intended]
                    if recovery:
                        allowed.append(parse_version(recovery["after_binding"]))
                    if live_version not in allowed or live_version is None:
                        raise ValueError("ambiguous live credential")
                    files.verify(live, live_version)
                elif old_version is not None:
                    raise ValueError("missing prior credential")
        if (
            forward_published
            and journal["secret_change"]
            and live_version != intended
            and (recovery is None or live_version != parse_version(recovery["after_binding"]))
        ):
            raise ValueError("published credential does not match journal")
        changed = forward_published or (journal["secret_change"] and live_version == intended)
        if not changed and recovery is None:
            result = ConnectionMutationResult(
                503, {"error": "transaction_rolled_back"}, _etag(workspace.version, journal["before_epoch"])
            )
            self._finish(files, {**journal, "after_epoch": journal["before_epoch"]}, receipt, result, "failed")
            return
        if recovery is None:
            restored_version = old_version
            if journal["secret_change"] and live_version == intended:
                restored_version = ServiceSecretVersion(
                    intended.connection_ref,
                    intended.store_incarnation,
                    intended.binding_id,
                    intended.generation + 1,
                    old_version.present if old_version else False,
                )
            recovery = {
                "before_digest": observed_digest,
                "after_digest": None,
                "after_record": journal["before_record"],
                "after_binding": version_dict(restored_version),
                "after_epoch": config["services"]["connection_epoch"] + 1,
                "witness": str(uuid4()),
            }
            journal["recovery"] = recovery
            recovery_config = self._apply(config, {**journal, **recovery}, "after")
            recovery["after_digest"] = _domain_digest(recovery_config)
            self._journal(files, journal)
            _checkpoint("recovery_decision")
        recovery_config = self._apply(config, {**journal, **recovery}, "after")
        restored_version = parse_version(recovery["after_binding"])
        if not own_recovery:
            if journal["secret_change"] and restored_version != live_version:
                credential = None
                if old_version and old_version.present:
                    old = files.read(files.candidates, f"{journal['key']}.old")
                    files.verify(old, old_version)
                    credential = files.cipher.decrypt(old["ciphertext"].encode()).decode()
                candidate = f"{journal['key']}.recovery"
                if not files.candidates.exists(candidate):
                    files.write(files.candidates, candidate, files.envelope(restored_version, credential))
                self._install(files, journal, restored_version, candidate)
                _checkpoint("recovery_install")
            recovery_config = self._apply(config, {**journal, **recovery}, "after")
            workspace = self._cas(
                files,
                {**journal, "before_digest": recovery["before_digest"]},
                workspace,
                recovery_config,
                recovery=True,
            )
            _checkpoint("recovery_cas")
        self._snapshot(files, workspace, verify_anchor=False)
        result = ConnectionMutationResult(
            503, {"error": "transaction_rolled_back"}, _etag(workspace.version, recovery["after_epoch"])
        )
        self._finish(files, {**journal, "after_epoch": recovery["after_epoch"]}, receipt, result, "failed")

    def _foreign_first(
        self, files: TransactionFiles, journal: dict[str, Any], receipt: dict[str, Any]
    ) -> ConnectionMutationResult:
        """Compensate local authority only; the winning workspace is untouched."""
        if (
            journal["expected_workspace"] is not None
            or journal["operation"] != "create"
            or journal["before_epoch"] != 0
            or journal["before_record"] is not None
            or journal["before_binding"] is not None
            or journal["root"] != files.root_evidence()
        ):
            raise ConnectionStoreUnavailable("service_connection_store_unavailable")
        intended = parse_version(journal["after_binding"])
        if files.control.exists("blocked.json"):
            decision = files.read(files.control, "blocked.json")
            if set(decision) != {"schema", "key", "version", "foreign_workspace"} or decision["key"] != journal["key"]:
                raise ValueError("invalid blocked decision")
            compensation = parse_version(decision["version"])
        else:
            workspace = read_workspace_snapshot(self.workspace_dir)
            if workspace.version is None or _domain_digest(workspace.as_dict()) == journal["after_digest"]:
                raise ValueError("foreign creator is not established")
            compensation = None
            if intended is not None:
                files.live(intended)
                compensation = ServiceSecretVersion(
                    intended.connection_ref,
                    intended.store_incarnation,
                    intended.binding_id,
                    intended.generation + 1,
                    False,
                )
            decision = {
                "schema": 1,
                "key": journal["key"],
                "version": version_dict(compensation),
                "foreign_workspace": _workspace_version(workspace.version),
            }
            files.write(files.control, "blocked.json", decision)
            _checkpoint("foreign_decision")
        if intended is not None:
            if (
                compensation is None
                or compensation.connection_ref != intended.connection_ref
                or compensation.store_incarnation != intended.store_incarnation
                or compensation.binding_id != intended.binding_id
                or compensation.generation != intended.generation + 1
                or compensation.present
            ):
                raise ValueError("invalid blocked compensation identity")
            pending = self._check_claims(files, journal, restore_phase="recovery")
            if pending is not None:
                self._restore_claim(files, journal, pending)
            with files.binding_directory(journal["ref"]["connection_id"]) as directory:
                live = files.read(directory, "credential")
            observed = parse_version(live["version"])
            if observed not in {intended, compensation}:
                raise ValueError("ambiguous foreign-race credential")
            files.verify(live, observed)
            if observed != compensation:
                name = f"{journal['key']}.recovery"
                if not files.candidates.exists(name):
                    files.write(files.candidates, name, files.envelope(compensation, None))
                self._install(files, journal, compensation, name)
                _checkpoint("foreign_install")
            self._check_claims(files, journal)
        result = ConnectionMutationResult(409, {"error": "connection_revision_conflict"}, receipt["expected_etag"])
        event = ConnectionMutationAudit(
            uuid_text(journal["terminal_event"]),
            "create",
            ServiceConnectionRef(journal["ref"]["provider_id"], uuid_text(journal["ref"]["connection_id"])),
            receipt["actor"],
            receipt["session"],
            0,
            0,
            0,
            "failed",
            "revision_conflict",
        )
        files.write(files.outbox, f"{event.event_id}.json", event.to_dict())
        _checkpoint("foreign_terminal_audit")
        receipt["result"] = result.to_dict()
        files.write(files.receipts, f"{journal['key']}.json", receipt)
        return result

    def _flush(self) -> None:
        if self.audit_sink is None:
            return
        pending = []
        try:
            with TransactionFiles(self.workspace_dir) as files:
                if files.bootstrap is None:
                    return
                with os.scandir(files.outbox.path) as entries:
                    for entry in entries:
                        if len(pending) >= 32:
                            break
                        logical_name = entry.name
                        if logical_name.startswith(".") and logical_name.endswith(".delete-pending"):
                            logical_name = logical_name[1 : -len(".delete-pending")]
                        if not logical_name.endswith(".json"):
                            raise ValueError("unknown outbox member")
                        event = files.read(files.outbox, entry.name)
                        ref = event.pop("connection_ref")
                        event["connection_ref"] = ServiceConnectionRef(
                            ref["provider_id"], uuid_text(ref["connection_id"])
                        )
                        event["event_id"] = uuid_text(event["event_id"])
                        if logical_name != f"{event['event_id']}.json":
                            raise ValueError("outbox identity mismatch")
                        pending.append((logical_name, ConnectionMutationAudit(**event)))
            for name, event in pending:
                try:
                    self.audit_sink(event)
                except Exception:
                    continue
                with TransactionFiles(self.workspace_dir) as files:
                    if files.outbox.existing_member(name) is not None:
                        files.outbox.unlink(name)
        except Exception:
            # Export cannot change a durable domain outcome; retain pending state.
            return
