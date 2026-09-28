"""Static AI service-provider contributions with no runtime provider I/O."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from types import MappingProxyType

from flinttrade_core.llm_provider_profiles import (
    LLM_PROVIDER_PROFILES,
    LLMProviderProfile,
    _connection_requirements,
)
from flinttrade_core.news_provider_profiles import NEWS_PROVIDER_PROFILES, SENTIMENT_NEWS_CHANNELS
from flinttrade_core.service_providers import (
    EvidenceUseScope,
    LicenceFact,
    ProviderDescriptor,
    RightsBasis,
    RightsGrant,
    RightsResolution,
    ServiceKind,
    UsageRights,
)

from .agent_backends.profiles import AGENT_BACKEND_CATALOGUE, AgentBackendProfile

RSS_SOURCES: Mapping[str, str] = MappingProxyType(dict(SENTIMENT_NEWS_CHANNELS))
DEFAULT_FEEDS: tuple[str, ...] = tuple(RSS_SOURCES.values())


@dataclass(frozen=True, slots=True)
class EmbeddingServiceProfile:
    """A built-in embedding selection and its legacy runtime constructor name."""

    provider_id: str
    runtime_name: str
    display_name: str
    pricing_class: str


EMBEDDING_PROVIDER_PROFILES: tuple[EmbeddingServiceProfile, ...] = (
    EmbeddingServiceProfile(
        provider_id="embedding:sentence-transformers",
        runtime_name="sentence_transformers",
        display_name="Sentence Transformers",
        pricing_class="local_compute",
    ),
    EmbeddingServiceProfile(
        provider_id="embedding:openai-compatible",
        runtime_name="openai",
        display_name="OpenAI-compatible embeddings",
        pricing_class="provider_tariff",
    ),
)


def _unknown_rights() -> RightsResolution:
    return RightsResolution(rights=UsageRights())


def _llm_descriptor(profile: LLMProviderProfile) -> ProviderDescriptor:
    return ProviderDescriptor(
        provider_id=f"llm:{profile.provider_id}",
        display_name=profile.display_name,
        service_kinds=frozenset({ServiceKind.LLM}),
        capabilities=("llm.chat",),
        auth_models=profile.auth_modes,
        pricing_class="local_compute" if profile.managed_runtime else "provider_tariff",
        connection_requirements=_connection_requirements(profile),
        implemented=True,
        default_rights=_unknown_rights(),
    )


def _agent_runtime_descriptor(profile: AgentBackendProfile) -> ProviderDescriptor:
    return ProviderDescriptor(
        provider_id=f"agent-runtime:{profile.id}",
        display_name=profile.display_name,
        service_kinds=frozenset({ServiceKind.AGENT_RUNTIME}),
        capabilities=("agent.runtime",),
        auth_models=(profile.auth_mode.value,),
        pricing_class="unknown",
        resource_requirements=tuple(f"binary:{binary}" for binary in profile.detect_binaries),
        activation_blockers=("operator-managed runtime binary required",),
        implemented=True,
        default_rights=_unknown_rights(),
    )


def _news_descriptor(provider_id: str, display_name: str) -> ProviderDescriptor:
    return ProviderDescriptor(
        provider_id=provider_id,
        display_name=display_name,
        service_kinds=frozenset({ServiceKind.NEWS}),
        capabilities=("news.rss",),
        pricing_class="free",
        implemented=True,
        default_rights=_unknown_rights(),
    )


def _decision_rights() -> RightsResolution:
    """Base checkpoints may be used for offline qualification, not a Live decision.

    The pin matches ``laya_policy.toml``. Live stays closed until a separate
    qualification record exists for that same revision and digest.
    """
    rights = UsageRights(max_evidence_use_scope=EvidenceUseScope.OFFLINE_QUALIFICATION)
    grant = RightsGrant(
        grant_id="flinttrade-policy:laya-offline-qualification",
        basis=RightsBasis.FLINTTRADE_POLICY,
        rights=rights,
        evidence=(
            LicenceFact(
                fact_id="laya-checkpoint-pin",
                subject_kind="checkpoint",
                identifier="convaiinnovations/laya",
                source_uri="https://huggingface.co/convaiinnovations/laya",
                revision="55cf4c4ebb4ebe31b2550e8bdf3bd21b99753851",
                sha256="891102d372688fc2a094dac56a384bc537b87c63f21f9f3dac0be2b7cbc8d86c",
                reviewed_at="unspecified",
                basis=RightsBasis.FLINTTRADE_POLICY,
            ),
        ),
    )
    return RightsResolution(rights=rights, grants=(grant,))


def _decision_descriptors() -> tuple[ProviderDescriptor, ...]:
    """Managed sidecar and an optional operator host. Neither is a chat profile."""
    return (
        ProviderDescriptor(
            provider_id="decision:laya-managed",
            display_name="Laya decision model",
            service_kinds=frozenset({ServiceKind.DECISION}),
            capabilities=("decision.admit",),
            auth_models=("bearer",),
            pricing_class="local_compute",
            connection_requirements=("managed_runtime",),
            software_licence="Apache-2.0",
            model_licence="Apache-2.0",
            resource_requirements=("python-venv:laya[serve]==0.3.21",),
            activation_blockers=(
                "base checkpoint is not qualified for Live",
                "opt-in sidecar",
            ),
            implemented=True,
            default_rights=_decision_rights(),
        ),
        ProviderDescriptor(
            provider_id="decision:systemone-endpoint",
            display_name="System-one decision endpoint",
            service_kinds=frozenset({ServiceKind.DECISION}),
            capabilities=("decision.admit",),
            auth_models=("bearer", "none"),
            pricing_class="local_compute",
            connection_requirements=("operator_endpoint",),
            activation_blockers=(
                "base checkpoint is not qualified for Live",
                "operator host required",
            ),
            implemented=True,
            default_rights=_decision_rights(),
        ),
    )


def _embedding_descriptor(profile: EmbeddingServiceProfile) -> ProviderDescriptor:
    return ProviderDescriptor(
        provider_id=profile.provider_id,
        display_name=profile.display_name,
        service_kinds=frozenset({ServiceKind.EMBEDDING}),
        capabilities=("embedding.create",),
        pricing_class=profile.pricing_class,
        implemented=True,
        default_rights=_unknown_rights(),
    )


def ai_service_descriptors() -> tuple[ProviderDescriptor, ...]:
    """Return fresh immutable descriptors for the implemented AI surfaces."""
    return (
        *(_llm_descriptor(profile) for profile in LLM_PROVIDER_PROFILES),
        *(
            _agent_runtime_descriptor(profile)
            for profile in AGENT_BACKEND_CATALOGUE
            if profile.requires_binary
        ),
        *(_news_descriptor(profile.provider_id, profile.display_name) for profile in NEWS_PROVIDER_PROFILES),
        *(_embedding_descriptor(profile) for profile in EMBEDDING_PROVIDER_PROFILES),
        *_decision_descriptors(),
        ProviderDescriptor(
            provider_id="forecast:external-json",
            display_name="External JSON forecast protocol",
            service_kinds=frozenset({ServiceKind.FORECAST}),
            capabilities=("forecast.protocol",),
            pricing_class="provider_tariff",
            activation_blockers=("forecast worker is not implemented",),
            implemented=False,
            default_rights=_unknown_rights(),
        ),
    )
