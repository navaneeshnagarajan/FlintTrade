"""Session-authenticated knowledge and learning-permission HTTP interfaces."""
from __future__ import annotations

import hashlib
import json
import os
import secrets
import time
from dataclasses import asdict, fields
from datetime import datetime
from functools import wraps
from typing import Any
from urllib.parse import urlsplit
from uuid import UUID

from flask import Blueprint, current_app, g, jsonify, request

from flinttrade_core.knowledge_integration import require_knowledge_runtime
from flinttrade_core.service_task_contracts import TaskRefused

knowledge_bp = Blueprint("knowledge", __name__)


def _family() -> bool:
    return any(request.path == root or request.path.startswith(root + "/")
               for root in ("/v1/knowledge", "/v1/learning"))


def _bind_sensitive_family() -> None:
    """Reuse the existing fixed-field redaction context before any rejecting hook."""
    if not _family():
        return
    import structlog

    from flinttrade_core.request_observability import SafeRequestSummary, set_safe_request_summary
    root = "/v1/knowledge" if request.path.startswith("/v1/knowledge") else "/v1/learning"
    summary = SafeRequestSummary(root + "/{resource}", request.method, request.content_length, True)
    g._knowledge_summary_token = set_safe_request_summary(summary)
    structlog.contextvars.clear_contextvars()
    structlog.contextvars.bind_contextvars(**summary.to_dict())


def _clear_sensitive_family(_error: Any) -> None:
    from flinttrade_core.request_observability import reset_safe_request_summary
    token = getattr(g, "_knowledge_summary_token", None)
    if token is not None:
        g._knowledge_summary_token = None
        reset_safe_request_summary(token)


def _guard() -> Any:
    if not _family():
        return None
    from flinttrade_core.service_connection_routes import _authenticate_connection_request, _is_loopback_peer
    # Reuse the stronger family guard and its verified, opaque principal. Never
    # let the general API-key guard reinterpret a rejected session afterwards.
    g.service_connection_guard_complete = True
    if not _is_loopback_peer():
        return jsonify(error="forbidden"), 403
    origin = request.headers.get("Origin")
    allowed = set(os.environ.get("CORS_ORIGINS", "http://127.0.0.1:5173").split(",")) - {"*", "null", ""}
    if urlsplit(request.host_url).hostname in {"localhost", "127.0.0.1", "::1"}:
        allowed.add(request.host_url.rstrip("/"))
    if origin is not None and origin not in allowed:
        return jsonify(error="origin_forbidden"), 403
    if request.headers.get("Sec-Fetch-Site") == "cross-site":
        return jsonify(error="origin_forbidden"), 403
    if request.method == "OPTIONS":
        return None
    proof, denial = _authenticate_connection_request()
    if denial is not None:
        return denial
    if proof.principal is None:
        return jsonify(error="operator_session_required"), 403
    g.knowledge_principal = proof.principal
    return None


def _no_store(response: Any) -> Any:
    if _family():
        response.headers["Cache-Control"] = "no-store"
        response.headers["Pragma"] = "no-cache"
    return response


def _handled(operation: Any) -> Any:
    @wraps(operation)
    def call(*args: Any, **kwargs: Any) -> Any:
        try:
            return jsonify(operation(*args, **kwargs))
        except TaskRefused as error:
            return jsonify(error=error.code), error.status
        except KeyError:
            return jsonify(error="not_found"), 404
        except (ValueError, TypeError):
            return jsonify(error="invalid_request"), 400
        except Exception:
            return jsonify(error="knowledge_unavailable"), 503
    return call


def _body(fields: set[str]) -> dict[str, Any]:
    from flinttrade_core.service_connection_routes import _validated_json_body
    value, denial = _validated_json_body()
    if denial is not None:
        raise TaskRefused(denial[0].get_json()["error"], denial[1])
    def unique(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
        result = dict(pairs)
        if len(result) != len(pairs):
            raise ValueError("duplicate JSON field")
        return result
    def invalid_constant(_value: str) -> Any:
        raise ValueError("non-finite JSON value")
    value = json.loads(request.get_data(), object_pairs_hook=unique, parse_constant=invalid_constant)
    if type(value) is not dict or set(value) != fields:
        raise ValueError("exact fields required")
    return value


def _text(value: Any) -> str:
    if type(value) is not str or not value.strip() or len(value.encode()) > 4096:
        raise ValueError("bounded string required")
    return value


def _runtime() -> Any:
    return require_knowledge_runtime(current_app)


def _version(identifier: str) -> dict[str, Any]:
    return current_app.config["SERVICE_TASK_CONTEXT_RESOLVER"].authorise_version(
        identifier, g.knowledge_principal.actor_ref)


def _assert_response_scope(expected: dict[str, str] | None) -> None:
    scope = current_app.config["SERVICE_TASK_CONTEXT_RESOLVER"].scope(g.knowledge_principal.actor_ref)
    if (asdict(scope) if scope is not None else None) != expected:
        raise TaskRefused("context_changed", 409)


@knowledge_bp.get("/v1/knowledge/skills")
@_handled
def skills() -> dict[str, Any]:
    resolver = current_app.config["SERVICE_TASK_CONTEXT_RESOLVER"]
    scope = resolver.scope(g.knowledge_principal.actor_ref)
    return {"skills": _runtime().skills(scope).catalogue(), "scope": asdict(scope) if scope is not None else None}


@knowledge_bp.get("/v1/knowledge/skills/<name>")
@_handled
def skill(name: str) -> dict[str, Any]:
    resolver = current_app.config["SERVICE_TASK_CONTEXT_RESOLVER"]
    result = resolver.resolve(
        references=("skill:" + name,), actor=g.knowledge_principal.actor_ref, purpose="assistant")[0]
    scope = resolver.context_scope(result)
    _assert_response_scope(scope)
    return {"reference": result.reference, "version": result.version, "body": result.body,
            "classification": result.classification, "receipt": result.receipt, "scope": scope}


@knowledge_bp.get("/v1/knowledge/versions/<identifier>")
@_handled
def version(identifier: str) -> dict[str, Any]:
    value = {"version": identifier, **_version(identifier), "version_id": identifier,
             "rights": _runtime().ledger.get_event(identifier).rights.to_public_dict()}
    _assert_response_scope(value["context_scope"])
    return value


@knowledge_bp.post("/v1/knowledge/versions/<identifier>/retire")
@_handled
def retire(identifier: str) -> dict[str, Any]:
    body = _body({"reason"})
    reason = _text(body["reason"])
    _version(identifier)
    evidence = _runtime().store.retire(identifier, reason=g.knowledge_principal.actor_ref + ": " + reason)
    return {"version": identifier, "state": "retired", "receipt": evidence}


_PERMISSION_FIELDS = {"scope", "recipient", "purpose", "operations", "valid_from", "valid_until", "limits",
                      "max_rows", "max_trials", "retention", "derivatives", "objective", "rights", "supersedes"}


def _object(value: Any, keys: set[str]) -> dict[str, Any]:
    if type(value) is not dict or set(value) != keys:
        raise ValueError("exact object required")
    return value


def _sequence(value: Any) -> tuple[str, ...]:
    if type(value) is not list or not value or len(value) > 256:
        raise ValueError("bounded list required")
    result = tuple(_text(item) for item in value)
    if len(set(result)) != len(result):
        raise ValueError("unique list required")
    return result


def _instant(value: Any) -> datetime:
    from flinttrade_core.service_usage_contracts import utc
    return utc(datetime.fromisoformat(_text(value)))


def _gate() -> Any:
    from flinttrade_core.knowledge_integration import get_learning_consent_ledger
    return get_learning_consent_ledger(current_app._get_current_object())


def _status(identifier: str) -> dict[str, Any]:
    value = _gate().status(identifier)
    if value["grant"]["approver"] != g.knowledge_principal.actor_ref:
        raise TaskRefused("forbidden", 403)
    return value


def _permission(body: dict[str, Any]) -> dict[str, Any]:
    """Validate all JSON types before consulting a trusted canonical authority.

    LEARNING_PERMISSION_RESOLVER(actor, scope, recipient, purpose, operations)
    returns (DatasetScope, Recipient, RightsResolution), or None. It is supplied
    by a qualified canonical dataset/destination owner, never an HTTP payload or
    a model. Boot supplies none: unknown rights or account ownership refuse.
    """
    from flinttrade_core.learning_consent import PURPOSES, DatasetScope, Recipient
    from flinttrade_core.service_connections import ServiceConnectionRef
    from flinttrade_core.service_providers import PermissionState, RightsResolution
    from flinttrade_core.service_usage_contracts import USAGE_DIMENSIONS, canonical, integer
    scope_body = _object(body["scope"], {item.name for item in fields(DatasetScope)})
    scope = DatasetScope(**{key: _sequence(value) if key in {
        "accounts", "environments", "runs", "sources", "fields", "splits"} else
        _instant(value) if key in {"as_of_start", "as_of_end"} else _text(value)
        for key, value in scope_body.items()})
    if not set(scope.environments) <= {"paper", "live", "research"}:
        raise ValueError("unknown environment")
    recipient_body = _object(body["recipient"], {item.name for item in fields(Recipient)})
    connection = _object(recipient_body["connection"], {"provider_id", "connection_id"})
    identity = _text(connection["connection_id"])
    if str(UUID(identity)) != identity:
        raise ValueError("canonical connection required")
    downstream = recipient_body["downstream"]
    if downstream == []:
        downstream = ()
    else:
        downstream = _sequence(downstream)
    recipient = Recipient(**{**{key: _text(value) for key, value in recipient_body.items()
                                if key not in {"connection", "downstream"}},
                             "connection": ServiceConnectionRef(_text(connection["provider_id"]), UUID(identity)),
                             "downstream": downstream})
    purpose = _text(body["purpose"])
    operations = _sequence(body["operations"])
    if purpose not in PURPOSES or operations != (recipient.method,):
        raise ValueError("exact purpose and single recipient operation required")
    if recipient.method in {"publish", "export"}:
        raise ValueError("publication authority not available")
    start, end = _instant(body["valid_from"]), _instant(body["valid_until"])
    if end <= start:
        raise ValueError("empty grant interval")
    limits = _object(body["limits"], set(USAGE_DIMENSIONS))
    for key, value in limits.items():
        integer(value, key)
    integer(body["max_rows"], "max_rows", minimum=1)
    integer(body["max_trials"], "max_trials", minimum=1)
    for key in ("retention", "derivatives", "objective"):
        _text(body[key])
    supersedes = body["supersedes"]
    if supersedes is not None:
        _status(_text(supersedes))
    if type(body["rights"]) is not dict:
        raise ValueError("explicit rights required")
    resolver = current_app.config.get("LEARNING_PERMISSION_RESOLVER")
    if not callable(resolver):
        raise TaskRefused("learning_authority_unavailable", 503)
    authorised = resolver(actor=g.knowledge_principal.actor_ref, scope=scope, recipient=recipient,
                          purpose=purpose, operations=operations)
    if type(authorised) is not tuple or len(authorised) != 3:
        raise TaskRefused("learning_authority_denied", 403)
    resolved_scope, resolved_recipient, rights = authorised
    if (type(resolved_scope) is not DatasetScope or type(resolved_recipient) is not Recipient
        or scope != resolved_scope or recipient != resolved_recipient or type(rights) is not RightsResolution
        or canonical(body["rights"]) != canonical(rights.to_public_dict())
        or any(getattr(rights.rights, key) is not PermissionState.ALLOWED
               for key in ("output_use", "retention", "training_distillation"))):
        raise TaskRefused("learning_rights_unavailable", 403)
    return {"scope": scope, "recipient": recipient, "purpose": purpose, "operations": operations,
            "valid_from": start, "valid_until": end, "limits": limits,
            **{key: body[key] for key in ("max_rows", "max_trials", "retention", "derivatives", "objective", "supersedes")}}


def _confirmation_digest(body: dict[str, Any]) -> str:
    from flinttrade_core.service_usage_contracts import canonical
    principal = g.knowledge_principal
    return hashlib.sha256(canonical([principal.actor_ref, principal.session_binding, body]).encode()).hexdigest()


@knowledge_bp.post("/v1/learning/permissions/preview")
@_handled
def permission_preview() -> dict[str, Any]:
    body = _body(_PERMISSION_FIELDS)
    _permission(body)
    now = time.monotonic()
    token = secrets.token_urlsafe(32)
    with current_app.config["KNOWLEDGE_OWNER_LOCK"]:
        pending = current_app.config.setdefault("LEARNING_CONFIRMATIONS", {})
        for key in list(pending):
            if pending[key][1] <= now:
                del pending[key]
        if len(pending) >= 128:
            raise TaskRefused("confirmation_limit", 429)
        pending[token] = (_confirmation_digest(body), now + 300)
    return {"proposal": body, "confirmation": token, "expires_in_seconds": 300}


@knowledge_bp.post("/v1/learning/permissions/grants")
@_handled
def permission_grant() -> dict[str, Any]:
    body = _body(_PERMISSION_FIELDS | {"confirmation"})
    token = _text(body.pop("confirmation"))
    # Consume the confirmation before the durable grant; a failed/lost request
    # cannot reuse it. Re-preview explicitly rather than silently retrying.
    with current_app.config["KNOWLEDGE_OWNER_LOCK"]:
        item = current_app.config.get("LEARNING_CONFIRMATIONS", {}).pop(token, None)
        if item is None or item[1] <= time.monotonic() or item[0] != _confirmation_digest(body):
            raise TaskRefused("confirmation_required", 409)
        values = _permission(body)  # current authority rechecked, not a queue-time permit
        identity = _gate().grant(**values, approver=g.knowledge_principal.actor_ref,
                                 confirmation=_confirmation_digest(body) + ":" + token)
        return {"grant_id": identity, **_status(identity)}


@knowledge_bp.get("/v1/learning/permissions/grants/<identifier>")
@_handled
def permission_status(identifier: str) -> dict[str, Any]:
    return _status(identifier)


@knowledge_bp.post("/v1/learning/permissions/grants/<identifier>/revoke")
@_handled
def permission_revoke(identifier: str) -> dict[str, Any]:
    _body(set())
    _status(identifier)
    _gate().revoke(identifier, actor=g.knowledge_principal.actor_ref)
    return _status(identifier)


@knowledge_bp.get("/v1/learning/permissions/grants/<identifier>/manifests/<batch_id>")
@_handled
def permission_manifest(identifier: str, batch_id: str) -> dict[str, Any]:
    grant = _status(identifier)["grant"]
    manifest = _gate().manifest(batch_id)
    if manifest["scope_hash"] != grant["scope_hash"]:
        raise TaskRefused("forbidden", 403)
    return manifest


@knowledge_bp.get("/v1/learning/permissions/receipts/<attempt_id>")
@_handled
def permission_receipt(attempt_id: str) -> dict[str, Any]:
    receipt = _gate().receipt(attempt_id)
    _status(receipt["grant_id"])
    return receipt


def install_knowledge_routes(app: Any) -> None:
    """Register with the existing guard order; no independent credential source."""
    app.register_blueprint(knowledge_bp)
    hooks = app.before_request_funcs.setdefault(None, [])
    index = next((i for i, hook in enumerate(hooks) if hook.__name__ == "guard_service_connection_family"), 1)
    hooks.insert(index, _guard)
    binding_index = next((i + 1 for i, hook in enumerate(hooks) if hook.__name__ == "_bind_request_context"), 0)
    hooks.insert(binding_index, _bind_sensitive_family)
    app.teardown_request(_clear_sensitive_family)
    app.after_request(_no_store)
