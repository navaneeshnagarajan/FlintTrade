"""Dhan v2 adapter skeleton for wave-1 broker support.

The full BrokerAdapter async surface (contract §5) is declared here, but every
live broker call is gated behind SDK attestation until the Dhan §9.5 wave lands.
``broker_id`` and ``capabilities`` return real values so the registry, router,
and capability-routing layers can be exercised ahead of live trading.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, AsyncIterator

from flinttrade_gateway.capabilities import (
    AuthModel,
    Capabilities,
    DepthLevels,
    OrderTypes,
    Segments,
    TickProtocol,
)

from ._base import BrokerAdapter, Session

if TYPE_CHECKING:  # pragma: no cover - typing only
    from flinttrade_core.models import Candles, OptionChain, Order, Position, Quote, Trade
    from flinttrade_gateway.reconciliation import ReconciliationReport

_GATED = "Dhan {0} is gated behind broker SDK attestation (wave 1 §9.5)"

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
    # Standard market-depth feed is 5-level, but Dhan v2 also offers a dedicated
    # 20-level depth feed (wss://depth-api-feed.dhan.co/twentydepth) and a
    # 200-level full-depth feed (wss://full-depth-api.dhan.co/twohundreddepth),
    # so the advertised maximum is L20 (the enum ceiling; 200-level is beyond it).
    depth_levels=DepthLevels.L20,
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
    # ---------- identity + capabilities ----------

    @property
    def broker_id(self) -> str:
        return "dhan"

    @property
    def capabilities(self) -> Capabilities:
        return DHAN_CAPABILITIES

    # ---------- auth lifecycle ----------

    async def login(self, credentials: dict) -> Session:
        raise NotImplementedError(_GATED.format("login"))

    async def refresh(self, session: Session) -> Session:
        raise NotImplementedError(_GATED.format("refresh"))

    async def logout(self, session: Session) -> None:
        raise NotImplementedError(_GATED.format("logout"))

    # ---------- trading: writes (router-only) ----------

    async def place_order(self, session: Session, order: Order, *, _router_token: object | None = None) -> str:
        self._require_router_token(_router_token, _ROUTER_TOKEN)
        raise NotImplementedError(_GATED.format("order placement"))

    async def modify_order(
        self, session: Session, order_id: str, changes: dict, *, _router_token: object | None = None
    ) -> None:
        self._require_router_token(_router_token, _ROUTER_TOKEN)
        raise NotImplementedError(_GATED.format("order modification"))

    async def cancel_order(
        self, session: Session, order_id: str, *, _router_token: object | None = None
    ) -> None:
        self._require_router_token(_router_token, _ROUTER_TOKEN)
        raise NotImplementedError(_GATED.format("order cancellation"))

    # ---------- trading: reads ----------

    async def order_book(self, session: Session) -> list[Order]:
        raise NotImplementedError(_GATED.format("order_book"))

    async def trade_book(self, session: Session) -> list[Trade]:
        raise NotImplementedError(_GATED.format("trade_book"))

    async def positions(self, session: Session) -> list[Position]:
        raise NotImplementedError(_GATED.format("positions"))

    async def holdings(self, session: Session) -> list[dict]:
        raise NotImplementedError(_GATED.format("holdings"))

    async def funds(self, session: Session) -> dict:
        raise NotImplementedError(_GATED.format("funds"))

    # ---------- market data: rest ----------

    async def quotes(self, session: Session, symbols: list[str]) -> list[Quote]:
        raise NotImplementedError(_GATED.format("quotes"))

    async def historical(self, session: Session, req: dict) -> Candles:
        raise NotImplementedError(_GATED.format("historical"))

    async def option_chain(self, session: Session, req: dict) -> OptionChain:
        raise NotImplementedError(_GATED.format("option_chain"))

    # ---------- market data: streaming ----------

    def stream(self, session: Session) -> AsyncIterator[Any]:
        raise NotImplementedError(_GATED.format("stream"))

    async def subscribe(self, session: Session, symbols: list[str], mode: str = "FULL") -> None:
        raise NotImplementedError(_GATED.format("subscribe"))

    async def unsubscribe(self, session: Session, symbols: list[str]) -> None:
        raise NotImplementedError(_GATED.format("unsubscribe"))

    # ---------- reconciliation ----------

    async def reconcile(self, session: Session) -> ReconciliationReport:
        raise NotImplementedError(_GATED.format("reconcile"))


_ROUTER_TOKEN = object()
