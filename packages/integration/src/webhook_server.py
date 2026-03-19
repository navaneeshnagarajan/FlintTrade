"""Lightweight Flask webhook server.

Registers multiple webhook endpoints (TradingView, ChartInk, custom),
handles request logging, validation, rate limiting, and authentication.

Runs on configurable port (default 8080). Rate limited to 100/min per
OpenAlgo webhook limits.
"""

from __future__ import annotations

import hashlib
import hmac
import logging
import time
from dataclasses import dataclass
from typing import Any, Callable

from flask import Flask, Response, jsonify, request

logger = logging.getLogger("flinttrade.integration.webhook_server")


# ---------------------------------------------------------------------------
# Rate limiter for webhooks (100/min as per OpenAlgo docs)
# ---------------------------------------------------------------------------


class WebhookRateLimiter:
    """Simple sliding-window rate limiter."""

    def __init__(self, max_requests: int = 100, window_seconds: float = 60.0) -> None:
        self.max_requests = max_requests
        self.window = window_seconds
        self._timestamps: list[float] = []

    def allow(self) -> bool:
        """Check if a request is allowed under the rate limit."""
        now = time.monotonic()
        # Prune old timestamps
        cutoff = now - self.window
        self._timestamps = [t for t in self._timestamps if t > cutoff]

        if len(self._timestamps) >= self.max_requests:
            return False

        self._timestamps.append(now)
        return True

    @property
    def remaining(self) -> int:
        now = time.monotonic()
        cutoff = now - self.window
        active = sum(1 for t in self._timestamps if t > cutoff)
        return max(0, self.max_requests - active)


# ---------------------------------------------------------------------------
# Webhook handler registry
# ---------------------------------------------------------------------------


@dataclass
class WebhookEndpoint:
    """Registered webhook endpoint."""

    path: str
    name: str
    handler: Callable[[bytes, dict[str, str]], dict[str, Any]]
    secret: str = ""
    enabled: bool = True


# ---------------------------------------------------------------------------
# WebhookServer
# ---------------------------------------------------------------------------


class WebhookServer:
    """Flask-based webhook server with rate limiting and auth.

    Usage::

        server = WebhookServer(port=8080)
        server.register_tradingview(tv_handler)
        server.register_chartink(ci_handler)
        server.register_custom("/webhook/custom/my_signal", my_handler, secret="abc")
        server.run()  # blocks
    """

    def __init__(
        self,
        port: int = 8080,
        host: str = "0.0.0.0",
        rate_limit: int = 100,
        rate_window: float = 60.0,
    ) -> None:
        self.port = port
        self.host = host
        self._app = Flask("flinttrade-webhooks")
        self._rate_limiter = WebhookRateLimiter(rate_limit, rate_window)
        self._endpoints: dict[str, WebhookEndpoint] = {}
        self._request_log: list[dict[str, Any]] = []

        # Register health check
        self._app.add_url_rule("/health", "health", self._health, methods=["GET"])

    @property
    def app(self) -> Flask:
        """Expose the Flask app for testing or WSGI mounting."""
        return self._app

    @property
    def request_log(self) -> list[dict[str, Any]]:
        return list(self._request_log)

    # ------------------------------------------------------------------
    # Endpoint registration
    # ------------------------------------------------------------------

    def register(
        self,
        path: str,
        name: str,
        handler: Callable[[bytes, dict[str, str]], dict[str, Any]],
        secret: str = "",
    ) -> None:
        """Register a webhook endpoint.

        The handler receives (raw_body: bytes, headers: dict) and returns
        a dict response.
        """
        endpoint = WebhookEndpoint(
            path=path, name=name, handler=handler, secret=secret,
        )
        self._endpoints[path] = endpoint

        # Create Flask route
        # Use a factory to capture `path` in the closure correctly
        def make_view(ep_path: str):
            def view(**kwargs: Any) -> Response:
                return self._handle_request(ep_path)
            view.__name__ = f"webhook_{name}_{id(endpoint)}"
            return view

        self._app.add_url_rule(path, view_func=make_view(path), methods=["POST"])
        logger.info("Registered webhook: %s → %s", path, name)

    def register_tradingview(
        self,
        handler: Callable[[bytes, dict[str, str]], dict[str, Any]],
        strategy_id: str = "default",
        secret: str = "",
    ) -> None:
        """Register a TradingView webhook endpoint."""
        path = f"/webhook/tradingview/{strategy_id}"
        self.register(path, f"tradingview-{strategy_id}", handler, secret)

    def register_chartink(
        self,
        handler: Callable[[bytes, dict[str, str]], dict[str, Any]],
        strategy_id: str = "default",
        secret: str = "",
    ) -> None:
        """Register a ChartInk webhook endpoint."""
        path = f"/webhook/chartink/{strategy_id}"
        self.register(path, f"chartink-{strategy_id}", handler, secret)

    def register_custom(
        self,
        path: str,
        handler: Callable[[bytes, dict[str, str]], dict[str, Any]],
        secret: str = "",
    ) -> None:
        """Register a custom webhook endpoint."""
        name = path.strip("/").replace("/", "-")
        self.register(path, name, handler, secret)

    # ------------------------------------------------------------------
    # Request handling
    # ------------------------------------------------------------------

    def _handle_request(self, path: str) -> Response:
        """Central request handler for all webhook endpoints."""
        endpoint = self._endpoints.get(path)
        if not endpoint:
            return jsonify({"status": "error", "message": "Unknown endpoint"}), 404

        if not endpoint.enabled:
            return jsonify({"status": "error", "message": "Endpoint disabled"}), 503

        # Rate limiting
        if not self._rate_limiter.allow():
            logger.warning("Rate limit exceeded for %s", path)
            return jsonify({"status": "error", "message": "Rate limit exceeded"}), 429

        # Authentication
        if endpoint.secret:
            auth_header = request.headers.get("X-Webhook-Secret", "")
            sig_header = request.headers.get("X-Signature", "")
            if sig_header:
                # Validate HMAC-SHA256 signature against the raw body
                body_for_auth = request.get_data()
                expected = hmac.new(
                    endpoint.secret.encode(), body_for_auth, hashlib.sha256
                ).hexdigest()
                if not hmac.compare_digest(expected, sig_header):
                    logger.warning("Signature validation failed for %s", path)
                    return jsonify({"status": "error", "message": "Unauthorized"}), 401
            elif not hmac.compare_digest(auth_header, endpoint.secret):
                logger.warning("Auth failed for %s", path)
                return jsonify({"status": "error", "message": "Unauthorized"}), 401

        # Get raw body and headers
        body = request.get_data()
        headers = {k: v for k, v in request.headers}

        # Log the request
        log_entry = {
            "timestamp": time.time(),
            "path": path,
            "name": endpoint.name,
            "method": request.method,
            "content_length": len(body),
            "remote_addr": request.remote_addr,
        }
        self._request_log.append(log_entry)

        # Call the handler
        try:
            result = endpoint.handler(body, headers)
            logger.info("Webhook %s handled: %s", endpoint.name, result.get("status", "ok"))
            return jsonify({"status": "success", **result})
        except Exception as exc:
            logger.error("Webhook %s error: %s", endpoint.name, exc)
            return jsonify({"status": "error", "message": str(exc)}), 500

    def _health(self) -> Response:
        """Health check endpoint."""
        return jsonify({
            "status": "ok",
            "endpoints": list(self._endpoints.keys()),
            "rate_limit_remaining": self._rate_limiter.remaining,
        })

    # ------------------------------------------------------------------
    # Enable / disable
    # ------------------------------------------------------------------

    def enable_endpoint(self, path: str) -> None:
        ep = self._endpoints.get(path)
        if ep:
            ep.enabled = True

    def disable_endpoint(self, path: str) -> None:
        ep = self._endpoints.get(path)
        if ep:
            ep.enabled = False

    # ------------------------------------------------------------------
    # Run
    # ------------------------------------------------------------------

    def run(self, debug: bool = False) -> None:
        """Start the webhook server (blocking)."""
        logger.info(
            "Webhook server starting on %s:%d with %d endpoints",
            self.host, self.port, len(self._endpoints),
        )
        self._app.run(host=self.host, port=self.port, debug=debug)
