"""Tests for packages/engine/src/hot_reload_routes.py — strategy hot-reload admin routes."""

from __future__ import annotations

import io
from unittest.mock import MagicMock

import pytest
from flask import Flask

import packages.engine.src.hot_reload_routes as mod


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


def _mock_reloader(tmp_path) -> MagicMock:
    reloader = MagicMock()
    reloader.discover.return_value = ["ema_crossover", "momentum_scalper"]
    reloader.reload.return_value = (True, "Strategy 'ema_crossover' reloaded successfully")
    reloader.validate.return_value = (True, [])
    reloader._dir = tmp_path
    return reloader


@pytest.fixture()
def app(tmp_path):
    flask_app = Flask(__name__)
    flask_app.config["TESTING"] = True
    flask_app.config["HOT_RELOADER"] = _mock_reloader(tmp_path)
    flask_app.register_blueprint(mod.hot_reload_bp)
    return flask_app


@pytest.fixture()
def app_no_reloader():
    flask_app = Flask(__name__)
    flask_app.config["TESTING"] = True
    flask_app.register_blueprint(mod.hot_reload_bp)
    return flask_app


@pytest.fixture()
def client(app):
    return app.test_client()


# ---------------------------------------------------------------------------
# GET /admin/strategies/discovered
# ---------------------------------------------------------------------------


def test_discovered_ok(client):
    """200 with strategy list."""
    resp = client.get("/admin/strategies/discovered")
    assert resp.status_code == 200
    body = resp.get_json()
    assert body["status"] == "ok"
    assert body["count"] == 2
    assert "ema_crossover" in body["strategies"]


def test_discovered_no_reloader(app_no_reloader):
    """503 when HOT_RELOADER not configured."""
    with app_no_reloader.test_client() as c:
        resp = c.get("/admin/strategies/discovered")
    assert resp.status_code == 503


# ---------------------------------------------------------------------------
# POST /admin/strategies/<name>/reload
# ---------------------------------------------------------------------------


def test_reload_ok(client):
    """200 on successful reload."""
    resp = client.post("/admin/strategies/ema_crossover/reload")
    assert resp.status_code == 200
    assert resp.get_json()["status"] == "ok"


def test_reload_invalid_name(client):
    """400 when name contains invalid characters."""
    resp = client.post("/admin/strategies/bad-name!/reload")
    assert resp.status_code == 400


def test_reload_failure(app):
    """422 when reload reports failure."""
    app.config["HOT_RELOADER"].reload.return_value = (
        False, "Strategy not found"
    )
    with app.test_client() as c:
        resp = c.post("/admin/strategies/missing_strat/reload")
    assert resp.status_code == 422


# ---------------------------------------------------------------------------
# POST /admin/strategies/upload
# ---------------------------------------------------------------------------

_SAFE_CODE = "class Strategy:\n    def on_tick(self, ltp): pass\n"


def test_upload_ok(client, tmp_path):
    """201 on valid strategy upload."""
    data = {
        "file": (io.BytesIO(_SAFE_CODE.encode()), "my_strategy.py"),
        "name": "my_strategy",
    }
    resp = client.post(
        "/admin/strategies/upload",
        data=data,
        content_type="multipart/form-data",
    )
    assert resp.status_code == 201
    assert resp.get_json()["name"] == "my_strategy"


def test_upload_no_file(client):
    """400 when file field absent."""
    resp = client.post(
        "/admin/strategies/upload",
        data={"name": "test"},
        content_type="multipart/form-data",
    )
    assert resp.status_code == 400


def test_upload_validation_failure(app):
    """422 when AST validation fails."""
    app.config["HOT_RELOADER"].validate.return_value = (
        False, ["Missing Strategy class"]
    )
    data = {
        "file": (io.BytesIO(b"x = 1\n"), "bad_strategy.py"),
    }
    with app.test_client() as c:
        resp = c.post(
            "/admin/strategies/upload",
            data=data,
            content_type="multipart/form-data",
        )
    assert resp.status_code == 422


# ---------------------------------------------------------------------------
# DELETE /admin/strategies/<name>
# ---------------------------------------------------------------------------


def test_delete_ok(app, tmp_path):
    """200 on successful delete."""
    strategy_file = tmp_path / "ema_crossover.py"
    strategy_file.write_text(_SAFE_CODE, encoding="utf-8")

    with app.test_client() as c:
        resp = c.delete("/admin/strategies/ema_crossover")
    assert resp.status_code == 200
    assert resp.get_json()["status"] == "ok"


def test_delete_not_found(client):
    """404 when strategy file does not exist."""
    resp = client.delete("/admin/strategies/nonexistent_strat")
    assert resp.status_code == 404
