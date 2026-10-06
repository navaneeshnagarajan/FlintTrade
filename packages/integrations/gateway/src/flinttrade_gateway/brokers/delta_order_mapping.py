"""Pure Delta Exchange India native options, brackets and snapshot evidence.

These mappings confer no product eligibility or execution authority. Callers
must establish account/venue/product eligibility and validate the resulting
payload against the product's verified tick size before any gated dispatch.
Native reduce-only is preserved when explicitly requested for eligible exits;
it does not establish a fill or a closed position.
"""

from __future__ import annotations

from copy import deepcopy
from decimal import Decimal, InvalidOperation
from typing import Any, Mapping

from flinttrade_core.exceptions import BrokerError
from flinttrade_gateway.brokers import delta_mapping

_NATIVE_FIELDS = frozenset({
    "post_only", "client_order_id", "stop_order_type", "stop_price", "trail_amount", "stop_trigger_method",
    "bracket_stop_loss_limit_price", "bracket_take_profit_limit_price", "bracket_stop_trigger_method",
})
_CONDITIONAL_FIELDS = frozenset({"stop_order_type", "stop_price", "trail_amount", "stop_trigger_method"})
_DECIMAL_FIELDS = frozenset({
    "limit_price", "stop_price", "trail_amount", "bracket_stop_loss_price", "bracket_take_profit_price",
    "bracket_trail_amount", "bracket_stop_loss_limit_price", "bracket_take_profit_limit_price",
})
_STOP_KINDS = frozenset({"stop_loss_order", "take_profit_order"})
_TRIGGER_METHODS = frozenset({"mark_price", "last_traded_price", "spot_price"})
_PRODUCT_FIELDS = frozenset({"product_id", "product_symbol"})
_ORDER_BRACKET_FIELDS = frozenset({
    "bracket_stop_loss_price", "bracket_stop_loss_limit_price", "bracket_take_profit_price",
    "bracket_take_profit_limit_price", "bracket_trail_amount", "bracket_stop_trigger_method",
})
_POSITION_BRACKET_FIELDS = frozenset({"stop_loss_order", "take_profit_order", "bracket_stop_trigger_method"})
_BRACKET_LEG_FIELDS = frozenset({"order_type", "stop_price", "limit_price"})


def _decimal(raw: Any, field: str, *, allow_zero: bool = False) -> tuple[str, Decimal]:
    if isinstance(raw, bool) or not isinstance(raw, (str, int, float, Decimal)):
        raise ValueError(f"Delta {field} must be a finite positive decimal")
    text = str(raw).strip()
    try:
        value = Decimal(text)
    except InvalidOperation as exc:
        raise ValueError(f"Delta {field} must be a finite positive decimal") from exc
    if not value.is_finite() or value < 0 or (not allow_zero and value == 0):
        raise ValueError(f"Delta {field} must be a finite positive decimal")
    return text, value


def _canonical_price(raw: Any, field: str) -> str | None:
    """Canonical empty/zero defaults are absent; explicit native zero is invalid."""
    if raw is None or (isinstance(raw, str) and not raw.strip()):
        return None
    text, value = _decimal(raw, field, allow_zero=True)
    return text if value != 0 else None


def _contract_size(raw: Any) -> int:
    if isinstance(raw, bool):
        raise ValueError("Delta size must be a positive integer contract count")
    try:
        return delta_mapping.contract_size(raw)
    except BrokerError as exc:
        raise ValueError("Delta size must be a positive integer contract count") from exc


def _validate_options(payload: Mapping[str, Any]) -> None:
    for field in ("post_only", "reduce_only"):
        if field in payload and type(payload[field]) is not bool:
            raise ValueError(f"Delta {field} must be a boolean")
    if "client_order_id" in payload:
        client_id = payload["client_order_id"]
        if not isinstance(client_id, str) or len(client_id) > 32:
            raise ValueError("Delta client_order_id must be a string of at most 32 characters")
    if "stop_order_type" in payload:
        kind = payload["stop_order_type"]
        if not isinstance(kind, str) or kind not in _STOP_KINDS:
            raise ValueError("Delta stop_order_type must be stop_loss_order or take_profit_order")
    for field in ("stop_trigger_method", "bracket_stop_trigger_method"):
        if field in payload and (not isinstance(payload[field], str) or payload[field] not in _TRIGGER_METHODS):
            raise ValueError(f"Delta {field} must be mark_price, last_traded_price or spot_price")


def _validate_shape(payload: Mapping[str, Any]) -> None:
    _contract_size(payload.get("size"))
    _validate_options(payload)
    order_type = payload.get("order_type")
    if not isinstance(order_type, str) or order_type not in {"limit_order", "market_order"}:
        raise ValueError("Delta order_type must be limit_order or market_order")
    if payload["order_type"] == "limit_order" and "limit_price" not in payload:
        raise ValueError("Delta limit orders require limit_price")
    if "stop_order_type" in payload and "stop_price" not in payload and "trail_amount" not in payload:
        raise ValueError("Delta conditional orders require stop_price or a positive trail_amount")
    for field in _DECIMAL_FIELDS.intersection(payload):
        _decimal(payload[field], field)


def _entry_stop(order: Any, native: Mapping[str, Any], *, bracket: bool) -> str | None:
    aliases: list[str] = []
    if "stop_price" in native:
        aliases.append(_decimal(native["stop_price"], "stop_price")[0])
    trigger = _canonical_price(getattr(order, "trigger_price", None), "trigger_price")
    if trigger is not None:
        aliases.append(trigger)
    if not bracket:
        stop = _canonical_price(getattr(order, "stop_loss_price", None), "stop_loss_price")
        if stop is not None:
            aliases.append(stop)
    if not aliases:
        return None
    if any(Decimal(alias) != Decimal(aliases[0]) for alias in aliases[1:]):
        raise ValueError("Delta stop price aliases conflict")
    return aliases[0]


def _conditional_payload(order: Any, native: Mapping[str, Any], price_type: str) -> dict[str, Any]:
    """Resolve entry triggers before validation without invoking base SL placement."""
    variety = str(getattr(order, "variety", "regular") or "regular").lower()
    if variety not in {"", "regular", "bracket"}:
        raise ValueError(f"Delta does not support order variety {variety!r}")
    payload: dict[str, Any] = {
        "product_symbol": delta_mapping.product_symbol(getattr(order, "symbol", "")),
        "size": _contract_size(getattr(order, "quantity", None)),
        "side": delta_mapping._side(getattr(order, "action", "")),
        "time_in_force": delta_mapping.time_in_force(getattr(order, "validity", None)),
        "order_type": "limit_order" if price_type in {"SL", "LIMIT"} else "market_order",
        "stop_order_type": native.get("stop_order_type", "stop_loss_order"),
        "stop_trigger_method": native.get("stop_trigger_method", "mark_price"),
    }
    if payload["order_type"] == "limit_order":
        price = _canonical_price(getattr(order, "price", None), "limit_price")
        if price is not None:
            payload["limit_price"] = price
    stop_price = _entry_stop(order, native, bracket=variety == "bracket")
    if stop_price is not None:
        payload["stop_price"] = stop_price
    if variety == "bracket":
        stop = _canonical_price(getattr(order, "stop_loss_price", None), "bracket_stop_loss_price")
        target = _canonical_price(getattr(order, "target_price", None), "bracket_take_profit_price")
        if stop is None and target is None:
            raise ValueError("Delta bracket orders require a target or stop price")
        if stop is not None:
            payload["bracket_stop_loss_price"] = stop
            payload["bracket_stop_trigger_method"] = "mark_price"
        if target is not None:
            payload["bracket_take_profit_price"] = target
        trail = _canonical_price(getattr(order, "trailing_jump", None), "bracket_trail_amount")
        if trail is not None:
            payload["bracket_trail_amount"] = trail
    return payload


def to_native_place_payload(order: Any, *, native: Mapping[str, Any], reduce_only: bool = False) -> dict[str, Any]:
    """Retain supported native options and exact decimals; apply no eligibility inference."""
    if type(reduce_only) is not bool:
        raise ValueError("Delta reduce_only must be an explicit boolean")
    if not isinstance(native, Mapping):
        raise ValueError("Delta native options must be a mapping")
    unknown = set(native) - _NATIVE_FIELDS
    if unknown:
        raise ValueError(f"Unknown Delta native fields: {', '.join(sorted(map(str, unknown)))}")
    _validate_options(native)
    _contract_size(getattr(order, "quantity", None))
    price_type = str(getattr(order, "pricetype", "MARKET") or "MARKET").upper()
    if price_type not in {"MARKET", "LIMIT", "SL", "SL-M", "SLM"}:
        raise ValueError(f"Delta does not support price type {price_type!r}")
    conditional = price_type in {"SL", "SL-M", "SLM"} or bool(_CONDITIONAL_FIELDS.intersection(native))
    if conditional:
        payload = _conditional_payload(order, native, price_type)
    else:
        if price_type == "LIMIT" and _canonical_price(getattr(order, "price", None), "limit_price") is None:
            raise ValueError("Delta limit orders require limit_price")
        payload = delta_mapping.to_place_payload(order, reduce_only=False)
    payload.update(native)
    if reduce_only:
        payload["reduce_only"] = True
    _validate_shape(payload)
    for field in _DECIMAL_FIELDS.intersection(payload):
        payload[field] = _decimal(payload[field], field)[0]
    return payload


def validate_contract_payload(payload: Mapping[str, Any], *, tick_size: str) -> None:
    """Validate contracts and exact tick multiples without mutating or rounding.

    ``tick_size`` must come from independently verified product metadata. This
    pure check makes no claim about permissions, product availability or funds.
    """
    if not isinstance(payload, Mapping):
        raise ValueError("Delta contract payload must be a mapping")
    _validate_shape(payload)
    _text, tick = _decimal(tick_size, "tick_size")
    tick_numerator, tick_denominator = tick.as_integer_ratio()
    for field in _DECIMAL_FIELDS.intersection(payload):
        _text, value = _decimal(payload[field], field)
        numerator, denominator = value.as_integer_ratio()
        if (numerator * tick_denominator) % (denominator * tick_numerator):
            raise ValueError(f"Delta {field} is not an exact multiple of tick_size")


def _positive_identity(raw: Any, field: str) -> int:
    if isinstance(raw, bool) or not isinstance(raw, (int, str)):
        raise ValueError(f"Delta {field} must be a positive integer")
    text = str(raw).strip()
    if not text or any(character not in "0123456789" for character in text):
        raise ValueError(f"Delta {field} must be a positive integer")
    try:
        value = int(text)
    except ValueError as exc:
        raise ValueError(f"Delta {field} must be a positive integer") from exc
    if value <= 0:
        raise ValueError(f"Delta {field} must be a positive integer")
    return value


def _product_identity(fields: Mapping[str, Any]) -> dict[str, Any]:
    identities = _PRODUCT_FIELDS.intersection(fields)
    if len(identities) != 1:
        raise ValueError("Delta brackets require exactly one of product_id or product_symbol")
    if "product_id" in identities:
        return {"product_id": _positive_identity(fields["product_id"], "product_id")}
    symbol = fields["product_symbol"]
    if not isinstance(symbol, str):
        raise ValueError("Delta product_symbol must be a non-empty string")
    try:
        return {"product_symbol": delta_mapping.product_symbol(symbol)}
    except BrokerError as exc:
        raise ValueError("Delta product_symbol must be a non-empty string") from exc


def _known_fields(fields: Mapping[str, Any], allowed: frozenset[str]) -> None:
    unknown = set(fields) - allowed
    if unknown:
        raise ValueError(f"Unknown Delta bracket fields: {', '.join(sorted(map(str, unknown)))}")


def to_order_bracket_edit_payload(order_id: str, changes: Mapping[str, Any]) -> dict[str, Any]:
    """Build a flat PUT /v2/orders/bracket update for an identified order.

    This is a partial order-attached bracket update, not a position-bracket
    modification. Product eligibility and verified tick checks remain external.
    """
    if not isinstance(changes, Mapping):
        raise ValueError("Delta order bracket changes must be a mapping")
    _known_fields(changes, _PRODUCT_FIELDS | _ORDER_BRACKET_FIELDS)
    payload = {"id": _positive_identity(order_id, "order id"), **_product_identity(changes)}
    if not _ORDER_BRACKET_FIELDS.intersection(changes):
        raise ValueError("Delta order bracket edits require at least one bracket change")
    _validate_options(changes)
    for field in _ORDER_BRACKET_FIELDS.intersection(changes):
        payload[field] = _decimal(changes[field], field)[0] if field in _DECIMAL_FIELDS else changes[field]
    return payload


def _position_bracket_leg(leg: Any, field: str) -> dict[str, Any]:
    if not isinstance(leg, Mapping) or not leg:
        raise ValueError(f"Delta {field} must be a non-empty mapping")
    allowed = _BRACKET_LEG_FIELDS | ({"trail_amount"} if field == "stop_loss_order" else set())
    _known_fields(leg, allowed)
    order_type = leg.get("order_type")
    if not isinstance(order_type, str) or order_type not in {"limit_order", "market_order"}:
        raise ValueError(f"Delta {field} order_type must be limit_order or market_order")
    if order_type == "limit_order" and "limit_price" not in leg:
        raise ValueError(f"Delta {field} limit orders require limit_price")
    if "stop_price" not in leg and "trail_amount" not in leg:
        raise ValueError(f"Delta {field} requires stop_price or a positive stop-loss trail_amount")
    return {
        name: _decimal(value, name)[0] if name in _DECIMAL_FIELDS else value
        for name, value in leg.items()
    }


def to_position_bracket_create_payload(request: Mapping[str, Any]) -> dict[str, Any]:
    """Build nested POST /v2/orders/bracket protection for a product's position.

    Delta allows one position bracket per contract. This mapping has no order
    ID, child identity, position size or permission inference. Validate against
    independently verified product ticks before any future gated dispatch.
    """
    if not isinstance(request, Mapping):
        raise ValueError("Delta position bracket request must be a mapping")
    _known_fields(request, _PRODUCT_FIELDS | _POSITION_BRACKET_FIELDS)
    payload = _product_identity(request)
    _validate_options(request)
    if not _STOP_KINDS.intersection(request):
        raise ValueError("Delta position brackets require at least one stop_loss_order or take_profit_order leg")
    for field in ("stop_loss_order", "take_profit_order"):
        if field in request:
            payload[field] = _position_bracket_leg(request[field], field)
    if "bracket_stop_trigger_method" in request:
        payload["bracket_stop_trigger_method"] = request["bracket_stop_trigger_method"]
    return payload


def _snapshot_contract_count(raw: Any, field: str) -> int:
    """Read exact integer counts without truncation, rounding or a zero default."""
    if isinstance(raw, bool) or not isinstance(raw, (int, str)):
        raise ValueError(f"Delta {field} must be an integer contract count")
    text = str(raw).strip()
    if not text or any(character not in "0123456789" for character in text):
        raise ValueError(f"Delta {field} must be an integer contract count")
    value = int(text)
    if field == "size" and value == 0:
        raise ValueError("Delta size must be a positive integer contract count")
    return value


def from_native_order(row: Mapping[str, Any]) -> dict[str, Any]:
    """Project one order snapshot while retaining detached, opaque native evidence.

    Counts are cumulative snapshot quantities, not incremental fill events.
    Missing counts remain absent. IDs, status text, requested/effective fields,
    timestamps and any parent/position scope survive unchanged in ``native``.
    This does not reconcile executions or establish that a position is flat.
    """
    if not isinstance(row, Mapping):
        raise ValueError("Delta native order must be a mapping")
    native = deepcopy(dict(row))
    result: dict[str, Any] = {
        "orderid": deepcopy(native.get("id")),
        "product_id": deepcopy(native.get("product_id")),
        "symbol": deepcopy(native.get("product_symbol")),
        "quantity_unit": "contracts",
        "raw_status": deepcopy(native.get("state")),
        "status": "UNKNOWN",
        "native": native,
    }
    if "size" in native:
        result["quantity"] = _snapshot_contract_count(native["size"], "size")
    if "unfilled_size" in native:
        result["remaining_quantity"] = _snapshot_contract_count(native["unfilled_size"], "unfilled_size")
    if "quantity" in result and "remaining_quantity" in result:
        if result["remaining_quantity"] > result["quantity"]:
            raise ValueError("Delta unfilled_size cannot exceed size")
        result["filled_quantity"] = result["quantity"] - result["remaining_quantity"]
    state = native.get("state")
    if isinstance(state, str):
        result["status"] = {
            "open": "WORKING", "cancelled": "CANCELLED", "canceled": "CANCELLED",
        }.get(state, "UNKNOWN")
        if state == "closed" and "filled_quantity" in result and result["remaining_quantity"] == 0:
            result["status"] = "FILLED"
    return result


def from_operation_response(payload: Mapping[str, Any], *, operation: str) -> dict[str, Any]:
    """Retain per-item and skipped-product evidence without completion inference.

    Result arrays are copied item by item without interpreting errors, child
    identities, fills or corrections. Unknown result shapes and pagination
    remain in ``raw_response``. Success, empty rows and absent cursors cannot
    establish complete books, resolved executable orders or a flat position.
    """
    if not isinstance(payload, Mapping):
        raise ValueError("Delta operation response must be a mapping")
    if not isinstance(operation, str) or not operation.strip():
        raise ValueError("Delta operation must be a non-empty string")
    result = payload.get("result")
    skipped = result.get("skipped_products") if isinstance(result, Mapping) else None
    return {
        "operation": operation,
        "raw_response": deepcopy(dict(payload)),
        "items": [deepcopy(item) for item in result] if isinstance(result, list) else [],
        "skipped_products": [deepcopy(item) for item in skipped] if isinstance(skipped, list) else [],
        "complete": False,
    }
