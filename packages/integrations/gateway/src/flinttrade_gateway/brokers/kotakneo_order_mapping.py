"""Unwired, current-public Kotak order-parameter dictionaries, checked 2026-10-06.

Evidence: Kotak-Neo/kotak-neo-python docs/functions/orders/{place,modify}_order.md
and docs/guides/MIGRATION.md on public main. This is not a pinned-SDK compatibility
claim or a low-level HTTP body. No client, execution authority or account eligibility
is provided. Tags correlate only; they do not establish idempotency. Lot/tick/freeze,
funds, holdings, session and account checks remain separate integration gates.
"""

from collections.abc import Mapping
from decimal import Decimal, InvalidOperation

SCHEMA_ID = "kotak-public-v3-order-parameters-2026-10-06"

_ACTIONS = {"BUY": "B", "SELL": "S"}
_EXCHANGES = {"NSE": "nse_cm", "BSE": "bse_cm", "NFO": "nse_fo", "BFO": "bse_fo", "MCX": "mcx_fo"}
_TYPES = {"MARKET": "MKT", "LIMIT": "L", "SL": "SL", "SL-M": "SL-M"}
_WIRE_TYPES = {"MKT": "MKT", "L": "L", "SL": "SL", "SL-M": "SL-M"}
_PRODUCTS = {value: value for value in ("MIS", "CNC", "NRML", "MTF")}
_VALIDITIES = {"DAY": "DAY", "IOC": "IOC"}
_VARIETIES = {"regular": "NO", "amo": "YES"}
_COMMON = {"quantity", "price", "trigger_price", "disclosed_quantity", "validity", "variety"}
_PLACE = _COMMON | {"action", "exchange", "pricetype", "product"}
_MODIFY = _PLACE | {"order_type", "amo"}


def _input(value: Mapping[str, object], allowed: set[str]) -> None:
    if not isinstance(value, Mapping):
        raise ValueError("Order input must be a mapping")
    if any(key not in allowed for key in value):
        raise ValueError("Unsupported order field")


def _identifier(value: object, field: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{field} must be a nonblank string")
    return value


def _enum(value: object, choices: dict[str, str], field: str) -> str:
    if not isinstance(value, str) or value not in choices:
        raise ValueError(f"Unsupported {field}")
    return choices[value]


def _number(value: object, field: str, *, integral: bool = False, positive: bool = False) -> str:
    """Render exactly without Decimal context rounding or unbounded expansion.

    Limit effective significant digits and integer width to 64 and fractional
    scale to 16. Redundant trailing zeros do not consume effective precision.
    Strings are bounded before parsing; enormous integer objects fail before str.
    """
    if isinstance(value, bool) or not isinstance(value, (str, int, float, Decimal)):
        raise ValueError(f"{field} must be numeric")
    if isinstance(value, str) and (not value.strip() or len(value) > 256):
        raise ValueError(f"{field} numeric text is blank or too long")
    if isinstance(value, int) and value.bit_length() > 213:
        raise ValueError(f"{field} exceeds 64 digits")
    try:
        number = value if isinstance(value, Decimal) else Decimal(str(value))
    except (InvalidOperation, ValueError):
        raise ValueError(f"{field} must be numeric") from None
    if not number.is_finite() or number < 0 or (positive and number == 0):
        raise ValueError(f"{field} must be finite and {'positive' if positive else 'nonnegative'}")
    if number == 0:
        return "0"
    _, digits, exponent = number.as_tuple()
    # Trim exact coefficient zeros manually: Decimal.normalize() uses ambient precision.
    end = len(digits)
    while end > 1 and digits[end - 1] == 0:
        end -= 1
        exponent += 1
    if end > 64 or end + exponent > 64 or exponent < -16:
        raise ValueError(f"{field} exceeds numeric rendering bounds")
    if integral and exponent < 0:
        raise ValueError(f"{field} must be integral")
    text = format(Decimal((0, digits[:end], exponent)), "f")
    return text.rstrip("0").rstrip(".") if "." in text else text


def _values(order: Mapping[str, object], order_type: str) -> dict[str, object]:
    quantity = _number(order.get("quantity"), "quantity", integral=True, positive=True)
    disclosed = _number(order.get("disclosed_quantity", 0), "disclosed_quantity", integral=True)
    if Decimal(disclosed) > Decimal(quantity):
        raise ValueError("disclosed_quantity cannot exceed quantity")
    return {
        "order_type": order_type,
        "price": _number(order.get("price", 0), "price", positive=order_type in {"L", "SL"}),
        "quantity": quantity,
        "validity": _enum(order.get("validity", "DAY"), _VALIDITIES, "validity"),
        "trigger_price": _number(order.get("trigger_price", 0), "trigger_price", positive=order_type in {"SL", "SL-M"}),
        "disclosed_quantity": disclosed,
    }


def _validity_for_segment(segment: str | None, validity: object) -> None:
    if segment == "mcx_fo" and validity == "IOC":
        raise ValueError("MCX supports DAY only")


def place_parameters(order: Mapping[str, object], *, trading_symbol: str, tag: str | None = None) -> dict[str, object]:
    """Translate explicit canonical intent into the dated public place parameters."""
    _input(order, _PLACE)
    segment = _enum(order.get("exchange"), _EXCHANGES, "exchange")
    result = _values(order, _enum(order.get("pricetype"), _TYPES, "pricetype"))
    _validity_for_segment(segment, result["validity"])
    result.update(
        {
            "exchange_segment": segment,
            "product": _enum(order.get("product"), _PRODUCTS, "product"),
            "trading_symbol": _identifier(trading_symbol, "trading_symbol"),
            "transaction_type": _enum(order.get("action"), _ACTIONS, "action"),
            "amo": _enum(order.get("variety", "regular"), _VARIETIES, "variety"),
        }
    )
    if tag is not None:
        result["tag"] = _identifier(tag, "tag")
    return result


def modify_parameters(order_id: str, changes: Mapping[str, object]) -> dict[str, object]:
    """Build a full explicit parameter set, never fetching existing order values.

    pricetype accepts canonical intent; order_type accepts canonical or wire codes.
    Context exchange/product/action is validated but never forwarded. Known MCX
    context conservatively restricts validity even though public modify has no
    segment parameter. Absent AMO intent stays absent from this dictionary.
    """
    _identifier(order_id, "order_id")
    _input(changes, _MODIFY)
    types = []
    if "pricetype" in changes:
        types.append(_enum(changes["pricetype"], _TYPES, "pricetype"))
    if "order_type" in changes:
        types.append(_enum(changes["order_type"], _TYPES | _WIRE_TYPES, "order_type"))
    if not types or len(set(types)) != 1:
        raise ValueError("Explicit unambiguous order type is required")
    segment = None
    if "exchange" in changes:
        segment = _enum(changes["exchange"], _EXCHANGES, "exchange")
    if "product" in changes:
        _enum(changes["product"], _PRODUCTS, "product")
    if "action" in changes:
        _enum(changes["action"], _ACTIONS, "action")
    result = {"order_id": order_id, **_values(changes, types[0])}
    _validity_for_segment(segment, result["validity"])
    amo = []
    if "variety" in changes:
        amo.append(_enum(changes["variety"], _VARIETIES, "variety"))
    if "amo" in changes:
        amo.append(_enum(changes["amo"], {"YES": "YES", "NO": "NO"}, "amo"))
    if len(set(amo)) > 1:
        raise ValueError("Conflicting AMO intent")
    if amo:
        result["amo"] = amo[0]
    return result


# Observation vocabulary is deliberately independent of outbound eligibility.
# Sources: public docs/functions/orders/{order_report,order_history,trade_report}.md
# on 2026-10-06. No execution/position authority follows from these projections.
_STATES = {
    "COMPLETE": "FILLED",
    "TRADED": "FILLED",
    "CANCELLED": "CANCELLED",
    "REJECTED": "REJECTED",
    "OPEN": "WORKING",
    "CANCEL_PENDING": "CANCEL_PENDING",
    "CANCEL_REQUESTED": "CANCEL_PENDING",
}
_OBSERVATION_TEXT = {
    "broker_product": ("prod", "broker_product"),
    "trading_symbol": ("trdSym", "trading_symbol"),
    "symbol": ("sym", "symbol"),
    "exchange_segment": ("exSeg", "exchange_segment"),
    "transaction_type": ("trnsTp", "transaction_type"),
    "order_type": ("prcTp", "order_type"),
    "rejection_reason": ("rejRsn", "rejection_reason"),
    "exchange_order_id": ("exchOrdId", "exOrdId", "exchange_order_id"),
    "gui_order_id": ("GuiOrdId", "gui_order_id"),
    "validity": ("vldt", "ordDur", "validity"),
}


def attempt_state(status: object) -> str:
    """Classify only exact status tokens; no substring or position inference."""
    return _STATES.get(status.strip().upper(), "UNKNOWN") if isinstance(status, str) else "UNKNOWN"


def _populated(value: object) -> bool:
    return value is not None and not (isinstance(value, str) and not value.strip())


def _observation_alias(
    row: Mapping[str, object],
    names: tuple[str, ...],
    *,
    numeric: bool = False,
    integral: bool = False,
    status: bool = False,
) -> object:
    """Validate true synonyms, returning the first populated value.

    Numeric aliases compare exact normalised values; statuses compare trim/case
    only, rather than comparing classifications (two UNKNOWNs can conflict).
    """
    values = []
    comparisons = []
    for name in names:
        value = row.get(name)
        if not _populated(value):
            continue
        if numeric:
            value = _number(value, name, integral=integral)
        elif not status:
            value = _identifier(value, name)
        values.append(value)
        comparisons.append(value.strip().upper() if status and isinstance(value, str) else value)
    if comparisons and any(value != comparisons[0] for value in comparisons[1:]):
        raise ValueError(f"Conflicting aliases: {', '.join(names)}")
    return values[0] if values else None


def _observation_base(row: Mapping[str, object]) -> dict[str, object]:
    if not isinstance(row, Mapping) or any(not isinstance(key, str) for key in row):
        raise ValueError("Observation must be a string-keyed mapping")
    if any(_populated(row.get(key)) for key in ("error", "Error", "Error Message")):
        raise ValueError("Observation error row")
    orderid = _observation_alias(row, ("nOrdNo", "orderid"))
    if orderid is None:
        raise ValueError("Observation requires an order ID")
    result = {"schema_id": SCHEMA_ID, "raw": dict(row), "orderid": orderid}
    for target, names in _OBSERVATION_TEXT.items():
        value = _observation_alias(row, names)
        if value is not None:
            result[target] = value
    return result


def _observation_time(row: Mapping[str, object], names: tuple[str, ...]) -> object:
    # These denote different events, not synonyms. Preserve all original values
    # in raw, choose documented precedence, and do not invent timezone/precision.
    values = [_identifier(row[name], name) for name in names if _populated(row.get(name))]
    return values[0] if values else None


def project_order(row: Mapping[str, object]) -> dict[str, object]:
    """Project order evidence; cancelled/rejected orders may retain partial fills.

    Missing/null/blank optional numbers remain absent. Explicit numeric zero is
    retained. Decimal strings avoid float precision loss. Raw is a shallow copy;
    this is neither authenticated provenance nor an account-scoped read book.
    """
    result = _observation_base(row)
    for target, names, integral in (
        ("quantity", ("qty", "quantity"), True),
        ("filled_quantity", ("fldQty", "filled_quantity"), True),
        ("price", ("prc", "price"), False),
        ("trigger_price", ("trgPrc", "trigger_price"), False),
        ("average_price", ("avgPrc", "average_price"), False),
    ):
        value = _observation_alias(row, names, numeric=True, integral=integral)
        if value is not None:
            result[target] = value
    quantity = result.get("quantity")
    filled_quantity = result.get("filled_quantity")
    if quantity is not None and filled_quantity is not None and Decimal(str(filled_quantity)) > Decimal(str(quantity)):
        raise ValueError("filled_quantity cannot exceed quantity")
    status = _observation_alias(row, ("ordSt", "stat", "status"), status=True)
    if status is not None:
        result["status"] = status
    result["attempt_state"] = attempt_state(status)
    timestamp = _observation_time(row, ("ordDtTm", "ordEntTm", "flDtTm", "exTm", "exchTmstp"))
    if timestamp is not None:
        result["timestamp"] = timestamp
    return result


def project_trade(row: Mapping[str, object]) -> dict[str, object]:
    """Project one trade row without fabricating identity or deduplicating.

    Public trade examples contain fldQty=1 and qty=0: validate both independently,
    prefer the filled quantity, use qty only when absent. avgPrc/flPrc likewise
    represent average versus execution price, not synonyms. Preserve both in raw.
    An order ID, exchange order ID or timestamp is never promoted to a fill ID.
    """
    result = _observation_base(row)
    for target, names, integral in (
        ("quantity", ("fldQty", "qty"), True),
        ("price", ("avgPrc", "flPrc"), False),
    ):
        values = [_number(row[name], name, integral=integral) for name in names if _populated(row.get(name))]
        if values:
            result[target] = values[0]
    # Broker placeholders are evidence, not usable fill identifiers.
    identities = {
        key: value
        for key, value in row.items()
        if key in {"flId", "fill_id"} and not (isinstance(value, str) and value.strip().upper() in {"NA", "--"})
    }
    fill_id = _observation_alias(identities, ("flId", "fill_id"))
    if fill_id is not None:
        result["fill_id"] = fill_id
    timestamp = _observation_time(row, ("flDtTm", "exTm"))
    if timestamp is not None:
        result["timestamp"] = timestamp
    return result


def _history_envelope(response: Mapping[str, object]) -> None:
    if not isinstance(response, Mapping) or any(not isinstance(key, str) for key in response):
        raise ValueError("History envelope must be a string-keyed mapping")
    if any(_populated(response.get(key)) for key in ("error", "Error", "Error Message")):
        raise ValueError("History error envelope")
    if "stat" in response and (not isinstance(response["stat"], str) or response["stat"].strip().upper() != "OK"):
        raise ValueError("History envelope is not successful")
    for key in ("stCode", "status_code"):
        if key in response and (type(response[key]) is not int or response[key] != 200):
            raise ValueError("History envelope has unsuccessful or malformed code")


def history_rows(response: Mapping[str, object]) -> list[dict[str, object]]:
    """Unwrap direct or once-nested data lists; never turn malformed/error into [].

    Validate each row before returning any rows; preserve order and duplicates.
    Success envelopes and empty lists do not certify completeness or flatness.
    """
    _history_envelope(response)
    rows = response.get("data")
    if isinstance(rows, Mapping):
        _history_envelope(rows)
        rows = rows.get("data")
    if not isinstance(rows, list):
        raise ValueError("History data must be a list")
    result = []
    for row in rows:
        project_order(row)
        result.append(dict(row))
    return result


def project_write_result(response: Mapping[str, object], *, expected_order_id: str | None = None) -> dict[str, object]:
    """Retain write acknowledgement evidence without inferring execution.

    Public place/modify/cancel docs show a flat stat/nOrdNo/stCode ACK and
    stCode=1021/status_code=400 rejection. Only a complete native ACK establishes
    acceptance; explicit rejection takes precedence. Other transport/code/status
    outcomes remain unknown, never permission to replay. Identity comparisons are
    exact; expected identity validates evidence but cannot supply a missing ID.
    Raw is a shallow copy, not authenticated or account-scoped provenance.
    """
    if not isinstance(response, Mapping) or any(not isinstance(key, str) for key in response):
        raise ValueError("Write response must be a string-keyed mapping")
    if expected_order_id is not None:
        _identifier(expected_order_id, "expected_order_id")
    identities = [_identifier(response[key], key) for key in ("nOrdNo", "order_id", "orderid") if key in response]
    if identities and any(value != identities[0] for value in identities[1:]):
        raise ValueError("Conflicting write order identities")
    order_id = identities[0] if identities else None
    if order_id is not None and expected_order_id is not None and order_id != expected_order_id:
        raise ValueError("Write order identity does not match expected_order_id")

    stat = response.get("stat")
    status = stat.strip().upper() if isinstance(stat, str) else None
    code = response.get("stCode")
    http_code = response.get("status_code")
    error = any(_populated(response.get(key)) for key in ("Error", "Error Message", "error"))
    rejected = (
        error
        or status == "NOT_OK"
        or (type(code) is int and code == 1021)
        or (type(http_code) is int and http_code == 400)
    )
    accepted = None
    if rejected:
        accepted = False
    elif (
        status == "OK"
        and type(code) is int
        and code == 200
        and "nOrdNo" in response
        and not _populated(response.get("errMsg"))
        and ("status_code" not in response or (type(http_code) is int and http_code == 200))
    ):
        accepted = True
    reason = next(
        (
            response[key]
            for key in ("errMsg", "Error Message", "Error", "error", "reason")
            if _populated(response.get(key))
        ),
        None,
    )
    return {
        "schema_id": SCHEMA_ID,
        "raw": dict(response),
        "order_id": order_id,
        "accepted": accepted,
        "broker_code": code if "stCode" in response else http_code,
        "reason": reason,
        "execution_state": "UNKNOWN",
    }
