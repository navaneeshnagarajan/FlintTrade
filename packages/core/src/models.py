"""Pydantic models for OpenAlgo API requests and responses."""

from __future__ import annotations

from enum import Enum
from typing import Any

from pydantic import BaseModel, Field


# ---------------------------------------------------------------------------
# Enums
# ---------------------------------------------------------------------------

class Action(str, Enum):
    BUY = "BUY"
    SELL = "SELL"


class Exchange(str, Enum):
    NSE = "NSE"
    BSE = "BSE"
    NFO = "NFO"
    BFO = "BFO"
    MCX = "MCX"
    CDS = "CDS"
    BCD = "BCD"
    NCDEX = "NCDEX"
    NSE_INDEX = "NSE_INDEX"
    BSE_INDEX = "BSE_INDEX"


class PriceType(str, Enum):
    MARKET = "MARKET"
    LIMIT = "LIMIT"
    SL = "SL"
    SL_M = "SL-M"


class Product(str, Enum):
    MIS = "MIS"
    CNC = "CNC"
    NRML = "NRML"


class OptionType(str, Enum):
    CE = "CE"
    PE = "PE"


class Interval(str, Enum):
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
    strategy: str = "Flint"


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
