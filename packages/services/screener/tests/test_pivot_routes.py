"""Tests for packages/services/screener/src/pivot_routes.py — pivot point calculation endpoint."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest
from flask import Flask

import flinttrade_screener.pivot_routes as mod


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

_OHLC_VALID = {"high": 18500.0, "low": 18200.0, "close": 18400.0}


@pytest.fixture()
def app():
    """Minimal Flask app with pivot_bp registered."""
    flask_app = Flask(__name__)
    flask_app.config["TESTING"] = True
    flask_app.register_blueprint(mod.pivot_bp)
    return flask_app


@pytest.fixture()
def client(app):
    return app.test_client()


def _make_pivot_levels(method: str = "standard") -> MagicMock:
    """Build a mock PivotLevels object whose to_dict returns a plausible dict."""
    m = MagicMock()
    m.to_dict.return_value = {
        "method": method,
        "pivot": 18366.67,
        "r1": 18533.33,
        "r2": 18700.0,
        "r3": 18966.67,
        "r4": None,
        "s1": 18200.0,
        "s2": 18033.33,
        "s3": 17766.67,
        "s4": None,
    }
    return m


# ---------------------------------------------------------------------------
# POST /ft-api/v1/pivots/calculate
# ---------------------------------------------------------------------------


def test_calculate_pivots_ok(client):
    """200 with all five pivot methods in the response."""
    all_levels = {
        name: _make_pivot_levels(name)
        for name in ("standard", "fibonacci", "woodie", "camarilla", "demark")
    }
    with patch(
        "flinttrade_screener.pivot_calculator.PivotCalculator.all_methods",
        return_value=all_levels,
    ):
        resp = client.post("/v1/pivots/calculate", json=_OHLC_VALID)

    assert resp.status_code == 200
    body = resp.get_json()
    assert body["status"] == "success"
    assert "methods" in body["data"]
    assert set(body["data"]["methods"].keys()) == {
        "standard", "fibonacci", "woodie", "camarilla", "demark"
    }


def test_calculate_pivots_with_open(client):
    """200 when optional 'open' price is provided (needed for DeMark)."""
    all_levels = {
        name: _make_pivot_levels(name)
        for name in ("standard", "fibonacci", "woodie", "camarilla", "demark")
    }
    with patch(
        "flinttrade_screener.pivot_calculator.PivotCalculator.all_methods",
        return_value=all_levels,
    ):
        resp = client.post(
            "/v1/pivots/calculate",
            json={**_OHLC_VALID, "open": 18250.0},
        )
    assert resp.status_code == 200
    body = resp.get_json()
    assert body["data"]["input"]["open"] == 18250.0


def test_calculate_pivots_echo_input(client):
    """200 and the input values are echoed in the response data."""
    all_levels = {"standard": _make_pivot_levels()}
    with patch(
        "flinttrade_screener.pivot_calculator.PivotCalculator.all_methods",
        return_value=all_levels,
    ):
        resp = client.post("/v1/pivots/calculate", json=_OHLC_VALID)
    body = resp.get_json()
    assert body["data"]["input"]["high"] == 18500.0
    assert body["data"]["input"]["low"] == 18200.0
    assert body["data"]["input"]["close"] == 18400.0
    assert body["data"]["input"]["open"] is None


def test_calculate_pivots_missing_high(client):
    """400 when 'high' is absent."""
    resp = client.post(
        "/v1/pivots/calculate",
        json={"low": 18200.0, "close": 18400.0},
    )
    assert resp.status_code == 400
    body = resp.get_json()
    assert body["status"] == "error"
    assert "high" in body["message"]


def test_calculate_pivots_missing_all_required(client):
    """400 when all required fields are absent."""
    resp = client.post("/v1/pivots/calculate", json={})
    assert resp.status_code == 400
    body = resp.get_json()
    assert body["status"] == "error"


def test_calculate_pivots_invalid_numeric(client):
    """400 when a field value cannot be coerced to float."""
    resp = client.post(
        "/v1/pivots/calculate",
        json={"high": "eighteen-thousand", "low": 18200.0, "close": 18400.0},
    )
    assert resp.status_code == 400
    body = resp.get_json()
    assert body["status"] == "error"


def test_calculate_pivots_calculator_raises(client):
    """400 when PivotCalculator raises a ValueError (e.g. high < low)."""
    with patch(
        "flinttrade_screener.pivot_calculator.PivotCalculator.all_methods",
        side_effect=ValueError("high must be >= low"),
    ):
        resp = client.post(
            "/v1/pivots/calculate",
            json={"high": 18000.0, "low": 18500.0, "close": 18200.0},
        )
    assert resp.status_code == 400
    body = resp.get_json()
    assert body["status"] == "error"


def test_calculate_pivots_no_body(client):
    """400 when request body is absent entirely."""
    resp = client.post("/v1/pivots/calculate")
    assert resp.status_code == 400
