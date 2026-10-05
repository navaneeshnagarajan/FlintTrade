"""Practice HTTP failures expose local refusals, never dependency exception text."""

from __future__ import annotations

import json
from types import SimpleNamespace

import pytest
from flask import Flask

from flinttrade_core import practice_agent_runtime as runtime

pytestmark = pytest.mark.unit

_CANARY = "synthetic-private-path/practice.sqlite synthetic-provider-secret-canary"
_ROUTES = (
    ("POST", "/start", "start", "Practice agent dependencies or durable evidence are unavailable"),
    ("POST", "/stop", "stop", "Stop was requested but durable status is unavailable"),
    ("GET", "/status", "snapshot", "Practice agent status is unavailable"),
    ("GET", "/runs", "history", "Practice run history is unavailable"),
    ("GET", "/runs/example/events", "events", "Practice run evidence is unavailable"),
    ("POST", "/runs/example/resolve", "resolve", "Practice reconciliation could not be verified"),
)


@pytest.fixture
def endpoint(monkeypatch):
    app = Flask(__name__)
    app.config.update(
        TESTING=True,
        TIME_SCHEDULER=SimpleNamespace(
            get_market_session=lambda: None,
            now_ist=lambda: None,
        ),
    )
    for path, method, function in (
        ("/start", "POST", runtime.start_practice_agent),
        ("/stop", "POST", runtime.stop_practice_agent),
        ("/status", "GET", runtime.practice_agent_status),
        ("/runs", "GET", runtime.list_practice_runs),
        ("/runs/<run_id>/events", "GET", runtime.practice_run_events),
        ("/runs/<run_id>/resolve", "POST", runtime.resolve_practice_run),
    ):
        app.add_url_rule(path, view_func=function, methods=[method])
    supervisor = SimpleNamespace(
        start=lambda *_args: {},
        stop=lambda *_args: {},
        snapshot=lambda *_args: {},
        history=lambda *_args, **_kwargs: [],
        owned_run=lambda *_args: {"snapshot": {}},
        resolve=lambda *_args: {"snapshot": {}},
        store=SimpleNamespace(events=lambda *_args, **_kwargs: []),
    )
    monkeypatch.setattr(runtime, "_authorise", lambda: ("synthetic-session", "synthetic-operator", None))
    monkeypatch.setattr(runtime, "_enabled", lambda: True)
    monkeypatch.setattr(runtime, "get_practice_supervisor", lambda _app: supervisor)
    return app.test_client(), supervisor


def _raise(error):
    def fail(*_args, **_kwargs):
        raise error

    return fail


def _request(client, method, path):
    kwargs = {"json": {"symbols": ["RELIANCE"]}} if path == "/start" else {}
    return client.open(path, method=method, **kwargs)


@pytest.mark.parametrize("method,path,target,message", _ROUTES)
@pytest.mark.parametrize(
    "error", [ValueError(_CANARY), RuntimeError(_CANARY), KeyError(_CANARY), json.JSONDecodeError(_CANARY, _CANARY, 0)]
)
@pytest.mark.parametrize("initialisation", [False, True], ids=["operation", "initialisation"])
def test_dependency_errors_never_reach_http_responses(
    endpoint, monkeypatch, method, path, target, message, error, initialisation
):
    client, supervisor = endpoint
    if initialisation:
        monkeypatch.setattr(runtime, "get_practice_supervisor", _raise(error))
    else:
        monkeypatch.setattr(supervisor.store if target == "events" else supervisor, target, _raise(error))
    response = _request(client, method, path)
    assert _CANARY not in response.get_data(as_text=True)
    assert response.status_code == 503
    assert response.get_json() == {"status": "error", "message": message}


@pytest.mark.parametrize("error", [ValueError(_CANARY), RuntimeError(_CANARY)])
def test_event_ownership_lookup_errors_are_private(endpoint, monkeypatch, error):
    client, supervisor = endpoint
    monkeypatch.setattr(supervisor, "owned_run", _raise(error))
    response = client.get("/runs/example/events")
    assert response.status_code == 503
    assert response.get_json() == {"status": "error", "message": "Practice run evidence is unavailable"}


@pytest.mark.parametrize(
    "url,message",
    [
        ("/runs?limit=0", "limit must be an integer between 1 and 100"),
        ("/runs?limit=secret-canary", "limit must be an integer between 1 and 100"),
        ("/runs/example/events?after=-1", "after must be an integer between 0 and 2147483647"),
        ("/runs/example/events?limit=1001", "limit must be an integer between 1 and 1000"),
    ],
)
def test_invalid_query_retains_actionable_local_message(endpoint, url, message):
    client, _supervisor = endpoint
    response = client.get(url)
    assert response.status_code == 400
    assert response.get_json() == {"status": "error", "message": message}


@pytest.mark.parametrize(
    "body,message",
    [
        ({}, "symbols must be a list containing 1 to 20 instrument names"),
        ({"symbols": ["RELIANCE"], "mode": "live"}, "Practice execution mode cannot be changed"),
        ({"symbols": ["RELIANCE"], "model_call_limit": 0}, "model_call_limit must be an integer between 1 and 10000"),
        ({"symbols": ["RELIANCE"], "daily_stop_loss": 0}, "daily_stop_loss must be negative"),
    ],
)
def test_invalid_config_retains_actionable_local_message(endpoint, body, message):
    client, _supervisor = endpoint
    response = client.post("/start", json=body)
    assert response.status_code == 400
    assert response.get_json() == {"status": "error", "message": message}


@pytest.mark.parametrize(
    "path,target,error,message",
    [
        ("/start", "start", RuntimeError("The application is shutting down"), "The application is shutting down"),
        (
            "/start",
            "start",
            RuntimeError("A Practice agent worker is still owned; stop it first"),
            "A Practice agent worker is still owned; stop it first",
        ),
        (
            "/start",
            "start",
            RuntimeError("Practice positions and pending orders must be flat before starting"),
            "Practice positions and pending orders must be flat before starting",
        ),
        (
            "/start",
            "start",
            RuntimeError("The preceding Practice worker requires reconciliation"),
            "A Practice run is active or requires reconciliation",
        ),
        (
            "/start",
            "start",
            RuntimeError("an active run or unresolved interruption already exists"),
            "A Practice run is active or requires reconciliation",
        ),
        (
            "/runs/example/resolve",
            "resolve",
            RuntimeError("The worker has not finished; reconciliation cannot release it"),
            "The worker has not finished; reconciliation cannot release it",
        ),
        (
            "/runs/example/resolve",
            "resolve",
            RuntimeError("Practice resources have not closed; reconciliation cannot release them"),
            "Practice resources have not closed; reconciliation cannot release them",
        ),
        (
            "/runs/example/resolve",
            "resolve",
            RuntimeError("Only a run requiring reconciliation can be resolved"),
            "Only a run requiring reconciliation can be resolved",
        ),
        (
            "/runs/example/resolve",
            "resolve",
            RuntimeError("Practice positions or pending orders remain; inspect the sandbox before resolving"),
            "Practice positions or pending orders remain; inspect the sandbox before resolving",
        ),
    ],
)
def test_source_owned_conflicts_keep_safe_message_and_status(endpoint, monkeypatch, path, target, error, message):
    client, supervisor = endpoint
    monkeypatch.setattr(supervisor, target, _raise(error))
    response = _request(client, "POST", path)
    assert response.status_code == 409
    assert response.get_json() == {"status": "error", "message": message}


def test_missing_run_keeps_not_found(endpoint, monkeypatch):
    client, supervisor = endpoint
    monkeypatch.setattr(supervisor, "resolve", _raise(KeyError("example")))
    response = client.post("/runs/example/resolve")
    assert response.status_code == 404
    assert response.get_json() == {"status": "error", "message": "Practice run not found"}


def test_initialisation_key_error_matching_run_id_is_not_mistaken_for_missing_run(endpoint, monkeypatch):
    client, _supervisor = endpoint
    monkeypatch.setattr(runtime, "get_practice_supervisor", _raise(KeyError("example")))
    response = client.post("/runs/example/resolve")
    assert response.status_code == 503
    assert response.get_json() == {"status": "error", "message": "Practice reconciliation could not be verified"}


@pytest.mark.parametrize("path,target", [("/runs/example/events", "owned_run"), ("/runs/example/resolve", "resolve")])
@pytest.mark.parametrize(
    "message",
    [
        "run identifiers and event kinds must be bounded identifier text",
        "credential material is not permitted in run evidence",
    ],
)
def test_invalid_run_identifier_keeps_safe_validation_response(endpoint, monkeypatch, path, target, message):
    client, supervisor = endpoint
    monkeypatch.setattr(supervisor, target, _raise(ValueError(message)))
    response = _request(client, "POST" if target == "resolve" else "GET", path)
    assert response.status_code == 400
    assert response.get_json() == {"status": "error", "message": message}


@pytest.mark.parametrize("error", [ValueError(_CANARY), RuntimeError(_CANARY)])
def test_unexpected_config_validation_failure_is_private(endpoint, monkeypatch, error):
    client, _supervisor = endpoint
    monkeypatch.setattr(runtime, "validate_practice_config", _raise(error))
    response = _request(client, "POST", "/start")
    assert response.status_code == 503
    assert response.get_json() == {
        "status": "error",
        "message": "Practice agent dependencies or durable evidence are unavailable",
    }


def test_local_conflict_returns_canonical_text_without_stringifying_exception(endpoint, monkeypatch):
    class DependencyError(RuntimeError):
        def __str__(self):
            return _CANARY

    client, supervisor = endpoint
    message = "Only a run requiring reconciliation can be resolved"
    monkeypatch.setattr(supervisor, "resolve", _raise(DependencyError(message)))
    response = client.post("/runs/example/resolve")
    assert response.status_code == 409
    assert response.get_json() == {"status": "error", "message": message}
