from dataclasses import FrozenInstanceError

import pytest

from flinttrade_core.service_providers import (
    DuplicateProviderIdError,
    EvidenceUseScope,
    LicenceFact,
    PermissionState,
    ProviderDescriptor,
    RightsBasis,
    RightsGrant,
    RightsResolution,
    ServiceKind,
    ServiceProviderCatalogue,
    UsageRights,
    intersect_rights,
)


def _provider(provider_id: str) -> ProviderDescriptor:
    return ProviderDescriptor(
        provider_id=provider_id,
        display_name="Fixture",
        service_kinds=frozenset({ServiceKind.FORECAST}),
        capabilities=("forecast.run",),
    )


def test_provider_ids_are_namespaced_and_descriptors_are_frozen() -> None:
    with pytest.raises(ValueError, match="namespaced"):
        _provider("unnamespaced")
    descriptor = _provider("forecast:fixture")
    with pytest.raises(FrozenInstanceError):
        descriptor.display_name = "Changed"  # type: ignore[misc]


def test_catalogue_rejects_duplicate_ids() -> None:
    with pytest.raises(DuplicateProviderIdError, match="forecast:fixture"):
        ServiceProviderCatalogue((_provider("forecast:fixture"), _provider("forecast:fixture")))


def test_rights_intersection_never_widens_scope_or_permissions() -> None:
    live = RightsGrant(
        grant_id="grant:live",
        basis=RightsBasis.ENTITLEMENT,
        rights=UsageRights(
            model_distribution=PermissionState.ALLOWED,
            output_use=PermissionState.ALLOWED,
            max_evidence_use_scope=EvidenceUseScope.LIVE_DECISION,
            restrictions=("retain-provenance",),
        ),
    )
    research_only = RightsGrant(
        grant_id="grant:research",
        basis=RightsBasis.FLINTTRADE_POLICY,
        rights=UsageRights(
            model_distribution=PermissionState.DENIED,
            output_use=PermissionState.UNKNOWN,
            max_evidence_use_scope=EvidenceUseScope.ISOLATED_RESEARCH,
            restrictions=("no-production",),
        ),
    )

    effective = intersect_rights(live, research_only)

    assert effective.rights.model_distribution is PermissionState.DENIED
    assert effective.rights.output_use is PermissionState.UNKNOWN
    assert effective.rights.max_evidence_use_scope is EvidenceUseScope.ISOLATED_RESEARCH
    assert effective.rights.restrictions == ("no-production", "retain-provenance")
    assert tuple(grant.grant_id for grant in effective.grants) == ("grant:live", "grant:research")
    assert len(effective.digest) == 64


def test_rights_intersection_is_a_fail_closed_semilattice() -> None:
    allowed = RightsGrant(
        grant_id="grant:allowed",
        basis=RightsBasis.ENTITLEMENT,
        rights=UsageRights(
            commercial_use=PermissionState.ALLOWED,
            production_use=PermissionState.ALLOWED,
            max_evidence_use_scope=EvidenceUseScope.LIVE_DECISION,
        ),
    )
    unknown = RightsGrant(
        grant_id="grant:unknown",
        basis=RightsBasis.PROVIDER_TERMS,
        rights=UsageRights(),
    )
    denied = RightsGrant(
        grant_id="grant:denied",
        basis=RightsBasis.LICENCE,
        rights=UsageRights(
            commercial_use=PermissionState.DENIED,
            production_use=PermissionState.DENIED,
        ),
    )

    assert intersect_rights().rights == UsageRights()
    assert intersect_rights(allowed, unknown) == intersect_rights(unknown, allowed)
    assert intersect_rights(allowed, allowed) == intersect_rights(allowed)
    assert intersect_rights(intersect_rights(allowed, unknown), denied) == intersect_rights(
        allowed, intersect_rights(unknown, denied)
    )


def test_licence_facts_bind_subject_identity_and_basis() -> None:
    fact = LicenceFact(
        fact_id="licence:fixture",
        subject_kind="model",
        identifier="provider/model",
        source_uri="https://licence.example.invalid/v1",
        revision="revision-1",
        sha256="a" * 64,
        reviewed_at="2026-09-03T00:00:00Z",
        basis=RightsBasis.LICENCE,
    )
    assert fact.to_public_dict()["identifier"] == "provider/model"


def test_public_payload_is_deterministic_and_contains_no_mutable_mapping() -> None:
    catalogue = ServiceProviderCatalogue((_provider("forecast:fixture"),))
    first = catalogue.to_public_payload()
    second = catalogue.to_public_payload()
    first["providers"][0]["display_name"] = "Mutated"  # type: ignore[index]

    assert catalogue.to_public_payload() == second
    assert second["providers"][0]["provider_id"] == "forecast:fixture"  # type: ignore[index]
    assert second["catalogue_digest"] == catalogue.to_public_payload()["catalogue_digest"]


def test_descriptor_deep_freezes_inputs_and_projects_connection_requirements() -> None:
    capabilities = ["forecast.protocol"]
    service_kinds = {ServiceKind.FORECAST}
    descriptor = ProviderDescriptor(
        provider_id="forecast:external-json",
        display_name="External JSON forecast protocol",
        service_kinds=service_kinds,
        capabilities=capabilities,
        connection_requirements=["authenticated_endpoint"],
        implemented=False,
    )
    capabilities.append("forecast.run")
    service_kinds.clear()
    assert descriptor.capabilities == ("forecast.protocol",)
    assert descriptor.service_kinds == frozenset({ServiceKind.FORECAST})
    assert descriptor.connection_requirements == ("authenticated_endpoint",)


def test_rights_resolution_does_not_retain_a_mutable_grant_list() -> None:
    grant = RightsGrant(
        grant_id="grant:unknown",
        basis=RightsBasis.FLINTTRADE_POLICY,
        rights=UsageRights(),
    )
    mutable_grants = [grant]
    resolution = RightsResolution(rights=UsageRights(), grants=mutable_grants)
    mutable_grants.clear()
    assert resolution.grants == (grant,)


def test_rights_resolution_rejects_manual_rights_that_do_not_match_its_grants() -> None:
    allowed = RightsGrant(
        grant_id="grant:allowed",
        basis=RightsBasis.ENTITLEMENT,
        rights=UsageRights(production_use=PermissionState.ALLOWED),
    )

    with pytest.raises(ValueError, match="rights must equal the effective grants"):
        RightsResolution(rights=UsageRights(production_use=PermissionState.DENIED))
    with pytest.raises(ValueError, match="rights must equal the effective grants"):
        RightsResolution(rights=UsageRights(), grants=(allowed,))

    resolution = RightsResolution(rights=allowed.rights, grants=(allowed,))
    assert intersect_rights(resolution).rights.production_use is PermissionState.ALLOWED


def test_catalogue_internal_storage_cannot_be_mutated_or_reassigned() -> None:
    catalogue = ServiceProviderCatalogue((_provider("forecast:fixture"),))

    with pytest.raises(FrozenInstanceError):
        catalogue._ordered = ()  # type: ignore[misc]
    with pytest.raises(AttributeError):
        catalogue._by_id.clear()  # type: ignore[attr-defined]
    with pytest.raises(TypeError):
        catalogue._by_id["forecast:other"] = _provider("forecast:other")  # type: ignore[index]

    assert catalogue.list() == (_provider("forecast:fixture"),)


def test_grant_copies_mutable_evidence_and_rejects_conflicting_duplicate_ids() -> None:
    fact = LicenceFact(
        fact_id="licence:fixture",
        subject_kind="model",
        identifier="provider/model",
        source_uri="https://licence.example.invalid/v1",
        revision="revision-1",
        sha256="b" * 64,
        reviewed_at="2026-09-03T00:00:00Z",
        basis=RightsBasis.LICENCE,
    )
    evidence = [fact]
    grant = RightsGrant(
        grant_id="grant:licence",
        basis=RightsBasis.LICENCE,
        rights=UsageRights(),
        evidence=evidence,
    )
    evidence.clear()

    assert grant.evidence == (fact,)
    with pytest.raises(ValueError, match="conflicting rights grant"):
        intersect_rights(
            grant,
            RightsGrant("grant:licence", RightsBasis.LICENCE, UsageRights(commercial_use=PermissionState.DENIED)),
        )
