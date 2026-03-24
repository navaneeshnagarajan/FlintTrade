"""Pydantic models for the FlintTrade broker gateway."""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum

from pydantic import BaseModel


# ---------------------------------------------------------------------------
# Enums
# ---------------------------------------------------------------------------


class AuthFlowType(StrEnum):
    """Authentication flow required by a broker."""

    oauth_redirect = "oauth_redirect"
    totp_form = "totp_form"
    api_key_direct = "api_key_direct"
    otp_sms = "otp_sms"


class AccountStatus(StrEnum):
    """Connection status of a broker account."""

    disconnected = "disconnected"
    authenticating = "authenticating"
    connected = "connected"
    error = "error"
    token_expired = "token_expired"


# ---------------------------------------------------------------------------
# Broker catalog models
# ---------------------------------------------------------------------------


class BrokerInfo(BaseModel):
    """Static metadata describing a broker's capabilities and auth requirements.

    Args:
        name: Canonical machine-readable broker identifier (e.g. ``"zerodha"``).
        display_name: Human-readable broker name shown in the UI.
        auth_flow: Authentication flow type the broker requires.
        exchanges: List of exchange codes the broker supports.
        max_symbols_per_ws: Maximum WebSocket subscriptions per connection.
        supports_streaming: Whether the broker offers a live WebSocket feed.
        oauth_url_template: URL template for OAuth redirect flows (``None``
            for non-OAuth flows).
        is_sandbox: Whether this entry represents a sandbox/paper environment.
    """

    name: str
    display_name: str
    auth_flow: AuthFlowType
    exchanges: list[str]
    max_symbols_per_ws: int = 3000
    supports_streaming: bool = True
    oauth_url_template: str | None = None
    is_sandbox: bool = False


class BrokerAccountInfo(BaseModel):
    """Runtime state of a single connected broker account.

    Args:
        account_id: Unique identifier for the account within the broker.
        broker: Canonical broker name matching :attr:`BrokerInfo.name`.
        label: User-facing label for this account (e.g. ``"Primary Zerodha"``).
        status: Current connection/auth status of the account.
        connected_at: UTC timestamp of the last successful connection.
        error_message: Human-readable error detail when status is ``error``.
        is_primary: Whether this is the primary account for order routing.
    """

    account_id: str
    broker: str
    label: str
    status: AccountStatus = AccountStatus.disconnected
    connected_at: datetime | None = None
    error_message: str | None = None
    is_primary: bool = False
