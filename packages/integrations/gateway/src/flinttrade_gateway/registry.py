"""Provider-free exact registry state and owner-bound publication capabilities."""

from __future__ import annotations

import math
import threading
import time
import weakref
from dataclasses import dataclass
from typing import Any
from uuid import uuid4

from flinttrade_core.account_mutation_contracts import (
    BrokerAccountAmbiguousError,
    RegistryCapabilityError,
    RegistrySelectorVersion,
    RegistrySessionUnavailable,
    RegistryVersionConflict,
    RegistryVersionValidationError,
    SessionVersion,
    validate_workspace_versions,
)
from flinttrade_core.broker_account_cutover import MutationAdmission, require_broker_account_mutations
from flinttrade_core.broker_identity import INT64_MAX, BrokerSelector, CredentialVersion, _validate_selector
from flinttrade_core.workspace_migrations import (
    BrokerWorkspaceVersion,
    WorkspaceSnapshot,
    WorkspaceVersion,
    broker_workspace_version,
    legacy_openalgo_broker_projection,
)

from .adapter import BROKER_CATALOG
from .brokers._base import Session
from .exceptions import BrokerNotFoundError
from .models import AccountStatus, BrokerAccountInfo, BrokerInfo
from .session import BrokerSession

_DEFAULT = BrokerSelector("openalgo", "default")


@dataclass(frozen=True)
class ManagedLookupAuthority:
    credential_version: CredentialVersion
    broker_workspace_version: BrokerWorkspaceVersion

    def __post_init__(self) -> None:
        if type(self.credential_version) is not CredentialVersion or not self.credential_version.generation:
            raise RegistryVersionValidationError
        self.credential_version.__post_init__()
        broker = self.broker_workspace_version
        if type(broker) is not BrokerWorkspaceVersion:
            raise RegistryVersionValidationError
        validate_workspace_versions(WorkspaceVersion(broker.instance_id, broker.generation), broker)


@dataclass(frozen=True)
class ManagedSessionAuthority:
    credential_version: CredentialVersion
    workspace_version: WorkspaceVersion
    broker_workspace_version: BrokerWorkspaceVersion

    def __post_init__(self) -> None:
        ManagedLookupAuthority(self.credential_version, self.broker_workspace_version)
        validate_workspace_versions(self.workspace_version, self.broker_workspace_version)


class _OpaqueReceipt:
    __slots__ = ("__weakref__",)

    def __repr__(self) -> str:
        return f"<{type(self).__name__}>"

    def __reduce_ex__(self, protocol: int) -> Any:
        raise TypeError("registry_capability_not_serialisable")


class PreparedRegistryCandidateReceipt(_OpaqueReceipt):
    """Identity-sealed single-use preparation capability."""


class RegistryRetirementReceipt(_OpaqueReceipt):
    """Identity-sealed single-use claim on quarantined payload."""


class OpenAlgoDefaultCompatibilityAuthorityReceipt(_OpaqueReceipt):
    """Caller-lifetime seal; private OpenAlgo authority never renders."""


@dataclass(frozen=True)
class OpenAlgoDefaultCompatibilitySessionVersion:
    selector: BrokerSelector
    registry_version: RegistrySelectorVersion
    workspace_version: WorkspaceVersion
    broker_workspace_version: BrokerWorkspaceVersion

    def __post_init__(self) -> None:
        if self.selector != _DEFAULT or type(self.registry_version) is not RegistrySelectorVersion:
            raise RegistryVersionValidationError
        self.registry_version.__post_init__()
        if self.registry_version.selector != _DEFAULT or not self.registry_version.present:
            raise RegistryVersionValidationError
        validate_workspace_versions(self.workspace_version, self.broker_workspace_version)


Binding = SessionVersion | OpenAlgoDefaultCompatibilitySessionVersion
SessionPublicationAuthority = ManagedSessionAuthority | OpenAlgoDefaultCompatibilityAuthorityReceipt


@dataclass(frozen=True)
class ExactRegistryState:
    selector: BrokerSelector
    registry_version: RegistrySelectorVersion
    binding: Binding | None
    broker: str | None
    label: str
    status: str
    expires_at: float | None
    read_only: bool | None


@dataclass(frozen=True)
class RegistryPublishResult:
    version: Binding
    retired: RegistryRetirementReceipt | None


@dataclass(frozen=True)
class RegistryRemoveResult:
    version: RegistrySelectorVersion
    retired: RegistryRetirementReceipt | None


@dataclass(frozen=True, repr=False)
class RetiredRegistryCandidate:
    selector: BrokerSelector
    session: Session | BrokerSession
    client: object | None

    def __repr__(self) -> str:
        return "<RetiredRegistryCandidate>"

    def __reduce_ex__(self, protocol: int) -> Any:
        raise TypeError("registry_payload_not_serialisable")


@dataclass(repr=False)
class _Record:
    selector: BrokerSelector
    session: Session | BrokerSession
    client: object | None
    expected: RegistrySelectorVersion
    authority: ManagedSessionAuthority | _CompatibilityAuthority
    broker: str | None
    label: str
    binding: Binding | None = None


@dataclass(frozen=True, repr=False)
class _CompatibilityAuthority:
    workspace_version: WorkspaceVersion
    broker_workspace_version: BrokerWorkspaceVersion
    projection: Any


class ConnectedRegistrySession(_OpaqueReceipt):
    """Sealed canonical adapter view; logical identity is independent of raw ID."""

    __slots__ = ("_record",)

    def __init__(self, record: _Record) -> None:
        self._record = record

    @property
    def selector(self) -> BrokerSelector:
        return self._record.selector

    @property
    def version(self) -> Binding:
        return self._record.binding

    @property
    def access_token(self) -> str:
        return self._record.session.access_token

    @property
    def expires_at(self) -> float:
        return self._record.session.expires_at

    @property
    def account_id(self) -> str:
        return self._record.session.account_id

    @property
    def adapter_id(self) -> str:
        return self._record.session.adapter_id

    @property
    def extra(self) -> dict[str, Any]:
        return self._record.session.extra

    @property
    def read_only_until_at(self) -> float | None:
        return self._record.session.read_only_until_at

    @property
    def is_read_only(self) -> bool:
        return self._record.session.is_read_only

    def is_expiring_soon(self, leeway_seconds: int = 60) -> bool:
        return self._record.session.is_expiring_soon(leeway_seconds)

    @property
    def algo_id(self) -> str:
        return self._record.session.algo_id

    @algo_id.setter
    def algo_id(self, value: str) -> None:
        self._record.session.algo_id = value


class BrokerRegistry:
    """Own exact records; compatibility dictionaries are derived projections."""

    def __init__(
        self,
        *,
        mutation_admission: MutationAdmission = require_broker_account_mutations,
        publication_owner_token: object | None = None,
    ) -> None:
        self._mutation_admission = mutation_admission
        self._owner_token = publication_owner_token
        self._incarnation = uuid4()
        self._lock = threading.RLock()
        self._history: dict[BrokerSelector, RegistrySelectorVersion] = {}
        self._records: dict[BrokerSelector, _Record] = {}
        self._metadata: dict[BrokerSelector, tuple[str | None, str]] = {}
        self._prepared: dict[PreparedRegistryCandidateReceipt, _Record] = {}
        self._retired: dict[RegistryRetirementReceipt, _Record] = {}
        self._authorities: weakref.WeakKeyDictionary = weakref.WeakKeyDictionary()
        self._handles: weakref.WeakKeyDictionary = weakref.WeakKeyDictionary()
        self._clients: dict[int, tuple[object, BrokerSelector, object]] = {}
        self._default_selector: BrokerSelector | None = None
        self._default_workspace: WorkspaceVersion | None = None
        self._sessions: dict[str, BrokerSession] = {}
        self._adapter_sessions: dict[tuple[str, str], Session] = {}
        self._primary: str | None = None

    def _owner(self, token: object) -> None:
        if self._owner_token is None or token is not self._owner_token:
            raise RegistryCapabilityError

    def snapshot_selector(self, selector: BrokerSelector) -> RegistrySelectorVersion:
        _validate_selector(selector)
        with self._lock:
            return self._history.get(selector, RegistrySelectorVersion(selector, self._incarnation, 0, False))

    def _expect(self, selector: BrokerSelector, expected: RegistrySelectorVersion) -> None:
        if type(expected) is not RegistrySelectorVersion:
            raise RegistryVersionValidationError
        expected.__post_init__()
        if (
            expected.selector != selector
            or expected != self.snapshot_selector(selector)
            or expected.generation == INT64_MAX
        ):
            raise RegistryVersionConflict

    def _authority(self, authority: SessionPublicationAuthority) -> ManagedSessionAuthority | _CompatibilityAuthority:
        if type(authority) is ManagedSessionAuthority:
            authority.__post_init__()
            return authority
        if type(authority) is OpenAlgoDefaultCompatibilityAuthorityReceipt and authority in self._authorities:
            return self._authorities[authority]
        raise RegistryCapabilityError

    def seal_openalgo_default_compatibility_authority(
        self, workspace_snapshot: WorkspaceSnapshot, *, owner_token: object
    ) -> OpenAlgoDefaultCompatibilityAuthorityReceipt:
        self._owner(owner_token)
        if type(workspace_snapshot) is not WorkspaceSnapshot:
            raise RegistryVersionValidationError
        broker = broker_workspace_version(workspace_snapshot)
        validate_workspace_versions(workspace_snapshot.version, broker)
        authority = _CompatibilityAuthority(
            workspace_snapshot.version, broker, legacy_openalgo_broker_projection(workspace_snapshot.as_dict())
        )
        receipt = OpenAlgoDefaultCompatibilityAuthorityReceipt()
        with self._lock:
            self._authorities[receipt] = authority
        return receipt

    def _prepare(
        self,
        selector: BrokerSelector,
        session: object,
        expected: RegistrySelectorVersion,
        authority: ManagedSessionAuthority | _CompatibilityAuthority,
        client: object | None,
        broker: str | None,
        label: str,
    ) -> PreparedRegistryCandidateReceipt:
        _validate_selector(selector)
        if callable(client):
            raise RegistryVersionValidationError
        if type(expected) is not RegistrySelectorVersion:
            raise RegistryVersionValidationError
        expected.__post_init__()
        if expected.selector != selector:
            raise RegistryVersionValidationError
        if (
            not isinstance(session, (Session, BrokerSession))
            or (broker is not None and type(broker) is not str)
            or type(label) is not str
        ):
            raise RegistryVersionValidationError
        if isinstance(session, Session):
            if (
                session.adapter_id != selector.adapter_id
                or type(session.expires_at) not in (int, float)
                or not math.isfinite(session.expires_at)
            ):
                raise RegistryVersionValidationError
        if isinstance(session, BrokerSession) and selector.adapter_id != "openalgo":
            raise RegistryVersionValidationError
        if type(authority) is ManagedSessionAuthority and authority.credential_version.selector != selector:
            raise RegistryVersionValidationError
        client_binding = authority if selector != _DEFAULT else _DEFAULT
        if client is not None:
            owned = self._clients.get(id(client))
            if owned is not None and (owned[1] != selector or owned[2] != client_binding):
                raise RegistrySessionUnavailable
        receipt = PreparedRegistryCandidateReceipt()
        self._prepared[receipt] = _Record(selector, session, client, expected, authority, broker, label)
        if client is not None:
            self._clients[id(client)] = (client, selector, client_binding)
        return receipt

    def prepare_session_candidate(
        self,
        selector: BrokerSelector,
        session: object,
        *,
        expected_registry: RegistrySelectorVersion,
        authority: ManagedSessionAuthority,
        broker: str | None,
        label: str,
        client: object | None = None,
        owner_token: object,
    ) -> PreparedRegistryCandidateReceipt:
        self._owner(owner_token)
        with self._lock:
            if type(authority) is not ManagedSessionAuthority or selector == _DEFAULT:
                raise RegistryVersionValidationError
            authority.__post_init__()
            return self._prepare(selector, session, expected_registry, authority, client, broker, label)

    def prepare_openalgo_default_compatibility_candidate(
        self,
        session: object,
        *,
        expected_registry: RegistrySelectorVersion,
        authority: OpenAlgoDefaultCompatibilityAuthorityReceipt,
        client: object,
        broker: str | None,
        label: str,
        owner_token: object,
    ) -> PreparedRegistryCandidateReceipt:
        self._owner(owner_token)
        with self._lock:
            sealed = self._authority(authority)
            if type(sealed) is not _CompatibilityAuthority or not isinstance(session, Session) or client is None:
                raise RegistryCapabilityError
            return self._prepare(_DEFAULT, session, expected_registry, sealed, client, broker, label)

    def _retire(self, record: _Record) -> RegistryRetirementReceipt:
        receipt = RegistryRetirementReceipt()
        self._retired[receipt] = record
        return receipt

    def publish_prepared_candidate(
        self,
        receipt: PreparedRegistryCandidateReceipt,
        *,
        current_authority: SessionPublicationAuthority,
        owner_token: object,
    ) -> RegistryPublishResult:
        self._owner(owner_token)
        with self._lock:
            if type(receipt) is not PreparedRegistryCandidateReceipt or receipt not in self._prepared:
                raise RegistryCapabilityError
            current = self._authority(current_authority)
            record = self._prepared.pop(receipt)
            try:
                self._expect(record.selector, record.expected)
                if current != record.authority:
                    raise RegistryVersionConflict
            except (RegistryVersionConflict, RegistryVersionValidationError):
                raise RegistryVersionConflict(retirement_receipt=self._retire(record)) from None
            version = RegistrySelectorVersion(record.selector, self._incarnation, record.expected.generation + 1, True)
            if type(current) is ManagedSessionAuthority:
                binding = SessionVersion(
                    record.selector,
                    version,
                    current.credential_version,
                    current.workspace_version,
                    current.broker_workspace_version,
                )
            else:
                binding = OpenAlgoDefaultCompatibilitySessionVersion(
                    record.selector, version, current.workspace_version, current.broker_workspace_version
                )
            previous = self._records.get(record.selector)
            retired = self._retire(previous) if previous is not None else None
            record.binding = binding
            self._records[record.selector] = record
            self._history[record.selector] = version
            self._metadata[record.selector] = (record.broker, record.label)
            self._project()
            return RegistryPublishResult(binding, retired)

    def abandon_prepared_candidate(
        self, receipt: PreparedRegistryCandidateReceipt, *, owner_token: object
    ) -> RegistryRetirementReceipt:
        self._owner(owner_token)
        with self._lock:
            if type(receipt) is not PreparedRegistryCandidateReceipt or receipt not in self._prepared:
                raise RegistryCapabilityError
            return self._retire(self._prepared.pop(receipt))

    def remove_session_for_exact(
        self, selector: BrokerSelector, *, expected_registry: RegistrySelectorVersion, owner_token: object
    ) -> RegistryRemoveResult:
        self._owner(owner_token)
        _validate_selector(selector)
        with self._lock:
            self._expect(selector, expected_registry)
            version = RegistrySelectorVersion(selector, self._incarnation, expected_registry.generation + 1, False)
            previous = self._records.pop(selector, None)
            retired = self._retire(previous) if previous is not None else None
            self._history[selector] = version
            self._project()
            return RegistryRemoveResult(version, retired)

    def claim_retired_candidate(
        self, receipt: RegistryRetirementReceipt, *, owner_token: object
    ) -> RetiredRegistryCandidate:
        self._owner(owner_token)
        with self._lock:
            if type(receipt) is not RegistryRetirementReceipt or receipt not in self._retired:
                raise RegistryCapabilityError
            record = self._retired.pop(receipt)
            if record.client is not None:
                retained = (*self._records.values(), *self._prepared.values(), *self._retired.values())
                if not any(other.client is record.client for other in retained):
                    self._clients.pop(id(record.client), None)
            return RetiredRegistryCandidate(record.selector, record.session, record.client)

    @staticmethod
    def _valid_expiry(session: Session) -> bool:
        expiry = session.expires_at
        return type(expiry) in (int, float) and math.isfinite(expiry)

    def _status(self, record: _Record) -> str:
        if isinstance(record.session, Session):
            if not self._valid_expiry(record.session):
                return "disconnected"
            return "connected" if record.session.expires_at > time.time() else "expired"
        status = record.session.info.status
        return (
            "expired"
            if status == AccountStatus.token_expired
            else "connected"
            if record.session.is_connected
            else "disconnected"
        )

    def _connected(
        self, selector: BrokerSelector, authority: ManagedLookupAuthority | OpenAlgoDefaultCompatibilityAuthorityReceipt
    ) -> _Record:
        record = self._records.get(selector)
        if record is None or not isinstance(record.session, Session) or self._status(record) != "connected":
            raise RegistrySessionUnavailable
        if type(record.authority) is ManagedSessionAuthority:
            if type(authority) is not ManagedLookupAuthority:
                raise RegistrySessionUnavailable
            authority.__post_init__()
            if (
                authority.credential_version != record.authority.credential_version
                or authority.broker_workspace_version != record.authority.broker_workspace_version
            ):
                raise RegistrySessionUnavailable
        else:
            try:
                current = self._authority(authority)
            except RegistryCapabilityError:
                raise RegistrySessionUnavailable from None
            if (
                type(current) is not _CompatibilityAuthority
                or current.broker_workspace_version != record.authority.broker_workspace_version
                or current.projection != record.authority.projection
            ):
                raise RegistrySessionUnavailable
        return record

    def get_connected_session_for(
        self,
        selector: BrokerSelector,
        *,
        current_authority: ManagedLookupAuthority | OpenAlgoDefaultCompatibilityAuthorityReceipt,
    ) -> ConnectedRegistrySession:
        _validate_selector(selector)
        with self._lock:
            record = self._connected(selector, current_authority)
            handle = ConnectedRegistrySession(record)
            self._handles[handle] = record.binding.registry_version
            return handle

    def client_for_connected_session(
        self,
        session: ConnectedRegistrySession,
        *,
        current_authority: ManagedLookupAuthority | OpenAlgoDefaultCompatibilityAuthorityReceipt,
    ) -> object:
        with self._lock:
            if type(session) is not ConnectedRegistrySession or session not in self._handles:
                raise RegistrySessionUnavailable
            record = self._connected(session.selector, current_authority)
            if self._handles[session] != record.binding.registry_version or record.client is None:
                raise RegistrySessionUnavailable
            return record.client

    def snapshot_exact_state(self, selector: BrokerSelector) -> ExactRegistryState | None:
        """Detached metadata for a seen selector; unseen alone returns None."""
        _validate_selector(selector)
        with self._lock:
            version = self._history.get(selector)
            if version is None:
                return None
            record = self._records.get(selector)
            canonical = (
                record is not None and isinstance(record.session, Session) and self._valid_expiry(record.session)
            )
            return ExactRegistryState(
                selector,
                version,
                record.binding if record else None,
                *self._metadata.get(selector, (None, "")),
                self._status(record) if record else "tombstoned",
                float(record.session.expires_at) if canonical else None,
                record.session.is_read_only if canonical else None,
            )

    def list_exact_states(self) -> tuple[ExactRegistryState, ...]:
        with self._lock:
            return tuple(self.snapshot_exact_state(selector) for selector in sorted(self._history))

    def set_execution_default_projection(
        self, selector: BrokerSelector | None, *, workspace_version: WorkspaceVersion, owner_token: object
    ) -> None:
        self._owner(owner_token)
        if selector is not None:
            _validate_selector(selector)
        if type(workspace_version) is not WorkspaceVersion:
            raise RegistryVersionValidationError
        validate_workspace_versions(
            workspace_version, BrokerWorkspaceVersion(workspace_version.instance_id, workspace_version.generation)
        )
        with self._lock:
            old = self._default_workspace
            if old is not None and (
                old.instance_id != workspace_version.instance_id
                or old.generation > workspace_version.generation
                or (old == workspace_version and selector != self._default_selector)
            ):
                raise RegistryVersionConflict
            self._default_workspace = workspace_version
            self._default_selector = selector
            self._project()

    def _project(self) -> None:
        counts: dict[str, int] = {}
        for selector in self._records:
            counts[selector.account_id] = counts.get(selector.account_id, 0) + 1
        self._sessions = {
            selector.account_id: record.session
            for selector, record in self._records.items()
            if counts[selector.account_id] == 1 and isinstance(record.session, BrokerSession)
        }
        self._adapter_sessions = {
            (selector.adapter_id, selector.account_id): record.session
            for selector, record in self._records.items()
            if isinstance(record.session, Session)
        }
        self._primary = self._default_selector.account_id if self._default_selector in self._records else None

    def get_supported_brokers(self) -> list[BrokerInfo]:
        return [info for info in BROKER_CATALOG.values() if not info.is_sandbox]

    def _unversioned_unavailable(self, *args: Any, **kwargs: Any) -> Any:
        self._mutation_admission()
        raise RegistrySessionUnavailable

    add_account = _unversioned_unavailable
    reconnect_account = _unversioned_unavailable
    remove_account = _unversioned_unavailable
    set_primary = _unversioned_unavailable
    put_session = _unversioned_unavailable
    remove_session_for = _unversioned_unavailable

    def get_session(self, account_id: str) -> BrokerSession:
        with self._lock:
            matches = [record for selector, record in self._records.items() if selector.account_id == account_id]
            if len(matches) > 1:
                raise BrokerAccountAmbiguousError
            if not matches:
                raise BrokerNotFoundError("broker_session_missing")
            if not isinstance(matches[0].session, BrokerSession):
                raise RegistrySessionUnavailable
            return matches[0].session

    def get_session_for(self, adapter_id: str, account_id: str) -> Any:
        """Unversioned raw canonical lookup cannot grant routing authority."""
        BrokerSelector(adapter_id, account_id)
        raise RegistrySessionUnavailable

    def get_primary_session(self) -> BrokerSession:
        with self._lock:
            record = self._records.get(self._default_selector)
            if record is None or not isinstance(record.session, BrokerSession):
                raise RegistrySessionUnavailable
            return record.session

    def get_primary_account_id(self) -> str | None:
        with self._lock:
            return self._primary

    def is_connected(self) -> bool:
        return any(state.status == "connected" for state in self.list_exact_states())

    def list_connected_adapter_sessions(self) -> list[tuple[str, str, Any]]:
        raise RegistrySessionUnavailable

    def list_accounts(self) -> list[BrokerAccountInfo]:
        return [
            BrokerAccountInfo(
                adapter_id=state.selector.adapter_id,
                account_id=state.selector.account_id,
                broker=state.broker,
                label=state.label,
                status=AccountStatus.token_expired if state.status == "expired" else AccountStatus(state.status),
                is_primary=state.selector == self._default_selector,
            )
            for state in self.list_exact_states()
            if state.registry_version.present
        ]

    def list_sessions(self) -> list[dict[str, Any]]:
        return [
            {
                "adapter_id": state.selector.adapter_id,
                "account_id": state.selector.account_id,
                "broker": state.broker,
                "is_connected": state.status == "connected",
            }
            for state in self.list_exact_states()
            if state.registry_version.present
        ]

    def get_positions(self, account_id: str) -> Any:
        return self.get_session(account_id).get_positions()

    def get_orders(self, account_id: str) -> Any:
        return self.get_session(account_id).get_orders()

    def get_trades(self, account_id: str) -> Any:
        return self.get_session(account_id).get_trades()

    def get_holdings(self, account_id: str) -> Any:
        return self.get_session(account_id).get_holdings()

    def get_funds(self, account_id: str) -> Any:
        return self.get_session(account_id).get_funds()

    def get_margin(self, account_id: str, order_data: dict[str, Any]) -> Any:
        return self.get_session(account_id).get_margin(order_data)

    def get_quotes(self, account_id: str, symbol: str, exchange: str) -> Any:
        return self.get_session(account_id).get_quotes([symbol])

    def get_depth(self, account_id: str, symbol: str) -> Any:
        return self.get_session(account_id).get_depth(symbol)

    def get_history(self, account_id: str, params: dict[str, Any]) -> Any:
        return self.get_session(account_id).get_history(params)

    def get_option_chain(self, account_id: str, params: dict[str, Any]) -> Any:
        return self.get_session(account_id).get_option_chain(params)

    def search_symbols(self, account_id: str, query: str) -> Any:
        return self.get_session(account_id).search_symbols(query)


class RegistryPublicationOwner:
    """One registry's capability holder; retains every unclaimed retirement."""

    def __init__(self, registry: BrokerRegistry, token: object) -> None:
        registry._owner(token)
        self._registry = registry
        self._token = token
        self._retirements: set[RegistryRetirementReceipt] = set()

    def owns(self, registry: BrokerRegistry) -> bool:
        return self._registry is registry

    def _call(self, method: str, *args: Any, **kwargs: Any) -> Any:
        try:
            result = getattr(self._registry, method)(*args, owner_token=self._token, **kwargs)
        except RegistryVersionConflict as exc:
            if exc.retirement_receipt is not None:
                self.retain_retirement(exc.retirement_receipt)
            raise
        if isinstance(result, (RegistryPublishResult, RegistryRemoveResult)) and result.retired is not None:
            self.retain_retirement(result.retired)
        if type(result) is RegistryRetirementReceipt:
            self.retain_retirement(result)
        return result

    def retain_retirement(self, receipt: RegistryRetirementReceipt) -> None:
        if type(receipt) is not RegistryRetirementReceipt or receipt not in self._registry._retired:
            raise RegistryCapabilityError
        self._retirements.add(receipt)

    def prepare_session_candidate(self, *args: Any, **kwargs: Any) -> PreparedRegistryCandidateReceipt:
        return self._call("prepare_session_candidate", *args, **kwargs)

    def prepare_openalgo_default_compatibility_candidate(
        self, *args: Any, **kwargs: Any
    ) -> PreparedRegistryCandidateReceipt:
        return self._call("prepare_openalgo_default_compatibility_candidate", *args, **kwargs)

    def seal_openalgo_default_compatibility_authority(
        self, *args: Any, **kwargs: Any
    ) -> OpenAlgoDefaultCompatibilityAuthorityReceipt:
        return self._call("seal_openalgo_default_compatibility_authority", *args, **kwargs)

    def publish_prepared_candidate(self, *args: Any, **kwargs: Any) -> RegistryPublishResult:
        return self._call("publish_prepared_candidate", *args, **kwargs)

    def abandon_prepared_candidate(self, *args: Any, **kwargs: Any) -> RegistryRetirementReceipt:
        return self._call("abandon_prepared_candidate", *args, **kwargs)

    def remove_session_for_exact(self, *args: Any, **kwargs: Any) -> RegistryRemoveResult:
        return self._call("remove_session_for_exact", *args, **kwargs)

    def set_execution_default_projection(self, *args: Any, **kwargs: Any) -> None:
        self._call("set_execution_default_projection", *args, **kwargs)

    def claim_retired_candidate(self, receipt: RegistryRetirementReceipt) -> RetiredRegistryCandidate:
        result = self._call("claim_retired_candidate", receipt)
        self._retirements.discard(receipt)
        return result


def create_owned_registry(
    *, mutation_admission: MutationAdmission = require_broker_account_mutations
) -> tuple[BrokerRegistry, RegistryPublicationOwner]:
    """Create a matched pair; existing registries cannot acquire a new owner."""
    token = object()
    registry = BrokerRegistry(mutation_admission=mutation_admission, publication_owner_token=token)
    return registry, RegistryPublicationOwner(registry, token)
