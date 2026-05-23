# packages/core/core/src/user_routes.py
"""Multi-user admin REST API.

Blueprint prefix: /v1/users
All endpoints require admin role (enforced via JWT + role check).

Endpoints:
  - GET    /v1/users              — list all users
  - POST   /v1/users              — create a user
  - PUT    /v1/users/<username>   — update a user
  - DELETE /v1/users/<username>   — soft-delete a user
"""

from __future__ import annotations

import logging
import os
from typing import Any

import jwt
from flask import Blueprint, current_app, jsonify, request

logger = logging.getLogger("flinttrade.users")

users_bp = Blueprint("users", __name__, url_prefix="/v1/users")


def _get_user_manager():
    """Get the UserManager instance from app config."""
    return current_app.config.get("USER_MANAGER")


def _get_jwt_secret() -> str:
    """Reuse the JWT secret from auth_routes."""
    from .auth_routes import _get_jwt_secret as _auth_jwt_secret  # noqa: PLC0415
    return _auth_jwt_secret()


def _require_admin() -> tuple[Any, int] | dict:
    """Extract JWT from Authorization header and verify admin role.

    Returns:
        The decoded JWT payload dict on success, or a (jsonify, status)
        error tuple on failure.
    """
    auth_header = request.headers.get("Authorization", "")
    token = auth_header.removeprefix("Bearer ").strip()
    if not token:
        return jsonify({"status": "error", "message": "Authentication required."}), 401

    try:
        payload = jwt.decode(token, _get_jwt_secret(), algorithms=["HS256"])
    except jwt.ExpiredSignatureError:
        return jsonify({"status": "error", "message": "Token expired."}), 401
    except jwt.InvalidTokenError:
        return jsonify({"status": "error", "message": "Invalid token."}), 401

    # For now, role is checked against the 'role' claim in the JWT.
    # In the current single-user system, there is no role claim — so we
    # also accept if the caller is the original single-user admin (no role
    # claim means legacy single-user token → treat as admin).
    role = payload.get("role", "admin")
    if role != "admin":
        return jsonify({"status": "error", "message": "Admin access required."}), 403

    return payload


def _is_multi_user_enabled() -> bool:
    """Check whether multi-user mode is enabled."""
    return os.environ.get("FLINTTRADE_MULTI_USER", "").strip() in ("1", "true", "yes")


@users_bp.route("", methods=["GET"])
def list_users() -> tuple[Any, int]:
    """List all users (admin only)."""
    if not _is_multi_user_enabled():
        return jsonify({"status": "error", "message": "Multi-user mode not enabled."}), 404

    auth = _require_admin()
    if isinstance(auth, tuple):
        return auth

    mgr = _get_user_manager()
    if mgr is None:
        return jsonify({"status": "error", "message": "User manager not available."}), 503

    users = mgr.list_users()
    return jsonify({"status": "success", "data": {"users": users}}), 200


@users_bp.route("", methods=["POST"])
def create_user() -> tuple[Any, int]:
    """Create a new user (admin only)."""
    if not _is_multi_user_enabled():
        return jsonify({"status": "error", "message": "Multi-user mode not enabled."}), 404

    auth = _require_admin()
    if isinstance(auth, tuple):
        return auth

    mgr = _get_user_manager()
    if mgr is None:
        return jsonify({"status": "error", "message": "User manager not available."}), 503

    body = request.get_json(silent=True) or {}
    username = str(body.get("username", "")).strip()
    password = str(body.get("password", ""))
    email = str(body.get("email", "")).strip()
    role = str(body.get("role", "trader")).strip()

    if not username or not password or not email:
        return jsonify({"status": "error", "message": "Required fields: username, password, email."}), 400

    try:
        user = mgr.create_user(username, password, email, role)
    except ValueError as exc:
        return jsonify({"status": "error", "message": str(exc)}), 400
    except RuntimeError as exc:
        return jsonify({"status": "error", "message": str(exc)}), 409

    return jsonify({"status": "success", "data": user}), 201


@users_bp.route("/<username>", methods=["PUT"])
def update_user(username: str) -> tuple[Any, int]:
    """Update a user (admin only)."""
    if not _is_multi_user_enabled():
        return jsonify({"status": "error", "message": "Multi-user mode not enabled."}), 404

    auth = _require_admin()
    if isinstance(auth, tuple):
        return auth

    mgr = _get_user_manager()
    if mgr is None:
        return jsonify({"status": "error", "message": "User manager not available."}), 503

    body = request.get_json(silent=True) or {}
    allowed_fields = {k: v for k, v in body.items() if k in ("email", "role", "is_active")}

    if not allowed_fields:
        return jsonify({"status": "error", "message": "No valid fields to update."}), 400

    try:
        updated = mgr.update_user(username, **allowed_fields)
    except ValueError as exc:
        return jsonify({"status": "error", "message": str(exc)}), 400

    if not updated:
        return jsonify({"status": "error", "message": "User not found."}), 404

    user = mgr.get_user(username)
    return jsonify({"status": "success", "data": user}), 200


@users_bp.route("/<username>", methods=["DELETE"])
def delete_user(username: str) -> tuple[Any, int]:
    """Soft-delete a user (admin only)."""
    if not _is_multi_user_enabled():
        return jsonify({"status": "error", "message": "Multi-user mode not enabled."}), 404

    auth = _require_admin()
    if isinstance(auth, tuple):
        return auth

    mgr = _get_user_manager()
    if mgr is None:
        return jsonify({"status": "error", "message": "User manager not available."}), 503

    deleted = mgr.delete_user(username)
    if not deleted:
        return jsonify({"status": "error", "message": "User not found."}), 404

    return jsonify({"status": "success", "data": {"message": f"User '{username}' deactivated."}}), 200
