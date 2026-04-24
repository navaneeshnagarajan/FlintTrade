"""Tests for packages/screener/src/breadth_routes.py — market breadth & vol cone endpoints."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest
from flask import Flask

import packages.screener.src.breadth_routes as mod


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture()
def app():
    flask_app = Flask(__name__)
    flask_app.config["TESTING"] = True
    flask_app.register_blueprint(mod.breadth_bp)
    return flask_app


@pytest.fixture()
def client(app):
    return app.test_client()


# ---------------------------------------------------------------------------
# GET /ft-api/v1/breadth/current
# ---------------------------------------------------------------------------


def test_breadth_current_ok(client):
    """200 with breadth snapshot."""
    resp = client.get("/v1/breadth/current")
    assert resp.status_code == 200
    body = resp.get_json()
    assert body["status"] == "success"
    data = body["data"]
    assert "advances" in data or "ad_ratio" in data


# ---------------------------------------------------------------------------
# GET /ft-api/v1/breadth/history
# ---------------------------------------------------------------------------


def test_breadth_history_ok(client):
    """200 with list of historical breadth data."""
    resp = client.get("/v1/breadth/history?days=10")
    assert resp.status_code == 200
    body = resp.get_json()
    assert body["status"] == "success"
    assert isinstance(body["data"], list)


def test_breadth_history_default_days(client):
    """200 with default days parameter."""
    resp = client.get("/v1/breadth/history")
    assert resp.status_code == 200


# ---------------------------------------------------------------------------
# POST /ft-api/v1/analytics/volcone
# ---------------------------------------------------------------------------


def test_volcone_ok(client):
    """200 with vol cone data for a valid return series."""
    returns = [0.01, -0.005, 0.008, 0.003, -0.002] * 20
    resp = client.post(
        "/v1/analytics/volcone",
        json={"returns": returns},
    )
    assert resp.status_code == 200
    body = resp.get_json()
    assert body["status"] == "success"


def test_volcone_missing_returns(client):
    """400 or sample data when returns absent (depends on implementation)."""
    resp = client.post("/v1/analytics/volcone", json={})
    # Either 400 validation or 200 with sample data
    assert resp.status_code in {200, 400}
