"""Authenticated discovery for installed shared data; no broker activation."""
from __future__ import annotations

import json
import os
from typing import Any

from flask import Blueprint, current_app, jsonify, request

from flinttrade_core.auth_scopes import _session_token
from flinttrade_core.data_runtime import DataSessionRequired

data_runtime_bp = Blueprint("data_runtime", __name__)


def _family() -> bool:
    return (request.path == "/api/v1/data" or request.path.startswith("/api/v1/data/")
            or request.path.startswith("/v1/historify/"))


def _guard() -> Any:
    if not _family():
        return None
    runtime = current_app.config["DATA_RUNTIME"]
    try:
        token = _session_token()
        if not token:
            return jsonify(status="error", code="operator_session_required"), 401
        runtime.principal(token)
        if request.method in {"POST", "PUT", "PATCH", "DELETE"}:
            # Session cookies must not turn cross-origin requests into mutations.
            origin = request.headers.get("Origin")
            allowed = set(os.environ.get("CORS_ORIGINS", "http://127.0.0.1:5173").split(",")) - {"*", "null", ""}
            allowed.add(request.host_url.rstrip("/"))
            if ((origin is not None and origin not in allowed)
                    or request.headers.get("Sec-Fetch-Site") == "cross-site"):
                return jsonify(status="error", code="origin_forbidden"), 403
            if request.path != "/api/v1/data/leases" and not request.path.startswith("/api/v1/data/leases/"):
                if not runtime.evidence_write_allowed():
                    raise PermissionError
            if request.path.startswith("/api/v1/data/") and request.method == "POST":
                def unique(pairs):
                    result = dict(pairs)
                    if len(result) != len(pairs):
                        raise ValueError("duplicate JSON field")
                    return result
                def invalid_constant(_value):
                    raise ValueError("nonfinite JSON")
                try:
                    json.loads(request.get_data(), object_pairs_hook=unique, parse_constant=invalid_constant)
                except (ValueError, TypeError):
                    return jsonify(status="error", code="invalid_data_request"), 400
    except DataSessionRequired:
        return jsonify(status="error", code="operator_session_required"), 401
    except PermissionError:
        return jsonify(status="error", code="data_scope_unavailable"), 403
    except RuntimeError:
        return jsonify(status="unavailable", code="data_runtime_unavailable"), 503
    return None


def _no_store(response: Any) -> Any:
    if _family():
        response.headers["Cache-Control"] = "no-store"
    return response


@data_runtime_bp.get("/api/v1/data/datasets")
def datasets() -> Any:
    """Return exact current-scope datasets and honest native unavailable labels."""
    try:
        return jsonify(status="success", data=current_app.config["DATA_RUNTIME"].datasets())
    except PermissionError:
        return jsonify(status="error", code="data_scope_unavailable"), 403
    except Exception:
        return jsonify(status="unavailable", code="history_store_unavailable"), 503


def install_data_routes(app: Any) -> None:
    """Mount once, sharing existing local-history/lease/evidence route implementations."""
    app.before_request(_guard)
    app.after_request(_no_store)
    app.register_blueprint(data_runtime_bp)
