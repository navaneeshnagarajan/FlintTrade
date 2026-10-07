"""Canonical-to-IndMoney (INDstocks) mapping tables and translators.

Values are grounded in the official INDstocks API docs (``api-docs.indstocks.com``,
captured 2026-06-12 into ``.local/reference/broker-docs/indmoney/``). IndMoney has
no official SDK, so this module owns BOTH directions of the pure-REST translation:
request building (FlintTrade ``Order`` → JSON payloads) and response parsing
(IndMoney JSON → normalised FlintTrade-shaped dicts), plus the WebSocket frame
codecs. Keep these tables in lock-step with ``INDMONEY_CAPABILITIES``.

Honesty rule: anything the broker does not document is REJECTED, never silently
downgraded — e.g. a standalone SL/SL-M order raises (the broker only accepts
LIMIT/MARKET on ``/order``; trigger behaviour lives in the smart-order family).
"""

from __future__ import annotations

import json
import math
from datetime import datetime, timedelta, timezone
from decimal import Decimal, InvalidOperation
from typing import Any

from flinttrade_core.broker_read_port import BrokerReadResponseInvalid
from flinttrade_core.exceptions import (
    AuthError,
    BrokerError,
    BrokerInternal,
    BrokerTimeout,
    DataError,
    InsufficientFunds,
    NetworkError,
    OrderError,
    OrderRejectedByBroker,
    RateLimitError,
    SessionExpired,
)
from flinttrade_gateway.json_evidence import copy_json_evidence

# ---------------------------------------------------------------------------
# Constants (doc-grounded)
# ---------------------------------------------------------------------------

BASE_URL = "https://api.indstocks.com"
PRICE_FEED_WS_URL = "wss://ws-prices.indstocks.com/api/v1/ws/prices"
ORDER_FEED_WS_URL = "wss://ws-order-updates.indstocks.com/api/v1/ws/trades"

# Mandatory algo identifiers (normal-orders doc): 99999 for NSE orders,
# 9999999999999999 for BSE orders.
ALGO_ID_NSE = "99999"
ALGO_ID_BSE = "9999999999999999"

# Canonical transaction side -> IndMoney txn_type.
SIDE_MAP = {
    "BUY": "BUY",
    "SELL": "SELL",
}

# Canonical order type -> IndMoney order_type for NORMAL orders. The broker
# accepts only LIMIT/MARKET here (MARKET is broker-converted to LIMIT at the
# live price); SL/SL-M are deliberately absent — see to_place_order_payload.
ORDER_TYPE_MAP = {
    "MARKET": "MARKET",
    "LIMIT": "LIMIT",
}

# Canonical product -> IndMoney product.
PRODUCT_MAP = {
    "MIS": "INTRADAY",
    "CNC": "CNC",
    "NRML": "MARGIN",
}

# Canonical validity -> IndMoney validity (normal orders only; smart orders are
# DAY-only per the smart-orders doc).
VALIDITY_MAP = {
    "DAY": "DAY",
    "IOC": "IOC",
}

# Canonical exchange -> (IndMoney exchange, IndMoney segment) for the order APIs.
# INDstocks trades NSE/BSE equity and F&O only — no MCX/CDS order endpoints.
EXCHANGE_SEGMENT_MAP = {
    "NSE": ("NSE", "EQUITY"),
    "BSE": ("BSE", "EQUITY"),
    "NFO": ("NSE", "DERIVATIVE"),
    "BFO": ("BSE", "DERIVATIVE"),
}

# Canonical exchange -> scrip-code prefix for the quote/historical REST APIs
# (format ``SEGMENT_INSTRUMENTTOKEN``, e.g. ``NSE_3045``). Index segments use
# NIDX/BIDX, not NSE/BSE (marketquote + instruments docs).
SCRIP_SEGMENT_MAP = {
    "NSE": "NSE",
    "BSE": "BSE",
    "NFO": "NFO",
    "BFO": "BFO",
    "NSE_INDEX": "NIDX",
    "BSE_INDEX": "BIDX",
}

# FlintTrade stream mode -> IndMoney price-feed WebSocket mode.
WS_MODE_MAP = {
    "LTP": "ltp",
    "QUOTE": "quote",
    "FULL": "quote",  # quote is the richest documented price-feed mode
}

# IndMoney product -> canonical product (response parsing).
PRODUCT_REVERSE_MAP = {
    "INTRADAY": "MIS",
    "CNC": "CNC",
    "MARGIN": "NRML",
}

# (exchange, segment) -> canonical exchange (response parsing).
SEGMENT_REVERSE_MAP = {
    ("NSE", "EQUITY"): "NSE",
    ("BSE", "EQUITY"): "BSE",
    ("NSE", "DERIVATIVE"): "NFO",
    ("BSE", "DERIVATIVE"): "BFO",
}

# Documented exchange_segment values (trades/holdings payloads) -> canonical.
EXCHANGE_SEGMENT_REVERSE_MAP = {
    "NSE_EQ": "NSE",
    "BSE_EQ": "BSE",
    "NSE_FNO": "NFO",
    "BSE_FNO": "BFO",
}

# Historical interval -> (IndMoney interval label, max fetch range in days).
# Straight from the historical-data "Supported Intervals & Maximum Time Range"
# table. Keys are FlintTrade canonical interval spellings.
INTERVAL_MAP = {
    "1s": ("1second", 1),
    "5s": ("5second", 1),
    "10s": ("10second", 1),
    "15s": ("15second", 1),
    "1m": ("1minute", 7),
    "2m": ("2minute", 7),
    "3m": ("3minute", 7),
    "4m": ("4minute", 7),
    "5m": ("5minute", 7),
    "10m": ("10minute", 7),
    "15m": ("15minute", 7),
    "30m": ("30minute", 7),
    "1h": ("60minute", 14),
    "2h": ("120minute", 14),
    "3h": ("180minute", 14),
    "4h": ("240minute", 14),
    "d": ("1day", 365),
    "1d": ("1day", 365),
    "day": ("1day", 365),
    "w": ("1week", 365),
    "1w": ("1week", 365),
    "week": ("1week", 365),
    "1mo": ("1month", 365),
    "month": ("1month", 365),
}

# Varieties dispatched to the smart-order (GTT) endpoints.
SMART_VARIETIES = ("gtt", "oco", "trigger")

# IST — all IndMoney timestamps are IST epoch milliseconds (conventions doc).
_IST = timezone(timedelta(hours=5, minutes=30))


class IndMoneyMappingError(ValueError):
    """Raised when an order/response cannot be translated to/from the IndMoney API."""


# ---------------------------------------------------------------------------
# Small helpers
# ---------------------------------------------------------------------------

_MISSING = object()


def _response_record(value: object) -> dict[str, Any]:
    if type(value) is not dict or any(type(key) is not str for key in value):
        raise BrokerReadResponseInvalid
    return value


def _response_text(
    row: dict[str, Any],
    name: str,
    *,
    required: bool = False,
    empty_absent: bool = False,
) -> str | object:
    if name not in row or row[name] is None:
        if required:
            raise BrokerReadResponseInvalid
        return _MISSING
    value = row[name]
    if type(value) is not str:
        raise BrokerReadResponseInvalid
    if not value:
        if empty_absent and not required:
            return _MISSING
        if required:
            raise BrokerReadResponseInvalid
    return value.encode("utf-8").decode("utf-8")


def _response_number_text(
    row: dict[str, Any],
    name: str,
    *,
    required: bool = False,
    empty_absent: bool = False,
) -> str | object:
    if name not in row or row[name] is None:
        if required:
            raise BrokerReadResponseInvalid
        return _MISSING
    value = row[name]
    if type(value) is int:
        return str(value)
    if type(value) is float:
        if not math.isfinite(value):
            raise BrokerReadResponseInvalid
        return str(value)
    if type(value) is str:
        if not value.strip():
            if empty_absent and not required:
                return _MISSING
            raise BrokerReadResponseInvalid
        try:
            number = Decimal(value)
        except InvalidOperation:
            raise BrokerReadResponseInvalid from None
        if number.is_finite():
            return value.encode("utf-8").decode("utf-8")
    raise BrokerReadResponseInvalid


def _response_exchange(row: dict[str, Any]) -> str:
    exchange = _response_text(row, "exchange", required=True)
    segment = _response_text(row, "segment", required=True)
    try:
        return SEGMENT_REVERSE_MAP[(exchange.upper(), segment.upper())]
    except KeyError:
        raise BrokerReadResponseInvalid from None


def _response_exchange_segment(row: dict[str, Any]) -> str:
    segment = _response_text(row, "exchange_segment", required=True)
    try:
        return EXCHANGE_SEGMENT_REVERSE_MAP[segment.upper()]
    except KeyError:
        raise BrokerReadResponseInvalid from None


def _response_product(value: object) -> str:
    if type(value) is not str or not value:
        raise BrokerReadResponseInvalid
    try:
        return PRODUCT_REVERSE_MAP[value.upper()]
    except KeyError:
        raise BrokerReadResponseInvalid from None


def _put_present(target: dict[str, Any], name: str, value: object) -> None:
    if value is not _MISSING:
        target[name] = value


def _market_number(
    row: dict[str, Any],
    name: str,
    *,
    integer: bool = False,
    indian: bool = False,
) -> float | int | object:
    """Copy present market evidence after validating exact JSON primitives."""
    if name not in row:
        return _MISSING
    value = row[name]
    if type(value) is str:
        candidate = value.strip()
        if not candidate:
            raise BrokerReadResponseInvalid from None
        if indian:
            candidate = candidate.replace(",", "")
    elif type(value) in (int, float):
        candidate = str(value)
    else:
        raise BrokerReadResponseInvalid from None
    try:
        number = Decimal(candidate)
    except InvalidOperation:
        raise BrokerReadResponseInvalid from None
    converted = float(number)
    if not number.is_finite() or not math.isfinite(converted):
        raise BrokerReadResponseInvalid from None
    if integer:
        if number < 0 or number != number.to_integral_value():
            raise BrokerReadResponseInvalid from None
        return int(number)
    return converted


def _quote_depth_price(record: dict[str, Any], side: str) -> float | object:
    depth = record
    if "market_depth" in record:
        depth = _response_record(record["market_depth"])
    if "depth" not in depth:
        return _MISSING
    rows = depth["depth"]
    if type(rows) is not list:
        raise BrokerReadResponseInvalid from None
    if not rows:
        return _MISSING
    first = _response_record(rows[0])
    if side not in first:
        return _MISSING
    leg = _response_record(first[side])
    return _market_number(leg, "price", indian=True)


def _num(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _present_order_number(record: dict[str, Any], key: str) -> str | None:
    if key not in record:
        return None
    value = record[key]
    if value is None or (isinstance(value, str) and not value.strip()):
        return None
    return str(value)


def parse_indian_number(value: Any) -> float:
    """Parse a numeric string that may use Indian comma grouping (``"5,82,909"``).

    Args:
        value: Raw value from a depth/quote payload (str or number).

    Returns:
        The parsed float; 0.0 if unparseable.
    """
    if isinstance(value, str):
        value = value.replace(",", "").strip()
    return _num(value)


def _norm_pricetype(pricetype: Any) -> str:
    # FlintTrade uses "SL-M"; normalise to a hyphen-free comparison key.
    return str(pricetype).upper().replace("-", "")


def default_algo_id(exchange: str) -> str:
    """Return the mandatory broker algo id for *exchange* (canonical or IndMoney).

    Args:
        exchange: Canonical exchange (``"NSE"``/``"BSE"``/``"NFO"``/``"BFO"``).

    Returns:
        ``"99999"`` for NSE-family orders, ``"9999999999999999"`` for BSE-family.
    """
    return ALGO_ID_BSE if str(exchange).upper() in ("BSE", "BFO", "BSE_INDEX") else ALGO_ID_NSE


def to_exchange_segment(exchange: str) -> tuple[str, str]:
    """Map a canonical exchange to the IndMoney ``(exchange, segment)`` pair.

    Args:
        exchange: Canonical FlintTrade exchange (e.g. ``"NSE"``, ``"NFO"``).

    Returns:
        Tuple of IndMoney exchange (``"NSE"``/``"BSE"``) and segment
        (``"EQUITY"``/``"DERIVATIVE"``).

    Raises:
        IndMoneyMappingError: If *exchange* is not orderable on IndMoney.
    """
    try:
        return EXCHANGE_SEGMENT_MAP[str(exchange).upper()]
    except KeyError as exc:
        raise IndMoneyMappingError(f"IndMoney cannot trade exchange {exchange!r} (NSE/BSE/NFO/BFO only)") from exc


def to_scrip_code(exchange: str, security_id: str) -> str:
    """Build a quote/historical scrip code (``SEGMENT_INSTRUMENTTOKEN``).

    Args:
        exchange: Canonical exchange (NSE/BSE/NFO/BFO/NSE_INDEX/BSE_INDEX).
        security_id: Instrument token from the instruments master.

    Raises:
        IndMoneyMappingError: If *exchange* has no scrip segment mapping.
    """
    try:
        prefix = SCRIP_SEGMENT_MAP[str(exchange).upper()]
    except KeyError as exc:
        raise IndMoneyMappingError(f"No IndMoney scrip segment for exchange {exchange!r}") from exc
    return f"{prefix}_{security_id}"


def from_scrip_code(scrip: str) -> tuple[str, str]:
    """Split a scrip code back into ``(canonical_exchange, security_id)``."""
    prefix, _, token = str(scrip).partition("_")
    reverse = {v: k for k, v in SCRIP_SEGMENT_MAP.items()}
    return reverse.get(prefix.upper(), prefix.upper()), token


def ws_instrument(exchange: str, security_id: str) -> str:
    """Build a price-feed WebSocket instrument token (``SEGMENT:TOKEN``)."""
    try:
        prefix = SCRIP_SEGMENT_MAP[str(exchange).upper()]
    except KeyError as exc:
        raise IndMoneyMappingError(f"No IndMoney WebSocket segment for exchange {exchange!r}") from exc
    return f"{prefix}:{security_id}"


def segment_from_order_id(order_id: str) -> str | None:
    """Infer the IndMoney segment from a documented order-id prefix.

    ``DRV-`` ids are derivative parents, ``EQ-`` ids equity parents. ``GTT-``
    ids carry no segment information, so ``None`` is returned and the caller
    must resolve the segment another way (e.g. from the order book).
    """
    oid = str(order_id)
    if oid.startswith("DRV-"):
        return "DERIVATIVE"
    if oid.startswith("EQ-"):
        return "EQUITY"
    return None


def is_smart_order_id(order_id: str) -> bool:
    """True when *order_id* belongs to the smart-order (GTT) family."""
    return str(order_id).startswith("GTT-")


def resolve_segment(
    order_id: str, changes: dict[str, Any] | None = None, *, segment: str | None = None
) -> str | None:
    """Reconcile all supplied segment evidence; GTT IDs carry no segment."""
    _request_identity(order_id, "order_id")
    changes = changes or {}
    candidates = []
    for value in ([segment] if segment is not None else []) + (
        [changes["segment"]] if "segment" in changes else []
    ):
        if type(value) is not str or value.upper() not in {"EQUITY", "DERIVATIVE"}:
            raise IndMoneyMappingError("Invalid IndMoney segment")
        candidates.append(value.upper())
    if "exchange" in changes:
        candidates.append(to_exchange_segment(changes["exchange"])[1])
    inferred = segment_from_order_id(order_id)
    if inferred is not None:
        candidates.append(inferred)
    if candidates and any(value != candidates[0] for value in candidates):
        raise IndMoneyMappingError("Conflicting IndMoney segment evidence")
    return candidates[0] if candidates else None


# ---------------------------------------------------------------------------
# Request building: FlintTrade Order -> IndMoney payloads
# ---------------------------------------------------------------------------


def _request_identity(value: object, field: str) -> str:
    if (type(value) is not str or not value or not value.isprintable()
            or any(character.isspace() for character in value)
            or any(character in value for character in "/?#\\")):
        raise IndMoneyMappingError(f"{field} must be a canonical nonblank identity")
    return value


def _request_decimal(value: object, field: str) -> Decimal:
    if type(value) not in (str, int, float, Decimal) or len(str(value)) > 256:
        raise IndMoneyMappingError(f"{field} must be numeric")
    try:
        number = Decimal(str(value))
    except InvalidOperation:
        raise IndMoneyMappingError(f"Invalid {field}") from None
    if not number.is_finite() or number.adjusted() > 308:
        raise IndMoneyMappingError(f"{field} must be bounded and finite")
    return number


def _request_number(value: object, field: str, *, integer: bool = False, zero: bool = False) -> int | float:
    number = _request_decimal(value, field)
    if number < 0 or (number == 0 and not zero):
        label = "limit price" if field == "price" else field
        raise IndMoneyMappingError(f"{label} must be {'nonnegative' if zero else 'greater than zero'}")
    if integer and number != number.to_integral_value():
        raise IndMoneyMappingError(f"{field} must be an exact integer")
    if number == number.to_integral_value():
        return int(number)
    result = float(number)
    if not math.isfinite(result) or Decimal(str(result)) != number:
        raise IndMoneyMappingError(f"{field} cannot be represented faithfully on the JSON wire")
    return result


def _number_alias(
    values: dict[str, Any], *names: str, required: bool = False, integer: bool = False, zero: bool = False
) -> int | float | None:
    supplied = [_request_number(values[name], names[0], integer=integer, zero=zero) for name in names if name in values]
    if not supplied:
        if required:
            raise IndMoneyMappingError(f"Missing {names[0]}")
        return None
    if any(value != supplied[0] for value in supplied):
        raise IndMoneyMappingError(f"Conflicting aliases: {', '.join(names)}")
    return supplied[0]


def _order_values(order: Any, *names: str) -> dict[str, Any]:
    return {name: getattr(order, name) for name in names if hasattr(order, name)}


def _put_requested_remarks(payload: dict[str, Any], order: Any) -> None:
    if hasattr(order, "remarks"):
        remarks = order.remarks
        if type(remarks) is not str or len(remarks) > 100:
            raise IndMoneyMappingError("remarks must be text of at most 100 characters; no silent truncation")
        payload["remarks"] = remarks


def _order_validity(order: Any) -> str:
    validity = getattr(order, "validity", None)
    if validity is None:  # Canonical Order uses None for omitted native validity.
        return "DAY"
    if type(validity) is not str or validity.upper() not in VALIDITY_MAP:
        raise IndMoneyMappingError(f"Unsupported validity {validity!r}")
    return validity.upper()


def _trailing_requested(order: Any) -> bool:
    flag = getattr(order, "is_tsl", False)
    if type(flag) is not bool:
        raise IndMoneyMappingError("is_tsl must be boolean")
    steps = [_request_number(value, name, zero=True) for name, value in
             _order_values(order, "tsl_step_size", "trailing_jump").items()]
    return flag or any(step != 0 for step in steps)


def indmoney_execution_effects(order: Any) -> dict[str, Any]:
    """Describe requested/effective semantics, never observed broker execution."""
    requested = "TRIGGER" if str(getattr(order, "variety", "")).lower() == "trigger" else _norm_pricetype(
        getattr(order, "pricetype", "MARKET")
    )
    limitations = []
    if requested == "TRIGGER":
        trigger = _request_number(getattr(order, "trigger_price", None), "trigger_price")
        price = _optional_order_price(order, "price", "trigger_limit_price")
        effective, effective_price = "TRIGGER_LIMIT", trigger if price is None else price
    elif requested in ORDER_TYPE_MAP:
        effective = "LIMIT"
        price = _number_alias(_order_values(order, "price", "limit_price"), "price", "limit_price",
                              required=requested == "LIMIT", zero=requested == "MARKET")
        effective_price = None if requested == "MARKET" else price
        if requested == "MARKET":
            limitations.append("MARKET_TO_LIMIT")
    else:
        raise IndMoneyMappingError(f"Unsupported requested type {requested!r}")
    if _trailing_requested(order):
        limitations.append("TSL_IGNORED")
    return {"requested_type": requested, "effective_type": effective, "effective_limit_price": effective_price,
            "trailing_active": False, "limitations": limitations}


def _validated_core(order: Any) -> dict[str, Any]:
    """Shared validation + core fields for every IndMoney order payload."""
    if _trailing_requested(order):
        raise IndMoneyMappingError("TSL_IGNORED: active trailing is unsupported")
    side = str(order.action).upper()
    if side not in SIDE_MAP:
        raise IndMoneyMappingError(f"Unsupported action {side!r}")
    exchange, segment = to_exchange_segment(str(order.exchange))
    product = str(order.product).upper()
    if product not in PRODUCT_MAP:
        raise IndMoneyMappingError(f"Unsupported product {product!r}")
    if (segment == "EQUITY" and product == "NRML") or (segment == "DERIVATIVE" and product == "CNC"):
        raise IndMoneyMappingError("product is incompatible with segment")
    qty = _number_alias(_order_values(order, "qty", "quantity"), "qty", "quantity", required=True, integer=True)
    return {
        "txn_type": SIDE_MAP[side],
        "exchange": exchange,
        "segment": segment,
        "product": PRODUCT_MAP[product],
        "qty": qty,
    }


def to_place_order_payload(order: Any, security_id: str, *, algo_id: str | None = None) -> dict[str, Any]:
    """Translate a FlintTrade ``Order`` into a ``POST /order`` JSON body.

    ``security_id`` is resolved by the adapter (IndMoney trades by instrument
    token, not symbol). Variety ``"amo"`` sets the documented ``is_amo`` flag on
    the same payload.

    Raises:
        IndMoneyMappingError: For unmappable enum values, SL/SL-M price types
            (the broker has no standalone stop-loss order — use variety
            ``"trigger"``), or a missing limit price on a LIMIT order.
    """
    payload = _validated_core(order)
    ptype = _norm_pricetype(getattr(order, "pricetype", "MARKET"))
    if ptype in ("SL", "SLM"):
        raise IndMoneyMappingError(
            "IndMoney normal orders accept only LIMIT/MARKET — for stop/trigger behaviour "
            "use variety='trigger' (smart order)"
        )
    if ptype not in ORDER_TYPE_MAP:
        raise IndMoneyMappingError(f"Unsupported pricetype {ptype!r}")
    validity = _order_validity(order)

    payload.update(
        {
            "order_type": ORDER_TYPE_MAP[ptype],
            "validity": VALIDITY_MAP[validity],
            "security_id": _request_identity(security_id, "security_id"),
            "is_amo": str(getattr(order, "variety", "regular")).lower() == "amo",
            "algo_id": _request_identity(
                default_algo_id(payload["exchange"]) if algo_id is None else algo_id, "algo_id"
            ),
        }
    )
    price = _number_alias(
        _order_values(order, "price", "limit_price"), "price", "limit_price",
        required=ptype == "LIMIT", zero=ptype == "MARKET",
    )
    if payload["order_type"] == "LIMIT":
        payload["limit_price"] = price
    _put_requested_remarks(payload, order)
    return payload


def _optional_order_price(order: Any, *names: str) -> int | float | None:
    """Treat canonical zero placeholders as absent, but validate every value."""
    values = _order_values(order, *names)
    numbers = {name: _request_number(value, name, zero=True) for name, value in values.items()}
    return _number_alias({name: value for name, value in numbers.items() if value != 0}, *names)


def to_smart_order_payload(order: Any, security_id: str, *, algo_id: str | None = None) -> dict[str, Any]:
    """Build a smart parent with paired protective legs for either transaction side.

    TRIGGER uses trigger_limit_price, never ordinary limit_price. MARKET/CMP,
    lot/tick/freeze and BSE smart eligibility need independent runtime evidence;
    a request's arbitrary price is not a quote or readiness proof.
    """
    payload = _validated_core(order)
    variety = str(getattr(order, "variety", "")).lower()
    if variety not in SMART_VARIETIES:
        raise IndMoneyMappingError(f"Unsupported smart variety {variety!r}")
    if _order_validity(order) != "DAY":
        raise IndMoneyMappingError("Smart validity must be DAY")
    payload.update({
        "validity": "DAY", "security_id": _request_identity(security_id, "security_id"),
        "algo_id": _request_identity(default_algo_id(payload["exchange"]) if algo_id is None else algo_id, "algo_id"),
    })
    entry = None
    if variety == "trigger":
        if hasattr(order, "limit_price"):
            raise IndMoneyMappingError("TRIGGER uses trigger_limit_price, not limit_price")
        trigger = _request_number(getattr(order, "trigger_price", None), "trigger_price")
        payload.update({"order_type": "TRIGGER", "trigger_price": trigger})
        limit = _optional_order_price(order, "price", "trigger_limit_price")
        if limit is not None:
            payload["trigger_limit_price"] = limit
        entry = trigger if limit is None else limit
    else:
        ptype = _norm_pricetype(getattr(order, "pricetype", "MARKET"))
        if ptype not in ORDER_TYPE_MAP:
            raise IndMoneyMappingError(f"Unsupported pricetype {ptype!r} for a smart order")
        payload["order_type"] = ptype
        price = _number_alias(_order_values(order, "price", "limit_price"), "price", "limit_price",
                              required=ptype == "LIMIT", zero=ptype == "MARKET")
        if ptype == "LIMIT":
            payload["limit_price"] = entry = price
    legs = {}
    for prefix, alias in (("sl", "stop_loss_price"), ("tgt", "target_price")):
        trigger_name, limit_name = f"{prefix}_trigger_price", f"{prefix}_limit_price"
        trigger = _optional_order_price(order, trigger_name, alias)
        limit = _optional_order_price(order, limit_name)
        if (trigger is None) != (limit is None):
            raise IndMoneyMappingError(f"A protective leg requires both {trigger_name} and {limit_name}")
        if trigger is None or limit is None:
            continue
        below = (payload["txn_type"] == "BUY") == (prefix == "sl")
        if (below and limit >= trigger) or (not below and limit <= trigger):
            direction = "less" if below else "greater"
            raise IndMoneyMappingError(f"{limit_name} must be strictly {direction} than {trigger_name}")
        if entry is not None and ((below and trigger >= entry) or (not below and trigger <= entry)):
            raise IndMoneyMappingError(f"{trigger_name} is on the wrong side of entry")
        legs.update({trigger_name: trigger, limit_name: limit})
    if variety in {"gtt", "oco"} and not legs:
        raise IndMoneyMappingError("A GTT/OCO smart order needs a stop_loss_price and/or a target_price leg")
    payload.update(legs)
    _put_requested_remarks(payload, order)
    return payload


def to_modify_order_payload(order_id: str, changes: dict[str, Any], *, segment: str | None = None) -> dict[str, Any]:
    """Translate modify ``changes`` into a ``POST /order/modify`` JSON body.

    Both ``qty`` and ``limit_price`` are mandatory on the IndMoney modify API.

    Raises:
        IndMoneyMappingError: Missing/zero qty or limit price, or an
            unresolvable segment.
    """
    seg = resolve_segment(order_id, changes, segment=segment)
    if seg is None:
        raise IndMoneyMappingError(
            f"Cannot infer the IndMoney segment for order {order_id!r} — pass changes['segment']"
        )
    qty = _number_alias(changes, "qty", "quantity", required=True, integer=True)
    limit_price = _number_alias(changes, "limit_price", "price", required=True)
    return {"order_id": _request_identity(order_id, "order_id"), "segment": seg, "qty": qty,
            "limit_price": limit_price}


def to_smart_modify_payload(
    order_id: str, changes: dict[str, Any], *, segment: str | None = None, algo_id: str | None = None,
    existing_order_type: str | None = None,
) -> dict[str, Any]:
    """Build supplied smart edits, bound to caller-observed immutable type.

    Resource context is validation-only. Partial protective edits remain
    supported; unchanged leg/side/CMP coherence needs fresh broker evidence.
    Neither an opaque ID nor a requested type establishes existing type.
    """
    allowed = {
        "order_type", "pricetype", "qty", "quantity", "price", "limit_price", "trigger_price",
        "trigger_limit_price", "sl_trigger_price", "sl_limit_price", "tgt_trigger_price", "tgt_limit_price",
        "stop_loss_price", "target_price", "segment", "exchange", "algo_id", "existing_order_type", "variety",
    }
    if type(changes) is not dict or any(key not in allowed for key in changes):
        raise IndMoneyMappingError("Unsupported smart mutation fields")
    seg = resolve_segment(order_id, changes, segment=segment)
    if seg is None:
        raise IndMoneyMappingError("Smart modify requires explicit segment evidence")
    current = existing_order_type if existing_order_type is not None else changes.get("existing_order_type")
    if type(current) is not str or current.upper() not in {"LIMIT", "MARKET", "TRIGGER"}:
        raise IndMoneyMappingError("Smart modify requires an observed existing_order_type")
    current = current.upper()
    if "existing_order_type" in changes and (
        type(changes["existing_order_type"]) is not str or changes["existing_order_type"].upper() != current
    ):
        raise IndMoneyMappingError("Conflicting existing_order_type evidence")
    requested = [_norm_pricetype(changes[key]) for key in ("order_type", "pricetype") if key in changes]
    if any(value != current for value in requested):
        raise IndMoneyMappingError("Requested order_type must match the existing order type")
    algorithm = algo_id if algo_id is not None else changes.get("algo_id")
    if algorithm is None:
        if "exchange" not in changes:
            raise IndMoneyMappingError("Smart modify requires algo_id or explicit exchange evidence")
        algorithm = default_algo_id(changes["exchange"])
    if "algo_id" in changes and changes["algo_id"] != algorithm:
        raise IndMoneyMappingError("Conflicting algo_id evidence")
    payload: dict[str, Any] = {
        "order_id": _request_identity(order_id, "order_id"), "segment": seg,
        "algo_id": _request_identity(algorithm, "algo_id"),
    }
    if requested:
        payload["order_type"] = current
    qty = _number_alias(changes, "qty", "quantity", integer=True)
    if qty is not None:
        payload["qty"] = qty
    if current == "TRIGGER":
        if "limit_price" in changes:
            raise IndMoneyMappingError("TRIGGER uses trigger_limit_price, not limit_price")
        payload["trigger_price"] = _number_alias(changes, "trigger_price", required=True)
        price = _number_alias(changes, "price", "trigger_limit_price")
        if price is not None:
            payload["trigger_limit_price"] = price
    else:
        if "trigger_price" in changes or "trigger_limit_price" in changes:
            raise IndMoneyMappingError("Parent trigger fields require an existing TRIGGER")
        if current == "MARKET" and any(key in changes for key in ("price", "limit_price")):
            raise IndMoneyMappingError("MARKET price edits are ignored, not supported")
        price = _number_alias(changes, "price", "limit_price")
        if price is not None:
            payload["limit_price"] = price
    for prefix, alias in (("sl", "stop_loss_price"), ("tgt", "target_price")):
        trigger = _number_alias(changes, f"{prefix}_trigger_price", alias)
        limit = _number_alias(changes, f"{prefix}_limit_price")
        if trigger is not None:
            payload[f"{prefix}_trigger_price"] = trigger
        if limit is not None:
            payload[f"{prefix}_limit_price"] = limit
    if not set(payload) - {"order_id", "segment", "algo_id"}:
        raise IndMoneyMappingError("Smart modify requires an explicit edit")
    return payload


def to_cancel_payload(order_id: str, segment: str) -> dict[str, Any]:
    """Build the shared cancel body for ``/order/cancel`` and ``/smart/order/cancel``."""
    if segment is None:
        raise IndMoneyMappingError("Cancel requires an explicit segment")
    return {"order_id": _request_identity(order_id, "order_id"), "segment": resolve_segment(order_id, segment=segment)}


def to_margin_params(order: Any, security_id: str) -> dict[str, str]:
    """Translate an ``Order`` into the ``GET /margin`` body (string-typed fields)."""
    core = _validated_core(order)
    return {
        "segment": core["segment"],
        "exchange": core["exchange"],
        "securityID": str(security_id),
        "txnType": core["txn_type"],
        "quantity": str(core["qty"]),
        "price": str(_num(getattr(order, "price", 0))),
        "product": core["product"],
    }


# ---------------------------------------------------------------------------
# Response envelope + error mapping
# ---------------------------------------------------------------------------


def unwrap(resp: Any) -> Any:
    """Unwrap an IndMoney ``{status, data, message}`` envelope; raise on error.

    Raises:
        IndMoneyMappingError: If the payload carries ``status: "error"``.
    """
    if isinstance(resp, dict):
        if str(resp.get("status", "")).lower() == "error":
            raise IndMoneyMappingError(f"IndMoney API error: {resp.get('message') or resp}")
        if "data" in resp:
            return resp["data"]
    return resp


def unwrap_fixed_read(resp: Any) -> Any:
    """Strictly unwrap a fixed broker-read response envelope."""
    if type(resp) is not dict or any(type(key) is not str for key in resp):
        raise BrokerReadResponseInvalid from None
    status = resp.get("status")
    if type(status) is not str or not status.strip():
        raise BrokerReadResponseInvalid from None
    if status.strip().lower() != "success":
        message = resp.get("message")
        detail = message.strip() if type(message) is str and message.strip() else "provider-declared failure"
        raise IndMoneyMappingError(f"IndMoney API error: {detail}")
    if "data" not in resp:
        raise BrokerReadResponseInvalid from None
    return resp["data"]


def map_error(status_code: int, payload: Any) -> BrokerError:
    """Map an IndMoney HTTP error response to the FlintTrade exception taxonomy.

    Args:
        status_code: HTTP status code of the failed request.
        payload: Decoded JSON body (``{status, message, error_type|error_code}``)
            or raw text.

    Returns:
        The mapped :class:`~flinttrade_core.exceptions.BrokerError` subclass
        instance (contract §7 — broker-native errors never escape the adapter).
    """
    body = payload if isinstance(payload, dict) else {}
    message = str(body.get("message") or payload or f"HTTP {status_code}")
    etype = str(body.get("error_type") or body.get("error_code") or "")
    kwargs: dict[str, Any] = {
        "broker_code": str(body.get("error_code") or etype or status_code), "broker_id": "indmoney",
    }

    if status_code == 429:
        return RateLimitError(message, endpoint="default", **kwargs)
    if etype == "TokenException":
        return SessionExpired(message, **kwargs)
    if etype == "UserException":
        return AuthError(message, **kwargs)
    if etype == "OrderException":
        if "margin" in message.lower() and "exceed" in message.lower():
            return InsufficientFunds(message, **kwargs)
        return OrderRejectedByBroker(message, **kwargs)
    if etype in ("InputException", "RequestValidationException"):
        return OrderError(message, **kwargs)
    if etype == "DataException":
        return DataError(message, **kwargs)
    if etype == "GatewayTimeoutException":
        return BrokerTimeout(message, **kwargs)
    if etype in ("NetworkException", "ServiceUnavailableException"):
        return NetworkError(message, **kwargs)
    if etype == "GeneralException" or status_code >= 500:
        return BrokerInternal(message, **kwargs)
    return BrokerError(message, **kwargs)


def extract_order_id(resp: Any) -> str:
    """Pull the order id from a ``POST /order`` response."""
    try:
        data = _response_record(unwrap_write(resp))
        oid = _response_alias(data, "order_id", "id", required=True)
        if not isinstance(oid, str):
            raise BrokerReadResponseInvalid from None
        order_status = _response_text(data, "order_status")
        if data.get("error") is not None or order_status in {"FAILED", "ABORTED", "REJECTED", "ERROR"}:
            reason = data.get("error") or order_status
            raise IndMoneyMappingError(f"Order acknowledgement rejected: {reason}")
        return oid
    except BrokerReadResponseInvalid:
        raise IndMoneyMappingError("No valid order id in IndMoney response") from None


def unwrap_write(resp: Any, *, require_status: bool = False) -> Any:
    """Require a successful write envelope, not execution or replay evidence.

    Internal legacy extractor calls may wrap already unwrapped data; actual
    transport responses must carry the documented explicit success status.
    """
    response = _response_record(resp)
    if require_status or "status" in response:
        status = response.get("status")
        if type(status) is not str or status.lower() != "success":
            reason = response.get("message") or status
            raise IndMoneyMappingError(f"IndMoney write acknowledgement is not successful: {reason}")
    if response.get("error") is not None or response.get("error_type") is not None:
        reason = response.get("message") or response.get("error")
        raise IndMoneyMappingError(f"IndMoney write acknowledgement contains an error: {reason}")
    return unwrap(response)


def _response_json_copy(value: object) -> Any:
    """Detach structural evidence while retaining the broker-read error taxonomy."""
    try:
        return copy_json_evidence(value)
    except ValueError:
        raise BrokerReadResponseInvalid from None


def from_indmoney_smart_results(resp: Any) -> list[dict[str, Any]]:
    """Preserve every smart operation result; acknowledgements are not fills."""
    data = _response_record(unwrap_write(resp))
    rows = data.get("order_data", [data] if "order_id" in data else None)
    if type(rows) is not list or not rows:
        raise BrokerReadResponseInvalid from None
    results = []
    for source in rows:
        row = _response_record(_response_json_copy(source))
        parent = _response_alias(row, "order_id", "parent_order_id")
        error = row.get("error")
        if error is not None and type(error) not in (str, dict):
            raise BrokerReadResponseInvalid from None
        if parent is _MISSING and error is None:
            raise BrokerReadResponseInvalid from None
        child = row.get("child_order_details")
        child = {} if child is None else _response_record(child)
        child_id = _response_alias(child, "order_id", "child_order_id")
        parent_status = _response_text(row, "order_status")
        child_status = _response_text(child, "order_status")
        results.append({
            "parent_order_id": None if parent is _MISSING else parent,
            "parent_status": None if parent_status is _MISSING else parent_status,
            "child_order_id": None if child_id is _MISSING else child_id,
            "child_status": None if child_status is _MISSING else child_status,
            "error": error, "raw": row,
        })
    return results


def extract_smart_order_ids(resp: Any) -> tuple[str, str | None]:
    """Extract one acknowledged result only, refusing ambiguous/multi outcomes."""
    try:
        results = from_indmoney_smart_results(resp)
    except BrokerReadResponseInvalid:
        raise IndMoneyMappingError("No valid order id in IndMoney smart-order response") from None
    if len(results) != 1:
        raise IndMoneyMappingError("A single-ID contract cannot represent multiple smart results")
    result = results[0]
    if (result["parent_order_id"] is None or result["error"] is not None
            or result["parent_status"] in {"FAILED", "ABORTED", "REJECTED", "ERROR"}
            or result["child_status"] in {"FAILED", "ABORTED", "REJECTED", "ERROR"}):
        reason = result["error"] or result["parent_status"]
        raise IndMoneyMappingError(f"Smart-order acknowledgement rejected: {reason}")
    return result["parent_order_id"], result["child_order_id"]


# ---------------------------------------------------------------------------
# Response parsing (IndMoney -> normalised FlintTrade-shaped dicts)
# ---------------------------------------------------------------------------


def _reverse_exchange(d: dict[str, Any]) -> str:
    """Reconstruct the canonical exchange from an order/position record."""
    pair = (str(d.get("exchange", "")).upper(), str(d.get("segment", "")).upper())
    if pair in SEGMENT_REVERSE_MAP:
        return SEGMENT_REVERSE_MAP[pair]
    seg = str(d.get("exchange_segment", "")).upper()
    return EXCHANGE_SEGMENT_REVERSE_MAP.get(seg, seg or pair[0])


def _response_identifier(row: dict[str, Any], name: str, *, required: bool = False) -> str | object:
    value = _response_text(row, name, required=required, empty_absent=True)
    if value is not _MISSING:
        try:
            _request_identity(value, name)
        except IndMoneyMappingError:
            raise BrokerReadResponseInvalid from None
    return value


def _response_quantity_text(row: dict[str, Any], name: str) -> str | object:
    value = _response_number_text(row, name, empty_absent=True)
    if value is not _MISSING:
        try:
            _request_number(value, name, integer=True, zero=True)
        except IndMoneyMappingError:
            raise BrokerReadResponseInvalid from None
    return value


def _response_alias(row: dict[str, Any], *names: str, quantity: bool = False, required: bool = False) -> str | object:
    reader = _response_quantity_text if quantity else _response_identifier
    values = [reader(row, name) for name in names if name in row]
    values = [value for value in values if isinstance(value, str)]
    if not values:
        if required:
            raise BrokerReadResponseInvalid from None
        return _MISSING
    comparison = [Decimal(value) for value in values] if quantity else values
    if any(value != comparison[0] for value in comparison):
        raise BrokerReadResponseInvalid from None
    return values[0]


_INDMONEY_ATTEMPT_STATES = {
    "SUCCESS": "FILLED", "CANCELLED": "CANCELLED", "PARTIALLY FILLED - CANCELLED": "CANCELLED",
    "EXPIRED": "EXPIRED", "PARTIALLY FILLED - EXPIRED": "EXPIRED", "PARTIALLY FILLED": "PARTIALLY_FILLED",
    "INITIATED": "ACKNOWLEDGED", "QUEUED": "SUBMITTING", "PROCESSING": "SUBMITTING",
    "O-PENDING": "WORKING", "SL-PENDING": "WORKING", "PENDING": "WORKING", "MODIFIED": "WORKING",
    **dict.fromkeys((
        "CANCEL_PENDING", "CANCEL_REQUESTED", "CANCEL PENDING", "CANCEL REQUESTED", "CANCEL-PENDING",
        "CANCEL-REQUESTED", "CANCELLATION_PENDING", "CANCELLATION_REQUESTED", "CANCELLATION PENDING",
        "CANCELLATION REQUESTED",
    ), "CANCEL_PENDING"),
}


def indmoney_attempt_state(status: object) -> str:
    """Classify exact ordinary REST states; never feed codes or substring guesses."""
    return _INDMONEY_ATTEMPT_STATES.get(status, "UNKNOWN") if type(status) is str else "UNKNOWN"


def from_indmoney_order(d: dict[str, Any]) -> dict[str, Any]:
    """Normalise an order record without manufacturing quantities or fills."""
    d = _response_record(d)
    security_id = _response_identifier(d, "security_id")
    quantity = _response_alias(d, "requested_qty", "quantity", quantity=True)
    filled = _response_alias(d, "traded_qty", "filled_quantity", quantity=True)
    if isinstance(quantity, str) and isinstance(filled, str) and Decimal(filled) > Decimal(quantity):
        raise BrokerReadResponseInvalid from None
    status = _response_text(d, "status")
    if status is _MISSING:
        raise BrokerReadResponseInvalid from None
    order = {
        "orderid": _response_alias(d, "id", "order_id", "orderid", required=True),
        "status": status,
        "symbol": _response_text(d, "name", required=True),
        "exchange": _response_exchange(d),
        "action": _response_text(d, "txn_type", required=True),
        "pricetype": _response_text(d, "order_type", required=True),
        "product": _response_product(_response_text(d, "product", required=True)),
    }
    order["attempt_state"] = (
        "UNKNOWN" if is_smart_order_id(order["orderid"]) or order["pricetype"] in {"GTT", "OCO", "TRIGGER"}
        else indmoney_attempt_state(status)
    )
    _put_present(order, "quantity", quantity)
    _put_present(order, "filled_quantity", filled)
    _put_present(order, "instrument_id", security_id)
    _put_present(order, "security_id", security_id)
    for field in ("sl_trigger_price", "sl_limit_price", "tgt_trigger_price", "tgt_limit_price"):
        _put_present(order, field, _response_number_text(d, field, empty_absent=True))
    for field in ("extra_info", "remarks", "created_at", "updated_at", "validity"):
        _put_present(order, field, _response_text(d, field))
    _put_present(order, "exchange_order_id", _response_alias(d, "exch_order_id", "exchange_order_id"))
    for field, source_field in {
        "price": "requested_price", "trigger_price": "trigger_price", "trigger_limit_price": "trigger_limit_price",
        "average_price": "traded_price",
    }.items():
        _put_present(order, field, _response_number_text(d, source_field, empty_absent=True))
    return order


def from_indmoney_trade(d: dict[str, Any]) -> dict[str, Any]:
    """Preserve the historical populated trade schema without coercing evidence."""
    d = _response_record(d)
    result: dict[str, Any] = {
        "orderid": _response_alias(d, "order_id", "orderid", required=True),
        "symbol": "", "exchange": "", "action": "", "product": "", "timestamp": "",
    }
    for target, source in (("symbol", "trading_symbol"), ("action", "transaction_type"),
                           ("timestamp", "trade_timestamp"), ("trade_id", "trade_id")):
        _put_present(result, target, _response_text(d, source))
    exchange = _response_text(d, "exchange_segment")
    if isinstance(exchange, str):
        result["exchange"] = EXCHANGE_SEGMENT_REVERSE_MAP.get(exchange.upper(), exchange)
    product = _response_text(d, "product_type")
    if isinstance(product, str):
        result["product"] = PRODUCT_REVERSE_MAP.get(product, product)
    _put_present(result, "quantity", _response_quantity_text(d, "quantity"))
    price = _response_number_text(d, "price", empty_absent=True)
    if isinstance(price, str) and Decimal(price) < 0:
        raise BrokerReadResponseInvalid from None
    _put_present(result, "price", price)
    return result


def _from_indmoney_fill(d: dict[str, Any], *, order_id: str | None = None) -> dict[str, Any]:
    d = _response_record(d)
    observed_order = _response_alias(d, "order_id", "orderid")
    if order_id is not None:
        try:
            _request_identity(order_id, "order_id")
        except IndMoneyMappingError:
            raise BrokerReadResponseInvalid from None
        if observed_order is not _MISSING and observed_order != order_id:
            raise BrokerReadResponseInvalid from None
    fill_id = _response_quantity_text(d, "fill_id")
    if not isinstance(fill_id, str):
        raise BrokerReadResponseInvalid from None
    exchange_id = _response_alias(d, "exch_order_id", "exchange_order_id", required=True)
    timestamp = _response_text(d, "trade_date", required=True)
    result = {
        "orderid": order_id if order_id is not None else ("" if observed_order is _MISSING else observed_order),
        "fill_id": int(Decimal(fill_id)), "exchange_order_id": exchange_id, "exch_order_id": exchange_id,
        "timestamp": timestamp, "trade_date": timestamp,
        "symbol": "", "exchange": "", "action": "", "product": "",
    }
    _put_present(result, "quantity", _response_quantity_text(d, "quantity"))
    price = _response_number_text(d, "price", empty_absent=True)
    if isinstance(price, str) and Decimal(price) < 0:
        raise BrokerReadResponseInvalid from None
    _put_present(result, "price", price)
    for name in ("trade_serial_no", "scrip_code", "remarks"):
        _put_present(result, name, _response_text(d, name))
    if "scrip_code" in result:
        result["symbol"] = result["scrip_code"]
    return result


def from_indmoney_order_fill(d: dict[str, Any], *, order_id: str) -> dict[str, Any]:
    """Bind current per-order fills to the requested broker order ID.

    The historical populated trade schema remains supported explicitly; it is
    never substituted for current fill/exchange identity or trade_date.
    """
    d = _response_record(d)
    if "trade_timestamp" in d and not any(key in d for key in ("fill_id", "exch_order_id", "trade_date")):
        observed = _response_alias(d, "order_id", "orderid", required=True)
        if observed != order_id:
            raise BrokerReadResponseInvalid from None
        result = from_indmoney_trade(d)
        quantity = _response_quantity_text(d, "quantity")
        if quantity is _MISSING:
            result.pop("quantity", None)
        else:
            result["quantity"] = quantity
        price = _response_number_text(d, "price", empty_absent=True)
        if price is _MISSING:
            result.pop("price", None)
        else:
            result["price"] = price
        return result
    return _from_indmoney_fill(d, order_id=order_id)


def from_indmoney_tradebook_row(d: dict[str, Any]) -> dict[str, Any]:
    """Keep segment-level fill IDs separate from unknown order correlation."""
    return _from_indmoney_fill(d)


def from_indmoney_position(d: dict[str, Any], *, product: str = "") -> dict[str, Any]:
    """Normalise an IndMoney position record (``net_positions``/``day_positions``)."""
    d = _response_record(d)
    canonical_product = product.upper() if type(product) is str else ""
    if canonical_product not in {"CNC", "MIS", "NRML"}:
        raise BrokerReadResponseInvalid
    security_id = _response_text(d, "security_id")
    position = {
        "symbol": _response_text(d, "trading_symbol", required=True),
        "exchange": _response_exchange_segment(d),
        "product": canonical_product,
        "quantity": _response_number_text(d, "net_quantity", required=True),
    }
    _put_present(position, "instrument_id", security_id)
    _put_present(position, "security_id", security_id)
    for field, source_field in {
        "average_price": "average_price",
        "ltp": "last_traded_price",
        "pnl": "pnl_absolute",
    }.items():
        _put_present(position, field, _response_number_text(d, source_field))
    return position


def from_indmoney_holding(d: dict[str, Any]) -> dict[str, Any]:
    """Normalise an IndMoney demat-holding record."""
    d = _response_record(d)
    security_id = _response_text(d, "security_id")
    holding = {
        "symbol": _response_text(d, "trading_symbol", required=True),
        "exchange": _response_exchange_segment(d),
        "quantity": _response_number_text(d, "quantity", required=True),
    }
    _put_present(holding, "instrument_id", security_id)
    _put_present(holding, "security_id", security_id)
    _put_present(holding, "isin", _response_text(d, "isin", empty_absent=True))
    for field, source_field in {
        "average_price": "average_price",
        "ltp": "last_traded_price",
        "pnl": "pnl_absolute",
        "pnl_percent": "pnl_percent",
    }.items():
        _put_present(holding, field, _response_number_text(d, source_field))
    return holding


def from_indmoney_funds(resp: Any) -> dict[str, Any]:
    """Normalise the ``GET /funds`` response.

    IndMoney reports a start-of-day balance plus per-product available balances;
    there is no single "available" figure, so ``available_balance`` carries the
    documented ``withdrawal_balance`` and the full payload is preserved under
    ``extra`` (callers MUST tolerate missing keys — contract §5).
    """
    d = unwrap(resp)
    if not isinstance(d, dict):
        return {"available_balance": "0", "used_margin": "0", "total_balance": "0", "extra": {}}
    sod = _num(d.get("sod_balance", 0))
    withdrawal = _num(d.get("withdrawal_balance", 0))
    used = round(max(sod - withdrawal, 0.0), 2)
    return {
        "available_balance": str(withdrawal),
        "used_margin": str(used),
        "total_balance": str(sod),
        "extra": d,
    }


def from_indmoney_margin(resp: Any) -> dict[str, Any]:
    """Normalise a ``GET /margin`` response into FlintTrade margin fields."""
    data = unwrap(resp)
    if not isinstance(data, dict):
        data = {}
    total = str(data.get("total_margin", 0))
    return {
        "required_margin": total,  # common key across all native adapters
        "total_margin": total,
        "span_margin": str(data.get("span_margin", 0)),
        "exposure_margin": str(data.get("exposure_margin", 0)),
        "available_balance": str(data.get("available_balance", 0)),
        "insufficient_balance": str(data.get("insufficient_balance", 0)),
        "brokerage": str(data.get("brokerage", 0)),
        "var_margin": str(data.get("var_margin", 0)),
        "delivery_margin": str(data.get("delivery_margin", 0)),
        "hedge_benefit": str(data.get("hedge_benefit", 0)),
        "charges": data.get("charges", {}) or {},
    }


def _depth_levels(rows: Any, side: str) -> list[dict[str, Any]]:
    levels: list[dict[str, Any]] = []
    if not isinstance(rows, list):
        return levels
    for row in rows:
        leg = (row or {}).get(side, {}) if isinstance(row, dict) else {}
        levels.append(
            {
                "price": parse_indian_number(leg.get("price", 0)),
                "quantity": int(parse_indian_number(leg.get("quantity", 0))),
            }
        )
    return levels


def from_indmoney_depth(record: dict[str, Any]) -> dict[str, Any]:
    """Parse a ``market_depth`` object into bid/ask ladders with numeric fields."""
    depth = (record or {}).get("market_depth", record) or {}
    rows = depth.get("depth", [])
    aggregate = depth.get("aggregate", {}) or {}
    return {
        "bids": _depth_levels(rows, "buy"),
        "asks": _depth_levels(rows, "sell"),
        "total_buy": parse_indian_number(aggregate.get("total_buy", 0)),
        "total_sell": parse_indian_number(aggregate.get("total_sell", 0)),
    }


def from_indmoney_quote(
    symbol: str,
    exchange: str,
    q: dict[str, Any],
    *,
    strict: bool = False,
) -> dict[str, Any]:
    """Map one full-quote record to a Quote-shaped dict.

    The best bid/ask is taken from the first market-depth level when present.
    """
    if not strict:
        depth = from_indmoney_depth(q)
        bids, asks = depth["bids"], depth["asks"]
        return {
            "symbol": symbol,
            "exchange": exchange,
            "ltp": _num(q.get("live_price", 0)),
            "open": _num(q.get("day_open", 0)),
            "high": _num(q.get("day_high", 0)),
            "low": _num(q.get("day_low", 0)),
            "close": _num(q.get("prev_close", 0)),
            "prev_close": _num(q.get("prev_close", 0)),
            "volume": int(_num(q.get("volume", 0))),
            "bid": bids[0]["price"] if bids else 0.0,
            "ask": asks[0]["price"] if asks else 0.0,
        }

    record = _response_record(q)
    quote: dict[str, Any] = {"symbol": symbol, "exchange": exchange}
    for source, target in (
        ("live_price", "ltp"),
        ("day_open", "open"),
        ("day_high", "high"),
        ("day_low", "low"),
    ):
        _put_present(quote, target, _market_number(record, source))
    previous_close = _market_number(record, "prev_close")
    _put_present(quote, "close", previous_close)
    _put_present(quote, "prev_close", previous_close)
    _put_present(quote, "volume", _market_number(record, "volume", integer=True))
    _put_present(quote, "bid", _quote_depth_price(record, "buy"))
    _put_present(quote, "ask", _quote_depth_price(record, "sell"))
    return quote


# ---------------------------------------------------------------------------
# Historical data
# ---------------------------------------------------------------------------


def interval_to_indmoney(interval: str) -> tuple[str, int]:
    """Map a FlintTrade interval to ``(indmoney_interval, max_range_days)``.

    Args:
        interval: Canonical interval (``"1m"``, ``"1h"``, ``"D"``, …) or a raw
            IndMoney label (``"1minute"``).

    Raises:
        IndMoneyMappingError: If the interval is not in the documented table.
    """
    raw = str(interval).strip().lower()
    if raw in INTERVAL_MAP:
        return INTERVAL_MAP[raw]
    for label, max_days in INTERVAL_MAP.values():
        if raw == label:
            return label, max_days
    raise IndMoneyMappingError(
        f"Unsupported IndMoney historical interval {interval!r} — see the documented interval table"
    )


def to_epoch_ms(value: Any) -> int:
    """Coerce a timestamp input to IST Unix epoch milliseconds.

    Accepts epoch values (int/float/str of digits — seconds are auto-promoted to
    milliseconds) and ``YYYY-MM-DD`` date strings (interpreted at IST midnight,
    matching the broker's IST-epoch convention).

    Raises:
        IndMoneyMappingError: If the value cannot be interpreted.
    """
    if isinstance(value, (int, float)) or (isinstance(value, str) and value.strip().isdigit()):
        n = int(float(value))
        return n * 1000 if n < 10_000_000_000 else n  # < year 2286 in seconds → promote
    if isinstance(value, str):
        try:
            dt = datetime.strptime(value.strip(), "%Y-%m-%d").replace(tzinfo=_IST)
        except ValueError as exc:
            raise IndMoneyMappingError(f"Cannot parse timestamp {value!r} (epoch ms or YYYY-MM-DD)") from exc
        return int(dt.timestamp() * 1000)
    raise IndMoneyMappingError(f"Cannot parse timestamp {value!r} (epoch ms or YYYY-MM-DD)")


def validate_history_range(start_ms: int, end_ms: int, max_days: int) -> None:
    """Enforce the documented per-request fetch-range cap for an interval.

    Raises:
        IndMoneyMappingError: If ``end <= start`` or the range exceeds the cap.
    """
    if end_ms <= start_ms:
        raise IndMoneyMappingError("Historical end_time must be after start_time")
    if (end_ms - start_ms) > max_days * 86_400_000:
        raise IndMoneyMappingError(
            f"Historical range exceeds the documented maximum of {max_days} day(s) for this interval"
        )


def to_candles_dict(symbol: str, exchange: str, interval: str, resp: Any) -> dict[str, Any]:
    """Map a historical response (``[ts, o, h, l, c, v]`` arrays) to a Candles-shaped dict."""
    data = unwrap(resp) or {}
    candles = data.get("candles", []) if isinstance(data, dict) else []
    bars = []
    for row in candles:
        if not isinstance(row, (list, tuple)) or len(row) < 6:
            continue
        bars.append(
            {
                "timestamp": str(row[0]),
                "open": _num(row[1]),
                "high": _num(row[2]),
                "low": _num(row[3]),
                "close": _num(row[4]),
                "volume": int(_num(row[5])),
            }
        )
    return {"symbol": symbol, "exchange": exchange, "interval": str(interval), "bars": bars}


# ---------------------------------------------------------------------------
# Instruments master (CSV)
# ---------------------------------------------------------------------------


def parse_instruments_csv(text: str) -> list[dict[str, str]]:
    """Parse the instruments-master CSV into a list of row dicts.

    Args:
        text: Raw CSV body from ``GET /market/instruments``.

    Returns:
        One dict per instrument, keyed by the documented column names
        (``EXCH``, ``SEGMENT``, ``SECURITY_ID``, ``TRADING_SYMBOL``, …).
    """
    import csv  # noqa: PLC0415
    import io  # noqa: PLC0415

    reader = csv.DictReader(io.StringIO(text))
    return [dict(row) for row in reader]


# ---------------------------------------------------------------------------
# WebSocket codecs (price feed + order updates)
# ---------------------------------------------------------------------------


def subscribe_message(instruments: list[str], mode: str = "FULL", *, action: str = "subscribe") -> str:
    """Build a price-feed subscribe/unsubscribe JSON message.

    Args:
        instruments: WebSocket instrument tokens (``"NSE:2885"`` form).
        mode: FlintTrade mode (``"LTP"``/``"QUOTE"``/``"FULL"``) or a raw
            IndMoney mode (``"ltp"``/``"quote"``).
        action: ``"subscribe"`` or ``"unsubscribe"``.
    """
    ws_mode = WS_MODE_MAP.get(str(mode).upper(), str(mode).lower())
    if ws_mode not in ("ltp", "quote"):
        raise IndMoneyMappingError(f"Unsupported IndMoney feed mode {mode!r} (ltp/quote)")
    if action not in ("subscribe", "unsubscribe"):
        raise IndMoneyMappingError(f"Unsupported feed action {action!r}")
    return json.dumps({"action": action, "mode": ws_mode, "instruments": list(instruments)})


def order_updates_subscribe_message() -> str:
    """Build the one-shot order-updates feed subscription message."""
    return json.dumps({"action": "subscribe", "mode": "order_updates"})


def decode_price_frame(raw: str | bytes) -> dict[str, Any] | None:
    """Decode one price-feed frame into a normalised tick dict.

    Returns ``None`` for heartbeats, non-JSON noise, and frames without a
    recognisable ``instrument``/``data`` shape (the documented server may send
    keep-alive messages that clients should ignore).
    """
    if isinstance(raw, bytes):
        try:
            raw = raw.decode("utf-8")
        except UnicodeDecodeError:
            return None
    try:
        frame = json.loads(raw)
    except (TypeError, ValueError):
        return None
    if not isinstance(frame, dict):
        return None
    instrument = frame.get("instrument")
    data = frame.get("data")
    if not instrument or not isinstance(data, dict):
        return None  # heartbeat / control frame
    return {
        "mode": str(frame.get("mode", "")),
        "security_id": str(instrument),
        "timestamp": str(frame.get("timestamp", "")),
        "ltp": _num(data.get("ltp", data.get("live_price", 0))),
        "volume": int(_num(data.get("volume", 0))),
    }


def decode_order_update(raw: str | bytes) -> dict[str, Any] | None:
    """Decode one order-updates frame; ``None`` for heartbeats/noise."""
    if isinstance(raw, bytes):
        try:
            raw = raw.decode("utf-8")
        except UnicodeDecodeError:
            return None
    try:
        frame = json.loads(raw)
    except (TypeError, ValueError):
        return None
    if not isinstance(frame, dict) or frame.get("type") != "order":
        return None
    return {
        "orderid": str(frame.get("order_id", "")),
        "status": str(frame.get("order_status", "")),
        "filled_quantity": str(frame.get("filled_quantity", 0)),
        "remaining_quantity": str(frame.get("remaining_quantity", 0)),
        "average_price": str(frame.get("average_price", 0)),
        "timestamp": str(frame.get("timestamp", "")),
    }
