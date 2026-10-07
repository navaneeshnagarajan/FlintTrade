"""Delta Exchange native adapter.

Direct signed REST and the documented India websockets cover the v2 surface
(products, orders, brackets, batch orders, positions, wallet, option chain,
candles, leverage, margin mode, MMP, subaccounts, and the deadman heartbeat).
India and Global are separate venues; a key from one is rejected by the other.
The catalogue stays ``connectable=False`` until live order-safety proof and a
deadman runtime proof exist. Every write requires the router's shared token.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import time
from copy import deepcopy
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any, AsyncIterator, Callable, Mapping

from flinttrade_core.broker_read_port import BrokerReadResponseInvalid
from flinttrade_core.exceptions import BrokerError, UnsupportedCapabilityError
from flinttrade_core.models import OHLCV, Candles, OptionChain, Quote
from flinttrade_gateway.capabilities import (
    AuthModel,
    Capabilities,
    DepthLevels,
    OrderTypes,
    Segments,
    TickProtocol,
)

from . import delta_feed as F, delta_mapping as M
from ._base import ROUTER_TOKEN as _ROUTER_TOKEN, BrokerAdapter, Session, run_blocking_sdk_call

if TYPE_CHECKING:  # pragma: no cover - typing only
    from flinttrade_core.models import Order
    from flinttrade_engine.safety import EmergencyReductionPlan, EmergencyWritePolicy
    from flinttrade_gateway.reconciliation import ReconciliationReport

Transport = Callable[[str, str, dict[str, str], str], tuple[int, Any]]
Clock = Callable[[], int]

_EMERGENCY_BATCH_LIMIT = 10
_ORDER_CACHE = "order_products"
_READ_PAGE_LIMIT = 1000


DELTA_CAPABILITIES = Capabilities(
    segments=Segments.CRYPTO,
    order_types=OrderTypes.MARKET | OrderTypes.LIMIT | OrderTypes.SL | OrderTypes.SLM | OrderTypes.BO,
    depth_levels=DepthLevels.L20,
    tick_protocol=TickProtocol.GENERIC_JSON,
    auth_model=AuthModel.API_KEY_PERSISTENT,
    session_lifetime_hours=24 * 365,
    sandbox=False,
    rate_limit_orders_per_sec=10,
    rate_limit_data_per_sec=10,
    historical_intraday_intervals_minutes=[1, 3, 5, 15, 30, 60, 120, 240, 360],
    historical_calendar_intervals=["1d", "1w"],
    option_chain_supported=True,
    option_chain_greeks_supported=True,
    streaming_supported=True,
    streaming_runtime_ready=True,
    market_depth_runtime_ready=True,
    streaming_max_symbols_per_connection=100,
    bracket_order_native=True,
    basket_order_native=True,
    multi_quote_supported=True,
    modify_qty_supported=True,
    brokerage_note=(
        "Delta matching-engine cap is 500 operations/second per product. "
        "FlintTrade advertises a conservative 10/second until live quota proof exists. "
        "Order size is an integer contract count, not a coin amount."
    ),
)


def _httpx_transport() -> Transport:
    import httpx

    def transport(method: str, url: str, headers: dict[str, str], body: str) -> tuple[int, Any]:
        with httpx.Client(timeout=20.0) as client:
            response = client.request(method, url, headers=headers, content=body.encode("utf-8"))
        try:
            payload = response.json()
        except ValueError:
            payload = response.text
        return response.status_code, payload

    return transport


class DeltaAdapter(BrokerAdapter):
    """Signed Delta v2 adapter. Construction does not open a network session."""

    def __init__(
        self,
        *,
        transport_factory: Callable[[], Transport] | None = None,
        socket_factory: Callable[[str], Any] | None = None,
        clock: Clock | None = None,
    ) -> None:
        self._transport_factory = transport_factory
        self._socket_factory = socket_factory
        self._clock = clock or (lambda: int(time.time()))

    @property
    def broker_id(self) -> str:
        return M.BROKER_ID

    @property
    def capabilities(self) -> Capabilities:
        return DELTA_CAPABILITIES

    async def login(self, credentials: dict) -> Session:
        api_key = str(credentials.get("api_key") or "").strip()
        api_secret = str(credentials.get("api_secret") or credentials.get("secret") or "").strip()
        environment = str(credentials.get("environment") or "").strip()
        if not api_key or not api_secret:
            raise BrokerError("Delta login requires api_key and api_secret", broker_id=self.broker_id)
        if not environment:
            raise BrokerError(
                "Delta login requires environment (india_prod, india_testnet, global_prod, or global_testnet)",
                broker_id=self.broker_id,
            )
        venue = M.resolve_venue(environment)
        transport = self._transport_factory() if self._transport_factory is not None else _httpx_transport()
        session = Session(
            access_token=api_key,
            expires_at=self._clock() + int(DELTA_CAPABILITIES.session_lifetime_hours * 3600),
            account_id=str(credentials.get("user_id") or credentials.get("account_id") or ""),
            adapter_id=self.broker_id,
            extra={
                "api_secret": api_secret,
                "environment": venue.id,
                "rest_base": venue.rest_base,
                "private_ws": venue.private_ws,
                "public_ws": venue.public_ws,
                "testnet": venue.testnet,
                "region": venue.region,
                "transport": transport,
                _ORDER_CACHE: {},
            },
        )
        balances = await self.exchange_call(session, "wallet_balances")
        wallets = balances if isinstance(balances, list) else []
        user_ids = {str(row.get("user_id")) for row in wallets if isinstance(row, dict) and row.get("user_id") is not None}
        if len(user_ids) == 1:
            session.extra["user_id"] = next(iter(user_ids))
            if not session.account_id:
                session.account_id = session.extra["user_id"]
        return session

    async def refresh(self, session: Session) -> Session:
        return session

    async def logout(self, session: Session) -> None:
        session.extra.pop("api_secret", None)
        session.extra.pop("transport", None)
        return

    async def place_order(self, session: Session, order: Order, *, _router_token: object | None = None) -> str:
        self._require_router_token(_router_token, _ROUTER_TOKEN)
        payload = M.to_place_payload(order)
        outcome = await self.exchange_call(
            session, "place_order", body=payload, _router_token=_router_token, _preserve_envelope=True,
        )
        result = M.require_write_success(outcome)
        order_id = str(result["id"])
        product_id = result.get("product_id") if isinstance(result, dict) else None
        if product_id is not None:
            session.extra.setdefault(_ORDER_CACHE, {})[order_id] = int(product_id)
        return order_id

    async def modify_order(
        self, session: Session, order_id: str, changes: dict, *, _router_token: object | None = None
    ) -> None:
        self._require_router_token(_router_token, _ROUTER_TOKEN)
        enriched = dict(changes)
        if "product_id" not in enriched and "product_symbol" not in enriched and "symbol" not in enriched:
            cached = session.extra.get(_ORDER_CACHE, {}).get(str(order_id))
            if cached is not None:
                enriched["product_id"] = cached
        outcome = await self.exchange_call(
            session,
            "edit_order",
            body=M.to_edit_payload(order_id, enriched),
            _router_token=_router_token,
            _preserve_envelope=True,
        )
        M.require_write_success(outcome, expected_id=order_id)

    async def cancel_order(self, session: Session, order_id: str, *, _router_token: object | None = None) -> None:
        self._require_router_token(_router_token, _ROUTER_TOKEN)
        product_id = session.extra.get(_ORDER_CACHE, {}).get(str(order_id))
        if product_id is None:
            looked_up = await self.exchange_call(session, "order_by_id", path_params={"order_id": order_id})
            if not isinstance(looked_up, Mapping) or M._order_id(looked_up.get("id")) != M._order_id(order_id):
                raise BrokerError("Delta cancel product lookup conflicts with order id", broker_id=self.broker_id)
            product_id = M._order_id(looked_up.get("product_id"))
        outcome = await self.exchange_call(
            session,
            "cancel_order",
            body=M.to_cancel_payload(order_id, product_id=product_id),
            _router_token=_router_token,
            _preserve_envelope=True,
        )
        M.require_write_success(outcome, expected_id=order_id)

    async def cancel_all_orders(
        self,
        session: Session,
        *,
        tag: str | None = None,
        segment: str | None = None,
        _router_token: object | None = None,
    ) -> Any:
        """Native bulk cancel. One broker call, so one consumed safety context is enough."""
        del tag, segment
        self._require_router_token(_router_token, _ROUTER_TOKEN)
        before = await self._open_order_rows(session)
        outcome = await self.exchange_call(
            session, "cancel_all_orders", _router_token=_router_token, _preserve_envelope=True,
        )
        try:
            after = await self._open_order_rows(session)
        except (BrokerError, BrokerReadResponseInvalid) as exc:
            return _ack_summary(before=before, after=None, outcome=outcome, operation="cancel_all_orders",
                                readback_error=str(exc))
        return _ack_summary(before=before, after=after, outcome=outcome, operation="cancel_all_orders")

    async def exit_all_positions(
        self,
        session: Session,
        *,
        tag: str | None = None,
        segment: str | None = None,
        _router_token: object | None = None,
    ) -> Any:
        """Native close-all. Refuses to fan out into per-position orders."""
        del tag, segment
        self._require_router_token(_router_token, _ROUTER_TOKEN)
        user_id = session.extra.get("user_id")
        if not user_id:
            raise BrokerError("Delta close-all requires the user id captured at login", broker_id=self.broker_id)
        before = await self._open_position_rows(session)
        outcome = await self.exchange_call(
            session,
            "close_all_positions",
            body={
                "close_all_portfolio": True,
                "close_all_isolated": True,
                "user_id": int(user_id),
            },
            _router_token=_router_token,
            _preserve_envelope=True,
        )
        try:
            after = await self._open_position_rows(session)
        except (BrokerError, BrokerReadResponseInvalid) as exc:
            return _ack_summary(before=before, after=None, outcome=outcome, operation="close_all_positions",
                                readback_error=str(exc))
        return _ack_summary(before=before, after=after, outcome=outcome, operation="close_all_positions")

    async def place_reducing_order(
        self,
        session: Session,
        payload: dict[str, Any],
        *,
        _router_token: object | None = None,
    ) -> str:
        """Place one reduce-only market order after confirming the live position size."""
        self._require_router_token(_router_token, _ROUTER_TOKEN)
        symbol = M._request_alias(payload, ("product_symbol", "symbol"), M.product_symbol)
        if symbol is None:
            raise BrokerError("Delta reducing order requires symbol", broker_id=self.broker_id)
        try:
            expected = M.contract_evidence(payload.get("expected_position_size"), signed=True)
        except BrokerReadResponseInvalid as exc:
            raise BrokerError("Delta expected position must be an exact signed contract count", broker_id=self.broker_id) from exc
        size = M._request_alias(payload, ("size", "quantity"), M.contract_size)
        if size != abs(expected) or expected == 0:
            raise BrokerError("Delta reducing order size must equal the open position", broker_id=self.broker_id)
        product = payload.get("product")
        if payload.get("exchange") != "CRYPTO" or not isinstance(product, str) or not product.strip():
            raise BrokerError("Delta reducing order requires CRYPTO exchange and product identity", broker_id=self.broker_id)
        tag = payload.get("emergency_tag")
        if not isinstance(tag, str) or not tag or len(tag) > 32:
            raise BrokerError("Delta reducing order requires an emergency_tag of at most 32 characters", broker_id=self.broker_id)
        side = "sell" if expected > 0 else "buy"
        for field in ("side", "action"):
            if field in payload and M._side(payload[field]) != side:
                raise BrokerError("Delta reducing order side conflicts with the position", broker_id=self.broker_id)
        if "reduce_only" in payload and payload["reduce_only"] is not True:
            raise BrokerError("Delta reducing order requires native boolean reduce_only", broker_id=self.broker_id)
        body = {
            "product_symbol": symbol,
            "size": size,
            "side": side,
            "order_type": "market_order",
            "reduce_only": True,
            "time_in_force": "ioc",
            "client_order_id": tag,
        }
        live = await self._position_size(session, symbol)
        if live != expected:
            raise BrokerError("Delta position changed before the reducing order", broker_id=self.broker_id)
        outcome = await self.exchange_call(
            session, "place_order", body=body, _router_token=_router_token, _preserve_envelope=True,
        )
        return str(M.require_write_success(outcome)["id"])

    async def plan_emergency_reduction(
        self,
        session: Session,
        *,
        policy: EmergencyWritePolicy,
        protected_order_ids: frozenset[str],
        protected_exit_order_ids: frozenset[str] = frozenset(),
        protected_exit_tags: frozenset[str],
        unidentified_exit_inflight: bool = False,
    ) -> EmergencyReductionPlan:
        """Plan exact exposure-reducing writes. Bulk verbs are used only when nothing is protected."""
        from flinttrade_engine.safety import EmergencyBrokerWrite, EmergencyReductionPlan

        del protected_exit_tags
        requested = frozenset(policy.verbs)
        open_orders = await self._open_order_rows(session) if "cancel_all_orders" in requested else []
        open_positions = await self._open_position_rows(session) if "exit_all_positions" in requested else []
        pending: set[str] = set()
        if open_orders:
            pending.add("cancel_all_orders")
        if open_positions:
            pending.add("exit_all_positions")
        if not pending or unidentified_exit_inflight:
            return EmergencyReductionPlan(writes=(), pending_verbs=frozenset(pending))

        writes: list[EmergencyBrokerWrite] = []
        if "cancel_all_orders" in pending:
            protected = protected_order_ids | protected_exit_order_ids
            exposed = [row for row in open_orders if str(row.get("id")) not in protected]
            if exposed and len(exposed) == len(open_orders):
                writes.append(
                    EmergencyBrokerWrite(
                        parent_verb="cancel_all_orders",
                        verb="cancel_all_orders",
                        payload={"_op": "cancel_all_orders"},
                    )
                )
            else:
                for row in exposed[:_EMERGENCY_BATCH_LIMIT]:
                    writes.append(
                        EmergencyBrokerWrite(
                            parent_verb="cancel_all_orders",
                            verb="cancel_order",
                            payload={"_op": "cancel_order", "order_id": str(row.get("id"))},
                        )
                    )
        elif "exit_all_positions" in pending and session.extra.get("user_id"):
            writes.append(
                EmergencyBrokerWrite(
                    parent_verb="exit_all_positions",
                    verb="exit_all_positions",
                    payload={"_op": "exit_all_positions"},
                )
            )
        else:
            for row in open_positions[:_EMERGENCY_BATCH_LIMIT]:
                size = int(row.get("size") or 0)
                symbol = str(row.get("product_symbol") or "")
                writes.append(
                    EmergencyBrokerWrite(
                        parent_verb="exit_all_positions",
                        verb="place_reducing_order",
                        payload={
                            "_op": "place_reducing_order",
                            "symbol": symbol,
                            "exchange": "CRYPTO",
                            "product": "NRML",
                            "product_symbol": symbol,
                            "expected_position_size": size,
                            "size": abs(size),
                            "emergency_tag": _emergency_exit_tag(symbol, size),
                        },
                    )
                )
        return EmergencyReductionPlan(writes=tuple(writes), pending_verbs=frozenset(pending))

    async def order_book(self, session: Session) -> list[dict[str, Any]]:
        rows = await self._open_order_rows(session)
        return [M.from_order(row) for row in rows]

    async def trade_book(self, session: Session) -> list[dict[str, Any]]:
        return [M.from_fill(row) for row in await self._read_rows(session, "fills")]

    async def positions(self, session: Session) -> list[dict[str, Any]]:
        return [M.from_position(row) for row in await self._open_position_rows(session)]

    async def holdings(self, session: Session) -> list[dict]:
        del session
        return []

    async def funds(self, session: Session) -> dict:
        return M.funds_from_wallets(await self.exchange_call(session, "wallet_balances"))

    async def quotes(self, session: Session, symbols: list[str]) -> list[Quote]:
        wanted = [M.product_symbol(symbol) for symbol in symbols]
        if len(wanted) == 1:
            row = await self.exchange_call(session, "ticker", path_params={"symbol": wanted[0]})
            rows = [row] if isinstance(row, dict) else []
        else:
            listed = await self.exchange_call(session, "tickers")
            rows = listed if isinstance(listed, list) else []
        by_symbol = {str(row.get("symbol")): row for row in rows if isinstance(row, dict)}
        out: list[Quote] = []
        for symbol in wanted:
            row = by_symbol.get(symbol)
            if row is None:
                out.append(Quote(symbol=symbol, exchange="CRYPTO"))
                continue
            mapped = M.from_ticker(row)
            out.append(Quote(**{key: mapped[key] for key in Quote.model_fields if key in mapped}))
        return out

    async def historical(self, session: Session, req: dict) -> Candles:
        symbol = M.product_symbol(req.get("symbol") or req.get("product_symbol"))
        resolution = M.candle_resolution(req.get("interval") or req.get("resolution") or "1m")
        start = req.get("start") or req.get("start_time") or req.get("start_date")
        end = req.get("end") or req.get("end_time") or req.get("end_date")
        if start is None or end is None:
            raise BrokerError("Delta candles require start and end bounds", broker_id=self.broker_id)
        result = await self.exchange_call(
            session,
            "candles",
            query={
                "symbol": symbol,
                "resolution": resolution,
                "start": M.unix_seconds(start),
                "end": M.unix_seconds(end),
            },
        )
        rows = result if isinstance(result, list) else []
        bars = [
            OHLCV(
                timestamp=str(row.get("time") or ""),
                open=float(row.get("open") or 0),
                high=float(row.get("high") or 0),
                low=float(row.get("low") or 0),
                close=float(row.get("close") or 0),
                volume=int(float(row.get("volume") or 0)),
            )
            for row in rows
            if isinstance(row, dict)
        ]
        return Candles(symbol=symbol, exchange="CRYPTO", interval=resolution, bars=bars)

    async def option_chain(self, session: Session, req: dict) -> OptionChain:
        underlying = str(req.get("underlying") or req.get("symbol") or "").strip().upper()
        expiry = M.option_expiry(req.get("expiry_date") or req.get("expiry"))
        if ":" in underlying:
            underlying = underlying.split(":", 1)[1]
        result = await self.exchange_call(
            session,
            "tickers",
            query={
                "contract_types": "call_options,put_options",
                "underlying_asset_symbols": underlying,
                "expiry_date": expiry,
            },
        )
        return OptionChain(**M.option_chain_from_tickers(result, underlying=underlying, expiry=expiry))

    async def market_depth(self, session: Session, symbols: list[str]) -> list[dict[str, Any]]:
        """L2 snapshots. The probe and read callers pass a symbol list."""
        out: list[dict[str, Any]] = []
        for symbol in symbols:
            name = M.product_symbol(symbol)
            book = await self.exchange_call(session, "l2_orderbook", path_params={"symbol": name})
            out.append(book if isinstance(book, dict) else {"symbol": name, "buy": [], "sell": []})
        return out

    async def profile(self, session: Session) -> dict[str, Any]:
        result = await self.exchange_call(session, "trading_preferences")
        return result if isinstance(result, dict) else {}

    async def order_details(self, session: Session, order_id: str) -> dict[str, Any]:
        result = await self.exchange_call(session, "order_by_id", path_params={"order_id": order_id})
        if not isinstance(result, dict):
            raise BrokerReadResponseInvalid
        _validate_book_rows([result], operation="order_by_id")
        if M.contract_evidence(result["id"], positive=True) != M.contract_evidence(order_id, positive=True):
            raise BrokerReadResponseInvalid
        return M.from_order(result)

    async def order_history(self, session: Session, *_args: Any, **_kwargs: Any) -> list[dict[str, Any]]:
        return [M.from_order(row) for row in await self._read_rows(session, "order_history")]

    async def arm_deadman(
        self,
        session: Session,
        *,
        heartbeat_id: str,
        ttl_ms: int,
        unhealthy_count: int = 2,
        impact: str = "high",
        product_symbols: list[str] | None = None,
        _router_token: object | None = None,
    ) -> Any:
        """Register a broker-side cancel-on-silence heartbeat. Does not start the ack loop."""
        self._require_router_token(_router_token, _ROUTER_TOKEN)
        body = F.deadman_create_body(
            heartbeat_id=heartbeat_id,
            impact=impact,
            unhealthy_count=unhealthy_count,
            product_symbols=product_symbols,
        )
        result = await self.exchange_call(session, "heartbeat_create", body=body, _router_token=_router_token)
        session.extra["deadman"] = {"heartbeat_id": heartbeat_id, "ttl_ms": int(ttl_ms)}
        return result

    async def acknowledge_deadman(self, session: Session, *, _router_token: object | None = None) -> Any:
        """Refresh one armed deadman. A missed ack lets Delta cancel open orders."""
        self._require_router_token(_router_token, _ROUTER_TOKEN)
        armed = session.extra.get("deadman")
        if not isinstance(armed, dict) or not armed.get("heartbeat_id"):
            raise BrokerError("Delta deadman is not armed", broker_id=self.broker_id)
        return await self.exchange_call(
            session,
            "heartbeat_ack",
            body=F.deadman_ack_body(heartbeat_id=str(armed["heartbeat_id"]), ttl_ms=int(armed["ttl_ms"])),
            _router_token=_router_token,
        )

    async def subscribe(self, session: Session, symbols: list[str], mode: str = "FULL") -> None:
        channel = "ob_l1" if str(mode).upper() in {"L1", "L2", "DEPTH"} else "ticker"
        booked = session.extra.setdefault("subscriptions", {})
        names = booked.setdefault(channel, [])
        for symbol in symbols:
            name = M.product_symbol(symbol)
            if name not in names:
                names.append(name)

    async def unsubscribe(self, session: Session, symbols: list[str]) -> None:
        booked = session.extra.get("subscriptions")
        if not isinstance(booked, dict):
            return
        drop = {M.product_symbol(symbol) for symbol in symbols}
        for channel, names in booked.items():
            booked[channel] = [name for name in names if name not in drop]

    def stream(self, session: Session) -> AsyncIterator[Any]:
        return self._stream_impl(session)

    async def _stream_impl(self, session: Session) -> AsyncIterator[Any]:
        symbols = _subscription(session, "ticker")
        if not symbols:
            raise BrokerError("Delta stream requires subscribe() before the socket opens", broker_id=self.broker_id)
        async for raw in self._socket_frames(session, public=True, opener=self._open_messages("ticker", symbols)):
            tick = F.parse_ticker_frame(raw)
            if tick is not None:
                yield tick

    def stream_orders(self, session: Session) -> AsyncIterator[dict[str, Any]]:
        """Private order, position, margin, and fill updates after key-auth."""
        return self._order_stream_impl(session)

    async def _order_stream_impl(self, session: Session) -> AsyncIterator[dict[str, Any]]:
        async for raw in self._socket_frames(
            session,
            public=False,
            opener=self._private_open_messages(session),
        ):
            update = F.parse_private_frame(raw)
            if update is not None:
                yield update

    def _open_messages(self, channel: str, symbols: list[str]) -> list[dict[str, Any]]:
        return [F.subscribe_message(channel, symbols)]

    def _private_open_messages(self, session: Session) -> list[dict[str, Any]]:
        secret = str(session.extra.get("api_secret") or "")
        if not secret:
            raise BrokerError("Delta private socket requires the API secret from login", broker_id=self.broker_id)
        timestamp = str(self._clock())
        return [
            F.private_auth_message(api_key=session.access_token, api_secret=secret, timestamp=timestamp),
            F.subscribe_message("orders", ["all"]),
            F.subscribe_message("positions", ["all"]),
        ]

    async def _socket_frames(
        self,
        session: Session,
        *,
        public: bool,
        opener: list[dict[str, Any]],
    ) -> AsyncIterator[Any]:
        url = str(session.extra.get("public_ws" if public else "private_ws") or "")
        if not url:
            raise UnsupportedCapabilityError(
                F.socket_required_message(str(session.extra.get("environment") or "")),
                broker_id=self.broker_id,
            )
        factory = self._socket_factory or _live_socket
        async with factory(url) as socket:
            for message in opener:
                await socket.send(json.dumps(message))
            async for raw in socket:
                yield raw

    async def reconcile(self, session: Session) -> ReconciliationReport:
        from flinttrade_gateway.reconciliation import (
            EMPTY_LOCAL_STATE,
            build_report,
            declare_unavailable_order_fields,
        )

        generated_at = datetime.now(UTC)
        try:
            broker_orders = declare_unavailable_order_fields(
                await self.order_book(session),
                fields=("variety", "validity", "strategy"),
            )
            broker_positions = await self.positions(session)
            broker_holdings = await self.holdings(session)
        except (BrokerError, ValueError) as exc:
            return build_report(
                adapter_id=self.broker_id,
                account_id=session.account_id,
                generated_at=generated_at,
                local_state=EMPTY_LOCAL_STATE,
                error=f"broker fetch failed: {exc}",
            )
        return build_report(
            adapter_id=self.broker_id,
            account_id=session.account_id,
            generated_at=generated_at,
            broker_orders=broker_orders,
            broker_positions=broker_positions,
            broker_holdings=broker_holdings,
            local_state=EMPTY_LOCAL_STATE,
        )

    async def exchange_call(
        self,
        session: Session,
        name: str,
        *,
        query: Mapping[str, Any] | None = None,
        body: Mapping[str, Any] | None = None,
        path_params: Mapping[str, Any] | None = None,
        _router_token: object | None = None,
        _preserve_envelope: bool = False,
    ) -> Any:
        """Call one swagger endpoint. Writes refuse unless the router token is present."""
        spec = M.ENDPOINTS.get(name)
        if spec is None:
            raise BrokerError(f"Unknown Delta endpoint {name!r}", broker_id=self.broker_id)
        method, template = spec
        if M.is_write(method):
            self._require_router_token(_router_token, _ROUTER_TOKEN)
        if name == "place_order":
            M.validate_create_payload(body)
        elif name == "place_bracket":
            body = M.to_position_bracket_create_payload(body)
        elif name == "edit_bracket":
            if not isinstance(body, Mapping) or "id" not in body:
                raise BrokerError("Delta order bracket edits require id", broker_id=self.broker_id)
            body = M.to_order_bracket_edit_payload(body["id"], {key: value for key, value in body.items() if key != "id"})
        path = M.fill_path(template, path_params)
        query_text = M.query_string(query)
        body_text = M.body_string(dict(body) if body is not None else None)
        secret = str(session.extra.get("api_secret") or "")
        if secret:
            headers = M.signed_headers(
                api_key=session.access_token,
                api_secret=secret,
                method=method,
                timestamp=str(self._clock()),
                path=path,
                query=query_text,
                body=body_text,
            )
        else:
            headers = M.public_headers()
        url = f"{session.extra['rest_base']}{path}{query_text}"
        status, payload = await run_blocking_sdk_call(self._transport(session), method, url, headers, body_text)
        return M.unwrap(payload, status=status, endpoint=path, preserve_envelope=_preserve_envelope)

    def _transport(self, session: Session) -> Transport:
        transport = session.extra.get("transport")
        if transport is None:
            raise BrokerError("Delta session has no transport", broker_id=self.broker_id)
        return transport

    async def _open_order_rows(self, session: Session) -> list[dict[str, Any]]:
        return await self._read_rows(session, "open_orders", query={"states": "open,pending"})

    async def _open_position_rows(self, session: Session) -> list[dict[str, Any]]:
        rows = await self._read_rows(session, "positions")
        return [row for row in rows if M.contract_evidence(row["size"], signed=True) != 0]

    async def _read_rows(
        self, session: Session, name: str, *, query: Mapping[str, Any] | None = None,
    ) -> list[dict[str, Any]]:
        """Exhaust documented cursors or refuse; do not equate traversal with coherence."""
        paginated = name in {"open_orders", "order_history", "fills"}
        parameters = dict(query or {})
        if paginated:
            parameters["page_size"] = 100
        rows: list[dict[str, Any]] = []
        pages: list[dict[str, Any]] = []
        cursors: set[str] = set()
        evidence = {"pages": pages, "pagination_exhausted": False}
        session.extra.setdefault("delta_read_evidence", {})[name] = evidence
        for _ in range(_READ_PAGE_LIMIT):
            envelope = await self.exchange_call(session, name, query=parameters, _preserve_envelope=True)
            if not isinstance(envelope, dict) or envelope.get("success") is not True:
                raise BrokerReadResponseInvalid
            pages.append(deepcopy(envelope))
            page = envelope.get("result")
            if not isinstance(page, list) or any(not isinstance(row, dict) for row in page):
                raise BrokerReadResponseInvalid
            if envelope.get("error") or envelope.get("errors"):
                raise BrokerReadResponseInvalid
            rows.extend(page)
            if paginated:
                meta = envelope.get("meta")
                if not isinstance(meta, dict) or "after" not in meta:
                    raise BrokerReadResponseInvalid
                cursor = meta["after"]
                for field in ("after", "before"):
                    if field in meta and meta[field] is not None and (
                        not isinstance(meta[field], str) or not meta[field].strip()
                    ):
                        raise BrokerReadResponseInvalid
                if cursor is not None:
                    if cursor in cursors:
                        raise BrokerReadResponseInvalid
                    cursors.add(cursor)
                    parameters["after"] = cursor
                    continue
                if meta.get("has_more") is True:
                    raise BrokerReadResponseInvalid
            elif "meta" in envelope:
                meta = envelope["meta"]
                if not isinstance(meta, dict) or meta.get("after") is not None:
                    # Position pagination has no established contract here.
                    raise BrokerReadResponseInvalid
            _validate_book_rows(rows, operation=name)
            evidence["pagination_exhausted"] = True
            return rows
        raise BrokerReadResponseInvalid

    async def _position_size(self, session: Session, symbol: str) -> int:
        for row in await self._open_position_rows(session):
            if str(row.get("product_symbol") or "") == symbol:
                return M.contract_evidence(row["size"], signed=True)
        return 0


def _validate_book_rows(rows: list[dict[str, Any]], *, operation: str) -> None:
    """Validate each observed identity/count, without conflating fills and order totals."""
    identities: set[Any] = set()
    by_product: dict[int, str] = {}
    by_symbol: dict[str, int] = {}
    for row in rows:
        symbol = row.get("product_symbol")
        if not isinstance(symbol, str) or not symbol or symbol != symbol.strip():
            raise BrokerReadResponseInvalid
        if "product_id" in row:
            product_id = M.contract_evidence(row["product_id"], positive=True)
            if (product_id in by_product and by_product[product_id] != symbol) or (
                symbol in by_symbol and by_symbol[symbol] != product_id
            ):
                raise BrokerReadResponseInvalid
            by_product[product_id], by_symbol[symbol] = symbol, product_id
        if operation == "positions":
            identity = symbol
            M.contract_evidence(row.get("size"), signed=True)
        elif operation == "fills":
            # Fill IDs are UUID strings; settlement order IDs can also be UUIDs.
            # Treat native strings as opaque, never repair or numeric-coerce them.
            identity = _opaque_read_id(row.get("id"))
            _opaque_read_id(row.get("order_id"))
            M.from_fill(row)
        else:
            identity = M.contract_evidence(row.get("id"), positive=True)
            M.from_order(row)
        if identity in identities:
            raise BrokerReadResponseInvalid
        identities.add(identity)


def _opaque_read_id(raw: Any) -> str:
    if isinstance(raw, int) and not isinstance(raw, bool) and raw > 0:
        return str(raw)
    if isinstance(raw, str) and raw and raw == raw.strip():
        return raw
    raise BrokerReadResponseInvalid


def _ack_summary(
    *, before: list[dict[str, Any]], after: list[dict[str, Any]] | None,
    outcome: Any, operation: str, readback_error: str = "",
) -> dict[str, Any]:
    """Count ACKs, not cancellations/fills/closure; missing readback stays unknown."""
    evidence = M.operation_evidence(outcome, operation=operation)
    key = "id" if operation == "cancel_all_orders" else "product_symbol"
    targets = {str(row[key]): row for row in before}
    remaining = {str(row[key]): row for row in after or []}
    universe = targets | remaining
    native_result = outcome.get("result") if isinstance(outcome, Mapping) else None
    acknowledged = isinstance(outcome, Mapping) and outcome.get("success") is True
    if isinstance(outcome, Mapping) and "result" in outcome:
        acknowledged = acknowledged and isinstance(native_result, (Mapping, list))
    if isinstance(native_result, Mapping) and not set(native_result).intersection({
        "success", "orders", "errors", "error", "skipped_products",
    }):
        acknowledged = False
    for source in (outcome, native_result):
        if not isinstance(source, Mapping):
            continue
        if "success" in source and source["success"] is not True:
            acknowledged = False
        for field in ("errors", "skipped_products", "orders"):
            if field in source and (not isinstance(source[field], list)
                                    or any(not isinstance(item, Mapping) for item in source[field])):
                acknowledged = False
    failures = evidence["native_errors"] + evidence["skipped_products"]
    for item in evidence["items"]:
        if (not isinstance(item, Mapping) or not set(item).intersection({"id", "order_id", "product_id", "product_symbol"})
                or item.get("success") is False or item.get("error") or item.get("errors")):
            failures.append(item)
    errors, ack_ids = [], []
    identity_fields = ("id", "order_id", "product_id", "product_symbol")
    unscoped = any(not isinstance(item, Mapping) or not any(
        field in item and field in row and str(item[field]) == str(row[field])
        for row in universe.values() for field in identity_fields
    ) for item in failures)
    for identity, row in universe.items():
        matched = [item for item in failures if isinstance(item, Mapping) and any(
            field in item and field in row and str(item[field]) == str(row[field]) for field in identity_fields
        )]

        if matched:
            errors.append({"order_id": identity, "reason": matched[0].get("reason", "native_error")})
        elif not acknowledged or unscoped or after is None:
            errors.append({"order_id": identity, "reason": "outcome_unknown"})
        elif identity in remaining:
            errors.append({"order_id": identity, "reason": "still_open"})
        else:
            ack_ids.append(identity)
    if not universe and (not acknowledged or failures or after is None):
        errors.append({"reason": "outcome_unknown"})
    return evidence | {
        "errors": errors, "total": len(errors) + len(ack_ids), "success": len(ack_ids),
        "order_ids": ack_ids if operation == "cancel_all_orders" else [],
        "acknowledgement_only": True, "readback_available": after is not None,
        "readback_error": readback_error,
    }


def _emergency_exit_tag(symbol: str, size: int) -> str:
    identity = f"{symbol}|{size}".encode()
    return "fte-delta-" + hashlib.sha256(identity).hexdigest()[:16]


def _subscription(session: Session, channel: str) -> list[str]:
    booked = session.extra.get("subscriptions")
    if not isinstance(booked, dict):
        return []
    names = booked.get(channel)
    return [str(name) for name in names] if isinstance(names, list) else []


def _live_socket(url: str) -> Any:
    """Open the documented socket. Tests inject ``socket_factory`` instead."""
    import websockets

    return websockets.connect(url, open_timeout=10)


async def run_deadman_acks(
    adapter: DeltaAdapter,
    session: Session,
    *,
    interval_seconds: float,
    stop: asyncio.Event,
    _router_token: object,
) -> None:
    """Acknowledge an armed deadman until ``stop`` is set.

    The caller must arm through the router first. This loop is not started by
    login: a missed acknowledgement is an order-cancelling broker action.
    """
    if interval_seconds <= 0:
        raise BrokerError("Delta deadman ack interval must be positive", broker_id=adapter.broker_id)
    while not stop.is_set():
        await adapter.acknowledge_deadman(session, _router_token=_router_token)
        try:
            await asyncio.wait_for(stop.wait(), timeout=interval_seconds)
        except TimeoutError:
            continue
