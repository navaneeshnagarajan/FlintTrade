"""Pure Delta Exchange v2 mapping.

Signing follows the official ``delta-rest-client`` prehash, not the stale
sample hex on the docs page (that hash matches a pre-v2 ``/orders`` path).
The prehash is ``method + timestamp + path + query + body``, with the query
in official-client form (``?k=v`` via ``quote_plus``, or an empty string)
and the body as compact JSON. India and Global keys are not interchangeable.
"""

from __future__ import annotations

import hashlib
import hmac
import json
from copy import deepcopy
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from typing import Any, Callable, Mapping
from urllib.parse import quote_plus

from flinttrade_core.broker_read_port import BrokerReadResponseInvalid
from flinttrade_core.exceptions import (
    BrokerError,
    BrokerInternal,
    CredentialsInvalid,
    InsufficientFunds,
    InvalidPrice,
    InvalidQuantity,
    InvalidSymbol,
    OrderRejectedByBroker,
    RateLimitError,
    SessionExpired,
)

BROKER_ID = "deltaexchange"
USER_AGENT = "FlintTrade-delta-native"

# Documented India sockets are from docs.delta.exchange. Global REST hosts are
# from the official python-rest-client README. Global websocket hosts are not
# published on the India docs page, so they stay empty until that evidence exists.
@dataclass(frozen=True, slots=True)
class DeltaVenue:
    """One Delta environment. Keys from another venue are rejected by the API."""

    id: str
    rest_base: str
    private_ws: str
    public_ws: str
    testnet: bool
    region: str


VENUES: dict[str, DeltaVenue] = {
    "india_prod": DeltaVenue(
        "india_prod",
        "https://api.india.delta.exchange",
        "wss://socket.india.delta.exchange",
        "wss://public-socket.india.delta.exchange",
        False,
        "india",
    ),
    "india_testnet": DeltaVenue(
        "india_testnet",
        "https://cdn-ind.testnet.deltaex.org",
        "wss://socket-ind.testnet.deltaex.org",
        "wss://socket-ind-pub.testnet.deltaex.org",
        True,
        "india",
    ),
    "global_prod": DeltaVenue(
        "global_prod",
        "https://api.delta.exchange",
        "",
        "",
        False,
        "global",
    ),
    "global_testnet": DeltaVenue(
        "global_testnet",
        "https://testnet-api.delta.exchange",
        "",
        "",
        True,
        "global",
    ),
}

# Every path in the India v2 swagger. ``{param}`` is substituted by the caller.
# Non-GET methods are writes and must pass the router token before they are sent.
V2_ENDPOINTS: tuple[tuple[str, str, str], ...] = (
    ("assets", "GET", "/v2/assets"),
    ("fills", "GET", "/v2/fills"),
    ("fills_csv", "GET", "/v2/fills/history/download/csv"),
    ("heartbeat_ack", "POST", "/v2/heartbeat"),
    ("heartbeats", "GET", "/v2/heartbeat"),
    ("heartbeat_create", "POST", "/v2/heartbeat/create"),
    ("candles", "GET", "/v2/history/candles"),
    ("sparklines", "GET", "/v2/history/sparklines"),
    ("indices", "GET", "/v2/indices"),
    ("l2_orderbook", "GET", "/v2/l2orderbook/{symbol}"),
    ("place_order", "POST", "/v2/orders"),
    ("cancel_order", "DELETE", "/v2/orders"),
    ("edit_order", "PUT", "/v2/orders"),
    ("open_orders", "GET", "/v2/orders"),
    ("cancel_all_orders", "DELETE", "/v2/orders/all"),
    ("batch_create", "POST", "/v2/orders/batch"),
    ("batch_edit", "PUT", "/v2/orders/batch"),
    ("batch_cancel", "DELETE", "/v2/orders/batch"),
    ("place_bracket", "POST", "/v2/orders/bracket"),
    ("edit_bracket", "PUT", "/v2/orders/bracket"),
    ("order_by_client_id", "GET", "/v2/orders/client_order_id/{client_oid}"),
    ("order_history", "GET", "/v2/orders/history"),
    ("order_by_id", "GET", "/v2/orders/{order_id}"),
    ("positions", "GET", "/v2/positions"),
    ("auto_topup", "PUT", "/v2/positions/auto_topup"),
    ("change_margin", "POST", "/v2/positions/change_margin"),
    ("close_all_positions", "POST", "/v2/positions/close_all"),
    ("margined_positions", "GET", "/v2/positions/margined"),
    ("products", "GET", "/v2/products"),
    ("product", "GET", "/v2/products/{symbol}"),
    ("set_leverage", "POST", "/v2/products/{product_id}/orders/leverage"),
    ("get_leverage", "GET", "/v2/products/{product_id}/orders/leverage"),
    ("rate_limit_quota", "GET", "/v2/rate_limits/quota"),
    ("stats", "GET", "/v2/stats"),
    ("subaccounts", "GET", "/v2/sub_accounts"),
    ("tickers", "GET", "/v2/tickers"),
    ("ticker", "GET", "/v2/tickers/{symbol}"),
    ("public_trades", "GET", "/v2/trades/{symbol}"),
    ("margin_mode", "PUT", "/v2/users/margin_mode"),
    ("reset_mmp", "PUT", "/v2/users/reset_mmp"),
    ("trading_preferences", "GET", "/v2/users/trading_preferences"),
    ("update_trading_preferences", "PUT", "/v2/users/trading_preferences"),
    ("update_mmp", "PUT", "/v2/users/update_mmp"),
    ("wallet_balances", "GET", "/v2/wallet/balances"),
    ("wallet_transactions", "GET", "/v2/wallet/transactions"),
    ("wallet_transactions_download", "GET", "/v2/wallet/transactions/download"),
    ("subaccount_transfer", "POST", "/v2/wallets/sub_account_balance_transfer"),
    ("subaccount_transfer_history", "GET", "/v2/wallets/sub_accounts_transfer_history"),
)

ENDPOINTS: dict[str, tuple[str, str]] = {name: (method, path) for name, method, path in V2_ENDPOINTS}

CANDLE_RESOLUTIONS = ("1m", "3m", "5m", "15m", "30m", "1h", "2h", "4h", "6h", "1d", "1w")
_RESOLUTION_ALIASES = {
    "1": "1m",
    "3": "3m",
    "5": "5m",
    "15": "15m",
    "30": "30m",
    "60": "1h",
    "60m": "1h",
    "120": "2h",
    "120m": "2h",
    "240": "4h",
    "240m": "4h",
    "360": "6h",
    "360m": "6h",
    "d": "1d",
    "1D": "1d",
    "w": "1w",
    "1W": "1w",
}


def unix_seconds(raw: Any) -> int:
    """Accept unix seconds or an ISO date/datetime. Dates are UTC midnight."""
    from datetime import UTC, datetime

    if isinstance(raw, bool) or raw is None or (isinstance(raw, str) and not raw.strip()):
        raise BrokerError("Delta candle bound is missing", broker_id=BROKER_ID)
    if isinstance(raw, (int, float)):
        return int(raw)
    text = str(raw).strip()
    if text.isdigit():
        return int(text)
    normalised = text.replace("Z", "+00:00")
    try:
        parsed = datetime.fromisoformat(normalised)
    except ValueError as exc:
        raise BrokerError(
            f"Delta candle bound {text!r} is not a unix timestamp or ISO date",
            broker_id=BROKER_ID,
        ) from exc
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=UTC)
    return int(parsed.timestamp())


def resolve_venue(environment: str) -> DeltaVenue:
    """Return a known venue, or raise. Never guess India versus Global."""
    key = str(environment or "").strip().lower().replace("-", "_")
    venue = VENUES.get(key)
    if venue is None:
        allowed = ", ".join(sorted(VENUES))
        raise BrokerError(
            f"Delta environment must be one of {allowed}",
            broker_id=BROKER_ID,
        )
    return venue


def query_string(query: Mapping[str, Any] | None) -> str:
    """Official-client query prehash. Empty when there is no query."""
    if not query:
        return ""
    parts = [f"{key}={quote_plus(str(value))}" for key, value in query.items() if value is not None]
    if not parts:
        return ""
    return "?" + "&".join(parts)


def body_string(body: Mapping[str, Any] | None) -> str:
    """Compact JSON, or an empty string. The same text must be signed and sent."""
    if body is None:
        return ""
    return json.dumps(body, separators=(",", ":"))


def sign_request(secret: str, method: str, timestamp: str, path: str, query: str, body: str) -> str:
    """HMAC-SHA256 hex of the official prehash."""
    message = f"{method.upper()}{timestamp}{path}{query}{body}"
    return hmac.new(secret.encode("utf-8"), message.encode("utf-8"), hashlib.sha256).hexdigest()


def signed_headers(*, api_key: str, api_secret: str, method: str, timestamp: str, path: str, query: str, body: str) -> dict[str, str]:
    """Headers required on every authenticated Delta request."""
    return {
        "Content-Type": "application/json",
        "Accept": "application/json",
        "User-Agent": USER_AGENT,
        "api-key": api_key,
        "timestamp": timestamp,
        "signature": sign_request(api_secret, method, timestamp, path, query, body),
    }


def public_headers() -> dict[str, str]:
    """User-Agent is required even on public routes, or Delta returns 4xx."""
    return {
        "Content-Type": "application/json",
        "Accept": "application/json",
        "User-Agent": USER_AGENT,
    }


def fill_path(template: str, params: Mapping[str, Any] | None) -> str:
    """Substitute ``{name}`` segments. Raises if a placeholder remains."""
    path = template
    for key, value in (params or {}).items():
        path = path.replace("{" + key + "}", quote_plus(str(value)))
    if "{" in path or "}" in path:
        raise BrokerError(f"Delta path {template!r} is missing parameters", broker_id=BROKER_ID)
    return path


def is_write(method: str) -> bool:
    return method.upper() != "GET"


def unwrap(payload: Any, *, status: int, endpoint: str, preserve_envelope: bool = False) -> Any:
    """Return ``result`` from a success envelope, or raise a mapped error."""
    if status >= 400 or _failed(payload):
        raise map_error(status, payload, endpoint=endpoint)
    if preserve_envelope:
        return deepcopy(payload)
    if isinstance(payload, dict) and "result" in payload:
        return payload["result"]
    return payload


def _failed(payload: Any) -> bool:
    return isinstance(payload, dict) and payload.get("success") is False


def operation_evidence(payload: Any, *, operation: str) -> dict[str, Any]:
    """Retain every native outcome separately from dispatcher ACK counts."""
    result = payload.get("result") if isinstance(payload, Mapping) else None
    lists = {key: deepcopy(value) for key, value in result.items() if isinstance(value, list)} \
        if isinstance(result, Mapping) else {}
    errors = []
    for source in (payload, result):
        if isinstance(source, Mapping) and isinstance(source.get("errors"), list):
            errors.extend(deepcopy(source["errors"]))
        elif isinstance(source, Mapping) and source.get("errors") not in (None, "", [], {}):
            errors.append(deepcopy(source["errors"]))
        if isinstance(source, Mapping) and source.get("error") not in (None, "", [], {}):
            errors.append(deepcopy(source["error"]))
    return {
        "operation": operation, "raw_response": deepcopy(payload),
        "items": deepcopy(result) if isinstance(result, list) else deepcopy(lists.get("orders", [])),
        "result_lists": lists, "native_errors": errors,
        "skipped_products": deepcopy(lists.get("skipped_products", [])), "complete": False,
    }


def require_write_success(payload: Any, *, expected_id: str | None = None) -> dict[str, Any]:
    """A positive order ACK is not a fill; error IDs never establish an ACK."""
    if not isinstance(payload, Mapping) or payload.get("success") is not True:
        raise BrokerError("Delta write acknowledgement is unavailable", broker_id=BROKER_ID)
    result = payload.get("result")
    if not isinstance(result, Mapping):
        raise BrokerError("Delta write acknowledgement has no order result", broker_id=BROKER_ID)
    for source in (payload, result):
        if source.get("error") or source.get("errors") or source.get("success") is False:
            raise map_error(400, source, endpoint="/v2/orders")
    identifier = _order_id(result.get("id"))
    if expected_id is not None and identifier != _order_id(expected_id):
        raise BrokerError("Delta write acknowledgement order id conflicts", broker_id=BROKER_ID)
    if "product_id" in result:
        _order_id(result["product_id"])
    return deepcopy(dict(result))


def _error_fields(payload: Any) -> tuple[str, str]:
    if not isinstance(payload, dict):
        text = str(payload or "").strip()
        return "", text
    error = payload.get("error")
    if isinstance(error, dict):
        code = str(error.get("code") or error.get("error_code") or "").strip()
        message = str(error.get("message") or error.get("context") or code).strip()
        return code, message
    if isinstance(error, str):
        return error.strip(), str(payload.get("message") or error).strip()
    return str(payload.get("code") or "").strip(), str(payload.get("message") or "").strip()


def map_error(status: int, payload: Any, *, endpoint: str | None = None) -> BrokerError:
    """Map a Delta HTTP or envelope failure into FlintTrade's taxonomy."""
    code, message = _error_fields(payload)
    message = message or "Delta Exchange API error"
    lower = f"{code} {message}".lower()
    kwargs = {"broker_code": code or str(status), "broker_id": BROKER_ID}
    if "signatureexpired" in lower or "signature has expired" in lower:
        return SessionExpired("Delta request signature expired; check the system clock", **kwargs)
    if status in (401, 403) or "invalid_api_key" in lower or "unauthorized" in lower:
        return CredentialsInvalid("Delta API key was rejected for this venue", **kwargs)
    if status == 429 or "rate_limit" in lower or "too many requests" in lower:
        return RateLimitError(message, endpoint=endpoint or "delta", broker_code=code or str(status), broker_id=BROKER_ID)
    if status >= 500:
        return BrokerInternal(message, **kwargs)
    if "insufficient" in lower and "margin" in lower:
        return InsufficientFunds(message, **kwargs)
    if "size" in lower or "quantity" in lower:
        return InvalidQuantity(message, **kwargs)
    if "price" in lower or "tick" in lower:
        return InvalidPrice(message, **kwargs)
    if "product" in lower or "symbol" in lower:
        return InvalidSymbol(message, **kwargs)
    if status >= 400:
        return OrderRejectedByBroker(message, **kwargs)
    return BrokerError(message, **kwargs)


def product_symbol(raw: Any) -> str:
    """Strip an optional ``CRYPTO:`` prefix. Quantity is contract size, not coin size."""
    text = str(raw or "").strip()
    if ":" in text:
        _exchange, text = text.split(":", 1)
        text = text.strip()
    if not text:
        raise InvalidSymbol("Delta order is missing a product symbol", broker_id=BROKER_ID)
    return text


def contract_size(raw: Any) -> int:
    """Delta order size is an integer contract count."""
    if isinstance(raw, bool) or not isinstance(raw, (int, str)):
        raise InvalidQuantity("Delta order size must be a positive integer contract count", broker_id=BROKER_ID)
    text = str(raw if raw is not None else "").strip()
    if not text or any(ch not in "0123456789" for ch in text):
        raise InvalidQuantity("Delta order size must be a positive integer contract count", broker_id=BROKER_ID)
    try:
        size = int(text)
    except ValueError as exc:
        raise InvalidQuantity("Delta order size must be a positive integer contract count", broker_id=BROKER_ID) from exc
    if size <= 0:
        raise InvalidQuantity("Delta order size must be a positive integer contract count", broker_id=BROKER_ID)
    return size


def _side(action: Any) -> str:
    text = str(action or "").strip().lower()
    if text in {"buy", "b"}:
        return "buy"
    if text in {"sell", "s"}:
        return "sell"
    raise BrokerError(f"Delta order side {action!r} is not buy or sell", broker_id=BROKER_ID)


def _price_text(raw: Any, *, optional: bool = True) -> str:
    """Canonical zero defaults mean absent; supplied applicable prices never round."""
    if optional and (raw is None or raw == ""):
        return ""
    if isinstance(raw, bool) or not isinstance(raw, (str, int, float, Decimal)):
        raise InvalidPrice("Delta price must be a positive finite decimal", broker_id=BROKER_ID)
    text = str(raw if raw is not None else "").strip()
    try:
        value = Decimal(text)
    except InvalidOperation as exc:
        raise InvalidPrice("Delta price must be a positive finite decimal", broker_id=BROKER_ID) from exc
    if not value.is_finite() or value < 0 or (not optional and value == 0):
        raise InvalidPrice("Delta price must be a positive finite decimal", broker_id=BROKER_ID)
    if value == 0:
        return ""
    return text


def _request_alias(fields: Mapping[str, Any], names: tuple[str, ...], convert: Callable) -> Any:
    values = [convert(fields[name]) for name in names if name in fields]
    if not values:
        return None
    comparable = [Decimal(value) if convert is _required_price else value for value in values]
    if any(value != comparable[0] for value in comparable[1:]):
        raise BrokerError(f"Delta {'/'.join(names)} aliases conflict", broker_id=BROKER_ID)
    return values[0]


def _required_price(raw: Any) -> str:
    return _price_text(raw, optional=False)


def time_in_force(validity: Any) -> str:
    """24/7 contracts have no Indian DAY session. DAY and empty map to GTC."""
    text = str(validity or "").strip().lower()
    if text in {"", "gtc", "day"}:
        return "gtc"
    if text == "ioc":
        return "ioc"
    raise BrokerError(f"Delta time in force {validity!r} is not gtc or ioc", broker_id=BROKER_ID)


def candle_resolution(interval: Any) -> str:
    text = str(interval or "1m").strip()
    mapped = _RESOLUTION_ALIASES.get(text, text.lower())
    if mapped not in CANDLE_RESOLUTIONS:
        allowed = ", ".join(CANDLE_RESOLUTIONS)
        raise BrokerError(f"Delta candle resolution must be one of {allowed}", broker_id=BROKER_ID)
    return mapped


def option_expiry(raw: Any) -> str:
    """Normalise an expiry to Delta's option-chain ``DD-MM-YYYY`` form."""
    text = str(raw or "").strip()
    if not text:
        raise BrokerError("Delta option chain requires an expiry date", broker_id=BROKER_ID)
    if len(text) == 10 and text[2] == "-" and text[5] == "-":
        return text
    if len(text) == 10 and text[4] == "-" and text[7] == "-":
        year, month, day = text.split("-")
        return f"{day}-{month}-{year}"
    if len(text) == 6 and text.isdigit():
        day, month, year = text[:2], text[2:4], text[4:]
        return f"{day}-{month}-20{year}"
    raise BrokerError("Delta option expiry must be DD-MM-YYYY, YYYY-MM-DD, or YYMMDD", broker_id=BROKER_ID)


def to_place_payload(
    order: Any, *, reduce_only: bool = False, native: Mapping[str, Any] | None = None
) -> dict[str, Any]:
    """Map a FlintTrade order onto CreateOrderRequest. Size is contract count."""
    if type(reduce_only) is not bool:
        raise BrokerError("Delta reduce_only must be an explicit boolean", broker_id=BROKER_ID)
    variety = str(getattr(order, "variety", "regular") or "regular").lower()
    if variety in {"", "regular"} and any(
        _price_text(getattr(order, field, None)) for field in ("target_price", "trailing_jump")
    ):
        raise BrokerError("Delta canonical protection intent requires the bracket resource", broker_id=BROKER_ID)
    if native is None:
        for field in (
            "native", "post_only", "client_order_id", "stop_order_type", "stop_price", "trail_amount",
            "stop_trigger_method", "bracket_stop_loss_limit_price", "bracket_take_profit_limit_price",
            "bracket_stop_trigger_method", "reduce_only",
        ):
            if getattr(order, field, None) is not None:
                raise BrokerError(f"Delta {field} needs explicit native intent, not an unsigned order attribute", broker_id=BROKER_ID)
    if native is not None:
        from .delta_order_mapping import to_native_place_payload

        try:
            return to_native_place_payload(order, native=native, reduce_only=reduce_only)
        except ValueError as exc:
            raise BrokerError(str(exc), broker_id=BROKER_ID) from exc
    price_type = str(getattr(order, "pricetype", "MARKET") or "MARKET").upper()
    payload: dict[str, Any] = {
        "product_symbol": product_symbol(getattr(order, "symbol", "")),
        "size": contract_size(getattr(order, "quantity", "")),
        "side": _side(getattr(order, "action", "")),
        "time_in_force": time_in_force(getattr(order, "validity", None)),
    }
    limit_price = _price_text(getattr(order, "price", ""))
    trigger = _price_text(getattr(order, "trigger_price", ""))
    protection = _price_text(getattr(order, "stop_loss_price", ""))
    if variety != "bracket" and trigger and protection and Decimal(trigger) != Decimal(protection):
        raise BrokerError("Delta stop price aliases conflict", broker_id=BROKER_ID)
    stop_price = trigger or (protection if variety != "bracket" else "")
    if price_type == "MARKET":
        payload["order_type"] = "market_order"
    elif price_type == "LIMIT":
        if not limit_price:
            raise InvalidPrice("Delta limit orders require a limit price", broker_id=BROKER_ID)
        payload["order_type"] = "limit_order"
        payload["limit_price"] = limit_price
    elif price_type == "SL":
        if not limit_price or not stop_price:
            raise InvalidPrice("Delta stop-limit orders require a limit price and a stop price", broker_id=BROKER_ID)
        payload["order_type"] = "limit_order"
        payload["limit_price"] = limit_price
        payload["stop_order_type"] = "stop_loss_order"
        payload["stop_price"] = stop_price
        payload["stop_trigger_method"] = "mark_price"
    elif price_type in {"SL-M", "SLM"}:
        if not stop_price:
            raise InvalidPrice("Delta stop-market orders require a stop price", broker_id=BROKER_ID)
        payload["order_type"] = "market_order"
        payload["stop_order_type"] = "stop_loss_order"
        payload["stop_price"] = stop_price
        payload["stop_trigger_method"] = "mark_price"
    else:
        raise BrokerError(f"Delta does not support price type {price_type!r}", broker_id=BROKER_ID)

    if variety in {"", "regular"}:
        pass
    elif variety == "bracket":
        target = _price_text(getattr(order, "target_price", ""))
        stop = _price_text(getattr(order, "stop_loss_price", ""))
        if not target and not stop:
            raise BrokerError("Delta bracket orders require a target or stop price", broker_id=BROKER_ID)
        if stop:
            payload["bracket_stop_loss_price"] = stop
            payload["bracket_stop_trigger_method"] = "mark_price"
        if target:
            payload["bracket_take_profit_price"] = target
        trail = _price_text(getattr(order, "trailing_jump", ""))
        if trail:
            payload["bracket_trail_amount"] = trail
    else:
        raise BrokerError(f"Delta does not support order variety {variety!r}", broker_id=BROKER_ID)
    if reduce_only:
        payload["reduce_only"] = True
    return payload


def to_edit_payload(order_id: str, changes: Mapping[str, Any]) -> dict[str, Any]:
    """Map a modify request. Delta requires the order id and a product identity."""
    if not isinstance(changes, Mapping):
        raise BrokerError("Delta order edits must be a mapping", broker_id=BROKER_ID)
    allowed = {
        "product_id", "product_symbol", "symbol", "price", "limit_price", "quantity", "size", "trigger_price",
        "stop_price", "trail_amount", "post_only", "mmp", "action", "exchange", "product", "pricetype", "strategy",
    }
    unknown = set(changes) - allowed
    if unknown:
        raise BrokerError(f"Unsupported Delta edit fields: {', '.join(sorted(map(str, unknown)))}", broker_id=BROKER_ID)
    payload: dict[str, Any] = {"id": _order_id(order_id)}
    symbol = _request_alias(changes, ("product_symbol", "symbol"), product_symbol)
    product_id = changes.get("product_id")
    if symbol is not None and "product_id" in changes:
        raise BrokerError("Delta edits require exactly one product identity", broker_id=BROKER_ID)
    if symbol:
        payload["product_symbol"] = symbol
    elif product_id not in (None, ""):
        payload["product_id"] = _order_id(product_id)
    else:
        raise BrokerError("Delta order edits require product_symbol or product_id", broker_id=BROKER_ID)
    for field, names, convert in (
        ("limit_price", ("limit_price", "price"), _required_price),
        ("size", ("size", "quantity"), contract_size),
        ("stop_price", ("stop_price", "trigger_price"), _required_price),
        ("trail_amount", ("trail_amount",), _required_price),
    ):
        value = _request_alias(changes, names, convert)
        if value is not None:
            payload[field] = value
    if "post_only" in changes:
        if type(changes["post_only"]) is not bool:
            raise BrokerError("Delta post_only must be a boolean", broker_id=BROKER_ID)
        payload["post_only"] = changes["post_only"]
    if "mmp" in changes:
        if changes["mmp"] not in ("disabled", "mmp1", "mmp2", "mmp3", "mmp4", "mmp5"):
            raise BrokerError("Delta mmp is invalid", broker_id=BROKER_ID)
        payload["mmp"] = changes["mmp"]
    return payload


def to_cancel_payload(order_id: str, *, product_id: int | None = None) -> dict[str, Any]:
    payload: dict[str, Any] = {"id": _order_id(order_id)}
    if product_id is not None:
        payload["product_id"] = _order_id(product_id)
    return payload


def validate_create_payload(payload: Mapping[str, Any] | None) -> None:
    """Validate native order intent before signing; never invent a product tick."""
    if not isinstance(payload, Mapping):
        raise BrokerError("Delta create body must be a mapping", broker_id=BROKER_ID)
    allowed = {
        "product_id", "product_symbol", "size", "side", "order_type", "time_in_force", "limit_price",
        "stop_order_type", "stop_price", "trail_amount", "stop_trigger_method", "bracket_stop_trigger_method",
        "bracket_stop_loss_price", "bracket_stop_loss_limit_price", "bracket_take_profit_price",
        "bracket_take_profit_limit_price", "bracket_trail_amount", "mmp", "post_only", "reduce_only",
        "client_order_id", "cancel_orders_accepted",
    }
    unknown = set(payload) - allowed
    if unknown:
        raise BrokerError(f"Unsupported Delta create fields: {', '.join(sorted(map(str, unknown)))}", broker_id=BROKER_ID)
    identities = {"product_id", "product_symbol"}.intersection(payload)
    if len(identities) != 1:
        raise BrokerError("Delta create requires exactly one product identity", broker_id=BROKER_ID)
    if "product_id" in identities:
        _order_id(payload["product_id"])
    else:
        product_symbol(payload["product_symbol"])
    contract_size(payload.get("size"))
    if payload.get("side") not in ("buy", "sell"):
        raise BrokerError("Delta native side must be buy or sell", broker_id=BROKER_ID)
    order_type = payload.get("order_type")
    if order_type not in ("market_order", "limit_order"):
        raise BrokerError("Delta native order_type is invalid", broker_id=BROKER_ID)
    if payload.get("time_in_force", "gtc") not in ("gtc", "ioc"):
        raise BrokerError("Delta native time_in_force is invalid", broker_id=BROKER_ID)
    if order_type == "limit_order" and "limit_price" not in payload:
        raise InvalidPrice("Delta limit orders require limit_price", broker_id=BROKER_ID)
    for field in ("reduce_only", "post_only", "cancel_orders_accepted"):
        if field in payload and type(payload[field]) is not bool:
            raise BrokerError(f"Delta {field} must be a boolean", broker_id=BROKER_ID)
    if "mmp" in payload and payload["mmp"] not in ("disabled", "mmp1", "mmp2", "mmp3", "mmp4", "mmp5"):
        raise BrokerError("Delta mmp is invalid", broker_id=BROKER_ID)
    if "client_order_id" in payload:
        value = payload["client_order_id"]
        if not isinstance(value, str) or len(value) > 32:
            raise BrokerError("Delta client_order_id must be a string of at most 32 characters", broker_id=BROKER_ID)
    for field in ("stop_trigger_method", "bracket_stop_trigger_method"):
        if field in payload and payload[field] not in ("mark_price", "last_traded_price", "spot_price"):
            raise BrokerError(f"Delta {field} is invalid", broker_id=BROKER_ID)
    if "stop_order_type" in payload:
        if payload["stop_order_type"] not in ("stop_loss_order", "take_profit_order"):
            raise BrokerError("Delta stop_order_type is invalid", broker_id=BROKER_ID)
        if "stop_price" not in payload and "trail_amount" not in payload:
            raise InvalidPrice("Delta conditional orders require stop_price or trail_amount", broker_id=BROKER_ID)
    elif {"stop_price", "trail_amount", "stop_trigger_method"}.intersection(payload):
        raise BrokerError("Delta conditional fields require stop_order_type", broker_id=BROKER_ID)
    for field in (
        "limit_price", "stop_price", "trail_amount", "bracket_stop_loss_price", "bracket_take_profit_price",
        "bracket_trail_amount", "bracket_stop_loss_limit_price", "bracket_take_profit_limit_price",
    ):
        if field in payload:
            _required_price(payload[field])


def validate_contract_payload(payload: Mapping[str, Any], *, tick_size: str) -> None:
    """Apply the companion's exact tick check at the existing mapper boundary."""
    from .delta_order_mapping import validate_contract_payload as validate

    try:
        validate(payload, tick_size=tick_size)
    except ValueError as exc:
        raise BrokerError(str(exc), broker_id=BROKER_ID) from exc


def to_order_bracket_edit_payload(order_id: str, changes: Mapping[str, Any]) -> dict[str, Any]:
    """Retain the flat, order-attached bracket schema and existing error taxonomy."""
    from .delta_order_mapping import to_order_bracket_edit_payload as build

    try:
        return build(order_id, changes)
    except ValueError as exc:
        raise BrokerError(str(exc), broker_id=BROKER_ID) from exc


def to_position_bracket_create_payload(request: Mapping[str, Any]) -> dict[str, Any]:
    """Retain nested position creation. No position-modification contract is known."""
    from .delta_order_mapping import to_position_bracket_create_payload as build

    try:
        return build(request)
    except ValueError as exc:
        raise BrokerError(str(exc), broker_id=BROKER_ID) from exc


def _order_id(raw: Any) -> int:
    if isinstance(raw, bool) or not isinstance(raw, (str, int)):
        raise BrokerError("Delta order/product id must be a positive integer", broker_id=BROKER_ID)
    text = str(raw)
    if not text or any(char not in "0123456789" for char in text):
        raise BrokerError("Delta order/product id must be a positive integer", broker_id=BROKER_ID)
    try:
        value = int(text)
    except (TypeError, ValueError) as exc:
        raise BrokerError("Delta order id must be an integer", broker_id=BROKER_ID) from exc
    if value <= 0:
        raise BrokerError("Delta order/product id must be a positive integer", broker_id=BROKER_ID)
    return value


def _status(state: Any) -> str:
    if not isinstance(state, str):
        return "UNKNOWN"
    return {
        "open": "OPEN",
        "pending": "PENDING",
        "cancelled": "CANCELLED",
        "canceled": "CANCELLED",
    }.get(state, "UNKNOWN")


def _price_type(row: Mapping[str, Any]) -> str:
    if row.get("stop_order_type") and str(row.get("order_type")) == "market_order":
        return "SL-M"
    if row.get("stop_order_type"):
        return "SL"
    if str(row.get("order_type")) == "market_order":
        return "MARKET"
    return "LIMIT" if row.get("order_type") == "limit_order" else "UNKNOWN"


def contract_evidence(raw: Any, *, positive: bool = False, signed: bool = False) -> int:
    """Read an exact contract count. Signed position evidence is not an order total."""
    if isinstance(raw, bool) or not isinstance(raw, (int, str)):
        raise BrokerReadResponseInvalid
    text = str(raw)
    digits = text[1:] if signed and text.startswith("-") else text
    if not digits or any(char not in "0123456789" for char in digits):
        raise BrokerReadResponseInvalid
    try:
        value = int(text)
    except ValueError as exc:
        raise BrokerReadResponseInvalid from exc
    if (positive and value <= 0) or (not signed and value < 0):
        raise BrokerReadResponseInvalid
    return value


def from_order(row: Mapping[str, Any]) -> dict[str, Any]:
    """Normalise observed counts only; preserve detached native execution evidence."""
    if not isinstance(row, Mapping):
        raise BrokerReadResponseInvalid
    native = deepcopy(dict(row))
    result = {
        "orderid": str(row.get("id") or ""),
        "symbol": str(row.get("product_symbol") or ""),
        "exchange": "CRYPTO",
        "product": "MARGIN",
        "action": str(row.get("side") or "").upper(),
        "price_type": _price_type(row),
        "status": _status(row.get("state")),
        "product_id": row.get("product_id"),
        "raw_status": native.get("state"),
        "quantity_unit": "contracts",
        "native": native,
    }
    size = contract_evidence(row["size"], positive=True) if "size" in row else None
    unfilled = contract_evidence(row["unfilled_size"]) if "unfilled_size" in row else None
    if size is not None:
        result["quantity"] = str(size)
    if unfilled is not None:
        result["remaining_quantity"] = str(unfilled)
    if size is not None and unfilled is not None:
        if unfilled > size:
            raise BrokerReadResponseInvalid
        result["filled_quantity"] = str(size - unfilled)
        if row.get("state") == "closed" and unfilled == 0:
            result["status"] = "COMPLETE"
    result["attempt_state"] = {
        "OPEN": "WORKING", "CANCELLED": "CANCELLED", "COMPLETE": "FILLED",
    }.get(result["status"], "UNKNOWN")
    for field, source in (("price", "limit_price"), ("trigger_price", "stop_price"),
                          ("average_price", "average_fill_price")):
        if source in row and row[source] not in (None, ""):
            result[field] = str(row[source])
    return result


def from_position(row: Mapping[str, Any]) -> dict[str, Any]:
    if not isinstance(row, Mapping):
        raise BrokerReadResponseInvalid
    size = contract_evidence(row.get("size"), signed=True)
    return {
        "symbol": str(row.get("product_symbol") or ""),
        "exchange": "CRYPTO",
        "product": str(row.get("margin_mode") or "isolated"),
        "quantity": str(size),
        "average_price": str(row.get("entry_price") or "0"),
        "ltp": str(row.get("mark_price") or "0"),
        "pnl": str(row.get("unrealized_pnl") or "0"),
        "product_id": row.get("product_id"),
        "quantity_unit": "contracts",
        "native": deepcopy(dict(row)),
    }


def from_fill(row: Mapping[str, Any]) -> dict[str, Any]:
    if not isinstance(row, Mapping):
        raise BrokerReadResponseInvalid
    size = contract_evidence(row.get("size"), positive=True)
    return {
        "orderid": str(row.get("order_id") or ""),
        "symbol": str(row.get("product_symbol") or ""),
        "exchange": "CRYPTO",
        "action": str(row.get("side") or "").upper(),
        "quantity": str(size),
        "price": str(row.get("price") or "0"),
        "product": str(row.get("fill_type") or ""),
        "timestamp": str(row.get("created_at") or ""),
        "fill_id": row.get("id"),
        "quantity_unit": "contracts",
        "native": deepcopy(dict(row)),
    }


def from_ticker(row: Mapping[str, Any]) -> dict[str, Any]:
    quotes = row.get("quotes") if isinstance(row.get("quotes"), dict) else {}
    return {
        "symbol": str(row.get("symbol") or ""),
        "exchange": "CRYPTO",
        "ltp": _float(row.get("close") or row.get("mark_price")),
        "open": _float(row.get("open")),
        "high": _float(row.get("high")),
        "low": _float(row.get("low")),
        "close": _float(row.get("close")),
        "volume": int(_float(row.get("volume"))),
        "bid": _float(quotes.get("best_bid")),
        "ask": _float(quotes.get("best_ask")),
        "oi": int(_float(row.get("oi"))),
    }


def _implied_vol(greeks: Mapping[str, Any], quotes: Mapping[str, Any]) -> float:
    """IV lives on the quote, not inside the greeks object."""
    if "iv" in greeks:
        return _float(greeks.get("iv"))
    ask = quotes.get("ask_iv")
    bid = quotes.get("bid_iv")
    if ask not in (None, "") and bid not in (None, ""):
        return (_float(ask) + _float(bid)) / 2
    return _float(ask if ask not in (None, "") else bid)


def _float(raw: Any) -> float:
    try:
        return float(raw)
    except (TypeError, ValueError):
        return 0.0


def funds_from_wallets(rows: Any) -> dict[str, Any]:
    """Project wallet rows without summing mixed assets."""
    wallets = [row for row in rows if isinstance(row, dict)] if isinstance(rows, list) else []
    chosen: dict[str, Any] = {}
    for symbol in ("USD", "USDT", "INR"):
        match = next((row for row in wallets if row.get("asset_symbol") == symbol), None)
        if match is not None:
            chosen = match
            break
    if not chosen and wallets:
        chosen = wallets[0]
    return {
        "available_balance": str(chosen.get("available_balance") or "0"),
        "used_margin": str(chosen.get("blocked_margin") or "0"),
        "total_balance": str(chosen.get("balance") or "0"),
        "asset_symbol": str(chosen.get("asset_symbol") or ""),
        "wallets": wallets,
    }


def option_chain_from_tickers(rows: Any, *, underlying: str, expiry: str) -> dict[str, Any]:
    """Fold call and put tickers into strike rows. Missing greeks stay zero."""
    by_strike: dict[float, dict[str, Any]] = {}
    spot = 0.0
    for row in rows if isinstance(rows, list) else []:
        if not isinstance(row, dict):
            continue
        strike = _float(row.get("strike_price"))
        if strike <= 0:
            continue
        spot = spot or _float(row.get("spot_price"))
        bucket = by_strike.setdefault(strike, {"strike_price": strike})
        contract = str(row.get("contract_type") or row.get("symbol") or "").lower()
        prefix = "ce" if "call" in contract or str(row.get("symbol") or "").startswith("C-") else "pe"
        greeks_raw = row.get("greeks")
        quotes_raw = row.get("quotes")
        greeks: dict[str, Any] = greeks_raw if isinstance(greeks_raw, dict) else {}
        quotes: dict[str, Any] = quotes_raw if isinstance(quotes_raw, dict) else {}
        bucket[f"{prefix}_instrument_id"] = str(row.get("symbol") or "")
        bucket[f"{prefix}_ltp"] = _float(row.get("close") or row.get("mark_price"))
        bucket[f"{prefix}_oi"] = int(_float(row.get("oi")))
        bucket[f"{prefix}_volume"] = int(_float(row.get("volume")))
        bucket[f"{prefix}_iv"] = _implied_vol(greeks, quotes)
        bucket[f"{prefix}_delta"] = _float(greeks.get("delta"))
        bucket[f"{prefix}_gamma"] = _float(greeks.get("gamma"))
        bucket[f"{prefix}_theta"] = _float(greeks.get("theta"))
        bucket[f"{prefix}_vega"] = _float(greeks.get("vega"))
        bucket[f"{prefix}_bid"] = _float(quotes.get("best_bid"))
        bucket[f"{prefix}_ask"] = _float(quotes.get("best_ask"))
        bucket[f"{prefix}_greeks_complete"] = all(name in greeks for name in ("delta", "gamma", "theta", "vega")) and (
            "iv" in greeks or "ask_iv" in quotes or "bid_iv" in quotes
        )
    return {
        "underlying": underlying,
        "underlying_key": underlying,
        "exchange": "CRYPTO",
        "expiry": expiry,
        "expiry_date": expiry,
        "spot_price": spot,
        "strikes": [by_strike[key] for key in sorted(by_strike)],
    }
