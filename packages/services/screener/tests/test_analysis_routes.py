"""Tests for Flask analysis routes blueprint.

Uses Flask test client — no real broker connections or API calls required.
All endpoints fall back to sample data when no registry is connected.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

# Ensure repo root is on sys.path for cross-package imports
_REPO_ROOT = str(Path(__file__).resolve().parents[4])
if _REPO_ROOT not in sys.path:
    sys.path.insert(0, _REPO_ROOT)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture()
def app():
    """Create a minimal Flask app with only the analysis blueprint registered."""
    from flask import Flask
    from flinttrade_screener.analysis_routes import analysis_bp

    flask_app = Flask("test_analysis")
    flask_app.config["TESTING"] = True
    # No REGISTRY in config → endpoints fall back to sample data
    flask_app.register_blueprint(analysis_bp)
    return flask_app


@pytest.fixture()
def client(app):
    """Flask test client."""
    return app.test_client()


def _post(client, path: str, body: dict | None = None):
    """Helper: POST JSON to the given path and return parsed response."""
    data = json.dumps(body or {})
    response = client.post(
        path,
        data=data,
        content_type="application/json",
    )
    return response, response.get_json()


# ---------------------------------------------------------------------------
# GEX endpoint
# ---------------------------------------------------------------------------


class TestGEXEndpoint:
    """Tests for POST /v1/gex."""

    def test_gex_returns_200(self, client):
        resp, body = _post(client, "/api/v1/gex", {"symbol": "NIFTY", "exchange": "NFO", "expiry": "26MAR26"})
        assert resp.status_code == 200

    def test_gex_status_ok(self, client):
        _, body = _post(client, "/api/v1/gex", {"symbol": "NIFTY", "exchange": "NFO"})
        assert body["status"] == "success"

    def test_gex_has_data(self, client):
        _, body = _post(client, "/api/v1/gex", {"symbol": "NIFTY", "exchange": "NFO"})
        assert "data" in body
        # Terminal GEXData contract (mapped from the GEXResult dataclass).
        data = body["data"]
        assert "strikes" in data
        assert "net_gex" in data  # was total_net_gex on the dataclass
        assert "atm_strike" in data
        assert "gamma_flip_strike" in data
        assert "dealer_zone" in data
        assert "underlying" in data
        # Per-strike objects use the frontend `strike` key, not `strike_price`.
        if data["strikes"]:
            assert "strike" in data["strikes"][0]
            assert "call_gex" in data["strikes"][0]

    def test_gex_strikes_not_empty(self, client):
        _, body = _post(client, "/api/v1/gex", {"symbol": "NIFTY", "exchange": "NFO"})
        assert len(body["data"]["strikes"]) > 0

    def test_gex_symbol_in_response(self, client):
        _, body = _post(client, "/api/v1/gex", {"symbol": "BANKNIFTY", "exchange": "NFO"})
        assert body["symbol"] == "BANKNIFTY"


# ---------------------------------------------------------------------------
# Vol Surface endpoint
# ---------------------------------------------------------------------------


class TestVolSurfaceEndpoint:
    """Tests for POST /v1/volsurface."""

    def test_volsurface_returns_200(self, client):
        resp, _ = _post(client, "/api/v1/volsurface", {
            "symbol": "NIFTY", "exchange": "NFO",
            "expiries": ["26MAR26", "24APR26"], "strike_count": 20,
        })
        assert resp.status_code == 200

    def test_volsurface_status_ok(self, client):
        _, body = _post(client, "/api/v1/volsurface", {
            "symbol": "NIFTY", "exchange": "NFO", "expiries": ["26MAR26"],
        })
        assert body["status"] == "success"

    def test_volsurface_has_matrix(self, client):
        _, body = _post(client, "/api/v1/volsurface", {
            "symbol": "NIFTY", "exchange": "NFO",
            "expiries": ["26MAR26", "24APR26"],
        })
        # Terminal VolSurfaceData contract (mapped from the raw dataclass).
        data = body["data"]
        assert "iv_matrix" in data
        assert "strikes" in data
        assert "days_to_expiry" in data  # was expiries_dte on the dataclass
        assert "expiries" in data  # human-readable labels
        assert "atm_strike" in data
        assert "underlying" in data
        assert "spot_price" in data

    def test_volsurface_matrix_dimensions(self, client):
        """iv_matrix rows should match expiry count."""
        _, body = _post(client, "/api/v1/volsurface", {
            "symbol": "NIFTY", "exchange": "NFO",
            "expiries": ["26MAR26", "24APR26", "29MAY26"],
        })
        data = body["data"]
        n_expiries = len(data["days_to_expiry"])
        n_strikes = len(data["strikes"])
        assert len(data["iv_matrix"]) == n_expiries
        for row in data["iv_matrix"]:
            assert len(row) == n_strikes

    def test_volsurface_strike_count_limited(self, client):
        _, body = _post(client, "/api/v1/volsurface", {
            "symbol": "NIFTY", "exchange": "NFO",
            "expiries": ["26MAR26"], "strike_count": 5,
        })
        assert len(body["data"]["strikes"]) <= 5


# ---------------------------------------------------------------------------
# IV Smile endpoint
# ---------------------------------------------------------------------------


class TestIVSmileEndpoint:
    """Tests for POST /v1/ivsmile."""

    def test_ivsmile_returns_200(self, client):
        resp, _ = _post(client, "/api/v1/ivsmile", {
            "symbol": "NIFTY", "exchange": "NFO", "expiry": "26MAR26",
        })
        assert resp.status_code == 200

    def test_ivsmile_status_ok(self, client):
        _, body = _post(client, "/api/v1/ivsmile", {"symbol": "NIFTY", "exchange": "NFO"})
        assert body["status"] == "success"

    def test_ivsmile_has_required_fields(self, client):
        _, body = _post(client, "/api/v1/ivsmile", {"symbol": "NIFTY", "exchange": "NFO"})
        # Terminal IVSmileData contract: a `curves` array of per-strike points.
        data = body["data"]
        assert "underlying" in data
        assert "spot_price" in data
        assert "curves" in data and len(data["curves"]) >= 1
        curve = data["curves"][0]
        assert "atm_iv" in curve
        assert "atm_strike" in curve
        assert "skew_25delta" in curve  # was `skew` on the dataclass
        assert "points" in curve
        if curve["points"]:
            p = curve["points"][0]
            assert "strike" in p and "call_iv" in p and "put_iv" in p and "moneyness" in p

    def test_ivsmile_strikes_not_empty(self, client):
        _, body = _post(client, "/api/v1/ivsmile", {"symbol": "NIFTY", "exchange": "NFO"})
        assert len(body["data"]["curves"][0]["points"]) > 0

    def test_ivsmile_atm_iv_positive(self, client):
        _, body = _post(client, "/api/v1/ivsmile", {"symbol": "NIFTY", "exchange": "NFO"})
        assert body["data"]["curves"][0]["atm_iv"] > 0


# ---------------------------------------------------------------------------
# Straddle P&L endpoint
# ---------------------------------------------------------------------------


class TestStraddlePnLEndpoint:
    """Tests for POST /v1/straddlepnl."""

    def test_straddlepnl_returns_200(self, client):
        resp, _ = _post(client, "/api/v1/straddlepnl", {
            "symbol": "NIFTY", "exchange": "NFO", "expiry": "26MAR26",
            "interval": "5m", "adjustment_points": 50,
        })
        assert resp.status_code == 200

    def test_straddlepnl_status_ok(self, client):
        _, body = _post(client, "/api/v1/straddlepnl", {"symbol": "NIFTY"})
        assert body["status"] == "success"

    def test_straddlepnl_has_required_fields(self, client):
        _, body = _post(client, "/api/v1/straddlepnl", {"symbol": "NIFTY"})
        data = body["data"]
        assert "timestamps" in data
        assert "pnl_series" in data
        assert "adjustments" in data
        assert "max_pnl" in data
        assert "min_pnl" in data
        assert "final_pnl" in data
        assert "initial_premium" in data

    def test_straddlepnl_timestamps_not_empty(self, client):
        _, body = _post(client, "/api/v1/straddlepnl", {"symbol": "NIFTY"})
        assert len(body["data"]["timestamps"]) > 0

    def test_straddlepnl_pnl_series_same_length_as_timestamps(self, client):
        _, body = _post(client, "/api/v1/straddlepnl", {"symbol": "NIFTY"})
        data = body["data"]
        assert len(data["pnl_series"]) == len(data["timestamps"])


# ---------------------------------------------------------------------------
# OI Profile endpoint
# ---------------------------------------------------------------------------


class TestOIProfileEndpoint:
    """Tests for POST /v1/oiprofile."""

    def test_oiprofile_returns_200(self, client):
        resp, _ = _post(client, "/api/v1/oiprofile", {
            "symbol": "NIFTY", "exchange": "NFO", "expiry": "26MAR26", "interval": "5m",
        })
        assert resp.status_code == 200

    def test_oiprofile_status_ok(self, client):
        _, body = _post(client, "/api/v1/oiprofile", {"symbol": "NIFTY"})
        assert body["status"] == "success"

    def test_oiprofile_has_required_fields(self, client):
        _, body = _post(client, "/api/v1/oiprofile", {"symbol": "NIFTY"})
        data = body["data"]
        assert "strikes" in data
        assert "ce_oi" in data
        assert "pe_oi" in data
        assert "oi_butterfly" in data
        assert "oi_change" in data
        assert "futures_ohlcv" in data

    def test_oiprofile_butterfly_length_matches_strikes(self, client):
        _, body = _post(client, "/api/v1/oiprofile", {"symbol": "NIFTY"})
        data = body["data"]
        assert len(data["oi_butterfly"]) == len(data["strikes"])

    def test_oiprofile_strikes_not_empty(self, client):
        _, body = _post(client, "/api/v1/oiprofile", {"symbol": "NIFTY"})
        assert len(body["data"]["strikes"]) > 0


# ---------------------------------------------------------------------------
# Max Pain endpoint
# ---------------------------------------------------------------------------


class TestMaxPainEndpoint:
    """Tests for POST /v1/maxpain."""

    def test_maxpain_returns_200(self, client):
        resp, _ = _post(client, "/api/v1/maxpain", {
            "symbol": "NIFTY", "exchange": "NFO", "expiry": "26MAR26",
        })
        assert resp.status_code == 200

    def test_maxpain_status_ok(self, client):
        _, body = _post(client, "/api/v1/maxpain", {"symbol": "NIFTY"})
        assert body["status"] == "success"

    def test_maxpain_has_strike(self, client):
        _, body = _post(client, "/api/v1/maxpain", {"symbol": "NIFTY"})
        data = body["data"]
        assert "max_pain_strike" in data
        assert data["max_pain_strike"] > 0

    def test_maxpain_has_strike_losses(self, client):
        _, body = _post(client, "/api/v1/maxpain", {"symbol": "NIFTY"})
        data = body["data"]
        assert "strike_losses" in data
        assert len(data["strike_losses"]) > 0

    def test_maxpain_total_loss_positive(self, client):
        _, body = _post(client, "/api/v1/maxpain", {"symbol": "NIFTY"})
        assert body["data"]["total_loss_at_max_pain"] >= 0

    def test_maxpain_strike_near_spot(self, client):
        """Max pain should be within a reasonable range of the spot."""
        _, body = _post(client, "/api/v1/maxpain", {"symbol": "NIFTY"})
        spot = body["spot"]
        max_pain = body["data"]["max_pain_strike"]
        # Max pain within 10% of spot is reasonable for synthetic data
        assert abs(max_pain - spot) <= spot * 0.10


# ---------------------------------------------------------------------------
# Expiry param normalisation (feature audit H7)
# ---------------------------------------------------------------------------


class TestExpiryParamNormalisation:
    """The terminal sends expiry_date/expiry_dates; routes must honour them."""

    def test_body_expiry_accepts_all_key_variants(self):
        from flinttrade_screener.analysis_routes import _body_expiry

        assert _body_expiry({"expiry": "26MAR26"}, "X") == "26MAR26"
        assert _body_expiry({"expiry_date": "26MAR26"}, "X") == "26MAR26"
        assert _body_expiry({"expiry_dates": ["26MAR26", "24APR26"]}, "X") == "26MAR26"
        assert _body_expiry({}, "FALLBACK") == "FALLBACK"

    def test_body_expiries_accepts_all_key_variants(self):
        from flinttrade_screener.analysis_routes import _body_expiries

        assert _body_expiries({"expiries": ["A"]}, ["X"]) == ["A"]
        assert _body_expiries({"expiry_dates": ["A", "B"]}, ["X"]) == ["A", "B"]
        assert _body_expiries({"expiry_date": "A"}, ["X"]) == ["A"]
        assert _body_expiries({}, ["DEF"]) == ["DEF"]

    def test_oiprofile_honours_frontend_expiry_date_key(self, client):
        resp, _ = _post(
            client,
            "/api/v1/oiprofile",
            {"symbol": "NIFTY", "exchange": "NFO", "expiry_date": "26MAR26"},
        )
        assert resp.status_code == 200

    def test_gex_honours_frontend_expiry_date_key(self, client):
        resp, _ = _post(
            client,
            "/api/v1/gex",
            {"symbol": "NIFTY", "exchange": "NFO", "expiry_date": "26MAR26"},
        )
        assert resp.status_code == 200
