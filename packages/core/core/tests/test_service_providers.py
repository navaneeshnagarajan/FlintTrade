from dataclasses import FrozenInstanceError

import pytest

from flinttrade_core.service_providers import (
    DuplicateProviderIdError,
    EvidenceUseScope,
    LicenceFact,
    ModelIdentity,
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


def _fact(basis: RightsBasis, *, subject_kind: str = "service", identifier: str = "fixture") -> LicenceFact:
    return LicenceFact(
        fact_id=f"{basis.value}:{identifier}",
        subject_kind=subject_kind,
        identifier=identifier,
        source_uri="https://evidence.example.invalid/v1",
        revision="revision-1",
        sha256="d" * 64,
        reviewed_at="2026-09-04T00:00:00Z",
        basis=basis,
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
        evidence=(
            _fact(
                RightsBasis.ENTITLEMENT,
                subject_kind="model_entitlement",
                identifier="fixture/model",
            ),
        ),
        model_identity=ModelIdentity(
            provider_id="forecast:fixture",
            model_id="fixture/model",
            revision="revision-1",
            sha256="a" * 64,
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
        evidence=(_fact(RightsBasis.ENTITLEMENT),),
    )
    unknown = RightsGrant(
        grant_id="grant:unknown",
        basis=RightsBasis.PROVIDER_TERMS,
        rights=UsageRights(),
        evidence=(_fact(RightsBasis.PROVIDER_TERMS),),
    )
    denied = RightsGrant(
        grant_id="grant:denied",
        basis=RightsBasis.LICENCE,
        rights=UsageRights(
            commercial_use=PermissionState.DENIED,
            production_use=PermissionState.DENIED,
        ),
        evidence=(_fact(RightsBasis.LICENCE),),
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


def test_model_identity_requires_a_namespaced_provider_id() -> None:
    with pytest.raises(ValueError, match="namespaced"):
        ModelIdentity(
            provider_id="unnamespaced",
            model_id="provider/model",
            revision="revision-1",
            sha256="a" * 64,
        )


@pytest.mark.parametrize("field", ("model_distribution", "derivative_distribution"))
def test_model_scoped_allowed_rights_require_matching_model_evidence(field: str) -> None:
    with pytest.raises(ValueError, match="model-scoped allowed rights require exact model evidence"):
        RightsGrant(
            grant_id=f"grant:{field}",
            basis=RightsBasis.LICENCE,
            rights=UsageRights(
                **{
                    field: PermissionState.ALLOWED,
                    "production_use": PermissionState.ALLOWED,
                    "max_evidence_use_scope": EvidenceUseScope.LIVE_DECISION,
                },
            ),
            evidence=(_fact(RightsBasis.LICENCE),),
        )


def test_model_scoped_allowed_rights_accept_exact_model_evidence() -> None:
    identity = ModelIdentity(
        provider_id="forecast:fixture",
        model_id="fixture/model",
        revision="revision-1",
        sha256="a" * 64,
    )

    grant = RightsGrant(
        grant_id="grant:exact-model",
        basis=RightsBasis.LICENCE,
        rights=UsageRights(
            model_distribution=PermissionState.ALLOWED,
            derivative_distribution=PermissionState.ALLOWED,
            production_use=PermissionState.ALLOWED,
            max_evidence_use_scope=EvidenceUseScope.LIVE_DECISION,
        ),
        evidence=(
            _fact(
                RightsBasis.LICENCE,
                subject_kind="model_licence",
                identifier="fixture/model",
            ),
        ),
        model_identity=identity,
    )

    assert grant.model_identity == identity


def test_descriptor_rejects_default_rights_for_another_provider() -> None:
    local_grant = RightsGrant(
        grant_id="grant:local-provider-model",
        basis=RightsBasis.LICENCE,
        rights=UsageRights(model_distribution=PermissionState.ALLOWED),
        evidence=(
            _fact(
                RightsBasis.LICENCE,
                subject_kind="model_licence",
                identifier="fixture/model",
            ),
        ),
        model_identity=ModelIdentity(
            provider_id="forecast:fixture",
            model_id="fixture/model",
            revision="revision-1",
            sha256="a" * 64,
        ),
    )
    foreign_grant = RightsGrant(
        grant_id="grant:other-provider-model",
        basis=RightsBasis.LICENCE,
        rights=UsageRights(output_use=PermissionState.ALLOWED),
        evidence=(
            _fact(
                RightsBasis.LICENCE,
                subject_kind="model_licence",
                identifier="other/model",
            ),
        ),
        model_identity=ModelIdentity(
            provider_id="forecast:other",
            model_id="other/model",
            revision="revision-1",
            sha256="a" * 64,
        ),
    )
    default_rights = RightsResolution(rights=UsageRights(), grants=(local_grant, foreign_grant))

    with pytest.raises(ValueError, match="default rights model identity must match provider_id"):
        ProviderDescriptor(
            provider_id="forecast:fixture",
            display_name="Fixture",
            service_kinds=frozenset({ServiceKind.FORECAST}),
            default_rights=default_rights,
        )


def test_rights_resolution_preserves_cross_model_scoped_grant_lineage() -> None:
    first = RightsGrant(
        grant_id="grant:first-model",
        basis=RightsBasis.LICENCE,
        rights=UsageRights(model_distribution=PermissionState.ALLOWED),
        evidence=(
            _fact(
                RightsBasis.LICENCE,
                subject_kind="model_licence",
                identifier="fixture/first-model",
            ),
        ),
        model_identity=ModelIdentity(
            provider_id="forecast:fixture",
            model_id="fixture/first-model",
            revision="revision-1",
            sha256="a" * 64,
        ),
    )
    second = RightsGrant(
        grant_id="grant:second-model",
        basis=RightsBasis.LICENCE,
        rights=UsageRights(derivative_distribution=PermissionState.ALLOWED),
        evidence=(
            _fact(
                RightsBasis.LICENCE,
                subject_kind="model_licence",
                identifier="fixture/second-model",
            ),
        ),
        model_identity=ModelIdentity(
            provider_id="forecast:fixture",
            model_id="fixture/second-model",
            revision="revision-2",
            sha256="b" * 64,
        ),
    )

    resolution = intersect_rights(first, second)

    assert resolution.rights.model_distribution is PermissionState.UNKNOWN
    assert resolution.rights.derivative_distribution is PermissionState.UNKNOWN
    assert resolution.grants == (first, second)


@pytest.mark.parametrize(
    ("field", "value"),
    (
        ("model_distribution", "allowed"),
        ("derivative_distribution", "allowed"),
        ("commercial_use", "allowed"),
        ("production_use", "allowed"),
        ("output_use", "allowed"),
        ("output_distribution", "allowed"),
        ("retention", "allowed"),
        ("training_distillation", "allowed"),
        ("max_evidence_use_scope", "live_decision"),
    ),
)
def test_usage_rights_rejects_raw_enum_values(field: str, value: str) -> None:
    with pytest.raises(ValueError, match="must be a declared enum"):
        UsageRights(**{field: value})  # type: ignore[arg-type]


@pytest.mark.parametrize(
    "basis",
    (RightsBasis.LICENCE, RightsBasis.PROVIDER_TERMS, RightsBasis.ENTITLEMENT),
)
def test_non_policy_rights_grants_require_evidence(basis: RightsBasis) -> None:
    with pytest.raises(ValueError, match="non-policy rights grants require evidence"):
        RightsGrant(grant_id=f"grant:{basis.value}", basis=basis, rights=UsageRights())


@pytest.mark.parametrize(
    "rights",
    (
        UsageRights(commercial_use=PermissionState.ALLOWED),
        UsageRights(max_evidence_use_scope=EvidenceUseScope.OFFLINE_QUALIFICATION),
    ),
)
def test_evidence_free_policy_grants_cannot_widen_rights(rights: UsageRights) -> None:
    with pytest.raises(ValueError, match="expansive rights grants require evidence"):
        RightsGrant(grant_id="policy:unproven", basis=RightsBasis.FLINTTRADE_POLICY, rights=rights)


def test_model_evidence_requires_matching_exact_model_identity() -> None:
    fact = _fact(RightsBasis.LICENCE, subject_kind="model_licence", identifier="provider/model")

    with pytest.raises(ValueError, match="model evidence requires an exact model identity"):
        RightsGrant(
            grant_id="grant:model-without-identity",
            basis=RightsBasis.LICENCE,
            rights=UsageRights(),
            evidence=(fact,),
        )
    with pytest.raises(ValueError, match="model evidence identifier must match model identity"):
        RightsGrant(
            grant_id="grant:model-mismatch",
            basis=RightsBasis.LICENCE,
            rights=UsageRights(),
            evidence=(fact,),
            model_identity=ModelIdentity(
                provider_id="forecast:fixture",
                model_id="provider/other-model",
                revision="revision-1",
                sha256="e" * 64,
            ),
        )

    grant = RightsGrant(
        grant_id="grant:model-exact",
        basis=RightsBasis.LICENCE,
        rights=UsageRights(),
        evidence=(fact,),
        model_identity=ModelIdentity(
            provider_id="forecast:fixture",
            model_id="provider/model",
            revision="revision-1",
            sha256="e" * 64,
        ),
    )
    assert grant.model_identity is not None


def test_model_identity_requires_matching_canonical_model_evidence() -> None:
    identity = ModelIdentity(
        provider_id="forecast:fixture",
        model_id="provider/model",
        revision="revision-1",
        sha256="e" * 64,
    )

    with pytest.raises(ValueError, match="model identity requires matching model evidence"):
        RightsGrant(
            grant_id="grant:generic-evidence",
            basis=RightsBasis.ENTITLEMENT,
            rights=UsageRights(),
            evidence=(_fact(RightsBasis.ENTITLEMENT),),
            model_identity=identity,
        )

    grant = RightsGrant(
        grant_id="grant:canonical-model-evidence",
        basis=RightsBasis.PROVIDER_TERMS,
        rights=UsageRights(),
        evidence=(
            _fact(
                RightsBasis.PROVIDER_TERMS,
                subject_kind=" Model-Licence ",
                identifier="provider/model",
            ),
        ),
        model_identity=identity,
    )
    assert grant.model_identity == identity


@pytest.mark.parametrize("subject_kind", ("service:model", "foo model"))
def test_model_evidence_labels_require_exact_model_identity(subject_kind: str) -> None:
    with pytest.raises(ValueError, match="model evidence requires an exact model identity"):
        RightsGrant(
            grant_id="grant:ordinary-model-label",
            basis=RightsBasis.LICENCE,
            rights=UsageRights(),
            evidence=(
                _fact(
                    RightsBasis.LICENCE,
                    subject_kind=subject_kind,
                    identifier="provider/model",
                ),
            ),
        )


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
        evidence=(_fact(RightsBasis.ENTITLEMENT),),
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
        model_identity=ModelIdentity(
            provider_id="forecast:fixture",
            model_id="provider/model",
            revision="revision-1",
            sha256="b" * 64,
        ),
    )
    evidence.clear()

    assert grant.evidence == (fact,)
    with pytest.raises(ValueError, match="conflicting rights grant"):
        intersect_rights(
            grant,
            RightsGrant(
                "grant:licence",
                RightsBasis.LICENCE,
                UsageRights(commercial_use=PermissionState.DENIED),
                evidence=(_fact(RightsBasis.LICENCE),),
            ),
        )
