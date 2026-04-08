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
import os
import secrets
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Any

import jwt
from flask import Blueprint, jsonify, request, current_app

logger = logging.getLogger("flinttrade.auth")

auth_bp = Blueprint("auth", __name__, url_prefix="/v1/auth")


def _get_limiter():
    """Get the flask-limiter instance from the app config."""
    return current_app.config.get("LIMITER")


def _rate_limit(limit_string: str):
    """Apply a flask-limiter rate limit lazily (limiter lives in app config).

    Returns a decorator that applies the rate limit at request time,
    allowing the blueprint to be registered before the limiter is created.
    """
    import functools

    def decorator(f):
        @functools.wraps(f)
        def wrapper(*args, **kwargs):
            # The actual rate-limit enforcement is handled by flask-limiter
            # via the deferred decoration below; this wrapper is a no-op.
            return f(*args, **kwargs)

        # Store the limit string so we can apply it once the app is ready.
        if not hasattr(wrapper, "_rate_limits"):
            wrapper._rate_limits = []
        wrapper._rate_limits.append(limit_string)
        return wrapper

    return decorator


@auth_bp.record
def _apply_rate_limits(state):
    """Apply deferred rate limits once the blueprint is registered on an app."""
    limiter = state.app.config.get("LIMITER")
    if limiter is None:
        logger.warning("No LIMITER in app config — auth rate limits not applied")
        return

    for rule_func in [auth_status, auth_setup, auth_login, auth_pin_verify, auth_logout]:
        limits = getattr(rule_func, "_rate_limits", [])
        for limit_str in limits:
            limiter.limit(limit_str)(rule_func)

# JWT config
_JWT_SECRET_KEY = ""  # Set from env or generated at startup
_JWT_ALGORITHM = "HS256"

# IST timezone offset
_IST_OFFSET = timedelta(hours=5, minutes=30)


def _get_auth_service():
    """Get the AuthService instance from app config."""
    return current_app.config.get("AUTH_SERVICE")


def _get_jwt_secret() -> str:
    """Get or generate the JWT secret.

    Priority:
    1. JWT_SECRET environment variable (explicit override)
    2. Persisted secret from ~/.flinttrade/jwt_secret
    3. Generate a new secret and persist it for future restarts
    """
    global _JWT_SECRET_KEY
    if _JWT_SECRET_KEY:
        return _JWT_SECRET_KEY

    # 1. Environment variable override
    env_secret = os.environ.get("JWT_SECRET", "")
    if env_secret:
        _JWT_SECRET_KEY = env_secret
        return _JWT_SECRET_KEY

    # 2. Read from persisted file, or generate and persist
    secret_file = Path.home() / ".flinttrade" / "jwt_secret"
    try:
        if secret_file.exists():
            stored = secret_file.read_text().strip()
            if stored:
                _JWT_SECRET_KEY = stored
                return _JWT_SECRET_KEY
    except OSError:
        pass

    # 3. Generate new secret and persist
    new_secret = secrets.token_urlsafe(64)
    try:
        secret_file.parent.mkdir(parents=True, exist_ok=True)
        secret_file.write_text(new_secret)
        secret_file.chmod(0o600)
    except OSError as exc:
        logger.warning("Could not persist JWT secret to %s: %s", secret_file, exc)

    _JWT_SECRET_KEY = new_secret
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
    """Create a JWT that expires at next 8:00 AM IST.

    Includes a unique ``jti`` (JWT ID) to enable future token revocation
    via a server-side blocklist.
    """
    exp = _next_8am_ist()
    payload = {
        "sub": username,
        "iat": datetime.now(timezone.utc),
        "exp": exp,
        "type": "session",
        "jti": secrets.token_hex(16),
    }
    return jwt.encode(payload, _get_jwt_secret(), algorithm=_JWT_ALGORITHM)


@auth_bp.route("/status", methods=["GET"])
@_rate_limit("30 per minute")
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
@_rate_limit("3 per minute")
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

    if not username or not email or not password:
        return jsonify({"status": "error", "message": "Required fields: username, email, password."}), 400

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
@_rate_limit("5 per minute")
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
@_rate_limit("10 per minute")
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
@_rate_limit("10 per minute")
def auth_logout() -> tuple[Any, int]:
    """Invalidate current session."""
    # JWT is stateless — client discards token
    # Server-side: log the logout event
    logger.info("User logged out")
    return jsonify({"status": "success", "data": {"message": "Logged out."}}), 200
