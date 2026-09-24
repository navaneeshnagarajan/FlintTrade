"""Pure FlintTrade <-> Kotak Neo (NEO OMS) mapping.

Kept separate from the adapter so order translation and the (cryptically-keyed)
NEO response parsing are fully unit-testable without the Kotak Neo v3 SDK
or live credentials. Order request fields follow the pinned Kotak Neo v3 SDK;
legacy response decoding remains for authoritative readback of historical rows.

NEO is an OMS-style API: order/position records use terse abbreviated keys
(``nOrdNo``, ``trdSym``, ``exSeg``, ``trnsTp``, ``prcTp`` …) and positions are
reported as cumulative buy/sell quantities + amounts rather than a single net
line, so the net quantity, average price and realised P&L are derived here
(``Positions.md``); the unrealised leg is left to merge from a live quote.

Legacy frame decoders remain as compatibility fixtures for synthetic tests.
The public v3 async feed lifecycle is owned by the later streaming migration.
"""

from __future__ import annotations

import json
import math
from decimal import Decimal, InvalidOperation
from typing import Any

from flinttrade_core.broker_read_port import BrokerReadResponseInvalid

from .kotakneo_sdk import validate_read_envelope

# Exchange -> NEO exchange-segment code (from settings.exchange_segment).
EXCHANGE_TO_KOTAK = {
    "NSE": "nse_cm",
    "BSE": "bse_cm",
    "NFO": "nse_fo",
    "BFO": "bse_fo",
    "CDS": "cde_fo",
    "BCD": "bcs-fo",
    "MCX": "mcx_fo",
    # OpenAlgo/terminal index convention: NEO has no separate index segment —
    # index quotes ride the cash segments. Without these entries the
    # ex.lower() fallback emitted the invalid segment "nse_index".
    "NSE_INDEX": "nse_cm",
    "BSE_INDEX": "bse_cm",
}
# Segments with an exact v3 order path. Currency segments remain in the read
# map above so historical broker rows can still be decoded, but cannot be used
# to mint a new order or margin request.
ORDER_EXCHANGES = frozenset({"NSE", "BSE", "NFO", "BFO", "MCX"})
# Reverse map built from the FIRST occurrence of each segment so the primary
# NSE/BSE rows win over the *_INDEX aliases added after them.
KOTAK_TO_EXCHANGE: dict[str, str] = {}
for _ft_exchange, _kotak_segment in EXCHANGE_TO_KOTAK.items():
    KOTAK_TO_EXCHANGE.setdefault(_kotak_segment, _ft_exchange)

# FlintTrade product -> NEO product. NEO also exposes INTRADAY/CO/BO/MTF; we map
# the reverse codes back to the FlintTrade trio.
PRODUCT_TO_KOTAK = {"MIS": "MIS", "CNC": "CNC", "NRML": "NRML"}
KOTAK_TO_PRODUCT = {
    "MIS": "MIS",
    "INTRADAY": "MIS",
    "CO": "MIS",
    "BO": "MIS",
    "CNC": "CNC",
    "NRML": "NRML",
    "MTF": "NRML",
}

# FlintTrade pricetype -> NEO order_type code (settings.order_type).
ORDER_TYPE_TO_KOTAK = {"MARKET": "MKT", "LIMIT": "L", "SL": "SL", "SL-M": "SL-M"}
KOTAK_TO_ORDER_TYPE = {"MKT": "MARKET", "L": "LIMIT", "SL": "SL", "SL-M": "SL-M"}

# NEO transaction type is single-letter.
SIDE_TO_KOTAK = {"BUY": "B", "SELL": "S"}
KOTAK_TO_SIDE = {"B": "BUY", "S": "SELL"}

# Order validity codes in the current public docs and pinned SDK validation.
VALIDITY_ALLOWED = frozenset({"DAY", "IOC"})

# Keep every broker-facing Decimal cheap to validate and bounded when rendered
# as fixed-point text. Sixty-four significant/integer digits and sixteen
# fractional digits are deliberately far above ordinary Indian order values,
# while refusing compact exponent forms that would otherwise expand into an
# attacker-controlled multi-kilobyte (or larger) SDK payload.
_MAX_NUMERIC_DIGITS = 64
_MAX_NUMERIC_INTEGER_DIGITS = 64
_MAX_NUMERIC_SCALE = 16

# REST quotes quote_type values (Quotes.md). The SDK places the value directly
# into the URL path, so FlintTrade accepts case-insensitive input but emits
# Kotak's documented case (notably ``52W``).
QUOTE_TYPE_CANONICAL = {
    "all": "all",
    "depth": "depth",
    "ohlc": "ohlc",
    "ltp": "ltp",
    "oi": "oi",
    "52w": "52W",
    "circuit_limits": "circuit_limits",
    "scrip_details": "scrip_details",
}
QUOTE_TYPES = frozenset(QUOTE_TYPE_CANONICAL)

# Index exchange identifiers (``webSocket.md`` "For Indexes" + Quotes.md): the
# ``instrument_token`` for an index is its NAME, not a numeric scrip token. Both
# the quote and the subscription path pass these names through unresolved.
# Compared case-insensitively (``is_index_name``) since callers vary the casing.
INDEX_NAMES = frozenset(
    {
        "NIFTY 50",
        "NIFTY BANK",
        "NIFTY FIN SERVICE",
        "SENSEX",
        "BANKEX",
        "INDIA VIX",
        "NIFTY MIDCAP 100",
        "NIFTY 100",
        "NIFTY PSU BANK",
        "NIFTY PHARMA",
        "NIFTY IT",
        "NIFTY PSE",
        "NIFTY FMCG",
        "NIFTY 500",
        "NIFTY AUTO",
        "NIFTY CPSE",
        "NIFTY 200",
        "NIFTY NEXT 50",
        "NIFTY MID SELECT",
    }
)
_INDEX_NAME_CANONICAL = {
    "NIFTY 50": "Nifty 50",
    "NIFTY BANK": "Nifty Bank",
    "SENSEX": "SENSEX",
    "BANKEX": "BANKEX",
}


def canonical_quote_type(quote_type: str | None) -> str:
    """Return Kotak's documented quote filter spelling for ``quote_type``."""
    key = str(quote_type or "all").strip().lower()
    try:
        return QUOTE_TYPE_CANONICAL[key]
    except KeyError as exc:
        raise KotakNeoMappingError(f"Unsupported quote_type {quote_type!r}") from exc


def is_index_name(name: str) -> bool:
    """Return ``True`` if ``name`` is a NEO index identifier (passed by name).

    Index quotes/subscriptions key the instrument by its name (``webSocket.md``
    "For Indexes"); everything else needs a numeric scrip token resolved first.
    """
    return str(name).strip().upper() in INDEX_NAMES


def canonical_index_name(name: str) -> str:
    """Return the case-sensitive index name Kotak documents, where known."""
    text = str(name).strip()
    return _INDEX_NAME_CANONICAL.get(text.upper(), text)


# HSM live-feed terse keys -> long names (settings.stock_key_mapping).
STOCK_FEED_KEYS = {
    "ltt": "last_traded_time",
    "v": "volume",
    "ltp": "last_traded_price",
    "ltq": "last_traded_quantity",
    "tbq": "total_buy_quantity",
    "tsq": "total_sell_quantity",
    "bp": "buy_price",
    "sp": "sell_price",
    "bq": "buy_quantity",
    "sq": "sell_quantity",
    "ap": "average_price",
    "oi": "open_interest",
    "lo": "low",
    "h": "high",
    "lcl": "lower_circuit_limit",
    "ucl": "upper_circuit_limit",
    "yh": "52week_high",
    "yl": "52week_low",
    "op": "open",
    "c": "close",
    "cng": "change",
    "nc": "net_change_percentage",
    "to": "total_traded_value",
    "tk": "instrument_token",
    "e": "exchange_segment",
    "ts": "trading_symbol",
}

# HSM index-feed terse keys -> long names (settings.index_key_mapping).
INDEX_FEED_KEYS = {
    "iv": "last_traded_price",
    "ic": "prev_day_close",
    "tvalue": "timestamp",
    "highPrice": "high",
    "lowPrice": "low",
    "openingPrice": "open",
    "cng": "change",
    "nc": "net_change_percentage",
    "tk": "instrument_token",
    "e": "exchange_segment",
}


class KotakNeoMappingError(ValueError):
    """Raised when an order cannot be translated to / from the NEO API."""


_MISSING = object()


def _response_record(value: object) -> dict[str, Any]:
    if type(value) is not dict or any(type(key) is not str for key in value):
        raise BrokerReadResponseInvalid
    return value


def _response_text(
    row: dict[str, Any],
    *names: str,
    required: bool = False,
    empty_absent: bool = False,
) -> str | object:
    for name in names:
        if name not in row:
            continue
        value = row[name]
        if value is None and not required:
            continue
        if type(value) is not str:
            raise BrokerReadResponseInvalid
        if not value:
            if empty_absent and not required:
                continue
            if required:
                raise BrokerReadResponseInvalid
        return value.encode("utf-8").decode("utf-8")
    if required:
        raise BrokerReadResponseInvalid
    return _MISSING


def _response_decimal(
    row: dict[str, Any],
    *names: str,
    required: bool = False,
    empty_absent: bool = False,
) -> Decimal | object:
    for name in names:
        if name not in row:
            continue
        value = row[name]
        if value is None and not required:
            continue
        if type(value) not in (int, float, str) or type(value) is str and not value.strip():
            if empty_absent and not required and type(value) is str and not value.strip():
                continue
            raise BrokerReadResponseInvalid
        try:
            number = Decimal(str(value))
        except (InvalidOperation, ValueError):
            raise BrokerReadResponseInvalid from None
        if not number.is_finite():
            raise BrokerReadResponseInvalid
        if not _bounded_decimal_shape(number):
            raise BrokerReadResponseInvalid
        return number
    if required:
        raise BrokerReadResponseInvalid
    return _MISSING


def _response_number_text(
    row: dict[str, Any],
    *names: str,
    required: bool = False,
    empty_absent: bool = False,
) -> str | object:
    number = _response_decimal(row, *names, required=required, empty_absent=empty_absent)
    if number is _MISSING:
        return _MISSING
    for name in names:
        if name not in row or row[name] is None:
            continue
        value = row[name]
        if empty_absent and type(value) is str and not value.strip():
            continue
        return value.encode("utf-8").decode("utf-8") if type(value) is str else str(value)
    raise BrokerReadResponseInvalid


def _response_exchange(row: dict[str, Any], *names: str) -> str:
    segment = _response_text(row, *names, required=True)
    try:
        return KOTAK_TO_EXCHANGE[segment.lower()]
    except KeyError:
        raise BrokerReadResponseInvalid from None


def _response_identifier(row: dict[str, Any], name: str) -> str:
    value = _response_text(row, name, required=True)
    if value != value.strip() or not value.isprintable() or any(character.isspace() for character in value):
        raise BrokerReadResponseInvalid
    return value


def _response_product(row: dict[str, Any], name: str = "prod") -> str:
    value = _response_text(row, name, required=True)
    try:
        return KOTAK_TO_PRODUCT[value.upper()]
    except KeyError:
        raise BrokerReadResponseInvalid from None


def _put_present(target: dict[str, Any], name: str, value: object) -> None:
    if value is not _MISSING:
        target[name] = value


def _market_number(
    row: dict[str, Any],
    *names: str,
    integer: bool = False,
) -> float | int | object:
    """Copy the first present market-data alias after exact primitive validation."""
    for name in names:
        if name not in row:
            continue
        number = _response_decimal(row, name, required=True)
        converted = float(number)
        if not math.isfinite(converted):
            raise BrokerReadResponseInvalid from None
        if integer:
            if number < 0 or number != number.to_integral_value():
                raise BrokerReadResponseInvalid from None
            return int(number)
        return converted
    return _MISSING


def _market_text(row: dict[str, Any], *names: str) -> str | object:
    for name in names:
        if name not in row:
            continue
        return _response_text(row, name, required=True)
    return _MISSING


def _quote_depth_price(depth: dict[str, Any], side: str) -> float | object:
    if side not in depth:
        return _MISSING
    rows = depth[side]
    if type(rows) is not list:
        raise BrokerReadResponseInvalid from None
    if not rows:
        return _MISSING
    level = _response_record(rows[0])
    return _market_number(level, "price")


def _num(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _strict_decimal(
    value: object,
    *,
    label: str,
    positive: bool = False,
    whole: bool = False,
) -> Decimal:
    """Parse a caller-supplied order number without coercion or defaults."""
    if isinstance(value, bool) or type(value) not in (int, float, str, Decimal):
        raise KotakNeoMappingError(f"Kotak Neo {label} must be a finite number")
    if type(value) is str and not value.strip():
        raise KotakNeoMappingError(f"Kotak Neo {label} must be a finite number")
    try:
        number = Decimal(str(value).strip())
    except (InvalidOperation, ValueError):
        raise KotakNeoMappingError(f"Kotak Neo {label} must be a finite number") from None
    if not number.is_finite():
        raise KotakNeoMappingError(f"Kotak Neo {label} must be a finite number")
    if not _bounded_decimal_shape(number):
        raise KotakNeoMappingError(f"Kotak Neo {label} exceeds supported numeric bounds")
    if positive and number <= 0:
        raise KotakNeoMappingError(f"Kotak Neo {label} must be positive")
    if not positive and number < 0:
        raise KotakNeoMappingError(f"Kotak Neo {label} cannot be negative")
    if whole and number != number.to_integral_value():
        raise KotakNeoMappingError(f"Kotak Neo {label} must be a whole number")
    return Decimal(0) if number == 0 else number


def _bounded_decimal_shape(number: Decimal) -> bool:
    """Return whether fixed-point rendering stays within the v3 wire budget."""
    _sign, digits, exponent = number.as_tuple()
    significant_digits = len(digits)
    integer_digits = max(significant_digits + exponent, 0)
    scale = max(-exponent, 0)
    return (
        significant_digits <= _MAX_NUMERIC_DIGITS
        and integer_digits <= _MAX_NUMERIC_INTEGER_DIGITS
        and scale <= _MAX_NUMERIC_SCALE
    )


def _decimal_text(number: Decimal) -> str:
    return format(number, "f")


def _whole_text(number: Decimal) -> str:
    return str(int(number))


def _canonical_identifier(value: object, *, label: str) -> str:
    if not isinstance(value, str):
        raise KotakNeoMappingError(f"Kotak Neo {label} is not canonical")
    if (
        not value
        or value != value.strip()
        or not value.isprintable()
        or any(character.isspace() for character in value)
    ):
        raise KotakNeoMappingError(f"Kotak Neo {label} is not canonical")
    return value


def _canonical_text(value: object, *, label: str) -> str:
    if not isinstance(value, str) or not value or value != value.strip() or not value.isprintable():
        raise KotakNeoMappingError(f"Kotak Neo {label} is not canonical")
    return value


def canonical_order_id(value: object) -> str:
    """Return a transport-safe broker order id or fail closed."""
    return _canonical_identifier(value, label="order id")


def canonical_instrument_token(value: object) -> str:
    """Return one bounded positive numeric token without expanding huge ints."""
    if isinstance(value, bool):
        raise KotakNeoMappingError("Kotak Neo instrument token is not canonical")
    if type(value) is int:
        # 10**5000 cannot safely be converted to text on current Python builds.
        # A 64-digit positive decimal needs at most 213 bits, so reject larger
        # primitive ints before calling ``str``.
        if value <= 0 or value.bit_length() > 213:
            raise KotakNeoMappingError("Kotak Neo instrument token is not canonical")
        token = str(value)
    elif type(value) is str:
        token = value
    else:
        raise KotakNeoMappingError("Kotak Neo instrument token is not canonical")
    if (
        not token
        or len(token) > _MAX_NUMERIC_INTEGER_DIGITS
        or not token.isascii()
        or not token.isdigit()
        or not any(character != "0" for character in token)
    ):
        raise KotakNeoMappingError("Kotak Neo instrument token is not canonical")
    return token


def _validated_order_numbers(order: Any, price_type: str) -> tuple[Decimal, Decimal, Decimal, Decimal]:
    quantity = _strict_decimal(order.quantity, label="quantity", positive=True, whole=True)
    price = _strict_decimal(getattr(order, "price", 0), label="price")
    trigger = _strict_decimal(getattr(order, "trigger_price", 0), label="trigger price")
    disclosed = _strict_decimal(
        getattr(order, "disclosed_quantity", 0),
        label="disclosed quantity",
        whole=True,
    )
    if price_type in {"LIMIT", "SL"} and price <= 0:
        raise KotakNeoMappingError(f"Kotak Neo {price_type} price must be positive")
    if price_type in {"SL", "SL-M"} and trigger <= 0:
        raise KotakNeoMappingError(f"Kotak Neo {price_type} trigger price must be positive")
    return quantity, price, trigger, disclosed


def _present_order_number(record: dict[str, Any], key: str) -> str | None:
    if key not in record:
        return None
    value = record[key]
    if value is None or (isinstance(value, str) and not value.strip()):
        return None
    return str(value)


def _norm(value: Any, default: str = "") -> str:
    return str(value).upper() if value is not None else default


def validate_v3_order(order: Any) -> tuple[str, str, str, str, str, str]:
    """Validate the regular/AMO order shape supported by the v3 SDK.

    This is deliberately callable before symbol/token resolution so an
    unsupported write cannot cause even a preparatory SDK request.
    """
    side = _norm(order.action)
    if side not in SIDE_TO_KOTAK:
        raise KotakNeoMappingError(f"Unsupported action {side!r}")
    price_type = _norm(getattr(order, "pricetype", "MARKET"))
    if price_type not in ORDER_TYPE_TO_KOTAK:
        raise KotakNeoMappingError(f"Unsupported pricetype {price_type!r}")
    product = _norm(order.product)
    if product not in PRODUCT_TO_KOTAK:
        raise KotakNeoMappingError(f"Unsupported product {product!r}")
    exchange = _norm(order.exchange)
    if exchange not in ORDER_EXCHANGES:
        raise KotakNeoMappingError(f"Unsupported exchange {exchange!r}")
    validity = _norm(getattr(order, "validity", None) or "DAY")
    if validity not in VALIDITY_ALLOWED:
        raise KotakNeoMappingError(f"Unsupported validity {validity!r}")
    if exchange == "MCX" and validity != "DAY":
        raise KotakNeoMappingError("Kotak Neo MCX orders support DAY validity only")
    variety = str(getattr(order, "variety", "regular")).lower()
    if variety not in {"", "regular", "amo"}:
        raise KotakNeoMappingError(f"Kotak Neo v3 does not support order variety {variety!r}")
    if getattr(order, "market_protection", None) is not None:
        raise KotakNeoMappingError("Kotak Neo v3 does not support caller market protection")
    _validated_order_numbers(order, price_type)
    return side, price_type, product, exchange, validity, variety


def to_place_order_params(order: Any, trading_symbol: str, *, tag: str | None = None) -> dict[str, Any]:
    """Translate a FlintTrade ``Order`` into ``NeoAPI.place_order`` kwargs.

    ``trading_symbol`` is the NEO scrip symbol (e.g. ``"IDEA-EQ"``), resolved by
    the adapter via ``search_scrip``. NEO expects every numeric field as a string.
    Raises ``KotakNeoMappingError`` for unmappable enum values.
    """
    side, ptype, product, exchange, validity, variety = validate_v3_order(order)
    quantity, price, trigger, disclosed = _validated_order_numbers(order, ptype)
    resolved_symbol = _canonical_identifier(trading_symbol, label="trading symbol")

    params: dict[str, Any] = {
        "exchange_segment": EXCHANGE_TO_KOTAK[exchange],
        "product": PRODUCT_TO_KOTAK[product],
        "price": _decimal_text(price),
        "order_type": ORDER_TYPE_TO_KOTAK[ptype],
        "quantity": _whole_text(quantity),
        "validity": validity,
        "trading_symbol": resolved_symbol,
        "transaction_type": SIDE_TO_KOTAK[side],
        "trigger_price": _decimal_text(trigger),
        "disclosed_quantity": _whole_text(disclosed),
        "amo": "NO",
    }

    if variety == "amo":
        params["amo"] = "YES"
    if tag is not None:
        params["tag"] = _canonical_identifier(tag, label="tag")
    return params


_MODIFY_V3_INPUT_FIELDS = frozenset(
    {
        "pricetype",
        "order_type",
        "price",
        "quantity",
        "validity",
        "trigger_price",
        "disclosed_quantity",
        "amo",
        # Signed route context. These values are validated here but never sent
        # to the SDK's exact v3 order-id method.
        "symbol",
        "exchange",
        "action",
        "product",
        "strategy",
        "broker_product",
        "variety",
    }
)


def to_modify_order_params(order_id: str, changes: dict[str, Any]) -> dict[str, Any]:
    """Translate modify ``changes`` into ``NeoAPI.modify_order`` kwargs.

    V3 retains only the order-id method. Removed quick-method and legacy fields
    are rejected rather than silently discarded or forwarded to the SDK.
    """
    if type(changes) is not dict or any(type(key) is not str for key in changes):
        raise KotakNeoMappingError("Kotak Neo v3 modify changes must be a string-keyed object")
    unsupported = sorted(set(changes) - _MODIFY_V3_INPUT_FIELDS)
    if unsupported:
        raise KotakNeoMappingError(f"Kotak Neo v3 modify does not support fields {unsupported}")
    canonical_order_id_value = canonical_order_id(order_id)
    if "symbol" in changes:
        _canonical_identifier(changes["symbol"], label="symbol")
    exchange = ""
    if "exchange" in changes:
        exchange = _canonical_identifier(changes["exchange"], label="exchange").upper()
        if exchange not in ORDER_EXCHANGES:
            raise KotakNeoMappingError(f"Unsupported exchange {exchange!r}")
    if "action" in changes:
        action = _norm(changes["action"])
        if action not in SIDE_TO_KOTAK:
            raise KotakNeoMappingError(f"Unsupported action {action!r}")
    if "product" in changes:
        product = _norm(changes["product"])
        if product not in PRODUCT_TO_KOTAK:
            raise KotakNeoMappingError(f"Unsupported product {product!r}")
    broker_product = _norm(changes.get("broker_product"))
    if broker_product:
        if broker_product not in KOTAK_TO_PRODUCT:
            raise KotakNeoMappingError(f"Unsupported broker product {broker_product!r}")
        if broker_product in {"BO", "CO"}:
            variety_name = "bracket" if broker_product == "BO" else "cover"
            raise KotakNeoMappingError(f"Kotak Neo v3 cannot modify {variety_name} orders")
    variety = str(changes.get("variety", "")).strip().lower()
    if variety and variety not in {"regular", "amo"}:
        raise KotakNeoMappingError(f"Kotak Neo v3 cannot modify order variety {variety!r}")
    if "strategy" in changes:
        _canonical_text(changes["strategy"], label="strategy")

    ptype = _norm(changes.get("pricetype", changes.get("order_type", "LIMIT")))
    if ptype in ORDER_TYPE_TO_KOTAK:
        mapped_order_type = ORDER_TYPE_TO_KOTAK[ptype]
    elif ptype in ORDER_TYPE_TO_KOTAK.values():
        mapped_order_type = ptype
    else:
        raise KotakNeoMappingError(f"Unsupported order type {ptype!r}")
    validity = str(changes.get("validity", "DAY")).upper()
    if validity not in VALIDITY_ALLOWED:
        raise KotakNeoMappingError(f"Unsupported validity {validity!r}")
    if exchange == "MCX" and validity != "DAY":
        raise KotakNeoMappingError("Kotak Neo MCX orders support DAY validity only")
    quantity = _strict_decimal(changes.get("quantity"), label="quantity", positive=True, whole=True)
    price = _strict_decimal(changes.get("price", 0), label="price")
    trigger = _strict_decimal(changes.get("trigger_price", 0), label="trigger price")
    disclosed = _strict_decimal(
        changes.get("disclosed_quantity", 0),
        label="disclosed quantity",
        whole=True,
    )
    semantic_type = KOTAK_TO_ORDER_TYPE.get(mapped_order_type, mapped_order_type)
    if semantic_type in {"LIMIT", "SL"} and price <= 0:
        raise KotakNeoMappingError(f"Kotak Neo {semantic_type} price must be positive")
    if semantic_type in {"SL", "SL-M"} and trigger <= 0:
        raise KotakNeoMappingError(f"Kotak Neo {semantic_type} trigger price must be positive")
    params: dict[str, Any] = {
        "order_id": canonical_order_id_value,
        "order_type": mapped_order_type,
        "price": _decimal_text(price),
        "quantity": _whole_text(quantity),
        "validity": validity,
        "trigger_price": _decimal_text(trigger),
        "disclosed_quantity": _whole_text(disclosed),
    }
    if "amo" in changes:
        amo = changes["amo"]
        amo_value = ("YES" if amo else "NO") if isinstance(amo, bool) else _norm(amo)
        if amo_value not in {"YES", "NO"}:
            raise KotakNeoMappingError(f"Unsupported AMO flag {amo!r}")
        if variety and (variety == "amo") != (amo_value == "YES"):
            raise KotakNeoMappingError("Kotak Neo modify variety and AMO flag disagree")
        params["amo"] = amo_value
    return params


def ensure_ok(resp: Any) -> Any:
    """Raise ``KotakNeoMappingError`` if ``resp`` is a NEO error envelope.

    The Kotak Neo v3 SDK returns errors as data, never raises: ``{"Error": ...}``
    (SDK exception wrapper), ``{"Error Message": ...}`` (2FA not complete),
    ``{"error": [...]}`` (validation), ``{"status": "error", "message": ...}``
    (TOTP/MPIN login reject) and ``{"stat": "Not_Ok", "errMsg"/"emsg": ...}``
    (OMS reject). Writes and login MUST surface those instead of silently
    succeeding.
    """
    if isinstance(resp, dict):
        for key in ("Error", "Error Message", "error"):
            if resp.get(key):
                raise KotakNeoMappingError(f"Kotak Neo error: {resp[key]!r}")
        data = resp.get("data") if isinstance(resp.get("data"), dict) else {}
        status = resp.get("status", data.get("status"))
        if status is not None and str(status).lower() not in ("success", "ok", ""):
            message = resp.get("message") or data.get("message") or resp.get("emsg") or resp.get("errMsg") or resp
            raise KotakNeoMappingError(f"Kotak Neo rejected the request: {message!r}")
        if str(resp.get("stat", "Ok")).lower() not in ("ok", ""):
            raise KotakNeoMappingError(
                f"Kotak Neo rejected the request: {resp.get('errMsg') or resp.get('emsg') or resp!r}"
            )
    return resp


def require_write_success(resp: Any, *, expected_order_id: str | None = None) -> dict[str, Any]:
    """Require Kotak's documented affirmative write acknowledgement.

    ``ensure_ok`` remains deliberately tolerant for legacy read surfaces. Live
    mutations need the stronger contract documented by the place/modify/cancel APIs:
    an object with ``stat=Ok``, integer ``stCode=200`` and a canonical order
    number. When modifying or cancelling, that number must be the exact
    requested order.
    """
    ensure_ok(resp)
    if not isinstance(resp, dict):
        raise KotakNeoMappingError("Kotak Neo write response is malformed")
    status = resp.get("stat")
    status_code = resp.get("stCode")
    order_id = resp.get("nOrdNo")
    if not order_id:
        data = resp.get("data")
        if isinstance(data, dict):
            order_id = data.get("nOrdNo") or data.get("orderId")
    if not isinstance(status, str) or status.strip().lower() != "ok":
        raise KotakNeoMappingError("Kotak Neo write response has no explicit success status")
    if isinstance(status_code, bool) or not isinstance(status_code, int) or status_code != 200:
        raise KotakNeoMappingError("Kotak Neo write response has no explicit HTTP 200 status")
    if (
        not isinstance(order_id, str)
        or not order_id
        or order_id != order_id.strip()
        or not order_id.isprintable()
        or any(character.isspace() for character in order_id)
    ):
        raise KotakNeoMappingError("Kotak Neo write response has no canonical order id")
    if expected_order_id is not None and order_id != expected_order_id:
        raise KotakNeoMappingError("Kotak Neo write acknowledged a different order id")
    return resp


def extract_order_id(resp: dict[str, Any]) -> str:
    """Pull the order number from a NEO place/modify response.

    NEO returns ``{"stat": "Ok", "nOrdNo": "...", "stCode": 200}`` (the order id
    may also be nested under ``data`` on some gateway builds).
    """
    if not isinstance(resp, dict):
        raise KotakNeoMappingError(f"Unexpected NEO response: {resp!r}")
    oid = resp.get("nOrdNo")
    if not oid:
        data = resp.get("data")
        if isinstance(data, dict):
            oid = data.get("nOrdNo") or data.get("orderId")
    if not oid:
        raise KotakNeoMappingError(f"No order id in NEO response: {resp!r}")
    return str(oid)


def _exchange_of(d: dict[str, Any]) -> str:
    seg = str(d.get("exSeg", ""))
    return KOTAK_TO_EXCHANGE.get(seg, seg)


def from_kotak_order(d: dict[str, Any]) -> dict[str, Any]:
    """Normalise a NEO order-report / order-history record.

    Both surfaces share the terse OMS vocabulary (``Order_report.md`` /
    ``Order_history.md``); history rows carry ``exchTmstp``+``dclQty`` where the
    report uses ``ordDtTm``+``dscQty``, so each field falls back across both.
    """
    d = _response_record(d)
    side = _response_text(d, "trnsTp", required=True).upper()
    price_type = _response_text(d, "prcTp", required=True).upper()
    broker_product = _response_text(d, "prod", required=True).upper()
    try:
        action = KOTAK_TO_SIDE[side]
        canonical_price_type = KOTAK_TO_ORDER_TYPE[price_type]
        canonical_product = KOTAK_TO_PRODUCT[broker_product]
    except KeyError:
        raise BrokerReadResponseInvalid from None
    order = {
        "orderid": _response_text(d, "nOrdNo", required=True),
        "status": _response_text(d, "ordSt", "stat", required=True),
        "symbol": _response_text(d, "trdSym", "sym", required=True),
        "exchange": _response_exchange(d, "exSeg"),
        "action": action,
        "pricetype": canonical_price_type,
        "product": canonical_product,
        "broker_product": broker_product,
    }
    if broker_product == "BO":
        order["variety"] = "bracket"
    elif broker_product == "CO":
        order["variety"] = "cover"
    if "ordGenTp" in d:
        raw_generation = d["ordGenTp"]
        if type(raw_generation) is not str or raw_generation != raw_generation.strip() or not raw_generation.isprintable():
            raise BrokerReadResponseInvalid
        generation = raw_generation.upper()
        if generation not in {"", "NA", "--", "AMO"}:
            raise BrokerReadResponseInvalid
        order["amo"] = generation == "AMO"
        if broker_product not in {"BO", "CO"}:
            order["variety"] = "amo" if order["amo"] else "regular"
    for field, value in {
        "timestamp": _response_text(d, "ordDtTm", "exchTmstp", "flDtTm", empty_absent=True),
        "validity": _response_text(d, "vldt", "ordDur", empty_absent=True),
        "disclosed_quantity": _response_number_text(d, "dscQty", "dclQty", empty_absent=True),
        "tag": _response_text(d, "GuiOrdId"),
    }.items():
        _put_present(order, field, value)
    rejection = _response_text(d, "rejRsn")
    if rejection is not _MISSING:
        order["rejection_reason"] = "" if rejection in {"--", "NA"} else rejection
    exchange_order_id = _response_text(d, "exOrdId", "exchOrdId", empty_absent=True)
    if exchange_order_id is not _MISSING:
        order["exchange_order_id"] = "" if exchange_order_id == "NA" else exchange_order_id
    for field, source_field in {
        "quantity": "qty",
        "filled_quantity": "fldQty",
        "price": "prc",
        "trigger_price": "trgPrc",
        "average_price": "avgPrc",
    }.items():
        _put_present(order, field, _response_number_text(d, source_field, empty_absent=True))
    return order


def order_history_rows(resp: Any) -> list[dict[str, Any]]:
    """Unwrap the doubly-nested ``order_history`` envelope into raw OMS rows.

    The SDK returns ``{"data": {"stat": "Ok", "stCode": 200, "data": [rows]}}``
    (``Order_history.md``); some gateway builds skip the outer wrapper. Rows are
    the order's state transitions, OMS-newest-first.
    """
    if not isinstance(resp, dict):
        return []
    inner = resp.get("data", resp)
    if isinstance(inner, dict):
        inner = inner.get("data", [])
    return [r for r in inner if isinstance(r, dict)] if isinstance(inner, list) else []


def from_kotak_trade(d: dict[str, Any]) -> dict[str, Any]:
    """Normalise a NEO trade-report record."""
    d = _response_record(d)
    side = _response_text(d, "trnsTp", required=True).upper()
    try:
        action = KOTAK_TO_SIDE[side]
    except KeyError:
        raise BrokerReadResponseInvalid from None
    trade = {
        "orderid": _response_identifier(d, "nOrdNo"),
        "symbol": _response_text(d, "trdSym", "sym", required=True),
        "exchange": _response_exchange(d, "exSeg"),
        "action": action,
        "quantity": _response_number_text(d, "fldQty", "qty", required=True),
        "price": _response_number_text(d, "avgPrc", "flPrc", required=True),
        "product": _response_product(d),
        "timestamp": _response_text(d, "flDtTm", "exTm", required=True),
    }
    return trade


def _ratio(num: Any, den: Any) -> float:
    """``num/den`` defaulting to 1.0 (NEO price-denomination ratios genNum/genDen
    and prcNum/prcDen are 1 for equity; non-1 only for some commodity/currency)."""
    n = _num(num, 1.0)
    d = _num(den, 1.0)
    return (n / d) if d else 1.0


def _fmt_qty(value: float) -> str:
    """Format a quantity as an integer string (positions are whole units)."""
    return str(int(round(value)))


def from_kotak_position(d: dict[str, Any]) -> dict[str, Any]:
    """Normalise a NEO position record.

    NEO reports cumulative carry-forward + intraday buy/sell legs rather than a
    net line, so the net quantity, average price and **realised** P&L are derived
    here (``Positions.md``).

    Quantity is kept in raw traded units (shares/contracts), NOT divided by
    ``lotSz`` — FlintTrade reports total quantity across every adapter (Dhan /
    OpenAlgo do the same), so a lots-based F&O display would be an adapter-level
    inconsistency; that normalisation, if ever wanted, belongs at the Position
    layer. Average price is per-unit and follows the documented denominator
    (``Positions.md`` §"Avg Price Fields"): ``amount / (qty * multiplier *
    genNum/genDen * prcNum/prcDen)`` rounded to the scrip ``precision``. The
    ``multiplier`` term does NOT cancel — it is 1 for equity but ≠1 for some
    currency / commodity derivatives, so omitting it overstates the avg price on
    those scrips.

    P&L is the **realised** component only — ``matched_qty * (sell_avg -
    buy_avg) * unit_factor`` where ``matched_qty = min(buy_qty, sell_qty)`` and
    ``unit_factor = multiplier * genNum/genDen * prcNum/prcDen`` (the same
    per-unit factor used for the avg, so the value is amount-consistent on
    multiplier≠1 scrips). The open leg's unrealised P&L needs a live LTP not in
    the record and is left to merge from quotes; no LTP is fabricated.
    """
    d = _response_record(d)
    quantity_names = ("cfBuyQty", "flBuyQty", "cfSellQty", "flSellQty")
    quantities = {name: _response_decimal(d, name, required=True) for name in quantity_names}
    if any(number < 0 or number != number.to_integral_value() for number in quantities.values()):
        raise BrokerReadResponseInvalid
    buy_qty = quantities["cfBuyQty"] + quantities["flBuyQty"]
    sell_qty = quantities["cfSellQty"] + quantities["flSellQty"]
    net_qty = buy_qty - sell_qty
    position: dict[str, Any] = {
        "symbol": _response_text(d, "trdSym", "sym", required=True),
        "exchange": _response_exchange(d, "exSeg"),
        "product": _response_product(d),
        "quantity": str(int(net_qty)),
        "buy_quantity": str(int(buy_qty)),
        "sell_quantity": str(int(sell_qty)),
        "day_buy_quantity": str(int(quantities["flBuyQty"])),
        "day_sell_quantity": str(int(quantities["flSellQty"])),
        "carry_forward_buy_quantity": str(int(quantities["cfBuyQty"])),
        "carry_forward_sell_quantity": str(int(quantities["cfSellQty"])),
    }
    amount_names = ("cfBuyAmt", "buyAmt", "cfSellAmt", "sellAmt")
    amounts = {name: _response_decimal(d, name) for name in amount_names}
    if not all(value is not _MISSING for value in amounts.values()):
        return position
    quantity_amount_pairs = (
        (quantities["cfBuyQty"], amounts["cfBuyAmt"]),
        (quantities["flBuyQty"], amounts["buyAmt"]),
        (quantities["cfSellQty"], amounts["cfSellAmt"]),
        (quantities["flSellQty"], amounts["sellAmt"]),
    )
    if any(amount < 0 or (quantity == 0 and amount != 0) for quantity, amount in quantity_amount_pairs):
        raise BrokerReadResponseInvalid
    factor_names = ("genNum", "genDen", "prcNum", "prcDen", "multiplier", "precision")
    factors = {name: _response_decimal(d, name) for name in factor_names}
    if not all(value is not _MISSING for value in factors.values()):
        return position
    if any(factors[name] <= 0 for name in ("genNum", "genDen", "prcNum", "prcDen", "multiplier")):
        raise BrokerReadResponseInvalid
    precision_value = factors["precision"]
    if precision_value != precision_value.to_integral_value() or not 0 <= precision_value <= 8:
        raise BrokerReadResponseInvalid
    precision = int(precision_value)
    unit_factor = (
        factors["multiplier"]
        * factors["genNum"]
        / factors["genDen"]
        * factors["prcNum"]
        / factors["prcDen"]
    )
    if not unit_factor.is_finite() or unit_factor == 0:
        raise BrokerReadResponseInvalid
    buy_amount = amounts["cfBuyAmt"] + amounts["buyAmt"]
    sell_amount = amounts["cfSellAmt"] + amounts["sellAmt"]
    if (buy_qty == 0 and buy_amount != 0) or (sell_qty == 0 and sell_amount != 0):
        raise BrokerReadResponseInvalid
    buy_avg = buy_amount / (buy_qty * unit_factor) if buy_qty else Decimal(0)
    sell_avg = sell_amount / (sell_qty * unit_factor) if sell_qty else Decimal(0)
    average = buy_avg if buy_qty > sell_qty else sell_avg if sell_qty > buy_qty else Decimal(0)
    realised = min(buy_qty, sell_qty) * (sell_avg - buy_avg) * unit_factor
    if not realised:
        realised = Decimal(0)
    position.update(
        {
            "average_price": f"{average:.{precision}f}",
            "pnl": f"{realised:.2f}",
            "buy_avg": f"{buy_avg:.{precision}f}",
            "sell_avg": f"{sell_avg:.{precision}f}",
            "accounting_complete": True,
        }
    )
    return position


def from_kotak_holding(d: dict[str, Any]) -> dict[str, Any]:
    """Normalise a NEO holding record.

    The holdings endpoint uses longer keys than the OMS order/position feed
    (``displaySymbol``/``averagePrice``/``closingPrice`` …). ``closingPrice`` is
    the previous-day close, so it is surfaced only as ``close_price``. A live
    quote must supply LTP; aggregate ``mktValue`` is never treated as a price.
    """
    d = _response_record(d)
    holding = {
        "symbol": _response_text(d, "displaySymbol", "symbol", "trdSym", required=True),
        "exchange": _response_exchange(d, "exchangeSegment", "exSeg"),
        "quantity": _response_number_text(d, "quantity", "sellableQuantity", required=True),
    }
    for field, value in {
        "average_price": _response_number_text(d, "averagePrice", "avgPrc"),
        "close_price": _response_number_text(d, "closingPrice"),
        "pnl": _response_number_text(d, "unrealisedGainLoss", "pnl"),
    }.items():
        _put_present(holding, field, value)
    return holding


def from_kotak_scrip(rec: dict[str, Any]) -> dict[str, Any]:
    """Normalise one NEO ``search_scrip`` record into a scrip-lookup dict.

    NEO returns scrip metadata with ``p``-prefixed keys; the ``pTrdSymbol`` is the
    trading symbol the order endpoints expect and ``pSymbol`` is the token.
    """
    seg = str(rec.get("pExchSeg", ""))
    try:
        token = canonical_instrument_token(rec.get("pSymbol"))
    except KotakNeoMappingError:
        raise BrokerReadResponseInvalid from None
    return {
        "trading_symbol": rec.get("pTrdSymbol", ""),
        "token": token,
        "name": rec.get("pSymbolName", rec.get("pDesc", "")),
        "exchange": KOTAK_TO_EXCHANGE.get(seg, seg),
        "isin": rec.get("pISIN", ""),
        "lot_size": str(rec.get("lLotSize", 0)),
        "tick_size": str(rec.get("dTickSize", 0)),
        "option_type": rec.get("pOptionType") or "",
    }


def to_margin_params(order: Any, instrument_token: str) -> dict[str, Any]:
    """Build ``NeoAPI.margin_required`` kwargs from an ``Order`` (pre-trade).

    ``instrument_token`` must be the positive numeric ``pSymbol``. V3 has no
    ``trading_symbol`` argument here, and this adapter does not estimate removed
    BO/CO varieties.
    """
    side, ptype, product, exchange, _validity, _variety = validate_v3_order(order)
    quantity, price, trigger, _disclosed = _validated_order_numbers(order, ptype)
    if type(instrument_token) is not str:
        raise KotakNeoMappingError("Kotak Neo margin requires a positive numeric instrument_token")
    token = instrument_token
    if (
        len(token) > _MAX_NUMERIC_INTEGER_DIGITS
        or not token.isascii()
        or not token.isdigit()
        or not any(character != "0" for character in token)
    ):
        raise KotakNeoMappingError("Kotak Neo margin requires a positive numeric instrument_token")
    params: dict[str, Any] = {
        "exchange_segment": EXCHANGE_TO_KOTAK[exchange],
        "price": _decimal_text(price),
        "order_type": ORDER_TYPE_TO_KOTAK[ptype],
        "product": PRODUCT_TO_KOTAK[product],
        "quantity": _whole_text(quantity),
        "instrument_token": token,
        "transaction_type": SIDE_TO_KOTAK[side],
    }
    if trigger > 0:
        params["trigger_price"] = _decimal_text(trigger)
    return params


def to_limits_params(segment: str = "ALL", exchange: str = "ALL", product: str = "ALL") -> dict[str, str]:
    """Reject filters removed from the v3 no-argument ``limits()`` call."""
    seg, exch, prod = _norm(segment, "ALL"), _norm(exchange, "ALL"), _norm(product, "ALL")
    if (seg, exch, prod) != ("ALL", "ALL", "ALL"):
        raise KotakNeoMappingError("Kotak Neo v3 limits does not support server-side filters")
    return {}


def from_kotak_margin(resp: dict[str, Any]) -> dict[str, Any]:
    """Normalise a NEO ``margin_required`` response into FlintTrade margin fields."""
    envelope = _response_record(resp)
    data = _response_record(envelope.get("data"))
    status = _response_text(data, "stat", required=True)
    status_code = data.get("stCode")
    if status.lower() != "ok" or isinstance(status_code, bool) or type(status_code) is not int:
        raise BrokerReadResponseInvalid
    if status_code != 200:
        raise BrokerReadResponseInvalid
    order_margin = _response_decimal(data, "ordMrgn", required=True)
    additional_margin = _response_decimal(data, "reqdMrgn", required=True)
    available_cash = _response_decimal(data, "avlCash", required=True)
    insufficient = _response_decimal(data, "insufFund", required=True)
    if any(number < 0 for number in (order_margin, additional_margin, available_cash, insufficient)):
        raise BrokerReadResponseInvalid
    rms_validated = _response_text(data, "rmsVldtd", required=True)
    if rms_validated != rms_validated.strip() or not rms_validated.isprintable():
        raise BrokerReadResponseInvalid
    for optional_name in ("totMrgnUsd", "mrgnUsd", "avlMrgn"):
        if optional_name in data:
            optional = _response_decimal(data, optional_name, required=True)
            if optional < 0:
                raise BrokerReadResponseInvalid
    return {
        "required_margin": f"{order_margin:.2f}",
        "order_margin": f"{order_margin:.2f}",
        "provider_additional_margin": f"{additional_margin:.2f}",
        "available_balance": f"{available_cash:.2f}",
        "insufficient_balance": f"{insufficient:.2f}",
        "rms_validated": rms_validated,
    }


def to_quote_tokens(resolved: list[tuple[str, str]]) -> list[dict[str, str]]:
    """Build the NEO ``quotes`` request from ``(instrument_token, exchange)`` pairs.

    NEO's ``quotes(instrument_tokens=[...])`` takes a list of
    ``{"instrument_token": <wToken/pSymbol>, "exchange_segment": <seg>}`` dicts.
    The ``instrument_token`` is the numeric scrip token (``pSymbol``), resolved by
    the adapter — only indexes pass a NAME here (``webSocket.md`` "For Indexes").
    This function just shapes whatever resolved value it is given; the
    symbol→token resolution lives in the adapter.
    """
    tokens: list[dict[str, str]] = []
    for instrument_token, exchange in resolved:
        ex = _norm(exchange)
        tokens.append(
            {
                "instrument_token": str(instrument_token),
                "exchange_segment": EXCHANGE_TO_KOTAK.get(ex, ex.lower()),
            }
        )
    return tokens


def from_kotak_quote(
    rec: dict[str, Any],
    *,
    strict: bool = False,
    expected_symbol: str | None = None,
    expected_exchange: str | None = None,
) -> dict[str, Any]:
    """Parse one NEO quote record into a FlintTrade ``Quote`` dict.

    NEO quotes share their key vocabulary with the streaming feed
    (``settings.stock_key_mapping``); the REST surface may return either the long
    names (``last_traded_price``), the terse feed keys (``ltp``), or the current
    public-docs shape (``display_symbol`` / ``exchange`` / nested ``ohlc`` /
    nested ``depth``), so each field falls back across all documented variants.
    Bid/ask prices come from ``buy_price``/``sell_price`` or the first depth
    levels; ``total_buy``/``total_sell`` are quantities, not prices.
    """

    if not strict:
        def g(*keys: str) -> Any:
            for k in keys:
                if k in rec and rec[k] not in (None, ""):
                    return rec[k]
            return 0

        def nested(container: str, key: str) -> Any:
            value = rec.get(container)
            if isinstance(value, dict) and value.get(key) not in (None, ""):
                return value[key]
            return 0

        def depth_price(side: str) -> Any:
            depth = rec.get("depth")
            if not isinstance(depth, dict):
                return 0
            rows = depth.get(side)
            if isinstance(rows, list) and rows and isinstance(rows[0], dict):
                return rows[0].get("price", 0)
            return 0

        seg = str(g("exchange_segment", "exchange", "e") or "")
        return {
            "symbol": g("trading_symbol", "display_symbol", "exchange_token", "ts", "tk") or "",
            "exchange": KOTAK_TO_EXCHANGE.get(seg, seg),
            "ltp": _num(g("last_traded_price", "ltp")),
            "open": _num(g("open", "op") or nested("ohlc", "open")),
            "high": _num(g("high", "h") or nested("ohlc", "high")),
            "low": _num(g("low", "lo") or nested("ohlc", "low")),
            "close": _num(g("close", "c") or nested("ohlc", "close")),
            "volume": int(_num(g("volume", "last_volume", "v"))),
            "bid": _num(g("buy_price", "bp") or depth_price("buy")),
            "ask": _num(g("sell_price", "sp") or depth_price("sell")),
            "prev_close": _num(g("close", "c") or nested("ohlc", "close")),
            "oi": int(_num(g("open_interest", "oi"))),
        }

    record = _response_record(rec)
    ohlc: dict[str, Any] = {}
    if "ohlc" in record:
        ohlc = _response_record(record["ohlc"])
    depth: dict[str, Any] = {}
    if "depth" in record:
        depth = _response_record(record["depth"])
    quote: dict[str, Any] = {}
    if expected_symbol is not None:
        quote["symbol"] = expected_symbol
    else:
        _put_present(
            quote,
            "symbol",
            _market_text(record, "trading_symbol", "display_symbol", "exchange_token", "ts", "tk"),
        )
    if expected_exchange is not None:
        quote["exchange"] = expected_exchange
    else:
        segment = _market_text(record, "exchange_segment", "exchange", "e")
        if segment is not _MISSING:
            quote["exchange"] = KOTAK_TO_EXCHANGE.get(segment.lower(), segment)

    _put_present(quote, "ltp", _market_number(record, "last_traded_price", "ltp"))
    for canonical, aliases in (
        ("open", ("open", "op")),
        ("high", ("high", "h")),
        ("low", ("low", "lo")),
        ("close", ("close", "c")),
    ):
        value = _market_number(record, *aliases)
        if value is _MISSING:
            value = _market_number(ohlc, canonical)
        _put_present(quote, canonical, value)
    if "close" in quote:
        quote["prev_close"] = quote["close"]
    _put_present(quote, "volume", _market_number(record, "volume", "last_volume", "v", integer=True))
    bid = _market_number(record, "buy_price", "bp")
    if bid is _MISSING:
        bid = _quote_depth_price(depth, "buy")
    _put_present(quote, "bid", bid)
    ask = _market_number(record, "sell_price", "sp")
    if ask is _MISSING:
        ask = _quote_depth_price(depth, "sell")
    _put_present(quote, "ask", ask)
    _put_present(quote, "oi", _market_number(record, "open_interest", "oi", integer=True))
    return quote


def from_kotak_scrip_master(resp: Any) -> dict[str, Any]:
    """Normalise a NEO ``scrip_master`` response (``Scrip_Master.md``).

    The unfiltered call returns ``{"filesPaths": [...], "baseFolder": "..."}``;
    a segment-filtered call returns the single CSV URL as a bare string.
    """
    if isinstance(resp, str):
        return {"base_folder": "", "files": [resp]}
    if isinstance(resp, dict):
        files = resp.get("filesPaths", [])
        return {
            "base_folder": str(resp.get("baseFolder", "")),
            "files": [str(f) for f in files] if isinstance(files, list) else [],
        }
    return {"base_folder": "", "files": []}


def _depth_levels(rec: dict[str, Any], price_keys: list[str], qty_keys: list[str], ord_keys: list[str]) -> list[dict]:
    return [
        {
            "price": _num(rec.get(p, 0)),
            "quantity": int(_num(rec.get(q, 0))),
            "orders": int(_num(rec.get(o, 0))),
        }
        for p, q, o in zip(price_keys, qty_keys, ord_keys)
    ]


def _normalise_depth_levels(rows: Any) -> list[dict]:
    """Return depth levels with FlintTrade's numeric price/quantity/orders keys."""
    if not isinstance(rows, list):
        return []
    levels: list[dict] = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        levels.append(
            {
                "price": _num(row.get("price", 0)),
                "quantity": int(_num(row.get("quantity", 0))),
                "orders": int(_num(row.get("orders", 0))),
            }
        )
    return levels


def from_kotak_depth(rec: dict[str, Any]) -> dict[str, Any]:
    """Normalise one NEO market-depth record into FlintTrade ``Depth`` fields.

    Handles BOTH shapes: the SDK's pre-shaped ``{"depth": {"buy": [...],
    "sell": [...]}}`` / current public-docs quote-depth response and the raw
    terse frame (``bp..bp4`` / ``sp..sp4`` / ``bq..bq4`` / ``bs..bs4`` /
    ``bno1..5`` / ``sno1..5`` — ``webSocket.md`` "For Depth").
    """
    seg = str(rec.get("exchange_segment", rec.get("exchange", rec.get("e", ""))) or "")
    out: dict[str, Any] = {
        "symbol": str(
            rec.get("trading_symbol", rec.get("display_symbol", rec.get("exchange_token", rec.get("ts", "")))) or ""
        ),
        "exchange": KOTAK_TO_EXCHANGE.get(seg, seg),
        "token": str(rec.get("instrument_token", rec.get("exchange_token", rec.get("tk", ""))) or ""),
    }
    depth = rec.get("depth")
    if isinstance(depth, dict):
        out["bids"] = _normalise_depth_levels(depth.get("buy", []))
        out["asks"] = _normalise_depth_levels(depth.get("sell", []))
        return out
    out["bids"] = _depth_levels(
        rec,
        ["bp", "bp1", "bp2", "bp3", "bp4"],
        ["bq", "bq1", "bq2", "bq3", "bq4"],
        ["bno1", "bno2", "bno3", "bno4", "bno5"],
    )
    out["asks"] = _depth_levels(
        rec,
        ["sp", "sp1", "sp2", "sp3", "sp4"],
        ["bs", "bs1", "bs2", "bs3", "bs4"],
        ["sno1", "sno2", "sno3", "sno4", "sno5"],
    )
    return out


def subscription_flags(mode: str) -> tuple[bool, bool]:
    """Map a FlintTrade subscription mode to NEO's ``(isIndex, isDepth)`` pair.

    HSM subscription types (``settings.ReqTypeValues``): scrip feed ``mws``
    (LTP/QUOTE), depth feed ``dps`` (DEPTH/FULL) and index feed ``ifs`` (INDEX).
    """
    m = _norm(mode, "FULL")
    if m in ("LTP", "QUOTE"):
        return False, False
    if m in ("FULL", "DEPTH"):
        return False, True
    if m == "INDEX":
        return True, False
    raise KotakNeoMappingError(f"Unsupported subscription mode {mode!r}")


def _feed_records(frame: Any) -> list[dict[str, Any]]:
    """Extract the record list from one HSM feed delivery (tolerant)."""
    if isinstance(frame, str):
        try:
            frame = json.loads(frame)
        except ValueError:
            return []
    if isinstance(frame, dict):
        if frame.get("type") in ("stock_feed", "quotes"):
            frame = frame.get("data", [])
        elif "tk" in frame or "iv" in frame:
            frame = [frame]
        else:
            return []  # connection ack / unsub ack / heartbeat
    if not isinstance(frame, list):
        return []
    return [r for r in frame if isinstance(r, dict)]


def _fv(rec: dict[str, Any], terse: str, key_map: dict[str, str], default: Any = 0) -> Any:
    """Read a feed field by its terse key, falling back to the mapped long name.

    Raw HSM frames carry the terse keys; SDK-formatted deliveries
    (``quote_resp_mapper``) carry the long names from the same tables.
    """
    if terse in rec:
        return rec[terse]
    return rec.get(key_map.get(terse, terse), default)


def decode_kotak_feed(frame: Any) -> list[dict[str, Any]]:
    """Decode one HSM market-feed delivery into normalised tick dicts.

    Accepts what ``NeoWebSocket`` hands to ``on_message`` (``{"type":
    "stock_feed"|"quotes", "data": [...]}``), a bare record list, or a JSON
    string; connection/unsubscribe acks decode to ``[]``. Each tick dict
    carries ``kind`` (``"quote"`` / ``"index"`` / ``"depth"``); depth ticks
    embed the ``from_kotak_depth`` book under ``"depth"``.
    """
    ticks: list[dict[str, Any]] = []
    for rec in _feed_records(frame):
        if rec.get("request_type") == "cn" or rec.get("type") == "cn":
            continue
        seg = str(rec.get("e", rec.get("exchange_segment", "")) or "")
        base = {
            "symbol": str(rec.get("ts", rec.get("trading_symbol", "")) or ""),
            "exchange": KOTAK_TO_EXCHANGE.get(seg, seg),
            "token": str(rec.get("tk", rec.get("instrument_token", "")) or ""),
        }
        if "iv" in rec or rec.get("name") == "if":
            ticks.append(
                {
                    **base,
                    "kind": "index",
                    "ltp": _num(_fv(rec, "iv", INDEX_FEED_KEYS)),
                    "prev_close": _num(_fv(rec, "ic", INDEX_FEED_KEYS)),
                    "open": _num(_fv(rec, "openingPrice", INDEX_FEED_KEYS)),
                    "high": _num(_fv(rec, "highPrice", INDEX_FEED_KEYS)),
                    "low": _num(_fv(rec, "lowPrice", INDEX_FEED_KEYS)),
                    "volume": 0,
                    "bid": 0.0,
                    "ask": 0.0,
                    "oi": 0,
                    "timestamp": str(_fv(rec, "tvalue", INDEX_FEED_KEYS, "") or ""),
                }
            )
        elif rec.get("name") == "dp" or ("bp1" in rec and "ltp" not in rec):
            book = from_kotak_depth(rec)
            bids, asks = book.get("bids", []), book.get("asks", [])
            ticks.append(
                {
                    **base,
                    "kind": "depth",
                    "ltp": 0.0,
                    "volume": 0,
                    "bid": _num(bids[0]["price"]) if bids else 0.0,
                    "ask": _num(asks[0]["price"]) if asks else 0.0,
                    "oi": 0,
                    "timestamp": "",
                    "depth": book,
                }
            )
        else:
            ticks.append(
                {
                    **base,
                    "kind": "quote",
                    "ltp": _num(_fv(rec, "ltp", STOCK_FEED_KEYS)),
                    "volume": int(_num(_fv(rec, "v", STOCK_FEED_KEYS))),
                    "bid": _num(_fv(rec, "bp", STOCK_FEED_KEYS)),
                    "ask": _num(_fv(rec, "sp", STOCK_FEED_KEYS)),
                    # Best bid/ask size at level 1: NEO's SDK ``stock_key_mapping``
                    # keys these ``bq``/``sq`` (NOT ``bs`` — that is a depth-frame
                    # offer-size key), so the long-name fallback resolves them too.
                    "buy_quantity": int(_num(_fv(rec, "bq", STOCK_FEED_KEYS))),
                    "sell_quantity": int(_num(_fv(rec, "sq", STOCK_FEED_KEYS))),
                    "oi": int(_num(_fv(rec, "oi", STOCK_FEED_KEYS))),
                    "timestamp": str(_fv(rec, "ltt", STOCK_FEED_KEYS, "") or ""),
                }
            )
    return ticks


def decode_kotak_order_feed(frame: Any) -> dict[str, Any] | None:
    """Decode one HSI order-feed delivery into a normalised order update.

    Accepts ``{"type": "order_feed", "data": <payload>}`` (what ``NeoWebSocket``
    hands to ``on_message``), a bare payload dict, or a JSON string. Connection
    acks (``{"type": "cn"|"CONNECTION"}``) and undecodable frames return
    ``None``. An order payload is normalised via ``from_kotak_order`` with the
    raw record preserved under ``"raw"``.
    """
    payload = frame
    if isinstance(payload, dict) and payload.get("type") == "order_feed":
        payload = payload.get("data")
    if isinstance(payload, str):
        try:
            payload = json.loads(payload)
        except ValueError:
            return None
    if not isinstance(payload, dict):
        return None
    if str(payload.get("type", "")).lower() in ("cn", "connection", "hb"):
        return None
    record = payload.get("data") if isinstance(payload.get("data"), dict) else payload
    if not isinstance(record, dict) or not (record.get("nOrdNo") or record.get("ordSt")):
        return None
    update = from_kotak_order(record)
    update["raw"] = record
    return update


def from_kotak_funds(resp: dict[str, Any]) -> dict[str, Any]:
    """Normalise the NEO ``limits`` response into FlintTrade fund fields.

    The real ``limits()`` response is a FLAT object (no ``data`` wrapper) keyed
    ``Net`` (net available margin) / ``MarginUsed`` / ``CollateralValue`` —
    ``Net + MarginUsed == CollateralValue`` (``Limits.md``). We surface ``Net`` as
    the available balance and ``MarginUsed`` as the used margin, falling back to
    the ``data``-wrapped check-margin keys (``avlCash``/``totMrgnUsd``) only if a
    gateway build returns that shape instead.
    """
    validate_read_envelope(resp, operation="limits")
    data = resp.get("data", resp)
    if type(data) is not dict:
        raise BrokerReadResponseInvalid from None
    available = _response_decimal(data, "Net", "avlCash", "avlMrgn", required=True)
    used = _response_decimal(data, "MarginUsed", "totMrgnUsd", "mrgnUsd", required=True)
    return {
        "available_balance": f"{available:.2f}",
        "used_margin": f"{used:.2f}",
        "total_balance": f"{available + used:.2f}",
        "extra": data,
    }
