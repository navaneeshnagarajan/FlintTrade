"""Pure FlintTrade <-> Upstox v2/v3 mapping.

Kept separate from the adapter so order translation and response parsing are
fully unit-testable without the upstox-python SDK or live credentials. Field
names / enum codes follow the Upstox v2 and v3 APIs (request fields verified
against the staged SDK models: ``PlaceOrderRequest``, ``PlaceOrderV3Request``,
``MultiOrderRequest``, ``GttPlaceOrderRequest``/``GttModifyOrderRequest``/
``GttCancelOrderRequest``, ``ConvertPositionRequest`` and the ChargeApi /
MarketQuoteV3Api / TradeProfitAndLossApi query parameters).
"""

from __future__ import annotations

import json
from typing import Any
from urllib.parse import urlencode

from flinttrade_core.exceptions import (
    BrokerError,
    InsufficientFunds,
    InvalidPrice,
    InvalidQuantity,
    OrderRejectedByBroker,
    RateLimitError,
    SessionExpired,
)

# Exchange → Upstox segment code (instrument-token prefix / quote segment).
EXCHANGE_TO_UPSTOX = {
    "NSE": "NSE_EQ",
    "BSE": "BSE_EQ",
    "NFO": "NSE_FO",
    "BFO": "BSE_FO",
    "CDS": "NSE_CD",
    "BCD": "BSE_CD",
    "MCX": "MCX_FO",
    "NSE_INDEX": "NSE_INDEX",
    "BSE_INDEX": "BSE_INDEX",
}
UPSTOX_TO_EXCHANGE = {v: k for k, v in EXCHANGE_TO_UPSTOX.items()}

# FlintTrade product → Upstox product. Upstox uses I (Intraday) / D (Delivery);
# carry-forward F&O (NRML) maps to D.
PRODUCT_TO_UPSTOX = {"MIS": "I", "CNC": "D", "NRML": "D"}
UPSTOX_TO_PRODUCT = {"I": "MIS", "D": "CNC", "MTF": "NRML", "CO": "MIS", "OCO": "MIS"}

ORDER_TYPE_TO_UPSTOX = {"MARKET": "MARKET", "LIMIT": "LIMIT", "SL": "SL", "SL-M": "SL-M"}
UPSTOX_TO_ORDER_TYPE = {v: k for k, v in ORDER_TYPE_TO_UPSTOX.items()}

SIDE_TO_UPSTOX = {"BUY": "BUY", "SELL": "SELL"}

# Upstox order validity (PlaceOrderRequest.validity): DAY (default) or IOC.
# Anything else (GTC/GTD/EOS) is not accepted by the place/modify endpoints.
UPSTOX_VALIDITIES = frozenset({"DAY", "IOC"})


class UpstoxMappingError(ValueError):
    """Raised when an order cannot be translated to / from the Upstox API."""


def _validated_validity(validity: Any) -> str:
    """Validate an order's validity against the Upstox-accepted set.

    Args:
        validity: The FlintTrade ``Order.validity`` (``None`` keeps the Upstox
            default of ``DAY``); ``DAY``/``IOC`` pass through.

    Returns:
        The Upstox validity code (``"DAY"`` or ``"IOC"``).

    Raises:
        UpstoxMappingError: If ``validity`` is set to an unsupported value.
    """
    if validity is None or str(validity).strip() == "":
        return "DAY"
    code = str(validity).strip().upper()
    if code not in UPSTOX_VALIDITIES:
        raise UpstoxMappingError(
            f"Upstox supports only DAY/IOC validity, got {validity!r}"
        )
    return code


def _num(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _norm_pricetype(pricetype: str) -> str:
    return str(pricetype).upper()


def _validated_core(order: Any, instrument_token: str) -> dict[str, Any]:
    """Validate the shared order enums and return the common Upstox fields."""
    side = str(order.action).upper()
    if side not in SIDE_TO_UPSTOX:
        raise UpstoxMappingError(f"Unsupported action {side!r}")
    ptype = _norm_pricetype(getattr(order, "pricetype", "MARKET"))
    if ptype not in ORDER_TYPE_TO_UPSTOX:
        raise UpstoxMappingError(f"Unsupported pricetype {ptype!r}")
    product = str(order.product).upper()
    if product not in PRODUCT_TO_UPSTOX:
        raise UpstoxMappingError(f"Unsupported product {product!r}")
    return {
        "instrument_token": str(instrument_token),
        "quantity": int(_num(order.quantity, 0)),
        "product": PRODUCT_TO_UPSTOX[product],
        "validity": _validated_validity(getattr(order, "validity", None)),
        "price": _num(getattr(order, "price", 0)),
        "order_type": ORDER_TYPE_TO_UPSTOX[ptype],
        "transaction_type": SIDE_TO_UPSTOX[side],
        "disclosed_quantity": int(_num(getattr(order, "disclosed_quantity", 0), 0)),
        "trigger_price": _num(getattr(order, "trigger_price", 0)),
    }


def to_place_order_params(order: Any, instrument_token: str, *, tag: str | None = None) -> dict[str, Any]:
    """Translate a FlintTrade ``Order`` into Upstox ``PlaceOrderRequest`` kwargs.

    ``instrument_token`` is resolved by the adapter (Upstox trades by instrument
    token, e.g. ``"NSE_EQ|INE002A01018"``). Raises for unmappable enum values.
    An ``"amo"`` variety places the same payload flagged After Market Order.
    """
    # Safety: Upstox v2 does not expose bracket/cover via place_order (bracket
    # was retired); GTT and sliced (iceberg) orders use the dedicated v3
    # endpoints, dispatched by the adapter BEFORE this builder is called. Refuse
    # an advanced variety here rather than silently placing it as a plain order —
    # a bracket order that quietly loses its stop-loss leg would be a real risk.
    variety = str(getattr(order, "variety", "regular")).lower()
    if variety not in ("regular", "amo", ""):
        raise UpstoxMappingError(
            f"Upstox does not place variety {variety!r} via place_order "
            "(GTT/sliced orders use the v3 endpoints; bracket/cover were retired)"
        )

    params = _validated_core(order, instrument_token)
    params.update({"is_amo": variety == "amo", "tag": tag or ""})
    return params


def to_place_order_v3_params(order: Any, instrument_token: str, *, tag: str | None = None) -> dict[str, Any]:
    """Translate an ``iceberg`` (sliced) ``Order`` into ``PlaceOrderV3Request`` kwargs.

    The v3 place endpoint slices an over-freeze-quantity order into exchange-
    defined legs server-side when ``slice`` is true — Upstox's iceberg
    equivalent. AMO is carried through; bracket/cover/GTT are refused (GTT has
    its own builder; bracket/cover were retired by Upstox).
    """
    variety = str(getattr(order, "variety", "regular")).lower()
    if variety not in ("regular", "amo", "iceberg", ""):
        raise UpstoxMappingError(f"Upstox v3 place does not support variety {variety!r}")
    params = _validated_core(order, instrument_token)
    params.update({
        "is_amo": variety == "amo",
        "slice": variety == "iceberg",
        "tag": tag or "",
    })
    return params


def to_multi_order_params(
    orders_with_tokens: list[tuple[Any, str]], *, tag: str | None = None
) -> list[dict[str, Any]]:
    """Translate a basket of ``(Order, instrument_token)`` pairs into the Upstox
    ``MultiOrderRequest`` payload list (one dict per order, ``correlation_id``
    assigned positionally so per-order errors map back to the input)."""
    if not orders_with_tokens:
        raise UpstoxMappingError("Multi-order needs at least one order")
    payloads: list[dict[str, Any]] = []
    for i, (order, token) in enumerate(orders_with_tokens):
        variety = str(getattr(order, "variety", "regular")).lower()
        if variety not in ("regular", "amo", "iceberg", ""):
            raise UpstoxMappingError(f"Upstox multi-order does not support variety {variety!r}")
        params = _validated_core(order, token)
        params.update({
            "is_amo": variety == "amo",
            "slice": variety == "iceberg",
            "tag": tag or "",
            "correlation_id": str(i + 1),
        })
        payloads.append(params)
    return payloads


def to_margin_instrument(order: Any, instrument_token: str) -> dict[str, Any]:
    """Build one Upstox margin-request instrument from an ``Order`` (pre-trade)."""
    product = str(order.product).upper()
    if product not in PRODUCT_TO_UPSTOX:
        raise UpstoxMappingError(f"Unsupported product {product!r}")
    side = str(order.action).upper()
    if side not in SIDE_TO_UPSTOX:
        raise UpstoxMappingError(f"Unsupported action {side!r}")
    return {
        "instrument_key": str(instrument_token),
        "quantity": int(_num(order.quantity, 0)),
        "product": PRODUCT_TO_UPSTOX[product],
        "transaction_type": SIDE_TO_UPSTOX[side],
        "price": _num(getattr(order, "price", 0)),
    }


def from_upstox_margin(resp: dict[str, Any]) -> dict[str, Any]:
    """Normalise an Upstox ``post_margin`` response into FlintTrade margin fields."""
    data = resp.get("data", resp) if isinstance(resp, dict) else {}
    if not isinstance(data, dict):
        data = {}
    return {
        "required_margin": str(data.get("required_margin", 0)),
        "final_margin": str(data.get("final_margin", 0)),
        "available_balance": "0",  # Upstox margin response carries no balance; merge from funds()
        "extra": data,
    }


def to_modify_order_params(order_id: str, changes: dict[str, Any]) -> dict[str, Any]:
    """Translate modify ``changes`` into Upstox ``ModifyOrderRequest`` kwargs."""
    ptype = _norm_pricetype(changes.get("pricetype", changes.get("order_type", "LIMIT")))
    return {
        "order_id": str(order_id),
        "order_type": ORDER_TYPE_TO_UPSTOX.get(ptype, str(changes.get("order_type", "LIMIT"))),
        "quantity": int(_num(changes.get("quantity", 0), 0)),
        "price": _num(changes.get("price", 0)),
        "trigger_price": _num(changes.get("trigger_price", 0)),
        "disclosed_quantity": int(_num(changes.get("disclosed_quantity", 0), 0)),
        "validity": _validated_validity(changes.get("validity")),
    }


def _exchange_of_token(instrument_token: str) -> str:
    seg = str(instrument_token).split("|", 1)[0]
    return UPSTOX_TO_EXCHANGE.get(seg, seg)


# FlintTrade exchanges whose ``D`` product is carry-forward F&O (NRML), not
# delivery (CNC). Both NRML and CNC map to Upstox ``D`` on the way out, so the
# read side disambiguates ``D`` by the instrument's segment.
_DERIVATIVE_EXCHANGES = frozenset({"NFO", "BFO", "CDS", "BCD", "MCX"})


def _product_from_upstox(code: str, exchange: str, segment: str = "") -> str:
    """Map an Upstox product code back to a FlintTrade product.

    ``I``/``MTF``/``CO``/``OCO`` are unambiguous, but Upstox collapses both
    carry-forward F&O (``NRML``) and equity delivery (``CNC``) into ``D``. The
    forward map therefore cannot be inverted blindly: an F&O ``D`` position read
    back as ``CNC`` would feed reconciliation the wrong product. Disambiguate
    ``D`` by the instrument's segment — a derivative segment means ``NRML``,
    everything else means ``CNC``.

    Args:
        code: The Upstox product code from the order/position record.
        exchange: The FlintTrade exchange (resolved from the instrument token).
        segment: The Upstox segment code (e.g. ``"NSE_FO"``), used as a fallback
            when the exchange alone is ambiguous.

    Returns:
        The FlintTrade product name (``MIS``/``CNC``/``NRML``).
    """
    upstox_code = str(code).upper()
    if upstox_code != "D":
        return UPSTOX_TO_PRODUCT.get(upstox_code, upstox_code)
    exch = str(exchange).upper()
    seg = str(segment).upper()
    is_derivative = exch in _DERIVATIVE_EXCHANGES or any(
        marker in seg for marker in ("_FO", "_CD", "_COM")
    )
    return "NRML" if is_derivative else "CNC"


def extract_order_id(resp: dict[str, Any]) -> str:
    """Pull the order id from an Upstox place/modify response.

    Upstox returns ``{"status": "success", "data": {"order_ids": ["..."]}}``
    (and singular ``order_id`` on some endpoints).
    """
    if not isinstance(resp, dict):
        raise UpstoxMappingError(f"Unexpected Upstox response: {resp!r}")
    data = resp.get("data", resp)
    if isinstance(data, dict):
        ids = data.get("order_ids")
        if isinstance(ids, list) and ids:
            return str(ids[0])
        oid = data.get("order_id")
        if oid:
            return str(oid)
    raise UpstoxMappingError(f"No order id in Upstox response: {resp!r}")


def from_upstox_order(d: dict[str, Any]) -> dict[str, Any]:
    """Normalise an Upstox order-book record."""
    exchange = d.get("exchange", _exchange_of_token(d.get("instrument_token", "")))
    return {
        "orderid": str(d.get("order_id", "")),
        "status": d.get("status", ""),
        "symbol": d.get("trading_symbol", d.get("tradingsymbol", "")),
        "exchange": exchange,
        "action": d.get("transaction_type", ""),
        "pricetype": UPSTOX_TO_ORDER_TYPE.get(d.get("order_type", ""), d.get("order_type", "")),
        "product": _product_from_upstox(d.get("product", ""), exchange, d.get("segment", "")),
        "quantity": str(d.get("quantity", 0)),
        "price": str(d.get("price", 0)),
        "trigger_price": str(d.get("trigger_price", 0)),
        "filled_quantity": str(d.get("filled_quantity", 0)),
        "average_price": str(d.get("average_price", 0)),
    }


def from_upstox_position(d: dict[str, Any]) -> dict[str, Any]:
    """Normalise an Upstox position record."""
    exchange = d.get("exchange", _exchange_of_token(d.get("instrument_token", "")))
    return {
        "symbol": d.get("trading_symbol", d.get("tradingsymbol", "")),
        "exchange": exchange,
        "product": _product_from_upstox(d.get("product", ""), exchange, d.get("segment", "")),
        "quantity": str(d.get("quantity", 0)),
        "average_price": str(d.get("average_price", d.get("buy_price", 0))),
        "ltp": str(d.get("last_price", 0)),
        "pnl": str(d.get("pnl", 0)),
    }


def from_upstox_holding(d: dict[str, Any]) -> dict[str, Any]:
    """Normalise an Upstox holding record."""
    return {
        "symbol": d.get("trading_symbol", d.get("tradingsymbol", "")),
        "exchange": d.get("exchange", ""),
        "quantity": str(d.get("quantity", 0)),
        "average_price": str(d.get("average_price", 0)),
        "ltp": str(d.get("last_price", 0)),
        "pnl": str(d.get("pnl", 0)),
    }


def from_upstox_trade(d: dict[str, Any]) -> dict[str, Any]:
    """Normalise an Upstox trade record."""
    return {
        "orderid": str(d.get("order_id", "")),
        "symbol": d.get("trading_symbol", d.get("tradingsymbol", "")),
        "exchange": d.get("exchange", _exchange_of_token(d.get("instrument_token", ""))),
        "action": d.get("transaction_type", ""),
        "quantity": str(d.get("quantity", 0)),
        "price": str(d.get("average_price", d.get("price", 0))),
        "product": _product_from_upstox(
            d.get("product", ""), d.get("exchange", _exchange_of_token(d.get("instrument_token", ""))),
            d.get("segment", ""),
        ),
        "timestamp": str(d.get("order_timestamp", d.get("exchange_timestamp", ""))),
    }


def from_upstox_funds(resp: dict[str, Any]) -> dict[str, Any]:
    """Normalise the Upstox fund-and-margin response.

    Upstox returns ``data: {"equity": {available_margin, used_margin, ...},
    "commodity": {...}}``. We surface the equity segment with the raw payload.
    """
    data = resp.get("data", resp) if isinstance(resp, dict) else {}
    equity = data.get("equity", {}) if isinstance(data, dict) else {}
    available = equity.get("available_margin", 0)
    used = equity.get("used_margin", 0)
    return {
        "available_balance": str(available),
        "used_margin": str(used),
        "total_balance": str(_num(available) + _num(used)),
        "extra": data,
    }


# ---------------------------------------------------------------------------
# Market data (quotes / historical candles / option chain)
# ---------------------------------------------------------------------------

# FlintTrade interval suffix -> Upstox v3 history (unit, interval) pair.
# v3 ``get_historical_candle_data1(instrument_key, unit, interval, to, from)``
# takes unit in {seconds, minutes, hours, days, weeks, months} + a numeric
# interval ("1s" reaches the v3 one-second candles).
_UNIT_BY_SUFFIX = {"s": "seconds", "m": "minutes", "h": "hours", "d": "days", "w": "weeks", "mo": "months"}


def to_history_params(req: dict[str, Any]) -> dict[str, Any]:
    """Translate a FlintTrade historical ``req`` into Upstox v3 history kwargs.

    Accepts ``interval`` like ``"1m"``, ``"3m"``, ``"15m"``, ``"1h"``, ``"1d"``,
    ``"1w"``, ``"1mo"`` (or bare ``"day"``/``"week"``/``"month"``). Returns the
    ``instrument_key`` (resolved by the adapter), ``unit``, ``interval`` (number
    as string) and the ``to_date``/``from_date`` window.
    """
    raw = str(req.get("interval", req.get("timeframe", "1d"))).strip().lower()
    named = {"day": ("days", "1"), "week": ("weeks", "1"), "month": ("months", "1")}
    if raw in named:
        unit, interval = named[raw]
    else:
        digits = "".join(c for c in raw if c.isdigit()) or "1"
        suffix = "".join(c for c in raw if c.isalpha()) or "d"
        unit = _UNIT_BY_SUFFIX.get(suffix, "days")
        interval = digits
    return {
        "instrument_key": str(req.get("instrument_key", "")),
        "unit": unit,
        "interval": interval,
        "to_date": req.get("to_date") or req.get("end") or req.get("end_date"),
        "from_date": req.get("from_date") or req.get("start") or req.get("start_date"),
    }


def from_upstox_candles(symbol: str, exchange: str, interval: str, resp: dict[str, Any]) -> dict[str, Any]:
    """Parse an Upstox history response into a FlintTrade ``Candles`` dict.

    Upstox returns ``data.candles`` as arrays ordered
    ``[timestamp, open, high, low, close, volume, open_interest]`` (newest first).
    """
    data = resp.get("data", {}) if isinstance(resp, dict) else {}
    rows = data.get("candles", []) if isinstance(data, dict) else []
    bars: list[dict[str, Any]] = []
    for row in rows:
        if not isinstance(row, (list, tuple)) or len(row) < 5:
            continue
        bars.append({
            "timestamp": str(row[0]),
            "open": _num(row[1]),
            "high": _num(row[2]),
            "low": _num(row[3]),
            "close": _num(row[4]),
            "volume": int(_num(row[5])) if len(row) > 5 else 0,
        })
    return {"symbol": symbol, "exchange": exchange, "interval": interval, "bars": bars}


def from_upstox_quote(rec: dict[str, Any]) -> dict[str, Any]:
    """Parse one Upstox full-market-quote record into a FlintTrade ``Quote`` dict.

    The full-quote payload keys each instrument by ``"EXCHANGE_SEG:SYMBOL"`` but
    every record also carries its own ``symbol`` + ``instrument_token``, so the
    record alone is enough. Bid/ask come from the top depth level.
    """
    ohlc = rec.get("ohlc", {}) if isinstance(rec.get("ohlc"), dict) else {}
    depth = rec.get("depth", {}) if isinstance(rec.get("depth"), dict) else {}
    buy = depth.get("buy", []) if isinstance(depth.get("buy"), list) else []
    sell = depth.get("sell", []) if isinstance(depth.get("sell"), list) else []
    bid = _num(buy[0].get("price")) if buy and isinstance(buy[0], dict) else 0.0
    ask = _num(sell[0].get("price")) if sell and isinstance(sell[0], dict) else 0.0
    return {
        "symbol": rec.get("symbol", ""),
        "exchange": _exchange_of_token(rec.get("instrument_token", "")),
        "ltp": _num(rec.get("last_price")),
        "open": _num(ohlc.get("open")),
        "high": _num(ohlc.get("high")),
        "low": _num(ohlc.get("low")),
        "close": _num(ohlc.get("close")),
        "volume": int(_num(rec.get("volume"))),
        "bid": bid,
        "ask": ask,
        "prev_close": _num(ohlc.get("close")),
        "oi": int(_num(rec.get("oi"))),
    }


def _upstox_depth_levels(rows: Any) -> list[dict[str, Any]]:
    levels: list[dict[str, Any]] = []
    if not isinstance(rows, list):
        return levels
    for row in rows:
        if not isinstance(row, dict):
            continue
        levels.append({
            "price": _num(row.get("price")),
            "quantity": int(_num(row.get("quantity"))),
            "orders": int(_num(row.get("orders"))),
        })
    return levels


def from_upstox_depth(rec: dict[str, Any]) -> dict[str, Any]:
    """Parse one Upstox full-quote record into a FlintTrade depth ladder."""
    depth = rec.get("depth", {}) if isinstance(rec.get("depth"), dict) else {}
    return {
        "symbol": rec.get("symbol", ""),
        "exchange": _exchange_of_token(rec.get("instrument_token", "")),
        "bids": _upstox_depth_levels(depth.get("buy")),
        "asks": _upstox_depth_levels(depth.get("sell")),
    }


# ---------------------------------------------------------------------------
# Auth (OAuth 2.0 — login dialog URL + token-exchange form)
# ---------------------------------------------------------------------------

UPSTOX_LOGIN_DIALOG_URL = "https://api.upstox.com/v2/login/authorization/dialog"
UPSTOX_TOKEN_URL = "https://api.upstox.com/v2/login/authorization/token"


def build_login_url(client_id: str, redirect_uri: str, state: str | None = None) -> str:
    """Build the Upstox OAuth login-dialog URL (authentication doc, v2).

    The operator opens this in a browser; Upstox redirects back to
    ``redirect_uri`` with the single-use ``code`` query parameter.
    """
    if not client_id or not redirect_uri:
        raise UpstoxMappingError("Upstox login URL needs client_id (API key) and redirect_uri")
    query: dict[str, str] = {
        "response_type": "code",
        "client_id": client_id,
        "redirect_uri": redirect_uri,
    }
    if state:
        query["state"] = state
    return f"{UPSTOX_LOGIN_DIALOG_URL}?{urlencode(query)}"


def to_token_request_params(credentials: dict[str, Any]) -> dict[str, str]:
    """Build the token-exchange form fields (``POST /v2/login/authorization/token``).

    Requires the single-use auth ``code`` plus the app's API key/secret and the
    registered redirect URI; ``grant_type`` is always ``authorization_code``.
    """
    code = str(credentials.get("code") or "")
    client_id = str(credentials.get("api_key") or credentials.get("client_id") or "")
    client_secret = str(credentials.get("api_secret") or credentials.get("client_secret") or "")
    redirect_uri = str(credentials.get("redirect_uri") or "")
    if not (code and client_id and client_secret and redirect_uri):
        raise UpstoxMappingError(
            "Upstox token exchange needs code, api_key, api_secret and redirect_uri"
        )
    return {
        "code": code,
        "client_id": client_id,
        "client_secret": client_secret,
        "redirect_uri": redirect_uri,
        "grant_type": "authorization_code",
    }


def extract_access_token(resp: dict[str, Any]) -> str:
    """Pull the ``access_token`` out of an Upstox token-exchange response."""
    data = resp.get("data", resp) if isinstance(resp, dict) else {}
    token = str((data or {}).get("access_token", "")) if isinstance(data, dict) else ""
    if not token:
        raise UpstoxMappingError(f"No access_token in Upstox token response: {resp!r}")
    return token


# ---------------------------------------------------------------------------
# GTT orders (v3 /order/gtt — place / modify / cancel / details)
# ---------------------------------------------------------------------------


# GttRule.trigger_type enum (SDK model): ABOVE / BELOW / IMMEDIATE. Upstox's
# place/modify GTT examples use ABOVE for ENTRY and IMMEDIATE for TARGET and
# STOPLOSS. ENTRY can be overridden by callers that need BELOW/IMMEDIATE.
_GTT_TRIGGER_TYPES = frozenset({"ABOVE", "BELOW", "IMMEDIATE"})
_GTT_PROTECTIVE_TRIGGER_TYPES = frozenset({"IMMEDIATE"})


def _gtt_trigger_type(override: Any, *, allowed: frozenset[str] = _GTT_TRIGGER_TYPES, default: str) -> str:
    """Resolve a GTT ``trigger_type`` with an allow-list and default."""
    if override is not None and str(override).strip():
        code = str(override).strip().upper()
        if code not in allowed:
            raise UpstoxMappingError(
                f"Upstox GTT trigger_type must be one of {sorted(allowed)}, "
                f"got {override!r}"
            )
        return code
    return default


def _entry_trigger_override(order: Any) -> Any:
    """Return the ENTRY trigger override from current or legacy field names."""
    for field in ("entry_trigger_type", "gtt_entry_trigger_type", "trigger_type"):
        value = getattr(order, field, None)
        if value is not None and str(value).strip():
            return value
    return None


def _gtt_rules(order: Any, side: str = "BUY") -> tuple[str, list[dict[str, Any]]]:
    """Build the GTT rule list from an ``Order``'s trigger/leg prices.

    ``trigger_price`` is the ENTRY rule (mandatory); ``stop_loss_price`` and
    ``target_price`` add STOPLOSS / TARGET rules, upgrading the GTT to MULTIPLE.

    Upstox models ENTRY, TARGET and STOPLOSS as separate ``GttRule`` rows. The
    current v3 examples use ``trigger_type=ABOVE`` for ENTRY and
    ``trigger_type=IMMEDIATE`` for TARGET/STOPLOSS; the latter two are therefore
    pinned to IMMEDIATE unless a caller explicitly supplies the same value.
    ``entry_trigger_type`` may be set to ``ABOVE``, ``BELOW`` or ``IMMEDIATE`` to
    express the entry condition.

    Args:
        order: The order (or changes shim) carrying the leg prices and any
            explicit ``*_trigger_type`` overrides.
        side: The entry transaction side (``BUY``/``SELL``); kept for call-site
            readability and future broker-specific validation.

    Returns:
        ``(gtt_type, rules)`` where ``gtt_type`` is ``SINGLE`` or ``MULTIPLE``.
    """
    entry = _num(getattr(order, "trigger_price", 0))
    if entry <= 0:
        raise UpstoxMappingError("An Upstox GTT order needs a trigger_price (the ENTRY rule)")
    rules: list[dict[str, Any]] = [
        {
            "strategy": "ENTRY",
            "trigger_type": _gtt_trigger_type(_entry_trigger_override(order), default="ABOVE"),
            "trigger_price": entry,
        },
    ]
    stop_loss = _num(getattr(order, "stop_loss_price", 0))
    target = _num(getattr(order, "target_price", 0))
    if stop_loss > 0:
        rules.append({
            "strategy": "STOPLOSS",
            "trigger_type": _gtt_trigger_type(
                getattr(order, "stop_loss_trigger_type", None),
                allowed=_GTT_PROTECTIVE_TRIGGER_TYPES,
                default="IMMEDIATE",
            ),
            "trigger_price": stop_loss,
        })
    if target > 0:
        rules.append({
            "strategy": "TARGET",
            "trigger_type": _gtt_trigger_type(
                getattr(order, "target_trigger_type", None),
                allowed=_GTT_PROTECTIVE_TRIGGER_TYPES,
                default="IMMEDIATE",
            ),
            "trigger_price": target,
        })
    return ("MULTIPLE" if len(rules) > 1 else "SINGLE"), rules


def to_gtt_place_params(order: Any, instrument_token: str) -> dict[str, Any]:
    """Translate a ``gtt`` ``Order`` into Upstox ``GttPlaceOrderRequest`` kwargs."""
    side = str(order.action).upper()
    if side not in SIDE_TO_UPSTOX:
        raise UpstoxMappingError(f"Unsupported action {side!r}")
    product = str(order.product).upper()
    if product not in PRODUCT_TO_UPSTOX:
        raise UpstoxMappingError(f"Unsupported product {product!r}")
    gtt_type, rules = _gtt_rules(order, side=side)
    return {
        "type": gtt_type,
        "quantity": int(_num(order.quantity, 0)),
        "product": PRODUCT_TO_UPSTOX[product],
        "rules": rules,
        "instrument_token": str(instrument_token),
        "transaction_type": SIDE_TO_UPSTOX[side],
    }


def to_gtt_modify_params(gtt_order_id: str, changes: dict[str, Any]) -> dict[str, Any]:
    """Translate modify ``changes`` into Upstox ``GttModifyOrderRequest`` kwargs.

    A GTT modify is a full rule replacement: quantity plus the trigger prices
    (``trigger_price`` → ENTRY, ``stop_loss_price``/``target_price`` optional).
    """
    if not gtt_order_id:
        raise UpstoxMappingError("GTT modify needs the gtt_order_id")

    class _Changes:
        trigger_price = changes.get("trigger_price", 0)
        entry_trigger_type = changes.get("entry_trigger_type")
        gtt_entry_trigger_type = changes.get("gtt_entry_trigger_type")
        trigger_type = changes.get("trigger_type")
        stop_loss_price = changes.get("stop_loss_price", 0)
        target_price = changes.get("target_price", 0)
        stop_loss_trigger_type = changes.get("stop_loss_trigger_type")
        target_trigger_type = changes.get("target_trigger_type")

    side = str(changes.get("transaction_type", changes.get("action", "BUY"))).upper()
    gtt_type, rules = _gtt_rules(_Changes, side=side)
    return {
        "type": str(changes.get("type", gtt_type)).upper(),
        "quantity": int(_num(changes.get("quantity", 0), 0)),
        "rules": rules,
        "gtt_order_id": str(gtt_order_id),
    }


def to_gtt_cancel_params(gtt_order_id: str) -> dict[str, Any]:
    """Translate a GTT cancel into Upstox ``GttCancelOrderRequest`` kwargs."""
    if not gtt_order_id:
        raise UpstoxMappingError("GTT cancel needs the gtt_order_id")
    return {"gtt_order_id": str(gtt_order_id)}


def is_gtt_order_id(order_id: str) -> bool:
    """True when an order id is an Upstox GTT id (``"GTT-..."`` — webhook doc)."""
    return str(order_id).upper().startswith("GTT-")


def extract_gtt_order_id(resp: dict[str, Any]) -> str:
    """Pull the GTT order id from a place/modify/cancel GTT response
    (``data.gtt_order_ids`` per ``GttOrderData``)."""
    data = resp.get("data", resp) if isinstance(resp, dict) else {}
    if isinstance(data, dict):
        ids = data.get("gtt_order_ids")
        if isinstance(ids, list) and ids:
            return str(ids[0])
        gid = data.get("gtt_order_id")
        if gid:
            return str(gid)
    raise UpstoxMappingError(f"No GTT order id in Upstox response: {resp!r}")


def from_upstox_gtt_order(d: dict[str, Any]) -> dict[str, Any]:
    """Normalise one Upstox ``GttOrderDetails`` record."""
    rules = d.get("rules", []) if isinstance(d.get("rules"), list) else []
    return {
        "gtt_order_id": str(d.get("gtt_order_id", "")),
        "type": d.get("type", ""),
        "symbol": d.get("trading_symbol", d.get("tradingsymbol", "")),
        "exchange": d.get("exchange", _exchange_of_token(d.get("instrument_token", ""))),
        "product": _product_from_upstox(
            d.get("product", ""), d.get("exchange", _exchange_of_token(d.get("instrument_token", ""))),
            d.get("segment", ""),
        ),
        "quantity": str(d.get("quantity", 0)),
        "rules": [
            {
                "strategy": r.get("strategy", ""),
                "status": r.get("status", ""),
                "trigger_price": str(r.get("trigger_price", 0)),
                "transaction_type": r.get("transaction_type", ""),
                "order_id": str(r.get("order_id") or ""),
            }
            for r in rules
            if isinstance(r, dict)
        ],
        "created_at": str(d.get("created_at", "")),
        "expires_at": str(d.get("expires_at", "")),
    }


# ---------------------------------------------------------------------------
# Multi-order / cancel-all / exit-all responses
# ---------------------------------------------------------------------------


def from_upstox_multi_order(resp: dict[str, Any]) -> dict[str, Any]:
    """Normalise an Upstox ``MultiOrderResponse`` (per-order ids + errors)."""
    if not isinstance(resp, dict):
        raise UpstoxMappingError(f"Unexpected Upstox multi-order response: {resp!r}")
    rows = resp.get("data", []) if isinstance(resp.get("data"), list) else []
    errors = resp.get("errors", []) if isinstance(resp.get("errors"), list) else []
    summary = resp.get("summary", {}) if isinstance(resp.get("summary"), dict) else {}
    return {
        "order_ids": [str(r.get("order_id", "")) for r in rows if isinstance(r, dict)],
        "errors": [e for e in errors if isinstance(e, dict)],
        "total": int(_num(summary.get("total", len(rows) + len(errors)))),
        "success": int(_num(summary.get("success", len(rows)))),
    }


def from_upstox_cancel_exit(resp: dict[str, Any]) -> dict[str, Any]:
    """Normalise a ``CancelOrExitMultiOrderResponse`` (cancel-multi / exit-all)."""
    if not isinstance(resp, dict):
        raise UpstoxMappingError(f"Unexpected Upstox cancel/exit response: {resp!r}")
    data = resp.get("data", {}) if isinstance(resp.get("data"), dict) else {}
    errors = resp.get("errors", []) if isinstance(resp.get("errors"), list) else []
    summary = resp.get("summary", {}) if isinstance(resp.get("summary"), dict) else {}
    ids = data.get("order_ids", []) if isinstance(data.get("order_ids"), list) else []
    return {
        "order_ids": [str(i) for i in ids],
        "errors": [e for e in errors if isinstance(e, dict)],
        "total": int(_num(summary.get("total", len(ids) + len(errors)))),
        "success": int(_num(summary.get("success", len(ids)))),
    }


# ---------------------------------------------------------------------------
# Positions: convert + MTF
# ---------------------------------------------------------------------------


def to_convert_position_params(req: dict[str, Any]) -> dict[str, Any]:
    """Translate a convert-position request into ``ConvertPositionRequest`` kwargs.

    ``req`` carries the resolved ``instrument_token``, FlintTrade product names
    (``old_product``/``new_product``), ``transaction_type`` and ``quantity``.
    """
    old_product = str(req.get("old_product", "")).upper()
    new_product = str(req.get("new_product", "")).upper()
    if old_product not in PRODUCT_TO_UPSTOX or new_product not in PRODUCT_TO_UPSTOX:
        raise UpstoxMappingError(
            f"Unsupported convert products {old_product!r} -> {new_product!r}"
        )
    if PRODUCT_TO_UPSTOX[old_product] == PRODUCT_TO_UPSTOX[new_product]:
        raise UpstoxMappingError(
            f"Convert {old_product!r} -> {new_product!r} is a no-op on Upstox (both map to "
            f"{PRODUCT_TO_UPSTOX[new_product]!r})"
        )
    side = str(req.get("transaction_type", req.get("action", ""))).upper()
    if side not in SIDE_TO_UPSTOX:
        raise UpstoxMappingError(f"Unsupported action {side!r}")
    return {
        "instrument_token": str(req.get("instrument_token", "")),
        "new_product": PRODUCT_TO_UPSTOX[new_product],
        "old_product": PRODUCT_TO_UPSTOX[old_product],
        "transaction_type": SIDE_TO_UPSTOX[side],
        "quantity": int(_num(req.get("quantity", 0), 0)),
    }


# ---------------------------------------------------------------------------
# Charges: brokerage (pre-trade) + margin
# ---------------------------------------------------------------------------


def to_brokerage_query(order: Any, instrument_token: str) -> dict[str, Any]:
    """Build the ``GET /v2/charges/brokerage`` query from an ``Order``."""
    core = _validated_core(order, instrument_token)
    return {
        "instrument_token": core["instrument_token"],
        "quantity": core["quantity"],
        "product": core["product"],
        "transaction_type": core["transaction_type"],
        "price": core["price"],
    }


def from_upstox_brokerage(resp: dict[str, Any]) -> dict[str, Any]:
    """Normalise a ``GetBrokerageResponse`` (``data.charges`` per BrokerageData)."""
    data = resp.get("data", resp) if isinstance(resp, dict) else {}
    charges = data.get("charges", data) if isinstance(data, dict) else {}
    if not isinstance(charges, dict):
        charges = {}
    return {
        "total_charges": str(charges.get("total", 0)),
        "brokerage": str(charges.get("brokerage", 0)),
        "taxes": charges.get("taxes", {}) if isinstance(charges.get("taxes"), dict) else {},
        "other_taxes": charges.get("other_taxes", {}) if isinstance(charges.get("other_taxes"), dict) else {},
        "extra": charges,
    }


# ---------------------------------------------------------------------------
# User: profile / kill switch
# ---------------------------------------------------------------------------


def from_upstox_profile(resp: dict[str, Any]) -> dict[str, Any]:
    """Normalise a ``GetProfileResponse`` (``data`` per ProfileData)."""
    data = resp.get("data", resp) if isinstance(resp, dict) else {}
    if not isinstance(data, dict):
        data = {}
    return {
        "user_id": str(data.get("user_id", "")),
        "user_name": str(data.get("user_name", "")),
        "email": str(data.get("email", "")),
        "broker": str(data.get("broker", "UPSTOX")),
        "exchanges": list(data.get("exchanges", []) or []),
        "products": list(data.get("products", []) or []),
        "order_types": list(data.get("order_types", []) or []),
        "is_active": bool(data.get("is_active", False)),
        "poa": bool(data.get("poa", False)),
    }


# ---------------------------------------------------------------------------
# Market quotes v3 (OHLC / LTP / option Greeks) + option contracts
# ---------------------------------------------------------------------------


def _quote_records(resp: dict[str, Any]) -> list[tuple[str, dict[str, Any]]]:
    data = resp.get("data", {}) if isinstance(resp, dict) else {}
    if not isinstance(data, dict):
        return []
    return [(k, v) for k, v in data.items() if isinstance(v, dict)]


def from_upstox_ohlc_v3(resp: dict[str, Any]) -> list[dict[str, Any]]:
    """Parse a v3 OHLC quote response (``MarketQuoteOHLCV3`` per instrument)."""
    out: list[dict[str, Any]] = []
    for key, rec in _quote_records(resp):
        live = rec.get("live_ohlc", {}) if isinstance(rec.get("live_ohlc"), dict) else {}
        prev = rec.get("prev_ohlc", {}) if isinstance(rec.get("prev_ohlc"), dict) else {}
        out.append({
            "instrument_token": str(rec.get("instrument_token", key)),
            "ltp": _num(rec.get("last_price")),
            "open": _num(live.get("open")),
            "high": _num(live.get("high")),
            "low": _num(live.get("low")),
            "close": _num(live.get("close")),
            "volume": int(_num(live.get("volume"))),
            "prev_close": _num(prev.get("close")),
        })
    return out


def from_upstox_ltp_v3(resp: dict[str, Any]) -> list[dict[str, Any]]:
    """Parse a v3 LTP quote response (``MarketQuoteSymbolLtpV3`` per instrument)."""
    return [
        {
            "instrument_token": str(rec.get("instrument_token", key)),
            "ltp": _num(rec.get("last_price")),
            "volume": int(_num(rec.get("volume"))),
            "prev_close": _num(rec.get("cp")),
        }
        for key, rec in _quote_records(resp)
    ]


def from_upstox_option_greeks(resp: dict[str, Any]) -> list[dict[str, Any]]:
    """Parse a v3 option-Greek quote response (``MarketQuoteOptionGreekV3``)."""
    return [
        {
            "instrument_token": str(rec.get("instrument_token", key)),
            "ltp": _num(rec.get("last_price")),
            "iv": _num(rec.get("iv")),
            "delta": _num(rec.get("delta")),
            "gamma": _num(rec.get("gamma")),
            "theta": _num(rec.get("theta")),
            "vega": _num(rec.get("vega")),
            "oi": int(_num(rec.get("oi"))),
            "volume": int(_num(rec.get("volume"))),
        }
        for key, rec in _quote_records(resp)
    ]


def from_upstox_instrument_rows(resp: dict[str, Any]) -> list[dict[str, Any]]:
    """Normalise instrument rows (search / option contracts / expired contracts).

    All three endpoints return ``data`` as a list of ``InstrumentData``-shaped
    records; the useful identity + contract fields are surfaced uniformly.
    """
    rows = resp.get("data", []) if isinstance(resp, dict) else []
    out: list[dict[str, Any]] = []
    for d in rows:
        if not isinstance(d, dict):
            continue
        out.append({
            "instrument_key": str(d.get("instrument_key", "")),
            "symbol": d.get("trading_symbol", d.get("tradingsymbol", "")),
            "name": d.get("name", ""),
            "exchange": d.get("exchange", ""),
            "segment": d.get("segment", ""),
            "instrument_type": d.get("instrument_type", ""),
            "expiry": str(d.get("expiry", "")),
            "strike_price": _num(d.get("strike_price")),
            "lot_size": int(_num(d.get("lot_size"))),
            "tick_size": _num(d.get("tick_size")),
            "freeze_quantity": _num(d.get("freeze_quantity")),
            "underlying_key": str(d.get("underlying_key", "")),
        })
    return out


def from_upstox_expiries(resp: dict[str, Any]) -> list[str]:
    """Parse the expiry-date list (``GET /v2/expired-instruments/expiries``)."""
    rows = resp.get("data", []) if isinstance(resp, dict) else []
    return [str(r) for r in rows if r] if isinstance(rows, list) else []


# ---------------------------------------------------------------------------
# Reports: trade history (date range) + trade-wise P&L + P&L charges
# ---------------------------------------------------------------------------


def from_upstox_trade_history(resp: dict[str, Any]) -> list[dict[str, Any]]:
    """Normalise the historical trade rows (``/v2/charges/historical-trades``)."""
    rows = resp.get("data", []) if isinstance(resp, dict) else []
    out: list[dict[str, Any]] = []
    for d in rows if isinstance(rows, list) else []:
        if not isinstance(d, dict):
            continue
        out.append({
            "trade_id": str(d.get("trade_id", "")),
            "symbol": d.get("symbol", d.get("scrip_name", "")),
            "exchange": d.get("exchange", ""),
            "segment": d.get("segment", ""),
            "action": d.get("transaction_type", ""),
            "quantity": str(d.get("quantity", 0)),
            "price": str(d.get("price", 0)),
            "amount": str(d.get("amount", 0)),
            "trade_date": str(d.get("trade_date", "")),
            "isin": str(d.get("isin", "")),
            "instrument_token": str(d.get("instrument_token", "")),
        })
    return out


def from_upstox_pnl_rows(resp: dict[str, Any]) -> list[dict[str, Any]]:
    """Normalise trade-wise P&L rows (``/v2/trade/profit-loss/data``)."""
    rows = resp.get("data", []) if isinstance(resp, dict) else []
    out: list[dict[str, Any]] = []
    for d in rows if isinstance(rows, list) else []:
        if not isinstance(d, dict):
            continue
        buy_amount = _num(d.get("buy_amount"))
        sell_amount = _num(d.get("sell_amount"))
        out.append({
            "symbol": d.get("scrip_name", ""),
            "isin": str(d.get("isin", "")),
            "trade_type": d.get("trade_type", ""),
            "quantity": str(d.get("quantity", 0)),
            "buy_date": str(d.get("buy_date", "")),
            "buy_average": str(d.get("buy_average", 0)),
            "sell_date": str(d.get("sell_date", "")),
            "sell_average": str(d.get("sell_average", 0)),
            "buy_amount": str(buy_amount),
            "sell_amount": str(sell_amount),
            "pnl": str(sell_amount - buy_amount),
        })
    return out


def from_upstox_pnl_charges(resp: dict[str, Any]) -> dict[str, Any]:
    """Normalise the P&L charges report (``/v2/trade/profit-loss/charges``)."""
    data = resp.get("data", resp) if isinstance(resp, dict) else {}
    charges = data.get("charges_breakdown", data) if isinstance(data, dict) else {}
    if not isinstance(charges, dict):
        charges = {}
    return {
        "total_charges": str(charges.get("total", 0)),
        "brokerage": str(charges.get("brokerage", 0)),
        "extra": charges,
    }


# ---------------------------------------------------------------------------
# Market information: timings / holidays / status
# ---------------------------------------------------------------------------


def from_upstox_timings(resp: dict[str, Any]) -> list[dict[str, Any]]:
    """Normalise exchange timings (``/v2/market/timings/{date}``)."""
    rows = resp.get("data", []) if isinstance(resp, dict) else []
    return [
        {
            "exchange": d.get("exchange", ""),
            "start_time": str(d.get("start_time", "")),
            "end_time": str(d.get("end_time", "")),
        }
        for d in (rows if isinstance(rows, list) else [])
        if isinstance(d, dict)
    ]


def from_upstox_holidays(resp: dict[str, Any]) -> list[dict[str, Any]]:
    """Normalise market holidays (``/v2/market/holidays[/{date}]``)."""
    rows = resp.get("data", []) if isinstance(resp, dict) else []
    return [
        {
            "date": str(d.get("date", d.get("_date", ""))),
            "description": d.get("description", ""),
            "holiday_type": d.get("holiday_type", ""),
            "closed_exchanges": list(d.get("closed_exchanges", []) or []),
        }
        for d in (rows if isinstance(rows, list) else [])
        if isinstance(d, dict)
    ]


def from_upstox_market_status(resp: dict[str, Any]) -> dict[str, Any]:
    """Normalise the market status (``/v2/market/status/{exchange}``)."""
    data = resp.get("data", resp) if isinstance(resp, dict) else {}
    if not isinstance(data, dict):
        data = {}
    return {
        "exchange": data.get("exchange", ""),
        "status": data.get("status", ""),
        "last_updated": str(data.get("last_updated", "")),
    }


# ---------------------------------------------------------------------------
# Streaming (v3 market-data feed) — authorise + decoded-message parsing
# ---------------------------------------------------------------------------


def extract_authorized_uri(resp: dict[str, Any]) -> str:
    """Pull the one-time authorised wss:// URI from a feed-authorise response."""
    data = resp.get("data", resp) if isinstance(resp, dict) else {}
    uri = str((data or {}).get("authorized_redirect_uri", "")) if isinstance(data, dict) else ""
    if not uri:
        raise UpstoxMappingError(f"No authorised feed URI in Upstox response: {resp!r}")
    return uri


def _ltpc_of(rec: dict[str, Any]) -> dict[str, Any]:
    """Locate the ``ltpc`` block in a v3 feed record (ltpc or fullFeed modes)."""
    ltpc = rec.get("ltpc")
    if isinstance(ltpc, dict):
        return ltpc
    full = rec.get("fullFeed", {}) if isinstance(rec.get("fullFeed"), dict) else {}
    for branch in ("marketFF", "indexFF"):
        sub = full.get(branch, {}) if isinstance(full.get(branch), dict) else {}
        if isinstance(sub.get("ltpc"), dict):
            return sub["ltpc"]
    return {}


def from_upstox_feed_ticks(message: dict[str, Any]) -> list[dict[str, Any]]:
    """Parse one decoded v3 market-feed message into flat tick dicts.

    The live protobuf frames are decoded by the SDK's ``MarketDataStreamerV3``
    (or an injected equivalent), which emits ``{"feeds": {instrument_key:
    {ltpc|fullFeed: ...}}}`` dicts — this parser only handles that decoded form.
    """
    feeds = message.get("feeds", {}) if isinstance(message, dict) else {}
    if not isinstance(feeds, dict):
        return []
    ticks: list[dict[str, Any]] = []
    for key, rec in feeds.items():
        if not isinstance(rec, dict):
            continue
        ltpc = _ltpc_of(rec)
        if not ltpc:
            continue
        full = rec.get("fullFeed", {}) if isinstance(rec.get("fullFeed"), dict) else {}
        market = full.get("marketFF", {}) if isinstance(full.get("marketFF"), dict) else {}
        ticks.append({
            "instrument_key": str(key),
            "ltp": _num(ltpc.get("ltp")),
            "ltq": int(_num(ltpc.get("ltq"))),
            "ltt": str(ltpc.get("ltt", "")),
            "prev_close": _num(ltpc.get("cp")),
            "volume": int(_num(market.get("vtt"))),
            "oi": int(_num(market.get("oi"))),
        })
    return ticks


def _leg(side: dict[str, Any]) -> dict[str, Any]:
    """Flatten one option-chain leg (market_data + option_greeks)."""
    md = side.get("market_data", {}) if isinstance(side.get("market_data"), dict) else {}
    gk = side.get("option_greeks", {}) if isinstance(side.get("option_greeks"), dict) else {}
    return {
        "ltp": _num(md.get("ltp")),
        "oi": int(_num(md.get("oi"))),
        "volume": int(_num(md.get("volume"))),
        "iv": _num(gk.get("iv")),
        "delta": _num(gk.get("delta")),
        "gamma": _num(gk.get("gamma")),
        "theta": _num(gk.get("theta")),
        "vega": _num(gk.get("vega")),
        "bid": _num(md.get("bid_price")),
        "ask": _num(md.get("ask_price")),
    }


def to_option_chain_dict(underlying: str, exchange: str, resp: dict[str, Any]) -> dict[str, Any]:
    """Parse an Upstox put/call option-chain response into a FlintTrade dict.

    Upstox returns ``data`` as a list of strike rows, each with ``strike_price``,
    ``call_options`` and ``put_options`` (each ``{market_data, option_greeks}``).
    """
    rows = resp.get("data", []) if isinstance(resp, dict) else []
    strikes: list[dict[str, Any]] = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        call = _leg(row.get("call_options", {}) if isinstance(row.get("call_options"), dict) else {})
        put = _leg(row.get("put_options", {}) if isinstance(row.get("put_options"), dict) else {})
        strikes.append({
            "strike_price": _num(row.get("strike_price")),
            "ce_ltp": call["ltp"], "ce_oi": call["oi"], "ce_volume": call["volume"], "ce_iv": call["iv"],
            "ce_delta": call["delta"], "ce_gamma": call["gamma"], "ce_theta": call["theta"], "ce_vega": call["vega"],
            "ce_bid": call["bid"], "ce_ask": call["ask"],
            "pe_ltp": put["ltp"], "pe_oi": put["oi"], "pe_volume": put["volume"], "pe_iv": put["iv"],
            "pe_delta": put["delta"], "pe_gamma": put["gamma"], "pe_theta": put["theta"], "pe_vega": put["vega"],
            "pe_bid": put["bid"], "pe_ask": put["ask"],
        })
    return {"underlying": underlying, "exchange": exchange, "strikes": strikes}


# ---------------------------------------------------------------------------
# Broker-error translation (contract §7 — SDK errors never escape the adapter)
# ---------------------------------------------------------------------------


def is_api_exception(exc: BaseException) -> bool:
    """True for an upstox-python ``rest.ApiException`` (without importing the SDK).

    The OpenAPI-generated SDK raises ``upstox_client.rest.ApiException`` on any
    non-2xx response. The SDK is not installed in the test/runtime environment,
    so this duck-types the exception by class name plus its ``status``/``body``
    attribute shape rather than importing it. Tests inject a stand-in with the
    same shape.

    Args:
        exc: The caught exception.

    Returns:
        Whether ``exc`` looks like an Upstox ``ApiException``.
    """
    return (
        type(exc).__name__ == "ApiException"
        and hasattr(exc, "status")
        and hasattr(exc, "body")
    )


def _parse_error_body(body: Any) -> tuple[str, str]:
    """Extract ``(error_code, message)`` from an Upstox error response body.

    Upstox error payloads follow ``ApiGatewayErrorResponse``:
    ``{"status": "error", "errors": [{"errorCode": ..., "message": ...}]}``.
    The error code's wire key is ``errorCode`` (camelCase) — the SDK ``Problem``
    model maps ``error_code -> "errorCode"``, and ``ApiException.body`` is the
    RAW HTTP data, so we read the camelCase key (with a snake_case fallback for
    safety). The body arrives as bytes or a str; a non-JSON body degrades
    gracefully to ``("", "<raw>")`` so the broker message is never lost.

    Args:
        body: The ``ApiException.body`` (bytes / str / already-decoded dict).

    Returns:
        ``(error_code, message)`` — either field may be empty.
    """
    payload: Any = body
    if isinstance(body, (bytes, bytearray)):
        try:
            payload = json.loads(body.decode("utf-8", "replace"))
        except (ValueError, UnicodeDecodeError):
            return "", body.decode("utf-8", "replace").strip()
    elif isinstance(body, str):
        try:
            payload = json.loads(body)
        except ValueError:
            return "", body.strip()
    if not isinstance(payload, dict):
        return "", str(payload or "").strip()
    errors = payload.get("errors")
    if isinstance(errors, list) and errors and isinstance(errors[0], dict):
        first = errors[0]
        code = first.get("errorCode") or first.get("error_code") or ""
        return str(code), str(first.get("message") or "")
    # Some endpoints return a flat ``{"errorCode", "message"}`` body.
    code = payload.get("errorCode") or payload.get("error_code") or ""
    return str(code), str(payload.get("message") or "")


def map_upstox_error(exc: BaseException) -> BrokerError:
    """Map an Upstox ``ApiException`` to the FlintTrade exception taxonomy.

    Translates the HTTP status and parsed error body to the canonical
    :class:`~flinttrade_core.exceptions.BrokerError` subtree (contract §7), so a
    rejected order (4xx), expired daily token (401), or rate-limit (429) surfaces
    as a typed FlintTrade error instead of a raw SDK exception. The broker's own
    message and error code are preserved for the audit chain.

    Args:
        exc: The caught ``ApiException``-shaped exception.

    Returns:
        The mapped ``BrokerError`` subclass instance.
    """
    status = getattr(exc, "status", None)
    try:
        status_code = int(status) if status is not None else 0
    except (TypeError, ValueError):
        status_code = 0
    error_code, message = _parse_error_body(getattr(exc, "body", None))
    if not message:
        message = str(getattr(exc, "reason", "") or "") or f"Upstox API error (HTTP {status_code})"
    kwargs: dict[str, str] = {"broker_code": error_code or str(status_code), "broker_id": "upstox"}
    code = error_code.upper()
    msg_l = message.lower()

    if status_code in (401, 403) or "token" in code.lower() or "unauthor" in msg_l:
        return SessionExpired(message, **kwargs)
    if status_code == 429 or "rate" in msg_l and "limit" in msg_l:
        return RateLimitError(message, endpoint="default", **kwargs)
    if "margin" in msg_l or "insufficient" in msg_l or "funds" in msg_l:
        return InsufficientFunds(message, **kwargs)
    if "quantity" in msg_l or "lot size" in msg_l or "freeze" in msg_l:
        return InvalidQuantity(message, **kwargs)
    if "price" in msg_l or "circuit" in msg_l or "tick size" in msg_l:
        return InvalidPrice(message, **kwargs)
    if 400 <= status_code < 500:
        return OrderRejectedByBroker(message, **kwargs)
    return BrokerError(message, **kwargs)
