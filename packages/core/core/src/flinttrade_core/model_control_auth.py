"""Strict operator authentication for model control, never generic API-key auth."""
from __future__ import annotations

import json
import os
import re
from typing import Any
from urllib.parse import urlsplit

from flask import current_app, g, jsonify, request


class ModelControlDenied(ValueError):
    """Safe bounded refusal, distinct from provider/credential exceptions."""


def principal() -> Any:
    """Verify the existing full operator session and exact carrier on every call."""
    from .auth_routes import verify_operator_session_token
    from .auth_scopes import _session_token
    if request.headers.get("X-API-Key"):
        raise ModelControlDenied("operator_session_required")
    token = _session_token()
    if not token:
        raise ModelControlDenied("operator_session_required")
    try:
        result = verify_operator_session_token(token)
    except Exception:
        raise ModelControlDenied("operator_session_required") from None
    scope = "admin.services.read" if request.method in {"GET", "HEAD"} else "admin.services.write"
    if scope not in result.scopes:
        raise ModelControlDenied("model_control_scope_required")
    return result


def _body() -> dict[str, Any]:
    if not request.is_json or (request.content_length or 0) > 65536:
        raise ValueError("bounded JSON required")
    def unique(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
        value = dict(pairs)
        if len(value) != len(pairs):
            raise ValueError("duplicate fields")
        return value
    def invalid(value: str) -> None:
        raise ValueError("non-finite JSON")
    raw = request.get_data(cache=True)
    if len(raw) > 65536:
        raise ValueError("bounded JSON required")
    value = json.loads(raw, object_pairs_hook=unique, parse_constant=invalid)
    if type(value) is not dict:
        raise ValueError("object required")
    return value


def guard_model_control() -> Any:
    """Install before the broad API guard; later guards cannot widen rejection."""
    match = re.fullmatch(r"/api/v1/backtest/(adoptions|training/jobs)(?:/([^/]+)(?:/(cancel|reconcile))?)?", request.path)
    evaluation = re.fullmatch(r"/api/v1/backtest/(trials|experiments)/([^/]+)|/api/v1/backtest/evaluation/suites/([^/]+)/score", request.path)
    configuration = request.path.startswith("/v1/model-runs/")
    if match is None and evaluation is None and not configuration:
        return None
    g.model_control_family = True
    try:
        if request.remote_addr not in {"127.0.0.1", "::1"}:
            raise ModelControlDenied("loopback_required")
        origin = request.headers.get("Origin")
        allowed = set(os.environ.get("CORS_ORIGINS", "http://127.0.0.1:5173").split(",")) - {"*", "null", ""}
        if urlsplit(request.host_url).hostname in {"localhost", "127.0.0.1", "::1"}:
            allowed.add(request.host_url.rstrip("/"))
        if request.headers.get("Sec-Fetch-Site") == "cross-site" or origin is not None and origin not in allowed:
            raise ModelControlDenied("origin_forbidden")
        who = principal()
        if configuration:
            g.model_control_actor = who.actor_ref
            return None  # Exact run and one-shot confirmation checked by the route.
        if evaluation is not None:
            family, identity, suite = evaluation.groups()
            if suite is not None:
                if request.method != "POST":
                    raise ModelControlDenied("operation_forbidden")
                body = _body()
                if set(body) != {"trial_id"} or type(body["trial_id"]) is not str:
                    raise ValueError("Exact trial required")
                current_app.config["MODEL_RUN_SERVICES"].authorise_evaluation(
                    who.actor_ref, "score", body["trial_id"], suite=suite)
            elif request.method in {"GET", "HEAD"}:
                current_app.config["MODEL_RUN_SERVICES"].authorise_evaluation(
                    who.actor_ref, "read", identity, experiment=family == "experiments")
            else:
                raise ModelControlDenied("operation_forbidden")
            g.model_control_actor = who.actor_ref
            return None
        family, identity, verb = match.groups()
        kind = "adoption" if family == "adoptions" else "training"
        if request.method == "GET" and identity and verb is None:
            operation, body = "get", {}
        elif request.method == "POST":
            operation = verb or ("adopt" if kind == "adoption" else "start")
            body = _body()
            if identity:
                if body or not verb or (kind == "adoption" and verb != "reconcile"):
                    raise ValueError("no replacement scope")
            elif kind == "adoption":
                required = {"request_id", "run_id", "role", "candidate", "expected_generation"}
                if not required <= body.keys() or body.keys() - required - {"kind"}:
                    raise ValueError("exact fields required")
                if (type(body["expected_generation"]) is not int or body["expected_generation"] < 0
                        or body.get("kind", "adopt") not in {"adopt", "rollback"}
                        or any(type(body[k]) is not str or not re.fullmatch(r"[A-Za-z0-9_.:-]{1,128}", body[k])
                               for k in required - {"expected_generation"})):
                    raise ValueError("invalid adoption identity")
            elif set(body) != {"request_id", "payload", "lineage"} or type(body["payload"]) is not dict or type(body["lineage"]) is not dict:
                raise ValueError("exact training fields required")
        else:
            raise ModelControlDenied("operation_forbidden")
        owner = current_app.config["MODEL_RUN_SERVICES"]
        owner.authorise(who.actor_ref, kind, operation, identity=identity, body=body)
        g.model_control_actor = who.actor_ref
        return None
    except ModelControlDenied as exc:
        return jsonify(status="error", code=str(exc)), 403
    except (ValueError, TypeError, KeyError):
        return jsonify(status="error", code="invalid_model_control"), 400
    except Exception:
        return jsonify(status="unavailable", code="model_control_unavailable"), 503


def model_control_no_store(response: Any) -> Any:
    if getattr(g, "model_control_family", False):
        response.headers["Cache-Control"] = "no-store"
        response.headers["Pragma"] = "no-cache"
    return response
