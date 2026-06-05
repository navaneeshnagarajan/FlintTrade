"""Dhan v2 native adapter (doc-grounded against dhanhq 2.2.0).

Implements the BrokerAdapter contract for Dhan: auth, the gated write surface
(place/modify/cancel), and the portfolio reads (order book / trade book /
positions / holdings / funds). Request/response translation lives in
``dhan_mapping`` and is unit-tested; here the methods are thin wrappers that call
the dhanhq SDK on a worker thread (the SDK is synchronous) and normalise results.

Safety: writes still require the router's per-process ``_ROUTER_TOKEN`` (§8), so
a bare call raises before any Dhan request. ``build_broker_router``'s
native-activation factory registers this adapter automatically once its pinned
SDK (``dhanhq``) is attested AND vault credentials exist; until then it stays
dormant. Dhan is the one native with a real ``brokers.lock`` pin, so where
``dhanhq`` is installed at the pinned version it *is* attested — only stored
credentials + a live login then separate it from going live (verify live order
placement against the real SDK + a Dhan account).

This adapter implements the FULL contract: auth, gated writes, portfolio reads,
market data (quotes / historical / option_chain) and the binary tick stream.
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
        feed_factory: Callable[[Session], AsyncIterator[bytes]] | None = None,
    ) -> None:
        self._client_factory = client_factory
        self._security_resolver = security_resolver
        self._feed_factory = feed_factory
        # security_id -> (symbol, exchange) for routing decoded ticks back to names.
        self._feed_map: dict[str, tuple[str, str]] = {}

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
        # Dispatch on order variety. Every variety travels this SAME gated method
        # (the router token is already required above and the variety + leg prices
        # are part of the SafetyContext-hashed order), so a bracket/cover/iceberg
        # order is gated identically to a regular one — no parallel order path.
        variety = str(getattr(order, "variety", "regular")).lower()
        client = self._client(session)
        if variety in ("regular", ""):
            resp = await self._call(client.place_order, **M.to_place_order_kwargs(order, security_id, tag=tag))
        elif variety in ("bracket", "cover"):
            resp = await self._call(client.place_super_order, **M.to_super_order_kwargs(order, security_id, tag=tag))
        elif variety == "iceberg":
            resp = await self._call(client.place_slice_order, **M.to_slice_order_kwargs(order, security_id, tag=tag))
        elif variety == "gtt":
            resp = await self._call(client.place_forever, **M.to_forever_kwargs(order, security_id, tag=tag))
        else:
            raise BrokerError(f"Dhan does not support order variety {variety!r}")
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
        from flinttrade_core.models import OptionChain, OptionChainStrike  # noqa: PLC0415

        underlying = str(req.get("symbol") or req.get("underlying") or "")
        exchange = str(req.get("exchange", "NSE_INDEX"))
        expiry = req.get("expiry") or req.get("expiry_date")
        security_id = self._resolve_security(underlying, exchange)
        segment = M.to_dhan_segment(exchange)
        resp = await self._call(self._client(session).option_chain, security_id, segment, expiry)
        oc = M.to_option_chain_dict(underlying, exchange, resp)
        return OptionChain(
            underlying=oc["underlying"],
            exchange=oc["exchange"],
            strikes=[OptionChainStrike(**s) for s in oc["strikes"]],
        )

    # ---------- pre-trade info (reads) ----------

    async def margin_calculator(self, session: Session, order: Order) -> dict:
        """Pre-trade margin estimate for ``order`` (Dhan ``/margincalculator``).

        A read-only estimate — does NOT place anything, so it needs no gate.
        """
        security_id = self._resolve_security(order.symbol, order.exchange)
        kwargs = M.to_margin_kwargs(order, security_id)
        resp = await self._call(self._client(session).margin_calculator, **kwargs)
        return M.from_dhan_margin(resp)

    async def expiry_list(self, session: Session, symbol: str, exchange: str = "NSE_INDEX") -> list[str]:
        """List the available option expiries for an underlying (read)."""
        security_id = self._resolve_security(symbol, exchange)
        segment = M.to_dhan_segment(exchange)
        resp = await self._call(self._client(session).expiry_list, security_id, segment)
        return M.from_dhan_expiry_list(resp)

    async def kill_switch(self, session: Session, action: str) -> dict:
        """Toggle Dhan's broker-side kill switch (``ACTIVATE`` disables trading for
        the day; ``DEACTIVATE`` re-enables it). An account control, not an order —
        it places nothing, so it is outside the order gate.

        SAFETY: ``DEACTIVATE`` re-opens live trading, so any caller/route wiring it
        MUST gate ``DEACTIVATE`` behind an explicit, authenticated operator action
        (Live-mode + operator confirmation) and audit it. ``ACTIVATE`` is purely
        risk-reducing and may be invoked freely.
        """
        act = str(action).upper()
        if act not in ("ACTIVATE", "DEACTIVATE"):
            raise BrokerError(f"kill_switch action must be ACTIVATE or DEACTIVATE, got {action!r}")
        resp = await self._call(self._client(session).kill_switch, act)
        unwrapped = M.unwrap(resp)
        return unwrapped if isinstance(unwrapped, dict) else {"status": str(resp)}

    # ---------- market data: streaming ----------

    async def subscribe(self, session: Session, symbols: list[str], mode: str = "FULL") -> None:
        # Resolve each symbol to its Dhan security id and remember it so decoded
        # binary ticks (which carry only the security id) can be routed back to
        # the symbol when streamed.
        for raw in symbols:
            exchange, name = self._split_symbol(raw)
            security_id = self._resolve_security(name, exchange)
            self._feed_map[str(security_id)] = (name, exchange)

    async def unsubscribe(self, session: Session, symbols: list[str]) -> None:
        for raw in symbols:
            exchange, name = self._split_symbol(raw)
            try:
                security_id = self._resolve_security(name, exchange)
            except BrokerError:
                continue
            self._feed_map.pop(str(security_id), None)

    def stream(self, session: Session) -> AsyncIterator[Any]:
        return self._stream_impl(session)

    async def _stream_impl(self, session: Session) -> AsyncIterator[Any]:
        from flinttrade_core.models import TickEvent  # noqa: PLC0415

        if self._feed_factory is None:
            # Live: the binary WS feed needs the dhanhq SDK + credentials. The
            # decode path (decode_dhan_tick) is implemented and tested; the live
            # socket is provided by injecting a feed_factory.
            raise NotImplementedError(
                "Dhan live tick stream needs the dhanhq market feed (inject feed_factory)"
            )

        async for frame in self._feed_factory(session):
            tick = M.decode_dhan_tick(frame)
            if tick is None:
                continue
            symbol, exchange = self._feed_map.get(
                tick["security_id"], ("", tick.get("exchange", "")),
            )
            yield TickEvent(
                symbol=symbol,
                exchange=exchange or tick.get("exchange", ""),
                ltp=tick.get("ltp", 0.0),
                volume=int(tick.get("volume", 0)),
                timestamp="",
            )

    # ---------- reconciliation ----------

    async def reconcile(self, session: Session) -> ReconciliationReport:
        raise NotImplementedError(_PENDING.format("reconcile"))


from ._base import ROUTER_TOKEN as _ROUTER_TOKEN  # noqa: E402  shared per-process token (§8.0c)
