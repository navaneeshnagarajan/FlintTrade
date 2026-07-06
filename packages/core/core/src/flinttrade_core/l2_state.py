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


async def _maybe_await(value: Any) -> Any:
    import inspect  # noqa: PLC0415

    if inspect.isawaitable(value):
        return await value
    return value


async def gather_l2_state(
    config: Mapping[str, Any],
    adapter_id: str,
    *,
    account_id: str = "default",
) -> tuple[list[Any], float, float]:
    """THE shared best-effort ``(positions, used_margin, total_balance)`` gather.

    One implementation of the SafetySystem L2 input-gathering path — used by the
    human order route AND the webhook dispatcher, so the openalgo-vs-native
    branch, session resolution, and error classification can never drift between
    two copies. Reads the connected account's positions + funds through the
    same broker surface the order will use: OpenAlgo for the bridge path, or the
    active native adapter + registry session for routed native brokers.
    Best-effort by design: any failure (no client/session, network, auth)
    returns empty/zero state, so L2 simply enforces nothing for that order — a
    state-read hiccup must never block a live order (L1/L4/L5 still apply).
    """
    import logging  # noqa: PLC0415

    logger = logging.getLogger("flinttrade.l2_state")

    if adapter_id == "openalgo":
        client = config.get("OPENALGO_CLIENT")
        if client is None:
            return [], 0.0, 0.0
        try:
            positions = await _maybe_await(client.positionbook())
            funds = await _maybe_await(client.funds())
        except Exception:
            logger.debug(
                "L2 portfolio-state fetch failed — L2 limits not enforced this order",
                exc_info=True,
            )
            return [], 0.0, 0.0
        return normalise_l2_state(positions, funds)

    native_adapters = config.get("NATIVE_ADAPTERS") or {}
    registry = config.get("REGISTRY")
    adapter = native_adapters.get(adapter_id)
    if adapter is None or registry is None:
        return [], 0.0, 0.0

    try:
        session = registry.get_session_for(adapter_id, account_id)
    except Exception:
        return [], 0.0, 0.0

    positions_reader = getattr(adapter, "positions", None)
    funds_reader = getattr(adapter, "funds", None)
    if not callable(positions_reader) or not callable(funds_reader):
        return [], 0.0, 0.0
    try:
        positions = await _maybe_await(positions_reader(session))
        funds = await _maybe_await(funds_reader(session))
    except Exception:
        logger.debug(
            "Native L2 portfolio-state fetch failed — L2 limits not enforced this order",
            exc_info=True,
        )
        return [], 0.0, 0.0
    return normalise_l2_state(positions, funds)
