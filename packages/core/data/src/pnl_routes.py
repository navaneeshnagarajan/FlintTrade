"""P&L Tracker Flask endpoints.

Registered as a Blueprint in ``create_flask_app()``.

Endpoints
---------
GET  /api/v1/pnl-tracker          — P&L time series (optionally filtered by ?since=<unix>)
GET  /api/v1/pnl-tracker/summary  — Latest P&L summary stats
"""
from __future__ import annotations

import logging
from typing import Any

from flask import Blueprint, jsonify, request

from flinttrade_journal.pnl_tracker import PnLTracker

logger = logging.getLogger("flinttrade.data.pnl_routes")

pnl_bp = Blueprint("pnl", __name__, url_prefix="/api/v1")

# Module-level singleton — replaced by ``init_pnl_routes`` when injected.
_tracker: PnLTracker = PnLTracker()


def init_pnl_routes(tracker: PnLTracker) -> None:
    """Inject a PnLTracker instance into the blueprint's singleton.

    Call this from ``create_flask_app()`` after creating the tracker.

    Args:
        tracker: The :class:`PnLTracker` instance to use for all requests.
    """
    global _tracker  # noqa: PLW0603
    _tracker = tracker
    logger.info("PnLTracker singleton injected into pnl_routes")


@pnl_bp.route("/pnl-tracker", methods=["GET"])
def pnl_series() -> tuple[Any, int]:
    """Return the P&L time series as a JSON array.

    Query parameters:
        since (float, optional): Unix timestamp.  Only points at or after
            this timestamp are returned.

    Returns:
        JSON ``{"status": "success", "data": [...]}`` where each element has
        keys ``timestamp``, ``realized_pnl``, ``unrealized_pnl``,
        ``total_pnl``, ``trade_count``.
    """
    since_raw = request.args.get("since")
    since: float | None = None
    if since_raw is not None:
        try:
            since = float(since_raw)
        except ValueError:
            return jsonify({"status": "error", "message": "since must be a float"}), 400

    points = _tracker.get_series(since=since)
    return jsonify({
        "status": "success",
        "data": [
            {
                "timestamp": p.timestamp,
                "realized_pnl": p.realized_pnl,
                "unrealized_pnl": p.unrealized_pnl,
                "total_pnl": p.total_pnl,
                "trade_count": p.trade_count,
            }
            for p in points
        ],
    }), 200


@pnl_bp.route("/pnl-tracker/summary", methods=["GET"])
def pnl_summary() -> tuple[Any, int]:
    """Return a summary of the current P&L state.

    Returns:
        JSON ``{"status": "success", "data": {...}}`` with keys
        ``realized``, ``unrealized``, ``total``, ``max_total``,
        ``min_total``, ``trade_count``, ``data_points``.
    """
    return jsonify({"status": "success", "data": _tracker.get_summary()}), 200
