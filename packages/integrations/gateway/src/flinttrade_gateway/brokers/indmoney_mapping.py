"""Canonical-to-IndMoney (INDstocks) mapping tables and translators.

Values are grounded in the official INDstocks API docs (``api-docs.indstocks.com``,
captured 2026-06-12 into ``.local/reference/broker-docs/indmoney/``). IndMoney has
no official SDK, so this module owns BOTH directions of the pure-REST translation:
request building (FlintTrade ``Order`` → JSON payloads) and response parsing
(IndMoney JSON → normalised FlintTrade-shaped dicts), plus the WebSocket frame
codecs. Keep these tables in lock-step with ``INDMONEY_CAPABILITIES``.

Honesty rule: anything the broker does not document is REJECTED, never silently
downgraded — e.g. a standalone SL/SL-M order raises (the broker only accepts
LIMIT/MARKET on ``/order``; trigger behaviour lives in the smart-order family).
"""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from typing import Any

from flinttrade_core.exceptions import (
    AuthError,
    BrokerError,
    BrokerInternal,
    BrokerTimeout,
    DataError,
    InsufficientFunds,
    NetworkError,
    OrderError,
    OrderRejectedByBroker,
    RateLimitError,
    SessionExpired,
)

# ---------------------------------------------------------------------------
# Constants (doc-grounded)
# ---------------------------------------------------------------------------

BASE_URL = "https://api.indstocks.com"
PRICE_FEED_WS_URL = "wss://ws-prices.indstocks.com/api/v1/ws/prices"
ORDER_FEED_WS_URL = "wss://ws-order-updates.indstocks.com/api/v1/ws/trades"

# Mandatory algo identifiers (normal-orders doc): 99999 for NSE orders,
# 9999999999999999 for BSE orders.
ALGO_ID_NSE = "99999"
ALGO_ID_BSE = "9999999999999999"

# Canonical transaction side -> IndMoney txn_type.
SIDE_MAP = {
    "BUY": "BUY",
    "SELL": "SELL",
}

# Canonical order type -> IndMoney order_type for NORMAL orders. The broker
# accepts only LIMIT/MARKET here (MARKET is broker-converted to LIMIT at the
# live price); SL/SL-M are deliberately absent — see to_place_order_payload.
ORDER_TYPE_MAP = {
    "MARKET": "MARKET",
    "LIMIT": "LIMIT",
}

# Canonical product -> IndMoney product.
PRODUCT_MAP = {
    "MIS": "INTRADAY",
    "CNC": "CNC",
    "NRML": "MARGIN",
}

# Canonical validity -> IndMoney validity (normal orders only; smart orders are
# DAY-only per the smart-orders doc).
VALIDITY_MAP = {
    "DAY": "DAY",
    "IOC": "IOC",
}

# Canonical exchange -> (IndMoney exchange, IndMoney segment) for the order APIs.
# INDstocks trades NSE/BSE equity and F&O only — no MCX/CDS order endpoints.
EXCHANGE_SEGMENT_MAP = {
    "NSE": ("NSE", "EQUITY"),
    "BSE": ("BSE", "EQUITY"),
    "NFO": ("NSE", "DERIVATIVE"),
    "BFO": ("BSE", "DERIVATIVE"),
}

# Canonical exchange -> scrip-code prefix for the quote/historical REST APIs
# (format ``SEGMENT_INSTRUMENTTOKEN``, e.g. ``NSE_3045``). Index segments use
# NIDX/BIDX, not NSE/BSE (marketquote + instruments docs).
SCRIP_SEGMENT_MAP = {
    "NSE": "NSE",
    "BSE": "BSE",
    "NFO": "NFO",
    "BFO": "BFO",
    "NSE_INDEX": "NIDX",
    "BSE_INDEX": "BIDX",
}

# FlintTrade stream mode -> IndMoney price-feed WebSocket mode.
WS_MODE_MAP = {
    "LTP": "ltp",
    "QUOTE": "quote",
    "FULL": "quote",  # quote is the richest documented price-feed mode
}

# IndMoney product -> canonical product (response parsing).
PRODUCT_REVERSE_MAP = {
    "INTRADAY": "MIS",
    "CNC": "CNC",
    "MARGIN": "NRML",
}

# (exchange, segment) -> canonical exchange (response parsing).
SEGMENT_REVERSE_MAP = {
    ("NSE", "EQUITY"): "NSE",
    ("BSE", "EQUITY"): "BSE",
    ("NSE", "DERIVATIVE"): "NFO",
    ("BSE", "DERIVATIVE"): "BFO",
}

# Documented exchange_segment values (trades/holdings payloads) -> canonical.
EXCHANGE_SEGMENT_REVERSE_MAP = {
    "NSE_EQ": "NSE",
    "BSE_EQ": "BSE",
    "NSE_FNO": "NFO",
    "BSE_FNO": "BFO",
}

# Historical interval -> (IndMoney interval label, max fetch range in days).
# Straight from the historical-data "Supported Intervals & Maximum Time Range"
# table. Keys are FlintTrade canonical interval spellings.
INTERVAL_MAP = {
    "1s": ("1second", 1),
    "5s": ("5second", 1),
    "10s": ("10second", 1),
    "15s": ("15second", 1),
    "1m": ("1minute", 7),
    "2m": ("2minute", 7),
    "3m": ("3minute", 7),
    "4m": ("4minute", 7),
    "5m": ("5minute", 7),
    "10m": ("10minute", 7),
    "15m": ("15minute", 7),
    "30m": ("30minute", 7),
    "1h": ("60minute", 14),
    "2h": ("120minute", 14),
    "3h": ("180minute", 14),
    "4h": ("240minute", 14),
    "d": ("1day", 365),
    "1d": ("1day", 365),
    "day": ("1day", 365),
    "w": ("1week", 365),
    "1w": ("1week", 365),
    "week": ("1week", 365),
    "1mo": ("1month", 365),
    "month": ("1month", 365),
}

# Varieties dispatched to the smart-order (GTT) endpoints.
SMART_VARIETIES = ("gtt", "oco", "trigger")

# IST — all IndMoney timestamps are IST epoch milliseconds (conventions doc).
_IST = timezone(timedelta(hours=5, minutes=30))


class IndMoneyMappingError(ValueError):
    """Raised when an order/response cannot be translated to/from the IndMoney API."""


# ---------------------------------------------------------------------------
# Small helpers
# ---------------------------------------------------------------------------


def _num(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def parse_indian_number(value: Any) -> float:
    """Parse a numeric string that may use Indian comma grouping (``"5,82,909"``).

    Args:
        value: Raw value from a depth/quote payload (str or number).

    Returns:
        The parsed float; 0.0 if unparseable.
    """
    if isinstance(value, str):
        value = value.replace(",", "").strip()
    return _num(value)


def _norm_pricetype(pricetype: Any) -> str:
    # FlintTrade uses "SL-M"; normalise to a hyphen-free comparison key.
    return str(pricetype).upper().replace("-", "")


def default_algo_id(exchange: str) -> str:
    """Return the mandatory broker algo id for *exchange* (canonical or IndMoney).

    Args:
        exchange: Canonical exchange (``"NSE"``/``"BSE"``/``"NFO"``/``"BFO"``).

    Returns:
        ``"99999"`` for NSE-family orders, ``"9999999999999999"`` for BSE-family.
    """
    return ALGO_ID_BSE if str(exchange).upper() in ("BSE", "BFO", "BSE_INDEX") else ALGO_ID_NSE


def to_exchange_segment(exchange: str) -> tuple[str, str]:
    """Map a canonical exchange to the IndMoney ``(exchange, segment)`` pair.

    Args:
        exchange: Canonical FlintTrade exchange (e.g. ``"NSE"``, ``"NFO"``).

    Returns:
        Tuple of IndMoney exchange (``"NSE"``/``"BSE"``) and segment
        (``"EQUITY"``/``"DERIVATIVE"``).

    Raises:
        IndMoneyMappingError: If *exchange* is not orderable on IndMoney.
    """
    try:
        return EXCHANGE_SEGMENT_MAP[str(exchange).upper()]
    except KeyError as exc:
        raise IndMoneyMappingError(f"IndMoney cannot trade exchange {exchange!r} (NSE/BSE/NFO/BFO only)") from exc


def to_scrip_code(exchange: str, security_id: str) -> str:
    """Build a quote/historical scrip code (``SEGMENT_INSTRUMENTTOKEN``).

    Args:
        exchange: Canonical exchange (NSE/BSE/NFO/BFO/NSE_INDEX/BSE_INDEX).
        security_id: Instrument token from the instruments master.

    Raises:
        IndMoneyMappingError: If *exchange* has no scrip segment mapping.
    """
    try:
        prefix = SCRIP_SEGMENT_MAP[str(exchange).upper()]
    except KeyError as exc:
        raise IndMoneyMappingError(f"No IndMoney scrip segment for exchange {exchange!r}") from exc
    return f"{prefix}_{security_id}"


def from_scrip_code(scrip: str) -> tuple[str, str]:
    """Split a scrip code back into ``(canonical_exchange, security_id)``."""
    prefix, _, token = str(scrip).partition("_")
    reverse = {v: k for k, v in SCRIP_SEGMENT_MAP.items()}
    return reverse.get(prefix.upper(), prefix.upper()), token


def ws_instrument(exchange: str, security_id: str) -> str:
    """Build a price-feed WebSocket instrument token (``SEGMENT:TOKEN``)."""
    try:
        prefix = SCRIP_SEGMENT_MAP[str(exchange).upper()]
    except KeyError as exc:
        raise IndMoneyMappingError(f"No IndMoney WebSocket segment for exchange {exchange!r}") from exc
    return f"{prefix}:{security_id}"


def segment_from_order_id(order_id: str) -> str | None:
    """Infer the IndMoney segment from a documented order-id prefix.

    ``DRV-`` ids are derivative parents, ``EQ-`` ids equity parents. ``GTT-``
    ids carry no segment information, so ``None`` is returned and the caller
    must resolve the segment another way (e.g. from the order book).
    """
    oid = str(order_id)
    if oid.startswith("DRV-"):
        return "DERIVATIVE"
    if oid.startswith("EQ-"):
        return "EQUITY"
    return None


def is_smart_order_id(order_id: str) -> bool:
    """True when *order_id* belongs to the smart-order (GTT) family."""
    return str(order_id).startswith("GTT-")


def resolve_segment(order_id: str, changes: dict[str, Any] | None = None) -> str | None:
    """Resolve the IndMoney segment for a modify/cancel call.

    Precedence: explicit ``changes['segment']`` → ``changes['exchange']``
    (canonical, mapped) → order-id prefix → ``None``.
    """
    changes = changes or {}
    seg = str(changes.get("segment", "")).upper()
    if seg in ("EQUITY", "DERIVATIVE"):
        return seg
    exchange = changes.get("exchange")
    if exchange:
        return to_exchange_segment(str(exchange))[1]
    return segment_from_order_id(order_id)


# ---------------------------------------------------------------------------
# Request building: FlintTrade Order -> IndMoney payloads
# ---------------------------------------------------------------------------


def _validated_core(order: Any) -> dict[str, Any]:
    """Shared validation + core fields for every IndMoney order payload."""
    side = str(order.action).upper()
    if side not in SIDE_MAP:
        raise IndMoneyMappingError(f"Unsupported action {side!r}")
    exchange, segment = to_exchange_segment(str(order.exchange))
    product = str(order.product).upper()
    if product not in PRODUCT_MAP:
        raise IndMoneyMappingError(f"Unsupported product {product!r}")
    qty = int(_num(order.quantity, 0))
    if qty <= 0:
        raise IndMoneyMappingError("qty must be greater than zero")
    return {
        "txn_type": SIDE_MAP[side],
        "exchange": exchange,
        "segment": segment,
        "product": PRODUCT_MAP[product],
        "qty": qty,
    }


def to_place_order_payload(order: Any, security_id: str, *, algo_id: str | None = None) -> dict[str, Any]:
    """Translate a FlintTrade ``Order`` into a ``POST /order`` JSON body.

    ``security_id`` is resolved by the adapter (IndMoney trades by instrument
    token, not symbol). Variety ``"amo"`` sets the documented ``is_amo`` flag on
    the same payload.

    Raises:
        IndMoneyMappingError: For unmappable enum values, SL/SL-M price types
            (the broker has no standalone stop-loss order — use variety
            ``"trigger"``), or a missing limit price on a LIMIT order.
    """
    payload = _validated_core(order)
    ptype = _norm_pricetype(getattr(order, "pricetype", "MARKET"))
    if ptype in ("SL", "SLM"):
        raise IndMoneyMappingError(
            "IndMoney normal orders accept only LIMIT/MARKET — for stop/trigger behaviour "
            "use variety='trigger' (smart order)"
        )
    if ptype not in ORDER_TYPE_MAP:
        raise IndMoneyMappingError(f"Unsupported pricetype {ptype!r}")
    validity = str(getattr(order, "validity", "DAY") or "DAY").upper()
    if validity not in VALIDITY_MAP:
        raise IndMoneyMappingError(f"Unsupported validity {validity!r}")

    payload.update(
        {
            "order_type": ORDER_TYPE_MAP[ptype],
            "validity": VALIDITY_MAP[validity],
            "security_id": str(security_id),
            "is_amo": str(getattr(order, "variety", "regular")).lower() == "amo",
            "algo_id": algo_id or default_algo_id(payload["exchange"]),
        }
    )
    if payload["order_type"] == "LIMIT":
        price = _num(getattr(order, "price", 0))
        if price <= 0:
            raise IndMoneyMappingError("A LIMIT order needs a limit price greater than zero")
        payload["limit_price"] = price
    return payload


def to_smart_order_payload(order: Any, security_id: str, *, algo_id: str | None = None) -> dict[str, Any]:
    """Translate a smart-variety ``Order`` into a ``POST /smart/order`` JSON body.

    Varieties:
        * ``"trigger"`` — a TRIGGER parent; ``trigger_price`` is mandatory and a
          positive ``price`` becomes ``trigger_limit_price`` (trigger-limit).
        * ``"gtt"`` / ``"oco"`` — a LIMIT/MARKET parent with stop-loss and/or
          target GTT legs. ``stop_loss_price`` maps to ``sl_trigger_price`` and
          ``target_price`` to ``tgt_trigger_price``; the broker requires a limit
          price alongside each leg, so ``sl_limit_price``/``tgt_limit_price``
          default to the trigger values when not separately supplied.

    Raises:
        IndMoneyMappingError: Missing trigger price on a TRIGGER order, no legs
            on a GTT/OCO order, or any unmappable enum value.
    """
    payload = _validated_core(order)
    variety = str(getattr(order, "variety", "")).lower()
    payload.update(
        {
            "validity": "DAY",  # smart orders are DAY-only (smart-orders doc)
            "security_id": str(security_id),
            "algo_id": algo_id or default_algo_id(payload["exchange"]),
        }
    )

    if variety == "trigger":
        trigger = _num(getattr(order, "trigger_price", 0))
        if trigger <= 0:
            raise IndMoneyMappingError("A TRIGGER smart order needs a trigger_price greater than zero")
        payload["order_type"] = "TRIGGER"
        payload["trigger_price"] = trigger
        limit = _num(getattr(order, "price", 0))
        if limit > 0:
            payload["trigger_limit_price"] = limit
        return payload

    ptype = _norm_pricetype(getattr(order, "pricetype", "MARKET"))
    if ptype not in ORDER_TYPE_MAP:
        raise IndMoneyMappingError(f"Unsupported pricetype {ptype!r} for a smart order")
    payload["order_type"] = ORDER_TYPE_MAP[ptype]
    if payload["order_type"] == "LIMIT":
        price = _num(getattr(order, "price", 0))
        if price <= 0:
            raise IndMoneyMappingError("A LIMIT smart order needs a limit price greater than zero")
        payload["limit_price"] = price

    sl_trigger = _num(getattr(order, "stop_loss_price", 0))
    tgt_trigger = _num(getattr(order, "target_price", 0))
    if sl_trigger <= 0 and tgt_trigger <= 0:
        raise IndMoneyMappingError("A GTT/OCO smart order needs a stop_loss_price and/or a target_price leg")
    if sl_trigger > 0:
        payload["sl_trigger_price"] = sl_trigger
        # The broker rejects a stop-loss leg without its limit price.
        payload["sl_limit_price"] = _num(getattr(order, "sl_limit_price", 0)) or sl_trigger
    if tgt_trigger > 0:
        payload["tgt_trigger_price"] = tgt_trigger
        payload["tgt_limit_price"] = _num(getattr(order, "tgt_limit_price", 0)) or tgt_trigger
    return payload


def to_modify_order_payload(order_id: str, changes: dict[str, Any], *, segment: str | None = None) -> dict[str, Any]:
    """Translate modify ``changes`` into a ``POST /order/modify`` JSON body.

    Both ``qty`` and ``limit_price`` are mandatory on the IndMoney modify API.

    Raises:
        IndMoneyMappingError: Missing/zero qty or limit price, or an
            unresolvable segment.
    """
    seg = segment or resolve_segment(order_id, changes)
    if seg is None:
        raise IndMoneyMappingError(
            f"Cannot infer the IndMoney segment for order {order_id!r} — pass changes['segment']"
        )
    qty = int(_num(changes.get("qty", changes.get("quantity", 0)), 0))
    if qty <= 0:
        raise IndMoneyMappingError("Modify requires qty greater than zero")
    limit_price = _num(changes.get("limit_price", changes.get("price", 0)))
    if limit_price <= 0:
        raise IndMoneyMappingError("Modify requires limit_price greater than zero")
    return {"order_id": str(order_id), "segment": seg, "qty": qty, "limit_price": limit_price}


def to_smart_modify_payload(
    order_id: str, changes: dict[str, Any], *, segment: str | None = None, algo_id: str | None = None
) -> dict[str, Any]:
    """Translate modify ``changes`` into a ``POST /smart/order/modify`` JSON body.

    Only the documented optional fields are passed through; ``order_type`` must
    match the existing order (broker-enforced).
    """
    seg = segment or resolve_segment(order_id, changes)
    if seg is None:
        raise IndMoneyMappingError(
            f"Cannot infer the IndMoney segment for smart order {order_id!r} — pass changes['segment']"
        )
    exchange = str(changes.get("exchange", "NSE"))
    payload: dict[str, Any] = {
        "order_id": str(order_id),
        "segment": seg,
        "algo_id": algo_id or str(changes.get("algo_id", "")) or default_algo_id(exchange),
    }
    if changes.get("order_type") or changes.get("pricetype"):
        ptype = _norm_pricetype(changes.get("order_type", changes.get("pricetype")))
        payload["order_type"] = "TRIGGER" if ptype == "TRIGGER" else ORDER_TYPE_MAP.get(ptype, ptype)
    qty = int(_num(changes.get("qty", changes.get("quantity", 0)), 0))
    if qty > 0:
        payload["qty"] = qty
    for src, dst in (
        ("limit_price", "limit_price"),
        ("price", "limit_price"),
        ("trigger_price", "trigger_price"),
        ("trigger_limit_price", "trigger_limit_price"),
        ("sl_trigger_price", "sl_trigger_price"),
        ("sl_limit_price", "sl_limit_price"),
        ("tgt_trigger_price", "tgt_trigger_price"),
        ("tgt_limit_price", "tgt_limit_price"),
    ):
        value = _num(changes.get(src, 0))
        if value > 0 and dst not in payload:
            payload[dst] = value
    return payload


def to_cancel_payload(order_id: str, segment: str) -> dict[str, Any]:
    """Build the shared cancel body for ``/order/cancel`` and ``/smart/order/cancel``."""
    seg = str(segment).upper()
    if seg not in ("EQUITY", "DERIVATIVE"):
        raise IndMoneyMappingError(f"Invalid IndMoney segment {segment!r}")
    return {"order_id": str(order_id), "segment": seg}


def to_margin_params(order: Any, security_id: str) -> dict[str, str]:
    """Translate an ``Order`` into the ``GET /margin`` body (string-typed fields)."""
    core = _validated_core(order)
    return {
        "segment": core["segment"],
        "exchange": core["exchange"],
        "securityID": str(security_id),
        "txnType": core["txn_type"],
        "quantity": str(core["qty"]),
        "price": str(_num(getattr(order, "price", 0))),
        "product": core["product"],
    }


# ---------------------------------------------------------------------------
# Response envelope + error mapping
# ---------------------------------------------------------------------------


def unwrap(resp: Any) -> Any:
    """Unwrap an IndMoney ``{status, data, message}`` envelope; raise on error.

    Raises:
        IndMoneyMappingError: If the payload carries ``status: "error"``.
    """
    if isinstance(resp, dict):
        if str(resp.get("status", "")).lower() == "error":
            raise IndMoneyMappingError(f"IndMoney API error: {resp.get('message') or resp}")
        if "data" in resp:
            return resp["data"]
    return resp


def map_error(status_code: int, payload: Any) -> BrokerError:
    """Map an IndMoney HTTP error response to the FlintTrade exception taxonomy.

    Args:
        status_code: HTTP status code of the failed request.
        payload: Decoded JSON body (``{status, message, error_type|error_code}``)
            or raw text.

    Returns:
        The mapped :class:`~flinttrade_core.exceptions.BrokerError` subclass
        instance (contract §7 — broker-native errors never escape the adapter).
    """
    body = payload if isinstance(payload, dict) else {}
    message = str(body.get("message") or payload or f"HTTP {status_code}")
    etype = str(body.get("error_type") or body.get("error_code") or "")
    kwargs: dict[str, Any] = {"broker_code": etype or str(status_code), "broker_id": "indmoney"}

    if status_code == 429:
        return RateLimitError(message, endpoint="default", **kwargs)
    if etype == "TokenException":
        return SessionExpired(message, **kwargs)
    if etype == "UserException":
        return AuthError(message, **kwargs)
    if etype == "OrderException":
        if "margin" in message.lower() and "exceed" in message.lower():
            return InsufficientFunds(message, **kwargs)
        return OrderRejectedByBroker(message, **kwargs)
    if etype == "InputException":
        return OrderError(message, **kwargs)
    if etype == "DataException":
        return DataError(message, **kwargs)
    if etype == "GatewayTimeoutException":
        return BrokerTimeout(message, **kwargs)
    if etype in ("NetworkException", "ServiceUnavailableException"):
        return NetworkError(message, **kwargs)
    if etype == "GeneralException" or status_code >= 500:
        return BrokerInternal(message, **kwargs)
    return BrokerError(message, **kwargs)


def extract_order_id(resp: Any) -> str:
    """Pull the order id from a ``POST /order`` response."""
    data = unwrap(resp)
    if isinstance(data, dict):
        oid = data.get("order_id") or data.get("id")
        if oid:
            return str(oid)
    raise IndMoneyMappingError(f"No order id in IndMoney response: {resp}")


def extract_smart_order_ids(resp: Any) -> tuple[str, str | None]:
    """Pull ``(parent_id, child_id|None)`` from a ``POST /smart/order`` response.

    The smart placement payload nests ids under ``data.order_data[0]`` with the
    GTT child under ``child_order_details`` (smart-orders doc).
    """
    data = unwrap(resp)
    if isinstance(data, dict):
        rows = data.get("order_data")
        if isinstance(rows, list) and rows and isinstance(rows[0], dict):
            parent = rows[0].get("order_id")
            child = (rows[0].get("child_order_details") or {}).get("order_id")
            if parent:
                return str(parent), (str(child) if child else None)
        # Some placements (e.g. plain trigger orders) may answer with the flat shape.
        oid = data.get("order_id")
        if oid:
            return str(oid), None
    raise IndMoneyMappingError(f"No order id in IndMoney smart-order response: {resp}")


# ---------------------------------------------------------------------------
# Response parsing (IndMoney -> normalised FlintTrade-shaped dicts)
# ---------------------------------------------------------------------------


def _reverse_exchange(d: dict[str, Any]) -> str:
    """Reconstruct the canonical exchange from an order/position record."""
    pair = (str(d.get("exchange", "")).upper(), str(d.get("segment", "")).upper())
    if pair in SEGMENT_REVERSE_MAP:
        return SEGMENT_REVERSE_MAP[pair]
    seg = str(d.get("exchange_segment", "")).upper()
    return EXCHANGE_SEGMENT_REVERSE_MAP.get(seg, seg or pair[0])


def from_indmoney_order(d: dict[str, Any]) -> dict[str, Any]:
    """Normalise an IndMoney order-book/order-details record."""
    return {
        "orderid": str(d.get("id", "")),
        "status": str(d.get("status", "")),
        "symbol": str(d.get("name", "")),
        "exchange": _reverse_exchange(d),
        "action": str(d.get("txn_type", "")),
        "pricetype": str(d.get("order_type", "")),
        "product": PRODUCT_REVERSE_MAP.get(str(d.get("product", "")), str(d.get("product", ""))),
        "quantity": str(d.get("requested_qty", 0)),
        "price": str(d.get("requested_price", "") or 0),
        "trigger_price": str(d.get("sl_trigger_price", "") or 0),
        "filled_quantity": str(d.get("traded_qty", 0)),
        "average_price": str(d.get("traded_price", "") or 0),
        # Smart-order leg prices + forensic context, preserved verbatim.
        "sl_trigger_price": str(d.get("sl_trigger_price", "")),
        "sl_limit_price": str(d.get("sl_limit_price", "")),
        "tgt_trigger_price": str(d.get("tgt_trigger_price", "")),
        "tgt_limit_price": str(d.get("tgt_limit_price", "")),
        "extra_info": str(d.get("extra_info", "")),
        "exchange_order_id": str(d.get("exch_order_id", "")),
        "security_id": str(d.get("security_id", "")),
    }


def from_indmoney_trade(d: dict[str, Any]) -> dict[str, Any]:
    """Normalise a ``GET /trades/{order_id}`` trade-confirmation record."""
    return {
        "orderid": str(d.get("order_id", "")),
        "symbol": str(d.get("trading_symbol", "")),
        "exchange": EXCHANGE_SEGMENT_REVERSE_MAP.get(
            str(d.get("exchange_segment", "")).upper(), str(d.get("exchange_segment", ""))
        ),
        "action": str(d.get("transaction_type", "")),
        "quantity": str(d.get("quantity", 0)),
        "price": str(d.get("price", 0)),
        "product": PRODUCT_REVERSE_MAP.get(str(d.get("product_type", "")), str(d.get("product_type", ""))),
        "timestamp": str(d.get("trade_timestamp", "")),
    }


def from_indmoney_tradebook_row(d: dict[str, Any]) -> dict[str, Any]:
    """Normalise a ``GET /trade-book`` fill record (segment-level trade book)."""
    return {
        "orderid": str(d.get("exch_order_id", "")),
        "symbol": str(d.get("scrip_code", "")),
        "exchange": "",
        "action": "",
        "quantity": str(d.get("quantity", 0)),
        "price": str(d.get("price", 0)),
        "product": "",
        "timestamp": str(d.get("trade_date", "")),
        "fill_id": str(d.get("fill_id", "")),
        "trade_serial_no": str(d.get("trade_serial_no", "")),
    }


def from_indmoney_position(d: dict[str, Any], *, product: str = "") -> dict[str, Any]:
    """Normalise an IndMoney position record (``net_positions``/``day_positions``)."""
    return {
        "symbol": str(d.get("trading_symbol", "")),
        "exchange": EXCHANGE_SEGMENT_REVERSE_MAP.get(
            str(d.get("exchange_segment", "")).upper(), str(d.get("exchange_segment", ""))
        ),
        "product": PRODUCT_REVERSE_MAP.get(str(product).upper(), str(product).upper()),
        "quantity": str(d.get("net_quantity", 0)),
        "average_price": str(d.get("average_price", 0)),
        "ltp": str(d.get("last_traded_price", 0)),
        "pnl": str(d.get("pnl_absolute", 0)),
    }


def from_indmoney_holding(d: dict[str, Any]) -> dict[str, Any]:
    """Normalise an IndMoney demat-holding record."""
    return {
        "symbol": str(d.get("trading_symbol", "")),
        "exchange": EXCHANGE_SEGMENT_REVERSE_MAP.get(
            str(d.get("exchange_segment", "")).upper(), str(d.get("exchange_segment", ""))
        ),
        "quantity": str(d.get("quantity", 0)),
        "average_price": str(d.get("average_price", 0)),
        "ltp": str(d.get("last_traded_price", 0)),
        "pnl": str(d.get("pnl_absolute", 0)),
        "pnl_percent": str(d.get("pnl_percent", 0)),
        "isin": str(d.get("isin", "")),
        "security_id": str(d.get("security_id", "")),
    }


def from_indmoney_funds(resp: Any) -> dict[str, Any]:
    """Normalise the ``GET /funds`` response.

    IndMoney reports a start-of-day balance plus per-product available balances;
    there is no single "available" figure, so ``available_balance`` carries the
    documented ``withdrawal_balance`` and the full payload is preserved under
    ``extra`` (callers MUST tolerate missing keys — contract §5).
    """
    d = unwrap(resp)
    if not isinstance(d, dict):
        return {"available_balance": "0", "used_margin": "0", "total_balance": "0", "extra": {}}
    sod = _num(d.get("sod_balance", 0))
    withdrawal = _num(d.get("withdrawal_balance", 0))
    used = round(max(sod - withdrawal, 0.0), 2)
    return {
        "available_balance": str(withdrawal),
        "used_margin": str(used),
        "total_balance": str(sod),
        "extra": d,
    }


def from_indmoney_margin(resp: Any) -> dict[str, Any]:
    """Normalise a ``GET /margin`` response into FlintTrade margin fields."""
    data = unwrap(resp)
    if not isinstance(data, dict):
        data = {}
    total = str(data.get("total_margin", 0))
    return {
        "required_margin": total,  # common key across all native adapters
        "total_margin": total,
        "span_margin": str(data.get("span_margin", 0)),
        "exposure_margin": str(data.get("exposure_margin", 0)),
        "available_balance": str(data.get("available_balance", 0)),
        "insufficient_balance": str(data.get("insufficient_balance", 0)),
        "brokerage": str(data.get("brokerage", 0)),
        "var_margin": str(data.get("var_margin", 0)),
        "delivery_margin": str(data.get("delivery_margin", 0)),
        "hedge_benefit": str(data.get("hedge_benefit", 0)),
        "charges": data.get("charges", {}) or {},
    }


def _depth_levels(rows: Any, side: str) -> list[dict[str, Any]]:
    levels: list[dict[str, Any]] = []
    if not isinstance(rows, list):
        return levels
    for row in rows:
        leg = (row or {}).get(side, {}) if isinstance(row, dict) else {}
        levels.append(
            {
                "price": parse_indian_number(leg.get("price", 0)),
                "quantity": int(parse_indian_number(leg.get("quantity", 0))),
            }
        )
    return levels


def from_indmoney_depth(record: dict[str, Any]) -> dict[str, Any]:
    """Parse a ``market_depth`` object into bid/ask ladders with numeric fields."""
    depth = (record or {}).get("market_depth", record) or {}
    rows = depth.get("depth", [])
    aggregate = depth.get("aggregate", {}) or {}
    return {
        "bids": _depth_levels(rows, "buy"),
        "asks": _depth_levels(rows, "sell"),
        "total_buy": parse_indian_number(aggregate.get("total_buy", 0)),
        "total_sell": parse_indian_number(aggregate.get("total_sell", 0)),
    }


def from_indmoney_quote(symbol: str, exchange: str, q: dict[str, Any]) -> dict[str, Any]:
    """Map one full-quote record to a Quote-shaped dict.

    The best bid/ask is taken from the first market-depth level when present.
    """
    depth = from_indmoney_depth(q)
    bids, asks = depth["bids"], depth["asks"]
    return {
        "symbol": symbol,
        "exchange": exchange,
        "ltp": _num(q.get("live_price", 0)),
        "open": _num(q.get("day_open", 0)),
        "high": _num(q.get("day_high", 0)),
        "low": _num(q.get("day_low", 0)),
        "close": _num(q.get("prev_close", 0)),
        "prev_close": _num(q.get("prev_close", 0)),
        "volume": int(_num(q.get("volume", 0))),
        "bid": bids[0]["price"] if bids else 0.0,
        "ask": asks[0]["price"] if asks else 0.0,
    }


# ---------------------------------------------------------------------------
# Historical data
# ---------------------------------------------------------------------------


def interval_to_indmoney(interval: str) -> tuple[str, int]:
    """Map a FlintTrade interval to ``(indmoney_interval, max_range_days)``.

    Args:
        interval: Canonical interval (``"1m"``, ``"1h"``, ``"D"``, …) or a raw
            IndMoney label (``"1minute"``).

    Raises:
        IndMoneyMappingError: If the interval is not in the documented table.
    """
    raw = str(interval).strip().lower()
    if raw in INTERVAL_MAP:
        return INTERVAL_MAP[raw]
    for label, max_days in INTERVAL_MAP.values():
        if raw == label:
            return label, max_days
    raise IndMoneyMappingError(
        f"Unsupported IndMoney historical interval {interval!r} — see the documented interval table"
    )


def to_epoch_ms(value: Any) -> int:
    """Coerce a timestamp input to IST Unix epoch milliseconds.

    Accepts epoch values (int/float/str of digits — seconds are auto-promoted to
    milliseconds) and ``YYYY-MM-DD`` date strings (interpreted at IST midnight,
    matching the broker's IST-epoch convention).

    Raises:
        IndMoneyMappingError: If the value cannot be interpreted.
    """
    if isinstance(value, (int, float)) or (isinstance(value, str) and value.strip().isdigit()):
        n = int(float(value))
        return n * 1000 if n < 10_000_000_000 else n  # < year 2286 in seconds → promote
    if isinstance(value, str):
        try:
            dt = datetime.strptime(value.strip(), "%Y-%m-%d").replace(tzinfo=_IST)
        except ValueError as exc:
            raise IndMoneyMappingError(f"Cannot parse timestamp {value!r} (epoch ms or YYYY-MM-DD)") from exc
        return int(dt.timestamp() * 1000)
    raise IndMoneyMappingError(f"Cannot parse timestamp {value!r} (epoch ms or YYYY-MM-DD)")


def validate_history_range(start_ms: int, end_ms: int, max_days: int) -> None:
    """Enforce the documented per-request fetch-range cap for an interval.

    Raises:
        IndMoneyMappingError: If ``end <= start`` or the range exceeds the cap.
    """
    if end_ms <= start_ms:
        raise IndMoneyMappingError("Historical end_time must be after start_time")
    if (end_ms - start_ms) > max_days * 86_400_000:
        raise IndMoneyMappingError(
            f"Historical range exceeds the documented maximum of {max_days} day(s) for this interval"
        )


def to_candles_dict(symbol: str, exchange: str, interval: str, resp: Any) -> dict[str, Any]:
    """Map a historical response (``[ts, o, h, l, c, v]`` arrays) to a Candles-shaped dict."""
    data = unwrap(resp) or {}
    candles = data.get("candles", []) if isinstance(data, dict) else []
    bars = []
    for row in candles:
        if not isinstance(row, (list, tuple)) or len(row) < 6:
            continue
        bars.append(
            {
                "timestamp": str(row[0]),
                "open": _num(row[1]),
                "high": _num(row[2]),
                "low": _num(row[3]),
                "close": _num(row[4]),
                "volume": int(_num(row[5])),
            }
        )
    return {"symbol": symbol, "exchange": exchange, "interval": str(interval), "bars": bars}


# ---------------------------------------------------------------------------
# Instruments master (CSV)
# ---------------------------------------------------------------------------


def parse_instruments_csv(text: str) -> list[dict[str, str]]:
    """Parse the instruments-master CSV into a list of row dicts.

    Args:
        text: Raw CSV body from ``GET /market/instruments``.

    Returns:
        One dict per instrument, keyed by the documented column names
        (``EXCH``, ``SEGMENT``, ``SECURITY_ID``, ``TRADING_SYMBOL``, …).
    """
    import csv  # noqa: PLC0415
    import io  # noqa: PLC0415

    reader = csv.DictReader(io.StringIO(text))
    return [dict(row) for row in reader]


# ---------------------------------------------------------------------------
# WebSocket codecs (price feed + order updates)
# ---------------------------------------------------------------------------


def subscribe_message(instruments: list[str], mode: str = "FULL", *, action: str = "subscribe") -> str:
    """Build a price-feed subscribe/unsubscribe JSON message.

    Args:
        instruments: WebSocket instrument tokens (``"NSE:2885"`` form).
        mode: FlintTrade mode (``"LTP"``/``"QUOTE"``/``"FULL"``) or a raw
            IndMoney mode (``"ltp"``/``"quote"``).
        action: ``"subscribe"`` or ``"unsubscribe"``.
    """
    ws_mode = WS_MODE_MAP.get(str(mode).upper(), str(mode).lower())
    if ws_mode not in ("ltp", "quote"):
        raise IndMoneyMappingError(f"Unsupported IndMoney feed mode {mode!r} (ltp/quote)")
    if action not in ("subscribe", "unsubscribe"):
        raise IndMoneyMappingError(f"Unsupported feed action {action!r}")
    return json.dumps({"action": action, "mode": ws_mode, "instruments": list(instruments)})


def order_updates_subscribe_message() -> str:
    """Build the one-shot order-updates feed subscription message."""
    return json.dumps({"action": "subscribe", "mode": "order_updates"})


def decode_price_frame(raw: str | bytes) -> dict[str, Any] | None:
    """Decode one price-feed frame into a normalised tick dict.

    Returns ``None`` for heartbeats, non-JSON noise, and frames without a
    recognisable ``instrument``/``data`` shape (the documented server may send
    keep-alive messages that clients should ignore).
    """
    if isinstance(raw, bytes):
        try:
            raw = raw.decode("utf-8")
        except UnicodeDecodeError:
            return None
    try:
        frame = json.loads(raw)
    except (TypeError, ValueError):
        return None
    if not isinstance(frame, dict):
        return None
    instrument = frame.get("instrument")
    data = frame.get("data")
    if not instrument or not isinstance(data, dict):
        return None  # heartbeat / control frame
    return {
        "mode": str(frame.get("mode", "")),
        "security_id": str(instrument),
        "timestamp": str(frame.get("timestamp", "")),
        "ltp": _num(data.get("ltp", data.get("live_price", 0))),
        "volume": int(_num(data.get("volume", 0))),
    }


def decode_order_update(raw: str | bytes) -> dict[str, Any] | None:
    """Decode one order-updates frame; ``None`` for heartbeats/noise."""
    if isinstance(raw, bytes):
        try:
            raw = raw.decode("utf-8")
        except UnicodeDecodeError:
            return None
    try:
        frame = json.loads(raw)
    except (TypeError, ValueError):
        return None
    if not isinstance(frame, dict) or frame.get("type") != "order":
        return None
    return {
        "orderid": str(frame.get("order_id", "")),
        "status": str(frame.get("order_status", "")),
        "filled_quantity": str(frame.get("filled_quantity", 0)),
        "remaining_quantity": str(frame.get("remaining_quantity", 0)),
        "average_price": str(frame.get("average_price", 0)),
        "timestamp": str(frame.get("timestamp", "")),
    }
