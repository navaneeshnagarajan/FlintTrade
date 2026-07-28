"""Tests for packages/services/screener/src/analytics_routes.py — VWAP, pairs, MTF endpoints."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest
from flask import Flask

import flinttrade_screener.analytics_routes as mod


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
        "flinttrade_indicators.vwap_bands.calculate_vwap_bands",
        return_value=vwap_result,
    ):
        resp = client.post("/v1/indicators/vwap", json={"bars": _BARS})
    assert resp.status_code == 200
    assert resp.get_json()["status"] == "success"


def test_vwap_no_bars_uses_sample(client):
    """200 with sample data when bars not provided (falls back to _make_sample_vwap_bars)."""
    vwap_result = MagicMock()
    vwap_result.model_dump.return_value = {"vwap": [22000.0]}
    with patch(
        "flinttrade_indicators.vwap_bands.calculate_vwap_bands",
        return_value=vwap_result,
    ):
        resp = client.post("/v1/indicators/vwap", json={})
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
            "/v1/analytics/pairs",
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
    resp = client.post("/v1/analytics/pairs", json={})
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
            "/v1/analytics/mtf",
            json={
                "symbol": "NIFTY",
                "data": {"1h": _BARS, "4h": _BARS},
            },
        )
    assert resp.status_code == 200


def test_mtf_sample_data(client):
    """200 or 400 when no data provided."""
    resp = client.post("/v1/analytics/mtf", json={})
    assert resp.status_code in {200, 400}


# ---------------------------------------------------------------------------
# POST /ft-api/v1/analytics/seasonality
# ---------------------------------------------------------------------------


def _seasonality_bars(years: int = 3) -> list[dict]:
    """Deterministic weekday daily bars spanning ``years`` calendar years."""
    from datetime import date, timedelta

    start = date(2023, 1, 2)
    end = date(2023 + years - 1, 12, 29)
    bars: list[dict] = []
    close = 20_000.0
    day = start
    i = 0
    while day <= end:
        if day.weekday() < 5:
            # Deterministic drift with a sign wobble so returns are non-constant.
            close *= 1.0 + (0.002 if i % 3 else -0.001)
            bars.append({"timestamp": day.isoformat(), "close": round(close, 2)})
            i += 1
        day += timedelta(days=1)
    return bars


@pytest.mark.unit
def test_seasonality_ok(client):
    """200 with monthly/weekday/day-of-month stats and the year × month matrix."""
    resp = client.post(
        "/v1/analytics/seasonality",
        json={"symbol": "NIFTY", "exchange": "NSE_INDEX", "bars": _seasonality_bars()},
    )
    assert resp.status_code == 200
    body = resp.get_json()
    assert body["status"] == "success"
    data = body["data"]
    assert data["symbol"] == "NIFTY"
    assert data["exchange"] == "NSE_INDEX"
    assert data["is_sample_data"] is False

    # Three full years → every calendar month has at least one complete return.
    months = [row["month"] for row in data["monthly"]]
    assert len(months) == len(set(months))
    assert len(months) == 12
    first = data["monthly"][0]
    for key in (
        "month_name", "avg_return_pct", "median_return_pct", "std_pct",
        "positive_rate", "years_count", "best_year", "worst_year",
    ):
        assert key in first
    assert len(first["best_year"]) == 2  # (year, return_pct)

    # Weekday: Monday–Friday only.
    weekdays = [row["weekday"] for row in data["weekday"]]
    assert weekdays == sorted(weekdays)
    assert all(0 <= wd <= 4 for wd in weekdays)

    # Day-of-month rows are sorted and within 1–31.
    days = [row["day"] for row in data["day_of_month"]]
    assert days == sorted(days)
    assert all(1 <= day <= 31 for day in days)

    # Matrix: one row per year, always 12 month columns, NaN → null.
    matrix = data["matrix"]
    assert matrix["months"] == list(range(1, 13))
    assert len(matrix["returns"]) == len(matrix["years"])
    assert all(len(row) == 12 for row in matrix["returns"])


@pytest.mark.unit
def test_seasonality_no_bars_uses_sample(client):
    """200 with the deterministic sample series when bars are absent — flagged."""
    resp = client.post("/v1/analytics/seasonality", json={"symbol": "BANKNIFTY"})
    assert resp.status_code == 200
    data = resp.get_json()["data"]
    assert data["is_sample_data"] is True
    assert data["symbol"] == "BANKNIFTY"
    assert len(data["monthly"]) == 12
    assert len(data["weekday"]) == 5


@pytest.mark.unit
def test_seasonality_epoch_timestamps(client):
    """Bars with epoch-second and epoch-millisecond stamps both parse."""
    from datetime import date, timedelta, datetime, timezone

    bars = []
    day = date(2024, 1, 1)
    close = 100.0
    i = 0
    while day <= date(2025, 12, 31):
        if day.weekday() < 5:
            close *= 1.0 + (0.001 if i % 2 else -0.0005)
            epoch = int(datetime(day.year, day.month, day.day, tzinfo=timezone.utc).timestamp())
            # Alternate seconds and milliseconds to pin the unit heuristic.
            bars.append({"time": epoch * 1000 if i % 2 else epoch, "close": round(close, 4)})
            i += 1
        day += timedelta(days=1)

    resp = client.post("/v1/analytics/seasonality", json={"bars": bars})
    assert resp.status_code == 200
    data = resp.get_json()["data"]
    assert data["matrix"]["years"] == [2024, 2025]


@pytest.mark.unit
def test_seasonality_bars_not_a_list(client):
    """400 when bars is not a list."""
    resp = client.post("/v1/analytics/seasonality", json={"bars": {"close": 1}})
    assert resp.status_code == 400
    assert resp.get_json()["status"] == "error"


@pytest.mark.unit
def test_seasonality_unparseable_bars(client):
    """400 when no bar has a usable close + timestamp."""
    resp = client.post(
        "/v1/analytics/seasonality",
        json={"bars": [{"close": "not-a-number", "timestamp": "2024-01-01"}, {"open": 1}]},
    )
    assert resp.status_code == 400
    assert "usable bars" in resp.get_json()["message"]


@pytest.mark.unit
def test_seasonality_series_too_short(client):
    """422 when the series is too short for any seasonality statistic."""
    resp = client.post(
        "/v1/analytics/seasonality",
        json={"bars": [{"timestamp": "2024-01-01", "close": 100.0}]},
    )
    assert resp.status_code == 422
    assert "too short" in resp.get_json()["message"]

@pytest.mark.unit
def test_vwap_zero_volume_session_serialises_nan_as_null(client):
    """An all-zero-volume session must yield null band values, never literal NaN."""
    bars = [
        {
            "timestamp": f"2026-01-15T09:{15 + i}:00",
            "high": 100.0 + i,
            "low": 99.0 + i,
            "close": 99.5 + i,
            "volume": 0,
        }
        for i in range(5)
    ]
    response = client.post("/v1/indicators/vwap", json={"bars": bars})
    assert response.status_code == 200
    # The raw body must be valid strict JSON (no bare NaN tokens).
    assert b"NaN" not in response.data
    payload = response.get_json()
    assert payload["status"] == "success"
    assert all(v is None for v in payload["data"]["vwap"])
