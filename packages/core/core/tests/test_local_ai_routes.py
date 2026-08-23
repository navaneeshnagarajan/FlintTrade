from __future__ import annotations

from contextlib import contextmanager
import logging
from pathlib import Path
import threading
import time
from typing import Any
from unittest.mock import MagicMock

import pytest
from flask import Flask
from flask.testing import FlaskClient

from flinttrade_core import local_ai_routes
from flinttrade_core.llm_config import LLMConfigConflictError
from flinttrade_core.local_ai_routes import (
    _persist_locked_model_selection,
    local_ai_bp,
    persist_llm_config_with_runtime,
    shutdown_local_ai_runtime,
    start_configured_local_ai_runtime,
)
from flinttrade_core.ollama_runtime import OllamaRuntime, OllamaRuntimeError

_ADMISSION_ID = f"adm_{'a' * 32}"


class _FakeRuntime:
    def __init__(self) -> None:
        self.calls: list[tuple[str, Any]] = []
        self.operation_subjects: list[tuple[str, dict[str, str] | None]] = []
        self.repair_allowed = False
        self.repair_blocked_reason: str | None = "Runtime repair is not required."

    def status(self) -> dict[str, Any]:
        return {
            "state": "not_installed",
            "ready": False,
            "repair_allowed": self.repair_allowed,
            "repair_blocked_reason": self.repair_blocked_reason,
        }

    @contextmanager
    def provider_transition_guard(self):  # type: ignore[no-untyped-def]
        yield

    def mark_provider_transition_config_mutation_started(self) -> None:
        pass

    def mark_provider_transition_mutation_resolved(self) -> None:
        pass

    def install_async(self, *, admission_id: str | None = None) -> dict[str, Any]:
        self.calls.append(("install", admission_id))
        return {"operation": {"kind": "install", "state": "running"}}

    def repair_async(self, *, admission_id: str | None = None) -> dict[str, Any]:
        self.calls.append(("repair", admission_id))
        return {"operation": {"kind": "repair", "state": "running"}}

    def update_async(self, *, admission_id: str | None = None) -> dict[str, Any]:
        self.calls.append(("update", admission_id))
        return {"operation": {"kind": "update", "state": "running"}}

    def rollback(self) -> dict[str, Any]:
        self.calls.append(("rollback", None))
        return {"state": "installed", "active_version": "v0.31.2"}

    def uninstall(self) -> dict[str, Any]:
        self.calls.append(("uninstall", None))
        return {"state": "not_installed", "installed": False}

    def start_async(self, *, admission_id: str | None = None) -> dict[str, Any]:
        self.calls.append(("start", admission_id))
        return {"operation": {"kind": "start", "state": "running"}}

    def stop(self, *, expected_operation_id: str | None = None) -> dict[str, Any]:
        self.calls.append(("stop", expected_operation_id))
        return {"state": "stopped", "ready": False}

    def reconcile_indeterminate_operation(
        self,
        operation_id: str,
        admission_id: str,
    ) -> dict[str, Any]:
        self.calls.append(("reconcile", (operation_id, admission_id)))
        return {
            "state": "installed",
            "ready": False,
            "unresolved_operation": None,
        }

    def list_models(self) -> list[dict[str, Any]]:
        self.calls.append(("models", None))
        return [{"name": "qwen3:8b", "size": 5_000_000_000}]

    def pull_model_async(self, model: str, *, admission_id: str | None = None) -> dict[str, Any]:
        self.calls.append(("pull", (model, admission_id)))
        return {"operation": {"kind": "pull_model", "state": "running"}}

    def run_synchronous_operation(
        self,
        _kind: str,
        _admission_id: str,
        callback: Any,
        *,
        operation_subject: dict[str, str] | None = None,
    ) -> tuple[dict[str, Any], int]:
        self.operation_subjects.append((_kind, operation_subject))
        return callback(), 200

    def delete_model(
        self,
        model: str,
        *,
        protected_models: tuple[str, ...],
    ) -> dict[str, list[str]]:
        self.calls.append(("delete_model", (model, protected_models)))
        return {"deleted": [model], "pruned": []}

    def prune_models(
        self,
        *,
        protected_models: tuple[str, ...],
    ) -> dict[str, list[str]]:
        self.calls.append(("prune_models", protected_models))
        return {"deleted": [], "pruned": ["flinttrade/sha256-a:locked"]}

    def reset_model_digest_state(self) -> dict[str, bool]:
        self.calls.append(("reset_digests", None))
        return {"reset": True}

    def accept_model_digest(self, model: str, digest: str) -> dict[str, Any]:
        self.calls.append(("accept_digest", (model, digest)))
        return {"accepted": True, "model": model, "digest": digest}

    def shutdown(self, *, timeout: float) -> bool:
        self.calls.append(("shutdown", timeout))
        return True


class _LifecycleRuntime:
    def __init__(
        self,
        state: dict[str, Any],
        events: list[str],
        *,
        accepted_models: set[str] | None = None,
    ) -> None:
        self.state = dict(state)
        self.events = events
        self.accepted_models = {"qwen3:8b"} if accepted_models is None else set(accepted_models)

    def status(self) -> dict[str, Any]:
        return dict(self.state)

    @contextmanager
    def provider_transition_guard(self):  # type: ignore[no-untyped-def]
        yield

    def mark_provider_transition_config_mutation_started(self) -> None:
        pass

    def mark_provider_transition_mutation_resolved(self) -> None:
        pass

    def start(self, *, timeout_seconds: float = 30.0) -> dict[str, Any]:
        self.events.append(f"start:{timeout_seconds:g}")
        self.state.update({"installed": True, "ready": True, "managed_process": True})
        return dict(self.state)

    def stop(self, *, expected_operation_id: str | None = None) -> dict[str, Any]:
        self.events.append(f"stop:{expected_operation_id}" if expected_operation_id else "stop")
        self.state.update({"ready": False, "managed_process": False})
        return dict(self.state)

    def model_is_accepted(self, model: str) -> bool:
        return model in self.accepted_models


class _AuthenticatedClient(FlaskClient):
    def open(self, *args: Any, **kwargs: Any):  # type: ignore[no-untyped-def]
        headers = dict(kwargs.pop("headers", {}) or {})
        headers.setdefault("X-API-Key", "unit-local-ai-key")
        return super().open(*args, headers=headers, **kwargs)


@pytest.fixture()
def runtime_app(monkeypatch: pytest.MonkeyPatch) -> tuple[Flask, _FakeRuntime]:
    monkeypatch.setenv("FLINTTRADE_API_KEY", "unit-local-ai-key")
    app = Flask(__name__)
    app.config["TESTING"] = True
    app.test_client_class = _AuthenticatedClient
    runtime = _FakeRuntime()
    app.config["OLLAMA_RUNTIME"] = runtime
    app.register_blueprint(local_ai_bp)
    return app, runtime


def test_status_reports_the_managed_runtime(runtime_app) -> None:
    app, _runtime = runtime_app

    response = app.test_client().get("/v1/ai/local-runtime/status")

    assert response.status_code == 200
    assert response.get_json() == {
        "status": "success",
        "data": {
            "state": "not_installed",
            "ready": False,
            "repair_allowed": False,
            "repair_blocked_reason": "Runtime repair is not required.",
        },
    }


def test_runtime_controls_are_localhost_only(runtime_app) -> None:
    app, runtime = runtime_app

    response = app.test_client().post(
        "/v1/ai/local-runtime/start",
        environ_overrides={"REMOTE_ADDR": "10.0.0.9"},
    )

    assert response.status_code == 403
    assert runtime.calls == []


def test_install_requires_confirmation_and_runs_in_background(runtime_app) -> None:
    app, runtime = runtime_app
    client = app.test_client()

    refused = client.post("/v1/ai/local-runtime/install", json={})
    accepted = client.post(
        "/v1/ai/local-runtime/install",
        json={"confirmed": True, "admission_id": _ADMISSION_ID},
    )

    assert refused.status_code == 400
    assert accepted.status_code == 202
    assert accepted.get_json()["data"]["operation"]["kind"] == "install"
    assert runtime.calls == [("install", _ADMISSION_ID)]


def test_mutations_require_a_client_admission_id(runtime_app) -> None:
    app, runtime = runtime_app

    response = app.test_client().post(
        "/v1/ai/local-runtime/install",
        json={"confirmed": True},
    )

    assert response.status_code == 400
    assert response.get_json()["message"] == "admission_id is required"
    assert runtime.calls == []


def test_repair_requires_confirmation_and_runs_in_background(runtime_app) -> None:
    app, runtime = runtime_app
    runtime.repair_allowed = True
    runtime.repair_blocked_reason = None
    client = app.test_client()

    refused = client.post("/v1/ai/local-runtime/repair", json={})
    accepted = client.post(
        "/v1/ai/local-runtime/repair",
        json={"confirmed": True, "admission_id": _ADMISSION_ID},
    )

    assert refused.status_code == 400
    assert accepted.status_code == 202
    assert accepted.get_json()["data"]["operation"]["kind"] == "repair"
    assert runtime.calls == [("repair", _ADMISSION_ID)]


def test_repair_refuses_when_durable_operation_truth_is_unavailable(runtime_app) -> None:
    app, runtime = runtime_app
    runtime.repair_allowed = False
    runtime.repair_blocked_reason = (
        "Durable operation receipt truth is unavailable; runtime-file repair cannot recover it."
    )

    response = app.test_client().post(
        "/v1/ai/local-runtime/repair",
        json={"confirmed": True, "admission_id": _ADMISSION_ID},
    )

    assert response.status_code == 409
    assert "receipt truth is unavailable" in response.get_json()["message"]
    assert runtime.calls == []


def test_update_rollback_and_uninstall_require_confirmation(runtime_app) -> None:
    app, runtime = runtime_app
    client = app.test_client()

    assert client.post("/v1/ai/local-runtime/update", json={}).status_code == 400
    assert client.post("/v1/ai/local-runtime/rollback", json={}).status_code == 400
    assert client.post("/v1/ai/local-runtime/uninstall", json={}).status_code == 400

    update = client.post(
        "/v1/ai/local-runtime/update",
        json={"confirmed": True, "admission_id": _ADMISSION_ID},
    )
    rollback = client.post(
        "/v1/ai/local-runtime/rollback",
        json={"confirmed": True, "admission_id": f"adm_{'b' * 32}"},
    )
    uninstall = client.post(
        "/v1/ai/local-runtime/uninstall",
        json={"confirmed": True, "admission_id": f"adm_{'c' * 32}"},
    )

    assert update.status_code == 202
    assert update.get_json()["data"]["operation"]["kind"] == "update"
    assert rollback.status_code == 200
    assert uninstall.status_code == 200
    assert runtime.calls == [("update", _ADMISSION_ID), ("rollback", None), ("uninstall", None)]


def test_start_and_stop_control_only_the_runtime_owner(runtime_app) -> None:
    app, runtime = runtime_app
    client = app.test_client()

    start = client.post("/v1/ai/local-runtime/start", json={"admission_id": _ADMISSION_ID})
    stop = client.post("/v1/ai/local-runtime/stop")

    assert start.status_code == 202
    assert stop.status_code == 200
    assert runtime.calls == [("start", _ADMISSION_ID), ("stop", None)]


def test_stop_forwards_the_server_confirmed_operation_id(runtime_app) -> None:
    app, runtime = runtime_app
    client = app.test_client()
    operation_id = f"op_{'a' * 32}"

    response = client.post(
        "/v1/ai/local-runtime/stop",
        json={"expected_operation_id": operation_id},
    )

    assert response.status_code == 200
    assert runtime.calls == [("stop", operation_id)]


def test_indeterminate_reconciliation_requires_exact_confirmed_receipt_identity(runtime_app) -> None:
    app, runtime = runtime_app
    client = app.test_client()
    operation_id = f"op_{'a' * 32}"

    assert client.post(
        "/v1/ai/local-runtime/operations/reconcile",
        json={"operation_id": operation_id, "admission_id": _ADMISSION_ID},
    ).status_code == 400
    assert client.post(
        "/v1/ai/local-runtime/operations/reconcile",
        json={"confirmed": True, "admission_id": _ADMISSION_ID},
    ).status_code == 400
    accepted = client.post(
        "/v1/ai/local-runtime/operations/reconcile",
        json={
            "confirmed": True,
            "operation_id": operation_id,
            "admission_id": _ADMISSION_ID,
        },
    )

    assert accepted.status_code == 200
    assert accepted.get_json()["data"]["unresolved_operation"] is None
    assert runtime.calls == [("reconcile", (operation_id, _ADMISSION_ID))]


def test_model_pull_requires_an_explicit_model_and_confirmation(runtime_app) -> None:
    app, runtime = runtime_app
    client = app.test_client()

    missing_confirmation = client.post(
        "/v1/ai/local-runtime/models/pull",
        json={"model": "qwen3:8b"},
    )
    missing_model = client.post(
        "/v1/ai/local-runtime/models/pull",
        json={"confirmed": True},
    )
    accepted = client.post(
        "/v1/ai/local-runtime/models/pull",
        json={"model": "qwen3:8b", "confirmed": True, "admission_id": _ADMISSION_ID},
    )

    assert missing_confirmation.status_code == 400
    assert missing_model.status_code == 400
    assert accepted.status_code == 202
    assert runtime.calls == [("pull", ("qwen3:8b", _ADMISSION_ID))]


def test_model_delete_and_prune_are_confirmed_and_protect_configured_models(
    runtime_app,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    app, runtime = runtime_app
    client = app.test_client()
    monkeypatch.setattr(
        local_ai_routes,
        "_configured_ollama_models",
        lambda: ("flinttrade/sha256-b:locked", "qwen3:8b"),
    )

    assert client.post("/v1/ai/local-runtime/models/delete", json={"model": "other:latest"}).status_code == 400
    assert client.post("/v1/ai/local-runtime/models/prune", json={}).status_code == 400

    deleted = client.post(
        "/v1/ai/local-runtime/models/delete",
        json={"model": "other:latest", "confirmed": True, "admission_id": _ADMISSION_ID},
    )
    pruned = client.post(
        "/v1/ai/local-runtime/models/prune",
        json={"confirmed": True, "admission_id": f"adm_{'b' * 32}"},
    )

    protected = ("flinttrade/sha256-b:locked", "qwen3:8b")
    assert deleted.status_code == 200
    assert deleted.get_json()["data"] == {"deleted": ["other:latest"], "pruned": []}
    assert pruned.status_code == 200
    assert runtime.calls == [
        ("delete_model", ("other:latest", protected)),
        ("prune_models", protected),
    ]
    assert runtime.operation_subjects == [
        ("delete_model", {"model": "other:latest"}),
        ("prune_models", None),
    ]


def test_model_digest_recovery_requires_explicit_confirmation(runtime_app) -> None:
    app, runtime = runtime_app
    client = app.test_client()

    refused = client.post("/v1/ai/local-runtime/models/digests/reset", json={})
    accepted = client.post(
        "/v1/ai/local-runtime/models/digests/reset",
        json={"confirmed": True, "admission_id": _ADMISSION_ID},
    )

    assert refused.status_code == 400
    assert accepted.status_code == 200
    assert accepted.get_json()["data"] == {"reset": True}
    assert runtime.calls == [("reset_digests", None)]


def test_model_digest_acceptance_requires_the_exact_confirmed_identity(runtime_app) -> None:
    app, runtime = runtime_app
    client = app.test_client()
    digest = "b" * 64

    refused = client.post(
        "/v1/ai/local-runtime/models/digests/accept",
        json={"model": "qwen3:8b", "digest": digest},
    )
    accepted = client.post(
        "/v1/ai/local-runtime/models/digests/accept",
        json={
            "model": "qwen3:8b",
            "digest": digest,
            "confirmed": True,
            "admission_id": _ADMISSION_ID,
        },
    )

    assert refused.status_code == 400
    assert accepted.status_code == 200
    assert accepted.get_json()["data"] == {
        "accepted": True,
        "model": "qwen3:8b",
        "digest": digest,
    }
    assert runtime.calls == [("accept_digest", ("qwen3:8b", digest))]
    assert runtime.operation_subjects == [
        ("accept_model_digest", {"model": "qwen3:8b", "digest": digest}),
    ]


def test_digest_acceptance_rebinds_the_configured_source_to_the_locked_alias() -> None:
    digest = "b" * 64
    locked_alias = f"flinttrade/sha256-{digest}:locked"
    writes: list[dict[str, str]] = []

    _persist_locked_model_selection(
        {
            "accepted": True,
            "source_model": "qwen3:8b",
            "model": locked_alias,
            "digest": digest,
        },
        read_config=lambda: {"provider": "ollama", "model": "qwen3:8b"},
        persist_config=lambda payload: writes.append(payload) or {},
    )

    assert writes == [{"model": locked_alias}]


def test_models_returns_the_bounded_runtime_payload(runtime_app) -> None:
    app, runtime = runtime_app

    response = app.test_client().get("/v1/ai/local-runtime/models")

    assert response.status_code == 200
    assert response.get_json()["data"] == [{"name": "qwen3:8b", "size": 5_000_000_000}]
    assert runtime.calls == [("models", None)]


def test_runtime_conflicts_are_reported_without_internal_tracebacks(runtime_app) -> None:
    app, runtime = runtime_app

    def busy(*, admission_id: str | None = None) -> dict[str, Any]:
        assert admission_id == _ADMISSION_ID
        raise OllamaRuntimeError("another Ollama operation is already running")

    runtime.start_async = busy  # type: ignore[method-assign]

    response = app.test_client().post(
        "/v1/ai/local-runtime/start",
        json={"admission_id": _ADMISSION_ID},
    )

    assert response.status_code == 409
    assert response.get_json() == {
        "status": "error",
        "message": "another Ollama operation is already running",
    }


def test_unavailable_runtime_is_reported_fail_closed(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("FLINTTRADE_API_KEY", "unit-backend-key")
    app = Flask(__name__)
    app.config["TESTING"] = True
    app.config["OLLAMA_RUNTIME_ERROR"] = "unsupported platform: plan9/mips"
    app.register_blueprint(local_ai_bp)

    response = app.test_client().get(
        "/v1/ai/local-runtime/status",
        headers={"X-API-Key": "unit-backend-key"},
    )

    assert response.status_code == 503
    assert response.get_json()["data"]["supported"] is False


def test_runtime_control_requires_auth_even_when_no_global_key_is_configured(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("FLINTTRADE_API_KEY", raising=False)
    monkeypatch.delenv("OPENALGO_API_KEY", raising=False)
    app = Flask(__name__)
    app.config["TESTING"] = True
    runtime = _FakeRuntime()
    app.config["OLLAMA_RUNTIME"] = runtime
    app.register_blueprint(local_ai_bp)

    response = app.test_client().post("/v1/ai/local-runtime/start")

    assert response.status_code == 401
    assert runtime.calls == []


def test_openalgo_bridge_key_cannot_administer_the_managed_runtime(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("FLINTTRADE_API_KEY", raising=False)
    monkeypatch.setenv("OPENALGO_API_KEY", "bridge-only-key")
    app = Flask(__name__)
    app.config["TESTING"] = True
    runtime = _FakeRuntime()
    app.config["OLLAMA_RUNTIME"] = runtime
    app.register_blueprint(local_ai_bp)

    response = app.test_client().post(
        "/v1/ai/local-runtime/start",
        headers={"X-API-Key": "bridge-only-key"},
    )

    assert response.status_code == 401
    assert runtime.calls == []


def test_unexpected_runtime_failure_logs_only_bounded_type_and_internal_correlation(
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    secret = "runtime-exception-credential"
    correlation_id = "local_0123456789abcdef"

    class SecretFailureRuntime(_FakeRuntime):
        def status(self) -> dict[str, Any]:
            raise RuntimeError(f"transport exposed {secret}")

    monkeypatch.setenv("FLINTTRADE_API_KEY", "unit-local-ai-key")
    monkeypatch.setattr(
        local_ai_routes,
        "_new_internal_correlation_id",
        lambda: correlation_id,
        raising=False,
    )
    app = Flask(__name__)
    app.config["TESTING"] = True
    app.config["OLLAMA_RUNTIME"] = SecretFailureRuntime()
    app.register_blueprint(local_ai_bp)

    with caplog.at_level(logging.ERROR, logger="flinttrade.core.local_ai_routes"):
        response = app.test_client().get(
            "/v1/ai/local-runtime/status",
            headers={"X-API-Key": "unit-local-ai-key"},
        )

    body = response.get_json()
    assert response.status_code == 500
    assert body == {
        "status": "error",
        "message": "Managed local AI operation failed",
        "data": {"correlation_id": correlation_id},
    }
    assert secret not in str(body)
    assert secret not in caplog.text
    assert "transport exposed" not in caplog.text
    assert "RuntimeError" in caplog.text
    assert correlation_id in caplog.text
    assert all(record.exc_info is None for record in caplog.records)
    assert all(len(record.getMessage()) <= 200 for record in caplog.records)


def test_provider_transition_starts_owned_ollama_before_persisting() -> None:
    app = Flask(__name__)
    events: list[str] = []
    runtime = _LifecycleRuntime(
        {
            "installed": True,
            "ready": False,
            "managed_process": False,
            "external_process": False,
            "operation": None,
            "integrity_error": None,
        },
        events,
    )
    app.config["OLLAMA_RUNTIME"] = runtime
    current = {"provider": "openai", "host": "", "model": "gpt-4o"}

    result = persist_llm_config_with_runtime(
        app,
        {"provider": "ollama", "model": "qwen3:8b"},
        read_config=lambda: dict(current),
        resolve_secret=lambda: "",
        persist_config=lambda payload: events.append(f"persist:{payload['provider']}") or dict(payload),
    )

    assert result["provider"] == "ollama"
    assert events == ["start:30", "persist:ollama"]


@pytest.mark.parametrize("provider", ["lmstudio", "LMStudio", " lmstudio "])
def test_retired_provider_is_rejected_before_managed_runtime_transition(provider: str) -> None:
    app = Flask(__name__)
    events: list[str] = []
    runtime = _LifecycleRuntime(
        {
            "installed": True,
            "ready": True,
            "managed_process": True,
            "external_process": False,
            "operation": None,
            "integrity_error": None,
        },
        events,
    )
    runtime.status = MagicMock(wraps=runtime.status)
    runtime.start = MagicMock(wraps=runtime.start)
    runtime.stop = MagicMock(wraps=runtime.stop)
    app.config["OLLAMA_RUNTIME"] = runtime

    with pytest.raises(ValueError, match="LM Studio is retired"):
        persist_llm_config_with_runtime(
            app,
            {"provider": provider},
            read_config=lambda: {"provider": "ollama", "host": "", "model": "qwen3:8b"},
            resolve_secret=lambda: "",
            persist_config=lambda payload: events.append("persist") or dict(payload),
        )

    runtime.status.assert_not_called()
    runtime.stop.assert_not_called()
    runtime.start.assert_not_called()
    assert events == []


@pytest.mark.parametrize(
    ("previous", "payload"),
    [
        (
            {"provider": "openai", "host": "", "model": "gpt-4o"},
            {"provider": "ollama", "model": "qwen3:8b"},
        ),
        (
            {"provider": "ollama", "host": "", "model": "qwen3:8b"},
            {"provider": "openai", "model": "gpt-4o"},
        ),
    ],
)
def test_provider_transition_cannot_bypass_an_unresolved_operation(
    previous: dict[str, str],
    payload: dict[str, str],
) -> None:
    app = Flask(__name__)
    events: list[str] = []
    app.config["OLLAMA_RUNTIME"] = _LifecycleRuntime(
        {
            "installed": True,
            "ready": True,
            "managed_process": True,
            "external_process": False,
            "operation": None,
            "unresolved_operation": {
                "id": f"op_{'1' * 32}",
                "admission_id": f"adm_{'1' * 32}",
                "state": "indeterminate",
            },
            "integrity_error": None,
        },
        events,
    )

    with pytest.raises(OllamaRuntimeError, match="requires acknowledgement"):
        persist_llm_config_with_runtime(
            app,
            payload,
            read_config=lambda: dict(previous),
            resolve_secret=lambda: "",
            persist_config=lambda candidate: events.append("persist") or dict(candidate),
        )

    assert events == []


def test_provider_override_fast_path_cannot_bypass_an_unresolved_operation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("LLM_PROVIDER", "openai")
    app = Flask(__name__)
    events: list[str] = []
    app.config["OLLAMA_RUNTIME"] = _LifecycleRuntime(
        {
            "installed": True,
            "ready": True,
            "managed_process": True,
            "external_process": False,
            "operation": None,
            "unresolved_operation": {
                "id": f"op_{'1' * 32}",
                "admission_id": f"adm_{'1' * 32}",
                "state": "indeterminate",
            },
            "integrity_error": None,
        },
        events,
    )

    with pytest.raises(OllamaRuntimeError, match="requires acknowledgement"):
        persist_llm_config_with_runtime(
            app,
            {"api_key": "replacement"},
            read_config=lambda: {"provider": "ollama", "host": "", "model": "qwen3:8b"},
            read_effective_config=lambda: {"provider": "openai", "host": "", "model": "gpt-4o"},
            resolve_secret=lambda: "",
            persist_config=lambda candidate: events.append("persist") or dict(candidate),
        )

    assert events == []


def test_provider_override_fast_path_reloads_a_foreign_indeterminate_receipt(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setenv("LLM_PROVIDER", "openai")
    workspace = tmp_path / "workspace"
    stale_runtime = OllamaRuntime(workspace, probe=lambda: None)
    foreign_runtime = OllamaRuntime(workspace, probe=lambda: None)
    admission_id = f"adm_{'8' * 32}"

    def unknown_mutation() -> dict[str, bool]:
        foreign_runtime._mark_operation_mutation_started()
        raise OllamaRuntimeError("simulated post-mutation failure")

    with pytest.raises(OllamaRuntimeError, match="post-mutation failure"):
        foreign_runtime.run_synchronous_operation(
            "reset_model_digests",
            admission_id,
            unknown_mutation,
        )
    observed = stale_runtime.status()["unresolved_operation"]
    assert observed is not None
    assert observed["admission_id"] == admission_id
    app = Flask(__name__)
    app.config["OLLAMA_RUNTIME"] = stale_runtime
    events: list[str] = []

    with pytest.raises(OllamaRuntimeError, match="requires acknowledgement"):
        persist_llm_config_with_runtime(
            app,
            {"api_key": "replacement"},
            read_config=lambda: {"provider": "ollama", "host": "", "model": "qwen3:8b"},
            read_effective_config=lambda: {"provider": "openai", "host": "", "model": "gpt-4o"},
            resolve_secret=lambda: "",
            persist_config=lambda candidate: events.append("persist") or dict(candidate),
        )

    assert events == []
    assert stale_runtime.status()["unresolved_operation"]["admission_id"] == admission_id


def test_provider_override_fast_path_rejects_a_newly_corrupt_operation_journal(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setenv("LLM_PROVIDER", "openai")
    runtime = OllamaRuntime(tmp_path / "workspace", probe=lambda: None)
    runtime.runtime_root.mkdir(parents=True, exist_ok=True)
    runtime._operation_state_path().write_text("{not-json", encoding="utf-8")
    app = Flask(__name__)
    app.config["OLLAMA_RUNTIME"] = runtime
    events: list[str] = []

    with pytest.raises(OllamaRuntimeError, match="operation state is invalid"):
        persist_llm_config_with_runtime(
            app,
            {"api_key": "replacement"},
            read_config=lambda: {"provider": "ollama", "host": "", "model": "qwen3:8b"},
            read_effective_config=lambda: {"provider": "openai", "host": "", "model": "gpt-4o"},
            resolve_secret=lambda: "",
            persist_config=lambda candidate: events.append("persist") or dict(candidate),
        )

    assert events == []


def test_provider_override_fast_path_rejects_a_removed_observed_operation_journal(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setenv("LLM_PROVIDER", "openai")
    runtime = OllamaRuntime(tmp_path / "workspace", probe=lambda: None)
    runtime.run_synchronous_operation(
        "reset_model_digests",
        f"adm_{'7' * 32}",
        lambda: {"reset": True},
    )
    runtime._operation_state_path().unlink()
    app = Flask(__name__)
    app.config["OLLAMA_RUNTIME"] = runtime
    events: list[str] = []

    with pytest.raises(OllamaRuntimeError, match="operation truth is unavailable"):
        persist_llm_config_with_runtime(
            app,
            {"api_key": "replacement"},
            read_config=lambda: {"provider": "ollama", "host": "", "model": "qwen3:8b"},
            read_effective_config=lambda: {"provider": "openai", "host": "", "model": "gpt-4o"},
            resolve_secret=lambda: "",
            persist_config=lambda candidate: events.append("persist") or dict(candidate),
        )

    assert events == []
    assert "receipt journal is missing" in runtime.status()["integrity_error"]


def test_provider_config_write_failure_publishes_a_durable_indeterminate_receipt(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setenv("LLM_PROVIDER", "openai")
    runtime = OllamaRuntime(tmp_path / "workspace", probe=lambda: None)
    app = Flask(__name__)
    app.config["OLLAMA_RUNTIME"] = runtime

    with pytest.raises(RuntimeError, match="simulated ambiguous config write"):
        persist_llm_config_with_runtime(
            app,
            {"api_key": "replacement"},
            read_config=lambda: {"provider": "ollama", "host": "", "model": "qwen3:8b"},
            read_effective_config=lambda: {"provider": "openai", "host": "", "model": "gpt-4o"},
            resolve_secret=lambda: "",
            persist_config=lambda _candidate: (_ for _ in ()).throw(
                RuntimeError("simulated ambiguous config write")
            ),
        )

    status = runtime.status()
    assert status["operation"]["kind"] == "provider_transition"
    assert status["operation"]["state"] == "indeterminate"
    assert status["unresolved_operation"]["id"] == status["operation"]["id"]
    with pytest.raises(OllamaRuntimeError, match="outcome is unknown"):
        runtime.run_synchronous_operation(
            "reset_model_digests",
            f"adm_{'5' * 32}",
            lambda: pytest.fail("fresh mutation must remain blocked"),
        )


def test_provider_override_activation_write_failure_is_durably_indeterminate(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setenv("LLM_PROVIDER", "openai")
    runtime = OllamaRuntime(tmp_path / "workspace", probe=lambda: None)
    app = Flask(__name__)
    app.config["OLLAMA_RUNTIME"] = runtime

    with pytest.raises(RuntimeError, match="simulated ambiguous config write"):
        persist_llm_config_with_runtime(
            app,
            {"provider": "ollama", "model": "qwen3:8b"},
            read_config=lambda: {"provider": "openai", "host": "", "model": "gpt-4o"},
            read_effective_config=lambda: {"provider": "openai", "host": "", "model": "gpt-4o"},
            resolve_secret=lambda: "",
            persist_config=lambda _candidate: (_ for _ in ()).throw(
                RuntimeError("simulated ambiguous config write")
            ),
        )

    status = runtime.status()
    assert status["operation"]["kind"] == "provider_transition"
    assert status["operation"]["state"] == "indeterminate"
    assert status["unresolved_operation"]["id"] == status["operation"]["id"]
    with pytest.raises(OllamaRuntimeError, match="outcome is unknown"):
        runtime.run_synchronous_operation(
            "reset_model_digests",
            f"adm_{'4' * 32}",
            lambda: pytest.fail("fresh mutation must remain blocked"),
        )


def test_provider_override_fast_path_reloads_marker_created_by_another_runtime(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setenv("LLM_PROVIDER", "openai")
    workspace = tmp_path / "workspace"
    stale_runtime = OllamaRuntime(workspace, probe=lambda: None)
    writer = OllamaRuntime(workspace, probe=lambda: None)

    def unknown_mutation() -> dict[str, bool]:
        writer._mark_operation_mutation_started()
        raise OllamaRuntimeError("simulated post-mutation failure")

    with pytest.raises(OllamaRuntimeError, match="post-mutation failure"):
        writer.run_synchronous_operation(
            "reset_model_digests",
            f"adm_{'6' * 32}",
            unknown_mutation,
        )
    writer._operation_state_path().unlink()
    app = Flask(__name__)
    app.config["OLLAMA_RUNTIME"] = stale_runtime
    events: list[str] = []

    with pytest.raises(OllamaRuntimeError, match="operation truth is unavailable"):
        persist_llm_config_with_runtime(
            app,
            {"api_key": "replacement"},
            read_config=lambda: {"provider": "ollama", "host": "", "model": "qwen3:8b"},
            read_effective_config=lambda: {"provider": "openai", "host": "", "model": "gpt-4o"},
            resolve_secret=lambda: "",
            persist_config=lambda candidate: events.append("persist") or dict(candidate),
        )

    assert events == []
    assert "receipt journal is missing" in stale_runtime.status()["integrity_error"]


def test_provider_transition_holds_operation_exclusion_through_config_persistence(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setenv("LLM_PROVIDER", "openai")
    workspace = tmp_path / "workspace"
    transition_runtime = OllamaRuntime(workspace, probe=lambda: None)
    competing_runtime = OllamaRuntime(workspace, probe=lambda: None)
    app = Flask(__name__)
    app.config["OLLAMA_RUNTIME"] = transition_runtime
    attempted = threading.Event()
    mutation_ran = threading.Event()

    def compete() -> None:
        attempted.set()
        competing_runtime.run_synchronous_operation(
            "reset_model_digests",
            f"adm_{'9' * 32}",
            lambda: mutation_ran.set() or {"reset": True},
        )

    competitor: threading.Thread | None = None

    def persist(candidate: dict[str, Any]) -> dict[str, Any]:
        nonlocal competitor
        competitor = threading.Thread(target=compete)
        competitor.start()
        assert attempted.wait(timeout=2.0)
        time.sleep(0.1)
        assert mutation_ran.is_set() is False
        return dict(candidate)

    result = persist_llm_config_with_runtime(
        app,
        {"api_key": "replacement"},
        read_config=lambda: {"provider": "ollama", "host": "", "model": "qwen3:8b"},
        read_effective_config=lambda: {"provider": "openai", "host": "", "model": "gpt-4o"},
        resolve_secret=lambda: "",
        persist_config=persist,
    )

    assert competitor is not None
    competitor.join(timeout=2.0)
    assert competitor.is_alive() is False
    assert mutation_ran.is_set() is True
    assert result["api_key"] == "replacement"


def test_provider_transition_rejects_unavailable_managed_operation_truth() -> None:
    app = Flask(__name__)
    events: list[str] = []

    with pytest.raises(OllamaRuntimeError, match="operation truth is unavailable"):
        persist_llm_config_with_runtime(
            app,
            {"provider": "openai", "model": "gpt-4o"},
            read_config=lambda: {"provider": "ollama", "host": "", "model": "qwen3:8b"},
            resolve_secret=lambda: "",
            persist_config=lambda candidate: events.append("persist") or dict(candidate),
        )

    assert events == []


@pytest.mark.parametrize("model", ["", "qwen3:unaccepted"])
def test_provider_transition_requires_an_accepted_model_and_stops_a_new_runtime(model: str) -> None:
    app = Flask(__name__)
    events: list[str] = []
    app.config["OLLAMA_RUNTIME"] = _LifecycleRuntime(
        {
            "installed": True,
            "ready": False,
            "managed_process": False,
            "external_process": False,
            "operation": None,
            "integrity_error": None,
        },
        events,
        accepted_models=set(),
    )

    with pytest.raises(OllamaRuntimeError, match="accepted model"):
        persist_llm_config_with_runtime(
            app,
            {"provider": "ollama", "model": model},
            read_config=lambda: {"provider": "openai", "host": "", "model": "gpt-4o"},
            resolve_secret=lambda: "",
            persist_config=lambda payload: events.append(f"persist:{payload['provider']}") or dict(payload),
        )

    assert events == ["start:30", "stop"]


def test_current_ollama_provider_rejects_an_unaccepted_model_change() -> None:
    app = Flask(__name__)
    events: list[str] = []
    app.config["OLLAMA_RUNTIME"] = _LifecycleRuntime(
        {
            "installed": True,
            "ready": True,
            "managed_process": True,
            "external_process": False,
            "operation": None,
            "integrity_error": None,
        },
        events,
        accepted_models={"qwen3:8b"},
    )

    with pytest.raises(OllamaRuntimeError, match="accepted model"):
        persist_llm_config_with_runtime(
            app,
            {"provider": "ollama", "model": "qwen3:unaccepted"},
            read_config=lambda: {"provider": "ollama", "host": "", "model": "qwen3:8b"},
            resolve_secret=lambda: "",
            persist_config=lambda payload: events.append(f"persist:{payload['provider']}") or dict(payload),
        )

    assert events == []


def test_provider_transition_rejects_uninstalled_or_external_ollama_without_persisting() -> None:
    for state, message in (
        (
            {
                "installed": False,
                "ready": False,
                "managed_process": False,
                "external_process": False,
                "operation": None,
                "integrity_error": None,
            },
            "not installed",
        ),
        (
            {
                "installed": True,
                "ready": False,
                "managed_process": False,
                "external_process": True,
                "operation": None,
                "integrity_error": None,
            },
            "external process",
        ),
    ):
        app = Flask(__name__)
        events: list[str] = []
        app.config["OLLAMA_RUNTIME"] = _LifecycleRuntime(state, events)

        with pytest.raises(OllamaRuntimeError, match=message):
            persist_llm_config_with_runtime(
                app,
                {"provider": "ollama"},
                read_config=lambda: {"provider": "openai", "host": "", "model": "gpt-4o"},
                resolve_secret=lambda: "",
                persist_config=lambda payload: events.append(  # noqa: B023 - consumed in this iteration
                    f"persist:{payload['provider']}"
                )
                or dict(payload),
            )

        assert events == []


def test_failed_ollama_persist_stops_new_runtime_and_restores_previous_config() -> None:
    app = Flask(__name__)
    events: list[str] = []
    app.config["OLLAMA_RUNTIME"] = _LifecycleRuntime(
        {
            "installed": True,
            "ready": False,
            "managed_process": False,
            "external_process": False,
            "operation": None,
            "integrity_error": None,
        },
        events,
    )
    attempts = 0

    def persist(payload: dict[str, Any]) -> dict[str, Any]:
        nonlocal attempts
        attempts += 1
        events.append(f"persist:{payload['provider']}")
        if attempts == 1:
            raise OSError("simulated workspace failure")
        return dict(payload)

    with pytest.raises(OSError, match="simulated workspace failure"):
        persist_llm_config_with_runtime(
            app,
            {"provider": "ollama", "model": "qwen3:8b"},
            read_config=lambda: {"provider": "openai", "host": "", "model": "gpt-4o"},
            resolve_secret=lambda: "old-secret",
            persist_config=persist,
        )

    assert events == ["start:30", "persist:ollama", "stop", "persist:openai"]


def test_leaving_ollama_stops_owned_runtime_before_persist_and_restarts_on_failure() -> None:
    app = Flask(__name__)
    events: list[str] = []
    app.config["OLLAMA_RUNTIME"] = _LifecycleRuntime(
        {
            "installed": True,
            "ready": True,
            "managed_process": True,
            "external_process": False,
            "operation": None,
            "integrity_error": None,
        },
        events,
    )
    attempts = 0

    def persist(payload: dict[str, Any]) -> dict[str, Any]:
        nonlocal attempts
        attempts += 1
        events.append(f"persist:{payload['provider']}")
        if attempts == 1:
            raise OSError("simulated workspace failure")
        return dict(payload)

    with pytest.raises(OSError, match="simulated workspace failure"):
        persist_llm_config_with_runtime(
            app,
            {"provider": "openai"},
            read_config=lambda: {"provider": "ollama", "host": "http://127.0.0.1:11434", "model": "qwen3:8b"},
            resolve_secret=lambda: "",
            persist_config=persist,
        )

    assert events == ["stop", "persist:openai", "persist:ollama", "start:30"]


def test_leaving_ollama_never_restarts_after_a_rollback_cas_conflict() -> None:
    app = Flask(__name__)
    events: list[str] = []
    app.config["OLLAMA_RUNTIME"] = _LifecycleRuntime(
        {
            "installed": True,
            "ready": True,
            "managed_process": True,
            "external_process": False,
            "operation": None,
            "integrity_error": None,
        },
        events,
    )

    def persist(payload: dict[str, Any]) -> dict[str, Any]:
        events.append(f"persist:{payload['provider']}")
        raise LLMConfigConflictError("simulated concurrent config change")

    with pytest.raises(OllamaRuntimeError, match="rollback could not be proven"):
        persist_llm_config_with_runtime(
            app,
            {"provider": "openai"},
            read_config=lambda: {"provider": "ollama", "host": "", "model": "qwen3:8b"},
            resolve_secret=lambda: "",
            persist_config=persist,
        )

    assert events == ["stop", "persist:openai", "persist:ollama"]


def test_leaving_ollama_never_restarts_when_a_fresh_snapshot_selects_custom() -> None:
    app = Flask(__name__)
    events: list[str] = []
    app.config["OLLAMA_RUNTIME"] = _LifecycleRuntime(
        {
            "installed": True,
            "ready": True,
            "managed_process": True,
            "external_process": False,
            "operation": None,
            "integrity_error": None,
        },
        events,
    )
    attempts = 0

    def persist(payload: dict[str, Any]) -> dict[str, Any]:
        nonlocal attempts
        attempts += 1
        events.append(f"persist:{payload['provider']}")
        if attempts == 1:
            raise OSError("simulated target persistence failure")
        return dict(payload)

    with pytest.raises(OSError, match="target persistence failure"):
        persist_llm_config_with_runtime(
            app,
            {"provider": "openai"},
            read_config=lambda: {"provider": "ollama", "host": "", "model": "qwen3:8b"},
            read_effective_config=lambda: {
                "provider": "ollama",
                "host": "",
                "model": "qwen3:8b",
                "api_key": "",
            },
            read_current_effective_config=lambda: {
                "provider": "custom",
                "host": "https://new-models.example.invalid",
                "model": "new-model",
                "api_key": "",
            },
            resolve_secret=lambda: "",
            persist_config=persist,
        )

    assert events == ["stop", "persist:openai", "persist:ollama"]


def test_leaving_ollama_never_stops_an_external_process() -> None:
    app = Flask(__name__)
    events: list[str] = []
    app.config["OLLAMA_RUNTIME"] = _LifecycleRuntime(
        {
            "installed": True,
            "ready": False,
            "managed_process": False,
            "external_process": True,
            "operation": None,
            "integrity_error": None,
        },
        events,
    )

    persist_llm_config_with_runtime(
        app,
        {"provider": "openai"},
        read_config=lambda: {"provider": "ollama", "host": "http://127.0.0.1:11434", "model": "qwen3:8b"},
        resolve_secret=lambda: "",
        persist_config=lambda payload: events.append(f"persist:{payload['provider']}") or dict(payload),
    )

    assert events == ["persist:openai"]


def test_leaving_the_default_effective_ollama_provider_stops_the_owned_runtime() -> None:
    app = Flask(__name__)
    events: list[str] = []
    app.config["OLLAMA_RUNTIME"] = _LifecycleRuntime(
        {
            "installed": True,
            "ready": True,
            "managed_process": True,
            "external_process": False,
            "operation": None,
            "integrity_error": None,
        },
        events,
    )

    persist_llm_config_with_runtime(
        app,
        {"provider": "openai"},
        read_config=lambda: {"provider": "", "host": "", "model": ""},
        read_effective_config=lambda: {
            "provider": "ollama",
            "host": "http://127.0.0.1:11434",
            "model": "",
        },
        resolve_secret=lambda: "",
        persist_config=lambda payload: events.append(f"persist:{payload['provider']}") or dict(payload),
    )

    assert events == ["stop", "persist:openai"]


def test_provider_override_keeps_effective_ollama_running_during_stored_config_changes(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("LLM_PROVIDER", "ollama")
    app = Flask(__name__)
    events: list[str] = []
    app.config["OLLAMA_RUNTIME"] = _LifecycleRuntime(
        {
            "installed": True,
            "ready": True,
            "managed_process": True,
            "external_process": False,
            "operation": None,
            "integrity_error": None,
        },
        events,
    )

    persist_llm_config_with_runtime(
        app,
        {"provider": "openai"},
        read_config=lambda: {"provider": "anthropic", "host": "", "model": ""},
        read_effective_config=lambda: {
            "provider": "ollama",
            "host": "http://127.0.0.1:11434",
            "model": "",
        },
        resolve_secret=lambda: "",
        persist_config=lambda payload: events.append(f"persist:{payload['provider']}") or dict(payload),
    )

    assert events == ["persist:openai"]


def test_boot_autostarts_an_already_installed_runtime(runtime_app) -> None:
    app, runtime = runtime_app
    runtime.status = lambda: {"installed": True, "ready": False, "operation": None}  # type: ignore[method-assign]

    started = start_configured_local_ai_runtime(app, config={"provider": "ollama"})

    assert started is True
    assert runtime.calls == [("start", None)]
    assert "OLLAMA_AUTOSTART_ERROR" not in app.config


def test_boot_refuses_a_runtime_that_requires_version_state_repair(runtime_app) -> None:
    app, runtime = runtime_app
    runtime.status = lambda: {  # type: ignore[method-assign]
        "installed": True,
        "ready": False,
        "operation": None,
        "integrity_error": "managed Ollama runtime version state is invalid",
    }

    started = start_configured_local_ai_runtime(app, config={"provider": "ollama"})

    assert started is False
    assert runtime.calls == []
    assert app.config["OLLAMA_AUTOSTART_ERROR"] == "Managed Ollama runtime requires repair"


def test_boot_never_starts_over_an_external_listener(runtime_app) -> None:
    app, runtime = runtime_app
    runtime.status = lambda: {  # type: ignore[method-assign]
        "installed": True,
        "ready": False,
        "external_process": True,
        "state": "conflict",
        "operation": None,
    }

    started = start_configured_local_ai_runtime(app, config={"provider": "ollama"})

    assert started is False
    assert runtime.calls == []
    assert app.config["OLLAMA_AUTOSTART_ERROR"] == "Managed Ollama endpoint is occupied by an external process"


def test_boot_never_downloads_a_missing_runtime(runtime_app) -> None:
    app, runtime = runtime_app

    started = start_configured_local_ai_runtime(app, config={"provider": "ollama"})

    assert started is False
    assert runtime.calls == []
    assert app.config["OLLAMA_AUTOSTART_ERROR"] == "Managed Ollama runtime is not installed"


def test_boot_leaves_runtime_stopped_for_other_providers(runtime_app) -> None:
    app, runtime = runtime_app

    started = start_configured_local_ai_runtime(app, config={"provider": "openai"})

    assert started is False
    assert runtime.calls == []


def test_shutdown_is_bounded_and_delegated_to_runtime_owner(runtime_app) -> None:
    app, runtime = runtime_app

    assert shutdown_local_ai_runtime(app, timeout=2.5) is True
    assert runtime.calls[0][0] == "shutdown"
    assert 0 < runtime.calls[0][1] <= 2.5


def test_shutdown_deadline_includes_local_transition_lock_admission(runtime_app) -> None:
    app, runtime = runtime_app
    lock_held = threading.Event()
    release_lock = threading.Event()

    def hold_lock() -> None:
        with local_ai_routes._LLM_CONFIG_TRANSITION_LOCK:
            lock_held.set()
            assert release_lock.wait(timeout=2.0)

    holder = threading.Thread(target=hold_lock)
    holder.start()
    assert lock_held.wait(timeout=2.0)
    started = time.monotonic()
    try:
        assert shutdown_local_ai_runtime(app, timeout=0.05) is False
    finally:
        release_lock.set()
        holder.join(timeout=2.0)

    assert time.monotonic() - started < 0.5
    assert holder.is_alive() is False
    assert runtime.calls == []


def test_shutdown_deadline_includes_transition_state_guard_admission(runtime_app) -> None:
    app, runtime = runtime_app
    state = local_ai_routes._runtime_transition_state(app)
    lock_held = threading.Event()

    def hold_lock() -> None:
        with state.guard:
            lock_held.set()
            time.sleep(1.0)

    holder = threading.Thread(target=hold_lock)
    holder.start()
    assert lock_held.wait(timeout=2.0)
    started = time.monotonic()
    try:
        shutdown_result = shutdown_local_ai_runtime(app, timeout=0.02)
        elapsed = time.monotonic() - started
    finally:
        holder.join(timeout=2.0)

    assert shutdown_result is False
    # Must return well before the lock holder finishes; 0.15 was too tight
    # for macOS CI scheduling while still proving the deadline is honoured.
    assert elapsed < 0.4
    assert holder.is_alive() is False
    assert runtime.calls == []


def test_shutdown_deadline_includes_transition_state_creation_admission(runtime_app) -> None:
    app, runtime = runtime_app
    app.config.pop(local_ai_routes._RUNTIME_TRANSITION_STATE_KEY, None)
    lock_held = threading.Event()

    def hold_lock() -> None:
        with local_ai_routes._RUNTIME_TRANSITION_STATE_LOCK:
            lock_held.set()
            time.sleep(1.0)

    holder = threading.Thread(target=hold_lock)
    holder.start()
    assert lock_held.wait(timeout=2.0)
    started = time.monotonic()
    try:
        shutdown_result = shutdown_local_ai_runtime(app, timeout=0.02)
        elapsed = time.monotonic() - started
    finally:
        holder.join(timeout=2.0)

    assert shutdown_result is False
    assert elapsed < 0.4
    assert holder.is_alive() is False
    assert runtime.calls == []


def test_shutdown_admission_suppresses_a_failed_transition_rollback_restart(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setenv("FLINTTRADE_WORKSPACE_DIR", str(tmp_path))
    from flinttrade_core import local_ai_routes

    events: list[str] = []
    persist_entered = threading.Event()
    release_persist = threading.Event()
    shutdown_result: list[bool] = []
    transition_errors: list[BaseException] = []
    attempts = 0

    class ShutdownRuntime(_LifecycleRuntime):
        def shutdown(self, *, timeout: float) -> bool:
            self.events.append(f"shutdown:{timeout:g}")
            self.state.update({"ready": False, "managed_process": False})
            return True

    app = Flask(__name__)
    app.config["OLLAMA_RUNTIME"] = ShutdownRuntime(
        {
            "installed": True,
            "ready": True,
            "managed_process": True,
            "external_process": False,
            "operation": None,
            "integrity_error": None,
        },
        events,
    )

    def persist(payload: dict[str, Any]) -> dict[str, Any]:
        nonlocal attempts
        attempts += 1
        events.append(f"persist:{payload['provider']}")
        if attempts == 1:
            persist_entered.set()
            assert release_persist.wait(timeout=2.0)
            raise OSError("simulated workspace failure")
        return dict(payload)

    def transition() -> None:
        try:
            persist_llm_config_with_runtime(
                app,
                {"provider": "openai"},
                read_config=lambda: {"provider": "ollama", "host": "", "model": "local"},
                resolve_secret=lambda: "",
                persist_config=persist,
            )
        except BaseException as exc:  # noqa: BLE001 - retained for the parent assertion
            transition_errors.append(exc)

    transition_thread = threading.Thread(target=transition)
    shutdown_thread = threading.Thread(
        target=lambda: shutdown_result.append(shutdown_local_ai_runtime(app, timeout=2.0))
    )
    transition_thread.start()
    assert persist_entered.wait(timeout=2.0)
    shutdown_thread.start()

    deadline = time.monotonic() + 2.0
    state = local_ai_routes._runtime_transition_state(app)
    while not state.shutdown_admitted and time.monotonic() < deadline:
        time.sleep(0.01)
    assert state.shutdown_admitted is True

    release_persist.set()
    transition_thread.join(timeout=2.0)
    shutdown_thread.join(timeout=2.0)

    assert transition_thread.is_alive() is False
    assert shutdown_thread.is_alive() is False
    assert len(transition_errors) == 1
    assert isinstance(transition_errors[0], OSError)
    assert shutdown_result == [True]
    assert events[:3] == ["stop", "persist:openai", "persist:ollama"]
    assert events[3].startswith("shutdown:")
    assert 0 < float(events[3].partition(":")[2]) <= 2.0

    with pytest.raises(OllamaRuntimeError, match="shutdown is in progress"):
        persist_llm_config_with_runtime(
            app,
            {"provider": "openai"},
            read_config=lambda: {"provider": "ollama", "host": "", "model": "local"},
            resolve_secret=lambda: "",
            persist_config=lambda payload: dict(payload),
        )


def test_full_app_registers_and_authenticates_local_runtime_routes(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setenv("FLINTTRADE_WORKSPACE_DIR", str(tmp_path))
    monkeypatch.setenv("FLINTTRADE_API_KEY", "unit-backend-key")
    master_password = tmp_path / "master_password"
    master_password.write_text("unit-test-master-password", encoding="utf-8")
    master_password.chmod(0o600)

    from flinttrade_core.app import create_flask_app

    app = create_flask_app()
    app.config["TESTING"] = True
    client = app.test_client()

    unauthorised = client.get("/v1/ai/local-runtime/status")
    authorised = client.get(
        "/v1/ai/local-runtime/status",
        headers={"X-API-Key": "unit-backend-key"},
    )

    assert unauthorised.status_code == 401
    assert authorised.status_code == 200
    assert "OLLAMA_RUNTIME" in app.config


def test_runtime_stop_cannot_race_an_ollama_provider_transition(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("FLINTTRADE_API_KEY", "unit-local-ai-key")
    app = Flask(__name__)
    app.config["TESTING"] = True
    app.test_client_class = _AuthenticatedClient
    monkeypatch_runtime = _LifecycleRuntime(
        {
            "installed": True,
            "ready": False,
            "managed_process": False,
            "external_process": False,
            "operation": None,
            "integrity_error": None,
        },
        [],
    )
    app.config["OLLAMA_RUNTIME"] = monkeypatch_runtime
    app.register_blueprint(local_ai_bp)
    entered_persist = threading.Event()
    release_persist = threading.Event()
    transition_done = threading.Event()
    stop_done = threading.Event()

    def persist(_payload: dict[str, Any]) -> dict[str, Any]:
        entered_persist.set()
        assert release_persist.wait(timeout=2.0)
        return {"provider": "ollama"}

    def transition() -> None:
        persist_llm_config_with_runtime(
            app,
            {"provider": "ollama", "model": "qwen3:8b"},
            read_config=lambda: {"provider": "openai", "host": "", "model": "gpt-4o"},
            resolve_secret=lambda: "",
            persist_config=persist,
        )
        transition_done.set()

    def stop() -> None:
        with app.test_client() as client:
            response = client.post("/v1/ai/local-runtime/stop")
        assert response.status_code == 200
        stop_done.set()

    transition_thread = threading.Thread(target=transition)
    stop_thread = threading.Thread(target=stop)
    transition_thread.start()
    assert entered_persist.wait(timeout=2.0)
    stop_thread.start()
    time.sleep(0.05)

    assert "stop" not in monkeypatch_runtime.events
    assert stop_done.is_set() is False

    release_persist.set()
    transition_thread.join(timeout=2.0)
    stop_thread.join(timeout=2.0)
    assert transition_done.is_set() is True
    assert stop_done.is_set() is True
    assert monkeypatch_runtime.events == ["start:30", "stop"]


def test_runtime_transition_blocks_a_direct_config_writer_until_runtime_state_is_committed(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setenv("FLINTTRADE_WORKSPACE_DIR", str(tmp_path))
    monkeypatch.delenv("LLM_PROVIDER", raising=False)
    from flinttrade_core.llm_config import persist_llm_config, read_effective_llm_config
    from flinttrade_core.workspace import Workspace

    persist_llm_config(
        {
            "provider": "custom",
            "host": "https://old.example.invalid",
            "model": "old-model",
            "api_key": "old-secret",
        },
        Workspace(tmp_path),
    )
    runtime_started = threading.Event()
    release_runtime = threading.Event()
    writer_completed = threading.Event()
    errors: list[BaseException] = []
    events: list[str] = []

    class BlockingRuntime(_LifecycleRuntime):
        def start(self, *, timeout_seconds: float = 30.0) -> dict[str, Any]:
            runtime_started.set()
            assert release_runtime.wait(timeout=2.0)
            return super().start(timeout_seconds=timeout_seconds)

    app = Flask(__name__)
    app.config["OLLAMA_RUNTIME"] = BlockingRuntime(
        {
            "installed": True,
            "ready": False,
            "managed_process": False,
            "external_process": False,
            "operation": None,
            "integrity_error": None,
        },
        events,
        accepted_models={"local-model"},
    )

    def transition() -> None:
        try:
            persist_llm_config_with_runtime(app, {"provider": "ollama", "model": "local-model"})
        except BaseException as exc:  # noqa: BLE001 - retained for assertion in the parent
            errors.append(exc)

    def writer() -> None:
        try:
            persist_llm_config(
                {
                    "provider": "custom",
                    "host": "https://new.example.invalid",
                    "model": "new-model",
                    "api_key": "new-secret",
                },
                Workspace(tmp_path),
            )
            writer_completed.set()
        except BaseException as exc:  # noqa: BLE001 - retained for assertion in the parent
            errors.append(exc)

    transition_thread = threading.Thread(target=transition)
    writer_thread = threading.Thread(target=writer)
    transition_thread.start()
    assert runtime_started.wait(timeout=2.0)
    writer_thread.start()
    time.sleep(0.1)

    assert writer_completed.is_set() is False

    release_runtime.set()
    transition_thread.join(timeout=2.0)
    writer_thread.join(timeout=2.0)

    assert transition_thread.is_alive() is False
    assert writer_thread.is_alive() is False
    assert errors == []
    assert read_effective_llm_config(Workspace(tmp_path)) == {
        "provider": "custom",
        "host": "https://new.example.invalid",
        "model": "new-model",
        "api_key": "new-secret",
    }
