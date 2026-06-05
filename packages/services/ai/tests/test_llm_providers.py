"""Provider wiring tests for the LLM client (incl. Hermes + the local runtimes)."""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from flinttrade_ai.llm_client import (
    _PROVIDER_URLS,
    LLMClient,
    LLMConfig,
    LLMMessage,
    LLMProvider,
    resolve_endpoint,
)

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


# ---------------------------------------------------------------------------
# End-to-end provider routing: the mission's "connect to any model" — a client
# built for a provider must actually DISPATCH chat() to that provider's
# endpoint. resolve_endpoint is unit-tested above; these tests prove the full
# client.chat() path uses it (and that switching providers switches the URL).
# ---------------------------------------------------------------------------

_OPENAI_PAYLOAD = {
    "choices": [{"message": {"content": "ok"}, "finish_reason": "stop"}],
    "usage": {"prompt_tokens": 1, "completion_tokens": 1, "total_tokens": 2},
    "model": "echo",
}
_ANTHROPIC_PAYLOAD = {
    "content": [{"type": "text", "text": "ok"}],
    "usage": {"input_tokens": 1, "output_tokens": 1},
    "model": "echo",
    "stop_reason": "end_turn",
}
_MSGS = [LLMMessage(role="user", content="hi")]


def _fake_response(payload: dict) -> MagicMock:
    resp = MagicMock()
    resp.status_code = 200
    resp.json.return_value = payload
    resp.text = ""
    return resp


@pytest.mark.parametrize(
    ("provider", "host", "expected_url", "payload"),
    [
        ("openai", "", "https://api.openai.com/v1/chat/completions", _OPENAI_PAYLOAD),
        ("ollama", "http://127.0.0.1:11434", "http://127.0.0.1:11434/v1/chat/completions", _OPENAI_PAYLOAD),
        ("lmstudio", "http://127.0.0.1:1234", "http://127.0.0.1:1234/v1/chat/completions", _OPENAI_PAYLOAD),
        ("hermes", "http://my-vllm:8000", "http://my-vllm:8000/v1/chat/completions", _OPENAI_PAYLOAD),
        ("anthropic", "", "https://api.anthropic.com/v1/messages", _ANTHROPIC_PAYLOAD),
    ],
)
def test_chat_dispatches_to_the_providers_endpoint(provider, host, expected_url, payload) -> None:
    cfg = LLMConfig(provider=provider, host=host, model="echo", api_key="k")
    client = LLMClient(config=cfg)
    client._http.post = MagicMock(return_value=_fake_response(payload))

    resp = client.chat(_MSGS)

    assert resp.success, resp.error
    assert resp.content == "ok"
    assert resp.provider == provider
    called_url = client._http.post.call_args.args[0]
    assert called_url == expected_url
    client.close()


def test_switching_providers_switches_the_outbound_url() -> None:
    # The same process talks to a cloud model then a local one — each routes
    # to its own endpoint (the "connect to any model" switch, end to end).
    cloud = LLMClient(config=LLMConfig(provider="openai", host="", model="m", api_key="k"))
    cloud._http.post = MagicMock(return_value=_fake_response(_OPENAI_PAYLOAD))
    cloud.chat(_MSGS)
    assert cloud._http.post.call_args.args[0] == "https://api.openai.com/v1/chat/completions"
    cloud.close()

    local = LLMClient(config=LLMConfig(provider="ollama", host="http://127.0.0.1:11434", model="m"))
    local._http.post = MagicMock(return_value=_fake_response(_OPENAI_PAYLOAD))
    local.chat(_MSGS)
    assert local._http.post.call_args.args[0] == "http://127.0.0.1:11434/v1/chat/completions"
    local.close()


def test_chat_falls_back_to_a_different_providers_endpoint() -> None:
    # Primary (cloud) fails -> the client retries the fallback (local) provider,
    # hitting the fallback's endpoint. Proves fallback is real multi-model routing.
    primary = LLMConfig(provider="openai", host="", model="p", api_key="k")
    fallback = LLMConfig(provider="ollama", host="http://127.0.0.1:11434", model="f")
    client = LLMClient(config=primary, fallback_config=fallback)

    calls: list[str] = []

    def fake_post(url, **_kwargs):
        calls.append(url)
        if "openai.com" in url:
            bad = MagicMock()
            bad.status_code = 500
            bad.text = "boom"
            bad.json.return_value = {}
            return bad
        return _fake_response(_OPENAI_PAYLOAD)

    client._http.post = MagicMock(side_effect=fake_post)

    resp = client.chat(_MSGS)

    assert resp.success, resp.error
    assert resp.provider == "ollama"  # fell back to the local model
    assert calls == [
        "https://api.openai.com/v1/chat/completions",
        "http://127.0.0.1:11434/v1/chat/completions",
    ]
    client.close()
