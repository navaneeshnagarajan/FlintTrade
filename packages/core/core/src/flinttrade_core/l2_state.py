"""Gather broker-neutral portfolio inputs for SafetySystem L2 and L4."""

from __future__ import annotations

import asyncio
from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import date, datetime, time, timedelta, timezone
import math
from types import SimpleNamespace
from typing import Any


_IST = timezone(timedelta(hours=5, minutes=30))
_CASH_EXCHANGES = frozenset({"BSE", "NSE"})
_DERIVATIVE_EXCHANGES = frozenset({"BCD", "BFO", "CDS", "MCX", "NFO"})
_SNAPSHOT_ATTEMPTS = 3


def _to_float(value: Any) -> float:
    try:
        parsed = float(str(value))
    except (TypeError, ValueError):
        return 0.0
    return parsed if math.isfinite(parsed) else 0.0


def _field(obj: Any, *keys: str) -> Any:
    if isinstance(obj, Mapping):
        for key in keys:
            if key in obj:
                return obj[key]
        return None
    for key in keys:
        value = getattr(obj, key, None)
        if value is not None:
            return value
    return None


def normalise_l2_positions(raw: Any) -> list[Any]:
    """Return position-like objects with at least a ``quantity`` attribute."""
    if raw is None:
        return []
    if isinstance(raw, Mapping):
        rows = raw.get("data") or raw.get("positions") or raw.get("net") or raw.get("day") or []
    elif isinstance(raw, (list, tuple)):
        rows = raw
    else:
        rows = [raw]

    positions: list[Any] = []
    for row in rows:
        if hasattr(row, "quantity"):
            positions.append(row)
        elif isinstance(row, Mapping):
            quantity = _field(
                row,
                "quantity",
                "qty",
                "net_quantity",
                "netQty",
                "net_qty",
                "netqty",
                "cfBuyQty",
                "cfSellQty",
            )
            positions.append(
                SimpleNamespace(
                    symbol=_text(_field(row, "symbol", "trading_symbol", "tradingsymbol")),
                    exchange=_text(_field(row, "exchange")).upper(),
                    product=_text(_field(row, "product")).upper(),
                    quantity=str(quantity or "0"),
                )
            )
    return positions


def normalise_l2_funds(raw: Any) -> tuple[float, float]:
    """Return ``(used_margin, total_balance)`` from broker-shaped funds."""
    used = _to_float(_field(
        raw,
        "used_margin",
        "utilized_margin",
        "utilised_margin",
        "usedmargin",
        "margin_used",
        "marginUsed",
        "MarginUsed",
        "used",
    ))
    total = _to_float(_field(
        raw,
        "total_balance",
        "total",
        "totalcollateral",
        "totalCollateral",
        "net",
        "net_balance",
        "Net",
    ))
    if total <= 0:
        available = _to_float(_field(
            raw,
            "available_balance",
            "available_margin",
            "available",
            "net",
            "Net",
        ))
        if available or used:
            total = available + used
    return used, total


def normalise_l2_state(positions: Any, funds: Any) -> tuple[list[Any], float, float]:
    """Return ``(positions, used_margin, total_balance)`` for L2 validation."""
    used_margin, total_balance = normalise_l2_funds(funds)
    return normalise_l2_positions(positions), used_margin, total_balance


class PortfolioSafetyStateError(RuntimeError):
    """Raised when a complete, locally computed L4 snapshot is unavailable."""


@dataclass(frozen=True)
class ProspectiveSafetyInputs:
    """SafetySystem inputs aligned to one proposed order in a request."""

    positions: list[Any]
    used_margin: float
    net_delta: float
    net_vega: float


@dataclass(frozen=True)
class PortfolioSafetyState:
    """Selector-scoped inputs for one complete SafetySystem order check."""

    positions: list[Any]
    used_margin: float
    total_balance: float
    daily_pnl: float
    starting_capital: float
    net_delta: float = 0.0
    net_vega: float = 0.0
    order_ltps: dict[tuple[str, str], float] = field(default_factory=dict)
    prospective: tuple[ProspectiveSafetyInputs, ...] = ()
    reconciled_reservation_ids: tuple[str, ...] = ()

    def ltp_for(self, order: Any) -> float | None:
        """Return the authoritative LTP required by a LIMIT/SL safety check."""
        pricetype = _text(_field(order, "pricetype", "price_type", "order_type")).upper()
        if pricetype not in {"LIMIT", "SL"}:
            return None
        symbol = _text(_field(order, "symbol", "trading_symbol", "tradingsymbol"))
        exchange = _text(_field(order, "exchange")).upper()
        return self.order_ltps.get((exchange, symbol))

    def admission_for(self, order_index: int) -> ProspectiveSafetyInputs:
        """Return the post-order risk inputs aligned to ``orders[order_index]``."""
        try:
            return self.prospective[order_index]
        except IndexError as exc:
            raise PortfolioSafetyStateError("Proposed order is missing its prospective safety state") from exc


@dataclass(frozen=True)
class ModifySafetyIntent:
    """Authoritatively classified replacement for one live resting order."""

    proposed_order: Any
    risk_increasing: bool
    margin_delta: float


@dataclass(frozen=True)
class _AccountSource:
    target: Any
    session: Any = None
    openalgo: bool = False


@dataclass(frozen=True)
class _AccountingSnapshot:
    positions: Any
    trades: Any
    holdings: Any
    orders: Any


@dataclass
class _InstrumentLedger:
    symbol: str = ""
    end_quantity: float = 0.0
    position_quantity: float = 0.0
    net_trade_quantity: float = 0.0
    holding_quantity: float = 0.0
    overnight_quantity: float = 0.0
    day_buy_quantity: float = 0.0
    day_sell_quantity: float = 0.0
    carry_forward_buy_quantity: float = 0.0
    carry_forward_sell_quantity: float = 0.0
    position_seen: bool = False
    holding_seen: bool = False
    position_accounting_complete: bool = True
    holding_accounting_complete: bool = True
    multiplier: float | None = None
    fx_rate: float | None = None
    cross_currency: bool | None = None
    previous_close: float | None = None
    fills: list[tuple[float, float]] = field(default_factory=list)


def _canonical_option_type(row: Any) -> str:
    explicit = _text(_field(row, "option_type", "drvOptionType", "instrument_type")).upper()
    aliases = {"CALL": "CE", "CE": "CE", "PUT": "PE", "PE": "PE"}
    canonical = aliases.get(explicit)
    if canonical:
        return canonical
    exchange = _text(_field(row, "exchange")).upper()
    symbol = _text(_field(row, "symbol", "trading_symbol", "tradingsymbol")).upper()
    if exchange not in _DERIVATIVE_EXCHANGES:
        return ""
    for suffix, option_type in (("CALL", "CE"), ("PUT", "PE"), ("CE", "CE"), ("PE", "PE")):
        contract_root = symbol.removesuffix(suffix).rstrip()
        if contract_root != symbol and any(char.isdigit() for char in contract_root):
            return option_type
    return ""


def _option_risk_positions(
    raw_positions: Any,
    proposed_orders: list[Any] | tuple[Any, ...] = (),
) -> list[dict[str, Any]]:
    """Return the prospective non-flat option book for a broker Greek read."""
    aggregated: dict[str, dict[str, Any]] = {}

    def merge(row: Any, quantity: float) -> None:
        option_type = _canonical_option_type(row)
        if not option_type or quantity == 0:
            return
        symbol = _text(_field(row, "symbol", "trading_symbol", "tradingsymbol"))
        exchange = _text(_field(row, "exchange")).upper()
        instrument_id = _text(
            _field(row, "instrument_id", "instrument_token", "security_id", "securityId")
        )
        if not symbol or not exchange:
            raise PortfolioSafetyStateError("Incomplete option position identity")
        raw_strike = _field(row, "strike_price", "strike", "drvStrikePrice")
        strike_price = 0.0
        if raw_strike not in (None, ""):
            strike_price = _finite_number(raw_strike, "option strike price")
            if strike_price <= 0:
                raise PortfolioSafetyStateError("Option strike price must be positive")
        key = f"{exchange}:{symbol}"
        candidate = {
            "symbol": symbol,
            "instrument_id": instrument_id,
            "exchange": exchange,
            "quantity": quantity,
            "option_type": option_type,
            "expiry": _text(_field(row, "expiry", "expiry_date", "drvExpiryDate")),
            "strike_price": strike_price,
            "underlying": _text(_field(row, "underlying", "underlying_symbol")),
        }
        current = aggregated.get(key)
        if current is None:
            aggregated[key] = candidate
            return
        for field_name in ("symbol", "instrument_id", "exchange", "option_type", "expiry", "underlying"):
            current_value = current[field_name]
            candidate_value = candidate[field_name]
            if current_value and candidate_value and current_value != candidate_value:
                raise PortfolioSafetyStateError("Conflicting option position identity")
            if not current_value and candidate_value:
                current[field_name] = candidate_value
        if current["strike_price"] and candidate["strike_price"]:
            if not math.isclose(current["strike_price"], candidate["strike_price"], abs_tol=1e-9):
                raise PortfolioSafetyStateError("Conflicting option position identity")
        elif candidate["strike_price"]:
            current["strike_price"] = candidate["strike_price"]
        current["quantity"] += quantity

    for row in _rows(raw_positions, "data", "positions", "net", "day"):
        quantity = _finite_number(
            _field(row, "quantity", "qty", "net_quantity", "netQty"),
            "option position quantity",
        )
        merge(row, quantity)

    for order in proposed_orders:
        if not _canonical_option_type(order):
            continue
        quantity = _finite_number(_field(order, "quantity", "qty"), "option order quantity")
        action = _text(_field(order, "action", "transaction_type")).upper()
        if quantity <= 0 or action not in {"BUY", "SELL"}:
            raise PortfolioSafetyStateError("Invalid option order quantity or action")
        merge(order, quantity if action == "BUY" else -quantity)

    return [
        aggregated[key]
        for key in sorted(aggregated)
        if aggregated[key]["quantity"] != 0
    ]


def _greek_identity(row: Any) -> str:
    instrument_id = _greek_instrument_id(row)
    if instrument_id:
        return instrument_id
    return _greek_symbol_identity(row)


def _greek_instrument_id(row: Any) -> str:
    return _text(
        _field(row, "instrument_id", "instrument_token", "security_id", "securityId")
    )


def _greek_symbol_identity(row: Any) -> str:
    symbol = _text(_field(row, "symbol", "trading_symbol", "tradingsymbol"))
    exchange = _text(_field(row, "exchange")).upper()
    if not symbol or not exchange:
        raise PortfolioSafetyStateError("Incomplete option Greek identity")
    return f"{exchange}:{symbol}"


async def _portfolio_greeks(
    source: _AccountSource,
    raw_positions: Any,
    proposed_orders: list[Any] | tuple[Any, ...] = (),
    *,
    resolved_identities: dict[str, str] | None = None,
) -> tuple[float, float]:
    option_positions = _option_risk_positions(raw_positions, proposed_orders)
    if not option_positions:
        return 0.0, 0.0
    try:
        raw_greeks = await _read(
            source,
            "portfolio_greeks",
            "portfolio_greeks",
            option_positions,
        )
    except PortfolioSafetyStateError:
        raise
    except Exception as exc:
        raise PortfolioSafetyStateError("Authoritative option Greeks are unavailable") from exc

    expected: dict[str, dict[str, Any]] = {}
    symbol_resolvable: set[str] = set()
    resolved_identities = resolved_identities if resolved_identities is not None else {}
    resolved_symbols = {
        instrument_id: symbol_identity
        for symbol_identity, instrument_id in resolved_identities.items()
    }
    if len(resolved_symbols) != len(resolved_identities):
        raise PortfolioSafetyStateError("Option Greeks lack a unique resolved instrument identity")

    def register_resolved_identity(symbol_identity: str, instrument_id: str) -> None:
        if not instrument_id:
            return
        existing_id = resolved_identities.get(symbol_identity)
        if existing_id and existing_id != instrument_id:
            raise PortfolioSafetyStateError("Option Greeks have an inconsistent resolved instrument identity")
        existing_symbol = resolved_symbols.get(instrument_id)
        if existing_symbol and existing_symbol != symbol_identity:
            raise PortfolioSafetyStateError("Option Greeks lack a unique resolved instrument identity")
        resolved_identities[symbol_identity] = instrument_id
        resolved_symbols[instrument_id] = symbol_identity

    for position in option_positions:
        symbol_identity = f"{position['exchange']}:{position['symbol']}"
        identity = position["instrument_id"] or symbol_identity
        if identity in expected:
            raise PortfolioSafetyStateError("Duplicate option position identity")
        expected[identity] = position
        if position["instrument_id"]:
            register_resolved_identity(symbol_identity, position["instrument_id"])
        else:
            symbol_resolvable.add(symbol_identity)

    actual: dict[str, Any] = {}
    for row in _rows(raw_greeks, "data", "greeks"):
        returned_instrument_id = _greek_instrument_id(row)
        symbol_identity = _greek_symbol_identity(row)
        if returned_instrument_id and returned_instrument_id in expected:
            identity = returned_instrument_id
        elif symbol_identity in symbol_resolvable:
            if not source.openalgo and not returned_instrument_id:
                raise PortfolioSafetyStateError(
                    "Native option Greeks lack an adapter-resolved instrument identity"
                )
            register_resolved_identity(symbol_identity, returned_instrument_id)
            identity = symbol_identity
        else:
            identity = returned_instrument_id or symbol_identity
        if identity not in expected:
            raise PortfolioSafetyStateError("Option Greek response does not cover the complete option portfolio")
        expected_position = expected[identity]
        expected_symbol = f"{expected_position['exchange']}:{expected_position['symbol']}"
        if symbol_identity != expected_symbol:
            raise PortfolioSafetyStateError("Option Greek response conflicts with the option portfolio identity")
        if identity in actual:
            raise PortfolioSafetyStateError("Duplicate option Greek identity")
        actual[identity] = row
    if set(actual) != set(expected):
        raise PortfolioSafetyStateError("Option Greek response does not cover the complete option portfolio")

    net_delta = 0.0
    net_vega = 0.0
    for identity, position in expected.items():
        row = actual[identity]
        delta = _finite_number(_field(row, "delta"), "option Greek delta")
        vega = _finite_number(_field(row, "vega"), "option Greek vega")
        net_delta += position["quantity"] * delta
        net_vega += position["quantity"] * vega
    if not math.isfinite(net_delta) or not math.isfinite(net_vega):
        raise PortfolioSafetyStateError("Non-finite aggregate option Greeks")
    return net_delta, net_vega


def _worst_case_component(seed: float, contributions: list[float]) -> float:
    """Return the largest absolute result from any independently executable subset."""
    lower = seed + sum(min(value, 0.0) for value in contributions)
    upper = seed + sum(max(value, 0.0) for value in contributions)
    return lower if abs(lower) > abs(upper) else upper


async def _greek_contributions(
    source: _AccountSource,
    raw_positions: Any,
    orders: list[Any],
) -> tuple[float, float, list[tuple[float, float]]]:
    """Return base Greeks and each order's standalone additive contribution."""
    option_order_seen = any(_canonical_option_type(order) for order in orders)
    option_position_seen = bool(_option_risk_positions(raw_positions))
    if not option_position_seen and not option_order_seen:
        return 0.0, 0.0, [(0.0, 0.0) for _order in orders]

    resolved_identities: dict[str, str] = {}
    base_delta, base_vega = await _portfolio_greeks(
        source,
        raw_positions,
        resolved_identities=resolved_identities,
    )
    contributions: list[tuple[float, float]] = []
    for order in orders:
        if not _canonical_option_type(order):
            contributions.append((0.0, 0.0))
            continue
        scenario_delta, scenario_vega = await _portfolio_greeks(
            source,
            raw_positions,
            [order],
            resolved_identities=resolved_identities,
        )
        contributions.append((scenario_delta - base_delta, scenario_vega - base_vega))
    return base_delta, base_vega, contributions


def _text(value: Any) -> str:
    return str(getattr(value, "value", value) or "").strip()


def _finite_number(value: Any, label: str) -> float:
    try:
        parsed = float(str(value).strip())
    except (TypeError, ValueError) as exc:
        raise PortfolioSafetyStateError(f"Invalid {label} in portfolio safety state") from exc
    if not math.isfinite(parsed):
        raise PortfolioSafetyStateError(f"Non-finite {label} in portfolio safety state")
    return parsed


def _position_key(row: Any) -> tuple[str, str, str] | None:
    symbol = _text(_field(row, "symbol", "trading_symbol", "tradingsymbol")).upper()
    exchange = _text(_field(row, "exchange")).upper()
    product = _text(_field(row, "product")).upper()
    if not symbol or not exchange or not product:
        return None
    return symbol, exchange, product


def _signed_order_quantity(order: Any) -> float:
    quantity = _finite_number(_field(order, "quantity", "qty"), "order quantity")
    action = _text(_field(order, "action", "transaction_type")).upper()
    if quantity <= 0 or not quantity.is_integer() or action not in {"BUY", "SELL"}:
        raise PortfolioSafetyStateError("Invalid order quantity or action in prospective safety state")
    return quantity if action == "BUY" else -quantity


def _position_quantity(positions: list[Any], key: tuple[str, str, str]) -> float:
    total = 0.0
    matched = False
    for position in positions:
        if _position_key(position) != key:
            continue
        total += _finite_number(_field(position, "quantity", "qty"), "position quantity")
        matched = True
    return total if matched else 0.0


def _order_increases_exposure(positions: list[Any], order: Any) -> bool:
    key = _position_key(order)
    if key is None:
        raise PortfolioSafetyStateError("Incomplete order identity in prospective safety state")
    current = _position_quantity(positions, key)
    prospective = current + _signed_order_quantity(order)
    return abs(prospective) > abs(current)


def _quantity_text(quantity: float) -> str:
    return str(int(quantity)) if quantity.is_integer() else str(quantity)


def _apply_order_to_positions(positions: list[Any], order: Any) -> list[Any]:
    key = _position_key(order)
    if key is None:
        raise PortfolioSafetyStateError("Incomplete order identity in prospective safety state")
    prospective_quantity = _position_quantity(positions, key) + _signed_order_quantity(order)
    updated = [position for position in positions if _position_key(position) != key]
    if prospective_quantity != 0:
        symbol, exchange, product = key
        updated.append(
            SimpleNamespace(
                symbol=symbol,
                exchange=exchange,
                product=product,
                quantity=_quantity_text(prospective_quantity),
            )
        )
    return updated


def _worst_case_positions(positions: list[Any], uncertain_orders: list[Any]) -> list[Any]:
    """Project the largest absolute quantity possible for each instrument.

    Resting and sibling batch legs can execute independently.  Netting their
    signed quantities would incorrectly credit a hedge that may reject or fill
    later, so each instrument chooses the most adverse positive or negative
    executable subset relative to the authoritative position.
    """
    projected = list(positions)
    grouped: dict[tuple[str, str, str], tuple[float, float]] = {}
    for order in uncertain_orders:
        key = _position_key(order)
        if key is None:
            raise PortfolioSafetyStateError("Incomplete order identity in prospective safety state")
        signed = _signed_order_quantity(order)
        positive, negative = grouped.get(key, (0.0, 0.0))
        grouped[key] = (
            positive + max(signed, 0.0),
            negative + min(signed, 0.0),
        )

    for key, (positive, negative) in grouped.items():
        current = _position_quantity(projected, key)
        candidates = (current, current + positive, current + negative)
        worst = max(candidates, key=lambda value: (abs(value), value))
        projected = [position for position in projected if _position_key(position) != key]
        if worst != 0:
            symbol, exchange, product = key
            projected.append(
                SimpleNamespace(
                    symbol=symbol,
                    exchange=exchange,
                    product=product,
                    quantity=_quantity_text(worst),
                )
            )
    return projected


def _order_margin_payload(order: Any) -> dict[str, Any]:
    return {
        "symbol": _text(_field(order, "symbol", "trading_symbol", "tradingsymbol")),
        "exchange": _text(_field(order, "exchange")).upper(),
        "action": _text(_field(order, "action", "transaction_type")).upper(),
        "quantity": _quantity_text(abs(_signed_order_quantity(order))),
        "product": _text(_field(order, "product")).upper(),
        "pricetype": _text(_field(order, "pricetype", "price_type", "order_type")).upper(),
        "price": _text(_field(order, "price")) or "0",
        "trigger_price": _text(_field(order, "trigger_price")) or "0",
    }


def _required_margin_value(raw: Any, *, allow_zero: bool = False) -> float:
    data = raw
    if isinstance(data, Mapping) and isinstance(data.get("data"), Mapping):
        data = data["data"]
    if not isinstance(data, Mapping):
        raise PortfolioSafetyStateError("Authoritative order margin response is invalid")
    for key in (
        "required_margin",
        "total_margin_required",
        "total_margin",
        "final_margin",
        "order_margin",
        "margin",
    ):
        value = data.get(key)
        if value in (None, ""):
            continue
        margin = _finite_number(value, "required order margin")
        if margin < 0 or (margin == 0 and not allow_zero):
            qualifier = "non-negative" if allow_zero else "positive"
            raise PortfolioSafetyStateError(
                f"Authoritative required order margin is not {qualifier}"
            )
        return margin
    raise PortfolioSafetyStateError("Authoritative required order margin is unavailable")


async def _required_order_margin(
    source: _AccountSource,
    order: Any,
    *,
    allow_zero: bool = False,
) -> float:
    try:
        if source.openalgo:
            reader = getattr(source.target, "margin", None)
            if not callable(reader):
                raise PortfolioSafetyStateError("Portfolio reader lacks margin")
            raw = await _maybe_await(reader([_order_margin_payload(order)]))
        else:
            raw = await _read(source, "margin", "margin_calculator", order)
    except PortfolioSafetyStateError:
        raise
    except Exception as exc:
        raise PortfolioSafetyStateError("Authoritative order margin is unavailable") from exc
    return _required_margin_value(raw, allow_zero=allow_zero)


def _rows(raw: Any, *container_keys: str) -> list[Any]:
    if raw is None:
        return []
    if isinstance(raw, Mapping):
        for key in container_keys:
            candidate = raw.get(key)
            if isinstance(candidate, (list, tuple)):
                return list(candidate)
        return [raw]
    if isinstance(raw, (list, tuple)):
        return list(raw)
    return [raw]


def _instrument_key(
    row: Any,
    *,
    source: str,
    default_product: str = "",
) -> tuple[str, str, str]:
    symbol = _text(_field(row, "symbol", "trading_symbol", "tradingsymbol"))
    exchange = _text(_field(row, "exchange")).upper()
    product = _text(_field(row, "product")).upper() or default_product
    if not symbol or not exchange or not product:
        raise PortfolioSafetyStateError(f"Incomplete {source} instrument identity")
    instrument_id = _text(
        _field(row, "instrument_id", "instrument_token", "security_id", "securityId")
    )
    identity = instrument_id or f"symbol:{symbol}"
    return exchange, identity, product


def _quote_key(row: Any) -> tuple[str, str]:
    symbol = _text(_field(row, "symbol", "trading_symbol", "tradingsymbol"))
    exchange = _text(_field(row, "exchange")).upper()
    if not symbol or not exchange:
        raise PortfolioSafetyStateError("Incomplete quote instrument identity")
    return exchange, symbol


def _optional_positive_number(row: Any, *keys: str) -> float | None:
    raw = _field(row, *keys)
    if raw in (None, ""):
        return None
    value = _finite_number(raw, keys[0].replace("_", " "))
    return value if value > 0 else None


def _optional_bool(row: Any, key: str) -> bool | None:
    raw = _field(row, key)
    if raw is None:
        return None
    if isinstance(raw, bool):
        return raw
    normalised = str(raw).strip().lower()
    if normalised in {"true", "1"}:
        return True
    if normalised in {"false", "0"}:
        return False
    raise PortfolioSafetyStateError(f"Invalid {key.replace('_', ' ')} in portfolio safety state")


def _merge_accounting_value(
    current: float | None,
    candidate: float | None,
    *,
    label: str,
) -> float | None:
    if candidate is None:
        return current
    if current is not None and not math.isclose(current, candidate, rel_tol=1e-6, abs_tol=0.01):
        raise PortfolioSafetyStateError(f"Conflicting {label} in portfolio safety state")
    return candidate


def _merge_accounting_flag(
    current: bool | None,
    candidate: bool | None,
    *,
    label: str,
) -> bool | None:
    if candidate is None:
        return current
    if current is not None and current is not candidate:
        raise PortfolioSafetyStateError(f"Conflicting {label} in portfolio safety state")
    return candidate


def _merge_instrument_accounting(instrument: _InstrumentLedger, row: Any) -> None:
    instrument.multiplier = _merge_accounting_value(
        instrument.multiplier,
        _optional_positive_number(row, "multiplier", "contract_multiplier"),
        label="contract multiplier",
    )
    instrument.fx_rate = _merge_accounting_value(
        instrument.fx_rate,
        _optional_positive_number(row, "fx_rate", "rbi_reference_rate", "rbiReferenceRate"),
        label="FX rate",
    )
    instrument.cross_currency = _merge_accounting_flag(
        instrument.cross_currency,
        _optional_bool(row, "cross_currency"),
        label="cross-currency marker",
    )
    instrument.previous_close = _merge_accounting_value(
        instrument.previous_close,
        (
            _optional_positive_number(row, "previous_close", "prev_close", "close_price")
            if _optional_bool(row, "previous_close_trusted") is True
            else None
        ),
        label="previous close",
    )


def _merge_symbol(instrument: _InstrumentLedger, row: Any) -> None:
    symbol = _text(_field(row, "symbol", "trading_symbol", "tradingsymbol"))
    if instrument.symbol and instrument.symbol != symbol:
        raise PortfolioSafetyStateError("Instrument identity maps to conflicting symbols")
    instrument.symbol = symbol


def _validate_ledger_identities(
    ledger: dict[tuple[str, str, str], _InstrumentLedger],
) -> None:
    by_symbol: dict[tuple[str, str, str], set[str]] = {}
    for (exchange, identity, product), instrument in ledger.items():
        key = (exchange, instrument.symbol, product)
        by_symbol.setdefault(key, set()).add(identity)
    if any(len(identities) > 1 for identities in by_symbol.values()):
        raise PortfolioSafetyStateError("Broker rows disagree on canonical instrument identity")


def _validate_delivery_accounting(
    ledger: dict[tuple[str, str, str], _InstrumentLedger],
) -> None:
    for (exchange, _identity, product), instrument in ledger.items():
        if exchange not in _CASH_EXCHANGES or product != "CNC":
            continue
        expected_day_delta = instrument.day_buy_quantity - instrument.day_sell_quantity
        if instrument.holding_seen and instrument.position_seen:
            if not instrument.holding_accounting_complete or not instrument.position_accounting_complete:
                raise PortfolioSafetyStateError("Delivery holding/position overlap lacks complete broker accounting")
            if instrument.overnight_quantity != 0:
                raise PortfolioSafetyStateError("Delivery position duplicates overnight holding inventory")
            if instrument.carry_forward_buy_quantity or instrument.carry_forward_sell_quantity:
                raise PortfolioSafetyStateError("Delivery position contains unexpected carry-forward quantities")
            if not math.isclose(instrument.position_quantity, expected_day_delta, abs_tol=1e-9):
                raise PortfolioSafetyStateError("Delivery position does not equal today's broker quantity delta")
            if not math.isclose(instrument.net_trade_quantity, expected_day_delta, abs_tol=1e-9):
                raise PortfolioSafetyStateError("Delivery trade book does not reconcile to the broker quantity delta")
        elif instrument.position_seen:
            if instrument.position_accounting_complete:
                if instrument.overnight_quantity != 0:
                    raise PortfolioSafetyStateError("Delivery position has overnight inventory but no holding row")
                if not math.isclose(instrument.position_quantity, expected_day_delta, abs_tol=1e-9):
                    raise PortfolioSafetyStateError("Delivery position does not equal today's broker quantity delta")
                if not math.isclose(instrument.net_trade_quantity, expected_day_delta, abs_tol=1e-9):
                    raise PortfolioSafetyStateError("Delivery trade book does not reconcile to the broker quantity delta")
            elif not math.isclose(
                instrument.position_quantity,
                instrument.net_trade_quantity,
                abs_tol=1e-9,
            ):
                raise PortfolioSafetyStateError("Unproven delivery position does not reconcile to current-day fills")


def _build_local_ledger(
    trades: Any,
    positions: Any,
    holdings: Any = (),
) -> dict[tuple[str, str, str], _InstrumentLedger]:
    ledger: dict[tuple[str, str, str], _InstrumentLedger] = {}
    for position in _rows(positions, "data", "positions", "net", "day"):
        key = _instrument_key(position, source="position")
        quantity = _finite_number(_field(position, "quantity", "qty", "net_quantity", "netQty"), "position quantity")
        instrument = ledger.setdefault(key, _InstrumentLedger())
        _merge_symbol(instrument, position)
        instrument.end_quantity += quantity
        instrument.position_quantity += quantity
        instrument.overnight_quantity += _finite_number(
            _field(position, "overnight_quantity") or 0,
            "overnight quantity",
        )
        instrument.day_buy_quantity += _finite_number(
            _field(position, "day_buy_quantity", "dayBuyQty") or 0,
            "day buy quantity",
        )
        instrument.day_sell_quantity += _finite_number(
            _field(position, "day_sell_quantity", "daySellQty") or 0,
            "day sell quantity",
        )
        instrument.carry_forward_buy_quantity += _finite_number(
            _field(position, "carry_forward_buy_quantity", "carryForwardBuyQty") or 0,
            "carry-forward buy quantity",
        )
        instrument.carry_forward_sell_quantity += _finite_number(
            _field(position, "carry_forward_sell_quantity", "carryForwardSellQty") or 0,
            "carry-forward sell quantity",
        )
        instrument.position_accounting_complete = (
            instrument.position_accounting_complete
            and bool(_field(position, "accounting_complete", "_emergency_accounting_complete"))
        )
        instrument.position_seen = True
        _merge_instrument_accounting(instrument, position)

    for holding in _rows(holdings, "data", "holdings"):
        key = _instrument_key(holding, source="holding", default_product="CNC")
        quantity = _finite_number(
            _field(holding, "quantity", "qty", "total_quantity", "totalQty"),
            "holding quantity",
        )
        if quantity < 0:
            raise PortfolioSafetyStateError("Holding quantity cannot be negative")
        instrument = ledger.setdefault(key, _InstrumentLedger())
        _merge_symbol(instrument, holding)
        instrument.end_quantity += quantity
        instrument.holding_quantity += quantity
        instrument.holding_accounting_complete = (
            instrument.holding_accounting_complete
            and bool(_field(holding, "accounting_complete"))
        )
        instrument.holding_seen = True
        _merge_instrument_accounting(instrument, holding)

    for trade in _rows(trades, "data", "trades", "tradebook"):
        key = _instrument_key(trade, source="trade")
        action = _text(_field(trade, "action", "transaction_type", "transactionType")).upper()
        if action not in {"BUY", "SELL"}:
            raise PortfolioSafetyStateError("Invalid trade action in portfolio safety state")
        quantity = _finite_number(_field(trade, "quantity", "qty", "traded_quantity"), "trade quantity")
        price = _finite_number(_field(trade, "price", "average_price", "traded_price"), "trade price")
        if quantity <= 0 or price <= 0:
            raise PortfolioSafetyStateError("Trade quantity and price must be positive")
        signed_quantity = quantity if action == "BUY" else -quantity
        instrument = ledger.setdefault(key, _InstrumentLedger())
        _merge_symbol(instrument, trade)
        _merge_instrument_accounting(instrument, trade)
        instrument.net_trade_quantity += signed_quantity
        instrument.fills.append((signed_quantity, price))
    _validate_ledger_identities(ledger)
    _validate_delivery_accounting(ledger)
    return ledger


def required_quote_symbols(trades: Any, positions: Any, holdings: Any = ()) -> list[str]:
    """Return sorted ``EXCHANGE:SYMBOL`` quotes needed for daily MTM."""
    ledger = _build_local_ledger(trades, positions, holdings)
    required = {
        (exchange, instrument.symbol)
        for (exchange, _identity, _product), instrument in ledger.items()
        if instrument.end_quantity != 0.0
        or instrument.end_quantity - instrument.net_trade_quantity != 0.0
    }
    return [f"{exchange}:{symbol}" for exchange, symbol in sorted(required)]


def required_previous_close_symbols(trades: Any, positions: Any, holdings: Any = ()) -> list[str]:
    """Return instruments whose opening quantity lacks a trusted prior close."""
    ledger = _build_local_ledger(trades, positions, holdings)
    required = {
        (exchange, instrument.symbol)
        for (exchange, _identity, _product), instrument in ledger.items()
        if instrument.end_quantity - instrument.net_trade_quantity != 0.0
        and instrument.previous_close is None
    }
    return [f"{exchange}:{symbol}" for exchange, symbol in sorted(required)]


def _required_order_quote_symbols(orders: Any) -> list[str]:
    required: set[tuple[str, str]] = set()
    for order in orders or ():
        pricetype = _text(_field(order, "pricetype", "price_type", "order_type")).upper()
        if pricetype not in {"LIMIT", "SL"}:
            continue
        symbol = _text(_field(order, "symbol", "trading_symbol", "tradingsymbol"))
        exchange = _text(_field(order, "exchange")).upper()
        if not symbol or not exchange:
            raise PortfolioSafetyStateError("Incomplete order identity for LTP safety check")
        required.add((exchange, symbol))
    return [f"{exchange}:{symbol}" for exchange, symbol in sorted(required)]


def _instrument_factor(
    key: tuple[str, str, str],
    instrument: _InstrumentLedger,
) -> float:
    exchange, _identity, _product = key
    symbol = instrument.symbol
    multiplier = instrument.multiplier
    if multiplier is None:
        if exchange not in _CASH_EXCHANGES:
            raise PortfolioSafetyStateError(
                f"Missing contract multiplier for {exchange}:{symbol}"
            )
        multiplier = 1.0
    if exchange in _CASH_EXCHANGES:
        fx_rate = 1.0
    elif instrument.cross_currency is None:
        raise PortfolioSafetyStateError(
            f"Missing settlement-currency provenance for {exchange}:{symbol}"
        )
    elif instrument.cross_currency:
        if instrument.fx_rate is None:
            raise PortfolioSafetyStateError(f"Missing cross-currency FX rate for {exchange}:{symbol}")
        fx_rate = instrument.fx_rate
    else:
        fx_rate = 1.0
    factor = multiplier * fx_rate
    if not math.isfinite(factor) or factor <= 0:
        raise PortfolioSafetyStateError(f"Invalid accounting factor for {exchange}:{symbol}")
    return factor


def compute_local_daily_pnl(
    trades: Any,
    positions: Any,
    quotes: Any,
    holdings: Any = (),
) -> float:
    """Compute current-day MTM locally from fills, positions, and market prices.

    For each instrument, the opening quantity is inferred as current quantity
    minus today's signed fills. Daily P&L is then::

        (current_qty * ltp - opening_qty * previous_close - signed_trade_cash_flow)
        * contract_multiplier * fx_rate

    Broker-supplied aggregate ``pnl`` fields are deliberately never read.
    """
    ledger = _build_local_ledger(trades, positions, holdings)
    quote_map: dict[tuple[str, str], Any] = {}
    for quote in _rows(quotes, "data", "quotes"):
        key = _quote_key(quote)
        if key in quote_map:
            raise PortfolioSafetyStateError("Duplicate quote in portfolio safety state")
        quote_map[key] = quote

    total = 0.0
    for key, instrument in ledger.items():
        exchange, _identity, _product = key
        symbol = instrument.symbol
        opening_quantity = instrument.end_quantity - instrument.net_trade_quantity
        quote = quote_map.get((exchange, symbol))
        ltp = 0.0
        previous_close = 0.0
        if instrument.end_quantity != 0.0:
            if quote is None:
                raise PortfolioSafetyStateError(f"Missing quote for {exchange}:{symbol}")
            ltp = _finite_number(_field(quote, "ltp", "last_price", "last_traded_price"), "quote LTP")
            if ltp <= 0:
                raise PortfolioSafetyStateError(f"Invalid quote LTP for {exchange}:{symbol}")
        if opening_quantity != 0.0:
            if quote is None:
                raise PortfolioSafetyStateError(f"Missing quote for {exchange}:{symbol}")
            quote_previous_close = (
                _optional_positive_number(quote, "prev_close", "previous_close")
                if _optional_bool(quote, "previous_close_trusted") is True
                else None
            )
            previous_close = _merge_accounting_value(
                instrument.previous_close,
                quote_previous_close,
                label="previous close",
            ) or 0.0
            if previous_close <= 0:
                raise PortfolioSafetyStateError(f"Invalid previous close for {exchange}:{symbol}")
        factor = _instrument_factor(key, instrument)
        signed_trade_cash_flow = sum(quantity * price for quantity, price in instrument.fills)
        contribution = factor * (
            instrument.end_quantity * ltp
            - opening_quantity * previous_close
            - signed_trade_cash_flow
        )
        total += contribution
    if not math.isfinite(total):
        raise PortfolioSafetyStateError("Computed daily P&L is non-finite")
    return total


def _resolve_account_source(
    config: Mapping[str, Any],
    adapter_id: str,
    account_id: str,
) -> _AccountSource:
    if adapter_id == "openalgo":
        if account_id != "default":
            raise PortfolioSafetyStateError(
                "OpenAlgo exposes one configured account; non-default account selectors are unavailable"
            )
        client = config.get("OPENALGO_CLIENT")
        if client is None:
            raise PortfolioSafetyStateError("OpenAlgo portfolio reader is unavailable")
        return _AccountSource(client, openalgo=True)

    adapter = (config.get("NATIVE_ADAPTERS") or {}).get(adapter_id)
    registry = config.get("REGISTRY")
    if adapter is None or registry is None:
        raise PortfolioSafetyStateError("Native portfolio reader is unavailable")
    try:
        session = registry.get_session_for(adapter_id, account_id)
    except Exception as exc:
        raise PortfolioSafetyStateError("Native account session is unavailable") from exc
    return _AccountSource(adapter, session=session)


async def _read(source: _AccountSource, openalgo_name: str, native_name: str, *args: Any) -> Any:
    method_name = openalgo_name if source.openalgo else native_name
    reader = getattr(source.target, method_name, None)
    if not callable(reader):
        raise PortfolioSafetyStateError(f"Portfolio reader lacks {method_name}")
    call_args = args if source.openalgo else (source.session, *args)
    return await _maybe_await(reader(*call_args))


_ACTIVE_ORDER_STATUSES = frozenset({
    "ACTIVE",
    "AFTER MARKET ORDER REQ RECEIVED",
    "AMO REQ RECEIVED",
    "MODIFY PENDING",
    "MODIFY VALIDATION PENDING",
    "OPEN",
    "PARTIAL",
    "PARTIALLY FILLED",
    "PENDING",
    "PUT ORDER REQ RECEIVED",
    "TRANSIT",
    "TRIGGER PENDING",
    "TRIGGER_PENDING",
    "VALIDATION PENDING",
})

_TERMINAL_ORDER_STATUSES = frozenset({
    "CANCELED",
    "CANCELLED",
    "CLOSED",
    "COMPLETE",
    "COMPLETED",
    "DELETED",
    "DISABLED",
    "EXPIRED",
    "FILLED",
    "REJECTED",
    "TRADED",
})

_ORDER_READERS = {
    "regular": ("orderbook", "order_book"),
    "forever": ("gtt_orderbook", "forever_orders"),
    "super": ("", "super_orders"),
}


def _order_record_id(row: Any) -> str:
    return _text(
        _field(
            row,
            "orderid",
            "order_id",
            "orderId",
            "trigger_id",
            "alert_id",
            "id",
        )
    )


def _order_record_value(row: Any, fallback: Any, *keys: str) -> Any:
    value = _field(row, *keys)
    if value not in (None, ""):
        return value
    return _field(fallback, *keys) if fallback is not None else value


def _select_super_leg(parent: Any, changes: Mapping[str, Any]) -> tuple[Any, Any]:
    leg_name = _text(changes.get("leg_name") or "ENTRY_LEG").upper()
    if leg_name == "ENTRY_LEG":
        return parent, None
    if leg_name not in {"TARGET_LEG", "STOP_LOSS_LEG"}:
        raise PortfolioSafetyStateError("Super-order modify has an invalid leg name")
    legs = _rows(_field(parent, "legs", "leg_details", "legDetails"), "data", "legs")
    matched = [
        leg
        for leg in legs
        if _text(_field(leg, "leg_name", "legName")).upper() == leg_name
    ]
    if len(matched) != 1:
        raise PortfolioSafetyStateError("Authoritative super-order leg is unavailable")
    return matched[0], parent


def _normalise_authoritative_order(row: Any, fallback: Any = None) -> dict[str, Any]:
    return {
        "status": _text(_order_record_value(row, fallback, "status", "order_status", "orderStatus")).upper(),
        "symbol": _text(
            _order_record_value(row, fallback, "symbol", "trading_symbol", "tradingsymbol", "tradingSymbol")
        ),
        "exchange": _text(_order_record_value(row, fallback, "exchange", "exchange_segment")).upper(),
        "action": _text(
            _order_record_value(row, fallback, "action", "transaction_type", "transactionType")
        ).upper(),
        "product": _text(_order_record_value(row, fallback, "product", "product_type", "productType")).upper(),
        "quantity": _order_record_value(row, fallback, "quantity", "qty", "order_quantity"),
        "filled_quantity": _order_record_value(
            row,
            fallback,
            "filled_quantity",
            "filled_qty",
            "filledQty",
            "tradedQty",
        ),
        "pricetype": _text(
            _order_record_value(row, fallback, "pricetype", "price_type", "order_type", "orderType")
        ).upper(),
        "price": _order_record_value(row, fallback, "price") or 0,
        "trigger_price": _order_record_value(row, fallback, "trigger_price", "triggerPrice") or 0,
    }


def _active_unfilled_orders(raw_orders: Any) -> list[Any]:
    """Return validated remaining exposure from accepted non-terminal orders."""
    pending: list[Any] = []
    seen_ids: set[str] = set()
    for row in _rows(raw_orders, "data", "orders", "orderbook", "order_book"):
        status = _text(_field(row, "status", "order_status", "orderStatus")).upper()
        if not status:
            raise PortfolioSafetyStateError("Authoritative order status is unavailable")
        if status in _TERMINAL_ORDER_STATUSES:
            continue
        order_id = _order_record_id(row)
        if not order_id:
            raise PortfolioSafetyStateError("Authoritative active order id is unavailable")
        if order_id in seen_ids:
            raise PortfolioSafetyStateError("Authoritative order book contains a duplicate order id")
        seen_ids.add(order_id)

        current = _normalise_authoritative_order(row)
        required = ("symbol", "exchange", "action", "product", "quantity")
        if any(current[field] in (None, "") for field in required):
            raise PortfolioSafetyStateError("Authoritative active order is incomplete")
        quantity = _finite_number(current["quantity"], "authoritative order quantity")
        filled_quantity = _finite_number(current["filled_quantity"], "authoritative filled quantity")
        if (
            quantity <= 0
            or filled_quantity < 0
            or filled_quantity > quantity
            or not quantity.is_integer()
            or not filled_quantity.is_integer()
        ):
            raise PortfolioSafetyStateError("Authoritative active order quantity is inconsistent")
        remaining = quantity - filled_quantity
        if remaining == 0:
            continue

        pending.append(
            SimpleNamespace(
                order_id=order_id,
                symbol=current["symbol"],
                instrument_id=_text(
                    _field(row, "instrument_id", "instrument_token", "security_id", "securityId")
                ),
                exchange=current["exchange"],
                action=current["action"],
                product=current["product"],
                quantity=_quantity_text(remaining),
                pricetype=current["pricetype"] or "MARKET",
                price=str(current["price"]),
                trigger_price=str(current["trigger_price"]),
                option_type=_text(_field(row, "option_type", "drvOptionType", "instrument_type")),
                expiry=_text(_field(row, "expiry", "expiry_date", "drvExpiryDate")),
                strike_price=_field(row, "strike_price", "strike", "drvStrikePrice"),
                underlying=_text(_field(row, "underlying", "underlying_symbol")),
                margin_unfunded=bool(_field(row, "margin_unfunded")),
            )
        )
    return pending


_ZERO_FILL_TERMINAL_STATUSES = frozenset({
    "CANCELED",
    "CANCELLED",
    "CLOSED",
    "DELETED",
    "DISABLED",
    "EXPIRED",
    "REJECTED",
})


def _same_order_identity(authoritative: Mapping[str, Any], order: Any) -> bool:
    return (
        authoritative["symbol"].upper()
        == _text(_field(order, "symbol", "trading_symbol", "tradingsymbol")).upper()
        and authoritative["exchange"] == _text(_field(order, "exchange")).upper()
        and authoritative["product"] == _text(_field(order, "product")).upper()
        and authoritative["action"] == _text(_field(order, "action", "transaction_type")).upper()
    )


def _reservation_fill_is_represented(reservation: Any, positions: Any, filled_quantity: float) -> bool:
    order = getattr(reservation, "order", None)
    key = _position_key(order)
    if key is None:
        raise PortfolioSafetyStateError("Local order reservation lacks canonical instrument identity")
    try:
        starting_quantity = float(getattr(reservation, "starting_quantity"))
    except (TypeError, ValueError) as exc:
        raise PortfolioSafetyStateError("Local order reservation has invalid starting quantity") from exc
    if not math.isfinite(starting_quantity):
        raise PortfolioSafetyStateError("Local order reservation has non-finite starting quantity")
    action = _text(_field(order, "action", "transaction_type")).upper()
    if action not in {"BUY", "SELL"}:
        raise PortfolioSafetyStateError("Local order reservation has invalid action")
    signed_fill = filled_quantity if action == "BUY" else -filled_quantity
    current_quantity = _position_quantity(normalise_l2_positions(positions), key)
    if signed_fill > 0:
        return current_quantity >= starting_quantity + signed_fill
    return current_quantity <= starting_quantity + signed_fill


def _project_unresolved_reservations(
    reservations: list[Any] | tuple[Any, ...],
    snapshot: _AccountingSnapshot,
) -> tuple[list[Any], tuple[str, ...]]:
    """Keep locally dispatched exposure until broker state proves its outcome."""
    rows = _rows(snapshot.orders, "data", "orders", "orderbook", "order_book")
    by_order_id: dict[str, list[Any]] = {}
    for row in rows:
        order_id = _order_record_id(row)
        if order_id:
            by_order_id.setdefault(order_id, []).append(row)

    projected: list[Any] = []
    reconciled: list[str] = []
    for reservation in reservations:
        reservation_id = _text(getattr(reservation, "reservation_id", ""))
        order = getattr(reservation, "order", None)
        if not reservation_id or order is None:
            raise PortfolioSafetyStateError("Local order reservation is invalid")
        broker_order_id = _text(getattr(reservation, "broker_order_id", ""))
        matches = by_order_id.get(broker_order_id, []) if broker_order_id else []
        if len(matches) > 1:
            raise PortfolioSafetyStateError("Authoritative order book contains a duplicate reserved order id")
        if not matches:
            parent_order_id, separator, leg_index = broker_order_id.rpartition(":")
            parent_matches = by_order_id.get(parent_order_id, []) if separator and leg_index.isdigit() else []
            if len(parent_matches) > 1:
                raise PortfolioSafetyStateError(
                    "Authoritative order book contains a duplicate reserved parent order id"
                )
            if parent_matches and _text(_field(parent_matches[0], "order_family")).lower() == "conditional":
                parent = _normalise_authoritative_order(parent_matches[0])
                parent_status = parent["status"]
                if not parent_status:
                    raise PortfolioSafetyStateError("Authoritative reserved parent status is unavailable")
                if parent["filled_quantity"] in (None, ""):
                    projected.append(order)
                    continue
                parent_filled = _finite_number(
                    parent["filled_quantity"],
                    "authoritative reserved parent filled quantity",
                )
                if parent_filled < 0:
                    raise PortfolioSafetyStateError(
                        "Authoritative reserved parent filled quantity is inconsistent"
                    )
                if parent_status in _ZERO_FILL_TERMINAL_STATUSES and parent_filled == 0:
                    reconciled.append(reservation_id)
                    continue
            projected.append(order)
            continue

        authoritative = _normalise_authoritative_order(matches[0])
        status = authoritative["status"]
        if not status:
            raise PortfolioSafetyStateError("Authoritative reserved order status is unavailable")
        if authoritative["filled_quantity"] in (None, ""):
            projected.append(order)
            continue
        filled_quantity = _finite_number(
            authoritative["filled_quantity"],
            "authoritative reserved filled quantity",
        )
        if filled_quantity < 0:
            raise PortfolioSafetyStateError("Authoritative reserved filled quantity is inconsistent")
        # A unique broker id ending in a no-fill terminal state proves that the
        # dispatched intent created no exposure even when the broker omits the
        # rejected/cancelled row's instrument fields.
        if status in _ZERO_FILL_TERMINAL_STATUSES and filled_quantity == 0:
            reconciled.append(reservation_id)
            continue
        if not _same_order_identity(authoritative, order):
            raise PortfolioSafetyStateError("Authoritative reserved order identity changed")
        quantity = _finite_number(authoritative["quantity"], "authoritative reserved order quantity")
        if quantity <= 0 or filled_quantity < 0 or filled_quantity > quantity:
            raise PortfolioSafetyStateError("Authoritative reserved order quantity is inconsistent")
        if filled_quantity > 0 and not _reservation_fill_is_represented(
            reservation,
            snapshot.positions,
            filled_quantity,
        ):
            projected.append(order)
            continue
        if status in _ACTIVE_ORDER_STATUSES:
            # The authoritative active row already contributes its remaining
            # quantity to the pending-order horizon. Keep the reservation so a
            # subsequent terminal/disappearing row cannot reopen admission
            # before the resulting position has propagated.
            continue
        if status in _ZERO_FILL_TERMINAL_STATUSES:
            reconciled.append(reservation_id)
            continue
        if status in _TERMINAL_ORDER_STATUSES and filled_quantity == quantity:
            reconciled.append(reservation_id)
            continue
        projected.append(order)
    return projected, tuple(reconciled)


def _replacement_order_fields(current: Mapping[str, Any], changes: Mapping[str, Any]) -> dict[str, Any]:
    def changed(default_key: str, *aliases: str) -> Any:
        for key in (default_key, *aliases):
            if key in changes:
                return changes[key]
        return current[default_key]

    fields = {
        "symbol": changed("symbol", "trading_symbol", "tradingsymbol"),
        "exchange": changed("exchange"),
        "action": changed("action", "transaction_type"),
        "product": changed("product"),
        "quantity": changed("quantity", "qty"),
        "pricetype": changed("pricetype", "price_type", "order_type"),
        "price": changed("price"),
        "trigger_price": changed("trigger_price"),
    }
    for field_name in ("symbol", "quantity", "price", "trigger_price"):
        fields[field_name] = str(fields[field_name])
    return fields


def _validated_order_quantities(current: Mapping[str, Any], proposed: Any) -> tuple[float, float]:
    current_quantity = _finite_number(current["quantity"], "authoritative order quantity")
    filled_quantity = _finite_number(current["filled_quantity"], "authoritative filled quantity")
    proposed_quantity = _finite_number(_field(proposed, "quantity"), "replacement order quantity")
    if any(not quantity.is_integer() for quantity in (current_quantity, filled_quantity, proposed_quantity)):
        raise PortfolioSafetyStateError("Modify-order quantities must be whole numbers")
    if current_quantity <= 0 or filled_quantity < 0 or filled_quantity > current_quantity:
        raise PortfolioSafetyStateError("Authoritative order quantity is inconsistent")
    if proposed_quantity <= 0 or proposed_quantity < filled_quantity:
        raise PortfolioSafetyStateError("Replacement quantity is inconsistent with filled quantity")
    return current_quantity, proposed_quantity


async def classify_modify_intent(
    config: Mapping[str, Any],
    adapter_id: str,
    order_id: str,
    changes: Mapping[str, Any],
    *,
    account_id: str = "default",
    family: str = "regular",
) -> ModifySafetyIntent:
    """Prove whether a replacement can increase exposure or reserved margin."""
    from flinttrade_core.models import Order  # noqa: PLC0415

    readers = _ORDER_READERS.get(family)
    if readers is None:
        raise PortfolioSafetyStateError("Unknown modify-order family")
    source = _resolve_account_source(config, adapter_id, account_id)
    openalgo_reader, native_reader = readers
    if source.openalgo and not openalgo_reader:
        raise PortfolioSafetyStateError("Authoritative modify-order reader is unavailable")
    raw_orders = await _read(source, openalgo_reader, native_reader)
    rows = _rows(raw_orders, "data", "orders", "orderbook", "order_book")
    matches = [row for row in rows if _order_record_id(row) == str(order_id)]
    if len(matches) != 1:
        raise PortfolioSafetyStateError("Authoritative open order is unavailable")

    selected, fallback = (
        _select_super_leg(matches[0], changes)
        if family == "super"
        else (matches[0], None)
    )
    current = _normalise_authoritative_order(selected, fallback)
    if current["status"] not in _ACTIVE_ORDER_STATUSES:
        raise PortfolioSafetyStateError("Authoritative order is not active and modifiable")
    required = ("symbol", "exchange", "action", "product", "quantity", "pricetype")
    if any(current[field] in (None, "") for field in required):
        raise PortfolioSafetyStateError("Authoritative open order is incomplete")

    try:
        current_order = Order(**_replacement_order_fields(current, {}))
        proposed_order = Order(**_replacement_order_fields(current, changes))
    except Exception as exc:
        raise PortfolioSafetyStateError("Replacement order cannot be classified") from exc
    current_quantity, proposed_quantity = _validated_order_quantities(current, proposed_order)

    current_margin, proposed_margin = await asyncio.gather(
        _required_order_margin(source, current_order, allow_zero=True),
        _required_order_margin(source, proposed_order, allow_zero=True),
    )
    identity_fields = ("symbol", "exchange", "action", "product")
    same_exposure = all(
        _text(_field(current_order, field)).upper()
        == _text(_field(proposed_order, field)).upper()
        for field in identity_fields
    )
    no_increase = (
        same_exposure
        and proposed_quantity <= current_quantity
        and proposed_margin <= current_margin + 1e-9
    )
    return ModifySafetyIntent(
        proposed_order=proposed_order,
        risk_increasing=not no_increase,
        margin_delta=max(proposed_margin - current_margin, 0.0),
    )


async def gather_required_order_margin(
    config: Mapping[str, Any],
    adapter_id: str,
    order: Any,
    *,
    account_id: str = "default",
    allow_zero: bool = False,
) -> float:
    """Return one selector-bound authoritative pre-trade margin estimate."""
    source = _resolve_account_source(config, adapter_id, account_id)
    return await _required_order_margin(source, order, allow_zero=allow_zero)


async def gather_authoritative_positions(
    config: Mapping[str, Any],
    adapter_id: str,
    *,
    account_id: str = "default",
) -> list[Any]:
    """Return one stable, strictly validated selector-scoped position snapshot.

    This deliberately does not compute daily P&L or portfolio Greeks. It is
    used only to prove that a non-order broker verb (currently product
    conversion) targets an existing position before deciding whether the verb
    can increase risk. Any transition that is not independently proven
    non-increasing must still gather the complete :func:`gather_safety_state`
    snapshot before dispatch.
    """
    source = _resolve_account_source(config, adapter_id, account_id)
    previous: Any = None
    stable: Any = None
    try:
        for attempt in range(_SNAPSHOT_ATTEMPTS):
            current = await _read(source, "positionbook", "positions")
            if attempt and _fingerprint_rows(previous, "position") == _fingerprint_rows(current, "position"):
                stable = current
                break
            previous = current
            await asyncio.sleep(0)
    except PortfolioSafetyStateError:
        raise
    except Exception as exc:
        raise PortfolioSafetyStateError("Authoritative position snapshot is unavailable") from exc
    if stable is None:
        raise PortfolioSafetyStateError("Portfolio positions changed during snapshot")

    positions: list[Any] = []
    for row in _rows(stable, "data", "positions", "net", "day"):
        symbol = _text(_field(row, "symbol", "trading_symbol", "tradingsymbol"))
        exchange = _text(_field(row, "exchange")).upper()
        product = _text(_field(row, "product")).upper()
        quantity = _finite_number(
            _field(row, "quantity", "qty", "net_quantity", "netQty", "net_qty", "netqty"),
            "authoritative position quantity",
        )
        if not symbol or not exchange or not product:
            raise PortfolioSafetyStateError("Authoritative position identity is incomplete")
        if not quantity.is_integer():
            raise PortfolioSafetyStateError("Authoritative position quantity must be a whole number")
        positions.append(
            SimpleNamespace(
                symbol=symbol,
                exchange=exchange,
                product=product,
                quantity=_quantity_text(quantity),
            )
        )
    return positions


def _fingerprint_rows(raw: Any, kind: str) -> tuple[tuple[str, ...], ...]:
    fields_by_kind = {
        "position": (
            "symbol", "instrument_id", "instrument_token", "security_id", "exchange", "product",
            "quantity", "overnight_quantity",
            "day_buy_quantity", "day_sell_quantity", "multiplier", "fx_rate",
            "cross_currency", "previous_close_trusted",
            "carry_forward_buy_quantity", "carry_forward_sell_quantity", "accounting_complete",
            "option_type", "expiry", "strike_price", "underlying",
            "previous_close", "prev_close", "close_price",
        ),
        "holding": (
            "symbol", "instrument_id", "instrument_token", "security_id", "exchange", "product",
            "quantity", "settled_quantity", "t1_quantity", "accounting_complete", "multiplier", "fx_rate",
            "cross_currency", "previous_close_trusted",
            "previous_close", "prev_close", "close_price",
        ),
        "trade": (
            "orderid", "symbol", "instrument_id", "instrument_token", "security_id", "exchange",
            "product", "action", "quantity", "price",
            "timestamp", "multiplier", "fx_rate",
            "cross_currency",
        ),
        "order": (
            "orderid", "order_id", "orderId", "status", "order_status", "orderStatus",
            "safety_order_id", "broker_order_id", "raw_broker_order_id", "order_family",
            "symbol", "trading_symbol", "tradingsymbol", "instrument_id", "instrument_token",
            "security_id", "exchange", "product", "action", "transaction_type", "quantity",
            "filled_quantity", "filled_qty", "filledQty", "tradedQty", "pricetype", "price_type",
            "order_type", "price", "trigger_price", "option_type", "expiry", "strike_price",
            "underlying", "leg_name", "parent_order_id", "exchange_order_id", "margin_unfunded",
        ),
    }
    container_keys = {
        "position": ("data", "positions", "net", "day"),
        "holding": ("data", "holdings"),
        "trade": ("data", "trades", "tradebook"),
        "order": ("data", "orders", "orderbook", "order_book"),
    }
    rows = _rows(raw, *container_keys[kind])
    return tuple(sorted(tuple(_text(_field(row, field)) for field in fields_by_kind[kind]) for row in rows))


def _snapshot_fingerprint(snapshot: _AccountingSnapshot) -> tuple[tuple[tuple[str, ...], ...], ...]:
    return (
        _fingerprint_rows(snapshot.positions, "position"),
        _fingerprint_rows(snapshot.trades, "trade"),
        _fingerprint_rows(snapshot.holdings, "holding"),
        _fingerprint_rows(snapshot.orders, "order"),
    )


async def _read_accounting_snapshot(source: _AccountSource) -> _AccountingSnapshot:
    order_reader = "order_book"
    if not source.openalgo:
        class_reader = getattr(type(source.target), "safety_order_book", None)
        instance_reader = vars(source.target).get("safety_order_book")
        if callable(class_reader) or callable(instance_reader):
            order_reader = "safety_order_book"
    if not source.openalgo and bool(
        getattr(source.target, "safety_snapshot_requires_serial_reads", False)
    ):
        positions = await _read(source, "positionbook", "positions")
        trades = await _read(source, "tradebook", "trade_book")
        holdings = await _read(source, "holdings", "holdings")
        orders = await _read(source, "orderbook", order_reader)
    else:
        positions, trades, holdings, orders = await asyncio.gather(
            _read(source, "positionbook", "positions"),
            _read(source, "tradebook", "trade_book"),
            _read(source, "holdings", "holdings"),
            _read(source, "orderbook", order_reader),
        )
    return _AccountingSnapshot(positions=positions, trades=trades, holdings=holdings, orders=orders)


async def _read_stable_accounting_snapshot(source: _AccountSource) -> _AccountingSnapshot:
    previous = await _read_accounting_snapshot(source)
    for _attempt in range(1, _SNAPSHOT_ATTEMPTS):
        current = await _read_accounting_snapshot(source)
        if _snapshot_fingerprint(previous) == _snapshot_fingerprint(current):
            return current
        previous = current
        await asyncio.sleep(0)
    raise PortfolioSafetyStateError("Portfolio positions, holdings, and fills changed during snapshot")


def _history_rows(raw: Any) -> list[Any]:
    bars = getattr(raw, "bars", None)
    if isinstance(bars, (list, tuple)):
        return list(bars)
    if isinstance(raw, Mapping):
        for key in ("bars", "data", "candles"):
            candidate = raw.get(key)
            if isinstance(candidate, (list, tuple)):
                return list(candidate)
    if isinstance(raw, (list, tuple)):
        return list(raw)
    return []


async def _history_previous_close(
    source: _AccountSource,
    *,
    exchange: str,
    symbol: str,
    expected_date: date,
) -> tuple[float, str]:
    start_date = (expected_date - timedelta(days=14)).isoformat()
    end_date = (expected_date - timedelta(days=1)).isoformat()
    if source.openalgo:
        reader = getattr(source.target, "history", None)
        if not callable(reader):
            raise PortfolioSafetyStateError("OpenAlgo daily-history reader is unavailable")
        raw = await _maybe_await(reader(symbol, exchange, "D", start_date, end_date))
    else:
        reader = getattr(source.target, "historical", None)
        if not callable(reader):
            raise PortfolioSafetyStateError("Native daily-history reader is unavailable")
        raw = await _maybe_await(reader(source.session, {
            "symbol": symbol,
            "exchange": exchange,
            "interval": "D",
            "from_date": start_date,
            "to_date": end_date,
        }))

    candidates: dict[date, float] = {}
    for bar in _history_rows(raw):
        timestamp = _trade_timestamp(
            _field(bar, "timestamp", "time", "date"),
            expected_date=expected_date,
            allow_time_only=False,
        )
        bar_date = timestamp.date()
        if bar_date >= expected_date:
            raise PortfolioSafetyStateError("Daily history includes a non-completed session")
        close = _finite_number(_field(bar, "close"), "historical close")
        if close <= 0:
            raise PortfolioSafetyStateError("Daily history contains an invalid close")
        previous = candidates.get(bar_date)
        if previous is not None and not math.isclose(previous, close, rel_tol=1e-6, abs_tol=0.01):
            raise PortfolioSafetyStateError("Daily history contains conflicting closes")
        candidates[bar_date] = close
    if not candidates:
        raise PortfolioSafetyStateError(f"Previous-session close is unavailable for {exchange}:{symbol}")
    latest_date = max(candidates)
    return candidates[latest_date], latest_date.isoformat()


def _quote_record(quote: Any) -> dict[str, Any]:
    if isinstance(quote, Mapping):
        return dict(quote)
    model_dump = getattr(quote, "model_dump", None)
    if callable(model_dump):
        return dict(model_dump())
    values = vars(quote) if hasattr(quote, "__dict__") else {}
    return dict(values)


def _symbols_missing_trusted_quote(quotes: Any, symbols: list[str]) -> list[str]:
    trusted: set[tuple[str, str]] = set()
    for quote in _rows(quotes, "data", "quotes"):
        if (
            _optional_bool(quote, "previous_close_trusted") is True
            and _optional_positive_number(quote, "prev_close", "previous_close") is not None
        ):
            trusted.add(_quote_key(quote))
    return [
        value
        for value in symbols
        if tuple(value.split(":", 1)) not in trusted
    ]


async def _backfill_previous_closes(
    source: _AccountSource,
    quotes: Any,
    symbols: list[str],
    *,
    expected_date: date,
) -> list[dict[str, Any]]:
    quote_rows = [_quote_record(quote) for quote in _rows(quotes, "data", "quotes")]
    by_key = {_quote_key(quote): quote for quote in quote_rows}
    for value in symbols:
        exchange, symbol = value.split(":", 1)
        quote = by_key.get((exchange, symbol))
        if quote is None:
            raise PortfolioSafetyStateError(f"Missing quote for {exchange}:{symbol}")
        close, as_of = await _history_previous_close(
            source,
            exchange=exchange,
            symbol=symbol,
            expected_date=expected_date,
        )
        quote["prev_close"] = close
        quote["previous_close_trusted"] = True
        quote["previous_close_as_of"] = as_of
    return quote_rows


def _trade_timestamp(value: Any, *, expected_date: date, allow_time_only: bool) -> datetime:
    raw = _text(value)
    if not raw:
        raise PortfolioSafetyStateError("Trade timestamp is missing")
    if raw.isdigit():
        stamp = int(raw)
        if stamp > 10_000_000_000:
            stamp //= 1000
        try:
            return datetime.fromtimestamp(stamp, tz=_IST)
        except (OverflowError, OSError, ValueError) as exc:
            raise PortfolioSafetyStateError("Trade timestamp is invalid") from exc

    normalised = raw[:-1] + "+00:00" if raw.endswith("Z") else raw
    try:
        parsed = datetime.fromisoformat(normalised)
    except ValueError:
        parsed = None
    if parsed is None:
        for pattern in ("%d-%m-%Y %H:%M:%S", "%d/%m/%Y %H:%M:%S"):
            try:
                parsed = datetime.strptime(raw, pattern)  # noqa: DTZ007
                break
            except ValueError:
                continue
    if parsed is None and allow_time_only:
        try:
            parsed_time = time.fromisoformat(raw)
        except ValueError as exc:
            raise PortfolioSafetyStateError("Trade timestamp is invalid") from exc
        parsed = datetime.combine(expected_date, parsed_time, tzinfo=_IST)
    if parsed is None:
        raise PortfolioSafetyStateError("Trade timestamp must include the trading date")
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=_IST)
    return parsed.astimezone(_IST)


def _validate_trade_session(
    trades: Any,
    *,
    expected_date: date,
    allow_time_only: bool,
    observed_at: datetime,
    time_scheduler: Any = None,
) -> None:
    for trade in _rows(trades, "data", "trades", "tradebook"):
        raw_timestamp = _field(trade, "timestamp", "exchange_timestamp", "exchangeTime", "order_timestamp")
        raw_text = _text(raw_timestamp)
        time_only = False
        if allow_time_only and raw_text and not raw_text.isdigit():
            try:
                time.fromisoformat(raw_text)
            except ValueError:
                pass
            else:
                time_only = True
        if time_only:
            session_for = getattr(time_scheduler, "get_market_session", None)
            if not callable(session_for):
                raise PortfolioSafetyStateError(
                    "Authoritative market session is unavailable for a time-only trade book"
                )
            exchange = _text(_field(trade, "exchange")).upper()
            symbol = _text(_field(trade, "symbol", "trading_symbol", "tradingsymbol"))
            if not exchange:
                raise PortfolioSafetyStateError("Time-only trade is missing its exchange")
            try:
                market_session = session_for(exchange, on=expected_date, symbol=symbol or None)
            except Exception as exc:
                raise PortfolioSafetyStateError(
                    "Authoritative market session is unavailable for a time-only trade book"
                ) from exc
            if not isinstance(market_session, tuple) or len(market_session) != 2:
                raise PortfolioSafetyStateError("Time-only trade book is not from an open trading date")
            market_open, _market_close = market_session
            if not isinstance(market_open, time):
                raise PortfolioSafetyStateError("Authoritative market session is invalid")
            opens_at = datetime.combine(expected_date, market_open, tzinfo=_IST)
            if observed_at < opens_at:
                raise PortfolioSafetyStateError(
                    "Time-only trade book cannot be assigned before the current session opens"
                )
        timestamp = _trade_timestamp(
            raw_timestamp,
            expected_date=expected_date,
            allow_time_only=allow_time_only,
        )
        if timestamp.date() != expected_date:
            raise PortfolioSafetyStateError("Trade book contains a fill from another trading date")


async def gather_safety_state(
    config: Mapping[str, Any],
    adapter_id: str,
    *,
    account_id: str = "default",
    at: datetime | None = None,
    orders: list[Any] | tuple[Any, ...] = (),
    reservations: list[Any] | tuple[Any, ...] = (),
    include_order_margin: bool = False,
) -> PortfolioSafetyState:
    """Gather one complete selector-scoped L2/L4 snapshot.

    Unlike the best-effort L2-only wrapper, this function fails closed. A live
    order must not turn an unavailable trade book, quote, or capital balance
    into a zero-loss L4 bypass.
    """
    source = _resolve_account_source(config, adapter_id, account_id)
    try:
        snapshot = await _read_stable_accounting_snapshot(source)
        funds = await _read(source, "funds", "funds")
    except PortfolioSafetyStateError:
        raise
    except Exception as exc:
        raise PortfolioSafetyStateError(
            "Portfolio positions, holdings, funds, trade book, or order book are unavailable"
        ) from exc

    positions = snapshot.positions
    trades = snapshot.trades
    holdings = snapshot.holdings
    projected_reservations, reconciled_reservation_ids = _project_unresolved_reservations(
        reservations,
        snapshot,
    )
    pending_orders = [*_active_unfilled_orders(snapshot.orders), *projected_reservations]
    now = at or datetime.now(_IST)
    if now.tzinfo is None:
        now = now.replace(tzinfo=_IST)
    expected_date = now.astimezone(_IST).date()
    _validate_trade_session(
        trades,
        expected_date=expected_date,
        allow_time_only=source.openalgo,
        observed_at=now.astimezone(_IST),
        time_scheduler=config.get("TIME_SCHEDULER"),
    )

    order_quote_symbols = _required_order_quote_symbols([*projected_reservations, *orders])
    quote_symbols = sorted(
        set(required_quote_symbols(trades, positions, holdings)) | set(order_quote_symbols)
    )
    previous_close_symbols = required_previous_close_symbols(trades, positions, holdings)
    quotes: Any = []
    if quote_symbols:
        try:
            if source.openalgo:
                quote_payload = [
                    {"exchange": value.split(":", 1)[0], "symbol": value.split(":", 1)[1]}
                    for value in quote_symbols
                ]
                quotes = await _read(source, "multi_quotes", "quotes", quote_payload)
            else:
                quotes = await _read(source, "multi_quotes", "quotes", quote_symbols)
        except PortfolioSafetyStateError:
            raise
        except Exception as exc:
            raise PortfolioSafetyStateError("Portfolio quote snapshot is unavailable") from exc

    previous_close_symbols = _symbols_missing_trusted_quote(quotes, previous_close_symbols)
    if previous_close_symbols:
        try:
            quotes = await _backfill_previous_closes(
                source,
                quotes,
                previous_close_symbols,
                expected_date=expected_date,
            )
        except PortfolioSafetyStateError:
            raise
        except Exception as exc:
            raise PortfolioSafetyStateError("Previous-session close snapshot is unavailable") from exc

    l2_positions, used_margin, total_balance = normalise_l2_state(positions, funds)
    if not math.isfinite(total_balance) or total_balance <= 0:
        raise PortfolioSafetyStateError("Positive account capital is unavailable")
    opening_risk_capital = _to_float(
        _field(
            funds,
            "opening_risk_capital",
            "opening_balance",
            "sod_limit",
            "sodLimit",
        )
    )
    daily_pnl = compute_local_daily_pnl(trades, positions, quotes, holdings)
    # Accepted orders and sibling batch legs are independently executable.  Do
    # not net a protective leg against risk that can fill first or survive a
    # partial batch failure.
    all_exposure_orders = [*pending_orders, *orders]
    base_delta, base_vega, contributions = await _greek_contributions(
        source,
        positions,
        all_exposure_orders,
    )
    pending_count = len(pending_orders)
    pending_contributions = contributions[:pending_count]
    proposed_contributions = contributions[pending_count:]
    net_delta = _worst_case_component(
        base_delta,
        [delta for delta, _vega in pending_contributions],
    )
    net_vega = _worst_case_component(
        base_vega,
        [vega for _delta, vega in pending_contributions],
    )
    prospective: list[ProspectiveSafetyInputs] = []
    extra_margin = 0.0
    if include_order_margin:
        margin_orders = [
            *projected_reservations,
            *(order for order in pending_orders if bool(_field(order, "margin_unfunded"))),
            *orders,
        ]
        for margin_order in margin_orders:
            extra_margin += await _required_order_margin(source, margin_order)
    for index, order in enumerate(orders):
        uncertain_orders = [
            *pending_orders,
            *(other for other_index, other in enumerate(orders) if other_index != index),
        ]
        positions_before = _worst_case_positions(l2_positions, uncertain_orders)
        required_delta, required_vega = proposed_contributions[index]
        uncertain_contributions = [
            *pending_contributions,
            *(
                contribution
                for other_index, contribution in enumerate(proposed_contributions)
                if other_index != index
            ),
        ]
        order_net_delta = _worst_case_component(
            base_delta + required_delta,
            [delta for delta, _vega in uncertain_contributions],
        )
        order_net_vega = _worst_case_component(
            base_vega + required_vega,
            [vega for _delta, vega in uncertain_contributions],
        )
        prospective.append(
            ProspectiveSafetyInputs(
                positions=positions_before,
                used_margin=used_margin + extra_margin,
                net_delta=order_net_delta,
                net_vega=order_net_vega,
            )
        )
    quotes_by_key = {
        _quote_key(quote): quote
        for quote in _rows(quotes, "data", "quotes")
    }
    order_ltps: dict[tuple[str, str], float] = {}
    for value in order_quote_symbols:
        key = tuple(value.split(":", 1))
        quote = quotes_by_key.get(key)
        if quote is None:
            raise PortfolioSafetyStateError(f"Required order LTP is unavailable for {value}")
        ltp = _finite_number(_field(quote, "ltp", "last_price", "last_traded_price"), "order LTP")
        if ltp <= 0:
            raise PortfolioSafetyStateError(f"Required order LTP is invalid for {value}")
        order_ltps[key] = ltp
    return PortfolioSafetyState(
        positions=l2_positions,
        used_margin=used_margin,
        total_balance=total_balance,
        daily_pnl=daily_pnl,
        starting_capital=opening_risk_capital,
        net_delta=net_delta,
        net_vega=net_vega,
        order_ltps=order_ltps,
        prospective=tuple(prospective),
        reconciled_reservation_ids=reconciled_reservation_ids,
    )


async def _maybe_await(value: Any) -> Any:
    import inspect  # noqa: PLC0415

    if inspect.isawaitable(value):
        return await value
    return value


async def gather_l2_state(
    config: Mapping[str, Any],
    adapter_id: str,
    *,
    account_id: str = "default",
) -> tuple[list[Any], float, float]:
    """THE shared best-effort ``(positions, used_margin, total_balance)`` gather.

    One implementation of the SafetySystem L2 input-gathering path — used by the
    human order route AND the webhook dispatcher, so the openalgo-vs-native
    branch, session resolution, and error classification can never drift between
    two copies. Reads the connected account's positions + funds through the
    same broker surface the order will use: OpenAlgo for the bridge path, or the
    active native adapter + registry session for routed native brokers.
    Best-effort by design: any failure (no client/session, network, auth)
    returns empty/zero state, so L2 simply enforces nothing for that order — a
    state-read hiccup must never block a live order (L1/L4/L5 still apply).
    """
    import logging  # noqa: PLC0415

    logger = logging.getLogger("flinttrade.l2_state")

    if adapter_id == "openalgo":
        client = config.get("OPENALGO_CLIENT")
        if client is None:
            return [], 0.0, 0.0
        try:
            positions = await _maybe_await(client.positionbook())
            funds = await _maybe_await(client.funds())
        except Exception:
            logger.debug(
                "L2 portfolio-state fetch failed — L2 limits not enforced this order",
                exc_info=True,
            )
            return [], 0.0, 0.0
        return normalise_l2_state(positions, funds)

    native_adapters = config.get("NATIVE_ADAPTERS") or {}
    registry = config.get("REGISTRY")
    adapter = native_adapters.get(adapter_id)
    if adapter is None or registry is None:
        return [], 0.0, 0.0

    try:
        session = registry.get_session_for(adapter_id, account_id)
    except Exception:
        return [], 0.0, 0.0

    positions_reader = getattr(adapter, "positions", None)
    funds_reader = getattr(adapter, "funds", None)
    if not callable(positions_reader) or not callable(funds_reader):
        return [], 0.0, 0.0
    try:
        positions = await _maybe_await(positions_reader(session))
        funds = await _maybe_await(funds_reader(session))
    except Exception:
        logger.debug(
            "Native L2 portfolio-state fetch failed — L2 limits not enforced this order",
            exc_info=True,
        )
        return [], 0.0, 0.0
    return normalise_l2_state(positions, funds)
