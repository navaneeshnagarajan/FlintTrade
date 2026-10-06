"""Pure serializers for Groww's native GTT and OCO smart-order dictionaries.

These helpers validate wire fields, not account or instrument eligibility. GTT
product/segment eligibility and OCO leg-role eligibility require independent
checks before integration. Quantities retain native units; lot, tick and freeze
checks are the eventual caller's responsibility. The supplied OCO net position
is a caller-provided snapshot, not an atomic broker reduce-only guarantee.

No transport, authentication, readiness gate, execution or fill evidence is
provided here. The GTT trigger's broker-default lifetime is distinct from the
post-trigger order's DAY duration. Child bracket writes are not mapped because
the linked REST documentation does not establish their field schema.
"""

from __future__ import annotations

import re
from collections.abc import Mapping
from copy import deepcopy
from decimal import Decimal, InvalidOperation
from typing import Any

_COMMON_FIELDS = frozenset(
    {
        "reference_id",
        "smart_order_type",
        "segment",
        "trading_symbol",
        "quantity",
        "product_type",
        "exchange",
        "duration",
    }
)
_GTT_FIELDS = _COMMON_FIELDS | {"trigger_price", "trigger_direction", "order"}
_OCO_FIELDS = _COMMON_FIELDS | {"net_position_quantity", "transaction_type", "target", "stop_loss"}
_ORDER_TYPES = frozenset({"LIMIT", "MARKET", "SL", "SL_M"})
_LIMIT_TYPES = frozenset({"LIMIT", "SL"})
_SIDES = frozenset({"BUY", "SELL"})
_DECIMAL_TEXT = re.compile(r"[+-]?(?:[0-9]+(?:\.[0-9]*)?|\.[0-9]+)(?:[eE][+-]?[0-9]+)?")
_REFERENCE_ID = re.compile(r"[A-Za-z0-9-]{8,20}")


def _fields(
    value: Any, required: frozenset[str], field: str, *, optional: frozenset[str] = frozenset()
) -> dict[str, Any]:
    if not isinstance(value, Mapping):
        raise ValueError(f"{field} must be a mapping")
    result = dict(value)
    if set(result) - (required | optional):
        raise ValueError(f"{field} contains unsupported fields")
    if required - set(result):
        raise ValueError(f"{field} is missing required fields")
    return result


def _enum(value: Any, choices: frozenset[str], field: str) -> str:
    if not isinstance(value, str) or value not in choices:
        raise ValueError(f"{field} must use a documented native value")
    return value


def _price(value: Any, field: str) -> str:
    if not isinstance(value, str) or _DECIMAL_TEXT.fullmatch(value) is None:
        raise ValueError(f"{field} must be a positive finite decimal string")
    try:
        price = Decimal(value)
    except InvalidOperation as exc:
        raise ValueError(f"{field} must be a positive finite decimal string") from exc
    if not price.is_finite() or price <= 0:
        raise ValueError(f"{field} must be a positive finite decimal string")
    return value


def _integer(value: Any, field: str, *, signed: bool = False) -> int:
    if type(value) is not int or (value == 0 if signed else value <= 0):
        raise ValueError(f"{field} must be a {'non-zero signed' if signed else 'positive'} integer")
    return value


def _common(request: Mapping[str, Any], family: str, fields: frozenset[str]) -> dict[str, Any]:
    result = _fields(request, fields, "request")
    _enum(result["smart_order_type"], frozenset({family}), "smart_order_type")
    reference = result["reference_id"]
    if not isinstance(reference, str) or _REFERENCE_ID.fullmatch(reference) is None or reference.count("-") > 2:
        raise ValueError("reference_id must contain 8-20 ASCII alphanumeric/hyphen characters and at most two hyphens")
    symbol = result["trading_symbol"]
    if not isinstance(symbol, str) or not symbol or symbol != symbol.strip() or not symbol.isprintable():
        raise ValueError("trading_symbol must be a non-blank, unpadded printable string")
    _integer(result["quantity"], "quantity")
    _enum(result["segment"], frozenset({"CASH", "FNO"}), "segment")
    _enum(result["product_type"], frozenset({"CNC", "MIS", "NRML"}), "product_type")
    _enum(result["exchange"], frozenset({"NSE", "BSE"}), "exchange")
    _enum(result["duration"], frozenset({"DAY"}), "duration")
    return result


def _order(value: Any, field: str, *, triggered: bool) -> dict[str, Any]:
    required = frozenset({"order_type", "trigger_price"} if triggered else {"order_type", "transaction_type"})
    result = _fields(value, required, field, optional=frozenset({"price"}))
    order_type = _enum(result["order_type"], _ORDER_TYPES, f"{field}.order_type")
    if triggered:
        _price(result["trigger_price"], f"{field}.trigger_price")
    else:
        _enum(result["transaction_type"], _SIDES, f"{field}.transaction_type")
    if order_type in _LIMIT_TYPES:
        _price(result.get("price"), f"{field}.price")
    elif "price" in result and result["price"] is not None:
        _price(result["price"], f"{field}.price")
    return result


def to_gtt_create_payload(request: Mapping[str, Any]) -> dict[str, Any]:
    """Return a fresh native GTT creation payload without establishing eligibility.

    Args:
        request: Explicit Groww creation fields, including a nested execution order.

    Returns:
        A separate dictionary retaining decimal text and native quantity units.

    Raises:
        ValueError: A required field is absent, unsupported or malformed.
    """
    result = _common(request, "GTT", _GTT_FIELDS)
    _price(result["trigger_price"], "trigger_price")
    _enum(result["trigger_direction"], frozenset({"UP", "DOWN"}), "trigger_direction")
    result["order"] = _order(result["order"], "order", triggered=False)
    return result


def to_oco_create_payload(request: Mapping[str, Any]) -> dict[str, Any]:
    """Return native OCO fields sized against the supplied signed position snapshot.

    Args:
        request: Explicit Groww fields, target/stop objects and current net quantity.

    Returns:
        A fresh dictionary with an exit side opposing the supplied exposure.
        Snapshot validation establishes no atomic reduce-only or fill guarantee.

    Raises:
        ValueError: Fields are malformed, product scope is undocumented, or sizing
            would exceed or increase the supplied exposure.
    """
    result = _common(request, "OCO", _OCO_FIELDS)
    expected_product = "MIS" if result["segment"] == "CASH" else "NRML"
    if result["product_type"] != expected_product:
        raise ValueError("OCO product_type must be MIS for CASH or NRML for FNO")
    net_quantity = _integer(result["net_position_quantity"], "net_position_quantity", signed=True)
    side = _enum(result["transaction_type"], _SIDES, "transaction_type")
    if side != ("SELL" if net_quantity > 0 else "BUY"):
        raise ValueError("transaction_type must oppose the supplied net position")
    if result["quantity"] > abs(net_quantity):
        raise ValueError("quantity must not exceed the supplied absolute net position")
    result["target"] = _order(result["target"], "target", triggered=True)
    result["stop_loss"] = _order(result["stop_loss"], "stop_loss", triggered=True)
    return result


_SMART_TYPES = frozenset({"GTT", "OCO"})
_SEGMENTS = frozenset({"CASH", "FNO"})
_RESOURCE_ID = re.compile(r"[A-Za-z0-9_-]+")
_GTT_EDITS = frozenset({"quantity", "trigger_price", "trigger_direction", "order"})
_OCO_EDITS = frozenset({"quantity", "duration", "product_type", "target", "stop_loss"})


def _mapping(value: Any, field: str) -> dict[str, Any]:
    if not isinstance(value, Mapping):
        raise ValueError(f"{field} must be a mapping")
    return dict(value)


def _resource_identity(smart_order_id: Any, segment: Any, smart_order_type: Any) -> tuple[str, str, str]:
    if not isinstance(smart_order_id, str) or _RESOURCE_ID.fullmatch(smart_order_id) is None:
        raise ValueError(
            "smart_order_id must contain only non-empty ASCII alphanumeric, underscore or hyphen characters"
        )
    return (
        smart_order_id,
        _enum(segment, _SEGMENTS, "segment"),
        _enum(smart_order_type, _SMART_TYPES, "smart_order_type"),
    )


def smart_resource_path(operation: str, *, smart_order_id: str, segment: str, smart_order_type: str) -> str:
    """Return a native resource path with explicit, validated identity.

    Args:
        operation: ``modify`` (PUT), ``cancel`` (POST) or ``get`` (GET).
        smart_order_id: Opaque native identifier, never a creation reference.
        segment: Explicit native CASH or FNO segment.
        smart_order_type: Explicit native GTT or OCO family.

    Returns:
        A relative REST path. Cancellation has no invented request body.

    Raises:
        ValueError: Identity is absent/unsafe or the operation is unsupported.
    """
    _enum(operation, frozenset({"modify", "cancel", "get"}), "operation")
    identifier, segment, family = _resource_identity(smart_order_id, segment, smart_order_type)
    if operation == "modify":
        return f"/v1/order-advance/modify/{identifier}"
    if operation == "cancel":
        return f"/v1/order-advance/cancel/{segment}/{family}/{identifier}"
    return f"/v1/order-advance/status/{segment}/{family}/internal/{identifier}"


def _edits(value: Any, field: str, allowed: frozenset[str]) -> dict[str, Any]:
    result = _fields(value, frozenset(), field, optional=allowed)
    if not result:
        raise ValueError(f"{field} must contain an explicit editable field")
    return result


def _modify_gtt(current: dict[str, Any], changes: dict[str, Any]) -> dict[str, Any]:
    effective = {**current, **changes}
    for name in ("quantity", "trigger_price", "trigger_direction", "product_type", "duration"):
        if name not in effective:
            continue
        value = effective[name]
        if name == "quantity":
            _integer(value, name)
        elif name == "trigger_price":
            _price(value, name)
        else:
            choices = {
                "trigger_direction": frozenset({"UP", "DOWN"}),
                "product_type": frozenset({"CNC", "MIS", "NRML"}),
                "duration": frozenset({"DAY"}),
            }
            _enum(value, choices[name], name)
    current_order = _mapping(current.get("order"), "current.order")
    side = _enum(current_order.get("transaction_type"), _SIDES, "current.order.transaction_type")
    edits = _edits(changes["order"], "changes.order", frozenset({"order_type", "price"})) if "order" in changes else {}
    merged_order = {**current_order, **edits}
    order_type = _enum(merged_order.get("order_type"), _ORDER_TYPES, "order.order_type")
    if order_type in _LIMIT_TYPES:
        price = _price(merged_order.get("price"), "order.price")
    else:
        if "price" in edits and edits["price"] is not None:
            raise ValueError("GTT modification order.price must be null for MARKET or SL_M")
        price = None
    # Use the documented complete order shape. Do not forward returned metadata
    # or replay unrelated outer fields. Freshness and concurrent overwrites are
    # caller prerequisites; this mapper supplies no atomic update protection.
    result = {name: value for name, value in changes.items() if name != "order"}
    result["order"] = {"order_type": order_type, "price": price, "transaction_type": side}
    return result


def _validate_current_oco_leg(value: Any, field: str) -> dict[str, Any]:
    leg = _mapping(value, field)
    if "trigger_price" in leg:
        _price(leg["trigger_price"], f"{field}.trigger_price")
    if "order_type" in leg:
        order_type = _enum(leg["order_type"], _ORDER_TYPES, f"{field}.order_type")
        if order_type in _LIMIT_TYPES:
            _price(leg.get("price"), f"{field}.price")
    if "price" in leg and leg["price"] is not None:
        _price(leg["price"], f"{field}.price")
    return leg


def _modify_oco(current: dict[str, Any], changes: dict[str, Any], segment: str) -> dict[str, Any]:
    effective = {**current, **changes}
    if "quantity" in effective:
        _integer(effective["quantity"], "quantity")
    if "duration" in effective:
        _enum(effective["duration"], frozenset({"DAY"}), "duration")
    if "product_type" in effective:
        _enum(effective["product_type"], frozenset({"MIS" if segment == "CASH" else "NRML"}), "product_type")
    result = {name: value for name, value in changes.items() if name not in {"target", "stop_loss"}}
    for field in ("target", "stop_loss"):
        if field in current:
            leg = _mapping(current[field], f"current.{field}")
        else:
            leg = {}
        if field in changes:
            edits = _edits(changes[field], f"changes.{field}", frozenset({"trigger_price"}))
            leg.update(edits)
            result[field] = edits
        if field in current or field in changes:
            _validate_current_oco_leg(leg, field)
    # Creation-only constraints are optional for modify. If supplied, neither
    # half may be guessed, ignored or emitted. Their freshness is not proven.
    snapshot = {"net_position_quantity", "transaction_type"} & current.keys()
    if snapshot:
        if snapshot != {"net_position_quantity", "transaction_type"}:
            raise ValueError("OCO supplied snapshot constraints require both net position and transaction side")
        net = _integer(current["net_position_quantity"], "net_position_quantity", signed=True)
        side = _enum(current["transaction_type"], _SIDES, "transaction_type")
        if side != ("SELL" if net > 0 else "BUY"):
            raise ValueError("transaction_type must oppose the supplied net position")
        quantity = _integer(effective.get("quantity"), "quantity")
        if quantity > abs(net):
            raise ValueError("quantity must not exceed the supplied absolute net position")
    return result


def to_smart_modify_payload(current: Mapping[str, Any], changes: Mapping[str, Any]) -> dict[str, Any]:
    """Return resource-specific edit fields without granting execution authority.

    Args:
        current: Native state with explicit id/type/segment. GTT requires its
            current immutable side and enough order fields for a full effective
            order. OCO exposure/side constraints are optional, but must be a
            complete valid pair if supplied. Returned metadata is not emitted.
        changes: Explicit supported edits; unknown and immutable fields fail.

    Returns:
        A fresh native body with type/segment, sparse outer edits, and the full
        effective GTT order or only edited OCO leg triggers. MARKET/SL_M null
        pricing is a GTT modify rule, distinct from optional creation pricing.

    Raises:
        ValueError: Identity, edits or effective supplied fields are malformed.

    This function never cancels/recreates. Full GTT order replay requires fresh
    current state and can overwrite an external concurrent order change. OCO
    resizing still needs authoritative position/freshness/eligibility checks.
    No permissions, readiness, atomic reduce-only, fill or closure are proven.
    """
    state = _mapping(current, "current")
    _, segment, family = _resource_identity(
        state.get("smart_order_id"), state.get("segment"), state.get("smart_order_type")
    )
    edits = _edits(changes, "changes", _GTT_EDITS if family == "GTT" else _OCO_EDITS)
    result = _modify_gtt(state, edits) if family == "GTT" else _modify_oco(state, edits, segment)
    return {"smart_order_type": family, "segment": segment, **result}


def from_smart_order(row: Mapping[str, Any]) -> dict[str, Any]:
    """Preserve a native smart resource as observation, never execution evidence.

    Only an explicit nonblank string smart_order_id is required. Abbreviated
    responses may omit family/segment; unknown scope is retained without write
    validation, filtering or defaults. This identity is insufficient for scoped
    dispatch or account reconciliation and does not establish path safety.

    ACTIVE means ARMED; CANCELLED describes this resource only. All other
    statuses remain UNKNOWN, including COMPLETED. Neither timestamps, returned
    order IDs nor permission flags prove fills, a closed position or authority.
    Undocumented children and returned failures remain opaque in a deep copy.

    Raises:
        ValueError: The row is not a mapping or its smart identity is missing.
    """
    state = _mapping(row, "row")
    identifier = state.get("smart_order_id")
    if not isinstance(identifier, str) or not identifier.strip():
        raise ValueError("smart_order_id must be an explicit nonblank string")
    native = deepcopy(state)
    raw_status = native.get("status")
    status = "UNKNOWN"
    if isinstance(raw_status, str):
        status = {"ACTIVE": "ARMED", "CANCELLED": "CANCELLED"}.get(raw_status, "UNKNOWN")
    return {
        "smart_order_id": identifier,
        "smart_order_type": native.get("smart_order_type"),
        "segment": native.get("segment"),
        "raw_status": raw_status,
        "status": status,
        "native": native,
    }


def from_smart_page(payload: Mapping[str, Any]) -> list[dict[str, Any]]:
    """Map every row of one explicit successful native orders page, in order.

    The argument is the full SUCCESS/payload/orders response envelope. An
    explicit empty list returns []; it establishes neither a complete book nor
    absent orders/positions. Pagination, time filters and account completeness
    remain the caller's responsibility. No family/product/segment is filtered.
    A malformed item fails the whole conversion rather than returning a partial
    page. Native per-item failures remain evidence and are not dropped.

    Raises:
        ValueError: The envelope is unavailable/malformed or a row lacks identity.
    """
    envelope = _mapping(payload, "response")
    if envelope.get("status") != "SUCCESS":
        raise ValueError("response status must be SUCCESS")
    page = _mapping(envelope.get("payload"), "payload")
    orders = page.get("orders")
    if not isinstance(orders, list):
        raise ValueError("payload.orders must be an explicit list")
    return [from_smart_order(row) for row in orders]
