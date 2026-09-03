"""Static AI service-provider contributions with no runtime provider I/O."""

from __future__ import annotations

from dataclasses import dataclass

from flinttrade_core.llm_provider_profiles import (
    LLM_PROVIDER_PROFILES,
    LLMProviderProfile,
    _connection_requirements,
)
from flinttrade_core.news_provider_profiles import NEWS_PROVIDER_PROFILES, SENTIMENT_NEWS_CHANNELS
from flinttrade_core.service_providers import ProviderDescriptor, RightsResolution, ServiceKind, UsageRights

from .agent_backends.profiles import AGENT_BACKEND_CATALOGUE, AgentBackendProfile

RSS_SOURCES: dict[str, str] = dict(SENTIMENT_NEWS_CHANNELS)
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
        capabilities=(profile.kind.value,),
        auth_models=(profile.auth_mode.value,),
        pricing_class="local_compute",
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


def _embedding_descriptor(profile: EmbeddingServiceProfile) -> ProviderDescriptor:
    return ProviderDescriptor(
        provider_id=profile.provider_id,
        display_name=profile.display_name,
        service_kinds=frozenset({ServiceKind.EMBEDDING}),
        capabilities=("embedding.embed",),
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
