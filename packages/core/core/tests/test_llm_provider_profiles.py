from __future__ import annotations

from flinttrade_core.llm_provider_profiles import (
    LLM_PROVIDER_BY_ID,
    LLM_PROVIDER_PROFILES,
    LLMProvider,
    llm_provider_descriptors,
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


def test_service_projection_is_namespaced_and_unknown_rights_fail_closed() -> None:
    descriptors = llm_provider_descriptors()
    assert {item.provider_id for item in descriptors} == {
        f"llm:{provider.value}" for provider in LLMProvider
    }
    assert all(item.default_rights.rights.output_use.value == "unknown" for item in descriptors)
    assert all(
        item.default_rights.rights.max_evidence_use_scope.value == "isolated_research"
        for item in descriptors
    )
