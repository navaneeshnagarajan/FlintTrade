"""OpenAlgo bridge adapter — routes the selector-bound principal through OpenAlgo.

OpenAlgo already integrates every broker the operator uses (Dhan, Upstox, Kotak
Neo, IndMoney, …), so this single ``BrokerAdapter`` lets the safety-gated
``BrokerRouter`` dispatch to ALL of them via selectors like ``openalgo:dhan``
without per-broker SDK risk — the path the operator already runs and trusts.

It forwards each contract-§5 method to a :class:`~flinttrade_core.openalgo_client.OpenAlgoClient`.
The client is injected (or built per-session for multi-account), so the adapter
never couples to ``Settings`` and is trivially testable. Methods OpenAlgo's REST
client does not expose (tick streaming, reconciliation, clock-based refresh)
raise :class:`UnsupportedCapabilityError` honestly rather than pretending.

Writes (place/modify/cancel) keep the §8 invariant: they are reachable only with
the router's per-process ``_router_token``; a bare call raises ``SafetyBypassError``
before any OpenAlgo request is made.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any, AsyncIterator, Callable

from flinttrade_core.exceptions import (
    APIError,
    BrokerError,
    OpenAlgoAuthError,
    OpenAlgoRateLimitError,
    OrderRejectedByBroker,
    RateLimitError,
    SessionExpired,
    UnsupportedCapabilityError,
)
from flinttrade_core.models import ModifyOrder

from flinttrade_gateway.capabilities import (
    AuthModel,
    Capabilities,
    DepthLevels,
    OrderTypes,
    Segments,
    TickProtocol,
)

from ._base import ROUTER_TOKEN as _ROUTER_TOKEN  # the shared per-process router token (§8.0c)
from ._base import BrokerAdapter, Session

if TYPE_CHECKING:  # pragma: no cover - typing only
    from flinttrade_core.models import Candles, OptionChain, Order, Position, Quote, Trade
    from flinttrade_core.openalgo_client import OpenAlgoClient
    from flinttrade_gateway.reconciliation import ReconciliationReport

logger = logging.getLogger("flinttrade.gateway.brokers.openalgo")

# OpenAlgo's api-key auth is persistent; the underlying broker session is daily,
# but the adapter treats the api-key as the credential (the operator re-links the
# broker in the OpenAlgo UI). Far-future so SafetyContext/Session expiry never
# trips on the bridge itself.
_FAR_FUTURE = 4_102_444_800.0  # 2100-01-01 UTC

OPENALGO_CAPABILITIES = Capabilities(
    segments=Segments.NSE_EQ | Segments.BSE_EQ | Segments.NFO | Segments.BFO | Segments.CDS | Segments.MCX,
    order_types=(
        OrderTypes.MARKET
        | OrderTypes.LIMIT
        | OrderTypes.SL
        | OrderTypes.SLM
        | OrderTypes.MIS
        | OrderTypes.CNC
        | OrderTypes.NRML
    ),
    depth_levels=DepthLevels.L5,
    tick_protocol=TickProtocol.OPENALGO_JSON,
    auth_model=AuthModel.API_KEY_PERSISTENT,
    session_lifetime_hours=24.0,
    session_renewal_leeway_seconds=120,
    sandbox=False,
    rate_limit_orders_per_sec=10,
    rate_limit_orders_per_min=250,
    rate_limit_orders_per_hour=1000,
    rate_limit_orders_per_day=7000,
    rate_limit_data_per_sec=5,
    rate_limit_data_per_day=100_000,
    rate_limit_quote_per_sec=1,
    rate_limit_non_trading_per_sec=20,
    order_modifications_per_order=25,
    algo_tag_required=False,
    historical_max_lookback_days_intraday=90,
    historical_max_lookback_days_daily=None,
    historical_max_candles_per_request=5000,
    historical_intraday_intervals_minutes=[1, 5, 15, 30, 60],
    option_chain_supported=True,
    option_chain_greeks_supported=True,
    option_chain_rate_limit_seconds=3,
    # This REST bridge does not expose the OpenAlgo websocket feed — advertise it
    # off so the router never resolves a tick stream to this adapter.
    streaming_supported=False,
    streaming_max_connections_per_user=0,
    streaming_max_symbols_per_connection=0,
    streaming_max_total_symbols=0,
    streaming_heartbeat_seconds=10,
    streaming_disconnect_timeout_seconds=40,
    bracket_order_native=False,
    cover_order_native=False,
    iceberg_native=False,
    # Honesty: this bridge's place_order forwards a plain order to OpenAlgo's
    # /placeorder — there is no GTT/standing-order path here, and order_types
    # above omits GTT. Advertising gtt_native=True would have a `gtt` variety
    # silently placed as a plain order (losing the trigger). Keep it False.
    gtt_native=False,
    modify_qty_supported=True,
    modify_after_partial_fill=False,
)


class OpenAlgoAdapter(BrokerAdapter):
    """Bridge :class:`BrokerAdapter` that forwards to OpenAlgo (contract §5).

    Args:
        default_client: An ``OpenAlgoClient`` used when a session does not select
            a specific one — the common single-instance case.
        client_factory: Optional ``Session -> OpenAlgoClient`` for multi-account
            setups where each OpenAlgo account has its own host/api-key (built
            from ``session.extra``). Takes precedence over ``default_client``.
    """

    def __init__(
        self,
        default_client: "OpenAlgoClient | None" = None,
        *,
        client_factory: "Callable[[Session], OpenAlgoClient] | None" = None,
    ) -> None:
        self._default_client = default_client
        self._client_factory = client_factory

    # ---------- identity + capabilities ----------

    @property
    def broker_id(self) -> str:
        return "openalgo"

    @property
    def capabilities(self) -> Capabilities:
        return OPENALGO_CAPABILITIES

    # ---------- client resolution ----------

    def _client(self, session: Session) -> "OpenAlgoClient":
        if self._client_factory is not None:
            return self._client_factory(session)
        if self._default_client is not None:
            return self._default_client
        raise UnsupportedCapabilityError(
            "OpenAlgoAdapter has no client configured — pass default_client or client_factory"
        )

    # ---------- auth lifecycle ----------

    async def login(self, credentials: dict) -> Session:
        """Build a Session from an OpenAlgo api-key (no clock-based expiry)."""
        return Session(
            access_token=str(credentials.get("api_key", "")),
            expires_at=_FAR_FUTURE,
            account_id=str(credentials.get("account_id", "default")),
            adapter_id="openalgo",
            extra={
                k: credentials[k]
                for k in ("host", "ws_port", "strategy")
                if k in credentials
            },
        )

    async def refresh(self, session: Session) -> Session:
        # OpenAlgo api-keys do not expire on a clock; nothing to refresh.
        return session

    async def logout(self, session: Session) -> None:
        # api-key auth has no server-side session to invalidate. Idempotent no-op.
        return None

    # ---------- trading: writes (router-only) ----------

    async def place_order(self, session: Session, order: "Order", *, _router_token: object | None = None) -> str:
        self._require_router_token(_router_token, _ROUTER_TOKEN)
        # Honesty guard (audit HIGH): this bridge forwards a plain order to
        # OpenAlgo's /placeorder, which fires IMMEDIATELY — it has no resting
        # trigger semantics. A non-regular variety (gtt/forever, bracket, cover,
        # iceberg, conditional) carries a trigger/OCO/validity contract the
        # forward silently drops, so a "working order that rests until the
        # trigger fires" would instead be placed NOW. Refuse honestly rather
        # than downgrade. (capabilities advertises gtt/bracket/cover/iceberg as
        # not native; the route maps UnsupportedCapabilityError to a 501.)
        variety = str(getattr(order, "variety", "") or "").strip().lower()
        if variety not in ("", "regular"):
            raise UnsupportedCapabilityError(
                f"OpenAlgo bridge adapter does not support {variety!r} orders — it forwards a plain "
                "immediate order with no resting trigger. Route forever/GTT, bracket, cover, iceberg "
                "and conditional orders to a native broker adapter (Dhan/Upstox/…)."
            )
        with self._mapped("order placement"):
            resp = await self._client(session).place_order(order)
        return self._order_id_or_raise(resp)

    async def modify_order(
        self, session: Session, order_id: str, changes: dict, *, _router_token: object | None = None
    ) -> None:
        self._require_router_token(_router_token, _ROUTER_TOKEN)
        with self._mapped("order modification"):
            modify = ModifyOrder(orderid=order_id, **changes)
            resp = await self._client(session).modify_order(modify)
        self._order_id_or_raise(resp)

    async def cancel_order(
        self, session: Session, order_id: str, *, _router_token: object | None = None
    ) -> None:
        self._require_router_token(_router_token, _ROUTER_TOKEN)
        strategy = str(session.extra.get("strategy", "Flint"))
        with self._mapped("order cancellation"):
            resp = await self._client(session).cancel_order(order_id, strategy=strategy)
        self._order_id_or_raise(resp)

    # ---------- trading: reads ----------

    async def order_book(self, session: Session) -> "list[Order]":
        with self._mapped("order_book"):
            return await self._client(session).orderbook()  # type: ignore[return-value]

    async def trade_book(self, session: Session) -> "list[Trade]":
        with self._mapped("trade_book"):
            return await self._client(session).tradebook()

    async def positions(self, session: Session) -> "list[Position]":
        with self._mapped("positions"):
            return await self._client(session).positionbook()

    async def holdings(self, session: Session) -> list[dict]:
        with self._mapped("holdings"):
            return await self._client(session).holdings()  # type: ignore[return-value]

    async def funds(self, session: Session) -> dict:
        with self._mapped("funds"):
            funds = await self._client(session).funds()
        return funds if isinstance(funds, dict) else getattr(funds, "__dict__", {"funds": funds})

    # ---------- market data: rest ----------

    async def quotes(self, session: Session, symbols: list[str]) -> "list[Quote]":
        payload = [self._split_symbol(s) for s in symbols]
        with self._mapped("quotes"):
            return await self._client(session).multi_quotes(payload)

    async def historical(self, session: Session, req: dict) -> "Candles":
        with self._mapped("historical"):
            return await self._client(session).history(**req)  # type: ignore[return-value]

    async def option_chain(self, session: Session, req: dict) -> "OptionChain":
        symbol = str(req.get("symbol", ""))
        exchange = str(req.get("exchange", "NFO"))
        expiry = str(req.get("expiry") or req.get("expiry_date") or "")
        with self._mapped("option_chain"):
            return await self._client(session).option_chain(symbol, exchange, expiry)

    # ---------- market data: streaming (not exposed by the REST bridge) ----------

    def stream(self, session: Session) -> AsyncIterator["TickEvent"]:  # type: ignore[name-defined]  # noqa: F821
        raise UnsupportedCapabilityError(
            "OpenAlgo bridge adapter does not expose tick streaming; route data.ticks to a native adapter"
        )

    async def subscribe(self, session: Session, symbols: list[str], mode: str = "FULL") -> None:
        raise UnsupportedCapabilityError("OpenAlgo bridge adapter does not expose tick subscription")

    async def unsubscribe(self, session: Session, symbols: list[str]) -> None:
        raise UnsupportedCapabilityError("OpenAlgo bridge adapter does not expose tick subscription")

    # ---------- reconciliation (later wave) ----------

    async def reconcile(self, session: Session) -> "ReconciliationReport":
        raise UnsupportedCapabilityError("OpenAlgo bridge adapter reconciliation is a later wave")

    # ---------- helpers ----------

    @staticmethod
    def _split_symbol(symbol: str) -> dict[str, str]:
        """Parse ``'EXCHANGE:SYMBOL'`` (or bare ``'SYMBOL'``, default NSE)."""
        if ":" in symbol:
            exchange, _, sym = symbol.partition(":")
            return {"symbol": sym, "exchange": exchange}
        return {"symbol": symbol, "exchange": "NSE"}

    @staticmethod
    def _order_id_or_raise(resp: Any) -> str:
        """Extract the order id from an OpenAlgo OrderResponse, raising on failure."""
        status = str(getattr(resp, "status", "") or "").lower()
        order_id = str(getattr(resp, "orderid", "") or "")
        if status and status not in ("success", "ok"):
            raise OrderRejectedByBroker(
                f"OpenAlgo rejected the order (status={status!r}, orderid={order_id!r})"
            )
        return order_id

    class _MapBrokerErrors:
        """Context manager mapping OpenAlgo client errors to the broker taxonomy (§7)."""

        def __init__(self, what: str) -> None:
            self._what = what

        def __enter__(self) -> "OpenAlgoAdapter._MapBrokerErrors":
            return self

        def __exit__(self, exc_type, exc, tb) -> bool:
            if exc is None:
                return False
            if isinstance(exc, BrokerError):
                return False  # already in-taxonomy (incl. OrderRejectedByBroker) — propagate as-is
            if isinstance(exc, OpenAlgoRateLimitError):
                raise RateLimitError(f"OpenAlgo rate limit during {self._what}: {exc}") from exc
            if isinstance(exc, OpenAlgoAuthError):
                raise SessionExpired(f"OpenAlgo auth failed during {self._what}: {exc}") from exc
            if isinstance(exc, APIError):
                raise BrokerError(f"OpenAlgo API error during {self._what}: {exc}") from exc
            return False  # unexpected — let it propagate

    def _mapped(self, what: str) -> "OpenAlgoAdapter._MapBrokerErrors":
        return self._MapBrokerErrors(what)
