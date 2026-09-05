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
        result = self._mutate(
            operation,
            payload,
            connection_id=connection_id,
            expected_etag=expected_etag,
            idempotency_key=idempotency_key,
            actor_context=actor_context,
        )
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
            raise ValueError("invalid connection revision")
        uuid_text(idempotency_key)
        if type(actor_context) is not ConnectionActorContext:
            raise ValueError("trusted actor context required")
        if type(operation) is not str or operation not in {"create", "update", "delete"} or type(payload) is not dict:
            raise ValueError("invalid connection mutation")
        if operation == "create":
            if connection_id is not None:
                raise ValueError("create identity is server-owned")
        else:
            uuid_text(connection_id)
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
        if len(canonical(request).encode()) > MAX_MUTATION_BYTES:
            raise ValueError("mutation exceeds size limit")
        request = copy.deepcopy(request)
        payload = request["payload"]
        metadata_payload = dict(payload)
        credential = metadata_payload.pop("credential", None)
        replace_credential = "credential" in payload
        clear = metadata_payload.pop("clear_credential", False)
        if "clear_credential" in payload and clear is not True:
            raise ValueError("clear_credential must be true")
        if replace_credential and (
            type(credential) is not str or not credential or len(credential.encode()) > MAX_CREDENTIAL_BYTES
        ):
            raise ValueError("credential must be a bounded non-empty string")
        if replace_credential and clear:
            raise ValueError("conflicting credential instructions")
        if operation == "delete" and payload:
            raise ValueError("delete payload must be empty")
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
                        raise ValueError("connection not found")
                    if operation == "create":
                        if len(before.connections) >= MAX_CONNECTIONS:
                            raise ValueError("connection limit reached")
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
                        raise ValueError("provider rejects credential instructions")
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
        except (ConnectionRevisionConflict, ConnectionIdempotencyConflict, ValueError):
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
        self, files: TransactionFiles, journal: dict[str, Any], workspace: WorkspaceSnapshot, desired: dict[str, Any]
    ) -> WorkspaceSnapshot:
        expected_instance = workspace.version.instance_id if workspace.version else None
        for _ in range(8):

            def update(latest: dict[str, object]) -> None:
                files.revalidate()
                if _domain_digest(latest) != journal["before_digest"]:
                    raise ConnectionRevisionConflict("connection_revision_conflict")
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

    @staticmethod
    def _install(
        files: TransactionFiles, journal: dict[str, Any], version: ServiceSecretVersion, candidate: str
    ) -> None:
        files.revalidate()
        envelope = files.read(files.candidates, candidate)
        files.verify(envelope, version)
        with files.binding_directory(journal["ref"]["connection_id"], create=True) as directory:
            files.candidates.replace(candidate, directory, "credential")
        files.live(version)

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
        for suffix in ("new", "old", "recovery"):
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
        elif expected is not None:
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
        if journal["phase"] == "committed":
            if observed_digest != journal["after_digest"]:
                raise ValueError("committed state cannot be authenticated")
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
        forward_published = observed_digest == journal["after_digest"]
        changed = forward_published or (journal["secret_change"] and live_version == intended)
        if observed_digest not in {journal["before_digest"], journal["after_digest"]} and not own_recovery:
            raise ValueError("ambiguous service slice")
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
                files, {**journal, "before_digest": recovery["before_digest"]}, workspace, recovery_config
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
