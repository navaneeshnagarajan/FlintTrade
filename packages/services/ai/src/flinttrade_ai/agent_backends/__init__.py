"""Agent-backend streaming core for FlintTrade.

A Hermes-mirrored 4-layer stack that catalogues, detects, and streams over the
six supported AI backends (three LLM providers + three agent runtimes),
replacing the removed OpenClaw external-gateway bridge:

1. :mod:`~flinttrade_ai.agent_backends.profiles` — the declarative
   :class:`AgentBackendProfile` catalogue.
2. :mod:`~flinttrade_ai.agent_backends.registry` — register/get/list +
   :func:`detect_backend` (installed / not_installed / needs_config / ready)
   and :func:`get_session`.
3. :mod:`~flinttrade_ai.agent_backends.session` — the :class:`AgentSession`
   ABC, the typed :class:`AgentEvent` streaming unit, and the
   :class:`AgentBackendUnavailable` fail-closed signal.
4. :mod:`~flinttrade_ai.agent_backends.codex_session` — the full streaming
   :class:`CodexAppServerSession` over the codex app-server JSON-RPC protocol.
"""

from __future__ import annotations

from flinttrade_ai.agent_backends.antigravity_session import AntigravitySession
from flinttrade_ai.agent_backends.codex_session import (
    CodexAppServerError,
    CodexAppServerSession,
    project_codex_notification,
)
from flinttrade_ai.agent_backends.hermes_session import HermesACPSession
from flinttrade_ai.agent_backends.profiles import (
    AGENT_BACKEND_CATALOGUE,
    CATALOGUE_BY_ID,
    CATALOGUE_IDS,
    AgentAuthMode,
    AgentBackendKind,
    AgentBackendProfile,
)
from flinttrade_ai.agent_backends.registry import (
    BackendStatus,
    backend_ids,
    detect_backend,
    get_backend,
    get_session,
    list_backends,
    register_backend,
)
from flinttrade_ai.agent_backends.session import (
    AgentBackendUnavailable,
    AgentEvent,
    AgentEventKind,
    AgentSession,
    EventCallback,
)

__all__ = [
    # profiles
    "AgentBackendProfile",
    "AgentBackendKind",
    "AgentAuthMode",
    "AGENT_BACKEND_CATALOGUE",
    "CATALOGUE_BY_ID",
    "CATALOGUE_IDS",
    # registry
    "BackendStatus",
    "register_backend",
    "get_backend",
    "list_backends",
    "backend_ids",
    "detect_backend",
    "get_session",
    # session contract
    "AgentSession",
    "AgentEvent",
    "AgentEventKind",
    "EventCallback",
    "AgentBackendUnavailable",
    # codex
    "CodexAppServerSession",
    "CodexAppServerError",
    "project_codex_notification",
    # hermes (ACP) + antigravity (CLI) streaming runtimes
    "HermesACPSession",
    "AntigravitySession",
]
