"""Model-duty projections of existing native rows and service-ledger receipts.

This module owns no storage, spend or settlement authority. Resolved calls stay
in the native row for non-replenishing historical budget accounting.
"""
from __future__ import annotations

from typing import Any

from .native_autonomy_contracts_v2 import ModelDutyV2


_TERMINAL = {"SETTLED", "CANCELLED"}


def model_obligations(row: dict[str, Any]) -> list[dict[str, Any]]:
    """Project only unresolved tasks without inventing broker writes or costs.

    Args:
        row: The native owner's durable row, including actual task receipts.

    Returns:
        Strict model duties. A missing or pending receipt retains the reservation;
        only a final task with all evidenced terminal attempts leaves the census.

    Raises:
        ValueError: A retained observation contradicts its nominal duty contract.
    """
    from .native_autonomy import _digest

    duties = []
    for call in row.get("model_calls", []):
        receipt = call.get("receipt") or {}
        attempts = receipt.get("attempts", [])
        if (call["state"] in {"completed", "refused"}
                and receipt.get("outcome") in {"completed", "refused"}
                and all(a["state"] in _TERMINAL for a in attempts)):
            continue
        observed = []
        for attempt in attempts:
            known = attempt["state"] in _TERMINAL
            charged, reserved = attempt["charged"], attempt["reservation"]
            observed.append({
                "attempt_id": attempt["attempt_id"],
                "receipt_ref": {"id": attempt["attempt_id"], "revision": _digest(attempt)},
                "state": attempt["state"], "currency": attempt["tariff"]["currency"],
                "tokens_reserved": reserved["input_tokens"] + reserved["output_tokens"],
                "cost_micros_reserved": reserved["currency_micros"],
                "observed_tokens": charged["input_tokens"] + charged["output_tokens"] if known else None,
                "observed_cost_micros": charged["currency_micros"] if known else None,
            })
        duty = ModelDutyV2.model_validate({
            "request_ref": {"id": call["request_id"], "revision": call["task_digest"]},
            "task_outcome": call["state"], "tokens_reserved": call["tokens_reserved"],
            "cost_micros_reserved": call["cost_micros_reserved"], "currency": call["currency"],
            "attempts": observed,
        })
        duties.append(duty.model_dump(mode="json"))
    return duties
