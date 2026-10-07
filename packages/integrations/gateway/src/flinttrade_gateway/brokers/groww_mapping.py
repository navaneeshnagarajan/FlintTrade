"""Groww Trade API request/response mapping.

The Groww REST API speaks a compact ``{status, payload}`` envelope and uses
``CASH``/``FNO`` segment names with NSE/BSE exchange names. Keep the translation
logic here so the adapter stays a thin orchestration layer.
"""

from __future__ import annotations

import csv
import math
import re
from calendar import monthrange
from collections.abc import Mapping
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from io import StringIO
from typing import Any

from flinttrade_core.broker_read_port import BrokerReadResponseInvalid
from flinttrade_core.exceptions import (
    BrokerError,
    DataError,
    InsufficientFunds,
    InvalidPrice,
    InvalidQuantity,
    InvalidSymbol,
    MarketClosed,
    OrderError,
    OrderRejectedByBroker,
    RateLimitError,
    SessionExpired,
    UnsupportedOrderType,
)
from flinttrade_gateway.reconciliation import normalise_order_status

from . import groww_smart_mapping as S

BASE_URL = "https://api.groww.in"
_MISSING = object()
_DECIMAL_TEXT = re.compile(r"[+-]?(?:[0-9]+(?:\.[0-9]*)?|\.[0-9]+)(?:[eE][+-]?[0-9]+)?")
_REFERENCE_ID = re.compile(r"[A-Za-z0-9-]{8,20}")
_RESOURCE_ID = re.compile(r"[A-Za-z0-9_-]+")


def _request_enum(value: Any, choices: set[str] | frozenset[str], field: str) -> str:
    if not isinstance(value, str) or value not in choices:
        raise UnsupportedOrderType(f"Groww requires a supported explicit {field}", broker_id="groww")
    return str(value)


def _request_decimal(value: Any, field: str, *, positive: bool = False, wire_number: bool = False) -> int | float | str:
    if type(value) not in (int, float, str, Decimal):
        raise InvalidPrice(f"Groww {field} must be a finite decimal", broker_id="groww")
    text = str(value)
    if _DECIMAL_TEXT.fullmatch(text) is None:
        raise InvalidPrice(f"Groww {field} must use decimal grammar", broker_id="groww")
    try:
        number = Decimal(text)
    except InvalidOperation:
        raise InvalidPrice(f"Groww {field} must be a finite decimal", broker_id="groww") from None
    if not number.is_finite() or number < 0 or (positive and number == 0):
        raise InvalidPrice(
            f"Groww {field} must be {'positive' if positive else 'non-negative'} and finite", broker_id="groww"
        )
    if wire_number:
        # Ordinary REST decimals are JSON numbers; smart decimals are strings.
        # Never turn a valid but unrepresentable ordinary decimal into a rounded
        # request, zero, infinity or an undocumented JSON string field.
        if type(value) is int:
            return value
        converted = float(number)
        if not math.isfinite(converted) or Decimal(str(converted)) != number:
            raise InvalidPrice(
                f"Groww {field} cannot be represented losslessly as an ordinary JSON number", broker_id="groww"
            )
        return converted
    # Smart canonical text is kept verbatim; never round through a binary float.
    return text if type(value) is Decimal else value


def _request_quantity(value: Any) -> int:
    try:
        number = Decimal(str(_request_decimal(value, "quantity", positive=True)))
    except InvalidPrice:
        raise InvalidQuantity("Groww quantity must be an exact positive integer", broker_id="groww") from None
    if number != number.to_integral_value():
        raise InvalidQuantity("Groww quantity must be an exact positive integer", broker_id="groww")
    return int(number)


def _request_symbol(value: Any) -> str:
    if not isinstance(value, str) or not value or value != value.strip() or not value.isprintable():
        raise InvalidSymbol("Groww symbol must be a non-blank unpadded printable string", broker_id="groww")
    return value


def _request_reference(value: Any) -> str:
    if not isinstance(value, str) or _REFERENCE_ID.fullmatch(value) is None or value.count("-") > 2:
        raise OrderError(
            "Groww reference requires 8-20 ASCII alphanumeric/hyphen characters and at most two hyphens",
            broker_id="groww",
        )
    return value


def ordinary_resource_identity(order_id: Any, segment: Any) -> tuple[str, str]:
    """Validate an opaque ordinary-order address without coercion or defaults."""
    if not isinstance(order_id, str) or _RESOURCE_ID.fullmatch(order_id) is None:
        raise OrderError("Groww order id must be a safe non-empty ASCII identifier", broker_id="groww")
    return order_id, _request_enum(segment, {"CASH", "FNO", "COMMODITY"}, "segment")


def _request_alias(changes: dict[str, Any], names: tuple[str, ...], convert: Any, *, numeric: bool = False) -> Any:
    values = [convert(changes[name]) for name in names if name in changes]
    if not values:
        return _MISSING
    compared = [Decimal(str(value)) for value in values] if numeric else values
    if any(value != compared[0] for value in compared[1:]):
        raise OrderError(f"Groww conflicting aliases for {names[0]}", broker_id="groww")
    return values[0]


def _response_quantity(row: dict[str, Any], name: str) -> int | float | str | object:
    value = _response_number(row, name, empty_absent=True)
    if value is _MISSING:
        return value
    if type(value) is str and _DECIMAL_TEXT.fullmatch(value) is None:
        raise BrokerReadResponseInvalid from None
    number = Decimal(str(value))
    if number < 0 or number != number.to_integral_value():
        raise BrokerReadResponseInvalid from None
    return value


def _response_record(value: object) -> dict[str, Any]:
    if type(value) is not dict or any(type(key) is not str for key in value):
        raise BrokerReadResponseInvalid
    return value


def _response_text(
    row: dict[str, Any],
    *names: str,
    required: bool = False,
) -> str | object:
    for name in names:
        if name not in row:
            continue
        value = row[name]
        if value is None and not required:
            continue
        if type(value) is not str or not value:
            raise BrokerReadResponseInvalid
        return value.encode("utf-8").decode("utf-8")
    if required:
        raise BrokerReadResponseInvalid
    return _MISSING


def _response_number(
    row: dict[str, Any],
    *names: str,
    required: bool = False,
    empty_absent: bool = False,
) -> int | float | str | object:
    for name in names:
        if name not in row:
            continue
        value = row[name]
        if value is None and not required:
            continue
        if type(value) is int:
            return value
        if type(value) is float:
            if not math.isfinite(value):
                raise BrokerReadResponseInvalid
            return value
        if type(value) is str and not value.strip():
            if empty_absent and not required:
                continue
            raise BrokerReadResponseInvalid
        if type(value) is str:
            try:
                number = Decimal(value)
            except InvalidOperation:
                raise BrokerReadResponseInvalid from None
            if number.is_finite():
                return value.encode("utf-8").decode("utf-8")
        raise BrokerReadResponseInvalid
    if required:
        raise BrokerReadResponseInvalid
    return _MISSING


def _response_exchange(row: dict[str, Any], *, strict_pair: bool = False) -> str | object:
    exchange = _response_text(row, "exchange")
    if not strict_pair and exchange is _MISSING:
        return _MISSING
    segment = _response_text(row, "segment")
    if strict_pair:
        if exchange is _MISSING or segment is _MISSING:
            raise BrokerReadResponseInvalid
        pair = (exchange.upper(), segment.upper())
        mapped = {
            ("NSE", "CASH"): "NSE",
            ("BSE", "CASH"): "BSE",
            ("NSE", "FNO"): "NFO",
            ("BSE", "FNO"): "BFO",
            ("MCX", "COMMODITY"): "MCX",
        }.get(pair)
        if mapped is None:
            raise BrokerReadResponseInvalid
        return mapped
    ex = exchange.upper()
    seg = "" if segment is _MISSING else segment.upper()
    if ex not in {"NSE", "BSE", "MCX"} or seg not in {"", "CASH", "FNO", "COMMODITY"}:
        raise BrokerReadResponseInvalid
    if seg == "COMMODITY" or ex == "MCX":
        return "MCX"
    if seg == "FNO":
        return "BFO" if ex == "BSE" else "NFO"
    return ex


def _response_trade_id(row: dict[str, Any]) -> str | object:
    if "groww_trade_id" in row:
        primary = row["groww_trade_id"]
        if type(primary) is not str:
            raise BrokerReadResponseInvalid
        if primary:
            if not primary.strip():
                raise BrokerReadResponseInvalid
            return primary.encode("utf-8").decode("utf-8")
    secondary = _response_text(row, "exchange_trade_id")
    if secondary is not _MISSING and not secondary.strip():
        raise BrokerReadResponseInvalid
    return secondary


def _response_product(row: dict[str, Any]) -> str | object:
    value = _response_text(row, "product")
    if value is _MISSING:
        return _MISSING
    product_name = value.upper()
    try:
        return {"MIS": "MIS", "CNC": "CNC", "NRML": "NRML", "MARGIN": "NRML"}[product_name]
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
        value = _response_number(row, name, required=True)
        number = Decimal(str(value))
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


def _market_timestamp(value: object) -> str:
    if type(value) is str:
        if not value.strip():
            raise BrokerReadResponseInvalid from None
        return value.encode("utf-8").decode("utf-8")
    if type(value) is int:
        return str(value)
    if type(value) is float and math.isfinite(value):
        return str(value)
    raise BrokerReadResponseInvalid from None


def _required_response(value: object) -> Any:
    if value is _MISSING:
        raise BrokerReadResponseInvalid
    return value


def _text(value: Any) -> str:
    return str(value or "").strip()


def _upper(value: Any) -> str:
    return _text(value).upper()


def _float(value: Any, default: float = 0.0) -> float:
    try:
        if value in (None, ""):
            return default
        return float(value)
    except (TypeError, ValueError):
        return default


def _int(value: Any, default: int = 0) -> int:
    try:
        if value in (None, ""):
            return default
        return int(float(value))
    except (TypeError, ValueError):
        return default


def _present_order_number(row: dict[str, Any], key: str, *, integral: bool = False) -> Any:
    if key not in row:
        return _MISSING
    value = row[key]
    if value is None or (isinstance(value, str) and not value.strip()):
        return _MISSING
    if isinstance(value, bool):
        return value
    try:
        return int(float(value)) if integral else float(value)
    except (TypeError, ValueError, OverflowError):
        return value


def _error_fields(payload: Any) -> tuple[str, str]:
    if not isinstance(payload, dict):
        return "", _text(payload)
    nested = payload.get("error") if isinstance(payload.get("error"), dict) else {}
    code = _text(
        payload.get("error_code") or payload.get("code") or (nested.get("code") if isinstance(nested, dict) else "")
    )
    message = _text(payload.get("message") or (nested.get("message") if isinstance(nested, dict) else "") or payload)
    return code, message


def _is_market_data_endpoint(endpoint: str | None) -> bool:
    value = _text(endpoint).lower()
    return any(
        marker in value
        for marker in (
            "/live-data/",
            "/historical/",
            "/option-chain/",
            "/instruments/",
            "instrument.csv",
        )
    )


def map_error(status: int, payload: Any, *, endpoint: str | None = None) -> BrokerError:
    """Map a Groww HTTP/envelope failure into FlintTrade's taxonomy."""
    code, message = _error_fields(payload)
    message = message or "Groww API error"
    lower = message.lower()
    kwargs = {"broker_code": code or str(status), "broker_id": "groww"}
    if (
        status in (401, 403)
        and _is_market_data_endpoint(endpoint)
        and ("forbidden" in lower or "authentication required" in lower or "access denied" in lower)
    ):
        return DataError("Groww market-data access is not enabled for this API key", **kwargs)
    if status == 401 or "unauthor" in lower or "expired" in lower or "invalid token" in lower:
        return SessionExpired("Groww access token is invalid or expired", **kwargs)
    if status == 403:
        return BrokerError(message, **kwargs)
    if status == 429 or "rate limit" in lower:
        return RateLimitError(message, endpoint="groww", broker_code=code or str(status), broker_id="groww")
    if "margin" in lower or "fund" in lower or "balance" in lower:
        return InsufficientFunds(message, **kwargs)
    if "quantity" in lower or "lot" in lower:
        return InvalidQuantity(message, **kwargs)
    if "price" in lower or "circuit" in lower:
        return InvalidPrice(message, **kwargs)
    if "symbol" in lower or "instrument" in lower or "scrip" in lower:
        return InvalidSymbol(message, **kwargs)
    if "market" in lower and ("closed" in lower or "hour" in lower):
        return MarketClosed(message, **kwargs)
    return OrderRejectedByBroker(message, **kwargs)


def unwrap(payload: Any) -> Any:
    """Return the Groww ``payload`` field from a successful envelope."""
    if not isinstance(payload, dict):
        return payload
    if _upper(payload.get("status")) and _upper(payload.get("status")) != "SUCCESS":
        raise map_error(200, payload)
    return payload.get("payload", payload)


def unwrap_fixed_read(payload: Any) -> Any:
    """Strictly unwrap a fixed broker-read response envelope."""
    if type(payload) is not dict or any(type(key) is not str for key in payload):
        raise BrokerReadResponseInvalid from None
    status = payload.get("status")
    if type(status) is not str or not status.strip():
        raise BrokerReadResponseInvalid from None
    if status.strip().upper() != "SUCCESS":
        raise map_error(200, payload)
    if "payload" not in payload:
        raise BrokerReadResponseInvalid from None
    return payload["payload"]


def exchange_segment(exchange: Any) -> tuple[str, str]:
    """Map FlintTrade exchange names to Groww ``(exchange, segment)``."""
    pairs = {
        "NSE": ("NSE", "CASH"),
        "NSE_INDEX": ("NSE", "CASH"),
        "BSE": ("BSE", "CASH"),
        "BSE_INDEX": ("BSE", "CASH"),
        "NFO": ("NSE", "FNO"),
        "NSE_FO": ("NSE", "FNO"),
        "NSE_FNO": ("NSE", "FNO"),
        "BFO": ("BSE", "FNO"),
        "BSE_FO": ("BSE", "FNO"),
        "BSE_FNO": ("BSE", "FNO"),
        "MCX": ("MCX", "COMMODITY"),
        "MCX_FO": ("MCX", "COMMODITY"),
        "MCX_COM": ("MCX", "COMMODITY"),
        "COMMODITY": ("MCX", "COMMODITY"),
    }
    return pairs[_request_enum(exchange, set(pairs), "exchange")]


def native_broker_exchange(exchange: Any, segment: Any = "") -> str:
    ex = _upper(exchange)
    seg = _upper(segment)
    if seg == "COMMODITY" or ex == "MCX":
        return "MCX"
    if seg == "FNO" and ex == "BSE":
        return "BFO"
    if seg == "FNO":
        return "NFO"
    return "BSE" if ex == "BSE" else "NSE"


def order_type(value: Any) -> str:
    mapping = {
        "MARKET": "MARKET",
        "LIMIT": "LIMIT",
        "SL": "SL",
        "SL-M": "SL_M",
        "SLM": "SL_M",
        "SL_M": "SL_M",
        "STOP_LOSS_LIMIT": "SL",
        "STOP_LOSS_MARKET": "SL_M",
    }
    kind = _request_enum(value, set(mapping), "order_type")
    return mapping[kind]


def reverse_order_type(value: Any) -> str:
    return {
        "SL_M": "SL-M",
        "SLM": "SL-M",
        "STOP_LOSS_LIMIT": "SL",
        "STOP_LOSS_MARKET": "SL-M",
    }.get(_upper(value), _upper(value) or "MARKET")


def product(value: Any) -> str:
    prod = _request_enum(value, {"MIS", "CNC", "NRML", "MARGIN"}, "product")
    return "NRML" if prod == "MARGIN" else prod


def order_variety(value: Any, *, modification: bool = False) -> str:
    """Validate the native variety without falling back to an ordinary order.

    Args:
        value: Requested regular, AMO, GTT or OCO variety.
        modification: Permit the existing smart-modification discriminator.

    Returns:
        The validated native variety.

    Raises:
        OrderError: The value is absent, malformed or unsupported.
    """
    choices = {"regular", "amo", "gtt", "oco"} | ({"smart"} if modification else set())
    return _request_enum(value, choices, "variety")


def _refuse_unrepresented_intent(order: Any, *, smart: bool = False) -> None:
    if getattr(order, "market_protection", None) is not None:
        raise OrderError("Groww explicit market protection is not represented by this schema", broker_id="groww")
    for field in (
        "target_price",
        "stop_loss_price",
        "trailing_jump",
        "iceberg_legs",
        "price1",
        "trigger_price1",
        "quantity1",
    ):
        value = getattr(order, field, None)
        if value is not None and Decimal(str(_request_decimal(value, field))) != 0:
            raise OrderError(
                "Groww child/bracket/trailing/slicing intent is not represented by this schema", broker_id="groww"
            )
    for field in ("target_trigger_type", "stop_loss_trigger_type") + (() if smart else ("entry_trigger_type",)):
        if getattr(order, field, None) is not None:
            raise OrderError("Groww child or smart trigger intent is not represented by this schema", broker_id="groww")


def reverse_product(value: Any) -> str:
    return {"MIS": "MIS", "CNC": "CNC", "NRML": "NRML", "MARGIN": "NRML"}.get(_upper(value), "CNC")


def to_place_order_payload(order: Any) -> dict[str, Any]:
    _refuse_unrepresented_intent(order)
    exchange, segment = exchange_segment(getattr(order, "exchange", None))
    validity = getattr(order, "validity", None)
    payload: dict[str, Any] = {
        "trading_symbol": _request_symbol(getattr(order, "symbol", None)),
        "quantity": _request_quantity(getattr(order, "quantity", None)),
        "validity": "DAY" if validity is None else _request_enum(validity, {"DAY", "IOC"}, "validity"),
        "exchange": exchange,
        "segment": segment,
        "product": product(getattr(order, "product", None)),
        "order_type": order_type(getattr(order, "pricetype", None)),
        "transaction_type": _request_enum(getattr(order, "action", None), {"BUY", "SELL"}, "transaction_type"),
        "order_reference_id": _request_reference(getattr(order, "strategy", None)),
    }
    kind = payload["order_type"]
    price = _request_decimal(getattr(order, "price", 0), "price", positive=kind in {"LIMIT", "SL"}, wire_number=True)
    trigger = _request_decimal(
        getattr(order, "trigger_price", 0), "trigger_price", positive=kind in {"SL", "SL_M"}, wire_number=True
    )
    if kind in {"LIMIT", "SL"}:
        payload["price"] = price
    if kind in {"SL", "SL_M"}:
        payload["trigger_price"] = trigger
    return payload


def to_smart_create_payload(request: Mapping[str, Any]) -> dict[str, Any]:
    """Validate an explicit native GTT/OCO body; this supplies no write authority."""
    if not isinstance(request, Mapping):
        raise OrderError("Groww smart creation requires explicit native fields", broker_id="groww")
    family = _request_enum(request.get("smart_order_type"), {"GTT", "OCO"}, "smart_order_type")
    try:
        return S.to_gtt_create_payload(request) if family == "GTT" else S.to_oco_create_payload(request)
    except ValueError as exc:
        raise OrderError(str(exc), broker_id="groww") from exc


def to_smart_order_payload(order: Any) -> dict[str, Any]:
    """Map representable signed canonical GTT intent, never an ordinary fallback.

    ``entry_trigger_type`` must explicitly be native UP/DOWN. The canonical
    model has no independent OCO leg types/prices or signed native position
    snapshot, so OCO creation is refused here until that gate/model contract
    exists. Explicit native OCO dictionaries remain supported by the pure
    ``to_smart_create_payload`` seam, not an extra adapter write entrypoint.
    """
    if getattr(order, "variety", None) != "gtt":
        raise OrderError("Groww OCO creation needs a signed native position and leg intent schema", broker_id="groww")
    _refuse_unrepresented_intent(order, smart=True)
    exchange, segment = exchange_segment(getattr(order, "exchange", None))
    kind = order_type(getattr(order, "pricetype", None))
    nested_order: dict[str, Any] = {
        "order_type": kind,
        "transaction_type": _request_enum(getattr(order, "action", None), {"BUY", "SELL"}, "transaction_type"),
    }
    price = _request_decimal(getattr(order, "price", 0), "price", positive=kind in {"LIMIT", "SL"})
    if kind in {"LIMIT", "SL"} or Decimal(str(price)) != 0:
        nested_order["price"] = str(price)
    validity = getattr(order, "validity", None)
    return to_smart_create_payload(
        {
            "reference_id": _request_reference(getattr(order, "strategy", None)),
            "smart_order_type": "GTT",
            "segment": segment,
            "trading_symbol": _request_symbol(getattr(order, "symbol", None)),
            "quantity": _request_quantity(getattr(order, "quantity", None)),
            "trigger_price": str(
                _request_decimal(getattr(order, "trigger_price", None), "trigger_price", positive=True)
            ),
            "trigger_direction": _request_enum(
                getattr(order, "entry_trigger_type", None), {"UP", "DOWN"}, "trigger_direction"
            ),
            "order": nested_order,
            "product_type": product(getattr(order, "product", None)),
            "exchange": exchange,
            "duration": "DAY" if validity is None else validity,
        }
    )


def smart_resource_path(
    operation: str,
    *,
    smart_order_id: str,
    segment: str | None,
    smart_order_type: str | None,
) -> str:
    """Address a smart resource only with explicit native family and segment."""
    segment = _request_enum(segment, {"CASH", "FNO"}, "segment")
    smart_order_type = _request_enum(smart_order_type, {"GTT", "OCO"}, "smart_order_type")
    try:
        return S.smart_resource_path(
            operation, smart_order_id=smart_order_id, segment=segment, smart_order_type=smart_order_type
        )
    except ValueError as exc:
        raise OrderError(str(exc), broker_id="groww") from exc


def smart_page_params(
    *,
    segment: str,
    smart_order_type: str,
    status: str,
    start_date_time: str,
    end_date_time: str,
    page: int = 0,
    page_size: int = 50,
) -> dict[str, Any]:
    """Require explicit family/segment/status/time scope for a single smart page."""
    segment = _request_enum(segment, {"CASH", "FNO"}, "segment")
    family = _request_enum(smart_order_type, {"GTT", "OCO"}, "smart_order_type")
    if not isinstance(status, str) or _RESOURCE_ID.fullmatch(status) is None:
        raise OrderError("Groww smart page needs an explicit status filter", broker_id="groww")
    if type(page) is not int or not 0 <= page <= 500 or type(page_size) is not int or not 1 <= page_size <= 50:
        raise OrderError("Groww smart pagination requires page 0-500 and page_size 1-50", broker_id="groww")
    timestamps: list[datetime] = []
    for value in (start_date_time, end_date_time):
        if (
            not isinstance(value, str)
            or re.fullmatch(r"[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}", value) is None
        ):
            raise OrderError("Groww smart page requires explicit ISO second-resolution time bounds", broker_id="groww")
        try:
            timestamps.append(datetime.strptime(value, "%Y-%m-%dT%H:%M:%S"))
        except ValueError as exc:
            raise OrderError("Groww smart page time bounds are invalid", broker_id="groww") from exc
    start, end = timestamps
    try:
        year = start.year + (start.month == 12)
        month = start.month % 12 + 1
        limit = start.replace(year=year, month=month, day=min(start.day, monthrange(year, month)[1]))
    except ValueError as exc:
        raise OrderError("Groww smart page time range is invalid", broker_id="groww") from exc
    if end < start or end > limit:
        raise OrderError("Groww smart page time range must be ordered and no longer than one month", broker_id="groww")
    return {
        "segment": segment,
        "smart_order_type": family,
        "status": status,
        "page": page,
        "page_size": page_size,
        "start_date_time": start_date_time,
        "end_date_time": end_date_time,
    }


def from_smart_order(row: dict[str, Any]) -> dict[str, Any]:
    """Project smart observations through the actual mapper with typed refusal."""
    row = _response_record(row)
    try:
        return S.from_smart_order(row)
    except ValueError:
        raise BrokerReadResponseInvalid from None


def from_smart_page(payload: Any) -> list[dict[str, Any]]:
    """Map every row of one successful page, never manufacture a complete book."""
    unwrap_fixed_read(payload)
    try:
        return S.from_smart_page(payload)
    except ValueError:
        raise BrokerReadResponseInvalid from None


def to_smart_modify_payload(order_id: str, changes: dict[str, Any]) -> dict[str, Any]:
    """Validate current identity and family-specific edits; never fetch or infer state.

    ``current`` is explicit caller evidence and must travel inside the signed
    request. This checks correspondence, not its freshness or broker eligibility.
    GTT requires current product and the full immutable-side execution order.
    OCO partial edits do not require creation-only position fields; supplied
    position/side constraints are validated by the native mapper.
    """
    if type(changes) is not dict or not isinstance(changes.get("current"), Mapping):
        raise OrderError("Groww smart modification requires explicit current resource context", broker_id="groww")
    current = dict(changes["current"])
    if "is_modification_allowed" in current and current["is_modification_allowed"] is not True:
        raise OrderError("Groww observed smart modification permission is false or malformed", broker_id="groww")
    family = _request_enum(current.get("smart_order_type"), {"GTT", "OCO"}, "smart_order_type")
    segment = _request_enum(current.get("segment"), {"CASH", "FNO"}, "segment")
    smart_resource_path("modify", smart_order_id=order_id, segment=segment, smart_order_type=family)
    if current.get("smart_order_id") != order_id:
        raise OrderError("Groww current smart resource id does not match the requested id", broker_id="groww")
    for field in ("segment", "smart_order_type"):
        if field in changes and changes[field] != current[field]:
            raise OrderError(f"Groww {field} context conflicts with current resource", broker_id="groww")
    if "variety" in changes:
        _request_enum(changes["variety"], {family.lower(), "smart"}, "variety matching current family")
    if family == "GTT" and "product_type" not in current:
        raise OrderError("Groww GTT modification requires current product context", broker_id="groww")
    edits = {
        key: value for key, value in changes.items() if key not in {"current", "variety", "segment", "smart_order_type"}
    }
    try:
        return S.to_smart_modify_payload(current, edits)
    except ValueError as exc:
        raise OrderError(str(exc), broker_id="groww") from exc


def to_modify_payload(order_id: str, changes: dict[str, Any], *, segment: str | None) -> dict[str, Any]:
    identifier, segment = ordinary_resource_identity(order_id, segment)
    allowed = {
        "quantity",
        "qty",
        "pricetype",
        "order_type",
        "price",
        "limit_price",
        "trigger_price",
        "segment",
        "exchange",
        "symbol",
        "action",
        "product",
        "validity",
        "strategy",
        "variety",
        "disclosed_quantity",
        "amo",
    }
    if type(changes) is not dict or set(changes) - allowed:
        raise OrderError("Groww ordinary modification contains unsupported fields", broker_id="groww")
    if "segment" in changes and changes["segment"] != segment:
        raise OrderError("Groww segment context conflicts", broker_id="groww")
    if "exchange" in changes and exchange_segment(changes["exchange"])[1] != segment:
        raise OrderError("Groww exchange and segment context conflict", broker_id="groww")
    for field, choices in {
        "action": {"BUY", "SELL"},
        "validity": {"DAY", "IOC"},
        "variety": {"regular", "amo"},
    }.items():
        if field in changes:
            _request_enum(changes[field], choices, field)
    if "product" in changes:
        product(changes["product"])
    if "symbol" in changes:
        _request_symbol(changes["symbol"])
    if "amo" in changes and changes["amo"] is not False:
        raise OrderError("Groww has no documented ordinary AMO modification field", broker_id="groww")
    kind = _request_alias(changes, ("pricetype", "order_type"), order_type)
    if kind is _MISSING:
        raise OrderError("Groww modification requires explicit order_type", broker_id="groww")
    payload: dict[str, Any] = {"groww_order_id": identifier, "segment": segment, "order_type": kind}
    quantity = _request_alias(changes, ("quantity", "qty"), _request_quantity)
    price = _request_alias(
        changes,
        ("price", "limit_price"),
        lambda value: _request_decimal(value, "price", positive=kind in {"LIMIT", "SL"}, wire_number=True),
        numeric=True,
    )
    _put_present(payload, "quantity", quantity)
    _put_present(payload, "price", price)
    if "trigger_price" in changes:
        payload["trigger_price"] = _request_decimal(
            changes["trigger_price"], "trigger_price", positive=kind in {"SL", "SL_M"}, wire_number=True
        )
    return payload


def to_cancel_payload(order_id: str, *, segment: str) -> dict[str, Any]:
    identifier, segment = ordinary_resource_identity(order_id, segment)
    return {"groww_order_id": identifier, "segment": segment}


def to_margin_payload(order: Any) -> tuple[str, list[dict[str, Any]]]:
    payload = to_place_order_payload(order)
    return payload["segment"], [payload]


def extract_order_id(payload: Any, *, expected_family: str | None = None) -> str:
    """Extract exact acknowledgement identity, never a fill or terminal resource state."""
    try:
        data = unwrap_fixed_read(payload) if expected_family is not None else unwrap(payload)
    except BrokerReadResponseInvalid:
        raise OrderError("Groww placement acknowledgement envelope is malformed", broker_id="groww") from None
    if type(data) is not dict:
        raise OrderError("Groww placement acknowledgement payload is malformed", broker_id="groww")
    if expected_family in {"GTT", "OCO"}:
        if "smart_order_type" in data and data["smart_order_type"] != expected_family:
            raise OrderError("Groww acknowledgement smart family does not match intent", broker_id="groww")
        names = ("smart_order_id",)
    else:
        names = (
            ("groww_order_id", "order_id", "smart_order_id")
            if expected_family is None
            else ("groww_order_id", "order_id")
        )
    values = [data[name] for name in names if name in data]
    if not values:
        return ""
    if any(not isinstance(value, str) or _RESOURCE_ID.fullmatch(value) is None for value in values):
        raise OrderError("Groww acknowledgement has an unsafe or non-string order id", broker_id="groww")
    if any(value != values[0] for value in values[1:]):
        raise OrderError("Groww acknowledgement identity aliases conflict", broker_id="groww")
    return values[0]


def from_order(row: dict[str, Any]) -> dict[str, Any]:
    row = _response_record(row)
    quantity = _response_quantity(row, "quantity")
    filled_quantity = _response_quantity(row, "filled_quantity")
    remaining_quantity = _response_quantity(row, "remaining_quantity")
    counts = {
        name: int(Decimal(str(value)))
        for name, value in {"total": quantity, "filled": filled_quantity, "remaining": remaining_quantity}.items()
        if value is not _MISSING
    }
    if "total" in counts and counts.get("filled", 0) + counts.get("remaining", 0) > counts["total"]:
        raise BrokerReadResponseInvalid from None
    status = _response_text(row, "order_status", "status", required=True)
    canonical_status = _status(status)
    if canonical_status == "OPEN" and "total" in counts and 0 < counts.get("filled", 0) < counts["total"]:
        canonical_status = "PARTIALLY_FILLED"
    order: dict[str, Any] = {"status": canonical_status, "raw_status": status}
    for field, value in {
        "orderid": _response_text(row, "groww_order_id", "order_id"),
        "symbol": _response_text(row, "trading_symbol"),
        "exchange": _response_exchange(row, strict_pair=True) if "exchange" in row or "segment" in row else _MISSING,
        "quantity": quantity,
        "filled_quantity": filled_quantity,
        "remaining_quantity": remaining_quantity,
        "price": _response_number(row, "price", empty_absent=True),
        "trigger_price": _response_number(row, "trigger_price", empty_absent=True),
        "average_price": _response_number(
            row,
            "average_fill_price",
            "average_price",
            empty_absent=True,
        ),
        "order_timestamp": _response_text(row, "created_at", "order_date_time"),
        "order_reference_id": _response_text(row, "order_reference_id"),
        "remark": _response_text(row, "remark"),
    }.items():
        _put_present(order, field, value)
    action = _response_text(row, "transaction_type")
    if action is not _MISSING:
        order["action"] = order["transaction_type"] = action.upper()
    order_kind = _response_text(row, "order_type")
    if order_kind is not _MISSING:
        mapped_kind = {
            "MARKET": "MARKET",
            "LIMIT": "LIMIT",
            "SL": "SL",
            "SL-M": "SL-M",
            "SLM": "SL-M",
            "SL_M": "SL-M",
            "STOP_LOSS_LIMIT": "SL",
            "STOP_LOSS_MARKET": "SL-M",
        }.get(order_kind.upper())
        if mapped_kind is None:
            raise BrokerReadResponseInvalid
        order["pricetype"] = order["order_type"] = mapped_kind
    mapped_product = _response_product(row)
    _put_present(order, "product", mapped_product)
    return order


def from_trade(row: dict[str, Any]) -> dict[str, Any]:
    row = _response_record(row)
    trade = {
        "tradeid": _response_trade_id(row),
        "symbol": _response_text(row, "trading_symbol", required=True),
        "exchange": _required_response(_response_exchange(row, strict_pair=True)),
        "action": _response_text(row, "transaction_type", required=True).upper(),
        "quantity": _response_number(row, "quantity", required=True),
        "price": _response_number(row, "price", "average_price", required=True),
        "product": _required_response(_response_product(row)),
        "timestamp": _response_text(row, "trade_date_time", "created_at", required=True),
    }
    _put_present(trade, "orderid", _response_text(row, "groww_order_id"))
    return trade


def from_position(row: dict[str, Any]) -> dict[str, Any]:
    row = _response_record(row)
    if "quantity" in row:
        quantity = _response_number(row, "quantity", required=True)
    else:
        credit = _response_number(row, "credit_quantity", required=True)
        debit = _response_number(row, "debit_quantity", required=True)
        try:
            result = Decimal(str(credit)) - Decimal(str(debit))
        except InvalidOperation:
            raise BrokerReadResponseInvalid from None
        if not result.is_finite():
            raise BrokerReadResponseInvalid
        if type(credit) is int and type(debit) is int:
            quantity = int(result)
        elif type(credit) is float or type(debit) is float:
            quantity = float(result)
            if not math.isfinite(quantity):
                raise BrokerReadResponseInvalid
        else:
            quantity = str(result)
    position: dict[str, Any] = {"quantity": quantity}
    for field, value in {
        "symbol": _response_text(row, "trading_symbol"),
        "exchange": _response_exchange(row, strict_pair=True),
        "product": _response_product(row),
        "average_price": _response_number(row, "average_price", "net_price"),
        "ltp": _response_number(row, "ltp", "last_price"),
        "pnl": _response_number(row, "pnl", "realised_pnl", "unrealised_pnl"),
    }.items():
        _put_present(position, field, value)
    return position


def from_holding(row: dict[str, Any]) -> dict[str, Any]:
    row = _response_record(row)
    holding: dict[str, Any] = {"quantity": _response_number(row, "quantity", required=True)}
    for field, value in {
        "symbol": _response_text(row, "trading_symbol"),
        "exchange": _response_exchange(row),
        "product": _response_product(row),
        "average_price": _response_number(row, "average_price"),
        "ltp": _response_number(row, "ltp", "last_price"),
        "isin": _response_text(row, "isin"),
    }.items():
        _put_present(holding, field, value)
    return holding


def from_funds(row: dict[str, Any]) -> dict[str, Any]:
    return {
        "availablecash": _float(row.get("clear_cash")),
        "available_cash": _float(row.get("clear_cash")),
        "total_balance": _float(row.get("clear_cash")) + _float(row.get("collateral_available")),
        "used_margin": _float(row.get("net_margin_used")),
        "collateral": _float(row.get("collateral_available")),
        "brokerage_and_charges": _float(row.get("brokerage_and_charges")),
        "raw": row,
    }


def split_symbol(raw: str) -> tuple[str, str]:
    if ":" in raw:
        exchange, symbol = raw.split(":", 1)
        return _upper(exchange) or "NSE", _text(symbol)
    return "NSE", _text(raw)


def groww_exchange_symbol(exchange: str, symbol: str) -> str:
    ex, _segment = exchange_segment(exchange)
    return f"{ex}_{symbol}"


def from_quote(
    symbol: str,
    exchange: str,
    row: dict[str, Any],
    *,
    strict: bool = False,
) -> dict[str, Any]:
    # The documented /v1/live-data/quote payload nests OHLC under an "ohlc"
    # object and names the ask "offer_price" (captured official docs:
    # .local/reference-research/2026-07-03/groww-trade-api-docs). Flat keys stay
    # as tolerance fallbacks only — reading them alone rendered every quote's
    # open/high/low/close/ask as fabricated zeros.
    if not strict:
        raw_ohlc = row.get("ohlc")
        ohlc: dict[str, Any] = raw_ohlc if isinstance(raw_ohlc, dict) else {}
        return {
            "symbol": symbol,
            "exchange": exchange,
            "ltp": _float(row.get("last_price") or row.get("ltp") or row.get("live_price")),
            "open": _float(ohlc.get("open") or row.get("open")),
            "high": _float(ohlc.get("high") or row.get("high")),
            "low": _float(ohlc.get("low") or row.get("low")),
            "close": _float(ohlc.get("close") or row.get("close")),
            "volume": _int(row.get("volume")),
            "bid": _float(row.get("bid_price")),
            "ask": _float(row.get("offer_price") or row.get("ask_price")),
            "prev_close": _float(row.get("previous_close") or row.get("prev_close") or ohlc.get("close")),
            "oi": _int(row.get("open_interest") or row.get("oi")),
        }

    record = _response_record(row)
    ohlc: dict[str, Any] = {}
    if "ohlc" in record:
        ohlc = _response_record(record["ohlc"])
    quote: dict[str, Any] = {"symbol": symbol, "exchange": exchange}
    _put_present(quote, "ltp", _market_number(record, "last_price", "ltp", "live_price"))
    for name in ("open", "high", "low", "close"):
        value = _market_number(ohlc, name) if name in ohlc else _market_number(record, name)
        _put_present(quote, name, value)
    _put_present(quote, "volume", _market_number(record, "volume", integer=True))
    _put_present(quote, "bid", _market_number(record, "bid_price"))
    _put_present(quote, "ask", _market_number(record, "offer_price", "ask_price"))
    previous_close = _market_number(record, "previous_close", "prev_close")
    if previous_close is _MISSING:
        previous_close = _market_number(ohlc, "close")
    _put_present(quote, "prev_close", previous_close)
    _put_present(quote, "oi", _market_number(record, "open_interest", "oi", integer=True))
    return quote


def from_ohlc(symbol: str, exchange: str, row: dict[str, Any]) -> dict[str, Any]:
    return {
        "symbol": symbol,
        "exchange": exchange,
        "open": _float(row.get("open")),
        "high": _float(row.get("high")),
        "low": _float(row.get("low")),
        "close": _float(row.get("close")),
        "volume": _int(row.get("volume")),
        "timestamp": _text(row.get("timestamp") or row.get("time")),
        "raw": row,
    }


def expiry_values(payload: Any) -> list[str]:
    data = unwrap(payload)
    if isinstance(data, list):
        return [_text(item) for item in data if _text(item)]
    if not isinstance(data, dict):
        return []
    for key in ("expiry_dates", "expiries", "expiry", "data"):
        values = data.get(key)
        if isinstance(values, list):
            return [_text(item) for item in values if _text(item)]
    return []


def candle_rows(payload: Any, *, strict: bool = False) -> list[Any]:
    if strict:
        data = unwrap_fixed_read(payload)
        if type(data) is list:
            return data
        record = _response_record(data)
        if "candles" in record:
            rows = record["candles"]
        elif "data" in record:
            rows = record["data"]
        else:
            raise BrokerReadResponseInvalid from None
        if type(rows) is not list:
            raise BrokerReadResponseInvalid from None
        return rows
    data = unwrap(payload)
    if isinstance(data, dict):
        rows = data.get("candles") or data.get("data") or []
        return rows if isinstance(rows, list) else []
    return data if isinstance(data, list) else []


def from_candle_row(row: Any, *, strict: bool = False) -> dict[str, Any]:
    if strict:
        if type(row) is list:
            if len(row) < 5:
                raise BrokerReadResponseInvalid from None
            candle = {
                "timestamp": _market_timestamp(row[0]),
                "open": _market_number({"value": row[1]}, "value"),
                "high": _market_number({"value": row[2]}, "value"),
                "low": _market_number({"value": row[3]}, "value"),
                "close": _market_number({"value": row[4]}, "value"),
            }
            if len(row) > 5:
                candle["volume"] = _market_number({"value": row[5]}, "value", integer=True)
            return candle
        record = _response_record(row)
        timestamp = _market_text(record, "timestamp", "time")
        if timestamp is _MISSING:
            raise BrokerReadResponseInvalid from None
        candle = {
            "timestamp": _market_timestamp(timestamp),
            "open": _market_number(record, "open"),
            "high": _market_number(record, "high"),
            "low": _market_number(record, "low"),
            "close": _market_number(record, "close"),
        }
        if any(candle[name] is _MISSING for name in ("open", "high", "low", "close")):
            raise BrokerReadResponseInvalid from None
        _put_present(candle, "volume", _market_number(record, "volume", integer=True))
        return candle
    if isinstance(row, (list, tuple)):
        return {
            "timestamp": str(row[0] if len(row) > 0 else ""),
            "open": _float(row[1] if len(row) > 1 else 0),
            "high": _float(row[2] if len(row) > 2 else 0),
            "low": _float(row[3] if len(row) > 3 else 0),
            "close": _float(row[4] if len(row) > 4 else 0),
            "volume": _int(row[5] if len(row) > 5 else 0),
        }
    if isinstance(row, dict):
        return {
            "timestamp": _text(row.get("timestamp") or row.get("time")),
            "open": _float(row.get("open")),
            "high": _float(row.get("high")),
            "low": _float(row.get("low")),
            "close": _float(row.get("close")),
            "volume": _int(row.get("volume")),
        }
    return {}


def normalise_date(value: Any) -> str:
    if isinstance(value, datetime):
        return value.strftime("%Y-%m-%d %H:%M:%S")
    if isinstance(value, date):
        return value.strftime("%Y-%m-%d")
    return _text(value)


def option_chain_rows(payload: Any) -> dict[str, Any]:
    data = unwrap(payload)
    return data if isinstance(data, dict) else {}


def parse_instruments_csv(text: str) -> list[dict[str, str]]:
    return list(csv.DictReader(StringIO(text)))


def _status(value: Any, *, quantity: float = 0.0, filled_quantity: float = 0.0) -> str:
    return normalise_order_status(
        value,
        quantity=quantity,
        filled_quantity=filled_quantity,
    )
