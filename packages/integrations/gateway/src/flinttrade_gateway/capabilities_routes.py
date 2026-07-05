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

from .adapter import BROKER_CATALOG
from .capabilities import REGISTRY, BrokerCapabilities
from .recommendations import (
    NATIVE_BROKER_CAPABILITIES,
    BrokerUseCase,
    recommend,
    recommend_all,
)

logger = logging.getLogger("flinttrade.gateway.capabilities_routes")

capabilities_bp = Blueprint("capabilities", __name__, url_prefix="/api/v1")


_NATIVE_HISTORY_DAY_INTERVALS: dict[str, list[str]] = {
    "dhan": ["1D"],
    "upstox": ["1D", "1W", "1M"],
    "indmoney": ["1D", "1W", "1M"],
    "groww": ["1D", "1W"],
}


def _minute_interval_label(minutes: int) -> str:
    """Return the terminal's canonical label for an intraday interval."""
    if minutes > 0 and minutes % 60 == 0:
        return f"{minutes // 60}h"
    return f"{minutes}m"


def _native_capability_fields(broker_name: str) -> dict[str, Any]:
    """Expose optional native-adapter metadata alongside legacy capabilities."""
    native = NATIVE_BROKER_CAPABILITIES.get(broker_name)
    if native is None:
        return _catalog_mcp_fields(broker_name)
    intraday = list(native.historical_intraday_intervals_minutes)
    intervals = [_minute_interval_label(minutes) for minutes in intraday]
    intervals.extend(_NATIVE_HISTORY_DAY_INTERVALS.get(broker_name, []))
    data = {
        "connectable": BROKER_CATALOG.get(broker_name).connectable if BROKER_CATALOG.get(broker_name) else False,
        "historical_intervals": intervals,
        "historical_intraday_intervals_minutes": intraday,
        "historical_max_lookback_days_intraday": native.historical_max_lookback_days_intraday,
        "historical_max_lookback_days_daily": native.historical_max_lookback_days_daily,
        "historical_max_candles_per_request": native.historical_max_candles_per_request,
        "market_depth_runtime_ready": native.market_depth_runtime_ready,
        "option_chain_supported": native.option_chain_supported,
        "option_chain_greeks_supported": native.option_chain_greeks_supported,
    }
    data.update(_catalog_mcp_fields(broker_name))
    return data


def _catalog_mcp_fields(broker_name: str) -> dict[str, Any]:
    """Return broker-hosted MCP metadata from the unified catalogue."""
    info = BROKER_CATALOG.get(broker_name)
    if info is None or info.mcp is None:
        return {}
    return {"mcp": info.mcp.model_dump()}


def _caps_to_dict(caps: BrokerCapabilities) -> dict[str, Any]:
    """Serialise a :class:`BrokerCapabilities` dataclass to a plain dict.

    Args:
        caps: The capabilities record to serialise.

    Returns:
        Dict suitable for JSON serialisation.
    """
    data = dataclasses.asdict(caps)
    data.update(_native_capability_fields(caps.broker_name))
    return data


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
    data = dataclasses.asdict(rec)
    info = BROKER_CATALOG.get(rec.broker_id)
    if info is not None:
        data["connectable"] = info.connectable
        data["display_name"] = info.display_name
    return data


def _mcp_entry(info: Any) -> dict[str, Any]:
    """Serialise one broker-hosted MCP catalogue row."""
    return {
        "adapter_id": info.name,
        "display_name": info.display_name,
        "native": info.native,
        "connectable": info.connectable,
        "mcp": info.mcp.model_dump(),
    }


@capabilities_bp.route("/broker/mcp", methods=["GET"])
def get_broker_mcp_catalogue() -> tuple[Any, int]:
    """Return broker-hosted MCP setup/capability metadata.

    This endpoint intentionally exposes metadata only. It does not proxy MCP
    tool calls, and it does not create a broker write path around FlintTrade's
    order safety gate.
    """
    broker_param = request.args.get("broker", "").strip().lower()
    if broker_param:
        info = BROKER_CATALOG.get(broker_param)
        if info is None:
            known = sorted(name for name, row in BROKER_CATALOG.items() if row.mcp is not None)
            return (
                jsonify({
                    "status": "error",
                    "message": f"Broker {broker_param!r} not found",
                    "known_brokers": known,
                }),
                404,
            )
        if info.mcp is None:
            known = sorted(name for name, row in BROKER_CATALOG.items() if row.mcp is not None)
            return (
                jsonify({
                    "status": "error",
                    "message": f"Broker {broker_param!r} has no FlintTrade-catalogued MCP endpoint",
                    "known_brokers": known,
                }),
                404,
            )
        return jsonify({"status": "success", "broker": _mcp_entry(info)}), 200

    brokers = [_mcp_entry(info) for info in BROKER_CATALOG.values() if info.mcp is not None]
    return jsonify({"status": "success", "count": len(brokers), "brokers": brokers}), 200


def _truthy_query(value: str) -> bool:
    """Return whether a query flag explicitly opted in."""
    return value.strip().lower() in {"1", "true", "yes", "on"}


def _default_recommendation_capabilities(include_coming_soon: bool) -> dict[str, Any] | None:
    """Return the default recommendation scope for user-facing routes.

    The ranking engine still knows every native adapter, including built but
    unverified ones. The route defaults to login/read-verified connectable
    natives so the terminal does not recommend a broker the connect UI
    correctly disables.
    """
    if include_coming_soon:
        return None
    return {
        broker_id: caps
        for broker_id, caps in NATIVE_BROKER_CAPABILITIES.items()
        if BROKER_CATALOG.get(broker_id) is not None and BROKER_CATALOG[broker_id].connectable
    }


@capabilities_bp.route("/broker/recommendations", methods=["GET"])
def get_recommendations() -> tuple[Any, int]:
    """Rank native broker capability metadata for an operator-selected job.

    Query parameters:
        use_case (str, optional): One of the :class:`BrokerUseCase` values
            (e.g. ``low_cost_execution``, ``market_depth``). When omitted,
            rankings for every use-case are returned.
        brokers (str, optional): Comma-separated broker ids to restrict the
            ranking to (e.g. the operator's connected brokers). When omitted,
            only login/read-verified connectable native brokers are ranked.
        include_coming_soon (bool, optional): When true and ``brokers`` is not
        supplied, include built-but-disabled native brokers such as Kotak Neo
        and Groww in the capability metadata ranking.

    Returns:
        Single use-case: ``{"status": "success", "use_case": "...",
        "recommendations": [{"broker_id", "score", "raw_score", "rationale"},
        ...]}``.

        All use-cases: ``{"status": "success", "use_cases": {"<use_case>":
        [...], ...}}``.

        HTTP 400 for an unknown ``use_case`` or unknown broker id.
    """
    brokers_param = request.args.get("brokers", "").strip()
    include_coming_soon = _truthy_query(request.args.get("include_coming_soon", ""))
    caps_subset = _default_recommendation_capabilities(include_coming_soon)
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
