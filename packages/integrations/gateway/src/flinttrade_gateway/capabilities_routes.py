"""Flask Blueprint for broker capability queries.

Endpoints
---------
GET /api/v1/broker/capabilities   — capabilities for one or all brokers
GET /api/v1/broker/recommendations — rank brokers per use-case ("which broker
                                     for what")

Wraps :data:`flinttrade_gateway.capabilities.REGISTRY` and the
:mod:`flinttrade_gateway.recommendations` engine.

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
from .recommendations import (
    NATIVE_BROKER_CAPABILITIES,
    BrokerUseCase,
    recommend,
    recommend_all,
)

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


def _rec_to_dict(rec: Any) -> dict[str, Any]:
    """Serialise a :class:`BrokerRecommendation` to a plain dict."""
    return dataclasses.asdict(rec)


@capabilities_bp.route("/broker/recommendations", methods=["GET"])
def get_recommendations() -> tuple[Any, int]:
    """Rank native brokers for a trading job — "which broker for what".

    Query parameters:
        use_case (str, optional): One of the :class:`BrokerUseCase` values
            (e.g. ``low_cost_execution``, ``market_depth``). When omitted,
            rankings for every use-case are returned.
        brokers (str, optional): Comma-separated broker ids to restrict the
            ranking to (e.g. the operator's connected brokers). When omitted,
            all known native brokers are ranked.

    Returns:
        Single use-case: ``{"status": "success", "use_case": "...",
        "recommendations": [{"broker_id", "score", "raw_score", "rationale"},
        ...]}``.

        All use-cases: ``{"status": "success", "use_cases": {"<use_case>":
        [...], ...}}``.

        HTTP 400 for an unknown ``use_case`` or unknown broker id.
    """
    brokers_param = request.args.get("brokers", "").strip()
    caps_subset = None
    if brokers_param:
        wanted = [b.strip().lower() for b in brokers_param.split(",") if b.strip()]
        unknown = [b for b in wanted if b not in NATIVE_BROKER_CAPABILITIES]
        if unknown:
            return (
                jsonify(
                    {
                        "status": "error",
                        "message": f"Unknown broker(s): {unknown}",
                        "known_brokers": sorted(NATIVE_BROKER_CAPABILITIES),
                    }
                ),
                400,
            )
        caps_subset = {b: NATIVE_BROKER_CAPABILITIES[b] for b in wanted}

    use_case_param = request.args.get("use_case", "").strip().lower()
    if use_case_param:
        try:
            use_case = BrokerUseCase(use_case_param)
        except ValueError:
            return (
                jsonify(
                    {
                        "status": "error",
                        "message": f"Unknown use_case {use_case_param!r}",
                        "known_use_cases": [uc.value for uc in BrokerUseCase],
                    }
                ),
                400,
            )
        recs = recommend(use_case, caps_subset)
        return (
            jsonify(
                {
                    "status": "success",
                    "use_case": use_case.value,
                    "recommendations": [_rec_to_dict(r) for r in recs],
                }
            ),
            200,
        )

    everything = recommend_all(caps_subset)
    return (
        jsonify(
            {
                "status": "success",
                "use_cases": {
                    uc: [_rec_to_dict(r) for r in recs] for uc, recs in everything.items()
                },
            }
        ),
        200,
    )
