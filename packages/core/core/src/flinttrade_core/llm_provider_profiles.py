"""Canonical static facts for supported LLM providers."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from types import MappingProxyType


class LLMProvider(StrEnum):
    """Supported LLM provider identifiers."""

    OLLAMA = "ollama"
    ANTHROPIC = "anthropic"
    OPENAI = "openai"
    GEMINI = "gemini"
    DEEPSEEK = "deepseek"
    GROQ = "groq"
    GROK = "grok"
    MISTRAL = "mistral"
    TOGETHER = "together"
    NVIDIA = "nvidia"
    CEREBRAS = "cerebras"
    OPENROUTER = "openrouter"
    HERMES = "hermes"
    CUSTOM = "custom"


@dataclass(frozen=True, slots=True)
class LLMProviderProfile:
    """One static provider configuration, without connection state or secrets."""

    provider_id: str
    display_name: str
    endpoint_template: str
    auth_modes: tuple[str, ...]
    api_key_env: str = ""
    trust_destination: str = ""
    default_host: str = ""
    default_model: str = ""
    requires_host: bool = False
    managed_runtime: bool = False


LLM_PROVIDER_PROFILES: tuple[LLMProviderProfile, ...] = (
    LLMProviderProfile(
        provider_id=LLMProvider.OLLAMA,
        display_name="Ollama (Managed)",
        endpoint_template="{host}/v1/chat/completions",
        auth_modes=(),
        default_model="qwen3:8b",
        managed_runtime=True,
    ),
    LLMProviderProfile(
        provider_id=LLMProvider.ANTHROPIC,
        display_name="Anthropic",
        endpoint_template="https://api.anthropic.com/v1/messages",
        auth_modes=("api_key", "oauth"),
        api_key_env="ANTHROPIC_API_KEY",
        trust_destination="https://api.anthropic.com",
        default_model="claude-3-5-haiku-20241022",
    ),
    LLMProviderProfile(
        provider_id=LLMProvider.OPENAI,
        display_name="OpenAI",
        endpoint_template="https://api.openai.com/v1/chat/completions",
        auth_modes=("api_key",),
        api_key_env="OPENAI_API_KEY",
        trust_destination="https://api.openai.com",
        default_model="gpt-4o-mini",
    ),
    LLMProviderProfile(
        provider_id=LLMProvider.GEMINI,
        display_name="Google Gemini",
        endpoint_template="https://generativelanguage.googleapis.com/v1beta/openai/chat/completions",
        auth_modes=("api_key",),
        api_key_env="GEMINI_API_KEY",
        trust_destination="https://generativelanguage.googleapis.com",
        default_model="gemini-2.0-flash",
    ),
    LLMProviderProfile(
        provider_id=LLMProvider.DEEPSEEK,
        display_name="DeepSeek",
        endpoint_template="https://api.deepseek.com/v1/chat/completions",
        auth_modes=("api_key",),
        api_key_env="DEEPSEEK_API_KEY",
        trust_destination="https://api.deepseek.com",
        default_model="deepseek-chat",
    ),
    LLMProviderProfile(
        provider_id=LLMProvider.GROQ,
        display_name="Groq",
        endpoint_template="https://api.groq.com/openai/v1/chat/completions",
        auth_modes=("api_key",),
        api_key_env="GROQ_API_KEY",
        trust_destination="https://api.groq.com",
        default_model="llama-3.3-70b-versatile",
    ),
    LLMProviderProfile(
        provider_id=LLMProvider.GROK,
        display_name="Grok (xAI)",
        endpoint_template="https://api.x.ai/v1/chat/completions",
        auth_modes=("api_key",),
        api_key_env="GROK_API_KEY",
        trust_destination="https://api.x.ai",
        default_model="grok-3-mini",
    ),
    LLMProviderProfile(
        provider_id=LLMProvider.MISTRAL,
        display_name="Mistral",
        endpoint_template="https://api.mistral.ai/v1/chat/completions",
        auth_modes=("api_key",),
        api_key_env="MISTRAL_API_KEY",
        trust_destination="https://api.mistral.ai",
        default_model="mistral-small-latest",
    ),
    LLMProviderProfile(
        provider_id=LLMProvider.TOGETHER,
        display_name="Together AI",
        endpoint_template="https://api.together.xyz/v1/chat/completions",
        auth_modes=("api_key",),
        api_key_env="TOGETHER_API_KEY",
        trust_destination="https://api.together.xyz",
        default_model="meta-llama/Llama-3.3-70B-Instruct-Turbo",
    ),
    LLMProviderProfile(
        provider_id=LLMProvider.NVIDIA,
        display_name="NVIDIA NIM",
        endpoint_template="https://integrate.api.nvidia.com/v1/chat/completions",
        auth_modes=("api_key",),
        api_key_env="NVIDIA_API_KEY",
        trust_destination="https://integrate.api.nvidia.com",
    ),
    LLMProviderProfile(
        provider_id=LLMProvider.CEREBRAS,
        display_name="Cerebras",
        endpoint_template="https://api.cerebras.ai/v1/chat/completions",
        auth_modes=("api_key",),
        api_key_env="CEREBRAS_API_KEY",
        trust_destination="https://api.cerebras.ai",
        default_model="llama-3.3-70b",
    ),
    LLMProviderProfile(
        provider_id=LLMProvider.OPENROUTER,
        display_name="OpenRouter",
        endpoint_template="https://openrouter.ai/api/v1/chat/completions",
        auth_modes=("api_key",),
        api_key_env="OPENROUTER_API_KEY",
        trust_destination="https://openrouter.ai",
        default_model="openai/gpt-4o-mini",
    ),
    LLMProviderProfile(
        provider_id=LLMProvider.HERMES,
        display_name="Hermes (Nous)",
        endpoint_template="{host}/v1/chat/completions",
        auth_modes=(),
        api_key_env="HERMES_API_KEY",
        default_model="hermes-3",
        requires_host=True,
    ),
    LLMProviderProfile(
        provider_id=LLMProvider.CUSTOM,
        display_name="Custom Endpoint",
        endpoint_template="{host}/v1/chat/completions",
        auth_modes=("api_key",),
        requires_host=True,
    ),
)

LLM_PROVIDER_BY_ID = MappingProxyType({profile.provider_id: profile for profile in LLM_PROVIDER_PROFILES})
LLM_SERVICE_PROVIDER_IDS = tuple(f"llm:{profile.provider_id}" for profile in LLM_PROVIDER_PROFILES)
LLM_SERVICE_PROVIDER_BY_ID = MappingProxyType(dict(zip(LLM_SERVICE_PROVIDER_IDS, LLM_PROVIDER_PROFILES, strict=True)))


def _connection_requirements(profile: LLMProviderProfile) -> tuple[str, ...]:
    if profile.managed_runtime:
        return ("managed_runtime",)
    if profile.requires_host:
        return ("authenticated_endpoint",) if "api_key" in profile.auth_modes else ("operator_endpoint",)
    if profile.provider_id == LLMProvider.ANTHROPIC:
        return ("api_key_or_oauth",)
    return ("api_key",) if "api_key" in profile.auth_modes else ()
