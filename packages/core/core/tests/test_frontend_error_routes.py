"""Tests for packages/core/core/src/frontend_error_routes.py — error reporting & changelog."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest
from flask import Flask

import flinttrade_core.frontend_error_routes as mod


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture()
def app_with_log():
    """Flask app with ERROR_LOG configured."""
    flask_app = Flask(__name__)
    flask_app.config["TESTING"] = True
    flask_app.config["ERROR_LOG"] = MagicMock()
    flask_app.register_blueprint(mod.frontend_errors_bp)
    return flask_app


@pytest.fixture()
def app_no_log():
    """Flask app without ERROR_LOG."""
    flask_app = Flask(__name__)
    flask_app.config["TESTING"] = True
    flask_app.register_blueprint(mod.frontend_errors_bp)
    return flask_app


# ---------------------------------------------------------------------------
# POST /ft-api/v1/errors
# ---------------------------------------------------------------------------


def test_report_error_ok(app_with_log):
    """200 status:ok when valid error is submitted."""
    with app_with_log.test_client() as c:
        resp = c.post(
            "/v1/errors",
            json={
                "message": "TypeError: Cannot read property",
                "stack": "at Component (bundle.js:1)",
                "url": "https://host/trade",
            },
        )
    assert resp.status_code == 200
    assert resp.get_json()["status"] == "ok"


def test_report_error_no_message(app_with_log):
    """400 when message field is missing."""
    with app_with_log.test_client() as c:
        resp = c.post("/v1/errors", json={"stack": "at bundle.js:1"})
    assert resp.status_code == 400


def test_report_error_no_log_configured(app_no_log):
    """200 status:error (fire-and-forget) when ERROR_LOG not configured."""
    with app_no_log.test_client() as c:
        resp = c.post(
            "/v1/errors",
            json={"message": "Something broke"},
        )
    # Fire-and-forget: should not 5xx
    assert resp.status_code == 200
    assert resp.get_json()["status"] == "error"


# ---------------------------------------------------------------------------
# GET /ft-api/v1/changelog
# ---------------------------------------------------------------------------


def test_changelog_ok(app_no_log, tmp_path):
    """200 serving CHANGELOG.md as markdown."""
    changelog = tmp_path / "CHANGELOG.md"
    changelog.write_text("## v0.5.0\n- test release\n", encoding="utf-8")

    with patch.object(mod, "_CHANGELOG_PATH", changelog):
        with app_no_log.test_client() as c:
            resp = c.get("/v1/changelog")

    assert resp.status_code == 200
    assert b"v0.5.0" in resp.data


def test_changelog_missing(app_no_log, tmp_path):
    """404 when CHANGELOG.md not found."""
    missing = tmp_path / "MISSING.md"

    with patch.object(mod, "_CHANGELOG_PATH", missing):
        with app_no_log.test_client() as c:
            resp = c.get("/v1/changelog")

    assert resp.status_code == 404
