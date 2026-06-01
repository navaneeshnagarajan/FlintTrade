# packages/core/core/src/auth_routes.py
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
from typing import Any

import jwt
from flask import Blueprint, jsonify, request, current_app

logger = logging.getLogger("flinttrade.auth")

auth_bp = Blueprint("auth", __name__, url_prefix="/v1/auth")

# ---------------------------------------------------------------------------
# JWT revocation blocklist — DuckDB-backed, shared across gunicorn workers.
# ---------------------------------------------------------------------------


def _revoke_jti(jti: str, exp: float) -> None:
    """Persist a revoked JTI to the shared AuthState DB.

    Args:
        jti: JWT ID claim from the token.
        exp: Token expiry as a UTC epoch float.  Used for cleanup.
    """
    from .auth_state import get_auth_state  # lazy to avoid circular import

    get_auth_state().revoke_jti(jti, exp)


def _is_jti_revoked(jti: str) -> bool:
    """Check whether a JTI has been revoked.

    Args:
        jti: JWT ID claim to check.

    Returns:
        ``True`` if the token has been explicitly revoked.
    """
    from .auth_state import get_auth_state  # lazy import

    return get_auth_state().is_jti_revoked(jti)


# ---------------------------------------------------------------------------
# Rate limiter fallback — delegates to the persistent AuthState (DuckDB).
# The in-memory ``defaultdict`` is retained for legacy callers but writes
# go through the shared store so multi-worker deployments coordinate.
# ---------------------------------------------------------------------------

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
    try:
        from .auth_state import get_auth_state  # lazy import

        return get_auth_state().check_rate_limit(
            endpoint=endpoint,
            ip=ip,
            max_requests=max_requests,
            window_seconds=window_seconds,
        )
    except Exception as exc:
        # DuckDB unavailable (e.g. during import-time checks); fall back
        # to the in-process dict so the limiter keeps enforcing locally.
        logger.debug("Auth state DB unavailable, falling back in-process: %s", exc)
        key = (endpoint, ip)
        now = time.monotonic()
        cutoff = now - window_seconds
        timestamps = _RATE_LIMIT_STORE[key]
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
    """Apply deferred rate limits once the blueprint is registered on an app.

    Auto-discovers every blueprint view that carries the ``_rate_limits``
    attribute set by the ``@_rate_limit(...)`` decorator. The previous
    hardcoded list (auth_status, auth_setup, auth_login, auth_pin_verify,
    auth_logout) silently skipped every other ``@_rate_limit`` decorator
    in the module — including pre-existing ones on ``auth_setup_reset``
    and ``auth_setup_regenerate_2fa`` and the 2026-05-19 additions on
    ``auth_mode_switch``, ``auth_forgot_password``, ``auth_reset_password``.
    Codex caught the new gaps; this rewrite also closes the older ones.
    """
    limiter = state.app.config.get("LIMITER")
    if limiter is None:
        logger.warning(
            "No LIMITER in app config — auth rate limits enforced by in-memory fallback"
        )
        return

    registered = 0
    # Scan the module's own globals for any function carrying the
    # ``_rate_limits`` attribute the ``@_rate_limit`` decorator sets.
    # This is module-local so it cannot accidentally pick up unrelated
    # view functions registered by other blueprints on the same app.
    #
    # ``inspect.isfunction`` is intentionally strict so that Flask's
    # ``current_app`` (a Werkzeug LocalProxy in globals) is not poked —
    # ``getattr(current_app, "_rate_limits", None)`` would otherwise
    # try to resolve the proxy outside a request context and raise.
    import inspect  # noqa: PLC0415
    for obj in list(globals().values()):
        if not inspect.isfunction(obj):
            continue
        limits = getattr(obj, "_rate_limits", None)
        if not limits:
            continue
        for limit_str in limits:
            limiter.limit(limit_str)(obj)
            registered += 1
        logger.debug(
            "Registered %d rate limit(s) on %s", len(limits), obj.__name__,
        )
    logger.info("Auth blueprint: %d rate-limit rules registered with Flask-Limiter", registered)

# JWT config
_JWT_SECRET_KEY = ""  # Set from env or generated at startup
_JWT_ALGORITHM = "HS256"

# IST timezone offset
_IST_OFFSET = timedelta(hours=5, minutes=30)


def _get_auth_service():
    """Get the AuthService instance from app config."""
    return current_app.config.get("AUTH_SERVICE")


def _get_jwt_secret() -> str:
    """Get or generate the JWT signing secret.

    Source of truth (NO environment variable — secrets out of env, decision B/C):
      1. Persisted hardened secret at ``<workspace>/jwt_secret``.
      2. Generate a fresh ``secrets.token_urlsafe(64)``, persist it hardened.
    Honours ``FLINTTRADE_WORKSPACE_DIR`` so tests stay isolated from the
    operator's real home.
    """
    global _JWT_SECRET_KEY
    if _JWT_SECRET_KEY:
        return _JWT_SECRET_KEY

    from .secure_file import harden  # noqa: PLC0415
    from .workspace import workspace_dir  # noqa: PLC0415

    secret_file = workspace_dir() / "jwt_secret"
    try:
        if secret_file.exists():
            stored = secret_file.read_text().strip()
            if stored:
                _JWT_SECRET_KEY = stored
                return _JWT_SECRET_KEY
    except OSError:
        pass

    new_secret = secrets.token_urlsafe(64)
    try:
        secret_file.parent.mkdir(parents=True, exist_ok=True)
        secret_file.write_text(new_secret)
        harden(secret_file)  # SC-04: icacls/0600 owner-only
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
    from .auth_scopes import DEFAULT_SESSION_SCOPES  # noqa: PLC0415 — avoid import cycle

    exp = _next_8am_ist()
    payload = {
        "sub": username,
        "iat": datetime.now(timezone.utc),
        "exp": exp,
        "type": "session",
        "jti": secrets.token_hex(16),
        "live_mode_unlocked": live_mode_unlocked,
        "mode": mode,
        # OBS-09: additive admin-scope claim. The operator's own session gets read access
        # to every admin/observability surface; require_scope() enforces it per route.
        "scopes": list(DEFAULT_SESSION_SCOPES),
    }
    return jwt.encode(payload, _get_jwt_secret(), algorithm=_JWT_ALGORITHM)


def decode_token(token: str) -> dict[str, Any]:
    """Decode and verify a FlintTrade JWT.

    Also checks the server-side JTI revocation blocklist so that tokens
    invalidated by logout are rejected even before expiry, and rejects
    every token whose ``iat`` predates the user's most recent password
    change so that leaked sessions cannot survive a password reset. This
    is the FlintTrade analogue of OpenAlgo v2.0.0.7's session-on-password-
    change invalidation.

    Args:
        token: Encoded JWT string.

    Returns:
        Decoded payload dict.

    Raises:
        jwt.ExpiredSignatureError: If the token has expired.
        jwt.InvalidTokenError: If the token is invalid, has been revoked,
            or was issued before the most recent password change.
    """
    payload = jwt.decode(token, _get_jwt_secret(), algorithms=[_JWT_ALGORITHM])
    jti = payload.get("jti", "")
    if jti and _is_jti_revoked(jti):
        raise jwt.InvalidTokenError("Token has been revoked")

    # iat vs. password_changed_at — a password change invalidates every
    # token issued before it. Tokens minted for password resets carry
    # ``type == "reset"`` and are exempt so the reset flow itself can
    # complete. The OTP-driven reset path (``auth_reset_password_otp``)
    # does NOT mint a JWT — it consumes an in-memory OTP and calls
    # ``svc.update_password()`` directly, so no token-type exemption is
    # needed there.
    if payload.get("type") != "reset":
        iat = payload.get("iat")
        if iat is not None:
            try:
                iat_epoch = float(iat)
            except (TypeError, ValueError):
                iat_epoch = 0.0
            svc = _get_auth_service()
            if svc is not None:
                try:
                    pwd_changed_at = svc.get_password_changed_at()
                except Exception:  # pragma: no cover - defensive
                    pwd_changed_at = 0.0
                # Allow a 2-second skew window so a fresh post-change token
                # whose iat is rounded down isn't accidentally rejected.
                if pwd_changed_at > 0.0 and iat_epoch + 2.0 < pwd_changed_at:
                    raise jwt.InvalidTokenError(
                        "Token issued before most recent password change"
                    )

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


@auth_bp.route("/setup/reset", methods=["POST"])
@_rate_limit("3 per hour")
def auth_setup_reset() -> tuple[Any, int]:
    """Wipe the account during the setup wizard.

    Body: ``{"password": "…"}``. Requires the password the user just set so
    a casual shoulder-surfer cannot destroy an account. Used by the "Delete
    account & start over" escape hatch on the 2FA screen.
    """
    svc = _get_auth_service()
    if svc is None:
        return jsonify({"status": "error", "message": "Auth service not available."}), 503
    body = request.get_json(silent=True) or {}
    password = str(body.get("password", ""))
    if not password:
        return jsonify({"status": "error", "message": "Password required to confirm reset."}), 400
    if not svc.reset_account(password):
        return jsonify({"status": "error", "message": "Invalid password."}), 401
    return jsonify({"status": "success", "data": {}}), 200


@auth_bp.route("/setup/regenerate-2fa", methods=["POST"])
@_rate_limit("3 per hour")
def auth_setup_regenerate_2fa() -> tuple[Any, int]:
    """Issue a fresh TOTP URI + backup codes for the existing account.

    Body: ``{"password": "…"}``. Used by the "Reset 2FA" escape hatch on the
    setup wizard 2FA screen — useful when the user scanned the QR into the
    wrong device or wants a clean second attempt before first login.
    """
    svc = _get_auth_service()
    if svc is None:
        return jsonify({"status": "error", "message": "Auth service not available."}), 503
    body = request.get_json(silent=True) or {}
    password = str(body.get("password", ""))
    if not password:
        return jsonify({"status": "error", "message": "Password required to reset 2FA."}), 400
    result = svc.regenerate_totp(password)
    if result is None:
        return jsonify({"status": "error", "message": "Invalid password."}), 401
    totp_uri, backup_codes = result
    return jsonify({
        "status": "success",
        "data": {"totp_uri": totp_uri, "backup_codes": backup_codes},
    }), 200


def _tofu_authorise_login_actor(actor_id: str) -> None:
    """Authorise a freshly authenticated operator for the default execution account.

    Trust-on-first-use: the first human to log in claims the
    ``brokers.execution.default`` selector so gated live orders work without a
    manual ``workspace.json`` ``account_acls`` edit. In-memory only (the running
    BrokerRouter; re-established each process by an actual login) and never raises
    into the login path. Non-human actors (agents, external_intent) must be
    authorised explicitly in config.
    """
    try:
        router = current_app.config.get("BROKER_ROUTER")
        claim = getattr(router, "authorise_default_actor", None)
        if claim is None:
            return
        claimed = claim(actor_id)
        if claimed is not None:
            logger.info(
                "Auto-authorised operator %r for %s:%s (trust-on-first-use; add "
                "other actors explicitly in workspace.json brokers.account_acls)",
                actor_id, claimed[0], claimed[1],
            )
    except Exception:  # pragma: no cover — must never break login
        logger.debug("TOFU actor authorisation skipped", exc_info=True)


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
    username = str(profile.get("username") or "user")
    token = _create_token(username)
    _tofu_authorise_login_actor(username)

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


@auth_bp.route("/mode", methods=["POST"])
@_rate_limit("10 per minute")
def auth_mode_switch() -> tuple[Any, int]:
    """Downgrade the current session to Practice mode.

    Issues a NEW JWT with ``mode: "practice"`` and
    ``live_mode_unlocked: false``, and REVOKES the caller's existing JWT
    (so a stale live-unlocked token can't be replayed). This closes the
    2026-05-19 Codex audit finding that ``ModeIndicator.tsx`` was
    flipping local UI state to Practice without ever invalidating the
    PIN-unlocked JWT — meaning a retained live-unlocked JWT could still
    place live orders even after the UI displayed Practice.

    Only ``mode: "practice"`` is accepted. Upgrading to Live ALWAYS goes
    through ``/v1/auth/pin`` (re-authenticates with PIN) — no shortcut
    exists from this endpoint, by design.

    Request JSON:
        mode (str): Must be ``"practice"``. Any other value is a 400.

    Auth:
        Caller must send a valid Bearer JWT (Practice or Live). The
        endpoint reads the JTI from that token, issues a fresh JWT for
        the same user, then revokes the original JTI.

    Returns:
        JSON ``{"status": "success", "data": {"token": <new_jwt>,
        "mode": "practice", "live_mode_unlocked": false}}`` on 200.
        401 if no/invalid token; 400 if requested mode is not practice;
        503 if auth service is not configured.
    """
    target_mode = str((request.get_json(silent=True) or {}).get("mode", "")).strip().lower()
    if target_mode != "practice":
        return jsonify({
            "status": "error",
            "message": (
                "Only downgrades to 'practice' are allowed here. Upgrade to "
                "'live' via POST /v1/auth/pin with PIN verification."
            ),
        }), 400

    # Extract and verify the caller's existing JWT.
    auth_header = request.headers.get("Authorization", "")
    raw_token = auth_header.removeprefix("Bearer ").strip()
    if not raw_token:
        raw_token = request.headers.get("X-FlintTrade-Token", "").strip()
    if not raw_token:
        return jsonify({"status": "error", "message": "Authentication required."}), 401

    try:
        payload = decode_token(raw_token)
    except (jwt.ExpiredSignatureError, jwt.InvalidTokenError) as exc:
        logger.info("Mode-switch with invalid/expired token: %s", exc)
        return jsonify({"status": "error", "message": "Token invalid or expired."}), 401

    svc = _get_auth_service()
    if svc is None:
        return jsonify({"status": "error", "message": "Auth service not available."}), 503

    # Revoke the prior JTI FIRST — fail-closed. If the revocation can't
    # be persisted (DB lock, disk full, whatever), the old live-unlocked
    # token is still replayable until its 8 AM IST expiry, so we MUST NOT
    # tell the frontend the downgrade succeeded; the UI would then flip to
    # Practice while a stale live token sits in memory ready to place
    # real orders. Codex stop-gate 2026-05-19 flagged this as the inverse
    # of the original CRITICAL finding.
    old_jti = str(payload.get("jti", ""))
    old_exp = float(payload.get("exp", 0))
    if not old_jti:
        logger.warning(
            "Mode-switch token missing jti claim — refusing downgrade "
            "(cannot revoke a token without an id)",
        )
        return jsonify({
            "status": "error",
            "message": "Token missing jti claim — cannot perform mode downgrade.",
        }), 400

    try:
        _revoke_jti(old_jti, old_exp)
    except Exception:
        logger.exception(
            "Mode-switch revocation failed — refusing downgrade so the frontend "
            "stays in Live and the stale token doesn't go quietly unrevoked | jti=%s",
            old_jti,
        )
        return jsonify({
            "status": "error",
            "message": (
                "Could not revoke previous session token — try again. "
                "Staying in Live mode for safety."
            ),
        }), 503

    # Only AFTER successful revocation do we mint the new Practice token.
    username = str(payload.get("sub") or svc.get_profile().get("username", "user"))
    new_token = _create_token(
        username,
        live_mode_unlocked=False,
        mode="practice",
    )

    return jsonify({
        "status": "success",
        "data": {
            "token": new_token,
            "mode": "practice",
            "live_mode_unlocked": False,
        },
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
@_rate_limit("3 per hour")
def auth_forgot_password() -> tuple[Any, int]:
    """Request a password reset email.

    Always returns 200 to avoid leaking whether the email exists.
    Rate-limited to 3 per hour per client (matches the OTP-reset path).
    A faster cadence here would let an attacker spray emails or
    fingerprint registered addresses via timing.
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
@_rate_limit("5 per minute")
def auth_reset_password() -> tuple[Any, int]:
    """Reset password using a valid reset token.

    Rate-limited to 5 per minute per client to bound brute-force attempts
    against the reset-token namespace. The token itself is signed + has a
    one-hour expiry + is single-use via the JTI blocklist, so this is
    defence-in-depth.
    """
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


# ---------------------------------------------------------------------------
# Email OTP password reset
# ---------------------------------------------------------------------------
#
# Separate from the JWT-token reset above.  Uses a short-lived 6-digit OTP
# stored in memory with a 10-minute TTL.  No DB required.
#
# Endpoints:
#   POST /v1/auth/forgot-password-otp   — generate & send OTP
#   POST /v1/auth/reset-password-otp    — validate OTP + apply new password
#
# Rate limit: max 3 OTP requests per email per hour.
# ---------------------------------------------------------------------------

import random  # noqa: E402 (standard library, safe here)
import smtplib  # noqa: E402
from email.mime.text import MIMEText  # noqa: E402
from email.mime.multipart import MIMEMultipart  # noqa: E402

# {email: [(otp_str, expiry_epoch), ...]}
# Each email can have at most one live OTP; older entries are replaced.
_OTP_STORE: dict[str, dict[str, Any]] = {}

# {email: [epoch, epoch, ...]} — timestamps of OTP issue attempts this hour
_OTP_REQUEST_LOG: dict[str, list[float]] = {}

_OTP_TTL_SECONDS = 600          # 10 minutes
_OTP_MAX_REQUESTS_PER_HOUR = 3  # per email address


def _otp_rate_ok(email: str) -> bool:
    """Check whether ``email`` is within the 3-per-hour OTP request limit.

    Delegates to the persistent :class:`AuthState` store so the cap is
    enforced across gunicorn workers and survives worker restart. Falls
    back to the in-process ``_OTP_REQUEST_LOG`` dict if the DB is not
    available (e.g. during unit tests that run without a writable HOME).

    Args:
        email: The requester's email address used as the rate-limit key.

    Returns:
        ``True`` if the request is permitted; ``False`` if the hourly cap
        has been reached.
    """
    try:
        from .auth_state import get_auth_state  # lazy import

        state = get_auth_state()
        count = state.count_recent_otp_requests(email, window_seconds=3600)
        if count >= _OTP_MAX_REQUESTS_PER_HOUR:
            return False
        state.record_otp_request(email)
        return True
    except Exception as exc:  # noqa: BLE001
        logger.debug("OTP rate-limit DB unavailable, falling back in-process: %s", exc)
        now = time.monotonic()
        cutoff = now - 3600
        log = _OTP_REQUEST_LOG.get(email, [])
        log = [t for t in log if t > cutoff]
        if len(log) >= _OTP_MAX_REQUESTS_PER_HOUR:
            return False
        log.append(now)
        _OTP_REQUEST_LOG[email] = log
        return True


def _generate_otp() -> str:
    """Generate a cryptographically random 6-digit OTP string.

    Returns:
        Zero-padded 6-digit string, e.g. ``"042731"``.
    """
    return f"{random.SystemRandom().randint(0, 999999):06d}"


def _store_otp(email: str, otp: str) -> None:
    """Persist an OTP for ``email`` with a TTL of 10 minutes.

    Replaces any existing OTP for the same address so there is always at
    most one live entry per email.

    Args:
        email: The recipient's email address.
        otp: The 6-digit OTP string to store.
    """
    _OTP_STORE[email] = {
        "otp": otp,
        "expiry": time.monotonic() + _OTP_TTL_SECONDS,
    }


def _verify_and_consume_otp(email: str, otp: str) -> bool:
    """Verify ``otp`` for ``email`` and remove it from the store if valid.

    An OTP is considered invalid if it does not match, has expired, or there
    is no entry for the given email address.  Expired entries are cleaned up
    regardless of the ``otp`` value supplied.

    Args:
        email: The requester's email address.
        otp: The 6-digit code supplied by the user.

    Returns:
        ``True`` if the OTP matched and was consumed; ``False`` otherwise.
    """
    entry = _OTP_STORE.get(email)
    if entry is None:
        return False

    if time.monotonic() > entry["expiry"]:
        del _OTP_STORE[email]
        return False

    if entry["otp"] != otp.strip():
        return False

    del _OTP_STORE[email]
    return True


# ---------------------------------------------------------------------------
# EmailTransport
# ---------------------------------------------------------------------------


class EmailTransport:
    """Send OTP emails via SMTP or Amazon SES (boto3).

    Transport is chosen automatically based on available configuration:

    * If ``AWS_SES_REGION`` (or ``AWS_DEFAULT_REGION``) is set *and* boto3
      is importable → use Amazon SES.
    * Otherwise → fall back to SMTP (``SMTP_HOST``, ``SMTP_PORT``,
      ``SMTP_USER``, ``SMTP_PASSWORD``).

    Configuration env vars
    ----------------------
    SMTP_HOST     — SMTP server hostname (default ``localhost``).
    SMTP_PORT     — SMTP port (default ``587``).
    SMTP_USER     — SMTP username / sender address.
    SMTP_PASSWORD — SMTP password.
    SMTP_FROM     — From address (falls back to SMTP_USER).
    AWS_SES_REGION / AWS_DEFAULT_REGION — triggers SES transport.
    """

    def __init__(self) -> None:
        self._smtp_host = os.environ.get("SMTP_HOST", "localhost")
        self._smtp_port = int(os.environ.get("SMTP_PORT", "587"))
        self._smtp_user = os.environ.get("SMTP_USER", "")
        self._smtp_password = os.environ.get("SMTP_PASSWORD", "")
        self._smtp_from = os.environ.get("SMTP_FROM", self._smtp_user)
        self._ses_region = os.environ.get(
            "AWS_SES_REGION", os.environ.get("AWS_DEFAULT_REGION", "")
        )

    def send_otp(self, email: str, otp: str) -> bool:
        """Deliver a 6-digit OTP to ``email``.

        Attempts SES first (if configured), then falls back to SMTP.  Any
        failure is logged and ``False`` is returned so callers can decide
        whether to surface the error to the user.

        Args:
            email: Recipient email address.
            otp: The 6-digit OTP code to include in the message body.

        Returns:
            ``True`` if the email was dispatched without errors; ``False``
            if both transports failed or are not configured.
        """
        subject = "FlintTrade — password reset OTP"
        body = (
            f"Your FlintTrade password reset OTP is: {otp}\n\n"
            f"This code is valid for {_OTP_TTL_SECONDS // 60} minutes.\n"
            "If you did not request a password reset, please ignore this email."
        )

        if self._ses_region:
            success = self._send_ses(email, subject, body)
            if success:
                return True
            logger.warning("SES delivery failed — falling back to SMTP")

        return self._send_smtp(email, subject, body)

    def _send_smtp(self, to: str, subject: str, body: str) -> bool:
        """Send an email via SMTP.

        Args:
            to: Recipient address.
            subject: Email subject line.
            body: Plain-text message body.

        Returns:
            ``True`` on success, ``False`` on any SMTP exception.
        """
        if not self._smtp_host or not self._smtp_from:
            logger.warning("SMTP not configured (missing SMTP_HOST or SMTP_USER/SMTP_FROM)")
            return False

        try:
            msg = MIMEMultipart("alternative")
            msg["Subject"] = subject
            msg["From"] = self._smtp_from
            msg["To"] = to
            msg.attach(MIMEText(body, "plain"))

            with smtplib.SMTP(self._smtp_host, self._smtp_port, timeout=10) as server:
                server.ehlo()
                if self._smtp_port == 587:
                    server.starttls()
                    server.ehlo()
                if self._smtp_user and self._smtp_password:
                    server.login(self._smtp_user, self._smtp_password)
                server.sendmail(self._smtp_from, [to], msg.as_string())

            logger.info("OTP email sent via SMTP to %s", to)
            return True
        except smtplib.SMTPException as exc:
            logger.error("SMTP error sending OTP email to %s: %s", to, exc)
            return False
        except OSError as exc:
            logger.error("Network error sending OTP email to %s: %s", to, exc)
            return False

    def _send_ses(self, to: str, subject: str, body: str) -> bool:
        """Send an email via Amazon SES using boto3.

        Args:
            to: Recipient address.
            subject: Email subject line.
            body: Plain-text message body.

        Returns:
            ``True`` on success, ``False`` if boto3 is unavailable or SES
            raises an exception.
        """
        try:
            import boto3  # type: ignore[import]
        except ImportError:
            logger.debug("boto3 not installed — cannot use SES transport")
            return False

        if not self._smtp_from:
            logger.warning("SES: no From address configured (set SMTP_FROM)")
            return False

        try:
            client = boto3.client("ses", region_name=self._ses_region)
            client.send_email(
                Source=self._smtp_from,
                Destination={"ToAddresses": [to]},
                Message={
                    "Subject": {"Data": subject, "Charset": "UTF-8"},
                    "Body": {"Text": {"Data": body, "Charset": "UTF-8"}},
                },
            )
            logger.info("OTP email sent via SES to %s", to)
            return True
        except Exception as exc:
            logger.error("SES error sending OTP email to %s: %s", to, exc)
            return False


# ---------------------------------------------------------------------------
# Module-level EmailTransport singleton (replaced in tests via injection)
# ---------------------------------------------------------------------------

_email_transport: EmailTransport | None = None


def _get_email_transport() -> EmailTransport:
    """Return the module-level :class:`EmailTransport` singleton.

    Created lazily on first call.  Tests can replace the singleton by
    calling :func:`set_email_transport`.

    Returns:
        The active :class:`EmailTransport` instance.
    """
    global _email_transport  # noqa: PLW0603
    if _email_transport is None:
        _email_transport = EmailTransport()
    return _email_transport


def set_email_transport(transport: EmailTransport) -> None:
    """Inject a custom :class:`EmailTransport` (primarily for testing).

    Args:
        transport: The replacement transport to use.
    """
    global _email_transport  # noqa: PLW0603
    _email_transport = transport


# ---------------------------------------------------------------------------
# OTP password reset endpoints
# ---------------------------------------------------------------------------


@auth_bp.route("/forgot-password-otp", methods=["POST"])
@_rate_limit("5 per minute")
def auth_forgot_password_otp() -> tuple[Any, int]:
    """Request a 6-digit OTP for password reset.

    Accepts an email address, generates a 6-digit OTP valid for 10 minutes,
    and sends it to the registered address.  The response is always HTTP 200
    to avoid leaking whether the address is registered.

    Rate limit: max 3 OTP requests per email per hour.

    Request JSON:
        email (str): The account email address.

    Returns:
        ``{"status": "success", "message": "..."}`` (always 200 when email
        field is present, even if the address is not registered).
    """
    body = request.get_json(silent=True) or {}
    email = str(body.get("email", "")).strip().lower()

    if not email:
        return jsonify({"status": "error", "message": "Email is required."}), 400

    # Enforce per-email hourly rate limit
    if not _otp_rate_ok(email):
        return jsonify({
            "status": "error",
            "message": "Too many OTP requests. Please wait an hour before trying again.",
        }), 429

    # Only generate and send the OTP if the email is registered
    svc = _get_auth_service()
    if svc is not None:
        stored_email = svc.get_email()
        if stored_email and stored_email.lower() == email:
            otp = _generate_otp()
            _store_otp(email, otp)
            transport = _get_email_transport()
            sent = transport.send_otp(email, otp)
            if not sent:
                # Don't reveal the failure to the caller — log it internally.
                logger.error(
                    "Failed to deliver OTP to %s — check email transport config", email
                )

    # Always return success to avoid email-enumeration attacks
    return jsonify({
        "status": "success",
        "message": "If the email is registered, a reset OTP has been sent.",
    }), 200


@auth_bp.route("/reset-password-otp", methods=["POST"])
@_rate_limit("10 per minute")
def auth_reset_password_otp() -> tuple[Any, int]:
    """Reset password using a valid email + OTP pair.

    Validates the OTP (must match and be within the 10-minute TTL), then
    applies the new password via the auth service.  The OTP is consumed
    on first successful use — it cannot be replayed.

    Request JSON:
        email (str): The account email address.
        otp (str): The 6-digit OTP code received by email.
        new_password (str): The desired new password.

    Returns:
        ``{"status": "success", "message": "Password has been reset."}`` on
        success, or an error response on validation failure.
    """
    body = request.get_json(silent=True) or {}
    email = str(body.get("email", "")).strip().lower()
    otp = str(body.get("otp", "")).strip()
    new_password = str(body.get("new_password", ""))

    if not email or not otp or not new_password:
        return jsonify({
            "status": "error",
            "message": "email, otp, and new_password are all required.",
        }), 400

    if not _verify_and_consume_otp(email, otp):
        return jsonify({
            "status": "error",
            "message": "Invalid or expired OTP.",
        }), 400

    svc = _get_auth_service()
    if svc is None:
        return jsonify({"status": "error", "message": "Auth service not available."}), 503

    # Verify the email belongs to the registered account
    stored_email = svc.get_email()
    if not stored_email or stored_email.lower() != email:
        return jsonify({"status": "error", "message": "Email not registered."}), 400

    try:
        profile = svc.get_profile()
        username = profile.get("username", "user")
        result = svc.update_password(username, new_password)
    except ValueError as exc:
        return jsonify({"status": "error", "message": str(exc)}), 400

    if not result:
        return jsonify({"status": "error", "message": "Password update failed."}), 400

    # Invalidate any active session so all open logins are forced to re-auth.
    auth_header = request.headers.get("Authorization", "")
    session_token = auth_header.removeprefix("Bearer ").strip()
    if session_token:
        try:
            sess_payload = jwt.decode(
                session_token, _get_jwt_secret(), algorithms=[_JWT_ALGORITHM]
            )
            sess_jti = sess_payload.get("jti", "")
            sess_exp = float(sess_payload.get("exp", 0))
            if sess_jti:
                _revoke_jti(sess_jti, sess_exp)
        except (jwt.ExpiredSignatureError, jwt.InvalidTokenError):
            pass

    logger.info("Password reset via OTP for email=%s", email)
    return jsonify({"status": "success", "message": "Password has been reset."}), 200
