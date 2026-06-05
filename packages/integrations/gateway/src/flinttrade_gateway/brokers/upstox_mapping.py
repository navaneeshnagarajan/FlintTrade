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
