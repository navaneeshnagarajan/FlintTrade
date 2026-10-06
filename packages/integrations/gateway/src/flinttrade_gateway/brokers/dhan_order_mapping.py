"""Standalone Dhan Forever REST wire contracts, deliberately not integrated.

Based on https://dhanhq.co/docs/v2/forever/ (checked 2026-10-06).
Inputs use native REST camelCase names, not SDK spellings. These helpers do
not establish account ownership, instrument eligibility, broker readiness,
fill evidence or position closure. Existing adapters do not call them.
"""

import re
from collections.abc import Mapping
from copy import deepcopy
from math import isfinite

_CREATE_REQUIRED = frozenset(
    {
        "dhanClientId",
        "securityId",
        "transactionType",
        "exchangeSegment",
        "productType",
        "orderType",
        "orderFlag",
        "quantity",
        "price",
        "triggerPrice",
        "validity",
    }
)
_SECOND_LEG = frozenset({"quantity1", "price1", "triggerPrice1"})
_CREATE_OPTIONAL = frozenset({"correlationId", "disclosedQuantity"}) | _SECOND_LEG
_MODIFY_REQUIRED = frozenset(
    {
        "dhanClientId",
        "orderType",
        "orderFlag",
        "legName",
        "quantity",
        "price",
        "triggerPrice",
        "disclosedQuantity",
        "validity",
    }
)
_FAMILIES = frozenset({"SINGLE", "OCO"})
_EXECUTION_TYPES = frozenset({"LIMIT", "MARKET", "STOP_LOSS", "STOP_LOSS_MARKET"})


def _mapping(fields: Mapping[str, object]) -> dict[str, object]:
    if not isinstance(fields, Mapping):
        raise ValueError("Expected a mapping of native REST fields")
    return dict(fields)


def _request(fields: Mapping[str, object], required: frozenset[str], optional: frozenset[str]) -> dict[str, object]:
    result = _mapping(fields)
    if required - result.keys():
        raise ValueError("Missing required native REST fields")
    if result.keys() - (required | optional):
        raise ValueError("Unknown native REST request fields")
    return result


def _identifier(value: object, name: str) -> None:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{name} must be a nonempty string")


def _enum(value: object, allowed: frozenset[str], name: str) -> None:
    if not isinstance(value, str) or value not in allowed:
        raise ValueError(f"Unsupported {name}")


def _quantity(value: object, name: str, *, zero_allowed: bool = False) -> int:
    if isinstance(value, str) and re.fullmatch(r"[0-9]+", value):
        value = int(value)
    if type(value) is not int or value < (0 if zero_allowed else 1):
        raise ValueError(f"{name} must be an exact {'nonnegative' if zero_allowed else 'positive'} integer")
    return value


def _price(value: object, name: str, *, positive: bool = False) -> None:
    if type(value) not in (int, float) or (type(value) is float and not isfinite(value)):
        raise ValueError(f"{name} must be a finite built-in number")
    if value < 0 or (positive and value == 0):
        raise ValueError(f"{name} must be {'positive' if positive else 'nonnegative'}")


def _common_request(result: dict[str, object], types: frozenset[str]) -> None:
    _identifier(result["dhanClientId"], "dhanClientId")
    _enum(result["orderFlag"], _FAMILIES, "orderFlag")
    _enum(result["orderType"], types, "orderType")
    _enum(result["validity"], frozenset({"DAY", "IOC"}), "validity")
    result["quantity"] = _quantity(result["quantity"], "quantity")
    _price(result["price"], "price")
    _price(result["triggerPrice"], "triggerPrice", positive=True)
    if "disclosedQuantity" in result:
        result["disclosedQuantity"] = _quantity(result["disclosedQuantity"], "disclosedQuantity", zero_allowed=True)


def forever_create_payload(fields: Mapping[str, object]) -> dict[str, object]:
    """Validate a SINGLE/OCO creation body without changing the input.

    All plan-required native fields must be explicit. OCO requires its whole
    second leg; SINGLE rejects second-leg fields rather than silently dropping
    them. Segment eligibility, disclosed-quantity ratios and market/limit price
    rules beyond finite nonnegative prices remain external checks.
    """
    result = _request(fields, _CREATE_REQUIRED, _CREATE_OPTIONAL)
    _common_request(result, frozenset({"LIMIT", "MARKET"}))
    for name in ("securityId", "exchangeSegment"):
        _identifier(result[name], name)
    if "correlationId" in result:
        _identifier(result["correlationId"], "correlationId")
    _enum(result["transactionType"], frozenset({"BUY", "SELL"}), "transactionType")
    _enum(result["productType"], frozenset({"CNC", "MTF"}), "productType")
    supplied_leg = result.keys() & _SECOND_LEG
    if result["orderFlag"] == "OCO":
        if supplied_leg != _SECOND_LEG:
            raise ValueError("OCO requires quantity1, price1 and triggerPrice1")
        result["quantity1"] = _quantity(result["quantity1"], "quantity1")
        _price(result["price1"], "price1", positive=True)
        _price(result["triggerPrice1"], "triggerPrice1", positive=True)
    elif supplied_leg:
        raise ValueError("Second-leg fields require orderFlag OCO")
    return result


def forever_modify_payload(order_id: str, changes: Mapping[str, object]) -> dict[str, object]:
    """Validate a complete modification body, binding its orderId exactly.

    Account ownership and the order's actual family/state are external checks.
    disclosedQuantity is explicit under this companion's complete-body contract.
    """
    _identifier(order_id, "order_id")
    result = _request(changes, _MODIFY_REQUIRED, frozenset({"orderId"}))
    if "orderId" in result and result["orderId"] != order_id:
        raise ValueError("orderId conflicts with the bound order_id")
    _common_request(result, _EXECUTION_TYPES)
    _enum(result["legName"], frozenset({"TARGET_LEG", "STOP_LOSS_LEG"}), "legName")
    if result["legName"] == "STOP_LOSS_LEG" and result["orderFlag"] != "OCO":
        raise ValueError("STOP_LOSS_LEG requires orderFlag OCO")
    result["orderId"] = order_id
    return result


def project_forever(row: Mapping[str, object]) -> dict[str, object]:
    """Copy native observations and add only evidenced family/type aliases.

    Native keys, unknown products/segments/statuses and nullable evidence are
    retained unchanged. source_fields is an independent deep copy of the whole
    native row. It is not a request body or eligibility decision. Historical
    SINGLE/OCO orderType values identify family, so pricetype is empty for those
    values. Missing orderType/orderFlag, fills, validity, children and closure
    evidence are never defaulted. No native numeric evidence is coerced.
    """
    native = _mapping(row)
    result = deepcopy(native)
    result["source_fields"] = deepcopy(native)
    order_type = native.get("orderType")
    family_type = isinstance(order_type, str) and order_type in _FAMILIES
    if "orderFlag" in native:
        if family_type and native["orderFlag"] != order_type:
            raise ValueError("Conflicting Forever orderFlag and family orderType")
        result["order_flag"] = deepcopy(native["orderFlag"])
    elif family_type:
        result["order_flag"] = order_type
    if "orderType" in native:
        result["pricetype"] = "" if family_type else deepcopy(order_type)
    return result


_SUPER_LEG_FIELDS = {
    "ENTRY_LEG": frozenset({"orderType", "quantity", "price", "targetPrice", "stopLossPrice", "trailingJump"}),
    "TARGET_LEG": frozenset({"targetPrice"}),
    "STOP_LOSS_LEG": frozenset({"stopLossPrice", "trailingJump"}),
}
_SUPER_NUMERIC_EVIDENCE = frozenset(
    {
        "quantity", "remainingQuantity", "filledQty", "totalQuatity", "triggeredQuantity",
        "price", "ltp", "averageTradedPrice", "targetPrice", "stopLossPrice", "trailingJump",
    }
)


def super_modify_payload(order_id: str, changes: Mapping[str, object]) -> dict[str, object]:
    """Validate a leg-specific Super REST modification without defaulting intent.

    Based on https://dhanhq.co/docs/v2/super-order/ (checked 2026-10-06).
    ENTRY accepts LIMIT/MARKET; TARGET edits only targetPrice. ENTRY and
    STOP_LOSS require explicit trailingJump: zero intentionally cancels trailing,
    while omission is rejected because the native API also cancels on omission.
    State eligibility, account ownership and side-dependent price relationships
    remain external; this body contains no authoritative side or current state.
    """
    _identifier(order_id, "order_id")
    native = _mapping(changes)
    _enum(native.get("legName"), frozenset(_SUPER_LEG_FIELDS), "legName")
    required = _SUPER_LEG_FIELDS[native["legName"]] | {"dhanClientId", "legName"}
    result = _request(native, required, frozenset({"orderId"}))
    _identifier(result["dhanClientId"], "dhanClientId")
    if "orderId" in result and result["orderId"] != order_id:
        raise ValueError("orderId conflicts with the bound order_id")
    if result["legName"] == "ENTRY_LEG":
        _enum(result["orderType"], frozenset({"LIMIT", "MARKET"}), "orderType")
        result["quantity"] = _quantity(result["quantity"], "quantity")
        _price(result["price"], "price")
    for name in ("targetPrice", "stopLossPrice"):
        if name in result:
            _price(result[name], name, positive=True)
    if "trailingJump" in result:
        _price(result["trailingJump"], "trailingJump")
    result["orderId"] = order_id
    return result


def _super_numeric_evidence(row: Mapping[str, object]) -> None:
    for name in row.keys() & _SUPER_NUMERIC_EVIDENCE:
        value = row[name]
        if type(value) not in (int, float) or (type(value) is float and not isfinite(value)):
            raise ValueError(f"{name} evidence must be a finite built-in number")


def project_super(row: Mapping[str, object]) -> dict[str, object]:
    """Copy Super observations without deriving fills, terminality or closure.

    Preserve native names, including documented totalQuatity, raw statuses and
    same-ID/different-leg records in their original order. Validate supplied
    finite numeric evidence at parent and native legDetails levels, without
    request eligibility, sign/integrality checks or numeric coercion. A present
    legDetails must be an array of mappings; absent evidence stays absent.
    source_fields independently copies the whole input, including extensions.
    This projection cannot establish coherent books or safe execution amounts.
    """
    native = _mapping(row)
    _super_numeric_evidence(native)
    if "legDetails" in native:
        legs = native["legDetails"]
        if not isinstance(legs, list):
            raise ValueError("legDetails must be an array of native leg mappings")
        native["legDetails"] = [_mapping(leg) for leg in legs]
        for leg in native["legDetails"]:
            _super_numeric_evidence(leg)
    result = deepcopy(native)
    result["source_fields"] = deepcopy(native)
    return result


_NORMAL_REQUIRED = frozenset(
    {
        "dhanClientId", "securityId", "exchangeSegment", "transactionType", "productType",
        "orderType", "validity", "quantity", "price",
    }
)
_NORMAL_OPTIONAL = frozenset(
    {
        "correlationId", "disclosedQuantity", "triggerPrice", "afterMarketOrder",
        "amoTime", "boProfitValue", "boStopLossValue",
    }
)
_STOP_TYPES = frozenset({"STOP_LOSS", "STOP_LOSS_MARKET"})
_AMO_TIMES = frozenset({"PRE_OPEN", "OPEN", "OPEN_30", "OPEN_60"})


def normal_order_payload(fields: Mapping[str, object]) -> dict[str, object]:
    """Validate explicit normal/AMO REST fields without choosing an endpoint.

    Based on https://dhanhq.co/docs/v2/orders/ (checked 2026-10-06).
    Quantities are exact integers; stop types require a positive triggerPrice.
    afterMarketOrder, when supplied, must be bool; true requires explicit
    amoTime. Any supplied timing is validated and retained even without true.
    BO offsets retain finite signed numeric values as supplied: product-specific
    requirements and economic eligibility remain external. No optional values,
    children, slice outcomes, fills or closure evidence are synthesized.
    This body may describe a slicing request, but does not select that route.
    """
    result = _request(fields, _NORMAL_REQUIRED, _NORMAL_OPTIONAL)
    for name in ("dhanClientId", "securityId", "exchangeSegment"):
        _identifier(result[name], name)
    if "correlationId" in result:
        _identifier(result["correlationId"], "correlationId")
    _enum(result["transactionType"], frozenset({"BUY", "SELL"}), "transactionType")
    _enum(result["productType"], frozenset({"CNC", "INTRADAY", "MARGIN", "MTF", "CO", "BO"}), "productType")
    _enum(result["orderType"], _EXECUTION_TYPES, "orderType")
    _enum(result["validity"], frozenset({"DAY", "IOC"}), "validity")
    result["quantity"] = _quantity(result["quantity"], "quantity")
    if "disclosedQuantity" in result:
        result["disclosedQuantity"] = _quantity(result["disclosedQuantity"], "disclosedQuantity", zero_allowed=True)
    _price(result["price"], "price")
    stop_type = result["orderType"] in _STOP_TYPES
    if stop_type and "triggerPrice" not in result:
        raise ValueError("Stop orders require triggerPrice")
    if "triggerPrice" in result:
        _price(result["triggerPrice"], "triggerPrice", positive=stop_type)
    for name in ("boProfitValue", "boStopLossValue"):
        if name in result:
            value = result[name]
            if type(value) not in (int, float) or (type(value) is float and not isfinite(value)):
                raise ValueError(f"{name} must be a finite built-in number")
    if "afterMarketOrder" in result and type(result["afterMarketOrder"]) is not bool:
        raise ValueError("afterMarketOrder must be a boolean")
    if result.get("afterMarketOrder") is True and "amoTime" not in result:
        raise ValueError("After-market orders require explicit amoTime")
    if "amoTime" in result:
        _enum(result["amoTime"], _AMO_TIMES, "amoTime")
    return result
