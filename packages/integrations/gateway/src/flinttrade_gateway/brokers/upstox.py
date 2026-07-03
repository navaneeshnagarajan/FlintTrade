"""Upstox v2/v3 native adapter (doc-grounded against upstox-python).

Implements the FULL BrokerAdapter contract for Upstox: auth (OAuth login URL,
token exchange, logout), the gated write surface (place/modify/cancel with
variety dispatch across the v2 regular/AMO, v3 sliced and v3 GTT endpoints,
plus multi-order, cancel-all, exit-all-positions and convert-position), the
portfolio reads (order book / details / history, trade book / trades-by-order /
date-range trade history, positions / MTF positions, holdings, funds), pre-trade
charges (brokerage + margin), market data (full quotes, v3 OHLC/LTP/Greek
quotes, v2+v3 historical candles incl. one-second bars and expired-instrument
history, option chain + contracts + expiries), market information (timings /
holidays / status), reports (trade-wise P&L + charges), the user profile and
kill switch, and the v3 streaming surface (feed authorisation + tick stream via
an injected decoded-message feed). Request/response translation lives in
``upstox_mapping`` and is unit-tested.

The Upstox SDK is OpenAPI-generated (typed request/response models), so the
adapter talks to a small dict-based facade (``UpstoxClient``) that owns the SDK
models; ``login`` builds the live facade and tests inject a mock one. The adapter
itself only depends on the facade's dict interface, so it is fully mock-testable
without the SDK.

Safety: writes still require the router's per-process ``_ROUTER_TOKEN`` (§8).
``build_broker_router``'s native-activation factory registers this adapter
automatically once its pinned SDK is attested AND vault credentials exist;
until then it stays dormant (the ``brokers.lock`` Upstox pin is still
PLACEHOLDER, so it is ``skipped`` and never activates today).
"""

from __future__ import annotations

import asyncio
import functools
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
    from flinttrade_gateway.reconciliation import LocalStateSnapshot, ReconciliationReport

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
    # No OrderTypes.CO/BO: Upstox retired cover & bracket orders, the mapping
    # refuses variety "cover"/"bracket", and cover_order_native is False below.
    # Advertising CO here would contradict that (routers key off this flag set).
    order_types=(
        OrderTypes.MARKET | OrderTypes.LIMIT | OrderTypes.SL | OrderTypes.SLM
        | OrderTypes.MIS | OrderTypes.CNC | OrderTypes.NRML | OrderTypes.AMO
        | OrderTypes.GTT | OrderTypes.ICEBERG
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
    # Upstox intraday lookback is interval-dependent (HistoryApi.md duration
    # table): 1-minute candles reach only the last ~1 month, while 30-minute
    # candles reach the last 1 year. We advertise the SMALLEST documented window
    # (~31 days, the 1-minute bound) so the broker-recommendation engine never
    # over-credits Upstox for a depth that only the coarsest interval provides.
    # Upstox does not document a per-request candle cap, so it is left at 0.
    historical_max_lookback_days_intraday=31,
    historical_max_candles_per_request=0,
    option_chain_supported=True,
    option_chain_greeks_supported=True,
    streaming_supported=True,
    # Honesty: Upstox retired bracket/cover orders, so cover stays False for
    # good. GTT (v3 /order/gtt/*) and sliced orders (v3 place with slice=true,
    # our iceberg equivalent) ARE wired through the gated place/modify/cancel
    # dispatch below, so both are advertised. The capability-honesty test in
    # tests/test_upstox_mapping.py pins cover to False and these two to True.
    cover_order_native=False,
    iceberg_native=True,
    gtt_native=True,
    modify_qty_supported=True,
)


def _translate_api_errors(fn: Callable[..., Any]) -> Callable[..., Any]:
    """Wrap a facade method so any SDK ``ApiException`` is mapped + re-raised.

    The OpenAPI-generated SDK raises ``upstox_client.rest.ApiException`` on any
    non-2xx response. Per broker-adapter-contract §7 a broker-native error MUST
    be mapped to the FlintTrade exception taxonomy and never escape the adapter,
    so this catches the SDK exception, translates it via
    :func:`upstox_mapping.map_upstox_error` (preserving the broker message/code)
    and re-raises the mapped ``BrokerError`` ``from`` the original.
    """

    @functools.wraps(fn)
    def _wrapped(*args: Any, **kwargs: Any) -> Any:
        try:
            return fn(*args, **kwargs)
        except BrokerError:
            raise  # already in-taxonomy — propagate untouched
        except Exception as exc:  # noqa: BLE001 - re-raised as a mapped BrokerError
            if M.is_api_exception(exc):
                raise M.map_upstox_error(exc) from exc
            raise

    return _wrapped


def _facade_with_error_translation(cls: type) -> type:
    """Class decorator: wrap every public facade method with error translation.

    Applies :func:`_translate_api_errors` to each public callable (instance and
    static methods) so the mapping is applied uniformly to the WHOLE facade
    surface — no method can forget to translate its SDK errors.
    """
    for name, attr in list(vars(cls).items()):
        if name.startswith("_"):
            continue
        if isinstance(attr, staticmethod):
            setattr(cls, name, staticmethod(_translate_api_errors(attr.__func__)))
        elif callable(attr):
            setattr(cls, name, _translate_api_errors(attr))
    return cls


@_facade_with_error_translation
class UpstoxClient:
    """Dict-based facade over the upstox-python OpenAPI SDK (lazy import).

    Owns the SDK request/response models so the adapter stays SDK-free. Built by
    ``UpstoxAdapter.login`` for live use; tests inject a mock with the same
    method surface instead.

    Every public method is wrapped by :func:`_facade_with_error_translation` so a
    raw SDK ``ApiException`` is mapped to the FlintTrade exception taxonomy
    (contract §7) before it can escape.
    """

    _V = "v2"

    def __init__(self, access_token: str) -> None:
        import upstox_client  # noqa: PLC0415

        cfg = upstox_client.Configuration()
        cfg.access_token = access_token
        api = upstox_client.ApiClient(cfg)
        self._upstox = upstox_client
        self._order = upstox_client.OrderApi(api)
        self._order_v3 = upstox_client.OrderApiV3(api)
        self._portfolio = upstox_client.PortfolioApi(api)
        self._user = upstox_client.UserApi(api)
        self._login = upstox_client.LoginApi(api)
        self._market = upstox_client.MarketQuoteApi(api)
        self._market_v3 = upstox_client.MarketQuoteV3Api(api)
        self._history = upstox_client.HistoryV3Api(api)
        self._expired = upstox_client.ExpiredInstrumentApi(api)
        self._options = upstox_client.OptionsApi(api)
        self._charge = upstox_client.ChargeApi(api)
        self._post_trade = upstox_client.PostTradeApi(api)
        self._pnl = upstox_client.TradeProfitAndLossApi(api)
        self._market_info = upstox_client.MarketHolidaysAndTimingsApi(api)
        self._instruments = upstox_client.InstrumentsApi(api)
        self._websocket = upstox_client.WebsocketApi(api)

    # ---- auth ----

    @staticmethod
    def exchange_token(params: dict[str, Any]) -> dict[str, Any]:
        """Exchange a single-use OAuth ``code`` for an access token (no auth)."""
        import upstox_client  # noqa: PLC0415

        api = upstox_client.ApiClient(upstox_client.Configuration())
        return upstox_client.LoginApi(api).token("v2", **params).to_dict()

    def logout(self) -> dict[str, Any]:
        return self._login.logout(self._V).to_dict()

    # ---- orders: writes ----

    def place_order(self, params: dict[str, Any]) -> dict[str, Any]:
        body = self._upstox.PlaceOrderRequest(**params)
        return self._order.place_order(body, self._V).to_dict()

    def place_order_v3(self, params: dict[str, Any]) -> dict[str, Any]:
        body = self._upstox.PlaceOrderV3Request(**params)
        return self._order_v3.place_order(body).to_dict()

    def place_multi_order(self, payloads: list[dict[str, Any]]) -> dict[str, Any]:
        body = [self._upstox.MultiOrderRequest(**p) for p in payloads]
        return self._order.place_multi_order(body).to_dict()

    def modify_order(self, params: dict[str, Any]) -> dict[str, Any]:
        body = self._upstox.ModifyOrderRequest(**params)
        return self._order.modify_order(body, self._V).to_dict()

    def cancel_order(self, order_id: str) -> dict[str, Any]:
        return self._order.cancel_order(order_id, self._V).to_dict()

    def cancel_multi_order(self, tag: str | None = None, segment: str | None = None) -> dict[str, Any]:
        kwargs: dict[str, Any] = {}
        if tag:
            kwargs["tag"] = tag
        if segment:
            kwargs["segment"] = segment
        return self._order.cancel_multi_order(**kwargs).to_dict()

    def exit_positions(self, tag: str | None = None, segment: str | None = None) -> dict[str, Any]:
        kwargs: dict[str, Any] = {}
        if tag:
            kwargs["tag"] = tag
        if segment:
            kwargs["segment"] = segment
        return self._order.exit_positions(**kwargs).to_dict()

    # ---- orders: GTT (v3) ----

    def place_gtt_order(self, params: dict[str, Any]) -> dict[str, Any]:
        rules = [self._upstox.GttRule(**r) for r in params.get("rules", [])]
        body = self._upstox.GttPlaceOrderRequest(**{**params, "rules": rules})
        return self._order_v3.place_gtt_order(body).to_dict()

    def modify_gtt_order(self, params: dict[str, Any]) -> dict[str, Any]:
        rules = [self._upstox.GttRule(**r) for r in params.get("rules", [])]
        body = self._upstox.GttModifyOrderRequest(**{**params, "rules": rules})
        return self._order_v3.modify_gtt_order(body).to_dict()

    def cancel_gtt_order(self, params: dict[str, Any]) -> dict[str, Any]:
        body = self._upstox.GttCancelOrderRequest(**params)
        return self._order_v3.cancel_gtt_order(body).to_dict()

    def gtt_order_details(self, gtt_order_id: str | None = None) -> dict[str, Any]:
        kwargs = {"gtt_order_id": gtt_order_id} if gtt_order_id else {}
        return self._order_v3.get_gtt_order_details(**kwargs).to_dict()

    # ---- orders: reads ----

    def order_book(self) -> dict[str, Any]:
        return self._order.get_order_book(self._V).to_dict()

    def order_details(self, order_id: str) -> dict[str, Any]:
        # /v2/order/details — the latest snapshot of one order.
        return self._order.get_order_status(order_id=order_id).to_dict()

    def order_history(self, order_id: str | None = None, tag: str | None = None) -> dict[str, Any]:
        # /v2/order/history — every state transition for an order id or tag.
        kwargs: dict[str, Any] = {}
        if order_id:
            kwargs["order_id"] = order_id
        if tag:
            kwargs["tag"] = tag
        return self._order.get_order_details(self._V, **kwargs).to_dict()

    def trade_book(self) -> dict[str, Any]:
        return self._order.get_trade_history(self._V).to_dict()

    def trades_by_order(self, order_id: str) -> dict[str, Any]:
        return self._order.get_trades_by_order(order_id, self._V).to_dict()

    def trade_history(
        self, start_date: str, end_date: str, page_number: int, page_size: int, segment: str | None = None
    ) -> dict[str, Any]:
        kwargs = {"segment": segment} if segment else {}
        return self._post_trade.get_trades_by_date_range(
            start_date, end_date, page_number, page_size, **kwargs
        ).to_dict()

    # ---- portfolio ----

    def positions(self) -> dict[str, Any]:
        return self._portfolio.get_positions(self._V).to_dict()

    def mtf_positions(self) -> dict[str, Any]:
        return self._portfolio.get_mtf_positions().to_dict()

    def convert_position(self, params: dict[str, Any]) -> dict[str, Any]:
        body = self._upstox.ConvertPositionRequest(**params)
        return self._portfolio.convert_positions(body, self._V).to_dict()

    def holdings(self) -> dict[str, Any]:
        return self._portfolio.get_holdings(self._V).to_dict()

    # ---- user / funds / charges ----

    def funds(self) -> dict[str, Any]:
        return self._user.get_user_fund_margin(self._V).to_dict()

    def profile(self) -> dict[str, Any]:
        return self._user.get_profile(self._V).to_dict()

    def kill_switch_status(self) -> dict[str, Any]:
        return self._user.get_kill_switch().to_dict()

    def update_kill_switch(self, body: dict[str, Any]) -> dict[str, Any]:
        return self._user.update_kill_switch(body).to_dict()

    def brokerage(
        self, instrument_token: str, quantity: int, product: str, transaction_type: str, price: float
    ) -> dict[str, Any]:
        return self._charge.get_brokerage(
            instrument_token, quantity, product, transaction_type, price, self._V
        ).to_dict()

    def margin(self, instruments: list[dict[str, Any]]) -> dict[str, Any]:
        body = self._upstox.MarginRequest(
            instruments=[self._upstox.Instrument(**i) for i in instruments]
        )
        return self._charge.post_margin(body).to_dict()

    # ---- reports (trade-wise P&L) ----

    def pnl_report(
        self, segment: str, financial_year: str, page_number: int, page_size: int
    ) -> dict[str, Any]:
        return self._pnl.get_trade_wise_profit_and_loss_data(
            segment, financial_year, page_number, page_size, self._V
        ).to_dict()

    def pnl_charges(self, segment: str, financial_year: str) -> dict[str, Any]:
        return self._pnl.get_profit_and_loss_charges(segment, financial_year, self._V).to_dict()

    # ---- market data: quotes ----

    def full_quote(self, instrument_keys: str) -> dict[str, Any]:
        return self._market.get_full_market_quote(instrument_keys, self._V).to_dict()

    def ohlc_quote_v3(self, instrument_keys: str, interval: str) -> dict[str, Any]:
        return self._market_v3.get_market_quote_ohlc(interval, instrument_key=instrument_keys).to_dict()

    def ltp_quote_v3(self, instrument_keys: str) -> dict[str, Any]:
        return self._market_v3.get_ltp(instrument_key=instrument_keys).to_dict()

    def option_greeks_v3(self, instrument_keys: str) -> dict[str, Any]:
        return self._market_v3.get_market_quote_option_greek(instrument_key=instrument_keys).to_dict()

    # ---- market data: history ----

    def historical(self, instrument_key: str, unit: str, interval: str, to_date: str, from_date: str) -> dict[str, Any]:
        return self._history.get_historical_candle_data1(
            instrument_key, unit, interval, to_date, from_date
        ).to_dict()

    def intra_day(self, instrument_key: str, unit: str, interval: str) -> dict[str, Any]:
        # Upstox HistoryV3Api.get_intra_day_candle_data — the CURRENT trading
        # day's candles. The historical endpoint above EXCLUDES today, so this is
        # the only way to fetch intraday bars for the live session.
        return self._history.get_intra_day_candle_data(
            instrument_key, unit, interval
        ).to_dict()

    def expired_history(
        self, expired_instrument_key: str, interval: str, to_date: str, from_date: str
    ) -> dict[str, Any]:
        return self._expired.get_expired_historical_candle_data(
            expired_instrument_key, interval, to_date, from_date
        ).to_dict()

    def expiries(self, instrument_key: str) -> dict[str, Any]:
        return self._expired.get_expiries(instrument_key).to_dict()

    def expired_future_contracts(self, instrument_key: str, expiry_date: str) -> dict[str, Any]:
        return self._expired.get_expired_future_contracts(instrument_key, expiry_date).to_dict()

    def expired_option_contracts(self, instrument_key: str, expiry_date: str) -> dict[str, Any]:
        return self._expired.get_expired_option_contracts(instrument_key, expiry_date).to_dict()

    # ---- market data: options + instruments ----

    def option_chain(self, instrument_key: str, expiry_date: str) -> dict[str, Any]:
        return self._options.get_put_call_option_chain(instrument_key, expiry_date).to_dict()

    def option_contracts(self, instrument_key: str, expiry_date: str | None = None) -> dict[str, Any]:
        kwargs = {"expiry_date": expiry_date} if expiry_date else {}
        return self._options.get_option_contracts(instrument_key, **kwargs).to_dict()

    def search_instruments(self, query: str) -> dict[str, Any]:
        return self._instruments.search_instrument(query).to_dict()

    # ---- market information ----

    def exchange_timings(self, date: str) -> dict[str, Any]:
        return self._market_info.get_exchange_timings(date).to_dict()

    def market_holidays(self, date: str | None = None) -> dict[str, Any]:
        if date:
            return self._market_info.get_holiday(date).to_dict()
        return self._market_info.get_holidays().to_dict()

    def market_status(self, exchange: str) -> dict[str, Any]:
        return self._market_info.get_market_status(exchange).to_dict()

    # ---- streaming: feed authorisation ----

    def market_feed_authorize(self) -> dict[str, Any]:
        return self._websocket.get_market_data_feed_authorize_v3().to_dict()

    def portfolio_feed_authorize(
        self, order_update: bool = True, position_update: bool = False, holding_update: bool = False
    ) -> dict[str, Any]:
        return self._websocket.get_portfolio_stream_feed_authorize(
            self._V, order_update=order_update, position_update=position_update,
            holding_update=holding_update,
        ).to_dict()


class UpstoxAdapter(BrokerAdapter):
    """Native Upstox adapter.

    Args:
        client_factory: ``session -> UpstoxClient``-like facade (tests inject a
            mock). When omitted, ``login`` builds the live facade.
        instrument_resolver: ``(symbol, exchange) -> instrument_token`` — Upstox
            trades by instrument token (e.g. ``"NSE_EQ|INE002A01018"``).
        feed_factory: ``session -> AsyncIterator[dict]`` of DECODED v3 market-feed
            messages (live: a wrapper around the SDK's ``MarketDataStreamerV3``,
            which decodes the protobuf frames; tests inject a dict iterator).
        token_exchanger: ``form_params -> token response dict`` override for the
            OAuth code-for-token exchange (defaults to the SDK's LoginApi).
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
        instrument_resolver: Callable[[str, str], str] | None = None,
        feed_factory: Callable[[Session], AsyncIterator[dict[str, Any]]] | None = None,
        token_exchanger: Callable[[dict[str, str]], dict[str, Any]] | None = None,
        local_state_provider: Callable[[Session], LocalStateSnapshot] | None = None,
    ) -> None:
        self._client_factory = client_factory
        self._instrument_resolver = instrument_resolver
        self._feed_factory = feed_factory
        self._token_exchanger = token_exchanger
        self._local_state_provider = local_state_provider
        # instrument_key -> (symbol, exchange) for routing decoded feed ticks
        # back to FlintTrade names.
        self._feed_map: dict[str, tuple[str, str]] = {}

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

    @staticmethod
    def build_login_url(client_id: str, redirect_uri: str, state: str | None = None) -> str:
        """OAuth login-dialog URL for the operator's browser (authentication doc)."""
        return M.build_login_url(client_id, redirect_uri, state)

    async def login(self, credentials: dict) -> Session:
        access_token = str(credentials.get("access_token") or "")
        if not access_token and credentials.get("code"):
            # OAuth code flow: exchange the single-use auth code for a token
            # (POST /v2/login/authorization/token, grant_type=authorization_code).
            params = M.to_token_request_params(credentials)
            exchanger = self._token_exchanger or UpstoxClient.exchange_token
            resp = await self._call(exchanger, params)
            access_token = M.extract_access_token(resp if isinstance(resp, dict) else {})
        if not access_token:
            raise BrokerError("Upstox login requires an access_token (or an OAuth code + api_key/api_secret)")
        client = None if self._client_factory is not None else UpstoxClient(access_token)
        return Session(
            access_token=access_token,
            expires_at=datetime.now(tz=timezone.utc).timestamp() + 24 * 3600,
            account_id=str(credentials.get("client_id", "")),
            adapter_id="upstox",
            extra={"client": client},
        )

    def replay_credentials(self, credentials: dict, session: Session) -> dict:
        """The replayable vault payload after a successful login (G7).

        An OAuth ``code`` is single-use — the token endpoint rejects a replay,
        so a boot-time re-login with the stored code fails every time. Swap it
        for the exchanged ``access_token`` (valid until ~03:30 IST next day);
        keep ``api_key``/``api_secret`` so a fresh OAuth round only needs the
        operator's re-approval.
        """
        replayable = {k: v for k, v in credentials.items() if k != "code"}
        replayable["access_token"] = session.access_token
        return replayable

    async def refresh(self, session: Session) -> Session:
        # Upstox tokens are single-day (expire ~03:30 IST next day, no refresh
        # token) — a fresh login() is required at expiry.
        return session

    async def logout(self, session: Session) -> None:
        # Best-effort broker-side invalidation (GET /v2/logout), then always
        # drop the local client so logout stays idempotent.
        try:
            client = self._client(session)
        except BrokerError:
            client = None
        if client is not None and hasattr(client, "logout"):
            try:
                await self._call(client.logout)
            except Exception:  # noqa: BLE001 - local teardown must not fail on broker errors
                pass
        session.extra.pop("client", None)
        return None

    # ---------- trading: writes (router-only) ----------

    async def place_order(self, session: Session, order: Order, *, _router_token: object | None = None) -> str:
        self._require_router_token(_router_token, _ROUTER_TOKEN)
        token = self._resolve_instrument(order.symbol, order.exchange)
        tag = session.algo_id or None
        # Dispatch on order variety. Every variety travels this SAME gated method
        # (the router token is already required above and the variety + leg prices
        # are part of the SafetyContext-hashed order), so a GTT/sliced/AMO order
        # is gated identically to a regular one — no parallel order path.
        variety = str(getattr(order, "variety", "regular")).lower()
        client = self._client(session)
        if variety in ("regular", "amo", ""):
            resp = await self._call(client.place_order, M.to_place_order_params(order, token, tag=tag))
            return M.extract_order_id(resp)
        if variety == "iceberg":
            # v3 place with slice=true — Upstox slices over-freeze-quantity
            # orders into exchange-defined legs server-side.
            resp = await self._call(client.place_order_v3, M.to_place_order_v3_params(order, token, tag=tag))
            return M.extract_order_id(resp)
        if variety == "gtt":
            resp = await self._call(client.place_gtt_order, M.to_gtt_place_params(order, token))
            return M.extract_gtt_order_id(resp)
        # bracket/cover: refuse through the mapping so the message stays single-sourced.
        M.to_place_order_params(order, token, tag=tag)
        raise BrokerError(f"Upstox does not support order variety {variety!r}")  # pragma: no cover - mapping raises

    async def modify_order(
        self, session: Session, order_id: str, changes: dict, *, _router_token: object | None = None
    ) -> None:
        self._require_router_token(_router_token, _ROUTER_TOKEN)
        client = self._client(session)
        if M.is_gtt_order_id(order_id) or str(changes.get("variety", "")).lower() == "gtt":
            await self._call(client.modify_gtt_order, M.to_gtt_modify_params(str(order_id), changes))
            return
        params = M.to_modify_order_params(order_id, changes)
        await self._call(client.modify_order, params)

    async def cancel_order(
        self, session: Session, order_id: str, *, _router_token: object | None = None
    ) -> None:
        self._require_router_token(_router_token, _ROUTER_TOKEN)
        client = self._client(session)
        if M.is_gtt_order_id(order_id):
            await self._call(client.cancel_gtt_order, M.to_gtt_cancel_params(str(order_id)))
            return
        await self._call(client.cancel_order, str(order_id))

    async def place_multi_order(
        self, session: Session, orders: list[Order], *, _router_token: object | None = None
    ) -> dict:
        """Place a basket in one request (``POST /v2/order/multi/place``).

        Returns ``{order_ids, errors, total, success}`` — Upstox executes the
        batch best-effort, so per-order errors come back alongside successes.
        """
        self._require_router_token(_router_token, _ROUTER_TOKEN)
        tag = session.algo_id or None
        pairs = [(o, self._resolve_instrument(o.symbol, o.exchange)) for o in orders]
        resp = await self._call(self._client(session).place_multi_order, M.to_multi_order_params(pairs, tag=tag))
        return M.from_upstox_multi_order(resp)

    async def cancel_all_orders(
        self,
        session: Session,
        *,
        tag: str | None = None,
        segment: str | None = None,
        _router_token: object | None = None,
    ) -> dict:
        """Cancel every open/pending order, AMO included (``/v2/order/multi/cancel``).

        Optional ``tag``/``segment`` narrow the sweep. Trade-affecting, so it is
        router-gated like any other write.
        """
        self._require_router_token(_router_token, _ROUTER_TOKEN)
        resp = await self._call(self._client(session).cancel_multi_order, tag, segment)
        return M.from_upstox_cancel_exit(resp)

    async def exit_all_positions(
        self,
        session: Session,
        *,
        tag: str | None = None,
        segment: str | None = None,
        _router_token: object | None = None,
    ) -> dict:
        """Exit every open position in one sweep (``POST /v2/order/positions/exit``)."""
        self._require_router_token(_router_token, _ROUTER_TOKEN)
        resp = await self._call(self._client(session).exit_positions, tag, segment)
        return M.from_upstox_cancel_exit(resp)

    async def convert_position(
        self, session: Session, req: dict, *, _router_token: object | None = None
    ) -> dict:
        """Convert a position between products (``POST /v2/portfolio/convert-position``).

        ``req`` carries ``symbol``/``exchange`` (or a pre-resolved
        ``instrument_token``), ``old_product``/``new_product`` (FlintTrade
        names), ``transaction_type`` and ``quantity``. Margin-affecting, so it
        is router-gated.
        """
        self._require_router_token(_router_token, _ROUTER_TOKEN)
        token = str(
            req.get("instrument_token")
            or self._resolve_instrument(str(req.get("symbol", "")), str(req.get("exchange", "NSE")))
        )
        params = M.to_convert_position_params({**req, "instrument_token": token})
        resp = await self._call(self._client(session).convert_position, params)
        return resp.get("data", {}) if isinstance(resp, dict) and isinstance(resp.get("data"), dict) else {}

    # ---------- trading: reads ----------

    async def order_book(self, session: Session) -> list[Order]:
        resp = await self._call(self._client(session).order_book)
        return [M.from_upstox_order(r) for r in self._rows(resp)]  # type: ignore[misc]

    async def order_details(self, session: Session, order_id: str) -> dict:
        """Latest snapshot of one order (``GET /v2/order/details``) — a read."""
        resp = await self._call(self._client(session).order_details, str(order_id))
        data = resp.get("data", {}) if isinstance(resp, dict) else {}
        return M.from_upstox_order(data) if isinstance(data, dict) else {}

    async def order_history(
        self, session: Session, order_id: str | None = None, tag: str | None = None
    ) -> list[dict]:
        """Every state transition for an order id or tag (``GET /v2/order/history``)."""
        if not order_id and not tag:
            raise BrokerError("Upstox order_history needs an order_id or a tag")
        resp = await self._call(self._client(session).order_history, order_id, tag)
        return [M.from_upstox_order(r) for r in self._rows(resp)]

    async def gtt_orders(self, session: Session, gtt_order_id: str | None = None) -> list[dict]:
        """Active GTT orders, optionally narrowed to one id (``GET /v3/order/gtt``)."""
        resp = await self._call(self._client(session).gtt_order_details, gtt_order_id)
        return [M.from_upstox_gtt_order(r) for r in self._rows(resp)]

    async def trade_book(self, session: Session) -> list[Trade]:
        resp = await self._call(self._client(session).trade_book)
        return [M.from_upstox_trade(r) for r in self._rows(resp)]  # type: ignore[misc]

    async def trades_by_order(self, session: Session, order_id: str) -> list[dict]:
        """Fills for one specific order (``GET /v2/order/trades``) — a read."""
        resp = await self._call(self._client(session).trades_by_order, str(order_id))
        return [M.from_upstox_trade(r) for r in self._rows(resp)]

    async def trade_history(
        self,
        session: Session,
        from_date: str,
        to_date: str,
        page: int = 1,
        page_size: int = 100,
        segment: str | None = None,
    ) -> list[dict]:
        """Historical trades across segments (``GET /v2/charges/historical-trades``)."""
        resp = await self._call(
            self._client(session).trade_history, from_date, to_date, page, page_size, segment
        )
        return M.from_upstox_trade_history(resp)

    async def positions(self, session: Session) -> list[Position]:
        resp = await self._call(self._client(session).positions)
        return [M.from_upstox_position(r) for r in self._rows(resp)]  # type: ignore[misc]

    async def mtf_positions(self, session: Session) -> list[dict]:
        """Margin Trading Facility positions (``GET /v3/portfolio/mtf-positions``)."""
        resp = await self._call(self._client(session).mtf_positions)
        return [M.from_upstox_position(r) for r in self._rows(resp)]

    async def holdings(self, session: Session) -> list[dict]:
        resp = await self._call(self._client(session).holdings)
        return [M.from_upstox_holding(r) for r in self._rows(resp)]

    async def funds(self, session: Session) -> dict:
        resp = await self._call(self._client(session).funds)
        return M.from_upstox_funds(resp)

    async def profile(self, session: Session) -> dict:
        """User profile — segments/products enabled (``GET /v2/user/profile``)."""
        resp = await self._call(self._client(session).profile)
        return M.from_upstox_profile(resp)

    async def margin_calculator(self, session: Session, order: Order) -> dict:
        """Pre-trade margin estimate for ``order`` (Upstox ``/charges/margin``).

        Read-only — places nothing, so it needs no gate.
        """
        token = self._resolve_instrument(order.symbol, order.exchange)
        instrument = M.to_margin_instrument(order, token)
        resp = await self._call(self._client(session).margin, [instrument])
        return M.from_upstox_margin(resp)

    async def brokerage_calculator(self, session: Session, order: Order) -> dict:
        """Pre-trade brokerage + statutory charges (``GET /v2/charges/brokerage``)."""
        token = self._resolve_instrument(order.symbol, order.exchange)
        q = M.to_brokerage_query(order, token)
        resp = await self._call(
            self._client(session).brokerage,
            q["instrument_token"], q["quantity"], q["product"], q["transaction_type"], q["price"],
        )
        return M.from_upstox_brokerage(resp)

    async def pnl_report(
        self,
        session: Session,
        segment: str,
        financial_year: str,
        page: int = 1,
        page_size: int = 100,
    ) -> list[dict]:
        """Trade-wise realised P&L rows (``GET /v2/trade/profit-loss/data``)."""
        resp = await self._call(self._client(session).pnl_report, segment, financial_year, page, page_size)
        return M.from_upstox_pnl_rows(resp)

    async def pnl_charges(self, session: Session, segment: str, financial_year: str) -> dict:
        """Aggregate charges for the P&L report (``GET /v2/trade/profit-loss/charges``)."""
        resp = await self._call(self._client(session).pnl_charges, segment, financial_year)
        return M.from_upstox_pnl_charges(resp)

    async def kill_switch(self, session: Session, action: str) -> dict:
        """Toggle Upstox's broker-side kill switch (``PUT /v2/user/kill-switch``;
        ``ACTIVATE`` disables trading, ``DEACTIVATE`` re-enables it). An account
        control, not an order — it places nothing, so it is outside the order gate.

        SAFETY: ``DEACTIVATE`` re-opens live trading, so any caller/route wiring it
        MUST gate ``DEACTIVATE`` behind an explicit, authenticated operator action
        (Live-mode + operator confirmation) and audit it. ``ACTIVATE`` is purely
        risk-reducing and may be invoked freely.
        """
        act = str(action).upper()
        if act not in ("ACTIVATE", "DEACTIVATE"):
            raise BrokerError(f"kill_switch action must be ACTIVATE or DEACTIVATE, got {action!r}")
        resp = await self._call(self._client(session).update_kill_switch, {"action": act})
        data = resp.get("data", resp) if isinstance(resp, dict) else {}
        return data if isinstance(data, dict) else {"status": str(resp)}

    async def kill_switch_status(self, session: Session) -> dict:
        """Current kill-switch state (``GET /v2/user/kill-switch``) — a read."""
        resp = await self._call(self._client(session).kill_switch_status)
        data = resp.get("data", resp) if isinstance(resp, dict) else {}
        return data if isinstance(data, dict) else {}

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

    async def _resolve_keys(self, symbols: list[str]) -> list[str]:
        """Resolve ``"EXCHANGE:SYMBOL"`` strings to Upstox instrument keys."""
        keys: list[str] = []
        for raw in symbols:
            exchange, name = _split_symbol(raw)
            keys.append(self._resolve_instrument(name, exchange))
        return keys

    async def ohlc_quotes(self, session: Session, symbols: list[str], interval: str = "1d") -> list[dict]:
        """Bulk OHLC quotes, up to 500 instruments (``GET /v3/market-quote/ohlc``)."""
        keys = await self._resolve_keys(symbols)
        resp = await self._call(self._client(session).ohlc_quote_v3, ",".join(keys), interval)
        return M.from_upstox_ohlc_v3(resp)

    async def ltp_quotes(self, session: Session, symbols: list[str]) -> list[dict]:
        """Bulk last-traded-price quotes (``GET /v3/market-quote/ltp``)."""
        keys = await self._resolve_keys(symbols)
        resp = await self._call(self._client(session).ltp_quote_v3, ",".join(keys))
        return M.from_upstox_ltp_v3(resp)

    async def option_greeks(self, session: Session, symbols: list[str]) -> list[dict]:
        """Option Greeks + IV per contract (``GET /v3/market-quote/option-greek``)."""
        keys = await self._resolve_keys(symbols)
        resp = await self._call(self._client(session).option_greeks_v3, ",".join(keys))
        return M.from_upstox_option_greeks(resp)

    async def historical(self, session: Session, req: dict) -> Candles:
        from flinttrade_core.models import OHLCV, Candles  # noqa: PLC0415

        symbol = str(req.get("symbol", ""))
        exchange = str(req.get("exchange", "NSE"))
        interval = str(req.get("interval", req.get("timeframe", "1d")))
        instrument_key = str(req.get("instrument_key") or self._resolve_instrument(symbol, exchange))
        params = M.to_history_params({**req, "instrument_key": instrument_key})
        # Routing: an expired-instrument request uses the expired-history
        # endpoint (the key already encodes the dead contract); the v3
        # historical endpoint excludes the current trading day, so an explicit
        # intraday request routes to the intra-day endpoint (today's candles);
        # everything else uses the dated historical endpoint.
        if req.get("expired"):
            resp = await self._call(
                self._client(session).expired_history,
                params["instrument_key"], params["interval"],
                params["to_date"], params["from_date"],
            )
        elif req.get("intraday"):
            resp = await self._call(
                self._client(session).intra_day,
                params["instrument_key"], params["unit"], params["interval"],
            )
        else:
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

    async def option_contracts(
        self, session: Session, symbol: str, exchange: str = "NSE_INDEX", expiry: str | None = None
    ) -> list[dict]:
        """Option contracts for an underlying (``GET /v2/option/contract``) — a read."""
        instrument_key = self._resolve_instrument(symbol, exchange)
        resp = await self._call(self._client(session).option_contracts, instrument_key, expiry)
        return M.from_upstox_instrument_rows(resp)

    async def expiry_list(self, session: Session, symbol: str, exchange: str = "NSE_INDEX") -> list[str]:
        """Expiry dates for an underlying (``GET /v2/expired-instruments/expiries``)."""
        instrument_key = self._resolve_instrument(symbol, exchange)
        resp = await self._call(self._client(session).expiries, instrument_key)
        return M.from_upstox_expiries(resp)

    async def expired_contracts(
        self, session: Session, symbol: str, exchange: str, expiry: str, kind: str = "option"
    ) -> list[dict]:
        """Expired option/future contracts for a past expiry date — a read."""
        instrument_key = self._resolve_instrument(symbol, exchange)
        client = self._client(session)
        if str(kind).lower().startswith("fut"):
            resp = await self._call(client.expired_future_contracts, instrument_key, expiry)
        else:
            resp = await self._call(client.expired_option_contracts, instrument_key, expiry)
        return M.from_upstox_instrument_rows(resp)

    async def search_instruments(self, session: Session, query: str) -> list[dict]:
        """Instrument search (``GET /v2/instruments/search``) — a read."""
        resp = await self._call(self._client(session).search_instruments, query)
        return M.from_upstox_instrument_rows(resp)

    # ---------- market information ----------

    async def market_timings(self, session: Session, date: str) -> list[dict]:
        """Exchange open/close timings for a date (``GET /v2/market/timings/{date}``)."""
        resp = await self._call(self._client(session).exchange_timings, str(date))
        return M.from_upstox_timings(resp)

    async def market_holidays(self, session: Session, date: str | None = None) -> list[dict]:
        """Market holidays — the full year, or one date (``GET /v2/market/holidays``)."""
        resp = await self._call(self._client(session).market_holidays, date)
        return M.from_upstox_holidays(resp)

    async def market_status(self, session: Session, exchange: str) -> dict:
        """Live open/closed status per exchange (``GET /v2/market/status/{exchange}``)."""
        resp = await self._call(self._client(session).market_status, str(exchange).upper())
        return M.from_upstox_market_status(resp)

    # ---------- streaming (v3 market-data feed) ----------

    async def market_feed_authorize(self, session: Session) -> str:
        """One-time authorised wss:// URI for the v3 market feed (a read)."""
        resp = await self._call(self._client(session).market_feed_authorize)
        return M.extract_authorized_uri(resp)

    async def portfolio_feed_authorize(
        self,
        session: Session,
        *,
        order_update: bool = True,
        position_update: bool = False,
        holding_update: bool = False,
    ) -> str:
        """Authorised wss:// URI for the portfolio (order/position/holding) feed."""
        resp = await self._call(
            self._client(session).portfolio_feed_authorize,
            order_update, position_update, holding_update,
        )
        return M.extract_authorized_uri(resp)

    async def subscribe(self, session: Session, symbols: list[str], mode: str = "FULL") -> None:
        # Resolve each symbol to its instrument key and remember it so decoded
        # feed messages (keyed by instrument key) route back to the symbol.
        for raw in symbols:
            exchange, name = _split_symbol(raw)
            key = self._resolve_instrument(name, exchange)
            self._feed_map[str(key)] = (name, exchange)

    async def unsubscribe(self, session: Session, symbols: list[str]) -> None:
        for raw in symbols:
            exchange, name = _split_symbol(raw)
            try:
                key = self._resolve_instrument(name, exchange)
            except BrokerError:
                continue
            self._feed_map.pop(str(key), None)

    def stream(self, session: Session) -> AsyncIterator[Any]:
        if self._feed_factory is None:
            # Live: the v3 protobuf feed is decoded by the SDK's
            # MarketDataStreamerV3 — wire it by injecting a feed_factory that
            # yields the decoded message dicts.
            raise NotImplementedError(_PENDING.format("stream"))
        return self._stream_impl(session)

    async def _stream_impl(self, session: Session) -> AsyncIterator[Any]:
        from flinttrade_core.models import TickEvent  # noqa: PLC0415

        async for message in self._feed_factory(session):  # type: ignore[misc]
            for tick in M.from_upstox_feed_ticks(message):
                key = tick["instrument_key"]
                symbol, exchange = self._feed_map.get(key, ("", ""))
                if not symbol:
                    # Fall back to the key itself ("SEGMENT|ISIN-or-name").
                    seg, _, name = key.partition("|")
                    symbol, exchange = name or key, M.UPSTOX_TO_EXCHANGE.get(seg, seg)
                yield TickEvent(
                    symbol=symbol,
                    exchange=exchange,
                    ltp=tick.get("ltp", 0.0),
                    volume=int(tick.get("volume", 0)),
                    oi=int(tick.get("oi", 0)),
                    timestamp=str(tick.get("ltt", "")),
                )

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
