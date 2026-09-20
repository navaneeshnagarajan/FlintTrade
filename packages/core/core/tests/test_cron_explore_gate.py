"""Explore schedule pause/resume fail-closed (FT-AUTO-004)."""

from __future__ import annotations

from typing import Any

import pytest
from flask import Flask
from flask.testing import FlaskClient

from flinttrade_core.operations_routes import (
    _EXPLORE_SCHEDULE_WRITE_BLOCKED,
    _explore_schedule_write_blocked,
    cron_job_pause,
    cron_job_resume,
)

pytestmark = pytest.mark.unit


class _FakeCron:
    def __init__(self) -> None:
        self.pause_calls: list[str] = []
        self.resume_calls: list[str] = []
        self._jobs = {"health_check_job": object()}

    def pause(self, name: str) -> None:
        self.pause_calls.append(name)

    def resume(self, name: str) -> None:
        self.resume_calls.append(name)


@pytest.fixture()
def flask_app() -> Flask:
    app = Flask(__name__)
    app.add_url_rule(
        "/api/v1/cron/jobs/<name>/pause",
        view_func=cron_job_pause,
        methods=["POST"],
    )
    app.add_url_rule(
        "/api/v1/cron/jobs/<name>/resume",
        view_func=cron_job_resume,
        methods=["POST"],
    )
    app.config["CRON"] = _FakeCron()
    return app


@pytest.fixture()
def client(flask_app: Flask) -> FlaskClient:
    return flask_app.test_client()


def test_explore_helper_blocks_jwt_claim(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("flinttrade_engine.mode_guard.current_mode", lambda: "explore")
    app = Flask(__name__)
    with app.test_request_context():
        blocked = _explore_schedule_write_blocked()
        assert blocked is not None
        response, status = blocked
        assert status == 403
        body = response.get_json()
        assert body["status"] == "error"
        assert body["code"] == "mode_blocked"
        assert body["message"] == _EXPLORE_SCHEDULE_WRITE_BLOCKED


def test_explore_helper_blocks_mode_header(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("flinttrade_engine.mode_guard.current_mode", lambda: None)
    app = Flask(__name__)
    with app.test_request_context(headers={"X-FlintTrade-Mode": "explore"}):
        blocked = _explore_schedule_write_blocked()
        assert blocked is not None
        _response, status = blocked
        assert status == 403


def test_explore_helper_allows_practice(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("flinttrade_engine.mode_guard.current_mode", lambda: "practice")
    app = Flask(__name__)
    with app.test_request_context():
        assert _explore_schedule_write_blocked() is None


@pytest.mark.parametrize("path,attr", [
    ("/api/v1/cron/jobs/health_check_job/pause", "pause_calls"),
    ("/api/v1/cron/jobs/health_check_job/resume", "resume_calls"),
])
def test_explore_header_blocks_schedule_write(
    client: FlaskClient,
    flask_app: Flask,
    path: str,
    attr: str,
) -> None:
    response = client.post(path, headers={"X-FlintTrade-Mode": "explore"})
    assert response.status_code == 403
    body: dict[str, Any] = response.get_json()
    assert body["code"] == "mode_blocked"
    assert body["message"] == _EXPLORE_SCHEDULE_WRITE_BLOCKED
    cron: _FakeCron = flask_app.config["CRON"]
    assert getattr(cron, attr) == []


@pytest.mark.parametrize("path,attr", [
    ("/api/v1/cron/jobs/health_check_job/pause", "pause_calls"),
    ("/api/v1/cron/jobs/health_check_job/resume", "resume_calls"),
])
def test_practice_header_allows_schedule_write(
    client: FlaskClient,
    flask_app: Flask,
    path: str,
    attr: str,
) -> None:
    response = client.post(path, headers={"X-FlintTrade-Mode": "practice"})
    assert response.status_code == 200
    cron: _FakeCron = flask_app.config["CRON"]
    assert getattr(cron, attr) == ["health_check_job"]
