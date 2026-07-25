"""Tests for webhook_receiver.py and webhook_routes.py.

All tests are purely in-process.  No HTTP calls are made to external services.
Uses pytest with --import-mode=importlib.

Coverage targets:
- WebhookConfig validation
- WebhookPayload validation and field normalisation
- verify_signature: valid, invalid, no-secret, empty-signature
- parse_custom: generic JSON
- _SlidingWindowLimiter: allow, reject, remaining
- WebhookReceiver.check_rate_limit
- WebhookReceiver.dispatch: place_order, cancel_order, alert, signal, unknown
- WebhookReceiver.recent_log: limit, cap
- Flask routes: POST /webhook/<source> happy + error paths
- Flask routes: GET /webhook/log
"""

from __future__ import annotations

import asyncio
import hashlib
import hmac
import json
import time

import pytest

# ---------------------------------------------------------------------------
# Imports
# ---------------------------------------------------------------------------

from flinttrade_webhooks.webhook_receiver import (
    WebhookConfig,
    WebhookLogEntry,
    WebhookPayload,
    WebhookReceiver,
    _SlidingWindowLimiter,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _sign(body: bytes, secret: str) -> str:
    """Produce a sha256=<hex> signature for a payload."""
    digest = hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()
    return f"sha256={digest}"


def _make_receiver(
    secret: str = "",
    rate_limit: int = 100,
    log_payloads: bool = True,
) -> WebhookReceiver:
    cfg = WebhookConfig(secret=secret, rate_limit=rate_limit, log_payloads=log_payloads)
    return WebhookReceiver(cfg)


def _run(coro):
    """Run a coroutine synchronously."""
    return asyncio.run(coro)


# ---------------------------------------------------------------------------
# WebhookConfig
# ---------------------------------------------------------------------------


class TestWebhookConfig:
    def test_defaults(self):
        cfg = WebhookConfig()
        assert cfg.secret == ""
        assert cfg.allowed_sources == ["custom"]
        assert cfg.rate_limit == 60
        assert cfg.log_payloads is True

    def test_custom(self):
        cfg = WebhookConfig(secret="abc", rate_limit=10, log_payloads=False)
        assert cfg.secret == "abc"
        assert cfg.rate_limit == 10
        assert cfg.log_payloads is False

    def test_rate_limit_zero_raises(self):
        with pytest.raises(Exception):
            WebhookConfig(rate_limit=0)


# ---------------------------------------------------------------------------
# WebhookPayload
# ---------------------------------------------------------------------------


class TestWebhookPayload:
    def test_action_normalised_lowercase(self):
        p = WebhookPayload(source="custom", action="PLACE_ORDER")
        assert p.action == "place_order"

    def test_source_normalised_lowercase(self):
        p = WebhookPayload(source="Custom", action="signal")
        assert p.source == "custom"

    def test_defaults(self):
        p = WebhookPayload(source="custom", action="alert")
        assert p.symbol is None
        assert p.exchange is None
        assert p.data == {}
        assert p.timestamp is not None

    def test_data_preserved(self):
        p = WebhookPayload(source="custom", action="signal", data={"qty": 50})
        assert p.data["qty"] == 50


# ---------------------------------------------------------------------------
# verify_signature
# ---------------------------------------------------------------------------


class TestVerifySignature:
    def test_no_secret_rejects_when_skip_false(self):
        """Empty secret with skip_verification=False (default) must return False."""
        r = _make_receiver(secret="")
        assert r.verify_signature(b"payload", "sha256=wrongsig") is False

    def test_no_secret_skip_verification_true(self):
        """skip_verification=True bypasses HMAC check regardless of secret."""
        cfg = WebhookConfig(secret="", skip_verification=True)
        r = WebhookReceiver(cfg)
        assert r.verify_signature(b"payload", "sha256=wrongsig") is True

    def test_valid_signature(self):
        secret = "my-secret"
        body = b'{"action": "BUY"}'
        r = _make_receiver(secret=secret)
        sig = _sign(body, secret)
        assert r.verify_signature(body, sig) is True

    def test_invalid_signature(self):
        r = _make_receiver(secret="secret")
        assert r.verify_signature(b"data", "sha256=deadbeef") is False

    def test_wrong_secret(self):
        body = b"hello"
        r = _make_receiver(secret="right-secret")
        sig = _sign(body, "wrong-secret")
        assert r.verify_signature(body, sig) is False

    def test_empty_signature_returns_false_when_secret_set(self):
        r = _make_receiver(secret="mysecret")
        assert r.verify_signature(b"data", "") is False

    def test_plain_hex_accepted(self):
        """Signature without sha256= prefix should still work."""
        secret = "testsecret"
        body = b"testbody"
        r = _make_receiver(secret=secret)
        plain_hex = hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()
        assert r.verify_signature(body, plain_hex) is True


# ---------------------------------------------------------------------------
# parse_custom
# ---------------------------------------------------------------------------


class TestParseCustom:
    def test_basic_signal(self):
        r = _make_receiver()
        payload = r.parse_custom({"action": "alert", "message": "EMA cross"})
        assert payload.source == "custom"
        assert payload.action == "alert"
        assert payload.data["message"] == "EMA cross"

    def test_default_action_is_signal(self):
        r = _make_receiver()
        payload = r.parse_custom({"symbol": "NIFTY"})
        assert payload.action == "signal"

    def test_ticker_field_used_as_symbol(self):
        r = _make_receiver()
        payload = r.parse_custom({"ticker": "GOLD"})
        assert payload.symbol == "GOLD"

    def test_symbol_uppercased(self):
        r = _make_receiver()
        payload = r.parse_custom({"symbol": "reliance"})
        assert payload.symbol == "RELIANCE"

    def test_exchange_uppercased(self):
        r = _make_receiver()
        payload = r.parse_custom({"exchange": "mcx", "symbol": "CRUDEOIL"})
        assert payload.exchange == "MCX"

    def test_extra_fields_in_data(self):
        r = _make_receiver()
        payload = r.parse_custom({"action": "signal", "rsi": 72, "macd": 0.5})
        assert payload.data["rsi"] == 72
        assert payload.data["macd"] == 0.5


# ---------------------------------------------------------------------------
# _SlidingWindowLimiter
# ---------------------------------------------------------------------------


class TestSlidingWindowLimiter:
    def test_allows_within_limit(self):
        limiter = _SlidingWindowLimiter(max_requests=5, window_seconds=60.0)
        for _ in range(5):
            assert limiter.allow() is True

    def test_rejects_when_limit_reached(self):
        limiter = _SlidingWindowLimiter(max_requests=3, window_seconds=60.0)
        for _ in range(3):
            limiter.allow()
        assert limiter.allow() is False

    def test_remaining_decrements(self):
        limiter = _SlidingWindowLimiter(max_requests=10, window_seconds=60.0)
        assert limiter.remaining == 10
        limiter.allow()
        assert limiter.remaining == 9

    def test_remaining_never_negative(self):
        limiter = _SlidingWindowLimiter(max_requests=2, window_seconds=60.0)
        for _ in range(5):
            limiter.allow()
        assert limiter.remaining == 0


# ---------------------------------------------------------------------------
# Rate limiting
# ---------------------------------------------------------------------------


class TestRateLimit:
    def test_check_rate_limit_allows(self):
        r = _make_receiver(rate_limit=5)
        for _ in range(5):
            assert r.check_rate_limit() is True

    def test_check_rate_limit_blocks(self):
        r = _make_receiver(rate_limit=2)
        r.check_rate_limit()
        r.check_rate_limit()
        assert r.check_rate_limit() is False

    def test_remaining_property(self):
        r = _make_receiver(rate_limit=10)
        r.check_rate_limit()
        assert r.rate_limit_remaining == 9


# ---------------------------------------------------------------------------
# dispatch
# ---------------------------------------------------------------------------


class TestDispatch:
    def test_place_order_fails_honestly_when_ungated(self):
        """Order actions are NOT wired to the gated router yet (PLAN G23) — the
        receiver must say so, never fake a "queued" success for an order that
        was not placed."""
        r = _make_receiver()
        p = WebhookPayload(source="custom", action="place_order", symbol="NIFTY")
        result = _run(r.dispatch(p))
        assert result["status"] == "error"
        assert result["action"] == "place_order"
        assert "no order was placed" in result["message"]

    def test_place_order_uses_injected_gated_dispatcher(self):
        async def _dispatcher(payload: WebhookPayload) -> dict[str, object]:
            return {
                "status": "placed",
                "action": "place_order",
                "symbol": payload.symbol,
            }

        r = WebhookReceiver(WebhookConfig(rate_limit=100), order_dispatcher=_dispatcher)
        p = WebhookPayload(source="custom", action="place_order", symbol="NIFTY")
        result = _run(r.dispatch(p))
        assert result == {"status": "placed", "action": "place_order", "symbol": "NIFTY"}

    def test_place_order_dispatcher_exception_fails_closed(self):
        async def _dispatcher(_payload: WebhookPayload) -> dict[str, object]:
            raise RuntimeError("router unavailable")

        r = WebhookReceiver(WebhookConfig(rate_limit=100), order_dispatcher=_dispatcher)
        p = WebhookPayload(source="custom", action="place_order", symbol="NIFTY")
        result = _run(r.dispatch(p))
        assert result["status"] == "error"
        assert result["action"] == "place_order"
        assert "failed before broker execution" in result["message"]

    def test_cancel_order_fails_honestly_when_ungated(self):
        r = _make_receiver()
        p = WebhookPayload(source="custom", action="cancel_order", symbol="RELIANCE")
        result = _run(r.dispatch(p))
        assert result["status"] == "error"
        assert result["action"] == "cancel_order"
        assert "nothing was cancelled" in result["message"]

    def test_cancel_order_uses_injected_gated_dispatcher(self):
        def _dispatcher(payload: WebhookPayload) -> dict[str, object]:
            return {
                "status": "cancelled",
                "action": "cancel_order",
                "symbol": payload.symbol,
            }

        r = WebhookReceiver(WebhookConfig(rate_limit=100), cancel_dispatcher=_dispatcher)
        p = WebhookPayload(source="custom", action="cancel_order", symbol="RELIANCE")
        result = _run(r.dispatch(p))
        assert result == {"status": "cancelled", "action": "cancel_order", "symbol": "RELIANCE"}

    def test_alert(self):
        r = _make_receiver()
        p = WebhookPayload(source="custom", action="alert")
        result = _run(r.dispatch(p))
        assert result["status"] == "received"

    def test_signal(self):
        r = _make_receiver()
        p = WebhookPayload(source="custom", action="signal", symbol="TCS")
        result = _run(r.dispatch(p))
        assert result["status"] == "received"

    def test_unknown_action(self):
        r = _make_receiver()
        p = WebhookPayload(source="custom", action="do_something_weird")
        result = _run(r.dispatch(p))
        assert result["status"] == "unhandled"

    def test_dispatch_appends_log(self):
        r = _make_receiver()
        p = WebhookPayload(source="custom", action="alert")
        _run(r.dispatch(p))
        assert len(r.log) == 1
        assert r.log[0].action == "alert"

    def test_log_payload_stored_when_enabled(self):
        r = _make_receiver(log_payloads=True)
        p = WebhookPayload(source="custom", action="signal", data={"key": "val"})
        _run(r.dispatch(p))
        assert r.log[0].raw is not None

    def test_log_payload_omitted_when_disabled(self):
        r = _make_receiver(log_payloads=False)
        p = WebhookPayload(source="custom", action="signal", data={"key": "val"})
        _run(r.dispatch(p))
        assert r.log[0].raw is None


# ---------------------------------------------------------------------------
# recent_log
# ---------------------------------------------------------------------------


class TestRecentLog:
    def test_empty_log(self):
        r = _make_receiver()
        assert r.recent_log() == []

    def test_limit_applied(self):
        r = _make_receiver()
        for i in range(10):
            p = WebhookPayload(source="custom", action="signal")
            _run(r.dispatch(p))
        assert len(r.recent_log(limit=5)) == 5

    def test_full_log_returned(self):
        r = _make_receiver()
        for _ in range(3):
            _run(r.dispatch(WebhookPayload(source="custom", action="signal")))
        assert len(r.recent_log(limit=100)) == 3

    def test_log_capacity_capped(self):
        r = _make_receiver()
        for _ in range(r._LOG_CAPACITY + 50):
            r._append_log(WebhookLogEntry(
                received_at=time.time(), source="custom", action="signal",
            ))
        assert len(r.log) == r._LOG_CAPACITY

    def test_recent_log_is_list_of_dicts(self):
        r = _make_receiver()
        _run(r.dispatch(WebhookPayload(source="custom", action="alert")))
        entries = r.recent_log()
        assert isinstance(entries[0], dict)
        assert "action" in entries[0]


# ---------------------------------------------------------------------------
# Flask routes
# ---------------------------------------------------------------------------


@pytest.fixture()
def flask_client():
    """Flask test client with webhook Blueprint registered."""
    from flask import Flask
    from flinttrade_webhooks.webhook_receiver import WebhookConfig, WebhookReceiver
    from flinttrade_webhooks.webhook_routes import (
        init_webhook_routes,
        webhook_bp,
    )

    # Reset module singleton between tests using a fresh Blueprint app
    app = Flask("test_webhooks")
    receiver = WebhookReceiver(WebhookConfig(secret="testsecret", rate_limit=100))
    init_webhook_routes(receiver)
    app.register_blueprint(webhook_bp)
    app.config["TESTING"] = True
    return app.test_client()


@pytest.fixture()
def no_sig_client():
    """Flask test client with no secret (signature verification disabled)."""
    from flask import Flask
    from flinttrade_webhooks.webhook_receiver import WebhookConfig, WebhookReceiver
    from flinttrade_webhooks.webhook_routes import (
        init_webhook_routes,
        webhook_bp,
    )

    app = Flask("test_webhooks_nosig")
    receiver = WebhookReceiver(WebhookConfig(secret="", rate_limit=100, skip_verification=True))
    init_webhook_routes(receiver)
    app.register_blueprint(webhook_bp)
    app.config["TESTING"] = True
    return app.test_client()


class TestWebhookRoutes:
    def _post(self, client, source: str, body: dict, secret: str = "") -> object:
        raw = json.dumps(body).encode()
        headers = {"Content-Type": "application/json"}
        if secret:
            headers["X-Signature"] = _sign(raw, secret)
        return client.post(f"/v1/webhook/{source}", data=raw, headers=headers)

    # Happy paths

    def test_custom_place_order_fails_honestly_when_ungated(self, flask_client):
        resp = self._post(
            flask_client,
            "custom",
            {"action": "place_order", "side": "BUY", "symbol": "NIFTY", "exchange": "NFO"},
            secret="testsecret",
        )
        assert resp.status_code == 422
        data = resp.get_json()
        assert data["status"] == "error"
        assert data["data"]["action"] == "place_order"

    @pytest.mark.parametrize("retired", ["tradingview", "chartink", "gocharting"])
    def test_retired_provider_sources_answer_404(self, flask_client, retired):
        """TradingView/ChartInk/GoCharting are no longer supported sources."""
        resp = self._post(
            flask_client,
            retired,
            {"action": "BUY", "symbol": "NIFTY"},
            secret="testsecret",
        )
        assert resp.status_code == 404
        assert "Unknown source" in resp.get_json()["message"]

    def test_custom_alert(self, flask_client):
        resp = self._post(
            flask_client,
            "custom",
            {"action": "alert", "symbol": "GOLD"},
            secret="testsecret",
        )
        assert resp.status_code == 200

    # Auth

    def test_invalid_signature_rejected(self, flask_client):
        raw = json.dumps({"action": "BUY", "symbol": "NIFTY"}).encode()
        resp = flask_client.post(
            "/v1/webhook/custom",
            data=raw,
            headers={"Content-Type": "application/json", "X-Signature": "sha256=wrongsig"},
        )
        assert resp.status_code == 401

    def test_no_signature_rejected_when_secret_set(self, flask_client):
        raw = json.dumps({"action": "BUY"}).encode()
        resp = flask_client.post(
            "/v1/webhook/custom",
            data=raw,
            headers={"Content-Type": "application/json"},
        )
        assert resp.status_code == 401

    def test_no_secret_no_sig_ok(self, no_sig_client):
        raw = json.dumps({"action": "alert"}).encode()
        resp = no_sig_client.post(
            "/v1/webhook/custom",
            data=raw,
            headers={"Content-Type": "application/json"},
        )
        assert resp.status_code == 200

    # Input errors

    def test_unknown_source_404(self, flask_client):
        resp = self._post(flask_client, "unknown_source", {}, secret="testsecret")
        assert resp.status_code == 404

    def test_invalid_json_body(self, flask_client):
        resp = flask_client.post(
            "/v1/webhook/custom",
            data=b"not-json",
            headers={"Content-Type": "application/json"},
        )
        assert resp.status_code in (400, 401)

    def test_non_dict_json_body(self, flask_client):
        raw = json.dumps([1, 2, 3]).encode()
        sig = _sign(raw, "testsecret")
        resp = flask_client.post(
            "/v1/webhook/custom",
            data=raw,
            headers={"Content-Type": "application/json", "X-Signature": sig},
        )
        assert resp.status_code == 400

    # Rate limiting

    def test_rate_limit_exceeded(self):
        from flask import Flask
        from flinttrade_webhooks.webhook_receiver import WebhookConfig, WebhookReceiver
        from flinttrade_webhooks.webhook_routes import (
            init_webhook_routes,
            webhook_bp,
        )

        app = Flask("rate_limit_test")
        receiver = WebhookReceiver(WebhookConfig(rate_limit=2, secret="", skip_verification=True))
        init_webhook_routes(receiver)
        app.register_blueprint(webhook_bp)
        app.config["TESTING"] = True
        client = app.test_client()

        body = json.dumps({"action": "signal"}).encode()
        for _ in range(2):
            client.post(
                "/v1/webhook/custom",
                data=body,
                headers={"Content-Type": "application/json"},
            )
        resp = client.post(
            "/v1/webhook/custom",
            data=body,
            headers={"Content-Type": "application/json"},
        )
        assert resp.status_code == 429

    # Log endpoint

    def test_log_endpoint_empty(self, flask_client):
        resp = flask_client.get("/v1/webhook/log")
        assert resp.status_code == 200
        data = resp.get_json()
        assert data["status"] == "success"
        assert "entries" in data["data"]

    def test_log_endpoint_after_webhook(self, flask_client):
        self._post(
            flask_client,
            "custom",
            {"action": "signal", "symbol": "NIFTY"},
            secret="testsecret",
        )
        resp = flask_client.get("/v1/webhook/log")
        data = resp.get_json()
        assert data["data"]["count"] >= 1

    def test_log_limit_query_param(self, flask_client):
        # Send several webhooks
        for _ in range(5):
            self._post(
                flask_client,
                "custom",
                {"action": "signal", "symbol": "NIFTY"},
                secret="testsecret",
            )
        resp = flask_client.get("/v1/webhook/log?limit=2")
        data = resp.get_json()
        assert data["data"]["count"] <= 2

    def test_log_includes_rate_limit_remaining(self, flask_client):
        resp = flask_client.get("/v1/webhook/log")
        assert "rate_limit_remaining" in resp.get_json()["data"]
