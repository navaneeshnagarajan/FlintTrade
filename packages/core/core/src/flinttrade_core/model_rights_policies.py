"""Inert model-rights records; this module introduces no model runtime."""

from flinttrade_core.service_providers import (
    EvidenceUseScope,
    LicenceFact,
    ModelIdentity,
    PermissionState,
    RightsBasis,
    RightsGrant,
    RightsResolution,
    UsageRights,
    intersect_rights,
)

_TIMESFM_3_MODEL_IDENTITY = ModelIdentity(
    provider_id="forecast:google-timesfm",
    model_id="google/timesfm-3.0-pytorch",
    revision="43046b85ec22d584a13f8098c2ed39c889e129c2",
    sha256="a7592b0a8432baee54483254e5647856911ce69e09d09a9bb65904b2d98f17da",
)

TIMESFM_3_RESTRICTION_POLICY: RightsResolution = intersect_rights(
    RightsGrant(
        grant_id="licence:google-timesfm-3",
        basis=RightsBasis.LICENCE,
        rights=UsageRights(
            model_distribution=PermissionState.DENIED,
            derivative_distribution=PermissionState.DENIED,
            commercial_use=PermissionState.DENIED,
            production_use=PermissionState.DENIED,
        ),
        evidence=(
            LicenceFact(
                fact_id="licence:google-timesfm-3",
                subject_kind="model_licence",
                identifier="google/timesfm-3.0-pytorch",
                source_uri="https://huggingface.co/google/timesfm-3.0-pytorch",
                revision="43046b85ec22d584a13f8098c2ed39c889e129c2",
                sha256="3e36db7240d23adb6ac6d7d931892dcc5706a14a7d31581f08c35d2f25736dfd",
                reviewed_at="2026-09-03T00:00:00Z",
                basis=RightsBasis.LICENCE,
            ),
        ),
        model_identity=_TIMESFM_3_MODEL_IDENTITY,
    ),
    RightsGrant(
        grant_id="policy:timesfm-3-isolated-research",
        basis=RightsBasis.FLINTTRADE_POLICY,
        rights=UsageRights(max_evidence_use_scope=EvidenceUseScope.ISOLATED_RESEARCH),
    ),
)
