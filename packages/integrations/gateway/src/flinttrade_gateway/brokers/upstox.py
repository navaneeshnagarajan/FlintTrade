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
until then it stays dormant. The catalogue's ``connectable`` flag is the
operator-facing live-verification switch; SDK attestation alone does not expose
an unverified broker in the connect UI.
"""

from __future__ import annotations

import base64
import functools
import hashlib
import json
import logging
import math
from datetime import datetime, timezone
from typing import TYPE_CHECKING, Any, AsyncIterator, Callable

from flinttrade_core.exceptions import BrokerError
from flinttrade_engine.safety import EmergencyBrokerWrite, EmergencyReductionPlan, EmergencyWritePolicy
from flinttrade_gateway.capabilities import (
    AuthModel,
    Capabilities,
    DepthLevels,
    OrderTypes,
    Segments,
    TickProtocol,
)

from . import upstox_mapping as M
from ._base import BrokerAdapter, Session, run_blocking_sdk_call

if TYPE_CHECKING:  # pragma: no cover - typing only
    from flinttrade_core.models import Candles, OptionChain, Order, Position, Quote, Trade
    from flinttrade_gateway.reconciliation import LocalStateSnapshot, ReconciliationReport

logger = logging.getLogger("flinttrade.gateway.brokers.upstox")

_PENDING = "Upstox {0} — streaming wave pending live SDK verification"

# Upstox daily trading tokens always expire at ~03:30 IST the NEXT day (never
# more than ~28h after minting). Analytics and extended tokens — the read-only
# token classes — are valid for up to a year. Any server-minted token whose
# ``exp`` claim lies beyond this bound therefore cannot be a daily trading
# token, and is classified read-only (fail-closed).
_DAILY_TOKEN_MAX_LIFETIME_SECONDS = 36 * 3600.0
_EMERGENCY_BATCH_LIMIT = 10
_EMERGENCY_EXIT_TAG_PREFIX = "FTE-"
_EMERGENCY_SUCCESSFUL_ORDER_STATUSES = frozenset({"complete", "completed", "filled"})
_INSTRUMENT_SEARCH_RECORDS = 30
_MAX_INSTRUMENT_SEARCH_PAGES = 100

# Upstox error code for "APIs not permitted with this token" — raised when a
# read-only (analytics/extended) token hits an order endpoint (errors doc).
_TOKEN_SCOPE_REJECTION_CODES = frozenset({"UDAPI100067"})


def _credential_truthy(value: Any) -> bool:
    """Return True for common truthy credential flag spellings."""

    return str(value or "").strip().lower() in {"1", "true", "yes", "y", "on", "read_only"}


def _jwt_expiry(token: str) -> float | None:
    """Return the ``exp`` claim of a server-minted JWT access token, if decodable.

    Upstox access tokens are JWTs minted by Upstox; the payload's ``exp`` is
    server-issued metadata (NOT a client claim), so it is safe to use for
    narrowing capability. No signature verification is needed — the claim is
    only ever used to classify a session as read-only or to shorten its
    lifetime, never to widen what it may do.

    Args:
        token: The raw access token string.

    Returns:
        The ``exp`` claim as a Unix timestamp, or ``None`` when the token is
        not a decodable JWT or carries no ``exp``.
    """
    parts = token.split(".")
    if len(parts) != 3:
        return None
    try:
        payload = parts[1] + "=" * (-len(parts[1]) % 4)
        claims = json.loads(base64.urlsafe_b64decode(payload.encode("ascii")))
        exp = claims.get("exp") if isinstance(claims, dict) else None
        return float(exp) if exp is not None else None
    except Exception:  # noqa: BLE001 - an undecodable token is simply "no metadata"
        return None


def _is_write_scope_rejection(exc: BaseException) -> bool:
    """Return True when Upstox rejected a call because the token class cannot trade."""
    return str(getattr(exc, "broker_code", "") or "").upper() in _TOKEN_SCOPE_REJECTION_CODES


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
    historical_calendar_intervals=["1D", "1W", "1M"],
    option_chain_supported=True,
    option_chain_greeks_supported=True,
    streaming_supported=True,
    # Honesty: Upstox retired bracket/cover orders, so cover stays False for
    # good. GTT (v3 /order/gtt/*) and sliced orders (v3 place with slice=true,
    # our iceberg equivalent) ARE wired through the gated place/modify/cancel
    # dispatch below, so both are advertised. The capability-honesty test in
    # tests/brokers/test_upstox_mapping_base.py pins cover to False and these two to True.
    cover_order_native=False,
    basket_order_native=True,
    multi_quote_supported=True,
    multi_option_greeks_supported=True,
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
        return self._user.get_user_fund_margin_v3().to_dict()

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

    def search_instruments(
        self,
        query: str,
        *,
        page_number: int = 1,
        records: int = _INSTRUMENT_SEARCH_RECORDS,
    ) -> dict[str, Any]:
        return self._instruments.search_instrument(
            query,
            page_number=page_number,
            records=records,
        ).to_dict()

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
        self._instrument_cache: dict[tuple[str, str], str] = {}
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

    @staticmethod
    def _instrument_cache_key(symbol: str, exchange: str) -> tuple[str, str]:
        return (str(symbol).strip().upper(), str(exchange).strip().upper())

    @staticmethod
    def _search_row_matches(row: dict[str, Any], symbol: str, exchange: str) -> bool:
        expected_symbol = str(symbol).strip().upper()
        expected_exchange = str(exchange).strip().upper()
        expected_segment = M.EXCHANGE_TO_UPSTOX.get(expected_exchange, expected_exchange)
        row_symbol = str(row.get("symbol") or row.get("trading_symbol") or "").strip().upper()
        row_segment = str(row.get("segment") or "").strip().upper()
        instrument_key = str(row.get("instrument_key") or row.get("instrument_token") or "").strip()
        instrument_segment, separator, instrument_token = instrument_key.partition("|")
        instrument_segment = instrument_segment.strip().upper()
        if row_symbol != expected_symbol:
            return False
        # The token prefix is the broker's routing identity. Descriptive row
        # fields may supplement it, but may never override or contradict it.
        if instrument_segment != expected_segment or separator != "|" or not instrument_token.strip():
            return False
        return not row_segment or row_segment == expected_segment

    @staticmethod
    def _search_row_instrument_key(row: dict[str, Any]) -> str:
        return str(row.get("instrument_key") or row.get("instrument_token") or "").strip()

    @staticmethod
    def _instrument_search_page(
        resp: Any,
        *,
        expected_page: int,
    ) -> tuple[list[dict[str, Any]], int, int]:
        if not isinstance(resp, dict) or str(resp.get("status") or "").lower() != "success":
            raise BrokerError("Upstox instrument search returned an invalid response")
        meta_data = resp.get("meta_data")
        page = meta_data.get("page") if isinstance(meta_data, dict) else None
        page_number = page.get("page_number") if isinstance(page, dict) else None
        total_pages = page.get("total_pages") if isinstance(page, dict) else None
        records = page.get("records") if isinstance(page, dict) else None
        total_records = page.get("total_records") if isinstance(page, dict) else None
        if (
            isinstance(page_number, bool)
            or not isinstance(page_number, int)
            or page_number != expected_page
            or isinstance(total_pages, bool)
            or not isinstance(total_pages, int)
            or total_pages < 0
            or total_pages > _MAX_INSTRUMENT_SEARCH_PAGES
            or isinstance(records, bool)
            or not isinstance(records, int)
            or records != _INSTRUMENT_SEARCH_RECORDS
            or isinstance(total_records, bool)
            or not isinstance(total_records, int)
            or total_records < 0
            or (total_records == 0 and total_pages not in {0, 1})
            or (total_records > 0 and total_pages != math.ceil(total_records / records))
            or (total_pages > 0 and expected_page > total_pages)
        ):
            raise BrokerError("Upstox instrument search pagination is invalid")
        raw_rows = resp.get("data")
        if (
            not isinstance(raw_rows, list)
            or len(raw_rows) > _INSTRUMENT_SEARCH_RECORDS
            or any(not isinstance(row, dict) for row in raw_rows)
        ):
            raise BrokerError("Upstox instrument search rows are invalid")
        expected_rows = max(0, min(records, total_records - ((expected_page - 1) * records)))
        if len(raw_rows) != expected_rows:
            raise BrokerError("Upstox instrument search pagination is incomplete")
        rows = M.from_upstox_instrument_rows(resp)
        if len(rows) != len(raw_rows):
            raise BrokerError("Upstox instrument search rows could not be normalised exactly")
        return rows, total_pages, total_records

    async def _search_all_instruments(self, session: Session, query: str) -> list[dict[str, Any]]:
        rows: list[dict[str, Any]] = []
        declared_total_pages: int | None = None
        declared_total_records: int | None = None
        client = self._client(session)
        for page_number in range(1, _MAX_INSTRUMENT_SEARCH_PAGES + 1):
            resp = await self._call(
                client.search_instruments,
                query,
                page_number=page_number,
                records=_INSTRUMENT_SEARCH_RECORDS,
            )
            page_rows, total_pages, total_records = self._instrument_search_page(
                resp,
                expected_page=page_number,
            )
            if declared_total_pages is None:
                declared_total_pages = total_pages
                declared_total_records = total_records
            elif total_pages != declared_total_pages or total_records != declared_total_records:
                raise BrokerError("Upstox instrument search pagination changed during resolution")
            rows.extend(page_rows)
            if page_number >= total_pages:
                return rows
        raise BrokerError("Upstox instrument search exceeded its pagination bound")

    async def _resolve_instrument(self, session: Session, symbol: str, exchange: str) -> str:
        cache_key = self._instrument_cache_key(symbol, exchange)
        cached = self._instrument_cache.get(cache_key)
        if cached:
            return cached
        if self._instrument_resolver is not None:
            resolved = str(self._instrument_resolver(symbol, exchange)).strip()
            if not self._search_row_matches(
                {"symbol": symbol, "instrument_key": resolved},
                symbol,
                exchange,
            ):
                raise BrokerError(
                    f"Cannot resolve a unique Upstox instrument_token for {symbol}/{exchange}"
                )
            self._instrument_cache[cache_key] = resolved
            return resolved
        message = (
            f"Cannot resolve Upstox instrument_token for {symbol}/{exchange} — "
            "configure an instrument resolver or refresh the instruments master"
        )
        try:
            rows = await self._search_all_instruments(session, str(symbol).strip())
        except Exception as exc:  # noqa: BLE001 - surface a single resolver-family error
            raise BrokerError(message) from exc
        matches = [
            self._search_row_instrument_key(row)
            for row in rows
            if self._search_row_matches(row, symbol, exchange)
            and self._search_row_instrument_key(row)
        ]
        if len(matches) != 1:
            raise BrokerError(
                f"Cannot resolve a unique Upstox instrument_token for {symbol}/{exchange}"
            )
        instrument_key = matches[0]
        self._instrument_cache[cache_key] = instrument_key
        return instrument_key

    @staticmethod
    async def _call(fn: Callable[..., Any], *args: Any, **kwargs: Any) -> Any:
        return await run_blocking_sdk_call(fn, *args, **kwargs)

    @staticmethod
    def _rows(resp: Any) -> list[dict[str, Any]]:
        data = resp.get("data", []) if isinstance(resp, dict) else []
        return data if isinstance(data, list) else []

    @staticmethod
    def _emergency_rows(resp: Any, *, book: str) -> list[dict[str, Any]]:
        """Decode a broker snapshot without treating unknown state as empty."""
        if (
            not isinstance(resp, dict)
            or str(resp.get("status") or "").strip().lower() != "success"
            or not isinstance(resp.get("data"), list)
            or any(not isinstance(row, dict) for row in resp["data"])
        ):
            raise BrokerError(f"Upstox emergency {book} response is malformed")
        return resp["data"]

    @staticmethod
    def _emergency_gtt_order_ids(rows: list[dict[str, Any]]) -> frozenset[str]:
        """Return the canonical IDs from Upstox's active-only GTT book."""
        order_ids: set[str] = set()
        for row in rows:
            try:
                order_id = M.canonical_order_id(row.get("gtt_order_id"))
            except M.UpstoxMappingError as exc:
                raise BrokerError("Upstox emergency GTT order id is malformed") from exc
            if not M.is_gtt_order_id(order_id):
                raise BrokerError("Upstox emergency GTT order id is malformed")
            if order_id in order_ids:
                raise BrokerError("Upstox emergency GTT order book contains a duplicate id")
            order_ids.add(order_id)
        return frozenset(order_ids)

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
        expires_at = datetime.now(tz=timezone.utc).timestamp() + 24 * 3600
        read_only = _credential_truthy(credentials.get("read_only")) or str(credentials.get("token_scope") or "").lower() in {
            "analytics",
            "read_only",
            "readonly",
        }
        return Session(
            access_token=access_token,
            expires_at=expires_at,
            account_id=str(credentials.get("client_id", "")),
            adapter_id="upstox",
            extra={"client": client, "token_scope": str(credentials.get("token_scope") or "")},
            read_only_until_at=expires_at if read_only else None,
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
        token = await self._resolve_instrument(session, order.symbol, order.exchange)
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

    async def modify_forever(
        self, session: Session, order_id: str, changes: dict, *, _router_token: object | None = None
    ) -> None:
        """Fully replace one Upstox GTT order through the routed write contract."""
        self._require_router_token(_router_token, _ROUTER_TOKEN)
        await self._call(
            self._client(session).modify_gtt_order,
            M.to_gtt_modify_params(str(order_id), changes),
        )

    async def cancel_forever(
        self, session: Session, order_id: str, *, _router_token: object | None = None
    ) -> None:
        """Cancel one Upstox GTT order through the routed write contract."""
        self._require_router_token(_router_token, _ROUTER_TOKEN)
        await self._call(
            self._client(session).cancel_gtt_order,
            M.to_gtt_cancel_params(str(order_id)),
        )

    async def place_multi_order(
        self, session: Session, orders: list[Order], *, _router_token: object | None = None
    ) -> dict:
        """Place a basket in one request (``POST /v2/order/multi/place``).

        Returns ``{order_ids, errors, total, success}`` — Upstox executes the
        batch best-effort, so per-order errors come back alongside successes.
        """
        self._require_router_token(_router_token, _ROUTER_TOKEN)
        tag = session.algo_id or None
        pairs = [(o, await self._resolve_instrument(session, o.symbol, o.exchange)) for o in orders]
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

    @staticmethod
    def _emergency_position_accounting(position: dict[str, Any]) -> tuple[int, int, int, int, bool]:
        try:
            signed_quantity = int(str(position["quantity"]))
            overnight_quantity = int(str(position.get("overnight_quantity") or "0"))
            day_buy_quantity = int(str(position.get("day_buy_quantity") or "0"))
            day_sell_quantity = int(str(position.get("day_sell_quantity") or "0"))
        except (KeyError, TypeError, ValueError, OverflowError) as exc:
            raise BrokerError("Upstox emergency position accounting is invalid") from exc
        if day_buy_quantity < 0 or day_sell_quantity < 0:
            raise BrokerError("Upstox emergency position accounting cannot be negative")
        complete = bool(position.get("_emergency_accounting_complete", False))
        if complete and signed_quantity != overnight_quantity + day_buy_quantity - day_sell_quantity:
            raise BrokerError("Upstox emergency position accounting is inconsistent")
        return signed_quantity, overnight_quantity, day_buy_quantity, day_sell_quantity, complete

    @classmethod
    def _emergency_exit_tag(cls, position: dict[str, Any]) -> str:
        signed_quantity, overnight_quantity, day_buy_quantity, day_sell_quantity, complete = (
            cls._emergency_position_accounting(position)
        )
        if signed_quantity == 0:
            raise BrokerError("Upstox emergency position is flat")
        opposite_action = "SELL" if signed_quantity > 0 else "BUY"
        identity = "|".join(
            (
                str(position.get("symbol") or "").strip(),
                str(position.get("exchange") or "").strip().upper(),
                str(position.get("product") or "").strip().upper(),
                opposite_action,
                str(abs(signed_quantity)),
                str(overnight_quantity),
                str(day_buy_quantity),
                str(day_sell_quantity),
                "complete" if complete else "incomplete",
            )
        )
        return f"{_EMERGENCY_EXIT_TAG_PREFIX}{hashlib.sha256(identity.encode('utf-8')).hexdigest()[:16]}"

    @staticmethod
    def _exit_order_matches_position_identity(order: dict[str, Any], position: dict[str, Any]) -> bool:
        """Whether an order names the same symbol, exchange, and product."""
        try:
            signed_quantity = int(str(position["quantity"]))
        except (KeyError, TypeError, ValueError, OverflowError):
            return False
        if signed_quantity == 0:
            return False
        position_symbol = str(position.get("symbol") or "").strip()
        position_exchange = str(position.get("exchange") or "").strip().upper()
        position_product = str(position.get("product") or "").strip().upper()
        order_symbol = str(order.get("symbol") or "").strip()
        order_exchange = str(order.get("exchange") or "").strip().upper()
        order_product = str(order.get("product") or "").strip().upper()
        if not all(
            (
                position_symbol,
                position_exchange,
                position_product,
                order_symbol,
                order_exchange,
                order_product,
            )
        ):
            return False
        return (
            position_symbol,
            position_exchange,
            position_product,
        ) == (
            order_symbol,
            order_exchange,
            order_product,
        )

    @classmethod
    def _exit_order_targets_position(cls, order: dict[str, Any], position: dict[str, Any]) -> bool:
        """Whether an order has the exact identity and currently reducing side."""
        if not cls._exit_order_matches_position_identity(order, position):
            return False
        try:
            signed_quantity = int(str(position["quantity"]))
        except (KeyError, TypeError, ValueError, OverflowError):
            return False
        expected_action = "SELL" if signed_quantity > 0 else "BUY"
        return str(order.get("action") or "").strip().upper() == expected_action

    @classmethod
    def _completed_exit_matches_position(cls, order: dict[str, Any], position: dict[str, Any]) -> bool:
        """Whether a completed FTE belongs to this exact exposure episode."""
        if not cls._exit_order_targets_position(order, position):
            return False
        try:
            signed_quantity = int(str(position["quantity"]))
            requested_quantity = int(str(order.get("quantity") or "0"))
            filled_quantity = int(str(order.get("filled_quantity") or "0"))
        except (KeyError, TypeError, ValueError, OverflowError):
            return False
        return (
            requested_quantity == abs(signed_quantity)
            and requested_quantity > 0
            and str(order.get("tag") or "") == cls._emergency_exit_tag(position)
            and str(order.get("status") or "").strip().lower() in _EMERGENCY_SUCCESSFUL_ORDER_STATUSES
            and filled_quantity == requested_quantity
        )

    @classmethod
    def _active_exit_order_state(
        cls,
        order: dict[str, Any],
        position: dict[str, Any],
        *,
        trusted_order_id: bool = False,
    ) -> str:
        """Classify one active emergency exit as exact, conflicting, unsettled, or unrelated."""
        tag = str(order.get("tag") or "")
        tagged = tag.startswith(_EMERGENCY_EXIT_TAG_PREFIX)
        if not (tagged or trusted_order_id) or not cls._exit_order_matches_position_identity(order, position):
            return "unrelated"
        if not cls._exit_order_targets_position(order, position):
            return "conflicting"
        try:
            requested_quantity = int(str(order.get("quantity") or "0"))
            filled_quantity = int(str(order.get("filled_quantity") or "0"))
            pending_quantity = int(str(order.get("pending_quantity") or "0"))
        except (TypeError, ValueError, OverflowError):
            return "unsettled"
        if (
            requested_quantity <= 0
            or filled_quantity < 0
            or pending_quantity < 0
            or filled_quantity + pending_quantity != requested_quantity
            or pending_quantity == 0
        ):
            return "unsettled"

        signed_quantity, overnight_quantity, day_buy_quantity, day_sell_quantity, complete = (
            cls._emergency_position_accounting(position)
        )
        original = dict(position)
        if filled_quantity:
            if not complete:
                return "unsettled"
            if signed_quantity > 0:
                original["quantity"] = str(signed_quantity + filled_quantity)
                original["day_sell_quantity"] = str(day_sell_quantity - filled_quantity)
                if day_sell_quantity < filled_quantity:
                    return "unsettled"
            else:
                original["quantity"] = str(signed_quantity - filled_quantity)
                original["day_buy_quantity"] = str(day_buy_quantity - filled_quantity)
                if day_buy_quantity < filled_quantity:
                    return "unsettled"
        try:
            original_quantity = abs(int(str(original["quantity"])))
        except (KeyError, TypeError, ValueError, OverflowError):
            return "unsettled"
        if requested_quantity != original_quantity:
            return "conflicting"
        if tagged and tag != cls._emergency_exit_tag(original):
            return "conflicting"
        return "exact" if pending_quantity == abs(signed_quantity) else "conflicting"

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
        """Plan at most ten exact writes from one joint order/position snapshot."""
        requested = frozenset(policy.verbs)
        client = self._client(session)
        order_response = await self._call(client.order_book)
        order_rows = [
            M.from_upstox_order(row)
            for row in self._emergency_rows(order_response, book="order book")
        ]
        gtt_order_ids = frozenset()
        if "cancel_all_orders" in requested:
            gtt_response = await self._call(client.gtt_order_details, None)
            gtt_rows = [
                M.from_upstox_gtt_order(row)
                for row in self._emergency_rows(gtt_response, book="GTT order book")
            ]
            gtt_order_ids = self._emergency_gtt_order_ids(gtt_rows)
        regular_order_ids = M.emergency_order_ids(order_rows)
        if regular_order_ids & gtt_order_ids:
            raise BrokerError("Upstox emergency order and GTT books contain overlapping ids")
        known_order_ids = regular_order_ids | gtt_order_ids
        observed_exit_tags = {
            str(row.get("tag") or "")
            for row in order_rows
            if isinstance(row, dict) and str(row.get("tag") or "").startswith(_EMERGENCY_EXIT_TAG_PREFIX)
        }
        completed_rows = tuple(
            row
            for row in order_rows
            if isinstance(row, dict)
            and str(row.get("status") or "").strip().lower() in _EMERGENCY_SUCCESSFUL_ORDER_STATUSES
        )
        orders = M.active_emergency_orders(order_rows)
        position_response = await self._call(client.positions)
        try:
            position_rows = [
                M.from_upstox_position(row)
                for row in self._emergency_rows(position_response, book="position book")
            ]
        except M.UpstoxMappingError as exc:
            raise BrokerError(str(exc)) from exc
        positions = M.active_emergency_positions(position_rows)

        def position_key(position: dict[str, Any]) -> tuple[str, str, str]:
            return position["symbol"], position["exchange"], position["product"]

        current_position_tags = {self._emergency_exit_tag(position) for position in positions}
        completed_current_position_exit_tags: set[str] = set()
        ambiguous_completed_position_keys: set[tuple[str, str, str]] = set()
        for position in positions:
            candidate_rows = tuple(
                order
                for order in completed_rows
                if (
                    str(order.get("tag") or "").startswith(_EMERGENCY_EXIT_TAG_PREFIX)
                    or str(order.get("orderid") or "") in protected_exit_order_ids
                )
                and self._exit_order_matches_position_identity(order, position)
            )
            matching_rows = tuple(
                order for order in candidate_rows if self._completed_exit_matches_position(order, position)
            )
            protected_untagged_rows = tuple(
                order
                for order in candidate_rows
                if str(order.get("orderid") or "") in protected_exit_order_ids
                and not str(order.get("tag") or "").startswith(_EMERGENCY_EXIT_TAG_PREFIX)
            )
            accounting_complete = bool(position.get("_emergency_accounting_complete", False))
            if protected_untagged_rows:
                ambiguous_completed_position_keys.add(position_key(position))
            elif matching_rows and (
                accounting_complete
                or any(str(order.get("tag") or "") in protected_exit_tags for order in matching_rows)
            ):
                completed_current_position_exit_tags.add(self._emergency_exit_tag(position))
            elif candidate_rows and not accounting_complete:
                ambiguous_completed_position_keys.add(position_key(position))

        active_exit_orders: dict[str, dict[str, Any]] = {}
        grouped_active_exits: dict[
            tuple[str, str, str],
            list[tuple[dict[str, Any], str]],
        ] = {}
        active_current_position_exit_tags: set[str] = set()
        exact_active_position_keys: set[tuple[str, str, str]] = set()
        unsettled_active_position_keys: set[tuple[str, str, str]] = set()
        conflicting_active_orders: dict[str, dict[str, Any]] = {}
        for order in orders:
            order_id = order["orderid"]
            tagged = str(order.get("tag") or "").startswith(_EMERGENCY_EXIT_TAG_PREFIX)
            trusted_order_id = order_id in protected_exit_order_ids
            if not (tagged or trusted_order_id):
                continue
            active_exit_orders[order_id] = order
            matched_position = False
            for position in positions:
                state = self._active_exit_order_state(
                    order,
                    position,
                    trusted_order_id=trusted_order_id,
                )
                if state == "unrelated":
                    continue
                grouped_active_exits.setdefault(position_key(position), []).append((order, state))
                matched_position = True
                break
            if not matched_position:
                conflicting_active_orders[order_id] = order

        for key, entries in grouped_active_exits.items():
            if len(entries) > 1:
                conflicting_active_orders.update((order["orderid"], order) for order, _state in entries)
                continue
            order, state = entries[0]
            if state == "exact":
                exact_active_position_keys.add(key)
                tag = str(order.get("tag") or "")
                if tag.startswith(_EMERGENCY_EXIT_TAG_PREFIX):
                    active_current_position_exit_tags.add(tag)
            elif state == "unsettled":
                unsettled_active_position_keys.add(key)
            else:
                conflicting_active_orders[order["orderid"]] = order

        blocked_position_keys = ambiguous_completed_position_keys | unsettled_active_position_keys
        blocked_position_keys.update(
            position_key(position)
            for position in positions
            if self._emergency_exit_tag(position)
            in completed_current_position_exit_tags | active_current_position_exit_tags
        )
        blocked_position_keys.update(exact_active_position_keys)
        blocked_position_keys.update(
            position_key(position)
            for position in positions
            if any(
                self._exit_order_matches_position_identity(order, position)
                for order in conflicting_active_orders.values()
            )
        )
        positions_requiring_exit = tuple(
            position for position in positions if position_key(position) not in blocked_position_keys
        )
        protected = tuple(
            order
            for order in orders
            if (
                order["orderid"] in protected_order_ids
                or order["orderid"] in protected_exit_order_ids
                or order["orderid"] in active_exit_orders
            )
        )
        protected_ids = {order["orderid"] for order in protected}
        protected_non_exit = tuple(
            order for order in protected if order["orderid"] not in active_exit_orders
        )
        protected_gtt_ids = gtt_order_ids & (protected_order_ids | protected_exit_order_ids)
        cancellable_gtt_ids = tuple(sorted(gtt_order_ids - protected_gtt_ids))
        missing_protected_exit_ids = protected_exit_order_ids - known_order_ids
        protected_current_position_tags = protected_exit_tags & current_position_tags
        exact_protected_exit_tags = protected_current_position_tags & (
            completed_current_position_exit_tags | active_current_position_exit_tags
        )
        conflicting_protected_exit_tags = (
            protected_current_position_tags & observed_exit_tags
        ) - exact_protected_exit_tags
        missing_protected_exit_tags = (
            protected_current_position_tags
            - exact_protected_exit_tags
            - conflicting_protected_exit_tags
        )
        cancellable = tuple(order for order in orders if order["orderid"] not in protected_ids)
        pending: set[str] = set()
        if "cancel_all_orders" in requested and (cancellable or protected_non_exit or gtt_order_ids):
            pending.add("cancel_all_orders")
        if "exit_all_positions" in requested and (
            positions or missing_protected_exit_ids or active_exit_orders
        ):
            pending.add("exit_all_positions")
        if not pending:
            return EmergencyReductionPlan(writes=(), pending_verbs=frozenset())

        if unidentified_exit_inflight or missing_protected_exit_ids or missing_protected_exit_tags:
            return EmergencyReductionPlan(writes=(), pending_verbs=frozenset(pending))

        if "cancel_all_orders" in pending:
            if not protected and not gtt_order_ids and len(cancellable) <= _EMERGENCY_BATCH_LIMIT:
                writes = (
                    EmergencyBrokerWrite(
                        parent_verb="cancel_all_orders",
                        verb="cancel_all_orders",
                        payload={
                            "_op": "cancel_all_orders",
                            "_emergency_target_order_ids": sorted(
                                str(order["orderid"]) for order in cancellable
                            ),
                        },
                    ),
                )
            else:
                cancellable_ids = tuple(str(order["orderid"]) for order in cancellable) + cancellable_gtt_ids
                overflow = max(1, len(cancellable_ids) - _EMERGENCY_BATCH_LIMIT)
                writes = tuple(
                    EmergencyBrokerWrite(
                        parent_verb="cancel_all_orders",
                        verb="cancel_order",
                        payload={"_op": "cancel_order", "order_id": order_id},
                    )
                    for order_id in cancellable_ids[: min(_EMERGENCY_BATCH_LIMIT, overflow)]
                )
            return EmergencyReductionPlan(writes=writes, pending_verbs=frozenset(pending))

        if "exit_all_positions" in pending:
            if (
                protected_non_exit
                or missing_protected_exit_ids
                or missing_protected_exit_tags
            ):
                return EmergencyReductionPlan(writes=(), pending_verbs=frozenset(pending))
            if conflicting_active_orders:
                conflicting_cancellable_ids = tuple(
                    order_id
                    for order_id in conflicting_active_orders
                    if order_id not in protected_order_ids
                )
                return EmergencyReductionPlan(
                    writes=tuple(
                        EmergencyBrokerWrite(
                            parent_verb="exit_all_positions",
                            verb="cancel_order",
                            payload={"_op": "cancel_order", "order_id": order_id},
                        )
                        for order_id in conflicting_cancellable_ids[:_EMERGENCY_BATCH_LIMIT]
                    ),
                    pending_verbs=frozenset(pending),
                )
            if not positions_requiring_exit:
                return EmergencyReductionPlan(writes=(), pending_verbs=frozenset(pending))
            exact_positions = positions_requiring_exit[:_EMERGENCY_BATCH_LIMIT]
            return EmergencyReductionPlan(
                writes=tuple(
                    EmergencyBrokerWrite(
                        parent_verb="exit_all_positions",
                        verb="place_reducing_order",
                        payload=M.to_emergency_reducing_payload(
                            position,
                            tag=self._emergency_exit_tag(position),
                        ),
                    )
                    for position in exact_positions
                ),
                pending_verbs=frozenset(pending),
            )

        return EmergencyReductionPlan(writes=(), pending_verbs=frozenset(pending))

    async def place_reducing_order(
        self,
        session: Session,
        payload: dict[str, Any],
        *,
        _router_token: object | None = None,
    ) -> str | dict[str, Any]:
        """Place one opposite-side order after a final signed-position check."""
        self._require_router_token(_router_token, _ROUTER_TOKEN)
        symbol = str(payload.get("symbol") or "")
        exchange = str(payload.get("exchange") or "").upper()
        product = str(payload.get("product") or "").upper()
        try:
            expected_quantity = int(str(payload.get("expected_position_quantity") or "0"))
            reducing_quantity = int(str(payload.get("quantity") or "0"))
        except (TypeError, ValueError, OverflowError) as exc:
            raise BrokerError("Upstox reducing position quantity is invalid") from exc
        if not symbol or not exchange or not product or expected_quantity == 0 or reducing_quantity <= 0:
            raise BrokerError("Upstox reducing position fingerprint is incomplete")

        current_positions = M.active_emergency_positions(await self.positions(session))
        current = next(
            (
                position
                for position in current_positions
                if (
                    position["symbol"],
                    position["exchange"],
                    position["product"],
                )
                == (symbol, exchange, product)
            ),
            None,
        )
        if current is None:
            return {"order_ids": [], "errors": [], "total": 0, "success": 0}
        current_quantity = int(str(current["quantity"]))
        expected_action = "SELL" if expected_quantity > 0 else "BUY"
        if (
            current_quantity * expected_quantity <= 0
            or abs(current_quantity) < reducing_quantity
            or reducing_quantity != abs(expected_quantity)
            or str(payload.get("action") or "").upper() != expected_action
        ):
            raise BrokerError("Upstox position changed before the reducing write")
        tag = str(payload.get("emergency_tag") or "")
        if not tag.startswith(_EMERGENCY_EXIT_TAG_PREFIX) or tag != self._emergency_exit_tag(current):
            raise BrokerError("Upstox reducing position episode changed before dispatch")

        from flinttrade_core.models import Order  # noqa: PLC0415

        order = Order(
            symbol=symbol,
            action=expected_action,
            exchange=exchange,
            pricetype="MARKET",
            product=product,
            quantity=str(reducing_quantity),
            price="0",
            trigger_price="0",
            variety="regular",
            strategy="Emergency",
        )
        instrument_token = await self._resolve_instrument(session, symbol, exchange)
        response = await self._call(
            self._client(session).place_order,
            M.to_place_order_params(order, instrument_token, tag=tag),
        )
        return M.extract_order_id(response)

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
            or await self._resolve_instrument(session, str(req.get("symbol", "")), str(req.get("exchange", "NSE")))
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

    async def forever_orders(self, session: Session) -> list[dict]:
        """List active Upstox GTT orders through the canonical forever-order verb."""
        return await self.gtt_orders(session)

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
        token = await self._resolve_instrument(session, order.symbol, order.exchange)
        instrument = M.to_margin_instrument(order, token)
        resp = await self._call(self._client(session).margin, [instrument])
        return M.from_upstox_margin(resp)

    async def brokerage_calculator(self, session: Session, order: Order) -> dict:
        """Pre-trade brokerage + statutory charges (``GET /v2/charges/brokerage``)."""
        token = await self._resolve_instrument(session, order.symbol, order.exchange)
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
            keys.append(await self._resolve_instrument(session, name, exchange))
        resp = await self._call(self._client(session).full_quote, ",".join(keys))
        data = resp.get("data", {}) if isinstance(resp, dict) else {}
        records = data.values() if isinstance(data, dict) else []
        return [Quote(**M.from_upstox_quote(rec)) for rec in records if isinstance(rec, dict)]

    async def market_depth(self, session: Session, symbols: list[str]) -> list[dict[str, Any]]:
        """Five-level market depth from Upstox full-quote records.

        Upstox's full-quote endpoint returns the L1 quote and the 5-level
        ``depth.buy`` / ``depth.sell`` ladders together. Expose that ladder as a
        first-class read so native-only Depth/DOM widgets do not require the
        OpenAlgo bridge for market depth.
        """
        keys = await self._resolve_keys(session, symbols)
        resp = await self._call(self._client(session).full_quote, ",".join(keys))
        data = resp.get("data", {}) if isinstance(resp, dict) else {}
        out: list[dict[str, Any]] = []
        if not isinstance(data, dict):
            return out
        records = [rec for rec in data.values() if isinstance(rec, dict)]
        for idx, key in enumerate(keys):
            rec = data.get(key)
            if not isinstance(rec, dict):
                rec = next((r for r in records if str(r.get("instrument_token") or "") == key), None)
            if not isinstance(rec, dict) and len(keys) == len(records):
                rec = records[idx]
            if isinstance(rec, dict):
                out.append(M.from_upstox_depth(rec))
        return out

    async def _resolve_keys(self, session: Session, symbols: list[str]) -> list[str]:
        """Resolve ``"EXCHANGE:SYMBOL"`` strings to Upstox instrument keys."""
        keys: list[str] = []
        for raw in symbols:
            exchange, name = _split_symbol(raw)
            keys.append(await self._resolve_instrument(session, name, exchange))
        return keys

    @staticmethod
    def _exact_option_greeks(resp: Any, keys: list[str]) -> dict[str, dict[str, Any]]:
        """Return one complete broker row for every requested instrument key."""
        if any(not key for key in keys) or len(keys) != len(set(keys)):
            raise BrokerError("Upstox option-Greek request lacks unique instrument tokens")
        by_key: dict[str, dict[str, Any]] = {}
        try:
            rows = M.from_upstox_option_greeks(resp)
        except (M.UpstoxMappingError, TypeError, ValueError, OverflowError) as exc:
            raise BrokerError("Upstox option-Greek response is invalid") from exc
        for row in rows:
            key = str(row.get("instrument_token") or "").strip()
            if not key or key in by_key:
                raise BrokerError("Upstox option-Greek response has an invalid instrument token")
            by_key[key] = row
        if set(by_key) != set(keys):
            raise BrokerError("Upstox option-Greek response is incomplete")
        return by_key

    async def ohlc_quotes(self, session: Session, symbols: list[str], interval: str = "1d") -> list[dict]:
        """Bulk OHLC quotes, up to 500 instruments (``GET /v3/market-quote/ohlc``)."""
        keys = await self._resolve_keys(session, symbols)
        resp = await self._call(self._client(session).ohlc_quote_v3, ",".join(keys), interval)
        return M.from_upstox_ohlc_v3(resp)

    async def ltp_quotes(self, session: Session, symbols: list[str]) -> list[dict]:
        """Bulk last-traded-price quotes (``GET /v3/market-quote/ltp``)."""
        keys = await self._resolve_keys(session, symbols)
        resp = await self._call(self._client(session).ltp_quote_v3, ",".join(keys))
        return M.from_upstox_ltp_v3(resp)

    async def option_greeks(self, session: Session, symbols: list[str]) -> list[dict]:
        """Option Greeks + IV per contract (``GET /v3/market-quote/option-greek``)."""
        identities: list[tuple[str, str, str]] = []
        for raw in symbols:
            exchange, symbol = _split_symbol(raw)
            key = await self._resolve_instrument(session, symbol, exchange)
            identities.append((symbol, exchange, key))
        keys = [identity[2] for identity in identities]
        resp = await self._call(self._client(session).option_greeks_v3, ",".join(keys))
        by_key = self._exact_option_greeks(resp, keys)
        results: list[dict[str, Any]] = []
        for symbol, exchange, key in identities:
            row = by_key[key]
            values = [float(row[field]) for field in ("delta", "gamma", "theta", "vega", "iv")]
            if not row.get("greeks_complete") or not all(math.isfinite(value) for value in values):
                raise BrokerError("Upstox option-Greek response lacks complete Greek values")
            results.append({
                "symbol": symbol,
                "instrument_id": key,
                "exchange": exchange,
                "ltp": float(row["ltp"]),
                "iv": values[4],
                "delta": values[0],
                "gamma": values[1],
                "theta": values[2],
                "vega": values[3],
                "oi": int(row["oi"]),
            })
        return results

    async def portfolio_greeks(
        self,
        session: Session,
        positions: list[dict[str, Any]],
    ) -> list[dict[str, Any]]:
        """Read complete Delta/Vega rows by the exact portfolio instrument tokens."""
        keys: list[str] = []
        for position in positions:
            supplied_key = str(position.get("instrument_id") or "").strip()
            symbol = str(position.get("symbol") or "").strip()
            exchange = str(position.get("exchange") or "").strip().upper()
            if not symbol or not exchange:
                raise BrokerError("Upstox option position lacks a canonical symbol or exchange")
            resolved_key = str(await self._resolve_instrument(session, symbol, exchange)).strip()
            if not resolved_key:
                raise BrokerError("Upstox option position lacks an authoritative instrument token")
            if supplied_key and supplied_key != resolved_key:
                raise BrokerError("Upstox option position conflicts with its authoritative instrument token")
            keys.append(resolved_key)
        resp = await self._call(self._client(session).option_greeks_v3, ",".join(keys))
        by_key = self._exact_option_greeks(resp, keys)

        results: list[dict[str, Any]] = []
        for position, key in zip(positions, keys, strict=True):
            row = by_key[key]
            delta = float(row["delta"])
            vega = float(row["vega"])
            if not row.get("greeks_complete") or not math.isfinite(delta) or not math.isfinite(vega):
                raise BrokerError("Upstox option-Greek response lacks complete Delta/Vega values")
            results.append({
                "symbol": str(position.get("symbol") or ""),
                "instrument_id": key,
                "exchange": str(position.get("exchange") or "").upper(),
                "delta": delta,
                "vega": vega,
            })
        return results

    async def historical(self, session: Session, req: dict) -> Candles:
        from flinttrade_core.models import OHLCV, Candles  # noqa: PLC0415

        symbol = str(req.get("symbol", ""))
        exchange = str(req.get("exchange", "NSE"))
        interval = str(req.get("interval", req.get("timeframe", "1d")))
        instrument_key = str(req.get("instrument_key") or await self._resolve_instrument(session, symbol, exchange))
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
        instrument_key = await self._resolve_instrument(session, underlying, exchange)
        supplied_instrument_key = req.get("instrument_key")
        if supplied_instrument_key is not None and (
            not isinstance(supplied_instrument_key, str)
            or supplied_instrument_key.strip() != instrument_key
        ):
            raise BrokerError("Upstox option-chain instrument_key does not match the requested underlying")
        resp = await self._call(self._client(session).option_chain, instrument_key, expiry)
        oc = M.to_option_chain_dict(
            underlying,
            exchange,
            resp,
            requested_expiry=expiry,
            requested_instrument_key=instrument_key,
        )
        return OptionChain(
            underlying=oc["underlying"],
            underlying_key=oc["underlying_key"],
            exchange=oc["exchange"],
            expiry=oc["expiry"],
            spot_price=oc["spot_price"],
            strikes=[OptionChainStrike(**s) for s in oc["strikes"]],
        )

    async def option_contracts(
        self, session: Session, symbol: str, exchange: str = "NSE_INDEX", expiry: str | None = None
    ) -> list[dict]:
        """Option contracts for an underlying (``GET /v2/option/contract``) — a read."""
        instrument_key = await self._resolve_instrument(session, symbol, exchange)
        resp = await self._call(self._client(session).option_contracts, instrument_key, expiry)
        return M.from_upstox_instrument_rows(resp)

    async def expiry_list(self, session: Session, symbol: str, exchange: str = "NSE_INDEX") -> list[str]:
        """Expiry dates for an underlying (``GET /v2/expired-instruments/expiries``)."""
        instrument_key = await self._resolve_instrument(session, symbol, exchange)
        resp = await self._call(self._client(session).expiries, instrument_key)
        return M.from_upstox_expiries(resp)

    async def expired_contracts(
        self, session: Session, symbol: str, exchange: str, expiry: str, kind: str = "option"
    ) -> list[dict]:
        """Expired option/future contracts for a past expiry date — a read."""
        instrument_key = await self._resolve_instrument(session, symbol, exchange)
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
            key = await self._resolve_instrument(session, name, exchange)
            self._feed_map[str(key)] = (name, exchange)

    async def unsubscribe(self, session: Session, symbols: list[str]) -> None:
        for raw in symbols:
            exchange, name = _split_symbol(raw)
            try:
                key = await self._resolve_instrument(session, name, exchange)
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
        snapshot (the engine wires a durable selector-scoped provider). A
        broker fetch failure is captured on the report's
        ``error`` field instead of raised, so the runner retries next cycle.
        """
        from flinttrade_gateway.reconciliation import (  # noqa: PLC0415
            EMPTY_LOCAL_STATE,
            build_report,
            declare_unavailable_order_fields,
        )

        generated_at = datetime.now(tz=timezone.utc)
        local = EMPTY_LOCAL_STATE if self._local_state_provider is None else self._local_state_provider(session)
        try:
            broker_orders = declare_unavailable_order_fields(
                await self.order_book(session),
                fields=("variety", "validity", "strategy"),
            )
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
