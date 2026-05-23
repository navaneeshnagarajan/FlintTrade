"""Dhan v2 adapter skeleton for wave-1 broker support."""

from __future__ import annotations

from typing import Any

from flinttrade_gateway.capabilities import (
    AuthModel,
    Capabilities,
    DepthLevels,
    OrderTypes,
    Segments,
    TickProtocol,
)

from ._base import BrokerAdapter, Session

DHAN_CAPABILITIES = Capabilities(
    segments=Segments.NSE_EQ | Segments.BSE_EQ | Segments.NFO | Segments.BFO | Segments.CDS | Segments.MCX,
    order_types=(
        OrderTypes.MARKET
        | OrderTypes.LIMIT
        | OrderTypes.SL
        | OrderTypes.SLM
        | OrderTypes.MIS
        | OrderTypes.CNC
        | OrderTypes.NRML
        | OrderTypes.AMO
        | OrderTypes.GTT
        | OrderTypes.ICEBERG
        | OrderTypes.BO
        | OrderTypes.CO
    ),
    depth_levels=DepthLevels.L5,
    tick_protocol=TickProtocol.DHAN_BINARY,
    auth_model=AuthModel.OAUTH_RENEWABLE_24H,
    session_lifetime_hours=24.0,
    session_renewal_leeway_seconds=120,
    sandbox=True,
    rate_limit_orders_per_sec=10,
    rate_limit_orders_per_min=250,
    rate_limit_orders_per_hour=1000,
    rate_limit_orders_per_day=7000,
    rate_limit_data_per_sec=5,
    rate_limit_data_per_day=100_000,
    rate_limit_quote_per_sec=1,
    rate_limit_non_trading_per_sec=20,
    order_modifications_per_order=25,
    algo_tag_required=True,
    historical_max_lookback_days_intraday=90,
    historical_max_lookback_days_daily=None,
    historical_max_candles_per_request=5000,
    historical_intraday_intervals_minutes=[1, 5, 15, 25, 60],
    option_chain_supported=True,
    option_chain_greeks_supported=True,
    option_chain_rate_limit_seconds=3,
    streaming_supported=True,
    streaming_max_connections_per_user=5,
    streaming_max_symbols_per_connection=5000,
    streaming_max_total_symbols=25_000,
    streaming_heartbeat_seconds=10,
    streaming_disconnect_timeout_seconds=40,
    bracket_order_native=True,
    cover_order_native=True,
    iceberg_native=True,
    gtt_native=True,
    modify_qty_supported=True,
    modify_after_partial_fill=False,
)


class DhanAdapter(BrokerAdapter):
    @property
    def broker_id(self) -> str:
        return "dhan"

    @property
    def capabilities(self) -> Capabilities:
        return DHAN_CAPABILITIES

    def place_order(self, session: Session, order: Any, *, _router_token: object | None = None) -> Any:
        self._require_router_token(_router_token, _ROUTER_TOKEN)
        raise NotImplementedError("Dhan live order placement is gated behind broker SDK attestation")

    def modify_order(self, session: Session, order: Any, *, _router_token: object | None = None) -> Any:
        self._require_router_token(_router_token, _ROUTER_TOKEN)
        raise NotImplementedError("Dhan live order modification is gated behind broker SDK attestation")

    def cancel_order(self, session: Session, broker_order_id: str, *, _router_token: object | None = None) -> Any:
        self._require_router_token(_router_token, _ROUTER_TOKEN)
        raise NotImplementedError("Dhan live order cancellation is gated behind broker SDK attestation")

    def quotes(self, session: Session, symbols: list[str]) -> dict[str, Any]:
        return {symbol: {"available": False, "broker": self.broker_id} for symbol in symbols}


_ROUTER_TOKEN = object()
