"""Exact execution-session HTTP lifecycle, independent of Terminal selection."""
from __future__ import annotations

import os
import threading
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

from flask import Blueprint, current_app, g, jsonify, request

from .execution_session import ExecutionSession
from .execution_sessions import ExecutionSessions
from .model_control_auth import ModelControlDenied, _body, principal

execution_sessions_bp = Blueprint("execution_sessions", __name__, url_prefix="/api/v1/execution-sessions")
_INSTALL_LOCK = threading.RLock()


def get_execution_sessions(app: Any) -> ExecutionSessions:
    """Lazily acquire once, after the real backend lease exists."""
    with _INSTALL_LOCK:
        owner = app.config.get("EXECUTION_SESSIONS")
        if owner is None:
            path = Path(app.config["EXECUTION_SESSIONS_PATH"])
            established = (path / "registry.sqlite").exists()
            owner = ExecutionSessions(app, path)
            app.config["EXECUTION_SESSIONS"] = owner
            if established:
                owner.resume_protection()
        return owner


def resume_execution_protection(app: Any) -> dict[str, Any]:
    """Post-lease startup seam: never manufacture an empty historical owner."""
    with _INSTALL_LOCK:
        path = app.config.get("EXECUTION_SESSIONS_PATH")
        if path is None:
            return {"state": "unavailable", "runs": None}
        path = Path(path)
        marker = path.parent / (".execution-owner-" + path.name + ".json")
        if app.config.get("EXECUTION_SESSIONS") is None:
            if not path.exists() and not marker.exists():
                return {"state": "not_initialised", "runs": []}
            if not marker.exists() or not (path / "registry.sqlite").is_file():
                return {"state": "unavailable", "runs": None}
        try:
            return get_execution_sessions(app).resume_protection()
        except Exception:
            return {"state": "unavailable", "runs": None}


def install_execution_sessions(app: Any, workspace: Path) -> None:
    """Mount without opening files, provider connections or worker threads."""
    if "execution_sessions" not in app.blueprints:
        app.config["EXECUTION_SESSIONS_PATH"] = Path(workspace) / "execution-sessions"
        app.register_blueprint(execution_sessions_bp)


@execution_sessions_bp.before_request
def authorise() -> Any:
    try:
        if request.remote_addr not in {"127.0.0.1", "::1"}:
            raise ModelControlDenied("loopback_required")
        allowed = set(os.environ.get("CORS_ORIGINS", "http://127.0.0.1:5173").split(",")) - {"*", "null", ""}
        if urlsplit(request.host_url).hostname in {"localhost", "127.0.0.1", "::1"}:
            allowed.add(request.host_url.rstrip("/"))
        if request.headers.get("Sec-Fetch-Site") == "cross-site" or (
            request.headers.get("Origin") is not None and request.headers["Origin"] not in allowed
        ):
            raise ModelControlDenied("origin_forbidden")
        who = principal()
        required = "admin.accounts.read" if request.method == "GET" else "admin.accounts.write"
        if required not in who.scopes:
            raise ModelControlDenied("execution_scope_required")
        g.execution_actor = who.actor_ref
    except ModelControlDenied as exc:
        return jsonify(status="error", code=str(exc)), 403
    return None


@execution_sessions_bp.after_request
def no_store(response: Any) -> Any:
    response.headers["Cache-Control"] = "no-store"
    return response


@execution_sessions_bp.errorhandler(ValueError)
def invalid(_exc: ValueError) -> Any:
    return jsonify(status="error", code="execution_scope_or_generation_refused"), 409


@execution_sessions_bp.errorhandler(Exception)
def unavailable(_exc: Exception) -> Any:
    return jsonify(status="unavailable", code="execution_owner_unavailable", message="Read the exact run; never replay an uncertain command."), 503


@execution_sessions_bp.route("", methods=["GET", "POST"])
def sessions() -> Any:
    owner = get_execution_sessions(current_app._get_current_object())
    if request.method == "GET":
        return jsonify(status="success", data=owner.list(g.execution_actor))
    body = _body()
    if set(body) != {"run_id", "kind", "config"}:
        return jsonify(status="error", code="exact_session_fields_required"), 400
    from .practice_agent_runtime import validate_practice_config
    requested = body["config"]
    if body["kind"] == "strategy":
        if type(requested) is not dict or type(requested.get("strategy")) is not str:
            raise ValueError("exact registered strategy required")
        strategy = requested["strategy"]
        if strategy not in current_app.config.get("EXECUTION_STRATEGY_FACTORIES", {}):
            raise ValueError("registered Paper strategy unavailable")
        accepted = {"symbols", "exchange", "product", "max_position_size", "cycle_interval_sec"}
        if set(requested) - accepted - {"strategy"}:
            raise ValueError("unsupported strategy parameters")
        validated = validate_practice_config({key: value for key, value in requested.items() if key != "strategy"})
        config = {**{key: validated[key] for key in accepted}, "strategy": strategy}
    else:
        config = validate_practice_config(requested)
    scope = ExecutionSession(body["run_id"], g.execution_actor, "paper:run:" + body["run_id"], "paper")
    return jsonify(status="success", data=owner.create(scope, kind=body["kind"], config=config)), 201


@execution_sessions_bp.get("/<run_id>")
def status(run_id: str) -> Any:
    owner = get_execution_sessions(current_app._get_current_object())
    return jsonify(status="success", data=owner.status(owner.scope(run_id, g.execution_actor)))


@execution_sessions_bp.post("/<run_id>/<operation>")
def control(run_id: str, operation: str) -> Any:
    from .auth_routes import _session_token_from_request

    if operation not in {"start", "stop", "rearm", "close"}:
        return jsonify(status="error", code="unknown_session_operation"), 404
    body = _body()
    if set(body) != {"account", "environment", "expected_generation"}:
        return jsonify(status="error", code="exact_session_target_required"), 400
    owner = get_execution_sessions(current_app._get_current_object())
    scope = ExecutionSession(run_id, g.execution_actor, body["account"], body["environment"])
    generation = body["expected_generation"]
    if operation == "stop":
        value = owner.stop_entries(scope, expected_generation=generation)
    elif operation == "close":
        value = owner.close_positions(scope, expected_generation=generation)
    else:
        value = owner.start(scope, token=_session_token_from_request(), expected_generation=generation,
                            rearm=operation == "rearm")
    return jsonify(status="success", data=value), 202 if operation in {"start", "close", "rearm"} else 200
