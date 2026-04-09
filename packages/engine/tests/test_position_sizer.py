"""Tests for packages/engine/src/position_sizer.py and the /api/v1/position/size endpoint.

No live broker required — all tests are purely arithmetic.
"""

from __future__ import annotations

import pytest
from flask import Flask


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture()
def sizer():
    from packages.engine.src.position_sizer import PositionSizer
    return PositionSizer


@pytest.fixture()
def app():
    from packages.engine.src.position_sizer_routes import position_bp
    flask_app = Flask(__name__)
    flask_app.config["TESTING"] = True
    flask_app.register_blueprint(position_bp)
    return flask_app


@pytest.fixture()
def client(app):
    return app.test_client()


# ---------------------------------------------------------------------------
# Test 1 — from_capital
# ---------------------------------------------------------------------------


class TestFromCapital:
    """Invest a fixed rupee amount."""

    def test_basic_equity(self, sizer):
        # 50,000 / 500 = 100 shares
        assert sizer.from_capital(50_000, 500.0) == 100

    def test_fno_rounds_to_lot(self, sizer):
        # 55,000 / 500 = 110 → floor to nearest 50 = 100
        assert sizer.from_capital(55_000, 500.0, lot_size=50) == 100

    def test_capital_less_than_one_lot(self, sizer):
        # 10,000 / 500 = 20 shares, lot=50 → 0
        assert sizer.from_capital(10_000, 500.0, lot_size=50) == 0

    def test_invalid_zero_capital_returns_zero(self, sizer):
        assert sizer.from_capital(0, 500.0) == 0

    def test_invalid_zero_ltp_returns_zero(self, sizer):
        assert sizer.from_capital(50_000, 0.0) == 0


# ---------------------------------------------------------------------------
# Test 2 — from_risk_percent
# ---------------------------------------------------------------------------


class TestFromRiskPercent:
    """Risk a percentage of capital per trade."""

    def test_standard_calculation(self, sizer):
        # risk=1000, distance=5, raw=200, lot=50 → 200
        qty = sizer.from_risk_percent(100_000, 0.01, 450.0, 445.0, lot_size=50)
        assert qty == 200

    def test_rounds_down_to_lot(self, sizer):
        # risk=1000, distance=7, raw=142, lot=50 → 100
        qty = sizer.from_risk_percent(100_000, 0.01, 450.0, 443.0, lot_size=50)
        assert qty == 100

    def test_zero_distance_returns_zero(self, sizer):
        assert sizer.from_risk_percent(100_000, 0.01, 450.0, 450.0) == 0

    def test_invalid_risk_pct_returns_zero(self, sizer):
        assert sizer.from_risk_percent(100_000, 0.0, 450.0, 445.0) == 0
        assert sizer.from_risk_percent(100_000, 1.5, 450.0, 445.0) == 0

    def test_sl_above_entry_buy_side(self, sizer):
        # SL > entry (long trade but wrong direction) — distance is absolute
        qty = sizer.from_risk_percent(100_000, 0.01, 445.0, 450.0)
        assert qty > 0


# ---------------------------------------------------------------------------
# Test 3 — from_kelly
# ---------------------------------------------------------------------------


class TestFromKelly:
    """Kelly criterion sizing."""

    def test_positive_kelly_gives_nonzero(self, sizer):
        # win_rate=0.55, avg_win=500, avg_loss=300, half-Kelly fraction
        qty = sizer.from_kelly(0.55, 500, 300, 200_000, 500.0)
        assert qty > 0

    def test_negative_kelly_returns_zero(self, sizer):
        # win_rate=0.30, avg_win=100, avg_loss=500 → Kelly fraction < 0
        qty = sizer.from_kelly(0.30, 100, 500, 200_000, 500.0)
        assert qty == 0

    def test_invalid_win_rate_returns_zero(self, sizer):
        assert sizer.from_kelly(0.0, 500, 300, 200_000, 500.0) == 0
        assert sizer.from_kelly(1.0, 500, 300, 200_000, 500.0) == 0

    def test_invalid_ltp_returns_zero(self, sizer):
        assert sizer.from_kelly(0.55, 500, 300, 200_000, 0.0) == 0


# ---------------------------------------------------------------------------
# Test 4 — max_lots
# ---------------------------------------------------------------------------


class TestMaxLots:
    """Maximum affordable lots given margin."""

    def test_basic(self, sizer):
        assert sizer.max_lots(500_000, 120_000) == 4

    def test_exact_division(self, sizer):
        assert sizer.max_lots(240_000, 120_000) == 2

    def test_insufficient_capital(self, sizer):
        assert sizer.max_lots(50_000, 120_000) == 0

    def test_invalid_margin_returns_zero(self, sizer):
        assert sizer.max_lots(500_000, 0) == 0


# ---------------------------------------------------------------------------
# Test 5 — Flask endpoint (happy path + validation)
# ---------------------------------------------------------------------------


class TestPositionSizeEndpoint:
    """HTTP API endpoint tests."""

    def test_from_capital_endpoint(self, client):
        rv = client.post(
            "/api/v1/position/size",
            json={"method": "from_capital", "capital": 50_000, "ltp": 500.0},
        )
        assert rv.status_code == 200
        data = rv.get_json()
        assert data["status"] == "success"
        assert data["data"]["quantity"] == 100
        assert data["data"]["method"] == "from_capital"

    def test_from_risk_percent_endpoint(self, client):
        rv = client.post(
            "/api/v1/position/size",
            json={
                "method": "from_risk_percent",
                "capital": 100_000,
                "risk_pct": 0.01,
                "entry": 450.0,
                "sl": 445.0,
            },
        )
        assert rv.status_code == 200
        data = rv.get_json()
        assert data["data"]["quantity"] == 200

    def test_max_lots_endpoint(self, client):
        rv = client.post(
            "/api/v1/position/size",
            json={"method": "max_lots", "capital": 500_000, "margin_per_lot": 120_000},
        )
        assert rv.status_code == 200
        assert rv.get_json()["data"]["quantity"] == 4

    def test_missing_method_returns_400(self, client):
        rv = client.post(
            "/api/v1/position/size",
            json={"capital": 50_000, "ltp": 500.0},
        )
        assert rv.status_code == 400

    def test_unknown_method_returns_400(self, client):
        rv = client.post(
            "/api/v1/position/size",
            json={"method": "magic_formula", "capital": 50_000},
        )
        assert rv.status_code == 400

    def test_missing_ltp_for_from_capital_returns_400(self, client):
        rv = client.post(
            "/api/v1/position/size",
            json={"method": "from_capital", "capital": 50_000},
        )
        assert rv.status_code == 400
