"""Unified LLM client supporting multiple providers via OpenAI-compatible API.

Providers:
- Managed Ollama (local, backend-owned dynamic loopback endpoint)
- Anthropic Claude (cloud; both a Console API key and a Claude Code OAuth token —
  the auth scheme is chosen by token shape, see ``is_anthropic_oauth_token``)
- OpenAI and other OpenAI-compatible clouds (incl. Cerebras)

Provider selection from .env: LLM_PROVIDER, LLM_HOST, LLM_MODEL.
Retry with fallback: primary fails → fallback provider.
"""

from __future__ import annotations

import json
import logging
import os
import secrets
import unicodedata
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any, Generator
from urllib.parse import urlsplit, urlunsplit

import httpx

logger = logging.getLogger("flinttrade.ai.llm")
_LMSTUDIO_RETIRED_ERROR = "LM Studio is retired; use managed Ollama or the Custom provider"


def _reject_retired_provider(provider: str) -> None:
    if (provider or "").strip().lower() == "lmstudio":
        raise ValueError(_LMSTUDIO_RETIRED_ERROR)


class _ProviderHTTPClient:
    """Keep managed Ollama proxy-free while preserving provider proxy behaviour."""

    def __init__(self, *, timeout: float) -> None:
        self._timeout = httpx.Timeout(timeout)
        self._default: httpx.Client | None = None
        self._managed_ollama = httpx.Client(timeout=self._timeout, trust_env=False)

    @property
    def timeout(self) -> httpx.Timeout:
        return self._timeout

    def _default_client(self) -> httpx.Client:
        if self._default is None:
            self._default = httpx.Client(timeout=self._timeout)
        return self._default

    def post(
        self,
        url: str | httpx.URL,
        *,
        managed_ollama: bool = False,
        **kwargs: Any,
    ) -> httpx.Response:
        client = self._managed_ollama if managed_ollama else self._default_client()
        return client.post(url, **kwargs)

    def stream(
        self,
        method: str,
        url: str | httpx.URL,
        *,
        managed_ollama: bool = False,
        **kwargs: Any,
    ) -> Any:
        client = self._managed_ollama if managed_ollama else self._default_client()
        return client.stream(method, url, **kwargs)

    def close(self) -> None:
        try:
            if self._default is not None:
                self._default.close()
        finally:
            self._managed_ollama.close()


class LLMProvider(StrEnum):
    """Supported LLM providers.

    Local: Ollama (user's hardware, no cloud inference needed)
    Cloud: Any provider with an API (user brings their own key)
    Custom: Any OpenAI-compatible endpoint (user provides host URL)
    """

    OLLAMA = "ollama"
    ANTHROPIC = "anthropic"
    OPENAI = "openai"
    GEMINI = "gemini"
    DEEPSEEK = "deepseek"
    GROQ = "groq"       # Groq — fast LPU inference (groq.com)
    GROK = "grok"       # Grok — xAI's model (x.ai)
    MISTRAL = "mistral"
    TOGETHER = "together"
    NVIDIA = "nvidia"    # NVIDIA NIM — OpenAI-compatible (integrate.api.nvidia.com)
    CEREBRAS = "cerebras"  # Cerebras — wafer-scale fast inference, OpenAI-compatible (cerebras.ai)
    OPENROUTER = "openrouter"  # Routes to 100+ models
    HERMES = "hermes"    # Nous Hermes function-calling agent models (OpenAI-compatible host)
    CUSTOM = "custom"    # Any OpenAI-compatible endpoint


@dataclass
class LLMConfig:
    """LLM provider configuration."""

    provider: str = ""
    host: str = ""
    model: str = ""
    api_key: str = field(default="", repr=False)
    context_length: int = 32768
    temperature: float = 0.7
    max_tokens: int = 4096
    managed_runtime: bool = False
    # Budget used to retry a reasoning model whose chain of thought consumed the
    # whole ``max_tokens`` budget, leaving an empty visible answer. See
    # ``LLMClient._chat_openai_compat``. Set to 0 to disable the retry.
    reasoning_max_tokens: int = 8192

    def __post_init__(self) -> None:
        self.provider = self.provider.strip().lower()
        _reject_retired_provider(self.provider)
        if self.provider:
            _validate_configurable_api_base_url(self.provider, self.host)

    @classmethod
    def from_env(cls) -> LLMConfig:
        """Load LLM config from workspace.json, with env var overrides."""
        try:
            from flinttrade_core.llm_config import read_effective_llm_config
        except ImportError:
            effective = _environment_only_config()
        else:
            effective = read_effective_llm_config()

        provider = str(effective.get("provider") or "")
        return cls(
            provider=provider,
            host=str(effective.get("host") or ""),
            model=str(effective.get("model") or ""),
            api_key=str(effective.get("api_key") or ""),
            context_length=int(os.getenv("LLM_CONTEXT_LENGTH", "32768")),
            reasoning_max_tokens=int(os.getenv("LLM_REASONING_MAX_TOKENS", "8192")),
            managed_runtime=provider.strip().lower() == "ollama",
        )


@dataclass
class LLMMessage:
    """A single message in a conversation."""

    role: str  # "system", "user", "assistant"
    content: str


@dataclass
class LLMResponse:
    """Response from an LLM completion."""

    content: str = ""
    model: str = ""
    provider: str = ""
    prompt_tokens: int = 0
    completion_tokens: int = 0
    total_tokens: int = 0
    finish_reason: str = ""
    reasoning: str = ""  # chain-of-thought from reasoning models, if surfaced
    error: str = ""

    @property
    def success(self) -> bool:
        return bool(self.content) and not self.error


# Provider-specific base URLs for the OpenAI-compatible chat endpoint.
# Most cloud providers offer OpenAI-compatible APIs.
# Local providers use {host} placeholder resolved at runtime.
# "custom" and "openrouter" let users connect ANY endpoint.
_PROVIDER_URLS: dict[str, str] = {
    # Local (no internet needed)
    "ollama": "{host}/v1/chat/completions",
    # Cloud (user provides API key)
    "openai": "https://api.openai.com/v1/chat/completions",
    "anthropic": "https://api.anthropic.com/v1/messages",
    "gemini": "https://generativelanguage.googleapis.com/v1beta/openai/chat/completions",
    "deepseek": "https://api.deepseek.com/v1/chat/completions",
    "groq": "https://api.groq.com/openai/v1/chat/completions",
    "grok": "https://api.x.ai/v1/chat/completions",
    "mistral": "https://api.mistral.ai/v1/chat/completions",
    "together": "https://api.together.xyz/v1/chat/completions",
    "nvidia": "https://integrate.api.nvidia.com/v1/chat/completions",
    # Cerebras — strictly OpenAI-compatible (Bearer auth), flows through
    # ``_chat_openai_compat`` with no extra transport code.
    "cerebras": "https://api.cerebras.ai/v1/chat/completions",
    "openrouter": "https://openrouter.ai/api/v1/chat/completions",
    # Hermes — Nous Hermes function-calling/agent models, served OpenAI-compatibly
    # (local Ollama `hermes3`, a self-hosted vLLM, or any Hermes API host).
    "hermes": "{host}/v1/chat/completions",
    # Custom (any OpenAI-compatible endpoint)
    "custom": "{host}/v1/chat/completions",
}

_OLLAMA_BASE_URL = ""
_PROVIDER_API_KEY_ENV = {
    "anthropic": "ANTHROPIC_API_KEY",
    "cerebras": "CEREBRAS_API_KEY",
    "deepseek": "DEEPSEEK_API_KEY",
    "gemini": "GEMINI_API_KEY",
    "grok": "GROK_API_KEY",
    "groq": "GROQ_API_KEY",
    "hermes": "HERMES_API_KEY",
    "mistral": "MISTRAL_API_KEY",
    "nvidia": "NVIDIA_API_KEY",
    "openai": "OPENAI_API_KEY",
    "openrouter": "OPENROUTER_API_KEY",
    "together": "TOGETHER_API_KEY",
}


def _normalise_ollama_host(host: str) -> str:
    value = (host or "").strip()
    if not value:
        return _OLLAMA_BASE_URL
    try:
        parsed = urlsplit(value)
        port = parsed.port
    except ValueError as exc:
        raise ValueError("Ollama requires the managed Ollama endpoint") from exc
    if (
        parsed.scheme.lower() != "http"
        or (parsed.hostname or "").lower() not in {"127.0.0.1", "localhost", "::1"}
        or port != 11434
        or parsed.username is not None
        or parsed.password is not None
        or parsed.path not in {"", "/"}
        or parsed.query
        or parsed.fragment
    ):
        raise ValueError("Ollama requires the managed Ollama endpoint")
    return _OLLAMA_BASE_URL


def _validate_configurable_api_base_url(provider: str, host: str) -> str:
    """Reject URL components that HTTPX may include in request logs."""
    provider_name = (provider or "").strip().lower()
    template = _PROVIDER_URLS.get(provider_name, "{host}/v1/chat/completions")
    value = (host or "").strip()
    if provider_name == "ollama" or "{host}" not in template:
        return value
    try:
        parsed = urlsplit(value)
        _ = parsed.port
    except ValueError as exc:
        raise ValueError("LLM API base URL is invalid") from exc
    if parsed.username is not None or parsed.password is not None or parsed.query or parsed.fragment:
        raise ValueError(
            "LLM API base URLs must not contain credentials, query parameters, or fragments"
        )
    if parsed.scheme.lower() not in {"http", "https"} or parsed.hostname is None:
        raise ValueError("LLM API base URL must be an absolute HTTP(S) URL")
    return value


def _normalise_environment_api_key(value: str) -> str:
    if any(unicodedata.category(character) == "Cc" for character in value):
        raise ValueError("LLM API keys must not contain control characters")
    return value.strip()


def _append_url_path(host: str, endpoint_path: str) -> str:
    """Append a path before any query or fragment in an operator URL."""
    raw = (host or "").strip()
    try:
        parsed = urlsplit(raw)
    except ValueError:
        return f"{raw.rstrip('/')}/{endpoint_path.lstrip('/')}"
    original_scheme = raw.partition(":")[0] if parsed.scheme else ""
    path = f"{parsed.path.rstrip('/')}/{endpoint_path.lstrip('/')}"
    return urlunsplit((original_scheme, parsed.netloc, path, parsed.query, parsed.fragment))


def _environment_only_config() -> dict[str, str]:
    provider = os.getenv("LLM_PROVIDER", "").strip().lower() or "ollama"
    host = os.getenv("LLM_HOST", "").strip()
    if provider == "lmstudio":
        raise ValueError(_LMSTUDIO_RETIRED_ERROR)
    if provider == "ollama":
        host = _normalise_ollama_host(host)
        api_key = ""
    else:
        host = _validate_configurable_api_base_url(provider, host)
        key_name = _PROVIDER_API_KEY_ENV.get(provider, "")
        api_key = _normalise_environment_api_key(os.getenv(key_name, "")) if key_name else ""
    return {
        "provider": provider,
        "host": host,
        "model": os.getenv("LLM_MODEL", "").strip(),
        "api_key": api_key,
    }


def resolve_endpoint(provider: str, host: str) -> str:
    """Resolve the OpenAI-compatible chat endpoint for a provider.

    Hermes and custom endpoints interpolate the operator-supplied ``host``;
    managed Ollama is resolved only through runtime admission. Cloud providers
    return their fixed URL. An
    unknown provider falls back to a generic ``{host}/v1/chat/completions`` so any
    OpenAI-compatible endpoint still works. This is the single resolution point
    used by both the blocking and streaming request paths.
    """
    provider_name = (provider or "").lower()
    _reject_retired_provider(provider_name)
    if provider_name == "ollama":
        _normalise_ollama_host(host)
        raise ValueError("Ollama endpoint requires managed runtime admission")
    template = _PROVIDER_URLS.get(provider_name, "{host}/v1/chat/completions")
    if "{host}" not in template:
        return template
    safe_host = _validate_configurable_api_base_url(provider_name, host)
    return _append_url_path(safe_host, template.removeprefix("{host}/"))


def _new_correlation_id() -> str:
    return f"llm_{secrets.token_hex(8)}"


def _provider_http_error(response: httpx.Response) -> str:
    """Return status plus a local correlation, never upstream-controlled content."""
    status_code = int(response.status_code)
    correlation_id = _new_correlation_id()
    logger.warning(
        "LLM provider HTTP failure (status=%d, correlation_id=%s)",
        status_code,
        correlation_id,
    )
    return f"HTTP {status_code} (correlation_id={correlation_id})"


def _openai_compat_headers(cfg: LLMConfig) -> dict[str, str]:
    headers = {"Content-Type": "application/json"}
    api_key = (cfg.api_key or "").strip()
    if cfg.provider.strip().lower() != "ollama" and api_key:
        headers["Authorization"] = f"Bearer {api_key}"
    return headers


def _normalise_managed_ollama_base_url(base_url: str) -> str:
    value = (base_url or "").strip().rstrip("/")
    try:
        parsed = urlsplit(value)
        port = parsed.port
    except ValueError:
        return ""
    if (
        parsed.scheme.lower() != "http"
        or (parsed.hostname or "").lower() not in {"127.0.0.1", "localhost", "::1"}
        or port is None
        or parsed.username is not None
        or parsed.password is not None
        or parsed.path not in {"", "/"}
        or parsed.query
        or parsed.fragment
    ):
        return ""
    return value


def _request_endpoint(cfg: LLMConfig, managed_ollama_base_url: str = "") -> str:
    if cfg.provider.strip().lower() == "ollama":
        if not managed_ollama_base_url:
            raise ValueError("Ollama endpoint requires managed runtime admission")
        return f"{managed_ollama_base_url}/v1/chat/completions"
    return resolve_endpoint(cfg.provider, cfg.host)


def _bounded_log_label(value: str, *, limit: int = 32) -> str:
    safe = "".join(character for character in value if character.isascii() and (character.isalnum() or character in "_-"))
    return (safe or "unknown")[:limit]


def _bounded_exception_class(exc: Exception) -> str:
    return _bounded_log_label(type(exc).__name__, limit=64)


# Beta and identity headers Anthropic requires for Claude Code OAuth traffic.
# Without the Claude Code fingerprint, Anthropic's infrastructure intermittently
# rejects OAuth requests. Mirrors the Nous Hermes adapter's OAuth branch.
_ANTHROPIC_OAUTH_BETAS = "claude-code-20250219,oauth-2025-04-20"
_CLAUDE_CODE_USER_AGENT = "claude-code/1.0 (external, cli)"


def is_anthropic_oauth_token(token: str) -> bool:
    """Return True when an Anthropic credential is an OAuth / Claude Code token.

    The Anthropic Messages API accepts two auth schemes and the right one is
    determined purely by the credential's shape. A Claude Code OAuth / setup
    token is sent as ``Authorization: Bearer`` with the Claude Code identity
    headers; a regular Console API key keeps the standard ``x-api-key`` path.

    A token is treated as OAuth when it:

    - starts with ``sk-ant-`` but NOT ``sk-ant-api`` (setup tokens such as
      ``sk-ant-oat-…`` and managed keys); or
    - starts with ``eyJ`` (a JWT issued by the Anthropic OAuth flow); or
    - starts with ``cc-`` (a Claude Code OAuth access token).

    Anything else — a blank token, a Console API key (``sk-ant-api…``), or a
    non-Anthropic key (MiniMax, Alibaba, …) — returns ``False`` so the standard
    ``x-api-key`` path is used.

    Args:
        token: The operator-supplied Anthropic credential.

    Returns:
        ``True`` for an OAuth / Claude Code token, ``False`` otherwise.
    """
    # Trim on classification so a whitespace-wrapped credential (a trailing
    # newline from a copy-paste or a config file) is matched by shape rather
    # than being mis-classified and sent verbatim.
    token = (token or "").strip()
    if not token:
        return False
    # Regular Anthropic Console API key — x-api-key auth, never OAuth.
    if token.startswith("sk-ant-api"):
        return False
    # Anthropic-issued setup tokens (sk-ant-oat-*) and managed keys.
    if token.startswith("sk-ant-"):
        return True
    # JWT from the Anthropic OAuth flow.
    if token.startswith("eyJ"):
        return True
    # Opaque Claude Code OAuth access token.
    if token.startswith("cc-"):
        return True
    return False


def _anthropic_headers(api_key: str) -> dict[str, str]:
    """Build Anthropic Messages API headers, choosing auth by token shape.

    A Claude Code OAuth token (per :func:`is_anthropic_oauth_token`) is sent as
    ``Authorization: Bearer`` with the OAuth beta headers plus the Claude Code
    identity (``user-agent``/``x-app``) and no ``x-api-key``; a regular Console
    API key keeps the ``x-api-key`` header. This is the single header-resolution
    point shared by the blocking and streaming Anthropic request paths.

    Args:
        api_key: The operator-supplied Anthropic credential.

    Returns:
        The request headers for the Anthropic Messages API.
    """
    # Trim before sending: a stray leading/trailing space or newline in the
    # credential would otherwise be transmitted verbatim and rejected by auth.
    api_key = (api_key or "").strip()
    headers: dict[str, str] = {
        "Content-Type": "application/json",
        "anthropic-version": "2023-06-01",
    }
    if is_anthropic_oauth_token(api_key):
        headers["Authorization"] = f"Bearer {api_key}"
        headers["anthropic-beta"] = _ANTHROPIC_OAUTH_BETAS
        headers["user-agent"] = _CLAUDE_CODE_USER_AGENT
        headers["x-app"] = "cli"
    else:
        headers["x-api-key"] = api_key
    return headers


def estimate_tokens(text: str) -> int:
    """Rough token count estimate (~4 chars per token for English)."""
    return max(1, len(text) // 4)


class LLMClient:
    """Unified LLM client with fallback support.

    Usage::

        client = LLMClient()  # reads from .env
        response = client.chat([
            LLMMessage(role="system", content="You are a trading assistant."),
            LLMMessage(role="user", content="What is PCR?"),
        ])
        print(response.content)

        # Streaming
        for chunk in client.chat_stream(messages):
            print(chunk, end="")
    """

    def __init__(
        self,
        config: LLMConfig | None = None,
        fallback_config: LLMConfig | None = None,
        *,
        timeout_seconds: float = 120.0,
    ) -> None:
        if timeout_seconds <= 0:
            raise ValueError("timeout_seconds must be positive")
        self._dynamic_config = config is None
        self.config = config if config is not None else LLMConfig.from_env()
        self.fallback_config = fallback_config
        _reject_retired_provider(self.config.provider)
        if self.fallback_config is not None:
            _reject_retired_provider(self.fallback_config.provider)
        self._http = _ProviderHTTPClient(timeout=timeout_seconds)

    def _current_config(self) -> LLMConfig:
        if self._dynamic_config:
            self.config = LLMConfig.from_env()
        _reject_retired_provider(self.config.provider)
        return self.config

    def close(self) -> None:
        self._http.close()

    def __enter__(self) -> LLMClient:
        return self

    def __exit__(self, *args: Any) -> None:
        self.close()

    # ------------------------------------------------------------------
    # Chat completion
    # ------------------------------------------------------------------

    def chat(
        self,
        messages: list[LLMMessage],
        temperature: float | None = None,
        max_tokens: int | None = None,
        model: str | None = None,
        response_format: dict[str, Any] | None = None,
    ) -> LLMResponse:
        """Send a chat completion request. Falls back to secondary on failure.

        Args:
            messages: Conversation messages.
            temperature: Sampling temperature override.
            max_tokens: Token cap override.
            model: Model override.
            response_format: Optional OpenAI-compatible structured-output hint
                (e.g. ``{"type": "json_schema", "json_schema": {...}}``) passed
                straight to the provider for constrained decoding. Ignored by the
                Anthropic path.
        """
        config = self._current_config()
        resp = self._chat_with_config(config, messages, temperature, max_tokens, model, response_format)
        if resp.success:
            return resp

        if self.fallback_config:
            logger.warning(
                "Primary LLM failed (%s); trying fallback (%s)",
                _bounded_log_label(config.provider),
                _bounded_log_label(self.fallback_config.provider),
            )
            return self._chat_with_config(
                self.fallback_config, messages, temperature, max_tokens, model,
                response_format,
            )

        return resp

    def _chat_with_config(
        self,
        cfg: LLMConfig,
        messages: list[LLMMessage],
        temperature: float | None,
        max_tokens: int | None,
        model: str | None,
        response_format: dict[str, Any] | None = None,
    ) -> LLMResponse:
        """Execute chat completion against a specific provider config."""
        _reject_retired_provider(cfg.provider)
        provider = cfg.provider.lower()
        use_model = model or cfg.model
        use_temp = temperature if temperature is not None else cfg.temperature
        use_max = max_tokens or cfg.max_tokens

        if provider == "ollama":
            try:
                from flinttrade_core.ollama_runtime import managed_ollama_session

                with managed_ollama_session(use_model) as admission:
                    managed_ollama_base_url = _normalise_managed_ollama_base_url(admission.base_url)
                    if not managed_ollama_base_url:
                        raise ValueError("managed Ollama endpoint is invalid")
                    return self._chat_openai_compat(
                        cfg,
                        messages,
                        admission.model,
                        use_temp,
                        use_max,
                        response_format,
                        managed_ollama_base_url=managed_ollama_base_url,
                    )
            except Exception as exc:  # noqa: BLE001 - admission failures are bounded and fail closed
                logger.warning(
                    "Managed Ollama inference refused (exception=%s)",
                    _bounded_exception_class(exc),
                )
                return LLMResponse(
                    provider=cfg.provider,
                    model=use_model,
                    error="Managed Ollama runtime is not ready",
                )

        if provider == "anthropic":
            return self._chat_anthropic(cfg, messages, use_model, use_temp, use_max)

        return self._chat_openai_compat(
            cfg,
            messages,
            use_model,
            use_temp,
            use_max,
            response_format,
        )

    def _chat_openai_compat(
        self,
        cfg: LLMConfig,
        messages: list[LLMMessage],
        model: str,
        temperature: float,
        max_tokens: int,
        response_format: dict[str, Any] | None = None,
        *,
        managed_ollama_base_url: str = "",
        allow_reasoning_retry: bool = True,
    ) -> LLMResponse:
        """OpenAI-compatible endpoint (Ollama, custom endpoints, OpenAI).

        Reasoning models (Qwen3, DeepSeek-R1, …) emit the chain of thought in
        ``message.reasoning_content``, which counts against ``max_tokens``. With a
        modest budget the reasoning exhausts the cap and the visible ``content``
        comes back empty (``finish_reason == "length"``). When that happens we
        retry once with ``cfg.reasoning_max_tokens`` so callers still receive a
        real answer; non-reasoning models are never retried.
        """
        url = _request_endpoint(cfg, managed_ollama_base_url)

        headers = _openai_compat_headers(cfg)

        payload: dict[str, Any] = {
            "model": model,
            "messages": [{"role": m.role, "content": m.content} for m in messages],
            "temperature": temperature,
            "max_tokens": max_tokens,
            "stream": False,
        }
        if response_format is not None:
            payload["response_format"] = response_format

        try:
            resp = self._http.post(
                url,
                managed_ollama=cfg.provider.strip().lower() == "ollama",
                json=payload,
                headers=headers,
            )
            if resp.status_code >= 400:
                return LLMResponse(
                    provider=cfg.provider, model=model,
                    error=_provider_http_error(resp),
                )
            data = resp.json()
            choice = data.get("choices", [{}])[0]
            message = choice.get("message", {}) or {}
            usage = data.get("usage", {})
            content = message.get("content", "") or ""
            finish_reason = choice.get("finish_reason", "")
            reasoning = message.get("reasoning_content") or message.get("reasoning") or ""
            reasoning_tokens = (usage.get("completion_tokens_details") or {}).get(
                "reasoning_tokens", 0
            )

            # Reasoning ate the whole budget before producing a visible answer —
            # retry once with the larger reasoning budget.
            if (
                allow_reasoning_retry
                and not content.strip()
                and finish_reason == "length"
                and (reasoning or reasoning_tokens)
                and cfg.reasoning_max_tokens > max_tokens
            ):
                logger.info(
                    "Reasoning model returned empty content at max_tokens=%d; "
                    "retrying at %d.", max_tokens, cfg.reasoning_max_tokens,
                )
                return self._chat_openai_compat(
                    cfg, messages, model, temperature, cfg.reasoning_max_tokens,
                    response_format,
                    managed_ollama_base_url=managed_ollama_base_url,
                    allow_reasoning_retry=False,
                )

            return LLMResponse(
                content=content,
                model=data.get("model", model),
                provider=cfg.provider,
                prompt_tokens=usage.get("prompt_tokens", 0),
                completion_tokens=usage.get("completion_tokens", 0),
                total_tokens=usage.get("total_tokens", 0),
                finish_reason=finish_reason,
                reasoning=reasoning,
            )
        except Exception as exc:
            logger.error(
                "OpenAI-compatible chat request failed (provider=%s, exception=%s)",
                _bounded_log_label(cfg.provider),
                _bounded_exception_class(exc),
            )
            return LLMResponse(provider=cfg.provider, model=model, error="LLM request failed")

    def _chat_anthropic(
        self,
        cfg: LLMConfig,
        messages: list[LLMMessage],
        model: str,
        temperature: float,
        max_tokens: int,
    ) -> LLMResponse:
        """Anthropic Messages API.

        Auth is chosen by token shape: an operator-supplied Claude Code OAuth
        token is sent as ``Authorization: Bearer`` with the Claude Code identity
        headers; a Console API key keeps ``x-api-key`` (see
        :func:`is_anthropic_oauth_token`).
        """
        url = "https://api.anthropic.com/v1/messages"
        headers = _anthropic_headers(cfg.api_key)

        # Separate system message
        system = ""
        api_messages = []
        for m in messages:
            if m.role == "system":
                system = m.content
            else:
                api_messages.append({"role": m.role, "content": m.content})

        payload: dict[str, Any] = {
            "model": model,
            "messages": api_messages,
            "max_tokens": max_tokens,
            "temperature": temperature,
        }
        if system:
            payload["system"] = system

        try:
            resp = self._http.post(url, json=payload, headers=headers)
            if resp.status_code >= 400:
                return LLMResponse(
                    provider="anthropic", model=model,
                    error=_provider_http_error(resp),
                )
            data = resp.json()
            content_blocks = data.get("content", [])
            content = "".join(b.get("text", "") for b in content_blocks if b.get("type") == "text")
            usage = data.get("usage", {})
            return LLMResponse(
                content=content,
                model=data.get("model", model),
                provider="anthropic",
                prompt_tokens=usage.get("input_tokens", 0),
                completion_tokens=usage.get("output_tokens", 0),
                total_tokens=usage.get("input_tokens", 0) + usage.get("output_tokens", 0),
                finish_reason=data.get("stop_reason", ""),
            )
        except Exception as exc:
            logger.error("Anthropic chat request failed (exception=%s)", _bounded_exception_class(exc))
            return LLMResponse(provider="anthropic", model=model, error="LLM request failed")

    # ------------------------------------------------------------------
    # Streaming
    # ------------------------------------------------------------------

    def chat_stream(
        self,
        messages: list[LLMMessage],
        temperature: float | None = None,
        max_tokens: int | None = None,
    ) -> Generator[str, None, None]:
        """Stream chat completion tokens. Yields content chunks.

        Note: unlike :meth:`chat`, the streaming path yields only visible
        ``content`` deltas — a reasoning model's chain of thought is consumed
        silently and there is no empty-response retry (a stream cannot be
        replayed mid-flight). The default ``max_tokens`` leaves room for both
        reasoning and answer; if you stream a reasoning model with a very small
        ``max_tokens`` the answer may not fit and the stream can end empty.
        """
        cfg = self._current_config()
        provider = cfg.provider.lower()

        if provider == "ollama":
            try:
                from flinttrade_core.ollama_runtime import managed_ollama_session

                with managed_ollama_session(cfg.model) as admission:
                    managed_ollama_base_url = _normalise_managed_ollama_base_url(admission.base_url)
                    if not managed_ollama_base_url:
                        raise ValueError("managed Ollama endpoint is invalid")
                    buffered: list[str] = []
                    buffered_bytes = 0
                    byte_limit = min(16 * 1024 * 1024, max(1, max_tokens or cfg.max_tokens) * 32)
                    for chunk in self._stream_openai_compat(
                        cfg,
                        messages,
                        temperature,
                        max_tokens,
                        model=admission.model,
                        managed_ollama_base_url=managed_ollama_base_url,
                    ):
                        buffered_bytes += len(chunk.encode("utf-8"))
                        if buffered_bytes > byte_limit:
                            raise ValueError("managed Ollama stream exceeded its response budget")
                        buffered.append(chunk)
            except Exception as exc:  # noqa: BLE001 - admission failures are bounded and fail closed
                logger.warning(
                    "Managed Ollama stream refused (exception=%s)",
                    _bounded_exception_class(exc),
                )
                return
            yield from buffered
            return

        if provider == "anthropic":
            yield from self._stream_anthropic(cfg, messages, temperature, max_tokens)
        else:
            yield from self._stream_openai_compat(
                cfg,
                messages,
                temperature,
                max_tokens,
            )

    def _stream_openai_compat(
        self, cfg: LLMConfig, messages: list[LLMMessage],
        temperature: float | None, max_tokens: int | None,
        *,
        model: str | None = None,
        managed_ollama_base_url: str = "",
    ) -> Generator[str, None, None]:
        url = _request_endpoint(cfg, managed_ollama_base_url)
        headers = _openai_compat_headers(cfg)

        payload = {
            "model": model or cfg.model,
            "messages": [{"role": m.role, "content": m.content} for m in messages],
            "temperature": temperature or cfg.temperature,
            "max_tokens": max_tokens or cfg.max_tokens,
            "stream": True,
        }

        try:
            with self._http.stream(
                "POST",
                url,
                managed_ollama=cfg.provider.strip().lower() == "ollama",
                json=payload,
                headers=headers,
            ) as resp:
                if isinstance(resp.status_code, int) and resp.status_code >= 400:
                    return
                for line in resp.iter_lines():
                    if not line or line.startswith(":"):
                        continue
                    if line.startswith("data: "):
                        data_str = line[6:]
                        if data_str.strip() == "[DONE]":
                            break
                        try:
                            chunk = json.loads(data_str)
                            delta = chunk.get("choices", [{}])[0].get("delta", {})
                            text = delta.get("content", "")
                            if text:
                                yield text
                        except json.JSONDecodeError:
                            continue
        except Exception as exc:
            # Log the exception type only — never the request (which carries the
            # Authorization/x-api-key header) nor the token.
            logger.error(
                "Streaming request failed (provider=%s, exception=%s)",
                _bounded_log_label(cfg.provider),
                _bounded_exception_class(exc),
            )

    def _stream_anthropic(
        self, cfg: LLMConfig, messages: list[LLMMessage],
        temperature: float | None, max_tokens: int | None,
    ) -> Generator[str, None, None]:
        url = "https://api.anthropic.com/v1/messages"
        headers = _anthropic_headers(cfg.api_key)
        system = ""
        api_messages = []
        for m in messages:
            if m.role == "system":
                system = m.content
            else:
                api_messages.append({"role": m.role, "content": m.content})

        payload: dict[str, Any] = {
            "model": cfg.model,
            "messages": api_messages,
            "max_tokens": max_tokens or cfg.max_tokens,
            "temperature": temperature or cfg.temperature,
            "stream": True,
        }
        if system:
            payload["system"] = system

        try:
            with self._http.stream("POST", url, json=payload, headers=headers) as resp:
                for line in resp.iter_lines():
                    if not line or line.startswith(":"):
                        continue
                    if line.startswith("data: "):
                        try:
                            event = json.loads(line[6:])
                            if event.get("type") == "content_block_delta":
                                text = event.get("delta", {}).get("text", "")
                                if text:
                                    yield text
                        except json.JSONDecodeError:
                            continue
        except Exception as exc:
            # Log the exception type only — never the request (which carries the
            # Bearer/x-api-key auth header) nor the token itself.
            logger.error("Anthropic streaming request failed (exception=%s)", _bounded_exception_class(exc))

    # ------------------------------------------------------------------
    # Token management
    # ------------------------------------------------------------------

    def fits_context(self, messages: list[LLMMessage], reserve: int = 1000) -> bool:
        """Check if messages fit within the context window."""
        total = sum(estimate_tokens(m.content) for m in messages)
        return total + reserve <= self._current_config().context_length

    def trim_to_fit(
        self, messages: list[LLMMessage], reserve: int = 1000,
    ) -> list[LLMMessage]:
        """Trim older messages to fit context window. Keeps system + last N."""
        config = self._current_config()
        total = sum(estimate_tokens(message.content) for message in messages)
        if total + reserve <= config.context_length:
            return messages

        system = [m for m in messages if m.role == "system"]
        non_system = [m for m in messages if m.role != "system"]

        budget = config.context_length - reserve
        for m in system:
            budget -= estimate_tokens(m.content)

        trimmed = []
        for m in reversed(non_system):
            tokens = estimate_tokens(m.content)
            if tokens <= budget:
                trimmed.insert(0, m)
                budget -= tokens
            else:
                break

        return system + trimmed
