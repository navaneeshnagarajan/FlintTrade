"""Scope-based authorisation for admin / observability endpoints (OBS-09).

Right-sized for personal use — NO multi-tenant RBAC ceremony. The model:

* Every ``/v1/*`` request is already authenticated at the app level by the operator's
  single API key (``app.py`` ``require_auth``). The operator IS the admin and holds every
  scope; an API-key request with no session token passes ``require_scope`` unchanged.
* A session JWT (from ``auth_routes._create_token``) carries an additive ``scopes`` claim.
  The operator's own session gets :data:`DEFAULT_SESSION_SCOPES` (read access to every
  admin surface). A deliberately narrowed session — e.g. a low-trust dashboard token —
  can be minted with a subset, and ``require_scope`` will then deny it the audit export.

This closes the real hole the audit flagged (a scoped session could previously reach
``/v1/audit/export`` with no scope check) without inventing roles or a permission matrix.
"""

from __future__ import annotations

import hmac
import os
from functools import wraps
from typing import Any, Callable

from flask import jsonify, request

# v1.0 default session scopes — the operator's own session is granted read access to every
# admin/observability surface. Narrower sessions are minted with an explicit subset.
DEFAULT_SESSION_SCOPES: tuple[str, ...] = (
    "admin.observability.read",
    "admin.observability.run",
    "admin.audit.read",
    "admin.audit.verify",
    "admin.activity",
    "admin.health.read",
    "admin.errors.read",
    "admin.logs.read.operational",
    "admin.state.read",
)


def _session_token() -> str | None:
    """Return the session JWT from the Authorization header or session cookie, or None."""
    auth = request.headers.get("Authorization", "")
    if auth.startswith("Bearer "):
        return auth[7:].strip() or None
    return request.cookies.get("flinttrade_session") or None


def require_scope(scope: str) -> Callable[[Callable[..., Any]], Callable[..., Any]]:
    """Enforce that the caller holds ``scope`` (gate-11; observability §16.3).

    Applied UNDER the blueprint route decorator::

        @audit_bp.route("/export", methods=["GET"])
        @require_scope("admin.audit.read")
        def audit_export(): ...

    A request authenticated only by the operator's API key (no session token) holds all
    scopes. A request carrying a session JWT must have ``scope`` in its ``scopes`` claim;
    otherwise it gets HTTP 403.
    """

    def decorator(fn: Callable[..., Any]) -> Callable[..., Any]:
        @wraps(fn)
        def wrapper(*args: Any, **kwargs: Any) -> Any:
            token = _session_token()
            if token is None:
                # Operator authenticated by the shared API key — holds every scope.
                return fn(*args, **kwargs)
            try:
                from .auth_routes import decode_token  # lazy: avoid import cycle

                payload = decode_token(token)
            except Exception:
                expected_key = os.environ.get("FLINTTRADE_API_KEY", "") or os.environ.get("OPENALGO_API_KEY", "")
                if expected_key and hmac.compare_digest(token, expected_key):
                    return fn(*args, **kwargs)
                return (
                    jsonify({"status": "error", "message": "invalid or expired session token"}),
                    401,
                )
            scopes = payload.get("scopes")
            if scopes is None:
                # Legacy tokens minted before the scopes claim existed are operator
                # sessions and therefore carry the full default scope set.
                scopes = DEFAULT_SESSION_SCOPES
            if scope not in scopes:
                return (
                    jsonify({"status": "error", "message": f"missing required scope: {scope}"}),
                    403,
                )
            return fn(*args, **kwargs)

        wrapper.__required_scope__ = scope  # consumed by the gate-11 test
        return wrapper

    return decorator
