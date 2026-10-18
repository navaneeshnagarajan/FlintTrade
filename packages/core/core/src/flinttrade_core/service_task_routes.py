"""Task routes mounted on the existing authenticated service blueprint."""

from __future__ import annotations

from functools import partial
from typing import Any

from flask import Blueprint, Response, current_app, g, jsonify, request

from .service_task_dispatch import ServiceTaskDispatcher, TaskRefused
from .service_usage import ServiceUsageLedger, UsageConflict, UsageUnavailable


def get_service_task_dispatcher() -> ServiceTaskDispatcher:
    """Return the current app's single lazy dispatcher for trusted composition."""
    owner = current_app.config.get("SERVICE_TASK_DISPATCHER")
    if owner is None:
        from .service_connection_routes import _store

        lock = current_app.config["SERVICE_CONNECTION_STORE_LOCK"]
        store = _store()
        with lock:
            owner = current_app.config.get("SERVICE_TASK_DISPATCHER")
            if owner is None:
                clock = current_app.config.get("SERVICE_TASK_CLOCK")
                incidents = current_app.config.get("SYSTEM_INCIDENTS")
                ledger = ServiceUsageLedger(
                    store.workspace_dir / "service-usage", clock=clock,
                    failure_sink=partial(incidents.observe_failure, source="model_task") if incidents else None,
                )
                owner = ServiceTaskDispatcher(
                    store,
                    ledger,
                    clock=clock,
                    transport=current_app.config.get("SERVICE_TASK_TRANSPORT"),
                    context_resolver=current_app.config.get("SERVICE_TASK_CONTEXT_RESOLVER"),
                )
                current_app.config["SERVICE_TASK_DISPATCHER"] = owner
    return owner


# Existing internal consumers share the same getter during the integration cutover.
_dispatcher = get_service_task_dispatcher


def _revision() -> int:
    value = request.headers.get("If-Match")
    if value is None:
        raise TaskRefused("revision_required", 428)
    if len(value) < 3 or value[0] != '"' or value[-1] != '"' or not value[1:-1].isdigit():
        raise ValueError("revision must be a quoted integer")
    return int(value[1:-1])


def _route(operation: str, identifier: str | None = None) -> tuple[Response, int] | Response:
    from .service_connection_routes import _validated_json_body

    proof = getattr(g, "service_connection_proof", None)
    principal = getattr(proof, "principal", None)
    if principal is None:
        return jsonify({"error": "forbidden"}), 403
    try:
        payload = None
        if request.method in {"POST", "PUT"}:
            payload, error = _validated_json_body()
            if error:
                return error
        owner = _dispatcher()
        if operation == "admission":
            result = (
                owner.configure(identifier, payload, _revision())
                if payload is not None
                else owner.admission(identifier)
            )
        elif operation == "quota":
            if payload is not None:
                revision = owner.configure_group(identifier, payload, _revision())
                result = {"revision": revision, "policy": owner.ledger.control("quota:" + identifier)[1]}
            else:
                revision, value = owner.ledger.control("quota:" + identifier)
                result = {"revision": revision, "policy": value}
        elif operation == "routing":
            if payload is not None:
                result = owner.configure_routing(payload, _revision())
            else:
                revision, value = owner.ledger.control("routing")
                result = {"revision": revision, "policy": value}
        elif operation == "dispatch":
            from .service_oauth_routes import checked_authority

            oauth_actor, authority_check = checked_authority()
            result = owner.dispatch(
                payload, actor=principal.actor_ref, oauth_actor=oauth_actor, authority_check=authority_check
            )
        else:
            result = owner.ledger.task_receipt(identifier, principal.actor_ref)
        response = jsonify(result)
        if "revision" in result:
            response.headers["ETag"] = f'"{result["revision"]}"'
        return response
    except TaskRefused as error:
        return jsonify({"error": error.code}), error.status
    except UsageConflict:
        return jsonify({"error": "revision_conflict"}), 412
    except KeyError:
        return jsonify({"error": "not_found"}), 404
    except (ValueError, TypeError):
        return jsonify({"error": "invalid_request"}), 400
    except UsageUnavailable:
        return jsonify({"error": "accounting_unavailable"}), 503


def install_task_routes(blueprint: Blueprint) -> None:
    """Reuse the family's loopback, session, scope and no-store guards."""

    def admission(connection_id: str) -> Any:
        return _route("admission", connection_id)

    def quota(group_id: str) -> Any:
        return _route("quota", group_id)

    def dispatch() -> Any:
        return _route("dispatch")

    def receipt(request_id: str) -> Any:
        return _route("receipt", request_id)

    blueprint.add_url_rule("/<connection_id>/admission", "task_admission", admission, methods=["GET", "PUT"])
    blueprint.add_url_rule("/quota-groups/<group_id>", "task_quota", quota, methods=["GET", "PUT"])
    blueprint.add_url_rule("/task-routing", "task_routing", lambda: _route("routing"), methods=["GET", "PUT"])
    blueprint.add_url_rule("/tasks", "task_dispatch", dispatch, methods=["POST"])
    blueprint.add_url_rule("/tasks/<request_id>", "task_receipt", receipt, methods=["GET"])
