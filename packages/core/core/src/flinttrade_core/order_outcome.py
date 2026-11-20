"""Honest wording for an order whose result is not yet known.

These helpers only label a result that already exists. They do not place,
cancel, or retry an order. A later submit still has to pass the dispatch
ledger, which refuses a second broker write while an outcome is unknown.
"""

from __future__ import annotations

from typing import Any

ORDER_STATUS_UNKNOWN = "Order status unknown. Check Orders before trying again."
CANCELLATION_REQUESTED = "Cancellation requested"
ORDER_CANCELLED = "Order cancelled"

REASON_RESPONSE_UNCONFIRMED = "response_unconfirmed"
REASON_AWAITING_CONFIRMATION = "awaiting_confirmation"
REASON_STATUS_CONFIRMED = "status_confirmed"
REASON_BROKER_REJECTED = "broker_rejected"
REASON_TOOL_UNAVAILABLE = "tool_unavailable"

_CONFIRMED_CANCELLED = frozenset({"CANCELLED", "CANCELED"})


def annotate(
    payload: dict[str, Any],
    *,
    outcome: str,
    reason: str,
    message: str | None = None,
) -> dict[str, Any]:
    """Add the outcome beside the existing status envelope."""
    annotated = dict(payload)
    annotated["order_outcome"] = outcome
    annotated["reason"] = reason
    annotated["retry_safe"] = False
    if message is not None:
        annotated["message"] = message
    return annotated


def unknown_outcome(*, status: str = "error") -> dict[str, Any]:
    """A dropped, timed-out, or otherwise unconfirmed submit or cancel."""
    return annotate(
        {"status": status},
        outcome="unknown",
        reason=REASON_RESPONSE_UNCONFIRMED,
        message=ORDER_STATUS_UNKNOWN,
    )


def _status_token(value: object) -> str:
    if not isinstance(value, str):
        return ""
    return "_".join(part for part in "".join(ch if ch.isalnum() else "_" for ch in value.strip().upper()).split("_") if part)


def result_is_cancelled(result: object) -> bool:
    """True only when the engine or broker status itself says cancelled."""
    if not isinstance(result, dict):
        return False
    return any(_status_token(result.get(key)) in _CONFIRMED_CANCELLED for key in ("status", "order_status", "attempt_state"))


def cancel_acknowledgement(result: object, *, message: str | None = None) -> dict[str, str | bool]:
    """Label a cancel that returned, without turning an acknowledgement into a cancel."""
    if result_is_cancelled(result):
        fields: dict[str, str | bool] = {
            "order_outcome": "cancelled",
            "reason": REASON_STATUS_CONFIRMED,
        }
        if message is not None:
            fields["message"] = message
        return fields
    return {
        "order_outcome": "cancel_requested",
        "reason": REASON_AWAITING_CONFIRMATION,
        "message": CANCELLATION_REQUESTED,
    }


def describe_tool_outcome(payload: dict[str, Any] | None, *, dropped: bool = False) -> dict[str, Any]:
    """Shape an agent or MCP tool result the same way as the order API."""
    if dropped or payload is None:
        return unknown_outcome()
    if payload.get("order_outcome") in {"unknown", "cancel_requested", "cancelled", "rejected"}:
        described = dict(payload)
        described["retry_safe"] = False
        return described
    status = _status_token(payload.get("status"))
    if status in _CONFIRMED_CANCELLED:
        return annotate(payload, outcome="cancelled", reason=REASON_STATUS_CONFIRMED, message=ORDER_CANCELLED)
    if status == "REJECTED":
        return annotate(payload, outcome="rejected", reason=REASON_BROKER_REJECTED)
    if status in {"CANCEL_PENDING", "CANCEL_REQUESTED", "PENDING_CANCEL"}:
        return annotate(payload, outcome="cancel_requested", reason=REASON_AWAITING_CONFIRMATION, message=CANCELLATION_REQUESTED)
    if status in {"ERROR", "UNKNOWN"} or payload.get("dispatch_outcome") == "unknown_after_dispatch":
        return annotate(payload, outcome="unknown", reason=REASON_RESPONSE_UNCONFIRMED, message=ORDER_STATUS_UNKNOWN)
    return annotate(payload, outcome="unknown", reason=REASON_RESPONSE_UNCONFIRMED, message=ORDER_STATUS_UNKNOWN)
