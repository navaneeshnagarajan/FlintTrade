"""IndMoney (INDstocks) native adapter — pure REST + WebSocket, no SDK.

IndMoney publishes no official SDK, so this adapter speaks the documented REST
API (``https://api.indstocks.com``) directly through an injected HTTP transport
(default: a thin ``httpx`` wrapper — httpx is already a gateway dependency) and
the documented JSON WebSocket feeds through injected feed factories. All
request/response translation lives in ``indmoney_mapping`` and is unit-tested;
the methods here are thin orchestration over the transport.

Auth: a dashboard-generated access token (24 h expiry, manual regeneration —
there is no login or refresh endpoint). ``login`` therefore only builds the
Session; ``profile()`` doubles as a token-validity probe.

Coverage: the full BrokerAdapter ABC plus every extra documented INDstocks
feature as capability-style extension methods — order details, per-order trades,
segment trade books, segment/product positions, LTP + market-depth quotes,
instruments master (CSV), pre-trade margin, smart orders (GTT/OCO/TRIGGER), and
both WebSocket feeds (price + order updates). The utility family (option chain /
expiries / Greeks) is documented as "Coming Soon" broker-side and raises until
the API ships. The full parity matrix is
``.local/audits/broker-parity/indmoney.md``.

Safety: writes — including every smart-order variety — require the router's
per-process ``_ROUTER_TOKEN`` (§8), so a bare call raises before any IndMoney
request is made. The variety and its leg prices are part of the
SafetyContext-hashed order, so a GTT/OCO/TRIGGER order is gated identically to a
regular one — no parallel order path.
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

from . import indmoney_mapping as M
from ._base import BrokerAdapter, Session

if TYPE_CHECKING:  # pragma: no cover - typing only
    from flinttrade_core.models import Candles, OptionChain, Order, Position, Quote, Trade
    from flinttrade_gateway.reconciliation import LocalStateSnapshot, ReconciliationReport

_COMING_SOON = (
    "INDstocks {0} API is documented as 'Coming Soon' (under development broker-side) — "
    "not implementable until it ships"
)

INDMONEY_CAPABILITIES = Capabilities(
    # Order API enums: exchange NSE/BSE × segment EQUITY/DERIVATIVE only.
    segments=Segments.NSE_EQ | Segments.BSE_EQ | Segments.NFO | Segments.BFO,
    # Normal orders accept LIMIT/MARKET (MARKET is broker-converted to LIMIT at
    # the live price) + the is_amo flag; the smart-order family is native GTT
    # (single/OCO legs + TRIGGER parents). No standalone SL/SL-M order type, no
    # bracket/cover/iceberg endpoints — advertising them would credit work the
    # adapter rejects (the Upstox honesty precedent).
    order_types=(
        OrderTypes.MARKET
        | OrderTypes.LIMIT
        | OrderTypes.MIS
        | OrderTypes.CNC
        | OrderTypes.NRML
        | OrderTypes.AMO
        | OrderTypes.GTT
    ),
    depth_levels=DepthLevels.L5,
    tick_protocol=TickProtocol.GENERIC_JSON,  # both WS feeds stream plain JSON
    # Dashboard-generated access token, 24 h expiry, manual regeneration (FAQ).
    auth_model=AuthModel.OAUTH_RENEWABLE_24H,
    session_lifetime_hours=24.0,
    sandbox=False,  # no sandbox documented — every call is live
    # Conventions-page rate-limit table.
    rate_limit_orders_per_sec=10,
    rate_limit_data_per_sec=5,
    rate_limit_data_per_day=100_000,
    rate_limit_quote_per_sec=5,
    rate_limit_non_trading_per_sec=15,
    order_modifications_per_order=25,
    # algo_id is a mandatory order field (99999 NSE / 9999999999999999 BSE).
    algo_tag_required=True,
    # API access is free; execution brokerage is a flat ₹5 per order.
    cost_paid=False,
    cost_inr_per_month=0,
    brokerage_free=False,
    brokerage_note="Flat ₹5 brokerage per order regardless of size; API access itself is free.",
    # Historical-data interval table — the doc advertises only per-request "Max
    # Fetch Range" per resolution (sub-minute 1 day, minutes 7 days, hours
    # 14 days, day/week/month 1 year), NOT a documented multi-year intraday
    # total, so historical_max_lookback_days_intraday is intentionally left unset
    # (None). The per-request caps are enforced in the mapping. Leaving lookback
    # unset keeps the recommendation engine honest: IndMoney is credited for its
    # broad interval menu, not over-credited for intraday depth it does not
    # document.
    historical_intraday_intervals_minutes=[1, 2, 3, 4, 5, 10, 15, 30, 60, 120, 180, 240],
    option_chain_supported=False,  # utility family is "Coming Soon" broker-side
    option_chain_greeks_supported=False,
    streaming_supported=True,
    streaming_max_connections_per_user=3,
    streaming_max_symbols_per_connection=3000,
    gtt_native=True,
    bracket_order_native=False,
    cover_order_native=False,
    multi_quote_supported=True,
    iceberg_native=False,
    modify_qty_supported=True,
)

# Transport signature: (method, url, headers=..., params=..., json_body=...) ->
# (status_code, decoded_payload). Synchronous — the adapter runs it off the
# event loop via asyncio.to_thread (same posture as the SDK-backed adapters).
Transport = Callable[..., tuple[int, Any]]


def _build_httpx_transport(timeout: float = 10.0) -> Transport:
    """Build the default HTTP transport over httpx (lazy import).

    Args:
        timeout: Per-request timeout in seconds.

    Returns:
        A synchronous transport callable returning ``(status_code, payload)``
        where payload is decoded JSON when possible, else raw text.
    """
    import httpx  # noqa: PLC0415

    def _request(
        method: str,
        url: str,
        *,
        headers: dict[str, str],
        params: dict[str, Any] | None = None,
        json_body: Any | None = None,
    ) -> tuple[int, Any]:
        resp = httpx.request(method, url, headers=headers, params=params, json=json_body, timeout=timeout)
        try:
            payload: Any = resp.json()
        except ValueError:
            payload = resp.text
        return resp.status_code, payload

    return _request


class IndMoneyAdapter(BrokerAdapter):
    """Native IndMoney (INDstocks) adapter.

    Args:
        http_factory: ``() -> transport`` override (tests inject a fake). The
            transport is called as ``transport(method, url, headers=...,
            params=..., json_body=...)`` and returns ``(status_code, payload)``.
            When omitted, ``login`` builds the default httpx transport.
        security_resolver: ``(symbol, exchange) -> security_id`` — IndMoney
            trades by instrument token from the instruments master, so the
            operator supplies a scrip-master resolver. Numeric symbols pass
            through unchanged (already-resolved ids).
        feed_factory: ``session -> AsyncIterator[str | bytes]`` yielding raw
            price-feed JSON frames. The live socket is NOT bundled (no WS client
            dependency); without an injected factory ``stream`` raises.
        order_feed_factory: Same shape for the order-updates feed.
        local_state_provider: ``session -> LocalStateSnapshot`` supplying the
            flinttrade-side mirror that ``reconcile`` diffs broker state
            against. Defaults to EMPTY local state (every broker-side row then
            surfaces as ``exists_only_on_broker``) until the engine wave wires
            the journal-backed provider.
    """

    def __init__(
        self,
        *,
        http_factory: Callable[[], Transport] | None = None,
        security_resolver: Callable[[str, str], str] | None = None,
        feed_factory: Callable[[Session], AsyncIterator[str | bytes]] | None = None,
        order_feed_factory: Callable[[Session], AsyncIterator[str | bytes]] | None = None,
        local_state_provider: Callable[[Session], LocalStateSnapshot] | None = None,
    ) -> None:
        self._http_factory = http_factory
        self._security_resolver = security_resolver
        self._feed_factory = feed_factory
        self._order_feed_factory = order_feed_factory
        self._local_state_provider = local_state_provider
        # security_id -> (symbol, exchange) for routing decoded ticks back to names.
        self._feed_map: dict[str, tuple[str, str]] = {}
        # security_id -> requested feed mode (informational; the subscribe
        # message itself is built per stream() consumer).
        self._feed_modes: dict[str, str] = {}
        # Child GTT id of the most recent smart placement (the contract returns
        # one id, so the parent is returned and the child is surfaced here).
        self.last_child_order_id: str | None = None

    # ---------- identity + capabilities ----------

    @property
    def broker_id(self) -> str:
        return "indmoney"

    @property
    def capabilities(self) -> Capabilities:
        return INDMONEY_CAPABILITIES

    # ---------- helpers ----------

    def _transport(self, session: Session) -> Transport:
        if self._http_factory is not None:
            return self._http_factory()
        transport = session.extra.get("transport")
        if transport is None:
            raise BrokerError("IndMoney transport not initialised — call login() first")
        return transport

    @staticmethod
    def _headers(session: Session) -> dict[str, str]:
        # Header format is the bare token, no "Bearer" prefix (conventions doc).
        return {"Authorization": session.access_token, "Content-Type": "application/json"}

    async def _request(
        self,
        session: Session,
        method: str,
        path: str,
        *,
        params: dict[str, Any] | None = None,
        json_body: Any | None = None,
        raw: bool = False,
    ) -> Any:
        """Run one REST call off the event loop; unwrap the envelope or raise.

        Args:
            session: Active broker session (token + transport).
            method: HTTP method.
            path: Path under the API base URL.
            params: Query parameters.
            json_body: JSON request body (IndMoney uses bodies on some GETs).
            raw: Return the payload verbatim (CSV endpoints) instead of
                unwrapping the ``{status, data}`` envelope.
        """
        transport = self._transport(session)
        status, payload = await asyncio.to_thread(
            transport,
            method,
            f"{M.BASE_URL}{path}",
            headers=self._headers(session),
            params=params,
            json_body=json_body,
        )
        if status >= 400 or (isinstance(payload, dict) and str(payload.get("status", "")).lower() == "error"):
            raise M.map_error(status, payload)
        return payload if raw else M.unwrap(payload)

    def _resolve_security(self, symbol: str, exchange: str) -> str:
        sym = str(symbol).strip()
        if sym.isdigit():
            return sym  # already an instrument token
        if self._security_resolver is not None:
            return str(self._security_resolver(sym, exchange))
        raise BrokerError(
            f"Cannot resolve IndMoney security_id for {symbol}/{exchange} — "
            "configure a security resolver (instruments master)"
        )

    @staticmethod
    def _split_symbol(raw: str) -> tuple[str, str]:
        """Split an ``"EXCHANGE:SYMBOL"`` quote key (defaults exchange to NSE)."""
        if ":" in raw:
            exchange, name = raw.split(":", 1)
            return exchange.strip().upper(), name.strip()
        return "NSE", raw.strip()

    async def _segment_for_order(self, session: Session, order_id: str) -> str:
        """Resolve the EQUITY/DERIVATIVE segment for an order id.

        ``DRV-``/``EQ-`` prefixes are decisive; otherwise (``GTT-`` and unknown
        prefixes) the live order book is consulted. Falls back to EQUITY when
        the order cannot be found (the broker then rejects with its own error).
        """
        seg = M.segment_from_order_id(order_id)
        if seg is not None:
            return seg
        rows = await self._request(session, "GET", "/order-book") or []
        for row in rows:
            if isinstance(row, dict) and str(row.get("id", "")) == str(order_id):
                found = str(row.get("segment", "")).upper()
                if found in ("EQUITY", "DERIVATIVE"):
                    return found
        return "EQUITY"

    # ---------- auth lifecycle ----------

    async def login(self, credentials: dict) -> Session:
        access_token = str(credentials.get("access_token") or "")
        if not access_token:
            raise BrokerError("IndMoney login requires an access_token (generated on the INDstocks dashboard)")
        transport = None if self._http_factory is not None else _build_httpx_transport()
        return Session(
            access_token=access_token,
            # Dashboard tokens expire after 24 hours (FAQ) — no refresh endpoint.
            expires_at=datetime.now(tz=timezone.utc).timestamp() + 24 * 3600,
            account_id=str(credentials.get("user_id") or ""),
            adapter_id="indmoney",
            extra={"transport": transport},
        )

    async def refresh(self, session: Session) -> Session:
        # IndMoney tokens cannot be refreshed programmatically — a new dashboard
        # token + login() is required at expiry. Nothing to do until then.
        return session

    async def logout(self, session: Session) -> None:
        # No revoke endpoint is documented (revocation is dashboard-side); drop
        # the local transport so the session can no longer be used. Idempotent.
        session.extra.pop("transport", None)
        return None

    # ---------- trading: writes (safety-critical; router-only) ----------

    async def place_order(self, session: Session, order: Order, *, _router_token: object | None = None) -> str:
        self._require_router_token(_router_token, _ROUTER_TOKEN)
        security_id = self._resolve_security(order.symbol, str(order.exchange))
        algo_id = session.algo_id or None
        # Dispatch on order variety. Every variety travels this SAME gated method
        # (the router token is already required above and the variety + leg
        # prices are part of the SafetyContext-hashed order), so a GTT/OCO/
        # TRIGGER smart order is gated identically to a regular one.
        variety = str(getattr(order, "variety", "regular")).lower()
        if variety in ("regular", "", "amo"):
            payload = M.to_place_order_payload(order, security_id, algo_id=algo_id)
            resp = await self._request(session, "POST", "/order", json_body=payload)
            self.last_child_order_id = None
            return M.extract_order_id({"data": resp})
        if variety in M.SMART_VARIETIES:
            payload = M.to_smart_order_payload(order, security_id, algo_id=algo_id)
            resp = await self._request(session, "POST", "/smart/order", json_body=payload)
            parent, child = M.extract_smart_order_ids({"data": resp})
            self.last_child_order_id = child
            return parent
        raise BrokerError(f"IndMoney does not support order variety {variety!r}")

    async def modify_order(
        self, session: Session, order_id: str, changes: dict, *, _router_token: object | None = None
    ) -> None:
        self._require_router_token(_router_token, _ROUTER_TOKEN)
        variety = str(changes.get("variety", "")).lower()
        smart = variety in M.SMART_VARIETIES or variety == "smart" or M.is_smart_order_id(order_id)
        segment = M.resolve_segment(order_id, changes) or await self._segment_for_order(session, order_id)
        if smart:
            payload = M.to_smart_modify_payload(order_id, changes, segment=segment)
            await self._request(session, "POST", "/smart/order/modify", json_body=payload)
        else:
            payload = M.to_modify_order_payload(order_id, changes, segment=segment)
            await self._request(session, "POST", "/order/modify", json_body=payload)

    async def cancel_order(
        self, session: Session, order_id: str, *, _router_token: object | None = None
    ) -> None:
        self._require_router_token(_router_token, _ROUTER_TOKEN)
        segment = await self._segment_for_order(session, order_id)
        payload = M.to_cancel_payload(order_id, segment)
        # GTT-prefixed ids belong to the smart-order family and must travel its
        # cancel endpoint (smart-orders doc); parents cancel via /order/cancel.
        path = "/smart/order/cancel" if M.is_smart_order_id(order_id) else "/order/cancel"
        await self._request(session, "POST", path, json_body=payload)

    async def cancel_smart_order(
        self, session: Session, order_id: str, *, segment: str | None = None, _router_token: object | None = None
    ) -> None:
        """Cancel via ``POST /smart/order/cancel`` explicitly (a gated write).

        ``cancel_order`` auto-routes ``GTT-`` ids here; this method forces the
        smart path for ``EQ-``/``DRV-`` parents of smart orders.
        """
        self._require_router_token(_router_token, _ROUTER_TOKEN)
        seg = segment or await self._segment_for_order(session, order_id)
        await self._request(session, "POST", "/smart/order/cancel", json_body=M.to_cancel_payload(order_id, seg))

    # ---------- trading: reads (no SafetyContext required) ----------

    async def order_book(self, session: Session) -> list[Order]:
        rows = await self._request(session, "GET", "/order-book") or []
        return [M.from_indmoney_order(r) for r in rows if isinstance(r, dict)]  # type: ignore[misc]

    async def order_details(self, session: Session, order_id: str, *, segment: str | None = None) -> dict:
        """Full details of a single order (``GET /order`` with a JSON body) — a read."""
        seg = segment or await self._segment_for_order(session, order_id)
        data = await self._request(
            session, "GET", "/order", json_body={"order_id": str(order_id), "segment": seg}
        )
        return M.from_indmoney_order(data if isinstance(data, dict) else {})

    async def order_trades(self, session: Session, order_id: str) -> list[dict]:
        """Executed trades for one order (``GET /trades/{order_id}``) — a read."""
        rows = await self._request(session, "GET", f"/trades/{order_id}") or []
        return [M.from_indmoney_trade(r) for r in rows if isinstance(r, dict)]

    async def trade_book_segment(self, session: Session, segment: str) -> list[dict]:
        """Day fills for one segment (``GET /trade-book?segment=``) — a read."""
        seg = str(segment).upper()
        rows = await self._request(session, "GET", "/trade-book", params={"segment": seg}) or []
        return [M.from_indmoney_tradebook_row(r) for r in rows if isinstance(r, dict)]

    async def trade_book(self, session: Session) -> list[Trade]:
        # The endpoint is segment-scoped; the contract wants ALL fills for the
        # day, so both documented segments are aggregated.
        out: list[dict] = []
        for segment in ("EQUITY", "DERIVATIVE"):
            out.extend(await self.trade_book_segment(session, segment))
        return out  # type: ignore[return-value]

    async def positions_segment(self, session: Session, segment: str, product: str) -> dict:
        """Positions for one documented segment/product combo — a read.

        Returns the raw ``{net_positions, day_positions}`` split with rows
        normalised, preserving the broker's day/net distinction.
        """
        params = {"segment": str(segment).lower(), "product": str(product).lower()}
        data = await self._request(session, "GET", "/portfolio/positions", params=params) or {}
        prod = str(product).upper()
        # Map the IndMoney product spelling back to canonical for row tagging.
        canonical = {"MARGIN": "NRML", "INTRADAY": "MIS", "CNC": "CNC"}.get(prod, prod)
        return {
            "net_positions": [
                M.from_indmoney_position(r, product=canonical)
                for r in (data.get("net_positions") or [])
                if isinstance(r, dict)
            ],
            "day_positions": [
                M.from_indmoney_position(r, product=canonical)
                for r in (data.get("day_positions") or [])
                if isinstance(r, dict)
            ],
        }

    async def positions(self, session: Session) -> list[Position]:
        # The endpoint is (segment, product)-scoped; the contract wants every
        # open position, so all four documented combos are aggregated and
        # de-duplicated on (symbol, product).
        combos = (("derivative", "margin"), ("derivative", "intraday"), ("equity", "cnc"), ("equity", "intraday"))
        seen: set[tuple[str, str]] = set()
        out: list[dict] = []
        for segment, product in combos:
            split = await self.positions_segment(session, segment, product)
            for row in split["net_positions"]:
                key = (row.get("symbol", ""), row.get("product", ""))
                if key not in seen:
                    seen.add(key)
                    out.append(row)
        return out  # type: ignore[return-value]

    async def holdings(self, session: Session) -> list[dict]:
        rows = await self._request(session, "GET", "/portfolio/holdings") or []
        return [M.from_indmoney_holding(r) for r in rows if isinstance(r, dict)]

    async def funds(self, session: Session) -> dict:
        data = await self._request(session, "GET", "/funds")
        return M.from_indmoney_funds({"data": data})

    async def profile(self, session: Session) -> dict:
        """User profile (``GET /user/profile``) — also a token-validity probe."""
        data = await self._request(session, "GET", "/user/profile")
        return data if isinstance(data, dict) else {}

    # ---------- pre-trade info (reads) ----------

    async def margin_calculator(self, session: Session, order: Order) -> dict:
        """Pre-trade margin + charges estimate (``GET /margin``).

        A read-only estimate — it places nothing, so it needs no gate.
        """
        security_id = self._resolve_security(order.symbol, str(order.exchange))
        body = M.to_margin_params(order, security_id)
        data = await self._request(session, "GET", "/margin", json_body=body)
        return M.from_indmoney_margin({"data": data})

    async def instruments_csv(self, session: Session, source: str = "equity") -> str:
        """Raw instruments-master CSV (``GET /market/instruments?source=``)."""
        payload = await self._request(session, "GET", "/market/instruments", params={"source": source}, raw=True)
        return payload if isinstance(payload, str) else str(payload)

    async def instruments(self, session: Session, source: str = "equity") -> list[dict]:
        """Parsed instruments master for ``source`` (``equity``/``fno``/``index``)."""
        return M.parse_instruments_csv(await self.instruments_csv(session, source))

    async def smart_orders(self, session: Session) -> list[dict]:
        """Smart (GTT-family) rows from the order book — a read.

        There is no dedicated GTT-list endpoint; smart orders surface in the
        order book with ``GTT-`` ids and/or populated SL/target leg prices.
        """
        rows = await self.order_book(session)
        return [
            r
            for r in rows  # type: ignore[union-attr]
            if M.is_smart_order_id(r.get("orderid", ""))
            or any(M.parse_indian_number(r.get(k, "")) > 0 for k in ("sl_trigger_price", "tgt_trigger_price"))
        ]

    # ---------- market data: rest ----------

    async def quotes(self, session: Session, symbols: list[str]) -> list[Quote]:
        from flinttrade_core.models import Quote  # noqa: PLC0415

        resolved: list[tuple[str, str, str]] = []  # (symbol, exchange, scrip)
        for raw in symbols:
            exchange, name = self._split_symbol(raw)
            scrip = M.to_scrip_code(exchange, self._resolve_security(name, exchange))
            resolved.append((name, exchange, scrip))
        data = await self._request(
            session, "GET", "/market/quotes/full",
            params={"scrip-codes": ",".join(s for _, _, s in resolved)},
        ) or {}
        out: list[Quote] = []
        for name, exchange, scrip in resolved:
            rec = data.get(scrip)
            if isinstance(rec, dict):
                out.append(Quote(**M.from_indmoney_quote(name, exchange, rec)))
        return out

    async def ltp(self, session: Session, symbols: list[str]) -> dict[str, float]:
        """Last traded prices (``GET /market/quotes/ltp``) keyed by ``EXCHANGE:SYMBOL``."""
        resolved: list[tuple[str, str]] = []  # (key, scrip)
        for raw in symbols:
            exchange, name = self._split_symbol(raw)
            scrip = M.to_scrip_code(exchange, self._resolve_security(name, exchange))
            resolved.append((f"{exchange}:{name}", scrip))
        data = await self._request(
            session, "GET", "/market/quotes/ltp",
            params={"scrip-codes": ",".join(s for _, s in resolved)},
        ) or {}
        return {
            key: float((data.get(scrip) or {}).get("live_price", 0) or 0)
            for key, scrip in resolved
            if isinstance(data.get(scrip), dict)
        }

    async def market_depth(self, session: Session, symbols: list[str]) -> dict[str, dict]:
        """Five-level market depth (``GET /market/quotes/mkt``) keyed by ``EXCHANGE:SYMBOL``."""
        resolved: list[tuple[str, str]] = []
        for raw in symbols:
            exchange, name = self._split_symbol(raw)
            scrip = M.to_scrip_code(exchange, self._resolve_security(name, exchange))
            resolved.append((f"{exchange}:{name}", scrip))
        data = await self._request(
            session, "GET", "/market/quotes/mkt",
            params={"scrip-codes": ",".join(s for _, s in resolved)},
        ) or {}
        return {
            key: M.from_indmoney_depth(data.get(scrip) or {})
            for key, scrip in resolved
            if isinstance(data.get(scrip), dict)
        }

    async def historical(self, session: Session, req: dict) -> Candles:
        from flinttrade_core.models import OHLCV, Candles  # noqa: PLC0415

        symbol = str(req.get("symbol", ""))
        exchange = str(req.get("exchange", "NSE"))
        interval = str(req.get("interval", req.get("timeframe", "1m")))
        start = req.get("start_time") or req.get("from_date") or req.get("start") or req.get("start_date")
        end = req.get("end_time") or req.get("to_date") or req.get("end") or req.get("end_date")
        if start is None or end is None:
            raise BrokerError("IndMoney historical requires start_time and end_time")
        label, max_days = M.interval_to_indmoney(interval)
        start_ms, end_ms = M.to_epoch_ms(start), M.to_epoch_ms(end)
        M.validate_history_range(start_ms, end_ms, max_days)
        scrip = M.to_scrip_code(exchange, self._resolve_security(symbol, exchange))
        data = await self._request(
            session, "GET", f"/market/historical/{label}",
            params={"scrip-codes": scrip, "start_time": start_ms, "end_time": end_ms},
        )
        cd = M.to_candles_dict(symbol, exchange, interval, {"data": data})
        return Candles(
            symbol=cd["symbol"],
            exchange=cd["exchange"],
            interval=cd["interval"],
            bars=[OHLCV(**b) for b in cd["bars"]],
        )

    # ---------- utility family (documented "Coming Soon" broker-side) ----------

    async def option_chain(self, session: Session, req: dict) -> OptionChain:
        raise NotImplementedError(_COMING_SOON.format("option-chain"))

    async def option_chain_symbols(self, session: Session, token: str) -> list[str]:
        """Expiry dates for an option underlying (``GET /option-chain-symbols``)."""
        raise NotImplementedError(_COMING_SOON.format("option-chain-symbols (expiry list)"))

    async def greeks(self, session: Session, tokens: list[str]) -> list[dict]:
        """Option Greeks for instrument tokens (``POST /greeks``)."""
        raise NotImplementedError(_COMING_SOON.format("greeks"))

    # ---------- market data: streaming ----------

    async def subscribe(self, session: Session, symbols: list[str], mode: str = "FULL") -> None:
        # Resolve each symbol to its instrument token and remember it so decoded
        # JSON ticks (which carry only the token) route back to symbol names.
        # The actual subscribe message (built by M.subscribe_message) is sent by
        # whatever owns the live socket — the injected feed factory.
        for raw in symbols:
            exchange, name = self._split_symbol(raw)
            security_id = self._resolve_security(name, exchange)
            M.ws_instrument(exchange, security_id)  # validates the segment early
            self._feed_map[str(security_id)] = (name, exchange)
            self._feed_modes[str(security_id)] = mode

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
            # Live: the price-feed WebSocket needs a WS client + the token. The
            # decode path (decode_price_frame) and the subscribe-message builder
            # are implemented and tested; the live socket is provided by
            # injecting a feed_factory (no WS client dependency is bundled).
            raise NotImplementedError(
                "IndMoney live price feed needs an injected feed_factory "
                f"(connect to {M.PRICE_FEED_WS_URL} and yield raw frames)"
            )
        async for frame in self._feed_factory(session):
            tick = M.decode_price_frame(frame)
            if tick is None:
                continue  # heartbeat / control frame
            symbol, exchange = self._feed_map.get(tick["security_id"], ("", ""))
            yield TickEvent(
                symbol=symbol,
                exchange=exchange,
                ltp=tick.get("ltp", 0.0),
                volume=int(tick.get("volume", 0)),
                timestamp=str(tick.get("timestamp", "")),
            )

    async def order_update_stream(self, session: Session) -> AsyncIterator[dict]:
        """Stream normalised order updates from the order-updates WebSocket.

        A read-only feed (placement/execution/cancellation notifications) — it
        cannot place anything, so it needs no gate. The live socket is an
        injected ``order_feed_factory``; heartbeats are skipped.
        """
        if self._order_feed_factory is None:
            raise NotImplementedError(
                "IndMoney live order-updates feed needs an injected order_feed_factory "
                f"(connect to {M.ORDER_FEED_WS_URL} and yield raw frames)"
            )
        async for frame in self._order_feed_factory(session):
            update = M.decode_order_update(frame)
            if update is not None:
                yield update

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
