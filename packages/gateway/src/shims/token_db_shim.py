"""Shim for database.token_db — redirects to FlintTrade's contract DB.

OpenAlgo brokers call get_br_symbol(), get_token(), get_oa_symbol() etc.
We intercept these and route to our own contract database.
"""
from __future__ import annotations

from typing import Any

# Patched by adapter.py when a contract manager is available
_contract_manager: Any = None


def set_contract_manager(mgr: Any) -> None:
    """Install a contract manager for symbol/token lookups.

    Args:
        mgr: Object implementing get_br_symbol, get_token, get_oa_symbol.
    """
    global _contract_manager
    _contract_manager = mgr


def get_br_symbol(symbol: str, exchange: str) -> str:
    """Return broker-native symbol, falling through to passthrough if no manager.

    Args:
        symbol: OpenAlgo canonical symbol.
        exchange: Exchange code (e.g. ``"NSE"``).

    Returns:
        Broker-native symbol string.
    """
    if _contract_manager:
        return _contract_manager.get_br_symbol(symbol, exchange)
    return symbol  # passthrough if no manager


def get_token(symbol: str, exchange: str) -> str | None:
    """Return instrument token for the given symbol and exchange.

    Args:
        symbol: OpenAlgo canonical symbol.
        exchange: Exchange code.

    Returns:
        Instrument token string, or ``None`` if unavailable.
    """
    if _contract_manager:
        return _contract_manager.get_token(symbol, exchange)
    return None


def get_oa_symbol(symbol: str, exchange: str) -> str:
    """Return OpenAlgo canonical symbol from broker-native symbol.

    Args:
        symbol: Broker-native symbol.
        exchange: Exchange code.

    Returns:
        OpenAlgo canonical symbol string.
    """
    if _contract_manager:
        return _contract_manager.get_oa_symbol(symbol, exchange)
    return symbol


def get_exchange_token(symbol: str, exchange: str) -> str | None:
    """Return exchange token (alias for get_token).

    Args:
        symbol: OpenAlgo canonical symbol.
        exchange: Exchange code.

    Returns:
        Exchange token string, or ``None`` if unavailable.
    """
    return get_token(symbol, exchange)
