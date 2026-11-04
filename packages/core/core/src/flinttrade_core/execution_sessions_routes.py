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
        return jsonify(status="error", code=exc.public_code), 403
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
            raise ValueError("registered Practice strategy unavailable")
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


@execution_sessions_bp.post("/native")
def native_create() -> Any:
    """Configure, never implicitly qualify or authorise native autonomy."""
    from .auth_routes import _session_token_from_request
    owner = get_execution_sessions(current_app._get_current_object()).autonomy
    return jsonify(status="success", data=owner.create(_session_token_from_request(), _body())), 201


@execution_sessions_bp.post("/native-v2")
def native_v2_configure() -> Any:
    """Configure a nominal v2 run without qualifying, granting or starting it.

    Returns:
        The validated cash/options view and HTTP 201; owner refusals use 409.
    """
    from .auth_routes import _session_token_from_request

    owner = get_execution_sessions(current_app._get_current_object()).autonomy.v2
    return jsonify(status="success", data=owner.configure(_session_token_from_request(), _body())), 201


@execution_sessions_bp.get("/<run_id>/autonomy-v2")
def native_v2_status(run_id: str) -> Any:
    """Read local v2 custody without broker, model or qualification side effects.

    Args:
        run_id: Exact durable run selected by the authenticated operator.

    Returns:
        The nominal cash/options view; scope and version conflicts use 409.
    """
    from .auth_routes import _session_token_from_request

    registry = get_execution_sessions(current_app._get_current_object())
    native = registry._native_child()
    if native is None:
        raise ValueError("native custody has not been configured")
    return jsonify(status="success", data=native.v2.status(_session_token_from_request(), run_id))


@execution_sessions_bp.post("/<run_id>/autonomy-v2/inspect")
def native_v2_inspect(run_id: str) -> Any:
    """Run one explicit bounded canonical read plan, never entry qualification.

    Args:
        run_id: Exact configured run bound by the shared InspectRequestV2.

    Returns:
        A cash/options view with the stored report; invalid plans use HTTP 409.
    """
    from .auth_routes import _session_token_from_request

    owner = get_execution_sessions(current_app._get_current_object()).autonomy.v2
    return jsonify(status="success", data=owner.inspect(_session_token_from_request(), run_id, _body()))


@execution_sessions_bp.post("/<run_id>/autonomy-v2/qualify")
def native_v2_qualify(run_id: str) -> Any:
    """Evaluate server-owned evidence only; the request body must be empty.

    Args:
        run_id: Exact existing cash/options run.

    Returns:
        A nominal view with its current report, including honest blocked states.
    """
    from .auth_routes import _session_token_from_request

    if _body():
        raise ValueError("qualification accepts no caller evidence")
    owner = get_execution_sessions(current_app._get_current_object()).autonomy.v2
    return jsonify(status="success", data=owner.qualify(_session_token_from_request(), run_id))


@execution_sessions_bp.post("/<run_id>/autonomy-v2/transfer-preview")
def native_v2_transfer_preview(run_id: str) -> Any:
    """Select finite custody without granting permission or starting work."""
    from .auth_routes import _session_token_from_request

    owner = get_execution_sessions(current_app._get_current_object()).autonomy.v2
    return jsonify(status="success", data=owner.custody.preview(_session_token_from_request(), run_id, _body()))


@execution_sessions_bp.post("/<run_id>/autonomy-v2/transfer-accept")
def native_v2_transfer_accept(run_id: str) -> Any:
    """Record actual receiving acceptance against one exact current preview."""
    from .auth_routes import _session_token_from_request

    owner = get_execution_sessions(current_app._get_current_object()).autonomy.v2
    return jsonify(status="success", data=owner.custody.accept(_session_token_from_request(), run_id, _body()))


@execution_sessions_bp.post("/<run_id>/autonomy-v2/grant")
def native_v2_grant(run_id: str) -> Any:
    """Keep explicit grant refusal distinct from configuration and acceptance."""
    from .auth_routes import _session_token_from_request

    owner = get_execution_sessions(current_app._get_current_object()).autonomy.v2
    return jsonify(status="success", data=owner.grant(_session_token_from_request(), run_id, _body()))


@execution_sessions_bp.post("/<run_id>/autonomy-v2/start")
def native_v2_start(run_id: str) -> Any:
    """Never report running without an actual acquired bounded producer."""
    from .auth_routes import _session_token_from_request

    owner = get_execution_sessions(current_app._get_current_object()).autonomy.v2
    return jsonify(status="success", data=owner.start(_session_token_from_request(), run_id, _body()))


@execution_sessions_bp.get("/<run_id>/autonomy")
def native_status(run_id: str) -> Any:
    """Inspect retained native authority and obligations for the authenticated operator.

    Args:
        run_id: Exact run identifier resolved by the existing execution owner.

    Returns:
        Success envelope containing the owner's current native status.
    """
    from .auth_routes import _session_token_from_request
    owner = get_execution_sessions(current_app._get_current_object()).autonomy
    return jsonify(status="success", data=owner.status(_session_token_from_request(), run_id))


@execution_sessions_bp.post("/<run_id>/autonomy/qualify")
def native_qualify(run_id: str) -> Any:
    """Ask the existing owner to qualify a run using backend-held evidence only.

    Args:
        run_id: Exact run identifier resolved by the existing execution owner.

    Returns:
        Success envelope containing the owner's qualification result.

    Raises:
        ValueError: The caller supplies evidence or the owner rejects the run binding.
    """
    from .auth_routes import _session_token_from_request
    if _body():
        raise ValueError("qualification accepts no caller evidence")
    owner = get_execution_sessions(current_app._get_current_object()).autonomy
    return jsonify(status="success", data=owner.qualify(_session_token_from_request(), run_id))


@execution_sessions_bp.post("/<run_id>/autonomy/grant")
def native_grant(run_id: str) -> Any:
    """Submit the operator's explicit bounded grant to the existing authority owner.

    Args:
        run_id: Exact run identifier resolved by the existing execution owner.

    Returns:
        Success envelope containing the retained grant disposition.

    Raises:
        ValueError: The grant, run scope or current authority is invalid.
    """
    from .auth_routes import _session_token_from_request
    owner = get_execution_sessions(current_app._get_current_object()).autonomy
    return jsonify(status="success", data=owner.grant(_session_token_from_request(), run_id, _body()))


@execution_sessions_bp.post("/<run_id>/autonomy/revoke")
def native_revoke(run_id: str) -> Any:
    """Revoke the exact named grant without claiming its obligations are settled.

    Args:
        run_id: Exact run identifier resolved by the existing execution owner.

    Returns:
        Success envelope containing retained status after revocation.

    Raises:
        ValueError: The body is not an exact grant selector or the owner refuses it.
    """
    from .auth_routes import _session_token_from_request
    body = _body()
    if set(body) != {"grant_id"}:
        raise ValueError("exact grant required")
    owner = get_execution_sessions(current_app._get_current_object()).autonomy
    return jsonify(status="success", data=owner.revoke(_session_token_from_request(), run_id, body["grant_id"]))


@execution_sessions_bp.post("/<run_id>/autonomy/commands")
def native_command(run_id: str) -> Any:
    """Submit a bounded command through the existing native authority owner.

    Args:
        run_id: Exact run identifier resolved by the existing execution owner.

    Returns:
        Success envelope containing the command's actual retained disposition, not proof of a fill.

    Raises:
        ValueError: The mode contradicts native binding or command admission is refused.
    """
    from .auth_routes import _session_token_from_request
    if request.headers.get("X-FlintTrade-Mode") not in {None, "live"}:
        raise ValueError("command mode contradicts immutable native binding")
    owner = get_execution_sessions(current_app._get_current_object()).autonomy
    return jsonify(status="success", data=owner.submit(_session_token_from_request(), run_id, _body()))


@execution_sessions_bp.post("/<run_id>/autonomy/reconcile")
def native_reconcile(run_id: str) -> Any:
    """Reconcile retained obligations from owner-acquired broker observations.

    Args:
        run_id: Exact run identifier resolved by the existing execution owner.

    Returns:
        Success envelope with the owner's reconciliation result; missing evidence remains unresolved.

    Raises:
        ValueError: The caller supplies receipts or the owner rejects reconciliation.
    """
    from .auth_routes import _session_token_from_request
    if _body():
        raise ValueError("reconciliation never accepts caller receipts")
    owner = get_execution_sessions(current_app._get_current_object()).autonomy
    return jsonify(status="success", data=owner.reconcile(_session_token_from_request(), run_id))


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
