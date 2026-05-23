"""Tests for packages/services/backtest/src/permutation_routes.py — permutation & walk-forward."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest
from flask import Flask

import permutation_routes as mod  # noqa: E402 — conftest adds src/ to sys.path


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

_RETURNS = [0.01, -0.005, 0.008, 0.003, -0.002] * 10


def _mock_perm_result():
    r = MagicMock()
    r.p_value = 0.021
    r.is_significant = True
    r.as_dict.return_value = {
        "original_metric": 1.42,
        "p_value": 0.021,
        "is_significant": True,
    }
    return r


def _mock_wf_result():
    r = MagicMock()
    r.n_splits_run = 5
    r.degradation_pct = 20.5
    r.is_robust = True
    r.as_dict.return_value = {
        "splits": [],
        "avg_train_metric": 1.12,
        "avg_test_metric": 0.89,
        "degradation_pct": 20.5,
        "is_robust": True,
        "n_splits_run": 5,
    }
    return r


@pytest.fixture()
def app():
    flask_app = Flask(__name__)
    flask_app.config["TESTING"] = True
    flask_app.register_blueprint(mod.permutation_bp)
    return flask_app


@pytest.fixture()
def client(app):
    return app.test_client()


# ---------------------------------------------------------------------------
# POST /ft-api/v1/backtest/permutation
# ---------------------------------------------------------------------------


def test_permutation_ok(client):
    """200 for valid returns-mode request."""
    with patch(
        "permutation_routes.PermutationTester"
    ) as MockTester:
        instance = MagicMock()
        instance.test_returns.return_value = _mock_perm_result()
        MockTester.return_value = instance

        resp = client.post(
            "/v1/backtest/permutation",
            json={"returns": _RETURNS},
        )

    assert resp.status_code == 200
    body = resp.get_json()
    assert body["status"] == "success"
    assert "p_value" in body["data"]


def test_permutation_missing_returns(client):
    """400 when returns is absent in returns mode."""
    resp = client.post("/v1/backtest/permutation", json={"mode": "returns"})
    assert resp.status_code == 400


def test_permutation_invalid_config(client):
    """400 for unparseable config."""
    resp = client.post(
        "/v1/backtest/permutation",
        json={"returns": _RETURNS, "config": "not-a-dict"},
    )
    assert resp.status_code == 400


def test_permutation_trades_mode_missing_trades(client):
    """400 when trades mode but trades field absent."""
    resp = client.post(
        "/v1/backtest/permutation",
        json={"mode": "trades", "returns": _RETURNS},
    )
    assert resp.status_code == 400


# ---------------------------------------------------------------------------
# POST /ft-api/v1/backtest/walkforward
# ---------------------------------------------------------------------------

_BARS = [{"close": 18500.0 + i * 10} for i in range(30)]


def test_walkforward_ok(client):
    """200 for valid bars input."""
    with patch(
        "permutation_routes.WalkForwardAnalyser"
    ) as MockWF:
        instance = MagicMock()
        instance.analyse.return_value = _mock_wf_result()
        MockWF.return_value = instance

        resp = client.post(
            "/v1/backtest/walkforward",
            json={"bars": _BARS},
        )

    assert resp.status_code == 200
    body = resp.get_json()
    assert body["status"] == "success"
    assert body["data"]["is_robust"] is True


def test_walkforward_missing_bars(client):
    """400 when bars field absent."""
    resp = client.post("/v1/backtest/walkforward", json={})
    assert resp.status_code == 400


def test_walkforward_empty_bars(client):
    """400 for empty bars list."""
    resp = client.post("/v1/backtest/walkforward", json={"bars": []})
    assert resp.status_code == 400
