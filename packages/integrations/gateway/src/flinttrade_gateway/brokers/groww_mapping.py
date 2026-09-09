"""Groww Trade API request/response mapping.

The Groww REST API speaks a compact ``{status, payload}`` envelope and uses
``CASH``/``FNO`` segment names with NSE/BSE exchange names. Keep the translation
logic here so the adapter stays a thin orchestration layer.
"""

from __future__ import annotations

import csv
import math
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from io import StringIO
from typing import Any

from flinttrade_core.broker_read_port import BrokerReadResponseInvalid
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


def _response_record(value: object) -> dict[str, Any]:
    if type(value) is not dict or any(type(key) is not str for key in value):
        raise BrokerReadResponseInvalid
    return value


def _response_text(
    row: dict[str, Any],
    *names: str,
    required: bool = False,
) -> str | object:
    for name in names:
        if name not in row:
            continue
        value = row[name]
        if value is None and not required:
            continue
        if type(value) is not str or not value:
            raise BrokerReadResponseInvalid
        return value.encode("utf-8").decode("utf-8")
    if required:
        raise BrokerReadResponseInvalid
    return _MISSING


def _response_number(
    row: dict[str, Any],
    *names: str,
    required: bool = False,
    empty_absent: bool = False,
) -> int | float | str | object:
    for name in names:
        if name not in row:
            continue
        value = row[name]
        if value is None and not required:
            continue
        if type(value) is int:
            return value
        if type(value) is float:
            if not math.isfinite(value):
                raise BrokerReadResponseInvalid
            return value
        if type(value) is str and not value.strip():
            if empty_absent and not required:
                continue
            raise BrokerReadResponseInvalid
        if type(value) is str:
            try:
                number = Decimal(value)
            except InvalidOperation:
                raise BrokerReadResponseInvalid from None
            if number.is_finite():
                return value.encode("utf-8").decode("utf-8")
        raise BrokerReadResponseInvalid
    if required:
        raise BrokerReadResponseInvalid
    return _MISSING


def _response_exchange(row: dict[str, Any], *, strict_pair: bool = False) -> str | object:
    exchange = _response_text(row, "exchange")
    if not strict_pair and exchange is _MISSING:
        return _MISSING
    segment = _response_text(row, "segment")
    if strict_pair:
        if exchange is _MISSING or segment is _MISSING:
            raise BrokerReadResponseInvalid
        pair = (exchange.upper(), segment.upper())
        mapped = {
            ("NSE", "CASH"): "NSE",
            ("BSE", "CASH"): "BSE",
            ("NSE", "FNO"): "NFO",
            ("BSE", "FNO"): "BFO",
            ("MCX", "COMMODITY"): "MCX",
        }.get(pair)
        if mapped is None:
            raise BrokerReadResponseInvalid
        return mapped
    ex = exchange.upper()
    seg = "" if segment is _MISSING else segment.upper()
    if ex not in {"NSE", "BSE", "MCX"} or seg not in {"", "CASH", "FNO", "COMMODITY"}:
        raise BrokerReadResponseInvalid
    if seg == "COMMODITY" or ex == "MCX":
        return "MCX"
    if seg == "FNO":
        return "BFO" if ex == "BSE" else "NFO"
    return ex


def _response_trade_id(row: dict[str, Any]) -> str | object:
    if "groww_trade_id" in row:
        primary = row["groww_trade_id"]
        if type(primary) is not str:
            raise BrokerReadResponseInvalid
        if primary:
            if not primary.strip():
                raise BrokerReadResponseInvalid
            return primary.encode("utf-8").decode("utf-8")
    secondary = _response_text(row, "exchange_trade_id")
    if secondary is not _MISSING and not secondary.strip():
        raise BrokerReadResponseInvalid
    return secondary


def _response_product(row: dict[str, Any]) -> str | object:
    value = _response_text(row, "product")
    if value is _MISSING:
        return _MISSING
    product_name = value.upper()
    try:
        return {"MIS": "MIS", "CNC": "CNC", "NRML": "NRML", "MARGIN": "NRML"}[product_name]
    except KeyError:
        raise BrokerReadResponseInvalid from None


def _put_present(target: dict[str, Any], name: str, value: object) -> None:
    if value is not _MISSING:
        target[name] = value


def _market_number(
    row: dict[str, Any],
    *names: str,
    integer: bool = False,
) -> float | int | object:
    """Copy the first present market-data alias after exact primitive validation."""
    for name in names:
        if name not in row:
            continue
        value = _response_number(row, name, required=True)
        number = Decimal(str(value))
        converted = float(number)
        if not math.isfinite(converted):
            raise BrokerReadResponseInvalid from None
        if integer:
            if number < 0 or number != number.to_integral_value():
                raise BrokerReadResponseInvalid from None
            return int(number)
        return converted
    return _MISSING


def _market_text(row: dict[str, Any], *names: str) -> str | object:
    for name in names:
        if name not in row:
            continue
        return _response_text(row, name, required=True)
    return _MISSING


def _market_timestamp(value: object) -> str:
    if type(value) is str:
        if not value.strip():
            raise BrokerReadResponseInvalid from None
        return value.encode("utf-8").decode("utf-8")
    if type(value) is int:
        return str(value)
    if type(value) is float and math.isfinite(value):
        return str(value)
    raise BrokerReadResponseInvalid from None


def _required_response(value: object) -> Any:
    if value is _MISSING:
        raise BrokerReadResponseInvalid
    return value


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


def unwrap_fixed_read(payload: Any) -> Any:
    """Strictly unwrap a fixed broker-read response envelope."""
    if type(payload) is not dict or any(type(key) is not str for key in payload):
        raise BrokerReadResponseInvalid from None
    status = payload.get("status")
    if type(status) is not str or not status.strip():
        raise BrokerReadResponseInvalid from None
    if status.strip().upper() != "SUCCESS":
        raise map_error(200, payload)
    if "payload" not in payload:
        raise BrokerReadResponseInvalid from None
    return payload["payload"]


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
    row = _response_record(row)
    quantity = _response_number(row, "quantity", empty_absent=True)
    filled_quantity = _response_number(row, "filled_quantity", empty_absent=True)
    status = _response_text(row, "order_status", "status", required=True)
    order: dict[str, Any] = {
        "status": _status(
            status,
            quantity=float(quantity) if quantity is not _MISSING else 0.0,
            filled_quantity=float(filled_quantity) if filled_quantity is not _MISSING else 0.0,
        )
    }
    for field, value in {
        "orderid": _response_text(row, "groww_order_id", "order_id"),
        "symbol": _response_text(row, "trading_symbol"),
        "exchange": _response_exchange(row, strict_pair=True),
        "quantity": quantity,
        "filled_quantity": filled_quantity,
        "price": _response_number(row, "price", empty_absent=True),
        "trigger_price": _response_number(row, "trigger_price", empty_absent=True),
        "average_price": _response_number(
            row,
            "average_fill_price",
            "average_price",
            empty_absent=True,
        ),
        "order_timestamp": _response_text(row, "created_at", "order_date_time"),
        "order_reference_id": _response_text(row, "order_reference_id"),
    }.items():
        _put_present(order, field, value)
    action = _response_text(row, "transaction_type")
    if action is not _MISSING:
        order["action"] = order["transaction_type"] = action.upper()
    order_kind = _response_text(row, "order_type")
    if order_kind is not _MISSING:
        mapped_kind = {
            "MARKET": "MARKET",
            "LIMIT": "LIMIT",
            "SL": "SL",
            "SL-M": "SL-M",
            "SLM": "SL-M",
            "STOP_LOSS_LIMIT": "SL",
            "STOP_LOSS_MARKET": "SL-M",
        }.get(order_kind.upper())
        if mapped_kind is None:
            raise BrokerReadResponseInvalid
        order["pricetype"] = order["order_type"] = mapped_kind
    mapped_product = _response_product(row)
    _put_present(order, "product", mapped_product)
    return order


def from_trade(row: dict[str, Any]) -> dict[str, Any]:
    row = _response_record(row)
    trade = {
        "tradeid": _response_trade_id(row),
        "symbol": _response_text(row, "trading_symbol", required=True),
        "exchange": _required_response(_response_exchange(row, strict_pair=True)),
        "action": _response_text(row, "transaction_type", required=True).upper(),
        "quantity": _response_number(row, "quantity", required=True),
        "price": _response_number(row, "price", "average_price", required=True),
        "product": _required_response(_response_product(row)),
        "timestamp": _response_text(row, "trade_date_time", "created_at", required=True),
    }
    _put_present(trade, "orderid", _response_text(row, "groww_order_id"))
    return trade


def from_position(row: dict[str, Any]) -> dict[str, Any]:
    row = _response_record(row)
    if "quantity" in row:
        quantity = _response_number(row, "quantity", required=True)
    else:
        credit = _response_number(row, "credit_quantity", required=True)
        debit = _response_number(row, "debit_quantity", required=True)
        try:
            result = Decimal(str(credit)) - Decimal(str(debit))
        except InvalidOperation:
            raise BrokerReadResponseInvalid from None
        if not result.is_finite():
            raise BrokerReadResponseInvalid
        if type(credit) is int and type(debit) is int:
            quantity = int(result)
        elif type(credit) is float or type(debit) is float:
            quantity = float(result)
            if not math.isfinite(quantity):
                raise BrokerReadResponseInvalid
        else:
            quantity = str(result)
    position: dict[str, Any] = {"quantity": quantity}
    for field, value in {
        "symbol": _response_text(row, "trading_symbol"),
        "exchange": _response_exchange(row, strict_pair=True),
        "product": _response_product(row),
        "average_price": _response_number(row, "average_price", "net_price"),
        "ltp": _response_number(row, "ltp", "last_price"),
        "pnl": _response_number(row, "pnl", "realised_pnl", "unrealised_pnl"),
    }.items():
        _put_present(position, field, value)
    return position


def from_holding(row: dict[str, Any]) -> dict[str, Any]:
    row = _response_record(row)
    holding: dict[str, Any] = {"quantity": _response_number(row, "quantity", required=True)}
    for field, value in {
        "symbol": _response_text(row, "trading_symbol"),
        "exchange": _response_exchange(row),
        "product": _response_product(row),
        "average_price": _response_number(row, "average_price"),
        "ltp": _response_number(row, "ltp", "last_price"),
        "isin": _response_text(row, "isin"),
    }.items():
        _put_present(holding, field, value)
    return holding


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


def from_quote(
    symbol: str,
    exchange: str,
    row: dict[str, Any],
    *,
    strict: bool = False,
) -> dict[str, Any]:
    # The documented /v1/live-data/quote payload nests OHLC under an "ohlc"
    # object and names the ask "offer_price" (captured official docs:
    # .local/reference-research/2026-07-03/groww-trade-api-docs). Flat keys stay
    # as tolerance fallbacks only — reading them alone rendered every quote's
    # open/high/low/close/ask as fabricated zeros.
    if not strict:
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

    record = _response_record(row)
    ohlc: dict[str, Any] = {}
    if "ohlc" in record:
        ohlc = _response_record(record["ohlc"])
    quote: dict[str, Any] = {"symbol": symbol, "exchange": exchange}
    _put_present(quote, "ltp", _market_number(record, "last_price", "ltp", "live_price"))
    for name in ("open", "high", "low", "close"):
        value = _market_number(ohlc, name) if name in ohlc else _market_number(record, name)
        _put_present(quote, name, value)
    _put_present(quote, "volume", _market_number(record, "volume", integer=True))
    _put_present(quote, "bid", _market_number(record, "bid_price"))
    _put_present(quote, "ask", _market_number(record, "offer_price", "ask_price"))
    previous_close = _market_number(record, "previous_close", "prev_close")
    if previous_close is _MISSING:
        previous_close = _market_number(ohlc, "close")
    _put_present(quote, "prev_close", previous_close)
    _put_present(quote, "oi", _market_number(record, "open_interest", "oi", integer=True))
    return quote


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


def candle_rows(payload: Any, *, strict: bool = False) -> list[Any]:
    if strict:
        data = unwrap_fixed_read(payload)
        if type(data) is list:
            return data
        record = _response_record(data)
        if "candles" in record:
            rows = record["candles"]
        elif "data" in record:
            rows = record["data"]
        else:
            raise BrokerReadResponseInvalid from None
        if type(rows) is not list:
            raise BrokerReadResponseInvalid from None
        return rows
    data = unwrap(payload)
    if isinstance(data, dict):
        rows = data.get("candles") or data.get("data") or []
        return rows if isinstance(rows, list) else []
    return data if isinstance(data, list) else []


def from_candle_row(row: Any, *, strict: bool = False) -> dict[str, Any]:
    if strict:
        if type(row) is list:
            if len(row) < 5:
                raise BrokerReadResponseInvalid from None
            candle = {
                "timestamp": _market_timestamp(row[0]),
                "open": _market_number({"value": row[1]}, "value"),
                "high": _market_number({"value": row[2]}, "value"),
                "low": _market_number({"value": row[3]}, "value"),
                "close": _market_number({"value": row[4]}, "value"),
            }
            if len(row) > 5:
                candle["volume"] = _market_number({"value": row[5]}, "value", integer=True)
            return candle
        record = _response_record(row)
        timestamp = _market_text(record, "timestamp", "time")
        if timestamp is _MISSING:
            raise BrokerReadResponseInvalid from None
        candle = {
            "timestamp": _market_timestamp(timestamp),
            "open": _market_number(record, "open"),
            "high": _market_number(record, "high"),
            "low": _market_number(record, "low"),
            "close": _market_number(record, "close"),
        }
        if any(candle[name] is _MISSING for name in ("open", "high", "low", "close")):
            raise BrokerReadResponseInvalid from None
        _put_present(candle, "volume", _market_number(record, "volume", integer=True))
        return candle
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
