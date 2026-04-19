"""OpenAlgo v1 API Compatibility Shims.

Some external clients (TradingView webhooks, ChartInk integrations, older
FlintTrade releases) still call v1-era URL paths and send v1-era payloads.
FlintTrade targets OpenAlgo v2 internally.  This module bridges the gap
without touching the OpenAlgo submodule.

What is translated
------------------
1. **URL paths** — several endpoints were renamed in v2:
   ``/api/v1/orderbook`` → ``/api/v1/orders``, etc.

2. **Request payload keys** — ``action`` (v1) → ``transaction_type`` (v2).

3. **Response shapes** — v1 responses were wrapped in a top-level ``data``
   key; v2 returns the payload directly.  The compat layer unwraps v2
   responses so callers expecting v1 shape see ``{"data": {...}}``.

Flask integration
-----------------
Call :func:`register_v1_compat` once during app factory to attach
``before_request`` / ``after_request`` hooks::

    from packages.core.src.v1_compat import register_v1_compat
    register_v1_compat(app)

The hooks only activate for paths listed in :attr:`V1CompatLayer.V1_TO_V2_ROUTES`.
All other requests pass through unchanged.

Standalone usage
----------------
The :class:`V1CompatLayer` class can also be used without Flask::

    compat = V1CompatLayer()
    v2_path, v2_body = compat.translate_request("/api/v1/orderbook", {"apikey": "…"})
    v1_response = compat.translate_response("/api/v1/orderbook", v2_data)
"""

from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger("flinttrade.core.v1_compat")

# ---------------------------------------------------------------------------
# Payload-key translations (v1 key → v2 key)
# ---------------------------------------------------------------------------

# Order payload: only "action" needs renaming
_V1_TO_V2_PAYLOAD_KEYS: dict[str, str] = {
    "action": "transaction_type",
}

# Some v1 action *values* differ from v2 transaction_type values.
# Map them here (values are already uppercase in v2).
_V1_ACTION_VALUES: dict[str, str] = {
    "buy": "BUY",
    "sell": "SELL",
    "BUY": "BUY",
    "SELL": "SELL",
}


class V1CompatLayer:
    """Translate OpenAlgo v1 API calls to v2 internally.

    Handles:
    - Different URL paths (e.g. ``/api/v1/orderbook`` → ``/api/v1/orders``)
    - Different payload shapes (``action`` → ``transaction_type``)
    - Different response shapes (wrapped ``data`` key vs direct payload)

    All methods are stateless; the same instance can be used concurrently.
    """

    #: Mapping of v1 path → v2 path for all known renamed endpoints.
    V1_TO_V2_ROUTES: dict[str, str] = {
        # Account / read-only
        "/api/v1/orderbook": "/api/v1/orders",
        "/api/v1/positionbook": "/api/v1/positions",
        "/api/v1/tradebook": "/api/v1/trades",
        "/api/v1/holdings": "/api/v1/holdings",  # unchanged but listed for completeness
        "/api/v1/funds": "/api/v1/funds",
        # Order actions (v1 used different sub-paths)
        "/api/v1/placeorder": "/api/v1/placeorder",
        "/api/v1/modifyorder": "/api/v1/modifyorder",
        "/api/v1/cancelorder": "/api/v1/cancelorder",
        "/api/v1/cancelallorder": "/api/v1/cancelallorder",
        "/api/v1/closeposition": "/api/v1/closeposition",
        # Market data
        "/api/v1/quotes": "/api/v1/quotes",
        "/api/v1/history": "/api/v1/history",
        "/api/v1/depth": "/api/v1/depth",
        "/api/v1/optionchain": "/api/v1/optionchain",
        # Utilities
        "/api/v1/orderstatus": "/api/v1/orderstatus",
    }

    #: Paths for which v1 clients expect the response wrapped in ``{"data": …}``.
    #: These are the endpoints that v2 returns unwrapped.
    _WRAP_RESPONSE_PATHS: frozenset[str] = frozenset(
        {
            "/api/v1/orderbook",
            "/api/v1/positionbook",
            "/api/v1/tradebook",
            "/api/v1/holdings",
            "/api/v1/funds",
        }
    )

    def translate_request(self, v1_path: str, v1_body: dict[str, Any]) -> tuple[str, dict[str, Any]]:
        """Translate a v1 path and body to their v2 equivalents.

        Args:
            v1_path: The v1 endpoint path (e.g. ``"/api/v1/orderbook"``).
            v1_body: The request body dict sent by the v1 client.

        Returns:
            A tuple ``(v2_path, v2_body)`` where both values are safe to
            forward to the OpenAlgo v2 API.  If the path is not in
            :attr:`V1_TO_V2_ROUTES` the inputs are returned unchanged.
        """
        v2_path = self.V1_TO_V2_ROUTES.get(v1_path, v1_path)
        v2_body = self._translate_payload(v1_body)

        if v2_path != v1_path:
            logger.debug(
                "[v1-compat] path %s → %s (client used deprecated v1 path)",
                v1_path,
                v2_path,
            )

        return v2_path, v2_body

    def translate_response(self, v1_path: str, v2_response: dict[str, Any]) -> dict[str, Any]:
        """Convert a v2 response shape to what a v1 client expects.

        v1 clients expect read-only endpoints (orderbook, positionbook, etc.)
        to return ``{"status": "success", "data": <payload>}``.  v2 returns
        the payload directly without a ``data`` wrapper.

        This method wraps the response for paths in :attr:`_WRAP_RESPONSE_PATHS`
        **if** it is not already wrapped.

        Args:
            v1_path: The original v1 path the client called.
            v2_response: The response dict returned by the v2 API.

        Returns:
            The response dict in v1 shape.
        """
        if v1_path not in self._WRAP_RESPONSE_PATHS:
            return v2_response

        # Already wrapped — nothing to do
        if "data" in v2_response:
            return v2_response

        return {
            "status": v2_response.get("status", "success"),
            "data": v2_response,
        }

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _translate_payload(self, body: dict[str, Any]) -> dict[str, Any]:
        """Rename v1 payload keys to their v2 equivalents.

        Currently handles:
        - ``action`` → ``transaction_type`` (with value normalisation to
          uppercase ``BUY`` / ``SELL``).

        Args:
            body: v1 request body.

        Returns:
            Translated body dict.  A shallow copy is made; the original
            dict is not mutated.
        """
        translated = dict(body)

        if "action" in translated:
            raw_value = translated.pop("action")
            translated["transaction_type"] = _V1_ACTION_VALUES.get(
                str(raw_value), str(raw_value).upper()
            )
            logger.debug(
                "[v1-compat] payload key 'action' → 'transaction_type' (value=%r → %r)",
                raw_value,
                translated["transaction_type"],
            )

        return translated

    def is_v1_path(self, path: str) -> bool:
        """Return ``True`` if *path* is a known v1 endpoint.

        Args:
            path: HTTP request path to check.

        Returns:
            ``True`` when the path appears in :attr:`V1_TO_V2_ROUTES`.
        """
        return path in self.V1_TO_V2_ROUTES

    def deprecated_paths(self) -> list[str]:
        """Return all v1 paths that map to a *different* v2 path.

        Paths that are identical in both versions are excluded.

        Returns:
            Sorted list of renamed v1 paths.
        """
        return sorted(
            v1 for v1, v2 in self.V1_TO_V2_ROUTES.items() if v1 != v2
        )


# ---------------------------------------------------------------------------
# Flask middleware
# ---------------------------------------------------------------------------


def register_v1_compat(app: Any) -> None:  # noqa: ANN401 — Flask app type varies
    """Register before/after request hooks for v1 API compatibility.

    Attaches a :class:`V1CompatLayer` to ``app.config["V1_COMPAT"]`` and
    registers:

    - ``before_request``: rewrites ``request.path`` and mutates the parsed
      JSON body for v1 paths.
    - ``after_request``: wraps response JSON for v1 read-only endpoints.

    A ``X-FlintTrade-Compat: v1`` header is appended to translated responses
    so clients and logs can identify compat traffic.

    Args:
        app: Flask application instance.

    Note:
        Flask's ``request.path`` is read-only; the path rewrite works by
        storing the translated path and body on ``flask.g`` for downstream
        route handlers that opt-in by reading ``g.v1_compat_path`` and
        ``g.v1_compat_body``.  The route handlers themselves must be aware
        of the compat layer or the request must be proxied internally.
        For a pure-proxy setup, use the compat layer at the reverse-proxy
        level instead.
    """
    try:
        from flask import g, request, after_this_request  # type: ignore[import]
    except ImportError:  # pragma: no cover
        logger.warning("Flask not available — v1 compat middleware not registered")
        return

    compat = V1CompatLayer()
    app.config["V1_COMPAT"] = compat

    @app.before_request  # type: ignore[misc]
    def _v1_before() -> None:
        """Translate v1 path and body, storing on Flask g for route handlers."""
        if not compat.is_v1_path(request.path):
            return

        body: dict[str, Any] = {}
        if request.is_json and request.content_length and request.content_length > 0:
            try:
                body = request.get_json(silent=True) or {}
            except Exception:  # noqa: BLE001
                body = {}

        v2_path, v2_body = compat.translate_request(request.path, body)

        g.v1_original_path = request.path
        g.v1_compat_path = v2_path
        g.v1_compat_body = v2_body
        g.v1_compat_active = True

        logger.info(
            "[v1-compat] deprecated path called: %s (translated → %s)",
            request.path,
            v2_path,
        )

    @app.after_request  # type: ignore[misc]
    def _v1_after(response: Any) -> Any:
        """Wrap response for v1 clients when compat was active."""
        from flask import g  # type: ignore[import]

        if not getattr(g, "v1_compat_active", False):
            return response

        response.headers["X-FlintTrade-Compat"] = "v1"

        # Attempt response body translation for JSON responses
        if response.is_json:
            try:
                v2_data = response.get_json(silent=True) or {}
                original_path = getattr(g, "v1_original_path", "")
                v1_data = compat.translate_response(original_path, v2_data)
                if v1_data is not v2_data:
                    import json as _json

                    response.data = _json.dumps(v1_data).encode("utf-8")
                    response.content_type = "application/json"
            except Exception:  # noqa: BLE001
                logger.exception("[v1-compat] failed to translate response body")

        return response

    logger.info("v1 compatibility middleware registered on Flask app")
