"""Provider wiring tests for the LLM client (incl. Hermes + the local runtimes)."""

from __future__ import annotations

import pytest

from flinttrade_ai.llm_client import _PROVIDER_URLS, LLMProvider

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
