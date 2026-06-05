"""Provider wiring tests for the LLM client (incl. Hermes + the local runtimes)."""

from __future__ import annotations

import pytest

from flinttrade_ai.llm_client import _PROVIDER_URLS, LLMProvider, resolve_endpoint

pytestmark = pytest.mark.unit


def test_hermes_is_a_first_class_provider():
    assert LLMProvider.HERMES.value == "hermes"
    assert "hermes" in _PROVIDER_URLS


def test_hermes_resolves_to_a_host_based_openai_compatible_url():
    # Hermes function-calling models are served OpenAI-compatibly (e.g. local
    # Ollama `hermes3`), so the host is operator-supplied like ollama/custom.
    url = _PROVIDER_URLS["hermes"].format(host="http://127.0.0.1:11434")
    assert url == "http://127.0.0.1:11434/v1/chat/completions"


def test_local_runtimes_still_wired():
    # The spec's local model runtimes must remain available.
    for provider in ("ollama", "lmstudio"):
        assert provider in _PROVIDER_URLS
        assert "{host}" in _PROVIDER_URLS[provider]


def test_resolve_endpoint_local_providers():
    # The mission's "local via Ollama and LM Studio" — the resolution function the
    # request path actually calls must interpolate the runtime host.
    assert resolve_endpoint("ollama", "http://127.0.0.1:11434") == \
        "http://127.0.0.1:11434/v1/chat/completions"
    assert resolve_endpoint("lmstudio", "http://127.0.0.1:1234") == \
        "http://127.0.0.1:1234/v1/chat/completions"
    assert resolve_endpoint("hermes", "http://my-vllm:8000") == \
        "http://my-vllm:8000/v1/chat/completions"


def test_resolve_endpoint_cloud_provider_ignores_host():
    # Cloud providers have a fixed URL — the host placeholder is absent.
    assert resolve_endpoint("openai", "ignored") == "https://api.openai.com/v1/chat/completions"
    assert resolve_endpoint("anthropic", "ignored") == "https://api.anthropic.com/v1/messages"


def test_resolve_endpoint_edge_cases():
    # Trailing slash stripped; provider case-insensitive; unknown provider falls
    # back to a generic OpenAI-compatible path so ANY local endpoint works.
    assert resolve_endpoint("OLLAMA", "http://h:11434/") == "http://h:11434/v1/chat/completions"
    assert resolve_endpoint("somethingnew", "http://h:9999") == "http://h:9999/v1/chat/completions"
    assert resolve_endpoint("custom", "http://h:1") == "http://h:1/v1/chat/completions"
