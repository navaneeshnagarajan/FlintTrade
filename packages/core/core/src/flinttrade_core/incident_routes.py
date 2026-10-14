"""Scoped incident reads and explicit opt-in/cancellation; no repairs or purge."""
from __future__ import annotations

from typing import Any

from flask import Blueprint, Response, current_app, jsonify, request
from flask.typing import ResponseReturnValue

from .auth_scopes import _session_token, require_scope
from .incident_delivery import binding_digest, configured_binding
from .system_incidents import IncidentAuthorityChanged, IncidentConflict, IncidentTimeline, IncidentUnavailable

incident_bp = Blueprint("system_incidents", __name__, url_prefix="/api/v1/system/incidents")


def owner() -> IncidentTimeline:
    value = current_app.config.get("SYSTEM_INCIDENTS")
    if value is None:
        raise IncidentUnavailable("incident_owner_not_bound")
    return value


def scoped_read(value: dict[str, Any], scope: str = "admin.health.read") -> ResponseReturnValue:
    # Recheck after the final potentially blocking store read. Do not return
    # evidence to a session revoked while that read was in progress.
    @require_scope(scope)
    def finish():
        response = jsonify(value)
        response.headers["Cache-Control"] = "no-store"
        return response
    return finish()


@incident_bp.errorhandler(IncidentAuthorityChanged)
def authority_changed(error: IncidentAuthorityChanged) -> tuple[Response, int]:
    return jsonify({"error": "incident_authority_changed"}), error.status


@incident_bp.errorhandler(IncidentConflict)
def conflict(error: IncidentConflict) -> tuple[Response, int]:
    return jsonify({"error": str(error)}), 409


@incident_bp.errorhandler(IncidentUnavailable)
def unavailable(error: IncidentUnavailable) -> tuple[Response, int]:
    return jsonify({"error": "incident_storage_unavailable"}), 503


@incident_bp.errorhandler(ValueError)
def invalid(error: ValueError) -> tuple[Response, int]:
    return jsonify({"error": "invalid_incident_request"}), 400


@incident_bp.get("")
@require_scope("admin.health.read")
def timeline() -> ResponseReturnValue:
    return scoped_read(owner().snapshot(limit=int(request.args.get("limit", "50")),
                                       before=int(request.args["before"]) if "before" in request.args else None))


@incident_bp.get("/deliveries/<delivery>")
@require_scope("admin.health.read")
def read_delivery(delivery: str) -> ResponseReturnValue:
    return scoped_read(owner().delivery(delivery))


@incident_bp.put("/channels/<channel>")
@require_scope("admin.services.write")
def configure_channel(channel: str) -> ResponseReturnValue:
    value = request.get_json()
    if type(value) is not dict or type(value.get("enabled")) is not bool:
        raise ValueError("explicit enablement required")
    expected = {"enabled", "recipient", "provider"} if value["enabled"] else {"enabled"}
    if set(value) != expected:
        raise ValueError("unexpected configuration fields")
    binding = configured_binding(current_app._get_current_object(), channel, value["provider"], value["recipient"]) if value["enabled"] else None
    @require_scope("admin.services.write")
    def permitted() -> None:
        return None

    def check() -> None:
        refusal = permitted()
        if refusal is not None:
            raise IncidentAuthorityChanged(refusal[1])

    return scoped_read(owner().configure(channel, enabled=value["enabled"], binding=binding,
                                         authority_check=check), "admin.services.write")


@incident_bp.get("/channels/<channel>")
@require_scope("admin.services.read")
def read_channel(channel: str) -> ResponseReturnValue:
    return scoped_read(owner().channel(channel), "admin.services.read")


@incident_bp.post("/deliveries/<delivery>/<action>")
@require_scope("admin.observability.run")
def change_delivery(delivery: str, action: str) -> ResponseReturnValue:
    reader = binding_digest(("browser-reader", _session_token() or request.headers.get("X-API-Key", "")))
    if action == "claim":
        return scoped_read(owner().claim_browser(delivery, reader), "admin.observability.run")
    if action == "receipt":
        value = request.get_json()
        if type(value) is not dict or set(value) != {"claim", "state"}:
            raise ValueError("exact browser receipt required")
        return scoped_read(owner().browser_receipt(delivery, reader, value["claim"], value["state"]), "admin.observability.run")
    return scoped_read(owner().delivery_action(delivery, action), "admin.observability.run")
