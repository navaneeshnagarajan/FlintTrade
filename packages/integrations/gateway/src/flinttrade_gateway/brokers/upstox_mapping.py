"""Pure FlintTrade <-> Upstox v2 mapping.

Kept separate from the adapter so order translation and response parsing are
fully unit-testable without the upstox-python SDK or live credentials. Field
names / enum codes follow the Upstox v2 API (PlaceOrderRequest fields verified
against the staged SDK model).
"""

from __future__ import annotations

from typing import Any

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


class UpstoxMappingError(ValueError):
    """Raised when an order cannot be translated to / from the Upstox API."""


def _num(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _norm_pricetype(pricetype: str) -> str:
    return str(pricetype).upper()


def to_place_order_params(order: Any, instrument_token: str, *, tag: str | None = None) -> dict[str, Any]:
    """Translate a FlintTrade ``Order`` into Upstox ``PlaceOrderRequest`` kwargs.

    ``instrument_token`` is resolved by the adapter (Upstox trades by instrument
    token, e.g. ``"NSE_EQ|INE002A01018"``). Raises for unmappable enum values.
    """
    side = str(order.action).upper()
    if side not in SIDE_TO_UPSTOX:
        raise UpstoxMappingError(f"Unsupported action {side!r}")
    ptype = _norm_pricetype(getattr(order, "pricetype", "MARKET"))
    if ptype not in ORDER_TYPE_TO_UPSTOX:
        raise UpstoxMappingError(f"Unsupported pricetype {ptype!r}")
    product = str(order.product).upper()
    if product not in PRODUCT_TO_UPSTOX:
        raise UpstoxMappingError(f"Unsupported product {product!r}")

    # Safety: Upstox v2 does not expose bracket/cover/iceberg via place_order
    # (cover + GTT are separate endpoints, bracket was retired). Refuse an
    # advanced variety here rather than silently placing it as a plain order —
    # a bracket order that quietly loses its stop-loss leg would be a real risk.
    variety = str(getattr(order, "variety", "regular")).lower()
    if variety not in ("regular", ""):
        raise UpstoxMappingError(
            f"Upstox does not place variety {variety!r} via place_order "
            "(its cover/GTT order endpoints are a separate wave)"
        )

    return {
        "instrument_token": str(instrument_token),
        "quantity": int(_num(order.quantity, 0)),
        "product": PRODUCT_TO_UPSTOX[product],
        "validity": "DAY",
        "price": _num(getattr(order, "price", 0)),
        "order_type": ORDER_TYPE_TO_UPSTOX[ptype],
        "transaction_type": SIDE_TO_UPSTOX[side],
        "disclosed_quantity": int(_num(getattr(order, "disclosed_quantity", 0), 0)),
        "trigger_price": _num(getattr(order, "trigger_price", 0)),
        "is_amo": False,
        "tag": tag or "",
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
        "validity": str(changes.get("validity", "DAY")).upper(),
    }


def _exchange_of_token(instrument_token: str) -> str:
    seg = str(instrument_token).split("|", 1)[0]
    return UPSTOX_TO_EXCHANGE.get(seg, seg)


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
    return {
        "orderid": str(d.get("order_id", "")),
        "status": d.get("status", ""),
        "symbol": d.get("trading_symbol", d.get("tradingsymbol", "")),
        "exchange": d.get("exchange", _exchange_of_token(d.get("instrument_token", ""))),
        "action": d.get("transaction_type", ""),
        "pricetype": UPSTOX_TO_ORDER_TYPE.get(d.get("order_type", ""), d.get("order_type", "")),
        "product": UPSTOX_TO_PRODUCT.get(d.get("product", ""), d.get("product", "")),
        "quantity": str(d.get("quantity", 0)),
        "price": str(d.get("price", 0)),
        "trigger_price": str(d.get("trigger_price", 0)),
        "filled_quantity": str(d.get("filled_quantity", 0)),
        "average_price": str(d.get("average_price", 0)),
    }


def from_upstox_position(d: dict[str, Any]) -> dict[str, Any]:
    """Normalise an Upstox position record."""
    return {
        "symbol": d.get("trading_symbol", d.get("tradingsymbol", "")),
        "exchange": d.get("exchange", _exchange_of_token(d.get("instrument_token", ""))),
        "product": UPSTOX_TO_PRODUCT.get(d.get("product", ""), d.get("product", "")),
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
        "product": UPSTOX_TO_PRODUCT.get(d.get("product", ""), d.get("product", "")),
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
# takes unit in {minutes, hours, days, weeks, months} + a numeric interval.
_UNIT_BY_SUFFIX = {"m": "minutes", "h": "hours", "d": "days", "w": "weeks", "mo": "months"}


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
