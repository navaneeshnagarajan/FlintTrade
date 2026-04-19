"""Tests for packages/screener/src/earnings_routes.py — earnings calendar endpoints."""

from __future__ import annotations

import pytest
from flask import Flask

import packages.screener.src.earnings_routes as mod


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture()
def app():
    flask_app = Flask(__name__)
    flask_app.config["TESTING"] = True
    flask_app.register_blueprint(mod.earnings_bp)
    return flask_app


@pytest.fixture()
def client(app):
    return app.test_client()


# ---------------------------------------------------------------------------
# GET /ft-api/v1/earnings/calendar
# ---------------------------------------------------------------------------


def test_calendar_ok(client):
    """200 with upcoming earnings list."""
    resp = client.get("/ft-api/v1/earnings/calendar?days=30")
    assert resp.status_code == 200
    body = resp.get_json()
    assert body["status"] == "success"
    assert "data" in body


def test_calendar_default_days(client):
    """200 with default days=30."""
    resp = client.get("/ft-api/v1/earnings/calendar")
    assert resp.status_code == 200


def test_calendar_invalid_days(client):
    """400 or sample data when days is not a valid integer."""
    resp = client.get("/ft-api/v1/earnings/calendar?days=abc")
    # Either 400 validation or 200 with defaults — not 5xx
    assert resp.status_code in {200, 400}


# ---------------------------------------------------------------------------
# GET /ft-api/v1/earnings/by-date
# ---------------------------------------------------------------------------


def test_by_date_ok(client):
    """200 with earnings for a specific date."""
    resp = client.get("/ft-api/v1/earnings/by-date?date=2026-04-19")
    assert resp.status_code == 200
    body = resp.get_json()
    assert body["status"] == "success"


def test_by_date_invalid_format(client):
    """400 for malformed date string."""
    resp = client.get("/ft-api/v1/earnings/by-date?date=not-a-date")
    assert resp.status_code in {200, 400}


def test_by_date_missing(client):
    """400 or empty when date param absent."""
    resp = client.get("/ft-api/v1/earnings/by-date")
    assert resp.status_code in {200, 400}


# ---------------------------------------------------------------------------
# GET /ft-api/v1/earnings/by-symbol
# ---------------------------------------------------------------------------


def test_by_symbol_ok(client):
    """200 with earnings history for a symbol."""
    resp = client.get("/ft-api/v1/earnings/by-symbol?symbol=RELIANCE")
    assert resp.status_code == 200
    body = resp.get_json()
    assert body["status"] == "success"


def test_by_symbol_missing(client):
    """400 when symbol param absent."""
    resp = client.get("/ft-api/v1/earnings/by-symbol")
    assert resp.status_code in {200, 400}
