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

from .adapter import BROKER_CATALOG, OPENALGO_PLATFORM_MCP
from .capabilities import REGISTRY, BrokerCapabilities
from .models import BrokerMCPInfo
from .recommendations import (
    NATIVE_BROKER_CAPABILITIES,
    BrokerUseCase,
    recommend,
    recommend_all,
)

logger = logging.getLogger("flinttrade.gateway.capabilities_routes")

capabilities_bp = Blueprint("capabilities", __name__, url_prefix="/api/v1")


def _sdk_attestations_by_pin() -> dict[str, dict[str, Any]]:
    """Return installed SDK attestation rows keyed by brokers.lock pin name.

    The ONE error-swallowing wrapper for broker-catalogue routes: the gateway
    owns SDK attestation, so this is the single implementation —
    ``flinttrade_core.native_account_routes`` imports it rather than keeping
    its own copy (a byte-identical duplicate used to live there and the two
    could drift). Both failure modes stay non-fatal: catalogue routes must
    render even when the attestation module is absent or raises.
    """
    try:
        from flinttrade_core.broker_sdk_attest import attestations_by_pin  # noqa: PLC0415
    except Exception as exc:  # pragma: no cover - optional at import time
        logger.warning("Broker SDK attestation unavailable for broker catalogue (%s)", exc)
        return {}
    try:
        return attestations_by_pin()
    except Exception as exc:  # pragma: no cover - route must remain non-fatal
        logger.warning("Broker SDK attestation failed for broker catalogue (%s)", exc)
        return {}


def _catalog_sdk_fields(broker_name: str) -> dict[str, Any]:
    """Expose the repo-managed SDK pin and local install status for native brokers."""
    info = BROKER_CATALOG.get(broker_name)
    if info is None or not info.native:
        return {}
    from flinttrade_core.broker_sdk_attest import sdk_attestation_fields  # noqa: PLC0415

    return sdk_attestation_fields(info.sdk_pin, attestations=_sdk_attestations_by_pin())


def _minute_interval_label(minutes: int) -> str:
    """Return the terminal's canonical label for an intraday interval."""
    if minutes > 0 and minutes % 60 == 0:
        return f"{minutes // 60}h"
    return f"{minutes}m"


def _native_capability_fields(broker_name: str) -> dict[str, Any]:
    """Expose optional native-adapter metadata alongside legacy capabilities."""
    info = BROKER_CATALOG.get(broker_name)
    native = NATIVE_BROKER_CAPABILITIES.get(broker_name)
    if native is None:
        data = (
            {
                "requires_static_ip": info.requires_static_ip,
                "native_connect_blockers": list(info.native_connect_blockers),
            }
            if info is not None
            else {}
        )
        data.update(_catalog_mcp_fields(broker_name))
        data.update(_catalog_sdk_fields(broker_name))
        return data
    intraday = list(native.historical_intraday_intervals_minutes)
    intervals = [_minute_interval_label(minutes) for minutes in intraday]
    intervals.extend(native.historical_calendar_intervals)
    data = {
        "connectable": info.connectable if info else False,
        "requires_static_ip": info.requires_static_ip if info else False,
        "native_connect_blockers": list(info.native_connect_blockers) if info else [],
        "historical_intervals": intervals,
        "historical_intraday_intervals_minutes": intraday,
        "historical_calendar_intervals": list(native.historical_calendar_intervals),
        "historical_max_lookback_days_intraday": native.historical_max_lookback_days_intraday,
        "historical_max_lookback_days_daily": native.historical_max_lookback_days_daily,
        "historical_max_candles_per_request": native.historical_max_candles_per_request,
        "auth_model": native.auth_model.value,
        "session_lifetime_hours": native.session_lifetime_hours,
        "session_renewal_leeway_seconds": native.session_renewal_leeway_seconds,
        "rate_limit_orders_per_sec": native.rate_limit_orders_per_sec,
        "rate_limit_orders_per_min": native.rate_limit_orders_per_min,
        "rate_limit_orders_per_hour": native.rate_limit_orders_per_hour,
        "rate_limit_orders_per_day": native.rate_limit_orders_per_day,
        "rate_limit_data_per_sec": native.rate_limit_data_per_sec,
        "rate_limit_data_per_day": native.rate_limit_data_per_day,
        "rate_limit_quote_per_sec": native.rate_limit_quote_per_sec,
        "rate_limit_non_trading_per_sec": native.rate_limit_non_trading_per_sec,
        "order_modifications_per_order": native.order_modifications_per_order,
        "algo_tag_required": native.algo_tag_required,
        "brokerage_free": native.brokerage_free,
        "brokerage_note": native.brokerage_note,
        "cost_paid": native.cost_paid,
        "cost_inr_per_month": native.cost_inr_per_month,
        "market_depth_runtime_ready": native.market_depth_runtime_ready,
        "streaming_runtime_ready": native.streaming_runtime_ready,
        "streaming_max_connections_per_user": native.streaming_max_connections_per_user,
        "streaming_max_symbols_per_connection": native.streaming_max_symbols_per_connection,
        "streaming_max_total_symbols": native.streaming_max_total_symbols,
        "option_chain_supported": native.option_chain_supported,
        "option_chain_greeks_supported": native.option_chain_greeks_supported,
        "option_chain_rate_limit_seconds": native.option_chain_rate_limit_seconds,
        "options_history_supported": native.options_history_supported,
        "options_history_rolling": native.options_history_rolling,
        "gtt_native": native.gtt_native,
        "iceberg_native": native.iceberg_native,
        "modify_qty_supported": native.modify_qty_supported,
        "modify_after_partial_fill": native.modify_after_partial_fill,
        "bracket_order_native": native.bracket_order_native,
        "cover_order_native": native.cover_order_native,
        "basket_order_native": native.basket_order_native,
    }
    data.update(_catalog_mcp_fields(broker_name))
    data.update(_catalog_sdk_fields(broker_name))
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
        data["requires_static_ip"] = info.requires_static_ip
        data["native_connect_blockers"] = list(info.native_connect_blockers)
    return data


def _mcp_entry(info: Any) -> dict[str, Any]:
    """Serialise one broker-hosted MCP catalogue row."""
    data = {
        "adapter_id": info.name,
        "display_name": info.display_name,
        "native": info.native,
        "connectable": info.connectable,
        "requires_static_ip": info.requires_static_ip,
        "native_connect_blockers": list(info.native_connect_blockers),
        "mcp": info.mcp.model_dump(),
    }
    data.update(_catalog_sdk_fields(info.name))
    return data


def _openalgo_mcp_entry() -> dict[str, Any]:
    """Serialise the OpenAlgo platform MCP row.

    OpenAlgo is the bridge platform, not a BROKER_CATALOG broker, but its
    self-hosted MCP is the first-preference MCP surface (one server covering
    every bridged broker), so the catalogue route serves it ahead of the
    broker-hosted entries. Validated through the same BrokerMCPInfo model so
    the row cannot drift from the schema the UI renders.
    """
    return {
        "adapter_id": "openalgo",
        "display_name": "OpenAlgo (bridge)",
        "native": False,
        "connectable": True,
        "requires_static_ip": False,
        "native_connect_blockers": [],
        "mcp": BrokerMCPInfo(**OPENALGO_PLATFORM_MCP).model_dump(),
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
        if broker_param == "openalgo":
            return jsonify({"status": "success", "broker": _openalgo_mcp_entry()}), 200
        info = BROKER_CATALOG.get(broker_param)
        if info is None:
            known = ["openalgo"] + sorted(
                name for name, row in BROKER_CATALOG.items() if row.mcp is not None
            )
            return (
                jsonify({
                    "status": "error",
                    "message": f"Broker {broker_param!r} not found",
                    "known_brokers": known,
                }),
                404,
            )
        if info.mcp is None:
            known = ["openalgo"] + sorted(
                name for name, row in BROKER_CATALOG.items() if row.mcp is not None
            )
            return (
                jsonify({
                    "status": "error",
                    "message": f"Broker {broker_param!r} has no FlintTrade-catalogued MCP endpoint",
                    "known_brokers": known,
                }),
                404,
            )
        return jsonify({"status": "success", "broker": _mcp_entry(info)}), 200

    # OpenAlgo (the primary, community-tested path) leads the list; the
    # broker-hosted entries follow in catalogue order.
    brokers = [_openalgo_mcp_entry()] + [
        _mcp_entry(info) for info in BROKER_CATALOG.values() if info.mcp is not None
    ]
    return jsonify({"status": "success", "count": len(brokers), "brokers": brokers}), 200


def _truthy_query(value: str) -> bool:
    """Return whether a query flag explicitly opted in."""
    return value.strip().lower() in {"1", "true", "yes", "on"}


def _default_recommendation_capabilities(include_coming_soon: bool) -> dict[str, Any] | None:
    """Return the default recommendation scope for user-facing routes.

    The ranking engine still knows every native adapter, including built but
    unverified ones. The route defaults to activation-evidence-cleared
    connectable natives so the terminal does not recommend a broker the connect
    UI correctly disables.
    """
    if include_coming_soon:
        return None
    return {
        broker_id: caps
        for broker_id, caps in NATIVE_BROKER_CAPABILITIES.items()
        if BROKER_CATALOG.get(broker_id) is not None and BROKER_CATALOG[broker_id].connectable
    }


# OpenAlgo is the first-preference path on every user-facing surface
# (architecture north star): the ranking engine deliberately excludes the
# bridge (a meta-adapter cannot be capability-ranked), so the route emits this
# platform-level leading note for the recommendations panel to render FIRST —
# mirroring the MCP catalogue's leading OpenAlgo entry. Without it, the panel
# steers operators toward native brokers whose order paths are not yet
# live-verified while never mentioning the recommended path.
_OPENALGO_FIRST_NOTE: dict[str, str] = {
    "broker_id": "openalgo",
    "display_name": "OpenAlgo (bridge)",
    "note": (
        "Recommended first: the OpenAlgo bridge covers every use case through "
        "your configured broker — 30+ community-tested brokers on the primary, "
        "battle-tested path. Native adapters below are the secondary path."
    ),
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
            only activation-evidence-cleared connectable native brokers are ranked.
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
                    "openalgo_first": _OPENALGO_FIRST_NOTE,
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
                "openalgo_first": _OPENALGO_FIRST_NOTE,
                "use_cases": {
                    uc: [_rec_to_dict(r) for r in recs] for uc, recs in everything.items()
                },
            }
        ),
        200,
    )
