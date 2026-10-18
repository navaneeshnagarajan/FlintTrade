"""Explicit operator confirmation for bounded protection; never generic API auth."""
from __future__ import annotations

import json
from typing import Any
from urllib.parse import urlsplit

from flask import Blueprint, current_app, jsonify, request

from .practice_agent_adapter import PracticeAgentError

protection_bp = Blueprint("protection", __name__, url_prefix="/api/v1/protection")


def operator() -> tuple[Any, str]:
    """Verify exact full-session authority at each permission mutation."""
    from .auth_routes import decode_token, verify_operator_session_token
    from .auth_scopes import _session_token

    if (request.remote_addr not in {"127.0.0.1", "::1"} or request.headers.get("X-API-Key")
            or request.headers.get("Sec-Fetch-Site") == "cross-site"):
        raise PracticeAgentError("protection_operator_required")
    origin = request.headers.get("Origin")
    allowed = {request.host_url.rstrip("/")} | set(current_app.config.get("PROTECTION_CONTROL_ORIGINS", ()))
    if origin is not None and (origin not in allowed or urlsplit(origin).scheme not in {"http", "https"}):
        raise PracticeAgentError("protection_origin_forbidden")
    try:
        token = _session_token()
        if not token:
            raise ValueError
        who = verify_operator_session_token(token)
        claims = decode_token(token)
        if (claims.get("setup_session") is True
                or not {"admin.accounts.read", "admin.accounts.write"} <= set(who.scopes)):
            raise ValueError
    except Exception:
        raise PracticeAgentError("protection_operator_required") from None
    return who, claims["sub"]


def _body() -> dict[str, Any]:
    def unique(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
        result = dict(pairs)
        if len(result) != len(pairs):
            raise ValueError("Duplicate fields")
        return result

    def invalid(_value: str) -> None:
        raise ValueError("Finite JSON required")

    raw = request.get_data(cache=True)
    if not request.is_json or len(raw) > 65536:
        raise ValueError("Bounded JSON required")
    body = json.loads(raw, object_pairs_hook=unique, parse_constant=invalid)
    if type(body) is not dict:
        raise ValueError("Object required")
    return body


@protection_bp.get("/grants/<run_id>")
def grant_readback(run_id: str) -> Any:
    """Read only the exact existing owner with fresh full-session authority."""
    try:
        who, _ = operator()
        result = current_app.config["PROTECTION_SERVICES"].readback(run_id, who.actor_ref)
        return jsonify(status="success", data=result)
    except PracticeAgentError as exc:
        if exc.code in {"protection_custody_unavailable", "protection_owner_unavailable", "protection_owner_closed"}:
            return jsonify(status="unavailable", code="protection_custody_unavailable"), 503
        return jsonify(status="error", code=exc.code), 403
    except Exception:
        return jsonify(status="unavailable", code="protection_custody_unavailable"), 503


@protection_bp.post("/grants")
def configure_grant() -> Any:
    """Explicitly approve the complete policy for a backend-owned exact run."""
    try:
        operator()
        body = _body()
        if set(body) != {"run_id", "expected_revision", "policy"}:
            raise ValueError("Exact fields required")
        result = current_app.config["PROTECTION_SERVICES"].configure(**body)
        return jsonify(status="success", data=result), 201
    except PracticeAgentError as exc:
        return jsonify(status="error", code=exc.code), 403
    except (ValueError, TypeError, KeyError):
        return jsonify(status="error", code="protection_request_invalid"), 400
    except Exception:
        return jsonify(status="unavailable", code="protection_custody_unavailable"), 503


@protection_bp.after_request
def no_store(response: Any) -> Any:
    response.headers["Cache-Control"] = "no-store"
    return response


@protection_bp.post("/grants/<run_id>/revoke")
def revoke_grant(run_id: str) -> Any:
    """Revoke permission without discarding an unresolved protection obligation."""
    try:
        operator()
        body = _body()
        if set(body) != {"expected_revision"}:
            raise ValueError("Exact revision required")
        result = current_app.config["PROTECTION_SERVICES"].revoke(run_id, **body)
        return jsonify(status="success", data=result), 200
    except PracticeAgentError as exc:
        return jsonify(status="error", code=exc.code), 403
    except (ValueError, TypeError, KeyError):
        return jsonify(status="error", code="protection_request_invalid"), 400
    except Exception:
        return jsonify(status="unavailable", code="protection_custody_unavailable"), 503
