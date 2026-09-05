"""Authenticated inert service-connection HTTP and observability contracts."""

from __future__ import annotations

import importlib
import logging
import subprocess
import builtins
from pathlib import Path
from unittest.mock import MagicMock, patch
from uuid import uuid4

import httpx
import pytest
from flask import Flask
from flask_limiter import Limiter

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

    patched = client.patch(
        f"/v1/services/connections/{connection_id}",
        json={"label": "Renamed", "credential": "replacement"},
        headers=_session_headers(created.headers["ETag"], str(uuid4())),
    )
    assert patched.status_code == 200
    assert patched.get_json()["label"] == "Renamed"
    assert "credential" not in patched.get_json()

    deleted = client.delete(
        f"/v1/services/connections/{connection_id}",
        json={},
        headers=_session_headers(patched.headers["ETag"], str(uuid4())),
    )
    assert deleted.status_code == 200
    assert deleted.get_json() == {"deleted": True}
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
    with (
        patch.object(httpx, "get", side_effect=AssertionError("HTTP transport")),
        patch.object(httpx, "post", side_effect=AssertionError("HTTP transport")),
        patch.object(httpx.Client, "get", side_effect=AssertionError("HTTP transport")),
        patch.object(httpx.Client, "post", side_effect=AssertionError("HTTP transport")),
        patch.object(subprocess, "Popen", side_effect=AssertionError("subprocess launcher")),
        patch.object(subprocess, "run", side_effect=AssertionError("subprocess launcher")),
        patch("socket.socket.connect", side_effect=AssertionError("socket transport")),
        patch("flinttrade_ai.llm_client.LLMClient", side_effect=AssertionError("LLM client")),
        patch("flinttrade_gateway.adapter.load_broker_adapter", side_effect=AssertionError("broker factory")),
        patch.object(app_module.sentry_sdk, "init", side_effect=lambda **options: sentry_options.update(options)),
    ):
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


def test_mutation_rate_limit_is_shared_by_original_peer_across_verbs(tmp_path, monkeypatch):
    app = _unit_app(tmp_path / "workspace", monkeypatch)
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
    other_peer = client.delete(
        f"/v1/services/connections/{uuid4()}",
        headers=_session_headers(),
        environ_overrides={"werkzeug.proxy_fix.orig": {"REMOTE_ADDR": "::1"}},
    )

    assert limited.status_code == 429
    assert limited.get_json() == {"error": "rate_limit_exceeded"}
    assert limited.headers["Cache-Control"] == "no-store"
    assert other_peer.status_code == 415


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
