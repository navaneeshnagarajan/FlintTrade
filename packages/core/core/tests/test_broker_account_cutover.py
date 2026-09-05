"""Production cutover admission must precede every account authority effect."""

from __future__ import annotations

import asyncio
from copy import deepcopy
import logging

import pytest
from flask import Config, Flask, Request

from flinttrade_core import auth_routes, native_account_routes, operations_routes
from flinttrade_core.broker_account_cutover import BrokerAccountCutoverUnavailable
from flinttrade_core.native_rotation import NativeSessionRefresher, configure_session_rotation
from flinttrade_gateway.auth import gateway_bp
from flinttrade_gateway.credentials_rotation import CredentialsRotator
from flinttrade_gateway.native_login import establish_native_session, establish_native_sessions
from flinttrade_gateway.registry import BrokerRegistry
from flinttrade_gateway.exceptions import BrokerNotFoundError


class Forbidden:
    """Record attempts even when legacy code catches the sentinel exception."""

    def __init__(self):
        self.calls = []

    def __getattr__(self, name):
        self.calls.append(name)
        raise AssertionError(f"forbidden authority: {name}")

    def __call__(self, *args, **kwargs):
        self.calls.append("call")
        raise AssertionError("forbidden authority")


MUTATIONS = [
    ("POST", "/api/v1/native/accounts"),
    ("POST", "/api/v1/native/oauth/start"),
    ("POST", "/api/v1/native/accounts/upstox/synthetic/login"),
    ("POST", "/api/v1/native/accounts/upstox/synthetic/set-primary"),
    ("DELETE", "/api/v1/native/accounts/upstox/synthetic"),
    ("POST", "/v1/accounts"),
    ("DELETE", "/v1/accounts/synthetic"),
    ("POST", "/v1/accounts/synthetic/reconnect"),
    ("POST", "/v1/accounts/synthetic/set-primary"),
    ("POST", "/v1/auth/oauth/start"),
    ("POST", "/v1/auth/credentials"),
    ("POST", "/v1/auth/otp/request"),
    ("POST", "/v1/auth/otp/verify"),
    ("PUT", "/v1/rate-limits"),
    ("POST", "/admin/credentials/rotation/upstox/schedule"),
    ("POST", "/admin/credentials/rotation/upstox/rotate-now"),
    ("POST", "/api/v1/ditto/accounts"),
    ("DELETE", "/api/v1/ditto/accounts/synthetic"),
]


@pytest.fixture
def guarded_app(monkeypatch):
    app = Flask(__name__)
    app.config["TESTING"] = True
    app.config["BROKER_MGMT_WRITE_GUARD"] = auth_routes.require_operator_session
    app.register_blueprint(native_account_routes.native_accounts_bp)
    app.register_blueprint(gateway_bp)
    app.register_blueprint(operations_routes.operations_bp)
    app.register_blueprint(configure_session_rotation(app))
    forbidden = Forbidden()
    app.config.update(REGISTRY=forbidden, CREDENTIAL_STORE=forbidden, NATIVE_ADAPTERS=forbidden)
    monkeypatch.setattr(native_account_routes, "_pop_pending_oauth_callback", forbidden)
    monkeypatch.setattr(operations_routes, "_ditto_manager", forbidden)
    monkeypatch.setattr(operations_routes, "_quiesce_ditto_account_generation", forbidden)
    monkeypatch.setattr(Request, "get_json", forbidden)

    class AuthorityConfig(Config):
        def get(self, key, default=None):
            if key in {"REGISTRY", "CREDENTIAL_STORE", "NATIVE_ADAPTERS"}:
                forbidden.calls.append(key)
                raise AssertionError("authority lookup before admission")
            return super().get(key, default)

        def __getitem__(self, key):
            if key in {"REGISTRY", "CREDENTIAL_STORE", "NATIVE_ADAPTERS"}:
                forbidden.calls.append(key)
                raise AssertionError("authority lookup before admission")
            return super().__getitem__(key)

    app.config = AuthorityConfig(app.root_path, defaults=app.config)
    return app, forbidden


@pytest.mark.parametrize(("method", "path"), MUTATIONS)
@pytest.mark.parametrize("authenticated", [False, True])
def test_http_mutations_authenticate_then_deny_before_body_or_authorities(guarded_app, method, path, authenticated):
    app, forbidden = guarded_app
    with app.app_context():
        headers = {"Authorization": f"Bearer {auth_routes._create_token('synthetic', mode='explore')}"}
    response = app.test_client().open(
        path,
        method=method,
        headers=headers if authenticated else {},
        data="{invalid JSON",
        content_type="application/json",
    )
    assert forbidden.calls == []
    if authenticated:
        assert response.status_code == 503
        assert response.json == {"error": "broker_account_cutover_unavailable"}
        assert response.headers["Cache-Control"] == "no-store"
    else:
        assert response.status_code == 401


@pytest.mark.parametrize("path", ["/api/v1/native/oauth/callback", "/v1/auth/oauth/callback"])
def test_callbacks_do_not_consume_or_echo_pending_state(guarded_app, path, monkeypatch):
    app, forbidden = guarded_app
    pending = {"synthetic-state": {"broker": "zerodha", "label": "test", "account_id": "test"}}
    app.config["OAUTH_STATES"] = deepcopy(pending)
    monkeypatch.setattr(native_account_routes, "_OAUTH_PENDING", deepcopy(pending))
    monkeypatch.setattr("flinttrade_gateway.auth._oauth_states", forbidden)
    response = app.test_client().get(path + "?state=synthetic-state&code=synthetic-code")
    assert forbidden.calls == []
    assert response.status_code == 503
    assert response.json == {"error": "broker_account_cutover_unavailable"}
    assert response.headers["Cache-Control"] == "no-store"
    assert app.config["OAUTH_STATES"] == pending
    assert native_account_routes._OAUTH_PENDING == pending


@pytest.mark.parametrize("method", ["add_account", "remove_account", "reconnect_account", "set_primary"])
def test_registry_mutators_reject_before_lock_or_provider(method):
    registry = BrokerRegistry()
    forbidden = Forbidden()
    registry._lock = forbidden
    args = ("synthetic", "zerodha", "test", {}) if method == "add_account" else ("synthetic",)
    with pytest.raises(BrokerAccountCutoverUnavailable, match="^broker_account_cutover_unavailable$"):
        getattr(registry, method)(*args)
    assert forbidden.calls == []


@pytest.mark.parametrize("many", [False, True])
def test_direct_native_login_rejects_before_provider_and_vault(many):
    forbidden = Forbidden()
    call = (
        establish_native_sessions(forbidden, forbidden, forbidden, ["upstox:synthetic"])
        if many
        else establish_native_session(forbidden, forbidden, {}, "upstox", "synthetic")
    )
    with pytest.raises(BrokerAccountCutoverUnavailable, match="^broker_account_cutover_unavailable$"):
        asyncio.run(call)
    assert forbidden.calls == []


@pytest.mark.parametrize("locked", [False, True])
def test_direct_refresh_rejects_before_admission_and_authorities(locked):
    forbidden = Forbidden()
    refresher = NativeSessionRefresher(forbidden, admission=forbidden)
    with pytest.raises(BrokerAccountCutoverUnavailable, match="^broker_account_cutover_unavailable$"):
        if locked:
            refresher._refresh_token_locked("upstox", 0)
        else:
            refresher.refresh_token("upstox")
    assert forbidden.calls == []


@pytest.mark.parametrize("method", ["_do_refresh", "_do_rotation", "rotate_now"])
def test_rotator_reports_unavailable_without_touching_manager(method):
    forbidden = Forbidden()
    rotator = CredentialsRotator(forbidden, forbidden)
    result = getattr(rotator, method)("upstox")
    assert forbidden.calls == []
    assert result.success is False
    assert result.error == "broker_account_cutover_unavailable"
    assert rotator.last_rotation("upstox") is None


def test_startup_skips_workspace_and_authorities(monkeypatch, caplog):
    from flinttrade_core import app as app_module

    forbidden = Forbidden()
    monkeypatch.setattr(app_module, "_read_workspace_brokers", forbidden)
    app = Flask(__name__)
    app.config.update(NATIVE_ADAPTERS=forbidden, REGISTRY=forbidden, CREDENTIAL_STORE=forbidden)
    with caplog.at_level(logging.INFO):
        assert app_module._reestablish_native_sessions(app) == {}
        app_module._reconnect_saved_accounts(forbidden, forbidden, logging.getLogger("test"))
        blueprint = configure_session_rotation(app)
    assert blueprint is not None
    assert app.config["ROTATION_SCHEDULER"].get_jobs() == []
    assert forbidden.calls == []
    assert "broker_account_cutover_unavailable" in caplog.text


@pytest.mark.parametrize("method", ["add_account", "remove_account"])
def test_ditto_direct_writers_deny_before_fence_and_storage(method, tmp_path):
    from flinttrade_ditto.account_manager import AccountManager

    forbidden = Forbidden()
    manager = AccountManager(
        db_path=str(tmp_path / "metadata.db"),
        credential_store=forbidden,
        installation_state_root=tmp_path / "installation",
    )
    original_state = manager._installation_state
    try:
        manager._installation_state = forbidden
        with pytest.raises(BrokerAccountCutoverUnavailable, match="^broker_account_cutover_unavailable$"):
            getattr(manager, method)(forbidden)
    finally:
        manager._installation_state = original_state
        manager.close()
    assert forbidden.calls == []


@pytest.mark.parametrize("endpoint", ["schedule", "rotate-now"])
def test_standalone_rotation_blueprint_denies_before_body_and_rotator(endpoint):
    from flinttrade_gateway.rotation_routes import create_rotation_blueprint

    app = Flask(__name__)
    forbidden = Forbidden()
    app.register_blueprint(create_rotation_blueprint(forbidden))
    response = app.test_client().post(
        f"/admin/credentials/rotation/upstox/{endpoint}",
        data="{invalid",
        content_type="application/json",
    )
    assert response.status_code == 503
    assert response.json == {"error": "broker_account_cutover_unavailable"}
    assert forbidden.calls == []


def test_only_exact_default_openalgo_session_is_published():
    from flinttrade_core.app import build_broker_router

    registry = BrokerRegistry()
    build_broker_router(
        brokers_config={
            "registered": ["openalgo:default", "openalgo:other"],
            "execution": {"default": "openalgo:default"},
            "data": {
                "ticks": "openalgo:default",
                "historical": "openalgo:default",
                "option_chains": "openalgo:default",
            },
            "account_acls": {"openalgo": {"default": ["synthetic"], "other": ["synthetic"]}},
        },
        registry=registry,
        openalgo_client=object(),
    )
    assert registry.get_session_for("openalgo", "default").account_id == "default"
    with pytest.raises(BrokerNotFoundError):
        registry.get_session_for("openalgo", "other")


@pytest.mark.parametrize("weekly", [False, True])
def test_previously_registered_jobs_check_current_admission(weekly, caplog):
    from flinttrade_core.broker_account_cutover import require_broker_account_mutations

    allowed = True

    def admission():
        if not allowed:
            require_broker_account_mutations()

    class Scheduler:
        def add_job(self, job, **kwargs):
            self.job = job

    forbidden = Forbidden()
    scheduler = Scheduler()
    rotator = CredentialsRotator(forbidden, scheduler, mutation_admission=admission)
    if weekly:
        rotator.schedule_weekly_rotation("sensitive-input", 0, "08:05")
    else:
        rotator.schedule_daily_refresh("sensitive-input", "08:05")
    allowed = False
    caplog.clear()
    with caplog.at_level(logging.INFO):
        scheduler.job()
    assert forbidden.calls == []
    assert rotator.last_rotation("sensitive-input") is None
    assert "broker_account_cutover_unavailable" in caplog.text
    assert "sensitive-input" not in caplog.text


def test_manual_rotation_unavailability_diagnostic_contains_no_selector(caplog):
    rotator = CredentialsRotator(Forbidden(), Forbidden())
    with caplog.at_level(logging.INFO):
        result = rotator.rotate_now("sensitive-input")
    assert result.success is False
    assert "broker_account_cutover_unavailable" in caplog.text
    assert "sensitive-input" not in caplog.text


@pytest.mark.parametrize("weekly", [False, True])
def test_direct_schedule_denies_before_scheduler(weekly):

    forbidden = Forbidden()
    rotator = CredentialsRotator(forbidden, forbidden)
    with pytest.raises(BrokerAccountCutoverUnavailable):
        if weekly:
            rotator.schedule_weekly_rotation("upstox", 0, "08:05")
        else:
            rotator.schedule_daily_refresh("upstox", "08:05")
    assert forbidden.calls == []


@pytest.mark.parametrize("candidate", [False, True])
def test_internal_connect_rejects_before_candidate_or_shared_authorities(guarded_app, candidate):

    app, forbidden = guarded_app
    with app.app_context(), pytest.raises(BrokerAccountCutoverUnavailable):
        if candidate:
            native_account_routes._activate_candidate_credentials(forbidden, "upstox", "synthetic")
        else:
            native_account_routes._do_connect("upstox", "synthetic", "test", {}, False)
    assert forbidden.calls == []


def test_direct_rate_limit_writer_denies_before_generation_lease(guarded_app):
    from flinttrade_gateway.auth import update_rate_limits

    app, forbidden = guarded_app
    app.config["BROKER_ROUTER_REBUILD_LOCK"] = forbidden
    with app.test_request_context("/v1/rate-limits", method="PUT"):
        with pytest.raises(BrokerAccountCutoverUnavailable):
            update_rate_limits()
    assert forbidden.calls == []


def test_real_factory_keeps_default_guard_and_preserved_http_boundaries(monkeypatch):
    from flinttrade_core.app import create_flask_app

    monkeypatch.delenv("FLINTTRADE_API_KEY", raising=False)
    monkeypatch.delenv("OPENALGO_API_KEY", raising=False)
    app = create_flask_app()
    client = app.test_client()
    with app.app_context():
        headers = {"Authorization": f"Bearer {auth_routes._create_token('synthetic', mode='explore')}"}
    for method, path in MUTATIONS:
        response = client.open(path, method=method, headers=headers, json={})
        assert response.status_code == 503, (method, path, response.json)
        assert response.json == {"error": "broker_account_cutover_unavailable"}
        assert response.headers["Cache-Control"] == "no-store"
        assert client.open(path, method="OPTIONS", data="synthetic", content_type="text/plain").status_code == 200
    for path in ("/api/v1/native/oauth/callback", "/v1/auth/oauth/callback"):
        response = client.get(path + "?code=synthetic&state=synthetic")
        assert response.status_code == 503
        assert response.json == {"error": "broker_account_cutover_unavailable"}
    for path in (
        "/v1/brokers",
        "/v1/accounts",
        "/v1/rate-limits",
        "/api/v1/native/brokers",
        "/api/v1/native/accounts",
        "/admin/credentials/rotation/status",
    ):
        assert client.get(path, headers=headers, data="synthetic", content_type="text/plain").status_code == 200, path
    response = client.post("/api/v1/native/postbacks/upstox", json={"update_type": "order"})
    assert response.status_code == 200
    assert response.json["data"]["accepted"] is True
    rows_before = app.config["CREDENTIAL_STORE"].list_accounts()
    response = client.post("/v1/config/openalgo", headers=headers, json={"telegram_username": "synthetic"})
    assert response.status_code == 200, response.json
    assert app.config["CREDENTIAL_STORE"].list_accounts() == rows_before


@pytest.mark.parametrize("content_type", ["application/json", "text/plain", "application/x-www-form-urlencoded"])
@pytest.mark.parametrize("principal", ["missing", "invalid", "operator"])
@pytest.mark.parametrize("sink_raises", [False, True])
def test_real_factory_rejection_precedes_body_validation_and_observability(
    monkeypatch, caplog, content_type, principal, sink_raises
):
    """Exercise production hook ordering, including exceptions swallowed by sinks."""
    from flinttrade_core.app import create_flask_app

    monkeypatch.delenv("FLINTTRADE_API_KEY", raising=False)
    monkeypatch.delenv("OPENALGO_API_KEY", raising=False)
    monkeypatch.setenv("ENABLE_ANALYZER", "true")
    app = create_flask_app()
    with app.app_context():
        headers = {"Authorization": f"Bearer {auth_routes._create_token('synthetic', mode='explore')}"}
    if principal == "missing":
        headers = {}
    elif principal == "invalid":
        headers = {"Authorization": "Bearer synthetic-invalid-token"}
    forbidden = Forbidden()
    body_reads = Forbidden()

    class AuthorityConfig(Config):
        def get(self, key, default=None):
            if key in {"REGISTRY", "CREDENTIAL_STORE", "NATIVE_ADAPTERS", "BROKER_ROUTER_REBUILD_LOCK"}:
                forbidden.calls.append(key)
                raise AssertionError("authority lookup before admission")
            return super().get(key, default)

        def __getitem__(self, key):
            if key in {"REGISTRY", "CREDENTIAL_STORE", "NATIVE_ADAPTERS", "BROKER_ROUTER_REBUILD_LOCK"}:
                forbidden.calls.append(key)
                raise AssertionError("authority lookup before admission")
            return super().__getitem__(key)

    app.config = AuthorityConfig(app.root_path, defaults=app.config)
    monkeypatch.setattr(native_account_routes, "_pop_pending_oauth_callback", forbidden)
    monkeypatch.setattr(operations_routes, "_ditto_manager", forbidden)
    monkeypatch.setattr(operations_routes, "_quiesce_ditto_account_generation", forbidden)
    monkeypatch.setattr("flinttrade_gateway.auth._oauth_states", forbidden)
    for method in ("get_json", "get_data", "_load_form_data"):
        monkeypatch.setattr(Request, method, body_reads)
    observed = []
    errors = []
    traffic = []
    real_analyser = app.config["API_ANALYZER"].log_call
    real_traffic = app.config["TRAFFIC_LOGGER"].log

    def record_analyser(**fields):
        observed.append(fields)
        # The hook catches this: recording first proves it cannot hide body access.
        if sink_raises:
            raise RuntimeError("synthetic analyser failure")
        return real_analyser(**fields)

    def record_traffic(**fields):
        traffic.append(fields)
        if sink_raises:
            raise RuntimeError("synthetic traffic failure")
        return real_traffic(**fields)

    def record_error(**fields):
        errors.append(fields)
        raise RuntimeError("synthetic error sink failure")

    monkeypatch.setattr(app.config["API_ANALYZER"], "log_call", record_analyser)
    monkeypatch.setattr(app.config["ERROR_LOG"], "log", record_error)
    monkeypatch.setattr(app.config["TRAFFIC_LOGGER"], "log", record_traffic)
    client = app.test_client()
    for method, path in MUTATIONS:
        observed.clear()
        traffic.clear()
        response = client.open(
            path,
            method=method,
            headers=headers,
            data=(
                "review_marker=synthetic-body-must-not-be-read"
                if content_type == "application/x-www-form-urlencoded"
                else '{"review_marker":"synthetic-body-must-not-be-read"}'
            ),
            content_type=content_type,
        )
        assert response.status_code == (503 if principal == "operator" else 401), (method, path, response.json)
        if principal == "operator":
            assert response.json == {"error": "broker_account_cutover_unavailable"}
            assert response.headers["Cache-Control"] == "no-store"
        assert body_reads.calls == [], (method, path)
        assert forbidden.calls == [], (method, path)
        assert errors == []
        assert len(observed) == 1, (method, path)
        assert observed[0]["request_body"] is None
        assert observed[0]["safe_request"] is not None
        assert observed[0]["response_status"] == response.status_code
        assert len(traffic) == 1
        assert traffic[0]["ip"] == "redacted"
        assert traffic[0]["path"] == observed[0]["safe_request"].route_template
        assert traffic[0]["user_agent"] is None
        assert "synthetic-body-must-not-be-read" not in repr(observed)
        assert "synthetic-body-must-not-be-read" not in repr(traffic)
        assert "synthetic-body-must-not-be-read" not in caplog.text
        if not sink_raises:
            stored = app.config["API_ANALYZER"].recent(limit=1)[0]
            assert stored["request_body"] == observed[0]["safe_request"].to_dict()
            assert stored["route"] == observed[0]["safe_request"].route_template


@pytest.mark.parametrize(
    "path",
    [
        "/v1/config/openalgo",
        "/v1/config/telegram",
        "/api/v1/native/postbacks/upstox",
        "/api/v1/ditto/accounts/synthetic/enable",
        "/api/v1/ditto/accounts/synthetic/disable",
        "/v1/accounts-extra",
        "/v1/rate-limits-extra",
        "/admin/credentials/rotation/upstox/schedule-extra",
        "/api/v1/native/unmatched",
    ],
)
def test_real_factory_retains_non_cutover_content_type_validation(path):
    from flinttrade_core.app import create_flask_app

    app = create_flask_app()
    with app.app_context():
        headers = {"Authorization": f"Bearer {auth_routes._create_token('synthetic', mode='explore')}"}
    response = app.test_client().post(path, headers=headers, data="synthetic", content_type="text/plain")
    assert response.status_code == 415
    assert response.json == {"status": "error", "message": "Content-Type must be application/json"}


@pytest.mark.parametrize("invalid", [False, True])
def test_published_native_read_remains_available_and_evicts_only_invalid_session(invalid):
    from types import SimpleNamespace

    class Adapter:
        async def profile(self, session):
            if invalid:
                raise RuntimeError("401 token expired")
            return {"status": "ok"}

    app = Flask(__name__)
    app.register_blueprint(native_account_routes.native_accounts_bp)
    registry = BrokerRegistry()
    session = SimpleNamespace(account_id="synthetic", expires_at=4_102_444_800.0)
    other = SimpleNamespace(account_id="other", expires_at=4_102_444_800.0)
    registry.put_session("upstox", "synthetic", session)
    registry.put_session("upstox", "other", other)
    forbidden = Forbidden()
    app.config.update(REGISTRY=registry, NATIVE_ADAPTERS={"upstox": Adapter()}, CREDENTIAL_STORE=forbidden)
    response = app.test_client().get("/api/v1/native/accounts/upstox/synthetic/profile")
    assert response.status_code == (409 if invalid else 200)
    assert registry.get_session_for("upstox", "other") is other
    if invalid:
        with pytest.raises(BrokerNotFoundError):
            registry.get_session_for("upstox", "synthetic")
        assert app.config["NATIVE_SESSION_STATUS"] == {
            "upstox:synthetic": "Broker session expired or invalid; re-login required.",
        }
    else:
        assert registry.get_session_for("upstox", "synthetic") is session
    assert forbidden.calls == []


def test_ditto_default_manager_retains_reads_and_fenced_metadata_only_changes(tmp_path, monkeypatch):
    from flinttrade_ditto.account_manager import AccountManager, BrokerAccount
    from flinttrade_gateway.credentials import CredentialStore
    from flinttrade_core.broker_identity import BrokerSelector
    from flinttrade_core.secure_file import harden_directory

    harden_directory(tmp_path)
    store = CredentialStore(tmp_path / "vault.db", "synthetic-password")
    selector = BrokerSelector("openalgo", "synthetic")
    store.put_credentials(selector, "openalgo", "Synthetic", {"api_key": "synthetic-key"},
                          expected=store.selector_state(selector).version)
    kwargs = {
        "db_path": str(tmp_path / "metadata.db"),
        "credential_store": store,
        "installation_state_root": tmp_path / "installation",
    }
    with AccountManager(**kwargs, mutation_admission=lambda: None) as seed:
        seed.add_account(BrokerAccount("synthetic", "http://127.0.0.1:1", "synthetic-key"))
    credentials_before = store.retrieve_for("openalgo", "synthetic")
    with AccountManager(**kwargs) as manager:
        assert len(manager.list_accounts()) == 1
        manager.disable_account("synthetic")
        assert manager.get_account("synthetic").enabled is False
        manager.enable_account("synthetic")
        assert manager.get_account("synthetic").enabled is True
        app = Flask(__name__)
        app.register_blueprint(operations_routes.operations_bp)
        monkeypatch.setattr(operations_routes, "_ditto_manager", lambda: manager)
        monkeypatch.setattr(operations_routes, "_quiesce_ditto_account_generation", lambda _account: None)
        with app.app_context():
            headers = {"Authorization": f"Bearer {auth_routes._create_token('synthetic', mode='explore')}"}
        client = app.test_client()
        assert client.get("/api/v1/ditto/accounts").status_code == 200
        for action, expected in (("disable", False), ("enable", True)):
            response = client.post(f"/api/v1/ditto/accounts/synthetic/{action}", headers=headers)
            assert response.status_code == 200, response.json
            assert manager.get_account("synthetic").enabled is expected
    assert store.retrieve_for("openalgo", "synthetic") == credentials_before
