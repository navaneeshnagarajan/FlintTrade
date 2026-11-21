"""Honest wording for an order whose result is not yet known.

These helpers only label a result that already exists. They do not place,
cancel, or retry an order. A later submit still has to pass the dispatch
ledger, which refuses a second broker write while an outcome is unknown.
"""

from __future__ import annotations

from dataclasses import dataclass
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

@dataclass
class DispatchProgress:
    """Request-local invocation evidence, not execution or durable authority.

    A sync wait can time out while the router coroutine still runs. Only its
    completed failure before the invocation hook proves no adapter invocation.
    """

    started: bool = False
    invoked: bool = False
    failed_before_invoke: bool = False

    def on_adapter_invoke(self) -> None:
        self.invoked = True

    @property
    def outcome_unknown(self) -> bool:
        return self.started and not self.failed_before_invoke

    async def run(self, coroutine: Any) -> Any:
        try:
            return await coroutine
        except BaseException:
            self.failed_before_invoke = not self.invoked
            raise


# Each leg of an order record is unknown (its reply was lost), confirmed (a
# reply or read shows it at the broker) or absent (it was refused or never
# placed). A single-leg order has only an entry leg.
LEG_NAMES = ("entry", "target", "stop_loss")
LEG_STATES = frozenset({"unknown", "confirmed", "absent"})
_ENTRY_LEG_FOR_OUTCOME = {"unknown": "unknown", "rejected": "absent"}


def leg_outcomes(**legs: str | None) -> dict[str, str]:
    """One outcome per named leg; legs passed as None are left out."""
    shaped: dict[str, str] = {}
    for name, state in legs.items():
        if name not in LEG_NAMES or (state is not None and state not in LEG_STATES):
            raise ValueError(f"invalid leg outcome {name}={state!r}")
        if state is not None:
            shaped[name] = state
    return shaped


def single_leg_outcomes(outcome: str) -> dict[str, str]:
    """The entry leg of a single-leg order, read from its order_outcome."""
    return leg_outcomes(entry=_ENTRY_LEG_FOR_OUTCOME.get(outcome, "confirmed"))


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
    annotated.setdefault("leg_outcomes", single_leg_outcomes(outcome))
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


def cancel_acknowledgement(
    result: object, *, message: str | None = None,
) -> dict[str, str | bool | dict[str, str]]:
    """Label a cancel that returned, without turning an acknowledgement into a cancel."""
    if result_is_cancelled(result):
        fields: dict[str, str | bool | dict[str, str]] = {
            "order_outcome": "cancelled",
            "reason": REASON_STATUS_CONFIRMED,
            "leg_outcomes": single_leg_outcomes("cancelled"),
        }
        if message is not None:
            fields["message"] = message
        return fields
    return {
        "order_outcome": "cancel_requested",
        "reason": REASON_AWAITING_CONFIRMATION,
        "message": CANCELLATION_REQUESTED,
        "leg_outcomes": single_leg_outcomes("cancel_requested"),
    }


def describe_tool_outcome(payload: dict[str, Any] | None, *, dropped: bool = False) -> dict[str, Any]:
    """Shape an agent or MCP tool result the same way as the order API."""
    if dropped or payload is None:
        return unknown_outcome()
    if payload.get("order_outcome") in {"unknown", "cancel_requested", "cancelled", "rejected"}:
        described = dict(payload)
        described["retry_safe"] = False
        described.setdefault("leg_outcomes", single_leg_outcomes(described["order_outcome"]))
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
