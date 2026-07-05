"""Tests for the ChartPreferences Flask route."""

from __future__ import annotations

from collections.abc import Iterator
from typing import Any

import pytest
from flask import Flask
from flask.testing import FlaskClient

from flinttrade_core.chart_prefs import ChartPreferences
from flinttrade_core.chart_prefs_routes import (
    chart_prefs_bp,
    init_chart_prefs_routes,
)


@pytest.fixture()
def client(tmp_path: Any) -> Iterator[FlaskClient]:
    """Serve the chart preferences blueprint against an isolated DuckDB file."""
    prefs = ChartPreferences(db_path=str(tmp_path / "chart_prefs.duckdb"))
    init_chart_prefs_routes(prefs)
    app = Flask(__name__)
    app.register_blueprint(chart_prefs_bp)
    yield app.test_client()
    prefs.close()


def test_get_chart_preferences_returns_empty_payload(client: FlaskClient) -> None:
    response = client.get("/api/v1/chart")

    assert response.status_code == 200
    assert response.get_json() == {
        "status": "success",
        "data": {
            "user_id": "default",
            "theme": {},
            "indicator_sets": {},
            "layouts": {},
            "layout": {},
        },
    }


def test_post_chart_preferences_persists_theme_indicators_and_layout(client: FlaskClient) -> None:
    payload = {
        "theme": {"background": "#0a0a0f", "upColor": "#22c55e"},
        "indicator_sets": {"scalping": [{"name": "EMA", "params": {"period": 9}}]},
        "layout": {"panels": [{"id": "chart1", "type": "chart"}]},
    }

    response = client.post("/api/v1/chart", json=payload, headers={"X-User-Id": "alice"})

    assert response.status_code == 200
    data = response.get_json()["data"]
    assert data["user_id"] == "alice"
    assert data["theme"] == payload["theme"]
    assert data["indicator_sets"] == payload["indicator_sets"]
    assert data["layouts"]["default"] == payload["layout"]
    assert data["layout"] == payload["layout"]

    follow_up = client.get("/api/v1/chart", headers={"X-User-Id": "alice"})
    assert follow_up.get_json()["data"] == data


def test_post_unrecognised_object_keeps_legacy_default_layout(client: FlaskClient) -> None:
    response = client.post("/api/v1/chart", json={"symbol": "NIFTY", "interval": "5m"})

    assert response.status_code == 200
    data = response.get_json()["data"]
    assert data["layout"] == {"symbol": "NIFTY", "interval": "5m"}
    assert data["layouts"]["default"] == {"symbol": "NIFTY", "interval": "5m"}


def test_post_chart_preferences_validates_indicator_sets(client: FlaskClient) -> None:
    response = client.post("/api/v1/chart", json={"indicator_sets": {"bad": {"name": "EMA"}}})

    assert response.status_code == 400
    assert response.get_json()["message"] == "indicator_sets.bad must be an array of objects"
