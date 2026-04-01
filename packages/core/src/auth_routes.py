# packages/core/src/auth_routes.py
"""Auth REST API — setup, login, PIN verify, status, logout.

Blueprint prefix: /v1/auth
Public endpoints (no API key required):
  - GET  /v1/auth/status   — check if setup complete
  - POST /v1/auth/setup    — one-time account creation
  - POST /v1/auth/login    — daily password + TOTP login
  - POST /v1/auth/pin      — PIN quick-unlock
  - POST /v1/auth/logout   — invalidate session
"""

from __future__ import annotations

import logging
import time
from datetime import datetime, timezone, timedelta
from typing import Any

import jwt
from flask import Blueprint, jsonify, request, current_app

logger = logging.getLogger("flinttrade.auth")

auth_bp = Blueprint("auth", __name__, url_prefix="/v1/auth")

# JWT config
_JWT_SECRET_KEY = ""  # Set from env or generated at startup
_JWT_ALGORITHM = "HS256"

# IST timezone offset
_IST_OFFSET = timedelta(hours=5, minutes=30)


def _get_auth_service():
    """Get the AuthService instance from app config."""
    return current_app.config.get("AUTH_SERVICE")


def _get_jwt_secret() -> str:
    """Get or generate the JWT secret."""
    global _JWT_SECRET_KEY
    if not _JWT_SECRET_KEY:
        import secrets
        _JWT_SECRET_KEY = current_app.config.get("JWT_SECRET", secrets.token_urlsafe(64))
    return _JWT_SECRET_KEY


def _next_8am_ist() -> datetime:
    """Calculate the next 8:00 AM IST from now."""
    now_utc = datetime.now(timezone.utc)
    now_ist = now_utc + _IST_OFFSET
    today_8am_ist = now_ist.replace(hour=8, minute=0, second=0, microsecond=0)
    if now_ist >= today_8am_ist:
        today_8am_ist += timedelta(days=1)
    # Convert back to UTC
    return today_8am_ist - _IST_OFFSET


def _create_token(username: str) -> str:
    """Create a JWT that expires at next 8:00 AM IST."""
    exp = _next_8am_ist()
    payload = {
        "sub": username,
        "iat": datetime.now(timezone.utc),
        "exp": exp,
        "type": "session",
    }
    return jwt.encode(payload, _get_jwt_secret(), algorithm=_JWT_ALGORITHM)


@auth_bp.route("/status", methods=["GET"])
def auth_status() -> tuple[Any, int]:
    """Check if account is set up and if user is locked out."""
    svc = _get_auth_service()
    if svc is None:
        return jsonify({"status": "error", "message": "Auth service not available."}), 503
    return jsonify({
        "status": "success",
        "data": {
            "is_setup": svc.is_setup(),
            "is_locked": svc.is_locked(),
        },
    }), 200


@auth_bp.route("/setup", methods=["POST"])
def auth_setup() -> tuple[Any, int]:
    """One-time account setup. Returns backup codes and TOTP URI."""
    svc = _get_auth_service()
    if svc is None:
        return jsonify({"status": "error", "message": "Auth service not available."}), 503

    body = request.get_json(silent=True) or {}
    username = str(body.get("username", "")).strip()
    email = str(body.get("email", "")).strip()
    password = str(body.get("password", ""))
    pin = str(body.get("pin", ""))

    if not username or not email or not password or not pin:
        return jsonify({"status": "error", "message": "All fields required: username, email, password, pin."}), 400

    try:
        backup_codes = svc.setup_account(username, email, password, pin)
    except ValueError as exc:
        return jsonify({"status": "error", "message": str(exc)}), 400
    except RuntimeError as exc:
        return jsonify({"status": "error", "message": str(exc)}), 409

    return jsonify({
        "status": "success",
        "data": {
            "backup_codes": backup_codes,
            "totp_uri": svc.get_totp_provisioning_uri(),
        },
    }), 201


@auth_bp.route("/login", methods=["POST"])
def auth_login() -> tuple[Any, int]:
    """Daily login with password + TOTP."""
    svc = _get_auth_service()
    if svc is None:
        return jsonify({"status": "error", "message": "Auth service not available."}), 503

    if svc.is_locked():
        return jsonify({
            "status": "error",
            "message": "Account locked after too many failed attempts. Reset via email.",
        }), 423

    body = request.get_json(silent=True) or {}
    password = str(body.get("password", ""))
    totp_code = str(body.get("totp_code", ""))

    if not svc.verify_password(password):
        return jsonify({"status": "error", "message": "Invalid credentials."}), 401

    if not svc.verify_totp(totp_code):
        # Try backup code as fallback
        if not svc.verify_backup_code(totp_code):
            return jsonify({"status": "error", "message": "Invalid TOTP code."}), 401

    profile = svc.get_profile()
    token = _create_token(profile.get("username", "user"))

    return jsonify({
        "status": "success",
        "data": {
            "token": token,
            "username": profile.get("username"),
            "expires_at": _next_8am_ist().isoformat(),
        },
    }), 200


@auth_bp.route("/pin", methods=["POST"])
def auth_pin_verify() -> tuple[Any, int]:
    """PIN quick-unlock — returns new session token."""
    svc = _get_auth_service()
    if svc is None:
        return jsonify({"status": "error", "message": "Auth service not available."}), 503

    body = request.get_json(silent=True) or {}
    pin = str(body.get("pin", ""))

    if not svc.verify_pin(pin):
        return jsonify({"status": "error", "message": "Invalid PIN."}), 401

    profile = svc.get_profile()
    token = _create_token(profile.get("username", "user"))

    return jsonify({
        "status": "success",
        "data": {"token": token},
    }), 200


@auth_bp.route("/logout", methods=["POST"])
def auth_logout() -> tuple[Any, int]:
    """Invalidate current session."""
    # JWT is stateless — client discards token
    # Server-side: log the logout event
    logger.info("User logged out")
    return jsonify({"status": "success", "data": {"message": "Logged out."}}), 200
