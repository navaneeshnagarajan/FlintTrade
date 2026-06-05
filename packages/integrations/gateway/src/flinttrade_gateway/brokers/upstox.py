"""Upstox v2 native adapter (doc-grounded against upstox-python).

Implements the BrokerAdapter contract for Upstox: auth, the gated write surface
(place/modify/cancel), and the portfolio reads (order book / trade book /
positions / holdings / funds). Request/response translation lives in
``upstox_mapping`` and is unit-tested.

The Upstox SDK is OpenAPI-generated (typed request/response models), so the
adapter talks to a small dict-based facade (``UpstoxClient``) that owns the SDK
models; ``login`` builds the live facade and tests inject a mock one. The adapter
itself only depends on the facade's dict interface, so it is fully mock-testable
without the SDK.

Market data — quotes (full market quote), historical candles (v3 history) and
the put/call option chain — is implemented too; only live tick streaming remains
a separate wave. Response parsing lives in ``upstox_mapping`` and is unit-tested.

Safety: writes still require the router's per-process ``_ROUTER_TOKEN`` (§8). The
adapter is NOT registered in ``build_broker_router`` — it stays dormant until SDK
attestation + credentials.
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

from . import upstox_mapping as M
from ._base import BrokerAdapter, Session

if TYPE_CHECKING:  # pragma: no cover - typing only
    from flinttrade_core.models import Candles, OptionChain, Order, Position, Quote, Trade
    from flinttrade_gateway.reconciliation import ReconciliationReport

_PENDING = "Upstox {0} — streaming wave pending live SDK verification"


def _split_symbol(raw: str) -> tuple[str, str]:
    """Split a ``"NSE:RELIANCE"`` quote symbol into ``(exchange, name)``.

    A bare symbol (no ``":"``) defaults to the NSE cash segment.
    """
    if ":" in raw:
        exchange, name = raw.split(":", 1)
        return exchange.strip().upper(), name.strip()
    return "NSE", raw.strip()

UPSTOX_CAPABILITIES = Capabilities(
    segments=(
        Segments.NSE_EQ | Segments.BSE_EQ | Segments.NFO | Segments.BFO
        | Segments.CDS | Segments.BCD | Segments.MCX | Segments.MF
    ),
    order_types=(
        OrderTypes.MARKET | OrderTypes.LIMIT | OrderTypes.SL | OrderTypes.SLM
        | OrderTypes.MIS | OrderTypes.CNC | OrderTypes.NRML | OrderTypes.AMO
        | OrderTypes.GTT | OrderTypes.ICEBERG | OrderTypes.CO
    ),
    depth_levels=DepthLevels.L5,
    tick_protocol=TickProtocol.UPSTOX_JSON,
    auth_model=AuthModel.OAUTH_DAILY,
    session_lifetime_hours=24.0,
    sandbox=True,
    rate_limit_orders_per_sec=10,
    rate_limit_orders_per_min=500,
    rate_limit_data_per_sec=50,
    rate_limit_quote_per_sec=50,
    rate_limit_non_trading_per_sec=50,
    algo_tag_required=False,
    cost_paid=False,
    historical_intraday_intervals_minutes=[1, 3, 5, 15, 30],
    option_chain_supported=True,
    option_chain_greeks_supported=True,
    streaming_supported=True,
    cover_order_native=True,
    iceberg_native=True,
    gtt_native=True,
    modify_qty_supported=True,
)


class UpstoxClient:
    """Dict-based facade over the upstox-python OpenAPI SDK (lazy import).

    Owns the SDK request/response models so the adapter stays SDK-free. Built by
    ``UpstoxAdapter.login`` for live use; tests inject a mock with the same
    method surface instead.
    """

    _V = "v2"

    def __init__(self, access_token: str) -> None:
        import upstox_client  # noqa: PLC0415

        cfg = upstox_client.Configuration()
        cfg.access_token = access_token
        api = upstox_client.ApiClient(cfg)
        self._upstox = upstox_client
        self._order = upstox_client.OrderApi(api)
        self._portfolio = upstox_client.PortfolioApi(api)
        self._user = upstox_client.UserApi(api)
        self._market = upstox_client.MarketQuoteApi(api)
        self._history = upstox_client.HistoryV3Api(api)
        self._options = upstox_client.OptionsApi(api)

    def place_order(self, params: dict[str, Any]) -> dict[str, Any]:
        body = self._upstox.PlaceOrderRequest(**params)
        return self._order.place_order(body, self._V).to_dict()

    def modify_order(self, params: dict[str, Any]) -> dict[str, Any]:
        body = self._upstox.ModifyOrderRequest(**params)
        return self._order.modify_order(body, self._V).to_dict()

    def cancel_order(self, order_id: str) -> dict[str, Any]:
        return self._order.cancel_order(order_id, self._V).to_dict()

    def order_book(self) -> dict[str, Any]:
        return self._order.get_order_book(self._V).to_dict()

    def trade_book(self) -> dict[str, Any]:
        return self._order.get_trade_history(self._V).to_dict()

    def positions(self) -> dict[str, Any]:
        return self._portfolio.get_positions(self._V).to_dict()

    def holdings(self) -> dict[str, Any]:
        return self._portfolio.get_holdings(self._V).to_dict()

    def funds(self) -> dict[str, Any]:
        return self._user.get_user_fund_margin(self._V).to_dict()

    def full_quote(self, instrument_keys: str) -> dict[str, Any]:
        return self._market.get_full_market_quote(instrument_keys, self._V).to_dict()

    def historical(self, instrument_key: str, unit: str, interval: str, to_date: str, from_date: str) -> dict[str, Any]:
        return self._history.get_historical_candle_data1(
            instrument_key, unit, interval, to_date, from_date
        ).to_dict()

    def option_chain(self, instrument_key: str, expiry_date: str) -> dict[str, Any]:
        return self._options.get_put_call_option_chain(instrument_key, expiry_date).to_dict()


class UpstoxAdapter(BrokerAdapter):
    """Native Upstox adapter.

    Args:
        client_factory: ``session -> UpstoxClient``-like facade (tests inject a
            mock). When omitted, ``login`` builds the live facade.
        instrument_resolver: ``(symbol, exchange) -> instrument_token`` — Upstox
            trades by instrument token (e.g. ``"NSE_EQ|INE002A01018"``).
    """

    def __init__(
        self,
        *,
        client_factory: Callable[[Session], Any] | None = None,
        instrument_resolver: Callable[[str, str], str] | None = None,
    ) -> None:
        self._client_factory = client_factory
        self._instrument_resolver = instrument_resolver

    @property
    def broker_id(self) -> str:
        return "upstox"

    @property
    def capabilities(self) -> Capabilities:
        return UPSTOX_CAPABILITIES

    # ---------- helpers ----------

    def _client(self, session: Session) -> Any:
        if self._client_factory is not None:
            return self._client_factory(session)
        client = session.extra.get("client")
        if client is None:
            raise BrokerError("Upstox client not initialised — call login() first")
        return client

    def _resolve_instrument(self, symbol: str, exchange: str) -> str:
        if self._instrument_resolver is not None:
            return str(self._instrument_resolver(symbol, exchange))
        raise BrokerError(
            f"Cannot resolve Upstox instrument_token for {symbol}/{exchange} — "
            "configure an instrument resolver"
        )

    @staticmethod
    async def _call(fn: Callable[..., Any], *args: Any, **kwargs: Any) -> Any:
        return await asyncio.to_thread(fn, *args, **kwargs)

    @staticmethod
    def _rows(resp: Any) -> list[dict[str, Any]]:
        data = resp.get("data", []) if isinstance(resp, dict) else []
        return data if isinstance(data, list) else []

    # ---------- auth lifecycle ----------

    async def login(self, credentials: dict) -> Session:
        access_token = str(credentials.get("access_token") or "")
        if not access_token:
            raise BrokerError("Upstox login requires an access_token")
        client = None if self._client_factory is not None else UpstoxClient(access_token)
        return Session(
            access_token=access_token,
            expires_at=datetime.now(tz=timezone.utc).timestamp() + 24 * 3600,
            account_id=str(credentials.get("client_id", "")),
            adapter_id="upstox",
            extra={"client": client},
        )

    async def refresh(self, session: Session) -> Session:
        # Upstox tokens are single-day (expire ~03:30 IST next day, no refresh
        # token) — a fresh login() is required at expiry.
        return session

    async def logout(self, session: Session) -> None:
        session.extra.pop("client", None)
        return None

    # ---------- trading: writes (router-only) ----------

    async def place_order(self, session: Session, order: Order, *, _router_token: object | None = None) -> str:
        self._require_router_token(_router_token, _ROUTER_TOKEN)
        token = self._resolve_instrument(order.symbol, order.exchange)
        tag = session.algo_id or None
        params = M.to_place_order_params(order, token, tag=tag)
        resp = await self._call(self._client(session).place_order, params)
        return M.extract_order_id(resp)

    async def modify_order(
        self, session: Session, order_id: str, changes: dict, *, _router_token: object | None = None
    ) -> None:
        self._require_router_token(_router_token, _ROUTER_TOKEN)
        params = M.to_modify_order_params(order_id, changes)
        await self._call(self._client(session).modify_order, params)

    async def cancel_order(
        self, session: Session, order_id: str, *, _router_token: object | None = None
    ) -> None:
        self._require_router_token(_router_token, _ROUTER_TOKEN)
        await self._call(self._client(session).cancel_order, str(order_id))

    # ---------- trading: reads ----------

    async def order_book(self, session: Session) -> list[Order]:
        resp = await self._call(self._client(session).order_book)
        return [M.from_upstox_order(r) for r in self._rows(resp)]  # type: ignore[misc]

    async def trade_book(self, session: Session) -> list[Trade]:
        resp = await self._call(self._client(session).trade_book)
        return [M.from_upstox_trade(r) for r in self._rows(resp)]  # type: ignore[misc]

    async def positions(self, session: Session) -> list[Position]:
        resp = await self._call(self._client(session).positions)
        return [M.from_upstox_position(r) for r in self._rows(resp)]  # type: ignore[misc]

    async def holdings(self, session: Session) -> list[dict]:
        resp = await self._call(self._client(session).holdings)
        return [M.from_upstox_holding(r) for r in self._rows(resp)]

    async def funds(self, session: Session) -> dict:
        resp = await self._call(self._client(session).funds)
        return M.from_upstox_funds(resp)

    # ---------- market data ----------

    async def quotes(self, session: Session, symbols: list[str]) -> list[Quote]:
        from flinttrade_core.models import Quote  # noqa: PLC0415

        # Resolve every symbol to its instrument key and batch into one request.
        keys: list[str] = []
        for raw in symbols:
            exchange, name = _split_symbol(raw)
            keys.append(self._resolve_instrument(name, exchange))
        resp = await self._call(self._client(session).full_quote, ",".join(keys))
        data = resp.get("data", {}) if isinstance(resp, dict) else {}
        records = data.values() if isinstance(data, dict) else []
        return [Quote(**M.from_upstox_quote(rec)) for rec in records if isinstance(rec, dict)]

    async def historical(self, session: Session, req: dict) -> Candles:
        from flinttrade_core.models import OHLCV, Candles  # noqa: PLC0415

        symbol = str(req.get("symbol", ""))
        exchange = str(req.get("exchange", "NSE"))
        interval = str(req.get("interval", req.get("timeframe", "1d")))
        instrument_key = str(req.get("instrument_key") or self._resolve_instrument(symbol, exchange))
        params = M.to_history_params({**req, "instrument_key": instrument_key})
        resp = await self._call(
            self._client(session).historical,
            params["instrument_key"], params["unit"], params["interval"],
            params["to_date"], params["from_date"],
        )
        cd = M.from_upstox_candles(symbol, exchange, interval, resp)
        return Candles(
            symbol=cd["symbol"], exchange=cd["exchange"], interval=cd["interval"],
            bars=[OHLCV(**b) for b in cd["bars"]],
        )

    async def option_chain(self, session: Session, req: dict) -> OptionChain:
        from flinttrade_core.models import OptionChain, OptionChainStrike  # noqa: PLC0415

        underlying = str(req.get("symbol") or req.get("underlying") or "")
        exchange = str(req.get("exchange", "NSE_INDEX"))
        expiry = str(req.get("expiry") or req.get("expiry_date") or "")
        instrument_key = str(req.get("instrument_key") or self._resolve_instrument(underlying, exchange))
        resp = await self._call(self._client(session).option_chain, instrument_key, expiry)
        oc = M.to_option_chain_dict(underlying, exchange, resp)
        return OptionChain(
            underlying=oc["underlying"], exchange=oc["exchange"],
            strikes=[OptionChainStrike(**s) for s in oc["strikes"]],
        )

    # ---------- streaming (separate wave) ----------

    def stream(self, session: Session) -> AsyncIterator[Any]:
        raise NotImplementedError(_PENDING.format("stream"))

    async def subscribe(self, session: Session, symbols: list[str], mode: str = "FULL") -> None:
        raise NotImplementedError(_PENDING.format("subscribe"))

    async def unsubscribe(self, session: Session, symbols: list[str]) -> None:
        raise NotImplementedError(_PENDING.format("unsubscribe"))

    async def reconcile(self, session: Session) -> ReconciliationReport:
        raise NotImplementedError(_PENDING.format("reconcile"))


_ROUTER_TOKEN = object()
