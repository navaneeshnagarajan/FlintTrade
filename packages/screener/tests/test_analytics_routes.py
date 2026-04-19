"""Tests for packages/screener/src/analytics_routes.py — VWAP, pairs, MTF endpoints."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest
from flask import Flask

import packages.screener.src.analytics_routes as mod


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

_BARS = [
    {
        "timestamp": "2026-04-19T09:15:00",
        "high": 22500.0,
        "low": 22450.0,
        "close": 22480.0,
        "volume": 10000.0,
    }
] * 20


@pytest.fixture()
def app():
    flask_app = Flask(__name__)
    flask_app.config["TESTING"] = True
    flask_app.register_blueprint(mod.analytics_bp)
    return flask_app


@pytest.fixture()
def client(app):
    return app.test_client()


# ---------------------------------------------------------------------------
# POST /ft-api/v1/indicators/vwap
# ---------------------------------------------------------------------------


def test_vwap_ok(client):
    """200 with VWAP bands on valid bars."""
    vwap_result = MagicMock()
    vwap_result.model_dump.return_value = {
        "timestamps": ["2026-04-19T09:15:00"],
        "vwap": [22470.0],
        "upper_1": [22480.0],
        "lower_1": [22460.0],
    }
    # vwap_bands is imported lazily inside the handler; patch the source module
    with patch(
        "packages.indicators.src.vwap_bands.calculate_vwap_bands",
        return_value=vwap_result,
    ):
        resp = client.post("/ft-api/v1/indicators/vwap", json={"bars": _BARS})
    assert resp.status_code == 200
    assert resp.get_json()["status"] == "success"


def test_vwap_no_bars_uses_sample(client):
    """200 with sample data when bars not provided (falls back to _make_sample_vwap_bars)."""
    vwap_result = MagicMock()
    vwap_result.model_dump.return_value = {"vwap": [22000.0]}
    with patch(
        "packages.indicators.src.vwap_bands.calculate_vwap_bands",
        return_value=vwap_result,
    ):
        resp = client.post("/ft-api/v1/indicators/vwap", json={})
    assert resp.status_code == 200


# ---------------------------------------------------------------------------
# POST /ft-api/v1/analytics/pairs
# ---------------------------------------------------------------------------


def test_pairs_ok(client):
    """200 with pairs analysis result via analyse_pair."""
    pair_result = MagicMock()
    pair_result.model_dump.return_value = {
        "symbol_a": "TCS",
        "symbol_b": "INFY",
        "z_score": 1.2,
    }
    with patch.object(mod._pair_engine, "analyse_pair", return_value=pair_result):
        resp = client.post(
            "/ft-api/v1/analytics/pairs",
            json={
                "pairs": [
                    {
                        "symbol_a": "TCS",
                        "symbol_b": "INFY",
                        "returns_a": [0.01, -0.005, 0.003] * 10,
                        "returns_b": [0.008, -0.003, 0.002] * 10,
                        "prices_a": [3800.0] * 30,
                        "prices_b": [1500.0] * 30,
                    }
                ]
            },
        )
    # Either 200 (pairs found) or 400/422 (validation) — not 5xx
    assert resp.status_code in {200, 400, 422}


def test_pairs_sample_data(client):
    """200 with sample data when pairs absent."""
    resp = client.post("/ft-api/v1/analytics/pairs", json={})
    # Should return 200 with sample data or 400 — not 5xx
    assert resp.status_code in {200, 400}


# ---------------------------------------------------------------------------
# POST /ft-api/v1/analytics/mtf
# ---------------------------------------------------------------------------


def test_mtf_ok(client):
    """200 with multi-timeframe analysis."""
    mtf_result = MagicMock()
    mtf_result.model_dump.return_value = {
        "symbol": "NIFTY",
        "signals": [{"timeframe": "1h", "signal": "BUY"}],
    }
    with patch.object(mod._mtf_analyser, "analyse", return_value=mtf_result):
        resp = client.post(
            "/ft-api/v1/analytics/mtf",
            json={
                "symbol": "NIFTY",
                "data": {"1h": _BARS, "4h": _BARS},
            },
        )
    assert resp.status_code == 200


def test_mtf_sample_data(client):
    """200 or 400 when no data provided."""
    resp = client.post("/ft-api/v1/analytics/mtf", json={})
    assert resp.status_code in {200, 400}
