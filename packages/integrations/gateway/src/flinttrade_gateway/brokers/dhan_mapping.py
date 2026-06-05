"""Canonical-to-Dhan mapping tables.

Values are grounded in the official DhanHQ Agent Skill (``dhan-oss/dhanhq-skills``)
and the DhanHQ v2 SDK constants — see that skill's ``SKILL.md`` "Current SDK
Constants" table. These tables back the (gated) DhanAdapter's request building
and instrument resolution; keep them in lock-step with ``DHAN_CAPABILITIES``.
"""

from __future__ import annotations

import struct
from typing import Any

# Canonical order type -> Dhan order_type.
ORDER_TYPE_MAP = {
    "MARKET": "MARKET",
    "LIMIT": "LIMIT",
    "SL": "STOP_LOSS",
    "SLM": "STOP_LOSS_MARKET",
}

# Canonical product -> Dhan productType. Note Dhan uses INTRADAY/MARGIN (not
# MIS/NRML); MTF is equity-only (never F&O/commodity/currency — see the skill's
# Product-Type Rules).
PRODUCT_MAP = {
    "MIS": "INTRADAY",
    "CNC": "CNC",
    "NRML": "MARGIN",
    "MTF": "MTF",
}

# Canonical validity -> Dhan validity. GTT maps to Dhan's "forever order" family.
VALIDITY_MAP = {
    "DAY": "DAY",
    "IOC": "IOC",
    "GTT": "FOREVER",
}

# Canonical transaction side -> Dhan transaction_type.
SIDE_MAP = {
    "BUY": "BUY",
    "SELL": "SELL",
}

# Canonical exchange -> Dhan exchange_segment. Dhan collapses cash/derivative/
# currency/commodity/index into segment codes (NSE_EQ, NSE_FNO, MCX_COMM, IDX_I …).
EXCHANGE_SEGMENT_MAP = {
    "NSE": "NSE_EQ",
    "BSE": "BSE_EQ",
    "NFO": "NSE_FNO",
    "BFO": "BSE_FNO",
    "CDS": "NSE_CURRENCY",
    "BCD": "BSE_CURRENCY",
    "MCX": "MCX_COMM",
    "NSE_INDEX": "IDX_I",
    "BSE_INDEX": "IDX_I",
}

# Index underlying -> (security_id, segment). The security master is the
# authoritative source; this is a fast-path index for the common underlyings
# (skill "Instrument Resolution Rules"). Treat as a cache, not the source of truth.
INDEX_SECURITY_IDS = {
    "NIFTY": ("13", "IDX_I"),
    "NIFTY 50": ("13", "IDX_I"),
    "BANKNIFTY": ("25", "IDX_I"),
    "BANK NIFTY": ("25", "IDX_I"),
    "FINNIFTY": ("27", "IDX_I"),
    "MIDCPNIFTY": ("442", "IDX_I"),
    "SENSEX": ("51", "IDX_I"),
}


def to_dhan_segment(exchange: str) -> str:
    """Map a canonical exchange code to a Dhan ``exchange_segment``.

    Args:
        exchange: Canonical FlintTrade exchange (e.g. ``"NSE"``, ``"NFO"``).

    Returns:
        The Dhan segment code (e.g. ``"NSE_EQ"``, ``"NSE_FNO"``).

    Raises:
        KeyError: If *exchange* has no Dhan segment mapping.
    """
    return EXCHANGE_SEGMENT_MAP[exchange.upper()]


# ---------------------------------------------------------------------------
# Reverse maps (Dhan -> canonical) for response parsing
# ---------------------------------------------------------------------------

SEGMENT_TO_EXCHANGE = {
    "NSE_EQ": "NSE",
    "BSE_EQ": "BSE",
    "NSE_FNO": "NFO",
    "BSE_FNO": "BFO",
    "NSE_CURRENCY": "CDS",
    "BSE_CURRENCY": "BCD",
    "MCX_COMM": "MCX",
    "IDX_I": "NSE_INDEX",
}
DHAN_TO_ORDER_TYPE = {
    "MARKET": "MARKET",
    "LIMIT": "LIMIT",
    "STOP_LOSS": "SL",
    "STOP_LOSS_MARKET": "SL-M",
}
DHAN_TO_PRODUCT = {
    "INTRADAY": "MIS",
    "CNC": "CNC",
    "MARGIN": "NRML",
    "MTF": "MTF",
    "CO": "MIS",
    "BO": "MIS",
}


class DhanMappingError(ValueError):
    """Raised when an order cannot be translated to / from the Dhan API."""


def _num(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _norm_pricetype(pricetype: str) -> str:
    # FlintTrade uses "SL-M"; the canonical ORDER_TYPE_MAP key is "SLM".
    return str(pricetype).upper().replace("-", "")


# ---------------------------------------------------------------------------
# Request building: FlintTrade Order -> dhanhq.place_order / modify_order kwargs
# ---------------------------------------------------------------------------


def to_place_order_kwargs(order: Any, security_id: str, *, tag: str | None = None) -> dict[str, Any]:
    """Translate a FlintTrade ``Order`` into ``dhanhq.place_order`` keyword args.

    ``security_id`` is resolved by the adapter (Dhan trades by numeric id, not
    symbol). Raises :class:`DhanMappingError` for unmappable enum values.
    """
    side = str(order.action).upper()
    if side not in SIDE_MAP:
        raise DhanMappingError(f"Unsupported action {side!r}")
    ptype = _norm_pricetype(getattr(order, "pricetype", "MARKET"))
    if ptype not in ORDER_TYPE_MAP:
        raise DhanMappingError(f"Unsupported pricetype {ptype!r}")
    product = str(order.product).upper()
    if product not in PRODUCT_MAP:
        raise DhanMappingError(f"Unsupported product {product!r}")

    try:
        segment = to_dhan_segment(str(order.exchange))
    except KeyError as exc:
        raise DhanMappingError(f"No Dhan segment for exchange {order.exchange!r}") from exc

    kwargs: dict[str, Any] = {
        "security_id": str(security_id),
        "exchange_segment": segment,
        "transaction_type": SIDE_MAP[side],
        "quantity": int(_num(order.quantity, 0)),
        "order_type": ORDER_TYPE_MAP[ptype],
        "product_type": PRODUCT_MAP[product],
        "price": _num(getattr(order, "price", 0)),
        "trigger_price": _num(getattr(order, "trigger_price", 0)),
        "disclosed_quantity": int(_num(getattr(order, "disclosed_quantity", 0), 0)),
    }
    if tag:
        kwargs["tag"] = tag
    return kwargs


def _validated_core(order: Any, security_id: str) -> dict[str, Any]:
    """Shared validation + core kwargs for every Dhan order variety."""
    side = str(order.action).upper()
    if side not in SIDE_MAP:
        raise DhanMappingError(f"Unsupported action {side!r}")
    ptype = _norm_pricetype(getattr(order, "pricetype", "MARKET"))
    if ptype not in ORDER_TYPE_MAP:
        raise DhanMappingError(f"Unsupported pricetype {ptype!r}")
    product = str(order.product).upper()
    if product not in PRODUCT_MAP:
        raise DhanMappingError(f"Unsupported product {product!r}")
    try:
        segment = to_dhan_segment(str(order.exchange))
    except KeyError as exc:
        raise DhanMappingError(f"No Dhan segment for exchange {order.exchange!r}") from exc
    return {
        "security_id": str(security_id),
        "exchange_segment": segment,
        "transaction_type": SIDE_MAP[side],
        "quantity": int(_num(order.quantity, 0)),
        "order_type": ORDER_TYPE_MAP[ptype],
        "product_type": PRODUCT_MAP[product],
        "price": _num(getattr(order, "price", 0)),
    }


def to_super_order_kwargs(order: Any, security_id: str, *, tag: str | None = None) -> dict[str, Any]:
    """Translate a ``bracket``/``cover`` ``Order`` into ``dhanhq.place_super_order`` kwargs.

    A Dhan super order carries entry + target + stop-loss legs. ``cover`` orders
    set only the stop-loss leg; ``bracket`` orders set target (and optionally a
    trailing jump) too. Raises if neither a target nor a stop-loss is present.
    """
    kwargs = _validated_core(order, security_id)
    target = _num(getattr(order, "target_price", 0))
    stop_loss = _num(getattr(order, "stop_loss_price", 0))
    variety = str(getattr(order, "variety", "regular")).lower()
    if variety == "cover":
        target = 0.0  # a cover order has no target leg
    if target <= 0 and stop_loss <= 0:
        raise DhanMappingError("A super (bracket/cover) order needs a target_price or stop_loss_price")
    kwargs.update({
        "targetPrice": target,
        "stopLossPrice": stop_loss,
        "trailingJump": _num(getattr(order, "trailing_jump", 0)),
    })
    if tag:
        kwargs["tag"] = tag
    return kwargs


def to_slice_order_kwargs(order: Any, security_id: str, *, tag: str | None = None) -> dict[str, Any]:
    """Translate an ``iceberg`` ``Order`` into ``dhanhq.place_slice_order`` kwargs.

    Dhan slices a large order into freeze-quantity legs server-side, so the
    payload mirrors a regular order (the broker performs the slicing).
    """
    return to_place_order_kwargs(order, security_id, tag=tag)


def to_margin_kwargs(order: Any, security_id: str) -> dict[str, Any]:
    """Translate an ``Order`` into ``dhanhq.margin_calculator`` kwargs (pre-trade)."""
    core = _validated_core(order, security_id)
    return {
        "security_id": core["security_id"],
        "exchange_segment": core["exchange_segment"],
        "transaction_type": core["transaction_type"],
        "quantity": core["quantity"],
        "product_type": core["product_type"],
        "price": core["price"],
        "trigger_price": _num(getattr(order, "trigger_price", 0)),
    }


def from_dhan_margin(resp: Any) -> dict[str, Any]:
    """Normalise a Dhan ``/margincalculator`` response into FlintTrade fields."""
    data = unwrap(resp)
    if not isinstance(data, dict):
        data = {}
    return {
        "total_margin": str(data.get("totalMargin", data.get("total_margin", 0))),
        "span_margin": str(data.get("spanMargin", 0)),
        "exposure_margin": str(data.get("exposureMargin", 0)),
        "available_balance": str(data.get("availableBalance", 0)),
        "insufficient_balance": str(data.get("insufficientBalance", 0)),
        "brokerage": str(data.get("brokerage", 0)),
        "leverage": str(data.get("leverage", 0)),
    }


def from_dhan_expiry_list(resp: Any) -> list[str]:
    """Parse a Dhan ``/optionchain/expirylist`` response into expiry-date strings."""
    data = unwrap(resp)
    if isinstance(data, dict):
        data = data.get("data", data)
    if isinstance(data, list):
        return [str(d) for d in data]
    return []


def to_modify_order_kwargs(order_id: str, changes: dict[str, Any]) -> dict[str, Any]:
    """Translate modify ``changes`` into ``dhanhq.modify_order`` keyword args."""
    ptype = _norm_pricetype(changes.get("pricetype", changes.get("order_type", "LIMIT")))
    return {
        "order_id": str(order_id),
        "order_type": ORDER_TYPE_MAP.get(ptype, str(changes.get("order_type", "LIMIT"))),
        "leg_name": str(changes.get("leg_name", "ENTRY_LEG")),
        "quantity": int(_num(changes.get("quantity", 0), 0)),
        "price": _num(changes.get("price", 0)),
        "trigger_price": _num(changes.get("trigger_price", 0)),
        "disclosed_quantity": int(_num(changes.get("disclosed_quantity", 0), 0)),
        "validity": VALIDITY_MAP.get(str(changes.get("validity", "DAY")).upper(), "DAY"),
    }


# ---------------------------------------------------------------------------
# Response parsing (Dhan -> normalised FlintTrade-shaped dicts)
# ---------------------------------------------------------------------------


def unwrap(resp: Any) -> Any:
    """Unwrap a dhanhq ``{status, data, remarks}`` envelope; raise on failure."""
    if isinstance(resp, dict):
        if resp.get("status") == "failure":
            remarks = resp.get("remarks")
            msg = remarks.get("error_message") if isinstance(remarks, dict) else remarks
            raise DhanMappingError(f"Dhan API error: {msg or resp}")
        if "data" in resp:
            return resp["data"]
    return resp


def extract_order_id(resp: Any) -> str:
    """Pull the order id from a place/modify/cancel response."""
    data = unwrap(resp)
    if isinstance(data, dict):
        oid = data.get("orderId") or data.get("order_id") or data.get("orderid")
        if oid:
            return str(oid)
    raise DhanMappingError(f"No order id in Dhan response: {resp}")


def from_dhan_order(d: dict[str, Any]) -> dict[str, Any]:
    """Normalise a Dhan order-book record."""
    seg = d.get("exchangeSegment", "")
    return {
        "orderid": str(d.get("orderId", "")),
        "status": d.get("orderStatus", ""),
        "symbol": d.get("tradingSymbol", ""),
        "exchange": SEGMENT_TO_EXCHANGE.get(seg, seg),
        "action": d.get("transactionType", ""),
        "pricetype": DHAN_TO_ORDER_TYPE.get(d.get("orderType", ""), d.get("orderType", "")),
        "product": DHAN_TO_PRODUCT.get(d.get("productType", ""), d.get("productType", "")),
        "quantity": str(d.get("quantity", 0)),
        "price": str(d.get("price", 0)),
        "trigger_price": str(d.get("triggerPrice", 0)),
        "filled_quantity": str(d.get("filledQty", d.get("tradedQty", 0))),
        "average_price": str(d.get("averageTradedPrice", 0)),
    }


def from_dhan_position(d: dict[str, Any]) -> dict[str, Any]:
    """Normalise a Dhan position record."""
    seg = d.get("exchangeSegment", "")
    return {
        "symbol": d.get("tradingSymbol", ""),
        "exchange": SEGMENT_TO_EXCHANGE.get(seg, seg),
        "product": DHAN_TO_PRODUCT.get(d.get("productType", ""), d.get("productType", "")),
        "quantity": str(d.get("netQty", 0)),
        "average_price": str(d.get("costPrice", d.get("buyAvg", 0))),
        "buy_quantity": str(d.get("buyQty", 0)),
        "sell_quantity": str(d.get("sellQty", 0)),
        "buy_avg": str(d.get("buyAvg", 0)),
        "sell_avg": str(d.get("sellAvg", 0)),
        "pnl": str(_num(d.get("realizedProfit", 0)) + _num(d.get("unrealizedProfit", 0))),
    }


def from_dhan_holding(d: dict[str, Any]) -> dict[str, Any]:
    """Normalise a Dhan holding record."""
    return {
        "symbol": d.get("tradingSymbol", ""),
        "exchange": d.get("exchange", ""),
        "quantity": str(d.get("totalQty", d.get("availableQty", 0))),
        "average_price": str(d.get("avgCostPrice", 0)),
    }


def from_dhan_trade(d: dict[str, Any]) -> dict[str, Any]:
    """Normalise a Dhan trade-book record."""
    seg = d.get("exchangeSegment", "")
    return {
        "orderid": str(d.get("orderId", "")),
        "symbol": d.get("tradingSymbol", ""),
        "exchange": SEGMENT_TO_EXCHANGE.get(seg, seg),
        "action": d.get("transactionType", ""),
        "quantity": str(d.get("tradedQuantity", d.get("quantity", 0))),
        "price": str(d.get("tradedPrice", d.get("price", 0))),
        "product": DHAN_TO_PRODUCT.get(d.get("productType", ""), d.get("productType", "")),
        "timestamp": str(d.get("exchangeTime", d.get("createTime", ""))),
    }


def from_dhan_funds(resp: Any) -> dict[str, Any]:
    """Normalise the Dhan fund-limit response."""
    d = unwrap(resp)
    if not isinstance(d, dict):
        return {"available_balance": "0", "used_margin": "0", "total_balance": "0"}
    # Dhan's API uses the (sic) spelling "availabelBalance".
    available = d.get("availabelBalance", d.get("availableBalance", 0))
    used = d.get("utilizedAmount", 0)
    total = d.get("sodLimit", available)
    return {
        "available_balance": str(available),
        "used_margin": str(used),
        "total_balance": str(total),
        "extra": d,
    }


# ---------------------------------------------------------------------------
# Market data
# ---------------------------------------------------------------------------

# Dhan intraday candle intervals (minutes). Anything else falls back to daily.
DHAN_INTRADAY_INTERVALS = {1, 5, 15, 25, 60}


def interval_to_dhan(interval: str) -> tuple[str, int]:
    """Map a FlintTrade interval to ``(kind, minutes)`` where kind is
    ``"intraday"`` or ``"daily"`` (minutes is 0 for daily)."""
    raw = str(interval).strip().lower()
    if raw in {"d", "1d", "day", "daily"}:
        return "daily", 0
    digits = "".join(ch for ch in raw if ch.isdigit())
    minutes = int(digits) if digits else 1
    if "h" in raw:  # hourly → minutes
        minutes *= 60
    if minutes not in DHAN_INTRADAY_INTERVALS:
        # snap to the nearest supported intraday interval; on a tie prefer the
        # larger interval (fewer requests / less over-sampling).
        target = minutes
        minutes = min(DHAN_INTRADAY_INTERVALS, key=lambda m: (abs(m - target), -m))
    return "intraday", minutes


def to_candles_dict(symbol: str, exchange: str, interval: str, resp: Any) -> dict[str, Any]:
    """Map a Dhan historical response (parallel arrays) to a Candles-shaped dict."""
    d = unwrap(resp) or {}
    opens = d.get("open", []) or []
    highs = d.get("high", []) or []
    lows = d.get("low", []) or []
    closes = d.get("close", []) or []
    vols = d.get("volume", []) or []
    stamps = d.get("timestamp", []) or []
    n = min(len(opens), len(highs), len(lows), len(closes))
    bars = [
        {
            "timestamp": str(stamps[i]) if i < len(stamps) else "",
            "open": _num(opens[i]),
            "high": _num(highs[i]),
            "low": _num(lows[i]),
            "close": _num(closes[i]),
            "volume": int(_num(vols[i])) if i < len(vols) else 0,
        }
        for i in range(n)
    ]
    return {"symbol": symbol, "exchange": exchange, "interval": str(interval), "bars": bars}


def from_dhan_quote(symbol: str, exchange: str, q: dict[str, Any]) -> dict[str, Any]:
    """Map a single Dhan quote record (marketfeed/quote) to a Quote-shaped dict."""
    ohlc = q.get("ohlc", {}) or {}
    return {
        "symbol": symbol,
        "exchange": exchange,
        "ltp": _num(q.get("last_price", q.get("ltp", 0))),
        "open": _num(ohlc.get("open", 0)),
        "high": _num(ohlc.get("high", 0)),
        "low": _num(ohlc.get("low", 0)),
        "close": _num(ohlc.get("close", 0)),
        "volume": int(_num(q.get("volume", 0))),
        "oi": int(_num(q.get("oi", 0))),
    }


def quote_from_feed(segment: str, security_id: str, feed: Any) -> dict[str, Any] | None:
    """Pull one security's quote dict out of the nested marketfeed/quote payload.

    The payload is ``{segment: {security_id: {...}}}`` after :func:`unwrap`.
    """
    data = unwrap(feed)
    if not isinstance(data, dict):
        return None
    by_seg = data.get(segment)
    if not isinstance(by_seg, dict):
        return None
    rec = by_seg.get(str(security_id))
    return rec if isinstance(rec, dict) else None


def _leg(leg: dict[str, Any], side: str) -> dict[str, Any]:
    """Map one CE/PE leg of a Dhan option-chain strike to ce_*/pe_* fields."""
    greeks = leg.get("greeks", {}) or {}
    return {
        f"{side}_ltp": _num(leg.get("last_price", 0)),
        f"{side}_oi": int(_num(leg.get("oi", 0))),
        f"{side}_volume": int(_num(leg.get("volume", 0))),
        f"{side}_iv": _num(leg.get("implied_volatility", 0)),
        f"{side}_delta": _num(greeks.get("delta", 0)),
        f"{side}_gamma": _num(greeks.get("gamma", 0)),
        f"{side}_theta": _num(greeks.get("theta", 0)),
        f"{side}_vega": _num(greeks.get("vega", 0)),
        f"{side}_bid": _num(leg.get("top_bid_price", 0)),
        f"{side}_ask": _num(leg.get("top_ask_price", 0)),
    }


# ---------------------------------------------------------------------------
# Binary market feed (live tick stream)
# ---------------------------------------------------------------------------

# Dhan v2 binary feed response codes (first byte of each packet).
DHAN_FEED_TICKER = 15
DHAN_FEED_QUOTE = 17

# Feed exchange-segment byte → canonical exchange.
FEED_SEGMENT_TO_EXCHANGE = {
    0: "NSE_INDEX",
    1: "NSE",
    2: "NFO",
    3: "CDS",
    4: "BSE",
    5: "MCX",
    7: "BCD",
    8: "BFO",
}


def decode_dhan_tick(data: bytes) -> dict[str, Any] | None:
    """Decode one Dhan binary market-feed packet into a normalised tick dict.

    Dhan streams a packed binary frame whose first byte is a response code
    (15 = Ticker, 17 = Quote). The header is ``<BHBIf`` =
    code, message-length, exchange-segment, security-id, LTP. Returns None for
    short or unrecognised packets.
    """
    if data is None or len(data) < 16:
        return None
    code = struct.unpack_from("<B", data, 0)[0]
    if code == DHAN_FEED_TICKER:
        _, _, seg, security_id, ltp, _ltt = struct.unpack_from("<BHBIfI", data, 0)
        return {
            "code": code,
            "security_id": str(security_id),
            "exchange": FEED_SEGMENT_TO_EXCHANGE.get(seg, ""),
            "ltp": round(ltp, 2),
        }
    if code == DHAN_FEED_QUOTE and len(data) >= 50:
        fields = struct.unpack_from("<BHBIfHIfIIIffff", data, 0)
        # 0 code, 1 msglen, 2 seg, 3 security_id, 4 ltp, 5 ltq, 6 ltt, 7 atp,
        # 8 volume, 9 total_sell_qty, 10 total_buy_qty, 11 open, 12 close, 13 high, 14 low
        return {
            "code": code,
            "security_id": str(fields[3]),
            "exchange": FEED_SEGMENT_TO_EXCHANGE.get(fields[2], ""),
            "ltp": round(fields[4], 2),
            "volume": int(fields[8]),
            "open": round(fields[11], 2),
            "close": round(fields[12], 2),
            "high": round(fields[13], 2),
            "low": round(fields[14], 2),
        }
    return None


def to_option_chain_dict(underlying: str, exchange: str, resp: Any) -> dict[str, Any]:
    """Map a Dhan option-chain response to an OptionChain-shaped dict.

    Dhan returns ``data.oc`` keyed by strike string → ``{ce:{...}, pe:{...}}``.
    """
    data = unwrap(resp) or {}
    oc = data.get("oc", {}) or {}
    strikes: list[dict[str, Any]] = []
    for strike_str, legs in sorted(oc.items(), key=lambda kv: _num(kv[0])):
        if not isinstance(legs, dict):
            continue
        row: dict[str, Any] = {"strike_price": _num(strike_str)}
        row.update(_leg(legs.get("ce", {}) or {}, "ce"))
        row.update(_leg(legs.get("pe", {}) or {}, "pe"))
        strikes.append(row)
    return {"underlying": underlying, "exchange": exchange, "strikes": strikes}
