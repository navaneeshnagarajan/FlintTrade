"""Tests for packages/integrations/gateway/src/rotation_routes.py — credential rotation admin."""

from __future__ import annotations

from datetime import datetime
from unittest.mock import MagicMock

import pytest
from flask import Flask

from flinttrade_gateway.rotation_routes import create_rotation_blueprint


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


def _mock_rotator(success: bool = True) -> MagicMock:
    rotator = MagicMock()
    rotator.rotation_status.return_value = [
        {"broker": "broker1", "next_rotation": "2026-04-20T08:00:00"}
    ]

    result = MagicMock()
    result.success = success
    result.broker = "broker1"
    result.rotated_at = datetime(2026, 4, 19, 8, 0, 0)
    result.rotation_type = "daily"
    result.error = None if success else "Invalid credentials"

    rotator.rotate_now.return_value = result
    return rotator


@pytest.fixture()
def app():
    flask_app = Flask(__name__)
    flask_app.config["TESTING"] = True
    bp = create_rotation_blueprint(_mock_rotator(success=True))
    flask_app.register_blueprint(bp)
    return flask_app


@pytest.fixture()
def client(app):
    return app.test_client()


# ---------------------------------------------------------------------------
# GET /admin/credentials/rotation/status
# ---------------------------------------------------------------------------


def test_status_ok(client):
    """200 with brokers list."""
    resp = client.get("/admin/credentials/rotation/status")
    assert resp.status_code == 200
    body = resp.get_json()
    assert body["status"] == "ok"
    assert isinstance(body["brokers"], list)
    assert body["brokers"][0]["broker"] == "broker1"


# ---------------------------------------------------------------------------
# POST /admin/credentials/rotation/<broker>/schedule
# ---------------------------------------------------------------------------


def test_schedule_daily(client):
    """200 for daily rotation schedule."""
    resp = client.post(
        "/admin/credentials/rotation/broker1/schedule",
        json={"interval": "daily", "time_ist": "08:00"},
    )
    assert resp.status_code == 200
    assert resp.get_json()["status"] == "ok"
    assert "Daily" in resp.get_json()["message"] or "daily" in resp.get_json()["message"].lower()


def test_schedule_weekly(client):
    """200 for weekly rotation schedule."""
    resp = client.post(
        "/admin/credentials/rotation/broker1/schedule",
        json={"interval": "weekly", "time_ist": "08:00", "day": 0},
    )
    assert resp.status_code == 200
    assert resp.get_json()["status"] == "ok"


def test_schedule_error():
    """400 when rotator raises ValueError."""
    rotator = _mock_rotator()
    rotator.schedule_daily_refresh.side_effect = ValueError("Bad time format")
    flask_app = Flask(__name__)
    flask_app.config["TESTING"] = True
    flask_app.register_blueprint(create_rotation_blueprint(rotator))
    with flask_app.test_client() as c:
        resp = c.post(
            "/admin/credentials/rotation/broker1/schedule",
            json={"interval": "daily", "time_ist": "bad"},
        )
    assert resp.status_code == 400


# ---------------------------------------------------------------------------
# POST /admin/credentials/rotation/<broker>/rotate-now
# ---------------------------------------------------------------------------


def test_rotate_now_ok(client):
    """200 on successful immediate rotation."""
    resp = client.post("/admin/credentials/rotation/broker1/rotate-now")
    assert resp.status_code == 200
    body = resp.get_json()
    assert body["success"] is True
    assert "rotated_at" in body


def test_rotate_now_failure():
    """500 on rotation failure."""
    flask_app = Flask(__name__)
    flask_app.config["TESTING"] = True
    flask_app.register_blueprint(
        create_rotation_blueprint(_mock_rotator(success=False))
    )
    with flask_app.test_client() as c:
        resp = c.post("/admin/credentials/rotation/broker1/rotate-now")
    assert resp.status_code == 500
    assert resp.get_json()["success"] is False
