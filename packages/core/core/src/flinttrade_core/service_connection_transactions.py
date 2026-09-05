"""Bounded private files and cryptographic envelopes for the inert store.

Only the store orchestrator owns transaction policy and workspace updates.
No provider, environment credential or external runtime is consulted here.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import math
import os
from contextlib import ExitStack
from datetime import datetime
from pathlib import Path
from typing import Any
from uuid import UUID, uuid4

from cryptography.fernet import Fernet

from .owner_file_lock import OwnerSafeFileLock
from .secure_file import HeldOwnerDirectory, harden_directory
from .service_connections import ServiceConnection, ServiceConnectionRef, ServiceSecretVersion

MAX_CREDENTIAL_BYTES = 16 * 1024
MAX_MUTATION_BYTES = 32 * 1024
MAX_ENVELOPE_BYTES = 64 * 1024
MAX_JOURNAL_BYTES = 256 * 1024
MAX_CONNECTIONS = 128


def canonical(value: object) -> str:
    """Encode bounded private structures without ambiguous JSON values."""
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False)


def _pairs(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate private member")
        result[key] = value
    return result


def decode(text: str) -> dict[str, Any]:
    def reject_constant(_value: str) -> None:
        raise ValueError("non-finite private value")

    result = json.loads(text, object_pairs_hook=_pairs, parse_constant=reject_constant)
    if type(result) is not dict:
        raise ValueError("invalid private envelope")
    return result


def uuid_text(value: object) -> UUID:
    if type(value) is not str:
        raise ValueError("invalid canonical UUID4")
    result = UUID(value)
    if str(result) != value or result.version != 4:
        raise ValueError("invalid canonical UUID4")
    return result


def version_dict(version: ServiceSecretVersion | None) -> dict[str, object] | None:
    if version is None:
        return None
    return {
        "connection_ref": version.connection_ref.to_dict(),
        "store_incarnation": str(version.store_incarnation),
        "binding_id": str(version.binding_id),
        "generation": version.generation,
        "present": version.present,
    }


def parse_version(value: object) -> ServiceSecretVersion | None:
    if value is None:
        return None
    if type(value) is not dict or set(value) != {
        "connection_ref",
        "store_incarnation",
        "binding_id",
        "generation",
        "present",
    }:
        raise ValueError("invalid secret version")
    ref = value["connection_ref"]
    if type(ref) is not dict or set(ref) != {"provider_id", "connection_id"}:
        raise ValueError("invalid secret reference")
    return ServiceSecretVersion(
        ServiceConnectionRef(ref["provider_id"], uuid_text(ref["connection_id"])),
        uuid_text(value["store_incarnation"]),
        uuid_text(value["binding_id"]),
        value["generation"],
        value["present"],
    )


def record_dict(record: ServiceConnection | None) -> dict[str, object] | None:
    if record is None:
        return None
    result = record.to_public_dict()
    del result["credential_configured"]
    return result


def parse_record(value: object, version: ServiceSecretVersion | None) -> ServiceConnection:
    if type(value) is not dict or set(value) != {
        "schema_version",
        "provider_id",
        "connection_id",
        "label",
        "model",
        "endpoint",
        "auth_mode",
        "created_at",
        "updated_at",
    }:
        raise ValueError("invalid connection record")
    values = dict(value)
    values["connection_id"] = uuid_text(values["connection_id"])
    for field in ("created_at", "updated_at"):
        if type(values[field]) is not str:
            raise ValueError("invalid connection timestamp")
        values[field] = datetime.fromisoformat(values[field])
    values["_secret_version"] = version if values["auth_mode"] is not None else None
    return ServiceConnection(**values)


def directory_pin(value: os.stat_result, previous: dict[str, object] | None = None) -> dict[str, object]:
    """Keep the persisted birth representation; mtime/ctime are not identity."""
    if type(value.st_ino) is not int or value.st_ino <= 0 or type(value.st_dev) is not int:
        raise ValueError("unusable directory identity")
    result: dict[str, object] = {"device": value.st_dev, "object": value.st_ino}
    kind = previous.get("birth_kind") if previous is not None else None
    if kind == "ns" or (previous is None and hasattr(value, "st_birthtime_ns")):
        birth = getattr(value, "st_birthtime_ns", None)
        if type(birth) is not int:
            raise ValueError("unavailable directory birth identity")
        result.update(birth_kind="ns", birth=birth)
    elif kind == "float" or (previous is None and hasattr(value, "st_birthtime")):
        birth = getattr(value, "st_birthtime", None)
        if type(birth) is not float or not math.isfinite(birth):
            raise ValueError("unavailable directory birth identity")
        result.update(birth_kind="float", birth=birth.hex())
    elif kind not in {None, "none"}:
        raise ValueError("invalid directory birth identity")
    else:
        result.update(birth_kind="none", birth=None)
    return result


def member_identity(value: os.stat_result) -> dict[str, int]:
    """Stable across a rename; content is authenticated separately."""
    identity = {"device": value.st_dev, "object": value.st_ino, "size": value.st_size, "mtime_ns": value.st_mtime_ns}
    validate_member_identity(identity)
    return identity


def validate_member_identity(value: object) -> None:
    if (
        type(value) is not dict
        or set(value) != {"device", "object", "size", "mtime_ns"}
        or any(type(item) is not int for item in value.values())
        or value["device"] < 0
        or value["object"] <= 0
        or value["size"] < 0
    ):
        raise ValueError("invalid claimed member identity")


def validate_journal(value: dict[str, Any]) -> None:
    """Reject unknown, ambiguous or counter-regressing recovery instructions."""
    if set(value) != {
        "schema",
        "phase",
        "key",
        "operation",
        "expected_workspace",
        "published_workspace",
        "before_epoch",
        "after_epoch",
        "before_record",
        "after_record",
        "before_binding",
        "after_binding",
        "ref",
        "root",
        "witness",
        "before_digest",
        "after_digest",
        "prepared_event",
        "terminal_event",
        "recovery",
        "result",
        "secret_change",
        "claims",
    }:
        raise ValueError("invalid journal members")
    if type(value["schema"]) is not int or value["schema"] != 1 or value["phase"] not in {"prepared", "committed"}:
        raise ValueError("invalid journal schema")
    if value["operation"] not in {"create", "update", "delete"} or type(value["secret_change"]) is not bool:
        raise ValueError("invalid journal operation")
    for name in ("key", "witness", "prepared_event", "terminal_event"):
        uuid_text(value[name])
    for name in ("before_epoch", "after_epoch"):
        if type(value[name]) is not int or not 0 <= value[name] <= (1 << 63) - 1:
            raise ValueError("invalid journal epoch")
    if value["after_epoch"] != value["before_epoch"] + 1:
        raise ValueError("invalid forward epoch")
    for name in ("before_digest", "after_digest"):
        if (
            type(value[name]) is not str
            or len(value[name]) != 64
            or any(c not in "0123456789abcdef" for c in value[name])
        ):
            raise ValueError("invalid service slice proof")
    for name in ("expected_workspace", "published_workspace"):
        version = value[name]
        if version is not None:
            if type(version) is not dict or set(version) != {"instance_id", "generation"}:
                raise ValueError("invalid workspace journal identity")
            if type(version["instance_id"]) is not str or str(UUID(version["instance_id"])) != version["instance_id"]:
                raise ValueError("invalid workspace journal identity")
            if type(version["generation"]) is not int or not 1 <= version["generation"] <= (1 << 63) - 1:
                raise ValueError("invalid workspace journal generation")
    ref = value["ref"]
    if type(ref) is not dict or set(ref) != {"provider_id", "connection_id"}:
        raise ValueError("invalid journal reference")
    identity = ServiceConnectionRef(ref["provider_id"], uuid_text(ref["connection_id"]))
    old, new = parse_version(value["before_binding"]), parse_version(value["after_binding"])
    for binding in (old, new):
        if binding is not None and (
            binding.connection_ref != identity or str(binding.store_incarnation) != value["root"]["incarnation"]
        ):
            raise ValueError("foreign journal binding")
    if value["secret_change"]:
        if (
            new is None
            or new.generation != (old.generation if old else 0) + 1
            or (old and old.binding_id != new.binding_id)
        ):
            raise ValueError("invalid binding advance")
    elif old != new:
        raise ValueError("unjournalled binding change")
    for side, binding in (("before", old), ("after", new)):
        if value[f"{side}_record"] is not None:
            if parse_record(value[f"{side}_record"], binding).ref != identity:
                raise ValueError("foreign journal record")
    recovery = value["recovery"]
    if recovery is not None:
        if type(recovery) is not dict or set(recovery) != {
            "before_digest",
            "after_digest",
            "after_record",
            "after_binding",
            "after_epoch",
            "witness",
        }:
            raise ValueError("invalid recovery decision")
        uuid_text(recovery["witness"])
        for name in ("before_digest", "after_digest"):
            if (
                type(recovery[name]) is not str
                or len(recovery[name]) != 64
                or any(c not in "0123456789abcdef" for c in recovery[name])
            ):
                raise ValueError("invalid recovery slice proof")
        if (
            type(recovery["after_epoch"]) is not int
            or recovery["after_epoch"]
            not in {
                value["after_epoch"],
                value["after_epoch"] + 1,
            }
            or recovery["after_epoch"] > (1 << 63) - 1
        ):
            raise ValueError("invalid recovery epoch")
        binding = parse_version(recovery["after_binding"])
        if value["secret_change"]:
            if binding is None or (
                binding.connection_ref != identity
                or binding.store_incarnation != new.store_incarnation
                or binding.binding_id != new.binding_id
                or binding.generation != new.generation + 1
                or binding.present != (old.present if old else False)
            ):
                raise ValueError("invalid compensation binding")
        elif binding != old:
            raise ValueError("invalid unchanged recovery binding")
        if recovery["after_record"] != value["before_record"]:
            raise ValueError("invalid recovery logical record")
        if recovery["after_record"] is not None:
            parse_record(recovery["after_record"], binding)
    claims = value["claims"]
    if type(claims) is not dict or set(claims) - {"new", "recovery"}:
        raise ValueError("invalid claim phases")
    for phase, claim in claims.items():
        if type(claim) is not dict or set(claim) != {"identity", "expected", "intended"}:
            raise ValueError("invalid claim intent")
        validate_member_identity(claim["identity"])
        expected, intended = parse_version(claim["expected"]), parse_version(claim["intended"])
        if not value["secret_change"] or expected is None or intended is None:
            raise ValueError("claim lacks binding authority")
        if phase == "new":
            if expected != old or intended != new:
                raise ValueError("foreign forward claim")
        elif (
            expected != new
            or intended.connection_ref != new.connection_ref
            or intended.store_incarnation != new.store_incarnation
            or intended.binding_id != new.binding_id
            or intended.generation != new.generation + 1
            or intended.present != (old.present if old else False)
            or (recovery is not None and claim["intended"] != recovery["after_binding"])
        ):
            raise ValueError("foreign compensation claim")


class TransactionFiles:
    """One held filesystem/lock scope used by the sole store orchestrator."""

    def __init__(self, root: Path) -> None:
        self.path = root
        self.stack = ExitStack()
        self.bootstrap: dict[str, Any] | None = None

    def __enter__(self) -> TransactionFiles:
        try:
            if not self.path.exists():
                self.path.mkdir(mode=0o700, parents=True)
                harden_directory(self.path)
            self.root = self.stack.enter_context(HeldOwnerDirectory(self.path, require_hardened=False))
            self.control = self.stack.enter_context(self.root.child("service-connections-state", create=True))
            self.stack.enter_context(OwnerSafeFileLock(self.control.path / "service.lock", mode=0o600))
            self.control.revalidate()
            if self.control.exists("bootstrap.json"):
                self.bootstrap = self.read(self.control, "bootstrap.json")
                self._open_private()
            elif set(os.listdir(self.control.path)) != {"service.lock"}:
                raise ValueError("unrecognised bootstrap state")
            return self
        except BaseException:
            self.stack.close()
            raise

    def __exit__(self, *args: object) -> None:
        self.stack.close()

    def initialise(self) -> None:
        """Recognise infrastructure ownership before the first owner key."""
        if self.bootstrap is not None:
            return
        if set(os.listdir(self.control.path)) != {"service.lock"}:
            raise ValueError("unrecognised bootstrap artefacts")
        self.secrets = self.stack.enter_context(self.root.child("secrets", create=True))
        self.secret_root = self.stack.enter_context(self.secrets.child("services", create=True))
        if os.listdir(self.secret_root.path):
            raise ValueError("unrecognised secret authority")
        self.bootstrap = {
            "schema": 1,
            "incarnation": str(uuid4()),
            "state_pin": directory_pin(self.control.revalidate()),
            "secret_pin": directory_pin(self.secret_root.revalidate()),
            "ready": False,
        }
        self.write(self.control, "bootstrap.json", self.bootstrap)
        for name in ("encryption.key", "recovery.key", "idempotency.key"):
            self.control.write_text(name, Fernet.generate_key().decode("ascii"))
        self.receipts = self.stack.enter_context(self.control.child("receipts", create=True))
        self.operation_keys = self.stack.enter_context(self.control.child("operation-keys", create=True))
        self.outbox = self.stack.enter_context(self.control.child("outbox", create=True))
        self.candidates = self.stack.enter_context(self.control.child("candidates", create=True))
        self.bootstrap["ready"] = True
        self.write(self.control, "bootstrap.json", self.bootstrap)
        self._load_keys()

    def _open_private(self) -> None:
        if set(self.bootstrap) != {"schema", "incarnation", "state_pin", "secret_pin", "ready"}:
            raise ValueError("invalid bootstrap")
        if (
            type(self.bootstrap["schema"]) is not int
            or self.bootstrap["schema"] != 1
            or self.bootstrap["ready"] is not True
        ):
            raise ValueError("incomplete bootstrap")
        uuid_text(self.bootstrap["incarnation"])
        self.secrets = self.stack.enter_context(self.root.child("secrets"))
        self.secret_root = self.stack.enter_context(self.secrets.child("services"))
        self.receipts = self.stack.enter_context(self.control.child("receipts"))
        self.operation_keys = self.stack.enter_context(self.control.child("operation-keys"))
        self.outbox = self.stack.enter_context(self.control.child("outbox"))
        self.candidates = self.stack.enter_context(self.control.child("candidates"))
        self.revalidate()
        self._load_keys()

    def _load_keys(self) -> None:
        self.cipher = Fernet(self.control.read_text("encryption.key", max_bytes=64).encode("ascii"))
        self.mac_key = self.control.read_text("recovery.key", max_bytes=64).encode("ascii")
        self.pepper = self.control.read_text("idempotency.key", max_bytes=64).encode("ascii")
        if len(self.mac_key) != 44 or len(self.pepper) != 44 or self.mac_key == self.pepper:
            raise ValueError("invalid independent owner keys")

    def revalidate(self) -> None:
        self.root.revalidate()
        self.control.revalidate()
        if self.bootstrap is not None:
            for key, directory in (("state_pin", self.control), ("secret_pin", self.secret_root)):
                if directory_pin(directory.revalidate(), self.bootstrap[key]) != self.bootstrap[key]:
                    raise ValueError("authority root changed")

    def root_evidence(self) -> dict[str, object]:
        self.revalidate()
        return {key: self.bootstrap[key] for key in ("incarnation", "state_pin", "secret_pin")}

    @staticmethod
    def read(directory: HeldOwnerDirectory, name: str, limit: int = MAX_ENVELOPE_BYTES) -> dict[str, Any]:
        return decode(directory.read_text(name, max_bytes=limit))

    @staticmethod
    def read_identity(directory: HeldOwnerDirectory, name: str) -> tuple[dict[str, Any], dict[str, int]]:
        text, observed = directory.read_text_with_identity(name, max_bytes=MAX_ENVELOPE_BYTES)
        return decode(text), member_identity(observed)

    @staticmethod
    def write(directory: HeldOwnerDirectory, name: str, value: object, limit: int = MAX_ENVELOPE_BYTES) -> None:
        text = canonical(value)
        if len(text.encode("utf-8")) > limit:
            raise ValueError("private envelope exceeds limit")
        directory.write_text(name, text)

    def request_mac(self, value: object) -> str:
        return hmac.new(self.pepper, ("service-request/v1\0" + canonical(value)).encode(), hashlib.sha256).hexdigest()

    def envelope(self, version: ServiceSecretVersion, credential: str | None) -> dict[str, object]:
        token = self.cipher.encrypt((credential or "").encode("utf-8")).decode("ascii")
        content = {"schema": 1, "version": version_dict(version), "ciphertext": token}
        content["mac"] = hmac.new(
            self.mac_key,
            ("service-candidate/v1\0" + canonical(content)).encode(),
            hashlib.sha256,
        ).hexdigest()
        return content

    def verify(self, envelope: dict[str, Any], expected: ServiceSecretVersion) -> None:
        if set(envelope) != {"schema", "version", "ciphertext", "mac"} or type(envelope["schema"]) is not int:
            raise ValueError("invalid candidate envelope")
        if envelope["schema"] != 1 or parse_version(envelope["version"]) != expected:
            raise ValueError("candidate identity mismatch")
        content = {key: envelope[key] for key in ("schema", "version", "ciphertext")}
        mac = hmac.new(
            self.mac_key, ("service-candidate/v1\0" + canonical(content)).encode(), hashlib.sha256
        ).hexdigest()
        if type(envelope["mac"]) is not str or not hmac.compare_digest(mac, envelope["mac"]):
            raise ValueError("candidate authentication failed")
        if type(envelope["ciphertext"]) is not str:
            raise ValueError("invalid ciphertext")
        plaintext = self.cipher.decrypt(envelope["ciphertext"].encode("ascii"))
        if (
            len(plaintext) > MAX_CREDENTIAL_BYTES
            or (expected.present and not plaintext)
            or (not expected.present and plaintext)
        ):
            raise ValueError("invalid credential envelope")

    def binding_directory(self, connection_id: str, *, create: bool = False) -> HeldOwnerDirectory:
        uuid_text(connection_id)
        return self.secret_root.child(connection_id, create=create)

    def live(self, version: ServiceSecretVersion) -> dict[str, Any]:
        with self.binding_directory(str(version.connection_ref.connection_id)) as directory:
            envelope = self.read(directory, "credential")
            self.verify(envelope, version)
            return envelope
