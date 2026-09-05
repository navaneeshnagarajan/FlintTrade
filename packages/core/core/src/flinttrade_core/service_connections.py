"""Pure immutable contracts for inert LLM service connections.

Operator endpoints are base URLs substituted for ``{host}`` in the canonical
provider profile. This module validates configuration only: it never resolves,
probes, authenticates to, or starts a provider.
"""

from __future__ import annotations

import unicodedata
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field, replace
from datetime import UTC, datetime
from typing import Any
from urllib.parse import urlsplit
from uuid import RFC_4122, UUID, uuid4

from .llm_provider_profiles import LLM_SERVICE_PROVIDER_BY_ID, LLMProviderProfile

SERVICE_CONNECTION_SCHEMA_VERSION = 1
MAX_OPERATOR_ENDPOINT_LENGTH = 2048
MAX_CONNECTION_LABEL_LENGTH = 128
MAX_CONNECTION_MODEL_LENGTH = 256
INT64_MAX = (1 << 63) - 1

_CREATE_FIELDS = frozenset({"provider_id", "label", "model", "endpoint", "auth_mode"})
_UPDATE_FIELDS = frozenset({"label", "model", "endpoint", "auth_mode"})
_SERVER_OWNED_FIELDS = frozenset(
    {
        "schema_version",
        "connection_id",
        "created_at",
        "updated_at",
        "_secret_version",
        "secret_version",
    }
)


def _utc_now() -> datetime:
    return datetime.now(UTC)


def _validate_uuid4(value: object, *, field_name: str) -> UUID:
    if type(value) is not UUID or value.version != 4 or value.variant != RFC_4122:
        raise ValueError(f"{field_name} must be an exact RFC 4122 UUID4")
    return value


def _profile(provider_id: object) -> LLMProviderProfile:
    if type(provider_id) is not str or provider_id not in LLM_SERVICE_PROVIDER_BY_ID:
        raise ValueError("provider_id must be an exact canonical LLM provider ID")
    return LLM_SERVICE_PROVIDER_BY_ID[provider_id]


def _validate_utc(value: object, *, field_name: str) -> datetime:
    if type(value) is not datetime or value.tzinfo is None or value.utcoffset() != UTC.utcoffset(value):
        raise ValueError(f"{field_name} must be a timezone-aware UTC datetime")
    return value.replace(tzinfo=UTC)


def _public_timestamp(value: datetime) -> str:
    return value.isoformat().replace("+00:00", "Z")


def _validate_text(value: object, *, field_name: str, maximum: int, blank: bool) -> str:
    if type(value) is not str:
        raise ValueError(f"{field_name} must be a string")
    if not blank and not value.strip():
        raise ValueError(f"{field_name} must be non-blank")
    if len(value) > maximum:
        raise ValueError(f"{field_name} must contain at most {maximum} characters")
    if any(unicodedata.category(character) == "Cc" for character in value):
        raise ValueError(f"{field_name} must not contain control characters")
    return value


def _validate_operator_endpoint(value: object) -> str:
    if type(value) is not str or not value or len(value) > MAX_OPERATOR_ENDPOINT_LENGTH:
        raise ValueError("operator endpoint must be a non-empty absolute HTTP(S) URL of at most 2048 characters")
    if any(unicodedata.category(character) == "Cc" for character in value):
        raise ValueError("operator endpoint must not contain control characters")
    if any(character.isspace() for character in value):
        raise ValueError("operator endpoint must not contain whitespace")
    try:
        parsed = urlsplit(value)
        _ = parsed.port
    except ValueError:
        raise ValueError("operator endpoint must be a valid absolute HTTP(S) URL") from None
    if parsed.scheme.lower() not in {"http", "https"} or parsed.hostname is None:
        raise ValueError("operator endpoint must be an absolute HTTP(S) URL")
    if (
        parsed.netloc.endswith(":")
        or parsed.username is not None
        or parsed.password is not None
        or parsed.query
        or parsed.fragment
        or "?" in value
        or "#" in value
    ):
        raise ValueError("operator endpoint must not contain userinfo, a query, or a fragment")
    return value


def _validate_stored_endpoint(profile: LLMProviderProfile, value: object) -> str | None:
    if profile.managed_runtime:
        if value is not None:
            raise ValueError("managed LLM connection must not store an operator endpoint")
        return None
    if profile.requires_host:
        return _validate_operator_endpoint(value)
    if value != profile.endpoint_template:
        raise ValueError("fixed cloud endpoint must match the canonical provider profile")
    return profile.endpoint_template


def _validate_stored_auth_mode(profile: LLMProviderProfile, value: object) -> str | None:
    if not profile.auth_modes:
        if value is not None:
            raise ValueError("unauthenticated LLM connection must not store an auth mode")
        return None
    if type(value) is not str or value not in profile.auth_modes:
        raise ValueError("auth_mode must be an exact mode allowed by the canonical provider profile")
    return value


def _validate_endpoint(
    profile: LLMProviderProfile,
    value: object,
    *,
    supplied: bool,
) -> str | None:
    if profile.managed_runtime:
        if supplied:
            raise ValueError("managed LLM profiles reject an endpoint override")
        return None
    if profile.requires_host:
        if not supplied:
            raise ValueError("operator endpoint is required")
        return _validate_operator_endpoint(value)
    if supplied:
        raise ValueError("fixed cloud LLM profiles reject an endpoint override")
    return profile.endpoint_template


def _validate_auth_mode(
    profile: LLMProviderProfile,
    value: object,
    *,
    supplied: bool,
) -> str | None:
    if not profile.auth_modes:
        if supplied and value is not None:
            raise ValueError("auth_mode must be omitted or null for this unauthenticated profile")
        return None
    if not supplied or type(value) is not str or value not in profile.auth_modes:
        raise ValueError("auth_mode must be an exact mode allowed by the canonical provider profile")
    return value


def _payload_dict(payload: object) -> dict[object, object]:
    if not isinstance(payload, Mapping):
        raise ValueError("service connection payload must be an object")
    return dict(payload)


def _validate_create_fields(payload: Mapping[object, object]) -> None:
    if any(field in payload for field in _SERVER_OWNED_FIELDS):
        raise ValueError("service connection payload contains server-owned fields")
    if any(type(field) is not str or field not in _CREATE_FIELDS for field in payload):
        raise ValueError("service connection payload contains unknown fields")


def _validate_update_fields(payload: Mapping[object, object]) -> None:
    if "provider_id" in payload:
        raise ValueError("service connection provider_id is immutable")
    if any(field in payload for field in _SERVER_OWNED_FIELDS):
        raise ValueError("service connection update contains server-owned fields")
    if any(type(field) is not str or field not in _UPDATE_FIELDS for field in payload):
        raise ValueError("service connection update contains unknown fields")


@dataclass(frozen=True, slots=True)
class ServiceConnectionRef:
    """Canonical two-part identity for one operator-owned connection."""

    provider_id: str
    connection_id: UUID

    def __post_init__(self) -> None:
        _profile(self.provider_id)
        _validate_uuid4(self.connection_id, field_name="connection_id")

    def to_dict(self) -> dict[str, str]:
        """Return a detached serialisable representation of the full identity."""
        return {"provider_id": self.provider_id, "connection_id": str(self.connection_id)}


@dataclass(frozen=True, slots=True, repr=False)
class ServiceSecretVersion:
    """Opaque immutable identity for one materialised secret binding version."""

    connection_ref: ServiceConnectionRef
    store_incarnation: UUID
    binding_id: UUID
    generation: int
    present: bool

    def __post_init__(self) -> None:
        if type(self.connection_ref) is not ServiceConnectionRef:
            raise ValueError("connection_ref must be an exact ServiceConnectionRef")
        _validate_uuid4(self.store_incarnation, field_name="store_incarnation")
        _validate_uuid4(self.binding_id, field_name="binding_id")
        if type(self.generation) is not int or not 1 <= self.generation <= INT64_MAX:
            raise ValueError("generation must be an exact integer in 1..INT64_MAX")
        if type(self.present) is not bool:
            raise ValueError("present must be an exact boolean")

    def __repr__(self) -> str:
        return "ServiceSecretVersion(<redacted>)"


@dataclass(frozen=True, slots=True)
class ServiceConnection:
    """One deeply immutable, non-invoking LLM connection configuration."""

    schema_version: int
    provider_id: str
    connection_id: UUID
    label: str
    model: str
    endpoint: str | None
    auth_mode: str | None
    created_at: datetime
    updated_at: datetime
    _secret_version: ServiceSecretVersion | None = field(default=None, repr=False)

    def __post_init__(self) -> None:
        if type(self.schema_version) is not int or self.schema_version != SERVICE_CONNECTION_SCHEMA_VERSION:
            raise ValueError("schema_version must be the exact supported integer")
        profile = _profile(self.provider_id)
        _validate_uuid4(self.connection_id, field_name="connection_id")
        _validate_text(
            self.label,
            field_name="label",
            maximum=MAX_CONNECTION_LABEL_LENGTH,
            blank=False,
        )
        _validate_text(
            self.model,
            field_name="model",
            maximum=MAX_CONNECTION_MODEL_LENGTH,
            blank=True,
        )
        expected_endpoint = _validate_stored_endpoint(profile, self.endpoint)
        if self.endpoint != expected_endpoint:
            raise ValueError("endpoint must match the canonical provider policy")
        expected_auth_mode = _validate_stored_auth_mode(profile, self.auth_mode)
        if self.auth_mode != expected_auth_mode:
            raise ValueError("auth_mode must match the canonical provider policy")
        created_at = _validate_utc(self.created_at, field_name="created_at")
        updated_at = _validate_utc(self.updated_at, field_name="updated_at")
        if updated_at < created_at:
            raise ValueError("updated_at must not precede created_at")
        object.__setattr__(self, "created_at", created_at)
        object.__setattr__(self, "updated_at", updated_at)
        if self._secret_version is not None:
            self._validate_secret_version(self._secret_version)

    @property
    def ref(self) -> ServiceConnectionRef:
        """Return this connection's complete immutable identity."""
        return ServiceConnectionRef(self.provider_id, self.connection_id)

    @property
    def secret_version(self) -> ServiceSecretVersion | None:
        """Return opaque binding metadata for the trusted internal store only."""
        return self._secret_version

    @property
    def credential_configured(self) -> bool:
        """Report only whether the current opaque binding is materially present."""
        return self._secret_version is not None and self._secret_version.present

    def _validate_secret_version(self, secret_version: object) -> ServiceSecretVersion:
        if type(secret_version) is not ServiceSecretVersion:
            raise ValueError("secret version must be an exact ServiceSecretVersion")
        if secret_version.connection_ref != self.ref:
            raise ValueError("secret version must match the exact connection identity")
        if self.auth_mode is None:
            raise ValueError("this provider does not accept credentials")
        return secret_version

    def with_secret_version(self, secret_version: ServiceSecretVersion | None) -> ServiceConnection:
        """Return an immutable replacement for use only by the trusted secret store."""
        if secret_version is not None:
            self._validate_secret_version(secret_version)
        return replace(self, _secret_version=secret_version)

    def to_public_dict(self) -> dict[str, Any]:
        """Return a detached DTO containing no opaque secret-binding metadata."""
        return {
            "schema_version": self.schema_version,
            **self.ref.to_dict(),
            "label": self.label,
            "model": self.model,
            "endpoint": self.endpoint,
            "auth_mode": self.auth_mode,
            "credential_configured": self.credential_configured,
            "created_at": _public_timestamp(self.created_at),
            "updated_at": _public_timestamp(self.updated_at),
        }


def create_service_connection(
    payload: Mapping[str, object],
    *,
    uuid_factory: Callable[[], UUID] = uuid4,
    clock_factory: Callable[[], datetime] = _utc_now,
) -> ServiceConnection:
    """Validate an operator payload and mint one inert server-owned connection."""
    values = _payload_dict(payload)
    _validate_create_fields(values)
    profile = _profile(values.get("provider_id"))
    label = _validate_text(
        values.get("label"),
        field_name="label",
        maximum=MAX_CONNECTION_LABEL_LENGTH,
        blank=False,
    )
    model = _validate_text(
        values.get("model", profile.default_model),
        field_name="model",
        maximum=MAX_CONNECTION_MODEL_LENGTH,
        blank=True,
    )
    endpoint = _validate_endpoint(profile, values.get("endpoint"), supplied="endpoint" in values)
    auth_mode = _validate_auth_mode(profile, values.get("auth_mode"), supplied="auth_mode" in values)
    connection_id = _validate_uuid4(uuid_factory(), field_name="connection_id")
    now = _validate_utc(clock_factory(), field_name="clock factory result")
    return ServiceConnection(
        schema_version=SERVICE_CONNECTION_SCHEMA_VERSION,
        provider_id=str(values["provider_id"]),
        connection_id=connection_id,
        label=label,
        model=model,
        endpoint=endpoint,
        auth_mode=auth_mode,
        created_at=now,
        updated_at=now,
    )


def update_service_connection(
    current: ServiceConnection,
    payload: Mapping[str, object],
    *,
    clock_factory: Callable[[], datetime] = _utc_now,
) -> ServiceConnection:
    """Apply an immutable metadata patch and invalidate unsafe binding reuse."""
    if type(current) is not ServiceConnection:
        raise ValueError("current must be an exact ServiceConnection")
    values = _payload_dict(payload)
    _validate_update_fields(values)
    profile = _profile(current.provider_id)
    label = _validate_text(
        values.get("label", current.label),
        field_name="label",
        maximum=MAX_CONNECTION_LABEL_LENGTH,
        blank=False,
    )
    model = _validate_text(
        values.get("model", current.model),
        field_name="model",
        maximum=MAX_CONNECTION_MODEL_LENGTH,
        blank=True,
    )
    if "endpoint" in values:
        endpoint = _validate_endpoint(profile, values["endpoint"], supplied=True)
    else:
        endpoint = current.endpoint
    if "auth_mode" in values:
        auth_mode = _validate_auth_mode(profile, values["auth_mode"], supplied=True)
    else:
        auth_mode = current.auth_mode
    binding = current.secret_version if endpoint == current.endpoint and auth_mode == current.auth_mode else None
    updated_at = _validate_utc(clock_factory(), field_name="clock factory result")
    return replace(
        current,
        label=label,
        model=model,
        endpoint=endpoint,
        auth_mode=auth_mode,
        updated_at=updated_at,
        _secret_version=binding,
    )
