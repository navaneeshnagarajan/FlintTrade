"""Tests for the two added LLM backends: Cerebras and Claude Code OAuth auth.

Cerebras is strictly OpenAI-compatible, so it must flow through the existing
``_chat_openai_compat`` path with Bearer auth. Anthropic supports two auth
schemes chosen by token shape: a Claude Code OAuth token uses Bearer plus the
Claude Code identity headers (no ``x-api-key``); a Console API key keeps the
``x-api-key`` path unchanged.
"""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from flinttrade_ai.llm_client import (
    _PROVIDER_URLS,
    LLMClient,
    LLMConfig,
    LLMMessage,
    LLMProvider,
    is_anthropic_oauth_token,
    resolve_endpoint,
)

pytestmark = pytest.mark.unit

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


class _FakeStream:
    """Minimal context-manager stand-in for ``httpx.Client.stream``."""

    def __init__(self, lines: list[str]) -> None:
        self._lines = lines

    def __enter__(self) -> MagicMock:
        resp = MagicMock()
        resp.iter_lines.return_value = iter(self._lines)
        return resp

    def __exit__(self, *_args: object) -> bool:
        return False


# ---------------------------------------------------------------------------
# Cerebras — OpenAI-compatible, Bearer auth, zero new transport code.
# ---------------------------------------------------------------------------


def test_cerebras_is_a_first_class_provider() -> None:
    assert LLMProvider.CEREBRAS.value == "cerebras"
    assert "cerebras" in _PROVIDER_URLS


def test_cerebras_resolves_to_the_fixed_cloud_endpoint() -> None:
    # Cloud provider: fixed URL, host placeholder ignored.
    assert resolve_endpoint("cerebras", "ignored") == "https://api.cerebras.ai/v1/chat/completions"
    assert _PROVIDER_URLS["cerebras"] == "https://api.cerebras.ai/v1/chat/completions"


def test_cerebras_routes_through_openai_compat_with_bearer() -> None:
    # A cerebras client must dispatch chat() to the cerebras endpoint using the
    # shared OpenAI-compatible path with Authorization: Bearer and no x-api-key.
    cfg = LLMConfig(provider="cerebras", host="", model="llama-3.3-70b", api_key="csk-secret")
    client = LLMClient(config=cfg)
    client._http.post = MagicMock(return_value=_fake_response(_OPENAI_PAYLOAD))

    resp = client.chat(_MSGS)

    assert resp.success, resp.error
    assert resp.provider == "cerebras"
    called_url = client._http.post.call_args.args[0]
    headers = client._http.post.call_args.kwargs["headers"]
    assert called_url == "https://api.cerebras.ai/v1/chat/completions"
    assert headers["Authorization"] == "Bearer csk-secret"
    assert "x-api-key" not in headers
    client.close()


def test_from_env_reads_cerebras_api_key(monkeypatch: pytest.MonkeyPatch) -> None:
    # CEREBRAS_API_KEY must be in the from_env fallback list.
    for var in (
        "LLM_API_KEY", "OPENAI_API_KEY", "ANTHROPIC_API_KEY", "GEMINI_API_KEY",
        "DEEPSEEK_API_KEY", "GROQ_API_KEY", "GROK_API_KEY", "MISTRAL_API_KEY",
        "TOGETHER_API_KEY", "NVIDIA_API_KEY", "OPENROUTER_API_KEY",
    ):
        monkeypatch.delenv(var, raising=False)
    monkeypatch.setenv("LLM_PROVIDER", "cerebras")
    monkeypatch.setenv("LLM_HOST", "https://api.cerebras.ai")
    monkeypatch.setenv("CEREBRAS_API_KEY", "csk-from-env")

    cfg = LLMConfig.from_env()

    assert cfg.provider == "cerebras"
    assert cfg.api_key == "csk-from-env"


# ---------------------------------------------------------------------------
# Claude Code OAuth token classifier — one assertion per token shape.
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("token", "is_oauth"),
    [
        ("sk-ant-api03-abcdef", False),   # Console API key → x-api-key
        ("sk-ant-oat01-abcdef", True),    # setup token → OAuth
        ("sk-ant-managed-xyz", True),     # sk-ant- but not sk-ant-api → OAuth
        ("eyJhbGciOiJItokenpart", True),  # JWT → OAuth
        ("cc-opaque-access-token", True),  # Claude Code OAuth access token → OAuth
        ("", False),                       # blank → not OAuth
        ("sk-openai-abc", False),          # non-Anthropic key → not OAuth
        ("minimax-secret", False),         # third-party Anthropic-compatible → not OAuth
    ],
)
def test_is_anthropic_oauth_token_classifies_each_shape(token: str, is_oauth: bool) -> None:
    assert is_anthropic_oauth_token(token) is is_oauth


# ---------------------------------------------------------------------------
# Anthropic auth — OAuth token vs Console API key, blocking and streaming.
# ---------------------------------------------------------------------------


def test_anthropic_oauth_token_uses_bearer_and_betas_no_x_api_key() -> None:
    cfg = LLMConfig(provider="anthropic", host="", model="claude-sonnet-4", api_key="sk-ant-oat01-tok")
    client = LLMClient(config=cfg)
    client._http.post = MagicMock(return_value=_fake_response(_ANTHROPIC_PAYLOAD))

    resp = client.chat(_MSGS)

    assert resp.success, resp.error
    headers = client._http.post.call_args.kwargs["headers"]
    assert headers["Authorization"] == "Bearer sk-ant-oat01-tok"
    assert headers["anthropic-beta"] == "claude-code-20250219,oauth-2025-04-20"
    assert headers["user-agent"] == "claude-code/1.0 (external, cli)"
    assert headers["x-app"] == "cli"
    assert "x-api-key" not in headers
    client.close()


def test_anthropic_api_key_uses_x_api_key_unchanged() -> None:
    cfg = LLMConfig(provider="anthropic", host="", model="claude-sonnet-4", api_key="sk-ant-api03-key")
    client = LLMClient(config=cfg)
    client._http.post = MagicMock(return_value=_fake_response(_ANTHROPIC_PAYLOAD))

    resp = client.chat(_MSGS)

    assert resp.success, resp.error
    headers = client._http.post.call_args.kwargs["headers"]
    assert headers["x-api-key"] == "sk-ant-api03-key"
    assert headers["anthropic-version"] == "2023-06-01"
    assert "Authorization" not in headers
    assert "anthropic-beta" not in headers
    assert "x-app" not in headers
    client.close()


def test_anthropic_stream_oauth_uses_bearer_no_x_api_key() -> None:
    cfg = LLMConfig(provider="anthropic", host="", model="claude-sonnet-4", api_key="cc-oauth-tok")
    client = LLMClient(config=cfg)
    client._http.stream = MagicMock(return_value=_FakeStream([]))

    list(client.chat_stream(_MSGS))

    headers = client._http.stream.call_args.kwargs["headers"]
    assert headers["Authorization"] == "Bearer cc-oauth-tok"
    assert headers["anthropic-beta"] == "claude-code-20250219,oauth-2025-04-20"
    assert headers["user-agent"] == "claude-code/1.0 (external, cli)"
    assert headers["x-app"] == "cli"
    assert "x-api-key" not in headers
    client.close()


def test_anthropic_stream_api_key_uses_x_api_key() -> None:
    cfg = LLMConfig(provider="anthropic", host="", model="claude-sonnet-4", api_key="sk-ant-api03-key")
    client = LLMClient(config=cfg)
    client._http.stream = MagicMock(return_value=_FakeStream([]))

    list(client.chat_stream(_MSGS))

    headers = client._http.stream.call_args.kwargs["headers"]
    assert headers["x-api-key"] == "sk-ant-api03-key"
    assert "Authorization" not in headers
    assert "anthropic-beta" not in headers
    client.close()


# ---------------------------------------------------------------------------
# Credential hygiene — a whitespace-wrapped token must be trimmed before send
# so auth doesn't break on a stray newline from a copy-paste or config file.
# ---------------------------------------------------------------------------


def test_is_anthropic_oauth_token_ignores_surrounding_whitespace() -> None:
    assert is_anthropic_oauth_token("  sk-ant-oat01-tok  ") is True
    assert is_anthropic_oauth_token("\tsk-ant-api03-key\n") is False


def test_anthropic_oauth_token_is_trimmed_before_send() -> None:
    cfg = LLMConfig(provider="anthropic", host="", model="claude-sonnet-4", api_key="  sk-ant-oat01-tok\n")
    client = LLMClient(config=cfg)
    client._http.post = MagicMock(return_value=_fake_response(_ANTHROPIC_PAYLOAD))

    assert client.chat(_MSGS).success
    headers = client._http.post.call_args.kwargs["headers"]
    assert headers["Authorization"] == "Bearer sk-ant-oat01-tok"
    assert "x-api-key" not in headers
    client.close()


def test_anthropic_api_key_is_trimmed_before_send() -> None:
    cfg = LLMConfig(provider="anthropic", host="", model="claude-sonnet-4", api_key="  sk-ant-api03-key\n")
    client = LLMClient(config=cfg)
    client._http.post = MagicMock(return_value=_fake_response(_ANTHROPIC_PAYLOAD))

    assert client.chat(_MSGS).success
    headers = client._http.post.call_args.kwargs["headers"]
    assert headers["x-api-key"] == "sk-ant-api03-key"
    assert "Authorization" not in headers
    client.close()


def test_openai_compat_token_is_trimmed_before_send() -> None:
    cfg = LLMConfig(provider="cerebras", host="", model="llama-3.3-70b", api_key="  csk-secret  ")
    client = LLMClient(config=cfg)
    client._http.post = MagicMock(return_value=_fake_response(_OPENAI_PAYLOAD))

    assert client.chat(_MSGS).success
    headers = client._http.post.call_args.kwargs["headers"]
    assert headers["Authorization"] == "Bearer csk-secret"
    client.close()
