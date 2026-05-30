"""Position sizer Flask Blueprint — /api/v1/position/size.

Exposes the :class:`~flinttrade_engine.position_sizer.PositionSizer`
calculation methods over HTTP so the React terminal can call them without
importing Python.
"""

from __future__ import annotations

import logging
from typing import Any

from flask import Blueprint, jsonify, request

logger = logging.getLogger("flinttrade.engine.position_sizer_routes")

position_bp = Blueprint("position", __name__, url_prefix="/api/v1/position")


@position_bp.route("/size", methods=["POST"])
def calculate_size() -> tuple[Any, int]:
    """Calculate position size using one of four methods.

    Request JSON:
        method (str): One of ``"from_capital"``, ``"from_risk_percent"``,
            ``"from_kelly"``, ``"max_lots"``.
        capital (float): Account capital or available amount in rupees.
        ltp (float, optional): Last traded price (required for
            ``from_capital`` and ``from_kelly``).
        lot_size (int, optional): Lot size (default 1 for equities).
        risk_pct (float, optional): Risk fraction for ``from_risk_percent``,
            e.g. 0.01 for 1%.
        entry (float, optional): Entry price for ``from_risk_percent``.
        sl (float, optional): Stop-loss price for ``from_risk_percent``.
        win_rate (float, optional): Historical win rate for ``from_kelly``.
        avg_win (float, optional): Average winning trade amount for ``from_kelly``.
        avg_loss (float, optional): Average losing trade amount for ``from_kelly``.
        margin_per_lot (float, optional): Margin per lot for ``max_lots``.

    Returns:
        JSON with ``status`` and ``data`` containing ``quantity`` (int),
        ``method`` (str used), and ``inputs`` (echo of request params).
    """
    body = request.get_json(silent=True) or {}
    method: str = str(body.get("method", "")).strip().lower()

    valid_methods = {"from_capital", "from_risk_percent", "from_kelly", "max_lots"}
    if not method:
        return jsonify({"status": "error", "message": "method is required"}), 400
    if method not in valid_methods:
        return jsonify({
            "status": "error",
            "message": f"method must be one of: {', '.join(sorted(valid_methods))}",
        }), 400

    try:
        capital = float(body.get("capital", 0) or 0)
    except (TypeError, ValueError):
        return jsonify({"status": "error", "message": "capital must be a number"}), 400

    try:
        from .position_sizer import PositionSizer  # noqa: PLC0415
    except ImportError as exc:
        logger.error("Could not import PositionSizer: %s", exc)
        return jsonify({"status": "error", "message": "Position sizer unavailable"}), 503

    try:
        quantity: int = 0

        if method == "from_capital":
            ltp = float(body.get("ltp", 0) or 0)
            lot_size = int(body.get("lot_size", 1) or 1)
            if ltp <= 0:
                return jsonify({"status": "error", "message": "ltp must be > 0"}), 400
            quantity = PositionSizer.from_capital(capital, ltp, lot_size)

        elif method == "from_risk_percent":
            risk_pct = float(body.get("risk_pct", 0) or 0)
            entry = float(body.get("entry", 0) or 0)
            sl = float(body.get("sl", 0) or 0)
            lot_size = int(body.get("lot_size", 1) or 1)
            if risk_pct <= 0:
                return jsonify({"status": "error", "message": "risk_pct must be > 0"}), 400
            if entry <= 0 or sl <= 0:
                return jsonify({"status": "error", "message": "entry and sl must be > 0"}), 400
            quantity = PositionSizer.from_risk_percent(capital, risk_pct, entry, sl, lot_size)

        elif method == "from_kelly":
            win_rate = float(body.get("win_rate", 0) or 0)
            avg_win = float(body.get("avg_win", 0) or 0)
            avg_loss = float(body.get("avg_loss", 0) or 0)
            ltp = float(body.get("ltp", 0) or 0)
            if ltp <= 0:
                return jsonify({"status": "error", "message": "ltp must be > 0"}), 400
            quantity = PositionSizer.from_kelly(win_rate, avg_win, avg_loss, capital, ltp)

        elif method == "max_lots":
            margin_per_lot = float(body.get("margin_per_lot", 0) or 0)
            if margin_per_lot <= 0:
                return jsonify({"status": "error", "message": "margin_per_lot must be > 0"}), 400
            quantity = PositionSizer.max_lots(capital, margin_per_lot)

        return jsonify({
            "status": "success",
            "data": {
                "quantity": quantity,
                "method": method,
                "inputs": body,
            },
        }), 200

    except (TypeError, ValueError) as exc:
        return jsonify({"status": "error", "message": f"Invalid input: {exc}"}), 400
    except Exception:
        logger.exception("calculate_size error")
        return jsonify({"status": "error", "message": "Internal server error"}), 500
