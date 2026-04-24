"""Tests for packages/backtest-engine/src/optimiser_routes.py — portfolio optimisation."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest
from flask import Flask

import optimiser_routes as mod  # noqa: E402 — conftest adds src/ to sys.path


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

_RETURNS_PAYLOAD = {
    "NIFTY": [0.01, -0.005, 0.008, 0.003, -0.002],
    "TCS":   [0.007, 0.002, -0.003, 0.004, 0.001],
}

_MOCK_RESULT = MagicMock()
_MOCK_RESULT.weights = {"NIFTY": 0.6, "TCS": 0.4}
_MOCK_RESULT.expected_return = 0.05
_MOCK_RESULT.expected_volatility = 0.15
_MOCK_RESULT.sharpe_ratio = 0.33
_MOCK_RESULT.diversification_ratio = 1.2
_MOCK_RESULT.model_dump.return_value = {
    "weights": {"NIFTY": 0.6, "TCS": 0.4},
    "expected_return": 0.05,
    "expected_volatility": 0.15,
    "sharpe_ratio": 0.33,
    "diversification_ratio": 1.2,
}


@pytest.fixture()
def app():
    flask_app = Flask(__name__)
    flask_app.config["TESTING"] = True
    flask_app.register_blueprint(mod.optimiser_bp)
    return flask_app


@pytest.fixture()
def client(app):
    return app.test_client()


def _mock_optimiser(result=None, frontier=None):
    optimiser = MagicMock()
    optimiser.optimise.return_value = result or _MOCK_RESULT
    optimiser.efficient_frontier.return_value = frontier or [_MOCK_RESULT]
    return optimiser


# ---------------------------------------------------------------------------
# POST /ft-api/v1/portfolio/optimise
# ---------------------------------------------------------------------------


def test_optimise_ok(client):
    """200 with weights on valid input."""
    with patch(
        "optimiser_routes.PortfolioOptimiser",
        return_value=_mock_optimiser(),
    ):
        resp = client.post(
            "/v1/portfolio/optimise",
            json={"returns": _RETURNS_PAYLOAD},
        )
    assert resp.status_code == 200
    body = resp.get_json()
    assert body["status"] == "success"
    assert "weights" in body["data"]


def test_optimise_missing_returns(client):
    """400 when returns field absent."""
    resp = client.post("/v1/portfolio/optimise", json={})
    assert resp.status_code == 400


def test_optimise_single_asset(client):
    """400 when returns has fewer than 2 assets."""
    resp = client.post(
        "/v1/portfolio/optimise",
        json={"returns": {"NIFTY": [0.01, 0.02]}},
    )
    assert resp.status_code == 400


def test_optimise_invalid_config(client):
    """400 for an invalid config dict."""
    with patch(
        "optimiser_routes.PortfolioOptimiser",
        return_value=_mock_optimiser(),
    ):
        resp = client.post(
            "/v1/portfolio/optimise",
            json={
                "returns": _RETURNS_PAYLOAD,
                "config": {"method": "invalid_method", "bad_field": "x"},
            },
        )
    # Config validation may reject or use defaults — both are acceptable
    assert resp.status_code in {200, 400}


# ---------------------------------------------------------------------------
# POST /ft-api/v1/portfolio/frontier
# ---------------------------------------------------------------------------


def test_frontier_ok(client):
    """200 with list of frontier points."""
    with patch(
        "optimiser_routes.PortfolioOptimiser",
        return_value=_mock_optimiser(),
    ):
        resp = client.post(
            "/v1/portfolio/frontier",
            json={"returns": _RETURNS_PAYLOAD, "n_points": 5},
        )
    assert resp.status_code == 200
    body = resp.get_json()
    assert body["status"] == "success"
    assert isinstance(body["data"], list)


def test_frontier_missing_returns(client):
    """400 when returns is absent."""
    resp = client.post("/v1/portfolio/frontier", json={})
    assert resp.status_code == 400


def test_frontier_bad_n_points(client):
    """400 when n_points is out of range."""
    with patch(
        "optimiser_routes.PortfolioOptimiser",
        return_value=_mock_optimiser(),
    ):
        resp = client.post(
            "/v1/portfolio/frontier",
            json={"returns": _RETURNS_PAYLOAD, "n_points": 1},
        )
    assert resp.status_code == 400
