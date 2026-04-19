"""Bracket order Flask Blueprint — POST/GET/DELETE for bracket orders.

All endpoints live under ``/api/v1/orders/`` and delegate to a
:class:`~packages.engine.src.bracket_order.BracketOrderService` instance
stored on ``app.config["BRACKET_SERVICE"]``.
"""

from __future__ import annotations

import logging
from typing import Any

from flask import Blueprint, Response, current_app, jsonify, request

from packages.core.src.rate_limiter import rate_limit

from .mode_guard import require_non_explore

logger = logging.getLogger("flinttrade.engine.bracket_routes")

bracket_bp = Blueprint("brackets", __name__, url_prefix="/api/v1/orders")


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _get_service():
    """Retrieve the BracketOrderService from the Flask app config."""
    return current_app.config.get("BRACKET_SERVICE")


def _service_required() -> tuple[Any, Response | None]:
    """Return (service, None) or (None, error_response)."""
    svc = _get_service()
    if svc is None:
        return None, (
            jsonify({"status": "error", "message": "Bracket service not configured"}),
            503,
        )
    return svc, None


# ---------------------------------------------------------------------------
# POST /api/v1/orders/bracket  — place bracket order
# ---------------------------------------------------------------------------


@bracket_bp.route("/bracket", methods=["POST"])
@require_non_explore
@rate_limit("orders", user_rate=10, global_rate=100)
def place_bracket() -> Response:
    """Place a bracket order (entry + SL + target).

    Request body (JSON):

    .. code-block:: json

        {
            "entry": {
                "symbol": "NIFTY25APRFUT",
                "exchange": "NFO",
                "action": "BUY",
                "quantity": 50,
                "price": 0,
                "strategy": "Flint",
                "product": "MIS"
            },
            "stoploss": 22000.0,
            "target": 22500.0,
            "trailing_sl": null
        }

    Returns:
        201 with bracket details on success, or 4xx/503 on failure.
    """
    svc, err = _service_required()
    if err:
        return err

    body: dict[str, Any] = request.get_json(silent=True) or {}

    entry = body.get("entry")
    if not entry or not isinstance(entry, dict):
        return jsonify({"status": "error", "message": "'entry' object is required"}), 400

    try:
        stoploss = float(body["stoploss"])
        target = float(body["target"])
    except (KeyError, TypeError, ValueError):
        return jsonify(
            {"status": "error", "message": "'stoploss' and 'target' are required numbers"}
        ), 400

    trailing_sl_raw = body.get("trailing_sl")
    trailing_sl: float | None = None
    if trailing_sl_raw is not None:
        try:
            trailing_sl = float(trailing_sl_raw)
        except (TypeError, ValueError):
            return jsonify(
                {"status": "error", "message": "'trailing_sl' must be a number"}
            ), 400

    result = svc.place_bracket(entry, stoploss, target, trailing_sl)

    if not result.success:
        return (
            jsonify(
                {
                    "status": "error",
                    "message": result.message,
                    "error": result.error,
                }
            ),
            422,
        )

    return (
        jsonify(
            {
                "status": "success",
                "message": result.message,
                "data": result.bracket.to_dict() if result.bracket else None,
            }
        ),
        201,
    )


# ---------------------------------------------------------------------------
# GET /api/v1/orders/brackets  — list active brackets
# ---------------------------------------------------------------------------


@bracket_bp.route("/brackets", methods=["GET"])
def list_brackets() -> Response:
    """List all active (non-completed, non-cancelled) bracket orders.

    Returns:
        JSON with ``data.brackets`` list.
    """
    svc, err = _service_required()
    if err:
        return err

    brackets = svc.get_active_brackets()
    return jsonify(
        {
            "status": "success",
            "data": {
                "count": len(brackets),
                "brackets": [b.to_dict() for b in brackets],
            },
        }
    )


# ---------------------------------------------------------------------------
# DELETE /api/v1/orders/bracket/<id>  — cancel bracket
# ---------------------------------------------------------------------------


@bracket_bp.route("/bracket/<bracket_id>", methods=["DELETE"])
def cancel_bracket(bracket_id: str) -> Response:
    """Cancel all pending legs of a bracket order.

    Args:
        bracket_id: UUID of the bracket to cancel.

    Returns:
        JSON confirmation or 404 if not found.
    """
    svc, err = _service_required()
    if err:
        return err

    # Check existence first for a clean 404
    bracket = svc.get_bracket(bracket_id)
    if bracket is None:
        return jsonify({"status": "error", "message": f"Bracket '{bracket_id}' not found"}), 404

    cancelled = svc.cancel_bracket(bracket_id)
    if not cancelled:
        return (
            jsonify(
                {
                    "status": "error",
                    "message": (
                        f"Bracket '{bracket_id}' could not be cancelled — "
                        "it may already be completed or cancelled"
                    ),
                }
            ),
            409,
        )

    return jsonify(
        {
            "status": "success",
            "message": f"Bracket '{bracket_id}' cancelled",
        }
    )
