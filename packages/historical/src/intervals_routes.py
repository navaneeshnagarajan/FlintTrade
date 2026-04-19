"""Flask Blueprint for supported candle interval queries.

Endpoint
--------
GET /api/v1/intervals  — list intervals supported by a broker (or all brokers)

Wraps :mod:`packages.historical.src.intervals`.

Register in ``create_flask_app()``::

    from packages.historical.src.intervals_routes import intervals_bp
    app.register_blueprint(intervals_bp)
"""

from __future__ import annotations

import logging
from typing import Any

from flask import Blueprint, jsonify, request

from .intervals import (
    SUPPORTED_INTERVALS_PER_BROKER,
    get_common_intervals,
    get_intervals,
    list_brokers,
)

logger = logging.getLogger("flinttrade.historical.intervals_routes")

intervals_bp = Blueprint("intervals", __name__, url_prefix="/api/v1")


@intervals_bp.route("/intervals", methods=["GET"])
def get_intervals_endpoint() -> tuple[Any, int]:
    """Return the supported candle intervals for a broker.

    Query parameters:
        broker (str, optional): Broker identifier, e.g. ``zerodha``.
            When omitted all known broker → interval mappings are returned.
        brokers (str, optional): Comma-separated broker list.  When provided
            returns the *intersection* of supported intervals so that data can
            be fetched from every listed broker.

    Returns:
        JSON ``{"status": "success", "broker": "zerodha",
        "intervals": ["1m", "3m", ...]}``

        or, when no broker is supplied:

        JSON ``{"status": "success", "brokers": {...}, "all_brokers": [...]}``.
    """
    broker_param: str = request.args.get("broker", "").strip().lower()
    brokers_param: str = request.args.get("brokers", "").strip()

    # Multi-broker intersection query
    if brokers_param:
        broker_list = [b.strip().lower() for b in brokers_param.split(",") if b.strip()]
        intervals = get_common_intervals(broker_list)
        return (
            jsonify(
                {
                    "status": "success",
                    "brokers": broker_list,
                    "intervals": intervals,
                    "count": len(intervals),
                }
            ),
            200,
        )

    # Single broker query
    if broker_param:
        intervals = get_intervals(broker_param)
        known = broker_param in SUPPORTED_INTERVALS_PER_BROKER
        return (
            jsonify(
                {
                    "status": "success",
                    "broker": broker_param,
                    "intervals": intervals,
                    "count": len(intervals),
                    "is_known_broker": known,
                }
            ),
            200,
        )

    # No broker — return full registry
    all_brokers = list_brokers()
    registry = {b: SUPPORTED_INTERVALS_PER_BROKER[b] for b in all_brokers}
    return (
        jsonify(
            {
                "status": "success",
                "brokers": registry,
                "all_brokers": all_brokers,
            }
        ),
        200,
    )
