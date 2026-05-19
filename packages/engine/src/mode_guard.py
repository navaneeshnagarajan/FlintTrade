"""Server-side mode enforcement guard for engine order routes.

Every endpoint in ``engine`` that can place real orders (basket, split,
options-strategy, bracket, strategy start/stop) must consult the JWT's
``mode`` claim before executing. This module exposes:

- :func:`require_non_explore` — decorator that returns HTTP 403 when the
  caller's JWT claims ``mode == "explore"``. No token = treated as explore
  (reject). Practice and live both pass. Suitable for endpoints whose
  downstream order placement is itself mode-aware (e.g. strategy lifecycle
  routes whose orders flow back through ``orders_bp``).

- :func:`require_live_unlocked` — stricter decorator for endpoints whose
  executors (BasketOrderExecutor, SplitOrderExecutor, BracketOrderService,
  OptionsStrategyBuilder) call OpenAlgo *directly*, bypassing the
  mode-aware ``core.order_routes`` safety proxy. Rejects explore (no
  orders ever), rejects practice (no sandbox executor parity yet) and
  rejects live without the ``live_mode_unlocked`` JWT claim (PIN re-verify
  required).

The mode claim is set at login/PIN-verify time and signed by the server's
JWT secret, so it cannot be forged by the frontend. This layer mirrors
:func:`packages.core.src.order_routes._dispatch_order` so engine routes
share its safety posture instead of holding only a partial check.
"""

from __future__ import annotations

import functools
import logging
from collections.abc import Callable
from typing import Any

import jwt
from flask import Response, current_app, jsonify, request

logger = logging.getLogger("flinttrade.engine.mode_guard")

_MODE_EXPLORE = "explore"
_MODE_PRACTICE = "practice"
_MODE_LIVE = "live"


def _decode_payload() -> dict[str, Any] | None:
    """Decode the Bearer JWT (or ``X-FlintTrade-Token`` fallback) into a payload dict.

    Returns:
        The JWT payload, or ``None`` if the token is absent, expired, or invalid.
    """
    from packages.core.src.auth_routes import decode_token  # lazy to avoid import cycle

    auth_header = request.headers.get("Authorization", "")
    token = auth_header.removeprefix("Bearer ").strip()
    if not token:
        token = request.headers.get("X-FlintTrade-Token", "").strip()
    if not token:
        return None
    try:
        payload = decode_token(token)
    except (jwt.ExpiredSignatureError, jwt.InvalidTokenError):
        return None
    return payload if isinstance(payload, dict) else None


def _extract_mode() -> str | None:
    """Return the ``mode`` claim from the request JWT, or ``None`` if absent/invalid."""
    payload = _decode_payload()
    if payload is None:
        return None
    value = payload.get("mode")
    return value if isinstance(value, str) else None


def require_non_explore(view: Callable[..., Any]) -> Callable[..., Any]:
    """Flask view decorator — reject explore-mode callers with HTTP 403.

    Missing/invalid JWTs are also rejected. Routes wrapped with this
    decorator still fire for ``practice`` and ``live`` modes; further
    routing (sandbox vs live broker) is the view's responsibility.
    """

    @functools.wraps(view)
    def wrapper(*args: Any, **kwargs: Any) -> Response | tuple[Response, int]:
        # Bypass in Flask test mode so unit tests can exercise the handler
        # without minting JWTs. Production requests never see TESTING=True.
        if current_app.config.get("TESTING"):
            return view(*args, **kwargs)
        mode = _extract_mode()
        if mode is None or mode == _MODE_EXPLORE:
            logger.info(
                "Blocked order request on %s (mode=%s)", request.path, mode or "unknown",
            )
            return (
                jsonify(
                    {
                        "status": "error",
                        "message": "Order placement disabled in Explore mode.",
                        "code": "mode_blocked",
                    }
                ),
                403,
            )
        return view(*args, **kwargs)

    return wrapper


def require_live_unlocked(view: Callable[..., Any]) -> Callable[..., Any]:
    """Flask view decorator — full mode-safety stack for routes that bypass ``orders_bp``.

    Used by endpoints (basket, split, options-strategy, bracket) whose
    executors place orders against OpenAlgo *directly* — i.e. they do not
    re-enter the mode-aware ``core.order_routes`` proxy, so the proxy's
    explore/practice/live fan-out doesn't protect them. This decorator
    reproduces the equivalent of
    :func:`packages.core.src.order_routes._dispatch_order` at the route
    boundary:

    - **explore** → HTTP 403, ``code="mode_blocked"``
    - **practice** → HTTP 403, ``code="practice_unsupported"`` — these
      executors don't yet have a sandbox counterpart, so paper-trading is
      refused rather than silently routed to the broker
    - **live** without ``live_mode_unlocked`` JWT claim → HTTP 403,
      ``code="live_locked"`` (PIN re-verify required)
    - **live** with ``live_mode_unlocked`` → wrapped view executes
    - missing/invalid JWT → HTTP 401, ``code="auth_required"``
    - unknown mode value → HTTP 400, ``code="mode_invalid"``

    Bypassed when ``current_app.config["TESTING"] == True`` so unit tests
    can exercise the handler without minting full JWTs.
    """

    @functools.wraps(view)
    def wrapper(*args: Any, **kwargs: Any) -> Response | tuple[Response, int]:
        if current_app.config.get("TESTING"):
            return view(*args, **kwargs)

        payload = _decode_payload()
        if payload is None:
            logger.info(
                "Order request rejected on %s — missing/invalid JWT", request.path,
            )
            return (
                jsonify(
                    {
                        "status": "error",
                        "message": (
                            "Authentication required — provide a valid JWT with a mode claim."
                        ),
                        "code": "auth_required",
                    }
                ),
                401,
            )

        mode_raw = payload.get("mode")
        mode = mode_raw if isinstance(mode_raw, str) else None

        if mode == _MODE_EXPLORE:
            logger.info("Blocked order request on %s (mode=explore)", request.path)
            return (
                jsonify(
                    {
                        "status": "error",
                        "message": "Order placement disabled in Explore mode.",
                        "code": "mode_blocked",
                    }
                ),
                403,
            )

        if mode == _MODE_PRACTICE:
            logger.info(
                "Blocked advanced order on %s — practice mode not supported for "
                "executor-direct routes (basket/split/options-strategy/bracket)",
                request.path,
            )
            return (
                jsonify(
                    {
                        "status": "error",
                        "message": (
                            "Advanced orders (basket, split, options-strategy, bracket) "
                            "are not yet available in Practice mode. Switch to Live with "
                            "PIN verified, or use single-leg orders which support practice."
                        ),
                        "code": "practice_unsupported",
                    }
                ),
                403,
            )

        if mode == _MODE_LIVE:
            if not bool(payload.get("live_mode_unlocked")):
                logger.warning(
                    "Live advanced order rejected on %s — JWT does not contain "
                    "live_mode_unlocked claim", request.path,
                )
                return (
                    jsonify(
                        {
                            "status": "error",
                            "message": "Live mode not unlocked — verify PIN first.",
                            "code": "live_locked",
                        }
                    ),
                    403,
                )
            return view(*args, **kwargs)

        logger.warning(
            "Order request on %s has invalid/unknown mode '%s'", request.path, mode,
        )
        return (
            jsonify(
                {
                    "status": "error",
                    "message": (
                        f"Invalid mode '{mode}' in JWT claim. "
                        "Expected one of: explore, practice, live."
                    ),
                    "code": "mode_invalid",
                }
            ),
            400,
        )

    return wrapper


def current_mode() -> str | None:
    """Public accessor — returns the current JWT mode or ``None``.

    Returns ``None`` for missing or invalid JWTs (auth-failed), not
    ``"explore"`` — callers using this for routing decisions must
    distinguish these cases themselves. (``require_non_explore`` and
    ``require_live_unlocked`` both treat ``None`` as failure, but with
    different HTTP status codes — 403 vs 401.)
    """
    return _extract_mode()
