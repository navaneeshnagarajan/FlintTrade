"""Pydantic models for OpenAlgo API requests and responses."""

from __future__ import annotations

from enum import StrEnum
from typing import Any

from pydantic import BaseModel, Field


# ---------------------------------------------------------------------------
# Enums
# ---------------------------------------------------------------------------

class Action(StrEnum):
    BUY = "BUY"
    SELL = "SELL"


class Exchange(StrEnum):
    NSE = "NSE"
    BSE = "BSE"
    NFO = "NFO"
    BFO = "BFO"
    MCX = "MCX"
    CDS = "CDS"
    BCD = "BCD"
    NCDEX = "NCDEX"
    # NCO (NSE Commodities) added upstream in v2.0.0.7 — Zerodha-only as of v2.0.1.1.
    NCO = "NCO"
    NSE_INDEX = "NSE_INDEX"
    BSE_INDEX = "BSE_INDEX"
    # MCX_INDEX (commodity indices, e.g. MCXBULLDEX) added upstream in v2.0.0.7.
    MCX_INDEX = "MCX_INDEX"
    # GLOBAL_INDEX (foreign + IFSC reference indices, e.g. US30, JAPAN225,
    # GIFTNIFTY) added upstream in v2.0.0.7.
    GLOBAL_INDEX = "GLOBAL_INDEX"
    # Delta Exchange crypto. Upstream's plugin.json declares the value as
    # CRYPTO; FlintTrade-internal names sometimes alias it as DELTA for
    # broker-side disambiguation — both forms are accepted at validation.
    CRYPTO = "CRYPTO"


class PriceType(StrEnum):
    MARKET = "MARKET"
    LIMIT = "LIMIT"
    SL = "SL"
    SL_M = "SL-M"


class Product(StrEnum):
    MIS = "MIS"
    CNC = "CNC"
    NRML = "NRML"


class OptionType(StrEnum):
    CE = "CE"
    PE = "PE"


class Interval(StrEnum):
    m1 = "1m"
    m2 = "2m"
    m3 = "3m"
    m5 = "5m"
    m10 = "10m"
    m15 = "15m"
    m30 = "30m"
    h1 = "1h"
    D = "D"


# ---------------------------------------------------------------------------
# Order models
# ---------------------------------------------------------------------------

class Order(BaseModel):
    """Represents an order to place via OpenAlgo."""

    symbol: str
    action: Action
    exchange: Exchange = Exchange.NSE
    pricetype: PriceType = PriceType.MARKET
    product: Product = Product.MIS
    quantity: str = "1"
    price: str = "0"
    trigger_price: str = "0"
    disclosed_quantity: str = "0"
    variety: str = "regular"
    """Order variety. ``"regular"`` (default) is a plain order; ``"bracket"`` /
    ``"cover"`` carry target/stop-loss legs (mapped to a broker's bracket/cover/
    super-order endpoint); ``"iceberg"`` slices a large order into legs. Adapters
    that do not support a variety raise ``BrokerError``. Because the variety and
    its leg prices are part of the order, they are covered by the SafetyContext
    HMAC — an advanced order traverses the SAME gated path as a regular one."""
    target_price: str = "0"
    """Target/take-profit leg price for ``bracket`` orders (0 = none)."""
    stop_loss_price: str = "0"
    """Stop-loss leg price for ``bracket`` / ``cover`` orders (0 = none)."""
    trailing_jump: str = "0"
    """Trailing stop-loss step for ``bracket`` orders (0 = no trailing)."""
    iceberg_legs: str = "0"
    """Number of legs to slice an ``iceberg`` order into (0 = broker default)."""
    strategy: str = "Flint"
    market_protection: bool | None = None
    """Enable Market Price Protection (MPP) for market orders.

    When True, OpenAlgo converts MARKET orders to LIMIT orders with a
    price buffer based on exchange-regulated protection slabs.  Currently
    supported by Zerodha and selected brokers.  None means use the
    broker's default behaviour.
    """
    validity: str | None = None
    """Order validity pass-through (for example ``DAY`` or ``IOC``).

    ``None`` (default) keeps each adapter's default (usually ``DAY``). Each
    native mapping enforces the broker-specific allowed set before a request can
    reach the SDK. Because the field lives on the Order it is covered by the
    SafetyContext HMAC: changing it after the gate is minted invalidates the gate.
    """
    price1: str | None = None
    """OCO second-leg limit price (Dhan forever ``price1``). ``None`` = no OCO.

    When the OCO trio (``price1``/``trigger_price1``/``quantity1``) is set on a
    ``gtt`` order, the Dhan adapter places an OCO forever order instead of a
    SINGLE one. Hashed by the SafetyContext like every other order field."""
    trigger_price1: str | None = None
    """OCO second-leg trigger price (Dhan forever ``triggerPrice1``)."""
    quantity1: str | None = None
    """OCO second-leg quantity (Dhan forever ``quantity1``)."""
    entry_trigger_type: str | None = None
    """Broker-specific GTT entry condition (for example Upstox ABOVE/BELOW/IMMEDIATE).

    ``None`` lets each adapter choose its documented default. When set, the value
    is part of the SafetyContext HMAC just like trigger_price and the leg fields.
    """
    stop_loss_trigger_type: str | None = None
    """Broker-specific stop-loss trigger-type override for GTT-capable adapters."""
    target_trigger_type: str | None = None
    """Broker-specific target trigger-type override for GTT-capable adapters."""


class SmartOrder(Order):
    """Order with automatic position sizing."""

    position_size: str = "0"


class OptionsOrder(BaseModel):
    """Options order using offset-based strike selection."""

    underlying: str
    exchange: Exchange = Exchange.NFO
    expiry_date: str  # YYMMDD
    offset: str = "0"
    option_type: OptionType = OptionType.CE
    action: Action = Action.BUY
    quantity: str = "75"
    pricetype: PriceType = PriceType.MARKET
    product: Product = Product.MIS
    splitsize: str = "75"
    strategy: str = "Flint"


class OptionsLeg(BaseModel):
    """Single leg of a multi-leg options order."""

    offset: str = "0"
    option_type: OptionType = OptionType.CE
    action: Action = Action.BUY
    quantity: str = "75"


class OptionsMultiOrder(BaseModel):
    """Multi-leg options order (straddle, strangle, spread, etc.)."""

    underlying: str
    exchange: Exchange = Exchange.NFO
    expiry_date: str
    legs: list[OptionsLeg]
    pricetype: PriceType = PriceType.MARKET
    product: Product = Product.NRML
    strategy: str = "Flint"


class BasketOrderItem(BaseModel):
    """Single order within a basket."""

    symbol: str
    exchange: Exchange = Exchange.NSE
    action: Action = Action.BUY
    quantity: str = "1"
    pricetype: PriceType = PriceType.MARKET
    product: Product = Product.MIS


class BasketOrder(BaseModel):
    """Multiple orders submitted as a batch."""

    orders: list[BasketOrderItem]
    strategy: str = "Flint"


class SplitOrder(Order):
    """Large order split into smaller chunks."""

    splitsize: str = "25"


class ModifyOrder(BaseModel):
    """Modify an existing order."""

    orderid: str
    symbol: str
    exchange: Exchange = Exchange.NSE
    action: Action = Action.BUY
    pricetype: PriceType = PriceType.LIMIT
    product: Product = Product.MIS
    quantity: str = "1"
    price: str = "0"
    strategy: str = "Flint"


# ---------------------------------------------------------------------------
# GTT (Good Till Triggered) — added to mirror OpenAlgo v2.0.0.9
# ---------------------------------------------------------------------------
#
# GTTs sit on the broker as a trigger condition; when LTP crosses the
# trigger, the broker emits a real order. They live for days/weeks, so
# the schema rejects MIS (intraday) — only CNC / NRML pass validation.
#
# Two trigger types:
#   * SINGLE — exactly one of triggerprice_sl / triggerprice_tg is set
#   * OCO    — both triggers + both limit prices (stoploss / target)
#
# Upstream live support: Dhan + Zerodha. Other brokers return a clean
# 501 — FlintTrade does not gate on broker; we forward the request and
# surface whatever OpenAlgo replies. See restx_api/place_gtt_order.py
# in .local/external/openalgo/ for the canonical schema.


class GttTriggerType(StrEnum):
    SINGLE = "SINGLE"
    OCO = "OCO"


class GttProduct(StrEnum):
    """Products accepted on GTTs. MIS is intentionally absent —
    upstream rejects intraday product on triggers that can sit for days."""

    CNC = "CNC"
    NRML = "NRML"


class GttOrder(BaseModel):
    """Place a GTT (Good Till Triggered) — single or two-leg OCO.

    Required fields mirror OpenAlgo's flat ``PlaceGTTOrderSchema``. Field
    naming follows the upstream wire format exactly (snake_case JSON
    tokens) so the wrapper does not need to remap.
    """

    strategy: str = "Flint"
    trigger_type: GttTriggerType = GttTriggerType.SINGLE
    exchange: Exchange = Exchange.NSE
    symbol: str
    action: Action = Action.BUY
    product: GttProduct = GttProduct.CNC
    quantity: str = "1"
    pricetype: PriceType = PriceType.LIMIT
    price: str = "0"
    triggerprice_sl: str = "0"
    """Stoploss leg trigger price. Required for SINGLE-SL and OCO."""
    triggerprice_tg: str = "0"
    """Target leg trigger price. Required for SINGLE-TG and OCO."""
    stoploss: str | None = None
    """Stoploss leg limit price (OCO only)."""
    target: str | None = None
    """Target leg limit price (OCO only)."""
    expires_at: str | None = None
    """Optional ISO timestamp at which the trigger auto-expires."""


class ModifyGttOrder(BaseModel):
    """Modify an active GTT. Same fields as :class:`GttOrder` plus
    ``trigger_id`` (the broker-returned identifier of the live trigger).

    Modify is a full replacement: trigger prices, last price, and order
    params are replaced atomically by the broker's PUT semantics.
    """

    strategy: str = "Flint"
    trigger_id: str
    trigger_type: GttTriggerType = GttTriggerType.SINGLE
    exchange: Exchange = Exchange.NSE
    symbol: str
    action: Action = Action.BUY
    product: GttProduct = GttProduct.CNC
    quantity: str = "1"
    pricetype: PriceType = PriceType.LIMIT
    price: str = "0"
    triggerprice_sl: str = "0"
    triggerprice_tg: str = "0"
    stoploss: str | None = None
    target: str | None = None


class CancelGttOrder(BaseModel):
    """Cancel an active GTT by its trigger identifier."""

    strategy: str = "Flint"
    trigger_id: str


class GttTrigger(BaseModel):
    """Single row returned by GTT orderbook listings.

    Field names follow OpenAlgo's response; unknown brokers may add
    extras which are silently dropped at the Pydantic boundary.
    """

    trigger_id: str = ""
    status: str = ""
    trigger_type: str = ""
    symbol: str = ""
    exchange: str = ""
    action: str = ""
    quantity: str = ""
    product: str = ""
    price: str = ""
    triggerprice_sl: str = ""
    triggerprice_tg: str = ""
    stoploss: str = ""
    target: str = ""
    created_at: str = ""
    expires_at: str = ""


# ---------------------------------------------------------------------------
# Response models
# ---------------------------------------------------------------------------

class OrderResponse(BaseModel):
    """Response from place/modify/cancel order."""

    status: str
    orderid: str = ""
    message: str = ""


class OrderStatus(BaseModel):
    """Status of a single order."""

    orderid: str = ""
    status: str = ""
    symbol: str = ""
    action: str = ""
    quantity: str = ""
    price: str = ""
    pricetype: str = ""
    product: str = ""
    exchange: str = ""
    filled_quantity: str = ""
    average_price: str = ""
    timestamp: str = ""


# ---------------------------------------------------------------------------
# Position / Holding / Trade
# ---------------------------------------------------------------------------

class Position(BaseModel):
    """Open position from positionbook."""

    symbol: str = ""
    exchange: str = ""
    product: str = ""
    quantity: str = "0"
    average_price: str = "0"
    ltp: str = "0"
    pnl: str = "0"
    buy_quantity: str = "0"
    sell_quantity: str = "0"
    buy_avg: str = "0"
    sell_avg: str = "0"


class Holding(BaseModel):
    """Delivery holding from holdings endpoint."""

    symbol: str = ""
    exchange: str = ""
    quantity: str = "0"
    average_price: str = "0"
    ltp: str = "0"
    pnl: str = "0"
    pnl_percent: str = "0"


class Trade(BaseModel):
    """Executed trade from tradebook."""

    orderid: str = ""
    symbol: str = ""
    exchange: str = ""
    action: str = ""
    quantity: str = "0"
    price: str = "0"
    product: str = ""
    timestamp: str = ""


# ---------------------------------------------------------------------------
# Market data models
# ---------------------------------------------------------------------------

class Quote(BaseModel):
    """Quote data from /quotes or /multiquotes."""

    symbol: str = ""
    exchange: str = ""
    ltp: float = 0.0
    open: float = 0.0
    high: float = 0.0
    low: float = 0.0
    close: float = 0.0
    volume: int = 0
    bid: float = 0.0
    ask: float = 0.0
    prev_close: float = 0.0
    oi: int = 0


class DepthLevel(BaseModel):
    """Single bid/ask level in market depth."""

    price: float = 0.0
    quantity: int = 0
    orders: int = 0


class Depth(BaseModel):
    """Market depth (top 5 bid/ask levels)."""

    symbol: str = ""
    exchange: str = ""
    bids: list[DepthLevel] = Field(default_factory=list)
    asks: list[DepthLevel] = Field(default_factory=list)


class OHLCV(BaseModel):
    """Single OHLCV bar from history endpoint."""

    timestamp: str = ""
    open: float = 0.0
    high: float = 0.0
    low: float = 0.0
    close: float = 0.0
    volume: int = 0


class Candles(BaseModel):
    """Historical OHLCV series for one instrument/interval.

    The canonical return type of ``BrokerAdapter.historical`` — a thin envelope
    around a list of :class:`OHLCV` bars plus the instrument context.
    """

    symbol: str = ""
    exchange: str = ""
    interval: str = ""
    bars: list[OHLCV] = Field(default_factory=list)


class TickEvent(BaseModel):
    """A single streamed market tick (the unit yielded by ``BrokerAdapter.stream``)."""

    symbol: str = ""
    exchange: str = ""
    ltp: float = 0.0
    volume: int = 0
    bid: float = 0.0
    ask: float = 0.0
    oi: int = 0
    timestamp: str = ""


# ---------------------------------------------------------------------------
# Account models
# ---------------------------------------------------------------------------

class Fund(BaseModel):
    """Fund/margin info from /funds endpoint."""

    available_balance: str = "0"
    used_margin: str = "0"
    total_balance: str = "0"
    # OpenAlgo may return additional broker-specific fields
    extra: dict[str, Any] = Field(default_factory=dict)


# ---------------------------------------------------------------------------
# Options analytics
# ---------------------------------------------------------------------------

class OptionGreek(BaseModel):
    """Greeks for a single option contract."""

    symbol: str = ""
    exchange: str = ""
    delta: float = 0.0
    gamma: float = 0.0
    theta: float = 0.0
    vega: float = 0.0
    iv: float = 0.0


class OptionChainStrike(BaseModel):
    """Single strike in an option chain."""

    strike_price: float = 0.0
    ce_ltp: float = 0.0
    ce_oi: int = 0
    ce_volume: int = 0
    ce_iv: float = 0.0
    ce_delta: float = 0.0
    ce_gamma: float = 0.0
    ce_theta: float = 0.0
    ce_vega: float = 0.0
    ce_bid: float = 0.0
    ce_ask: float = 0.0
    pe_ltp: float = 0.0
    pe_oi: int = 0
    pe_volume: int = 0
    pe_iv: float = 0.0
    pe_delta: float = 0.0
    pe_gamma: float = 0.0
    pe_theta: float = 0.0
    pe_vega: float = 0.0
    pe_bid: float = 0.0
    pe_ask: float = 0.0


class OptionChain(BaseModel):
    """Full option chain for an underlying."""

    underlying: str = ""
    exchange: str = ""
    strikes: list[OptionChainStrike] = Field(default_factory=list)
