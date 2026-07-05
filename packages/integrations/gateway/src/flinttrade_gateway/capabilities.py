"""Broker capability registry for FlintTrade.

Provides a structured record of what each Indian broker supports so that
the UI, order router, and screener can make runtime decisions without
hardcoding broker-specific conditionals throughout the codebase.

Usage::

    from capabilities import CapabilityRegistry, REGISTRY

    caps = REGISTRY.get("zerodha")
    if caps and caps.supports_bracket_orders:
        ...

    for caps in REGISTRY.all():
        print(caps.broker_name, caps.supports_websocket)
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum, IntEnum, IntFlag, auto
from typing import ClassVar


@dataclass
class BrokerCapabilities:
    """Declares what a single broker supports.

    All boolean fields default to ``False`` so that adding a new capability
    field does not silently break existing broker entries — they simply
    advertise ``False`` until explicitly set.

    Args:
        broker_name: Canonical lower-case broker identifier.
        supports_market_orders: Broker accepts MARKET order type.
        supports_limit_orders: Broker accepts LIMIT order type.
        supports_sl_orders: Broker accepts SL (stop-loss limit) order type.
        supports_sl_m_orders: Broker accepts SL-M (stop-loss market) order type.
        supports_bracket_orders: Broker accepts BO (bracket order) type.
        supports_cover_orders: Broker accepts CO (cover order) type.
        supports_basket_orders: Broker accepts multi-leg basket orders.
        supports_options: Broker supports options (NFO/BFO) trading.
        supports_futures: Broker supports futures (NFO/BFO/MCX) trading.
        supports_commodities: Broker supports MCX commodity trading.
        supports_currency: Broker supports CDS currency derivatives.
        supports_equity: Broker supports equity (NSE/BSE) trading.
        supports_mis: Broker supports MIS (intraday) product type.
        supports_cnc: Broker supports CNC (delivery) product type.
        supports_nrml: Broker supports NRML (carry-forward) product type.
        supports_websocket: Broker provides a real-time WebSocket feed.
        supports_multi_quote: Broker returns multiple symbol quotes in one call.
        supports_multi_option_greeks: Broker provides batch option greeks.
        order_rate_limit_per_sec: Maximum order requests per second.
        quote_rate_limit_per_sec: Maximum quote requests per second.
    """

    broker_name: str
    supports_market_orders: bool = False
    supports_limit_orders: bool = False
    supports_sl_orders: bool = False
    supports_sl_m_orders: bool = False
    supports_bracket_orders: bool = False
    supports_cover_orders: bool = False
    supports_basket_orders: bool = False
    supports_options: bool = False
    supports_futures: bool = False
    supports_commodities: bool = False
    supports_currency: bool = False
    supports_equity: bool = False
    supports_mis: bool = False
    supports_cnc: bool = False
    supports_nrml: bool = False
    supports_websocket: bool = False
    supports_multi_quote: bool = False
    supports_multi_option_greeks: bool = False
    order_rate_limit_per_sec: int = 10
    quote_rate_limit_per_sec: int = 50


class Segments(IntFlag):
    NSE_EQ = auto()
    BSE_EQ = auto()
    NFO = auto()
    BFO = auto()
    CDS = auto()
    BCD = auto()
    MCX = auto()
    NCDEX = auto()
    MF = auto()


class OrderTypes(IntFlag):
    MARKET = auto()
    LIMIT = auto()
    SL = auto()
    SLM = auto()
    MIS = auto()
    CNC = auto()
    NRML = auto()
    AMO = auto()
    GTT = auto()
    ICEBERG = auto()
    BO = auto()
    CO = auto()


class DepthLevels(IntEnum):
    L1 = 1
    L5 = 5
    L20 = 20


class TickProtocol(Enum):
    KITE_BINARY = "kite_binary"
    DHAN_BINARY = "dhan_binary"
    UPSTOX_JSON = "upstox_json"
    KOTAK_NEO_JSON = "kotak_neo_json"
    OPENALGO_JSON = "openalgo_json"
    GENERIC_JSON = "generic_json"


class AuthModel(Enum):
    JWT_LONG_LIVED = "jwt_long_lived"
    OAUTH_DAILY = "oauth_daily"
    OAUTH_TOTP_DAILY = "oauth_totp_daily"
    MPIN_TOTP_DAILY = "mpin_totp_daily"
    OAUTH_RENEWABLE_24H = "oauth_renewable_24h"
    API_KEY_PERSISTENT = "api_key_persistent"


@dataclass(frozen=True)
class Capabilities:
    """Capability advertisement consumed by broker routers and adapters."""

    segments: Segments
    order_types: OrderTypes
    depth_levels: DepthLevels
    tick_protocol: TickProtocol
    auth_model: AuthModel
    session_lifetime_hours: float
    session_renewal_leeway_seconds: int = 60
    sandbox: bool = False
    rate_limit_orders_per_sec: int | None = None
    rate_limit_orders_per_min: int | None = None
    rate_limit_orders_per_hour: int | None = None
    rate_limit_orders_per_day: int | None = None
    rate_limit_data_per_sec: int | None = None
    rate_limit_data_per_day: int | None = None
    rate_limit_quote_per_sec: int | None = None
    rate_limit_non_trading_per_sec: int | None = None
    order_modifications_per_order: int | None = None
    algo_tag_required: bool = False
    cost_paid: bool = False
    cost_inr_per_month: int | None = None
    # Per-trade execution brokerage (distinct from the API-subscription cost
    # above). ``brokerage_free`` advertises zero brokerage on order execution
    # (e.g. Kotak Neo); ``brokerage_note`` carries any caveats (e.g. a bracket
    # square-off leg that still attracts standard brokerage).
    brokerage_free: bool = False
    brokerage_note: str = ""
    historical_max_lookback_days_intraday: int | None = None
    historical_max_lookback_days_daily: int | None = None
    historical_max_candles_per_request: int = 0
    historical_intraday_intervals_minutes: list[int] = field(default_factory=list)
    option_chain_supported: bool = False
    option_chain_greeks_supported: bool = False
    option_chain_rate_limit_seconds: int | None = None
    # Historical options data. ``options_history_supported`` advertises a
    # historical option-chain / options-OHLC API; ``options_history_rolling``
    # adds rolling/continuous series stitched across expiries (Dhan's edge — you
    # can pull a strike's history past its expiry rollover). Routing metadata for
    # the "options_history" use-case; independent of adapter activation.
    options_history_supported: bool = False
    options_history_rolling: bool = False
    streaming_supported: bool = False
    # True only when FlintTrade has a runtime path that can open the live stream
    # without a caller injecting a test/feed-factory shim. ``streaming_supported``
    # records broker/API capability; this records product readiness.
    streaming_runtime_ready: bool = False
    # True only when FlintTrade can return a depth snapshot through the current
    # read route/probe surface. Some brokers document depth only through a feed
    # path that is not wired into runtime yet; keep their documented
    # ``depth_levels`` without recommending an unavailable snapshot read.
    market_depth_runtime_ready: bool = True
    streaming_max_connections_per_user: int | None = None
    streaming_max_symbols_per_connection: int | None = None
    streaming_max_total_symbols: int | None = None
    streaming_heartbeat_seconds: int | None = None
    streaming_disconnect_timeout_seconds: int | None = None
    bracket_order_native: bool = False
    cover_order_native: bool = False
    basket_order_native: bool = False
    multi_quote_supported: bool = False
    multi_option_greeks_supported: bool = False
    iceberg_native: bool = False
    gtt_native: bool = False
    modify_qty_supported: bool = False
    modify_after_partial_fill: bool = False
    reconcile_recommended_seconds: int = 300


def native_capabilities_by_broker() -> dict[str, Capabilities]:
    """Return the authoritative native capabilities keyed by broker id.

    Native membership comes from the activation registry. Instantiating these
    adapters is SDK-safe: constructors only store injected factories/resolvers;
    live SDK clients are built later during ``login()``.
    """
    from .brokers.native_factory import NATIVE_ADAPTER_CLASSES  # noqa: PLC0415

    return {broker_id: cls().capabilities for broker_id, cls in NATIVE_ADAPTER_CLASSES.items()}


def _native_to_broker_capabilities(broker_name: str, caps: Capabilities) -> BrokerCapabilities:
    """Project adapter-native capability metadata onto the legacy route shape."""
    return BrokerCapabilities(
        broker_name=broker_name,
        supports_market_orders=bool(caps.order_types & OrderTypes.MARKET),
        supports_limit_orders=bool(caps.order_types & OrderTypes.LIMIT),
        supports_sl_orders=bool(caps.order_types & OrderTypes.SL),
        supports_sl_m_orders=bool(caps.order_types & OrderTypes.SLM),
        supports_bracket_orders=caps.bracket_order_native or bool(caps.order_types & OrderTypes.BO),
        supports_cover_orders=caps.cover_order_native or bool(caps.order_types & OrderTypes.CO),
        supports_basket_orders=caps.basket_order_native,
        supports_options=bool(caps.segments & (Segments.NFO | Segments.BFO)),
        supports_futures=bool(caps.segments & (Segments.NFO | Segments.BFO)),
        supports_commodities=bool(caps.segments & (Segments.MCX | Segments.NCDEX)),
        supports_currency=bool(caps.segments & (Segments.CDS | Segments.BCD)),
        supports_equity=bool(caps.segments & (Segments.NSE_EQ | Segments.BSE_EQ)),
        supports_mis=bool(caps.order_types & OrderTypes.MIS),
        supports_cnc=bool(caps.order_types & OrderTypes.CNC),
        supports_nrml=bool(caps.order_types & OrderTypes.NRML),
        supports_websocket=caps.streaming_supported,
        supports_multi_quote=caps.multi_quote_supported,
        supports_multi_option_greeks=caps.multi_option_greeks_supported,
        order_rate_limit_per_sec=caps.rate_limit_orders_per_sec or 10,
        quote_rate_limit_per_sec=(
            caps.rate_limit_quote_per_sec
            or caps.rate_limit_data_per_sec
            or caps.rate_limit_non_trading_per_sec
            or 50
        ),
    )


def _register_native_capability_views(reg: CapabilityRegistry) -> None:
    """Register native brokers from adapter constants, overriding stale rows."""
    for broker_name, caps in native_capabilities_by_broker().items():
        reg.register(_native_to_broker_capabilities(broker_name, caps))


class CapabilityRegistry:
    """Lookup broker capabilities by name.

    The registry is pre-seeded with entries for all supported Indian brokers.
    Additional or overriding entries can be added at runtime via
    :meth:`register`.

    Example::

        registry = CapabilityRegistry()
        caps = registry.get("zerodha")
        all_caps = registry.all()
    """

    _instance: ClassVar[CapabilityRegistry | None] = None

    def __init__(self, *, auto_native: bool = False) -> None:
        self._store: dict[str, BrokerCapabilities] = {}
        self._auto_native = auto_native
        self._native_synced = False

    def _ensure_native_synced(self) -> None:
        if not self._auto_native or self._native_synced:
            return
        self._native_synced = True
        _register_native_capability_views(self)

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def register(self, caps: BrokerCapabilities) -> None:
        """Add or replace the capabilities entry for a broker.

        Args:
            caps: :class:`BrokerCapabilities` instance to register.
        """
        self._store[caps.broker_name] = caps

    def get(self, broker_name: str) -> BrokerCapabilities | None:
        """Return the capabilities for *broker_name*, or ``None``.

        Args:
            broker_name: Canonical lower-case broker identifier.

        Returns:
            :class:`BrokerCapabilities` or ``None`` if not found.
        """
        self._ensure_native_synced()
        return self._store.get(broker_name)

    def all(self) -> list[BrokerCapabilities]:
        """Return all registered capability entries.

        Returns:
            List of :class:`BrokerCapabilities` sorted by broker name.
        """
        self._ensure_native_synced()
        return sorted(self._store.values(), key=lambda c: c.broker_name)

    def broker_names(self) -> list[str]:
        """Return a sorted list of all registered broker names.

        Returns:
            List of broker name strings.
        """
        self._ensure_native_synced()
        return sorted(self._store.keys())


# ---------------------------------------------------------------------------
# Pre-seeded registry — bridge/legacy broker capability rows
# ---------------------------------------------------------------------------


def _build_default_registry() -> CapabilityRegistry:
    """Build and return the default capability registry.

    Returns:
        :class:`CapabilityRegistry` pre-populated with known bridge/legacy
        broker rows. Native broker rows are derived lazily from adapter
        capability constants by ``CapabilityRegistry(auto_native=True)``.
    """
    reg = CapabilityRegistry(auto_native=True)

    # -- Zerodha (Kite) ---------------------------------------------------
    reg.register(BrokerCapabilities(
        broker_name="zerodha",
        supports_market_orders=True,
        supports_limit_orders=True,
        supports_sl_orders=True,
        supports_sl_m_orders=True,
        supports_bracket_orders=True,
        supports_cover_orders=True,
        supports_basket_orders=True,
        supports_options=True,
        supports_futures=True,
        supports_commodities=True,
        supports_currency=True,
        supports_equity=True,
        supports_mis=True,
        supports_cnc=True,
        supports_nrml=True,
        supports_websocket=True,
        supports_multi_quote=True,
        supports_multi_option_greeks=False,
        order_rate_limit_per_sec=10,
        quote_rate_limit_per_sec=50,
    ))

    # -- Angel One (SmartAPI) ---------------------------------------------
    reg.register(BrokerCapabilities(
        broker_name="angel",
        supports_market_orders=True,
        supports_limit_orders=True,
        supports_sl_orders=True,
        supports_sl_m_orders=True,
        supports_bracket_orders=False,
        supports_cover_orders=False,
        supports_basket_orders=True,
        supports_options=True,
        supports_futures=True,
        supports_commodities=True,
        supports_currency=True,
        supports_equity=True,
        supports_mis=True,
        supports_cnc=True,
        supports_nrml=True,
        supports_websocket=True,
        supports_multi_quote=True,
        supports_multi_option_greeks=True,
        order_rate_limit_per_sec=10,
        quote_rate_limit_per_sec=50,
    ))

    # -- ICICI Direct (Breeze) --------------------------------------------
    reg.register(BrokerCapabilities(
        broker_name="icici",
        supports_market_orders=True,
        supports_limit_orders=True,
        supports_sl_orders=True,
        supports_sl_m_orders=False,
        supports_bracket_orders=False,
        supports_cover_orders=False,
        supports_basket_orders=False,
        supports_options=True,
        supports_futures=True,
        supports_commodities=True,
        supports_currency=True,
        supports_equity=True,
        supports_mis=True,
        supports_cnc=True,
        supports_nrml=True,
        supports_websocket=True,
        supports_multi_quote=False,
        supports_multi_option_greeks=False,
        order_rate_limit_per_sec=5,
        quote_rate_limit_per_sec=20,
    ))

    # -- Fyers ------------------------------------------------------------
    reg.register(BrokerCapabilities(
        broker_name="fyers",
        supports_market_orders=True,
        supports_limit_orders=True,
        supports_sl_orders=True,
        supports_sl_m_orders=True,
        supports_bracket_orders=True,
        supports_cover_orders=True,
        supports_basket_orders=True,
        supports_options=True,
        supports_futures=True,
        supports_commodities=True,
        supports_currency=True,
        supports_equity=True,
        supports_mis=True,
        supports_cnc=True,
        supports_nrml=True,
        supports_websocket=True,
        supports_multi_quote=True,
        supports_multi_option_greeks=False,
        order_rate_limit_per_sec=10,
        quote_rate_limit_per_sec=50,
    ))

    # -- Motilal Oswal (MO Investor / MOSL) -------------------------------
    reg.register(BrokerCapabilities(
        broker_name="motilal",
        supports_market_orders=True,
        supports_limit_orders=True,
        supports_sl_orders=True,
        supports_sl_m_orders=True,
        supports_bracket_orders=False,
        supports_cover_orders=False,
        supports_basket_orders=True,
        supports_options=True,
        supports_futures=True,
        supports_commodities=True,
        supports_currency=False,
        supports_equity=True,
        supports_mis=True,
        supports_cnc=True,
        supports_nrml=True,
        supports_websocket=True,
        supports_multi_quote=False,
        supports_multi_option_greeks=False,
        order_rate_limit_per_sec=5,
        quote_rate_limit_per_sec=20,
    ))

    # -- IIFL Securities --------------------------------------------------
    reg.register(BrokerCapabilities(
        broker_name="iifl",
        supports_market_orders=True,
        supports_limit_orders=True,
        supports_sl_orders=True,
        supports_sl_m_orders=False,
        supports_bracket_orders=False,
        supports_cover_orders=False,
        supports_basket_orders=False,
        supports_options=True,
        supports_futures=True,
        supports_commodities=True,
        supports_currency=True,
        supports_equity=True,
        supports_mis=True,
        supports_cnc=True,
        supports_nrml=True,
        supports_websocket=False,
        supports_multi_quote=False,
        supports_multi_option_greeks=False,
        order_rate_limit_per_sec=5,
        quote_rate_limit_per_sec=20,
    ))

    # -- Samco (StockNote) ------------------------------------------------
    reg.register(BrokerCapabilities(
        broker_name="samco",
        supports_market_orders=True,
        supports_limit_orders=True,
        supports_sl_orders=True,
        supports_sl_m_orders=True,
        supports_bracket_orders=True,
        supports_cover_orders=True,
        supports_basket_orders=False,
        supports_options=True,
        supports_futures=True,
        supports_commodities=True,
        supports_currency=True,
        supports_equity=True,
        supports_mis=True,
        supports_cnc=True,
        supports_nrml=True,
        supports_websocket=True,
        supports_multi_quote=False,
        supports_multi_option_greeks=False,
        order_rate_limit_per_sec=5,
        quote_rate_limit_per_sec=20,
    ))

    # -- Shoonya (Finvasia) -----------------------------------------------
    reg.register(BrokerCapabilities(
        broker_name="shoonya",
        supports_market_orders=True,
        supports_limit_orders=True,
        supports_sl_orders=True,
        supports_sl_m_orders=True,
        supports_bracket_orders=False,
        supports_cover_orders=False,
        supports_basket_orders=True,
        supports_options=True,
        supports_futures=True,
        supports_commodities=True,
        supports_currency=True,
        supports_equity=True,
        supports_mis=True,
        supports_cnc=True,
        supports_nrml=True,
        supports_websocket=True,
        supports_multi_quote=True,
        supports_multi_option_greeks=False,
        order_rate_limit_per_sec=10,
        quote_rate_limit_per_sec=50,
    ))

    # -- Tradejini --------------------------------------------------------
    reg.register(BrokerCapabilities(
        broker_name="tradejini",
        supports_market_orders=True,
        supports_limit_orders=True,
        supports_sl_orders=True,
        supports_sl_m_orders=True,
        supports_bracket_orders=True,
        supports_cover_orders=True,
        supports_basket_orders=False,
        supports_options=True,
        supports_futures=True,
        supports_commodities=True,
        supports_currency=True,
        supports_equity=True,
        supports_mis=True,
        supports_cnc=True,
        supports_nrml=True,
        supports_websocket=True,
        supports_multi_quote=False,
        supports_multi_option_greeks=False,
        order_rate_limit_per_sec=5,
        quote_rate_limit_per_sec=20,
    ))

    return reg


#: Module-level default registry — import and use directly.
REGISTRY: CapabilityRegistry = _build_default_registry()
