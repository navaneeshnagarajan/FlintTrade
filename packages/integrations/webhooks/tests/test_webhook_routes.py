"""Tests for packages/integrations/webhooks/src/webhook_routes.py — webhook receiver endpoints."""

from __future__ import annotations

import json
import threading
import time
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from flask import Flask

import flinttrade_webhooks.webhook_routes as mod
from flinttrade_webhooks.webhook_receiver import WebhookConfig
from flinttrade_webhooks.webhook_hmac import build_webhook_signature_payload
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


def test_receive_gocharting_ok(client):
    """200 for a valid GoCharting webhook — routes through the shared gate."""
    payload = {"symbol": "NIFTY", "exchange": "NSE", "product": "MIS", "action": "BUY", "quantity": 50}
    with patch(
        "flinttrade_webhooks.webhook_routes._run_dispatch",
        return_value={"status": "executed", "order_id": "OID123"},
    ):
        resp = client.post(
            "/v1/webhook/gocharting",
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


def test_bad_signature_does_not_consume_authenticated_rate_limit():
    """Unauthenticated traffic cannot starve valid signed relays."""
    flask_app = Flask(__name__)
    flask_app.config["TESTING"] = True
    receiver = _mock_receiver(sig_ok=False)
    mod.init_webhook_routes(receiver)
    flask_app.register_blueprint(mod.webhook_bp)

    with flask_app.test_client() as c:
        resp = c.post(
            "/v1/webhook/tradingview",
            data=json.dumps({"symbol": "NIFTY"}),
            content_type="application/json",
        )

    assert resp.status_code == 401
    receiver.check_rate_limit.assert_not_called()


def test_unregistered_named_path_does_not_consume_authenticated_rate_limit():
    """Unknown endpoint probes are rejected before shared quota accounting."""
    flask_app = Flask(__name__)
    flask_app.config["TESTING"] = True
    receiver = _mock_receiver()
    mod.init_webhook_routes(receiver, endpoint_status_provider=lambda _path: None)
    flask_app.register_blueprint(mod.webhook_bp)

    with flask_app.test_client() as c:
        resp = c.post(
            "/v1/webhook/custom/not-registered",
            data=json.dumps({"symbol": "NIFTY"}),
            content_type="application/json",
        )

    assert resp.status_code == 404
    receiver.check_rate_limit.assert_not_called()


def test_stale_signed_request_does_not_consume_authenticated_rate_limit(tmp_path):
    """Captured signed traffic is rejected before shared quota accounting."""
    secret = "stale-quota-secret"
    path = "/v1/webhook/custom/stale-quota"
    store = WebhookSecretStore(tmp_path / "webhooks.db", "test-master-password")
    store.store_secret(path, "custom", "Stale quota", secret)
    receiver = MagicMock()
    receiver._config = WebhookConfig(rate_limit=1)
    receiver.verify_signature.return_value = True
    receiver.check_rate_limit.return_value = True
    flask_app = Flask(__name__)
    flask_app.config["TESTING"] = True
    mod.init_webhook_routes(
        receiver,
        secret_store=store,
        endpoint_status_provider=lambda candidate: candidate == path,
    )
    flask_app.register_blueprint(mod.webhook_bp)
    body = json.dumps({"action": "signal", "symbol": "NIFTY"}).encode()

    with flask_app.test_client() as c:
        stale = c.post(
            path,
            data=body,
            headers={
                "Content-Type": "application/json",
                "X-Signature": "sha256=accepted-by-mock",
                "X-Webhook-Nonce": "captured-stale-nonce",
                "X-Webhook-Timestamp": str(time.time() - 600),
            },
        )

    assert stale.status_code == 400
    receiver.check_rate_limit.assert_not_called()


def test_receive_named_endpoint_disabled_by_registry():
    """503 when the mounted endpoint registry marks a named endpoint disabled."""
    flask_app = Flask(__name__)
    flask_app.config["TESTING"] = True
    provider = MagicMock(return_value=False)
    mod.init_webhook_routes(_mock_receiver(), endpoint_status_provider=provider)
    flask_app.register_blueprint(mod.webhook_bp)
    with flask_app.test_client() as c:
        resp = c.post(
            "/v1/webhook/custom/disabled-signal",
            data=json.dumps({"symbol": "NIFTY"}),
            content_type="application/json",
        )
    assert resp.status_code == 503
    assert resp.get_json()["message"] == "Webhook endpoint disabled"
    provider.assert_called_once_with("/v1/webhook/custom/disabled-signal")


def test_receive_named_endpoint_registry_failure_fails_closed():
    """503 when endpoint status cannot be checked."""
    flask_app = Flask(__name__)
    flask_app.config["TESTING"] = True

    def _boom(_path: str) -> bool:
        raise RuntimeError("workspace locked")

    mod.init_webhook_routes(_mock_receiver(), endpoint_status_provider=_boom)
    flask_app.register_blueprint(mod.webhook_bp)
    with flask_app.test_client() as c:
        resp = c.post(
            "/v1/webhook/custom/registry-error",
            data=json.dumps({"symbol": "NIFTY"}),
            content_type="application/json",
        )
    assert resp.status_code == 503
    assert resp.get_json()["message"] == "Webhook endpoint registry unavailable"


def test_receive_invalid_json(client):
    """400 for a body that is neither JSON nor valid provider text."""
    resp = client.post(
        "/v1/webhook/tradingview",
        data=b"\xff",
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

        ts = str(time.time() if timestamp is None else timestamp)
        signed_payload = build_webhook_signature_payload(body, nonce=nonce, timestamp=ts)
        return {
            "Content-Type": "application/json",
            "X-Signature": "sha256=" + hmac.new(_SECRET.encode(), signed_payload, hashlib.sha256).hexdigest(),
            "X-Webhook-Nonce": nonce,
            "X-Webhook-Timestamp": ts,
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

    def test_rate_limited_signed_intent_can_retry_same_nonce(self, tmp_path):
        from flinttrade_webhooks.webhook_receiver import WebhookReceiver

        path = "/v1/webhook/custom/quota-retry"
        store = WebhookSecretStore(tmp_path / "webhook_secrets.db", "test-master-password")
        store.store_secret(path, "custom", "Quota retry", _SECRET)
        receiver = WebhookReceiver(WebhookConfig(secret="", rate_limit=1))
        receiver.check_rate_limit = MagicMock(side_effect=[False, True])
        mod.init_webhook_routes(receiver, secret_store=store)
        flask_app = Flask("signed_webhook_quota_retry")
        flask_app.config["TESTING"] = True
        flask_app.register_blueprint(mod.webhook_bp)
        body = json.dumps({"action": "signal", "symbol": "TCS"}).encode()
        headers = self._headers(body, nonce="quota-retry-nonce")

        with flask_app.test_client() as client:
            limited = client.post(path, data=body, headers=headers)
            retried = client.post(path, data=body, headers=headers)
            replay = client.post(path, data=body, headers=headers)

        assert limited.status_code == 429
        assert retried.status_code == 200
        assert replay.status_code == 409
        assert receiver.check_rate_limit.call_count == 2

    def test_concurrent_replay_loser_does_not_consume_quota(self, tmp_path):
        from flinttrade_webhooks.webhook_receiver import WebhookReceiver

        path = "/v1/webhook/custom/concurrent-replay"
        store = WebhookSecretStore(tmp_path / "webhook_secrets.db", "test-master-password")
        store.store_secret(path, "custom", "Concurrent replay", _SECRET)
        receiver = WebhookReceiver(WebhookConfig(secret="", rate_limit=2))
        rate_entered = threading.Event()
        release_rate = threading.Event()

        def blocking_rate_check() -> bool:
            rate_entered.set()
            return release_rate.wait(timeout=5)

        receiver.check_rate_limit = MagicMock(side_effect=blocking_rate_check)
        mod.init_webhook_routes(receiver, secret_store=store)
        flask_app = Flask("signed_webhook_concurrent_replay")
        flask_app.config["TESTING"] = True
        flask_app.register_blueprint(mod.webhook_bp)
        body = json.dumps({"action": "signal", "symbol": "TCS"}).encode()
        headers = self._headers(body, nonce="concurrent-replay-nonce")
        first_result: dict[str, object] = {}

        def post_first() -> None:
            with flask_app.test_client() as client:
                first_result["response"] = client.post(path, data=body, headers=headers)

        first = threading.Thread(target=post_first)
        first.start()
        assert rate_entered.wait(timeout=5)

        with flask_app.test_client() as client:
            replay = client.post(path, data=body, headers=headers)
        release_rate.set()
        first.join(timeout=5)

        assert not first.is_alive()
        assert first_result["response"].status_code == 200
        assert replay.status_code == 409
        assert receiver.check_rate_limit.call_count == 1

    def test_captured_body_signature_cannot_be_replayed_with_fresh_headers(self, signed_client):
        body = json.dumps({"action": "signal", "symbol": "TCS"}).encode()
        captured = self._headers(body, nonce="captured-nonce")
        forged = dict(captured)
        forged["X-Webhook-Nonce"] = "fresh-nonce"
        forged["X-Webhook-Timestamp"] = str(time.time())

        resp = signed_client.post("/v1/webhook/custom/signed", data=body, headers=forged)

        assert resp.status_code == 401
        assert resp.get_json()["message"] == "Signature verification failed"

    def test_unregistered_named_endpoint_is_rejected_even_with_orphan_secret(self, tmp_path):
        from flinttrade_webhooks.webhook_receiver import WebhookReceiver

        flask_app = Flask("orphan_webhook_secret")
        flask_app.config["TESTING"] = True
        store = WebhookSecretStore(tmp_path / "webhook_secrets.db", "test-master-password")
        store.store_secret("/v1/webhook/custom/orphan", "custom", "Orphan", _SECRET)
        mod.init_webhook_routes(
            WebhookReceiver(WebhookConfig(secret="", rate_limit=100)),
            secret_store=store,
            endpoint_status_provider=lambda _path: None,
        )
        flask_app.register_blueprint(mod.webhook_bp)
        body = json.dumps({"action": "signal", "symbol": "TCS"}).encode()

        resp = flask_app.test_client().post(
            "/v1/webhook/custom/orphan",
            data=body,
            headers=self._headers(body, nonce="orphan-nonce"),
        )

        assert resp.status_code == 404
        assert resp.get_json()["message"] == "Webhook endpoint is not registered"

    def test_signed_order_webhook_threads_verified_nonce_to_dispatcher(self, tmp_path):
        from flinttrade_webhooks.webhook_receiver import WebhookPayload, WebhookReceiver

        captured: dict[str, WebhookPayload] = {}

        def _place_dispatcher(payload: WebhookPayload) -> dict[str, object]:
            captured["payload"] = payload
            return {"status": "placed", "action": "place_order", "symbol": payload.symbol}

        flask_app = Flask("signed_order_dispatch")
        flask_app.config["TESTING"] = True
        store = WebhookSecretStore(tmp_path / "webhook_secrets.db", "test-master-password")
        store.store_secret(
            "/v1/webhook/tradingview/order-signal",
            "tradingview",
            "Order Signal",
            _SECRET,
        )
        mod.init_webhook_routes(
            WebhookReceiver(
                WebhookConfig(secret="", rate_limit=100),
                order_dispatcher=_place_dispatcher,
            ),
            secret_store=store,
        )
        flask_app.register_blueprint(mod.webhook_bp)

        body = json.dumps({"action": "BUY", "symbol": "NIFTY", "exchange": "NSE"}).encode()
        resp = flask_app.test_client().post(
            "/v1/webhook/tradingview/order-signal",
            data=body,
            headers=self._headers(body, nonce="order-nonce-verified"),
        )

        assert resp.status_code == 200
        assert resp.get_json()["data"]["status"] == "placed"
        assert captured["payload"].webhook_nonce == "order-nonce-verified"
        assert captured["payload"].webhook_path == "/v1/webhook/tradingview/order-signal"

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

    @pytest.mark.parametrize("timestamp", [float("nan"), float("inf"), float("-inf")])
    def test_signed_named_webhook_rejects_non_finite_timestamp(self, signed_client, timestamp):
        body = json.dumps({"action": "signal", "symbol": "TCS"}).encode()
        resp = signed_client.post(
            "/v1/webhook/custom/signed",
            data=body,
            headers=self._headers(body, nonce=f"non-finite-{timestamp}", timestamp=timestamp),
        )

        assert resp.status_code == 400
        assert "nonce and timestamp" in resp.get_json()["message"]

    def test_signed_place_order_still_fails_honestly(self, signed_client):
        body = json.dumps({"action": "BUY", "symbol": "NIFTY", "exchange": "NSE"}).encode()
        resp = signed_client.post(
            "/v1/webhook/tradingview/order-signal",
            data=body,
            headers=self._headers(body, nonce="order-nonce-1"),
        )
        assert resp.status_code == 422
        body = resp.get_json()
        assert body["status"] == "error"
        assert body["data"]["action"] == "place_order"
        assert "no order was placed" in body["message"]

    def test_signed_text_tradingview_payload_reaches_canonical_parser(self, tmp_path):
        from flinttrade_webhooks.webhook_receiver import WebhookReceiver

        flask_app = Flask("signed_text_tradingview")
        flask_app.config["TESTING"] = True
        store = WebhookSecretStore(tmp_path / "webhook_secrets.db", "test-master-password")
        store.store_secret("/v1/webhook/tradingview/text-order", "tradingview", "Text Order", _SECRET)
        mod.init_webhook_routes(
            WebhookReceiver(WebhookConfig(secret="", rate_limit=100)),
            secret_store=store,
        )
        flask_app.register_blueprint(mod.webhook_bp)

        body = b"BUY BANKNIFTY NFO 30 LIMIT 51000"
        resp = flask_app.test_client().post(
            "/v1/webhook/tradingview/text-order",
            data=body,
            headers=self._headers(body, nonce="text-order-1"),
        )

        assert resp.status_code == 422
        payload = resp.get_json()["data"]
        assert payload["action"] == "place_order"
        assert payload["symbol"] == "BANKNIFTY"

    def test_signed_chartink_csv_payload_reaches_canonical_parser(self, tmp_path):
        from flinttrade_webhooks.webhook_receiver import WebhookReceiver

        flask_app = Flask("signed_csv_chartink")
        flask_app.config["TESTING"] = True
        store = WebhookSecretStore(tmp_path / "webhook_secrets.db", "test-master-password")
        store.store_secret("/v1/webhook/chartink/csv-scan", "chartink", "CSV Scan", _SECRET)
        mod.init_webhook_routes(
            WebhookReceiver(WebhookConfig(secret="", rate_limit=100)),
            secret_store=store,
        )
        flask_app.register_blueprint(mod.webhook_bp)

        body = b"NSE:RELIANCE-EQ,TCS,INFY-BE"
        resp = flask_app.test_client().post(
            "/v1/webhook/chartink/csv-scan",
            data=body,
            headers=self._headers(body, nonce="csv-scan-1"),
        )

        assert resp.status_code == 200
        payload = resp.get_json()["data"]
        assert payload["status"] == "received"
        assert payload["symbol"] == "RELIANCE"

    def test_signed_gocharting_text_payload_reaches_canonical_parser(self, tmp_path):
        from flinttrade_webhooks.webhook_receiver import WebhookReceiver

        flask_app = Flask("signed_text_gocharting")
        flask_app.config["TESTING"] = True
        store = WebhookSecretStore(tmp_path / "webhook_secrets.db", "test-master-password")
        store.store_secret("/v1/webhook/gocharting/text-order", "gocharting", "Text Order", _SECRET)
        mod.init_webhook_routes(
            WebhookReceiver(WebhookConfig(secret="", rate_limit=100)),
            secret_store=store,
        )
        flask_app.register_blueprint(mod.webhook_bp)

        body = b"BUY BANKNIFTY NFO 30 LIMIT 51000"
        resp = flask_app.test_client().post(
            "/v1/webhook/gocharting/text-order",
            data=body,
            headers=self._headers(body, nonce="gocharting-text-order-1"),
        )

        assert resp.status_code == 422
        payload = resp.get_json()["data"]
        assert payload["action"] == "place_order"
        assert payload["symbol"] == "BANKNIFTY"
