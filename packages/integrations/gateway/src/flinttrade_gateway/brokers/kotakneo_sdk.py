"""The single Kotak Neo v3 SDK import and response boundary.

The SDK is imported only when a native session is created. Its file logger is
disabled by default before import; an operator's explicit setting is retained.
"""

from __future__ import annotations

import logging
import os
from typing import Any

from flinttrade_core.exceptions import (
    BrokerError,
    BrokerInternal,
    BrokerTimeout,
    CredentialsInvalid,
    MFARequired,
    NetworkError,
    OrderRejectedByBroker,
    RateLimitError,
    SessionExpired,
)


def _sdk_class() -> type:
    os.environ.setdefault("NEO_LOG_FILE_ENABLED", "false")
    from neo_api_client import NeoAPI  # noqa: PLC0415

    _install_ip_log_filter()
    return NeoAPI


class _ClientIpResponseFilter(logging.Filter):
    """Redact only the client-IP endpoint's response before SDK rendering."""

    def filter(self, record: logging.LogRecord) -> bool:
        event = record.msg
        if (
            isinstance(event, dict)
            and isinstance(event.get("url"), str)
            and "/get-client-ip" in event["url"].lower()
            and "response_body" in event
        ):
            record.msg = {**event, "response_body": "<redacted>"}
        return True


def _install_ip_log_filter() -> None:
    """Keep SDK console/file levels and unrelated events intact."""
    for handler in logging.getLogger("neo_api_client").handlers:
        if not any(isinstance(existing, _ClientIpResponseFilter) for existing in handler.filters):
            handler.addFilter(_ClientIpResponseFilter())


def _error_details(value: dict[str, Any]) -> tuple[str, str]:
    """Extract only classification fields; never render a provider payload."""
    error = value.get("error") or value.get("Error") or value.get("Error Message")
    if isinstance(error, list):
        error = error[0] if error else None
    if isinstance(error, dict):
        code = str(error.get("code") or error.get("errorCode") or "")
        message = str(error.get("message") or error.get("emsg") or "")
    elif isinstance(error, BaseException):
        code = str(getattr(error, "status", "") or getattr(error, "status_code", "") or "")
        message = str(getattr(error, "reason", "") or type(error).__name__)
    else:
        code, message = "", str(error or "")
    code = code or str(value.get("errorCode") or value.get("stCode") or "")
    message = message or str(value.get("message") or value.get("errMsg") or value.get("emsg") or "")
    return code.lower(), message.lower()


def _raise_provider_error(value: dict[str, Any], *, operation: str, auth: bool = False, write: bool = False) -> None:
    layers: list[dict[str, Any]] = []
    current: Any = value
    while isinstance(current, dict):
        layers.append(current)
        current = current.get("data")

    def is_rejected(layer: dict[str, Any]) -> bool:
        status = layer.get("status")
        stat = layer.get("stat")
        status_code = layer.get("stCode")
        rejected_layer = any(key in layer for key in ("Error", "Error Message", "error"))
        rejected_layer |= "status" in layer and (
            type(status) is not str or status.lower() not in {"ok", "success"}
        )
        rejected_layer |= "stat" in layer and (type(stat) is not str or stat.lower() != "ok")
        rejected_layer |= isinstance(status_code, int) and status_code >= 400 and not (
            status_code == 1000 and operation == "whatsmyip" and status == "success"
        )
        return rejected_layer

    rejected = any(is_rejected(layer) for layer in layers)
    if not rejected:
        return

    # A provider may wrap one failure in another envelope. Classify every layer
    # before choosing an error so a nested generic/5xx detail cannot hide outer
    # authentication or rate-limit evidence.
    classified: list[tuple[int, str, str, BrokerError | None]] = []
    expiry_markers = (
        "expired", "invalid token", "invalid session", "please login", "please log in",
        "complete the 2fa process",
    )
    rate_markers = ("rate limit", "too many requests")
    for layer in layers:
        code, message = _error_details(layer)
        status_code = layer.get("stCode")
        if any(marker in message for marker in expiry_markers):
            classified.append((5, "session", code, None))
        elif code in {"401", "403"}:
            classified.append((4, "credentials" if auth else "session", code, None))
        elif code in {"429", "too_many_requests"} or any(marker in message for marker in rate_markers):
            classified.append((3, "rate", code, None))
        elif code.startswith("5") or isinstance(status_code, int) and status_code >= 500:
            classified.append((2, "internal", code, None))
        else:
            classified.append((1, "generic", code, None))

    # Embedded transport exceptions remain canonical, but lower-ranked detail
    # cannot override a stronger envelope classification.
    for layer in layers:
        for key in ("Error", "Error Message", "error"):
            embedded = layer.get(key)
            items = embedded if isinstance(embedded, list) else [embedded]
            for item in items:
                if isinstance(item, BaseException):
                    canonical = _canonical_exception(item, operation)
                    rank = (
                        5 if isinstance(canonical, SessionExpired)
                        else 3 if isinstance(canonical, RateLimitError)
                        else 4 if isinstance(canonical, CredentialsInvalid)
                        else 2 if isinstance(canonical, BrokerInternal)
                        else 1
                    )
                    classified.append((
                        rank, "exception", str(getattr(canonical, "broker_code", "") or ""), canonical,
                    ))

    _rank, classification, code, canonical = max(
        classified,
        key=lambda evidence: (evidence[0], evidence[1] == "exception"),
    )
    reason = f"Kotak Neo {operation} was rejected"
    if classification == "session":
        raise SessionExpired(reason, broker_id="kotakneo", broker_code=code)
    if classification == "credentials":
        raise CredentialsInvalid(reason, broker_id="kotakneo", broker_code=code)
    if classification == "rate":
        metadata = value.get("rateLimit")
        retry = metadata.get("retryAfter", 0) if isinstance(metadata, dict) else 0
        try:
            retry_after = max(0.0, float(retry))
        except (TypeError, ValueError):
            retry_after = 0.0
        raise RateLimitError(reason, broker_id="kotakneo", broker_code=code, retry_after=retry_after)
    if classification == "exception":
        if canonical is not None:
            raise canonical
    if auth:
        raise CredentialsInvalid(reason, broker_id="kotakneo", broker_code=code)
    if classification == "internal":
        raise BrokerInternal(reason, broker_id="kotakneo", broker_code=code)
    if write:
        raise OrderRejectedByBroker(reason, broker_id="kotakneo", broker_code=code or "REJECTED")
    raise BrokerInternal(reason, broker_id="kotakneo", broker_code=code)


def _canonical_exception(exc: Exception, operation: str) -> BrokerError:
    if isinstance(exc, BrokerError):
        return exc
    response = getattr(exc, "response", None)
    status_code = getattr(response, "status_code", None)
    if status_code is None:
        status_code = getattr(exc, "status", None) or getattr(exc, "status_code", None)
    if status_code in {401, 403}:
        return SessionExpired(f"Kotak Neo {operation} session expired", broker_id="kotakneo", broker_code=str(status_code))
    if status_code == 429:
        return RateLimitError(f"Kotak Neo {operation} was rate limited", broker_id="kotakneo", broker_code="429")
    if isinstance(status_code, int) and status_code >= 500:
        return BrokerInternal(f"Kotak Neo {operation} failed", broker_id="kotakneo", broker_code=str(status_code))
    name = type(exc).__name__.lower()
    reason = str(getattr(exc, "reason", "") or "").lower()
    if isinstance(exc, TimeoutError) or "timeout" in name or "timeout" in reason or "timed out" in reason:
        return BrokerTimeout(f"Kotak Neo {operation} timed out", broker_id="kotakneo")
    if isinstance(exc, ConnectionError) or any(
        term in name or term in reason for term in ("connect", "network", "transport", "dns", "name resolution")
    ):
        return NetworkError(f"Kotak Neo {operation} could not reach the broker", broker_id="kotakneo")
    return BrokerInternal(f"Kotak Neo {operation} failed", broker_id="kotakneo")


def validate_read_envelope(value: Any, *, operation: str) -> Any:
    """Require a successful broker read before callers extract rows or funds."""
    if operation == "search_scrip" and isinstance(value, list) and all(type(row) is dict for row in value):
        return value
    if operation == "scrip_master" and isinstance(value, str) and value.startswith("https://"):
        return value
    if type(value) is not dict or any(type(key) is not str for key in value):
        raise BrokerInternal(f"Kotak Neo {operation} response is malformed", broker_id="kotakneo")
    _raise_provider_error(value, operation=operation)
    if operation == "scrip_master" and "filesPaths" in value:
        paths = value["filesPaths"]
        if type(paths) is list and all(type(path) is str and path.startswith("https://") for path in paths):
            return value
        raise BrokerInternal("Kotak Neo scrip master paths are malformed", broker_id="kotakneo")
    if operation == "order_history" and type(value.get("data")) is dict:
        validate_read_envelope(value["data"], operation="order_history_rows")
        return value
    if operation == "margin_required" and type(value.get("data")) is dict:
        _raise_provider_error(value["data"], operation=operation)
    status = value.get("status")
    stat = value.get("stat")
    if not (isinstance(status, str) and status.lower() == "success" or isinstance(stat, str) and stat.lower() == "ok"):
        # Some SDK read responses expose a nested success status only.
        data = value.get("data")
        data_only_read = (
            operation == "quotes" and status is None and stat is None and type(data) is list
        ) or (operation == "holdings" and set(value) == {"data"} and type(data) is list)
        nested_success = isinstance(data, dict) and (
            str(data.get("status", "")).lower() == "success" or str(data.get("stat", "")).lower() == "ok"
        )
        if not data_only_read and not nested_success:
            raise BrokerInternal(f"Kotak Neo {operation} response has no success status", broker_id="kotakneo")
    status_code = value.get("stCode")
    if status_code is not None and (type(status_code) is not int or status_code not in {200, 1000}):
        raise BrokerInternal(f"Kotak Neo {operation} returned an invalid status code", broker_id="kotakneo")
    if operation in {
        "order_report", "order_history", "order_history_rows", "trade_report", "positions", "holdings",
        "quotes", "whatsmyip",
    }:
        rows = value.get("data")
        if type(rows) is not list or any(type(row) is not dict for row in rows):
            raise BrokerInternal(f"Kotak Neo {operation} returned malformed rows", broker_id="kotakneo")
    if operation == "limits":
        funds = value.get("data", value)
        if type(funds) is not dict or not any(key in funds for key in ("Net", "avlCash", "avlMrgn")):
            raise BrokerInternal("Kotak Neo limits response is malformed", broker_id="kotakneo")
    return value


def _validate_auth(value: Any, *, step: str, ucc: str) -> None:
    if type(value) is not dict:
        raise CredentialsInvalid("Kotak Neo authentication response is malformed", broker_id="kotakneo")
    _raise_provider_error(value, operation=step, auth=True)
    data = value.get("data")
    if type(data) is not dict or str(data.get("status", "")).lower() != "success":
        raise CredentialsInvalid("Kotak Neo authentication did not succeed", broker_id="kotakneo")
    for key in ("token", "sid"):
        if type(data.get(key)) is not str or not data[key].strip():
            raise CredentialsInvalid("Kotak Neo authentication token is missing", broker_id="kotakneo")
    if data.get("kType") != step:
        raise CredentialsInvalid("Kotak Neo authentication scope is invalid", broker_id="kotakneo")
    if step == "View":
        if data.get("ucc") != ucc:
            raise CredentialsInvalid("Kotak Neo account identity differs from the request", broker_id="kotakneo")
    else:
        if type(data.get("baseUrl")) is not str or not data["baseUrl"].strip():
            raise CredentialsInvalid("Kotak Neo trade API URL is missing", broker_id="kotakneo")
        if "ucc" in data and data["ucc"] != ucc:
            raise CredentialsInvalid("Kotak Neo account identity differs from the request", broker_id="kotakneo")


class KotakNeoSdkSession:
    """Owned, blocking NeoAPI session. Only this class invokes the installed SDK."""

    SFEED_NOT_WIRED = "Kotak Neo Connected (read) / API smoke is REST-only; SFeed is not wired."

    def __init__(self, credentials: dict[str, Any]) -> None:
        key = credentials.get("consumer_key") or credentials.get("access_token")
        if not isinstance(key, str) or not key.strip():
            raise CredentialsInvalid("Kotak Neo consumer key is required", broker_id="kotakneo")
        for field in ("mobile_number", "ucc", "totp", "mpin"):
            if not isinstance(credentials.get(field), str) or not credentials[field].strip():
                raise MFARequired("Fresh Kotak Neo TOTP and MPIN are required", broker_id="kotakneo")
        self._closed = False
        self._neo = None
        try:
            self._neo = _sdk_class()(
                consumer_key=key, environment=str(credentials.get("environment") or "prod"),
                access_token=None, neo_fin_key=credentials.get("neo_fin_key"),
            )
            view = self._neo.totp_login(
                mobile_number=credentials["mobile_number"], ucc=credentials["ucc"], totp=credentials["totp"],
            )
            _validate_auth(view, step="View", ucc=credentials["ucc"])
            trade = self._neo.totp_validate(mpin=credentials["mpin"])
            _validate_auth(trade, step="Trade", ucc=credentials["ucc"])
        except Exception as exc:
            self.close()
            raise _canonical_exception(exc, "login") from None

    @classmethod
    def login(cls, credentials: dict[str, Any]) -> KotakNeoSdkSession:
        """Run a fresh TOTP + MPIN exchange and return the owned session."""
        return cls(credentials)

    def _call(self, method: str, *args: Any, read: bool = False, write: bool = False, **kwargs: Any) -> Any:
        if self._closed or self._neo is None:
            raise SessionExpired("Kotak Neo session is closed", broker_id="kotakneo")
        try:
            value = getattr(self._neo, method)(*args, **kwargs)
            if read:
                return validate_read_envelope(value, operation=method)
            if write and isinstance(value, dict):
                _raise_provider_error(value, operation=method, write=True)
            return value
        except Exception as exc:
            raise _canonical_exception(exc, method) from None

    def liveness(self) -> None:
        """Probe trade-session auth; never return or log the reported IP."""
        _install_ip_log_filter()
        self._call("whatsmyip", read=True)

    def place_order(self, params: dict[str, Any]) -> dict[str, Any]:
        return self._call("place_order", write=True, **params)

    def modify_order(self, params: dict[str, Any]) -> dict[str, Any]:
        return self._call("modify_order", write=True, **params)

    def cancel_order(self, order_id: str, amo: str = "NO", is_verify: bool = False,
                     trading_symbol: str | None = None) -> dict[str, Any]:
        if trading_symbol is not None:
            raise OrderRejectedByBroker("Kotak Neo v3 cancel has no trading symbol", broker_id="kotakneo", broker_code="UNSUPPORTED")
        return self._call("cancel_order", order_id=order_id, amo=amo, isVerify=is_verify, write=True)

    def order_book(self) -> dict[str, Any]:
        return self._call("order_report", read=True)

    def order_history(self, order_id: str) -> dict[str, Any]:
        return self._call("order_history", order_id=order_id, read=True)

    def trade_book(self, order_id: str | None = None) -> dict[str, Any]:
        if order_id is not None:
            raise BrokerInternal("Kotak Neo v3 trade report has no order filter", broker_id="kotakneo")
        return self._call("trade_report", read=True)

    def positions(self) -> dict[str, Any]:
        return self._call("positions", read=True)

    def holdings(self) -> dict[str, Any]:
        return self._call("holdings", read=True)

    def funds(self) -> dict[str, Any]:
        return self._call("limits", read=True)

    def limits(self, segment: str = "ALL", exchange: str = "ALL", product: str = "ALL") -> dict[str, Any]:
        if (segment, exchange, product) != ("ALL", "ALL", "ALL"):
            raise BrokerInternal("Kotak Neo v3 limits has no server-side filters", broker_id="kotakneo")
        return self.funds()

    def quotes(self, instrument_tokens: list[dict[str, str]], quote_type: str = "all") -> Any:
        return self._call("quotes", instrument_tokens=instrument_tokens, quote_type=quote_type, read=True)

    def margin(self, params: dict[str, Any]) -> dict[str, Any]:
        return self._call("margin_required", read=True, **params)

    def scrip_master(self, exchange_segment: str | None = None) -> Any:
        return self._call("scrip_master", exchange_segment=exchange_segment, read=True)

    def search_scrip(self, exchange_segment: str, symbol: str, expiry: str | None = None,
                     option_type: str | None = None, strike_price: str | None = None,
                     ignore_50multiple: bool = True) -> Any:
        return self._call("search_scrip", exchange_segment=exchange_segment, symbol=symbol, expiry=expiry,
                          option_type=option_type, strike_price=strike_price,
                          ignore_50multiple=ignore_50multiple, read=True)

    def expiries(self, exchange: str, underlying: str, instrument_type: str | None = None) -> Any:
        return self._call("expiries", exchange=exchange, underlying=underlying,
                          instrument_type=instrument_type, read=True)

    def option_chain(self, exchange: str, underlying: str, expiry: str | None = None,
                     instrument_type: str | None = None, count: int | None = None) -> Any:
        return self._call("option_chain", exchange=exchange, underlying=underlying, expiry=expiry,
                          instrument_type=instrument_type, count=count, read=True)

    def historical_data(self, neosymbol: str, interval: str, from_date: str, to_date: str) -> Any:
        return self._call("historical_data", neosymbol=neosymbol, interval=interval, from_date=from_date,
                          to_date=to_date, read=True)

    def subscribe(self, instrument_tokens: list[dict[str, str]], is_index: bool, is_depth: bool) -> None:
        raise BrokerError(self.SFEED_NOT_WIRED, broker_id="kotakneo")

    def un_subscribe(self, instrument_tokens: list[dict[str, str]], is_index: bool, is_depth: bool) -> None:
        raise BrokerError(self.SFEED_NOT_WIRED, broker_id="kotakneo")

    def subscribe_to_orderfeed(self) -> None:
        raise BrokerError(self.SFEED_NOT_WIRED, broker_id="kotakneo")

    def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        neo = self._neo
        self._neo = None
        if neo is None:
            return
        try:
            neo.logout()
        except Exception:
            pass
        rest = getattr(getattr(neo, "api_client", None), "rest_client", None)
        close = getattr(rest, "close", None)
        if callable(close):
            try:
                close()
            except Exception:
                pass

    def logout(self) -> None:
        self.close()
