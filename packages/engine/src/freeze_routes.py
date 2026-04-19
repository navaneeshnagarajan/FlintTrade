# packages/engine/src/freeze_routes.py
"""Admin API routes for Quantity Freeze management.

Blueprint: ``/v1/admin/freeze``

Endpoints::

    GET  /v1/admin/freeze            — list all configured freeze limits
    POST /v1/admin/freeze            — create or update a freeze limit
    GET  /v1/admin/freeze/blocks     — recent orders blocked by freeze manager

This blueprint is registered by the core app factory alongside the existing
admin blueprint.  It expects a :class:`~packages.engine.src.qty_freeze.QuantityFreezeManager`
instance to be stored on ``current_app.freeze_manager``.  If not set, all
endpoints return 503.
"""

from __future__ import annotations

import logging

from flask import Blueprint, Response, current_app, jsonify, request

logger = logging.getLogger("flinttrade.engine.freeze_routes")

freeze_bp = Blueprint("freeze", __name__, url_prefix="/v1/admin/freeze")


def _get_manager():
    """Retrieve the QuantityFreezeManager from the Flask app context.

    Returns:
        The freeze manager instance, or ``None`` if not configured.
    """
    return getattr(current_app, "freeze_manager", None)


@freeze_bp.route("", methods=["GET"])
def list_limits() -> tuple[Response, int]:
    """Return all configured quantity freeze limits.

    Returns:
        JSON with ``status`` and ``data.limits`` list.
        503 if the freeze manager is not configured.
    """
    manager = _get_manager()
    if manager is None:
        return jsonify({"status": "error", "message": "Freeze manager not configured"}), 503

    limits = manager.all_limits()
    return jsonify({
        "status": "success",
        "data": {
            "limits": limits,
            "count": len(limits),
        },
    }), 200


@freeze_bp.route("", methods=["POST"])
def set_limit() -> tuple[Response, int]:
    """Create or update a quantity freeze limit.

    Request body (JSON)::

        {
            "symbol":   "NIFTY",
            "exchange": "NFO",
            "max_qty":  1800
        }

    Returns:
        JSON with ``status`` and confirmation message.
        400 on missing or invalid fields.
        503 if the freeze manager is not configured.
    """
    manager = _get_manager()
    if manager is None:
        return jsonify({"status": "error", "message": "Freeze manager not configured"}), 503

    body = request.get_json(silent=True) or {}
    symbol: str = str(body.get("symbol", "")).strip().upper()
    exchange: str = str(body.get("exchange", "")).strip().upper()
    max_qty_raw = body.get("max_qty")

    if not symbol:
        return jsonify({"status": "error", "message": "symbol is required"}), 400
    if not exchange:
        return jsonify({"status": "error", "message": "exchange is required"}), 400
    if max_qty_raw is None:
        return jsonify({"status": "error", "message": "max_qty is required"}), 400

    try:
        max_qty = int(max_qty_raw)
    except (TypeError, ValueError):
        return jsonify({"status": "error", "message": "max_qty must be an integer"}), 400

    try:
        manager.set_limit(symbol, exchange, max_qty)
    except ValueError as exc:
        return jsonify({"status": "error", "message": str(exc)}), 400

    logger.info("Freeze limit updated via API: %s/%s → %d", symbol, exchange, max_qty)
    return jsonify({
        "status": "success",
        "data": {
            "symbol": symbol,
            "exchange": exchange,
            "max_qty": max_qty,
        },
    }), 200


@freeze_bp.route("/blocks", methods=["GET"])
def recent_blocks() -> tuple[Response, int]:
    """Return orders recently blocked by the freeze manager.

    Query parameters:
        limit (int, default 50): Maximum records to return.

    Returns:
        JSON with ``status`` and ``data.blocks`` list.
        503 if the freeze manager is not configured.
    """
    manager = _get_manager()
    if manager is None:
        return jsonify({"status": "error", "message": "Freeze manager not configured"}), 503

    try:
        limit = int(request.args.get("limit", 50))
        limit = max(1, min(limit, 500))  # clamp 1..500
    except (TypeError, ValueError):
        limit = 50

    blocks = manager.recent_blocks(limit=limit)
    return jsonify({
        "status": "success",
        "data": {
            "blocks": blocks,
            "count": len(blocks),
        },
    }), 200
