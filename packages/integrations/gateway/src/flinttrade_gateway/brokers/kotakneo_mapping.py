"""Pure FlintTrade <-> Kotak Neo (NEO OMS) mapping.

Kept separate from the adapter so order translation and the (cryptically-keyed)
NEO response parsing are fully unit-testable without the ``neo-api-client`` SDK
or live credentials. Field names / enum codes follow the Kotak Neo v2 trade API
as documented in the staged SDK (``settings.py`` lookup tables) and the local
broker docs (``.local/reference/broker-docs/kotak-neo/sdk-docs/``).

NEO is an OMS-style API: order/position records use terse abbreviated keys
(``nOrdNo``, ``trdSym``, ``exSeg``, ``trnsTp``, ``prcTp`` …) and positions are
reported as cumulative buy/sell quantities + amounts rather than a single net
line, so the net quantity and booked P&L are derived here per the documented
formula (``Positions.md``).
"""

from __future__ import annotations

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
    if tag:
        params["tag"] = str(tag)
    return params


def to_modify_order_params(order_id: str, changes: dict[str, Any]) -> dict[str, Any]:
    """Translate modify ``changes`` into ``NeoAPI.modify_order`` kwargs."""
    ptype = _norm(changes.get("pricetype", changes.get("order_type", "LIMIT")))
    return {
        "order_id": str(order_id),
        "order_type": ORDER_TYPE_TO_KOTAK.get(ptype, str(changes.get("order_type", "L"))),
        "price": str(_num(changes.get("price", 0))),
        "quantity": str(int(_num(changes.get("quantity", 0), 0))),
        "validity": str(changes.get("validity", "DAY")).upper(),
        "trigger_price": str(_num(changes.get("trigger_price", 0))),
        "disclosed_quantity": str(int(_num(changes.get("disclosed_quantity", 0), 0))),
    }


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
    """Normalise a NEO order-report record."""
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
    }


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


def from_kotak_position(d: dict[str, Any]) -> dict[str, Any]:
    """Normalise a NEO position record.

    NEO reports cumulative carry-forward + intraday buy/sell legs rather than a
    net line; the net quantity, average price and booked P&L are derived per the
    documented formula (``Positions.md``). Unrealised P&L needs a live LTP, which
    the position record does not carry, so it is left to be merged from quotes —
    no LTP is fabricated here.
    """
    buy_qty = _num(d.get("cfBuyQty", 0)) + _num(d.get("flBuyQty", 0))
    sell_qty = _num(d.get("cfSellQty", 0)) + _num(d.get("flSellQty", 0))
    buy_amt = _num(d.get("cfBuyAmt", 0)) + _num(d.get("buyAmt", 0))
    sell_amt = _num(d.get("cfSellAmt", 0)) + _num(d.get("sellAmt", 0))
    net_qty = buy_qty - sell_qty

    if net_qty > 0 and buy_qty:
        avg_price = buy_amt / buy_qty
    elif net_qty < 0 and sell_qty:
        avg_price = sell_amt / sell_qty
    else:
        avg_price = 0.0

    # Booked component only (sell proceeds - buy cost); the open leg's unrealised
    # P&L requires a live LTP and is intentionally not estimated here.
    booked_pnl = sell_amt - buy_amt

    return {
        "symbol": d.get("trdSym", d.get("sym", "")),
        "exchange": _exchange_of(d),
        "product": KOTAK_TO_PRODUCT.get(str(d.get("prod", "")), str(d.get("prod", ""))),
        "quantity": str(int(net_qty)),
        "average_price": f"{avg_price:.2f}",
        "ltp": "0",
        "pnl": f"{booked_pnl:.2f}",
        "buy_quantity": str(int(buy_qty)),
        "sell_quantity": str(int(sell_qty)),
    }


def from_kotak_holding(d: dict[str, Any]) -> dict[str, Any]:
    """Normalise a NEO holding record.

    The holdings endpoint uses longer keys than the OMS order/position feed
    (``displaySymbol``/``averagePrice``/``closingPrice`` …); we fall back across
    the documented variants.
    """
    return {
        "symbol": d.get("displaySymbol", d.get("trdSym", d.get("symbol", ""))),
        "exchange": d.get("exchangeSegment", _exchange_of(d)),
        "quantity": str(d.get("quantity", d.get("holdingCost", 0)) if "quantity" in d else d.get("sellableQuantity", 0)),
        "average_price": str(d.get("averagePrice", d.get("avgPrc", 0))),
        "ltp": str(d.get("closingPrice", d.get("mktValue", 0))),
        "pnl": str(d.get("pnl", 0)),
    }


def from_kotak_funds(resp: dict[str, Any]) -> dict[str, Any]:
    """Normalise the NEO ``limits`` response into FlintTrade fund fields.

    NEO returns ``data: {avlCash, totMrgnUsd, mrgnUsd, ordMrgn, avlMrgn …}``.
    """
    data = resp.get("data", resp) if isinstance(resp, dict) else {}
    if not isinstance(data, dict):
        data = {}
    available = _num(data.get("avlCash", data.get("avlMrgn", 0)))
    used = _num(data.get("totMrgnUsd", data.get("mrgnUsd", 0)))
    return {
        "available_balance": f"{available:.2f}",
        "used_margin": f"{used:.2f}",
        "total_balance": f"{available + used:.2f}",
        "extra": data,
    }
