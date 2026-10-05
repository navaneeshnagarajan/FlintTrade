"""Public agent controls dispatch Practice to its isolated runtime."""

import sys
from types import SimpleNamespace

import pytest
from flask import Flask, jsonify

from flinttrade_core import agent_routes, order_routes


@pytest.fixture
def controls(monkeypatch):
    called = []

    def handler(name):
        def respond(*args):
            called.append((name, args))
            return jsonify({"status": "success", "data": {"mode": "practice", "operation": name}}), 200

        return respond

    runtime = SimpleNamespace(
        **{
            name: handler(name)
            for name in (
                "start_practice_agent",
                "stop_practice_agent",
                "practice_agent_status",
                "list_practice_runs",
                "practice_run_events",
                "resolve_practice_run",
            )
        }
    )
    runtime.shutdown_practice_agent = lambda app, timeout: called.append(("shutdown", ())) or True
    monkeypatch.setitem(sys.modules, "flinttrade_core.practice_agent_runtime", runtime)
    monkeypatch.setattr(order_routes, "_decode_request_payload", lambda: {"mode": "practice"})
    monkeypatch.setattr(agent_routes, "_agent_flag_enabled", lambda: True)
    app = Flask(__name__)
    app.register_blueprint(agent_routes.agent_bp)
    return app, called


@pytest.mark.parametrize(
    ("method", "path", "operation"),
    [
        ("post", "/start", "start_practice_agent"),
        ("post", "/stop", "stop_practice_agent"),
        ("get", "/status", "practice_agent_status"),
        ("get", "/practice/runs", "list_practice_runs"),
        ("get", "/practice/runs/run-1/events", "practice_run_events"),
        ("post", "/practice/runs/run-1/resolve", "resolve_practice_run"),
    ],
)
def test_public_practice_control_is_routed(controls, method, path, operation):
    app, called = controls
    response = getattr(app.test_client(), method)("/api/v1/ai/agent" + path, json={})
    assert response.status_code == 200
    assert response.get_json()["data"]["operation"] == operation
    assert called[0][0] == operation


def test_shutdown_owns_practice_even_without_a_legacy_live_runner(controls):
    app, called = controls
    agent_routes._reset_runner_for_tests()
    assert agent_routes.shutdown_agent_runtime(app, timeout=1)
    assert ("shutdown", ()) in called
