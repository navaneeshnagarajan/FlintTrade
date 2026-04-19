"""Tests for packages/screener/src/economic_routes.py — economic calendar endpoint."""

from __future__ import annotations

import pytest
from flask import Flask

import packages.screener.src.economic_routes as mod


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture()
def app():
    flask_app = Flask(__name__)
    flask_app.config["TESTING"] = True
    flask_app.register_blueprint(mod.economic_bp)
    return flask_app


@pytest.fixture()
def client(app):
    return app.test_client()


# ---------------------------------------------------------------------------
# GET /ft-api/v1/economic/calendar
# ---------------------------------------------------------------------------


def test_calendar_ok(client):
    """200 with event list for default params."""
    resp = client.get("/ft-api/v1/economic/calendar")
    assert resp.status_code == 200
    body = resp.get_json()
    assert body["status"] == "success"
    assert "events" in body["data"]


def test_calendar_with_days(client):
    """200 with events for specified days."""
    resp = client.get("/ft-api/v1/economic/calendar?days=7")
    assert resp.status_code == 200
    body = resp.get_json()
    assert body["data"]["days"] == 7


def test_calendar_with_country_filter(client):
    """200 with country filter applied."""
    resp = client.get("/ft-api/v1/economic/calendar?country=IN&impact=high")
    assert resp.status_code == 200


def test_calendar_invalid_days(client):
    """400 or default when days is invalid."""
    resp = client.get("/ft-api/v1/economic/calendar?days=abc")
    assert resp.status_code in {200, 400}
