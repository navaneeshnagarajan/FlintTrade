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

This adapter implements the FULL contract plus the complete Dhan v2.x surface
(through v2.5): auth, gated writes (regular / bracket / cover / iceberg /
forever / super / conditional-trigger), portfolio reads + convert position,
market data (quotes / historical / option chain / expired rolling options),
EDIS, Trader's Control (kill switch + P&L-based exit + Exit All), static-IP
management, the binary tick stream, the order-update stream and the 20/200-level
depth streams. v2.5 endpoints absent from the pinned SDK (dhanhq 2.2.0) are
called through the SDK's own ``DhanHTTP`` transport with doc-grounded paths.
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
    from flinttrade_gateway.reconciliation import LocalStateSnapshot, ReconciliationReport

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
    # Intraday history reaches ~5 years back (historical-data.md "for last 5
    # years"); the documented 90-day cap is the per-REQUEST date range, not the
    # lookback, so it is noted here, not encoded as the lookback. Dhan documents
    # no max-candles-per-request limit (it caps by date range), so 0 = unknown.
    historical_max_lookback_days_intraday=1825,  # ~5 years (90 days = per-request range cap)
    historical_max_lookback_days_daily=None,
    historical_max_candles_per_request=0,
    historical_intraday_intervals_minutes=[1, 5, 15, 25, 60],
    option_chain_supported=True,
    option_chain_greeks_supported=True,
    option_chain_rate_limit_seconds=3,
    # Dhan's edge: historical option-chain / options-OHLC with rolling expiry
    # series (a strike's history readable across its expiry rollover).
    options_history_supported=True,
    options_history_rolling=True,
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


def _build_dhan_login(client_id: str) -> Any:
    """Construct a live ``DhanLogin`` auth helper (lazy import — SDK optional)."""
    from dhanhq import DhanLogin  # noqa: PLC0415

    return DhanLogin(client_id)


def _download_text(url: str) -> str:
    """Fetch a (HTTPS-only) text resource — the scrip-master CSV downloader."""
    if not url.startswith("https://"):
        raise BrokerError(f"Refusing non-HTTPS scrip master URL: {url!r}")
    from urllib.request import urlopen  # noqa: PLC0415

    with urlopen(url, timeout=60) as response:  # noqa: S310 - scheme pinned to https above
        return response.read().decode("utf-8", errors="replace")


class DhanAdapter(BrokerAdapter):
    """Native Dhan adapter.

    Args:
        client_factory: ``session -> dhanhq client`` override (tests inject a
            mock). When omitted, ``login`` builds a live client and stores it on
            ``session.extra['client']``.
        security_resolver: ``(symbol, exchange) -> security_id`` — Dhan trades by
            numeric security id, so the operator must supply a scrip-master
            resolver (see :meth:`fetch_security_list` +
            ``dhan_mapping.build_security_resolver``). Common indices are
            resolved from a built-in fast path.
        feed_factory: ``session -> async iterator of binary frames`` for the
            live tick stream (tests inject synthetic frames; live wiring uses
            the dhanhq market feed).
        order_feed_factory: ``session -> async iterator of JSON frames`` for the
            order-update stream. When omitted, a live socket to
            ``wss://api-order-update.dhan.co`` is opened (the documented
            transport behind the SDK's ``orderupdate.OrderUpdate``).
        depth_feed_factory: ``(session, level) -> async iterator of binary
            frames`` for the 20/200-level depth streams (live sockets:
            ``wss://depth-api-feed.dhan.co/twentydepth`` and
            ``wss://full-depth-api.dhan.co/twohundreddepth``, the transports
            behind the SDK's ``fulldepth.FullDepth``).
        login_factory: ``client_id -> DhanLogin-like`` override for the auth
            surface (token generation / renewal / static-IP management).
        local_state_provider: ``session -> LocalStateSnapshot`` supplying the
            flinttrade-side mirror that ``reconcile`` diffs broker state
            against. Defaults to EMPTY local state (every broker-side row then
            surfaces as ``exists_only_on_broker``) until the engine wave wires
            the journal-backed provider.
    """

    def __init__(
        self,
        *,
        client_factory: Callable[[Session], Any] | None = None,
        security_resolver: Callable[[str, str], str] | None = None,
        feed_factory: Callable[[Session], AsyncIterator[bytes]] | None = None,
        order_feed_factory: Callable[[Session], AsyncIterator[Any]] | None = None,
        depth_feed_factory: Callable[[Session, int], AsyncIterator[bytes]] | None = None,
        login_factory: Callable[[str], Any] | None = None,
        local_state_provider: Callable[[Session], LocalStateSnapshot] | None = None,
    ) -> None:
        self._client_factory = client_factory
        self._security_resolver = security_resolver
        self._feed_factory = feed_factory
        self._order_feed_factory = order_feed_factory
        self._depth_feed_factory = depth_feed_factory
        self._login_factory = login_factory
        self._local_state_provider = local_state_provider
        # security_id -> (symbol, exchange) for routing decoded ticks back to names.
        self._feed_map: dict[str, tuple[str, str]] = {}
        # security_id -> requested feed RequestCode (TICKER/QUOTE/FULL).
        self._feed_modes: dict[str, int] = {}

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

    def _http(self, session: Session) -> Any:
        """The SDK's ``DhanHTTP`` transport — used for v2.5 endpoints that the
        pinned SDK (2.2.0) does not wrap (conditional triggers, P&L exit,
        Exit All). Doc-grounded paths live in ``dhan_mapping``."""
        http = getattr(self._client(session), "dhan_http", None)
        if http is None:
            raise BrokerError("Dhan client exposes no DhanHTTP transport (dhan_http)")
        return http

    def _login_helper(self, client_id: str) -> Any:
        """A ``DhanLogin``-shaped auth helper for the token/IP surface."""
        if self._login_factory is not None:
            return self._login_factory(client_id)
        return _build_dhan_login(client_id)

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
        pin = str(credentials.get("pin") or "")
        totp = str(credentials.get("totp") or "")
        if not access_token and pin and totp:
            # PIN + TOTP path: mint a fresh 24h token via the v2.5 token API
            # (generate_token needs no existing token), then log in with it. Lets
            # an operator connect without pasting a console-generated token —
            # requires TOTP enabled on the account.
            if not client_id:
                raise BrokerError("Dhan PIN+TOTP login requires client_id")
            resp = await self.generate_token(client_id, pin, totp)
            access_token = str(resp.get("accessToken") or resp.get("access_token") or "")
            if not access_token:
                raise BrokerError(f"Dhan PIN+TOTP token generation failed: {resp}")
        if not access_token:
            raise BrokerError("Dhan login requires an access_token (or client_id + pin + totp)")
        client = None if self._client_factory is not None else _build_dhan_client(client_id, access_token)
        return Session(
            access_token=access_token,
            expires_at=datetime.now(tz=timezone.utc).timestamp() + 24 * 3600,
            account_id=client_id,
            adapter_id="dhan",
            extra={"client": client, "client_id": client_id},
        )

    def replay_credentials(self, credentials: dict, session: Session) -> dict:
        """The replayable vault payload after a successful login (G7).

        A pasted TOTP is a 30-second one-time code — replaying it at the next
        boot is guaranteed to fail. Swap it for the minted 24h ``access_token``
        (restart-within-validity reconnects cleanly); keep ``client_id`` and
        ``pin`` so a UI-assisted re-auth only needs a fresh TOTP.
        """
        replayable = {k: v for k, v in credentials.items() if k != "totp"}
        replayable["access_token"] = session.access_token
        return replayable

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
        elif variety == "amo":
            # After-market order: POST /orders directly via DhanHTTP with the
            # afterMarketOrder flag + amoTime pump window. We bypass the SDK's
            # place_order because dhanhq 2.2.0 drops amoTime from its payload
            # (so the pump window would never reach the broker) — see
            # to_amo_order_payload. Still the SAME gated method/variety dispatch.
            resp = await self._call(
                self._http(session).post, M.ORDERS_ENDPOINT, M.to_amo_order_payload(order, security_id, tag=tag)
            )
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

    # ---------- trading: forever (GTT) management (router-only writes) ----------

    async def modify_forever(
        self, session: Session, order_id: str, changes: dict, *, _router_token: object | None = None
    ) -> None:
        """Modify a resting forever (GTT) order (``PUT /forever/orders/{id}``)."""
        self._require_router_token(_router_token, _ROUTER_TOKEN)
        kwargs = M.to_modify_forever_kwargs(order_id, changes)
        resp = await self._call(self._client(session).modify_forever, **kwargs)
        M.unwrap(resp)

    async def cancel_forever(
        self, session: Session, order_id: str, *, _router_token: object | None = None
    ) -> None:
        """Cancel a resting forever (GTT) order (``DELETE /forever/orders/{id}``)."""
        self._require_router_token(_router_token, _ROUTER_TOKEN)
        resp = await self._call(self._client(session).cancel_forever, str(order_id))
        M.unwrap(resp)

    async def forever_orders(self, session: Session) -> list[dict]:
        """List all resting forever (GTT) orders (``GET /forever/orders``) — a read."""
        resp = await self._call(self._client(session).get_forever)
        rows = M.unwrap(resp) or []
        return [M.from_dhan_forever_order(r) for r in rows if isinstance(r, dict)]

    # ---------- trading: super-order management (router-only writes) ----------

    async def modify_super_order(
        self, session: Session, order_id: str, changes: dict, *, _router_token: object | None = None
    ) -> None:
        """Modify one leg of a pending super order (``PUT /super/orders/{id}``).

        ``changes['leg_name']`` selects ENTRY_LEG / TARGET_LEG / STOP_LOSS_LEG;
        the mapping layer builds the leg-appropriate payload.
        """
        self._require_router_token(_router_token, _ROUTER_TOKEN)
        kwargs = M.to_modify_super_order_kwargs(order_id, changes)
        resp = await self._call(self._client(session).modify_super_order, **kwargs)
        M.unwrap(resp)

    async def cancel_super_order(
        self, session: Session, order_id: str, leg: str = "ENTRY_LEG", *, _router_token: object | None = None
    ) -> None:
        """Cancel a super order or one leg (``DELETE /super/orders/{id}/{leg}``).

        Cancelling ENTRY_LEG cancels every leg; a target/stop-loss leg cancelled
        individually cannot be re-added later (super-order.md).
        """
        self._require_router_token(_router_token, _ROUTER_TOKEN)
        leg_name = str(leg).upper()
        if leg_name not in M.SUPER_ORDER_LEGS:
            raise BrokerError(f"Super order leg must be one of {M.SUPER_ORDER_LEGS}, got {leg!r}")
        resp = await self._call(self._client(session).cancel_super_order, str(order_id), leg_name)
        M.unwrap(resp)

    async def super_orders(self, session: Session) -> list[dict]:
        """List all super orders with nested leg details (``GET /super/orders``) — a read."""
        resp = await self._call(self._client(session).get_super_order_list)
        rows = M.unwrap(resp) or []
        return [M.from_dhan_super_order(r) for r in rows if isinstance(r, dict)]

    # ---------- trading: conditional triggers (v2.5; router-only writes) ----------

    async def place_conditional_trigger(
        self, session: Session, condition: dict, orders: list[Order], *, _router_token: object | None = None
    ) -> str:
        """Place a conditional trigger (``POST /alerts/orders``, v2.5) and return its alert id.

        The trigger fires the supplied order legs when the price/indicator
        condition is met, so it is trade-affecting and traverses the same
        router gate as a direct order. The pinned SDK (2.2.0) has no wrapper,
        so the documented endpoint is called via the SDK's ``DhanHTTP``.
        """
        self._require_router_token(_router_token, _ROUTER_TOKEN)
        legs = [M.to_conditional_order_leg(o, self._resolve_security(o.symbol, o.exchange)) for o in orders]
        payload = M.to_conditional_trigger_payload(condition, legs)
        resp = await self._call(self._http(session).post, M.CONDITIONAL_TRIGGER_ENDPOINT, payload)
        return M.extract_alert_id(resp)

    async def modify_conditional_trigger(
        self,
        session: Session,
        alert_id: str,
        condition: dict,
        orders: list[Order],
        *,
        _router_token: object | None = None,
    ) -> None:
        """Modify a conditional trigger (``PUT /alerts/orders/{alertId}``, v2.5)."""
        self._require_router_token(_router_token, _ROUTER_TOKEN)
        legs = [M.to_conditional_order_leg(o, self._resolve_security(o.symbol, o.exchange)) for o in orders]
        payload = M.to_conditional_trigger_payload(condition, legs)
        payload["alertId"] = str(alert_id)
        resp = await self._call(self._http(session).put, f"{M.CONDITIONAL_TRIGGER_ENDPOINT}/{alert_id}", payload)
        M.unwrap(resp)

    async def cancel_conditional_trigger(
        self, session: Session, alert_id: str, *, _router_token: object | None = None
    ) -> None:
        """Delete a conditional trigger (``DELETE /alerts/orders/{alertId}``, v2.5)."""
        self._require_router_token(_router_token, _ROUTER_TOKEN)
        resp = await self._call(self._http(session).delete, f"{M.CONDITIONAL_TRIGGER_ENDPOINT}/{alert_id}")
        M.unwrap(resp)

    async def conditional_triggers(self, session: Session) -> list[dict]:
        """List all conditional triggers (``GET /alerts/orders``, v2.5) — a read."""
        resp = await self._call(self._http(session).get, M.CONDITIONAL_TRIGGER_ENDPOINT)
        rows = M.unwrap(resp) or []
        return [M.from_dhan_conditional_trigger(r) for r in rows if isinstance(r, dict)]

    async def get_conditional_trigger(self, session: Session, alert_id: str) -> dict:
        """Fetch one conditional trigger by alert id (``GET /alerts/orders/{alertId}``) — a read."""
        resp = await self._call(self._http(session).get, f"{M.CONDITIONAL_TRIGGER_ENDPOINT}/{alert_id}")
        data = M.unwrap(resp)
        return M.from_dhan_conditional_trigger(data if isinstance(data, dict) else {})

    # ---------- trading: portfolio writes (router-only) ----------

    async def convert_position(
        self, session: Session, req: dict, *, _router_token: object | None = None
    ) -> None:
        """Convert an open position intraday↔delivery (``POST /positions/convert``).

        ``req`` carries symbol/exchange (or an explicit ``security_id``),
        ``from_product`` / ``to_product``, ``position_type`` and ``quantity``.
        Changing a position's product changes margin treatment, so this is a
        gated write like any order mutation.
        """
        self._require_router_token(_router_token, _ROUTER_TOKEN)
        security_id = str(req.get("security_id") or self._resolve_security(
            str(req.get("symbol", "")), str(req.get("exchange", "NSE"))
        ))
        kwargs = M.to_convert_position_kwargs(req, security_id)
        resp = await self._call(self._client(session).convert_position, **kwargs)
        M.unwrap(resp)

    async def exit_all_positions(self, session: Session, *, _router_token: object | None = None) -> dict:
        """Exit ALL active positions and cancel ALL open orders (``DELETE /positions``, v2.5).

        SAFETY: this is the broker-side flatten-everything control. It places
        live exit orders for every open position, so it is router-gated like
        any other trade-affecting call, and any caller/route wiring it MUST
        additionally gate it behind an explicit, authenticated operator action
        (Live-mode + operator confirmation) and audit it.
        """
        self._require_router_token(_router_token, _ROUTER_TOKEN)
        resp = await self._call(self._http(session).delete, M.EXIT_ALL_ENDPOINT)
        data = M.unwrap(resp)
        return data if isinstance(data, dict) else {"status": str(data)}

    # ---------- trading: reads ----------

    async def order_book(self, session: Session) -> list[Order]:
        resp = await self._call(self._client(session).get_order_list)
        rows = M.unwrap(resp) or []
        return [M.from_dhan_order(r) for r in rows]  # type: ignore[misc]

    async def get_order_by_id(self, session: Session, order_id: str) -> dict:
        """Fetch one order's current status by Dhan order id (``GET /orders/{id}``)."""
        resp = await self._call(self._client(session).get_order_by_id, str(order_id))
        data = M.unwrap(resp)
        if isinstance(data, list):  # Dhan returns a single-element array for this endpoint
            data = data[0] if data else {}
        return M.from_dhan_order(data if isinstance(data, dict) else {})

    async def get_order_by_correlation_id(self, session: Session, correlation_id: str) -> dict:
        """Fetch one order by the caller-supplied correlation id (``GET /orders/external/{id}``)."""
        resp = await self._call(self._client(session).get_order_by_correlationID, str(correlation_id))
        data = M.unwrap(resp)
        if isinstance(data, list):
            data = data[0] if data else {}
        return M.from_dhan_order(data if isinstance(data, dict) else {})

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

    async def trade_history(
        self, session: Session, from_date: str, to_date: str, page: int = 0
    ) -> list[dict]:
        """Historical trade statement for a date range (Dhan ``/trades``) — a read."""
        resp = await self._call(self._client(session).get_trade_history, from_date, to_date, page)
        return M.from_dhan_statement_list(resp)

    async def ledger(self, session: Session, from_date: str, to_date: str) -> list[dict]:
        """Ledger / funds statement for a date range (Dhan ledger report) — a read."""
        resp = await self._call(self._client(session).ledger_report, from_date, to_date)
        return M.from_dhan_statement_list(resp)

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

    async def kill_switch_status(self, session: Session) -> dict:
        """Read the kill-switch state for the account (``GET /killswitch``) — a read."""
        resp = await self._call(self._client(session).status_kill_switch)
        data = M.unwrap(resp)
        return data if isinstance(data, dict) else {"status": str(data)}

    # ---------- trader's control: P&L based exit (v2.5) ----------

    async def set_pnl_exit(
        self,
        session: Session,
        profit_value: float,
        loss_value: float,
        product_types: list[str] | None = None,
        enable_kill_switch: bool = False,
    ) -> dict:
        """Configure the day's P&L-based auto-exit (``POST /pnlExit``, v2.5).

        A purely risk-reducing account control (it can only flatten positions
        when thresholds breach), so like ``kill_switch`` ACTIVATE it sits
        outside the order gate. Resets at the end of the trading session.
        """
        payload = M.to_pnl_exit_payload(profit_value, loss_value, product_types, enable_kill_switch)
        resp = await self._call(self._http(session).post, M.PNL_EXIT_ENDPOINT, payload)
        data = M.unwrap(resp)
        return data if isinstance(data, dict) else {"status": str(data)}

    async def stop_pnl_exit(self, session: Session) -> dict:
        """Disable the active P&L-based exit configuration (``DELETE /pnlExit``, v2.5).

        SAFETY: stopping the P&L exit REMOVES a protective control, so any
        caller/route wiring it MUST gate it behind an explicit, authenticated
        operator action (Live-mode + operator confirmation) and audit it —
        the same pattern as ``kill_switch`` DEACTIVATE. Configuring
        (:meth:`set_pnl_exit`) is risk-reducing and may be invoked freely.
        """
        resp = await self._call(self._http(session).delete, M.PNL_EXIT_ENDPOINT)
        data = M.unwrap(resp)
        return data if isinstance(data, dict) else {"status": str(data)}

    async def get_pnl_exit(self, session: Session) -> dict:
        """Read the currently active P&L-based exit configuration (``GET /pnlExit``) — a read."""
        resp = await self._call(self._http(session).get, M.PNL_EXIT_ENDPOINT)
        data = M.unwrap(resp)
        return data if isinstance(data, dict) else {"status": str(data)}

    # ---------- EDIS (sell-side demat authorisation) ----------

    async def generate_tpin(self, session: Session) -> dict:
        """Trigger a CDSL T-PIN to the registered mobile (``GET /edis/tpin``) — a read-shaped trigger."""
        resp = await self._call(self._client(session).generate_tpin)
        return resp if isinstance(resp, dict) else {"status": str(resp)}

    async def edis_form(
        self, session: Session, isin: str, qty: int, exchange: str, segment: str = "EQ", bulk: bool = False
    ) -> dict:
        """Fetch the escaped CDSL eDIS form HTML (``POST /edis/form``) — headless.

        The SDK's ``open_browser_for_tpin`` writes a temp file and opens a
        browser, which is useless on a server — so the documented endpoint is
        called directly and the (unescaped) form HTML is returned for the
        caller to render. The form posts to CDSL where the operator enters
        their T-PIN; FlintTrade never sees it.
        """
        payload = {
            "isin": str(isin),
            "qty": int(qty),
            "exchange": str(exchange).upper(),
            "segment": str(segment).upper(),
            "bulk": bool(bulk),
        }
        resp = await self._call(self._http(session).post, "/edis/form", payload)
        data = M.unwrap(resp)
        if not isinstance(data, dict):
            return {"edis_form_html": ""}
        html = str(data.get("edisFormHtml", "")).replace("\\", "")
        return {**data, "edis_form_html": html}

    async def edis_inquiry(self, session: Session, isin: str = "ALL") -> dict:
        """Check eDIS approval status for an ISIN, or ``\"ALL\"`` (``GET /edis/inquire/{isin}``)."""
        resp = await self._call(self._client(session).edis_inquiry, str(isin))
        data = M.unwrap(resp)
        return data if isinstance(data, dict) else {"status": str(data)}

    # ---------- auth surface (token + static IP management) ----------

    async def user_profile(self, session: Session) -> dict:
        """Validate the token / account setup (``GET /profile``) — a read."""
        login = self._login_helper(str(session.extra.get("client_id") or session.account_id))
        resp = await self._call(login.user_profile, session.access_token)
        return resp if isinstance(resp, dict) else {"status": str(resp)}

    async def generate_token(self, client_id: str, pin: str, totp: str) -> dict:
        """Generate a fresh 24h access token via PIN + TOTP (v2.5 token API).

        Pre-session auth: needs no existing token, so it takes the client id
        directly. Returns Dhan's response (``accessToken`` + ``expiryTime``);
        feed it to :meth:`login` to mint a Session.
        """
        login = self._login_helper(str(client_id))
        resp = await self._call(login.generate_token, str(pin), str(totp))
        return resp if isinstance(resp, dict) else {"status": str(resp)}

    async def renew_token(self, session: Session) -> dict:
        """Renew a still-active access token for another 24h (``GET /RenewToken``).

        Returns Dhan's response (new ``accessToken``); the caller re-runs
        :meth:`login` with it — the adapter does not mutate the old Session.
        """
        login = self._login_helper(str(session.extra.get("client_id") or session.account_id))
        resp = await self._call(login.renew_token, session.access_token)
        return resp if isinstance(resp, dict) else {"status": str(resp)}

    async def set_ip(self, session: Session, ip: str, ip_flag: str = "PRIMARY") -> dict:
        """Whitelist a static IP for order placement (``POST /ip/setIP``).

        Once set, an IP cannot be modified for 7 days (authentication.md).
        """
        login = self._login_helper(str(session.extra.get("client_id") or session.account_id))
        resp = await self._call(login.set_ip, session.access_token, str(ip), str(ip_flag).upper())
        data = M.unwrap(resp)
        return data if isinstance(data, dict) else {"status": str(data)}

    async def modify_ip(self, session: Session, ip: str, ip_flag: str = "PRIMARY") -> dict:
        """Modify the whitelisted static IP (``PUT /ip/modifyIP``; once per 7 days)."""
        login = self._login_helper(str(session.extra.get("client_id") or session.account_id))
        resp = await self._call(login.modify_ip, session.access_token, str(ip), str(ip_flag).upper())
        data = M.unwrap(resp)
        return data if isinstance(data, dict) else {"status": str(data)}

    async def get_ip(self, session: Session) -> dict:
        """Read the currently whitelisted static IPs (``GET /ip/getIP``) — a read."""
        login = self._login_helper(str(session.extra.get("client_id") or session.account_id))
        resp = await self._call(login.get_ip, session.access_token)
        data = M.unwrap(resp)
        return data if isinstance(data, dict) else {"status": str(data)}

    # ---------- instruments (scrip master) ----------

    async def fetch_security_list(
        self, mode: str = "compact", *, downloader: Callable[[str], str] | None = None
    ) -> list[dict]:
        """Download + parse the Dhan scrip master CSV (instruments.md).

        Returns the rows as dicts keyed by the CSV header tags (``SEM_*`` for
        compact). Feed the rows to ``dhan_mapping.build_security_resolver`` to
        obtain a ``security_resolver`` for this adapter. ``downloader`` is
        injectable for tests; the default fetches over HTTPS via stdlib.
        """
        url = M.SCRIP_MASTER_URLS.get(str(mode).lower())
        if url is None:
            raise BrokerError(f"Scrip master mode must be 'compact' or 'detailed', got {mode!r}")
        fetch = downloader or _download_text
        text = await self._call(fetch, url)
        import csv  # noqa: PLC0415
        import io  # noqa: PLC0415

        return [dict(row) for row in csv.DictReader(io.StringIO(text))]

    # ---------- market data: expired (rolling) options ----------

    async def expired_options(self, session: Session, req: dict) -> dict:
        """Historical expired-options data on a rolling basis (``POST /charts/rollingoption``).

        Dhan's edge feature: up to 5 years of strike-relative (ATM±n) options
        history readable ACROSS expiry rollovers — this backs the advertised
        ``options_history_supported`` / ``options_history_rolling`` capability.
        ``req`` carries symbol/exchange (or ``security_id``), ``expiry_flag``
        (WEEK/MONTH), ``expiry_code``, ``strike`` (e.g. ``"ATM"``),
        ``option_type`` (CALL/PUT), ``required_data``, dates and ``interval``.
        """
        security_id = str(req.get("security_id") or self._resolve_security(
            str(req.get("symbol", req.get("underlying", ""))), str(req.get("exchange", "NFO"))
        ))
        kwargs = M.to_expired_options_kwargs(req, security_id)
        resp = await self._call(self._client(session).expired_options_data, **kwargs)
        return M.from_dhan_expired_options(resp)

    # ---------- market data: streaming ----------

    async def subscribe(self, session: Session, symbols: list[str], mode: str = "FULL") -> None:
        # Resolve each symbol to its Dhan security id and remember it so decoded
        # binary ticks (which carry only the security id) can be routed back to
        # the symbol when streamed. The mode maps to the v2 feed RequestCode
        # (TICKER=15 / QUOTE=17 / FULL=21 — the SDK marketfeed constants) and is
        # recorded per instrument for the live feed wiring.
        request_code = M.subscribe_mode_to_request_code(mode)
        for raw in symbols:
            exchange, name = self._split_symbol(raw)
            security_id = self._resolve_security(name, exchange)
            self._feed_map[str(security_id)] = (name, exchange)
            self._feed_modes[str(security_id)] = request_code

    async def unsubscribe(self, session: Session, symbols: list[str]) -> None:
        for raw in symbols:
            exchange, name = self._split_symbol(raw)
            try:
                security_id = self._resolve_security(name, exchange)
            except BrokerError:
                continue
            self._feed_map.pop(str(security_id), None)
            self._feed_modes.pop(str(security_id), None)

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

    # ---------- order-update streaming ----------

    def stream_order_updates(self, session: Session) -> AsyncIterator[dict]:
        """Open the live order-update stream and yield normalised update dicts.

        Frames arrive as JSON over ``wss://api-order-update.dhan.co``
        (order-update.md); non-``order_alert`` frames are skipped. Tests inject
        ``order_feed_factory``; live runs open the documented socket (the
        transport behind the SDK's ``orderupdate.OrderUpdate``).
        """
        return self._order_updates_impl(session)

    async def _order_updates_impl(self, session: Session) -> AsyncIterator[dict]:
        if self._order_feed_factory is not None:
            frames = self._order_feed_factory(session)
        else:
            frames = self._live_order_update_frames(session)
        async for frame in frames:
            update = M.decode_order_update(frame)
            if update is not None:
                yield update

    async def _live_order_update_frames(self, session: Session) -> AsyncIterator[Any]:
        """Live order-update socket: authorise (MsgCode 42) then relay frames."""
        import json  # noqa: PLC0415

        try:
            import websockets  # noqa: PLC0415
        except ImportError as exc:  # pragma: no cover - environment-dependent
            raise BrokerError("Dhan order-update stream needs the 'websockets' package") from exc

        client_id = str(session.extra.get("client_id") or session.account_id)
        async with websockets.connect(M.ORDER_UPDATE_WSS) as ws:  # pragma: no cover - live socket
            await ws.send(json.dumps(M.order_update_login_payload(client_id, session.access_token)))
            async for message in ws:
                yield message

    # ---------- market depth streaming (20 / 200 level) ----------

    def stream_depth(self, session: Session, level: int = 20) -> AsyncIterator[dict]:
        """Open a 20- or 200-level depth stream and yield per-side depth dicts.

        Each yielded dict carries ``side`` (bid/ask), ``security_id``,
        ``symbol`` (routed via the subscribe map), ``exchange`` and ``depth``
        rows of ``{price, quantity, orders}`` — decoded per the documented
        binary layout (full-market-depth.md / the SDK's ``fulldepth.py``).
        The live sockets (``wss://depth-api-feed.dhan.co/twentydepth`` and
        ``wss://full-depth-api.dhan.co/twohundreddepth``) are provided by
        injecting ``depth_feed_factory``.
        """
        return self._depth_impl(session, level)

    async def _depth_impl(self, session: Session, level: int) -> AsyncIterator[dict]:
        if level not in M.DHAN_DEPTH_LEVELS:
            raise BrokerError(f"Dhan depth level must be one of {M.DHAN_DEPTH_LEVELS}, got {level!r}")
        if self._depth_feed_factory is None:
            raise NotImplementedError(
                "Dhan live depth stream needs the depth feed socket (inject depth_feed_factory; "
                "live default is the dhanhq fulldepth.FullDepth transport)"
            )
        async for frame in self._depth_feed_factory(session, level):
            for message in M.iter_dhan_depth_messages(frame):
                symbol, exchange = self._feed_map.get(
                    message["security_id"], ("", message.get("exchange", "")),
                )
                message["symbol"] = symbol
                if exchange:
                    message["exchange"] = exchange
                yield message

    # ---------- reconciliation ----------

    async def reconcile(self, session: Session) -> ReconciliationReport:
        """Broker-truth vs flinttrade-mirror diff (contract §14).

        Fetches the order book, positions and holdings through this adapter's
        own reads and diffs them against the injected ``local_state_provider``
        snapshot (empty until the engine wave wires the journal-backed
        provider). A broker fetch failure is captured on the report's
        ``error`` field instead of raised, so the runner retries next cycle.
        """
        from flinttrade_gateway.reconciliation import EMPTY_LOCAL_STATE, build_report  # noqa: PLC0415

        generated_at = datetime.now(tz=timezone.utc)
        local = EMPTY_LOCAL_STATE if self._local_state_provider is None else self._local_state_provider(session)
        try:
            broker_orders = await self.order_book(session)
            broker_positions = await self.positions(session)
            broker_holdings = await self.holdings(session)
        except (BrokerError, ValueError) as exc:  # ValueError covers the mapping-error classes
            return build_report(
                adapter_id=self.broker_id,
                account_id=session.account_id,
                generated_at=generated_at,
                local_state=local,
                error=f"broker fetch failed: {exc}",
            )
        # The read methods return the normalised row dicts at runtime (see the
        # mapping layer); build_report consumes them as plain mappings.
        return build_report(
            adapter_id=self.broker_id,
            account_id=session.account_id,
            generated_at=generated_at,
            broker_orders=broker_orders,  # type: ignore[arg-type]
            broker_positions=broker_positions,  # type: ignore[arg-type]
            broker_holdings=broker_holdings,
            local_state=local,
        )


from ._base import ROUTER_TOKEN as _ROUTER_TOKEN  # noqa: E402  shared per-process token (§8.0c)
