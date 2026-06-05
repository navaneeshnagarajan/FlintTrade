"""Dhan v2 native adapter (doc-grounded against dhanhq 2.2.0).

Implements the BrokerAdapter contract for Dhan: auth, the gated write surface
(place/modify/cancel), and the portfolio reads (order book / trade book /
positions / holdings / funds). Request/response translation lives in
``dhan_mapping`` and is unit-tested; here the methods are thin wrappers that call
the dhanhq SDK on a worker thread (the SDK is synchronous) and normalise results.

Safety: writes still require the router's per-process ``_ROUTER_TOKEN`` (§8), so
a bare call raises before any Dhan request. This adapter is NOT registered in
``build_broker_router`` — it stays dormant until the operator wires it behind SDK
attestation + the algo-tag guard and provides credentials; live order placement
must be verified against the real SDK + a Dhan account.

Market-data methods (quotes/historical/option_chain) and the binary tick stream
are a separate wave and currently raise ``NotImplementedError`` honestly.
"""

from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from typing import TYPE_CHECKING, Any, AsyncIterator, Callable

from flinttrade_core.exceptions import BrokerError
from flinttrade_gateway.capabilities import (
    AuthModel,
    Capabilities,
    DepthLevels,
    OrderTypes,
    Segments,
    TickProtocol,
)

from . import dhan_mapping as M
from ._base import BrokerAdapter, Session

if TYPE_CHECKING:  # pragma: no cover - typing only
    from flinttrade_core.models import Candles, OptionChain, Order, Position, Quote, Trade
    from flinttrade_gateway.reconciliation import ReconciliationReport

_PENDING = "Dhan {0} — market-data/streaming wave pending live SDK verification"

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


def _build_dhan_client(client_id: str, access_token: str) -> Any:
    """Construct a live dhanhq 2.2.0 client (lazy import — SDK optional)."""
    from dhanhq import DhanContext, dhanhq  # noqa: PLC0415

    return dhanhq(DhanContext(client_id, access_token))


class DhanAdapter(BrokerAdapter):
    """Native Dhan adapter.

    Args:
        client_factory: ``session -> dhanhq client`` override (tests inject a
            mock). When omitted, ``login`` builds a live client and stores it on
            ``session.extra['client']``.
        security_resolver: ``(symbol, exchange) -> security_id`` — Dhan trades by
            numeric security id, so the operator must supply a scrip-master
            resolver. Common indices are resolved from a built-in fast path.
    """

    def __init__(
        self,
        *,
        client_factory: Callable[[Session], Any] | None = None,
        security_resolver: Callable[[str, str], str] | None = None,
    ) -> None:
        self._client_factory = client_factory
        self._security_resolver = security_resolver

    # ---------- identity + capabilities ----------

    @property
    def broker_id(self) -> str:
        return "dhan"

    @property
    def capabilities(self) -> Capabilities:
        return DHAN_CAPABILITIES

    # ---------- helpers ----------

    def _client(self, session: Session) -> Any:
        if self._client_factory is not None:
            return self._client_factory(session)
        client = session.extra.get("client")
        if client is None:
            raise BrokerError("Dhan client not initialised — call login() first")
        return client

    def _resolve_security(self, symbol: str, exchange: str) -> str:
        key = str(symbol).upper()
        if key in M.INDEX_SECURITY_IDS:
            return M.INDEX_SECURITY_IDS[key][0]
        if self._security_resolver is not None:
            return str(self._security_resolver(symbol, exchange))
        raise BrokerError(
            f"Cannot resolve Dhan security_id for {symbol}/{exchange} — "
            "configure a security resolver (scrip master)"
        )

    @staticmethod
    def _split_symbol(s: str) -> tuple[str, str]:
        """Split an ``"EXCHANGE:SYMBOL"`` quote key (defaults exchange to NSE)."""
        if ":" in s:
            exchange, name = s.split(":", 1)
            return exchange.strip().upper(), name.strip()
        return "NSE", s.strip()

    @staticmethod
    async def _call(fn: Callable[..., Any], *args: Any, **kwargs: Any) -> Any:
        # dhanhq is synchronous — run it off the event loop.
        return await asyncio.to_thread(fn, *args, **kwargs)

    # ---------- auth lifecycle ----------

    async def login(self, credentials: dict) -> Session:
        client_id = str(credentials.get("client_id") or credentials.get("dhan_client_id") or "")
        access_token = str(credentials.get("access_token") or "")
        if not access_token:
            raise BrokerError("Dhan login requires an access_token")
        client = None if self._client_factory is not None else _build_dhan_client(client_id, access_token)
        return Session(
            access_token=access_token,
            expires_at=datetime.now(tz=timezone.utc).timestamp() + 24 * 3600,
            account_id=client_id,
            adapter_id="dhan",
            extra={"client": client, "client_id": client_id},
        )

    async def refresh(self, session: Session) -> Session:
        # Dhan access tokens are long-lived (manual 24h renewal); nothing to do
        # until expiry, at which point a fresh login() is required.
        return session

    async def logout(self, session: Session) -> None:
        session.extra.pop("client", None)
        return None

    # ---------- trading: writes (router-only) ----------

    async def place_order(self, session: Session, order: Order, *, _router_token: object | None = None) -> str:
        self._require_router_token(_router_token, _ROUTER_TOKEN)
        security_id = self._resolve_security(order.symbol, order.exchange)
        tag = session.algo_id or None
        kwargs = M.to_place_order_kwargs(order, security_id, tag=tag)
        resp = await self._call(self._client(session).place_order, **kwargs)
        return M.extract_order_id(resp)

    async def modify_order(
        self, session: Session, order_id: str, changes: dict, *, _router_token: object | None = None
    ) -> None:
        self._require_router_token(_router_token, _ROUTER_TOKEN)
        kwargs = M.to_modify_order_kwargs(order_id, changes)
        resp = await self._call(self._client(session).modify_order, **kwargs)
        M.unwrap(resp)

    async def cancel_order(
        self, session: Session, order_id: str, *, _router_token: object | None = None
    ) -> None:
        self._require_router_token(_router_token, _ROUTER_TOKEN)
        resp = await self._call(self._client(session).cancel_order, str(order_id))
        M.unwrap(resp)

    # ---------- trading: reads ----------

    async def order_book(self, session: Session) -> list[Order]:
        resp = await self._call(self._client(session).get_order_list)
        rows = M.unwrap(resp) or []
        return [M.from_dhan_order(r) for r in rows]  # type: ignore[misc]

    async def trade_book(self, session: Session) -> list[Trade]:
        resp = await self._call(self._client(session).get_trade_book)
        rows = M.unwrap(resp) or []
        return [M.from_dhan_trade(r) for r in rows]  # type: ignore[misc]

    async def positions(self, session: Session) -> list[Position]:
        resp = await self._call(self._client(session).get_positions)
        rows = M.unwrap(resp) or []
        return [M.from_dhan_position(r) for r in rows]  # type: ignore[misc]

    async def holdings(self, session: Session) -> list[dict]:
        resp = await self._call(self._client(session).get_holdings)
        rows = M.unwrap(resp) or []
        return [M.from_dhan_holding(r) for r in rows]

    async def funds(self, session: Session) -> dict:
        resp = await self._call(self._client(session).get_fund_limits)
        return M.from_dhan_funds(resp)

    # ---------- market data: rest ----------

    async def quotes(self, session: Session, symbols: list[str]) -> list[Quote]:
        from flinttrade_core.models import Quote  # noqa: PLC0415

        # Resolve every symbol to (segment, security_id) and batch by segment.
        resolved: list[tuple[str, str, str, str]] = []
        securities: dict[str, list[Any]] = {}
        for raw in symbols:
            exchange, name = self._split_symbol(raw)
            sec_id = self._resolve_security(name, exchange)
            segment = M.to_dhan_segment(exchange)
            securities.setdefault(segment, []).append(int(sec_id) if sec_id.isdigit() else sec_id)
            resolved.append((name, exchange, segment, sec_id))

        resp = await self._call(self._client(session).quote_data, securities)

        out: list[Quote] = []
        for name, exchange, segment, sec_id in resolved:
            rec = M.quote_from_feed(segment, sec_id, resp)
            if rec is not None:
                out.append(Quote(**M.from_dhan_quote(name, exchange, rec)))
        return out

    async def historical(self, session: Session, req: dict) -> Candles:
        from flinttrade_core.models import OHLCV, Candles  # noqa: PLC0415

        symbol = str(req.get("symbol", ""))
        exchange = str(req.get("exchange", "NSE"))
        interval = str(req.get("interval", req.get("timeframe", "1m")))
        instrument = str(req.get("instrument_type", req.get("instrument", "EQUITY")))
        from_date = req.get("from_date") or req.get("start") or req.get("start_date")
        to_date = req.get("to_date") or req.get("end") or req.get("end_date")
        security_id = self._resolve_security(symbol, exchange)
        segment = M.to_dhan_segment(exchange)
        kind, minutes = M.interval_to_dhan(interval)
        client = self._client(session)
        if kind == "daily":
            resp = await self._call(
                client.historical_daily_data, security_id, segment, instrument, from_date, to_date
            )
        else:
            resp = await self._call(
                client.intraday_minute_data, security_id, segment, instrument, from_date, to_date, minutes
            )
        cd = M.to_candles_dict(symbol, exchange, interval, resp)
        return Candles(
            symbol=cd["symbol"],
            exchange=cd["exchange"],
            interval=cd["interval"],
            bars=[OHLCV(**b) for b in cd["bars"]],
        )

    async def option_chain(self, session: Session, req: dict) -> OptionChain:
        raise NotImplementedError(_PENDING.format("option_chain"))

    # ---------- market data: streaming (separate wave) ----------

    def stream(self, session: Session) -> AsyncIterator[Any]:
        raise NotImplementedError(_PENDING.format("stream"))

    async def subscribe(self, session: Session, symbols: list[str], mode: str = "FULL") -> None:
        raise NotImplementedError(_PENDING.format("subscribe"))

    async def unsubscribe(self, session: Session, symbols: list[str]) -> None:
        raise NotImplementedError(_PENDING.format("unsubscribe"))

    # ---------- reconciliation ----------

    async def reconcile(self, session: Session) -> ReconciliationReport:
        raise NotImplementedError(_PENDING.format("reconcile"))


_ROUTER_TOKEN = object()
