"""Real factory cutover and persistent admission; disposable authorities only."""
from __future__ import annotations

import hashlib
import hmac
import secrets
import sqlite3
import time

import duckdb
import pytest

from flinttrade_core import app as app_module
from flinttrade_core.auth_state import get_auth_state, reset_singleton_for_tests
from flinttrade_core.workspace import Workspace
from flinttrade_webhooks.webhook_hmac import build_webhook_signature_payload
from flinttrade_webhooks.webhook_secret_store import WebhookSecretStore
from scripts.__tests__.test_auth_migration_integrity import auth_source, invoke

pytestmark = pytest.mark.integration


@pytest.fixture
def factory(tmp_path, monkeypatch):
    monkeypatch.setenv("FLINTTRADE_WORKSPACE_DIR", str(tmp_path))
    monkeypatch.setenv("FLINTTRADE_API_KEY", secrets.token_urlsafe(32))
    reset_singleton_for_tests()
    apps = []
    original = app_module.Flask.__init__

    def observed_init(self, *args, **kwargs):
        # Observe, never replace, real construction. Failed-factory REDs must
        # also release the shared owners created before the rejection.
        original(self, *args, **kwargs)
        apps.append(self)

    monkeypatch.setattr(app_module.Flask, "__init__", observed_init)

    def create(password=None):
        if password is not None:
            monkeypatch.setattr(app_module, "_MASTER_PASSWORD", password)
        app = app_module.create_flask_app()
        app.config["TESTING"] = True
        return app

    try:
        yield create
    finally:
        for app in reversed(apps):
            for key in ("MODEL_RUN_SERVICES", "DATA_RUNTIME", "LEARNING_CONSENT_LEDGER",
                        "KNOWLEDGE_RUNTIME", "SERVICE_TASK_DISPATCHER"):
                owner = app.config.pop(key, None)
                if owner is not None:
                    owner.close()
        reset_singleton_for_tests()


@pytest.mark.parametrize("migrated_hooks", [True, False])
def test_factory_uses_migrated_or_retained_webhook_authority(factory, tmp_path, migrated_hooks):
    hook = "/v1/webhook/custom/retained"
    password = secrets.token_urlsafe(32)
    secret = secrets.token_urlsafe(32)
    if not migrated_hooks:
        standalone = WebhookSecretStore(tmp_path / "webhook_secrets.db", password)
        standalone.store_secret(hook, "custom", "Retained fixture", secret)
        admitted = standalone.check_and_record_nonce(hook, "fixture-nonce", time.time())
        assert admitted is None
    source, password, key, migrated_secret = auth_source(tmp_path, with_hooks=migrated_hooks, password=password)
    if migrated_hooks:
        secret = migrated_secret
        with duckdb.connect(str(source), config={"threads": 1}) as db:
            db.execute("UPDATE webhooks SET path=?,webhook_id=?,source='custom'", (hook, hook.lstrip("/")))
            db.execute("UPDATE webhook_nonces SET webhook_id=?,seen_at=?", (hook.lstrip("/"), time.time()))
    key_file = tmp_path / "synthetic-legacy-key"
    key_file.write_bytes(key)
    result = invoke(tmp_path, password, "--legacy-fernet-key-path", str(key_file))
    assert result.returncode == 0, "synthetic public migration failed"
    key_file.unlink()
    workspace = Workspace(tmp_path)
    workspace.initialise()
    workspace.set("automation.webhooks", [
        {"id": "retained", "path": hook, "name": "Retained fixture", "type": "custom", "enabled": True},
    ])
    app = factory(password)
    store = app.config["WEBHOOK_SECRET_STORE"]
    expected = tmp_path / ("auth_state.sqlite" if migrated_hooks else "webhook_secrets.db")
    assert store._db_path == expected
    matches = hmac.compare_digest(store.get_secret(hook), secret)
    assert matches, "factory selected a different signing authority"
    assert get_auth_state().is_jti_revoked("synthetic-jti")
    assert get_auth_state()._db_path == tmp_path / "auth_state.sqlite"
    raw = b'{"action":"signal","symbol":"SYNTHETIC","exchange":"NSE"}'
    timestamp = str(time.time())
    signature = hmac.new(secret.encode(), build_webhook_signature_payload(
        raw, nonce="fixture-nonce", timestamp=timestamp), hashlib.sha256).hexdigest()
    response = app.test_client().post(hook, data=raw, content_type="application/json", headers={
        "X-Signature": "sha256=" + signature,
        "X-Webhook-Nonce": "fixture-nonce", "X-Webhook-Timestamp": timestamp,
    })
    assert response.status_code == 409
    assert response.json["message"] == "Webhook replay rejected"
    with sqlite3.connect(expected) as db:
        assert db.execute("SELECT count(*) FROM webhook_nonces WHERE nonce='fixture-nonce'").fetchone() == (1,)
    assert not source.exists()
    if migrated_hooks:
        assert not (tmp_path / "webhook_secrets.db").exists()


def test_normal_factory_limiter_honours_the_persistent_login_budget(factory):
    app = factory()
    assert app.config["LIMITER"] is not None
    state = get_auth_state()
    for _ in range(5):
        assert state.check_rate_limit("auth_login", "127.0.0.1", 5, 60)
    response = app.test_client().post("/v1/auth/login", json={})
    assert response.status_code == 429, "a fresh Flask-Limiter must not reset durable auth admission"


def test_normal_factory_limiter_refuses_lost_auth_authority(factory):
    app = factory()
    state = get_auth_state()
    with sqlite3.connect(state._db_path) as db:
        db.execute("DROP TABLE otp_requests")
    response = app.test_client().post("/v1/auth/login", json={})
    assert response.status_code == 429, "configured HTTP limiter bypassed lost persistent authority"


def test_normal_factory_login_attempts_are_persisted_before_validation(factory):
    app = factory()
    response = app.test_client().post("/v1/auth/login", json={})
    assert response.status_code == 401
    assert response.json["message"] == "Invalid credentials."
    with sqlite3.connect(get_auth_state()._db_path) as db:
        assert db.execute("SELECT count(*) FROM rate_limit_events WHERE endpoint='auth_login'").fetchone() == (1,)
