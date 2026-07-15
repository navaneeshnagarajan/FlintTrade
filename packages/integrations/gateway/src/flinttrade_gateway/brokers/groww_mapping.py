"""Groww Trade API request/response mapping.

The Groww REST API speaks a compact ``{status, payload}`` envelope and uses
``CASH``/``FNO`` segment names with NSE/BSE exchange names. Keep the translation
logic here so the adapter stays a thin orchestration layer.
"""

from __future__ import annotations

import csv
from datetime import date, datetime
from io import StringIO
from typing import Any

from flinttrade_core.exceptions import (
    BrokerError,
    DataError,
    InsufficientFunds,
    InvalidPrice,
    InvalidQuantity,
    InvalidSymbol,
    MarketClosed,
    OrderRejectedByBroker,
    RateLimitError,
    SessionExpired,
    UnsupportedOrderType,
)
from flinttrade_gateway.reconciliation import normalise_order_status

BASE_URL = "https://api.groww.in"
_MISSING = object()


def _text(value: Any) -> str:
    return str(value or "").strip()


def _upper(value: Any) -> str:
    return _text(value).upper()


def _float(value: Any, default: float = 0.0) -> float:
    try:
        if value in (None, ""):
            return default
        return float(value)
    except (TypeError, ValueError):
        return default


def _int(value: Any, default: int = 0) -> int:
    try:
        if value in (None, ""):
            return default
        return int(float(value))
    except (TypeError, ValueError):
        return default


def _present_order_number(row: dict[str, Any], key: str, *, integral: bool = False) -> Any:
    if key not in row:
        return _MISSING
    value = row[key]
    if value is None or (isinstance(value, str) and not value.strip()):
        return _MISSING
    if isinstance(value, bool):
        return value
    try:
        return int(float(value)) if integral else float(value)
    except (TypeError, ValueError, OverflowError):
        return value


def _error_fields(payload: Any) -> tuple[str, str]:
    if not isinstance(payload, dict):
        return "", _text(payload)
    nested = payload.get("error") if isinstance(payload.get("error"), dict) else {}
    code = _text(
        payload.get("error_code")
        or payload.get("code")
        or (nested.get("code") if isinstance(nested, dict) else "")
    )
    message = _text(
        payload.get("message")
        or (nested.get("message") if isinstance(nested, dict) else "")
        or payload
    )
    return code, message


def _is_market_data_endpoint(endpoint: str | None) -> bool:
    value = _text(endpoint).lower()
    return any(
        marker in value
        for marker in (
            "/live-data/",
            "/historical/",
            "/option-chain/",
            "/instruments/",
            "instrument.csv",
        )
    )


def map_error(status: int, payload: Any, *, endpoint: str | None = None) -> BrokerError:
    """Map a Groww HTTP/envelope failure into FlintTrade's taxonomy."""
    code, message = _error_fields(payload)
    message = message or "Groww API error"
    lower = message.lower()
    kwargs = {"broker_code": code or str(status), "broker_id": "groww"}
    if status in (401, 403) and _is_market_data_endpoint(endpoint) and (
        "forbidden" in lower or "authentication required" in lower or "access denied" in lower
    ):
        return DataError("Groww market-data access is not enabled for this API key", **kwargs)
    if status == 401 or "unauthor" in lower or "expired" in lower or "invalid token" in lower:
        return SessionExpired("Groww access token is invalid or expired", **kwargs)
    if status == 403:
        return BrokerError(message, **kwargs)
    if status == 429 or "rate limit" in lower:
        return RateLimitError(message, endpoint="groww", broker_code=code or str(status), broker_id="groww")
    if "margin" in lower or "fund" in lower or "balance" in lower:
        return InsufficientFunds(message, **kwargs)
    if "quantity" in lower or "lot" in lower:
        return InvalidQuantity(message, **kwargs)
    if "price" in lower or "circuit" in lower:
        return InvalidPrice(message, **kwargs)
    if "symbol" in lower or "instrument" in lower or "scrip" in lower:
        return InvalidSymbol(message, **kwargs)
    if "market" in lower and ("closed" in lower or "hour" in lower):
        return MarketClosed(message, **kwargs)
    return OrderRejectedByBroker(message, **kwargs)


def unwrap(payload: Any) -> Any:
    """Return the Groww ``payload`` field from a successful envelope."""
    if not isinstance(payload, dict):
        return payload
    if _upper(payload.get("status")) and _upper(payload.get("status")) != "SUCCESS":
        raise map_error(200, payload)
    return payload.get("payload", payload)


def exchange_segment(exchange: Any) -> tuple[str, str]:
    """Map FlintTrade exchange names to Groww ``(exchange, segment)``."""
    ex = _upper(exchange) or "NSE"
    if ex in {"MCX", "MCX_FO", "MCX_COM", "COMMODITY"}:
        return "MCX", "COMMODITY"
    if ex in {"NFO", "NSE_FO", "NSE_FNO"}:
        return "NSE", "FNO"
    if ex in {"BFO", "BSE_FO", "BSE_FNO"}:
        return "BSE", "FNO"
    if ex == "BSE_INDEX":
        return "BSE", "CASH"
    return ("BSE", "CASH") if ex == "BSE" else ("NSE", "CASH")


def openalgo_exchange(exchange: Any, segment: Any = "") -> str:
    ex = _upper(exchange)
    seg = _upper(segment)
    if seg == "COMMODITY" or ex == "MCX":
        return "MCX"
    if seg == "FNO" and ex == "BSE":
        return "BFO"
    if seg == "FNO":
        return "NFO"
    return "BSE" if ex == "BSE" else "NSE"


def order_type(value: Any) -> str:
    mapping = {
        "MARKET": "MARKET",
        "LIMIT": "LIMIT",
        "SL": "STOP_LOSS_LIMIT",
        "SL-M": "STOP_LOSS_MARKET",
        "SLM": "STOP_LOSS_MARKET",
        "STOP_LOSS_LIMIT": "STOP_LOSS_LIMIT",
        "STOP_LOSS_MARKET": "STOP_LOSS_MARKET",
    }
    kind = _upper(value) or "MARKET"
    if kind not in mapping:
        raise UnsupportedOrderType(f"Groww does not support order type {kind!r}", broker_id="groww")
    return mapping[kind]


def reverse_order_type(value: Any) -> str:
    return {
        "STOP_LOSS_LIMIT": "SL",
        "STOP_LOSS_MARKET": "SL-M",
    }.get(_upper(value), _upper(value) or "MARKET")


def product(value: Any) -> str:
    prod = _upper(value) or "CNC"
    return {"MIS": "MIS", "CNC": "CNC", "NRML": "NRML", "MARGIN": "NRML"}.get(prod, "CNC")


def reverse_product(value: Any) -> str:
    return {"MIS": "MIS", "CNC": "CNC", "NRML": "NRML", "MARGIN": "NRML"}.get(_upper(value), "CNC")


def to_place_order_payload(order: Any) -> dict[str, Any]:
    exchange, segment = exchange_segment(getattr(order, "exchange", "NSE"))
    payload: dict[str, Any] = {
        "trading_symbol": _text(getattr(order, "symbol", "")),
        "quantity": _int(getattr(order, "quantity", 1), 1),
        "validity": _upper(getattr(order, "validity", None)) or "DAY",
        "exchange": exchange,
        "segment": segment,
        "product": product(getattr(order, "product", "CNC")),
        "order_type": order_type(getattr(order, "pricetype", "MARKET")),
        "transaction_type": _upper(getattr(order, "action", "BUY")) or "BUY",
    }
    price = _float(getattr(order, "price", 0))
    trigger = _float(getattr(order, "trigger_price", 0))
    if payload["order_type"] == "LIMIT":
        payload["price"] = price
    if payload["order_type"] in {"STOP_LOSS_LIMIT", "STOP_LOSS_MARKET"}:
        if trigger <= 0:
            raise InvalidPrice("Groww stop-loss orders require trigger_price", broker_id="groww")
        payload["trigger_price"] = trigger
        if payload["order_type"] == "STOP_LOSS_LIMIT":
            payload["price"] = price
    ref = _text(getattr(order, "strategy", ""))[:20]
    if ref:
        payload["order_reference_id"] = ref
    return payload


def to_modify_payload(order_id: str, changes: dict[str, Any], *, segment: str) -> dict[str, Any]:
    payload: dict[str, Any] = {"groww_order_id": str(order_id), "segment": segment}
    if "quantity" in changes:
        payload["quantity"] = _int(changes["quantity"])
    if "pricetype" in changes or "order_type" in changes:
        payload["order_type"] = order_type(changes.get("pricetype") or changes.get("order_type"))
    if "price" in changes:
        payload["price"] = _float(changes["price"])
    if "trigger_price" in changes:
        payload["trigger_price"] = _float(changes["trigger_price"])
    return payload


def to_cancel_payload(order_id: str, *, segment: str) -> dict[str, Any]:
    return {"groww_order_id": str(order_id), "segment": segment}


def to_margin_payload(order: Any) -> tuple[str, list[dict[str, Any]]]:
    payload = to_place_order_payload(order)
    return payload["segment"], [payload]


def extract_order_id(payload: Any) -> str:
    data = unwrap(payload)
    if isinstance(data, dict):
        return _text(data.get("groww_order_id") or data.get("order_id") or data.get("smart_order_id"))
    return ""


def from_order(row: dict[str, Any]) -> dict[str, Any]:
    exchange = openalgo_exchange(row.get("exchange"), row.get("segment"))
    quantity = _present_order_number(row, "quantity", integral=True)
    filled_quantity = _present_order_number(row, "filled_quantity", integral=True)
    order = {
        "orderid": _text(row.get("groww_order_id") or row.get("order_id")),
        "symbol": _text(row.get("trading_symbol")),
        "exchange": exchange,
        "action": _upper(row.get("transaction_type")) or "BUY",
        "transaction_type": _upper(row.get("transaction_type")) or "BUY",
        "pricetype": reverse_order_type(row.get("order_type")),
        "order_type": reverse_order_type(row.get("order_type")),
        "product": reverse_product(row.get("product")),
        "status": _status(
            row.get("order_status") or row.get("status"),
            quantity=_int(quantity) if quantity is not _MISSING else 0,
            filled_quantity=_int(filled_quantity) if filled_quantity is not _MISSING else 0,
        ),
        "order_timestamp": _text(row.get("created_at") or row.get("order_date_time")),
        "order_reference_id": _text(row.get("order_reference_id")),
        "raw": row,
    }
    for field, value in {
        "quantity": quantity,
        "filled_quantity": filled_quantity,
        "price": _present_order_number(row, "price"),
        "trigger_price": _present_order_number(row, "trigger_price"),
        "average_price": _present_order_number(row, "average_price"),
    }.items():
        if value is not _MISSING:
            order[field] = value
    return order


def from_trade(row: dict[str, Any]) -> dict[str, Any]:
    return {
        "orderid": _text(row.get("groww_order_id")),
        "tradeid": _text(row.get("groww_trade_id") or row.get("exchange_trade_id")),
        "symbol": _text(row.get("trading_symbol")),
        "exchange": openalgo_exchange(row.get("exchange"), row.get("segment")),
        "action": _upper(row.get("transaction_type")) or "BUY",
        "quantity": _int(row.get("quantity")),
        "price": _float(row.get("price")),
        "product": reverse_product(row.get("product")),
        "timestamp": _text(row.get("trade_date_time") or row.get("created_at")),
        "raw": row,
    }


def from_position(row: dict[str, Any]) -> dict[str, Any]:
    credit_qty = _float(row.get("credit_quantity"))
    debit_qty = _float(row.get("debit_quantity"))
    net_qty = _float(row.get("quantity"), credit_qty - debit_qty)
    return {
        "symbol": _text(row.get("trading_symbol")),
        "exchange": openalgo_exchange(row.get("exchange"), row.get("segment")),
        "product": reverse_product(row.get("product")),
        "quantity": net_qty,
        "average_price": _float(row.get("average_price") or row.get("net_price")),
        "ltp": _float(row.get("ltp") or row.get("last_price")),
        "pnl": _float(row.get("pnl") or row.get("realised_pnl") or row.get("unrealised_pnl")),
        "raw": row,
    }


def from_holding(row: dict[str, Any]) -> dict[str, Any]:
    return {
        "symbol": _text(row.get("trading_symbol")),
        "exchange": openalgo_exchange(row.get("exchange", "NSE"), "CASH"),
        "quantity": _float(row.get("quantity")),
        "average_price": _float(row.get("average_price")),
        "ltp": _float(row.get("ltp") or row.get("last_price")),
        "isin": _text(row.get("isin")),
        "raw": row,
    }


def from_funds(row: dict[str, Any]) -> dict[str, Any]:
    return {
        "availablecash": _float(row.get("clear_cash")),
        "available_cash": _float(row.get("clear_cash")),
        "total_balance": _float(row.get("clear_cash")) + _float(row.get("collateral_available")),
        "used_margin": _float(row.get("net_margin_used")),
        "collateral": _float(row.get("collateral_available")),
        "brokerage_and_charges": _float(row.get("brokerage_and_charges")),
        "raw": row,
    }


def split_symbol(raw: str) -> tuple[str, str]:
    if ":" in raw:
        exchange, symbol = raw.split(":", 1)
        return _upper(exchange) or "NSE", _text(symbol)
    return "NSE", _text(raw)


def groww_exchange_symbol(exchange: str, symbol: str) -> str:
    ex, _segment = exchange_segment(exchange)
    return f"{ex}_{symbol}"


def from_quote(symbol: str, exchange: str, row: dict[str, Any]) -> dict[str, Any]:
    # The documented /v1/live-data/quote payload nests OHLC under an "ohlc"
    # object and names the ask "offer_price" (captured official docs:
    # .local/reference-research/2026-07-03/groww-trade-api-docs). Flat keys stay
    # as tolerance fallbacks only — reading them alone rendered every quote's
    # open/high/low/close/ask as fabricated zeros.
    raw_ohlc = row.get("ohlc")
    ohlc: dict[str, Any] = raw_ohlc if isinstance(raw_ohlc, dict) else {}
    return {
        "symbol": symbol,
        "exchange": exchange,
        "ltp": _float(row.get("last_price") or row.get("ltp") or row.get("live_price")),
        "open": _float(ohlc.get("open") or row.get("open")),
        "high": _float(ohlc.get("high") or row.get("high")),
        "low": _float(ohlc.get("low") or row.get("low")),
        "close": _float(ohlc.get("close") or row.get("close")),
        "volume": _int(row.get("volume")),
        "bid": _float(row.get("bid_price")),
        "ask": _float(row.get("offer_price") or row.get("ask_price")),
        "prev_close": _float(
            row.get("previous_close") or row.get("prev_close") or ohlc.get("close")
        ),
        "oi": _int(row.get("open_interest") or row.get("oi")),
    }


def from_ohlc(symbol: str, exchange: str, row: dict[str, Any]) -> dict[str, Any]:
    return {
        "symbol": symbol,
        "exchange": exchange,
        "open": _float(row.get("open")),
        "high": _float(row.get("high")),
        "low": _float(row.get("low")),
        "close": _float(row.get("close")),
        "volume": _int(row.get("volume")),
        "timestamp": _text(row.get("timestamp") or row.get("time")),
        "raw": row,
    }


def expiry_values(payload: Any) -> list[str]:
    data = unwrap(payload)
    if isinstance(data, list):
        return [_text(item) for item in data if _text(item)]
    if not isinstance(data, dict):
        return []
    for key in ("expiry_dates", "expiries", "expiry", "data"):
        values = data.get(key)
        if isinstance(values, list):
            return [_text(item) for item in values if _text(item)]
    return []


def candle_rows(payload: Any) -> list[list[Any]]:
    data = unwrap(payload)
    if isinstance(data, dict):
        rows = data.get("candles") or data.get("data") or []
        return rows if isinstance(rows, list) else []
    return data if isinstance(data, list) else []


def from_candle_row(row: Any) -> dict[str, Any]:
    if isinstance(row, (list, tuple)):
        return {
            "timestamp": str(row[0] if len(row) > 0 else ""),
            "open": _float(row[1] if len(row) > 1 else 0),
            "high": _float(row[2] if len(row) > 2 else 0),
            "low": _float(row[3] if len(row) > 3 else 0),
            "close": _float(row[4] if len(row) > 4 else 0),
            "volume": _int(row[5] if len(row) > 5 else 0),
        }
    if isinstance(row, dict):
        return {
            "timestamp": _text(row.get("timestamp") or row.get("time")),
            "open": _float(row.get("open")),
            "high": _float(row.get("high")),
            "low": _float(row.get("low")),
            "close": _float(row.get("close")),
            "volume": _int(row.get("volume")),
        }
    return {}


def normalise_date(value: Any) -> str:
    if isinstance(value, datetime):
        return value.strftime("%Y-%m-%d %H:%M:%S")
    if isinstance(value, date):
        return value.strftime("%Y-%m-%d")
    return _text(value)


def option_chain_rows(payload: Any) -> dict[str, Any]:
    data = unwrap(payload)
    return data if isinstance(data, dict) else {}


def parse_instruments_csv(text: str) -> list[dict[str, str]]:
    return list(csv.DictReader(StringIO(text)))


def _status(value: Any, *, quantity: float = 0.0, filled_quantity: float = 0.0) -> str:
    return normalise_order_status(
        value,
        quantity=quantity,
        filled_quantity=filled_quantity,
    )
