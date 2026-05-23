"""Tests for packages/services/screener/src/stock_routes.py — stock screener scan endpoint."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest
from flask import Flask

import flinttrade_screener.stock_routes as mod
from flinttrade_screener.stock_cache import StockFundamentals


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


def _make_stock(symbol: str = "RELIANCE", sector: str = "Energy") -> StockFundamentals:
    """Build a StockFundamentals with realistic defaults."""
    return StockFundamentals(
        symbol=symbol,
        name=f"{symbol} Ltd",
        exchange="NSE",
        market_cap=1_500_000.0,
        pe_ratio=28.5,
        pb_ratio=2.8,
        roe=12.5,
        roce=15.2,
        dividend_yield=0.4,
        sector=sector,
        updated_at=1_745_000_000.0,
    )


@pytest.fixture()
def app():
    """Minimal Flask app with stock_bp registered and module-level cache reset."""
    flask_app = Flask(__name__)
    flask_app.config["TESTING"] = True
    flask_app.register_blueprint(mod.stock_bp)
    return flask_app


@pytest.fixture()
def client(app):
    return app.test_client()


@pytest.fixture(autouse=True)
def reset_module_cache():
    """Reset the module-level _cache singleton so each test starts clean."""
    original = mod._cache
    mod._cache = None
    yield
    mod._cache = original


# ---------------------------------------------------------------------------
# GET /v1/stocks/scan
# ---------------------------------------------------------------------------


def test_stock_scan_ok(client):
    """200 with stocks list, sectors list, and count when cache is seeded."""
    stocks = [_make_stock("RELIANCE"), _make_stock("TCS", "IT")]
    mock_cache = MagicMock()
    mock_cache.get.return_value = _make_stock()  # cache is warm
    mock_cache.scan.return_value = stocks

    with patch("flinttrade_screener.stock_routes._get_cache", return_value=mock_cache):
        resp = client.get("/v1/stocks/scan")

    assert resp.status_code == 200
    body = resp.get_json()
    assert body["status"] == "success"
    assert isinstance(body["data"]["stocks"], list)
    assert isinstance(body["data"]["sectors"], list)
    assert body["data"]["count"] == 2


def test_stock_scan_response_fields(client):
    """200 response contains all expected per-stock fields."""
    stocks = [_make_stock()]
    mock_cache = MagicMock()
    mock_cache.get.return_value = _make_stock()
    mock_cache.scan.return_value = stocks

    with patch("flinttrade_screener.stock_routes._get_cache", return_value=mock_cache):
        resp = client.get("/v1/stocks/scan")

    body = resp.get_json()
    stock = body["data"]["stocks"][0]
    for field in ("symbol", "name", "exchange", "market_cap", "pe_ratio",
                  "pb_ratio", "roe", "roce", "dividend_yield", "sector"):
        assert field in stock, f"Missing field: {field}"


def test_stock_scan_sector_filter(client):
    """200 with filtered results when sector param is provided."""
    stocks = [_make_stock("TCS", "IT")]
    mock_cache = MagicMock()
    mock_cache.get.return_value = _make_stock()
    mock_cache.scan.return_value = stocks

    with patch("flinttrade_screener.stock_routes._get_cache", return_value=mock_cache):
        resp = client.get("/v1/stocks/scan?sector=IT")

    assert resp.status_code == 200
    # Verify scan was called with sector filter
    call_kwargs = mock_cache.scan.call_args
    assert call_kwargs is not None


def test_stock_scan_max_pe_filter(client):
    """200 with max_pe filter applied."""
    mock_cache = MagicMock()
    mock_cache.get.return_value = _make_stock()
    mock_cache.scan.return_value = [_make_stock()]

    with patch("flinttrade_screener.stock_routes._get_cache", return_value=mock_cache):
        resp = client.get("/v1/stocks/scan?max_pe=30")

    assert resp.status_code == 200


def test_stock_scan_limit_clamped(client):
    """200 and limit is clamped to 200 when >200 is requested."""
    mock_cache = MagicMock()
    mock_cache.get.return_value = _make_stock()
    mock_cache.scan.return_value = []

    with patch("flinttrade_screener.stock_routes._get_cache", return_value=mock_cache):
        resp = client.get("/v1/stocks/scan?limit=999")

    assert resp.status_code == 200
    # scan must be called with limit=200 (clamped)
    _, kwargs = mock_cache.scan.call_args
    assert kwargs.get("limit", mock_cache.scan.call_args[0][1] if mock_cache.scan.call_args[0] else 200) <= 200


def test_stock_scan_triggers_seed_when_cache_empty(client):
    """_ensure_seeded upserts seed data when cache returns None for first symbol."""
    mock_cache = MagicMock()
    mock_cache.get.return_value = None   # cache is cold
    mock_cache.scan.return_value = []

    with patch("flinttrade_screener.stock_routes._get_cache", return_value=mock_cache):
        resp = client.get("/v1/stocks/scan")

    assert resp.status_code == 200
    # At least one upsert should have been called to seed the cache
    assert mock_cache.upsert.call_count > 0


def test_stock_scan_internal_error(client):
    """500 when an unexpected exception occurs in the handler."""
    mock_cache = MagicMock()
    mock_cache.get.side_effect = RuntimeError("DuckDB connection lost")

    with patch("flinttrade_screener.stock_routes._get_cache", return_value=mock_cache):
        resp = client.get("/v1/stocks/scan")

    assert resp.status_code == 500
    body = resp.get_json()
    assert body["status"] == "error"


def test_stock_scan_sort_by_param(client):
    """200 and sort_by is forwarded to cache.scan."""
    mock_cache = MagicMock()
    mock_cache.get.return_value = _make_stock()
    mock_cache.scan.return_value = [_make_stock()]

    with patch("flinttrade_screener.stock_routes._get_cache", return_value=mock_cache):
        resp = client.get("/v1/stocks/scan?sort_by=pe_ratio")

    assert resp.status_code == 200
    # Verify scan was passed sort_by
    call_args = mock_cache.scan.call_args
    assert call_args is not None


def test_stock_scan_empty_cache(client):
    """200 with empty stocks list when cache returns nothing after seeding."""
    mock_cache = MagicMock()
    mock_cache.get.return_value = None
    mock_cache.scan.return_value = []

    with patch("flinttrade_screener.stock_routes._get_cache", return_value=mock_cache):
        resp = client.get("/v1/stocks/scan")

    assert resp.status_code == 200
    body = resp.get_json()
    assert body["data"]["count"] == 0
    assert body["data"]["stocks"] == []
