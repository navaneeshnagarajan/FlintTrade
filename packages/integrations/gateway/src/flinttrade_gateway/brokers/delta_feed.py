"""Delta websocket frames and deadman payloads.

Public market channels use the documented India public sockets. Private
channels authenticate with HMAC of ``GET + timestamp + /live``. Global
websocket hosts are not published on the India docs site, so callers must
fail closed rather than invent a URL.
"""

from __future__ import annotations

import json
from typing import Any

from flinttrade_core.models import TickEvent

from .delta_mapping import BROKER_ID, sign_request

TICKER_TYPES = frozenset({"ticker", "v2/ticker"})
ORDER_TYPES = frozenset({"orders", "positions", "margins", "user_trades"})


def subscribe_message(channel: str, symbols: list[str]) -> dict[str, Any]:
    """Public or private subscribe frame. Symbols are product symbols."""
    return {
        "type": "subscribe",
        "payload": {"channels": [{"name": channel, "symbols": symbols}]},
    }


def private_auth_message(*, api_key: str, api_secret: str, timestamp: str) -> dict[str, Any]:
    """key-auth frame. The signed path is ``/live``, not a REST path."""
    return {
        "type": "key-auth",
        "payload": {
            "api-key": api_key,
            "timestamp": timestamp,
            "signature": sign_request(api_secret, "GET", timestamp, "/live", "", ""),
        },
    }


def deadman_create_body(
    *,
    heartbeat_id: str,
    impact: str = "high",
    unhealthy_count: int = 2,
    product_symbols: list[str] | None = None,
) -> dict[str, Any]:
    """Create a heartbeat that cancels open orders after missed acknowledgements."""
    if impact not in {"low", "medium", "high"}:
        raise ValueError("Delta deadman impact must be low, medium, or high")
    if unhealthy_count < 1:
        raise ValueError("Delta deadman unhealthy_count must be at least 1")
    body: dict[str, Any] = {
        "heartbeat_id": heartbeat_id,
        "impact": impact,
        "config": [{"action": "cancel_orders", "unhealthy_count": unhealthy_count}],
    }
    if product_symbols:
        body["product_symbols"] = product_symbols
    return body


def deadman_ack_body(*, heartbeat_id: str, ttl_ms: int) -> dict[str, Any]:
    if ttl_ms < 1:
        raise ValueError("Delta deadman ttl must be a positive number of milliseconds")
    return {"heartbeat_id": heartbeat_id, "ttl": ttl_ms}


def parse_ticker_frame(raw: str | bytes | dict[str, Any]) -> TickEvent | None:
    """Return a tick for a ticker frame, or None for acks and other channels.

    India public sockets emit both the verbose ticker and the compact frame
    whose symbol is ``sy`` and whose market data sits under ``d[]``.
    """
    message = _load(raw)
    if message is None:
        return None
    kind = str(message.get("type") or "")
    compact = _compact_ticker(message)
    if kind and kind not in TICKER_TYPES:
        return None
    if not kind and not compact:
        return None
    symbol = str(
        compact.get("symbol")
        or message.get("symbol")
        or message.get("product_symbol")
        or message.get("sy")
        or ""
    ).strip()
    if not symbol:
        return None
    quotes_raw = message.get("quotes")
    quotes: dict[str, Any] = quotes_raw if isinstance(quotes_raw, dict) else {}
    close = message.get("close")
    if close in (None, "") and compact.get("close") not in (None, ""):
        close = compact.get("close")
    mark = message.get("mark_price") or compact.get("mark_price") or message.get("price")
    return TickEvent(
        symbol=symbol,
        exchange="CRYPTO",
        ltp=_float(close or mark),
        volume=int(_float(message.get("volume") or message.get("size") or compact.get("volume"))),
        bid=_float(quotes.get("best_bid") or message.get("best_bid") or compact.get("bid")),
        ask=_float(quotes.get("best_ask") or message.get("best_ask") or compact.get("ask")),
        oi=int(_float(message.get("oi") or compact.get("oi"))),
        timestamp=str(message.get("timestamp") or message.get("ts") or compact.get("timestamp") or ""),
    )


def parse_private_frame(raw: str | bytes | dict[str, Any]) -> dict[str, Any] | None:
    """Return an order, position, margin, or fill update. Auth acks are ignored."""
    message = _load(raw)
    if message is None or str(message.get("type") or "") not in ORDER_TYPES:
        return None
    return message


def _compact_ticker(message: dict[str, Any]) -> dict[str, Any]:
    """Project one documented compact ticker row onto verbose field names."""
    rows = message.get("d")
    if not isinstance(rows, list):
        return {}
    wanted = str(message.get("sy") or "").strip()
    row = next(
        (item for item in rows if isinstance(item, dict) and str(item.get("s") or "") == wanted),
        None,
    )
    if row is None:
        row = next((item for item in rows if isinstance(item, dict)), None)
    if not isinstance(row, dict):
        return {}
    ohlc = row.get("ohlc")
    candles = ohlc if isinstance(ohlc, list) else []
    return {
        "symbol": str(row.get("s") or wanted or ""),
        "mark_price": row.get("m"),
        "close": candles[3] if len(candles) > 3 else None,
        "volume": row.get("v"),
        "oi": row.get("oi"),
        "bid": row.get("b"),
        "ask": row.get("a"),
        "timestamp": message.get("ts"),
    }


def _load(raw: str | bytes | dict[str, Any]) -> dict[str, Any] | None:
    if isinstance(raw, dict):
        return raw
    text = raw.decode("utf-8") if isinstance(raw, bytes) else raw
    try:
        parsed = json.loads(text)
    except json.JSONDecodeError:
        return None
    return parsed if isinstance(parsed, dict) else None


def _float(raw: Any) -> float:
    try:
        return float(raw)
    except (TypeError, ValueError):
        return 0.0


def socket_required_message(environment: str) -> str:
    return (
        f"Delta venue {environment or 'unknown'} has no documented websocket host. "
        f"India sockets are published; Global sockets are not. broker_id={BROKER_ID}"
    )
