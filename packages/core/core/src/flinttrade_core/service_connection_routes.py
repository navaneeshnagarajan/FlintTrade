"""Authenticated, non-invoking service-connection HTTP control plane."""

from __future__ import annotations

import hmac
import logging
import os
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from flask import Blueprint, Response, current_app, g, jsonify, request

from .auth_routes import (
    VerifiedOperatorSession,
    _OperatorSessionVerificationError,
    verify_operator_session_token,
)
from .service_connection_audit import ConnectionActorContext, ConnectionMutationAudit, RouteMutationAttempt
from .service_connection_etags import parse_single_strong_entity_tag
from .service_connection_store import (
    ConnectionIdempotencyConflict,
    ConnectionMutationRejected,
    ConnectionMutationResult,
    ConnectionRevisionConflict,
    ConnectionRevisionRequired,
    ConnectionStoreUnavailable,
    ServiceConnectionStore,
)
from .service_connection_transactions import MAX_MUTATION_BYTES, uuid_text

SERVICE_CONNECTION_COLLECTION_PATH = "/v1/services/connections"
SERVICE_CONNECTION_COLLECTION_TEMPLATE = "/ft-api/v1/services/connections"
SERVICE_CONNECTION_ITEM_TEMPLATE = "/ft-api/v1/services/connections/{connection_id}"

service_connection_bp = Blueprint(
    "service_connections",
    __name__,
    url_prefix=SERVICE_CONNECTION_COLLECTION_PATH,
)
logger = logging.getLogger("flinttrade.service_connections")


@dataclass(frozen=True, slots=True)
class _ConnectionProof:
    authentication_class: str
    principal: VerifiedOperatorSession | None = None


def _is_service_connection_path(path: object) -> bool:
    return type(path) is str and (
        path == SERVICE_CONNECTION_COLLECTION_PATH or path.startswith(SERVICE_CONNECTION_COLLECTION_PATH + "/")
    )


def _response(error: str, status: int) -> tuple[Response, int]:
    return jsonify({"error": error}), status


def _trusted_peer() -> str:
    original = request.environ.get("werkzeug.proxy_fix.orig")
    if isinstance(original, dict) and type(original.get("REMOTE_ADDR")) is str:
        return original["REMOTE_ADDR"]
    return request.environ.get("REMOTE_ADDR", "")


def _is_loopback_peer() -> bool:
    return _trusted_peer() in {"127.0.0.1", "::1", "localhost"}


def _selected_read_key() -> str:
    return os.environ.get("FLINTTRADE_API_KEY", "") or os.environ.get("OPENALGO_API_KEY", "")


def _scope_for_method(method: str) -> str:
    return "admin.services.read" if method in {"GET", "HEAD"} else "admin.services.write"


def _proof_matches(candidate: str, expected: str) -> bool:
    try:
        return hmac.compare_digest(candidate, expected)
    except TypeError:
        return False


def _authenticate_connection_request() -> tuple[_ConnectionProof | None, tuple[Response, int] | None]:
    method = request.method
    scope = _scope_for_method(method)
    authorization = request.headers.get("Authorization", "")
    selected_token = request.headers.get("X-FlintTrade-Token", "").strip()
    selected_key = request.headers.get("X-API-Key", "").strip()
    source = "missing"
    candidate = ""
    if authorization.strip():
        source = "authorization"
        candidate = authorization.removeprefix("Bearer ").strip()
    elif selected_token:
        source = "session"
        candidate = selected_token
    elif selected_key:
        source = "api_key"
        candidate = selected_key

    if source in {"authorization", "session"}:
        try:
            principal = verify_operator_session_token(candidate)
        except _OperatorSessionVerificationError as error:
            expected = _selected_read_key()
            if (
                source == "authorization"
                and error.reason == "invalid"
                and method in {"GET", "HEAD"}
                and expected
                and _proof_matches(candidate, expected)
            ):
                return _ConnectionProof("authenticated"), None
            return _ConnectionProof("invalid"), _response("authentication_required", 401)
        if scope not in principal.scopes:
            return _ConnectionProof("authenticated", principal), _response("forbidden", 403)
        return _ConnectionProof("authenticated", principal), None

    if source == "api_key":
        expected = _selected_read_key()
        if not expected or not _proof_matches(candidate, expected):
            return _ConnectionProof("invalid"), _response("authentication_required", 401)
        proof = _ConnectionProof("authenticated")
        if scope != "admin.services.read":
            return proof, _response("forbidden", 403)
        return proof, None
    return _ConnectionProof("anonymous"), _response("authentication_required", 401)


def build_connection_audit_sink(
    audit_logger: object,
) -> Callable[[ConnectionMutationAudit], None] | None:
    """Return the exact-acknowledgement domain sink, or no sink if unsupported."""
    log = getattr(audit_logger, "log_idempotent_event", None)
    if not callable(log):
        return None

    def sink(event: ConnectionMutationAudit) -> None:
        fields = event.to_dict()
        event_id = fields.pop("event_id")
        acknowledgement = log("SERVICE_CONNECTION_MUTATION", event_id=event_id, fields=fields)
        if acknowledgement != event_id:
            raise RuntimeError("service-connection audit acknowledgement mismatch")

    return sink


def _route_template() -> str:
    return (
        SERVICE_CONNECTION_COLLECTION_TEMPLATE
        if request.path == SERVICE_CONNECTION_COLLECTION_PATH
        else SERVICE_CONNECTION_ITEM_TEMPLATE
    )


def _record_attempt(outcome: str, proof: _ConnectionProof | None) -> None:
    if request.method not in {"POST", "PATCH", "DELETE"}:
        return
    actor = proof.principal.actor_ref if proof is not None and proof.principal is not None else None
    authentication_class = proof.authentication_class if proof is not None else "invalid"
    try:
        attempt = RouteMutationAttempt(
            _route_template(),
            request.method,
            authentication_class,
            outcome,
            actor=actor,
        )
        audit = current_app.config.get("AUDIT_LOGGER")
        log = getattr(audit, "log_event", None)
        if not callable(log):
            raise RuntimeError("audit logger unavailable")
        log(
            "SERVICE_CONNECTION_ROUTE_ATTEMPT",
            route_template=attempt.route_template,
            method=attempt.method,
            authentication_class=attempt.authentication_class,
            outcome=attempt.outcome,
            actor=attempt.actor,
            connection_ref=None,
        )
    except Exception:
        logger.warning("Service-connection route-attempt audit unavailable")


def guard_service_connection_family() -> tuple[Response, int] | None:
    """Authenticate the entire family before Flask route dispatch."""
    if not _is_service_connection_path(request.path):
        return None
    g.service_connection_guard_complete = True
    if request.method == "OPTIONS":
        return None
    if not _is_loopback_peer():
        has_carrier = any(
            request.headers.get(name, "").strip()
            for name in ("Authorization", "X-FlintTrade-Token", "X-API-Key")
        )
        proof = _ConnectionProof("invalid" if has_carrier else "anonymous")
        _record_attempt("rejected", proof)
        return _response("forbidden", 403)
    proof, denial = _authenticate_connection_request()
    g.service_connection_proof = proof
    if denial is not None:
        _record_attempt("rejected", proof)
    return denial


def apply_service_connection_cache_policy(response: Response) -> Response:
    """Prevent storage of every matched, malformed or rejected family response."""
    if _is_service_connection_path(request.path):
        response.headers["Cache-Control"] = "no-store"
        response.headers["Pragma"] = "no-cache"
    return response


def _store() -> ServiceConnectionStore:
    store = current_app.config.get("SERVICE_CONNECTION_STORE")
    if store is None:
        factory = current_app.config.get("SERVICE_CONNECTION_STORE_FACTORY")
        if not callable(factory):
            raise ConnectionStoreUnavailable("service_connection_store_unavailable")
        lock = current_app.config.get("SERVICE_CONNECTION_STORE_LOCK")
        if lock is None:
            store = factory()
            current_app.config["SERVICE_CONNECTION_STORE"] = store
        else:
            with lock:
                store = current_app.config.get("SERVICE_CONNECTION_STORE")
                if store is None:
                    store = factory()
                    current_app.config["SERVICE_CONNECTION_STORE"] = store
    return store


def _validated_json_body(*, require_empty: bool = False) -> tuple[dict[str, object] | None, tuple[Response, int] | None]:
    length = request.content_length
    if type(length) is int and length > MAX_MUTATION_BYTES:
        return None, _response("request_too_large", 413)
    if not request.is_json:
        return None, _response("unsupported_media_type", 415)
    raw = request.get_data(cache=True)
    if len(raw) > MAX_MUTATION_BYTES:
        return None, _response("request_too_large", 413)
    try:
        payload = request.get_json(silent=False)
    except Exception:
        return None, _response("invalid_request", 400)
    if type(payload) is not dict or (require_empty and payload):
        return None, _response("invalid_request", 400)
    return payload, None


def _preconditions() -> tuple[tuple[str, str] | None, tuple[Response, int] | None]:
    revision = request.headers.get("If-Match")
    if revision is None:
        return None, _response("connection_revision_required", 428)
    try:
        revision = parse_single_strong_entity_tag(revision)
        key = str(uuid_text(request.headers.get("Idempotency-Key")))
    except (TypeError, ValueError):
        return None, _response("invalid_request", 400)
    return (revision, key), None


def _mutation_response(result: ConnectionMutationResult) -> Response:
    public = result.to_dict()
    response = jsonify(public["body"])
    response.status_code = result.status
    response.headers["ETag"] = result.etag
    return response


def _mutate(operation: str, connection_id: str | None) -> tuple[Response, int] | Response:
    proof = getattr(g, "service_connection_proof", None)

    def reject(denial: tuple[Response, int], *, failed: bool = False) -> tuple[Response, int]:
        _record_attempt("failed" if failed else "rejected", proof)
        return denial

    if connection_id is not None:
        try:
            connection_id = str(uuid_text(connection_id))
        except (TypeError, ValueError):
            return reject(_response("invalid_request", 400))
    payload, denial = _validated_json_body(require_empty=operation == "delete")
    if denial is not None:
        return reject(denial)
    preconditions, denial = _preconditions()
    if denial is not None:
        return reject(denial)
    principal = proof.principal if type(proof) is _ConnectionProof else None
    if type(principal) is not VerifiedOperatorSession:
        return reject(_response("forbidden", 403))
    try:
        actor_context = ConnectionActorContext(principal.actor_ref, principal.session_binding)
        result = _store().mutate(
            operation,
            payload,
            connection_id=connection_id,
            expected_etag=preconditions[0],
            idempotency_key=preconditions[1],
            actor_context=actor_context,
        )
    except ConnectionRevisionRequired:
        return reject(_response("connection_revision_required", 428))
    except ConnectionRevisionConflict:
        return reject(_response("connection_revision_conflict", 412))
    except ConnectionIdempotencyConflict:
        return reject(_response("connection_idempotency_conflict", 409))
    except ConnectionMutationRejected as error:
        status, code = {
            "invalid_request": (400, "invalid_request"),
            "not_found": (404, "connection_not_found"),
            "connection_limit": (409, "connection_limit_reached"),
        }[error.reason]
        return reject(_response(code, status))
    except Exception:
        return reject(_response("service_connection_store_unavailable", 503), failed=True)
    return _mutation_response(result)


@service_connection_bp.get("")
def list_service_connections() -> tuple[Response, int] | Response:
    """Return the complete redacted inert connection collection."""
    try:
        snapshot = _store().read_snapshot()
    except Exception:
        return _response("service_connection_store_unavailable", 503)
    response = jsonify({"connections": [connection.to_public_dict() for connection in snapshot.connections]})
    response.headers["ETag"] = snapshot.etag
    return response


@service_connection_bp.post("")
def create_service_connection_route() -> tuple[Response, int] | Response:
    """Persist one inert configuration without invoking its provider."""
    return _mutate("create", None)


@service_connection_bp.get("/<connection_id>")
def get_service_connection(connection_id: str) -> tuple[Response, int] | Response:
    """Return one redacted inert connection by canonical UUID4."""
    try:
        identifier = uuid_text(connection_id)
    except (TypeError, ValueError):
        return _response("invalid_request", 400)
    try:
        snapshot = _store().read_snapshot()
    except Exception:
        return _response("service_connection_store_unavailable", 503)
    connection = next((item for item in snapshot.connections if item.connection_id == identifier), None)
    if connection is None:
        return _response("connection_not_found", 404)
    response = jsonify(connection.to_public_dict())
    response.headers["ETag"] = snapshot.etag
    return response


@service_connection_bp.patch("/<connection_id>")
def update_service_connection_route(connection_id: str) -> tuple[Response, int] | Response:
    """Update one inert configuration using collection concurrency."""
    return _mutate("update", connection_id)


@service_connection_bp.delete("/<connection_id>")
def delete_service_connection_route(connection_id: str) -> tuple[Response, int] | Response:
    """Delete one inert configuration using collection concurrency."""
    return _mutate("delete", connection_id)


def install_service_connection_rate_limits(app: Any) -> int:
    """Install one shared mutation limit after blueprint registration."""
    limiter = app.config.get("LIMITER")
    if limiter is None:
        raise RuntimeError("service-connection rate limiter is unavailable")

    def on_breach(_limit: object) -> Response:
        response = jsonify({"error": "rate_limit_exceeded"})
        response.status_code = 429
        return response

    endpoints = (
        "service_connections.create_service_connection_route",
        "service_connections.update_service_connection_route",
        "service_connections.delete_service_connection_route",
    )
    for endpoint in endpoints:
        app.view_functions[endpoint] = limiter.shared_limit(
            "10 per minute",
            scope="service-connection-mutations",
            key_func=_trusted_peer,
            on_breach=on_breach,
            override_defaults=False,
        )(app.view_functions[endpoint])
    return len(endpoints)
