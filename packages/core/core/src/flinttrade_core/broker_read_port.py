"""Dependency-neutral contracts for an exact, read-only broker capability."""

from __future__ import annotations

import math
from dataclasses import dataclass, fields
from enum import StrEnum
from typing import Literal, Protocol, TypeAlias, TypeVar
from uuid import UUID

from .account_mutation_contracts import RegistrySelectorVersion
from .broker_identity import INT64_MAX, BrokerSelector, CredentialVersion
from .workspace_migrations import BrokerWorkspaceVersion, WorkspaceVersion


class BrokerReadContractError(ValueError):
    """A public read request or copied result is malformed."""

    def __init__(self) -> None:
        super().__init__("broker_read_contract_invalid")


class BrokerReadResponseInvalid(BrokerReadContractError):
    """A provider response failed one fixed strict projection seam."""

    def __init__(self) -> None:
        ValueError.__init__(self, "broker_read_response_invalid")


class BrokerBalanceResponseInvalid(BrokerReadResponseInvalid):
    """A provider balance payload failed the fixed strict conversion seam."""

    def __init__(self) -> None:
        ValueError.__init__(self, "broker_balance_response_invalid")


class BrokerLotSizeResponseInvalid(BrokerReadResponseInvalid):
    """A provider lot-size payload failed the fixed strict conversion seam."""

    def __init__(self) -> None:
        ValueError.__init__(self, "broker_lot_size_response_invalid")


def _invalid() -> None:
    raise BrokerReadContractError


def _required_str(value: object) -> None:
    if type(value) is not str or not value:
        _invalid()


def _optional_str(value: object) -> None:
    if value is not None:
        _required_str(value)


def _float(value: object) -> None:
    if type(value) is not float or not math.isfinite(value):
        _invalid()


def _optional_float(value: object) -> None:
    if value is not None:
        _float(value)


def _int(value: object) -> None:
    if type(value) is not int:
        _invalid()


def _optional_int(value: object) -> None:
    if value is not None:
        _int(value)


def _optional_bool(value: object) -> None:
    if value is not None and type(value) is not bool:
        _invalid()


def _tuple_of(value: object, item_type: type) -> None:
    if type(value) is not tuple or any(type(item) is not item_type for item in value):
        _invalid()


class BrokerDataRole(StrEnum):
    """Closed persisted broker data-routing roles."""

    QUOTE = "quote"
    HISTORICAL = "historical"
    OPTION_CHAINS = "option_chains"
    GLOBAL_INDICES = "global_indices"


class BrokerReadErrorCode(StrEnum):
    """Fixed public failure outcomes; provider details never cross the port."""

    INVALID_REQUEST = "invalid_request"
    TARGET_UNAVAILABLE = "target_unavailable"
    TARGET_AMBIGUOUS = "target_ambiguous"
    TARGET_STALE = "target_stale"
    UNAUTHORISED = "unauthorised"
    REVOKED = "revoked"
    DISCONNECTED = "disconnected"
    UNSUPPORTED = "unsupported"
    PROVIDER_FAILURE = "provider_failure"
    MALFORMED_RESPONSE = "malformed_response"


class BalanceEvidence(StrEnum):
    """Origin of a copied balance value."""

    DIRECT = "direct"
    DERIVED_FROM_DIRECT_COMPONENTS = "derived_from_direct_components"


class BrokerOrderFamily(StrEnum):
    REGULAR = "regular"
    FOREVER = "forever"
    SUPER = "super"


class BrokerOrderSourceFamily(StrEnum):
    REGULAR = "regular"
    FOREVER = "forever"
    SUPER = "super"
    CONDITIONAL = "conditional"


@dataclass(frozen=True, slots=True, weakref_slot=True)
class ExactReadTarget:
    selector: BrokerSelector

    def __post_init__(self) -> None:
        if type(self.selector) is not BrokerSelector:
            _invalid()
        try:
            self.selector.__post_init__()
        except ValueError:
            _invalid()


@dataclass(frozen=True, slots=True, weakref_slot=True)
class DataRoleReadTarget:
    role: BrokerDataRole

    def __post_init__(self) -> None:
        if type(self.role) is not BrokerDataRole:
            _invalid()


BrokerReadTarget: TypeAlias = ExactReadTarget | DataRoleReadTarget


@dataclass(frozen=True, slots=True)
class BrokerReadProvenance:
    selector: BrokerSelector
    registry_version: RegistrySelectorVersion
    credential_version: CredentialVersion | None
    workspace_version: WorkspaceVersion
    broker_workspace_version: BrokerWorkspaceVersion
    requested_role: BrokerDataRole | None

    def __post_init__(self) -> None:
        if (
            type(self.selector) is not BrokerSelector
            or type(self.registry_version) is not RegistrySelectorVersion
            or type(self.workspace_version) is not WorkspaceVersion
            or type(self.broker_workspace_version) is not BrokerWorkspaceVersion
            or (self.credential_version is not None and type(self.credential_version) is not CredentialVersion)
            or (self.requested_role is not None and type(self.requested_role) is not BrokerDataRole)
        ):
            _invalid()
        registry = self.registry_version
        credential = self.credential_version
        workspace = self.workspace_version
        broker_workspace = self.broker_workspace_version
        if (
            registry.selector != self.selector
            or not registry.present
            or registry.generation < 1
            or (credential is None and self.selector != BrokerSelector("openalgo", "default"))
            or (credential is not None and (credential.selector != self.selector or credential.generation < 1))
            or type(workspace.instance_id) is not UUID
            or type(workspace.generation) is not int
            or not 1 <= workspace.generation <= INT64_MAX
            or type(broker_workspace.instance_id) is not UUID
            or type(broker_workspace.generation) is not int
            or not 1 <= broker_workspace.generation <= INT64_MAX
            or workspace.instance_id != broker_workspace.instance_id
        ):
            _invalid()


T = TypeVar("T")


@dataclass(frozen=True, slots=True)
class BrokerReadSuccess[T]:
    provenance: BrokerReadProvenance
    value: T

    def __post_init__(self) -> None:
        if type(self.provenance) is not BrokerReadProvenance:
            _invalid()


@dataclass(frozen=True, slots=True)
class BrokerReadFailure:
    code: BrokerReadErrorCode

    def __post_init__(self) -> None:
        if type(self.code) is not BrokerReadErrorCode:
            _invalid()


BrokerReadOutcome: TypeAlias = BrokerReadSuccess[T] | BrokerReadFailure


@dataclass(frozen=True, slots=True)
class InstrumentRef:
    symbol: str
    exchange: str
    instrument_id: str | None = None

    def __post_init__(self) -> None:
        _required_str(self.symbol)
        _required_str(self.exchange)
        _optional_str(self.instrument_id)


@dataclass(frozen=True, slots=True)
class QuoteRequest:
    instrument: InstrumentRef

    def __post_init__(self) -> None:
        if type(self.instrument) is not InstrumentRef:
            _invalid()


@dataclass(frozen=True, slots=True)
class QuoteSnapshot:
    instrument: InstrumentRef
    available: bool
    ltp: float | None
    open: float | None
    high: float | None
    low: float | None
    close: float | None
    volume: int | None
    bid: float | None
    ask: float | None
    prev_close: float | None
    previous_close_trusted: bool | None
    previous_close_as_of: str | None
    oi: int | None

    def __post_init__(self) -> None:
        if type(self.instrument) is not InstrumentRef or type(self.available) is not bool:
            _invalid()
        for value in (self.ltp, self.open, self.high, self.low, self.close, self.bid, self.ask, self.prev_close):
            _optional_float(value)
        _optional_int(self.volume)
        _optional_int(self.oi)
        _optional_bool(self.previous_close_trusted)
        _optional_str(self.previous_close_as_of)
        if not self.available and any(
            value is not None
            for value in fields(self)
            if value.name not in {"instrument", "available"}
            for value in (getattr(self, value.name),)
        ):
            _invalid()


@dataclass(frozen=True, slots=True)
class DepthLevelSnapshot:
    price: float
    quantity: int
    orders: int | None

    def __post_init__(self) -> None:
        _float(self.price)
        _int(self.quantity)
        _optional_int(self.orders)


@dataclass(frozen=True, slots=True)
class DepthSnapshot:
    instrument: InstrumentRef
    bids: tuple[DepthLevelSnapshot, ...]
    asks: tuple[DepthLevelSnapshot, ...]

    def __post_init__(self) -> None:
        if type(self.instrument) is not InstrumentRef:
            _invalid()
        _tuple_of(self.bids, DepthLevelSnapshot)
        _tuple_of(self.asks, DepthLevelSnapshot)


@dataclass(frozen=True, slots=True)
class HistoricalRequest:
    instrument: InstrumentRef
    interval: str
    start_date: str
    end_date: str

    def __post_init__(self) -> None:
        if type(self.instrument) is not InstrumentRef:
            _invalid()
        for value in (self.interval, self.start_date, self.end_date):
            _required_str(value)


@dataclass(frozen=True, slots=True)
class CandleSnapshot:
    timestamp: str
    open: float
    high: float
    low: float
    close: float
    volume: int | None

    def __post_init__(self) -> None:
        _required_str(self.timestamp)
        for value in (self.open, self.high, self.low, self.close):
            _float(value)
        _optional_int(self.volume)


@dataclass(frozen=True, slots=True)
class HistoricalSnapshot:
    instrument: InstrumentRef
    interval: str
    bars: tuple[CandleSnapshot, ...]

    def __post_init__(self) -> None:
        if type(self.instrument) is not InstrumentRef:
            _invalid()
        _required_str(self.interval)
        _tuple_of(self.bars, CandleSnapshot)


@dataclass(frozen=True, slots=True)
class BatchQuoteRequest:
    instruments: tuple[InstrumentRef, ...]

    def __post_init__(self) -> None:
        _tuple_of(self.instruments, InstrumentRef)
        if not self.instruments:
            _invalid()


@dataclass(frozen=True, slots=True)
class OptionChainRequest:
    underlying: InstrumentRef
    expiry_date: str

    def __post_init__(self) -> None:
        if type(self.underlying) is not InstrumentRef:
            _invalid()
        _required_str(self.expiry_date)


@dataclass(frozen=True, slots=True)
class OptionChainStrikeSnapshot:
    strike_price: float
    ce_instrument_id: str | None
    ce_ltp: float | None
    ce_oi: int | None
    ce_volume: int | None
    ce_iv: float | None
    ce_delta: float | None
    ce_gamma: float | None
    ce_theta: float | None
    ce_vega: float | None
    ce_bid: float | None
    ce_ask: float | None
    ce_greeks_complete: bool | None
    pe_instrument_id: str | None
    pe_ltp: float | None
    pe_oi: int | None
    pe_volume: int | None
    pe_iv: float | None
    pe_delta: float | None
    pe_gamma: float | None
    pe_theta: float | None
    pe_vega: float | None
    pe_bid: float | None
    pe_ask: float | None
    pe_greeks_complete: bool | None

    def __post_init__(self) -> None:
        _float(self.strike_price)
        _optional_str(self.ce_instrument_id)
        _optional_str(self.pe_instrument_id)
        for value in (
            self.ce_ltp,
            self.ce_iv,
            self.ce_delta,
            self.ce_gamma,
            self.ce_theta,
            self.ce_vega,
            self.ce_bid,
            self.ce_ask,
            self.pe_ltp,
            self.pe_iv,
            self.pe_delta,
            self.pe_gamma,
            self.pe_theta,
            self.pe_vega,
            self.pe_bid,
            self.pe_ask,
        ):
            _optional_float(value)
        for value in (self.ce_oi, self.ce_volume, self.pe_oi, self.pe_volume):
            _optional_int(value)
        _optional_bool(self.ce_greeks_complete)
        _optional_bool(self.pe_greeks_complete)


@dataclass(frozen=True, slots=True)
class OptionChainSnapshot:
    underlying: InstrumentRef
    expiry: str
    spot_price: float | None
    strikes: tuple[OptionChainStrikeSnapshot, ...]

    def __post_init__(self) -> None:
        if type(self.underlying) is not InstrumentRef:
            _invalid()
        _required_str(self.expiry)
        _optional_float(self.spot_price)
        _tuple_of(self.strikes, OptionChainStrikeSnapshot)


@dataclass(frozen=True, slots=True)
class LotSizeRequest:
    exchange: str
    symbols: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        _required_str(self.exchange)
        if type(self.symbols) is not tuple or any(type(symbol) is not str or not symbol for symbol in self.symbols):
            _invalid()


@dataclass(frozen=True, slots=True)
class InstrumentLotSizeSnapshot:
    symbol: str
    exchange: str
    lot_size: int
    instrument_id: str | None = None

    def __post_init__(self) -> None:
        _required_str(self.symbol)
        _required_str(self.exchange)
        _optional_str(self.instrument_id)
        if type(self.lot_size) is not int or not 1 <= self.lot_size <= 1_000_000:
            _invalid()


@dataclass(frozen=True, slots=True)
class BalanceSnapshot:
    available_balance: float | None
    available_balance_evidence: BalanceEvidence | None
    used_margin: float | None
    used_margin_evidence: BalanceEvidence | None
    total_balance: float | None
    total_balance_evidence: BalanceEvidence | None
    opening_risk_capital: float | None
    opening_risk_capital_evidence: BalanceEvidence | None

    def __post_init__(self) -> None:
        pairs = (
            (self.available_balance, self.available_balance_evidence),
            (self.used_margin, self.used_margin_evidence),
            (self.total_balance, self.total_balance_evidence),
            (self.opening_risk_capital, self.opening_risk_capital_evidence),
        )
        for value, evidence in pairs:
            _optional_float(value)
            if (value is None) != (evidence is None):
                _invalid()
            if evidence is not None and type(evidence) is not BalanceEvidence:
                _invalid()
        if self.available_balance_evidence not in (None, BalanceEvidence.DIRECT):
            _invalid()
        if self.opening_risk_capital_evidence not in (None, BalanceEvidence.DIRECT):
            _invalid()


@dataclass(frozen=True, slots=True)
class MarginRequest:
    symbol: str
    exchange: str
    action: Literal["BUY", "SELL"]
    quantity: str
    product: str
    pricetype: str
    price: str
    trigger_price: str

    def __post_init__(self) -> None:
        for value in (
            self.symbol,
            self.exchange,
            self.quantity,
            self.product,
            self.pricetype,
            self.price,
            self.trigger_price,
        ):
            _required_str(value)
        if type(self.action) is not str or self.action not in {"BUY", "SELL"}:
            _invalid()


@dataclass(frozen=True, slots=True)
class MarginSnapshot:
    required_margin: float

    def __post_init__(self) -> None:
        _float(self.required_margin)
        if self.required_margin < 0:
            _invalid()


@dataclass(frozen=True, slots=True)
class PortfolioPositionRef:
    symbol: str
    exchange: str
    quantity: str
    option_type: Literal["CE", "PE"]
    instrument_id: str | None
    expiry: str | None
    strike_price: float | None
    underlying: str | None

    def __post_init__(self) -> None:
        for value in (self.symbol, self.exchange, self.quantity):
            _required_str(value)
        if type(self.option_type) is not str or self.option_type not in {"CE", "PE"}:
            _invalid()
        _optional_str(self.instrument_id)
        _optional_str(self.expiry)
        _optional_float(self.strike_price)
        _optional_str(self.underlying)


@dataclass(frozen=True, slots=True)
class PortfolioGreeksRequest:
    positions: tuple[PortfolioPositionRef, ...]

    def __post_init__(self) -> None:
        _tuple_of(self.positions, PortfolioPositionRef)


@dataclass(frozen=True, slots=True)
class PortfolioGreekSnapshot:
    symbol: str
    exchange: str
    instrument_id: str | None
    delta: float
    vega: float

    def __post_init__(self) -> None:
        _required_str(self.symbol)
        _required_str(self.exchange)
        _optional_str(self.instrument_id)
        _float(self.delta)
        _float(self.vega)


@dataclass(frozen=True, slots=True)
class PositionSnapshot:
    symbol: str
    instrument_id: str | None
    exchange: str
    product: str
    quantity: str
    average_price: str | None
    ltp: str | None
    pnl: str | None
    buy_quantity: str | None
    sell_quantity: str | None
    buy_avg: str | None
    sell_avg: str | None
    multiplier: float | None
    fx_rate: float | None
    close_price: float | None
    previous_close_trusted: bool | None
    cross_currency: bool | None
    overnight_quantity: str | None
    day_buy_quantity: str | None
    day_sell_quantity: str | None
    carry_forward_buy_quantity: str | None
    carry_forward_sell_quantity: str | None
    accounting_complete: bool | None
    option_type: str | None
    expiry: str | None
    strike_price: float | None
    underlying: str | None

    def __post_init__(self) -> None:
        for value in (self.symbol, self.exchange, self.product, self.quantity):
            _required_str(value)
        for value in (
            self.instrument_id,
            self.average_price,
            self.ltp,
            self.pnl,
            self.buy_quantity,
            self.sell_quantity,
            self.buy_avg,
            self.sell_avg,
            self.overnight_quantity,
            self.day_buy_quantity,
            self.day_sell_quantity,
            self.carry_forward_buy_quantity,
            self.carry_forward_sell_quantity,
            self.option_type,
            self.expiry,
            self.underlying,
        ):
            _optional_str(value)
        for value in (self.multiplier, self.fx_rate, self.close_price, self.strike_price):
            _optional_float(value)
        for value in (self.previous_close_trusted, self.cross_currency, self.accounting_complete):
            _optional_bool(value)


@dataclass(frozen=True, slots=True)
class HoldingSnapshot:
    symbol: str
    instrument_id: str | None
    exchange: str
    product: str | None
    quantity: str
    average_price: str | None
    ltp: str | None
    pnl: str | None
    pnl_percent: str | None
    multiplier: float | None
    fx_rate: float | None
    close_price: float | None
    previous_close_trusted: bool | None
    cross_currency: bool | None
    settled_quantity: str | None
    t1_quantity: str | None
    accounting_complete: bool | None

    def __post_init__(self) -> None:
        for value in (self.symbol, self.exchange, self.quantity):
            _required_str(value)
        for value in (
            self.instrument_id,
            self.product,
            self.average_price,
            self.ltp,
            self.pnl,
            self.pnl_percent,
            self.settled_quantity,
            self.t1_quantity,
        ):
            _optional_str(value)
        for value in (self.multiplier, self.fx_rate, self.close_price):
            _optional_float(value)
        for value in (self.previous_close_trusted, self.cross_currency, self.accounting_complete):
            _optional_bool(value)


@dataclass(frozen=True, slots=True)
class TradeSnapshot:
    orderid: str | None
    symbol: str
    instrument_id: str | None
    exchange: str
    action: str
    quantity: str
    price: str
    product: str
    timestamp: str
    multiplier: float | None
    fx_rate: float | None
    cross_currency: bool | None

    def __post_init__(self) -> None:
        for value in (self.symbol, self.exchange, self.action, self.quantity, self.price, self.product, self.timestamp):
            _required_str(value)
        _optional_str(self.orderid)
        _optional_str(self.instrument_id)
        _optional_float(self.multiplier)
        _optional_float(self.fx_rate)
        _optional_bool(self.cross_currency)


@dataclass(frozen=True, slots=True)
class OrderStateRequest:
    family: BrokerOrderFamily
    order_id: str | None = None

    def __post_init__(self) -> None:
        if type(self.family) is not BrokerOrderFamily:
            _invalid()
        _optional_str(self.order_id)


@dataclass(frozen=True, slots=True)
class OrderLegStateSnapshot:
    leg_name: str
    status: str | None
    order_id: str | None
    exchange_order_id: str | None
    quantity: str | None
    filled_quantity: str | None
    price: str | None
    trigger_price: str | None

    def __post_init__(self) -> None:
        if type(self.leg_name) is not str or self.leg_name not in {"ENTRY_LEG", "TARGET_LEG", "STOP_LOSS_LEG"}:
            _invalid()
        for value in (
            self.status,
            self.order_id,
            self.exchange_order_id,
            self.quantity,
            self.filled_quantity,
            self.price,
            self.trigger_price,
        ):
            _optional_str(value)


@dataclass(frozen=True, slots=True)
class OrderStateSnapshot:
    family: BrokerOrderFamily
    order_family: BrokerOrderSourceFamily | None
    orderid: str | None
    status: str
    symbol: str | None
    instrument_id: str | None
    exchange: str | None
    action: str | None
    product: str | None
    quantity: str | None
    filled_quantity: str | None
    pricetype: str | None
    price: str | None
    trigger_price: str | None
    disclosed_quantity: str | None
    option_type: str | None
    expiry: str | None
    strike_price: float | None
    underlying: str | None
    safety_order_id: str | None
    broker_order_id: str | None
    raw_broker_order_id: str | None
    parent_order_id: str | None
    exchange_order_id: str | None
    leg_name: str | None
    margin_unfunded: bool | None
    order_flag: Literal["SINGLE", "OCO"] | None
    legs: tuple[OrderLegStateSnapshot, ...]

    def __post_init__(self) -> None:
        if type(self.family) is not BrokerOrderFamily:
            _invalid()
        if self.order_family is not None and type(self.order_family) is not BrokerOrderSourceFamily:
            _invalid()
        _required_str(self.status)
        for value in (
            self.orderid,
            self.symbol,
            self.instrument_id,
            self.exchange,
            self.action,
            self.product,
            self.quantity,
            self.filled_quantity,
            self.pricetype,
            self.price,
            self.trigger_price,
            self.disclosed_quantity,
            self.option_type,
            self.expiry,
            self.underlying,
            self.safety_order_id,
            self.broker_order_id,
            self.raw_broker_order_id,
            self.parent_order_id,
            self.exchange_order_id,
            self.leg_name,
        ):
            _optional_str(value)
        _optional_float(self.strike_price)
        _optional_bool(self.margin_unfunded)
        if self.order_flag is not None and (
            type(self.order_flag) is not str or self.order_flag not in {"SINGLE", "OCO"}
        ):
            _invalid()
        _tuple_of(self.legs, OrderLegStateSnapshot)


class BrokerReadPort(Protocol):
    async def quote(self, request: QuoteRequest) -> BrokerReadOutcome[QuoteSnapshot]: ...

    async def depth(self, request: QuoteRequest) -> BrokerReadOutcome[DepthSnapshot]: ...

    async def historical(self, request: HistoricalRequest) -> BrokerReadOutcome[HistoricalSnapshot]: ...

    async def batch_quotes(
        self, request: BatchQuoteRequest
    ) -> BrokerReadOutcome[tuple[QuoteSnapshot, ...]]: ...

    async def option_chain(self, request: OptionChainRequest) -> BrokerReadOutcome[OptionChainSnapshot]: ...

    async def lot_sizes(
        self, request: LotSizeRequest
    ) -> BrokerReadOutcome[tuple[InstrumentLotSizeSnapshot, ...]]: ...

    async def balance(self) -> BrokerReadOutcome[BalanceSnapshot]: ...

    async def portfolio_greeks(
        self, request: PortfolioGreeksRequest
    ) -> BrokerReadOutcome[tuple[PortfolioGreekSnapshot, ...]]: ...

    async def positions(self) -> BrokerReadOutcome[tuple[PositionSnapshot, ...]]: ...

    async def holdings(self) -> BrokerReadOutcome[tuple[HoldingSnapshot, ...]]: ...

    async def margin(self, request: MarginRequest) -> BrokerReadOutcome[MarginSnapshot]: ...

    async def order_states(
        self, request: OrderStateRequest
    ) -> BrokerReadOutcome[tuple[OrderStateSnapshot, ...]]: ...

    async def trades(self) -> BrokerReadOutcome[tuple[TradeSnapshot, ...]]: ...
