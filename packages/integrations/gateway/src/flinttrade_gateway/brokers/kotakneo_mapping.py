"""Pure FlintTrade <-> Kotak Neo (NEO OMS) mapping.

Kept separate from the adapter so order translation and the (cryptically-keyed)
NEO response parsing are fully unit-testable without the ``neo-api-client`` SDK
or live credentials. Field names / enum codes follow the Kotak Neo v2 trade API
as documented in the staged SDK (``settings.py`` lookup tables) and the local
broker docs (``.local/reference/broker-docs/kotak-neo/sdk-docs/``).

NEO is an OMS-style API: order/position records use terse abbreviated keys
(``nOrdNo``, ``trdSym``, ``exSeg``, ``trnsTp``, ``prcTp`` …) and positions are
reported as cumulative buy/sell quantities + amounts rather than a single net
line, so the net quantity, average price and realised P&L are derived here
(``Positions.md``); the unrealised leg is left to merge from a live quote.

Streaming: the HSM market feed and HSI order feed deliver JSON frames whose
key vocabulary is the SDK's ``stock_key_mapping`` / ``index_key_mapping``
(``settings.py``) — the decoders here (``decode_kotak_feed`` /
``decode_kotak_order_feed``) normalise those frames so the adapter's
``stream()`` / ``order_stream()`` stay SDK-free and unit-testable against
synthetic frames.
"""

from __future__ import annotations

import json
from typing import Any

# Exchange -> NEO exchange-segment code (from settings.exchange_segment).
EXCHANGE_TO_KOTAK = {
    "NSE": "nse_cm",
    "BSE": "bse_cm",
    "NFO": "nse_fo",
    "BFO": "bse_fo",
    "CDS": "cde_fo",
    "BCD": "bcs-fo",
    "MCX": "mcx_fo",
}
KOTAK_TO_EXCHANGE = {v: k for k, v in EXCHANGE_TO_KOTAK.items()}

# FlintTrade product -> NEO product. NEO also exposes INTRADAY/CO/BO/MTF; we map
# the reverse codes back to the FlintTrade trio.
PRODUCT_TO_KOTAK = {"MIS": "MIS", "CNC": "CNC", "NRML": "NRML"}
KOTAK_TO_PRODUCT = {
    "MIS": "MIS",
    "INTRADAY": "MIS",
    "CO": "MIS",
    "BO": "MIS",
    "CNC": "CNC",
    "NRML": "NRML",
    "MTF": "NRML",
}

# FlintTrade pricetype -> NEO order_type code (settings.order_type).
ORDER_TYPE_TO_KOTAK = {"MARKET": "MKT", "LIMIT": "L", "SL": "SL", "SL-M": "SL-M"}
KOTAK_TO_ORDER_TYPE = {"MKT": "MARKET", "L": "LIMIT", "SL": "SL", "SL-M": "SL-M"}

# NEO transaction type is single-letter.
SIDE_TO_KOTAK = {"BUY": "B", "SELL": "S"}
KOTAK_TO_SIDE = {"B": "BUY", "S": "SELL"}

# Order validity codes (Place_Order.md): DAY everywhere, IOC (not for CO),
# GTC/GTD (MCX only), EOS (BSE + MCX only).
VALIDITY_ALLOWED = frozenset({"DAY", "IOC", "GTC", "EOS", "GTD"})

# limits() filter enums (settings.segment_limits / exchange_limits / product_limits).
LIMITS_SEGMENTS = frozenset({"CASH", "CUR", "FO", "ALL"})
LIMITS_EXCHANGES = frozenset({"NSE", "BSE", "ALL"})
LIMITS_PRODUCTS = frozenset({"CNC", "MIS", "NRML", "ALL"})

# REST quotes quote_type values (Quotes.md).
QUOTE_TYPES = frozenset({"all", "depth", "ohlc", "ltp", "oi", "52w", "circuit_limits", "scrip_details"})

# HSM live-feed terse keys -> long names (settings.stock_key_mapping).
STOCK_FEED_KEYS = {
    "ltt": "last_traded_time",
    "v": "volume",
    "ltp": "last_traded_price",
    "ltq": "last_traded_quantity",
    "tbq": "total_buy_quantity",
    "tsq": "total_sell_quantity",
    "bp": "buy_price",
    "sp": "sell_price",
    "bq": "buy_quantity",
    "bs": "sell_quantity",
    "ap": "average_price",
    "oi": "open_interest",
    "lo": "low",
    "h": "high",
    "lcl": "lower_circuit_limit",
    "ucl": "upper_circuit_limit",
    "yh": "52week_high",
    "yl": "52week_low",
    "op": "open",
    "c": "close",
    "cng": "change",
    "nc": "net_change_percentage",
    "to": "total_traded_value",
    "tk": "instrument_token",
    "e": "exchange_segment",
    "ts": "trading_symbol",
}

# HSM index-feed terse keys -> long names (settings.index_key_mapping).
INDEX_FEED_KEYS = {
    "iv": "last_traded_price",
    "ic": "prev_day_close",
    "tvalue": "timestamp",
    "highPrice": "high",
    "lowPrice": "low",
    "openingPrice": "open",
    "cng": "change",
    "nc": "net_change_percentage",
    "tk": "instrument_token",
    "e": "exchange_segment",
}


class KotakNeoMappingError(ValueError):
    """Raised when an order cannot be translated to / from the NEO API."""


def _num(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _norm(value: Any, default: str = "") -> str:
    return str(value).upper() if value is not None else default


def to_place_order_params(order: Any, trading_symbol: str, *, tag: str | None = None) -> dict[str, Any]:
    """Translate a FlintTrade ``Order`` into ``NeoAPI.place_order`` kwargs.

    ``trading_symbol`` is the NEO scrip symbol (e.g. ``"IDEA-EQ"``), resolved by
    the adapter via ``search_scrip``. NEO expects every numeric field as a string.
    Raises ``KotakNeoMappingError`` for unmappable enum values.
    """
    side = _norm(order.action)
    if side not in SIDE_TO_KOTAK:
        raise KotakNeoMappingError(f"Unsupported action {side!r}")
    ptype = _norm(getattr(order, "pricetype", "MARKET"))
    if ptype not in ORDER_TYPE_TO_KOTAK:
        raise KotakNeoMappingError(f"Unsupported pricetype {ptype!r}")
    product = _norm(order.product)
    if product not in PRODUCT_TO_KOTAK:
        raise KotakNeoMappingError(f"Unsupported product {product!r}")
    exchange = _norm(order.exchange)
    if exchange not in EXCHANGE_TO_KOTAK:
        raise KotakNeoMappingError(f"Unsupported exchange {exchange!r}")

    params: dict[str, Any] = {
        "exchange_segment": EXCHANGE_TO_KOTAK[exchange],
        "product": PRODUCT_TO_KOTAK[product],
        "price": str(_num(getattr(order, "price", 0))),
        "order_type": ORDER_TYPE_TO_KOTAK[ptype],
        "quantity": str(int(_num(order.quantity, 0))),
        "validity": "DAY",
        "trading_symbol": str(trading_symbol),
        "transaction_type": SIDE_TO_KOTAK[side],
        "trigger_price": str(_num(getattr(order, "trigger_price", 0))),
        "disclosed_quantity": str(int(_num(getattr(order, "disclosed_quantity", 0), 0))),
        "amo": "NO",
    }

    # Advanced varieties: NEO places bracket (BO) and cover (CO) orders through
    # the SAME place_order call, overriding the product code and attaching the
    # target / stop-loss / trailing legs; an AMO is a regular order with the
    # ``amo`` flag set. NEO has no iceberg/slice endpoint (only
    # disclosed_quantity), so that variety is refused.
    variety = str(getattr(order, "variety", "regular")).lower()
    if variety == "amo":
        params["amo"] = "YES"
    elif variety in ("bracket", "cover"):
        _apply_variety_legs(order, variety, params)
    elif variety not in ("regular", ""):
        raise KotakNeoMappingError(f"Kotak Neo does not support order variety {variety!r}")

    if tag:
        params["tag"] = str(tag)
    return params


def _apply_variety_legs(order: Any, variety: str, params: dict[str, Any]) -> None:
    """Attach bracket/cover legs onto ``params`` (shared by place + margin).

    NEO leg-type / flag enums are forwarded verbatim to the OMS (slt/sot/tlt),
    so they MUST match the documented values: square_off_type/stop_loss_type
    ∈ {"Absolute","Ticks"} and trailing_stop_loss ∈ {"Y","N"} (Place_Order.md).
    Sending "abs"/"YES" silently drops the protective legs on a live order.
    """
    target = _num(getattr(order, "target_price", 0))
    stop_loss = _num(getattr(order, "stop_loss_price", 0))
    if variety == "cover":
        target = 0.0  # a cover order has only a stop-loss leg
    if target <= 0 and stop_loss <= 0:
        raise KotakNeoMappingError("A bracket/cover order needs a target_price or stop_loss_price")
    params["product"] = "BO" if variety == "bracket" else "CO"
    params["stop_loss_value"] = str(stop_loss)
    params["stop_loss_type"] = "Absolute"
    if target > 0:
        params["square_off_value"] = str(target)
        params["square_off_type"] = "Absolute"
    trailing = _num(getattr(order, "trailing_jump", 0))
    if trailing > 0:
        params["trailing_stop_loss"] = "Y"
        params["trailing_sl_value"] = str(trailing)


def to_modify_order_params(order_id: str, changes: dict[str, Any]) -> dict[str, Any]:
    """Translate modify ``changes`` into ``NeoAPI.modify_order`` kwargs.

    The base surface (order-id method, ``Modify_Order.md`` "Method 2") is always
    emitted; the quick-method extras (``instrument_token`` / ``exchange_segment``
    / ``product`` / ``trading_symbol`` / ``transaction_type``) plus the ``amo`` /
    ``market_protection`` / ``filled_quantity`` / ``dd`` flags are forwarded only
    when present in ``changes``, so the SDK picks the right modification path.
    """
    ptype = _norm(changes.get("pricetype", changes.get("order_type", "LIMIT")))
    validity = str(changes.get("validity", "DAY")).upper()
    if validity not in VALIDITY_ALLOWED:
        raise KotakNeoMappingError(f"Unsupported validity {validity!r}")
    params: dict[str, Any] = {
        "order_id": str(order_id),
        "order_type": ORDER_TYPE_TO_KOTAK.get(ptype, str(changes.get("order_type", "L"))),
        "price": str(_num(changes.get("price", 0))),
        "quantity": str(int(_num(changes.get("quantity", 0), 0))),
        "validity": validity,
        "trigger_price": str(_num(changes.get("trigger_price", 0))),
        "disclosed_quantity": str(int(_num(changes.get("disclosed_quantity", 0), 0))),
    }
    if changes.get("amo") is not None:
        amo = changes["amo"]
        params["amo"] = ("YES" if amo else "NO") if isinstance(amo, bool) else _norm(amo)
    if changes.get("instrument_token"):
        params["instrument_token"] = str(changes["instrument_token"])
    if changes.get("exchange_segment"):
        seg = _norm(changes["exchange_segment"])
        params["exchange_segment"] = EXCHANGE_TO_KOTAK.get(seg, str(changes["exchange_segment"]))
    if changes.get("product"):
        prod = _norm(changes["product"])
        params["product"] = PRODUCT_TO_KOTAK.get(prod, prod)
    if changes.get("trading_symbol"):
        params["trading_symbol"] = str(changes["trading_symbol"])
    if changes.get("transaction_type") or changes.get("action"):
        side = _norm(changes.get("transaction_type", changes.get("action")))
        params["transaction_type"] = SIDE_TO_KOTAK.get(side, side)
    if changes.get("filled_quantity") is not None:
        params["filled_quantity"] = str(int(_num(changes["filled_quantity"], 0)))
    if changes.get("market_protection") is not None:
        params["market_protection"] = str(changes["market_protection"])
    if changes.get("dd"):
        params["dd"] = str(changes["dd"])
    return params


def ensure_ok(resp: Any) -> Any:
    """Raise ``KotakNeoMappingError`` if ``resp`` is a NEO error envelope.

    The neo-api-client returns errors as data, never raises: ``{"Error": ...}``
    (SDK exception wrapper), ``{"Error Message": ...}`` (2FA not complete),
    ``{"error": [...]}`` (validation) and ``{"stat": "Not_Ok", "errMsg": ...}``
    (OMS reject). Writes MUST surface those instead of silently succeeding.
    """
    if isinstance(resp, dict):
        for key in ("Error", "Error Message", "error"):
            if resp.get(key):
                raise KotakNeoMappingError(f"Kotak Neo error: {resp[key]!r}")
        if str(resp.get("stat", "Ok")).lower() not in ("ok", ""):
            raise KotakNeoMappingError(
                f"Kotak Neo rejected the request: {resp.get('errMsg', resp)!r}"
            )
    return resp


def extract_order_id(resp: dict[str, Any]) -> str:
    """Pull the order number from a NEO place/modify response.

    NEO returns ``{"stat": "Ok", "nOrdNo": "...", "stCode": 200}`` (the order id
    may also be nested under ``data`` on some gateway builds).
    """
    if not isinstance(resp, dict):
        raise KotakNeoMappingError(f"Unexpected NEO response: {resp!r}")
    oid = resp.get("nOrdNo")
    if not oid:
        data = resp.get("data")
        if isinstance(data, dict):
            oid = data.get("nOrdNo") or data.get("orderId")
    if not oid:
        raise KotakNeoMappingError(f"No order id in NEO response: {resp!r}")
    return str(oid)


def _exchange_of(d: dict[str, Any]) -> str:
    seg = str(d.get("exSeg", ""))
    return KOTAK_TO_EXCHANGE.get(seg, seg)


def from_kotak_order(d: dict[str, Any]) -> dict[str, Any]:
    """Normalise a NEO order-report / order-history record.

    Both surfaces share the terse OMS vocabulary (``Order_report.md`` /
    ``Order_history.md``); history rows carry ``exchTmstp``+``dclQty`` where the
    report uses ``ordDtTm``+``dscQty``, so each field falls back across both.
    """
    return {
        "orderid": str(d.get("nOrdNo", "")),
        "status": d.get("ordSt", d.get("stat", "")),
        "symbol": d.get("trdSym", d.get("sym", "")),
        "exchange": _exchange_of(d),
        "action": KOTAK_TO_SIDE.get(str(d.get("trnsTp", "")), str(d.get("trnsTp", ""))),
        "pricetype": KOTAK_TO_ORDER_TYPE.get(str(d.get("prcTp", "")), str(d.get("prcTp", ""))),
        "product": KOTAK_TO_PRODUCT.get(str(d.get("prod", "")), str(d.get("prod", ""))),
        "quantity": str(d.get("qty", 0)),
        "price": str(d.get("prc", 0)),
        "trigger_price": str(d.get("trgPrc", 0)),
        "filled_quantity": str(d.get("fldQty", 0)),
        "average_price": str(d.get("avgPrc", 0)),
        "timestamp": str(d.get("ordDtTm", d.get("exchTmstp", d.get("flDtTm", "")))),
        "validity": str(d.get("vldt", d.get("ordDur", ""))),
        "disclosed_quantity": str(d.get("dscQty", d.get("dclQty", 0))),
        "rejection_reason": "" if str(d.get("rejRsn", "")) in ("--", "NA") else str(d.get("rejRsn", "")),
        "exchange_order_id": "" if str(d.get("exOrdId", d.get("exchOrdId", ""))) == "NA"
        else str(d.get("exOrdId", d.get("exchOrdId", ""))),
        "tag": str(d.get("GuiOrdId", "") or ""),
    }


def order_history_rows(resp: Any) -> list[dict[str, Any]]:
    """Unwrap the doubly-nested ``order_history`` envelope into raw OMS rows.

    The SDK returns ``{"data": {"stat": "Ok", "stCode": 200, "data": [rows]}}``
    (``Order_history.md``); some gateway builds skip the outer wrapper. Rows are
    the order's state transitions, OMS-newest-first.
    """
    if not isinstance(resp, dict):
        return []
    inner = resp.get("data", resp)
    if isinstance(inner, dict):
        inner = inner.get("data", [])
    return [r for r in inner if isinstance(r, dict)] if isinstance(inner, list) else []


def from_kotak_trade(d: dict[str, Any]) -> dict[str, Any]:
    """Normalise a NEO trade-report record."""
    return {
        "orderid": str(d.get("nOrdNo", "")),
        "symbol": d.get("trdSym", d.get("sym", "")),
        "exchange": _exchange_of(d),
        "action": KOTAK_TO_SIDE.get(str(d.get("trnsTp", "")), str(d.get("trnsTp", ""))),
        "quantity": str(d.get("fldQty", d.get("qty", 0))),
        "price": str(d.get("avgPrc", d.get("flPrc", 0))),
        "product": KOTAK_TO_PRODUCT.get(str(d.get("prod", "")), str(d.get("prod", ""))),
        "timestamp": str(d.get("flDtTm", d.get("exTm", ""))),
    }


def _ratio(num: Any, den: Any) -> float:
    """``num/den`` defaulting to 1.0 (NEO price-denomination ratios genNum/genDen
    and prcNum/prcDen are 1 for equity; non-1 only for some commodity/currency)."""
    n = _num(num, 1.0)
    d = _num(den, 1.0)
    return (n / d) if d else 1.0


def _fmt_qty(value: float) -> str:
    """Format a quantity as an integer string (positions are whole units)."""
    return str(int(round(value)))


def from_kotak_position(d: dict[str, Any]) -> dict[str, Any]:
    """Normalise a NEO position record.

    NEO reports cumulative carry-forward + intraday buy/sell legs rather than a
    net line, so the net quantity, average price and **realised** P&L are derived
    here (``Positions.md``).

    Quantity is kept in raw traded units (shares/contracts), NOT divided by
    ``lotSz`` — FlintTrade reports total quantity across every adapter (Dhan /
    OpenAlgo do the same), so a lots-based F&O display would be an adapter-level
    inconsistency; that normalisation, if ever wanted, belongs at the Position
    layer. Average price is per-unit: ``amount / (qty * genNum/genDen *
    prcNum/prcDen)`` rounded to the scrip ``precision`` (the ``multiplier``/
    ``lotSz`` terms in the doc formula cancel once qty stays in raw units).

    P&L is the **realised** component only — ``matched_qty * (sell_avg -
    buy_avg)`` where ``matched_qty = min(buy_qty, sell_qty)`` — which is unit-safe
    regardless of lot size. The open leg's unrealised P&L needs a live LTP not in
    the record and is left to merge from quotes (``ltp`` is ``0``; none is
    fabricated). This matches Dhan (realised+unrealised) / Upstox (broker pnl)
    once a quote is merged.
    """
    price_div = _ratio(d.get("genNum", 1), d.get("genDen", 1)) * _ratio(d.get("prcNum", 1), d.get("prcDen", 1))
    price_div = price_div or 1.0
    # Clamp to a sane decimal-place range: a malformed/negative precision would
    # otherwise make the avg-price f-string raise ValueError and abort the whole
    # positions() fetch instead of degrading one row.
    precision = max(0, min(int(_num(d.get("precision", 2), 2)), 8))

    buy_qty = _num(d.get("cfBuyQty", 0)) + _num(d.get("flBuyQty", 0))
    sell_qty = _num(d.get("cfSellQty", 0)) + _num(d.get("flSellQty", 0))
    buy_amt = _num(d.get("cfBuyAmt", 0)) + _num(d.get("buyAmt", 0))
    sell_amt = _num(d.get("cfSellAmt", 0)) + _num(d.get("sellAmt", 0))
    net_qty = buy_qty - sell_qty

    buy_avg = buy_amt / (buy_qty * price_div) if buy_qty else 0.0
    sell_avg = sell_amt / (sell_qty * price_div) if sell_qty else 0.0
    if buy_qty > sell_qty:
        avg_price = buy_avg
    elif sell_qty > buy_qty:
        avg_price = sell_avg
    else:
        avg_price = 0.0

    matched = min(buy_qty, sell_qty)
    # `... or 0.0` normalises Python negative zero: an open long (matched == 0,
    # buy_avg > 0) yields 0.0 * -buy_avg == -0.0, which would render as "-0.00".
    realised_pnl = matched * (sell_avg - buy_avg) or 0.0

    return {
        "symbol": d.get("trdSym", d.get("sym", "")),
        "exchange": _exchange_of(d),
        "product": KOTAK_TO_PRODUCT.get(str(d.get("prod", "")), str(d.get("prod", ""))),
        "quantity": _fmt_qty(net_qty),
        "average_price": f"{avg_price:.{precision}f}",
        "ltp": "0",
        "pnl": f"{realised_pnl:.2f}",
        "buy_quantity": _fmt_qty(buy_qty),
        "sell_quantity": _fmt_qty(sell_qty),
    }


def from_kotak_holding(d: dict[str, Any]) -> dict[str, Any]:
    """Normalise a NEO holding record.

    The holdings endpoint uses longer keys than the OMS order/position feed
    (``displaySymbol``/``averagePrice``/``closingPrice`` …). ``closingPrice`` is
    the previous-day close (a per-share price), surfaced as ``ltp`` until a live
    quote is merged — we do NOT fall back to ``mktValue`` (that is the aggregate
    market value of the holding, which would be a per-share price inflated by the
    quantity factor).
    """
    seg = str(d.get("exchangeSegment", ""))
    exchange = KOTAK_TO_EXCHANGE.get(seg, seg) if seg else _exchange_of(d)
    return {
        "symbol": d.get("displaySymbol", d.get("symbol", d.get("trdSym", ""))),
        "exchange": exchange,
        "quantity": str(d.get("quantity", d.get("sellableQuantity", 0))),
        "average_price": str(d.get("averagePrice", d.get("avgPrc", 0))),
        "ltp": str(d.get("closingPrice", 0)),
        "pnl": str(d.get("pnl", 0)),
    }


def from_kotak_scrip(rec: dict[str, Any]) -> dict[str, Any]:
    """Normalise one NEO ``search_scrip`` record into a scrip-lookup dict.

    NEO returns scrip metadata with ``p``-prefixed keys; the ``pTrdSymbol`` is the
    trading symbol the order endpoints expect and ``pSymbol`` is the token.
    """
    seg = str(rec.get("pExchSeg", ""))
    return {
        "trading_symbol": rec.get("pTrdSymbol", ""),
        "token": str(rec.get("pSymbol", "")),
        "name": rec.get("pSymbolName", rec.get("pDesc", "")),
        "exchange": KOTAK_TO_EXCHANGE.get(seg, seg),
        "isin": rec.get("pISIN", ""),
        "lot_size": str(rec.get("lLotSize", 0)),
        "tick_size": str(rec.get("dTickSize", 0)),
        "option_type": rec.get("pOptionType") or "",
    }


def to_margin_params(order: Any, trading_symbol: str) -> dict[str, Any]:
    """Build ``NeoAPI.margin_required`` kwargs from an ``Order`` (pre-trade).

    Mirrors the place-order translation: a bracket/cover variety overrides the
    product to BO/CO and carries its stop-loss / target / trailing legs so the
    estimate covers the whole order, and a stop order forwards its
    ``trigger_price`` (``Margin_Required.md``).
    """
    side = _norm(order.action)
    if side not in SIDE_TO_KOTAK:
        raise KotakNeoMappingError(f"Unsupported action {side!r}")
    ptype = _norm(getattr(order, "pricetype", "MARKET"))
    if ptype not in ORDER_TYPE_TO_KOTAK:
        raise KotakNeoMappingError(f"Unsupported pricetype {ptype!r}")
    product = _norm(order.product)
    if product not in PRODUCT_TO_KOTAK:
        raise KotakNeoMappingError(f"Unsupported product {product!r}")
    exchange = _norm(order.exchange)
    if exchange not in EXCHANGE_TO_KOTAK:
        raise KotakNeoMappingError(f"Unsupported exchange {exchange!r}")
    params: dict[str, Any] = {
        "exchange_segment": EXCHANGE_TO_KOTAK[exchange],
        "price": str(_num(getattr(order, "price", 0))),
        "order_type": ORDER_TYPE_TO_KOTAK[ptype],
        "product": PRODUCT_TO_KOTAK[product],
        "quantity": str(int(_num(order.quantity, 0))),
        "instrument_token": str(trading_symbol),
        "transaction_type": SIDE_TO_KOTAK[side],
    }
    trigger = _num(getattr(order, "trigger_price", 0))
    if trigger > 0:
        params["trigger_price"] = str(trigger)
    variety = str(getattr(order, "variety", "regular")).lower()
    if variety in ("bracket", "cover"):
        _apply_variety_legs(order, variety, params)
    return params


def to_limits_params(segment: str = "ALL", exchange: str = "ALL", product: str = "ALL") -> dict[str, str]:
    """Validate + build the ``NeoAPI.limits`` filter kwargs (``Limits.md``)."""
    seg, exch, prod = _norm(segment, "ALL"), _norm(exchange, "ALL"), _norm(product, "ALL")
    if seg not in LIMITS_SEGMENTS:
        raise KotakNeoMappingError(f"Unsupported limits segment {segment!r}")
    if exch not in LIMITS_EXCHANGES:
        raise KotakNeoMappingError(f"Unsupported limits exchange {exchange!r}")
    if prod not in LIMITS_PRODUCTS:
        raise KotakNeoMappingError(f"Unsupported limits product {product!r}")
    return {"segment": seg, "exchange": exch, "product": prod}


def from_kotak_margin(resp: dict[str, Any]) -> dict[str, Any]:
    """Normalise a NEO ``margin_required`` response into FlintTrade margin fields."""
    data = resp.get("data", resp) if isinstance(resp, dict) else {}
    if not isinstance(data, dict):
        data = {}
    return {
        "required_margin": f"{_num(data.get('reqdMrgn', 0)):.2f}",
        "order_margin": f"{_num(data.get('ordMrgn', 0)):.2f}",
        "available_balance": f"{_num(data.get('avlCash', data.get('avlMrgn', 0))):.2f}",
        "insufficient_balance": f"{_num(data.get('insufFund', 0)):.2f}",
        "rms_validated": str(data.get("rmsVldtd", "")),
    }


def to_quote_tokens(resolved: list[tuple[str, str]]) -> list[dict[str, str]]:
    """Build the NEO ``quotes`` request from ``(trading_symbol, exchange)`` pairs.

    NEO's ``quotes(instrument_tokens=[...])`` takes a list of
    ``{"instrument_token": <scrip>, "exchange_segment": <seg>}`` dicts.
    """
    tokens: list[dict[str, str]] = []
    for trading_symbol, exchange in resolved:
        ex = _norm(exchange)
        tokens.append({
            "instrument_token": str(trading_symbol),
            "exchange_segment": EXCHANGE_TO_KOTAK.get(ex, ex.lower()),
        })
    return tokens


def from_kotak_quote(rec: dict[str, Any]) -> dict[str, Any]:
    """Parse one NEO quote record into a FlintTrade ``Quote`` dict.

    NEO quotes share their key vocabulary with the streaming feed
    (``settings.stock_key_mapping``); the REST surface may return either the long
    names (``last_traded_price``) or the terse feed keys (``ltp``), so each field
    falls back across both. Bid/ask come from ``buy_price``/``sell_price``.
    """
    def g(*keys: str) -> Any:
        for k in keys:
            if k in rec and rec[k] not in (None, ""):
                return rec[k]
        return 0

    seg = str(g("exchange_segment", "e") or "")
    return {
        "symbol": g("trading_symbol", "ts") or "",
        "exchange": KOTAK_TO_EXCHANGE.get(seg, seg),
        "ltp": _num(g("last_traded_price", "ltp")),
        "open": _num(g("open", "op")),
        "high": _num(g("high", "h")),
        "low": _num(g("low", "lo")),
        "close": _num(g("close", "c")),
        "volume": int(_num(g("volume", "v"))),
        "bid": _num(g("buy_price", "bp")),
        "ask": _num(g("sell_price", "sp")),
        "prev_close": _num(g("close", "c")),
        "oi": int(_num(g("open_interest", "oi"))),
    }


def from_kotak_scrip_master(resp: Any) -> dict[str, Any]:
    """Normalise a NEO ``scrip_master`` response (``Scrip_Master.md``).

    The unfiltered call returns ``{"filesPaths": [...], "baseFolder": "..."}``;
    a segment-filtered call returns the single CSV URL as a bare string.
    """
    if isinstance(resp, str):
        return {"base_folder": "", "files": [resp]}
    if isinstance(resp, dict):
        files = resp.get("filesPaths", [])
        return {
            "base_folder": str(resp.get("baseFolder", "")),
            "files": [str(f) for f in files] if isinstance(files, list) else [],
        }
    return {"base_folder": "", "files": []}


def _depth_levels(rec: dict[str, Any], price_keys: list[str], qty_keys: list[str], ord_keys: list[str]) -> list[dict]:
    return [
        {
            "price": _num(rec.get(p, 0)),
            "quantity": int(_num(rec.get(q, 0))),
            "orders": int(_num(rec.get(o, 0))),
        }
        for p, q, o in zip(price_keys, qty_keys, ord_keys)
    ]


def from_kotak_depth(rec: dict[str, Any]) -> dict[str, Any]:
    """Normalise one NEO market-depth record into FlintTrade ``Depth`` fields.

    Handles BOTH shapes: the SDK's pre-shaped ``{"depth": {"buy": [...],
    "sell": [...]}}`` (``NeoWebSocket.depth_resp_mapping``) and the raw terse
    frame (``bp..bp4`` / ``sp..sp4`` / ``bq..bq4`` / ``bs..bs4`` /
    ``bno1..5`` / ``sno1..5`` — ``webSocket.md`` "For Depth").
    """
    seg = str(rec.get("exchange_segment", rec.get("e", "")) or "")
    out: dict[str, Any] = {
        "symbol": str(rec.get("trading_symbol", rec.get("ts", "")) or ""),
        "exchange": KOTAK_TO_EXCHANGE.get(seg, seg),
        "token": str(rec.get("instrument_token", rec.get("tk", "")) or ""),
    }
    depth = rec.get("depth")
    if isinstance(depth, dict):
        out["bids"] = [b for b in depth.get("buy", []) if isinstance(b, dict)]
        out["asks"] = [a for a in depth.get("sell", []) if isinstance(a, dict)]
        return out
    out["bids"] = _depth_levels(
        rec,
        ["bp", "bp1", "bp2", "bp3", "bp4"],
        ["bq", "bq1", "bq2", "bq3", "bq4"],
        ["bno1", "bno2", "bno3", "bno4", "bno5"],
    )
    out["asks"] = _depth_levels(
        rec,
        ["sp", "sp1", "sp2", "sp3", "sp4"],
        ["bs", "bs1", "bs2", "bs3", "bs4"],
        ["sno1", "sno2", "sno3", "sno4", "sno5"],
    )
    return out


def subscription_flags(mode: str) -> tuple[bool, bool]:
    """Map a FlintTrade subscription mode to NEO's ``(isIndex, isDepth)`` pair.

    HSM subscription types (``settings.ReqTypeValues``): scrip feed ``mws``
    (LTP/QUOTE), depth feed ``dps`` (DEPTH/FULL) and index feed ``ifs`` (INDEX).
    """
    m = _norm(mode, "FULL")
    if m in ("LTP", "QUOTE"):
        return False, False
    if m in ("FULL", "DEPTH"):
        return False, True
    if m == "INDEX":
        return True, False
    raise KotakNeoMappingError(f"Unsupported subscription mode {mode!r}")


def _feed_records(frame: Any) -> list[dict[str, Any]]:
    """Extract the record list from one HSM feed delivery (tolerant)."""
    if isinstance(frame, str):
        try:
            frame = json.loads(frame)
        except ValueError:
            return []
    if isinstance(frame, dict):
        if frame.get("type") in ("stock_feed", "quotes"):
            frame = frame.get("data", [])
        elif "tk" in frame or "iv" in frame:
            frame = [frame]
        else:
            return []  # connection ack / unsub ack / heartbeat
    if not isinstance(frame, list):
        return []
    return [r for r in frame if isinstance(r, dict)]


def _fv(rec: dict[str, Any], terse: str, key_map: dict[str, str], default: Any = 0) -> Any:
    """Read a feed field by its terse key, falling back to the mapped long name.

    Raw HSM frames carry the terse keys; SDK-formatted deliveries
    (``quote_resp_mapper``) carry the long names from the same tables.
    """
    if terse in rec:
        return rec[terse]
    return rec.get(key_map.get(terse, terse), default)


def decode_kotak_feed(frame: Any) -> list[dict[str, Any]]:
    """Decode one HSM market-feed delivery into normalised tick dicts.

    Accepts what ``NeoWebSocket`` hands to ``on_message`` (``{"type":
    "stock_feed"|"quotes", "data": [...]}``), a bare record list, or a JSON
    string; connection/unsubscribe acks decode to ``[]``. Each tick dict
    carries ``kind`` (``"quote"`` / ``"index"`` / ``"depth"``); depth ticks
    embed the ``from_kotak_depth`` book under ``"depth"``.
    """
    ticks: list[dict[str, Any]] = []
    for rec in _feed_records(frame):
        if rec.get("request_type") == "cn" or rec.get("type") == "cn":
            continue
        seg = str(rec.get("e", rec.get("exchange_segment", "")) or "")
        base = {
            "symbol": str(rec.get("ts", rec.get("trading_symbol", "")) or ""),
            "exchange": KOTAK_TO_EXCHANGE.get(seg, seg),
            "token": str(rec.get("tk", rec.get("instrument_token", "")) or ""),
        }
        if "iv" in rec or rec.get("name") == "if":
            ticks.append({
                **base,
                "kind": "index",
                "ltp": _num(_fv(rec, "iv", INDEX_FEED_KEYS)),
                "prev_close": _num(_fv(rec, "ic", INDEX_FEED_KEYS)),
                "open": _num(_fv(rec, "openingPrice", INDEX_FEED_KEYS)),
                "high": _num(_fv(rec, "highPrice", INDEX_FEED_KEYS)),
                "low": _num(_fv(rec, "lowPrice", INDEX_FEED_KEYS)),
                "volume": 0,
                "bid": 0.0,
                "ask": 0.0,
                "oi": 0,
                "timestamp": str(_fv(rec, "tvalue", INDEX_FEED_KEYS, "") or ""),
            })
        elif rec.get("name") == "dp" or ("bp1" in rec and "ltp" not in rec):
            book = from_kotak_depth(rec)
            bids, asks = book.get("bids", []), book.get("asks", [])
            ticks.append({
                **base,
                "kind": "depth",
                "ltp": 0.0,
                "volume": 0,
                "bid": _num(bids[0]["price"]) if bids else 0.0,
                "ask": _num(asks[0]["price"]) if asks else 0.0,
                "oi": 0,
                "timestamp": "",
                "depth": book,
            })
        else:
            ticks.append({
                **base,
                "kind": "quote",
                "ltp": _num(_fv(rec, "ltp", STOCK_FEED_KEYS)),
                "volume": int(_num(_fv(rec, "v", STOCK_FEED_KEYS))),
                "bid": _num(_fv(rec, "bp", STOCK_FEED_KEYS)),
                "ask": _num(_fv(rec, "sp", STOCK_FEED_KEYS)),
                "oi": int(_num(_fv(rec, "oi", STOCK_FEED_KEYS))),
                "timestamp": str(_fv(rec, "ltt", STOCK_FEED_KEYS, "") or ""),
            })
    return ticks


def decode_kotak_order_feed(frame: Any) -> dict[str, Any] | None:
    """Decode one HSI order-feed delivery into a normalised order update.

    Accepts ``{"type": "order_feed", "data": <payload>}`` (what ``NeoWebSocket``
    hands to ``on_message``), a bare payload dict, or a JSON string. Connection
    acks (``{"type": "cn"|"CONNECTION"}``) and undecodable frames return
    ``None``. An order payload is normalised via ``from_kotak_order`` with the
    raw record preserved under ``"raw"``.
    """
    payload = frame
    if isinstance(payload, dict) and payload.get("type") == "order_feed":
        payload = payload.get("data")
    if isinstance(payload, str):
        try:
            payload = json.loads(payload)
        except ValueError:
            return None
    if not isinstance(payload, dict):
        return None
    if str(payload.get("type", "")).lower() in ("cn", "connection", "hb"):
        return None
    record = payload.get("data") if isinstance(payload.get("data"), dict) else payload
    if not isinstance(record, dict) or not (record.get("nOrdNo") or record.get("ordSt")):
        return None
    update = from_kotak_order(record)
    update["raw"] = record
    return update


def from_kotak_funds(resp: dict[str, Any]) -> dict[str, Any]:
    """Normalise the NEO ``limits`` response into FlintTrade fund fields.

    The real ``limits()`` response is a FLAT object (no ``data`` wrapper) keyed
    ``Net`` (net available margin) / ``MarginUsed`` / ``CollateralValue`` —
    ``Net + MarginUsed == CollateralValue`` (``Limits.md``). We surface ``Net`` as
    the available balance and ``MarginUsed`` as the used margin, falling back to
    the ``data``-wrapped check-margin keys (``avlCash``/``totMrgnUsd``) only if a
    gateway build returns that shape instead.
    """
    data = resp.get("data", resp) if isinstance(resp, dict) else {}
    if not isinstance(data, dict):
        data = {}
    available = _num(data.get("Net", data.get("avlCash", data.get("avlMrgn", 0))))
    used = _num(data.get("MarginUsed", data.get("totMrgnUsd", data.get("mrgnUsd", 0))))
    return {
        "available_balance": f"{available:.2f}",
        "used_margin": f"{used:.2f}",
        "total_balance": f"{available + used:.2f}",
        "extra": data,
    }
