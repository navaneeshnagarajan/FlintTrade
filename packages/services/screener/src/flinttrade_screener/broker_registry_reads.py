"""Helpers for live reads through the legacy BrokerRegistry.

The screener blueprints are synchronous Flask routes, while broker reads are
exposed through the gateway's legacy ``BrokerRegistry`` contract:
``get_history(account_id, params)``. Keep that shape in one place so widgets do
not quietly fall back to sample data because each route guessed a different
call signature.
"""

from __future__ import annotations

from datetime import date, timedelta
from typing import Any


def primary_account_id(registry: Any) -> str:
    """Return the registry's primary account id or raise when none is usable."""
    getter = getattr(registry, "get_primary_account_id", None)
    account_id = getter() if callable(getter) else None
    if not account_id:
        raise ValueError("Broker registry is connected but has no usable account id")
    return str(account_id)


def get_history(
    registry: Any,
    *,
    symbol: str,
    exchange: str,
    interval: str,
    days: int | None = None,
    start: str | None = None,
    end: str | None = None,
) -> dict[str, Any]:
    """Fetch OHLCV from ``BrokerRegistry.get_history(account_id, params)``."""
    account_id = primary_account_id(registry)
    params: dict[str, Any] = {
        "symbol": symbol,
        "exchange": exchange,
        "interval": interval,
    }
    if start:
        params["start"] = start
    if end:
        params["end"] = end
    if days is not None:
        params["days"] = days
        if not start:
            params["start"] = (date.today() - timedelta(days=days)).isoformat()
        if not end:
            params["end"] = date.today().isoformat()
    return registry.get_history(account_id, params)


def get_option_chain(
    registry: Any,
    *,
    symbol: str,
    exchange: str,
    expiry: str | None = None,
) -> dict[str, Any]:
    """Fetch option-chain data when the registry exposes a compatible method."""
    method = getattr(registry, "get_option_chain", None)
    if not callable(method):
        raise AttributeError("Broker registry does not expose get_option_chain")
    account_id = primary_account_id(registry)
    params: dict[str, Any] = {"symbol": symbol, "exchange": exchange}
    if expiry:
        params["expiry"] = expiry
    return method(account_id, params)
