"""Unified LLM client supporting multiple providers via OpenAI-compatible API.

Providers:
- LM Studio (local, http://127.0.0.1:1234)
- Ollama (local, http://127.0.0.1:11434)
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
    api_key: str = ""
    context_length: int = 32768
    temperature: float = 0.7
    max_tokens: int = 4096
    # Budget used to retry a reasoning model whose chain of thought consumed the
    # whole ``max_tokens`` budget, leaving an empty visible answer. See
    # ``LLMClient._chat_openai_compat``. Set to 0 to disable the retry.
    reasoning_max_tokens: int = 8192

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

        workspace_api_key = ""
        try:
            from flinttrade_core.llm_config import resolve_llm_api_key

            workspace_api_key = resolve_llm_api_key()
        except Exception:
            workspace_api_key = ""

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
                or os.getenv("CEREBRAS_API_KEY", "")
                or os.getenv("OPENROUTER_API_KEY", "")
                or workspace_api_key
            ),
            context_length=int(os.getenv("LLM_CONTEXT_LENGTH", "32768")),
            reasoning_max_tokens=int(os.getenv("LLM_REASONING_MAX_TOKENS", "8192")),
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
        resp = self._chat_with_config(
            self.config, messages, temperature, max_tokens, model, response_format,
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
        provider = cfg.provider.lower()
        use_model = model or cfg.model
        use_temp = temperature if temperature is not None else cfg.temperature
        use_max = max_tokens or cfg.max_tokens

        if provider == "anthropic":
            return self._chat_anthropic(cfg, messages, use_model, use_temp, use_max)

        return self._chat_openai_compat(
            cfg, messages, use_model, use_temp, use_max, response_format,
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
        allow_reasoning_retry: bool = True,
    ) -> LLMResponse:
        """OpenAI-compatible endpoint (LM Studio, Ollama, OpenAI).

        Reasoning models (Qwen3, DeepSeek-R1, …) emit the chain of thought in
        ``message.reasoning_content``, which counts against ``max_tokens``. With a
        modest budget the reasoning exhausts the cap and the visible ``content``
        comes back empty (``finish_reason == "length"``). When that happens we
        retry once with ``cfg.reasoning_max_tokens`` so callers still receive a
        real answer; non-reasoning models are never retried.
        """
        url = resolve_endpoint(cfg.provider, cfg.host)

        headers: dict[str, str] = {"Content-Type": "application/json"}
        api_key = (cfg.api_key or "").strip()
        if api_key:
            headers["Authorization"] = f"Bearer {api_key}"

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
            resp = self._http.post(url, json=payload, headers=headers)
            if resp.status_code >= 400:
                return LLMResponse(
                    provider=cfg.provider, model=model,
                    error=f"HTTP {resp.status_code}: {resp.text[:200]}",
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
                    response_format, allow_reasoning_retry=False,
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
        except Exception:
            logger.exception("OpenAI-compatible chat request failed for provider=%s model=%s", cfg.provider, model)
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
        except Exception:
            logger.exception("Anthropic chat request failed for model=%s", model)
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
        api_key = (cfg.api_key or "").strip()
        if api_key:
            headers["Authorization"] = f"Bearer {api_key}"

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
            # Log the exception type only — never the request (which carries the
            # Authorization/x-api-key header) nor the token.
            logger.error("Streaming request failed (provider=%s): %s", cfg.provider, type(exc).__name__)

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
            logger.error("Anthropic streaming request failed: %s", type(exc).__name__)

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
