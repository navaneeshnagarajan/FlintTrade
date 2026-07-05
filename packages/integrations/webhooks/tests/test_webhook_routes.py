"""Tests for packages/integrations/webhooks/src/webhook_routes.py — webhook receiver endpoints."""

from __future__ import annotations

import json
import time
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from flask import Flask

import flinttrade_webhooks.webhook_routes as mod
from flinttrade_webhooks.webhook_receiver import WebhookConfig
from flinttrade_webhooks.webhook_secret_store import WebhookSecretStore


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

_SECRET = "test-webhook-secret"


def _mock_receiver(rate_ok: bool = True, sig_ok: bool = True) -> MagicMock:
    receiver = MagicMock()
    receiver.check_rate_limit.return_value = rate_ok
    receiver.verify_signature.return_value = sig_ok
    receiver._config = WebhookConfig(secret=_SECRET, require_signature=False)
    receiver._config.allowed_sources = {"tradingview", "chartink", "custom"}

    dispatch_result = {
        "status": "executed",
        "order_id": "OID123",
        "symbol": "NIFTY",
    }
    receiver.dispatch = AsyncMock(return_value=dispatch_result)

    history_entry = MagicMock()
    history_entry.timestamp = "2026-04-19T10:00:00"
    history_entry.source = "tradingview"
    history_entry.status = "executed"
    history_entry.payload = {"symbol": "NIFTY"}
    receiver.get_history.return_value = [history_entry]
    # recent_log must return JSON-serialisable dicts for the log endpoint
    receiver.recent_log.return_value = [
        {
            "timestamp": "2026-04-19T10:00:00",
            "source": "tradingview",
            "status": "executed",
        }
    ]
    # rate_limit_remaining must be an int for JSON serialisation
    receiver.rate_limit_remaining = 59
    return receiver


@pytest.fixture()
def app():
    flask_app = Flask(__name__)
    flask_app.config["TESTING"] = True
    mod.init_webhook_routes(_mock_receiver())
    flask_app.register_blueprint(mod.webhook_bp)
    return flask_app


@pytest.fixture()
def client(app):
    return app.test_client()


# ---------------------------------------------------------------------------
# POST /ft-api/v1/webhook/<source>
# ---------------------------------------------------------------------------


def test_receive_tradingview_ok(client):
    """200 for a valid tradingview webhook."""
    payload = {"symbol": "NIFTY", "action": "BUY", "qty": 50}
    with patch(
        "flinttrade_webhooks.webhook_routes._run_dispatch",
        return_value={"status": "executed", "order_id": "OID123"},
    ):
        resp = client.post(
            "/v1/webhook/tradingview",
            data=json.dumps(payload),
            content_type="application/json",
        )
    assert resp.status_code == 200
    body = resp.get_json()
    assert body["status"] in {"success", "error", "executed"}


def test_receive_named_chartink_endpoint_ok(client):
    """Named registry endpoints dispatch through the same receiver path."""
    payload = {"symbol": "NIFTY", "action": "BUY", "qty": 50}
    with patch(
        "flinttrade_webhooks.webhook_routes._run_dispatch",
        return_value={"status": "executed", "order_id": "OID123"},
    ):
        resp = client.post(
            "/v1/webhook/chartink/scan1",
            data=json.dumps(payload),
            content_type="application/json",
        )
    assert resp.status_code == 200
    assert resp.get_json()["status"] == "success"


def test_receive_invalid_source(client):
    """404 for unknown webhook source."""
    resp = client.post(
        "/v1/webhook/unknownsource",
        data=json.dumps({"symbol": "NIFTY"}),
        content_type="application/json",
    )
    assert resp.status_code == 404


def test_receive_rate_limited():
    """429 when rate limit exceeded."""
    flask_app = Flask(__name__)
    flask_app.config["TESTING"] = True
    mod.init_webhook_routes(_mock_receiver(rate_ok=False))
    flask_app.register_blueprint(mod.webhook_bp)
    with flask_app.test_client() as c:
        resp = c.post(
            "/v1/webhook/tradingview",
            data=json.dumps({"symbol": "NIFTY"}),
            content_type="application/json",
        )
    assert resp.status_code == 429


def test_receive_invalid_json(client):
    """400 for non-JSON body."""
    resp = client.post(
        "/v1/webhook/tradingview",
        data=b"not-json",
        content_type="text/plain",
    )
    assert resp.status_code == 400


# ---------------------------------------------------------------------------
# GET /ft-api/v1/webhook/log
# ---------------------------------------------------------------------------


def test_log_ok(client):
    """200 with webhook history list."""
    resp = client.get("/v1/webhook/log")
    assert resp.status_code == 200
    body = resp.get_json()
    assert body["status"] == "success"
    assert "entries" in body["data"]


class TestNamedWebhookSecrets:
    @pytest.fixture()
    def signed_client(self, tmp_path):
        from flinttrade_webhooks.webhook_receiver import WebhookReceiver

        flask_app = Flask("signed_webhooks")
        flask_app.config["TESTING"] = True
        store = WebhookSecretStore(tmp_path / "webhook_secrets.db", "test-master-password")
        store.store_secret(
            "/v1/webhook/custom/signed",
            "custom",
            "Signed",
            _SECRET,
        )
        store.store_secret(
            "/v1/webhook/tradingview/order-signal",
            "tradingview",
            "Order Signal",
            _SECRET,
        )
        mod.init_webhook_routes(
            WebhookReceiver(WebhookConfig(secret="", rate_limit=100)),
            secret_store=store,
        )
        flask_app.register_blueprint(mod.webhook_bp)
        return flask_app.test_client()

    def _headers(self, body: bytes, nonce: str = "nonce-1", timestamp: float | None = None) -> dict[str, str]:
        import hashlib
        import hmac

        ts = time.time() if timestamp is None else timestamp
        return {
            "Content-Type": "application/json",
            "X-Signature": "sha256=" + hmac.new(_SECRET.encode(), body, hashlib.sha256).hexdigest(),
            "X-Webhook-Nonce": nonce,
            "X-Webhook-Timestamp": str(ts),
        }

    def test_signed_named_webhook_dispatches_and_replay_is_rejected(self, signed_client):
        body = json.dumps({"action": "signal", "symbol": "TCS"}).encode()
        headers = self._headers(body)
        first = signed_client.post("/v1/webhook/custom/signed", data=body, headers=headers)
        assert first.status_code == 200
        assert first.get_json()["data"]["status"] == "received"

        replay = signed_client.post("/v1/webhook/custom/signed", data=body, headers=headers)
        assert replay.status_code == 409
        assert replay.get_json()["message"] == "Webhook replay rejected"

    def test_signed_named_webhook_rejects_bad_signature(self, signed_client):
        body = json.dumps({"action": "signal", "symbol": "TCS"}).encode()
        headers = self._headers(body)
        headers["X-Signature"] = "sha256=" + "0" * 64
        resp = signed_client.post("/v1/webhook/custom/signed", data=body, headers=headers)
        assert resp.status_code == 401

    def test_signed_named_webhook_requires_nonce_and_timestamp(self, signed_client):
        body = json.dumps({"action": "signal", "symbol": "TCS"}).encode()
        headers = self._headers(body)
        headers.pop("X-Webhook-Nonce")
        resp = signed_client.post("/v1/webhook/custom/signed", data=body, headers=headers)
        assert resp.status_code == 400
        assert "nonce and timestamp" in resp.get_json()["message"]

    def test_signed_place_order_still_fails_honestly(self, signed_client):
        body = json.dumps({"action": "BUY", "symbol": "NIFTY", "exchange": "NSE"}).encode()
        resp = signed_client.post(
            "/v1/webhook/tradingview/order-signal",
            data=body,
            headers=self._headers(body, nonce="order-nonce-1"),
        )
        assert resp.status_code == 200
        data = resp.get_json()["data"]
        assert data["status"] == "error"
        assert data["action"] == "place_order"
        assert "no order was placed" in data["message"]
