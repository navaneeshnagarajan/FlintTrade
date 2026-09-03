from __future__ import annotations

from flinttrade_core import llm_provider_profiles as profile_module
from flinttrade_core.llm_provider_profiles import (
    LLM_PROVIDER_BY_ID,
    LLM_PROVIDER_PROFILES,
    LLMProvider,
)


def test_profiles_cover_every_llm_enum_exactly_once() -> None:
    assert tuple(profile.provider_id for profile in LLM_PROVIDER_PROFILES) == tuple(
        provider.value for provider in LLMProvider
    )
    assert set(LLM_PROVIDER_BY_ID) == {provider.value for provider in LLMProvider}


def test_nvidia_is_present_and_claude_oauth_is_an_auth_mode() -> None:
    assert LLM_PROVIDER_BY_ID["nvidia"].endpoint_template == (
        "https://integrate.api.nvidia.com/v1/chat/completions"
    )
    assert "oauth" in LLM_PROVIDER_BY_ID["anthropic"].auth_modes
    assert "claude-code-oauth" not in LLM_PROVIDER_BY_ID


def test_core_profiles_do_not_publish_a_shadow_service_descriptor_authority() -> None:
    assert not hasattr(profile_module, "llm_provider_descriptors")
