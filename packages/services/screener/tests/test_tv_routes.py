"""Tests for packages/services/screener/src/tv_routes.py — TradingView signals endpoints."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest
from flask import Flask

import flinttrade_screener.tv_routes as mod


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture()
def app():
    """Minimal Flask app with the tv_bp blueprint registered."""
    flask_app = Flask(__name__)
    flask_app.config["TESTING"] = True
    flask_app.register_blueprint(mod.tv_bp)
    return flask_app


@pytest.fixture()
def client(app):
    return app.test_client()


def _make_tv_result(symbol: str = "RELIANCE", error: str = "") -> MagicMock:
    """Build a mock TVAnalysisResult."""
    r = MagicMock()
    r.symbol = symbol
    r.exchange = "NSE"
    r.interval = "1d"
    r.recommendation = "BUY"
    r.summary = {"BUY": 15, "SELL": 2, "NEUTRAL": 9}
    r.oscillators = {"RSI": 58.2}
    r.oscillators_recommendation = "BUY"
    r.moving_averages = {"EMA10": 2850.5}
    r.moving_averages_recommendation = "BUY"
    r.error = error
    return r


# ---------------------------------------------------------------------------
# GET /v1/tv/analysis
# ---------------------------------------------------------------------------


def test_tv_analysis_ok(client):
    """200 with analysis fields for a valid symbol."""
    result = _make_tv_result("RELIANCE")
    mock_tv = MagicMock()
    mock_tv.get_analysis.return_value = result
    with patch("flinttrade_screener.tv_routes.tv_signals", create=True), patch(
        "flinttrade_screener.tv_signals.TVSignals", return_value=mock_tv
    ):
        # Patch the lazy import inside the handler
        with patch(
            "flinttrade_screener.tv_routes.tv_bp.view_functions",
            wraps=mod.tv_bp.view_functions,
        ):
            with patch(
                "flinttrade_screener.tv_signals.TVSignals"
            ) as cls_mock:
                cls_mock.return_value = mock_tv
                resp = client.get("/v1/tv/analysis?symbol=RELIANCE&exchange=NSE&interval=1d")

    assert resp.status_code == 200
    body = resp.get_json()
    assert body["status"] == "success"
    assert "recommendation" in body["data"]
    assert body["data"]["symbol"] == "RELIANCE"


def test_tv_analysis_missing_symbol(client):
    """400 when symbol query param is absent."""
    resp = client.get("/v1/tv/analysis")
    assert resp.status_code == 400
    body = resp.get_json()
    assert body["status"] == "error"
    assert "symbol" in body["message"].lower()


def test_tv_analysis_upstream_error(client):
    """502 when TVSignals returns an error string."""
    error_result = _make_tv_result("NIFTY", error="Symbol not found on TradingView")
    mock_tv = MagicMock()
    mock_tv.get_analysis.return_value = error_result
    with patch("flinttrade_screener.tv_signals.TVSignals", return_value=mock_tv):
        resp = client.get("/v1/tv/analysis?symbol=NIFTY")
    assert resp.status_code == 502
    body = resp.get_json()
    assert body["status"] == "error"


def test_tv_analysis_default_params(client):
    """200 with defaults: exchange=NSE, interval=1d."""
    ok_result = _make_tv_result("TCS")
    mock_tv = MagicMock()
    mock_tv.get_analysis.return_value = ok_result
    with patch("flinttrade_screener.tv_signals.TVSignals", return_value=mock_tv):
        resp = client.get("/v1/tv/analysis?symbol=TCS")
    assert resp.status_code == 200


# ---------------------------------------------------------------------------
# POST /v1/tv/analysis/bulk
# ---------------------------------------------------------------------------


def test_tv_bulk_ok(client):
    """200 with list of results for valid symbols."""
    ok_result = _make_tv_result("RELIANCE")
    mock_tv = MagicMock()
    mock_tv.get_bulk_analysis.return_value = [ok_result, ok_result]
    with patch("flinttrade_screener.tv_signals.TVSignals", return_value=mock_tv):
        resp = client.post(
            "/v1/tv/analysis/bulk",
            json={"symbols": [{"symbol": "RELIANCE"}, {"symbol": "TCS"}], "interval": "1d"},
        )
    assert resp.status_code == 200
    body = resp.get_json()
    assert body["status"] == "success"
    assert isinstance(body["data"], list)


def test_tv_bulk_empty_symbols(client):
    """400 when symbols list is empty."""
    resp = client.post("/v1/tv/analysis/bulk", json={"symbols": []})
    assert resp.status_code == 400
    body = resp.get_json()
    assert body["status"] == "error"


def test_tv_bulk_missing_symbols(client):
    """400 when symbols key is absent from payload."""
    resp = client.post("/v1/tv/analysis/bulk", json={})
    assert resp.status_code == 400


def test_tv_bulk_string_symbols(client):
    """200 when symbols are plain strings (not dicts)."""
    ok_result = _make_tv_result("INFY")
    mock_tv = MagicMock()
    mock_tv.get_bulk_analysis.return_value = [ok_result]
    with patch("flinttrade_screener.tv_signals.TVSignals", return_value=mock_tv):
        resp = client.post(
            "/v1/tv/analysis/bulk",
            json={"symbols": ["INFY"], "interval": "4h"},
        )
    assert resp.status_code == 200


# ---------------------------------------------------------------------------
# GET /v1/tv/recommendation
# ---------------------------------------------------------------------------


def test_tv_recommendation_ok(client):
    """200 with recommendations dict across timeframes."""
    mock_tv = MagicMock()
    mock_tv.get_recommendation_summary.return_value = {
        "1h": "BUY",
        "4h": "BUY",
        "1d": "STRONG_BUY",
        "1w": "NEUTRAL",
    }
    with patch("flinttrade_screener.tv_signals.TVSignals", return_value=mock_tv):
        resp = client.get("/v1/tv/recommendation?symbol=NIFTY&exchange=NSE")
    assert resp.status_code == 200
    body = resp.get_json()
    assert body["status"] == "success"
    assert "recommendations" in body["data"]
    assert body["data"]["symbol"] == "NIFTY"


def test_tv_recommendation_missing_symbol(client):
    """400 when symbol is not provided."""
    resp = client.get("/v1/tv/recommendation")
    assert resp.status_code == 400
    body = resp.get_json()
    assert body["status"] == "error"
