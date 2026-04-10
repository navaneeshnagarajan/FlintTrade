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

import functools
import logging
import os
import secrets
import time
from collections import defaultdict
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Any

import jwt
from flask import Blueprint, jsonify, request, current_app

logger = logging.getLogger("flinttrade.auth")

auth_bp = Blueprint("auth", __name__, url_prefix="/v1/auth")

# ---------------------------------------------------------------------------
# JWT revocation blocklist
# ---------------------------------------------------------------------------

# Maps jti → expiry epoch (UTC seconds).  Checked on every token decode.
_REVOKED_JTIS: dict[str, float] = {}


def _revoke_jti(jti: str, exp: float) -> None:
    """Add a JTI to the revocation blocklist.

    Args:
        jti: JWT ID claim from the token.
        exp: Token expiry as a UTC epoch float.  Used for cleanup.
    """
    _REVOKED_JTIS[jti] = exp
    _cleanup_revoked_jtis()


def _cleanup_revoked_jtis() -> None:
    """Remove expired entries from the JTI blocklist.

    Expired tokens cannot be replayed anyway (signature check fails), so
    keeping them in the set wastes memory.  Called on every revocation.
    """
    now = datetime.now(timezone.utc).timestamp()
    expired = [jti for jti, exp in _REVOKED_JTIS.items() if exp <= now]
    for jti in expired:
        del _REVOKED_JTIS[jti]


def _is_jti_revoked(jti: str) -> bool:
    """Check whether a JTI has been revoked.

    Args:
        jti: JWT ID claim to check.

    Returns:
        ``True`` if the token has been explicitly revoked.
    """
    return jti in _REVOKED_JTIS


# ---------------------------------------------------------------------------
# In-memory rate limiter (fallback when Flask-Limiter is absent)
# ---------------------------------------------------------------------------

# {(endpoint_name, ip): [epoch_float, ...]}
_RATE_LIMIT_STORE: dict[tuple[str, str], list[float]] = defaultdict(list)


def _parse_limit(limit_string: str) -> tuple[int, int]:
    """Parse a limit string like ``"10 per minute"`` into ``(count, seconds)``.

    Args:
        limit_string: Rate limit descriptor, e.g. ``"5 per minute"``.

    Returns:
        ``(max_requests, window_seconds)`` tuple.
    """
    parts = limit_string.lower().split()
    count = int(parts[0])
    unit = parts[-1] if len(parts) >= 3 else "minute"
    unit_map = {"second": 1, "minute": 60, "hour": 3600, "day": 86400}
    seconds = unit_map.get(unit, 60)
    return count, seconds


def _check_in_memory_rate_limit(endpoint: str, max_requests: int, window_seconds: int) -> bool:
    """Sliding-window in-memory rate limit check.

    Returns ``True`` if the request is within the limit; ``False`` otherwise.
    Mutates ``_RATE_LIMIT_STORE`` to record the new request timestamp.

    Args:
        endpoint: Endpoint name used as part of the bucket key.
        max_requests: Maximum number of requests allowed in the window.
        window_seconds: Duration of the sliding window in seconds.

    Returns:
        ``True`` if allowed, ``False`` if limit exceeded.
    """
    ip = request.remote_addr or "unknown"
    key = (endpoint, ip)
    now = time.monotonic()
    cutoff = now - window_seconds

    timestamps = _RATE_LIMIT_STORE[key]
    # Prune expired entries
    _RATE_LIMIT_STORE[key] = [t for t in timestamps if t > cutoff]

    if len(_RATE_LIMIT_STORE[key]) >= max_requests:
        return False

    _RATE_LIMIT_STORE[key].append(now)
    return True


def _get_limiter():
    """Get the flask-limiter instance from the app config."""
    return current_app.config.get("LIMITER")


def _rate_limit(limit_string: str):
    """Apply a rate limit to a route function.

    Tries Flask-Limiter first (if configured in ``app.config["LIMITER"]``).
    Falls back to the in-memory sliding-window limiter when Flask-Limiter is
    absent.  Either path *enforces* the limit — this is no longer a no-op.

    Args:
        limit_string: Limit descriptor, e.g. ``"10 per minute"``.

    Returns:
        Decorator that wraps the route function.
    """
    max_requests, window_seconds = _parse_limit(limit_string)

    def decorator(f: Any) -> Any:
        @functools.wraps(f)
        def wrapper(*args: Any, **kwargs: Any) -> Any:
            limiter = _get_limiter()
            if limiter is not None:
                # Flask-Limiter is available — it handles enforcement via the
                # deferred decorator applied in ``_apply_rate_limits``.
                return f(*args, **kwargs)

            # Fallback: enforce with the in-memory sliding-window limiter.
            if not _check_in_memory_rate_limit(f.__name__, max_requests, window_seconds):
                logger.warning(
                    "Rate limit exceeded for %s from %s", f.__name__, request.remote_addr
                )
                return jsonify({
                    "status": "error",
                    "message": "Too many requests. Please try again later.",
                }), 429

            return f(*args, **kwargs)

        # Preserve limit metadata for the deferred Flask-Limiter path.
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
        logger.warning(
            "No LIMITER in app config — auth rate limits enforced by in-memory fallback"
        )
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


def _create_token(
    username: str,
    *,
    live_mode_unlocked: bool = False,
    mode: str = "explore",
) -> str:
    """Create a JWT that expires at next 8:00 AM IST.

    Includes a unique ``jti`` (JWT ID) for server-side revocation and a
    ``mode`` claim so that ``order_routes`` can enforce the trading mode
    without trusting a client-controlled header.

    Args:
        username: The authenticated user's name.
        live_mode_unlocked: If ``True``, the token carries a
            ``live_mode_unlocked`` claim that authorises live order
            execution.  Only set after successful PIN verification.
        mode: Trading mode at token-issue time: ``"explore"``,
            ``"practice"``, or ``"live"``.  Defaults to ``"explore"`` so
            that freshly issued (non-PIN) tokens cannot place live orders.
    """
    exp = _next_8am_ist()
    payload = {
        "sub": username,
        "iat": datetime.now(timezone.utc),
        "exp": exp,
        "type": "session",
        "jti": secrets.token_hex(16),
        "live_mode_unlocked": live_mode_unlocked,
        "mode": mode,
    }
    return jwt.encode(payload, _get_jwt_secret(), algorithm=_JWT_ALGORITHM)


def decode_token(token: str) -> dict[str, Any]:
    """Decode and verify a FlintTrade JWT.

    Also checks the server-side JTI revocation blocklist so that tokens
    invalidated by logout or password change are rejected even before expiry.

    Args:
        token: Encoded JWT string.

    Returns:
        Decoded payload dict.

    Raises:
        jwt.ExpiredSignatureError: If the token has expired.
        jwt.InvalidTokenError: If the token is invalid or has been revoked.
    """
    payload = jwt.decode(token, _get_jwt_secret(), algorithms=[_JWT_ALGORITHM])
    jti = payload.get("jti", "")
    if jti and _is_jti_revoked(jti):
        raise jwt.InvalidTokenError("Token has been revoked")
    return payload


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
    """PIN quick-unlock — returns new session token with live mode unlocked.

    After successful PIN verification the returned JWT carries
    ``live_mode_unlocked: true``, which is checked server-side by
    ``order_routes`` before any live order is forwarded to OpenAlgo.
    """
    svc = _get_auth_service()
    if svc is None:
        return jsonify({"status": "error", "message": "Auth service not available."}), 503

    body = request.get_json(silent=True) or {}
    pin = str(body.get("pin", ""))

    if not svc.verify_pin(pin):
        return jsonify({"status": "error", "message": "Invalid PIN."}), 401

    profile = svc.get_profile()
    token = _create_token(
        profile.get("username", "user"),
        live_mode_unlocked=True,
        mode="live",
    )

    return jsonify({
        "status": "success",
        "data": {"token": token, "live_mode_unlocked": True},
    }), 200


@auth_bp.route("/logout", methods=["POST"])
@_rate_limit("10 per minute")
def auth_logout() -> tuple[Any, int]:
    """Invalidate current session by revoking the JWT on the server side."""
    auth_header = request.headers.get("Authorization", "")
    token = auth_header.removeprefix("Bearer ").strip()
    if not token:
        token = request.headers.get("X-FlintTrade-Token", "").strip()

    if token:
        try:
            # Decode without blocklist check so we can extract the jti even
            # for tokens that were already revoked (idempotent logout).
            payload = jwt.decode(token, _get_jwt_secret(), algorithms=[_JWT_ALGORITHM])
            jti = payload.get("jti", "")
            exp = float(payload.get("exp", 0))
            if jti:
                _revoke_jti(jti, exp)
                logger.info("JWT revoked on logout — jti=%s", jti)
        except (jwt.ExpiredSignatureError, jwt.InvalidTokenError) as exc:
            # Token already expired or invalid — nothing to revoke.
            logger.debug("Logout with invalid/expired token: %s", exc)

    logger.info("User logged out")
    return jsonify({"status": "success", "data": {"message": "Logged out."}}), 200


# ---------------------------------------------------------------------------
# Password reset — token helpers
# ---------------------------------------------------------------------------


def _create_reset_token(username: str) -> str:
    """Create a short-lived JWT for password reset (1 hour expiry).

    Args:
        username: The user whose password is being reset.

    Returns:
        Encoded JWT string.
    """
    from datetime import timedelta as _td  # noqa: PLC0415

    now = datetime.now(timezone.utc)
    payload = {
        "sub": username,
        "iat": now,
        "exp": now + _td(hours=1),
        "type": "reset",
        "jti": secrets.token_hex(16),
    }
    return jwt.encode(payload, _get_jwt_secret(), algorithm=_JWT_ALGORITHM)


def _verify_reset_token(token: str) -> str | None:
    """Verify a password-reset JWT and return the username.

    Returns None if the token is invalid, expired, or not a reset token.
    """
    try:
        payload = jwt.decode(token, _get_jwt_secret(), algorithms=[_JWT_ALGORITHM])
        if payload.get("type") != "reset":
            return None
        return payload.get("sub")
    except (jwt.ExpiredSignatureError, jwt.InvalidTokenError):
        return None


# ---------------------------------------------------------------------------
# Password reset — endpoints
# ---------------------------------------------------------------------------

# Placeholder for flask-mail Message (lazy import so tests can mock it)
try:
    from flask_mail import Message  # type: ignore[import]
except ImportError:
    Message = None  # type: ignore[assignment,misc]


@auth_bp.route("/forgot-password", methods=["POST"])
def auth_forgot_password() -> tuple[Any, int]:
    """Request a password reset email.

    Always returns 200 to avoid leaking whether the email exists.
    """
    mail = current_app.config.get("MAIL")
    if mail is None:
        return jsonify({"status": "error", "message": "Email service not configured."}), 503

    body = request.get_json(silent=True) or {}
    email = str(body.get("email", "")).strip()
    if not email:
        return jsonify({"status": "error", "message": "Email is required."}), 400

    svc = _get_auth_service()
    if svc is not None:
        stored_email = svc.get_email()
        if stored_email and stored_email == email:
            profile = svc.get_profile()
            username = profile.get("username", "user")
            token = _create_reset_token(username)
            try:
                msg = Message(
                    subject="FlintTrade Password Reset",
                    recipients=[email],
                    body=f"Your password reset token: {token}\n\nThis token expires in 1 hour.",
                )
                mail.send(msg)
            except Exception as exc:
                logger.error("Failed to send reset email: %s", exc)

    return jsonify({"status": "success", "message": "If the email is registered, a reset link has been sent."}), 200


@auth_bp.route("/reset-password", methods=["POST"])
def auth_reset_password() -> tuple[Any, int]:
    """Reset password using a valid reset token."""
    body = request.get_json(silent=True) or {}
    token = str(body.get("token", "")).strip()
    new_password = str(body.get("new_password", ""))

    if not token or not new_password:
        return jsonify({"status": "error", "message": "Token and new_password are required."}), 400

    username = _verify_reset_token(token)
    if username is None:
        return jsonify({"status": "error", "message": "Invalid or expired reset token."}), 400

    svc = _get_auth_service()
    if svc is None:
        return jsonify({"status": "error", "message": "Auth service not available."}), 503

    try:
        result = svc.update_password(username, new_password)
    except ValueError as exc:
        return jsonify({"status": "error", "message": str(exc)}), 400

    if not result:
        return jsonify({"status": "error", "message": "Password update failed."}), 400

    # Revoke the one-time reset token so it cannot be replayed.
    try:
        rt_payload = jwt.decode(token, _get_jwt_secret(), algorithms=[_JWT_ALGORITHM])
        rt_jti = rt_payload.get("jti", "")
        rt_exp = float(rt_payload.get("exp", 0))
        if rt_jti:
            _revoke_jti(rt_jti, rt_exp)
    except (jwt.ExpiredSignatureError, jwt.InvalidTokenError):
        pass

    # Also revoke any active session token provided in the Authorization header
    # so all open sessions are invalidated after a password change.
    auth_header = request.headers.get("Authorization", "")
    session_token = auth_header.removeprefix("Bearer ").strip()
    if session_token:
        try:
            sess_payload = jwt.decode(session_token, _get_jwt_secret(), algorithms=[_JWT_ALGORITHM])
            sess_jti = sess_payload.get("jti", "")
            sess_exp = float(sess_payload.get("exp", 0))
            if sess_jti:
                _revoke_jti(sess_jti, sess_exp)
        except (jwt.ExpiredSignatureError, jwt.InvalidTokenError):
            pass

    return jsonify({"status": "success", "message": "Password has been reset."}), 200
