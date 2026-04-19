"""Tests for CSP middleware and violation report handler.

Run with:
    python -m pytest packages/core/tests/test_csp.py -v --import-mode=importlib
"""

from __future__ import annotations

import json

import pytest
from flask import Flask

from packages.core.src.csp import (
    CSP_POLICY,
    _format_csp,
    apply_security_headers,
    csp_report_bp,
    csp_report_handler,
)


# ---------------------------------------------------------------------------
# _format_csp
# ---------------------------------------------------------------------------


class TestFormatCsp:
    def test_single_directive(self):
        result = _format_csp({"default-src": ["'self'"]})
        assert result == "default-src 'self'"

    def test_multiple_sources(self):
        result = _format_csp({"img-src": ["'self'", "data:", "https:"]})
        assert "img-src 'self' data: https:" in result

    def test_multiple_directives_joined_by_semicolon(self):
        policy = {
            "default-src": ["'self'"],
            "img-src": ["'self'"],
        }
        result = _format_csp(policy)
        assert "; " in result

    def test_report_uri_is_last(self):
        policy = {
            "default-src": ["'self'"],
            "report-uri": ["/csp-report"],
            "img-src": ["'self'"],
        }
        result = _format_csp(policy)
        assert result.endswith("report-uri /csp-report")

    def test_empty_sources_directive_only(self):
        result = _format_csp({"upgrade-insecure-requests": []})
        assert "upgrade-insecure-requests" in result

    def test_default_policy_contains_self(self):
        result = _format_csp(CSP_POLICY)
        assert "'self'" in result
        assert "default-src" in result


# ---------------------------------------------------------------------------
# apply_security_headers
# ---------------------------------------------------------------------------


class TestApplySecurityHeaders:
    def _app(self) -> Flask:
        app = Flask(__name__)
        app.after_request(apply_security_headers)

        @app.route("/test")
        def _view():
            return "ok"

        return app

    def test_csp_header_present(self):
        with self._app().test_client() as client:
            resp = client.get("/test")
        assert "Content-Security-Policy" in resp.headers

    def test_x_frame_options_deny(self):
        with self._app().test_client() as client:
            resp = client.get("/test")
        assert resp.headers["X-Frame-Options"] == "DENY"

    def test_x_content_type_options_nosniff(self):
        with self._app().test_client() as client:
            resp = client.get("/test")
        assert resp.headers["X-Content-Type-Options"] == "nosniff"

    def test_referrer_policy(self):
        with self._app().test_client() as client:
            resp = client.get("/test")
        assert "strict-origin-when-cross-origin" in resp.headers["Referrer-Policy"]

    def test_hsts_header(self):
        with self._app().test_client() as client:
            resp = client.get("/test")
        hsts = resp.headers.get("Strict-Transport-Security", "")
        assert "max-age=31536000" in hsts

    def test_permissions_policy(self):
        with self._app().test_client() as client:
            resp = client.get("/test")
        pp = resp.headers.get("Permissions-Policy", "")
        assert "geolocation=()" in pp

    def test_does_not_override_existing_header(self):
        app = Flask(__name__)
        app.after_request(apply_security_headers)

        @app.route("/custom")
        def _custom():
            from flask import make_response
            r = make_response("ok")
            r.headers["X-Frame-Options"] = "SAMEORIGIN"
            return r

        with app.test_client() as client:
            resp = client.get("/custom")
        assert resp.headers["X-Frame-Options"] == "SAMEORIGIN"


# ---------------------------------------------------------------------------
# csp_report_handler
# ---------------------------------------------------------------------------


class TestCspReportHandler:
    def test_does_not_raise_on_empty_report(self):
        # Should never raise — just log
        csp_report_handler({})

    def test_does_not_raise_on_full_report(self):
        csp_report_handler({
            "blocked-uri": "https://evil.example.com",
            "violated-directive": "script-src 'self'",
            "document-uri": "https://app.example.com",
            "source-file": "app.js",
            "line-number": 42,
        })


# ---------------------------------------------------------------------------
# /csp-report endpoint
# ---------------------------------------------------------------------------


class TestCspReportEndpoint:
    def _app(self) -> Flask:
        app = Flask(__name__)
        app.register_blueprint(csp_report_bp)
        return app

    def test_returns_204(self):
        payload = {
            "csp-report": {
                "blocked-uri": "https://evil.example.com",
                "violated-directive": "script-src",
            }
        }
        with self._app().test_client() as client:
            resp = client.post(
                "/csp-report",
                data=json.dumps(payload),
                content_type="application/csp-report",
            )
        assert resp.status_code == 204

    def test_empty_body_returns_204(self):
        with self._app().test_client() as client:
            resp = client.post(
                "/csp-report",
                data="",
                content_type="application/csp-report",
            )
        assert resp.status_code == 204
