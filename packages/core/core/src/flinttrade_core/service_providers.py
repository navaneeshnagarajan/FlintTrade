from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from enum import StrEnum
from types import MappingProxyType

_PROVIDER_ID = re.compile(r"^[a-z][a-z0-9-]*:[a-z0-9][a-z0-9._-]*$")


class ServiceKind(StrEnum):
    BROKER_EXECUTION = "broker_execution"
    MARKET_DATA_LIVE = "market_data_live"
    MARKET_DATA_HISTORICAL = "market_data_historical"
    NEWS = "news"
    FORECAST = "forecast"
    LLM = "llm"
    AGENT_RUNTIME = "agent_runtime"
    EMBEDDING = "embedding"


class EvidenceUseScope(StrEnum):
    ISOLATED_RESEARCH = "isolated_research"
    OFFLINE_QUALIFICATION = "offline_qualification"
    PRACTICE_QUALIFICATION = "practice_qualification"
    LIVE_DECISION = "live_decision"


class PermissionState(StrEnum):
    DENIED = "denied"
    UNKNOWN = "unknown"
    ALLOWED = "allowed"


class RightsBasis(StrEnum):
    LICENCE = "licence"
    PROVIDER_TERMS = "provider_terms"
    ENTITLEMENT = "entitlement"
    FLINTTRADE_POLICY = "flinttrade_policy"


_PERMISSION_RANK = {
    PermissionState.DENIED: 0,
    PermissionState.UNKNOWN: 1,
    PermissionState.ALLOWED: 2,
}
_SCOPE_RANK = {
    EvidenceUseScope.ISOLATED_RESEARCH: 0,
    EvidenceUseScope.OFFLINE_QUALIFICATION: 1,
    EvidenceUseScope.PRACTICE_QUALIFICATION: 2,
    EvidenceUseScope.LIVE_DECISION: 3,
}
_PERMISSION_NAMES = (
    "model_distribution",
    "derivative_distribution",
    "commercial_use",
    "production_use",
    "output_use",
    "output_distribution",
    "retention",
    "training_distillation",
)


@dataclass(frozen=True, slots=True)
class LicenceFact:
    fact_id: str
    subject_kind: str
    identifier: str
    source_uri: str
    revision: str
    sha256: str
    reviewed_at: str
    basis: RightsBasis

    def __post_init__(self) -> None:
        if any(
            not value.strip()
            for value in (
                self.fact_id,
                self.subject_kind,
                self.identifier,
                self.source_uri,
                self.revision,
                self.reviewed_at,
            )
        ):
            raise ValueError("licence fact fields must be non-blank")
        if not re.fullmatch(r"[0-9a-f]{64}", self.sha256):
            raise ValueError("licence fact sha256 must be 64 lower-case hex characters")

    def to_public_dict(self) -> dict[str, str]:
        return {
            "fact_id": self.fact_id,
            "subject_kind": self.subject_kind,
            "identifier": self.identifier,
            "source_uri": self.source_uri,
            "revision": self.revision,
            "sha256": self.sha256,
            "reviewed_at": self.reviewed_at,
            "basis": self.basis.value,
        }


@dataclass(frozen=True, slots=True)
class ModelIdentity:
    provider_id: str
    model_id: str
    revision: str
    sha256: str

    def __post_init__(self) -> None:
        if any(not value.strip() for value in (self.provider_id, self.model_id, self.revision)):
            raise ValueError("model identity fields must be non-blank")
        if not re.fullmatch(r"[0-9a-f]{64}", self.sha256):
            raise ValueError("model sha256 must be 64 lower-case hex characters")

    def to_public_dict(self) -> dict[str, str]:
        return {
            "provider_id": self.provider_id,
            "model_id": self.model_id,
            "revision": self.revision,
            "sha256": self.sha256,
        }


@dataclass(frozen=True, slots=True)
class UsageRights:
    model_distribution: PermissionState = PermissionState.UNKNOWN
    derivative_distribution: PermissionState = PermissionState.UNKNOWN
    commercial_use: PermissionState = PermissionState.UNKNOWN
    production_use: PermissionState = PermissionState.UNKNOWN
    output_use: PermissionState = PermissionState.UNKNOWN
    output_distribution: PermissionState = PermissionState.UNKNOWN
    retention: PermissionState = PermissionState.UNKNOWN
    training_distillation: PermissionState = PermissionState.UNKNOWN
    max_evidence_use_scope: EvidenceUseScope = EvidenceUseScope.ISOLATED_RESEARCH
    restrictions: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        values = tuple(str(value).strip() for value in self.restrictions)
        if any(not value for value in values) or len(values) != len(set(values)):
            raise ValueError("restrictions must contain unique non-blank values")
        object.__setattr__(self, "restrictions", tuple(sorted(values)))

    def to_public_dict(self) -> dict[str, object]:
        return {
            "model_distribution": self.model_distribution.value,
            "derivative_distribution": self.derivative_distribution.value,
            "commercial_use": self.commercial_use.value,
            "production_use": self.production_use.value,
            "output_use": self.output_use.value,
            "output_distribution": self.output_distribution.value,
            "retention": self.retention.value,
            "training_distillation": self.training_distillation.value,
            "max_evidence_use_scope": self.max_evidence_use_scope.value,
            "restrictions": list(self.restrictions),
        }

    @property
    def digest(self) -> str:
        return _digest(self.to_public_dict())


@dataclass(frozen=True, slots=True)
class RightsGrant:
    grant_id: str
    basis: RightsBasis
    rights: UsageRights
    evidence: tuple[LicenceFact, ...] = ()
    model_identity: ModelIdentity | None = None

    def __post_init__(self) -> None:
        if not self.grant_id.strip():
            raise ValueError("grant_id must be non-blank")
        evidence = tuple(sorted(self.evidence, key=lambda fact: fact.fact_id))
        if len({fact.fact_id for fact in evidence}) != len(evidence):
            raise ValueError("evidence fact IDs must be unique")
        if any(fact.basis is not self.basis for fact in evidence):
            raise ValueError("every evidence fact must match the grant basis")
        if self.basis is not RightsBasis.FLINTTRADE_POLICY and not evidence:
            raise ValueError("non-policy rights grants require evidence")
        is_expansive = any(
            getattr(self.rights, name) is PermissionState.ALLOWED for name in _PERMISSION_NAMES
        ) or self.rights.max_evidence_use_scope is not EvidenceUseScope.ISOLATED_RESEARCH
        if is_expansive and not evidence:
            raise ValueError("expansive rights grants require evidence")
        model_evidence = tuple(
            fact
            for fact in evidence
            if re.sub(r"[^a-z0-9]+", "", fact.subject_kind.casefold()).startswith("model")
        )
        if model_evidence and self.model_identity is None:
            raise ValueError("model evidence requires an exact model identity")
        if self.model_identity is not None and any(
            fact.identifier != self.model_identity.model_id for fact in model_evidence
        ):
            raise ValueError("model evidence identifier must match model identity")
        if self.model_identity is not None and (self.basis is not RightsBasis.FLINTTRADE_POLICY or is_expansive) and not any(
            fact.identifier == self.model_identity.model_id for fact in model_evidence
        ):
            raise ValueError("model identity requires matching model evidence")
        object.__setattr__(self, "evidence", evidence)

    def to_public_dict(self) -> dict[str, object]:
        return {
            "grant_id": self.grant_id,
            "basis": self.basis.value,
            "rights": self.rights.to_public_dict(),
            "evidence": [fact.to_public_dict() for fact in self.evidence],
            "model_identity": None if self.model_identity is None else self.model_identity.to_public_dict(),
        }


@dataclass(frozen=True, slots=True)
class RightsResolution:
    rights: UsageRights = UsageRights()
    grants: tuple[RightsGrant, ...] = ()

    def __post_init__(self) -> None:
        grants = _canonical_grants(tuple(self.grants))
        if self.rights != _intersect_grant_rights(grants):
            raise ValueError("rights must equal the effective grants")
        object.__setattr__(self, "grants", grants)

    def to_public_dict(self) -> dict[str, object]:
        return {
            "rights": self.rights.to_public_dict(),
            "grants": [grant.to_public_dict() for grant in self.grants],
        }

    @property
    def digest(self) -> str:
        return _digest(self.to_public_dict())


def _digest(payload: object) -> str:
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _canonical_grants(grants: tuple[RightsGrant, ...]) -> tuple[RightsGrant, ...]:
    by_id: dict[str, RightsGrant] = {}
    for grant in grants:
        existing = by_id.get(grant.grant_id)
        if existing is not None and existing != grant:
            raise ValueError(f"conflicting rights grant: {grant.grant_id}")
        by_id[grant.grant_id] = grant
    return tuple(by_id[grant_id] for grant_id in sorted(by_id))


def _intersect_grant_rights(grants: tuple[RightsGrant, ...]) -> UsageRights:
    if not grants:
        return UsageRights()
    permissions = {
        name: min((getattr(grant.rights, name) for grant in grants), key=_PERMISSION_RANK.__getitem__)
        for name in _PERMISSION_NAMES
    }
    return UsageRights(
        **permissions,
        max_evidence_use_scope=min(
            (grant.rights.max_evidence_use_scope for grant in grants),
            key=_SCOPE_RANK.__getitem__,
        ),
        restrictions=tuple(sorted({item for grant in grants for item in grant.rights.restrictions})),
    )


def intersect_rights(*items: RightsGrant | RightsResolution) -> RightsResolution:
    grants = tuple(
        grant
        for item in items
        for grant in (item.grants if isinstance(item, RightsResolution) else (item,))
    )
    grants = _canonical_grants(grants)
    return RightsResolution(rights=_intersect_grant_rights(grants), grants=grants)


@dataclass(frozen=True, slots=True)
class ProviderDescriptor:
    provider_id: str
    display_name: str
    service_kinds: frozenset[ServiceKind]
    capabilities: tuple[str, ...] = ()
    regions: tuple[str, ...] = ()
    exchanges: tuple[str, ...] = ()
    auth_models: tuple[str, ...] = ()
    pricing_class: str = "unknown"
    connection_requirements: tuple[str, ...] = ()
    software_licence: str = "unknown"
    model_licence: str = "not_applicable"
    data_licence: str = "unknown"
    retention_policy: str = "unknown"
    resource_requirements: tuple[str, ...] = ()
    provenance: tuple[str, ...] = ()
    activation_blockers: tuple[str, ...] = ()
    implemented: bool = False
    licence_facts: tuple[LicenceFact, ...] = ()
    default_rights: RightsResolution = RightsResolution()

    def __post_init__(self) -> None:
        if not _PROVIDER_ID.fullmatch(self.provider_id):
            raise ValueError("provider_id must be a namespaced lower-case identifier")
        if not self.display_name.strip():
            raise ValueError("display_name must be non-blank")
        service_kinds = frozenset(self.service_kinds)
        if not service_kinds:
            raise ValueError("service_kinds must be non-empty")
        object.__setattr__(self, "service_kinds", service_kinds)
        for name in (
            "capabilities",
            "regions",
            "exchanges",
            "auth_models",
            "connection_requirements",
            "resource_requirements",
            "provenance",
            "activation_blockers",
        ):
            values = tuple(str(value).strip() for value in getattr(self, name))
            if any(not value for value in values) or len(values) != len(set(values)):
                raise ValueError(f"{name} must contain unique non-blank values")
            object.__setattr__(self, name, tuple(sorted(values)))
        licence_facts = tuple(sorted(self.licence_facts, key=lambda fact: fact.fact_id))
        if len({fact.fact_id for fact in licence_facts}) != len(licence_facts):
            raise ValueError("licence fact IDs must be unique")
        object.__setattr__(self, "licence_facts", licence_facts)

    def to_public_dict(self) -> dict[str, object]:
        return {
            "provider_id": self.provider_id,
            "display_name": self.display_name,
            "service_kinds": sorted(kind.value for kind in self.service_kinds),
            "capabilities": list(self.capabilities),
            "regions": list(self.regions),
            "exchanges": list(self.exchanges),
            "auth_models": list(self.auth_models),
            "pricing_class": self.pricing_class,
            "connection_requirements": list(self.connection_requirements),
            "software_licence": self.software_licence,
            "model_licence": self.model_licence,
            "data_licence": self.data_licence,
            "retention_policy": self.retention_policy,
            "resource_requirements": list(self.resource_requirements),
            "provenance": list(self.provenance),
            "activation_blockers": list(self.activation_blockers),
            "implemented": self.implemented,
            "licence_facts": [fact.to_public_dict() for fact in self.licence_facts],
            "default_rights": self.default_rights.to_public_dict(),
        }


class DuplicateProviderIdError(ValueError):
    """Two domain contributors claimed the same provider ID."""


@dataclass(frozen=True, slots=True, init=False, eq=False)
class ServiceProviderCatalogue:
    _ordered: tuple[ProviderDescriptor, ...]
    _by_id: Mapping[str, ProviderDescriptor]

    def __init__(self, providers: Iterable[ProviderDescriptor]) -> None:
        ordered = tuple(providers)
        by_id: dict[str, ProviderDescriptor] = {}
        for provider in ordered:
            if provider.provider_id in by_id:
                raise DuplicateProviderIdError(provider.provider_id)
            by_id[provider.provider_id] = provider
        object.__setattr__(self, "_ordered", ordered)
        object.__setattr__(self, "_by_id", MappingProxyType(by_id))

    def get(self, provider_id: str) -> ProviderDescriptor:
        return self._by_id[provider_id]

    def list(self) -> tuple[ProviderDescriptor, ...]:
        return self._ordered

    def by_kind(self, service_kind: ServiceKind) -> tuple[ProviderDescriptor, ...]:
        return tuple(provider for provider in self._ordered if service_kind in provider.service_kinds)

    def to_public_payload(self) -> dict[str, object]:
        providers = [provider.to_public_dict() for provider in self._ordered]
        digest_payload = sorted(providers, key=lambda item: str(item["provider_id"]))
        return {
            "catalogue_digest": _digest(digest_payload),
            "count": len(providers),
            "providers": providers,
        }
