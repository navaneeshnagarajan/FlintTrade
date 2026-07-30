"""FlintTrade exception hierarchy.

Two distinct trees live here:

1. **OpenAlgo HTTP-client errors** (``FlintTradeError`` → ``APIError`` →
   ``OpenAlgoAuthError`` / ``OpenAlgoRateLimitError``). These describe failures
   of the OpenAlgo REST client and carry HTTP status codes.

2. **Broker-adapter taxonomy** (``BrokerError`` and its subtree). This is the
   canonical taxonomy every direct broker adapter MUST map native SDK exceptions
   to (per broker-adapter-contract §7). Raw SDK exceptions escaping an adapter
   are a contract violation — adapters MUST wrap them, preserving ``broker_code``
   for forensic audit, via ``raise FlintError(...) from sdk_error``.

   ``SafetyBypassError`` lives in this tree (a ``BrokerError``) and is raised by
   ``BrokerRouter`` when ``SafetyContext`` verification fails — the non-negotiable
   invariant of broker-adapter-contract §8.
"""

from __future__ import annotations

from datetime import datetime

# ===========================================================================
# OpenAlgo HTTP-client errors (legacy tree)
# ===========================================================================


class FlintTradeError(Exception):
    """Base exception for all FlintTrade errors."""


class ConfigError(FlintTradeError):
    """Missing or invalid configuration."""


class APIError(FlintTradeError):
    """OpenAlgo API returned an error."""

    def __init__(self, status_code: int, message: str, endpoint: str) -> None:
        self.status_code = status_code
        self.message = message
        self.endpoint = endpoint
        super().__init__(f"[{status_code}] {endpoint}: {message}")


class OpenAlgoRateLimitError(APIError):
    """OpenAlgo client hit an HTTP 429 rate limit.

    (Renamed from ``RateLimitError`` so the canonical ``RateLimitError`` name
    belongs to the broker-adapter taxonomy below. Specific to the OpenAlgo REST
    client.)
    """

    def __init__(self, endpoint: str, retry_after: float | None = None) -> None:
        self.retry_after = retry_after
        super().__init__(429, "Rate limit exceeded", endpoint)


class OpenAlgoAuthError(APIError):
    """OpenAlgo client authentication failed (HTTP 401/403).

    (Renamed from ``AuthError`` so the canonical ``AuthError`` name belongs to
    the broker-adapter taxonomy below.)
    """

    def __init__(
        self,
        endpoint: str,
        message: str = "Authentication failed",
        status_code: int = 401,
    ) -> None:
        super().__init__(status_code, message, endpoint)


# ===========================================================================
# Broker-adapter taxonomy (broker-adapter-contract §7)
# ===========================================================================


class BrokerError(Exception):
    """Base for every broker-adapter-raised exception.

    Args:
        message: human-readable error message
        broker_code: broker-native error code (e.g. "DH-401", "401"); empty if not available
        broker_id: the broker adapter that raised this (e.g. "dhan")
    """

    def __init__(self, message: str, *, broker_code: str = "", broker_id: str = "") -> None:
        super().__init__(message)
        self.broker_code = broker_code
        self.broker_id = broker_id


# ---------- auth ----------


class AuthError(BrokerError):
    """Generic broker authentication failure."""


class SessionExpired(AuthError):
    """Session token has expired and refresh failed or is not supported."""


class MFARequired(AuthError):
    """Broker requires an additional MFA step (TOTP, OTP, PIN) the adapter
    cannot complete autonomously. Operator must re-invoke login() with the
    additional credential."""


class CredentialsInvalid(AuthError):
    """Credentials are malformed or rejected by the broker (not expired —
    fundamentally wrong)."""


class BrokerSessionDegraded(AuthError):
    """Identity N2: broker session is partially valid — credentials authentic,
    but a runtime constraint blocks write operations.

    Example: Dhan DH-903 static-IP mismatch (per dhan §11.4) — credentials are
    fine, but the outbound IP doesn't match the registered static IP, so order
    placement is rejected while read-side methods (quotes, historical, option
    chain) still work.

    The router MUST set ``session.read_only_until_at = now() + 5min`` on this
    exception and refuse write methods until that timestamp passes.

    Fields:
        reason: machine-readable code (e.g. "STATIC_IP_MISMATCH").
        read_only_until: when the read-only window ends.
        broker_message: human-readable broker response (forensic context).
        broker_raw_response: full broker payload preserved for the audit chain.
    """

    def __init__(
        self,
        reason: str,
        read_only_until: datetime,
        broker_message: str | None = None,
        broker_raw_response: dict | None = None,
    ) -> None:
        self.reason = reason
        self.read_only_until = read_only_until
        self.broker_message = broker_message
        self.broker_raw_response = broker_raw_response or {}
        super().__init__(
            f"BrokerSessionDegraded(reason={reason!r}, "
            f"read_only_until={read_only_until.isoformat()})"
        )


# ---------- order ----------


class OrderError(BrokerError):
    """Generic order-placement failure."""


class InsufficientFunds(OrderError):
    """Order rejected because available funds < required margin."""


class InvalidPrice(OrderError):
    """Price violates broker tick size, circuit limit, or band rules."""


class InvalidQuantity(OrderError):
    """Quantity violates lot size, freeze quantity, or zero/negative."""


class InvalidSymbol(OrderError):
    """Symbol unknown to broker, delisted, expired (for derivatives), or
    not in any segment the adapter advertises."""


class MarketClosed(OrderError):
    """Order placed outside market hours and AMO was not requested."""


class UnsupportedOrderType(OrderError):
    """Order type/product combination not supported by this adapter (per
    Capabilities.order_types)."""


class OrderRejectedByBroker(OrderError):
    """Catch-all for broker-side rejections not covered by the more specific
    subclasses. broker_code MUST be populated for forensic audit."""


# ---------- rate limit ----------


class RateLimitError(BrokerError):
    """Broker rate-limit hit. Caller may retry after ``retry_after`` seconds.

    Args:
        retry_after: seconds to wait before retrying; 0 if broker did not specify.
        endpoint: which rate-limit bucket was exhausted ("orders", "data", ...).
    """

    def __init__(
        self,
        message: str,
        *,
        retry_after: float = 0.0,
        endpoint: str = "default",
        broker_code: str = "",
        broker_id: str = "",
    ) -> None:
        super().__init__(message, broker_code=broker_code, broker_id=broker_id)
        self.retry_after = retry_after
        self.endpoint = endpoint


# ---------- data ----------


class DataError(BrokerError):
    """Generic data-fetch failure."""


class QuoteUnavailable(DataError):
    """Broker reports no quotes available (e.g., symbol halted)."""


class HistoricalUnavailable(DataError):
    """Requested historical range outside broker's lookback window."""


class OptionChainUnavailable(DataError):
    """Underlying/expiry combination invalid or chain temporarily unavailable."""


# ---------- network ----------


class NetworkError(BrokerError):
    """Broker unreachable (DNS, TCP, TLS, HTTP-level failures)."""


class BrokerTimeout(NetworkError):
    """Broker reachable but response timed out. Transient — caller may retry."""


class BrokerInternal(NetworkError):
    """Broker returned 5xx. Transient — caller may retry with backoff."""


# ---------- registry / capability ----------


class BrokerNotFoundError(BrokerError):
    """Registry has no adapter for the requested broker_id."""


class UnsupportedCapabilityError(BrokerError):
    """Caller requested a capability the adapter does not advertise
    (e.g., greeks on a broker without option greeks support)."""


# ---------- safety ----------


class SafetyBypassError(BrokerError):
    """Raised by BrokerRouter when SafetyContext verification fails.

    See broker-adapter-contract §8 — the non-negotiable invariant. Adapters MUST
    NOT raise this themselves; only the router (and
    ``SafetyContext.verify_for_failover``) raises it.
    """
