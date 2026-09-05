"""The real factory authenticates recovery before body or authority access."""

import logging
from uuid import UUID

import jwt
import pytest
from flask import Config, Request

from flinttrade_core import auth_routes
from flinttrade_core.broker_identity import QuarantineRef
from flinttrade_gateway.credentials import QuarantinedCredentialMetadata


@pytest.fixture
def recovery_app(monkeypatch):
    from flinttrade_core.app import create_flask_app

    monkeypatch.delenv("FLINTTRADE_API_KEY", raising=False)
    monkeypatch.delenv("OPENALGO_API_KEY", raising=False)
    monkeypatch.setenv("ENABLE_ANALYZER", "true")
    app = create_flask_app()
    with app.app_context():
        token = auth_routes._create_token("synthetic", mode="explore")
    return app, token


def proof(app, token, kind):
    if kind == "missing":
        return {}
    if kind == "key":
        return {"X-API-Key": "synthetic-key"}
    if kind == "invalid":
        return {"Authorization": "Bearer invalid"}
    with app.app_context():
        key = auth_routes._get_jwt_secret()
        payload = jwt.decode(token, key, algorithms=["HS256"])
        if kind == "narrow":
            payload["scopes"] = ["admin.services.read"]
        elif kind == "legacy":
            payload.pop("scopes")
        elif kind in {"reset", "pin"}:
            payload["type"] = kind
        elif kind == "expired":
            payload["exp"] = 1
        elif kind == "revoked":
            auth_routes._revoke_jti(payload["jti"], payload["exp"])
        token = jwt.encode(payload, key, algorithm="HS256")
    return {"Authorization": "Bearer " + token}


@pytest.mark.parametrize(
    "kind,want",
    [
        ("missing", 401),
        ("key", 401),
        ("invalid", 401),
        ("reset", 401),
        ("pin", 401),
        ("expired", 401),
        ("revoked", 401),
        ("narrow", 403),
        ("legacy", 403),
        ("full", None),
    ],
)
@pytest.mark.parametrize("content_type", ["application/json", "text/plain", "application/x-www-form-urlencoded"])
def test_recovery_family_denials_precede_body_storage_and_provider(recovery_app, monkeypatch, kind, want, content_type):
    app, token = recovery_app
    if kind == "key":
        monkeypatch.setenv("FLINTTRADE_API_KEY", "synthetic-key")
    headers = proof(app, token, kind)
    attempts = []

    def forbidden(*args, **kwargs):
        attempts.append("forbidden")
        raise AssertionError("PRIVATE-body-authority")

    class CheckedConfig(Config):
        def get(self, key, default=None):
            if key in {"CREDENTIAL_STORE", "REGISTRY", "NATIVE_ADAPTERS"}:
                return forbidden()
            return super().get(key, default)

        def __getitem__(self, key):
            if key in {"CREDENTIAL_STORE", "REGISTRY", "NATIVE_ADAPTERS"}:
                return forbidden()
            return super().__getitem__(key)

    app.config = CheckedConfig(app.root_path, defaults=app.config)
    for name in ("get_data", "get_json", "_load_form_data"):
        monkeypatch.setattr(Request, name, forbidden)
    monkeypatch.setattr("flinttrade_gateway.adapter.load_broker_adapter", forbidden)
    cases = [
        ("POST", "/quarantine/PRIVATE-path/adopt", 503),
        ("DELETE", "/quarantine", 503),
        ("DELETE", "/quarantine/PRIVATE-path", 503),
        ("PATCH", "/quarantine/unmatched/deep", 503),
        ("GET", "/quarantine/unmatched/deep", 404),
        ("TRACE", "/quarantine", 405),
        ("OPTIONS", "/quarantine", 405),
    ]
    if kind != "full":
        cases.append(("GET", "/quarantine", want))
    for method, suffix, allowed_status in cases:
        response = app.test_client().open(
            "/ft-api/v1/accounts" + suffix,
            method=method,
            headers=headers,
            data="PRIVATE-body",
            content_type=content_type,
        )
        assert response.status_code == (want or allowed_status), (method, suffix, response.status_code)
        assert response.headers.get("Cache-Control") == "no-store"
        assert attempts == []
        assert "PRIVATE" not in response.get_data(as_text=True)


def test_recovery_list_projects_only_metadata_and_fails_closed(recovery_app, monkeypatch):
    app, token = recovery_app
    entry = QuarantinedCredentialMetadata(
        QuarantineRef(UUID("b45b558c-d014-4879-8b63-d095720389ba"), UUID("384bdd4b-929f-4ead-b171-d8351c9eb9b0"), 7),
        "legacy_identity_invalid",
        "legacy_pre_workspace_authority",
    )

    class ReadStore:
        calls = 0
        fail = False

        def list_quarantine(self):
            self.calls += 1
            if self.fail:
                raise RuntimeError("PRIVATE-source-failure")
            return (entry,)

    store = ReadStore()
    app.config["CREDENTIAL_STORE"] = store
    headers = {"X-FlintTrade-Token": token}
    response = app.test_client().get("/ft-api/v1/accounts/quarantine", headers=headers)
    assert response.status_code == 200
    assert response.json == {
        "quarantined_credentials": [
            {
                "quarantine_id": "b45b558c-d014-4879-8b63-d095720389ba",
                "source_vault_incarnation": "384bdd4b-929f-4ead-b171-d8351c9eb9b0",
                "row_generation": 7,
                "reason": "legacy_identity_invalid",
                "provenance": "legacy_pre_workspace_authority",
            }
        ]
    }
    assert response.headers["Cache-Control"] == "no-store"
    assert app.test_client().head("/v1/accounts/quarantine", headers=headers).status_code == 200
    assert store.calls == 2
    response = app.test_client().get("/v1/accounts/quarantine", headers=headers | {"Authorization": "Bearer bad"})
    assert response.status_code == 401 and store.calls == 2
    store.fail = True
    response = app.test_client().get("/v1/accounts/quarantine", headers=headers)
    assert response.status_code == 503 and response.json == {"error": "credential_quarantine_unavailable"}


@pytest.mark.parametrize("sink_raises", [False, True])
def test_unmatched_recovery_metadata_never_reaches_raw_sinks(recovery_app, monkeypatch, caplog, sink_raises):
    app, token = recovery_app
    calls = []

    def sink(ip, path):
        calls.append((ip, path))
        if sink_raises:
            raise RuntimeError("PRIVATE-sink-error")

    monkeypatch.setattr(app.config["SECURITY_TRACKER"], "track_404", sink)
    with caplog.at_level(logging.DEBUG):
        response = app.test_client().get(
            "/v1/accounts/quarantine/PRIVATE-path/missing?PRIVATE-query=one",
            headers={"Authorization": "Bearer " + token, "User-Agent": "PRIVATE-agent"},
        )
    assert response.status_code == 404
    assert calls == [("redacted", "/v1/accounts/quarantine/{quarantine_id}")]
    assert "PRIVATE" not in caplog.text


def test_quarantine_namespace_does_not_exempt_sibling_content_type_or_authentication(recovery_app, monkeypatch):
    app, token = recovery_app
    headers = {"Authorization": "Bearer " + token}
    for path in ("/v1/accounts/quarantine-extra/deep", "/v1/accounts-extra/quarantine"):
        response = app.test_client().post(path, headers=headers, data="not-json", content_type="text/plain")
        assert response.status_code == 415
    monkeypatch.setenv("FLINTTRADE_API_KEY", "configured-key")
    assert app.test_client().get("/v1/accounts/quarantine-extra/deep").status_code == 401


@pytest.mark.parametrize("sink_raises", [False, True])
def test_recovery_observability_never_reads_bodies_even_when_sinks_fail(recovery_app, monkeypatch, caplog, sink_raises):
    app, token = recovery_app
    read_calls, traffic, analysed, errors = [], [], [], []

    def forbidden(*args, **kwargs):
        read_calls.append("read")
        raise AssertionError("PRIVATE-body-read")

    for name in ("get_data", "get_json", "_load_form_data"):
        monkeypatch.setattr(Request, name, forbidden)

    def traffic_sink(**fields):
        traffic.append(fields)
        if sink_raises:
            raise RuntimeError("PRIVATE-traffic-error")

    def analyser_sink(**fields):
        analysed.append(fields)
        if sink_raises:
            raise RuntimeError("PRIVATE-analyser-error")

    def error_sink(**fields):
        errors.append(fields)
        raise RuntimeError("PRIVATE-error-sink")

    monkeypatch.setattr(app.config["TRAFFIC_LOGGER"], "log", traffic_sink)
    monkeypatch.setattr(app.config["API_ANALYZER"], "log_call", analyser_sink)
    monkeypatch.setattr(app.config["ERROR_LOG"], "log", error_sink)
    with caplog.at_level(logging.DEBUG):
        for headers in ({}, {"Authorization": "Bearer " + token}):
            response = app.test_client().post(
                "/v1/accounts/quarantine/PRIVATE-path/adopt",
                headers=headers,
                data="PRIVATE-body",
                content_type="application/x-www-form-urlencoded",
            )
            assert response.status_code == (503 if headers else 401)
    assert read_calls == [] and errors == []
    assert len(traffic) == len(analysed) == 2
    assert all(item["ip"] == "redacted" and item["user_agent"] is None for item in traffic)
    assert all(item["request_body"] is None and item["safe_request"] is not None for item in analysed)
    assert "PRIVATE" not in repr(traffic) and "PRIVATE" not in caplog.text


def test_empty_composed_vault_is_real_success_missing_store_is_unavailable(recovery_app, monkeypatch):
    app, token = recovery_app
    headers = {"Authorization": "Bearer " + token}
    assert app.test_client().get("/v1/accounts/quarantine", headers=headers).json == {"quarantined_credentials": []}
    app.config.pop("CREDENTIAL_STORE")
    attempts = []

    def forbidden(*args, **kwargs):
        attempts.append(1)
        raise AssertionError("unexpected replacement vault")

    monkeypatch.setattr("flinttrade_gateway.credentials.CredentialStore", forbidden)
    response = app.test_client().get("/v1/accounts/quarantine", headers=headers)
    assert response.status_code == 503 and response.json == {"error": "credential_quarantine_unavailable"}
    assert attempts == []


def test_pre_password_change_session_has_no_recovery_access(recovery_app, monkeypatch):
    app, token = recovery_app
    with app.app_context():
        payload = jwt.decode(token, auth_routes._get_jwt_secret(), algorithms=["HS256"])

    class PasswordState:
        def get_password_changed_at(self):
            return payload["iat"] + 10

    monkeypatch.setattr(auth_routes, "_get_auth_service", lambda: PasswordState())
    response = app.test_client().get("/v1/accounts/quarantine", headers={"Authorization": "Bearer " + token})
    assert response.status_code == 401 and response.headers["Cache-Control"] == "no-store"


@pytest.mark.parametrize(
    "method,path,status",
    [
        ("GET", "/ft-api/v1/accounts/quarantine", 200),
        ("HEAD", "/ft-api/v1/accounts/quarantine", 200),
        ("GET", "/ft-api/v1/accounts/quarantine/PRIVATE-path/missing", 404),
    ],
)
def test_recovery_heartbeat_failure_keeps_private_diagnostics_out_of_logs(recovery_app, caplog, method, path, status):
    app, token = recovery_app
    calls = []
    private_error = "PRIVATE-heartbeat-diagnostic: " + token

    class FailingTracker:
        def heartbeat(self, selected_token):
            calls.append(selected_token)
            raise RuntimeError(private_error)

    app.config["SESSION_TRACKER"] = FailingTracker()
    caplog.clear()
    with caplog.at_level(logging.DEBUG):
        response = app.test_client().open(path, method=method, headers={"Authorization": "Bearer " + token})
    assert calls == [token]
    assert response.status_code == status
    assert response.headers["Cache-Control"] == "no-store"
    assert "PRIVATE" not in caplog.text and token not in caplog.text and private_error not in caplog.text


def test_unclassified_heartbeat_failure_retains_ordinary_diagnostic(recovery_app, caplog):
    app, token = recovery_app
    calls = []
    diagnostic = "synthetic ordinary heartbeat diagnostic"

    class FailingTracker:
        def heartbeat(self, selected_token):
            calls.append(selected_token)
            raise RuntimeError(diagnostic)

    app.config["SESSION_TRACKER"] = FailingTracker()
    caplog.clear()
    with caplog.at_level(logging.DEBUG):
        response = app.test_client().get("/v1/brokers", headers={"Authorization": "Bearer " + token})
    assert calls == [token]
    assert response.status_code == 200
    assert diagnostic in caplog.text
