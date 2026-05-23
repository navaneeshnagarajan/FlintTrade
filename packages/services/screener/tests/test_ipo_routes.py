"""Tests for IPO calendar Flask routes.

Uses Flask test client — reads from the real ipo_calendar.json data file.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

# Ensure repo root is on sys.path for cross-package imports
_REPO_ROOT = str(Path(__file__).resolve().parents[3])
if _REPO_ROOT not in sys.path:
    sys.path.insert(0, _REPO_ROOT)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture()
def app():
    """Create a minimal Flask app with only the IPO blueprint registered."""
    from flask import Flask
    from flinttrade_screener.ipo_routes import ipo_bp

    flask_app = Flask("test_ipo")
    flask_app.config["TESTING"] = True
    flask_app.register_blueprint(ipo_bp)
    return flask_app


@pytest.fixture()
def client(app):
    """Flask test client."""
    return app.test_client()


# ---------------------------------------------------------------------------
# GET /api/v1/ipo/upcoming
# ---------------------------------------------------------------------------


class TestIpoUpcoming:
    """Tests for GET /api/v1/ipo/upcoming."""

    def test_returns_200(self, client):
        resp = client.get("/api/v1/ipo/upcoming")
        assert resp.status_code == 200

    def test_status_ok(self, client):
        body = client.get("/api/v1/ipo/upcoming").get_json()
        assert body["status"] == "success"

    def test_has_ipos_list(self, client):
        body = client.get("/api/v1/ipo/upcoming").get_json()
        assert "ipos" in body["data"]
        assert isinstance(body["data"]["ipos"], list)

    def test_has_last_updated(self, client):
        body = client.get("/api/v1/ipo/upcoming").get_json()
        assert "last_updated" in body["data"]

    def test_ipo_entry_shape(self, client):
        body = client.get("/api/v1/ipo/upcoming").get_json()
        if body["data"]["ipos"]:
            ipo = body["data"]["ipos"][0]
            assert "name" in ipo
            assert "symbol" in ipo
            assert "issue_size" in ipo
            assert "status" in ipo
            assert ipo["status"] in ("upcoming", "open", "closed", "listed")


# ---------------------------------------------------------------------------
# GET /api/v1/ipo/recent
# ---------------------------------------------------------------------------


class TestIpoRecent:
    """Tests for GET /api/v1/ipo/recent."""

    def test_returns_200(self, client):
        resp = client.get("/api/v1/ipo/recent")
        assert resp.status_code == 200

    def test_status_ok(self, client):
        body = client.get("/api/v1/ipo/recent").get_json()
        assert body["status"] == "success"

    def test_has_ipos_list(self, client):
        body = client.get("/api/v1/ipo/recent").get_json()
        assert "ipos" in body["data"]
        assert isinstance(body["data"]["ipos"], list)

    def test_recent_has_entries(self, client):
        """The data file should have at least some recent IPOs."""
        body = client.get("/api/v1/ipo/recent").get_json()
        assert len(body["data"]["ipos"]) > 0

    def test_recent_entries_have_listing_gain(self, client):
        """Recent (listed) IPOs should have a numeric listing_gain."""
        body = client.get("/api/v1/ipo/recent").get_json()
        listed = [i for i in body["data"]["ipos"] if i["status"] == "listed"]
        for ipo in listed:
            assert ipo["listing_gain"] is not None
            assert isinstance(ipo["listing_gain"], (int, float))

    def test_ipo_entry_fields(self, client):
        """Verify all expected fields are present in each entry."""
        body = client.get("/api/v1/ipo/recent").get_json()
        required_fields = {
            "name", "symbol", "issue_size", "price_band",
            "lot_size", "open_date", "close_date", "listing_date",
            "status", "listing_gain",
        }
        for ipo in body["data"]["ipos"]:
            assert required_fields.issubset(ipo.keys()), (
                f"Missing fields in {ipo.get('symbol', '?')}: "
                f"{required_fields - set(ipo.keys())}"
            )
