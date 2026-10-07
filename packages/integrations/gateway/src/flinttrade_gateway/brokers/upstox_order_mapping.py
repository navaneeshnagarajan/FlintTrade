"""Standalone Upstox native wire contracts; no runtime or SDK authority.

These helpers retain requested intent only. Upstox may ignore is_amo and infer
it from the session; protection is ignored for LIMIT/SL. Correlation IDs identify
request-local lines, not idempotent submissions. No broker eligibility is proved.
"""

from collections.abc import Mapping, Sequence
from copy import deepcopy
from math import isfinite

_REQUIRED = frozenset({
    "quantity", "product", "validity", "price", "instrument_token", "order_type",
    "transaction_type", "disclosed_quantity", "trigger_price",
})
_OPTIONAL = frozenset({"tag", "is_amo", "slice", "market_protection"})
_ENUMS = {
    "product": frozenset({"I", "D", "MTF"}),
    "validity": frozenset({"DAY", "IOC"}),
    "order_type": frozenset({"MARKET", "LIMIT", "SL", "SL-M"}),
    "transaction_type": frozenset({"BUY", "SELL"}),
}


def _whole_quantity(value: object, field: str, minimum: int) -> int:
    if type(value) is str and value and value.isascii() and value.isdecimal():
        value = int(value)
    if type(value) is not int or value < minimum:
        raise ValueError(f"{field} must be an exact integer >= {minimum}")
    return value


def _identifier(value: object, field: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{field} must be a nonempty string")
    return value


def v3_order_payload(fields: Mapping[str, object]) -> dict[str, object]:
    """Validate native placement fields without defaults or order conversion.

    Numeric validation preserves finite signed prices and exact quantities; it
    does not establish tick/lot/freeze limits, int32 bounds or price eligibility.
    """
    if not isinstance(fields, Mapping):
        raise ValueError("order fields must be a mapping")
    payload = dict(fields)
    if not _REQUIRED <= payload.keys() or payload.keys() - (_REQUIRED | _OPTIONAL):
        raise ValueError("missing required or unknown order fields")
    for field, allowed in _ENUMS.items():
        value = payload[field]
        if not isinstance(value, str) or value not in allowed:
            raise ValueError(f"invalid {field}")
    _identifier(payload["instrument_token"], "instrument_token")
    payload["quantity"] = _whole_quantity(payload["quantity"], "quantity", 1)
    payload["disclosed_quantity"] = _whole_quantity(payload["disclosed_quantity"], "disclosed_quantity", 0)
    for field in ("price", "trigger_price"):
        value = payload[field]
        if type(value) not in (int, float) or (type(value) is float and not isfinite(value)):
            raise ValueError(f"{field} must be a finite built-in number")
    for field in ("is_amo", "slice"):
        if field in payload and type(payload[field]) is not bool:
            raise ValueError(f"{field} must be a boolean")
    if "tag" in payload:
        tag = payload["tag"]
        if not isinstance(tag, str) or len(tag) > 40:
            raise ValueError("tag must be a string of at most 40 characters")
    if "market_protection" in payload:
        protection = payload["market_protection"]
        if type(protection) is not int or not -1 <= protection <= 25:
            raise ValueError("market_protection must be an integer from -1 through 25")
    return payload


def multi_order_payloads(items: Sequence[Mapping[str, object]]) -> list[dict[str, object]]:
    """Retain one to ten ordered request lines with unique local correlations.

    Slice-child counts and actual broker execution ordering are not inferred.
    Correlations are never generated and do not authorise retries.
    """
    if not isinstance(items, Sequence) or isinstance(items, (str, bytes, bytearray)) or not 1 <= len(items) <= 10:
        raise ValueError("multi order requires a sequence of one to ten mappings")
    payloads = []
    seen = set()
    for item in items:
        if not isinstance(item, Mapping):
            raise ValueError("each order line must be a mapping")
        fields = dict(item)
        correlation = _identifier(fields.pop("correlation_id", None), "correlation_id")
        if len(correlation) > 20 or correlation in seen:
            raise ValueError("correlation_id must be unique within the request and at most 20 characters")
        seen.add(correlation)
        payload = v3_order_payload(fields)
        payload["correlation_id"] = correlation
        payloads.append(payload)
    return payloads


def _finite_number(value: object, field: str, minimum: int = 0, *, positive: bool = False) -> None:
    if (type(value) not in (int, float) or (type(value) is float and not isfinite(value))
            or value < minimum or (positive and value == minimum)):
        raise ValueError(f"{field} must be a finite {'positive' if positive else 'nonnegative'} built-in number")


def _protection(value: object) -> None:
    if type(value) is not int or not -1 <= value <= 25:
        raise ValueError("market_protection must be an integer from -1 through 25")


def _rule_rows(value: object) -> list[dict[str, object]]:
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes, bytearray)):
        raise ValueError("rules must be a sequence of mappings")
    rows = []
    seen = set()
    for item in value:
        if not isinstance(item, Mapping):
            raise ValueError("each rule must be a mapping")
        row = dict(item)
        strategy = _identifier(row.get("strategy"), "strategy")
        if strategy in seen:
            raise ValueError("duplicate rule strategy")
        seen.add(strategy)
        rows.append(row)
    return rows


def _gtt_request(fields: Mapping[str, object], *, create: bool) -> dict[str, object]:
    if not isinstance(fields, Mapping):
        raise ValueError("GTT fields must be a mapping")
    required = {"type", "quantity", "rules"}
    if create:
        required |= {"product", "instrument_token", "transaction_type"}
    payload = dict(fields)
    if payload.keys() != required:
        raise ValueError("missing required or unknown GTT fields")
    kind = payload["type"]
    if not isinstance(kind, str) or kind not in ("SINGLE", "MULTIPLE"):
        raise ValueError("invalid GTT type")
    payload["quantity"] = _whole_quantity(payload["quantity"], "quantity", 1)
    if create:
        _identifier(payload["instrument_token"], "instrument_token")
        for field in ("product", "transaction_type"):
            value = payload[field]
            if not isinstance(value, str) or value not in _ENUMS[field]:
                raise ValueError(f"invalid {field}")
    rows = _rule_rows(payload["rules"])
    strategies = {row["strategy"] for row in rows}
    if ("ENTRY" not in strategies or strategies - {"ENTRY", "STOPLOSS", "TARGET"}
            or (kind == "SINGLE" and len(rows) != 1) or (kind == "MULTIPLE" and not 2 <= len(rows) <= 3)):
        raise ValueError("invalid GTT rule composition")
    required_rule = {"strategy", "trigger_type", "trigger_price"}
    optional = {"trailing_gap", "market_protection"}
    for row in rows:
        if not required_rule <= row.keys() or row.keys() - (required_rule | optional):
            raise ValueError("missing required or unknown GTT rule fields")
        trigger = row["trigger_type"]
        allowed = ("ABOVE", "BELOW", "IMMEDIATE") if row["strategy"] == "ENTRY" else ("IMMEDIATE",)
        if not isinstance(trigger, str) or trigger not in allowed:
            raise ValueError("invalid rule trigger_type")
        _finite_number(row["trigger_price"], "trigger_price", positive=True)
        if "trailing_gap" in row:
            if row["strategy"] != "STOPLOSS":
                raise ValueError("trailing_gap is documented only for STOPLOSS")
            _finite_number(row["trailing_gap"], "trailing_gap", positive=True)
        if "market_protection" in row:
            _protection(row["market_protection"])
    payload["rules"] = rows
    return payload


def gtt_create_payload(fields: Mapping[str, object]) -> dict[str, object]:
    """Validate creation intent, preserving independent optional rule protection.

    No LTP-dependent trailing minimum, lot/tick or account eligibility is proved.
    """
    return _gtt_request(fields, create=True)


def gtt_modify_payload(gtt_order_id: str, changes: Mapping[str, object]) -> dict[str, object]:
    """Require a complete replacement, preserving explicit pinned SDK rule fields.

    The 2.30.0 SDK's shared GttRule serialises market_protection on modification,
    although the web modification table omits it. Server acceptance and effective
    protection remain unverified; this helper only preserves requested intent.
    Current OPEN-state quantity/trigger restrictions require separate fresh
    evidence. This helper neither merges existing rules nor infers positions.

    Args:
        gtt_order_id: Explicit broker resource identity; not an idempotency token.
        changes: Complete replacement containing type, quantity and every rule.
            Creation-only top-level fields are refused. Optional per-rule
            market_protection is validated and retained without supplying a default.

    Returns:
        Detached replacement payload with the supplied gtt_order_id.

    Raises:
        ValueError: The identity, replacement shape or rule fields are invalid.
    """
    identifier = _identifier(gtt_order_id, "gtt_order_id")
    return {**_gtt_request(changes, create=False), "gtt_order_id": identifier}


def project_gtt(row: Mapping[str, object]) -> dict[str, object]:
    """Copy one native resource, keeping rule/resource status and fills distinct.

    This takes a data row, not a response envelope. Unknown read evidence is
    retained without asserting request eligibility. A child ID or COMPLETED
    trigger is not a fill or evidence that a child exchange order is terminal.
    """
    if not isinstance(row, Mapping):
        raise ValueError("GTT resource must be a mapping")
    _identifier(row.get("gtt_order_id"), "gtt_order_id")
    _identifier(row.get("instrument_token"), "instrument_token")
    rules = _rule_rows(row.get("rules"))
    result = deepcopy(dict(row))
    for field in ("entry_status", "resource_status", "source_fields"):
        result.pop(field, None)
    for field in ("quantity", "filled_quantity", "pending_quantity"):
        if field in result:
            result[field] = _whole_quantity(result[field], field, 0)
    for field in ("created_at", "expires_at"):
        if field in result and (type(result[field]) is not int or result[field] < 0):
            raise ValueError(f"{field} must be a nonnegative integer timestamp")
    for field in ("average_price", "price", "trigger_price", "trailing_gap"):
        if field in result:
            _finite_number(result[field], field)
    for rule in rules:
        for field in ("trigger_price", "trailing_gap", "average_price", "price"):
            if field in rule:
                _finite_number(rule[field], field)
        for field in ("quantity", "filled_quantity", "pending_quantity"):
            if field in rule:
                rule[field] = _whole_quantity(rule[field], field, 0)
        if "market_protection" in rule:
            _protection(rule["market_protection"])
        if "order_id" in rule and rule["order_id"] is not None:
            _identifier(rule["order_id"], "order_id")
        if rule["strategy"] == "ENTRY" and "status" in rule:
            result["entry_status"] = deepcopy(rule["status"])
    result["rules"] = deepcopy(rules)
    if "status" in row:
        result["resource_status"] = deepcopy(row["status"])
    result["source_fields"] = deepcopy(dict(row))
    return result


def _result_sequence(value: object, field: str) -> Sequence:
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes, bytearray)):
        raise ValueError(f"{field} must be a sequence")
    return value


def _batch_envelope(response: Mapping[str, object]) -> dict[str, object]:
    if not isinstance(response, Mapping):
        raise ValueError("response must be a mapping")
    status = response.get("status")
    if not isinstance(status, str) or status not in ("success", "partial_success", "error"):
        raise ValueError("unknown response status")
    errors = response.get("errors")
    if errors is not None:
        for error in _result_sequence(errors, "errors"):
            if not isinstance(error, Mapping) or not error:
                raise ValueError("each error must be a nonempty mapping")
            for field in ("order_id", "correlation_id", "instrument_key"):
                if field in error and error[field] is not None:
                    _identifier(error[field], field)
    if (status == "success" and errors) or (status != "success" and not errors):
        raise ValueError("errors contradict response status")
    summary = response.get("summary", {})
    if not isinstance(summary, Mapping):
        raise ValueError("summary must be a mapping")
    for field in ("total", "success", "error", "payload_error"):
        if field in summary and (type(summary[field]) is not int or summary[field] < 0):
            raise ValueError(f"summary.{field} must be a nonnegative integer")
    if "total" in summary:
        for field in ("success", "error", "payload_error"):
            if field in summary and summary[field] > summary["total"]:
                raise ValueError("summary count exceeds total")
    if status == "success" and (summary.get("error", 0) or summary.get("payload_error", 0)):
        raise ValueError("success summary contains errors")
    if status == "error" and summary.get("success", 0):
        raise ValueError("error summary contains successes")
    if status != "error" and "success" in summary and not summary["success"]:
        raise ValueError("successful response has zero summary successes")
    if status != "error" and "total" in summary and not summary["total"]:
        raise ValueError("successful response has zero summary total")
    if status == "partial_success" and (summary.get("payload_error", 0)
                                        or ("error" in summary and not summary["error"])):
        raise ValueError("partial success summary contradicts processing outcomes")
    # Counts describe native lines, not slice children or individual error objects.
    # Payload validation can stop the whole batch before otherwise valid lines run.
    if (not summary.get("payload_error", 0) and {"total", "success", "error"} <= summary.keys()
            and summary["total"] != summary["success"] + summary["error"]):
        raise ValueError("summary processing counts contradict total")
    return deepcopy(dict(response))


def _batch_ids(identifiers: Sequence) -> list[str]:
    result = []
    seen = set()
    for value in identifiers:
        identifier = _identifier(value, "order_id")
        if identifier in seen:
            raise ValueError("duplicate child order_id")
        seen.add(identifier)
        result.append(identifier)
    return result


def _batch_outcome(result: dict[str, object], identifiers: list[str], response: Mapping[str, object]) -> None:
    if (result["status"] == "error" and identifiers) or (result["status"] != "error" and not identifiers):
        raise ValueError("successful child evidence contradicts response status")
    result["order_ids"] = identifiers
    result["source_fields"] = deepcopy(dict(response))


def project_multi_result(response: Mapping[str, object]) -> dict[str, object]:
    """Preserve ordered children, complete rejections and native line summaries.

    Distinct children may share correlations. Neither acknowledgements nor
    summary successes establish fills, terminal exchange orders or atomicity.
    Missing error-only data/summary stays missing; aliases cannot forge children.
    """
    result = _batch_envelope(response)
    summary = response.get("summary", {})
    if summary.get("payload_error", 0) and summary.get("error", 0):
        raise ValueError("placement payload errors preclude processing errors")
    data = response.get("data")
    rows = []
    if data is not None:
        for row in _result_sequence(data, "data"):
            if not isinstance(row, Mapping):
                raise ValueError("each successful child must be a mapping")
            _identifier(row.get("correlation_id"), "correlation_id")
            _identifier(row.get("order_id"), "order_id")
            rows.append(dict(row))
    identifiers = _batch_ids([row["order_id"] for row in rows])
    result["order_results"] = deepcopy(rows)
    _batch_outcome(result, identifiers, response)
    return result


def project_cancel_exit_result(
    response: Mapping[str, object], *, operation: str | None = None,
) -> dict[str, object]:
    """Retain cancellation/exit acknowledgements, never infer a flat position.

    This is a response-only contract. Cancellation filters are tag/segment, not
    selected order IDs; an unfiltered call targets all open orders (up to ten).
    Exit IDs identify newly placed square-off orders, not confirmed execution.
    Supply operation='cancel' to reject success/error order-ID conflicts. Exit
    error IDs are opaque position-associated evidence, not proven failed-child
    IDs. Without an operation, collisions are retained in operation_ambiguity;
    consumers must supply the operation for operation-specific validation.
    """
    if operation is not None and (not isinstance(operation, str) or operation not in ("cancel", "exit")):
        raise ValueError("operation must be None, 'cancel' or 'exit'")
    result = _batch_envelope(response)
    result.pop("operation_ambiguity", None)
    data = response.get("data")
    identifiers = []
    if data is not None:
        if not isinstance(data, Mapping):
            raise ValueError("cancel/exit data must be a mapping")
        identifiers = _batch_ids(_result_sequence(data.get("order_ids"), "data.order_ids"))
    error_ids = {error.get("order_id") for error in (response.get("errors") or [])}
    collisions = [identifier for identifier in identifiers if identifier in error_ids]
    if collisions and operation == "cancel":
        raise ValueError("cancellation order IDs appear in both successful and error evidence")
    if collisions and operation is None:
        result["operation_ambiguity"] = {"order_ids": collisions}
    _batch_outcome(result, identifiers, response)
    return result
