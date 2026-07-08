"""Declarative catalogue of supported agent backends.

Layer 1 of the agent-backend stack. An :class:`AgentBackendProfile` is a
pure, frozen description of one backend — how to recognise it (an LLM
provider config, or a CLI binary on ``PATH``), how to invoke it, and which
auth model it uses. The registry (layer 2) turns these descriptions into
detection + session-construction behaviour.

Six backends are catalogued, in two categories that mirror the AI-backends
design (see ``.local/specs/ai-backends/DESIGN_LOG.md``):

* **LLM providers** (``kind == "llm"``) — chat/completion backends driven by
  the existing ``LLMClient``. Detection is *configured-if provider + key set*:
  ``claude-code`` (Anthropic API key), ``claude-code-oauth`` (Anthropic OAuth
  token), and ``cerebras``.
* **Agent runtimes** — subprocess/entrypoint agents detected by whether their
  CLI is on ``PATH``: ``codex`` (``cli_agent``), ``antigravity``
  (``cli_agent``), and ``hermes`` (``acp_agent``).
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import Any


class AgentBackendKind(StrEnum):
    """The three backend categories.

    * ``llm`` — an OpenAI/Anthropic-compatible chat provider driven through
      ``LLMClient``; no subprocess of its own.
    * ``cli_agent`` — a stand-alone agent CLI spawned as a subprocess.
    * ``acp_agent`` — an agent bridged over its ACP stdio entrypoint.
    """

    LLM = "llm"
    CLI_AGENT = "cli_agent"
    ACP_AGENT = "acp_agent"


class AgentAuthMode(StrEnum):
    """How a backend authenticates.

    * ``api_key`` — an operator-supplied API key (file-backed LLM secret).
    * ``oauth`` — an operator-supplied OAuth token (Bearer; e.g. Claude Code
      credits). Never harvested — the operator pastes it into the vault.
    * ``cli_managed`` — the CLI/entrypoint owns its own login (``codex
      login``, ``agy``'s own flow, Hermes' own auth); FlintTrade never touches
      those credentials.
    * ``none`` — no auth required.
    """

    API_KEY = "api_key"
    OAUTH = "oauth"
    CLI_MANAGED = "cli_managed"
    NONE = "none"


@dataclass(frozen=True)
class AgentBackendProfile:
    """A declarative description of one agent backend.

    Attributes:
        id: Stable catalogue identifier (e.g. ``"codex"``).
        display_name: Human-readable, British-English label for the UI.
        kind: The :class:`AgentBackendKind` category.
        auth_mode: The :class:`AgentAuthMode` this backend uses.
        description: Short British-English summary shown in the backends UI.
        llm_provider: For ``kind == llm`` only — the ``LLMProvider`` value
            whose configured provider + key gates readiness. ``None`` for
            agent runtimes.
        detect_binaries: For agent runtimes — candidate binary names probed
            on ``PATH`` (first found wins). Empty for LLM backends.
        invocation: For agent runtimes — the full argv used to launch a
            streaming session (e.g. ``("codex", "app-server")``).
        version_args: For agent runtimes — args appended to the binary to
            read its version during detection (never runs a task).
    """

    id: str
    display_name: str
    kind: AgentBackendKind
    auth_mode: AgentAuthMode
    description: str = ""
    llm_provider: str | None = None
    detect_binaries: tuple[str, ...] = ()
    invocation: tuple[str, ...] = ()
    version_args: tuple[str, ...] = ("--version",)

    @property
    def is_llm(self) -> bool:
        """Whether this is an LLM chat/completion backend."""
        return self.kind == AgentBackendKind.LLM

    @property
    def is_cli_agent(self) -> bool:
        """Whether this is a stand-alone CLI agent runtime."""
        return self.kind == AgentBackendKind.CLI_AGENT

    @property
    def is_acp_agent(self) -> bool:
        """Whether this is an ACP-bridged agent runtime."""
        return self.kind == AgentBackendKind.ACP_AGENT

    @property
    def requires_binary(self) -> bool:
        """Whether detection is by a CLI/entrypoint on ``PATH``."""
        return self.kind in (AgentBackendKind.CLI_AGENT, AgentBackendKind.ACP_AGENT)

    def to_dict(self) -> dict[str, Any]:
        """Return a JSON-friendly dict for the backends route/UI."""
        return {
            "id": self.id,
            "display_name": self.display_name,
            "kind": str(self.kind),
            "auth_mode": str(self.auth_mode),
            "description": self.description,
            "llm_provider": self.llm_provider,
            "detect_binaries": list(self.detect_binaries),
            "invocation": list(self.invocation),
            "requires_binary": self.requires_binary,
        }


# --- LLM providers (driven through LLMClient) -----------------------------

CLAUDE_CODE = AgentBackendProfile(
    id="claude-code",
    display_name="Claude Code (API key)",
    kind=AgentBackendKind.LLM,
    auth_mode=AgentAuthMode.API_KEY,
    description="Anthropic Claude via an operator-supplied API key (x-api-key).",
    llm_provider="anthropic",
)

CLAUDE_CODE_OAUTH = AgentBackendProfile(
    id="claude-code-oauth",
    display_name="Claude Code (OAuth + credits)",
    kind=AgentBackendKind.LLM,
    auth_mode=AgentAuthMode.OAUTH,
    description=(
        "Anthropic Claude via an operator-supplied OAuth token (Bearer). The "
        "same endpoint as the API-key backend; auth is chosen by token shape."
    ),
    llm_provider="anthropic",
)

CEREBRAS = AgentBackendProfile(
    id="cerebras",
    display_name="Cerebras",
    kind=AgentBackendKind.LLM,
    auth_mode=AgentAuthMode.API_KEY,
    description="Cerebras inference (OpenAI-compatible chat completions).",
    llm_provider="cerebras",
)

# --- Agent runtimes (subprocess / ACP entrypoints) ------------------------

CODEX = AgentBackendProfile(
    id="codex",
    display_name="Codex CLI",
    kind=AgentBackendKind.CLI_AGENT,
    auth_mode=AgentAuthMode.CLI_MANAGED,
    description="OpenAI Codex CLI app-server — newline-delimited JSON-RPC over stdio.",
    detect_binaries=("codex",),
    invocation=("codex", "app-server"),
)

ANTIGRAVITY = AgentBackendProfile(
    id="antigravity",
    display_name="Antigravity CLI",
    kind=AgentBackendKind.CLI_AGENT,
    auth_mode=AgentAuthMode.CLI_MANAGED,
    description="Google Antigravity 'agy' CLI agent, spawned as a subprocess.",
    detect_binaries=("agy",),
    invocation=("agy",),
)

HERMES = AgentBackendProfile(
    id="hermes",
    display_name="Hermes Agent (ACP)",
    kind=AgentBackendKind.ACP_AGENT,
    auth_mode=AgentAuthMode.CLI_MANAGED,
    description="Nous Hermes agent bridged over its ACP stdio entrypoint.",
    detect_binaries=("hermes", "hermes-acp"),
    invocation=("hermes", "acp"),
)


# Ordered catalogue of every supported backend. The registry seeds itself
# from this tuple; ``list_backends`` preserves this order.
AGENT_BACKEND_CATALOGUE: tuple[AgentBackendProfile, ...] = (
    CLAUDE_CODE,
    CLAUDE_CODE_OAUTH,
    CEREBRAS,
    CODEX,
    ANTIGRAVITY,
    HERMES,
)

# Convenience id → profile map over the catalogue (registry is the mutable one).
CATALOGUE_BY_ID: dict[str, AgentBackendProfile] = {p.id: p for p in AGENT_BACKEND_CATALOGUE}

# The canonical list of catalogue ids, in declaration order.
CATALOGUE_IDS: tuple[str, ...] = tuple(p.id for p in AGENT_BACKEND_CATALOGUE)
