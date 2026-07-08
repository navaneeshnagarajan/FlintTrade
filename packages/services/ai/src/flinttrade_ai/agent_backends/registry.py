"""Registry and detection for agent backends.

Layer 2 of the agent-backend stack. It owns the mutable registry seeded from
the declarative catalogue (:mod:`flinttrade_ai.agent_backends.profiles`) and
provides:

* ``register_backend`` / ``get_backend`` / ``list_backends`` — CRUD over the
  registry.
* ``detect_backend`` — a fail-closed, honest status probe returning one of
  ``installed | not_installed | needs_config | ready``. For LLM backends it
  inspects the configured LLM provider + key; for CLI/ACP agents it checks
  whether the binary is on ``PATH`` (``which``) and, when present, whether
  ``<binary> --version`` responds — detection only, it never runs a task.
* ``get_session`` — construct a streaming :class:`AgentSession` for a backend
  id (Codex today; other runtimes land in a later phase).

Detection is dependency-light and fully injectable so it can be unit-tested
without any backend actually installed.
"""

from __future__ import annotations

import shutil
import subprocess
from collections.abc import Callable, Sequence
from enum import StrEnum
from typing import Any

from flinttrade_ai.agent_backends.profiles import (
    AGENT_BACKEND_CATALOGUE,
    AgentAuthMode,
    AgentBackendProfile,
)
from flinttrade_ai.agent_backends.session import AgentSession

# Injectable seams (kept as module-level types for readable signatures).
WhichFn = Callable[[str], str | None]
VersionProbeFn = Callable[[Sequence[str]], bool]

# How long a ``--version`` probe may take before we treat the binary as
# present-but-unverified. Detection must never block the caller for long.
_VERSION_PROBE_TIMEOUT = 10.0


class BackendStatus(StrEnum):
    """The outcome of :func:`detect_backend`.

    * ``not_installed`` — an agent runtime whose binary is not on ``PATH``.
    * ``needs_config`` — an LLM backend whose provider/key (or OAuth token
      shape) is not configured for this backend.
    * ``installed`` — an agent runtime binary is on ``PATH`` but its
      ``--version`` probe did not confirm it runs.
    * ``ready`` — configured/verified and usable.
    """

    NOT_INSTALLED = "not_installed"
    NEEDS_CONFIG = "needs_config"
    INSTALLED = "installed"
    READY = "ready"


# --- registry -------------------------------------------------------------

_REGISTRY: dict[str, AgentBackendProfile] = {}


def _seed_registry() -> None:
    """Seed the registry from the catalogue (idempotent, order-preserving)."""
    for profile in AGENT_BACKEND_CATALOGUE:
        _REGISTRY.setdefault(profile.id, profile)


_seed_registry()


def register_backend(profile: AgentBackendProfile) -> None:
    """Register (or override) a backend profile by its id.

    Args:
        profile: The profile to store. Re-registering an existing id keeps
            its position in the registry order.
    """
    _REGISTRY[profile.id] = profile


def get_backend(backend_id: str) -> AgentBackendProfile:
    """Return the profile for ``backend_id``.

    Args:
        backend_id: The catalogue id to look up.

    Returns:
        The matching :class:`AgentBackendProfile`.

    Raises:
        KeyError: if no backend with that id is registered.
    """
    try:
        return _REGISTRY[backend_id]
    except KeyError as exc:
        known = ", ".join(sorted(_REGISTRY))
        raise KeyError(f"unknown agent backend {backend_id!r}; known: {known}") from exc


def list_backends() -> list[AgentBackendProfile]:
    """Return all registered backend profiles in registry order."""
    return list(_REGISTRY.values())


def backend_ids() -> list[str]:
    """Return the ids of all registered backends in registry order."""
    return list(_REGISTRY)


# --- detection ------------------------------------------------------------


def _looks_like_oauth_token(token: str) -> bool:
    """Return ``True`` if ``token`` looks like an Anthropic OAuth/credits token.

    Mirrors Hermes' ``anthropic_adapter._is_oauth_token``: a token that is
    ``sk-ant-`` (but *not* the standard ``sk-ant-api`` API key), a ``eyJ…``
    JWT, or a ``cc-…`` Claude Code token is treated as OAuth (Bearer auth).
    """
    candidate = (token or "").strip()
    if not candidate:
        return False
    if candidate.startswith("sk-ant-api"):
        return False
    if candidate.startswith("sk-ant-"):
        return True
    if candidate.startswith("cc-"):
        return True
    if candidate.startswith("eyJ"):
        return True
    return False


def _resolve_llm_config() -> Any | None:
    """Return the live ``LLMConfig`` (provider + api_key), or ``None``.

    Imported lazily so the registry has no import-time dependency on the LLM
    client, and so a broken/absent workspace never raises during detection.
    """
    try:
        from flinttrade_ai.llm_client import LLMConfig

        return LLMConfig.from_env()
    except Exception:
        return None


def _detect_llm(profile: AgentBackendProfile, config: Any | None) -> BackendStatus:
    """Detect an LLM backend by its configured provider + key.

    Ready iff the active LLM provider matches the profile's provider and a
    key is present. For the Anthropic pair, the token *shape* additionally
    selects between the API-key and OAuth backends.
    """
    cfg = config if config is not None else _resolve_llm_config()
    if cfg is None:
        return BackendStatus.NEEDS_CONFIG

    provider = str(getattr(cfg, "provider", "") or "").lower()
    api_key = str(getattr(cfg, "api_key", "") or "")
    expected = str(profile.llm_provider or "").lower()

    if not provider or provider != expected:
        return BackendStatus.NEEDS_CONFIG
    if not api_key:
        return BackendStatus.NEEDS_CONFIG

    # The two Anthropic backends share an endpoint; the token shape decides
    # which one the current config actually satisfies.
    if profile.llm_provider == "anthropic":
        is_oauth = _looks_like_oauth_token(api_key)
        if profile.auth_mode == AgentAuthMode.OAUTH and not is_oauth:
            return BackendStatus.NEEDS_CONFIG
        if profile.auth_mode == AgentAuthMode.API_KEY and is_oauth:
            return BackendStatus.NEEDS_CONFIG

    return BackendStatus.READY


def _default_version_probe(cmd: Sequence[str]) -> bool:
    """Run ``<binary> --version`` and return whether it exited cleanly.

    Detection only — this never runs an agent task. Any spawn failure or a
    non-zero exit is treated as "present but unverified".
    """
    try:
        proc = subprocess.run(
            list(cmd),
            capture_output=True,
            text=True,
            timeout=_VERSION_PROBE_TIMEOUT,
            stdin=subprocess.DEVNULL,
        )
    except (FileNotFoundError, OSError, subprocess.SubprocessError):
        return False
    return proc.returncode == 0


def _detect_binary(
    profile: AgentBackendProfile,
    which: WhichFn,
    version_probe: VersionProbeFn | None,
) -> BackendStatus:
    """Detect an agent runtime by its binary on ``PATH``.

    ``not_installed`` when no candidate binary resolves; ``ready`` when the
    resolved binary's ``--version`` probe succeeds; ``installed`` when the
    binary is present but the probe could not confirm it runs.
    """
    resolved: str | None = None
    for candidate in profile.detect_binaries:
        if which(candidate):
            resolved = candidate
            break
    if resolved is None:
        return BackendStatus.NOT_INSTALLED

    probe = version_probe if version_probe is not None else _default_version_probe
    try:
        ok = probe((resolved, *profile.version_args))
    except Exception:
        ok = False
    return BackendStatus.READY if ok else BackendStatus.INSTALLED


def detect_backend(
    backend_id: str,
    *,
    which: WhichFn = shutil.which,
    version_probe: VersionProbeFn | None = None,
    llm_config: Any | None = None,
) -> BackendStatus:
    """Return the :class:`BackendStatus` for ``backend_id``.

    Args:
        backend_id: The catalogue id to probe.
        which: ``PATH`` lookup used for agent-runtime detection (injectable
            for tests). Defaults to :func:`shutil.which`.
        version_probe: Callable that runs ``<binary> --version`` and returns
            whether it succeeded (injectable for tests). Defaults to a short
            subprocess probe.
        llm_config: An ``LLMConfig``-like object for LLM detection
            (injectable for tests). Defaults to the live config.

    Returns:
        The detected status. LLM backends never return ``not_installed``;
        agent runtimes never return ``needs_config``.

    Raises:
        KeyError: if ``backend_id`` is unknown.
    """
    profile = get_backend(backend_id)
    if profile.is_llm:
        return _detect_llm(profile, llm_config)
    return _detect_binary(profile, which, version_probe)


# --- session construction -------------------------------------------------


def get_session(backend_id: str, **kwargs: Any) -> AgentSession:
    """Construct a streaming :class:`AgentSession` for ``backend_id``.

    Args:
        backend_id: The catalogue id to build a session for.
        **kwargs: Forwarded to the concrete session constructor (e.g. ``cwd``,
            ``codex_bin``, ``codex_home`` for Codex).

    Returns:
        A concrete :class:`AgentSession`.

    Raises:
        KeyError: if ``backend_id`` is unknown.
        ValueError: if ``backend_id`` is an LLM backend (drive those through
            ``LLMClient``, not a streaming session).
        NotImplementedError: if the backend is an agent runtime whose
            streaming session is not implemented yet.
    """
    profile = get_backend(backend_id)
    if profile.is_llm:
        raise ValueError(
            f"backend {backend_id!r} is an LLM backend; drive it through LLMClient, "
            f"not an AgentSession"
        )
    if backend_id == "codex":
        from flinttrade_ai.agent_backends.codex_session import CodexAppServerSession

        return CodexAppServerSession(**kwargs)
    raise NotImplementedError(
        f"streaming AgentSession for backend {backend_id!r} is not implemented yet"
    )
