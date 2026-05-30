"""Sandbox Flask Blueprint — paper trading API endpoints.

All endpoints are mounted under ``/v1/sandbox``.  The
:class:`~flinttrade_data.sandbox_engine.SandboxEngine` instance is
retrieved from ``app.config["DATA_SANDBOX_ENGINE"]`` so it does not
collide with the engine-level sandbox registered under ``SANDBOX_ENGINE``.

Endpoint summary::

    GET  /v1/sandbox/capital          — current virtual capital
    POST /v1/sandbox/capital/adjust   — add or remove capital {amount}
    POST /v1/sandbox/order            — place a paper order
    GET  /v1/sandbox/positions        — open positions
    GET  /v1/sandbox/orders           — today's orders
    GET  /v1/sandbox/pnl              — aggregate P&L
    POST /v1/sandbox/reset            — clear all data (returns backup)
    GET  /v1/sandbox/export           — export as JSON string
    POST /v1/sandbox/import           — import from JSON
"""

from __future__ import annotations

import logging
from typing import Any

from flask import Blueprint, Response, current_app, jsonify, request

logger = logging.getLogger("flinttrade.data.sandbox_routes")

data_sandbox_bp = Blueprint(
    "data_sandbox",
    __name__,
    url_prefix="/v1/sandbox",
)

_CONFIG_KEY = "DATA_SANDBOX_ENGINE"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _get_engine():
    """Retrieve the SandboxEngine from the Flask app config.

    Returns:
        The SandboxEngine instance or None if not configured.
    """
    return current_app.config.get(_CONFIG_KEY)


def _engine_required() -> tuple[Any, Response | None]:
    """Return ``(engine, None)`` or ``(None, error_response)``."""
    engine = _get_engine()
    if engine is None:
        return None, (
            jsonify(
                {
                    "status": "error",
                    "message": (
                        "Data sandbox engine not configured. "
                        f"Set app.config['{_CONFIG_KEY}'] to a SandboxEngine instance."
                    ),
                }
            ),
            503,
        )
    return engine, None


# ---------------------------------------------------------------------------
# Capital
# ---------------------------------------------------------------------------


@data_sandbox_bp.route("/capital", methods=["GET"])
def get_capital() -> Response:
    """Return current virtual capital.

    Returns:
        JSON ``{status, capital: {initial, current, available, used_margin}}``.
    """
    engine, err = _engine_required()
    if err:
        return err

    return jsonify({"status": "success", "data": {"capital": engine.get_capital()}})


@data_sandbox_bp.route("/capital/adjust", methods=["POST"])
def adjust_capital() -> Response:
    """Add or remove virtual capital.

    Request body::

        {"amount": 50000}   # positive = add, negative = remove

    Returns:
        JSON ``{status, capital}`` with updated capital state.
    """
    engine, err = _engine_required()
    if err:
        return err

    body: dict[str, Any] = request.get_json(silent=True) or {}
    amount = body.get("amount")

    if amount is None:
        return jsonify({"status": "error", "message": "'amount' is required"}), 400

    try:
        amount = float(amount)
    except (TypeError, ValueError):
        return jsonify({"status": "error", "message": "'amount' must be a number"}), 400

    try:
        updated = engine.adjust_capital(amount)
    except ValueError as exc:
        return jsonify({"status": "error", "message": str(exc)}), 400

    return jsonify({"status": "success", "data": {"capital": updated}})


# ---------------------------------------------------------------------------
# Orders
# ---------------------------------------------------------------------------


@data_sandbox_bp.route("/order", methods=["POST"])
def place_order() -> Response:
    """Place a paper order.

    Request body::

        {
          "symbol":   "NIFTY",
          "exchange": "NSE_INDEX",
          "action":   "BUY",
          "quantity": 50,
          "price":    24000.0,
          "product":  "MIS"   // optional, default "MIS"
        }

    Returns:
        JSON ``{status, order}`` where ``order`` contains order_id, status, message.
    """
    engine, err = _engine_required()
    if err:
        return err

    body: dict[str, Any] = request.get_json(silent=True) or {}

    symbol = body.get("symbol", "")
    exchange = body.get("exchange", "")
    action = body.get("action", "")
    quantity = body.get("quantity")
    price = body.get("price")
    product = body.get("product", "MIS")

    # Basic presence validation before calling engine
    missing = [f for f, v in [("symbol", symbol), ("exchange", exchange),
                               ("action", action), ("quantity", quantity),
                               ("price", price)] if not v and v != 0]
    if missing:
        return (
            jsonify({
                "status": "error",
                "message": f"Missing required fields: {', '.join(missing)}",
            }),
            400,
        )

    try:
        quantity = int(quantity)
        price = float(price)
    except (TypeError, ValueError):
        return (
            jsonify({"status": "error", "message": "'quantity' must be int, 'price' must be number"}),
            400,
        )

    result = engine.place_order(
        symbol=symbol,
        exchange=exchange,
        action=action,
        quantity=quantity,
        price=price,
        product=product,
    )

    http_status = 200 if result["status"] == "COMPLETE" else 400
    return jsonify({"status": "success", "data": {"order": result}}), http_status


# ---------------------------------------------------------------------------
# Positions
# ---------------------------------------------------------------------------


@data_sandbox_bp.route("/positions", methods=["GET"])
def get_positions() -> Response:
    """Return open sandbox positions.

    Returns:
        JSON ``{status, positions: [...]}``.
    """
    engine, err = _engine_required()
    if err:
        return err

    return jsonify({"status": "success", "data": {"positions": engine.get_positions()}})


# ---------------------------------------------------------------------------
# Orders (today)
# ---------------------------------------------------------------------------


@data_sandbox_bp.route("/orders", methods=["GET"])
def get_orders() -> Response:
    """Return today's sandbox orders.

    Returns:
        JSON ``{status, orders: [...]}``.
    """
    engine, err = _engine_required()
    if err:
        return err

    return jsonify({"status": "success", "data": {"orders": engine.get_orders()}})


# ---------------------------------------------------------------------------
# P&L
# ---------------------------------------------------------------------------


@data_sandbox_bp.route("/pnl", methods=["GET"])
def get_pnl() -> Response:
    """Return aggregate P&L.

    Returns:
        JSON ``{status, pnl: {realised, unrealised, total}}``.
    """
    engine, err = _engine_required()
    if err:
        return err

    return jsonify({"status": "success", "data": {"pnl": engine.get_pnl()}})


# ---------------------------------------------------------------------------
# Reset
# ---------------------------------------------------------------------------


@data_sandbox_bp.route("/reset", methods=["POST"])
def reset_sandbox() -> Response:
    """Reset all sandbox data and return a backup.

    Returns:
        JSON ``{status, message, backup: {capital, positions, orders}}``.
    """
    engine, err = _engine_required()
    if err:
        return err

    backup = engine.reset()
    return jsonify({
        "status": "success",
        "data": {
            "message": "Sandbox reset — all paper trades cleared",
            "backup": backup,
        },
    })


# ---------------------------------------------------------------------------
# Export / Import
# ---------------------------------------------------------------------------


@data_sandbox_bp.route("/export", methods=["GET"])
def export_data() -> Response:
    """Export all sandbox data as a JSON string.

    Returns:
        JSON ``{status, data: "<json string>"}`` where ``data`` is the
        exportable payload that can be POSTed to ``/import``.
    """
    engine, err = _engine_required()
    if err:
        return err

    return jsonify({"status": "success", "data": engine.export_data()})


@data_sandbox_bp.route("/import", methods=["POST"])
def import_data() -> Response:
    """Import sandbox data from a previously exported JSON string.

    Request body::

        {"data": "<json string from /export>"}

    Returns:
        JSON ``{status, stats: {capital_imported, positions_imported, orders_imported}}``.
    """
    engine, err = _engine_required()
    if err:
        return err

    body: dict[str, Any] = request.get_json(silent=True) or {}
    json_str = body.get("data", "")

    if not json_str:
        return jsonify({"status": "error", "message": "'data' field is required"}), 400

    try:
        stats = engine.import_data(json_str)
    except ValueError as exc:
        return jsonify({"status": "error", "message": str(exc)}), 400

    return jsonify({"status": "success", "data": {"stats": stats}})
