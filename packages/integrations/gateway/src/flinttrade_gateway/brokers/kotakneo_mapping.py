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
    # OpenAlgo/terminal index convention: NEO has no separate index segment —
    # index quotes ride the cash segments. Without these entries the
    # ex.lower() fallback emitted the invalid segment "nse_index".
    "NSE_INDEX": "nse_cm",
    "BSE_INDEX": "bse_cm",
}
# Reverse map built from the FIRST occurrence of each segment so the primary
# NSE/BSE rows win over the *_INDEX aliases added after them.
KOTAK_TO_EXCHANGE: dict[str, str] = {}
for _ft_exchange, _kotak_segment in EXCHANGE_TO_KOTAK.items():
    KOTAK_TO_EXCHANGE.setdefault(_kotak_segment, _ft_exchange)

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

# Order validity codes in the current public docs and pinned SDK validation.
VALIDITY_ALLOWED = frozenset({"DAY", "IOC"})

# limits() filter enums (settings.segment_limits / exchange_limits / product_limits).
LIMITS_SEGMENTS = frozenset({"CASH", "CUR", "FO", "ALL"})
LIMITS_EXCHANGES = frozenset({"NSE", "BSE", "ALL"})
LIMITS_PRODUCTS = frozenset({"CNC", "MIS", "NRML", "ALL"})

# REST quotes quote_type values (Quotes.md). The SDK places the value directly
# into the URL path, so FlintTrade accepts case-insensitive input but emits
# Kotak's documented case (notably ``52W``).
QUOTE_TYPE_CANONICAL = {
    "all": "all",
    "depth": "depth",
    "ohlc": "ohlc",
    "ltp": "ltp",
    "oi": "oi",
    "52w": "52W",
    "circuit_limits": "circuit_limits",
    "scrip_details": "scrip_details",
}
QUOTE_TYPES = frozenset(QUOTE_TYPE_CANONICAL)

# Index exchange identifiers (``webSocket.md`` "For Indexes" + Quotes.md): the
# ``instrument_token`` for an index is its NAME, not a numeric scrip token. Both
# the quote and the subscription path pass these names through unresolved.
# Compared case-insensitively (``is_index_name``) since callers vary the casing.
INDEX_NAMES = frozenset(
    {
        "NIFTY 50",
        "NIFTY BANK",
        "NIFTY FIN SERVICE",
        "SENSEX",
        "BANKEX",
        "INDIA VIX",
        "NIFTY MIDCAP 100",
        "NIFTY 100",
        "NIFTY PSU BANK",
        "NIFTY PHARMA",
        "NIFTY IT",
        "NIFTY PSE",
        "NIFTY FMCG",
        "NIFTY 500",
        "NIFTY AUTO",
        "NIFTY CPSE",
        "NIFTY 200",
        "NIFTY NEXT 50",
        "NIFTY MID SELECT",
    }
)
_INDEX_NAME_CANONICAL = {
    "NIFTY 50": "Nifty 50",
    "NIFTY BANK": "Nifty Bank",
    "SENSEX": "SENSEX",
    "BANKEX": "BANKEX",
}


def canonical_quote_type(quote_type: str | None) -> str:
    """Return Kotak's documented quote filter spelling for ``quote_type``."""
    key = str(quote_type or "all").strip().lower()
    try:
        return QUOTE_TYPE_CANONICAL[key]
    except KeyError as exc:
        raise KotakNeoMappingError(f"Unsupported quote_type {quote_type!r}") from exc


def is_index_name(name: str) -> bool:
    """Return ``True`` if ``name`` is a NEO index identifier (passed by name).

    Index quotes/subscriptions key the instrument by its name (``webSocket.md``
    "For Indexes"); everything else needs a numeric scrip token resolved first.
    """
    return str(name).strip().upper() in INDEX_NAMES


def canonical_index_name(name: str) -> str:
    """Return the case-sensitive index name Kotak documents, where known."""
    text = str(name).strip()
    return _INDEX_NAME_CANONICAL.get(text.upper(), text)


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
    "sq": "sell_quantity",
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


def _present_order_number(record: dict[str, Any], key: str) -> str | None:
    if key not in record:
        return None
    value = record[key]
    if value is None or (isinstance(value, str) and not value.strip()):
        return None
    return str(value)


def _norm(value: Any, default: str = "") -> str:
    return str(value).upper() if value is not None else default


def _market_protection_value(value: Any) -> str:
    """Return NEO's string ``mp`` value for FlintTrade's optional MPP flag."""
    if isinstance(value, bool):
        return "1" if value else "0"
    return str(value)


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
    # Validity pass-through: None keeps the NEO default (DAY). The field is part
    # of the SafetyContext-hashed Order, so it cannot be mutated after gating.
    validity = _norm(getattr(order, "validity", None) or "DAY")
    if validity not in VALIDITY_ALLOWED:
        raise KotakNeoMappingError(f"Unsupported validity {validity!r}")

    params: dict[str, Any] = {
        "exchange_segment": EXCHANGE_TO_KOTAK[exchange],
        "product": PRODUCT_TO_KOTAK[product],
        "price": str(_num(getattr(order, "price", 0))),
        "order_type": ORDER_TYPE_TO_KOTAK[ptype],
        "quantity": str(int(_num(order.quantity, 0))),
        "validity": validity,
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

    if getattr(order, "market_protection", None) is not None:
        params["market_protection"] = _market_protection_value(order.market_protection)
    if tag:
        params["tag"] = str(tag)
    return params


# Bracket-only NEO leg fields (``Place_Order.md`` marks every one "Applicable
# only for Bracket Order"). A cover order MUST NOT carry these — its stop level
# rides ``trigger_price`` instead — so the cover branch strips any that leaked in.
_BRACKET_ONLY_LEG_FIELDS = (
    "stop_loss_value",
    "stop_loss_type",
    "square_off_value",
    "square_off_type",
    "trailing_stop_loss",
    "trailing_sl_value",
)


def _apply_variety_legs(order: Any, variety: str, params: dict[str, Any]) -> None:
    """Attach bracket/cover legs onto ``params`` (shared by place + margin).

    Bracket (BO) and cover (CO) differ in how the stop level is carried:

    * **Bracket** attaches the protective legs via the bracket-only fields —
      ``square_off_*``/``stop_loss_*``/``trailing_*``. Their enum values are
      forwarded verbatim to the OMS, so they MUST match the documented set:
      square_off_type/stop_loss_type ∈ {"Absolute","Ticks"} and
      trailing_stop_loss ∈ {"Y","N"} (``Place_Order.md``). Sending "abs"/"YES"
      silently drops the protective legs on a live order.
    * **Cover** has only a stop-loss, which the OMS reads from ``trigger_price``
      (``Place_Order.md``: required for stop-loss and cover order); the
      bracket-only leg fields do not apply and are dropped. The stop level is
      taken from ``stop_loss_price`` (falling back to ``trigger_price`` when the
      caller set only that).
    """
    target = _num(getattr(order, "target_price", 0))
    stop_loss = _num(getattr(order, "stop_loss_price", 0))
    if variety == "cover":
        params["product"] = "CO"
        # CO carries its stop level in trigger_price, NOT a bracket leg field.
        cover_trigger = stop_loss if stop_loss > 0 else _num(getattr(order, "trigger_price", 0))
        if cover_trigger <= 0:
            raise KotakNeoMappingError("A cover order needs a stop level (stop_loss_price or trigger_price)")
        params["trigger_price"] = str(cover_trigger)
        # Strip any bracket-only legs that the base place/margin params seeded.
        for field in _BRACKET_ONLY_LEG_FIELDS:
            params.pop(field, None)
        return

    if target <= 0 and stop_loss <= 0:
        raise KotakNeoMappingError("A bracket order needs a target_price or stop_loss_price")
    params["product"] = "BO"
    params["stop_loss_value"] = str(stop_loss)
    params["stop_loss_type"] = "Absolute"
    if target > 0:
        params["square_off_value"] = str(target)
        params["square_off_type"] = "Absolute"
    trailing = _num(getattr(order, "trailing_jump", 0))
    if trailing > 0:
        params["trailing_stop_loss"] = "Y"
        params["trailing_sl_value"] = str(trailing)


# NEO modify quick-path discriminators (``neo_api.modify_order`` line 361). The
# SDK takes the quick path only when ALL four are set, and the order-id path only
# when ``instrument_token``/``exchange_segment``/``trading_symbol`` are ALL unset
# — any partial set falls through to its ``raise ValueError``. We enforce the
# all-or-nothing contract here so a clear ``KotakNeoMappingError`` is raised
# before the SDK does (``Modify_Order.md`` Methods 1 & 2).
_MODIFY_QUICK_FIELDS = ("instrument_token", "exchange_segment", "product", "trading_symbol")


def to_modify_order_params(order_id: str, changes: dict[str, Any]) -> dict[str, Any]:
    """Translate modify ``changes`` into ``NeoAPI.modify_order`` kwargs.

    The base surface (order-id method, ``Modify_Order.md`` "Method 2") is always
    emitted; the quick-method extras (``instrument_token`` / ``exchange_segment``
    / ``product`` / ``trading_symbol`` / ``transaction_type``) plus the ``amo`` /
    ``market_protection`` / ``filled_quantity`` / ``dd`` flags are forwarded only
    when present in ``changes``, so the SDK picks the right modification path.

    The four quick-method discriminators are all-or-nothing: the SDK requires the
    complete set for the quick path (and none of them for the order-id path), so
    a partial set is rejected with a clear ``KotakNeoMappingError`` here rather
    than the SDK's opaque ``ValueError``.
    """
    quick_present = [f for f in _MODIFY_QUICK_FIELDS if changes.get(f)]
    if quick_present and len(quick_present) != len(_MODIFY_QUICK_FIELDS):
        missing = [f for f in _MODIFY_QUICK_FIELDS if not changes.get(f)]
        raise KotakNeoMappingError(
            "Kotak Neo modify quick-method requires all of "
            f"{list(_MODIFY_QUICK_FIELDS)} together or none — missing {missing}"
        )
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
    ``{"error": [...]}`` (validation), ``{"status": "error", "message": ...}``
    (TOTP/MPIN login reject) and ``{"stat": "Not_Ok", "errMsg"/"emsg": ...}``
    (OMS reject). Writes and login MUST surface those instead of silently
    succeeding.
    """
    if isinstance(resp, dict):
        for key in ("Error", "Error Message", "error"):
            if resp.get(key):
                raise KotakNeoMappingError(f"Kotak Neo error: {resp[key]!r}")
        data = resp.get("data") if isinstance(resp.get("data"), dict) else {}
        status = resp.get("status", data.get("status"))
        if status is not None and str(status).lower() not in ("success", "ok", ""):
            message = resp.get("message") or data.get("message") or resp.get("emsg") or resp.get("errMsg") or resp
            raise KotakNeoMappingError(f"Kotak Neo rejected the request: {message!r}")
        if str(resp.get("stat", "Ok")).lower() not in ("ok", ""):
            raise KotakNeoMappingError(
                f"Kotak Neo rejected the request: {resp.get('errMsg') or resp.get('emsg') or resp!r}"
            )
    return resp


def require_write_success(resp: Any, *, expected_order_id: str | None = None) -> dict[str, Any]:
    """Require Kotak's documented affirmative write acknowledgement.

    ``ensure_ok`` remains deliberately tolerant for legacy read surfaces. Live
    mutations need the stronger contract documented by the place/modify/cancel APIs:
    an object with ``stat=Ok``, integer ``stCode=200`` and a canonical order
    number. When modifying or cancelling, that number must be the exact
    requested order.
    """
    ensure_ok(resp)
    if not isinstance(resp, dict):
        raise KotakNeoMappingError("Kotak Neo write response is malformed")
    status = resp.get("stat")
    status_code = resp.get("stCode")
    order_id = resp.get("nOrdNo")
    if not order_id:
        data = resp.get("data")
        if isinstance(data, dict):
            order_id = data.get("nOrdNo") or data.get("orderId")
    if not isinstance(status, str) or status.strip().lower() != "ok":
        raise KotakNeoMappingError("Kotak Neo write response has no explicit success status")
    if isinstance(status_code, bool) or not isinstance(status_code, int) or status_code != 200:
        raise KotakNeoMappingError("Kotak Neo write response has no explicit HTTP 200 status")
    if (
        not isinstance(order_id, str)
        or not order_id
        or order_id != order_id.strip()
        or not order_id.isprintable()
        or any(character.isspace() for character in order_id)
    ):
        raise KotakNeoMappingError("Kotak Neo write response has no canonical order id")
    if expected_order_id is not None and order_id != expected_order_id:
        raise KotakNeoMappingError("Kotak Neo write acknowledged a different order id")
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
    order = {
        "orderid": str(d.get("nOrdNo", "")),
        "status": d.get("ordSt", d.get("stat", "")),
        "symbol": d.get("trdSym", d.get("sym", "")),
        "exchange": _exchange_of(d),
        "action": KOTAK_TO_SIDE.get(str(d.get("trnsTp", "")), str(d.get("trnsTp", ""))),
        "pricetype": KOTAK_TO_ORDER_TYPE.get(str(d.get("prcTp", "")), str(d.get("prcTp", ""))),
        "product": KOTAK_TO_PRODUCT.get(str(d.get("prod", "")), str(d.get("prod", ""))),
        "timestamp": str(d.get("ordDtTm", d.get("exchTmstp", d.get("flDtTm", "")))),
        "validity": str(d.get("vldt", d.get("ordDur", ""))),
        "disclosed_quantity": str(d.get("dscQty", d.get("dclQty", 0))),
        "rejection_reason": "" if str(d.get("rejRsn", "")) in ("--", "NA") else str(d.get("rejRsn", "")),
        "exchange_order_id": ""
        if str(d.get("exOrdId", d.get("exchOrdId", ""))) == "NA"
        else str(d.get("exOrdId", d.get("exchOrdId", ""))),
        "tag": str(d.get("GuiOrdId", "") or ""),
    }
    for field, source_field in {
        "quantity": "qty",
        "filled_quantity": "fldQty",
        "price": "prc",
        "trigger_price": "trgPrc",
        "average_price": "avgPrc",
    }.items():
        value = _present_order_number(d, source_field)
        if value is not None:
            order[field] = value
    return order


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
    layer. Average price is per-unit and follows the documented denominator
    (``Positions.md`` §"Avg Price Fields"): ``amount / (qty * multiplier *
    genNum/genDen * prcNum/prcDen)`` rounded to the scrip ``precision``. The
    ``multiplier`` term does NOT cancel — it is 1 for equity but ≠1 for some
    currency / commodity derivatives, so omitting it overstates the avg price on
    those scrips.

    P&L is the **realised** component only — ``matched_qty * (sell_avg -
    buy_avg) * unit_factor`` where ``matched_qty = min(buy_qty, sell_qty)`` and
    ``unit_factor = multiplier * genNum/genDen * prcNum/prcDen`` (the same
    per-unit factor used for the avg, so the value is amount-consistent on
    multiplier≠1 scrips). The open leg's unrealised P&L needs a live LTP not in
    the record and is left to merge from quotes (``ltp`` is ``0``; none is
    fabricated). This matches Dhan (realised+unrealised) / Upstox (broker pnl)
    once a quote is merged.
    """
    ratios = _ratio(d.get("genNum", 1), d.get("genDen", 1)) * _ratio(d.get("prcNum", 1), d.get("prcDen", 1))
    multiplier = _num(d.get("multiplier", 1), 1.0)
    # Full per-unit factor (``Positions.md``: multiplier × genNum/genDen ×
    # prcNum/prcDen). 1.0 for equity; ≠1 for some currency/commodity scrips.
    unit_factor = (ratios * multiplier) or 1.0
    # Clamp to a sane decimal-place range: a malformed/negative precision would
    # otherwise make the avg-price f-string raise ValueError and abort the whole
    # positions() fetch instead of degrading one row.
    precision = max(0, min(int(_num(d.get("precision", 2), 2)), 8))

    buy_qty = _num(d.get("cfBuyQty", 0)) + _num(d.get("flBuyQty", 0))
    sell_qty = _num(d.get("cfSellQty", 0)) + _num(d.get("flSellQty", 0))
    buy_amt = _num(d.get("cfBuyAmt", 0)) + _num(d.get("buyAmt", 0))
    sell_amt = _num(d.get("cfSellAmt", 0)) + _num(d.get("sellAmt", 0))
    net_qty = buy_qty - sell_qty

    buy_avg = buy_amt / (buy_qty * unit_factor) if buy_qty else 0.0
    sell_avg = sell_amt / (sell_qty * unit_factor) if sell_qty else 0.0
    if buy_qty > sell_qty:
        avg_price = buy_avg
    elif sell_qty > buy_qty:
        avg_price = sell_avg
    else:
        avg_price = 0.0

    matched = min(buy_qty, sell_qty)
    # Realised = closed-leg sell amount − buy amount. Re-multiplying by
    # ``unit_factor`` recovers the amount-space value the per-unit avgs were
    # divided out of. `... or 0.0` normalises Python negative zero: an open long
    # (matched == 0, buy_avg > 0) yields -0.0, which would render as "-0.00".
    realised_pnl = matched * (sell_avg - buy_avg) * unit_factor or 0.0

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


def to_margin_params(order: Any, trading_symbol: str, *, instrument_token: str | None = None) -> dict[str, Any]:
    """Build ``NeoAPI.margin_required`` kwargs from an ``Order`` (pre-trade).

    ``instrument_token`` is the numeric ``pSymbol`` from the ScripMaster files —
    the field NEO's ``margin_required`` keys the scrip by (``Margin_Required.md``
    line 35); ``trading_symbol`` is the ``pTrdSymbol`` and rides its own field.
    When the numeric token is not resolvable the trading symbol is used as a
    best-effort fallback (NEO may still resolve some scrips by symbol), and the
    ``trading_symbol`` field is always set so the estimate is unambiguous.

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
        # instrument_token = numeric pSymbol; trading_symbol = pTrdSymbol.
        "instrument_token": str(instrument_token) if instrument_token else str(trading_symbol),
        "trading_symbol": str(trading_symbol),
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
    """Build the NEO ``quotes`` request from ``(instrument_token, exchange)`` pairs.

    NEO's ``quotes(instrument_tokens=[...])`` takes a list of
    ``{"instrument_token": <wToken/pSymbol>, "exchange_segment": <seg>}`` dicts.
    The ``instrument_token`` is the numeric scrip token (``pSymbol``), resolved by
    the adapter — only indexes pass a NAME here (``webSocket.md`` "For Indexes").
    This function just shapes whatever resolved value it is given; the
    symbol→token resolution lives in the adapter.
    """
    tokens: list[dict[str, str]] = []
    for instrument_token, exchange in resolved:
        ex = _norm(exchange)
        tokens.append(
            {
                "instrument_token": str(instrument_token),
                "exchange_segment": EXCHANGE_TO_KOTAK.get(ex, ex.lower()),
            }
        )
    return tokens


def from_kotak_quote(rec: dict[str, Any]) -> dict[str, Any]:
    """Parse one NEO quote record into a FlintTrade ``Quote`` dict.

    NEO quotes share their key vocabulary with the streaming feed
    (``settings.stock_key_mapping``); the REST surface may return either the long
    names (``last_traded_price``), the terse feed keys (``ltp``), or the current
    public-docs shape (``display_symbol`` / ``exchange`` / nested ``ohlc`` /
    nested ``depth``), so each field falls back across all documented variants.
    Bid/ask prices come from ``buy_price``/``sell_price`` or the first depth
    levels; ``total_buy``/``total_sell`` are quantities, not prices.
    """

    def g(*keys: str) -> Any:
        for k in keys:
            if k in rec and rec[k] not in (None, ""):
                return rec[k]
        return 0

    def nested(container: str, key: str) -> Any:
        value = rec.get(container)
        if isinstance(value, dict) and value.get(key) not in (None, ""):
            return value[key]
        return 0

    def depth_price(side: str) -> Any:
        depth = rec.get("depth")
        if not isinstance(depth, dict):
            return 0
        rows = depth.get(side)
        if isinstance(rows, list) and rows and isinstance(rows[0], dict):
            return rows[0].get("price", 0)
        return 0

    seg = str(g("exchange_segment", "exchange", "e") or "")
    return {
        "symbol": g("trading_symbol", "display_symbol", "exchange_token", "ts", "tk") or "",
        "exchange": KOTAK_TO_EXCHANGE.get(seg, seg),
        "ltp": _num(g("last_traded_price", "ltp")),
        "open": _num(g("open", "op") or nested("ohlc", "open")),
        "high": _num(g("high", "h") or nested("ohlc", "high")),
        "low": _num(g("low", "lo") or nested("ohlc", "low")),
        "close": _num(g("close", "c") or nested("ohlc", "close")),
        "volume": int(_num(g("volume", "last_volume", "v"))),
        "bid": _num(g("buy_price", "bp") or depth_price("buy")),
        "ask": _num(g("sell_price", "sp") or depth_price("sell")),
        "prev_close": _num(g("close", "c") or nested("ohlc", "close")),
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


def _normalise_depth_levels(rows: Any) -> list[dict]:
    """Return depth levels with FlintTrade's numeric price/quantity/orders keys."""
    if not isinstance(rows, list):
        return []
    levels: list[dict] = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        levels.append(
            {
                "price": _num(row.get("price", 0)),
                "quantity": int(_num(row.get("quantity", 0))),
                "orders": int(_num(row.get("orders", 0))),
            }
        )
    return levels


def from_kotak_depth(rec: dict[str, Any]) -> dict[str, Any]:
    """Normalise one NEO market-depth record into FlintTrade ``Depth`` fields.

    Handles BOTH shapes: the SDK's pre-shaped ``{"depth": {"buy": [...],
    "sell": [...]}}`` / current public-docs quote-depth response and the raw
    terse frame (``bp..bp4`` / ``sp..sp4`` / ``bq..bq4`` / ``bs..bs4`` /
    ``bno1..5`` / ``sno1..5`` — ``webSocket.md`` "For Depth").
    """
    seg = str(rec.get("exchange_segment", rec.get("exchange", rec.get("e", ""))) or "")
    out: dict[str, Any] = {
        "symbol": str(
            rec.get("trading_symbol", rec.get("display_symbol", rec.get("exchange_token", rec.get("ts", "")))) or ""
        ),
        "exchange": KOTAK_TO_EXCHANGE.get(seg, seg),
        "token": str(rec.get("instrument_token", rec.get("exchange_token", rec.get("tk", ""))) or ""),
    }
    depth = rec.get("depth")
    if isinstance(depth, dict):
        out["bids"] = _normalise_depth_levels(depth.get("buy", []))
        out["asks"] = _normalise_depth_levels(depth.get("sell", []))
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
            ticks.append(
                {
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
                }
            )
        elif rec.get("name") == "dp" or ("bp1" in rec and "ltp" not in rec):
            book = from_kotak_depth(rec)
            bids, asks = book.get("bids", []), book.get("asks", [])
            ticks.append(
                {
                    **base,
                    "kind": "depth",
                    "ltp": 0.0,
                    "volume": 0,
                    "bid": _num(bids[0]["price"]) if bids else 0.0,
                    "ask": _num(asks[0]["price"]) if asks else 0.0,
                    "oi": 0,
                    "timestamp": "",
                    "depth": book,
                }
            )
        else:
            ticks.append(
                {
                    **base,
                    "kind": "quote",
                    "ltp": _num(_fv(rec, "ltp", STOCK_FEED_KEYS)),
                    "volume": int(_num(_fv(rec, "v", STOCK_FEED_KEYS))),
                    "bid": _num(_fv(rec, "bp", STOCK_FEED_KEYS)),
                    "ask": _num(_fv(rec, "sp", STOCK_FEED_KEYS)),
                    # Best bid/ask size at level 1: NEO's SDK ``stock_key_mapping``
                    # keys these ``bq``/``sq`` (NOT ``bs`` — that is a depth-frame
                    # offer-size key), so the long-name fallback resolves them too.
                    "buy_quantity": int(_num(_fv(rec, "bq", STOCK_FEED_KEYS))),
                    "sell_quantity": int(_num(_fv(rec, "sq", STOCK_FEED_KEYS))),
                    "oi": int(_num(_fv(rec, "oi", STOCK_FEED_KEYS))),
                    "timestamp": str(_fv(rec, "ltt", STOCK_FEED_KEYS, "") or ""),
                }
            )
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
