"""Sandbox Flask Blueprint — paper trading API endpoints.

All endpoints are mounted under ``/v1/sandbox``.  The
:class:`~flinttrade_data.sandbox_engine.SandboxEngine` instance is
retrieved from ``app.config["DATA_SANDBOX_ENGINE"]``.

Endpoint summary::

    GET  /v1/sandbox/capital          — current virtual capital
    GET  /v1/sandbox/funds            — legacy-compatible funds summary
    GET  /v1/sandbox/config           — leverage and square-off policy
    POST /v1/sandbox/config           — update sandbox policy
    POST /v1/sandbox/capital/adjust   — add or remove capital {amount}
    POST /v1/sandbox/order            — place a paper order
    GET  /v1/sandbox/positions        — open positions
    GET  /v1/sandbox/orders           — today's orders
    GET  /v1/sandbox/trades           — executed trades
    GET  /v1/sandbox/pnl              — aggregate P&L
    GET  /v1/sandbox/pnl/history      — daily P&L history
    POST /v1/sandbox/square-off       — close all positions at supplied LTPs
    POST /v1/sandbox/reset            — clear all data (returns backup)
    GET  /v1/sandbox/export           — export as JSON string
    POST /v1/sandbox/import           — import from JSON
"""

from __future__ import annotations

import logging
from dataclasses import asdict
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
# Config
# ---------------------------------------------------------------------------


@data_sandbox_bp.route("/config", methods=["GET"])
def get_config() -> Response:
    """Return the persisted Practice account configuration."""
    engine, err = _engine_required()
    if err:
        return err
    return jsonify({"status": "success", "data": {"config": asdict(engine.config)}})


@data_sandbox_bp.route("/config", methods=["POST"])
def update_config() -> Response:
    """Validate and persist selected Practice configuration fields."""
    engine, err = _engine_required()
    if err:
        return err
    body: dict[str, Any] = request.get_json(silent=True) or {}
    try:
        updated = engine.update_config(**body)
    except (TypeError, ValueError):
        return jsonify({"status": "error", "message": "Invalid request"}), 400
    return jsonify({"status": "success", "data": {"config": asdict(updated)}})


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


@data_sandbox_bp.route("/funds", methods=["GET"])
def get_funds() -> Response:
    """Return the canonical account in the retired engine's funds shape."""
    engine, err = _engine_required()
    if err:
        return err

    return jsonify({"status": "success", "data": {"funds": engine.get_funds()}})


@data_sandbox_bp.route("/status", methods=["GET"])
def get_status() -> Response:
    """Combined sandbox status for the terminal's virtual-capital panel.

    The terminal SandboxControls panel reads a flat status shape (capital as a
    single current-balance number) rather than the nested ``/capital`` payload.
    Provide it in one round-trip so the panel does not 404 on a missing route.

    Returns:
        JSON ``{status, data: {capital, initial_capital, pnl, trades_count}}``.
    """
    engine, err = _engine_required()
    if err:
        return err

    capital = engine.get_capital()
    pnl = engine.get_pnl()
    try:
        trades_count = len(engine.get_trades())
    except Exception:  # pragma: no cover - defensive
        trades_count = 0

    return jsonify({
        "status": "success",
        "data": {
            "capital": capital.get("current", 0.0),
            "initial_capital": capital.get("initial", 0.0),
            "pnl": pnl.get("total", 0.0),
            "trades_count": trades_count,
        },
    })


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
    except ValueError:
        return jsonify({"status": "error", "message": "Invalid request"}), 400

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
    order_type = body.get("order_type", body.get("pricetype", "MARKET"))
    trigger_price = body.get("trigger_price", 0.0)
    strategy = body.get("strategy", "")

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
        trigger_price = float(trigger_price)
    except (TypeError, ValueError):
        return (
            jsonify({
                "status": "error",
                "message": "'quantity' must be int and prices must be numbers",
            }),
            400,
        )

    result = engine.place_order(
        symbol=symbol,
        exchange=exchange,
        action=action,
        quantity=quantity,
        price=price,
        product=product,
        order_type=order_type,
        trigger_price=trigger_price,
        strategy=strategy,
    )

    accepted = result["status"] in {"COMPLETE", "PENDING"}
    return jsonify({
        "status": "success" if accepted else "error",
        "data": {"order": result},
    }), (200 if accepted else 400)


@data_sandbox_bp.route("/order/<order_id>", methods=["DELETE"])
def cancel_order(order_id: str) -> Response:
    """Cancel one pending Practice order."""
    engine, err = _engine_required()
    if err:
        return err
    result = engine.cancel_order(order_id)
    accepted = result["status"] == "CANCELLED"
    return jsonify({
        "status": "success" if accepted else "error",
        "data": {"order": result},
    }), (200 if accepted else 400)


@data_sandbox_bp.route("/order/<order_id>", methods=["PATCH"])
def modify_order(order_id: str) -> Response:
    """Modify selected fields on one pending Practice order."""
    engine, err = _engine_required()
    if err:
        return err
    body: dict[str, Any] = request.get_json(silent=True) or {}
    changes: dict[str, Any] = {}
    try:
        if "quantity" in body:
            changes["quantity"] = int(body["quantity"])
        if "price" in body:
            changes["price"] = float(body["price"])
        if "trigger_price" in body:
            changes["trigger_price"] = float(body["trigger_price"])
        if "order_type" in body or "pricetype" in body:
            changes["order_type"] = body.get("order_type", body.get("pricetype"))
    except (TypeError, ValueError):
        return jsonify({"status": "error", "message": "Invalid request"}), 400
    result = engine.modify_order(order_id, **changes)
    accepted = result["status"] == "PENDING"
    return jsonify({
        "status": "success" if accepted else "error",
        "data": {"order": result},
    }), (200 if accepted else 400)


@data_sandbox_bp.route("/orders/cancel-all", methods=["POST"])
def cancel_all_orders() -> Response:
    """Cancel every pending Practice order."""
    engine, err = _engine_required()
    if err:
        return err
    return jsonify({
        "status": "success",
        "data": {"result": engine.cancel_pending_orders()},
    })


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


@data_sandbox_bp.route("/trades", methods=["GET"])
def get_trades() -> Response:
    """Return executed Practice fills."""
    engine, err = _engine_required()
    if err:
        return err
    return jsonify({"status": "success", "data": {"trades": engine.get_trades()}})


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


@data_sandbox_bp.route("/pnl/history", methods=["GET"])
def get_pnl_history() -> Response:
    """Return durable daily Practice P&L records."""
    engine, err = _engine_required()
    if err:
        return err
    return jsonify({
        "status": "success",
        "data": {"pnl_history": engine.get_pnl_history()},
    })


@data_sandbox_bp.route("/square-off", methods=["POST"])
def square_off_all() -> Response:
    """Close every open Practice position at supplied current LTPs."""
    engine, err = _engine_required()
    if err:
        return err
    body: dict[str, Any] = request.get_json(silent=True) or {}
    latest_ticks = body.get("latest_ticks")
    if not isinstance(latest_ticks, dict):
        return jsonify({"status": "error", "message": "'latest_ticks' must be an object"}), 400
    try:
        closed = engine.square_off_all(latest_ticks)
    except ValueError as exc:
        return jsonify({"status": "error", "message": str(exc)}), 400
    return jsonify({
        "status": "success",
        "data": {"closed_positions": closed},
    })


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
    except ValueError:
        return jsonify({"status": "error", "message": "Invalid request"}), 400

    return jsonify({"status": "success", "data": {"stats": stats}})
