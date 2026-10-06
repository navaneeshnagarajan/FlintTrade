"""Unwired INDstocks public REST request contracts, not runtime readiness.

Only the dated public schema is represented. Instrument, tick/lot/freeze,
account, funds, holdings, session and permission checks belong to integration.
No function sends orders or establishes execution, protection or replay safety.
"""

from collections.abc import Mapping
from decimal import Decimal, InvalidOperation
from math import isfinite

SCHEMA_ID = "indstocks-public-rest-2026-10-06"


def _mapping(value: object) -> Mapping[str, object]:
    if not isinstance(value, Mapping):
        raise ValueError("Expected a mapping")
    return value


def _identity(value: object, field: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{field} must be a nonblank string")
    return value


def _choice(value: object, choices: set[str], field: str) -> str:
    if not isinstance(value, str) or value not in choices:
        raise ValueError(f"Unsupported {field}")
    return value


def _decimal(value: object, field: str) -> Decimal:
    if isinstance(value, bool) or not isinstance(value, (str, int, float, Decimal)):
        raise ValueError(f"{field} must be numeric")
    try:
        number = Decimal(str(value))
    except (InvalidOperation, ValueError):
        raise ValueError(f"Invalid {field}") from None
    if not number.is_finite():
        raise ValueError(f"{field} must be finite")
    return number


def _number(value: Decimal, field: str, *, integer: bool = False, zero: bool = False) -> int | float:
    if value < 0 or (value == 0 and not zero):
        raise ValueError(f"{field} must be {'nonnegative' if zero else 'positive'}")
    if integer:
        if value != value.to_integral_value():
            raise ValueError(f"{field} must be integral")
        return int(value)
    if value == value.to_integral_value():
        return int(value)
    result = float(value)
    if not isfinite(result) or Decimal(str(result)) != value:
        raise ValueError(f"{field} cannot be represented faithfully as a JSON number")
    return result


def _alias(
    data: Mapping[str, object],
    *fields: str,
    required: bool = False,
    integer: bool = False,
    zero: bool = False,
) -> int | float | None:
    values = [_decimal(data[field], field) for field in fields if field in data]
    if not values:
        if required:
            raise ValueError(f"Missing {fields[0]}")
        return None
    if any(value != values[0] for value in values[1:]):
        raise ValueError(f"Conflicting aliases: {', '.join(fields)}")
    return _number(values[0], fields[0], integer=integer, zero=zero)


def _trailing_requested(order: Mapping[str, object]) -> bool:
    flag = order.get("is_tsl", False)
    if not isinstance(flag, bool):
        raise ValueError("is_tsl must be boolean")
    # Validate every supplied field even when the flag is already true.
    steps = [_decimal(order[field], field) for field in ("tsl_step_size", "trailing_jump") if field in order]
    return flag or any(step != 0 for step in steps)


def _known(data: Mapping[str, object], fields: set[str]) -> None:
    if any(field not in fields for field in data):
        raise ValueError("Unsupported mutation fields")


def normal_payload(order: Mapping[str, object], *, security_id: str, algo_id: str) -> dict[str, object]:
    """Build a standard placement body; active trailing requests are refused.

    DAY only: published IOC enum and DAY-only validation conflict. MARKET stays
    MARKET on the wire; callers must also surface execution_effects to users.
    """
    order = _mapping(order)
    _known(
        order,
        {
            "action",
            "exchange",
            "product",
            "pricetype",
            "quantity",
            "qty",
            "price",
            "limit_price",
            "validity",
            "variety",
            "is_amo",
            "remarks",
            "is_tsl",
            "tsl_step_size",
            "trailing_jump",
        },
    )
    security_id = _identity(security_id, "security_id")
    algo_id = _identity(algo_id, "algo_id")
    action = _choice(order.get("action"), {"BUY", "SELL"}, "action")
    exchange = _choice(order.get("exchange"), {"NSE", "BSE", "NFO", "BFO"}, "exchange")
    segment = "DERIVATIVE" if exchange in {"NFO", "BFO"} else "EQUITY"
    product = _choice(order.get("product"), {"MIS", "CNC", "NRML", "INTRADAY", "MARGIN"}, "product")
    product = {"MIS": "INTRADAY", "NRML": "MARGIN"}.get(product, product)
    if (segment == "EQUITY" and product == "MARGIN") or (segment == "DERIVATIVE" and product == "CNC"):
        raise ValueError("Product is incompatible with segment")
    order_type = _choice(order.get("pricetype"), {"LIMIT", "MARKET"}, "pricetype")
    validity = _choice(order.get("validity", "DAY"), {"DAY"}, "validity")
    variety = _choice(order.get("variety", "regular"), {"regular", "amo"}, "variety")
    is_amo = order.get("is_amo", variety == "amo")
    if not isinstance(is_amo, bool):
        raise ValueError("is_amo must be boolean")
    if "variety" in order and "is_amo" in order and is_amo != (variety == "amo"):
        raise ValueError("Conflicting variety/is_amo")
    if _trailing_requested(order):
        raise ValueError("TSL_IGNORED: active trailing is unsupported")
    qty = _alias(order, "quantity", "qty", required=True, integer=True)
    price = _alias(order, "price", "limit_price", required=order_type == "LIMIT", zero=order_type == "MARKET")
    body: dict[str, object] = {
        "txn_type": action,
        "exchange": {"NFO": "NSE", "BFO": "BSE"}.get(exchange, exchange),
        "segment": segment,
        "product": product,
        "qty": qty,
        "order_type": order_type,
        "validity": validity,
        "security_id": security_id,
        "is_amo": is_amo,
        "algo_id": algo_id,
    }
    if order_type == "LIMIT":
        body["limit_price"] = price
    if "remarks" in order:
        remarks = order["remarks"]
        if not isinstance(remarks, str) or len(remarks) > 100 or remarks.strip().casefold() == "tv-terminal":
            raise ValueError("Invalid remarks")
        body["remarks"] = remarks
    return body


def normal_modify(order_id: str, changes: Mapping[str, object], *, segment: str) -> dict[str, object]:
    """Build a quantity-and-price change without inferring segment from an ID."""
    changes = _mapping(changes)
    _known(changes, {"quantity", "qty", "price", "limit_price"})
    order_id = _identity(order_id, "order_id")
    segment = _choice(segment, {"EQUITY", "DERIVATIVE"}, "segment")
    if (order_id.startswith("EQ-") and segment != "EQUITY") or (
        order_id.startswith("DRV-") and segment != "DERIVATIVE"
    ):
        raise ValueError("Order prefix contradicts explicit segment")
    return {
        "order_id": order_id,
        "segment": segment,
        "qty": _alias(changes, "quantity", "qty", required=True, integer=True),
        "limit_price": _alias(changes, "price", "limit_price", required=True),
    }


def execution_effects(order: Mapping[str, object]) -> dict[str, object]:
    """Describe documented transformations, never actual execution or protection.

    requested is a shallow copy. Unknown source context is retained as evidence;
    this projection is not payload validation or permission to submit an order.
    MARKET's live effective limit cannot be known from a request alone.
    """
    order = _mapping(order)
    requested_type = _choice(order.get("pricetype"), {"LIMIT", "MARKET", "TRIGGER"}, "pricetype")
    limitations: list[str] = []
    if requested_type == "TRIGGER":
        if "limit_price" in order:
            raise ValueError("TRIGGER uses trigger_limit_price, not limit_price")
        trigger = _alias(order, "trigger_price", required=True)
        price = _alias(order, "price", "trigger_limit_price")
        effective_price = trigger if price is None else price
        effective_type = "TRIGGER_LIMIT"
    else:
        if "trigger_price" in order or "trigger_limit_price" in order:
            raise ValueError("Trigger fields require TRIGGER")
        price = _alias(
            order, "price", "limit_price", required=requested_type == "LIMIT", zero=requested_type == "MARKET"
        )
        effective_price = price
        effective_type = "LIMIT"
        if requested_type == "MARKET":
            effective_price = None
            limitations.append("MARKET_TO_LIMIT")
    if _trailing_requested(order):
        limitations.append("TSL_IGNORED")
    return {
        "schema_id": SCHEMA_ID,
        "requested_type": requested_type,
        "effective_type": effective_type,
        "effective_limit_price": effective_price,
        "trailing_active": False,
        "limitations": limitations,
        "requested": dict(order),
    }


_LEG_FIELDS = {"sl_trigger_price", "sl_limit_price", "tgt_trigger_price", "tgt_limit_price"}
_LEG_ALIASES = {"stop_loss_price", "target_price"}


def _smart_legs(data: Mapping[str, object], *, paired: bool) -> dict[str, object]:
    legs: dict[str, object] = {}
    for prefix, alias in (("sl", "stop_loss_price"), ("tgt", "target_price")):
        trigger_field, limit_field = f"{prefix}_trigger_price", f"{prefix}_limit_price"
        trigger = _alias(data, trigger_field, alias)
        limit = _alias(data, limit_field)
        if paired and (trigger is None) != (limit is None):
            raise ValueError("Protective legs require both trigger and limit prices")
        if trigger is not None:
            legs[trigger_field] = trigger
        if limit is not None:
            legs[limit_field] = limit
    return legs


def smart_payload(order: Mapping[str, object], *, security_id: str, algo_id: str) -> dict[str, object]:
    """Build a smart body without asserting live protection or eligibility.

    MARKET entry/CMP and BSE smart eligibility remain unverified. The source's
    market price is never treated as a live entry. Trigger defaults remain
    broker-side; execution_effects describes their effective semantics.
    """
    order = _mapping(order)
    _known(
        order,
        {
            "action",
            "exchange",
            "product",
            "pricetype",
            "quantity",
            "qty",
            "price",
            "limit_price",
            "trigger_price",
            "trigger_limit_price",
            "validity",
            "variety",
            "remarks",
            "is_tsl",
            "tsl_step_size",
            "trailing_jump",
        }
        | _LEG_FIELDS
        | _LEG_ALIASES,
    )
    variety = _choice(order.get("variety"), {"gtt", "oco", "trigger"}, "variety")
    order_type = _choice(order.get("pricetype"), {"LIMIT", "MARKET", "TRIGGER"}, "pricetype")
    if (variety == "trigger") != (order_type == "TRIGGER"):
        raise ValueError("Smart variety and order type disagree")
    effects = execution_effects(order)
    if effects["trailing_active"] or "TSL_IGNORED" in effects["limitations"]:
        raise ValueError("TSL_IGNORED: active trailing is unsupported")
    # Reuse the normal common-field validation without forwarding smart-only
    # fields or mutating the source. Only the common body is retained below.
    common = {
        key: value
        for key, value in order.items()
        if key
        in {
            "action",
            "exchange",
            "product",
            "quantity",
            "qty",
            "validity",
            "remarks",
        }
    }
    common["pricetype"] = "LIMIT" if order_type == "TRIGGER" else order_type
    if order_type != "MARKET":
        common["price"] = effects["effective_limit_price"]
    body = normal_payload(common, security_id=security_id, algo_id=algo_id)
    del body["is_amo"]
    body.pop("limit_price", None)
    body["order_type"] = order_type
    if order_type == "LIMIT":
        body["limit_price"] = effects["effective_limit_price"]
    elif order_type == "TRIGGER":
        body["trigger_price"] = _alias(order, "trigger_price", required=True)
        trigger_limit = _alias(order, "price", "trigger_limit_price")
        if trigger_limit is not None:
            body["trigger_limit_price"] = trigger_limit
    legs = _smart_legs(order, paired=True)
    if variety in {"gtt", "oco"} and not legs:
        raise ValueError("GTT/OCO requires at least one paired protective leg")
    entry = effects["effective_limit_price"]
    for prefix in ("sl", "tgt"):
        trigger = legs.get(f"{prefix}_trigger_price")
        if trigger is None:
            continue
        limit = legs[f"{prefix}_limit_price"]
        below = (body["txn_type"] == "BUY") == (prefix == "sl")
        # Limit-to-trigger ordering is independently knowable for MARKET too.
        if (below and limit >= trigger) or (not below and limit <= trigger):
            raise ValueError("Protective limit is on the wrong side of its trigger")
        if entry is not None and ((below and trigger >= entry) or (not below and trigger <= entry)):
            raise ValueError("Protective trigger is on the wrong side of entry")
    body.update(legs)
    return body


def cancel_payload(order_id: str, *, segment: str) -> dict[str, object]:
    """Address exactly one resource; infer no GTT segment, role or sibling effect."""
    order_id = _identity(order_id, "order_id")
    segment = _choice(segment, {"EQUITY", "DERIVATIVE"}, "segment")
    if (order_id.startswith("EQ-") and segment != "EQUITY") or (
        order_id.startswith("DRV-") and segment != "DERIVATIVE"
    ):
        raise ValueError("Order prefix contradicts explicit segment")
    return {"order_id": order_id, "segment": segment}


def smart_modify(
    order_id: str,
    changes: Mapping[str, object],
    *,
    segment: str,
    existing_order_type: str,
    algo_id: str,
) -> dict[str, object]:
    """Build only documented supplied edits bound to explicit existing type.

    Partial leg edits are supported by the schema. Their relationship to the
    unchanged leg, entry, side and CMP requires authoritative existing state;
    no such state is inferred here. MARKET price edits are refused as ignored.
    """
    changes = _mapping(changes)
    _known(
        changes,
        {
            "quantity",
            "qty",
            "order_type",
            "price",
            "limit_price",
            "trigger_price",
            "trigger_limit_price",
        }
        | _LEG_FIELDS
        | _LEG_ALIASES,
    )
    body = cancel_payload(order_id, segment=segment)
    body["algo_id"] = _identity(algo_id, "algo_id")
    existing_order_type = _choice(existing_order_type, {"LIMIT", "MARKET", "TRIGGER"}, "existing_order_type")
    if "order_type" in changes:
        requested_type = _choice(changes["order_type"], {"LIMIT", "MARKET", "TRIGGER"}, "order_type")
        if requested_type != existing_order_type:
            raise ValueError("Requested type differs from existing order type")
        body["order_type"] = requested_type
    qty = _alias(changes, "quantity", "qty", integer=True)
    if qty is not None:
        body["qty"] = qty
    if existing_order_type == "TRIGGER":
        if "limit_price" in changes:
            raise ValueError("TRIGGER uses trigger_limit_price, not limit_price")
        body["trigger_price"] = _alias(changes, "trigger_price", required=True)
        price = _alias(changes, "price", "trigger_limit_price")
        if price is not None:
            body["trigger_limit_price"] = price
    else:
        if "trigger_price" in changes or "trigger_limit_price" in changes:
            raise ValueError("Trigger fields require TRIGGER")
        if existing_order_type == "MARKET" and ("price" in changes or "limit_price" in changes):
            raise ValueError("MARKET price changes are not supported")
        price = _alias(changes, "price", "limit_price")
        if price is not None:
            body["limit_price"] = price
    body.update(_smart_legs(changes, paired=False))
    return body


# Exact resource-status vocabulary. Feed PF/PFC/numeric IDs are deliberately
# outside this REST projection; no fuzzy matching or execution correlation.
_ATTEMPT_STATES = {
    "SUCCESS": "FILLED",
    "CANCELLED": "CANCELLED",
    "PARTIALLY FILLED - CANCELLED": "CANCELLED",
    "EXPIRED": "EXPIRED",
    "PARTIALLY FILLED - EXPIRED": "EXPIRED",
    "PARTIALLY FILLED": "PARTIALLY_FILLED",
    "INITIATED": "ACKNOWLEDGED",
    "QUEUED": "SUBMITTING",
    "PROCESSING": "SUBMITTING",
    "O-PENDING": "WORKING",
    "SL-PENDING": "WORKING",
    "PENDING": "WORKING",
    "MODIFIED": "WORKING",
    "CANCEL_PENDING": "CANCEL_PENDING",
    "CANCEL_REQUESTED": "CANCEL_PENDING",
    "CANCEL PENDING": "CANCEL_PENDING",
    "CANCEL REQUESTED": "CANCEL_PENDING",
    "CANCEL-PENDING": "CANCEL_PENDING",
    "CANCEL-REQUESTED": "CANCEL_PENDING",
    "CANCELLATION_PENDING": "CANCEL_PENDING",
    "CANCELLATION_REQUESTED": "CANCEL_PENDING",
    "CANCELLATION PENDING": "CANCEL_PENDING",
    "CANCELLATION REQUESTED": "CANCEL_PENDING",
}


def attempt_state(status: object) -> str:
    """Interpret an exact ordinary REST order status, never a trigger outcome.

    ACK is not a fill. UNKNOWN is not rejection or permission to replay.
    Resource context must be checked separately (as project_order does).
    """
    return _ATTEMPT_STATES.get(status, "UNKNOWN") if isinstance(status, str) else "UNKNOWN"


def _read_text(value: object, field: str) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str):
        raise ValueError(f"{field} must be a string or null")
    return value if value.strip() else None


def _read_alias(row: Mapping[str, object], *fields: str, numeric: bool = False) -> object:
    """Reconcile only supplied aliases; blank identities are absent evidence.

    Quantities are stricter: an explicitly blank/null quantity is malformed,
    whereas an omitted quantity is unknown. Zero is always retained.
    """
    values = []
    for field in fields:
        if field in row:
            value = (
                _number(_decimal(row[field], field), field, integer=True, zero=True)
                if numeric
                else _read_text(row[field], field)
            )
            values.append(value)
    if any(value != values[0] for value in values[1:]):
        raise ValueError(f"Conflicting aliases: {', '.join(fields)}")
    return values[0] if values else None


def _read_price(row: Mapping[str, object], field: str) -> int | float | None:
    value = row.get(field)
    if value is None or (isinstance(value, str) and not value.strip()):
        return None
    return _number(_decimal(value, field), field, zero=True)


def project_order(row: Mapping[str, object]) -> dict[str, object]:
    """Preserve a REST order row without inventing trigger or fill evidence.

    Missing/blank optional identities and prices project to None; raw retains
    their distinction. Quantities never default to zero. GTT/OCO resources
    cannot prove the execution state of any spawned exchange order.
    """
    row = _mapping(row)
    order_id = _read_alias(row, "id", "orderid", "order_id")
    quantity = _read_alias(row, "requested_qty", "quantity", numeric=True)
    filled = _read_alias(row, "traded_qty", "filled_quantity", numeric=True)
    if quantity is not None and filled is not None and filled > quantity:
        raise ValueError("Filled quantity exceeds requested quantity")
    status = _read_alias(row, "status", "order_status")
    order_type = _read_text(row.get("order_type"), "order_type")
    is_trigger_resource = (isinstance(order_id, str) and order_id.startswith("GTT-")) or order_type in {"GTT", "OCO"}
    result = {
        "schema_id": SCHEMA_ID,
        "raw": dict(row),
        "orderid": order_id,
        "quantity": quantity,
        "filled_quantity": filled,
        "exchange_order_id": _read_alias(row, "exch_order_id", "exchange_order_id"),
        # Preserve the exact raw status, including a blank string, independently
        # of its conservative interpretation.
        "status": row.get("status", row.get("order_status")),
        "attempt_state": "UNKNOWN" if is_trigger_resource else attempt_state(status),
    }
    for field in (
        "security_id",
        "exchange",
        "segment",
        "product",
        "txn_type",
        "order_type",
        "validity",
        "created_at",
        "updated_at",
        "remarks",
        "extra_info",
    ):
        value = row.get(field)
        if field in {"remarks", "extra_info"}:
            # Read evidence is not placement input: don't truncate, reserve or
            # normalise broker messages and tags.
            if value is not None and not isinstance(value, str):
                raise ValueError(f"{field} must be a string or null")
            result[field] = value
        else:
            result[field] = _read_text(value, field)
    for field in (
        "requested_price",
        "traded_price",
        "trigger_price",
        "trigger_limit_price",
        "sl_trigger_price",
        "sl_limit_price",
        "tgt_trigger_price",
        "tgt_limit_price",
    ):
        result[field] = _read_price(row, field)
    return result


def project_fill(row: Mapping[str, object], *, order_id: str | None = None) -> dict[str, object]:
    """Project one fill without substituting its exchange ID for an order ID.

    fill_id and trade_serial_no remain independent fill identities. Numeric
    fill_id is retained as an integer; it is never an order correlation key.
    """
    row = _mapping(row)
    row_order = _read_alias(row, "order_id", "orderid")
    if order_id is not None:
        _identity(order_id, "order_id")
        if row_order is not None and row_order != order_id:
            raise ValueError("Conflicting explicit and row order IDs")
    fill_id = row.get("fill_id")
    if fill_id is not None and not (isinstance(fill_id, str) and not fill_id.strip()):
        fill_id = _number(_decimal(fill_id, "fill_id"), "fill_id", integer=True, zero=True)
    else:
        fill_id = None
    result = {
        "schema_id": SCHEMA_ID,
        "raw": dict(row),
        "order_id": order_id if order_id is not None else row_order,
        "fill_id": fill_id,
        "quantity": _read_alias(row, "quantity", numeric=True),
        "price": _read_price(row, "price"),
        "exch_order_id": _read_alias(row, "exch_order_id", "exchange_order_id"),
    }
    for field in ("trade_date", "trade_serial_no", "scrip_code", "remarks"):
        value = row.get(field)
        if field == "remarks":
            if value is not None and not isinstance(value, str):
                raise ValueError("remarks must be a string or null")
            result[field] = value
        else:
            result[field] = _read_text(value, field)
    return result


def smart_results(response: Mapping[str, object]) -> list[dict[str, object]]:
    """Retain every linked placement result in order, with separate resources.

    No sibling cancellation, child activation, execution or replay safety is
    inferred from these acknowledgements. A malformed item fails the response
    rather than disappearing from an apparently complete result list.
    """
    response = _mapping(response)
    data = _mapping(response.get("data"))
    items = data.get("order_data")
    if not isinstance(items, list):
        raise ValueError("order_data must be a list")
    results = []
    for item in items:
        item = _mapping(item)
        parent = _read_alias(item, "order_id", "parent_order_id")
        error = item.get("error")
        if error is not None and not isinstance(error, (str, Mapping)):
            raise ValueError("error must be a string, mapping or null")
        if parent is None and error is None:
            raise ValueError("Result has neither parent identity nor error evidence")
        child = item.get("child_order_details")
        child = {} if child is None else _mapping(child)
        results.append(
            {
                "schema_id": SCHEMA_ID,
                "raw": dict(item),
                "parent_order_id": parent,
                "parent_status": _read_alias(item, "order_status", "parent_status"),
                "child_order_id": _read_alias(child, "order_id", "child_order_id"),
                "child_status": _read_alias(child, "order_status", "child_status"),
                "error": dict(error) if isinstance(error, Mapping) else error,
            }
        )
    return results


def project_error(http_status: int, payload: Mapping[str, object]) -> dict[str, object]:
    """Categorise an error without claiming execution outcome or safe replay.

    HTTP 429 takes precedence. Exact error_type determines other categories;
    bare HTTP codes and message substrings do not prove a broker cause.
    """
    if isinstance(http_status, bool) or not isinstance(http_status, int) or not 100 <= http_status <= 599:
        raise ValueError("http_status must be an integer HTTP status")
    payload = _mapping(payload)
    code = _read_text(payload.get("error_type"), "error_type")
    reasons = [_read_text(payload.get(field), field) for field in ("debug_info", "message", "error")]
    category = (
        "RATE_LIMIT"
        if http_status == 429
        else {
            "TokenException": "SESSION_EXPIRED",
            "RequestValidationException": "VALIDATION",
            "GatewayTimeoutException": "TIMEOUT",
        }.get(code, "UNKNOWN")
    )
    return {
        "schema_id": SCHEMA_ID,
        "raw": dict(payload),
        "http_status": http_status,
        "broker_code": code,
        "reason": next((reason for reason in reasons if reason is not None), None),
        "category": category,
        "execution_state": "UNKNOWN",
    }
