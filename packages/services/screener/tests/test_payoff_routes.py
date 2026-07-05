"""Tests for packages/services/screener/src/payoff_routes.py — payoff, regime, correlation endpoints."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest
from flask import Flask

import flinttrade_screener.payoff_routes as mod


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

_LEG = {
    "side": "BUY",
    "option_type": "CE",
    "strike": 24000.0,
    "lots": 1,
    "premium": 150.0,
}


def _history_candles(n: int = 40) -> list[dict]:
    base = 1_700_000_000
    return [
        {"timestamp": base + i * 86_400, "open": 100 + i, "high": 102 + i, "low": 99 + i,
         "close": 101 + i, "volume": 10_000 + i}
        for i in range(n)
    ]


class _ConnectedRegistry:
    def __init__(self) -> None:
        self.history_calls: list[tuple[str, dict]] = []

    def is_connected(self) -> bool:
        return True

    def get_primary_account_id(self) -> str:
        return "acc-primary"

    def get_history(self, account_id: str, params: dict) -> dict:
        self.history_calls.append((account_id, params))
        return {"candles": _history_candles()}


@pytest.fixture()
def app():
    """Minimal Flask app with payoff_bp registered."""
    flask_app = Flask(__name__)
    flask_app.config["TESTING"] = True
    flask_app.register_blueprint(mod.payoff_bp)
    return flask_app


@pytest.fixture()
def client(app):
    return app.test_client()


# ---------------------------------------------------------------------------
# POST /ft-api/v1/payoff/analyse
# ---------------------------------------------------------------------------


def test_payoff_analyse_ok(client):
    """200 with full analysis result for a single-leg strategy."""
    result = MagicMock()
    result.model_dump.return_value = {
        "legs": [_LEG],
        "points": [{"spot": 24000.0, "pnl": -150.0}],
        "max_profit": None,
        "max_loss": -150.0,
        "breakevens": [24150.0],
        "net_premium": -150.0,
        "net_delta": 0.52,
        "net_gamma": 0.001,
        "net_theta": -5.2,
        "net_vega": 8.1,
        "pop": 0.48,
    }
    with patch.object(mod._payoff_engine, "calculate", return_value=result):
        resp = client.post(
            "/api/v1/payoff/analyse",
            json={"legs": [_LEG], "spot": 24000.0, "iv": 0.18, "days_to_expiry": 7},
        )
    assert resp.status_code == 200
    body = resp.get_json()
    assert body["status"] == "success"
    assert "breakevens" in body["data"]


def test_payoff_analyse_no_legs(client):
    """400 when legs list is empty."""
    resp = client.post("/api/v1/payoff/analyse", json={"legs": [], "spot": 24000.0})
    assert resp.status_code == 400
    body = resp.get_json()
    assert body["status"] == "error"


def test_payoff_analyse_invalid_leg(client):
    """400 when a leg object has invalid fields."""
    bad_leg = {"side": "INVALID_SIDE", "option_type": "CE", "strike": 24000.0}
    resp = client.post(
        "/api/v1/payoff/analyse",
        json={"legs": [bad_leg], "spot": 24000.0},
    )
    assert resp.status_code == 400


def test_payoff_analyse_engine_error(client):
    """500 when the payoff engine raises an unexpected exception."""
    with patch.object(mod._payoff_engine, "calculate", side_effect=RuntimeError("GPU OOM")):
        resp = client.post(
            "/api/v1/payoff/analyse",
            json={"legs": [_LEG], "spot": 24000.0},
        )
    assert resp.status_code == 500
    body = resp.get_json()
    assert body["status"] == "error"


# ---------------------------------------------------------------------------
# POST /ft-api/v1/payoff/curve
# ---------------------------------------------------------------------------


def _make_point(spot: float = 24000.0, pnl: float = -150.0) -> MagicMock:
    p = MagicMock()
    p.model_dump.return_value = {"spot": spot, "pnl": pnl}
    return p


def test_payoff_curve_ok(client):
    """200 with curve points and net_premium."""
    points = [_make_point(24000.0, -150.0), _make_point(24150.0, 0.0)]
    with patch.object(mod._payoff_engine, "payoff_at_expiry", return_value=points):
        resp = client.post(
            "/api/v1/payoff/curve",
            json={"legs": [_LEG], "spot": 24000.0, "n_points": 50},
        )
    assert resp.status_code == 200
    body = resp.get_json()
    assert body["status"] == "success"
    assert "points" in body["data"]
    assert "net_premium" in body["data"]


def test_payoff_curve_no_legs(client):
    """400 when legs list is absent."""
    resp = client.post("/api/v1/payoff/curve", json={"spot": 24000.0})
    assert resp.status_code == 400


def test_payoff_curve_with_explicit_range(client):
    """200 when an explicit spot_range is supplied."""
    points = [_make_point()]
    with patch.object(mod._payoff_engine, "payoff_at_expiry", return_value=points):
        resp = client.post(
            "/api/v1/payoff/curve",
            json={
                "legs": [_LEG],
                "spot": 24000.0,
                "spot_range": [22000.0, 26000.0],
            },
        )
    assert resp.status_code == 200


def test_payoff_curve_engine_error(client):
    """500 when payoff_at_expiry raises unexpectedly."""
    with patch.object(
        mod._payoff_engine, "payoff_at_expiry", side_effect=ValueError("bad range")
    ):
        resp = client.post(
            "/api/v1/payoff/curve",
            json={"legs": [_LEG], "spot": 24000.0},
        )
    assert resp.status_code == 500


# ---------------------------------------------------------------------------
# GET /ft-api/v1/regime/current
# ---------------------------------------------------------------------------


def _make_regime_signal() -> MagicMock:
    signal = MagicMock()
    signal.model_dump.return_value = {
        "regime": "risk_on",
        "confidence": 0.75,
        "vix_level": 15.0,
        "vix_percentile": 35.0,
        "dxy_level": None,
        "advance_decline_ratio": None,
        "fii_dii_net": None,
        "breadth": None,
        "rationale": "Low VIX indicates calm market.",
    }
    return signal


def test_regime_current_ok(client):
    """200 with regime signal when VIX is provided."""
    signal = _make_regime_signal()
    with patch.object(mod._regime_detector, "detect", return_value=signal):
        resp = client.get("/api/v1/regime/current?vix=15.0")
    assert resp.status_code == 200
    body = resp.get_json()
    assert body["status"] == "success"
    assert "regime" in body["data"]


def test_regime_current_defaults(client):
    """200 using default VIX=15 when no params are given."""
    signal = _make_regime_signal()
    with patch.object(mod._regime_detector, "detect", return_value=signal):
        resp = client.get("/api/v1/regime/current")
    assert resp.status_code == 200


def test_regime_current_full_params(client):
    """200 with all optional parameters supplied."""
    signal = _make_regime_signal()
    with patch.object(mod._regime_detector, "detect", return_value=signal):
        resp = client.get(
            "/api/v1/regime/current"
            "?vix=18.5&dxy=104.2&fii_net=1200&breadth=55&advance=1200&decline=800"
        )
    assert resp.status_code == 200


def test_regime_current_detector_error(client):
    """500 when RegimeDetector raises unexpectedly."""
    with patch.object(
        mod._regime_detector, "detect", side_effect=RuntimeError("model failure")
    ):
        resp = client.get("/api/v1/regime/current?vix=20.0")
    assert resp.status_code == 500
    body = resp.get_json()
    assert body["status"] == "error"


def test_regime_current_uses_connected_registry_history_contract(app, client):
    registry = _ConnectedRegistry()
    app.config["REGISTRY"] = registry
    signal = _make_regime_signal()

    with patch.object(mod._regime_detector, "detect", return_value=signal) as detect:
        resp = client.get("/api/v1/regime/current?vix=15.0")

    assert resp.status_code == 200
    account_id, params = registry.history_calls[0]
    assert account_id == "acc-primary"
    assert params["symbol"] == "NIFTY"
    assert params["exchange"] == "NSE_INDEX"
    assert params["interval"] == "1d"
    assert "start" in params and "end" in params
    assert detect.call_args.kwargs["nifty_returns"]


# ---------------------------------------------------------------------------
# POST /ft-api/v1/analytics/correlation
# ---------------------------------------------------------------------------


def _make_corr_result() -> MagicMock:
    regime = MagicMock()
    regime.regime.value = "risk_on"
    regime.rationale = "Low VIX, positive A/D."
    regime.vix_level = 15.0
    regime.dxy_level = None

    result = MagicMock()
    result.symbols = ["NIFTY", "BANKNIFTY"]
    result.matrix = [[1.0, 0.85], [0.85, 1.0]]
    result.regime = regime
    result.updated_at = "2026-04-19T09:15:00Z"
    result.period_days = 90
    return result


def test_correlation_post_ok(client):
    """200 with correlation matrix on POST with symbols."""
    result = _make_corr_result()
    with patch.object(mod._correlation_engine, "compute", return_value=result), patch(
        "flinttrade_screener.payoff_routes.make_sample_returns",
        return_value={"NIFTY": [0.01] * 90, "BANKNIFTY": [0.009] * 90},
    ):
        resp = client.post(
            "/api/v1/analytics/correlation",
            json={"symbols": ["NIFTY", "BANKNIFTY"], "vix": 15.0},
        )
    assert resp.status_code == 200
    body = resp.get_json()
    assert body["status"] == "success"
    assert "matrix" in body["data"]
    assert "regime" in body["data"]


def test_correlation_get_ok(client):
    """200 on GET request with query params."""
    result = _make_corr_result()
    with patch.object(mod._correlation_engine, "compute", return_value=result), patch(
        "flinttrade_screener.payoff_routes.make_sample_returns",
        return_value={"NIFTY": [0.01] * 90},
    ):
        resp = client.get("/api/v1/analytics/correlation?vix=15.0")
    assert resp.status_code == 200
    body = resp.get_json()
    assert body["status"] == "success"


def test_correlation_sample_data_flag(client):
    """is_sample_data is True when no live registry is attached."""
    result = _make_corr_result()
    with patch.object(mod._correlation_engine, "compute", return_value=result), patch(
        "flinttrade_screener.payoff_routes.make_sample_returns",
        return_value={"NIFTY": [0.01] * 90},
    ):
        resp = client.post("/api/v1/analytics/correlation", json={})
    assert resp.status_code == 200
    body = resp.get_json()
    assert body["data"]["is_sample_data"] is True


def test_correlation_engine_error(client):
    """500 when CorrelationEngine raises unexpectedly."""
    with patch.object(
        mod._correlation_engine, "compute", side_effect=RuntimeError("linalg error")
    ), patch(
        "flinttrade_screener.payoff_routes.make_sample_returns",
        return_value={"NIFTY": [0.01] * 90},
    ):
        resp = client.post("/api/v1/analytics/correlation", json={})
    assert resp.status_code == 500
    body = resp.get_json()
    assert body["status"] == "error"


def test_correlation_uses_connected_registry_history_contract(app, client):
    registry = _ConnectedRegistry()
    app.config["REGISTRY"] = registry
    result = _make_corr_result()

    with patch.object(mod._correlation_engine, "compute", return_value=result):
        resp = client.post(
            "/api/v1/analytics/correlation",
            json={"symbols": ["NIFTY", "BANKNIFTY"], "vix": 15.0},
        )

    assert resp.status_code == 200
    body = resp.get_json()
    assert body["data"]["is_sample_data"] is False
    assert len(registry.history_calls) == 2
    for account_id, params in registry.history_calls:
        assert account_id == "acc-primary"
        assert params["exchange"] == "NSE_INDEX"
        assert params["interval"] == "1d"
        assert "start" in params and "end" in params
