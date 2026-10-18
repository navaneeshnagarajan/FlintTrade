"""Public HTTP security regressions; synthetic inputs and inert failures only."""
from __future__ import annotations

from types import SimpleNamespace

import pytest
from flask import Flask

pytestmark = pytest.mark.integration
PRIVATE = "/synthetic/private/config.sqlite password=synthetic-password\nTraceback: sentinel"


@pytest.fixture
def http_app(monkeypatch, tmp_path):
    from flinttrade_core import auth_routes
    from flinttrade_core.auth_scopes import DEFAULT_SESSION_SCOPES

    app = Flask(__name__)
    app.config.update(TESTING=True)
    monkeypatch.setenv("FLINTTRADE_WORKSPACE_DIR", str(tmp_path))
    monkeypatch.setattr(auth_routes, "_JWT_SECRET_KEY", "")
    with app.app_context():
        token = auth_routes._create_token("synthetic-operator", scopes=DEFAULT_SESSION_SCOPES)
    return app, {"Authorization": "Bearer " + token}


def fail_with(error):
    def fail(*args, **kwargs):
        raise error
    return fail


@pytest.mark.parametrize("surface", ["execution", "model_guard", "configuration_denied", "configuration_conflict", "manifest"])
def test_http_unknown_exception_detail_is_never_public(http_app, monkeypatch, surface):
    from flinttrade_core import backtest_routes, execution_sessions_routes, model_control_auth, model_run_config

    app, headers = http_app
    error = model_control_auth.ModelControlDenied(PRIVATE)
    if surface == "execution":
        app.register_blueprint(execution_sessions_routes.execution_sessions_bp)
        monkeypatch.setattr(execution_sessions_routes, "principal", fail_with(error))
        response = app.test_client().get("/api/v1/execution-sessions", headers=headers)
        expected = (403, {"status": "error", "code": "model_control_refused"})
    elif surface == "model_guard":
        app.before_request(model_control_auth.guard_model_control)
        app.after_request(model_control_auth.model_control_no_store)
        app.config["MODEL_RUN_SERVICES"] = SimpleNamespace(authorise=fail_with(error))
        app.add_url_rule("/api/v1/backtest/adoptions/existing", view_func=lambda: {"unexpected": True})
        response = app.test_client().get("/api/v1/backtest/adoptions/existing", headers=headers)
        expected = (403, {"status": "error", "code": "model_control_refused"})
    elif surface.startswith("configuration"):
        if surface == "configuration_conflict":
            error = model_run_config.ConfigurationConflict(PRIVATE)
        app.register_blueprint(model_run_config.model_run_config_bp)
        configuration = SimpleNamespace(read=fail_with(error))
        app.config["MODEL_RUN_SERVICES"] = SimpleNamespace(configuration=lambda: configuration)
        response = app.test_client().get("/v1/model-runs/run/configuration", headers=headers)
        expected = ((409, {"code": "model_configuration_conflict"}) if surface.endswith("conflict")
                    else (403, {"code": "model_control_refused"}))
    else:
        app.register_blueprint(backtest_routes.backtest_bp)
        monkeypatch.setattr(backtest_routes, "_validate_manifest_request", fail_with(ValueError(PRIVATE)))
        response = app.test_client().post("/api/v1/backtest/run", json={"data_manifest_id": "a" * 64})
        expected = (400, {"status": "error", "message": "Invalid manifest request"})
    assert PRIVATE not in response.json.values(), "raw exception detail escaped HTTP"
    assert (response.status_code, response.json) == expected


@pytest.mark.parametrize("code", [
    "backtest_history_scope_changed", "backtest_run_owner_changed", "backtest_run_scope_changed",
    "backtest_run_scope_refused", "backtest_run_session_changed", "evaluation_owner_unavailable",
    "evaluation_scope_not_owned", "execution_scope_required", "loopback_required", "model_control_scope_required",
    "model_operation_not_authorised", "model_services_closed", "operation_forbidden", "operator_session_changed",
    "operator_session_required", "origin_forbidden", "run_not_owned", "run_producer_unavailable",
    "run_scope_not_owned", "sealed_access_not_authorised",
])
def test_http_known_denial_codes_remain_useful(http_app, code):
    from flinttrade_core import model_control_auth, model_run_config

    app, headers = http_app
    app.register_blueprint(model_run_config.model_run_config_bp)
    config = SimpleNamespace(read=fail_with(model_control_auth.ModelControlDenied(code)))
    app.config["MODEL_RUN_SERVICES"] = SimpleNamespace(configuration=lambda: config)
    response = app.test_client().get("/v1/model-runs/run/configuration", headers=headers)
    assert response.status_code == 403
    assert response.json == {"code": code}


@pytest.mark.parametrize("code", ["configuration_revision_changed", "confirmation_capacity_reached",
                                      "confirmation_invalid_or_consumed", "candidate_identity_changed"])
def test_http_known_conflict_codes_remain_useful(http_app, code):
    from flinttrade_core import model_run_config

    app, headers = http_app
    app.register_blueprint(model_run_config.model_run_config_bp)
    config = SimpleNamespace(read=fail_with(model_run_config.ConfigurationConflict(code)))
    app.config["MODEL_RUN_SERVICES"] = SimpleNamespace(configuration=lambda: config)
    response = app.test_client().get("/v1/model-runs/run/configuration", headers=headers)
    assert response.status_code == 409
    assert response.json == {"code": code}


@pytest.mark.parametrize(("change", "message"), [
    ({"unsupported": "untrusted"}, "Unsupported manifest request fields"),
    ({"data_manifest_id": "A" * 64}, "Canonical history manifest identity required"),
    ({"symbol": " TEST"}, "Explicit canonical manifest selectors required"),
    ({"start_date": None}, "Manifest dates must be strings"),
])
def test_http_manifest_validation_keeps_exact_refusals(http_app, change, message):
    from flinttrade_core.backtest_routes import backtest_bp

    app, _ = http_app
    app.register_blueprint(backtest_bp)
    body = {"data_manifest_id": "a" * 64, "symbol": "TEST", "exchange": "TEST", "interval": "1m",
            "strategy": "EMACrossover", **change}
    response = app.test_client().post("/api/v1/backtest/run", json=body)
    assert response.status_code == 400
    assert response.json == {"status": "error", "message": message}
