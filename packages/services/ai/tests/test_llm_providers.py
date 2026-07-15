"""Provider wiring tests for the LLM client, including managed Ollama."""

from __future__ import annotations

import hashlib
import logging
from contextlib import contextmanager
from types import SimpleNamespace
from typing import Iterator
from unittest.mock import MagicMock
from urllib.parse import urlparse

import pytest

from flinttrade_ai.llm_client import (
    _PROVIDER_URLS,
    _environment_only_config,
    LLMClient,
    LLMConfig,
    LLMMessage,
    LLMProvider,
    resolve_endpoint,
)

pytestmark = pytest.mark.unit

_MANAGED_OLLAMA_BASE_URL = "http://127.0.0.1:49152"


@pytest.fixture(autouse=True)
def _owned_managed_ollama(monkeypatch: pytest.MonkeyPatch) -> None:
    from flinttrade_core import ollama_runtime

    @contextmanager
    def admitted(model: str) -> Iterator[SimpleNamespace]:
        yield SimpleNamespace(
            base_url=_MANAGED_OLLAMA_BASE_URL,
            model=model,
            digest="a" * 64,
        )

    monkeypatch.setattr(ollama_runtime, "managed_ollama_session", admitted, raising=False)


def test_hermes_is_a_first_class_provider():
    assert LLMProvider.HERMES.value == "hermes"
    assert "hermes" in _PROVIDER_URLS


def test_hermes_resolves_to_a_host_based_openai_compatible_url():
    # Hermes function-calling models are served OpenAI-compatibly (e.g. local
    # Ollama `hermes3`), so the host is operator-supplied like ollama/custom.
    url = _PROVIDER_URLS["hermes"].format(host="http://127.0.0.1:11434")
    assert url == "http://127.0.0.1:11434/v1/chat/completions"


def test_local_runtimes_still_wired():
    for provider in ("ollama", "hermes", "custom"):
        assert provider in _PROVIDER_URLS
        assert "{host}" in _PROVIDER_URLS[provider]
    assert "lmstudio" not in _PROVIDER_URLS


def test_low_level_config_explicitly_rejects_lmstudio() -> None:
    with pytest.raises(ValueError, match="LM Studio is retired"):
        LLMConfig(provider="lmstudio", host="http://127.0.0.1:1234", model="legacy")


@pytest.mark.parametrize("target", ["primary", "fallback"])
def test_client_rejects_a_mutated_lmstudio_config(target: str) -> None:
    primary = LLMConfig(provider="openai", model="primary")
    fallback = LLMConfig(provider="custom", host="http://models.invalid", model="fallback")
    if target == "primary":
        primary.provider = "lmstudio"
    else:
        fallback.provider = "lmstudio"

    with pytest.raises(ValueError, match="LM Studio is retired"):
        LLMClient(config=primary, fallback_config=fallback)


def test_lmstudio_cannot_reach_the_generic_endpoint_fallback() -> None:
    with pytest.raises(ValueError, match="LM Studio is retired"):
        resolve_endpoint("lmstudio", "http://127.0.0.1:1234")


def test_resolve_endpoint_local_providers():
    assert resolve_endpoint("hermes", "http://my-vllm:8000") == \
        "http://my-vllm:8000/v1/chat/completions"


def test_persisted_ollama_host_cannot_resolve_without_runtime_admission() -> None:
    with pytest.raises(ValueError, match="managed runtime admission"):
        resolve_endpoint("ollama", "http://127.0.0.1:11434")


def test_resolve_endpoint_cloud_provider_ignores_host():
    # Cloud providers have a fixed URL — the host placeholder is absent.
    assert resolve_endpoint("openai", "ignored") == "https://api.openai.com/v1/chat/completions"
    assert resolve_endpoint("anthropic", "ignored") == "https://api.anthropic.com/v1/messages"


def test_resolve_endpoint_edge_cases():
    # Custom and unknown providers retain operator-supplied OpenAI-compatible
    # endpoints; managed Ollama is admitted through its runtime owner instead.
    assert resolve_endpoint("somethingnew", "http://h:9999") == "http://h:9999/v1/chat/completions"
    assert resolve_endpoint("custom", "http://h:1") == "http://h:1/v1/chat/completions"


def test_resolve_endpoint_appends_the_path_without_rewriting_authority_case() -> None:
    assert resolve_endpoint(
        "custom",
        "HTTPS://Models.Example.INVALID:443/API/",
    ) == "HTTPS://Models.Example.INVALID:443/API/v1/chat/completions"


@pytest.mark.parametrize(
    "host",
    [
        "https://operator:credential@models.example.invalid/api",
        "https://models.example.invalid/api?token=credential",
        "https://models.example.invalid/api#credential",
    ],
)
def test_resolve_endpoint_rejects_unsafe_api_base_components(host: str) -> None:
    with pytest.raises(ValueError, match="must not contain credentials"):
        resolve_endpoint("custom", host)


@pytest.mark.parametrize(
    "host",
    [
        "http://localhost:1234",
        "http://10.0.0.8:9000",
        "HTTPS://Models.Example.INVALID:443/API/?Token=X/",
    ],
)
def test_environment_only_lmstudio_is_always_rejected(monkeypatch, host: str) -> None:
    monkeypatch.setenv("LLM_PROVIDER", "lmstudio")
    monkeypatch.setenv("LLM_HOST", host)

    with pytest.raises(ValueError, match="LM Studio is retired"):
        _environment_only_config()


def test_unsafe_custom_url_is_rejected_before_httpx_can_log_its_query(caplog) -> None:
    secret = "query-credential-must-not-reach-httpx"

    with (
        caplog.at_level(logging.INFO, logger="httpx"),
        pytest.raises(ValueError, match="must not contain credentials"),
    ):
        LLMConfig(
            provider="custom",
            host=f"https://models.example.invalid/api?token={secret}",
            model="m",
        )

    assert secret not in caplog.text
    assert caplog.records == []


@pytest.mark.parametrize(
    "host",
    [
        "https://127.0.0.1:11434",
        "http://10.0.0.8:11434",
        "http://localhost.evil.invalid:11434",
        "http://operator@127.0.0.1:11434",
        "http://127.0.0.1:11434/proxy",
        "http://127.0.0.1:11435",
    ],
)
def test_ollama_rejects_every_non_managed_endpoint(host: str) -> None:
    with pytest.raises(ValueError, match="managed Ollama endpoint"):
        resolve_endpoint("ollama", host)


def test_custom_provider_retains_remote_endpoint_support() -> None:
    assert resolve_endpoint("custom", "https://models.example.invalid/api") == \
        "https://models.example.invalid/api/v1/chat/completions"


def test_environment_only_config_ignores_the_generic_api_key(monkeypatch) -> None:
    monkeypatch.setenv("LLM_PROVIDER", "openai")
    monkeypatch.setenv("LLM_API_KEY", "unsafe-generic-secret")
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)

    assert _environment_only_config()["api_key"] == ""


def test_environment_only_config_rejects_provider_key_control_characters(monkeypatch) -> None:
    monkeypatch.setenv("LLM_PROVIDER", "openai")
    monkeypatch.setenv("OPENAI_API_KEY", "provider-secret\nsmuggled-header")

    with pytest.raises(ValueError, match="control characters"):
        _environment_only_config()


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
        ("ollama", "http://127.0.0.1:11434", f"{_MANAGED_OLLAMA_BASE_URL}/v1/chat/completions", _OPENAI_PAYLOAD),
        ("custom", "http://127.0.0.1:9000", "http://127.0.0.1:9000/v1/chat/completions", _OPENAI_PAYLOAD),
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

    local = LLMClient(config=LLMConfig(provider="ollama", host="", model="m"))
    local._http.post = MagicMock(return_value=_fake_response(_OPENAI_PAYLOAD))
    local.chat(_MSGS)
    assert local._http.post.call_args.args[0] == f"{_MANAGED_OLLAMA_BASE_URL}/v1/chat/completions"
    local.close()


def test_managed_ollama_refuses_an_unowned_loopback_listener(monkeypatch) -> None:
    from flinttrade_core import ollama_runtime

    @contextmanager
    def refused(_model: str) -> Iterator[SimpleNamespace]:
        raise ollama_runtime.OllamaRuntimeError("managed Ollama runtime is not ready")
        yield SimpleNamespace()

    monkeypatch.setattr(ollama_runtime, "managed_ollama_session", refused, raising=False)
    cfg = LLMConfig(
        provider="ollama",
        host="",
        model="m",
        managed_runtime=True,
    )
    client = LLMClient(config=cfg)
    client._http.post = MagicMock(return_value=_fake_response(_OPENAI_PAYLOAD))

    response = client.chat(_MSGS)

    assert response.error == "Managed Ollama runtime is not ready"
    client._http.post.assert_not_called()
    client.close()


def test_ollama_cannot_opt_out_of_managed_listener_ownership(monkeypatch) -> None:
    from flinttrade_core import ollama_runtime

    @contextmanager
    def refused(_model: str) -> Iterator[SimpleNamespace]:
        raise ollama_runtime.OllamaRuntimeError("managed Ollama runtime is not ready")
        yield SimpleNamespace()

    monkeypatch.setattr(ollama_runtime, "managed_ollama_session", refused, raising=False)
    cfg = LLMConfig(
        provider="ollama",
        host="",
        model="m",
        managed_runtime=False,
    )
    client = LLMClient(config=cfg)
    client._http.post = MagicMock(return_value=_fake_response(_OPENAI_PAYLOAD))

    response = client.chat(_MSGS)

    assert response.error == "Managed Ollama runtime is not ready"
    client._http.post.assert_not_called()
    client.close()


def test_default_client_refreshes_workspace_provider_before_each_request(monkeypatch) -> None:
    configs = iter(
        [
            LLMConfig(provider="openai", model="old", api_key="old-key"),
            LLMConfig(provider="custom", host="https://models.example.invalid", model="new", api_key="new-key"),
        ]
    )
    monkeypatch.setattr(LLMConfig, "from_env", classmethod(lambda _cls: next(configs)))
    client = LLMClient()
    client._http.post = MagicMock(return_value=_fake_response(_OPENAI_PAYLOAD))

    response = client.chat(_MSGS)

    assert response.success
    assert client._http.post.call_args.args[0] == "https://models.example.invalid/v1/chat/completions"
    assert client._http.post.call_args.kwargs["json"]["model"] == "new"
    assert client._http.post.call_args.kwargs["headers"]["Authorization"] == "Bearer new-key"
    client.close()


def test_managed_ollama_chat_uses_the_admitted_model_and_runtime_endpoint(monkeypatch) -> None:
    from flinttrade_core import ollama_runtime

    admitted_models: list[str] = []
    runtime_url = "http://127.0.0.1:49321"
    locked_model = "flinttrade/sha256-" + "a" * 64 + ":locked"

    @contextmanager
    def admitted(model: str) -> Iterator[SimpleNamespace]:
        admitted_models.append(model)
        yield SimpleNamespace(base_url=runtime_url, model=locked_model, digest="a" * 64)

    monkeypatch.setattr(ollama_runtime, "managed_ollama_session", admitted, raising=False)
    client = LLMClient(
        config=LLMConfig(
            provider="ollama",
            host="http://127.0.0.1:11434",
            model="accepted-model",
        )
    )
    client._http.post = MagicMock(return_value=_fake_response(_OPENAI_PAYLOAD))

    response = client.chat(_MSGS)

    assert response.success
    assert admitted_models == ["accepted-model"]
    assert client._http.post.call_args.args[0] == f"{runtime_url}/v1/chat/completions"
    assert client._http.post.call_args.kwargs["json"]["model"] == locked_model
    client.close()


def test_client_accepts_a_bounded_request_timeout() -> None:
    client = LLMClient(
        config=LLMConfig(provider="openai", model="m", api_key="k"),
        timeout_seconds=15.0,
    )

    assert client._http.timeout.read == 15.0
    client.close()


@pytest.mark.parametrize("provider", ["ollama", "Ollama", "OLLAMA"])
def test_managed_ollama_chat_ignores_ambient_proxy_transport(provider: str) -> None:
    config = LLMConfig(provider=provider, model="accepted-model")
    if provider != "ollama":
        config.provider = provider
    client = LLMClient(config=config)
    client._http._managed_ollama.post = MagicMock(return_value=_fake_response(_OPENAI_PAYLOAD))
    client._http._default_client = MagicMock()

    response = client.chat(_MSGS)

    assert response.success
    assert client._http._managed_ollama.trust_env is False
    client._http._managed_ollama.post.assert_called_once()
    client._http._default_client.assert_not_called()
    client.close()


@pytest.mark.parametrize("provider", ["ollama", "Ollama", "OLLAMA"])
def test_managed_ollama_stream_ignores_ambient_proxy_transport(provider: str) -> None:
    config = LLMConfig(provider=provider, model="accepted-model")
    if provider != "ollama":
        config.provider = provider
    client = LLMClient(config=config)
    stream_response = MagicMock()
    stream_response.__enter__.return_value.status_code = 200
    stream_response.__enter__.return_value.iter_lines.return_value = [
        'data: {"choices":[{"delta":{"content":"local"}}]}',
        "data: [DONE]",
    ]
    client._http._managed_ollama.stream = MagicMock(return_value=stream_response)
    client._http._default_client = MagicMock()

    assert list(client.chat_stream(_MSGS)) == ["local"]
    assert client._http._managed_ollama.trust_env is False
    client._http._managed_ollama.stream.assert_called_once()
    client._http._default_client.assert_not_called()
    client.close()


def test_managed_ollama_construction_does_not_parse_ambient_socks_proxy(monkeypatch) -> None:
    monkeypatch.setenv("HTTP_PROXY", "socks5://127.0.0.1:1")
    monkeypatch.setenv("ALL_PROXY", "socks5://127.0.0.1:1")

    client = LLMClient(config=LLMConfig(provider="ollama", model="accepted-model"))

    assert client._http._default is None
    assert client._http._managed_ollama.trust_env is False
    client.close()


def test_custom_loopback_endpoint_retains_environment_aware_transport() -> None:
    client = LLMClient(
        config=LLMConfig(provider="custom", host="http://127.0.0.1:8000", model="custom-model")
    )
    default_client = MagicMock()
    default_client.post.return_value = _fake_response(_OPENAI_PAYLOAD)
    client._http._default = default_client
    client._http._managed_ollama.post = MagicMock(return_value=_fake_response(_OPENAI_PAYLOAD))

    response = client.chat(_MSGS)

    assert response.success
    default_client.post.assert_called_once()
    client._http._managed_ollama.post.assert_not_called()
    client.close()


def test_managed_ollama_stream_refuses_an_unowned_loopback_listener(monkeypatch) -> None:
    from flinttrade_core import ollama_runtime

    @contextmanager
    def refused(_model: str) -> Iterator[SimpleNamespace]:
        raise ollama_runtime.OllamaRuntimeError("managed Ollama runtime is not ready")
        yield SimpleNamespace()

    monkeypatch.setattr(ollama_runtime, "managed_ollama_session", refused, raising=False)
    cfg = LLMConfig(
        provider="ollama",
        host="",
        model="m",
        managed_runtime=True,
    )
    client = LLMClient(config=cfg)
    client._http.stream = MagicMock()

    assert list(client.chat_stream(_MSGS)) == []
    client._http.stream.assert_not_called()
    client.close()


def test_ollama_never_receives_an_authorization_header() -> None:
    cfg = LLMConfig(
        provider="ollama",
        host="",
        model="m",
        api_key="must-not-leave-the-process",
    )
    client = LLMClient(config=cfg)
    client._http.post = MagicMock(return_value=_fake_response(_OPENAI_PAYLOAD))

    response = client.chat(_MSGS)

    assert response.success
    assert "Authorization" not in client._http.post.call_args.kwargs["headers"]
    client.close()


def test_streaming_ollama_never_receives_an_authorization_header() -> None:
    cfg = LLMConfig(
        provider="ollama",
        host="",
        model="m",
        api_key="must-not-leave-the-process",
    )
    stream_response = MagicMock()
    stream_response.__enter__.return_value.iter_lines.return_value = [
        'data: {"choices":[{"delta":{"content":"ok"}}]}',
        "data: [DONE]",
    ]
    client = LLMClient(config=cfg)
    client._http.stream = MagicMock(return_value=stream_response)

    assert list(client.chat_stream(_MSGS)) == ["ok"]
    assert "Authorization" not in client._http.stream.call_args.kwargs["headers"]
    client.close()


def test_managed_ollama_stream_uses_the_configured_model_and_runtime_endpoint(monkeypatch) -> None:
    from flinttrade_core import ollama_runtime

    admitted_models: list[str] = []
    runtime_url = "http://127.0.0.1:49421"
    locked_model = "flinttrade/sha256-" + "b" * 64 + ":locked"

    @contextmanager
    def admitted(model: str) -> Iterator[SimpleNamespace]:
        admitted_models.append(model)
        yield SimpleNamespace(base_url=runtime_url, model=locked_model, digest="b" * 64)

    monkeypatch.setattr(ollama_runtime, "managed_ollama_session", admitted, raising=False)
    stream_response = MagicMock()
    stream_response.__enter__.return_value.iter_lines.return_value = [
        'data: {"choices":[{"delta":{"content":"ok"}}]}',
        "data: [DONE]",
    ]
    client = LLMClient(config=LLMConfig(provider="ollama", host="", model="stream-model"))
    client._http.stream = MagicMock(return_value=stream_response)

    assert list(client.chat_stream(_MSGS)) == ["ok"]
    assert admitted_models == ["stream-model"]
    assert client._http.stream.call_args.args[1] == f"{runtime_url}/v1/chat/completions"
    assert client._http.stream.call_args.kwargs["json"]["model"] == locked_model
    client.close()


def test_managed_ollama_chat_discards_a_response_when_post_admission_fails(monkeypatch) -> None:
    from flinttrade_core import ollama_runtime

    @contextmanager
    def changed(model: str) -> Iterator[SimpleNamespace]:
        yield SimpleNamespace(base_url=_MANAGED_OLLAMA_BASE_URL, model=model, digest="a" * 64)
        raise ollama_runtime.OllamaRuntimeError("loaded model digest changed")

    monkeypatch.setattr(ollama_runtime, "managed_ollama_session", changed, raising=False)
    client = LLMClient(config=LLMConfig(provider="ollama", host="", model="qwen3:8b"))
    client._http.post = MagicMock(return_value=_fake_response(_OPENAI_PAYLOAD))

    response = client.chat(_MSGS)

    assert response.content == ""
    assert response.error == "Managed Ollama runtime is not ready"
    client._http.post.assert_called_once()
    client.close()


def test_managed_ollama_stream_buffers_tokens_until_post_admission_succeeds(monkeypatch) -> None:
    from flinttrade_core import ollama_runtime

    @contextmanager
    def changed(model: str) -> Iterator[SimpleNamespace]:
        yield SimpleNamespace(base_url=_MANAGED_OLLAMA_BASE_URL, model=model, digest="a" * 64)
        raise ollama_runtime.OllamaRuntimeError("loaded model digest changed")

    monkeypatch.setattr(ollama_runtime, "managed_ollama_session", changed, raising=False)
    stream_response = MagicMock()
    stream_response.__enter__.return_value.status_code = 200
    stream_response.__enter__.return_value.iter_lines.return_value = [
        'data: {"choices":[{"delta":{"content":"must-not-escape"}}]}',
        "data: [DONE]",
    ]
    client = LLMClient(config=LLMConfig(provider="ollama", host="", model="qwen3:8b"))
    client._http.stream = MagicMock(return_value=stream_response)

    assert list(client.chat_stream(_MSGS)) == []
    client._http.stream.assert_called_once()
    client.close()


def test_chat_falls_back_to_a_different_providers_endpoint() -> None:
    # Primary (cloud) fails -> the client retries the fallback (local) provider,
    # hitting the fallback's endpoint. Proves fallback is real multi-model routing.
    primary = LLMConfig(provider="openai", host="", model="p", api_key="k")
    fallback = LLMConfig(provider="ollama", host="", model="f")
    client = LLMClient(config=primary, fallback_config=fallback)

    calls: list[str] = []

    def fake_post(url, **_kwargs):
        calls.append(url)
        if urlparse(url).hostname == "api.openai.com":
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
        f"{_MANAGED_OLLAMA_BASE_URL}/v1/chat/completions",
    ]
    client.close()


@pytest.mark.parametrize("provider", ["openai", "anthropic"])
def test_blocking_failure_logs_only_a_bounded_exception_class(provider, caplog) -> None:
    secret = "credential-must-not-reach-logs"

    class CredentialFailure(RuntimeError):
        pass

    client = LLMClient(config=LLMConfig(provider=provider, model="m", api_key=secret))
    client._http.post = MagicMock(side_effect=CredentialFailure(f"transport exposed {secret}"))

    with caplog.at_level(logging.ERROR, logger="flinttrade.ai.llm"):
        response = client.chat(_MSGS)

    assert response.error == "LLM request failed"
    assert secret not in caplog.text
    assert "transport exposed" not in caplog.text
    assert "CredentialFailure" in caplog.text
    assert all(record.exc_info is None for record in caplog.records)
    assert all(len(record.getMessage()) <= 160 for record in caplog.records)
    client.close()


def test_fallback_warning_does_not_log_provider_response_credentials(caplog) -> None:
    secret = "provider-response-credential"
    primary = LLMConfig(provider="openai", model="p", api_key="key")
    fallback = LLMConfig(provider="custom", host="http://fallback.invalid", model="f")
    client = LLMClient(config=primary, fallback_config=fallback)
    failed = MagicMock(status_code=500, text=f"upstream echoed {secret}")
    failed.json.return_value = {}
    client._http.post = MagicMock(side_effect=[failed, _fake_response(_OPENAI_PAYLOAD)])

    with caplog.at_level(logging.WARNING, logger="flinttrade.ai.llm"):
        response = client.chat(_MSGS)

    assert response.success
    assert secret not in caplog.text
    assert "upstream echoed" not in caplog.text
    client.close()


@pytest.mark.parametrize("provider", ["openai", "anthropic"])
@pytest.mark.parametrize(
    "upstream_request_id",
    [
        "outbound-api-key",
        "prefix-outbound-api-key-suffix",
        hashlib.sha256(b"outbound-api-key").hexdigest(),
    ],
)
def test_provider_http_failure_uses_only_a_server_generated_correlation(
    provider: str,
    upstream_request_id: str,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    from flinttrade_ai import llm_client

    provider_body_secret = "provider-response-credential"
    api_key = "outbound-api-key"
    correlation_id = "srv_0123456789abcdef"
    monkeypatch.setattr(llm_client, "_new_correlation_id", lambda: correlation_id, raising=False)
    client = LLMClient(config=LLMConfig(provider=provider, model="m", api_key=api_key))
    failed = MagicMock(
        status_code=401,
        text=f"upstream echoed Bearer {provider_body_secret}",
        headers={"x-request-id": upstream_request_id},
    )
    client._http.post = MagicMock(return_value=failed)

    with caplog.at_level(logging.WARNING, logger="flinttrade.ai.llm"):
        response = client.chat(_MSGS)

    assert response.error == f"HTTP 401 (correlation_id={correlation_id})"
    assert api_key not in response.error
    assert upstream_request_id not in response.error
    assert provider_body_secret not in response.error
    assert "upstream echoed" not in response.error
    assert api_key not in caplog.text
    assert upstream_request_id not in caplog.text
    assert provider_body_secret not in caplog.text
    assert "upstream echoed" not in caplog.text
    assert correlation_id in caplog.text
    client.close()


def test_provider_http_failure_never_reflects_an_unbounded_request_identifier(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from flinttrade_ai import llm_client

    correlation_id = "srv_fedcba9876543210"
    monkeypatch.setattr(llm_client, "_new_correlation_id", lambda: correlation_id, raising=False)
    client = LLMClient(config=LLMConfig(provider="openai", model="m", api_key="key"))
    failed = MagicMock(
        status_code=503,
        text="private provider detail",
        headers={"x-request-id": "r" * 65},
    )
    client._http.post = MagicMock(return_value=failed)

    response = client.chat(_MSGS)

    assert response.error == f"HTTP 503 (correlation_id={correlation_id})"
    assert "r" * 65 not in response.error
    client.close()


def test_llm_config_repr_never_discloses_the_api_key() -> None:
    config = LLMConfig(provider="openai", model="m", api_key="repr-secret")

    assert "repr-secret" not in repr(config)


# ---------------------------------------------------------------------------
# Reasoning-model support for OpenAI-compatible runtimes
# serve reasoning models that emit the chain of thought in
# `message.reasoning_content`, which consumes the `max_tokens` budget. With a
# modest budget the visible `content` comes back empty (`finish_reason ==
# "length"`). The client must capture the reasoning AND retry with a larger
# budget so callers still get a real answer.
# ---------------------------------------------------------------------------

_REASONING_TRUNCATED_PAYLOAD = {
    "choices": [{"message": {"content": "", "reasoning_content": "Let me think step by step..."},
                 "finish_reason": "length"}],
    "usage": {"prompt_tokens": 5, "completion_tokens": 64, "total_tokens": 69,
              "completion_tokens_details": {"reasoning_tokens": 64}},
    "model": "reasoner",
}
_REASONING_FULL_PAYLOAD = {
    "choices": [{"message": {"content": "PCR indicates sentiment.",
                             "reasoning_content": "Thought it through."},
                 "finish_reason": "stop"}],
    "usage": {"prompt_tokens": 5, "completion_tokens": 200, "total_tokens": 205,
              "completion_tokens_details": {"reasoning_tokens": 170}},
    "model": "reasoner",
}


def test_reasoning_content_is_captured_on_the_response() -> None:
    # A reasoning model's chain of thought is surfaced on LLMResponse.reasoning
    # so callers can log/inspect it instead of silently dropping it.
    cfg = LLMConfig(provider="ollama", host="", model="reasoner")
    client = LLMClient(config=cfg)
    client._http.post = MagicMock(return_value=_fake_response(_REASONING_FULL_PAYLOAD))

    resp = client.chat(_MSGS)

    assert resp.success, resp.error
    assert resp.content == "PCR indicates sentiment."
    assert resp.reasoning == "Thought it through."
    client.close()


def test_empty_content_from_truncated_reasoning_retries_with_larger_budget() -> None:
    # The headline reasoning-model fix: the first call exhausts the small budget
    # on reasoning (empty content, finish_reason=length); the client retries once
    # at reasoning_max_tokens and returns the real answer.
    cfg = LLMConfig(provider="ollama", host="", model="reasoner",
                    max_tokens=64, reasoning_max_tokens=4096)
    client = LLMClient(config=cfg)
    client._http.post = MagicMock(side_effect=[
        _fake_response(_REASONING_TRUNCATED_PAYLOAD),
        _fake_response(_REASONING_FULL_PAYLOAD),
    ])

    resp = client.chat(_MSGS, max_tokens=64)

    assert resp.success, resp.error
    assert resp.content == "PCR indicates sentiment."
    assert client._http.post.call_count == 2
    first_payload = client._http.post.call_args_list[0].kwargs["json"]
    second_payload = client._http.post.call_args_list[1].kwargs["json"]
    assert first_payload["max_tokens"] == 64
    assert second_payload["max_tokens"] == 4096
    client.close()


def test_no_retry_when_content_is_present() -> None:
    # Non-reasoning models are unaffected: a normal completion never retries.
    cfg = LLMConfig(provider="ollama", host="", model="m",
                    max_tokens=64, reasoning_max_tokens=4096)
    client = LLMClient(config=cfg)
    client._http.post = MagicMock(return_value=_fake_response(_OPENAI_PAYLOAD))

    resp = client.chat(_MSGS)

    assert resp.success and resp.content == "ok"
    assert client._http.post.call_count == 1
    client.close()


def test_no_retry_when_reasoning_budget_not_larger() -> None:
    # If reasoning_max_tokens <= the requested budget there is no headroom to
    # gain, so the client must not loop or retry.
    cfg = LLMConfig(provider="ollama", host="", model="reasoner",
                    max_tokens=4096, reasoning_max_tokens=4096)
    client = LLMClient(config=cfg)
    client._http.post = MagicMock(return_value=_fake_response(_REASONING_TRUNCATED_PAYLOAD))

    resp = client.chat(_MSGS, max_tokens=4096)

    assert client._http.post.call_count == 1
    assert not resp.success  # genuinely empty; surfaced rather than silently looped
    client.close()


def test_chat_passes_response_format_into_the_payload() -> None:
    # Structured-output passthrough: response_format reaches the OpenAI-compatible
    # payload so a compatible runtime can enforce a JSON schema.
    cfg = LLMConfig(provider="ollama", host="", model="m")
    client = LLMClient(config=cfg)
    client._http.post = MagicMock(return_value=_fake_response(_OPENAI_PAYLOAD))
    schema = {"type": "json_schema",
              "json_schema": {"name": "x", "strict": True, "schema": {"type": "object"}}}

    client.chat(_MSGS, response_format=schema)

    payload = client._http.post.call_args.kwargs["json"]
    assert payload["response_format"] == schema
    client.close()
