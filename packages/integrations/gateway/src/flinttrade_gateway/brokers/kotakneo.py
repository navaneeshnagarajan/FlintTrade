"""Kotak Neo adapter skeleton for wave-3 broker support.

The full ``BrokerAdapter`` async surface (contract §5) is declared here, but
every live broker call is gated behind SDK attestation until the Kotak Neo wave
lands. ``broker_id`` and ``capabilities`` return real values so the registry,
router, capability-routing, and broker-recommendation layers can be exercised
ahead of live trading.

Capability values are grounded in the local Kotak Neo reference docs
(``.local/reference/broker-docs/kotak-neo/``). Fields not stated in those docs
are left at their dataclass defaults (``None``/``0``/``[]``) rather than guessed.

Auth model (for the future ``login``/``refresh``): the neo_api_client v2 SDK
(``Kotak-Neo/Kotak-neo-api-v2``, git-pinned at tag ``v2.0.1`` — there is no
official PyPI package) initialises as ``NeoAPI(environment='prod',
access_token=None, neo_fin_key=None, consumer_key=...)``, then the two-step Neo
flow: ``totp_login(mobile, ucc, totp)`` mints a view token + session id, and
``totp_validate(mpin)`` mints the trade token. (v2 removed the older
``base_url()``/``customer_key``/``customer_secret`` and QR-login flows; ``refresh``
is a full daily re-login.) v2.0.1 added MCX trading and the MTF product type.

Cost note: Kotak Neo advertises **zero brokerage** on API order execution and a
free API (no subscription charge). The one documented exception is that a
bracket order's square-off leg attracts standard brokerage even though the
initial leg is free.
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

_GATED = "Kotak Neo {0} is gated behind broker SDK attestation (wave 3)"

KOTAKNEO_CAPABILITIES = Capabilities(
    segments=(
        Segments.NSE_EQ
        | Segments.BSE_EQ
        | Segments.NFO
        | Segments.BFO
        | Segments.CDS
        | Segments.BCD
        | Segments.MCX
    ),
    # Native bracket (BO) and cover (CO) orders; no GTT and no iceberg
    # (only disclosed-quantity). Market orders are auto-converted to a protected
    # limit per SEBI retail-algo rules — handled at the adapter layer when wired.
    order_types=(
        OrderTypes.MARKET
        | OrderTypes.LIMIT
        | OrderTypes.SL
        | OrderTypes.SLM
        | OrderTypes.MIS
        | OrderTypes.CNC
        | OrderTypes.NRML
        | OrderTypes.AMO
        | OrderTypes.BO
        | OrderTypes.CO
    ),
    depth_levels=DepthLevels.L5,
    tick_protocol=TickProtocol.KOTAK_NEO_JSON,
    auth_model=AuthModel.MPIN_TOTP_DAILY,
    # Trade-token TTL is not stated in the local docs; 24h is the daily-cycle
    # ceiling used for refresh timing (the only JWT shown is a view-scope token).
    session_lifetime_hours=24.0,
    sandbox=True,
    # "Currently the system supports up to 10 orders per second."
    rate_limit_orders_per_sec=10,
    # 'tag' is an optional order field, not a mandated algo tag.
    algo_tag_required=False,
    # Zero brokerage on execution + zero API subscription charge (BO square-off
    # leg attracts standard brokerage — see module docstring).
    cost_paid=False,
    cost_inr_per_month=0,
    brokerage_free=True,
    brokerage_note=(
        "Zero brokerage on all API order execution; only statutory charges "
        "apply. Exception: a bracket order's square-off leg attracts standard "
        "brokerage."
    ),
    # No historical/OHLC-candle API in the Neo trade API — only live quotes.
    # No option-chain endpoint (search_scrip only).
    option_chain_supported=False,
    streaming_supported=True,
    bracket_order_native=True,
    cover_order_native=True,
    modify_qty_supported=True,
)


class KotakNeoAdapter(BrokerAdapter):
    # ---------- identity + capabilities ----------

    @property
    def broker_id(self) -> str:
        return "kotakneo"

    @property
    def capabilities(self) -> Capabilities:
        return KOTAKNEO_CAPABILITIES

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
