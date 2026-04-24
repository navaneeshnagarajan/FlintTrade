"""Flask blueprint for pivot point calculation endpoint.

External URL (frontend calls this via /ft-api/v1/pivots/*; the WSGI prefix
stripper in app.py rewrites to /v1/pivots/* before Flask dispatch):

    POST /ft-api/v1/pivots/calculate
        Body: { "high": float, "low": float, "close": float, "open": float? }
        Returns pivot levels for all five methods.

Blueprint registered at ``/v1/pivots`` (post-strip form).

Response shape::

    {
        "status": "success",
        "data": {
            "input": { "high": 18500, "low": 18200, "close": 18400, "open": null },
            "methods": {
                "standard":   { "method": "standard",   "pivot": ..., "r1": ..., ... },
                "fibonacci":  { ... },
                "woodie":     { ... },
                "camarilla":  { ... },
                "demark":     { ... }
            }
        }
    }
"""

from __future__ import annotations

import logging
from typing import Any

from flask import Blueprint, jsonify, request

logger = logging.getLogger("flinttrade.screener.pivot_routes")

pivot_bp = Blueprint("pivots", __name__, url_prefix="/v1/pivots")


@pivot_bp.route("/calculate", methods=["POST"])
def calculate_pivots() -> tuple[Any, int]:
    """Calculate pivot levels for all five methods from a single OHLC input.

    Request body (JSON):
        high (float): Session high price (required).
        low (float): Session low price (required).
        close (float): Session close price (required).
        open (float): Session open price (optional; used by DeMark method).

    Returns:
        JSON with pivot levels for all five methods::

            {
                "status": "success",
                "data": {
                    "input": { "high": 18500, "low": 18200, "close": 18400, "open": null },
                    "methods": {
                        "standard":  { "method": "standard", "pivot": 18366.67, ... },
                        "fibonacci": { ... },
                        "woodie":    { ... },
                        "camarilla": { ... },
                        "demark":    { ... }
                    }
                }
            }

        On validation error returns HTTP 400::

            { "status": "error", "message": "..." }
    """
    payload: dict[str, Any] = request.get_json(silent=True) or {}

    # --- Extract and validate required fields ---
    missing = [f for f in ("high", "low", "close") if f not in payload]
    if missing:
        return (
            jsonify({
                "status": "error",
                "message": f"Missing required field(s): {', '.join(missing)}",
            }),
            400,
        )

    try:
        high = float(payload["high"])
        low = float(payload["low"])
        close = float(payload["close"])
        open_price: float | None = (
            float(payload["open"]) if "open" in payload and payload["open"] is not None
            else None
        )
    except (TypeError, ValueError) as exc:
        return (
            jsonify({"status": "error", "message": f"Invalid numeric value: {exc}"}),
            400,
        )

    # --- Delegate to calculator ---
    from .pivot_calculator import PivotCalculator  # noqa: PLC0415

    try:
        all_levels = PivotCalculator.all_methods(
            high=high, low=low, close=close, open_price=open_price
        )
    except ValueError as exc:
        return jsonify({"status": "error", "message": str(exc)}), 400

    return (
        jsonify({
            "status": "success",
            "data": {
                "input": {
                    "high": high,
                    "low": low,
                    "close": close,
                    "open": open_price,
                },
                "methods": {name: levels.to_dict() for name, levels in all_levels.items()},
            },
        }),
        200,
    )
