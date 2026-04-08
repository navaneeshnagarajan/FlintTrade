"""Tests for Mutual Fund NAV Flask routes.

Uses Flask test client with mocked AMFI data to avoid network calls in CI.
"""

from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import patch

import pytest

# Ensure repo root is on sys.path for cross-package imports
_REPO_ROOT = str(Path(__file__).resolve().parents[3])
if _REPO_ROOT not in sys.path:
    sys.path.insert(0, _REPO_ROOT)


# ---------------------------------------------------------------------------
# Sample AMFI NAV data (mimics the real pipe-delimited format)
# ---------------------------------------------------------------------------

SAMPLE_NAV_TEXT = """\
Open Ended Schemes(Equity Scheme - Large Cap Fund)
Axis Mutual Fund
Scheme Code;ISIN Div Payout/ ISIN Growth;ISIN Div Reinvestment;Scheme Name;Net Asset Value;Date
120503;INF846K01DP8;INF846K01DQ6;Axis Bluechip Fund - Direct Plan - Growth;62.4500;08-Apr-2026
120504;INF846K01DR4;INF846K01DS2;Axis Bluechip Fund - Regular Plan - Growth;58.1200;08-Apr-2026

Open Ended Schemes(Equity Scheme - Flexi Cap Fund)
PPFAS Mutual Fund
Scheme Code;ISIN Div Payout/ ISIN Growth;ISIN Div Reinvestment;Scheme Name;Net Asset Value;Date
122639;INF879O01019;INF879O01027;Parag Parikh Flexi Cap Fund - Direct Plan - Growth;89.1200;08-Apr-2026

Open Ended Schemes(Equity Scheme - Mid Cap Fund)
HDFC Mutual Fund
Scheme Code;ISIN Div Payout/ ISIN Growth;ISIN Div Reinvestment;Scheme Name;Net Asset Value;Date
118989;INF179K01BB8;INF179K01BC6;HDFC Mid-Cap Opportunities Fund - Direct Plan - Growth;145.6700;08-Apr-2026

Open Ended Schemes(Debt Scheme - Liquid Fund)
SBI Mutual Fund
Scheme Code;ISIN Div Payout/ ISIN Growth;ISIN Div Reinvestment;Scheme Name;Net Asset Value;Date
119550;INF200K01180;INF200K01198;SBI Liquid Fund - Direct Plan - Growth;3845.2300;08-Apr-2026
"""


def _mock_fetch(url, timeout=30):
    """Mock urlopen that returns sample NAV data."""

    class FakeResponse:
        def read(self):
            return SAMPLE_NAV_TEXT.encode("utf-8")

        def __enter__(self):
            return self

        def __exit__(self, *args):
            pass

    return FakeResponse()


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def _clear_cache():
    """Clear the module-level cache before each test."""
    import packages.screener.src.mf_routes as mod
    mod._funds_cache = []
    mod._categories_cache = []
    mod._cache_ts = 0.0
    yield


@pytest.fixture()
def app():
    """Create a minimal Flask app with only the MF blueprint registered."""
    from flask import Flask
    from packages.screener.src.mf_routes import mf_bp

    flask_app = Flask("test_mf")
    flask_app.config["TESTING"] = True
    flask_app.register_blueprint(mf_bp)
    return flask_app


@pytest.fixture()
def client(app):
    """Flask test client with mocked AMFI fetch."""
    with patch("packages.screener.src.mf_routes.urlopen", side_effect=_mock_fetch):
        yield app.test_client()


# ---------------------------------------------------------------------------
# GET /api/v1/mf/search?q=...
# ---------------------------------------------------------------------------


class TestMFSearch:
    """Tests for GET /api/v1/mf/search."""

    def test_returns_200(self, client):
        resp = client.get("/api/v1/mf/search?q=axis")
        assert resp.status_code == 200

    def test_status_ok(self, client):
        body = client.get("/api/v1/mf/search?q=axis").get_json()
        assert body["status"] == "success"

    def test_has_funds_list(self, client):
        body = client.get("/api/v1/mf/search?q=axis").get_json()
        assert "funds" in body
        assert isinstance(body["funds"], list)

    def test_search_matches_name(self, client):
        body = client.get("/api/v1/mf/search?q=axis").get_json()
        assert body["count"] > 0
        assert all("axis" in f["scheme_name"].lower() or "axis" in f["amc"].lower() for f in body["funds"])

    def test_search_matches_amc(self, client):
        body = client.get("/api/v1/mf/search?q=hdfc").get_json()
        assert body["count"] > 0

    def test_search_query_too_short(self, client):
        resp = client.get("/api/v1/mf/search?q=a")
        assert resp.status_code == 400
        body = resp.get_json()
        assert body["status"] == "error"

    def test_search_no_results(self, client):
        body = client.get("/api/v1/mf/search?q=zzzznotfound").get_json()
        assert body["status"] == "success"
        assert body["count"] == 0
        assert body["funds"] == []

    def test_fund_entry_shape(self, client):
        body = client.get("/api/v1/mf/search?q=axis").get_json()
        if body["funds"]:
            fund = body["funds"][0]
            assert "scheme_code" in fund
            assert "scheme_name" in fund
            assert "amc" in fund
            assert "category" in fund
            assert "nav" in fund
            assert "nav_date" in fund
            assert "scheme_type" in fund
            assert isinstance(fund["scheme_code"], int)
            assert isinstance(fund["nav"], float)


# ---------------------------------------------------------------------------
# GET /api/v1/mf/nav/<scheme_code>
# ---------------------------------------------------------------------------


class TestMFNAV:
    """Tests for GET /api/v1/mf/nav/<scheme_code>."""

    def test_returns_200_for_known_code(self, client):
        resp = client.get("/api/v1/mf/nav/120503")
        assert resp.status_code == 200

    def test_fund_data_correct(self, client):
        body = client.get("/api/v1/mf/nav/120503").get_json()
        assert body["status"] == "success"
        assert body["fund"]["scheme_code"] == 120503
        assert body["fund"]["nav"] == 62.45
        assert "Axis" in body["fund"]["scheme_name"]

    def test_returns_404_for_unknown_code(self, client):
        resp = client.get("/api/v1/mf/nav/999999999")
        assert resp.status_code == 404
        body = resp.get_json()
        assert body["status"] == "error"


# ---------------------------------------------------------------------------
# GET /api/v1/mf/categories
# ---------------------------------------------------------------------------


class TestMFCategories:
    """Tests for GET /api/v1/mf/categories."""

    def test_returns_200(self, client):
        resp = client.get("/api/v1/mf/categories")
        assert resp.status_code == 200

    def test_has_categories_list(self, client):
        body = client.get("/api/v1/mf/categories").get_json()
        assert body["status"] == "success"
        assert "categories" in body
        assert isinstance(body["categories"], list)

    def test_categories_not_empty(self, client):
        body = client.get("/api/v1/mf/categories").get_json()
        assert body["count"] > 0
        assert len(body["categories"]) > 0

    def test_categories_are_strings(self, client):
        body = client.get("/api/v1/mf/categories").get_json()
        for cat in body["categories"]:
            assert isinstance(cat, str)
            assert len(cat) > 0


# ---------------------------------------------------------------------------
# Parser unit tests
# ---------------------------------------------------------------------------


class TestAMFIParser:
    """Unit tests for the AMFI NAV text parser."""

    def test_parse_returns_list(self):
        from packages.screener.src.mf_routes import _parse_amfi_nav
        result = _parse_amfi_nav(SAMPLE_NAV_TEXT)
        assert isinstance(result, list)

    def test_parse_correct_count(self):
        from packages.screener.src.mf_routes import _parse_amfi_nav
        result = _parse_amfi_nav(SAMPLE_NAV_TEXT)
        # 5 data lines in sample
        assert len(result) == 5

    def test_parse_extracts_scheme_code(self):
        from packages.screener.src.mf_routes import _parse_amfi_nav
        result = _parse_amfi_nav(SAMPLE_NAV_TEXT)
        codes = {f.scheme_code for f in result}
        assert 120503 in codes
        assert 122639 in codes

    def test_parse_extracts_category(self):
        from packages.screener.src.mf_routes import _parse_amfi_nav
        result = _parse_amfi_nav(SAMPLE_NAV_TEXT)
        fund = next(f for f in result if f.scheme_code == 120503)
        assert fund.category == "Equity Scheme - Large Cap Fund"

    def test_parse_extracts_amc(self):
        from packages.screener.src.mf_routes import _parse_amfi_nav
        result = _parse_amfi_nav(SAMPLE_NAV_TEXT)
        fund = next(f for f in result if f.scheme_code == 120503)
        assert fund.amc == "Axis Mutual Fund"

    def test_parse_extracts_nav(self):
        from packages.screener.src.mf_routes import _parse_amfi_nav
        result = _parse_amfi_nav(SAMPLE_NAV_TEXT)
        fund = next(f for f in result if f.scheme_code == 119550)
        assert fund.nav == 3845.23

    def test_parse_empty_input(self):
        from packages.screener.src.mf_routes import _parse_amfi_nav
        result = _parse_amfi_nav("")
        assert result == []
