"""Tests for packages/core/data/src/questdb_routes.py — QuestDB tick storage endpoints."""

from __future__ import annotations

import logging
from unittest.mock import MagicMock

import pytest
from flask import Flask

import flinttrade_data.questdb_routes as mod
from flinttrade_data.questdb_config import QuestDBWritesDisabledError
from flinttrade_data.questdb_routes import WRITES_DISABLED_MESSAGE


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


def _mock_bridge() -> MagicMock:
    bridge = MagicMock()
    bridge.check_health.return_value = True
    bridge.insert_ticks.return_value = 3
    bridge.query.return_value = [{"symbol": "NIFTY", "ltp": 22500.0}]
    bridge.aggregate_ohlcv.return_value = [{"open": 22000.0, "high": 22500.0, "low": 21900.0, "close": 22400.0}]
    bridge.get_latest_tick.return_value = {"symbol": "NIFTY", "ltp": 22500.0}
    return bridge


@pytest.fixture()
def app():
    flask_app = Flask(__name__)
    flask_app.config["TESTING"] = True
    mod.init_questdb_routes(_mock_bridge())
    flask_app.register_blueprint(mod.questdb_bp)
    return flask_app


@pytest.fixture()
def client(app):
    return app.test_client()


# ---------------------------------------------------------------------------
# GET /api/v1/data/questdb/health
# ---------------------------------------------------------------------------


def test_health_ok(client):
    """200 when QuestDB is reachable."""
    resp = client.get("/api/v1/data/questdb/health")
    assert resp.status_code == 200
    assert resp.get_json()["data"]["running"] is True


def test_health_down():
    """503 when QuestDB is down."""
    flask_app = Flask(__name__)
    flask_app.config["TESTING"] = True
    bridge = _mock_bridge()
    bridge.check_health.return_value = False
    mod.init_questdb_routes(bridge)
    flask_app.register_blueprint(mod.questdb_bp)
    with flask_app.test_client() as c:
        resp = c.get("/api/v1/data/questdb/health")
    assert resp.status_code == 503


# ---------------------------------------------------------------------------
# POST /api/v1/data/questdb/ticks
# ---------------------------------------------------------------------------


def test_insert_ticks_ok(client):
    """200 with inserted count."""
    ticks = [{"symbol": "NIFTY", "exchange": "NSE_INDEX", "ltp": 22500.0}] * 3
    resp = client.post("/api/v1/data/questdb/ticks", json={"ticks": ticks})
    assert resp.status_code == 200
    assert resp.get_json()["data"]["inserted"] == 3


def test_insert_ticks_empty(client):
    """400 when ticks list is empty."""
    resp = client.post("/api/v1/data/questdb/ticks", json={"ticks": []})
    assert resp.status_code == 400


def test_insert_ticks_not_list(client):
    """400 when ticks is not a list."""
    resp = client.post("/api/v1/data/questdb/ticks", json={"ticks": "bad"})
    assert resp.status_code == 400


def test_insert_ticks_writes_disabled_hides_exception_text(app, caplog):
    """403 with a fixed message; exception text stays server side."""
    bridge = _mock_bridge()
    exc = QuestDBWritesDisabledError("insert_ticks")
    leak = str(exc)
    bridge.insert_ticks.side_effect = exc
    mod.init_questdb_routes(bridge)
    with caplog.at_level(logging.WARNING, logger="flinttrade.data.questdb_routes"):
        with app.test_client() as client:
            resp = client.post(
                "/api/v1/data/questdb/ticks",
                json={"ticks": [{"symbol": "NIFTY", "exchange": "NFO", "ltp": 1.0}]},
            )
    body = resp.get_json()
    assert resp.status_code == 403
    assert body["message"] == WRITES_DISABLED_MESSAGE
    raw = resp.get_data(as_text=True) or ""
    assert leak not in raw
    assert leak in caplog.text


# ---------------------------------------------------------------------------
# POST /api/v1/data/questdb/query
# ---------------------------------------------------------------------------


def test_query_ok(client):
    """200 with rows."""
    resp = client.post(
        "/api/v1/data/questdb/query",
        json={"sql": "SELECT * FROM ticks LIMIT 1"},
    )
    assert resp.status_code == 200
    assert "rows" in resp.get_json()["data"]


def test_query_empty_sql(client):
    """400 when sql is absent."""
    resp = client.post("/api/v1/data/questdb/query", json={})
    assert resp.status_code == 400


def test_query_writes_disabled_hides_exception_text(app, caplog):
    """403 with a fixed message; exception text stays server side."""
    bridge = _mock_bridge()
    exc = QuestDBWritesDisabledError("query")
    leak = str(exc)
    bridge.query.side_effect = exc
    mod.init_questdb_routes(bridge)
    with caplog.at_level(logging.WARNING, logger="flinttrade.data.questdb_routes"):
        with app.test_client() as client:
            resp = client.post(
                "/api/v1/data/questdb/query",
                json={"sql": "INSERT INTO ticks VALUES (1)"},
            )
    body = resp.get_json()
    assert resp.status_code == 403
    assert body["message"] == WRITES_DISABLED_MESSAGE
    raw = resp.get_data(as_text=True) or ""
    assert leak not in raw
    assert leak in caplog.text


# ---------------------------------------------------------------------------
# POST /api/v1/data/questdb/ohlcv
# ---------------------------------------------------------------------------


def test_ohlcv_ok(client):
    """200 with bars."""
    resp = client.post(
        "/api/v1/data/questdb/ohlcv",
        json={
            "symbol": "NIFTY",
            "interval": "5m",
            "start": "2026-04-01T09:15:00",
            "end": "2026-04-01T15:30:00",
        },
    )
    assert resp.status_code == 200
    assert "bars" in resp.get_json()["data"]


def test_ohlcv_missing_fields(client):
    """400 when required fields absent."""
    resp = client.post("/api/v1/data/questdb/ohlcv", json={"symbol": "NIFTY"})
    assert resp.status_code == 400


# ---------------------------------------------------------------------------
# GET /api/v1/data/questdb/tick/latest/<symbol>
# ---------------------------------------------------------------------------


def test_latest_tick_ok(client):
    """200 with tick data."""
    resp = client.get("/api/v1/data/questdb/tick/latest/NIFTY")
    assert resp.status_code == 200
    assert resp.get_json()["data"]["symbol"] == "NIFTY"


def test_latest_tick_not_found(app):
    """404 when no ticks stored for symbol."""
    bridge = _mock_bridge()
    bridge.get_latest_tick.return_value = None
    mod.init_questdb_routes(bridge)
    with app.test_client() as c:
        resp = c.get("/api/v1/data/questdb/tick/latest/UNKNOWN")
    assert resp.status_code == 404
