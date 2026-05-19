"""Tests for packages/screener/src/fundamental_routes.py — fundamental screener endpoints."""

from __future__ import annotations

from dataclasses import dataclass
from unittest.mock import patch

import pytest
from flask import Flask

import packages.screener.src.fundamental_routes as mod


# ---------------------------------------------------------------------------
# Helpers — minimal dataclass-compatible objects
# ---------------------------------------------------------------------------


@dataclass
class _SearchResult:
    """Minimal search result with attributes the route accesses."""
    name: str = "Reliance Industries"
    symbol: str = "RELIANCE"
    url: str = "https://www.screener.in/company/RELIANCE/"


@dataclass
class _CompanyData:
    """Minimal company fundamentals for asdict() serialisation."""
    symbol: str = "RELIANCE"
    name: str = "Reliance Industries"
    pe: float = 25.0
    pb: float = 2.1
    market_cap: float = 1_800_000.0
    roe: float = 0.14
    sector: str = "Energy"


@dataclass
class _ScreenResult:
    """Minimal screener result matching what fundamental_screen accesses."""
    symbol: str = "RELIANCE"
    name: str = "Reliance Industries"
    exchange: str = "NSE"
    market_cap: float = 1_800_000.0
    pe_ratio: float = 25.0
    pb_ratio: float = 2.1
    roe: float = 0.14
    roce: float = 0.18
    dividend_yield: float = 0.01
    sector: str = "Energy"


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture()
def app():
    flask_app = Flask(__name__)
    flask_app.config["TESTING"] = True
    flask_app.register_blueprint(mod.fundamental_bp)
    return flask_app


@pytest.fixture()
def client(app):
    return app.test_client()


# ---------------------------------------------------------------------------
# GET /api/v1/screener/fundamental/search
# ---------------------------------------------------------------------------


def test_search_ok(client):
    """200 with company search results."""
    with patch(
        "packages.screener.src.fundamental_routes._run_async",
        return_value=[_SearchResult()],
    ):
        resp = client.get("/api/v1/screener/fundamental/search?q=reliance")
    assert resp.status_code == 200
    body = resp.get_json()
    assert body["status"] == "success"
    assert body["data"]["count"] == 1
    assert body["data"]["results"][0]["symbol"] == "RELIANCE"


def test_search_short_q(client):
    """400 when q < 2 characters."""
    resp = client.get("/api/v1/screener/fundamental/search?q=r")
    assert resp.status_code == 400


def test_search_missing_q(client):
    """400 when q param absent."""
    resp = client.get("/api/v1/screener/fundamental/search")
    assert resp.status_code == 400


# ---------------------------------------------------------------------------
# GET /api/v1/screener/fundamental/<symbol>
# ---------------------------------------------------------------------------


def test_get_company_ok(client):
    """200 with company fundamentals."""
    with patch(
        "packages.screener.src.fundamental_routes._run_async",
        return_value=_CompanyData(),
    ):
        resp = client.get("/api/v1/screener/fundamental/RELIANCE")
    assert resp.status_code == 200
    body = resp.get_json()
    assert body["status"] == "success"
    assert body["data"]["symbol"] == "RELIANCE"


def test_get_company_not_found(client):
    """500 or 404 when company data not found (asdict on None raises exception)."""
    with patch(
        "packages.screener.src.fundamental_routes._run_async",
        side_effect=Exception("Not found"),
    ):
        resp = client.get("/api/v1/screener/fundamental/UNKNOWNSYMBOL")
    # The route catches all exceptions and returns 500
    assert resp.status_code in {404, 500}
    assert resp.get_json()["status"] == "error"


# ---------------------------------------------------------------------------
# POST /api/v1/screener/fundamental/screen
# ---------------------------------------------------------------------------


def test_screen_ok(client):
    """200 with screened companies list."""
    with patch(
        "packages.screener.src.fundamental_routes._run_async",
        return_value=[_ScreenResult()],
    ):
        resp = client.post(
            "/api/v1/screener/fundamental/screen",
            json={"min_roe": 0.12, "max_pe": 30},
        )
    assert resp.status_code == 200
    body = resp.get_json()
    assert body["status"] == "success"
    assert isinstance(body["data"]["stocks"], list)
    assert body["data"]["stocks"][0]["symbol"] == "RELIANCE"


def test_screen_empty_result(client):
    """200 with empty stocks list when no companies pass the filter."""
    with patch(
        "packages.screener.src.fundamental_routes._run_async",
        return_value=[],
    ):
        resp = client.post("/api/v1/screener/fundamental/screen", json={})
    assert resp.status_code == 200
    assert resp.get_json()["data"]["stocks"] == []
