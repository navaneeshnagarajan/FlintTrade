"""Tests for packages/screener/src/oi_analytics_routes.py — OI heatmap, analysis, unusual."""

from __future__ import annotations

import pytest
from flask import Flask

import packages.screener.src.oi_analytics_routes as mod


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

_CHAIN = [
    {
        "strike": 22000,
        "ce_oi": 150000,
        "pe_oi": 120000,
        "ce_oi_change": 5000,
        "pe_oi_change": -3000,
        "ce_volume": 8000,
        "pe_volume": 6500,
        "ce_ltp": 250.0,
        "pe_ltp": 180.0,
    },
    {
        "strike": 22100,
        "ce_oi": 80000,
        "pe_oi": 90000,
        "ce_oi_change": -2000,
        "pe_oi_change": 4000,
        "ce_volume": 4000,
        "pe_volume": 5000,
        "ce_ltp": 200.0,
        "pe_ltp": 220.0,
    },
]


@pytest.fixture()
def app():
    flask_app = Flask(__name__)
    flask_app.config["TESTING"] = True
    flask_app.register_blueprint(mod.oi_analytics_bp)
    return flask_app


@pytest.fixture()
def client(app):
    return app.test_client()


# ---------------------------------------------------------------------------
# POST /ft-api/v1/oi/heatmap
# ---------------------------------------------------------------------------


def test_heatmap_ok(client):
    """200 with heatmap data."""
    resp = client.post(
        "/ft-api/v1/oi/heatmap",
        json={"symbol": "NIFTY", "chain": _CHAIN},
    )
    assert resp.status_code == 200
    body = resp.get_json()
    assert body["status"] == "success"


def test_heatmap_sample_data(client):
    """200 with synthetic sample data when chain absent."""
    resp = client.post("/ft-api/v1/oi/heatmap", json={"symbol": "NIFTY"})
    assert resp.status_code == 200


# ---------------------------------------------------------------------------
# POST /ft-api/v1/oi/analysis
# ---------------------------------------------------------------------------


def test_oi_analysis_ok(client):
    """200 with LB/SC/SB/LU signal analysis."""
    resp = client.post(
        "/ft-api/v1/oi/analysis",
        json={"symbol": "NIFTY", "chain": _CHAIN, "spot": 22050.0},
    )
    assert resp.status_code == 200
    body = resp.get_json()
    assert body["status"] == "success"


def test_oi_analysis_sample(client):
    """200 with sample data when chain absent."""
    resp = client.post("/ft-api/v1/oi/analysis", json={})
    assert resp.status_code == 200


# ---------------------------------------------------------------------------
# POST /ft-api/v1/oi/unusual
# ---------------------------------------------------------------------------


def test_unusual_ok(client):
    """200 with unusual OI activity report."""
    resp = client.post(
        "/ft-api/v1/oi/unusual",
        json={"symbol": "NIFTY", "chain": _CHAIN},
    )
    assert resp.status_code == 200
    body = resp.get_json()
    assert body["status"] == "success"


def test_unusual_sample(client):
    """200 with sample data when chain absent."""
    resp = client.post("/ft-api/v1/oi/unusual", json={})
    assert resp.status_code == 200
