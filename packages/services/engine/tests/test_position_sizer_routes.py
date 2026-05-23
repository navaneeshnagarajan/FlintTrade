"""Tests for packages/services/engine/src/position_sizer_routes.py — position sizing endpoint."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest
from flask import Flask

import flinttrade_engine.position_sizer_routes as mod


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture()
def app():
    flask_app = Flask(__name__)
    flask_app.config["TESTING"] = True
    flask_app.register_blueprint(mod.position_bp)
    return flask_app


@pytest.fixture()
def client(app):
    return app.test_client()


def _sizer_patch(quantity: int = 5):
    """Return a context manager patching PositionSizer with a mock.

    The route imports PositionSizer lazily inside the handler via
    ``from .position_sizer import PositionSizer``.  We patch the
    module where the name is looked up at runtime.
    """
    sizer = MagicMock()
    sizer.from_capital.return_value = quantity
    sizer.from_risk_percent.return_value = quantity
    sizer.from_kelly.return_value = quantity
    sizer.max_lots.return_value = quantity
    return patch(
        "flinttrade_engine.position_sizer.PositionSizer",
        sizer,
    )


# ---------------------------------------------------------------------------
# POST /api/v1/position/size
# ---------------------------------------------------------------------------


def test_missing_method(client):
    """400 when method is absent."""
    resp = client.post("/api/v1/position/size", json={"capital": 100000})
    assert resp.status_code == 400


def test_invalid_method(client):
    """400 for unrecognised method name."""
    resp = client.post(
        "/api/v1/position/size",
        json={"method": "unknown_method", "capital": 100000},
    )
    assert resp.status_code == 400


def test_from_capital_ok(client):
    """200 for from_capital method."""
    with _sizer_patch(quantity=10):
        resp = client.post(
            "/api/v1/position/size",
            json={"method": "from_capital", "capital": 500000, "ltp": 22000.0, "lot_size": 50},
        )
    assert resp.status_code == 200
    body = resp.get_json()
    assert body["status"] == "success"
    assert body["data"]["method"] == "from_capital"
    assert body["data"]["quantity"] == 10


def test_from_capital_missing_ltp(client):
    """400 when ltp is 0 for from_capital."""
    with _sizer_patch():
        resp = client.post(
            "/api/v1/position/size",
            json={"method": "from_capital", "capital": 500000, "ltp": 0},
        )
    assert resp.status_code == 400


def test_from_risk_percent_ok(client):
    """200 for from_risk_percent method."""
    with _sizer_patch(quantity=3):
        resp = client.post(
            "/api/v1/position/size",
            json={
                "method": "from_risk_percent",
                "capital": 500000,
                "risk_pct": 0.01,
                "entry": 22000.0,
                "sl": 21800.0,
                "lot_size": 50,
            },
        )
    assert resp.status_code == 200
    assert resp.get_json()["data"]["quantity"] == 3


def test_from_risk_percent_missing_entry(client):
    """400 when entry price is 0."""
    with _sizer_patch():
        resp = client.post(
            "/api/v1/position/size",
            json={
                "method": "from_risk_percent",
                "capital": 500000,
                "risk_pct": 0.01,
                "entry": 0,
                "sl": 21800.0,
            },
        )
    assert resp.status_code == 400


def test_from_kelly_ok(client):
    """200 for from_kelly method."""
    with _sizer_patch(quantity=2):
        resp = client.post(
            "/api/v1/position/size",
            json={
                "method": "from_kelly",
                "capital": 500000,
                "win_rate": 0.55,
                "avg_win": 1500.0,
                "avg_loss": 1000.0,
                "ltp": 22000.0,
            },
        )
    assert resp.status_code == 200


def test_max_lots_ok(client):
    """200 for max_lots method."""
    with _sizer_patch(quantity=4):
        resp = client.post(
            "/api/v1/position/size",
            json={
                "method": "max_lots",
                "capital": 200000,
                "margin_per_lot": 50000.0,
            },
        )
    assert resp.status_code == 200
    assert resp.get_json()["data"]["quantity"] == 4


def test_max_lots_zero_margin(client):
    """400 when margin_per_lot is 0."""
    with _sizer_patch():
        resp = client.post(
            "/api/v1/position/size",
            json={"method": "max_lots", "capital": 200000, "margin_per_lot": 0},
        )
    assert resp.status_code == 400
