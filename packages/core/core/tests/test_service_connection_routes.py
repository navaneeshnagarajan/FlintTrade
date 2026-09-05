"""Authenticated inert service-connection HTTP and observability contracts."""

from __future__ import annotations

import asyncio
import builtins
import importlib
import json
import logging
import os
import subprocess
import sys
from contextlib import ExitStack
from pathlib import Path
from unittest.mock import MagicMock, patch
from uuid import uuid4

import httpx
import pytest
from flask import Flask, Response
from flask_limiter import Limiter
from werkzeug.datastructures import Headers

from flinttrade_core.llm_provider_profiles import LLM_PROVIDER_PROFILES
from flinttrade_core.service_connection_store import ConnectionMutationResult, ServiceConnectionStore


FULL_SCOPES = ("admin.services.read", "admin.services.write")
CREATE_PAYLOAD = {
    "provider_id": "llm:openai",
    "label": "Primary",
    "auth_mode": "api_key",
    "credential": "synthetic-secret",
}


class RecordingAudit:
    def __init__(self, *, acknowledgement: str | None = None, fail_attempts: bool = False) -> None:
        self.acknowledgement = acknowledgement
        self.fail_attempts = fail_attempts
        self.attempts: list[tuple[str, dict[str, object]]] = []
        self.domain: list[tuple[str, str, dict[str, object]]] = []

    def log_event(self, event_type: str, **fields: object) -> str:
        if self.fail_attempts:
            raise RuntimeError("synthetic audit failure")
        self.attempts.append((event_type, fields))
        return "synthetic-record-hash"

    def log_idempotent_event(self, event_type: str, *, event_id: str, fields: dict[str, object]) -> str:
        self.domain.append((event_type, event_id, fields))
        return event_id if self.acknowledgement is None else self.acknowledgement


def _run_service_connection_import_probe(tmp_path: Path, mode: str) -> subprocess.CompletedProcess[str]:
    environment = os.environ.copy()
    environment["FLINTTRADE_WORKSPACE_DIR"] = str(tmp_path)
    provider_credentials = sorted(profile.api_key_env for profile in LLM_PROVIDER_PROFILES if profile.api_key_env)
    environment["FLINTTRADE_TEST_PROVIDER_CREDENTIAL_NAMES"] = json.dumps(provider_credentials)
    for name in provider_credentials:
        environment.pop(name, None)
    return subprocess.run(
        [sys.executable, "-B", str(Path(__file__).with_name("service_connection_import_probe.py")), mode],
        cwd=Path.cwd(),
        env=environment,
        text=True,
        capture_output=True,
        check=False,
    )


def test_service_connection_import_probe_detects_caught_forbidden_attempts(tmp_path):
    observations = {
        mode: _run_service_connection_import_probe(tmp_path / mode, mode)
        for mode in ("caught-transport", "caught-environment-index", "caught-named")
    }

    assert observations["caught-transport"].returncode != 0
    assert json.loads(observations["caught-transport"].stdout)["attempts"] == ["httpx.get"]
    assert observations["caught-environment-index"].returncode != 0
    assert json.loads(observations["caught-environment-index"].stdout)["attempts"] == [
        "os.environ.__getitem__:HERMES_API_KEY"
    ]
    assert observations["caught-named"].returncode != 0
    assert json.loads(observations["caught-named"].stdout)["attempts"] == [
        "flinttrade_ai.llm_client.LLMClient"
    ]


def test_service_connection_imports_are_inert_under_transport_and_credential_poison(tmp_path):
    result = _run_service_connection_import_probe(tmp_path, "clean")

    assert result.returncode == 0, result.stderr
    observation = json.loads(result.stdout)
    assert observation["attempts"] == []
    assert observation["named_guards"] == [
        "flinttrade_ai.llm_client.LLMClient",
        "flinttrade_ai.llm_client.LLMConfig.from_env",
        "flinttrade_core.ollama_runtime.OllamaRuntime.start",
        "flinttrade_core.ollama_runtime.OllamaRuntime.start_async",
        "flinttrade_ai.agent_backends.codex_session.CodexAppServerSession.ensure_started",
        "flinttrade_ai.agent_backends.hermes_session.HermesACPSession.ensure_started",
        "flinttrade_gateway.adapter.load_broker_adapter",
        "flinttrade_gateway.session.load_broker_adapter",
        "flinttrade_gateway.registry.BrokerRegistry",
        "flinttrade_gateway.credentials.CredentialStore",
        "flinttrade_gateway.contracts.ContractManager",
    ]


@pytest.mark.parametrize(
    "method,path,want",
    [
        ("POST", "/v1/services/connections", "/v1/services/connections"),
        ("TRACE", "/ft-api/v1/services/connections/not-a-uuid/extra", "/v1/services/connections/{connection_id}"),
        ("POST", "/v1/accounts/operator/reconnect", "/v1/accounts/{account_id}/reconnect"),
        ("GET", "/v1/auth/oauth/callback?code=private", "/v1/auth/oauth/callback"),
        ("POST", "/v1/auth/otp/verify", "/v1/auth/otp/verify"),
        ("POST", "/api/v1/native/accounts/dhan/operator/login", "/api/v1/native/accounts/{adapter_id}/{account_id}/login"),
        ("GET", "/ft-api/api/v1/native/oauth/callback?code=private", "/api/v1/native/oauth/callback"),
        ("POST", "/v1/auth/setup/regenerate-2fa", "/v1/auth/setup/regenerate-2fa"),
        ("POST", "/v1/auth/reset-password-otp", "/v1/auth/reset-password-otp"),
        ("POST", "/v1/config/llm", "/v1/config/llm"),
        ("POST", "/v1/config/openalgo", "/v1/config/openalgo"),
        ("POST", "/v1/test-connection", "/v1/test-connection"),
    ],
)
def test_secret_envelope_classifier_returns_fixed_templates_for_untrusted_paths(method, path, want):
    """Catch malformed or external secret routes escaping into body-aware sinks."""
    module = importlib.import_module("flinttrade_core.request_observability") if importlib.util.find_spec(
        "flinttrade_core.request_observability"
    ) else None
    classify = getattr(module, "classify_secret_envelope", lambda method, path: None)
    assert classify(method, path) == want


@pytest.mark.parametrize(
    "path",
    [
        "/v1/services/connection",
        "/v1/accounts-extra/operator/reconnect",
        "/v1/auth/status",
        "/v1/config/llm-extra",
        "/api/v1/native/account",
    ],
)
def test_secret_envelope_classifier_leaves_lookalike_non_secret_routes_useful(path):
    """Catch prefix matching that suppresses diagnostics for unrelated siblings."""
    module = importlib.import_module("flinttrade_core.request_observability") if importlib.util.find_spec(
        "flinttrade_core.request_observability"
    ) else None
    classify = getattr(module, "classify_secret_envelope", lambda method, path: None)
    assert classify("POST", path) is None


def _unit_app(
    workspace: Path,
    monkeypatch: pytest.MonkeyPatch,
    *,
    scopes: tuple[str, ...] = FULL_SCOPES,
    audit: RecordingAudit | None = None,
) -> Flask:
    app = Flask(__name__)
    app.config["TESTING"] = True
    monkeypatch.setenv("FLINTTRADE_API_KEY", "synthetic-read-key")
    if importlib.util.find_spec("flinttrade_core.service_connection_routes"):
        routes = importlib.import_module("flinttrade_core.service_connection_routes")
        app.config["AUDIT_LOGGER"] = audit
        sink = routes.build_connection_audit_sink(audit)
        app.config["SERVICE_CONNECTION_STORE"] = ServiceConnectionStore(workspace, audit_sink=sink)
        principal = routes.VerifiedOperatorSession(
            "operator:" + "a" * 64,
            "session:" + "b" * 64,
            scopes,
        )

        def verify(token: str):
            if token == "synthetic.session.jwt":
                return principal
            raise routes._OperatorSessionVerificationError("invalid")

        monkeypatch.setattr(routes, "verify_operator_session_token", verify)
        app.register_blueprint(routes.service_connection_bp)
        app.before_request(routes.guard_service_connection_family)
        app.after_request(routes.apply_service_connection_cache_policy)
    return app


def test_collection_read_accepts_loopback_api_key_and_returns_empty_snapshot(tmp_path, monkeypatch):
    """Prove the read surface requires explicit proof and exposes the collection ETag."""
    app = _unit_app(tmp_path / "workspace", monkeypatch)

    response = app.test_client().get(
        "/v1/services/connections",
        headers={"X-API-Key": "synthetic-read-key"},
        environ_base={"REMOTE_ADDR": "127.0.0.1"},
    )

    assert response.status_code == 200
    assert response.get_json() == {"connections": []}
    assert response.headers["ETag"].startswith('"')
    assert response.headers["Cache-Control"] == "no-store"
    assert response.headers["Pragma"] == "no-cache"


def _session_headers(etag: str | None = None, key: str | None = None) -> dict[str, str]:
    headers = {"Authorization": "Bearer synthetic.session.jwt"}
    if etag is not None:
        headers["If-Match"] = etag
    if key is not None:
        headers["Idempotency-Key"] = key
    return headers


def test_crud_is_inert_public_and_idempotent_across_reopened_store(tmp_path, monkeypatch):
    """Exercise the public CRUD contract without calling a provider or exposing a credential."""
    workspace = tmp_path / "workspace"
    app = _unit_app(workspace, monkeypatch)
    client = app.test_client()
    initial = client.get("/v1/services/connections", headers=_session_headers())
    create_key = str(uuid4())

    created = client.post(
        "/v1/services/connections",
        json=CREATE_PAYLOAD,
        headers=_session_headers(initial.headers["ETag"], create_key),
    )

    assert created.status_code == 201
    assert created.get_json()["credential_configured"] is True
    assert "credential" not in created.get_json()
    connection_id = created.get_json()["connection_id"]
    app.config["SERVICE_CONNECTION_STORE"] = ServiceConnectionStore(workspace)
    replay = client.post(
        "/v1/services/connections",
        json=CREATE_PAYLOAD,
        headers=_session_headers(initial.headers["ETag"], create_key),
    )
    assert (replay.status_code, replay.get_json(), replay.headers["ETag"]) == (
        created.status_code,
        created.get_json(),
        created.headers["ETag"],
    )

    item = client.get(f"/v1/services/connections/{connection_id}", headers=_session_headers())
    assert item.status_code == 200
    assert item.get_json() == created.get_json()

    patch_key = str(uuid4())
    patch_headers = _session_headers(created.headers["ETag"], patch_key)
    patched = client.patch(
        f"/v1/services/connections/{connection_id}",
        json={"label": "Renamed", "credential": "replacement"},
        headers=patch_headers,
    )
    assert patched.status_code == 200
    assert patched.get_json()["label"] == "Renamed"
    assert "credential" not in patched.get_json()
    patched_epoch = app.config["SERVICE_CONNECTION_STORE"].read_snapshot().epoch
    app.config["SERVICE_CONNECTION_STORE"] = ServiceConnectionStore(workspace)
    patch_replay = client.patch(
        f"/v1/services/connections/{connection_id}",
        json={"label": "Renamed", "credential": "replacement"},
        headers=patch_headers,
    )
    assert (patch_replay.status_code, patch_replay.get_json(), patch_replay.headers["ETag"]) == (
        patched.status_code,
        patched.get_json(),
        patched.headers["ETag"],
    )
    assert app.config["SERVICE_CONNECTION_STORE"].read_snapshot().epoch == patched_epoch

    delete_key = str(uuid4())
    delete_headers = _session_headers(patched.headers["ETag"], delete_key)
    deleted = client.delete(
        f"/v1/services/connections/{connection_id}",
        json={},
        headers=delete_headers,
    )
    assert deleted.status_code == 200
    assert deleted.get_json() == {"deleted": True}
    deleted_epoch = app.config["SERVICE_CONNECTION_STORE"].read_snapshot().epoch
    app.config["SERVICE_CONNECTION_STORE"] = ServiceConnectionStore(workspace)
    delete_replay = client.delete(
        f"/v1/services/connections/{connection_id}",
        json={},
        headers=delete_headers,
    )
    assert (delete_replay.status_code, delete_replay.get_json(), delete_replay.headers["ETag"]) == (
        deleted.status_code,
        deleted.get_json(),
        deleted.headers["ETag"],
    )
    assert app.config["SERVICE_CONNECTION_STORE"].read_snapshot().epoch == deleted_epoch
    assert client.get(f"/v1/services/connections/{connection_id}", headers=_session_headers()).status_code == 404


@pytest.mark.parametrize(
    "headers,status,error",
    [
        ({}, 401, "authentication_required"),
        ({"X-API-Key": "wrong"}, 401, "authentication_required"),
        ({"X-API-Key": "synthetic-read-key"}, 403, "forbidden"),
        (
            {"Authorization": "Bearer wrong", "X-API-Key": "synthetic-read-key"},
            401,
            "authentication_required",
        ),
    ],
)
def test_mutation_proof_failures_are_closed(headers, status, error, tmp_path, monkeypatch):
    """Catch absent, invalid, read-only and competing-key proof escalation."""
    app = _unit_app(tmp_path / "workspace", monkeypatch)
    response = app.test_client().post("/v1/services/connections", json=CREATE_PAYLOAD, headers=headers)
    assert response.status_code == status
    assert response.get_json() == {"error": error}


def test_remote_peer_is_rejected_before_presented_proof(tmp_path, monkeypatch):
    app = _unit_app(tmp_path / "workspace", monkeypatch)
    response = app.test_client().get(
        "/v1/services/connections",
        headers=_session_headers(),
        environ_base={"REMOTE_ADDR": "198.51.100.9"},
    )
    assert response.status_code == 403
    assert response.get_json() == {"error": "forbidden"}


def test_narrowed_full_session_does_not_gain_connection_scope(tmp_path, monkeypatch):
    app = _unit_app(tmp_path / "workspace", monkeypatch, scopes=("admin.audit.read",))
    response = app.test_client().get("/v1/services/connections", headers=_session_headers())
    assert response.status_code == 403
    assert response.get_json() == {"error": "forbidden"}


def test_rejected_attempt_export_is_ref_free_and_never_changes_response(tmp_path, monkeypatch):
    audit = RecordingAudit()
    app = _unit_app(tmp_path / "workspace", monkeypatch, audit=audit)

    response = app.test_client().post("/v1/services/connections", json=CREATE_PAYLOAD)

    assert response.status_code == 401
    assert audit.attempts == [
        (
            "SERVICE_CONNECTION_ROUTE_ATTEMPT",
            {
                "route_template": "/ft-api/v1/services/connections",
                "method": "POST",
                "authentication_class": "anonymous",
                "outcome": "rejected",
                "actor": None,
                "connection_ref": None,
            },
        )
    ]


def test_attempt_sink_failure_preserves_closed_rejection(tmp_path, monkeypatch, caplog):
    audit = RecordingAudit(fail_attempts=True)
    app = _unit_app(tmp_path / "workspace", monkeypatch, audit=audit)

    response = app.test_client().post("/v1/services/connections", json=CREATE_PAYLOAD)

    assert response.status_code == 401
    assert response.get_json() == {"error": "authentication_required"}
    assert "Service-connection route-attempt audit unavailable" in caplog.text
    assert "synthetic audit failure" not in caplog.text


def test_domain_audit_requires_exact_stable_id_ack_and_retains_outbox_on_mismatch(tmp_path, monkeypatch):
    audit = RecordingAudit(acknowledgement="wrong")
    workspace = tmp_path / "workspace"
    app = _unit_app(workspace, monkeypatch, audit=audit)
    initial = app.test_client().get("/v1/services/connections", headers=_session_headers())

    response = app.test_client().post(
        "/v1/services/connections",
        json=CREATE_PAYLOAD,
        headers=_session_headers(initial.headers["ETag"], str(uuid4())),
    )

    assert response.status_code == 201
    assert len({event_id for _, event_id, _ in audit.domain}) == 2
    assert all("event_id" not in fields for _, _, fields in audit.domain)
    assert audit.attempts == []
    outbox = workspace / "service-connections-state" / "outbox"
    assert len(list(outbox.glob("*.json"))) == 2


def test_real_app_composition_is_lazy_inert_and_cors_bounded(tmp_path, monkeypatch):
    """Exercise actual wiring while transports, brokers and launchers are poisoned."""
    monkeypatch.setenv("FLINTTRADE_WORKSPACE_DIR", str(tmp_path))
    monkeypatch.setenv("FLINTTRADE_API_KEY", "synthetic-read-key")
    monkeypatch.setenv("GLITCHTIP_DSN", "https://public@example.invalid/1")
    monkeypatch.setenv("ENABLE_ANALYZER", "true")
    monkeypatch.setenv("TRUST_PROXY_HEADERS", "true")
    from flinttrade_core import service_connection_routes as routes
    from flinttrade_core import app as app_module
    from flinttrade_core.app import create_flask_app
    from flinttrade_core.request_observability import (
        SafeRequestSummary,
        reset_safe_request_summary,
        set_safe_request_summary,
    )
    from flinttrade_core.service_providers import ServiceProviderCatalogue

    safety = MagicMock(order_reservations_durable=True)
    registry = MagicMock()
    credentials = MagicMock()
    credentials.list_accounts.return_value = []
    contract_manager = MagicMock()
    injected = ServiceConnectionStore(tmp_path)
    audit = RecordingAudit()
    sentry_options: dict[str, object] = {}
    environment_get = os.environ.get
    environment_getitem = type(os.environ).__getitem__
    forbidden_provider_environment_reads: list[str] = []
    provider_credentials = frozenset(
        profile.api_key_env for profile in LLM_PROVIDER_PROFILES if profile.api_key_env
    )

    def guarded_environment_get(name, default=None):
        if name in provider_credentials:
            forbidden_provider_environment_reads.append(name)
            raise AssertionError("provider environment credential")
        return environment_get(name, default)

    def guarded_environment_getitem(environ, name):
        if name in provider_credentials:
            forbidden_provider_environment_reads.append(name)
            raise AssertionError("provider environment credential")
        return environment_getitem(environ, name)

    with ExitStack() as poisons:
        poisons.enter_context(patch.object(os.environ, "get", side_effect=guarded_environment_get))
        poisons.enter_context(patch.object(type(os.environ), "__getitem__", guarded_environment_getitem))
        forbidden_seams = (
            poisons.enter_context(patch.object(httpx, "get", side_effect=AssertionError("HTTP transport"))),
            poisons.enter_context(patch.object(httpx, "post", side_effect=AssertionError("HTTP transport"))),
            poisons.enter_context(patch.object(httpx.Client, "get", side_effect=AssertionError("HTTP transport"))),
            poisons.enter_context(patch.object(httpx.Client, "post", side_effect=AssertionError("HTTP transport"))),
            poisons.enter_context(patch.object(subprocess, "Popen", side_effect=AssertionError("subprocess launcher"))),
            poisons.enter_context(patch.object(subprocess, "run", side_effect=AssertionError("subprocess launcher"))),
            poisons.enter_context(
                patch.object(
                    asyncio,
                    "create_subprocess_exec",
                    side_effect=AssertionError("async subprocess launcher"),
                )
            ),
            poisons.enter_context(patch("socket.socket.connect", side_effect=AssertionError("socket transport"))),
            poisons.enter_context(
                patch("flinttrade_ai.llm_client.LLMClient", side_effect=AssertionError("LLM client"))
            ),
            poisons.enter_context(
                patch(
                    "flinttrade_ai.llm_client.LLMConfig.from_env",
                    side_effect=AssertionError("provider credential read"),
                )
            ),
            poisons.enter_context(
                patch(
                    "flinttrade_core.ollama_runtime.OllamaRuntime.start",
                    side_effect=AssertionError("Ollama launcher"),
                )
            ),
            poisons.enter_context(
                patch(
                    "flinttrade_core.ollama_runtime.OllamaRuntime.start_async",
                    side_effect=AssertionError("Ollama launcher"),
                )
            ),
            poisons.enter_context(
                patch(
                    "flinttrade_ai.agent_backends.codex_session.CodexAppServerSession.ensure_started",
                    side_effect=AssertionError("Codex launcher"),
                )
            ),
            poisons.enter_context(
                patch(
                    "flinttrade_ai.agent_backends.hermes_session.HermesACPSession.ensure_started",
                    side_effect=AssertionError("Hermes launcher"),
                )
            ),
            poisons.enter_context(
                patch(
                    "flinttrade_gateway.adapter.load_broker_adapter",
                    side_effect=AssertionError("broker factory"),
                )
            ),
            poisons.enter_context(
                patch(
                    "flinttrade_gateway.session.load_broker_adapter",
                    side_effect=AssertionError("gateway constructor"),
                )
            ),
            poisons.enter_context(
                patch.object(app_module, "BrokerRegistry", side_effect=AssertionError("broker registry"))
            ),
            poisons.enter_context(
                patch.object(app_module, "CredentialStore", side_effect=AssertionError("credential store"))
            ),
            poisons.enter_context(
                patch.object(app_module, "ContractManager", side_effect=AssertionError("contract manager"))
            ),
        )
        poisons.enter_context(patch.object(app_module, "_open_ditto_credential_store", return_value=None))
        poisons.enter_context(
            patch.object(app_module.sentry_sdk, "init", side_effect=lambda **options: sentry_options.update(options))
        )
        app = create_flask_app(
            safety=safety,
            audit=audit,
            registry=registry,
            credential_store=credentials,
            contract_manager=contract_manager,
            service_provider_catalogue=ServiceProviderCatalogue(()),
            service_connection_store=injected,
        )
        app.config["TESTING"] = True

        def unhandled_secret_failure():
            raise RuntimeError("credential must never reach diagnostics")

        app.add_url_rule(
            "/v1/services/connections/unhandled",
            "test_unhandled_secret_failure",
            unhandled_secret_failure,
            methods=["POST"],
        )
        app.add_url_rule(
            "/v1/observability-control",
            "test_observability_control",
            lambda: ({"status": "ok"}, 200),
            methods=["POST"],
        )

        def iteration_failure():
            def chunks():
                yield b"first"
                raise RuntimeError("synthetic iteration failure")

            return Response(chunks())

        class CloseFailureBody:
            def __iter__(self):
                yield b"only"

            def close(self):
                raise RuntimeError("synthetic close failure")

        app.add_url_rule(
            "/v1/services/connections/iteration-failure",
            "test_secret_iteration_failure",
            iteration_failure,
        )
        app.add_url_rule(
            "/v1/services/connections/close-failure",
            "test_secret_close_failure",
            lambda: Response(CloseFailureBody()),
        )
        app.add_url_rule(
            "/ordinary-iteration-failure",
            "test_ordinary_iteration_failure",
            iteration_failure,
        )
        app.add_url_rule(
            "/v1/services/connections/probe",
            "test_service_connection_observability_probe",
            lambda: ({"status": "ok"}, 200),
        )
        assert app.config["SERVICE_CONNECTION_STORE"] is injected
        app.config["SERVICE_CONNECTION_STORE"] = None
        assert not (tmp_path / "service-connections-state").exists()

        client = app.test_client()
        response = client.get(
            "/v1/services/connections",
            headers={"X-API-Key": "synthetic-read-key"},
        )
        assert response.status_code == 200
        assert type(app.config["SERVICE_CONNECTION_STORE"]) is ServiceConnectionStore
        assert app.config["SERVICE_CONNECTION_STORE"].audit_sink is not None
        from flinttrade_core.auth_routes import _create_token

        actual_token = _create_token("synthetic-operator")
        actual_session = client.get(
            "/v1/services/connections",
            headers={"Authorization": f"Bearer {actual_token}", "X-API-Key": "competing-wrong-key"},
        )
        forwarded_loopback = client.get(
            "/v1/services/connections",
            headers={
                "Authorization": f"Bearer {actual_token}",
                "X-API-Key": "synthetic-read-key",
                "X-Forwarded-For": "127.0.0.1",
            },
            environ_overrides={"REMOTE_ADDR": "198.51.100.8"},
        )
        assert actual_session.status_code == 200
        assert forwarded_loopback.status_code == 403
        assert forwarded_loopback.get_json() == {"error": "forbidden"}
        mutation_headers = _session_headers(response.headers["ETag"], str(uuid4()))
        mutation_headers["Authorization"] = f"Bearer {actual_token}"
        created = client.post(
            "/v1/services/connections",
            json=CREATE_PAYLOAD,
            headers=mutation_headers,
        )
        connection_id = created.get_json()["connection_id"]
        patched = client.patch(
            f"/v1/services/connections/{connection_id}",
            json={"label": "Poisoned CRUD"},
            headers={
                **_session_headers(created.headers["ETag"], str(uuid4())),
                "Authorization": f"Bearer {actual_token}",
            },
        )
        deleted = client.delete(
            f"/v1/services/connections/{connection_id}",
            json={},
            headers={
                **_session_headers(patched.headers["ETag"], str(uuid4())),
                "Authorization": f"Bearer {actual_token}",
            },
        )
        assert (created.status_code, patched.status_code, deleted.status_code) == (201, 200, 200)
        assert forbidden_provider_environment_reads == []
        for forbidden_seam in forbidden_seams:
            forbidden_seam.assert_not_called()

        allowed = client.options(
            "/v1/services/connections/invalid",
            headers={
                "Origin": "http://127.0.0.1:5173",
                "Access-Control-Request-Method": "PATCH",
                "Access-Control-Request-Headers": "Content-Type,If-Match,Idempotency-Key",
            },
        )
        foreign = client.options(
            "/v1/services/connections",
            headers={"Origin": "https://foreign.invalid", "Access-Control-Request-Method": "PATCH"},
        )
        forbidden = client.options(
            "/v1/services/connections",
            headers={
                "Origin": "http://127.0.0.1:5173",
                "Access-Control-Request-Method": "CONNECT",
                "Access-Control-Request-Headers": "X-Forbidden",
            },
        )
        principal = routes.VerifiedOperatorSession(
            "operator:" + "c" * 64,
            "session:" + "d" * 64,
            FULL_SCOPES,
        )
        monkeypatch.setattr(routes, "verify_operator_session_token", lambda _token: principal)
        secret_failure = client.post(
            "/v1/services/connections/unhandled",
            json={"opaque": {"arbitrary": "private-value"}, "credential": "synthetic-secret"},
            headers=_session_headers(),
        )
        ordinary = client.post(
            "/v1/observability-control",
            json={"note": "useful"},
            headers={"X-API-Key": "synthetic-read-key"},
        )

    assert allowed.headers["Access-Control-Allow-Origin"] == "http://127.0.0.1:5173"
    assert "PATCH" in allowed.headers["Access-Control-Allow-Methods"]
    assert {"Content-Type", "If-Match", "Idempotency-Key"} <= set(
        allowed.headers["Access-Control-Allow-Headers"].split(", ")
    )
    assert "ETag" in allowed.headers["Access-Control-Expose-Headers"]
    assert "Access-Control-Allow-Origin" not in foreign.headers
    assert "Access-Control-Allow-Methods" not in forbidden.headers
    assert "Access-Control-Allow-Headers" not in forbidden.headers
    assert secret_failure.status_code == 500
    assert ordinary.status_code == 200
    error = app.config["ERROR_LOG"].recent(limit=1)[0]
    assert error["route"] == "/v1/services/connections/{connection_id}"
    assert error["request_body"] == {
        "route_template": "/v1/services/connections/{connection_id}",
        "method": "POST",
        "content_length": 76,
        "has_credentials": True,
    }
    assert error["error_class"] is None
    assert error["error_message"] is None
    calls = app.config["API_ANALYZER"].recent(limit=20)
    secret_call = next(call for call in calls if call["route"] == "/v1/services/connections/{connection_id}")
    ordinary_call = next(call for call in calls if call["route"] == "/v1/observability-control")
    assert secret_call["request_body"] == error["request_body"]
    assert secret_call["response_body"] is None
    assert ordinary_call["request_body"] == {"note": "useful"}
    assert sentry_options["max_request_body_size"] == "never"
    assert sentry_options["include_local_variables"] is False
    assert sentry_options["send_default_pii"] is False
    token = set_safe_request_summary(
        SafeRequestSummary("/v1/services/connections", "POST", 1, True)
    )
    try:
        assert sentry_options["before_send"]({"event": "private"}, {}) is None
        assert sentry_options["before_send_transaction"]({"transaction": "private"}, {}) is None
        assert sentry_options["traces_sampler"]({}) == 0.0
    finally:
        reset_safe_request_summary(token)
    assert sentry_options["before_send"]({"event": "ordinary"}, {}) == {"event": "ordinary"}
    assert sentry_options["traces_sampler"]({}) == 0.1
    assert sentry_options["traces_sampler"]({
        "wsgi_environ": {"REQUEST_METHOD": "POST", "PATH_INFO": "/ft-api/v1/services/connections/bad"}
    }) == 0.0

    from sentry_sdk.integrations import wsgi as sentry_wsgi
    from sentry_sdk.integrations.wsgi import SentryWsgiMiddleware
    from werkzeug.test import EnvironBuilder
    from flinttrade_core.request_observability import current_safe_request_summary

    middleware = SentryWsgiMiddleware(app.wsgi_app)
    captured_path = ""
    captures: list[tuple[str, bool, object, object]] = []

    def capture_exception():
        error = sys.exc_info()
        event = {
            "request": {
                "method": "GET",
                "url": f"http://localhost{captured_path}?code=synthetic-private-query",
            },
            "exception": {"value": str(error[1])},
        }
        captures.append(
            (
                captured_path,
                current_safe_request_summary() is not None,
                sentry_options["before_send"](event, {}),
                sentry_options["before_send_transaction"](event, {}),
            )
        )
        return error

    def start_response(_status, _headers, _exc_info=None):
        return None

    with patch.object(sentry_wsgi, "_capture_exception", side_effect=capture_exception):
        for captured_path, phase in (
            ("/v1/services/connections/iteration-failure", "iteration"),
            ("/v1/services/connections/close-failure", "close"),
            ("/ordinary-iteration-failure", "iteration"),
        ):
            environ = EnvironBuilder(
                path=captured_path,
                headers={"X-API-Key": "synthetic-read-key"},
                environ_base={"REMOTE_ADDR": "127.0.0.1"},
            ).get_environ()
            body = middleware(environ, start_response)
            if phase == "iteration":
                with pytest.raises(RuntimeError, match="iteration failure"):
                    list(body)
                body.close()
            else:
                assert list(body) == [b"only"]
                with pytest.raises(RuntimeError, match="close failure"):
                    body.close()
            assert current_safe_request_summary() is None

    assert captures[0][:2] == ("/v1/services/connections/iteration-failure", False)
    assert captures[0][2] is None
    assert captures[0][3] is None
    assert captures[1][:2] == ("/v1/services/connections/close-failure", False)
    assert captures[1][2] is None
    assert captures[1][3] is None
    assert captures[2][:2] == ("/ordinary-iteration-failure", False)
    assert captures[2][2] is not None
    assert captures[2][3] is not None

    for malformed_host, expected_sdk_url in (
        ("[", "http://[/v1/services/connections/probe"),
        ("fixture.invalid/ordinary", "http://fixture.invalid/ordinary/v1/services/connections/probe"),
        ("fixture.invalid?next=", "http://fixture.invalid?next=/v1/services/connections/probe"),
        ("fixture.invalid#ordinary", "http://fixture.invalid#ordinary/v1/services/connections/probe"),
    ):
        malformed_environ = EnvironBuilder(
            path="/v1/services/connections/probe?code=synthetic-private-query",
            headers={"X-API-Key": "synthetic-read-key"},
            environ_base={"REMOTE_ADDR": "127.0.0.1"},
        ).get_environ()
        malformed_environ["HTTP_HOST"] = malformed_host
        malformed_body = middleware(malformed_environ, start_response)
        list(malformed_body)
        malformed_body.close()
        assert current_safe_request_summary() is None

        sdk_event = sentry_wsgi._make_wsgi_event_processor(malformed_environ, False)(
            {"exception": {"value": "synthetic private exception"}},
            {},
        )
        assert sdk_event["request"]["url"] == expected_sdk_url
        assert "PATH_INFO" not in sdk_event["request"]["env"]
        assert sentry_options["before_send"](sdk_event, {}) is None
        assert sentry_options["before_send_transaction"](sdk_event, {}) is None


def test_werkzeug_fallback_logging_is_reference_counted_for_owned_servers(monkeypatch):
    """Concurrent fallback owners restore the pre-existing logger state only after the last stop."""
    from flinttrade_core import app as app_module

    class Server:
        def serve_forever(self):
            return None

        def shutdown(self):
            return None

        def server_close(self):
            return None

    real_import = builtins.__import__

    def import_without_waitress(name, *args, **kwargs):
        if name == "waitress.server":
            raise ImportError("synthetic missing waitress")
        return real_import(name, *args, **kwargs)

    werkzeug_logger = logging.getLogger("werkzeug")
    original = werkzeug_logger.disabled
    werkzeug_logger.disabled = False
    monkeypatch.setattr(builtins, "__import__", import_without_waitress)
    monkeypatch.setattr("werkzeug.serving.make_server", lambda *_args, **_kwargs: Server())

    first = app_module._run_flask_server(Flask("fallback-first"), port=0)
    second = app_module._run_flask_server(Flask("fallback-second"), port=0)
    assert werkzeug_logger.disabled is True
    assert first.stop(timeout=1) is True
    assert werkzeug_logger.disabled is True
    assert second.stop(timeout=1) is True
    assert werkzeug_logger.disabled is False
    werkzeug_logger.disabled = original


def test_werkzeug_fallback_start_failure_releases_its_suppression_lease(monkeypatch):
    from flinttrade_core import app as app_module

    server = MagicMock()
    real_import = builtins.__import__

    def import_without_waitress(name, *args, **kwargs):
        if name == "waitress.server":
            raise ImportError("synthetic missing waitress")
        return real_import(name, *args, **kwargs)

    werkzeug_logger = logging.getLogger("werkzeug")
    original = werkzeug_logger.disabled
    werkzeug_logger.disabled = False
    monkeypatch.setattr(builtins, "__import__", import_without_waitress)
    monkeypatch.setattr("werkzeug.serving.make_server", lambda *_args, **_kwargs: server)
    monkeypatch.setattr("threading.Thread.start", MagicMock(side_effect=RuntimeError("synthetic start failure")))

    with pytest.raises(RuntimeError, match="start failure"):
        app_module._run_flask_server(Flask("fallback-start-failure"), port=0)

    server.server_close.assert_called_once_with()
    assert werkzeug_logger.disabled is False
    werkzeug_logger.disabled = original


def test_werkzeug_fallback_owner_construction_failure_releases_its_suppression_lease(monkeypatch):
    from flinttrade_core import app as app_module

    server = MagicMock()
    real_import = builtins.__import__

    def import_without_waitress(name, *args, **kwargs):
        if name == "waitress.server":
            raise ImportError("synthetic missing waitress")
        return real_import(name, *args, **kwargs)

    werkzeug_logger = logging.getLogger("werkzeug")
    original = werkzeug_logger.disabled
    werkzeug_logger.disabled = False
    monkeypatch.setattr(builtins, "__import__", import_without_waitress)
    monkeypatch.setattr("werkzeug.serving.make_server", lambda *_args, **_kwargs: server)
    monkeypatch.setattr(
        app_module,
        "_FlaskServerOwner",
        MagicMock(side_effect=RuntimeError("synthetic owner construction failure")),
    )

    with pytest.raises(RuntimeError, match="construction failure"):
        app_module._run_flask_server(Flask("fallback-construction-failure"), port=0)

    server.server_close.assert_called_once_with()
    assert werkzeug_logger.disabled is False
    werkzeug_logger.disabled = original


def test_werkzeug_fallback_close_retry_releases_each_overlapping_lease_once(monkeypatch):
    from flinttrade_core import app as app_module

    class Server:
        def __init__(self, *, fail_close: bool = False) -> None:
            self.fail_close = fail_close
            self.close_calls = 0

        def serve_forever(self):
            return None

        def shutdown(self):
            return None

        def server_close(self):
            self.close_calls += 1
            if self.fail_close:
                self.fail_close = False
                raise RuntimeError("synthetic close failure")

    servers = iter((Server(fail_close=True), Server()))
    real_import = builtins.__import__

    def import_without_waitress(name, *args, **kwargs):
        if name == "waitress.server":
            raise ImportError("synthetic missing waitress")
        return real_import(name, *args, **kwargs)

    werkzeug_logger = logging.getLogger("werkzeug")
    original = werkzeug_logger.disabled
    werkzeug_logger.disabled = False
    monkeypatch.setattr(builtins, "__import__", import_without_waitress)
    monkeypatch.setattr("werkzeug.serving.make_server", lambda *_args, **_kwargs: next(servers))

    first = app_module._run_flask_server(Flask("fallback-close-failure"), port=0)
    second = app_module._run_flask_server(Flask("fallback-overlap"), port=0)
    with pytest.raises(RuntimeError, match="close failure"):
        first.stop(timeout=1)
    assert werkzeug_logger.disabled is True
    assert first.stop(timeout=1) is True
    assert werkzeug_logger.disabled is True
    assert second.stop(timeout=1) is True
    assert werkzeug_logger.disabled is False
    werkzeug_logger.disabled = original


def test_mutation_rate_limit_is_shared_by_original_peer_across_verbs(tmp_path, monkeypatch):
    audit = RecordingAudit()
    app = _unit_app(tmp_path / "workspace", monkeypatch, audit=audit)
    limiter = Limiter(lambda: "default", app=app, default_limits=[], storage_uri="memory://")
    app.config["LIMITER"] = limiter
    routes = importlib.import_module("flinttrade_core.service_connection_routes")
    assert routes.install_service_connection_rate_limits(app) == 3
    client = app.test_client()
    loopback = {"werkzeug.proxy_fix.orig": {"REMOTE_ADDR": "127.0.0.1"}}

    for _ in range(10):
        response = client.post(
            "/v1/services/connections",
            headers=_session_headers(),
            environ_overrides=loopback,
        )
        assert response.status_code == 415
    limited = client.patch(
        f"/v1/services/connections/{uuid4()}",
        headers=_session_headers(),
        environ_overrides=loopback,
    )
    assert len(audit.attempts) == 11
    assert audit.attempts[-1][1] == {
        "route_template": "/ft-api/v1/services/connections/{connection_id}",
        "method": "PATCH",
        "authentication_class": "authenticated",
        "outcome": "rejected",
        "actor": "operator:" + "a" * 64,
        "connection_ref": None,
    }
    other_peer = client.delete(
        f"/v1/services/connections/{uuid4()}",
        headers=_session_headers(),
        environ_overrides={"werkzeug.proxy_fix.orig": {"REMOTE_ADDR": "::1"}},
    )

    assert limited.status_code == 429
    assert limited.get_json() == {"error": "rate_limit_exceeded"}
    assert limited.headers["Cache-Control"] == "no-store"
    assert other_peer.status_code == 415


def test_global_limit_before_family_guard_records_one_unverified_attempt(tmp_path, monkeypatch):
    routes = importlib.import_module("flinttrade_core.service_connection_routes")
    audit = RecordingAudit()
    app = Flask("global-limit-before-family-guard")
    app.config["TESTING"] = True
    Limiter(lambda: "global-peer", app=app, default_limits=["1 per minute"], storage_uri="memory://")
    app.config["AUDIT_LOGGER"] = audit
    app.config["SERVICE_CONNECTION_STORE"] = ServiceConnectionStore(tmp_path / "workspace")
    monkeypatch.setenv("FLINTTRADE_API_KEY", "synthetic-read-key")
    app.register_blueprint(routes.service_connection_bp)
    app.before_request(routes.guard_service_connection_family)
    app.after_request(routes.apply_service_connection_cache_policy)
    client = app.test_client()

    first = client.post(
        "/v1/services/connections",
        headers=_session_headers(),
        environ_overrides={"REMOTE_ADDR": "127.0.0.1"},
    )
    assert first.status_code == 401
    audit.attempts.clear()
    limited = client.post(
        "/v1/services/connections",
        headers=_session_headers(),
        environ_overrides={"REMOTE_ADDR": "127.0.0.1"},
    )

    assert limited.status_code == 429
    assert audit.attempts == [
        (
            "SERVICE_CONNECTION_ROUTE_ATTEMPT",
            {
                "route_template": "/ft-api/v1/services/connections",
                "method": "POST",
                "authentication_class": "invalid",
                "outcome": "rejected",
                "actor": None,
                "connection_ref": None,
            },
        )
    ]


@pytest.mark.parametrize("method", ["POST", "PATCH", "DELETE"])
def test_authenticated_unmatched_mutation_records_one_ref_free_attempt(method, tmp_path, monkeypatch):
    audit = RecordingAudit()
    app = _unit_app(tmp_path / "workspace", monkeypatch, audit=audit)

    response = app.test_client().open(
        "/v1/services/connections/not-a-route/extra",
        method=method,
        headers=_session_headers(),
    )

    assert response.status_code == 404
    assert audit.attempts == [
        (
            "SERVICE_CONNECTION_ROUTE_ATTEMPT",
            {
                "route_template": "/ft-api/v1/services/connections/{connection_id}",
                "method": method,
                "authentication_class": "authenticated",
                "outcome": "rejected",
                "actor": "operator:" + "a" * 64,
                "connection_ref": None,
            },
        )
    ]


def test_authenticated_method_mismatch_records_one_ref_free_attempt(tmp_path, monkeypatch):
    audit = RecordingAudit()
    app = _unit_app(tmp_path / "workspace", monkeypatch, audit=audit)

    response = app.test_client().post(
        f"/v1/services/connections/{uuid4()}",
        headers=_session_headers(),
    )

    assert response.status_code == 405
    assert len(audit.attempts) == 1
    assert audit.attempts[0][1] == {
        "route_template": "/ft-api/v1/services/connections/{connection_id}",
        "method": "POST",
        "authentication_class": "authenticated",
        "outcome": "rejected",
        "actor": "operator:" + "a" * 64,
        "connection_ref": None,
    }


@pytest.mark.parametrize("audit", [None, RecordingAudit(fail_attempts=True)])
def test_unmatched_mutation_audit_unavailable_preserves_404(audit, tmp_path, monkeypatch, caplog):
    app = _unit_app(tmp_path / "workspace", monkeypatch, audit=audit)

    response = app.test_client().post(
        "/v1/services/connections/not-a-route/extra",
        headers=_session_headers(),
    )

    assert response.status_code == 404
    assert response.get_json() is None
    assert caplog.messages.count("Service-connection route-attempt audit unavailable") == 1


@pytest.mark.parametrize(
    "headers,expected",
    [
        ({"Authorization": "Bearer synthetic-read-key"}, 200),
        ({"X-FlintTrade-Token": "wrong", "X-API-Key": "synthetic-read-key"}, 401),
        ({"Authorization": "Bearer wrong", "X-API-Key": "synthetic-read-key"}, 401),
    ],
)
def test_read_proof_carrier_precedence_is_deterministic(headers, expected, tmp_path, monkeypatch):
    app = _unit_app(tmp_path / "workspace", monkeypatch)
    response = app.test_client().get("/v1/services/connections", headers=headers)
    assert response.status_code == expected


@pytest.mark.parametrize(
    "headers",
    [
        {"Authorization": "Bearer caf\u00e9"},
        {"X-API-Key": "caf\u00e9"},
    ],
)
def test_non_ascii_read_proof_is_an_invalid_credential(headers, tmp_path, monkeypatch):
    app = _unit_app(tmp_path / "workspace", monkeypatch)

    response = app.test_client().get("/v1/services/connections", headers=headers)

    assert response.status_code == 401
    assert response.get_json() == {"error": "authentication_required"}


def test_verified_invalid_identity_is_never_recast_as_same_bearer_key(tmp_path, monkeypatch):
    app = _unit_app(tmp_path / "workspace", monkeypatch)
    routes = importlib.import_module("flinttrade_core.service_connection_routes")

    def invalid_identity(_token: str):
        raise routes._OperatorSessionVerificationError("invalid_identity")

    monkeypatch.setattr(routes, "verify_operator_session_token", invalid_identity)
    response = app.test_client().get(
        "/v1/services/connections",
        headers={"Authorization": "Bearer synthetic-read-key"},
    )
    assert response.status_code == 401


@pytest.mark.parametrize(
    "headers,json_body,raw_body,content_type,status,error",
    [
        ({}, CREATE_PAYLOAD, None, None, 428, "connection_revision_required"),
        ({"If-Match": '"tag"'}, CREATE_PAYLOAD, None, None, 400, "invalid_request"),
        (
            {"If-Match": "*", "Idempotency-Key": "24f523c6-b510-44ab-a80c-da6940438325"},
            CREATE_PAYLOAD,
            None,
            None,
            400,
            "invalid_request",
        ),
        (
            {"If-Match": 'W/"tag"', "Idempotency-Key": "24f523c6-b510-44ab-a80c-da6940438325"},
            CREATE_PAYLOAD,
            None,
            None,
            400,
            "invalid_request",
        ),
        (
            {"If-Match": '"a", "b"', "Idempotency-Key": "24f523c6-b510-44ab-a80c-da6940438325"},
            CREATE_PAYLOAD,
            None,
            None,
            400,
            "invalid_request",
        ),
        ({}, None, "{}", "text/plain", 415, "unsupported_media_type"),
        ({}, None, "{", "application/json", 400, "invalid_request"),
        ({}, None, "{\"padding\":\"" + "x" * (32 * 1024) + "\"}", "application/json", 413, "request_too_large"),
    ],
)
def test_mutation_http_boundary_errors_are_closed(
    headers, json_body, raw_body, content_type, status, error, tmp_path, monkeypatch
):
    app = _unit_app(tmp_path / "workspace", monkeypatch)
    request_headers = {**_session_headers(), **headers}
    kwargs: dict[str, object] = {"headers": request_headers}
    if json_body is not None:
        kwargs["json"] = json_body
    else:
        kwargs.update(data=raw_body, content_type=content_type)
    response = app.test_client().post("/v1/services/connections", **kwargs)
    assert response.status_code == status
    assert response.get_json() == {"error": error}
    assert "ETag" not in response.headers


@pytest.mark.parametrize("tag", ['""', '"short"', '"comma,slash\\value"'])
def test_valid_foreign_strong_tag_maps_to_failed_precondition(tag, tmp_path, monkeypatch):
    app = _unit_app(tmp_path / "workspace", monkeypatch)
    response = app.test_client().post(
        "/v1/services/connections",
        json=CREATE_PAYLOAD,
        headers=_session_headers(tag, str(uuid4())),
    )
    assert response.status_code == 412
    assert response.get_json() == {"error": "connection_revision_conflict"}
    assert "ETag" not in response.headers


def test_repeated_if_match_fields_are_rejected_as_a_list(tmp_path, monkeypatch):
    app = _unit_app(tmp_path / "workspace", monkeypatch)
    headers = Headers(_session_headers(key=str(uuid4())))
    headers.add("If-Match", '"first"')
    headers.add("If-Match", '"second"')

    response = app.test_client().post(
        "/v1/services/connections",
        json=CREATE_PAYLOAD,
        headers=headers,
    )

    assert response.status_code == 400
    assert response.get_json() == {"error": "invalid_request"}


@pytest.mark.parametrize("tag", ['"' + "a" * 4095 + '"', '"snowman\u2603"'])
def test_over_limit_or_non_latin1_if_match_is_rejected(tag, tmp_path, monkeypatch):
    app = _unit_app(tmp_path / "workspace", monkeypatch)

    response = app.test_client().post(
        "/v1/services/connections",
        json=CREATE_PAYLOAD,
        headers=_session_headers(tag, str(uuid4())),
    )

    assert response.status_code == 400
    assert response.get_json() == {"error": "invalid_request"}


def test_http_retry_removes_only_outer_ows_and_preserves_opaque_tag(tmp_path, monkeypatch):
    workspace = tmp_path / "workspace"
    app = _unit_app(workspace, monkeypatch)
    initial = app.test_client().get("/v1/services/connections", headers=_session_headers())
    key = str(uuid4())
    tag = initial.headers["ETag"]
    first = app.test_client().post(
        "/v1/services/connections",
        json=CREATE_PAYLOAD,
        headers=_session_headers(tag, key),
    )
    app.config["SERVICE_CONNECTION_STORE"] = ServiceConnectionStore(workspace)

    replay = app.test_client().post(
        "/v1/services/connections",
        json=CREATE_PAYLOAD,
        headers=_session_headers(f" \t{tag}\t ", key),
    )

    assert (replay.status_code, replay.get_json(), replay.headers["ETag"]) == (
        first.status_code,
        first.get_json(),
        first.headers["ETag"],
    )
    assert app.config["SERVICE_CONNECTION_STORE"].read_snapshot().epoch == 1


def test_http_passes_exact_inner_opaque_tag_to_store(tmp_path, monkeypatch):
    app = _unit_app(tmp_path / "workspace", monkeypatch)
    store = MagicMock()
    store.mutate.return_value = ConnectionMutationResult(
        409,
        {"error": "connection_revision_conflict"},
        '"' + "f" * 64 + '"',
    )
    app.config["SERVICE_CONNECTION_STORE"] = store
    tag = '"opaque,slash\\value\u00ff"'

    response = app.test_client().post(
        "/v1/services/connections",
        json=CREATE_PAYLOAD,
        headers=_session_headers(f" \t{tag}\t ", str(uuid4())),
    )

    assert response.status_code == 409
    assert store.mutate.call_args.kwargs["expected_etag"] == tag


def test_missing_item_has_no_revision_header(tmp_path, monkeypatch):
    app = _unit_app(tmp_path / "workspace", monkeypatch)
    response = app.test_client().get(f"/v1/services/connections/{uuid4()}", headers=_session_headers())
    assert response.status_code == 404
    assert response.get_json() == {"error": "connection_not_found"}
    assert "ETag" not in response.headers


@pytest.mark.parametrize(
    "result",
    [
        ConnectionMutationResult(409, {"error": "connection_revision_conflict"}, '"' + "1" * 64 + '"'),
        ConnectionMutationResult(503, {"error": "transaction_rolled_back"}, '"' + "2" * 64 + '"'),
    ],
)
def test_admitted_stored_failure_result_is_returned_verbatim(result, tmp_path, monkeypatch):
    app = _unit_app(tmp_path / "workspace", monkeypatch)
    store = MagicMock()
    store.mutate.return_value = result
    app.config["SERVICE_CONNECTION_STORE"] = store
    response = app.test_client().post(
        "/v1/services/connections",
        json=CREATE_PAYLOAD,
        headers=_session_headers('"foreign"', str(uuid4())),
    )
    assert response.status_code == result.status
    assert response.get_json() == result.to_dict()["body"]
    assert response.headers["ETag"] == result.etag
