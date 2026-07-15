"""Localhost control plane for FlintTrade's managed Ollama runtime."""

from __future__ import annotations

import hmac
import logging
import os
import secrets
import threading
import time
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from dataclasses import dataclass, field
from typing import Any

from flask import Blueprint, Response, current_app, jsonify, request
from filelock import Timeout as FileLockTimeout

from .ollama_runtime import OllamaRuntime, OllamaRuntimeError

logger = logging.getLogger("flinttrade.core.local_ai_routes")

local_ai_bp = Blueprint("local_ai", __name__, url_prefix="/v1/ai/local-runtime")
_LOOPBACK_ADDRESSES = {"127.0.0.1", "::1", "localhost"}
_LLM_CONFIG_TRANSITION_LOCK = threading.RLock()
_RUNTIME_TRANSITION_STATE_LOCK = threading.Lock()
_RUNTIME_TRANSITION_STATE_KEY = "_FLINTTRADE_LLM_RUNTIME_TRANSITION_STATE"
_ROUTE_TRANSITION_WAIT_SECONDS = 5.0


@dataclass
class _RuntimeTransitionState:
    guard: threading.Lock = field(default_factory=threading.Lock)
    generation: int = 0
    shutdown_admitted: bool = False


def _runtime_transition_state(app: Any, *, deadline: float | None = None) -> _RuntimeTransitionState:
    state = app.config.get(_RUNTIME_TRANSITION_STATE_KEY)
    if isinstance(state, _RuntimeTransitionState):
        return state
    timeout = None if deadline is None else max(0.0, deadline - time.monotonic())
    acquired = (
        _RUNTIME_TRANSITION_STATE_LOCK.acquire()
        if timeout is None
        else _RUNTIME_TRANSITION_STATE_LOCK.acquire(timeout=timeout)
    )
    if not acquired:
        raise OllamaRuntimeError("managed Ollama transition-state admission timed out")
    try:
        state = app.config.get(_RUNTIME_TRANSITION_STATE_KEY)
        if not isinstance(state, _RuntimeTransitionState):
            state = _RuntimeTransitionState()
            app.config[_RUNTIME_TRANSITION_STATE_KEY] = state
        return state
    finally:
        _RUNTIME_TRANSITION_STATE_LOCK.release()


def _admit_provider_transition(app: Any) -> int:
    state = _runtime_transition_state(app)
    with state.guard:
        if state.shutdown_admitted:
            raise OllamaRuntimeError("managed Ollama runtime shutdown is in progress")
        state.generation += 1
        return state.generation


def _admit_runtime_shutdown(app: Any, *, deadline: float) -> None:
    state = _runtime_transition_state(app, deadline=deadline)
    acquired = state.guard.acquire(timeout=max(0.0, deadline - time.monotonic()))
    if not acquired:
        raise OllamaRuntimeError("managed Ollama transition-state admission timed out")
    try:
        if not state.shutdown_admitted:
            state.generation += 1
            state.shutdown_admitted = True
    finally:
        state.guard.release()


def _ensure_current_generation(app: Any, generation: int) -> None:
    state = _runtime_transition_state(app)
    with state.guard:
        if state.shutdown_admitted or state.generation != generation:
            raise OllamaRuntimeError("managed Ollama runtime shutdown is in progress")


def _run_for_current_generation(
    app: Any,
    generation: int,
    operation: Callable[[], Any],
) -> Any | None:
    """Run one runtime action only while its admitted generation remains current."""
    state = _runtime_transition_state(app)
    with state.guard:
        if state.shutdown_admitted or state.generation != generation:
            return None
    return operation()


@contextmanager
def _bounded_transition_lock(deadline: float) -> Iterator[None]:
    acquired = _LLM_CONFIG_TRANSITION_LOCK.acquire(
        timeout=max(0.0, deadline - time.monotonic()),
    )
    if not acquired:
        raise OllamaRuntimeError("managed Ollama config transition timed out")
    try:
        yield
    finally:
        _LLM_CONFIG_TRANSITION_LOCK.release()


@contextmanager
def _runtime_transition_guard(
    app: Any,
    *,
    timeout: float = _ROUTE_TRANSITION_WAIT_SECONDS,
) -> Iterator[None]:
    """Share runtime-operation exclusion with direct config writers."""
    from .llm_config import llm_config_transition_guard  # noqa: PLC0415

    if timeout < 0:
        raise ValueError("managed Ollama transition timeout must be non-negative")
    deadline = time.monotonic() + timeout
    with _bounded_transition_lock(deadline):
        generation = _admit_provider_transition(app)
        remaining = max(0.0, deadline - time.monotonic())
        try:
            with llm_config_transition_guard(timeout=remaining):
                _ensure_current_generation(app, generation)
                yield
        except FileLockTimeout as exc:
            raise OllamaRuntimeError("managed Ollama config transition timed out") from exc


def _local_only() -> tuple[Response, int] | None:
    if (request.remote_addr or "") in _LOOPBACK_ADDRESSES:
        return None
    return jsonify({"status": "error", "message": "This endpoint is only reachable from localhost"}), 403


def require_local_control_auth(
    *,
    message: str = "Local AI control requires an authenticated session",
) -> tuple[Response, int] | None:
    """Require a session or configured backend key independently of app defaults."""
    auth_header = request.headers.get("Authorization", "")
    bearer = auth_header.removeprefix("Bearer ").strip() if auth_header.startswith("Bearer ") else ""
    if bearer:
        try:
            from .auth_routes import decode_token  # noqa: PLC0415

            if decode_token(bearer).get("type") == "session":
                return None
        except Exception:  # noqa: BLE001 - invalid credentials are mapped uniformly
            pass

    expected_key = os.environ.get("FLINTTRADE_API_KEY", "")
    supplied_key = request.headers.get("X-API-Key", "")
    if expected_key and supplied_key and hmac.compare_digest(supplied_key, expected_key):
        return None
    return jsonify({"status": "error", "message": message}), 401


@local_ai_bp.before_request
def _guard_local_ai_control() -> tuple[Response, int] | None:
    denied = _local_only()
    return denied if denied is not None else require_local_control_auth()


def _runtime() -> OllamaRuntime | None:
    runtime = current_app.config.get("OLLAMA_RUNTIME")
    return runtime if runtime is not None else None


def _unavailable_response() -> tuple[Response, int]:
    reason = str(current_app.config.get("OLLAMA_RUNTIME_ERROR") or "managed runtime is unavailable")
    return (
        jsonify(
            {
                "status": "error",
                "message": "Managed local AI is unavailable on this platform",
                "data": {"supported": False, "reason": reason[:300]},
            }
        ),
        503,
    )


def _success(data: Any, *, status_code: int = 200) -> tuple[Response, int]:
    return jsonify({"status": "success", "data": data}), status_code


def _required_admission_id(payload: dict[str, Any]) -> str:
    admission_id = payload.get("admission_id")
    if not isinstance(admission_id, str):
        raise ValueError("admission_id is required")
    if not admission_id.startswith("adm_") or len(admission_id) != 36:
        raise ValueError("admission_id is invalid")
    if any(character not in "0123456789abcdef" for character in admission_id[4:]):
        raise ValueError("admission_id is invalid")
    return admission_id


def _new_internal_correlation_id() -> str:
    return f"local_{secrets.token_hex(8)}"


def _bounded_exception_code(exc: Exception) -> str:
    name = type(exc).__name__
    safe = "".join(
        character
        for character in name
        if character.isascii() and (character.isalnum() or character in "_.-")
    )
    return (safe or "UnexpectedError")[:64]


def _log_unexpected_runtime_failure(operation: str, exc: Exception) -> str:
    correlation_id = _new_internal_correlation_id()
    logger.error(
        "Managed local AI %s failed (error_type=%s, correlation_id=%s)",
        operation,
        _bounded_exception_code(exc),
        correlation_id,
    )
    return correlation_id


def _runtime_error(exc: Exception) -> tuple[Response, int]:
    if isinstance(exc, ValueError):
        return jsonify({"status": "error", "message": str(exc)}), 400
    if isinstance(exc, OllamaRuntimeError):
        return jsonify({"status": "error", "message": str(exc)}), 409
    correlation_id = _log_unexpected_runtime_failure("operation", exc)
    return (
        jsonify(
            {
                "status": "error",
                "message": "Managed local AI operation failed",
                "data": {"correlation_id": correlation_id},
            }
        ),
        500,
    )


def _selects_managed_ollama(config: dict[str, Any]) -> bool:
    if str(config.get("provider") or "").strip().lower() != "ollama":
        return False
    from .llm_config import normalise_ollama_host  # noqa: PLC0415

    try:
        normalise_ollama_host(str(config.get("host") or ""))
    except ValueError:
        return False
    return True


def _model_aliases(model: str) -> set[str]:
    tail = model.rsplit("/", 1)[-1]
    if ":" not in tail:
        return {model, f"{model}:latest"}
    if tail.endswith(":latest"):
        return {model, model[: -len(":latest")]}
    return {model}


def _configured_ollama_models() -> tuple[str, ...]:
    """Protect stored and effective managed-model selections from reclamation."""
    from .llm_config import read_effective_llm_config, read_llm_config  # noqa: PLC0415

    protected: list[str] = []
    for config in (read_llm_config(), read_effective_llm_config()):
        if str(config.get("provider") or "").strip().lower() != "ollama":
            continue
        model = str(config.get("model") or "").strip()
        if model and model not in protected:
            protected.append(model)
    return tuple(protected)


def _persist_locked_model_selection(
    acceptance: dict[str, Any],
    *,
    read_config: Callable[[], dict[str, Any]] | None = None,
    persist_config: Callable[[dict[str, Any]], dict[str, Any]] | None = None,
) -> None:
    """Replace a configured mutable source tag with its verified locked alias."""
    source_model = str(acceptance.get("source_model") or "").strip()
    locked_model = str(acceptance.get("model") or "").strip()
    if not acceptance.get("accepted") or not source_model or not locked_model or source_model == locked_model:
        return
    if read_config is None or persist_config is None:
        from .llm_config import persist_llm_config, read_llm_config  # noqa: PLC0415

        read_config = read_config or read_llm_config
        persist_config = persist_config or persist_llm_config
    current = read_config()
    configured_model = str(current.get("model") or "").strip()
    if (
        str(current.get("provider") or "").strip().lower() == "ollama"
        and _model_aliases(configured_model).intersection(_model_aliases(source_model))
    ):
        persist_config({"model": locked_model})


def start_configured_local_ai_runtime(
    app: Any,
    *,
    config: dict[str, Any] | None = None,
) -> bool:
    """Start a configured, previously installed managed runtime at boot."""
    if config is None:
        try:
            from .llm_config import read_effective_llm_config  # noqa: PLC0415

            config = read_effective_llm_config()
        except Exception as exc:  # noqa: BLE001 - app remains available for recovery
            correlation_id = _log_unexpected_runtime_failure("autostart-config", exc)
            app.config["OLLAMA_AUTOSTART_ERROR"] = (
                f"Could not read local AI configuration (correlation_id={correlation_id})"
            )
            return False
    if str(config.get("provider") or "").strip().lower() != "ollama":
        app.config.pop("OLLAMA_AUTOSTART_ERROR", None)
        return False

    runtime = app.config.get("OLLAMA_RUNTIME")
    if runtime is None:
        app.config["OLLAMA_AUTOSTART_ERROR"] = str(
            app.config.get("OLLAMA_RUNTIME_ERROR") or "Managed Ollama runtime is unavailable"
        )
        return False
    try:
        with _runtime_transition_guard(app):
            status = runtime.status()
            if status.get("integrity_error"):
                app.config["OLLAMA_AUTOSTART_ERROR"] = "Managed Ollama runtime requires repair"
                return False
            if status.get("external_process") or status.get("state") == "conflict":
                app.config["OLLAMA_AUTOSTART_ERROR"] = "Managed Ollama endpoint is occupied by an external process"
                return False
            if status.get("ready"):
                app.config.pop("OLLAMA_AUTOSTART_ERROR", None)
                return True
            operation = status.get("operation")
            if isinstance(operation, dict) and operation.get("state") == "running":
                if operation.get("kind") == "start":
                    return True
                app.config["OLLAMA_AUTOSTART_ERROR"] = "Another managed Ollama operation is in progress"
                return False
            if not status.get("installed"):
                app.config["OLLAMA_AUTOSTART_ERROR"] = "Managed Ollama runtime is not installed"
                return False
            runtime.start_async()
    except Exception as exc:  # noqa: BLE001 - app remains available for recovery
        correlation_id = _log_unexpected_runtime_failure("autostart", exc)
        app.config["OLLAMA_AUTOSTART_ERROR"] = (
            f"Managed Ollama autostart failed (correlation_id={correlation_id})"
        )
        return False
    app.config.pop("OLLAMA_AUTOSTART_ERROR", None)
    return True


def shutdown_local_ai_runtime(app: Any, *, timeout: float = 5.0) -> bool:
    """Stop the managed local AI child within a bounded wait."""
    if timeout < 0:
        raise ValueError("timeout must be non-negative")
    deadline = time.monotonic() + timeout
    try:
        _admit_runtime_shutdown(app, deadline=deadline)
        runtime = app.config.get("OLLAMA_RUNTIME")
        if runtime is None:
            return True
        from .llm_config import llm_config_transition_guard  # noqa: PLC0415

        with _bounded_transition_lock(deadline):
            remaining = max(0.0, deadline - time.monotonic())
            with llm_config_transition_guard(timeout=remaining):
                return bool(runtime.shutdown(timeout=max(0.0, deadline - time.monotonic())))
    except (FileLockTimeout, OllamaRuntimeError):
        return False


def _provider_transition_uses_managed_ollama(
    payload: dict[str, Any],
    previous: dict[str, Any],
    effective: dict[str, Any],
) -> bool:
    previous_provider = str(previous.get("provider") or "").strip().lower()
    target_provider = str(payload.get("provider", previous_provider) or "").strip().lower()
    previous_runtime_provider = str(effective.get("provider") or previous_provider or "ollama").strip().lower()
    provider_override = os.getenv("LLM_PROVIDER", "").strip()
    target_runtime_provider = (
        previous_runtime_provider
        if provider_override or "provider" not in payload
        else target_provider or "ollama"
    )
    return "ollama" in {
        previous_provider,
        target_provider,
        previous_runtime_provider,
        target_runtime_provider,
    }


@contextmanager
def _provider_operation_truth_guard(
    app: Any,
    payload: dict[str, Any],
    *,
    previous: dict[str, Any],
    effective: dict[str, Any],
) -> Iterator[str | None]:
    if not _provider_transition_uses_managed_ollama(payload, previous, effective):
        yield None
        return
    runtime = app.config.get("OLLAMA_RUNTIME")
    if runtime is None:
        raise OllamaRuntimeError("managed Ollama operation truth is unavailable")
    with runtime.provider_transition_guard() as operation_id:
        yield operation_id


def _persist_llm_config_with_runtime_locked(
    app: Any,
    payload: dict[str, Any],
    *,
    generation: int,
    previous: dict[str, Any],
    effective: dict[str, Any],
    read_current_effective_config: Callable[[], dict[str, Any]],
    resolve_secret: Callable[[], str],
    persist_config: Callable[[dict[str, Any]], dict[str, Any]],
    provider_operation_id: str | None,
) -> dict[str, Any]:
    _ensure_current_generation(app, generation)
    previous_provider = str(previous.get("provider") or "").strip().lower()
    target_provider = str(payload.get("provider", previous_provider) or "").strip().lower()
    previous_runtime_provider = str(effective.get("provider") or previous_provider or "ollama").strip().lower()
    provider_override = os.getenv("LLM_PROVIDER", "").strip()
    target_runtime_provider = (
        previous_runtime_provider
        if provider_override or "provider" not in payload
        else target_provider or "ollama"
    )
    if target_provider == "ollama":
        from .llm_config import normalise_ollama_host  # noqa: PLC0415

        normalise_ollama_host(str(payload.get("host") or ""))

    rollback_payload = {
        "provider": previous_provider,
        "host": str(previous.get("host") or ""),
        "model": str(previous.get("model") or ""),
        "api_key": resolve_secret(),
    }
    needs_managed_activation = target_provider == "ollama" and any(
        field in payload for field in ("provider", "model")
    )
    managed_ollama_involved = _provider_transition_uses_managed_ollama(payload, previous, effective)
    runtime = app.config.get("OLLAMA_RUNTIME")
    runtime_status: dict[str, Any] | None = None
    if managed_ollama_involved:
        if runtime is None:
            raise OllamaRuntimeError("managed Ollama operation truth is unavailable")
        runtime_status = _run_for_current_generation(app, generation, runtime.status)
        if runtime_status is None:
            raise OllamaRuntimeError("managed Ollama runtime shutdown is in progress")
        operation = runtime_status.get("operation")
        if (
            isinstance(operation, dict)
            and operation.get("state") == "running"
            and operation.get("id") != provider_operation_id
        ):
            raise OllamaRuntimeError("another managed Ollama operation is already running")
        if isinstance(runtime_status.get("unresolved_operation"), dict):
            raise OllamaRuntimeError("an indeterminate managed Ollama operation requires acknowledgement")
    if (
        target_provider == previous_provider or target_runtime_provider == previous_runtime_provider
    ) and not needs_managed_activation:
        _ensure_current_generation(app, generation)
        if managed_ollama_involved:
            assert runtime is not None
            runtime.mark_provider_transition_config_mutation_started()
        return persist_config(payload)

    if target_runtime_provider == "ollama":
        assert runtime is not None and runtime_status is not None
        status = runtime_status
        if status.get("external_process"):
            raise OllamaRuntimeError("managed Ollama endpoint is occupied by an external process")
        if status.get("integrity_error"):
            raise OllamaRuntimeError("managed Ollama runtime integrity verification failed; repair it first")
        if not status.get("installed"):
            raise OllamaRuntimeError("managed Ollama runtime is not installed")

        started_here = False
        if not status.get("ready"):
            started = _run_for_current_generation(
                app,
                generation,
                lambda: runtime.start(timeout_seconds=30.0),
            )
            if started is None:
                raise OllamaRuntimeError("managed Ollama runtime shutdown is in progress")
            if not started.get("ready") or not started.get("managed_process") or started.get("external_process"):
                raise OllamaRuntimeError("managed Ollama runtime did not reach owned readiness")
            started_here = True
        elif not status.get("managed_process"):
            raise OllamaRuntimeError("managed Ollama readiness ownership could not be proven")
        target_model = str(
            payload.get("model", previous.get("model") or effective.get("model") or "")
        ).strip()
        try:
            if not target_model or not runtime.model_is_accepted(target_model):
                raise OllamaRuntimeError("managed Ollama requires an installed, accepted model")
        except Exception as exc:
            cleanup_failed = False
            if started_here:
                try:
                    stopped = runtime.stop(expected_operation_id=provider_operation_id)
                    cleanup_failed = bool(stopped.get("managed_process") or stopped.get("ready"))
                except Exception:  # noqa: BLE001 - reported as an unproven cleanup
                    cleanup_failed = True
            if cleanup_failed:
                raise OllamaRuntimeError(
                    "managed Ollama model activation failed and cleanup could not be proven"
                ) from exc
            runtime.mark_provider_transition_mutation_resolved()
            raise
        try:
            _ensure_current_generation(app, generation)
            runtime.mark_provider_transition_config_mutation_started()
            return persist_config(payload)
        except Exception as exc:
            rollback_failed = False
            if started_here:
                try:
                    stopped = runtime.stop(expected_operation_id=provider_operation_id)
                    rollback_failed = bool(stopped.get("managed_process") or stopped.get("ready"))
                except Exception:  # noqa: BLE001 - reported as an unproven rollback
                    rollback_failed = True
            try:
                persist_config(rollback_payload)
            except Exception:  # noqa: BLE001 - reported as an unproven rollback
                rollback_failed = True
            if rollback_failed:
                raise OllamaRuntimeError(
                    "LLM config transition failed and rollback could not be proven"
                ) from exc
            runtime.mark_provider_transition_mutation_resolved()
            raise

    if previous_runtime_provider == "ollama":
        assert runtime is not None and runtime_status is not None
        status = runtime_status
        stopped_here = bool(status.get("managed_process"))
        if stopped_here:
            runtime.mark_provider_transition_config_mutation_started()
            stopped = _run_for_current_generation(
                app,
                generation,
                lambda: runtime.stop(expected_operation_id=provider_operation_id),
            )
            if stopped is None:
                raise OllamaRuntimeError("managed Ollama runtime shutdown is in progress")
            if stopped.get("managed_process") or stopped.get("ready"):
                raise OllamaRuntimeError("managed Ollama teardown could not be proven")
        try:
            _ensure_current_generation(app, generation)
            runtime.mark_provider_transition_config_mutation_started()
            return persist_config(payload)
        except Exception as exc:
            rollback_failed = False
            rollback_persisted = False
            try:
                persist_config(rollback_payload)
                rollback_persisted = True
            except Exception:  # noqa: BLE001 - reported as an unproven rollback
                rollback_failed = True
            restart_managed_ollama = False
            if stopped_here and rollback_persisted:
                try:
                    restart_managed_ollama = _selects_managed_ollama(
                        read_current_effective_config()
                    )
                except Exception:  # noqa: BLE001 - reported as an unproven rollback
                    rollback_failed = True
            if restart_managed_ollama:
                try:
                    restarted = _run_for_current_generation(
                        app,
                        generation,
                        lambda: runtime.start(timeout_seconds=30.0),
                    )
                    if restarted is not None:
                        rollback_failed = rollback_failed or not bool(
                            restarted.get("ready") and restarted.get("managed_process")
                        )
                except Exception:  # noqa: BLE001 - reported as an unproven rollback
                    rollback_failed = True
            if rollback_failed:
                raise OllamaRuntimeError(
                    "LLM config transition failed and rollback could not be proven"
                ) from exc
            runtime.mark_provider_transition_mutation_resolved()
            raise

    _ensure_current_generation(app, generation)
    if managed_ollama_involved:
        assert runtime is not None
        runtime.mark_provider_transition_config_mutation_started()
    return persist_config(payload)


def persist_llm_config_with_runtime(
    app: Any,
    payload: dict[str, Any],
    *,
    read_config: Callable[[], dict[str, Any]] | None = None,
    read_effective_config: Callable[[], dict[str, Any]] | None = None,
    read_current_effective_config: Callable[[], dict[str, Any]] | None = None,
    resolve_secret: Callable[[], str] | None = None,
    persist_config: Callable[[dict[str, Any]], dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Persist an LLM provider change as one managed-runtime transaction."""
    if not any(field in payload for field in ("provider", "host", "model", "api_key")):
        raise ValueError("At least one of provider, host, model, api_key is required")
    from .llm_config import reject_retired_llm_provider  # noqa: PLC0415

    reject_retired_llm_provider(payload.get("provider"))

    injected = any(
        callback is not None
        for callback in (
            read_config,
            read_effective_config,
            read_current_effective_config,
            resolve_secret,
            persist_config,
        )
    )
    if not injected:
        from .llm_config import llm_config_transition  # noqa: PLC0415

        with _LLM_CONFIG_TRANSITION_LOCK:
            generation = _admit_provider_transition(app)
            with llm_config_transition() as transition:
                previous = transition.snapshot.redacted()
                effective = transition.effective
                with _provider_operation_truth_guard(
                    app,
                    payload,
                    previous=previous,
                    effective=effective,
                ) as provider_operation_id:
                    return _persist_llm_config_with_runtime_locked(
                        app,
                        payload,
                        generation=generation,
                        previous=previous,
                        effective=effective,
                        read_current_effective_config=transition.refresh_effective,
                        resolve_secret=lambda: transition.snapshot.api_key,
                        persist_config=transition.persist,
                        provider_operation_id=provider_operation_id,
                    )

    needs_defaults = read_config is None or resolve_secret is None or persist_config is None
    from .llm_config import (  # noqa: PLC0415
        persist_llm_config,
        read_effective_llm_config,
        read_llm_config,
        resolve_llm_api_key,
    )

    read_config = read_config or read_llm_config
    read_effective_config = read_effective_config or (
        read_effective_llm_config if needs_defaults else read_config
    )
    read_current_effective_config = read_current_effective_config or read_effective_config
    resolve_secret = resolve_secret or resolve_llm_api_key
    persist_config = persist_config or persist_llm_config
    with _LLM_CONFIG_TRANSITION_LOCK:
        generation = _admit_provider_transition(app)
        previous = read_config()
        effective = read_effective_config()
        with _provider_operation_truth_guard(
            app,
            payload,
            previous=previous,
            effective=effective,
        ) as provider_operation_id:
            return _persist_llm_config_with_runtime_locked(
                app,
                payload,
                generation=generation,
                previous=previous,
                effective=effective,
                read_current_effective_config=read_current_effective_config,
                resolve_secret=resolve_secret,
                persist_config=persist_config,
                provider_operation_id=provider_operation_id,
            )


@local_ai_bp.get("/status")
def local_ai_status() -> tuple[Response, int]:
    """Return bounded install, process, operation, and model-pull state."""
    denied = _local_only()
    if denied is not None:
        return denied
    runtime = _runtime()
    if runtime is None:
        return _unavailable_response()
    try:
        return _success(runtime.status())
    except Exception as exc:  # noqa: BLE001 - mapped to a bounded HTTP response
        return _runtime_error(exc)


@local_ai_bp.post("/install")
def install_local_ai() -> tuple[Response, int]:
    """Queue the pinned, hash-verified Ollama runtime download."""
    denied = _local_only()
    if denied is not None:
        return denied
    payload = request.get_json(silent=True) or {}
    if payload.get("confirmed") is not True:
        return jsonify({"status": "error", "message": "Runtime download confirmation is required"}), 400
    runtime = _runtime()
    if runtime is None:
        return _unavailable_response()
    try:
        admission_id = _required_admission_id(payload)
        with _runtime_transition_guard(current_app):
            return _success(runtime.install_async(admission_id=admission_id), status_code=202)
    except Exception as exc:  # noqa: BLE001 - mapped to a bounded HTTP response
        return _runtime_error(exc)


@local_ai_bp.post("/repair")
def repair_local_ai() -> tuple[Response, int]:
    """Queue an explicitly confirmed replacement of one corrupt install."""
    denied = _local_only()
    if denied is not None:
        return denied
    payload = request.get_json(silent=True) or {}
    if payload.get("confirmed") is not True:
        return jsonify({"status": "error", "message": "Runtime repair confirmation is required"}), 400
    runtime = _runtime()
    if runtime is None:
        return _unavailable_response()
    try:
        admission_id = _required_admission_id(payload)
        with _runtime_transition_guard(current_app):
            status = runtime.status()
            if status.get("repair_allowed") is not True:
                reason = status.get("repair_blocked_reason")
                raise OllamaRuntimeError(
                    str(reason or "managed Ollama runtime repair is unavailable")
                )
            return _success(runtime.repair_async(admission_id=admission_id), status_code=202)
    except Exception as exc:  # noqa: BLE001 - mapped to a bounded HTTP response
        return _runtime_error(exc)


@local_ai_bp.post("/update")
def update_local_ai() -> tuple[Response, int]:
    """Queue an explicitly confirmed update to the preferred pinned release."""
    denied = _local_only()
    if denied is not None:
        return denied
    payload = request.get_json(silent=True) or {}
    if payload.get("confirmed") is not True:
        return jsonify({"status": "error", "message": "Runtime update confirmation is required"}), 400
    runtime = _runtime()
    if runtime is None:
        return _unavailable_response()
    try:
        admission_id = _required_admission_id(payload)
        with _runtime_transition_guard(current_app):
            return _success(runtime.update_async(admission_id=admission_id), status_code=202)
    except Exception as exc:  # noqa: BLE001 - mapped to a bounded HTTP response
        return _runtime_error(exc)


@local_ai_bp.post("/rollback")
def rollback_local_ai() -> tuple[Response, int]:
    """Switch to the one retained, verified rollback release."""
    denied = _local_only()
    if denied is not None:
        return denied
    payload = request.get_json(silent=True) or {}
    if payload.get("confirmed") is not True:
        return jsonify({"status": "error", "message": "Runtime rollback confirmation is required"}), 400
    runtime = _runtime()
    if runtime is None:
        return _unavailable_response()
    try:
        admission_id = _required_admission_id(payload)
        with _runtime_transition_guard(current_app):
            result, status_code = runtime.run_synchronous_operation(
                "rollback",
                admission_id,
                runtime.rollback,
            )
            return _success(result, status_code=status_code)
    except Exception as exc:  # noqa: BLE001 - mapped to a bounded HTTP response
        return _runtime_error(exc)


@local_ai_bp.post("/uninstall")
def uninstall_local_ai() -> tuple[Response, int]:
    """Remove stopped managed runtime binaries while preserving models."""
    denied = _local_only()
    if denied is not None:
        return denied
    payload = request.get_json(silent=True) or {}
    if payload.get("confirmed") is not True:
        return jsonify({"status": "error", "message": "Runtime uninstall confirmation is required"}), 400
    runtime = _runtime()
    if runtime is None:
        return _unavailable_response()
    try:
        admission_id = _required_admission_id(payload)
        with _runtime_transition_guard(current_app):
            result, status_code = runtime.run_synchronous_operation(
                "uninstall",
                admission_id,
                runtime.uninstall,
            )
            return _success(result, status_code=status_code)
    except Exception as exc:  # noqa: BLE001 - mapped to a bounded HTTP response
        return _runtime_error(exc)


@local_ai_bp.post("/start")
def start_local_ai() -> tuple[Response, int]:
    """Queue startup of the installed, loopback-bound server."""
    denied = _local_only()
    if denied is not None:
        return denied
    runtime = _runtime()
    if runtime is None:
        return _unavailable_response()
    payload = request.get_json(silent=True) or {}
    try:
        admission_id = _required_admission_id(payload)
        with _runtime_transition_guard(current_app):
            return _success(runtime.start_async(admission_id=admission_id), status_code=202)
    except Exception as exc:  # noqa: BLE001 - mapped to a bounded HTTP response
        return _runtime_error(exc)


@local_ai_bp.post("/stop")
def stop_local_ai() -> tuple[Response, int]:
    """Stop only an Ollama server process owned by FlintTrade."""
    denied = _local_only()
    if denied is not None:
        return denied
    runtime = _runtime()
    if runtime is None:
        return _unavailable_response()
    payload = request.get_json(silent=True) or {}
    expected_operation_id = payload.get("expected_operation_id")
    if expected_operation_id is not None and not isinstance(expected_operation_id, str):
        return jsonify({"status": "error", "message": "expected_operation_id must be a string"}), 400
    try:
        with _runtime_transition_guard(current_app):
            if expected_operation_id is None:
                return _success(runtime.stop())
            return _success(runtime.stop(expected_operation_id=expected_operation_id))
    except Exception as exc:  # noqa: BLE001 - mapped to a bounded HTTP response
        return _runtime_error(exc)


@local_ai_bp.post("/operations/reconcile")
def reconcile_local_ai_operation() -> tuple[Response, int]:
    """Acknowledge one exact indeterminate receipt without replaying it."""
    denied = _local_only()
    if denied is not None:
        return denied
    payload = request.get_json(silent=True) or {}
    if payload.get("confirmed") is not True:
        return jsonify({"status": "error", "message": "Unknown-outcome confirmation is required"}), 400
    operation_id = payload.get("operation_id")
    if not isinstance(operation_id, str) or not operation_id:
        return jsonify({"status": "error", "message": "operation_id is required"}), 400
    runtime = _runtime()
    if runtime is None:
        return _unavailable_response()
    try:
        admission_id = _required_admission_id(payload)
        with _runtime_transition_guard(current_app):
            return _success(runtime.reconcile_indeterminate_operation(operation_id, admission_id))
    except Exception as exc:  # noqa: BLE001 - mapped to a bounded HTTP response
        return _runtime_error(exc)


@local_ai_bp.get("/models")
def list_local_ai_models() -> tuple[Response, int]:
    """List installed models from the live loopback server."""
    denied = _local_only()
    if denied is not None:
        return denied
    runtime = _runtime()
    if runtime is None:
        return _unavailable_response()
    try:
        return _success(runtime.list_models())
    except Exception as exc:  # noqa: BLE001 - mapped to a bounded HTTP response
        return _runtime_error(exc)


@local_ai_bp.post("/models/pull")
def pull_local_ai_model() -> tuple[Response, int]:
    """Queue one explicitly confirmed model download."""
    denied = _local_only()
    if denied is not None:
        return denied
    payload = request.get_json(silent=True) or {}
    if payload.get("confirmed") is not True:
        return jsonify({"status": "error", "message": "Model download confirmation is required"}), 400
    model = payload.get("model")
    if not isinstance(model, str) or not model.strip():
        return jsonify({"status": "error", "message": "model is required"}), 400
    runtime = _runtime()
    if runtime is None:
        return _unavailable_response()
    try:
        admission_id = _required_admission_id(payload)
        with _runtime_transition_guard(current_app):
            return _success(runtime.pull_model_async(model, admission_id=admission_id), status_code=202)
    except Exception as exc:  # noqa: BLE001 - mapped to a bounded HTTP response
        return _runtime_error(exc)


@local_ai_bp.post("/models/delete")
def delete_local_ai_model() -> tuple[Response, int]:
    """Delete one exact, unselected model alias after confirmation."""
    denied = _local_only()
    if denied is not None:
        return denied
    payload = request.get_json(silent=True) or {}
    if payload.get("confirmed") is not True:
        return jsonify({"status": "error", "message": "Model deletion confirmation is required"}), 400
    model = payload.get("model")
    if not isinstance(model, str) or not model.strip():
        return jsonify({"status": "error", "message": "model is required"}), 400
    runtime = _runtime()
    if runtime is None:
        return _unavailable_response()
    try:
        admission_id = _required_admission_id(payload)
        with _runtime_transition_guard(current_app):
            result, status_code = runtime.run_synchronous_operation(
                "delete_model",
                admission_id,
                lambda: runtime.delete_model(
                    model,
                    protected_models=_configured_ollama_models(),
                ),
                operation_subject={"model": model.strip()},
            )
            return _success(result, status_code=status_code)
    except Exception as exc:  # noqa: BLE001 - mapped to a bounded HTTP response
        return _runtime_error(exc)


@local_ai_bp.post("/models/prune")
def prune_local_ai_models() -> tuple[Response, int]:
    """Delete only unreferenced digest-locked aliases created by FlintTrade."""
    denied = _local_only()
    if denied is not None:
        return denied
    payload = request.get_json(silent=True) or {}
    if payload.get("confirmed") is not True:
        return jsonify({"status": "error", "message": "Model prune confirmation is required"}), 400
    runtime = _runtime()
    if runtime is None:
        return _unavailable_response()
    try:
        admission_id = _required_admission_id(payload)
        with _runtime_transition_guard(current_app):
            result, status_code = runtime.run_synchronous_operation(
                "prune_models",
                admission_id,
                lambda: runtime.prune_models(
                    protected_models=_configured_ollama_models(),
                ),
            )
            return _success(result, status_code=status_code)
    except Exception as exc:  # noqa: BLE001 - mapped to a bounded HTTP response
        return _runtime_error(exc)


@local_ai_bp.post("/models/digests/reset")
def reset_local_ai_model_digests() -> tuple[Response, int]:
    """Reset only invalid FlintTrade model-digest trust metadata."""
    denied = _local_only()
    if denied is not None:
        return denied
    payload = request.get_json(silent=True) or {}
    if payload.get("confirmed") is not True:
        return jsonify({"status": "error", "message": "Model trust-state reset confirmation is required"}), 400
    runtime = _runtime()
    if runtime is None:
        return _unavailable_response()
    try:
        admission_id = _required_admission_id(payload)
        with _runtime_transition_guard(current_app):
            result, status_code = runtime.run_synchronous_operation(
                "reset_model_digests",
                admission_id,
                runtime.reset_model_digest_state,
            )
            return _success(result, status_code=status_code)
    except Exception as exc:  # noqa: BLE001 - mapped to a bounded HTTP response
        return _runtime_error(exc)


@local_ai_bp.post("/models/digests/accept")
def accept_local_ai_model_digest() -> tuple[Response, int]:
    """Accept one exact live model digest after explicit operator confirmation."""
    denied = _local_only()
    if denied is not None:
        return denied
    payload = request.get_json(silent=True) or {}
    if payload.get("confirmed") is not True:
        return jsonify({"status": "error", "message": "Model digest acceptance confirmation is required"}), 400
    model = payload.get("model")
    digest = payload.get("digest")
    if not isinstance(model, str) or not model.strip():
        return jsonify({"status": "error", "message": "model is required"}), 400
    if not isinstance(digest, str) or not digest.strip():
        return jsonify({"status": "error", "message": "digest is required"}), 400
    runtime = _runtime()
    if runtime is None:
        return _unavailable_response()
    try:
        admission_id = _required_admission_id(payload)
        deadline = time.monotonic() + _ROUTE_TRANSITION_WAIT_SECONDS
        with _bounded_transition_lock(deadline):
            from .llm_config import llm_config_transition  # noqa: PLC0415

            generation = _admit_provider_transition(current_app)
            with llm_config_transition(
                timeout=max(0.0, deadline - time.monotonic()),
            ) as transition:
                _ensure_current_generation(current_app, generation)

                def accept_and_persist() -> dict[str, Any]:
                    acceptance = runtime.accept_model_digest(model, digest)
                    try:
                        _persist_locked_model_selection(
                            acceptance,
                            read_config=transition.snapshot.redacted,
                            persist_config=transition.persist,
                        )
                    except Exception as exc:
                        raise OllamaRuntimeError(
                            "model digest was accepted but the locked model selection could not be persisted"
                        ) from exc
                    return acceptance

                result, status_code = runtime.run_synchronous_operation(
                    "accept_model_digest",
                    admission_id,
                    accept_and_persist,
                    operation_subject={"model": model.strip(), "digest": digest.strip()},
                )
                return _success(result, status_code=status_code)
    except FileLockTimeout:
        return _runtime_error(OllamaRuntimeError("managed Ollama config transition timed out"))
    except Exception as exc:  # noqa: BLE001 - mapped to a bounded HTTP response
        return _runtime_error(exc)
