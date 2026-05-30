"""Flask Blueprint for broker capability queries.

Endpoint
--------
GET /api/v1/broker/capabilities  — return capabilities for one or all brokers

Wraps :data:`flinttrade_gateway.capabilities.REGISTRY`.

Register in ``create_flask_app()``::

    from flinttrade_gateway.capabilities_routes import capabilities_bp
    app.register_blueprint(capabilities_bp)
"""

from __future__ import annotations

import dataclasses
import logging
from typing import Any

from flask import Blueprint, jsonify, request

from .capabilities import REGISTRY, BrokerCapabilities

logger = logging.getLogger("flinttrade.gateway.capabilities_routes")

capabilities_bp = Blueprint("capabilities", __name__, url_prefix="/api/v1")


def _caps_to_dict(caps: BrokerCapabilities) -> dict[str, Any]:
    """Serialise a :class:`BrokerCapabilities` dataclass to a plain dict.

    Args:
        caps: The capabilities record to serialise.

    Returns:
        Dict suitable for JSON serialisation.
    """
    return dataclasses.asdict(caps)


@capabilities_bp.route("/broker/capabilities", methods=["GET"])
def get_capabilities() -> tuple[Any, int]:
    """Return capability information for one or all brokers.

    Query parameters:
        broker (str, optional): Broker identifier, e.g. ``zerodha``.
            When omitted all registered broker capabilities are returned.

    Returns:
        Single broker: JSON ``{"status": "success", "broker": "zerodha",
        "capabilities": {...}}``.

        All brokers: JSON ``{"status": "success", "count": N,
        "brokers": [{"broker_name": "...", ...}, ...]}``.

    Raises HTTP 404 when a specific broker is not found in the registry.
    """
    broker_param: str = request.args.get("broker", "").strip().lower()

    if broker_param:
        caps = REGISTRY.get(broker_param)
        if caps is None:
            known = REGISTRY.broker_names()
            return (
                jsonify(
                    {
                        "status": "error",
                        "message": f"Broker {broker_param!r} not found",
                        "known_brokers": known,
                    }
                ),
                404,
            )
        return (
            jsonify(
                {
                    "status": "success",
                    "broker": broker_param,
                    "capabilities": _caps_to_dict(caps),
                }
            ),
            200,
        )

    all_caps = REGISTRY.all()
    return (
        jsonify(
            {
                "status": "success",
                "count": len(all_caps),
                "brokers": [_caps_to_dict(c) for c in all_caps],
            }
        ),
        200,
    )
