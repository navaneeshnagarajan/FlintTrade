"""Tests for packages/engine/src/sandbox_routes.py (Flask Blueprint).

Uses Flask test client with an in-memory SandboxEngine.
"""

from __future__ import annotations

import pytest

duckdb = pytest.importorskip("duckdb", reason="duckdb not installed")

from flask import Flask  # noqa: E402


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture()
def app():
    """Minimal Flask test app with the sandbox blueprint registered."""
    import packages.engine.src.sandbox as _sandbox_mod
    import packages.engine.src.sandbox_routes as _routes_mod

    flask_app = Flask(__name__)
    flask_app.config["TESTING"] = True

    cfg = _sandbox_mod.SandboxConfig(starting_capital=500_000.0)
    engine = _sandbox_mod.SandboxEngine(account_id="route_test", config=cfg, db_path=":memory:")
    flask_app.config["SANDBOX_ENGINE"] = engine

    flask_app.register_blueprint(_routes_mod.sandbox_bp)
    yield flask_app
    engine.close()


@pytest.fixture()
def client(app):
    return app.test_client()


@pytest.fixture()
def app_no_engine():
    """Flask app without a sandbox engine — tests 503 responses."""
    import packages.engine.src.sandbox_routes as _routes_mod

    flask_app = Flask(__name__)
    flask_app.config["TESTING"] = True
    flask_app.register_blueprint(_routes_mod.sandbox_bp)
    return flask_app


@pytest.fixture()
def client_no_engine(app_no_engine):
    return app_no_engine.test_client()


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestSandboxRoutes:
    def test_get_config(self, client):
        resp = client.get("/v1/sandbox-config/config")
        assert resp.status_code == 200
        data = resp.get_json()
        assert data["status"] == "success"
        assert data["config"]["starting_capital"] == 500_000.0

    def test_update_config(self, client):
        resp = client.post(
            "/v1/sandbox-config/config",
            json={"equity_leverage": 5},
        )
        assert resp.status_code == 200
        data = resp.get_json()
        assert data["config"]["equity_leverage"] == 5

    def test_get_funds(self, client):
        resp = client.get("/v1/sandbox-config/funds")
        assert resp.status_code == 200
        data = resp.get_json()
        assert "funds" in data
        assert data["funds"]["starting_capital"] == 500_000.0

    def test_get_positions_empty(self, client):
        resp = client.get("/v1/sandbox-config/positions")
        assert resp.status_code == 200
        assert resp.get_json()["positions"] == []

    def test_get_orders_empty(self, client):
        resp = client.get("/v1/sandbox-config/orders")
        assert resp.status_code == 200
        assert resp.get_json()["orders"] == []

    def test_get_trades_empty(self, client):
        resp = client.get("/v1/sandbox-config/trades")
        assert resp.status_code == 200
        assert resp.get_json()["trades"] == []

    def test_get_pnl_empty(self, client):
        resp = client.get("/v1/sandbox-config/pnl")
        assert resp.status_code == 200
        assert resp.get_json()["pnl_history"] == []

    def test_reset(self, client):
        resp = client.post("/v1/sandbox-config/reset")
        assert resp.status_code == 200
        data = resp.get_json()
        assert data["status"] == "success"
        assert data["starting_capital"] == 500_000.0

    def test_no_engine_returns_503(self, client_no_engine):
        resp = client_no_engine.get("/v1/sandbox-config/funds")
        assert resp.status_code == 503
