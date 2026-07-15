"""Workspace-backed LLM configuration and local secret storage."""

from __future__ import annotations

import copy
import hashlib
import json
import os
import unicodedata
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass, field as dataclass_field
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit, urlunsplit

from .owner_file_lock import OwnerSafeFileLock, UnsafeFileLockPathError
from .secure_file import (
    cleanup_pending_unlink,
    durable_replace,
    durable_unlink,
    read_owner_owned_bytes,
    read_owner_owned_text,
    write_secret_text,
)
from .workspace import Workspace

LLM_API_KEY_REF = "secret://llm/api_key"
OLLAMA_BASE_URL = ""
_LEGACY_OLLAMA_BASE_URL = "http://127.0.0.1:11434"
_LMSTUDIO_RETIRED_ERROR = "LM Studio is retired; use managed Ollama or the Custom provider"
_LLM_TRANSACTION_VERSION = 1
_LLM_TRANSACTION_PHASES = {"prepared", "committed"}
_LLM_TRANSACTION_OPERATIONS = {"replace", "delete"}
_LLM_TRANSACTION_JOURNAL = ".llm_api_key.transaction.json"
_LLM_TRANSACTION_NEW = ".llm_api_key.transaction.new"
_LLM_TRANSACTION_OLD = ".llm_api_key.transaction.old"
_LLM_TRANSITION_LOCK = ".llm-config-transition.lock"
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


def reject_retired_llm_provider(provider: Any) -> None:
    """Reject a legacy provider before any runtime transition can begin."""
    if str(provider or "").strip().lower() == "lmstudio":
        raise ValueError(_LMSTUDIO_RETIRED_ERROR)


class LLMConfigConflictError(RuntimeError):
    """The LLM config or credential changed after a transition snapshot."""


@dataclass(frozen=True)
class LLMConfigSnapshot:
    """One coherent, unredacted workspace LLM config and credential snapshot."""

    provider: str
    host: str
    model: str
    api_key: str = dataclass_field(repr=False)
    revision: str

    def redacted(self) -> dict[str, Any]:
        return {
            "provider": self.provider,
            "host": self.host,
            "model": self.model,
            "api_key_configured": bool(self.api_key),
            "api_key_last4": self.api_key[-4:] if self.api_key else "",
        }

    def stored(self) -> dict[str, str]:
        return {
            "provider": self.provider,
            "host": self.host,
            "model": self.model,
            "api_key": self.api_key,
        }


class LLMConfigTransition:
    """Persist against a snapshot while the shared transition lock is held."""

    def __init__(self, workspace: Workspace, snapshot: LLMConfigSnapshot) -> None:
        self._workspace = workspace
        self.snapshot = snapshot

    @property
    def effective(self) -> dict[str, Any]:
        return _effective_llm_config(self.snapshot.stored())

    def persist(self, payload: dict[str, Any]) -> dict[str, Any]:
        self.snapshot = _persist_llm_config_snapshot(
            payload,
            self._workspace,
            expected_revision=self.snapshot.revision,
        )
        return self.snapshot.redacted()

    def refresh(self) -> LLMConfigSnapshot:
        """Read a fresh coherent snapshot while the transition lock remains held."""
        with _llm_transaction_lock(self._workspace):
            _load_or_initialise_workspace_locked(self._workspace)
            _recover_llm_config_transaction_locked(self._workspace)
            self.snapshot = _snapshot_from_loaded_workspace(self._workspace)
        return self.snapshot

    def refresh_effective(self) -> dict[str, Any]:
        """Resolve environment overrides against a fresh locked snapshot."""
        return _effective_llm_config(self.refresh().stored())


_PROVIDER_TRUST_DESTINATIONS = {
    "anthropic": "https://api.anthropic.com",
    "cerebras": "https://api.cerebras.ai",
    "deepseek": "https://api.deepseek.com",
    "gemini": "https://generativelanguage.googleapis.com",
    "grok": "https://api.x.ai",
    "groq": "https://api.groq.com",
    "mistral": "https://api.mistral.ai",
    "nvidia": "https://integrate.api.nvidia.com",
    "openai": "https://api.openai.com",
    "openrouter": "https://openrouter.ai",
    "together": "https://api.together.xyz",
}


def normalise_ollama_host(host: str) -> str:
    """Accept an empty or legacy host and return the logical managed endpoint."""
    value = (host or "").strip()
    if not value:
        return OLLAMA_BASE_URL
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
    return OLLAMA_BASE_URL


def _validate_configurable_api_base_url(provider: str, host: str) -> str:
    """Reject URL components that may disclose credentials through transport logs."""
    provider_name = (provider or "").strip().lower()
    value = (host or "").strip()
    if not provider_name or provider_name == "ollama" or provider_name in _PROVIDER_TRUST_DESTINATIONS:
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


def _normalise_api_key(value: object) -> str:
    raw = str(value or "")
    if any(unicodedata.category(character) == "Cc" for character in raw):
        raise ValueError("LLM API keys must not contain control characters")
    return raw.strip()


def _secret_path(ws: Workspace) -> Path:
    return ws.workspace_dir / "secrets" / "llm_api_key"


def _read_secret(path: Path) -> str:
    try:
        raw = read_owner_owned_text(path)
    except (FileNotFoundError, OSError, UnicodeDecodeError):
        return ""
    try:
        return _normalise_api_key(raw)
    except ValueError:
        return ""


def _normalise_destination(host: str) -> str:
    raw = (host or "").strip()
    try:
        parsed = urlsplit(raw)
        port = parsed.port
    except ValueError:
        return raw.rstrip("/")
    if not parsed.scheme or parsed.hostname is None:
        return raw.rstrip("/")

    scheme = parsed.scheme.lower()
    hostname = parsed.hostname.lower()
    if ":" in hostname:
        hostname = f"[{hostname}]"
    userinfo = parsed.netloc.rpartition("@")[0] + "@" if "@" in parsed.netloc else ""
    default_port = (scheme == "http" and port == 80) or (scheme == "https" and port == 443)
    netloc = f"{userinfo}{hostname}{f':{port}' if port is not None and not default_port else ''}"
    path = parsed.path.rstrip("/")
    return urlunsplit((scheme, netloc, path, parsed.query, parsed.fragment))


def _trust_destination(provider: str, host: str) -> str:
    provider_name = (provider or "").strip().lower()
    if provider_name == "ollama":
        return ""
    return _PROVIDER_TRUST_DESTINATIONS.get(provider_name, _normalise_destination(host))


def _resolve_bound_workspace_key(
    workspace: Workspace,
    llm: dict[str, Any],
    *,
    provider: str,
    host: str,
    secret_value: str | None = None,
) -> str:
    if str(llm.get("api_key_ref", "") or "") != LLM_API_KEY_REF:
        return ""
    provider_name = (provider or "").strip().lower()
    destination = _trust_destination(provider_name, host)
    if not provider_name or not destination:
        return ""
    key_provider = str(llm.get("api_key_provider", "") or "").strip().lower()
    key_destination = _normalise_destination(str(llm.get("api_key_destination", "") or ""))
    if key_provider != provider_name or key_destination != destination:
        return ""
    return _read_secret(_secret_path(workspace)) if secret_value is None else secret_value


def _read_secret_state(path: Path) -> tuple[str, str]:
    value = _read_secret(path)
    digest = hashlib.sha256(value.encode("utf-8")).hexdigest() if value else "empty"
    return value, digest


def _snapshot_revision(llm: dict[str, Any], secret_digest: str) -> str:
    payload = json.dumps(
        {"llm": llm, "secret_sha256": secret_digest},
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def _snapshot_from_loaded_workspace(workspace: Workspace) -> LLMConfigSnapshot:
    config = workspace.as_dict()
    llm = config.get("llm", {})
    if not isinstance(llm, dict):
        llm = {}
    provider = str(llm.get("provider", "") or "")
    host = str(llm.get("host", "") or "")
    secret_value, secret_digest = _read_secret_state(_secret_path(workspace))
    return LLMConfigSnapshot(
        provider=provider,
        host=host,
        model=str(llm.get("model", "") or ""),
        api_key=_resolve_bound_workspace_key(
            workspace,
            llm,
            provider=provider,
            host=host,
            secret_value=secret_value,
        ),
        revision=_snapshot_revision(llm, secret_digest),
    )


def _load_or_initialise_workspace_locked(workspace: Workspace) -> None:
    """Load or create the first workspace while the caller holds the LLM lock."""
    if workspace.config_path.exists():
        workspace.load()
        return
    workspace.update(lambda _config: None)


def _read_stored_llm_snapshot(workspace: Workspace) -> dict[str, str]:
    """Read config and its bound credential while holding one LLM lock."""
    with _llm_transaction_lock(workspace):
        _load_or_initialise_workspace_locked(workspace)
        _recover_llm_config_transaction_locked(workspace)
        return _snapshot_from_loaded_workspace(workspace).stored()


def resolve_llm_api_key(ws: Workspace | None = None) -> str:
    """Return the key bound to the workspace's current provider and destination."""
    workspace = ws or Workspace()
    return _read_stored_llm_snapshot(workspace)["api_key"]


def read_llm_config(ws: Workspace | None = None) -> dict[str, Any]:
    """Return the redacted LLM config stored in the workspace."""
    workspace = ws or Workspace()
    stored = _read_stored_llm_snapshot(workspace)
    api_key = stored["api_key"]
    return {
        "provider": stored["provider"],
        "host": stored["host"],
        "model": stored["model"],
        "api_key_configured": bool(api_key),
        "api_key_last4": api_key[-4:] if api_key else "",
    }


def read_effective_llm_config(ws: Workspace | None = None) -> dict[str, Any]:
    """Resolve one provider-scoped config for runtime and request clients."""
    workspace = ws or Workspace()
    return _effective_llm_config(_read_stored_llm_snapshot(workspace))


def _effective_llm_config(stored: dict[str, str]) -> dict[str, Any]:
    """Apply environment overrides to one already coherent stored snapshot."""
    stored_provider = str(stored.get("provider") or "").strip().lower()
    provider_override = os.getenv("LLM_PROVIDER", "").strip().lower()
    provider = provider_override or stored_provider or "ollama"

    host_override = os.getenv("LLM_HOST", "").strip()
    if host_override:
        host = host_override
    elif provider_override and provider_override != stored_provider:
        host = ""
    else:
        host = str(stored.get("host") or "").strip()
    model = os.getenv("LLM_MODEL", "").strip() or str(stored.get("model") or "")

    if provider == "lmstudio":
        raise ValueError(_LMSTUDIO_RETIRED_ERROR)
    if provider == "ollama":
        host = normalise_ollama_host(host)
    else:
        host = _validate_configurable_api_base_url(provider, host)

    api_key = ""
    if provider != "ollama":
        provider_key_name = _PROVIDER_API_KEY_ENV.get(provider, "")
        provider_key = _normalise_api_key(os.getenv(provider_key_name, "")) if provider_key_name else ""
        workspace_key = (
            stored["api_key"]
            if provider == stored_provider
            and _trust_destination(provider, host)
            == _trust_destination(stored_provider, str(stored.get("host") or ""))
            else ""
        )
        api_key = provider_key or workspace_key

    return {
        "provider": provider,
        "host": host,
        "model": model,
        "api_key": api_key,
    }


def resolve_llm_test_config(
    payload: dict[str, Any],
    *,
    effective: dict[str, Any],
) -> dict[str, str]:
    """Overlay an operator's connection-test draft without crossing secret trust boundaries."""
    if not isinstance(payload, dict):
        raise ValueError("LLM connection-test payload must be an object")

    for field in ("provider", "host", "model", "api_key"):
        if field in payload and not isinstance(payload[field], str):
            raise ValueError(f"{field} must be a string")

    effective_provider = str(effective.get("provider") or "").strip().lower()
    effective_host = str(effective.get("host") or "").strip()
    provider = str(payload.get("provider", effective_provider) or "").strip().lower()
    if not provider:
        provider = "ollama"
    if provider == "lmstudio":
        raise ValueError(_LMSTUDIO_RETIRED_ERROR)
    host = str(
        payload.get(
            "host",
            effective_host if provider == effective_provider else "",
        )
        or ""
    ).strip()
    model = str(payload.get("model", effective.get("model", "")) or "").strip()

    if provider == "ollama":
        host = normalise_ollama_host(host)
        api_key = ""
    else:
        host = _validate_configurable_api_base_url(provider, host)
        if "api_key" in payload:
            api_key = _normalise_api_key(payload.get("api_key", ""))
        else:
            same_destination = (
                provider == effective_provider
                and _trust_destination(provider, host)
                == _trust_destination(effective_provider, effective_host)
            )
            api_key = str(effective.get("api_key") or "") if same_destination else ""

    return {
        "provider": provider,
        "host": host,
        "model": model,
        "api_key": api_key,
    }


def _llm_section(config: dict[str, Any]) -> dict[str, Any]:
    llm = config.setdefault("llm", {})
    if not isinstance(llm, dict):
        llm = {}
        config["llm"] = llm
    return llm


def _clear_api_key_binding(llm: dict[str, Any]) -> None:
    llm["api_key_ref"] = ""
    llm["api_key_provider"] = ""
    llm["api_key_destination"] = ""


def _transaction_paths(secret_path: Path) -> tuple[Path, Path, Path, Path]:
    secret_dir = secret_path.parent
    journal_path = secret_dir / _LLM_TRANSACTION_JOURNAL
    return (
        journal_path,
        journal_path.with_name(f"{journal_path.name}.tmp"),
        secret_dir / _LLM_TRANSACTION_NEW,
        secret_dir / _LLM_TRANSACTION_OLD,
    )


@contextmanager
def _llm_transaction_lock(workspace: Workspace) -> Iterator[None]:
    workspace.workspace_dir.mkdir(parents=True, exist_ok=True)
    lock = OwnerSafeFileLock(workspace.workspace_dir / ".llm-config.lock", timeout=10, mode=0o600)
    try:
        with lock.acquire():
            yield
    except UnsafeFileLockPathError as exc:
        raise LLMConfigConflictError("LLM config lock path is unsafe") from exc


@contextmanager
def llm_config_transition_guard(
    ws: Workspace | None = None,
    *,
    timeout: float = 10.0,
) -> Iterator[None]:
    """Serialise runtime/config transitions across threads and processes."""
    if timeout < 0:
        raise ValueError("LLM config transition timeout must be non-negative")
    workspace = ws or Workspace()
    workspace.workspace_dir.mkdir(parents=True, exist_ok=True)
    lock = OwnerSafeFileLock(workspace.workspace_dir / _LLM_TRANSITION_LOCK, timeout=timeout, mode=0o600)
    try:
        with lock.acquire():
            yield
    except UnsafeFileLockPathError as exc:
        raise LLMConfigConflictError("LLM config transition lock path is unsafe") from exc


@contextmanager
def llm_config_transition(
    ws: Workspace | None = None,
    *,
    timeout: float = 10.0,
) -> Iterator[LLMConfigTransition]:
    """Yield one unredacted snapshot with CAS persistence under the transition lock."""
    workspace = ws or Workspace()
    with llm_config_transition_guard(workspace, timeout=timeout):
        with _llm_transaction_lock(workspace):
            _load_or_initialise_workspace_locked(workspace)
            _recover_llm_config_transaction_locked(workspace)
            snapshot = _snapshot_from_loaded_workspace(workspace)
        yield LLMConfigTransition(workspace, snapshot)


def _unlink_file(path: Path) -> None:
    """Delete one transaction-owned file while surfacing every real failure."""
    durable_unlink(path)


def _replace_file(source: Path, destination: Path) -> None:
    durable_replace(source, destination)


def _sha256_file(path: Path) -> str:
    return hashlib.sha256(read_owner_owned_bytes(path)).hexdigest()


def _write_transaction_journal(secret_path: Path, journal: dict[str, Any]) -> None:
    journal_path, journal_tmp_path, _, _ = _transaction_paths(secret_path)
    try:
        write_secret_text(journal_tmp_path, json.dumps(journal, sort_keys=True))
        _replace_file(journal_tmp_path, journal_path)
    except Exception:
        _unlink_file(journal_tmp_path)
        raise


def _read_transaction_journal(secret_path: Path) -> dict[str, Any] | None:
    journal_path, _, _, _ = _transaction_paths(secret_path)
    cleanup_pending_unlink(journal_path)
    try:
        raw = json.loads(read_owner_owned_text(journal_path))
    except FileNotFoundError:
        return None
    except (OSError, json.JSONDecodeError, TypeError) as exc:
        raise RuntimeError("LLM config transaction journal is unreadable") from exc

    if (
        not isinstance(raw, dict)
        or raw.get("version") != _LLM_TRANSACTION_VERSION
        or raw.get("phase") not in _LLM_TRANSACTION_PHASES
        or raw.get("operation") not in _LLM_TRANSACTION_OPERATIONS
        or not isinstance(raw.get("previous_llm"), dict)
        or not isinstance(raw.get("desired_llm"), dict)
        or not isinstance(raw.get("had_secret"), bool)
        or not isinstance(raw.get("old_sha256"), str)
        or not isinstance(raw.get("new_sha256"), str)
    ):
        raise RuntimeError("LLM config transaction journal is invalid")
    return raw


def _replace_llm_section(workspace: Workspace, llm: dict[str, Any]) -> None:
    workspace.update(lambda config: config.__setitem__("llm", copy.deepcopy(llm)))


def _recover_prepared_transaction(
    workspace: Workspace,
    secret_path: Path,
    journal: dict[str, Any],
) -> None:
    _, _, staged_path, backup_path = _transaction_paths(secret_path)
    if journal["had_secret"]:
        if backup_path.exists():
            _replace_file(backup_path, secret_path)
        if not secret_path.exists() or _sha256_file(secret_path) != journal["old_sha256"]:
            raise RuntimeError("previous LLM credential cannot be proven during transaction recovery")
    else:
        _unlink_file(secret_path)

    _replace_llm_section(workspace, journal["previous_llm"])
    _unlink_file(staged_path)
    _unlink_file(backup_path)


def _recover_committed_transaction(
    workspace: Workspace,
    secret_path: Path,
    journal: dict[str, Any],
) -> None:
    _, _, staged_path, backup_path = _transaction_paths(secret_path)
    if journal["operation"] == "replace":
        if not secret_path.exists() or _sha256_file(secret_path) != journal["new_sha256"]:
            raise RuntimeError("committed LLM credential cannot be proven during transaction recovery")
        _replace_llm_section(workspace, journal["desired_llm"])
    else:
        _replace_llm_section(workspace, journal["desired_llm"])
        _unlink_file(secret_path)

    _unlink_file(staged_path)
    _unlink_file(backup_path)


def _recover_llm_config_transaction_locked(workspace: Workspace) -> None:
    secret_path = _secret_path(workspace)
    journal_path, journal_tmp_path, staged_path, backup_path = _transaction_paths(secret_path)
    journal = _read_transaction_journal(secret_path)
    if journal is None:
        _unlink_file(journal_tmp_path)
        _unlink_file(staged_path)
        if backup_path.exists():
            raise RuntimeError("orphaned LLM credential backup has no recovery journal")
        workspace.load()
        return

    recovery_workspace = Workspace(workspace.workspace_dir)
    if journal["phase"] == "prepared":
        _recover_prepared_transaction(recovery_workspace, secret_path, journal)
    else:
        _recover_committed_transaction(recovery_workspace, secret_path, journal)

    _unlink_file(journal_tmp_path)
    _unlink_file(journal_path)
    workspace.load()


def recover_llm_config_transaction(ws: Workspace | None = None) -> None:
    """Finish or roll back an interrupted credential/config transaction."""
    workspace = ws or Workspace()
    with llm_config_transition_guard(workspace):
        with _llm_transaction_lock(workspace):
            _load_or_initialise_workspace_locked(workspace)
            _recover_llm_config_transaction_locked(workspace)


def _stage_secret(secret_path: Path, api_key: str) -> Path:
    _, _, staged_path, _ = _transaction_paths(secret_path)
    try:
        write_secret_text(staged_path, api_key)
    except Exception:
        _unlink_file(staged_path)
        raise
    return staged_path


def _prepare_transaction_journal(
    secret_path: Path,
    *,
    operation: str,
    previous_llm: dict[str, Any],
    desired_llm: dict[str, Any],
    replacement_key: str = "",
) -> dict[str, Any]:
    try:
        old_sha256 = _sha256_file(secret_path)
    except FileNotFoundError:
        had_secret = False
        old_sha256 = ""
    else:
        had_secret = True
    return {
        "version": _LLM_TRANSACTION_VERSION,
        "phase": "prepared",
        "operation": operation,
        "previous_llm": copy.deepcopy(previous_llm),
        "desired_llm": copy.deepcopy(desired_llm),
        "had_secret": had_secret,
        "old_sha256": old_sha256,
        "new_sha256": hashlib.sha256(replacement_key.encode("utf-8")).hexdigest()
        if replacement_key
        else "",
    }


def _mark_transaction_committed(secret_path: Path, journal: dict[str, Any]) -> None:
    committed = copy.deepcopy(journal)
    committed["phase"] = "committed"
    _write_transaction_journal(secret_path, committed)


def _handle_transaction_failure(workspace: Workspace, secret_path: Path, exc: Exception) -> None:
    journal = _read_transaction_journal(secret_path)
    if journal is not None and journal["phase"] == "committed":
        raise RuntimeError("LLM config update committed but credential cleanup is pending") from exc
    try:
        _recover_llm_config_transaction_locked(workspace)
    except Exception as recovery_exc:
        raise RuntimeError("LLM config update failed and credential rollback could not be proven") from recovery_exc


def _persist_llm_config_snapshot(
    payload: dict[str, Any],
    workspace: Workspace,
    *,
    expected_revision: str | None = None,
) -> LLMConfigSnapshot:
    if not any(field in payload for field in ("provider", "host", "model", "api_key")):
        raise ValueError("At least one of provider, host, model, api_key is required")

    replacement_key = (
        _normalise_api_key(payload.get("api_key", ""))
        if "api_key" in payload
        else None
    )
    secret_path = _secret_path(workspace)

    with _llm_transaction_lock(workspace):
        _load_or_initialise_workspace_locked(workspace)
        _recover_llm_config_transaction_locked(workspace)
        current_config = workspace.as_dict()
        current_llm = current_config.get("llm", {})
        if not isinstance(current_llm, dict):
            current_llm = {}
        current_snapshot = _snapshot_from_loaded_workspace(workspace)
        if expected_revision is not None and current_snapshot.revision != expected_revision:
            raise LLMConfigConflictError("LLM config changed during transition")
        previous_llm = copy.deepcopy(current_llm)
        current_provider = str(current_llm.get("provider", "") or "").strip().lower()
        current_host = str(current_llm.get("host", "") or "").strip()
        current_destination = _trust_destination(current_provider, current_host)

        provider = str(payload.get("provider", current_provider) or "").strip().lower()
        if provider == "lmstudio":
            raise ValueError(_LMSTUDIO_RETIRED_ERROR)
        default_host = "" if "provider" in payload and provider == "ollama" else current_host
        host = str(payload.get("host", default_host) or "").strip()
        if provider == "ollama":
            host = normalise_ollama_host(host)
        else:
            host = _validate_configurable_api_base_url(provider, host)
        destination = _trust_destination(provider, host)
        destination_changed = (provider, destination) != (current_provider, current_destination)

        if replacement_key and (provider == "ollama" or not provider or not destination):
            raise ValueError("An LLM API key requires a non-Ollama provider and trust destination")

        current_ref = str(current_llm.get("api_key_ref", "") or "")
        current_key_provider = str(current_llm.get("api_key_provider", "") or "").strip().lower()
        current_key_destination = _normalise_destination(
            str(current_llm.get("api_key_destination", "") or "")
        )
        binding_present = bool(current_ref or current_key_provider or current_key_destination)
        binding_matches = (
            current_ref == LLM_API_KEY_REF
            and bool(current_destination)
            and current_key_provider == current_provider
            and current_key_destination == current_destination
        )
        clear_binding = (
            replacement_key == ""
            if replacement_key is not None
            else destination_changed or (binding_present and not binding_matches)
        )
        write_host = (
            "host" in payload
            or ("provider" in payload and provider == "ollama")
            or (provider == "ollama" and current_host != host)
        )

        desired_config = {"llm": copy.deepcopy(previous_llm)}
        desired_llm = _llm_section(desired_config)
        if clear_binding or replacement_key or destination_changed:
            _clear_api_key_binding(desired_llm)
        if "provider" in payload:
            desired_llm["provider"] = provider
        if write_host:
            desired_llm["host"] = host
        if "model" in payload:
            desired_llm["model"] = str(payload.get("model", "") or "").strip()
        if replacement_key:
            desired_llm["api_key_provider"] = provider
            desired_llm["api_key_destination"] = destination
            desired_llm["api_key_ref"] = LLM_API_KEY_REF

        operation = "replace" if replacement_key else "delete"
        requires_secret_transaction = replacement_key is not None or clear_binding
        if not requires_secret_transaction:
            _replace_llm_section(workspace, desired_llm)
        else:
            journal = _prepare_transaction_journal(
                secret_path,
                operation=operation,
                previous_llm=previous_llm,
                desired_llm=desired_llm,
                replacement_key=replacement_key or "",
            )
            staged_path: Path | None = None
            if replacement_key:
                staged_path = _stage_secret(secret_path, replacement_key)
            try:
                _write_transaction_journal(secret_path, journal)
            except Exception:
                if staged_path is not None:
                    _unlink_file(staged_path)
                raise

            try:
                if replacement_key:
                    _, _, _, backup_path = _transaction_paths(secret_path)
                    if destination_changed and current_ref == LLM_API_KEY_REF:
                        workspace.update(lambda config: _clear_api_key_binding(_llm_section(config)))
                    if secret_path.exists():
                        _replace_file(secret_path, backup_path)
                    _replace_file(staged_path, secret_path)
                    _replace_llm_section(workspace, desired_llm)
                else:
                    _replace_llm_section(workspace, desired_llm)

                _mark_transaction_committed(secret_path, journal)
                if operation == "delete":
                    _unlink_file(secret_path)
                _, journal_tmp_path, staged_path, backup_path = _transaction_paths(secret_path)
                _unlink_file(staged_path)
                _unlink_file(backup_path)
                _unlink_file(journal_tmp_path)
                _unlink_file(_transaction_paths(secret_path)[0])
            except Exception as exc:
                _handle_transaction_failure(workspace, secret_path, exc)
                raise

        return _snapshot_from_loaded_workspace(workspace)


def persist_llm_config(payload: dict[str, Any], ws: Workspace | None = None) -> dict[str, Any]:
    """Persist a partial LLM config patch and return the redacted config."""
    workspace = ws or Workspace()
    with llm_config_transition_guard(workspace):
        return _persist_llm_config_snapshot(payload, workspace).redacted()
