"""FlintTrade order intentions and normalised native broker observations.

The order fields form the safety-gate input. Each native adapter maps that
intention to its broker protocol; these models do not define a transport.
"""

from __future__ import annotations

from decimal import Decimal, InvalidOperation
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, Field, field_validator


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
    NCO = "NCO"
    NSE_INDEX = "NSE_INDEX"
    BSE_INDEX = "BSE_INDEX"
    MCX_INDEX = "MCX_INDEX"
    GLOBAL_INDEX = "GLOBAL_INDEX"
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


class Order(BaseModel):
    """A gated trading intention; every execution-affecting field is signed."""

    symbol: str
    action: Action
    exchange: Exchange = Exchange.NSE
    product: Product = Product.MIS
    pricetype: PriceType = PriceType.MARKET
    quantity: str = "1"
    price: str = "0"
    trigger_price: str = "0"
    disclosed_quantity: str = "0"
    strategy: str = "Flint"
    admission_note: str = ""
    variety: str = "regular"
    validity: str | None = None
    market_protection: bool | None = None
    # Native advanced-order controls participate in the same gate signature.
    target_price: str = "0"
    stop_loss_price: str = "0"
    trailing_jump: str = "0"
    iceberg_legs: str = "0"
    price1: str | None = None
    trigger_price1: str | None = None
    quantity1: str | None = None
    entry_trigger_type: str | None = None
    stop_loss_trigger_type: str | None = None
    target_trigger_type: str | None = None


class ModifyOrder(BaseModel):
    """Replacement fields supplied to native order modification admission."""

    orderid: str
    symbol: str
    action: Action = Action.BUY
    exchange: Exchange = Exchange.NSE
    product: Product = Product.MIS
    pricetype: PriceType = PriceType.LIMIT
    quantity: str = "1"
    price: str = "0"
    trigger_price: str = "0"
    disclosed_quantity: str = "0"
    strategy: str = "Flint"


class SmartOrder(Order):
    position_size: str = "0"


class SplitOrder(Order):
    splitsize: str = "25"


class OptionsLeg(BaseModel):
    offset: str = "0"
    option_type: OptionType = OptionType.CE
    action: Action = Action.BUY
    quantity: str = "75"


class OptionsOrder(OptionsLeg):
    """An option-selection intention; execution requires a native resolved instrument."""

    underlying: str
    expiry_date: str
    exchange: Exchange = Exchange.NFO
    pricetype: PriceType = PriceType.MARKET
    product: Product = Product.MIS
    splitsize: str = "75"
    strategy: str = "Flint"


class OptionsMultiOrder(BaseModel):
    underlying: str
    expiry_date: str
    legs: list[OptionsLeg]
    exchange: Exchange = Exchange.NFO
    product: Product = Product.NRML
    pricetype: PriceType = PriceType.MARKET
    strategy: str = "Flint"


class BasketOrderItem(BaseModel):
    symbol: str
    action: Action = Action.BUY
    exchange: Exchange = Exchange.NSE
    product: Product = Product.MIS
    pricetype: PriceType = PriceType.MARKET
    quantity: str = "1"


class BasketOrder(BaseModel):
    orders: list[BasketOrderItem]
    strategy: str = "Flint"


class GttTriggerType(StrEnum):
    SINGLE = "SINGLE"
    OCO = "OCO"


class GttProduct(StrEnum):
    CNC = "CNC"
    NRML = "NRML"


class GttOrder(BaseModel):
    """A durable native trigger intention with optional stop and target legs."""

    symbol: str
    strategy: str = "Flint"
    trigger_type: GttTriggerType = GttTriggerType.SINGLE
    exchange: Exchange = Exchange.NSE
    action: Action = Action.BUY
    product: GttProduct = GttProduct.CNC
    quantity: str = "1"
    pricetype: PriceType = PriceType.LIMIT
    price: str = "0"
    triggerprice_sl: str = "0"
    triggerprice_tg: str = "0"
    stoploss: str | None = None
    target: str | None = None
    expires_at: str | None = None


class ModifyGttOrder(BaseModel):
    trigger_id: str
    symbol: str
    strategy: str = "Flint"
    trigger_type: GttTriggerType = GttTriggerType.SINGLE
    exchange: Exchange = Exchange.NSE
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
    trigger_id: str
    strategy: str = "Flint"


class GttTrigger(BaseModel):
    """Normalised durable trigger state read from a native adapter."""

    trigger_id: str = ""
    symbol: str = ""
    exchange: str = ""
    status: str = ""
    trigger_type: str = ""
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


class OrderResponse(BaseModel):
    status: str
    message: str = ""
    orderid: str = ""


class OrderStatus(BaseModel):
    """Omitted broker evidence stays blank so reconciliation can detect it."""

    orderid: str = ""
    symbol: str = ""
    exchange: str = ""
    product: str = ""
    status: str = ""
    action: str = ""
    quantity: str = ""
    price: str = ""
    pricetype: str = ""
    filled_quantity: str = ""
    average_price: str = ""
    trigger_price: str = ""
    disclosed_quantity: str = ""
    timestamp: str = ""


class _InventoryEvidence(BaseModel):
    symbol: str = ""
    instrument_id: str = ""
    exchange: str = ""
    product: str = ""
    quantity: str = "0"
    average_price: str = "0"
    ltp: str = "0"
    pnl: str = "0"
    multiplier: float | None = None
    fx_rate: float | None = None
    close_price: float | None = None
    previous_close_trusted: bool = False
    cross_currency: bool | None = None
    accounting_complete: bool = False


class Position(_InventoryEvidence):
    buy_quantity: str = "0"
    sell_quantity: str = "0"
    buy_avg: str = "0"
    sell_avg: str = "0"
    overnight_quantity: str = "0"
    day_buy_quantity: str = "0"
    day_sell_quantity: str = "0"
    carry_forward_buy_quantity: str = "0"
    carry_forward_sell_quantity: str = "0"
    option_type: str = ""
    expiry: str = ""
    strike_price: float = 0.0
    underlying: str = ""


class Holding(_InventoryEvidence):
    pnl_percent: str = "0"
    settled_quantity: str = "0"
    t1_quantity: str = "0"


class Trade(BaseModel):
    orderid: str = ""
    symbol: str = ""
    instrument_id: str = ""
    exchange: str = ""
    product: str = ""
    action: str = ""
    quantity: str = "0"
    price: str = "0"
    timestamp: str = ""
    multiplier: float | None = None
    fx_rate: float | None = None
    cross_currency: bool | None = None


class Quote(BaseModel):
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
    previous_close_trusted: bool = False
    previous_close_as_of: str = ""
    oi: int = 0


class DepthLevel(BaseModel):
    price: float = 0.0
    quantity: int = 0
    orders: int = 0


class Depth(BaseModel):
    symbol: str = ""
    exchange: str = ""
    bids: list[DepthLevel] = Field(default_factory=list)
    asks: list[DepthLevel] = Field(default_factory=list)


class OHLCV(BaseModel):
    timestamp: str = ""
    open: float = 0.0
    high: float = 0.0
    low: float = 0.0
    close: float = 0.0
    volume: int = 0


class Candles(BaseModel):
    symbol: str = ""
    exchange: str = ""
    interval: str = ""
    bars: list[OHLCV] = Field(default_factory=list)


class TickEvent(BaseModel):
    symbol: str = ""
    exchange: str = ""
    timestamp: str = ""
    ltp: float = 0.0
    volume: int = 0
    bid: float = 0.0
    ask: float = 0.0
    oi: int = 0


class Fund(BaseModel):
    available_balance: str = "0"
    used_margin: str = "0"
    total_balance: str = "0"
    opening_risk_capital: str = "0"
    extra: dict[str, Any] = Field(default_factory=dict)


class OptionGreek(BaseModel):
    symbol: str = ""
    exchange: str = ""
    delta: float = 0.0
    gamma: float = 0.0
    theta: float = 0.0
    vega: float = 0.0
    iv: float = 0.0
    rho: float = 0.0


def _validate_numeric(value: Any, *, positive: bool = False, integer: bool = False) -> Any:
    if isinstance(value, bool):
        raise ValueError("boolean values cannot be numeric evidence")
    try:
        number = Decimal(str(value))
    except (InvalidOperation, ValueError, TypeError) as exc:
        raise ValueError("numeric evidence required") from exc
    if not number.is_finite() or (number <= 0 if positive else number < 0):
        raise ValueError("finite positive evidence required" if positive else "finite non-negative evidence required")
    if integer and number != number.to_integral_value():
        raise ValueError("integer evidence required")
    return value


class OptionChainStrike(BaseModel):
    strike_price: float = 0.0
    ce_instrument_id: str = ""
    ce_ltp: float = 0.0
    ce_oi: int | None = None
    ce_volume: int = 0
    ce_iv: float = 0.0
    ce_delta: float = 0.0
    ce_gamma: float = 0.0
    ce_theta: float = 0.0
    ce_vega: float = 0.0
    ce_bid: float = 0.0
    ce_ask: float = 0.0
    ce_greeks_complete: bool = False
    pe_instrument_id: str = ""
    pe_ltp: float = 0.0
    pe_oi: int | None = None
    pe_volume: int = 0
    pe_iv: float = 0.0
    pe_delta: float = 0.0
    pe_gamma: float = 0.0
    pe_theta: float = 0.0
    pe_vega: float = 0.0
    pe_bid: float = 0.0
    pe_ask: float = 0.0
    pe_greeks_complete: bool = False

    @field_validator("strike_price", mode="before")
    @classmethod
    def validate_strike_price(cls, value: Any) -> Any:
        try:
            return _validate_numeric(value, positive=True)
        except ValueError as exc:
            message = (
                "strike_price must be numeric"
                if isinstance(value, bool)
                else "strike_price must be a finite positive number"
            )
            raise ValueError(message) from exc

    @field_validator("ce_oi", "pe_oi", mode="before")
    @classmethod
    def validate_open_interest(cls, value: Any) -> Any:
        try:
            return None if value is None else _validate_numeric(value, integer=True)
        except ValueError as exc:
            raise ValueError("OI must be a finite non-negative number") from exc


class OptionChain(BaseModel):
    underlying: str = ""
    underlying_key: str = ""
    exchange: str = ""
    expiry: str = ""
    expiry_date: str = ""
    spot_price: float = 0.0
    strikes: list[OptionChainStrike] = Field(default_factory=list)

    @field_validator("underlying_key", "expiry", "expiry_date", mode="before")
    @classmethod
    def reject_non_string_identity(cls, value: Any) -> Any:
        if not isinstance(value, str):
            raise ValueError("option-chain identity fields must be strings")
        return value

    @field_validator("spot_price", mode="before")
    @classmethod
    def reject_boolean_spot_price(cls, value: Any) -> Any:
        if isinstance(value, bool):
            raise ValueError("spot_price must be numeric, not boolean")
        return value
