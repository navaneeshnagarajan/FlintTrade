"""Shim for database.auth_db — provides auth token from BrokerSession.

OpenAlgo brokers call get_auth_token() which reads from their SQLAlchemy DB.
We intercept and return the token from the active BrokerSession.
"""
from __future__ import annotations

_auth_tokens: dict[str, str] = {}  # broker_name -> auth_token


def set_auth_token(broker_name: str, token: str) -> None:
    """Store an auth token for a given broker.

    Args:
        broker_name: Canonical broker name (e.g. ``"zerodha"``).
        token: Auth token string returned by the broker's auth flow.
    """
    _auth_tokens[broker_name] = token


def get_auth_token() -> str | None:
    """Return the most recently set auth token.

    Returns:
        Auth token string, or ``None`` if none have been set.
    """
    if _auth_tokens:
        return next(iter(_auth_tokens.values()))
    return None


def get_auth_token_broker(broker_name: str) -> str | None:
    """Return the auth token for a specific broker.

    Args:
        broker_name: Canonical broker name.

    Returns:
        Auth token string, or ``None`` if not set for this broker.
    """
    return _auth_tokens.get(broker_name)
