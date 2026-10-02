"""Dependency-neutral, immutable offline account lifecycle contracts.

No value in this module grants provider, execution or publication authority.
"""

from __future__ import annotations

import hashlib
import json
import math
import re
from collections.abc import Mapping
from dataclasses import dataclass, field
from enum import StrEnum
from types import MappingProxyType
from uuid import RFC_4122, UUID

from .account_mutation_contracts import validate_workspace_versions
from .broker_identity import INT64_MAX, BrokerSelector, CredentialVersion, _validate_selector
from .workspace_migrations import BrokerWorkspaceVersion, WorkspaceSnapshot, WorkspaceVersion

ACCOUNT_PROTOCOL_SCHEMA = 1
ACCOUNT_JSON_MAX_BYTES = 65_536
ACCOUNT_MAX_OPERATIONS = 10_000
_DATA_ROLES = frozenset(("ticks", "historical", "option_chains", "quote", "global_indices"))


class AccountContractError(ValueError):
    """Invalid lifecycle evidence, with no input reflected in the error."""

    def __init__(self) -> None:
        super().__init__("account_contract_invalid")


class AccountMutationKind(StrEnum):
    CONNECT = "connect"
    RECONNECT = "reconnect"
    ROTATE = "rotate"
    REMOVE = "remove"


class AccountOperationStage(StrEnum):
    ADMITTED = "admitted"
    AUTHENTICATION_STARTED = "authentication_started"
    PLAN_READY = "plan_ready"
    COMMITTED = "committed"
    REJECTED = "rejected"
    AUTHENTICATION_UNKNOWN = "authentication_unknown"
    BLOCKED = "blocked"


_TERMINAL = frozenset(
    (
        AccountOperationStage.COMMITTED,
        AccountOperationStage.REJECTED,
        AccountOperationStage.AUTHENTICATION_UNKNOWN,
        AccountOperationStage.BLOCKED,
    )
)


def _uuid(value: object, *, random: bool = True) -> None:
    if type(value) is not UUID or (random and (value.version != 4 or value.variant != RFC_4122)):
        raise AccountContractError


def _digest(value: object) -> None:
    if type(value) is not str or re.fullmatch(r"[0-9a-f]{64}", value) is None:
        raise AccountContractError


def _reason(value: object) -> None:
    if value is not None and (type(value) is not str or re.fullmatch(r"[a-z][a-z0-9_]{0,63}", value) is None):
        raise AccountContractError


def _freeze(value: object) -> object:
    if isinstance(value, Mapping):
        if any(type(key) is not str for key in value):
            raise AccountContractError
        return MappingProxyType({key: _freeze(item) for key, item in value.items()})
    if type(value) in (list, tuple):
        return tuple(_freeze(item) for item in value)
    if value is None or type(value) in (str, int, bool):
        return value
    if type(value) is float and math.isfinite(value):
        return value
    raise AccountContractError


def _thaw(value: object) -> object:
    if isinstance(value, Mapping):
        return {key: _thaw(item) for key, item in value.items()}
    if type(value) is tuple:
        return [_thaw(item) for item in value]
    return value


def canonical_account_json(value: object) -> str:
    """Canonical bounded JSON; refuses non-string keys and non-finite values."""
    try:
        encoded = json.dumps(
            _thaw(_freeze(value)), sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False
        )
        if len(encoded.encode("utf-8")) > ACCOUNT_JSON_MAX_BYTES:
            raise AccountContractError
        return encoded
    except (TypeError, ValueError, OverflowError, RecursionError):
        raise AccountContractError from None


def parse_account_json(value: str) -> object:
    """Read only canonical JSON; duplicate keys and alternate encodings refuse."""

    def pairs(items):
        result = {}
        for key, item in items:
            if key in result:
                raise AccountContractError
            result[key] = item
        return result

    try:
        if type(value) is not str or len(value.encode("utf-8")) > ACCOUNT_JSON_MAX_BYTES:
            raise AccountContractError
        result = json.loads(value, object_pairs_hook=pairs)
        if canonical_account_json(result) != value:
            raise AccountContractError
        return result
    except (TypeError, ValueError, OverflowError, RecursionError):
        raise AccountContractError from None


def _version_dict(value: WorkspaceVersion | BrokerWorkspaceVersion) -> dict:
    return {"instance_id": str(value.instance_id), "generation": value.generation}


def _version_from(value: object, cls: type) -> object:
    if type(value) is not dict or set(value) != {"instance_id", "generation"}:
        raise AccountContractError
    return cls(_uuid_from(value["instance_id"]), value["generation"])


def _uuid_from(value: object) -> UUID:
    if type(value) is not str:
        raise AccountContractError
    try:
        result = UUID(value)
    except ValueError:
        raise AccountContractError from None
    if str(result) != value:
        raise AccountContractError
    return result


def broker_account_digest(workspace: WorkspaceSnapshot | Mapping[str, object]) -> str:
    """Hash exactly broker liveness fields, excluding the transaction marker."""
    # Local import lets the workspace participant consume these neutral codecs.
    from .workspace_migrations import legacy_openalgo_broker_projection

    config = workspace.as_dict() if type(workspace) is WorkspaceSnapshot else _thaw(_freeze(workspace))
    if type(config) is not dict:
        raise AccountContractError
    payload = [config.get("brokers"), legacy_openalgo_broker_projection(config)]
    return hashlib.sha256(("broker-account-domain/v1\0" + canonical_account_json(payload)).encode()).hexdigest()


@dataclass(frozen=True, slots=True)
class AccountActorContext:
    actor: str
    session_binding: str

    def __post_init__(self) -> None:
        if (
            type(self.actor) is not str
            or re.fullmatch(r"[A-Za-z0-9_.:@-]{1,256}", self.actor) is None
            or type(self.session_binding) is not str
            or re.fullmatch(r"session:[0-9a-f]{64}", self.session_binding) is None
        ):
            raise AccountContractError


class _PrivateValue:
    __slots__ = ()

    def __reduce__(self):
        raise TypeError("account_private_value_not_serialisable")

    def __reduce_ex__(self, protocol):
        raise TypeError("account_private_value_not_serialisable")


@dataclass(frozen=True, slots=True)
class AccountMutationRequest(_PrivateValue):
    operation_id: UUID
    kind: AccountMutationKind
    selector: BrokerSelector
    actor: AccountActorContext
    expected_workspace: WorkspaceVersion
    expected_broker_workspace: BrokerWorkspaceVersion
    expected_credential: CredentialVersion
    broker: str
    label: str
    credentials: Mapping[str, object] | None = field(default=None, repr=False)
    data_roles: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        try:
            _uuid(self.operation_id)
            _validate_selector(self.selector)
            if type(self.kind) is not AccountMutationKind or type(self.actor) is not AccountActorContext:
                raise AccountContractError
            self.actor.__post_init__()
            validate_workspace_versions(self.expected_workspace, self.expected_broker_workspace)
            if type(self.expected_credential) is not CredentialVersion:
                raise AccountContractError
            self.expected_credential.__post_init__()
            if (
                self.expected_credential.selector != self.selector
                or self.selector.adapter_id == "openalgo"
                or type(self.broker) is not str
                or self.broker != self.selector.adapter_id
                or type(self.label) is not str
                or len(self.label) > 256
                or type(self.data_roles) is not tuple
                or len(self.data_roles) > len(_DATA_ROLES)
                or len(set(self.data_roles)) != len(self.data_roles)
                or any(type(role) is not str or role not in _DATA_ROLES for role in self.data_roles)
            ):
                raise AccountContractError
            if self.kind is AccountMutationKind.REMOVE and (self.credentials is not None or self.data_roles):
                raise AccountContractError
            if self.credentials is not None:
                if not isinstance(self.credentials, Mapping):
                    raise AccountContractError
                object.__setattr__(self, "credentials", _freeze(self.credentials))
            canonical_account_json(_request_dict(self))
        except (ValueError, TypeError, RecursionError):
            raise AccountContractError from None


def _request_dict(value: AccountMutationRequest, *, private: bool = True) -> dict:
    result = {
        "operation_id": str(value.operation_id),
        "kind": value.kind.value,
        "selector": {"adapter_id": value.selector.adapter_id, "account_id": value.selector.account_id},
        "actor": {"actor": value.actor.actor, "session_binding": value.actor.session_binding},
        "expected_workspace": _version_dict(value.expected_workspace),
        "expected_broker_workspace": _version_dict(value.expected_broker_workspace),
        "expected_credential": {
            "vault_incarnation": str(value.expected_credential.vault_incarnation),
            "generation": value.expected_credential.generation,
        },
        "broker": value.broker,
        "label": value.label,
        "data_roles": list(value.data_roles),
    }
    if private:
        result["credentials"] = _thaw(value.credentials)
    return result


def _request_from(value: dict) -> AccountMutationRequest:
    try:
        selector = BrokerSelector(**value["selector"])
        result = AccountMutationRequest(
            _uuid_from(value["operation_id"]),
            AccountMutationKind(value["kind"]),
            selector,
            AccountActorContext(**value["actor"]),
            _version_from(value["expected_workspace"], WorkspaceVersion),
            _version_from(value["expected_broker_workspace"], BrokerWorkspaceVersion),
            CredentialVersion(
                selector,
                _uuid_from(value["expected_credential"]["vault_incarnation"]),
                value["expected_credential"]["generation"],
            ),
            value["broker"],
            value["label"],
            value["credentials"],
            tuple(value["data_roles"]),
        )
        if _request_dict(result) != value:
            raise AccountContractError
        return result
    except (KeyError, TypeError, ValueError):
        raise AccountContractError from None


@dataclass(frozen=True, slots=True)
class BrokerAccountWitness:
    schema: int
    workspace_instance: UUID
    vault_incarnation: UUID
    operation_id: UUID
    epoch: int
    before_digest: str
    after_digest: str
    commit_workspace: WorkspaceVersion
    commit_broker_workspace: BrokerWorkspaceVersion

    def __post_init__(self) -> None:
        _uuid(self.workspace_instance, random=False)
        _uuid(self.vault_incarnation)
        _uuid(self.operation_id)
        _digest(self.before_digest)
        _digest(self.after_digest)
        validate_workspace_versions(self.commit_workspace, self.commit_broker_workspace)
        if (
            type(self.schema) is not int
            or self.schema != ACCOUNT_PROTOCOL_SCHEMA
            or type(self.epoch) is not int
            or not 0 <= self.epoch <= INT64_MAX
            or self.workspace_instance != self.commit_workspace.instance_id
            or (self.epoch == 0 and self.before_digest != self.after_digest)
        ):
            raise AccountContractError

    def to_dict(self) -> dict:
        return {
            "schema": self.schema,
            "workspace_instance": str(self.workspace_instance),
            "vault_incarnation": str(self.vault_incarnation),
            "operation_id": str(self.operation_id),
            "epoch": self.epoch,
            "before_digest": self.before_digest,
            "after_digest": self.after_digest,
            "commit_workspace": _version_dict(self.commit_workspace),
            "commit_broker_workspace": _version_dict(self.commit_broker_workspace),
        }

    def to_json(self) -> str:
        return canonical_account_json(self.to_dict())

    @classmethod
    def from_dict(cls, value: dict) -> BrokerAccountWitness:
        try:
            if type(value) is not dict or set(value) != set(cls.__dataclass_fields__):
                raise AccountContractError
            return cls(
                value["schema"],
                _uuid_from(value["workspace_instance"]),
                _uuid_from(value["vault_incarnation"]),
                _uuid_from(value["operation_id"]),
                value["epoch"],
                value["before_digest"],
                value["after_digest"],
                _version_from(value["commit_workspace"], WorkspaceVersion),
                _version_from(value["commit_broker_workspace"], BrokerWorkspaceVersion),
            )
        except (ValueError, TypeError, KeyError):
            raise AccountContractError from None

    @classmethod
    def from_json(cls, value: str) -> BrokerAccountWitness:
        return cls.from_dict(parse_account_json(value))


@dataclass(frozen=True, slots=True)
class AccountEnrolmentIntent:
    workspace_instance: UUID
    vault_incarnation: UUID
    operation_id: UUID
    expected_workspace: WorkspaceVersion
    expected_broker_workspace: BrokerWorkspaceVersion
    before_digest: str

    def __post_init__(self) -> None:
        _uuid(self.workspace_instance, random=False)
        _uuid(self.vault_incarnation)
        _uuid(self.operation_id)
        _digest(self.before_digest)
        validate_workspace_versions(self.expected_workspace, self.expected_broker_workspace)
        if self.workspace_instance != self.expected_workspace.instance_id:
            raise AccountContractError

    def to_dict(self) -> dict:
        return {
            "workspace_instance": str(self.workspace_instance),
            "vault_incarnation": str(self.vault_incarnation),
            "operation_id": str(self.operation_id),
            "before_digest": self.before_digest,
            "expected_workspace": _version_dict(self.expected_workspace),
            "expected_broker_workspace": _version_dict(self.expected_broker_workspace),
        }

    @classmethod
    def from_dict(cls, value: dict) -> AccountEnrolmentIntent:
        try:
            if type(value) is not dict or set(value) != set(cls.__dataclass_fields__):
                raise AccountContractError
            return cls(
                _uuid_from(value["workspace_instance"]),
                _uuid_from(value["vault_incarnation"]),
                _uuid_from(value["operation_id"]),
                _version_from(value["expected_workspace"], WorkspaceVersion),
                _version_from(value["expected_broker_workspace"], BrokerWorkspaceVersion),
                value["before_digest"],
            )
        except (ValueError, TypeError, KeyError):
            raise AccountContractError from None


@dataclass(frozen=True, slots=True)
class AccountMutationReceipt:
    operation_id: UUID
    selector: BrokerSelector
    kind: AccountMutationKind
    state: AccountOperationStage
    reason: str | None
    credential_version: CredentialVersion | None
    commit_workspace: WorkspaceVersion | None
    commit_broker_workspace: BrokerWorkspaceVersion | None

    def __post_init__(self) -> None:
        _uuid(self.operation_id)
        _validate_selector(self.selector)
        _reason(self.reason)
        if (
            type(self.kind) is not AccountMutationKind
            or type(self.state) is not AccountOperationStage
            or self.state not in _TERMINAL
        ):
            raise AccountContractError
        if self.state is AccountOperationStage.COMMITTED:
            validate_workspace_versions(self.commit_workspace, self.commit_broker_workspace)
            if type(self.credential_version) is not CredentialVersion:
                raise AccountContractError
            self.credential_version.__post_init__()
            if self.credential_version.selector != self.selector or not self.credential_version.generation:
                raise AccountContractError
        elif any(
            value is not None
            for value in (self.credential_version, self.commit_workspace, self.commit_broker_workspace)
        ):
            raise AccountContractError


@dataclass(frozen=True, slots=True)
class AccountOperationSnapshot:
    operation_id: UUID
    selector: BrokerSelector
    kind: AccountMutationKind
    actor: AccountActorContext
    state: AccountOperationStage
    expected_workspace: WorkspaceVersion
    expected_broker_workspace: BrokerWorkspaceVersion
    expected_credential: CredentialVersion
    witness: BrokerAccountWitness | None = None
    receipt: AccountMutationReceipt | None = None
    abandoned: bool = False
    abandonment_committed: bool = False
    abandonment_reason: str | None = None
    before_digest: str | None = None
    after_digest: str | None = None
    workspace_attempted: bool = False
    workspace_conflicted: bool = False

    def __post_init__(self) -> None:
        _uuid(self.operation_id)
        _validate_selector(self.selector)
        validate_workspace_versions(self.expected_workspace, self.expected_broker_workspace)
        if (
            type(self.kind) is not AccountMutationKind
            or type(self.state) is not AccountOperationStage
            or type(self.actor) is not AccountActorContext
            or type(self.expected_credential) is not CredentialVersion
            or self.expected_credential.selector != self.selector
            or type(self.abandoned) is not bool
            or type(self.abandonment_committed) is not bool
            or (self.abandonment_committed and not self.abandoned)
            or type(self.workspace_attempted) is not bool
            or type(self.workspace_conflicted) is not bool
            or self.workspace_conflicted and not self.workspace_attempted
            or self.workspace_attempted and (
                self.state not in (AccountOperationStage.PLAN_READY, AccountOperationStage.COMMITTED)
                or self.before_digest is None or self.after_digest is None
            )
            or self.state is AccountOperationStage.COMMITTED and not self.workspace_attempted
            or self.abandonment_committed and not self.workspace_attempted
        ):
            raise AccountContractError
        self.actor.__post_init__()
        self.expected_credential.__post_init__()
        _reason(self.abandonment_reason)
        if self.abandoned != (self.abandonment_reason is not None):
            raise AccountContractError
        for digest in (self.before_digest, self.after_digest):
            if digest is not None:
                _digest(digest)
        if (self.before_digest is None) != (self.after_digest is None):
            raise AccountContractError
        if self.witness is not None:
            if type(self.witness) is not BrokerAccountWitness or self.witness.operation_id != self.operation_id:
                raise AccountContractError
            self.witness.__post_init__()
        if self.receipt is not None:
            if type(self.receipt) is not AccountMutationReceipt:
                raise AccountContractError
            self.receipt.__post_init__()
            if (self.receipt.operation_id, self.receipt.selector, self.receipt.kind, self.receipt.state) != (
                self.operation_id,
                self.selector,
                self.kind,
                self.state,
            ):
                raise AccountContractError
        if (self.state in _TERMINAL) != (self.receipt is not None):
            raise AccountContractError


@dataclass(frozen=True, slots=True)
class AccountMutationOutcome:
    receipt: AccountMutationReceipt
    runtime_status: str

    def __post_init__(self) -> None:
        if (
            type(self.receipt) is not AccountMutationReceipt
            or type(self.runtime_status) is not str
            or self.runtime_status not in {"ready", "removed", "session_unavailable", "cleanup_pending", "blocked"}
        ):
            raise AccountContractError
        self.receipt.__post_init__()
