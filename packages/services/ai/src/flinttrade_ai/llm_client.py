"""Unified LLM client supporting multiple providers via OpenAI-compatible API.

Providers:
- LM Studio (local, http://127.0.0.1:1234)
- Ollama (local, http://127.0.0.1:11434)
- Anthropic Claude (cloud)
- OpenAI (cloud)

Provider selection from .env: LLM_PROVIDER, LLM_HOST, LLM_MODEL.
Retry with fallback: primary fails → fallback provider.
"""

from __future__ import annotations

import json
import logging
import os
from dataclasses import dataclass
from enum import StrEnum
from typing import Any, Generator

import httpx

logger = logging.getLogger("flinttrade.ai.llm")


class LLMProvider(StrEnum):
    """Supported LLM providers.

    Local: LM Studio, Ollama (user's hardware, no internet needed)
    Cloud: Any provider with an API (user brings their own key)
    Custom: Any OpenAI-compatible endpoint (user provides host URL)
    """

    LMSTUDIO = "lmstudio"
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
    OPENROUTER = "openrouter"  # Routes to 100+ models
    HERMES = "hermes"    # Nous Hermes function-calling agent models (OpenAI-compatible host)
    CUSTOM = "custom"    # Any OpenAI-compatible endpoint


@dataclass
class LLMConfig:
    """LLM provider configuration."""

    provider: str = ""
    host: str = ""
    model: str = ""
    api_key: str = ""
    context_length: int = 32768
    temperature: float = 0.7
    max_tokens: int = 4096

    @classmethod
    def from_env(cls) -> LLMConfig:
        """Load LLM config from workspace.json, with env var overrides."""
        provider = os.getenv("LLM_PROVIDER", "")
        host = os.getenv("LLM_HOST", "")
        model = os.getenv("LLM_MODEL", "")

        # Fall back to workspace config if env vars are not set
        if not provider or not host:
            try:
                from flinttrade_core.workspace import Workspace
                ws = Workspace()
                provider = provider or ws.get("llm.provider", "") or ""
                host = host or ws.get("llm.host", "") or "http://127.0.0.1:1234"
                model = model or ws.get("llm.model", "") or ""
            except Exception:
                host = host or "http://127.0.0.1:1234"

        return cls(
            provider=provider,
            host=host,
            model=model,
            api_key=(
                os.getenv("LLM_API_KEY", "")  # Generic — works for any provider
                or os.getenv("OPENAI_API_KEY", "")
                or os.getenv("ANTHROPIC_API_KEY", "")
                or os.getenv("GEMINI_API_KEY", "")
                or os.getenv("DEEPSEEK_API_KEY", "")
                or os.getenv("GROQ_API_KEY", "")
                or os.getenv("GROK_API_KEY", "")
                or os.getenv("MISTRAL_API_KEY", "")
                or os.getenv("TOGETHER_API_KEY", "")
                or os.getenv("NVIDIA_API_KEY", "")
                or os.getenv("OPENROUTER_API_KEY", "")
            ),
            context_length=int(os.getenv("LLM_CONTEXT_LENGTH", "32768")),
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
    "lmstudio": "{host}/v1/chat/completions",
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
    "openrouter": "https://openrouter.ai/api/v1/chat/completions",
    # Hermes — Nous Hermes function-calling/agent models, served OpenAI-compatibly
    # (local Ollama `hermes3`, a self-hosted vLLM, or any Hermes API host).
    "hermes": "{host}/v1/chat/completions",
    # Custom (any OpenAI-compatible endpoint)
    "custom": "{host}/v1/chat/completions",
}


def resolve_endpoint(provider: str, host: str) -> str:
    """Resolve the OpenAI-compatible chat endpoint for a provider.

    Local providers (Ollama → ``:11434``, LM Studio → ``:1234``, Hermes, custom)
    interpolate the runtime ``host``; cloud providers return their fixed URL. An
    unknown provider falls back to a generic ``{host}/v1/chat/completions`` so any
    OpenAI-compatible endpoint still works. This is the single resolution point
    used by both the blocking and streaming request paths.
    """
    template = _PROVIDER_URLS.get((provider or "").lower(), "{host}/v1/chat/completions")
    return template.format(host=(host or "").rstrip("/"))


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
    ) -> None:
        self.config = config or LLMConfig.from_env()
        self.fallback_config = fallback_config
        self._http = httpx.Client(timeout=120.0)

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
    ) -> LLMResponse:
        """Send a chat completion request. Falls back to secondary on failure."""
        resp = self._chat_with_config(
            self.config, messages, temperature, max_tokens, model,
        )
        if resp.success:
            return resp

        if self.fallback_config:
            logger.warning(
                "Primary LLM failed (%s), trying fallback (%s): %s",
                self.config.provider, self.fallback_config.provider, resp.error,
            )
            return self._chat_with_config(
                self.fallback_config, messages, temperature, max_tokens, model,
            )

        return resp

    def _chat_with_config(
        self,
        cfg: LLMConfig,
        messages: list[LLMMessage],
        temperature: float | None,
        max_tokens: int | None,
        model: str | None,
    ) -> LLMResponse:
        """Execute chat completion against a specific provider config."""
        provider = cfg.provider.lower()
        use_model = model or cfg.model
        use_temp = temperature if temperature is not None else cfg.temperature
        use_max = max_tokens or cfg.max_tokens

        if provider == "anthropic":
            return self._chat_anthropic(cfg, messages, use_model, use_temp, use_max)

        return self._chat_openai_compat(cfg, messages, use_model, use_temp, use_max)

    def _chat_openai_compat(
        self,
        cfg: LLMConfig,
        messages: list[LLMMessage],
        model: str,
        temperature: float,
        max_tokens: int,
    ) -> LLMResponse:
        """OpenAI-compatible endpoint (LM Studio, Ollama, OpenAI)."""
        url = resolve_endpoint(cfg.provider, cfg.host)

        headers: dict[str, str] = {"Content-Type": "application/json"}
        if cfg.api_key:
            headers["Authorization"] = f"Bearer {cfg.api_key}"

        payload = {
            "model": model,
            "messages": [{"role": m.role, "content": m.content} for m in messages],
            "temperature": temperature,
            "max_tokens": max_tokens,
            "stream": False,
        }

        try:
            resp = self._http.post(url, json=payload, headers=headers)
            if resp.status_code >= 400:
                return LLMResponse(
                    provider=cfg.provider, model=model,
                    error=f"HTTP {resp.status_code}: {resp.text[:200]}",
                )
            data = resp.json()
            choice = data.get("choices", [{}])[0]
            usage = data.get("usage", {})
            return LLMResponse(
                content=choice.get("message", {}).get("content", ""),
                model=data.get("model", model),
                provider=cfg.provider,
                prompt_tokens=usage.get("prompt_tokens", 0),
                completion_tokens=usage.get("completion_tokens", 0),
                total_tokens=usage.get("total_tokens", 0),
                finish_reason=choice.get("finish_reason", ""),
            )
        except Exception as exc:
            return LLMResponse(provider=cfg.provider, model=model, error=str(exc))

    def _chat_anthropic(
        self,
        cfg: LLMConfig,
        messages: list[LLMMessage],
        model: str,
        temperature: float,
        max_tokens: int,
    ) -> LLMResponse:
        """Anthropic Messages API."""
        url = "https://api.anthropic.com/v1/messages"
        headers = {
            "Content-Type": "application/json",
            "x-api-key": cfg.api_key,
            "anthropic-version": "2023-06-01",
        }

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
                    error=f"HTTP {resp.status_code}: {resp.text[:200]}",
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
            return LLMResponse(provider="anthropic", model=model, error=str(exc))

    # ------------------------------------------------------------------
    # Streaming
    # ------------------------------------------------------------------

    def chat_stream(
        self,
        messages: list[LLMMessage],
        temperature: float | None = None,
        max_tokens: int | None = None,
    ) -> Generator[str, None, None]:
        """Stream chat completion tokens. Yields content chunks."""
        cfg = self.config
        provider = cfg.provider.lower()

        if provider == "anthropic":
            yield from self._stream_anthropic(cfg, messages, temperature, max_tokens)
        else:
            yield from self._stream_openai_compat(cfg, messages, temperature, max_tokens)

    def _stream_openai_compat(
        self, cfg: LLMConfig, messages: list[LLMMessage],
        temperature: float | None, max_tokens: int | None,
    ) -> Generator[str, None, None]:
        url = resolve_endpoint(cfg.provider, cfg.host)
        headers: dict[str, str] = {"Content-Type": "application/json"}
        if cfg.api_key:
            headers["Authorization"] = f"Bearer {cfg.api_key}"

        payload = {
            "model": cfg.model,
            "messages": [{"role": m.role, "content": m.content} for m in messages],
            "temperature": temperature or cfg.temperature,
            "max_tokens": max_tokens or cfg.max_tokens,
            "stream": True,
        }

        try:
            with self._http.stream("POST", url, json=payload, headers=headers) as resp:
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
            logger.error("Streaming error: %s", exc)

    def _stream_anthropic(
        self, cfg: LLMConfig, messages: list[LLMMessage],
        temperature: float | None, max_tokens: int | None,
    ) -> Generator[str, None, None]:
        url = "https://api.anthropic.com/v1/messages"
        headers = {
            "Content-Type": "application/json",
            "x-api-key": cfg.api_key,
            "anthropic-version": "2023-06-01",
        }
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
            logger.error("Anthropic streaming error: %s", exc)

    # ------------------------------------------------------------------
    # Token management
    # ------------------------------------------------------------------

    def fits_context(self, messages: list[LLMMessage], reserve: int = 1000) -> bool:
        """Check if messages fit within the context window."""
        total = sum(estimate_tokens(m.content) for m in messages)
        return total + reserve <= self.config.context_length

    def trim_to_fit(
        self, messages: list[LLMMessage], reserve: int = 1000,
    ) -> list[LLMMessage]:
        """Trim older messages to fit context window. Keeps system + last N."""
        if self.fits_context(messages, reserve):
            return messages

        system = [m for m in messages if m.role == "system"]
        non_system = [m for m in messages if m.role != "system"]

        budget = self.config.context_length - reserve
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
