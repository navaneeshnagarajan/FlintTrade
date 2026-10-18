"""Normal-factory auth carrier and rotation regressions, with disposable state."""
from __future__ import annotations

import secrets

import jwt
import pytest

from flinttrade_core import auth_routes
from flinttrade_core.auth_scopes import LEGACY_NO_SCOPE_SESSION_SCOPES

pytestmark = pytest.mark.integration


@pytest.fixture
def app(monkeypatch, tmp_path):
    from flinttrade_core.app import create_flask_app

    monkeypatch.setenv("FLINTTRADE_WORKSPACE_DIR", str(tmp_path))
    monkeypatch.setenv("FLINTTRADE_API_KEY", secrets.token_urlsafe(32))
    app = create_flask_app()
    app.config.update(TESTING=True, RATELIMIT_ENABLED=False)
    limiter = app.config.get("LIMITER")
    if limiter is not None:
        limiter.enabled = False
    return app


def token(app, scopes):
    with app.app_context():
        raw = auth_routes._create_token("operator")
        key = auth_routes._get_jwt_secret()
        payload = jwt.decode(raw, key, algorithms=["HS256"])
        if scopes is ...:
            payload.pop("scopes")
        else:
            payload["scopes"] = scopes
        return jwt.encode(payload, key, algorithm="HS256")


@pytest.mark.parametrize("carrier", ["Authorization", "X-FlintTrade-Token"])
def test_normal_factory_narrowed_session_cannot_read_diagnostics(app, carrier):
    raw = token(app, [])
    headers = {carrier: f"Bearer {raw}" if carrier == "Authorization" else raw}
    response = app.test_client().get("/v1/support/diagnostics", headers=headers)
    assert response.status_code == 403


@pytest.mark.parametrize("scopes", [[], ["admin.health.read"], None, ...])
def test_practice_rotation_preserves_grants_and_retires_old_credential(app, scopes):
    raw = token(app, scopes)
    response = app.test_client().post(
        "/v1/auth/mode", json={"mode": "practice"}, headers={"Authorization": f"Bearer {raw}"}
    )
    assert response.status_code == 200
    with app.app_context():
        payload = auth_routes.decode_token(response.get_json()["data"]["token"])
        expected = LEGACY_NO_SCOPE_SESSION_SCOPES if scopes is ... else scopes or []
        assert payload["scopes"] == list(expected)
        assert payload["mode"] == "practice"
        assert payload["live_mode_unlocked"] is False
        with pytest.raises(jwt.InvalidTokenError):
            auth_routes.decode_token(raw)


@pytest.mark.parametrize("bearer_kind", ["broad", "reset", "empty"])
def test_competing_credentials_cannot_launder_narrowed_scope(app, bearer_kind):
    narrowed = token(app, [])
    bearer = token(app, ["admin.observability.read"])
    if bearer_kind == "reset":
        with app.app_context():
            bearer = auth_routes._create_reset_token("operator")
    elif bearer_kind == "empty":
        bearer = ""
    response = app.test_client().get(
        "/v1/support/diagnostics",
        headers={"Authorization": f"Bearer {bearer}", "X-FlintTrade-Token": narrowed},
    )
    assert response.status_code in (401, 403)


@pytest.mark.parametrize("failure", ["missing-jti", "storage"])
def test_logout_refuses_when_credential_retirement_is_not_proven(app, monkeypatch, failure):
    raw = token(app, [])
    if failure == "missing-jti":
        with app.app_context():
            key = auth_routes._get_jwt_secret()
            claims = jwt.decode(raw, key, algorithms=["HS256"])
            claims.pop("jti")
            raw = jwt.encode(claims, key, algorithm="HS256")
    else:
        def unavailable(*args):
            raise OSError("synthetic revocation unavailable")
        monkeypatch.setattr(auth_routes, "_revoke_jti", unavailable)
    response = app.test_client().post("/v1/auth/logout", headers={"X-FlintTrade-Token": raw})
    assert response.status_code == (400 if failure == "missing-jti" else 503)
    with app.app_context():
        assert auth_routes.decode_token(raw)["type"] == "session"


@pytest.mark.parametrize("credential", ["api-key", "reset-token", "conflicting"])
def test_logout_requires_one_full_session_target(app, monkeypatch, credential):
    monkeypatch.setenv("FLINTTRADE_API_KEY", "fixture-key")
    headers = {"X-API-Key": "fixture-key"}
    with app.app_context():
        if credential == "reset-token":
            headers["Authorization"] = "Bearer " + auth_routes._create_reset_token("operator")
        elif credential == "conflicting":
            headers["Authorization"] = "Bearer " + token(app, [])
            headers["X-FlintTrade-Token"] = token(app, [])
    response = app.test_client().post("/v1/auth/logout", headers=headers)
    assert response.status_code == 401


def test_logout_retires_only_presented_session_not_independent_credentials(app):
    raw = token(app, [])
    independent = token(app, [])
    response = app.test_client().post("/v1/auth/logout", headers={"X-FlintTrade-Token": raw})
    assert response.status_code == 200
    with app.app_context():
        with pytest.raises(jwt.InvalidTokenError):
            auth_routes.decode_token(raw)
        assert auth_routes.decode_token(independent)["type"] == "session"


@pytest.mark.parametrize("route", ["pin", "live"])
def test_pin_rotation_does_not_widen_scopes(app, route):
    import pyotp

    svc = app.config["AUTH_SERVICE"]
    svc.setup_account("operator", "operator@example.test", secrets.token_urlsafe(24), "123456")
    assert svc.enable_totp(pyotp.TOTP(svc.get_totp_secret()).now())
    raw = token(app, [])
    response = app.test_client().post(f"/v1/auth/{route}", json={"pin": "123456"},
                                      headers={"Authorization": f"Bearer {raw}"})
    assert response.status_code == 200
    with app.app_context():
        assert auth_routes.decode_token(response.get_json()["data"]["token"])["scopes"] == []
        with pytest.raises(jwt.InvalidTokenError):
            auth_routes.decode_token(raw)


def test_reset_token_cannot_inherit_scopes_from_competing_api_key(app, monkeypatch):
    monkeypatch.setenv("FLINTTRADE_API_KEY", "fixture-key")
    with app.app_context():
        raw = auth_routes._create_reset_token("operator")
    response = app.test_client().get("/v1/support/diagnostics", headers={
        "Authorization": f"Bearer {raw}", "X-API-Key": "fixture-key",
    })
    assert response.status_code == 401


@pytest.mark.parametrize("cold", [False, True])
def test_normal_factory_reset_preserves_mfa_or_reports_recovery_required(app, tmp_path, cold):
    import pyotp
    from flinttrade_core.auth_service import AuthService

    path = tmp_path / "reset.sqlite"
    svc = AuthService(db_path=path)
    old, new = secrets.token_urlsafe(24), secrets.token_urlsafe(24)
    svc.setup_account("operator", "operator@example.test", old)
    secret = svc.get_totp_secret()
    assert svc.enable_totp(pyotp.TOTP(secret).now())
    app.config["AUTH_SERVICE"] = svc
    with app.app_context():
        raw = auth_routes._create_reset_token("operator")
        old_session = auth_routes._create_token("operator")
    if cold:
        svc.close()
        svc = AuthService(db_path=path)
        app.config["AUTH_SERVICE"] = svc
    try:
        response = app.test_client().post("/v1/auth/reset-password", json={"token": raw, "new_password": new})
        assert response.status_code == (409 if cold else 200)
        if cold:
            assert response.get_json()["code"] == "authenticator_recovery_required"
        else:
            with app.app_context(), pytest.raises(jwt.InvalidTokenError):
                auth_routes.decode_token(old_session)
    finally:
        svc.close()
    fresh = AuthService(db_path=path)
    try:
        assert fresh.verify_password(old if cold else new)
        assert fresh.verify_totp(pyotp.TOTP(secret).now())
    finally:
        fresh.close()
