"""Server-side mode enforcement guard for engine order routes.

Every endpoint in ``engine`` that can place real orders (basket, split,
options-strategy, bracket, strategy start/stop) must consult the JWT's
``mode`` claim before executing. This module exposes:

- :func:`require_non_explore` — decorator that returns HTTP 403 when the
  caller's JWT claims ``mode == "explore"``. No token = treated as explore
  (reject). Practice and live both pass.

The mode claim is set at login/PIN-verify time and signed by the server's
JWT secret, so it cannot be forged by the frontend. This layer sits
alongside the ``core.order_routes`` mode-routing logic and gives engine
endpoints the same safety posture.
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


def _extract_mode() -> str | None:
    """Return the ``mode`` claim from the request JWT, or ``None`` if absent/invalid."""
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


def current_mode() -> str | None:
    """Public accessor — returns the current JWT mode or ``None``."""
    return _extract_mode()
