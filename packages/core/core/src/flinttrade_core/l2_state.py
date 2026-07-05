"""Normalise broker portfolio snapshots for SafetySystem L2 checks."""

from __future__ import annotations

from collections.abc import Mapping
from types import SimpleNamespace
from typing import Any


def _to_float(value: Any) -> float:
    try:
        return float(str(value))
    except (TypeError, ValueError):
        return 0.0


def _field(obj: Any, *keys: str) -> Any:
    if isinstance(obj, Mapping):
        for key in keys:
            if key in obj:
                return obj[key]
        return None
    for key in keys:
        value = getattr(obj, key, None)
        if value is not None:
            return value
    return None


def normalise_l2_positions(raw: Any) -> list[Any]:
    """Return position-like objects with at least a ``quantity`` attribute."""
    if raw is None:
        return []
    if isinstance(raw, Mapping):
        rows = raw.get("data") or raw.get("positions") or raw.get("net") or raw.get("day") or []
    elif isinstance(raw, (list, tuple)):
        rows = raw
    else:
        rows = [raw]

    positions: list[Any] = []
    for row in rows:
        if hasattr(row, "quantity"):
            positions.append(row)
        elif isinstance(row, Mapping):
            quantity = _field(
                row,
                "quantity",
                "qty",
                "net_quantity",
                "netQty",
                "net_qty",
                "netqty",
                "cfBuyQty",
                "cfSellQty",
            )
            positions.append(SimpleNamespace(quantity=quantity or "0"))
    return positions


def normalise_l2_funds(raw: Any) -> tuple[float, float]:
    """Return ``(used_margin, total_balance)`` from broker-shaped funds."""
    used = _to_float(_field(
        raw,
        "used_margin",
        "utilized_margin",
        "utilised_margin",
        "usedmargin",
        "margin_used",
        "marginUsed",
        "MarginUsed",
        "used",
    ))
    total = _to_float(_field(
        raw,
        "total_balance",
        "total",
        "totalcollateral",
        "totalCollateral",
        "net",
        "net_balance",
        "Net",
    ))
    if total <= 0:
        available = _to_float(_field(
            raw,
            "available_balance",
            "available_margin",
            "available",
            "net",
            "Net",
        ))
        if available or used:
            total = available + used
    return used, total


def normalise_l2_state(positions: Any, funds: Any) -> tuple[list[Any], float, float]:
    """Return ``(positions, used_margin, total_balance)`` for L2 validation."""
    used_margin, total_balance = normalise_l2_funds(funds)
    return normalise_l2_positions(positions), used_margin, total_balance
